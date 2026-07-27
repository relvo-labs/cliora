package files

import (
	"context"
	"io/fs"
	"path"
	"sort"
	"strings"

	"github.com/cliora/cliora/daemon/internal/workspace"
)

// Search walks the workspace (or a subtree) for entries whose base name
// contains keyword (case-insensitive filename match only — never file content,
// never a shell/ripgrep invocation, SEC-002). It is bounded on depth, results,
// scanned count, and — via ctx — wall-clock time; hitting any bound stops the
// walk and marks the result partial with the reason. Excluded directories are
// not descended (tech §11.4, §11.8; ADR 0015).
func (s *Service) Search(ctx context.Context, root *workspace.Root, keyword, startRel string, maxResults int) (SearchResult, error) {
	start := startRel
	if start == "" {
		start = "."
	} else {
		start = path.Clean(startRel)
	}
	limit := s.search.MaxResults
	if maxResults > 0 && maxResults < limit {
		limit = maxResults
	}
	needle := strings.ToLower(keyword)

	var (
		result  SearchResult
		scanned int
		stopped string
	)
	fsys := root.FS()
	walkErr := fs.WalkDir(fsys, start, func(p string, d fs.DirEntry, err error) error {
		if err != nil {
			// A permission error on one subtree must not abort the whole search;
			// skip it and continue.
			if d != nil && d.IsDir() {
				return fs.SkipDir
			}
			return nil
		}
		if ctx.Err() != nil {
			stopped = "timeout"
			return errStop
		}
		if d.IsDir() {
			// Depth is measured from the search start.
			if depthFrom(start, p) > s.search.MaxDepth {
				return fs.SkipDir
			}
			if p != start && s.excludedDirs[d.Name()] {
				return fs.SkipDir
			}
			return nil
		}
		scanned++
		if scanned > s.search.MaxScanned {
			stopped = "scanned"
			return errStop
		}
		if strings.Contains(strings.ToLower(d.Name()), needle) {
			e := Entry{Name: d.Name(), RelPath: p, Type: "file"}
			if info, infoErr := d.Info(); infoErr == nil {
				e.ModifiedAt = info.ModTime().UTC()
				e.Size = info.Size()
			}
			result.Results = append(result.Results, e)
			if len(result.Results) >= limit {
				stopped = "results"
				return errStop
			}
		}
		return nil
	})

	result.ScannedCount = scanned
	if walkErr != nil && walkErr != errStop {
		return SearchResult{}, workspace.ErrPermision
	}
	if stopped == "" && ctx.Err() != nil {
		stopped = "timeout"
	}
	if stopped != "" {
		result.Partial = true
		result.StoppedReason = stopped
	}
	sort.SliceStable(result.Results, func(i, j int) bool {
		return result.Results[i].RelPath < result.Results[j].RelPath
	})
	return result, nil
}

// errStop unwinds fs.WalkDir when a bound is hit; it is never returned to the
// caller.
var errStop = fsStopError{}

type fsStopError struct{}

func (fsStopError) Error() string { return "search bound reached" }

// depthFrom returns how many path segments p is below start (start itself = 0).
func depthFrom(start, p string) int {
	if p == start {
		return 0
	}
	rel := p
	if start != "." {
		rel = strings.TrimPrefix(p, start+"/")
	}
	if rel == "" || rel == p && start != "." {
		return 0
	}
	return strings.Count(rel, "/") + 1
}
