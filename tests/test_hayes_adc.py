"""Tests for Hayes ADC: the reference model against the firmware vectors, and the ROM caller."""
import json
import os
import random
from pathlib import Path

import pytest

from modem_emu.families.hayes.adc import Decoder, Encoder

VECTORS = json.loads((Path(__file__).parent.parent / "modem_emu" / "families" / "hayes" / "adc_vectors.json").read_text())


def test_reference_encoder_agrees_with_the_firmware_vectors():
    """Each frame of the 5 connections gives the output of the firmware encoder, byte for byte."""
    frames = 0
    for vector in VECTORS["vectors"]:
        enc, dec = Encoder(), Decoder()
        for frame in vector["frames"]:
            data, want = bytes.fromhex(frame["in"]), bytes.fromhex(frame["out"])
            assert enc.frame(data) == want, vector["name"]
            dec.feed(want)
            assert dec.take() == data, vector["name"]
            frames += 1
    assert frames == 43


def test_round_trip_with_runs_and_fa_bytes():
    """Random bytes, long runs and many FAh bytes come back unchanged, frame by frame."""
    rng = random.Random(3)
    texts = [bytes(rng.randrange(256) for _ in range(4000)),
             b"A" * 16 + b"B" * 31 + b"C" * 200 + b"\xFA" * 300,
             bytes(rng.choice(b"ab \r\n\xFA\x03\xFF\x00") for _ in range(5000))]
    for text in texts:
        enc, dec = Encoder(), Decoder()
        for i in range(0, len(text), 128):
            dec.feed(enc.frame(text[i:i + 128]))
        assert dec.take() == text


def test_fa00_sets_the_decoder_model_again():
    """FAh 00h in the stream sets the decoder to the initial model."""
    enc, dec = Encoder(), Decoder()
    dec.feed(enc.frame(b"etaoin shrdlu " * 20))
    dec.take()
    dec.feed(b"\xFA\x00" + Encoder().frame(b"a new connection"))
    assert dec.take() == b"a new connection"


ROM = os.environ.get("MODEM_EMU_HAYES_ROM")


@pytest.mark.skipif(not ROM, reason="set MODEM_EMU_HAYES_ROM to the 96 KB image (U12 + U13)")
def test_firmware_encoder_and_decoder_agree_with_the_model():
    """The firmware encoder gives the vectors, and the firmware decoder gives the input back."""
    pytest.importorskip("z80")
    from modem_emu.families.hayes.vseries import VSeriesAdc

    for vector in VECTORS["vectors"]:
        enc, dec = VSeriesAdc(ROM), VSeriesAdc(ROM)
        for frame in vector["frames"]:
            data, want = bytes.fromhex(frame["in"]), bytes.fromhex(frame["out"])
            assert enc.encode_frame(data) == want, vector["name"]
            assert dec.decode_frame(want) == data, vector["name"]


def test_caller_refuses_an_image_of_the_wrong_size():
    """An image that is not U12 + U13 is refused."""
    pytest.importorskip("z80")
    from modem_emu.families.hayes.vseries import VSeriesAdc

    with pytest.raises(ValueError):
        VSeriesAdc(b"\x00" * 0x10000)
