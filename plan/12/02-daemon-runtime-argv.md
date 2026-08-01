# 02 — Daemon：啟動參數表與 codex 無沙箱預設（PV-03）

適用 skill：`cliora-project-context` → `go-daemon-development`（「Use typed runtime operations and
allowlisted arguments; never accept arbitrary command strings」正是本檔的中心規則）。

## 1. 設計

### 1.1 參數從哪裡來：一張表，一個布林

```go
// daemon/internal/runtime/launch.go（新檔）

// launchArgs is the complete, closed set of arguments the daemon may add to a
// runtime's argv. It is a compile-time table on purpose: RuntimeConfig has no
// argv field (see config.go's DefaultShellBinary comment), session.start has no
// command/args field (ADR 0021 §1), and neither may grow one. The only thing a
// node operator can do is turn an entry off — see RuntimeConfig.SandboxBypass.
//
// codex: --dangerously-bypass-approvals-and-sandbox disables both the approval
// prompt and the OS sandbox. It is the default because Cliora nodes are
// disposable isolated VMs (ADR 0023 §Context); on a machine that is not, install
// with --no-privileged-terminal and set runtime.codex.sandbox_bypass: false.
var sandboxBypassArgs = map[string][]string{
    "codex": {"--dangerously-bypass-approvals-and-sandbox"},
}
```

| 決定 | 選擇 | 理由 |
|---|---|---|
| 表的位置 | daemon 的 `runtime` 套件，編譯期常數 | 唯一能同時滿足「node 可關」與「沒有人可以指定字串」的位置。設定檔在 node 上、但**內容**由 daemon 決定 |
| node 的控制面 | `runtime.codex.sandbox_bypass: bool`（缺項＝true） | `00-…md` D1／D2 |
| 只有 codex 有條目 | `claude` 與 `shell` 不在表中 | `claude` 的沙箱／核准模型不同，不在本期需求內；`shell` 本來就是使用者自己的 shell，沒有沙箱可談。**表是空的比表有一個猜測的值好** |
| 為什麼是 `map` 而不是散在 `cliRuntime` 建構處 | 一個地方可以 grep、可以測「除了 codex 沒有別人有參數」 | 安全審查（`PV-11`）要能一眼看完所有 daemon 會加的參數 |

### 1.2 `RuntimeConfig` 的新欄位

```go
// daemon/internal/config/config.go

type RuntimeConfig struct {
    Enabled bool   `yaml:"enabled"`
    Binary  string `yaml:"binary"`
    // SandboxBypass turns off the runtime's own sandbox and approval prompts by
    // adding the daemon's fixed flag set for that runtime (runtime/launch.go).
    // Absent → enabled, matching how runtime.shell defaults (ADR 0021): an
    // upgraded node gains the posture without an operator edit, which is a
    // capability change and is why Load records where the value came from.
    //
    // There is deliberately no args/flags field here. The node decides whether
    // the flags apply, never what they are (ADR 0023 §2.4).
    SandboxBypass *bool `yaml:"sandbox_bypass"`
}
```

- `*bool`（不是 `bool`）：要分辨「沒寫」與「明確寫 false」。零值型別會讓「沒寫」變成停用，
  於是每台既有 node 升級後都拿不到使用者要求的預設 —— 與 `TunnelConfig.Enabled` 同一個理由
  （`plan/11/03-…md` §1.1 已經踩過）。
- `Config.SandboxBypassFromDefault map[string]bool`（`yaml:"-"`）：記錄哪些 runtime 的值是預設來的，
  啟動時 log 一行。沿用 `ShellFromDefault` 的作法（`config.go:152`）。
- `Validate`：`sandbox_bypass` 出現在 **`codex` 以外**的 runtime 上 → **明確報錯**
  （`runtime %q does not support sandbox_bypass`）。理由：一個被靜默忽略的設定鍵會讓 node 擁有者
  以為自己關掉了某個東西。`KnownFields(true)` 只擋未知鍵，擋不了「已知鍵放錯位置」。
- `install/plan.go`：產生的初始 config 要**明確寫出** `sandbox_bypass: true` 並在上方掛註解
  （這是什麼、為什麼預設開、關掉的後果、與 `--privileged-terminal` 的關係）。
  沿用 plan/08 的教訓：決定所需的資訊要寫在他會打開的那個檔案裡。

### 1.3 偵測：回報實況，不回報意圖

`DetectResult` 新增兩欄：

