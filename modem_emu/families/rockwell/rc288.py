"""A register-level model of the Rockwell RC288/RC336 data pump interface.

The real data pump is a Rockwell DSP with a mask ROM program. Its program
is not available (refer to ``docs/families/rockwell.md``). This model is a
stand-in. It has the 32 interface registers (00-1F) and the DSP RAM window,
and it does the handshakes that the controller firmware waits for.

What we know about the interface, and from where:

- The register layout is the same family as the RC96V24DP data sheet
  (table 3-1): 00 RBUFFER, 10 TBUFFER, 12 CONF, 1E and 1F interrupt
  handling, 18-1D RAM access.
- The DSP RAM access of the V.34 pumps (Apex firmware trace, section 3):
  1C = address low, 1D bit 7 = start, bit 5 = write, bits 0-3 = address
  high; 18 and 19 = the data word. The DSP clears bit 7 when it is done.
- At reset, the DSP puts a ready code in 1C/1D ($3C, $EA). The Apex firmware
  waits for it at $4D10. (Found by running the firmware.)
- NEWC (1F bit 0): the host sets it after a configuration change. The DSP
  clears it when the change is done.
- TDBE (1E bit 3): the transmit data buffer is empty.
- After the ready code, the DSP shows its ROM revision in registers 13, 12,
  11 and 00 (ASCII, "05BA" for the RC288DPi of the Apex card, which agrees
  with ``ATI6``). The firmware also accepts "04BC". Then the DSP loads its
  default configuration: CONF (12) = $76. The firmware waits for this at
  $4CD4. (Found from the firmware routine at $4C4F.)

The DSP RAM starts with a RAM dump of a real card when one is given.
Without a dump, it starts with zeros and the words of ``DEFAULT_RAM``.
"""
from __future__ import annotations

READY_CODE = (0x3C, 0xEA)
REVISION = b"05BA"
DEFAULT_CONF = 0x76

# DSP RAM words that the firmware reads during boot and for ATI6, for use when
# no RAM dump is given. The values are from the RAM dump of the real card.
# The firmware copies the high byte of word $08FE to $0459 and checks it as a
# revision letter at $0BE9. Without these words, ATI6 shows "RC288DPL", not "RC288DPi".
DEFAULT_RAM = {0x0008: 0x0E76, 0x0089: 0x0028, 0x010D: 0x00DA, 0x032C: 0xFF0B, 0x08FE: 0x4441}

RBUFFER, TBUFFER, CONF = 0x00, 0x10, 0x12
XDAL, XDAM, YADD, YCTL, XADD, XCTL, IRQ_E, IRQ_F = 0x18, 0x19, 0x1A, 0x1B, 0x1C, 0x1D, 0x1E, 0x1F

TDBE = 0x08
NEWC = 0x01


class RC288:
    """The interface registers and the DSP RAM of an RC288-class data pump (no signal processing)."""

    def __init__(self, ram: list[int] | None = None, revision: bytes = REVISION):
        """Make the data pump in the reset state.

        ram: the initial words of DSP RAM (for example, a dump of a real card), or None for
        zeros with the words of ``DEFAULT_RAM``.
        revision: the 4-character ROM revision that the DSP shows after reset.
        """
        self.revision = revision
        self.regs = bytearray(0x20)
        self.ram = [0] * 0x10000
        if ram is None:
            for i, w in DEFAULT_RAM.items():
                self.ram[i] = w
        for i, w in enumerate(ram or []):
            self.ram[i] = w & 0xFFFF
        self.log: list[tuple[str, int, int]] = []
        self.keep_log = False
        self.reset()

    def reset(self) -> None:
        """Do a data pump reset: the ready code in 1C/1D, the transmit buffer empty."""
        self.regs[:] = bytes(0x20)
        self.regs[XADD], self.regs[XCTL] = READY_CODE
        self.regs[0x13], self.regs[0x12], self.regs[0x11], self.regs[0x00] = self.revision
        self.regs[IRQ_E] = TDBE
        self.booting = True

    def irq(self) -> bool:
        """Return True when the data pump asserts its IRQ line (an active interrupt flag)."""
        return bool(self.regs[IRQ_F] & 0xC0 or self.regs[IRQ_E] & 0xC0)

    def _ram_access(self, ctl: int, wide: bool) -> None:
        """Do one DSP RAM read or write for a start bit in register 1D."""
        if wide:
            addr = self.regs[0x16] | (self.regs[0x17] << 8)
        else:
            addr = self.regs[XADD] | ((ctl & 0x0F) << 8)
        if ctl & 0x20:
            self.ram[addr] = self.regs[XDAL] | (self.regs[XDAM] << 8)
        else:
            w = self.ram[addr]
            self.regs[XDAL], self.regs[XDAM] = w & 0xFF, w >> 8

    def read(self, r: int) -> int:
        """The controller reads interface register ``r`` (0-$1F)."""
        r &= 0x1F
        v = self.regs[r]
        if self.keep_log:
            self.log.append(("r", r, v))
        if self.booting and r == 0x00:
            # The controller read the last revision byte: the DSP loads its default configuration.
            self.booting = False
            self.regs[CONF] = DEFAULT_CONF
            self.regs[0x00] = 0
        return v

    def write(self, r: int, v: int) -> None:
        """The controller writes interface register ``r``. The model does the handshake at once."""
        r &= 0x1F
        if self.keep_log:
            self.log.append(("w", r, v))
        if r == XCTL and v & 0x80:
            self._ram_access(v, wide=bool(v & 0x40))
            v &= 0x7F
        elif r == IRQ_F:
            v &= ~NEWC & 0xFF              # the configuration change is done at once
        elif r == YADD:
            v &= 0x7F
        elif r == TBUFFER:
            self.regs[IRQ_E] |= TDBE       # the byte goes out at once
        self.regs[r] = v
        if r == IRQ_E:
            self.regs[r] |= TDBE
