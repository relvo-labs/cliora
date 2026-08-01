// Package config loads and validates the typed agentd configuration and
// credentials (PRD §13, ADR 0011). Config and credential files must be 0600 and
// the daemon must not run as root (SEC-007 / tech §23 #13).
package config

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"gopkg.in/yaml.v3"
)

const (
	DefaultConfigPath      = "/etc/agentd/config.yaml"
	DefaultCredentialsPath = "/etc/agentd/credentials.yaml"
)

type ServerConfig struct {
	URL string `yaml:"url"`
	// AllowInsecure permits ws:// (dev only); production requires wss:// (ADR 0007).
	AllowInsecure bool `yaml:"allow_insecure"`
}

type NodeConfig struct {
	Name string `yaml:"name"`
}

type RuntimeConfig struct {
	Enabled bool   `yaml:"enabled"`
	Binary  string `yaml:"binary"`
}

type WorkspaceConfig struct {
	AllowedRoots     []string `yaml:"allowed_roots"`
	ExcludedPatterns []string `yaml:"excluded_patterns"`
	// ExcludedDirectories are shown in a listing but not auto-loaded/searched
	// (tech §11.4): large or low-value trees like node_modules. Matched against a
	// directory's base name.
	ExcludedDirectories []string `yaml:"excluded_directories"`
}

// FilesystemConfig bounds the read-only workspace preview relay (P3, tech §11,
// ADR 0015). max_preview_size caps the bytes returned for a single file preview
// so a large or binary file cannot exhaust memory; denied_patterns/directories
// implement the sensitive-file policy; search bounds cap filename search.
type FilesystemConfig struct {
	MaxPreviewSize int64 `yaml:"max_preview_size"`
	// DeniedPatterns are glob patterns matched against a file's base name
	// (filepath.Match); a match denies preview (FILE_DENIED). Empty → defaults.
	DeniedPatterns []string `yaml:"denied_patterns"`
	// DeniedDirectories deny everything beneath a path segment matching the
	// pattern (e.g. ".ssh"). Empty → defaults.
	DeniedDirectories []string     `yaml:"denied_directories"`
	Search            SearchConfig `yaml:"search"`
}

// SearchConfig bounds filename search so a request cannot walk an unbounded
// tree (tech §11.8, ADR 0015).
type SearchConfig struct {
	MaxDepth       int `yaml:"max_depth"`
	MaxResults     int `yaml:"max_results"`
	MaxScanned     int `yaml:"max_scanned"`
	TimeoutSeconds int `yaml:"timeout_seconds"`
}

// DefaultMaxPreviewSize is used when filesystem.max_preview_size is omitted
// (2 MiB, matching tech §11.5 / FR-FILE-003).
const DefaultMaxPreviewSize int64 = 2 * 1024 * 1024

// P3 defaults (ADR 0015). The sensitive policy is deliberately "balanced":
// exact names and extensions plus the narrow ".env.*" glob — the broad
// "*secret*"/"*credentials*" globs are intentionally omitted so source code is
// not denied. Admins extend these lists for environment-specific secrets.
var (
	DefaultDeniedPatterns    = []string{".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx", "id_rsa", "id_ed25519"}
	DefaultDeniedDirectories = []string{".ssh", ".aws", ".gnupg"}
	DefaultExcludedDirs      = []string{".git", "node_modules", ".venv", "dist", "build", "__pycache__"}
)

const (
	DefaultSearchMaxDepth   = 10
	DefaultSearchMaxResults = 200
	DefaultSearchMaxScanned = 50000
	DefaultSearchTimeoutSec = 10
)

type SessionConfig struct {
	Backend         string `yaml:"backend"`
	ScrollbackLimit int    `yaml:"scrollback_limit"`
}

