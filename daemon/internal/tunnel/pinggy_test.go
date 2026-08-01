package tunnel

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// A stand-in for the provider's client. It reproduces the three behaviours measured in
// PG-01 (banner shape, anonymous downgrade, host-key refusal) so the whole supervisor can be
// tested without a network, an account, or the provider's availability. A CI that goes red
// when a third party has an outage is a CI whose red means nothing.
const fakeProvider = `#!/usr/bin/env bash
# args are inspected by the tests via FAKE_ARGS_FILE
if [ -n "${FAKE_ARGS_FILE:-}" ]; then printf '%s\n' "$*" > "$FAKE_ARGS_FILE"; fi
case "${FAKE_MODE:-ok}" in
  ok)
    echo "You are not authenticated."
    echo "Your tunnel will expire in 60 minutes. Upgrade to Pinggy Pro to get unrestricted tunnels. https://dashboard.pinggy.io"
    echo "https://${FAKE_SLUG:-aaaaa}-203-0-113-7.run.pinggy-free.link"
    echo "https://${FAKE_SLUG:-aaaaa}-203-0-113-7.free.pinggy.net"
    sleep "${FAKE_LIFETIME:-30}"
    ;;
  authenticated)
    echo "https://${FAKE_SLUG:-aaaaa}.pinggy.link"
    sleep "${FAKE_LIFETIME:-30}"
    ;;
  hostkey)
    echo "No RSA host key is known for free.pinggy.io and you have requested strict checking." >&2
    echo "Host key verification failed." >&2
    exit 255
    ;;
  refused)
    echo "ssh: connect to host free.pinggy.io port 443: Connection refused" >&2
    exit 255
    ;;
  nourl)
    echo "some unrelated chatter"
    sleep "${FAKE_LIFETIME:-30}"
    ;;
  shortlived)
    echo "https://${FAKE_SLUG:-aaaaa}-203-0-113-7.run.pinggy-free.link"
    exit 0
    ;;
esac
`

func writeFake(t *testing.T) string {
	t.Helper()
	dir := t.TempDir()
	path := filepath.Join(dir, "fake-provider")
	if err := os.WriteFile(path, []byte(fakeProvider), 0o700); err != nil {
		t.Fatal(err)
	}
	return path
}

