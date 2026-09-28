package files

import (
	"bytes"
	"compress/zlib"
	"crypto/sha256"
	"runtime"
	"sync"
	"testing"
	"time"
)

// validate runs the structural validator directly on bytes, with default limits.
func validate(t testing.TB, data []byte) previewVerdict {
	t.Helper()
	mime := sniffPreviewMime(data)
	if mime == "" {
		t.Fatalf("fixture is not sniffed as a preview type")
	}
	return validatePreviewBytes(mime, data, defaultPreviewLimits())
}

func wantVerdict(t *testing.T, name string, v previewVerdict, code, reason string) {
	t.Helper()
	if v.code != code || v.reason != reason {
		t.Fatalf("%s: got %q/%q; want %q/%q", name, v.code, v.reason, code, reason)
	}
}

// inflated observes every compressed-metadata inflate the validator performs,
// so a test can assert how many bytes it produced (plan/31/03 §7).
func inflated(t *testing.T) *[]int64 {
	t.Helper()
	var mu sync.Mutex
	seen := []int64{}
	inflateObserved = func(n int64) {
		mu.Lock()
		seen = append(seen, n)
		mu.Unlock()
	}
	t.Cleanup(func() { inflateObserved = nil })
	return &seen
}

func total(ns []int64) (s int64) {
	for _, n := range ns {
		s += n
	}
	return s
}

// D15: a ~1 KiB iCCP or zTXt that inflates to 100 MiB is refused as complexity
// having produced no more than budget+1 bytes of output.
func TestPreviewPNGCompressedAncillaryBomb(t *testing.T) {
	bomb := zlibBytes(t, make([]byte, 100*mib), zlib.BestCompression)
	if len(bomb) > 200*kib {
		t.Fatalf("fixture: bomb stream is %d bytes", len(bomb))
	}
	for name, chunk := range map[string][]byte{
		"iCCP": iccpChunk(bomb), "zTXt": ztxtChunk(bomb), "iTXt": itxtCompressedChunk(bomb),
	} {
		seen := inflated(t)
		v := validate(t, withAncillary(realPNG(t, 4, 4), chunk))
		wantVerdict(t, name, v, "FILE_PREVIEW_LIMIT", "complexity")
		budget := int64(mib)
		if name != "iCCP" {
			budget = 256 * kib
		}
		if got := total(*seen); got > budget+1 {
			t.Fatalf("%s: inflated %d bytes; must stop at budget+1 (%d)", name, got, budget+1)
		}
	}
}

