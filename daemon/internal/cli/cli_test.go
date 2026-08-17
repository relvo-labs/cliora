package cli

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// The two properties that matter more than any command (D14):
//
//   - `context show` works with no network at all, because an agent that cannot read
//     its brief when Central is down is an agent that stops;
//   - everything else fails with a message whose *second sentence* says the session can
//     keep working — without it, a failed status update reads as "I cannot continue".

func writeContext(t *testing.T, dir, sessionID, apiBase string) {
	t.Helper()
	contextDir := filepath.Join(dir, ".cliora", "context")
	if err := os.MkdirAll(contextDir, 0o700); err != nil {
		t.Fatal(err)
	}
	pack := "# TASK-1 something\n\n`cliora context show` 讀本機檔案，不需要連線。API：" + apiBase + "\n"
	if err := os.WriteFile(filepath.Join(contextDir, sessionID+".md"), []byte(pack), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(contextDir, sessionID+".token"), []byte("cliora_st_abc"), 0o600); err != nil {
		t.Fatal(err)
	}
}

func TestContextShowNeedsNoNetwork(t *testing.T) {
	dir := t.TempDir()
	writeContext(t, dir, "s1", "http://127.0.0.1:1")
	ctx, err := FindContext(dir, "")
	if err != nil {
		t.Fatalf("find: %v", err)
	}
	var out bytes.Buffer
	code, showErr := ShowContext(&out, ctx)
	if showErr != nil || code != ExitOK {
		t.Fatalf("show: code=%d err=%v", code, showErr)
	}
	if !strings.Contains(out.String(), "TASK-1") {
		t.Fatalf("pack not printed: %q", out.String())
	}
}

func TestTheContextIsFoundFromASubdirectory(t *testing.T) {
	// An agent spends most of its time somewhere below the workspace root.
	dir := t.TempDir()
	writeContext(t, dir, "s1", "http://example.invalid")
	deep := filepath.Join(dir, "backend", "app", "services")
	if err := os.MkdirAll(deep, 0o755); err != nil {
		t.Fatal(err)
	}
	ctx, err := FindContext(deep, "")
	if err != nil {
		t.Fatalf("find: %v", err)
	}
	if ctx.SessionID != "s1" {
		t.Fatalf("session = %q", ctx.SessionID)
	}
}

func TestTwoSessionsInOneWorkspaceAreAmbiguousRatherThanGuessed(t *testing.T) {
	// Guessing would silently file one agent's report against another's card.
	dir := t.TempDir()
	writeContext(t, dir, "s1", "http://example.invalid")
	writeContext(t, dir, "s2", "http://example.invalid")
	if _, err := FindContext(dir, ""); err == nil {
		t.Fatal("expected the ambiguity to be refused")
	}
	ctx, err := FindContext(dir, "s2")
	if err != nil {
		t.Fatalf("explicit session: %v", err)
	}
	if ctx.SessionID != "s2" {
		t.Fatalf("session = %q", ctx.SessionID)
	}
}

func TestAnUnreachablePlatformSaysTheSessionCanContinue(t *testing.T) {
	dir := t.TempDir()
	// A port nothing is listening on: the transport failure D14 is about.
	writeContext(t, dir, "s1", "http://127.0.0.1:1")
	ctx, err := FindContext(dir, "")
	if err != nil {
		t.Fatalf("find: %v", err)
	}
	_, code, listErr := NewClient(ctx).ListTasks("")
	if code != ExitUnreachable {
		t.Fatalf("exit code = %d, want %d", code, ExitUnreachable)
	}
	if listErr == nil || listErr.Error() != OfflineMessage {
		t.Fatalf("message = %v", listErr)
	}
	// The second sentence is the load-bearing one.
	if !strings.Contains(OfflineMessage, "Session 可繼續工作") {
		t.Fatal("the offline message lost the sentence that keeps an agent working")
	}
}

func TestAServerErrorIsTreatedAsUnreachable(t *testing.T) {
	// From the agent's side, "up but broken" and "down" are the same situation:
	// nothing was recorded, and the work continues either way.
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusBadGateway)
	}))
	defer server.Close()
	dir := t.TempDir()
	writeContext(t, dir, "s1", server.URL)
	ctx, _ := FindContext(dir, "")
	_, code, err := NewClient(ctx).ListTasks("")
	if code != ExitUnreachable || err.Error() != OfflineMessage {
		t.Fatalf("code=%d err=%v", code, err)
	}
}

