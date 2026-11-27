"""Unit tests for the Rockwell R65C19 / C39 core."""
import os

import pytest

from modem_emu.cores.r65c19 import (
    F_B, F_C, F_D, F_I, F_N, F_V, F_Z, OPCODES, R65C19, C39Banks, disasm, irq_vector,
)


def make(program: bytes, org: int = 0x2000, vectors: dict | None = None):
    """Return a core and its flat 64 KB memory, with ``program`` at ``org`` and the reset vector to it."""
    mem = bytearray(0x10000)
    mem[org:org + len(program)] = program
    mem[0xFFFE] = org & 0xFF
    mem[0xFFFF] = org >> 8
    for addr, target in (vectors or {}).items():
        mem[addr] = target & 0xFF
        mem[addr + 1] = target >> 8

    def write(a, v):
        """Write one byte of the flat memory."""
        mem[a] = v & 0xFF

    cpu = R65C19(mem.__getitem__, write)
    cpu.reset()
    return cpu, mem


def run(cpu, n):
    """Do ``n`` instructions."""
    for _ in range(n):
        cpu.step()


def test_opcode_map_has_every_opcode():
    """The map has 256 entries, and the removed 65C02 opcodes have the R65C19 meaning."""
    assert len(OPCODES) == 256
    assert OPCODES[0x01] == ("ora", "zpi")    # (zp,X) on a 65C02
    assert OPCODES[0x11] == ("ora", "ipx")    # (zp),Y on a 65C02
    assert OPCODES[0x89] == ("add", "imm")    # BIT #imm on a 65C02
    assert OPCODES[0x9C] == ("nop", "abx")    # STZ abs on a 65C02
    assert OPCODES[0xCB] == ("phi", "imp")    # WAI on a W65C02
    assert OPCODES[0xC2] == ("rba", "ima")
    assert OPCODES[0xF2] == ("bas", "amr")


def test_reset_uses_fffe_and_sets_i():
    """RES loads PC from $FFFE, sets I and clears D."""
    cpu, _ = make(b"\xea")
    assert cpu.pc == 0x2000
    assert cpu.flag(F_I) and not cpu.flag(F_D)


def test_indirect_modes_are_zp_and_zp_x():
    """Opcode $B1 is LDA (zp),X and $A1 is LDA (zp)."""
    cpu, mem = make(bytes([0xA2, 0x02, 0xB1, 0x10, 0xA8, 0xA1, 0x10]))
    mem[0x10], mem[0x11] = 0x00, 0x30
    mem[0x3000], mem[0x3002] = 0x55, 0x66
    run(cpu, 3)
    assert cpu.y == 0x66
    run(cpu, 1)
    assert cpu.a == 0x55


def test_jsr_pushes_next_opcode_and_rts_does_not_add_one():
    """JSR pushes the address of the next opcode. RTS returns to that address."""
    cpu, mem = make(bytes([0x20, 0x00, 0x30, 0xEA]))
    mem[0x3000] = 0x60
    cpu.s = 0xFF
    run(cpu, 1)
    assert mem[0x1FF] == 0x20 and mem[0x1FE] == 0x03
    run(cpu, 1)
    assert cpu.pc == 0x2003


def test_mpy_signed_result_in_a_and_y():
    """MPY: -3 x 5 = -15 = $FFF1. A is the high byte, Y the low byte, N is set."""
    cpu, _ = make(bytes([0xA9, 0xFD, 0xA0, 0x05, 0x02]))
    run(cpu, 3)
    assert (cpu.a, cpu.y) == (0xFF, 0xF1)
    assert cpu.flag(F_N)


def test_mpa_saturates_and_sets_v():
    """MPA adds A x Y to W. A positive overflow gives $7FFF and sets V."""
    cpu, _ = make(bytes([0xA9, 0x7F, 0x62, 0xA0, 0x7F, 0x12, 0x12, 0x12]))
    run(cpu, 2)                  # LDA #$7F, TAW: W = $7F00
    assert cpu.w == 0x7F00
    run(cpu, 2)                  # LDY #$7F, MPA: W = $7F00 + $3F01 -> saturated
    assert cpu.w == 0x7FFF and cpu.flag(F_V)


