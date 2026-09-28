package files

import (
	"testing"
)

// Fuzz targets for the preview envelope walkers (ADR 0029 T5, plan/31/03 §2).
// Property: never panic, never index out of range, and a verdict is always one of
// the closed set. `go test` runs the seeds; `go test -fuzz=FuzzSniffPNG` explores.

func fuzzVerdict(t *testing.T, mime string, data []byte) {
	v := validatePreviewBytes(mime, data, defaultPreviewLimits())
	switch v.code {
	case "":
		if mime != "application/pdf" && (v.width <= 0 || v.height <= 0) {
			t.Fatalf("an accepted image without dimensions: %+v", v)
		}
	case "FILE_PREVIEW_INVALID":
		if v.reason != "malformed" {
			t.Fatalf("unexpected reason %q", v.reason)
		}
	case "FILE_PREVIEW_LIMIT":
		if v.reason != "pixels" && v.reason != "dimensions" && v.reason != "complexity" {
			t.Fatalf("unexpected reason %q", v.reason)
		}
	default:
		t.Fatalf("unexpected code %q", v.code)
	}
}

func FuzzSniffPNG(f *testing.F) {
	f.Add(realPNG(f, 3, 2))
	f.Add(headerOnlyPNG(50000, 50000))
	f.Add(withAncillary(realPNG(f, 2, 2), iccpChunk(zlibBytes(f, []byte("icc"), 6)), actl(1), fctl(0, 2, 2, 0, 0)))
	f.Add(pngSignature)
	f.Fuzz(func(t *testing.T, data []byte) { fuzzVerdict(t, "image/png", data) })
}

func FuzzSniffJPEG(f *testing.F) {
	f.Add(realJPEG(f, 3, 2))
	f.Add(jpegWithScans(10, 10, 3))
	f.Add(withJPEGSegments(realJPEG(f, 2, 2), iccSegment(1, 1, []byte("icc"))))
	f.Add([]byte{0xFF, 0xD8, 0xFF})
	f.Fuzz(func(t *testing.T, data []byte) { fuzzVerdict(t, "image/jpeg", data) })
}

func FuzzSniffGIF(f *testing.F) {
	f.Add(realGIF(f, 3, 2))
	f.Add(craftedGIF(10, 10, gifExtension(300), gifFrame(0, 0, 2, 2)))
	f.Add([]byte("GIF89a"))
	f.Fuzz(func(t *testing.T, data []byte) { fuzzVerdict(t, "image/gif", data) })
}

func FuzzSniffWebP(f *testing.F) {
	f.Add(webp(vp8lChunk(3, 2)))
	f.Add(webp(vp8xChunk(10, 10, 0x2c), riffChunk("ICCP", []byte("x")), anmfChunk(0, 0, 2, 2)))
	f.Add([]byte("RIFF\x04\x00\x00\x00WEBP"))
	f.Fuzz(func(t *testing.T, data []byte) { fuzzVerdict(t, "image/webp", data) })
}

func FuzzPDFEnvelope(f *testing.F) {
	f.Add(tinyPDF(""))
	f.Add([]byte("%PDF-2.0\n%%EOF"))
	f.Add([]byte("%PDF-"))
	f.Fuzz(func(t *testing.T, data []byte) { fuzzVerdict(t, "application/pdf", data) })
}
