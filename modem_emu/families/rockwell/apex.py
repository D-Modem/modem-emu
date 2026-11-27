"""Board model of the Apex Data Mobile Plus V.34 PC Card (Rockwell RC288ACL controller, RC288DPi data pump).

Memory map (found from the firmware, 1.601-US, and the C39 manual):

| CPU address | Select | Device |
|---|---|---|
| $0000-$003F | internal | C39 registers (``c39.C39``) |
| $0040-$05FF | internal | RAM |
| $0600-$07FF | ES4 (PBS bit 1 = 0) | data pump interface registers (``rc288.RC288``) |
| banked by BSR0-BSR7 | ES3 | 128 KB flash (the firmware image) |
| banked by BSR0-BSR7 | ES2 | RAM |

The firmware sets BSR0-BSR3 to ES3 (flash $00000-$07FFF), BSR4-BSR6 to ES2
(RAM) and BSR7 to ES3 (flash $0E000-$0FFFF). It changes BSR1-BSR3 to call
code in the other flash banks.

Port A bit 7 (SCL) and bit 1 (SDA) go to a 24C16 serial EEPROM
(``eeprom.I2CEeprom``) that holds the stored profiles.
"""
from __future__ import annotations

from modem_emu.cores.r65c19 import R65C19

from .c39 import C39
from .eeprom import I2CEeprom
from .rc288 import RC288

FLASH_SIZE = 0x20000
RAM_SIZE = 0x20000


def load_ram_dump(path: str) -> list[int]:
    """Read a DSP RAM dump: 16-bit big-endian words (the format of ``txcel-cellular/dumps``)."""
    data = open(path, "rb").read()
    return [(data[i] << 8) | data[i + 1] for i in range(0, len(data) - 1, 2)]


class ApexBoard:
    """The Apex Mobile Plus V.34 card: a C39-type CPU, flash, RAM and a data pump model."""

    def __init__(self, flash: bytes, dsp_ram: list[int] | None = None, eeprom: bytes | None = None):
        """Make the board with the firmware image ``flash`` (at most 128 KB) and reset it.

        dsp_ram: the initial DSP RAM words (for example, from ``load_ram_dump``).
        eeprom: the initial content of the 2 KB serial EEPROM, or None for a blank part.
        """
        if len(flash) > FLASH_SIZE:
            raise ValueError("the flash image is larger than 128 KB")
        self.flash = bytes(flash) + b"\xff" * (FLASH_SIZE - len(flash))
        self.ram = bytearray(RAM_SIZE)
        self.low = bytearray(0x600)
        self.c39 = C39()
        self.pump = RC288(dsp_ram)
        self.eeprom = I2CEeprom(eeprom)
        self.c39.port_a_hook = self._port_a
        self.cpu = R65C19(self.read, self.write)
        self.bad: dict[str, int] = {}
        self.cpu.reset()

    def _port_a(self, latch: int, direction: int) -> int:
        """Port A: bit 7 is the I2C clock and bit 1 the I2C data of the EEPROM (open drain). Return the pins."""
        scl = (latch >> 7) & 1 if direction & 0x80 else 1
        sda = (latch >> 1) & 1 if direction & 0x02 else 1
        bus = self.eeprom.update(scl, sda)
        return 0xFD | (bus << 1)

    def read(self, a: int) -> int:
        """Read one byte of the CPU address space."""
        if a < 0x40:
            return self.c39.read(a)
        if a < 0x600:
            return self.low[a]
        sel, off = self.c39.banks.decode(a)
        if sel == "es4":
            return self.pump.read(off)
        if sel == "es3":
            return self.flash[off]
        if sel == "es2":
            return self.ram[off]
        self.bad[sel] = self.bad.get(sel, 0) + 1
        return 0xFF

    def write(self, a: int, v: int) -> None:
        """Write one byte of the CPU address space."""
        if a < 0x40:
            self.c39.write(a, v)
            return
        if a < 0x600:
            self.low[a] = v
            return
        sel, off = self.c39.banks.decode(a)
        if sel == "es4":
            self.pump.write(off, v)
        elif sel == "es2":
            self.ram[off] = v
        else:
            self.bad["w_" + sel] = self.bad.get("w_" + sel, 0) + 1

    def step(self) -> int:
        """Do one CPU step, advance the timers and update the IRQ line. Return the cycles used."""
        self.cpu.set_irq(self.c39.irq())
        n = self.cpu.step()
        self.c39.tick(n)
        return n

    BOOT_CYCLES = 16_000_000
    BOOT_LIMIT = 150_000_000
    EEPROM_QUIET = 4_000_000

    def boot(self) -> None:
        """Run the firmware through its start-up, then open the host port as a serial driver does.

        With a blank EEPROM, the firmware writes the factory profiles first. This takes
        about 55 million cycles (one byte for each write cycle of the part). The board
        runs until the EEPROM has had no writes for ``EEPROM_QUIET`` cycles.
        """
        self.run(self.BOOT_CYCLES - 1_000_000)
        quiet_since, count = self.cpu.cycles, self.eeprom.writes
        while self.cpu.cycles - quiet_since < self.EEPROM_QUIET and self.cpu.cycles < self.BOOT_LIMIT:
            self.run(1_000_000)
            if self.eeprom.writes != count:
                quiet_since, count = self.cpu.cycles, self.eeprom.writes
        self.c39.host_set_line()
        self.run(1_000_000)
        self.c39.host_read()

    def run(self, cycles: int) -> None:
        """Run the board for about ``cycles`` CPU cycles."""
        end = self.cpu.cycles + cycles
        while self.cpu.cycles < end:
            self.step()

    def command(self, text: str, cycles: int = 4_000_000) -> str:
        """Send an AT command line (``text`` + CR) from the host, run, and return what the firmware sent back."""
        data = text.encode("ascii") + b"\r"
        out = bytearray()
        end = self.cpu.cycles + cycles
        while self.cpu.cycles < end:
            if data:
                n = self.c39.host_write(data)
                data = data[n:]
            self.step()
            out += self.c39.host_read()
        return out.decode("latin-1")
