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


# --------------------------------------------------------------------- AES, RC4
#
# The encrypted PDFs need RC4 (40-bit, R2), AES-128-CBC (AESV2, R4) and
# AES-256-CBC plus the R6 password hash (AESV3). Encryption only, straight from
# FIPS-197, so the generator keeps to the standard library. Correctness is
# checked end to end: PDF.js opening the permissions-only files without a
# prompt and drawing their text is only possible if every step here is right.


def rc4(key: bytes, data: bytes) -> bytes:
    s = list(range(256))
    j = 0
    for i in range(256):
        j = (j + s[i] + key[i % len(key)]) & 0xFF
        s[i], s[j] = s[j], s[i]
    out = bytearray()
    i = j = 0
    for byte in data:
        i = (i + 1) & 0xFF
        j = (j + s[i]) & 0xFF
        s[i], s[j] = s[j], s[i]
        out.append(byte ^ s[(s[i] + s[j]) & 0xFF])
    return bytes(out)


def _xtime(a: int) -> int:
    return ((a << 1) ^ 0x1B) & 0xFF if a & 0x80 else a << 1


def _sbox() -> list[int]:
    box = [0] * 256
    p = q = 1
    while True:
        p = p ^ ((p << 1) & 0xFF) ^ (0x1B if p & 0x80 else 0)  # p *= 3
        q ^= q << 1
        q ^= q << 2
        q ^= q << 4
        q &= 0xFF
        if q & 0x80:
            q ^= 0x09  # q /= 3
        x = q ^ (q << 1 | q >> 7) ^ (q << 2 | q >> 6) ^ (q << 3 | q >> 5) ^ (q << 4 | q >> 4)
        box[p] = (x ^ 0x63) & 0xFF
        if p == 1:
            break
    box[0] = 0x63
    return box


SBOX = _sbox()


def _expand_key(key: bytes) -> list[list[int]]:
    nk = len(key) // 4
    rounds = nk + 6
    words = [list(key[4 * i : 4 * i + 4]) for i in range(nk)]
    rcon = 1
    for i in range(nk, 4 * (rounds + 1)):
        t = list(words[i - 1])
        if i % nk == 0:
            t = [SBOX[b] for b in t[1:] + t[:1]]
            t[0] ^= rcon
            rcon = _xtime(rcon)
        elif nk > 6 and i % nk == 4:
            t = [SBOX[b] for b in t]
        words.append([a ^ b for a, b in zip(words[i - nk], t)])
    return [sum(words[4 * r : 4 * r + 4], []) for r in range(rounds + 1)]


def _encrypt_block(round_keys: list[list[int]], block: bytes) -> bytes:
    s = [b ^ k for b, k in zip(block, round_keys[0])]
    last = len(round_keys) - 1
    for r in range(1, last + 1):
        s = [SBOX[b] for b in s]
        s = [s[(i + 4 * (i % 4)) % 16] for i in range(16)]  # ShiftRows (column-major)
        if r != last:
            mixed = []
            for c in range(4):
                a = s[4 * c : 4 * c + 4]
                t = a[0] ^ a[1] ^ a[2] ^ a[3]
                mixed += [a[i] ^ t ^ _xtime(a[i] ^ a[(i + 1) % 4]) for i in range(4)]
            s = mixed
        s = [b ^ k for b, k in zip(s, round_keys[r])]
    return bytes(s)


def aes_cbc(key: bytes, iv: bytes, data: bytes, pad: bool = True) -> bytes:
    if pad:
        n = 16 - len(data) % 16
        data += bytes([n]) * n
    assert len(data) % 16 == 0
    keys = _expand_key(key)
    out = bytearray()
    prev = iv
    for i in range(0, len(data), 16):
        prev = _encrypt_block(keys, bytes(a ^ b for a, b in zip(data[i : i + 16], prev)))
        out += prev
    return bytes(out)


def aes_ecb_block(key: bytes, block: bytes) -> bytes:
    return _encrypt_block(_expand_key(key), block)


# --------------------------------------------------------------------------- PDF


class Name(str):
    """A PDF name, written /like-this."""


class Raw(bytes):
    """Pre-serialised PDF syntax, written as is."""


