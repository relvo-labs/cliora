package files

import (
	"io/fs"
	"path"
	"sort"
	"strconv"
	"strings"

	"github.com/cliora/cliora/daemon/internal/workspace"
)

// List returns a single directory level under the workspace root. Ordering is
// deterministic (directories first, then files, each by byte-order name) so
// pagination is stable; entries are workspace-relative and never leak an
// absolute path. excluded directories are shown but marked non-expandable
// (tech §11.4). The cursor is an opaque offset into the sorted list.
func (s *Service) List(root *workspace.Root, relDir, cursor string, entryLimit int) (ListResult, error) {
	cleanDir := relDir
	if cleanDir == "" {
		cleanDir = "."
	}
	dir, err := root.OpenDir(relDir)
	if err != nil {
		return ListResult{}, err
	}
	defer dir.Close()

	dirents, err := dir.ReadDir(-1)
	if err != nil {
		return ListResult{}, workspace.ErrPermision
	}

	entries := make([]Entry, 0, len(dirents))
	for _, de := range dirents {
		name := de.Name()
		rel := name
		if cleanDir != "." {
			rel = path.Join(cleanDir, name)
		}
		info, infoErr := de.Info()
		e := Entry{
			Name:    name,
			RelPath: rel,
			Hidden:  strings.HasPrefix(name, "."),
		}
		switch {
		case de.Type()&fs.ModeSymlink != 0:
			e.Type = "symlink"
			e.Symlink = true
		case de.IsDir():
			e.Type = "directory"
		default:
			e.Type = "file"
		}
		if infoErr == nil {
			e.Size = info.Size()
			e.ModifiedAt = info.ModTime().UTC()
		}
		if e.Type == "directory" {
			e.Excluded = s.excludedDirs[name]
			e.Expandable = !e.Excluded
		}
		entries = append(entries, e)
	}

	sort.SliceStable(entries, func(i, j int) bool {
		di, dj := entries[i].Type == "directory", entries[j].Type == "directory"
		if di != dj {
			return di // directories first
		}
		return entries[i].Name < entries[j].Name
	})

	limit := entryLimit
	if limit <= 0 || limit > s.entryLimit {
		limit = s.entryLimit
	}
	offset := 0
	if cursor != "" {
		if n, convErr := strconv.Atoi(cursor); convErr == nil && n > 0 {
			offset = n
		}
	}
	if offset > len(entries) {
		offset = len(entries)
	}
	end := offset + limit
	truncated := end < len(entries)
	if end > len(entries) {
		end = len(entries)
	}
	result := ListResult{
		Path:      cleanDir,
		Entries:   entries[offset:end],
		Truncated: truncated,
	}
	if truncated {
		result.NextCursor = strconv.Itoa(end)
	}
	return result, nil
}
