"""Tests for the ZyXEL U-1496 ROM-function caller."""
import pytest

pytest.importorskip("unicorn")

from modem_emu.families.zyxel.u1496 import U1496Caller  # noqa: E402


def test_call_runs_a_rom_function_until_it_returns():
    """A ROM function that writes a short-address word and returns runs to the end."""
    # MOVE.W #$1234,($0100).W ; RTS
    rom = bytes.fromhex("31FC12340100" "4E75")
    caller = U1496Caller(rom)
    caller.call(0x80000)
    assert caller.read16(0x100) == 0x1234
