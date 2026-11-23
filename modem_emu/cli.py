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


def main(argv: list[str] | None = None) -> int:
    """Parse the command line and run the command."""
    parser = argparse.ArgumentParser(prog="modem-emu", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="list the modem families and their state")
    courier = sub.add_parser("courier", help="run the courier-emu CLI", add_help=False)
    courier.add_argument("rest", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.command == "list":
        return list_families()
    return run_courier(args.rest)


if __name__ == "__main__":
    sys.exit(main())
