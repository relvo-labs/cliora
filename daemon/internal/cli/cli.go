// Package cli is the `cliora` tool an agent runs inside a session (TK-08, ADR 0028).
//
// **It is the same binary as agentd**, dispatched on argv[0] or reached as
// `agentd cliora …`. Three facts forced that and none of them is preference: a Go
// binary is far over the 4 MiB single-file ceiling the projection path allows,
// `.cliora/` is closed to the user-facing write verb, and the updater extracts exactly
// one archive member by name — widening a deliberately minimal tar extractor to ship a
// second file would trade a hardened surface for a convenience.
//
// The pleasant consequence is that D11's "MCP needs a stable executable path" is
// already true in V2.1: the path is wherever agentd lives, and the version can never
// disagree with the daemon's.
//
// Two properties matter more than any command here:
//
//  1. `context show` **reads a local file and never dials**. When Central is down the
//     agent still knows what it is working on — that is the premise D14 accepted
//     "fail immediately, no queue" on.
//  2. Everything else fails **immediately and loudly**, with a message that says the
//     session can keep working. Without that sentence an agent reads a failed status
//     update as "I cannot continue", and stopping is a far worse outcome than an
//     unrecorded lane change.
package cli

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"
)

// ExitCode values are part of the contract with whatever runs the CLI.
//
// Two rather than one, because the two situations need different reactions: a refused
// request is something the agent should read and act on, while an unreachable platform
// is something it should ignore and carry on through.
const (
	ExitOK          = 0
	ExitRefused     = 1
	ExitUnreachable = 2
)

// OfflineMessage is the exact text D14 asks for, and the second line is the whole
// point of it: the platform being down does not stop the agent working. It is produced
// here rather than passed through from an HTTP error, because an agent shown a raw
// transport error concludes something much worse than the truth.
const OfflineMessage = `無法連線到 Cliora（Session 可繼續工作）。
你的變更未被記錄，恢復連線後請重新執行。`

// Context is what a session's projection left in the workspace.
type Context struct {
	SessionID string
	Dir       string // the `.cliora` directory that was found
	PackPath  string
	TokenPath string
	Token     string
	APIBase   string
}

// FindContext walks up from `start` looking for `.cliora/context/`.
//
// Upwards, because an agent spends most of its time in a subdirectory of the
// workspace; the search stops at the filesystem root or when a `.cliora` is found —
// whichever comes first — so it can never wander into another project's context.
func FindContext(start string, session string) (Context, error) {
	dir, err := filepath.Abs(start)
	if err != nil {
		return Context{}, err
	}
	for {
		candidate := filepath.Join(dir, ".cliora", "context")
		if entries, readErr := os.ReadDir(candidate); readErr == nil {
			return contextFrom(candidate, entries, session)
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			return Context{}, errors.New(
				"找不到 .cliora/context/：這個目錄不在一個有任務情境的 Session 工作區裡")
		}
		dir = parent
	}
}

func contextFrom(dir string, entries []os.DirEntry, session string) (Context, error) {
	ids := map[string]bool{}
	for _, entry := range entries {
		name := entry.Name()
		if strings.HasSuffix(name, ".md") {
			ids[strings.TrimSuffix(name, ".md")] = true
		}
	}
	if len(ids) == 0 {
		return Context{}, errors.New("找不到任務情境包")
	}
	chosen := session
	if chosen == "" {
		if len(ids) > 1 {
			// Ambiguity is answered by asking, never by guessing: picking the newest
			// would silently attach an agent's report to another session's card.
			names := make([]string, 0, len(ids))
			for id := range ids {
				names = append(names, id)
			}
			return Context{}, fmt.Errorf(
				"這個工作區有多個 Session 的情境包，請用 --session 指定其中一個：%s",
				strings.Join(names, ", "))
		}
		for id := range ids {
			chosen = id
		}
	}
	if !ids[chosen] {
		return Context{}, fmt.Errorf("找不到 Session %s 的情境包", chosen)
	}
	ctx := Context{
		SessionID: chosen,
		Dir:       filepath.Dir(dir),
		PackPath:  filepath.Join(dir, chosen+".md"),
		TokenPath: filepath.Join(dir, chosen+".token"),
	}
	if raw, err := os.ReadFile(ctx.TokenPath); err == nil {
		ctx.Token = strings.TrimSpace(string(raw))
	}
	ctx.APIBase = apiBaseFrom(ctx.PackPath)
	return ctx, nil
}