func TestARefusalExplainsTheNextStep(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodGet {
			_ = json.NewEncoder(w).Encode([]TaskSummary{
				{ID: "11111111-1111-4111-8111-111111111111", CardRef: "TASK-1", Stage: "backlog", Version: 3},
			})
			return
		}
		w.WriteHeader(http.StatusConflict)
		_, _ = w.Write([]byte(`{"error":{"code":"TASK_DEPENDENCY_UNSATISFIED","message":"x","details":{"blocking_refs":["TASK-3","TASK-7"]}}}`))
	}))
	defer server.Close()
	dir := t.TempDir()
	writeContext(t, dir, "s1", server.URL)
	ctx, _ := FindContext(dir, "")
	_, _, code, err := NewClient(ctx).UpdateTask("TASK-1", "implementing", "")
	if code != ExitRefused {
		t.Fatalf("exit code = %d, want %d", code, ExitRefused)
	}
	// The blocking cards are named: "相依未滿足" is not something an agent can act on.
	if err == nil || !strings.Contains(err.Error(), "TASK-3") || !strings.Contains(err.Error(), "TASK-7") {
		t.Fatalf("message = %v", err)
	}
}

func TestUpdateSendsTheVersionItJustRead(t *testing.T) {
	var seen map[string]any
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodGet {
			_ = json.NewEncoder(w).Encode([]TaskSummary{
				{ID: "11111111-1111-4111-8111-111111111111", CardRef: "TASK-1", Stage: "backlog", Version: 7},
			})
			return
		}
		_ = json.NewDecoder(r.Body).Decode(&seen)
		_ = json.NewEncoder(w).Encode(map[string]any{
			"task":     TaskSummary{CardRef: "TASK-1", Stage: "implementing", Version: 8},
			"warnings": []map[string]any{},
		})
	}))
	defer server.Close()
	dir := t.TempDir()
	writeContext(t, dir, "s1", server.URL)
	ctx, _ := FindContext(dir, "")
	item, _, code, err := NewClient(ctx).UpdateTask("TASK-1", "implementing", "開始")
	if err != nil || code != ExitOK {
		t.Fatalf("update: code=%d err=%v", code, err)
	}
	if item.Stage != "implementing" {
		t.Fatalf("stage = %q", item.Stage)
	}
	if seen["version"] != float64(7) {
		t.Fatalf("version sent = %v, want 7", seen["version"])
	}
	if _, ok := seen["gates"]; ok {
		t.Fatal("the CLI must never send gates: approval is a person's decision")
	}
}

func TestTheCommandTreeHasNoApproveSubcommand(t *testing.T) {
	// The API refuses it either way. A subcommand that exists invites an agent to try
	// and then hands it a 403 to interpret; a tool that cannot express the thing is
	// clearer than one that can and always fails (ADR 0028 sec 3).
	root := NewCommand()
	for _, group := range root.Commands() {
		for _, sub := range group.Commands() {
			if strings.Contains(sub.Name(), "approve") || strings.Contains(sub.Name(), "gate") {
				t.Fatalf("unexpected subcommand: %s %s", group.Name(), sub.Name())
			}
		}
	}
}

// The offline promise, in its run-shaped form. The first line changes because a run is
// not a session; **the second must not**, because it is the part that tells an agent
// its work is still worth doing.
func TestAnUnreachablePlatformTellsARunItsWorkCanContinue(t *testing.T) {
	if !strings.Contains(RunOfflineMessage, "工作可繼續") {
		t.Fatalf("the run's offline message does not say work can continue: %q", RunOfflineMessage)
	}
	if !strings.Contains(RunOfflineMessage, "恢復連線後請重新執行") {
		t.Fatalf("the run's offline message does not say to retry later: %q", RunOfflineMessage)
	}
	// And it does not call a run a Session, which is what the wording change is for.
	if strings.Contains(RunOfflineMessage, "Session") {
		t.Fatalf("the run's offline message calls it a Session: %q", RunOfflineMessage)
	}
}

