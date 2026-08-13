// Package config loads and validates the typed agentd configuration and
// credentials (PRD §13, ADR 0011). Config and credential files must be 0600 and
// the daemon must not run as root (SEC-007 / tech §23 #13).
package config

import (
	"errors"
	"fmt"
	"log/slog"
	"os"
	"path/filepath"
	"sort"
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
	// PrivilegedTerminal reports that this machine's system terminal can reach root
	// through sudo (ADR 0023). It is a *report*, not an authorization: the grant is
	// the sudoers drop-in plus the absence of NoNewPrivileges in the systemd unit,
	// and setting this to false does not take sudo away. It exists so the daemon can
	// tell Central what posture this machine is in without parsing systemd state at
	// runtime; `agentd posture` keeps the two in sync and `agentd doctor` reports
	// when they disagree.
	PrivilegedTerminal bool `yaml:"privileged_terminal"`
}

type RuntimeConfig struct {
	Enabled bool   `yaml:"enabled"`
	Binary  string `yaml:"binary"`
	// SandboxBypass turns off the runtime's own approval prompts and OS sandbox by
	// adding the daemon's fixed flag set for that runtime (runtime/launch.go).
	// Absent → enabled, the same way runtime.shell defaults (ADR 0021/0023): an
	// upgraded node takes the posture without an operator editing a file, which is
	// a capability change, which is why Load records where the value came from.
	//
	// Only the runtimes in SandboxBypassRuntimeIDs accept this key; Validate
	// refuses it elsewhere rather than ignoring it, because a silently ignored
	// setting reads exactly like a setting that worked.
	//
	// There is deliberately no args/flags field here. The node decides whether the
	// daemon's fixed flags apply, never what they are (SEC-002, ADR 0023 §2.4).
	SandboxBypass *bool `yaml:"sandbox_bypass"`
}

// BypassSandbox reports the effective sandbox_bypass value: absent means enabled
// (ADR 0023 D2). Callers that hand-build a RuntimeConfig (installer detection,
// doctor) get the same default as a config file that omits the key.
func (r RuntimeConfig) BypassSandbox() bool {
	return r.SandboxBypass == nil || *r.SandboxBypass
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
	// Projection controls retention for platform-owned context packs. It is
	// separate from Upload because uploads are user content with a different
	// lifecycle and must never be touched by this sweep (ADR 0028).
	Projection ProjectionConfig `yaml:"projection"`
	// Upload bounds both write paths into the workspace: image drop (ADR 0024)
	// and general file upload (ADR 0026, the nested Files block).
	Upload UploadConfig `yaml:"upload"`
}

type ProjectionConfig struct {
	RetentionDays        int `yaml:"retention_days"`
	CleanupIntervalHours int `yaml:"cleanup_interval_hours"`
}

// UploadConfig bounds image drop, the one path by which anything may be written
// into a workspace (ADR 0024, FR-FILE-009).
//
// There is deliberately no `directory`, `filename_template` or `allowed_types`
// key here. The target directory and the file name belong to the daemon —
// letting a config name them would re-open path traversal and overwrite through
// the back door — and the accepted formats are part of the wire contract, so
// changing them means changing the contract and all three consumers.
type UploadConfig struct {
	// Enabled is a pointer so that "absent" and "explicitly false" stay
	// distinguishable: absent means the node inherited the behaviour from an
	// upgrade, and the startup log has to be able to say so (see
	// UploadFromDefault). Same reasoning as TunnelConfig.Enabled.
	Enabled *bool `yaml:"enabled"`
	// MaxBytes caps a single image. The wire schema caps the base64 form at the
	// matching length, so an over-size request is refused before it is decoded.
	MaxBytes int64 `yaml:"max_bytes"`
	// MaxSessionBytes and MaxFilesPerDay are the cumulative quota (ADR 0024 W2).
	// Without them, a write path is a disk-exhaustion entry point.
	MaxSessionBytes int64 `yaml:"max_session_bytes"`
	MaxFilesPerDay  int   `yaml:"max_files_per_day"`
	// RetentionDays is how long a dropped image survives. It is not "until the
	// session ends": a CLI transcript keeps referring to the file, and a
	// vanished image reads to the user as the model losing its memory.
	RetentionDays int `yaml:"retention_days"`
	// Files bounds general file upload (ADR 0026). It is nested rather than a
	// sibling because it shares MaxBytes above: one ceiling for both paths, so
	// they cannot drift into disagreeing about what fits in a frame.
	Files FileUploadConfig `yaml:"files"`
}

