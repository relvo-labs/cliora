package files

import (
	"os"
	"path/filepath"
	"syscall"
	"testing"
	"time"

	"github.com/cliora/cliora/daemon/internal/config"
)

// Issue #83 (plan/31/09 §4 E1): Read and Download must never wait in open(2) on
// a FIFO, whether it is named directly, reached through an in-root symlink, or
// swapped in after the pre-open type check.

// within runs fn and fails if it has not returned in d. A blocked fn is
// released by writing-end opens on fifos so the goroutine does not outlive the
// test.
func within(t *testing.T, d time.Duration, fifos []string, fn func()) {
	t.Helper()
	done := make(chan struct{})
	go func() { defer close(done); fn() }()
	select {
	case <-done:
	case <-time.After(d):
		until := time.Now().Add(2 * time.Second)
		for time.Now().Before(until) {
			for _, p := range fifos {
				if w, err := os.OpenFile(p, os.O_WRONLY|syscall.O_NONBLOCK, 0); err == nil {
					_ = w.Close()
				}
			}
			select {
			case <-done:
				t.Fatalf("blocked for more than %v (released by a writer)", d)
			case <-time.After(20 * time.Millisecond):
			}
		}
		t.Fatalf("blocked for more than %v and could not be released", d)
	}
}

func mkfifo(t *testing.T, path string) {
	t.Helper()
	if err := syscall.Mkfifo(path, 0o600); err != nil {
		t.Skipf("mkfifo: %v", err)
	}
}

func fifoService(t *testing.T) *Service {
	cfg := defaultCfg()
	cfg.Filesystem.Download.MaxBytes = config.DefaultDownloadMaxBytes
	return NewService(cfg, func() time.Time { return time.Unix(0, 0).UTC() })
}

func TestReadFifoIsDeniedWithoutBlocking(t *testing.T) {
	allowed, ws := buildTree(t)
	fifo := filepath.Join(ws, "pipe.txt")
	mkfifo(t, fifo)
	if err := os.Symlink("pipe.txt", filepath.Join(ws, "link.txt")); err != nil {
		t.Fatal(err)
	}
	root := openWS(t, allowed, ws)
	s := fifoService(t)
	for _, rel := range []string{"pipe.txt", "link.txt"} {
		var res ReadResult
		var err error
		within(t, 500*time.Millisecond, []string{fifo}, func() { res, err = s.Read(root, rel) })
		if err != nil || !res.Denied || res.Code != "FILE_DENIED" || res.Reason != "not_regular" || res.Content != "" {
			t.Fatalf("%s: %+v %v", rel, res, err)
		}
	}
}

func TestDownloadFifoIsDeniedWithoutBlocking(t *testing.T) {
	allowed, ws := buildTree(t)
	fifo := filepath.Join(ws, "pipe.bin")
	mkfifo(t, fifo)
	if err := os.Symlink("pipe.bin", filepath.Join(ws, "link.bin")); err != nil {
		t.Fatal(err)
	}
	root := openWS(t, allowed, ws)
	s := fifoService(t)
	for _, rel := range []string{"pipe.bin", "link.bin"} {
		var res DownloadResult
		var err error
		within(t, 500*time.Millisecond, []string{fifo}, func() { res, err = s.Download(root, rel) })
		if code, reason := DownloadCode(err); code != "FILE_DENIED" || reason != "not_regular" || res.Content != nil {
			t.Fatalf("%s: %+v %v", rel, res, err)
		}
	}
}

// The pre-open StatIn is advisory. A FIFO renamed over a regular file after it
// is the case only the non-blocking open and the fd's fstat catch.
func TestFifoSwappedInAfterPreStatIsDeniedWithoutBlocking(t *testing.T) {
	allowed, ws := buildTree(t)
	staged := filepath.Join(ws, "staged.fifo")
	mkfifo(t, staged)
	target := filepath.Join(ws, "notes.txt")
	root := openWS(t, allowed, ws)
	s := fifoService(t)
	swap := func() {
		if err := os.Rename(staged, target); err != nil {
			t.Errorf("swap: %v", err)
		}
	}
	reset := func() {
		_ = os.Remove(target)
		if err := os.WriteFile(target, []byte("hello\n"), 0o644); err != nil {
			t.Fatal(err)
		}
		_ = os.Remove(staged)
		mkfifo(t, staged)
	}

	reset()
	s.afterPreStat = swap
	var res ReadResult
	var err error
	within(t, 500*time.Millisecond, []string{target}, func() { res, err = s.Read(root, "notes.txt") })
	if err != nil || res.Code != "FILE_DENIED" || res.Reason != "not_regular" {
		t.Fatalf("read after swap: %+v %v", res, err)
	}

	reset()
	var dl DownloadResult
	within(t, 500*time.Millisecond, []string{target}, func() { dl, err = s.Download(root, "notes.txt") })
	if code, reason := DownloadCode(err); code != "FILE_DENIED" || reason != "not_regular" || dl.Content != nil {
		t.Fatalf("download after swap: %+v %v", dl, err)
	}
}

// Regular files read exactly as before through the non-blocking descriptor:
// same bytes, size, mtime, and the same denials around them.
func TestReadAndDownloadRegularFileUnchanged(t *testing.T) {
	allowed, ws := buildTree(t)
	root := openWS(t, allowed, ws)
	s := fifoService(t)

	res, err := s.Read(root, "main.go")
	if err != nil || res.Denied || res.Content != "package main\n" || res.Size != int64(len("package main\n")) ||
		res.Encoding != "utf-8" || res.Language != "go" {
		t.Fatalf("read: %+v %v", res, err)
	}
	info, _ := os.Stat(filepath.Join(ws, "main.go"))
	if !res.ModifiedAt.Equal(info.ModTime().UTC()) {
		t.Fatalf("mtime: %v vs %v", res.ModifiedAt, info.ModTime())
	}
	dl, err := s.Download(root, "bin.dat")
	if err != nil || string(dl.Content) != "\x00\x01\x02binary\x00" {
		t.Fatalf("download: %+v %v", dl, err)
	}

	cases := []struct{ rel, code, reason string }{
		{".env", "FILE_DENIED", "dotenv"},
		{"src", "FILE_DENIED", "not_regular"},
		{"missing.txt", "FILE_NOT_FOUND", "not_found"},
		{"../../secrets", "FILE_DENIED", "outside_root"},
		{"bin.dat", "FILE_BINARY", "binary"},
	}
	for _, c := range cases {
		r, err := s.Read(root, c.rel)
		if err != nil || !r.Denied || r.Code != c.code || (r.Reason != c.reason && c.code != "FILE_BINARY") {
			t.Fatalf("read %s: %+v %v, want %s/%s", c.rel, r, err, c.code, c.reason)
		}
	}
}
