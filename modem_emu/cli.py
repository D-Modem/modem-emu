"""The modem-emu command line: list the families, and run a family's own CLI."""
from __future__ import annotations

import argparse
import sys

from .families import FAMILIES


def list_families() -> int:
    """Print each family with its models, processors and emulator state."""
    for family in FAMILIES.values():
        print(f"{family.name:10} {family.models}")
        print(f"{'':10} processors: {family.processors}")
        print(f"{'':10} state:      {family.state}")
        print(f"{'':10} code:       {family.location}")
    return 0


def run_courier(args: list[str]) -> int:
    """Give the arguments to the courier-emu CLI, if courier-emu is installed."""
    try:
        from courier_emu.cli import main as courier_main
    except ImportError:
        print("courier-emu is not installed. Install it with: pip install 'modem-emu[courier]'",
              file=sys.stderr)
        return 2
    result = courier_main(args)
    return int(result or 0)


def hayes_adc_check(rom: str) -> int:
    """Run the firmware ADC encoder and decoder on the test vectors, and compare with the model."""
    import json
    from pathlib import Path

    from .families.hayes.adc import Encoder
    from .families.hayes.vseries import VSeriesAdc

    vectors = json.loads((Path(__file__).parent / "families" / "hayes" / "adc_vectors.json").read_text())
    bad = 0
    for vector in vectors["vectors"]:
        fw_enc, fw_dec, ref = VSeriesAdc(rom), VSeriesAdc(rom), Encoder()
        for i, frame in enumerate(vector["frames"]):
            data = bytes.fromhex(frame["in"])
            coded = fw_enc.encode_frame(data)
            same = coded == ref.frame(data) == bytes.fromhex(frame["out"])
            back = fw_dec.decode_frame(coded) == data
            if not (same and back):
                bad += 1
                print(f"{vector['name']} frame {i}: encoder {'ok' if same else 'DIFF'}, "
                      f"decoder {'ok' if back else 'DIFF'}")
        print(f"{vector['name']}: {len(vector['frames'])} frames")
    print("all frames agree" if bad == 0 else f"{bad} frames do not agree")
    return 0 if bad == 0 else 1


def hayes_u21_image(out: str, clock_mhz: float, baud: int, passes: int) -> int:
    """Write the U21 dump program as EPROM images: 16-bit, high bytes and low bytes."""
    from pathlib import Path

    from .families.hayes import u21dump

    image = u21dump.build_image(int(clock_mhz * 1e6 / 4), baud, passes)
    high, low = u21dump.split_bytes(image)
    base = Path(out)
    base.parent.mkdir(parents=True, exist_ok=True)
    files = {
        base.with_name(base.name + "-16bit-be.bin"): u21dump.to_bytes_be(image),
        base.with_name(base.name + "-high-d15-d8.bin"): high,
        base.with_name(base.name + "-low-d7-d0.bin"): low,
    }
    for path, data in files.items():
        path.write_bytes(data)
        print(f"{path}: {len(data)} bytes")
    print(f"crystal {clock_mhz} MHz, CLKOUT1 {clock_mhz / 4} MHz, XF serial {baud} baud 8N1, {passes} passes")
    return 0


def hayes_u21_decode(capture: str, out: str) -> int:
    """Change a captured U21 dump text into an 8 KB ROM image, and compare the passes."""
    from pathlib import Path

    from .families.hayes import u21dump

    text = Path(capture).read_text(errors="replace")
    passes = u21dump.decode_capture(text)
    if not passes:
        print("no dump found in the capture", file=sys.stderr)
        return 1
    words, problems = u21dump.merge_passes(passes)
    Path(out).write_bytes(u21dump.to_bytes_be(words))
    print(f"{len(passes)} passes, {len(words)} words written to {out}")
    if problems:
        print(f"{len(problems)} addresses are missing or do not agree, for example: "
              + " ".join(f"{a:04X}" for a in problems[:16]))
    for name, value in u21dump.checksums(words).items():
        print(f"{name}: {value}")
    return 0 if not problems and len(passes) >= 2 else 1


def rockwell_apex(image: str, dsp_ram: str | None, eeprom: str | None, commands: list[str]) -> int:
    """Boot the Apex Mobile Plus V.34 firmware, then send AT commands (from the arguments or from stdin).

    eeprom: a file for the 2 KB serial EEPROM. If the file exists, the board starts with its
    content. After the commands, the board writes the EEPROM content back to the file when
    the firmware changed it (for example, the factory profiles after the first boot, or AT&W).
    """
    from pathlib import Path

    from .families.rockwell.apex import ApexBoard, load_ram_dump

    board = ApexBoard(Path(image).read_bytes(),
                      load_ram_dump(dsp_ram) if dsp_ram else None,
                      Path(eeprom).read_bytes() if eeprom and Path(eeprom).exists() else None)
    board.boot()
    lines = commands or (line.rstrip("\r\n") for line in sys.stdin)
    for line in lines:
        sys.stdout.write(board.command(line))
        sys.stdout.flush()
    if eeprom and board.eeprom.dirty:
        Path(eeprom).write_bytes(bytes(board.eeprom.mem))
    return 0


def main(argv: list[str] | None = None) -> int:
    """Parse the command line and run the command."""
    parser = argparse.ArgumentParser(prog="modem-emu", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="list the modem families and their state")
    courier = sub.add_parser("courier", help="run the courier-emu CLI", add_help=False)
    courier.add_argument("rest", nargs=argparse.REMAINDER)
    hayes = sub.add_parser("hayes-adc", help="compare the Hayes firmware ADC with the model")
    hayes.add_argument("rom", help="the 96 KB image: U12 then U13")
    img = sub.add_parser("hayes-u21-image", help="write the U21 (TMS320C25) ROM dump program as EPROM images")
    img.add_argument("out", help="the start of the output file names, for example out/u21dump")
    img.add_argument("--clock-mhz", type=float, default=40.0, help="the DSP crystal (Y1) in MHz (default 40)")
    img.add_argument("--baud", type=int, default=9600, help="the serial bit rate on XF (default 9600)")
    img.add_argument("--passes", type=int, default=3, help="how many times to send the ROM (default 3)")
    dec = sub.add_parser("hayes-u21-decode", help="change a captured U21 dump text into a ROM image")
    dec.add_argument("capture", help="the terminal log of the XF serial output")
    dec.add_argument("out", help="the output ROM image (8 KB, big-endian words)")
    apex = sub.add_parser("rockwell-apex", help="boot the Apex Mobile Plus V.34 firmware and send AT commands")
    apex.add_argument("image", help="the 128 KB flash image (for example, firmware 1.601-US)")
    apex.add_argument("commands", nargs="*", help="AT command lines; with none, read lines from stdin")
    apex.add_argument("--dsp-ram", help="a DSP RAM dump (16-bit big-endian words) for the data pump model")
    apex.add_argument("--eeprom", help="a file for the 2 KB serial EEPROM: read at start if it exists, written back if it changed (default: a blank part)")
    args = parser.parse_args(argv)
    if args.command == "rockwell-apex":
        return rockwell_apex(args.image, args.dsp_ram, args.eeprom, args.commands)
    if args.command == "hayes-u21-image":
        return hayes_u21_image(args.out, args.clock_mhz, args.baud, args.passes)
    if args.command == "hayes-u21-decode":
        return hayes_u21_decode(args.capture, args.out)
    if args.command == "list":
        return list_families()
    if args.command == "hayes-adc":
        return hayes_adc_check(args.rom)
    return run_courier(args.rest)


if __name__ == "__main__":
    sys.exit(main())
