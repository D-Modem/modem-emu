"""Tests for the modem-emu command line."""
from modem_emu.cli import main


def test_list_shows_every_family(capsys):
    """The list command prints each family."""
    assert main(["list"]) == 0
    output = capsys.readouterr().out
    for name in ("courier", "zyxel", "telebit", "microcom"):
        assert name in output
