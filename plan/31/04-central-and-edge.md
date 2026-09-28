# 04 — Central 與 edge（`BP-04`／`BP-05`）

## `BP-04` Central

**寫入集（完整）：**

| 檔案 | 改什麼 |
|---|---|
| `backend/app/api/http/files.py` | 一條新路由（POST），含「先 commit 再 raise」 |
| `backend/app/api/middleware.py`、`backend/app/main.py` | 外層純 ASGI middleware 在 server-facing send 完成最後一塊後觸發成功稽核，避免 `RequestIdMiddleware` 的 body buffer 提前記成功 |
| `backend/app/services/files.py` | `open_binary_preview`／串流 generator；回傳拒絕結果而不是直接 raise |
| `backend/app/services/authz.py` | `session_capabilities` 多一個 `can_preview_binary`（`:309-316`） |
| `backend/app/api/http/schemas.py` | `SessionCapabilities.can_preview_binary`（`:90-110`）；`_capabilities` 從 `get_node_registry()` 與 settings 取 live bit（`:164-169`） |
| `backend/app/api/ws/nodes.py` | `_register_input` 解析 `binary_preview`（`:91-114`）；`node.register` 分支設定 live bit（`:203-209`）；連線關閉時清除 |
| `backend/app/services/registry.py` | 保存「當下連線」的 `binary_preview`；現在只有 `is_connected`（`:185`） |
| `backend/app/services/nodes.py` | `RegisterNodeInput.binary_preview`；持久化與變更稽核（`:283-305` 模式） |
| `backend/app/db/models.py`、`backend/app/db/migrations/versions/0022_node_binary_preview.py` | **`downgrade()` 必須移除 `upgrade()` 加的全部東西**：`ix_nodes_binary_preview` 索引、`nodes.binary_preview`、`nodes.last_registration_at`（與 `0020_node_file_upload.py:56-58` 同一形狀）。顯示用欄位 `nodes.binary_preview`；以及**回退演練用**的 `nodes.last_registration_at`（timestamptz，nullable，無 backfill），**只**在 `persist_registration` 設定（`nodes.py:240` 起；heartbeat 路徑 `:324`、`:353` 不碰它）。不是 wire／契約變更 |
| `backend/app/api/http/schemas.py`（`NodeDetail`，`:356-372`）、`backend/app/api/http/nodes.py`（`:93` 附近） | 以唯讀欄位回傳 `last_registration_at` |
| `backend/app/settings.py`、`backend/app/services/audit.py`、`backend/app/api/error_catalog.py`、`docs/error-catalog.md`（產生） | flag、預算、稽核動作、錯誤碼 |
| 測試 | `backend/tests/db/test_files_binary_preview_api.py`（新）、`backend/tests/db/test_node_register_binary_preview.py`（新）、`backend/tests/test_authz.py`、`backend/tests/test_relay_timeouts.py`、`backend/tests/test_scope_guards.py` |

**前置：** `BP-02` 合併。可以用 fake daemon 先行，不必等 `BP-03`。

### 1. 端點：路徑在 body，不在 URL

```
POST /api/sessions/{session_id}/files/binary-preview
Content-Type: application/json
{"path": "<workspace-relative>"}
```

**為什麼不是 `GET ?path=`（ADR 0029 §6）：** URL 會被每一層記下來。兩份 nginx 的 log 格式都是
`"$request"`（`deploy/nginx/nginx.conf:52-55`、`deploy/railway/nginx.conf.template:64-67`）；uvicorn 0.35.0
的 access log 也帶 query string（`uvicorn/protocols/utils.py:52-56`），而 Central 啟動時沒有 `--no-access-log`
（`deploy/backend.Dockerfile:147`、`deploy/railway/central.railway.json:17`）；Railway edge 的行為不由我們設定。
把路徑移到 body，URL 就只剩 session id，而其他 session 路由本來就會記 session id。

