// Package files implements the daemon side of the P3 read-only workspace file
// relay: directory listing, filename search, and single-file preview. Every
// path operation goes through a workspace.Root handle (os.Root confined, ADR
// 0014) so nothing escapes the session workspace. This package is the sole
// authority on the sensitive/binary/oversize policy (tech §11.5-11.8, ADR
// 0015); Central only relays and authorizes.
package files

import (
	"path/filepath"
	"strings"
	"unicode/utf8"

	"github.com/cliora/cliora/daemon/internal/config"
)

// sniffWindow is the byte prefix examined for binary detection (tech §11.6).
const sniffWindow = 8 * 1024

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

// DetectBinary reports whether the sampled bytes look like a binary file and a
// coarse mime hint. A NUL byte, invalid UTF-8, or a high ratio of control
// characters marks it binary (tech §11.6). Unknown/undetermined content is
// treated as binary by the caller (deny preview by default, ADR 0015).
func DetectBinary(sample []byte) (bool, string) {
	if len(sample) == 0 {
		return false, "text/plain"
	}
	window := sample
	if len(window) > sniffWindow {
		window = window[:sniffWindow]
	}
	for _, b := range window {
		if b == 0 {
			return true, "application/octet-stream"
		}
	}
	if !utf8.Valid(window) {
		return true, "application/octet-stream"
	}
	control := 0
	for i := 0; i < len(window); {
		r, size := utf8.DecodeRune(window[i:])
		if r == '\t' || r == '\n' || r == '\r' {
			i += size
			continue
		}
		if r < 0x20 || r == 0x7f {
			control++
		}
		i += size
	}
	// More than ~10% control characters is treated as binary.
	if control*10 > len(window) {
		return true, "application/octet-stream"
	}
	return false, "text/plain"
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
