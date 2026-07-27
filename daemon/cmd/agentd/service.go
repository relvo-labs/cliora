package main

import (
	"fmt"
	"os"
	"os/exec"
	"os/user"
	"strconv"
	"time"

	"github.com/spf13/cobra"
	"gopkg.in/yaml.v3"

	"github.com/cliora/cliora/daemon/internal/config"
	"github.com/cliora/cliora/daemon/internal/install"
	"github.com/cliora/cliora/daemon/internal/systeminfo"
)

// newServiceCommands wraps the systemd lifecycle verbs the operator uses after
// install: start, stop, status.
func newServiceCommands() []*cobra.Command {
	start := &cobra.Command{
		Use:   "start",
		Short: "Start the agentd service",
		RunE:  func(cmd *cobra.Command, _ []string) error { return systemctl(cmd.Context(), "start", serviceName) },
	}
	stop := &cobra.Command{
		Use:   "stop",
		Short: "Stop the agentd service",
		RunE:  func(cmd *cobra.Command, _ []string) error { return systemctl(cmd.Context(), "stop", serviceName) },
	}
	status := &cobra.Command{
		Use:   "status",
		Short: "Show the agentd service status",
		RunE: func(cmd *cobra.Command, _ []string) error {
			// `systemctl status` exits non-zero when inactive; surface its output
			// without turning an inactive service into a command failure.
			out := exec.CommandContext(cmd.Context(), "systemctl", "status", serviceName, "--no-pager")
			out.Stdout = cmd.OutOrStdout()
			out.Stderr = cmd.ErrOrStderr()
			_ = out.Run()
			return nil
		},
	}
	return []*cobra.Command{start, stop, status}
}

// newRegisterCommand re-enrolls an existing installation: it registers over a
// fresh enrollment token and rewrites credentials.yaml (0600, owned by --user).
// Unlike install it does not touch the binary or systemd unit.
func newRegisterCommand() *cobra.Command {
	var (
		server          string
		token           string
		runUser         string
		nodeName        string
		allowInsecure   bool
		credentialsPath string
	)
	cmd := &cobra.Command{
		Use:   "register",
		Short: "Register (or re-enroll) this node and write credentials.yaml",
		RunE: func(cmd *cobra.Command, _ []string) error {
			if os.Geteuid() != 0 {
				return fmt.Errorf("register must run as root (use sudo)")
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
			publicKey, privateKey, err := config.GenerateKeypair()
			if err != nil {
				return err
			}
			params := install.Params{
				Server: server, Token: token, NodeName: nodeName, RunUser: runUser,
				AllowInsecure: allowInsecure, DaemonVersion: version, PublicKey: publicKey,
			}
			detected := install.DetectRuntimes(ctx, time.Now())
			resp, err := install.Register(ctx, install.DefaultClient(), server,
				install.BuildRegisterRequest(params, systeminfo.Gather(), detected))
			if err != nil {
				return err
			}
			data, err := yaml.Marshal(config.Credentials{NodeID: resp.NodeID, PrivateKey: privateKey})
			if err != nil {
				return err
			}
			if err := writeOwned(credentialsPath, data, 0o600, uid, gid); err != nil {
				return err
			}
			fmt.Fprintf(cmd.OutOrStdout(), "Registered as node %s\n", resp.NodeID)
			return nil
		},
	}
	cmd.Flags().StringVar(&server, "server", "", "Central base URL (https://…)")
	cmd.Flags().StringVar(&token, "token", "", "one-time enrollment token")
	cmd.Flags().StringVar(&runUser, "user", "", "non-root user that owns credentials.yaml")
	cmd.Flags().StringVar(&nodeName, "name", "", "human-readable node name")
	cmd.Flags().BoolVar(&allowInsecure, "allow-insecure", false, "permit http/ws server URL (dev only)")
	cmd.Flags().StringVar(&credentialsPath, "credentials", config.DefaultCredentialsPath, "path to credentials.yaml")
	return cmd
}

// newWorkspaceCommand lists the allowed workspace roots from the config.
func newWorkspaceCommand(configPath *string) *cobra.Command {
	parent := &cobra.Command{Use: "workspace", Short: "Workspace commands"}
	parent.AddCommand(&cobra.Command{
		Use:   "list",
		Short: "List configured allowed workspace roots",
		RunE: func(cmd *cobra.Command, _ []string) error {
			cfg, err := config.Load(*configPath)
			if err != nil {
				return err
			}
			out := cmd.OutOrStdout()
			if len(cfg.Workspace.AllowedRoots) == 0 {
				fmt.Fprintln(out, "(no allowed roots configured)")
				return nil
			}
			for _, root := range cfg.Workspace.AllowedRoots {
				fmt.Fprintln(out, root)
			}
			return nil
		},
	})
	return parent
}
