package connection

import (
	"context"
	"encoding/base64"
	"os"
	"path/filepath"
	"sync/atomic"
	"syscall"
	"testing"
	"time"

	"github.com/cliora/cliora/daemon/internal/config"
)

// Issue #83 (plan/31/09 §4 E1): filesystem.read and filesystem.download opened
// the requested path with a blocking open(2) on the dispatch loop, so a FIFO in
// the workspace held the loop until something wrote to it — terminal input,
// every other session's control frames and every other file request with it.
//
// These tests drive the production dispatch over a real WebSocket. On the
// defective code they fail on their deadline rather than hang: the FIFOs are
// released by a cleanup that runs before the harness waits for the daemon.

const fifoDeadline = 2 * time.Second

// newFsFifoHarness is the preview harness with two writerless FIFOs in the
// workspace and the file handlers resolving the harness's session.
func newFsFifoHarness(t *testing.T, body map[string][]byte) *previewHarness {
	t.Helper()
	h := newPreviewHarness(t, body, func(cfg *config.Config) {
		cfg.Filesystem.Download.MaxBytes = config.DefaultDownloadMaxBytes
	})
	h.m.fs.root = h.m.preview.root
	fifos := []string{filepath.Join(h.ws, "fifo-a.txt"), filepath.Join(h.ws, "fifo-b.txt")}
	for _, p := range fifos {
		if err := syscall.Mkfifo(p, 0o600); err != nil {
			t.Skipf("mkfifo: %v", err)
		}
	}
	h.start()
	// Registered after start, so it runs before the harness's own stop-and-wait:
	// on the defective code an open is still parked on a FIFO, and this lets it go.
	t.Cleanup(func() {
		if !t.Failed() {
			return // nothing is parked on a FIFO
		}
		until := time.Now().Add(fifoDeadline)
		for time.Now().Before(until) {
			for _, p := range fifos {
				releaseFifo(p)
			}
			time.Sleep(20 * time.Millisecond)
		}
	})
	return h
}

func TestFsReadTwoFifosDoNotStallDispatch(t *testing.T) {
	const text = "package main\n\nfunc main() {}\n"
	h := newFsFifoHarness(t, map[string][]byte{"ok.go": []byte(text)})
	sid := h.sessionID.String()
	deadline := time.Now().Add(fifoDeadline)

	a := h.send("filesystem.read", map[string]any{"session_id": sid, "path": "fifo-a.txt"})
	b := h.send("filesystem.read", map[string]any{"session_id": sid, "path": "fifo-b.txt"})
	ok := h.send("filesystem.read", map[string]any{"session_id": sid, "path": "ok.go"})
	// An inline control round trip (preview_close is answered on the dispatch
	// loop itself), standing in for terminal input and every other control frame.
	ping := h.send("filesystem.preview_close", map[string]any{"session_id": sid, "preview_id": "01K6B9R3V1EW7Q2M8N4X6Y0Z5T"})

	if r := h.await(ping, time.Until(deadline)); r.typ != "filesystem.preview_closed" {
		t.Fatalf("inline control frame: %+v", r)
	}
	for _, id := range []string{a, b} {
		r := h.await(id, time.Until(deadline))
		e, _ := r.payload["error"].(map[string]any)
		if r.typ != "filesystem.content" || r.payload["success"] != false ||
			e["code"] != "FILE_DENIED" || e["reason"] != "not_regular" {
			t.Fatalf("FIFO read must be an in-band not_regular denial: %+v", r)
		}
		if _, has := r.payload["content"]; has {
			t.Fatalf("a denial carried content: %s", truncate(r.raw))
		}
	}
	r := h.await(ok, time.Until(deadline))
	if r.typ != "filesystem.content" || !r.success || r.payload["success"] != true ||
		r.payload["content"] != text || r.payload["size"] != float64(len(text)) ||
		r.payload["encoding"] != "utf-8" || r.payload["language_hint"] != "go" || r.payload["rel_path"] != "ok.go" {
		t.Fatalf("the normal read changed: %+v", r)
	}
	if time.Now().After(deadline) {
		t.Fatalf("over the %v deadline", fifoDeadline)
	}
	// The connection is still the same one and still serving.
	if d := h.ping(); d > 500*time.Millisecond {
		t.Fatalf("dispatch round trip after the FIFOs: %v", d)
	}
}

