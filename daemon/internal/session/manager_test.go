package session

import (
	"testing"

	ctmux "github.com/cliora/cliora/daemon/internal/tmux"
	"github.com/google/uuid"
)

func TestStateNamesStable(t *testing.T) {
	if Starting != "starting" || Running != "running" || Stopping != "stopping" || Exited != "exited" || Failed != "failed" {
		t.Fatal("state contract changed")
	}
}

// TestSnapshotLimitIsThePublishedTwoMegabytes pins FR-TERM-004's reattach
// snapshot cap. Raising it silently would push multi-megabyte frames at every
// reconnecting browser; lowering it would quietly shorten the scrollback users
// are promised on reattach.
func TestSnapshotLimitIsThePublishedTwoMegabytes(t *testing.T) {
	if SnapshotLimitBytes != 2*1024*1024 {
		t.Errorf("SnapshotLimitBytes = %d, PRD FR-TERM-004 publishes 2 MB", SnapshotLimitBytes)
	}
}

func TestWorkspacesReturnsUniqueLiveSessionWorkspaces(t *testing.T) {
	m := New(ctmux.Client{}, "", "")
	m.sessions[uuid.New()] = &entry{state: Running, workspace: "/work/a"}
	m.sessions[uuid.New()] = &entry{state: Starting, workspace: "/work/a"}
	m.sessions[uuid.New()] = &entry{state: Running, workspace: "/work/b"}
	m.sessions[uuid.New()] = &entry{state: Exited, workspace: "/work/old"}

	got := m.Workspaces()
	if len(got) != 2 {
		t.Fatalf("workspaces = %v, want two unique live workspaces", got)
	}
	seen := map[string]bool{got[0]: true, got[1]: true}
	if !seen["/work/a"] || !seen["/work/b"] || seen["/work/old"] {
		t.Fatalf("unexpected workspaces: %v", got)
	}
}
