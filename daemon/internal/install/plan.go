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
	// PrivilegedTerminal records the posture chosen at install time so the generated
	// config reports it (ADR 0023). The grant itself is the systemd unit plus the
	// sudoers drop-in; this is what the node tells Central about itself.
	PrivilegedTerminal bool
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
		// The system terminal ships enabled (ADR 0021). Detection still decides
		// whether it is *usable*: a node without the binary reports
		// available:false and Central refuses the request with RUNTIME_NOT_FOUND.
		config.ShellRuntimeID: {Enabled: true, Binary: config.DefaultShellBinary},
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
		rc := config.RuntimeConfig{Enabled: true, Binary: binary}
		// Written explicitly rather than left to load-time defaulting, for the same
		// reason the shell and tunnel blocks are: the node owner's only way to refuse
		// this posture is a key they can see (ADR 0023 D2).
		if config.SandboxBypassRuntimeIDs[r.Runtime] {
			bypass := true
			rc.SandboxBypass = &bypass
		}
		runtimes[r.Runtime] = rc
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
		Node:    config.NodeConfig{Name: p.NodeName, PrivilegedTerminal: p.PrivilegedTerminal},
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
			Projection: config.ProjectionConfig{
				RetentionDays:        config.DefaultProjectionRetentionDays,
				CleanupIntervalHours: config.DefaultProjectionCleanupHours,
			},
		},
		Session:   config.SessionConfig{Backend: "tmux", ScrollbackLimit: 5000},
		Heartbeat: config.HeartbeatConfig{IntervalSeconds: heartbeat},
		// Written out with its explanation rather than left absent. An absent block would
		// behave identically (it defaults to "do not veto"), but the owner's only veto would
		// then live in a file that does not mention it — and the same omission would leave
		// them looking for the provider credential here, where it deliberately is not.
		Tunnel: config.TunnelConfig{
			Enabled:        &tunnelEnabledByDefault,
			KnownHostsPath: config.DefaultKnownHostsPath,
		},
	}
	if err := cfg.Validate(); err != nil {
		return nil, fmt.Errorf("generated config is invalid: %w", err)
	}
	return cfg, nil
}

// shellRuntimeComment is written above the runtime.shell block of a generated
// config.yaml. The node's owner holds the only veto over the system terminal
// (ADR 0021 D6), and a veto nobody knows about is not a control — so the file
// says what the block is and how to refuse it, rather than assuming its reader
// has the ADR open.
const shellRuntimeComment = `The system terminal (FR-SHELL-001, ADR 0021): an interactive shell on this
node, opened from the Cliora console by the owner of a session running here.
It is an ordinary session — same RBAC, same audit trail, same limits — and the
commands typed into it are deliberately never recorded.
It ships enabled, and a config that predates this block also counts as enabled.
To refuse it on this node set "enabled: false" below and restart agentd; Central
cannot turn it back on.
The shell grants nothing agentd does not already have: its ceiling is this
service's own execution identity. agentd never runs as root — but on a node
installed with the privileged posture that identity can reach root through sudo,
so the ceiling is root (ADR 0023). See the node block above.`

// sandboxRuntimeComment is written above the runtime.codex block of a generated
// config.yaml. Same reasoning as shellRuntimeComment: the node owner holds the only
// veto, and a veto whose location nobody knows is not a control.
const sandboxRuntimeComment = `codex runs with its approval prompts and OS sandbox disabled on this node
(ADR 0023). agentd adds one fixed flag when starting it:
"--dangerously-bypass-approvals-and-sandbox".
This is the intended posture for a disposable, isolated VM: codex edits files,
installs packages and runs commands here without asking. On a machine you would
not rebuild, set "sandbox_bypass: false" below and restart agentd.
The flag itself is not configurable — agentd owns it, and neither the console nor
Central can name a command, argument or environment variable for a session
(SEC-002). This switch only decides whether agentd's own flag is applied.
If the installed codex does not recognise the flag, agentd launches without it and
the console shows the sandbox as enforced rather than claiming otherwise.`

