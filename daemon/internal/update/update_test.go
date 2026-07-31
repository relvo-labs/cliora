package update

import (
	"archive/tar"
	"bytes"
	"compress/gzip"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"os/user"
	"path/filepath"
	"reflect"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/cliora/cliora/daemon/internal/metrics"
	"github.com/cliora/cliora/daemon/internal/protocol"
)

// --------------------------------------------------------------------------- //
// Fakes
// --------------------------------------------------------------------------- //

type fakeFetcher struct {
	manifest Manifest
	err      error
	calls    int
}

func (f *fakeFetcher) Fetch(context.Context) (Manifest, error) {
	f.calls++
	return f.manifest, f.err
}

type fakeDownloader struct {
	payload []byte
	err     error
	calls   int
}

func (d *fakeDownloader) Download(_ context.Context, _ Artifact, destination string) error {
	d.calls++
	if d.err != nil {
		return d.err
	}
	return os.WriteFile(destination, d.payload, 0o600)
}

type fakeRestarter struct {
	available  error
	restartErr error
	restarts   int
	// After this many restarts, stop failing — models a rollback restart succeeding
	// after the update restart failed.
	failFirstOnly bool
}

func (r *fakeRestarter) Available() error { return r.available }

func (r *fakeRestarter) Restart(context.Context) error {
	r.restarts++
	if r.restartErr != nil && (!r.failFirstOnly || r.restarts == 1) {
		return r.restartErr
	}
	return nil
}

type fakeHealth struct {
	err   error
	calls int
	// Healthy from this call onward (1 = immediately).
	healthyFrom int
}

func (h *fakeHealth) Check(context.Context) error {
	h.calls++
	if h.healthyFrom > 0 && h.calls >= h.healthyFrom {
		return nil
	}
	return h.err
}

// --------------------------------------------------------------------------- //
// Fixtures
// --------------------------------------------------------------------------- //

// tarballWithBinary builds a gzipped tar containing one member named `agentd`
// whose content is `script`, so a test can control what `agentd version` prints.
func tarballWithBinary(t *testing.T, script string) []byte {
	t.Helper()
	var raw bytes.Buffer
	gz := gzip.NewWriter(&raw)
	tw := tar.NewWriter(gz)
	body := []byte(script)
	if err := tw.WriteHeader(&tar.Header{
		Name: "agentd", Mode: 0o755, Size: int64(len(body)), Typeflag: tar.TypeReg,
	}); err != nil {
		t.Fatal(err)
	}
	if _, err := tw.Write(body); err != nil {
		t.Fatal(err)
	}
	if err := tw.Close(); err != nil {
		t.Fatal(err)
	}
	if err := gz.Close(); err != nil {
		t.Fatal(err)
	}
	return raw.Bytes()
}

func digestOf(data []byte) string {
	sum := sha256.Sum256(data)
	return hex.EncodeToString(sum[:])
}

type harness struct {
	updater    *Updater
	fetcher    *fakeFetcher
	downloader *fakeDownloader
	restarter  *fakeRestarter
	health     *fakeHealth
	binaryPath string
	staging    string
}

// newHarness wires an Updater over a temp directory with an installed "binary"
// containing a known marker, so a test can tell whether the file was replaced.
func newHarness(t *testing.T, current, target string, payload []byte) *harness {
	t.Helper()
	dir := t.TempDir()
	binaryPath := filepath.Join(dir, "agentd")
	if err := os.WriteFile(binaryPath, []byte("OLD-BINARY"), 0o755); err != nil {
		t.Fatal(err)
	}
	staging := filepath.Join(dir, "staging")

	fetcher := &fakeFetcher{manifest: Manifest{
		Latest: target,
		Artifacts: []Artifact{{
			Version:      target,
			Architecture: "amd64",
			Filename:     fmt.Sprintf("agentd_%s_linux_amd64.tar.gz", target),
			SHA256:       digestOf(payload),
			Size:         int64(len(payload)),
		}},
	}}
	downloader := &fakeDownloader{payload: payload}
	restarter := &fakeRestarter{}
	health := &fakeHealth{healthyFrom: 1}

	h := &harness{
		fetcher: fetcher, downloader: downloader, restarter: restarter, health: health,
		binaryPath: binaryPath, staging: staging,
	}
	h.updater = New(current, Options{
		Fetcher:        fetcher,
		Downloader:     downloader,
		Restarter:      restarter,
		HealthChecker:  health,
		Architecture:   "amd64",
		BinaryPath:     binaryPath,
		StagingRoot:    staging,
		HealthTimeout:  50 * time.Millisecond,
		HealthInterval: time.Millisecond,
		// Default probe: report the target version, so the happy path passes without
		// executing anything. Tests that care override it.
		VersionProbe: func(context.Context, string) (string, error) { return target, nil },
	})
	return h
}

func (h *harness) installed(t *testing.T) string {
	t.Helper()
	data, err := os.ReadFile(h.binaryPath)
	if err != nil {
		t.Fatal(err)
	}
	return string(data)
}

func (h *harness) backups(t *testing.T) []string {
	t.Helper()
	matches, err := filepath.Glob(h.binaryPath + ".bak-*")
	if err != nil {
		t.Fatal(err)
	}
	return matches
}

// --------------------------------------------------------------------------- //
// The input boundary (SEC-002)
// --------------------------------------------------------------------------- //

// TestUpdateAcceptsNoArtifactReference is the structural half of SEC-002: the
// protocol refuses a `url`/`binary_path`/`sha256` field, and this refuses the same
// thing one layer down. Without it, "just add a --url for testing" would reopen the
// hole the protocol closed.
func TestUpdateAcceptsNoArtifactReference(t *testing.T) {
	method, ok := reflect.TypeOf(&Updater{}).MethodByName("Update")
	if !ok {
		t.Fatal("Updater has no Update method")
	}
	fn := method.Type
	// (receiver, ctx, string, bool, bool)
	if fn.NumIn() != 5 {
		t.Fatalf("Update takes %d parameters; the signature is a security boundary", fn.NumIn()-1)
	}
	strings := 0
	for i := 2; i < fn.NumIn(); i++ {
		switch fn.In(i).Kind() {
		case reflect.String:
			strings++
		case reflect.Bool:
		default:
			t.Fatalf("Update parameter %d is a %s; only a version string and flags are allowed",
				i-1, fn.In(i).Kind())
		}
	}
	if strings != 1 {
		t.Fatalf("Update takes %d string parameters; exactly one (the version) is allowed", strings)
	}
}