def test_clw_taw_twa():
    """TAW puts A in the high byte of W. TWA reads it back. CLW clears W and V."""
    cpu, _ = make(bytes([0xA9, 0x12, 0x62, 0xA9, 0x00, 0x72, 0x52]))
    run(cpu, 4)
    assert cpu.w == 0x1200 and cpu.a == 0x12
    cpu.p |= F_V
    run(cpu, 1)
    assert cpu.w == 0 and not cpu.flag(F_V)


def test_rba_sba_change_bits_and_load_a():
    """RBA and SBA (Apex trace encoding C2/D2 mask, address) change bits. A gets the mask."""
    cpu, mem = make(bytes([0xC2, 0x02, 0x03, 0x06, 0xD2, 0x80, 0x1A, 0x06]))
    mem[0x0603] = 0xFF
    run(cpu, 1)
    assert mem[0x0603] == 0xFD and cpu.a == 0x02
    run(cpu, 1)
    assert mem[0x061A] == 0x80 and cpu.a == 0x80


def test_bar_bas_branch_on_bits():
    """BAR branches when a mask bit is 0. BAS branches when a mask bit is 1."""
    # BAR $0700,#$08,+2 ; NOP ; NOP ; BAS $0700,#$01,-7 (back to BAR)
    prog = bytes([0xE2, 0x00, 0x07, 0x08, 0x02, 0xEA, 0xEA, 0xF2, 0x00, 0x07, 0x01, 0x00])
    cpu, mem = make(prog)
    mem[0x0700] = 0x00
    run(cpu, 1)
    assert cpu.pc == 0x2007      # bit 3 is 0: branch over the two NOPs
    mem[0x0700] = 0x08
    cpu.pc = 0x2000
    run(cpu, 1)
    assert cpu.pc == 0x2005      # bit 3 is 1: no branch
    cpu.pc = 0x2007
    run(cpu, 1)
    assert cpu.pc == 0x200C      # bit 0 is 0: BAS does not branch


def test_sti_and_exc():
    """STI stores an immediate byte in zero page. EXC swaps A with zp,X."""
    cpu, mem = make(bytes([0xB2, 0xC0, 0x3A, 0xA2, 0x01, 0xA9, 0x11, 0xD4, 0x3F]))
    run(cpu, 1)
    assert mem[0x3A] == 0xC0
    mem[0x40] = 0x22
    run(cpu, 3)
    assert cpu.a == 0x22 and mem[0x40] == 0x11


def test_jsb_uses_ffe0_table():
    """JSB n jumps through the vector at $FFE0 + 2n and pushes the next opcode address."""
    cpu, mem = make(bytes([0x3B]), vectors={0xFFE6: 0x4000})
    cpu.s = 0xFF
    run(cpu, 1)
    assert cpu.pc == 0x4000
    assert (mem[0x1FF], mem[0x1FE]) == (0x20, 0x01)


def test_threaded_code_jpi_nxt_tip():
    """JPI (ptr) puts the operand address in I and jumps. TIP returns. NXT follows the thread."""
    cpu, mem = make(bytes([0x0C, 0x00, 0x31, 0xEA]))
    mem[0x3100], mem[0x3101] = 0x00, 0x32
    mem[0x3200] = 0x03           # TIP
    run(cpu, 1)
    assert cpu.pc == 0x3200 and cpu.i == 0x2003
    run(cpu, 1)
    assert cpu.pc == 0x2003
    cpu.i = 0x3300
    mem[0x3300], mem[0x3301] = 0x34, 0x12
    mem[0x2003] = 0x8B           # NXT
    run(cpu, 1)
    assert cpu.pc == 0x1234 and cpu.i == 0x3302


def test_decimal_adc_and_sbc():
    """In decimal mode, $15 + $27 = $42, and $42 - $27 = $15."""
    cpu, _ = make(bytes([0xF8, 0x18, 0xA9, 0x15, 0x69, 0x27, 0x38, 0xE9, 0x27]))
    run(cpu, 4)
    assert cpu.a == 0x42 and not cpu.flag(F_C)
    run(cpu, 2)
    assert cpu.a == 0x15 and cpu.flag(F_C)


def test_add_ignores_carry():
    """ADD #imm adds without the carry."""
    cpu, _ = make(bytes([0x38, 0xA9, 0x01, 0x89, 0x01]))
    run(cpu, 3)
    assert cpu.a == 0x02


