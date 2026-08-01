package main

import (
	"context"
	"log/slog"
	"os/signal"
	"syscall"

	"github.com/spf13/cobra"

	"github.com/cliora/cliora/daemon/internal/config"
	"github.com/cliora/cliora/daemon/internal/connection"
	"github.com/cliora/cliora/daemon/internal/runtime"
	"github.com/cliora/cliora/daemon/internal/systeminfo"
	ctmux "github.com/cliora/cliora/daemon/internal/tmux"
)

// newRunCommand is the systemd entrypoint: preflight (non-root, config,
// credentials) then run the connection manager until signalled (P1-11).
func newRunCommand(configPath *string) *cobra.Command {
	var credentialsPath string
	cmd := &cobra.Command{
		Use:   "run",
		Short: "Connect to Central and serve (systemd entrypoint)",
		RunE: func(_ *cobra.Command, _ []string) error {
			if err := config.EnsureNonRoot(); err != nil {
				return err
			}
			cfg, err := config.Load(*configPath)
			if err != nil {
				return err
			}
			creds, err := config.LoadCredentials(credentialsPath)
			if err != nil {
				return err
			}
			registry := runtime.NewRegistry(cfg.Runtime)
			// The system terminal is enabled unless the operator disabled it, and
			// an upgraded node inherits it from the default rather than from its
			// config file (ADR 0021). Which of the two applies here is not
			// guessable from the outside, so it goes in the startup log.
			shellSource := "config"
			if cfg.ShellFromDefault {
				shellSource = "default"
			}
			slog.Info("runtime_shell",
				"enabled", cfg.Runtime[config.ShellRuntimeID].Enabled,
				"source", shellSource)
			// The same reasoning applies to the two posture switches this node now
			// carries (ADR 0023): "the operator chose this" and "an upgrade defaulted
			// into this" are different facts about a machine that runs a CLI without a
			// sandbox and hands out root through sudo, and neither is guessable from
			// outside. Both go in the startup log, once, on the way up.
			for id := range config.SandboxBypassRuntimeIDs {
				rc, present := cfg.Runtime[id]
				if !present {
					continue
				}
				source := "config"
				if cfg.SandboxBypassFromDefault[id] {
					source = "default"
				}
				slog.Info("runtime_sandbox",
					"runtime", id, "bypass", rc.BypassSandbox(), "source", source)
			}
			slog.Info("privileged_terminal", "enabled", cfg.Node.PrivilegedTerminal)
			// Sessions moved to their own tmux server (PV-04). Anything left on the
			// default socket by an older daemon cannot be adopted — a tmux session
			// belongs to its server — so the only useful thing to do is say so, because
			// from the console those sessions simply stopped existing.
			if legacy := ctmux.LegacySessionNames(context.Background()); len(legacy) > 0 {
				slog.Warn("cliora sessions found on the default tmux socket; they are no "+
					"longer served and are not killed — see docs/runbooks/privileged-node-posture.md",
					"count", len(legacy))
			}
			info := systeminfo.Gather()
			manager := connection.New(cfg, creds, registry, info, version)
			manager.SetConfigPath(*configPath)

			ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
			defer stop()
			return manager.Run(ctx)
		},
	}
	cmd.Flags().StringVar(&credentialsPath, "credentials", config.DefaultCredentialsPath, "path to credentials.yaml")
	return cmd
}
