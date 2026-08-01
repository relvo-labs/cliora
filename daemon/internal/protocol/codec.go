package protocol

import (
	"bytes"
	"encoding/json"
	"errors"
	"path"
	"regexp"
	"strings"
	"time"

	"github.com/google/uuid"
)

const MaxPayload = 64 * 1024

// MaxFilePayload bounds a filesystem response frame (P3). A ≤2 MiB preview
// (FR-FILE-003) plus JSON escaping, or a 2000-entry listing (ADR 0015),
// legitimately exceeds the 64 KiB control bound, so those response types get
// their own — still bounded — ceiling. It must stay in lockstep with Central's
// MAX_FILE_PAYLOAD (backend/app/protocol/codec.py); a frame above it would be
// dropped on decode and the request would time out instead of answering.
const MaxFilePayload = 8 * 1024 * 1024

// LargeFrameTypes are the response types allowed to use MaxFilePayload.
var LargeFrameTypes = map[string]bool{
	"filesystem.entries":       true,
	"filesystem.content":       true,
	"filesystem.search_result": true,
}

const HeaderSize = 18

var allowedTypes = map[string]bool{"session.start": true, "session.started": true, "session.start_failed": true, "session.attach": true, "session.attached": true, "session.stop": true, "session.stopped": true, "session.list": true, "session.list_result": true, "session.recover": true, "session.status_changed": true, "terminal.resize": true, "terminal.detach": true, "terminal.gap": true, "terminal.exited": true, "terminal.error": true, "terminal.control_acquire": true, "terminal.control_release": true, "filesystem.list": true, "filesystem.entries": true, "filesystem.read": true, "filesystem.content": true, "filesystem.search": true, "filesystem.search_result": true, "node.challenge": true, "node.auth": true, "node.authenticated": true, "node.heartbeat": true, "node.register": true, "node.registered": true, "node.system_info": true, "node.runtime_status": true, "node.shutdown": true, "daemon.version": true, "daemon.doctor": true, "daemon.doctor_result": true, "daemon.update": true, "daemon.update_result": true, "tunnel.open": true, "tunnel.opened": true, "tunnel.close": true, "tunnel.closed": true, "tunnel.status": true, "error": true}

type Envelope struct {
	Version   int             `json:"version"`
	Type      string          `json:"type"`
	RequestID string          `json:"request_id"`
	NodeID    uuid.UUID       `json:"node_id"`
	Timestamp string          `json:"timestamp"`
	Payload   json.RawMessage `json:"payload"`
	Success   *bool           `json:"success,omitempty"`
}

func DecodeControl(data []byte) (Envelope, error) {
	if len(data) > MaxPayload {
		return Envelope{}, errors.New("FRAME_TOO_LARGE")
	}
	var raw map[string]json.RawMessage
	if json.Unmarshal(data, &raw) != nil {
		return Envelope{}, errors.New("INVALID_MESSAGE")
	}
	allowed := map[string]bool{"version": true, "type": true, "request_id": true, "node_id": true, "timestamp": true, "payload": true, "success": true, "error": true}
	for key := range raw {
		if !allowed[key] {
			return Envelope{}, errors.New("INVALID_MESSAGE")
		}
	}
	var env Envelope
	if json.Unmarshal(data, &env) != nil {
		return Envelope{}, errors.New("INVALID_MESSAGE")
	}
	if env.Version != 1 {
		return Envelope{}, errors.New("PROTOCOL_VERSION_UNSUPPORTED")
	}
	if !allowedTypes[env.Type] {
		return Envelope{}, errors.New("MESSAGE_TYPE_UNSUPPORTED")
	}
	if len(env.RequestID) != 26 || env.NodeID == uuid.Nil || len(env.Payload) == 0 {
		return Envelope{}, errors.New("INVALID_MESSAGE")
	}
	parsed, err := time.Parse("2006-01-02T15:04:05.999999Z", env.Timestamp)
	if err != nil || parsed.Location() != time.UTC || env.Timestamp[len(env.Timestamp)-1:] != "Z" {
		return Envelope{}, errors.New("INVALID_MESSAGE")
	}
	return env, nil
}

