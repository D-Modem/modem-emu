"""Tests for the Rockwell family: the C39 peripherals, the I2C EEPROM, the data pump model and the Apex board."""
import os

import pytest

from modem_emu.cores.r65c19 import irq_vector
from modem_emu.families.rockwell.c39 import C39, VEC_TIMER_A_RAM
from modem_emu.families.rockwell.eeprom import I2CEeprom
from modem_emu.families.rockwell.rc288 import RC288


# ----- C39 -----

def test_timer_a_underflow_sets_flag_and_irq5():
    """Timer A counts down from the latch. An underflow sets TAM7, and with TAM6 it asserts IRQ5."""
    c = C39()
    c.write(0x11, 9)
    c.write(0x13, 0)            # latch = 9, download
    c.write(0x10, 0x40)         # interrupt enable, ROM vector
    c.tick(9)
    assert c.irq() is None
    c.tick(1)
    assert c.read(0x10) & 0x80
    assert c.irq() == irq_vector(5)
    c.read(0x13)                # clears the flag
    assert c.irq() is None


def test_timer_a_ram_vector():
    """With TAM5 set, Timer A uses the page 1 RAM vector $0102."""
    c = C39()
    c.write(0x13, 0)
    c.write(0x10, 0x60)
    c.tick(1)
    assert c.irq() == VEC_TIMER_A_RAM


def test_host_fifos_and_fsr():
    """Host bytes go to the TX FIFO (read at $20). CPU writes to $20 go to the host."""
    c = C39()
    assert c.read(0x30) & 0x02             # RX FIFO (to the host) is empty
    c.host_write(b"AT")
    assert c.read(0x30) & 0x40             # TCDA: data from the host
    c.write(0x31, 0x40)
    assert c.irq() == irq_vector(3)
    assert bytes([c.read(0x20), c.read(0x20)]) == b"AT"
    assert c.irq() is None
    c.write(0x20, ord("O"))
    c.write(0x20, ord("K"))
    assert c.host_read() == b"OK"


def test_host_line_flags_in_hcr():
    """A host write of the divisor, LCR and MCR sets HCR bits 4-6. The CPU clears them by writing 0."""
    c = C39()
    c.host_set_line()
    assert c.read(0x32) & 0x70 == 0x70
    c.write(0x32, 0x07)
    assert c.read(0x32) & 0x70 == 0


def test_port_a_hook_gives_input_levels():
    """Port A reads the latch on output bits and the board's levels on input bits."""
    c = C39()
    c.port_a_hook = lambda latch, direction: 0x0F
    c.write(0x04, 0xF0)
    c.write(0x00, 0xA0)
    assert c.read(0x00) == 0xAF


# ----- I2C EEPROM -----

class Master:
    """A bit-banged I2C master for the tests."""

    def __init__(self, dev: I2CEeprom):
        """Use the EEPROM ``dev``."""
        self.dev = dev
        self.scl = self.sda = 1

    def set(self, scl: int, sda: int) -> int:
        """Drive the lines and return the bus SDA."""
        self.scl, self.sda = scl, sda
        return self.dev.update(scl, sda)

    def start(self):
        """Send START."""
        self.set(1, 1)
        self.set(1, 0)
        self.set(0, 0)

    def stop(self):
        """Send STOP."""
        self.set(0, 0)
        self.set(1, 0)
        self.set(1, 1)

    def send(self, b: int) -> bool:
        """Send one byte. Return True for ACK."""
        for i in range(7, -1, -1):
            bit = (b >> i) & 1
            self.set(0, bit)
            self.set(1, bit)
            self.set(0, bit)
        self.set(0, 1)
        ack = self.set(1, 1) == 0
        self.set(0, 1)
        return ack

    def recv(self, ack: bool) -> int:
        """Receive one byte, then send ACK or NAK."""
        v = 0
        for _ in range(8):
            self.set(0, 1)
            v = (v << 1) | self.set(1, 1)
            self.set(0, 1)
        self.set(0, 0 if ack else 1)
        self.set(1, 0 if ack else 1)
        self.set(0, 0 if ack else 1)
        return v


def test_eeprom_write_then_random_read():
    """A byte write, then a random read with a repeated START, gives the byte back."""
    dev = I2CEeprom()
    m = Master(dev)
    m.start()
    assert m.send(0xA0 | (3 << 1)) and m.send(0x45) and m.send(0x5A)
    m.stop()
    assert dev.mem[0x345] == 0x5A
    m.start()
    assert m.send(0xA0 | (3 << 1)) and m.send(0x45)
    m.start()
    assert m.send(0xA1 | (3 << 1))
    assert m.recv(ack=True) == 0x5A
    assert m.recv(ack=False) == 0xFF
    m.stop()


