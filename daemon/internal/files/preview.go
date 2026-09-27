package files

import (
	"context"
	"errors"
	"io"
	"os"
	"time"

	"github.com/cliora/cliora/daemon/internal/config"
	"github.com/cliora/cliora/daemon/internal/metrics"
	"github.com/cliora/cliora/daemon/internal/protocol"
	"github.com/cliora/cliora/daemon/internal/workspace"
)

// Read-only binary preview (ADR 0029, plan/31/03). This file sits beside read.go
// on purpose: the two open sequences should be read side by side. Read returns
// UTF-8 text and denies binary; PreviewOpen returns an allowlisted image or PDF
// and denies everything else. Neither changes the other.

var (
	// ErrPreviewDisabled is the node switch (step 1). It is an error frame, not an
	// in-band denial, because it says nothing about the file.
	ErrPreviewDisabled = errors.New("FILE_PREVIEW_DISABLED")
	// ErrPreviewBusy is the shared snapshot pool refusing a reservation. It is
	// answered immediately as NODE_BUSY, before the full read, never queued.
	ErrPreviewBusy = errors.New("NODE_BUSY")
)

// PreviewChunkSize and the transport bounds are the contract's (1.11.0).
const (
	PreviewChunkSize = protocol.PreviewChunkSize
	previewHeaderLen = 64
	// previewReadBlock bounds each Read of the full snapshot, so a cancelled
	// connection stops the read at the next block boundary.
	previewReadBlock = 256 * 1024
)

// PreviewLimits are the effective, possibly lowered, ceilings (ADR 0029 §4).
type PreviewLimits struct {
	ImageMaxBytes  int64
	ImageMaxPixels int64
	ImageMaxSide   int
	PDFMaxBytes    int64
}

func defaultPreviewLimits() PreviewLimits {
	return PreviewLimits{
		ImageMaxBytes:  config.DefaultPreviewImageMaxBytes,
		ImageMaxPixels: config.DefaultPreviewImageMaxPixels,
		ImageMaxSide:   config.DefaultPreviewImageMaxSide,
		PDFMaxBytes:    config.DefaultPreviewPDFMaxBytes,
	}
}

// previewLimitsFrom fills unset (zero) values with the defaults. Load has done
// this already; a Config built in code (tests, tools) gets the same answer.
func previewLimitsFrom(c config.BinaryPreviewConfig) PreviewLimits {
	l := defaultPreviewLimits()
	if c.ImageMaxBytes > 0 && c.ImageMaxBytes < l.ImageMaxBytes {
		l.ImageMaxBytes = c.ImageMaxBytes
	}
	if c.ImageMaxPixels > 0 && c.ImageMaxPixels < l.ImageMaxPixels {
		l.ImageMaxPixels = c.ImageMaxPixels
	}
	if c.ImageMaxSide > 0 && c.ImageMaxSide < l.ImageMaxSide {
		l.ImageMaxSide = c.ImageMaxSide
	}
	if c.PDFMaxBytes > 0 && c.PDFMaxBytes < l.PDFMaxBytes {
		l.PDFMaxBytes = c.PDFMaxBytes
	}
	return l
}

// PreviewEnabled reports the node switch. node.register omits binary_preview
// when this is false (ADR 0029 §9).
func (s *Service) PreviewEnabled() bool { return s.previewEnabled }

// PreviewResult is the outcome of PreviewOpen. A denial carries a code, a coarse
// reason and, for FILE_TOO_LARGE, size and limit; never content or a path other
// than the one requested. A success carries the validated snapshot and the pool
// reservation that pays for it, which the caller must hand to a PreviewTable or
// Release.
type PreviewResult struct {
	RelPath string

	Denied bool
	Code   string
	Reason string
	Size   int64
	Limit  int64

	Kind       string
	Mime       string
	Width      int
	Height     int
	ModifiedAt time.Time
	Data       []byte

	Reservation *PreviewReservation
}

// previewHooks are test seams. Every hook is a no-op in production (nil).
type previewHooks struct {
	afterStat      func()
	afterHeader    func()
	beforeValidate func()
	wrapReader     func(io.Reader) io.Reader
}

