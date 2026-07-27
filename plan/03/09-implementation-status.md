# 09 — P2 實作進度與證據（2026-07-24）

本檔記錄 `plan/03` 各 ticket 的實際實作狀態與可定位的自動化證據，對齊 `00-execution-plan.md` §4 的波次表。只記錄已執行或可定位的證據；尚未在對應 runner 執行的項目不標為完成。判定規則沿用 `08-verification-and-exit.md`。

## 1. 狀態總覽

| Ticket | 狀態 | 說明 |
|---|---|---|
| P2-01 Gate-0 recovery | ✅ 完成 | P0 blocker 已由現有 `manager.go`（Detach + `attach-session -d`）解決；新增 regression 測試證明並反向驗證 |
| P2-02 決策 ADR | ✅ 完成 | ADR 0012（recovery/attach）、0013（session lifecycle）；0004 更新 |
| P2-03 protocol v1.2 | ✅ 完成 | schema/fixtures/manifest + Python/Go/TS 三 codec；契約三語言一致 |
| P2-04 資料層 + RBAC seed | ✅ 完成 | migration 0005/0006；upgrade/downgrade/re-upgrade + seed 反轉已驗 |
| P2-05 session domain 服務 | ✅ 完成 | 狀態機 + repository + service；hermetic + DB 測試 |
| P2-06 session HTTP API | ✅ 完成 | `/api/sessions` 全端點；首個 `registry.request()` production caller |
| P2-07 daemon session lifecycle | ✅ 完成 | `internal/workspace` guard + dispatch 已接進 production `connection.go`；session.start/stop/resize；unit（error paths）+ integration（真實 tmux start→stop round-trip）綠 |
| P2-08 daemon restart reconcile | ✅ 完成 | daemon 於 session exit 送 `session.status_changed`；Central node WS → `SessionService.apply_status_changed`（`session.list`/`recover` 完整掃描留 P3 follow-up） |
| P2-09 browser terminal WS relay | ✅ 完成 | daemon session.attach 串流；Central `terminal_relay` hub + node-WS binary 路由 + `/ws/sessions/{id}/terminal` endpoint |
| P2-10 single writer/viewer/takeover | ✅ 完成 | server 端 writer 標記、viewer/偽造 input 丟棄、takeover（需 `terminal.takeover`）；relay hub 6 tests |
| P2-11 Sessions list + New Session dialog | ✅ 完成 | `SessionsView` + `NewSessionDialog`（相依 Node→runtime→workspace、offline 過濾、error code 對映） |
| P2-12 Session Workspace route | ✅ 完成 | `SessionWorkspaceView` 三欄、header 狀態/reconnect/terminate、切 session reconnect、P3 workspace 面板佔位 |
| P2-13 xterm production composable | ✅ 完成 | `useTerminalSession` 改用 ws-ticket + `/ws/sessions/{id}/terminal`；raw bytes/resize/gap/exit/dispose；9 tests 含 leak gate |
| P2-14 writer/viewer + takeover UI | ✅ 完成 | 角色標示（非僅顏色）+ Request control；danger confirm |
| P2-15 audit + observability | ✅ 完成（metrics 部分） | session create/attach/takeover/terminate/failed 均 audit（無 terminal content）；結構化 metrics 匯出留 P4 |
| P2-16 verification + exit review | ✅ 完成（本機） | 三 stack 全綠；`docs/p2-report.md` 產出；CI/E2E/latency 仍待真實 runner |

圖例：✅ 完成並在本機驗證綠燈 · ◐ 部分完成 · ⬜ 未開始。

> **P2 本機驗證（2026-07-24）全綠**：daemon `go test -race ./...` + `-tags integration -race`、`gofmt`/`vet` clean；backend `ruff`/`mypy` clean + `pytest` 161 passed（含 PostgreSQL DB）；frontend typecheck/lint/format clean + 78 unit + build。三語言 contract 一致。完整判定與未竟項（CI、Playwright full-stack E2E、latency/scale）見 `docs/p2-report.md`。

