package main

import (
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"strings"

	"github.com/spf13/cobra"

	"github.com/cliora/cliora/daemon/internal/config"
	"github.com/cliora/cliora/daemon/internal/install"
)

// newPostureCommand implements `agentd posture` (ADR 0023, PV-05): the supported
// way to grant or revoke the privileged terminal on a node that is *already*
// installed.
//
// It exists because neither of the other paths works for an upgrade. `agentd
// install` needs a one-time enrollment token and would register a second node;
// `agentd update` replaces the binary and deliberately never rewrites the unit —
// a remotely triggered command that could change the unit would be a remotely
// triggered command that could grant root (ADR 0023 D11).
//
// The alternative was a runbook telling operators to edit sudoers by hand, which is
// the one step that can leave a machine unable to sudo at all. That validation and
// rollback logic exists once, here, and is covered by tests.
func newPostureCommand(configPath *string) *cobra.Command {
	var privileged bool
	cmd := &cobra.Command{
		Use:   "posture",
		Short: "Show or change this node's privileged-terminal posture (run with sudo)",
		Long: "With no flags, report what is actually installed. With " +
			"--privileged-terminal[=false], apply or revoke the posture: rewrite the " +
			"systemd unit, add or remove /etc/sudoers.d/60-agentd, and restart the service.",
		RunE: func(cmd *cobra.Command, _ []string) error {
			out := cmd.OutOrStdout()
			ctx := cmd.Context()
			sudoers := install.NewSudoersInstaller()
			current, err := currentPosture(sudoers)
			if err != nil {
				return err
			}
			if !cmd.Flags().Changed("privileged-terminal") {
				printPosture(out, current, *configPath)
				return nil
			}
			if os.Geteuid() != 0 {
				return errors.New("changing the posture must run as root (use sudo)")
			}
			// Idempotent on purpose: a runbook that says "run it again to confirm" must
			// not kick every session off the machine each time it is followed.
			if current.privileged == privileged {
				fmt.Fprintf(out, "Already %s; nothing to do.\n", postureWord(privileged))
				printPosture(out, current, *configPath)
				return nil
			}
			runUser, err := postureRunUser(current.unit)
			if err != nil {
				return err
			}
			if err := writeUnit(runUser, *configPath, privileged); err != nil {
				return err
			}
			if privileged {
				if err := sudoers.Install(ctx, runUser); err != nil {
					// Put the unit back: a machine whose unit says "privileged" but whose
					// sudoers says nothing is a machine that reports a posture it does not
					// have, and the console would then be lying about it.
					_ = writeUnit(runUser, *configPath, false)
					return fmt.Errorf("grant sudo to %s: %w", runUser, err)
				}
			} else if err := sudoers.Remove(); err != nil {
				return err
			}
			if err := setConfigPrivileged(*configPath, privileged); err != nil {
				// The config key is only a report (see config.NodeConfig), so a failure
				// here does not undo the grant — but it does mean the console will show
				// the wrong posture until it is fixed, so say so loudly.
				fmt.Fprintf(out, "[warn] could not update %s: %v\n", *configPath, err)
				fmt.Fprintf(out, "[warn] set node.privileged_terminal: %t there by hand, or the\n",
					privileged)
				fmt.Fprintln(out, "[warn] console will report the previous posture.")
			}
			if err := systemctl(ctx, "daemon-reload"); err != nil {
				return err
			}
			if err := systemctl(ctx, "restart", serviceName); err != nil {
				return err
			}
			fmt.Fprintf(out, "Posture is now %s.\n", postureWord(privileged))
			updated, err := currentPosture(sudoers)
			if err == nil {
				printPosture(out, updated, *configPath)
			}
			return nil
		},
	}
	cmd.Flags().BoolVar(&privileged, "privileged-terminal", true,
		"allow the system terminal to reach root via sudo (--privileged-terminal=false to revoke)")
	return cmd
}

type posture struct {
	unit       string
	unitFound  bool
	privileged bool
	dropIn     bool
	sudoWorks  bool
	configSays bool
	configRead bool
}

