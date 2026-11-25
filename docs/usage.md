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
```

`modem-emu courier` gives all the next arguments to the courier-emu command
line. For those commands, refer to the courier-emu documentation.

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