type startFields struct {
	SessionID uuid.UUID `json:"session_id"`
	Runtime   string    `json:"runtime"`
	Workspace string    `json:"workspace"`
	Rows      uint16    `json:"rows"`
	Columns   uint16    `json:"columns"`
}
type sizeFields struct {
	SessionID uuid.UUID `json:"session_id"`
	Rows      uint16    `json:"rows"`
	Columns   uint16    `json:"columns"`
}
type sessionIDFields struct {
	SessionID uuid.UUID `json:"session_id"`
}

// P3 filesystem request payloads (protocol v1.3). These mirror the
// contracts/v1/schemas/messages/filesystem-*.schema.json definitions so Go
// enforces the same accept/reject as the Python (schema) and TypeScript
// consumers. Paths are workspace-relative; absolute/`..`/control-char inputs are
// rejected here and never reach the workspace guard (SEC-001, ADR 0014).
type fsListFields struct {
	SessionID  uuid.UUID `json:"session_id"`
	Path       string    `json:"path"`
	Cursor     string    `json:"cursor,omitempty"`
	EntryLimit int       `json:"entry_limit,omitempty"`
}
type fsReadFields struct {
	SessionID uuid.UUID `json:"session_id"`
	Path      string    `json:"path"`
}
type fsSearchFields struct {
	SessionID  uuid.UUID `json:"session_id"`
	Keyword    string    `json:"keyword"`
	Root       string    `json:"root,omitempty"`
	MaxResults int       `json:"max_results,omitempty"`
}

// P4 daemon self-update payloads (protocol v1.4). daemonUpdateFields is
// deliberately the whole request: a version and an optional downgrade flag.
// There is no field for a URL, filename, path, checksum or binary, so a
// compromised or spoofed control frame cannot make this node fetch or execute an
// artifact of the sender's choosing — the download location and expected digest
// come only from the local config plus Central's release manifest (SEC-002
// extended to the release path, ADR 0017). strictUnmarshal rejects any extra
// field, which is what enforces that.
type daemonUpdateFields struct {
	TargetVersion  string `json:"target_version"`
	AllowDowngrade *bool  `json:"allow_downgrade,omitempty"`
}

type daemonUpdateResultFields struct {
	FromVersion string `json:"from_version"`
	ToVersion   string `json:"to_version"`
	Status      string `json:"status"`
	Stage       string `json:"stage"`
	ErrorCode   string `json:"error_code,omitempty"`
}

// Phase 1 node control-plane payloads (protocol v1.1). These mirror the
// contracts/v1/schemas/messages/node-*.schema.json definitions so Go enforces
// the same accept/reject as the Python (schema-authoritative) and TypeScript
// consumers. additionalProperties:false is enforced by strictUnmarshal's
// DisallowUnknownFields at every nesting level, which is what forbids injecting
// command/argv/env into a node.register.
type runtimeItem struct {
	Runtime    string  `json:"runtime"`
	Available  *bool   `json:"available"`
	Version    *string `json:"version,omitempty"`
	BinaryPath *string `json:"binary_path,omitempty"`
	CheckedAt  *string `json:"checked_at,omitempty"`
}
type workspaceRoot struct {
	Path        string  `json:"path"`
	DisplayName *string `json:"display_name,omitempty"`
	IsEnabled   *bool   `json:"is_enabled"`
}
type registerFields struct {
	Name           string          `json:"name"`
	Hostname       string          `json:"hostname"`
	OS             string          `json:"os"`
	OSVersion      string          `json:"os_version"`
	Architecture   string          `json:"architecture"`
	DaemonVersion  string          `json:"daemon_version"`
	RunUser        string          `json:"run_user"`
	Runtimes       []runtimeItem   `json:"runtimes"`
	WorkspaceRoots []workspaceRoot `json:"workspace_roots"`
	Tunnel         *tunnelReport   `json:"tunnel"`
}
type heartbeatFields struct {
	DaemonVersion  string       `json:"daemon_version"`
	ActiveSessions *int         `json:"active_sessions"`
	Resources      *hbResources `json:"resources,omitempty"`
}
type hbResources struct {
	CPUUsage     *float64 `json:"cpu_usage,omitempty"`
	MemoryUsage  *float64 `json:"memory_usage,omitempty"`
	LoadAverage  *float64 `json:"load_average,omitempty"`
	DiskUsage    *float64 `json:"disk_usage,omitempty"`
	DaemonUptime *float64 `json:"daemon_uptime,omitempty"`
}
type runtimeStatusFields struct {
	Runtimes []runtimeItem `json:"runtimes"`
	Tunnel   *tunnelReport `json:"tunnel"`
}

