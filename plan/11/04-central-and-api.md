# 04 — Central：整合設定、服務、API 與稽核（PG-09、PG-07、PG-08）

> 需求變更（2026-08-01）：新增 `PG-09`（整合設定服務、憑證加解密與 API），並讓 `PG-07` 的建立路徑
> 改為先合成三層設定、再解密憑證放入 `tunnel.open`。**`PG-09` 先於 `PG-07`**（`00-…md` §5）。

## PG-09：整合設定服務、憑證加解密與 API

新增 `backend/app/services/integrations.py`、`backend/app/repositories/integrations.py`、`backend/app/security/secret_box.py`、`backend/app/api/http/integrations.py`。

### 0.1 `secret_box.py`

AES-GCM，金鑰來自 `CLIORA_SECRET_ENCRYPTION_KEY`（32 bytes base64），用既有的 `cryptography`（**不新增依賴**）。介面刻意小：

```python
def encrypt(plaintext: str) -> tuple[bytes, bytes]:   # (ciphertext, nonce)
def decrypt(ciphertext: bytes, nonce: bytes) -> str
def fingerprint(plaintext: str) -> str                # sha256 前 8 hex
def is_available() -> bool                            # 金鑰是否已設定
```

| 規則 | 理由 |
|---|---|
| 金鑰未設定時 `encrypt`／`decrypt` **拋錯**（`SECRET_KEY_MISSING`），不回傳明文、不無聲通過 | 「先存明文，日後再加密」是這類功能最常見的走向，而它沒有回頭路：一旦有明文躺在 DB 裡，補加密也救不了已洩漏的那些 |
| 每次加密用新的隨機 nonce，與 ciphertext 一起存 | AES-GCM 的 nonce 重用會直接破壞機密性。這不是可以「之後再說」的細節 |
| `fingerprint` 是 **plaintext 的** sha256 前 8 hex | 讓人回答「現在裝的是不是我上週換的那一把」。前 8 hex 不足以還原 token，但足以比對 |
| 明文不進任何 dataclass 欄位、不跨 await 邊界長期持有 | 減少它出現在例外追蹤、repr、序列化與記憶體轉存中的機會 |

### 0.2 服務

| 操作 | 行為 |
|---|---|
| `get()` | 回傳單列（不存在則回一個 `enabled=False` 的預設物件，**不自動建立列** —— 讀取不該有副作用） |
| `enable(user, acknowledge=True)` | 需 `integration.manage`；金鑰不可用 → `SECRET_KEY_MISSING`；憑證未設定且 `plan_tier=pro` → 拒絕（Pro 模式沒有憑證等於一定失敗）；未帶 `acknowledge` 且 `acknowledged_at` 為空 → 422（D14 第一處）；成功後寫稽核 `integration.enable` |
| `disable(user)` | 需 `integration.manage`；**不關閉既有隧道**（見下）；寫稽核 |
| `set_credential(user, token, plan_tier)` | 需 `integration.manage`；驗字元集 `^[A-Za-z0-9]{8,128}$`；加密後寫入三欄；寫稽核 `integration.credential_set`（**metadata 只有指紋**） |
| `clear_credential(user)` | 清三欄；若 `plan_tier=pro` 則同時把 `plan_tier` 降為 `free`（否則會留下一個必然失敗的組合） |
| `update_defaults(user, …)` | 併發預算、預設保護模式、預設 TTL、全域 `allowed_ports` |
| `credential_for_open()` | **唯一的解密呼叫點**，供 `PG-07` 的建立路徑使用。回傳明文字串，呼叫端用完即丟 |

`disable` 為什麼不關閉既有隧道：關閉需要對每個 node 發 `tunnel.close`，而其中有些可能離線 —— 一個「停用整合」的動作若可能部分失敗，就會產生「已停用但還有隧道在跑」的狀態而沒人知道。**決定：`disable` 只擋新建，既有隧道由其 TTL 自然結束，UI 明確顯示「整合已停用，N 條既有隧道仍在執行（將於到期後結束）」並提供「一併關閉」的獨立按鈕。** 把「擋住新的」與「收掉舊的」分成兩個動作，兩者都能誠實回報結果。

