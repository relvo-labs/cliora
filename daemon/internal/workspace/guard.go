// Package workspace enforces that every session/file path stays inside a
// configured allowed root, even after symlink resolution (SEC-001,
// FR-WORKSPACE-003, tech §11.2). P2 uses Validate at session launch; P3 reuses
// it for the read-only file relay. Never use strings.HasPrefix for containment
// (a "/a/projects" prefix would wrongly admit "/a/projects-other").
package workspace

import (
	"errors"
	"path/filepath"
	"strings"
)

// Error codes mirror the protocol WORKSPACE_* vocabulary so callers can surface
// them unchanged.
var (
	ErrInvalid   = errors.New("WORKSPACE_INVALID")
	ErrOutside   = errors.New("WORKSPACE_OUTSIDE_ALLOWED_ROOT")
	ErrNotFound  = errors.New("WORKSPACE_NOT_FOUND")
	ErrNotDir    = errors.New("WORKSPACE_NOT_DIRECTORY")
	ErrPermision = errors.New("WORKSPACE_PERMISSION_DENIED")
	// ErrExists is its own sentinel because on the file-upload path "something is
	// already called that" is a normal, expected outcome the user has to be told
	// about (ADR 0026 §3) — not a malformed request. Folding it into ErrInvalid
	// would surface a collision as "invalid path", which explains nothing.
	ErrExists = errors.New("WORKSPACE_EXISTS")
)

// evalSymlinks is a seam so tests can exercise the containment logic without a
// real filesystem; production uses filepath.EvalSymlinks.
type evalFunc func(string) (string, error)

// Guard validates targets against a fixed set of allowed roots.
type Guard struct {
	roots []string
	eval  evalFunc
}

// New builds a Guard from the configured allowed roots. Roots are cleaned and
// made absolute; a root that cannot be made absolute is skipped.
func New(roots []string) *Guard {
	return newGuard(roots, filepath.EvalSymlinks)
}

func newGuard(roots []string, eval evalFunc) *Guard {
	cleaned := make([]string, 0, len(roots))
	for _, r := range roots {
		if abs, err := filepath.Abs(r); err == nil {
			cleaned = append(cleaned, abs)
		}
	}
	return &Guard{roots: cleaned, eval: eval}
}

// Resolve validates target and returns its canonical (symlink-resolved) path.
// The steps follow tech §11.2: reject empty / null byte, make absolute, clean,
// resolve symlinks of both target and root, then containment via filepath.Rel.
func (g *Guard) Resolve(target string) (string, error) {
	if strings.TrimSpace(target) == "" {
		return "", ErrInvalid
	}
	if strings.ContainsRune(target, '\x00') {
		return "", ErrInvalid
	}
	abs, err := filepath.Abs(target)
	if err != nil {
		return "", ErrInvalid
	}
	abs = filepath.Clean(abs)

	resolved, err := g.eval(abs)
	if err != nil {
		// A broken symlink or a missing path is not-found, not an escape.
		return "", ErrNotFound
	}
	for _, root := range g.roots {
		realRoot, err := g.eval(root)
		if err != nil {
			continue // a root that no longer resolves cannot contain anything
		}
		if contained(realRoot, resolved) {
			return resolved, nil
		}
	}
	return "", ErrOutside
}

// contained reports whether path is root itself or lives beneath it, using
// filepath.Rel so a sibling with a shared prefix ("projects-other" vs
// "projects") is correctly excluded.
func contained(root, path string) bool {
	rel, err := filepath.Rel(root, path)
	if err != nil {
		return false
	}
	if rel == "." {
		return true
	}
	return rel != ".." && !strings.HasPrefix(rel, ".."+string(filepath.Separator))
}
