package protocol

import (
	"bytes"
	"encoding/json"
	"time"

	"github.com/google/uuid"
)

// Read-only binary preview payloads (contract 1.11.0, ADR 0029). These mirror
// contracts/v1/schemas/messages/filesystem-preview-*.schema.json so Go accepts and
// rejects exactly what the Python (schema) and TypeScript consumers do.
//
// The request side has nothing to claim: preview_open is fsReadFields, and the
// chunk/close requests name a handle and an index, never an offset or a length.

type previewChunkFields struct {
	SessionID uuid.UUID `json:"session_id"`
	PreviewID string    `json:"preview_id"`
	// Index is a pointer so a missing index is refused rather than read as 0.
	Index *int `json:"index"`
}

type previewCloseFields struct {
	SessionID uuid.UUID `json:"session_id"`
	PreviewID string    `json:"preview_id"`
}

// ValidPreviewID reports whether s has the ULID shape of a preview handle (the
// same pattern as request_id). Exported because the handle table checks it too.
func ValidPreviewID(s string) bool {
	if len(s) != 26 {
		return false
	}
	for i := 0; i < len(s); i++ {
		if !isCrockford(s[i]) {
			return false
		}
	}
	return true
}

func isCrockford(c byte) bool {
	switch {
	case c >= '0' && c <= '9':
		return true
	case c >= 'A' && c <= 'Z':
		return c != 'I' && c != 'L' && c != 'O' && c != 'U'
	}
	return false
}

func validChunkIndex(index *int) bool {
	return index != nil && *index >= 0 && *index < MaxPreviewChunks
}

// validConstTrue enforces a `{"const": true}` report field: absent is fine,
// true is fine, and false or null is invalid. A pointer alone cannot tell absent
// from null, so the raw payload is consulted for that case.
func validConstTrue(payload json.RawMessage, key string, value *bool) bool {
	if value != nil {
		return *value
	}
	var raw map[string]json.RawMessage
	if json.Unmarshal(payload, &raw) != nil {
		return false
	}
	present, ok := raw[key]
	return !ok || !bytes.Equal(bytes.TrimSpace(present), []byte("null"))
}

// The two preview RESPONSE types are validated here even though the daemon only
// produces them: a response branch missing on one consumer means the shared
// fixtures pass in Python and TypeScript and are silently accepted by Go (that is
// the RED this branch answers, plan/31/02 §6.3). It is also how the daemon's own
// tests prove it never emits an svg mime or a pdf with dimensions.

// PreviewMimes is the wire allowlist (the schema enum). Kind is derived from it.
var PreviewMimes = map[string]string{
	"image/png":       "image",
	"image/jpeg":      "image",
	"image/webp":      "image",
	"image/gif":       "image",
	"application/pdf": "pdf",
}

// PreviewDenialCodes are the in-band refusal codes of filesystem.preview_opened.
// Node-level refusals (FILE_PREVIEW_DISABLED, FILE_PREVIEW_EXPIRED, NODE_BUSY) are
// error frames instead, because they say nothing about the file.
var PreviewDenialCodes = map[string]bool{
	"FILE_PREVIEW_UNSUPPORTED": true, "FILE_PREVIEW_INVALID": true, "FILE_PREVIEW_LIMIT": true,
	"FILE_DENIED": true, "FILE_NOT_FOUND": true, "FILE_PERMISSION_DENIED": true, "FILE_TOO_LARGE": true,
}

const maxPreviewSide = 8192

var (
	previewOpenedKeys = map[string]bool{
		"success": true, "preview_id": true, "path": true, "kind": true, "mime": true, "size": true,
		"modified_at": true, "chunk_size": true, "chunk_count": true, "width": true, "height": true,
	}
	previewDeniedKeys = map[string]bool{"success": true, "path": true, "error": true}
)

