package files

import (
	"bytes"
	"context"
	"crypto/sha256"
	"io"
	"net"
	"os"
	"path/filepath"
	"sync"
	"sync/atomic"
	"syscall"
	"testing"
	"time"

	"github.com/cliora/cliora/daemon/internal/config"
	"github.com/cliora/cliora/daemon/internal/metrics"
)

// previewWS lays out an allowed root with a workspace and writes the given files.
func previewWS(t *testing.T, files map[string][]byte) (root, ws string) {
	t.Helper()
	base := t.TempDir()
	root = filepath.Join(base, "projects")
	ws = filepath.Join(root, "app")
	if err := os.MkdirAll(ws, 0o755); err != nil {
		t.Fatal(err)
	}
	for rel, body := range files {
		p := filepath.Join(ws, rel)
		if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(p, body, 0o644); err != nil {
			t.Fatal(err)
		}
	}
	return root, ws
}

func bigPool() *PreviewPool { return NewPreviewPool(DefaultPreviewPoolBytes, DefaultPreviewMaxHandles) }

func open(t *testing.T, s *Service, root, ws, rel string) PreviewResult {
	t.Helper()
	res, err := s.PreviewOpen(context.Background(), openWS(t, root, ws), rel, bigPool())
	if err != nil {
		t.Fatalf("PreviewOpen(%s): unexpected error %v", rel, err)
	}
	if !res.Denied && res.Reservation != nil {
		t.Cleanup(res.Reservation.Release)
	}
	return res
}

func wantDenied(t *testing.T, res PreviewResult, code, reason string) {
	t.Helper()
	if !res.Denied || res.Code != code || (reason != "" && res.Reason != reason) {
		t.Fatalf("got denied=%v code=%q reason=%q; want %s/%s", res.Denied, res.Code, res.Reason, code, reason)
	}
	if res.Data != nil || res.Reservation != nil {
		t.Fatal("a denial must carry no bytes and hold no reservation")
	}
}

func wantOpened(t *testing.T, res PreviewResult, mime string) {
	t.Helper()
	if res.Denied {
		t.Fatalf("denied %s/%s; want %s", res.Code, res.Reason, mime)
	}
	if res.Mime != mime || res.Kind != PreviewMimeKind(mime) {
		t.Fatalf("mime=%q kind=%q; want %q", res.Mime, res.Kind, mime)
	}
}

// Step 2 and step 6 are the same SensitiveClassification, called twice. The
// second call is the only thing that stops an innocuous in-root symlink from
// naming a secret (ADR 0029 §3, §7).
func TestPreviewUsesSameSensitivePolicyTwice(t *testing.T) {
	pngBytes := realPNG(t, 4, 4)
	root, ws := previewWS(t, map[string][]byte{
		".env":             pngBytes,
		"id_rsa":           pngBytes,
		".ssh/diagram.png": pngBytes,
		".env.png":         pngBytes,
		"real/.env":        pngBytes,
	})
	if err := os.Symlink(".env", filepath.Join(ws, "photo.png")); err != nil {
		t.Fatal(err)
	}
	s := testService()
	for _, rel := range []string{".env", "id_rsa", ".ssh/diagram.png", ".env.png"} {
		res := open(t, s, root, ws, rel)
		wantDenied(t, res, "FILE_DENIED", "")
		if res.Reason != s.policy.SensitiveClassification(rel) {
			t.Fatalf("%s: reason %q is not the shared policy's %q", rel, res.Reason, s.policy.SensitiveClassification(rel))
		}
	}
	// The request path is clean; only the resolved name is sensitive.
	if s.policy.SensitiveClassification("photo.png") != "" {
		t.Fatal("fixture: photo.png must pass the first check")
	}
	wantDenied(t, open(t, s, root, ws, "photo.png"), "FILE_DENIED", "dotenv")
}

