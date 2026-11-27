"""The on-chip peripherals of the Rockwell C39 modem controller.

Written from the "C29/C39 Technical Reference Manual" (TRM). This model has
the parts that the Rockwell modem firmware uses to boot and to talk to the
host:

- The register page $0000-$003F (as plain registers, with the special
  registers below).
- The Bank Select Registers ($0018-$001F) and Port B Select ($0005), through
  ``modem_emu.cores.r65c19.C39Banks``.
- Timer A ($0010-$0013, IRQ5) and Timer B ($0014-$0017, IRQ3), interval
  mode only.
- The dual port RAM in 16450/16550A mode ($0020-$0032): the TX FIFO (bytes
  from the host), the RX FIFO (bytes to the host), FSR, FIER and HCR.
- The IRQ priority logic (TRM table 3-5) for these sources.

The ports, the PTGs, the USART and the CRC are plain registers.
"""
from __future__ import annotations

from collections import deque

from modem_emu.cores.r65c19 import C39Banks, irq_vector

# Register addresses (TRM table 3-1).
PORTA, PADIR = 0x00, 0x04
PBS = 0x05
TAM, TALL, TAUL, TAUL_GO = 0x10, 0x11, 0x12, 0x13
TBM, TBLL, TBUL, TBUL_GO = 0x14, 0x15, 0x16, 0x17
BSR0 = 0x18
FIFO, LSR, MSR, LCR, MCR, FCR = 0x20, 0x21, 0x22, 0x23, 0x24, 0x25
FSR, FIER, HCR = 0x30, 0x31, 0x32

FIFO_SIZE = 16

# Page 1 RAM vectors of the timers (TRM table 3-5).
VEC_TIMER_A_RAM = 0x0102
VEC_TIMER_B_RAM = 0x0106


class Timer:
    """One 16-bit C39 counter/timer in interval mode: a latch, a counter and an underflow flag."""

    def __init__(self):
        """Make a stopped timer with a zero latch."""
        self.mode = 0
        self.latch = 0
        self.counter = 0xFFFF
        self.running = False
        self.prescale = 0

    def load(self) -> None:
        """Copy the latch to the counter and start the timer (a write to the upper latch with download)."""
        self.counter = self.latch
        self.running = True

    def tick(self, cycles: int) -> bool:
        """Count down by ``cycles`` CPU cycles. Return True when the counter underflows one or more times."""
        if not self.running or self.mode & 0x03:
            return False
        if self.mode & 0x04:                     # divide by 32
            self.prescale += cycles
            cycles, self.prescale = divmod(self.prescale, 32)
        if cycles <= self.counter:
            self.counter -= cycles
            return False
        cycles -= self.counter + 1
        period = self.latch + 1
        self.counter = self.latch - (cycles % period)
        self.mode |= 0x80
        return True


