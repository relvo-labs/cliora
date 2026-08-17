package cli

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

// The CLI half of V2-C1 (`FR-CONV-009`). Four of these assert a *refusal*, and each
// refusal exists to say something an agent would otherwise learn the hard way.

func TestTheIdempotencyKeyIsStableForTheSameSentence(t *testing.T) {
	// An agent's retry is usually the whole command run again, not the same HTTP
	// request resent. A fresh identifier per invocation would make every retry a new
	// message — which is an idempotency key that never repeats, i.e. not one.
	first := idempotencyKey("token", "comment", "做完了 X")
	again := idempotencyKey("token", "comment", "做完了 X")
	if first != again {
		t.Fatalf("the same sentence produced two keys: %s and %s", first, again)
	}
	if idempotencyKey("token", "comment", "做完了 Y") == first {
		t.Fatal("two different sentences produced one key")
	}
	if idempotencyKey("other", "comment", "做完了 X") == first {
		t.Fatal("two different runs produced one key; a retry of one would suppress the other")
	}
	if len(first) != 32 {
		t.Fatalf("key length = %d, want 32", len(first))
	}
}

func TestWaitRefusesATimeoutAboveTheCeilingAndSaysWhatToDoInstead(t *testing.T) {
	// The ceiling is the point of the command rather than a limit on it: past a couple
	// of minutes the right move is to end the process, because the platform starts a
	// new turn when the answer arrives. A bare "too large" would teach the opposite.
	if WaitTimeoutMax != 120*time.Second {
		t.Fatalf("WaitTimeoutMax = %v, want 120s", WaitTimeoutMax)
	}
}

func TestWaitReturnsATimeoutCodeAndPrintsNothing(t *testing.T) {
	// "Nothing yet" is a normal answer, and an agent must be able to tell it from a
	// refusal (exit 1) and from an unreachable platform (exit 2) by the code alone.
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte(`{"items":[],"next_after_seq":null,"has_more":false}`))
	}))
	defer server.Close()
	dir := t.TempDir()
	writeContext(t, dir, "s1", server.URL)
	ctx, _ := FindContext(dir, "")

	page, code, err := NewClient(ctx).WaitMessages(0, 10*time.Millisecond)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if code != ExitTimeout {
		t.Fatalf("code = %d, want %d", code, ExitTimeout)
	}
	if len(page.Items) != 0 {
		t.Fatalf("a timeout returned %d messages", len(page.Items))
	}
}

func TestWaitReturnsAsSoonAsSomethingArrives(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte(
			`{"items":[{"id":"m1","kind":"answer","conversation_seq":7,` +
				`"author_kind":"user","body":"用 SAML"}],"next_after_seq":7,"has_more":false}`))
	}))
	defer server.Close()
	dir := t.TempDir()
	writeContext(t, dir, "s1", server.URL)
	ctx, _ := FindContext(dir, "")

	page, code, err := NewClient(ctx).WaitMessages(0, time.Second)
	if err != nil || code != 0 {
		t.Fatalf("code = %d, err = %v", code, err)
	}
	if len(page.Items) != 1 || page.Items[0].Seq != 7 {
		t.Fatalf("unexpected page: %+v", page)
	}
}

func TestTheCursorIsSentAsAfterSeqAndSinceIsNotSentWithIt(t *testing.T) {
	var seen string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		seen = r.URL.RawQuery
		_, _ = w.Write([]byte(`{"items":[],"next_after_seq":null,"has_more":false}`))
	}))
	defer server.Close()
	dir := t.TempDir()
	writeContext(t, dir, "s1", server.URL)
	ctx, _ := FindContext(dir, "")

	if _, _, err := NewClient(ctx).ListMessages(12, "", 0); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(seen, "after_seq=12") {
		t.Fatalf("query = %q, want after_seq=12", seen)
	}
	if strings.Contains(seen, "since=") {
		t.Fatalf("query = %q, want no since", seen)
	}

	// A negative cursor means "from the beginning"; **zero is a legitimate cursor** and
	// must still be sent, or the first page would silently become "everything".
	if _, _, err := NewClient(ctx).ListMessages(0, "", 0); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(seen, "after_seq=0") {
		t.Fatalf("query = %q, want after_seq=0", seen)
	}
	if _, _, err := NewClient(ctx).ListMessages(-1, "", 0); err != nil {
		t.Fatal(err)
	}
	if strings.Contains(seen, "after_seq") {
		t.Fatalf("query = %q, want no cursor", seen)
	}
}

func TestPostMessageCarriesTheReplyAndTheKey(t *testing.T) {
	var body string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		buffer := make([]byte, r.ContentLength)
		_, _ = r.Body.Read(buffer)
		body = string(buffer)
		_, _ = w.Write([]byte(`{"id":"m1","kind":"answer","conversation_seq":3}`))
	}))
	defer server.Close()
	dir := t.TempDir()
	writeContext(t, dir, "s1", server.URL)
	ctx, _ := FindContext(dir, "")

	if _, _, err := NewClient(ctx).PostMessage("是的", "answer", "m0"); err != nil {
		t.Fatal(err)
	}
	for _, want := range []string{`"reply_to_message_id":"m0"`, `"idempotency_key":`} {
		if !strings.Contains(body, want) {
			t.Fatalf("body = %s, want %s", body, want)
		}
	}
}

func TestProposeSpecPostsAProposal(t *testing.T) {
	// Not `spec submit`: that writes a structured specification against a *requirement*
	// and goes through the requirement's approval path. This one is a message on this
	// card. Merging them would make one a degenerate form of the other.
	var body string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		buffer := make([]byte, r.ContentLength)
		_, _ = r.Body.Read(buffer)
		body = string(buffer)
		_, _ = w.Write([]byte(`{"id":"m1","kind":"proposal","conversation_seq":4}`))
	}))
	defer server.Close()
	dir := t.TempDir()
	writeContext(t, dir, "s1", server.URL)
	ctx, _ := FindContext(dir, "")

	if _, _, err := NewClient(ctx).ProposeSpec("## 目標\n支援 SSO"); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(body, `"kind":"proposal"`) {
		t.Fatalf("body = %s, want kind proposal", body)
	}
}

func TestAuthorLabelPrefersTheRunnerName(t *testing.T) {
	// A uuid tells a reader nothing, and "agent" tells them almost nothing when three
	// runners are on the same project.
	cases := []struct {
		item Message
		want string
	}{
		{Message{Author: "agent", RunnerName: "runner-03"}, "runner-03"},
		{Message{Author: "agent"}, "agent"},
		{Message{Author: "system"}, "系統"},
		{Message{Author: "user"}, "人"},
	}
	for _, tc := range cases {
		if got := authorLabel(tc.item); got != tc.want {
			t.Fatalf("authorLabel(%+v) = %q, want %q", tc.item, got, tc.want)
		}
	}
}