type previewOpenedFields struct {
	Success    *bool                `json:"success"`
	PreviewID  string               `json:"preview_id"`
	Path       string               `json:"path"`
	Kind       string               `json:"kind"`
	Mime       string               `json:"mime"`
	Size       *int64               `json:"size"`
	ModifiedAt string               `json:"modified_at"`
	ChunkSize  *int                 `json:"chunk_size"`
	ChunkCount *int                 `json:"chunk_count"`
	Width      *int                 `json:"width"`
	Height     *int                 `json:"height"`
	Error      *previewDenialFields `json:"error"`
}

type previewDenialFields struct {
	Code   string `json:"code"`
	Reason string `json:"reason"`
	Size   *int64 `json:"size,omitempty"`
	Limit  *int64 `json:"limit,omitempty"`
}

type previewDataFields struct {
	PreviewID string `json:"preview_id"`
	Index     *int   `json:"index"`
	Data      string `json:"data"`
}

type previewClosedFields struct {
	PreviewID string `json:"preview_id"`
}

func validatePreviewOpened(payload json.RawMessage) bool {
	var raw map[string]json.RawMessage
	var p previewOpenedFields
	if json.Unmarshal(payload, &raw) != nil || strictUnmarshal(payload, &p) != nil || p.Success == nil {
		return false
	}
	allowed := previewOpenedKeys
	if !*p.Success {
		allowed = previewDeniedKeys
	}
	for key := range raw {
		if !allowed[key] {
			return false
		}
	}
	if !validRelPath(p.Path) {
		return false
	}
	if !*p.Success {
		e := p.Error
		return e != nil && PreviewDenialCodes[e.Code] && validDenialReason(e.Reason) &&
			(e.Size == nil || *e.Size >= 0) && (e.Limit == nil || *e.Limit >= 1)
	}
	kind, known := PreviewMimes[p.Mime]
	if !known || kind != p.Kind || !ValidPreviewID(p.PreviewID) ||
		p.Size == nil || *p.Size < 1 || *p.Size > MaxPreviewSize ||
		!validUTCTimestamp(p.ModifiedAt) ||
		p.ChunkSize == nil || *p.ChunkSize != PreviewChunkSize ||
		p.ChunkCount == nil || *p.ChunkCount < 1 || *p.ChunkCount > MaxPreviewChunks {
		return false
	}
	if kind == "pdf" {
		return p.Width == nil && p.Height == nil
	}
	return validSide(p.Width) && validSide(p.Height)
}

func validSide(v *int) bool { return v != nil && *v >= 1 && *v <= maxPreviewSide }

// validDenialReason mirrors the schema's reason pattern: a coarse lowercase
// classification such as "dotenv" or "pixels", never a path or a message.
func validDenialReason(s string) bool {
	if len(s) < 1 || len(s) > 64 || s[0] < 'a' || s[0] > 'z' {
		return false
	}
	for i := 0; i < len(s); i++ {
		c := s[i]
		if !(c >= 'a' && c <= 'z' || c >= '0' && c <= '9' || c == '_') {
			return false
		}
	}
	return true
}

// validUTCTimestamp mirrors the schema's `...Z` timestamp pattern.
func validUTCTimestamp(s string) bool {
	if len(s) < 20 || s[len(s)-1] != 'Z' {
		return false
	}
	_, err := time.Parse("2006-01-02T15:04:05.999999Z", s)
	return err == nil
}

// ValidPreviewData accepts canonical standard-alphabet base64 of at most one
// chunk. Empty is refused: there is no empty file to preview.
func ValidPreviewData(data string) bool {
	return len(data) <= MaxPreviewDataBase64 && validUploadData(data)
}

func validatePreviewData(env Envelope) bool {
	var p previewDataFields
	return env.Success != nil && *env.Success &&
		strictUnmarshal(env.Payload, &p) == nil && ValidPreviewID(p.PreviewID) &&
		validChunkIndex(p.Index) && ValidPreviewData(p.Data)
}

func validatePreviewClosed(env Envelope) bool {
	var p previewClosedFields
	return env.Success != nil && *env.Success &&
		strictUnmarshal(env.Payload, &p) == nil && ValidPreviewID(p.PreviewID)
}
