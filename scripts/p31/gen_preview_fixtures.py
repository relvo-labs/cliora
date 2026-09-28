#!/usr/bin/env python3
"""Generate the binary-preview browser fixtures (plan/31/07 §1, BP-07 E2E).

    python3 scripts/p31/gen_preview_fixtures.py OUTDIR

Standard library only and deterministic: the same bytes on every run, listed
with their SHA-256 in OUTDIR/SHA256SUMS, so a failure can be reproduced from
the file names alone. Nothing here is committed as a binary; the E2E specs run
this into a temporary directory. The full adversarial corpus (bombs, polyglots,
metadata budgets) is BP-09's; this is the minimal set the renderer tests need.

Each fixture's purpose is in its builder's docstring. None contains real data.
"""

from __future__ import annotations

import hashlib
import struct
import sys
import zlib
from collections.abc import Callable
from pathlib import Path

# --------------------------------------------------------------------------- PNG


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    body = kind + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))


def png(width: int, height: int, pixel: Callable[[int, int], tuple[int, int, int]]) -> bytes:
    """8-bit RGB, filter 0 on every row."""
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        for x in range(width):
            raw.extend(pixel(x, y))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + _png_chunk(b"IEND", b"")
    )


def ok_png() -> bytes:
    """1200x800 test chart: eight vertical bands with a diagonal, so fit-to-width
    and zoom are visibly correct (plan/31/07 §1 `ok.png`)."""

    def pixel(x: int, y: int) -> tuple[int, int, int]:
        band = x * 8 // 1200
        base = 40 + band * 26
        if abs(x * 800 - y * 1200) < 1600:  # the diagonal, about 2 px wide
            return (230, 230, 230)
        return (base, 90 + (y * 100 // 800), 200 - band * 18)

    return png(1200, 800, pixel)


# -------------------------------------------------------------------------- JPEG
#
# A baseline greyscale JPEG made only of flat 8x8 blocks, so every block is its
# DC coefficient plus an end-of-block: no DCT is needed, and the Huffman tables
# can be the two smallest valid ones. That keeps the encoder short enough to
# read, which is the point of generating rather than committing.


def _segment(marker: int, payload: bytes) -> bytes:
    return struct.pack(">HH", 0xFF00 | marker, len(payload) + 2) + payload


class _Bits:
    def __init__(self) -> None:
        self.out = bytearray()
        self.acc = 0
        self.n = 0

    def put(self, value: int, length: int) -> None:
        for i in range(length - 1, -1, -1):
            self.acc = (self.acc << 1) | ((value >> i) & 1)
            self.n += 1
            if self.n == 8:
                self.out.append(self.acc)
                if self.acc == 0xFF:
                    self.out.append(0x00)  # byte stuffing
                self.acc = 0
                self.n = 0

    def flush(self) -> bytes:
        if self.n:
            self.put((1 << (8 - self.n)) - 1, 8 - self.n)  # pad with ones
        return bytes(self.out)


def jpeg_flat(width: int, height: int, value: Callable[[int, int], int], orientation: int) -> bytes:
    """`value(bx, by)` is the grey level of block (bx, by). EXIF Orientation is
    written into APP1, so the decoder must rotate (`imageOrientation: from-image`)."""
    assert width % 8 == 0 and height % 8 == 0
    exif = (
        b"Exif\x00\x00"
        + b"MM\x00\x2a\x00\x00\x00\x08"  # big-endian TIFF, IFD0 at 8
        + struct.pack(">H", 1)  # one entry
        + struct.pack(">HHIHH", 0x0112, 3, 1, orientation, 0)  # Orientation, SHORT
        + struct.pack(">I", 0)  # no next IFD
    )
    dqt = b"\x00" + b"\x01" * 64  # table 0, all ones
    sof = struct.pack(">BHHB", 8, height, width, 1) + b"\x01\x11\x00"
    # DC table: categories 0..11 as twelve 4-bit codes 0000..1011.
    dc_bits = [0, 0, 0, 12] + [0] * 12
    dht_dc = b"\x00" + bytes(dc_bits) + bytes(range(12))
    # AC table: the end-of-block symbol only, as the 1-bit code "0".
    ac_bits = [1] + [0] * 15
    dht_ac = b"\x10" + bytes(ac_bits) + b"\x00"
    sos = b"\x01\x01\x00\x00\x3f\x00"

    bits = _Bits()
    previous = 0
    for by in range(height // 8):
        for bx in range(width // 8):
            dc = 8 * (value(bx, by) - 128)
            diff = dc - previous
            previous = dc
            category = abs(diff).bit_length()
            bits.put(category, 4)
            if category:
                bits.put(diff if diff > 0 else diff + (1 << category) - 1, category)
            bits.put(0, 1)  # EOB
    return (
        b"\xff\xd8"
        + _segment(0xE1, exif)
        + _segment(0xDB, dqt)
        + _segment(0xC0, sof)
        + _segment(0xC4, dht_dc)
        + _segment(0xC4, dht_ac)
        + _segment(0xDA, sos)
        + bits.flush()
        + b"\xff\xd9"
    )


def ok_orientation6_jpg() -> bytes:
    """64x32 stored, Orientation 6 (rotate 90 deg clockwise): shown 32x64. The dark
    half is stored on the left, so it must appear at the top when displayed."""
    return jpeg_flat(64, 32, lambda bx, by: 40 if bx < 4 else 220, orientation=6)


# --------------------------------------------------------------------------- GIF
#
# An "uncompressed" GIF: the LZW stream sends a clear code after every two
# pixels, so the code width never grows past 3 bits and no dictionary is needed.
# Valid for every decoder; just larger than a real one.


def _gif_lzw(indices: list[int]) -> bytes:
    clear, end = 4, 5
    codes: list[int] = []
    for i in range(0, len(indices), 2):
        codes.append(clear)
        codes.extend(indices[i : i + 2])
    codes.append(end)
    acc = n = 0
    out = bytearray()
    for code in codes:
        acc |= code << n
        n += 3
        while n >= 8:
            out.append(acc & 0xFF)
            acc >>= 8
            n -= 8
    if n:
        out.append(acc & 0xFF)
    blocks = bytearray([2])  # minimum code size
    for i in range(0, len(out), 255):
        piece = out[i : i + 255]
        blocks.append(len(piece))
        blocks.extend(piece)
    blocks.append(0)
    return bytes(blocks)


def ok_animated_gif() -> bytes:
    """48x24, two frames: the first is left-dark, the second right-dark. Only the
    first may ever be shown (OD-1)."""
    width, height = 48, 24
    palette = bytes([30, 30, 30, 220, 220, 220, 200, 60, 60, 60, 60, 200])
    out = bytearray(b"GIF89a")
    out += struct.pack("<HHBBB", width, height, 0xF1, 0, 0)  # GCT, 4 colours
    out += palette
    out += b"\x21\xff\x0bNETSCAPE2.0\x03\x01\x00\x00\x00"  # loop forever
    for frame in range(2):
        out += b"\x21\xf9\x04\x00\x32\x00\x00\x00"  # 0.5 s delay
        out += b"\x2c" + struct.pack("<HHHHB", 0, 0, width, height, 0)
        indices = [
            (0 if (x < width // 2) == (frame == 0) else 1) for y in range(height) for x in range(width)
        ]
        out += _gif_lzw(indices)
    out += b"\x3b"
    return bytes(out)


# ------------------------------------------------------------------------ driver

FIXTURES: dict[str, Callable[[], bytes]] = {
    "ok.png": ok_png,
    "ok-orientation6.jpg": ok_orientation6_jpg,
    "ok-animated.gif": ok_animated_gif,
}


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    out = Path(argv[1])
    out.mkdir(parents=True, exist_ok=True)
    sums = []
    for name, build in FIXTURES.items():
        data = build()
        (out / name).write_bytes(data)
        sums.append(f"{hashlib.sha256(data).hexdigest()}  {name}")
    (out / "SHA256SUMS").write_text("\n".join(sums) + "\n")
    print("\n".join(sums))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
