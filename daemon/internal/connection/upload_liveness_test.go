package connection

import (
	"encoding/base64"
	"sync"
	"testing"
	"time"

	"github.com/cliora/cliora/daemon/internal/config"
	"github.com/cliora/cliora/daemon/internal/workspace"
	"github.com/google/uuid"
)

// A slow workspace/storage entry must not park the production control loop.
// Cleanup releases it on the defective inline implementation as well.
func TestImageUploadSlowStorageKeepsDispatchLive(t *testing.T) {
	h := newPreviewHarness(t, nil, func(cfg *config.Config) {
		cfg.Filesystem.Upload.MaxBytes = 6
		cfg.Filesystem.Upload.MaxSessionBytes = 6
		cfg.Filesystem.Upload.MaxFilesPerDay = 1
	})
	entered, release := make(chan struct{}), make(chan struct{})
	var first sync.Once
	h.m.fs.root = func(id uuid.UUID) (*workspace.Root, string, bool) {
		first.Do(func() { close(entered); <-release })
		return h.m.preview.root(id)
	}
	h.start()
	released := false
	t.Cleanup(func() {
		if !released {
			close(release)
		}
	})
	id := h.send("filesystem.upload", map[string]any{"session_id": h.sessionID.String(), "data": base64.StdEncoding.EncodeToString([]byte("GIF89a"))})

	select {
	case <-entered:
	case <-time.After(time.Second):
		t.Fatal("storage did not start")
	}
	ping := h.send("filesystem.preview_close", map[string]any{"session_id": h.sessionID.String(), "preview_id": "01K6B9R3V1EW7Q2M8N4X6Y0Z5T"})
	if r := h.await(ping, 500*time.Millisecond); r.typ != "filesystem.preview_closed" {
		t.Fatalf("dispatch blocked by upload: %+v", r)
	}
	busy := h.send("filesystem.upload", map[string]any{"session_id": h.sessionID.String(), "data": base64.StdEncoding.EncodeToString([]byte("GIF89a"))})
	if r := h.await(busy, 500*time.Millisecond); r.code != "NODE_BUSY" {
		t.Fatalf("upload admission must be bounded: %+v", r)
	}
	// A worker stuck in IO must keep its admission slot across reconnects,
	// while allowing a new control connection to register and serve requests.
	h.mu.Lock()
	_ = h.conn.Close()
	h.mu.Unlock()
	h.awaitRegister()
	busy = h.send("filesystem.upload", map[string]any{"session_id": h.sessionID.String(), "data": base64.StdEncoding.EncodeToString([]byte("GIF89a"))})
	if r := h.await(busy, time.Second); r.code != "NODE_BUSY" {
		t.Fatalf("reconnect lost upload bound: %+v", r)
	}
	close(release)
	released = true
	until := time.Now().Add(time.Second)
	for len(h.m.fs.uploadSlots) != 0 && time.Now().Before(until) {
		time.Sleep(time.Millisecond)
	}
	if len(h.m.fs.uploadSlots) != 0 {
		t.Fatal("upload slot leaked after IO returned")
	}
	h.mu.Lock()
	_, late := h.pending[id]
	h.mu.Unlock()
	if late {
		t.Fatal("obsolete connection replied after reconnect")
	}
	quota := h.send("filesystem.upload", map[string]any{"session_id": h.sessionID.String(), "data": base64.StdEncoding.EncodeToString([]byte("GIF89a"))})
	if r := h.await(quota, time.Second); r.code != "FILE_UPLOAD_QUOTA_EXCEEDED" {
		t.Fatalf("completed old write was lost from quota: %+v", r)
	}
	select {
	case <-h.heartbeats:
	case <-time.After(2 * time.Second):
		t.Fatal("heartbeat stalled")
	}
}
