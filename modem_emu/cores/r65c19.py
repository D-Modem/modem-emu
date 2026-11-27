"""Rockwell R65C19 / C29 / C39 instruction-level emulator.

Written from the Rockwell "R65C19 Microcomputer" data sheet (1992) and the
"C29/C39 Technical Reference Manual" (both on bitsavers, under
``components/rockwell``). The instruction behaviour was checked against the
MAME ``r65c19.cpp`` core (BSD-3-Clause, refer to ``docs/cores/r65c19.md``).

The Rockwell modem controllers use this CPU. It is a 65C02 with these
changes:

- ``(zp,X)`` becomes ``(zp)`` and ``(zp),Y`` becomes ``(zp),X``.
- JSR pushes the address of the next opcode, and RTS does not add 1.
- New registers W (16-bit accumulator for MPY/MPA/RND) and I (16-bit
  pointer for the threaded-code instructions).
- New instructions: MPY, MPA, RND, TAW, TWA, CLW, PHW, PLW, PSH, PUL, NEG,
  ASR, LAB, EXC, ADD, STI, RBA, SBA, BAR, BAS, JSB, JMP (abs,X), and the
  threaded-code set NXT, LII, LAI, LAN, INI, PHI, PLI, PIA, JPI, TIP.
- TSB, TRB, STZ, WAI, STP, BIT #imm, BIT zp,X, BIT abs,X, INC A and DEC A
  are not present.

Usage::

    cpu = R65C19(read, write)   # read(addr) -> byte, write(addr, byte)
    cpu.reset()
    cycles = cpu.step()

The board gives the memory map through ``read`` and ``write``. For a C39,
``C39Banks`` does the bank select translation of the chip.
"""
from __future__ import annotations

F_C, F_Z, F_I, F_D, F_B, F_E, F_V, F_N = 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80

VEC_IRQ6, VEC_IRQ5, VEC_IRQ4, VEC_IRQ3, VEC_IRQ2, VEC_IRQ1 = 0xFFF0, 0xFFF2, 0xFFF4, 0xFFF6, 0xFFF8, 0xFFFA
VEC_NMI, VEC_RESET = 0xFFFC, 0xFFFE
VEC_JSB = 0xFFE0


def irq_vector(number: int) -> int:
    """Return the ROM vector address of IRQ ``number`` (1 = highest priority, at $FFFA)."""
    if not 1 <= number <= 6:
        raise ValueError("IRQ number must be 1 to 6")
    return 0xFFF0 + 2 * (6 - number)


def s8(v: int) -> int:
    """Return the byte as a signed integer."""
    v &= 0xFF
    return v - 0x100 if v & 0x80 else v


def s16(v: int) -> int:
    """Return the 16-bit value as a signed integer."""
    v &= 0xFFFF
    return v - 0x10000 if v & 0x8000 else v


# The opcode map, one row of 16 opcodes for each high nibble. Each cell is
# "mnemonic mode". The modes are listed in MODE_BYTES.
_MAP = """
brk imp|ora zpi|mpy imp|tip imp|nop zp|ora zp|asl zp|rmb0 zp|php imp|ora imm|asl acc|jsb0 imp|jpi abs|ora abs|asl abs|bbr0 zpr
bpl rel|ora ipx|mpa imp|lab acc|nop zpx|ora zpx|asl zpx|rmb1 zp|clc imp|ora aby|neg acc|jsb1 imp|nop abx|ora abx|asl abx|bbr1 zpr
jsr abs|and zpi|psh imp|phw imp|bit zp|and zp|rol zp|rmb2 zp|plp imp|and imm|rol acc|jsb2 imp|bit abs|and abs|rol abs|bbr2 zpr
bmi rel|and ipx|pul imp|plw imp|nop zpx|and zpx|rol zpx|rmb3 zp|sec imp|and aby|asr acc|jsb3 imp|nop abx|and abx|rol abx|bbr3 zpr
rti imp|eor zpi|rnd imp|nop1 imp|nop zp|eor zp|lsr zp|rmb4 zp|pha imp|eor imm|lsr acc|jsb4 imp|jmp abs|eor abs|lsr abs|bbr4 zpr
bvc rel|eor ipx|clw imp|nop1 imp|nop zpx|eor zpx|lsr zpx|rmb5 zp|cli imp|eor aby|phy imp|jsb5 imp|nop abx|eor abx|lsr abx|bbr5 zpr
rts imp|adc zpi|taw imp|nop1 imp|add zp|adc zp|ror zp|rmb6 zp|pla imp|adc imm|ror acc|jsb6 imp|jmp ind|adc abs|ror abs|bbr6 zpr
bvs rel|adc ipx|twa imp|nop1 imp|add zpx|adc zpx|ror zpx|rmb7 zp|sei imp|adc aby|ply imp|jsb7 imp|jmp iax|adc abx|ror abx|bbr7 zpr
bra rel|sta zpi|nop imm|nop1 imp|sty zp|sta zp|stx zp|smb0 zp|dey imp|add imm|txa imp|nxt imp|sty abs|sta abs|stx abs|bbs0 zpr
bcc rel|sta ipx|nop imm|nop1 imp|sty zpx|sta zpx|stx zpy|smb1 zp|tya imp|sta aby|txs imp|lii imp|nop abx|sta abx|nop abx|bbs1 zpr
ldy imm|lda zpi|ldx imm|nop1 imp|ldy zp|lda zp|ldx zp|smb2 zp|tay imp|lda imm|tax imp|lan imp|ldy abs|lda abs|ldx abs|bbs2 zpr
bcs rel|lda ipx|sti imz|nop1 imp|ldy zpx|lda zpx|ldx zpy|smb3 zp|clv imp|lda aby|tsx imp|ini imp|ldy abx|lda abx|ldx aby|bbs3 zpr
cpy imm|cmp zpi|rba ima|nop1 imp|cpy zp|cmp zp|dec zp|smb4 zp|iny imp|cmp imm|dex imp|phi imp|cpy abs|cmp abs|dec abs|bbs4 zpr
bne rel|cmp ipx|sba ima|nop1 imp|exc zpx|cmp zpx|dec zpx|smb5 zp|cld imp|cmp aby|phx imp|pli imp|nop abx|cmp abx|dec abx|bbs5 zpr
cpx imm|sbc zpi|bar amr|nop1 imp|cpx zp|sbc zp|inc zp|smb6 zp|inx imp|sbc imm|nop imp|lai imp|cpx abs|sbc abs|inc abs|bbs6 zpr
beq rel|sbc ipx|bas amr|nop1 imp|nop zpx|sbc zpx|inc zpx|smb7 zp|sed imp|sbc aby|plx imp|pia imp|nop abx|sbc abx|inc abx|bbs7 zpr
"""