func TestPreviewFollowsInRootSymlinkThenRechecks(t *testing.T) {
	pngBytes := realPNG(t, 8, 6)
	root, ws := previewWS(t, map[string][]byte{"images/ok.png": pngBytes, ".env": []byte("SECRET=1\n")})
	if err := os.Symlink("images/ok.png", filepath.Join(ws, "ok-link.png")); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(".env", filepath.Join(ws, "photo.png")); err != nil {
		t.Fatal(err)
	}
	s := testService()
	res := open(t, s, root, ws, "ok-link.png")
	wantOpened(t, res, "image/png")
	if !bytes.Equal(res.Data, pngBytes) || res.Width != 8 || res.Height != 6 {
		t.Fatal("an in-root symlink must be followed (this open is not O_NOFOLLOW)")
	}
	wantDenied(t, open(t, s, root, ws, "photo.png"), "FILE_DENIED", "dotenv")
}

type countingReader struct {
	r io.Reader
	n *atomic.Int64
}

func (c countingReader) Read(p []byte) (int, error) {
	n, err := c.r.Read(p)
	c.n.Add(int64(n))
	return n, err
}

// Step 8 refuses on the fd's size before reading anything beyond the header.
func TestPreviewNeverReadsBeyondHeaderWhenTooLarge(t *testing.T) {
	big := append(realPNG(t, 2, 2), make([]byte, 9*mib)...)
	pdf := append(tinyPDF(""), make([]byte, 17*mib)...)
	root, ws := previewWS(t, map[string][]byte{"big.png": big, "big.pdf": pdf})
	s := testService()
	var read atomic.Int64
	s.previewHooks = &previewHooks{wrapReader: func(r io.Reader) io.Reader { return countingReader{r, &read} }}
	for rel, limit := range map[string]int64{"big.png": 8 * mib, "big.pdf": 16 * mib} {
		read.Store(0)
		res := open(t, s, root, ws, rel)
		wantDenied(t, res, "FILE_TOO_LARGE", "")
		if res.Limit != limit || res.Size <= limit {
			t.Fatalf("%s: size=%d limit=%d", rel, res.Size, res.Limit)
		}
		if got := read.Load(); got > 64 {
			t.Fatalf("%s: read %d bytes before refusing; must be <= 64", rel, got)
		}
	}
}

func TestPreviewAllowlistIsClosed(t *testing.T) {
	files := map[string][]byte{
		"logo.svg":      []byte(`<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>`),
		"pic.bmp":       append([]byte("BM"), make([]byte, 60)...),
		"pic.tiff":      append([]byte("II*\x00"), make([]byte, 60)...),
		"pic.heic":      append([]byte("\x00\x00\x00\x18ftypheic"), make([]byte, 60)...),
		"a.zip":         append([]byte("PK\x03\x04"), make([]byte, 60)...),
		"notes.txt":     []byte("hello world\n"),
		"empty.png":     {},
		"html.png":      []byte("<!doctype html><script>alert(1)</script>"),
		"svg-named.png": []byte(`<svg xmlns="http://www.w3.org/2000/svg"/>`),
		// Extension says JPEG, content says PDF: content decides.
		"pdf-named.jpg": tinyPDF(""),
		// Extension says nothing at all: content decides.
		"noext": realPNG(t, 2, 2),
	}
	root, ws := previewWS(t, files)
	s := testService()
	for _, rel := range []string{"logo.svg", "pic.bmp", "pic.tiff", "pic.heic", "a.zip", "notes.txt", "empty.png", "html.png", "svg-named.png"} {
		wantDenied(t, open(t, s, root, ws, rel), "FILE_PREVIEW_UNSUPPORTED", "unsupported_type")
	}
	wantOpened(t, open(t, s, root, ws, "pdf-named.jpg"), "application/pdf")
	wantOpened(t, open(t, s, root, ws, "noext"), "image/png")
}

