package files

import (
	"encoding/base64"
	"errors"
	"io/fs"
	"os"
	"path"
	"strings"
	"time"

	"github.com/cliora/cliora/daemon/internal/workspace"
)

// Platform context projection (ADR 0028, contract 1.10.0).
//
// The second write verb, and its whole reason for existing is that the first one
// cannot do this: `VerbStore` refuses everything under `.cliora/` (store_policy.go),
// and the store path requires the destination directory to already exist while the
// protocol has no mkdir at all. Relaxing either for the user-facing verb would let
// any holder of `file.upload` overwrite the context pack — or the session credential.
//
// The two verbs' writable sets are **disjoint**, in both directions:
//
//	VerbStore    anywhere under the workspace EXCEPT .cliora/
//	VerbProject  ONLY .cliora/{context,process,reference}/
//
// and neither ever replaces a byte. `.cliora/uploads/` and `.cliora/.gitignore` belong
// to image drop and to the user; the projection is refused there as firmly as the user
// is refused in `context/`.

const (
	contextDir   = clioraDir + "/context"
	processDir   = clioraDir + "/process"
	referenceDir = clioraDir + "/reference"

	// projectFileMode is fixed, not configurable. The context pack and the session
	// credential are read by the agent running as the workspace's owner and by nobody
	// else; a group- or world-readable credential file would be a different decision
	// than the one ADR 0028 records.
	projectFileMode os.FileMode = 0o600
	projectDirMode  os.FileMode = 0o700

	// maxProjectFileBytes mirrors the wire schema's per-file cap (64 KiB). Checked
	// here as well because Central is not the only conceivable caller (SEC-001).
	maxProjectFileBytes = 64 * 1024
	maxProjectFiles     = 32
)

// ProjectFile is one file to write, as it arrives on the wire.
type ProjectFile struct {
	Path string `json:"path"`
	Mode string `json:"mode"`
	Data string `json:"data"`
}

// ProjectResult reports what landed and what was already there.
//
// `Skipped` is not a failure list. A process-notes directory that already exists means
// a second session in the same workspace found the same version already projected, and
// treating that as success is what lets this path keep `O_EXCL` with no overwrite flag
// anywhere in the protocol (ADR 0028 sec 2).
type ProjectResult struct {
	Written []string `json:"written"`
	Skipped []string `json:"skipped"`
	Bytes   int64    `json:"bytes"`

	Denied bool   `json:"-"`
	Code   string `json:"-"`
	Reason string `json:"-"`
}

// ProjectableClassification returns "" if the platform may write at rel, or a coarse
// refusal reason.
//
// Deliberately not a relaxed copy of StorableClassification: the answers are per-verb
// (see the `Verb` type), and the only thing the two share is the git rule — which is
// called rather than restated, because two copies of a security check are two copies
// to keep in step.
func (s *Service) ProjectableClassification(rel string) string {
	clean := path.Clean(rel)
	if clean != rel || strings.HasPrefix(clean, "/") || strings.HasPrefix(clean, "~") {
		return "invalid"
	}
	if strings.ContainsRune(rel, 0) {
		return "invalid"
	}
	for _, seg := range strings.Split(clean, "/") {
		if seg == "" || seg == "." || seg == ".." {
			return "invalid"
		}
		if reason := classifyFilename(seg); reason != "" {
			return reason
		}
	}
	if reason := classifyGitPath(clean); reason != "" {
		return reason
	}
	// The whole allowance, stated once. Everything else — including `.cliora` itself,
	// `.cliora/uploads/…` and `.cliora/.gitignore` — falls through to the refusal.
	switch {
	case strings.HasPrefix(clean, contextDir+"/"),
		strings.HasPrefix(clean, processDir+"/"),
		strings.HasPrefix(clean, referenceDir+"/"):
		return ""
	}
	return "not_platform_owned"
}

