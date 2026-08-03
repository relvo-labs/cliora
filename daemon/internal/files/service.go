package files

import (
	"time"

	"github.com/cliora/cliora/daemon/internal/config"
)

// DefaultEntryLimit caps a single directory response (ADR 0015); larger
// directories paginate via a cursor.
const DefaultEntryLimit = 2000

// Service performs confined list/read/search operations under a workspace.Root.
// It is built once from config and is safe for concurrent use (all state is
// read-only; per-request state lives on the stack).
type Service struct {
	policy       *Policy
	excludedDirs map[string]bool
	search       config.SearchConfig
	upload       config.UploadConfig
	maxPreview   int64
	entryLimit   int
	now          func() time.Time
	// storeQuota is the only mutable state on the service. General file upload
	// cannot recount its usage from the filesystem the way image drop can,
	// because its files land wherever the user chose (ADR 0026 §5).
	storeQuota *storeQuota
	// freeBytes is a seam so the free-space refusal can be tested without
	// filling a disk. Production uses statfsFreeBytes.
	freeBytes func(path string) (int64, error)
}

// NewService builds the file service from daemon config.
func NewService(cfg *config.Config, now func() time.Time) *Service {
	excluded := make(map[string]bool, len(cfg.Workspace.ExcludedDirectories))
	for _, d := range cfg.Workspace.ExcludedDirectories {
		excluded[d] = true
	}
	if now == nil {
		now = time.Now
	}
	return &Service{
		policy:       NewPolicy(cfg.Filesystem),
		excludedDirs: excluded,
		search:       cfg.Filesystem.Search,
		upload:       cfg.Filesystem.Upload,
		maxPreview:   cfg.Filesystem.MaxPreviewSize,
		entryLimit:   DefaultEntryLimit,
		now:          now,
		storeQuota:   newStoreQuota(),
		freeBytes:    statfsFreeBytes,
	}
}

// Entry is a single directory entry in a listing or search result. Paths are
// workspace-relative; no server absolute path is ever included.
type Entry struct {
	Name       string    `json:"name"`
	RelPath    string    `json:"rel_path"`
	Type       string    `json:"type"` // directory | file | symlink
	Size       int64     `json:"size"`
	ModifiedAt time.Time `json:"modified_at"`
	Hidden     bool      `json:"hidden"`
	Symlink    bool      `json:"symlink"`
	Excluded   bool      `json:"excluded"`
	Expandable bool      `json:"expandable"`
}

// ListResult is the response payload for filesystem.list.
type ListResult struct {
	Path       string  `json:"path"`
	Entries    []Entry `json:"entries"`
	Truncated  bool    `json:"truncated"`
	NextCursor string  `json:"next_cursor,omitempty"`
}

// ReadResult is the response payload for filesystem.read. On success Content
// holds the bounded UTF-8 text; on denial Denied is true and Code/Reason carry
// the safe classification (never content or a server absolute path).
type ReadResult struct {
	RelPath    string    `json:"rel_path"`
	Size       int64     `json:"size"`
	ModifiedAt time.Time `json:"modified_at"`
	Encoding   string    `json:"encoding,omitempty"`
	Language   string    `json:"language_hint,omitempty"`
	Content    string    `json:"content,omitempty"`

	Denied bool   `json:"-"`
	Code   string `json:"-"`
	Reason string `json:"-"`
	Mime   string `json:"-"`
}

// StoreResultPayload is the response payload for filesystem.store. Unlike
// filesystem.uploaded it carries no mime: this path does not judge content type
// (ADR 0026 §1.3), and a field nobody can fill honestly is a field that will one
// day be filled dishonestly.
type StoreResultPayload struct {
	Path       string    `json:"path"`
	Size       int64     `json:"size"`
	ModifiedAt time.Time `json:"modified_at"`
}

// SearchResult is the response payload for filesystem.search.
type SearchResult struct {
	Results       []Entry `json:"results"`
	Partial       bool    `json:"partial"`
	StoppedReason string  `json:"stopped_reason,omitempty"`
	ScannedCount  int     `json:"scanned_count"`
}