### 0.3 API（`/api/integrations/tunnel`）

| 方法 | 路徑 | action | 回應 |
|---|---|---|---|
| `GET` | `/api/integrations/tunnel` | `integration.manage` | 設定物件：`{enabled, provider, plan_tier, credential: {configured, fingerprint, updated_at, updated_by}, concurrent_budget, default_protection, default_ttl_seconds, allowed_ports, acknowledged_at, secret_key_available, active_tunnel_count}` |
| `PUT` | `/api/integrations/tunnel` | `integration.manage` | 更新 `enabled`／`plan_tier`／預設值／`allowed_ports`／`acknowledge` |
| `PUT` | `/api/integrations/tunnel/credential` | `integration.manage` | 設定或更換憑證（body 只有 `token`、`plan_tier?`） |
| `DELETE` | `/api/integrations/tunnel/credential` | `integration.manage` | 清除憑證 |

| 決定 | 理由 |
|---|---|
| **回應永不含 token 的任何字元**，只有 `configured` 與 `fingerprint` | D19。這一條要有測試（回應 JSON 的鍵集合 + 值比對） |
| `secret_key_available` 由伺服器回報 | UI 才能在金鑰未設定時顯示「此環境無法保存憑證，請聯繫部署管理員」，而不是讓 Admin 按下儲存後拿到 500 |
| `active_tunnel_count` 一併回報 | `disable` 的後果（§0.2）要在按下之前就看得到 |
| **沒有「測試連線」端點** | 一個 `POST /test` 需要挑一台 node、起一條真的隧道再關掉 —— 它會產生一個使用者沒有要求的對外暴露，而且失敗原因與正式建立時完全相同。**改為：在 `PG-11` 的頁面上，第一次建立就是測試。** 若日後真的要，它必須是「在指定 node 上建立一條 60 秒、`ipallow` 限本人 IP 的隧道」，而不是一個看不見的探測 |
| 不接受 `provider` 的其他值 | D2 |

`frontend/src/api/client.ts` 新增四個方法；`api/dto.ts` 新增型別與 `ACTION_INTEGRATION_MANAGE`。

### 0.4 稽核

| action | metadata |
|---|---|
| `integration.enable` | `provider`、`plan_tier`、`acknowledged: true` |
| `integration.disable` | `provider`、`active_tunnel_count`（停用時仍在跑的條數 —— 事後要能回答「那時還有幾條」） |
| `integration.credential_set` | `provider`、`plan_tier`、**`fingerprint`**、`replaced: true/false` |
| `integration.node_settings_updated` | `node_id`、`enabled`、`allowed_ports`、`max_tunnels`（`PG-11` 的頁面寫入時） |

**`credential_set` 記指紋而不是「有沒有換」**：指紋讓事後能對上「這條隧道是用哪一把憑證開的」，而完整 token 永遠不進稽核。

### 0.5 驗收

- 單元測試：`secret_box` 的加解密往返、錯誤金鑰無法解密、金鑰未設定時 `encrypt` 拋錯。
- DB 測試：singleton 約束（插第二列失敗）、`enable` 在金鑰不可用時被拒、`enable` 在 Pro 但無憑證時被拒、未確認時 422、`set_credential` 後 DB 內為 ciphertext 且 `GET` 回應不含明文、`clear_credential` 會把 `plan_tier` 降為 free。
- 授權測試：Developer 對四個端點皆 403（**action 層**）；Admin 成功。
- 稽核測試：四個 action 各有寫入點；`credential_set` 的 metadata 只有指紋。

---

## PG-07：tunnel service、三層設定合成與 URL 變更傳播

新增 `backend/app/services/tunnels.py` 與 `backend/app/repositories/tunnels.py`。**沒有 registry、沒有 stream manager、沒有代理** —— 這一層薄到只有「寫 DB、下控制訊息、收事件」三件事，這正是整合方案的形狀。

### 1.1 建立

`TunnelService.create(user, node_id, port, protection, allowed_ips, label, ttl)`：

