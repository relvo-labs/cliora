// Project memory, from the side that can actually reach the repository (ADR 0038 §3.4).
//
// **Central never fetches a repository.** It has no git client and no outbound
// connection it is allowed to use for this, and the one existing path to a node's files
// authorises a person against a terminal session — which a background worker is not.
// The agent, on the other hand, is already standing in a clean checkout of exactly the
// commit in question and already holds a run token. So the sync runs here.
//
// The protocol is content-addressed and two calls: a full manifest of
// `(path, sha256, size)`, then only the bodies Central says it is missing. An unchanged
// repository therefore costs one request and zero bytes, which is what makes running
// this on every run affordable rather than something a person has to remember.
//
// Nothing in this file changes the wire: both calls are ordinary HTTPS with the
// credential the run already has, so an `agentd` that predates it simply does not have
// the subcommand — and Central knows that from `runner.register.features` and leaves the
// instruction out of the context pack.
package cli

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io"
	"io/fs"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
)

// D88's bounds, mirrored here so the agent is told *before* it uploads eight megabytes
// that the platform will refuse them. The server enforces the same numbers; this copy is
// a courtesy, not the check.
const (
	maxSyncFiles     = 800
	maxSyncFileBytes = 256 * 1024
	maxUploadBytes   = 8 * 1024 * 1024
	// Enough of the head to decide "is this text": a NUL byte anywhere in the first
	// pages means no reader would want it in a search index either.
	binarySniffBytes = 8 * 1024
)

// includeSuffixes and includeNames are documentation-shaped rather than
// language-shaped. `.sql` and `.proto` are in because a schema *is* documentation, and
// they are also the partial answer to this release not building a symbol map.
var includeSuffixes = []string{
	".md", ".mdx", ".rst", ".txt", ".adoc", ".sql", ".proto",
}

var includeNames = []string{
	"readme", "changelog", "contributing", "license", "openapi", "codeowners",
}

// includeDirs catch documents that do not announce themselves by extension.
var includeDirs = []string{"docs/", "doc/", "adr/", "rfc/", "spec/", "specs/"}

// excludeDirs is checked before anything else and is deliberately conservative: every
// entry is a directory whose contents are generated, vendored or enormous, and none of
// them is somewhere a person writes a decision down.
var excludeDirs = []string{
	"node_modules/", "vendor/", "dist/", "build/", "target/", ".venv/", "venv/",
	"__pycache__/", ".git/", ".mypy_cache/", ".pytest_cache/", ".ruff_cache/",
	"coverage/", ".next/", ".nuxt/",
}

var excludeSuffixes = []string{".lock", ".min.js", ".min.css", ".map", ".snap"}

// SyncFile is one candidate, as the manifest describes it.
type SyncFile struct {
	Path   string `json:"path"`
	SHA256 string `json:"sha256"`
	Size   int64  `json:"size"`

	// Not sent in the manifest; used to load the body only if Central asks for it.
	abs string
}

type manifestRequest struct {
	// Omitted: the card already names its repository, and an agent should not have to
	// know a platform UUID to describe the directory it is standing in.
	RepositoryID string     `json:"repository_id,omitempty"`
	Commit       string     `json:"commit"`
	Files        []SyncFile `json:"files"`
}

// ManifestResult is Central's answer to call ①.
type ManifestResult struct {
	Want      []string            `json:"want"`
	Skipped   []map[string]string `json:"skipped"`
	Removed   int                 `json:"removed"`
	Unchanged int                 `json:"unchanged"`
}

type contentFile struct {
	Path string `json:"path"`
	Text string `json:"text"`
}

type contentRequest struct {
	RepositoryID string        `json:"repository_id,omitempty"`
	Commit       string        `json:"commit"`
	Files        []contentFile `json:"files"`
}

// ContentResult is Central's answer to call ②.
type ContentResult struct {
	Ingested int `json:"ingested"`
	Bytes    int `json:"bytes"`
}

// RepoManifest is call ①.
func (c *Client) RepoManifest(repositoryID, commit string, files []SyncFile) (ManifestResult, int, error) {
	var out ManifestResult
	status, err := c.do("POST", "/api/cli/runs/knowledge/repo-manifest",
		manifestRequest{RepositoryID: repositoryID, Commit: commit, Files: files}, &out)
	return out, status, err
}

