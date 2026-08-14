package runner

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// The delivery predicate, over every value and both tree states.
//
// **This is the test that would have caught the bug it exists for.** Before V2.4 the
// condition was written twice: `ShouldAttachDiff` covered `none` and `artifact`, and
// the sentence explaining the attachment was produced only for `none` — so an
// `artifact` card's diff arrived on the board with nothing saying why. The value of a
// table here is not that it is green today; it is that it goes red when somebody adds a
// sixth delivery mode and updates one of the two callers.
func TestTheDiffRuleAndItsSentenceNeverDisagree(t *testing.T) {
	for _, delivery := range []string{"none", "artifact", "branch", "pull_request", "existing_pr"} {
		for _, dirty := range []bool{false, true} {
			summary := Summary{Dirty: dirty}
			if dirty {
				summary.Diff = "diff --git a/x b/x\n"
			}
			attaches := ShouldAttachDiff(delivery, summary)
			explains := strings.Contains(SummaryText(delivery, summary), "diff 已附為產物")
			if attaches != explains {
				t.Fatalf("delivery=%s dirty=%v: attaches=%v but explains=%v — a diff on the "+
					"card with nothing saying why is the exact failure honesty rule 1 exists "+
					"to prevent", delivery, dirty, attaches, explains)
			}
		}
	}
}

func TestOnlyTheTwoNoCodeModesDeclareNoCode(t *testing.T) {
	for delivery, want := range map[string]bool{
		"none": true, "artifact": true,
		"branch": false, "pull_request": false, "existing_pr": false,
	} {
		if got := DeclaresNoCode(delivery); got != want {
			t.Fatalf("DeclaresNoCode(%q) = %v, want %v", delivery, got, want)
		}
	}
}

// --- decoding -----------------------------------------------------------------

func TestDecodeChecksReadsOriginAndArgv(t *testing.T) {
	checks := DecodeChecks([]string{
		"p\tunit tests\tpytest\t-q\ttests/",
		"c\te2e: login\tnpm\trun\ttest:e2e",
	})
	if len(checks) != 2 {
		t.Fatalf("got %d checks, want 2", len(checks))
	}
	if checks[0].Origin != "project" || checks[0].Name != "unit tests" {
		t.Fatalf("first check decoded as %+v", checks[0])
	}
	if len(checks[0].Argv) != 3 || checks[0].Argv[0] != "pytest" {
		t.Fatalf("argv decoded as %v", checks[0].Argv)
	}
	if checks[1].Origin != "card" {
		t.Fatalf("second check origin = %q, want card", checks[1].Origin)
	}
}

// A mis-encoded command is dropped, not fatal.
//
// The run has already done its work by the time these decode; refusing to report
// anything because one entry was malformed would throw away the other results. Central
// measures the encoded length when the command is *saved*, which is where a person can
// act on it.
func TestAMalformedCheckIsDroppedRatherThanFatal(t *testing.T) {
	checks := DecodeChecks([]string{
		"p\tgood\techo\thi",
		"x\tunknown origin\techo",
		"p\tno argv",
		"p\t\techo", // empty name
		"",
	})
	if len(checks) != 1 || checks[0].Name != "good" {
		t.Fatalf("expected only the well-formed check, got %+v", checks)
	}
}

// --- execution ----------------------------------------------------------------

func TestExitCodesAreTheRealOnes(t *testing.T) {
	results := RunChecks(context.Background(), DecodeChecks([]string{
		"p\tpasses\tsh\t-c\texit 0",
		"c\tfails\tsh\t-c\texit 3",
	}), VerifyOptions{Dir: t.TempDir()})

	if len(results) != 2 {
		t.Fatalf("got %d results, want 2", len(results))
	}
	if results[0].ExitCode != 0 {
		t.Fatalf("passing check reported %d", results[0].ExitCode)
	}
	// The whole substance of `machine_verified`: 3 is what the command said, not what
	// anything reported about itself.
	if results[1].ExitCode != 3 {
		t.Fatalf("failing check reported %d, want the real 3", results[1].ExitCode)
	}
	if results[1].Origin != "card" {
		t.Fatalf("origin lost in transit: %+v", results[1])
	}
}

// A timeout is `-1` and the group carries on.
//
// Two properties in one test because they are one decision: a command that never
// finished has no exit code, and recording it as 1 would make "the test failed" and
// "the test did not finish" identical in the report — while a stuck lint must not take
// the test results with it.
func TestATimedOutCheckIsMinusOneAndTheOthersStillRun(t *testing.T) {
	results := RunChecks(context.Background(), DecodeChecks([]string{
		"p\tfirst\tsh\t-c\texit 0",
		"p\thangs\tsleep\t5",
		"p\tlast\tsh\t-c\texit 0",
	}), VerifyOptions{Dir: t.TempDir(), CheckTimeout: 200 * time.Millisecond})

	if len(results) != 3 {
		t.Fatalf("got %d results, want 3", len(results))
	}
	if results[1].ExitCode != ExitTimedOut {
		t.Fatalf("timed-out check reported %d, want %d", results[1].ExitCode, ExitTimedOut)
	}
	if results[2].ExitCode != 0 {
		t.Fatalf("a stuck check took the later ones with it: %+v", results[2])
	}
}