| 選項 | 取捨 | 結論 |
|---|---|---|
| `GET ?path=`，每一層關 log 或改成不含 query 的格式 | 正確性取決於每一層的設定一直正確，其中 Railway edge 我們設定不了 | 不作為主要控制；edge 的無 query 格式保留作縱深防禦 |
| **`POST` + JSON body** | 讀取用 POST：不可快取（本來就要 `no-store`）、proxy 不會重送（正合所需）。RBAC 拒絕 middleware 會把 action 層的 403 當成「mutation」稽核（`middleware.py:153-157`），但三個角色都持有 `file.browse`，實務上不會發生；scope 層的拒絕在 GET 也本來就會稽核 | **採用** |
| `POST` 換 opaque handle，再 `GET /…/{handle}` | Central 端要有跨 process 的 handle 狀態（`BP-OM-09`）、重放與綁定規則、多一次往返；唯一的好處是可 GET 的 URL，而 ADR §11 正是不要 `<img src>` | 不採用 |

**CSRF：** 認證是由 script 加上的 Bearer header（`frontend/src/api/client.ts:654`），跨站表單或 `fetch`
帶不到憑證，會得到 401。另外路由**要求** `Content-Type: application/json`，其他一律 415，
所以 `text/plain` 這類不觸發 preflight 的「simple request」也到不了 handler。`backend/app` 沒有 `CORSMiddleware`。

處理順序固定：

| # | 步驟 | 失敗時 |
|---|---|---|
| 1 | `require_action(FILE_BROWSE)` | 403 `FORBIDDEN` |
| 2 | `_resolve()`：session 存在 → `authorize_file_browse`（含 shell 拒絕）→ node 已連線（`services/files.py:182-198`） | 404／403／409 `NODE_OFFLINE` |
| 3 | `settings.binary_preview_enabled` | 409 `FILE_PREVIEW_UNSUPPORTED_NODE` |
| 4 | `registry.binary_preview(node_id)`：**當下連線**的註冊回報 | 409 `FILE_PREVIEW_UNSUPPORTED_NODE`。**不送任何 frame** |
| 5 | 請求形狀：`Content-Type` 必須是 `application/json`；body ≤ 24 KiB（足以容納 4096 code point 的 UTF-8 路徑）；JSON 物件**恰好**只有 `path`；**URL 不得帶任何 query 參數** | 415／413／422／400。帶 query 就拒絕，是為了讓「有人把路徑放回 URL」在 CI 上變紅，而不是在 log 裡被發現 |
| 6 | `_reject_rel_path(path)` | 400 `FILE_INVALID_PATH` |
| 7 | 每使用者 2、每節點 4 條串流的上限（process 內 semaphore） | 429 `FILE_PREVIEW_BUSY` |
| 8 | `preview_open`（15 秒）。in-band 拒絕時，service **回傳**一個拒絕結果（不 raise）；敏感拒絕照舊經 `_maybe_audit_denied`（`services/files.py:482-523`，**不改**）加入 session | — |
| 9 | 有拒絕結果時：路由**先 `await session.commit()`**，**再** raise `ApiError(code, 固定訊息, status, details={reason, size?, limit?})`。與現有 `/content` 路由 commit `read_file` 加入的稽核是同一模式（`files.py:212-215`）。反過來做，稽核列會隨 session 關閉而消失：`AuditService.record` 只把列加進 session（`audit.py:204-210`），`get_session` 也不會自己 commit（`db/engine.py:96-98`） | 對應 HTTP 狀態（下表） |
| 10 | `StreamingResponse`：逐塊 `preview_chunk`（每塊 10 秒，整體 60 秒） | 串流中斷 → 連線被截斷，`Content-Length` 不符讓瀏覽器得到 network error |
| 11 | 最後一塊的**最外層、面向 server 的 ASGI `send`** 成功返回後：以**獨立的短 session**（`get_database().session()`）寫入成功稽核並 commit，與 RBAC 拒絕 middleware 同一模式（`middleware.py:126-127`、`:171`）。外層純 ASGI middleware 越過 `RequestIdMiddleware` 的 body buffer 觀察 send；寫入受有期限的 cancellation shield 保護，因為 generator 在最後一個 `yield` 後可能直接被取消。不用 request 的 session，因為它相對於串流 body 的生命週期取決於 FastAPI（0.120.1）的 dependency 結束時機，本設計不依賴它 | 寫入失敗或逾時只計數並記無路徑 log |
| 12 | generator 的 `finally`：**一律**送 `preview_close`，包括成功送完最後一塊、節點或逾時錯誤、client 取消三種情況（不等待結果，1 秒上限）。完成的串流因此會立即釋放 daemon 的 snapshot；daemon 的閒置 TTL 只是 close 遺失時的 backstop（ADR 0029 §5、§6） | — |

