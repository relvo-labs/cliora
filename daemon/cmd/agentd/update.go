package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"runtime"

	"github.com/spf13/cobra"

	"github.com/cliora/cliora/daemon/internal/config"
	"github.com/cliora/cliora/daemon/internal/update"
)

// newUpdateCommand implements `agentd update` (P4-10, FR-INSTALL-005).
//
// The flag set is the security boundary, and it is short on purpose: `--version`,
// `--allow-downgrade`, `--dry-run`. There is no `--url`, no `--file`, no
// `--checksum` — the artifact to install is derived from Central's release manifest
// plus this node's own config file, so nothing an operator (or an attacker with a
// shell) types on this line can redirect where a binary comes from (SEC-002).
//
// Run with sudo: replacing /usr/local/bin/agentd and restarting the unit need root,
// and the long-running daemon deliberately does not have it (SEC-007, ADR 0017).
func newUpdateCommand(configPath *string) *cobra.Command {
	var (
		targetVersion  string
		allowDowngrade bool
		dryRun         bool
		binaryPath     string
	)
	cmd := &cobra.Command{
		Use:   "update",
		Short: "Update this daemon to an allowlisted release",
		Long: "Downloads the requested release from this node's configured Central, " +
			"verifies its SHA-256 against the release manifest, replaces the binary " +
			"atomically, restarts the service, and rolls back if the health check " +
			"fails.\n\ntmux sessions are not affected: the tmux server is a separate " +
			"process, so running CLI sessions survive the restart and browsers " +
			"reconnect automatically.",
		RunE: func(cmd *cobra.Command, _ []string) error {
			cfg, err := config.Load(*configPath)
			if err != nil {
				return err
			}
			source, err := update.NewHTTPSource(cfg.Server.URL, nil)
			if err != nil {
				return err
			}
			resolved, err := resolveBinaryPath(binaryPath)
			if err != nil {
				return err
			}
			if targetVersion == "" {
				// Default to the newest allowlisted release rather than requiring the
				// operator to look it up — but resolved here, from the manifest, so it
				// is still a concrete version by the time the updater sees it.
				manifest, ferr := source.Fetch(cmd.Context())
				if ferr != nil {
					return ferr
				}
				if manifest.Latest == "" {
					return fmt.Errorf("no releases are published on %s", source.BaseURL)
				}
				targetVersion = manifest.Latest
			}

			updater := update.New(version, update.Options{
				Fetcher:    source,
				Downloader: source,
				Restarter:  update.NewSystemdRestarter(serviceName),
				HealthChecker: update.DoctorHealthChecker{
					BinaryPath: resolved,
					ConfigPath: *configPath,
					Unit:       serviceName,
				},
				Architecture: runtime.GOARCH,
				BinaryPath:   resolved,
			})
			result := updater.Update(cmd.Context(), targetVersion, allowDowngrade, dryRun)
			printUpdateResult(cmd, result)
			if result.Failed() {
				// Non-zero so a wrapper script or an operator's `&&` chain sees the
				// failure; the reason has already been printed in full.
				return fmt.Errorf("update %s: %s", result.Status, result.ErrorCode)
			}
			return nil
		},
	}
	cmd.Flags().StringVar(&targetVersion, "version", "", "release version to install (default: latest published)")
	cmd.Flags().BoolVar(&allowDowngrade, "allow-downgrade", false, "permit installing an older version than the running one")
	cmd.Flags().BoolVar(&dryRun, "dry-run", false, "verify manifest, checksum and version without replacing the binary")
	cmd.Flags().StringVar(&binaryPath, "binary", "", "path of the installed agentd binary (default: this executable)")
	return cmd
}