func TestFsDownloadTwoFifosDoNotStallDispatch(t *testing.T) {
	blob := []byte{0x89, 'P', 'N', 'G', 0, 1, 2, 3, 0xff}
	h := newFsFifoHarness(t, map[string][]byte{"ok.bin": blob})
	sid := h.sessionID.String()
	deadline := time.Now().Add(fifoDeadline)

	a := h.send("filesystem.download", map[string]any{"session_id": sid, "path": "fifo-a.txt"})
	b := h.send("filesystem.download", map[string]any{"session_id": sid, "path": "fifo-b.txt"})
	ping := h.send("filesystem.preview_close", map[string]any{"session_id": sid, "preview_id": "01K6B9R3V1EW7Q2M8N4X6Y0Z5T"})

	if r := h.await(ping, time.Until(deadline)); r.typ != "filesystem.preview_closed" {
		t.Fatalf("inline control frame: %+v", r)
	}
	for _, id := range []string{a, b} {
		if r := h.await(id, time.Until(deadline)); r.typ != "error" || r.code != "FILE_DENIED" {
			t.Fatalf("FIFO download must be refused FILE_DENIED: %+v", r)
		}
	}
	// Download has two worker slots, so the normal request goes once the two
	// FIFO refusals are in: it proves the FIFOs did not keep their slots, where
	// sending it alongside them could legitimately draw NODE_BUSY.
	ok := h.send("filesystem.download", map[string]any{"session_id": sid, "path": "ok.bin"})
	r := h.await(ok, time.Until(deadline))
	if r.typ != "filesystem.downloaded" || !r.success || r.payload["size"] != float64(len(blob)) || r.payload["path"] != "ok.bin" {
		t.Fatalf("the normal download changed: %+v", r)
	}
	got, err := base64.StdEncoding.DecodeString(r.payload["data"].(string))
	if err != nil || string(got) != string(blob) {
		t.Fatalf("download bytes: %q %v", got, err)
	}
	if time.Now().After(deadline) {
		t.Fatalf("over the %v deadline", fifoDeadline)
	}
}

// filesystem.list on a FIFO named as the directory: OpenDir used the same
// blocking open before its is-a-directory check.
func TestFsListOnFifoDoesNotStallDispatch(t *testing.T) {
	h := newFsFifoHarness(t, map[string][]byte{"src/a.go": []byte("package a\n")})
	sid := h.sessionID.String()
	deadline := time.Now().Add(fifoDeadline)
	a := h.send("filesystem.list", map[string]any{"session_id": sid, "path": "fifo-a.txt"})
	ok := h.send("filesystem.list", map[string]any{"session_id": sid, "path": "src"})
	if r := h.await(a, time.Until(deadline)); r.typ != "error" || r.code != "WORKSPACE_NOT_DIRECTORY" {
		t.Fatalf("listing a FIFO: %+v", r)
	}
	if r := h.await(ok, time.Until(deadline)); r.typ != "filesystem.entries" {
		t.Fatalf("the normal list: %+v", r)
	}
}

// The FIFO stays a FIFO: a refusal must not have consumed or replaced it.
func TestFsFifoLeftInPlace(t *testing.T) {
	h := newFsFifoHarness(t, map[string][]byte{"ok.go": []byte("package main\n")})
	r := h.request("filesystem.read", map[string]any{"session_id": h.sessionID.String(), "path": "fifo-a.txt"})
	if r.payload["success"] != false {
		t.Fatalf("FIFO read: %+v", r)
	}
	info, err := os.Lstat(filepath.Join(h.ws, "fifo-a.txt"))
	if err != nil || info.Mode()&os.ModeNamedPipe == 0 {
		t.Fatalf("the FIFO was disturbed: %v %v", info, err)
	}
}

// holdFsWorkers parks every read/download worker at its start until released,
// so a test can fill the slots on demand.
func holdFsWorkers(h *previewHarness) *gate {
	g := &gate{entered: make(chan struct{}, 16), release: make(chan struct{})}
	h.m.fs.beforeRun = func(ctx context.Context, op string) {
		g.entered <- struct{}{}
		select {
		case <-g.release:
		case <-ctx.Done():
		}
	}
	return g
}

