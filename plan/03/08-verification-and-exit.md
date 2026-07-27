# 08 — 驗證、證據與 P2 Exit Gate

對應 ticket **P2-16**。延續 P0/P1 的驗證紀律（`plan/01/07`、`plan/02/08`），擴充 session 生命週期、terminal relay、writer/viewer、daemon recovery 與延遲量測。

## 1. 測試分層

| 層級 | 必跑內容 | 主要 owner |
|---|---|---|
| Contract | protocol v1.2 新型別 schema、三語言 fixtures、round trip；forbidden（start 帶 command）/naive-time/bad-enum/out-of-range size/unknown-field 拒絕；binary frame input/output round trip | protocol |
| Unit（backend） | session 狀態機所有 transition（fake clock）、create guard（offline/disabled/missing-runtime/invalid-workspace/limit）、idempotency/conflict、terminate timeout、`registry.request` 首個 caller 的 correlation/timeout/late-response/斷線 cleanup、relay queue/backpressure/gap、writer 授權（viewer 偽造 input 丟棄）、takeover race、audit redaction、tz round-trip、transaction rollback | Central |
| Unit（daemon） | runtime allowlist 拒任意 argv、workspace canonical validation（`../`/absolute escape/prefix collision/symlink chain/broken link/null byte）、start/stop/resize、graceful→force terminate、session.list/recover、`-race` 無 leak | daemon |
| Migration | `terminal_sessions`/`session_connections` clean upgrade、重跑、downgrade（含引用資料）；RBAC session/terminal seed clean/repeat/prior-data/contraction | Central |
| Integration | **P2-01 recovery gate**：rapid reattach ×20 + cross-process daemon-restart recovery 無 leaked client；enrollment→WSS→session.start→tmux→PTY→attach→resize→terminate 全鏈；daemon restart reconcile + reattach；Fake CLI byte 保真（ANSI/UTF-8） | Central+daemon |
| Browser（E2E） | login→node→New Session（相依選項/前置阻擋）→workspace→terminal 互動→refresh reattach→writer/viewer→授權 takeover→terminate；三角色差異；非同步/錯誤/offline 狀態；responsive | frontend |
| Performance | 端到端額外延遲量測（目標 < 200 ms）；output burst 16 MiB slow-consumer RSS/queue 有界；500 terminal WS 規模（NFR-003）代表性量測 | cross-stack |
| Security | terminal WS ws-ticket 認證（stolen/expired/forged session_id）、viewer 偽造 input 拒絕、takeover RBAC、任意 command/argv 注入拒絕、path escape 拒絕、flood/backpressure、log/audit/DB redaction（無 terminal content） | cross-stack |

測試不得依賴外部 Claude/Codex、真實網際網路或固定個人路徑；時間/retry/timeout/writer 保留窗用 fake/monotonic clock；UUID/ULID/nonce 用可注入 deterministic source；PostgreSQL 以 CI service container 或 ephemeral schema 提供並清理。日常 integration 用 Fake CLI（`daemon/cmd/fakecli`），真實 runtime 僅 isolated smoke。

## 2. 必要 CI gates

延續 `.github/workflows`（P1 的 `backend`/`daemon`/`contract`/`security`/`e2e`），P2 新增/擴充：

- `backend`：新增 session/relay/writer/audit unit；DB job 跑 `terminal_sessions`/`session_connections` migration upgrade/downgrade + rollback、RBAC seed。
- `daemon`：`go vet`、`go test -race ./...`、`-tags integration -race ./internal/session`（含 recovery gate 與 launcher/workspace/terminate 測試）、build amd64/arm64。
- `contract`：Python/Go/TS 對 v1.2 `manifest.json` 一致 accept/reject。
- `e2e`：Playwright Chromium/Firefox/WebKit，涵蓋 session→terminal→reconnect→writer/viewer→takeover→terminate（full-stack 以 env flag 開，沿用 `nodes.spec.ts` gating）。
- `security`：terminal WS 認證、偽造 input、command 注入、path escape、flood/redaction 掃描。
- `performance`（merge/RC）：延遲與 slow-consumer RSS/queue artifact。

