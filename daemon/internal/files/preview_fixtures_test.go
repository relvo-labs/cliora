package files

// Fixture builders for the binary preview tests (ADR 0029, plan/31/03 §7). Every
// fixture is generated here rather than committed as a binary, so each one says
// in code exactly which property it has: "a 1 KiB iCCP that inflates to 100 MiB"
// is a sentence a reviewer can check, a 1 KiB file under testdata/ is not.
// BP-09 adds a committed corpus (scripts/p31/gen_preview_fixtures.py) for the
// cross-layer tests; the daemon's own tests do not depend on it.

import (
	"bytes"
	"compress/zlib"
	"encoding/binary"
	"hash/crc32"
	"image"
	"image/color"
	"image/gif"
	"image/jpeg"
	"image/png"
	"math/rand/v2"
	"testing"
)

const (
	kib = 1024
	mib = 1024 * 1024
)

func be32(v uint32) []byte { b := make([]byte, 4); binary.BigEndian.PutUint32(b, v); return b }
func le16(v uint16) []byte { b := make([]byte, 2); binary.LittleEndian.PutUint16(b, v); return b }
func le24(v uint32) []byte { return []byte{byte(v), byte(v >> 8), byte(v >> 16)} }
func le32(v uint32) []byte { b := make([]byte, 4); binary.LittleEndian.PutUint32(b, v); return b }

func cat(parts ...[]byte) []byte { return bytes.Join(parts, nil) }

// --- PNG ---

var pngSignature = []byte{0x89, 'P', 'N', 'G', '\r', '\n', 0x1a, '\n'}

func pngChunk(typ string, data []byte) []byte {
	crc := crc32.NewIEEE()
	crc.Write([]byte(typ))
	crc.Write(data)
	return cat(be32(uint32(len(data))), []byte(typ), data, be32(crc.Sum32()))
}

func ihdr(w, h uint32) []byte {
	return pngChunk("IHDR", cat(be32(w), be32(h), []byte{8, 6, 0, 0, 0}))
}

// realPNG encodes a genuine w×h RGBA image with the standard library, so the
// "passes" cases are files a browser would decode.
func realPNG(t testing.TB, w, h int) []byte {
	t.Helper()
	img := image.NewRGBA(image.Rect(0, 0, w, h))
	for i := range img.Pix {
		img.Pix[i] = byte(i * 7)
	}
	var buf bytes.Buffer
	if err := png.Encode(&buf, img); err != nil {
		t.Fatal(err)
	}
	return buf.Bytes()
}

// withAncillary splices chunks right after IHDR (offset 8 + 25) of a real PNG.
func withAncillary(pngBytes []byte, chunks ...[]byte) []byte {
	head := pngBytes[:8+25]
	return cat(append([][]byte{append([]byte(nil), head...)}, append(chunks, pngBytes[8+25:])...)...)
}

// headerOnlyPNG is a structurally complete PNG whose IDAT is never inflated by
// the validator; the dimensions in IHDR are the point.
func headerOnlyPNG(w, h uint32, extra ...[]byte) []byte {
	parts := [][]byte{pngSignature, ihdr(w, h)}
	parts = append(parts, extra...)
	parts = append(parts, pngChunk("IDAT", []byte{0x78, 0x9c, 0x03, 0x00, 0x00, 0x00, 0x00, 0x01}), pngChunk("IEND", nil))
	return cat(parts...)
}

func zlibBytes(t testing.TB, raw []byte, level int) []byte {
	t.Helper()
	var buf bytes.Buffer
	w, err := zlib.NewWriterLevel(&buf, level)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := w.Write(raw); err != nil {
		t.Fatal(err)
	}
	if err := w.Close(); err != nil {
		t.Fatal(err)
	}
	return buf.Bytes()
}

func iccpChunk(compressed []byte) []byte {
	return pngChunk("iCCP", cat([]byte("Display P3\x00\x00"), compressed))
}

func ztxtChunk(compressed []byte) []byte {
	return pngChunk("zTXt", cat([]byte("Comment\x00\x00"), compressed))
}

func itxtCompressedChunk(compressed []byte) []byte {
	return pngChunk("iTXt", cat([]byte("XML:com.adobe.xmp\x00\x01\x00\x00\x00"), compressed))
}

// incompressible returns n pseudo-random bytes (seeded, so fixtures are
// reproducible); stored in a zlib stream they expand to exactly n.
func incompressible(n int, seed uint64) []byte {
	r := rand.New(rand.NewPCG(seed, seed^0x9e3779b97f4a7c15))
	out := make([]byte, n)
	for i := range out {
		out[i] = byte(r.Uint32())
	}
	return out
}

// storedStreamFor returns a zlib stream (level 0, stored blocks) whose inflated
// size is exactly expanded bytes.
func storedStreamFor(t testing.TB, expanded int, seed uint64) []byte {
	return zlibBytes(t, incompressible(expanded, seed), zlib.NoCompression)
}

func actl(frames uint32) []byte { return pngChunk("acTL", cat(be32(frames), be32(0))) }

