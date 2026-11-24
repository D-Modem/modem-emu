"""Hayes ADC (Adaptive Data Compression), the reference model.

This is the model of the Hayes V-series Smartmodem 9600 firmware 1.4, ROM
bank 10: the encoder 67C8h, the flush 6818h, the nibble output 684Ch and
6863h, the model update 6EF1h, the decoder 6A9Ch and the initial values
7B2Ah. Each function names the firmware address that it copies. The model
came from the firmware analysis of the project (tools/adc_ref.py). The
tests compare it with the output of the firmware encoder.
"""
from __future__ import annotations


class Model:
    """The adaptive rank model that the encoder and the decoder share.

    count[r] is the frequency of rank r (E000h page), rank[c] is the rank of
    character c (E100h page), char[r] is the character at rank r (E200h page).
    t1, t2 and off are the code thresholds at FC0Fh, FC10h and FC11h.
    """

    def __init__(self) -> None:
        """Set the initial state (firmware 7B2Ah and 7BA7h)."""
        self.count = [0] * 256
        self.rank = list(range(256))
        self.char = list(range(256))
        self.tick = 0x80
        self.t1 = 4
        self.t2 = 0xBF
        self.off = 0x3C
        self.prev = 0
        self.run = -2

    def recalc(self) -> None:
        """Calculate t1, t2 and off again from the counts (firmware 6EFCh)."""
        low = 0
        e = 0
        found = False
        while True:
            total = 0
            for _ in range(16):
                low = (low - 1) & 0xFF
                total = (total + self.count[low]) & 0xFF
            if self.count[e] < total:
                found = True
                break
            old = e
            e += 1
            if old == 15:
                break
        k = (0 if e == 0 else e - 1) if found else 15
        self.t1 = k
        self.t2 = (~(k << 4)) & 0xFF
        self.off = (k << 4) - k

    def update(self, c: int) -> None:
        """Count character c and move it up in rank (firmware 6EF1h)."""
        self.tick -= 1
        if self.tick == 0:
            self.tick = 0x80
            self.recalc()
            self.count = [x >> 1 for x in self.count]
        r = self.rank[c]
        self.count[r] = (self.count[r] + 1) & 0xFF
        if r == 0:
            return
        new = self.count[r]
        for j in range(max(r - 16, 0), r):
            if self.count[j] < new:
                self.count[r] = self.count[j]
                self.count[j] = new
                cj = self.char[j]
                self.char[r] = cj
                self.rank[cj] = r
                self.char[j] = c
                self.rank[c] = j
                return


class Encoder:
    """Compress a byte stream into ADC code (firmware 67C8h)."""

    def __init__(self) -> None:
        """Set the initial model and no waiting nibble."""
        self.m = Model()
        self.half: int | None = None
        self.out = bytearray()

    def _byte(self, b: int) -> None:
        """Send one output byte. Send FAh as FAh 03h (firmware 6880h)."""
        self.out.append(b)
        if b == 0xFA:
            self.out.append(0x03)

    def nibble(self, n: int) -> None:
        """Send one 4-bit value (firmware 684Ch)."""
        if self.half is None:
            self.half = n & 0x0F
        else:
            self._byte((self.half << 4) | (n & 0x0F))
            self.half = None

    def octet(self, b: int) -> None:
        """Send one 8-bit value as two nibbles, high first (firmware 6863h)."""
        self.nibble(b >> 4)
        self.nibble(b & 0x0F)

    def _code(self, c: int) -> None:
        """Send the rank code of character c and update the model (67F0h)."""
        m = self.m
        r = m.rank[c]
        if r < m.t1:
            self.nibble(r)
        elif r <= m.t2:
            self.octet((r + m.off) & 0xFF)
        else:
            self.nibble(15)
            self.octet(r)
        m.update(c)

    def put(self, c: int) -> None:
        """Compress one character c (firmware 67C8h)."""
        m = self.m
        if c == m.prev:
            m.run += 1
            if m.run <= 0:
                self._code(c)
                return
            if m.run == 15:
                self.nibble(15)
                m.run = 0
            return
        if m.run >= 0:
            self.nibble(m.run)
        m.run = -2
        m.prev = c
        self._code(c)

    def flush(self) -> None:
        """End the frame on a byte boundary (firmware 6818h)."""
        m = self.m
        if self.half is not None:
            hi = self.half
            self.half = None
            if m.run >= 0:
                b = (hi << 4) | m.run
                m.run = -2
                self._byte(b)
            else:
                self.out.append((hi << 4) | 0x0F)
                self.out += b"\xFA\xFF"
        elif m.run >= 0:
            b = (m.run << 4) | 0x0F
            m.run = -2
            self.out.append(b)
            self.out += b"\xFA\xFF"

    def take(self) -> bytes:
        """Return the output bytes made since the last call."""
        data = bytes(self.out)
        self.out = bytearray()
        return data

    def frame(self, data: bytes) -> bytes:
        """Compress the DTE bytes of one frame, flush, and return the information field."""
        for c in data:
            self.put(c)
        self.flush()
        return self.take()


class Decoder:
    """Expand ADC code back into bytes (firmware 6A9Ch)."""

    def __init__(self) -> None:
        """Set the initial model and the first-nibble state."""
        self.m = Model()
        self.state = 0
        self.hi = 0
        self.out = bytearray()

    def _char(self, c: int) -> None:
        """Write a decoded character and update the model (6B19h)."""
        m = self.m
        if c == m.prev:
            m.run += 1
        else:
            m.prev = c
            m.run = -2
        self.out.append(c)
        m.update(c)

    def _nibble(self, n: int) -> None:
        """Use one 4-bit value of the input (firmware 6AA2h)."""
        m = self.m
        if self.state == 0 and m.run >= 0:
            m.run = 0 if n == 15 else -2
            self.out += bytes([m.prev]) * n
            return
        if self.state == 0:
            if n < m.t1:
                self._char(m.char[n])
            else:
                self.hi = n << 4
                self.state = 1
        elif self.state == 1:
            v = ((self.hi | n) - m.off) & 0xFF
            if v <= m.t2:
                self.state = 0
                self._char(m.char[v])
            else:
                self.hi = n << 4
                self.state = 2
        else:
            self.state = 0
            self._char(m.char[self.hi | n])

    def feed(self, data: bytes) -> None:
        """Decode the bytes of one frame (firmware 6B39h, FAh rules 6B8Dh)."""
        esc = False
        for b in data:
            if esc:
                esc = False
                if b == 0x03:
                    b = 0xFA
                elif b == 0xFF:
                    self.state = 0
                    if self.m.run >= 1:
                        self.m.run = -2
                    continue
                elif b < 0x02:
                    self.m = Model()
                    self.state = 0
                    continue
                else:
                    continue
            elif b == 0xFA:
                esc = True
                continue
            self._nibble(b >> 4)
            self._nibble(b & 0x0F)

    def take(self) -> bytes:
        """Return the decoded bytes made since the last call."""
        data = bytes(self.out)
        self.out = bytearray()
        return data
