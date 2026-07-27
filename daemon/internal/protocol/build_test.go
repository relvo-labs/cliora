package protocol

import (
	"errors"
	"regexp"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"
)

// requestIDPattern mirrors control-envelope.schema.json's request_id constraint.
var requestIDPattern = regexp.MustCompile(`^[0-9A-HJKMNP-TV-Z]{26}$`)

func TestNewIDUniqueAndValid(t *testing.T) {
	const n = 10000
	seen := make(map[string]struct{}, n)
	for i := 0; i < n; i++ {
		id := NewID()
		if len(id) != 26 {
			t.Fatalf("id %q has length %d, want 26", id, len(id))
		}
		if !requestIDPattern.MatchString(id) {
			t.Fatalf("id %q does not match the request_id pattern", id)
		}
		if _, dup := seen[id]; dup {
			t.Fatalf("duplicate id generated: %q", id)
		}
		seen[id] = struct{}{}
	}
}

func TestNewIDTwoEventsDiffer(t *testing.T) {
	a, b := NewID(), NewID()
	if a == b {
		t.Fatalf("two consecutive event ids must differ, both were %q", a)
	}
}

func TestNewIDMonotonic(t *testing.T) {
	// ULIDs are lexicographically sortable; ids minted in sequence must be
	// strictly increasing (timestamp prefix, or monotonic randomness within the
	// same millisecond).
	prev := NewID()
	for i := 0; i < 5000; i++ {
		next := NewID()
		if next <= prev {
			t.Fatalf("id %q is not strictly greater than previous %q", next, prev)
		}
		prev = next
	}
}

// P3: a ≤2 MiB preview legitimately exceeds the 64 KiB control bound, so
// filesystem responses build against MaxFilePayload while every other type keeps
// the tight limit. A frame beyond its bound must fail to build rather than be
// sent and silently dropped by Central (which would surface as a timeout).
func TestBuildResponseFrameBounds(t *testing.T) {
	nodeID := uuid.New()
	now := time.Unix(0, 0).UTC()
	rid := "01K0ABCDEFGHJKMNPQRSTVWXYZ"

	// A 2 MiB preview builds fine as a filesystem.content frame.
	content := strings.Repeat("const answer = 42;\n", (2<<20)/19-16)
	frame, err := BuildResponse("filesystem.content", nodeID, rid, true,
		map[string]any{"success": true, "rel_path": "large.ts", "content": content}, now)
	if err != nil {
		t.Fatalf("2 MiB preview should build: %v", err)
	}
	if len(frame) <= MaxPayload {
		t.Fatalf("expected the frame to exceed the control bound, got %d bytes", len(frame))
	}

	// The same payload as a non-filesystem type is refused at 64 KiB.
	if _, err := BuildResponse("session.started", nodeID, rid, true,
		map[string]any{"pad": content}, now); !errors.Is(err, ErrFrameTooLarge) {
		t.Fatalf("oversize session frame err = %v, want ErrFrameTooLarge", err)
	}

	// And a filesystem frame beyond MaxFilePayload is refused too.
	if _, err := BuildResponse("filesystem.content", nodeID, rid, true,
		map[string]any{"content": strings.Repeat("x", MaxFilePayload+1)}, now); !errors.Is(err, ErrFrameTooLarge) {
		t.Fatalf("over-limit filesystem frame err = %v, want ErrFrameTooLarge", err)
	}
}