// Slots full → NODE_BUSY at once, from the dispatch loop, without queueing;
// and the loop keeps serving while the workers are held.
func TestFsReadAndDownloadBusyIsImmediate(t *testing.T) {
	h := newPreviewHarness(t, map[string][]byte{"ok.go": []byte("package main\n")}, func(cfg *config.Config) {
		cfg.Filesystem.Download.MaxBytes = config.DefaultDownloadMaxBytes
	})
	h.m.fs.root = h.m.preview.root
	g := holdFsWorkers(h)
	h.start()
	sid := h.sessionID.String()

	for _, c := range []struct {
		typ, reply string
		slots      int
	}{
		{"filesystem.read", "filesystem.content", fsReadWorkers},
		{"filesystem.download", "filesystem.downloaded", fsDownloadWorkers},
	} {
		held := make([]string, 0, c.slots)
		for i := 0; i < c.slots; i++ {
			held = append(held, h.send(c.typ, map[string]any{"session_id": sid, "path": "ok.go"}))
		}
		for i := 0; i < c.slots; i++ {
			select {
			case <-g.entered:
			case <-time.After(2 * time.Second):
				t.Fatalf("%s: only %d of %d workers started", c.typ, i, c.slots)
			}
		}
		started := time.Now()
		busy := h.request(c.typ, map[string]any{"session_id": sid, "path": "ok.go"})
		if busy.typ != "error" || busy.code != "NODE_BUSY" {
			t.Fatalf("%s with every slot held: %+v", c.typ, busy)
		}
		if d := time.Since(started); d > 500*time.Millisecond {
			t.Fatalf("%s: NODE_BUSY took %v; it must not queue", c.typ, d)
		}
		if d := h.ping(); d > 200*time.Millisecond {
			t.Fatalf("dispatch round trip with %s workers held: %v", c.typ, d)
		}
		g.release <- struct{}{} // free exactly one worker
		for i := 1; i < c.slots; i++ {
			g.release <- struct{}{}
		}
		for _, id := range held {
			if r := h.await(id, 5*time.Second); r.typ != c.reply || !r.success {
				t.Fatalf("%s held request: %+v", c.typ, r)
			}
		}
	}
	if n := len(h.m.fs.readSlots) + len(h.m.fs.downloadSlots); n != 0 {
		t.Fatalf("%d slots still held after every worker finished", n)
	}
}

// A worker belongs to its connection: when the connection drops, the worker is
// cancelled, its late reply is not written, its slot is freed, and the next
// connection serves normally.
func TestFsWorkersEndWithTheirConnection(t *testing.T) {
	h := newPreviewHarness(t, map[string][]byte{"ok.go": []byte("package main\n")})
	h.m.fs.root = h.m.preview.root
	var cancelled atomic.Bool
	entered := make(chan struct{}, 1)
	h.m.fs.beforeRun = func(ctx context.Context, op string) {
		entered <- struct{}{}
		<-ctx.Done()
		cancelled.Store(true)
	}
	h.start()
	id := h.send("filesystem.read", map[string]any{"session_id": h.sessionID.String(), "path": "ok.go"})
	<-entered
	h.mu.Lock()
	_ = h.conn.Close()
	h.mu.Unlock()
	h.awaitRegister() // reconnected: the old loop ended, so its worker did too
	if !cancelled.Load() {
		t.Fatal("the worker was not cancelled with its connection")
	}
	if n := len(h.m.fs.readSlots); n != 0 {
		t.Fatalf("the dropped connection's worker still holds %d slot(s)", n)
	}
	h.mu.Lock()
	_, late := h.pending[id]
	h.mu.Unlock()
	if late {
		t.Fatal("a worker replied after its connection ended")
	}
	h.m.fs.beforeRun = nil
	r := h.request("filesystem.read", map[string]any{"session_id": h.sessionID.String(), "path": "ok.go"})
	if r.typ != "filesystem.content" || r.payload["content"] != "package main\n" {
		t.Fatalf("read on the new connection: %+v", r)
	}
}
