package gitfetch

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
)

// Platform-managed git credentials, and the two ways a value reaches git without ever
// reaching a file (ADR 0031 amendment A3).
//
// **This whole file is off by default.** `CLIORA_GIT_SECRET_DELIVERY_ENABLED` is a
// Central setting, so from here the switch is simply whether the run received a git
// secret at all — which is the right shape: the daemon does not need to know about a
// deployment flag, only about what it was handed.
//
// The two mechanisms exist because git has two transports and they fail differently:
//
//	PAT  GIT_ASKPASS -> a helper that itself contains no secret, reading an env var
//	SSH  ssh-agent + `ssh-add -` on **stdin**, socket inside the run directory at 0700
//
// What is *not* used, in both cases for the same reason — the value would end up
// somewhere it can be read later: a token in the remote URL (`git remote -v`, the
// reflog, error messages), `-c http.extraHeader` (`ps`), or a 0600 key file that is
// deleted afterwards (it is on disk in between, and a failed delete leaves it there).

// askpassScript reads the password from the environment and prints it. **It contains no
// secret**, so it can be read, copied or committed and disclose nothing.
//
// The username branch matters for GitHub: a fine-grained PAT authenticates as
// `x-access-token`, and without an answer git prompts — which `GIT_TERMINAL_PROMPT=0`
// then turns into a failure rather than a hang, but a failure nobody can explain.
const askpassScript = `#!/bin/sh
case "$1" in
  Username*) printf '%s' "${CLIORA_GIT_USERNAME:-x-access-token}" ;;
  *)         printf '%s' "${CLIORA_GIT_PASSWORD}" ;;
esac
`

// WriteAskpass places the helper inside the run's own directory and returns its path.
//
// 0700 rather than 0755: nothing else on the machine has any business running it, and
// the run directory is the daemon's.
func WriteAskpass(dir string) (string, error) {
	path := filepath.Join(dir, "askpass.sh")
	if err := os.WriteFile(path, []byte(askpassScript), 0o700); err != nil {
		return "", fmt.Errorf("could not write the credential helper: %w", err)
	}
	return path, nil
}

// Agent is an `ssh-agent` holding one run's key.
type Agent struct {
	socket string
	cmd    *exec.Cmd
}

// StartAgent runs an agent for this run and loads the key **from stdin**.
//
// `ssh-add -` is the whole point: the private key never exists as a file. Writing a
// 0600 key and deleting it afterwards is the implementation this comment exists to
// prevent — it breaks the never-on-disk rule for the duration, and a failed delete
// leaves the key there permanently.
//
// **The socket is not the key.** It lives inside the run directory, at 0700, and dies
// with the run; anything that can read it could already read the run's memory.
func StartAgent(ctx context.Context, dir, privateKey string) (*Agent, error) {
	if _, err := exec.LookPath("ssh-agent"); err != nil {
		return nil, fmt.Errorf("ssh-agent is not on PATH: %w", err)
	}
	socket := filepath.Join(dir, "ssh-agent.sock")
	// `-D` keeps it in the foreground so its lifetime is this process's child rather
	// than an orphan the cleanup loop has to find later.
	cmd := exec.CommandContext(ctx, "ssh-agent", "-D", "-a", socket)
	if err := cmd.Start(); err != nil {
		return nil, fmt.Errorf("could not start ssh-agent: %w", err)
	}
	agent := &Agent{socket: socket, cmd: cmd}

	// The socket appears asynchronously; bounded rather than waited on forever, because
	// a missing agent has to fail in seconds like every other credential problem here.
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		if _, err := os.Stat(socket); err == nil {
			break
		}
		time.Sleep(20 * time.Millisecond)
	}
	if _, err := os.Stat(socket); err != nil {
		agent.Close()
		return nil, fmt.Errorf("ssh-agent did not create its socket: %w", err)
	}

	add := exec.CommandContext(ctx, "ssh-add", "-")
	add.Env = append(os.Environ(), "SSH_AUTH_SOCK="+socket)
	// The key, and then EOF. It exists as a string in this process and in the agent's
	// memory, and nowhere else.
	add.Stdin = strings.NewReader(ensureTrailingNewline(privateKey))
	var stderr strings.Builder
	add.Stderr = &stderr
	if err := add.Run(); err != nil {
		agent.Close()
		// The key is never echoed, and neither is ssh-add's stderr verbatim: it can
		// quote the input on a malformed key.
		return nil, fmt.Errorf("ssh-add refused the key")
	}
	return agent, nil
}

// SocketPath is where the agent listens. It goes into the **daemon's** git environment
// and never into the child's.
func (a *Agent) SocketPath() string {
	if a == nil {
		return ""
	}
	return a.socket
}

// Close kills the agent and removes its socket.
//
// Called on every path out of a run, including the failed ones. It is not the only
// defence: the run is started with `Setpgid`, so a SIGKILL of the group takes the agent
// with it, and the directory reclamation loop removes whatever is left. Three layers
// because "the daemon exited between these two lines" is a real state.
func (a *Agent) Close() {
	if a == nil {
		return
	}
	if a.cmd != nil && a.cmd.Process != nil {
		_ = a.cmd.Process.Kill()
		_, _ = a.cmd.Process.Wait()
	}
	_ = os.Remove(a.socket)
}

func ensureTrailingNewline(key string) string {
	if strings.HasSuffix(key, "\n") {
		return key
	}
	return key + "\n"
}

// writeHook places a git hook inside a checkout, executable.
//
// It writes into `.git/hooks/`, which is the daemon's own doing rather than a path a
// caller named — the same class of destination as the run directory itself.
func writeHook(dir, name, body string) error {
	hooks := filepath.Join(dir, ".git", "hooks")
	if err := os.MkdirAll(hooks, 0o700); err != nil {
		return fmt.Errorf("could not create the hooks directory: %w", err)
	}
	return os.WriteFile(filepath.Join(hooks, name), []byte(body), 0o700)
}