class C39:
    """The C39 register page, the bank logic, the timers, the host UART and the IRQ logic."""

    def __init__(self):
        """Make the peripherals in the reset state."""
        self.regs = bytearray(0x40)
        self.banks = C39Banks()
        self.timer_a = Timer()
        self.timer_b = Timer()
        self.tx_fifo: deque[int] = deque()    # host -> C39 (the host writes THR)
        self.rx_fifo: deque[int] = deque()    # C39 -> host (the host reads RBR)
        self.fier = 0
        self.hcr = 0
        self.fsr_w = 0                        # bits 2-5, written by the CPU
        self.writes: dict[int, int] = {}      # write counts, for analysis
        self.pa_latch = 0
        self.pa_dir = 0
        self.pa_pins = 0xFF                   # the input levels of port A
        self.port_a_hook = None               # fn(latch, direction) -> input levels, after a change

    # ----- host side -----

    def host_write(self, data: bytes) -> int:
        """Put bytes from the host into the TX FIFO. Return the number of bytes that fit."""
        n = 0
        for b in data:
            if len(self.tx_fifo) >= FIFO_SIZE:
                break
            self.tx_fifo.append(b)
            n += 1
        return n

    def host_set_line(self, divisor: int = 1, lcr: int = 0x03, mcr: int = 0x0B) -> None:
        """Do what a host serial driver does when it opens the port: write the divisor, LCR and MCR.

        Each write sets its flag in HCR (bits 4, 5 and 6), as on the chip (TRM 3.14.5).
        """
        self.regs[0x28], self.regs[0x29] = divisor & 0xFF, divisor >> 8
        self.regs[LCR] = lcr & 0x7F
        self.regs[MCR] = mcr
        self.hcr |= 0x70

    def host_read(self) -> bytes:
        """Take all bytes that the firmware sent to the host."""
        out = bytes(self.rx_fifo)
        self.rx_fifo.clear()
        return out

    # ----- status -----

    def fsr(self) -> int:
        """Return the FIFO Status Register (TRM 3.14.16)."""
        v = self.fsr_w & 0x3C
        if len(self.rx_fifo) < 8:
            v |= 0x01
        if not self.rx_fifo:
            v |= 0x02
        if self.tx_fifo:
            v |= 0x40
        if len(self.tx_fifo) >= 8:
            v |= 0x80
        return v

    def irq(self) -> int | None:
        """Return the vector of the highest priority pending IRQ, or None (TRM 3.5)."""
        fsr = self.fsr()
        host = ((fsr & self.fier & 0xC3) != 0) or (self.hcr & 0x01 and self.hcr & 0x70)
        timer_b = self.timer_b.mode & 0xC0 == 0xC0
        if host or timer_b:
            if timer_b and not host and self.timer_b.mode & 0x20:
                return VEC_TIMER_B_RAM
            return irq_vector(3)
        if self.timer_a.mode & 0xC0 == 0xC0:
            return VEC_TIMER_A_RAM if self.timer_a.mode & 0x20 else irq_vector(5)
        return None

    def tick(self, cycles: int) -> None:
        """Advance the timers by ``cycles`` CPU cycles."""
        self.timer_a.tick(cycles)
        self.timer_b.tick(cycles)

    # ----- CPU side -----

    def _port_a_changed(self) -> None:
        """Give the new port A outputs to the board, and get the new input levels."""
        if self.port_a_hook is not None:
            self.pa_pins = self.port_a_hook(self.pa_latch, self.pa_dir) & 0xFF

    def read(self, a: int) -> int:
        """Read a register of the page $0000-$003F."""
        if a == PORTA:
            return (self.pa_latch & self.pa_dir) | (self.pa_pins & ~self.pa_dir & 0xFF)
        if BSR0 <= a < BSR0 + 8:
            return self.banks.bsr[a - BSR0]
        if a == PBS:
            return self.banks.pbs
        if a == TAM:
            return self.timer_a.mode & 0xE7
        if a in (TAUL, TAUL_GO):
            if a == TAUL_GO:
                self.timer_a.mode &= 0x7F
            return self.timer_a.counter >> 8
        if a == TALL:
            return self.timer_a.counter & 0xFF
        if a == TBM:
            return self.timer_b.mode & 0xE7
        if a in (TBUL, TBUL_GO):
            if a == TBUL_GO:
                self.timer_b.mode &= 0x7F
            return self.timer_b.counter >> 8
        if a == TBLL:
            return self.timer_b.counter & 0xFF
        if a == FIFO:
            return self.tx_fifo.popleft() if self.tx_fifo else 0
        if a == FSR:
            return self.fsr()
        if a == FIER:
            return self.fier
        if a == HCR:
            v = self.hcr
            fsr = self.fsr()
            if fsr & self.fier & 0x03:
                v |= 0x08
            if fsr & self.fier & 0xC0:
                v |= 0x80
            return v
        if a == FCR:
            return self.regs[a] | 0x36
        return self.regs[a]

    def write(self, a: int, v: int) -> None:
        """Write a register of the page $0000-$003F."""
        self.writes[a] = self.writes.get(a, 0) + 1
        if a == PORTA:
            self.pa_latch = v
            self._port_a_changed()
        elif a == PADIR:
            self.pa_dir = v
            self._port_a_changed()
        elif BSR0 <= a < BSR0 + 8:
            self.banks.bsr[a - BSR0] = v
        elif a == PBS:
            self.banks.pbs = v
        elif a == TAM:
            self.timer_a.mode = (self.timer_a.mode & 0x80) | (v & 0x67)
        elif a == TALL:
            self.timer_a.latch = (self.timer_a.latch & 0xFF00) | v
        elif a in (TAUL, TAUL_GO):
            self.timer_a.latch = (self.timer_a.latch & 0xFF) | (v << 8)
            if a == TAUL_GO:
                self.timer_a.mode &= 0x7F
                self.timer_a.load()
        elif a == TBM:
            self.timer_b.mode = (self.timer_b.mode & 0x80) | (v & 0x67)
        elif a == TBLL:
            self.timer_b.latch = (self.timer_b.latch & 0xFF00) | v
        elif a in (TBUL, TBUL_GO):
            self.timer_b.latch = (self.timer_b.latch & 0xFF) | (v << 8)
            if a == TBUL_GO:
                self.timer_b.mode &= 0x7F
                self.timer_b.load()
        elif a == FIFO:
            if len(self.rx_fifo) < FIFO_SIZE:
                self.rx_fifo.append(v)
        elif a == FSR:
            self.fsr_w = v & 0x3C
        elif a == FIER:
            if v & 0x04:
                self.rx_fifo.clear()
            if v & 0x08:
                self.tx_fifo.clear()
            self.fier = v & 0xF3
        elif a == HCR:
            self.hcr = (self.hcr & 0x70 & v) | (v & 0x07)
        else:
            self.regs[a] = v
