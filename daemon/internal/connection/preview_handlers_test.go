package connection

import (
	"bytes"
	"compress/zlib"
	"context"
	"crypto/ed25519"
	"crypto/rand"
	"encoding/base64"
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"hash/crc32"
	"image"
	"image/png"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	goruntime "runtime"
	"sort"
	"strings"
	"sync"
	"sync/atomic"
	"syscall"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/gorilla/websocket"

	"github.com/cliora/cliora/daemon/internal/config"
	"github.com/cliora/cliora/daemon/internal/files"
	"github.com/cliora/cliora/daemon/internal/protocol"
	"github.com/cliora/cliora/daemon/internal/runtime"
	"github.com/cliora/cliora/daemon/internal/systeminfo"
	"github.com/cliora/cliora/daemon/internal/workspace"
)

// --- a fake Central that can drive the preview frames (ADR 0029, plan/31/03 §7) ---

type previewReply struct {
	typ     string
	success bool
	code    string
	payload map[string]any
	raw     []byte
}

type previewHarness struct {
	t         *testing.T
	nodeID    uuid.UUID
	sessionID uuid.UUID
	ws        string
	m         *Manager

	mu         sync.Mutex
	conn       *websocket.Conn
	writeMu    sync.Mutex
	pending    map[string]previewReply
	waiters    map[string]chan previewReply
	registered chan map[string]any
	heartbeats chan time.Time
	seq        atomic.Int64
}

type harnessOption func(cfg *config.Config)

func previewFixtureWS(t *testing.T, body map[string][]byte) (allowed, ws string) {
	t.Helper()
	base := t.TempDir()
	allowed = filepath.Join(base, "projects")
	ws = filepath.Join(allowed, "app")
	if err := os.MkdirAll(ws, 0o755); err != nil {
		t.Fatal(err)
	}
	for rel, data := range body {
		p := filepath.Join(ws, rel)
		if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(p, data, 0o644); err != nil {
			t.Fatal(err)
		}
	}
	return allowed, ws
}

func newPreviewHarness(t *testing.T, body map[string][]byte, opts ...harnessOption) *previewHarness {
	t.Helper()
	allowed, ws := previewFixtureWS(t, body)
	h := &previewHarness{
		t: t, nodeID: uuid.New(), sessionID: uuid.New(), ws: ws,
		pending:    map[string]previewReply{},
		waiters:    map[string]chan previewReply{},
		registered: make(chan map[string]any, 8),
		heartbeats: make(chan time.Time, 64),
	}
	upgrader := websocket.Upgrader{}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			return
		}
		defer conn.Close()
		challenge, _ := protocol.BuildControl("node.challenge", h.nodeID, "01K0PREV1EWCHA11ENGE00000A",
			map[string]any{"nonce": base64.StdEncoding.EncodeToString(make([]byte, 32))}, time.Now())
		_ = conn.WriteMessage(websocket.TextMessage, challenge)
		for {
			mt, data, err := conn.ReadMessage()
			if err != nil {
				return
			}
			if mt != websocket.TextMessage {
				continue
			}
			if err := protocol.ValidateControl(data); err != nil {
				t.Errorf("the daemon sent a frame the contract rejects: %v: %s", err, truncate(data))
				continue
			}
			env, _ := protocol.DecodeControl(data)
			switch env.Type {
			case "node.auth":
				f, _ := protocol.BuildControl("node.authenticated", h.nodeID, env.RequestID,
					map[string]any{"node_id": h.nodeID.String()}, time.Now())
				h.write(conn, f)
			case "node.register":
				var p map[string]any
				_ = json.Unmarshal(env.Payload, &p)
				ack, _ := protocol.BuildControl("node.registered", h.nodeID, env.RequestID,
					map[string]any{"node_id": h.nodeID.String()}, time.Now())
				h.write(conn, ack)
				h.mu.Lock()
				h.conn = conn
				h.mu.Unlock()
				h.registered <- p
			case "node.heartbeat":
				select {
				case h.heartbeats <- time.Now():
				default:
				}
			case "node.system_info", "node.runtime_status":
			default:
				h.deliver(env, data)
			}
		}
	}))
	t.Cleanup(server.Close)

	cfg := &config.Config{
		Server:    config.ServerConfig{URL: strings.Replace(server.URL, "http", "ws", 1) + "/ws/nodes"},
		Node:      config.NodeConfig{Name: "vm-preview"},
		Workspace: config.WorkspaceConfig{AllowedRoots: []string{allowed}},
		Heartbeat: config.HeartbeatConfig{IntervalSeconds: 1},
	}
	cfg.Filesystem.MaxPreviewSize = config.DefaultMaxPreviewSize
	cfg.Filesystem.DeniedPatterns = config.DefaultDeniedPatterns
	cfg.Filesystem.DeniedDirectories = config.DefaultDeniedDirectories
	for _, opt := range opts {
		opt(cfg)
	}
	_, private, _ := ed25519.GenerateKey(rand.Reader)
	creds := &config.Credentials{NodeID: h.nodeID, PrivateKey: base64.StdEncoding.EncodeToString(private)}
	h.m = New(cfg, creds, runtime.NewRegistry(cfg.Runtime), systeminfo.Gather(), "1.0.0")
	h.m.preview.probe = func() error { return nil }
	h.m.preview.root = func(id uuid.UUID) (*workspace.Root, string, bool) {
		if id != h.sessionID {
			return nil, "SESSION_NOT_FOUND", false
		}
		r, err := h.m.guard.OpenWorkspace(ws)
		if err != nil {
			return nil, workspaceCode(err), false
		}
		return r, "", true
	}
	return h
}

