package connection

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"log/slog"
	"time"

	"github.com/cliora/cliora/daemon/internal/files"
	"github.com/cliora/cliora/daemon/internal/metrics"
	"github.com/cliora/cliora/daemon/internal/protocol"
	"github.com/cliora/cliora/daemon/internal/workspace"
	"github.com/google/uuid"
)

// searchRequestTimeout bounds a single filesystem.search walk independent of
// the Central relay timeout, so a slow tree cannot hold a goroutine open
// indefinitely (ADR 0015).
const searchRequestTimeout = 12 * time.Second

// openSessionWorkspace resolves the session's launch workspace and opens a
// confined workspace.Root for it. Every filesystem request re-canonicalises the
// workspace (never trusting a prior listing) via the guard (ADR 0014).
func (m *Manager) openSessionWorkspace(sessionID uuid.UUID) (*workspace.Root, string, bool) {
	ws, ok := m.sessions.Workspace(sessionID)
	if !ok {
		return nil, "", false
	}
	root, err := m.guard.OpenWorkspace(ws)
	if err != nil {
		return nil, workspaceCode(err), false
	}
	return root, "", true
}

func (m *Manager) handleFsList(env protocol.Envelope, data []byte, send func([]byte) error) {
	if protocol.ValidateControl(data) != nil {
		m.replyError(send, env.RequestID, "INVALID_MESSAGE")
		return
	}
	var p fsListPayload
	if json.Unmarshal(env.Payload, &p) != nil {
		m.replyError(send, env.RequestID, "INVALID_MESSAGE")
		return
	}
	root, code, ok := m.openSessionWorkspace(p.SessionID)
	if !ok {
		m.replyError(send, env.RequestID, orSessionNotFound(code))
		return
	}
	defer root.Close()

	started := time.Now()
	res, err := m.files.List(root, p.Path, p.Cursor, p.EntryLimit)
	if err != nil {
		code := workspaceCode(err)
		metrics.Increment(metrics.FilesystemRequestTotal, map[string]string{"op": "list", "code": code})
		m.replyError(send, env.RequestID, code)
		return
	}
	metrics.Increment(metrics.FilesystemRequestTotal, map[string]string{"op": "list", "code": "OK"})
	metrics.Observe(metrics.FilesystemListEntries, float64(len(res.Entries)), nil)
	// Correlation log: ids, volumes and outcome only — never a path or a name.
	slog.Info("filesystem list",
		"event", "filesystem.list", "request_id", env.RequestID,
		"session_id", p.SessionID.String(), "entries", len(res.Entries),
		"truncated", res.Truncated, "duration_ms", time.Since(started).Milliseconds())
	frame, buildErr := protocol.BuildResponse("filesystem.entries", m.creds.NodeID, env.RequestID,
		true, listPayload(res), m.now())
	if buildErr != nil {
		// Over the frame bound: answer with an error rather than emit a frame
		// Central would drop (which would surface as a request timeout).
		metrics.Increment(metrics.FilesystemRequestTotal,
			map[string]string{"op": "list", "code": "FRAME_TOO_LARGE"})
		m.replyError(send, env.RequestID, "FRAME_TOO_LARGE")
		return
	}
	_ = send(frame)
}

func (m *Manager) handleFsRead(env protocol.Envelope, data []byte, send func([]byte) error) {
	if protocol.ValidateControl(data) != nil {
		m.replyError(send, env.RequestID, "INVALID_MESSAGE")
		return
	}
	var p fsReadPayload
	if json.Unmarshal(env.Payload, &p) != nil {
		m.replyError(send, env.RequestID, "INVALID_MESSAGE")
		return
	}
	root, code, ok := m.openSessionWorkspace(p.SessionID)
	if !ok {
		m.replyError(send, env.RequestID, orSessionNotFound(code))
		return
	}
	defer root.Close()

	started := time.Now()
	res, err := m.files.Read(root, p.Path)
	if err != nil {
		code := workspaceCode(err)
		metrics.Increment(metrics.FilesystemRequestTotal, map[string]string{"op": "read", "code": code})
		m.replyError(send, env.RequestID, code)
		return
	}
	if res.Denied {
		// Reason is a coarse classification (dotenv/private_key/binary/…), safe
		// to count; the path and content never leave the node.
		metrics.Increment(metrics.FilesystemDeniedTotal,
			map[string]string{"code": res.Code, "reason": denialReason(res)})
		metrics.Increment(metrics.FilesystemRequestTotal,
			map[string]string{"op": "read", "code": res.Code})
	} else {
		metrics.Increment(metrics.FilesystemRequestTotal, map[string]string{"op": "read", "code": "OK"})
		metrics.Observe(metrics.FilesystemReadBytes, float64(len(res.Content)), nil)
	}
	slog.Info("filesystem read",
		"event", "filesystem.read", "request_id", env.RequestID,
		"session_id", p.SessionID.String(), "denied", res.Denied,
		"code", readCode(res), "bytes", len(res.Content),
		"duration_ms", time.Since(started).Milliseconds())
	frame, buildErr := protocol.BuildResponse("filesystem.content", m.creds.NodeID, env.RequestID,
		!res.Denied, contentPayload(res), m.now())
	if buildErr != nil {
		metrics.Increment(metrics.FilesystemRequestTotal,
			map[string]string{"op": "read", "code": "FRAME_TOO_LARGE"})
		m.replyError(send, env.RequestID, "FRAME_TOO_LARGE")
		return
	}
	_ = send(frame)
}