每個 PR 跑 format/lint、typecheck、unit、contract、build 與 migration；合併主分支與 RC 另跑 integration（含 recovery gate）、E2E matrix、security 與 performance。CI log 不列印 secret/token/**terminal content**。

## 3. 操作證據包

於 `artifacts/p2/<run-id>/`（CI artifact）保存：

- `versions.txt`、`commands.txt`（root task 與 exit status）。
- `contract.xml`、`unit-backend.xml`、`unit-daemon.xml`、`migration.xml`、`integration.xml`、`e2e.xml`、`race.txt`。
- `recovery-gate.txt`：P2-01 rapid reattach + daemon-restart recovery 結果與 client/PTY leak 檢查。
- `latency.json`：端到端額外延遲分佈（含環境）與是否達 < 200 ms。
- `backpressure.json`：output burst RSS/queue baseline、overflow→gap、bytes 歸零證據。
- `writer-viewer.md`：single-writer、viewer 偽造 input 拒絕、takeover race、通知/audit 結果。
- `security-report.md`：WS 認證/偽造/注入/path/flood/redaction。
- `screenshots/`：sessions list（含 empty/offline/forbidden）、New Session（validation/starting/timeout/conflict）、workspace（connected/reconnecting/gap/exited）、writer vs viewer、takeover 確認。

發布前以掃描確認 log/artifact/DB 不含 password、JWT、ws-ticket、challenge 簽章、**terminal input/output**、process environment 或不必要 absolute path。

## 4. Exit Gate checklist

### 功能

- [ ] **P2-01 recovery gate 通過**：rapid reattach 與 cross-process daemon-restart recovery 無 leaked attach client，recovered attach 後 `session.stop` 正常收尾。
- [ ] Developer 可於 Online node 選 Claude/Codex 與合法 workspace 建立 session 並完整操作原生 CLI（審批選單、Ctrl+C、Unicode、resize、長輸出）。
- [ ] Browser refresh／短暫斷線不終止 session，可安全 reattach 並取得最新 bounded snapshot（截斷標記 + gap）。
- [ ] single-writer/viewer 明確；授權 takeover 經確認、通知現任並 audit；terminate 走 graceful→force→狀態更新。
- [ ] offline/disabled node 不能建立 session；missing/disabled runtime、非 allowed root 路徑被拒。

### 契約與安全

- [ ] Python/Go/TS 共用 v1.2 fixtures 全通過；start 帶 command／naive-time／out-of-range size／unknown-field 安全拒絕。
- [ ] Central 全程不接受 command/binary/shell string；runtime 以 allowlisted argv 啟動，注入嘗試被拒。
- [ ] terminal WS 以 single-use ws-ticket（綁 user+session）認證；stolen/expired/forged session_id 於 handshake 拒絕。
- [ ] **viewer 偽造 input frame 由 server 丟棄**；takeover 需 `terminal.takeover` 權。
- [ ] workspace launch-time canonical validation 拒 `../`/absolute escape/prefix collision/symlink chain/broken link/null byte。
- [ ] log/audit/DB 無 secret/token/**terminal content**（掃描證明）。

### 資料與可靠性

- [ ] `terminal_sessions`/`session_connections` Alembic upgrade/重跑/downgrade 通過；transaction rollback 無部分寫入；tz-aware round-trip。
- [ ] `go test -race ./...` 與 `-tags integration -race` 綠；pytest 無 pending task/leak；relay 斷線/timeout/late-response cleanup 無 correlation/subscription/writer 標記 leak。
- [ ] daemon restart 後既有 session 正確 reconcile 並可 reattach；孤兒 session 依 policy 處置且不誤殺。

### 效能與工程基線

- [ ] 端到端額外延遲有量測結果；未達 < 200 ms 的項目有明確 release decision。
- [ ] output burst/slow-consumer RSS/queue 有界（artifact 佐證）；500 terminal WS 規模有代表性量測。
- [ ] 乾淨 checkout 依 README 可 bootstrap、migrate、build、test、run（含 session→terminal 垂直）。
- [ ] CI gates 綠燈且 artifact 可追溯到 commit；`research/01/06-requirement-traceability.md` §7 以實際證據更新 FR-SESSION/TERM、相關 SEC/NFR。

任一項未過即維持 P2 open；不可因 demo 可建立 session 即豁免 recovery gate、認證、偽造 input 拒絕、migration、redaction 或 race gate。

## 5. ADR / 決策清單

| ADR | P2 必答問題 | 截止 |
|---|---|---|
| 0012 recovery/attach 模型 | control-mode pipe bridge vs attach subprocess-group cleanup、`terminal.exited.code` 保真度、snapshot 上限與 gap 語意 | P2-01 完成時 |
| 0013 session 生命週期 | 狀態機與 transition 來源、writer/takeover policy（保留窗、是否需現任同意/admin override）、`session_connections` 模型與持久化、browser terminal WS 認證、P2 limits（每 node session/queue/timeout） | P2-02（P2-05/09/10 前） |

同時更新既有 ADR：0004（P0 recovery strategy）於 P2-01 完成時補上採用方案與 exit-code 決策。

## 6. 已知風險與相依

- **P2-01 為硬性 Gate-0**：P0 recovery blocker 未關閉前不得推進其餘 wave；P1 已明列此為 P2 開工前提。若 spike 顯示兩方案皆不可行，須回報替代設計（例如改以 tmux control-mode 為主要 attach 通道）與重新估算，而非硬闖。
- **production 連線整合點**：`internal/connection` 的 `readLoop` 目前丟棄 inbound frame；P2-07 把 dispatch 接上是行為改變面最大處，需 `-race` 與 late/duplicate frame 測試。
- **`registry.request()` 首個 production caller**：correlation/timeout/斷線 cleanup 先前只有 unit（`test_correlation.py`），P2 於真實 route/relay 壓力下驗證無 future/pending leak。
- **規模**：P2 才首次驗 terminal 500 WS 與 session 規模（NFR-003），與延遲目標一併量測；未達標列 release decision，不隱藏。
- **本規劃補上、需回填 canonical docs 的決策**：`session_connections` 表（PRD §12 未列）、writer 保留窗與顯式 takeover policy、terminal WS ws-ticket 綁 session、launch-time workspace 錯誤碼（`WORKSPACE_*`）、`terminal.exited.code` 保真度——皆於 ADR 0012/0013 記錄並視情況回填 `research/prd.md`/`tech.md`。

## 7. Go / No-Go review

Exit review 輸出一頁 `docs/p2-report.md`：結果、未通過項、實測參數（延遲、recovery 恢復時間、writer 保留窗、queue/snapshot 上限、500-WS 規模結果）、已知 gap、採納 ADR、P3 follow-ups（workspace 檔案樹/搜尋/唯讀預覽依賴 P2 的 session context；`workspace_favorites`/最近使用 workspace）。只有上述 checklist 全過、且無未處理的高風險：認證繞過、viewer 輸入穿透、command 注入、path escape、terminal content 外洩、migration 不可回退或 relay/registry leak，才可標記 Go。若不可行，報告須列替代方案、需修改的架構、重新估算與下一個 time-boxed spike，而非直接進 Phase 3。