func TestManifestEntryWithAnUnacceptableFilenameIsNotUsable(t *testing.T) {
	// A compromised or buggy server must not be able to turn a manifest filename
	// into a path. Every rejection collapses to "not an allowlisted release".
	for _, filename := range []string{
		"../../etc/passwd",
		"/etc/passwd",
		"agentd_1.0.0_linux_amd64.tar.gz/../evil",
		"evil.sh",
		"agentd_1.0.0_windows_amd64.tar.gz",
	} {
		manifest := Manifest{Artifacts: []Artifact{{
			Version: "1.0.0", Architecture: "amd64", Filename: filename,
			SHA256: strings.Repeat("a", 64), Size: 10,
		}}}
		if _, ok := manifest.Find("1.0.0", "amd64"); ok {
			t.Errorf("accepted a manifest entry named %q", filename)
		}
	}
}

func TestManifestEntryWithAMalformedDigestIsNotUsable(t *testing.T) {
	for _, digest := range []string{"", "abc", strings.Repeat("A", 64), strings.Repeat("g", 64)} {
		manifest := Manifest{Artifacts: []Artifact{{
			Version: "1.0.0", Architecture: "amd64",
			Filename: "agentd_1.0.0_linux_amd64.tar.gz", SHA256: digest, Size: 10,
		}}}
		if _, ok := manifest.Find("1.0.0", "amd64"); ok {
			t.Errorf("accepted a manifest entry with digest %q", digest)
		}
	}
}

func TestHTTPBaseRejectsANonWebSocketScheme(t *testing.T) {
	// Silently accepting http:// here would mean the artifact origin is not the
	// server the node authenticated against, and a downgrade to plaintext would pass
	// unnoticed.
	for _, raw := range []string{"http://central", "https://central", "file:///tmp", "", "://x"} {
		if _, err := HTTPBase(raw); err == nil {
			t.Errorf("accepted server.url %q", raw)
		}
	}
}

func TestHTTPBaseMapsSchemeAndDropsThePath(t *testing.T) {
	for _, tc := range []struct{ in, want string }{
		{"wss://central.example/ws/nodes/abc", "https://central.example"},
		{"ws://127.0.0.1:8000/ws/nodes/abc", "http://127.0.0.1:8000"},
	} {
		got, err := HTTPBase(tc.in)
		if err != nil || got != tc.want {
			t.Errorf("HTTPBase(%q) = %q, %v; want %q", tc.in, got, err, tc.want)
		}
	}
}

// --------------------------------------------------------------------------- //
// Privilege (SEC-007)
// --------------------------------------------------------------------------- //

func TestWithoutPrivilegeNothingIsFetchedOrTouched(t *testing.T) {
	// The refusal must happen before any network or disk work: an update this
	// process cannot install should cost nothing. It is also what keeps the daemon
	// non-root rather than escalating to satisfy a remote request.
	h := newHarness(t, "1.0.0", "1.1.0", tarballWithBinary(t, "x"))
	h.restarter.available = ErrNoPrivilege

	result := h.updater.Update(context.Background(), "1.1.0", false, false)

	if result.Status != StatusFailed || result.ErrorCode != CodeNotAllowed {
		t.Fatalf("got %s/%s, want failed/%s", result.Status, result.ErrorCode, CodeNotAllowed)
	}
	if result.Stage != StageManifest {
		t.Errorf("refused at stage %q, want %q (before any work)", result.Stage, StageManifest)
	}
	if h.fetcher.calls != 0 || h.downloader.calls != 0 {
		t.Errorf("fetched %d / downloaded %d times before refusing", h.fetcher.calls, h.downloader.calls)
	}
	if h.installed(t) != "OLD-BINARY" {
		t.Error("the installed binary was modified")
	}
}

func TestSystemdRestarterRefusesWhenNotRoot(t *testing.T) {
	r := &SystemdRestarter{
		Unit:     "agentd",
		Geteuid:  func() int { return 1000 },
		LookPath: func(string) (string, error) { return "/usr/bin/systemctl", nil },
	}
	if err := r.Available(); !errors.Is(err, ErrNoPrivilege) {
		t.Fatalf("Available() = %v, want ErrNoPrivilege", err)
	}
}

func TestSystemdRestarterRefusesWithoutSystemctl(t *testing.T) {
	// A container or non-systemd distro: refuse with an instruction rather than
	// half-installing and leaving the service on the old binary.
	r := &SystemdRestarter{
		Unit:     "agentd",
		Geteuid:  func() int { return 0 },
		LookPath: func(string) (string, error) { return "", errors.New("not found") },
	}
	err := r.Available()
	if err == nil || !strings.Contains(err.Error(), "manually") {
		t.Fatalf("Available() = %v, want an instruction to act manually", err)
	}
}

func TestSystemdRestarterAllowsRoot(t *testing.T) {
	r := &SystemdRestarter{
		Unit:     "agentd",
		Geteuid:  func() int { return 0 },
		LookPath: func(string) (string, error) { return "/usr/bin/systemctl", nil },
	}
	if err := r.Available(); err != nil {
		t.Fatalf("Available() = %v, want nil", err)
	}
}

// --------------------------------------------------------------------------- //
// Healthcheck stage
// --------------------------------------------------------------------------- //

