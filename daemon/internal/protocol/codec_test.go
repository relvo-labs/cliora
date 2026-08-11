package protocol

import (
	"bytes"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"testing"

	"github.com/google/uuid"
)

type manifest struct {
	JSON []struct {
		Path   string `json:"path"`
		Accept bool   `json:"accept"`
		Type   string `json:"type"`
	} `json:"json"`
	Binary []struct {
		Name       string `json:"name"`
		Accept     bool   `json:"accept"`
		Version    byte   `json:"version"`
		Kind       byte   `json:"kind"`
		SessionID  string `json:"session_id"`
		PayloadHex string `json:"payload_hex"`
		Hex        string `json:"hex"`
	} `json:"binary"`
}

func fixturesDir(t *testing.T) string {
	t.Helper()
	dir, err := filepath.Abs(filepath.Join("..", "..", "..", "contracts", "v1", "fixtures"))
	if err != nil {
		t.Fatal(err)
	}
	return dir
}

func loadManifest(t *testing.T) (string, manifest) {
	t.Helper()
	dir := fixturesDir(t)
	raw, err := os.ReadFile(filepath.Join(dir, "manifest.json"))
	if err != nil {
		t.Fatal(err)
	}
	var m manifest
	if err := json.Unmarshal(raw, &m); err != nil {
		t.Fatal(err)
	}
	return dir, m
}

func TestContractJSONManifest(t *testing.T) {
	dir, m := loadManifest(t)
	for _, item := range m.JSON {
		raw, err := os.ReadFile(filepath.Join(dir, item.Path))
		if err != nil {
			t.Fatalf("%s: %v", item.Path, err)
		}
		err = ValidateControl(raw)
		if item.Accept {
			if err != nil {
				t.Errorf("%s: expected accept, got %v", item.Path, err)
				continue
			}
			env, _ := DecodeControl(raw)
			if env.Type != item.Type {
				t.Errorf("%s: type %q != %q", item.Path, env.Type, item.Type)
			}
		} else if err == nil {
			t.Errorf("%s: expected reject, got accept", item.Path)
		}
	}
}

func TestContractBinaryManifest(t *testing.T) {
	_, m := loadManifest(t)
	for _, item := range m.Binary {
		if item.Accept {
			id := uuid.MustParse(item.SessionID)
			payload, _ := hex.DecodeString(item.PayloadHex)
			frame, err := EncodeBinary(item.Kind, id, payload)
			if err != nil {
				t.Errorf("%s: encode: %v", item.Name, err)
				continue
			}
			kind, gotID, got, err := DecodeBinary(frame)
			if err != nil || kind != item.Kind || gotID != id || !bytes.Equal(got, payload) {
				t.Errorf("%s: round trip failed: %v", item.Name, err)
			}
		} else {
			frame, _ := hex.DecodeString(item.Hex)
			if _, _, _, err := DecodeBinary(frame); err == nil {
				t.Errorf("%s: expected reject, got accept", item.Name)
			}
		}
	}
}

func TestContractBinaryRoundTrip(t *testing.T) {
	id := uuid.MustParse("00000000-0000-4000-8000-000000000002")
	payload := []byte("\x1b[31m中文")
	frame, err := EncodeBinary(2, id, payload)
	if err != nil {
		t.Fatal(err)
	}
	kind, gotID, got, err := DecodeBinary(frame)
	if err != nil || kind != 2 || gotID != id || !bytes.Equal(got, payload) {
		t.Fatal("round trip failed")
	}
}

func FuzzDecodeBinary(f *testing.F) {
	f.Add([]byte{1, 2})
	f.Fuzz(func(t *testing.T, b []byte) { _, _, _, _ = DecodeBinary(b) })
}

// --- P4 daemon.update (protocol v1.4) ---
//
// The security property of daemon.update is what it cannot express: the daemon
// derives the artifact location and expected digest from its own config plus
// Central's release manifest, never from the frame. If any of these decoded, a
// spoofed control frame could point this node at an attacker-chosen artifact
// (ADR 0017, SEC-002).

