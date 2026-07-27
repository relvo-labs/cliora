# 06 — 需求追蹤矩陣

## 1. 核心需求到階段

| 需求群 | 主要階段 | 核心證據 |
|---|---|---|
| FR-AUTH-001/002 | P1、P4 | HTTP/WS auth tests、permission matrix、RBAC E2E |
| FR-NODE-001–005 | P1、P4 | enrollment/replay tests、heartbeat/offline tests、Node UI E2E |
| FR-INSTALL-001–005 | P1、P4 | Linux install matrix、checksum、update/rollback |
| FR-RUNTIME-001–004 | P1、P2 | adapter unit tests、missing runtime E2E、allowlist review |
| FR-WORKSPACE-001–005 | P2、P3 | workspace selection、root containment、favorites 若納入 MVP |
| FR-SESSION-001–007 | P2 | state transition、start/attach/terminate/recovery、writer tests |
| FR-TERM-001–006 | P0、P2 | cross-language contract、xterm E2E、resize/reconnect/burst |
| FR-FILE-001–007 | P3 | path security、tree/search/preview E2E、denial matrix |
| FR-CONN-001–006 | P0、P1、P2 | outbound WSS、TLS、correlation、timeout、binary frame |
| SEC-001–007 | 全階段 | security suite、artifact/config review、audit/redaction |
| NFR-001–005 | P2–P4 | latency/load/recovery/support-matrix reports |

## 2. PRD MVP 驗收條件對照

| # | 驗收能力 | 工作包 | 主要驗證 |
|---:|---|---|---|
| 1–3 | token、一行安裝、自動註冊 | P1-W3/W4/W6 | install integration |
| 4–5 | Node 狀態與 runtime | P1-W5/W7 | heartbeat + UI E2E |
| 6–10 | 選 Node/runtime/workspace 並啟動 | P2-W1/W2/W5 | session integration |
| 11–12 | 完整 Terminal 與 CLI 原生審批 | P0-W3/W4、P2-W3/W6 | Fake CLI + isolated live smoke |
| 13–14 | Browser 分離與重新連線 | P0-W5、P2-W2/W6 | refresh/disconnect/recovery |
| 15–17 | tree、唯讀 preview、敏感拒絕 | P3-W2–W5 | security + browser E2E |
| 18 | offline 不可建 session | P1-W5、P2-W1/W5 | domain + E2E |
| 19 | 終止 session | P2-W1/W2/W5 | lifecycle integration |
| 20 | 重要操作 Audit | P2-W7、P4-W2 | audit completeness/redaction |

## 3. 原型頁面到正式元件

| 原型區塊 | 正式 route/元件 | 對應階段 | 缺少的 production states |
|---|---|---|---|
| Top/Side/Status shell | `AppShell`、router navigation | P0/P1 | auth loading、connection stale、keyboard nav |
| Dashboard | `DashboardView`、metric/activity components | P4 | partial/stale/empty/error、real aggregates |
| Nodes cards/filter | `NodesView`、`NodeCard/Table` | P1 | pagination、offline detail、forbidden、API retry |
| Node details（原型未完整） | `NodeDetailView` | P1 | roots、daemon、errors、disable confirm |
| Sessions table | `SessionsView` | P2 | status transitions、filters、empty/error/RBAC |
| New Session modal | `NewSessionDialog` | P2 | dependent loading、validation、timeout/conflict |
| Enrollment | `EnrollmentView` | P1 | secret once-only、expiry/revoke/error/install status |
| Workspace header/rails | `SessionWorkspaceView` | P2 | reconnect/gap/writer-viewer/takeover |
| Fake terminal | `TerminalPane` + xterm composable | P0/P2 | raw bytes、resize、scrollback、cleanup/backpressure |
| Static file explorer | `FileTree`、`PreviewPane` | P3 | lazy/cancel/deny/Monaco/model lifecycle |
| Team/Audit/Settings placeholders | RBAC/Audit settings views | P4 | real policy、pagination、empty/error |

## 4. Release gate checklist

每個 release candidate 至少產生以下證據：