func TestPreviewPixelBombRefused(t *testing.T) {
	root, ws := previewWS(t, map[string][]byte{
		"bomb.png":   headerOnlyPNG(50000, 50000),
		"bomb.jpg":   jpegWithScans(65535, 65535, 1),
		"wide.png":   headerOnlyPNG(8193, 1),
		"bomb.gif":   craftedGIF(65535, 65535, gifFrame(0, 0, 1, 1)),
		"bomb.webp":  webp(vp8xChunk(16384, 16384, 0), vp8lChunk(1, 1)),
		"square.png": headerOnlyPNG(4097, 4096),
	})
	s := testService()
	pool := bigPool()
	for rel, reason := range map[string]string{
		"bomb.png": "pixels", "bomb.jpg": "pixels", "bomb.gif": "pixels", "bomb.webp": "pixels",
		"wide.png": "dimensions", "square.png": "pixels",
	} {
		res, err := s.PreviewOpen(context.Background(), openWS(t, root, ws), rel, pool)
		if err != nil {
			t.Fatal(err)
		}
		wantDenied(t, res, "FILE_PREVIEW_LIMIT", reason)
	}
	if b, n := pool.InUse(); b != 0 || n != 0 {
		t.Fatalf("a refused open left %d bytes / %d slots reserved", b, n)
	}
}

func TestPreviewJPEGScanBomb(t *testing.T) {
	root, ws := previewWS(t, map[string][]byte{
		"scans.jpg": jpegWithScans(64, 64, 1000),
		"ok64.jpg":  jpegWithScans(64, 64, 64),
		"over.jpg":  jpegWithScans(64, 64, 65),
	})
	s := testService()
	wantDenied(t, open(t, s, root, ws, "scans.jpg"), "FILE_PREVIEW_LIMIT", "complexity")
	wantDenied(t, open(t, s, root, ws, "over.jpg"), "FILE_PREVIEW_LIMIT", "complexity")
	// 64 scans is within the limit; this envelope then fails the standard
	// library's cross-check, which is a malformed file, not a limit.
	if res := open(t, s, root, ws, "ok64.jpg"); res.Code == "FILE_PREVIEW_LIMIT" {
		t.Fatalf("64 scans must not trip the scan limit: %+v", res)
	}
}

func TestPreviewSocketAndSymlinkToDevice(t *testing.T) {
	root, ws := previewWS(t, nil)
	// A unix socket path must fit in sun_path (108 bytes); t.TempDir() under the
	// scratch dir can be longer, so bind with a relative name from inside ws.
	wd, _ := os.Getwd()
	if err := os.Chdir(ws); err != nil {
		t.Fatal(err)
	}
	ln, err := net.Listen("unix", "sock.png")
	_ = os.Chdir(wd)
	if err != nil {
		t.Skipf("unix socket unavailable: %v", err)
	}
	defer ln.Close()
	if err := os.Symlink("/dev/zero", filepath.Join(ws, "zero.png")); err != nil {
		t.Fatal(err)
	}
	s := testService()
	wantDenied(t, open(t, s, root, ws, "sock.png"), "FILE_DENIED", "not_regular")
	wantDenied(t, open(t, s, root, ws, "zero.png"), "FILE_DENIED", "outside_root")
}

func TestPreviewFifoRefusedWithoutBlocking(t *testing.T) {
	root, ws := previewWS(t, nil)
	if err := syscall.Mkfifo(filepath.Join(ws, "fifo.png"), 0o600); err != nil {
		t.Skipf("mkfifo: %v", err)
	}
	s := testService()
	done := make(chan PreviewResult, 1)
	go func() { done <- open(t, s, root, ws, "fifo.png") }()
	select {
	case res := <-done:
		wantDenied(t, res, "FILE_DENIED", "not_regular")
	case <-time.After(2 * time.Second):
		releaseFifo(filepath.Join(ws, "fifo.png"))
		t.Fatal("a FIFO preview blocked")
	}
}

func releaseFifo(path string) {
	if w, err := os.OpenFile(path, os.O_WRONLY|syscall.O_NONBLOCK, 0); err == nil {
		_ = w.Close()
	}
}

