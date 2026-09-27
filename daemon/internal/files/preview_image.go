package files

import (
	"bytes"
	"compress/zlib"
	"encoding/binary"
	"image/gif"
	"image/jpeg"
	"image/png"
	"io"
)

// Structural validation for the four image types (ADR 0029 §3 step 10, §4;
// plan/31/03 §2 and §2.1, decision D15).
//
// This is a bounded header and marker walk, NOT a decode. Pixel data (PNG IDAT
// and fdAT, JPEG entropy-coded scans, GIF LZW data, WebP VP8/VP8L/ALPH) is never
// decompressed. The one exception is compressed PNG metadata (iCCP, zTXt,
// compressed iTXt): each is a separate deflate stream that a browser will
// inflate, so it is inflated here into a discard sink behind a budget, only to
// measure it. The bytes sent are the original bytes; nothing is transcoded or
// stripped. The standard library's DecodeConfig (header-only) cross-checks each
// walker's dimensions.

type previewVerdict struct {
	code, reason  string
	width, height int
}

func malformed() previewVerdict {
	return previewVerdict{code: "FILE_PREVIEW_INVALID", reason: "malformed"}
}
func tooComplex() previewVerdict {
	return previewVerdict{code: "FILE_PREVIEW_LIMIT", reason: "complexity"}
}

// D15 budgets (plan/31/03 §2.1). Fixed technical ceilings, not product options.
const (
	pngMaxChunks               = 4096
	pngMaxICCP                 = 1
	pngICCPMaxCompressed       = 1 << 20
	pngICCPMaxExpanded         = 1 << 20
	pngMaxCompressedText       = 64
	pngTextMaxCompressed       = 256 << 10
	pngTextMaxExpanded         = 256 << 10
	pngAllCompressedMaxInput   = 2 << 20
	pngAllCompressedMaxOutput  = 2 << 20
	pngUncompressedTextMax     = 1 << 20
	previewMaxFrames           = 1000
	jpegMaxScans               = 64
	jpegMaxMarkers             = 1024
	jpegMetadataMax            = 2 << 20
	jpegICCMax                 = 1 << 20
	webpICCPMax                = 1 << 20
	webpEXIFXMPMax             = 1 << 20
	webpMaxChunks              = 4096
	gifExtensionMax            = 1 << 20
	previewHeaderSniffMinBytes = 12
)

var (
	pngMagic  = []byte{0x89, 'P', 'N', 'G', '\r', '\n', 0x1a, '\n'}
	jpegMagic = []byte{0xFF, 0xD8, 0xFF}
)

// sniffPreviewMime decides the type from magic bytes only. The extension and
// any client claim never decide it. Anything else is "" (unsupported_type).
func sniffPreviewMime(b []byte) string {
	switch {
	case bytes.HasPrefix(b, pngMagic):
		return "image/png"
	case bytes.HasPrefix(b, jpegMagic):
		return "image/jpeg"
	case bytes.HasPrefix(b, []byte("GIF87a")), bytes.HasPrefix(b, []byte("GIF89a")):
		return "image/gif"
	case len(b) >= previewHeaderSniffMinBytes && bytes.Equal(b[:4], []byte("RIFF")) && bytes.Equal(b[8:12], []byte("WEBP")):
		return "image/webp"
	case bytes.HasPrefix(b, []byte("%PDF-")):
		return "application/pdf"
	}
	return ""
}

func validatePreviewBytes(mime string, b []byte, lim PreviewLimits) previewVerdict {
	switch mime {
	case "image/png":
		return validatePNG(b, lim)
	case "image/jpeg":
		return validateJPEG(b, lim)
	case "image/gif":
		return validateGIF(b, lim)
	case "image/webp":
		return validateWebP(b, lim)
	case "application/pdf":
		return validatePDF(b)
	}
	return previewVerdict{code: "FILE_PREVIEW_UNSUPPORTED", reason: "unsupported_type"}
}

