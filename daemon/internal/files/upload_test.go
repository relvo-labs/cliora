package files

import (
	"bytes"
	"encoding/binary"
	"image"
	"image/color"
	"image/gif"
	"image/jpeg"
	"image/png"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/cliora/cliora/daemon/internal/config"
	"github.com/cliora/cliora/daemon/internal/workspace"
)

// Image-drop tests (FR-FILE-009, ADR 0024). The properties under test are the
// ones the design leans on: the caller cannot influence the destination, the
// content decides the type, every limit denies without writing, and a failed
// write leaves nothing behind.

func uploadService(t *testing.T, tune func(*config.UploadConfig)) *Service {
	t.Helper()
	cfg := &config.Config{}
	cfg.Filesystem.MaxPreviewSize = config.DefaultMaxPreviewSize
	cfg.Filesystem.Upload = config.UploadConfig{
		MaxBytes:        config.DefaultUploadMaxBytes,
		MaxSessionBytes: config.DefaultUploadMaxSessionBytes,
		MaxFilesPerDay:  config.DefaultUploadMaxFilesPerDay,
		RetentionDays:   config.DefaultUploadRetentionDays,
	}
	if tune != nil {
		tune(&cfg.Filesystem.Upload)
	}
	return NewService(cfg, nil)
}

func uploadRoot(t *testing.T) (*workspace.Root, string) {
	t.Helper()
	dir := t.TempDir()
	guard := workspace.New([]string{dir})
	root, err := guard.OpenWorkspace(dir)
	if err != nil {
		t.Fatalf("open workspace: %v", err)
	}
	t.Cleanup(func() { _ = root.Close() })
	return root, dir
}

func sampleImage() image.Image {
	m := image.NewRGBA(image.Rect(0, 0, 8, 8))
	for y := 0; y < 8; y++ {
		for x := 0; x < 8; x++ {
			m.Set(x, y, color.RGBA{uint8(x * 30), uint8(y * 30), 90, 255})
		}
	}
	return m
}

func pngBytes(t *testing.T) []byte {
	t.Helper()
	var b bytes.Buffer
	if err := png.Encode(&b, sampleImage()); err != nil {
		t.Fatal(err)
	}
	return b.Bytes()
}

func webpBytes() []byte {
	// RIFF <size> WEBP + a body. No WebP encoder exists in the standard
	// library; the sniffer only reads the container header.
	out := append([]byte{}, 'R', 'I', 'F', 'F')
	out = binary.LittleEndian.AppendUint32(out, 32)
	out = append(out, 'W', 'E', 'B', 'P', 'V', 'P', '8', 'L')
	return append(out, bytes.Repeat([]byte{0xAB}, 28)...)
}

var now = time.Date(2026, 8, 5, 10, 30, 0, 0, time.UTC)

func TestSaveImageAcceptsFourFormats(t *testing.T) {
	var jpg, animated bytes.Buffer
	if err := jpeg.Encode(&jpg, sampleImage(), nil); err != nil {
		t.Fatal(err)
	}
	if err := gif.Encode(&animated, sampleImage(), nil); err != nil {
		t.Fatal(err)
	}
	cases := []struct {
		name     string
		data     []byte
		wantMime string
		wantExt  string
	}{
		{"png", pngBytes(t), "image/png", ".png"},
		{"jpeg", jpg.Bytes(), "image/jpeg", ".jpg"},
		{"gif", animated.Bytes(), "image/gif", ".gif"},
		{"webp", webpBytes(), "image/webp", ".webp"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			root, dir := uploadRoot(t)
			s := uploadService(t, nil)
			res, err := s.SaveImage(root, tc.data, now)
			if err != nil || res.Denied {
				t.Fatalf("save: err=%v denied=%v code=%s", err, res.Denied, res.Code)
			}
			if res.Mime != tc.wantMime {
				t.Errorf("mime=%s want %s", res.Mime, tc.wantMime)
			}
			if !strings.HasSuffix(res.RelPath, tc.wantExt) {
				t.Errorf("rel path %q does not end in %s", res.RelPath, tc.wantExt)
			}
			if !strings.HasPrefix(res.RelPath, ".cliora/uploads/2026-08-05/") {
				t.Errorf("rel path %q is not under the dated upload directory", res.RelPath)
			}
			on, err := os.ReadFile(filepath.Join(dir, res.RelPath))
			if err != nil {
				t.Fatalf("read back: %v", err)
			}
			if !bytes.Equal(on, tc.data) {
				t.Error("stored bytes differ from the uploaded bytes")
			}
		})
	}
}

