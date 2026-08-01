package tunnel

import (
	"bufio"
	"context"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"os"
	"os/exec"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"
)

// Provider hosts. These are constants here rather than fields anywhere, so that no message
// from Central can point a node's ssh client at a host of the sender's choosing. Which one
// is used follows from whether a credential was supplied, and nothing else.
const (
	freeHost = "free.pinggy.io"
	proHost  = "pro.pinggy.io"
	sshPort  = "443" // the provider listens here so that egress filters that allow 443 work
)

// ProviderDialAddress is the endpoint a node must be able to reach for port forwarding to
// work at all. Exported so `agentd doctor` tests the same address the tunnel will use,
// rather than a copy of it that could drift.
func ProviderDialAddress() string { return freeHost + ":" + sshPort }

// Hostname suffixes the provider is known to assign, measured in PG-01. The banner also
// contains `https://dashboard.pinggy.io`, so "take the first https URL" would take the
// wrong one — this allowlist is what makes the parse correct rather than lucky.
var urlSuffixes = []string{
	".run.pinggy-free.link",
	".free.pinggy.net",
	".pinggy.link",
	".a.pinggy.link",
}

// The banner line the provider prints when the tunnel is anonymous. With a credential
// supplied, this is how — and the only way — the daemon learns the credential was refused:
// the process does not fail and a URL is still issued (PG-01 #7).
const anonymousBanner = "You are not authenticated"

var (
	urlPattern     = regexp.MustCompile(`https://[a-z0-9][a-z0-9.\-]*`)
	expiryPattern  = regexp.MustCompile(`expire in (\d+) minutes?`)
	hostKeyFailure = "host key verification failed"
)

// PinggyProvider starts tunnels by supervising an OpenSSH client, the same way the daemon
// already supervises tmux and systemctl.
type PinggyProvider struct {
	// SSHPath overrides the ssh binary; tests point it at a fake provider.
	SSHPath string
	// Now is injected so expiry arithmetic is testable.
	Now func() time.Time
}

// TestProviderCommandEnv names a stand-in for the ssh client. It exists for the end-to-end
// stack (`scripts/e2e/run-stack.sh`), which must exercise the whole path — Central, the
// protocol, this supervisor, the browser — without reaching the real provider: a CI that goes
// red when a third party has an outage is a CI whose red means nothing (plan/11 §2.6).
//
// It grants nothing. The node owner already decides which `ssh` is on the daemon's PATH, so
// naming a different binary in the daemon's own environment moves no boundary — which is
// exactly why it must stay an environment variable on the node and never become a field in a
// message from Central (SEC-002). `TestProviderCommandInUse` is what the rest of the daemon
// asks so that a stack running a fake provider does not also dial the real one.
const TestProviderCommandEnv = "CLIORA_TUNNEL_PROVIDER_COMMAND_FOR_TESTS"

// TestProviderCommandInUse reports whether this daemon was started with a stand-in provider.
func TestProviderCommandInUse() bool {
	return strings.TrimSpace(os.Getenv(TestProviderCommandEnv)) != ""
}

func NewPinggyProvider() *PinggyProvider {
	if command := strings.TrimSpace(os.Getenv(TestProviderCommandEnv)); command != "" {
		// Warned, not silent: a node running a stand-in provider is not forwarding traffic to
		// anywhere real, and the one thing worse than that in production would be nobody
		// being able to tell from the log.
		slog.Warn(
			"port forwarding is using a stand-in provider from the environment; "+
				"this is for tests only and forwards no real traffic",
			"env", TestProviderCommandEnv, "command", command,
		)
		return &PinggyProvider{SSHPath: command, Now: time.Now}
	}
	return &PinggyProvider{SSHPath: "ssh", Now: time.Now}
}

func (p *PinggyProvider) Name() string { return "pinggy" }

func (p *PinggyProvider) sshPath() string {
	if p.SSHPath == "" {
		return "ssh"
	}
	return p.SSHPath
}

