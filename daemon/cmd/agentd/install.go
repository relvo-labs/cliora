package main

import (
	"context"
	"fmt"
	"io"
	"os"
	"os/exec"
	"os/user"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"github.com/spf13/cobra"
	"gopkg.in/yaml.v3"

	"github.com/cliora/cliora/daemon/internal/config"
	"github.com/cliora/cliora/daemon/internal/install"
	"github.com/cliora/cliora/daemon/internal/systeminfo"
)

const (
	binaryInstallPath = "/usr/local/bin/agentd"
	// The agent's CLI is the *same binary*, reached through a symlink (ADR 0028
	// sec 4). A symlink rather than a copy so that an update — which replaces the
	// file at `binaryInstallPath` in place — can never leave the two at different
	// versions, and so the release archive keeps its single member.
	cliInstallPath  = "/usr/local/bin/cliora"
	systemdUnitPath = "/etc/systemd/system/agentd.service"
	stateDir        = "/var/lib/agentd"
	logDir          = "/var/log/agentd"
	serviceName     = "agentd"
)

// newInstallCommand implements `agentd install` (P1-15). It runs under sudo,
// registers with Central over the enrollment token, writes the 0600
// config/credentials owned by --user, installs the binary + systemd unit, and
// starts the service as that non-root user (SEC-007).
func newInstallCommand(configPath *string) *cobra.Command {
	var (
		server          string
		token           string
		runUser         string
		nodeName        string
		workspaceRoots  []string
		allowInsecure   bool
		credentialsPath string
		privileged      bool
	)
	cmd := &cobra.Command{
		Use:   "install",
		Short: "Register with Central and install the systemd service (run with sudo)",
		RunE: func(cmd *cobra.Command, _ []string) error {
			if os.Geteuid() != 0 {
				return fmt.Errorf("install must run as root (use sudo)")
			}
			if server == "" || token == "" || runUser == "" || nodeName == "" {
				return fmt.Errorf("--server, --token, --user and --name are required")
			}
			acct, err := user.Lookup(runUser)
			if err != nil {
				return fmt.Errorf("service user %q not found: %w", runUser, err)
			}
			uid, _ := strconv.Atoi(acct.Uid)
			gid, _ := strconv.Atoi(acct.Gid)

			ctx := cmd.Context()
			out := cmd.OutOrStdout()
			now := time.Now()
			detected := install.DetectRuntimes(ctx, now)
			info := systeminfo.Gather()

			publicKey, privateKey, err := config.GenerateKeypair()
			if err != nil {
				return err
			}

			params := install.Params{
				Server: server, Token: token, NodeName: nodeName, RunUser: runUser,
				WorkspaceRoots: workspaceRoots, AllowInsecure: allowInsecure, DaemonVersion: version,
				PublicKey: publicKey, PrivilegedTerminal: privileged,
			}
			// Said before anything is written, and said plainly: this is the one part of
			// the install the operator cannot discover by reading the console later
			// (SEC-007.AC-02, ADR 0023).
			printPostureNotice(out, privileged)

			fmt.Fprintln(out, "Registering with Central…")
			resp, err := install.Register(ctx, install.DefaultClient(), server,
				install.BuildRegisterRequest(params, info, detected))
			if err != nil {
				return err // never contains the token or secret
			}
			fmt.Fprintf(out, "Registered as node %s\n", resp.NodeID)

			cfg, err := install.BuildConfig(params, detected)
			if err != nil {
				return err
			}
			if err := installFiles(cfg, resp, privateKey, *configPath, credentialsPath, uid, gid); err != nil {
				return err
			}
			if err := writeUnit(runUser, *configPath, privileged); err != nil {
				return err
			}
			if privileged {
				if err := install.NewSudoersInstaller().Install(ctx, runUser); err != nil {
					// Not a warning: the operator asked for a privileged node and would
					// otherwise get a machine whose console claims a posture it does not
					// have. The unit is written but the service is not started yet.
					return fmt.Errorf("grant sudo to %s: %w", runUser, err)
				}
				fmt.Fprintf(out, "Granted sudo to %s via %s\n", runUser, install.SudoersPath)
			}
			if err := startService(ctx); err != nil {
				return err
			}
			// Best-effort post-start check that the service is active and Central
			// is reachable. A failure is a warning, not a hard error: the unit is
			// Restart=always and the daemon reconnects with backoff on its own.
			if err := verifyStarted(ctx, cfg.Server.URL); err != nil {
				fmt.Fprintf(out, "[warn] post-start verification: %v\n", err)
				fmt.Fprintf(out, "[warn] the service will keep retrying; run 'agentd doctor' and check logs\n")
			} else {
				fmt.Fprintln(out, "Post-start check passed: service active and Central reachable.")
			}
			fmt.Fprintf(out, "Service %s installed and started. Verify with: agentd doctor\n", serviceName)
			return nil
		},
	}
	cmd.Flags().StringVar(&server, "server", "", "Central base URL (https://…)")
	cmd.Flags().StringVar(&token, "token", "", "one-time enrollment token")
	cmd.Flags().StringVar(&runUser, "user", "", "non-root user the service runs as")
	cmd.Flags().StringVar(&nodeName, "name", "", "human-readable node name")
	cmd.Flags().StringArrayVar(&workspaceRoots, "workspace-root", nil, "allowed workspace root (repeatable)")
	cmd.Flags().BoolVar(&allowInsecure, "allow-insecure", false, "permit http/ws server URL (dev only)")
	cmd.Flags().StringVar(&credentialsPath, "credentials", config.DefaultCredentialsPath, "path to credentials.yaml")
	// Default true: Cliora nodes are disposable isolated VMs and the posture was
	// asked for explicitly (ADR 0023 D0/D2). A machine that is not disposable is
	// installed with --privileged-terminal=false.
	cmd.Flags().BoolVar(&privileged, "privileged-terminal", true,
		"allow the system terminal to reach root via sudo (see ADR 0023)")
	return cmd
}

