"""A 24C16-type I2C serial EEPROM (2 KB), driven by two bit-banged port lines.

The Apex firmware reads and writes its stored profiles through I2C on C39
port A: bit 7 is SCL and bit 1 is SDA (found from the firmware routines at
$0B84-$0C5D). The control byte is $A0 | (block << 1) | R/W, with a 3-bit
block number, thus a 24C16 (8 blocks of 256 bytes).
"""
from __future__ import annotations


class I2CEeprom:
    """A 24C16 EEPROM on an open-drain I2C bus. The board calls ``update(scl, sda)`` after each pin change."""

    SIZE = 0x800

    def __init__(self, data: bytes | None = None):
        """Make the EEPROM. ``data`` is the initial content (2 KB), or None for a blank ($FF) part."""
        self.mem = bytearray(data or b"\xff" * self.SIZE)
        self.mem.extend(b"\xff" * (self.SIZE - len(self.mem)))
        self.scl = 1
        self.sda = 1
        self.out = 1            # the level that the EEPROM drives on SDA (1 = released)
        self.phase = "idle"     # idle, control, word, data (receive), read (send)
        self.bit = 0            # clock pulses done in the current byte (-1 after START, then 0-9)
        self.shift = 0
        self.addr = 0
        self.dirty = False
        self.writes = 0         # bytes written since power-on

    def _received(self, b: int) -> bool:
        """Handle a byte that the master sent. Return True to send ACK."""
        if self.phase == "control":
            if b & 0xF0 != 0xA0:
                self.phase = "idle"
                return False
            block = (b >> 1) & 0x07
            if b & 1:
                self.addr = (block << 8) | (self.addr & 0xFF)
                self.phase = "read"
            else:
                self.addr = block << 8
                self.phase = "word"
            return True
        if self.phase == "word":
            self.addr = (self.addr & 0x700) | b
            self.phase = "data"
            return True
        if self.phase == "data":
            self.mem[self.addr] = b
            self.dirty = True
            self.writes += 1
            self.addr = (self.addr & ~0x0F) | ((self.addr + 1) & 0x0F)
            return True
        return False

    def _falling(self) -> None:
        """Handle a falling edge of SCL: count the clock pulse and set the SDA output for the next one."""
        if self.phase == "idle":
            self.out = 1
            return
        self.bit += 1
        if self.phase == "read" and self._sending:
            if self.bit < 8:
                self.out = (self.shift >> (7 - self.bit)) & 1
            elif self.bit == 8:
                self.out = 1                       # release for the master ACK
            else:                                   # bit 9: the next byte
                self._start_send()
            return
        if self.bit == 0:
            return
        if self.bit == 8:
            ack = self._received(self.shift & 0xFF)
            self.out = 0 if ack else 1
            self._was_control_read = self.phase == "read"
        elif self.bit >= 9:
            self.bit, self.shift = 0, 0
            self.out = 1
            if self.phase == "read" and self._was_control_read:
                self._start_send(first=True)

    def _start_send(self, first: bool = False) -> None:
        """Load the next byte to send and drive its bit 7."""
        if not first:
            self.addr = (self.addr + 1) % self.SIZE
        self._sending = True
        self.shift = self.mem[self.addr]
        self.bit = 0
        self.out = (self.shift >> 7) & 1

    _sending = False
    _was_control_read = False

    def update(self, scl: int, sda: int) -> int:
        """Give the master's levels (SCL, SDA as driven by the master, 1 = released). Return the bus SDA level."""
        bus = sda & self.out
        if scl and self.scl and self.sda != bus:
            if not bus:                              # START (also a repeated START)
                # bit = -1: the falling edge of SCL after START is not a clock pulse.
                self.phase, self.bit, self.shift, self.out = "control", -1, 0, 1
                self._sending = self._was_control_read = False
                bus = sda
            else:                                    # STOP
                self.phase, self.out = "idle", 1
                self._sending = False
        elif scl and not self.scl:                   # rising edge: sample
            if self._sending:
                if self.bit == 8 and bus:             # master NAK
                    self.phase, self._sending = "idle", False
            elif self.phase != "idle" and self.bit < 8:
                self.shift = (self.shift << 1) | bus
        elif not scl and self.scl:
            self._falling()
            bus = sda & self.out
        self.scl, self.sda = scl, bus
        return bus
