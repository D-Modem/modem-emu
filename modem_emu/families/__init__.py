"""The modem families, and the state of the emulator for each family."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Family:
    """One modem family: its models, its processors and the state of its emulator."""

    name: str
    models: str
    processors: str
    state: str
    location: str


FAMILIES: dict[str, Family] = {
    "courier": Family(
        name="courier",
        models="USRobotics Courier (XMF analog, I-modem, Quad, 3453 B/C and C)",
        processors="Intel 80186 / 386EX, TMS320C5x",
        state="Runs the firmware. V.34, V.90 and x2 connect. Sustained reliability is open.",
        location="courier-emu (dependency, extra 'courier')",
    ),
    "zyxel": Family(
        name="zyxel",
        models="ZyXEL U-1496, Elite 2864I",
        processors="Motorola 68000, TMS320C25",
        state="Calls single ROM functions (u1496). TMS320C25 core. No boot.",
        location="modem_emu.families.zyxel, modem_emu.cores.c25",
    ),
    "telebit": Family(
        name="telebit",
        models="Telebit T2500, T3000",
        processors="Motorola 68000, TMS32010, TMS320C25",
        state="TMS32010 core for the T2500 DSP programs, not yet checked. No boot.",
        location="modem_emu.cores.c10",
    ),
    "microcom": Family(
        name="microcom",
        models="Microcom AX/9624c, DeskPorte",
        processors="NEC D70008 (Z80)",
        state="Analysis only. No emulator yet.",
        location="-",
    ),
}
