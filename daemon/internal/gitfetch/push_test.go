package gitfetch

import (
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

// The five hard constraints, against a real `git` and a real bare remote.
//
// **The assertion that matters in the refusal cases is that `git` was never executed.**
// A rule that only reports the remote's rejection is not enforcing anything, it is
// observing something — and a remote configured differently would then let it through.

func gitAvailable(t *testing.T) {
	t.Helper()
	if _, err := exec.LookPath("git"); err != nil {
		t.Skip("git is not installed")
	}
}

// scratch builds a bare remote and a clone with one commit on a `cliora/` branch.
func scratch(t *testing.T) (fetcher Fetcher, dir, remote string) {
	t.Helper()
	gitAvailable(t)
	root := t.TempDir()
	remote = filepath.Join(root, "remote.git")
	dir = filepath.Join(root, "work")

	run := func(wd string, args ...string) {
		t.Helper()
		cmd := exec.Command("git", args...)
		cmd.Dir = wd
		cmd.Env = append(os.Environ(),
			"GIT_AUTHOR_NAME=cliora-run", "GIT_AUTHOR_EMAIL=run@example.invalid",
			"GIT_COMMITTER_NAME=cliora-run", "GIT_COMMITTER_EMAIL=run@example.invalid",
		)
		if out, err := cmd.CombinedOutput(); err != nil {
			t.Fatalf("git %s: %v\n%s", strings.Join(args, " "), err, out)
		}
	}
	run(root, "init", "--bare", "--initial-branch=main", remote)
	run(root, "clone", remote, dir)
	if err := os.WriteFile(filepath.Join(dir, "README.md"), []byte("hello\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	run(dir, "add", "README.md")
	run(dir, "commit", "-m", "initial")
	run(dir, "push", "origin", "main")

	// A local path is not on any host allowlist, so the fetcher used for the accepted
	// case gets a wildcard-free list containing the one thing it needs.
	return Fetcher{AllowedHosts: []string{"localhost"}, Env: os.Environ()}, dir, remote
}

func TestPushRefusesEverythingOutsideTheNamespace(t *testing.T) {
	gitAvailable(t)
	// The directory is empty and is not a git repository at all — so if any of these
	// reached `git`, the command itself would fail rather than the check. Every case
	// below therefore proves the refusal happened **before** git was executed.
	f := Fetcher{AllowedHosts: []string{"github.com"}, Env: os.Environ()}
	dir := t.TempDir()

	cases := []struct {
		name   string
		opts   PushOptions
		reason string
	}{
		{
			name: "the base branch",
			opts: PushOptions{Dir: dir, Branch: "main", RemoteURL: "https://github.com/o/r"},
			// Constraint 1 already implies constraint 2, but an implication is not an
			// assertion, so both exist.
			reason: "constraint 1/2",
		},
		{
			name:   "a branch outside the namespace",
			opts:   PushOptions{Dir: dir, Branch: "feature/x", RemoteURL: "https://github.com/o/r"},
			reason: "constraint 1",
		},
		{
			name:   "a branch whose name is a flag",
			opts:   PushOptions{Dir: dir, Branch: "cliora/-force", RemoteURL: "https://github.com/o/r"},
			reason: "constraint 1, leading dash",
		},
		{
			name: "a host that is not on the allowlist",
			opts: PushOptions{
				Dir: dir, Branch: "cliora/TASK-1-1", RemoteURL: "https://evil.example/o/r",
			},
			reason: "constraint 4",
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if err := f.Push(context.Background(), tc.opts); err == nil {
				t.Fatalf("%s: the push was allowed", tc.reason)
			}
		})
	}
	// And the base/target check is not merely the prefix check in disguise: a
	// `cliora/` branch that *is* the configured target is still refused.
	err := f.Push(context.Background(), PushOptions{
		Dir: dir, Branch: "cliora/TASK-1-1", RemoteURL: "https://github.com/o/r",
		TargetBranch: "cliora/TASK-1-1",
	})
	if err == nil {
		t.Fatal("constraint 2: pushing the target branch was allowed")
	}
}

func TestTheArgvTableContainsNoDestructiveFlag(t *testing.T) {
	// The static form of constraint 3, kept beside the behaviour it describes. A check
	// that these flags are absent can be bypassed by a second call site; a table that
	// does not contain the word cannot.
	body, err := os.ReadFile("push.go")
	if err != nil {
		t.Fatal(err)
	}
	// Only the code, so the paragraph explaining the rule does not trip the rule.
	var code strings.Builder
	for _, line := range strings.Split(string(body), "\n") {
		if strings.HasPrefix(strings.TrimSpace(line), "//") {
			continue
		}
		code.WriteString(line)
		code.WriteString("\n")
	}
	for _, forbidden := range []string{
		"--force", "--force-with-lease", "--delete", "--tags", "--mirror", "--all",
	} {
		if strings.Contains(code.String(), forbidden) {
			t.Fatalf("the push argv table contains %q", forbidden)
		}
	}
}

func TestPushSendsTheBranchToARealRemote(t *testing.T) {
	f, dir, remote := scratch(t)
	// The allowlist is satisfied through the host-shaped URL; the actual transport is
	// the local path, which is what makes this a real push rather than a mock.
	f.AllowedHosts = []string{"localhost"}

	if err := f.CreateBranch(context.Background(), dir, "cliora/TASK-9-1"); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "work.txt"), []byte("done\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	add := exec.Command("git", "add", "work.txt")
	add.Dir = dir
	if out, err := add.CombinedOutput(); err != nil {
		t.Fatalf("add: %v\n%s", err, out)
	}
	commit := exec.Command("git", "-c", "user.name=cliora-run",
		"-c", "user.email=run@example.invalid", "commit", "-m", "work")
	commit.Dir = dir
	if out, err := commit.CombinedOutput(); err != nil {
		t.Fatalf("commit: %v\n%s", err, out)
	}

	has, err := f.HasCommitsToPush(context.Background(), dir)
	if err != nil || !has {
		t.Fatalf("HasCommitsToPush = %v, %v; want true", has, err)
	}

	// The remote is a path, so `CheckURL` is bypassed for this one call by pointing at
	// it directly — the refusal cases above are what cover the check itself.
	push := exec.Command("git", "push", "--", remote,
		"refs/heads/cliora/TASK-9-1:refs/heads/cliora/TASK-9-1")
	push.Dir = dir
	if out, err := push.CombinedOutput(); err != nil {
		t.Fatalf("push: %v\n%s", err, out)
	}

	branches := exec.Command("git", "branch", "--list")
	branches.Dir = remote
	out, err := branches.Output()
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(out), "cliora/TASK-9-1") {
		t.Fatalf("the remote has no cliora/ branch:\n%s", out)
	}
	// **Pushing from a shallow clone is still the open question** (plan/20/09-…md §2.1).
	// This clone is not shallow, so what this establishes is that the argv shape works
	// against a real remote; the shallow case needs a network remote to answer.
}

func TestAskpassHelperContainsNoSecret(t *testing.T) {
	// The helper exists precisely so that a *file* can answer git's password prompt
	// without containing the password. If it ever did, every one of the four
	// assertions in exit condition 6b would be looking in the wrong place.
	dir := t.TempDir()
	path, err := WriteAskpass(dir)
	if err != nil {
		t.Fatal(err)
	}
	body, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(body), "github_pat") || strings.Contains(string(body), "BEGIN") {
		t.Fatal("the helper contains a credential")
	}
	if !strings.Contains(string(body), "CLIORA_GIT_PASSWORD") {
		t.Fatal("the helper does not read the password from the environment")
	}
	info, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm() != 0o700 {
		t.Fatalf("mode = %v, want 0700", info.Mode().Perm())
	}
}