// RepoContent is call ②.
func (c *Client) RepoContent(repositoryID, commit string, files []contentFile) (ContentResult, int, error) {
	var out ContentResult
	status, err := c.do("POST", "/api/cli/runs/knowledge/repo-content",
		contentRequest{RepositoryID: repositoryID, Commit: commit, Files: files}, &out)
	return out, status, err
}

// HeadCommit reads the checkout's current commit.
//
// The **only** git invocation in this package, and it is read-only, takes no input from
// anywhere, and reaches no network. It is called out here because `internal/cli` had no
// git dependency before: a reviewer should be able to satisfy themselves about that in
// one function rather than by searching.
func HeadCommit(root string) (string, error) {
	cmd := exec.Command("git", "-C", root, "rev-parse", "HEAD")
	out, err := cmd.Output()
	if err != nil {
		return "", fmt.Errorf("讀不到目前的 commit（這個目錄不是 git 檢出？）：%w", err)
	}
	return strings.TrimSpace(string(out)), nil
}

// wanted decides whether one repository-relative path is a candidate.
//
// Exclusion is checked first and wins, which is the rule that makes `.clioraignore`
// usable: a person adding a line to it must not have to know whether some builtin
// include rule also matches.
func wanted(rel string, ignore []string) bool {
	lower := strings.ToLower(rel)
	slashed := "/" + lower
	for _, dir := range excludeDirs {
		if strings.HasPrefix(lower, dir) || strings.Contains(slashed, "/"+dir) {
			return false
		}
	}
	for _, suffix := range excludeSuffixes {
		if strings.HasSuffix(lower, suffix) {
			return false
		}
	}
	for _, pattern := range ignore {
		if matchIgnore(pattern, lower) {
			return false
		}
	}
	for _, dir := range includeDirs {
		if strings.HasPrefix(lower, dir) || strings.Contains(slashed, "/"+dir) {
			return true
		}
	}
	for _, suffix := range includeSuffixes {
		if strings.HasSuffix(lower, suffix) {
			return true
		}
	}
	base := strings.ToLower(filepath.Base(rel))
	for _, name := range includeNames {
		if strings.HasPrefix(base, name) {
			return true
		}
	}
	return false
}

// matchIgnore implements the subset of `.gitignore` syntax that is unambiguous:
// a trailing `/` means a directory prefix, a leading `/` anchors to the root, and `*`
// is `filepath.Match`. Deliberately **not** the full specification — a partial
// implementation that silently disagrees with git on `**` would be worse than one whose
// limits are written down here.
func matchIgnore(pattern, lower string) bool {
	pattern = strings.ToLower(strings.TrimSpace(pattern))
	if pattern == "" || strings.HasPrefix(pattern, "#") {
		return false
	}
	anchored := strings.HasPrefix(pattern, "/")
	pattern = strings.TrimPrefix(pattern, "/")
	if strings.HasSuffix(pattern, "/") {
		dir := pattern
		if anchored {
			return strings.HasPrefix(lower, dir)
		}
		return strings.HasPrefix(lower, dir) || strings.Contains("/"+lower, "/"+dir)
	}
	if ok, _ := filepath.Match(pattern, lower); ok {
		return true
	}
	if !anchored {
		if ok, _ := filepath.Match(pattern, filepath.Base(lower)); ok {
			return true
		}
		// `docs/**/*.md`-style patterns collapse to a suffix test, which is the
		// behaviour a person writing one expects even though it is not git's.
		if strings.Contains(pattern, "**") {
			tail := pattern[strings.LastIndex(pattern, "**")+2:]
			tail = strings.TrimPrefix(tail, "/")
			if tail != "" {
				if ok, _ := filepath.Match(tail, filepath.Base(lower)); ok {
					return true
				}
			}
		}
	}
	return false
}

func readIgnore(root string) []string {
	raw, err := os.ReadFile(filepath.Join(root, ".clioraignore"))
	if err != nil {
		return nil
	}
	return strings.Split(string(raw), "\n")
}