HTTP 狀態對照：`FILE_DENIED` 403、`FILE_NOT_FOUND` 404、`FILE_PERMISSION_DENIED` 403、
`FILE_TOO_LARGE` 413、`FILE_PREVIEW_UNSUPPORTED` 415、`FILE_PREVIEW_INVALID` 422、
`FILE_PREVIEW_LIMIT` 413、`FILE_PREVIEW_DISABLED` 403、`FILE_PREVIEW_EXPIRED` 502（中途過期，
對使用者而言是暫時性失敗）、`NODE_BUSY` 503。
每個 code 保留自己的碼，因為每個的下一步都不同（`_map_error` 的既有原則，`services/files.py:555-562`）。

**未驗證：** `RequestIdMiddleware` 是 `BaseHTTPMiddleware`（`middleware.py:41`），位於路由與 server 之間。
它會不會影響串流的背壓與斷線偵測，要由 `test_stream_backpressure` 與 `test_disconnect_sends_close`
在**完整 middleware stack** 下證明（`BP-OM-11`），不能只測裸路由。

### 2. 回應標頭

ADR 0029 §6 的七個標頭為一組，缺一不可：`Content-Type: application/octet-stream`、
`X-Content-Type-Options: nosniff`、`Content-Length`、`Cache-Control: no-store, private` 加
`Vary: Authorization`、`Cross-Origin-Resource-Policy: same-origin`、
`Content-Security-Policy: sandbox; default-src 'none'`，以及 `X-Cliora-Preview-{Mime,Kind,Width,Height}`。
**沒有 `Content-Disposition`。**

`X-Cliora-Preview-Mime` 的值只能來自 wire enum。Central 在送出前再比對一次，
不在 enum 內就當作節點回應異常（502），不把節點給的字串原樣轉出。

### 3. 能力協商

- `ws/nodes.py` 在 `node.register` 分支（`:203-209`）把該連線的 `binary_preview` 交給 `registry`，
  連線關閉時清掉。**這是權威來源。**
  欄位缺席即 false；`false` 在 schema 上無效（`const: true`，`02-…md` §2）。
- `nodes.binary_preview` 欄位（migration `0022`，`server_default=false`，有索引，
  與 `models.py:98-107` 同一模式）只供節點頁面顯示與「哪些節點開了預覽」這類查詢。
- `SessionCapabilities.can_preview_binary`
  = `settings.binary_preview_enabled ∧ registry.binary_preview(node) ∧ may_browse_files(user, session)`。
  在 `authz.session_capabilities` 計算（`authz.py:309-316`），經 `schemas._capabilities`（`schemas.py:164-169`）
  進入每一個 `SessionSummary`／`SessionDetail`（`schemas.py:150`、`:160`；呼叫端 `sessions.py:72`、`:90`、`:101`、`:118`、`:155`）。
  `_capabilities` 自己從 `get_node_registry()` 與 settings 取值，**呼叫端不改簽名**。
  前端的既有上傳入口是在 client 端合成 `can_upload_files ∧ nodePosture.image_upload`
  （`SessionWorkspaceView.vue:476-480`）；本功能刻意在**伺服器端**合成，
  因為權威來源是當下連線，而那只有 Central 知道。
- 節點狀態變更（開關切換）沿用 `nodes.py:283-305` 的「變更才寫、並留稽核」模式。

### 4. 稽核