func writeKnownHosts(t *testing.T) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "known_hosts")
	if err := os.WriteFile(path, []byte("[free.pinggy.io]:443 ssh-rsa AAAAfake\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	return path
}

func baseOptions(t *testing.T) Options {
	return Options{
		Port:           5173,
		Protection:     ProtectionPublic,
		KnownHostsPath: writeKnownHosts(t),
	}
}

// --- command assembly ------------------------------------------------------------------

func TestArgsNeverRequestsAPTY(t *testing.T) {
	// Measured in PG-01 #2: with a PTY the provider renders a full-screen ANSI interface and
	// the URL cannot be parsed. This is the guard that stops someone adding -t to "see the
	// output better".
	p := NewPinggyProvider()
	args, err := p.Args(baseOptions(t))
	if err != nil {
		t.Fatal(err)
	}
	for _, arg := range args {
		if arg == "-t" || arg == "-tt" || arg == "-T" {
			t.Fatalf("args must not negotiate a PTY, got %v", args)
		}
		if arg == "-N" {
			t.Fatalf("-N would suppress the remote options that carry the tunnel config: %v", args)
		}
	}
}

func TestArgsPinTheHostKeyAndRefuseToSkipIt(t *testing.T) {
	p := NewPinggyProvider()
	args, err := p.Args(baseOptions(t))
	if err != nil {
		t.Fatal(err)
	}
	joined := strings.Join(args, " ")
	for _, required := range []string{
		"StrictHostKeyChecking=yes",
		"GlobalKnownHostsFile=/dev/null",
		"BatchMode=yes",
		"ExitOnForwardFailure=yes",
	} {
		if !strings.Contains(joined, required) {
			t.Errorf("missing %q in %q", required, joined)
		}
	}
	if strings.Contains(joined, "StrictHostKeyChecking=no") ||
		strings.Contains(joined, "UserKnownHostsFile=/dev/null") {
		t.Fatalf("host key verification must never be skipped: %q", joined)
	}
}

func TestArgsRefuseAnEmptyKnownHostsPath(t *testing.T) {
	opts := baseOptions(t)
	opts.KnownHostsPath = ""
	if _, err := NewPinggyProvider().Args(opts); err == nil {
		t.Fatal("an unpinned tunnel must be refused, not started")
	}
}

func TestArgsRejectACredentialThatCouldRedirectTheTunnel(t *testing.T) {
	// The credential lands in ssh's "<token>@<host>" argument, where '+' selects a tunnel
	// type and '@' selects the host. The wire schema rejects these; this asserts the daemon
	// does not rely on that.
	for _, credential := range []string{
		"AAAA+tcp@evil.host",
		"AAAAAAAA@evil.host",
		"AAAAAAAA+tcp",
		"AAAA AAAA",
		"short",
	} {
		opts := baseOptions(t)
		opts.Credential = credential
		if _, err := NewPinggyProvider().Args(opts); err == nil {
			t.Errorf("credential %q should have been refused", credential)
		}
	}
}

func TestArgsSendCredentialToTheProHostAndNothingElseChoosesTheHost(t *testing.T) {
	opts := baseOptions(t)
	opts.Credential = "xGBTh6cy58qAAAA"
	args, err := NewPinggyProvider().Args(opts)
	if err != nil {
		t.Fatal(err)
	}
	joined := strings.Join(args, " ")
	if !strings.Contains(joined, "xGBTh6cy58qAAAA@"+proHost) {
		t.Fatalf("expected the credential to address the pro host: %q", joined)
	}
	// Without a credential the free host is used, and there is no field anywhere that could
	// name a different one.
	opts.Credential = ""
	args, _ = NewPinggyProvider().Args(opts)
	if !strings.Contains(strings.Join(args, " "), "http@"+freeHost) {
		t.Fatalf("expected the free host without a credential: %v", args)
	}
}

func TestArgsRejectBasicAuthContainingTheOptionSeparator(t *testing.T) {
	opts := baseOptions(t)
	opts.Protection = ProtectionBasic
	opts.BasicUser = "preview"
	opts.BasicPass = "pass:word:1234"
	if _, err := NewPinggyProvider().Args(opts); err == nil {
		t.Fatal("a colon in the password would create a second credential pair")
	}
}

func TestArgsCarryProtectionAndHostRewrite(t *testing.T) {
	opts := baseOptions(t)
	opts.Protection = ProtectionBasic
	opts.BasicUser = "preview"
	opts.BasicPass = "abcdefghij"
	opts.RewriteHost = true
	args, err := NewPinggyProvider().Args(opts)
	if err != nil {
		t.Fatal(err)
	}
	joined := strings.Join(args, " ")
	if !strings.Contains(joined, "b:preview:abcdefghij") {
		t.Errorf("basic auth option missing: %q", joined)
	}
	if !strings.Contains(joined, "u:Host:localhost:5173") {
		t.Errorf("host rewrite option missing: %q", joined)
	}
	if !strings.Contains(joined, "x:https") {
		t.Errorf("x:https must always be present: %q", joined)
	}
}

func TestArgsRejectPrivilegedPorts(t *testing.T) {
	for _, port := range []int{22, 80, 443, 1023, 0, 70000} {
		opts := baseOptions(t)
		opts.Port = port
		if _, err := NewPinggyProvider().Args(opts); err == nil {
			t.Errorf("port %d should be refused", port)
		}
	}
}

// --- URL parsing -----------------------------------------------------------------------

func TestExtractURLIgnoresTheDashboardLink(t *testing.T) {
	// The banner's second line contains https://dashboard.pinggy.io. "Take the first https
	// URL" would take that one and the platform would show a link to the provider's own
	// dashboard instead of the tunnel.
	line := "Your tunnel will expire in 60 minutes. Upgrade to Pinggy Pro … https://dashboard.pinggy.io"
	if got := extractURL(line); got != "" {
		t.Fatalf("expected no tunnel URL, got %q", got)
	}
}

func TestExtractURLAcceptsTheMeasuredSuffixes(t *testing.T) {
	cases := map[string]string{
		"https://abcde-203-0-113-7.run.pinggy-free.link": "https://abcde-203-0-113-7.run.pinggy-free.link",
		"https://abcde-203-0-113-7.free.pinggy.net":      "https://abcde-203-0-113-7.free.pinggy.net",
		"https://myapp.pinggy.link":                      "https://myapp.pinggy.link",
		"https://evil.example.com":                       "",
		"http://abcde.run.pinggy-free.link":              "",
	}
	for line, want := range cases {
		if got := extractURL(line); got != want {
			t.Errorf("%q: got %q want %q", line, got, want)
		}
	}
}

// --- classification --------------------------------------------------------------------

func TestClassifyStderrSeparatesInterceptionFromUnavailability(t *testing.T) {
	cases := map[string]string{
		"Host key verification failed.":                                    CodeUntrusted,
		"No RSA host key is known for [free.pinggy.io]:443":                CodeUntrusted,
		"ssh: connect to host free.pinggy.io port 443: Connection refused": CodeUnavailable,
		"ssh: Could not resolve hostname free.pinggy.io":                   CodeUnavailable,
		"Permission denied (publickey).":                                   CodeUnauthorized,
		"something nobody has seen before":                                 "",
	}
	for tail, want := range cases {
		if got := classifyStderr(tail); got != want {
			t.Errorf("%q: got %q want %q", tail, got, want)
		}
	}
}

// --- start / stop ----------------------------------------------------------------------

func TestStartParsesTheURLWithoutAPTY(t *testing.T) {
	p := &PinggyProvider{SSHPath: writeFake(t), Now: func() time.Time {
		return time.Date(2026, 8, 1, 9, 0, 0, 0, time.UTC)
	}}
	t.Setenv("FAKE_MODE", "ok")
	t.Setenv("FAKE_SLUG", "abcde")
	result, handle, err := p.Start(context.Background(), baseOptions(t))
	if err != nil {
		t.Fatal(err)
	}
	defer handle.Stop()
	if result.URL != "https://abcde-203-0-113-7.run.pinggy-free.link" {
		t.Fatalf("unexpected url %q", result.URL)
	}
	if result.Authenticated {
		t.Error("the free-tier banner means not authenticated")
	}
	if result.ExpiresAt != "2026-08-01T10:00:00Z" {
		t.Errorf("expiry should follow the banner's 60 minutes, got %q", result.ExpiresAt)
	}
}

func TestStartTearsDownWhenTheProviderDowngradesAPaidTunnel(t *testing.T) {
	// The measurement that matters most (PG-01 #7): an invalid credential is not rejected.
	// A user who supplied a Pro token must not be handed a 60-minute anonymous tunnel and
	// told it worked.
	p := &PinggyProvider{SSHPath: writeFake(t)}
	t.Setenv("FAKE_MODE", "ok")
	opts := baseOptions(t)
	opts.Credential = "xGBTh6cy58qAAAA"
	_, _, err := p.Start(context.Background(), opts)
	if err == nil {
		t.Fatal("a downgraded tunnel must be reported as unauthorized, not returned")
	}
	var provErr *ProviderError
	if !asProviderError(err, &provErr) || provErr.Code != CodeUnauthorized {
		t.Fatalf("expected %s, got %v", CodeUnauthorized, err)
	}
}

func TestStartReportsAnAuthenticatedTunnel(t *testing.T) {
	p := &PinggyProvider{SSHPath: writeFake(t)}
	t.Setenv("FAKE_MODE", "authenticated")
	t.Setenv("FAKE_SLUG", "myapp")
	opts := baseOptions(t)
	opts.Credential = "xGBTh6cy58qAAAA"
	result, handle, err := p.Start(context.Background(), opts)
	if err != nil {
		t.Fatal(err)
	}
	defer handle.Stop()
	if !result.Authenticated || result.URL != "https://myapp.pinggy.link" {
		t.Fatalf("unexpected result %+v", result)
	}
}

func TestStartRefusesWhenTheHostKeyDoesNotMatch(t *testing.T) {
	p := &PinggyProvider{SSHPath: writeFake(t)}
	t.Setenv("FAKE_MODE", "hostkey")
	_, _, err := p.Start(context.Background(), baseOptions(t))
	if err == nil {
		t.Fatal("expected the connection to be refused")
	}
	var provErr *ProviderError
	if !asProviderError(err, &provErr) || provErr.Code != CodeUntrusted {
		t.Fatalf("expected %s, got %v", CodeUntrusted, err)
	}
}

func TestStartRefusesWithoutAPinnedKeyFile(t *testing.T) {
	p := &PinggyProvider{SSHPath: writeFake(t)}
	opts := baseOptions(t)
	opts.KnownHostsPath = filepath.Join(t.TempDir(), "absent")
	if _, _, err := p.Start(context.Background(), opts); err == nil {
		t.Fatal("a missing pinned key file must refuse, never fall back to trusting one")
	}
	// And an empty file is the same answer: an operator who truncated it has not opted out
	// of verification.
	empty := filepath.Join(t.TempDir(), "empty")
	if err := os.WriteFile(empty, nil, 0o644); err != nil {
		t.Fatal(err)
	}
	opts.KnownHostsPath = empty
	if _, _, err := p.Start(context.Background(), opts); err == nil {
		t.Fatal("an empty pinned key file must refuse")
	}
}

func TestStartGivesUpWhenNoURLArrives(t *testing.T) {
	p := &PinggyProvider{SSHPath: writeFake(t)}
	t.Setenv("FAKE_MODE", "nourl")
	ctx, cancel := context.WithTimeout(context.Background(), 500*time.Millisecond)
	defer cancel()
	if _, _, err := p.Start(ctx, baseOptions(t)); err == nil {
		t.Fatal("expected a failure when the provider never announces a URL")
	}
}

func TestStopEndsTheProcess(t *testing.T) {
	p := &PinggyProvider{SSHPath: writeFake(t)}
	t.Setenv("FAKE_MODE", "ok")
	_, handle, err := p.Start(context.Background(), baseOptions(t))
	if err != nil {
		t.Fatal(err)
	}
	pid := handle.PID()
	handle.Stop()
	handle.Stop() // idempotent
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		if !processAlive(pid) {
			return
		}
		time.Sleep(20 * time.Millisecond)
	}
	t.Fatalf("process %d survived Stop", pid)
}

