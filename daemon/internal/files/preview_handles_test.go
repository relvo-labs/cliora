package files

import (
	"bytes"
	"sync"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/cliora/cliora/daemon/internal/metrics"
)

type fakeClock struct {
	mu  sync.Mutex
	now time.Time
}

func (c *fakeClock) Now() time.Time { c.mu.Lock(); defer c.mu.Unlock(); return c.now }
func (c *fakeClock) Advance(d time.Duration) {
	c.mu.Lock()
	c.now = c.now.Add(d)
	c.mu.Unlock()
}

// snapshot registers a fake validated snapshot of n bytes in table t.
func snapshot(t *testing.T, pool *PreviewPool, table *PreviewTable, sid uuid.UUID, n int) (string, []byte) {
	t.Helper()
	res, ok := pool.Reserve(int64(n))
	if !ok {
		t.Fatalf("pool refused %d bytes", n)
	}
	data := bytes.Repeat([]byte{0xAB}, n)
	for i := range data {
		data[i] = byte(i)
	}
	id, count, err := table.Register(sid, PreviewResult{
		Kind: "pdf", Mime: "application/pdf", Size: int64(n), Data: data, Reservation: res,
	})
	if err != nil {
		t.Fatal(err)
	}
	if want := (n + PreviewChunkSize - 1) / PreviewChunkSize; count != want {
		t.Fatalf("chunk count %d; want %d", count, want)
	}
	return id, data
}

func TestPreviewHandleBoundToSession(t *testing.T) {
	pool := bigPool()
	table := NewPreviewTable(pool, time.Now)
	a, b := uuid.New(), uuid.New()
	id, _ := snapshot(t, pool, table, a, 1000)
	if _, err := table.Chunk(b, id, 0); err != ErrPreviewExpired {
		t.Fatalf("session B read session A's handle: %v", err)
	}
	if _, err := table.Chunk(a, "01K6B9R3V1EW7Q2M8N4X6Y0Z5T", 0); err != ErrPreviewExpired {
		t.Fatalf("unknown handle: %v", err)
	}
	// A close from the wrong session is answered like any close and changes nothing.
	table.Close(b, id)
	if _, err := table.Chunk(a, id, 0); err != nil {
		t.Fatalf("a foreign close must not free the handle: %v", err)
	}
	if _, err := table.Chunk(a, id, 1); err != ErrPreviewChunkRange {
		t.Fatalf("index beyond chunk_count: %v", err)
	}
}

func TestPreviewCloseFreesImmediately(t *testing.T) {
	metrics.Reset()
	pool := bigPool()
	clock := &fakeClock{now: time.Unix(1000, 0)}
	table := NewPreviewTable(pool, clock.Now)
	sid := uuid.New()
	id, data := snapshot(t, pool, table, sid, 3*PreviewChunkSize+17)
	if metrics.GaugeValue(metrics.FilesystemPreviewHandles, nil) != 1 ||
		metrics.GaugeValue(metrics.FilesystemPreviewReservedBytes, nil) != float64(len(data)) {
		t.Fatal("gauges must show the held snapshot")
	}
	var got []byte
	for i := 0; i < 4; i++ {
		chunk, err := table.Chunk(sid, id, i)
		if err != nil {
			t.Fatal(err)
		}
		got = append(got, chunk...)
	}
	if !bytes.Equal(got, data) {
		t.Fatal("the chunks do not reassemble into the validated snapshot")
	}
	table.Close(sid, id)
	table.Close(sid, id) // idempotent
	if table.Len() != 0 {
		t.Fatal("close must free the handle at once, not at the TTL")
	}
	if b, n := pool.InUse(); b != 0 || n != 0 {
		t.Fatalf("pool still holds %d bytes / %d slots after close", b, n)
	}
	if metrics.GaugeValue(metrics.FilesystemPreviewHandles, nil) != 0 ||
		metrics.GaugeValue(metrics.FilesystemPreviewReservedBytes, nil) != 0 {
		t.Fatal("gauges must drop to zero on close")
	}
}

