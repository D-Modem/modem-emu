# Hayes V-series: dump of the data pump ROM (U21)

Status: 2026-11-25. The program is tested on the C25 core. It is not yet
tested on a real chip.

## 1. Background

U21 on the V-series Smartmodem 9600 board is marked "04-00197 V1-0
D12015FN". It is a TMS320C25 with a Hayes mask ROM (probable). The ROM has
4096 words. The modulation, the training and the Express 96 handshake are
in this ROM. The Z80 controller cannot read it (refer to the project file
`hayes-dsp/research-and-plan.md`).

The TMS320C25 has no read protection. The UG (TI SPRU014, section 3.4)
says:

1. The MP/MC pin selects the external memory (MP/MC = 1) or the on-chip
   ROM (MP/MC = 0) at program addresses 0x0000-0x0FFF.
2. The pin is not latched. A program can change it while it runs.
3. TBLR reads the on-chip ROM when MP/MC is 0.

## 2. How the dump program operates

File: `modem_emu/families/hayes/u21dump.py`.

1. The DSP starts with MP/MC = 1. It runs the loader from external
   program memory at 0x0000.
2. The loader copies the dump code into block B0 (data 0x200), sets CNF to
   1 (B0 becomes program memory at 0xFF00) and jumps to 0xFF00. Thus the
   code continues to run when the external memory goes away.
3. The code sends `U21 READY` on the XF pin. Then it reads the four
   signature words at program address 0x07F0 again and again. It sends a
   `.` approximately each 0.3 s (at a 40 MHz crystal).
4. The operator sets MP/MC to 0. The signature words change (now they are
   ROM words), and the code sends `GO`.
5. The code reads 0x0000-0x0FFF with TBLR and sends each word as hex text.
   One line has 8 words: `0000: 44CB 204F ...`. After 4096 words it sends
   `END`. It does this 3 times.

The XF output is asynchronous serial: 8 data bits, no parity, 1 stop bit,
LSB first, idle at 1 (TTL levels, 0 V and 5 V). Connect a 5 V USB-serial
adapter: its RX to XF (U21 pin 56) and its GND to Vss. Do not connect its TX.

The bit time comes from the DSP clock. The default is a 40 MHz crystal
(CLKOUT1 = 10 MHz) and 9600 baud. If the text is not correct, measure the
crystal and make the image again with `--clock-mhz`.

## 3. Make the EPROM images

```sh
modem-emu hayes-u21-image out/u21dump --clock-mhz 40 --baud 9600
```

The command writes three files of 2K words:

| File | Use |
|---|---|
| `u21dump-16bit-be.bin` | One 16-bit memory (4 KB, big-endian) |
| `u21dump-high-d15-d8.bin` | The 8-bit memory on data bits D15-D8 |
| `u21dump-low-d7-d0.bin` | The 8-bit memory on data bits D7-D0 |

The meter checks (project file `hayes-dsp/research-and-plan.md`, section
2.1) tell which socket (U22 or U23) is on D15-D8, and which chip type the
sockets take.

## 4. Do the dump

1. Disconnect the power. Put the two programmed chips in U22 and U23.
2. Make MP/MC (U21 pin 1) controllable:
   - If pin 1 connects directly to ground, first lift pin 1 from the board
     or cut its trace. **Do not connect +5 V to a pin that connects to
     ground.**
   - Connect a 1 kΩ resistor from pin 1 to +5 V (pin 23). Connect a switch
     from pin 1 to ground (pin 10). Switch open = MP/MC 1. Switch closed =
     MP/MC 0.
3. Open the switch (MP/MC = 1). Start the terminal capture (9600
   8N1, log to a file).
4. Apply power. Look for `U21 READY` and then dots.
5. Close the switch (MP/MC = 0). Look for `GO`, then the lines of
   hex words. Wait for three `END` lines (approximately 80 seconds at 9600
   baud).
6. Disconnect the power. Remove the resistor and the switch, and put pin 1
   back as it was.

Then decode the capture:

```sh
modem-emu hayes-u21-decode capture.txt u21-04-00197-10.bin
```

The command compares the passes, writes the 8 KB image (big-endian
words), and prints some checksums. The ATI3 checksum of the pump ROM is
241. When we know the checksum method from the code, it is a good check of
the dump.

## 5. Possible problems

| Problem | Possible cause | Action |
|---|---|---|
| No text | The sockets do not connect to U21, XF is not free, or MP/MC was 0 at reset | Do the meter checks. MP/MC must be 1 at reset. |
| Text that is not correct | The clock is not 40 MHz | Measure Y1. Make the image again with `--clock-mhz`. |
| Dots, but no `GO` | MP/MC did not change to 0 | Measure U21 pin 1 with the switch closed |
| The passes do not agree | Noise on the XF line | Use a short wire. Use a lower baud rate. |

If XF is connected to other parts on the board, the dump program can
disturb them. In this case, lift U21 pin 56 or use the off-board fixture
(option B in the research file).