def _opcode_map() -> list[tuple[str, str]]:
    """Return the (mnemonic, mode) pair of each of the 256 opcodes."""
    rows = [r for r in _MAP.strip().splitlines()]
    out = []
    for row in rows:
        cells = row.split("|")
        assert len(cells) == 16
        for cell in cells:
            mn, mode = cell.split()
            out.append((mn, mode))
    assert len(out) == 256
    return out


OPCODES = _opcode_map()

# The number of bytes of each mode, with the opcode.
MODE_BYTES = {
    "imp": 1, "acc": 1, "imm": 2, "zp": 2, "zpx": 2, "zpy": 2, "zpi": 2, "ipx": 2, "rel": 2,
    "abs": 3, "abx": 3, "aby": 3, "ind": 3, "iax": 3, "zpr": 3, "imz": 3, "ima": 4, "amr": 5,
}


def _base_cycles(mn: str, mode: str) -> int:
    """Return the base cycle count of one instruction (no page crossing, no branch, binary mode).

    The counts come from the R65C19 data sheet (table A-3 and the new
    instruction tables) and the 65C02 rules. They are not exact for all
    bus cycles. They are good enough for the timers of a board model.
    """
    new = {
        "asr": 2, "clw": 2, "exc": 5, "lab": 2, "mpa": 6, "mpy": 6, "psh": 5, "pul": 6, "rnd": 2,
        "taw": 2, "twa": 2, "neg": 2, "phw": 4, "plw": 5, "nxt": 4, "lii": 5, "lai": 3, "ini": 3,
        "phi": 4, "pli": 6, "jpi": 5, "tip": 2, "pia": 6, "lan": 3, "bar": 7, "bas": 7, "sti": 4,
        "rba": 7, "sba": 7, "brk": 7, "rti": 6, "rts": 5, "jsr": 5, "php": 3, "pha": 3, "phx": 3,
        "phy": 3, "plp": 4, "pla": 4, "plx": 4, "ply": 4, "nop1": 1,
    }
    if mn.startswith("jsb"):
        return 6
    if mn.startswith(("rmb", "smb")):
        return 5
    if mn.startswith(("bbr", "bbs")):
        return 5
    if mn in new:
        return new[mn]
    if mn == "jmp":
        return {"abs": 3, "ind": 5, "iax": 6}[mode]
    if mode == "rel":
        return 3 if mn == "bra" else 2
    rmw = mn in ("asl", "rol", "lsr", "ror", "inc", "dec")
    if rmw:
        return {"acc": 2, "zp": 5, "zpx": 6, "abs": 6, "abx": 7}[mode]
    store = mn in ("sta", "stx", "sty")
    table = {
        "imp": 2, "acc": 2, "imm": 2, "zp": 3, "zpx": 4, "zpy": 4, "abs": 4, "abx": 4, "aby": 4,
        "zpi": 5, "ipx": 5,
    }
    c = table[mode]
    if store and mode in ("abx", "aby", "ipx"):
        c += 1
    return c


CYCLES = [_base_cycles(mn, mode) for mn, mode in OPCODES]