// Too little wall clock left: skipped **with an explanation**.
//
// An empty verification section reads as "the project declared no checks", which is a
// different and much more comfortable conclusion than the true one.
func TestTooLittleRemainingClockSkipsLoudly(t *testing.T) {
	results := RunChecks(context.Background(), DecodeChecks([]string{
		"p\twould take a while\tsh\t-c\texit 0",
	}), VerifyOptions{Dir: t.TempDir(), Remaining: 30 * time.Second})

	if len(results) != 1 {
		t.Fatalf("a skipped group still reports: got %d results", len(results))
	}
	if results[0].ExitCode != ExitTimedOut {
		t.Fatalf("skipped check reported %d", results[0].ExitCode)
	}
	if !strings.Contains(results[0].OutputTail, "剩餘的時間不足") {
		t.Fatalf("the skip did not say why: %q", results[0].OutputTail)
	}
}

func TestAMissingBinaryIsAFailedCheckWithAReason(t *testing.T) {
	results := RunChecks(context.Background(), DecodeChecks([]string{
		"p\tmissing\t/nonexistent/cliora-not-a-binary",
	}), VerifyOptions{Dir: t.TempDir()})

	if len(results) != 1 || results[0].ExitCode == 0 {
		t.Fatalf("a missing binary must not look like a pass: %+v", results)
	}
	if results[0].OutputTail == "" {
		t.Fatalf("a project that renamed a script gets no explanation: %+v", results[0])
	}
}

// The commands run **in the run directory**, so a check can see what the agent left.
func TestChecksRunInTheRunDirectory(t *testing.T) {
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "marker"), []byte("x"), 0o644); err != nil {
		t.Fatal(err)
	}
	results := RunChecks(context.Background(), DecodeChecks([]string{
		"p\tsees the tree\tsh\t-c\ttest -f marker",
	}), VerifyOptions{Dir: dir})
	if results[0].ExitCode != 0 {
		t.Fatalf("check could not see the run directory: %+v", results[0])
	}
}

// The child's environment reaches a check, because tests commonly need it to run.
func TestChecksReceiveTheChildEnvironment(t *testing.T) {
	results := RunChecks(context.Background(), DecodeChecks([]string{
		"p\treads env\tsh\t-c\ttest \"$NPM_TOKEN\" = secret-value",
	}), VerifyOptions{Dir: t.TempDir(), Env: []string{"NPM_TOKEN=secret-value", "PATH=" + os.Getenv("PATH")}})
	if results[0].ExitCode != 0 {
		t.Fatalf("the check did not receive the environment: %+v", results[0])
	}
}

// Only the tail is kept, and it is cut on a rune boundary.
func TestOutputKeepsTheTailOnARuneBoundary(t *testing.T) {
	long := strings.Repeat("每", 2000) + "END"
	got := tail(long)
	if len(got) > maxOutputTail {
		t.Fatalf("tail kept %d bytes, want <= %d", len(got), maxOutputTail)
	}
	if !strings.HasSuffix(got, "END") {
		t.Fatalf("the useful end was cut off: %q", got[len(got)-20:])
	}
	// A byte-wise cut would leave a partial rune, which renders as U+FFFD in the
	// middle of somebody's error message (ADR 0015 amendment).
	if strings.ContainsRune(got, '�') {
		t.Fatalf("cut mid-rune: %q", got[:20])
	}
}

// `Features` is a constant describing the binary, not a setting describing the machine.
func TestFeaturesAreWhatThisBinaryCanDo(t *testing.T) {
	if len(Features) == 0 {
		t.Fatal("a daemon that declares nothing is offered nothing feature-gated")
	}
	for _, feature := range Features {
		if feature != "verification" && feature != "evidence" {
			t.Fatalf("%q is not in the contract's enum; a misspelling here is a rejected "+
				"frame rather than a silent 'unsupported'", feature)
		}
	}
}

// A secret in a check's output does not leave the node.
//
// **This test exists because the first implementation failed it.** `RunChecks` returns
// `[]CheckResult`, and `Redactor.Payload` recurses through maps and `[]any` while
// returning everything else untouched — so putting the typed slice into the frame sent
// a command's output verbatim past a redactor that was working perfectly. The promise
// V2.3 bought by wrapping `send` instead of the log sink ("new fields are covered
// without anybody remembering") only holds for shapes the redactor understands.
func TestACheckOutputPassesThroughTheRedactor(t *testing.T) {
	const secret = "npm_supersecretvalue"
	redactor := NewRedactor([]string{secret})

	results := []CheckResult{{
		Name:       "leaks",
		Origin:     "project",
		ExitCode:   1,
		OutputTail: "error: token " + secret + " rejected",
	}}
	payload := redactor.Payload(map[string]any{
		"result":       "succeeded",
		"verification": CheckPayload(results),
	})

	rendered, err := json.Marshal(payload)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(rendered), secret) {
		t.Fatalf("a verification command's output carried a secret off the node: %s", rendered)
	}
	if !strings.Contains(string(rendered), "***") {
		t.Fatalf("the value was neither redacted nor present, which means the walk missed "+
			"the shape entirely: %s", rendered)
	}
}