func (p *PinggyProvider) now() time.Time {
	if p.Now == nil {
		return time.Now()
	}
	return p.Now()
}

// destination builds the ssh user@host. The credential goes in the user field, which is
// exactly why its character set is restricted upstream and re-checked below: the provider
// separates modifiers with '+' and the host with '@', so a credential carrying either would
// change the tunnel type or the destination.
func destination(credential string) string {
	if credential == "" {
		return "http@" + freeHost
	}
	return credential + "@" + proHost
}

// Args assembles the command line. Exported for the test that asserts what is and is not
// on it: no PTY request, no -N, no way for a value to reach a shell.
func (p *PinggyProvider) Args(opts Options) ([]string, error) {
	if opts.Port < 1024 || opts.Port > 65535 {
		return nil, fmt.Errorf("port %d is outside the forwardable range", opts.Port)
	}
	if opts.Credential != "" && !validCredential(opts.Credential) {
		// Second layer. The wire schema already rejects this; the daemon does not depend on
		// its caller having validated anything, because the consequence here is a redirected
		// SSH destination rather than a rejected message.
		return nil, errors.New("credential contains characters that could redirect the tunnel")
	}
	if opts.KnownHostsPath == "" {
		return nil, ErrKnownHostsMissing
	}
	args := []string{
		"-p", sshPort,
		// Non-interactive: the provider authenticates with method "none", so nothing ever
		// prompts (PG-01 #1). BatchMode makes a prompt an error instead of a hang.
		"-o", "BatchMode=yes",
		"-o", "StrictHostKeyChecking=yes",
		"-o", "UserKnownHostsFile=" + opts.KnownHostsPath,
		// Only the pinned file counts. A system-wide known_hosts could have been written by
		// anything else on the machine.
		"-o", "GlobalKnownHostsFile=/dev/null",
		"-o", "IdentitiesOnly=yes",
		// Without this, a connection whose forwarding was refused looks successful and the
		// user gets a URL that answers 502 forever.
		"-o", "ExitOnForwardFailure=yes",
		"-o", "ServerAliveInterval=60",
		"-o", "ServerAliveCountMax=3",
		"-R", "0:localhost:" + strconv.Itoa(opts.Port),
		destination(opts.Credential),
	}
	// Remote options travel as the remote command, which is why -N (do not execute a remote
	// command) must not be used. And no -t: with a PTY the provider replaces this banner
	// with a full-screen ANSI interface.
	args = append(args, "x:https", "x:xff")
	switch opts.Protection {
	case ProtectionBasic:
		if !validBasicPart(opts.BasicUser, 1) || !validBasicPart(opts.BasicPass, 8) {
			return nil, errors.New("basic auth credentials contain a separator or are too short")
		}
		args = append(args, "b:"+opts.BasicUser+":"+opts.BasicPass)
	case ProtectionIPAllow:
		if len(opts.AllowedIPs) == 0 {
			return nil, errors.New("ipallow protection needs at least one address")
		}
		for _, ip := range opts.AllowedIPs {
			if strings.ContainsAny(ip, ", \t:") && !strings.Contains(ip, ":") {
				return nil, fmt.Errorf("address %q contains a separator", ip)
			}
			if strings.ContainsAny(ip, ", \t") {
				return nil, fmt.Errorf("address %q contains a separator", ip)
			}
		}
		args = append(args, "w:"+strings.Join(opts.AllowedIPs, ","))
	case ProtectionPublic:
		// Nothing to add: the URL is the only thing standing in the way, which is why
		// choosing this requires an explicit acknowledgement in the platform.
	default:
		return nil, fmt.Errorf("unknown protection mode %q", opts.Protection)
	}
	if opts.RewriteHost {
		// Measured in PG-01 #11: without this the app sees the tunnel hostname as Host and
		// dev servers with host allowlists (Vite, Next) refuse the request.
		args = append(args, "u:Host:localhost:"+strconv.Itoa(opts.Port))
	}
	return args, nil
}