func (h *previewHarness) start() map[string]any {
	h.t.Helper()
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	go func() { _ = h.m.Run(ctx); close(done) }()
	h.t.Cleanup(func() {
		cancel()
		select {
		case <-done:
		case <-time.After(5 * time.Second):
			h.t.Error("the daemon did not stop")
		}
	})
	return h.awaitRegister()
}

func (h *previewHarness) awaitRegister() map[string]any {
	h.t.Helper()
	select {
	case p := <-h.registered:
		return p
	case <-time.After(10 * time.Second):
		h.t.Fatal("the daemon did not register")
		return nil
	}
}

func (h *previewHarness) write(conn *websocket.Conn, frame []byte) {
	h.writeMu.Lock()
	defer h.writeMu.Unlock()
	_ = conn.WriteMessage(websocket.TextMessage, frame)
}

func (h *previewHarness) deliver(env protocol.Envelope, data []byte) {
	var wire struct {
		Error struct {
			Code string `json:"code"`
		} `json:"error"`
	}
	_ = json.Unmarshal(data, &wire)
	var p map[string]any
	_ = json.Unmarshal(env.Payload, &p)
	r := previewReply{typ: env.Type, success: env.Success != nil && *env.Success, code: wire.Error.Code,
		payload: p, raw: append([]byte(nil), data...)}
	h.mu.Lock()
	defer h.mu.Unlock()
	if ch, ok := h.waiters[env.RequestID]; ok {
		delete(h.waiters, env.RequestID)
		ch <- r
		return
	}
	h.pending[env.RequestID] = r
}

func (h *previewHarness) send(typ string, payload map[string]any) string {
	h.t.Helper()
	id := fmt.Sprintf("01K6PREV%018d", h.seq.Add(1))
	frame, err := protocol.BuildControl(typ, h.nodeID, id, payload, time.Now())
	if err != nil {
		h.t.Fatal(err)
	}
	h.mu.Lock()
	conn := h.conn
	h.mu.Unlock()
	h.write(conn, frame)
	return id
}

func (h *previewHarness) await(id string, timeout time.Duration) previewReply {
	h.t.Helper()
	h.mu.Lock()
	if r, ok := h.pending[id]; ok {
		delete(h.pending, id)
		h.mu.Unlock()
		return r
	}
	ch := make(chan previewReply, 1)
	h.waiters[id] = ch
	h.mu.Unlock()
	select {
	case r := <-ch:
		return r
	case <-time.After(timeout):
		h.t.Fatalf("no reply to %s within %v", id, timeout)
		return previewReply{}
	}
}

func (h *previewHarness) request(typ string, payload map[string]any) previewReply {
	h.t.Helper()
	return h.await(h.send(typ, payload), 5*time.Second)
}

func (h *previewHarness) openPreview(rel string) previewReply {
	return h.request("filesystem.preview_open", map[string]any{"session_id": h.sessionID.String(), "path": rel})
}

