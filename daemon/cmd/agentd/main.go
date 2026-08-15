package main

import (
	"fmt"
	"os"
	"path/filepath"

	"github.com/spf13/cobra"

	"github.com/cliora/cliora/daemon/internal/cli"
	"github.com/cliora/cliora/daemon/internal/config"
)

// version is overridden at build time via -ldflags "-X main.version=...". The release
// it is overridden *to* is declared in daemon/VERSION, which is the single place the
// daemon's version is set: GoReleaser, the in-image build (scripts/railway/pack-agentd.sh)
// and this default all derive from it, and TestVersionMatchesTheVersionFile fails if this
// literal drifts from that file. An unstamped build says `-dev` so a developer binary
// cannot be mistaken for the release it was cut from.
var version = "0.12.0-dev"

func main() {
	// One binary, two tools (ADR 0028 sec 4). Invoked as `cliora` — through the
	// symlink the installer places beside agentd — this *is* the agent's CLI. The
	// alternative was shipping a second binary, and all three ways to do that were
	// closed: the projection path caps a file at 4 MiB, `.cliora/` is shut to the
	// user-facing write verb, and the updater extracts exactly one archive member by
	// name. Sharing the binary also means the CLI's version can never disagree with
	// the daemon's, which is what D11 wanted from "ship it with agentd".
	if filepath.Base(os.Args[0]) == "cliora" {
		if err := cli.NewCommand().Execute(); err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		return
	}
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
		// Also reachable as a subcommand, for every environment where the symlink
		// could not be created — a container, a test, a machine whose /usr/local/bin
		// the installer may not write to.
		cli.NewCommand(),
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
