// Sudoers management for the privileged node posture (ADR 0023, PV-05).
//
// This is the most destructive thing agentd writes. A sudoers drop-in with a syntax
// error takes sudo away from the *whole machine*, including the sudo needed to fix
// it — so every write goes through `visudo -c` on a temp file first, is installed
// with an atomic rename, and is rolled back if the result does not actually work.
package install

import (
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
)

// SudoersPath is where the drop-in lives. The 60- prefix orders it after a
// distribution's own files and before an administrator's later additions;
// #includedir reads the directory in lexical order.
const SudoersPath = "/etc/sudoers.d/60-agentd"

// SudoersMode is required, not preferred: sudo ignores a drop-in whose permissions
// are wider than 0440, and it does so silently. The failure mode of getting this
// wrong is "the file is right there and has no effect".
const SudoersMode os.FileMode = 0o440

// userNamePattern is a POSIX user name. The value is interpolated into a file root
// parses, so it is validated before anything is written — not because the caller is
// hostile, but because a typo must fail here rather than in sudo's parser.
var userNamePattern = regexp.MustCompile(`^[a-z_][a-z0-9_-]{0,31}$`)

// SudoersContent renders the drop-in. NOPASSWD is not laziness: the service account
// generally has no password to type, and codex in bypass mode runs `sudo` unattended
// — an interactive prompt would hang it until timeout, which surfaces as "codex is
// stuck", not "codex lacks permission". A command allowlist was rejected: inside a
// shell that can already run anything, an allowlist either contains `sudo bash`
// (equivalent to full access, plus a list that rots) or gets edited to full access
// by the first user who needs a package (plan/12/00 D9).
func SudoersContent(user string) (string, error) {
	if !userNamePattern.MatchString(user) {
		return "", fmt.Errorf("invalid service user name %q", user)
	}
	return fmt.Sprintf(`# Managed by agentd (ADR 0023). Do not edit by hand.
# The Cliora system terminal (FR-SHELL-001) runs as this user. NOPASSWD is required
# because the service account has no password to type and because codex runs
# unattended in bypass mode (plan/12/00 D9).
# To revoke: agentd posture --privileged-terminal=false
%s ALL=(ALL) NOPASSWD:ALL
`, user), nil
}

// visudoBinary is a seam so tests can supply a stub validator instead of requiring
// visudo (and root) on the machine running them.
type SudoersInstaller struct {
	Path      string
	Visudo    string
	Runner    func(ctx context.Context, name string, args ...string) error
	Verifier  func(ctx context.Context, user string) error
	LookPathF func(string) (string, error)
}

// NewSudoersInstaller returns the production installer.
func NewSudoersInstaller() *SudoersInstaller {
	return &SudoersInstaller{
		Path:   SudoersPath,
		Visudo: "visudo",
		Runner: func(ctx context.Context, name string, args ...string) error {
			out, err := exec.CommandContext(ctx, name, args...).CombinedOutput()
			if err != nil {
				return fmt.Errorf("%s: %w: %s", name, err, strings.TrimSpace(string(out)))
			}
			return nil
		},
		Verifier:  verifySudoWorks,
		LookPathF: exec.LookPath,
	}
}