func looksBinary(path string) bool {
	file, err := os.Open(path)
	if err != nil {
		return true
	}
	defer func() { _ = file.Close() }()
	buffer := make([]byte, binarySniffBytes)
	read, err := file.Read(buffer)
	if err != nil && err != io.EOF {
		return true
	}
	for _, b := range buffer[:read] {
		if b == 0 {
			return true
		}
	}
	return false
}

// CollectSyncFiles walks the checkout and returns the candidates, sorted.
//
// Sorted because the manifest is compared against a stored set and a person reading two
// `--dry-run` outputs should be able to diff them.
func CollectSyncFiles(root string) ([]SyncFile, error) {
	ignore := readIgnore(root)
	var out []SyncFile
	err := filepath.WalkDir(root, func(path string, entry fs.DirEntry, err error) error {
		if err != nil {
			// One unreadable directory must not fail the sync: a checkout may contain a
			// path this process cannot enter, and the rest of the repository is still
			// worth indexing.
			if entry != nil && entry.IsDir() {
				return fs.SkipDir
			}
			return nil
		}
		rel, relErr := filepath.Rel(root, path)
		if relErr != nil {
			return nil
		}
		rel = filepath.ToSlash(rel)
		if entry.IsDir() {
			for _, dir := range excludeDirs {
				if strings.EqualFold(rel+"/", dir) || strings.HasSuffix(strings.ToLower(rel)+"/", "/"+dir) {
					return fs.SkipDir
				}
			}
			return nil
		}
		if !entry.Type().IsRegular() || !wanted(rel, ignore) {
			return nil
		}
		info, infoErr := entry.Info()
		if infoErr != nil {
			return nil
		}
		if looksBinary(path) {
			return nil
		}
		digest, digestErr := fileDigest(path)
		if digestErr != nil {
			return nil
		}
		out = append(out, SyncFile{Path: rel, SHA256: digest, Size: info.Size(), abs: path})
		return nil
	})
	if err != nil {
		return nil, err
	}
	sortSyncFiles(out)
	return out, nil
}

func fileDigest(path string) (string, error) {
	file, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer func() { _ = file.Close() }()
	hasher := sha256.New()
	if _, err := io.Copy(hasher, file); err != nil {
		return "", err
	}
	return hex.EncodeToString(hasher.Sum(nil)), nil
}

func sortSyncFiles(files []SyncFile) {
	for i := 1; i < len(files); i++ {
		for j := i; j > 0 && files[j].Path < files[j-1].Path; j-- {
			files[j], files[j-1] = files[j-1], files[j]
		}
	}
}

// BatchContent splits the wanted paths into uploads that each stay under the byte
// ceiling. A file bigger than the ceiling on its own is dropped rather than sent alone:
// the server would skip it anyway, and sending it costs the bytes twice.
func BatchContent(files []SyncFile, want []string) ([][]contentFile, []string, error) {
	byPath := make(map[string]SyncFile, len(files))
	for _, file := range files {
		byPath[file.Path] = file
	}
	var batches [][]contentFile
	var current []contentFile
	var skipped []string
	size := 0
	for _, path := range want {
		file, ok := byPath[path]
		if !ok {
			continue
		}
		if file.Size > maxSyncFileBytes {
			skipped = append(skipped, path)
			continue
		}
		body, err := os.ReadFile(file.abs)
		if err != nil {
			skipped = append(skipped, path)
			continue
		}
		if size+len(body) > maxUploadBytes && len(current) > 0 {
			batches = append(batches, current)
			current = nil
			size = 0
		}
		current = append(current, contentFile{Path: path, Text: string(body)})
		size += len(body)
	}
	if len(current) > 0 {
		batches = append(batches, current)
	}
	return batches, skipped, nil
}

// --- reading, as opposed to pushing (`KN-09`) -------------------------------

// ContextPack is what `cliora knowledge context` fetches.
//
// It is a **pull**, and that is ADR 0039's whole shape: `run.offer.context` is capped at
// 32 KiB by the daemon's decoder and a breach of that cap is silent, so the offer
// carries the project's rules and a pointer, and the rest is fetched here.
type ContextPack struct {
	PackID     string           `json:"pack_id"`
	Markdown   string           `json:"markdown"`
	Manifest   []ManifestSource `json:"manifest"`
	Budget     map[string]any   `json:"budget"`
	Omitted    []map[string]any `json:"omitted"`
	TotalBytes int              `json:"total_bytes"`
}