// The regression this file exists for. `agentd update` runs under sudo (ADR 0017),
// so a plain doctor child inherits euid 0 and trips doctor's own EnsureNonRoot —
// which made *every* real update fail healthcheck and roll back, with the
// misleading message "agentd must not run as root". The doctor child must carry the
// unit's User=, not the updater's.
func TestHealthcheckRunsDoctorAsTheServiceUserNotAsRoot(t *testing.T) {
	c := DoctorHealthChecker{
		Unit:        "agentd",
		Geteuid:     func() int { return 0 },
		ServiceUser: func(context.Context, string) (string, error) { return "cliora", nil },
		LookupUser: func(name string) (*user.User, error) {
			return &user.User{Username: name, Uid: "4242", Gid: "4243", HomeDir: "/home/cliora"}, nil
		},
	}
	cred, env, err := c.doctorIdentity(context.Background(), exec.LookPath)
	if err != nil {
		t.Fatalf("doctorIdentity() error = %v", err)
	}
	if cred == nil {
		t.Fatal("doctor would run as root; it must drop to the service user")
	}
	if cred.Uid != 4242 || cred.Gid != 4243 {
		t.Errorf("credential = uid %d gid %d, want 4242/4243", cred.Uid, cred.Gid)
	}
	// HOME must follow the uid: doctor's runtime detection probes the home
	// directory, and root's is unreadable to the service user.
	var home string
	for _, kv := range env {
		if strings.HasPrefix(kv, "HOME=") {
			home = kv
		}
	}
	if home != "HOME=/home/cliora" {
		t.Errorf("HOME = %q, want HOME=/home/cliora", home)
	}
}

func TestHealthcheckRunsDoctorAsItselfWhenNotRoot(t *testing.T) {
	// Unprivileged local dev: there is no privilege to drop, and asking systemd
	// who the service is would be pointless.
	c := DoctorHealthChecker{
		Unit:    "agentd",
		Geteuid: func() int { return 1000 },
		ServiceUser: func(context.Context, string) (string, error) {
			t.Error("the service user must not be looked up when the updater is not root")
			return "", nil
		},
	}
	cred, env, err := c.doctorIdentity(context.Background(), exec.LookPath)
	if err != nil || cred != nil || env != nil {
		t.Fatalf("doctorIdentity() = %v, %v, %v; want nil, nil, nil", cred, env, err)
	}
}

func TestHealthcheckFailsWhenTheServiceUserCannotBeDetermined(t *testing.T) {
	// Root, but systemd cannot say who the unit runs as. Falling back to a root
	// doctor run would report a green healthcheck for a daemon that may not be
	// able to read its own credentials, so the stage fails and names the cause.
	c := DoctorHealthChecker{
		Unit:        "agentd",
		Geteuid:     func() int { return 0 },
		ServiceUser: func(context.Context, string) (string, error) { return "", errors.New("no such unit") },
	}
	_, _, err := c.doctorIdentity(context.Background(), exec.LookPath)
	if err == nil || !strings.Contains(err.Error(), "cannot determine the user of unit agentd") {
		t.Fatalf("doctorIdentity() error = %v, want it to name the unit", err)
	}
}

func TestHealthcheckLetsDoctorReportAServiceThatReallyRunsAsRoot(t *testing.T) {
	// No User= in the unit means the service is genuinely root, which SEC-007
	// forbids. That is doctor's finding to report, not something to mask by
	// dropping to some other identity.
	for _, name := range []string{"", "root"} {
		c := DoctorHealthChecker{
			Unit:        "agentd",
			Geteuid:     func() int { return 0 },
			ServiceUser: func(context.Context, string) (string, error) { return name, nil },
		}
		cred, _, err := c.doctorIdentity(context.Background(), exec.LookPath)
		if err != nil || cred != nil {
			t.Errorf("User=%q: doctorIdentity() = %v, %v; want no credential and no error", name, cred, err)
		}
	}
}

func TestHealthcheckFailsWhenTheServiceUserDoesNotExist(t *testing.T) {
	c := DoctorHealthChecker{
		Unit:        "agentd",
		Geteuid:     func() int { return 0 },
		ServiceUser: func(context.Context, string) (string, error) { return "ghost", nil },
		LookupUser:  func(string) (*user.User, error) { return nil, errors.New("unknown user") },
	}
	_, _, err := c.doctorIdentity(context.Background(), exec.LookPath)
	if err == nil || !strings.Contains(err.Error(), `service user "ghost"`) {
		t.Fatalf("doctorIdentity() error = %v, want it to name the missing user", err)
	}
}

// --------------------------------------------------------------------------- //
// Manifest stage
// --------------------------------------------------------------------------- //

func TestAnUnpublishedVersionIsRefusedWithoutTouchingTheFilesystem(t *testing.T) {
	h := newHarness(t, "1.0.0", "1.1.0", tarballWithBinary(t, "x"))

	result := h.updater.Update(context.Background(), "9.9.9", false, false)

	if result.ErrorCode != CodeNotAllowed || result.Stage != StageManifest {
		t.Fatalf("got %s/%s, want %s at %s", result.Stage, result.ErrorCode, CodeNotAllowed, StageManifest)
	}
	if h.downloader.calls != 0 {
		t.Error("downloaded an artifact for an unpublished version")
	}
	if _, err := os.Stat(h.staging); err == nil {
		t.Error("created a staging directory for an unpublished version")
	}
}

func TestAnArchitectureThatWasNotBuiltIsRefused(t *testing.T) {
	h := newHarness(t, "1.0.0", "1.1.0", tarballWithBinary(t, "x"))
	h.fetcher.manifest.Artifacts[0].Architecture = "arm64"

	result := h.updater.Update(context.Background(), "1.1.0", false, false)
	if result.ErrorCode != CodeNotAllowed {
		t.Fatalf("got %s, want %s", result.ErrorCode, CodeNotAllowed)
	}
}

func TestAnUnreachableManifestIsRetryableNotForbidden(t *testing.T) {
	// The distinction matters to the operator: DOWNLOAD_FAILED means "try again",
	// NOT_ALLOWED means "this will never work".
	h := newHarness(t, "1.0.0", "1.1.0", tarballWithBinary(t, "x"))
	h.fetcher.err = errors.New("connection refused")

	result := h.updater.Update(context.Background(), "1.1.0", false, false)
	if result.ErrorCode != CodeDownloadFailed {
		t.Fatalf("got %s, want %s", result.ErrorCode, CodeDownloadFailed)
	}
}

func TestUpdatingToTheRunningVersionSucceedsAsANoOp(t *testing.T) {
	// So "update the fleet to X" is idempotent instead of producing a failure for
	// every node already on X.
	h := newHarness(t, "1.1.0", "1.1.0", tarballWithBinary(t, "x"))

	result := h.updater.Update(context.Background(), "1.1.0", false, false)

	if result.Status != StatusSucceeded {
		t.Fatalf("got %s, want succeeded", result.Status)
	}
	if h.downloader.calls != 0 {
		t.Error("downloaded an artifact for a version already installed")
	}
	if h.restarter.restarts != 0 {
		t.Error("restarted the service for a no-op update")
	}
}

