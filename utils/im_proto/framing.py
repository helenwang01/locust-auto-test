from __future__ import annotations
from typing import Tuple

# Simple varint (protobuf) encoding/decoding for unsigned ints

def encode_varint(value: int) -> bytes:
    out = bytearray()
    v = value & 0xFFFFFFFFFFFFFFFF
    while v > 0x7F:
        out.append((v & 0x7F) | 0x80)
        v >>= 7
    out.append(v)
    return bytes(out)


def decode_varint_from_reader(read_fn) -> int:
    # read_fn(n) -> bytes, reads exactly n bytes
    shift = 0
    result = 0
    while True:
        b = read_fn(1)
        if not b:
            raise EOFError("unexpected EOF while reading varint")
        byte = b[0]
        result |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            break
        shift += 7
        if shift > 63:
            raise ValueError("varint too long")
    return result


class VarintFramer:
    @staticmethod
    def frame(payload: bytes) -> bytes:
        return encode_varint(len(payload)) + payload

    @staticmethod
    def deframe(read_fn) -> bytes:
        length = decode_varint_from_reader(read_fn)
        data = read_fn(length)
        if len(data) != length:
            raise EOFError("short read on frame payload")
        return data


class Fixed32Framer:
    @staticmethod
    def frame(payload: bytes) -> bytes:
        if len(payload) > 0xFFFFFFFF:
            raise ValueError("payload too large for fixed32 frame")
        length = len(payload)
        prefix = length.to_bytes(4, byteorder="big")
        return prefix + payload

    @staticmethod
    def deframe(read_fn) -> bytes:
        prefix = read_fn(4)
        if len(prefix) != 4:
            raise EOFError("short read on fixed32 prefix")
        length = int.from_bytes(prefix, byteorder="big")
        data = read_fn(length)
        if len(data) != length:
            raise EOFError("short read on frame payload")
        return data


def select_framer(name: str):
    n = name.lower()
    if n in ("varint", "varint_length_delimited", "varint-delimited"):
        return VarintFramer
    if n in ("fixed", "fixed32", "fixed-32"):
        return Fixed32Framer
    raise ValueError(f"unknown framer: {name}")