// handleFsUpload writes one image into the session workspace (FR-FILE-009).
// This is the only handler in the daemon that writes to a workspace; it follows
// the same shape as handleFsRead so the two are read side by side.
func (m *Manager) handleFsUpload(env protocol.Envelope, data []byte, send func([]byte) error) {
	if protocol.ValidateControl(data) != nil {
		m.replyError(send, env.RequestID, "INVALID_MESSAGE")
		return
	}
	var p fsUploadPayload
	if json.Unmarshal(env.Payload, &p) != nil {
		m.replyError(send, env.RequestID, "INVALID_MESSAGE")
		return
	}
	// Strict base64: the permissive decoder accepts trailing garbage, and the
	// wire schema already restricts the alphabet, so anything else is malformed
	// rather than merely unusual.
	raw, decodeErr := base64.StdEncoding.Strict().DecodeString(p.Data)
	if decodeErr != nil {
		m.replyError(send, env.RequestID, "INVALID_MESSAGE")
		return
	}
	root, code, ok := m.openSessionWorkspace(p.SessionID)
	if !ok {
		m.replyError(send, env.RequestID, orSessionNotFound(code))
		return
	}
	defer root.Close()

	started := time.Now()
	res, err := m.files.SaveImage(root, raw, m.now())
	if err != nil {
		code := workspaceCode(err)
		metrics.Increment(metrics.FilesystemRequestTotal, map[string]string{"op": "upload", "code": code})
		m.replyError(send, env.RequestID, code)
		return
	}
	if res.Denied {
		metrics.Increment(metrics.FilesystemRequestTotal,
			map[string]string{"op": "upload", "code": res.Code})
		m.replyError(send, env.RequestID, res.Code)
		return
	}
	metrics.Increment(metrics.FilesystemRequestTotal, map[string]string{"op": "upload", "code": "OK"})
	metrics.Observe(metrics.FilesystemUploadBytes, float64(res.Size), map[string]string{"mime": res.Mime})
	// The relative path is the platform's own invention, so logging it leaks
	// nothing about the node's existing tree. The bytes are never logged.
	slog.Info("filesystem upload",
		"event", "filesystem.upload", "request_id", env.RequestID,
		"session_id", p.SessionID.String(), "mime", res.Mime, "bytes", res.Size,
		"rel_path", res.RelPath, "duration_ms", time.Since(started).Milliseconds())

	frame, buildErr := protocol.BuildResponse("filesystem.uploaded", m.creds.NodeID, env.RequestID,
		true, map[string]any{
			"path":        res.RelPath,
			"mime":        res.Mime,
			"size":        res.Size,
			"modified_at": res.ModifiedAt.UTC().Format(time.RFC3339),
		}, m.now())
	if buildErr != nil {
		m.replyError(send, env.RequestID, "FRAME_TOO_LARGE")
		return
	}
	_ = send(frame)
}

