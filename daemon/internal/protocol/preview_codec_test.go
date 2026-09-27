package protocol

import (
	"encoding/base64"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"
)

// --- read-only binary preview, contract 1.11.0 (ADR 0029) ---

const (
	testPreviewID = "01K6B9R3V1EW7Q2M8N4X6Y0Z5T"
	testSessionID = "22222222-2222-4222-8222-222222222222"
)

func previewFrame(msgType, success, payload string) []byte {
	s := ""
	if success != "" {
		s = `"success":` + success + `,`
	}
	return []byte(`{"version":1,"type":"` + msgType + `",` +
		`"request_id":"01K0ABCDEFGHJKMNPQRSTVWXYZ",` +
		`"node_id":"11111111-1111-4111-8111-111111111111",` +
		`"timestamp":"2026-09-27T00:00:00Z",` + s + `"payload":` + payload + `}`)
}

// Only the response that carries bytes gets the 8 MiB ceiling; the requests and
// the small responses keep 64 KiB (plan/31/02 §7).
func TestPreviewFrameBounds(t *testing.T) {
	if !LargeFrameTypes["filesystem.preview_data"] {
		t.Fatal("filesystem.preview_data must be allowed the large frame bound")
	}
	for _, small := range []string{
		"filesystem.preview_open", "filesystem.preview_opened", "filesystem.preview_chunk",
		"filesystem.preview_close", "filesystem.preview_closed",
	} {
		if LargeFrameTypes[small] {
			t.Errorf("%s must keep the 64 KiB bound", small)
		}
	}
	pad := strings.Repeat("a", MaxPayload)
	for _, frame := range [][]byte{
		previewFrame("filesystem.preview_open", "", `{"session_id":"`+testSessionID+`","path":"a.png","pad":"`+pad+`"}`),
		previewFrame("filesystem.preview_chunk", "", `{"session_id":"`+testSessionID+`","preview_id":"`+testPreviewID+`","index":0,"pad":"`+pad+`"}`),
	} {
		if _, err := DecodeControl(frame); err == nil || err.Error() != "FRAME_TOO_LARGE" {
			t.Errorf("oversize preview request: got %v, want FRAME_TOO_LARGE", err)
		}
	}
}

// A full 512 KiB chunk, built the way the daemon builds it, must fit the file
// bound and validate; otherwise BuildResponse would refuse it and every full
// chunk would come back as FRAME_TOO_LARGE.
func TestPreviewChunkFitsFrameBound(t *testing.T) {
	data := base64.StdEncoding.EncodeToString(make([]byte, PreviewChunkSize))
	if len(data) != MaxPreviewDataBase64 {
		t.Fatalf("base64 of one chunk is %d chars, schema maxLength is %d", len(data), MaxPreviewDataBase64)
	}
	frame, err := BuildResponse("filesystem.preview_data", uuid.MustParse("11111111-1111-4111-8111-111111111111"),
		"01K0ABCDEFGHJKMNPQRSTVWXYZ", true,
		map[string]any{"preview_id": testPreviewID, "index": 31, "data": data}, time.Now())
	if err != nil {
		t.Fatalf("BuildResponse: %v", err)
	}
	if len(frame) >= MaxFilePayload || len(frame) <= MaxPayload {
		t.Fatalf("frame is %d bytes; want (%d, %d)", len(frame), MaxPayload, MaxFilePayload)
	}
	if err := ValidateControl(frame); err != nil {
		t.Fatalf("a full chunk frame was rejected: %v", err)
	}
	if MaxPreviewChunks*PreviewChunkSize != 16*1024*1024 {
		t.Fatalf("32 chunks of 512 KiB must cover the 16 MiB PDF cap")
	}
}

