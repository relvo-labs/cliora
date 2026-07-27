# 01 — 決策、Protocol v1.4 與 RBAC 完整化（P4-W1）

涵蓋 ticket **P4-01**（決策 ADR）、**P4-02**（protocol v1.4 凍結）與 **P4-03**（P4-W1 RBAC 完整化，**P4 硬性 Gate**）。對應 `research/01/05-phase-4-operations-hardening.md` §P4-W1、PRD FR-AUTH-001/002、SEC-006、tech §14。

---

## P4-01：決策 ADR 0016 / 0017 / 0018

P4 橫跨授權、稽核、可觀測性、發布與部署五個面向，決策量大於前幾期，因此拆為三份 ADR。`00-execution-plan.md` §7 已列出十二項閘門與六項已拍板結論；P4-01 的工作是把它們寫成 ADR 並補齊未定項。

| ADR | 必答內容 | 阻擋的 ticket |
|---|---|---|
| **0016** RBAC & audit 營運模型 | permission matrix 定稿（PRD §8.1 × 10 個 action key）、resource scope/owner 規則、capability 傳遞方式（`/api/auth/me`）、audit coverage 與單一性保證、metadata 粒度與 `request_id` 來源、retention 策略、**P0 dev relay 退場**（ADR 0006 標記 superseded） | P4-03、P4-04、P4-05、P4-07 |
| **0017** Release/update & deployment 基線 | manifest 格式與來源、簽章/來源策略與 reproducible build 驗證、update 步驟與 rollback 邊界、tmux 保留語意與 reconciliation、compose 服務組成、TLS 憑證來源、secret 注入、migration job 時機、graceful shutdown 語意 | P4-02、P4-10、P4-12 |
| **0018** Observability & capacity 基線 | metrics 清單（tech §18.1/18.2）與 **label 白名單**、export 端點與授權、資源歷史取樣率與 retention、alert 門檻與 for-duration、負載測試方法與判定、runbook 清單 | P4-06、P4-09、P4-11 |

**產出**：`docs/adr/0016-p4-rbac-and-audit-operations.md`、`docs/adr/0017-p4-release-update-and-deployment.md`、`docs/adr/0018-p4-observability-and-capacity.md`，並在 `docs/adr/0006-p1-auth-handoff.md` 標記 superseded-by 0016（P0 relay 退場）。ADR 必須寫出**被拒絕的替代方案與原因**（例如：為何不引入 Prometheus client library、為何不自動排程升級、為何不做自訂角色）。

---

## P4-02：Protocol v1.4 凍結（`daemon.update*`）

### 現況

`daemon/internal/protocol/codec.go:33` 的 `allowedTypes` 已含 `daemon.version`、`daemon.doctor`、`daemon.doctor_result`，**沒有** `daemon.update`／`daemon.update_result`（tech §12.2 已列出型別名稱）。`contracts/v1/schemas/messages/` 有 14 個 typed payload schema，尚無 update 相關者。`contracts/CHANGELOG.md` 目前最新為 1.3.1。

### 新增型別

| Type | 方向 | Payload | 說明 |
|---|---|---|---|
| `daemon.update` | Central → daemon | `{"target_version": "<semver>"}`，`additionalProperties:false` | **絕不含 URL、檔名、binary path、command 或任何檔案系統輸入**。daemon 收到後自行向 Central 取 manifest 並比對版本（SEC-002 延伸） |
| `daemon.update_result` | daemon → Central | `{"from_version","to_version","status":"succeeded\|failed\|rolled_back","stage":"manifest\|download\|checksum\|swap\|restart\|healthcheck","error_code"?}` | `error_code` 取自下方 `UPDATE_*` 集合；`stage` 讓 Central 與 runbook 知道失敗點 |

`target_version` 以嚴格 pattern 驗證（`^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.]+)?$`，長度 5..64（實作值）），避免任意字串進入檔名組合。**版本字串在 daemon 端只用於「與 manifest 比對」，不用於組合下載路徑**——路徑一律取自 manifest 中 Central 給的 allowlisted filename。

### 新增 error code

`UPDATE_NOT_ALLOWED`（非 allowlisted release／版本不存在於 manifest／降級被拒）、`UPDATE_DOWNLOAD_FAILED`、`UPDATE_CHECKSUM_MISMATCH`、`UPDATE_HEALTHCHECK_FAILED`、`UPDATE_ROLLED_BACK`、`UPDATE_IN_PROGRESS`。加入三語言的 error code 集合與 `contracts/v1/schemas/control-envelope.schema.json` 的 enum（若該檔以 enum 列舉 code）。