// TunnelConfig is this node's veto and narrowing over the platform's port-forwarding
// settings (P11, ADR 0022). The platform decides whether the integration exists at all
// and holds the provider credential; this file decides whether THIS machine takes part
// and, if so, within which bounds. Every field here can only make the platform's settings
// narrower, never wider.
//
// There is deliberately no token field. The credential is held by the platform and arrives
// with each tunnel.open, so it never touches this machine's disk. A config that still
// carries a `token:` key from an earlier design is accepted with a warning rather than
// refused — refusing would stop the daemon from starting over a key that no longer means
// anything.
type TunnelConfig struct {
	// Enabled false is an absolute veto the platform cannot override. A pointer, not a
	// bool, because "absent" and "explicitly false" are different answers: with a plain
	// bool every existing node would read as vetoed after an upgrade, and nobody would
	// remember vetoing anything.
	Enabled *bool `yaml:"enabled"`
	// AllowedPorts narrows the platform's list ("3000-3999", "5173"). Empty means no extra
	// narrowing. Ports below 1024 are refused whatever any layer says.
	AllowedPorts []string `yaml:"allowed_ports"`
	// MaxTunnels narrows the platform's per-node cap. Zero means no extra narrowing.
	MaxTunnels int `yaml:"max_tunnels"`
	// KnownHostsPath is this node's own pinned host key file, and it overrides the keys
	// embedded in the binary. It exists for one job: pinning a rotated key out of band,
	// before a release carrying it exists. A node without the file is still pinned — see
	// daemon/internal/tunnel/knownhosts.go — so leaving this unset is the normal case.
	// Host key checking is never disabled; see ADR 0022 and PG-01.
	KnownHostsPath string `yaml:"known_hosts_path"`
	// Token is only here so that a config written under the earlier design (where the
	// node held the credential) still parses. It is never read, never sent and never
	// logged. Load warns and clears it.
	Token string `yaml:"token"`
}

// DefaultKnownHostsPath is where the installer places the provider's pinned host keys.
const DefaultKnownHostsPath = "/etc/agentd/pinggy_known_hosts"

// MinTunnelPort is a floor no configuration can lower. Below it live system services —
// sshd, and on many machines a database — and the cost of getting this wrong is
// publishing one of them to the internet.
const MinTunnelPort = 1024

type HeartbeatConfig struct {
	IntervalSeconds int `yaml:"interval_seconds"`
}

type Config struct {
	Server     ServerConfig             `yaml:"server"`
	Node       NodeConfig               `yaml:"node"`
	Runtime    map[string]RuntimeConfig `yaml:"runtime"`
	Workspace  WorkspaceConfig          `yaml:"workspace"`
	Filesystem FilesystemConfig         `yaml:"filesystem"`
	Session    SessionConfig            `yaml:"session"`
	Heartbeat  HeartbeatConfig          `yaml:"heartbeat"`
	Tunnel     TunnelConfig             `yaml:"tunnel"`

	// ShellFromDefault reports that runtime.shell was absent and defaulted to
	// enabled, rather than being written by an operator. Never serialised.
	ShellFromDefault bool `yaml:"-"`

	// LegacyTunnelToken records that the config carried a `tunnel.token` key, which the
	// platform now holds instead. Surfaced at startup so the node owner learns the key is
	// dead rather than assuming it is in use. Never serialised.
	LegacyTunnelToken bool `yaml:"-"`
}

// AllowedRuntimeIDs is the closed allowlist; no other runtime id may appear.
var AllowedRuntimeIDs = map[string]bool{"claude": true, "codex": true, "shell": true}

// ShellRuntimeID is the system terminal (FR-SHELL-001, ADR 0021). Unlike the CLI
// runtimes it is enabled by default, including on a config that predates it, so
// an upgraded node gains the capability without the operator editing a file.
// That is a capability change, which is why Load records where the setting came
// from and the daemon logs it at startup.
const ShellRuntimeID = "shell"

// DefaultShellBinary is resolved through PATH like any other runtime binary. It
// is a single token on purpose: RuntimeConfig has no argv field, and adding one
// would be the beginning of letting a caller name a command (SEC-002).
const DefaultShellBinary = "bash"

// Load reads, permission-checks, strictly parses, and validates a config file.
func Load(path string) (*Config, error) {
	data, err := readSecureFile(path)
	if err != nil {
		return nil, err
	}
	var cfg Config
	dec := yaml.NewDecoder(strings.NewReader(string(data)))
	dec.KnownFields(true)
	if err := dec.Decode(&cfg); err != nil {
		return nil, fmt.Errorf("parse config: %w", err)
	}
	cfg.applyFilesystemDefaults()
	cfg.applyRuntimeDefaults()
	cfg.applyTunnelDefaults()
	if err := cfg.Validate(); err != nil {
		return nil, err
	}
	return &cfg, nil
}

