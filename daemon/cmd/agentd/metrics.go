package main

import (
	"fmt"

	"github.com/spf13/cobra"

	"github.com/cliora/cliora/daemon/internal/metrics"
)

// newMetricsCommand prints this process's metric registry (tech §18.2, P4-09).
//
// Deliberately a command, not a port. The daemon's trust boundary is outbound-only
// (ADR 0008): it dials Central and nothing dials it. Opening a Prometheus listener on
// every node to make scraping convenient would invert that for every node in the
// fleet, so the values Central needs travel on the heartbeat it is already sending
// (`node_metric_samples`, P4-06) and this command covers local debugging.
//
// Note what it can and cannot show: run as a separate process from the daemon, it sees
// a *fresh* registry — the counters belong to whichever process recorded them. It is
// therefore useful for `agentd update` and one-shot commands, while live daemon
// counters are read through Central. Said plainly in the output rather than left for
// someone to discover from a screen of zeros.
func newMetricsCommand() *cobra.Command {
	return &cobra.Command{
		Use:   "metrics",
		Short: "Print this process's metrics registry (no network port is opened)",
		RunE: func(cmd *cobra.Command, _ []string) error {
			out := cmd.OutOrStdout()
			rendered := metrics.Render()
			if rendered == "" {
				fmt.Fprintln(out, "(no metrics recorded in this process)")
			} else {
				fmt.Fprint(out, rendered)
			}
			fmt.Fprintln(out, "# These are this process's own counters. The running")
			fmt.Fprintln(out, "# daemon's live values reach Central over the heartbeat;")
			fmt.Fprintln(out, "# agentd never opens a metrics port.")
			return nil
		},
	}
}