func TestPreviewPNGAncillaryBudgetBoundary(t *testing.T) {
	base := realPNG(t, 4, 4)

	// iCCP expanding to exactly 1 MiB passes; 1 MiB + 1 is refused.
	exact := zlibBytes(t, bytes.Repeat([]byte{7}, mib), zlib.BestCompression)
	over := zlibBytes(t, bytes.Repeat([]byte{7}, mib+1), zlib.BestCompression)
	wantVerdict(t, "iCCP 1 MiB", validate(t, withAncillary(base, iccpChunk(exact))), "", "")
	wantVerdict(t, "iCCP 1 MiB+1", validate(t, withAncillary(base, iccpChunk(over))), "FILE_PREVIEW_LIMIT", "complexity")

	// Two iCCP chunks: the spec allows one.
	small := zlibBytes(t, []byte("profile"), 6)
	wantVerdict(t, "two iCCP", validate(t, withAncillary(base, iccpChunk(small), iccpChunk(small))), "FILE_PREVIEW_LIMIT", "complexity")

	// 64 zTXt pass; 65 are refused.
	tiny := zlibBytes(t, []byte("note"), 6)
	sixtyFour := make([][]byte, 64)
	for i := range sixtyFour {
		sixtyFour[i] = ztxtChunk(tiny)
	}
	wantVerdict(t, "64 zTXt", validate(t, withAncillary(base, sixtyFour...)), "", "")
	wantVerdict(t, "65 zTXt", validate(t, withAncillary(base, append(sixtyFour, itxtCompressedChunk(tiny))...)), "FILE_PREVIEW_LIMIT", "complexity")

	// Expanded total 2 MiB + 1 across chunks that are each within their own
	// budget (iCCP 1 MiB, four zTXt of 256 KiB, one more byte).
	parts := [][]byte{iccpChunk(zlibBytes(t, bytes.Repeat([]byte{1}, mib), 9))}
	for i := 0; i < 4; i++ {
		parts = append(parts, ztxtChunk(zlibBytes(t, bytes.Repeat([]byte{2}, 256*kib), 9)))
	}
	wantVerdict(t, "expanded 2 MiB", validate(t, withAncillary(base, parts...)), "", "")
	parts = append(parts, ztxtChunk(zlibBytes(t, []byte{3}, 9)))
	wantVerdict(t, "expanded 2 MiB+1", validate(t, withAncillary(base, parts...)), "FILE_PREVIEW_LIMIT", "complexity")

	// A single zTXt whose compressed stream is 256 KiB + 1 is refused before any
	// inflate: zero bytes produced.
	seen := inflated(t)
	wantVerdict(t, "zTXt compressed 256 KiB+1",
		validate(t, withAncillary(base, ztxtChunk(make([]byte, 256*kib+1)))), "FILE_PREVIEW_LIMIT", "complexity")
	if total(*seen) != 0 || len(*seen) != 0 {
		t.Fatalf("an over-length compressed chunk was inflated (%v)", *seen)
	}

	// Compressed total 2 MiB + 1 is refused before any inflate. Every chunk is
	// individually within its compressed cap.
	seen = inflated(t)
	parts = [][]byte{iccpChunk(make([]byte, mib))}
	for i := 0; i < 4; i++ {
		parts = append(parts, ztxtChunk(make([]byte, 256*kib)))
	}
	parts = append(parts, ztxtChunk(make([]byte, 1)))
	wantVerdict(t, "compressed 2 MiB+1", validate(t, withAncillary(base, parts...)), "FILE_PREVIEW_LIMIT", "complexity")
	if len(*seen) != 0 {
		t.Fatalf("the compressed total must be checked before inflating anything (%v)", *seen)
	}

	// Uncompressed text/eXIf total 1 MiB passes, 1 MiB + 1 is refused.
	text := func(n int) []byte { return pngChunk("tEXt", cat([]byte("k\x00"), bytes.Repeat([]byte{'a'}, n-2))) }
	wantVerdict(t, "tEXt 1 MiB", validate(t, withAncillary(base, text(mib/2), pngChunk("eXIf", make([]byte, mib/2)))), "", "")
	wantVerdict(t, "tEXt 1 MiB+1", validate(t, withAncillary(base, text(mib/2+1), pngChunk("eXIf", make([]byte, mib/2)))), "FILE_PREVIEW_LIMIT", "complexity")

	// A corrupt compressed stream is malformed, not silently accepted.
	wantVerdict(t, "corrupt iCCP", validate(t, withAncillary(base, iccpChunk([]byte{0x78, 0x9c, 0xff, 0xff}))), "FILE_PREVIEW_INVALID", "malformed")
}

// A screenshot-like PNG with an embedded colour profile passes and is sent
// byte-for-byte (measure, never modify). The profile here is a deterministic
// stand-in of Display P3 size; the real-device corpus is BP-OM-13 / BP-09.
func TestPreviewPNGRealWorldICCPasses(t *testing.T) {
	profile := incompressible(536, 3) // a Display P3 profile is ~536 bytes
	shot := withAncillary(realPNG(t, 390, 844), iccpChunk(zlibBytes(t, profile, 6)),
		pngChunk("eXIf", make([]byte, 120)), pngChunk("iTXt", []byte("XML:com.adobe.xmp\x00\x00\x00\x00\x00<x:xmpmeta/>")))
	root, ws := previewWS(t, map[string][]byte{"IMG_0001.png": shot})
	res := open(t, testService(), root, ws, "IMG_0001.png")
	wantOpened(t, res, "image/png")
	if sha256.Sum256(res.Data) != sha256.Sum256(shot) || res.Width != 390 || res.Height != 844 {
		t.Fatal("the screenshot must pass unchanged")
	}
}

func TestPreviewAPNGFrameBounds(t *testing.T) {
	base := realPNG(t, 10, 10)
	wantVerdict(t, "apng ok", validate(t, withAncillary(base, actl(2), fctl(0, 10, 10, 0, 0))), "", "")
	wantVerdict(t, "1001 frames", validate(t, withAncillary(base, actl(1001))), "FILE_PREVIEW_LIMIT", "complexity")
	wantVerdict(t, "frame outside", validate(t, withAncillary(base, actl(1), fctl(0, 8, 8, 4, 0))), "FILE_PREVIEW_INVALID", "malformed")
	many := [][]byte{actl(1000)}
	for i := 0; i < 1001; i++ {
		many = append(many, fctl(uint32(i), 1, 1, 0, 0))
	}
	wantVerdict(t, "1001 fcTL", validate(t, withAncillary(base, many...)), "FILE_PREVIEW_LIMIT", "complexity")
}