// apiBaseFrom reads the API address out of the context pack.
//
// From the pack rather than from the daemon's config file: the CLI runs as the user
// inside a session, and assuming it can read a service's configuration would be
// assuming a permission it has no reason to hold.
func apiBaseFrom(packPath string) string {
	raw, err := os.ReadFile(packPath)
	if err != nil {
		return ""
	}
	for _, line := range strings.Split(string(raw), "\n") {
		if idx := strings.Index(line, "API："); idx >= 0 {
			return strings.TrimSpace(line[idx+len("API："):])
		}
	}
	return ""
}

// ShowContext prints the pack. **No network, by design** (D14).
func ShowContext(out io.Writer, ctx Context) (int, error) {
	raw, err := os.ReadFile(ctx.PackPath)
	if err != nil {
		return ExitRefused, err
	}
	_, _ = out.Write(raw)
	return ExitOK, nil
}

// Client talks to Central with a session credential.
type Client struct {
	Base    string
	Token   string
	HTTP    *http.Client
	Timeout time.Duration
}

func NewClient(ctx Context) *Client {
	return &Client{
		Base:  strings.TrimRight(ctx.APIBase, "/"),
		Token: ctx.Token,
		HTTP:  &http.Client{Timeout: 10 * time.Second},
	}
}

type apiError struct {
	Error struct {
		Code    string         `json:"code"`
		Message string         `json:"message"`
		Details map[string]any `json:"details"`
	} `json:"error"`
}

// do performs one request and turns every failure into something an agent can act on.
//
// The split is the design: a transport failure is `ExitUnreachable` plus
// `OfflineMessage`, and everything else is `ExitRefused` plus a sentence that says
// what to do next. A raw `502 Bad Gateway` tells an agent nothing it can use.
func (c *Client) do(method, path string, body any, into any) (int, error) {
	if c.Base == "" || c.Token == "" {
		return ExitUnreachable, errors.New(OfflineMessage)
	}
	var payload io.Reader
	if body != nil {
		encoded, err := json.Marshal(body)
		if err != nil {
			return ExitRefused, err
		}
		payload = bytes.NewReader(encoded)
	}
	req, err := http.NewRequest(method, c.Base+path, payload)
	if err != nil {
		return ExitRefused, err
	}
	req.Header.Set("Authorization", "Bearer "+c.Token)
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	resp, err := c.HTTP.Do(req)
	if err != nil {
		return ExitUnreachable, errors.New(OfflineMessage)
	}
	defer func() { _ = resp.Body.Close() }()
	raw, _ := io.ReadAll(resp.Body)
	if resp.StatusCode >= 500 {
		// A server that is up but broken is, from the agent's point of view, the same
		// situation as one that is down: nothing was recorded, and work continues.
		return ExitUnreachable, errors.New(OfflineMessage)
	}
	if resp.StatusCode >= 400 {
		return ExitRefused, errors.New(explain(resp.StatusCode, raw))
	}
	if into != nil {
		if err := json.Unmarshal(raw, into); err != nil {
			return ExitRefused, err
		}
	}
	return ExitOK, nil
}