# The instructions that take one more cycle when an indexed read crosses a page.
_PAGE_PENALTY = {"ora", "and", "eor", "adc", "sbc", "cmp", "lda", "ldx", "ldy", "bit", "nop"}


class R65C19:
    """One R65C19-family CPU core: the registers, the instruction set and the interrupt logic."""

    def __init__(self, read, write, brk_vector: int = VEC_NMI):
        """Make a core. Call ``reset()`` before ``step()``.

        read: fn(addr) -> byte, for the 16-bit CPU address space.
        write: fn(addr, byte).
        brk_vector: the vector that BRK uses. The C39 uses the NMI vector
            ($FFFC). The C29 uses the IRQ6 vector ($FFF0).
        """
        self.read = read
        self.write = write
        self.brk_vector = brk_vector
        self.a = self.x = self.y = 0
        self.s = 0xFF
        self.p = F_I | F_B | F_E
        self.pc = 0
        self.w = 0
        self.i = 0
        self.cycles = 0
        self.nmi_pending = False
        self.irq_vector_pending: int | None = None
        self._dispatch = [getattr(self, "_op_" + self._handler_name(mn)) for mn, _ in OPCODES]

    @staticmethod
    def _handler_name(mn: str) -> str:
        """Return the handler name for a mnemonic (the bit instructions share one handler)."""
        for prefix in ("rmb", "smb", "bbr", "bbs", "jsb"):
            if mn.startswith(prefix):
                return prefix
        return mn

    # ----- state -----

    def reset(self) -> None:
        """Do the RES sequence: set I, clear D, and load PC from $FFFE."""
        self.s = (self.s - 3) & 0xFF
        self.p = (self.p | F_I | F_B | F_E) & ~F_D
        self.pc = self.rd16(VEC_RESET)
        self.nmi_pending = False
        self.irq_vector_pending = None
        self.cycles += 7

    def nmi(self) -> None:
        """Latch an NMI. The core takes it before the next instruction."""
        self.nmi_pending = True

    def set_irq(self, vector: int | None) -> None:
        """Set the IRQ line. ``vector`` is the vector address of the highest pending IRQ, or None for no IRQ.

        The board (the IRQ logic of the chip) selects the vector: a ROM
        vector from ``irq_vector(n)``, or a page 1 RAM vector for the timers.
        """
        self.irq_vector_pending = vector

    def flag(self, f: int) -> bool:
        """Return True when the status flag ``f`` is set."""
        return bool(self.p & f)

    # ----- memory helpers -----

    def rd16(self, addr: int) -> int:
        """Read a little-endian word."""
        return self.read(addr & 0xFFFF) | (self.read((addr + 1) & 0xFFFF) << 8)

    def _fetch(self) -> int:
        """Read the byte at PC and increment PC."""
        v = self.read(self.pc)
        self.pc = (self.pc + 1) & 0xFFFF
        return v

    def _fetch16(self) -> int:
        """Read the word at PC and add 2 to PC."""
        lo = self._fetch()
        return lo | (self._fetch() << 8)

    def push(self, v: int) -> None:
        """Push a byte on the page 1 stack."""
        self.write(0x100 | self.s, v & 0xFF)
        self.s = (self.s - 1) & 0xFF

    def pull(self) -> int:
        """Pull a byte from the page 1 stack."""
        self.s = (self.s + 1) & 0xFF
        return self.read(0x100 | self.s)

    def push16(self, v: int) -> None:
        """Push a word, high byte first."""
        self.push(v >> 8)
        self.push(v)

    def pull16(self) -> int:
        """Pull a word, low byte first."""
        lo = self.pull()
        return lo | (self.pull() << 8)

    # ----- flags and ALU -----

    def _nz(self, v: int) -> int:
        """Set N and Z from the byte and return it."""
        v &= 0xFF
        self.p &= ~(F_N | F_Z)
        if v == 0:
            self.p |= F_Z
        elif v & 0x80:
            self.p |= F_N
        return v

    def _adc(self, v: int) -> None:
        """Add with carry. In decimal mode, use the BCD adder; N and Z come from the result."""
        a = self.a
        c = 1 if self.p & F_C else 0
        if self.p & F_D:
            self.p &= ~(F_N | F_V | F_Z | F_C)
            al = (a & 15) + (v & 15) + c
            if al > 9:
                al += 6
            ah = (a >> 4) + (v >> 4) + (1 if al > 15 else 0)
            if ~(a ^ v) & (a ^ ((ah << 4) & 0xFF)) & 0x80:
                self.p |= F_V
            if ah > 9:
                ah += 6
            if ah > 15:
                self.p |= F_C
            self.a = ((ah << 4) | (al & 15)) & 0xFF
            self._nz(self.a)
            self.cycles += 1
        else:
            r = a + v + c
            self.p &= ~(F_V | F_C)
            if ~(a ^ v) & (a ^ r) & 0x80:
                self.p |= F_V
            if r > 0xFF:
                self.p |= F_C
            self.a = self._nz(r)

    def _sbc(self, v: int) -> None:
        """Subtract with borrow. In decimal mode, use the 65C02 BCD rules; N and Z come from the result."""
        a = self.a
        b = 0 if self.p & F_C else 1
        diff = (a - v - b) & 0xFFFF
        self.p &= ~(F_V | F_C)
        if (a ^ v) & (a ^ diff) & 0x80:
            self.p |= F_V
        if not diff & 0xFF00:
            self.p |= F_C
        if self.p & F_D:
            al = (a & 15) - (v & 15) - b
            ah = (a >> 4) - (v >> 4) - (1 if al < 0 else 0)
            r = ((ah << 4) | (al & 15)) & 0xFF
            if al < 0:
                r = (r - 6) & 0xFF
            if ah < 0:
                r = (r - 0x60) & 0xFF
            self.a = self._nz(r)
            self.cycles += 1
        else:
            self.a = self._nz(diff)

    def _cmp(self, r: int, v: int) -> None:
        """Compare a register with a byte: set N, Z and C."""
        d = (r - v) & 0xFFFF
        self.p &= ~F_C
        if not d & 0xFF00:
            self.p |= F_C
        self._nz(d)

    def _accumulate(self, v: int, w: int) -> int:
        """Add two signed 16-bit values with saturation, as MPY, MPA and RND do.

        Set V on overflow and N for a negative result (Z does not change).
        Y gets the low byte of the result. Return the 16-bit result.
        """
        r = s16(v) + s16(w)
        self.p &= ~(F_N | F_V)
        if r > 32767:
            self.p |= F_V
            r = 32767
        elif r < 0:
            self.p |= F_N
            if r < -32768:
                self.p |= F_V
                r = -32768
        self.y = r & 0xFF
        return r & 0xFFFF

    # ----- addressing -----

    def _ea(self, mode: str) -> tuple[int, bool]:
        """Read the operand of a memory mode. Return the effective address and True if an index crossed a page."""
        if mode == "zp":
            return self._fetch(), False
        if mode == "zpx":
            return (self._fetch() + self.x) & 0xFF, False
        if mode == "zpy":
            return (self._fetch() + self.y) & 0xFF, False
        if mode == "abs":
            return self._fetch16(), False
        if mode in ("abx", "aby"):
            base = self._fetch16()
            ea = (base + (self.x if mode == "abx" else self.y)) & 0xFFFF
            return ea, (base ^ ea) & 0xFF00 != 0
        zp = self._fetch()
        ptr = self.read(zp) | (self.read((zp + 1) & 0xFF) << 8)
        if mode == "zpi":
            return ptr, False
        if mode == "ipx":
            ea = (ptr + self.x) & 0xFFFF
            return ea, (ptr ^ ea) & 0xFF00 != 0
        raise ValueError(mode)

    def _operand(self, mode: str, mn: str) -> int:
        """Return the operand byte of a read instruction (immediate or memory)."""
        if mode == "imm":
            return self._fetch()
        ea, crossed = self._ea(mode)
        if crossed and mn in _PAGE_PENALTY:
            self.cycles += 1
        return self.read(ea)

    def _branch(self, cond: bool, off: int) -> None:
        """Take a relative branch when ``cond`` is True (one more cycle, and one more for a page crossing)."""
        if cond:
            target = (self.pc + s8(off)) & 0xFFFF
            self.cycles += 1 + (1 if (target ^ self.pc) & 0xFF00 else 0)
            self.pc = target

    # ----- execution -----

    def _interrupt(self, vector: int, brk: bool) -> None:
        """Push PC and P, set I, clear D and jump through ``vector``."""
        self.push16(self.pc)
        self.push((self.p | F_E | F_B) if brk else ((self.p | F_E) & ~F_B))
        self.p = (self.p | F_I) & ~F_D
        self.pc = self.rd16(vector)
        self.cycles += 7

    def step(self) -> int:
        """Take a pending interrupt or do one instruction. Return the number of cycles used."""
        start = self.cycles
        if self.nmi_pending:
            self.nmi_pending = False
            self._interrupt(VEC_NMI, brk=False)
            return self.cycles - start
        if self.irq_vector_pending is not None and not self.p & F_I:
            self._interrupt(self.irq_vector_pending, brk=False)
            return self.cycles - start
        op = self._fetch()
        mn, mode = OPCODES[op]
        self.cycles += CYCLES[op]
        self._dispatch[op](op, mode)
        return self.cycles - start

    def run(self, max_cycles: int) -> int:
        """Do instructions until at least ``max_cycles`` cycles are used. Return the cycles used."""
        start = self.cycles
        while self.cycles - start < max_cycles:
            self.step()
        return self.cycles - start

    # ----- loads, stores, logic -----

    def _op_lda(self, op, mode):
        """LDA: load A."""
        self.a = self._nz(self._operand(mode, "lda"))

    def _op_ldx(self, op, mode):
        """LDX: load X."""
        self.x = self._nz(self._operand(mode, "ldx"))

    def _op_ldy(self, op, mode):
        """LDY: load Y."""
        self.y = self._nz(self._operand(mode, "ldy"))

    def _op_sta(self, op, mode):
        """STA: store A."""
        self.write(self._ea(mode)[0], self.a)

    def _op_stx(self, op, mode):
        """STX: store X."""
        self.write(self._ea(mode)[0], self.x)

    def _op_sty(self, op, mode):
        """STY: store Y."""
        self.write(self._ea(mode)[0], self.y)

    def _op_ora(self, op, mode):
        """ORA: OR memory into A."""
        self.a = self._nz(self.a | self._operand(mode, "ora"))

    def _op_and(self, op, mode):
        """AND: AND memory into A."""
        self.a = self._nz(self.a & self._operand(mode, "and"))

    def _op_eor(self, op, mode):
        """EOR: exclusive-OR memory into A."""
        self.a = self._nz(self.a ^ self._operand(mode, "eor"))

    def _op_adc(self, op, mode):
        """ADC: add memory and carry to A."""
        self._adc(self._operand(mode, "adc"))

    def _op_add(self, op, mode):
        """ADD: add memory to A without the carry (the carry is cleared first)."""
        v = self._operand(mode, "add")
        self.p &= ~F_C
        self._adc(v)

    def _op_sbc(self, op, mode):
        """SBC: subtract memory and borrow from A."""
        self._sbc(self._operand(mode, "sbc"))

    def _op_cmp(self, op, mode):
        """CMP: compare A with memory."""
        self._cmp(self.a, self._operand(mode, "cmp"))

    def _op_cpx(self, op, mode):
        """CPX: compare X with memory."""
        self._cmp(self.x, self._operand(mode, "cpx"))

    def _op_cpy(self, op, mode):
        """CPY: compare Y with memory."""
        self._cmp(self.y, self._operand(mode, "cpy"))

    def _op_bit(self, op, mode):
        """BIT: N and V from memory bits 7 and 6, Z from A AND memory."""
        v = self._operand(mode, "bit")
        self.p &= ~(F_N | F_V | F_Z)
        self.p |= v & (F_N | F_V)
        if not self.a & v:
            self.p |= F_Z

    def _op_nop(self, op, mode):
        """NOP: read the operand and do nothing (the operand length depends on the opcode)."""
        if mode == "imm":
            self._fetch()
        elif mode != "imp":
            self._operand(mode, "nop")

    def _op_nop1(self, op, mode):
        """NOP (one byte, one cycle): an unused opcode of column 3."""

    def _op_sti(self, op, mode):
        """STI #imm, zp: store an immediate byte into zero page."""
        v = self._fetch()
        self.write(self._fetch(), v)

    def _op_exc(self, op, mode):
        """EXC zp,X: exchange A with memory. The flags do not change."""
        ea = (self._fetch() + self.x) & 0xFF
        v = self.read(ea)
        self.write(ea, self.a)
        self.a = v

    # ----- read-modify-write -----

    def _rmw(self, mode, fn):
        """Do a read-modify-write: on A (mode acc) or on memory."""
        if mode == "acc":
            self.a = fn(self.a)
            return
        ea = self._ea(mode)[0]
        self.write(ea, fn(self.read(ea)))

    def _op_asl(self, op, mode):
        """ASL: shift left, bit 7 to C."""
        def f(v):
            self.p = (self.p & ~F_C) | (F_C if v & 0x80 else 0)
            return self._nz(v << 1)
        self._rmw(mode, f)

    def _op_lsr(self, op, mode):
        """LSR: shift right, bit 0 to C."""
        def f(v):
            self.p = (self.p & ~F_C) | (v & 1)
            return self._nz(v >> 1)
        self._rmw(mode, f)

    def _op_rol(self, op, mode):
        """ROL: rotate left through C."""
        def f(v):
            c = self.p & F_C
            self.p = (self.p & ~F_C) | (F_C if v & 0x80 else 0)
            return self._nz((v << 1) | c)
        self._rmw(mode, f)

    def _op_ror(self, op, mode):
        """ROR: rotate right through C."""
        def f(v):
            c = 0x80 if self.p & F_C else 0
            self.p = (self.p & ~F_C) | (v & 1)
            return self._nz((v >> 1) | c)
        self._rmw(mode, f)

    def _op_inc(self, op, mode):
        """INC: increment memory."""
        self._rmw(mode, lambda v: self._nz(v + 1))

    def _op_dec(self, op, mode):
        """DEC: decrement memory."""
        self._rmw(mode, lambda v: self._nz(v - 1))

    def _op_asr(self, op, mode):
        """ASR A: arithmetic shift right (bit 7 stays), bit 0 to C."""
        v = self.a
        self.p = (self.p & ~F_C) | (v & 1)
        self.a = self._nz((v >> 1) | (v & 0x80))

    def _op_neg(self, op, mode):
        """NEG A: two's complement of A."""
        self.a = self._nz(-self.a)

    def _op_lab(self, op, mode):
        """LAB A: absolute value of A ($80 stays $80)."""
        if self.a & 0x80:
            self.a = (-self.a) & 0xFF
        self._nz(self.a)

    # ----- register transfers and flags -----

    def _op_tax(self, op, mode):
        """TAX."""
        self.x = self._nz(self.a)

    def _op_tay(self, op, mode):
        """TAY."""
        self.y = self._nz(self.a)

    def _op_txa(self, op, mode):
        """TXA."""
        self.a = self._nz(self.x)

    def _op_tya(self, op, mode):
        """TYA."""
        self.a = self._nz(self.y)

    def _op_tsx(self, op, mode):
        """TSX."""
        self.x = self._nz(self.s)

    def _op_txs(self, op, mode):
        """TXS (no flags)."""
        self.s = self.x

    def _op_inx(self, op, mode):
        """INX."""
        self.x = self._nz(self.x + 1)

    def _op_iny(self, op, mode):
        """INY."""
        self.y = self._nz(self.y + 1)

    def _op_dex(self, op, mode):
        """DEX."""
        self.x = self._nz(self.x - 1)

    def _op_dey(self, op, mode):
        """DEY."""
        self.y = self._nz(self.y - 1)

    def _op_clc(self, op, mode):
        """CLC."""
        self.p &= ~F_C

    def _op_sec(self, op, mode):
        """SEC."""
        self.p |= F_C

    def _op_cli(self, op, mode):
        """CLI."""
        self.p &= ~F_I

    def _op_sei(self, op, mode):
        """SEI."""
        self.p |= F_I

    def _op_cld(self, op, mode):
        """CLD."""
        self.p &= ~F_D

    def _op_sed(self, op, mode):
        """SED."""
        self.p |= F_D

    def _op_clv(self, op, mode):
        """CLV."""
        self.p &= ~F_V

    # ----- stack -----

    def _op_pha(self, op, mode):
        """PHA."""
        self.push(self.a)

    def _op_phx(self, op, mode):
        """PHX."""
        self.push(self.x)

    def _op_phy(self, op, mode):
        """PHY."""
        self.push(self.y)

    def _op_php(self, op, mode):
        """PHP: push P with B and bit 5 set."""
        self.push(self.p | F_B | F_E)

    def _op_pla(self, op, mode):
        """PLA."""
        self.a = self._nz(self.pull())

    def _op_plx(self, op, mode):
        """PLX."""
        self.x = self._nz(self.pull())

    def _op_ply(self, op, mode):
        """PLY."""
        self.y = self._nz(self.pull())

    def _op_plp(self, op, mode):
        """PLP."""
        self.p = self.pull() | F_B | F_E

    def _op_psh(self, op, mode):
        """PSH: push A, X and Y."""
        self.push(self.a)
        self.push(self.x)
        self.push(self.y)

    def _op_pul(self, op, mode):
        """PUL: pull Y, X and A (no flags)."""
        self.y = self.pull()
        self.x = self.pull()
        self.a = self.pull()

    # ----- jumps and branches -----

    def _op_jmp(self, op, mode):
        """JMP abs, JMP (abs) and JMP (abs,X). The indirect forms have no page wrap bug."""
        addr = self._fetch16()
        if mode == "abs":
            self.pc = addr
        elif mode == "ind":
            self.pc = self.rd16(addr)
        else:
            self.pc = self.rd16((addr + self.x) & 0xFFFF)

    def _op_jsr(self, op, mode):
        """JSR: push the address of the next opcode (not minus 1) and jump."""
        addr = self._fetch16()
        self.push16(self.pc)
        self.pc = addr

    def _op_rts(self, op, mode):
        """RTS: pull PC (no increment)."""
        self.pc = self.pull16()

    def _op_rti(self, op, mode):
        """RTI: pull P and PC."""
        self.p = self.pull() | F_B | F_E
        self.pc = self.pull16()

    def _op_brk(self, op, mode):
        """BRK: push PC+1 and P (B set), then jump through the BRK vector."""
        self.pc = (self.pc + 1) & 0xFFFF
        self.cycles -= 7     # _interrupt adds the 7 cycles again
        self._interrupt(self.brk_vector, brk=True)

    def _op_jsb(self, op, mode):
        """JSB n: push PC and jump through the vector at $FFE0 + 2n."""
        self.push16(self.pc)
        self.pc = self.rd16(VEC_JSB + 2 * (op >> 4))

    def _op_bra(self, op, mode):
        """BRA: branch always."""
        self._branch(True, self._fetch())

    def _op_bpl(self, op, mode):
        """BPL."""
        self._branch(not self.p & F_N, self._fetch())

    def _op_bmi(self, op, mode):
        """BMI."""
        self._branch(bool(self.p & F_N), self._fetch())

    def _op_bvc(self, op, mode):
        """BVC."""
        self._branch(not self.p & F_V, self._fetch())

    def _op_bvs(self, op, mode):
        """BVS."""
        self._branch(bool(self.p & F_V), self._fetch())

    def _op_bcc(self, op, mode):
        """BCC."""
        self._branch(not self.p & F_C, self._fetch())

    def _op_bcs(self, op, mode):
        """BCS."""
        self._branch(bool(self.p & F_C), self._fetch())

    def _op_bne(self, op, mode):
        """BNE."""
        self._branch(not self.p & F_Z, self._fetch())

    def _op_beq(self, op, mode):
        """BEQ."""
        self._branch(bool(self.p & F_Z), self._fetch())

    # ----- bit instructions -----

    def _op_rmb(self, op, mode):
        """RMBn zp: clear bit n of a zero page byte."""
        ea = self._fetch()
        self.write(ea, self.read(ea) & ~(1 << ((op >> 4) & 7)) & 0xFF)

    def _op_smb(self, op, mode):
        """SMBn zp: set bit n of a zero page byte."""
        ea = self._fetch()
        self.write(ea, self.read(ea) | (1 << ((op >> 4) & 7)))

    def _op_bbr(self, op, mode):
        """BBRn zp, rel: branch when bit n of a zero page byte is 0."""
        v = self.read(self._fetch())
        off = self._fetch()
        self._branch(not v & (1 << ((op >> 4) & 7)), off)

    def _op_bbs(self, op, mode):
        """BBSn zp, rel: branch when bit n of a zero page byte is 1."""
        v = self.read(self._fetch())
        off = self._fetch()
        self._branch(bool(v & (1 << ((op >> 4) & 7))), off)

    def _op_rba(self, op, mode):
        """RBA #mask, abs: clear the mask bits in memory. A gets the mask (as on the chip)."""
        self.a = self._fetch()
        ea = self._fetch16()
        self.write(ea, self.read(ea) & ~self.a & 0xFF)

    def _op_sba(self, op, mode):
        """SBA #mask, abs: set the mask bits in memory. A gets the mask (as on the chip)."""
        self.a = self._fetch()
        ea = self._fetch16()
        self.write(ea, self.read(ea) | self.a)

    def _op_bar(self, op, mode):
        """BAR abs, #mask, rel: branch when one or more of the mask bits in memory are 0."""
        v = self.read(self._fetch16())
        mask = self._fetch()
        off = self._fetch()
        self._branch((~v & mask) != 0, off)

    def _op_bas(self, op, mode):
        """BAS abs, #mask, rel: branch when one or more of the mask bits in memory are 1."""
        v = self.read(self._fetch16())
        mask = self._fetch()
        off = self._fetch()
        self._branch((v & mask) != 0, off)

    # ----- multiply and the W register -----

    def _op_mpy(self, op, mode):
        """MPY: signed A x Y. The high byte goes to A, the low byte to Y."""
        r = s8(self.a) * s8(self.y)
        self.a = self._accumulate(r, 0) >> 8

    def _op_mpa(self, op, mode):
        """MPA: W = W + signed A x Y, with saturation. Y gets the low byte."""
        self.w = self._accumulate(s8(self.a) * s8(self.y), self.w)

    def _op_rnd(self, op, mode):
        """RND: round W to its high byte into A (MAME behaviour: the low byte comes from Y)."""
        v = (self.w & 0xFF00) | self.y
        self.a = self._accumulate(v, (self.w << 1) & 0x100) >> 8

    def _op_taw(self, op, mode):
        """TAW: W = A x 256. N and Z from A."""
        self.w = (self.a << 8) & 0xFFFF
        self._nz(self.a)

    def _op_twa(self, op, mode):
        """TWA: A = the high byte of W. N and Z from A."""
        self.a = self._nz(self.w >> 8)

    def _op_clw(self, op, mode):
        """CLW: clear W and V."""
        self.w = 0
        self.p &= ~F_V

    def _op_phw(self, op, mode):
        """PHW: push W, high byte first."""
        self.push16(self.w)

    def _op_plw(self, op, mode):
        """PLW: pull W, low byte first."""
        self.w = self.pull16()

    # ----- threaded code (the I register) -----

    def _op_nxt(self, op, mode):
        """NXT: PC = (I), I = I + 2."""
        self.pc = self.rd16(self.i)
        self.i = (self.i + 2) & 0xFFFF

    def _op_lii(self, op, mode):
        """LII: I = (I)."""
        self.i = self.rd16(self.i)

    def _op_lai(self, op, mode):
        """LAI: A = (I). The flags do not change."""
        self.a = self.read(self.i)

    def _op_lan(self, op, mode):
        """LAN: A = (I), I = I + 1. The flags do not change."""
        self.a = self.read(self.i)
        self.i = (self.i + 1) & 0xFFFF

    def _op_ini(self, op, mode):
        """INI: I = I + 1."""
        self.i = (self.i + 1) & 0xFFFF

    def _op_phi(self, op, mode):
        """PHI: push I, high byte first."""
        self.push16(self.i)

    def _op_pli(self, op, mode):
        """PLI: pull I, low byte first."""
        self.i = self.pull16()

    def _op_pia(self, op, mode):
        """PIA: pull I, then A = (I), I = I + 1."""
        self.i = self.pull16()
        self.a = self.read(self.i)
        self.i = (self.i + 1) & 0xFFFF

    def _op_jpi(self, op, mode):
        """JPI (abs): I = the address of the operand, PC = (operand), I = I + 2."""
        self.i = self.pc
        ptr = self.rd16(self.i)
        self.i = (self.i + 2) & 0xFFFF
        self.pc = self.rd16(ptr)

    def _op_tip(self, op, mode):
        """TIP: PC = I (the return of JPI)."""
        self.pc = self.i


