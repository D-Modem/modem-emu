"""TMS320C25 instruction-level emulator.

Written from the TI "Second-Generation TMS320 User's Guide" (SPRU014, 1987).
The instruction behaviour was checked against the MAME ``tms32025.cpp`` core
(refer to ``docs/cores/c25.md``). It runs the ZyXEL Elite DSP programs.

Usage: ``e = C25(prog_words); e.inp[port] = fn; e.out[port] = fn``.

The core has the MP/MC pin (``e.mp_mc``) and the 4K-word on-chip mask ROM
(``e.rom``). When ``mp_mc`` is 1 (microprocessor mode), program addresses
0x0000-0x0FFF are external (``e.pm``). When it is 0 (microcomputer mode),
they are the on-chip ROM. The pin is not latched, so a test can change it
at any time, as on the real chip.
"""
import struct

M32 = 0xFFFFFFFF


def s16(x):
    """Return the 16-bit value as a signed integer."""
    x &= 0xFFFF
    return x - 0x10000 if x & 0x8000 else x


def s32(x):
    """Return the 32-bit value as a signed integer."""
    x &= M32
    return x - 0x100000000 if x & 0x80000000 else x


def _cycle_table():
    """Return the cycle count of each instruction, by the high byte (0xCE and 0xDx have their own rules).

    The counts are for on-chip program and data memory, with no wait states.
    They are the same as the MAME core. They are approximate for some
    instructions (refer to ``docs/cores/c25.md``).
    """
    t = [1] * 256
    t[0x58] = 3
    for h in [0x59, 0x5C, 0x5D, 0x5E, 0x5F] + list(range(0x80, 0x90)) + list(range(0xE0, 0x100)) + \
            list(range(0xD0, 0xE0)):
        t[h] = 2
    return t


CYCLES = _cycle_table()
CE_CYCLES = {0x1E: 2, 0x1F: 3, 0x24: 2, 0x25: 2, 0x26: 2}


class Halt(Exception):
    """The core found an opcode that it does not know."""


