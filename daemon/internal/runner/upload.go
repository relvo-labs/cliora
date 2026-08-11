package runner

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"strings"
	"time"
)

// Attaching the daemon's own artifact — the run's `git diff` (ADR 0031 §7).
//
// **The honesty rule.** If a card declared no delivery and the working tree changed
// anyway, that work disappears when the run directory is reclaimed **and nobody would
// know it had existed**. So the diff is attached whether or not the card asked for it.
//
// The second ruling of 2026-08-10 narrows where this bites without removing it: an
// agent that pushed a branch has not lost its work, an agent that did not still will,
// and the platform cannot tell those apart. It only knows the tree changed.
//
// This uses **the same endpoint and the same credential** the agent's own
// `cliora task attach` uses. That is a side benefit of artifacts being HTTP rather
// than a protocol message (ADR 0030 Part B): had they gone over the WebSocket, the
// daemon would have needed a second upload path of its own.

// Uploader posts an artifact to Central on a run's behalf.
type Uploader struct {
	// APIBase is Central's HTTP origin, derived from the WebSocket URL the daemon
	// already has — there is no second address to configure and get wrong.
	APIBase string
	// Credential is the run's own `cliora_rt_…` token, which is the only thing that
	// authorises this. It is never logged.
	Credential string
	HTTP       *http.Client
}

// APIBaseFromWebsocketURL turns `wss://host/ws/nodes` into `https://host`.
//
// Derived rather than configured: a second URL in the config file is a second thing
// that can point somewhere else, and "the artifact upload went to the wrong Central"
// is a failure nobody would think to look for.
func APIBaseFromWebsocketURL(raw string) string {
	base := strings.TrimRight(raw, "/")
	switch {
	case strings.HasPrefix(base, "wss://"):
		base = "https://" + strings.TrimPrefix(base, "wss://")
	case strings.HasPrefix(base, "ws://"):
		base = "http://" + strings.TrimPrefix(base, "ws://")
	}
	if index := strings.Index(base, "/ws/"); index >= 0 {
		base = base[:index]
	}
	return base
}

// AttachDiff uploads one patch and returns the artifact id.
//
// A digest travels with it and the server re-computes it. Not tamper protection — the
// connection is TLS — but a **truncated** upload should fail rather than become a
// broken artifact nobody can open.
func (u Uploader) AttachDiff(ctx context.Context, filename, patch, message string) (string, error) {
	if u.APIBase == "" || u.Credential == "" {
		return "", fmt.Errorf("no run credential: the diff cannot be attached")
	}
	digest := sha256.Sum256([]byte(patch))

	var body bytes.Buffer
	writer := multipart.NewWriter(&body)
	_ = writer.WriteField("sha256", hex.EncodeToString(digest[:]))
	if message != "" {
		_ = writer.WriteField("message", message)
	}
	part, err := writer.CreateFormFile("file", filename)
	if err != nil {
		return "", err
	}
	if _, err := io.WriteString(part, patch); err != nil {
		return "", err
	}
	if err := writer.Close(); err != nil {
		return "", err
	}

	request, err := http.NewRequestWithContext(
		ctx, "POST", u.APIBase+"/api/cli/runs/artifacts", &body,
	)
	if err != nil {
		return "", err
	}
	request.Header.Set("Authorization", "Bearer "+u.Credential)
	request.Header.Set("Content-Type", writer.FormDataContentType())

	client := u.HTTP
	if client == nil {
		client = &http.Client{Timeout: 120 * time.Second}
	}
	response, err := client.Do(request)
	if err != nil {
		return "", err
	}
	defer func() { _ = response.Body.Close() }()
	raw, _ := io.ReadAll(response.Body)
	if response.StatusCode >= 400 {
		// The quota codes reach here, and the run summary carries them onward: an
		// artifact that silently failed to attach is work that vanishes with the
		// directory, which is the exact thing this whole path exists to prevent.
		return "", fmt.Errorf("upload refused (%d): %s", response.StatusCode, safeTail(string(raw)))
	}
	return artifactIDFrom(raw), nil
}

func safeTail(body string) string {
	body = strings.TrimSpace(body)
	if len(body) > 200 {
		return body[:200]
	}
	return body
}

func artifactIDFrom(raw []byte) string {
	// Deliberately not a full JSON decode into a typed struct: the daemon needs one
	// field for a log line, and a struct here would be a third copy of a DTO that
	// already exists on both other sides.
	text := string(raw)
	const key = "\"id\":\""
	start := strings.Index(text, key)
	if start < 0 {
		return ""
	}
	rest := text[start+len(key):]
	end := strings.Index(rest, "\"")
	if end < 0 {
		return ""
	}
	return rest[:end]
}