```go
type DetectResult struct {
    // …既有欄位…
    // SandboxBypassRequested is what config asked for; SandboxBypass is what the
    // binary will actually get. They differ when the installed CLI does not
    // accept the flag, which is a third-party interface change we must report
    // rather than assume away (ADR 0023, PV-01 #1).
    SandboxBypassRequested bool
    SandboxBypass          bool
}
```

偵測流程（`cliRuntime.Detect`，接在既有 `--version` 之後）：

1. 表中無此 runtime，或 `SandboxBypass` 為 false → `SandboxBypass = false`，結束（**不執行任何額外行程**）。
2. 否則跑一次 `<binary> --help`，`context.WithTimeout(r.timeout)` ＋ `WaitDelay`（與 `--version` 同樣的保護，
   `runtime.go:91-97` 的理由完全適用）。
3. 輸出含該旗標字串 → `SandboxBypass = true`；不含或執行失敗 → `false`，並在 `Reason` 之外
   另記一個可供 `doctor`／log 使用的欄位值 `sandbox_flag_unsupported`。
4. **`Available` 不受影響**：旗標不支援不等於 runtime 不可用（`00-…md` D3）。

| 決定 | 選擇 | 理由 |
|---|---|---|
| 偵測方式 | `--help` 字串比對 | 沒有更好的方法：CLI 不提供旗標查詢。`--version` 不會列旗標，而真的帶旗標跑一次會啟動互動式 session |
| 失敗時的方向 | 往「有沙箱」倒（回報 false） | 兩個方向都會錯，但錯的代價不對稱：回報 false 而實際 bypass → 使用者以為有保護（壞）；回報 true 而實際有沙箱 → 使用者以為沒保護（也壞）。選 false 的理由是它與「旗標沒生效」這個**實際發生的事**一致 —— UI 不該顯示一個沒有發生的事 |
| 頻率 | 跟著既有 `DetectAll`（連線時一次，`connection.go:204`） | 不加新的定時器。codex 被升級後，姿態會在下一次 daemon 重啟／重連時更新，這一點寫進 runbook |

### 1.4 `ResolveBinary` → `ResolveLaunch`

```go
// daemon/internal/runtime/registry.go

// LaunchSpec is the complete launch description for an allowlisted runtime.
// Args comes from the daemon's own table (launch.go); no caller, message or
// config file can contribute a string to it (SEC-002, ADR 0023 §2.4).
type LaunchSpec struct {
    Path string
    Args []string
}

func (r *Registry) ResolveLaunch(id string) (LaunchSpec, error)
```

- **取代** `ResolveBinary`，不並存。兩個入口會變成兩種真相，而其中一個沒有參數。
- 呼叫端：`connection.go:502`（`m.resolveBinary` → `m.resolveLaunch`）、
  `session.Manager.StartSession`（多收一個 `args []string`）、`tmux.StartSpec.Args`。
- `Runtime` interface：`Binary() string` → 保留（`Detect` 用），新增 `LaunchArgs() []string`；
  `BuildCommand` 一併帶上參數（它目前是 P1 遺留的驗證用途，但不能與真正的啟動路徑說不一樣的話）。

### 1.5 tmux 端

```go
// daemon/internal/tmux/client.go
type StartSpec struct {
    // …既有欄位…
    // Args are the daemon-owned launch flags for RuntimeID. They are passed as
    // separate argv elements after Binary; see PV-01 #4 for how tmux interprets
    // multiple shell-command arguments on the versions we support.
    Args []string
}
```

`Start` 的組裝：

```go
argv := append(c.args("new-session", "-d",
    "-x", strconv.Itoa(int(s.Size.Columns)),
    "-y", strconv.Itoa(int(s.Size.Rows)),
    "-s", name, "-c", s.Workspace, s.Binary), s.Args...)
```

驗證要跟著加：`Args` 的每個元素必須符合 `^-{1,2}[A-Za-z0-9][A-Za-z0-9-]*$`（只允許旗標形狀），
否則 `invalid start spec`。這條檢查**不是為了防止呼叫端**（呼叫端是我們自己），而是為了讓
`PV-01` #4 的結論（tmux 可能經過 shell）永遠不會變成一個注入面：一個永遠只含旗標 token 的 `Args`，
在「直接 execvp」與「先組字串交給 shell」兩種解讀下**結果相同**。

## 2. `agentd doctor`

`daemon/cmd/agentd/commands.go` 的 runtime 迴圈（目前在 `commands.go:120-128`）擴充一行：

