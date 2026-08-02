package files

import (
	"bytes"
	"crypto/rand"
	"encoding/binary"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path"
	"strings"
	"time"

	"github.com/cliora/cliora/daemon/internal/workspace"
)

// Image drop: the only path by which anything is written into a workspace
// (ADR 0024, FR-FILE-009). Everything about the destination is decided here —
// the request carries bytes and a session id, and nothing else. That is not
// tidiness: path traversal, double extensions and overwriting an existing file
// are three problems with one shared entry point, and removing the entry point
// removes all three without leaving validation code to get wrong.

const (
	// uploadDir is the platform-owned subtree. Fixed, never configurable: a
	// config key naming the directory would be the naming channel this design
	// exists to avoid.
	clioraDir  = ".cliora"
	uploadDir  = clioraDir + "/uploads"
	gitignore  = clioraDir + "/.gitignore"
	tempSuffix = ".part"
)

// gitignoreBody keeps dropped images out of the user's commits. Written once,
// never overwritten: the user may have their own rules in this file, and the
// platform does not edit files it did not create.
const gitignoreBody = "*\n"

// UploadResult is the outcome of an image drop. On denial Denied is true and
// Code carries the reason; RelPath is set only on success.
type UploadResult struct {
	RelPath    string
	Mime       string
	Size       int64
	ModifiedAt time.Time

	Denied bool
	Code   string
}

// imageFormat is one accepted image type: its magic-number prefix and the
// extension that prefix implies. The extension comes from the sniff, never from
// the caller, so a name can never disagree with the content.
type imageFormat struct {
	mime      string
	extension string
	// match reports whether data begins with this format's signature.
	match func(data []byte) bool
}

func prefixMatch(sig []byte) func([]byte) bool {
	return func(data []byte) bool { return bytes.HasPrefix(data, sig) }
}

// imageFormats is the accepted set (ADR 0024 §2.1). Order does not matter: the
// signatures are mutually exclusive.
var imageFormats = []imageFormat{
	{"image/png", ".png", prefixMatch([]byte{0x89, 'P', 'N', 'G', 0x0D, 0x0A, 0x1A, 0x0A})},
	{"image/jpeg", ".jpg", prefixMatch([]byte{0xFF, 0xD8, 0xFF})},
	{"image/gif", ".gif", func(d []byte) bool {
		return bytes.HasPrefix(d, []byte("GIF87a")) || bytes.HasPrefix(d, []byte("GIF89a"))
	}},
	// WebP is a RIFF container: "RIFF" <4-byte size> "WEBP". The size field in
	// between is why this one cannot be a plain prefix compare.
	{"image/webp", ".webp", func(d []byte) bool {
		return len(d) >= 12 && bytes.HasPrefix(d, []byte("RIFF")) && bytes.Equal(d[8:12], []byte("WEBP"))
	}},
}

// SniffImage returns the format of data, or ok=false if it is not one of the
// four accepted image types. It reads only the leading bytes and never trusts a
// declared content type.
func SniffImage(data []byte) (mime, extension string, ok bool) {
	for _, f := range imageFormats {
		if f.match(data) {
			return f.mime, f.extension, true
		}
	}
	return "", "", false
}

// UploadEnabled reports whether this node accepts image drop. Central asks at
// registration so the console can hide an entry point rather than offer a
// button that always fails (ADR 0024 W4).
func (s *Service) UploadEnabled() bool { return s.upload.UploadEnabled() }

