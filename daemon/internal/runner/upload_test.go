package runner

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

// Exit condition 18, on the daemon's side: the diff really is uploaded, with the
// credential and the digest, to the endpoint the agent's own `attach` uses.
//
// The regression this guards is specific and was real: `ShouldAttachDiff` existed and
// **nothing called it**, so the honesty rule was dead code — a card could change files,
// declare no delivery, and lose the work when the directory was reclaimed, with no
// trace anywhere.
func TestAttachDiffPostsTheePatchWithItsDigest(t *testing.T) {
	var gotAuth, gotDigest, gotFilename, gotBody, gotMessage string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/cli/runs/artifacts" {
			t.Errorf("posted to %s", r.URL.Path)
		}
		gotAuth = r.Header.Get("Authorization")
		if err := r.ParseMultipartForm(1 << 20); err != nil {
			t.Fatalf("not multipart: %v", err)
		}
		gotDigest = r.FormValue("sha256")
		gotMessage = r.FormValue("message")
		file, header, err := r.FormFile("file")
		if err != nil {
			t.Fatalf("no file part: %v", err)
		}
		gotFilename = header.Filename
		body, _ := io.ReadAll(file)
		gotBody = string(body)
		w.Header().Set("content-type", "application/json")
		_, _ = w.Write([]byte(`{"id":"7f000000-0000-4000-8000-00000000000a"}`))
	}))
	defer server.Close()

	patch := "--- a/x\n+++ b/x\n@@\n-one\n+two\n"
	uploader := Uploader{APIBase: server.URL, Credential: "cliora_rt_example"}
	id, err := uploader.AttachDiff(context.Background(), "changes-abc.patch", patch, "說明")
	if err != nil {
		t.Fatalf("attach: %v", err)
	}

	if id != "7f000000-0000-4000-8000-00000000000a" {
		t.Fatalf("artifact id = %q", id)
	}
	if gotAuth != "Bearer cliora_rt_example" {
		t.Fatalf("authorization = %q", gotAuth)
	}
	want := sha256.Sum256([]byte(patch))
	if gotDigest != hex.EncodeToString(want[:]) {
		t.Fatal("the digest does not match the body; a truncated upload would not be caught")
	}
	if gotBody != patch || gotFilename != "changes-abc.patch" || gotMessage != "說明" {
		t.Fatalf("body=%q filename=%q message=%q", gotBody, gotFilename, gotMessage)
	}
}

// A quota refusal has to come back as an error the caller can put in the run summary.
// Silence here is the failure this whole path exists to prevent.
func TestAttachDiffSurfacesARefusal(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusRequestEntityTooLarge)
		_, _ = w.Write([]byte(`{"error":{"code":"ARTIFACT_PROJECT_QUOTA"}}`))
	}))
	defer server.Close()

	_, err := Uploader{APIBase: server.URL, Credential: "cliora_rt_x"}.
		AttachDiff(context.Background(), "a.patch", "diff", "")
	if err == nil {
		t.Fatal("a refused upload reported success")
	}
	if !strings.Contains(err.Error(), "ARTIFACT_PROJECT_QUOTA") {
		t.Fatalf("the refusal lost its code: %v", err)
	}
}

// Without a credential there is nothing to attach with, and that must be an error
// rather than a silent skip.
func TestAttachDiffRefusesWithoutACredential(t *testing.T) {
	if _, err := (Uploader{APIBase: "http://x"}).
		AttachDiff(context.Background(), "a.patch", "d", ""); err == nil {
		t.Fatal("attached without a credential")
	}
}

// One URL, derived rather than configured: a second address in the config file is a
// second thing that can point at the wrong Central.
func TestAPIBaseIsDerivedFromTheWebsocketURL(t *testing.T) {
	cases := map[string]string{
		"wss://cliora.example/ws/nodes":  "https://cliora.example",
		"ws://127.0.0.1:8000/ws/nodes":   "http://127.0.0.1:8000",
		"wss://cliora.example/ws/nodes/": "https://cliora.example",
	}
	for input, want := range cases {
		if got := APIBaseFromWebsocketURL(input); got != want {
			t.Fatalf("APIBaseFromWebsocketURL(%q) = %q, want %q", input, got, want)
		}
	}
}

// The rule itself: it applies to both `none` and `artifact`, and only when the tree
// actually changed.
func TestShouldAttachDiff(t *testing.T) {
	dirty := Summary{Dirty: true, Diff: "diff --git a/x b/x"}
	clean := Summary{}
	cases := []struct {
		delivery string
		summary  Summary
		want     bool
	}{
		{"none", dirty, true},
		{"artifact", dirty, true},
		{"none", clean, false},
		// A tree that changed but produced no tracked diff — every change was an
		// untracked file. Those are counted, never packaged: one `node_modules/`
		// would blow the quota.
		{"none", Summary{Dirty: true, UntrackedFiles: 3}, false},
		{"pull_request", dirty, false},
	}
	for _, tc := range cases {
		if got := ShouldAttachDiff(tc.delivery, tc.summary); got != tc.want {
			t.Fatalf("ShouldAttachDiff(%q, dirty=%v) = %v", tc.delivery, tc.summary.Dirty, got)
		}
	}
}

// The summary says the awkward thing out loud when it applies.
func TestSummaryTextNamesTheUndeclaredChange(t *testing.T) {
	text := SummaryText("none", Summary{Dirty: true, UntrackedFiles: 2, UnpushedCommits: 1,
		Remotes: []string{"origin\thttps://example.invalid/a (fetch)"}})
	for _, want := range []string{"宣告不交付", "2 個未追蹤", "未推送"} {
		if !strings.Contains(text, want) {
			t.Fatalf("summary is missing %q: %s", want, text)
		}
	}
}