```text
[ OK ] runtime:codex
[info] runtime:codex sandbox=bypassed flag=--dangerously-bypass-approvals-and-sandbox
```

三種狀態，訊息必須說得出要改哪個檔案：

| 情況 | 輸出 |
|---|---|
| 設定要求且旗標支援 | `[info] runtime:codex sandbox=bypassed`（不是 FAIL，也不是 warn —— 這是設計上的預設狀態） |
| 設定關閉 | `[info] runtime:codex sandbox=enforced (runtime.codex.sandbox_bypass: false)` |
| 設定要求但旗標不支援 | `[warn] runtime:codex sandbox=enforced：此版 codex 不接受 --dangerously-bypass-approvals-and-sandbox（codex 版本 <version>）。平台會顯示「沙箱：啟用」。` |

`[warn]` 不影響 exit code（`commands.go:80-84` 的既有契約）。

## 3. 可觀測性

- 既有 `metrics.DaemonSessionStartTotal` 的標籤是 `{runtime, result}`（`connection.go:520`）。
  **新增一個 `sandbox` 標籤值**（`bypassed`／`enforced`）—— 標籤基數只加 2 倍且非識別性，
  而「這台機器上的 codex session 到底有沒有沙箱」是事後會被問的問題。
- 啟動時 log 一行姿態摘要（`slog.Info("runtime posture", "codex_sandbox", …, "from_default", …)`）。
  `from_default` 是關鍵：它區分「使用者選了這個」與「升級後自動變成這樣」。

## 4. 測試（`daemon/internal/...`，`go test ./...` 與 `-race`）

| 測試 | 斷言 |
|---|---|
| `TestLaunchArgsOnlyCodexHasFlags` | 對 `AllowedRuntimeIDs` 的每個 id 取 `LaunchArgs()`，除 `codex` 外皆為空。**這是「表沒有偷偷長大」的守門測試** |
| `TestResolveLaunchIncludesBypassFlagByDefault` | 缺 `sandbox_bypass` 的 config → `Args` 含該旗標 |
| `TestResolveLaunchOmitsFlagWhenDisabled` | `sandbox_bypass: false` → `Args` 為空 |
| `TestResolveLaunchOmitsFlagWhenUnsupported` | 假 binary 的 `--help` 不含旗標 → `Args` 為空、`DetectResult.SandboxBypass` 為 false、`SandboxBypassRequested` 為 true |
| `TestConfigRejectsSandboxBypassOnNonCodexRuntime` | `runtime.shell.sandbox_bypass: true` → `Load` 報錯 |
| `TestConfigSandboxBypassFromDefaultRecorded` | 缺項時 `SandboxBypassFromDefault["codex"]` 為 true；明寫 `true` 時為 false |
| `TestTmuxStartSpecRejectsNonFlagArgs` | `Args: []string{"; rm -rf /"}`、`Args: []string{"--flag=value with space"}` → `invalid start spec` |
| `TestTmuxStartPassesArgsAsSeparateArgv` | 以 stub `tmux`（既有測試已有此手法）確認 argv 順序：`… -c <ws> <binary> --dangerously-…` |
| `TestDetectHelpProbeDoesNotHang` | `--help` 卡住的假 binary → 在 `timeout` 內回傳（沿用 `TestDetectTimeoutDoesNotHang` 的手法與 `WaitDelay`） |
| `TestStartSessionRecordsSandboxLabel` | metrics 標籤含 `sandbox` |

`daemon/cmd/fakecli/main.go` 要跟著支援：`--help` 印一行含
`--dangerously-bypass-approvals-and-sandbox` 的文字，並在收到該旗標時把
`FAKECLI_READY v1 … sandbox=bypassed` 印出來 —— 這讓 e2e（`scripts/e2e/run-stack.sh`）
可以在**沒有真的 codex** 的機器上驗完整條路徑，包括瀏覽器看到的字。
`--version` 的既有行為（`main.go:18`）不能被 `--help` 的新分支影響。

## 5. 不做的事

- 不新增 `runtime.claude.sandbox_bypass`（claude 的模型不同，需求也沒提）。
- 不讓 `sandbox_bypass` 影響 `Available`（D3）。
- 不把旗標寫進 config 的 `binary` 欄位（`binary: "codex --dangerously-…"`）—— 那會讓
  `exec.LookPath` 失敗，而修法會是「用 shell 包一層」，也就是把 argv 決定權交出去的第一步。
