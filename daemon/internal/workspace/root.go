package workspace

import (
	"errors"
	"io/fs"
	"os"
	"path"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
)

// Root is a traversal-safe handle to a session's workspace directory. It wraps
// os.Root (Go 1.24+, openat2 RESOLVE_BENEATH on Linux) so every subsequent path
// operation is confined to the workspace by the kernel: a "../" segment or a
// symlink that would escape the root is refused even if the tree is mutated
// after validation. This closes the resolve→open TOCTOU window that the plain
// Resolve string cannot (ADR 0014, SEC-001). P3 list/read/search open a Root
// once per request and operate only through it.
type Root struct {
	root      *os.Root
	canonical string
}

// OpenWorkspace re-canonicalises workspace against the allowed roots (never
// trusting a prior listing) and returns a confined handle rooted at it. The
// caller must Close the returned Root. The workspace is expected to already sit
// inside an enabled allowed root (validated at session launch); this re-check
// enforces it again on every filesystem operation.
func (g *Guard) OpenWorkspace(workspace string) (*Root, error) {
	canonical, err := g.Resolve(workspace)
	if err != nil {
		return nil, err
	}
	r, err := os.OpenRoot(canonical)
	if err != nil {
		return nil, mapPathErr(err)
	}
	return &Root{root: r, canonical: canonical}, nil
}

// Canonical is the resolved absolute path of the workspace root. It is for
// daemon-internal use and audit classification only; it is never returned to
// the browser (which sees workspace-relative paths only).
func (r *Root) Canonical() string { return r.canonical }

// FS returns a read-only fs.FS confined to the workspace root, suitable for
// fs.WalkDir during filename search. Like the other handle operations it does
// not follow symlinks out of the root.
func (r *Root) FS() fs.FS { return r.root.FS() }

// Close releases the underlying directory handle.
func (r *Root) Close() error { return r.root.Close() }

// relClean validates and normalises a workspace-relative path. Empty or "."
// means the workspace root itself. Absolute paths, "~", null bytes, and any
// ".." escape are rejected here; os.Root enforces the same at the syscall layer
// as defence in depth.
func relClean(rel string) (string, error) {
	if strings.ContainsRune(rel, 0) {
		return "", ErrInvalid
	}
	if rel == "" || rel == "." {
		return ".", nil
	}
	if strings.HasPrefix(rel, "/") || strings.HasPrefix(rel, "~") {
		return "", ErrInvalid
	}
	clean := path.Clean(rel)
	if clean == ".." || strings.HasPrefix(clean, "../") {
		return "", ErrOutside
	}
	return clean, nil
}

// OpenDir opens a directory relative to the workspace root for listing. The
// returned file is a confined handle; its entries are read via ReadDir.
func (r *Root) OpenDir(rel string) (*os.File, error) {
	clean, err := relClean(rel)
	if err != nil {
		return nil, err
	}
	f, err := r.root.Open(clean)
	if err != nil {
		return nil, mapPathErr(err)
	}
	info, err := f.Stat()
	if err != nil {
		_ = f.Close()
		return nil, ErrInvalid
	}
	if !info.IsDir() {
		_ = f.Close()
		return nil, ErrNotDir
	}
	return f, nil
}

// OpenFile opens a file relative to the workspace root for reading. os.Root
// confines resolution to the root: an escaping symlink or ".." is refused, but
// a symlink that stays within the workspace is followed. The caller must Stat
// the returned handle (not the path) for the regular-file and size checks and
// read from the same handle, so a post-open replacement cannot redirect the
// read or bypass the size cap. Because an in-root symlink can point at a
// sensitive in-root file (e.g. notes.txt -> .env) and bypass a name-only check,
// callers must also classify RealRel(handle) — the fd's resolved name — before
// serving content (ADR 0014).
func (r *Root) OpenFile(rel string) (*os.File, error) {
	clean, err := relClean(rel)
	if err != nil {
		return nil, err
	}
	f, err := r.root.Open(clean)
	if err != nil {
		return nil, mapPathErr(err)
	}
	return f, nil
}

