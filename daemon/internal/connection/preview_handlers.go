package connection

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"os"
	"path/filepath"
	"sync"
	"syscall"
	"time"

	"github.com/google/uuid"

	"github.com/cliora/cliora/daemon/internal/files"
	"github.com/cliora/cliora/daemon/internal/metrics"
	"github.com/cliora/cliora/daemon/internal/protocol"
	ctmux "github.com/cliora/cliora/daemon/internal/tmux"
	"github.com/cliora/cliora/daemon/internal/workspace"
)

// Read-only binary preview handlers (ADR 0029 §5, plan/31/03 §4).
//
// Unlike handleFsRead, which runs inline on the dispatch loop, preview_open and
// preview_chunk run on bounded workers: 2 opens and 4 chunk encoders per daemon.
// A full worker set is answered NODE_BUSY at once; nothing queues, because a
// queue would only move the wait into Central's timeout. preview_close stays
// inline on purpose: it is an O(1) map delete, and a close must never be refused
// as busy — it is what frees the snapshot.
//
// Logs carry ids, kind, code, bytes and duration. Never a path or a file name.

const (
	previewOpenWorkers  = 2
	previewChunkWorkers = 4
	previewProbeTimeout = 100 * time.Millisecond
)

type previewOpenFunc func(ctx context.Context, root *workspace.Root, rel string, pool *files.PreviewPool) (files.PreviewResult, error)

type previewState struct {
	pool       *files.PreviewPool
	openSlots  chan struct{}
	chunkSlots chan struct{}

	// Test seams; nil means production behaviour.
	now             func() time.Time
	janitorInterval time.Duration
	probe           func() error
	root            func(uuid.UUID) (*workspace.Root, string, bool)
	open            previewOpenFunc

	once      sync.Once
	available bool

	// The current connection's handle table. A new one per connection; closed
	// (all snapshots freed) when that connection's dispatch loop ends.
	mu    sync.Mutex
	table *files.PreviewTable
}

func newPreviewState() *previewState {
	return &previewState{
		pool:            files.NewPreviewPool(files.DefaultPreviewPoolBytes, files.DefaultPreviewMaxHandles),
		openSlots:       make(chan struct{}, previewOpenWorkers),
		chunkSlots:      make(chan struct{}, previewChunkWorkers),
		now:             time.Now,
		janitorInterval: files.PreviewJanitorInterval,
	}
}

// binaryPreviewAvailable is the node switch AND the start-up probe, evaluated
// once. Either one false means the capability is not reported and every preview
// request is refused FILE_PREVIEW_DISABLED (fail closed, ADR 0029 §3 step 4).
func (m *Manager) binaryPreviewAvailable() bool {
	p := m.preview
	p.once.Do(func() {
		if !m.files.PreviewEnabled() {
			slog.Info("binary_preview", "available", false, "reason", "disabled")
			return
		}
		probe := p.probe
		if probe == nil {
			probe = func() error { return probeNonBlockingOpen(ctmux.ResolveConfigDir(), nil, previewProbeTimeout) }
		}
		if err := probe(); err != nil {
			slog.Warn("binary preview is not offered: the non-blocking open probe failed",
				"event", "filesystem.preview_probe_failed", "error", err.Error())
			return
		}
		p.available = true
		slog.Info("binary_preview", "available", true)
	})
	return p.available
}

// reportBinaryPreview adds binary_preview: true when the node offers it, and
// otherwise leaves the key OUT. `false` is invalid on the wire (const: true): an
// older Central rejects the key itself, so a disabled daemon must look exactly
// like an old one (ADR 0029 §9).
func (m *Manager) reportBinaryPreview(payload map[string]any) {
	if m.binaryPreviewAvailable() {
		payload["binary_preview"] = true
	}
}