// privilegedTerminalComment is written above the node block when the posture is on.
// It says what the key is *not*, because a boolean named privileged_terminal reads
// like the switch that grants the privilege, and editing it changes nothing.
const privilegedTerminalComment = `This node's identity and posture.
"privileged_terminal: true" REPORTS that the system terminal can reach root
through sudo on this machine; it does not grant it, and setting it to false does
not take it away. The grant is the systemd unit (no NoNewPrivileges) plus
/etc/sudoers.d/60-agentd.
To actually change the posture: sudo agentd posture --privileged-terminal=false
To see what is installed right now: sudo agentd posture`

// tunnelEnabledByDefault is addressable so the generated config can carry an explicit
// `enabled: true` rather than an absent key. Same value either way; the difference is
// whether the file tells its reader that the switch exists.
var tunnelEnabledByDefault = true

// tunnelComment is written above the tunnel block of a generated config.yaml. Same
// reasoning as shellRuntimeComment: the node's owner holds the only veto the platform
// cannot override, and a veto whose location nobody knows is not a control. This one has an
// extra job — telling the reader that the provider credential is *not* in this file, so
// they do not go looking for a field that no longer exists.
const tunnelComment = `Port forwarding (FR-TUNNEL-001, ADR 0022): the Cliora console can expose a port
on this machine through a third-party tunnel provider, so a web app running here
can be opened from a browser elsewhere.
Two things are worth knowing before leaving this enabled:
  * The provider terminates TLS and can see the unencrypted HTTP content of
    whatever is forwarded. This is for previewing work in progress, not for
    anything holding real data.
  * The provider credential is NOT in this file. It is held by the platform and
    sent with each request, so nothing about it is stored on this machine.
The platform decides whether the feature exists at all and which nodes take part.
This block is this machine's refusal: set "enabled: false" and restart agentd, and
no request from Central can turn it back on. "allowed_ports" narrows what may be
forwarded; ports below 1024 are never forwarded whatever it says.
Like the shell, a tunnel grants nothing agentd does not already have — its ceiling
is this service's own execution identity, which on a privileged node can reach root
through sudo (ADR 0023).`

// MarshalConfig serializes a config for writing to config.yaml (0600). It goes
// through a yaml.Node rather than straight to bytes so the shell block can carry
// its explanation into the file; struct marshalling cannot emit comments.
func MarshalConfig(cfg *config.Config) ([]byte, error) {
	var doc yaml.Node
	if err := doc.Encode(cfg); err != nil {
		return nil, err
	}
	// Absent when this node has no shell binary: BuildConfig only writes runtimes
	// that were detected, and a comment about a block that is not there would be
	// worse than none.
	if key := mappingKey(mappingValue(&doc, "runtime"), config.ShellRuntimeID); key != nil {
		key.HeadComment = shellRuntimeComment
	}
	if key := mappingKey(&doc, "tunnel"); key != nil {
		key.HeadComment = tunnelComment
	}
	// Absent when the node has no codex binary: BuildConfig only writes detected
	// runtimes, and a comment about a block that is not there is worse than none.
	if key := mappingKey(mappingValue(&doc, "runtime"), "codex"); key != nil {
		key.HeadComment = sandboxRuntimeComment
	}
	if cfg.Node.PrivilegedTerminal {
		if key := mappingKey(&doc, "node"); key != nil {
			key.HeadComment = privilegedTerminalComment
		}
	}
	return yaml.Marshal(&doc)
}

// mappingKey returns the key node named name in a mapping, or nil. yaml.Node
// mappings store keys and values as alternating entries in Content.
func mappingKey(node *yaml.Node, name string) *yaml.Node {
	if node == nil || node.Kind != yaml.MappingNode {
		return nil
	}
	for i := 0; i+1 < len(node.Content); i += 2 {
		if node.Content[i].Value == name {
			return node.Content[i]
		}
	}
	return nil
}

// mappingValue returns the value node for the key named name, or nil.
func mappingValue(node *yaml.Node, name string) *yaml.Node {
	if node == nil || node.Kind != yaml.MappingNode {
		return nil
	}
	for i := 0; i+1 < len(node.Content); i += 2 {
		if node.Content[i].Value == name {
			return node.Content[i+1]
		}
	}
	return nil
}
