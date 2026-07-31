package update

import (
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"os/user"
	"strconv"
	"strings"
	"syscall"
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
// The doctor child runs as the unit's `User=`, never as the updater. Two reasons,
// and the first one is why this gate did not work at all before: `agentd update`
// is run with sudo (ADR 0017), a plain child would inherit euid 0, and doctor's
// first check is EnsureNonRoot — so every real update failed healthcheck and rolled
// back. Dropping to the service user also makes the rest of the run mean something:
// "config readable", "credentials 0600", "workspace root readable" are all claims
// about a *specific* identity, and root satisfies them no matter who owns what.
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
	// Geteuid, ServiceUser and LookupUser are injectable so the privilege-drop
	// decision can be tested without root and without a live systemd.
	Geteuid     func() int
	ServiceUser func(ctx context.Context, unit string) (string, error)
	LookupUser  func(name string) (*user.User, error)
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

	cred, env, err := c.doctorIdentity(ctx, lookPath)
	if err != nil {
		return err
	}

	cctx, cancel := contextWithTimeout(ctx, 20*time.Second)
	defer cancel()
	cmd := exec.CommandContext(cctx, c.BinaryPath, "doctor", "--config", c.ConfigPath)
	cmd.WaitDelay = 500 * time.Millisecond
	if cred != nil {
		cmd.SysProcAttr = &syscall.SysProcAttr{Credential: cred}
		cmd.Env = env
	}
	if out, err := cmd.CombinedOutput(); err != nil {
		return fmt.Errorf("doctor failed: %s", firstLine(string(out)))
	}
	return nil
}

// doctorIdentity decides who the doctor child runs as. A nil credential means "run
// as this process", which is the right answer whenever the updater is not root —
// the unprivileged local-dev path, where there is nothing to drop.
func (c DoctorHealthChecker) doctorIdentity(
	ctx context.Context, lookPath func(string) (string, error),
) (*syscall.Credential, []string, error) {
	geteuid := c.Geteuid
	if geteuid == nil {
		geteuid = os.Geteuid
	}
	if geteuid() != 0 {
		return nil, nil, nil
	}

	serviceUser := c.ServiceUser
	if serviceUser == nil {
		serviceUser = systemdUnitUser
	}
	name, err := serviceUser(ctx, c.Unit)
	if err != nil {
		// Being root with no way to find out who the service is, is not something to
		// paper over by running doctor as root: that produces a green healthcheck for
		// a daemon that may not be able to read its own credentials. Fail the stage
		// and say why, so the rollback message names the real problem instead of
		// surfacing as a confusing "agentd must not run as root".
		return nil, nil, fmt.Errorf("cannot determine the user of unit %s: %w", c.Unit, err)
	}
	if name == "" || name == "root" {
		// No User= (or an explicit root) means the service really is running as root,
		// which SEC-007 forbids. Let doctor be the one to say so.
		return nil, nil, nil
	}

	lookupUser := c.LookupUser
	if lookupUser == nil {
		lookupUser = user.Lookup
	}
	acct, err := lookupUser(name)
	if err != nil {
		return nil, nil, fmt.Errorf("service user %q of unit %s not found: %w", name, c.Unit, err)
	}
	uid, err := strconv.ParseUint(acct.Uid, 10, 32)
	if err != nil {
		return nil, nil, fmt.Errorf("service user %q has a non-numeric uid %q", name, acct.Uid)
	}
	gid, err := strconv.ParseUint(acct.Gid, 10, 32)
	if err != nil {
		return nil, nil, fmt.Errorf("service user %q has a non-numeric gid %q", name, acct.Gid)
	}

	// Supplementary groups are carried over deliberately. systemd's User= grants
	// them, so omitting them here would run doctor with *less* access than the
	// daemon actually has and fail a workspace root that is readable by group.
	cred := &syscall.Credential{Uid: uint32(uid), Gid: uint32(gid)}
	if ids, gerr := acct.GroupIds(); gerr == nil {
		for _, raw := range ids {
			g, perr := strconv.ParseUint(raw, 10, 32)
			if perr == nil && uint32(g) != cred.Gid {
				cred.Groups = append(cred.Groups, uint32(g))
			}
		}
	}

	// HOME/USER/LOGNAME follow the uid. Left alone they would still say root, and
	// doctor's runtime detection probes the home directory for CLI config — it would
	// look in /root, which the service user cannot read, and report the wrong answer.
	env := os.Environ()
	filtered := env[:0]
	for _, kv := range env {
		if strings.HasPrefix(kv, "HOME=") || strings.HasPrefix(kv, "USER=") || strings.HasPrefix(kv, "LOGNAME=") {
			continue
		}
		filtered = append(filtered, kv)
	}
	filtered = append(filtered, "HOME="+acct.HomeDir, "USER="+name, "LOGNAME="+name)
	return cred, filtered, nil
}

// systemdUnitUser reads the effective User= of a unit. `systemctl show` is used
// rather than parsing the unit file: it reports what systemd resolved, including
// drop-ins, and it is what the running service actually is.
func systemdUnitUser(ctx context.Context, unit string) (string, error) {
	cctx, cancel := contextWithTimeout(ctx, 10*time.Second)
	defer cancel()
	out, err := exec.CommandContext(cctx, "systemctl", "show", "--property=User", "--value", unit).Output()
	if err != nil {
		return "", fmt.Errorf("systemctl show %s failed: %w", unit, err)
	}
	return strings.TrimSpace(string(out)), nil
}

func contextWithTimeout(ctx context.Context, d time.Duration) (context.Context, context.CancelFunc) {
	if ctx == nil {
		ctx = context.Background()
	}
	return context.WithTimeout(ctx, d)
}