1. 整合未啟用（`tunnel_integration.enabled` 為假）→ 404／`TUNNEL_INTEGRATION_DISABLED`（功能關閉是明確狀態）。
2. action 層 `tunnel.manage` → 資源層 `may_create_tunnel`。
3. **三層設定合成**（D17，本期新增的核心邏輯）：
   - `enabled` = 整合 ∧ per-node（`node_tunnel_settings.enabled`）∧ ¬node 本機否決（`nodes.tunnel_veto`）。任一為假 → `TUNNEL_NODE_DISABLED`（409），**且錯誤訊息要指出是哪一層**，否則使用者不知道該去改哪裡。
   - `allowed_ports` = 三層交集（`NULL` 視為不收窄）。
   - **每台 node 的上限** = `min(tunnels_per_node_max, per-node 設定, node 本機回報)`。**`concurrent_budget` 不在這個 `min()` 裡**（`00-…md` D17b）。
   - 合成結果要能被單獨測試（純函式 `effective_policy(integration, node_settings, node_report, settings)`），因為它有四個輸入、三個輸出，而錯誤會直接變成安全問題。
4. **node 先決條件檢查**（`02-…md` §2.4 回報的欄位）：`ssh_available`／`egress_ok`／`known_hosts_ok` 任一為假或未回報 → `TUNNEL_PROVIDER_NOT_CONFIGURED`（409），訊息指向 `agentd doctor`。這是使用者最常遇到的第一個錯誤，必須在按下按鈕後**立刻**回答，不能等 20 秒的逾時。
5. port 檢查：`<1024` 或不在合成後的 `allowed_ports` → `TUNNEL_PORT_NOT_ALLOWED`。
6. 額度，**三條獨立的檢查**，錯誤訊息必須說出撞到哪一條：
   - **車隊併發預算**：`COUNT(*) FROM node_tunnels WHERE closed_at IS NULL AND expires_at > now()` ≥ `concurrent_budget`（預設 8）→ `TUNNEL_LIMIT_REACHED`，訊息寫「已達整體併發上限 8／8，請關閉其他隧道或由管理員調整預算」。**這條是 provider 方案的硬事實**：超出它的後果不是排隊而是踢掉別人的隧道（`+force` 語意，`PG-01` #8）。
   - **每台 node 上限**：該 node 的存活條數 ≥ 合成後的上限 → 同一個碼，訊息指向這台 node。
   - **每位使用者上限**：`tunnels_per_user_max`。
   三條合用同一個錯誤碼但**不同的訊息**：使用者能做的事完全不同（關別人的、關這台的、關自己的）。
7. 保護模式（預設值來自整合設定的 `default_protection`）：
   - `basic` → 產生 `tunnel_basic_password_length`（24）字元密碼（`secrets.token_urlsafe`，**移除 `:`** 以符合 provider 限制）＋ 使用者名（`preview`），存 Argon2 hash。
   - `ipallow` → 驗證 `allowed_ips`（IP／CIDR、上限 32 筆）。
   - `public` → 要求 request 帶 `acknowledge_public: true`，否則 422；並寫 `tunnel.public_acknowledged` 稽核。
8. **首次確認檢查**（D14 第二處，Admin 的第一處在整合設定頁）：該 (user, node) 若無 `tunnel.create` 稽核紀錄，request 必須帶 `acknowledge_third_party: true`，否則回 422 附 `requires_acknowledgement: true`，讓 UI 顯示說明。
9. 寫 DB（`uq_node_tunnels_live_port` 擋同 port 重複 → 409 並回既有那一條）。
10. **解密憑證**（`IntegrationService.credential_for_open()`，§0.2）並放入 `tunnel.open` 的 `credential` 欄位；`plan_tier=free` 時省略。明文只存在於組裝這個 frame 的區間內，不進任何 dataclass、不進 log、不進例外訊息。
11. 送 `tunnel.open`（`registry.request`，timeout `tunnel_open_timeout_seconds`）。
12. 成功 → 寫回 `url`／`url_updated_at`／`upstream_expires_at`；失敗 → **rollback DB row**（不留下一條不存在的隧道），並把 daemon 的錯誤碼原樣回傳。
13. 稽核 `tunnel.create`（metadata 含 `credential_fingerprint`，**不含 url、不含 label、不含憑證明文**）；回傳 `TunnelDetail`，**`basic_auth_password` 只在這一個回應中出現**。