// checkDimensions applies the pixel limit before the side limit, so a
// 50000×50000 bomb reports "pixels" (plan/31/00 success criterion 3).
func checkDimensions(w, h int64, lim PreviewLimits) previewVerdict {
	if w <= 0 || h <= 0 {
		return malformed()
	}
	if w*h > lim.ImageMaxPixels {
		return previewVerdict{code: "FILE_PREVIEW_LIMIT", reason: "pixels"}
	}
	if w > int64(lim.ImageMaxSide) || h > int64(lim.ImageMaxSide) {
		return previewVerdict{code: "FILE_PREVIEW_LIMIT", reason: "dimensions"}
	}
	return previewVerdict{width: int(w), height: int(h)}
}

// --- PNG ---

type pngStream struct {
	data   []byte
	budget int64
}

func validPNGChunkType(t []byte) bool {
	for _, c := range t {
		if !(c >= 'A' && c <= 'Z' || c >= 'a' && c <= 'z') {
			return false
		}
	}
	return true
}

func validatePNG(b []byte, lim PreviewLimits) previewVerdict {
	if len(b) < len(pngMagic)+25 || !bytes.HasPrefix(b, pngMagic) {
		return malformed()
	}
	var (
		dims                                previewVerdict
		chunks, iccp, compressedText, fctls int
		compressedIn, uncompressedText      int64
		sawIDAT, sawIEND                    bool
		streams                             []pngStream
		canvasW, canvasH                    int64
	)
	pos := len(pngMagic)
	for pos < len(b) && !sawIEND {
		if len(b)-pos < 12 {
			return malformed()
		}
		length := int64(binary.BigEndian.Uint32(b[pos:]))
		typ := b[pos+4 : pos+8]
		if length > int64(len(b)-pos-12) || !validPNGChunkType(typ) {
			return malformed()
		}
		chunks++
		if chunks > pngMaxChunks {
			return tooComplex()
		}
		data := b[pos+8 : pos+8+int(length)]
		name := string(typ)
		if chunks == 1 && name != "IHDR" {
			return malformed()
		}
		switch name {
		case "IHDR":
			if chunks != 1 || length != 13 {
				return malformed()
			}
			canvasW = int64(binary.BigEndian.Uint32(data[0:]))
			canvasH = int64(binary.BigEndian.Uint32(data[4:]))
			if dims = checkDimensions(canvasW, canvasH, lim); dims.code != "" {
				return dims
			}
		case "IDAT":
			sawIDAT = true
		case "IEND":
			sawIEND = true
		case "iCCP":
			iccp++
			if iccp > pngMaxICCP {
				return tooComplex()
			}
			stream, ok := afterKeywordAndMethod(data)
			if !ok {
				return malformed()
			}
			if len(stream) > pngICCPMaxCompressed {
				return tooComplex()
			}
			compressedIn += int64(len(stream))
			streams = append(streams, pngStream{stream, pngICCPMaxExpanded})
		case "zTXt":
			compressedText++
			if compressedText > pngMaxCompressedText {
				return tooComplex()
			}
			stream, ok := afterKeywordAndMethod(data)
			if !ok {
				return malformed()
			}
			if len(stream) > pngTextMaxCompressed {
				return tooComplex()
			}
			compressedIn += int64(len(stream))
			streams = append(streams, pngStream{stream, pngTextMaxExpanded})
		case "iTXt":
			stream, compressed, ok := itxtText(data)
			if !ok {
				return malformed()
			}
			if !compressed {
				uncompressedText += length
				break
			}
			compressedText++
			if compressedText > pngMaxCompressedText {
				return tooComplex()
			}
			if len(stream) > pngTextMaxCompressed {
				return tooComplex()
			}
			compressedIn += int64(len(stream))
			streams = append(streams, pngStream{stream, pngTextMaxExpanded})
		case "tEXt", "eXIf":
			uncompressedText += length
		case "acTL":
			if length != 8 {
				return malformed()
			}
			frames := binary.BigEndian.Uint32(data)
			if frames == 0 {
				return malformed()
			}
			if frames > previewMaxFrames {
				return tooComplex()
			}
		case "fcTL":
			if length != 26 {
				return malformed()
			}
			fctls++
			if fctls > previewMaxFrames {
				return tooComplex()
			}
			fw := int64(binary.BigEndian.Uint32(data[4:]))
			fh := int64(binary.BigEndian.Uint32(data[8:]))
			fx := int64(binary.BigEndian.Uint32(data[12:]))
			fy := int64(binary.BigEndian.Uint32(data[16:]))
			if fw == 0 || fh == 0 || fx+fw > canvasW || fy+fh > canvasH {
				return malformed()
			}
		}
		// Both totals are checked as the walk goes, so an over-budget file is
		// refused before a single byte is inflated.
		if compressedIn > pngAllCompressedMaxInput || uncompressedText > pngUncompressedTextMax {
			return tooComplex()
		}
		pos += 12 + int(length)
	}
	if !sawIEND || !sawIDAT {
		return malformed()
	}
	// Measure, never modify: inflate each compressed metadata stream into a
	// discard sink, stopping at min(its own budget, what is left of the total).
	remaining := int64(pngAllCompressedMaxOutput)
	for _, s := range streams {
		budget := min(s.budget, remaining)
		n, err := inflateMeasure(s.data, budget)
		if n > budget {
			return tooComplex()
		}
		if err != nil {
			return malformed()
		}
		remaining -= n
	}
	cfg, err := png.DecodeConfig(bytes.NewReader(b))
	if err != nil || int64(cfg.Width) != canvasW || int64(cfg.Height) != canvasH {
		return malformed()
	}
	return dims
}