// The name is 26 Crockford base32 characters and contains nothing the caller
// supplied, so there is no traversal, double extension or overwrite to defend.
func TestSaveImageNamesAreDaemonGenerated(t *testing.T) {
	root, _ := uploadRoot(t)
	s := uploadService(t, nil)
	seen := map[string]bool{}
	for i := 0; i < 20; i++ {
		res, err := s.SaveImage(root, pngBytes(t), now)
		if err != nil || res.Denied {
			t.Fatalf("save %d: err=%v code=%s", i, err, res.Code)
		}
		base := filepath.Base(res.RelPath)
		name := strings.TrimSuffix(base, ".png")
		if len(name) != 26 {
			t.Fatalf("name %q is %d characters, want a 26-character ULID", name, len(name))
		}
		if strings.ContainsAny(base, "/\\ ") {
			t.Fatalf("name %q contains a separator or space", base)
		}
		for _, c := range name {
			if !strings.ContainsRune(ulidEncoding, c) {
				t.Fatalf("name %q contains %q, outside Crockford base32", name, c)
			}
		}
		if seen[base] {
			t.Fatalf("duplicate name %q", base)
		}
		seen[base] = true
	}
}

func TestSaveImageRejectsNonImages(t *testing.T) {
	cases := map[string][]byte{
		"elf":           append([]byte{0x7f, 'E', 'L', 'F'}, make([]byte, 64)...),
		"text":          []byte("just some text, honest\n"),
		"empty":         nil,
		"svg":           []byte(`<svg xmlns="http://www.w3.org/2000/svg"><script/></svg>`),
		"pdf":           []byte("%PDF-1.7\n%âãÏÓ\n"),
		"png-truncated": []byte{0x89, 'P', 'N'},
		"riff-not-webp": append([]byte("RIFF\x20\x00\x00\x00WAVE"), make([]byte, 16)...),
	}
	for name, data := range cases {
		t.Run(name, func(t *testing.T) {
			root, dir := uploadRoot(t)
			s := uploadService(t, nil)
			res, err := s.SaveImage(root, data, now)
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if !res.Denied || res.Code != "FILE_UPLOAD_UNSUPPORTED_TYPE" {
				t.Fatalf("denied=%v code=%s, want FILE_UPLOAD_UNSUPPORTED_TYPE", res.Denied, res.Code)
			}
			assertNothingWritten(t, dir)
		})
	}
}

// A denial must not leave a directory, a temp file or a .gitignore behind: the
// user should not be able to tell, from their workspace, that a rejected upload
// was ever attempted.
func assertNothingWritten(t *testing.T, dir string) {
	t.Helper()
	if _, err := os.Stat(filepath.Join(dir, ".cliora")); !os.IsNotExist(err) {
		var found []string
		_ = filepath.WalkDir(filepath.Join(dir, ".cliora"), func(p string, d fs.DirEntry, err error) error {
			if err == nil {
				found = append(found, p)
			}
			return nil
		})
		t.Fatalf("denial created files: %v", found)
	}
}

func TestSaveImageTooLarge(t *testing.T) {
	root, dir := uploadRoot(t)
	s := uploadService(t, func(u *config.UploadConfig) { u.MaxBytes = 1024 })
	res, err := s.SaveImage(root, append(pngBytes(t), make([]byte, 2048)...), now)
	if err != nil {
		t.Fatal(err)
	}
	if !res.Denied || res.Code != "FILE_UPLOAD_TOO_LARGE" {
		t.Fatalf("denied=%v code=%s, want FILE_UPLOAD_TOO_LARGE", res.Denied, res.Code)
	}
	assertNothingWritten(t, dir)
}