// SaveImage writes one image into the workspace and returns its
// workspace-relative path. The order of checks is fixed and default-deny, the
// same discipline as Read: cheapest and most decisive first, nothing touches
// the filesystem until the content has been accepted.
//
// A denial is not an error; only unexpected failures return err.
func (s *Service) SaveImage(root *workspace.Root, data []byte, now time.Time) (UploadResult, error) {
	// 1. Disabled by the node (W4).
	if !s.upload.UploadEnabled() {
		return UploadResult{Denied: true, Code: "FILE_UPLOAD_DISABLED"}, nil
	}
	// 2. Size. Central checked this too; Central is not the only conceivable
	// caller, and the daemon owns the resource being consumed.
	if int64(len(data)) > s.upload.MaxBytes {
		return UploadResult{Denied: true, Code: "FILE_UPLOAD_TOO_LARGE"}, nil
	}
	if len(data) == 0 {
		return UploadResult{Denied: true, Code: "FILE_UPLOAD_UNSUPPORTED_TYPE"}, nil
	}
	// 3. Content decides the type, and therefore the extension.
	mime, extension, ok := SniffImage(data)
	if !ok {
		return UploadResult{Denied: true, Code: "FILE_UPLOAD_UNSUPPORTED_TYPE"}, nil
	}
	// 4. Cumulative quota (W2). Recomputed from the directory every time rather
	// than tracked in memory: the user can delete files from the tree, and a
	// counter that disagrees with the filesystem is worse than a directory walk
	// on a path that runs at most a few times a minute.
	usedBytes, todayCount, err := s.uploadUsage(root, now)
	if err != nil {
		return UploadResult{}, err
	}
	if usedBytes+int64(len(data)) > s.upload.MaxSessionBytes ||
		todayCount+1 > s.upload.MaxFilesPerDay {
		return UploadResult{Denied: true, Code: "FILE_UPLOAD_QUOTA_EXCEEDED"}, nil
	}
	// 5. Destination directory, plus the one-off .gitignore.
	dayDir := path.Join(uploadDir, now.UTC().Format("2006-01-02"))
	if err := s.ensureUploadDir(root, dayDir); err != nil {
		if errors.Is(err, errNotADirectory) {
			return UploadResult{Denied: true, Code: "FILE_UPLOAD_FAILED"}, nil
		}
		return UploadResult{}, err
	}
	// 6. Write to a dotted temp file, fsync, then rename into place, so a failed
	// write never leaves something that looks like a usable image.
	name := newULID(now) + extension
	finalRel := path.Join(dayDir, name)
	tempRel := path.Join(dayDir, "."+name+tempSuffix)

	f, err := root.CreateExclusive(tempRel, 0o600)
	if err != nil {
		return UploadResult{}, err
	}
	if err := writeAndSync(f, data); err != nil {
		_ = root.RemoveIn(tempRel)
		return UploadResult{}, err
	}
	if err := root.RenameIn(tempRel, finalRel); err != nil {
		_ = root.RemoveIn(tempRel)
		return UploadResult{}, err
	}
	return UploadResult{
		RelPath:    finalRel,
		Mime:       mime,
		Size:       int64(len(data)),
		ModifiedAt: now.UTC(),
	}, nil
}

func writeAndSync(f *os.File, data []byte) error {
	defer f.Close()
	if _, err := f.Write(data); err != nil {
		return err
	}
	return f.Sync()
}

var errNotADirectory = errors.New("upload path is not a directory")

// ensureUploadDir creates .cliora/uploads/<day>/ and, on first use, the
// .gitignore beside it.
func (s *Service) ensureUploadDir(root *workspace.Root, dayDir string) error {
	// os.Root follows symlinks that stay inside the root, so an in-root
	// `.cliora -> somewhere/else` would silently redirect every write. Lstat
	// binds the decision to what is actually there. This is the write-side
	// equivalent of the read path's RealRel check.
	if info, err := root.LstatIn(clioraDir); err == nil {
		if !info.IsDir() {
			return errNotADirectory
		}
	} else if !errors.Is(err, workspace.ErrNotFound) {
		return err
	}
	if err := root.MkdirAllIn(dayDir, 0o700); err != nil {
		return err
	}
	// Only if absent: the platform does not overwrite a file the user may own.
	if _, err := root.LstatIn(gitignore); errors.Is(err, workspace.ErrNotFound) {
		g, err := root.CreateExclusive(gitignore, 0o600)
		if err == nil {
			_ = writeAndSync(g, []byte(gitignoreBody))
		}
		// A failure here is not fatal: the images are already useful, and the
		// worst case is a noisier `git status`.
	}
	return nil
}