// printPostureNotice states the posture in the installer output. SEC-007's
// requirement that installation "clearly warns" about the daemon's privileges is
// older than this change; what is new is that the warning now has to cover a
// terminal that can become root and a CLI that runs without a sandbox.
func printPostureNotice(out io.Writer, privileged bool) {
	if !privileged {
		fmt.Fprintln(out, "Posture: the system terminal cannot escalate (NoNewPrivileges stays set).")
		fmt.Fprintln(out, "         codex still runs without a sandbox unless you also set")
		fmt.Fprintln(out, "         runtime.codex.sandbox_bypass: false in the config.")
		return
	}
	fmt.Fprintln(out, "warning: this node's system terminal can reach root through sudo, and codex")
	fmt.Fprintln(out, "         will run with approvals and its sandbox disabled. That is the")
	fmt.Fprintln(out, "         intended posture for a disposable, isolated VM.")
	fmt.Fprintln(out, "         If this machine is not disposable, reinstall with")
	fmt.Fprintln(out, "         --privileged-terminal=false and set")
	fmt.Fprintln(out, "         runtime.codex.sandbox_bypass: false in /etc/agentd/config.yaml.")
}

// installFiles writes config + credentials at 0600 owned by the service user,
// installs the binary, and creates the owned state/log directories.
func installFiles(cfg *config.Config, resp *install.RegisterResponse, privateKey, configPath, credentialsPath string, uid, gid int) error {
	configData, err := install.MarshalConfig(cfg)
	if err != nil {
		return err
	}
	credsData, err := yaml.Marshal(config.Credentials{NodeID: resp.NodeID, PrivateKey: privateKey})
	if err != nil {
		return err
	}
	if err := writeOwned(configPath, configData, 0o600, uid, gid); err != nil {
		return err
	}
	if err := writeOwned(credentialsPath, credsData, 0o600, uid, gid); err != nil {
		return err
	}
	for _, dir := range []string{stateDir, logDir} {
		if err := os.MkdirAll(dir, 0o750); err != nil {
			return fmt.Errorf("create %s: %w", dir, err)
		}
		if err := os.Chown(dir, uid, gid); err != nil {
			return fmt.Errorf("chown %s: %w", dir, err)
		}
	}
	if err := copyExecutable(binaryInstallPath); err != nil {
		return err
	}
	// Best-effort, and loud when it does not happen: the daemon is what the install is
	// for, and `agentd cliora …` reaches the same code without the symlink.
	if err := ensureCLISymlink(); err != nil {
		fmt.Fprintf(os.Stderr, "note: %v (agent tools remain available as `agentd cliora`)\n", err)
	}
	return nil
}

// writeOwned creates the parent directory, writes the file at the given mode,
// then chowns it to the service user so a non-root daemon can read it at 0600.
func writeOwned(path string, data []byte, mode os.FileMode, uid, gid int) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return fmt.Errorf("create dir for %s: %w", path, err)
	}
	if err := os.WriteFile(path, data, mode); err != nil {
		return fmt.Errorf("write %s: %w", path, err)
	}
	if err := os.Chmod(path, mode); err != nil {
		return fmt.Errorf("chmod %s: %w", path, err)
	}
	if err := os.Chown(path, uid, gid); err != nil {
		return fmt.Errorf("chown %s: %w", path, err)
	}
	return nil
}

