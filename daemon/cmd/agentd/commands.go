package main

import (
	"context"
	"fmt"
	"io"
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
	ctmux "github.com/cliora/cliora/daemon/internal/tmux"
	"github.com/cliora/cliora/daemon/internal/tunnel"
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
					reportSandboxPosture(out, r)
				}
				reportTmuxPosture(ctx, out, cfg)
			}

			// The privileged posture is not a fault in either direction, so neither
			// branch fails doctor. What *is* worth flagging is a machine whose config
			// reports one posture and whose kernel is in the other — the console shows
			// the config's answer, so a mismatch means the console is lying.
			reportPrivilegePosture(out, cfg, cfgErr, note)

			if cfgErr == nil {
				reportTunnelReadiness(out, cfg, report, note)
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

// reportSandboxPosture prints what a runtime will actually launch with. The
// requested-but-unsupported case is the only one that warrants a warning: the node
// asked for the sandbox to be off, the installed CLI does not know the flag, and the
// console will show "enforced". Without this line the operator would have to diff
// the process argv against their config to find that out (ADR 0023 D3).
func reportSandboxPosture(out io.Writer, r runtime.DetectResult) {
	if !r.SandboxBypassRequested && !r.SandboxBypass {
		return
	}
	switch {
	case r.SandboxBypass:
		fmt.Fprintf(out, "[info] runtime:%s sandbox=bypassed flag=%s\n",
			r.Runtime, runtime.SandboxBypassFlag)
	case r.SandboxNote == runtime.ReasonSandboxFlagUnsupported:
		fmt.Fprintf(out, "[warn] runtime:%s sandbox=enforced: this build of %s does not accept "+
			"%s (version %s). The console will show the sandbox as enforced.\n",
			r.Runtime, r.Runtime, runtime.SandboxBypassFlag, r.Version)
	default:
		fmt.Fprintf(out, "[info] runtime:%s sandbox=enforced\n", r.Runtime)
	}
}

// reportTmuxPosture prints the scrollback depth the terminal actually has. Read from
// the live tmux server, not from config: the server outlives the daemon, and a pane
// keeps the history-limit it was created with, so the two can disagree after a
// config change (see tmux.Client.applySessionOptions).
func reportTmuxPosture(ctx context.Context, out io.Writer, cfg *config.Config) {
	fmt.Fprintf(out, "[info] tmux socket=%s scrollback_configured=%d\n",
		ctmux.DefaultSocket, cfg.Session.ScrollbackLimit)
	if legacy := ctmux.LegacySessionNames(ctx); len(legacy) > 0 {
		fmt.Fprintf(out, "[warn] %d cliora session(s) remain on tmux's default socket and are "+
			"no longer served; see docs/runbooks/privileged-node-posture.md\n", len(legacy))
	}
}

// reportPrivilegePosture prints the sudo posture and, when config and kernel
// disagree, says which one the console believes.
func reportPrivilegePosture(out io.Writer, cfg *config.Config, cfgErr error, note func(string, string)) {
	noNewPrivs, known := noNewPrivsSet()
	switch {
	case !known:
		fmt.Fprintln(out, "[info] no-new-privs=unknown (no /proc/self/status)")
	case noNewPrivs:
		fmt.Fprintln(out, "[info] no-new-privs=1 (sudo cannot escalate from this process)")
	default:
		fmt.Fprintln(out, "[info] no-new-privs=0 (escalation allowed)")
	}
	sudo := sudoAvailable()
	fmt.Fprintf(out, "[info] sudo=%s\n", map[bool]string{true: "available", false: "unavailable"}[sudo])
	if cfgErr != nil || cfg == nil {
		return
	}
	fmt.Fprintf(out, "[info] privileged-terminal reported to Central: %t\n", cfg.Node.PrivilegedTerminal)
	if cfg.Node.PrivilegedTerminal != sudo {
		note("posture", fmt.Sprintf(
			"config reports privileged_terminal: %t but sudo %s here; run "+
				"`sudo agentd posture` to see what is installed and "+
				"`sudo agentd posture --privileged-terminal=%t` to make them agree",
			cfg.Node.PrivilegedTerminal, map[bool]string{true: "succeeds", false: "fails"}[sudo],
			cfg.Node.PrivilegedTerminal))
	}
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

// reportTunnelReadiness answers the four questions port forwarding fails on (P11, ADR 0022).
// Without them, all four look identical from the platform: "could not open a tunnel".
//
// There is deliberately no credential check. The provider credential is held by the platform
// and delivered with each request, so this node has nothing to inspect — and saying so here
// is better than leaving a reader to wonder which check is missing.
func reportTunnelReadiness(
	out io.Writer,
	cfg *config.Config,
	report func(string, error),
	note func(string, string),
) {
	if !cfg.TunnelEnabled() {
		// A veto is a valid configuration, not a fault: it must not fail doctor.
		note("tunnel", "disabled on this node (tunnel.enabled: false); the platform cannot override this")
		return
	}
	if _, err := exec.LookPath("ssh"); err != nil {
		report("tunnel:ssh-client", fmt.Errorf("ssh not found on PATH (install openssh-client)"))
	} else {
		report("tunnel:ssh-client", nil)
	}

	// A missing node-local file is not a fault: the binary carries the provider's keys,
	// and reporting otherwise is what used to roll back every update — doctor is the
	// update health check, so a hard failure here fails the upgrade of a node whose
	// tunnels would have worked fine (P4-10 × P11).
	resolved, err := tunnel.ResolveKnownHosts(cfg.Tunnel.KnownHostsPath)
	switch {
	case err != nil:
		report("tunnel:host-key", err)
	case resolved.FromBuild():
		report("tunnel:host-key", nil)
		fmt.Fprintf(out, "[info] tunnel host keys pinned by this build (no %s on this node)\n",
			cfg.Tunnel.KnownHostsPath)
	default:
		report("tunnel:host-key", nil)
		fmt.Fprintf(out, "[info] tunnel host keys pinned by %s\n", resolved.Path)
	}

	if err := dialProvider(); err != nil {
		report("tunnel:provider-reachable", err)
	} else {
		report("tunnel:provider-reachable", nil)
	}

	if len(cfg.Tunnel.AllowedPorts) > 0 {
		fmt.Fprintf(out, "[info] tunnel allowed ports on this node: %s\n",
			strings.Join(cfg.Tunnel.AllowedPorts, ", "))
	}
	fmt.Fprintf(out, "[info] tunnel credential is held by the platform, not this node\n")
}

// dialProvider tests outbound reachability to the provider's SSH endpoint. A plain TCP
// connect: enough to tell a blocked egress from a broken tunnel, and it authenticates
// nothing and sends nothing.
func dialProvider() error {
	conn, err := net.DialTimeout("tcp", tunnel.ProviderDialAddress(), 5*time.Second)
	if err != nil {
		return fmt.Errorf("cannot reach %s (check firewall or proxy)", tunnel.ProviderDialAddress())
	}
	_ = conn.Close()
	return nil
}