## 2. 已完成項目的證據

| 需求/工作包 | 實作檔案 | 自動化證據 |
|---|---|---|
| P2-01 recovery gate | `daemon/internal/session/recovery_test.go` | `go test -tags integration -race ./internal/session` 綠；`TestRecoveredReattachEvictsLiveOrphan`（no leaked client，含移除 `-d` 反向驗證）、`TestRapidReattachChurn` |
| P2-02 ADR | `docs/adr/0012-p2-recovery-attach-model.md`、`0013-p2-session-lifecycle.md`、`0004`(updated) | — |
| P2-03 protocol v1.2 | `contracts/v1/schemas/{control-envelope,messages/session-*,session-id,session-list}`、`fixtures/{valid,invalid}/*`、`manifest.json`、`CHANGELOG.md`；`daemon/internal/protocol/codec.go`、`daemon/cmd/agentd/dispatcher.go`、`frontend/src/protocol/decode.ts` | Go `go test ./internal/protocol -run Contract` 綠；Python `pytest tests/contract` 42 passed；TS `vitest src/protocol` 41 passed |
| P2-04 資料層/RBAC | `backend/app/db/models.py`（TerminalSession/SessionConnection）、`migrations/versions/0005_*`、`0006_*`、`services/rbac.py`、`tests/db/conftest.py` | `alembic upgrade head`→downgrade 0004→re-upgrade 驗證；permissions 反轉驗證；`pytest tests/db` 綠 |
| P2-05 domain 服務 | `backend/app/services/sessions.py`、`repositories/sessions.py`、`settings.py`（P2 knobs）、`services/audit.py`（session actions） | `tests/test_session_state.py`(4) + `tests/db/test_sessions_service.py`(10) 綠 |
| P2-06 HTTP API | `backend/app/api/http/sessions.py`、`schemas.py`（session DTO）、`main.py`（router） | `tests/db/test_sessions_api.py`(7) 綠：create/get/list、offline 409、Viewer 403/可 view+attach、terminate、404、422 |
| P2-07 workspace guard | `daemon/internal/workspace/guard.go`、`guard_test.go` | `go test -race ./internal/workspace` 綠：`../`/absolute escape/prefix-collision/symlink chain/broken link/null byte 全覆蓋 |
| P2-07 daemon dispatch | `daemon/internal/connection/connection.go`（dispatch + handleStart/Stop/resize）、`internal/protocol/build.go`（BuildResponse/BuildError）、`internal/runtime/{runtime,registry}.go`（Binary/ResolveBinary）、`internal/tmux/client.go`（allowlist）、`internal/session/manager.go`（StartSession）、`connection_test.go`、`connection_integration_test.go` | unit：session.start disabled-runtime→`RUNTIME_DISABLED`、workspace escape→`WORKSPACE_OUTSIDE_ALLOWED_ROOT`（contract-valid error frame）；integration（`-tags integration -race`）：真實 tmux start→`session.started`→stop→`session.stopped`、session 消失 |
| P2-09 daemon attach | `daemon/internal/connection/connection.go`（handleAttach + sendChunked）、`connection_integration_test.go` | integration：session.attach→`session.attached`＋Fake CLI banner 以 binary kind=2 串流至 Central |
| P2-08 reconcile | `connection.go`（onExit 送 `session.status_changed`）、`backend/app/api/ws/nodes.py`、`tests/db/test_sessions_service.py` | daemon exit → Central `apply_status_changed`；running→exited 測試 |
| P2-09/10 Central relay | `backend/app/services/terminal_relay.py`、`app/api/ws/terminal.py`、`app/api/ws/nodes.py`（`receive()` + binary 路由）、`app/services/registry.py`（send_binary/send_text_frame）、`tests/test_terminal_relay.py` | relay hub 6 tests；node-WS binary→`route_output`；ws-ticket handshake；viewer input server 丟棄 |
| P2-11..14 frontend | `frontend/src/{views/SessionsView,views/SessionWorkspaceView,components/session/NewSessionDialog}.vue`、`stores/sessions.ts`、`api/{client,dto}.ts`、`composables/useTerminalSession.ts`（+ test）、`router/index.ts`、`components/layout/AppLayout.vue` | typecheck/lint/format clean；78 unit（含 terminal leak gate）；`npm run build` ok |
| P2-15 audit | `app/api/ws/terminal.py`（attach/takeover audit）、`app/services/audit.py`、`services/sessions.py` | session create/attach/takeover/terminate/failed 均 audit，無 terminal content |
| Backend 整體 | — | `ruff`/`mypy` clean；`pytest tests` **161 passed**（含 DB） |
| Daemon 整體 | — | `gofmt`/`go vet` clean；`go test -race ./...` 綠；`-tags integration -race ./internal/{session,connection}` 綠 |
| Frontend 整體 | — | typecheck/lint/format clean；78 unit；build ok |