// readAll pulls every chunk and closes the handle, the way Central does.
func (h *previewHarness) readAll(opened previewReply) []byte {
	h.t.Helper()
	id := opened.payload["preview_id"].(string)
	count := int(opened.payload["chunk_count"].(float64))
	var out []byte
	for i := 0; i < count; i++ {
		r := h.request("filesystem.preview_chunk", map[string]any{
			"session_id": h.sessionID.String(), "preview_id": id, "index": i,
		})
		if r.typ != "filesystem.preview_data" {
			h.t.Fatalf("chunk %d: %s %s", i, r.typ, r.code)
		}
		data, err := base64.StdEncoding.DecodeString(r.payload["data"].(string))
		if err != nil {
			h.t.Fatal(err)
		}
		out = append(out, data...)
	}
	closed := h.request("filesystem.preview_close", map[string]any{"session_id": h.sessionID.String(), "preview_id": id})
	if closed.typ != "filesystem.preview_closed" || closed.payload["preview_id"] != id {
		h.t.Fatalf("close: %+v", closed)
	}
	return out
}

func (h *previewHarness) handles() int {
	h.m.preview.mu.Lock()
	table := h.m.preview.table
	h.m.preview.mu.Unlock()
	if table == nil {
		return 0
	}
	return table.Len()
}

func wireError(t *testing.T, raw []byte) string {
	t.Helper()
	var frame struct {
		Error   json.RawMessage `json:"error"`
		Payload json.RawMessage `json:"payload"`
	}
	if err := json.Unmarshal(raw, &frame); err != nil {
		t.Fatal(err)
	}
	return string(frame.Error) + string(frame.Payload)
}

func truncate(b []byte) string {
	if len(b) > 200 {
		return string(b[:200]) + "…"
	}
	return string(b)
}

func smallPNG(t *testing.T, w, h int) []byte {
	t.Helper()
	img := image.NewRGBA(image.Rect(0, 0, w, h))
	for i := range img.Pix {
		img.Pix[i] = byte(i)
	}
	var buf bytes.Buffer
	if err := png.Encode(&buf, img); err != nil {
		t.Fatal(err)
	}
	return buf.Bytes()
}

// --- tests ---

func TestPreviewOverConnection(t *testing.T) {
	pic := smallPNG(t, 300, 200)
	pdf := append([]byte("%PDF-1.7\n"), make([]byte, 3*protocol.PreviewChunkSize)...)
	pdf = append(pdf, []byte("\n%%EOF\n")...)
	h := newPreviewHarness(t, map[string][]byte{"a.png": pic, "docs/b.pdf": pdf, ".env": []byte("S=1")})
	register := h.start()
	if register["binary_preview"] != true {
		t.Fatalf("an enabled node must report binary_preview: true, got %v", register["binary_preview"])
	}

	opened := h.openPreview("a.png")
	if opened.typ != "filesystem.preview_opened" || !opened.success || opened.payload["success"] != true {
		t.Fatalf("open: %+v %s", opened, truncate(opened.raw))
	}
	p := opened.payload
	if p["kind"] != "image" || p["mime"] != "image/png" || p["width"] != float64(300) ||
		p["height"] != float64(200) || p["size"] != float64(len(pic)) || p["path"] != "a.png" ||
		p["chunk_size"] != float64(524288) || p["chunk_count"] != float64(1) {
		t.Fatalf("opened payload: %v", p)
	}
	if got := h.readAll(opened); !bytes.Equal(got, pic) {
		t.Fatal("the chunks must reassemble into the file")
	}
	if n := h.handles(); n != 0 {
		t.Fatalf("close must free the handle at once; %d left", n)
	}

	// A multi-chunk PDF: the snapshot equals the validated bytes (TestPreviewSnapshotEqualsValidatedBytes).
	opened = h.openPreview("docs/b.pdf")
	if opened.payload["kind"] != "pdf" || opened.payload["chunk_count"] != float64(4) {
		t.Fatalf("pdf: %v", opened.payload)
	}
	if _, has := opened.payload["width"]; has {
		t.Fatal("a PDF carries no dimensions")
	}
	if got := h.readAll(opened); !bytes.Equal(got, pdf) {
		t.Fatal("PDF chunks do not reassemble")
	}

	// In-band denial.
	denied := h.openPreview(".env")
	if denied.typ != "filesystem.preview_opened" || denied.success || denied.payload["success"] != false {
		t.Fatalf("denial: %+v", denied)
	}
	if e := denied.payload["error"].(map[string]any); e["code"] != "FILE_DENIED" || e["reason"] != "dotenv" {
		t.Fatalf("denial error: %v", e)
	}
	if strings.Contains(string(denied.raw), h.ws) {
		t.Fatal("a denial must not carry an absolute path")
	}
	// Unknown session.
	other := h.request("filesystem.preview_open", map[string]any{"session_id": uuid.NewString(), "path": "a.png"})
	if other.typ != "error" || other.code != "SESSION_NOT_FOUND" {
		t.Fatalf("unknown session: %+v", other)
	}
}