- 契約：protocol schema/fixtures 與 API spec diff。
- 品質：lint、typecheck、unit、Go race、build 報告。
- 整合：Fake daemon/CLI deterministic integration 報告。
- E2E：login → node → session → terminal → file → reconnect → terminate。
- 安全：auth/RBAC、replay、path、sensitive file、forged WS、flood/redaction 報告。
- 效能：Terminal latency、list/preview latency、connection/session load。
- UX/a11y：keyboard/focus、status not color-only、async/error states、browser matrix。
- 維運：migration、backup/restore、deploy/rollback、daemon update/rollback。

## 5. 未決需求清單

下列項目應在對應階段開工前決定，避免實作者自行發明需求：

| 決策 | 最晚時間 | 預設規劃假設 |
|---|---|---|
| ~~Cliora/Cask 正式名稱~~ **已決定：Cliora**（ADR 0016，2026-07-25） | P0 結束（實際於 P4-01 補記） | product name 仍可設定，不硬編碼 |
| Writer takeover policy | P0 結束 | owner 為 writer，viewer 不可輸入，顯式授權才接管 |
| 精確 frame/queue/file/session limits | 各風險 PoC 結束 | 先用可設定且 bounded 值，由量測定稿 |
| Auth token/session 方案 | P1-W2 前 | 短效 access + 可撤銷 refresh/session，WS boundary 驗證 |
| macOS daemon 是否為 MVP | P1-W6 前 | 依 PRD NFR，以 Linux 三發行版為 MVP gate |
| Workspace favorites | P3 前 | 非核心安全路徑，可在 tree 完成後排入 |
| Node remove 與資料保留 | P4 前 | 先 disable，不做破壞性 hard delete |

## 6. 變更控制

若新增任意 shell、Web 編輯、Git automation、Terminal retention、Central SSH、多 agent 或橫向擴充，必須先：

1. 更新 PRD 的目標/非目標與新 requirement ID。
2. 更新 tech 的 trust boundary、protocol、data、failure、security、observability 與 test。
3. 更新 style 的 UI/state contract。
4. 再更新本矩陣與階段出口，不能只在 implementation ticket 中暗自擴張。


## 7. P1 實際證據（2026-07-24）

| 需求 | 實作與自動化證據 | 驗收狀態 |
|---|---|---|
| FR-AUTH-001/002 | `backend/tests/db/test_auth_api.py`、`backend/tests/test_security.py`、`frontend/src/stores/auth.test.ts`、`frontend/tests/e2e/auth.spec.ts` | Backend/Frontend unit 與 Chromium/Firefox E2E 通過；WebKit 交由 CI runner |
| FR-NODE-001–005 | `backend/tests/db/test_enrollment_api.py`、`test_node_registration.py`、`test_node_api.py`、`test_node_ws.py`、`frontend/tests/e2e/nodes.spec.ts` | DB 32 tests 通過；Chromium/Firefox login→nodes→enrollment 4 tests 通過 |
| FR-INSTALL-001–005 | `deploy/install.sh`、`daemon/internal/install/install_test.go`、`.github/workflows/p1.yml` 的 `daemon-artifacts`/`install-smoke` | installer contract 已自動化；真實 systemd 六平台矩陣仍是 release blocker |
| FR-RUNTIME-001–004 | `daemon/internal/runtime/runtime_test.go`、`contracts/v1/fixtures/invalid/node-runtime-status-bad-runtime.json` | 實作與測試存在；本機缺 Go toolchain，須由 CI 執行 race/contract |
| FR-CONN-001–006 | `backend/app/api/ws/nodes.py`、`daemon/internal/connection/connection_test.go`、`backend/tests/db/test_node_ws.py` | Ed25519 nonce challenge 實作含有效簽章、錯誤簽章、重放 challenge id 與撤銷測試 |
| SEC-001–007 | `backend/tests/test_security.py`、`backend/tests/db/test_node_ws.py`、`.github/workflows/p1.yml` 的 `security` | 本機 backend gates 通過；CI 尚待首次綠燈 |
| P1 資料可靠性 | `backend/tests/db/test_schema.py`、Alembic `0001`/`0002`/`0003`（`0003` 以 Ed25519 public key 取代共享 node secret，見 `backend/app/db/migrations/versions/0003_ed25519_node_credentials.py`） | PostgreSQL 16 upgrade→建立 Admin→downgrade base→upgrade 與 31 DB tests 通過 |
| P1 UI/UX | `frontend/src/**/*.test.ts`、`frontend/tests/e2e/*.spec.ts` | lint/typecheck/build、58 unit、Chromium/Firefox smoke 8 與 full-stack 4 通過 |

