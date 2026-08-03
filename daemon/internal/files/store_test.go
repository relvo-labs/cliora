package files

import (
	"crypto/sha256"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/cliora/cliora/daemon/internal/config"
	"github.com/cliora/cliora/daemon/internal/workspace"
)

// General file upload (ADR 0026). The tests are organised around the one
// property that lets this path be as small as it is: it never replaces an
// existing byte. TestStoreNeverOverwrites is therefore the load-bearing one —
// asserting the error code alone would not catch a version of Store that
// returned FILE_EXISTS *after* clobbering the file.

func storeService(t *testing.T, mutate func(*config.Config)) *Service {
	t.Helper()
	cfg := &config.Config{}
	cfg.Filesystem.MaxPreviewSize = 2 * 1024 * 1024
	cfg.Filesystem.Upload.MaxBytes = 4 * 1024 * 1024
	cfg.Filesystem.Upload.Files.MaxSessionBytes = 256 * 1024 * 1024
	cfg.Filesystem.Upload.Files.MaxFilesPerDay = 200
	cfg.Workspace.ExcludedDirectories = []string{".git", "node_modules", "dist"}
	cfg.Filesystem.DeniedPatterns = []string{".env", ".env.*", "*.pem", "*.key", "id_rsa", "*credentials*"}
	cfg.Filesystem.DeniedDirectories = []string{".ssh", ".aws", ".gnupg"}
	if mutate != nil {
		mutate(cfg)
	}
	svc := NewService(cfg, func() time.Time { return storeNow })
	// Default to plenty of room; the free-space tests override this seam rather
	// than filling a disk.
	svc.freeBytes = func(string) (int64, error) { return 100 << 30, nil }
	return svc
}

var storeNow = time.Date(2026, 8, 3, 12, 0, 0, 0, time.UTC)

func storeRoot(t *testing.T) (*workspace.Root, string) {
	t.Helper()
	dir := t.TempDir()
	root, err := workspace.New([]string{dir}).OpenWorkspace(dir)
	if err != nil {
		t.Fatalf("open workspace: %v", err)
	}
	t.Cleanup(func() { _ = root.Close() })
	return root, dir
}

func TestStoreWritesFileWithFixedMode(t *testing.T) {
	svc := storeService(t, nil)
	root, dir := storeRoot(t)
	if err := os.Mkdir(filepath.Join(dir, "datasets"), 0o755); err != nil {
		t.Fatal(err)
	}

	res, err := svc.Store(root, "datasets", "data.csv", []byte("a,b\n1,2\n"), storeNow)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if res.Denied {
		t.Fatalf("denied: %s/%s", res.Code, res.Reason)
	}
	if res.RelPath != "datasets/data.csv" {
		t.Fatalf("rel path = %q", res.RelPath)
	}
	info, err := os.Lstat(filepath.Join(dir, "datasets", "data.csv"))
	if err != nil {
		t.Fatalf("stat: %v", err)
	}
	// 0644 whatever the source was: a file dragged in from a browser must not
	// arrive executable (ADR 0026 §1.3).
	if got := info.Mode().Perm(); got != 0o644 {
		t.Fatalf("mode = %o, want 644", got)
	}
	if info.Size() != 8 {
		t.Fatalf("size = %d", info.Size())
	}
	// Exactly one entry, and it is the file: there is no temp file in this design
	// (see Store step 8 — a temp plus rename would replace an existing target).
	entries, _ := os.ReadDir(filepath.Join(dir, "datasets"))
	if len(entries) != 1 || entries[0].Name() != "data.csv" {
		t.Fatalf("unexpected directory contents: %v", entries)
	}
}

func TestStoreWorkspaceRootIsAValidDestination(t *testing.T) {
	svc := storeService(t, nil)
	root, dir := storeRoot(t)
	for _, d := range []string{"", "."} {
		res, err := svc.Store(root, d, "notes-"+d+".txt", []byte("x"), storeNow)
		if err != nil {
			t.Fatalf("dir %q: %v", d, err)
		}
		if res.Denied {
			t.Fatalf("dir %q denied: %s/%s", d, res.Code, res.Reason)
		}
		if _, err := os.Lstat(filepath.Join(dir, "notes-"+d+".txt")); err != nil {
			t.Fatalf("dir %q: file missing: %v", d, err)
		}
	}
}