// tunnelReport is a node's port-forwarding prerequisites (P11, ADR 0022). Optional, so a
// daemon that predates the capability still registers; a missing object means "this node
// cannot forward ports", which is also the correct reading of an old daemon.
//
// Note what is not here: a credential, or any field about one. The provider credential is
// the platform's, delivered per request, so this direction of the protocol has nothing to
// say about it — and a field that does not exist cannot leak.
type tunnelReport struct {
	Veto                 *bool    `json:"veto"`
	SSHAvailable         *bool    `json:"ssh_available"`
	EgressOK             *bool    `json:"egress_ok"`
	KnownHostsOK         *bool    `json:"known_hosts_ok"`
	DaemonSupportsTunnel *bool    `json:"daemon_supports_tunnel"`
	AllowedPorts         []string `json:"allowed_ports"`
	MaxTunnels           int      `json:"max_tunnels"`
}

// validTunnelReport mirrors node-tunnel-report.schema.json.
func validTunnelReport(report *tunnelReport) bool {
	if report == nil {
		return true
	}
	if report.Veto == nil || report.SSHAvailable == nil || report.EgressOK == nil ||
		report.KnownHostsOK == nil || report.DaemonSupportsTunnel == nil {
		return false
	}
	if len(report.AllowedPorts) > 64 {
		return false
	}
	for _, spec := range report.AllowedPorts {
		if !validPortSpec(spec) {
			return false
		}
	}
	return report.MaxTunnels >= 0 && report.MaxTunnels <= 100
}

// validPortSpec accepts "5173" and "3000-3999" and nothing else — in particular nothing
// that could carry a separator into the provider's comma-separated options.
func validPortSpec(spec string) bool {
	if spec == "" || len(spec) > 16 {
		return false
	}
	low, high, found := strings.Cut(spec, "-")
	if !validPortNumber(low) {
		return false
	}
	if found && !validPortNumber(high) {
		return false
	}
	return true
}

func validPortNumber(value string) bool {
	if value == "" || len(value) > 5 {
		return false
	}
	for i := 0; i < len(value); i++ {
		if value[i] < '0' || value[i] > '9' {
			return false
		}
	}
	return true
}

type systemInfoFields struct {
	OS           string  `json:"os"`
	OSVersion    string  `json:"os_version"`
	Architecture string  `json:"architecture"`
	Kernel       *string `json:"kernel,omitempty"`
	RunUser      string  `json:"run_user"`
}

func strictUnmarshal(data []byte, v any) error {
	dec := json.NewDecoder(bytes.NewReader(data))
	dec.DisallowUnknownFields()
	return dec.Decode(v)
}

func validSize(rows, columns uint16) bool {
	return rows >= 2 && rows <= 300 && columns >= 2 && columns <= 500
}

func validArch(s string) bool { return s == "amd64" || s == "arm64" }

