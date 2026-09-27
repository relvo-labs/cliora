package workspace

import (
	"errors"
	"os"
	"path/filepath"
	"syscall"
	"testing"
	"time"
)

// TestOpenFileNonBlockingOnFifoReturns is the proof ADR 0029 §3 step 4 depends on:
// os.Root.OpenFile passes O_NONBLOCK through to openat, so a FIFO with no writer
// does not hold the caller in open(2). If this fails on a build target, binary
// preview must not be offered there (fail closed; plan/31/03 §1).
func TestOpenFileNonBlockingOnFifoReturns(t *testing.T) {
	allowed, ws, _ := buildWorkspace(t)
	fifo := filepath.Join(ws, "pipe.png")
	if err := syscall.Mkfifo(fifo, 0o600); err != nil {
		t.Skipf("mkfifo unavailable: %v", err)
	}
	root, err := New([]string{allowed}).OpenWorkspace(ws)
	if err != nil {
		t.Fatal(err)
	}
	defer root.Close()

	done := make(chan error, 1)
	var opened *os.File
	go func() {
		f, err := root.OpenFileNonBlocking("pipe.png")
		opened = f
		done <- err
	}()
	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("non-blocking open of a writerless FIFO failed: %v", err)
		}
		defer opened.Close()
		info, err := opened.Stat()
		if err != nil {
			t.Fatal(err)
		}
		if info.Mode().IsRegular() || info.Mode()&os.ModeNamedPipe == 0 {
			t.Fatalf("expected the FIFO itself, got mode %v", info.Mode())
		}
	case <-time.After(100 * time.Millisecond):
		// Release the blocked open so the goroutine does not outlive the test.
		w, _ := os.OpenFile(fifo, os.O_WRONLY|syscall.O_NONBLOCK, 0)
		if w != nil {
			_ = w.Close()
		}
		<-done
		t.Fatal("OpenFileNonBlocking blocked on a FIFO: O_NONBLOCK did not reach openat")
	}
}

// Confinement is identical to OpenFile: .. and escaping symlinks are refused,
// in-root symlinks are followed (so RealRel must be re-checked by the caller).
func TestOpenFileNonBlockingConfinement(t *testing.T) {
	allowed, ws, outside := buildWorkspace(t)
	root, err := New([]string{allowed}).OpenWorkspace(ws)
	if err != nil {
		t.Fatal(err)
	}
	defer root.Close()

	if f, err := root.OpenFileNonBlocking("main.go"); err != nil {
		t.Fatalf("regular file: %v", err)
	} else {
		buf := make([]byte, 64)
		n, rerr := f.Read(buf)
		_ = f.Close()
		if rerr != nil || string(buf[:n]) != "package main\n" {
			t.Fatalf("read from a non-blocking regular fd: %q %v", buf[:n], rerr)
		}
	}
	if _, err := root.OpenFileNonBlocking("../secrets/token"); !errors.Is(err, ErrOutside) {
		t.Fatalf("parent escape: got %v, want ErrOutside", err)
	}
	if err := os.Symlink(filepath.Join(outside, "token"), filepath.Join(ws, "out.png")); err != nil {
		t.Fatal(err)
	}
	if _, err := root.OpenFileNonBlocking("out.png"); !errors.Is(err, ErrOutside) {
		t.Fatalf("escaping symlink: got %v, want ErrOutside", err)
	}
	if err := os.Symlink("main.go", filepath.Join(ws, "in.png")); err != nil {
		t.Fatal(err)
	}
	f, err := root.OpenFileNonBlocking("in.png")
	if err != nil {
		t.Fatalf("in-root symlink must be followed: %v", err)
	}
	defer f.Close()
	real, err := root.RealRel(f)
	if err != nil || real != "main.go" {
		t.Fatalf("RealRel = %q, %v; want main.go", real, err)
	}
	if _, err := root.OpenFileNonBlocking("missing.png"); !errors.Is(err, ErrNotFound) {
		t.Fatalf("missing: got %v", err)
	}
}