// afterKeywordAndMethod parses "keyword\0 method" (iCCP, zTXt) and returns the
// compressed stream. Keyword 1-79 bytes; method 0 (deflate) is the only one.
func afterKeywordAndMethod(data []byte) ([]byte, bool) {
	i := bytes.IndexByte(data, 0)
	if i < 1 || i > 79 || len(data) < i+2 || data[i+1] != 0 {
		return nil, false
	}
	return data[i+2:], true
}

// itxtText parses iTXt: keyword\0 flag method language\0 translated\0 text.
func itxtText(data []byte) (text []byte, compressed, ok bool) {
	i := bytes.IndexByte(data, 0)
	if i < 1 || i > 79 || len(data) < i+3 {
		return nil, false, false
	}
	flag, method := data[i+1], data[i+2]
	if flag > 1 || (flag == 1 && method != 0) {
		return nil, false, false
	}
	rest := data[i+3:]
	lang := bytes.IndexByte(rest, 0)
	if lang < 0 {
		return nil, false, false
	}
	rest = rest[lang+1:]
	translated := bytes.IndexByte(rest, 0)
	if translated < 0 {
		return nil, false, false
	}
	return rest[translated+1:], flag == 1, true
}

// inflateObserved is a test seam: it receives the number of bytes each inflate
// produced, so a test can assert the budget really stops the work.
var inflateObserved func(n int64)

// inflateMeasure returns how many bytes stream inflates to, reading at most
// budget+1 of output; a result above budget means "over".
func inflateMeasure(stream []byte, budget int64) (int64, error) {
	zr, err := zlib.NewReader(bytes.NewReader(stream))
	if err != nil {
		if inflateObserved != nil {
			inflateObserved(0)
		}
		return 0, err
	}
	defer zr.Close()
	n, err := io.Copy(io.Discard, io.LimitReader(zr, budget+1))
	if inflateObserved != nil {
		inflateObserved(n)
	}
	if n > budget {
		return n, nil
	}
	return n, err
}

// --- JPEG ---

func isSOF(m byte) bool {
	return m >= 0xC0 && m <= 0xCF && m != 0xC4 && m != 0xC8 && m != 0xCC
}

