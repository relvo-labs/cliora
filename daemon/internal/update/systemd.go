package update

import (
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"time"
)

// SystemdRestarter restarts the agentd unit through systemctl.
//
// `Available` is what keeps SEC-007 true. It refuses unless the calling process is
// root, and it refuses *before* anything is downloaded or replaced. The long-running
// daemon is non-root, so a `daemon.update` control frame from Central lands here and
// is answered UPDATE_NOT_ALLOWED — the daemon is never given a way to escalate, and
// an operator runs `sudo agentd update` instead (ADR 0017).
//
// That also avoids the trap in the restart step: whoever runs `systemctl restart
// agentd` must not be the unit being restarted, or the process dies before it can
// health check or roll back. Under `sudo agentd update` the updater is a separate
// process, so it survives to finish the flow.
type SystemdRestarter struct {
	Unit string
	// Geteuid is injectable so the privilege rule can be tested without root.
	Geteuid func() int
	// LookPath is injectable so the systemd-absent branch can be tested.
	LookPath func(string) (string, error)
}

func NewSystemdRestarter(unit string) *SystemdRestarter {
	return &SystemdRestarter{Unit: unit, Geteuid: os.Geteuid, LookPath: exec.LookPath}
}

func (r *SystemdRestarter) Available() error {
	geteuid := r.Geteuid
	if geteuid == nil {
		geteuid = os.Geteuid
	}
	lookPath := r.LookPath
	if lookPath == nil {
		lookPath = exec.LookPath
	}
	if _, err := lookPath("systemctl"); err != nil {
		// A container or a non-systemd distro. The update is refused rather than
		// attempted by some other means, so the operator gets a clear instruction
		// instead of a half-installed binary and a service that never restarted.
		return errors.New("systemctl not found; replace the binary and restart the service manually")
	}
	if geteuid() != 0 {
		return ErrNoPrivilege
	}
	return nil
}

func (r *SystemdRestarter) Restart(ctx context.Context) error {
	cctx, cancel := contextWithTimeout(ctx, 60*time.Second)
	defer cancel()
	cmd := exec.CommandContext(cctx, "systemctl", "restart", r.Unit)
	if out, err := cmd.CombinedOutput(); err != nil {
		// systemctl's own message is included: it is the operator's most useful clue,
		// and it goes to the daemon log and the operator's terminal — never into a
		// Central API response (ADR 0017).
		return fmt.Errorf("systemctl restart %s failed: %s", r.Unit, firstLine(string(out)))
	}
	return nil
}

// DoctorHealthChecker is the post-restart health gate: the unit is active **and**
// the installed binary's own `doctor` passes.
//
// Two checks, because either alone is misleading. An active unit only proves the
// process started, not that it can read its config, find tmux or reach Central; a
// passing doctor run by *this* process does not prove the service came back at all.
//
// Re-registration with Central is the third half of the health definition
// (ADR 0017) and is deliberately not checked here: only Central can observe it. It
// is confirmed on that side, from the `node.register` the restarted daemon sends,
// which is also how a node whose result frame never arrived stops looking stuck.
type DoctorHealthChecker struct {
	BinaryPath string
	ConfigPath string
	Unit       string
	LookPath   func(string) (string, error)
}

func (c DoctorHealthChecker) Check(ctx context.Context) error {
	lookPath := c.LookPath
	if lookPath == nil {
		lookPath = exec.LookPath
	}
	if _, err := lookPath("systemctl"); err == nil {
		cctx, cancel := contextWithTimeout(ctx, 10*time.Second)
		cmd := exec.CommandContext(cctx, "systemctl", "is-active", "--quiet", c.Unit)
		err := cmd.Run()
		cancel()
		if err != nil {
			return fmt.Errorf("unit %s is not active", c.Unit)
		}
	}
	cctx, cancel := contextWithTimeout(ctx, 20*time.Second)
	defer cancel()
	cmd := exec.CommandContext(cctx, c.BinaryPath, "doctor", "--config", c.ConfigPath)
	cmd.WaitDelay = 500 * time.Millisecond
	if out, err := cmd.CombinedOutput(); err != nil {
		return fmt.Errorf("doctor failed: %s", firstLine(string(out)))
	}
	return nil
}

func contextWithTimeout(ctx context.Context, d time.Duration) (context.Context, context.CancelFunc) {
	if ctx == nil {
		ctx = context.Background()
	}
	return context.WithTimeout(ctx, d)
}
