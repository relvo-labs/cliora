# Cliora P2 可實作規劃（Session 與 Terminal）

本目錄把 `research/01` 的 **Phase 2（Session 與 Terminal）** 轉成可直接建立 ticket、撰寫程式與驗收的執行規格。P2 的產品成果，是讓授權使用者從 Web 在**合法 Workspace** 以 Claude/Codex 建立 session、完整操作原生 CLI（含審批選單、Ctrl+C、Unicode、resize、長輸出），並在**瀏覽器刷新或 Daemon 短暫斷線後安全 reattach**；同一 session 只有一個 writer、其餘 viewer 唯讀，接管需授權、確認並稽核。P2 不實作 workspace 檔案樹與唯讀預覽（P3）、RBAC 完整營運介面與 Dashboard 真實聚合（P4）。

> 命名說明：plan 資料夾編號比 research 的 Phase 編號少 1。`plan/01`=Phase 0（Terminal PoC）、`plan/02`=Phase 1（Node Control Plane），皆已交付。本目錄 `plan/03` 對應 **Phase 2**，ticket 前綴為 `P2-`。

## 前置狀態（P0/P1 已交付）

- **P0**（`docs/p0-report.md`、`plan/01`）交付了本 phase 直接沿用的 Terminal 垂直切片基礎：protocol v1 control/binary frame 與三語言 codec、`tmux`/PTY session manager（`daemon/internal/session`、`internal/tmux`、`internal/terminal`）、per-session `BrowserChannel` byte-aware bounded queue（`backend/app/relay/queue.py`）、xterm 生命週期 composable（`frontend/src/composables/useTerminalSession.ts`）、`StatusBadge` 的 terminal 狀態（connected/reconnecting/gap/exited）與 semantic tokens。P0 的 dispatch 邏輯目前只存在於 dev relay `daemon/cmd/agentd/dispatcher.go serve()`。
- **P1**（`docs/p1-report.md`、`plan/02`）交付了認證 control plane：`/ws/nodes/{node_id}` Ed25519 daemon 連線、`NodeConnectionRegistry`（含 `request()` 的 request_id correlation、pending map、per-node send-lock、timeout；**目前無 production caller**）、RBAC（`services/rbac.py`，含未使用的 session/file action 佔位）、audit（`services/audit.py`）、ws-ticket（60s single-use，`services/ws_ticket.py`）、tz-aware 資料層與 Alembic。
- **P0 exit = No-Go**，唯一 blocker：daemon/browser 中斷後殘留的 `tmux attach` client 使 recovered reattach 阻塞（`docs/p0-report.md`、ADR 0004）。**此 blocker 是 P2 的硬性 Gate-0（`P2-01`），未關閉前不得進入其餘 wave。**

## 文件順序

| 文件 | 用途 |
|---|---|
| [00-execution-plan.md](./00-execution-plan.md) | 範圍、非目標、固定基線、垂直架構、ticket 波次、共同完成定義與 P2 預設限制 |
| [01-session-domain-api.md](./01-session-domain-api.md) | P2-W1：session 狀態機、`terminal_sessions`/`session_connections` schema、domain service、HTTP API 與 relay 接線 |
| [02-runtime-launcher-tmux.md](./02-runtime-launcher-tmux.md) | P2-W2：**P0 recovery blocker spike（Gate-0）**、runtime allowlist launcher、tmux 命名/metadata、terminate policy、daemon restart reconciliation |
| [03-terminal-relay.md](./03-terminal-relay.md) | P2-W3：protocol v1.2 凍結、browser terminal WS relay、control/binary frame、resize/heartbeat/attach-resume/exit、bounds/backpressure、cleanup |
| [04-single-writer-viewers.md](./04-single-writer-viewers.md) | P2-W4：single writer/viewer、writer disconnect 保留與釋放、takeover（RBAC+confirm+notify+audit）、偽造 input 拒絕 |
| [05-frontend-session-flow.md](./05-frontend-session-flow.md) | P2-W5：Sessions list、New Session dialog（相依選項/前置阻擋）、Session Workspace route 與 header |
| [06-xterm-integration.md](./06-xterm-integration.md) | P2-W6：xterm production composable（ws-ticket + session-scoped WS）、reconnect/gap/exit、切 session dispose、writer/viewer UI |
| [07-audit-observability.md](./07-audit-observability.md) | P2-W7：session/terminal audit（不含 terminal content）、metrics、correlation log、argv redaction |
| [08-verification-and-exit.md](./08-verification-and-exit.md) | 測試矩陣、CI gates、操作證據、P2 exit gate、ADR/決策清單、風險與 P3 follow-ups |
| [09-implementation-status.md](./09-implementation-status.md) | 實作進度與證據（各 ticket 狀態、已驗證證據、P2-07 續作點）— 隨實作更新 |

## 使用規則

1. **先過 `P2-01`（recovery spike Gate-0）與 `P2-03`（protocol v1.2 凍結）**，再並行 Central、Daemon 與 Frontend。修改契約的 PR 必須先於 consumer 合併，且同步更新 schema、`contracts/v1/fixtures/manifest.json`、fixtures 與 Python/Go/TS 三個 consumer。
2. 每項 task 都需提交其列出的產物與測試；「可手動展示」不能替代自動測試。真實 Claude/Codex 只做 isolated smoke，日常 integration 一律用 P0 的 Fake CLI（`daemon/cmd/fakecli`）。
3. 依 `.agent/skills/cliora-project-context`：先檢視 repo 現況、不假設規劃中的目錄已存在、做最小可行變更，並保全 trust-boundary invariants（outbound-only daemon WSS、runtime-ID allowlist、**Central 不接受 command/binary/shell string**、無 Central SSH、PostgreSQL 不存 terminal bytes）。相關技能：`terminal-websocket-protocol`、`go-daemon-development`、`fastapi`、`vue-naive-ui-workflow`、`cliora-security-review`、`timezone-precision`、`webapp-testing`。
4. 需求變更先更新 `research/prd.md`／`tech.md`／`style.md`，再同步 `research/01/06-requirement-traceability.md`，不得在 implementation ticket 中暗自擴張範圍。
5. 所有時間採 tz-aware；持久化用 timezone-aware PostgreSQL 型別，傳輸 RFC 3339 UTC（`Z`），畫面才本地化；duration（heartbeat/attach/terminate timeout、reconnect backoff、writer 保留窗）以 **monotonic** 計算。

## 完成結果

P2 通過時，Developer 可在 Nodes 挑一台 Online node、選 Claude 或 Codex、指定該 node allowed root 下的合法目錄，於 New Session dialog 啟動 session；瀏覽器以 ws-ticket 認證連上 `/ws/sessions/{id}/terminal`，看到 ANSI/UTF-8/審批選單，送出原始鍵盤 bytes 與 resize。刷新頁面或短暫斷線後，session 不終止，可 reattach 並取得最新 bounded snapshot（截斷時標記 `truncated` 並送 `terminal.gap`）。第二位使用者只能 viewer；授權者可經確認接管 writer，現任被通知，操作留下不含 terminal content 的 audit。終止 session 走 graceful→force→狀態更新；offline node 不能建立 session。端到端額外延遲在代表性環境符合 PRD < 200 ms 目標，或已有量測與改善門檻。
