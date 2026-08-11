package gitfetch

import (
	"context"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// The URL rules are security properties, not input hygiene, so they are tested as
// such: a credential inside a remote URL surfaces in `git remote -v`, in the reflog
// and in error messages, and the host allowlist is this node's half of a two-layer
// check that Central also performs.
func TestCheckURL(t *testing.T) {
	fetcher := Fetcher{AllowedHosts: []string{"github.com", "GitLab.example.com"}}
	cases := []struct {
		name string
		url  string
		want error
	}{
		{"https on an allowed host", "https://github.com/Lei-k/Traqora", nil},
		{"ssh on an allowed host", "ssh://git@github.com/Lei-k/Traqora", nil},
		{"ssh without a user", "ssh://github.com/Lei-k/Traqora", nil},
		{"any other ssh user is refused", "ssh://root@github.com/Lei-k/Traqora", ErrInvalidArgument},
		{"a password is unrepresentable", "ssh://git:pw@github.com/Lei-k/Traqora", ErrInvalidArgument},
		{"host match is case-insensitive", "https://gitlab.example.com/g/p", nil},
		{"host not on this node's list", "https://evil.example/g/p", ErrHostNotAllowed},
		{"userinfo is refused", "https://user:token@github.com/Lei-k/Traqora", ErrInvalidArgument},
		{"file scheme is refused", "file:///etc/passwd", ErrInvalidArgument},
		{"git scheme is refused", "git://github.com/Lei-k/Traqora", ErrInvalidArgument},
		{"no path", "https://github.com", ErrInvalidArgument},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			err := fetcher.CheckURL(tc.url)
			if tc.want == nil && err != nil {
				t.Fatalf("expected %s to be accepted, got %v", tc.url, err)
			}
			if tc.want != nil && !errors.Is(err, tc.want) {
				t.Fatalf("expected %v for %s, got %v", tc.want, tc.url, err)
			}
		})
	}
}

// The accepted set is exactly the set Central can produce.
//
// Central stores a repository as three columns and assembles `ssh://git@host/path`, so
// `git@` has to be accepted — ssh genuinely needs a user name. Accepting it as a fixed
// literal rather than as "any userinfo" keeps the property that matters: **a password
// is unrepresentable**, which is what would leak into `git remote -v`, the reflog and
// error messages.
func TestOnlyTheProducibleSshUserIsAccepted(t *testing.T) {
	fetcher := Fetcher{AllowedHosts: []string{"github.com"}}
	if err := fetcher.CheckURL("ssh://git@github.com/Lei-k/Traqora"); err != nil {
		t.Fatalf("the canonical ssh clone form must be accepted: %v", err)
	}
	for _, bad := range []string{
		"ssh://root@github.com/a/b",
		"ssh://git:secret@github.com/a/b",
		"https://git@github.com/a/b",
	} {
		if err := fetcher.CheckURL(bad); !errors.Is(err, ErrInvalidArgument) {
			t.Fatalf("accepted %s", bad)
		}
	}
}

func TestMaskUserinfo(t *testing.T) {
	cases := map[string]string{
		"origin\thttps://user:tok@github.com/a/b (fetch)": "origin\thttps://***@github.com/a/b (fetch)",
		"origin\thttps://github.com/a/b (push)":           "origin\thttps://github.com/a/b (push)",
		// An `@` after the first slash is part of the path, not credentials.
		"origin\thttps://github.com/a/b@c (fetch)": "origin\thttps://github.com/a/b@c (fetch)",
	}
	for input, want := range cases {
		if got := MaskUserinfo(input); got != want {
			t.Fatalf("MaskUserinfo(%q) = %q, want %q", input, got, want)
		}
	}
}

// A ref that *is* a flag is the case a closed argv table cannot save you from, so it
// is refused before execve rather than relied on being quoted.
func TestCloneRefusesARefThatIsAFlag(t *testing.T) {
	fetcher := Fetcher{AllowedHosts: []string{"github.com"}}
	_, err := fetcher.Clone(context.Background(), "https://github.com/a/b",
		"--upload-pack=touch /tmp/x", t.TempDir())
	if !errors.Is(err, ErrInvalidArgument) {
		t.Fatalf("expected the flag-shaped ref to be refused, got %v", err)
	}
}