func TestValidatePreviewPayloads(t *testing.T) {
	image := `"success":true,"preview_id":"` + testPreviewID + `","path":"a/b.png","kind":"image",` +
		`"mime":"image/png","size":1024,"modified_at":"2026-09-27T00:00:00Z","chunk_size":524288,"chunk_count":1`
	pdf := `"success":true,"preview_id":"` + testPreviewID + `","path":"a/b.pdf","kind":"pdf",` +
		`"mime":"application/pdf","size":1024,"modified_at":"2026-09-27T00:00:00Z","chunk_size":524288,"chunk_count":1`
	cases := []struct {
		name, typ, success, payload string
		accept                      bool
	}{
		{"open", "filesystem.preview_open", "", `{"session_id":"` + testSessionID + `","path":"docs/a.png"}`, true},
		{"open mime", "filesystem.preview_open", "", `{"session_id":"` + testSessionID + `","path":"docs/a.png","mime":"image/png"}`, false},
		{"open raw", "filesystem.preview_open", "", `{"session_id":"` + testSessionID + `","path":"docs/a.png","raw":true}`, false},
		{"open offset", "filesystem.preview_open", "", `{"session_id":"` + testSessionID + `","path":"docs/a.png","offset":0}`, false},
		{"open escape", "filesystem.preview_open", "", `{"session_id":"` + testSessionID + `","path":"../x.png"}`, false},
		{"open absolute", "filesystem.preview_open", "", `{"session_id":"` + testSessionID + `","path":"/etc/x.png"}`, false},

		{"opened image", "filesystem.preview_opened", "true", `{` + image + `,"width":10,"height":20}`, true},
		{"opened image no size", "filesystem.preview_opened", "true", `{` + image + `}`, false},
		{"opened image side too big", "filesystem.preview_opened", "true", `{` + image + `,"width":8193,"height":20}`, false},
		{"opened image pdf mime", "filesystem.preview_opened", "true", `{` + strings.Replace(image, "image/png", "application/pdf", 1) + `,"width":10,"height":20}`, false},
		{"opened svg", "filesystem.preview_opened", "true", `{` + strings.Replace(image, "image/png", "image/svg+xml", 1) + `,"width":10,"height":20}`, false},
		{"opened pdf", "filesystem.preview_opened", "true", `{` + pdf + `}`, true},
		{"opened pdf with width", "filesystem.preview_opened", "true", `{` + pdf + `,"width":10}`, false},
		{"opened pdf image mime", "filesystem.preview_opened", "true", `{` + strings.Replace(pdf, "application/pdf", "image/png", 1) + `}`, false},
		{"opened chunk size", "filesystem.preview_opened", "true", `{` + strings.Replace(pdf, "524288", "1048576", 1) + `}`, false},
		{"opened chunk count", "filesystem.preview_opened", "true", `{` + strings.Replace(pdf, `"chunk_count":1`, `"chunk_count":33`, 1) + `}`, false},
		{"opened too big", "filesystem.preview_opened", "true", `{` + strings.Replace(pdf, `"size":1024`, `"size":16777217`, 1) + `}`, false},
		{"opened local time", "filesystem.preview_opened", "true", `{` + strings.Replace(pdf, "00:00:00Z", "00:00:00+08:00", 1) + `}`, false},
		{"opened extra", "filesystem.preview_opened", "true", `{` + pdf + `,"disposition":"attachment"}`, false},
		{"denied", "filesystem.preview_opened", "false", `{"success":false,"path":"a.png","error":{"code":"FILE_PREVIEW_LIMIT","reason":"pixels"}}`, true},
		{"denied with size", "filesystem.preview_opened", "false", `{"success":false,"path":"a.png","error":{"code":"FILE_TOO_LARGE","reason":"too_large","size":9,"limit":8}}`, true},
		{"denied unknown code", "filesystem.preview_opened", "false", `{"success":false,"path":"a.png","error":{"code":"FILE_BINARY","reason":"binary"}}`, false},
		{"denied path in reason", "filesystem.preview_opened", "false", `{"success":false,"path":"a.png","error":{"code":"FILE_DENIED","reason":"/etc/passwd"}}`, false},
		{"denied with handle", "filesystem.preview_opened", "false", `{"success":false,"path":"a.png","preview_id":"` + testPreviewID + `","error":{"code":"FILE_DENIED","reason":"dotenv"}}`, false},

		{"chunk", "filesystem.preview_chunk", "", `{"session_id":"` + testSessionID + `","preview_id":"` + testPreviewID + `","index":31}`, true},
		{"chunk missing index", "filesystem.preview_chunk", "", `{"session_id":"` + testSessionID + `","preview_id":"` + testPreviewID + `"}`, false},
		{"chunk negative", "filesystem.preview_chunk", "", `{"session_id":"` + testSessionID + `","preview_id":"` + testPreviewID + `","index":-1}`, false},
		{"chunk length", "filesystem.preview_chunk", "", `{"session_id":"` + testSessionID + `","preview_id":"` + testPreviewID + `","index":0,"length":1}`, false},

		{"data", "filesystem.preview_data", "true", `{"preview_id":"` + testPreviewID + `","index":0,"data":"QUJD"}`, true},
		{"data without success", "filesystem.preview_data", "", `{"preview_id":"` + testPreviewID + `","index":0,"data":"QUJD"}`, false},
		{"data empty", "filesystem.preview_data", "true", `{"preview_id":"` + testPreviewID + `","index":0,"data":""}`, false},
		{"data url-safe", "filesystem.preview_data", "true", `{"preview_id":"` + testPreviewID + `","index":0,"data":"a-_="}`, false},

		{"close", "filesystem.preview_close", "", `{"session_id":"` + testSessionID + `","preview_id":"` + testPreviewID + `"}`, true},
		{"close bad id", "filesystem.preview_close", "", `{"session_id":"` + testSessionID + `","preview_id":"x"}`, false},
		{"closed", "filesystem.preview_closed", "true", `{"preview_id":"` + testPreviewID + `"}`, true},
		{"closed extra", "filesystem.preview_closed", "true", `{"preview_id":"` + testPreviewID + `","bytes":1}`, false},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			err := ValidateControl(previewFrame(tc.typ, tc.success, tc.payload))
			if tc.accept && err != nil {
				t.Fatalf("rejected: %v", err)
			}
			if !tc.accept && err == nil {
				t.Fatal("accepted")
			}
		})
	}
}