func printUpdateResult(cmd *cobra.Command, result update.Result) {
	out := cmd.OutOrStdout()
	switch result.Status {
	case update.StatusSucceeded:
		fmt.Fprintf(out, "[ OK ] %s\n", result.Detail)
	case update.StatusRolledBack:
		fmt.Fprintf(out, "[FAIL] update failed at the %s stage (%s) and was rolled back to %s\n",
			result.Stage, result.ErrorCode, result.FromVersion)
		fmt.Fprintf(out, "       %s\n", result.Detail)
		fmt.Fprintln(out, "       See docs/runbooks/update-failure.md")
	default:
		fmt.Fprintf(out, "[FAIL] update failed at the %s stage (%s)\n", result.Stage, result.ErrorCode)
		fmt.Fprintf(out, "       %s\n", result.Detail)
		if result.RollbackFailed {
			// The most serious outcome there is: the box is running a binary that
			// failed its own health check, and no automated step will fix it.
			fmt.Fprintf(out, "       WARNING: the rollback did not restore %s. Restore it manually.\n",
				result.FromVersion)
		}
		fmt.Fprintln(out, "       See docs/runbooks/update-failure.md")
	}
	// tmux is stated explicitly on every outcome: "did I just lose my sessions?" is
	// the first question an operator has, and the answer is always no.
	fmt.Fprintln(out, "       Existing tmux sessions were not affected.")
}

// resolveBinaryPath finds the installed binary to replace. Defaults to this
// executable, which is what `sudo agentd update` should mean; `--binary` exists for
// an installation in a non-default location, and is a *local* path an operator with
// root already controls — not something that can arrive over the wire.
func resolveBinaryPath(override string) (string, error) {
	if override != "" {
		return filepath.Abs(override)
	}
	self, err := os.Executable()
	if err != nil {
		return "", fmt.Errorf("cannot determine the running binary path: %w", err)
	}
	// Resolved so a symlinked /usr/local/bin/agentd is replaced where it really
	// lives, rather than the symlink being overwritten with a regular file.
	return filepath.EvalSymlinks(self)
}

// newVersionCommand prints the version, with --json for machine consumption
// (FR-INSTALL-004).
func newVersionCommand() *cobra.Command {
	var asJSON bool
	cmd := &cobra.Command{
		Use:   "version",
		Short: "Print the agentd version",
		RunE: func(cmd *cobra.Command, _ []string) error {
			if asJSON {
				// Marshalled rather than hand-formatted so a value containing a quote
				// cannot produce invalid JSON for whatever parses this.
				payload, err := json.Marshal(map[string]string{
					"version":      version,
					"architecture": runtime.GOARCH,
					"os":           runtime.GOOS,
					"go_version":   runtime.Version(),
				})
				if err != nil {
					return err
				}
				fmt.Fprintln(cmd.OutOrStdout(), string(payload))
				return nil
			}
			// Plain mode stays exactly one bare line: `agentd version` is what the
			// updater executes to confirm a staged binary reports the expected
			// version, so anything extra here would break verify-before-swap.
			fmt.Fprintln(cmd.OutOrStdout(), version)
			return nil
		},
	}
	cmd.Flags().BoolVar(&asJSON, "json", false, "print version information as JSON")
	return cmd
}

// checkUpdateReadiness adds the update subsystem's doctor lines (FR-INSTALL-004):
// is the staging directory private, and is a rollback actually possible?
//
// Both look fine until the moment they matter. A missing backup only hurts during a
// failed update — precisely when there is no time to discover it. A group-writable
// staging directory would let a local user replace the candidate binary in the
// window between the checksum passing and the swap, which is the one gap the
// verify-then-swap ordering cannot close on its own.
//
// `report` and `note` are the doctor command's own reporters, so these lines look
// like every other doctor line and a hard problem still makes the exit code non-zero.
func checkUpdateReadiness(
	stagingRoot, binaryPath string,
	report func(string, error),
	note func(string, string),
) {
	if info, err := os.Stat(stagingRoot); err == nil {
		if info.Mode().Perm()&0o077 != 0 {
			report("update-staging", fmt.Errorf(
				"%s must not be group/world accessible (want 0700, got %o)",
				stagingRoot, info.Mode().Perm()))
		} else {
			report("update-staging", nil)
		}
	} else {
		// Absent is fine: the first update creates it, 0700.
		note("update-staging", stagingRoot+" not present yet (created on first update)")
	}

	matches, _ := filepath.Glob(binaryPath + ".bak-*")
	if len(matches) > 0 {
		note("update-backup", "rollback target "+filepath.Base(matches[len(matches)-1]))
	} else {
		note("update-backup", "no backup binary yet (created by the first update)")
	}
}