// beginPreviewTable opens this connection's handle table and its janitor, which
// ends (freeing everything) with the connection's context.
func (m *Manager) beginPreviewTable(ctx context.Context) *files.PreviewTable {
	p := m.preview
	table := files.NewPreviewTable(p.pool, p.now)
	p.mu.Lock()
	p.table = table
	p.mu.Unlock()
	go table.Janitor(ctx, p.janitorInterval)
	return table
}

// endPreviewTable frees every snapshot of a connection that has gone. Called
// when the dispatch loop returns, which can be before the context is cancelled.
func (m *Manager) endPreviewTable(table *files.PreviewTable) {
	table.CloseAll()
	p := m.preview
	p.mu.Lock()
	if p.table == table {
		p.table = nil
	}
	p.mu.Unlock()
}

// dropSessionPreviews is the session.stop hook (plan/31/03 §3).
func (m *Manager) dropSessionPreviews(sessionID uuid.UUID) {
	p := m.preview
	p.mu.Lock()
	table := p.table
	p.mu.Unlock()
	if table != nil {
		table.DropSession(sessionID)
	}
}

func tryAcquire(slots chan struct{}) bool {
	select {
	case slots <- struct{}{}:
		return true
	default:
		return false
	}
}

type previewOpenPayload struct {
	SessionID uuid.UUID `json:"session_id"`
	Path      string    `json:"path"`
}

type previewChunkPayload struct {
	SessionID uuid.UUID `json:"session_id"`
	PreviewID string    `json:"preview_id"`
	Index     int       `json:"index"`
}

func (m *Manager) handlePreviewOpen(
	ctx context.Context, table *files.PreviewTable, env protocol.Envelope, data []byte, send func([]byte) error,
) {
	if protocol.ValidateControl(data) != nil {
		m.replyError(send, env.RequestID, "INVALID_MESSAGE")
		return
	}
	var p previewOpenPayload
	if json.Unmarshal(env.Payload, &p) != nil {
		m.replyError(send, env.RequestID, "INVALID_MESSAGE")
		return
	}
	if !m.binaryPreviewAvailable() {
		m.previewOutcome("preview_open", "FILE_PREVIEW_DISABLED")
		m.replyError(send, env.RequestID, "FILE_PREVIEW_DISABLED")
		return
	}
	if !tryAcquire(m.preview.openSlots) {
		m.previewOutcome("preview_open", "NODE_BUSY")
		m.replyError(send, env.RequestID, "NODE_BUSY")
		return
	}
	go func() {
		defer func() { <-m.preview.openSlots }()
		defer m.recoverPreview(send, env.RequestID, "preview_open")
		m.runPreviewOpen(ctx, table, env, p, send)
	}()
}