func TestPreviewPNGStructure(t *testing.T) {
	good := realPNG(t, 3, 3)
	wantVerdict(t, "good", validate(t, good), "", "")
	wantVerdict(t, "truncated", validate(t, good[:len(good)-5]), "FILE_PREVIEW_INVALID", "malformed")
	noIEND := good[:len(good)-12]
	wantVerdict(t, "no IEND", validate(t, noIEND), "FILE_PREVIEW_INVALID", "malformed")
	notFirst := cat(pngSignature, pngChunk("tEXt", []byte("a\x00b")), good[8:])
	wantVerdict(t, "IHDR not first", validate(t, notFirst), "FILE_PREVIEW_INVALID", "malformed")
	lying := append([]byte(nil), good...)
	copy(lying[8+25:], be32(0x7fffff00)) // first chunk after IHDR claims a huge length
	wantVerdict(t, "length beyond file", validate(t, lying), "FILE_PREVIEW_INVALID", "malformed")
	chunks := [][]byte{}
	for i := 0; i < 4100; i++ {
		chunks = append(chunks, pngChunk("prVt", nil))
	}
	wantVerdict(t, "4100 chunks", validate(t, withAncillary(good, chunks...)), "FILE_PREVIEW_LIMIT", "complexity")
	wantVerdict(t, "zero width", validate(t, headerOnlyPNG(0, 5)), "FILE_PREVIEW_INVALID", "malformed")
}

func TestPreviewJPEGMetadataBounds(t *testing.T) {
	base := realJPEG(t, 8, 8)
	wantVerdict(t, "good", validate(t, base), "", "")
	segs := func(n, each int) [][]byte {
		out := [][]byte{}
		for i := 0; i < n; i++ {
			out = append(out, jpegSegment(0xE1, make([]byte, each)))
		}
		return out
	}
	// 32 APP1 segments of 65533 data bytes: 32*(65533+2) = 2 MiB - 32*... keep
	// the arithmetic in the test: total counted is the segment length field.
	under := segs(32, 65533)
	wantVerdict(t, "APPn under 2 MiB", validate(t, withJPEGSegments(base, under...)), "", "")
	over := append(segs(32, 65533), jpegSegment(0xFE, make([]byte, 2*mib-32*65535+1-2)))
	wantVerdict(t, "APPn+COM 2 MiB+1", validate(t, withJPEGSegments(base, over...)), "FILE_PREVIEW_LIMIT", "complexity")

	icc := func(seq, n byte, size int) []byte { return iccSegment(seq, n, make([]byte, size)) }
	// 17 ICC chunks: 16 of 65519 and one small = just over 1 MiB of profile.
	iccOver := [][]byte{}
	for i := byte(1); i <= 16; i++ {
		iccOver = append(iccOver, icc(i, 17, 65519))
	}
	iccOver = append(iccOver, icc(17, 17, mib-16*65519+1))
	wantVerdict(t, "ICC 1 MiB+1", validate(t, withJPEGSegments(base, iccOver...)), "FILE_PREVIEW_LIMIT", "complexity")
	iccExact := append(append([][]byte{}, iccOver[:16]...), icc(17, 17, mib-16*65519))
	wantVerdict(t, "ICC 1 MiB", validate(t, withJPEGSegments(base, iccExact...)), "", "")
	wantVerdict(t, "ICC gap", validate(t, withJPEGSegments(base, icc(1, 3, 10), icc(3, 3, 10))), "FILE_PREVIEW_INVALID", "malformed")
	wantVerdict(t, "ICC dup", validate(t, withJPEGSegments(base, icc(1, 2, 10), icc(1, 2, 10))), "FILE_PREVIEW_INVALID", "malformed")
	wantVerdict(t, "ICC count mismatch", validate(t, withJPEGSegments(base, icc(1, 2, 10), icc(2, 3, 10))), "FILE_PREVIEW_INVALID", "malformed")

	markers := [][]byte{}
	for i := 0; i < 1030; i++ {
		markers = append(markers, jpegSegment(0xFE, []byte{'c'}))
	}
	wantVerdict(t, "1030 markers", validate(t, withJPEGSegments(base, markers...)), "FILE_PREVIEW_LIMIT", "complexity")
	wantVerdict(t, "no EOI", validate(t, base[:len(base)-2]), "FILE_PREVIEW_INVALID", "malformed")
	wantVerdict(t, "segment beyond file", validate(t, cat([]byte{0xFF, 0xD8, 0xFF, 0xE1, 0xFF, 0xFF}, make([]byte, 10))), "FILE_PREVIEW_INVALID", "malformed")
	// Data after EOI (an MPF preview, say) is not parsed.
	wantVerdict(t, "trailing data", validate(t, cat(base, []byte("MPF trailing bytes"))), "", "")
}