// ensureCLISymlink puts `cliora` beside `agentd`, pointing at it.
//
// Three deliberate refusals, in order of how likely each is to bite:
//
//   - an existing symlink already pointing at agentd is success, not an error, so the
//     installer stays re-runnable;
//   - anything else already at that path is **left alone** and reported — silently
//     replacing a file called `cliora` that somebody put there is not the installer's
//     decision to make;
//   - a failure here does not fail the install. The daemon is what the install is for,
//     and `agentd cliora …` works either way.
func ensureCLISymlink() error {
	if target, err := os.Readlink(cliInstallPath); err == nil {
		if target == binaryInstallPath {
			return nil
		}
		return fmt.Errorf("%s already points at %s; leaving it alone", cliInstallPath, target)
	}
	if _, err := os.Lstat(cliInstallPath); err == nil {
		return fmt.Errorf("%s already exists and is not a symlink; leaving it alone", cliInstallPath)
	}
	return os.Symlink(binaryInstallPath, cliInstallPath)
}

func copyExecutable(dst string) error {
	src, err := os.Executable()
	if err != nil {
		return fmt.Errorf("locate current binary: %w", err)
	}
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer func() { _ = in.Close() }()
	tmp := dst + ".new"
	out, err := os.OpenFile(tmp, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o755)
	if err != nil {
		return err
	}
	if _, err := io.Copy(out, in); err != nil {
		_ = out.Close()
		return err
	}
	if err := out.Close(); err != nil {
		return err
	}
	// Atomic replace so a running binary is never truncated mid-copy.
	return os.Rename(tmp, dst)
}

func writeUnit(runUser, configPath string, privileged bool) error {
	unit := install.UnitFile(install.UnitParams{
		User: runUser, BinaryPath: binaryInstallPath, ConfigPath: configPath,
		PrivilegedTerminal: privileged,
	})
	return os.WriteFile(systemdUnitPath, []byte(unit), 0o644)
}

// verifyStarted runs the bounded post-start verification, checking service
// activation via `systemctl is-active` and Central TCP reachability.
func verifyStarted(ctx context.Context, centralURL string) error {
	active := func(c context.Context) (bool, error) {
		out, err := exec.CommandContext(c, "systemctl", "is-active", serviceName).Output()
		return strings.TrimSpace(string(out)) == "active", err
	}
	return install.VerifyConnection(ctx, centralURL, active, 15*time.Second)
}

func startService(ctx context.Context) error {
	if err := systemctl(ctx, "daemon-reload"); err != nil {
		return err
	}
	return systemctl(ctx, "enable", "--now", serviceName)
}

func systemctl(ctx context.Context, args ...string) error {
	cmd := exec.CommandContext(ctx, "systemctl", args...)
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	if err := cmd.Run(); err != nil {
		return fmt.Errorf("systemctl %v failed: %w", args, err)
	}
	return nil
}

// newUninstallCommand implements `agentd uninstall`: stop + disable the service,
// remove the unit and config directory. State under /var/lib is left in place
// unless --purge is given (node removal on Central is a soft delete, ADR 0011).
func newUninstallCommand(configPath *string) *cobra.Command {
	var purge bool
	cmd := &cobra.Command{
		Use:   "uninstall",
		Short: "Stop the service and remove agentd files (run with sudo)",
		RunE: func(cmd *cobra.Command, _ []string) error {
			if os.Geteuid() != 0 {
				return fmt.Errorf("uninstall must run as root (use sudo)")
			}
			ctx := cmd.Context()
			out := cmd.OutOrStdout()
			// Best-effort: continue teardown even if the service is already gone.
			_ = systemctl(ctx, "disable", "--now", serviceName)
			_ = os.Remove(systemdUnitPath)
			_ = systemctl(ctx, "daemon-reload")
			_ = os.RemoveAll(filepath.Dir(*configPath))
			if purge {
				_ = os.RemoveAll(stateDir)
				_ = os.RemoveAll(logDir)
			}
			// Removed in both modes: a sudoers file granting rights to a service that no
			// longer exists is the worst kind of leftover — it grants something and
			// explains nothing.
			_ = install.NewSudoersInstaller().Remove()
			_ = os.Remove(binaryInstallPath)
			fmt.Fprintln(out, "agentd removed. Central still holds the node record (soft delete).")
			return nil
		},
	}
	cmd.Flags().BoolVar(&purge, "purge", false, "also remove state and log directories")
	return cmd
}
