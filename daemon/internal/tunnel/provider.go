// Package tunnel supervises port-forwarding tunnels to a third-party provider (P11,
// ADR 0022).
//
// The shape of this package follows three measured facts about the provider, none of which
// is in its documentation (see scripts/tunnel/verify-provider.sh and PG-01):
//
//  1. A PTY must not be allocated. With one, the service renders a full-screen ANSI
//     interface and the URL cannot be parsed. Without one, stdout is a handful of lines.
//  2. An invalid credential is not rejected. The service silently downgrades to an
//     anonymous, time-limited tunnel and still hands out a URL, so "unauthorized" has to be
//     detected by reading the banner — and then the tunnel must be torn down, because a Pro
//     user asked for a stable URL and would otherwise be handed a 60-minute anonymous one.
//  3. The app receives the tunnel hostname as Host. Dev servers with host allowlists
//     refuse that, which is why the platform offers an opt-in Host rewrite.
//
// The Provider interface exists so that replacing the provider — or returning to a
// self-hosted proxy (plan/10) — stays inside this package instead of reaching the protocol
// and Central. There is exactly one implementation, and the config accepts exactly one
// provider name: an interface with one implementation is cheap, an unused enum value is not.
package tunnel

import (
	"context"
	"errors"
)

// Protection mirrors the wire vocabulary (contracts/v1/schemas/messages/tunnel-open).
const (
	ProtectionBasic   = "basic"
	ProtectionIPAllow = "ipallow"
	ProtectionPublic  = "public"
)

// Stable codes reported back to Central. The daemon's own error strings never leave the
// node; only these do (ADR 0014's rule, extended to the tunnel path).
const (
	CodeUnavailable    = "TUNNEL_PROVIDER_UNAVAILABLE"
	CodeUnauthorized   = "TUNNEL_PROVIDER_UNAUTHORIZED"
	CodeUntrusted      = "TUNNEL_PROVIDER_UNTRUSTED"
	CodeNotConfigured  = "TUNNEL_PROVIDER_NOT_CONFIGURED"
	CodePortNotAllowed = "TUNNEL_PORT_NOT_ALLOWED"
	CodeInternal       = "INTERNAL_ERROR"
	CodeInvalidMessage = "INVALID_MESSAGE"
	// CodeNodeVetoed is Central-only on the wire's error enum, but the daemon reports it so
	// that a platform that ignored the node's veto gets told exactly why it was refused.
	CodeNodeVetoed   = "TUNNEL_NODE_DISABLED"
	CodeLimitReached = "TUNNEL_LIMIT_REACHED"
)

// Options is everything a tunnel needs, and nothing more. There is no host, scheme or
// command field: the provider host is this package's own constant, so no message from
// Central can redirect where a node connects.
type Options struct {
	Port int
	// Credential is the provider token, delivered per open and held only in memory.
	// Empty means the anonymous free tier.
	Credential string
	Protection string
	BasicUser  string
	BasicPass  string
	AllowedIPs []string
	// RewriteHost asks the provider to present the loopback address to the local app
	// instead of the tunnel hostname, so that dev servers with host allowlists answer.
	RewriteHost bool
	// KnownHostsPath is the node's own pinned host key file. Empty — or a path that does
	// not exist — falls back to the keys embedded in this binary (see knownhosts.go), so
	// a node is pinned whether or not anyone deployed a file to it. What no value here
	// can produce is an unpinned tunnel: "skip verification" is not one of the outcomes.
	KnownHostsPath string
}

// Result is what a successful start produced.
type Result struct {
	URL string
	// Authenticated is false when the provider announced an anonymous tunnel. With a
	// credential supplied that means the credential was rejected.
	Authenticated bool
	// ExpiresAt is the provider's own deadline, if it announced one (RFC 3339, UTC).
	ExpiresAt string

	// anonymousSeen records that the "not authenticated" banner arrived before the URL.
	// Unexported: it is parser state, not something a caller should read or set.
	anonymousSeen bool
}

// Provider starts and stops one tunnel process.
type Provider interface {
	// Name is the wire-level provider id.
	Name() string
	// Start blocks until the provider assigns a URL or the context expires.
	Start(ctx context.Context, opts Options) (Result, ProcessHandle, error)
}

// ProcessHandle is a running tunnel. Stop must be safe to call more than once, and Wait
// must return the classification of why the process ended.
type ProcessHandle interface {
	// Wait blocks until the process exits and reports whether a retry makes sense along
	// with the stable code to report if it does not.
	Wait() Exit
	// Stop terminates the process group and waits briefly for it to go.
	Stop()
	// PID of the supervised process, for the pid file used to reap orphans.
	PID() int
}

// Exit is why a tunnel process ended.
type Exit struct {
	// Retryable is true for conditions a reconnect can clear: a dropped connection, the
	// provider's own time limit, a transient refusal.
	Retryable bool
	// Code is the stable code to report when Retryable is false.
	Code string
}

// ErrNoURL is returned when the provider connected but never announced a URL. It is its
// own error because the remedy differs from a refused connection: the tunnel may in fact
// be up, so the supervisor tears it down rather than leaving a URL-less process running.
var ErrNoURL = errors.New("provider did not announce a url")

// ErrKnownHostsMissing is returned when no pinned host key can be produced at all — the
// node has no file and the embedded keys could not be written to disk. It is fatal by
// design: without a pinned key the only alternatives are to trust whatever key is
// presented (which is the attack this prevents) or to refuse. It refuses.
//
// A merely absent /etc/agentd/pinggy_known_hosts is no longer this error: the binary
// carries the keys, so that case resolves instead of failing.
var ErrKnownHostsMissing = errors.New("no pinned provider host key is available")