// FileUploadConfig bounds general file upload, the second write path into a
// workspace (ADR 0026, FR-FILE-010).
//
// Unlike UploadConfig there is no retention key, and its absence is the design:
// these files land where the *user* chose, so they are the user's data from the
// moment they arrive. Deleting them on a timer would be the opposite of what a
// quota exists to prevent (ADR 0024 W2, as refined by ADR 0026 §5). What replaces
// retention is MinFreeBytes — it addresses the exhaustion risk directly instead
// of by expiry.
type FileUploadConfig struct {
	// Enabled is a pointer for the same reason as UploadConfig.Enabled, and it is
	// a *separate* switch: "may the platform put screenshots in .cliora/" and
	// "may it put arbitrary files anywhere in my workspace" are different-sized
	// grants, and a node owner is entitled to answer them differently.
	Enabled *bool `yaml:"enabled"`
	// MaxSessionBytes and MaxFilesPerDay are counted in memory and reset when
	// agentd restarts: unlike image drop, these files are scattered across
	// locations the daemon does not track, so there is nothing to recount from.
	// They bound a broken client; a determined user holds terminal.operate and
	// can write files directly (ADR 0026 §5).
	MaxSessionBytes int64 `yaml:"max_session_bytes"`
	MaxFilesPerDay  int   `yaml:"max_files_per_day"`
	// MinFreeBytes refuses an upload that would leave the workspace filesystem
	// below this much free space. A pointer for the same reason as Enabled: an
	// explicit 0 means "do not check" (some container filesystems report figures
	// that mean nothing), and that has to stay distinguishable from absent.
	MinFreeBytes *int64 `yaml:"min_free_bytes"`
}

// FileUploadEnabled reports whether general file upload is on, treating an
// absent key as on (ADR 0026 §9: default true, acquired by upgrade, announced in
// the release note and the runbook).
func (f FileUploadConfig) FileUploadEnabled() bool { return f.Enabled == nil || *f.Enabled }

// MinFree is the free-space floor, with an absent key meaning the default. A
// configured 0 disables the check and is returned as 0.
func (f FileUploadConfig) MinFree() int64 {
	if f.MinFreeBytes == nil {
		return DefaultFileUploadMinFreeBytes
	}
	return *f.MinFreeBytes
}

// UploadEnabled reports whether image drop is on, treating an absent key as on
// (see D8: default true, acquired by upgrade, announced in the release note).
func (u UploadConfig) UploadEnabled() bool { return u.Enabled == nil || *u.Enabled }

