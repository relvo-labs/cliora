//go:build ignore

// Regenerates the text/binary classification corpus (FR-FILE-008.AC-04).
//
//	cd daemon/internal/files/testdata && go run generate.go
//
// The corpus is committed, not generated at test time: a fixture that the test
// builds for itself can drift with the code under test, and the whole point of
// this corpus is to be an independent statement of what the classifier must
// say. Regenerate only when adding a case, and read the diff.
package main

import (
	"archive/zip"
	"bytes"
	"compress/gzip"
	"encoding/binary"
	"encoding/json"
	"fmt"
	"image"
	"image/color"
	"image/gif"
	"image/jpeg"
	"image/png"
	"os"
	"path/filepath"
	"strings"
)

const dir = "classify"

type expectation struct {
	Name    string `json:"name"`
	Verdict string `json:"verdict"`
	Note    string `json:"note"`
}

var expectations []expectation

func write(name, verdict, note string, data []byte) {
	if err := os.WriteFile(filepath.Join(dir, name), data, 0o644); err != nil {
		panic(err)
	}
	expectations = append(expectations, expectation{name, verdict, note})
}

func img() image.Image {
	m := image.NewRGBA(image.Rect(0, 0, 24, 16))
	for y := 0; y < 16; y++ {
		for x := 0; x < 24; x++ {
			m.Set(x, y, color.RGBA{uint8(x * 10), uint8(y * 15), 200, 255})
		}
	}
	return m
}

func encode(f func(*bytes.Buffer) error) []byte {
	var b bytes.Buffer
	if err := f(&b); err != nil {
		panic(err)
	}
	return b.Bytes()
}

