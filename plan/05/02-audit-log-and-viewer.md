# 02 — Audit Log 完整化與 Admin 查詢介面（P4-W2）

涵蓋 ticket **P4-04**（audit 完整化）與 **P4-05**（audit 查詢 API + Admin UI）。對應 `research/01/05` §P4-W2、SEC-006、tech §13.3、PRD §19 條目 20（「所有重要操作均有 Audit Log」）。

---

## 現況

**已有的**：`app/services/audit.py` 是單一寫入點，`AuditService.record()` 已對 metadata 套 `redact_mapping()`（`app/logging.py`，比對 9 個敏感 key 片段）。已定義 17 個 action：P1 的 `user.login`／`user.logout`／`enrollment.create|revoke|use`／`node.register|disable|remove`／`credential.revoke`，P2 的 `session.create|attach|takeover|terminate|failed`，P3 的 `file.sensitive_read_denied`。`AuditLog` 模型（models.py:201）有 `user_id`／`node_id`／`session_id`／`action`／`audit_metadata`(JSONB)／`created_at`(timezone-aware)，索引為 `action`、`created_at`（`0001`）與 `node_id`（`0004`）。

**四個缺口**：

1. **`request_id` 沒有進 audit**。`app/logging.py` 的 `request_id_var` contextvar 由 `RequestIdMiddleware` 設定並進入每筆 log，但 `AuditService.record()` 不讀它。research §P4-W2 明確要求 audit 帶「actor/resource/request ID」——目前只有前兩者。少了 request_id，就無法把一筆 audit 與當時的 log 串起來除錯。
2. **`daemon.update` 事件不存在**。SEC-006 的八項清單最後一項是「Daemon 更新」，tech §13.3 亦列出；P4-10 會實作 update，audit 必須同步。
3. **無法查詢**。沒有任何 audit 查詢 API、沒有 repository 查詢方法（`AuditRepository` 只有 `add()`）、沒有 UI。`audit.view` 權限已 seed 但無端點使用（見 `01-rbac-and-protocol.md` 缺口 1）。
4. **查詢索引不足**。`user_id` 無索引（依 actor 過濾會全表掃描）；沒有支援「時間範圍 + action」或「時間範圍 + actor」的複合索引。retention 與 backup 也尚無決策落地。

---

## P4-04：Audit 完整化

### 1. Coverage 定稿與單一性

以 SEC-006 八項 + tech §13.3 十一項為基準，產出最終 coverage 表並以測試鎖住：

| 事件 | action | 觸發點 | resource 欄位 | metadata（safe） |
|---|---|---|---|---|
| 登入成功／失敗 | `user.login` | `services/auth.py` | `user_id` | `result`、`username`（失敗時記嘗試的 username，**不記密碼**）、`request_id` |
| 登出 | `user.logout` | `services/auth.py` | `user_id` | `request_id` |
| Token 撤銷／refresh 失效 | `user.session_revoked` ★新增 | `services/auth.py` | `user_id` | `reason`、`request_id` |
| 建立／撤銷／使用 enrollment token | `enrollment.create|revoke|use` | `services/enrollment.py` | `user_id`／`node_id` | `token_id`、`expires_at`、`max_uses`；**不記 token 明文** |
| Node 註冊 | `node.register` | `services/nodes.py` | `node_id` | `name`、`architecture`、`daemon_version` |
| Node 停用／啟用／移除 | `node.disable`／`node.enable` ★新增／`node.remove` | `services/nodes.py` | `user_id`+`node_id` | `request_id` |
| Credential 撤銷／輪替 | `credential.revoke`／`credential.rotate` ★新增 | `services/nodes.py` | `user_id`+`node_id` | `algorithm`、`version`；**不記金鑰** |
| Session 建立／attach／takeover／終止／失敗 | `session.create|attach|takeover|terminate|failed` | `services/sessions.py`、`api/ws/terminal.py` | `user_id`+`node_id`+`session_id` | `runtime`、`status`、`from_user_id`（takeover）、`exit_code`／`error_code`（failed）；**不記 terminal bytes、不記 workspace 絕對路徑全文**（僅記 workspace 目錄名或 root 識別） |
| 敏感檔讀取被拒 | `file.sensitive_read_denied` | `services/files.py` | 三者 | `classification`、`extension`（沿用 P3 決定：**不記 rel_path/檔名主體**） |
| Daemon 更新 | `daemon.update_started`／`daemon.update_result` ★新增 | `services/releases.py`／`api/ws/nodes.py` | `user_id`(觸發者)+`node_id` | `from_version`、`to_version`、`status`、`stage`、`error_code` |
| 授權被拒（安全事件） | `authz.denied` ★新增 | `services/authz.py`／`deps.py` | `user_id`(+resource) | `action`、`resource_type`、`request_id`；**只記安全相關拒絕**（見下） |