func TestArgsAreNeverPassedThroughAShell(t *testing.T) {
	// Every value reaches the child as its own argv entry, so there is no place for a shell
	// to interpret one. This asserts the property rather than trusting it: the fake writes
	// "$*" to a file, and a shell-expanded value would show up mangled there.
	argsFile := filepath.Join(t.TempDir(), "args")
	p := &PinggyProvider{SSHPath: writeFake(t)}
	t.Setenv("FAKE_MODE", "ok")
	t.Setenv("FAKE_ARGS_FILE", argsFile)
	opts := baseOptions(t)
	opts.Protection = ProtectionBasic
	opts.BasicUser = "preview"
	opts.BasicPass = "a;b&c|d$e"
	_, handle, err := p.Start(context.Background(), opts)
	if err != nil {
		t.Fatal(err)
	}
	defer handle.Stop()
	raw, err := os.ReadFile(argsFile)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(raw), "b:preview:a;b&c|d$e") {
		t.Fatalf("the password should arrive verbatim, got %q", string(raw))
	}
}

func processAlive(pid int) bool {
	if pid <= 0 {
		return false
	}
	_, err := os.Stat(filepath.Join("/proc", itoa(pid)))
	return err == nil
}

func itoa(n int) string {
	if n == 0 {
		return "0"
	}
	var digits []byte
	for n > 0 {
		digits = append([]byte{byte('0' + n%10)}, digits...)
		n /= 10
	}
	return string(digits)
}

// asProviderError is errors.As with a narrower signature, kept local so the test file does
// not import errors just for one call.
func asProviderError(err error, target **ProviderError) bool {
	pe, ok := err.(*ProviderError)
	if ok {
		*target = pe
	}
	return ok
}