func TestPreviewHandleBoundToSessionOverConnection(t *testing.T) {
	h := newPreviewHarness(t, map[string][]byte{"a.png": smallPNG(t, 4, 4)})
	h.start()
	opened := h.openPreview("a.png")
	id := opened.payload["preview_id"].(string)
	stranger := uuid.NewString()
	chunk := h.request("filesystem.preview_chunk", map[string]any{"session_id": stranger, "preview_id": id, "index": 0})
	if chunk.typ != "error" || chunk.code != "FILE_PREVIEW_EXPIRED" {
		t.Fatalf("another session's chunk: %+v", chunk)
	}
	unknown := h.request("filesystem.preview_chunk", map[string]any{"session_id": h.sessionID.String(), "preview_id": "01K6B9R3V1EW7Q2M8N4X6Y0Z5T", "index": 0})
	if unknown.code != "FILE_PREVIEW_EXPIRED" {
		t.Fatalf("unknown handle: %+v", unknown)
	}
	if wireError(t, unknown.raw) != wireError(t, chunk.raw) {
		t.Fatal("a foreign session's handle must be indistinguishable from a missing one")
	}
	h.request("filesystem.preview_close", map[string]any{"session_id": stranger, "preview_id": id})
	if h.handles() != 1 {
		t.Fatal("a foreign close must not free the handle")
	}
	out := h.request("filesystem.preview_chunk", map[string]any{"session_id": h.sessionID.String(), "preview_id": id, "index": 1})
	if out.code != "INVALID_MESSAGE" {
		t.Fatalf("index past chunk_count: %+v", out)
	}
}

// Five "open → read all → close" in a row, with the handle clock frozen so no
// TTL can fire: every one succeeds, and nothing is left afterwards. With a close
// that did not free, the fifth would be NODE_BUSY (4 handles).
func TestPreviewSuccessiveOpensBeyondHandleLimit(t *testing.T) {
	frozen := time.Unix(1_800_000_000, 0)
	h := newPreviewHarness(t, map[string][]byte{"a.png": smallPNG(t, 16, 16)})
	h.m.preview.now = func() time.Time { return frozen }
	h.m.preview.janitorInterval = time.Hour
	h.start()
	for i := 0; i < files.DefaultPreviewMaxHandles+1; i++ {
		opened := h.openPreview("a.png")
		if opened.typ != "filesystem.preview_opened" || !opened.success {
			t.Fatalf("preview %d: %+v", i+1, opened)
		}
		h.readAll(opened)
		if n := h.handles(); n != 0 {
			t.Fatalf("after preview %d: %d handles held", i+1, n)
		}
	}
	if b, n := h.m.preview.pool.InUse(); b != 0 || n != 0 {
		t.Fatalf("pool not empty: %d bytes, %d slots", b, n)
	}
}

// Two FIFOs, then a legitimate PNG, all within 2 s. A blocking open would hold
// both workers and the PNG would get NODE_BUSY or time out.
func TestPreviewTwoFifosDoNotStarveWorkers(t *testing.T) {
	h := newPreviewHarness(t, map[string][]byte{"ok.png": smallPNG(t, 8, 8)})
	for _, name := range []string{"fifo-a.png", "fifo-b.png"} {
		if err := syscall.Mkfifo(filepath.Join(h.ws, name), 0o600); err != nil {
			t.Skipf("mkfifo: %v", err)
		}
		path := filepath.Join(h.ws, name)
		t.Cleanup(func() { releaseFifo(path) })
	}
	h.start()
	deadline := time.Now().Add(2 * time.Second)
	a := h.send("filesystem.preview_open", map[string]any{"session_id": h.sessionID.String(), "path": "fifo-a.png"})
	b := h.send("filesystem.preview_open", map[string]any{"session_id": h.sessionID.String(), "path": "fifo-b.png"})
	for _, id := range []string{a, b} {
		r := h.await(id, time.Until(deadline))
		if r.payload["success"] != false || r.payload["error"].(map[string]any)["reason"] != "not_regular" {
			t.Fatalf("FIFO preview: %+v", r)
		}
	}
	ok := h.await(h.send("filesystem.preview_open", map[string]any{"session_id": h.sessionID.String(), "path": "ok.png"}), time.Until(deadline))
	if ok.typ != "filesystem.preview_opened" || !ok.success {
		t.Fatalf("the third, legitimate preview: %+v", ok)
	}
	if time.Now().After(deadline) {
		t.Fatal("over the 2 s deadline")
	}
}

