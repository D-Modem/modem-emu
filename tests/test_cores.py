"""Unit tests for the shared DSP cores."""
from modem_emu.cores import c10, c25


def test_signed_helpers():
    """The sign helpers give signed 16-bit and 32-bit values."""
    assert c25.s16(0xFFFF) == -1 and c25.s16(0x7FFF) == 0x7FFF
    assert c25.s32(0x80000000) == -0x80000000 and c10.s32(0xFFFFFFFF) == -1


def test_c25_add_saturates_when_ovm_is_set():
    """An add that overflows sets OV, and saturates only when OVM is 1."""
    core = c25.C25([])
    core.setacc_add(0x7FFFFFFF, 1)
    assert core.ov == 1 and core.acc == -0x80000000
    core.ov = 0
    core.ovm = 1
    core.setacc_add(0x7FFFFFFF, 1)
    assert core.ov == 1 and core.acc == 0x7FFFFFFF


def test_c25_stack_keeps_eight_levels():
    """The hardware stack keeps the last eight words. A pop copies the bottom word up."""
    core = c25.C25([])
    for value in range(10):
        core.push(value)
    assert [core.pop() for _ in range(10)] == [9, 8, 7, 6, 5, 4, 3, 2, 2, 2]


def test_c25_block_b0_moves_with_cnf():
    """Block B0 is data memory at 0x200 when CNF is 0, and program memory at 0xFF00 when CNF is 1."""
    core = c25.C25([])
    core.wr(0x200, 0x1234)
    core.cnf = 1
    assert core.prd(0xFF00) == 0x1234


def test_c10_shared_ram_ports():
    """Port 5 sets the shared-RAM address; port 0 reads and increments it."""
    shared = [0] * 0x4000
    shared[0x10:0x12] = [0xAAAA, 0x5555]
    core = c10.C10([], shared)
    core.port_out(5, 0x10)
    assert core.port_in(0) == 0xAAAA and core.port_in(0) == 0x5555 and core.addr == 0x12