★ = 本期新增。`authz.denied` 是 research「login/security event」的落地：**只在 mutation 或跨 owner 存取被拒時記錄**（例如 Viewer 嘗試 terminate、Developer 嘗試 takeover 他人 session），一般讀取的 403 與 validation 422 **不記**，否則 audit 會被雜訊淹沒。以設定值控制是否啟用，預設啟用。

**單一性保證**：一個重要操作只能產生一筆 audit。實作規則：audit 一律由 **service 層**寫入，API 層不得再寫；`api/ws/terminal.py` 這類沒有 service 的路徑，以明確註解標示其為該事件的唯一寫入點。測試以「執行一次操作 → 斷言該 action 的筆數恰為 1」鎖住（P2 已有部分此類測試，本期擴及全部事件）。

### 2. `request_id` 與 actor/resource

`AuditService.record()` 自動補 `request_id`：

- HTTP 觸發：讀 `app.logging.request_id_var`（middleware 已設）。
- daemon relay 觸發（例如 `daemon.update_result`）：由呼叫方傳入該次 `registry.request()` 的 request_id；若無（daemon 主動上報）則記 `None` 並在 metadata 標 `source: "daemon"`。
- 背景任務觸發：記 `None` 並標 `source`。

`request_id` 放在 metadata（`{"request_id": ...}`）而非新增欄位——避免為單一欄位再開一次 migration，且 metadata 已是 JSONB 可索引。若查詢效能不足，ADR 0016 記錄改為欄位的條件。

### 3. Metadata 最小化與 redaction 強化

- **禁止清單**（測試斷言）：terminal bytes、file content、目錄清單、search keyword 明文、password、任何 token 明文、Ed25519 私鑰、完整 server absolute path（workspace 只記目錄名或 root id）、Authorization header。
- `redact_mapping()` 目前只做**淺層**替換（`app/logging.py`）。P4 擴充為**遞迴**處理嵌套 dict/list，並新增 key 片段（`key`、`pepper` 已有；補 `bearer`、`cookie`、`apikey`、`api_key`、`session_token`）。同時新增**值層級**的防護：對明顯的 JWT／`enroll_` 前綴字串做遮蔽，作為 defence in depth（primary rule 仍是不要傳進來）。
- 新增 metadata **大小上限**（如 4 KiB）：超過即截斷並標 `truncated: true`，防止意外把大 payload 塞進 audit。
- 負面測試：刻意傳入含 `password`／`token`／巨大字串／嵌套 secret 的 metadata，斷言落地後已遮蔽/截斷。

### 4. Migration `0009`：查詢索引

- `ix_audit_logs_user_id`（缺）。
- 複合索引 `ix_audit_logs_created_at_action`（`created_at DESC, action`）與 `ix_audit_logs_created_at_user`（`created_at DESC, user_id`），對應 UI 的主要查詢模式（時間倒序 + 過濾）。
- 附 upgrade→downgrade→upgrade 測試；並以 `EXPLAIN` 或至少「大量資料下查詢時間有界」的測試佐證（可在 DB 測試中插入 10k 筆後量測，門檻寬鬆但能抓到全表掃描）。

### 5. Retention 與 backup 決策落地

- 設定：`audit_retention_days`（預設 365）、`node_metric_retention_days`（預設 30，見 `04-observability-and-capacity.md`）。
- **不做自動刪除排程**（避免在 MVP 引入背景 scheduler 與誤刪風險）。改為提供 `scripts/p4/prune-retention.sh`（呼叫一個明確的 CLI 子命令，dry-run 為預設，需 `--yes` 才執行），並在 `docs/runbooks/backup-restore.md` 記錄執行時機與前置備份要求。
- backup 範圍與「不含 terminal raw log」的驗證屬 P4-12（`07-verification-and-exit.md`），此處只定義策略與設定。

### 測試（P4-04）

- 每個 coverage 表事件：執行操作 → 恰一筆 audit、欄位齊備（actor/resource/`request_id`/aware `created_at`）、metadata 通過禁止清單斷言。
- redaction：淺層 + 嵌套 + 值層級 + 超長截斷。
- 失敗路徑：audit 寫入失敗不阻斷使用者請求（沿用 P3 的 `filesystem_audit_error_total` 模式，擴為通用 `audit_error_total`）。
- migration `0009` up/down/up + 大量資料查詢時間有界。
- `authz.denied`：Viewer forged mutation 產生一筆安全事件；一般讀取 403 不產生。

