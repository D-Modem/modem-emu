# Usage

## Installation

You must have Python 3.10 or later.

```sh
python3 -m venv .venv
.venv/bin/pip install -e '.[execute,test]'
```

The `execute` extra installs Unicorn. The ZyXEL ROM-function caller uses it.
The `hayes` extra installs the Z80 emulator (the package `z80`). The Hayes
ROM caller uses it. To add the Courier family, also install the `courier`
extra:

```sh
.venv/bin/pip install -e '.[execute,test,courier]'
```

## Command line

```sh
modem-emu list                          # the families and their state
modem-emu courier info main211.xmf      # any courier-emu command
modem-emu hayes-adc full.bin            # the Hayes firmware ADC against the model
modem-emu hayes-u21-image out/u21dump   # EPROM images of the U21 ROM dump program
modem-emu hayes-u21-decode cap.txt u21.bin  # the captured U21 dump text to a ROM image
modem-emu rockwell-apex apex.bin ATI3 --eeprom apex-ee.bin  # boot the Apex firmware, send AT commands
```

`modem-emu courier` gives all the next arguments to the courier-emu command
line. For those commands, refer to the courier-emu documentation.

### rockwell-apex

`modem-emu rockwell-apex IMAGE [COMMAND ...]` boots the Apex Mobile Plus
V.34 firmware (the 128 KB flash image) on the board model. Then it sends
each command line to the firmware and writes the answers. With no
commands, it reads command lines from stdin.

| Option | Function |
|---|---|
| `--eeprom FILE` | The file for the 2 KB serial EEPROM. If the file exists, the board starts with its content. If the firmware changes the EEPROM, the command writes the new content to the file. |
| `--dsp-ram FILE` | A DSP RAM dump of a real card (16-bit big-endian words). Without it, the data pump model starts with the words that the firmware needs. |

With a blank EEPROM, the firmware writes its factory profiles first. This
first boot takes about 50 seconds. Use `--eeprom` to keep the result, and
the next boots take about 20 seconds.

## Library use

```python
from modem_emu.cores.c25 import C25, load_words

core = C25(load_words("dspa_main.bin"))
core.inp[0] = lambda: 0          # an input port
core.run(10_000)
```

```python
from modem_emu.families.zyxel.u1496 import U1496Caller

caller = U1496Caller("u1496s-5.06b.bin")   # the decoded ROM image
caller.call(0x80000 + 0x1234)              # a ROM function
```

## Tests

```sh
.venv/bin/python -m pytest -q
```

The tests do not need firmware images. To also test the Hayes ROM caller,
set `MODEM_EMU_HAYES_ROM` to the 96 KB image (U12, then U13).

To also test the Apex board, set `MODEM_EMU_APEX_ROM` to the 1.601-US flash
image. These variables are optional:

- `MODEM_EMU_APEX_EEPROM`: an EEPROM image. Without it, the test starts
  with a blank EEPROM and takes about 50 seconds.
- `MODEM_EMU_APEX_DSP_RAM`: a DSP RAM dump of a real card.