- 敏感拒絕：沿用 `_maybe_audit_denied`，**先 commit 再回錯誤**（§1 第 9 步）。
- 成功（OD-6）：新動作 `file.binary_preview`，呼叫端給的 metadata 是 `{kind, mime, size_bytes}`；
  `AuditService.record` 會自動加上 `request_id`（沒有時加 `source`，`audit.py:196-201`），那是允許的關聯鍵。
  在**最後一塊送出之後**以獨立 session 寫入（§1 第 11 步）。中途取消的不記成功，只記 metric。
  **`bytes` 不能當 key**（`audit.py:159` 會濾掉）。
- 稽核寫入失敗不讓請求失敗，而是計數並記 log，與 `_audit_upload` 同一種取捨（`services/files.py:472-480`）。
- `frontend/src/utils/auditActions.ts` 的標籤在 `BP-06` 加（「預覽圖片／PDF」）。

### 5. 記憶體與 log

- 每條串流同時最多持有一塊（≤512 KiB 原始、≤683 KiB base64）。
- `_observe("binary_preview", …)` 記 `kind`、`code`、`reason`、`chunks`、`bytes`、`duration_ms`。
  **不記 path**；`bytes` 是 log 欄位，不是稽核 metadata，所以可以用。
- uvicorn access log 會記 URL，而 URL 只有 session id（§1）。

### 6. 設定

`settings.py` 新增：`binary_preview_enabled: bool = False`（OD-5）、
`file_preview_open_timeout_seconds = 15`、`file_preview_chunk_timeout_seconds = 10`、
`file_preview_total_seconds = 60`、`file_preview_streams_per_user = 2`、
`file_preview_streams_per_node = 4`、`file_preview_max_body_bytes = 24576`。每個預算都要在 PRD `FR-CONN-006.AC-13` 公布
（`test_every_relay_budget_is_published`）。

### 7. 先寫的 RED 測試