### Fixtures

- **valid**：`daemon-update.json`（僅 `target_version`）、`daemon-update-result-succeeded.json`、`daemon-update-result-rolled-back.json`（含 `stage` 與 `error_code`）。
- **invalid**（每個都必須被三語言拒絕）：`daemon-update-with-url.json`（多一個 `url` 欄位 → `additionalProperties:false`）、`daemon-update-with-binary-path.json`、`daemon-update-bad-version.json`（`../../etc/passwd`、`latest`、空字串）、`daemon-update-result-bad-status.json`（enum 外）、`daemon-update-result-bad-stage.json`、`daemon-update-result-naive-time.json`（若 envelope 帶時間欄位）。

`contracts/v1/fixtures/manifest.json` 同步新增條目；`contracts/CHANGELOG.md` 新增 **1.4.0（compatible）** 段落，說明「additive，`version` 整數仍為 `1`」，並明確寫出「payload 不含 URL/path 是刻意的安全設計」。

### 測試

- Python：`backend/tests/contract/` 對新 fixtures 的 accept/reject；`decode_control` 對 `daemon.update_result` 的 payload 驗證。
- Go：`internal/protocol/codec_test.go` 的 `TestContract*` 覆蓋新型別與所有 invalid fixtures；`build_test.go` 驗證 `daemon.update_result` 可正確建構且不超 frame 上限（沿用 1.3.1 的 `MaxFilePayload` 分流邏輯——update 訊息屬**小型控制訊息**，維持 64 KiB）。
- TypeScript：`src/protocol/contract.test.ts` 同步（browser 不會收到 `daemon.*`，但 codec 的 allowlist 與 error code 集合仍須一致）。

**對應需求**：FR-INSTALL-005、SEC-002、tech §12.2/§12.3。

---

## P4-03（Gate）：RBAC 完整化

### 現況與三個實際缺口

已存在：`app/services/rbac.py`（10 個 action key + `role_actions()`／`has_action()`）、`app/api/http/deps.py` 的 `require_action()`（套在 nodes/sessions/enrollment/files 共 19 個 route）、`app/api/ws/terminal.py` 的 `has_action(user, TERMINAL_OPERATE)`（line 91）與 `has_action(user, TERMINAL_TAKEOVER)`（line 187）、seed migration `0002`/`0006`/`0007`、前端 `dto.ts` 的 9 個 `ACTION_*` 常數與 `auth.hasPermission()`。

**缺口 1 — `audit.view` 是死權限**。`0002_seed_roles.py` 已把 `audit.view` 給 Admin，`rbac.py` 已定義 `AUDIT_VIEW`，但 grep 全 repo 沒有任何 endpoint 使用它。P4-05 會建立 audit 端點，但**在 P4-03 就必須把它納入矩陣測試的骨架**（先以「端點不存在 → 測試標記 pending，端點出現即必須通過」的方式綁定，避免 P4-05 上線時漏掉授權）。

**缺口 2 — 沒有資源範圍/owner 規則（最高風險）**。目前 `session.terminate` 只檢查 role，因此**任何 Developer 都能終止其他人的 session**；`session.view` 讓任何角色能 attach 任何 session；`terminal.takeover` 讓任何 Developer 能搶走任何人的 writer。`TerminalSession` 已有 `user_id` 欄位（models.py:163），資料在，只是沒被用來授權。research §P4-W1 明確要求「資源範圍與 owner 規則明確，尤其 attach/takeover/terminate/read file」。

**缺口 3 — 沒有 single source of truth 與矩陣測試**。permission 定義散在 `0002`/`0006`/`0007` 三個 migration 的字串陣列、`rbac.py` 的常數、`dto.ts` 的常數三處，沒有任何測試斷言「seed 的 action 集合 == `rbac.py` 定義的集合 == 前端常數集合」，也沒有「每個 endpoint × 三角色」的窮舉測試。

### 交付內容

#### 1. 單一 source of truth

在 `app/services/rbac.py` 建立**宣告式 matrix**（既有常數保留，新增結構化定義）：