// Install writes the drop-in for user. Order matters and is the whole point:
// validate the name, write a temp file, have visudo parse it, rename it into place,
// then prove sudo actually works for that user — and undo the write if it does not.
// A half-applied privileged posture is worse than none, because nothing on the
// machine says which half.
func (s *SudoersInstaller) Install(ctx context.Context, user string) error {
	content, err := SudoersContent(user)
	if err != nil {
		return err
	}
	dir := filepath.Dir(s.Path)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return fmt.Errorf("create %s: %w", dir, err)
	}
	tmp, err := os.CreateTemp(dir, ".60-agentd.*")
	if err != nil {
		return fmt.Errorf("create temp sudoers: %w", err)
	}
	tmpName := tmp.Name()
	cleanup := func() { _ = os.Remove(tmpName) }
	if _, err := tmp.WriteString(content); err != nil {
		_ = tmp.Close()
		cleanup()
		return fmt.Errorf("write temp sudoers: %w", err)
	}
	if err := tmp.Close(); err != nil {
		cleanup()
		return fmt.Errorf("close temp sudoers: %w", err)
	}
	if err := os.Chmod(tmpName, SudoersMode); err != nil {
		cleanup()
		return fmt.Errorf("chmod temp sudoers: %w", err)
	}
	if err := s.validate(ctx, tmpName); err != nil {
		cleanup()
		return err
	}
	// Keep whatever was there so a failed verification can put it back.
	previous, hadPrevious := s.readExisting()
	if err := os.Rename(tmpName, s.Path); err != nil {
		cleanup()
		return fmt.Errorf("install %s: %w", s.Path, err)
	}
	if s.Verifier != nil {
		if verifyErr := s.Verifier(ctx, user); verifyErr != nil {
			// The rollback is part of the promise this error makes, so a rollback that
			// fails must change what the error says. "Rolled back" when nothing was
			// rolled back is the worst possible message here.
			if restoreErr := s.restore(previous, hadPrevious); restoreErr != nil {
				return fmt.Errorf(
					"sudo did not work for %s after installing %s (%w) AND the rollback failed "+
						"(%v) — remove or repair %s by hand before relying on this node",
					user, s.Path, verifyErr, restoreErr, s.Path)
			}
			return fmt.Errorf("sudo did not work for %s after installing %s (rolled back): %w",
				user, s.Path, verifyErr)
		}
	}
	return nil
}

// Remove deletes the drop-in. Absent is success: revoking a posture that was never
// granted is not an error, and `agentd posture` is meant to be re-runnable.
func (s *SudoersInstaller) Remove() error {
	if err := os.Remove(s.Path); err != nil && !errors.Is(err, os.ErrNotExist) {
		return fmt.Errorf("remove %s: %w", s.Path, err)
	}
	return nil
}

// Installed reports whether the drop-in exists.
func (s *SudoersInstaller) Installed() bool {
	_, err := os.Stat(s.Path)
	return err == nil
}

func (s *SudoersInstaller) validate(ctx context.Context, path string) error {
	if s.LookPathF != nil {
		if _, err := s.LookPathF(s.Visudo); err != nil {
			// Without a validator there is no safe way to install this file, so refuse.
			// "Install it and hope" is how a machine loses sudo entirely.
			return fmt.Errorf("%s not found; refusing to install a sudoers file that "+
				"cannot be validated", s.Visudo)
		}
	}
	if s.Runner == nil {
		return errors.New("no runner configured")
	}
	if err := s.Runner(ctx, s.Visudo, "-c", "-f", path); err != nil {
		return fmt.Errorf("sudoers file rejected by %s: %w", s.Visudo, err)
	}
	return nil
}

func (s *SudoersInstaller) readExisting() ([]byte, bool) {
	data, err := os.ReadFile(s.Path)
	if err != nil {
		return nil, false
	}
	return data, true
}

// restore puts back whatever was at Path before this install, or removes the file
// if there was nothing. The existing file is removed first: it is mode 0440, and
// writing over a read-only file fails — a detail that made an earlier version of
// this rollback silently do nothing.
func (s *SudoersInstaller) restore(previous []byte, had bool) error {
	if err := os.Remove(s.Path); err != nil && !errors.Is(err, os.ErrNotExist) {
		return err
	}
	if !had {
		return nil
	}
	return os.WriteFile(s.Path, previous, SudoersMode)
}

// verifySudoWorks checks the grant from the service user's own point of view. `sudo
// -n` never prompts, so this cannot hang an installer.
func verifySudoWorks(ctx context.Context, user string) error {
	if path, err := exec.LookPath("runuser"); err == nil {
		return runQuiet(ctx, path, "-u", user, "--", "sudo", "-n", "true")
	}
	// Some minimal images ship su but not runuser.
	if path, err := exec.LookPath("su"); err == nil {
		return runQuiet(ctx, path, "-s", "/bin/sh", "-c", "sudo -n true", user)
	}
	return errors.New("neither runuser nor su is available to verify the grant")
}

func runQuiet(ctx context.Context, name string, args ...string) error {
	out, err := exec.CommandContext(ctx, name, args...).CombinedOutput()
	if err != nil {
		return fmt.Errorf("%w: %s", err, strings.TrimSpace(string(out)))
	}
	return nil
}