// MkdirAllIn creates rel and any missing parents beneath the root. Every
// component is resolved by os.Root, so a ".." segment or an escaping symlink is
// refused by the kernel exactly as it is for reads (ADR 0024 W1).
func (r *Root) MkdirAllIn(rel string, perm os.FileMode) error {
	clean, err := relClean(rel)
	if err != nil {
		return err
	}
	if clean == "." {
		return nil
	}
	if err := r.root.MkdirAll(clean, perm); err != nil {
		return mapPathErr(err)
	}
	return nil
}

// CreateExclusive opens rel for writing and fails if it already exists.
//
// O_EXCL is load-bearing rather than defensive: the daemon generates every name
// it writes (ADR 0024 §3), so a collision does not mean "try again with a
// suffix" — it means something else is writing into a directory this code
// believes it owns, and continuing would overwrite it. O_NOFOLLOW matches the
// read path's refusal to follow a symlink as the final component.
func (r *Root) CreateExclusive(rel string, perm os.FileMode) (*os.File, error) {
	clean, err := relClean(rel)
	if err != nil {
		return nil, err
	}
	f, err := r.root.OpenFile(clean, os.O_WRONLY|os.O_CREATE|os.O_EXCL|syscall.O_NOFOLLOW, perm)
	if err != nil {
		return nil, mapPathErr(err)
	}
	return f, nil
}

// RenameIn renames oldRel to newRel, both confined to the root. Used to publish
// a fully written temp file atomically, so a failed write never leaves a
// partial file under a name that looks finished.
func (r *Root) RenameIn(oldRel, newRel string) error {
	oldClean, err := relClean(oldRel)
	if err != nil {
		return err
	}
	newClean, err := relClean(newRel)
	if err != nil {
		return err
	}
	if err := r.root.Rename(oldClean, newClean); err != nil {
		return mapPathErr(err)
	}
	return nil
}

// RemoveIn deletes rel beneath the root. Used by upload pruning and to clean up
// a temp file after a failed write.
func (r *Root) RemoveIn(rel string) error {
	clean, err := relClean(rel)
	if err != nil {
		return err
	}
	if err := r.root.Remove(clean); err != nil {
		return mapPathErr(err)
	}
	return nil
}

// LstatIn stats rel without following a final symlink. Callers use it to
// confirm that a directory they are about to write into is a real directory:
// os.Root follows symlinks that stay inside the root, so an in-root symlink
// could otherwise redirect writes to another part of the workspace. This is the
// write-side counterpart of RealRel on the read path.
func (r *Root) LstatIn(rel string) (os.FileInfo, error) {
	clean, err := relClean(rel)
	if err != nil {
		return nil, err
	}
	info, err := r.root.Lstat(clean)
	if err != nil {
		return nil, mapPathErr(err)
	}
	return info, nil
}

// RealRel returns the workspace-relative resolved path of an open handle, read
// from /proc/self/fd (Linux daemon). It binds a follow-up check (e.g. the
// sensitive-name policy) to the actual opened inode rather than to a path that
// could be swapped, closing the in-root symlink-to-sensitive bypass. It returns
// an error if the handle cannot be resolved or resolves outside the root.
func (r *Root) RealRel(f *os.File) (string, error) {
	target, err := os.Readlink("/proc/self/fd/" + strconv.FormatUint(uint64(f.Fd()), 10))
	if err != nil {
		return "", err
	}
	rel, err := filepath.Rel(r.canonical, target)
	if err != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
		return "", ErrOutside
	}
	return rel, nil
}

// mapPathErr converts an os.Root/open error into the WORKSPACE_* vocabulary. An
// escape attempt (os.Root refusing a "../" or out-of-root symlink) is treated
// as outside-root; missing paths as not-found; EACCES as permission-denied.
func mapPathErr(err error) error {
	switch {
	case errors.Is(err, fs.ErrNotExist):
		return ErrNotFound
	case errors.Is(err, fs.ErrPermission):
		return ErrPermision
	case isEscape(err):
		return ErrOutside
	default:
		return ErrInvalid
	}
}

// isEscape reports whether err is os.Root's "path escapes from parent" refusal.
// The sentinel is not exported by the os package, so match on the message.
func isEscape(err error) bool {
	return err != nil && strings.Contains(err.Error(), "escapes from parent")
}