// RunnerConfig bounds the agent runner (ADR 0029/0031). Every field here answers a
// question about **this machine**, never about the work: what it may fetch, how much
// disk it will lend, and how long it keeps the evidence.
//
// The one field with no default worth arguing about is WorkDir. It defaults to
// systemd's StateDirectory, and wherever it points, the daemon **refuses to start in
// runner mode if it overlaps any allowed root** (§3.6). That is a refusal rather than
// a warning because the failure mode is two authorization models becoming reachable
// from each other, and a daemon that warns and starts anyway leaves that live for
// months.
type RunnerConfig struct {
	// Enabled turns runner mode on. Absent means off: a machine does not start
	// running unattended work because it was upgraded.
	Enabled bool `yaml:"enabled"`
	// WorkDir is the run root. Empty means <StateDirectory>/.cliora/runs, i.e.
	// /var/lib/agentd/.cliora/runs. The `.cliora` segment is kept deliberately: the
	// ruling asked for a hidden directory by that name, and it inherits an accidental
	// benefit — image drop already writes a `.cliora/.gitignore` containing `*`, so a
	// work_dir that lands inside a repository is ignored by git anyway. A softened
	// worst case, not something the design leans on.
	WorkDir string `yaml:"work_dir"`
	// MaxConcurrent runs at once, and MaxWaiting runs parked on a human's reply. Two
	// numbers because a run in waiting_for_input holds no process and must not occupy
	// execution capacity (ADR 0029 §5).
	MaxConcurrent int `yaml:"max_concurrent"`
	MaxWaiting    int `yaml:"max_waiting"`
	// PollIntervalSeconds between polls when there is spare capacity. A runner at
	// capacity simply stops polling — backpressure is structural, and there is no
	// "capacity: 0" frame.
	PollIntervalSeconds int `yaml:"poll_interval_seconds"`
	// IdleTimeoutSeconds is the **primary liveness judgement**: how long the child may
	// go without emitting an event on its JSONL stream. **Do not lower this without a
	// measurement.** Killing an agent that is working re-queues the card, so one wrong
	// kill is usually three (ADR 0029 §4, M-AR-9).
	IdleTimeoutSeconds int `yaml:"idle_timeout_seconds"`
	// RunQuotaBytes caps one run directory; TotalQuotaBytes caps all of them together.
	// Exceeding the first fails that run; exceeding the second **stops polling** and
	// reports why — "out of disk" and "machine is gone" are different facts and a
	// person reacts differently to each.
	RunQuotaBytes   int64 `yaml:"run_quota_bytes"`
	TotalQuotaBytes int64 `yaml:"total_quota_bytes"`
	// MinFreeBytes is the free-space floor, and it deliberately reuses image drop's
	// default: the agent's clones and the user's uploads compete for one disk, and two
	// different floors would let one starve the other.
	MinFreeBytes *int64 `yaml:"min_free_bytes"`
	// RetentionSuccessDays / RetentionFailedDays are how long a finished run's
	// directory is kept. A failed run's is kept far longer because that is the one
	// somebody comes back to look at.
	RetentionSuccessDays int `yaml:"retention_success_days"`
	RetentionFailedDays  int `yaml:"retention_failed_days"`

	// Tags is what this machine declares about its own capabilities, reported with
	// `runner.register` and matched as a superset against a card's `required_labels`
	// (ADR 0029 amendment B3). **A tag is not authorization**: it is a value this
	// machine reports about itself, so reporting one more changes what it is offered.
	// The authorization boundary is enrollment (ADR 0032 §0).
	Tags []string `yaml:"tags"`
	// RunUntagged off means this runner only claims cards that declare at least one
	// tag — the only way to reserve a machine for particular work, since a dedicated
	// box otherwise fills with ordinary untagged cards.
	//
	// AcceptSecrets off means it is only ever offered cards with no `required_secrets`.
	// It is the node operator's veto, declared by the person who knows what else runs
	// on this machine (ADR 0032 §0, compensating control 2).
	//
	// **Both are pointers, and that is load-bearing.** A bool's zero value is false,
	// but an absent key has to mean *true* — the default has to equal the behaviour
	// before the upgrade. Plain bools would make an existing config file that never
	// mentioned these silently stop claiming anything.
	RunUntagged   *bool `yaml:"run_untagged"`
	AcceptSecrets *bool `yaml:"accept_secrets"`

	Git RunnerGitConfig `yaml:"git"`
}

// RunUntaggedValue and AcceptSecretsValue resolve the two tri-state declarations.
// Absent means true for both, matching the column defaults on Central and therefore
// leaving behaviour unchanged across an upgrade.
func (r RunnerConfig) RunUntaggedValue() bool {
	return r.RunUntagged == nil || *r.RunUntagged
}

func (r RunnerConfig) AcceptSecretsValue() bool {
	return r.AcceptSecrets == nil || *r.AcceptSecrets
}

// TagList is the declared tags, normalised and **never nil**.
//
// Never nil is not defensive style: a nil slice marshals to `null`, the contract says
// `labels` is an array, and Central's decoder drops a frame that fails validation
// *silently*. That exact defect cost a debugging session in V2.2 when `runtimes` went
// out as null and the runner simply never appeared, with neither end reporting an
// error (plan/18/09-…md §3 item 17).
//
// Sorted and de-duplicated so that "what did this node report" is stable across
// restarts and a config file's ordering does not show up as a change on the Agents page.
func (r RunnerConfig) TagList() []string {
	seen := map[string]struct{}{}
	tags := []string{}
	for _, tag := range r.Tags {
		trimmed := strings.TrimSpace(tag)
		if trimmed == "" {
			continue
		}
		if _, dup := seen[trimmed]; dup {
			continue
		}
		seen[trimmed] = struct{}{}
		tags = append(tags, trimmed)
	}
	sort.Strings(tags)
	return tags
}

