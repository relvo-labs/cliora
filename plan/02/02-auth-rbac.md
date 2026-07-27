# 02 — P1-W2 Authentication 與 RBAC 骨架

對應 `research/01/02-phase-1-node-control-plane.md` §P1-W2 與 `docs/adr/0006-p1-auth-handoff.md`。涵蓋 ticket **P1-05**（auth）、**P1-06**（RBAC + audit）、**P1-07**（WS handshake）。需求：FR-AUTH-001/002、SEC-005、SEC-006、tech §14。

## 目標

以認證的瀏覽器 session、可插拔 resource 授權，以及安全的 browser/daemon WS handshake，取代 P0 的 shared dev token + subprotocol。P0 的 `authorized()`（`p0_enabled` + bearer/subprotocol）僅保留於 `CLIORA_P0_ENABLED` flag 後供 terminal 切片；正式路徑不得依賴它。

## P1-05：Authentication

實作 endpoints（PRD §11.1）：

```text
POST /api/auth/login    {username, password} → {access_token, refresh_token, user}
POST /api/auth/refresh  {refresh_token} → {access_token, refresh_token?}
POST /api/auth/logout   撤銷目前 refresh/session
GET  /api/auth/me       回目前 user + role + permissions
```

實作規則：

- **密碼**：Argon2id（`argon2-cffi`），參數（memory/time/parallelism）於 settings 固定並記 ADR 0007；login 對不存在帳號亦執行 dummy verify 以避免 timing oracle。
- **Token**：JWT access（15 min）帶 `sub`(user_id)、`role`、`jti`、`exp`、`iat`；refresh（14 天）為可撤銷憑證。撤銷採「refresh 存 DB／或 user token-version 欄位」擇一（ADR 0007 定），logout 使該 refresh 立即失效。access token 過期回 401 `TOKEN_EXPIRED`。
- **時間**：`exp`/`iat` 以 aware UTC 產生；驗證比較在 UTC；expiry 相等邊界（剛好到期視為過期）有測試。
- **停用使用者**：`is_active=false` 的 user 不可 login，且既有 access token 在下次進 boundary 時被拒（檢查 user 狀態或 token-version）。

驗收（延續 research §P1-W2）：success、invalid password、unknown user、disabled user、expired access、expired/撤銷 refresh、expiry 相等邊界皆有測試；login/logout 寫 audit（`user.login`/`user.logout`）且不含密碼或 token 明文。

## P1-06：RBAC 骨架與 authorization

- 建立 stable role keys `Admin/Developer/Viewer`（由 P1-04 seed 提供），權限矩陣依 PRD §8.1。
- **可插拔 resource authorization**：以 dependency/decorator 在 boundary 檢查「動作 + 資源」，而非只檢查角色字串；P1 需涵蓋的動作：查看 Node（全角色）、建立 enrollment token（Admin）、停用/移除 Node（Admin）、查看 audit（Admin）。Session/Terminal/檔案動作在 P2/P3 接上同一機制。
- authorization 失敗回 403 `FORBIDDEN`（safe message，不洩漏資源是否存在的細節區分需一致）；未認證回 401。
- **Audit 服務**（P1-06 建立、跨 ticket 使用）：`services/audit` 提供 `record(action, user_id?, node_id?, session_id?, metadata)`，寫 `audit_logs`；metadata 只存非敏感欄位，經 redaction（不存 token、secret、terminal content、檔案內容）。P1 必記事件：`user.login`、`user.logout`、`enrollment.create`、`enrollment.revoke`、`node.register`、`node.disable`、`node.remove`（軟刪除，見 `05`）、`credential.revoke`（對照 SEC-006）。

驗收：三角色對 P1 動作的 allow/deny 矩陣有測試（成功、forbidden、未認證）；audit 記錄完整且 redaction 測試證明無敏感內容；RBAC 檢查在 service 層可單元測試，不需真實 HTTP。

## P1-07：WS handshake（browser 與 daemon）

瀏覽器 JS WebSocket 無法設自訂 header，且長效 JWT 不可進 query string 或 log（tech §14.1）。因此兩條 WS 路徑各有 handshake：

### Browser：一次性 ws-ticket

```text
POST /api/ws-ticket  {resource}     （需有效 access token）
     → {ticket}        60s 有效、single-use、綁 user + resource
WS   /ws/...?ticket=<ticket>         boundary 驗 ticket → 建立認證連線後即作廢
```

- ticket 存於短效 store（記憶體或 DB，ADR 0007 定）；驗證後立即標記已用；過期或重用一律拒絕並 close（`1008`）。
- P1 尚無 browser terminal WS 需求，但 ws-ticket 機制在 P1 建立並以測試覆蓋，供 P2 直接使用；P0 的 `cliora-p0-dev` subprotocol 僅留在 flag 後。

### Daemon：challenge-response HMAC（`/ws/nodes/{node_id}`）

沿用 tech §14.2 與 ADR 0006：

```text
1. daemon dial WSS /ws/nodes/{node_id}（帶 node_id，不帶 secret）
2. central 產生一次性 nonce challenge（30s、single-use）→ 送 daemon
3. daemon 以 private_key 對 challenge 做 HMAC → 回簽章
4. central 以 node_credentials.secret_hash 驗算；成功才建立認證連線並註冊 registry
5. 失敗回 NODE_AUTH_FAILED 並 close；node 不存在/已撤銷/被 disable 亦拒絕（NODE_DISABLED）
```

- **絕不**在 query string 或 log 出現 private_key 或 challenge 簽章；nonce 用畢即棄。
- 認證成功後 daemon 送 `node.register`（P1-02）上報 metadata；central 落 DB 並回 `node.registered`。
- 已被 admin `is_enabled=false` 的 node：允許認證與連線（FR-NODE-005：daemon 可保持連線），但拒絕任何建立性操作並標示 Disabled。credential 已 `revoked_at` 的 node：認證即拒。

驗收（延續 research §P1-W2/W5）：browser ticket 的 success、過期、重用、錯 resource；daemon 的 success、錯 secret、過期 nonce、重放 nonce、撤銷 credential、被 disable node、未知 node_id，皆有 WS-level 測試並確認 close code 正確且 log 無 secret。
