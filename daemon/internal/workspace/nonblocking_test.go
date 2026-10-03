package workspace

import (
	"errors"
	"io/fs"
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

// openWithin fails the test if open has not returned within 200 ms, releasing a
// blocked open with a writer so the goroutine does not outlive the test.
func openWithin(t *testing.T, fifo string, open func() error) error {
	t.Helper()
	done := make(chan error, 1)
	go func() { done <- open() }()
	select {
	case err := <-done:
		return err
	case <-time.After(200 * time.Millisecond):
		for i := 0; i < 100; i++ {
			if w, _ := os.OpenFile(fifo, os.O_WRONLY|syscall.O_NONBLOCK, 0); w != nil {
				_ = w.Close()
			}
			select {
			case <-done:
				t.Fatal("open blocked on a FIFO (released by a writer)")
			case <-time.After(20 * time.Millisecond):
			}
		}
		t.Fatal("open blocked on a FIFO and could not be released")
		return nil
	}
}

// filesystem.list names a directory; a FIFO in its place must be refused as not
// a directory without waiting for a writer (issue #83).
func TestOpenDirOnFifoReturnsNotDir(t *testing.T) {
	allowed, ws, _ := buildWorkspace(t)
	fifo := filepath.Join(ws, "pipe")
	if err := syscall.Mkfifo(fifo, 0o600); err != nil {
		t.Skipf("mkfifo unavailable: %v", err)
	}
	root, err := New([]string{allowed}).OpenWorkspace(ws)
	if err != nil {
		t.Fatal(err)
	}
	defer root.Close()
	err = openWithin(t, fifo, func() error {
		f, err := root.OpenDir("pipe")
		if f != nil {
			_ = f.Close()
		}
		return err
	})
	if !errors.Is(err, ErrNotDir) {
		t.Fatalf("OpenDir on a FIFO: got %v, want ErrNotDir", err)
	}
	if f, err := root.OpenDir("sub"); err != nil {
		t.Fatalf("a real directory: %v", err)
	} else {
		_ = f.Close()
	}
}

// Search and upload pruning walk Root.FS(). WalkDir only reads entries the
// kernel reported as directories, but one swapped for a FIFO between getdents and
// the open would otherwise park the walk in open(2).
func TestFSOpenOnFifoDoesNotBlock(t *testing.T) {
	allowed, ws, _ := buildWorkspace(t)
	fifo := filepath.Join(ws, "pipe")
	if err := syscall.Mkfifo(fifo, 0o600); err != nil {
		t.Skipf("mkfifo unavailable: %v", err)
	}
	root, err := New([]string{allowed}).OpenWorkspace(ws)
	if err != nil {
		t.Fatal(err)
	}
	defer root.Close()
	fsys := root.FS()
	_ = openWithin(t, fifo, func() error {
		_, err := fs.ReadDir(fsys, "pipe")
		return err
	})
	_ = openWithin(t, fifo, func() error {
		f, err := fsys.Open("pipe")
		if f != nil {
			_ = f.Close()
		}
		return err
	})
	// Regular behaviour is unchanged: sorted entries, readable files, confinement.
	entries, err := fs.ReadDir(fsys, ".")
	if err != nil || len(entries) != 3 || entries[0].Name() != "main.go" || entries[1].Name() != "pipe" || entries[2].Name() != "sub" {
		t.Fatalf("ReadDir: %v %v", entries, err)
	}
	if b, err := fs.ReadFile(fsys, "main.go"); err != nil || string(b) != "package main\n" {
		t.Fatalf("ReadFile: %q %v", b, err)
	}
	if _, err := fsys.Open("../secrets/token"); err == nil {
		t.Fatal("FS escaped the root")
	}
	if info, err := fs.Stat(fsys, "sub"); err != nil || !info.IsDir() {
		t.Fatalf("Stat: %v %v", info, err)
	}
}