// Project writes the platform's files into `.cliora/`.
//
// Ordering matters and mirrors Store: judge the paths before touching the filesystem,
// bind the `.cliora` decision to what is actually on disk (Lstat, not Stat — os.Root
// follows in-root symlinks, so `.cliora -> elsewhere` would otherwise redirect every
// write), then create each file under its final name with O_EXCL.
func (s *Service) Project(root *workspace.Root, files []ProjectFile, now time.Time) (ProjectResult, error) {
	if len(files) == 0 || len(files) > maxProjectFiles {
		return ProjectResult{Denied: true, Code: "FILE_DENIED", Reason: "invalid"}, nil
	}

	decoded := make([][]byte, len(files))
	for i, file := range files {
		if file.Mode != "0600" {
			return ProjectResult{Denied: true, Code: "FILE_DENIED", Reason: "invalid_mode"}, nil
		}
		if reason := s.ProjectableClassification(file.Path); reason != "" {
			return ProjectResult{Denied: true, Code: "FILE_DENIED", Reason: reason}, nil
		}
		data, err := base64.StdEncoding.DecodeString(file.Data)
		if err != nil {
			return ProjectResult{Denied: true, Code: "FILE_DENIED", Reason: "invalid"}, nil
		}
		if len(data) > maxProjectFileBytes {
			return ProjectResult{Denied: true, Code: "FILE_UPLOAD_TOO_LARGE"}, nil
		}
		decoded[i] = data
	}

	// `.cliora` must be a real directory if it exists at all. Same check, same reason,
	// as ensureUploadDir.
	if info, err := root.LstatIn(clioraDir); err == nil {
		if !info.IsDir() {
			return ProjectResult{Denied: true, Code: "FILE_DENIED", Reason: "dir_not_directory"}, nil
		}
	} else if !errors.Is(err, workspace.ErrNotFound) {
		return ProjectResult{}, err
	}

	result := ProjectResult{Written: []string{}, Skipped: []string{}}
	for i, file := range files {
		rel := path.Clean(file.Path)
		if err := root.MkdirAllIn(path.Dir(rel), projectDirMode); err != nil {
			return ProjectResult{}, err
		}
		// Written once, never overwritten — the user may have their own rules in it.
		// Reused rather than reimplemented: two gitignore writers would drift.
		s.ensureClioraGitignore(root)

		handle, err := root.CreateExclusive(rel, projectFileMode)
		if err != nil {
			if errors.Is(err, workspace.ErrExists) {
				// The same content version is already here. Success, not a collision:
				// this is what a second session in one workspace looks like.
				result.Skipped = append(result.Skipped, rel)
				continue
			}
			if denied, ok := denyStoreFromWorkspaceErr(err, "create"); ok {
				return ProjectResult{Denied: true, Code: denied.Code, Reason: denied.Reason}, nil
			}
			return ProjectResult{}, err
		}
		if err := writeSyncChmod(handle, decoded[i], projectFileMode); err != nil {
			_ = root.RemoveIn(rel)
			return ProjectResult{}, err
		}
		result.Written = append(result.Written, rel)
		result.Bytes += int64(len(decoded[i]))
	}
	return result, nil
}

// ensureClioraGitignore writes `.cliora/.gitignore` when it is absent.
//
// Best-effort on purpose, exactly as image drop treats it: the projection is already
// useful without it, and the worst case is a noisier `git status`.
func (s *Service) ensureClioraGitignore(root *workspace.Root) {
	if _, err := root.LstatIn(gitignore); errors.Is(err, workspace.ErrNotFound) {
		if handle, createErr := root.CreateExclusive(gitignore, 0o600); createErr == nil {
			_ = writeSyncChmod(handle, []byte(gitignoreBody), 0o600)
		}
	}
}

// ProjectRetention removes projected files older than `maxAge`.
//
// ADR 0024's W2 question, answered for this store: the daemon cleans it, after 30
// days by default. The path list is **closed**, and that is the point — `uploads/` is
// image drop's area with its own quota, and `.gitignore` may be the user's own file.
// A cleanup that walked `.cliora/` wholesale would delete a user's screenshots on a
// timer.
func (s *Service) ProjectRetention(root *workspace.Root, keepVersion string, maxAge time.Duration, now time.Time) (removed int, err error) {
	for _, subtree := range []string{contextDir, processDir, referenceDir} {
		// Until Central has projected a process definition this daemon does not
		// know which version is live. Skipping process/ is safer than guessing and
		// deleting a live session's instructions after a daemon restart.
		if subtree == processDir && keepVersion == "" {
			continue
		}
		// Deepest-first, so a directory is only removed once its files are gone —
		// `Root` exposes no recursive remove, and giving it one for this would hand
		// every other path a tool it has no business holding.
		var victims []string
		walkErr := fs.WalkDir(root.FS(), subtree, func(rel string, entry fs.DirEntry, walkErr error) error {
			if walkErr != nil {
				if errors.Is(walkErr, fs.ErrNotExist) {
					return fs.SkipAll // the subtree simply may not exist yet
				}
				return nil
			}
			if rel == subtree {
				return nil
			}
			// The process notes for the version in force are not garbage: a live
			// session is pointing at them.
			if subtree == processDir && path.Base(rel) == keepVersion && entry.IsDir() {
				return fs.SkipDir
			}
			info, statErr := entry.Info()
			if statErr != nil {
				return nil
			}
			if !entry.IsDir() && now.Sub(info.ModTime()) < maxAge {
				return nil
			}
			victims = append(victims, rel)
			return nil
		})
		if walkErr != nil {
			continue
		}
		for i := len(victims) - 1; i >= 0; i-- {
			if removeErr := root.RemoveIn(victims[i]); removeErr == nil {
				removed++
			}
		}
	}
	return removed, nil
}