// explain turns a refusal into the next step, per code.
//
// Written here rather than echoed from the server because the reader is an agent
// deciding what to do next, and "409 Conflict" is not a decision it can make.
func explain(status int, raw []byte) string {
	var parsed apiError
	_ = json.Unmarshal(raw, &parsed)
	switch parsed.Error.Code {
	case "":
		if status == http.StatusUnauthorized {
			return "這個 Session 的憑證已失效（Session 可能已結束）。看板上的紀錄需要由人補上。"
		}
		return fmt.Sprintf("請求被拒絕（HTTP %d）。", status)
	case "TASK_VERSION_CONFLICT":
		return "這張卡剛被別人改過。用 `cliora task get <ref>` 看目前的狀態再試一次。"
	case "TASK_DEPENDENCY_UNSATISFIED":
		blocking := ""
		if details := parsed.Error.Details; details != nil {
			if refs, ok := details["blocking_refs"].([]any); ok {
				parts := make([]string, 0, len(refs))
				for _, ref := range refs {
					parts = append(parts, fmt.Sprint(ref))
				}
				blocking = strings.Join(parts, "、")
			}
		}
		if blocking == "" {
			return "前置任務尚未完成，這張卡還不能推進。"
		}
		return fmt.Sprintf("%s 尚未完成，這張卡還不能推進。", blocking)
	case "FORBIDDEN_FIELD":
		return "這個欄位由人決定，Agent 憑證不能設定它。"
	case "FORBIDDEN":
		return "Review Gate 的核准必須由人在平台上完成；Agent 憑證沒有這個權限。"
	case "TASK_NOT_FOUND":
		return "找不到這張卡（可能不屬於這個 Session 的專案）。"
	}
	if parsed.Error.Message != "" {
		return parsed.Error.Message
	}
	return fmt.Sprintf("請求被拒絕（HTTP %d）。", status)
}

// TaskSummary is the subset of a card the CLI prints.
type TaskSummary struct {
	ID       string `json:"id"`
	CardRef  string `json:"card_ref"`
	Title    string `json:"title"`
	Stage    string `json:"stage"`
	Risk     string `json:"risk"`
	Version  int    `json:"version"`
	Delivery string `json:"delivery"`
}

func (c *Client) ListTasks(stage string) ([]TaskSummary, int, error) {
	path := "/api/cli/tasks"
	if stage != "" {
		path += "?stage=" + stage
	}
	var tasks []TaskSummary
	code, err := c.do(http.MethodGet, path, nil, &tasks)
	return tasks, code, err
}

// GetTask resolves a human reference to a card.
//
// Two round trips by design: `card_ref` is unique only inside a project, so it is a
// query parameter rather than a path segment (`plan/17/03-…md` §3.2). One field with
// two meanings is the shape this codebase keeps refusing.
func (c *Client) GetTask(ref string) (TaskSummary, int, error) {
	var tasks []TaskSummary
	code, err := c.do(http.MethodGet, "/api/cli/tasks?ref="+ref, nil, &tasks)
	if err != nil {
		return TaskSummary{}, code, err
	}
	if len(tasks) == 0 {
		return TaskSummary{}, ExitRefused, fmt.Errorf("找不到 %s", ref)
	}
	return tasks[0], ExitOK, nil
}

type updateResult struct {
	Task     TaskSummary      `json:"task"`
	Warnings []map[string]any `json:"warnings"`
}

// UpdateTask moves a card, carrying the version it was just read at.
func (c *Client) UpdateTask(ref, stage, note string) (TaskSummary, []map[string]any, int, error) {
	current, code, err := c.GetTask(ref)
	if err != nil {
		return TaskSummary{}, nil, code, err
	}
	body := map[string]any{"version": current.Version}
	if stage != "" {
		body["stage"] = stage
	}
	if note != "" {
		// A note lands on the card's links rather than inventing a field: V2.2's
		// message thread is where an agent's prose belongs, and adding a second place
		// for it now would mean two places to read in three months (D24).
		body["links"] = map[string]any{"last_note": note}
	}
	var result updateResult
	code, err = c.do(http.MethodPatch, "/api/cli/tasks/"+current.ID, body, &result)
	if err != nil {
		return TaskSummary{}, nil, code, err
	}
	return result.Task, result.Warnings, ExitOK, nil
}
