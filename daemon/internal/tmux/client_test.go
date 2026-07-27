package tmux

import (
	"github.com/google/uuid"
	"testing"
)

func TestNameIsCanonicalAndSafe(t *testing.T) {
	id := uuid.MustParse("A488D16C-838E-4D64-92CB-1638835156B3")
	name, err := Name(id)
	if err != nil || name != "cliora-a488d16c-838e-4d64-92cb-1638835156b3" || !ValidName(name) {
		t.Fatal(name, err)
	}
}
func TestNilNameRejected(t *testing.T) {
	if _, err := Name(uuid.Nil); err == nil {
		t.Fatal("expected rejection")
	}
}