func TestSaveImageDisabled(t *testing.T) {
	root, dir := uploadRoot(t)
	off := false
	s := uploadService(t, func(u *config.UploadConfig) { u.Enabled = &off })
	res, err := s.SaveImage(root, pngBytes(t), now)
	if err != nil {
		t.Fatal(err)
	}
	if !res.Denied || res.Code != "FILE_UPLOAD_DISABLED" {
		t.Fatalf("denied=%v code=%s, want FILE_UPLOAD_DISABLED", res.Denied, res.Code)
	}
	if s.UploadEnabled() {
		t.Error("UploadEnabled must report false so Central can hide the entry point")
	}
	assertNothingWritten(t, dir)
}

func TestSaveImageQuotas(t *testing.T) {
	t.Run("per-day count", func(t *testing.T) {
		root, _ := uploadRoot(t)
		s := uploadService(t, func(u *config.UploadConfig) { u.MaxFilesPerDay = 3 })
		for i := 0; i < 3; i++ {
			if res, err := s.SaveImage(root, pngBytes(t), now); err != nil || res.Denied {
				t.Fatalf("save %d should succeed: err=%v code=%s", i, err, res.Code)
			}
		}
		res, err := s.SaveImage(root, pngBytes(t), now)
		if err != nil {
			t.Fatal(err)
		}
		if !res.Denied || res.Code != "FILE_UPLOAD_QUOTA_EXCEEDED" {
			t.Fatalf("4th save: denied=%v code=%s, want FILE_UPLOAD_QUOTA_EXCEEDED", res.Denied, res.Code)
		}
		// The next UTC day has its own allowance.
		if res, err := s.SaveImage(root, pngBytes(t), now.AddDate(0, 0, 1)); err != nil || res.Denied {
			t.Fatalf("next day should succeed: err=%v code=%s", err, res.Code)
		}
	})

	t.Run("cumulative bytes", func(t *testing.T) {
		root, _ := uploadRoot(t)
		data := pngBytes(t)
		// Room for exactly two.
		s := uploadService(t, func(u *config.UploadConfig) {
			u.MaxSessionBytes = int64(len(data))*2 + 1
		})
		for i := 0; i < 2; i++ {
			if res, err := s.SaveImage(root, data, now); err != nil || res.Denied {
				t.Fatalf("save %d should succeed: code=%s", i, res.Code)
			}
		}
		res, err := s.SaveImage(root, data, now)
		if err != nil {
			t.Fatal(err)
		}
		if !res.Denied || res.Code != "FILE_UPLOAD_QUOTA_EXCEEDED" {
			t.Fatalf("denied=%v code=%s, want FILE_UPLOAD_QUOTA_EXCEEDED", res.Denied, res.Code)
		}
	})
}

func TestSaveImageWritesGitignoreOnceAndNeverOverwrites(t *testing.T) {
	root, dir := uploadRoot(t)
	s := uploadService(t, nil)
	if res, err := s.SaveImage(root, pngBytes(t), now); err != nil || res.Denied {
		t.Fatalf("save: err=%v code=%s", err, res.Code)
	}
	body, err := os.ReadFile(filepath.Join(dir, ".cliora", ".gitignore"))
	if err != nil {
		t.Fatalf("gitignore: %v", err)
	}
	if string(body) != "*\n" {
		t.Fatalf("gitignore = %q, want %q", body, "*\n")
	}
	// A user edit must survive the next upload.
	custom := "# mine\n*.png\n"
	if err := os.WriteFile(filepath.Join(dir, ".cliora", ".gitignore"), []byte(custom), 0o600); err != nil {
		t.Fatal(err)
	}
	if res, err := s.SaveImage(root, pngBytes(t), now); err != nil || res.Denied {
		t.Fatalf("second save: err=%v code=%s", err, res.Code)
	}
	body, _ = os.ReadFile(filepath.Join(dir, ".cliora", ".gitignore"))
	if string(body) != custom {
		t.Fatalf("gitignore was overwritten: %q", body)
	}
}