```
ROLE_ACTIONS: dict[str, frozenset[str]]   # Admin / Developer / Viewer → actions
ALL_ACTIONS: frozenset[str]               # 所有已知 action（migration 與前端的對照基準）
```

並新增三個一致性測試：
- `ROLE_ACTIONS` 與 **seed migration 實際套用後的 DB 內容**一致（DB 測試，跑完 `upgrade head` 後比對）。
- `ALL_ACTIONS` 與 `frontend/src/api/dto.ts` 的 `ACTION_*` 常數集合一致（以 pytest 讀取該檔或以 vitest 讀取匯出的 JSON；**擇一但必須自動化**，避免手動同步）。
- 每個 `ALL_ACTIONS` 成員至少被一個 endpoint 或 WS handler 使用（防止再出現 `audit.view` 這類死權限；允許以明確 allowlist 標註「本期尚未實作」）。

同時產生一份**由程式生成**的 `docs/permission-matrix.md`（測試斷言檔案內容與 `ROLE_ACTIONS` 一致，避免文件腐化），對照 PRD §8.1 的 8 列功能。

#### 2. `app/services/authz.py`（新增，resource scope 層）

`require_action()` 保留為 action 層；新增 resource 層的單一判斷處：

| 函式 | 規則（ADR 0016 定案） |
|---|---|
| `authorize_session_view(user, session)` | 具 `session.view` → 允許（沿用 P2「Viewer 唯讀 attach」） |
| `authorize_session_terminate(user, session)` | `session.terminate` **且**（`session.user_id == user.id` **或** 具 `node.manage`）；否則 403 `FORBIDDEN` |
| `authorize_session_write(user, session)` | `terminal.operate` **且**（owner **或** 具 `terminal.takeover`）；決定 handshake 時的 writer 資格 |
| `authorize_session_takeover(user, session)` | **與 write 資格相同**（實作後修訂，ADR 0016 amendment）：`terminal.operate` 且（owner 或具 `terminal.takeover`）。原設計「owner 或 takeover」在**降級**情境有破口——被降為 Viewer 的建立者仍「擁有」該 session，owner 分支會讓他繼續接管。成功必寫 audit |
| `authorize_file_browse(user, session)` | `file.browse` **且** `authorize_session_view` 通過（檔案存取範圍由 session 決定，沿用 P3） |
| `authorize_node_manage(user, node)` | `node.manage`（node 無 owner 概念；保留函式使呼叫點一致） |

所有函式在拒絕時 raise 同一個 `ApiError("FORBIDDEN", "You do not have permission for this action", 403)`——**訊息不得洩漏資源是否存在或屬於誰**。對於「資源不存在」與「無權存取」的合併策略沿用 P3 的 existence-probe collapse 原則：先確認 `session.view` 通過，再回 404；否則一律 403。

`session.create` 的 owner 由 server 指派：`user_id` 取自認證使用者，**不接受 client 傳入**（檢查現有 `app/api/http/sessions.py` 已如此，補測試鎖住）。

#### 3. 四面一致

| 面 | 變更 |
|---|---|
| HTTP | `sessions.py` 的 `terminate`／`delete`／`attach` route 在 `require_action()` 之後呼叫對應的 `authz` 函式；`files.py` 三個端點呼叫 `authorize_file_browse` |
| Browser WS | `api/ws/terminal.py` 移除就地的 `has_action()` 判斷（line 91／187），改呼叫 `authorize_session_write`／`authorize_session_takeover`；**每個 inbound 控制訊息都重新判斷**（不只 handshake），viewer 送 input 或 `terminal.control_acquire` 一律丟棄並記 metric |
| Daemon WS | `api/ws/nodes.py` 的授權維持 Ed25519 credential（非 user RBAC），但需補測試證明**daemon 連線無法冒用任何 user action**（例如 daemon 送 `session.stop` 不會繞過 user 授權——Central 只接受 daemon 的回應與 data frame，不接受它發起 user 級 mutation） |
| UI | `/api/auth/me` 回傳 server 計算的 capability 清單（`actions: string[]`，並可含 per-session capability 由 session detail 提供如 `can_terminate`/`can_write`）；`auth.hasPermission()` 只讀該清單，**前端不重寫 owner 規則**；每個以 `v-if` 隱藏的操作都必須有對應的 server 403 測試 |

#### 4. Seed migration —— **實作後確認不需要**

