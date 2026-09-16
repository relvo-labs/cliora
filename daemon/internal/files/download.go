package files

import (
	"io"
	"time"

	"github.com/cliora/cliora/daemon/internal/workspace"
)

// Workspace file download (ADR 0028, FR-FILE-011): the one path by which bytes
// leave a workspace for a browser.
//
// It is the read path's sibling, not its extension, and the difference is one
// question: Read answers "can this be shown in an editor", Download answers "can
// this be handed over as-is". Those have different correct answers for the same
// file, in both directions:
//
//	a 300 KiB PNG   - Read denies it (binary), Download allows it
//	a 3 MiB .env    - Read denies it (sensitive), Download denies it too
//
// So binary detection is absent here and the sensitive-file policy is not. That
// is the whole of the delta, and it is worth stating as a rule rather than as a
// list of steps:
//
//	the platform does not hand over a file it would refuse to show you,
//	but it will hand over one it merely cannot render.
//
// The first half is what keeps this path from becoming a way to read .env by
// asking for it differently - which is exactly what a `raw: true` flag on
// filesystem.read would have been.

// DownloadResult is the outcome of a download. Unlike ReadResult there is no
// Denied field: a refusal on this path is an error frame, not an in-band body.
// A preview denial has a pane to render itself into; a download's HTTP body is
// the file, so there is nowhere for a denial to live except the status line.
type DownloadResult struct {
	RelPath    string
	Size       int64
	ModifiedAt time.Time
	Content    []byte
}

// downloadDenial is a refusal carrying the wire code the caller must answer
// with. It is an error type rather than a result flag for the reason above.
type downloadDenial struct {
	code   string
	reason string
}

func (d *downloadDenial) Error() string { return d.code }

// DownloadCode returns the wire error code and coarse reason for a download
// refusal, and "" if err is not one. The handler uses it to answer with a
// specific code instead of collapsing every refusal into INTERNAL_ERROR, which
// would tell a user whose file is too large that the server broke.
func DownloadCode(err error) (code, reason string) {
	if d, ok := err.(*downloadDenial); ok {
		return d.code, d.reason
	}
	return "", ""
}

// DownloadEnabled reports whether this node hands workspace files back. Central
// caches the answer from node.register; the daemon re-checks on every request
// because a cached posture is a stale posture (same shape as UploadEnabled).
func (s *Service) DownloadEnabled() bool { return s.download.DownloadEnabled() }

// Download reads one file for delivery to a browser, in the same default-deny
// order as Read and for the same reason - each step is cheap and each one is a
// precondition of the next:
//
//  1. node switch
//  2. sensitive-name deny on the requested path, before anything is opened
//  3. confined O_NOFOLLOW open (ADR 0014)
//  4. regular-file check on the open fd, not on the path
//  5. sensitive-name deny on the fd's RESOLVED name, binding the decision to
//     the opened inode
//  6. size cap from the fd's snapshot size
//  7. bounded read from that same fd
//
// Steps 2 and 5 are the same check twice on purpose, and dropping either one
// breaks it: without 2 the platform opens files it has already decided not to
// serve, and without 5 an innocuously-named in-root symlink pointing at an
// in-root .env is downloadable.
//
// There is deliberately no step between 7 and returning. Read has one - the
// binary/encoding classification - and its absence here is the feature.
func (s *Service) Download(root *workspace.Root, relPath string) (DownloadResult, error) {
	if !s.download.DownloadEnabled() {
		return DownloadResult{}, &downloadDenial{code: "FILE_DOWNLOAD_DISABLED", reason: "disabled"}
	}

	// 2. The read path's policy, unchanged and called rather than copied: two
	// copies of a sensitive-file list are two lists to keep in step, and they
	// would not stay in step.
	if class := s.policy.SensitiveClassification(relPath); class != "" {
		return DownloadResult{}, &downloadDenial{code: "FILE_DENIED", reason: class}
	}

	// 3. Confined open, refusing a symlink final component.
	f, err := root.OpenFile(relPath)
	if err != nil {
		if denial, ok := denialFromWorkspaceErr(err); ok {
			return DownloadResult{}, denial
		}
		return DownloadResult{}, err
	}
	defer f.Close()

	// 4. Regular-file check on the fd. A directory, a FIFO or a device node is
	// not a download; a FIFO in particular would block the read forever.
	info, err := f.Stat()
	if err != nil {
		return DownloadResult{}, workspace.ErrPermision
	}
	if !info.Mode().IsRegular() {
		return DownloadResult{}, &downloadDenial{code: "FILE_DENIED", reason: "not_regular"}
	}
	size := info.Size()
	mtime := info.ModTime().UTC()

	// 5. Sensitive check on the resolved name, binding the decision to the inode
	// that was actually opened. Unresolvable means deny, not allow.
	realRel, resErr := root.RealRel(f)
	if resErr != nil {
		return DownloadResult{}, &downloadDenial{code: "FILE_DENIED", reason: "unresolved"}
	}
	if class := s.policy.SensitiveClassification(realRel); class != "" {
		return DownloadResult{}, &downloadDenial{code: "FILE_DENIED", reason: class}
	}

	// 6. Size cap. This is a frame-budget fact before it is a policy: the wire
	// caps `data` at the base64 length of this many bytes, so a larger file
	// cannot be answered at all, and refusing it here gives the user a code and
	// a next step instead of a timeout.
	maxBytes := s.download.MaxBytes
	if size > maxBytes {
		return DownloadResult{}, &downloadDenial{code: "FILE_TOO_LARGE", reason: "oversize"}
	}

	// 7. Bounded read from the same fd - never more than the cap even if the
	// file grew between the stat and here.
	content, err := io.ReadAll(io.LimitReader(f, maxBytes))
	if err != nil {
		return DownloadResult{}, workspace.ErrPermision
	}

	return DownloadResult{
		RelPath:    relPath,
		Size:       int64(len(content)),
		ModifiedAt: mtime,
		Content:    content,
	}, nil
}

// denialFromWorkspaceErr is denyFromWorkspaceErr's counterpart for this path.
// Same mapping, different carrier: outside-root still collapses to FILE_DENIED
// so the browser cannot probe for the existence of paths outside the workspace
// (ADR 0014).
func denialFromWorkspaceErr(err error) (*downloadDenial, bool) {
	res, ok := denyFromWorkspaceErr("", err)
	if !ok {
		return nil, false
	}
	return &downloadDenial{code: res.Code, reason: res.Reason}, true
}