func validCredential(value string) bool {
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

func validBasicPart(value string, minLen int) bool {
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

// Start launches the client and waits for the URL banner.
func (p *PinggyProvider) Start(ctx context.Context, opts Options) (Result, ProcessHandle, error) {
	// Resolution happens here rather than in the caller so a reconnect hours later
	// re-checks the file: the node's own pinned file can appear (an operator rotating
	// a key) or a materialized one can be swept out of the temp directory, and neither
	// should be decided once at startup.
	resolved, err := ResolveKnownHosts(opts.KnownHostsPath)
	if err != nil {
		return Result{}, nil, err
	}
	opts.KnownHostsPath = resolved.Path

	args, err := p.Args(opts)
	if err != nil {
		return Result{}, nil, err
	}
	// Not context-bound: the process must outlive Start, which only waits for the banner.
	// Its lifetime belongs to the handle, and the supervisor owns the handle.
	cmd := exec.Command(p.sshPath(), args...)
	// Own process group so Stop can take the whole tree. ssh can fork helpers, and killing
	// only the parent is how orphans are made.
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return Result{}, nil, err
	}
	stderr, err := cmd.StderrPipe()
	if err != nil {
		return Result{}, nil, err
	}
	if err := cmd.Start(); err != nil {
		return Result{}, nil, fmt.Errorf("start provider client: %w", err)
	}

	handle := &sshHandle{cmd: cmd, stderrDone: make(chan struct{})}
	// stderr is drained in the background and kept only as a bounded tail for
	// classification. It is never forwarded: it can echo the destination argument, which
	// carries the credential.
	go handle.drainStderr(stderr)

	result, err := p.readBanner(ctx, stdout, opts, handle)
	if err != nil {
		handle.Stop()
		return Result{}, nil, err
	}
	// The provider issued a URL but told us the tunnel is anonymous, while a credential was
	// supplied. The user asked for their paid tunnel; handing them a 60-minute anonymous one
	// and calling it success is worse than failing.
	if opts.Credential != "" && !result.Authenticated {
		handle.Stop()
		return Result{}, nil, &ProviderError{Code: CodeUnauthorized}
	}
	go handle.drainStdout(stdout)
	return result, handle, nil
}

// ProviderError carries a stable code out of Start.
type ProviderError struct{ Code string }

func (e *ProviderError) Error() string { return e.Code }

// readBanner reads stdout until a URL appears, the process dies, or the context expires.
func (p *PinggyProvider) readBanner(
	ctx context.Context, stdout io.Reader, opts Options, handle *sshHandle,
) (Result, error) {
	type scanned struct {
		result Result
		err    error
	}
	done := make(chan scanned, 1)
	go func() {
		var res Result
		scanner := bufio.NewScanner(stdout)
		scanner.Buffer(make([]byte, 0, 4096), 64*1024)
		for scanner.Scan() {
			line := scanner.Text()
			if strings.Contains(line, anonymousBanner) {
				res.Authenticated = false
				res.anonymousSeen = true
				continue
			}
			if minutes := expiryPattern.FindStringSubmatch(line); minutes != nil {
				if n, err := strconv.Atoi(minutes[1]); err == nil {
					res.ExpiresAt = p.now().UTC().
						Add(time.Duration(n) * time.Minute).
						Format("2006-01-02T15:04:05Z")
				}
			}
			if url := extractURL(line); url != "" {
				res.URL = url
				res.Authenticated = !res.anonymousSeen
				done <- scanned{result: res}
				return
			}
		}
		done <- scanned{err: ErrNoURL}
	}()

	select {
	case <-ctx.Done():
		return Result{}, ErrNoURL
	case got := <-done:
		if got.err != nil {
			// The process may have died for a classifiable reason; prefer that over "no URL".
			handle.awaitStderr()
			if code := classifyStderr(handle.stderrTail()); code != "" {
				return Result{}, &ProviderError{Code: code}
			}
			return Result{}, got.err
		}
		return got.result, nil
	}
}

// The suffix a stand-in provider announces. `.invalid` is reserved by RFC 2606 and can never
// resolve, which is the point: the end-to-end suite asserts that a URL is *shown* with the
// right link attributes and must never open it. Accepted only when this daemon was started
// with a stand-in provider, so a real node cannot be talked into trusting it.
const testURLSuffix = ".example.invalid"

// extractURL returns the assigned tunnel URL from one banner line, or "".
func extractURL(line string) string {
	suffixes := urlSuffixes
	if TestProviderCommandInUse() {
		suffixes = append(append([]string{}, urlSuffixes...), testURLSuffix)
	}
	for _, candidate := range urlPattern.FindAllString(line, -1) {
		host := strings.TrimPrefix(candidate, "https://")
		for _, suffix := range suffixes {
			if strings.HasSuffix(host, suffix) {
				return candidate
			}
		}
	}
	return ""
}

// classifyStderr maps the client's own diagnostics to a stable code.
//
// This is string matching against another project's output, which is a known fragile point
// (recorded in ADR 0022): if the provider or OpenSSH rewords a message, the classification
// degrades to "unavailable" rather than misreporting. Only the host-key case is matched
// exactly, because that one must never be softened into "try again later".
func classifyStderr(tail string) string {
	lower := strings.ToLower(tail)
	switch {
	case strings.Contains(lower, hostKeyFailure),
		strings.Contains(lower, "no rsa host key is known"),
		strings.Contains(lower, "host key for") && strings.Contains(lower, "changed"):
		return CodeUntrusted
	case strings.Contains(lower, "permission denied"),
		strings.Contains(lower, "authentication failed"):
		return CodeUnauthorized
	case strings.Contains(lower, "connection refused"),
		strings.Contains(lower, "could not resolve hostname"),
		strings.Contains(lower, "connection timed out"),
		strings.Contains(lower, "network is unreachable"),
		strings.Contains(lower, "remote port forwarding failed"):
		return CodeUnavailable
	}
	return ""
}

// sshHandle owns one running client.
type sshHandle struct {
	cmd *exec.Cmd

	mu       sync.Mutex
	tail     string
	stopped  bool
	waitOnce sync.Once
	exit     Exit
	waited   chan struct{}
	// Closed when drainStderr reaches EOF, so a classification can wait for the whole
	// message instead of racing it.
	stderrDone chan struct{}
}

func (h *sshHandle) PID() int {
	if h.cmd.Process == nil {
		return 0
	}
	return h.cmd.Process.Pid
}

// drainStderr keeps a bounded tail for classification. The full text stays on the node and
// is never sent anywhere: the destination argument it may echo contains the credential.
func (h *sshHandle) drainStderr(r io.Reader) {
	defer close(h.stderrDone)
	scanner := bufio.NewScanner(r)
	for scanner.Scan() {
		h.mu.Lock()
		h.tail = truncateTail(h.tail + scanner.Text() + "\n")
		h.mu.Unlock()
	}
}

// awaitStderr waits for the drain to reach EOF, so a classification decision is made on
// the whole of what ssh said rather than on however much of it happened to be copied.
//
// Without this, "Host key verification failed." — the one message the pinning exists to
// produce — races the stdout EOF that prompts the lookup, and loses often enough to be
// seen: the operator gets TUNNEL_NO_URL, which points at the provider instead of at a key
// that no longer matches. The wait is bounded because it is only ever reached after the
// child's stdout has closed; a stderr that stays open past that is a hung process, not a
// slow one, and it must not hold up the refusal.
func (h *sshHandle) awaitStderr() {
	select {
	case <-h.stderrDone:
	case <-time.After(2 * time.Second):
	}
}

// drainStdout keeps reading after the URL so the pipe never fills. A blocked write in the
// child would stall the tunnel with no visible cause.
func (h *sshHandle) drainStdout(r io.Reader) {
	buf := make([]byte, 4096)
	for {
		if _, err := r.Read(buf); err != nil {
			return
		}
	}
}

func truncateTail(s string) string {
	const limit = 4096
	if len(s) <= limit {
		return s
	}
	return s[len(s)-limit:]
}

func (h *sshHandle) stderrTail() string {
	h.mu.Lock()
	defer h.mu.Unlock()
	return h.tail
}

func (h *sshHandle) Wait() Exit {
	h.waitOnce.Do(func() {
		h.waited = make(chan struct{})
		err := h.cmd.Wait()
		h.mu.Lock()
		stopped := h.stopped
		tail := h.tail
		h.mu.Unlock()
		switch {
		case stopped:
			// We asked for this; not a failure to report or retry.
			h.exit = Exit{Retryable: false, Code: ""}
		default:
			if code := classifyStderr(tail); code != "" {
				h.exit = Exit{Retryable: code == CodeUnavailable, Code: code}
			} else if err == nil {
				// A clean exit is how the free tier's time limit arrives: reconnect and a
				// new URL is issued.
				h.exit = Exit{Retryable: true}
			} else {
				// Unclassified: retry, but the supervisor's attempt limit still applies. An
				// unbounded retry against a provider that has stopped answering would hammer
				// it all night.
				h.exit = Exit{Retryable: true, Code: CodeUnavailable}
			}
		}
		close(h.waited)
	})
	<-h.waited
	return h.exit
}

// Stop terminates the process group and reaps it: SIGTERM, then SIGKILL if it is still
// there, and Wait in either case.
//
// The reap is not incidental. Signalling alone leaves a zombie until somebody calls Wait,
// and `Start`'s own failure paths (a downgraded credential, a URL that never arrives) call
// Stop with no supervisor goroutine behind them — so without this, every refused tunnel
// would leave an unreaped child for the life of the daemon. Signal 0 cannot detect that
// state either, because a zombie still accepts signals; waiting for Wait is the only
// reliable "it is gone".
func (h *sshHandle) Stop() {
	h.mu.Lock()
	if h.stopped {
		h.mu.Unlock()
		return
	}
	h.stopped = true
	h.mu.Unlock()
	if h.cmd.Process == nil {
		return
	}
	pgid := -h.cmd.Process.Pid
	// The whole group, not just the client: ssh may have forked helpers, and killing only
	// the parent is how orphans are made.
	_ = syscall.Kill(pgid, syscall.SIGTERM)
	reaped := make(chan struct{})
	go func() {
		h.Wait()
		close(reaped)
	}()
	select {
	case <-reaped:
		return
	case <-time.After(2 * time.Second):
		_ = syscall.Kill(pgid, syscall.SIGKILL)
	}
	select {
	case <-reaped:
	case <-time.After(2 * time.Second):
		// Unreapable within four seconds total. Reported rather than waited on forever: a
		// stuck child must not hold up closing a tunnel or shutting the daemon down.
		slog.Warn("tunnel process did not exit after SIGKILL", "pid", h.cmd.Process.Pid)
	}
}

// killProcessGroup sends SIGTERM then SIGKILL to a pid's process group. Reported separately
// from Stop because orphan reaping has no handle to work with — only a pid from a file.
func killProcessGroup(pid int) bool {
	if syscall.Kill(-pid, 0) != nil && syscall.Kill(pid, 0) != nil {
		return false
	}
	_ = syscall.Kill(-pid, syscall.SIGTERM)
	deadline := time.After(2 * time.Second)
	ticker := time.NewTicker(50 * time.Millisecond)
	defer ticker.Stop()
	for {
		select {
		case <-deadline:
			_ = syscall.Kill(-pid, syscall.SIGKILL)
			return true
		case <-ticker.C:
			if syscall.Kill(-pid, 0) != nil {
				return true
			}
		}
	}
}
