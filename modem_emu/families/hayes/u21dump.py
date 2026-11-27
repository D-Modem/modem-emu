"""Dump program for the TMS320C25 mask ROM of the Hayes data pump (U21).

Method (TI SPRU014, section 3.4 and the TBLR and BLKP pages):

1. The DSP starts with MP/MC = 1. It runs this program from external
   program memory (the U22/U23 sockets, or a test fixture).
2. The loader copies the dump code into block B0, sets CNF = 1 (B0 is
   program memory at 0xFF00) and jumps to 0xFF00.
3. The code sends "U21 READY" on the XF pin (asynchronous serial, 8N1),
   then waits until the operator sets MP/MC to 0. It sees the change
   because the signature words at ``SIG_ADDR`` change when the on-chip ROM
   replaces the external memory.
4. It reads program words 0x0000-0x0FFF with TBLR, and sends them as hex
   text on XF. It does this ``passes`` times.

The text is: one line ``AAAA: wwww wwww ...`` (8 words) for each 8
addresses, then ``END``. ``decode_capture`` changes the text back into the
ROM words.
"""
import re

from modem_emu.cores.c25asm import Asm, IND_DEC

# Data variables in block B2 (data page 0, addresses 0x60-0x7F).
CH, SH, VAL, NIB, ADDR, PASS, PTR, CNT, TMP = range(0x60, 0x69)

B0_ORIGIN = 0xFF00          # program address of block B0 when CNF = 1
B0_SIZE = 256               # words
SIG_ADDR = 0x07F0           # signature words in the external memory
SIGNATURE = [0x5A3C, 0xC3A5, 0x0F1E, 0xE1F0]
EXT_WORDS = 0x0800          # size of the external image (2K words = two 2K x 8 chips)
ROM_WORDS = 0x1000          # size of the on-chip ROM

# Cycles of the bit loop without the delay, from one RXF/SXF to the next (see putc).
_BIT_OVERHEAD = 18


def _delay_body(a, cycles):
    """Add code that takes the given number of cycles: a BANZ loop of RPTK/NOP, then RPTK/NOP pairs.

    The code can change ARP and AR4. Its callers select their ARP again after the call.
    """
    loop = 1 + 256 + 2                  # RPTK, 256 NOPs, BANZ
    if cycles >= 2 + loop:
        n = (cycles - 2) // loop        # LARK + LARP = 2 cycles
        a.lark(4, n - 1)
        a.larp(4)
        top = "_dly%d" % len(a.code)
        a.label(top)
        a.rptk(255)
        a.nop()
        a.banz(top, IND_DEC)
        cycles -= 2 + n * loop
    while cycles >= 2:
        n = min(cycles - 1, 256)        # RPTK (1 cycle) + n NOPs
        a.rptk(n - 1)
        a.nop()
        cycles -= n + 1
    if cycles == 1:
        a.nop()


