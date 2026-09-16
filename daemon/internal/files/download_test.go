package files

import (
	"bytes"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/cliora/cliora/daemon/internal/config"
	"github.com/cliora/cliora/daemon/internal/protocol"
	"github.com/cliora/cliora/daemon/internal/workspace"
)

// Workspace file download (ADR 0028, FR-FILE-011).
//
// The tests are organised around the one sentence the design rests on:
//
//	the platform does not hand over a file it would refuse to show you,
//	but it will hand over one it merely cannot render.
//
// So there are two load-bearing groups, and they pull in opposite directions.
// TestDownloadRefusesSensitive* asserts the first clause and would catch a
// version of Download that reached for the bytes before consulting the policy;
// TestDownloadAllows* asserts the second and would catch someone "fixing" this
// path by copying Read's binary classification into it — which would silently
// restore exactly the refusals the feature exists to remove.

func downloadService(t *testing.T, mutate func(*config.Config)) *Service {
	t.Helper()
	cfg := &config.Config{}
	cfg.Filesystem.MaxPreviewSize = 2 * 1024 * 1024
	cfg.Filesystem.Download.MaxBytes = 4 * 1024 * 1024
	cfg.Workspace.ExcludedDirectories = []string{".git", "node_modules", "dist"}
	cfg.Filesystem.DeniedPatterns = []string{
		".env", ".env.*", "*.pem", "*.key", "id_rsa", "*credentials*",
	}
	cfg.Filesystem.DeniedDirectories = []string{".ssh", ".aws", ".gnupg"}
	if mutate != nil {
		mutate(cfg)
	}
	return NewService(cfg, func() time.Time { return downloadNow })
}

var downloadNow = time.Date(2026, 9, 16, 12, 0, 0, 0, time.UTC)

func downloadRoot(t *testing.T) (*workspace.Root, string) {
	t.Helper()
	dir := t.TempDir()
	root, err := workspace.New([]string{dir}).OpenWorkspace(dir)
	if err != nil {
		t.Fatalf("open workspace: %v", err)
	}
	t.Cleanup(func() { _ = root.Close() })
	return root, dir
}