本節只記錄實際執行或可定位的自動化證據；尚未在真實 runner 執行的項目不得標為完成。完整判定見 `docs/p1-report.md`。

## 8. P2 實際證據（2026-07-24）

| 需求 | 實作與自動化證據 | 驗收狀態 |
|---|---|---|
| FR-SESSION-001–007 | `backend/app/services/sessions.py`（狀態機）、`app/api/http/sessions.py`、`tests/test_session_state.py`、`tests/db/test_sessions_service.py`、`test_sessions_api.py`（狀態機/guards/idempotency/RBAC/offline/limit/terminate/status_changed） | Backend 161 tests 通過（含 DB）；三角色 allow/deny、offline/limit/timeout 均測 |
| FR-TERM-001–006 | daemon `internal/connection`（attach 串流 kind=2、resize、gap/exited）、`frontend/src/composables/useTerminalSession.ts`、`app/api/ws/terminal.py` | daemon integration（真實 tmux start→attach→stream→stop）；frontend 9 tests 含 leak gate |
| FR-RUNTIME-002/003 | daemon `internal/runtime`（ResolveBinary allowlist）、`internal/tmux`（runtime allowlist） | disabled→`RUNTIME_DISABLED`；任意 command 無法注入（無 argv 入口，SEC-002） |
| FR-WORKSPACE-003 | daemon `internal/workspace/guard.go`、`services/sessions.py`（Central prefix 授權） | `go test -race ./internal/workspace`：traversal/symlink/prefix-collision/null-byte 全拒 |
| FR-CONN-005（binary frame） | `protocol` EncodeBinary/DecodeBinary、relay `route_output`、`registry.send_binary` | daemon→browser binary 串流 integration；relay hub 6 tests |
| FR-SESSION-007（single writer） | `app/services/terminal_relay.py`、`app/api/ws/terminal.py` | writer/viewer/takeover 單元測試；viewer/偽造 input server 端丟棄 |
| SEC-001/002/003/006 | workspace guard、runtime allowlist、ws-ticket（綁 user+session）、session audit（create/attach/takeover/terminate/failed） | audit 無 terminal content；ws-ticket single-use；path/command 注入拒絕 |
| P2 資料可靠性 | Alembic `0005`（terminal_sessions/session_connections）、`0006`（RBAC seed）；`tests/db` | upgrade→downgrade 0004→re-upgrade + seed 反轉驗證 |
| P2 recovery（P0 blocker） | `daemon/internal/session/recovery_test.go` | live-orphan 驅逐無 leaked client、rapid reattach ×20、post-recovery stop（`-tags integration -race`）；ADR 0012 |

尚未在真實 runner 執行：`p2` CI、Playwright full-stack E2E、端到端 < 200 ms latency 與 500-WS/10-per-node 規模量測。完整判定見 `docs/p2-report.md`。

## 9. P3 實際證據（2026-07-25）

