"""A small TMS320C25 assembler for test programs and the U21 dump program.

It knows only the instructions that the modem-emu tools use. Each method
adds the words of one instruction. A label can be used before it is set.

Example::

    a = Asm(origin=0x0000)
    a.label("top")
    a.lack(5)
    a.b("top")
    words = a.words()
"""

# Indirect addressing modes for the low byte of an instruction.
IND = 0x80      # *
IND_INC = 0xA0  # *+
IND_DEC = 0x90  # *-


class AsmError(Exception):
    """The program has an error (a bad operand, or a label that is not set)."""


class Asm:
    """One program section that starts at a fixed program address."""

    def __init__(self, origin=0):
        """Make an empty section at the program address origin."""
        self.origin = origin
        self.code = []
        self.labels = {}
        self.fixups = []    # (index in code, label name)

    # ---- section helpers
    @property
    def pc(self):
        """Return the program address of the next word."""
        return self.origin + len(self.code)

    def label(self, name):
        """Set the label name to the current program address."""
        if name in self.labels:
            raise AsmError("label %s is set two times" % name)
        self.labels[name] = self.pc

    def word(self, value):
        """Add one data word (a number, or a label name for its address)."""
        if isinstance(value, str):
            self.fixups.append((len(self.code), value))
            self.code.append(0)
        else:
            self.code.append(value & 0xFFFF)

    def text(self, string):
        """Add a string as one character in each word, with a 0 word at the end."""
        for ch in string:
            self.word(ord(ch))
        self.word(0)

    def words(self):
        """Return the program words, with all labels resolved."""
        out = list(self.code)
        for index, name in self.fixups:
            if name not in self.labels:
                raise AsmError("label %s is not set" % name)
            out[index] = self.labels[name] & 0xFFFF
        return out

    # ---- operand helpers
    @staticmethod
    def _dma(dma):
        """Return the low byte for a direct address (0-127) or an indirect mode (0x80 and up)."""
        if dma >= 0x80:
            return dma & 0xFF
        if dma < 0:
            raise AsmError("bad data address %r" % dma)
        return dma & 0x7F

    def _op(self, high, dma):
        """Add a one-word instruction with the high byte and a data operand."""
        self.word((high << 8) | self._dma(dma))

    def _branch(self, high, target, mode=IND):
        """Add a two-word branch instruction."""
        self.word((high << 8) | mode)
        self.word(target)

    # ---- accumulator and memory
    def lac(self, dma, shift=0):
        """LAC: load the accumulator, with a left shift."""
        self._op(0x20 | (shift & 15), dma)

    def add(self, dma, shift=0):
        """ADD: add to the accumulator, with a left shift."""
        self._op(0x00 | (shift & 15), dma)

    def sub(self, dma, shift=0):
        """SUB: subtract from the accumulator, with a left shift."""
        self._op(0x10 | (shift & 15), dma)

    def addh(self, dma):
        """ADDH: add to the high word of the accumulator."""
        self._op(0x48, dma)

    def subh(self, dma):
        """SUBH: subtract from the high word of the accumulator."""
        self._op(0x44, dma)

    def subc(self, dma):
        """SUBC: conditional subtract (one step of a division)."""
        self._op(0x47, dma)

    def zals(self, dma):
        """ZALS: load the low word of the accumulator, and set the high word to 0."""
        self._op(0x41, dma)

    def xor(self, dma):
        """XOR: exclusive OR with the low word of the accumulator."""
        self._op(0x4C, dma)

    def and_(self, dma):
        """AND: AND with the accumulator (the high word becomes 0)."""
        self._op(0x4E, dma)

    def sacl(self, dma, shift=0):
        """SACL: store the low word of the accumulator, with a left shift of 0-7."""
        self._op(0x60 | (shift & 7), dma)

    def sach(self, dma, shift=0):
        """SACH: store the high word of the accumulator, with a left shift of 0-7."""
        self._op(0x68 | (shift & 7), dma)

    def lack(self, k):
        """LACK: load an 8-bit constant into the accumulator."""
        self.word(0xCA00 | (k & 0xFF))

    def addk(self, k):
        """ADDK: add an 8-bit constant."""
        self.word(0xCC00 | (k & 0xFF))

    def subk(self, k):
        """SUBK: subtract an 8-bit constant."""
        self.word(0xCD00 | (k & 0xFF))

    def lalk(self, k, shift=0):
        """LALK: load a 16-bit constant (or label) into the accumulator, with a left shift."""
        self.word(0xD001 | ((shift & 15) << 8))
        self.word(k)

    def andk(self, k, shift=0):
        """ANDK: AND the accumulator with a 16-bit constant, with a left shift."""
        self.word(0xD004 | ((shift & 15) << 8))
        self.word(k)

    def sfr(self):
        """SFR: shift the accumulator right by 1."""
        self.word(0xCE19)

    def sfl(self):
        """SFL: shift the accumulator left by 1."""
        self.word(0xCE18)

    def abs_(self):
        """ABS: absolute value of the accumulator."""
        self.word(0xCE1B)

    # ---- auxiliary registers
    def lark(self, ar, k):
        """LARK: load an 8-bit constant into auxiliary register ar."""
        self.word(0xC000 | ((ar & 7) << 8) | (k & 0xFF))

    def lrlk(self, ar, k):
        """LRLK: load a 16-bit constant (or label) into auxiliary register ar."""
        self.word(0xD000 | ((ar & 7) << 8))
        self.word(k)

    def larp(self, ar):
        """LARP: select auxiliary register ar."""
        self.word(0x5588 | (ar & 7))

    def ldpk(self, page):
        """LDPK: load the data page pointer (0-511)."""
        self.word(0xC800 | (page & 0x1FF))

    # ---- status
    def lst(self, dma):
        """LST: load status register ST0 (INTM does not change)."""
        self._op(0x50, dma)

    def sst(self, dma):
        """SST: store status register ST0."""
        self._op(0x78, dma)

    # ---- program memory
    def tblr(self, dma):
        """TBLR: read the program word at the address in the low word of ACC into data memory."""
        self._op(0x58, dma)

    def blkp(self, source, dma=IND_INC):
        """BLKP: move one program word (or a block, with RPTK) to data memory."""
        self.word(0xFC00 | self._dma(dma))
        self.word(source)

    # ---- repeat and control
    def rptk(self, k):
        """RPTK: repeat the next instruction k + 1 times."""
        self.word(0xCB00 | (k & 0xFF))

    def rpt(self, dma):
        """RPT: repeat the next instruction (low 8 bits of the data word) + 1 times."""
        self._op(0x4B, dma)

    def nop(self):
        """NOP (MAR with direct addressing)."""
        self.word(0x5500)

    def mar(self, mode):
        """MAR: change an auxiliary register with an indirect mode."""
        self._op(0x55, mode)

    def dint(self):
        """DINT: disable the interrupts."""
        self.word(0xCE01)

    def cnfp(self):
        """CNFP: block B0 becomes program memory at 0xFF00."""
        self.word(0xCE05)

    def cnfd(self):
        """CNFD: block B0 becomes data memory at 0x200."""
        self.word(0xCE04)

    def rsxm(self):
        """RSXM: no sign extension."""
        self.word(0xCE06)

    def ssxm(self):
        """SSXM: sign extension."""
        self.word(0xCE07)

    def sovm(self):
        """SOVM: overflow saturation on."""
        self.word(0xCE03)

    def sxf(self):
        """SXF: set the XF pin to 1."""
        self.word(0xCE0D)

    def rxf(self):
        """RXF: set the XF pin to 0."""
        self.word(0xCE0C)

    def out(self, dma, port):
        """OUT: write a data word to I/O port 0-15."""
        self._op(0xE0 | (port & 15), dma)

    def ret(self):
        """RET: return from a subroutine."""
        self.word(0xCE26)

    # ---- branches
    def b(self, target):
        """B: branch."""
        self._branch(0xFF, target)

    def call(self, target):
        """CALL: call a subroutine."""
        self._branch(0xFE, target)

    def bz(self, target):
        """BZ: branch if ACC is 0."""
        self._branch(0xF6, target)

    def bnz(self, target):
        """BNZ: branch if ACC is not 0."""
        self._branch(0xF5, target)

    def blz(self, target):
        """BLZ: branch if ACC is less than 0."""
        self._branch(0xF3, target)

    def bv(self, target):
        """BV: branch if OV is 1 (and set OV to 0)."""
        self._branch(0xF0, target)

    def bnv(self, target):
        """BNV: branch if OV is 0 (else set OV to 0)."""
        self._branch(0xF7, target)

    def banz(self, target, mode=IND_DEC):
        """BANZ: branch if the current auxiliary register is not 0, then change it."""
        self._branch(0xFB, target, mode)