func currentPosture(sudoers *install.SudoersInstaller) (posture, error) {
	p := posture{dropIn: sudoers.Installed()}
	data, err := os.ReadFile(systemdUnitPath)
	if err == nil {
		p.unit, p.unitFound = string(data), true
		p.privileged = install.UnitIsPrivileged(p.unit)
	} else if !errors.Is(err, os.ErrNotExist) {
		return p, fmt.Errorf("read %s: %w", systemdUnitPath, err)
	}
	// Both halves are needed for the posture to actually work, so report the
	// conjunction rather than the unit alone.
	p.privileged = p.privileged && p.dropIn
	p.sudoWorks = sudoAvailable()
	return p, nil
}

func printPosture(out io.Writer, p posture, configPath string) {
	if !p.unitFound {
		fmt.Fprintf(out, "unit          : %s not found (agentd not installed here?)\n", systemdUnitPath)
	} else if install.UnitIsPrivileged(p.unit) {
		fmt.Fprintln(out, "unit          : NoNewPrivileges not set (escalation allowed)")
	} else {
		fmt.Fprintln(out, "unit          : NoNewPrivileges=true (sudo will fail)")
	}
	fmt.Fprintf(out, "sudoers       : %s\n", presence(p.dropIn, install.SudoersPath))
	fmt.Fprintf(out, "sudo -n true  : %s\n", yesNo(p.sudoWorks))
	if cfg, err := config.Load(configPath); err == nil {
		fmt.Fprintf(out, "config reports: privileged_terminal: %t\n", cfg.Node.PrivilegedTerminal)
		if cfg.Node.PrivilegedTerminal != p.privileged {
			fmt.Fprintf(out, "[warn] the config reports a posture the machine is not in; "+
				"the console will show the wrong thing until this is fixed\n")
		}
	}
	fmt.Fprintf(out, "posture       : %s\n", postureWord(p.privileged))
}

func postureWord(privileged bool) string {
	if privileged {
		return "privileged (the system terminal can reach root via sudo)"
	}
	return "unprivileged (the system terminal cannot escalate)"
}

func presence(present bool, path string) string {
	if present {
		return path + " present"
	}
	return path + " absent"
}

func yesNo(ok bool) string {
	if ok {
		return "succeeds"
	}
	return "fails"
}

// postureRunUser reads the service user out of the installed unit. Taken from the
// unit rather than a flag because that is the identity systemd will actually use,
// and a mismatch would grant sudo to the wrong account.
func postureRunUser(unit string) (string, error) {
	for _, line := range strings.Split(unit, "\n") {
		if user, ok := strings.CutPrefix(strings.TrimSpace(line), "User="); ok && user != "" {
			return user, nil
		}
	}
	return "", fmt.Errorf("no User= line in %s; reinstall rather than editing the posture",
		systemdUnitPath)
}

// setConfigPrivileged rewrites node.privileged_terminal in place, preserving the
// file's comments — they are how the node owner learns what the key does and does
// not do, so a rewrite that dropped them would remove the explanation and leave the
// switch.
func setConfigPrivileged(path string, privileged bool) error {
	data, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	lines := strings.Split(string(data), "\n")
	for i, line := range lines {
		if strings.HasPrefix(strings.TrimSpace(line), "privileged_terminal:") {
			indent := line[:len(line)-len(strings.TrimLeft(line, " \t"))]
			lines[i] = fmt.Sprintf("%sprivileged_terminal: %t", indent, privileged)
			return os.WriteFile(path, []byte(strings.Join(lines, "\n")), 0o600)
		}
	}
	return fmt.Errorf("no privileged_terminal key in %s", path)
}

// sudoAvailable reports whether sudo works right now, for this process, without a
// prompt. `-n` guarantees it cannot hang waiting for a password.
func sudoAvailable() bool {
	path, err := exec.LookPath("sudo")
	if err != nil {
		return false
	}
	return exec.CommandContext(context.Background(), path, "-n", "true").Run() == nil
}

// noNewPrivsSet reads the kernel's view of this process. It is the ground truth for
// why sudo fails: with no_new_privs set, setuid does nothing and sudo cannot become
// root no matter what sudoers says.
func noNewPrivsSet() (bool, bool) {
	data, err := os.ReadFile("/proc/self/status")
	if err != nil {
		return false, false
	}
	for _, line := range strings.Split(string(data), "\n") {
		if value, ok := strings.CutPrefix(line, "NoNewPrivs:"); ok {
			return strings.TrimSpace(value) == "1", true
		}
	}
	return false, false
}