// uploadUsage totals the bytes under the upload subtree and counts today's
// files. It walks only that subtree, never the rest of the workspace.
func (s *Service) uploadUsage(root *workspace.Root, now time.Time) (bytes int64, today int, err error) {
	todayPrefix := uploadDir + "/" + now.UTC().Format("2006-01-02") + "/"
	walkErr := fs.WalkDir(root.FS(), uploadDir, func(p string, d fs.DirEntry, err error) error {
		if err != nil {
			// The subtree simply may not exist yet.
			if errors.Is(err, fs.ErrNotExist) {
				return fs.SkipAll
			}
			return nil
		}
		if d.IsDir() {
			return nil
		}
		info, statErr := d.Info()
		if statErr != nil {
			return nil
		}
		bytes += info.Size()
		if strings.HasPrefix(p, todayPrefix) && !strings.HasSuffix(p, tempSuffix) {
			today++
		}
		return nil
	})
	if walkErr != nil && !errors.Is(walkErr, fs.ErrNotExist) {
		return 0, 0, walkErr
	}
	return bytes, today, nil
}

// PruneUploads deletes dropped images older than the retention period and
// removes the day directories left empty behind them (FR-FILE-009.AC-09).
//
// It deliberately does not run at session end. The CLI transcript keeps
// referring to these paths, and an image that disappears when the session does
// presents to the user as the model forgetting, not as the platform tidying up.
func (s *Service) PruneUploads(root *workspace.Root, now time.Time) (removed int, freed int64) {
	cutoff := now.UTC().AddDate(0, 0, -s.upload.RetentionDays)
	days, err := fs.ReadDir(root.FS(), uploadDir)
	if err != nil {
		return 0, 0
	}
	for _, day := range days {
		if !day.IsDir() {
			continue
		}
		dayRel := path.Join(uploadDir, day.Name())
		entries, err := fs.ReadDir(root.FS(), dayRel)
		if err != nil {
			continue
		}
		remaining := 0
		for _, e := range entries {
			info, err := e.Info()
			if err != nil {
				remaining++
				continue
			}
			if info.ModTime().UTC().After(cutoff) {
				remaining++
				continue
			}
			if err := root.RemoveIn(path.Join(dayRel, e.Name())); err == nil {
				removed++
				freed += info.Size()
			} else {
				remaining++
			}
		}
		if remaining == 0 {
			// Best effort: an empty day directory is clutter, not a failure.
			_ = root.RemoveIn(dayRel)
		}
	}
	return removed, freed
}

// UploadDirRel is the workspace-relative upload subtree, exported so doctor and
// tests refer to the same constant the writer uses.
func UploadDirRel() string { return uploadDir }

// ulidEncoding is Crockford base32, as used by the protocol's request ids.
const ulidEncoding = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

// newULID returns a 26-character ULID: 48 bits of millisecond timestamp then 80
// bits of randomness. ULID rather than UUID so that `ls` in the upload
// directory comes out in drop order, which is what someone looking for "the one
// I just added" actually wants.
func newULID(now time.Time) string {
	var raw [16]byte
	ms := uint64(now.UTC().UnixMilli())
	binary.BigEndian.PutUint64(raw[:8], ms<<16)
	if _, err := rand.Read(raw[6:]); err != nil {
		// crypto/rand does not fail in practice; if it ever does, a predictable
		// name is still safe here (O_EXCL refuses a collision) but must be loud.
		panic(fmt.Sprintf("upload: read random: %v", err))
	}
	hi := binary.BigEndian.Uint64(raw[0:8])
	lo := binary.BigEndian.Uint64(raw[8:16])
	var out [26]byte
	// 26 characters of 5 bits, least significant last.
	for i := 0; i < 26; i++ {
		out[25-i] = ulidEncoding[ulidGroup(hi, lo, uint(5*i))&0x1f]
	}
	return string(out[:])
}

// ulidGroup returns (hi:lo >> shift) as a 128-bit big-endian value. Go defines
// a shift wider than the operand as zero, so shift == 0 needs no special case.
func ulidGroup(hi, lo uint64, shift uint) uint64 {
	if shift >= 64 {
		return hi >> (shift - 64)
	}
	return lo>>shift | hi<<(64-shift)
}