// The end-to-end path, over `file://`… except that `file://` is not an allowed scheme,
// which is itself the point: this test drives the *inspection* commands against a real
// repository instead, and the clone path is covered by the argument tests above plus
// the e2e stack.
func TestInspectionCommandsAgainstARealRepository(t *testing.T) {
	if _, err := exec.LookPath("git"); err != nil {
		t.Skip("git is not installed; it is a runner-mode prerequisite, not a test-suite one")
	}
	dir := t.TempDir()
	run := func(args ...string) {
		t.Helper()
		cmd := exec.Command("git", args...)
		cmd.Dir = dir
		cmd.Env = append(os.Environ(),
			"GIT_CONFIG_GLOBAL=/dev/null", "GIT_CONFIG_SYSTEM=/dev/null",
			"GIT_AUTHOR_NAME=t", "GIT_AUTHOR_EMAIL=t@example.invalid",
			"GIT_COMMITTER_NAME=t", "GIT_COMMITTER_EMAIL=t@example.invalid")
		if out, err := cmd.CombinedOutput(); err != nil {
			t.Fatalf("git %v: %v: %s", args, err, out)
		}
	}
	run("init", "-q", "-b", "main")
	if err := os.WriteFile(filepath.Join(dir, "a.txt"), []byte("one\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	run("add", "a.txt")
	run("commit", "-qm", "first")

	fetcher := Fetcher{Timeout: 30 * time.Second, Env: os.Environ()}
	ctx := context.Background()

	if err := fetcher.SetRunIdentity(ctx, dir, "Dev-VM 01"); err != nil {
		t.Fatalf("identity: %v", err)
	}
	// It does not impersonate a person and does not pretend to be the platform.
	out, err := fetcher.run(ctx, dir, "config", "user.email")
	if err != nil {
		t.Fatal(err)
	}
	if got := strings.TrimSpace(out); got != "cliora-run@dev-vm-01" {
		t.Fatalf("run identity is %q", got)
	}

	status, err := fetcher.Status(ctx, dir)
	if err != nil {
		t.Fatalf("status: %v", err)
	}
	if strings.TrimSpace(status) != "" {
		t.Fatalf("a fresh checkout should be clean, got %q", status)
	}

	if err := os.WriteFile(filepath.Join(dir, "a.txt"), []byte("two\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	diff, err := fetcher.Diff(ctx, dir)
	if err != nil {
		t.Fatalf("diff: %v", err)
	}
	if !strings.Contains(diff, "-one") || !strings.Contains(diff, "+two") {
		t.Fatalf("diff did not describe the change: %s", diff)
	}

	// No remote, so nothing has been pushed anywhere — which is exactly what the run
	// summary reports when an agent leaves work only on disk.
	count, err := fetcher.UnpushedCommits(ctx, dir)
	if err != nil {
		t.Fatalf("unpushed: %v", err)
	}
	if count != 1 {
		t.Fatalf("unpushed commits = %d, want 1", count)
	}
	remotes, err := fetcher.Remotes(ctx, dir)
	if err != nil {
		t.Fatalf("remotes: %v", err)
	}
	if len(remotes) != 0 {
		t.Fatalf("expected no remotes, got %v", remotes)
	}
}

// The daemon's own git calls must not be able to sit on a password prompt: the exit
// condition asks for a failure in seconds, and the idle timer cannot help because the
// clone happens before there is any event stream to measure.
func TestFetchEnvDisablesEveryPrompt(t *testing.T) {
	env := Fetcher{KnownHosts: "/etc/agentd/git_known_hosts"}.fetchEnv(nil)
	joined := strings.Join(env, "\n")
	for _, want := range []string{
		"GIT_TERMINAL_PROMPT=0",
		"GIT_ASKPASS=/bin/false",
		"BatchMode=yes",
		"StrictHostKeyChecking=yes",
		"UserKnownHostsFile=/etc/agentd/git_known_hosts",
	} {
		if !strings.Contains(joined, want) {
			t.Fatalf("fetch environment is missing %s", want)
		}
	}
}

func TestClassifyDistinguishesTheThreeCauses(t *testing.T) {
	// Three different actions for a person: supply a credential, allow the host,
	// correct the branch. A single "clone failed" would make all three the same.
	if got := classify(errors.New("git clone: fatal: Authentication failed for x")); !errors.Is(got, ErrCredentials) {
		t.Fatalf("expected a credential error, got %v", got)
	}
	if got := classify(errors.New("git clone: fatal: Remote branch nope not found")); !errors.Is(got, ErrRefNotFound) {
		t.Fatalf("expected a ref error, got %v", got)
	}
	if got := classify(errors.New("git clone: fatal: unable to access")); errors.Is(got, ErrCredentials) {
		t.Fatal("an unrelated failure was classified as a credential problem")
	}
}