def disasm(read, addr: int) -> tuple[str, int]:
    """Disassemble one instruction at ``addr``. Return the text and the length in bytes."""
    op = read(addr & 0xFFFF)
    mn, mode = OPCODES[op]
    n = MODE_BYTES[mode]
    b = [read((addr + k) & 0xFFFF) for k in range(n)]
    name = "nop" if mn == "nop1" else mn

    def rel(off, after):
        """Return the target of a relative branch."""
        return (addr + after + s8(off)) & 0xFFFF

    if mode in ("imp",):
        text = name
    elif mode == "acc":
        text = f"{name} a"
    elif mode == "imm":
        text = f"{name} #${b[1]:02x}"
    elif mode == "zp":
        text = f"{name} ${b[1]:02x}"
    elif mode == "zpx":
        text = f"{name} ${b[1]:02x},x"
    elif mode == "zpy":
        text = f"{name} ${b[1]:02x},y"
    elif mode == "zpi":
        text = f"{name} (${b[1]:02x})"
    elif mode == "ipx":
        text = f"{name} (${b[1]:02x}),x"
    elif mode == "rel":
        text = f"{name} ${rel(b[1], 2):04x}"
    elif mode == "abs":
        text = f"{name} ${b[1] | b[2] << 8:04x}"
    elif mode == "abx":
        text = f"{name} ${b[1] | b[2] << 8:04x},x"
    elif mode == "aby":
        text = f"{name} ${b[1] | b[2] << 8:04x},y"
    elif mode == "ind":
        text = f"{name} (${b[1] | b[2] << 8:04x})"
    elif mode == "iax":
        text = f"{name} (${b[1] | b[2] << 8:04x},x)"
    elif mode == "zpr":
        text = f"{name} ${b[1]:02x},${rel(b[2], 3):04x}"
    elif mode == "imz":
        text = f"{name} #${b[1]:02x},${b[2]:02x}"
    elif mode == "ima":
        text = f"{name} #${b[1]:02x},${b[2] | b[3] << 8:04x}"
    elif mode == "amr":
        text = f"{name} ${b[1] | b[2] << 8:04x},#${b[3]:02x},${rel(b[4], 5):04x}"
    else:
        raise ValueError(mode)
    if mn == "jpi":
        text = f"jpi (${b[1] | b[2] << 8:04x})"
    return text, n


