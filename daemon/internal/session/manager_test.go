package session

import "testing"

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
