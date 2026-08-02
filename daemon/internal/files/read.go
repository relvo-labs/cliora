package files

import (
	"errors"
	"io"

	"github.com/cliora/cliora/daemon/internal/workspace"
)

// Read previews a single file under the workspace root, applying the P3 policy
// in a fixed, default-deny order (tech §11.5): sensitive-name deny → confined
// O_NOFOLLOW open → regular-file check on the open fd → size cap → bounded read
// → binary/undetermined deny. On any denial it returns a ReadResult with Denied
// set and only a safe classification — never file content or an absolute path.
// A denial is not an error; only unexpected failures return err.
func (s *Service) Read(root *workspace.Root, relPath string) (ReadResult, error) {
	// 1. Sensitive-name deny before opening or reading anything (SEC-004).
	if class := s.policy.SensitiveClassification(relPath); class != "" {
		return ReadResult{RelPath: relPath, Denied: true, Code: "FILE_DENIED", Reason: class}, nil
	}

	// 2. Open confined, refusing a symlink final component (ADR 0014). Any
	// path/containment problem becomes a safe in-band denial (the browser always
	// renders a denial pane); only truly unexpected failures return err.
	f, err := root.OpenFile(relPath)
	if err != nil {
		if denied, ok := denyFromWorkspaceErr(relPath, err); ok {
			return denied, nil
		}
		return ReadResult{}, err
	}
	defer f.Close()

	// 3. Regular-file check on the open fd (not the path).
	info, err := f.Stat()
	if err != nil {
		return ReadResult{}, workspace.ErrPermision
	}
	if !info.Mode().IsRegular() {
		return ReadResult{RelPath: relPath, Denied: true, Code: "FILE_DENIED", Reason: "not_regular"}, nil
	}
	size := info.Size()
	mtime := info.ModTime().UTC()

	// 3b. Sensitive check on the fd's RESOLVED name, binding the decision to the
	// opened inode. This closes the bypass where an innocuously-named in-root
	// symlink points at a sensitive in-root file (ADR 0014). If the real name
	// cannot be resolved, deny (default-deny) rather than risk serving it.
	realRel, resErr := root.RealRel(f)
	if resErr != nil {
		return ReadResult{RelPath: relPath, Denied: true, Code: "FILE_DENIED", Reason: "unresolved"}, nil
	}
	if class := s.policy.SensitiveClassification(realRel); class != "" {
		return ReadResult{RelPath: relPath, Denied: true, Code: "FILE_DENIED", Reason: class}, nil
	}

	// 4. Size cap using the fd's snapshot size (FR-FILE-003).
	if size > s.maxPreview {
		return ReadResult{RelPath: relPath, Denied: true, Code: "FILE_TOO_LARGE", Size: size, ModifiedAt: mtime}, nil
	}

	// 5. Bounded read from the same fd (never more than the cap, even if the
	// file grew after the stat).
	content, err := io.ReadAll(io.LimitReader(f, s.maxPreview))
	if err != nil {
		return ReadResult{}, workspace.ErrPermision
	}

	// 6. Binary / undetermined deny (default-deny for non-text, ADR 0015).
	// The whole bounded buffer is classified, not a prefix window — see
	// Classify. A non-UTF-8 text file is denied under the same wire code but
	// with a distinct reason, because "transcode it" and "give up" are
	// different next steps for the user (FR-FILE-004 note, FR-FILE-008).
	switch verdict, mime := Classify(content); verdict {
	case VerdictBinary:
		return ReadResult{RelPath: relPath, Denied: true, Code: "FILE_BINARY", Reason: "binary", Mime: mime, Size: size, ModifiedAt: mtime}, nil
	case VerdictUnsupportedEncoding:
		return ReadResult{RelPath: relPath, Denied: true, Code: "FILE_BINARY", Reason: "unsupported_encoding", Mime: mime, Size: size, ModifiedAt: mtime}, nil
	}

	// 7. Success: bounded UTF-8 text preview.
	return ReadResult{
		RelPath:    relPath,
		Size:       size,
		ModifiedAt: mtime,
		Encoding:   "utf-8",
		Language:   LanguageHint(relPath),
		Content:    string(content),
	}, nil
}

// denyFromWorkspaceErr maps a workspace path/containment error to a safe in-band
// preview denial. outside-root collapses to FILE_DENIED so the browser cannot
// probe for the existence of paths outside the workspace (ADR 0014).
func denyFromWorkspaceErr(relPath string, err error) (ReadResult, bool) {
	base := ReadResult{RelPath: relPath, Denied: true}
	switch {
	case errors.Is(err, workspace.ErrNotFound):
		base.Code, base.Reason = "FILE_NOT_FOUND", "not_found"
	case errors.Is(err, workspace.ErrPermision):
		base.Code, base.Reason = "FILE_PERMISSION_DENIED", "permission"
	case errors.Is(err, workspace.ErrOutside):
		base.Code, base.Reason = "FILE_DENIED", "outside_root"
	case errors.Is(err, workspace.ErrNotDir):
		base.Code, base.Reason = "FILE_DENIED", "not_regular"
	case errors.Is(err, workspace.ErrInvalid):
		base.Code, base.Reason = "FILE_DENIED", "invalid"
	default:
		return ReadResult{}, false
	}
	return base, true
}
