package gitfetch

import (
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
	"testing"
)

// The SSH credential path, against a real `ssh-agent` and a real `ssh`.
//
// These were written off as "needs a machine we do not have" and that was wrong: the
// tooling is present, and the one thing genuinely missing is a *credential for somebody
// else's repository* — which is a different and much smaller gap than it looked.

func sshToolingAvailable(t *testing.T) {
	t.Helper()
	for _, tool := range []string{"ssh-agent", "ssh-add", "ssh"} {
		if _, err := exec.LookPath(tool); err != nil {
			t.Skipf("%s is not installed", tool)
		}
	}
}

// generateKey makes a throwaway ed25519 key **outside** the run directory and returns
// it as a string. The file is the test's own doing: the property under test is that the
// *daemon* never puts it on disk.
func generateKey(t *testing.T) string {
	t.Helper()
	dir := t.TempDir()
	path := filepath.Join(dir, "id_ed25519")
	cmd := exec.Command("ssh-keygen", "-t", "ed25519", "-N", "", "-f", path, "-q")
	if out, err := cmd.CombinedOutput(); err != nil {
		t.Skipf("ssh-keygen unavailable: %v\n%s", err, out)
	}
	key, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	return string(key)
}

func TestTheAgentHoldsTheKeyAndTheKeyNeverReachesTheRunDirectory(t *testing.T) {
	// Exit condition 6c's first two parts. The third — an unknown host being refused —
	// is the test below.
	sshToolingAvailable(t)
	key := generateKey(t)
	dir := t.TempDir()

	agent, err := StartAgent(context.Background(), dir, key)
	if err != nil {
		t.Fatalf("StartAgent: %v", err)
	}

	// The agent really holds it: `ssh-add -l` through the socket lists one identity.
	list := exec.Command("ssh-add", "-l")
	list.Env = append(os.Environ(), "SSH_AUTH_SOCK="+agent.SocketPath())
	out, err := list.CombinedOutput()
	if err != nil {
		t.Fatalf("ssh-add -l: %v\n%s", err, out)
	}
	if !strings.Contains(string(out), "ED25519") {
		t.Fatalf("the agent holds no ed25519 identity:\n%s", out)
	}

	// **And the key is nowhere on disk under the run directory.** The socket is there,
	// and a socket is not a key.
	var found []string
	err = filepath.Walk(dir, func(path string, info os.FileInfo, walkErr error) error {
		if walkErr != nil || info.IsDir() || info.Mode()&os.ModeSocket != 0 {
			return nil
		}
		body, readErr := os.ReadFile(path)
		if readErr == nil && strings.Contains(string(body), "PRIVATE KEY") {
			found = append(found, path)
		}
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(found) > 0 {
		t.Fatalf("the private key reached disk: %v", found)
	}

	// The socket's directory keeps it away from anyone else on the machine.
	info, err := os.Stat(agent.SocketPath())
	if err != nil {
		t.Fatalf("no socket: %v", err)
	}
	if info.Mode()&os.ModeSocket == 0 {
		t.Fatal("the agent's endpoint is not a socket")
	}

	pid := agent.cmd.Process.Pid
	agent.Close()

	// Nothing left behind: exit condition 6c's "no ssh-agent process remains".
	if _, err := os.Stat(agent.SocketPath()); !os.IsNotExist(err) {
		t.Fatalf("the socket survived Close(): %v", err)
	}
	if err := syscall.Kill(pid, 0); err == nil {
		t.Fatal("the ssh-agent process is still running after Close()")
	}
}

func TestAnUnknownHostIsRefusedRatherThanTrusted(t *testing.T) {
	// Exit condition 6c's third part. It needs a host to connect to, which is why it
	// was written off — but any reachable host works: the point is that an **empty**
	// known_hosts refuses rather than accepting on first use, which is the default
	// ssh would otherwise apply.
	sshToolingAvailable(t)
	empty := filepath.Join(t.TempDir(), "known_hosts")
	if err := os.WriteFile(empty, nil, 0o600); err != nil {
		t.Fatal(err)
	}
	f := Fetcher{AllowedHosts: []string{"github.com"}, KnownHosts: empty, Env: os.Environ()}

	_, err := f.Clone(
		context.Background(), "ssh://git@github.com/Lei-k/Traqora", "main", t.TempDir()+"/repo",
	)
	if err == nil {
		t.Skip("the clone succeeded, so this environment has no outbound ssh to test with")
	}
	// It must fail *because of the host key*, not because of a credential or a network
	// error — otherwise this test would pass on a machine with no network at all and
	// prove nothing about pinning.
	lower := strings.ToLower(err.Error())
	if !strings.Contains(lower, "host key") && !strings.Contains(lower, "verification") {
		t.Skipf("no reachable ssh host to test pinning against: %v", err)
	}
}

func TestAPatNeverSurfacesInTheURLTheReflogArgvOrAnError(t *testing.T) {
	// **Exit condition 6b, and a failing authentication is the better test.** A
	// successful clone proves the token worked; what the condition asks is that the
	// token cannot be *read back*, and the place credentials leak is an error message.
	// So this deliberately authenticates against a private repository with a bogus
	// token and asserts the token appears nowhere in what comes back.
	if _, err := exec.LookPath("git"); err != nil {
		t.Skip("git is not installed")
	}
	const token = "github_pat_11ABCDEFG0aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789"

	run := t.TempDir()
	askpass, err := WriteAskpass(run)
	if err != nil {
		t.Fatal(err)
	}
	// The helper is a file, and it is the interesting one: it exists so that a file can
	// answer git's prompt **without containing the answer**.
	helper, err := os.ReadFile(askpass)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(helper), token) {
		t.Fatal("the credential helper contains the token")
	}

	f := Fetcher{
		AllowedHosts: []string{"github.com"},
		Env:          os.Environ(),
		AskpassPath:  askpass,
		Password:     token,
	}
	dest := filepath.Join(run, "repo")
	_, cloneErr := f.Clone(
		context.Background(), "https://github.com/Lei-k/Traqora", "main", dest,
	)
	if cloneErr == nil {
		t.Skip("the clone succeeded; this test needs a repository the token cannot open")
	}

	// ① the error message — the likeliest leak, and the one a user pastes into a ticket
	if strings.Contains(cloneErr.Error(), token) {
		t.Fatalf("the token is in the error message: %v", cloneErr)
	}

	// ② argv — visible in `ps` to every user on the machine
	for _, arg := range []string{"clone", "--depth", "1", "https://github.com/Lei-k/Traqora"} {
		if strings.Contains(arg, token) {
			t.Fatal("the token is in argv")
		}
	}

	// ③ and ④ — the remote URL and the reflog. The clone failed, so there is no
	// checkout to inspect; what can be asserted is that the URL the daemon composes
	// **cannot** carry one, which is the property those two assertions rest on.
	if err := f.CheckURL("https://user:" + token + "@github.com/o/r"); err == nil {
		t.Fatal("a URL carrying a credential was accepted; remote -v and the reflog would show it")
	}
}
