# 02 — P2-W2：Runtime Launcher、tmux Ownership 與 Recovery

對應 `research/01/03-phase-2-session-terminal.md` §P2-W2。涵蓋 ticket **P2-01**（P0 recovery blocker spike，**Gate-0**）、**P2-07**（daemon session lifecycle + launcher + tmux）、**P2-08**（daemon restart reconciliation）。需求：FR-SESSION-001/005/006、FR-RUNTIME-002/003、FR-WORKSPACE-003、SEC-001/002/007、ADR 0004。相關技能：`go-daemon-development`、`terminal-websocket-protocol`。

## 現況（P2 起點）

- **dispatch 只在 dev relay**：真正的 control 分派、`boundedWriter`（4 MiB/512 frames、`QUEUE_OVERFLOW`）、`response()`（echo request_id）、`stable()`（error code allowlist）都在 `daemon/cmd/agentd/dispatcher.go serve()`。**production 連線 `daemon/internal/connection/connection.go` 的 `readLoop` 目前只讀取並丟棄所有 inbound frame**（註解：「session/terminal frames arrive in P2」）。把 dispatch 接進 production 連線是 P2-W2 的核心整合點。
- **session manager 存在但受限**：`internal/session/manager.go` 的 `Manager` 只有單一 `workspace string` 供所有 session 共用；`Start` 直接把 `m.workspace` 傳給 `ctmux.StartSpec.Workspace`；wire `startPayload` 帶 `WorkspaceID`/`workspace` 但目前被忽略。`internal/tmux/client.go` 以 `cliora-<uuid>` 命名並把 workspace 當 `-c` cwd（僅拒空）。`internal/terminal/process.go` 為 PTY wrapper（`creack/pty`）。
- **runtime adapters 已可偵測**：`internal/runtime`（claude/codex 偵測 + allowlist），P1 只偵測/回報；P2 才真正 `BuildCommand` 啟動。
- **config 已具輸入**：`internal/config` 的 `WorkspaceConfig{AllowedRoots, ExcludedPatterns}`（validate 要求絕對路徑）。

## P2-01：P0 Recovery Blocker Spike（Gate-0，硬性前置）

**背景**：P0 exit 為 No-Go，唯一 blocker 是「browser/daemon 中斷後殘留的 `tmux attach` client 使 recovered daemon 到達 `Exists`/`Capture` 後，於啟動替換 PTY attach 時阻塞；`detach-client`、`attach-session -d`、非阻塞 PTY cancel 均已試仍可重現」（`docs/p0-report.md`、ADR 0004）。P1 report 明列此 blocker「必須在 P2 開工前以獨立 spike 關閉」。

**任務**：

- 建立 process-level 隔離整合測試（`-tags integration`，沿用 `internal/session/integration_test.go` 以真實 `fakecli`+tmux 的模式），重現孤兒 attach client 與 recovered attach 阻塞。
- 定位 `creack/pty.StartWithSize(tmux attach)` 產生的 orphan client/process 關係，於兩方案擇一並實作：
  1. **tmux control-mode pipe bridge**（`tmux -CC`/`control` 模式，daemon 以 pipe 收發，不再對每次 reattach 起新的 `attach-session` PTY client），或
  2. **attach subprocess-group cleanup**（attach client 置於獨立 process group，reattach 前確保前一 client 完全回收）。
- 決策記 **ADR 0012**（recovery/attach 模型），並更新 ADR 0004。

驗收（Gate-0，未過不得進入其餘 wave）：rapid reattach（連續斷線 ≥20 次）與 **cross-process daemon-restart recovery** 皆無 leaked attach client、無 goroutine/PTY leak，且 recovered attach 後 `session.stop` 能正常收尾；tmux session 與 Fake CLI 全程存活。

## P2-07：Daemon Session Lifecycle、Launcher 與 tmux Ownership

**接上 production dispatch**：把 `serve()` 的分派抽成可共用的 handler（`internal/session` 或新 `internal/control`），於 `connection.go` 的 read owner 呼叫；text frame → `protocol.DecodeControl` + `protocol.ValidateControl`，binary frame（kind=1 input）→ `manager.Input`；回應經單一 write owner（`writeMu`）序列化，沿用 `boundedWriter` 語意。