// RunnerGitConfig is the node's own half of the two-layer host check. Central has a
// deployment-wide allowlist and this is the machine's; **both must pass**, the same
// split `authorize_workspace` and the daemon's own path containment already use —
// Central is the coarse filter, the node is the final authority.
type RunnerGitConfig struct {
	AllowedHosts []string `yaml:"allowed_hosts"`
	// KnownHostsPath pins ssh host keys. A separate file from the tunnel's, because
	// the host lists are different, but the same posture: pin the keys rather than
	// turn strict host key checking off. (Spelling the disabling form out here would
	// trip `test_no_source_disables_provider_host_key_verification`, which scans the
	// whole tree for it — and that guard is right to.)
	KnownHostsPath string `yaml:"known_hosts_path"`
	// FetchTimeoutSeconds bounds one clone. Missing credentials are meant to fail in
	// seconds, not to hang until the wall clock — the idle timer cannot save that case
	// because the clone happens before there is any event stream to measure.
	FetchTimeoutSeconds int `yaml:"fetch_timeout_seconds"`
	// IsolateAmbientCredentials hides the machine's own git credentials from a run —
	// **but only when that run actually received a platform credential** (ADR 0031
	// amendment A3). Applying it unconditionally would hide them and supply no
	// replacement, so on the default deployment (where platform-managed git
	// credentials are off) every private-repository clone would fail, and the symptom
	// would look like a misconfigured credential rather than a policy.
	//
	// A pointer for the same reason `run_untagged` is one: absent has to mean the
	// documented default, which here is `true`.
	IsolateAmbientCredentials *bool `yaml:"isolate_ambient_credentials"`
}

// IsolateAmbient resolves the tri-state. Absent means true.
func (g RunnerGitConfig) IsolateAmbient() bool {
	return g.IsolateAmbientCredentials == nil || *g.IsolateAmbientCredentials
}

// Runner defaults. The two quotas come from M11/M12 (plan/18/10-…md §1.3): a checkout
// is ~17 MB, but a run that installs its dependencies is ~390 MB — so the order of
// magnitude is GB, not MB, and the headroom above the measured figure is a judgement
// rather than a measurement.
const (
	DefaultRunnerMaxConcurrent         = 1
	DefaultRunnerMaxWaiting            = 5
	DefaultRunnerPollInterval          = 5
	DefaultRunnerIdleTimeout           = 300
	DefaultRunnerRunQuotaBytes   int64 = 2 * 1024 * 1024 * 1024
	DefaultRunnerTotalQuotaBytes int64 = 8 * 1024 * 1024 * 1024
	DefaultRunnerRetentionOK           = 3
	DefaultRunnerRetentionFailed       = 14
	DefaultRunnerFetchTimeout          = 900
	// DefaultRunnerStateDir is where systemd's StateDirectory=agentd lands.
	DefaultRunnerStateDir = "/var/lib/agentd"
)

