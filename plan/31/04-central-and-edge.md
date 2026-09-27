# 04 — Central 與 edge（`BP-04`／`BP-05`）

## `BP-04` Central

**寫入集：** 見 `00-…md` §5。重點檔：`backend/app/api/http/files.py`（一條新路由）、
`backend/app/services/files.py`（`preview_binary` 與其 helper）、`authz.py`（capability）、
`registry.py`（保存當下連線的 `binary_preview`）、`nodes.py`／`models.py`／migration `0022`、
`settings.py`、`audit.py`、`error_catalog.py`。

**前置：** `BP-02` 合併。可以用 fake daemon 先行，不必等 `BP-03`。

### 1. 端點

```
GET /api/sessions/{session_id}/files/binary-preview?path=<workspace-relative>
```

處理順序固定：

| # | 步驟 | 失敗時 |
|---|---|---|
| 1 | `require_action(FILE_BROWSE)` | 403 `FORBIDDEN` |
| 2 | `_resolve()`：session 存在 → `authorize_file_browse`（含 shell 拒絕）→ node 已連線（`services/files.py:182-198`） | 404／403／409 `NODE_OFFLINE` |
| 3 | `settings.binary_preview_enabled` | 409 `FILE_PREVIEW_UNSUPPORTED_NODE` |
| 4 | `registry.binary_preview(node_id)`：**當下連線**的註冊回報 | 409 `FILE_PREVIEW_UNSUPPORTED_NODE`。**不送任何 frame** |
| 5 | `_reject_rel_path(path)` | 400 `FILE_INVALID_PATH` |
| 6 | 每使用者 2、每節點 4 條串流的上限（process 內 semaphore） | 429 `FILE_PREVIEW_BUSY` |
| 7 | `preview_open`（15 秒） | in-band 拒絕 → `ApiError(code, 固定訊息, status, details={reason, size?, limit?})`；敏感拒絕走既有的 `_maybe_audit_denied`（`services/files.py:482-523`，**不改**） |
| 8 | `StreamingResponse`：逐塊 `preview_chunk`（每塊 10 秒，整體 60 秒） | 串流中斷 → 連線被截斷，`Content-Length` 不符讓瀏覽器得到 network error |
| 9 | generator 的 `finally`：若還沒送完，就送 `preview_close`（不等待結果，1 秒上限） | — |

HTTP 狀態對照：`FILE_DENIED` 403、`FILE_NOT_FOUND` 404、`FILE_PERMISSION_DENIED` 403、
`FILE_TOO_LARGE` 413、`FILE_PREVIEW_UNSUPPORTED` 415、`FILE_PREVIEW_INVALID` 422、
`FILE_PREVIEW_LIMIT` 413、`FILE_PREVIEW_DISABLED` 403、`FILE_PREVIEW_EXPIRED` 502（中途過期，
對使用者而言是暫時性失敗）、`NODE_BUSY` 503。
每個 code 保留自己的碼，因為每個的下一步都不同（`_map_error` 的既有原則，`services/files.py:555-562`）。

### 2. 回應標頭

ADR 0029 §6 的七個標頭為一組，缺一不可：`Content-Type: application/octet-stream`、
`X-Content-Type-Options: nosniff`、`Content-Length`、`Cache-Control: no-store, private` 加
`Vary: Authorization`、`Cross-Origin-Resource-Policy: same-origin`、
`Content-Security-Policy: sandbox; default-src 'none'`，以及 `X-Cliora-Preview-{Mime,Kind,Width,Height}`。
**沒有 `Content-Disposition`。**

`X-Cliora-Preview-Mime` 的值只能來自 wire enum。Central 在送出前再比對一次，
不在 enum 內就當作節點回應異常（502），不把節點給的字串原樣轉出。

### 3. 能力協商

- `registry` 在收到 `node.register` 時記下該連線的 `binary_preview`，連線關閉時清掉。
  **這是權威來源。**
- `nodes.binary_preview` 欄位（migration `0022`，`server_default=false`，有索引，
  與 `models.py:98-107` 同一模式）只供節點頁面顯示與「哪些節點開了預覽」這類查詢。
- `SessionSummary.capabilities.can_preview_binary`
  = `settings.binary_preview_enabled ∧ registry.binary_preview(node) ∧ may_browse_files(user, session)`，
  計算位置在 `authz.py:315-316` 旁。
  前端的既有上傳入口是在 client 端合成 `can_upload_files ∧ nodePosture.image_upload`
  （`SessionWorkspaceView.vue:476-480`）；本功能刻意在**伺服器端**合成，
  因為權威來源是當下連線，而那只有 Central 知道。
- 節點狀態變更（開關切換）沿用 `nodes.py:283-305` 的「變更才寫、並留稽核」模式。

### 4. 稽核

- 敏感拒絕：沿用，不改。
- 成功（OD-6）：新動作 `file.binary_preview`，metadata `{kind, mime, size_bytes}`，
  在**最後一塊送出之後**寫入並 commit。中途取消的不記成功，只記 metric。
  **`bytes` 不能當 key**（`audit.py:159` 會濾掉）。
- 稽核寫入失敗不讓請求失敗，而是計數並記 log，與 `_audit_upload` 同一種取捨（`services/files.py:472-480`）。
- `frontend/src/utils/auditActions.ts` 的標籤在 `BP-06` 加（「預覽圖片／PDF」）。

### 5. 記憶體與 log

- 每條串流同時最多持有一塊（≤512 KiB 原始、≤683 KiB base64）。
- `_observe("binary_preview", …)` 記 `kind`、`code`、`reason`、`chunks`、`bytes`、`duration_ms`。
  **不記 path**；`bytes` 是 log 欄位，不是稽核 metadata，所以可以用。

