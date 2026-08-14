// Package gitfetch is the daemon's read-only half of git (ADR 0031 §5).
//
// **It shells out to the `git` executable and adds no dependency to go.mod.** Three
// reasons, and the second is the one that decided it: a Go git library would be a
// second implementation of git's behaviour, so the daemon's view of the repository
// could differ from the agent's — and the agent, inside the sandbox, uses real `git`.
// The third is that `git --version` answers "is it installed" with the same probe
// shape `RunCapable` already uses, so a machine without it reports no runtimes and
// says why, instead of failing every run.
//
// **argv is a closed table.** Every command below is a fixed slice with values
// substituted only at marked positions, the same discipline `runtime/launch.go`
// applies to a session's argv. Nothing here comes from a request payload, from a
// card's free-text field, or from the agent's output: the repository is *platform
// configuration*, stored as three columns and assembled at the last moment, which is
// the same class of source as `runtime.binary` in the config file.
//
// **Shallow clone, not a bare mirror.** The upstream design said mirror-plus-worktree,
// but that conclusion assumed a large repository. M11 measured it (plan/18/10-…md
// §1.2): over the network the mirror saves about 1.5 seconds per run at this scale,
// and almost all of its per-run cost is a no-op `remote update --prune` — one network
// round trip, largely independent of repository size. A cache that saves 1.5 seconds
// but adds lock contention, corruption handling and a reclamation pass is a poor
// trade. Two things would flip it back: a repository an order of magnitude larger, or
// a run rate high enough for 1.5 seconds to matter.
//
// **The three fail-fast environment variables go on the daemon's own git calls and
// nowhere else.** Their purpose is to stop *this* clone hanging on a password prompt,
// not to constrain the agent: the second ruling of 2026-08-10 made the agent's git
// freedom deliberate, and putting these into the child's environment would break a
// push that is meant to be allowed.
package gitfetch

import (
	"context"
	"errors"
	"fmt"
	"os/exec"
	"strconv"
	"strings"
	"time"
)

// Fetcher runs git for one node, under that node's configuration.
type Fetcher struct {
	// AllowedHosts is the **node's** list. Central has its own, and both must pass:
	// Central is the coarse filter, the node is the final authority — the same split
	// path containment already uses.
	AllowedHosts []string
	KnownHosts   string
	Timeout      time.Duration
	// Env is the base environment for git. Nil means "derive it", which is what
	// production does; tests supply their own.
	Env []string
	// AskpassPath, Username and Password are the PAT path, and all three are empty
	// unless this run actually received a git credential. With them empty this
	// Fetcher's environment is byte-for-byte what V2.2 produced — which is the
	// default deployment, because platform-managed git credentials are off unless
	// `CLIORA_GIT_SECRET_DELIVERY_ENABLED` says otherwise (ADR 0031 amendment A1).
	AskpassPath string
	Username    string
	Password    string
	// AuthSock is the SSH path: an `ssh-agent` socket inside the run directory. It
	// goes here and **never into the child's environment** — see ADR 0032 §4.
	AuthSock string
}

// Errors a caller distinguishes. `RUN_SOURCE_UNAVAILABLE` carries which one it was in
// its details, because supplying a credential, allowing a host and correcting a branch
// are three different actions.
var (
	ErrHostNotAllowed  = errors.New("host is not on this node's allowlist")
	ErrCredentials     = errors.New("no usable credential for that repository")
	ErrRefNotFound     = errors.New("ref does not exist")
	ErrGitUnavailable  = errors.New("git is not installed or not executable")
	ErrInvalidArgument = errors.New("invalid repository argument")
)

// Available reports whether `git` can be run at all. A new node prerequisite for
// runner mode, and `agentd doctor` prints it: a machine without git registers with no
// runtimes rather than failing each run in turn.
func Available(ctx context.Context) (string, error) {
	out, err := exec.CommandContext(ctx, "git", "--version").Output()
	if err != nil {
		return "", ErrGitUnavailable
	}
	return strings.TrimSpace(string(out)), nil
}

