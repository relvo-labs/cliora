# 06 — File Audit 與 Observability（P3-W3/W6 橫切）

涵蓋 ticket **P3-09**。把 filesystem 的稽核與可觀測性從 relay/read 抽出成獨立 slice，確保**內容永不入 audit/log/DB**，且有足夠 metric 佐證 relay bounds/timeout/cancel/disconnect。需求：SEC-006、SEC-004、tech §18（可觀測性）、`research/01/00` §5 security/privacy。

## 目標

- **Failed sensitive read 有 audit**（SEC-006）：使用者嘗試讀取被 `denied_patterns` 拒絕的敏感檔時，記一筆 audit metadata；**只記分類與相對識別，不記檔案內容、不記完整 server absolute path**。
- **Filesystem 可觀測**：list/read/search 的 latency、bounds-hit、cancel、daemon disconnect、error code 分佈皆有 metric。
- **Correlation log**：request/node/session/user id 串起一次 filesystem 操作，便於除錯，但不含敏感資料。

## 現況

- `app/services/audit.py`（P1/P2）已有 audit 寫入；`AuditLog` 具 `session_id` 欄位；P2 已寫 session create/attach/takeover/terminate/failed，且證明無 terminal content。P3 沿用同一服務新增 file 事件。
- P2 已有 daemon/backend metrics 與 correlation log 骨架（tech §18.1/18.2/18.3）。

## P3-09：Audit 事件

新增 audit action（沿用 SEC-006 清單「讀取敏感路徑失敗」）：

| action | 觸發 | 記錄欄位（safe） | 不記錄 |
|---|---|---|---|
| `file.sensitive_read_denied` | daemon 回 `FILE_DENIED`（sensitive 分類）且來自使用者 read 請求 | `user_id`、`node_id`、`session_id`、denial 分類（如 `dotenv`/`private_key`/`credential`）、**副檔名（僅副檔名，不含 `rel_path` 與檔名主體）**、`request_id`、tz-aware time | 檔案內容、`rel_path`/檔名主體、完整 server absolute path、workspace 全路徑 |

- **相對識別粒度（已確認：僅分類）**：sensitive denial **只記「分類 + 副檔名 + node/session/user/request_id + time」，不記 `rel_path`**（路徑本身可能含機密專案名/目錄名）。此為定案，不在 audit 留下可反推機密路徑的欄位；若未來確有調查需求，須另立 policy 變更並仍不含內容（列入 P4 follow-up，不在 P3 開此口）。
- 是否對**成功的一般檔案 read/list** 記 audit：MVP **不記**（量大且非 SEC-006 要求）；僅 sensitive-denied 必記。P4 若要 file access history 再擴充（列入 follow-up）。
- audit 寫入失敗不可吞掉使用者請求，但需記系統 error metric。

## Metrics（tech §18）

- **Backend**：`filesystem_request_total{op=list|read|search, code}`、`filesystem_request_duration_seconds{op}`（供 NFR latency 佐證）、`filesystem_relay_timeout_total`、`filesystem_relay_cancel_total`、`filesystem_node_disconnect_total`、`node_pending_requests`（沿用 P2，含 filesystem caller）。
- **Daemon**：`filesystem_list_entries`、`filesystem_search_scanned`、`filesystem_search_stopped_total{reason}`、`filesystem_read_bytes`（bounded）、`filesystem_denied_total{reason=sensitive|binary|oversize|permission}`。
- 皆為聚合計數/直方圖，**不含 path 內容或檔案內容**。

## Correlation log

- 一次 filesystem 操作以 `request_id` 串 Central→daemon→回應；log 欄位：`request_id`、`user_id`、`node_id`、`session_id`、`op`、`code`、`duration_ms`、`bytes`(bounded)/`entries`/`results`、`stopped_reason`。
- **redaction**：log 不印 path 內容、keyword（可能含機密）、檔案內容、token；keyword 若須記錄則 hash 或截斷（ADR 0015）。
- 沿用 P1/P2 的結構化 log 格式與 request_id 傳遞。

## 測試

- **Unit**：sensitive-denied 觸發一筆 audit，欄位齊全且**無內容/無完整絕對路徑**（斷言）；一般 read/list 不寫 audit；audit 寫入失敗記 error metric 但不失敗使用者請求。
- **Metric**：list/read/search 各 op 計數與 duration 觀測；timeout/cancel/disconnect 計數在對應情境遞增；denied_total 按 reason 分類。
- **Redaction 掃描**（併入 P3-10 security）：log/audit/DB dump 掃描確認無 file content、無 terminal content、無 keyword 明文、無不必要 absolute path、無 token/secret。

**對應需求**：SEC-006（敏感路徑讀取失敗須 audit）、SEC-004（敏感內容不外洩至任何 sink）、NFR latency（metric 佐證）、tech §18。
