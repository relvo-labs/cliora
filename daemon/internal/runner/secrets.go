package runner

import (
	"log/slog"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"github.com/cliora/cliora/daemon/internal/protocol"
)

// What a run does with the secrets it was handed (ADR 0032 §2/§4).
//
// Three rules, and each of them is a place the obvious implementation is wrong:
//
//  1. **`kind` decides where the value goes.** `env` reaches the CLI child's
//     environment; `git_pat` and `git_ssh_key` reach **only the daemon's own git
//     environment**. Putting a git credential in the child's environment would hand the
//     agent the platform's revocable credential — and it could push it anywhere, where
//     none of the five hard constraints reach, because those are compiled into the
//     daemon's own push path.
//  2. **Nothing is written to a file.** The one apparent exception is `ssh-agent`'s
//     socket, and a socket is not a key: the key arrives on `ssh-add -`'s stdin and the
//     socket dies with the run.
//  3. **Redaction wraps every outbound frame, not the log.** `run.failed` carries git's
//     stderr and `run.complete` carries free text; the credential-shaped path out of a
//     run is an error message, not a log line.
//
// The struct is a local variable for the length of one run. Nothing here is stored on
// the Runner or the Manager, and `GATE-SC-NO-SECRET-TO-DISK` asserts no field of it
// reaches `os.WriteFile`, `os.Create` or `os.OpenFile`.

// Secrets is one run's delivered values, already sorted into where each one goes.
type Secrets struct {
	// Env is passed to the CLI child.
	Env map[string]string
	// Git is passed to `gitfetch` and nowhere else.
	Git map[string]string
	// All is every value, for the redactor. **Both classes**, because git's error
	// messages are the likeliest place a credential surfaces.
	All []string
}

// dangerousNames would replace part of the execution environment rather than add to
// it. Central refuses them at creation, where the person is standing; this is the last
// line, and it exists for the same reason `gitfetch.validRef` re-checks a ref — this is
// the layer that actually hands the value to execve.
var dangerousNames = map[string]bool{
	"PATH": true, "HOME": true, "USER": true, "SHELL": true, "PWD": true,
	"LD_PRELOAD": true, "LD_LIBRARY_PATH": true, "IFS": true, "TMPDIR": true,
}

// SortSecrets splits a delivered set by kind.
//
// A name this daemon will not accept is skipped with a log line rather than failing the
// run: the value was already refused upstream, so reaching here means an older Central
// or a direct database edit, and failing a whole run for it would be a worse answer than
// running without a value the card may not even use.
func SortSecrets(delivered []protocol.RunSecret) Secrets {
	s := Secrets{Env: map[string]string{}, Git: map[string]string{}}
	for _, item := range delivered {
		if item.Value == "" {
			continue
		}
		if dangerousNames[item.Name] || strings.HasPrefix(item.Name, "CLIORA_") {
			slog.Warn("refusing a secret whose name would replace the environment",
				"name", item.Name)
			continue
		}
		switch item.Kind {
		case "env":
			s.Env[item.Name] = item.Value
		case "git_pat", "git_ssh_key":
			// **Not the child's environment.** See rule 1 above.
			s.Git[item.Kind] = item.Value
		default:
			slog.Warn("ignoring a secret of an unknown kind", "kind", item.Kind)
			continue
		}
		s.All = append(s.All, item.Value)
	}
	return s
}

// ChildEnv is the environment the CLI child is started with: the process environment
// plus the `env` secrets, and **never the git ones**.
func (s Secrets) ChildEnv(base []string) []string {
	if len(s.Env) == 0 {
		return base
	}
	names := make([]string, 0, len(s.Env))
	for name := range s.Env {
		names = append(names, name)
	}
	// Sorted so that "what environment did this run get" is stable across runs; a map's
	// iteration order would make two identical runs differ for no reason.
	sort.Strings(names)
	env := append([]string{}, base...)
	for _, name := range names {
		env = append(env, name+"="+s.Env[name])
	}
	return env
}

// Redactor replaces known secret values wherever they appear on their way out.
//
// **Best effort, and the ADR says so** (ADR 0032 §2 rule 5): values are matched
// literally, so a base64- or URL-encoded one gets through. The second line of defence is
// not a cleverer matcher — it is that secrets are revocable and logs expire.
type Redactor struct {
	values []string
}