// fetchEnv is the closed environment for the daemon's own git calls.
//
// Without these three a missing credential hangs on a prompt until the wall clock —
// six hours — and the user sees "it ran for an hour and then failed". The exit
// condition asks for a failure in **seconds**, and the idle timer cannot help: the
// clone happens before `run.accept`, so there is no event stream yet to measure.
func (f Fetcher) fetchEnv(base []string) []string {
	ssh := "ssh -o BatchMode=yes -o StrictHostKeyChecking=yes"
	if f.KnownHosts != "" {
		ssh += " -o UserKnownHostsFile=" + f.KnownHosts
	}
	if f.AuthSock != "" {
		// The agent is reached through the environment rather than through a config
		// file, so nothing about this run's key survives it.
		ssh = "ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -o IdentitiesOnly=no"
		if f.KnownHosts != "" {
			ssh += " -o UserKnownHostsFile=" + f.KnownHosts
		}
	}
	// **`GIT_ASKPASS` was already occupied, and this is not a choice between the two
	// behaviours.** V2.2 hard-codes `/bin/false` as one of the three variables that
	// make "a missing credential fails in seconds" true — measured at 2.7 s. The
	// helper replaces the value and keeps that property: with no password in the
	// environment it prints an empty string, git's authentication fails, and
	// `GIT_TERMINAL_PROMPT=0` still forbids falling back to a prompt.
	askpass := "/bin/false"
	if f.AskpassPath != "" {
		askpass = f.AskpassPath
	}
	env := append(append([]string{}, base...),
		"GIT_TERMINAL_PROMPT=0",
		"GIT_ASKPASS="+askpass,
		"GIT_SSH_COMMAND="+ssh,
	)
	if f.Password != "" {
		// Read by the helper, which itself contains no secret. Never in the URL
		// (`git remote -v`, the reflog, error messages) and never in argv (`ps`).
		env = append(env, "CLIORA_GIT_PASSWORD="+f.Password)
		username := f.Username
		if username == "" {
			username = "x-access-token"
		}
		env = append(env, "CLIORA_GIT_USERNAME="+username)
	}
	if f.AuthSock != "" {
		env = append(env, "SSH_AUTH_SOCK="+f.AuthSock)
	}
	return env
}

// CheckURL applies the node's half of the host allowlist and the two shape rules.
//
// The userinfo rule is not input hygiene: a credential inside a remote URL surfaces in
// `git remote -v`, in the reflog and in error messages. Central stores the repository
// as three columns so it cannot be expressed there either — this is the same rule at
// the other end of the wire.
func (f Fetcher) CheckURL(url string) error {
	rest, ok := strings.CutPrefix(url, "https://")
	if !ok {
		rest, ok = strings.CutPrefix(url, "ssh://")
		if !ok {
			return fmt.Errorf("%w: scheme must be https or ssh", ErrInvalidArgument)
		}
		// `git@` is the canonical ssh clone form and ssh genuinely needs a user name.
		// It is accepted as a fixed literal rather than as "any userinfo": Central
		// assembles this URL from three stored columns and can only ever emit this
		// one, so the accepted set is exactly the producible set.
		rest = strings.TrimPrefix(rest, "git@")
	}
	host, _, found := strings.Cut(rest, "/")
	if strings.Contains(host, "@") {
		// Anything else in the authority is credentials. A **password** in particular
		// must be unrepresentable: it would surface in `git remote -v`, in the reflog
		// and in error messages (ADR 0031 §5).
		return fmt.Errorf("%w: the URL may not carry credentials", ErrInvalidArgument)
	}
	if !found || host == "" {
		return fmt.Errorf("%w: no repository path", ErrInvalidArgument)
	}
	host, _, _ = strings.Cut(host, ":")
	for _, allowed := range f.AllowedHosts {
		if strings.EqualFold(allowed, host) {
			return nil
		}
	}
	return fmt.Errorf("%w: %s", ErrHostNotAllowed, host)
}

