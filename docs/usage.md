# Usage

## Installation

You must have Python 3.10 or later.

```sh
python3 -m venv .venv
.venv/bin/pip install -e '.[execute,test]'
```

The `execute` extra installs Unicorn. The ZyXEL ROM-function caller uses it.
To add the Courier family, also install the `courier` extra:

```sh
.venv/bin/pip install -e '.[execute,test,courier]'
```

## Command line

```sh
modem-emu list                          # the families and their state
modem-emu courier info main211.xmf      # any courier-emu command
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

The tests do not need firmware images.