func validRuntimeID(s string) bool {
	return s == "claude" || s == "codex" || s == "shell" || s == "fake"
}

// validRelPath accepts a workspace-relative path: non-empty, no control chars,
// not absolute, not `~`-rooted, and no `..` segment after cleaning. This is the
// wire-level guard; internal/workspace does the final canonical containment.
func validRelPath(s string) bool {
	if s == "" || len(s) > 4096 {
		return false
	}
	for _, r := range s {
		if r < 0x20 {
			return false
		}
	}
	if strings.HasPrefix(s, "/") || strings.HasPrefix(s, "~") {
		return false
	}
	clean := path.Clean(s)
	if clean == ".." || strings.HasPrefix(clean, "../") {
		return false
	}
	return true
}

// validKeyword accepts a filename search keyword: non-empty, bounded, no
// control chars. No globs/regex/shell arguments are permitted (SEC-002).
func validKeyword(s string) bool {
	if s == "" || len(s) > 256 {
		return false
	}
	for _, r := range s {
		if r < 0x20 {
			return false
		}
	}
	return true
}

// UpdateStages and UpdateStatuses are the stable vocabularies from
// Tunnel payload fields (P11, ADR 0022). Mirrors
// contracts/v1/schemas/messages/tunnel-*.schema.json.
//
// validCredential is the load-bearing one. The credential is concatenated into
// ssh's "<token>@<host>" argument, and the provider separates modifiers with '+'
// and the host with '@' — so a value carrying either would change the tunnel type
// or the destination. Central's schema already rejects those, and this rejects them
// again: the daemon must not depend on its caller having validated anything.
type tunnelOpenFields struct {
	TunnelID   uuid.UUID `json:"tunnel_id"`
	Port       int       `json:"port"`
	Protection string    `json:"protection"`
	Credential string    `json:"credential"`
	BasicAuth  *struct {
		Username string `json:"username"`
		Password string `json:"password"`
	} `json:"basic_auth"`
	AllowedIPs  []string `json:"allowed_ips"`
	RewriteHost bool     `json:"rewrite_host"`
	TTLSeconds  int      `json:"ttl_seconds"`
}

type tunnelOpenedFields struct {
	TunnelID          uuid.UUID `json:"tunnel_id"`
	URL               string    `json:"url"`
	Provider          string    `json:"provider"`
	UpstreamExpiresAt string    `json:"upstream_expires_at"`
	Authenticated     bool      `json:"authenticated"`
}

type tunnelIDFields struct {
	TunnelID uuid.UUID `json:"tunnel_id"`
}

type tunnelClosedFields struct {
	TunnelID uuid.UUID `json:"tunnel_id"`
	Reason   string    `json:"reason"`
}

type tunnelStatusFields struct {
	TunnelID          uuid.UUID `json:"tunnel_id"`
	State             string    `json:"state"`
	URL               string    `json:"url"`
	UpstreamExpiresAt string    `json:"upstream_expires_at"`
	ErrorCode         string    `json:"error_code"`
}

var (
	tunnelProtectionSet = map[string]bool{"basic": true, "ipallow": true, "public": true}
	tunnelReasonSet     = map[string]bool{"requested": true, "expired": true, "provider_failed": true, "shutdown": true}
	tunnelStateSet      = map[string]bool{"running": true, "reconnecting": true, "failed": true, "closed": true}
	tunnelErrorCodeSet  = map[string]bool{
		"TUNNEL_PROVIDER_UNAVAILABLE":  true,
		"TUNNEL_PROVIDER_UNAUTHORIZED": true,
		"TUNNEL_PROVIDER_UNTRUSTED":    true,
		"TUNNEL_PORT_NOT_ALLOWED":      true,
		"INTERNAL_ERROR":               true,
	}
)

