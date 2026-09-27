package files

import (
	"context"
	"errors"
	"sync"
	"time"

	"github.com/google/uuid"

	"github.com/cliora/cliora/daemon/internal/metrics"
	"github.com/cliora/cliora/daemon/internal/protocol"
)

// Snapshot handles for read-only binary preview (ADR 0029 §5, plan/31/03 §3).
//
// Two structures, with different owners and lifetimes:
//
//   - PreviewPool is per DAEMON. It is the one 32 MiB budget and the one 4-handle
//     budget, shared by snapshots already held and opens still reading. An open
//     reserves its size before the full read and the reservation moves into the
//     handle, so held snapshots plus in-progress reads never exceed the pool —
//     including across a reconnect, when an old connection's read may still be
//     finishing.
//   - PreviewTable is per CONNECTION. When the WebSocket drops, the whole table
//     is closed, so a preview_id never survives a reconnect (FILE_PREVIEW_EXPIRED).
//
// Release is by preview_close, which Central sends at the end of every stream.
// Idle 30 s, absolute 120 s, session stop and disconnect are backstops for a lost
// close, not the normal path.

const (
	DefaultPreviewPoolBytes  int64 = 32 * 1024 * 1024
	DefaultPreviewMaxHandles       = 4
	PreviewIdleTTL                 = 30 * time.Second
	PreviewAbsoluteTTL             = 120 * time.Second
	PreviewJanitorInterval         = 5 * time.Second
)

var (
	// ErrPreviewExpired is every "no such handle for you" outcome: unknown id,
	// expired, another session's, or a table that has been closed. They are
	// deliberately indistinguishable.
	ErrPreviewExpired = errors.New("FILE_PREVIEW_EXPIRED")
	// ErrPreviewChunkRange is an index at or past chunk_count on a handle the
	// caller does own: a malformed request, not an expiry.
	ErrPreviewChunkRange = errors.New("INVALID_MESSAGE")
)

// PreviewPool is the daemon-wide snapshot budget.
type PreviewPool struct {
	mu         sync.Mutex
	maxBytes   int64
	maxHandles int
	bytes      int64
	slots      int
	handles    int
}

func NewPreviewPool(maxBytes int64, maxHandles int) *PreviewPool {
	return &PreviewPool{maxBytes: maxBytes, maxHandles: maxHandles}
}

// PreviewReservation is size bytes and one handle slot, held from before the
// full read until the handle is freed (or the open fails).
type PreviewReservation struct {
	pool  *PreviewPool
	n     int64
	once  sync.Once
	held  bool // counted as a registered handle, for the gauge
	mu    sync.Mutex
	freed bool
}

// Reserve takes n bytes and a slot, or refuses at once. It never waits.
func (p *PreviewPool) Reserve(n int64) (*PreviewReservation, bool) {
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.slots >= p.maxHandles || p.bytes+n > p.maxBytes {
		return nil, false
	}
	p.slots++
	p.bytes += n
	p.publishLocked()
	return &PreviewReservation{pool: p, n: n}, true
}

// Bytes is the size this reservation holds.
func (r *PreviewReservation) Bytes() int64 { return r.n }

// Release returns the bytes and the slot. Idempotent.
func (r *PreviewReservation) Release() {
	if r == nil {
		return
	}
	r.once.Do(func() {
		p := r.pool
		p.mu.Lock()
		p.slots--
		p.bytes -= r.n
		r.mu.Lock()
		if r.held {
			p.handles--
		}
		r.freed = true
		r.mu.Unlock()
		p.publishLocked()
		p.mu.Unlock()
	})
}

func (r *PreviewReservation) markHeld() bool {
	p := r.pool
	p.mu.Lock()
	defer p.mu.Unlock()
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.freed || r.held {
		return false
	}
	r.held = true
	p.handles++
	p.publishLocked()
	return true
}

// InUse reports reserved bytes and slots (handles plus in-progress opens).
func (p *PreviewPool) InUse() (int64, int) {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.bytes, p.slots
}

func (p *PreviewPool) publishLocked() {
	metrics.SetGauge(metrics.FilesystemPreviewHandles, float64(p.handles), nil)
	metrics.SetGauge(metrics.FilesystemPreviewReservedBytes, float64(p.bytes), nil)
}

type previewHandle struct {
	id        string
	sessionID uuid.UUID
	kind      string
	mime      string
	data      []byte // the validated snapshot, exactly
	created   time.Time
	lastUsed  time.Time
	res       *PreviewReservation
}