func TestADowngradeIsRefusedUnlessAskedFor(t *testing.T) {
	payload := tarballWithBinary(t, "x")
	h := newHarness(t, "1.2.0", "1.1.0", payload)

	refused := h.updater.Update(context.Background(), "1.1.0", false, false)
	if refused.ErrorCode != CodeNotAllowed {
		t.Fatalf("got %s, want %s", refused.ErrorCode, CodeNotAllowed)
	}
	if h.installed(t) != "OLD-BINARY" {
		t.Fatal("a refused downgrade replaced the binary")
	}

	allowed := h.updater.Update(context.Background(), "1.1.0", true, false)
	if allowed.Status != StatusSucceeded {
		t.Fatalf("explicit downgrade: got %s/%s (%s)", allowed.Status, allowed.ErrorCode, allowed.Detail)
	}
}

func TestAPreReleaseIsADowngradeFromTheFinalRelease(t *testing.T) {
	// Otherwise "1.0.0 → 1.0.0-rc1" looks like a sideways move and slips past the
	// downgrade guard.
	if CompareVersions("1.0.0-rc1", "1.0.0") >= 0 {
		t.Error("1.0.0-rc1 does not sort below 1.0.0")
	}
	if CompareVersions("1.0.0", "1.0.0") != 0 {
		t.Error("equal versions do not compare equal")
	}
	if CompareVersions("1.10.0", "1.9.0") <= 0 {
		t.Error("1.10.0 does not sort above 1.9.0 (string comparison leaking in?)")
	}
}

// --------------------------------------------------------------------------- //
// Checksum stage
// --------------------------------------------------------------------------- //

func TestAChecksumMismatchAbortsBeforeAnythingIsExtracted(t *testing.T) {
	payload := tarballWithBinary(t, "x")
	h := newHarness(t, "1.0.0", "1.1.0", payload)
	// The server serves something else than it published.
	h.downloader.payload = append([]byte("tampered"), payload...)

	result := h.updater.Update(context.Background(), "1.1.0", false, false)

	if result.ErrorCode != CodeChecksumMismatch || result.Stage != StageChecksum {
		t.Fatalf("got %s/%s, want %s at %s",
			result.Stage, result.ErrorCode, CodeChecksumMismatch, StageChecksum)
	}
	if h.installed(t) != "OLD-BINARY" {
		t.Fatal("a checksum mismatch replaced the installed binary")
	}
	if len(h.backups(t)) != 0 {
		t.Error("a checksum mismatch took a backup, so it got as far as the swap")
	}
	if h.restarter.restarts != 0 {
		t.Error("a checksum mismatch restarted the service")
	}
}

func TestTheStagingDirectoryIsAlwaysCleanedUp(t *testing.T) {
	// A leftover archive is both wasted disk and a stale candidate a later run might
	// pick up.
	for _, name := range []string{"success", "mismatch"} {
		payload := tarballWithBinary(t, "x")
		h := newHarness(t, "1.0.0", "1.1.0", payload)
		if name == "mismatch" {
			h.downloader.payload = []byte("wrong")
		}
		h.updater.Update(context.Background(), "1.1.0", false, false)
		if entries, err := os.ReadDir(filepath.Join(h.staging, "1.1.0")); err == nil && len(entries) > 0 {
			t.Errorf("%s: staging directory still holds %d entries", name, len(entries))
		}
	}
}

func TestADownloadFailureLeavesNoResidue(t *testing.T) {
	h := newHarness(t, "1.0.0", "1.1.0", tarballWithBinary(t, "x"))
	h.downloader.err = errors.New("connection reset")

	result := h.updater.Update(context.Background(), "1.1.0", false, false)

	if result.ErrorCode != CodeDownloadFailed || result.Stage != StageDownload {
		t.Fatalf("got %s/%s", result.Stage, result.ErrorCode)
	}
	if entries, err := os.ReadDir(filepath.Join(h.staging, "1.1.0")); err == nil && len(entries) > 0 {
		t.Error("a failed download left files behind")
	}
}

// --------------------------------------------------------------------------- //
// Swap stage: verify before replacing
// --------------------------------------------------------------------------- //

func TestAStagedBinaryReportingTheWrongVersionIsNotInstalled(t *testing.T) {
	// The digest matched, so the artifact *is* what the server published — but its
	// filename and its own version disagree. Installing it would leave the fleet
	// reporting a version it is not running.
	payload := tarballWithBinary(t, "x")
	h := newHarness(t, "1.0.0", "1.1.0", payload)
	h.updater.opts.VersionProbe = func(context.Context, string) (string, error) {
		return "0.9.0", nil
	}

	result := h.updater.Update(context.Background(), "1.1.0", false, false)

	if result.Stage != StageSwap || result.ErrorCode != CodeNotAllowed {
		t.Fatalf("got %s/%s, want %s/%s", result.Stage, result.ErrorCode, StageSwap, CodeNotAllowed)
	}
	if h.installed(t) != "OLD-BINARY" {
		t.Fatal("a version-mismatched binary was installed")
	}
	if len(h.backups(t)) != 0 {
		t.Error("took a backup before verifying the staged binary")
	}
}

func TestAStagedBinaryThatCannotExecuteIsNotInstalled(t *testing.T) {
	// Wrong architecture, corrupt link: caught while the installation is untouched.
	h := newHarness(t, "1.0.0", "1.1.0", tarballWithBinary(t, "x"))
	h.updater.opts.VersionProbe = func(context.Context, string) (string, error) {
		return "", errors.New("exec format error")
	}

	result := h.updater.Update(context.Background(), "1.1.0", false, false)

	if result.Stage != StageSwap {
		t.Fatalf("failed at %s, want %s", result.Stage, StageSwap)
	}
	if h.installed(t) != "OLD-BINARY" {
		t.Fatal("an unexecutable binary was installed")
	}
}