// The discovery code needed no change for runs, and this is the assertion that keeps
// it that way: `<run>/repo` is the child's cwd, and the context is one level up.
func TestFindContextWalksUpFromARunCheckout(t *testing.T) {
	root := t.TempDir()
	runDir := filepath.Join(root, "9f3c1a20-4e7b-4c11-9a55-0123456789ab")
	contextDir := filepath.Join(runDir, ".cliora", "context")
	repo := filepath.Join(runDir, "repo", "src")
	for _, dir := range []string{contextDir, repo} {
		if err := os.MkdirAll(dir, 0o700); err != nil {
			t.Fatal(err)
		}
	}
	pack := filepath.Join(contextDir, "task.md")
	if err := os.WriteFile(pack, []byte("# TASK-1\nAPI：http://127.0.0.1:8000\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(contextDir, "task.token"),
		[]byte("cliora_rt_example"), 0o600); err != nil {
		t.Fatal(err)
	}

	ctx, err := FindContext(repo, "")
	if err != nil {
		t.Fatalf("a run's checkout could not find its own context: %v", err)
	}
	if ctx.Token != "cliora_rt_example" {
		t.Fatalf("token = %q", ctx.Token)
	}
	// A run directory holds exactly one pack, so the "name one with --session" branch
	// is unreachable there — the ambiguity only ever existed for a shared workspace.
	if ctx.SessionID != "task" {
		t.Fatalf("pack id = %q", ctx.SessionID)
	}
}

// The two messages that had to change wording, because they now cover two kinds of
// subject rather than one.
func TestContextNotFoundMentionsBothKindsOfSubject(t *testing.T) {
	_, err := FindContext(t.TempDir(), "")
	if err == nil {
		t.Fatal("expected a refusal in a directory with no context")
	}
	if !strings.Contains(err.Error(), "Agent Run") {
		t.Fatalf("the message still speaks only of Sessions: %v", err)
	}
}

// --- V2.5: the three writes and the local question check (ADR 0034) ---------

func TestSpecTemplateNeedsNoNetworkAndParses(t *testing.T) {
	// The reason this subcommand exists is a budget: the template is ~2.5 KB and the
	// clarification context pack has 6 KB to spend on the requirement, the current
	// draft and the rules. Fetching it locally is what keeps it out of the frame.
	root := NewCommand()
	var out bytes.Buffer
	root.SetOut(&out)
	root.SetArgs([]string{"spec", "template"})
	if err := root.Execute(); err != nil {
		t.Fatalf("spec template: %v", err)
	}
	var parsed map[string]any
	if err := json.Unmarshal(out.Bytes(), &parsed); err != nil {
		t.Fatalf("template is not valid JSON: %v", err)
	}
	sections, ok := parsed["sections"].(map[string]any)
	if !ok {
		t.Fatal("the template has no sections block")
	}
	// The three that carry weight: a decomposition reads `user_stories`, the `ui` gate
	// reads `screens`, and acceptance criteria come from `verification_plan`.
	for _, key := range []string{"user_stories", "screens", "verification_plan"} {
		if _, present := sections[key]; !present {
			t.Fatalf("the template is missing %q", key)
		}
	}
}

func TestSubmittingASpecSaysTheAgentCannotApproveIt(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_ = json.NewEncoder(w).Encode(map[string]any{"seq": 3})
	}))
	defer server.Close()
	dir := t.TempDir()
	writeContext(t, dir, "s1", server.URL)
	if err := os.WriteFile(filepath.Join(dir, "spec.json"), []byte(`{"objective":"x"}`), 0o600); err != nil {
		t.Fatal(err)
	}
	root := NewCommand()
	var out bytes.Buffer
	root.SetOut(&out)
	root.SetArgs([]string{"spec", "submit", filepath.Join(dir, "spec.json")})
	cwd, _ := os.Getwd()
	_ = os.Chdir(dir)
	defer func() { _ = os.Chdir(cwd) }()
	if err := root.Execute(); err != nil {
		t.Fatalf("spec submit: %v", err)
	}
	// Told up front rather than discovered through a 401: not trying is cheaper than
	// being refused, the same reason `verify report` says what it says.
	if !strings.Contains(out.String(), "你核准不了") {
		t.Fatalf("output does not say approval is out of reach: %q", out.String())
	}
}

