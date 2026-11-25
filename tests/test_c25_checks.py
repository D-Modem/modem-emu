"""Instruction tests for the TMS320C25 core. The expected results agree with TI SPRU014 and the MAME core."""
from modem_emu.cores.c25 import C25
from modem_emu.cores.c25asm import Asm, IND_INC


def run_program(build, steps=50, **kw):
    """Assemble a program with the build function, run it for some steps, and return the core and the labels."""
    a = Asm(0)
    build(a)
    a.label("end")
    a.b("end")
    core = C25(a.words(), **kw)
    core.run(steps)
    return core, a.labels


def test_addh_keeps_carry_when_there_is_no_carry():
    """ADDH sets C on a carry. It does not clear C when there is no carry."""
    def prog(a):
        a.ldpk(0); a.lack(1); a.sacl(0x60); a.lack(0); a.subk(1)  # ACC = -1, then SUBK gives C = 0
        a.lack(0); a.addk(0)                                      # no change
    core, _ = run_program(prog)
    core.c = 1
    core.dm[0x60] = 1
    core.acc = 0
    core.exe(0x4860, 0)     # ADDH 60h
    assert core.c == 1 and core.acc == 0x10000


def test_subh_borrow_clears_carry_only():
    """SUBH clears C on a borrow. It does not set C when there is no borrow."""
    core = C25([])
    core.dm[0x60] = 1
    core.c = 0
    core.acc = 0x20000
    core.exe(0x4460, 0)     # SUBH 60h, no borrow
    assert core.c == 0 and core.acc == 0x10000
    core.c = 1
    core.acc = 0
    core.exe(0x4460, 0)     # borrow
    assert core.c == 0


def test_bnv_clears_ov_when_it_does_not_branch():
    """BNV sets OV to 0 when OV was 1 (it does not branch then)."""
    core = C25([0xF780, 0x0010])
    core.ov = 1
    core.step()
    assert core.ov == 0 and core.pc == 2


def test_tblr_repeat_does_not_change_acc():
    """In a repeat, TBLR counts its own program address. ACC does not change."""
    def prog(a):
        a.ldpk(0); a.lalk("table"); a.lrlk(1, 0x300); a.larp(1)
        a.rptk(2); a.tblr(IND_INC)
        a.b("over")
        a.label("table"); a.word(0x1111); a.word(0x2222); a.word(0x3333)
        a.label("over")
    core, labels = run_program(prog)
    assert core.dm[0x300:0x303] == [0x1111, 0x2222, 0x3333]
    assert core.acc == labels["table"]


def test_rpt_uses_low_eight_bits():
    """RPT uses only the low 8 bits of the data word."""
    core = C25([])
    core.dm[0x60] = 0x0102
    core.exe(0x4B60, 0)
    assert core.rpt == 3


def test_lst_does_not_use_next_arp_field():
    """LST with indirect addressing does not change ARB with the next-ARP field."""
    core = C25([])
    core.ar[1] = 0x300
    core.arp = 1
    core.arb = 5
    core.dm[0x300] = (2 << 13) | 7          # ARP = 2, DP = 7
    core.exe(0x5080 | 0x08 | 3, 0)          # LST *, AR3
    assert core.arp == 2 and core.dp == 7 and core.arb == 5


def test_abs_clears_carry():
    """ABS sets C to 0."""
    core = C25([])
    core.acc = -5
    core.c = 1
    core.exe(0xCE1B, 0)
    assert core.acc == 5 and core.c == 0


def test_subc_divides():
    """16 SUBC steps divide 1000 by 7: quotient 142, remainder 6."""
    core = C25([])
    core.dm[0x60] = 7
    core.acc = 1000
    for _ in range(16):
        core.exe(0x4760, 0)
    assert core.acc & 0xFFFF == 142 and (core.acc >> 16) == 6


def test_mp_mc_selects_rom_or_external_memory_at_any_time():
    """MP/MC = 1 gives external memory at 0x0000-0x0FFF; 0 gives the ROM. The pin is not latched."""
    core = C25([0xAAAA] * 0x1001, rom=[0x5555] * 0x1000, mp_mc=1)
    assert core.prd(0x0123) == 0xAAAA and core.prd(0x1000) == 0xAAAA
    core.mp_mc = 0
    assert core.prd(0x0123) == 0x5555 and core.prd(0x1000) == 0xAAAA
    core.pwr(0x0123, 0)
    assert core.rom[0x0123] == 0x5555


def test_xf_callback_gets_level_and_time():
    """SXF and RXF call xf_out with the level and the cycle count."""
    core = C25([0xCE0C, 0xCE0D])
    seen = []
    core.xf_out = lambda level, cycles: seen.append((level, cycles))
    core.run(2)
    assert seen == [(0, 1), (1, 2)]