func main() {
	if err := os.MkdirAll(dir, 0o755); err != nil {
		panic(err)
	}

	// ---- the cut points that caused the original bug -----------------------
	// A pure-CJK document with an ASCII pad chosen so byte 8192 lands at a
	// different offset within a 3-byte rune each time. Under the old 8 KiB
	// window, pads 0 and 1 were reported as binary and pad 2 was not.
	for _, pad := range []int{0, 1, 2, 3, 4} {
		body := strings.Repeat("x", pad) + strings.Repeat("工作區檔案預覽說明文件。", 300)
		write(fmt.Sprintf("cjk-cut-pad%d.md", pad), "text",
			fmt.Sprintf("valid UTF-8 CJK, %d-byte ASCII pad shifts the old 8 KiB cut inside a rune", pad),
			[]byte(body))
	}

	// ---- ordinary text -----------------------------------------------------
	write("ascii.txt", "text", "plain ASCII", []byte("hello world\nsecond line\n"))
	write("crlf.txt", "text", "CRLF line endings", []byte("line one\r\nline two\r\n"))
	write("no-trailing-newline.txt", "text", "no newline at EOF", []byte("last line has no newline"))
	write("empty.txt", "text", "empty file is text, and Monaco shows it blank", nil)
	write("only-newlines.txt", "text", "whitespace only", []byte("\n\n\n\n"))
	write("utf8-bom.txt", "text", "UTF-8 BOM is valid UTF-8", append([]byte{0xEF, 0xBB, 0xBF}, []byte("內容\n")...))
	write("tabs.tsv", "text", "tab-heavy tabular data", []byte(strings.Repeat("a\tb\tc\n", 200)))

	// ---- terminal output: text, and the old rule said otherwise ------------
	write("ansi-colour.log", "text", "three ANSI colour pairs per line; binary under the old rule",
		[]byte(strings.Repeat("\x1b[32mINFO\x1b[0m \x1b[36mreq\x1b[0m \x1b[33m12ms\x1b[0m\n", 300)))
	write("ansi-spinner.log", "text", "cursor-control heavy spinner output; binary under the old rule",
		[]byte(strings.Repeat("\x1b[2K\x1b[1G\x1b[36m⠋\x1b[0m building\n", 300)))
	write("formfeed.txt", "text", "form feed as a page break; binary under the old rule",
		[]byte(strings.Repeat("page\x0c\n", 300)))
	write("vertical-tab.txt", "text", "vertical tab in older documents",
		[]byte(strings.Repeat("col\x0bcol\n", 300)))

	// ---- source and markup -------------------------------------------------
	write("emoji.md", "text", "4-byte runes throughout", []byte(strings.Repeat("狀態 🙂 ok ✅\n", 700)))
	write("four-byte.json", "text", "4-byte runes inside JSON",
		[]byte(`{"emoji":"`+strings.Repeat("🚀", 600)+`"}`))
	write("minified.js", "text", "one very long line",
		[]byte("!function(){"+strings.Repeat("var a=1;", 1200)+"}();"))

	// ---- text, but not UTF-8 ----------------------------------------------
	write("big5.txt", "unsupported_encoding", "Big5-encoded Chinese",
		[]byte("\xa4\xa4\xa4\xe5\xb4\xfa\xb8\xd5\xa4\xba\xae\xe9\n"))
	write("gbk.txt", "unsupported_encoding", "GBK-encoded Chinese", []byte("\xd6\xd0\xce\xc4\xb2\xe2\xca\xd4\n"))
	write("shiftjis.txt", "unsupported_encoding", "Shift-JIS Japanese", []byte("\x93\xfa\x96\x7b\x8c\xea\n"))
	write("latin1.txt", "unsupported_encoding", "Latin-1 accents", []byte("caf\xe9 na\xefve r\xe9sum\xe9\n"))

	// ---- genuinely binary --------------------------------------------------
	write("image.png", "binary", "real PNG", encode(func(b *bytes.Buffer) error { return png.Encode(b, img()) }))
	write("image.jpg", "binary", "real JPEG", encode(func(b *bytes.Buffer) error { return jpeg.Encode(b, img(), nil) }))
	write("image.gif", "binary", "real GIF", encode(func(b *bytes.Buffer) error { return gif.Encode(b, img(), nil) }))

	// Synthetic WebP: a correct RIFF/WEBP container header over a binary body.
	// No WebP encoder exists in the Go standard library or on the authoring
	// machine, and the classifier only needs bytes that are not text.
	webp := make([]byte, 0, 64)
	webp = append(webp, 'R', 'I', 'F', 'F')
	webp = binary.LittleEndian.AppendUint32(webp, 44)
	webp = append(webp, 'W', 'E', 'B', 'P', 'V', 'P', '8', 'L')
	for i := 0; i < 40; i++ {
		webp = append(webp, byte(i*7%251))
	}
	write("image.webp", "binary", "synthetic RIFF/WEBP container (no encoder available)", webp)

	write("archive.tar.gz", "binary", "gzip stream", encode(func(b *bytes.Buffer) error {
		w := gzip.NewWriter(b)
		if _, err := w.Write([]byte(strings.Repeat("payload\n", 500))); err != nil {
			return err
		}
		return w.Close()
	}))
	write("archive.zip", "binary", "zip container", encode(func(b *bytes.Buffer) error {
		w := zip.NewWriter(b)
		f, err := w.Create("a.txt")
		if err != nil {
			return err
		}
		if _, err := f.Write([]byte("payload")); err != nil {
			return err
		}
		return w.Close()
	}))

	// A real ELF header, copied from the host's /bin/true, so the corpus
	// contains at least one executable that was not invented here.
	if elf, err := os.ReadFile("/bin/true"); err == nil && len(elf) > 2048 {
		write("program.elf", "binary", "first 2 KiB of a real ELF executable", elf[:2048])
	} else {
		write("program.elf", "binary", "synthetic ELF header",
			append([]byte{0x7f, 'E', 'L', 'F', 2, 1, 1, 0}, make([]byte, 120)...))
	}

	var u16le, u16be []byte
	for _, r := range "工作區 workspace\n" {
		u16le = binary.LittleEndian.AppendUint16(u16le, uint16(r))
		u16be = binary.BigEndian.AppendUint16(u16be, uint16(r))
	}
	write("utf16le.txt", "binary", "UTF-16LE: NUL bytes make it binary, not merely unreadable",
		append([]byte{0xFF, 0xFE}, u16le...))
	write("utf16be.txt", "binary", "UTF-16BE", append([]byte{0xFE, 0xFF}, u16be...))
	write("sqlite.db", "binary", "SQLite header", append([]byte("SQLite format 3\x00"), make([]byte, 96)...))

	// ---- realistic text that must not be over-blocked ----------------------
	// A PEM block is all-printable ASCII and looks alarming; it is still text,
	// and denying it would be denying the file people most want to read when
	// they are debugging a certificate.
	write("certificate.pem.txt", "text", "PEM block: printable ASCII only",
		[]byte("-----BEGIN CERTIFICATE-----\n"+
			strings.Repeat("MIIDdzCCAl+gAwIBAgIEbGl0ZTANBgkqhkiG9w0BAQsFADBaMQswCQYDVQQGEwJV\n", 30)+
			"-----END CERTIFICATE-----\n"))
	write("base64-blob.txt", "text", "long base64 lines, no control characters",
		[]byte(strings.Repeat(strings.Repeat("QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVowMTIzNDU2Nzg5", 3)+"\n", 120)))
	// Exactly 8192 bytes of ASCII before the first multi-byte rune: the old
	// window ended precisely here, so this is the one offset that used to work
	// by luck. Pinned so a future window cannot quietly reintroduce the bug at
	// a different boundary.
	write("boundary-8192-then-cjk.md", "text", "first multi-byte rune starts exactly at byte 8192",
		[]byte(strings.Repeat("a", 8192)+strings.Repeat("中文段落。", 200)))
	write("del-sparse.txt", "text", "one DEL per 12 runes, under the control-character threshold",
		[]byte(strings.Repeat("aaaaaaaaaaa\x7f", 400)))
	write("bom-only.txt", "text", "a UTF-8 BOM and nothing else", []byte{0xEF, 0xBB, 0xBF})

	// ---- the edge the old window missed entirely ---------------------------
	write("ascii-prefix-then-nul.bin", "binary",
		"first 9000 bytes printable ASCII, NUL after: served as TEXT under the old window",
		append([]byte(strings.Repeat("A", 9000)), 0x00, 0x01, 0xff))
	write("control-heavy.bin", "binary", "more than 10% real control characters",
		[]byte(strings.Repeat("a\x01\x02", 500)))

	out, err := json.MarshalIndent(expectations, "", "  ")
	if err != nil {
		panic(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "expected.json"), append(out, '\n'), 0o644); err != nil {
		panic(err)
	}
	fmt.Printf("wrote %d fixtures to %s/\n", len(expectations), dir)
}