func (h *previewHooks) call(f func(*previewHooks) func()) {
	if h != nil {
		if fn := f(h); fn != nil {
			fn()
		}
	}
}

func deny(rel, code, reason string) PreviewResult {
	return PreviewResult{RelPath: rel, Denied: true, Code: code, Reason: reason}
}

// PreviewOpen runs ADR 0029 §3's eleven steps, default-deny, in a fixed order.
// Step 11 (registering the handle) belongs to the caller's PreviewTable; this
// returns the validated snapshot and its reservation.
//
// It must run off the dispatch loop (step 4 makes the open itself non-blocking,
// but the full read and validation of 16 MiB still take time). ctx is the
// connection's: a dropped connection stops the read at the next block.
func (s *Service) PreviewOpen(
	ctx context.Context, root *workspace.Root, relPath string, pool *PreviewPool,
) (PreviewResult, error) {
	// 1. Node switch.
	if !s.previewEnabled {
		return PreviewResult{}, ErrPreviewDisabled
	}
	// 2. Sensitive policy on the requested path — the same function Read uses.
	if class := s.policy.SensitiveClassification(relPath); class != "" {
		return deny(relPath, "FILE_DENIED", class), nil
	}
	// 3. Pre-open type check. os.Root.Stat follows an in-root symlink and refuses
	// an escaping one, as the open will. Anything that is not a regular file is
	// never opened, so a FIFO, socket or device is spared the open call. Advisory:
	// it races with step 4, and step 5 is the binding check.
	pre, err := root.StatIn(relPath)
	if err != nil {
		if d, ok := denyFromWorkspaceErr(relPath, err); ok {
			return previewDenial(d), nil
		}
		return PreviewResult{}, err
	}
	if !pre.Mode().IsRegular() {
		return deny(relPath, "FILE_DENIED", "not_regular"), nil
	}
	s.previewHooks.call(func(h *previewHooks) func() { return h.afterStat })

	// 4. Confined, non-blocking open (O_NONBLOCK|O_NOCTTY). A FIFO swapped in
	// after step 3 returns at once instead of waiting for a writer.
	f, err := root.OpenFileNonBlocking(relPath)
	if err != nil {
		if d, ok := denyFromWorkspaceErr(relPath, err); ok {
			return previewDenial(d), nil
		}
		return PreviewResult{}, err
	}
	defer f.Close()

	// 5. The binding type check, on the fd; and the fd must be the file step 3
	// looked at.
	info, err := f.Stat()
	if err != nil {
		return PreviewResult{}, workspace.ErrPermision
	}
	if !info.Mode().IsRegular() {
		return deny(relPath, "FILE_DENIED", "not_regular"), nil
	}
	if !os.SameFile(pre, info) {
		return deny(relPath, "FILE_PREVIEW_INVALID", "changed"), nil
	}

	// 6. Sensitive policy again, on the fd's resolved name. The open follows
	// in-root symlinks, so this is what stops photo.png -> .env.
	realRel, err := root.RealRel(f)
	if err != nil {
		return deny(relPath, "FILE_DENIED", "unresolved"), nil
	}
	if class := s.policy.SensitiveClassification(realRel); class != "" {
		return deny(relPath, "FILE_DENIED", class), nil
	}

	var r io.Reader = f
	if s.previewHooks != nil && s.previewHooks.wrapReader != nil {
		r = s.previewHooks.wrapReader(f)
	}

	// 7. Header from the same fd; the content decides the type.
	header := make([]byte, previewHeaderLen)
	n, err := io.ReadFull(r, header)
	if err != nil && !errors.Is(err, io.ErrUnexpectedEOF) && !errors.Is(err, io.EOF) {
		return PreviewResult{}, workspace.ErrPermision
	}
	header = header[:n]
	mime := sniffPreviewMime(header)
	if mime == "" {
		return deny(relPath, "FILE_PREVIEW_UNSUPPORTED", "unsupported_type"), nil
	}
	kind := PreviewMimeKind(mime)

	// 8. Kind-specific size cap on the fd's size. Nothing beyond the header has
	// been read, and nothing will be if this refuses.
	size := info.Size()
	limit := s.previewLimits.ImageMaxBytes
	if kind == "pdf" {
		limit = s.previewLimits.PDFMaxBytes
	}
	if size > limit {
		d := deny(relPath, "FILE_TOO_LARGE", "too_large")
		d.Size, d.Limit = size, limit
		return d, nil
	}
	// The shared pool is reserved BEFORE the full read: snapshots held plus reads
	// in progress never exceed it. No room is NODE_BUSY, not a queue.
	reservation, ok := pool.Reserve(size)
	if !ok {
		return PreviewResult{}, ErrPreviewBusy
	}
	release := true
	defer func() {
		if release {
			reservation.Release()
		}
	}()
	s.previewHooks.call(func(h *previewHooks) func() { return h.afterHeader })

	// 9. Bounded read of the whole file from the same fd, then re-stat: reading
	// more or fewer bytes than fstat said, or a changed size/mtime, means the
	// bytes about to be validated are not a stable file.
	data, err := readSnapshot(ctx, r, header, size, limit)
	if err != nil {
		return PreviewResult{}, err
	}
	if int64(len(data)) != size {
		return deny(relPath, "FILE_PREVIEW_INVALID", "changed"), nil
	}
	after, err := f.Stat()
	if err != nil {
		return PreviewResult{}, workspace.ErrPermision
	}
	if after.Size() != size || !after.ModTime().Equal(info.ModTime()) {
		return deny(relPath, "FILE_PREVIEW_INVALID", "changed"), nil
	}

	// 10. Structural validation of exactly these bytes. A validator panic is a
	// malformed file, recovered here so one bad file cannot take the node down.
	verdict := s.validateRecovered(mime, data)
	if verdict.code != "" {
		return deny(relPath, verdict.code, verdict.reason), nil
	}

	// 11 happens in the caller: the snapshot and its reservation move to a handle.
	release = false
	return PreviewResult{
		RelPath:     relPath,
		Kind:        kind,
		Mime:        mime,
		Width:       verdict.width,
		Height:      verdict.height,
		Size:        size,
		ModifiedAt:  info.ModTime().UTC(),
		Data:        data,
		Reservation: reservation,
	}, nil
}