func releaseFifo(path string) {
	if w, err := os.OpenFile(path, os.O_WRONLY|syscall.O_NONBLOCK, 0); err == nil {
		_ = w.Close()
	}
}

// gate holds every open after it has run for real, until released, so a test can
// keep workers busy on demand.
type gate struct {
	entered chan struct{}
	release chan struct{}
}

func holdOpens(h *previewHarness) *gate {
	g := &gate{entered: make(chan struct{}, 8), release: make(chan struct{})}
	real := h.m.files.PreviewOpen
	h.m.preview.open = func(ctx context.Context, root *workspace.Root, rel string, pool *files.PreviewPool) (files.PreviewResult, error) {
		res, err := real(ctx, root, rel, pool)
		g.entered <- struct{}{}
		<-g.release
		return res, err
	}
	return g
}

// ping measures one dispatch-loop round trip: preview_close is answered inline.
func (h *previewHarness) ping() time.Duration {
	started := time.Now()
	h.request("filesystem.preview_close", map[string]any{"session_id": h.sessionID.String(), "preview_id": "01K6B9R3V1EW7Q2M8N4X6Y0Z5T"})
	return time.Since(started)
}

func TestPreviewBusyIsImmediate(t *testing.T) {
	h := newPreviewHarness(t, map[string][]byte{"a.png": smallPNG(t, 4, 4)})
	g := holdOpens(h)
	h.start()
	first := h.send("filesystem.preview_open", map[string]any{"session_id": h.sessionID.String(), "path": "a.png"})
	second := h.send("filesystem.preview_open", map[string]any{"session_id": h.sessionID.String(), "path": "a.png"})
	<-g.entered
	<-g.entered
	started := time.Now()
	third := h.openPreview("a.png")
	if third.typ != "error" || third.code != "NODE_BUSY" {
		t.Fatalf("third concurrent open: %+v", third)
	}
	if d := time.Since(started); d > 500*time.Millisecond {
		t.Fatalf("NODE_BUSY took %v; it must not queue", d)
	}
	close(g.release)
	for _, id := range []string{first, second} {
		if r := h.await(id, 5*time.Second); !r.success {
			t.Fatalf("held open: %+v", r)
		}
	}
}

// A 16 MiB open in progress does not delay the dispatch loop, which also carries
// terminal input and heartbeats (plan/31/03 §4).
func TestPreviewDoesNotBlockDispatch(t *testing.T) {
	pdf := append([]byte("%PDF-1.7\n"), make([]byte, 16*1024*1024-16)...)
	pdf = append(pdf, []byte("\n%%EOF\n")...)
	h := newPreviewHarness(t, map[string][]byte{"big.pdf": pdf})
	g := holdOpens(h)
	h.start()
	open := h.send("filesystem.preview_open", map[string]any{"session_id": h.sessionID.String(), "path": "big.pdf"})
	<-g.entered
	for i := 0; i < 5; i++ {
		if d := h.ping(); d > 50*time.Millisecond {
			t.Fatalf("dispatch round trip %v while a 16 MiB preview is open; budget 50 ms", d)
		}
	}
	close(g.release)
	if r := h.await(open, 5*time.Second); !r.success || r.payload["size"] != float64(len(pdf)) {
		t.Fatalf("16 MiB open: %+v", r)
	}
}

