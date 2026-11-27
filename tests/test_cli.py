"""Tests for the modem-emu command line."""
from modem_emu.cli import main


def test_list_shows_every_family(capsys):
    """The list command prints each family."""
    assert main(["list"]) == 0
    output = capsys.readouterr().out
    for name in ("courier", "zyxel", "telebit", "hayes", "microcom"):
        assert name in output


def test_hayes_u21_image_and_decode(tmp_path, capsys):
    """The image command writes three files, and the decode command reads a capture."""
    from modem_emu.families.hayes import u21dump

    assert main(["hayes-u21-image", str(tmp_path / "u21dump")]) == 0
    assert (tmp_path / "u21dump-16bit-be.bin").stat().st_size == 4096
    assert (tmp_path / "u21dump-high-d15-d8.bin").stat().st_size == 2048
    lines = ["GO"]
    for base in range(0, u21dump.ROM_WORDS, 8):
        lines.append(f"{base:04X}:" + "".join(f" {base + i:04X}" for i in range(8)))
    capture = "\r\n".join(lines + ["END"] * 1) + "\r\n"
    (tmp_path / "cap.txt").write_text(capture + capture.replace("GO", "", 1))
    assert main(["hayes-u21-decode", str(tmp_path / "cap.txt"), str(tmp_path / "rom.bin")]) == 0
    data = (tmp_path / "rom.bin").read_bytes()
    assert len(data) == 8192 and data[2:4] == b"\x00\x01"
