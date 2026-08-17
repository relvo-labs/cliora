package cli

import (
	_ "embed"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"time"

	"github.com/spf13/cobra"
)

// The specification skeleton `cliora spec template` prints, adapted from Monstrare's
// `ai/templates/feature-spec.md` (MIT; see ADR 0034 §7 and the attribution there).
//
// **Embedded rather than sent in the context pack.** The template is ~2.5 KB and the
// clarification pack has a 6 KB budget shared with the requirement text and the current
// draft; a third of it spent on a form the agent can fetch locally is a third the draft
// does not get. Embedded rather than read from disk because a run directory contains no
// copy of Monstrare.
//
//go:embed spec_template.json
var specTemplate []byte

// PayloadSurvivedMessage is appended when one of V2.5's three file-carrying writes
// fails.
//
// The three payloads below took the agent real work to produce, unlike a one-line
// message where retyping costs nothing. **Without this sentence the agent regenerates a
// different draft on the retry** — and two drafts of one specification, one of them
// never seen, is worse than the failure was.
//
// A constant rather than three literals so that a test can assert the promise without
// executing a command: `exit` calls `os.Exit`, so the failure path is not reachable from
// a test binary (`RunOfflineMessage` is asserted the same way).
const PayloadSurvivedMessage = "內容還在 %s 裡，沒有遺失。恢復連線後用同一個檔案再執行一次。"

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
	var sayReplyTo string
	var sayKind string
	say := &cobra.Command{
		Use:   "say <text>",
		Short: "Post a message on this run's card",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx, err := FindContext(".", sessionID)
			if err != nil {
				return exit(cmd, ExitRefused, err)
			}
			// Local half of a server rule, in the shape `ask` already uses: the gate is
			// the server's 403, and this exists to say the *reason* rather than to
			// enforce anything. An agent has a shell and a readable token file.
			if sayKind == "decision" {
				return exit(cmd, ExitRefused, errors.New(
					"decision 是人的動作：接受或退回一份提案需要核准權限，"+
						"而執行憑證永遠沒有它。\n"+
						"把內容用 `cliora task propose-spec` 送成提案，交由人決定。"))
			}
			message, code, postErr := NewClient(ctx).PostMessage(args[0], sayKind, sayReplyTo)
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
	say.Flags().StringVar(&sayReplyTo, "reply-to", "", "the message this replies to")
	say.Flags().StringVar(&sayKind, "kind", "comment", "comment|answer")
	ask := &cobra.Command{
		Use:   "ask <text>",
		Short: "Ask a question and wait for a human answer",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx, err := FindContext(".", sessionID)
			if err != nil {
				return exit(cmd, ExitRefused, err)
			}
			client := NewClient(ctx)
			// The local half of "one question at a time" (V2.5, ADR 0034 §4). **A
			// hint, not the gate** — the gate is the server's 409, because an agent
			// has a shell and a readable token file. This saves a round trip and
			// prints the question still waiting, which a 409 body cannot do as well.
			if pending, waiting := client.PendingQuestion(); waiting {
				return exit(cmd, ExitRefused, fmt.Errorf(
					"上一個問題還沒有答案：「%s」\n"+
						"要問新的：把兩個問題合併成一則，或先 `cliora task messages` 看看有沒有回覆。",
					pending))
			}
			message, code, postErr := client.PostMessage(args[0], "question", "")
			if postErr != nil {
				return exit(cmd, code, postErr)
			}
			if asJSON {
				return writeJSON(cmd, message)
			}
			// Three options, and **the first one is the recommendation**, for the same
			// reason `render_run_context` puts "how to report" first: the thing most
			// likely to go wrong is not the agent misunderstanding, it is the agent not
			// knowing an option exists. Holding a process open for a day used to be the
			// only way to keep a conversation alive; since V2-C1 it is the worst one.
			fmt.Fprintf(cmd.OutOrStdout(),
				"已提問。你可以：\n"+
					"  ① 直接結束這個行程——人回覆之後，平台會用新的一輪把你叫回來（建議）\n"+
					"  ② `cliora task wait --after %d --timeout 120` 等最多兩分鐘\n"+
					"  ③ `cliora task messages --after %d` 自己輪詢\n"+
					"24 小時無人回覆，這張卡會退回「阻塞」。\n",
				message.Seq, message.Seq)
			return nil
		},
	}
	var since string
	var afterSeq int
	var messageLimit int
	messages := &cobra.Command{
		Use:   "messages",
		Short: "Read this card's conversation",
		RunE: func(cmd *cobra.Command, _ []string) error {
			ctx, err := FindContext(".", sessionID)
			if err != nil {
				return exit(cmd, ExitRefused, err)
			}
			// Refused locally rather than resolved: guessing which cursor the caller
			// meant is worse than saying no, and the server refuses the same pair.
			if since != "" && afterSeq >= 0 {
				return exit(cmd, ExitRefused, errors.New(
					"--after 與 --since 只能給一個。--since 會在下一版移除。"))
			}
			if since != "" {
				fmt.Fprintln(cmd.ErrOrStderr(),
					"--since 會在下一版移除，改用 --after <seq>；每則訊息的 seq 在 --json 輸出裡。")
			}
			page, code, listErr := NewClient(ctx).ListMessages(afterSeq, since, messageLimit)
			if listErr != nil {
				return exit(cmd, code, listErr)
			}
			if asJSON {
				return writeJSON(cmd, page)
			}
			for _, item := range page.Items {
				// The seq leads, because it is the value the next `--after` needs.
				fmt.Fprintf(cmd.OutOrStdout(), "[%4d] %s %s: %s\n",
					item.Seq, item.CreatedAt, authorLabel(item), item.Body)
			}
			return nil
		},
	}
	messages.Flags().StringVar(&since, "since", "", "deprecated: only messages after this timestamp")
	messages.Flags().IntVar(&afterSeq, "after", -1, "only messages after this sequence number")
	messages.Flags().IntVar(&messageLimit, "limit", 0, "how many messages at most")

	var waitAfter int
	var waitTimeout int
	wait := &cobra.Command{
		Use:   "wait",
		Short: "Wait a short while for new messages on this card",
		RunE: func(cmd *cobra.Command, _ []string) error {
			ctx, err := FindContext(".", sessionID)
			if err != nil {
				return exit(cmd, ExitRefused, err)
			}
			if time.Duration(waitTimeout)*time.Second > WaitTimeoutMax {
				// The ceiling is the point of the command rather than a limit on it, so
				// the refusal names the better option instead of just the number.
				return exit(cmd, ExitRefused, fmt.Errorf(
					"--timeout 上限是 %d 秒。要等更久，就結束這個行程——"+
						"人回覆之後平台會用新的一輪把你叫回來，對話不會遺失。",
					int(WaitTimeoutMax.Seconds())))
			}
			page, code, waitErr := NewClient(ctx).WaitMessages(
				waitAfter, time.Duration(waitTimeout)*time.Second)
			if waitErr != nil {
				return exit(cmd, code, waitErr)
			}
			if code == ExitTimeout {
				// Not an error, and it prints nothing: "nothing yet" is a normal answer
				// and an agent should be able to tell it from a refusal by the code.
				return exit(cmd, ExitTimeout, nil)
			}
			if asJSON {
				return writeJSON(cmd, page)
			}
			for _, item := range page.Items {
				fmt.Fprintf(cmd.OutOrStdout(), "[%4d] %s %s: %s\n",
					item.Seq, item.CreatedAt, authorLabel(item), item.Body)
			}
			return nil
		},
	}
	wait.Flags().IntVar(&waitAfter, "after", -1, "wait for messages after this sequence number")
	wait.Flags().IntVar(&waitTimeout, "timeout", 30, "seconds to wait, at most 120")

	proposeSpec := &cobra.Command{
		Use:   "propose-spec <file|->",
		Short: "Propose a specification on this card, for a person to accept",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx, err := FindContext(".", sessionID)
			if err != nil {
				return exit(cmd, ExitRefused, err)
			}
			body, readErr := readTextOrStdin(cmd, args[0])
			if readErr != nil {
				return exit(cmd, ExitRefused, readErr)
			}
			message, code, postErr := NewClient(ctx).ProposeSpec(string(body))
			if postErr != nil {
				return exit(cmd, code, postErr)
			}
			if asJSON {
				return writeJSON(cmd, message)
			}
			// Says what it is *not*, because that is the half an agent gets wrong: a
			// proposal changes no readiness and passes no gate.
			fmt.Fprintln(cmd.OutOrStdout(),
				"已提出規格提案。這不會改變卡片的就緒狀態——要由人接受才算數。")
			return nil
		},
	}

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

	task.AddCommand(say, ask, messages, wait, proposeSpec, attach)

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

	// --- V2.5: what a requirement-driven run writes (ADR 0034 §2) ---
	//
	// Three writes and one read. The read is the exception to the write-only restraint
	// above, and it earns it: the context pack is a dispatch-time snapshot, so a run
	// that has already submitted two versions cannot otherwise see them — and it is
	// invoked statelessly, so it does not remember.
	//
	// **Still no `approve` and no `accept`.** Same reason as `--force`: a subcommand
	// that exists invites an attempt, and the answer would be a 401 to interpret.
	spec := &cobra.Command{Use: "spec", Short: "This requirement's specification"}
	spec.AddCommand(&cobra.Command{
		Use:   "template",
		Short: "Print an empty specification (no network)",
		RunE: func(cmd *cobra.Command, _ []string) error {
			// No client, no dial: it is a constant. Usable while Central is down and
			// before a run has done anything.
			_, err := cmd.OutOrStdout().Write(specTemplate)
			return err
		},
	})
	spec.AddCommand(&cobra.Command{
		Use:   "submit <file>",
		Short: "Submit a version of this requirement's specification (JSON)",
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
			out, code, postErr := NewClient(ctx).SubmitSpec(payload)
			if postErr != nil {
				// The payload took the agent real work to produce, unlike a one-line
				// message. Saying the file survived is what stops it regenerating a
				// different draft on the retry.
				return exit(cmd, code, fmt.Errorf("%w\n"+PayloadSurvivedMessage, postErr, args[0]))
			}
			if asJSON {
				return writeJSON(cmd, out)
			}
			fmt.Fprintln(cmd.OutOrStdout(),
				"已送出一版規格草稿。\n"+
					"規格由人核准，你核准不了——不知道的就留在 open_questions 裡，那正是它存在的理由。")
			return nil
		},
	})

	proposal := &cobra.Command{Use: "proposal", Short: "This requirement's decomposition"}
	proposal.AddCommand(&cobra.Command{
		Use:   "submit <file>",
		Short: "Submit a decomposition proposal (JSON: {epics, user_stories, tasks})",
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
			tree, ok := payload["tree"].(map[string]any)
			if !ok {
				// Accept both shapes: the file may be the tree itself or `{tree: …}`.
				// Guessing wrong here costs a round trip and an error about a field the
				// agent believes it sent.
				tree = payload
			}
			out, code, postErr := NewClient(ctx).SubmitProposal(tree)
			if postErr != nil {
				return exit(cmd, code, fmt.Errorf("%w\n"+PayloadSurvivedMessage, postErr, args[0]))
			}
			if asJSON {
				return writeJSON(cmd, out)
			}
			// The three counts land in the run log **before** anybody opens the accept
			// screen, which is the earliest place the scale of a decomposition is
			// visible.
			fmt.Fprintf(cmd.OutOrStdout(),
				"已送出提案：%d 個 Epic、%d 個 User Story、%d 張 Task。\n"+
					"人會逐張勾選；缺就緒條件的會落在「待辦」而不是「就緒」。\n",
				countIn(tree, "epics"), countIn(tree, "user_stories"), countIn(tree, "tasks"))
			return nil
		},
	})

	patch := &cobra.Command{Use: "patch", Short: "Propose an edit to a document"}
	patch.AddCommand(&cobra.Command{
		Use:   "propose <file>",
		Short: "Propose a document edit (JSON: {target_path, diff, sections, reason})",
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
			out, code, postErr := NewClient(ctx).ProposePatch(payload)
			if postErr != nil {
				return exit(cmd, code, fmt.Errorf("%w\n"+PayloadSurvivedMessage, postErr, args[0]))
			}
			if asJSON {
				return writeJSON(cmd, out)
			}
			fmt.Fprintln(cmd.OutOrStdout(),
				"已送出文件修訂提案。**平台只渲染與記錄決定，不會套用**——"+
					"人接受之後，套用是一張走 pull_request 的正常卡片。")
			return nil
		},
	})

	requirement := &cobra.Command{Use: "requirement", Short: "What this run is working on"}
	requirement.AddCommand(&cobra.Command{
		Use:   "show",
		Short: "Print this card's requirement, its latest spec and its open questions",
		RunE: func(cmd *cobra.Command, _ []string) error {
			ctx, err := FindContext(".", sessionID)
			if err != nil {
				return exit(cmd, ExitRefused, err)
			}
			out, code, getErr := NewClient(ctx).ShowRequirement()
			if getErr != nil {
				return exit(cmd, code, getErr)
			}
			if asJSON {
				return writeJSON(cmd, out)
			}
			fmt.Fprintf(cmd.OutOrStdout(), "%s [%s]\n%s\n", out.CardRef, out.Status, out.RawText)
			fmt.Fprintf(cmd.OutOrStdout(), "規格版本：%d\n", len(out.Specs))
			for _, question := range out.Blocking {
				fmt.Fprintf(cmd.OutOrStdout(), "  未解決：%s\n", question)
			}
			return nil
		},
	})

	root.AddCommand(context, task, plan, verify, evidence, spec, proposal, patch, requirement)
	return root
}

