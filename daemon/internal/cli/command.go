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

	// --- V2.2: the four an unattended run needs (AR-08) ---
	//
	// **The card is the only channel.** A run has nobody at a terminal, so anything it
	// does not say here is something nobody will ever know it did — and the run
	// directory is reclaimed on a retention schedule.
	say := &cobra.Command{
		Use:   "say <text>",
		Short: "Post a message on this run's card",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx, err := FindContext(".", sessionID)
			if err != nil {
				return exit(cmd, ExitRefused, err)
			}
			message, code, postErr := NewClient(ctx).PostMessage(args[0], "message")
			if postErr != nil {
				return exit(cmd, code, postErr)
			}
			if asJSON {
				return writeJSON(cmd, message)
			}
			fmt.Fprintln(cmd.OutOrStdout(), "已留言。")
			return nil
		},
	}
	ask := &cobra.Command{
		Use:   "ask <text>",
		Short: "Ask a question and wait for a human answer",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx, err := FindContext(".", sessionID)
			if err != nil {
				return exit(cmd, ExitRefused, err)
			}
			message, code, postErr := NewClient(ctx).PostMessage(args[0], "question")
			if postErr != nil {
				return exit(cmd, code, postErr)
			}
			if asJSON {
				return writeJSON(cmd, message)
			}
			// Said plainly, because the next thing the agent does depends on it: the
			// answer will not be pushed, and nobody may reply at all.
			fmt.Fprintln(cmd.OutOrStdout(),
				"已提問。用 `cliora task messages` 拉取回覆；24 小時無人回覆這張卡會退回「阻塞」。")
			return nil
		},
	}
	var since string
	messages := &cobra.Command{
		Use:   "messages",
		Short: "Read this card's conversation",
		RunE: func(cmd *cobra.Command, _ []string) error {
			ctx, err := FindContext(".", sessionID)
			if err != nil {
				return exit(cmd, ExitRefused, err)
			}
			items, code, listErr := NewClient(ctx).ListMessages(since)
			if listErr != nil {
				return exit(cmd, code, listErr)
			}
			if asJSON {
				return writeJSON(cmd, items)
			}
			for _, item := range items {
				fmt.Fprintf(cmd.OutOrStdout(), "[%s] %s: %s\n",
					item.CreatedAt, item.Author, item.Body)
			}
			return nil
		},
	}
	messages.Flags().StringVar(&since, "since", "", "only messages after this timestamp")

	var attachMessage string
	attach := &cobra.Command{
		Use:   "attach <file>",
		Short: "Attach a file to this run's card",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx, err := FindContext(".", sessionID)
			if err != nil {
				return exit(cmd, ExitRefused, err)
			}
			artifact, code, attachErr := NewClient(ctx).Attach(args[0], attachMessage)
			if attachErr != nil {
				// Never silent. A quota refusal that printed nothing would let an
				// agent believe its work was delivered right up until the run
				// directory was reclaimed.
				return exit(cmd, code, attachErr)
			}
			if asJSON {
				return writeJSON(cmd, artifact)
			}
			fmt.Fprintf(cmd.OutOrStdout(), "已附加 %s（%d bytes）。\n",
				artifact.Filename, artifact.Size)
			return nil
		},
	}
	attach.Flags().StringVar(&attachMessage, "message", "", "a message to post alongside the file")

	task.AddCommand(say, ask, messages, attach)

	// --- V2.4: what happened, what the checks said, and what was observed (DV-06) ---
	//
	// **Three writes and no reads.** An agent does not need to read back what it just
	// wrote, and every read endpoint is another surface to authorize — the same
	// restraint that keeps `approve` out of this tool.
	//
	// **And there is no `--force` here, and there will not be.** Skipping a card's
	// completion criteria is an administrator's act with a permanent mark on the card;
	// a subcommand that existed would invite an agent to try it, and what came back
	// would be a 403 it then had to interpret.
	plan := &cobra.Command{Use: "plan", Short: "This run's execution plan"}
	plan.AddCommand(&cobra.Command{
		Use:   "snapshot <file>",
		Short: "Record a version of the plan (JSON: {note, steps})",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx, err := FindContext(".", sessionID)
			if err != nil {
				return exit(cmd, ExitRefused, err)
			}
			payload, readErr := readJSONFile(args[0])
			if readErr != nil {
				return exit(cmd, ExitRefused, readErr)
			}
			out, code, postErr := NewClient(ctx).RecordPlan(payload)
			if postErr != nil {
				return exit(cmd, code, postErr)
			}
			if asJSON {
				return writeJSON(cmd, out)
			}
			fmt.Fprintln(cmd.OutOrStdout(), "已記錄執行計畫。改寫時記得附上 note 說明原因。")
			return nil
		},
	})

	verify := &cobra.Command{Use: "verify", Short: "This run's verification report"}
	verify.AddCommand(&cobra.Command{
		Use:   "report <file>",
		Short: "Submit a verification report (JSON)",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx, err := FindContext(".", sessionID)
			if err != nil {
				return exit(cmd, ExitRefused, err)
			}
			payload, readErr := readJSONFile(args[0])
			if readErr != nil {
				return exit(cmd, ExitRefused, readErr)
			}
			out, code, postErr := NewClient(ctx).SubmitVerification(payload)
			if postErr != nil {
				return exit(cmd, code, postErr)
			}
			if asJSON {
				return writeJSON(cmd, out)
			}
			// Said plainly, and the second sentence matters more than the first: the
			// agent can *see* a verification command list on the card, so it has to be
			// told it cannot change one — otherwise it spends a `task.update` finding
			// out. Not trying is cheaper than being refused.
			fmt.Fprintln(cmd.OutOrStdout(),
				"已提交驗證報告（記為「Agent 自述」）。\n"+
					"平台自己執行的驗證由專案設定或卡片上的宣告決定，而那兩處你都改不了。")
			return nil
		},
	})

	evidence := &cobra.Command{Use: "evidence", Short: "What this run observed"}
	evidence.AddCommand(&cobra.Command{
		Use:   "add <finding|limitation|risk> <file>",
		Short: "Record an observation (JSON payload)",
		Args:  cobra.ExactArgs(2),
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx, err := FindContext(".", sessionID)
			if err != nil {
				return exit(cmd, ExitRefused, err)
			}
			kind, ok := evidenceKinds[args[0]]
			if !ok {
				// Refused here rather than by the server, because the server's answer
				// would be a 403 about a kind this tool should never have offered.
				return exit(cmd, ExitRefused,
					fmt.Errorf("類型只能是 finding、limitation 或 risk"))
			}
			payload, readErr := readJSONFile(args[1])
			if readErr != nil {
				return exit(cmd, ExitRefused, readErr)
			}
			out, code, postErr := NewClient(ctx).AddEvidence(kind, payload)
			if postErr != nil {
				return exit(cmd, code, postErr)
			}
			if asJSON {
				return writeJSON(cmd, out)
			}
			fmt.Fprintln(cmd.OutOrStdout(), "已記錄。")
			return nil
		},
	})

	root.AddCommand(context, task, plan, verify, evidence)
	return root
}

// evidenceKinds maps what an agent may say to what the platform stores.
//
// The three machine kinds are deliberately absent: the platform refuses them anyway,
// and a tool that can express something always refused is worse than one that cannot
// express it.
var evidenceKinds = map[string]string{
	"finding":    "agent_finding",
	"limitation": "agent_limitation",
	"risk":       "agent_risk",
}

// readJSONFile reads a JSON document an agent produced.
//
// A file rather than an argument, for the reason SEC-002 gives about argv generally:
// a report is long, structured, and belongs on a stream rather than in a process's
// command line where it lands in `ps` output.
func readJSONFile(path string) (map[string]any, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("讀不到 %s：%w", path, err)
	}
	var payload map[string]any
	if err := json.Unmarshal(raw, &payload); err != nil {
		return nil, fmt.Errorf("%s 不是合法的 JSON 物件：%w", path, err)
	}
	return payload, nil
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