// ValidCredential reports whether a provider credential is safe to place in the
// ssh destination argument. Exported because the tunnel supervisor checks it again
// at the point of use, not only at decode time.
func ValidCredential(value string) bool {
	if len(value) < 8 || len(value) > 128 {
		return false
	}
	for i := 0; i < len(value); i++ {
		c := value[i]
		if !(c >= '0' && c <= '9' || c >= 'A' && c <= 'Z' || c >= 'a' && c <= 'z') {
			return false
		}
	}
	return true
}

// validBasicAuthPart rejects ':' (the provider option's own separator) and anything
// outside printable ASCII.
func validBasicAuthPart(value string, minLen int) bool {
	if len(value) < minLen || len(value) > 64 {
		return false
	}
	for i := 0; i < len(value); i++ {
		c := value[i]
		if c <= 0x20 || c >= 0x7f || c == ':' {
			return false
		}
	}
	return true
}

// ValidTunnelURL enforces https-only, bounded, control-character-free URLs. The URL
// is external input: the daemon parsed it out of the provider's stdout, so it is
// checked before it can travel to Central and from there to a browser.
func ValidTunnelURL(value string) bool {
	if len(value) == 0 || len(value) > 2048 || !strings.HasPrefix(value, "https://") {
		return false
	}
	for i := 0; i < len(value); i++ {
		if value[i] <= 0x20 || value[i] == 0x7f {
			return false
		}
	}
	return true
}

// contracts/v1/schemas/messages/daemon-update-result.schema.json. Exported so
// internal/update reports a stage the schema accepts rather than free text.
var UpdateStages = []string{"manifest", "download", "checksum", "swap", "restart", "healthcheck"}

var updateStageSet = map[string]bool{
	"manifest": true, "download": true, "checksum": true,
	"swap": true, "restart": true, "healthcheck": true,
}

var updateStatusSet = map[string]bool{"succeeded": true, "failed": true, "rolled_back": true}

var updateErrorCodeSet = map[string]bool{
	"UPDATE_NOT_ALLOWED": true, "UPDATE_DOWNLOAD_FAILED": true,
	"UPDATE_CHECKSUM_MISMATCH": true, "UPDATE_HEALTHCHECK_FAILED": true,
	"UPDATE_ROLLED_BACK": true, "UPDATE_IN_PROGRESS": true,
}

// semver matches the target_version pattern in daemon-update.schema.json. The
// version is compared against the release manifest; it is never interpolated
// into a filesystem path or URL, but it is still pinned to this shape so a
// traversal-looking or floating ("latest") value is refused at the wire.
var semver = regexp.MustCompile(`^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.]+)?$`)

// ValidTargetVersion reports whether s is an acceptable update target version.
func ValidTargetVersion(s string) bool {
	return len(s) >= 5 && len(s) <= 64 && semver.MatchString(s)
}

func validRuntimes(items []runtimeItem) bool {
	for _, it := range items {
		if (it.Runtime != "claude" && it.Runtime != "codex" && it.Runtime != "shell") ||
			it.Available == nil {
			return false
		}
	}
	return true
}