func TestStoreEmptyFileIsAllowed(t *testing.T) {
	// An empty file is a legitimate upload (a placeholder, an empty
	// __init__.py). All three wire consumers decode "" to zero bytes cleanly —
	// plan/15/07-open-measurements.md §4 — so nothing above needs to reject it.
	svc := storeService(t, nil)
	root, dir := storeRoot(t)
	res, err := svc.Store(root, ".", "__init__.py", nil, storeNow)
	if err != nil || res.Denied {
		t.Fatalf("err=%v denied=%v %s", err, res.Denied, res.Code)
	}
	info, err := os.Lstat(filepath.Join(dir, "__init__.py"))
	if err != nil {
		t.Fatal(err)
	}
	if info.Size() != 0 {
		t.Fatalf("size = %d, want 0", info.Size())
	}
}

// TestStoreNeverOverwrites is the whole reason this path needs no version
// precondition, no trash can and no undo (ADR 0026 §3). Asserting the code is
// not enough: the existing bytes and mtime must be untouched.
func TestStoreNeverOverwrites(t *testing.T) {
	svc := storeService(t, nil)
	root, dir := storeRoot(t)
	target := filepath.Join(dir, "keep.txt")
	if err := os.WriteFile(target, []byte("ORIGINAL"), 0o600); err != nil {
		t.Fatal(err)
	}
	before, err := os.Lstat(target)
	if err != nil {
		t.Fatal(err)
	}
	beforeSum := sha256.Sum256([]byte("ORIGINAL"))

	res, err := svc.Store(root, ".", "keep.txt", []byte("REPLACEMENT"), storeNow)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !res.Denied || res.Code != "FILE_EXISTS" {
		t.Fatalf("want FILE_EXISTS, got denied=%v code=%s", res.Denied, res.Code)
	}
	if res.Reason != "file_exists" {
		t.Fatalf("reason = %q", res.Reason)
	}
	content, err := os.ReadFile(target)
	if err != nil {
		t.Fatal(err)
	}
	if sha256.Sum256(content) != beforeSum {
		t.Fatalf("content changed: %q", content)
	}
	after, err := os.Lstat(target)
	if err != nil {
		t.Fatal(err)
	}
	if !after.ModTime().Equal(before.ModTime()) {
		t.Fatalf("mtime changed: %v -> %v", before.ModTime(), after.ModTime())
	}
	if after.Mode().Perm() != 0o600 {
		t.Fatalf("mode changed to %o", after.Mode().Perm())
	}
}

func TestStoreRefusesExistingDirectoryName(t *testing.T) {
	svc := storeService(t, nil)
	root, dir := storeRoot(t)
	if err := os.Mkdir(filepath.Join(dir, "docs"), 0o755); err != nil {
		t.Fatal(err)
	}
	res, err := svc.Store(root, ".", "docs", []byte("x"), storeNow)
	if err != nil {
		t.Fatal(err)
	}
	// A different reason from a file collision, because the wording a user needs
	// is different.
	if !res.Denied || res.Code != "FILE_EXISTS" || res.Reason != "directory_exists" {
		t.Fatalf("got denied=%v %s/%s", res.Denied, res.Code, res.Reason)
	}
}

func TestStoreRefusesMissingAndNonDirectoryDestination(t *testing.T) {
	svc := storeService(t, nil)
	root, dir := storeRoot(t)
	if err := os.WriteFile(filepath.Join(dir, "afile"), []byte("x"), 0o644); err != nil {
		t.Fatal(err)
	}

	res, err := svc.Store(root, "nope", "a.txt", []byte("x"), storeNow)
	if err != nil {
		t.Fatal(err)
	}
	if !res.Denied || res.Code != "FILE_NOT_FOUND" {
		t.Fatalf("missing dir: got %v %s", res.Denied, res.Code)
	}

	res, err = svc.Store(root, "afile", "a.txt", []byte("x"), storeNow)
	if err != nil {
		t.Fatal(err)
	}
	if !res.Denied || res.Code != "FILE_DENIED" || res.Reason != "dir_not_directory" {
		t.Fatalf("file as dir: got %v %s/%s", res.Denied, res.Code, res.Reason)
	}
}