// NewRedactor sorts by descending length, and that ordering is load-bearing.
//
// When one secret is a prefix of another, replacing the short one first cuts the long
// one into `***<tail>` — and that tail is still part of a secret. Longest-first makes
// the replacement idempotent in the direction that matters.
//
// **Values shorter than eight characters are skipped**, with a warning. A secret whose
// value is `1` would turn every digit in the log into `***`, which destroys the log and
// protects nothing.
func NewRedactor(values []string) *Redactor {
	kept := make([]string, 0, len(values))
	for _, value := range values {
		if len(value) < 8 {
			slog.Warn("not redacting a very short secret value; it would replace ordinary text",
				"length", len(value))
			continue
		}
		kept = append(kept, value)
	}
	sort.Slice(kept, func(i, j int) bool { return len(kept[i]) > len(kept[j]) })
	return &Redactor{values: kept}
}

// String replaces every known value in one string.
func (r *Redactor) String(text string) string {
	if r == nil || len(r.values) == 0 || text == "" {
		return text
	}
	for _, value := range r.values {
		text = strings.ReplaceAll(text, value, "***")
	}
	return text
}

// Payload walks a frame payload and redacts every string in it, at any depth.
//
// Walking the whole payload rather than three known field names is deliberate: which
// fields carry free text changes as the contract grows, and the cost of missing one is a
// leaked secret. If the measurement (M-SC-2) ever shows this on the terminal's critical
// path, the fallback is named in the plan — but it is a fallback, not the default.
func (r *Redactor) Payload(payload map[string]any) map[string]any {
	if r == nil || len(r.values) == 0 {
		return payload
	}
	for key, value := range payload {
		payload[key] = r.value(value)
	}
	return payload
}

func (r *Redactor) value(node any) any {
	switch typed := node.(type) {
	case string:
		return r.String(typed)
	case []string:
		out := make([]string, len(typed))
		for i, item := range typed {
			out[i] = r.String(item)
		}
		return out
	case []any:
		for i, item := range typed {
			typed[i] = r.value(item)
		}
		return typed
	case map[string]any:
		for key, item := range typed {
			typed[key] = r.value(item)
		}
		return typed
	default:
		return node
	}
}

// IsolateAmbient builds the environment overrides that hide the machine's own git
// credentials from a run (ADR 0031 amendment A3).
//
// **It only applies when this run actually received a platform credential**, and that
// condition is the correction the 2026-08-13 ruling forced. The 2026-08-11 default
// ("replace") was chosen because a revocable credential loses its meaning beside an
// unrevocable one — and *that reasoning holds only when a platform credential exists*.
// Applying it unconditionally would hide the machine's credentials and put nothing in
// their place: on the default deployment every private-repository clone would fail, and
// the symptom would look like a misconfigured credential rather than a policy.
//
// So the trigger is `len(s.Git) > 0`, not the setting alone. The setting decides what to
// do when a credential *was* delivered.
//
// **And this is not a sandbox.** It makes git blind to those credentials. The run's
// child shares an OS user with agentd and can read the home directory; what is bought is
// that the default path does not use them by accident, not that they cannot be used.
func (s Secrets) IsolateAmbient(home string, enabled bool) []string {
	if len(s.Git) == 0 || !enabled || home == "" {
		return nil
	}
	return []string{
		"HOME=" + home,
		"GIT_CONFIG_GLOBAL=" + filepath.Join(home, ".gitconfig"),
		"XDG_CONFIG_HOME=" + filepath.Join(home, ".config"),
	}
}

// PrepareIsolatedHome creates the minimal home an isolated run points at.
//
// An empty `.gitconfig` rather than no file: git falls back to `$HOME/.gitconfig`
// anyway, and an absent one leaves the door open to whatever `XDG_CONFIG_HOME` resolves
// to next.
func PrepareIsolatedHome(root string) (string, error) {
	home := filepath.Join(root, "home")
	if err := os.MkdirAll(filepath.Join(home, ".config"), 0o700); err != nil {
		return "", err
	}
	if err := os.WriteFile(filepath.Join(home, ".gitconfig"), []byte(""), 0o600); err != nil {
		return "", err
	}
	return home, nil
}
