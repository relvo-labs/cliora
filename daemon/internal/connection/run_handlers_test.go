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