// TTLs are a backstop for a lost close, not the release path.
func TestPreviewHandleExpiresAndFrees(t *testing.T) {
	pool := bigPool()
	clock := &fakeClock{now: time.Unix(1000, 0)}
	table := NewPreviewTable(pool, clock.Now)
	sid := uuid.New()
	idle, _ := snapshot(t, pool, table, sid, 10)
	busy, _ := snapshot(t, pool, table, sid, 10)
	clock.Advance(29 * time.Second)
	if _, err := table.Chunk(sid, busy, 0); err != nil { // keeps `busy` fresh
		t.Fatal(err)
	}
	if table.Sweep() != 0 {
		t.Fatal("nothing is idle for 30 s yet")
	}
	clock.Advance(2 * time.Second)
	if n := table.Sweep(); n != 1 || table.Len() != 1 {
		t.Fatalf("idle handle not reaped: swept %d, left %d", n, table.Len())
	}
	if _, err := table.Chunk(sid, idle, 0); err != ErrPreviewExpired {
		t.Fatal("an expired handle must read as expired")
	}
	// Absolute 120 s, however busy.
	for i := 0; i < 5; i++ {
		clock.Advance(20 * time.Second)
		if _, err := table.Chunk(sid, busy, 0); err != nil {
			t.Fatal(err)
		}
	}
	clock.Advance(1 * time.Second)
	if table.Sweep() != 1 || table.Len() != 0 {
		t.Fatal("the absolute lifetime must reap a handle that is still being read")
	}
	if b, n := pool.InUse(); b != 0 || n != 0 {
		t.Fatal("expiry must return the bytes to the pool")
	}
}

func TestPreviewSessionStopDropsItsHandles(t *testing.T) {
	pool := bigPool()
	table := NewPreviewTable(pool, time.Now)
	a, b := uuid.New(), uuid.New()
	snapshot(t, pool, table, a, 10)
	snapshot(t, pool, table, a, 10)
	keep, _ := snapshot(t, pool, table, b, 10)
	if n := table.DropSession(a); n != 2 || table.Len() != 1 {
		t.Fatalf("dropped %d, left %d", n, table.Len())
	}
	if _, err := table.Chunk(b, keep, 0); err != nil {
		t.Fatal("another session's handle must survive")
	}
}

func TestPreviewTableCloseAllAndLateRegister(t *testing.T) {
	pool := bigPool()
	table := NewPreviewTable(pool, time.Now)
	sid := uuid.New()
	snapshot(t, pool, table, sid, 10)
	table.CloseAll()
	if table.Len() != 0 {
		t.Fatal("CloseAll must empty the table")
	}
	// An open that finishes after its connection is gone must not park bytes.
	res, _ := pool.Reserve(10)
	if _, _, err := table.Register(sid, PreviewResult{Kind: "pdf", Mime: "application/pdf", Size: 10, Data: make([]byte, 10), Reservation: res}); err != ErrPreviewExpired {
		t.Fatalf("register on a closed table: %v", err)
	}
	if b, n := pool.InUse(); b != 0 || n != 0 {
		t.Fatal("a refused register must release its reservation")
	}
}

func TestPreviewPoolLimits(t *testing.T) {
	pool := NewPreviewPool(32*mib, 4)
	var held []*PreviewReservation
	for i := 0; i < 4; i++ {
		r, ok := pool.Reserve(1)
		if !ok {
			t.Fatal("four slots must be available")
		}
		held = append(held, r)
	}
	if _, ok := pool.Reserve(1); ok {
		t.Fatal("a fifth handle must be refused")
	}
	held[0].Release()
	held[0].Release() // idempotent: must not free a second slot
	if _, n := pool.InUse(); n != 3 {
		t.Fatalf("double release freed twice: %d slots in use", n)
	}
	if _, ok := pool.Reserve(32*mib - 3 + 1); ok {
		t.Fatal("bytes beyond the pool must be refused")
	}
}