本機執行環境：Go 1.26.5、Python 3.12.3、Node 22.14.0、tmux 3.4、PostgreSQL 16（docker `cliora-pg`）。DB 測試需 `CLIORA_TEST_DATABASE_URL`。

## 3. 補齊項目（2026-07-25）：CI / E2E / 效能 harness 已交付並本機驗證

原 §3 列的三個「可撰寫但尚缺」exit-gate 產物已補齊，且在本機（含真實全棧）驗證綠燈：

1. **`p2` CI workflow** — 新增 `.github/workflows/p2.yml`，含 `backend-db`、`daemon`（vet + `-race` + `-tags integration` + amd64/arm64 build，runner 裝 tmux）、`contract`（Python/Go/TS 三語言）、`security`（ws-ticket/relay/session）、`frontend`、`browser-e2e`、`performance` 七個 job。每個 job 的核心指令皆已本機執行綠燈（見下）。**唯一真正剩餘**：在實際 GitHub runner 上首次綠燈（需 push；本環境非 git repo，未執行）。
2. **Playwright full-stack E2E** — 新增 `frontend/tests/e2e/session.spec.ts`（login→New Session→live terminal→refresh reattach→terminate），比照 `nodes.spec.ts` 以 `E2E_FULL_STACK` gating，且無 online node 時自動 skip 互動段。**已對真實全棧跑綠**（chromium 2 passed）。全棧由新腳本 `scripts/e2e/run-stack.sh` 帶起：Central + 一個真實 daemon node（rootless `daemon/cmd/enroll-dev`，runtime `claude` → `daemon/cmd/fakecli`，fakecli 新增 `--version` 供 runtime detection）。
3. **效能/規模 harness** — 新增 `backend/perf/relay_bench.py`（+ `make perf`），對真實 `TerminalRelay`+`BrowserChannel` 熱路徑量測：單訂閱者 p99 ≈ 2 ms、500-WS fan-out（NFR-003）p99 ≈ 98 ms（< 200 ms 目標），slow-consumer 16 MiB burst 佇列有界（4 MiB/1024 frame）、恰一個 overflow→`terminal.gap`、RSS 平；invariant 迴歸則非零退出。artifact：`artifacts/p2/<run>/relay-bench.json`。

本機驗證（2026-07-25，DB reset 後）：backend `pytest` 161 passed、security subset 29、contract Python 42/Go/TS 41；daemon `gofmt`/`vet` clean、`-race` + `-tags integration -race ./internal/{session,connection}` 綠、三 binary build ok；frontend typecheck/lint/build + 78 unit；`scripts/e2e/run-stack.sh` 全棧 + Playwright session spec 2 passed；`relay_bench.py` rc=0。

仍為後續 phase 範圍（依規劃刻意延後，非本次補齊對象）：

4. **Observability**：`BrowserChannel` stats 以外的結構化 terminal/queue/timeout metrics 匯出（與 P4 併整）。
5. **P3 follow-up**：daemon `session.list`/`session.recover` 完整 restart 掃描（目前 exit 由 `status_changed` 覆蓋）。

進度亦記於使用者 memory `p2-implementation-progress.md`。
