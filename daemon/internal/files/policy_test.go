package files

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// Classification tests (FR-FILE-008). Every case in this file except the corpus
// runner is a regression test for a wrong answer that was measured on the old
// 8 KiB-window implementation — see plan/13/08-measurements.md.

func verdictName(v Verdict) string {
	switch v {
	case VerdictText:
		return "text"
	case VerdictBinary:
		return "binary"
	case VerdictUnsupportedEncoding:
		return "unsupported_encoding"
	}
	return "unknown"
}

// The original bug: the window was cut at a fixed byte offset, so whether a
// perfectly valid UTF-8 document was readable depended on where byte 8192
// happened to land. Pads 0/1/3/4 were reported binary; pad 2 was not.
func TestClassifyRuneBoundary(t *testing.T) {
	for pad := 0; pad < 6; pad++ {
		body := strings.Repeat("x", pad) + strings.Repeat("工作區檔案預覽說明文件。", 300)
		if len(body) <= 8192 {
			t.Fatalf("pad %d: fixture must exceed the old 8 KiB window", pad)
		}
		if v, mime := Classify([]byte(body)); v != VerdictText {
			t.Fatalf("pad %d: verdict=%s mime=%s, want text", pad, verdictName(v), mime)
		}
	}
}

// A 4-byte rune straddling the old boundary is the same bug with a wider rune.
func TestClassifyFourByteRuneAcrossOldWindow(t *testing.T) {
	for pad := 0; pad < 4; pad++ {
		body := strings.Repeat("x", pad) + strings.Repeat("🚀", 3000)
		if v, _ := Classify([]byte(body)); v != VerdictText {
			t.Fatalf("pad %d: verdict=%s, want text", pad, verdictName(v))
		}
	}
}

// The reverse failure: content past the window was never examined, so a binary
// file with a printable prefix was served as text (FR-FILE-008.AC-03).
func TestClassifyNulAnywhere(t *testing.T) {
	base := strings.Repeat("A", 20000)
	for _, at := range []int{0, 1, 8191, 8192, 8193, 15000, len(base) - 1} {
		b := []byte(base)
		b[at] = 0
		if v, mime := Classify(b); v != VerdictBinary {
			t.Fatalf("NUL at %d: verdict=%s mime=%s, want binary", at, verdictName(v), mime)
		}
	}
}

// ANSI-coloured terminal output is a text file (FR-FILE-008.AC-02). Three
// colour pairs per line was enough to trip the old control-character rule.
func TestClassifyAnsiLog(t *testing.T) {
	cases := map[string]string{
		"plain":        "2026-08-01 INFO  request completed in 12ms\n",
		"one-pair":     "\x1b[32m2026-08-01 INFO\x1b[0m  request completed in 12ms\n",
		"three-pairs":  "\x1b[32mINFO\x1b[0m \x1b[36mreq\x1b[0m \x1b[33m12ms\x1b[0m\n",
		"spinner":      "\x1b[2K\x1b[1G\x1b[36m⠋\x1b[0m building\n",
		"formfeed":     "page\x0c\n",
		"verticaltab":  "col\x0bcol\n",
		"cursor-heavy": "\x1b[1;1H\x1b[2J\x1b[?25l\x1b[?25h\n",
	}
	for name, line := range cases {
		body := []byte(strings.Repeat(line, 400))
		if v, _ := Classify(body); v != VerdictText {
			t.Errorf("%s: verdict=%s, want text", name, verdictName(v))
		}
	}
}

// The ratio must compare like with like. Before, control runes were divided by
// the byte length, so the same density meant different things in ASCII and CJK.
func TestClassifyControlRatioUsesRunes(t *testing.T) {
	ascii := []byte(strings.Repeat("a\x01", 2000)) // 50% control
	cjk := []byte(strings.Repeat("中\x01", 2000))   // 50% control
	av, _ := Classify(ascii)
	cv, _ := Classify(cjk)
	if av != cv {
		t.Fatalf("same control density judged differently: ascii=%s cjk=%s",
			verdictName(av), verdictName(cv))
	}
	if av != VerdictBinary {
		t.Fatalf("50%% control characters should be binary, got %s", verdictName(av))
	}
	// Just under the threshold stays text in both scripts.
	for name, unit := range map[string]string{"ascii": "aaaaaaaaaaa\x01", "cjk": "中中中中中中中中中中中\x01"} {
		if v, _ := Classify([]byte(strings.Repeat(unit, 500))); v != VerdictText {
			t.Errorf("%s: 1-in-12 control runes should stay text, got %s", name, verdictName(v))
		}
	}
}

