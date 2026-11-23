# Telebit

## Models

- T2500, firmware GF7.03
- T3000, firmware LA3.00

## Processors

- T2500: Motorola 68000 controller, TMS32010 DSPs. The controller downloads
  the DSP programs.
- T3000: Motorola 68302 controller, TMS320C25 DSP. The controller downloads
  DSP program A (V.32bis and CCITT data pump), program B (PEP data pump) and
  program C (self-test) through the DSP host port at 0x800000.

## What is in modem-emu

| Part | File | State |
|---|---|---|
| TMS32010 core | `modem_emu/cores/c10.py` | Has the shared-RAM ports and the sample DMA of the T2500. It is not yet checked against a known output. |
| TMS320C25 core | `modem_emu/cores/c25.py` | Shared with ZyXEL. It can run the T3000 DSP programs, but we did not test this yet. |

## Open items

- Check the TMS32010 core against a known output (for example the 2125 Hz
  tone of program 1, bank B).
- Run the T3000 DSP programs on the TMS320C25 core.
- A 68000/68302 board model that boots the controller to an AT prompt.
