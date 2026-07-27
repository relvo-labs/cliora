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
	systemdUnitPath   = "/etc/systemd/system/agentd.service"
	stateDir          = "/var/lib/agentd"
	logDir            = "/var/log/agentd"
	serviceName       = "agentd"
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
				PublicKey: publicKey,
			}

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
			if err := writeUnit(runUser, *configPath); err != nil {
				return err
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
	return cmd
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
	return copyExecutable(binaryInstallPath)
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

func writeUnit(runUser, configPath string) error {
	unit := install.UnitFile(install.UnitParams{
		User: runUser, BinaryPath: binaryInstallPath, ConfigPath: configPath,
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
			_ = os.Remove(binaryInstallPath)
			fmt.Fprintln(out, "agentd removed. Central still holds the node record (soft delete).")
			return nil
		},
	}
	cmd.Flags().BoolVar(&purge, "purge", false, "also remove state and log directories")
	return cmd
}