// Step 3 passes (a regular file), then the path is swapped for a FIFO before the
// open. The non-blocking open returns at once and the fd check refuses it.
func TestPreviewFifoSwappedAfterStat(t *testing.T) {
	root, ws := previewWS(t, map[string][]byte{"swap.png": realPNG(t, 2, 2)})
	target := filepath.Join(ws, "swap.png")
	s := testService()
	s.previewHooks = &previewHooks{afterStat: func() {
		_ = os.Remove(target)
		if err := syscall.Mkfifo(target, 0o600); err != nil {
			t.Errorf("mkfifo: %v", err)
		}
	}}
	t.Cleanup(func() { releaseFifo(target) })
	done := make(chan PreviewResult, 1)
	go func() { done <- open(t, s, root, ws, "swap.png") }()
	select {
	case res := <-done:
		if !res.Denied || (res.Reason != "not_regular" && res.Reason != "changed") {
			t.Fatalf("swapped FIFO: got %+v; want not_regular or changed", res)
		}
	case <-time.After(2 * time.Second):
		releaseFifo(target)
		t.Fatal("the open blocked on a FIFO swapped in after the pre-open Stat")
	}
}

// A regular file replaced by another regular file between Stat and open is
// caught by SameFile.
func TestPreviewRegularFileSwappedAfterStat(t *testing.T) {
	root, ws := previewWS(t, map[string][]byte{"swap.png": realPNG(t, 2, 2), "other.png": realPNG(t, 3, 3)})
	s := testService()
	s.previewHooks = &previewHooks{afterStat: func() {
		_ = os.Rename(filepath.Join(ws, "other.png"), filepath.Join(ws, "swap.png"))
	}}
	wantDenied(t, open(t, s, root, ws, "swap.png"), "FILE_PREVIEW_INVALID", "changed")
}

func TestPreviewChangedDuringRead(t *testing.T) {
	root, ws := previewWS(t, map[string][]byte{"grow.png": realPNG(t, 16, 16)})
	s := testService()
	s.previewHooks = &previewHooks{afterHeader: func() {
		f, err := os.OpenFile(filepath.Join(ws, "grow.png"), os.O_APPEND|os.O_WRONLY, 0)
		if err != nil {
			t.Error(err)
			return
		}
		_, _ = f.Write([]byte("appended"))
		_ = f.Close()
	}}
	wantDenied(t, open(t, s, root, ws, "grow.png"), "FILE_PREVIEW_INVALID", "changed")
}

func TestPreviewDisabledSwitch(t *testing.T) {
	cfg := defaultCfg()
	off := false
	cfg.Filesystem.BinaryPreview.Enabled = &off
	s := NewService(cfg, nil)
	root, ws := previewWS(t, map[string][]byte{"a.png": realPNG(t, 2, 2)})
	if s.PreviewEnabled() {
		t.Fatal("PreviewEnabled must follow the switch")
	}
	var read atomic.Int64
	s.previewHooks = &previewHooks{wrapReader: func(r io.Reader) io.Reader { return countingReader{r, &read} }}
	_, err := s.PreviewOpen(context.Background(), openWS(t, root, ws), "a.png", bigPool())
	if err != ErrPreviewDisabled {
		t.Fatalf("got %v; want ErrPreviewDisabled", err)
	}
	if read.Load() != 0 {
		t.Fatal("a disabled node must not read the file")
	}
	if !testService().PreviewEnabled() {
		t.Fatal("absent switch means enabled (OD-5)")
	}
}

// The text preview is unchanged: the same PNG is still FILE_BINARY on Read.
func TestReadStillDeniesBinary(t *testing.T) {
	pngBytes := realPNG(t, 4, 4)
	root, ws := previewWS(t, map[string][]byte{"a.png": pngBytes})
	s := testService()
	res, err := s.Read(openWS(t, root, ws), "a.png")
	if err != nil {
		t.Fatal(err)
	}
	if !res.Denied || res.Code != "FILE_BINARY" {
		t.Fatalf("Read of a PNG: %+v; want FILE_BINARY", res)
	}
	wantOpened(t, open(t, s, root, ws, "a.png"), "image/png")
}

