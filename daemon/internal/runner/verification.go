package runner

import (
	"context"
	"errors"
	"os/exec"
	"strings"
	"time"
)

// The platform's own checks, run inside the run directory after the agent exits
// (DV-04, ADR 0033 §3b, FR-VERIFY-001).
//
// This is the phase's new execution capability, and it is narrower than that phrase
// sounds. Four properties bound it, and each of them is a decision:
//
//  1. **No shell.** `exec.CommandContext(argv[0], argv[1:]...)` — never `sh -c`. A shell
//     string is an injection path, and this one would sit on the platform's own storage
//     surface, which makes it worse rather than better. SEC-002's argv clause holds
//     here word for word; only the table changed, from `AllowedRuntimeIDs` to two
//     platform-side stores.
//  2. **The commands are not the caller's.** They arrive already assembled by Central
//     from `projects.verification_commands` and `tasks.verification_commands`. No
//     request payload names a command — declaring one on a card requires
//     `task.approve`, which a run token never holds — so the exit codes mean something
//     the agent did not choose.
//  3. **After the agent, before the summary.** A check that reformats or builds leaves
//     its own marks in `git status`, and that ordering is deliberate: hiding a
//     verification step's side effects would make the evidence disagree with the diff
//     for reasons nobody could see.
//  4. **Bounded twice, and it may decline to start.** Each command has its own timeout
//     and the group has one; and because the group runs inside the run's wall clock,
//     too little remaining clock means the checks are **skipped with an explanation**
//     rather than silently, and rather than being killed halfway by a timer that
//     belongs to something else.
//
// The encoding is `origin\tname\tcmd\targ…` in one string, because `spec` may not gain
// a field: the receiving decoder rejects unknown fields and answers nothing, so a new
// field costs every un-upgraded node its offers (ADR 0029 amendment C). Tab rather
// than JSON because it stays readable in a log at 256 characters, and argv elements
// containing a tab are far rarer than ones containing a space.

const (
	// Per command and for the group. Values live here rather than on the wire: a
	// timeout is what *this machine* is willing to spend, not something the card
	// declares (plan/21/00-…md §0.3).
	DefaultCheckTimeout = 300 * time.Second
	DefaultGroupTimeout = 900 * time.Second

	// Reserved for "timed out and was killed". A command that never finished has no
	// exit code, and recording it as 1 would make "the test failed" and "the test did
	// not finish" identical in the report — two different things to do next.
	ExitTimedOut = -1

	// Only the tail is kept: what is useful about a failed command is at the end.
	maxOutputTail = 2000
)

// Check is one command as it arrived, decoded.
type Check struct {
	Origin string
	Name   string
	Argv   []string
}

// CheckResult is what the platform learns from running one.
type CheckResult struct {
	Name       string `json:"name"`
	Origin     string `json:"origin"`
	ExitCode   int    `json:"exit_code"`
	DurationMS int64  `json:"duration_ms"`
	OutputTail string `json:"output_tail,omitempty"`
}

// CheckPayload converts results into the generic shape the redactor walks.
//
// **This is not ceremony, it is the difference between redacted and not.**
// `Redactor.Payload` recurses through `map[string]any` and `[]any` and returns anything
// else untouched — so a `[]CheckResult` placed straight into the frame would reach
// `default:` and travel verbatim. A verification command's output is one of the likeliest
// places a secret appears (`env`, a failing config dump, a curl trace), and the whole
// value of wrapping `send` rather than the log sink was that new fields are covered
// without anybody remembering to cover them. Handing the redactor a shape it understands
// is how that promise stays true for this one (ADR 0032, plan/21/03-…md §4.2).
func CheckPayload(results []CheckResult) []any {
	out := make([]any, 0, len(results))
	for _, result := range results {
		entry := map[string]any{
			"name":      result.Name,
			"origin":    result.Origin,
			"exit_code": result.ExitCode,
		}
		if result.DurationMS > 0 {
			entry["duration_ms"] = result.DurationMS
		}
		// Omitted when empty: the contract gives it no minimum, but an empty string
		// carries nothing and costs frame budget.
		if result.OutputTail != "" {
			entry["output_tail"] = result.OutputTail
		}
		out = append(out, entry)
	}
	return out
}

var errMalformedCheck = errors.New("malformed verification command")

// Features is what this binary can do that an older one cannot, reported verbatim on
// `runner.register`. A constant rather than a setting: it describes the code, not the
// operator's wishes (ADR 0029 amendment C).
var Features = []string{"verification", "evidence"}

// originNames maps the single wire character to the value the report stores. A
// character rather than the word because the whole encoded command has 256 bytes to
// live in, and the report is where the readable form belongs.
var originNames = map[string]string{"p": "project", "c": "card"}

// DecodeChecks turns `spec.allowed_verification_commands` into commands to run.
//
// A malformed entry is **dropped rather than failing the run**: the run has already
// done its work by the time this is called, and refusing to report anything because
// one command was mis-encoded would throw away the results of the others. The drop is
// visible — the check simply does not appear in the report — and Central measures the
// encoded length when the command is *saved*, which is where a person can act on it.
func DecodeChecks(raw []string) []Check {
	checks := make([]Check, 0, len(raw))
	for _, entry := range raw {
		check, err := decodeCheck(entry)
		if err != nil {
			continue
		}
		checks = append(checks, check)
	}
	return checks
}