func TestPreviewWebPMetadataBounds(t *testing.T) {
	canvas := vp8xChunk(100, 100, 0x2c)
	wantVerdict(t, "simple lossless", validate(t, webp(vp8lChunk(10, 10))), "", "")
	wantVerdict(t, "vp8x", validate(t, webp(canvas, riffChunk("ICCP", make([]byte, 100)), vp8lChunk(100, 100))), "", "")
	wantVerdict(t, "ICCP 1 MiB+1", validate(t, webp(canvas, riffChunk("ICCP", make([]byte, mib+1)), vp8lChunk(100, 100))), "FILE_PREVIEW_LIMIT", "complexity")
	wantVerdict(t, "EXIF+XMP 1 MiB+1", validate(t, webp(canvas, vp8lChunk(100, 100), riffChunk("EXIF", make([]byte, mib/2)), riffChunk("XMP ", make([]byte, mib/2+1)))), "FILE_PREVIEW_LIMIT", "complexity")
	wantVerdict(t, "EXIF+XMP 1 MiB", validate(t, webp(canvas, vp8lChunk(100, 100), riffChunk("EXIF", make([]byte, mib/2)), riffChunk("XMP ", make([]byte, mib/2)))), "", "")
	frames := [][]byte{canvas, riffChunk("ANIM", make([]byte, 6))}
	for i := 0; i < 1001; i++ {
		frames = append(frames, anmfChunk(0, 0, 2, 2))
	}
	wantVerdict(t, "1001 ANMF", validate(t, webp(frames...)), "FILE_PREVIEW_LIMIT", "complexity")
	wantVerdict(t, "ANMF outside", validate(t, webp(canvas, riffChunk("ANIM", make([]byte, 6)), anmfChunk(98, 0, 4, 4))), "FILE_PREVIEW_INVALID", "malformed")
	bad := webp(vp8lChunk(10, 10))
	copy(bad[4:], le32(uint32(len(bad)))) // RIFF size disagrees with the file
	wantVerdict(t, "riff size", validate(t, bad), "FILE_PREVIEW_INVALID", "malformed")
	wantVerdict(t, "first chunk", validate(t, webp(riffChunk("EXIF", make([]byte, 4)), vp8lChunk(1, 1))), "FILE_PREVIEW_INVALID", "malformed")
	wantVerdict(t, "vp8x without image", validate(t, webp(canvas)), "FILE_PREVIEW_INVALID", "malformed")
	lossy := riffChunk("VP8 ", cat([]byte{0x10, 0x02, 0x00, 0x9d, 0x01, 0x2a}, le16(640), le16(480), make([]byte, 4)))
	v := validate(t, webp(lossy))
	if v.code != "" || v.width != 640 || v.height != 480 {
		t.Fatalf("VP8 lossy: %+v", v)
	}
}

func TestPreviewGIFExtensionBounds(t *testing.T) {
	wantVerdict(t, "real", validate(t, realGIF(t, 6, 4)), "", "")
	wantVerdict(t, "ext 1 MiB", validate(t, craftedGIF(10, 10, gifExtension(mib), gifFrame(0, 0, 1, 1))), "", "")
	wantVerdict(t, "ext 1 MiB+1", validate(t, craftedGIF(10, 10, gifExtension(mib/2), gifExtension(mib/2+1), gifFrame(0, 0, 1, 1))), "FILE_PREVIEW_LIMIT", "complexity")
	frames := []([]byte){}
	for i := 0; i < 1001; i++ {
		frames = append(frames, gifFrame(0, 0, 1, 1))
	}
	wantVerdict(t, "1001 frames", validate(t, craftedGIF(10, 10, frames...)), "FILE_PREVIEW_LIMIT", "complexity")
	wantVerdict(t, "first frame outside", validate(t, craftedGIF(10, 10, gifFrame(5, 5, 6, 6))), "FILE_PREVIEW_INVALID", "malformed")
	wantVerdict(t, "later frame outside", validate(t, craftedGIF(10, 10, gifFrame(0, 0, 1, 1), gifFrame(9, 0, 2, 1))), "FILE_PREVIEW_INVALID", "malformed")
	wantVerdict(t, "no frame", validate(t, craftedGIF(10, 10)), "FILE_PREVIEW_INVALID", "malformed")
	noTrailer := craftedGIF(10, 10, gifFrame(0, 0, 1, 1))
	wantVerdict(t, "no trailer", validate(t, noTrailer[:len(noTrailer)-1]), "FILE_PREVIEW_INVALID", "malformed")
}