// worstCasePNG: 8 MiB, compressed metadata at its ceilings (iCCP ~1 MiB in/out,
// four zTXt ~256 KiB in/out as stored blocks), padded with a private chunk.
func worstCasePNG(t *testing.T) []byte {
	t.Helper()
	chunk := func(typ string, data []byte) []byte {
		out := make([]byte, 0, len(data)+12)
		out = binary.BigEndian.AppendUint32(out, uint32(len(data)))
		out = append(out, typ...)
		out = append(out, data...)
		crc := crc32.NewIEEE()
		crc.Write([]byte(typ))
		crc.Write(data)
		return binary.BigEndian.AppendUint32(out, crc.Sum32())
	}
	stored := func(n int) []byte {
		raw := make([]byte, n)
		_, _ = rand.Read(raw)
		var buf bytes.Buffer
		w, _ := zlib.NewWriterLevel(&buf, zlib.NoCompression)
		_, _ = w.Write(raw)
		_ = w.Close()
		return buf.Bytes()
	}
	base := smallPNG(t, 64, 64)
	parts := [][]byte{base[:33], chunk("iCCP", append([]byte("Display P3\x00\x00"), stored(1024*1024-200)...))}
	for i := 0; i < 4; i++ {
		parts = append(parts, chunk("zTXt", append([]byte("Comment\x00\x00"), stored(256*1024-200)...)))
	}
	parts = append(parts, base[33:len(base)-12])
	body := bytes.Join(parts, nil)
	pad := 8*1024*1024 - len(body) - 12 - 12
	return bytes.Join([][]byte{body, chunk("paDd", make([]byte, pad)), base[len(base)-12:]}, nil)
}

func percentile(ds []time.Duration, p float64) time.Duration {
	s := append([]time.Duration(nil), ds...)
	sort.Slice(s, func(i, j int) bool { return s[i] < s[j] })
	return s[min(len(s)-1, int(float64(len(s))*p))]
}

// Two workers validate the most expensive legal PNG while the loop keeps
// answering and heartbeats keep flowing; a third open is NODE_BUSY. The three
// Wall-clock p95 uses CI slack for host jitter; set the release threshold on
// target hardware (BP-OM-05). Run once normally and once on one CPU.
func TestPreviewConcurrentWorstCaseMetadata(t *testing.T) {
	worst := worstCasePNG(t)
	if len(worst) != 8*1024*1024 {
		t.Fatalf("fixture is %d bytes", len(worst))
	}
	for _, procs := range []int{goruntime.GOMAXPROCS(0), 1} {
		t.Run(fmt.Sprintf("GOMAXPROCS=%d", procs), func(t *testing.T) {
			prev := goruntime.GOMAXPROCS(procs)
			defer goruntime.GOMAXPROCS(prev)
			h := newPreviewHarness(t, map[string][]byte{"w1.png": worst, "w2.png": worst})
			g := holdOpens(h)
			h.start()
			var baseline []time.Duration
			for i := 0; i < 10; i++ {
				baseline = append(baseline, h.ping())
				time.Sleep(50 * time.Millisecond)
			}
			started := time.Now()
			a := h.send("filesystem.preview_open", map[string]any{"session_id": h.sessionID.String(), "path": "w1.png"})
			b := h.send("filesystem.preview_open", map[string]any{"session_id": h.sessionID.String(), "path": "w2.png"})
			var loaded []time.Duration
			entered := 0
			for entered < 2 {
				select {
				case <-g.entered:
					entered++
				default:
					loaded = append(loaded, h.ping())
					time.Sleep(50 * time.Millisecond)
				}
			}
			if d := time.Since(started); d > time.Second {
				t.Fatalf("two worst-case validations took %v; provisional budget 1 s", d)
			}
			busy := h.openPreview("w1.png")
			if busy.code != "NODE_BUSY" {
				t.Fatalf("third concurrent open: %+v", busy)
			}
			// Keep the two workers held for a heartbeat interval and a half, pinging.
			hbStart := time.Now()
			for time.Since(hbStart) < 1500*time.Millisecond {
				loaded = append(loaded, h.ping())
				time.Sleep(50 * time.Millisecond)
			}
			close(g.release)
			for _, id := range []string{a, b} {
				if r := h.await(id, 5*time.Second); !r.success {
					t.Fatalf("worst-case open: %+v", r)
				}
			}
			if inc := percentile(loaded, 0.95) - percentile(baseline, 0.95); inc > 100*time.Millisecond {
				t.Fatalf("dispatch latency p95 rose by %v; CI budget 100 ms", inc)
			}
			var beats []time.Time
		drain:
			for {
				select {
				case at := <-h.heartbeats:
					beats = append(beats, at)
				default:
					break drain
				}
			}
			if len(beats) < 2 {
				t.Fatalf("observed %d heartbeats; want at least 2", len(beats))
			}
			for i := 1; i < len(beats); i++ {
				if gap := beats[i].Sub(beats[i-1]); gap > 2*time.Second {
					t.Fatalf("heartbeat gap %v; interval 1 s, allowed drift 1 s", gap)
				}
			}
			t.Logf("baseline p95 %v, loaded p95 %v, heartbeats %d", percentile(baseline, 0.95), percentile(loaded, 0.95), len(beats))
		})
	}
}

