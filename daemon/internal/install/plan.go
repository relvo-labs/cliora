package install

import (
	"context"
	"fmt"
	"net/url"
	"strings"
	"time"

	"gopkg.in/yaml.v3"

	"github.com/cliora/cliora/daemon/internal/config"
	"github.com/cliora/cliora/daemon/internal/runtime"
)

// Params captures the operator-supplied install inputs (CLI flags).
type Params struct {
	Server         string // e.g. https://platform.example.com
	Token          string
	NodeName       string
	RunUser        string
	WorkspaceRoots []string
	AllowInsecure  bool // dev only: permits http/ws instead of https/wss
	DaemonVersion  string
	PublicKey      string
	HeartbeatSecs  int
}

// ServerWSURL converts the public HTTPS base URL into the wss node endpoint the
// connection manager expects (it appends "/<node_id>" to config.Server.URL).
// http/ws bases are only honoured as insecure dev endpoints.
func ServerWSURL(base string) (wsURL string, insecure bool, err error) {
	u, err := url.Parse(strings.TrimRight(strings.TrimSpace(base), "/"))
	if err != nil {
		return "", false, fmt.Errorf("invalid server url: %w", err)
	}
	if u.Host == "" {
		return "", false, fmt.Errorf("server url must include a host")
	}
	switch u.Scheme {
	case "https", "wss":
		u.Scheme = "wss"
	case "http", "ws":
		u.Scheme = "ws"
		insecure = true
	default:
		return "", false, fmt.Errorf("unsupported server scheme %q (use https)", u.Scheme)
	}
	u.Path = strings.TrimRight(u.Path, "/") + "/ws/nodes"
	return u.String(), insecure, nil
}

// DetectRuntimes probes the allowlisted CLIs on PATH using their default binary
// names, for both the register report and the generated config.
func DetectRuntimes(ctx context.Context, now time.Time) []runtime.DetectResult {
	cfg := map[string]config.RuntimeConfig{
		"claude": {Enabled: true, Binary: "claude"},
		"codex":  {Enabled: true, Binary: "codex"},
	}
	return runtime.NewRegistry(cfg).DetectAll(ctx, now)
}

// BuildConfig renders a valid config.Config: available runtimes are enabled with
// their resolved binary path; the result is validated before it is returned.
func BuildConfig(p Params, detected []runtime.DetectResult) (*config.Config, error) {
	wsURL, insecure, err := ServerWSURL(p.Server)
	if err != nil {
		return nil, err
	}
	if p.AllowInsecure {
		insecure = true
	}
	runtimes := map[string]config.RuntimeConfig{}
	for _, r := range detected {
		if !r.Available {
			continue
		}
		binary := r.BinaryPath
		if binary == "" {
			binary = r.Runtime
		}
		runtimes[r.Runtime] = config.RuntimeConfig{Enabled: true, Binary: binary}
	}
	heartbeat := p.HeartbeatSecs
	if heartbeat <= 0 {
		heartbeat = 10
	}
	// The P3 filesystem policy is written out explicitly rather than left to
	// load-time defaulting: yaml.Marshal renders a nil slice as `[]`, which
	// decodes back as an *empty* (non-nil) slice, so an omitted policy would come
	// back as "deny nothing, exclude nothing" — no sensitive-file protection on a
	// freshly enrolled node. Writing the documented defaults (ADR 0015) also
	// gives the operator a visible place to extend them.
	cfg := &config.Config{
		Server:  config.ServerConfig{URL: wsURL, AllowInsecure: insecure},
		Node:    config.NodeConfig{Name: p.NodeName},
		Runtime: runtimes,
		Workspace: config.WorkspaceConfig{
			AllowedRoots:        p.WorkspaceRoots,
			ExcludedDirectories: append([]string(nil), config.DefaultExcludedDirs...),
		},
		Filesystem: config.FilesystemConfig{
			MaxPreviewSize:    config.DefaultMaxPreviewSize,
			DeniedPatterns:    append([]string(nil), config.DefaultDeniedPatterns...),
			DeniedDirectories: append([]string(nil), config.DefaultDeniedDirectories...),
			Search: config.SearchConfig{
				MaxDepth:       config.DefaultSearchMaxDepth,
				MaxResults:     config.DefaultSearchMaxResults,
				MaxScanned:     config.DefaultSearchMaxScanned,
				TimeoutSeconds: config.DefaultSearchTimeoutSec,
			},
		},
		Session:   config.SessionConfig{Backend: "tmux", ScrollbackLimit: 5000},
		Heartbeat: config.HeartbeatConfig{IntervalSeconds: heartbeat},
	}
	if err := cfg.Validate(); err != nil {
		return nil, fmt.Errorf("generated config is invalid: %w", err)
	}
	return cfg, nil
}

// MarshalConfig serializes a config for writing to config.yaml (0600).
func MarshalConfig(cfg *config.Config) ([]byte, error) {
	return yaml.Marshal(cfg)
}
