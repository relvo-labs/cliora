package runner

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/cliora/cliora/daemon/internal/protocol"
)

// The property this file exists for is the first test: a git credential must never
// reach the CLI child's environment. Everything else here is a supporting rule.

func TestKindDecidesWhereAValueGoes(t *testing.T) {
	// The whole of ADR 0032 §4 as one assertion. Handing the agent the platform's
	// revocable credential would let it push anywhere — and none of the five hard
	// constraints reach that, because they are compiled into the daemon's push path.
	secrets := SortSecrets([]protocol.RunSecret{
		{Name: "NPM_TOKEN", Kind: "env", Value: "npm-secret-value"},
		{Name: "GITHUB_TOKEN", Kind: "git_pat", Value: "github_pat_secret"},
		{Name: "DEPLOY_KEY", Kind: "git_ssh_key", Value: "-----BEGIN OPENSSH PRIVATE KEY-----"},
	})

	if got := secrets.Env["NPM_TOKEN"]; got != "npm-secret-value" {
		t.Fatalf("env secret = %q, want it in the child's environment", got)
	}
	if len(secrets.Env) != 1 {
		t.Fatalf("env has %d entries, want only the env kind", len(secrets.Env))
	}
	if secrets.Git["git_pat"] != "github_pat_secret" ||
		secrets.Git["git_ssh_key"] == "" {
		t.Fatal("the git credentials did not reach the daemon's own git environment")
	}

	child := secrets.ChildEnv([]string{"PATH=/usr/bin"})
	joined := strings.Join(child, "\n")
	if !strings.Contains(joined, "NPM_TOKEN=npm-secret-value") {
		t.Fatal("the env secret is missing from the child's environment")
	}
	for _, forbidden := range []string{"github_pat_secret", "BEGIN OPENSSH"} {
		if strings.Contains(joined, forbidden) {
			t.Fatalf("a git credential reached the child's environment: %q", forbidden)
		}
	}
	// And every value is still redactable, including the ones the child never sees:
	// git's error messages are the likeliest place a credential surfaces.
	if len(secrets.All) != 3 {
		t.Fatalf("All has %d values, want every delivered value for the redactor", len(secrets.All))
	}
}

func TestANameThatWouldReplaceTheEnvironmentIsSkipped(t *testing.T) {
	// Central refuses these at creation, where the person is standing. This is the
	// last line, and it exists for the same reason `validRef` re-checks a ref: this is
	// the layer that actually hands the value to execve.
	secrets := SortSecrets([]protocol.RunSecret{
		{Name: "PATH", Kind: "env", Value: "/attacker/bin"},
		{Name: "LD_PRELOAD", Kind: "env", Value: "/attacker/lib.so"},
		{Name: "CLIORA_TOKEN", Kind: "env", Value: "pretend"},
		{Name: "KEEP_ME", Kind: "env", Value: "ordinary"},
	})
	if len(secrets.Env) != 1 || secrets.Env["KEEP_ME"] != "ordinary" {
		t.Fatalf("env = %v, want only the ordinary name", secrets.Env)
	}
}

func TestRedactorReplacesTheLongestValueFirst(t *testing.T) {
	// When one secret is a prefix of another, replacing the short one first cuts the
	// long one into `***<tail>` — and that tail is still part of a secret.
	r := NewRedactor([]string{"secret-prefix", "secret-prefix-and-more"})
	got := r.String("log: secret-prefix-and-more here")
	if got != "log: *** here" {
		t.Fatalf("redacted = %q, want the longer value replaced whole", got)
	}
}

func TestRedactorLeavesVeryShortValuesAlone(t *testing.T) {
	// A secret whose value is "1" would turn every digit in the log into `***`, which
	// destroys the log and protects nothing.
	r := NewRedactor([]string{"1", "ab"})
	got := r.String("exit code 1 after ab attempts")
	if got != "exit code 1 after ab attempts" {
		t.Fatalf("redacted = %q, want short values left alone", got)
	}
}

