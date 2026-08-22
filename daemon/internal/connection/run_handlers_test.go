package connection

import (
	"context"
	"encoding/json"
	"testing"
	"time"

	"github.com/cliora/cliora/daemon/internal/config"
	"github.com/cliora/cliora/daemon/internal/protocol"
	"github.com/cliora/cliora/daemon/internal/runtime"
	"github.com/google/uuid"
)

// A nil slice marshals to `null`, the contract says `runtimes` is an array, and
// Central's decoder **drops a frame that fails validation without reporting
// anything**. That is the exact failure ADR 0029 D2 warns about, and it is how this
// bug presented: runner mode said "enabled", the node said "registered", and no runner
// row ever appeared.
//
// The empty case is not an edge case here — it is the designed one. A node whose CLIs
// are installed but too old registers **successfully with no runtimes**, because a
// failed registration reads as "the machine is broken".
func TestRunnerRegisterPayloadIsValidWithNoCapableRuntimes(t *testing.T) {
	cfg := &config.Config{}
	cfg.Node.Name = "dev-runner-01"
	cfg.Runner = config.RunnerConfig{Enabled: true, MaxConcurrent: 1, MaxWaiting: 5}
	m := &Manager{cfg: cfg, registry: runtime.NewRegistry(nil)}

	payload := m.runnerRegisterPayload(context.Background())
	encoded, err := json.Marshal(payload)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	var decoded map[string]any
	if err := json.Unmarshal(encoded, &decoded); err != nil {
		t.Fatal(err)
	}
	for _, field := range []string{"runtimes", "labels"} {
		if decoded[field] == nil {
			t.Fatalf("%s marshalled to null; the contract requires an array", field)
		}
	}

	// The whole frame, validated the way the far end validates it.
	frame, err := protocol.BuildControl(
		"runner.register", uuid.New(), protocol.NewID(), payload, timeFixed(),
	)
	if err != nil {
		t.Fatalf("build: %v", err)
	}
	if err := protocol.ValidateControl(frame); err != nil {
		t.Fatalf("a registration with no capable runtimes is not a valid frame: %v", err)
	}
}

func timeFixed() time.Time {
	return time.Date(2026, 8, 11, 10, 0, 0, 0, time.UTC)
}

// The three dispatch declarations reach the wire, and the two booleans default to the
// permissive value when the config file never mentions them.
//
// **`labels` was a hard-coded empty slice until V2.3.** Central's column and the wire
// field both existed, so a reader could reasonably believe tags already worked; nothing
// could put a value in one. Shipping Central's matching without this would have made
// every card that declares a tag permanently unclaimable, and the Agents page would
// have shown every runner with no tags — a symptom that reads as a missing setting
// rather than a missing feature (plan/20/00-…md D13).
func TestRunnerRegisterPayloadCarriesTheNodesDeclarations(t *testing.T) {
	cfg := &config.Config{}
	cfg.Node.Name = "dev-runner-01"
	no := false
	cfg.Runner = config.RunnerConfig{
		Enabled: true, MaxConcurrent: 1, MaxWaiting: 5,
		// Deliberately unsorted, duplicated and padded: the node's config file is
		// hand-written, and "what did this machine report" should not change because
		// somebody reordered two lines.
		Tags:          []string{"node20", " docker ", "docker", ""},
		AcceptSecrets: &no,
	}
	m := &Manager{cfg: cfg, registry: runtime.NewRegistry(nil)}

	payload := m.runnerRegisterPayload(context.Background())

	labels, ok := payload["labels"].([]string)
	if !ok {
		t.Fatalf("labels is %T, want []string", payload["labels"])
	}
	if len(labels) != 2 || labels[0] != "docker" || labels[1] != "node20" {
		t.Fatalf("labels = %v, want [docker node20] sorted and de-duplicated", labels)
	}
	// Absent means true: a config file written before this phase must not silently
	// stop claiming untagged work after an upgrade.
	if payload["run_untagged"] != true {
		t.Fatalf("run_untagged = %v, want true when the key is absent", payload["run_untagged"])
	}
	if payload["accept_secrets"] != false {
		t.Fatalf("accept_secrets = %v, want the node's explicit false", payload["accept_secrets"])
	}

	frame, err := protocol.BuildControl(
		"runner.register", uuid.New(), protocol.NewID(), payload, timeFixed(),
	)
	if err != nil {
		t.Fatalf("build: %v", err)
	}
	if err := protocol.ValidateControl(frame); err != nil {
		t.Fatalf("a registration carrying tags is not a valid frame: %v", err)
	}
}