class Ref:
    def __init__(self, num: int) -> None:
        self.num = num


class Stream:
    def __init__(self, dictionary: dict[str, object], data: bytes) -> None:
        self.dictionary = dictionary
        self.data = data


# Standard padding string, ISO 32000-1 7.6.3.3.
PAD = bytes.fromhex("28bf4e5e4e758a4164004e56fffa01082e2e00b6d0683e802f0ca9fe6453697a")


class Encryption:
    """One of the three standard security handlers the fixtures need. `user` is
    the password needed to open; an empty one means permissions-only."""

    def __init__(self, scheme: str, user: str, owner: str, doc_id: bytes) -> None:
        self.scheme = scheme
        self.doc_id = doc_id
        # Print, modify, copy and annotate all denied; nothing the preview offers
        # anyway, which is why a permissions-only file must still render (OD-8).
        self.p = -3904
        u, o = user.encode(), owner.encode()
        if scheme == "rc4-40":
            self._rc4(u, o, rev=2, length=5)
        elif scheme == "aes-128":
            self._rc4(u, o, rev=4, length=16)
        elif scheme == "aes-256":
            self._aes256(u, o)
        else:
            raise ValueError(scheme)

    def _rc4(self, u: bytes, o: bytes, rev: int, length: int) -> None:
        padded_u = (u + PAD)[:32]
        digest = hashlib.md5((o + PAD)[:32]).digest()
        if rev >= 3:
            for _ in range(50):
                digest = hashlib.md5(digest[:length]).digest()
        owner_key = digest[:length]
        self.O = rc4(owner_key, padded_u)
        if rev >= 3:
            for i in range(1, 20):
                self.O = rc4(bytes(b ^ i for b in owner_key), self.O)
        key = hashlib.md5(padded_u + self.O + struct.pack("<i", self.p) + self.doc_id).digest()
        if rev >= 3:
            for _ in range(50):
                key = hashlib.md5(key[:length]).digest()
        self.key = key[:length]
        if rev == 2:
            self.U = rc4(self.key, PAD)
        else:
            value = rc4(self.key, hashlib.md5(PAD + self.doc_id).digest())
            for i in range(1, 20):
                value = rc4(bytes(b ^ i for b in self.key), value)
            self.U = value + bytes(16)
        self.rev = rev

    @staticmethod
    def _hash_r6(password: bytes, salt: bytes, udata: bytes) -> bytes:
        k = hashlib.sha256(password + salt + udata).digest()
        i = 0
        while True:
            k1 = (password + k + udata) * 64
            e = aes_cbc(k[:16], k[16:32], k1, pad=False)
            choice = sum(e[:16]) % 3
            k = [hashlib.sha256, hashlib.sha384, hashlib.sha512][choice](e).digest()
            i += 1
            if i >= 64 and e[-1] <= i - 32:
                return k[:32]

    def _aes256(self, u: bytes, o: bytes) -> None:
        seed = hashlib.sha256(b"cliora-bp07-aes256" + u + o).digest()
        self.key = seed
        uvs, uks, ovs, oks = seed[:8], seed[8:16], seed[16:24], seed[24:32]
        self.U = self._hash_r6(u, uvs, b"") + uvs + uks
        self.UE = aes_cbc(self._hash_r6(u, uks, b""), bytes(16), self.key, pad=False)
        self.O = self._hash_r6(o, ovs, self.U) + ovs + oks
        self.OE = aes_cbc(self._hash_r6(o, oks, self.U), bytes(16), self.key, pad=False)
        perms = struct.pack("<i", self.p) + b"\xff\xff\xff\xff" + b"Tadb" + b"bp07"
        self.Perms = aes_ecb_block(self.key, perms)
        self.rev = 6

    def dictionary(self) -> dict[str, object]:
        hexs = lambda b: Raw(b"<" + b.hex().encode() + b">")  # noqa: E731
        if self.scheme == "rc4-40":
            return {
                "Filter": Name("Standard"),
                "V": 1,
                "R": 2,
                "O": hexs(self.O),
                "U": hexs(self.U),
                "P": self.p,
            }
        if self.scheme == "aes-128":
            return {
                "Filter": Name("Standard"),
                "V": 4,
                "R": 4,
                "Length": 128,
                "CF": {"StdCF": {"CFM": Name("AESV2"), "AuthEvent": Name("DocOpen"), "Length": 16}},
                "StmF": Name("StdCF"),
                "StrF": Name("StdCF"),
                "O": hexs(self.O),
                "U": hexs(self.U),
                "P": self.p,
            }
        return {
            "Filter": Name("Standard"),
            "V": 5,
            "R": 6,
            "Length": 256,
            "CF": {"StdCF": {"CFM": Name("AESV3"), "AuthEvent": Name("DocOpen"), "Length": 32}},
            "StmF": Name("StdCF"),
            "StrF": Name("StdCF"),
            "O": hexs(self.O),
            "U": hexs(self.U),
            "OE": hexs(self.OE),
            "UE": hexs(self.UE),
            "Perms": hexs(self.Perms),
            "P": self.p,
        }

    def encrypt(self, num: int, data: bytes) -> bytes:
        # Deterministic IVs: a fixture must be byte-identical on every run.
        iv = hashlib.md5(b"iv" + num.to_bytes(4, "big") + data[:16]).digest()
        if self.rev == 6:
            return iv + aes_cbc(self.key, iv, data)
        base = self.key + num.to_bytes(3, "little") + b"\x00\x00"
        if self.scheme == "rc4-40":
            return rc4(hashlib.md5(base).digest()[: min(len(self.key) + 5, 16)], data)
        object_key = hashlib.md5(base + b"sAlT").digest()[:16]
        return iv + aes_cbc(object_key, iv, data)


