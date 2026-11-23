"""Call single functions of the ZyXEL U-1496 68000 ROM with Unicorn.

This is not a board model. It maps the decoded ROM at 0x80000, RAM at 0 and
the on-chip area at 0xFFFF0000. Then it calls one ROM function and stops when
the function returns. Use it to test ROM tables and routines (for example the
ZyX frame mapper) against the D-Modem code.
"""
from __future__ import annotations

import struct
from pathlib import Path

ROM_BASE = 0x80000
ROM_SIZE = 0x40000
RAM_SIZE = 0x80000
STOP = 0x7F000
STACK_TOP = 0x7E00


class U1496Caller:
    """A 68020 Unicorn instance with the U-1496 ROM, to call ROM functions."""

    def __init__(self, rom: bytes | str | Path) -> None:
        """Map the memory and load the decoded ROM image (bytes or a file path)."""
        from unicorn import UC_ARCH_M68K, UC_MODE_BIG_ENDIAN, Uc
        from unicorn.m68k_const import UC_CPU_M68K_M68020

        if not isinstance(rom, (bytes, bytearray)):
            rom = Path(rom).read_bytes()
        if len(rom) > ROM_SIZE:
            raise ValueError(f"ROM is {len(rom)} bytes; the limit is {ROM_SIZE}")
        uc = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
        uc.ctl_set_cpu_model(UC_CPU_M68K_M68020)
        uc.mem_map(0, RAM_SIZE)
        uc.mem_map(ROM_BASE, ROM_SIZE)
        uc.mem_write(ROM_BASE, bytes(rom))
        uc.mem_map(0xFFFF0000, 0x10000)
        uc.mem_write(STOP, b"\x4e\x71\x4e\x71")  # two NOPs: the return address
        self.uc = uc

    @staticmethod
    def _address(address: int) -> int:
        """Map a short (16-bit) address below 0x8000 to itself, and others to 0xFFFFxxxx."""
        return address if address < 0x8000 else 0xFFFF0000 | address

    def write16(self, address: int, value: int) -> None:
        """Write a big-endian word at a short address."""
        self.uc.mem_write(self._address(address), struct.pack(">H", value & 0xFFFF))

    def read16(self, address: int) -> int:
        """Read a big-endian word at a short address."""
        return struct.unpack(">H", self.uc.mem_read(self._address(address), 2))[0]

    def write8(self, address: int, value: int) -> None:
        """Write one byte at an absolute address."""
        self.uc.mem_write(address, bytes([value & 0xFF]))

    def read8(self, address: int) -> int:
        """Read one byte at an absolute address."""
        return self.uc.mem_read(address, 1)[0]

    def call(self, pc: int, regs: dict[int, int] | None = None, count: int = 200_000) -> None:
        """Call the ROM function at pc with the given Unicorn registers, until it returns."""
        from unicorn.m68k_const import UC_M68K_REG_A7

        sp = STACK_TOP - 4
        self.uc.mem_write(sp, struct.pack(">I", STOP))
        self.uc.reg_write(UC_M68K_REG_A7, sp)
        for register, value in (regs or {}).items():
            self.uc.reg_write(register, value)
        self.uc.emu_start(pc, STOP, count=count)