func (m *Manager) runPreviewOpen(
	ctx context.Context, table *files.PreviewTable, env protocol.Envelope, p previewOpenPayload, send func([]byte) error,
) {
	started := time.Now()
	resolve := m.preview.root
	if resolve == nil {
		resolve = m.openSessionWorkspace
	}
	root, code, ok := resolve(p.SessionID)
	if !ok {
		m.replyError(send, env.RequestID, orSessionNotFound(code))
		return
	}
	defer root.Close()
	open := m.preview.open
	if open == nil {
		open = m.files.PreviewOpen
	}
	res, err := open(ctx, root, p.Path, m.preview.pool)
	switch {
	case ctx.Err() != nil:
		res.Reservation.Release()
		return // the connection has gone; there is nobody to answer
	case errors.Is(err, files.ErrPreviewDisabled):
		m.previewOutcome("preview_open", "FILE_PREVIEW_DISABLED")
		m.replyError(send, env.RequestID, "FILE_PREVIEW_DISABLED")
		return
	case errors.Is(err, files.ErrPreviewBusy):
		m.previewOutcome("preview_open", "NODE_BUSY")
		m.replyError(send, env.RequestID, "NODE_BUSY")
		return
	case err != nil:
		code := workspaceCode(err)
		m.previewOutcome("preview_open", code)
		m.replyError(send, env.RequestID, code)
		return
	}
	if res.Denied {
		metrics.Increment(metrics.FilesystemDeniedTotal, map[string]string{"code": res.Code, "reason": res.Reason})
		m.previewOutcome("preview_open", res.Code)
		m.logPreview(env.RequestID, p.SessionID, "", res.Code, 0, started)
		denial := map[string]any{"code": res.Code, "reason": res.Reason}
		if res.Code == "FILE_TOO_LARGE" {
			denial["size"], denial["limit"] = res.Size, res.Limit
		}
		frame, buildErr := protocol.BuildResponse("filesystem.preview_opened", m.creds.NodeID, env.RequestID, false,
			map[string]any{"success": false, "path": p.Path, "error": denial}, m.now())
		if buildErr != nil {
			m.replyError(send, env.RequestID, "FRAME_TOO_LARGE")
			return
		}
		_ = send(frame)
		return
	}
	id, count, err := table.Register(p.SessionID, res)
	if err != nil {
		m.previewOutcome("preview_open", "FILE_PREVIEW_EXPIRED")
		m.replyError(send, env.RequestID, "FILE_PREVIEW_EXPIRED")
		return
	}
	payload := map[string]any{
		"success":     true,
		"preview_id":  id,
		"path":        p.Path,
		"kind":        res.Kind,
		"mime":        res.Mime,
		"size":        res.Size,
		"modified_at": res.ModifiedAt.UTC().Format("2006-01-02T15:04:05.000000Z"),
		"chunk_size":  files.PreviewChunkSize,
		"chunk_count": count,
	}
	if res.Kind == "image" {
		payload["width"], payload["height"] = res.Width, res.Height
	}
	frame, err := protocol.BuildResponse("filesystem.preview_opened", m.creds.NodeID, env.RequestID, true, payload, m.now())
	if err != nil {
		table.Close(p.SessionID, id)
		m.replyError(send, env.RequestID, "FRAME_TOO_LARGE")
		return
	}
	metrics.Observe(metrics.FilesystemPreviewBytes, float64(res.Size), map[string]string{"kind": res.Kind})
	m.previewOutcome("preview_open", "OK")
	m.logPreview(env.RequestID, p.SessionID, res.Kind, "OK", res.Size, started)
	if send(frame) != nil {
		table.Close(p.SessionID, id)
	}
}

func (m *Manager) handlePreviewChunk(
	table *files.PreviewTable, env protocol.Envelope, data []byte, send func([]byte) error,
) {
	if protocol.ValidateControl(data) != nil {
		m.replyError(send, env.RequestID, "INVALID_MESSAGE")
		return
	}
	var p previewChunkPayload
	if json.Unmarshal(env.Payload, &p) != nil {
		m.replyError(send, env.RequestID, "INVALID_MESSAGE")
		return
	}
	if !tryAcquire(m.preview.chunkSlots) {
		m.previewOutcome("preview_chunk", "NODE_BUSY")
		m.replyError(send, env.RequestID, "NODE_BUSY")
		return
	}
	go func() {
		defer func() { <-m.preview.chunkSlots }()
		defer m.recoverPreview(send, env.RequestID, "preview_chunk")
		chunk, err := table.Chunk(p.SessionID, p.PreviewID, p.Index)
		if err != nil {
			code := err.Error() // FILE_PREVIEW_EXPIRED or INVALID_MESSAGE
			m.previewOutcome("preview_chunk", code)
			m.replyError(send, env.RequestID, code)
			return
		}
		frame, err := protocol.BuildResponse("filesystem.preview_data", m.creds.NodeID, env.RequestID, true,
			map[string]any{"preview_id": p.PreviewID, "index": p.Index, "data": base64.StdEncoding.EncodeToString(chunk)},
			m.now())
		if err != nil {
			m.previewOutcome("preview_chunk", "FRAME_TOO_LARGE")
			m.replyError(send, env.RequestID, "FRAME_TOO_LARGE")
			return
		}
		m.previewOutcome("preview_chunk", "OK")
		_ = send(frame)
	}()
}