class C25:
    """One TMS320C25 core: program memory, data memory, registers and I/O ports."""

    def __init__(s, prog, rom=None, mp_mc=1):
        """Make a core in the reset state.

        prog: the external program words, from program address 0.
        rom: the on-chip mask ROM words (at most 4096), or None for an empty ROM.
        mp_mc: the level of the MP/MC pin (1 = external memory at 0x0000-0x0FFF).
        """
        s.pm = [0] * 0x10000
        for i, w in enumerate(prog):
            s.pm[i] = w
        s.rom = [0] * 0x1000
        for i, w in enumerate(rom or []):
            s.rom[i] = w & 0xFFFF
        s.mp_mc = mp_mc
        s.xf_out = None     # fn(level, cycles) when XF changes
        s.dm = [0] * 0x10000
        s.b0 = [0] * 256
        s.acc = 0; s.p = 0; s.t = 0
        s.ar = [0] * 8; s.arp = 0; s.arb = 0; s.dp = 0
        s.ov = 0; s.ovm = 0; s.intm = 1; s.cnf = 0; s.tc = 0; s.sxm = 1
        s.c = 0; s.hm = 1; s.fsm = 0; s.xf = 0; s.fo = 0; s.txm = 0; s.pm_ = 0
        s.stack = [0] * 8   # index 0 is the top of the stack
        s.pc = 0; s.rpt = 0
        s.inp = {}; s.out = {}
        s.bio = lambda: True
        s.pending = []      # interrupt vectors pending
        s.idle = False
        s.cycles = 0
        s.trace = None
        s.dwatch = {}       # data address -> fn(addr,val,pc) on write

    # ---- memory
    def rd(s, a):
        """Read one data word. Block B0 replaces data addresses 0x200-0x2FF when CNF is 0."""
        a &= 0xFFFF
        if 0x200 <= a < 0x300 and not s.cnf:
            return s.b0[a - 0x200]
        if a == 4:
            return s.dm[4] & 0x3F
        return s.dm[a]

    def wr(s, a, v):
        """Write one data word, and call a data watch for that address if there is one."""
        a &= 0xFFFF; v &= 0xFFFF
        if a in s.dwatch:
            s.dwatch[a](a, v, s.pc)
        if 0x200 <= a < 0x300 and not s.cnf:
            s.b0[a - 0x200] = v; return
        s.dm[a] = v

    def prd(s, a):
        """Read one program word.

        Block B0 replaces program addresses 0xFF00-0xFFFF when CNF is 1. The
        on-chip ROM replaces addresses 0x0000-0x0FFF when MP/MC is 0.
        """
        a &= 0xFFFF
        if a >= 0xFF00 and s.cnf:
            return s.b0[a - 0xFF00]
        if a < 0x1000 and not s.mp_mc:
            return s.rom[a]
        return s.pm[a]

    def pwr(s, a, v):
        """Write one program word. A write to the on-chip ROM has no effect."""
        a &= 0xFFFF
        if a >= 0xFF00 and s.cnf:
            s.b0[a - 0xFF00] = v & 0xFFFF
        elif a < 0x1000 and not s.mp_mc:
            return
        else:
            s.pm[a] = v & 0xFFFF

    # ---- status words
    def st0(s):
        """Return status register ST0."""
        return (s.arp << 13) | (s.ov << 12) | (s.ovm << 11) | 0x400 | (s.intm << 9) | s.dp

    def st1(s):
        """Return status register ST1."""
        return (s.arb << 13) | (s.cnf << 12) | (s.tc << 11) | (s.sxm << 10) | (s.c << 9) | 0x180 | \
            (s.hm << 6) | (s.fsm << 5) | (s.xf << 4) | (s.fo << 3) | (s.txm << 2) | s.pm_

    def lst0(s, v):
        """Load status register ST0."""
        s.arp = v >> 13; s.ov = (v >> 12) & 1; s.ovm = (v >> 11) & 1; s.dp = v & 0x1FF

    def lst1(s, v):
        """Load status register ST1."""
        s.arb = v >> 13; s.arp = s.arb; s.cnf = (v >> 12) & 1; s.tc = (v >> 11) & 1
        s.sxm = (v >> 10) & 1; s.c = (v >> 9) & 1; s.hm = (v >> 6) & 1; s.fsm = (v >> 5) & 1
        s.xf = (v >> 4) & 1; s.fo = (v >> 3) & 1; s.txm = (v >> 2) & 1; s.pm_ = v & 3

    # ---- operand address
    def ea(s, l, keep_arp=False):
        """Return the effective data address for the low byte l, and apply the AR changes.

        keep_arp: do not apply the next-ARP field (LST, LST1, SST and SST1 do not use it).
        """
        if not l & 0x80:
            return (s.dp << 7) | (l & 0x7F)
        a = s.ar[s.arp]
        m = (l >> 4) & 7
        cur = s.arp
        if m == 1: s.ar[cur] = (a - 1) & 0xFFFF
        elif m == 2: s.ar[cur] = (a + 1) & 0xFFFF
        elif m == 5: s.ar[cur] = (a - s.ar[0]) & 0xFFFF
        elif m == 6: s.ar[cur] = (a + s.ar[0]) & 0xFFFF
        elif m in (4, 7):
            s.ar[cur] = s.brev(a, s.ar[0], m == 7)
        if l & 8 and not keep_arp:
            s.arb = s.arp; s.arp = l & 7
        return a

    @staticmethod
    def brev(a, n, add):
        """Add or subtract in bit-reversed order (the bit-reversed addressing modes)."""
        def rev(x):
            """Reverse the 16 bits of the value."""
            return int('{:016b}'.format(x & 0xFFFF)[::-1], 2)
        r = rev(a); k = rev(n)
        r = (r + k) if add else (r - k)
        return rev(r & 0xFFFF)

    # ---- accumulator helpers
    def ext(s, v):
        """Extend a 16-bit operand with the sign when SXM is 1."""
        return s16(v) if s.sxm else (v & 0xFFFF)

    def setacc_add(s, a, b):
        """Set the accumulator to a + b, with carry and overflow."""
        r = a + b
        s.c = 1 if ((a & M32) + (b & M32)) > M32 else 0
        s._ovf(r)

    def setacc_sub(s, a, b):
        """Set the accumulator to a - b, with carry and overflow."""
        r = a - b
        s.c = 0 if (a & M32) < (b & M32) else 1
        s._ovf(r)

    def _ovf(s, r):
        """Set OV for a result out of range, saturate it when OVM is 1, and store it."""
        if r > 0x7FFFFFFF or r < -0x80000000:
            s.ov = 1
            if s.ovm:
                r = 0x7FFFFFFF if r > 0 else -0x80000000
        s.acc = s32(r)

    def pshift(s):
        """Return the P register shifted by the product shift mode (PM)."""
        p = s32(s.p)
        return [p, p << 1, p << 4, p >> 6][s.pm_]

    def push(s, v):
        """Push a word on the 8-level hardware stack. The bottom word is lost."""
        s.stack = [v & 0xFFFF] + s.stack[:7]

    def pop(s):
        """Pop a word from the hardware stack. The bottom word is copied up, as on the chip."""
        v = s.stack[0]
        s.stack = s.stack[1:] + [s.stack[7]]
        return v

    # ---- interrupts
    VEC = {'RS': 0, 'INT0': 2, 'INT1': 4, 'INT2': 6, 'TINT': 0x18, 'RINT': 0x1A, 'XINT': 0x1C}
    BIT = {'INT0': 1, 'INT1': 2, 'INT2': 4, 'TINT': 8, 'RINT': 16, 'XINT': 32}

    def irq(s, name):
        """Make an interrupt pending."""
        s.pending.append(name)

    def take_irq(s):
        """Start the first pending interrupt that IMR enables, if INTM permits it."""
        if s.intm or s.rpt:
            return False
        for n in list(s.pending):
            if s.rd(4) & s.BIT[n]:
                s.pending.remove(n)
                s.push(s.pc); s.pc = s.VEC[n]; s.intm = 1; s.idle = False
                return True
        return False

    # ---- run
    def run(s, n):
        """Run a number of steps, and start pending interrupts between them."""
        for _ in range(n):
            if s.take_irq():
                pass
            if s.idle:
                s.cycles += 1
                continue
            s.step()

    def step(s):
        """Execute one instruction, or one instruction with its RPT repeat count."""
        pc = s.pc
        x = s.prd(pc)
        if s.trace:
            s.trace(pc)
        s.pc = (pc + 1) & 0xFFFF
        if s.rpt:
            cnt = s.rpt - 1; s.rpt = 0
            nx = s.pc
            if (x >> 8) in (0x5C, 0x5D):  # MAC/MACD with pma increment
                pma = s.prd(nx); s.pc = nx + 1
                for _ in range(cnt + 1):
                    s.mac(x, pma); pma += 1
                return
            if (x >> 8) == 0xFC or (x >> 8) == 0xFD:
                src = s.prd(nx); s.pc = nx + 1
                for _ in range(cnt + 1):
                    s.blk(x, src); src += 1
                return
            if (x >> 8) == 0x58 or (x >> 8) == 0x59:  # TBLR/TBLW: the PFC counts, ACC does not change
                pfc = s.acc & 0xFFFF
                for _ in range(cnt + 1):
                    s.exe(x, pc, pfc=pfc); pfc = (pfc + 1) & 0xFFFF
                return
            if x == 0x5500:     # RPT of NOP: only the time changes
                s.cycles += cnt + 1
                return
            for _ in range(cnt + 1):
                s.pc = nx
                s.exe(x, pc)
            return
        s.exe(x, pc)

    def mac(s, x, pma):
        """Do one MAC or MACD step with the given program-memory operand address."""
        l = x & 0xFF
        a = s.ea(l)
        s.setacc_add(s.acc, s.pshift())
        d = s.rd(a)
        s.t = d
        s.p = s32(s16(d) * s16(s.prd(pma)))
        if (x >> 8) == 0x5C:
            s.wr(a + 1, d)

    def blk(s, x, src):
        """Do one BLKP or BLKD block-move step from the given source address."""
        l = x & 0xFF
        a = s.ea(l)
        if (x >> 8) == 0xFC:
            s.wr(a, s.prd(src))
        else:
            s.wr(a, s.rd(src))

    def exe(s, x, pc, pfc=None):
        """Decode and execute one instruction word.

        pfc: the program address for TBLR and TBLW in a repeat (None = the low word of ACC).
        """
        h = x >> 8; l = x & 0xFF
        s.cycles += CE_CYCLES.get(l, 1) if h == 0xCE else CYCLES[h]
        # branches
        if h in (0xFF, 0xFE, 0xFB, 0xF9, 0xF8, 0xF4, 0xF1, 0xFA, 0xF2, 0xF3, 0xF7, 0xF5, 0xF0, 0xF6, 0x5E, 0x5F) and \
                not (h == 0x5E and False):
            tgt = s.prd(s.pc); s.pc = (s.pc + 1) & 0xFFFF
            if h == 0xFB:
                cond = s.ar[s.arp] != 0
            else:
                a = s.acc
                cond = {0xFF: True, 0xFE: True, 0xF9: s.tc == 1, 0xF8: s.tc == 0, 0xF4: a >= 0, 0xF1: a > 0,
                        0xFA: s.bio(), 0xF2: a <= 0, 0xF3: a < 0, 0xF7: s.ov == 0, 0xF5: a != 0,
                        0xF0: s.ov == 1, 0xF6: a == 0, 0x5E: s.c == 1, 0x5F: s.c == 0}[h]
                if (h == 0xF0 and cond) or (h == 0xF7 and not cond):
                    s.ov = 0    # BV and BNV clear OV when OV was 1
            if l & 0x80:
                s.ea(l)
            if cond:
                if h == 0xFE:
                    s.push(s.pc)
                s.pc = tgt
            return
        if h in (0xFC, 0xFD):
            src = s.prd(s.pc); s.pc += 1
            s.blk(x, src); return
        if h < 0x10:
            a = s.ea(l); s.setacc_add(s.acc, s.ext(s.rd(a)) << h); return
        if h < 0x20:
            a = s.ea(l); s.setacc_sub(s.acc, s.ext(s.rd(a)) << (h & 15)); return
        if h < 0x30:
            a = s.ea(l); s.acc = s32(s.ext(s.rd(a)) << (h & 15)); return
        if h < 0x38:
            a = s.ea(l); s.ar[h & 7] = s.rd(a); return
        if h < 0x40:
            op = h - 0x38; a = s.ea(l); d = s.rd(a)
            if op == 0: s.p = s32(s16(s.t) * s16(d))
            elif op == 1:  # SQRA
                s.setacc_add(s.acc, s.pshift()); s.t = d; s.p = s32(s16(d) * s16(d))
            elif op == 2:  # MPYA
                s.setacc_add(s.acc, s.pshift()); s.p = s32(s16(s.t) * s16(d))
            elif op == 3:  # MPYS
                s.setacc_sub(s.acc, s.pshift()); s.p = s32(s16(s.t) * s16(d))
            elif op == 4: s.t = d
            elif op == 5: s.t = d; s.setacc_add(s.acc, s.pshift())
            elif op == 6: s.t = d; s.acc = s32(s.pshift())
            elif op == 7: s.t = d; s.setacc_add(s.acc, s.pshift()); s.wr(a + 1, d)
            return
        if h < 0x50:
            op = h - 0x40; a = s.ea(l); d = s.rd(a)
            if op == 0: s.acc = s32(d << 16)
            elif op == 1: s.acc = d
            elif op == 2: s.acc = s32(s.ext(d) << (s.t & 15))
            elif op == 3: s.setacc_add(s.acc, d + s.c)
            elif op == 4:  # SUBH: a borrow clears C, else C does not change
                c0 = s.c; s.setacc_sub(s.acc, d << 16); s.c = s.c & c0
            elif op == 5: s.setacc_sub(s.acc, d)
            elif op == 6: s.setacc_sub(s.acc, s.ext(d) << (s.t & 15))
            elif op == 7:  # SUBC: OV and C change, OVM has no effect
                sub = s32(d << 15); r = s.acc - sub
                if r > 0x7FFFFFFF or r < -0x80000000:
                    s.ov = 1
                s.c = 0 if (s.acc & M32) < (sub & M32) else 1
                if (s.acc & M32) >= (sub & M32):
                    s.acc = s32((r << 1) | 1)
                else:
                    s.acc = s32(s.acc << 1)
            elif op == 8:  # ADDH: a carry sets C, else C does not change
                c0 = s.c; s.setacc_add(s.acc, d << 16); s.c = s.c | c0
            elif op == 9: s.setacc_add(s.acc, d)
            elif op == 10: s.setacc_add(s.acc, s.ext(d) << (s.t & 15))
            elif op == 11: s.rpt = (d & 0xFF) + 1
            elif op == 12: s.acc = s32((s.acc & 0xFFFF0000) | ((s.acc ^ d) & 0xFFFF))
            elif op == 13: s.acc = s32((s.acc & 0xFFFF0000) | ((s.acc | d) & 0xFFFF))
            elif op == 14: s.acc = s.acc & d
            elif op == 15: s.setacc_sub(s.acc, d + (1 - s.c))
            return
        if h == 0x55 and l & 0x80 and (l & 0xF8) == 0x88:
            s.arb = s.arp; s.arp = l & 7; return
        if h in (0x5C, 0x5D):
            pma = s.prd(s.pc); s.pc += 1; s.mac(x, pma); return
        if h < 0x5E:
            op = h - 0x50; a = s.ea(l, keep_arp=h in (0x50, 0x51))
            if op == 0: v = s.rd(a); intm = s.intm; s.lst0(v)
            elif op == 1: s.lst1(s.rd(a))
            elif op == 2: s.dp = s.rd(a) & 0x1FF
            elif op == 3: s.p = s32((s.p & 0xFFFF) | (s.rd(a) << 16))
            elif op == 4: s.push(s.rd(a))
            elif op == 5: pass
            elif op == 6: s.wr(a + 1, s.rd(a))
            elif op == 7: s.tc = (s.rd(a) >> (15 - (s.t & 15))) & 1
            elif op == 8:
                s.wr(a, s.prd(s.acc & 0xFFFF if pfc is None else pfc))
            elif op == 9:
                s.pwr(s.acc & 0xFFFF if pfc is None else pfc, s.rd(a))
            elif op == 10:  # SQRS
                d = s.rd(a); s.setacc_sub(s.acc, s.pshift()); s.t = d; s.p = s32(s16(d) * s16(d))
            elif op == 11:
                s.t = s.rd(a); s.setacc_sub(s.acc, s.pshift())
            return
        if h < 0x68:
            a = s.ea(l); s.wr(a, (s.acc << (h & 7)) & 0xFFFF); return
        if h < 0x70:
            a = s.ea(l); s.wr(a, ((s.acc << (h & 7)) >> 16) & 0xFFFF); return
        if h < 0x78:
            v = s.ar[h & 7]; a = s.ea(l); s.wr(a, v); return
        if h < 0x7E:
            op = h - 0x78
            if op == 0: v = s.st0(); a = (l & 0x7F) if not l & 0x80 else s.ea(l, True); s.wr(a, v)
            elif op == 1: v = s.st1(); a = (l & 0x7F) if not l & 0x80 else s.ea(l, True); s.wr(a, v)
            elif op == 2: a = s.ea(l); s.wr(a, s.pop())
            elif op == 3: a = s.ea(l); s.acc = s32((s.rd(a) << 16) | 0x8000)
            elif op == 4: a = s.ea(l); s.wr(a, s.pshift() & 0xFFFF)
            elif op == 5: a = s.ea(l); s.wr(a, (s.pshift() >> 16) & 0xFFFF)
            return
        if h == 0x7E: s.ar[s.arp] = (s.ar[s.arp] + l) & 0xFFFF; return
        if h == 0x7F: s.ar[s.arp] = (s.ar[s.arp] - l) & 0xFFFF; return
        if h < 0x90:
            a = s.ea(l); f = s.inp.get(h & 15)
            s.wr(a, f(pc) if f else 0); return
        if h < 0xA0:
            a = s.ea(l); s.tc = (s.rd(a) >> (15 - (h & 15))) & 1; return
        if h < 0xC0:
            k = x & 0x1FFF; k = k - 0x2000 if k & 0x1000 else k
            s.p = s32(s16(s.t) * k); return
        if h < 0xC8: s.ar[h & 7] = l; return
        if h < 0xCA: s.dp = x & 0x1FF; return
        if h == 0xCA: s.acc = l; return
        if h == 0xCB: s.rpt = l + 1; return
        if h == 0xCC: s.setacc_add(s.acc, l); return
        if h == 0xCD: s.setacc_sub(s.acc, l); return
        if h == 0xCF:
            a = s.ea(l); s.p = s32((s.t & 0xFFFF) * s.rd(a)); return
        if h == 0xCE:
            s.ce(l); return
        if 0xD0 <= h <= 0xDF:
            k = s.prd(s.pc); s.pc += 1; sh = h & 15
            if l == 0: s.ar[h & 7] = k; return
            if l == 1: s.acc = s32(s.ext(k) << sh); return
            if l == 2: s.setacc_add(s.acc, s.ext(k) << sh); return
            if l == 3: s.setacc_sub(s.acc, s.ext(k) << sh); return
            if l == 4: s.acc = s32(s.acc & ((k << sh) & M32)); return
            if l == 5: s.acc = s32(s.acc | ((k << sh) & M32)); return
            if l == 6: s.acc = s32(s.acc ^ ((k << sh) & M32)); return
        if 0xE0 <= h < 0xF0:
            a = s.ea(l); f = s.out.get(h & 15)
            if f: f(s.rd(a), pc)
            return
        raise Halt('bad opcode %04x at %04x' % (x, pc))

    def ce(s, l):
        """Execute one instruction of the 0xCE group (control, accumulator and status operations)."""
        if l == 0: s.intm = 0
        elif l == 1: s.intm = 1
        elif l == 2: s.ovm = 0
        elif l == 3: s.ovm = 1
        elif l == 4: s.cnf = 0
        elif l == 5: s.cnf = 1
        elif l == 6: s.sxm = 0
        elif l == 7: s.sxm = 1
        elif 8 <= l <= 0xB: s.pm_ = l - 8
        elif l in (0xC, 0xD):
            s.xf = l - 0xC
            if s.xf_out:
                s.xf_out(s.xf, s.cycles)
        elif l in (0xE, 0xF): s.fo = l - 0xE
        elif l == 0x14: s.acc = s32(s.pshift())
        elif l == 0x15: s.setacc_add(s.acc, s.pshift())
        elif l == 0x16: s.setacc_sub(s.acc, s.pshift())
        elif l == 0x18: s.c = (s.acc >> 31) & 1; s.acc = s32(s.acc << 1)
        elif l == 0x19:
            s.c = s.acc & 1
            s.acc = (s.acc >> 1) if s.sxm else ((s.acc & M32) >> 1)
            s.acc = s32(s.acc)
        elif l == 0x1B:  # ABS clears C
            if s.acc == -0x80000000:
                s.ov = 1; s.acc = 0x7FFFFFFF if s.ovm else s.acc
            else: s.acc = abs(s.acc)
            s.c = 0
        elif l == 0x1C: s.push(s.acc & 0xFFFF)
        elif l == 0x1D: s.acc = s.pop()
        elif l == 0x1E: s.push(s.pc); s.pc = 0x1E
        elif l == 0x1F: s.idle = True; s.intm = 0
        elif l in (0x20, 0x21): s.txm = l - 0x20
        elif l == 0x23: s.setacc_sub(0, s.acc)
        elif l == 0x24: s.push(s.pc); s.pc = s.acc & 0xFFFF
        elif l == 0x25: s.pc = s.acc & 0xFFFF
        elif l == 0x26: s.pc = s.pop()
        elif l == 0x27: s.acc = s32(~s.acc)
        elif l in (0x30, 0x31): s.c = l - 0x30
        elif l in (0x32, 0x33): s.tc = l - 0x32
        elif l == 0x34:
            c = s.c; s.c = (s.acc >> 31) & 1; s.acc = s32((s.acc << 1) | c)
        elif l == 0x35:
            c = s.c; s.c = s.acc & 1; s.acc = s32(((s.acc & M32) >> 1) | (c << 31))
        elif l in (0x36, 0x37): s.fsm = l - 0x36
        elif l in (0x38, 0x39): s.hm = l - 0x38
        elif 0x3C <= l <= 0x3F: pass   # CONF is a TMS320C26 instruction; no effect on the C25
        elif 0x50 <= l <= 0x53:
            a = s.ar[s.arp]; b = s.ar[0]
            s.tc = int([a == b, a < b, a > b, a != b][l - 0x50])
        elif l & 0x80 and l & 0x0F == 2:  # NORM
            if s.acc != 0 and ((s.acc >> 31) & 1) == ((s.acc >> 30) & 1):
                s.tc = 0; s.acc = s32(s.acc << 1); s.ea(l)
            else:
                s.tc = 1
        else:
            raise Halt('bad CE %02x at %04x' % (l, s.pc - 1))


def load_words(path):
    """Read a binary file as big-endian 16-bit program words."""
    d = open(path, 'rb').read()
    return list(struct.unpack('>%dH' % (len(d) // 2), d))
