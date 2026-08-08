package files

import (
	"errors"
	"log/slog"
	"os"
	"path"
	"sync"
	"syscall"
	"time"

	"github.com/cliora/cliora/daemon/internal/workspace"
)

// storeMode is the mode every uploaded file lands with. Fixed, never configurable
// and never copied from the source: a file dragged in from a browser should not
// arrive executable, and `chmod +x` is a decision a user should make knowingly
// (ADR 0026 §1.3).
const storeMode os.FileMode = 0o644

// StoreResult is the outcome of one file upload. On denial Denied is true and
// Code carries the reason; RelPath is set only on success. A denial is not an
// error — only unexpected failures return err — the same contract as Read and
// SaveImage, so the three read side by side.
type StoreResult struct {
	RelPath    string
	Size       int64
	ModifiedAt time.Time

	Denied bool
	Code   string
	Reason string
}

// storeUsage is the in-memory quota for one session. There is nothing to recount
// from on this path: unlike image drop, the files land wherever the user chose,
// so the filesystem holds no record of what the platform put there (ADR 0026 §5).
//
// The cost is that a daemon restart resets it, and that is acceptable because of
// what this ceiling is for: it bounds a broken client, not a determined user. A
// determined user holds terminal.operate on the same node and can write files
// directly. The risk that actually needs a durable guard — filling the disk — is
// held by the free-space floor, which needs no memory.
type storeUsage struct {
	day   string
	bytes int64
	count int
}

// storeQuota tracks per-session usage. Safe for concurrent use; the map is small
// (one entry per session that has uploaded today) and pruned on the day roll.
type storeQuota struct {
	mu     sync.Mutex
	perDay map[string]*storeUsage
}

func newStoreQuota() *storeQuota { return &storeQuota{perDay: map[string]*storeUsage{}} }

// reserve records an upload of size bytes against sessionID, or reports which
// ceiling it would cross. It is called after the content has been accepted and
// before anything touches the filesystem, so a refusal costs nothing.
func (q *storeQuota) reserve(sessionID string, size int64, now time.Time, maxBytes int64, maxFiles int) bool {
	day := now.UTC().Format("2006-01-02")
	q.mu.Lock()
	defer q.mu.Unlock()
	u := q.perDay[sessionID]
	if u == nil || u.day != day {
		// A new day resets both counters. Dropping the stale entry rather than
		// keeping a per-day history is deliberate: nothing reads yesterday.
		u = &storeUsage{day: day}
		q.perDay[sessionID] = u
	}
	if u.bytes+size > maxBytes || u.count+1 > maxFiles {
		return false
	}
	u.bytes += size
	u.count++
	return true
}

// release undoes a reservation when the write itself fails, so a node that
// cannot write does not also lose its quota.
func (q *storeQuota) release(sessionID string, size int64, now time.Time) {
	day := now.UTC().Format("2006-01-02")
	q.mu.Lock()
	defer q.mu.Unlock()
	if u := q.perDay[sessionID]; u != nil && u.day == day {
		u.bytes -= size
		u.count--
		if u.bytes < 0 {
			u.bytes = 0
		}
		if u.count < 0 {
			u.count = 0
		}
	}
}

// FileUploadEnabled reports whether this node accepts general file upload.
// Central asks at registration so the console can hide an entry point rather
// than offer a control that always fails (ADR 0024 W4, ADR 0026 §9).
func (s *Service) FileUploadEnabled() bool { return s.upload.Files.FileUploadEnabled() }