---

## P4-05：Audit 查詢 API 與 Admin UI

### API

`GET /api/audit`（`require_action(AUDIT_VIEW)`，Admin only）：

| Query 參數 | 規則 |
|---|---|
| `action` | 可重複；必須屬於已知 action 集合，未知值回 422（不做模糊比對，避免變成任意查詢） |
| `user_id`／`node_id`／`session_id` | UUID，選填 |
| `from`／`to` | RFC 3339 UTC；**naive time 一律 422**；範圍上限 90 天（§6），超出回 422 |
| `limit` | 預設 50，上限 200 |
| `cursor` | opaque cursor（`created_at` + `id` 複合，穩定分頁）；不用 offset，避免大 offset 掃描 |

回應：`{items: [...], next_cursor: str | null}`。每個 item：`id`、`action`、`created_at`（RFC 3339 `Z`）、`user`（`{id, username, display_name}` 或 `null`）、`node`（`{id, name}` 或 `null`）、`session_id`、`metadata`（**已 redact 的安全 metadata**，且不含前述禁止清單任何項）、`request_id`。

**安全要點**：
- 回應不得洩漏被刪除/停用資源的敏感資訊；user/node 以 join 補顯示名稱，找不到則回 `null` 而非錯誤。
- metadata 直接回傳 DB 內容——因此 **P4-04 的 metadata 最小化是這個端點的安全前提**；補一個 API 層的最終 sanitizer 作為 defence in depth（斷言 key 不在禁止清單）。
- 查詢本身**不寫 audit**（避免 Admin 查閱行為造成 audit 自我膨脹）；ADR 0016 記錄此決定與替代方案（若合規需求出現再改）。

`services/audit_query.py` 擁有查詢邏輯（bounded、參數驗證、cursor 編解碼）；`repositories/audit.py` 新增 `list()`。

### Admin UI（`views/AuditView.vue` + `stores/audit.ts`）

- 路由 `/audit`，`AppLayout` nav 在 `hasPermission('audit.view')` 時顯示（**server 端仍必須 403**，UI 隱藏不是授權）。
- Filter 區：action 多選（來自已知 action 集合）、actor（使用者選單或 UUID 輸入）、node、時間範圍（預設近 24 小時，快捷：1h/24h/7d/自訂），套用/清除；filter 狀態進 URL query 以便分享與重載。
- 表格：時間（**本地時區 + 明確時區標示**，沿用 `utils/time.ts` 的 `formatInstant`）、action（人類可讀標籤 + 原始 code）、actor、resource（node/session 連結）、`request_id`（可複製）、metadata（展開檢視，以 `<pre>` 呈現已 redact 的 JSON）。
- 分頁：「載入更多」以 cursor 前進；顯示已載入筆數；**不假造總筆數**。
- **狀態矩陣（全部必測）**：`idle`／`loading`（骨架）／`success`／`empty`（「此條件下沒有紀錄」+ 放寬條件建議）／`forbidden`（非 Admin 直接進入 URL → 明確訊息 + 返回）／`error`（含 `request_id` 與重試）／`partial`（後續頁失敗時保留已載入內容並標示）。狀態不可只靠顏色。
- a11y：表格有 caption/`scope`、filter 有 label、鍵盤可完成「設定條件 → 套用 → 展開一列 metadata → 載入更多」全流程、focus 可見、`aria-live` 播報結果筆數變化。

### 測試（P4-05）

- **Backend**：三角色 allow/deny（僅 Admin 2xx）；未知 action／naive time／超範圍／超 limit → 422；cursor 分頁穩定（新增資料不造成重複或跳過，以固定時鐘測）；join 缺失資源回 `null`；回應 sanitizer 斷言無禁止清單 key；查詢不寫 audit。
- **Frontend**：`stores/audit.ts`（filter → query、cursor 前進、in-flight abort、切換 filter 丟棄過期回應）、`AuditView` 各狀態渲染、時區格式化、鍵盤流程、非 Admin 的 forbidden 畫面。
- **E2E**（併入 P4-15 的 `p4.yml`）：Admin 登入 → `/audit` → 以 action 過濾 → 展開一筆 metadata（斷言 DOM 內無 token/password/檔案內容）→ 載入更多 → 以 Developer 帳號直接開 `/audit` 得到 forbidden。

**對應需求**：FR-AUTH-002（Audit 僅 Admin）、SEC-006、tech §13.3、PRD §10（前端頁面）、PRD §19 條目 20。