func TestSubmittingAProposalPrintsItsSizeBeforeAnybodyOpensTheScreen(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_ = json.NewEncoder(w).Encode(map[string]any{"seq": 1})
	}))
	defer server.Close()
	dir := t.TempDir()
	writeContext(t, dir, "s1", server.URL)
	tree := `{"epics":[{"id":"e1"}],"user_stories":[{"id":"u1"},{"id":"u2"}],` +
		`"tasks":[{"id":"t1"},{"id":"t2"},{"id":"t3"}]}`
	if err := os.WriteFile(filepath.Join(dir, "tree.json"), []byte(tree), 0o600); err != nil {
		t.Fatal(err)
	}
	root := NewCommand()
	var out bytes.Buffer
	root.SetOut(&out)
	root.SetArgs([]string{"proposal", "submit", filepath.Join(dir, "tree.json")})
	cwd, _ := os.Getwd()
	_ = os.Chdir(dir)
	defer func() { _ = os.Chdir(cwd) }()
	if err := root.Execute(); err != nil {
		t.Fatalf("proposal submit: %v", err)
	}
	// The run log is the earliest place a forty-card decomposition is visible.
	if !strings.Contains(out.String(), "1 個 Epic、2 個 User Story、3 張 Task") {
		t.Fatalf("counts missing: %q", out.String())
	}
}

func TestTheLocalQuestionCheckUsesTheSameRuleAsTheServer(t *testing.T) {
	// Two rules that disagree produce "sometimes I can ask and sometimes I cannot",
	// which reads as flakiness rather than as a bug. Same fixture, both directions.
	cases := []struct {
		name     string
		messages []Message
		waiting  bool
	}{
		{"no messages at all", nil, false},
		{
			"an unanswered question",
			[]Message{{Kind: "question", Author: "agent", Body: "CSV or PDF?"}},
			true,
		},
		{
			"a plain reply from a person counts as an answer",
			[]Message{
				{Kind: "question", Author: "agent", Body: "CSV or PDF?"},
				{Kind: "message", Author: "user", Body: "CSV"},
			},
			false,
		},
		{
			"a system notice does not count",
			[]Message{
				{Kind: "question", Author: "agent", Body: "CSV or PDF?"},
				{Kind: "event", Author: "system", Body: "lease renewed"},
			},
			true,
		},
		{
			"an answered question followed by a new one",
			[]Message{
				{Kind: "question", Author: "agent", Body: "first"},
				{Kind: "message", Author: "user", Body: "yes"},
				{Kind: "question", Author: "agent", Body: "second"},
			},
			true,
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
				// A page object rather than a bare array since V2-C1: the thread needs
				// a cursor, and the two consumers of this route both changed with it.
				_ = json.NewEncoder(w).Encode(MessagePage{Items: tc.messages})
			}))
			defer server.Close()
			dir := t.TempDir()
			writeContext(t, dir, "s1", server.URL)
			ctx, _ := FindContext(dir, "")
			_, waiting := NewClient(ctx).PendingQuestion()
			if waiting != tc.waiting {
				t.Fatalf("waiting = %v, want %v", waiting, tc.waiting)
			}
		})
	}
}

func TestAFailedWriteSaysThePayloadSurvived(t *testing.T) {
	// Asserted against the constant rather than by running the command: `exit` calls
	// `os.Exit`, so the failure path is not reachable from a test binary. The offline
	// message is asserted the same way, for the same reason.
	if !strings.Contains(PayloadSurvivedMessage, "沒有遺失") {
		t.Fatalf("the message does not say the file survived: %q", PayloadSurvivedMessage)
	}
	if !strings.Contains(PayloadSurvivedMessage, "同一個檔案") {
		t.Fatalf("the message does not say to reuse the same file: %q", PayloadSurvivedMessage)
	}
}

func TestTheCommandTreeHasNoAcceptOrApplySubcommand(t *testing.T) {
	// V2.5's version of the `approve` restraint. Accepting a proposal and applying a
	// document patch are both a person's decisions; a subcommand that exists invites an
	// attempt whose answer is a 401 to interpret.
	root := NewCommand()
	for _, group := range root.Commands() {
		for _, sub := range group.Commands() {
			for _, banned := range []string{"accept", "apply", "reject"} {
				if strings.Contains(sub.Name(), banned) {
					t.Fatalf("unexpected subcommand: %s %s", group.Name(), sub.Name())
				}
			}
		}
	}
}