func updateFrame(t *testing.T, payload string) []byte {
	t.Helper()
	return []byte(`{"version":1,"type":"daemon.update",` +
		`"request_id":"01K0ABCDEFGHJKMNPQRSTVWXYZ",` +
		`"node_id":"11111111-1111-4111-8111-111111111111",` +
		`"timestamp":"2026-07-25T00:00:00Z","payload":` + payload + `}`)
}

func TestDaemonUpdateRefusesAnyArtifactReference(t *testing.T) {
	for _, extra := range []string{
		`"url":"https://evil.example.com/agentd.tar.gz"`,
		`"download_url":"http://127.0.0.1:8000/x.tar.gz"`,
		`"binary_path":"/tmp/payload"`,
		`"filename":"agentd_1.0.0_linux_amd64.tar.gz"`,
		`"sha256":"0000000000000000000000000000000000000000000000000000000000000000"`,
		`"command":"/bin/sh -c id"`,
		`"argv":["sh","-c","id"]`,
	} {
		raw := updateFrame(t, `{"target_version":"1.0.0",`+extra+`}`)
		if err := ValidateControl(raw); err == nil {
			t.Errorf("accepted a daemon.update carrying %s", extra)
		}
	}
}

func TestDaemonUpdateTargetVersionMustBeSemver(t *testing.T) {
	rejected := []string{"latest", "", "1.0", "../../etc/passwd", "1.0.0/../../x", "v1.0.0", "1.0.0 "}
	for _, v := range rejected {
		if ValidTargetVersion(v) {
			t.Errorf("ValidTargetVersion(%q) = true, want false", v)
		}
	}
	for _, v := range []string{"1.0.0", "0.2.0", "1.10.3", "1.1.0-rc.1", "10.0.0-snapshot.1"} {
		if !ValidTargetVersion(v) {
			t.Errorf("ValidTargetVersion(%q) = false, want true", v)
		}
	}
}

func TestDaemonUpdateResultVocabularyIsClosed(t *testing.T) {
	base := `{"from_version":"0.9.3","to_version":"1.0.0","status":%q,"stage":%q%s}`
	ok := []byte(`{"version":1,"type":"daemon.update_result",` +
		`"request_id":"01K0ABCDEFGHJKMNPQRSTVWXYZ",` +
		`"node_id":"11111111-1111-4111-8111-111111111111",` +
		`"timestamp":"2026-07-25T00:00:00Z","payload":` +
		fmt.Sprintf(base, "rolled_back", "healthcheck", `,"error_code":"UPDATE_HEALTHCHECK_FAILED"`) + `}`)
	if err := ValidateControl(ok); err != nil {
		t.Fatalf("rejected a valid update result: %v", err)
	}
	for _, bad := range []struct{ status, stage, extra string }{
		{"partial", "swap", ""},
		{"failed", "reboot", ""},
		{"failed", "download", `,"error_code":"BOOM"`},
		{"failed", "download", `,"log":"/var/log/agentd/agentd.log"`},
	} {
		raw := []byte(`{"version":1,"type":"daemon.update_result",` +
			`"request_id":"01K0ABCDEFGHJKMNPQRSTVWXYZ",` +
			`"node_id":"11111111-1111-4111-8111-111111111111",` +
			`"timestamp":"2026-07-25T00:00:00Z","payload":` +
			fmt.Sprintf(base, bad.status, bad.stage, bad.extra) + `}`)
		if err := ValidateControl(raw); err == nil {
			t.Errorf("accepted invalid update result %+v", bad)
		}
	}
}

// UpdateStages must stay in lockstep with the schema enum, since internal/update
// reports a stage from it.
func TestUpdateStagesMatchTheAcceptedVocabulary(t *testing.T) {
	if len(UpdateStages) != len(updateStageSet) {
		t.Fatalf("UpdateStages has %d entries, stage set has %d", len(UpdateStages), len(updateStageSet))
	}
	for _, stage := range UpdateStages {
		if !updateStageSet[stage] {
			t.Errorf("UpdateStages contains %q which the validator rejects", stage)
		}
	}
}