// Store writes one uploaded file into the workspace at a caller-chosen location
// and returns its workspace-relative path.
//
// The order of checks is fixed and default-deny, the same discipline as Read and
// SaveImage: cheapest and most decisive first, and nothing touches the
// filesystem until the request has been accepted.
//
// The single most important property is step 8: the file is created with O_EXCL
// under its FINAL name. Because this path never replaces an existing byte, it
// needs no version precondition, no trash can and no undo — which is the whole
// reason it is this small (ADR 0026 §3).
func (s *Service) Store(root *workspace.Root, dir, name string, data []byte, now time.Time) (StoreResult, error) {
	// 1. Disabled by the node (W4).
	if !s.upload.Files.FileUploadEnabled() {
		return StoreResult{Denied: true, Code: "FILE_UPLOAD_DISABLED"}, nil
	}
	// 2. Size. Central checked this too; Central is not the only conceivable
	// caller, and the daemon owns the resource being consumed.
	if int64(len(data)) > s.upload.MaxBytes {
		return StoreResult{Denied: true, Code: "FILE_UPLOAD_TOO_LARGE"}, nil
	}
	// 3. Where and under what name (store_policy.go). No filesystem access yet.
	if reason := s.StorableClassification(dir, name, VerbStore); reason != "" {
		return StoreResult{Denied: true, Code: "FILE_DENIED", Reason: reason}, nil
	}
	cleanDir, ok := cleanStoreDir(dir)
	if !ok {
		return StoreResult{Denied: true, Code: "FILE_DENIED", Reason: "invalid"}, nil
	}
	finalRel := name
	if cleanDir != "." {
		finalRel = path.Join(cleanDir, name)
	}
	// There is deliberately no content check here. Image drop sniffs magic
	// numbers because it must guarantee the CLI can read the result; a general
	// upload carries no such promise, and a user putting a .tar.gz in their own
	// workspace is not the platform's business. What stands in for a type check
	// is step 3 (the name must pass policy) and step 8's fixed 0644.

	// 4. Cumulative quota (W2's first two legs; the third is visibility, not
	// retention — see storeUsage and ADR 0026 §5).
	sessionKey := root.Canonical()
	if !s.storeQuota.reserve(sessionKey, int64(len(data)), now,
		s.upload.Files.MaxSessionBytes, s.upload.Files.MaxFilesPerDay) {
		return StoreResult{Denied: true, Code: "FILE_UPLOAD_QUOTA_EXCEEDED"}, nil
	}
	released := false
	releaseQuota := func() {
		if !released {
			s.storeQuota.release(sessionKey, int64(len(data)), now)
			released = true
		}
	}

	// 5. Free space. This is what replaces a retention period on this path: it
	// addresses disk exhaustion directly instead of by expiry. Twice the file size
	// as well as the floor, because this figure is a snapshot taken before the
	// write and the disk has other writers — accepting a file that exactly fits
	// would mean landing it with nothing left.
	if floor := s.upload.Files.MinFree(); floor > 0 {
		free, err := s.freeBytes(root.Canonical())
		switch {
		case err != nil:
			// The one fail-open check in this function, and it is deliberate:
			// this is an auxiliary guard against filling a disk, not a security
			// boundary, and letting a statfs failure refuse every upload would be
			// treating it as one. Loud rather than silent.
			slog.Warn("free space check unavailable",
				"event", "filesystem.store_freespace_unknown", "error", err.Error())
		case free < floor || free < 2*int64(len(data)):
			releaseQuota()
			return StoreResult{Denied: true, Code: "FILE_UPLOAD_NO_SPACE"}, nil
		}
	}

	// 6. The destination directory must already exist and be a real directory.
	// Lstat before Stat: os.Root follows in-root symlinks, so `datasets ->
	// elsewhere-in-root` would otherwise redirect where the file lands. This is
	// the write-side counterpart of the read path's RealRel check.
	if cleanDir != "." {
		info, err := root.LstatIn(cleanDir)
		if err != nil {
			releaseQuota()
			if denied, ok := denyStoreFromWorkspaceErr(err, "dir_missing"); ok {
				return denied, nil
			}
			return StoreResult{}, err
		}
		if info.Mode()&os.ModeSymlink != 0 {
			releaseQuota()
			return StoreResult{Denied: true, Code: "FILE_DENIED", Reason: "dir_symlink"}, nil
		}
		if !info.IsDir() {
			releaseQuota()
			return StoreResult{Denied: true, Code: "FILE_DENIED", Reason: "dir_not_directory"}, nil
		}
	}

	// 7. Nothing may already be called that. This step does not provide the
	// guarantee — step 8's O_EXCL does — it provides the right ERROR: a failed
	// CreateExclusive only says EEXIST, and "there is a file there" and "there is
	// a directory there" need different wording.
	if info, err := root.LstatIn(finalRel); err == nil {
		releaseQuota()
		reason := "file_exists"
		if info.IsDir() {
			reason = "directory_exists"
		}
		return StoreResult{Denied: true, Code: "FILE_EXISTS", Reason: reason}, nil
	} else if !errors.Is(err, workspace.ErrNotFound) {
		releaseQuota()
		if denied, ok := denyStoreFromWorkspaceErr(err, "invalid"); ok {
			return denied, nil
		}
		return StoreResult{}, err
	}

	// 8. Create the file under its FINAL name with O_EXCL, then write it.
	//
	// Not a temp file plus rename, and this is the one place where copying image
	// drop's shape would have been wrong: `renameat` REPLACES its destination,
	// and os.Root exposes no RENAME_NOREPLACE, so temp-then-rename would quietly
	// clobber a file that appeared after step 7 — losing the one guarantee this
	// whole path is built on. Image drop can afford rename because it invents a
	// ULID name that cannot already exist; here the name comes from the client.
	//
	// The accepted cost is that the name becomes visible before the bytes are
	// complete. It is bounded: one Write of at most 4 MiB to a local file, and
	// every handled failure below removes the file again — we know nothing was
	// there before, because O_EXCL succeeded. Only an abrupt kill can leave a
	// short file, and that is a far smaller hazard than replacing a file the user
	// still needs.
	f, err := root.CreateExclusive(finalRel, 0o600)
	if err != nil {
		releaseQuota()
		if errors.Is(err, workspace.ErrExists) {
			// Someone created that name between step 7 and here. Losing that race
			// must read as a collision, not as a broken node.
			return StoreResult{Denied: true, Code: "FILE_EXISTS", Reason: "file_exists"}, nil
		}
		if denied, ok := denyStoreFromWorkspaceErr(err, "create"); ok {
			return denied, nil
		}
		return StoreResult{}, err
	}
	if err := writeSyncChmod(f, data, storeMode); err != nil {
		// We created it, so removing it is ours to do — and leaving a truncated
		// file under a name the user will try again is worse than removing it.
		_ = root.RemoveIn(finalRel)
		releaseQuota()
		return StoreResult{}, err
	}
	return StoreResult{
		RelPath:    finalRel,
		Size:       int64(len(data)),
		ModifiedAt: now.UTC(),
	}, nil
}

