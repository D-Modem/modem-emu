# Microcom

## Models

- AX/9624c (and probably AX/9612c), ROM 0095001 revision 1.6, MNP class 6
- DeskPorte (FAST, 28.8P, 33.6S)

## Processors

- AX/9624c: NEC D70008 (Z80). The ROM is at CPU address 0x0000.
- DeskPorte FAST: Zilog Z80182 controller and a Rockwell V.FC data pump.

## State

Analysis only. There is no emulator yet. The AX/9624c ROM is disassembled.
The DeskPorte data pump runs from Rockwell mask ROM, which we do not have.

## Open items

- A Z80 board model that boots the AX/9624c to an AT prompt. This needs
  a Z80 core in `modem_emu/cores/`.