// ValidateControl enforces the full v1 contract for request messages: the
// envelope plus the typed payload (no unknown fields, no forbidden executable
// fields, and rows/columns within bounds). This is the single source of truth
// shared by the dispatcher and the contract tests so runtime behaviour matches
// the golden fixtures across languages.
func ValidateControl(raw []byte) error {
	env, err := DecodeControl(raw)
	if err != nil {
		return err
	}
	switch env.Type {
	case "node.challenge":
		var p struct {
			Nonce string `json:"nonce"`
		}
		if strictUnmarshal(env.Payload, &p) != nil || len(p.Nonce) != 44 {
			return errors.New("INVALID_MESSAGE")
		}
	case "node.auth":
		var p struct {
			ChallengeID string `json:"challenge_id"`
			Signature   string `json:"signature"`
		}
		if strictUnmarshal(env.Payload, &p) != nil || len(p.ChallengeID) != 26 || len(p.Signature) != 88 {
			return errors.New("INVALID_MESSAGE")
		}
	case "session.start":
		var p startFields
		if strictUnmarshal(env.Payload, &p) != nil || !validRuntimeID(p.Runtime) ||
			p.SessionID == uuid.Nil || p.Workspace == "" || !validSize(p.Rows, p.Columns) {
			return errors.New("INVALID_MESSAGE")
		}
	case "session.attach", "terminal.resize":
		var p sizeFields
		if strictUnmarshal(env.Payload, &p) != nil || p.SessionID == uuid.Nil || !validSize(p.Rows, p.Columns) {
			return errors.New("INVALID_MESSAGE")
		}
	case "session.stop", "session.recover", "terminal.detach", "terminal.control_acquire", "terminal.control_release":
		var p sessionIDFields
		if strictUnmarshal(env.Payload, &p) != nil || p.SessionID == uuid.Nil {
			return errors.New("INVALID_MESSAGE")
		}
	case "session.list":
		var p struct{}
		if strictUnmarshal(env.Payload, &p) != nil {
			return errors.New("INVALID_MESSAGE")
		}
	case "filesystem.list":
		var p fsListFields
		if strictUnmarshal(env.Payload, &p) != nil || p.SessionID == uuid.Nil ||
			!validRelPath(p.Path) || p.EntryLimit < 0 || p.EntryLimit > 2000 {
			return errors.New("INVALID_MESSAGE")
		}
	case "filesystem.read":
		var p fsReadFields
		if strictUnmarshal(env.Payload, &p) != nil || p.SessionID == uuid.Nil ||
			!validRelPath(p.Path) {
			return errors.New("INVALID_MESSAGE")
		}
	case "filesystem.search":
		var p fsSearchFields
		if strictUnmarshal(env.Payload, &p) != nil || p.SessionID == uuid.Nil ||
			!validKeyword(p.Keyword) || (p.Root != "" && !validRelPath(p.Root)) ||
			p.MaxResults < 0 || p.MaxResults > 200 {
			return errors.New("INVALID_MESSAGE")
		}
	case "tunnel.open":
		var p tunnelOpenFields
		if strictUnmarshal(env.Payload, &p) != nil || p.TunnelID == uuid.Nil ||
			p.Port < 1024 || p.Port > 65535 || !tunnelProtectionSet[p.Protection] ||
			p.TTLSeconds < 60 || p.TTLSeconds > 86400 ||
			(p.Credential != "" && !ValidCredential(p.Credential)) ||
			(p.Protection == "basic" && (p.BasicAuth == nil ||
				!validBasicAuthPart(p.BasicAuth.Username, 1) ||
				!validBasicAuthPart(p.BasicAuth.Password, 8))) ||
			(p.Protection == "ipallow" && len(p.AllowedIPs) == 0) ||
			len(p.AllowedIPs) > 32 {
			return errors.New("INVALID_MESSAGE")
		}
	case "tunnel.opened":
		var p tunnelOpenedFields
		if strictUnmarshal(env.Payload, &p) != nil || p.TunnelID == uuid.Nil ||
			!ValidTunnelURL(p.URL) || p.Provider != "pinggy" {
			return errors.New("INVALID_MESSAGE")
		}
	case "tunnel.close":
		var p tunnelIDFields
		if strictUnmarshal(env.Payload, &p) != nil || p.TunnelID == uuid.Nil {
			return errors.New("INVALID_MESSAGE")
		}
	case "tunnel.closed":
		var p tunnelClosedFields
		if strictUnmarshal(env.Payload, &p) != nil || p.TunnelID == uuid.Nil ||
			!tunnelReasonSet[p.Reason] {
			return errors.New("INVALID_MESSAGE")
		}
	case "tunnel.status":
		var p tunnelStatusFields
		if strictUnmarshal(env.Payload, &p) != nil || p.TunnelID == uuid.Nil ||
			!tunnelStateSet[p.State] ||
			(p.URL != "" && !ValidTunnelURL(p.URL)) ||
			(p.ErrorCode != "" && !tunnelErrorCodeSet[p.ErrorCode]) ||
			(p.State == "failed" && p.ErrorCode == "") {
			return errors.New("INVALID_MESSAGE")
		}
	case "daemon.update":
		var p daemonUpdateFields
		if strictUnmarshal(env.Payload, &p) != nil || !ValidTargetVersion(p.TargetVersion) {
			return errors.New("INVALID_MESSAGE")
		}
	case "daemon.update_result":
		var p daemonUpdateResultFields
		if strictUnmarshal(env.Payload, &p) != nil ||
			p.FromVersion == "" || p.ToVersion == "" ||
			!updateStatusSet[p.Status] || !updateStageSet[p.Stage] ||
			(p.ErrorCode != "" && !updateErrorCodeSet[p.ErrorCode]) {
			return errors.New("INVALID_MESSAGE")
		}
	case "node.register":
		var p registerFields
		if strictUnmarshal(env.Payload, &p) != nil ||
			p.Name == "" || p.Hostname == "" || p.OS == "" || p.OSVersion == "" ||
			p.DaemonVersion == "" || p.RunUser == "" || !validArch(p.Architecture) ||
			!validRuntimes(p.Runtimes) || !validTunnelReport(p.Tunnel) {
			return errors.New("INVALID_MESSAGE")
		}
		for _, w := range p.WorkspaceRoots {
			if w.Path == "" || w.IsEnabled == nil {
				return errors.New("INVALID_MESSAGE")
			}
		}
	case "node.heartbeat":
		var p heartbeatFields
		if strictUnmarshal(env.Payload, &p) != nil || p.DaemonVersion == "" ||
			p.ActiveSessions == nil || *p.ActiveSessions < 0 {
			return errors.New("INVALID_MESSAGE")
		}
	case "node.runtime_status":
		var p runtimeStatusFields
		if strictUnmarshal(env.Payload, &p) != nil || !validRuntimes(p.Runtimes) ||
			!validTunnelReport(p.Tunnel) {
			return errors.New("INVALID_MESSAGE")
		}
	case "node.system_info":
		var p systemInfoFields
		if strictUnmarshal(env.Payload, &p) != nil ||
			p.OS == "" || p.OSVersion == "" || p.RunUser == "" || !validArch(p.Architecture) {
			return errors.New("INVALID_MESSAGE")
		}
	}
	return nil
}