// Clone fetches one ref into `dest`, shallow, and returns the checked-out commit.
//
// `--depth 1` plus `--single-branch`: a run executes one commit of one ref, and the
// history it does not read is history it should not spend a node's disk on. Detached
// HEAD, because this phase creates no branches — "which commit is this run on" then has
// exactly one answer.
//
// **`origin` is left in place.** An earlier design removed it so that a casual push
// would fail; the second ruling of 2026-08-10 withdrew that, because removing the
// remote also breaks fetch and pull *and* the push that is now deliberately allowed.
// What replaced it is observability: `Remotes` and `UnpushedCommits` below.
func (f Fetcher) Clone(ctx context.Context, url, ref, dest string) (string, error) {
	if err := f.CheckURL(url); err != nil {
		return "", err
	}
	if !validRef(ref) {
		return "", fmt.Errorf("%w: ref %q", ErrInvalidArgument, ref)
	}
	ctx, cancel := context.WithTimeout(ctx, f.timeout())
	defer cancel()

	// The closed table. `--` before the URL is required, not decorative: a URL
	// beginning with `-` would otherwise be read as a flag, and a closed argv table
	// cannot protect a value that *is* a flag.
	args := []string{
		"clone", "--depth", "1", "--single-branch",
		"--branch", ref, "--no-tags", "--", url, dest,
	}
	if _, err := f.run(ctx, "", args...); err != nil {
		return "", classify(err)
	}
	head, err := f.run(ctx, dest, "rev-parse", "HEAD")
	if err != nil {
		return "", classify(err)
	}
	return strings.TrimSpace(head), nil
}

// Status returns `git status --porcelain` for the working tree.
//
// Called twice: once after the checkout to record a baseline (normally empty), and
// once at the end, where a non-empty result is what triggers attaching the diff.
func (f Fetcher) Status(ctx context.Context, dir string) (string, error) {
	out, err := f.run(ctx, dir, "status", "--porcelain")
	return out, err
}

// Diff returns `git diff` for tracked modifications.
//
// Tracked only. Untracked files are counted by the caller and deliberately not
// packaged: one `node_modules/` would blow the artifact quota, so the run summary says
// how many were left behind and a person decides (ADR 0031 §7).
func (f Fetcher) Diff(ctx context.Context, dir string) (string, error) {
	return f.run(ctx, dir, "diff")
}

// DiffStat returns `git diff --stat`, the summary the card and the pull request show.
//
// Separate from `Diff` rather than derived from it: the full diff is attached as an
// artifact and can be megabytes, while this is a handful of lines that goes on a page.
// **M6 measured both** and they are not interchangeable — on a dirty 31 300-file
// repository `--stat` costs 260 ms and `status --porcelain` costs 47 ms, so the
// evidence step's timeout has to be sized against this one rather than against
// `status` alone (plan/21/10-…md §1.1).
func (f Fetcher) DiffStat(ctx context.Context, dir string) (string, error) {
	return f.run(ctx, dir, "diff", "--stat")
}

// Remotes returns `git remote -v` with any userinfo masked.
//
// One half of what **replaced blocking the agent from pushing**. Masking is belt and
// braces — the platform never writes a credential into a URL — but the agent may have
// added a remote of its own, and this output goes onto a page people read.
func (f Fetcher) Remotes(ctx context.Context, dir string) ([]string, error) {
	out, err := f.run(ctx, dir, "remote", "-v")
	if err != nil {
		return nil, err
	}
	var lines []string
	for _, line := range strings.Split(strings.TrimSpace(out), "\n") {
		if line != "" {
			lines = append(lines, MaskUserinfo(line))
		}
	}
	return lines, nil
}

// UnpushedCommits counts commits on local branches that no remote has.
//
// The other half. Not perfect detection — an agent can rewrite refs after pushing —
// but it costs nothing, assumes nothing, and turns "did this run touch a remote" from
// a guess into a line on the Run detail page.
func (f Fetcher) UnpushedCommits(ctx context.Context, dir string) (int, error) {
	out, err := f.run(ctx, dir, "log", "--oneline", "--branches", "--not", "--remotes")
	if err != nil {
		return 0, err
	}
	trimmed := strings.TrimSpace(out)
	if trimmed == "" {
		return 0, nil
	}
	return len(strings.Split(trimmed, "\n")), nil
}