// MinFree is the free-space floor, with an absent key meaning image drop's default
// and an explicit 0 meaning "do not check".
func (r RunnerConfig) MinFree() int64 {
	if r.MinFreeBytes == nil {
		return DefaultFileUploadMinFreeBytes
	}
	return *r.MinFreeBytes
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

// Image-drop defaults (ADR 0024). DefaultUploadMaxBytes is chosen from the frame
// budget, not from taste: 4 MiB of image is 5.33 MiB of base64, which still fits
// the 8 MiB MaxFilePayload with room for the JSON envelope.
const (
	DefaultUploadMaxBytes        int64 = 4 * 1024 * 1024
	DefaultUploadMaxSessionBytes int64 = 64 * 1024 * 1024
	DefaultUploadMaxFilesPerDay        = 200
	DefaultUploadRetentionDays         = 7
)

// File-upload defaults (ADR 0026). The per-file ceiling is deliberately absent:
// it is DefaultUploadMaxBytes above, shared with image drop, and
// TestUploadCapFitsFrameBound asserts that it still fits the frame.
const (
	DefaultFileUploadMaxSessionBytes int64 = 256 * 1024 * 1024
	DefaultFileUploadMaxFilesPerDay        = 200
	DefaultFileUploadMinFreeBytes    int64 = 512 * 1024 * 1024
	DefaultProjectionRetentionDays         = 30
	DefaultProjectionCleanupHours          = 6
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
	Runner     RunnerConfig             `yaml:"runner"`

	// ShellFromDefault reports that runtime.shell was absent and defaulted to
	// enabled, rather than being written by an operator. Never serialised.
	ShellFromDefault bool `yaml:"-"`

	// UploadFromDefault reports that filesystem.upload.enabled was absent and
	// defaulted to enabled, rather than being written by an operator. Surfaced
	// at startup because a workspace that the platform may now write into is a
	// fact the node's owner should not learn by accident. Never serialised.
	UploadFromDefault bool `yaml:"-"`

	// FileUploadFromDefault is the same fact for filesystem.upload.files.enabled
	// (ADR 0026). Tracked separately because a node can have chosen image drop
	// explicitly while acquiring general file upload from an upgrade — and the
	// second one is the wider grant, so conflating them would report the wrong
	// posture. Never serialised.
	FileUploadFromDefault bool `yaml:"-"`

	// SandboxBypassFromDefault records, per runtime id, that sandbox_bypass was
	// absent and defaulted to enabled rather than being chosen. Surfaced in the
	// startup log because "the operator asked for this" and "an upgrade did this"
	// are different facts about a machine that now runs a CLI without a sandbox.
	// Never serialised.
	SandboxBypassFromDefault map[string]bool `yaml:"-"`

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

// SandboxBypassRuntimeIDs are the runtimes for which sandbox_bypass means
// something. It is deliberately not "every CLI runtime": claude's approval model
// is different and was not part of the ADR 0023 decision, and the shell is the
// operator's own shell, which has no sandbox to speak of. A runtime with no entry
// in the daemon's flag table (runtime/launch.go) must not accept the key either —
// runtime's tests assert the two stay in step.
var SandboxBypassRuntimeIDs = map[string]bool{"codex": true}

// Scrollback bounds for the tmux history the browser can scroll through
// (FR-TERM-004.AC-04 requires at least 5000 lines). The floor is applied rather
// than enforced by an error: an existing node with a smaller value must still
// start, and the requirement is the platform's promise, not the operator's.
const (
	MinScrollbackLimit = 5000
	MaxScrollbackLimit = 200000
)

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
	cfg.applySessionDefaults()
	cfg.applyTunnelDefaults()
	cfg.applyRunnerDefaults()
	if err := cfg.Validate(); err != nil {
		return nil, err
	}
	return &cfg, nil
}

// applyRunnerDefaults fills the absent runner keys. It never flips `enabled`: a
// machine must not begin running unattended work because it was upgraded, which is
// the opposite of the image-drop default and deliberately so — that grant lets the
// platform put a file somewhere, this one starts a process.
func (c *Config) applyRunnerDefaults() {
	r := &c.Runner
	if r.WorkDir == "" {
		r.WorkDir = filepath.Join(DefaultRunnerStateDir, ".cliora", "runs")
	}
	if r.MaxConcurrent <= 0 {
		r.MaxConcurrent = DefaultRunnerMaxConcurrent
	}
	if r.MaxWaiting <= 0 {
		r.MaxWaiting = DefaultRunnerMaxWaiting
	}
	if r.PollIntervalSeconds <= 0 {
		r.PollIntervalSeconds = DefaultRunnerPollInterval
	}
	if r.IdleTimeoutSeconds <= 0 {
		r.IdleTimeoutSeconds = DefaultRunnerIdleTimeout
	}
	if r.RunQuotaBytes <= 0 {
		r.RunQuotaBytes = DefaultRunnerRunQuotaBytes
	}
	if r.TotalQuotaBytes <= 0 {
		r.TotalQuotaBytes = DefaultRunnerTotalQuotaBytes
	}
	if r.RetentionSuccessDays <= 0 {
		r.RetentionSuccessDays = DefaultRunnerRetentionOK
	}
	if r.RetentionFailedDays <= 0 {
		r.RetentionFailedDays = DefaultRunnerRetentionFailed
	}
	if r.Git.FetchTimeoutSeconds <= 0 {
		r.Git.FetchTimeoutSeconds = DefaultRunnerFetchTimeout
	}
}

// applyRuntimeDefaults enables the system terminal when the config says nothing
// about it. An explicit `enabled: false` is left alone — the node operator's veto
// must survive every future default change, so this only ever fills an absent key.
func (c *Config) applyRuntimeDefaults() {
	if c.Runtime == nil {
		c.Runtime = map[string]RuntimeConfig{}
	}
	if _, ok := c.Runtime[ShellRuntimeID]; !ok {
		c.Runtime[ShellRuntimeID] = RuntimeConfig{Enabled: true, Binary: DefaultShellBinary}
		c.ShellFromDefault = true
	}
	// Same rule for sandbox_bypass, and for the same reason: an absent key means
	// enabled (ADR 0023 D2), and an explicit `false` is an operator decision that
	// no future default change may overwrite. Only a runtime that is actually
	// present gets the key filled in — writing it onto a runtime the node does not
	// have would put a setting in memory for a binary that will never launch.
	for id := range SandboxBypassRuntimeIDs {
		rc, ok := c.Runtime[id]
		if !ok || rc.SandboxBypass != nil {
			continue
		}
		enabled := true
		rc.SandboxBypass = &enabled
		c.Runtime[id] = rc
		if c.SandboxBypassFromDefault == nil {
			c.SandboxBypassFromDefault = map[string]bool{}
		}
		c.SandboxBypassFromDefault[id] = true
	}
}

// applySessionDefaults brings the tmux scrollback into the range the product
// promises. This value used to be written into every generated config and read by
// nothing: tmux's own default is 2000 lines, so FR-TERM-004.AC-04 ("at least 5000
// lines") was not met on any node until PV-04 wired it to the tmux config file.
func (c *Config) applySessionDefaults() {
	switch {
	case c.Session.ScrollbackLimit < MinScrollbackLimit:
		if c.Session.ScrollbackLimit > 0 {
			slog.Warn("session.scrollback_limit raised to the required minimum",
				"configured", c.Session.ScrollbackLimit, "using", MinScrollbackLimit)
		}
		c.Session.ScrollbackLimit = MinScrollbackLimit
	case c.Session.ScrollbackLimit > MaxScrollbackLimit:
		// A misplaced zero here costs memory in every pane on the machine, and the
		// symptom (a node that slowly runs out of memory) points nowhere near this
		// file. Clamp and say so.
		slog.Warn("session.scrollback_limit clamped",
			"configured", c.Session.ScrollbackLimit, "using", MaxScrollbackLimit)
		c.Session.ScrollbackLimit = MaxScrollbackLimit
	}
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
	p := &c.Filesystem.Projection
	if p.RetentionDays == 0 {
		p.RetentionDays = DefaultProjectionRetentionDays
	}
	if p.CleanupIntervalHours == 0 {
		p.CleanupIntervalHours = DefaultProjectionCleanupHours
	}
	u := &c.Filesystem.Upload
	if u.Enabled == nil {
		// Record that nobody chose this. "The operator asked for it" and "an
		// upgrade did it" are different facts about a machine whose workspace
		// can now be written to, and the startup log must be able to tell them
		// apart (same treatment as SandboxBypassFromDefault).
		c.UploadFromDefault = true
	}
	if u.MaxBytes <= 0 {
		u.MaxBytes = DefaultUploadMaxBytes
	}
	if u.MaxSessionBytes <= 0 {
		u.MaxSessionBytes = DefaultUploadMaxSessionBytes
	}
	if u.MaxFilesPerDay <= 0 {
		u.MaxFilesPerDay = DefaultUploadMaxFilesPerDay
	}
	if u.RetentionDays <= 0 {
		u.RetentionDays = DefaultUploadRetentionDays
	}
	f := &u.Files
	if f.Enabled == nil {
		// Same reasoning as UploadFromDefault, and it has to be recorded
		// separately: a node can have chosen image drop explicitly while
		// acquiring file upload from an upgrade.
		c.FileUploadFromDefault = true
	}
	if f.MaxSessionBytes <= 0 {
		f.MaxSessionBytes = DefaultFileUploadMaxSessionBytes
	}
	if f.MaxFilesPerDay <= 0 {
		f.MaxFilesPerDay = DefaultFileUploadMaxFilesPerDay
	}
	// MinFreeBytes is left as-is: absent (nil) and an explicit 0 mean different
	// things, and MinFree() resolves that rather than a default written here.
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
		if rc.SandboxBypass != nil && !SandboxBypassRuntimeIDs[id] {
			return fmt.Errorf(
				"runtime %q does not support sandbox_bypass (only codex); remove the key "+
					"rather than expecting it to be ignored", id)
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
	p := c.Filesystem.Projection
	if p.RetentionDays < 0 || p.CleanupIntervalHours < 0 {
		return errors.New("filesystem.projection retention and cleanup interval must not be negative")
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