// applyRuntimeDefaults enables the system terminal when the config says nothing
// about it. An explicit `enabled: false` is left alone — the node operator's veto
// must survive every future default change, so this only ever fills an absent key.
func (c *Config) applyRuntimeDefaults() {
	if _, ok := c.Runtime[ShellRuntimeID]; ok {
		return
	}
	if c.Runtime == nil {
		c.Runtime = map[string]RuntimeConfig{}
	}
	c.Runtime[ShellRuntimeID] = RuntimeConfig{Enabled: true, Binary: DefaultShellBinary}
	c.ShellFromDefault = true
}

// applyFilesystemDefaults fills omitted P3 filesystem/workspace fields with the
// documented defaults (ADR 0015) so an operator only overrides what they need.
func (c *Config) applyFilesystemDefaults() {
	if c.Filesystem.MaxPreviewSize == 0 {
		c.Filesystem.MaxPreviewSize = DefaultMaxPreviewSize
	}
	// The two sensitive-file lists default on *empty*, not just nil: an absent or
	// blank list must never mean "deny nothing". (yaml.Marshal writes a nil slice
	// as `[]`, which decodes back non-nil but empty, so a nil-only check let a
	// generated config ship with no sensitive-file policy at all.) Default-deny
	// cannot be disabled by omission — only replaced by a non-empty list.
	if len(c.Filesystem.DeniedPatterns) == 0 {
		c.Filesystem.DeniedPatterns = append([]string(nil), DefaultDeniedPatterns...)
	}
	if len(c.Filesystem.DeniedDirectories) == 0 {
		c.Filesystem.DeniedDirectories = append([]string(nil), DefaultDeniedDirectories...)
	}
	// Excluded directories keep the nil-only check: this is an ignore rule, not a
	// security control, so an operator may legitimately write
	// `excluded_directories: []` to load everything. The installer always writes
	// the defaults out explicitly, so omission is not how a node ends up with none.
	if c.Workspace.ExcludedDirectories == nil {
		c.Workspace.ExcludedDirectories = append([]string(nil), DefaultExcludedDirs...)
	}
	s := &c.Filesystem.Search
	if s.MaxDepth == 0 {
		s.MaxDepth = DefaultSearchMaxDepth
	}
	if s.MaxResults == 0 {
		s.MaxResults = DefaultSearchMaxResults
	}
	if s.MaxScanned == 0 {
		s.MaxScanned = DefaultSearchMaxScanned
	}
	if s.TimeoutSeconds == 0 {
		s.TimeoutSeconds = DefaultSearchTimeoutSec
	}
}

// applyTunnelDefaults fills in what an absent `tunnel:` block means. Absent is "do not
// veto and do not narrow", because the gate for this capability is the platform's own
// integration switch (ADR 0022): an administrator has to enable it and supply a credential
// before any node can forward anything. Requiring a second per-machine edit on top would
// be form rather than substance on a node that already grants the platform a shell runtime
// (ADR 0021) — and it would silently exclude every node that upgraded.
//
// An explicit `enabled: false` is never touched. That veto has to survive every future
// change to this function.
func (c *Config) applyTunnelDefaults() {
	if c.Tunnel.Token != "" {
		c.LegacyTunnelToken = true
		c.Tunnel.Token = ""
	}
	if c.Tunnel.Enabled == nil {
		enabled := true
		c.Tunnel.Enabled = &enabled
	}
	if c.Tunnel.KnownHostsPath == "" {
		c.Tunnel.KnownHostsPath = DefaultKnownHostsPath
	}
}

// TunnelEnabled reports whether this node takes part in port forwarding. False is the
// node owner's veto, and nothing in the protocol can override it.
func (c *Config) TunnelEnabled() bool {
	return c.Tunnel.Enabled == nil || *c.Tunnel.Enabled
}

// TunnelPortAllowed applies this node's own port policy: the hard floor first, then the
// local allowlist if one is configured. An empty allowlist means "do not narrow further",
// which is different from a list that excludes everything.
func (c *Config) TunnelPortAllowed(port int) bool {
	if port < MinTunnelPort || port > 65535 {
		return false
	}
	if len(c.Tunnel.AllowedPorts) == 0 {
		return true
	}
	for _, spec := range c.Tunnel.AllowedPorts {
		low, high, err := parsePortSpec(spec)
		if err != nil {
			// A malformed entry narrows rather than widens: it is skipped, so it can never
			// accidentally allow a port. Validate() rejects such a config at startup
			// anyway; this is the behaviour if one ever gets past that.
			continue
		}
		if port >= low && port <= high {
			return true
		}
	}
	return false
}