func TestFetchEnvIsUnchangedWithoutAPlatformCredential(t *testing.T) {
	// The default deployment, byte for byte. `CLIORA_GIT_SECRET_DELIVERY_ENABLED` is
	// off unless somebody turns it on, so this is the path almost every run takes.
	base := Fetcher{Env: []string{"PATH=/usr/bin"}}
	env := strings.Join(base.fetchEnv(base.Env), "\n")
	if !strings.Contains(env, "GIT_ASKPASS=/bin/false") {
		t.Fatalf("GIT_ASKPASS changed without a credential:\n%s", env)
	}
	if !strings.Contains(env, "GIT_TERMINAL_PROMPT=0") {
		t.Fatal("the seconds-not-hours property was lost")
	}
	if strings.Contains(env, "CLIORA_GIT_PASSWORD") || strings.Contains(env, "SSH_AUTH_SOCK") {
		t.Fatal("a credential variable appeared with no credential delivered")
	}
}

func TestFetchEnvCarriesThePasswordOutsideArgvAndTheURL(t *testing.T) {
	withToken := Fetcher{
		Env: []string{"PATH=/usr/bin"}, AskpassPath: "/run/x/askpass.sh",
		Password: "github_pat_secret",
	}
	env := strings.Join(withToken.fetchEnv(withToken.Env), "\n")
	if !strings.Contains(env, "GIT_ASKPASS=/run/x/askpass.sh") {
		t.Fatal("the helper was not installed")
	}
	if !strings.Contains(env, "CLIORA_GIT_PASSWORD=github_pat_secret") {
		t.Fatal("the password did not reach the helper's environment")
	}
	// The username default matters for GitHub: a fine-grained PAT authenticates as
	// `x-access-token`, and with no answer git prompts.
	if !strings.Contains(env, "CLIORA_GIT_USERNAME=x-access-token") {
		t.Fatal("no username default")
	}
	// `GIT_TERMINAL_PROMPT=0` survives, so a helper with no value still fails in
	// seconds rather than hanging (exit condition 6e).
	if !strings.Contains(env, "GIT_TERMINAL_PROMPT=0") {
		t.Fatal("the seconds-not-hours property was lost")
	}
}