def build_b0(cycles_per_bit, passes=3, count=ROM_WORDS):
    """Return the B0 code words (origin 0xFF00) for the given serial bit time.

    cycles_per_bit: CLKOUT1 cycles for one bit (CLKOUT1 / baud rate).
    passes: the number of times to send the ROM.
    count: the number of ROM words to send (a multiple of 8; 4096 for the full ROM).
    """
    delay = int(round(cycles_per_bit)) - _BIT_OVERHEAD
    if delay < 2:
        raise ValueError("the baud rate is too high for this clock")
    if count % 8 or not 0 < count <= ROM_WORDS:
        raise ValueError("count must be a multiple of 8, from 8 to 4096")
    a = Asm(B0_ORIGIN)

    # ---- main: banner, wait for MP/MC = 0, dump
    a.label("main")
    a.lalk("s_ready")
    a.sacl(PTR)
    a.call("puts")
    a.lack(0)
    a.sacl(CNT)
    a.label("wait")
    for i, sig in enumerate(SIGNATURE):
        a.lalk(SIG_ADDR + i)
        a.tblr(TMP)
        a.lalk(sig)
        a.xor(TMP)
        a.bnz("go")
    a.lac(CNT)
    a.addk(1)
    a.andk(0xFFFF)
    a.sacl(CNT)
    a.bnz("wait")
    a.lack(ord("."))
    a.sacl(CH)
    a.call("putc")
    a.b("wait")

    a.label("go")
    a.lalk("s_go")
    a.sacl(PTR)
    a.call("puts")
    a.lack(passes)
    a.sacl(PASS)
    a.label("pass")
    a.lack(0)
    a.sacl(ADDR)
    a.label("word")
    a.lac(ADDR)
    a.andk(7)
    a.bnz("nohead")
    a.call("crlf")
    a.lac(ADDR)
    a.sacl(VAL)
    a.call("puthex4")
    a.lack(ord(":"))
    a.sacl(CH)
    a.call("putc")
    a.label("nohead")
    a.lack(ord(" "))
    a.sacl(CH)
    a.call("putc")
    a.lac(ADDR)
    a.tblr(VAL)
    a.call("puthex4")
    a.lac(ADDR)
    a.addk(1)
    a.sacl(ADDR)
    a.lalk(count)
    a.xor(ADDR)
    a.bnz("word")
    a.call("crlf")
    a.lalk("s_end")
    a.sacl(PTR)
    a.call("puts")
    a.lac(PASS)
    a.subk(1)
    a.sacl(PASS)
    a.bnz("pass")
    a.label("done")
    a.b("done")

    # ---- crlf: send CR and LF
    a.label("crlf")
    a.lack(13)
    a.sacl(CH)
    a.call("putc")
    a.lack(10)
    a.sacl(CH)
    a.call("putc")
    a.ret()

    # ---- puts: send the 0-terminated string at program address PTR
    a.label("puts")
    a.lac(PTR)
    a.tblr(CH)
    a.lac(CH)
    a.bz("puts_end")
    a.call("putc")
    a.lac(PTR)
    a.addk(1)
    a.sacl(PTR)
    a.b("puts")
    a.label("puts_end")
    a.ret()

    # ---- puthex4: send VAL as 4 hex digits
    a.label("puthex4")
    a.lark(3, 3)
    a.label("hex_loop")
    a.lac(VAL, 4)           # ACC = VAL << 4 (no sign extension)
    a.sach(NIB)             # the top digit
    a.sacl(VAL)             # the other digits move up
    a.lac(NIB)
    a.subk(10)
    a.blz("hex_digit")
    a.addk(ord("A"))
    a.b("hex_out")
    a.label("hex_digit")
    a.addk(ord("0") + 10)
    a.label("hex_out")
    a.sacl(CH)
    a.call("putc")
    a.larp(3)
    a.banz("hex_loop", IND_DEC)
    a.ret()

    # ---- putc: send CH on XF, 8N1, LSB first. Each bit takes cycles_per_bit.
    # The time from one RXF/SXF to the next is the same for each path:
    # start bit: RXF, CALL(2) delay RET(2) LARK(1) LAC(1) SACL(1) RPTK/NOP(5) LAC(1) ANDK(2) BZ(2), RXF/SXF(1)
    # bit loop:  LAC(1) ANDK(2) BZ(2) RXF/SXF  B(2) or NOP NOP(2)  LAC SFR SACL(3)
    #            CALL(2) delay RET(2) LARP(1) BANZ(2), and the RXF/SXF (1) -> 18 + delay cycles
    a.label("putc")
    a.rxf()                 # start bit
    a.call("bitdelay")
    a.lark(2, 7)
    a.lac(CH)
    a.sacl(SH)
    a.rptk(3)                # 5 cycles: RPTK + 4 NOPs
    a.nop()
    a.label("bit_loop")
    a.lac(SH)
    a.andk(1)
    a.bz("bit_zero")
    a.sxf()
    a.b("bit_next")
    a.label("bit_zero")
    a.rxf()
    a.nop()
    a.nop()
    a.label("bit_next")
    a.lac(SH)
    a.sfr()
    a.sacl(SH)
    a.call("bitdelay")
    a.larp(2)
    a.banz("bit_loop", IND_DEC)
    a.rptk(3)                # 5 cycles
    a.nop()
    a.sxf()                 # stop bit
    a.call("bitdelay")
    a.rptk(10)               # 12 cycles: the stop bit is a little longer than one bit
    a.nop()
    a.ret()

    a.label("bitdelay")
    _delay_body(a, delay)
    a.ret()

    a.label("s_ready")
    a.text("\r\nU21 READY\r\n")
    a.label("s_go")
    a.text("\r\nGO")
    a.label("s_end")
    a.text("END\r\n")

    words = a.words()
    if len(words) > B0_SIZE:
        raise ValueError("the B0 code is %d words; block B0 has %d" % (len(words), B0_SIZE))
    return words


def build_image(clkout1_hz=10_000_000, baud=9600, passes=3, count=ROM_WORDS):
    """Return the external program image (EXT_WORDS words) with the loader, the B0 code and the signature.

    clkout1_hz: the DSP instruction clock (the crystal frequency divided by 4).
    baud: the serial bit rate on XF.
    """
    b0 = build_b0(clkout1_hz / baud, passes, count)
    a = Asm(0x0000)
    a.dint()
    a.ldpk(0)
    a.rsxm()
    a.sxf()                 # the serial line is idle at 1
    a.lrlk(1, 0x200)        # B0 data address while CNF = 0
    a.larp(1)
    a.rptk(len(b0) - 1)
    a.blkp("b0_source")
    a.cnfp()
    a.nop()
    a.nop()
    a.b(B0_ORIGIN)
    a.label("b0_source")
    for w in b0:
        a.word(w)
    image = a.words()
    if len(image) > SIG_ADDR:
        raise ValueError("the loader and the B0 code do not fit below the signature")
    image += [0] * (EXT_WORDS - len(image))
    image[SIG_ADDR:SIG_ADDR + len(SIGNATURE)] = SIGNATURE
    return image