func TestAnArchiveWithoutTheBinaryIsRejected(t *testing.T) {
	var raw bytes.Buffer
	gz := gzip.NewWriter(&raw)
	tw := tar.NewWriter(gz)
	_ = tw.WriteHeader(&tar.Header{Name: "README", Mode: 0o644, Size: 2, Typeflag: tar.TypeReg})
	_, _ = tw.Write([]byte("hi"))
	_ = tw.Close()
	_ = gz.Close()

	h := newHarness(t, "1.0.0", "1.1.0", raw.Bytes())
	result := h.updater.Update(context.Background(), "1.1.0", false, false)

	if result.Stage != StageSwap {
		t.Fatalf("failed at %s, want %s", result.Stage, StageSwap)
	}
	if h.installed(t) != "OLD-BINARY" {
		t.Fatal("replaced the binary from an archive that had none")
	}
}

func TestExtractionIgnoresEveryMemberExceptTheBinary(t *testing.T) {
	// Not a general extractor on purpose: a traversal path, a symlink or a second
	// payload is never written, because nothing but `agentd` is read out at all.
	var raw bytes.Buffer
	gz := gzip.NewWriter(&raw)
	tw := tar.NewWriter(gz)
	for _, name := range []string{"../../evil", "/etc/evil", "bin/agentd", "agentd"} {
		body := []byte("payload-" + name)
		_ = tw.WriteHeader(&tar.Header{
			Name: name, Mode: 0o755, Size: int64(len(body)), Typeflag: tar.TypeReg,
		})
		_, _ = tw.Write(body)
	}
	_ = tw.WriteHeader(&tar.Header{
		Name: "agentd-link", Typeflag: tar.TypeSymlink, Linkname: "/etc/passwd", Mode: 0o777,
	})
	_ = tw.Close()
	_ = gz.Close()

	dir := t.TempDir()
	archive := filepath.Join(dir, "a.tar.gz")
	if err := os.WriteFile(archive, raw.Bytes(), 0o600); err != nil {
		t.Fatal(err)
	}
	destination := filepath.Join(dir, "out")
	if err := extractBinary(archive, destination); err != nil {
		t.Fatalf("extractBinary: %v", err)
	}

	data, err := os.ReadFile(destination)
	if err != nil {
		t.Fatal(err)
	}
	if string(data) != "payload-agentd" {
		t.Errorf("extracted %q; want only the root `agentd` member", data)
	}
	for _, stray := range []string{"evil", "etc", "bin", "agentd-link"} {
		if _, err := os.Stat(filepath.Join(dir, stray)); err == nil {
			t.Errorf("extraction created %q", stray)
		}
	}
}

func TestADryRunVerifiesEverythingAndReplacesNothing(t *testing.T) {
	h := newHarness(t, "1.0.0", "1.1.0", tarballWithBinary(t, "x"))

	result := h.updater.Update(context.Background(), "1.1.0", false, true)

	if result.Status != StatusSucceeded {
		t.Fatalf("got %s/%s (%s)", result.Status, result.ErrorCode, result.Detail)
	}
	if h.downloader.calls != 1 {
		t.Error("a dry run must still download and verify")
	}
	if h.installed(t) != "OLD-BINARY" {
		t.Fatal("a dry run replaced the binary")
	}
	if h.restarter.restarts != 0 {
		t.Error("a dry run restarted the service")
	}
}

func TestADryRunWithoutPrivilegeStillVerifiesButSaysSo(t *testing.T) {
	// A rehearsal must not be harder to perform than the real thing. The question a
	// dry run answers is "is this artifact installable?", which privilege does not
	// change — so it proceeds, and reports the privilege verdict rather than hiding it.
	h := newHarness(t, "1.0.0", "1.1.0", tarballWithBinary(t, "x"))
	h.restarter.available = ErrNoPrivilege

	result := h.updater.Update(context.Background(), "1.1.0", false, true)

	if result.Status != StatusSucceeded {
		t.Fatalf("got %s/%s (%s)", result.Status, result.ErrorCode, result.Detail)
	}
	if h.downloader.calls != 1 {
		t.Error("the dry run stopped before verifying the artifact")
	}
	if !strings.Contains(result.Detail, "sudo agentd update") {
		t.Errorf("the dry run did not mention the missing privilege: %q", result.Detail)
	}
	if h.installed(t) != "OLD-BINARY" {
		t.Fatal("a dry run replaced the binary")
	}
}

func TestARealUpdateWithoutPrivilegeStillRefusesEarly(t *testing.T) {
	// The dry-run exception must not leak into the real path: without privilege the
	// refusal has to come before any network or disk work.
	h := newHarness(t, "1.0.0", "1.1.0", tarballWithBinary(t, "x"))
	h.restarter.available = ErrNoPrivilege

	result := h.updater.Update(context.Background(), "1.1.0", false, false)

	if result.ErrorCode != CodeNotAllowed {
		t.Fatalf("got %s, want %s", result.ErrorCode, CodeNotAllowed)
	}
	if h.fetcher.calls != 0 || h.downloader.calls != 0 {
		t.Errorf("fetched %d / downloaded %d before refusing", h.fetcher.calls, h.downloader.calls)
	}
}

// --------------------------------------------------------------------------- //
// Success, restart and rollback
// --------------------------------------------------------------------------- //

func TestASuccessfulUpdateReplacesTheBinaryAndKeepsABackup(t *testing.T) {
	h := newHarness(t, "1.0.0", "1.1.0", tarballWithBinary(t, "NEW-BINARY"))
	metrics.Reset()

	result := h.updater.Update(context.Background(), "1.1.0", false, false)

	if result.Status != StatusSucceeded || result.Stage != StageHealthcheck {
		t.Fatalf("got %s at %s (%s)", result.Status, result.Stage, result.Detail)
	}
	if h.installed(t) != "NEW-BINARY" {
		t.Errorf("installed binary is %q", h.installed(t))
	}
	backups := h.backups(t)
	if len(backups) != 1 {
		t.Fatalf("kept %d backups, want 1", len(backups))
	}
	// Named after the version it holds, so a manual rollback is unambiguous.
	if !strings.HasSuffix(backups[0], ".bak-1.0.0") {
		t.Errorf("backup is named %q", filepath.Base(backups[0]))
	}
	if data, _ := os.ReadFile(backups[0]); string(data) != "OLD-BINARY" {
		t.Error("the backup does not hold the previous binary")
	}
	if h.restarter.restarts != 1 {
		t.Errorf("restarted %d times, want 1", h.restarter.restarts)
	}
	if got := metrics.CounterValue(DaemonUpdateTotal, map[string]string{
		"status": StatusSucceeded, "stage": StageHealthcheck,
	}); got != 1 {
		t.Errorf("daemon_update_total = %d, want 1", got)
	}
}