def _literal(text: bytes) -> bytes:
    return b"(" + text.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)") + b")"


def _serialise(value: object, num: int, enc: Encryption | None) -> bytes:
    if isinstance(value, Raw):
        return bytes(value)
    if isinstance(value, Name):
        return b"/" + value.encode()
    if isinstance(value, bool):
        return b"true" if value else b"false"
    if isinstance(value, int | float):
        return str(value).encode()
    if isinstance(value, Ref):
        return f"{value.num} 0 R".encode()
    if isinstance(value, str | bytes):
        data = value.encode("latin-1") if isinstance(value, str) else value
        if enc:
            return b"<" + enc.encrypt(num, data).hex().encode() + b">"
        return _literal(data)
    if isinstance(value, list):
        return b"[" + b" ".join(_serialise(v, num, enc) for v in value) + b"]"
    if isinstance(value, dict):
        parts = [b"/" + k.encode() + b" " + _serialise(v, num, enc) for k, v in value.items()]
        return b"<<" + b" ".join(parts) + b">>"
    raise TypeError(type(value))


def pdf(
    objects: dict[int, object],
    root: int,
    encryption: Encryption | None = None,
    doc_id: bytes = b"cliora-bp07-fixture0",
) -> bytes:
    """Objects are numbered by the caller; object numbers must be dense from 1."""
    out = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    offsets: dict[int, int] = {}
    enc_num = None
    if encryption:
        enc_num = max(objects) + 1
        objects = {**objects, enc_num: Raw(_serialise(encryption.dictionary(), enc_num, None))}
    for num in sorted(objects):
        offsets[num] = len(out)
        value = objects[num]
        enc = encryption if (encryption and num != enc_num) else None
        out += f"{num} 0 obj\n".encode()
        if isinstance(value, Stream):
            data = enc.encrypt(num, value.data) if enc else value.data
            dictionary = {**value.dictionary, "Length": len(data)}
            out += _serialise(dictionary, num, enc) + b"\nstream\n" + data + b"\nendstream"
        else:
            out += _serialise(value, num, enc)
        out += b"\nendobj\n"
    xref = len(out)
    size = max(offsets) + 1
    out += f"xref\n0 {size}\n0000000000 65535 f \n".encode()
    for num in range(1, size):
        out += f"{offsets[num]:010d} 00000 n \n".encode()
    trailer: dict[str, object] = {
        "Size": size,
        "Root": Ref(root),
        "ID": [Raw(b"<" + doc_id.hex().encode() + b">")] * 2,
    }
    if enc_num:
        trailer["Encrypt"] = Ref(enc_num)
    out += b"trailer\n" + _serialise(trailer, 0, None) + f"\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def text_pages(labels: list[str], extra_page: dict[str, object] | None = None) -> tuple[dict[int, object], int]:
    """A document of Letter pages, each showing one line of Helvetica text.
    Returns (objects, root). Object 1 catalog, 2 pages, 3 font, then pairs of
    (page, content)."""
    objects: dict[int, object] = {
        1: {"Type": Name("Catalog"), "Pages": Ref(2)},
        3: {"Type": Name("Font"), "Subtype": Name("Type1"), "BaseFont": Name("Helvetica")},
    }
    kids = []
    for i, label in enumerate(labels):
        page, content = 4 + 2 * i, 5 + 2 * i
        kids.append(Ref(page))
        objects[page] = {
            "Type": Name("Page"),
            "Parent": Ref(2),
            "MediaBox": [0, 0, 612, 792],
            "Resources": {"Font": {"F1": Ref(3)}},
            "Contents": Ref(content),
            **(extra_page if i == 0 and extra_page else {}),
        }
        stream = f"BT /F1 36 Tf 72 680 Td ({label}) Tj ET 0.2 0.4 0.8 rg 72 120 468 40 re f".encode()
        objects[content] = Stream({}, stream)
    objects[2] = {"Type": Name("Pages"), "Kids": kids, "Count": len(kids)}
    return objects, 1