| 測試 | 斷言 |
|---|---|
| `test_roles_matrix` | Viewer／Developer／Admin 可預覽白名單檔；沒有 `file.browse` 的使用者 403；看不到該 session 的使用者 403，且與「不存在」同一訊息 |
| `test_shell_session_refused` | 經 shell session 的 id → 403 |
| `test_old_daemon_is_never_asked` | fake daemon 的註冊沒有 `binary_preview` → 409，且 fake daemon **沒有收到任何 frame** |
| `test_flag_off_is_never_asked` | flag 關 → 409，同樣零 frame |
| `test_reconnect_flips_gate_and_capability` | 以 `binary_preview:true` 註冊 → `GET /api/sessions/{id}` 的 `capabilities.can_preview_binary` 為 true，且預覽 200；斷線 → 以**省略欄位**的 register 重連 → capability **與**端點**同時**變成 false／409（不必等 DB）；再以 true 重連 → 兩者都恢復。每一步都斷言兩處一致 |
| `test_capability_on_every_session_response` | `sessions.py` 五個回傳點（`:72`、`:90`、`:101`、`:118`、`:155`）都帶 `can_preview_binary`，而且值相同 |
| `test_last_registration_at_is_registration_specific` | 同一版本重新註冊 → `last_registration_at` 前進；只有 heartbeat → 不變；schema 不符而被略過的 register → 不變 |
| `test_invalid_register_is_silently_skipped` | 釘住**現行**行為（也就是舊 Central 回退時的故障形態）：schema 不符的 `node.register` → 不持久化、不回 `node.registered`、連線仍在（`ws/nodes.py:199-202`）。這條測試讓 runbook 的「回退前先停用 daemon」有依據 |
| `test_path_never_in_url` | 帶任何 query 參數（包括 `?path=`）→ 400；前端 `fetchBinaryPreview` 產生的 URL 不含路徑（`BP-06` 另有前端測試） |
| `test_requires_json_body` | `text/plain` → 415；body 超過 24 KiB → 413；多一個 key → 422 |
| `test_headers_are_a_set` | 七個標頭都在，而且沒有 `Content-Disposition` |
| `test_mime_header_comes_from_enum` | fake daemon 回 `image/svg+xml`（繞過 schema）→ 502，不轉出 |
| `test_cookie_without_bearer_is_401` | 帶 cookie、不帶 `Authorization` → 401 |
| `test_stream_backpressure` | **完整 middleware stack** 下，慢速 client：Central 在前一塊被消費前不送下一個 `preview_chunk`（`BP-OM-11`） |
| `test_disconnect_sends_close` | 同上 stack，client 中途斷線 → fake daemon 收到 `preview_close`；`_observe` 記 `CANCELLED` |
| `test_close_sent_on_success_and_error` | 成功送完 → fake daemon 收到恰好一次 `preview_close`；第 2 塊逾時或節點回錯 → 同樣收到 close |
| `test_successive_previews_beyond_handle_limit` | fake daemon 嚴格實作 4 個 handle 上限，而且**沒有 TTL**：同一使用者依序完成 N+1＝5 次預覽，全部 200；每次串流結束後 fake daemon 的 handle 數為 0 |
| `test_truncated_stream_is_error` | 第 3 塊時節點斷線 → 回應長度小於 `Content-Length` |
| `test_budget_total` | 60 秒整體預算到期 → 中止並送 close |
| `test_busy_limits` | 同一使用者第 3 條串流 → 429 |
| `test_sensitive_denial_audit_persists_after_403` | `.env.png` → 回應 403 **之後**，以**另一個 DB session** 查詢，稽核列存在，metadata 為 `{classification, extension}` 加 `request_id`，不含路徑。先移掉路由裡的 `commit` 再跑一次，這條必須變紅（mutation check） |
| `test_success_audit_has_no_path` | 成功稽核的 metadata：**必須**有 `kind`、`mime`、`size_bytes`；**只能**再有 `request_id` 或 `source`（服務自動加入，`audit.py:196-201`）；**不得**有 `path`、`rel_path`、`filename`、`name`、`extension`、`content`、`data`、`bytes` 任何一個；而且沒有任何值包含 canary 路徑的片段 |
| `test_success_audit_on_own_session` | 串流完整送完 → 稽核列可見；中途取消 → 沒有成功列 |
| `test_log_has_no_path` | 以 canary 路徑 `bp-canary-<隨機>/機密-<隨機>.pdf` 請求，擷取 app 的所有 log 記錄，不含任何片段（原文與 percent-encoded） |
| `test_preview_does_not_imply_download` | （#71 合併後）`binary_preview:true, file_download:false` → 預覽 200、下載 403；反之亦然 |
| `test_read_content_unchanged` | 同一張 PNG 走 `/content` 仍是 in-band `FILE_BINARY` |
| `test_authz.py` 路由矩陣 | 新路由（POST）有列、Viewer 允許一列明文（#71 同一原則） |

### 8. 驗收清單

- [ ] §7 全綠；`make test-db` 綠。
- [ ] Migration `0022` 可升可降：`test_migration_0022_roundtrip`（新，`backend/tests/db/`）依序 upgrade head → downgrade 到上一版 → 斷言兩個欄位與索引**都不存在** → 再 upgrade head → 斷言都存在 → 以 alembic 的 `compare_metadata` 比對 models 與實際 schema，**差異必須為空**（沒有 drift）。`backend/tests` 目前沒有任何 migration 來回測試（已查），這是新的測試形狀，列入寫入集。降級只刪 report-only 欄位，沒有使用者資料損失。
- [ ] `docs/error-catalog.md` 由 `render_error_catalog.py --check` 確認未漂移。
- [ ] `backend/app/api/http/files.py:203-215` 的 `/content` 沒有 diff。
- [ ] `sessions.py` 的五個呼叫端沒有簽名改動。

### 9. 不在範圍

前端、edge 設定；把 Central 改成多 worker 共享 semaphore（現行是 process 內，
**假設**單一 process 服務一個節點的 WebSocket，未驗證，列為 `BP-OM-09`）；
既有 GET 檔案路由（`/content`、`/tree`、`/search`）把路徑與關鍵字放在 query string 的問題
（既有缺陷，另開議題，`09-…md` §4）。

---

## `BP-05` Edge（nginx）