// ManifestSource is one entry in "what this turn read".
type ManifestSource struct {
	SourceID   string   `json:"source_id"`
	Label      string   `json:"label"`
	Layer      int      `json:"layer"`
	Title      string   `json:"title"`
	Authority  string   `json:"authority"`
	Version    string   `json:"version"`
	SourceType string   `json:"source_type"`
	Why        []string `json:"why"`
}

// KnowledgeHit is one search result.
type KnowledgeHit struct {
	SourceID   string   `json:"source_id"`
	SourceType string   `json:"source_type"`
	Title      string   `json:"title"`
	Authority  string   `json:"authority"`
	Version    string   `json:"version"`
	Excerpt    string   `json:"excerpt"`
	Historical bool     `json:"historical"`
	Why        []string `json:"why"`
}

// KnowledgeSearchPage is the search response.
type KnowledgeSearchPage struct {
	Items    []KnowledgeHit `json:"items"`
	Total    int            `json:"total"`
	Channels []string       `json:"channels"`
	Degraded string         `json:"degraded"`
}

// KnowledgeSource is one source, expanded.
type KnowledgeSource struct {
	SourceID   string `json:"source_id"`
	SourceType string `json:"source_type"`
	Title      string `json:"title"`
	Authority  string `json:"authority"`
	Version    string `json:"version"`
	URI        string `json:"uri"`
	Content    string `json:"content"`
}

// FetchContextPack is `cliora knowledge context`.
func (c *Client) FetchContextPack(layers string) (ContextPack, int, error) {
	path := "/api/cli/runs/knowledge/context-pack"
	if layers != "" {
		path += "?layers=" + url.QueryEscape(layers)
	}
	var out ContextPack
	status, err := c.do("GET", path, nil, &out)
	return out, status, err
}

// SearchKnowledge is `cliora knowledge search`.
//
// The server caps `limit` at eight regardless of what is sent. Clamping here as well is
// a courtesy to the reader of `--help`, not the enforcement.
func (c *Client) SearchKnowledge(query string, limit int) (KnowledgeSearchPage, int, error) {
	if limit <= 0 || limit > 8 {
		limit = 8
	}
	path := fmt.Sprintf("/api/cli/runs/knowledge/search?q=%s&limit=%d",
		url.QueryEscape(query), limit)
	var out KnowledgeSearchPage
	status, err := c.do("GET", path, nil, &out)
	return out, status, err
}

// ReadKnowledgeSource is `cliora knowledge cite`.
func (c *Client) ReadKnowledgeSource(sourceID string) (KnowledgeSource, int, error) {
	var out KnowledgeSource
	status, err := c.do("GET", "/api/cli/runs/knowledge/sources/"+url.PathEscape(sourceID), nil, &out)
	return out, status, err
}

// ResolveLabel turns `S2` — the short form the pack and the search results print — into
// the source id behind it.
//
// **Short labels rather than uuids** because they end up inside prose an agent writes on
// a card, where a uuid tells a reader nothing and a `[S2]` can be rendered back into a
// link. The mapping is per pack, which is why a stale label is a `SOURCE_NOT_FOUND`
// telling the agent to fetch the pack again rather than a silent miss.
func ResolveLabel(pack ContextPack, label string) (string, bool) {
	label = strings.TrimSpace(label)
	if strings.HasPrefix(label, "[") && strings.HasSuffix(label, "]") {
		label = strings.TrimSuffix(strings.TrimPrefix(label, "["), "]")
	}
	for _, entry := range pack.Manifest {
		if strings.EqualFold(strings.Trim(entry.Label, "[]"), label) {
			return entry.SourceID, true
		}
	}
	// A uuid passed straight through is accepted: an agent that kept one from an earlier
	// call should not be forced to re-derive a label for it.
	if strings.Count(label, "-") == 4 {
		return label, true
	}
	return "", false
}