// A nil `Tags` must not marshal to `null` — the same defect class as `runtimes` above,
// and the commonest configuration there is.
func TestRunnerRegisterLabelsAreNeverNull(t *testing.T) {
	cfg := &config.Config{}
	cfg.Node.Name = "dev-runner-01"
	cfg.Runner = config.RunnerConfig{Enabled: true, MaxConcurrent: 1, MaxWaiting: 5}
	m := &Manager{cfg: cfg, registry: runtime.NewRegistry(nil)}

	encoded, err := json.Marshal(m.runnerRegisterPayload(context.Background()))
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	var decoded map[string]any
	if err := json.Unmarshal(encoded, &decoded); err != nil {
		t.Fatal(err)
	}
	if decoded["labels"] == nil {
		t.Fatal("labels marshalled to null; the contract requires an array")
	}
}

// The same failure as `TestRunnerRegisterPayloadIsValidWithNoCapableRuntimes`, one
// message later and with a worse blast radius: a nil `[]string` marshals to `null`, the
// contract says `git_remotes` is an array, and Central drops a frame that fails
// validation **without reporting anything**.
//
// `Remotes()` returns nil both for a repository with no remotes and for a directory that
// is not a repository — which is every `source: none` card, so every clarification card
// this milestone is about. The run was claimed, started, and then nothing: no completion,
// no error, and a lease quietly expiring three minutes later. Found by the first journey
// that ran an agent to the end (`plan/24/10` §2.2).
func TestRunCompleteIsAValidFrameWithNoGitRemotes(t *testing.T) {
	payload := map[string]any{
		"run_id":           uuid.New().String(),
		"result":           "succeeded",
		"summary":          "已在卡片上留言。",
		"disk_bytes":       4096,
		"git_remotes":      []string(nil), // what Summarise leaves behind off a repo
		"unpushed_commits": 0,
		"untracked_files":  0,
		"pushed_branch":    "", // already handled; asserted here so it stays handled
	}
	omitEmptyOptionals(payload)

	if _, present := payload["git_remotes"]; present {
		t.Fatal("git_remotes survived as null; the whole run.complete would be dropped")
	}
	if _, present := payload["pushed_branch"]; present {
		t.Fatal("an empty pushed_branch survived")
	}

	frame, err := protocol.BuildControl(
		"run.complete", uuid.New(), protocol.NewID(), payload, timeFixed(),
	)
	if err != nil {
		t.Fatalf("build: %v", err)
	}
	// Validated the way the far end validates it — the assertion above only proves the
	// key is gone, not that what is left is acceptable.
	if err := protocol.ValidateControl(frame); err != nil {
		t.Fatalf("a run that pushed nothing cannot report success: %v", err)
	}
}

// The other direction: a run that *did* touch a remote must still carry the evidence.
// A fix that dropped the field unconditionally would pass the test above and delete the
// observability ADR 0031 §5 chose instead of blocking the agent from pushing.
func TestRunCompleteKeepsTheRemotesItHas(t *testing.T) {
	payload := map[string]any{
		"run_id":      uuid.New().String(),
		"result":      "succeeded",
		"git_remotes": []string{"origin\thttps://github.com/example/repo (fetch)"},
	}
	omitEmptyOptionals(payload)

	remotes, ok := payload["git_remotes"].([]string)
	if !ok || len(remotes) != 1 {
		t.Fatalf("git_remotes = %#v; a real remote must survive", payload["git_remotes"])
	}
}
