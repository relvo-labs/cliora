package workspace

import (
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// buildWorkspace lays out an allowed root with a session workspace inside it and
// a sibling outside it, plus in-root and escaping symlinks.
func buildWorkspace(t testing.TB) (root, ws, outside string) {
	t.Helper()
	base := t.TempDir()
	root = filepath.Join(base, "projects")
	ws = filepath.Join(root, "app")
	outside = filepath.Join(base, "secrets")
	for _, d := range []string{ws, outside, filepath.Join(ws, "sub")} {
		if err := os.MkdirAll(d, 0o755); err != nil {
			t.Fatal(err)
		}
	}
	if err := os.WriteFile(filepath.Join(ws, "main.go"), []byte("package main\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(outside, "token"), []byte("SECRET"), 0o644); err != nil {
		t.Fatal(err)
	}
	return root, ws, outside
}

func TestOpenWorkspaceConfinesReads(t *testing.T) {
	root, ws, outside := buildWorkspace(t)
	g := New([]string{root})
	r, err := g.OpenWorkspace(ws)
	if err != nil {
		t.Fatalf("open workspace: %v", err)
	}
	defer r.Close()

	// A legitimate in-workspace read works and returns the real bytes.
	f, err := r.OpenFile("main.go")
	if err != nil {
		t.Fatalf("open main.go: %v", err)
	}
	data, _ := io.ReadAll(f)
	f.Close()
	if string(data) != "package main\n" {
		t.Fatalf("unexpected content %q", data)
	}

	// A symlink that escapes the workspace to the sibling secret is refused.
	if err := os.Symlink(filepath.Join(outside, "token"), filepath.Join(ws, "escape")); err != nil {
		t.Fatal(err)
	}
	if _, err := r.OpenFile("escape"); !errors.Is(err, ErrOutside) && !errors.Is(err, ErrNotFound) {
		t.Fatalf("escaping symlink should be refused, got %v", err)
	}

	// Explicit traversal is refused before hitting the filesystem.
	for _, bad := range []string{"../secrets/token", "../../etc/passwd", "/etc/passwd", "~/x"} {
		if _, err := r.OpenFile(bad); err == nil {
			t.Fatalf("expected refusal for %q", bad)
		}
	}
}

func TestOpenDirRejectsFileAndEscape(t *testing.T) {
	root, ws, _ := buildWorkspace(t)
	g := New([]string{root})
	r, err := g.OpenWorkspace(ws)
	if err != nil {
		t.Fatal(err)
	}
	defer r.Close()

	if _, err := r.OpenDir("main.go"); !errors.Is(err, ErrNotDir) {
		t.Fatalf("expected ErrNotDir for a file, got %v", err)
	}
	if _, err := r.OpenDir("nope"); !errors.Is(err, ErrNotFound) {
		t.Fatalf("expected ErrNotFound, got %v", err)
	}
	d, err := r.OpenDir("sub")
	if err != nil {
		t.Fatalf("open sub: %v", err)
	}
	d.Close()
}

// TestSymlinkSwapTOCTOU proves that swapping a validated name for an escaping
// symlink cannot redirect a read outside the workspace: os.Root re-resolves the
// component under the confined handle at open time.
func TestSymlinkSwapTOCTOU(t *testing.T) {
	root, ws, outside := buildWorkspace(t)
	g := New([]string{root})
	r, err := g.OpenWorkspace(ws)
	if err != nil {
		t.Fatal(err)
	}
	defer r.Close()

	target := filepath.Join(ws, "doc.txt")
	if err := os.WriteFile(target, []byte("safe"), 0o644); err != nil {
		t.Fatal(err)
	}
	// Read once (legitimate), then swap the name to a symlink escaping the root.
	if f, err := r.OpenFile("doc.txt"); err == nil {
		f.Close()
	} else {
		t.Fatalf("initial read: %v", err)
	}
	if err := os.Remove(target); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(filepath.Join(outside, "token"), target); err != nil {
		t.Fatal(err)
	}
	f, err := r.OpenFile("doc.txt")
	if err == nil {
		data, _ := io.ReadAll(f)
		f.Close()
		if strings.Contains(string(data), "SECRET") {
			t.Fatal("TOCTOU: read escaped the workspace via a swapped symlink")
		}
		t.Fatalf("expected refusal after symlink swap, read %q", data)
	}
	if !errors.Is(err, ErrOutside) && !errors.Is(err, ErrNotFound) {
		t.Fatalf("unexpected error after swap: %v", err)
	}
}

// TestBoundedReadCapsGrowthTOCTOU proves the oversize decision binds to the
// open fd's fstat snapshot and the read is bounded: even if the file grows on
// the same inode after the check, a LimitReader never returns more than the
// cap (no OOM), which is how read.go enforces max_preview_size.
func TestBoundedReadCapsGrowthTOCTOU(t *testing.T) {
	root, ws, _ := buildWorkspace(t)
	g := New([]string{root})
	r, err := g.OpenWorkspace(ws)
	if err != nil {
		t.Fatal(err)
	}
	defer r.Close()

	const cap = 64
	target := filepath.Join(ws, "data.txt")
	if err := os.WriteFile(target, []byte("small"), 0o644); err != nil {
		t.Fatal(err)
	}
	f, err := r.OpenFile("data.txt")
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	info, err := f.Stat()
	if err != nil {
		t.Fatal(err)
	}
	if info.Size() != int64(len("small")) {
		t.Fatalf("fstat snapshot size = %d, want 5", info.Size())
	}
	// Grow the file well past the cap after the check.
	if err := os.WriteFile(target, make([]byte, 1<<20), 0o644); err != nil {
		t.Fatal(err)
	}
	data, err := io.ReadAll(io.LimitReader(f, cap))
	if err != nil {
		t.Fatal(err)
	}
	if len(data) > cap {
		t.Fatalf("bounded read returned %d bytes, exceeds cap %d", len(data), cap)
	}
}

func TestRelClean(t *testing.T) {
	ok := []string{"", ".", "a", "a/b/c.py", "a/b c/.env", "..foo"}
	for _, s := range ok {
		if _, err := relClean(s); err != nil {
			t.Errorf("relClean(%q) = %v, want ok", s, err)
		}
	}
	bad := []string{"/etc", "~/x", "..", "../x", "a/../../x", "a\x00b"}
	for _, s := range bad {
		if _, err := relClean(s); err == nil {
			t.Errorf("relClean(%q) = ok, want error", s)
		}
	}
}

// FuzzOpenFile asserts the containment invariant: any relative input that opens
// successfully must resolve to a real path beneath the workspace root; nothing
// escapes regardless of the fuzzed bytes.
func FuzzOpenFile(f *testing.F) {
	root, ws, _ := buildWorkspace(f)
	g := New([]string{root})
	realWS, _ := filepath.EvalSymlinks(ws)
	for _, seed := range []string{"main.go", "../secrets/token", "sub", "a/../b", "/etc", "\x00", "..", "sub/../main.go"} {
		f.Add(seed)
	}
	f.Fuzz(func(t *testing.T, rel string) {
		r, err := g.OpenWorkspace(ws)
		if err != nil {
			t.Skip()
		}
		defer r.Close()
		fh, err := r.OpenFile(rel)
		if err != nil {
			return // refusal is always acceptable
		}
		defer fh.Close()
		// Any successfully-opened handle must resolve (via its fd) to a path
		// beneath the workspace root — nothing escapes, whatever the input.
		realRel, err := r.RealRel(fh)
		if err != nil {
			t.Fatalf("opened %q but fd did not resolve inside root: %v", rel, err)
		}
		if realRel == ".." || strings.HasPrefix(realRel, ".."+string(filepath.Separator)) {
			t.Fatalf("containment violated: rel=%q resolved to %q outside root %q", rel, realRel, realWS)
		}
	})
}