func TestPreviewSnapshotIsTheValidatedBytes(t *testing.T) {
	pngBytes := withAncillary(realPNG(t, 32, 32), iccpChunk(zlibBytes(t, incompressible(3000, 7), 6)))
	jpg := realJPEG(t, 20, 10)
	gifBytes := realGIF(t, 5, 7)
	web := webp(vp8lChunk(9, 4))
	pdf := tinyPDF("2 0 obj << /Length 0 >> stream\nendstream endobj")
	root, ws := previewWS(t, map[string][]byte{"a.png": pngBytes, "b.jpg": jpg, "c.gif": gifBytes, "d.webp": web, "e.pdf": pdf})
	s := testService()
	for rel, want := range map[string]struct {
		body []byte
		mime string
		w, h int
	}{
		"a.png":  {pngBytes, "image/png", 32, 32},
		"b.jpg":  {jpg, "image/jpeg", 20, 10},
		"c.gif":  {gifBytes, "image/gif", 5, 7},
		"d.webp": {web, "image/webp", 9, 4},
		"e.pdf":  {pdf, "application/pdf", 0, 0},
	} {
		res := open(t, s, root, ws, rel)
		wantOpened(t, res, want.mime)
		if sha256.Sum256(res.Data) != sha256.Sum256(want.body) {
			t.Fatalf("%s: the snapshot differs from the file (only measure, never modify)", rel)
		}
		if res.Width != want.w || res.Height != want.h || res.Size != int64(len(want.body)) {
			t.Fatalf("%s: %dx%d size %d", rel, res.Width, res.Height, res.Size)
		}
		if res.Reservation == nil || res.Reservation.Bytes() != res.Size {
			t.Fatalf("%s: the reservation must equal the snapshot size", rel)
		}
	}
}

// A panic inside a validator is recovered, answered malformed, and counted.
func TestPreviewValidatorPanicIsRecovered(t *testing.T) {
	root, ws := previewWS(t, map[string][]byte{"a.png": realPNG(t, 2, 2)})
	s := testService()
	s.previewHooks = &previewHooks{beforeValidate: func() { panic("boom") }}
	metrics.Reset()
	pool := bigPool()
	res, err := s.PreviewOpen(context.Background(), openWS(t, root, ws), "a.png", pool)
	if err != nil {
		t.Fatal(err)
	}
	wantDenied(t, res, "FILE_PREVIEW_INVALID", "malformed")
	if metrics.CounterValue(metrics.FilesystemPreviewPanicTotal, map[string]string{"kind": "image"}) != 1 {
		t.Fatal("a recovered panic must be counted")
	}
	if b, n := pool.InUse(); b != 0 || n != 0 {
		t.Fatal("a recovered panic must release its reservation")
	}
}