// handlePreviewClose is inline and idempotent. An unknown id, another session's
// id, and a real one are all answered the same way.
func (m *Manager) handlePreviewClose(
	table *files.PreviewTable, env protocol.Envelope, data []byte, send func([]byte) error,
) {
	if protocol.ValidateControl(data) != nil {
		m.replyError(send, env.RequestID, "INVALID_MESSAGE")
		return
	}
	var p previewChunkPayload
	if json.Unmarshal(env.Payload, &p) != nil {
		m.replyError(send, env.RequestID, "INVALID_MESSAGE")
		return
	}
	table.Close(p.SessionID, p.PreviewID)
	frame, err := protocol.BuildResponse("filesystem.preview_closed", m.creds.NodeID, env.RequestID, true,
		map[string]any{"preview_id": p.PreviewID}, m.now())
	if err == nil {
		_ = send(frame)
	}
}

func (m *Manager) recoverPreview(send func([]byte) error, requestID, op string) {
	if recover() != nil {
		m.previewOutcome(op, "INTERNAL_ERROR")
		m.replyError(send, requestID, "INTERNAL_ERROR")
	}
}

func (m *Manager) previewOutcome(op, code string) {
	metrics.Increment(metrics.FilesystemRequestTotal, map[string]string{"op": op, "code": code})
}

func (m *Manager) logPreview(requestID string, sessionID uuid.UUID, kind, code string, size int64, started time.Time) {
	slog.Info("filesystem preview",
		"event", "filesystem.preview_open", "request_id", requestID,
		"session_id", sessionID.String(), "kind", kind, "code", code, "bytes", size,
		"duration_ms", time.Since(started).Milliseconds())
}

var errProbeBlocked = errors.New("open of a writerless FIFO did not return within the probe timeout")

// probeNonBlockingOpen proves, on this machine, that os.Root.OpenFile passes
// O_NONBLOCK through (ADR 0029 §3 step 4). It creates a FIFO in the daemon's OWN
// private directory — never a workspace — and opens it with the preview's flags.
// If the open has not returned within timeout, the probe opens the write end
// itself, which releases the blocked open: both ends belong to the daemon, so
// nothing is abandoned. Any failure fails closed.
//
// open is a test seam; nil means the production open.
func probeNonBlockingOpen(dir string, open func(r *os.Root, name string) (*os.File, error), timeout time.Duration) error {
	if open == nil {
		open = func(r *os.Root, name string) (*os.File, error) {
			return r.OpenFile(name, workspace.NonBlockingReadFlags, 0)
		}
	}
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return fmt.Errorf("probe directory: %w", err)
	}
	name := ".cliora-preview-probe-" + protocol.NewID()
	path := filepath.Join(dir, name)
	if err := syscall.Mkfifo(path, 0o600); err != nil {
		return fmt.Errorf("mkfifo: %w", err)
	}
	defer os.Remove(path)
	root, err := os.OpenRoot(dir)
	if err != nil {
		return fmt.Errorf("open root: %w", err)
	}
	defer root.Close()

	type result struct {
		f   *os.File
		err error
	}
	done := make(chan result, 1)
	go func() {
		f, err := open(root, name)
		done <- result{f, err}
	}()
	finish := func(r result) error {
		if r.f == nil {
			return r.err
		}
		info, err := r.f.Stat()
		_ = r.f.Close()
		if err != nil || info.Mode()&os.ModeNamedPipe == 0 {
			return errors.New("the probe opened something other than its FIFO")
		}
		return r.err
	}
	select {
	case r := <-done:
		return finish(r)
	case <-time.After(timeout):
	}
	// Release the blocked open with our own writer, then wait for it.
	if w, werr := os.OpenFile(path, os.O_WRONLY|syscall.O_NONBLOCK, 0); werr == nil {
		defer w.Close()
	}
	select {
	case r := <-done:
		_ = finish(r)
	case <-time.After(time.Second):
		return fmt.Errorf("%w, and could not be released", errProbeBlocked)
	}
	return errProbeBlocked
}