// "Not UTF-8" and "not text" are different answers with different next steps.
func TestClassifyEncodings(t *testing.T) {
	cases := []struct {
		name string
		data []byte
		want Verdict
	}{
		{"utf8-bom", append([]byte{0xEF, 0xBB, 0xBF}, []byte("內容\n")...), VerdictText},
		{"big5", []byte("\xa4\xa4\xa4\xe5\xb4\xfa\xb8\xd5\n"), VerdictUnsupportedEncoding},
		{"gbk", []byte("\xd6\xd0\xce\xc4\n"), VerdictUnsupportedEncoding},
		{"latin1", []byte("caf\xe9 na\xefve\n"), VerdictUnsupportedEncoding},
		{"utf16le", []byte{0xFF, 0xFE, 0x68, 0x00, 0x69, 0x00}, VerdictBinary},
		{"empty", nil, VerdictText},
	}
	for _, tc := range cases {
		v, mime := Classify(tc.data)
		if v != tc.want {
			t.Errorf("%s: verdict=%s want %s", tc.name, verdictName(v), verdictName(tc.want))
		}
		if v == VerdictUnsupportedEncoding && mime != "text/plain; charset=unknown" {
			t.Errorf("%s: mime=%q — an unreadable encoding is still text, and the mime must say so", tc.name, mime)
		}
	}
}

// TestClassifyCorpus is the gate (GATE-WF-CLASSIFY-CORPUS, FR-FILE-008.AC-04).
// The corpus is committed data, deliberately independent of the code under
// test: relaxing the classifier without noticing is exactly the failure this
// guards, and only a fixed expectation table can catch it.
func TestClassifyCorpus(t *testing.T) {
	dir := filepath.Join("testdata", "classify")
	raw, err := os.ReadFile(filepath.Join(dir, "expected.json"))
	if err != nil {
		t.Fatalf("read corpus expectations: %v", err)
	}
	var expected []struct {
		Name    string `json:"name"`
		Verdict string `json:"verdict"`
		Note    string `json:"note"`
	}
	if err := json.Unmarshal(raw, &expected); err != nil {
		t.Fatalf("parse corpus expectations: %v", err)
	}
	// plan/13 02-…md §3 specifies at least 40. The floor is asserted so the
	// corpus cannot be quietly thinned out to make a failing case go away.
	if len(expected) < 40 {
		t.Fatalf("corpus has only %d entries; plan/13 §3 specifies at least 40", len(expected))
	}

	seen := make(map[string]bool, len(expected))
	for _, e := range expected {
		seen[e.Name] = true
		data, err := os.ReadFile(filepath.Join(dir, e.Name))
		if err != nil {
			t.Errorf("%s: %v", e.Name, err)
			continue
		}
		got, mime := Classify(data)
		if verdictName(got) != e.Verdict {
			t.Errorf("%s (%s): verdict=%s mime=%s, want %s",
				e.Name, e.Note, verdictName(got), mime, e.Verdict)
		}
	}

	// Every file in the directory must be accounted for, so adding a fixture
	// without an expectation fails instead of silently doing nothing.
	entries, err := os.ReadDir(dir)
	if err != nil {
		t.Fatal(err)
	}
	for _, entry := range entries {
		if entry.IsDir() || entry.Name() == "expected.json" {
			continue
		}
		if !seen[entry.Name()] {
			t.Errorf("%s is in the corpus directory but not in expected.json", entry.Name())
		}
	}
}

// DetectBinary keeps its allow/deny meaning for callers that do not care which
// kind of denial it is.
func TestDetectBinaryMatchesClassify(t *testing.T) {
	cases := [][]byte{
		[]byte("plain text\n"),
		{0x00, 0x01},
		[]byte("caf\xe9\n"),
		nil,
	}
	for _, data := range cases {
		v, mime := Classify(data)
		binary, bmime := DetectBinary(data)
		if binary != (v != VerdictText) || mime != bmime {
			t.Fatalf("DetectBinary disagrees with Classify for %q", data)
		}
	}
}
