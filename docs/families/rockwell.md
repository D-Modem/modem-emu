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

| Part | File | State |
|---|---|---|
| R65C19 / C39 core | `modem_emu/cores/r65c19.py` | All opcodes, the interrupts, the C39 bank select logic and a disassembler. Refer to [the core page](../cores/r65c19.md). |
| C39 peripherals | `modem_emu/families/rockwell/c39.py` | The register page, Timer A and Timer B (interval mode), the host 16550A emulation (FIFOs, FSR, FIER, HCR), port A and the IRQ priority logic. |
| Data pump model | `modem_emu/families/rockwell/rc288.py` | The 32 interface registers, the DSP RAM window and the boot handshake. No signal processing. |
| Serial EEPROM | `modem_emu/families/rockwell/eeprom.py` | A 24C16 (2 KB) on bit-banged I2C. |
| Apex board | `modem_emu/families/rockwell/apex.py` | The memory map, the parts above, `boot()` and `command()`. |

### The Apex board

The Apex 1.601-US firmware boots on the board model and answers AT
commands. These answers are the same as on the real card:

| Command | Answer |
|---|---|
| `ATI0` | `33600` |
| `ATI3` | `Data/Fax Modem V.34 REV 1.601 June 10,1997` and `V1.600B1-V34_LP` |
| `ATI4`, `ATI5` | The same text as the real card |
| `ATI6` | `RC288DPi Rev 05BA` |
| `AT&V` | Stored profile 1 is the same as on the real card. Stored profile 0 on the real card has the owner's settings. |

The memory map:

| CPU address | Select | Device |
|---|---|---|
| $0000-$003F | internal | C39 registers |
| $0040-$05FF | internal | RAM |
| $0600-$07FF | ES4 (PBS bit 1 = 0) | Data pump interface registers |
| Banked by BSR0-BSR7 | ES3 | 128 KB flash (the firmware image) |
| Banked by BSR0-BSR7 | ES2 | RAM |

### The data pump boot handshake

We found these steps by running the firmware:

1. At reset, the DSP puts the ready code $3C, $EA in registers 1C and 1D.
   The firmware waits for it at $4D10.
2. The DSP shows its ROM revision in registers 13, 12, 11 and 00, as
   ASCII ("05BA"). The firmware also accepts "04BC".
3. The DSP loads its default configuration: CONF (register 12) = $76. The
   firmware waits for this at $4CD4.
4. The firmware reads DSP RAM word $08FE. It checks the high byte as a
   revision letter at $0BE9. If the check fails, the firmware sets error
   code 3 in $47 and blinks DCD.

The DSP RAM access: register 1C is the address low byte. In register 1D,
bit 7 starts the access, bit 5 selects a write and bits 0-3 are the address
high bits. Registers 18 and 19 hold the data word. The DSP clears bit 7
when the access is done.

### The serial EEPROM

Port A bit 7 is SCL and port A bit 1 is SDA. The firmware routines are at
$0B84-$0C5D. The control byte is $A0 or (block × 2) or R/W, with a 3-bit
block number. This agrees with a 24C16.

The firmware does a read before each byte write. When the EEPROM is blank,
the firmware writes 293 bytes of factory profiles. It waits for the write
cycle of each byte, thus this takes about 55 million CPU cycles. The board
`boot()` runs until the EEPROM has had no writes for 4 million cycles.

The firmware also sends the control byte $40 to a second I2C device. On
this board, no device answers.

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

- `ATI3` line 2: the model gives `CELLULAR DRIVER:  Lucent Rev 0.1`. The
  real card gives `Not Installed`. The cause is not known. The I2C device
  at $40 is possibly part of it.
- `ATI7`: the model gives no text. The real card gives `000`.
- The active profile after reset is not the same as stored profile 0.
- The data pump model does no signal processing. Step 4 is a digital link
  between two boards. Step 5 is the analog link through D-Modem.
- The DSP instruction set and a read of the mask ROM
