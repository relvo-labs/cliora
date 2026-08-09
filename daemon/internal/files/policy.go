// Package files implements the daemon side of the P3 read-only workspace file
// relay: directory listing, filename search, and single-file preview. Every
// path operation goes through a workspace.Root handle (os.Root confined, ADR
// 0014) so nothing escapes the session workspace. This package is the sole
// authority on the sensitive/binary/oversize policy (tech §11.5-11.8, ADR
// 0015); Central only relays and authorizes.
package files

import (
	"bytes"
	"path"
	"path/filepath"
	"strings"
	"unicode/utf8"

	"github.com/cliora/cliora/daemon/internal/config"
)

// Policy decides whether a file may be previewed. It is built once from config
// and is read-only thereafter (safe for concurrent use).
type Policy struct {
	deniedPatterns []string
	deniedDirs     []string
}

// NewPolicy compiles the sensitive-file policy from filesystem config.
func NewPolicy(fs config.FilesystemConfig) *Policy {
	return &Policy{
		deniedPatterns: fs.DeniedPatterns,
		deniedDirs:     fs.DeniedDirectories,
	}
}

// SensitiveClassification returns a non-empty classification if relPath is a
// sensitive file that must not be previewed, else "". The classification is a
// coarse category (never the path or content) suitable for audit (SEC-006, ADR
// 0014). A path segment matching a denied directory denies everything beneath
// it; otherwise the base name is matched (glob) against the denied patterns.
func (p *Policy) SensitiveClassification(relPath string) string {
	// Session credentials are platform-defined secrets, not an operator-tunable
	// filename convention. Keep this check ahead of the configured policy so an
	// empty/replaced denied_patterns list can never make a projected token
	// previewable (plan/17 D14, SEC-001).
	if isProjectedToken(relPath) {
		return "sensitive"
	}
	segments := strings.Split(filepath.ToSlash(relPath), "/")
	for _, seg := range segments[:max(0, len(segments)-1)] {
		for _, d := range p.deniedDirs {
			if ok, _ := filepath.Match(d, seg); ok {
				return "sensitive_dir"
			}
		}
	}
	base := segments[len(segments)-1]
	for _, dir := range p.deniedDirs {
		if ok, _ := filepath.Match(dir, base); ok {
			return "sensitive_dir"
		}
	}
	for _, pat := range p.deniedPatterns {
		if ok, _ := filepath.Match(pat, base); ok {
			return classify(base)
		}
	}
	return ""
}

// isProjectedToken identifies the credential files produced by context.project.
// The scope is deliberately the closed platform-owned .cliora tree: a user's
// ordinary source file named foo.token is still governed by their configured
// policy, while every .cliora/**/*.token remains denied regardless of config.
func isProjectedToken(relPath string) bool {
	clean := path.Clean(filepath.ToSlash(relPath))
	return clean != "." &&
		strings.HasPrefix(clean, clioraDir+"/") &&
		strings.HasSuffix(strings.ToLower(path.Base(clean)), ".token")
}

// classify maps a denied base name to an audit category. It inspects only the
// name shape, never content.
func classify(name string) string {
	lower := strings.ToLower(name)
	ext := filepath.Ext(lower)
	switch {
	case lower == ".env" || strings.HasPrefix(lower, ".env."):
		return "dotenv"
	case ext == ".pem" || ext == ".key" || lower == "id_rsa" || lower == "id_ed25519":
		return "private_key"
	case ext == ".p12" || ext == ".pfx":
		return "keystore"
	default:
		return "sensitive"
	}
}

// Verdict is the outcome of classifying a file's bytes.
type Verdict int

const (
	// VerdictText means the content is UTF-8 text and may be previewed.
	VerdictText Verdict = iota
	// VerdictBinary means the content is not text; preview is denied.
	VerdictBinary
	// VerdictUnsupportedEncoding means the content looks like text but is not
	// UTF-8 (Big5, GBK, Latin-1, UTF-16…). Preview is denied, but for a
	// different reason and with a different next step for the user: transcode
	// it, rather than give up. Kept distinct from VerdictBinary because saying
	// "binary" about a Big5 source file is simply wrong.
	VerdictUnsupportedEncoding
)

// controlRatioDenominator is the share of runes that may be control characters
// before content is treated as binary (1/10 = 10%).
const controlRatioDenominator = 10

