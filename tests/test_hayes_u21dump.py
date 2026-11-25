"""Tests for the U21 (TMS320C25) mask ROM dump program, on the C25 core."""
import random

from modem_emu.cores.c25 import C25
from modem_emu.families.hayes import u21dump


def fake_rom(seed=7):
    """Return a random 4096-word ROM."""
    rng = random.Random(seed)
    return [rng.randrange(0x10000) for _ in range(u21dump.ROM_WORDS)]


def test_image_fits_and_has_signature():
    """The image is 2K words, the B0 code fits in 256 words, and the signature is at SIG_ADDR."""
    for baud in (1200, 9600, 19200, 115200):
        assert len(u21dump.build_b0(10e6 / baud)) <= u21dump.B0_SIZE
    image = u21dump.build_image()
    assert len(image) == u21dump.EXT_WORDS
    assert image[u21dump.SIG_ADDR:u21dump.SIG_ADDR + 4] == u21dump.SIGNATURE
    high, low = u21dump.split_bytes(image)
    assert len(high) == len(low) == 2048 and high[0] == image[0] >> 8


def test_bit_edges_are_on_the_bit_grid():
    """Inside each character, every XF edge is a whole number of bit times after the start edge."""
    cpb = round(10e6 / 9600)    # the program rounds the bit time to whole cycles
    core = C25(u21dump.build_image(10_000_000, 9600), rom=fake_rom())
    edges = []
    core.xf_out = lambda level, cycles: edges.append((cycles, level))
    core.run(40000)
    starts = 0
    i = 0
    while i < len(edges):
        t0, level = edges[i]
        if level == 0:
            starts += 1
            j = i + 1
            while j < len(edges) and edges[j][0] < t0 + 9.5 * cpb:
                k = (edges[j][0] - t0) / cpb
                assert abs(k - round(k)) * cpb <= 1.0, (t0, edges[j])
                j += 1
            i = j
        else:
            i += 1
    assert starts > 5


def test_dump_reads_back_a_known_rom_three_passes():
    """Three passes at 9600 baud of the first 32 words agree with the ROM."""
    rom = fake_rom()
    text = u21dump.simulate(rom, baud=9600, passes=3, count=32)
    assert "U21 READY" in text
    passes = u21dump.decode_capture(text, 32)
    words, problems = u21dump.merge_passes(passes)
    assert len(passes) == 3 and words == rom[:32] and problems == []


def test_dump_reads_back_the_full_rom():
    """One fast pass reads all 4096 words."""
    rom = fake_rom(3)
    text = u21dump.simulate(rom, baud=250000, passes=1)
    words, problems = u21dump.merge_passes(u21dump.decode_capture(text))
    assert words == rom and problems == []


def test_merge_reports_a_bad_word():
    """A word that one pass reads differently is reported."""
    good = [1, 2, 3, 4]
    words, problems = u21dump.merge_passes([good, [1, 2, 9, 4], good])
    assert words == good and problems == [2]
