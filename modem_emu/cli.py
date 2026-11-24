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


def main(argv: list[str] | None = None) -> int:
    """Parse the command line and run the command."""
    parser = argparse.ArgumentParser(prog="modem-emu", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="list the modem families and their state")
    courier = sub.add_parser("courier", help="run the courier-emu CLI", add_help=False)
    courier.add_argument("rest", nargs=argparse.REMAINDER)
    hayes = sub.add_parser("hayes-adc", help="compare the Hayes firmware ADC with the model")
    hayes.add_argument("rom", help="the 96 KB image: U12 then U13")
    args = parser.parse_args(argv)
    if args.command == "list":
        return list_families()
    if args.command == "hayes-adc":
        return hayes_adc_check(args.rom)
    return run_courier(args.rest)


if __name__ == "__main__":
    sys.exit(main())