def ok_pdf(pages: int) -> Callable[[], bytes]:
    def build() -> bytes:
        """Plain multi-page document: page navigation, `第 n／N 頁`, and the
        page limit (200 passes, 201 is refused before any page renders)."""
        objects, root = text_pages([f"Page {n} of {pages}" for n in range(1, pages + 1)])
        return pdf(objects, root)

    return build


def encrypted_pdf(scheme: str, user: str) -> Callable[[], bytes]:
    def build() -> bytes:
        """Encrypted with the standard handler. A non-empty user password needs a
        prompt, which the console never shows (`pdf_password_required`); an
        empty one is permissions-only and renders view-only (OD-8 (a)). The
        daemon decides neither: both kinds reach the browser."""
        doc_id = hashlib.md5(f"{scheme}/{user}".encode()).digest()
        objects, root = text_pages([f"Encrypted {scheme}"])
        enc = Encryption(scheme, user=user, owner="owner-secret", doc_id=doc_id)
        return pdf(objects, root, enc, doc_id=doc_id)

    return build


def cjk_pdf() -> bytes:
    """Traditional Chinese with a non-embedded CID font, so PDF.js must fetch
    the UniCNS-UCS2-H CMap from the self-hosted cMapUrl (the CSP path)."""
    text = "繁體中文預覽測試"
    hex_text = text.encode("utf-16-be").hex().upper()
    objects: dict[int, object] = {
        1: {"Type": Name("Catalog"), "Pages": Ref(2)},
        2: {"Type": Name("Pages"), "Kids": [Ref(3)], "Count": 1},
        3: {
            "Type": Name("Page"),
            "Parent": Ref(2),
            "MediaBox": [0, 0, 612, 792],
            "Resources": {"Font": {"F1": Ref(5)}},
            "Contents": Ref(4),
        },
        4: Stream({}, f"BT /F1 32 Tf 72 680 Td <{hex_text}> Tj ET".encode()),
        5: {
            "Type": Name("Font"),
            "Subtype": Name("Type0"),
            "BaseFont": Name("MSung-Light"),
            "Encoding": Name("UniCNS-UCS2-H"),
            "DescendantFonts": [Ref(6)],
        },
        6: {
            "Type": Name("Font"),
            "Subtype": Name("CIDFontType0"),
            "BaseFont": Name("MSung-Light"),
            "CIDSystemInfo": {"Registry": "Adobe", "Ordering": "CNS1", "Supplement": 0},
            "FontDescriptor": Ref(7),
        },
        7: {
            "Type": Name("FontDescriptor"),
            "FontName": Name("MSung-Light"),
            "Flags": 6,
            "FontBBox": [-160, -259, 1015, 888],
            "ItalicAngle": 0,
            "Ascent": 888,
            "Descent": -259,
            "CapHeight": 880,
            "StemV": 93,
        },
    }
    return pdf(objects, 1)


