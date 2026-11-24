"""Call the ADC routines of the Hayes V-series 9600 firmware 1.4 in a Z80 emulator.

This is not a board model. It maps the fixed ROM (0000h-5FFFh) and ROM bank
10 (at 6000h-7FFFh) of the image, puts the initial ADC values in RAM, and
calls one routine until it returns. The output routine at 654Bh is replaced
with a stub that sends each byte to port FEh. Use it to make test vectors of
the firmware encoder, and to decode with the firmware decoder.

The image is the two EPROMs one after the other:
``cat u12-27c512-64k.bin u13-27c256-32k.bin > full.bin`` (96 KB).
"""
from __future__ import annotations

from pathlib import Path

BANK_SIZE = 0x2000
ADC_BANK = 10
IMAGE_SIZE = 0x18000
ENCODE = 0x67C8
FLUSH = 0x6818
DECODE = 0x6A9C
OUT_STUB = 0x654B
HALT_STUB = 0x9000
STACK = 0x8FF0
INIT_VALUES = 0x7B34
DEC_BUF = 0xA800
DEC_OUT = 0xFD00


class VSeriesAdc:
    """A Z80 with the fixed ROM, ROM bank 10 and the ADC RAM of one direction."""

    def __init__(self, image: bytes | str | Path) -> None:
        """Load the 96 KB image (bytes or a file path) and set the initial ADC state."""
        import z80

        if not isinstance(image, (bytes, bytearray)):
            image = Path(image).read_bytes()
        if len(image) != IMAGE_SIZE:
            raise ValueError(f"the image is {len(image)} bytes; it must be {IMAGE_SIZE} (U12 + U13)")
        mem = bytearray(0x10000)
        mem[0:0x6000] = image[0:0x6000]
        bank = image[ADC_BANK * BANK_SIZE:(ADC_BANK + 1) * BANK_SIZE]
        mem[0x6000:0x8000] = bank
        mem[OUT_STUB:OUT_STUB + 3] = bytes([0xD3, 0xFE, 0xC9])   # OUT (FEh),A ; RET
        mem[HALT_STUB] = 0x76                                     # HALT
        start = INIT_VALUES - 0x6000
        mem[0xFC0E:0xFC0E + 30] = bank[start:start + 30]
        for i in range(256):
            mem[0xE000 + i] = 0
            mem[0xE100 + i] = i
            mem[0xE200 + i] = i
        self.m = z80.Z80Machine()
        self.m.set_memory_block(0, bytes(mem))
        self.out = bytearray()
        self.m.set_output_callback(self._port)
        self.m.set_input_callback(lambda port: 0)

    def _port(self, port: int, value: int) -> None:
        """Keep the bytes that the output stub sends to port FEh."""
        if port & 0xFF == 0xFE:
            self.out.append(value)

    def call(self, pc: int, a: int = 0) -> int:
        """Call the routine at pc with register A, run until it returns, and give the carry flag."""
        m = self.m
        m.sp = STACK
        m.memory[STACK] = HALT_STUB & 0xFF
        m.memory[STACK + 1] = HALT_STUB >> 8
        m.iy = 0x9100
        m.ix = 0x8E80
        m.c = 0x81
        m.a = a
        m.pc = pc
        m.halted = False
        for _ in range(1000):
            m.ticks_to_stop = 100000
            m.run()
            if m.halted:
                return m.f & 1
        raise RuntimeError(f"the routine did not return (PC {m.pc:04X})")

    def encode_frame(self, data: bytes) -> bytes:
        """Encode the DTE bytes of one frame with the firmware (67C8h, then 6818h)."""
        for c in data:
            self.call(ENCODE, c)
        self.call(FLUSH)
        frame = bytes(self.out)
        self.out.clear()
        return frame

    def decode_frame(self, frame: bytes) -> bytes:
        """Decode one received information field with the firmware (6A9Ch)."""
        m = self.m
        for j, b in enumerate(frame):
            m.memory[DEC_BUF + j] = b
        m.memory[0xFC06] = DEC_BUF & 0xFF
        m.memory[0xFC07] = DEC_BUF >> 8
        m.memory[0xFC0A] = len(frame) & 0xFF
        m.memory[0xFC0B] = len(frame) >> 8
        m.memory[0xFC03] = 0
        result = bytearray()
        while True:
            m.memory[0xFC04] = 0
            self.call(DECODE)
            k = m.memory[0xFC04]
            result += bytes(m.memory[DEC_OUT:DEC_OUT + k])
            if k == 0:
                return bytes(result)