// PreviewTable is one connection's handles.
type PreviewTable struct {
	mu      sync.Mutex
	pool    *PreviewPool
	now     func() time.Time
	handles map[string]*previewHandle
	closed  bool
}

func NewPreviewTable(pool *PreviewPool, now func() time.Time) *PreviewTable {
	if now == nil {
		now = time.Now
	}
	return &PreviewTable{pool: pool, now: now, handles: map[string]*previewHandle{}}
}

// Register moves a validated snapshot and its reservation into a new handle
// (ADR 0029 §3 step 11) and returns its id and chunk count. On a closed table
// (the connection has gone) the reservation is released and ErrPreviewExpired
// returned, so a late open cannot park bytes nobody can read.
func (t *PreviewTable) Register(sessionID uuid.UUID, res PreviewResult) (string, int, error) {
	t.mu.Lock()
	defer t.mu.Unlock()
	if t.closed || res.Reservation == nil || !res.Reservation.markHeld() {
		res.Reservation.Release()
		return "", 0, ErrPreviewExpired
	}
	now := t.now()
	h := &previewHandle{
		id:        protocol.NewID(),
		sessionID: sessionID,
		kind:      res.Kind,
		mime:      res.Mime,
		data:      res.Data,
		created:   now,
		lastUsed:  now,
		res:       res.Reservation,
	}
	t.handles[h.id] = h
	return h.id, ChunkCount(int64(len(res.Data))), nil
}

// Chunk returns chunk index of the handle. The slice aliases the snapshot; it is
// read-only by contract.
func (t *PreviewTable) Chunk(sessionID uuid.UUID, id string, index int) ([]byte, error) {
	t.mu.Lock()
	defer t.mu.Unlock()
	h, ok := t.handles[id]
	if !ok || h.sessionID != sessionID {
		return nil, ErrPreviewExpired
	}
	if index < 0 || index >= ChunkCount(int64(len(h.data))) {
		return nil, ErrPreviewChunkRange
	}
	h.lastUsed = t.now()
	start := index * PreviewChunkSize
	end := min(start+PreviewChunkSize, len(h.data))
	return h.data[start:end], nil
}

// Close frees the handle at once. Idempotent; a close naming another session's
// handle changes nothing and is answered the same way.
func (t *PreviewTable) Close(sessionID uuid.UUID, id string) {
	t.mu.Lock()
	defer t.mu.Unlock()
	if h, ok := t.handles[id]; ok && h.sessionID == sessionID {
		t.freeLocked(h)
	}
}

// DropSession frees every handle of a session (session.stop).
func (t *PreviewTable) DropSession(sessionID uuid.UUID) int {
	t.mu.Lock()
	defer t.mu.Unlock()
	n := 0
	for _, h := range t.handles {
		if h.sessionID == sessionID {
			t.freeLocked(h)
			n++
		}
	}
	return n
}

// Sweep frees handles idle for PreviewIdleTTL or older than PreviewAbsoluteTTL.
func (t *PreviewTable) Sweep() int {
	t.mu.Lock()
	defer t.mu.Unlock()
	now := t.now()
	n := 0
	for _, h := range t.handles {
		if now.Sub(h.lastUsed) >= PreviewIdleTTL || now.Sub(h.created) >= PreviewAbsoluteTTL {
			t.freeLocked(h)
			n++
		}
	}
	return n
}

// CloseAll frees everything and refuses later registrations (disconnect).
func (t *PreviewTable) CloseAll() {
	t.mu.Lock()
	defer t.mu.Unlock()
	t.closed = true
	for _, h := range t.handles {
		t.freeLocked(h)
	}
}

// Len is the number of live handles.
func (t *PreviewTable) Len() int {
	t.mu.Lock()
	defer t.mu.Unlock()
	return len(t.handles)
}

// Janitor sweeps every interval until ctx ends, then closes the table. It is the
// table's only goroutine and it ends with the connection.
func (t *PreviewTable) Janitor(ctx context.Context, interval time.Duration) {
	ticker := time.NewTicker(interval)
	defer ticker.Stop()
	defer t.CloseAll()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			t.Sweep()
		}
	}
}

func (t *PreviewTable) freeLocked(h *previewHandle) {
	delete(t.handles, h.id)
	h.data = nil
	h.res.Release()
}