# 16x16 horizontal grey gradient, JPEG 2000 codestream. Made once with OpenJPEG
# 2.5.2 (`opj_compress -i gradient.pgm -o a.j2k -n 2`, alpine:3.20
# openjpeg-tools-2.5.2-r0) because no standard-library encoder exists; the PGM
# was 16x16, pixel (x, y) = 16 * x. Embedded rather than committed as a file so
# its provenance sits next to it.
J2K_GRADIENT = bytes.fromhex(
    "ff4fff510029000000000010000000100000000000000000000000100000001000000000"
    "000000000001070101ff52000c00000001000104040001ff5c00074040484850ff640025"
    "000143726561746564206279204f70656e4a5045472076657273696f6e20322e352e32ff"
    "90000a00000000002e0001ff93df80a8116aa1f0207906f900434f6ddf95f6042402fdd5"
    "7fc1f3840036a199cfffd9"
)


def jpx_pdf() -> bytes:
    """A JPXDecode image, drawn large: PDF.js decodes it with the self-hosted
    OpenJPEG WebAssembly module, which is what `'wasm-unsafe-eval'` and wasmUrl
    have to allow (BP-OM-04)."""
    objects: dict[int, object] = {
        1: {"Type": Name("Catalog"), "Pages": Ref(2)},
        2: {"Type": Name("Pages"), "Kids": [Ref(3)], "Count": 1},
        3: {
            "Type": Name("Page"),
            "Parent": Ref(2),
            "MediaBox": [0, 0, 612, 792],
            "Resources": {"XObject": {"Im1": Ref(5)}},
            "Contents": Ref(4),
        },
        4: Stream({}, b"q 400 0 0 400 106 196 cm /Im1 Do Q"),
        5: Stream(
            {
                "Type": Name("XObject"),
                "Subtype": Name("Image"),
                "Width": 16,
                "Height": 16,
                "Filter": Name("JPXDecode"),
            },
            J2K_GRADIENT,
        ),
    }
    return pdf(objects, 1)


def active_pdf() -> bytes:
    """Every kind of active content in one document (ADR 0029 T1): document
    JavaScript as OpenAction and in the name tree, a URI link over the visible
    text, Launch and GoToR links, a form with a submit button and an XFA
    packet, and an embedded file with an attachment annotation. The console
    must stay inert: no navigation, no popup, no request, no <a>, no script."""
    js = "window.__cliora_pwned = 1; app.alert('bp07');"
    link = lambda rect, action: {  # noqa: E731
        "Type": Name("Annot"),
        "Subtype": Name("Link"),
        "Rect": rect,
        "Border": [0, 0, 0],
        "A": action,
    }
    objects: dict[int, object] = {
        1: {
            "Type": Name("Catalog"),
            "Pages": Ref(2),
            "OpenAction": Ref(8),
            "Names": {
                "JavaScript": {"Names": ["bp07", Ref(8)]},
                "EmbeddedFiles": {"Names": ["note.txt", Ref(10)]},
            },
            "AcroForm": {"Fields": [Ref(12)], "XFA": Ref(13)},
        },
        2: {"Type": Name("Pages"), "Kids": [Ref(3)], "Count": 1},
        3: {
            "Type": Name("Page"),
            "Parent": Ref(2),
            "MediaBox": [0, 0, 612, 792],
            "Resources": {"Font": {"F1": Ref(5)}},
            "Contents": Ref(4),
            "Annots": [Ref(6), Ref(7), Ref(9), Ref(11), Ref(12), Ref(14)],
            "AA": {"O": Ref(8)},
        },
        4: Stream(
            {},
            b"BT /F1 28 Tf 72 700 Td (Active content) Tj 0 -60 Td (URI link here) Tj"
            b" 0 -60 Td (Launch here) Tj 0 -60 Td (GoToR here) Tj ET",
        ),
        5: {"Type": Name("Font"), "Subtype": Name("Type1"), "BaseFont": Name("Helvetica")},
        6: link([72, 630, 400, 670], {"S": Name("URI"), "URI": "https://bp07.example.invalid/uri"}),
        7: link([72, 570, 400, 610], {"S": Name("Launch"), "F": "calc.exe"}),
        8: {"S": Name("JavaScript"), "JS": js},
        9: link([72, 510, 400, 550], {"S": Name("GoToR"), "F": "other.pdf", "D": [0, Name("Fit")]}),
        10: {"Type": Name("Filespec"), "F": "note.txt", "EF": {"F": Ref(15)}},
        11: {
            "Type": Name("Annot"),
            "Subtype": Name("FileAttachment"),
            "Rect": [450, 700, 480, 730],
            "FS": Ref(10),
        },
        12: {
            "Type": Name("Annot"),
            "Subtype": Name("Widget"),
            "FT": Name("Btn"),
            "Ff": 65536,  # pushbutton
            "T": "submit",
            "Rect": [72, 420, 300, 470],
            "A": {
                "S": Name("SubmitForm"),
                "F": {"FS": Name("URL"), "F": "https://bp07.example.invalid/submit"},
            },
        },
        13: Stream({}, b"<xdp:xdp xmlns:xdp='http://ns.adobe.com/xdp/'><template/></xdp:xdp>"),
        14: link([72, 360, 400, 400], {"S": Name("JavaScript"), "JS": js}),
        15: Stream({"Type": Name("EmbeddedFile")}, b"attachment body\n"),
    }
    return pdf(objects, 1)


