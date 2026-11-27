# Rockwell

## Models

- Apex Data Mobile Plus V.34 PC Card, firmware 1.601-US (first target)
- Microcom DeskPorte FAST+ (Rockwell RC288DPi data pump, Z80182
  controller) (later)
- Rockwell 56K modems, for example the Sony MDM-5614G (RCV56DPF) (later)

## Processors

- The controller is a Rockwell R65C19-family MCU (C39 type). It is a 65C02
  core with more opcodes and banked memory. Some OEM modems use a Z80
  controller with a Rockwell data pump.
- The data pump is a Rockwell DSP. Its program is in mask ROM in the chip.
  The firmware files do not contain it.

## Documentation

| Item | Where |
|---|---|
| R65C19 data sheet | bitsavers, `components/rockwell/R65C19_Data_Sheet_199202.pdf` |
| C29/C39 and C40/L39 technical reference manuals | bitsavers, `components/rockwell/` |
| R65C19, C39 and L2800 CPU core (BSD-3-Clause) | MAME, `src/devices/cpu/m6502/r65c19.cpp` |
| Older data pumps and their interface registers | bitsavers, `components/rockwell/_dataBooks/` (1987 and 1989 data books) |
| AT command sets 144ACx, 288ACx, RPI | lysator.liu.se, `~mats/modem/reference.html` |

We found no public description of the instruction set of the data pump DSP.

## What is in modem-emu

Nothing yet. This page and the entry in the family table are the start.

## The approach

1. Emulate the controller and run its firmware.
2. Replace the data pump with a model of its 32 interface registers. The
   model gives the controller the same status bits as the real data pump.
   D-Modem does the modulation.
3. Research the real DSP separately.

With step 2, the emulator tests the Rockwell protocol layer: the AT
commands, V.42, MNP, MNP 10 and V.42bis. It does not test the Rockwell
modulation.

## Open items

- A C39 core in `modem_emu/cores/`
- An Apex board model that boots to an AT prompt
- The data pump model
- The DSP instruction set and a read of the mask ROM