func TestRedactorWalksAWholePayload(t *testing.T) {
	// Not just `data`: `run.failed`'s message carries git's stderr and
	// `run.complete`'s summary is free text.
	r := NewRedactor([]string{"github_pat_secret"})
	payload := map[string]any{
		"message":     "fatal: authentication failed for github_pat_secret",
		"summary":     "pushed with github_pat_secret",
		"git_remotes": []string{"origin https://x@host/r (push) github_pat_secret"},
		"nested": map[string]any{
			"deep": []any{"github_pat_secret", 7},
		},
	}
	out := r.Payload(payload)
	rendered := strings.Join([]string{
		out["message"].(string),
		out["summary"].(string),
		strings.Join(out["git_remotes"].([]string), " "),
		out["nested"].(map[string]any)["deep"].([]any)[0].(string),
	}, "\n")
	if strings.Contains(rendered, "github_pat_secret") {
		t.Fatalf("a secret survived redaction:\n%s", rendered)
	}
	if !strings.Contains(rendered, "***") {
		t.Fatal("nothing was redacted at all")
	}
}

func TestIsolationOnlyAppliesWhenAPlatformCredentialArrived(t *testing.T) {
	// **The correction the 2026-08-13 ruling forced.** Applying isolation
	// unconditionally would hide the machine's credentials and supply no replacement:
	// on the default deployment every private-repository clone would fail, and the
	// symptom would look like a misconfigured credential rather than a policy.
	root := t.TempDir()
	home, err := PrepareIsolatedHome(root)
	if err != nil {
		t.Fatal(err)
	}

	withGit := Secrets{Git: map[string]string{"git_pat": "token"}}
	if got := withGit.IsolateAmbient(home, true); len(got) != 3 {
		t.Fatalf("isolation = %v, want HOME/GIT_CONFIG_GLOBAL/XDG_CONFIG_HOME", got)
	}
	// The same setting, no delivered credential: nothing is overridden.
	noGit := Secrets{Git: map[string]string{}}
	if got := noGit.IsolateAmbient(home, true); got != nil {
		t.Fatalf("isolation = %v, want none when no platform credential arrived", got)
	}
	// And the setting still turns it off when one did.
	if got := withGit.IsolateAmbient(home, false); got != nil {
		t.Fatalf("isolation = %v, want none when the node opted out", got)
	}

	if _, err := os.Stat(filepath.Join(home, ".gitconfig")); err != nil {
		t.Fatalf("the isolated home has no .gitconfig: %v", err)
	}
}

func TestNoSecretValueIsWrittenIntoTheRunDirectory(t *testing.T) {
	// The executable form of "nothing is written to a file" (ADR 0032 §2 rule 4). The
	// static form is `GATE-SC-NO-SECRET-TO-DISK`; this one catches a value that
	// arrives on disk by some route the scan does not model.
	root := t.TempDir()
	layout, err := Create(root, "11111111-1111-4111-8111-111111111111")
	if err != nil {
		t.Fatal(err)
	}
	secrets := SortSecrets([]protocol.RunSecret{
		{Name: "NPM_TOKEN", Kind: "env", Value: "npm-secret-value"},
		{Name: "GITHUB_TOKEN", Kind: "git_pat", Value: "github_pat_secret"},
	})
	if err := WriteContext(layout, "# a card\n", "cliora_rt_example"); err != nil {
		t.Fatal(err)
	}
	// The helper is written here too, and it is the interesting case: it exists so
	// that a *file* can answer git's password prompt without containing the password.
	home, err := PrepareIsolatedHome(layout.Cliora)
	if err != nil {
		t.Fatal(err)
	}
	_ = secrets.IsolateAmbient(home, true)

	err = filepath.Walk(layout.Root, func(path string, info os.FileInfo, err error) error {
		if err != nil || info.IsDir() {
			return err
		}
		body, readErr := os.ReadFile(path)
		if readErr != nil {
			return nil
		}
		for _, value := range secrets.All {
			if strings.Contains(string(body), value) {
				t.Fatalf("%s contains a secret value", path)
			}
		}
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
}