// SetRunIdentity writes the run's git identity into the checkout's local config.
//
// `cliora-run` **does not impersonate a person and does not pretend to be the
// platform**: if the agent commits, `git log` should show that the commit came from an
// unattended run. Bot identity and commit trailers in full are V2.3.
func (f Fetcher) SetRunIdentity(ctx context.Context, dir, node string) error {
	if _, err := f.run(ctx, dir, "config", "user.name", "cliora-run"); err != nil {
		return err
	}
	email := "cliora-run@" + sanitiseNode(node)
	_, err := f.run(ctx, dir, "config", "user.email", email)
	return err
}

// MaskUserinfo replaces `scheme://user:secret@host` with `scheme://***@host`.
func MaskUserinfo(line string) string {
	for _, scheme := range []string{"https://", "http://", "ssh://"} {
		idx := strings.Index(line, scheme)
		if idx < 0 {
			continue
		}
		rest := line[idx+len(scheme):]
		at := strings.Index(rest, "@")
		slash := strings.Index(rest, "/")
		if at < 0 || (slash >= 0 && at > slash) {
			continue
		}
		line = line[:idx] + scheme + "***" + rest[at:]
	}
	return line
}

func (f Fetcher) timeout() time.Duration {
	if f.Timeout <= 0 {
		return 15 * time.Minute
	}
	return f.Timeout
}

func (f Fetcher) run(ctx context.Context, dir string, args ...string) (string, error) {
	cmd := exec.CommandContext(ctx, "git", args...)
	cmd.Dir = dir
	cmd.Env = f.fetchEnv(f.Env)
	var stderr strings.Builder
	cmd.Stderr = &stderr
	out, err := cmd.Output()
	if err != nil {
		return "", fmt.Errorf("git %s: %w: %s", args[0], err, strings.TrimSpace(stderr.String()))
	}
	return string(out), nil
}

// classify turns git's stderr into one of the three causes a person acts on
// differently. **The message never echoes the URL**: somebody may have pasted a
// credential into it, and this string reaches an API response.
func classify(err error) error {
	text := strings.ToLower(err.Error())
	switch {
	case strings.Contains(text, "authentication failed"),
		strings.Contains(text, "could not read username"),
		strings.Contains(text, "permission denied"),
		strings.Contains(text, "terminal prompts disabled"):
		return ErrCredentials
	case strings.Contains(text, "remote branch"),
		strings.Contains(text, "not found in upstream"),
		strings.Contains(text, "couldn't find remote ref"):
		return ErrRefNotFound
	default:
		return err
	}
}

// validRef mirrors the contract's pattern. A leading `-` is refused here as well as on
// the wire: defence in depth, and this is the layer that actually hands it to execve.
func validRef(ref string) bool {
	if ref == "" || len(ref) > 255 {
		return false
	}
	for i, r := range ref {
		switch {
		case r >= 'a' && r <= 'z', r >= 'A' && r <= 'Z', r >= '0' && r <= '9':
		case (r == '.' || r == '_' || r == '/' || r == '-') && i > 0:
		default:
			return false
		}
	}
	return true
}

func sanitiseNode(node string) string {
	cleaned := strings.Map(func(r rune) rune {
		switch {
		case r >= 'a' && r <= 'z', r >= '0' && r <= '9', r == '.', r == '-':
			return r
		case r >= 'A' && r <= 'Z':
			return r + 32
		default:
			return '-'
		}
	}, node)
	if cleaned == "" {
		return "node"
	}
	if len(cleaned) > 64 {
		cleaned = cleaned[:64]
	}
	return cleaned
}

// Quota is a byte budget with a name, so the caller can report which one was hit.
type Quota struct {
	Name  string
	Limit int64
}

// Exceeded formats the refusal a run sees when its directory outgrows its allowance.
func (q Quota) Exceeded(used int64) error {
	return fmt.Errorf(
		"%s exceeded: %s bytes used of %s",
		q.Name, strconv.FormatInt(used, 10), strconv.FormatInt(q.Limit, 10),
	)
}