func validateJPEG(b []byte, lim PreviewLimits) previewVerdict {
	if len(b) < 4 || b[0] != 0xFF || b[1] != 0xD8 {
		return malformed()
	}
	var (
		dims               previewVerdict
		sawSOF             bool
		markers, scans     int
		metadata, iccTotal int64
		iccCount           byte
		iccSeen            = map[byte]bool{}
	)
	pos := 2
	for {
		if pos >= len(b) || b[pos] != 0xFF {
			return malformed()
		}
		for pos < len(b) && b[pos] == 0xFF {
			pos++
		}
		if pos >= len(b) {
			return malformed()
		}
		m := b[pos]
		pos++
		markers++
		if markers > jpegMaxMarkers {
			return tooComplex()
		}
		if m == 0xD9 {
			break // EOI; anything after it (an MPF preview, say) is not parsed
		}
		if m == 0x01 || (m >= 0xD0 && m <= 0xD7) {
			continue
		}
		if m == 0xD8 || m == 0x00 {
			return malformed()
		}
		if len(b)-pos < 2 {
			return malformed()
		}
		segLen := int(binary.BigEndian.Uint16(b[pos:]))
		if segLen < 2 || segLen > len(b)-pos {
			return malformed()
		}
		seg := b[pos+2 : pos+segLen]
		pos += segLen
		switch {
		case isSOF(m):
			if sawSOF || len(seg) < 6 {
				return malformed()
			}
			sawSOF = true
			h := int64(binary.BigEndian.Uint16(seg[1:]))
			w := int64(binary.BigEndian.Uint16(seg[3:]))
			if dims = checkDimensions(w, h, lim); dims.code != "" {
				return dims
			}
		case (m >= 0xE0 && m <= 0xEF) || m == 0xFE:
			metadata += int64(segLen)
			if metadata > jpegMetadataMax {
				return tooComplex()
			}
			if m == 0xE2 && bytes.HasPrefix(seg, []byte("ICC_PROFILE\x00")) {
				if len(seg) < 14 {
					return malformed()
				}
				seq, count := seg[12], seg[13]
				if seq == 0 || count == 0 || seq > count || iccSeen[seq] || (iccCount != 0 && count != iccCount) {
					return malformed()
				}
				iccCount = count
				iccSeen[seq] = true
				iccTotal += int64(len(seg) - 14)
				if iccTotal > jpegICCMax {
					return tooComplex()
				}
			}
		case m == 0xDA:
			if !sawSOF {
				return malformed()
			}
			scans++
			if scans > jpegMaxScans {
				return tooComplex()
			}
			// Skip the entropy-coded data to the next marker without decoding it:
			// FF00 is a stuffed byte, FFD0-FFD7 a restart marker, FFFF fill.
			for {
				if pos >= len(b)-1 {
					return malformed()
				}
				if b[pos] != 0xFF {
					pos++
					continue
				}
				next := b[pos+1]
				if next == 0x00 || (next >= 0xD0 && next <= 0xD7) {
					pos += 2
					continue
				}
				if next == 0xFF {
					pos++
					continue
				}
				break
			}
		}
	}
	if !sawSOF || scans == 0 || (iccCount != 0 && len(iccSeen) != int(iccCount)) {
		return malformed()
	}
	cfg, err := jpeg.DecodeConfig(bytes.NewReader(b))
	if err != nil || cfg.Width != dims.width || cfg.Height != dims.height {
		return malformed()
	}
	return dims
}

// --- GIF ---

func validateGIF(b []byte, lim PreviewLimits) previewVerdict {
	if len(b) < 13 || !(bytes.HasPrefix(b, []byte("GIF87a")) || bytes.HasPrefix(b, []byte("GIF89a"))) {
		return malformed()
	}
	sw := int64(binary.LittleEndian.Uint16(b[6:]))
	sh := int64(binary.LittleEndian.Uint16(b[8:]))
	dims := checkDimensions(sw, sh, lim)
	if dims.code != "" {
		return dims
	}
	pos := 13
	if b[10]&0x80 != 0 {
		pos += 3 << ((b[10] & 7) + 1)
	}
	frames := 0
	var extensions int64
	skipSubBlocks := func(count bool) (bool, previewVerdict) {
		for {
			if pos >= len(b) {
				return false, malformed()
			}
			n := int(b[pos])
			pos++
			if n == 0 {
				return true, previewVerdict{}
			}
			if pos+n > len(b) {
				return false, malformed()
			}
			if count {
				extensions += int64(n)
				if extensions > gifExtensionMax {
					return false, tooComplex()
				}
			}
			pos += n
		}
	}
	for {
		if pos >= len(b) {
			return malformed()
		}
		switch b[pos] {
		case 0x3B:
			if frames == 0 {
				return malformed()
			}
			cfg, err := gif.DecodeConfig(bytes.NewReader(b))
			if err != nil || int64(cfg.Width) != sw || int64(cfg.Height) != sh {
				return malformed()
			}
			return dims
		case 0x21:
			pos += 2
			if ok, v := skipSubBlocks(true); !ok {
				return v
			}
		case 0x2C:
			if len(b)-pos < 11 {
				return malformed()
			}
			x := int64(binary.LittleEndian.Uint16(b[pos+1:]))
			y := int64(binary.LittleEndian.Uint16(b[pos+3:]))
			fw := int64(binary.LittleEndian.Uint16(b[pos+5:]))
			fh := int64(binary.LittleEndian.Uint16(b[pos+7:]))
			packed := b[pos+9]
			if fw == 0 || fh == 0 || x+fw > sw || y+fh > sh {
				return malformed()
			}
			frames++
			if frames > previewMaxFrames {
				return tooComplex()
			}
			pos += 10
			if packed&0x80 != 0 {
				pos += 3 << ((packed & 7) + 1)
			}
			if pos >= len(b) || b[pos] < 1 || b[pos] > 11 {
				return malformed()
			}
			pos++ // LZW minimum code size; the data itself is never decompressed
			if ok, v := skipSubBlocks(false); !ok {
				return v
			}
		default:
			return malformed()
		}
	}
}