**寫入集：** `deploy/nginx/nginx.conf`、`deploy/railway/nginx.conf.template`（http 層多一個 `log_format`，
加上一個專用 location，兩份各自的 upstream 寫法），`make railway-check` 對應的 parity 測試，以及
`.github/workflows/ci.yml`（新增 compose 設定的 `nginx -t` 步驟）。量測證據放在外部，並回填 `09-…md`。

**為什麼要有這一張：**

1. **暫存檔。** `location /api/` 是 `proxy_buffering on`、沒有 `proxy_max_temp_file_size`
   （`nginx.conf:163-175`、`railway/nginx.conf.template:159`）。依 nginx 文件的預設行為（**本部署未實測**），
   回應超過記憶體 buffer 時會寫到 `proxy_temp_path`；請求 body 超過 `client_body_buffer_size`
   時會寫到 `client_body_temp_path`，而**請求 body 正是帶著路徑的地方**。
2. **Access log。** 兩份設定的 `log_format cliora` 都記 `"$request"`（`nginx.conf:52-55`、
   `railway/nginx.conf.template:64-67`），也就是含 query string 的完整請求行。

**變更：** 在 http 層新增一個不含 query 的格式，再加一個 regex location，其餘設定照抄 `/api/`。
nginx 先記下最長的前綴匹配，再檢查 regex，regex 命中就優先；`location /api/` 不是 `^~`，所以這條 regex 會勝出。
位置放在 `/api/` 旁邊，是為了閱讀：

兩份設定的 upstream 解析方式本來就不同（`scripts/railway/check-edge-parity.sh:5-9` 明說這是刻意的），
所以 stanza 要各寫一份。兩份的 http 層都加同一個格式：

```nginx
# http 層（兩份設定都加）：永遠不用 $request 或 $args
log_format cliora_noquery '$remote_addr - $status "$request_method $uri" '
                          'rt=$request_time up=$upstream_response_time '
                          'nginx_req_id=$request_id';
```

**compose：`deploy/nginx/nginx.conf`**。沿用具名 upstream `cliora_backend`（`:72-73`）與 `/api/` 的 header 設定（`:163-175`）：

```nginx
location ~ ^/api/sessions/[0-9a-fA-F-]{36}/files/binary-preview$ {
    proxy_pass http://cliora_backend;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    access_log /var/log/nginx/access.log cliora_noquery;
    client_max_body_size 24k;        # 與 Central 的 body 上限一致
    client_body_buffer_size 32k;     # ≥ 上一行，所以帶路徑的 body 永遠留在記憶體，不寫 client_body_temp
    proxy_buffering off;             # 回應不緩衝，也就不會溢寫到 proxy_temp
    proxy_max_temp_file_size 0;      # 即使有人把上一行改回 on，也不寫暫存檔
    proxy_read_timeout 75s;          # 大於 Central 的 60 秒整體預算
}
```

**Railway：`deploy/railway/nginx.conf.template`**。沿用 `/api/` 的變數式 upstream（`:148-160`，`set` 在 `:149`）：
`set` 加上 `proxy_pass http://$var$request_uri` 的寫法，讓 nginx 透過 `resolver ${NGINX_LOCAL_RESOLVERS}`（`:101`）
在執行期重新解析 Central 的私網位址。沿用 TLS 在 Railway 前端終止時固定的 `X-Forwarded-Proto https`：

```nginx
location ~ ^/api/sessions/[0-9a-fA-F-]{36}/files/binary-preview$ {
    set $cliora_upstream "${CLIORA_BACKEND_HOST}:${CLIORA_BACKEND_PORT}";
    proxy_pass http://$cliora_upstream$request_uri;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
    access_log /var/log/nginx/access.log cliora_noquery;
    client_max_body_size 24k;
    client_body_buffer_size 32k;
    proxy_buffering off;
    proxy_max_temp_file_size 0;
    proxy_read_timeout 75s;
}
```

`${…}` 由映像的 envsubst 在容器啟動時代入（`deploy/railway/README.md:14`）。`$request_method`、`$uri`
這類 nginx 變數不是已定義的環境變數，不會被代入，與既有的 `log_format cliora` 相同。
`$request_uri` 會帶 query string，但 Central 對這條路由拒絕任何 query（`BP-04` §1 第 5 步），所以不會有 query 被轉送。