### 1.2 URL 變更傳播

`tunnel.status` 是主動事件，處理位置在 `app/api/ws/nodes.py` 的控制迴圈，**必須加進 `_TERMINAL_EVENTS` 之外的一個新分支，且在 `registry.resolve_response`（`:238`）之前**，否則它會被記成 `node_ws_unmatched_message` 並被丟棄。

| `state` | Central 的動作 |
|---|---|
| `running` + 新 `url` | 更新 `url`、`url_updated_at`、`upstream_expires_at`、清空 `state_error_code` |
| `reconnecting` | 只記 `state_error_code = None`；**不清空 `url`**（舊 URL 在重連期間仍是最後已知值，清空會讓 UI 閃成空白） |
| `failed` + `error_code` | 寫 `state_error_code`；**不自動關閉**（保留 row 讓使用者看到原因並自行決定重試或關閉） |
| `closed` | 寫 `closed_at`（daemon 側自行結束，例如重連上限） |

UI 怎麼知道 URL 變了：**輪詢**（沿用 `useAsyncResource` 與 Node 詳情頁既有的重新載入機制），不新增 WebSocket 推送。免費版一小時變一次，Pro 幾乎不變 —— 為這個頻率新增一條推送通道是不成比例的。輪詢間隔 15 秒，只在 node 的埠轉發頁（`PG-11`）可見時進行。

### 1.3 關閉與到期

- `close(user, tunnel_id)`：`may_close_tunnel` → 寫 `closed_at`／`closed_by` → 送 `tunnel.close` → 稽核。**先寫 DB 再通知**（與 plan/10 相反的順序在這裡不重要，因為 URL 的有效性由 provider 決定，平台無法讓它立即失效 —— 這一點要在 UI 說清楚：「關閉後服務商可能仍需數秒才停止回應」）。
- TTL：daemon 自己會在 `expires_at` 停止（`03-…md` §2.2），Central 以惰性檢查在讀取時把過期的標為 `expired`。**不新增背景排程器**（沿用 `retention.py` 的既有立場）。
- node 停用／移除／credential 撤銷 → 既有的 `registry.evict` 路徑；tunnel row 標為 `unavailable`（推導狀態），並送 `tunnel.close`（若 socket 仍在）。

### 1.4 驗收

- 單元測試（無 DB）：狀態推導的六種組合、`tunnel.status` 四種 state 的處置、**`effective_policy` 的三層合成**（含「平台放寬時 node 否決仍生效」與「三層 port 清單取交集」兩個必測案例）。
- DB 測試：建立成功、整合未啟用 404、per-node 停用 409、**node 本機否決 409 且訊息指出是本機層**、先決條件不足 409、port 不允許、額度、同 port 重複、daemon 失敗時 **rollback（斷言無殘留 row）**、`basic_auth_password` 不出現在後續任何讀取回應中、首次確認缺失時 422、**`tunnel.open` 的 payload 帶了解密後的憑證且該明文不出現在任何 log 或例外訊息中**。
- `pytest backend/tests -q`、`make test-db` 全綠。

---

## PG-08：REST API、稽核與資料外流確認

### 2.1 端點（`backend/app/api/http/tunnels.py`）

| 方法 | 路徑 | action | 回應 |
|---|---|---|---|
| `GET` | `/api/tunnels?node_id=&mine=` | `tunnel.view` | `TunnelSummary[]` |
| `POST` | `/api/tunnels` | `tunnel.manage` | `TunnelDetail`（201，**含一次性密碼**） |
| `DELETE` | `/api/tunnels/{id}` | `tunnel.manage` + `may_close_tunnel` | 204 |
| `POST` | `/api/tunnels/{id}/extend` | `tunnel.manage` + `may_close_tunnel` | `TunnelDetail` |
| `POST` | `/api/tunnels/{id}/rotate-password` | `tunnel.manage` + `may_close_tunnel` | `TunnelDetail`（**新的一次性密碼**；實作＝關閉並以新密碼重開，因此 **URL 可能改變**，回應要明說） |

