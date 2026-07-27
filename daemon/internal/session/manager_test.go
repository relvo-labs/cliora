package session

import "testing"

func TestStateNamesStable(t *testing.T) {
	if Starting != "starting" || Running != "running" || Stopping != "stopping" || Exited != "exited" || Failed != "failed" {
		t.Fatal("state contract changed")
	}
}
