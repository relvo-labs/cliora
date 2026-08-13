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
