package files

import "bytes"

// PDF envelope check (ADR 0029 §3 step 10, §4). The daemon checks what the file's
// envelope can tell it — a known header version at offset 0 and an %%EOF near the
// end — and nothing else. It does not parse the cross-reference table, does not
// inflate any stream, does not count pages and makes NO encryption judgement:
// those need a PDF parser, and the authority on them is PDF.js inside the
// browser's sandbox (page limit, password refusal; OD-8).

const pdfTailWindow = 1024

func validatePDF(b []byte) previewVerdict {
	versionOK := len(b) >= 8 &&
		(bytes.HasPrefix(b, []byte("%PDF-1.")) && b[7] >= '0' && b[7] <= '7' ||
			bytes.HasPrefix(b, []byte("%PDF-2.0")))
	if !versionOK {
		return malformed()
	}
	tail := b
	if len(tail) > pdfTailWindow {
		tail = tail[len(tail)-pdfTailWindow:]
	}
	if !bytes.Contains(tail, []byte("%%EOF")) {
		return malformed()
	}
	return previewVerdict{}
}
