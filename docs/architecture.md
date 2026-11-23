# Architecture

## Purpose

modem-emu holds the firmware emulators for all the modem families of the
D-Modem project. Each emulator runs the original firmware image of a modem.
D-Modem uses the emulators as test peers.

## Why the Courier is a dependency

The Courier emulator is in a different repository,
[D-Modem/courier-emu](https://github.com/D-Modem/courier-emu). That repository
is a fork of [cryan209/courier-emu](https://github.com/cryan209/courier-emu).
The upstream repository changes frequently. If we move its files into this
repository, each merge from the upstream gives conflicts in almost all files.
Thus, courier-emu stays a separate fork that is close to the upstream, and
modem-emu installs it as the `courier` extra.

## Layout

```
modem-emu/
  modem_emu/
    cli.py            the command line: modem-emu list, modem-emu courier ...
    cores/            CPU and DSP cores that more than one family can use
      c10.py          TMS32010 (Telebit T2500 DSPs)
      c25.py          TMS320C25 (ZyXEL Elite DSPs, Telebit T3000 DSPs)
    families/
      __init__.py     the family table and the state of each emulator
      zyxel/          ZyXEL U-1496 and Elite
      telebit/        Telebit T2500 and T3000
      microcom/       Microcom AX/9624c and DeskPorte
  tests/              one test file for each core and each family
  docs/               this documentation; docs/families/ has one page for each family
```

## Rules for a new family

1. Make a folder `modem_emu/families/<name>/`.
2. Add the family to `FAMILIES` in `modem_emu/families/__init__.py`.
3. Put a core in `modem_emu/cores/` when a different family can use it.
   Put board models (memory map, ports, latches) in the family folder.
4. Do not put firmware images in the repository. A test that needs an image
   must skip when the image is not available. Use a small synthetic program
   when possible.
5. Write a page in `docs/families/`. Tell the models, the processors, the
   state, and where the analysis is.
6. Each function must have a docstring.

## Cores that are in other repositories

| Core | Location |
|---|---|
| Intel 80186 and 386EX, TMS320C5x (Python and C++) | courier-emu |
| Intel 80186, TMS320C5x (C++, for the D-Modem interop tests) | D-Modem `dsp/test/hw/` |

D-Modem also has two complete C++ board emulators in `dsp/test/hw/`:
`courier.hpp` (Courier V.Everything) and `tc110.hpp` (3Com/Megahertz XJ5560
PC Card). They stay in D-Modem, because the C++ interop tests link them.
