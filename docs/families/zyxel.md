# ZyXEL

## Models

- U-1496 (E and S variants, decoded images 6.15 and 5.06b)
- Elite 2864I (version 1.11)

## Processors

- U-1496: Motorola 68000 controller. The modem DSP code is in mask ROM.
- Elite 2864I: Motorola 68302 controller, and TMS320C25 RAM DSPs. These RAM
  DSPs are the ISDN PCM front end, not the modem data pump.

The EPROMs of the U-1496 have scrambled data lines. The images must be
decoded before use.

## What is in modem-emu

| Part | File | State |
|---|---|---|
| ROM-function caller | `modem_emu/families/zyxel/u1496.py` | Calls one ROM function with Unicorn (68020 model), and stops when it returns. It does not boot the modem. |
| TMS320C25 core | `modem_emu/cores/c25.py` | Instruction-level core from the TI user's guide (best effort). It runs the Elite DSP programs. |

## Use

The ROM-function caller gives test vectors for the ZyX modes (16800 and
19200 bit/s, 2742.857 baud, the frame of 8 symbols and the ring table). The
D-Modem write-up is `docs/dsp/zyxel-details.md` in D-Modem.

## Open items

- A 68000 board model that boots the U-1496 to an AT prompt
- The modem DSP is in mask ROM, and we do not have a dump. Thus, a full
  emulation of a ZyX call is not possible yet.