def split_bytes(image):
    """Return (high bytes, low bytes) of the 16-bit image, one byte for each word."""
    return bytes(w >> 8 for w in image), bytes(w & 0xFF for w in image)


def to_bytes_be(words):
    """Return the 16-bit words as big-endian bytes."""
    return b"".join(bytes((w >> 8, w & 0xFF)) for w in words)


_LINE = re.compile(r"^([0-9A-F]{4}):((?: [0-9A-F]{4}){1,8})\s*$")


def decode_capture(text, count=ROM_WORDS):
    """Change the captured serial text into ROM passes.

    Return a list of passes. Each pass is a list of count words (None for a word that was not received).
    """
    passes = []
    cur = None
    for raw in text.replace("\r", "\n").split("\n"):
        line = raw.strip()
        if line.startswith("GO") or (cur is None and _LINE.match(line)):
            cur = [None] * count
        if line.startswith("END"):
            if cur is not None:
                passes.append(cur)
            cur = None
            continue
        m = _LINE.match(line)
        if m and cur is not None:
            base = int(m.group(1), 16)
            for i, w in enumerate(m.group(2).split()):
                if base + i < count:
                    cur[base + i] = int(w, 16)
    if cur is not None and any(w is not None for w in cur):
        passes.append(cur)
    return passes


def merge_passes(passes):
    """Return (words, problems): the majority word at each address, and the addresses where passes disagree."""
    if not passes:
        raise ValueError("no passes in the capture")
    count = len(passes[0])
    words, problems = [], []
    for i in range(count):
        seen = [p[i] for p in passes if p[i] is not None]
        if not seen:
            words.append(0)
            problems.append(i)
            continue
        best = max(set(seen), key=seen.count)
        words.append(best)
        if seen.count(best) != len(passes):
            problems.append(i)
    return words, problems


def checksums(words):
    """Return simple checksums of the ROM, to compare with the ATI3 value (241)."""
    data = to_bytes_be(words)
    return {
        "sum8 of bytes": sum(data) & 0xFF,
        "sum8 of bytes, without the last word": sum(data[:-2]) & 0xFF,
        "sum16 of words": sum(words) & 0xFFFF,
        "high byte + low byte of sum16": ((sum(words) >> 8) + sum(words)) & 0xFF,
    }


def uart_decode(edges, cycles_per_bit, end_cycle):
    """Decode 8N1 characters from XF edges.

    edges: a list of (cycle, level) in time order. The line starts at 1.
    Return the decoded text. The sample point is the centre of each bit.
    """
    def level_at(t):
        """Return the line level at cycle t."""
        lvl = 1
        lo, hi = 0, len(edges)
        while lo < hi:                      # last edge at or before t
            mid = (lo + hi) // 2
            if edges[mid][0] <= t:
                lo = mid + 1
            else:
                hi = mid
        if lo:
            lvl = edges[lo - 1][1]
        return lvl

    out = []
    i = 0
    while i < len(edges):
        t, lvl = edges[i]
        if lvl != 0:
            i += 1
            continue
        start = t
        if start + 9.5 * cycles_per_bit > end_cycle:
            break
        byte = 0
        for bit in range(8):
            byte |= level_at(start + (1.5 + bit) * cycles_per_bit) << bit
        if level_at(start + 9.5 * cycles_per_bit) == 1:
            out.append(chr(byte))
        stop = start + 9.5 * cycles_per_bit
        while i < len(edges) and edges[i][0] <= stop:
            i += 1
    return "".join(out)


def simulate(rom, clkout1_hz=10_000_000, baud=9600, passes=1, count=ROM_WORDS, max_steps=50_000_000):
    """Run the dump program on the C25 core with a known ROM. Return the serial text.

    The simulation sets MP/MC to 0 after the banner, as the operator does.
    """
    from modem_emu.cores.c25 import C25
    image = build_image(clkout1_hz, baud, passes, count)
    core = C25(image, rom=rom, mp_mc=1)
    edges = []
    core.xf_out = lambda level, cycles: edges.append((cycles, level))
    cpb = clkout1_hz / baud
    steps = 0
    while steps < max_steps:
        core.run(1000)
        steps += 1000
        if core.mp_mc and core.cycles > 400 * cpb:     # the banner is out
            core.mp_mc = 0
        if core.pc in (_done_address(clkout1_hz, baud, passes, count),) and not core.mp_mc:
            break
    return uart_decode(edges, cpb, core.cycles)


def _done_address(clkout1_hz, baud, passes, count):
    """Return the program address of the final loop of the B0 code."""
    a_words = build_b0(clkout1_hz / baud, passes, count)
    # The 'done' loop is "B done": find the first branch to itself.
    for i in range(len(a_words) - 1):
        if a_words[i] == 0xFF80 and a_words[i + 1] == B0_ORIGIN + i:
            return B0_ORIGIN + i
    raise ValueError("no done loop")