// --- general file upload, contract 1.9.0 (ADR 0026) ---

// filesystem.store is the second request type allowed the 8 MiB bound, and the
// bound itself does not move for it: 4 MiB raw is 5.33 MiB of base64, inside the
// ceiling image drop already paid for. The response stays on the tight limit.
func TestStoreFrameBounds(t *testing.T) {
	if !LargeFrameTypes["filesystem.store"] {
		t.Fatal("filesystem.store must be allowed the large frame bound")
	}
	if LargeFrameTypes["filesystem.stored"] {
		t.Fatal("filesystem.stored is a path and two scalars; it must keep the 64 KiB bound")
	}
	if MaxFilePayload != 8*1024*1024 {
		t.Fatalf("MaxFilePayload = %d; ADR 0026 does not move it", MaxFilePayload)
	}
}

func TestValidateStorePayload(t *testing.T) {
	const sid = "6ba7b810-9dad-11d1-80b4-00c04fd430c8"
	cases := []struct {
		name   string
		fields string
		accept bool
	}{
		{"minimal", `"directory":".","filename":"a.txt","data":"QQ=="`, true},
		{"nested directory", `"directory":"datasets/raw","filename":"a.csv","data":"QQ=="`, true},
		// An empty file is a legitimate upload; all three consumers decode "" to
		// zero bytes (plan/15/07-open-measurements.md §4).
		{"empty file", `"directory":".","filename":"__init__.py","data":""`, true},
		{"non-ascii filename", `"directory":".","filename":"測試.csv","data":"QQ=="`, true},

		// The filename is one segment. This is the type's core invariant, and it
		// matters because URL encoding can smuggle a separator into a query
		// parameter (%2F decodes to "/") — so the wire states the rule rather than
		// relying on the order of decode and validate alone.
		{"separator in filename", `"directory":".","filename":"a/b.txt","data":"QQ=="`, false},
		{"traversal filename", `"directory":".","filename":"../x","data":"QQ=="`, false},
		{"dot filename", `"directory":".","filename":".","data":"QQ=="`, false},
		{"empty filename", `"directory":".","filename":"","data":"QQ=="`, false},
		{"control char filename", `"directory":".","filename":"a\nb","data":"QQ=="`, false},

		{"absolute directory", `"directory":"/etc","filename":"a","data":"QQ=="`, false},
		{"parent escape directory", `"directory":"../x","filename":"a","data":"QQ=="`, false},
		{"missing directory", `"filename":"a","data":"QQ=="`, false},

		{"non-canonical base64", `"directory":".","filename":"a","data":"QQ"`, false},
		{"url-safe base64", `"directory":".","filename":"a","data":"a-_="`, false},

		// Nothing here may ask to replace something (ADR 0026 §1.1).
		{"overwrite field", `"directory":".","filename":"a","data":"QQ==","overwrite":true`, false},
		{"mode field", `"directory":".","filename":"a","data":"QQ==","mode":"0755"`, false},
		{"mime field", `"directory":".","filename":"a","data":"QQ==","mime":"text/plain"`, false},
		{"precondition field", `"directory":".","filename":"a","data":"QQ==","precondition":{}`, false},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			frame := []byte(`{"version":1,"type":"filesystem.store",` +
				`"request_id":"01J0000000000000000000000A",` +
				`"node_id":"` + sid + `","timestamp":"2026-08-03T00:00:00Z",` +
				`"payload":{"session_id":"` + sid + `",` + tc.fields + `}}`)
			err := ValidateControl(frame)
			if tc.accept && err != nil {
				t.Fatalf("rejected: %v", err)
			}
			if !tc.accept && err == nil {
				t.Fatal("accepted")
			}
		})
	}
}