// Classify decides whether content may be previewed, and returns a coarse mime
// hint (tech §11.6, ADR 0015 amendment 2026-08-01, FR-FILE-008).
//
// It examines the WHOLE buffer. The caller has already bounded it by
// filesystem.max_preview_size (2 MiB by default), and measurement showed the
// old 8 KiB window was the single largest source of wrong answers in both
// directions:
//
//   - Too strict: window[:8192] can cut inside a multi-byte rune, so utf8.Valid
//     fails and a perfectly good UTF-8 document is reported as binary. Measured
//     on this repository: 20 of 878 valid-UTF-8 text files, i.e. 8.7% of those
//     over 8 KiB containing multi-byte runes. For pure CJK the cut lands
//     mid-rune two times in three.
//   - Too lax: a binary file whose first 8 KiB happen to be printable ASCII was
//     served as text, so FR-FILE-004.AC-02 did not hold either.
//
// Scanning everything costs 2.66 ms for 2 MiB (0.09% of ADR 0015's 3 s preview
// budget), so the window was never buying anything. If a future change
// reintroduces a window for performance, it MUST trim the window back to a rune
// boundary before validating — that omission is exactly how this bug was built.
// Prefer fusing the UTF-8 and control-character passes instead; the rune loop,
// not the byte scan, is what costs.
func Classify(content []byte) (Verdict, string) {
	if len(content) == 0 {
		return VerdictText, "text/plain"
	}
	// 1. A NUL anywhere means binary (FR-FILE-008.AC-03). IndexByte is
	// vectorised, so this pass is nearly free even at 2 MiB.
	if bytes.IndexByte(content, 0) >= 0 {
		return VerdictBinary, "application/octet-stream"
	}
	// 2. UTF-8 over the whole buffer, so there is no truncation boundary to get
	// wrong. Failure here is an encoding we cannot read, not proof of binary.
	if !utf8.Valid(content) {
		return VerdictUnsupportedEncoding, "text/plain; charset=unknown"
	}
	// 3. Control-character ratio, runes over runes. The old comparison put a
	// rune count over a byte length, which made the same density of control
	// characters mean different things in an ASCII file and a CJK one.
	control, runes := 0, 0
	for i := 0; i < len(content); {
		r, size := utf8.DecodeRune(content[i:])
		runes++
		if isControlRune(r) {
			control++
		}
		i += size
	}
	if control*controlRatioDenominator > runes {
		return VerdictBinary, "application/octet-stream"
	}
	return VerdictText, "text/plain"
}

// isControlRune reports whether r counts against the control-character ratio.
//
// ESC, FF and VT are deliberately NOT control characters here. An ANSI-coloured
// build log (npm, cargo, pytest, go test) is an ordinary text file that people
// very much want to read in the browser, and three colour pairs per line was
// enough to trip the old rule. Form feed is a page break in older source files.
func isControlRune(r rune) bool {
	switch r {
	case '\t', '\n', '\r', 0x1b, 0x0c, 0x0b:
		return false
	}
	return r < 0x20 || r == 0x7f
}

// DetectBinary reports whether content must not be previewed, plus a mime hint.
// It is the boolean view of Classify, kept for callers that only need the
// allow/deny decision; Read uses Classify directly so it can tell the browser
// which kind of denial this is.
func DetectBinary(content []byte) (bool, string) {
	verdict, mime := Classify(content)
	return verdict != VerdictText, mime
}

// LanguageHint maps a file name to a Monaco language id by extension. It never
// affects the security decision, only the preview rendering (FR-FILE-002).
func LanguageHint(name string) string {
	switch strings.ToLower(filepath.Ext(name)) {
	case ".go":
		return "go"
	case ".py":
		return "python"
	case ".ts", ".tsx":
		return "typescript"
	case ".js", ".jsx", ".mjs", ".cjs":
		return "javascript"
	case ".vue":
		return "vue"
	case ".json":
		return "json"
	case ".yaml", ".yml":
		return "yaml"
	case ".toml":
		return "toml"
	case ".md", ".markdown":
		return "markdown"
	case ".sh", ".bash":
		return "shell"
	case ".sql":
		return "sql"
	case ".html", ".htm":
		return "html"
	case ".css":
		return "css"
	case ".rs":
		return "rust"
	default:
		return "plaintext"
	}
}
