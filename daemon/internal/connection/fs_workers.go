package connection

import (
	"context"
	"sync"

	"github.com/google/uuid"

	"github.com/cliora/cliora/daemon/internal/metrics"
	"github.com/cliora/cliora/daemon/internal/workspace"
)

// Bounded workers for filesystem.read and filesystem.download (issue #83,
// plan/31/09 §4 E1), following ADR 0029 §15's pattern for preview_open.
//
// Both used to run inline on the dispatch loop, which also carries terminal
// input, resize, session control and every other request on the connection. A
// file whose open or read is slow — a FIFO with no writer was the concrete case,
// and that open is now non-blocking as well — stalled all of it for every
// session on the node. Now the loop only validates the frame and takes a slot;
// the open, read and reply happen on a worker.
//
// The slots are daemon-wide, like the preview's, so they bound the node's memory
// for in-flight file bodies whatever the connection count: 4 text previews of at
// most max_preview_size (2 MiB default) and 2 downloads of at most
// download.max_bytes (4 MiB default, ~5.3 MiB as base64). A full set is answered
// NODE_BUSY immediately; nothing queues, because a queue only moves the wait
// into Central's request timeout. Read and download have separate slots so a
// burst of downloads cannot starve the preview pane, or the reverse.
//
// Ownership: every worker belongs to the connection whose dispatch loop started
// it. When that loop returns, its context is cancelled and the loop waits for
// its workers before returning, so none outlives the connection. A worker that
// finishes after the cancel drops its reply rather than writing it (the send
// guard below); replies still go through the connection's single serialized
// send, never a write of their own.
const (
	fsReadWorkers     = 4
	fsDownloadWorkers = 2
)

type fsWorkerState struct {
	readSlots     chan struct{}
	downloadSlots chan struct{}

	// Test seams; nil means production behaviour.
	root      func(uuid.UUID) (*workspace.Root, string, bool)
	beforeRun func(ctx context.Context, op string)
}

func newFsWorkerState() *fsWorkerState {
	return &fsWorkerState{
		readSlots:     make(chan struct{}, fsReadWorkers),
		downloadSlots: make(chan struct{}, fsDownloadWorkers),
	}
}

// fsWorkers is one connection's set of in-flight file workers.
type fsWorkers struct {
	m      *Manager
	ctx    context.Context
	cancel context.CancelFunc
	wg     sync.WaitGroup
}

func (m *Manager) beginFsWorkers(ctx context.Context) *fsWorkers {
	wctx, cancel := context.WithCancel(ctx)
	return &fsWorkers{m: m, ctx: wctx, cancel: cancel}
}

// end cancels the connection's workers and waits for them. Called from the
// dispatch goroutine, the only one that calls run, so Add and Wait never race.
//
// The wait is bounded by the work itself: a non-blocking open, an fstat, a read
// of at most the size cap from a regular file, and one send. It is not bounded
// against a read the kernel never returns from (a hung network filesystem); that
// would have frozen the dispatch loop outright before this change.
func (w *fsWorkers) end() {
	w.cancel()
	w.wg.Wait()
}

// run takes a slot from slots or answers NODE_BUSY at once, and runs work on a
// worker with a send that drops the reply once the connection has ended.
func (w *fsWorkers) run(slots chan struct{}, op, requestID string, send func([]byte) error, work func(send func([]byte) error)) {
	m := w.m
	if !tryAcquire(slots) {
		metrics.Increment(metrics.FilesystemRequestTotal, map[string]string{"op": op, "code": "NODE_BUSY"})
		m.replyError(send, requestID, "NODE_BUSY")
		return
	}
	live := func(frame []byte) error {
		if err := w.ctx.Err(); err != nil {
			return err // the connection has gone; there is nobody to answer
		}
		return send(frame)
	}
	w.wg.Add(1)
	go func() {
		defer w.wg.Done()
		defer func() { <-slots }()
		defer func() {
			if recover() != nil {
				metrics.Increment(metrics.FilesystemRequestTotal, map[string]string{"op": op, "code": "INTERNAL_ERROR"})
				m.replyError(live, requestID, "INTERNAL_ERROR")
			}
		}()
		if hook := m.fs.beforeRun; hook != nil {
			hook(w.ctx, op)
		}
		work(live)
	}()
}