func TestTheBackupIsACopySoTheBinaryPathIsNeverMissing(t *testing.T) {
	// Renaming the live binary away would leave a window in which the path does not
	// exist; a `systemctl restart` landing in it fails with nothing to roll back to.
	h := newHarness(t, "1.0.0", "1.1.0", tarballWithBinary(t, "NEW-BINARY"))
	h.restarter.restartErr = nil
	seen := make(chan bool, 1)
	h.updater.opts.Restarter = &probeRestarter{binaryPath: h.binaryPath, seen: seen}

	h.updater.Update(context.Background(), "1.1.0", false, false)

	select {
	case existed := <-seen:
		if !existed {
			t.Fatal("the binary path did not exist when the restart ran")
		}
	default:
		t.Fatal("the restart never ran")
	}
}

type probeRestarter struct {
	binaryPath string
	seen       chan bool
}

func (p *probeRestarter) Available() error { return nil }
func (p *probeRestarter) Restart(context.Context) error {
	_, err := os.Stat(p.binaryPath)
	p.seen <- err == nil
	return nil
}

func TestAFailedRestartRollsBackAndRestartsTheOldBinary(t *testing.T) {
	h := newHarness(t, "1.0.0", "1.1.0", tarballWithBinary(t, "NEW-BINARY"))
	h.restarter.restartErr = errors.New("job failed")
	h.restarter.failFirstOnly = true

	result := h.updater.Update(context.Background(), "1.1.0", false, false)

	if result.Status != StatusRolledBack || result.Stage != StageRestart {
		t.Fatalf("got %s at %s, want %s at %s",
			result.Status, result.Stage, StatusRolledBack, StageRestart)
	}
	if h.installed(t) != "OLD-BINARY" {
		t.Fatalf("after rollback the installed binary is %q", h.installed(t))
	}
	if h.restarter.restarts != 2 {
		t.Errorf("restarted %d times; want 2 (the attempt and the rollback)", h.restarter.restarts)
	}
}

func TestAFailedHealthCheckRollsBack(t *testing.T) {
	h := newHarness(t, "1.0.0", "1.1.0", tarballWithBinary(t, "NEW-BINARY"))
	h.health.healthyFrom = 0
	h.health.err = errors.New("doctor failed")

	result := h.updater.Update(context.Background(), "1.1.0", false, false)

	if result.Status != StatusRolledBack || result.ErrorCode != CodeHealthcheckFail {
		t.Fatalf("got %s/%s, want %s/%s",
			result.Status, result.ErrorCode, StatusRolledBack, CodeHealthcheckFail)
	}
	if result.Stage != StageHealthcheck {
		t.Errorf("stage %q", result.Stage)
	}
	if h.installed(t) != "OLD-BINARY" {
		t.Fatalf("after rollback the installed binary is %q", h.installed(t))
	}
	if h.health.calls < 2 {
		t.Errorf("health checked %d times; it must be polled, not sampled once", h.health.calls)
	}
}

func TestAHealthCheckThatPassesOnRetryIsNotARollback(t *testing.T) {
	// A restarting service is briefly unhealthy; failing on the first sample would
	// roll back every successful update.
	h := newHarness(t, "1.0.0", "1.1.0", tarballWithBinary(t, "NEW-BINARY"))
	h.health.err = errors.New("starting")
	h.health.healthyFrom = 3

	result := h.updater.Update(context.Background(), "1.1.0", false, false)

	if result.Status != StatusSucceeded {
		t.Fatalf("got %s/%s (%s)", result.Status, result.ErrorCode, result.Detail)
	}
	if h.installed(t) != "NEW-BINARY" {
		t.Error("the new binary was rolled back despite becoming healthy")
	}
}

func TestARollbackThatCannotRestoreReportsFailedNotRolledBack(t *testing.T) {
	// The distinction is the whole point: `rolled_back` means contained,
	// `failed` + RollbackFailed means the box needs hands on it.
	h := newHarness(t, "1.0.0", "1.1.0", tarballWithBinary(t, "NEW-BINARY"))
	h.health.healthyFrom = 0
	h.health.err = errors.New("doctor failed")
	// Delete the backup the moment it is taken, so the restore has nothing to use.
	h.updater.opts.Restarter = &deletingRestarter{binaryPath: h.binaryPath}

	result := h.updater.Update(context.Background(), "1.1.0", false, false)

	if result.Status != StatusFailed || !result.RollbackFailed {
		t.Fatalf("got %s (rollbackFailed=%v), want failed with rollbackFailed",
			result.Status, result.RollbackFailed)
	}
	if !strings.Contains(result.Detail, "rollback failed") {
		t.Errorf("detail does not mention the failed rollback: %q", result.Detail)
	}
}

type deletingRestarter struct{ binaryPath string }

func (d *deletingRestarter) Available() error { return nil }
func (d *deletingRestarter) Restart(context.Context) error {
	matches, _ := filepath.Glob(d.binaryPath + ".bak-*")
	for _, match := range matches {
		_ = os.Remove(match)
	}
	return nil
}

func TestTheHealthCheckIsBoundedByItsBudget(t *testing.T) {
	h := newHarness(t, "1.0.0", "1.1.0", tarballWithBinary(t, "NEW-BINARY"))
	h.health.healthyFrom = 0
	h.health.err = errors.New("never healthy")
	h.updater.opts.HealthTimeout = 20 * time.Millisecond
	h.updater.opts.HealthInterval = 5 * time.Millisecond

	start := time.Now()
	result := h.updater.Update(context.Background(), "1.1.0", false, false)
	elapsed := time.Since(start)

	if result.ErrorCode != CodeHealthcheckFail {
		t.Fatalf("got %s", result.ErrorCode)
	}
	if elapsed > 2*time.Second {
		t.Errorf("health check took %s; the budget is not bounding it", elapsed)
	}
}