func TestPreviewPDFEnvelope(t *testing.T) {
	wantVerdict(t, "ok", validate(t, tinyPDF("")), "", "")
	for _, version := range []string{"1.0", "1.4", "1.7", "2.0"} {
		wantVerdict(t, version, validate(t, cat([]byte("%PDF-"+version+"\n"), []byte("x\n%%EOF"))), "", "")
	}
	for name, body := range map[string][]byte{
		"version 1.8": []byte("%PDF-1.8\n%%EOF"),
		"version 3.0": []byte("%PDF-3.0\n%%EOF"),
		"no eof":      []byte("%PDF-1.7\n1 0 obj endobj\n"),
		"eof too far": cat([]byte("%PDF-1.7\n%%EOF\n"), make([]byte, 1100)),
	} {
		wantVerdict(t, name, validate(t, body), "FILE_PREVIEW_INVALID", "malformed")
	}
	// The daemon makes no encryption judgement (ADR 0029 §4, OD-8): an /Encrypt
	// dictionary in the trailer is not a refusal here.
	wantVerdict(t, "encrypted", validate(t, tinyPDF("3 0 obj << /Filter /Standard /V 2 >> endobj\ntrailer << /Encrypt 3 0 R >>")), "", "")
}

// Two workers validating the most expensive legal PNG at the same time finish
// within the provisional 1 s budget, including on one CPU (plan/31/03 §7; the
// terminal-latency half of this test is in the connection package).
func TestPreviewConcurrentWorstCaseMetadata(t *testing.T) {
	worst := worstCaseMetadataPNG(t)
	if len(worst) != 8*mib {
		t.Fatalf("fixture is %d bytes; want 8 MiB", len(worst))
	}
	for _, procs := range []int{runtime.GOMAXPROCS(0), 1} {
		prev := runtime.GOMAXPROCS(procs)
		var wg sync.WaitGroup
		durations := make([]time.Duration, 2)
		verdicts := make([]previewVerdict, 2)
		for i := 0; i < 2; i++ {
			wg.Add(1)
			go func(i int) {
				defer wg.Done()
				started := time.Now()
				verdicts[i] = validate(t, worst)
				durations[i] = time.Since(started)
			}(i)
		}
		wg.Wait()
		runtime.GOMAXPROCS(prev)
		for i := range verdicts {
			if verdicts[i].code != "" {
				t.Fatalf("GOMAXPROCS=%d: the worst legal file was refused: %+v", procs, verdicts[i])
			}
			if durations[i] > time.Second {
				t.Fatalf("GOMAXPROCS=%d: validation took %v; provisional budget is 1 s (BP-OM-05)", procs, durations[i])
			}
			t.Logf("GOMAXPROCS=%d worker %d: %v", procs, i, durations[i])
		}
	}
}

// worstCaseMetadataPNG is 8 MiB with the compressed-metadata input and output
// both at their ceilings: iCCP ~1 MiB in / 1 MiB out, four zTXt of ~256 KiB
// in / 256 KiB out (stored blocks, so input ≈ output), and the rest padding.
func worstCaseMetadataPNG(t testing.TB) []byte {
	t.Helper()
	overhead := func(n int) int { return len(storedStreamFor(t, n, 1)) - n }
	iccIn := mib - overhead(mib) - 16
	parts := [][]byte{iccpChunk(storedStreamFor(t, iccIn, 11))}
	zIn := 256*kib - overhead(256*kib) - 16
	for i := 0; i < 4; i++ {
		parts = append(parts, ztxtChunk(storedStreamFor(t, zIn, uint64(20+i))))
	}
	return withPadding(withAncillary(realPNG(t, 64, 64), parts...), 8*mib)
}