**新增/驗證的 control handler**：`session.start`、`session.stop`、`session.list`、`session.recover`（回應對應 `*.started/start_failed/stopped/list_result/status_changed`）；`terminal.resize`（沿用 P0）。新增的 message type 需先加入 `protocol/codec.go` 的 `allowedTypes`、`ValidateControl` 的 payload case，以及 `stable()` 的 error code allowlist（P2-03 契約凍結）。

**Runtime allowlist launcher**（SEC-002、FR-RUNTIME-003）：由 `internal/runtime` 的 adapter 以 runtime ID 建 **allowlisted argv**（daemon 決定 binary 與參數；**絕不接受 Central/前端傳入的 command/argv/shell string**）；缺 runtime/不可執行分別回 `RUNTIME_NOT_FOUND`/`RUNTIME_NOT_EXECUTABLE`。

**每 session workspace**（FR-WORKSPACE-003、SEC-001）：`Manager` 改為 per-session 保存 workspace（不再單一共用欄位）；`session.start` 前**重做 canonical validation**——非空、拒 null byte、absolute、clean、`EvalSymlinks`（target 與 root 皆解析）、`filepath.Rel` 判斷仍在某 allowed root 內（不得用 `strings.HasPrefix`）、regular directory 且可讀。驗證失敗回 `WORKSPACE_OUTSIDE_ALLOWED_ROOT`/`WORKSPACE_NOT_FOUND`/`WORKSPACE_PERMISSION_DENIED`。（此為 launch-time 驗證；完整檔案瀏覽 guard 於 P3。）

**tmux 命名/metadata**：session 以 Central 生成的 UUID 命名 `cliora-<lowercase uuid>`（沿用 P0）；於 tmux session option 或本地 metadata 保存足以 restart 掃描 reconcile 的資訊（session_id、runtime、workspace、rows/columns、建立時間）。

**Terminate policy**（FR-SESSION-005）：`session.stop` 先送 graceful signal，等待 graceful 窗（初值 10s），未結束送 force kill，最後回 `session.stopped` 帶結果；有明確 timeout 與 process/PTY/goroutine ownership，取消時等待結束不遺留孤兒。

**exit code**：依 ADR 0004/P2-02 決策，於 reap 前查 `#{pane_dead_status}` 取真實 exit code；不可行則沿用 attach client 狀態並明確標記為已知限制。

驗收（`go test -race`，含 `-tags integration` 對真實 tmux/Fake CLI）：start/attach/terminate/exit/resize；invalid workspace（`../`、absolute escape、prefix collision、symlink chain、broken link、null byte）全拒；runtime 缺失/不可執行；graceful→force terminate；process failure；併發 start/stop race；**任意 command/argv 注入嘗試被 allowlist 擋下**。日常 integration 用 Fake CLI，真實 Claude/Codex 僅 isolated smoke。

## P2-08：Daemon Restart Reconciliation

- daemon（re）啟動後掃描 `cliora-<uuid>` 命名的 tmux session，讀回本地/tmux metadata，與 Central 對帳：Central 已知且仍存活 → 回報存活並可 reattach；Central 未知或已終態 → 依 policy 清理或標記孤兒（不盲目 kill 使用者工作）。
- 以 `session.status_changed` 主動通知 Central 狀態變化（RUNNING/EXITED/DISCONNECTED）；Central 據以更新 `terminal_sessions.status`（P2-05 的 daemon-triggered transition 來源）。
- 沿用 ADR 0004：reattach 以 `capture-pane` 取最新 bounded snapshot（上限 2 MiB），截斷送 `terminal.gap{reattach_boundary}`；attach 切換期間序列化 capture 與 live subscription。

驗收（integration，`-race`）：daemon restart 後既有 session 被正確 reconcile 並可 reattach；孤兒 session 依 policy 處置且不誤殺；`status_changed` 序列與 Central 狀態一致；連續 restart 無 leaked client（延續 P2-01 的 Gate 條件）。
