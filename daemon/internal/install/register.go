// Package install holds the logic behind `agentd install` (P1-15): building the
// register request, calling Central over the enrollment token, and rendering the
// config.yaml and systemd unit. The shell installer stays thin and auditable;
// all real decisions live here so they can be unit tested without root.
package install

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"

	"github.com/google/uuid"

	"github.com/cliora/cliora/daemon/internal/runtime"
	"github.com/cliora/cliora/daemon/internal/systeminfo"
)

// timestampLayout matches the daemon's node.register encoding (microsecond UTC).
const timestampLayout = "2006-01-02T15:04:05.000000Z07:00"

type RuntimeItem struct {
	Runtime    string  `json:"runtime"`
	Available  bool    `json:"available"`
	Version    *string `json:"version,omitempty"`
	BinaryPath *string `json:"binary_path,omitempty"`
	CheckedAt  *string `json:"checked_at,omitempty"`
}

type WorkspaceRootItem struct {
	Path        string  `json:"path"`
	DisplayName *string `json:"display_name,omitempty"`
	IsEnabled   bool    `json:"is_enabled"`
}

// RegisterRequest mirrors backend RegisterNodeRequest (schemas.py); the field
// names are the wire contract and must not drift from the Pydantic model.
type RegisterRequest struct {
	Token          string              `json:"token"`
	Name           string              `json:"name"`
	Hostname       string              `json:"hostname"`
	OS             string              `json:"os"`
	OSVersion      string              `json:"os_version"`
	Architecture   string              `json:"architecture"`
	DaemonVersion  string              `json:"daemon_version"`
	RunUser        string              `json:"run_user"`
	PublicKey      string              `json:"public_key"`
	Runtimes       []RuntimeItem       `json:"runtimes"`
	WorkspaceRoots []WorkspaceRootItem `json:"workspace_roots"`
}

type RegisterResponse struct {
	NodeID    uuid.UUID `json:"node_id"`
	ServerURL string    `json:"server_url"`
}

// BuildRegisterRequest assembles the enrollment payload from detected system
// facts. run_user is the requested service account (--user), not the installing
// (root) user, so Central records the identity the daemon will actually run as.
func BuildRegisterRequest(p Params, info systeminfo.Info, detected []runtime.DetectResult) RegisterRequest {
	runtimes := make([]RuntimeItem, 0, len(detected))
	for _, r := range detected {
		item := RuntimeItem{Runtime: r.Runtime, Available: r.Available}
		if r.Version != "" {
			v := r.Version
			item.Version = &v
		}
		if r.BinaryPath != "" {
			b := r.BinaryPath
			item.BinaryPath = &b
		}
		if !r.CheckedAt.IsZero() {
			ts := r.CheckedAt.UTC().Format(timestampLayout)
			item.CheckedAt = &ts
		}
		runtimes = append(runtimes, item)
	}
	roots := make([]WorkspaceRootItem, 0, len(p.WorkspaceRoots))
	for _, root := range p.WorkspaceRoots {
		roots = append(roots, WorkspaceRootItem{Path: root, IsEnabled: true})
	}
	hostname := info.Hostname
	if hostname == "" {
		hostname = p.NodeName
	}
	return RegisterRequest{
		Token:          p.Token,
		Name:           p.NodeName,
		Hostname:       hostname,
		OS:             info.OS,
		OSVersion:      info.OSVersion,
		Architecture:   info.Architecture,
		DaemonVersion:  p.DaemonVersion,
		RunUser:        p.RunUser,
		PublicKey:      p.PublicKey,
		Runtimes:       runtimes,
		WorkspaceRoots: roots,
	}
}

// Register performs POST /api/nodes/register over the enrollment token. The
// token is never logged; on failure only the server's stable error code/message
// is surfaced.
func Register(ctx context.Context, client *http.Client, serverBaseURL string, req RegisterRequest) (*RegisterResponse, error) {
	endpoint := strings.TrimRight(serverBaseURL, "/") + "/api/nodes/register"
	payload, err := json.Marshal(req)
	if err != nil {
		return nil, err
	}
	httpReq, err := http.NewRequestWithContext(ctx, http.MethodPost, endpoint, bytes.NewReader(payload))
	if err != nil {
		return nil, err
	}
	httpReq.Header.Set("Content-Type", "application/json")
	resp, err := client.Do(httpReq)
	if err != nil {
		return nil, fmt.Errorf("register request failed: %w", err)
	}
	defer func() { _ = resp.Body.Close() }()
	body, _ := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if resp.StatusCode != http.StatusCreated {
		return nil, fmt.Errorf("register rejected (HTTP %d): %s", resp.StatusCode, safeServerError(body))
	}
	var out RegisterResponse
	if err := json.Unmarshal(body, &out); err != nil {
		return nil, fmt.Errorf("decode register response: %w", err)
	}
	if out.NodeID == uuid.Nil {
		return nil, fmt.Errorf("register response missing node identity")
	}
	return &out, nil
}

// DefaultClient is a short-timeout HTTP client for the one-shot register call.
func DefaultClient() *http.Client { return &http.Client{Timeout: 30 * time.Second} }

// safeServerError extracts the stable {"error":{"code","message"}} shape without
// echoing arbitrary server output (which could include reflected input).
func safeServerError(body []byte) string {
	var parsed struct {
		Error struct {
			Code    string `json:"code"`
			Message string `json:"message"`
		} `json:"error"`
	}
	if err := json.Unmarshal(body, &parsed); err == nil && parsed.Error.Code != "" {
		return fmt.Sprintf("%s: %s", parsed.Error.Code, parsed.Error.Message)
	}
	return "unexpected error"
}