func writeFile(t *testing.T, dir, rel string, data []byte) {
	t.Helper()
	full := filepath.Join(dir, rel)
	if err := os.MkdirAll(filepath.Dir(full), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(full, data, 0o644); err != nil {
		t.Fatal(err)
	}
}

// requireDenied asserts a refusal and returns its coarse reason, failing loudly
// if the call succeeded — a download that wrongly succeeds is the failure mode
// worth the noisiest assertion in this file.
func requireDenied(t *testing.T, res DownloadResult, err error, wantCode string) string {
	t.Helper()
	if err == nil {
		t.Fatalf("expected %s, got %d bytes", wantCode, len(res.Content))
	}
	code, reason := DownloadCode(err)
	if code != wantCode {
		t.Fatalf("code = %q (reason %q), want %q", code, reason, wantCode)
	}
	return reason
}

func TestDownloadReturnsExactBytes(t *testing.T) {
	svc := downloadService(t, nil)
	root, dir := downloadRoot(t)
	content := []byte("a,b\n1,2\n")
	writeFile(t, dir, "datasets/data.csv", content)

	res, err := svc.Download(root, "datasets/data.csv")
	if err != nil {
		t.Fatalf("download: %v", err)
	}
	if !bytes.Equal(res.Content, content) {
		t.Fatalf("content = %q, want %q", res.Content, content)
	}
	if res.Size != int64(len(content)) {
		t.Fatalf("size = %d, want %d", res.Size, len(content))
	}
	if res.RelPath != "datasets/data.csv" {
		t.Fatalf("rel path = %q", res.RelPath)
	}
}

// The whole point of the path. A PNG is denied by Read and must be allowed here;
// if this test starts failing, someone has re-introduced the binary check.
func TestDownloadAllowsBinaryContent(t *testing.T) {
	svc := downloadService(t, nil)
	root, dir := downloadRoot(t)
	png := []byte{0x89, 'P', 'N', 'G', 0x0D, 0x0A, 0x1A, 0x0A, 0x00, 0x01, 0x02}
	writeFile(t, dir, "assets/logo.png", png)

	// Establish the contrast rather than asserting it in isolation: the value of
	// this test is that the SAME file goes two ways through the two functions.
	if read, err := svc.Read(root, "assets/logo.png"); err != nil || !read.Denied {
		t.Fatalf("Read should deny a PNG (denied=%v err=%v)", read.Denied, err)
	}
	res, err := svc.Download(root, "assets/logo.png")
	if err != nil {
		t.Fatalf("download: %v", err)
	}
	if !bytes.Equal(res.Content, png) {
		t.Fatalf("content = %v, want %v", res.Content, png)
	}
}

// A NUL byte anywhere makes a file unpreviewable (FR-FILE-008.AC-03). It must
// still be downloadable: "contains a NUL" is a statement about rendering.
func TestDownloadAllowsContentWithNulBytes(t *testing.T) {
	svc := downloadService(t, nil)
	root, dir := downloadRoot(t)
	data := append([]byte("header\n"), append([]byte{0x00}, []byte("tail")...)...)
	writeFile(t, dir, "blob.bin", data)

	res, err := svc.Download(root, "blob.bin")
	if err != nil {
		t.Fatalf("download: %v", err)
	}
	if !bytes.Equal(res.Content, data) {
		t.Fatalf("content mismatch")
	}
}

func TestDownloadAllowsEmptyFile(t *testing.T) {
	svc := downloadService(t, nil)
	root, dir := downloadRoot(t)
	writeFile(t, dir, "src/__init__.py", nil)

	res, err := svc.Download(root, "src/__init__.py")
	if err != nil {
		t.Fatalf("download: %v", err)
	}
	if res.Size != 0 || len(res.Content) != 0 {
		t.Fatalf("size = %d, len = %d, want 0/0", res.Size, len(res.Content))
	}
}

// A file between the two ceilings: too large to preview (2 MiB), small enough to
// download (4 MiB). The band between them is real and the UI promises it exists.
func TestDownloadAllowsFileOverThePreviewCap(t *testing.T) {
	svc := downloadService(t, nil)
	root, dir := downloadRoot(t)
	data := bytes.Repeat([]byte("x"), 3*1024*1024)
	writeFile(t, dir, "big.txt", data)

	if read, err := svc.Read(root, "big.txt"); err != nil || read.Code != "FILE_TOO_LARGE" {
		t.Fatalf("Read should refuse over the preview cap (code=%q err=%v)", read.Code, err)
	}
	res, err := svc.Download(root, "big.txt")
	if err != nil {
		t.Fatalf("download: %v", err)
	}
	if res.Size != int64(len(data)) {
		t.Fatalf("size = %d, want %d", res.Size, len(data))
	}
}

func TestDownloadRefusesOverTheDownloadCap(t *testing.T) {
	svc := downloadService(t, func(c *config.Config) {
		c.Filesystem.Download.MaxBytes = 1024
	})
	root, dir := downloadRoot(t)
	writeFile(t, dir, "big.bin", bytes.Repeat([]byte("x"), 4096))

	res, err := svc.Download(root, "big.bin")
	requireDenied(t, res, err, "FILE_TOO_LARGE")
}

// The security half of the design sentence. Every one of these is refused by the
// preview path too, and by the same function — the table is here so that relaxing
// any single pattern for downloads has to be done deliberately.
func TestDownloadRefusesSensitiveNames(t *testing.T) {
	svc := downloadService(t, nil)
	root, dir := downloadRoot(t)
	for _, rel := range []string{
		".env",
		".env.production",
		"deploy/server.pem",
		"keys/id_rsa",
		"certs/tls.key",
		"config/credentials.json",
		".ssh/config",
	} {
		writeFile(t, dir, rel, []byte("SECRET"))
		res, err := svc.Download(root, rel)
		reason := requireDenied(t, res, err, "FILE_DENIED")
		if reason == "" {
			t.Errorf("%s: denied with no classification", rel)
		}
		if len(res.Content) != 0 {
			t.Errorf("%s: refused but returned %d bytes", rel, len(res.Content))
		}
	}
}

// The bypass the second policy check exists for: an innocuous name inside the
// workspace pointing at a sensitive file also inside the workspace. Checking only
// the requested path would serve it.
func TestDownloadRefusesSymlinkToSensitiveInRoot(t *testing.T) {
	svc := downloadService(t, nil)
	root, dir := downloadRoot(t)
	writeFile(t, dir, ".env", []byte("TOKEN=1"))
	if err := os.Symlink(filepath.Join(dir, ".env"), filepath.Join(dir, "notes.txt")); err != nil {
		t.Skipf("symlink unsupported: %v", err)
	}
	res, err := svc.Download(root, "notes.txt")
	if err == nil {
		t.Fatalf("symlink to .env was downloadable: %q", res.Content)
	}
	if code, _ := DownloadCode(err); code != "FILE_DENIED" {
		t.Fatalf("code = %q, want FILE_DENIED", code)
	}
}

func TestDownloadRefusesEscapingPath(t *testing.T) {
	svc := downloadService(t, nil)
	root, _ := downloadRoot(t)
	res, err := svc.Download(root, "../../etc/passwd")
	if err == nil {
		t.Fatalf("escaped the workspace: %q", res.Content)
	}
	// Outside-root collapses to FILE_DENIED so the caller cannot probe for the
	// existence of paths outside the workspace (ADR 0014).
	if code, _ := DownloadCode(err); code != "FILE_DENIED" && code != "FILE_NOT_FOUND" {
		t.Fatalf("code = %q, want a non-probing refusal", code)
	}
}

func TestDownloadRefusesDirectory(t *testing.T) {
	svc := downloadService(t, nil)
	root, dir := downloadRoot(t)
	if err := os.Mkdir(filepath.Join(dir, "datasets"), 0o755); err != nil {
		t.Fatal(err)
	}
	res, err := svc.Download(root, "datasets")
	if reason := requireDenied(t, res, err, "FILE_DENIED"); reason != "not_regular" {
		t.Fatalf("reason = %q, want not_regular", reason)
	}
}

func TestDownloadRefusedWhenNodeDisablesIt(t *testing.T) {
	off := false
	svc := downloadService(t, func(c *config.Config) { c.Filesystem.Download.Enabled = &off })
	root, dir := downloadRoot(t)
	writeFile(t, dir, "data.csv", []byte("a,b\n"))

	res, err := svc.Download(root, "data.csv")
	requireDenied(t, res, err, "FILE_DOWNLOAD_DISABLED")
	if !svc.DownloadEnabled() == false {
		t.Fatalf("DownloadEnabled should report false")
	}
}

// Absent means on, which is the trade ADR 0028 §6 makes explicitly: an upgrade
// acquires the behaviour, and that is what the release note and runbook are for.
func TestDownloadDefaultsToEnabledWhenUnset(t *testing.T) {
	svc := downloadService(t, nil)
	if !svc.DownloadEnabled() {
		t.Fatalf("an unset switch must read as enabled")
	}
}

// The ceiling is a frame-budget fact, not taste. Raising the config default
// without raising the frame bound would not fail loudly — the node would refuse
// to build the frame and the request would surface as a timeout — so the
// arithmetic is asserted here, the same guard TestUploadCapFitsFrameBound gives
// the write direction.
func TestDownloadCapFitsFrameBound(t *testing.T) {
	base64Len := (config.DefaultDownloadMaxBytes + 2) / 3 * 4
	if base64Len > protocol.MaxUploadBase64 {
		t.Fatalf("%d bytes is %d of base64, over the schema cap %d",
			config.DefaultDownloadMaxBytes, base64Len, protocol.MaxUploadBase64)
	}
	if int64(protocol.MaxUploadBase64) > int64(protocol.MaxFilePayload) {
		t.Fatalf("schema cap %d exceeds the frame bound %d",
			protocol.MaxUploadBase64, protocol.MaxFilePayload)
	}
	if config.DefaultDownloadMaxBytes != protocol.MaxDownloadBytes {
		t.Fatalf("config default %d and wire bound %d have drifted apart",
			config.DefaultDownloadMaxBytes, protocol.MaxDownloadBytes)
	}
}
