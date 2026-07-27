package main

import (
	"fmt"
	"os"

	"github.com/spf13/cobra"

	"github.com/cliora/cliora/daemon/internal/config"
)

// version is overridden at build time via -ldflags "-X main.version=...".
var version = "0.2.0-dev"

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
		newRegisterCommand(),
		newWorkspaceCommand(&configPath),
		newUpdateCommand(&configPath),
		newMetricsCommand(),
	)
	root.AddCommand(newServiceCommands()...)
	return root
}