func TestPreviewHandlesDroppedOnDisconnect(t *testing.T) {
	h := newPreviewHarness(t, map[string][]byte{"a.png": smallPNG(t, 4, 4)})
	h.start()
	opened := h.openPreview("a.png")
	id := opened.payload["preview_id"].(string)
	if b, _ := h.m.preview.pool.InUse(); b == 0 {
		t.Fatal("fixture: a handle must be held")
	}
	h.mu.Lock()
	_ = h.conn.Close()
	h.mu.Unlock()
	h.awaitRegister() // the daemon reconnects with a fresh table
	deadline := time.Now().Add(2 * time.Second)
	for {
		if b, n := h.m.preview.pool.InUse(); b == 0 && n == 0 {
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("the old connection's handles were not freed")
		}
		time.Sleep(10 * time.Millisecond)
	}
	r := h.request("filesystem.preview_chunk", map[string]any{"session_id": h.sessionID.String(), "preview_id": id, "index": 0})
	if r.code != "FILE_PREVIEW_EXPIRED" {
		t.Fatalf("an id from before the reconnect: %+v", r)
	}
}

func TestPreviewOpenSendFailureReleasesHandle(t *testing.T) {
	h := newPreviewHarness(t, map[string][]byte{"a.png": smallPNG(t, 4, 4)})
	table := files.NewPreviewTable(h.m.preview.pool, time.Now)
	defer table.CloseAll()
	h.m.runPreviewOpen(context.Background(), table,
		protocol.Envelope{RequestID: protocol.NewID()},
		previewOpenPayload{SessionID: h.sessionID, Path: "a.png"},
		func(frame []byte) error {
			env, err := protocol.DecodeControl(frame)
			if err != nil || env.Type != "filesystem.preview_opened" || env.Success == nil || !*env.Success {
				t.Fatalf("expected a successful open reply, got %s: %v", frame, err)
			}
			if n := table.Len(); n != 1 {
				t.Fatalf("fixture: expected one handle at send, got %d", n)
			}
			if b, n := h.m.preview.pool.InUse(); b == 0 || n != 1 {
				t.Fatalf("fixture: expected reserved bytes and one slot at send, got %d bytes, %d slots", b, n)
			}
			return errors.New("injected send failure")
		})
	if n := table.Len(); n != 0 {
		t.Fatalf("failed reply left %d handles before idle sweep", n)
	}
	if b, n := h.m.preview.pool.InUse(); b != 0 || n != 0 {
		t.Fatalf("failed reply left %d bytes and %d slots before idle sweep", b, n)
	}
}

func TestPreviewSessionStopDropsHandles(t *testing.T) {
	h := newPreviewHarness(t, map[string][]byte{"a.png": smallPNG(t, 4, 4)})
	h.start()
	h.openPreview("a.png")
	if h.handles() != 1 {
		t.Fatal("fixture: one handle")
	}
	// The session is not really running under tmux here, so the stop itself
	// fails; the handles go regardless, because Central asked for the stop.
	h.request("session.stop", map[string]any{"session_id": h.sessionID.String()})
	if h.handles() != 0 {
		t.Fatal("session.stop must drop that session's handles")
	}
}

func TestPreviewDisabledSwitchOverConnection(t *testing.T) {
	off := false
	h := newPreviewHarness(t, map[string][]byte{"a.png": smallPNG(t, 4, 4)}, func(cfg *config.Config) {
		cfg.Filesystem.BinaryPreview.Enabled = &off
	})
	register := h.start()
	if _, present := register["binary_preview"]; present {
		t.Fatal("a disabled node must omit binary_preview")
	}
	r := h.openPreview("a.png")
	if r.typ != "error" || r.code != "FILE_PREVIEW_DISABLED" {
		t.Fatalf("preview on a disabled node: %+v", r)
	}
}

// pre11RegisterKeys is the node-register property set available to a 1.10.0
// Central. It includes #71 file_download but excludes binary_preview. A subset is
// one an older Central accepts.
var pre11RegisterKeys = map[string]bool{
	"tunnel": true, "privileged_terminal": true, "image_upload": true, "file_upload": true, "file_download": true,
	"name": true, "hostname": true, "os": true, "os_version": true, "architecture": true,
	"daemon_version": true, "run_user": true, "runtimes": true, "workspace_roots": true,
}

