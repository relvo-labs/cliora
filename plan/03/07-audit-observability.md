# 07 — P2-W7：Audit 與 Observability Slice

對應 `research/01/03-phase-2-session-terminal.md` §P2-W7。涵蓋 ticket **P2-15**。需求：SEC-002/003/006、FR-CONN-006、PRD §20、tech §18、MVP 驗收 #20。相關技能：`cliora-security-review`、`timezone-precision`。

## 目標

讓一次 session 操作可由 request/node/session/user ID 完整追查，重要操作留下最小化、redact、aware-timestamp 的 audit，且 **DB/log/audit 完全不含 terminal input/output 內容**（沿用 ADR 0004、`app/logging.py` docstring 規範）。metrics 呈現 session/terminal/queue 健康度。

## 現況（P2 起點）

- `app/services/audit.py`：`AuditService.record(action, *, user_id, node_id, session_id, metadata)`，寫入前經 `redact_mapping()`（`app/logging.py`，shallow、substring 比對 `_SENSITIVE`：password/token/secret/authorization/credential/pepper/challenge/private_key/signature）。action 常數在 `audit.py`（目前僅 P1 動作，**無 session/file action**）；`AuditLog.session_id` 欄位已存在。呼叫端負責 commit（unit-of-work）。
- P0 已有 in-process metrics/collector 慣例與 `terminal_queue_*`/`terminal_gap_*`/`terminal_reconnect_*` 名稱（`plan/01/05`）。

## 實作（P2-15）

**Audit 動作**（新增於 `services/audit.py` 常數，並在對應 service/relay 呼叫後 commit）：

| action | 觸發點 | metadata（safe，最小化） |
|---|---|---|
| `session.create` | P2-05 create 成功/失敗 | node_id、runtime、workspace（相對/root 顯示名，不洩完整絕對路徑細節）、result |
| `session.attach` | P2-09 handshake 成功 | session_id、role（writer/viewer） |
| `session.takeover` | P2-10 接管成功 | session_id、from_user、to_user |
| `session.terminate` | P2-06 terminate | session_id、graceful/forced、exit_code |
| `session.failed` | start_failed/daemon error | session_id、error code（safe message，不含 daemon 內部細節） |

**Redaction/privacy**：確認 audit/log **絕不含 terminal bytes**；runtime launch 的 argv 若含可能敏感值，於 log/audit 前 redact（擴充 `_SENSITIVE` 或於 service 端遮罩）；workspace 路徑以 root display name + 相對路徑呈現，避免洩漏不必要的 node 絕對路徑；ws-ticket、JWT、challenge 簽章一律不入 log（延續 P1 掃描）。

**Metrics**（tech §18，label 不含 user input / 高 cardinality request ID）：`running_sessions`、`active_terminal_connections`、`terminal_bytes_total`、`terminal_queue_bytes`、`terminal_queue_frames`、`terminal_queue_overflow_total`、`terminal_gap_total`、`terminal_reconnect_total`、`session_start_timeout_total`、`control_request_timeout_total`。daemon 側 heartbeat 已回報 active session count（P1）；P2 確認其反映真實 running 數。

**Correlation log**：session HTTP mutation 與 terminal WS 事件以 `request_id`（`RequestIdMiddleware`）+ `node_id` + `session_id` + `user_id` 結構化關聯，能從一個 request_id 串起 create→daemon start→attach→terminate 的整條路徑。

## 驗收

- 從單一 request ID 可追出一次 session 操作全鏈（create→start→attach→terminate）且恰一筆對應 audit／動作。
- redaction 測試：構造帶敏感 key 的 metadata、含敏感值的 argv、以及 Fake CLI 大量輸入輸出，掃描 DB（`terminal_sessions`/`session_connections`/`audit_logs`）與 log/metric，**確認無 terminal content、無 password/token/credential/private_key/ws-ticket/JWT**。
- metrics 在 burst/slow-client/斷線情境有預期變化且有界；label 無高 cardinality。
- 時間欄位 tz-aware round-trip，audit `created_at` 為 UTC 持久化、顯示才本地化。