| 需求 | 實作與自動化證據 | 驗收狀態 |
|---|---|---|
| FR-FILE-001（tree、lazy、icon、metadata） | daemon `internal/files/list.go`（deterministic ordering、hidden/symlink/excluded、entry limit + cursor）、`stores/files.ts`、`composables/useFileTree.ts`、`components/file/FileTree*.vue`；`useFileTree.test.ts`（17）、`FileTree.test.ts`（5）、`internal/connection/files_integration_test.go`、`tests/e2e/files.spec.ts` | daemon 真實連線 integration + frontend unit + full-stack E2E 全綠；圖示/徽章以形狀+文字區分 |
| FR-FILE-002（Monaco 唯讀預覽） | `monaco/setup.ts`（curated build、自帶 worker、無 CDN）、`composables/useMonacoModel.ts`、`components/file/PreviewPane.vue`；`useMonacoModel.test.ts`（16，含 leak gate）、E2E（高亮/行號/輸入無效/wrap/find/copy/refresh） | 離線 build 通過並驗證 `editor.worker` 為本地 asset、dist 無 CDN 參照 |
| FR-FILE-003（oversize） | `internal/files/read.go`（fd 快照 size → `FILE_TOO_LARGE`，不讀內容）、`PreviewDenied.vue`；`TestReadPolicyMatrix`、integration、E2E（3.00 MB vs 上限） | 通過。**協定 frame 上限缺口已修**（見 `contracts/CHANGELOG.md` 1.3.1、ADR 0015 amendment）：原 64 KiB 控制上限無法承載 2 MiB 預覽，回應被丟棄導致逾時 |
| FR-FILE-004（binary） | `DetectBinary`（NUL/UTF-8/控制字元比例）+ mime/size/mtime；integration、E2E | 通過；僅回 metadata，無內容 |
| FR-FILE-005 / SEC-004（敏感檔） | `internal/files/policy.go`（exact/extension/glob/directory 四類）+ `RealRel` 解析後複查（擋 in-root symlink 繞道）；`TestReadPolicyMatrix`、integration、E2E（`.env`/`*.pem`）、`PreviewDenied.test.ts` | 通過。**部署路徑缺口已修**：`internal/install/plan.go` 產生的 config 未寫出政策清單，`yaml` 將 nil slice 寫成 `[]` 而載入端只檢查 nil，導致新註冊節點「不擋任何敏感檔」；現以 installer 顯式寫出 + 兩個安全清單「空即套預設」雙重修復，回歸測試見 `internal/config`、`internal/install` |
| FR-FILE-006（refresh、allowed→denied） | `FileTreeToolbar.vue`（重打該層並丟棄 cache）、`useMonacoModel.refresh()`（dispose model → 清畫面 → 顯示 denial）；unit（allowed→denied 清空斷言）、E2E | 通過；MVP 不做即時 watch（P4） |
| FR-FILE-007（檔名搜尋） | `internal/files/search.go`（depth/results/scanned/timeout bounds、可 cancel、excluded 不下探、僅檔名）、`FileSearchBar.vue` + `reveal()`；integration（partial + `stopped_reason`）、unit、E2E（搜尋→展開祖先→選中） | 通過；不接受 shell/ripgrep 參數（schema `additionalProperties:false`） |
| FR-WORKSPACE-002（瀏覽） | `SessionWorkspaceView.vue` 三欄整合（tree 面板 + 預覽分割）、`filesSessionId`/`workspaceLabel`（僅資料夾名，不外洩絕對路徑） | 通過；切 session／session 終態清空並中止在途請求 |
| SEC-001（路徑安全，硬性 Gate） | `internal/workspace/root.go`（`os.Root` handle：`OpenWorkspace/OpenDir/OpenFile`、`RealRel`）；`go test -race ./internal/workspace`（traversal/absolute/prefix-collision/symlink chain/broken link/null byte/非 regular/symlink-swap TOCTOU/bounded-read TOCTOU）、`FuzzOpenFile` 7.2M execs 無違規 | 全綠；每次 list/read/search 重新 canonicalize |
| SEC-002（不接受任意輸入） | `app/services/files.py` `_reject_rel_path`（absolute/`..`/`~`/控制字元 → 400，且**不轉發**）、protocol v1.3 request schema | `tests/db/test_files_api.py` 斷言 `fake.calls == []` |
| SEC-006（敏感讀取失敗稽核） | `app/services/files.py` `_maybe_audit_denied` → `FILE_SENSITIVE_READ_DENIED`（僅 classification + 副檔名） | DB 測試斷言 metadata 無 `rel_path`/檔名主體/內容；audit 寫入失敗不影響使用者請求並計入 error metric |
| NFR（list < 2s、≤2MB preview < 3s） | `daemon/internal/files/bench_test.go`（daemon leg，預算內建、超標即失敗）+ `backend/perf/files_bench.py`（Central leg + relay bounds）；`artifacts/p3/local/{fs-latency,relay-latency}.json` | list ~12 ms、preview ~9 ms、search ~7 ms（p95 兩段相加），皆遠低於目標 |
| tech §18（可觀測性） | `app/metrics.py` + `daemon/internal/metrics`（request/duration/denied/timeout/cancel/disconnect/bounds）、correlation log（keyword 只留 12 字 digest） | 單元 + DB 測試涵蓋各 op 計數、逾時/斷線計數、denial 分類；log 以 `JsonFormatter` 實際輸出斷言無 path/content/keyword |

本節只記錄實際執行或可定位的自動化證據。尚未在真實 runner 執行：`.github/workflows/p3.yml`（每個 job 的核心命令已在本機逐一執行通過）。完整判定見 `docs/p3-report.md`。
