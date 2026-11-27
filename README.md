# modem-emu

modem-emu runs the original firmware of old modems in software. D-Modem uses
these emulators to test interoperability against modems that are rare or
broken. Each modem family has its own folder. The families share the CPU and
DSP cores.

| Family | State |
|---|---|
| USRobotics Courier | Complete harness in [courier-emu](https://github.com/D-Modem/courier-emu), used here as a dependency |
| ZyXEL U-1496, Elite | ROM-function caller and TMS320C25 core |
| Telebit T2500, T3000 | TMS32010 core (not yet verified) |
| Hayes V-series Smartmodem 9600 | ADC reference model and a Z80 caller of the ROM's ADC routines |
| Microcom AX/9624c, DeskPorte | Analysis only |
| Rockwell (Apex Mobile Plus V.34, then other Rockwell modems) | C39 controller core. The Apex firmware boots to the data pump handshake. |

```sh
pip install -e '.[execute]'      # add ,courier for the Courier family
modem-emu list
```

Firmware images are not in this repository. For the details, refer to
[the documentation](docs/README.md).

## Licence

AGPL-3.0-only ([LICENSE](LICENSE)), or a commercial licence from the D-Modem
Authors ([COMMERCIAL-LICENSE.md](COMMERCIAL-LICENSE.md)). Contributions come
with a contributor agreement ([CONTRIBUTING.md](CONTRIBUTING.md)). The
firmware images belong to their owners and are not under these terms.