func (s *Service) validateRecovered(mime string, data []byte) (v previewVerdict) {
	defer func() {
		if recover() != nil {
			metrics.Increment(metrics.FilesystemPreviewPanicTotal, map[string]string{"kind": PreviewMimeKind(mime)})
			v = previewVerdict{code: "FILE_PREVIEW_INVALID", reason: "malformed"}
		}
	}()
	s.previewHooks.call(func(h *previewHooks) func() { return h.beforeValidate })
	return validatePreviewBytes(mime, data, s.previewLimits)
}

// readSnapshot reads the rest of the file after the header, never more than
// limit+1 bytes in total, checking ctx between blocks.
func readSnapshot(ctx context.Context, r io.Reader, header []byte, size, limit int64) ([]byte, error) {
	capacity := size
	if capacity < int64(len(header)) {
		capacity = int64(len(header))
	}
	data := make([]byte, len(header), capacity+1)
	copy(data, header)
	rest := io.LimitReader(r, limit+1-int64(len(header)))
	for {
		if err := ctx.Err(); err != nil {
			return nil, err
		}
		if len(data) == cap(data) {
			// size+1 bytes read: one byte past fstat's size proves the file grew.
			return data, nil
		}
		end := min(cap(data), len(data)+previewReadBlock)
		n, err := rest.Read(data[len(data):end])
		data = data[:len(data)+n]
		if errors.Is(err, io.EOF) {
			return data, nil
		}
		if err != nil {
			return nil, workspace.ErrPermision
		}
	}
}

// previewDenial adapts a read-path workspace denial to a preview result.
func previewDenial(d ReadResult) PreviewResult {
	return deny(d.RelPath, d.Code, d.Reason)
}

// PreviewMimeKind maps a wire mime to its kind ("image" or "pdf").
func PreviewMimeKind(mime string) string {
	return protocol.PreviewMimes[mime]
}

// ChunkCount is ceil(size / PreviewChunkSize), at least 1.
func ChunkCount(size int64) int {
	if size <= 0 {
		return 1
	}
	return int((size + PreviewChunkSize - 1) / PreviewChunkSize)
}