// A symlink that stays inside the root is followed by os.Root, so without the
// Lstat in step 6 an in-root `datasets -> elsewhere` would silently redirect
// where uploads land.
func TestStoreRefusesSymlinkDestination(t *testing.T) {
	svc := storeService(t, nil)
	root, dir := storeRoot(t)
	if err := os.Mkdir(filepath.Join(dir, "real"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink("real", filepath.Join(dir, "link")); err != nil {
		t.Fatal(err)
	}
	res, err := svc.Store(root, "link", "a.txt", []byte("x"), storeNow)
	if err != nil {
		t.Fatal(err)
	}
	if !res.Denied || res.Code != "FILE_DENIED" || res.Reason != "dir_symlink" {
		t.Fatalf("got denied=%v %s/%s", res.Denied, res.Code, res.Reason)
	}
	if _, err := os.Lstat(filepath.Join(dir, "real", "a.txt")); err == nil {
		t.Fatal("file landed through the symlink")
	}
}

func TestStoreRefusesEscapingDestination(t *testing.T) {
	svc := storeService(t, nil)
	root, dir := storeRoot(t)
	for _, d := range []string{"..", "../elsewhere", "/etc", "~/x"} {
		res, err := svc.Store(root, d, "a.txt", []byte("x"), storeNow)
		if err != nil {
			t.Fatalf("dir %q: unexpected error %v", d, err)
		}
		if !res.Denied {
			t.Fatalf("dir %q was accepted", d)
		}
	}
	// Nothing was created anywhere under the root.
	entries, _ := os.ReadDir(dir)
	if len(entries) != 0 {
		t.Fatalf("root is not empty: %v", entries)
	}
}

func TestStoreRefusesOversize(t *testing.T) {
	svc := storeService(t, func(c *config.Config) {
		c.Filesystem.Upload.MaxBytes = 16
	})
	root, dir := storeRoot(t)
	res, err := svc.Store(root, ".", "big.bin", make([]byte, 17), storeNow)
	if err != nil {
		t.Fatal(err)
	}
	if !res.Denied || res.Code != "FILE_UPLOAD_TOO_LARGE" {
		t.Fatalf("got %v %s", res.Denied, res.Code)
	}
	if entries, _ := os.ReadDir(dir); len(entries) != 0 {
		t.Fatalf("something was written: %v", entries)
	}
}

func TestStoreRefusesWhenDisabled(t *testing.T) {
	off := false
	svc := storeService(t, func(c *config.Config) {
		c.Filesystem.Upload.Files.Enabled = &off
	})
	root, _ := storeRoot(t)
	res, err := svc.Store(root, ".", "a.txt", []byte("x"), storeNow)
	if err != nil {
		t.Fatal(err)
	}
	if !res.Denied || res.Code != "FILE_UPLOAD_DISABLED" {
		t.Fatalf("got %v %s", res.Denied, res.Code)
	}
	if svc.FileUploadEnabled() {
		t.Fatal("FileUploadEnabled() should report false")
	}
}

// Concurrency: two uploads racing for the same name must produce exactly one
// winner and one FILE_EXISTS, and the file must hold one payload whole. This is
// what the ULID in the temp name is for — a fixed suffix would make the loser
// fail on the *temp* file and surface as an internal error instead of the
// collision it actually is.
func TestStoreConcurrentSameNameHasOneWinner(t *testing.T) {
	svc := storeService(t, nil)
	root, dir := storeRoot(t)
	payloads := [][]byte{[]byte(strings.Repeat("A", 512)), []byte(strings.Repeat("B", 512))}

	var wg sync.WaitGroup
	results := make([]StoreResult, 2)
	errs := make([]error, 2)
	start := make(chan struct{})
	for i := range payloads {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			<-start
			results[i], errs[i] = svc.Store(root, ".", "race.txt", payloads[i], storeNow)
		}(i)
	}
	close(start)
	wg.Wait()

	ok, collided := 0, 0
	for i := range results {
		if errs[i] != nil {
			t.Fatalf("goroutine %d: unexpected error %v", i, errs[i])
		}
		switch {
		case !results[i].Denied:
			ok++
		case results[i].Code == "FILE_EXISTS":
			collided++
		default:
			t.Fatalf("goroutine %d: unexpected refusal %s/%s", i, results[i].Code, results[i].Reason)
		}
	}
	if ok != 1 || collided != 1 {
		t.Fatalf("want 1 success and 1 FILE_EXISTS, got %d/%d", ok, collided)
	}
	content, err := os.ReadFile(filepath.Join(dir, "race.txt"))
	if err != nil {
		t.Fatal(err)
	}
	if string(content) != string(payloads[0]) && string(content) != string(payloads[1]) {
		t.Fatalf("content is interleaved or truncated (%d bytes)", len(content))
	}
	// And the race left exactly one file behind, not a stray from the loser.
	entries, _ := os.ReadDir(dir)
	if len(entries) != 1 || entries[0].Name() != "race.txt" {
		t.Fatalf("unexpected directory contents: %v", entries)
	}
}