// --- WebP ---

func le24At(b []byte) int64 { return int64(b[0]) | int64(b[1])<<8 | int64(b[2])<<16 }

func validateWebP(b []byte, lim PreviewLimits) previewVerdict {
	if len(b) < 20 || !bytes.Equal(b[:4], []byte("RIFF")) || !bytes.Equal(b[8:12], []byte("WEBP")) {
		return malformed()
	}
	if int64(binary.LittleEndian.Uint32(b[4:]))+8 != int64(len(b)) {
		return malformed()
	}
	var (
		dims               previewVerdict
		canvasW, canvasH   int64
		chunks, frames     int
		iccp, meta         int64
		extended, sawImage bool
	)
	pos := 12
	for pos < len(b) {
		if len(b)-pos < 8 {
			return malformed()
		}
		fourcc := string(b[pos : pos+4])
		size := int64(binary.LittleEndian.Uint32(b[pos+4:]))
		padded := size + size&1
		if padded > int64(len(b)-pos-8) {
			return malformed()
		}
		data := b[pos+8 : pos+8+int(size)]
		chunks++
		if chunks > webpMaxChunks {
			return tooComplex()
		}
		if chunks == 1 {
			var w, h int64
			switch fourcc {
			case "VP8 ":
				if len(data) < 10 || data[0]&1 != 0 || !bytes.Equal(data[3:6], []byte{0x9d, 0x01, 0x2a}) {
					return malformed()
				}
				w = int64(binary.LittleEndian.Uint16(data[6:]) & 0x3fff)
				h = int64(binary.LittleEndian.Uint16(data[8:]) & 0x3fff)
				sawImage = true
			case "VP8L":
				if len(data) < 5 || data[0] != 0x2f {
					return malformed()
				}
				bits := binary.LittleEndian.Uint32(data[1:])
				w = int64(bits&0x3fff) + 1
				h = int64((bits>>14)&0x3fff) + 1
				sawImage = true
			case "VP8X":
				if len(data) < 10 {
					return malformed()
				}
				w = le24At(data[4:]) + 1
				h = le24At(data[7:]) + 1
				extended = true
			default:
				return malformed()
			}
			canvasW, canvasH = w, h
			if dims = checkDimensions(w, h, lim); dims.code != "" {
				return dims
			}
		} else {
			switch fourcc {
			case "ICCP":
				iccp += size
				if iccp > webpICCPMax {
					return tooComplex()
				}
			case "EXIF", "XMP ":
				meta += size
				if meta > webpEXIFXMPMax {
					return tooComplex()
				}
			case "ANMF":
				frames++
				if frames > previewMaxFrames {
					return tooComplex()
				}
				if len(data) < 16 {
					return malformed()
				}
				fx, fy := le24At(data)*2, le24At(data[3:])*2
				fw, fh := le24At(data[6:])+1, le24At(data[9:])+1
				if fx+fw > canvasW || fy+fh > canvasH {
					return malformed()
				}
				sawImage = true
			case "VP8 ", "VP8L":
				sawImage = true
			}
		}
		pos += 8 + int(padded)
	}
	if extended && !sawImage {
		return malformed()
	}
	return dims
}