func fctl(seq, w, h, x, y uint32) []byte {
	return pngChunk("fcTL", cat(be32(seq), be32(w), be32(h), be32(x), be32(y), []byte{0, 1, 0, 1, 0, 0}))
}

// --- JPEG ---

func realJPEG(t testing.TB, w, h int) []byte {
	t.Helper()
	img := image.NewRGBA(image.Rect(0, 0, w, h))
	for i := range img.Pix {
		img.Pix[i] = byte(i * 3)
	}
	var buf bytes.Buffer
	if err := jpeg.Encode(&buf, img, &jpeg.Options{Quality: 80}); err != nil {
		t.Fatal(err)
	}
	return buf.Bytes()
}

func jpegSegment(marker byte, data []byte) []byte {
	return cat([]byte{0xFF, marker}, []byte{byte((len(data) + 2) >> 8), byte(len(data) + 2)}, data)
}

// withJPEGSegments inserts segments right after SOI of a real JPEG.
func withJPEGSegments(j []byte, segs ...[]byte) []byte {
	return cat(append([][]byte{{0xFF, 0xD8}}, append(segs, j[2:])...)...)
}

func sof0(w, h uint16) []byte {
	return jpegSegment(0xC0, []byte{8, byte(h >> 8), byte(h), byte(w >> 8), byte(w), 1, 1, 0x11, 0})
}

// jpegWithScans is a marker-walkable progressive JPEG envelope with n scans. Its
// entropy data is not decodable; the validator never decodes it.
func jpegWithScans(w, h uint16, n int) []byte {
	parts := [][]byte{{0xFF, 0xD8}, sof0(w, h)}
	for i := 0; i < n; i++ {
		parts = append(parts, jpegSegment(0xDA, []byte{1, 1, 0, 0, 63, 0}), []byte{0x12, 0x34, 0xFF, 0x00, 0x56})
	}
	parts = append(parts, []byte{0xFF, 0xD9})
	return cat(parts...)
}

func iccSegment(seq, total byte, data []byte) []byte {
	return jpegSegment(0xE2, cat([]byte("ICC_PROFILE\x00"), []byte{seq, total}, data))
}

// --- GIF ---

func realGIF(t testing.TB, w, h int) []byte {
	t.Helper()
	img := image.NewPaletted(image.Rect(0, 0, w, h), []color.Color{color.Black, color.White})
	var buf bytes.Buffer
	if err := gif.Encode(&buf, img, nil); err != nil {
		t.Fatal(err)
	}
	return buf.Bytes()
}

// gifFrame is an image descriptor with no local colour table and one tiny data
// sub-block.
func gifFrame(x, y, w, h uint16) []byte {
	return cat([]byte{0x2C}, le16(x), le16(y), le16(w), le16(h), []byte{0x00, 0x02, 0x02, 0x4C, 0x01, 0x00})
}

// gifExtension is a comment extension carrying n bytes in 255-byte sub-blocks.
func gifExtension(n int) []byte {
	parts := [][]byte{{0x21, 0xFE}}
	for n > 0 {
		k := min(n, 255)
		parts = append(parts, []byte{byte(k)}, bytes.Repeat([]byte{'x'}, k))
		n -= k
	}
	parts = append(parts, []byte{0x00})
	return cat(parts...)
}

// craftedGIF: header, logical screen with a 2-colour global table, then blocks.
func craftedGIF(sw, sh uint16, blocks ...[]byte) []byte {
	parts := [][]byte{[]byte("GIF89a"), le16(sw), le16(sh), {0x80, 0, 0}, {0, 0, 0, 255, 255, 255}}
	parts = append(parts, blocks...)
	parts = append(parts, []byte{0x3B})
	return cat(parts...)
}

// --- WebP ---

func riffChunk(fourcc string, data []byte) []byte {
	out := cat([]byte(fourcc), le32(uint32(len(data))), data)
	if len(data)%2 == 1 {
		out = append(out, 0)
	}
	return out
}

func vp8lChunk(w, h uint32) []byte {
	bits := (w - 1) | (h-1)<<14
	return riffChunk("VP8L", cat([]byte{0x2f}, le32(bits), []byte{0, 0, 0}))
}

func vp8xChunk(w, h uint32, flags byte) []byte {
	return riffChunk("VP8X", cat([]byte{flags, 0, 0, 0}, le24(w-1), le24(h-1)))
}

func anmfChunk(x, y, w, h uint32) []byte {
	return riffChunk("ANMF", cat(le24(x/2), le24(y/2), le24(w-1), le24(h-1), le24(100), []byte{0}, vp8lChunk(w, h)))
}

func webp(chunks ...[]byte) []byte {
	body := cat(append([][]byte{[]byte("WEBP")}, chunks...)...)
	return cat([]byte("RIFF"), le32(uint32(len(body))), body)
}

// --- PDF ---

func tinyPDF(body string) []byte {
	return []byte("%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj << /Type /Catalog >> endobj\n" + body + "\ntrailer << /Root 1 0 R >>\n%%EOF\n")
}