// NODE_BUSY before the full read: two 16 MiB handles fill the pool, and a third
// open of 16 MiB is refused having read nothing past the header.
func TestPreviewPoolReservesInProgressOpens(t *testing.T) {
	pdf16 := append(tinyPDF(""), make([]byte, 16*mib-len(tinyPDF(""))-6)...)
	pdf16 = append(pdf16, []byte("%%EOF\n")...)
	img8 := headerOnlyPNG(16, 16, pngChunk("tEXt", cat([]byte("Pad\x00"), make([]byte, 64))))
	img8 = withPadding(img8, 8*mib)
	root, ws := previewWS(t, map[string][]byte{"a.pdf": pdf16, "b.pdf": pdf16, "c.pdf": pdf16, "x.png": img8, "y.png": img8})
	s := testService()
	pool := bigPool()
	rootH := openWS(t, root, ws)

	first, err := s.PreviewOpen(context.Background(), rootH, "a.pdf", pool)
	if err != nil || first.Denied {
		t.Fatalf("first 16 MiB open: %v %+v", err, first)
	}
	// One 16 MiB snapshot held: two concurrent 8 MiB opens fit exactly (32 MiB).
	var wg sync.WaitGroup
	results := make([]PreviewResult, 2)
	errs := make([]error, 2)
	for i, rel := range []string{"x.png", "y.png"} {
		wg.Add(1)
		go func(i int, rel string) {
			defer wg.Done()
			results[i], errs[i] = s.PreviewOpen(context.Background(), rootH, rel, pool)
		}(i, rel)
	}
	wg.Wait()
	for i := range results {
		if errs[i] != nil || results[i].Denied {
			t.Fatalf("8 MiB open %d: %v %+v", i, errs[i], results[i])
		}
	}
	if b, _ := pool.InUse(); b != 32*mib {
		t.Fatalf("pool holds %d bytes; want exactly 32 MiB", b)
	}
	results[0].Reservation.Release()
	results[1].Reservation.Release()

	second, err := s.PreviewOpen(context.Background(), rootH, "b.pdf", pool)
	if err != nil || second.Denied {
		t.Fatalf("second 16 MiB open: %v %+v", err, second)
	}
	var read atomic.Int64
	s.previewHooks = &previewHooks{wrapReader: func(r io.Reader) io.Reader { return countingReader{r, &read} }}
	if _, err := s.PreviewOpen(context.Background(), rootH, "c.pdf", pool); err != ErrPreviewBusy {
		t.Fatalf("third 16 MiB open: got %v; want ErrPreviewBusy", err)
	}
	if read.Load() > 64 {
		t.Fatalf("a busy refusal read %d bytes; the reservation must precede the full read", read.Load())
	}
	// A refused in-progress open gives its reservation back at once.
	first.Reservation.Release()
	third, err := s.PreviewOpen(context.Background(), rootH, "c.pdf", pool)
	if err != nil || third.Denied {
		t.Fatalf("after a release the pool must have room: %v", err)
	}
	third.Reservation.Release()
	second.Reservation.Release()
	if b, n := pool.InUse(); b != 0 || n != 0 {
		t.Fatalf("pool not empty: %d bytes %d slots", b, n)
	}
}

// withPadding appends a private ancillary chunk so the PNG is exactly size bytes.
func withPadding(p []byte, size int) []byte {
	iend := p[len(p)-12:]
	body := p[:len(p)-12]
	pad := size - len(p) - 12
	return cat(body, pngChunk("paDd", make([]byte, pad)), iend)
}

func TestPreviewConfigLimitsApply(t *testing.T) {
	cfg := defaultCfg()
	cfg.Filesystem.BinaryPreview = config.BinaryPreviewConfig{ImageMaxBytes: 1024, ImageMaxPixels: 100, ImageMaxSide: 20, PDFMaxBytes: 256}
	s := NewService(cfg, nil)
	root, ws := previewWS(t, map[string][]byte{
		"big.png":  withPadding(headerOnlyPNG(4, 4), 2048),
		"many.png": headerOnlyPNG(11, 10),
		"side.png": headerOnlyPNG(21, 1),
		"big.pdf":  append(tinyPDF(""), make([]byte, 300)...),
	})
	wantDenied(t, open(t, s, root, ws, "big.png"), "FILE_TOO_LARGE", "")
	wantDenied(t, open(t, s, root, ws, "many.png"), "FILE_PREVIEW_LIMIT", "pixels")
	wantDenied(t, open(t, s, root, ws, "side.png"), "FILE_PREVIEW_LIMIT", "dimensions")
	wantDenied(t, open(t, s, root, ws, "big.pdf"), "FILE_TOO_LARGE", "")
}

func TestPreviewCancelledContextStopsTheRead(t *testing.T) {
	root, ws := previewWS(t, map[string][]byte{"a.pdf": withPDFSize(8 * mib)})
	s := testService()
	ctx, cancel := context.WithCancel(context.Background())
	s.previewHooks = &previewHooks{afterHeader: cancel}
	pool := bigPool()
	_, err := s.PreviewOpen(ctx, openWS(t, root, ws), "a.pdf", pool)
	if err == nil {
		t.Fatal("a cancelled connection must stop the read")
	}
	if b, n := pool.InUse(); b != 0 || n != 0 {
		t.Fatal("a cancelled read must release its reservation")
	}
}

func withPDFSize(n int) []byte {
	head := tinyPDF("")
	body := append([]byte(nil), head[:len(head)-6]...)
	body = append(body, make([]byte, n-len(head))...)
	return append(body, []byte("%%EOF\n")...)
}