// handleFsStore writes one uploaded file into the session workspace at a
// caller-chosen location (FR-FILE-010). It sits beside handleFsUpload
// deliberately: the two paths differ in exactly one respect — who names the
// destination — and reading them side by side is how that stays visible.
func (m *Manager) handleFsStore(env protocol.Envelope, data []byte, send func([]byte) error) {
	if protocol.ValidateControl(data) != nil {
		m.replyError(send, env.RequestID, "INVALID_MESSAGE")
		return
	}
	var p fsStorePayload
	if json.Unmarshal(env.Payload, &p) != nil {
		m.replyError(send, env.RequestID, "INVALID_MESSAGE")
		return
	}
	// Strict base64, for the same reason as image drop: the permissive decoder
	// tolerates trailing garbage, so the same bytes would have more than one
	// representation on the wire. Empty is legal here though — an empty file is a
	// legitimate thing to upload.
	var raw []byte
	if p.Data != "" {
		decoded, decodeErr := base64.StdEncoding.Strict().DecodeString(p.Data)
		if decodeErr != nil {
			m.replyError(send, env.RequestID, "INVALID_MESSAGE")
			return
		}
		raw = decoded
	}
	root, code, ok := m.openSessionWorkspace(p.SessionID)
	if !ok {
		m.replyError(send, env.RequestID, orSessionNotFound(code))
		return
	}
	defer root.Close()

	started := time.Now()
	res, err := m.files.Store(root, p.Directory, p.Filename, raw, m.now())
	if err != nil {
		code := workspaceCode(err)
		metrics.Increment(metrics.FilesystemRequestTotal, map[string]string{"op": "store", "code": code})
		m.replyError(send, env.RequestID, code)
		return
	}
	if res.Denied {
		metrics.Increment(metrics.FilesystemRequestTotal,
			map[string]string{"op": "store", "code": res.Code})
		metrics.Increment(metrics.FilesystemStoreRefusedTotal,
			map[string]string{"code": res.Code})
		// The refusal reason travels in the error frame's code only; the reason
		// string is a coarse classification, so it is safe to log but Central
		// needs the code to pick its HTTP status.
		slog.Info("filesystem store refused",
			"event", "filesystem.store", "request_id", env.RequestID,
			"session_id", p.SessionID.String(), "code", res.Code, "reason", res.Reason,
			"duration_ms", time.Since(started).Milliseconds())
		m.replyError(send, env.RequestID, res.Code)
		return
	}
	metrics.Increment(metrics.FilesystemRequestTotal, map[string]string{"op": "store", "code": "OK"})
	metrics.Observe(metrics.FilesystemUploadBytes, float64(res.Size), map[string]string{"source": "file"})
	// The relative path is logged because the user chose it and can see it; the
	// bytes never are.
	slog.Info("filesystem store",
		"event", "filesystem.store", "request_id", env.RequestID,
		"session_id", p.SessionID.String(), "bytes", res.Size,
		"rel_path", res.RelPath, "duration_ms", time.Since(started).Milliseconds())

	frame, buildErr := protocol.BuildResponse("filesystem.stored", m.creds.NodeID, env.RequestID,
		true, map[string]any{
			"path":        res.RelPath,
			"size":        res.Size,
			"modified_at": res.ModifiedAt.UTC().Format(time.RFC3339),
		}, m.now())
	if buildErr != nil {
		m.replyError(send, env.RequestID, "FRAME_TOO_LARGE")
		return
	}
	_ = send(frame)
}

// denialReason is the coarse classification for a denial metric, defaulting to
// the code when the policy did not attach one (binary/oversize).
func denialReason(res files.ReadResult) string {
	if res.Reason != "" {
		return res.Reason
	}
	switch res.Code {
	case "FILE_BINARY":
		return "binary"
	case "FILE_TOO_LARGE":
		return "oversize"
	default:
		return "unspecified"
	}
}

func readCode(res files.ReadResult) string {
	if res.Denied {
		return res.Code
	}
	return "OK"
}

func (m *Manager) handleFsSearch(ctx context.Context, env protocol.Envelope, data []byte, send func([]byte) error) {
	if protocol.ValidateControl(data) != nil {
		m.replyError(send, env.RequestID, "INVALID_MESSAGE")
		return
	}
	var p fsSearchPayload
	if json.Unmarshal(env.Payload, &p) != nil {
		m.replyError(send, env.RequestID, "INVALID_MESSAGE")
		return
	}
	root, code, ok := m.openSessionWorkspace(p.SessionID)
	if !ok {
		m.replyError(send, env.RequestID, orSessionNotFound(code))
		return
	}
	defer root.Close()

	sctx, cancel := context.WithTimeout(ctx, searchRequestTimeout)
	defer cancel()
	started := time.Now()
	res, err := m.files.Search(sctx, root, p.Keyword, p.Root, p.MaxResults)
	if err != nil {
		code := workspaceCode(err)
		metrics.Increment(metrics.FilesystemRequestTotal, map[string]string{"op": "search", "code": code})
		m.replyError(send, env.RequestID, code)
		return
	}
	metrics.Increment(metrics.FilesystemRequestTotal, map[string]string{"op": "search", "code": "OK"})
	metrics.Observe(metrics.FilesystemSearchScanned, float64(res.ScannedCount), nil)
	if res.StoppedReason != "" {
		metrics.Increment(metrics.FilesystemSearchStoppedTotal,
			map[string]string{"reason": res.StoppedReason})
	}
	// The keyword itself is never logged (it can name a confidential project).
	slog.Info("filesystem search",
		"event", "filesystem.search", "request_id", env.RequestID,
		"session_id", p.SessionID.String(), "results", len(res.Results),
		"scanned", res.ScannedCount, "partial", res.Partial,
		"stopped_reason", res.StoppedReason,
		"duration_ms", time.Since(started).Milliseconds())
	frame, buildErr := protocol.BuildResponse("filesystem.search_result", m.creds.NodeID,
		env.RequestID, true, searchPayload(res), m.now())
	if buildErr != nil {
		metrics.Increment(metrics.FilesystemRequestTotal,
			map[string]string{"op": "search", "code": "FRAME_TOO_LARGE"})
		m.replyError(send, env.RequestID, "FRAME_TOO_LARGE")
		return
	}
	_ = send(frame)
}