func decodeCheck(entry string) (Check, error) {
	parts := strings.Split(entry, "\t")
	if len(parts) < 3 {
		return Check{}, errMalformedCheck
	}
	origin, ok := originNames[parts[0]]
	if !ok {
		return Check{}, errMalformedCheck
	}
	name := strings.TrimSpace(parts[1])
	argv := parts[2:]
	if name == "" || argv[0] == "" {
		return Check{}, errMalformedCheck
	}
	return Check{Origin: origin, Name: name, Argv: argv}, nil
}

// VerifyOptions is what one group of checks needs.
type VerifyOptions struct {
	// Dir is the checkout, or the run's own directory when the card fetched nothing.
	Dir string
	// Env is the same environment the CLI child received, including the card's `env`
	// secrets — tests commonly need them to run at all. The git kinds are **not** in
	// it: `ChildEnv` already withholds them, and a verification command is a child
	// process like any other (ADR 0032 §4).
	Env []string
	// Remaining is how much of the run's wall clock is left. The group does not extend
	// it: a run that spent five and a half hours agent-side does not get another
	// fifteen minutes because it also declared checks.
	Remaining time.Duration

	CheckTimeout time.Duration
	GroupTimeout time.Duration
}

// RunChecks executes the group and reports what happened to every one of them.
//
// Never returns an error. A verification step that failed to run is a *result* — the
// report has a place to say `-1` — whereas an error here would have to either fail the
// run or be swallowed, and both lose the fact.
func RunChecks(ctx context.Context, checks []Check, opts VerifyOptions) []CheckResult {
	if len(checks) == 0 {
		return nil
	}
	checkTimeout := opts.CheckTimeout
	if checkTimeout <= 0 {
		checkTimeout = DefaultCheckTimeout
	}
	groupTimeout := opts.GroupTimeout
	if groupTimeout <= 0 {
		groupTimeout = DefaultGroupTimeout
	}

	// Not enough clock left to be worth starting. Reported rather than skipped in
	// silence: an empty verification section reads as "the project declared none",
	// which is a different and much more comfortable conclusion than the true one.
	if opts.Remaining > 0 && opts.Remaining < groupTimeout {
		results := make([]CheckResult, 0, len(checks))
		for _, check := range checks {
			results = append(results, CheckResult{
				Name:     check.Name,
				Origin:   check.Origin,
				ExitCode: ExitTimedOut,
				OutputTail: "未執行：這次執行剩餘的時間不足以跑完驗證（需要 " +
					groupTimeout.String() + "）。",
			})
		}
		return results
	}

	groupCtx, cancelGroup := context.WithTimeout(ctx, groupTimeout)
	defer cancelGroup()

	results := make([]CheckResult, 0, len(checks))
	for _, check := range checks {
		results = append(results, runOne(groupCtx, check, opts, checkTimeout))
	}
	return results
}

func runOne(ctx context.Context, check Check, opts VerifyOptions, timeout time.Duration) CheckResult {
	started := time.Now()
	result := CheckResult{Name: check.Name, Origin: check.Origin}

	// The group's own deadline may already have passed. A command that never got to
	// start is `-1` like one that was killed — in both cases there is no exit code,
	// and the distinction between them is in `output_tail` rather than in a second
	// sentinel nobody would remember the meaning of.
	if ctx.Err() != nil {
		result.ExitCode = ExitTimedOut
		result.OutputTail = "未執行：整組驗證已逾時。"
		return result
	}

	cmdCtx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()

	// **No shell.** The argv table changed; the rule did not.
	cmd := exec.CommandContext(cmdCtx, check.Argv[0], check.Argv[1:]...)
	cmd.Dir = opts.Dir
	cmd.Env = opts.Env
	output, err := cmd.CombinedOutput()
	result.DurationMS = time.Since(started).Milliseconds()
	result.OutputTail = tail(string(output))

	switch {
	case cmdCtx.Err() != nil:
		result.ExitCode = ExitTimedOut
		if result.OutputTail == "" {
			result.OutputTail = "逾時：" + timeout.String() + " 內未結束。"
		}
	case err == nil:
		result.ExitCode = 0
	default:
		var exitErr *exec.ExitError
		if errors.As(err, &exitErr) {
			result.ExitCode = exitErr.ExitCode()
		} else {
			// The binary is missing, or is not executable. A real outcome for a
			// project that renamed a script, and one a person can act on — so it is a
			// failed check with the reason rather than a dropped one.
			result.ExitCode = ExitTimedOut
			result.OutputTail = tail("無法執行：" + err.Error() + "\n" + result.OutputTail)
		}
	}
	return result
}

// tail keeps the last maxOutputTail bytes, cut on a rune boundary.
//
// The cut is on runes for the same reason ADR 0015's amendment gives for classifying
// text over whole buffers: slicing UTF-8 at an arbitrary byte produces a replacement
// character in the middle of somebody's error message.
func tail(text string) string {
	trimmed := strings.TrimRight(text, "\n")
	if len(trimmed) <= maxOutputTail {
		return trimmed
	}
	cut := trimmed[len(trimmed)-maxOutputTail:]
	for i := range len(cut) {
		if isRuneStart(cut[i]) {
			return cut[i:]
		}
	}
	return cut
}

func isRuneStart(b byte) bool { return b&0xC0 != 0x80 }
