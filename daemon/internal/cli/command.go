package cli

import (
	"encoding/json"
	"fmt"
	"os"

	"github.com/spf13/cobra"
)

// NewCommand builds the `cliora` command tree.
//
// Reachable two ways, and both matter: as `cliora …` through the symlink the installer
// places next to agentd, and as `agentd cliora …` where there is no symlink (a
// container, a test, a machine where the install step could not write to /usr/local/bin).
//
// Deliberately **no `approve` subcommand.** The API refuses it, but a subcommand that
// exists invites an agent to try — and what it would get back is a 403 it then has to
// interpret. A tool that cannot express the thing is clearer than one that can express
// it and always fails.
func NewCommand() *cobra.Command {
	var sessionID string
	var asJSON bool

	root := &cobra.Command{
		Use:           "cliora",
		Short:         "Cliora task tools for an agent inside a session",
		SilenceUsage:  true,
		SilenceErrors: true,
	}
	root.PersistentFlags().StringVar(&sessionID, "session", "", "session id, when a workspace has more than one")
	root.PersistentFlags().BoolVar(&asJSON, "json", false, "machine-readable output")

	context := &cobra.Command{Use: "context", Short: "This session's task context"}
	context.AddCommand(&cobra.Command{
		Use:   "show",
		Short: "Print the context pack (no network)",
		RunE: func(cmd *cobra.Command, _ []string) error {
			// The one command that must work with Central down (D14). It reads a file
			// and returns; there is no client, no dial, no timeout.
			ctx, err := FindContext(".", sessionID)
			if err != nil {
				return exit(cmd, ExitRefused, err)
			}
			code, showErr := ShowContext(cmd.OutOrStdout(), ctx)
			if showErr != nil {
				return exit(cmd, code, showErr)
			}
			return nil
		},
	})

	task := &cobra.Command{Use: "task", Short: "The cards on this project's board"}
	task.AddCommand(&cobra.Command{
		Use:   "list",
		Short: "List this project's cards",
		RunE: func(cmd *cobra.Command, _ []string) error {
			ctx, err := FindContext(".", sessionID)
			if err != nil {
				return exit(cmd, ExitRefused, err)
			}
			tasks, code, listErr := NewClient(ctx).ListTasks("")
			if listErr != nil {
				return exit(cmd, code, listErr)
			}
			if asJSON {
				return writeJSON(cmd, tasks)
			}
			for _, item := range tasks {
				fmt.Fprintf(cmd.OutOrStdout(), "%-10s %-12s %s\n", item.CardRef, item.Stage, item.Title)
			}
			return nil
		},
	})
	task.AddCommand(&cobra.Command{
		Use:   "get <ref>",
		Short: "Show one card",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx, err := FindContext(".", sessionID)
			if err != nil {
				return exit(cmd, ExitRefused, err)
			}
			item, code, getErr := NewClient(ctx).GetTask(args[0])
			if getErr != nil {
				return exit(cmd, code, getErr)
			}
			if asJSON {
				return writeJSON(cmd, item)
			}
			fmt.Fprintf(cmd.OutOrStdout(), "%s  %s\n車道：%s  風險：%s  交付：%s  版本：%d\n",
				item.CardRef, item.Title, item.Stage, item.Risk, item.Delivery, item.Version)
			return nil
		},
	})

	var stage, note string
	update := &cobra.Command{
		Use:   "update <ref>",
		Short: "Move a card, or leave a note on it",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx, err := FindContext(".", sessionID)
			if err != nil {
				return exit(cmd, ExitRefused, err)
			}
			if stage == "" && note == "" {
				return exit(cmd, ExitRefused, fmt.Errorf("要改什麼？用 --stage 或 --note"))
			}
			item, warnings, code, updateErr := NewClient(ctx).UpdateTask(args[0], stage, note)
			if updateErr != nil {
				return exit(cmd, code, updateErr)
			}
			if asJSON {
				return writeJSON(cmd, map[string]any{"task": item, "warnings": warnings})
			}
			fmt.Fprintf(cmd.OutOrStdout(), "%s → %s\n", item.CardRef, item.Stage)
			// Warnings are printed, never treated as failure: the Definition of Ready
			// reports, it does not refuse (ADR 0028 sec 1).
			for _, warning := range warnings {
				fmt.Fprintf(cmd.ErrOrStderr(), "提醒：%v\n", warning)
			}
			return nil
		},
	}
	update.Flags().StringVar(&stage, "stage", "", "lane to move the card to")
	update.Flags().StringVar(&note, "note", "", "a short note to record on the card")
	task.AddCommand(update)

	root.AddCommand(context, task)
	return root
}

// exit prints the message and stops with the right code.
//
// `ExitUnreachable` is separated from `ExitRefused` so an agent can tell "the platform
// is down, carry on" from "the platform said no, read this" — the distinction D14's
// second sentence exists to make.
func exit(cmd *cobra.Command, code int, err error) error {
	fmt.Fprintln(cmd.ErrOrStderr(), err.Error())
	os.Exit(code)
	return nil
}

func writeJSON(cmd *cobra.Command, value any) error {
	encoder := json.NewEncoder(cmd.OutOrStdout())
	encoder.SetIndent("", "  ")
	return encoder.Encode(value)
}