// --------------------------------------------------------------------------- //
// Concurrency
// --------------------------------------------------------------------------- //

func TestASecondConcurrentUpdateIsRefusedRatherThanQueued(t *testing.T) {
	// Queueing would mean two swaps of the same file back to back, with the second
	// one's backup holding the first one's binary.
	h := newHarness(t, "1.0.0", "1.1.0", tarballWithBinary(t, "NEW-BINARY"))
	entered := make(chan struct{})
	proceed := make(chan struct{})
	h.updater.opts.Restarter = &blockingRestarter{entered: entered, proceed: proceed}

	var first Result
	var wg sync.WaitGroup
	wg.Add(1)
	go func() {
		defer wg.Done()
		first = h.updater.Update(context.Background(), "1.1.0", false, false)
	}()

	<-entered
	second := h.updater.Update(context.Background(), "1.1.0", false, false)
	close(proceed)
	wg.Wait()

	if second.ErrorCode != CodeInProgress {
		t.Fatalf("second update got %s, want %s", second.ErrorCode, CodeInProgress)
	}
	if first.Status != StatusSucceeded {
		t.Errorf("first update got %s/%s (%s)", first.Status, first.ErrorCode, first.Detail)
	}
	if h.downloader.calls != 1 {
		t.Errorf("downloaded %d times; the refused update must do no work", h.downloader.calls)
	}
}

type blockingRestarter struct {
	entered chan struct{}
	proceed chan struct{}
	once    sync.Once
}

func (b *blockingRestarter) Available() error { return nil }
func (b *blockingRestarter) Restart(context.Context) error {
	b.once.Do(func() {
		close(b.entered)
		<-b.proceed
	})
	return nil
}

func TestTheLockIsReleasedAfterAFailure(t *testing.T) {
	// A lock leaked on the error path would make every later update report
	// UPDATE_IN_PROGRESS forever.
	h := newHarness(t, "1.0.0", "1.1.0", tarballWithBinary(t, "x"))
	h.fetcher.err = errors.New("down")
	h.updater.Update(context.Background(), "1.1.0", false, false)

	h.fetcher.err = nil
	second := h.updater.Update(context.Background(), "1.1.0", false, false)
	if second.ErrorCode == CodeInProgress {
		t.Fatal("the process lock was not released after a failure")
	}
}

// --------------------------------------------------------------------------- //
// HTTP source
// --------------------------------------------------------------------------- //

func TestTheHTTPSourceReadsTheManifestAndTheArtifact(t *testing.T) {
	payload := tarballWithBinary(t, "NEW")
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/api/releases/manifest":
			_, _ = fmt.Fprintf(w, `{"latest":"1.1.0","artifacts":[{"version":"1.1.0",`+
				`"architecture":"amd64","filename":"agentd_1.1.0_linux_amd64.tar.gz",`+
				`"sha256":%q,"size":%d}]}`, digestOf(payload), len(payload))
		case "/api/downloads/agentd_1.1.0_linux_amd64.tar.gz":
			_, _ = w.Write(payload)
		default:
			w.WriteHeader(http.StatusNotFound)
		}
	}))
	defer server.Close()

	source := &HTTPSource{BaseURL: server.URL, Client: server.Client()}
	manifest, err := source.Fetch(context.Background())
	if err != nil {
		t.Fatalf("Fetch: %v", err)
	}
	artifact, ok := manifest.Find("1.1.0", "amd64")
	if !ok {
		t.Fatal("the served manifest entry was not usable")
	}
	destination := filepath.Join(t.TempDir(), "a.tar.gz")
	if err := source.Download(context.Background(), artifact, destination); err != nil {
		t.Fatalf("Download: %v", err)
	}
	if digest, _ := sha256File(destination); digest != artifact.SHA256 {
		t.Error("the downloaded artifact does not match its digest")
	}
}

func TestTheHTTPSourceRefusesToDownloadANameOutsideTheAllowlist(t *testing.T) {
	// This method is the one that puts a server-supplied string into a URL path, so
	// it re-validates rather than trusting an earlier caller to have done it.
	source := &HTTPSource{BaseURL: "http://central", Client: http.DefaultClient}
	err := source.Download(context.Background(),
		Artifact{Filename: "../../etc/passwd"}, filepath.Join(t.TempDir(), "x"))
	if err == nil || !strings.Contains(err.Error(), "allowlisted") {
		t.Fatalf("Download = %v, want an allowlist refusal", err)
	}
}

func TestAnEmptyManifestMeansNothingIsInstallable(t *testing.T) {
	// 200 with an empty list, not 404: the daemon must distinguish "nothing
	// published" from "no such endpoint".
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte(`{"latest":null,"artifacts":[]}`))
	}))
	defer server.Close()

	source := &HTTPSource{BaseURL: server.URL, Client: server.Client()}
	manifest, err := source.Fetch(context.Background())
	if err != nil {
		t.Fatalf("Fetch: %v", err)
	}
	if manifest.Latest != "" || len(manifest.Artifacts) != 0 {
		t.Errorf("got %+v", manifest)
	}
	if _, ok := manifest.Find("1.0.0", "amd64"); ok {
		t.Error("found an artifact in an empty manifest")
	}
}

