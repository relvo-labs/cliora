package protocol

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"errors"
	"path"
	"regexp"
	"strings"
	"time"
	"unicode/utf8"

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
	// filesystem.upload is the first REQUEST type in this set, and the direction
	// is Central -> daemon, so the node's decode limit widens from 64 KiB to
	// 8 MiB for this one type (ADR 0024 §7). Accepted because the peer is an
	// authenticated Central, the handler re-checks type and size immediately
	// after decode, and three ceilings sit in front of the write (RBAC, then
	// Central's 4 MiB, then the daemon's own 4 MiB, then the quota). The
	// response, filesystem.uploaded, is a path and three scalars and stays on
	// the tight bound - only the direction carrying an image needs the room.
	"filesystem.upload": true,
	// filesystem.store is the second, and the bound itself does NOT move for it
	// (ADR 0026): general file upload shares image drop's 4 MiB per-file ceiling,
	// which is 5.33 MiB of base64 and still inside the 8 MiB already granted
	// above. Its response, filesystem.stored, is a path and two scalars.
	"filesystem.store": true,
	// context.project (ADR 0028) shares the wider bound without moving it: its schema
	// caps a file at the base64 length of 64 KiB and the array at 32, which is well
	// inside the room already granted. Its response is two short arrays and a scalar.
	"context.project": true,
}

const HeaderSize = 18