// os.Root follows symlinks that stay inside the root, so a .cliora symlink
// could otherwise redirect every write somewhere else in the workspace.
func TestSaveImageRefusesHijackedClioraPath(t *testing.T) {
	t.Run("regular file", func(t *testing.T) {
		root, dir := uploadRoot(t)
		if err := os.WriteFile(filepath.Join(dir, ".cliora"), []byte("not a dir"), 0o600); err != nil {
			t.Fatal(err)
		}
		s := uploadService(t, nil)
		res, err := s.SaveImage(root, pngBytes(t), now)
		if err != nil {
			t.Fatalf("a hijacked path must be an in-band denial, not an error: %v", err)
		}
		if !res.Denied || res.Code != "FILE_UPLOAD_FAILED" {
			t.Fatalf("denied=%v code=%s, want FILE_UPLOAD_FAILED", res.Denied, res.Code)
		}
	})

	t.Run("symlink to elsewhere in the workspace", func(t *testing.T) {
		root, dir := uploadRoot(t)
		if err := os.Mkdir(filepath.Join(dir, "victim"), 0o700); err != nil {
			t.Fatal(err)
		}
		if err := os.Symlink("victim", filepath.Join(dir, ".cliora")); err != nil {
			t.Fatal(err)
		}
		s := uploadService(t, nil)
		res, err := s.SaveImage(root, pngBytes(t), now)
		if err == nil && !res.Denied {
			t.Fatal("a symlinked .cliora must not be written through")
		}
		entries, _ := os.ReadDir(filepath.Join(dir, "victim"))
		if len(entries) != 0 {
			t.Fatalf("wrote through the symlink into victim/: %d entries", len(entries))
		}
	})
}

// An escaping symlink must be refused by os.Root itself (ADR 0024 W1).
func TestUploadWriteMethodsStayInsideRoot(t *testing.T) {
	root, dir := uploadRoot(t)
	outside := t.TempDir()
	if err := os.Symlink(outside, filepath.Join(dir, "escape")); err != nil {
		t.Fatal(err)
	}
	if err := root.MkdirAllIn("escape/evil", 0o700); err == nil {
		t.Error("MkdirAllIn followed a symlink out of the root")
	}
	if _, err := root.CreateExclusive("escape/evil.txt", 0o600); err == nil {
		t.Error("CreateExclusive followed a symlink out of the root")
	}
	for _, rel := range []string{"../escape.txt", "/etc/passwd", "a/../../b"} {
		if _, err := root.CreateExclusive(rel, 0o600); err == nil {
			t.Errorf("CreateExclusive(%q) should be refused", rel)
		}
	}
	if entries, _ := os.ReadDir(outside); len(entries) != 0 {
		t.Fatalf("wrote outside the workspace: %d entries", len(entries))
	}
}