func TestTheManifestReadIsBounded(t *testing.T) {
	// A hostile or broken server must not be able to stream unbounded JSON into
	// memory.
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"latest":"1.0.0","artifacts":[`))
		chunk := strings.Repeat(`{"version":"1.0.0","architecture":"amd64","filename":"x","sha256":"y","size":1},`, 1000)
		for i := 0; i < 200; i++ {
			if _, err := w.Write([]byte(chunk)); err != nil {
				return
			}
		}
	}))
	defer server.Close()

	source := &HTTPSource{BaseURL: server.URL, Client: server.Client()}
	if _, err := source.Fetch(context.Background()); err == nil {
		t.Fatal("an unbounded manifest body was accepted")
	}
}

// --------------------------------------------------------------------------- //
// The real version probe (executes the candidate)
// --------------------------------------------------------------------------- //

// executableTarball wraps a shell script as the archive's `agentd` member, so the
// default VersionProbe really executes what was extracted.
func executableTarball(t *testing.T, printed string) []byte {
	t.Helper()
	return tarballWithBinary(t, "#!/bin/sh\necho '"+printed+"'\n")
}

func TestTheDefaultProbeExecutesTheExtractedBinary(t *testing.T) {
	// The stubbed probe in the other tests cannot catch a candidate that unpacks
	// without the executable bit, or one whose output has trailing noise. This runs
	// the real thing against a real extracted file.
	h := newHarness(t, "1.0.0", "1.1.0", executableTarball(t, "1.1.0"))
	h.updater.opts.VersionProbe = probeVersion

	result := h.updater.Update(context.Background(), "1.1.0", false, false)

	if result.Status != StatusSucceeded {
		t.Fatalf("got %s/%s (%s)", result.Status, result.ErrorCode, result.Detail)
	}
	if h.installed(t) == "OLD-BINARY" {
		t.Error("the verified binary was not installed")
	}
}

func TestTheDefaultProbeRejectsACandidateReportingAnotherVersion(t *testing.T) {
	h := newHarness(t, "1.0.0", "1.1.0", executableTarball(t, "0.9.0"))
	h.updater.opts.VersionProbe = probeVersion

	result := h.updater.Update(context.Background(), "1.1.0", false, false)

	if result.Stage != StageSwap || result.ErrorCode != CodeNotAllowed {
		t.Fatalf("got %s/%s", result.Stage, result.ErrorCode)
	}
	if h.installed(t) != "OLD-BINARY" {
		t.Fatal("installed a binary reporting the wrong version")
	}
}

func TestTheDefaultProbeReadsOnlyTheFirstLine(t *testing.T) {
	// `agentd version` prints one bare line by design; anything after it must not
	// change the comparison, or an added banner would break every update.
	h := newHarness(t, "1.0.0", "1.1.0",
		tarballWithBinary(t, "#!/bin/sh\necho '1.1.0'\necho 'built by someone'\n"))
	h.updater.opts.VersionProbe = probeVersion

	if result := h.updater.Update(context.Background(), "1.1.0", false, false); result.Failed() {
		t.Fatalf("got %s/%s (%s)", result.Status, result.ErrorCode, result.Detail)
	}
}

func TestExtractionMakesTheCandidateExecutable(t *testing.T) {
	// Written 0600 while incomplete, then chmod 0755 — an extracted binary that
	// stayed 0600 would fail the probe with a confusing "permission denied".
	dir := t.TempDir()
	archive := filepath.Join(dir, "a.tar.gz")
	if err := os.WriteFile(archive, executableTarball(t, "1.1.0"), 0o600); err != nil {
		t.Fatal(err)
	}
	destination := filepath.Join(dir, "agentd")
	if err := extractBinary(archive, destination); err != nil {
		t.Fatal(err)
	}
	info, err := os.Stat(destination)
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm()&0o111 == 0 {
		t.Errorf("extracted binary is %o, not executable", info.Mode().Perm())
	}
}

// --------------------------------------------------------------------------- //
// Staging
// --------------------------------------------------------------------------- //

func TestARealUpdateFailsWhenTheStagingRootIsNotWritable(t *testing.T) {
	// The staged binary has to live under the operator-controlled 0700 root that
	// doctor checks; falling back elsewhere for a real update would move it somewhere
	// unchecked between the checksum and the swap.
	h := newHarness(t, "1.0.0", "1.1.0", tarballWithBinary(t, "x"))
	unwritable := filepath.Join(t.TempDir(), "locked")
	if err := os.Mkdir(unwritable, 0o500); err != nil {
		t.Fatal(err)
	}
	h.updater.opts.StagingRoot = filepath.Join(unwritable, "update")

	result := h.updater.Update(context.Background(), "1.1.0", false, false)

	if result.Stage != StageDownload || result.ErrorCode != CodeDownloadFailed {
		t.Fatalf("got %s/%s", result.Stage, result.ErrorCode)
	}
}

func TestADryRunFallsBackToAPrivateTempDirectory(t *testing.T) {
	// Found by running the real CLI as a non-root user: `/var/lib/agentd` needs root
	// to create, so without this fallback a non-root rehearsal could not run at all —
	// the very thing --dry-run exists for.
	h := newHarness(t, "1.0.0", "1.1.0", tarballWithBinary(t, "x"))
	unwritable := filepath.Join(t.TempDir(), "locked")
	if err := os.Mkdir(unwritable, 0o500); err != nil {
		t.Fatal(err)
	}
	h.updater.opts.StagingRoot = filepath.Join(unwritable, "update")

	result := h.updater.Update(context.Background(), "1.1.0", false, true)

	if result.Status != StatusSucceeded {
		t.Fatalf("got %s/%s (%s)", result.Status, result.ErrorCode, result.Detail)
	}
	if h.downloader.calls != 1 {
		t.Error("the dry run did not reach the download")
	}
}

// --------------------------------------------------------------------------- //
// Naming
// --------------------------------------------------------------------------- //

func TestABackupNameCannotEscapeTheBinaryDirectory(t *testing.T) {
	// The version here is this binary's own build-time value, not wire input — but a
	// path built from an unvalidated string is a habit worth not having.
	for _, version := range []string{"../../etc/passwd", "1.0.0/../..", "", "  "} {
		got := backupPath("/usr/local/bin/agentd", version)
		if filepath.Dir(got) != "/usr/local/bin" {
			t.Errorf("backupPath(%q) = %q, escaped the directory", version, got)
		}
	}
}

func TestEveryStageIsInTheProtocolVocabulary(t *testing.T) {
	// The stage is reported verbatim to Central, and `daemon-update-result.schema.json`
	// closes the enum. A stage this package invents would make Central's codec reject
	// the frame, so the outcome of a real update would be lost — the worst moment to
	// discover a typo.
	allowed := make(map[string]bool, len(protocol.UpdateStages))
	for _, stage := range protocol.UpdateStages {
		allowed[stage] = true
	}
	for _, stage := range []string{
		StageManifest, StageDownload, StageChecksum, StageSwap, StageRestart, StageHealthcheck,
	} {
		if !allowed[stage] {
			t.Errorf("stage %q is not in the protocol vocabulary", stage)
		}
	}
	if len(allowed) != 6 {
		t.Errorf("the protocol declares %d stages; this package implements 6", len(allowed))
	}
}
