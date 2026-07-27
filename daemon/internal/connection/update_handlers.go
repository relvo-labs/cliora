package connection

import (
	"context"
	"encoding/json"
	"log/slog"
	"os"
	"path/filepath"
	"runtime"

	"github.com/cliora/cliora/daemon/internal/protocol"
	"github.com/cliora/cliora/daemon/internal/update"
)

type updateFields struct {
	TargetVersion  string `json:"target_version"`
	AllowDowngrade bool   `json:"allow_downgrade"`
}

// handleUpdate answers a `daemon.update` control frame (P4-10).
//
// Under the MVP privilege model this almost always answers UPDATE_NOT_ALLOWED, and
// that is the design rather than a gap (ADR 0017, SEC-007). The long-running daemon
// is non-root, so it cannot replace `/usr/local/bin/agentd` or restart its own unit,
// and it is deliberately not given a way to acquire that ability: a remote frame
// must not be able to make a node's daemon operate as root.
//
// There is a second reason the daemon must not be the one restarting: `systemctl
// restart agentd` would kill this very process, so it could neither health check the
// new binary nor roll back if it failed. An update needs a supervisor that outlives
// the restart, which is exactly what `sudo agentd update` gives.
//
// The frame is still handled — rather than ignored — because a refusal that names
// the reason is what turns "the button did nothing" into "run this command on the
// box". The reply is a well-formed `daemon.update_result`, so Central records it,
// audits it and stops showing the node as `in_progress`.
func (m *Manager) handleUpdate(ctx context.Context, env protocol.Envelope, data []byte, send func([]byte) error) {
	if protocol.ValidateControl(data) != nil {
		m.replyError(send, env.RequestID, "INVALID_MESSAGE")
		return
	}
	var fields updateFields
	if json.Unmarshal(env.Payload, &fields) != nil || !protocol.ValidTargetVersion(fields.TargetVersion) {
		m.replyError(send, env.RequestID, "INVALID_MESSAGE")
		return
	}

	updater := m.newUpdater()
	if updater == nil {
		m.sendUpdateResult(send, env.RequestID, update.Result{
			FromVersion: m.version,
			ToVersion:   fields.TargetVersion,
			Status:      update.StatusFailed,
			Stage:       update.StageManifest,
			ErrorCode:   update.CodeNotAllowed,
			Detail:      "this node cannot resolve its own binary path",
		})
		return
	}
	result := updater.Update(ctx, fields.TargetVersion, fields.AllowDowngrade, false)
	slog.Info("daemon update requested by central",
		"target_version", fields.TargetVersion,
		"status", result.Status,
		"stage", result.Stage,
		"error_code", result.ErrorCode,
		// The detail can name a unit, a path or a systemctl message; it belongs in
		// the node's log, never in a frame Central turns into an API response.
		"detail", result.Detail,
	)
	m.sendUpdateResult(send, env.RequestID, result)
}

// newUpdater builds an Updater for this node, or nil if the installed binary cannot
// be located. Every input is local: the manifest origin comes from the config file's
// `server.url`, the binary path from this executable, the architecture from the
// build. Nothing is taken from the frame except the version.
func (m *Manager) newUpdater() *update.Updater {
	if m.newUpdaterFn != nil {
		return m.newUpdaterFn()
	}
	source, err := update.NewHTTPSource(m.cfg.Server.URL, nil)
	if err != nil {
		return nil
	}
	self, err := os.Executable()
	if err != nil {
		return nil
	}
	resolved, err := filepath.EvalSymlinks(self)
	if err != nil {
		resolved = self
	}
	return update.New(m.version, update.Options{
		Fetcher:    source,
		Downloader: source,
		Restarter:  update.NewSystemdRestarter("agentd"),
		HealthChecker: update.DoctorHealthChecker{
			BinaryPath: resolved,
			ConfigPath: m.configPath,
			Unit:       "agentd",
		},
		Architecture: runtime.GOARCH,
		BinaryPath:   resolved,
	})
}

// sendUpdateResult replies with a `daemon.update_result` frame.
//
// `error_code` is omitted when empty rather than sent as "": the schema's enum does
// not include the empty string, so a success frame carrying one would be rejected by
// Central's codec and the outcome would be lost.
func (m *Manager) sendUpdateResult(send func([]byte) error, requestID string, result update.Result) {
	payload := map[string]any{
		"from_version": result.FromVersion,
		"to_version":   result.ToVersion,
		"status":       result.Status,
		"stage":        result.Stage,
	}
	if result.ErrorCode != "" {
		payload["error_code"] = result.ErrorCode
	}
	frame, err := protocol.BuildResponse(
		"daemon.update_result", m.creds.NodeID, requestID, !result.Failed(), payload, m.now(),
	)
	if err == nil {
		_ = send(frame)
	}
}
