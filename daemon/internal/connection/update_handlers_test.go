package connection

import (
	"context"
	"encoding/json"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/cliora/cliora/daemon/internal/config"
	"github.com/cliora/cliora/daemon/internal/protocol"
	"github.com/cliora/cliora/daemon/internal/update"
)

// managerForUpdate builds the minimum Manager the update handler touches, with an
// injected Updater so nothing systemd- or filesystem-related is required.
func managerForUpdate(t *testing.T, updater *update.Updater) *Manager {
	t.Helper()
	nodeID := uuid.New()
	return &Manager{
		cfg:          &config.Config{Server: ServerURLFixture()},
		creds:        &config.Credentials{NodeID: nodeID},
		version:      "1.0.0",
		now:          func() time.Time { return time.Unix(1700000000, 0).UTC() },
		newUpdaterFn: func() *update.Updater { return updater },
	}
}

// ServerURLFixture keeps the config valid without pointing at anything real.
func ServerURLFixture() config.ServerConfig {
	return config.ServerConfig{URL: "wss://central.example/ws/nodes", AllowInsecure: false}
}

func updateFrame(t *testing.T, nodeID uuid.UUID, payload map[string]any) []byte {
	t.Helper()
	frame, err := protocol.BuildControl("daemon.update", nodeID, protocol.NewID(), payload, time.Now())
	if err != nil {
		t.Fatal(err)
	}
	return frame
}

func captured(sent *[][]byte) func([]byte) error {
	return func(frame []byte) error {
		*sent = append(*sent, frame)
		return nil
	}
}

func decodeResult(t *testing.T, frame []byte) (protocol.Envelope, map[string]any) {
	t.Helper()
	env, err := protocol.DecodeControl(frame)
	if err != nil {
		t.Fatalf("reply is not a valid control frame: %v", err)
	}
	var payload map[string]any
	if err := json.Unmarshal(env.Payload, &payload); err != nil {
		t.Fatal(err)
	}
	return env, payload
}

// refusingUpdater stands in for the real thing on a non-root daemon.
func refusingUpdater() *update.Updater {
	return update.New("1.0.0", update.Options{
		Restarter:  refusingRestarter{},
		BinaryPath: "/usr/local/bin/agentd",
	})
}

type refusingRestarter struct{}

func (refusingRestarter) Available() error              { return update.ErrNoPrivilege }
func (refusingRestarter) Restart(context.Context) error { return nil }

func TestUpdateRequestFromCentralIsAnsweredWithAResultFrame(t *testing.T) {
	// The refusal is the expected outcome on a non-root daemon (SEC-007), and it must
	// still be *reported*: a silently dropped frame leaves Central showing the node as
	// `in_progress` forever, which is how "the button did nothing" happens.
	manager := managerForUpdate(t, refusingUpdater())
	var sent [][]byte
	frame := updateFrame(t, manager.creds.NodeID, map[string]any{"target_version": "1.1.0"})

	manager.handleUpdate(context.Background(), mustEnvelope(t, frame), frame, captured(&sent))

	if len(sent) != 1 {
		t.Fatalf("sent %d frames, want 1", len(sent))
	}
	env, payload := decodeResult(t, sent[0])
	if env.Type != "daemon.update_result" {
		t.Fatalf("replied with %q", env.Type)
	}
	if payload["status"] != update.StatusFailed {
		t.Errorf("status = %v", payload["status"])
	}
	if payload["error_code"] != update.CodeNotAllowed {
		t.Errorf("error_code = %v, want %s", payload["error_code"], update.CodeNotAllowed)
	}
	if payload["from_version"] != "1.0.0" || payload["to_version"] != "1.1.0" {
		t.Errorf("versions = %v → %v", payload["from_version"], payload["to_version"])
	}
}

func TestTheResultFrameSatisfiesTheProtocolContract(t *testing.T) {
	// Central validates the frame before recording it. A payload the codec rejects
	// means the outcome of a real update is lost — the worst possible moment for a
	// schema slip.
	manager := managerForUpdate(t, refusingUpdater())
	var sent [][]byte
	frame := updateFrame(t, manager.creds.NodeID, map[string]any{"target_version": "1.1.0"})

	manager.handleUpdate(context.Background(), mustEnvelope(t, frame), frame, captured(&sent))

	if err := protocol.ValidateControl(sent[0]); err != nil {
		t.Fatalf("the reply does not satisfy the v1 contract: %v", err)
	}
}