// O_EXCL: the daemon owns every name it writes, so a collision means something
// else is in the directory, not "pick another name".
func TestCreateExclusiveRefusesExistingFile(t *testing.T) {
	root, dir := uploadRoot(t)
	if err := os.WriteFile(filepath.Join(dir, "taken.txt"), []byte("x"), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := root.CreateExclusive("taken.txt", 0o600); err == nil {
		t.Fatal("CreateExclusive overwrote an existing file")
	}
}

func TestSaveImageLeavesNoTempFile(t *testing.T) {
	root, dir := uploadRoot(t)
	s := uploadService(t, nil)
	if res, err := s.SaveImage(root, pngBytes(t), now); err != nil || res.Denied {
		t.Fatalf("save: err=%v code=%s", err, res.Code)
	}
	_ = filepath.WalkDir(dir, func(p string, d fs.DirEntry, err error) error {
		if err == nil && !d.IsDir() && strings.HasSuffix(p, ".part") {
			t.Errorf("temp file survived: %s", p)
		}
		return nil
	})
}

func TestSaveImagePermissions(t *testing.T) {
	root, dir := uploadRoot(t)
	s := uploadService(t, nil)
	res, err := s.SaveImage(root, pngBytes(t), now)
	if err != nil || res.Denied {
		t.Fatalf("save: err=%v code=%s", err, res.Code)
	}
	info, err := os.Stat(filepath.Join(dir, res.RelPath))
	if err != nil {
		t.Fatal(err)
	}
	if perm := info.Mode().Perm(); perm != 0o600 {
		t.Errorf("file mode = %o, want 600 so other users on the node cannot read it", perm)
	}
	dirInfo, err := os.Stat(filepath.Join(dir, ".cliora", "uploads", "2026-08-05"))
	if err != nil {
		t.Fatal(err)
	}
	if perm := dirInfo.Mode().Perm(); perm != 0o700 {
		t.Errorf("directory mode = %o, want 700", perm)
	}
}

func TestPruneUploads(t *testing.T) {
	root, dir := uploadRoot(t)
	s := uploadService(t, func(u *config.UploadConfig) { u.RetentionDays = 7 })

	// One fresh, one just inside retention, one just outside.
	var fresh, edge, stale string
	for name, at := range map[string]time.Time{
		"fresh": now,
		"edge":  now.AddDate(0, 0, -7).Add(time.Hour),
		"stale": now.AddDate(0, 0, -7).Add(-time.Minute),
	} {
		res, err := s.SaveImage(root, pngBytes(t), at)
		if err != nil || res.Denied {
			t.Fatalf("%s: err=%v code=%s", name, err, res.Code)
		}
		full := filepath.Join(dir, res.RelPath)
		if err := os.Chtimes(full, at, at); err != nil {
			t.Fatal(err)
		}
		switch name {
		case "fresh":
			fresh = full
		case "edge":
			edge = full
		case "stale":
			stale = full
		}
	}

	removed, freed := s.PruneUploads(root, now)
	if removed != 1 || freed == 0 {
		t.Fatalf("removed=%d freed=%d, want exactly the one stale file", removed, freed)
	}
	if _, err := os.Stat(stale); !os.IsNotExist(err) {
		t.Error("stale file survived pruning")
	}
	for _, keep := range []string{fresh, edge} {
		if _, err := os.Stat(keep); err != nil {
			t.Errorf("pruning removed a file inside retention: %s", keep)
		}
	}
	if _, err := os.Stat(filepath.Join(dir, ".cliora", ".gitignore")); err != nil {
		t.Error(".gitignore must survive pruning")
	}
	// `edge` and `stale` are minutes either side of the cutoff, so they share a
	// UTC day directory; that directory must stay because `edge` is still in it.
	if _, err := os.Stat(filepath.Dir(stale)); err != nil {
		t.Error("a day directory with a surviving file must not be removed")
	}
}

// A day directory left empty by pruning is removed, so the upload tree does not
// accumulate one directory per day forever.
func TestPruneUploadsRemovesEmptiedDayDirectory(t *testing.T) {
	root, dir := uploadRoot(t)
	s := uploadService(t, func(u *config.UploadConfig) { u.RetentionDays = 7 })
	old := now.AddDate(0, 0, -30)
	res, err := s.SaveImage(root, pngBytes(t), old)
	if err != nil || res.Denied {
		t.Fatalf("save: err=%v code=%s", err, res.Code)
	}
	full := filepath.Join(dir, res.RelPath)
	if err := os.Chtimes(full, old, old); err != nil {
		t.Fatal(err)
	}
	if removed, _ := s.PruneUploads(root, now); removed != 1 {
		t.Fatalf("removed=%d, want 1", removed)
	}
	if _, err := os.Stat(filepath.Dir(full)); !os.IsNotExist(err) {
		t.Error("emptied day directory should be removed")
	}
	if _, err := os.Stat(filepath.Join(dir, ".cliora", "uploads")); err != nil {
		t.Error("the uploads root itself must survive")
	}
}

func TestPruneUploadsOnEmptyWorkspace(t *testing.T) {
	root, _ := uploadRoot(t)
	s := uploadService(t, nil)
	if removed, freed := s.PruneUploads(root, now); removed != 0 || freed != 0 {
		t.Fatalf("removed=%d freed=%d on a workspace with no uploads", removed, freed)
	}
}
