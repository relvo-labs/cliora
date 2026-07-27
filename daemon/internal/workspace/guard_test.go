package workspace

import (
	"errors"
	"os"
	"path/filepath"
	"testing"
)

// realGuard builds a Guard over a real temp tree so symlink resolution is
// exercised end to end.
func TestResolveContainmentMatrix(t *testing.T) {
	base := t.TempDir()
	root := filepath.Join(base, "projects")
	sibling := filepath.Join(base, "projects-other")
	for _, d := range []string{root, sibling, filepath.Join(root, "app")} {
		if err := os.MkdirAll(d, 0o755); err != nil {
			t.Fatal(err)
		}
	}
	// A symlink inside root that escapes to the sibling.
	escape := filepath.Join(root, "escape")
	if err := os.Symlink(sibling, escape); err != nil {
		t.Fatal(err)
	}
	// A symlink inside root that stays inside root.
	inward := filepath.Join(root, "inward")
	if err := os.Symlink(filepath.Join(root, "app"), inward); err != nil {
		t.Fatal(err)
	}
	broken := filepath.Join(root, "broken")
	if err := os.Symlink(filepath.Join(root, "nope"), broken); err != nil {
		t.Fatal(err)
	}

	g := New([]string{root})
	cases := []struct {
		name    string
		target  string
		wantErr error
	}{
		{"root itself", root, nil},
		{"subdir", filepath.Join(root, "app"), nil},
		{"inward symlink", inward, nil},
		{"traversal escape", filepath.Join(root, "..", "projects-other"), ErrOutside},
		{"prefix collision sibling", sibling, ErrOutside},
		{"symlink escape", escape, ErrOutside},
		{"broken symlink", broken, ErrNotFound},
		{"absolute outside", "/etc", ErrOutside},
		{"missing path", filepath.Join(root, "does-not-exist"), ErrNotFound},
		{"empty", "", ErrInvalid},
		{"null byte", root + "\x00/x", ErrInvalid},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			_, err := g.Resolve(tc.target)
			if tc.wantErr == nil && err != nil {
				t.Fatalf("expected ok, got %v", err)
			}
			if tc.wantErr != nil && !errors.Is(err, tc.wantErr) {
				t.Fatalf("expected %v, got %v", tc.wantErr, err)
			}
		})
	}
}

func TestResolveReturnsCanonicalPath(t *testing.T) {
	root := t.TempDir()
	app := filepath.Join(root, "app")
	if err := os.MkdirAll(app, 0o755); err != nil {
		t.Fatal(err)
	}
	link := filepath.Join(root, "link")
	if err := os.Symlink(app, link); err != nil {
		t.Fatal(err)
	}
	g := New([]string{root})
	got, err := g.Resolve(link)
	if err != nil {
		t.Fatalf("resolve: %v", err)
	}
	want, _ := filepath.EvalSymlinks(app)
	if got != want {
		t.Fatalf("expected canonical %q, got %q", want, got)
	}
}

func TestNoRootsRejectsEverything(t *testing.T) {
	g := New(nil)
	if _, err := g.Resolve(t.TempDir()); !errors.Is(err, ErrOutside) {
		t.Fatalf("expected ErrOutside with no roots, got %v", err)
	}
}