func registerFrame(t *testing.T, m *Manager) (map[string]any, []byte) {
	t.Helper()
	payload := m.registerPayload(nil)
	frame, err := protocol.BuildControl("node.register", m.creds.NodeID, protocol.NewID(), payload, time.Now())
	if err != nil {
		t.Fatal(err)
	}
	return payload, frame
}

func TestRegisterOmitsBinaryPreviewWhenDisabled(t *testing.T) {
	build := func(enabled *bool, probe error) *Manager {
		cfg := &config.Config{Server: ServerURLFixture(), Node: config.NodeConfig{Name: "n"}}
		cfg.Filesystem.BinaryPreview.Enabled = enabled
		m := New(cfg, &config.Credentials{NodeID: uuid.New()}, runtime.NewRegistry(nil), systeminfo.Info{
			Hostname: "h", OS: "linux", OSVersion: "1", Architecture: "amd64", RunUser: "agentd",
		}, "1.0.0")
		m.preview.probe = func() error { return probe }
		return m
	}
	off, on := false, true
	for name, tc := range map[string]struct {
		m    *Manager
		want bool
	}{
		"disabled":        {build(&off, nil), false},
		"enabled":         {build(&on, nil), true},
		"default":         {build(nil, nil), true},
		"probe failed":    {build(&on, errors.New("open blocked")), false},
		"disabled+failed": {build(&off, errors.New("never probed")), false},
	} {
		payload, frame := registerFrame(t, tc.m)
		value, present := payload["binary_preview"]
		if tc.want && value != true {
			t.Errorf("%s: want binary_preview: true, got %v", name, value)
		}
		if !tc.want && present {
			t.Errorf("%s: binary_preview must be omitted (never false), got %v", name, value)
		}
		if err := protocol.ValidateControl(frame); err != nil {
			t.Errorf("%s: register rejected by the current contract: %v", name, err)
		}
		if !tc.want {
			for key := range payload {
				if !pre11RegisterKeys[key] {
					t.Errorf("%s: key %q would make an older Central drop this register", name, key)
				}
			}
		}
	}
}

// The start-up probe on this platform: a writerless FIFO in the daemon's own
// directory opens without blocking.
func TestStartupProbePassesOnThisPlatform(t *testing.T) {
	dir := t.TempDir()
	if err := probeNonBlockingOpen(dir, nil, previewProbeTimeout); err != nil {
		t.Fatalf("the non-blocking open probe failed on %s/%s: %v", goruntime.GOOS, goruntime.GOARCH, err)
	}
	if entries, _ := os.ReadDir(dir); len(entries) != 0 {
		t.Fatalf("the probe left %d entries behind", len(entries))
	}
}

// With an open that does not return (simulated by a genuinely blocking open of
// the probe's own FIFO), the probe fails closed within its timeout, releases the
// open itself, leaves no goroutine and no file, and the register omits the field.
func TestStartupProbeFailsClosed(t *testing.T) {
	dir := t.TempDir()
	before := goruntime.NumGoroutine()
	blocking := func(r *os.Root, name string) (*os.File, error) { return r.OpenFile(name, os.O_RDONLY, 0) }
	started := time.Now()
	err := probeNonBlockingOpen(dir, blocking, previewProbeTimeout)
	if err == nil {
		t.Fatal("a blocking open must fail the probe")
	}
	if d := time.Since(started); d > time.Second {
		t.Fatalf("the probe took %v", d)
	}
	if entries, _ := os.ReadDir(dir); len(entries) != 0 {
		t.Fatalf("the probe left %d entries behind", len(entries))
	}
	deadline := time.Now().Add(2 * time.Second)
	for goruntime.NumGoroutine() > before && time.Now().Before(deadline) {
		time.Sleep(10 * time.Millisecond)
	}
	if n := goruntime.NumGoroutine(); n > before {
		t.Fatalf("%d goroutines left behind by the probe", n-before)
	}

	cfg := &config.Config{Server: ServerURLFixture(), Node: config.NodeConfig{Name: "n"}}
	m := New(cfg, &config.Credentials{NodeID: uuid.New()}, runtime.NewRegistry(nil), systeminfo.Info{
		Hostname: "h", OS: "linux", OSVersion: "1", Architecture: "amd64", RunUser: "agentd",
	}, "1.0.0")
	m.preview.probe = func() error { return probeNonBlockingOpen(dir, blocking, previewProbeTimeout) }
	if payload, _ := registerFrame(t, m); payload["binary_preview"] != nil {
		t.Fatal("a failed probe must omit binary_preview")
	}
}