### 6. 設定

`settings.py` 新增：`binary_preview_enabled: bool = False`（OD-5）、
`file_preview_open_timeout_seconds = 15`、`file_preview_chunk_timeout_seconds = 10`、
`file_preview_total_seconds = 60`、`file_preview_streams_per_user = 2`、
`file_preview_streams_per_node = 4`。每個預算都要在 PRD `FR-CONN-006.AC-13` 公布
（`test_every_relay_budget_is_published`）。

### 7. 先寫的 RED 測試（`backend/tests/db/test_files_binary_preview_api.py` 等新檔）

| 測試 | 斷言 |
|---|---|
| `test_roles_matrix` | Viewer／Developer／Admin 可預覽白名單檔；沒有 `file.browse` 的使用者 403；看不到該 session 的使用者 403，且與「不存在」同一訊息 |
| `test_shell_session_refused` | 經 shell session 的 id → 403 |
| `test_old_daemon_is_never_asked` | fake daemon 的註冊沒有 `binary_preview` → 409，且 fake daemon **沒有收到任何 frame** |
| `test_flag_off_is_never_asked` | flag 關 → 409，同樣零 frame |
| `test_downgraded_reconnect` | 註冊 true → 斷線 → 以 false 重連 → 立即 409（不必等 DB） |
| `test_headers_are_a_set` | 七個標頭都在，而且沒有 `Content-Disposition` |
| `test_mime_header_comes_from_enum` | fake daemon 回 `image/svg+xml`（繞過 schema）→ 502，不轉出 |
| `test_cookie_without_bearer_is_401` | 帶 cookie、不帶 `Authorization` → 401 |
| `test_stream_backpressure` | 慢速 client：Central 在前一塊被消費前不送下一個 `preview_chunk` |
| `test_disconnect_sends_close` | client 中途斷線 → fake daemon 收到 `preview_close`；`_observe` 記 `CANCELLED` |
| `test_truncated_stream_is_error` | 第 3 塊時節點斷線 → 回應長度小於 `Content-Length` |
| `test_budget_total` | 60 秒整體預算到期 → 中止並送 close |
| `test_busy_limits` | 同一使用者第 3 條串流 → 429 |
| `test_sensitive_denial_audited_without_path` | `.env.png` → 稽核只有 classification 與 extension |
| `test_success_audit_has_no_path` | 成功稽核的 metadata keys 恰為 `{kind, mime, size_bytes}` |
| `test_log_has_no_path` | 以 `secret-project/plan.pdf` 請求，擷取所有 log，不含 `secret-project`、`plan` |
| `test_preview_does_not_imply_download` | （#71 合併後）`binary_preview:true, file_download:false` → 預覽 200、下載 403；反之亦然 |
| `test_read_content_unchanged` | 同一張 PNG 走 `/content` 仍是 in-band `FILE_BINARY` |
| `test_authz.py` 路由矩陣 | 新路由有列、Viewer 允許一列明文（#71 同一原則） |

### 8. 驗收清單

- [ ] §7 全綠；`make test-db` 綠。
- [ ] Migration `0022` 可升可降；降級只刪欄位（report-only，無資料損失）。
- [ ] `docs/error-catalog.md` 由 `render_error_catalog.py --check` 確認未漂移。
- [ ] `backend/app/api/http/files.py:203-215` 的 `/content` 沒有 diff。

### 9. 不在範圍

前端、edge 設定；把 Central 改成多 worker 共享 semaphore（現行是 process 內，
**假設**單一 process 服務一個節點的 WebSocket，未驗證，列為 `BP-OM-09`）。

---

## `BP-05` Edge（nginx）

**寫入集：** `deploy/nginx/nginx.conf`、`deploy/railway/nginx.conf.template`，以及
`make railway-check` 對應的 parity 測試。

**為什麼要有這一張：** `location /api/` 是 `proxy_buffering on`、沒有 `proxy_max_temp_file_size`
（`nginx.conf:163-175`、`railway/nginx.conf.template:159`）。依 nginx 文件的預設行為
（**本部署未實測**），回應超過記憶體 buffer 時會寫到 `proxy_temp_path` 的暫存檔。
對一條宣稱「不落地」的路徑來說，那就是落地。

**變更：** 加一個 regex location，其餘設定照抄 `/api/`。nginx 先記下最長的前綴匹配，
再檢查 regex，regex 命中就優先；`location /api/` 不是 `^~`，所以這條 regex 會勝出。
位置放在 `/api/` 旁邊，是為了閱讀：

```nginx
location ~ ^/api/sessions/[0-9a-fA-F-]{36}/files/binary-preview$ {
    proxy_pass http://cliora_backend;
    # … 與 /api/ 相同的 header 設定 …
    proxy_buffering off;            # 不緩衝，也就不會溢寫到 proxy_temp
    proxy_max_temp_file_size 0;     # 即使有人把上一行改回 on，也不寫暫存檔
    proxy_read_timeout 75s;         # 大於 Central 的 60 秒整體預算
}
```

**RED：** parity 測試先斷言兩份設定都有這個 location 與這兩個指令（先紅），再改設定。
**驗收：** `make railway-check` 綠；在 staging 以 16 MiB PDF 預覽時 `proxy_temp_path`
沒有新檔（`BP-OM-06` 記錄證據）。Railway 自己的 edge 會不會緩衝不在我們控制內，
量測結果寫進 `09-…md`。

**不在範圍：** 既有 `/content` 路徑的同一個溢寫風險。這裡只記錄，另開議題處理。