// parsePortSpec accepts "5173" or "3000-3999".
func parsePortSpec(spec string) (int, int, error) {
	trimmed := strings.TrimSpace(spec)
	if trimmed == "" {
		return 0, 0, errors.New("empty port spec")
	}
	low, high, found := strings.Cut(trimmed, "-")
	start, err := strconv.Atoi(strings.TrimSpace(low))
	if err != nil {
		return 0, 0, fmt.Errorf("invalid port %q", low)
	}
	if !found {
		return start, start, nil
	}
	end, err := strconv.Atoi(strings.TrimSpace(high))
	if err != nil {
		return 0, 0, fmt.Errorf("invalid port %q", high)
	}
	if end < start {
		return 0, 0, fmt.Errorf("range %q is inverted", trimmed)
	}
	return start, end, nil
}

func (c *Config) Validate() error {
	if c.Server.URL == "" {
		return errors.New("server.url is required")
	}
	if !c.Server.AllowInsecure && !strings.HasPrefix(c.Server.URL, "wss://") {
		return errors.New("server.url must use wss:// (set server.allow_insecure for dev ws://)")
	}
	if c.Server.AllowInsecure &&
		!strings.HasPrefix(c.Server.URL, "wss://") &&
		!strings.HasPrefix(c.Server.URL, "ws://") {
		return errors.New("server.url must be a ws:// or wss:// URL")
	}
	if c.Node.Name == "" {
		return errors.New("node.name is required")
	}
	for id, rc := range c.Runtime {
		if !AllowedRuntimeIDs[id] {
			return fmt.Errorf("runtime %q is not allowed (only claude, codex, shell)", id)
		}
		if rc.Enabled && rc.Binary == "" {
			return fmt.Errorf("runtime %q is enabled but has no binary", id)
		}
	}
	for _, spec := range c.Tunnel.AllowedPorts {
		low, high, err := parsePortSpec(spec)
		if err != nil {
			return fmt.Errorf("tunnel allowed_ports %q: %w", spec, err)
		}
		if low < MinTunnelPort {
			return fmt.Errorf(
				"tunnel allowed_ports %q includes a port below %d; ports below that are "+
					"never forwarded", spec, MinTunnelPort)
		}
		if high > 65535 {
			return fmt.Errorf("tunnel allowed_ports %q exceeds 65535", spec)
		}
	}
	if c.Tunnel.MaxTunnels < 0 {
		return errors.New("tunnel.max_tunnels must not be negative")
	}
	for _, root := range c.Workspace.AllowedRoots {
		if !filepath.IsAbs(root) {
			return fmt.Errorf("workspace allowed root %q must be absolute", root)
		}
	}
	if c.Heartbeat.IntervalSeconds <= 0 {
		return errors.New("heartbeat.interval_seconds must be positive")
	}
	if c.Filesystem.MaxPreviewSize < 0 {
		return errors.New("filesystem.max_preview_size must be positive")
	}
	for _, p := range c.Filesystem.DeniedPatterns {
		if _, err := filepath.Match(p, "x"); err != nil {
			return fmt.Errorf("filesystem.denied_patterns %q is not a valid glob: %w", p, err)
		}
	}
	s := c.Filesystem.Search
	if s.MaxDepth < 0 || s.MaxResults < 0 || s.MaxScanned < 0 || s.TimeoutSeconds < 0 {
		return errors.New("filesystem.search bounds must not be negative")
	}
	if c.Session.Backend != "" && c.Session.Backend != "tmux" {
		return fmt.Errorf("session.backend %q is not supported", c.Session.Backend)
	}
	return nil
}

// readSecureFile rejects a file that is group- or world-accessible.
func readSecureFile(path string) ([]byte, error) {
	info, err := os.Stat(path)
	if err != nil {
		return nil, fmt.Errorf("stat %s: %w", path, err)
	}
	if info.Mode().Perm()&0o077 != 0 {
		return nil, fmt.Errorf("%s must not be group/world accessible (want 0600, got %o)", path, info.Mode().Perm())
	}
	return os.ReadFile(path)
}