**兩份渲染後的設定都要真的被 nginx 接受：**

- **Railway：** 既有的 CI 步驟已經把 template envsubst 後跑 `nginx -t`（`.github/workflows/ci.yml:128-140`，
  `nginx:1.27-alpine`）。本票只要求它在新 location 加入後仍然綠。
- **compose：** 目前**沒有** CI 步驟驗證 `deploy/nginx/nginx.conf`。本票在同一個 job 新增一步：以同一個映像
  `docker run --rm --add-host backend:127.0.0.1 -v "$PWD/deploy/nginx/nginx.conf:/etc/nginx/nginx.conf:ro" … nginx:1.27-alpine nginx -t`。
  `--add-host` 是因為 nginx 在載入時就要解析具名 upstream 的 `backend`。TLS 憑證路徑若是 `-t` 的前提，以測試用的自簽檔掛入；
  **實際需要哪些掛載，在實作時依設定檔核對**。
- 兩步都要**先紅**：在新 location 裡故意放一個錯字，確認兩步都失敗，再修正。

路徑已經不在 URL 裡（`BP-04` §1），所以 `cliora_noquery` 是**縱深防禦**：日後若有人加了一個 query 參數，它也不會被寫下來。

**RED：** parity 測試先斷言兩份設定都有這個 location、`cliora_noquery` 不含 `$request`／`$args`，
以及五個指令（`access_log … cliora_noquery`、`client_max_body_size`、`client_body_buffer_size`
≥ `client_max_body_size`、`proxy_buffering off`、`proxy_max_temp_file_size 0`）。先紅，再改設定。

### 發布閘門（`BP-OM-06` 與 `BP-OM-10`）

在**每一種**要出貨的部署拓樸上（compose／nginx，以及 Railway）都做完，才可以在 PRD、release note 或 UI
宣稱「不落地」與「log 無路徑」（ADR 0029 §6）：

1. **Canary 路徑。** 在 staging 建立 `bp-canary-<隨機 12 碼>/機密-<隨機 12 碼>.pdf`，以 Viewer 預覽一次，
   再故意送一次會被拒絕的 `bp-canary-<同一碼>/.env.png`（敏感拒絕路徑）。
2. **搜尋。** 記號以原文與 percent-encoded（UTF-8）兩種形式搜尋，範圍：
   - compose 部署的 nginx `/var/log/nginx/access.log`，以及 Railway console 容器內的同一檔；
   - uvicorn／Central 的 stdout（兩種部署都要）；
   - Central 的 JSON correlation log；
   - `audit_logs` 表（`metadata` 欄）；
   - Railway 的 HTTP logs 與 deploy logs（由操作者在 Railway 介面匯出）。
   **每一處都必須是零筆。**
3. **暫存檔。** 預覽 16 MiB PDF 與 24 KiB 上限附近的 body 時，監看 `proxy_temp_path` 與 `client_body_temp_path`：
   沒有新檔（`inotifywait` 或前後 `find -newer` 比對）。
4. **Railway edge。** Railway 在我們的 nginx 前面還有自己的 edge。它會不會把 body 暫存到磁碟，我們量不到；
   它記不記路徑，第 2 步量得到。量不到或不合格的部分依 **OD-11** 的建議預設處理：**該拓樸的 flag 保持關閉**。
   要在未證實的 edge 上開啟，必須先由產品負責人明確修訂 `FR-FILE-012.AC-09`，這不是發布當下的決定。

證據（去識別化的指令與輸出）寫進 `09-…md` §3。**任何一處非零或未證實，該拓樸的 flag 不得開啟。**

**驗收：** `make railway-check` 綠；兩份渲染後設定的 `nginx -t` 在 CI 都綠；上面四步有證據。

**不在範圍：** 既有 `/content`、`/tree`、`/search` 的 query string 進 log 與 `proxy_temp` 溢寫。這裡只記錄，另開議題處理。