> **實作結果（2026-07-25）**：比對 `0002`+`0006`+`0007` 疊加後的實際 seed 與 `ROLE_ACTIONS`，**三角色完全一致**；且 P4 未新增任何 action key（audit 用既有 `audit.view`、favorites 用 `session.create`、node update 用 `node.manage`、metrics export 用 scrape token 而非 action）。**缺口不是 seeding 而是 enforcement**，因此不建立空的 `0008`（只會在 migration 歷史留下無效果的 revision）。改以 `test_role_actions_match_the_seeded_database` 斷言宣告與 DB 一致；`0008` 編號釋出給 P4-04 的 audit 索引。ADR 0016 已記錄此決定。

若**未來**需要調整任何角色的 action，一律新增 migration（沿用 `0006`/`0007` 的 `_add_action`／`_remove_action` idempotent 模式），**不修改既有 migration**，並必測四種情境：

- **clean**：空 DB `upgrade head` → 三角色 action 集合 == `ROLE_ACTIONS`。
- **repeat**：重跑不產生重複 action、不改變集合。
- **prior data**：先建立既有 users/roles 再 upgrade → 現有使用者權限正確且未被破壞。
- **contraction**：若移除某 action，upgrade 後該 action 確實消失，且 downgrade 可還原（測 `upgrade → downgrade → upgrade`）。

#### 5. Allow/deny 矩陣測試（Gate 的核心）

建立 `backend/tests/db/test_permission_matrix.py`，以**參數化窮舉**覆蓋：

- **每個 HTTP endpoint × 三角色**：預期 2xx/403 由 `ROLE_ACTIONS` + owner 規則推導（測試自 route table 產生清單，**新增 route 而未加入矩陣即測試失敗**——這是防止未來漏授權的機制）。
- **每個 browser WS 控制訊息型別 × 三角色 × (owner / 非 owner)**：`session.attach`、`terminal.resize`、`terminal.control_acquire`、`terminal.control_release`、`session.stop`、binary input frame。
- **Viewer forged mutation**：Viewer 直接以 HTTP 呼叫 create/terminate/enable/revoke/rotate/remove/enrollment，以及在 WS 上送 input 與 `control_acquire` → **一律失敗**，且不產生任何狀態變更（斷言 DB 未變、daemon 未收到任何 frame，沿用 P3 `fake.calls == []` 的模式）。
- **Owner 越權**：Developer A 嘗試 terminate／takeover Developer B 的 session → 403，且 audit 不記錄成功事件。
- **停用帳號與 role 變更即時生效**：`is_active=False` 或 role 變更後，下一個 request 即失效（`rbac.py` 註解已宣稱此行為，補測試鎖住）；token_version 撤銷路徑沿用 P1 測試。

### 測試與命令

```
make typecheck lint
uv run --project backend pytest backend/tests/db/test_permission_matrix.py -q
make test-db                       # 含 0008 seed 四情境
cd backend && alembic upgrade head && alembic downgrade 0007 && alembic upgrade head
cd frontend && npm run test:unit -- --run      # capability 來源、UI 隱藏測試
```

### Gate 判定

以下全綠才算通過，未通過則 **P4-05/P4-06/P4-09/P4-10/P4-13 的任何新端點不得合併**：

- [x] `ROLE_ACTIONS` 與 DB seed、前端常數三方一致（自動化斷言）。
- [x] 每個 endpoint 與每個 WS message type 都在矩陣測試中出現（route table 對照，無遺漏）。
- [x] attach/takeover/terminate/file browse 的 owner 規則有 allow 與 deny 兩側測試。
- [x] Viewer forged mutation 全部失敗且無副作用（DB 未變、daemon 未收 frame）。
- [x] ~~seed migration 四情境~~ → **確認不需要 migration**（宣告與 seed 已一致，改以 DB 斷言保證；見上文 §4）。
- [x] `audit.view` 已明確標註於 `rbac.UNENFORCED_ACTIONS`（待 P4-05 綁定；該測試雙向失敗，P4-05 合併時必須移除標註）。
- [x] 沒有任何授權判斷存在於 `authz.py`／`deps.py` 之外（`test_authorization_logic_is_confined_to_two_modules` 自動掃描，不再靠慣例）。

**對應需求**：FR-AUTH-001/002、FR-SESSION-005/007、SEC-006、PRD §8.1、PRD §19 條目 20（重要操作 audit 的前提是授權正確）、tech §14。
