package tmux

import (
	"strings"
	"testing"

	"github.com/google/uuid"
)

func TestNameIsCanonicalAndSafe(t *testing.T) {
	id := uuid.MustParse("A488D16C-838E-4D64-92CB-1638835156B3")
	name, err := Name(id)
	if err != nil || name != "cliora-a488d16c-838e-4d64-92cb-1638835156b3" || !ValidName(name) {
		t.Fatal(name, err)
	}
}

// A tmux client with TERM unset (how systemd starts agentd), or set to a
// terminfo entry without a `clear` capability, exits with "open terminal
// failed: terminal does not support clear" instead of attaching.
func TestEnvSuppliesAnAttachableTerm(t *testing.T) {
	for _, unusable := range []string{"", "dumb", "unknown"} {
		t.Setenv("TERM", unusable)
		if got := termValues(Env()); len(got) != 1 || got[0] != DefaultTerm {
			t.Errorf("TERM=%q -> %v, want exactly one %q", unusable, got, DefaultTerm)
		}
	}
}

func TestEnvKeepsAnOperatorSuppliedTerm(t *testing.T) {
	t.Setenv("TERM", "screen-256color")
	if got := termValues(Env()); len(got) != 1 || got[0] != "screen-256color" {
		t.Errorf("TERM -> %v, want exactly one screen-256color", got)
	}
}

// termValues returns every TERM assignment in env, so a test can assert the
// override replaced the old one rather than appending a shadowed duplicate.
func termValues(env []string) []string {
	var out []string
	for _, kv := range env {
		if v, ok := strings.CutPrefix(kv, "TERM="); ok {
			out = append(out, v)
		}
	}
	return out
}

func TestNilNameRejected(t *testing.T) {
	if _, err := Name(uuid.Nil); err == nil {
		t.Fatal("expected rejection")
	}
}
