package gitfetch

import (
	"context"
	"errors"
	"fmt"
	"strings"
)

// The platform's only remote write, and the five constraints that bound it
// (ADR 0031 amendment A2, FR-RUNENV-007).
//
// **They are independent of which credential pushes.** They constrain *what* is pushed,
// so they hold in full on the default path — where the credential is the node's own and
// the platform can neither manage nor revoke it (the 2026-08-13 ruling). "Revocable"
// does not apply there; these five do.
//
// Constraint 3 — never a force push, a remote deletion or a tag — is implemented as
// **those strings are not in the table**, rather than as a check that they are absent.
// A check can be bypassed by a second call site; a table that does not contain the word
// cannot. `GATE-SC-PUSH-ARGV` asserts the absence.

var (
	ErrBranchNotAllowed = errors.New("only a cliora/ branch may be pushed")
	ErrNothingToPush    = errors.New("the branch has no commits to push")
)

// PushOptions is what one push needs. Deliberately not a wire type: the fields it does
// **not** have — force, delete, refspec, remote name — are the design.
type PushOptions struct {
	// Dir is the checkout.
	Dir string
	// Branch must carry the `cliora/` prefix. Central composes the name; this checks it
	// anyway, because a constraint that trusts the frame it was sent is not a constraint.
	Branch string
	// RemoteURL is passed explicitly rather than using `origin`. `.git/config` sits
	// inside a directory the agent may write to — the sandbox git freedom of
	// 2026-08-10 is deliberate — so constraint 4 has to check the address the
	// *platform* knows, not the last one written into the checkout.
	RemoteURL string
	// BaseBranch and TargetBranch are refused explicitly by constraint 2. Constraint 1
	// already implies it, but an implication is not an assertion.
	BaseBranch   string
	TargetBranch string
}

// Push writes one branch to one remote, or refuses.
//
// Every refusal happens **before `git` is executed**. That distinction is the whole
// difference between a constraint and a hope: a rule that only reports the remote's
// rejection is not enforcing anything, it is observing something.
func (f Fetcher) Push(ctx context.Context, opts PushOptions) error {
	// ① only a `cliora/` branch
	if !ValidBranch(opts.Branch) {
		return fmt.Errorf("%w: %q", ErrBranchNotAllowed, opts.Branch)
	}
	// ② never the base or the target branch
	if opts.Branch == opts.BaseBranch || opts.Branch == opts.TargetBranch {
		return fmt.Errorf("%w: %q is the base or target branch", ErrBranchNotAllowed, opts.Branch)
	}
	// ④ only a host on the allowlist — the same check the fetch half uses, so there is
	// one answer to "may this deployment talk to that host" rather than two.
	if err := f.CheckURL(opts.RemoteURL); err != nil {
		return err
	}

	ctx, cancel := context.WithTimeout(ctx, f.timeout())
	defer cancel()

	// ③ The closed table. There is no `--force`, no `--force-with-lease`, no `--delete`,
	// no `--tags`, no `--mirror` and no `--all` — and the refspec is **composed here**
	// rather than accepted, so a caller cannot express `:refs/heads/main` either.
	ref := "refs/heads/" + opts.Branch
	args := []string{"push", "--", opts.RemoteURL, ref + ":" + ref}
	if _, err := f.run(ctx, opts.Dir, args...); err != nil {
		return classify(err)
	}
	return nil
}

// ValidBranch is constraint 1, and it is exported so the caller can refuse early with a
// message of its own rather than discovering it at the push.
//
// The character after the prefix may not be `-`: a closed argv table cannot protect a
// value that *is* a flag, which is the same rule `validRef` carries.
func ValidBranch(branch string) bool {
	rest, ok := strings.CutPrefix(branch, "cliora/")
	if !ok || rest == "" || len(branch) > 255 {
		return false
	}
	for i, r := range rest {
		switch {
		case r >= 'a' && r <= 'z', r >= 'A' && r <= 'Z', r >= '0' && r <= '9':
		case r == '.', r == '_':
		case r == '-' && i > 0:
		default:
			return false
		}
	}
	return true
}

// CreateBranch puts the checkout on the run's own branch.
//
// `checkout -b` rather than `switch -c` for the same reason the rest of this package
// prefers the older spelling: it is the form present in every git a node might have.
func (f Fetcher) CreateBranch(ctx context.Context, dir, branch string) error {
	if !ValidBranch(branch) {
		return fmt.Errorf("%w: %q", ErrBranchNotAllowed, branch)
	}
	_, err := f.run(ctx, dir, "checkout", "-b", branch)
	return err
}

// HasCommitsToPush reports whether this branch has anything the remote does not.
//
// Used to tell "the agent committed nothing" from "the push failed", which lead
// somewhere different: the first is the honesty rule's job (the diff becomes an
// artifact), the second is a warning in the run summary.
func (f Fetcher) HasCommitsToPush(ctx context.Context, dir string) (bool, error) {
	out, err := f.run(ctx, dir, "log", "--oneline", "--branches", "--not", "--remotes")
	if err != nil {
		return false, err
	}
	return strings.TrimSpace(out) != "", nil
}

// SetCommitTrailers installs a `prepare-commit-msg` hook that appends the run's
// identity to each commit message.
//
// **Constraint 5 has two tiers and they are not the same strength**, which is why this
// is documented rather than folded in with the identity:
//
//   - `user.name` / `user.email` are set in the checkout's local config by
//     `SetRunIdentity`, and the platform controls them. *The platform never impersonates
//     a human* is a guarantee.
//   - This hook lives in a directory the agent can write to, so it can be deleted.
//     *Every commit is traceable to a run* is best effort.
//
// Stating both as one guarantee would hide which half is soft.
func (f Fetcher) SetCommitTrailers(ctx context.Context, dir, runID, cardRef string) error {
	hook := "#!/bin/sh\n" +
		"# Appends the run's identity. Best effort: see gitfetch.SetCommitTrailers.\n" +
		"grep -q 'Cliora-Run-Id:' \"$1\" || printf '\\nCliora-Run-Id: %s\\nCliora-Card: %s\\n' " +
		shellQuote(runID) + " " + shellQuote(cardRef) + " >> \"$1\"\n"
	if err := writeHook(dir, "prepare-commit-msg", hook); err != nil {
		return err
	}
	_, err := f.run(ctx, dir, "config", "commit.gpgsign", "false")
	return err
}

// shellQuote is single-quote wrapping, and the only values it ever sees are a UUID and
// a card reference — both of which the platform generates. It exists so that the hook
// stays correct if either vocabulary ever widens, not because either is untrusted today.
func shellQuote(value string) string {
	return "'" + strings.ReplaceAll(value, "'", `'\''`) + "'"
}