`TunnelSummary` 欄位：`id`、`node_id`、`node_name`、`port`、`label`、`url`、`url_updated_at`、`state`、`protection`、`basic_auth_user`、`provider`、`upstream_expires_at`、`expires_at`、`created_by_username`、`created_at`、`capabilities{can_close, can_rotate}`、`state_error_code`。

| 決定 | 理由 |
|---|---|
| `basic_auth_password` **只在** `POST /api/tunnels` 與 `rotate-password` 的回應中 | D5。`TunnelSummary` 永遠不含它，這一條要有測試（讀取回應的 JSON 鍵集合斷言） |
| `rotate-password` 實作為「關閉並重開」 | provider 的 remote options 在連線建立時就固定了，改密碼沒有 in-place 的做法。誠實地把它做成重開，並在回應與 UI 明說 URL 可能改變 —— 假裝是原地修改會讓使用者以為舊 URL 仍有效 |
| `state` 由伺服器推導 | 沒有 DB 欄位（`02-…md` §2.1）。`unavailable` = row 活著但 node 不在線 |
| `capabilities` 由伺服器算 | 沿用 `SessionSummary.capabilities`／`can_open_shell`（`SessionWorkspaceView.vue:51`）的既有做法 |
| 整合未啟用時全部 404 | 與 `tunnel_integration.enabled` 一致（`02-…md` §2.2）。**開關在資料庫，不在環境變數** —— Admin 在 UI 上關掉之後，API 必須立刻一致 |
| `POST /api/tunnels` 的 body | `{node_id, port, protection, allowed_ips?, label?, ttl_seconds?, acknowledge_third_party?, acknowledge_public?}`。**沒有** `url`、`host`、`provider_options`、`ssh_options` 欄位 —— Central 不得成為 node 上執行內容的來源（`SEC-002`） |

`frontend/src/api/client.ts` 新增五個方法（沿用 `openShell` 的形狀）；`api/dto.ts` 新增型別與兩個 `ACTION_*` 常數。

### 2.2 稽核（三個 action）

`app/services/audit.py` 新增並加入 `ALL_ACTIONS`（`:78`）：

| action | metadata | 明確不含 |
|---|---|---|
| `tunnel.create` | `node_id`、`port`、`protection`、`provider`、`expires_at` | **`url`**、`label`、密碼、token |
| `tunnel.close` | `node_id`、`port`、`reason`（`user`／`expired`／`node_removed`／`provider_failed`）、`url_changed_count` | 同上 |
| `tunnel.public_acknowledged` | `node_id`、`port` | 同上 |

**`url` 不進稽核**，理由有兩層：它是第三方指派的識別碼，且它本身就是存取憑證的一部分（`public` 模式下 URL 就是全部）。把它寫進一張可被 `audit.view` 讀取的表，等於讓每個 Admin 事後都能存取那個預覽。

首次確認（D14）以**查詢既有 `tunnel.create` 稽核紀錄**判定，不新增欄位：「這個使用者是否曾為這個 node 建立過隧道」正是稽核表能回答的問題，多開一張 `acknowledgements` 表只會多一個要同步的真相。

`frontend/src/utils/auditActions.ts` 新增三個中文標籤。

### 2.3 驗收

- 端點測試：五個端點 × 三角色的授權矩陣；功能關閉時全部 404；`extend` 超上限被拒；`rotate-password` 回新密碼且 URL 欄位被更新。
- **密碼外洩測試**：`GET /api/tunnels` 與 `GET /api/tunnels/{id}` 的回應 JSON 不含任何密碼欄位；DB 中 `basic_auth_hash` 不等於明文。
- 稽核測試：三個 action 各有寫入點；metadata 不含 `url`／密碼／token（redaction 測試）；首次確認缺失回 422 且第二次建立不再要求。
- `make test-db` 全綠。
