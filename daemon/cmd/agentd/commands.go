package main

import (
	"context"
	"fmt"
	"net"
	"net/url"
	"os"
	"os/exec"
	"strings"
	"time"

	"github.com/spf13/cobra"

	"github.com/cliora/cliora/daemon/internal/config"
	"github.com/cliora/cliora/daemon/internal/runtime"
	"github.com/cliora/cliora/daemon/internal/systeminfo"
	"github.com/cliora/cliora/daemon/internal/update"
)

func newConfigCommand(configPath *string) *cobra.Command {
	parent := &cobra.Command{Use: "config", Short: "Configuration commands"}
	parent.AddCommand(&cobra.Command{
		Use:   "validate",
		Short: "Validate the config file",
		RunE: func(cmd *cobra.Command, _ []string) error {
			if _, err := config.Load(*configPath); err != nil {
				return err
			}
			fmt.Fprintf(cmd.OutOrStdout(), "config OK: %s\n", *configPath)
			return nil
		},
	})
	return parent
}

func newRuntimeCommand(configPath *string) *cobra.Command {
	parent := &cobra.Command{Use: "runtime", Short: "Runtime commands"}
	parent.AddCommand(&cobra.Command{
		Use:   "list",
		Short: "Detect and list allowlisted runtimes",
		RunE: func(cmd *cobra.Command, _ []string) error {
			cfg, err := config.Load(*configPath)
			if err != nil {
				return err
			}
			reg := runtime.NewRegistry(cfg.Runtime)
			for _, r := range reg.DetectAll(context.Background(), time.Now()) {
				status := "unavailable (" + r.Reason + ")"
				if r.Available {
					status = "available " + r.Version
				}
				fmt.Fprintf(cmd.OutOrStdout(), "%-8s %s\n", r.Runtime, status)
			}
			return nil
		},
	})
	return parent
}

func newDoctorCommand(configPath *string) *cobra.Command {
	var credentialsPath string
	cmd := &cobra.Command{
		Use:   "doctor",
		Short: "Run environment diagnostics",
		RunE: func(cmd *cobra.Command, _ []string) error {
			ctx := cmd.Context()
			out := cmd.OutOrStdout()
			ok := true
			report := func(name string, err error) {
				if err != nil {
					ok = false
					fmt.Fprintf(out, "[FAIL] %s: %v\n", name, err)
				} else {
					fmt.Fprintf(out, "[ OK ] %s\n", name)
				}
			}
			// A warning never affects the exit code: doctor's contract is that
			// non-zero means a hard problem, and "no backup binary yet" on a node
			// that has never updated is not one.
			note := func(name, message string) {
				fmt.Fprintf(out, "[warn] %s: %s\n", name, message)
			}

			report("non-root", config.EnsureNonRoot())

			cfg, cfgErr := config.Load(*configPath)
			report("config", cfgErr)

			// Credentials are absent on a fresh box until enrollment; only their
			// presence-with-bad-perms/format is a failure. LoadCredentials also
			// rejects group/world-readable files (0600 check).
			if _, statErr := os.Stat(credentialsPath); statErr == nil {
				_, credErr := config.LoadCredentials(credentialsPath)
				report("credentials", credErr)
			} else {
				fmt.Fprintf(out, "[warn] credentials: %s not found (node not enrolled yet)\n", credentialsPath)
			}

			if path, err := exec.LookPath("tmux"); err != nil {
				report("tmux", fmt.Errorf("tmux not found on PATH"))
			} else {
				report("tmux", nil)
				fmt.Fprintf(out, "[info] tmux version=%s\n", tmuxVersion(ctx, path))
			}

			info := systeminfo.Gather()
			fmt.Fprintf(out, "[info] os=%s arch=%s user=%s\n", info.OSVersion, info.Architecture, info.RunUser)

			if self, err := resolveBinaryPath(""); err == nil {
				checkUpdateReadiness(update.DefaultStagingRoot, self, report, note)
			}

			if cfgErr == nil {
				report("central-reachable", dialCentral(cfg.Server.URL))
				for _, root := range cfg.Workspace.AllowedRoots {
					report("workspace-root:"+root, checkReadableDir(root))
				}
				reg := runtime.NewRegistry(cfg.Runtime)
				for _, r := range reg.DetectAll(context.Background(), time.Now()) {
					if r.Available {
						report("runtime:"+r.Runtime, nil)
					} else {
						fmt.Fprintf(out, "[warn] runtime:%s unavailable (%s)\n", r.Runtime, r.Reason)
					}
				}
			}

			if !ok {
				return fmt.Errorf("doctor found problems")
			}
			return nil
		},
	}
	cmd.Flags().StringVar(&credentialsPath, "credentials", config.DefaultCredentialsPath, "path to credentials.yaml")
	return cmd
}

// tmuxVersion returns the `tmux -V` version string (e.g. "tmux 3.4"), bounded by
// a short timeout so a wedged tmux cannot hang doctor. It reports "unknown" on
// any failure and never surfaces anything beyond the version banner.
func tmuxVersion(ctx context.Context, path string) string {
	cctx, cancel := context.WithTimeout(ctx, 3*time.Second)
	defer cancel()
	cmd := exec.CommandContext(cctx, path, "-V")
	cmd.WaitDelay = 200 * time.Millisecond
	out, err := cmd.Output()
	if err != nil {
		return "unknown"
	}
	v := strings.TrimSpace(string(out))
	if v == "" {
		return "unknown"
	}
	return v
}

// dialCentral confirms the configured Central endpoint is TCP-reachable. It
// reports a generic message on failure and never includes any secret.
func dialCentral(wsURL string) error {
	u, err := url.Parse(wsURL)
	if err != nil {
		return fmt.Errorf("invalid server url")
	}
	hostport := u.Host
	if u.Port() == "" {
		port := "443"
		if u.Scheme == "ws" {
			port = "80"
		}
		hostport = net.JoinHostPort(u.Hostname(), port)
	}
	conn, err := net.DialTimeout("tcp", hostport, 3*time.Second)
	if err != nil {
		return fmt.Errorf("cannot reach %s", u.Host)
	}
	_ = conn.Close()
	return nil
}

func checkReadableDir(path string) error {
	info, err := os.Stat(path)
	if err != nil {
		return fmt.Errorf("not accessible")
	}
	if !info.IsDir() {
		return fmt.Errorf("not a directory")
	}
	f, err := os.Open(path)
	if err != nil {
		return fmt.Errorf("not readable")
	}
	_ = f.Close()
	return nil
}