class C39Banks:
    """The bank select logic of the C39: eight Bank Select Registers (BSR0-BSR7, at $0018-$001F).

    Each BSR controls one 8 KB window of the 64 KB CPU space. Bits 3-0
    give A16-A13 of the external address. Bits 7-4 are the active-low chip
    selects ES3-ES0. ES3 has priority over ES2, ES2 over ES1, ES1 over ES0.
    The ES4 chip select covers $0600-$07FF when PBS bit 1 is 0.
    """

    RESET = (0xE0, 0xD1, 0xB2, 0xB3, 0x74, 0x75, 0x76, 0x77)

    def __init__(self):
        """Make the registers with their reset values. PBS is $FF after reset."""
        self.bsr = list(self.RESET)
        self.pbs = 0xFF

    def reset(self) -> None:
        """Load the reset values."""
        self.bsr = list(self.RESET)
        self.pbs = 0xFF

    def internal_rom_enabled(self) -> bool:
        """Return True when BSR7 selects no ES line (then $E000-$FFFF is the internal ROM)."""
        return (self.bsr[7] & 0xF0) == 0xF0

    def decode(self, addr: int) -> tuple[str, int]:
        """Translate a CPU address for the expansion bus ($0600-$FFFF).

        Return (select, offset):
        - ("es4", offset) for the ES4 window ($0600-$07FF) when PBS bit 1 is 0.
          The offset is from $0600 (0-$1FF).
        - ("es0".."es3", physical) for a banked access. The physical address
          has 17 bits (A16-A0).
        - ("none", physical) when the BSR selects no ES line.
        """
        addr &= 0xFFFF
        if 0x0600 <= addr < 0x0800 and not self.pbs & 0x02:
            return "es4", addr - 0x0600
        b = self.bsr[addr >> 13]
        phys = ((b & 0x0F) << 13) | (addr & 0x1FFF)
        sel = (~b >> 4) & 0x0F
        for n in (3, 2, 1, 0):
            if sel & (1 << n):
                return f"es{n}", phys
        return "none", phys