// binary_preview is const:true. A disabled daemon omits it; false is invalid
// in every consumer (ADR 0029 §9).
func TestRegisterBinaryPreviewIsConstTrue(t *testing.T) {
	raw, err := os.ReadFile(filepath.Join(fixturesDir(t), "valid", "node-register.json"))
	if err != nil {
		t.Fatal(err)
	}
	base := string(raw)
	if err := ValidateControl(raw); err != nil {
		t.Fatalf("absent must be accepted: %v", err)
	}
	for value, accept := range map[string]bool{"true": true, "false": false, `"true"`: false, "1": false, "null": false} {
		frame := strings.Replace(base, `"runtimes"`, `"binary_preview":`+value+`,"runtimes"`, 1)
		err := ValidateControl([]byte(frame))
		if accept && err != nil {
			t.Errorf("binary_preview:%s rejected: %v", value, err)
		}
		if !accept && err == nil {
			t.Errorf("binary_preview:%s accepted", value)
		}
	}
}

// preV111AllowedTypes is the daemon's type vocabulary at contract 1.10.0. It extends the
// frozen 1.9.0 vocabulary with #71 downloads. It is the premise of ADR 0029 §9: an
// older daemon refuses the new types at decode, and the dispatch loop drops a
// frame that fails decode without replying, so Central must never send one.
var preV111AllowedTypes = map[string]bool{"session.start": true, "session.started": true, "session.start_failed": true, "session.attach": true, "session.attached": true, "session.stop": true, "session.stopped": true, "session.list": true, "session.list_result": true, "session.recover": true, "session.status_changed": true, "terminal.resize": true, "terminal.detach": true, "terminal.gap": true, "terminal.exited": true, "terminal.error": true, "terminal.control_acquire": true, "terminal.control_release": true, "filesystem.list": true, "filesystem.entries": true, "filesystem.read": true, "filesystem.content": true, "filesystem.search": true, "filesystem.search_result": true, "filesystem.upload": true, "filesystem.uploaded": true, "filesystem.store": true, "filesystem.stored": true, "filesystem.download": true, "filesystem.downloaded": true, "node.challenge": true, "node.auth": true, "node.authenticated": true, "node.heartbeat": true, "node.register": true, "node.registered": true, "node.system_info": true, "node.runtime_status": true, "node.shutdown": true, "daemon.version": true, "daemon.doctor": true, "daemon.doctor_result": true, "daemon.update": true, "daemon.update_result": true, "tunnel.open": true, "tunnel.opened": true, "tunnel.close": true, "tunnel.closed": true, "tunnel.status": true, "error": true}

func TestAnOlderDaemonRefusesEveryPreviewType(t *testing.T) {
	dir := fixturesDir(t)
	for _, name := range []string{
		"filesystem-preview-open.json", "filesystem-preview-chunk.json", "filesystem-preview-close.json",
	} {
		raw, err := os.ReadFile(filepath.Join(dir, "valid", name))
		if err != nil {
			t.Fatal(err)
		}
		if _, err := decodeControlWith(raw, preV111AllowedTypes); err == nil || err.Error() != "MESSAGE_TYPE_UNSUPPORTED" {
			t.Errorf("%s: a 1.10.0 daemon decoder returned %v, want MESSAGE_TYPE_UNSUPPORTED", name, err)
		}
		if _, err := DecodeControl(raw); err != nil {
			t.Errorf("%s: the current decoder must accept it: %v", name, err)
		}
	}
	// The frozen set really is the old one: it differs from today's by exactly
	// the six preview types.
	added := 0
	for typ := range allowedTypes {
		if !preV111AllowedTypes[typ] {
			if !strings.HasPrefix(typ, "filesystem.preview_") {
				t.Errorf("unexpected new type %s", typ)
			}
			added++
		}
	}
	if added != 6 || len(preV111AllowedTypes)+6 != len(allowedTypes) {
		t.Fatalf("expected exactly six new types, got %d", added)
	}
}
