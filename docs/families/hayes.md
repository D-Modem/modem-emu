# Hayes

## Models

- V-series Smartmodem 9600 (1000US), firmware 1.4: U12 (04-00152, 64 KB)
  and U13 (04-00153, 32 KB)

## Processors

- A Z80 controller with banked ROM. The fixed ROM is at 0000h–5FFFh. The
  ROM banks of 8 KB go in the window at 6000h–7FFFh.
- The data pump is U21 (TI 04-00197, probably a TMS320C25 with mask ROM).
  We do not have a dump of it. [hayes-u21-dump.md](hayes-u21-dump.md)
  tells how to dump it.

## What is in modem-emu

| Part | File | State |
|---|---|---|
| ADC reference model | `modem_emu/families/hayes/adc.py` | The encoder and the decoder of Hayes ADC. The output agrees with the firmware encoder, byte for byte. |
| ADC ROM caller | `modem_emu/families/hayes/vseries.py` | Calls the ADC encoder (67C8h), the flush (6818h) and the decoder (6A9Ch) of ROM bank 10 in a Z80 emulator (the package `z80`). It does not boot the modem. |
| Test vectors | `modem_emu/families/hayes/adc_vectors.json` | 5 connections (43 frames): the DTE input and the output of the firmware encoder |
| U21 ROM dump program | `modem_emu/families/hayes/u21dump.py` | Makes the EPROM images for the dump, and decodes the captured text. Tested on the C25 core with a known ROM. Not yet tested on a chip. |

## Use

Make the image from the two EPROMs, then compare the firmware with the
model:

```sh
cat u12-27c512-64k.bin u13-27c256-32k.bin > full.bin
pip install -e '.[hayes]'
modem-emu hayes-adc full.bin
```

```python
from modem_emu.families.hayes.vseries import VSeriesAdc

enc = VSeriesAdc("full.bin")
frame = enc.encode_frame(b"ATDT5551212\r\n")   # the information field
```

D-Modem uses the vectors in its own test (`link/test/hayes_test.cpp`).
The D-Modem write-up is `docs/hayes-details.md` in D-Modem.

## Open items

- A Z80 board model that boots the modem to an AT prompt (SIO, CTC and
  the bank latch)
- The data pump (U21) is in mask ROM, and we do not have a dump. Thus, an
  emulation of an Express 96 call is not possible yet. The dump procedure
  is in [hayes-u21-dump.md](hayes-u21-dump.md).