def cve_2024_4367_pdf() -> bytes:
    """The public CVE-2024-4367 shape: script smuggled into a Type1 font's
    FontMatrix, which PDF.js < 4.2.67 compiled into a glyph function when eval
    was allowed. The pinned version has no eval path at all; the E2E asserts
    the marker it would set stays unset under the real CSP."""
    objects, root = text_pages(["FontMatrix shape"])
    objects[3] = {
        "Type": Name("Font"),
        "Subtype": Name("Type1"),
        "BaseFont": Name("Helvetica"),
        "FontMatrix": [1, 0, 0, 1, 0, Raw(b"(1\\); window.__cliora_pwned = 1; //)")],
    }
    return pdf(objects, root)


def broken_xref_pdf() -> bytes:
    """A valid envelope (`%PDF-` at 0, `%%EOF` at the end) around an object graph
    PDF.js cannot use: the daemon passes it, the renderer must fail cleanly
    (`render_failed`), never half-draw."""
    body = ok_pdf(1)()
    head, _, _ = body.partition(b"xref\n")
    # The catalog points at a pages tree that does not exist, and the xref
    # table is garbage; PDF.js's reconstruction finds no usable page.
    head = head.replace(b"/Pages 2 0 R", b"/Pages 99 0 R")
    return head + b"xref\ngarbage\ntrailer\n<< /Root 1 0 R >>\nstartxref\n0\n%%EOF\n"


# ------------------------------------------------------------------------ driver

FIXTURES: dict[str, Callable[[], bytes]] = {
    "ok.png": ok_png,
    "ok-orientation6.jpg": ok_orientation6_jpg,
    "ok-animated.gif": ok_animated_gif,
    "ok.pdf": ok_pdf(40),
    "pages-200.pdf": ok_pdf(200),
    "pages-201.pdf": ok_pdf(201),
    "ok-cjk.pdf": cjk_pdf,
    "ok-jpx.pdf": jpx_pdf,
    "active.pdf": active_pdf,
    "cve-2024-4367-shape.pdf": cve_2024_4367_pdf,
    "broken-xref.pdf": broken_xref_pdf,
    "password-rc4-40.pdf": encrypted_pdf("rc4-40", "user-secret"),
    "password-aes-128.pdf": encrypted_pdf("aes-128", "user-secret"),
    "password-aes-256.pdf": encrypted_pdf("aes-256", "user-secret"),
    "permissions-rc4-40.pdf": encrypted_pdf("rc4-40", ""),
    "permissions-aes-128.pdf": encrypted_pdf("aes-128", ""),
    "permissions-aes-256.pdf": encrypted_pdf("aes-256", ""),
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