def test_irq_vector_and_rti():
    """An IRQ pushes PC and P (B clear), sets I and jumps. RTI returns."""
    cpu, mem = make(bytes([0x58, 0xEA, 0xEA]), vectors={irq_vector(3): 0x3000})
    mem[0x3000] = 0x40
    cpu.s = 0xFF
    run(cpu, 1)                  # CLI
    cpu.set_irq(irq_vector(3))
    run(cpu, 1)
    assert cpu.pc == 0x3000 and cpu.flag(F_I)
    assert not mem[0x1FD] & F_B
    cpu.set_irq(None)
    run(cpu, 1)
    assert cpu.pc == 0x2001 and not cpu.flag(F_I)


def test_brk_uses_nmi_vector_on_c39():
    """On the C39, BRK uses $FFFC and pushes the BRK address + 2."""
    cpu, mem = make(bytes([0x00, 0xFF]), vectors={0xFFFC: 0x3000})
    cpu.s = 0xFF
    run(cpu, 1)
    assert cpu.pc == 0x3000
    assert (mem[0x1FF], mem[0x1FE]) == (0x20, 0x02)
    assert mem[0x1FD] & F_B


def test_asr_neg_lab():
    """ASR keeps bit 7. NEG negates. LAB gives the absolute value."""
    cpu, _ = make(bytes([0xA9, 0x81, 0x3A, 0x1A, 0x13]))
    run(cpu, 2)
    assert cpu.a == 0xC0 and cpu.flag(F_C)
    run(cpu, 1)
    assert cpu.a == 0x40
    cpu.a = 0xF0
    run(cpu, 1)
    assert cpu.a == 0x10 and not cpu.flag(F_Z)


def test_disasm_new_instructions():
    """The disassembler shows the operand order of the new instructions."""
    mem = bytearray(0x10000)
    mem[0x4C4F:0x4C54] = bytes([0xE2, 0x1E, 0x06, 0x08, 0xFB])
    mem[0x2000:0x2003] = bytes([0xB2, 0xC0, 0x3A])
    assert disasm(mem.__getitem__, 0x4C4F) == ("bar $061e,#$08,$4c4f", 5)
    assert disasm(mem.__getitem__, 0x2000) == ("sti #$c0,$3a", 3)


def test_c39_banks_reset_and_es4():
    """After reset, BSR0 selects ES0. $0600-$07FF is ES4 only when PBS bit 1 is 0."""
    banks = C39Banks()
    assert banks.decode(0x0700) == ("es0", 0x0700)
    banks.pbs = 0xFD
    assert banks.decode(0x0700) == ("es4", 0x100)
    assert banks.decode(0xE123) == ("es3", 0xE123)
    assert not banks.internal_rom_enabled()
    banks.bsr[1] = 0x73          # ES3, A16-A13 = 3
    assert banks.decode(0x2004) == ("es3", 0x6004)
    banks.bsr[7] = 0xF7
    assert banks.internal_rom_enabled()


APEX = os.environ.get("MODEM_EMU_APEX_ROM")


@pytest.mark.skipif(not APEX, reason="set MODEM_EMU_APEX_ROM to the Apex 1.601-US flash image (128 KB)")
def test_apex_boot_reaches_data_pump_handshake():
    """The Apex 1.601 firmware boots on the core and waits for the data pump ready code in register 1C."""
    flash = open(APEX, "rb").read()
    ram = bytearray(0x20000)
    low = bytearray(0x600)
    pump = bytearray(0x200)
    banks = C39Banks()

    def read(a):
        """Read the CPU space of a minimal Apex board."""
        if a < 0x600:
            if 0x18 <= a < 0x20:
                return banks.bsr[a - 0x18]
            return banks.pbs if a == 5 else low[a]
        sel, off = banks.decode(a)
        return {"es4": pump, "es3": flash, "es2": ram}.get(sel, b"\xff" * 0x20000)[off]

    def write(a, v):
        """Write the CPU space of a minimal Apex board."""
        if a < 0x600:
            if 0x18 <= a < 0x20:
                banks.bsr[a - 0x18] = v
            elif a == 5:
                banks.pbs = v
            low[a] = v
            return
        sel, off = banks.decode(a)
        if sel == "es4":
            pump[off] = v
        elif sel == "es2":
            ram[off] = v

    cpu = R65C19(read, write)
    cpu.reset()
    for _ in range(20000):
        cpu.step()
    text, _ = disasm(read, cpu.pc)
    assert 0x4D10 <= cpu.pc <= 0x4D15, hex(cpu.pc)
    assert text in ("lda $061c", "cmp #$3c", "bne $4d10")