func EncodeBinary(kind byte, id uuid.UUID, payload []byte) ([]byte, error) {
	if (kind != 1 && kind != 2) || len(payload) == 0 {
		return nil, errors.New("INVALID_MESSAGE")
	}
	if len(payload) > MaxPayload {
		return nil, errors.New("FRAME_TOO_LARGE")
	}
	frame := make([]byte, HeaderSize+len(payload))
	frame[0], frame[1] = 1, kind
	copy(frame[2:18], id[:])
	copy(frame[18:], payload)
	return frame, nil
}

func DecodeBinary(frame []byte) (byte, uuid.UUID, []byte, error) {
	if len(frame) <= HeaderSize {
		return 0, uuid.Nil, nil, errors.New("INVALID_MESSAGE")
	}
	if frame[0] != 1 {
		return 0, uuid.Nil, nil, errors.New("PROTOCOL_VERSION_UNSUPPORTED")
	}
	if frame[1] != 1 && frame[1] != 2 {
		return 0, uuid.Nil, nil, errors.New("INVALID_MESSAGE")
	}
	if len(frame)-HeaderSize > MaxPayload {
		return 0, uuid.Nil, nil, errors.New("FRAME_TOO_LARGE")
	}
	var id uuid.UUID
	copy(id[:], frame[2:18])
	payload := append([]byte(nil), frame[18:]...)
	return frame[1], id, payload, nil
}
