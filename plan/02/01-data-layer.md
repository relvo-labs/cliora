# 01 — P1-W1 Central 分層與資料層

對應 `research/01/02-phase-1-node-control-plane.md` §P1-W1。涵蓋 ticket **P1-02**（protocol v1.1，因跨語言先凍結）、**P1-03**（分層與 DB 基礎）、**P1-04**（schema 與 seed）。

## 目標

把 P0 的扁平 `backend/app`（module-level `registry`、無 DB）升級為分 `api / services / repositories / db` 的 Central，並建立可 clean upgrade／重跑／downgrade 的 PostgreSQL schema，所有 timestamp tz-aware。此層是 P1 其餘工作的地基。

## P1-02：Protocol v1.1 契約（先凍結）

沿用 P0 envelope（`version/type/request_id/node_id/timestamp/payload`，`additionalProperties:false`，UTC `Z` timestamp，ULID request_id）。**版本仍為整數 `1`**，以 additive、向後相容方式新增訊息型別；在 `contracts/CHANGELOG.md` 標記為 `1.1.0 — compatible`。

新增 control 型別（tech §12.2）：

```text
node.register          daemon→central：完整 metadata + runtimes[] + workspace_roots[]（PRD §9.1）
node.registered        central→daemon：確認並回傳 canonical node_id、伺服器時間
node.system_info       daemon→central：系統資訊更新（OS/arch/kernel/run_user）
node.runtime_status    daemon→central：runtime 偵測結果更新（claude/codex available/version/path）
node.shutdown          daemon→central：graceful shutdown 前的 deregister 通知
daemon.doctor          central→daemon：請求自我診斷（P1 可選；doctor 主要為本機 CLI）
daemon.doctor_result   daemon→central：診斷結果
daemon.version         daemon→central：版本回報（亦可併入 heartbeat）
```

新增 error codes（tech §12.3）：`NODE_DISABLED`、`RUNTIME_NOT_FOUND`、`RUNTIME_DISABLED`、`RUNTIME_NOT_EXECUTABLE`、`ENROLLMENT_TOKEN_INVALID`、`NODE_AUTH_FAILED`。沿用 P0 既有 15 codes。

規則與邊界：

- `node.register` payload 只允許 typed 欄位：`name`、`hostname`、`os`、`os_version`、`architecture`（`amd64|arm64`）、`daemon_version`、`run_user`、`runtimes[]`（`{runtime: "claude"|"codex", available, version?, binary_path?, checked_at}`）、`workspace_roots[]`（`{path, display_name?, is_enabled}`）。禁止任意 command、argv、env、shell。
- `node.heartbeat` payload 擴充為 `{daemon_version, active_sessions, resources?: {cpu_usage, memory_usage, load_average?, disk_usage?, daemon_uptime?}}`，維持 P0 已送的 `daemon_version`/`active_sessions`。
- **事件 ID**：P0 daemon 目前送固定 placeholder ULID（`01K0EVENTFHJKMNPQRSTVWXYZ0`）。P1 必須改為每事件唯一 ID（純 event 用自己的 event ID，不借用 request ID）；此為 P1-02 的修正項。
- enrollment 的 token→credential 交換走 **HTTP**（見 `03-enrollment-credential.md`），不進 control envelope；`node.register` 是認證連線建立**之後**的 metadata 上報，此時 `node_id` 已存在。

產物與測試（延續 P0 契約紀律）：

```text
contracts/v1/schemas/messages/node-register.schema.json
contracts/v1/schemas/messages/node-heartbeat.schema.json
contracts/v1/schemas/messages/node-runtime-status.schema.json
contracts/v1/schemas/messages/node-system-info.schema.json
contracts/v1/fixtures/valid/node-register.json …
contracts/v1/fixtures/invalid/node-register-forbidden-command.json、bad-architecture、naive-timestamp …
contracts/v1/fixtures/manifest.json（新增 accept/reject 條目）
```

Python（`app/protocol/codec.py`）、Go（`daemon/internal/protocol/codec.go` 的 `allowedTypes` 與 `ValidateControl`）、TS（`frontend/src/protocol`）三 consumer 同步跑 manifest；缺 consumer 即 CI 失敗。

驗收：三語言對同一批新 fixtures 有相同 accept/reject；新型別的 forbidden 欄位、錯誤 architecture、naive/offset timestamp、未知欄位全被拒；`CHANGELOG.md` 標明 compatible。

## P1-03：分層 scaffold 與 DB 基礎

建立結構（不刪除 P0 relay，保留於 flag 之後）：

```text
backend/app/
  api/            http/（auth、nodes、enrollment、health routers）、ws/（daemon gateway、ws-ticket）
  services/       auth、rbac、node、enrollment、registry、audit
  repositories/   user、node、enrollment、audit（唯一 DB 存取層）
  db/             engine.py、session.py、base.py、models/、alembic/
  security/       password（Argon2id）、jwt、hmac、redaction
  settings.py     擴充：database_url、jwt_*、argon2_*、token TTL、heartbeat/status 邊界
  main.py         組裝 app、lifespan（engine dispose）、middleware（request-id、error）
```

