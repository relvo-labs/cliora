package main

import (
	"fmt"
	"os"

	"github.com/spf13/cobra"

	"github.com/cliora/cliora/daemon/internal/config"
)

// version is overridden at build time via -ldflags "-X main.version=...".
// daemon/VERSION declares the release: scripts/railway/pack-agentd.sh reads it,
// make release checks the GoReleaser tag against it, and
// TestVersionMatchesTheVersionFile guards this fallback against drift. An unstamped
// build says `-dev` so a developer binary cannot be mistaken for a release.
var version = "0.7.1-dev"

func main() {
	if err := newRootCommand().Execute(); err != nil {
		fmt.Fprintln(os.Stderr, "error:", err)
		os.Exit(1)
	}
}

func newRootCommand() *cobra.Command {
	var configPath string
	root := &cobra.Command{
		Use:           "agentd",
		Short:         "Cliora node daemon",
		SilenceUsage:  true,
		SilenceErrors: true,
	}
	root.PersistentFlags().StringVar(&configPath, "config", config.DefaultConfigPath, "path to config.yaml")

	root.AddCommand(
		newVersionCommand(),
		newRunCommand(&configPath),
		newConfigCommand(&configPath),
		newRuntimeCommand(&configPath),
		newDoctorCommand(&configPath),
		newInstallCommand(&configPath),
		newUninstallCommand(&configPath),
		newPostureCommand(&configPath),
		newRegisterCommand(),
		newWorkspaceCommand(&configPath),
		newUpdateCommand(&configPath),
		newMetricsCommand(),
	)
	root.AddCommand(newServiceCommands()...)
	return root
}