// countIn is how many nodes a proposal tree holds at one level.
func countIn(tree map[string]any, key string) int {
	items, ok := tree[key].([]any)
	if !ok {
		return 0
	}
	return len(items)
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

// readTextOrStdin reads a proposal body. A file or `-`, never an argument, for the
// reason SEC-002 gives about argv generally: a specification is long and belongs on a
// stream rather than in `ps` output.
func readTextOrStdin(cmd *cobra.Command, path string) ([]byte, error) {
	if path == "-" {
		return io.ReadAll(cmd.InOrStdin())
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("讀不到 %s：%w", path, err)
	}
	return raw, nil
}

// authorLabel names the speaker the way the thread does: a runner by its name, a
// person as "人". A uuid tells a reader nothing.
func authorLabel(item Message) string {
	if item.Author == "agent" && item.RunnerName != "" {
		return item.RunnerName
	}
	switch item.Author {
	case "agent":
		return "agent"
	case "system":
		return "系統"
	default:
		return "人"
	}
}

// exit prints the message and stops with the right code.
//
// `ExitUnreachable` is separated from `ExitRefused` so an agent can tell "the platform
// is down, carry on" from "the platform said no, read this" — the distinction D14's
// second sentence exists to make.
func exit(cmd *cobra.Command, code int, err error) error {
	// `task wait` reaching its ceiling passes nil: "nothing yet" is a normal answer, and
	// printing an error for it would teach an agent to treat waiting as failure.
	if err != nil {
		fmt.Fprintln(cmd.ErrOrStderr(), err.Error())
	}
	os.Exit(code)
	return nil
}

func writeJSON(cmd *cobra.Command, value any) error {
	encoder := json.NewEncoder(cmd.OutOrStdout())
	encoder.SetIndent("", "  ")
	return encoder.Encode(value)
}