// orSessionNotFound returns the workspace code if the guard produced one, else
// SESSION_NOT_FOUND when the session id is simply unknown.
func orSessionNotFound(code string) string {
	if code != "" {
		return code
	}
	return "SESSION_NOT_FOUND"
}

// --- payload types & mappers (no server absolute path is ever emitted) ---

type fsListPayload struct {
	SessionID  uuid.UUID `json:"session_id"`
	Path       string    `json:"path"`
	Cursor     string    `json:"cursor"`
	EntryLimit int       `json:"entry_limit"`
}
type fsReadPayload struct {
	SessionID uuid.UUID `json:"session_id"`
	Path      string    `json:"path"`
}
type fsSearchPayload struct {
	SessionID  uuid.UUID `json:"session_id"`
	Keyword    string    `json:"keyword"`
	Root       string    `json:"root"`
	MaxResults int       `json:"max_results"`
}

// fsUploadPayload is two fields, and that is the whole design (ADR 0024 §3).
// There is no filename, path, directory, extension or mime here, and the wire
// schema sets additionalProperties:false, so the sender cannot name the file it
// is creating. Adding a field to this struct means changing the contract, three
// consumers and an ADR — which is the intended cost.
type fsUploadPayload struct {
	SessionID uuid.UUID `json:"session_id"`
	Data      string    `json:"data"`
}

// fsStorePayload is the other upload path, and it is the mirror image of the one
// above: here the sender names the destination, because a file's name is what
// makes it useful (ADR 0026 §2). Still absent, and still enforced by the wire
// schema's additionalProperties:false: overwrite, mode, mime, precondition,
// revision. Nothing in this struct can ask to replace something.
type fsStorePayload struct {
	SessionID uuid.UUID `json:"session_id"`
	Directory string    `json:"directory"`
	Filename  string    `json:"filename"`
	Data      string    `json:"data"`
}

func entryMap(e files.Entry) map[string]any {
	return map[string]any{
		"name":        e.Name,
		"rel_path":    e.RelPath,
		"type":        e.Type,
		"size":        e.Size,
		"modified_at": e.ModifiedAt.UTC().Format(time.RFC3339),
		"hidden":      e.Hidden,
		"symlink":     e.Symlink,
		"excluded":    e.Excluded,
		"expandable":  e.Expandable,
	}
}

func listPayload(res files.ListResult) map[string]any {
	entries := make([]map[string]any, 0, len(res.Entries))
	for _, e := range res.Entries {
		entries = append(entries, entryMap(e))
	}
	out := map[string]any{
		"path":      res.Path,
		"entries":   entries,
		"truncated": res.Truncated,
	}
	if res.NextCursor != "" {
		out["next_cursor"] = res.NextCursor
	}
	return out
}

func contentPayload(res files.ReadResult) map[string]any {
	if res.Denied {
		out := map[string]any{
			"success":  false,
			"rel_path": res.RelPath,
			"error":    map[string]any{"code": res.Code, "reason": res.Reason},
		}
		// Size/mtime/mime are only meaningful (and safe) for binary/oversize.
		if res.Code == "FILE_BINARY" || res.Code == "FILE_TOO_LARGE" {
			out["size"] = res.Size
			if !res.ModifiedAt.IsZero() {
				out["modified_at"] = res.ModifiedAt.UTC().Format(time.RFC3339)
			}
			if res.Mime != "" {
				out["mime"] = res.Mime
			}
		}
		return out
	}
	return map[string]any{
		"success":       true,
		"rel_path":      res.RelPath,
		"size":          res.Size,
		"modified_at":   res.ModifiedAt.UTC().Format(time.RFC3339),
		"encoding":      res.Encoding,
		"language_hint": res.Language,
		"content":       res.Content,
	}
}

func searchPayload(res files.SearchResult) map[string]any {
	results := make([]map[string]any, 0, len(res.Results))
	for _, e := range res.Results {
		results = append(results, map[string]any{
			"name":        e.Name,
			"rel_path":    e.RelPath,
			"type":        e.Type,
			"modified_at": e.ModifiedAt.UTC().Format(time.RFC3339),
		})
	}
	out := map[string]any{
		"results":       results,
		"partial":       res.Partial,
		"scanned_count": res.ScannedCount,
	}
	if res.StoppedReason != "" {
		out["stopped_reason"] = res.StoppedReason
	}
	return out
}