var allowedTypes = map[string]bool{"session.start": true, "session.started": true, "session.start_failed": true, "session.attach": true, "session.attached": true, "session.stop": true, "session.stopped": true, "session.list": true, "session.list_result": true, "session.recover": true, "session.status_changed": true, "terminal.resize": true, "terminal.detach": true, "terminal.gap": true, "terminal.exited": true, "terminal.error": true, "terminal.control_acquire": true, "terminal.control_release": true, "filesystem.list": true, "filesystem.entries": true, "filesystem.read": true, "filesystem.content": true, "filesystem.search": true, "filesystem.search_result": true, "filesystem.upload": true, "filesystem.uploaded": true, "filesystem.store": true, "filesystem.stored": true, "context.project": true, "context.projected": true, "node.challenge": true, "node.auth": true, "node.authenticated": true, "node.heartbeat": true, "node.register": true, "node.registered": true, "node.system_info": true, "node.runtime_status": true, "node.shutdown": true, "daemon.version": true, "daemon.doctor": true, "daemon.doctor_result": true, "daemon.update": true, "daemon.update_result": true, "tunnel.open": true, "tunnel.opened": true, "tunnel.close": true, "tunnel.closed": true, "tunnel.status": true, "runner.register": true, "runner.registered": true, "runner.poll": true, "run.offer": true, "run.accept": true, "run.decline": true, "run.lease_renew": true, "run.progress": true, "run.log_chunk": true, "run.complete": true, "run.failed": true, "run.cancel": true, "error": true}

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
	// Two-stage bound, mirroring backend/app/protocol/codec.py: refuse an absurd
	// frame before parsing it, then — once the type is known — hold everything
	// except the large types to the tight 64 KiB control limit. Until image drop
	// the daemon only ever *built* large frames, so this side needed no
	// exception; filesystem.upload is the first one it receives (ADR 0024 §7).
	if len(data) > MaxFilePayload {
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
	// Stage two of the bound: the wider ceiling belongs to the large types only,
	// so it cannot be used to smuggle an oversize session or tunnel frame.
	if len(data) > MaxPayload && !LargeFrameTypes[env.Type] {
		return Envelope{}, errors.New("FRAME_TOO_LARGE")
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

// fsUploadFields is two fields, enforced by strictUnmarshal's
// DisallowUnknownFields: a frame carrying filename, path, directory, extension
// or mime is rejected here exactly as the JSON Schema rejects it. The point of
// the design is that the sender cannot name the file, and this is where Go
// says so (ADR 0024 sec 3).
type fsUploadFields struct {
	SessionID uuid.UUID `json:"session_id"`
	Data      string    `json:"data"`
}

// fsStoreFields is the other upload path, and the contrast with fsUploadFields
// above is the design (ADR 0026 sec 2). Here the sender DOES name the
// destination - it has to, because a file's name is what makes it useful - so
// the protection moves from "there is no field" to "the field cannot hold a
// path": Filename is one segment, checked by validStoreFilename, and Directory
// is checked by the same validRelPath every read request uses.
//
// Still absent, and still enforced by DisallowUnknownFields: overwrite, mode,
// mime, precondition, revision. Nothing here can ask to replace something.
type contextProjectFields struct {
	SessionID      uuid.UUID            `json:"session_id"`
	ProcessVersion string               `json:"process_version"`
	Files          []contextProjectFile `json:"files"`
}

type contextProjectFile struct {
	Path string `json:"path"`
	Mode string `json:"mode"`
	Data string `json:"data"`
}

// validProjectPath accepts only the three platform-owned subtrees, with no traversal
// segment anywhere. The user-facing areas under `.cliora/` — `uploads/` and
// `.gitignore` — are outside this by construction rather than by an exclusion list.
func validProjectPath(rel string) bool {
	if rel == "" || len(rel) > 4096 || strings.ContainsRune(rel, 0) {
		return false
	}
	if path.Clean(rel) != rel {
		return false
	}
	for _, seg := range strings.Split(rel, "/") {
		if seg == "" || seg == "." || seg == ".." {
			return false
		}
		for _, r := range seg {
			if r < 0x20 || r == 0x7f {
				return false
			}
		}
	}
	return strings.HasPrefix(rel, ".cliora/context/") ||
		strings.HasPrefix(rel, ".cliora/process/") ||
		strings.HasPrefix(rel, ".cliora/reference/")
}

// validProcessVersion bounds the one field that becomes a directory name.
func validProcessVersion(value string) bool {
	if value == "" || len(value) > 32 {
		return false
	}
	for i, r := range value {
		switch {
		case r >= 'a' && r <= 'z', r >= 'A' && r <= 'Z', r >= '0' && r <= '9':
		case (r == '.' || r == '_' || r == '-') && i > 0:
		default:
			return false
		}
	}
	return true
}

// validProjectData caps a projected file at the base64 length of 64 KiB — far below
// filesystem.store's ceiling, because a projection large enough to need more is one
// that should be handing the agent a path instead of a payload (D8).
func validProjectData(data string) bool {
	if len(data) > 87384 {
		return false
	}
	_, err := base64.StdEncoding.Strict().DecodeString(data)
	return err == nil
}

type fsStoreFields struct {
	SessionID uuid.UUID `json:"session_id"`
	Directory string    `json:"directory"`
	Filename  string    `json:"filename"`
	Data      string    `json:"data"`
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
	// SandboxBypass is the measured posture of this runtime on this node
	// (contract 1.7.0, ADR 0023). Optional: an older daemon does not send it, and
	// absent means "no bypass", never "unknown".
	SandboxBypass *bool `json:"sandbox_bypass,omitempty"`
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
	// PrivilegedTerminal reports that this node's system terminal can reach root
	// through sudo (contract 1.7.0, ADR 0023). Report-only: there is deliberately
	// no message in either direction that lets Central *set* it.
	PrivilegedTerminal *bool `json:"privileged_terminal,omitempty"`
	// ImageUpload reports that this node accepts image drop into a session
	// workspace (contract 1.8.0, ADR 0024 W4). Report-only for the same reason:
	// whether the platform may write to a machine is the machine's answer, and
	// the console needs it so it can hide the entry point instead of offering a
	// button that always fails.
	ImageUpload *bool `json:"image_upload,omitempty"`
	// FileUpload reports that this node accepts general file upload into a session
	// workspace (contract 1.9.0, ADR 0026 §9). Separate from ImageUpload because
	// the two grants are different sizes; absent means "no", never "unknown".
	FileUpload *bool `json:"file_upload,omitempty"`
	// ContextProjection reports that this daemon can receive a task context pack
	// (contract 1.10.0, ADR 0028 §5). Absent means "no", which is the right reading
	// for every daemon before 0.8.0: the message type does not exist there, so
	// Central simply does not send it and the session runs exactly as before.
	ContextProjection *bool `json:"context_projection,omitempty"`
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
// MaxUploadBase64 is the base64 length of a 4 MiB image, matching
// filesystem-upload.schema.json. Checking it before decoding means an
// over-limit frame is refused without allocating the decoded copy.
const MaxUploadBase64 = 5592408

// MaxStoreFilenameBytes bounds a stored filename. Bytes, not runes: the wire
// schema's maxLength counts code points, so an 88-character CJK name is 256
// bytes and would pass a code-point bound (measured:
// plan/15/07-open-measurements.md sec 2).
const MaxStoreFilenameBytes = 255

// validStoreFilename accepts exactly one storable path segment. A separator here
// is the only way a filename could become a path, and it matters more than it
// looks: URL encoding lets %2F reach the query parameter as "/", so this check
// must run after decoding and must not be the only place that runs it.
func validStoreFilename(name string) bool {
	if name == "" || len(name) > MaxStoreFilenameBytes || name == "." || name == ".." {
		return false
	}
	if strings.ContainsRune(name, '/') || strings.ContainsRune(name, 0) {
		return false
	}
	for _, r := range name {
		if r < 0x20 || r == 0x7f {
			return false
		}
	}
	return utf8.ValidString(name)
}

// validStoreData is validUploadData with one difference: an empty string is
// accepted, because an empty file is a legitimate thing to upload (a placeholder,
// an empty __init__.py). All three consumers decode "" to zero bytes cleanly
// (measured: plan/15/07-open-measurements.md sec 4).
func validStoreData(data string) bool {
	if data == "" {
		return true
	}
	return validUploadData(data)
}

// validUploadData accepts only canonical standard-alphabet base64. The
// permissive decoders tolerate newlines and the URL-safe alphabet; allowing
// either would mean two representations of the same bytes cross the wire, and
// the daemon decodes with StdEncoding.Strict().
func validUploadData(data string) bool {
	if len(data) < 4 || len(data) > MaxUploadBase64 || len(data)%4 != 0 {
		return false
	}
	for i := 0; i < len(data); i++ {
		c := data[i]
		switch {
		case c >= 'A' && c <= 'Z', c >= 'a' && c <= 'z', c >= '0' && c <= '9', c == '+', c == '/':
		case c == '=':
			// Padding is only legal in the final two positions.
			if i < len(data)-2 {
				return false
			}
		default:
			return false
		}
	}
	return true
}

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

// --- V2.2 agent runner (contract 1.11.0, ADR 0029/0031) ---------------------
//
// The daemon re-validates every one of these rather than trusting Central, the same
// defence-in-depth rule `context.project` follows (SEC-001). Two of the checks are
// the machine form of a decision rather than input hygiene:
//
//   - `runSpecFields` has no Command, no Args, no Env and **no Workspace**. Strict
//     unmarshalling makes any of them a rejection, which is what keeps SEC-002's argv
//     clause and the 2026-08-10 ruling true on the wire and not only in review.
//   - a source URL may not carry userinfo. A credential inside a remote URL surfaces
//     in `git remote -v`, in the reflog and in error messages (ADR 0031 §5).

type runnerRegisterFields struct {
	RunnerID      uuid.UUID `json:"runner_id"`
	Name          string    `json:"name"`
	Runtimes      []string  `json:"runtimes"`
	Labels        []string  `json:"labels"`
	MaxConcurrent *int      `json:"max_concurrent"`
	MaxWaiting    *int      `json:"max_waiting"`
	Dedicated     *bool     `json:"dedicated"`
}

type runnerRegisteredFields struct {
	RunnerID uuid.UUID `json:"runner_id"`
	Accepted *bool     `json:"accepted"`
	Enabled  *bool     `json:"enabled"`
	Reason   string    `json:"reason"`
}

type runnerPollFields struct {
	RunnerID uuid.UUID `json:"runner_id"`
	Capacity *int      `json:"capacity"`
}

type runIDFields struct {
	RunID uuid.UUID `json:"run_id"`
}

// RunSource names where a run's code comes from. Exported because the runner needs it.
type RunSource struct {
	Kind string `json:"kind"`
	URL  string `json:"url,omitempty"`
	Ref  string `json:"ref,omitempty"`
}

// RunSpec is everything a claimed run is told to do. Read the absent fields first.
type RunSpec struct {
	Runtime                     string    `json:"runtime,omitempty"`
	Source                      RunSource `json:"source"`
	Context                     string    `json:"context"`
	AllowedVerificationCommands []string  `json:"allowed_verification_commands,omitempty"`
	TimeoutSeconds              int       `json:"timeout_seconds"`
	IdleTimeoutSeconds          int       `json:"idle_timeout_seconds"`
}

// RunOffer is a run that has **already been claimed** for this node.
type RunOffer struct {
	RunID     *uuid.UUID `json:"run_id"`
	TaskID    uuid.UUID  `json:"task_id,omitempty"`
	ProjectID uuid.UUID  `json:"project_id,omitempty"`
	CardRef   string     `json:"card_ref,omitempty"`
	Title     string     `json:"title,omitempty"`
	Attempt   int        `json:"attempt,omitempty"`
	Delivery  string     `json:"delivery,omitempty"`
	Spec      *RunSpec   `json:"spec,omitempty"`
}

type runDeclineFields struct {
	RunID  uuid.UUID `json:"run_id"`
	Reason string    `json:"reason"`
}

type runProgressFields struct {
	RunID           uuid.UUID `json:"run_id"`
	Phase           string    `json:"phase"`
	Message         string    `json:"message"`
	CommitSHA       string    `json:"commit_sha"`
	WaitingForInput *bool     `json:"waiting_for_input"`
}

type runLogChunkFields struct {
	RunID     uuid.UUID `json:"run_id"`
	Seq       *int      `json:"seq"`
	Data      *string   `json:"data"`
	Truncated *bool     `json:"truncated"`
}

type runCompleteFields struct {
	RunID           uuid.UUID `json:"run_id"`
	Result          string    `json:"result"`
	Summary         string    `json:"summary"`
	DiskBytes       *int64    `json:"disk_bytes"`
	GitRemotes      []string  `json:"git_remotes"`
	UnpushedCommits *int      `json:"unpushed_commits"`
	UntrackedFiles  *int      `json:"untracked_files"`
}

type runFailedFields struct {
	RunID     uuid.UUID `json:"run_id"`
	ErrorCode string    `json:"error_code"`
	Message   string    `json:"message"`
	Summary   string    `json:"summary"`
	DiskBytes *int64    `json:"disk_bytes"`
}

type runCancelFields struct {
	RunID  uuid.UUID `json:"run_id"`
	Reason string    `json:"reason"`
}

var (
	runnerRuntimeSet = map[string]bool{"claude": true, "codex": true}
	runSourceKindSet = map[string]bool{"none": true, "repo": true, "existing_branch": true}
	runPhaseSet      = map[string]bool{
		"preparing": true, "fetching": true, "checked_out": true,
		"running": true, "waiting_for_input": true, "finishing": true,
	}
	runDeclineReasonSet = map[string]bool{
		"at_capacity": true, "runtime_unavailable": true, "disk_quota": true,
		"shutting_down": true, "internal_error": true,
	}
	runResultSet      = map[string]bool{"succeeded": true, "no_changes": true}
	runCancelReasons  = map[string]bool{"user_cancelled": true, "lease_lost": true, "shutting_down": true}
	runFailureCodeSet = map[string]bool{
		"RUN_SOURCE_UNAVAILABLE": true, "RUN_DISK_QUOTA": true, "RUN_IDLE_TIMEOUT": true,
		"RUN_TIMEOUT": true, "RUN_RUNTIME_UNAVAILABLE": true, "RUN_CANCELLED": true,
		"RUN_INTERNAL_ERROR": true,
	}
)

// validGitRef refuses a leading `-`: the closed argv table cannot protect a value
// that *is* a flag.
func validGitRef(value string) bool {
	if value == "" || len(value) > 255 {
		return false
	}
	for i, r := range value {
		switch {
		case r >= 'a' && r <= 'z', r >= 'A' && r <= 'Z', r >= '0' && r <= '9':
		case (r == '.' || r == '_' || r == '/' || r == '-') && i > 0:
		default:
			return false
		}
	}
	return true
}

// validCloneURL enforces the two properties ADR 0031 §5 names: a scheme the daemon
// will actually fetch over, and **no userinfo**.
func validCloneURL(value string) bool {
	if len(value) < 8 || len(value) > 2048 {
		return false
	}
	rest, ok := strings.CutPrefix(value, "https://")
	if !ok {
		rest, ok = strings.CutPrefix(value, "ssh://")
		if !ok {
			return false
		}
		// The canonical ssh clone form needs a user name, and `git` is the only one
		// Central can produce — it assembles the URL from three stored columns.
		rest = strings.TrimPrefix(rest, "git@")
	}
	if rest == "" || strings.ContainsAny(rest, " \t\r\n") {
		return false
	}
	// No further userinfo, and no colon-bearing form at all: a **password** is what
	// must be unrepresentable, because it would surface in `git remote -v`, the reflog
	// and error messages.
	authority, path, found := strings.Cut(rest, "/")
	if !found || authority == "" || strings.Contains(authority, "@") {
		return false
	}
	return path != "" || strings.HasSuffix(rest, "/")
}

func validRunSource(source RunSource) bool {
	if !runSourceKindSet[source.Kind] {
		return false
	}
	if source.Kind == "none" {
		// Absent, not empty-and-ignored: a field that should not exist has to be
		// unrepresentable (the same rule filesystem-store follows).
		return source.URL == "" && source.Ref == ""
	}
	return validCloneURL(source.URL) && validGitRef(source.Ref)
}

func validRunSpec(spec *RunSpec) bool {
	if spec == nil {
		return false
	}
	if spec.Runtime != "" && !runnerRuntimeSet[spec.Runtime] {
		return false
	}
	if spec.Context == "" || len(spec.Context) > 65536 {
		return false
	}
	if spec.TimeoutSeconds < 60 || spec.TimeoutSeconds > 86400 {
		return false
	}
	if spec.IdleTimeoutSeconds < 30 || spec.IdleTimeoutSeconds > 21600 {
		return false
	}
	if len(spec.AllowedVerificationCommands) > 16 {
		return false
	}
	return validRunSource(spec.Source)
}

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
	case "filesystem.upload":
		var p fsUploadFields
		if strictUnmarshal(env.Payload, &p) != nil || p.SessionID == uuid.Nil ||
			!validUploadData(p.Data) {
			return errors.New("INVALID_MESSAGE")
		}
	case "filesystem.store":
		var p fsStoreFields
		if strictUnmarshal(env.Payload, &p) != nil || p.SessionID == uuid.Nil ||
			!validRelPath(p.Directory) || !validStoreFilename(p.Filename) ||
			!validStoreData(p.Data) {
			return errors.New("INVALID_MESSAGE")
		}
	case "context.project":
		// The daemon re-validates rather than trusting Central (SEC-001, defence in
		// depth). Three properties, and each one is unrepresentable rather than
		// merely refused downstream: the destination is inside one of the three
		// platform-owned subtrees, there is no `..` segment anywhere, and the mode is
		// the single value the projection is allowed to write.
		var p contextProjectFields
		if strictUnmarshal(env.Payload, &p) != nil || p.SessionID == uuid.Nil ||
			!validProcessVersion(p.ProcessVersion) ||
			len(p.Files) == 0 || len(p.Files) > 32 {
			return errors.New("INVALID_MESSAGE")
		}
		for _, file := range p.Files {
			if file.Mode != "0600" || !validProjectPath(file.Path) ||
				!validProjectData(file.Data) {
				return errors.New("INVALID_MESSAGE")
			}
		}
	case "runner.register":
		var p runnerRegisterFields
		if strictUnmarshal(env.Payload, &p) != nil || p.Name == "" || len(p.Name) > 128 ||
			p.MaxConcurrent == nil || *p.MaxConcurrent < 0 || *p.MaxConcurrent > 64 ||
			p.MaxWaiting == nil || *p.MaxWaiting < 0 || *p.MaxWaiting > 64 ||
			p.Dedicated == nil || len(p.Runtimes) > 8 || len(p.Labels) > 32 {
			return errors.New("INVALID_MESSAGE")
		}
		for _, runtime := range p.Runtimes {
			if !runnerRuntimeSet[runtime] {
				return errors.New("INVALID_MESSAGE")
			}
		}
	case "runner.registered":
		var p runnerRegisteredFields
		if strictUnmarshal(env.Payload, &p) != nil || p.Accepted == nil {
			return errors.New("INVALID_MESSAGE")
		}
	case "runner.poll":
		var p runnerPollFields
		if strictUnmarshal(env.Payload, &p) != nil || p.RunnerID == uuid.Nil ||
			p.Capacity == nil || *p.Capacity < 1 || *p.Capacity > 16 {
			return errors.New("INVALID_MESSAGE")
		}
	case "run.offer":
		// `run_id: null` is the "nothing for you" answer, and it carries nothing else.
		var p RunOffer
		if strictUnmarshal(env.Payload, &p) != nil {
			return errors.New("INVALID_MESSAGE")
		}
		if p.RunID == nil {
			return nil
		}
		if *p.RunID == uuid.Nil || (p.Delivery != "" && p.Delivery != "none" && p.Delivery != "artifact") ||
			!validRunSpec(p.Spec) {
			return errors.New("INVALID_MESSAGE")
		}
	case "run.accept", "run.lease_renew":
		var p runIDFields
		if strictUnmarshal(env.Payload, &p) != nil || p.RunID == uuid.Nil {
			return errors.New("INVALID_MESSAGE")
		}
	case "run.decline":
		var p runDeclineFields
		if strictUnmarshal(env.Payload, &p) != nil || p.RunID == uuid.Nil ||
			!runDeclineReasonSet[p.Reason] {
			return errors.New("INVALID_MESSAGE")
		}
	case "run.progress":
		var p runProgressFields
		if strictUnmarshal(env.Payload, &p) != nil || p.RunID == uuid.Nil ||
			!runPhaseSet[p.Phase] || len(p.Message) > 512 ||
			(p.CommitSHA != "" && !validCommitSHA(p.CommitSHA)) {
			return errors.New("INVALID_MESSAGE")
		}
	case "run.log_chunk":
		var p runLogChunkFields
		// 32 KiB, and deliberately far below the large-frame ceiling: this type is not
		// in that set, because the same socket carries interactive terminal bytes.
		if strictUnmarshal(env.Payload, &p) != nil || p.RunID == uuid.Nil ||
			p.Seq == nil || *p.Seq < 0 || p.Data == nil || len(*p.Data) > 32768 {
			return errors.New("INVALID_MESSAGE")
		}
	case "run.complete":
		var p runCompleteFields
		if strictUnmarshal(env.Payload, &p) != nil || p.RunID == uuid.Nil ||
			!runResultSet[p.Result] || len(p.Summary) > 4096 || len(p.GitRemotes) > 16 {
			return errors.New("INVALID_MESSAGE")
		}
	case "run.failed":
		var p runFailedFields
		if strictUnmarshal(env.Payload, &p) != nil || p.RunID == uuid.Nil ||
			!runFailureCodeSet[p.ErrorCode] || len(p.Message) > 512 || len(p.Summary) > 4096 {
			return errors.New("INVALID_MESSAGE")
		}
	case "run.cancel":
		var p runCancelFields
		if strictUnmarshal(env.Payload, &p) != nil || p.RunID == uuid.Nil ||
			!runCancelReasons[p.Reason] {
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

// validCommitSHA accepts exactly a full lowercase hex object name. Abbreviations are
// refused: the Run detail page's promise is "which version did this run execute", and
// a short sha stops being unique as a repository grows.
func validCommitSHA(value string) bool {
	if len(value) != 40 {
		return false
	}
	for _, r := range value {
		if !((r >= '0' && r <= '9') || (r >= 'a' && r <= 'f')) {
			return false
		}
	}
	return true
}