func TestASuccessResultOmitsErrorCodeEntirely(t *testing.T) {
	// `error_code: ""` is not in the schema's enum, so a success frame carrying one
	// would be rejected and the success would never be recorded.
	manager := managerForUpdate(t, noOpUpdater())
	var sent [][]byte
	frame := updateFrame(t, manager.creds.NodeID, map[string]any{"target_version": "1.0.0"})

	manager.handleUpdate(context.Background(), mustEnvelope(t, frame), frame, captured(&sent))

	_, payload := decodeResult(t, sent[0])
	if payload["status"] != update.StatusSucceeded {
		t.Fatalf("status = %v", payload["status"])
	}
	if _, present := payload["error_code"]; present {
		t.Error("a successful result carried an error_code key")
	}
	if err := protocol.ValidateControl(sent[0]); err != nil {
		t.Fatalf("the reply does not satisfy the v1 contract: %v", err)
	}
}

// noOpUpdater reports "already on this version", the one success path reachable
// without touching a filesystem or a service.
func noOpUpdater() *update.Updater {
	return update.New("1.0.0", update.Options{
		Restarter:  permissiveRestarter{},
		BinaryPath: "/usr/local/bin/agentd",
		Fetcher:    staticFetcher{},
		// Pinned rather than inherited from runtime.GOARCH, so the test asserts the
		// same thing on an arm64 builder.
		Architecture: "amd64",
	})
}

type permissiveRestarter struct{}

func (permissiveRestarter) Available() error              { return nil }
func (permissiveRestarter) Restart(context.Context) error { return nil }

type staticFetcher struct{}

func (staticFetcher) Fetch(context.Context) (update.Manifest, error) {
	return update.Manifest{
		Latest: "1.0.0",
		Artifacts: []update.Artifact{{
			Version:      "1.0.0",
			Architecture: "amd64",
			Filename:     "agentd_1.0.0_linux_amd64.tar.gz",
			// A well-formed digest and a positive size: an entry missing either is
			// deliberately unusable (see update.Manifest.Find), and this fixture is
			// meant to reach the "already on this version" branch.
			SHA256: strings.Repeat("a", 64),
			Size:   1024,
		}},
	}, nil
}

func mustEnvelope(t *testing.T, frame []byte) protocol.Envelope {
	t.Helper()
	env, err := protocol.DecodeControl(frame)
	if err != nil {
		t.Fatal(err)
	}
	return env
}

func TestAnUpdateFrameCarryingAnArtifactReferenceIsRejected(t *testing.T) {
	// The wire half of SEC-002. `internal/update` refuses the same thing structurally
	// (its Update method takes no path or URL); this is the frame never getting that
	// far in the first place.
	manager := managerForUpdate(t, refusingUpdater())
	for _, extra := range []string{
		`"url":"http://evil/agentd"`,
		`"binary_path":"/tmp/agentd"`,
		`"sha256":"deadbeef"`,
		`"command":"rm -rf /"`,
	} {
		raw := []byte(`{"version":1,"type":"daemon.update","request_id":"01K0ABCDEFGHJKMNPQRSTVWXYZ",` +
			`"node_id":"` + manager.creds.NodeID.String() + `","timestamp":"2026-07-25T00:00:00Z",` +
			`"payload":{"target_version":"1.1.0",` + extra + `}}`)
		var sent [][]byte
		env, err := protocol.DecodeControl(raw)
		if err != nil {
			continue // already unreadable, which is also a rejection
		}
		manager.handleUpdate(context.Background(), env, raw, captured(&sent))
		if len(sent) != 1 {
			t.Fatalf("%s: sent %d frames", extra, len(sent))
		}
		replyEnv, _ := decodeResult(t, sent[0])
		if replyEnv.Type != "error" {
			t.Errorf("%s: replied %q, want an error frame", extra, replyEnv.Type)
		}
	}
}

func TestAnUpdateFrameWithABadVersionIsRejected(t *testing.T) {
	manager := managerForUpdate(t, refusingUpdater())
	for _, version := range []string{"latest", "../../etc", "1.0", "", "v1.0.0"} {
		raw := []byte(`{"version":1,"type":"daemon.update","request_id":"01K0ABCDEFGHJKMNPQRSTVWXYZ",` +
			`"node_id":"` + manager.creds.NodeID.String() + `","timestamp":"2026-07-25T00:00:00Z",` +
			`"payload":{"target_version":"` + version + `"}}`)
		env, err := protocol.DecodeControl(raw)
		if err != nil {
			continue
		}
		var sent [][]byte
		manager.handleUpdate(context.Background(), env, raw, captured(&sent))
		if len(sent) != 1 {
			t.Fatalf("%q: sent %d frames", version, len(sent))
		}
		replyEnv, _ := decodeResult(t, sent[0])
		if replyEnv.Type != "error" {
			t.Errorf("%q: replied %q, want an error frame", version, replyEnv.Type)
		}
	}
}