實作規則：

- **DB engine**：SQLAlchemy 2 async（`create_async_engine` + asyncpg），連線字串來自 `CLIORA_DATABASE_URL`；`AsyncSession` 以 dependency 注入，request/單元 use case 一個 session、一個 transaction。engine 於 lifespan 建立與 dispose。
- **repository 邊界**：service 不直接觸碰 ORM query，一律經 repository；terminal bytes 與 secret 明文永不入 DB。
- **時間**：所有 model 的 timestamp 使用 `TIMESTAMP(timezone=True)`，Python 端一律 aware UTC；DTO 序列化為 RFC 3339 `Z`。禁止 naive datetime 進 DB 或 DTO（以測試強制）。
- **health/readiness**：保留 `GET /healthz`；`GET /readyz` 擴充為檢查 DB 連線（`SELECT 1`）與 migration head 是否套用，回 `{status, database, migration}`。
- **request-id 與 error**：middleware 為每個 request 產生/沿用 `request_id`；統一 exception handler 映射為 stable machine code + safe message + `request_id`，不回傳 stack、secret、內部 path、SQL。
- **structured logging**：JSON log，common fields `timestamp, level, service, request_id, user_id, node_id, event, message, error`（tech §18.3）；redaction 過濾 password、token、secret、Authorization header 與 terminal content。

驗收：`app` 可在無 daemon 下啟動並回 health/readiness；統一 error handler 對 400/401/403/404/409/500 都回 typed code + request_id；log 掃描確認無 secret；mypy strict 通過。

## P1-04：Schema migration 與 role seed

以 Alembic 建立初始 migration（欄位依 PRD §12 / tech §13）。所有表主鍵 UUID、時間 tz-aware。

| 表 | 關鍵欄位 | 約束/索引 |
|---|---|---|
| `roles` | id, name（`Admin`/`Developer`/`Viewer`）, permissions(jsonb), created_at | name unique |
| `users` | id, username, password_hash, display_name, role_id→roles, is_active, created_at, updated_at | username unique；role_id FK |
| `nodes` | id, name, hostname, status, os, os_version, architecture, daemon_version, run_user, metadata(jsonb), last_seen_at, registered_at, is_enabled, deleted_at(null) | name/hostname 查詢索引；status 查詢用（值仍以 registry 動態計算，DB 存最後已知）；`deleted_at` 為軟刪除標記，預設查詢排除已刪除列 |
| `node_runtimes` | id, node_id→nodes, runtime(`claude`/`codex`), available, version, binary_path, checked_at | (node_id, runtime) unique |
| `node_workspace_roots` | id, node_id→nodes, path, display_name, is_enabled | (node_id, path) unique |
| `enrollment_tokens` | id, token_hash, created_by→users, expires_at, max_uses, used_count, is_active, created_at | token_hash unique；used_count 併發安全（見 P1-08） |
| `node_credentials` | id, node_id→nodes, secret_hash, algorithm, version, issued_at, revoked_at(null) | node_id + version；只存 hash（本規劃新增，PRD/tech 未明列，記 ADR 0008） |
| `audit_logs` | id, user_id, node_id, session_id, action, metadata(jsonb), created_at | action、created_at、node_id 索引 |

Migration 與 seed 規則：

- role seed 以**獨立 versioned migration** 寫入固定 `Admin/Developer/Viewer`（stable key），並填入 §8.1 權限矩陣為 `permissions` jsonb；**不在 startup 偷 seed**。首位 Admin 使用者以一次性 bootstrap migration 或明確 CLI 建立（密碼經 Argon2id），不硬編碼明文。
- migration 必須支援 clean upgrade、重跑（idempotent head 檢查）與可行的 downgrade；`node_credentials` 與 `audit_logs` 的 downgrade 不得遺留孤兒外鍵。
- `updated_at` 由 ORM `onupdate` 維護；DB 端可加 trigger 但需在測試中驗證一致。
- **Node 軟刪除（已確認決策）**：node 移除採軟刪除（設 `nodes.deleted_at`），保留該列與其 `node_runtimes`、`node_workspace_roots`、`audit_logs` 供稽核；不做破壞性 hard delete。repository 預設查詢一律過濾 `deleted_at IS NULL`；`node_id` 不重用。刪除語意與行為見 `05-registry-node-status.md`。

驗收（延續 research §P1-W1）：migration 可在乾淨 DB clean upgrade、重跑不報錯、支援的 downgrade 可回退；transaction rollback 測試（service 拋錯時無部分寫入）通過；aware timestamp round-trip 測試（Asia/Taipei 與非整點 offset 輸入、UTC 儲存、`Z` 輸出、expiry 相等邊界）通過；role seed 與權限矩陣一致性測試通過。