def test_eeprom_ignores_other_devices():
    """A control byte that is not $Ax gets no ACK."""
    m = Master(I2CEeprom())
    m.start()
    assert not m.send(0x90)


# ----- data pump model -----

def test_rc288_boot_sequence():
    """After reset: the ready code in 1C/1D, the revision in 13/12/11/00, then CONF = $76."""
    p = RC288()
    assert (p.read(0x1C), p.read(0x1D)) == (0x3C, 0xEA)
    assert bytes(p.read(r) for r in (0x13, 0x12, 0x11, 0x00)) == b"05BA"
    assert p.read(0x12) == 0x76
    assert p.read(0x1E) & 0x08


def test_rc288_ram_access():
    """A write and a read through 18/19, 1C and 1D (bit 7 start, bit 5 write)."""
    p = RC288(ram=[0] * 0x303 + [0x1234])
    p.write(0x1C, 0x03)
    p.write(0x1D, 0x83)
    assert p.read(0x1D) & 0x80 == 0
    assert (p.read(0x19), p.read(0x18)) == (0x12, 0x34)
    p.write(0x18, 0xCD)
    p.write(0x19, 0xAB)
    p.write(0x1C, 0x10)
    p.write(0x1D, 0xA2)
    assert p.ram[0x210] == 0xABCD


def test_rc288_default_ram():
    """Without a RAM dump, the DSP RAM has the words that the firmware needs. With a dump, it has the dump only."""
    assert RC288().ram[0x8FE] == 0x4441
    assert RC288(ram=[1, 2]).ram[0x8FE] == 0


def test_eeprom_page_write_wraps():
    """A page write that goes past the end of a 16-byte page wraps to the start of the page."""
    dev = I2CEeprom()
    m = Master(dev)
    m.start()
    assert m.send(0xA0) and m.send(0x1E)
    assert m.send(0x11) and m.send(0x22) and m.send(0x33)
    m.stop()
    assert (dev.mem[0x1E], dev.mem[0x1F], dev.mem[0x10]) == (0x11, 0x22, 0x33)
    assert dev.writes == 3


def test_rc288_newc_clears():
    """NEWC (1F bit 0) clears at once: the model applies a configuration change immediately."""
    p = RC288()
    p.write(0x1F, 0x11)
    assert p.read(0x1F) == 0x10


# ----- the Apex board, with the real firmware -----

APEX = os.environ.get("MODEM_EMU_APEX_ROM")
APEX_DSP_RAM = os.environ.get("MODEM_EMU_APEX_DSP_RAM")
APEX_EEPROM = os.environ.get("MODEM_EMU_APEX_EEPROM")


@pytest.mark.skipif(not APEX, reason="set MODEM_EMU_APEX_ROM to the Apex 1.601-US flash image (128 KB)")
def test_apex_ati_answers():
    """The 1.601-US firmware boots and gives the same ATI0, ATI3 (first line), ATI6 and stored profile 1 as the real card.

    Optional: MODEM_EMU_APEX_DSP_RAM (a DSP RAM dump) and MODEM_EMU_APEX_EEPROM (an
    EEPROM image). With a blank EEPROM, the boot takes longer, because the firmware
    writes the factory profiles first.
    """
    from modem_emu.families.rockwell.apex import ApexBoard, load_ram_dump

    board = ApexBoard(open(APEX, "rb").read(),
                      load_ram_dump(APEX_DSP_RAM) if APEX_DSP_RAM else None,
                      open(APEX_EEPROM, "rb").read() if APEX_EEPROM else None)
    board.boot()
    assert board.command("AT").endswith("OK\r\n")
    assert "\r\n33600\r\n" in board.command("ATI0")
    ati3 = board.command("ATI3")
    assert "Data/Fax Modem V.34 REV 1.601 June 10,1997\r\n" in ati3
    assert "V1.600B1-V34_LP\r\n" in ati3
    assert "RC288DPi Rev 05BA" in board.command("ATI6")
    profiles = board.command("AT&V", cycles=8_000_000)
    assert "STORED PROFILE 1:\r\nB1 E1 L3 M1 Q0 T V1 W2 X4 Y0 &C1 &D2 &G0 &J0 &K3 &Q5 &R1 &S0 &T5 &X0 \r\n" in profiles
