# USRobotics Courier

## Models

- Courier analog modems with XMF images (for example `main211.xmf`), and the
  captured 302 and 403 board images
- Courier I-modem (ISDN), with `.nac` and `.xmp` images
- Courier Quad (server modem)
- Courier 3453 B/C and 3453 C (V.Everything V.92)

## Processors

Intel 80186 or 386EX supervisor, TMS320C5x (C50, C51, C52) data pump.

## Location

The emulator is in [D-Modem/courier-emu](https://github.com/D-Modem/courier-emu).
modem-emu installs it with the `courier` extra, and `modem-emu courier ...`
runs its command line. Refer to [Architecture](../architecture.md) for the
reason.

## State

The harness runs the original firmware. The analog 403 firmware negotiates
V.34/LAPM and V.90/LAPM over SIP. The I-modem connects at V.90 to a RasFinder.
The Quad connects with V.34 and x2. Sustained reliability is not yet solved.
For the current state, refer to the courier-emu documentation
(`docs/current-boundary.md`).

## Other Courier emulators

D-Modem has a C++ board emulator of the Courier V.Everything (supervisor
7.3.14, DSP 3.0.13) in `dsp/test/hw/courier.hpp`. The D-Modem interop tests
use it.