// writeSyncChmod writes data, flushes it, and fixes the mode.
//
// The mode is set through the file's own descriptor (fchmod) rather than by
// path, for two reasons: Go's own documentation records that os.Root.Chmod races
// on Unix if the target is swapped for a symlink mid-call, and fchmod is not
// subject to the process umask, so the resulting mode is exactly storeMode
// rather than storeMode masked by whatever agentd inherited.
func writeSyncChmod(f *os.File, data []byte, mode os.FileMode) error {
	defer f.Close()
	if _, err := f.Write(data); err != nil {
		return err
	}
	if err := f.Sync(); err != nil {
		return err
	}
	return f.Chmod(mode)
}

// denyStoreFromWorkspaceErr maps a workspace path/containment error to a safe
// in-band refusal. outside-root collapses to FILE_DENIED so the browser cannot
// probe for paths outside the workspace (ADR 0014).
func denyStoreFromWorkspaceErr(err error, invalidReason string) (StoreResult, bool) {
	base := StoreResult{Denied: true}
	switch {
	case errors.Is(err, workspace.ErrNotFound):
		base.Code, base.Reason = "FILE_NOT_FOUND", invalidReason
	case errors.Is(err, workspace.ErrExists):
		base.Code, base.Reason = "FILE_EXISTS", "file_exists"
	case errors.Is(err, workspace.ErrPermision):
		base.Code, base.Reason = "FILE_PERMISSION_DENIED", "permission"
	case errors.Is(err, workspace.ErrOutside):
		base.Code, base.Reason = "FILE_DENIED", "outside_root"
	case errors.Is(err, workspace.ErrNotDir):
		base.Code, base.Reason = "FILE_DENIED", "dir_not_directory"
	case errors.Is(err, workspace.ErrInvalid):
		base.Code, base.Reason = "FILE_DENIED", "invalid"
	default:
		return StoreResult{}, false
	}
	return base, true
}

// FreeBytes is statfsFreeBytes exported for `agentd doctor`, which has no
// Service (it runs without a session) but asks the same question of each allowed
// root.
func FreeBytes(path string) (int64, error) { return statfsFreeBytes(path) }

// statfsFreeBytes reports the space available on the filesystem holding path.
//
// Bavail, not Bfree: the difference is the reserve ext4 keeps for root (measured
// at 7.9 GiB on the machine this was written on), and agentd runs non-root
// (ADR 0023), so it cannot use those blocks. Using Bfree would overstate free
// space by exactly the amount that is unavailable.
//
// syscall.Statfs is stdlib on Linux, so this adds no dependency — the daemon has
// six direct ones and that is a property worth keeping.
func statfsFreeBytes(path string) (int64, error) {
	var st syscall.Statfs_t
	if err := syscall.Statfs(path, &st); err != nil {
		return 0, err
	}
	return int64(st.Bavail) * st.Bsize, nil
}
