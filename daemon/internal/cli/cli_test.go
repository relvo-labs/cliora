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
