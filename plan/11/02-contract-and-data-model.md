# 02 — 契約與資料模型（PG-03、PG-04）

> 需求變更（2026-08-01）：憑證改由平台保管，因此本檔新增 `tunnel.open` 的 `credential` 欄位（§1.2）、
> 整合設定與 per-node 設定兩張表（§2.2）、第三個 action `integration.manage`（§2.3），
> 並把「啟用與否」從環境變數移進資料庫（§2.5）。

## PG-03：契約 v1.6.0（compatible）

只新增控制面訊息。**沒有 binary frame、沒有第二條 socket、`LARGE_FRAME_TYPES`（`protocol/codec.py:23`）不動、`encode_binary` 的 kind 白名單（`:100`）不動。** 這是整合方案與 plan/10 最大的差別。

### 1.1 五個訊息型別

| 型別 | 方向 | payload |
|---|---|---|
| `tunnel.open` | Central → daemon | `{tunnel_id, port, protection, credential?, basic_auth?, allowed_ips?, ttl_seconds}` |
| `tunnel.opened` | daemon → Central | `{tunnel_id, url, provider, upstream_expires_at?}` |
| `tunnel.close` | Central → daemon | `{tunnel_id}` |
| `tunnel.closed` | daemon → Central | `{tunnel_id, reason}` |
| `tunnel.status` | daemon → Central（**非相關聯**，主動事件） | `{tunnel_id, state, url?, upstream_expires_at?, error_code?}` |

`tunnel.status` 是這一期唯一的主動事件，處理方式沿用 `_TERMINAL_EVENTS`（`app/api/ws/nodes.py:41`）的形狀：它有自己的 ULID，不對應任何 pending request，所以在 node WS 的控制迴圈裡要在 `registry.resolve_response` **之前**分派，否則會被記成 `node_ws_unmatched_message`。

`state` 是封閉集合：`running` / `reconnecting` / `failed` / `closed`。URL 只在 `running` 且 URL 有變時附上。

### 1.2 Schema 要點（每一條對應一個 invalid fixture）

| 欄位 | 規則 | 為什麼 |
|---|---|---|
| `port` | integer 1024–65535 | 下界寫在 wire 上。`<1024` 在 API、DB CHECK、daemon 三層都擋，這是第四層 |
| `protection` | enum `basic` / `ipallow` / `public` | 封閉集合。沒有「無」這個值 —— `public` 必須被明確命名，才能被稽核與 UI 警告 |
| `credential` | 選填 string，pattern **`^[A-Za-z0-9]{8,128}$`** | provider token（D18 由 Central 下發）。**字元集是安全控制而非格式潔癖**：它會被組進 `ssh` 的 `<token>@<host>` 欄位，而 Pinggy 用 `+` 串接修飾詞、`@` 分隔主機。一個含 `+tcp` 的值會改變隧道型別，一個含 `@evil.host` 的值會改變連線目的地。免費模式省略此欄位 |
| `basic_auth` | `{username, password}`，兩者 pattern **禁止 `:`**、長度 1–64、僅可見 ASCII | Pinggy 的 `b:user:pass` 以 `:` 分隔，官方文件明載帳密不得含 `:`。**這是一個注入面**：一個含 `:` 的密碼會變成第三組憑證或一個非預期的 remote option。schema 擋第一層，daemon 擋第二層 |
| `allowed_ips` | array of IPv4／IPv6（或 CIDR），最多 32 筆 | 對應 `w:` 選項；同樣不得含 `,` 以外的分隔字元 |
| `url` | pattern `^https://[a-z0-9.-]+(:[0-9]{1,5})?(/.*)?$`，maxLength 2048 | **只接受 https**。daemon 解析 provider stdout 得到的字串是外部輸入，必須在 wire 上就限制形狀，否則 UI 會拿到一個可控的 `javascript:` 或 http URL |
| `provider` | enum，目前只有 `pinggy` | D2：只有一個實作 |
| 全部 payload | `additionalProperties: false` | 禁止長出 `command`／`args`／`ssh_options` 這類欄位 —— 那會讓 Central 能決定 node 上執行什麼（`SEC-002`） |

**`tunnel.open` 是本協定第一個攜帶秘密的訊息型別**，因此有兩條額外規則：

1. **禁止記錄。** 兩端的 codec 與任何 frame 除錯路徑都必須把 `tunnel.open` 的 payload 視為不可記錄（既有實作本來就不記 payload；本期要加上明確的測試與註解，避免日後有人為了 debug 加一行 `log.debug(frame)`）。
2. **golden fixture 不得含真實形狀的 token。** valid fixture 用 `AAAAAAAA…` 這種明顯是假的值，並在 `contracts/CHANGELOG.md` 註明原因 —— 一個看起來像真 token 的測資，遲早會有人拿去試。

### 1.3 錯誤碼（新增六個）

`TUNNEL_PROVIDER_NOT_CONFIGURED`（node 未啟用或未設定 token）、`TUNNEL_PROVIDER_UNAVAILABLE`（連不上 provider）、`TUNNEL_PROVIDER_UNAUTHORIZED`（token 無效／過期）、`TUNNEL_PROVIDER_UNTRUSTED`（**host key 不符**）、`TUNNEL_PORT_NOT_ALLOWED`、`TUNNEL_LIMIT_REACHED`。

複用：`NODE_OFFLINE`、`NODE_DISABLED`、`REQUEST_TIMEOUT`、`INVALID_MESSAGE`、`INTERNAL_ERROR`。

**另外三個碼只存在於 Central，不進協定 enum**：`TUNNEL_INTEGRATION_DISABLED`、`TUNNEL_NODE_DISABLED`、`SECRET_KEY_MISSING`（§2.5 的錯誤文案）。它們描述的是平台端的設定狀態，daemon 永遠不會產生它們。`error_catalog.py` 的既有斷言（每個條目必須「由 Central 拋出」或「存在於協定的封閉 enum」）因此仍然成立 —— 這三個走前者，六個 wire 碼走後者。

`TUNNEL_PROVIDER_UNTRUSTED` 值得單獨一個碼而不是併進 `_UNAVAILABLE`：它的意思是「有人在 egress 路徑上」，處置方式與「服務商掛了」完全不同（一個是等，一個是立刻查）。`PG-01` 第 10 項就是為了讓這三個碼能被實際分辨。

### 1.4 產物與驗收

| 檔案 | 變更 |
|---|---|
| `contracts/v1/schemas/control-envelope.schema.json` | `type` enum 加 5 個；`error.code` enum 加 6 個；`allOf` 加 payload `$ref` |
| `contracts/v1/schemas/messages/tunnel-open.schema.json` 等五個 | 新 payload schema |
| `contracts/v1/fixtures/valid/` | `tunnel-open-basic.json`、`tunnel-opened.json`、`tunnel-status-url-changed.json` |
| `contracts/v1/fixtures/invalid/` | **四筆黃金測資**：`tunnel-open-colon-in-password.json`（密碼含 `:` → 拒）、`tunnel-open-privileged-port.json`（`port: 22` → 拒）、`tunnel-opened-http-url.json`（`url` 是 `http://` → 拒）、**`tunnel-open-credential-with-plus.json`**（`credential` 為 `abc+tcp@evil.host` → 拒，把 SSH 目的地注入釘在 wire 上） |
| `contracts/v1/fixtures/manifest.json` | 新測資逐筆登錄。**實作發現**：這個 manifest 沒有雜湊欄位，格式是 `{path, accept, type, code?}`；原計畫寫「雜湊」是錯的 |
| `contracts/CHANGELOG.md` | `## 1.6.0 — <日期> (compatible)`：五個型別、六個錯誤碼、**明確寫下「本版不新增 binary frame kind、不新增 WebSocket 端點；埠轉發的資料流不經過 Central」**，以及 `url` 只接受 https 的理由 |

驗收：`make contract` 三語一致；三筆 invalid fixture 在 Python 與 Go 兩端皆被拒且碼相同；`make traceability-validate` 通過。

---

## PG-04：資料模型、RBAC、settings 與 error catalog

### 2.1 Migration `0014_node_tunnels.py`

沿用 plan/10 的形狀（該部分結論與 provider 無關），加上整合方案特有的欄位。現有最新為 `0013_shell_session_parent.py`。

```
node_tunnels
  id                  UUID  PK
  node_id             UUID  NOT NULL REFERENCES nodes(id) ON DELETE CASCADE
  port                INTEGER NOT NULL           CHECK (port BETWEEN 1024 AND 65535)
  provider            TEXT  NOT NULL DEFAULT 'pinggy'
  protection          TEXT  NOT NULL             CHECK (protection IN ('basic','ipallow','public'))
  basic_auth_user     TEXT  NULL
  basic_auth_hash     TEXT  NULL                 -- Argon2id；明文只在建立回應出現一次
  allowed_ips         JSONB NULL
  url                 TEXT  NULL                 -- provider 指派，可變更
  url_updated_at      TIMESTAMPTZ NULL
  state_error_code    TEXT  NULL                 -- 最近一次 tunnel.status 的錯誤碼
  label               TEXT  NULL
  created_by          UUID  NOT NULL REFERENCES users(id)
  created_at          TIMESTAMPTZ NOT NULL
  expires_at          TIMESTAMPTZ NOT NULL       -- 平台側 TTL
  upstream_expires_at TIMESTAMPTZ NULL           -- provider 側（免費版 60 分鐘）
  closed_at           TIMESTAMPTZ NULL
  closed_by           UUID  NULL REFERENCES users(id)

  ix_node_tunnels_node       (node_id)
  ix_node_tunnels_created_by (created_by)
  uq_node_tunnels_live_port  UNIQUE (node_id, port) WHERE closed_at IS NULL
```

| 決定 | 理由 |
|---|---|
| `CHECK (port BETWEEN 1024 AND 65535)` | 三層防守的其中一層。這一條錯了的後果是把 `sshd` 轉給網際網路 |
| `basic_auth_hash` 而非明文 | 密碼只在建立回應中出現一次（D5），之後只能 rotate（＝關閉並以新密碼重開）。沿用 enrollment token 的既有紀律 |
| 沒有 `status` 欄位 | 狀態一律推導：`closed_at` / `expires_at` / node 是否連線 / `state_error_code` 四者合成。存一份 status 就會有一份與事實不同的 status |
| `url` 可為 NULL 且可被更新 | 建立與取得 URL 之間有數秒；免費版每小時會變（D9）。**URL 變更要寫 `url_updated_at`**，UI 才能顯示「幾分鐘前更新」 |
| `upstream_expires_at` 與 `expires_at` 分開 | 兩個不同的東西：平台的 TTL 是我們的政策，provider 的時限是對方的。混成一欄會讓「為什麼它自己斷了」變成無法解釋 |
| 不存 `url_history` 表 | 曾考慮保留歷史 URL（`00-…md` §1 判準 3 的用語是「歸檔而非覆寫」）。**決定：以稽核紀錄承擔**（`tunnel.url_changed` 不設，改為在 `tunnel.close` 的 metadata 記錄 URL 變更次數）。一張只為了「以前的網址是什麼」而存在的表，沒有人會查 |

下行 migration 直接 drop table；需通過 upgrade→downgrade→upgrade 重複執行測試。

### 2.2 Migration `0016_tunnel_integration.py`：整合設定與 per-node 設定

需求變更後新增的兩張表。**這是本期唯一在平台資料庫內保管第三方憑證的地方。**

```
tunnel_integration                      -- 單列（platform-level）
  id                UUID  PK
  singleton         BOOLEAN NOT NULL DEFAULT TRUE UNIQUE  CHECK (singleton)
  enabled           BOOLEAN NOT NULL DEFAULT FALSE
  provider          TEXT  NOT NULL DEFAULT 'pinggy'  CHECK (provider IN ('pinggy'))
  plan_tier         TEXT  NOT NULL DEFAULT 'free'    CHECK (plan_tier IN ('free','pro'))
  token_ciphertext  BYTEA NULL
  token_nonce       BYTEA NULL
  token_fingerprint TEXT  NULL          -- sha256(token) 前 8 hex，僅供顯示與稽核比對
  concurrent_budget INTEGER NOT NULL DEFAULT 8  CHECK (concurrent_budget BETWEEN 1 AND 100)
  default_protection TEXT NOT NULL DEFAULT 'basic'
  default_ttl_seconds INTEGER NOT NULL DEFAULT 14400
  allowed_ports     JSONB NULL          -- 全域上限；NULL = 1024-65535
  acknowledged_at   TIMESTAMPTZ NULL    -- Admin 的資料外流確認（D14 第一處）
  acknowledged_by   UUID NULL REFERENCES users(id)
  updated_at        TIMESTAMPTZ NOT NULL
  updated_by        UUID NULL REFERENCES users(id)

node_tunnel_settings                    -- per-node（平台側，PG-11 的頁面）
  node_id       UUID  PK REFERENCES nodes(id) ON DELETE CASCADE
  enabled       BOOLEAN NOT NULL DEFAULT TRUE
  allowed_ports JSONB NULL              -- 只能比全域更窄；NULL = 不額外收窄
  max_tunnels   INTEGER NULL            -- NULL = 用全域預算
  updated_at    TIMESTAMPTZ NOT NULL
  updated_by    UUID NULL REFERENCES users(id)
```

| 決定 | 理由 |
|---|---|
| `singleton BOOLEAN … UNIQUE CHECK (singleton)` | 整合設定是平台級的單一事實。用一張表 + 唯一約束強制它只有一列，比在程式裡「總是取第一列」可靠 —— 後者在有第二列時會靜默地用錯設定 |
| `token_ciphertext`／`token_nonce`／`token_fingerprint` 三欄 | AES-GCM 需要 nonce；指紋讓人能回答「現在裝的是不是我上週換的那一把」而不洩漏任何字元（D19）。**沒有 `token_plaintext`，也沒有欄位可以放它** |
| `BYTEA` 而非 base64 TEXT | 少一次編碼／解碼與一次「忘記解碼就直接當金鑰用」的機會 |
| `concurrent_budget` 預設 **8**（2026-08-01 決定） | 這是**車隊級**的上限：整個平台同時存活的隧道數，對應一個 provider token 能同時開幾條。以全域 live tunnel 計數單獨檢查，**不進 per-node 的 `min()`**（`00-…md` D17b）。`PG-01` #8 仍必須確認方案的實際併發數：**若方案允許少於 8，這個值必須調降到符合方案**，否則第 9 條的後果不是排隊而是踢掉別人的隧道（Pinggy 的 `+force` 語意）。UI 的欄位說明因此寫「請依你的方案填寫」 |
| `acknowledged_at`／`acknowledged_by` | D14 的第一處確認（Admin 決定本組織使用這個服務）。存在表上而非只在稽核裡，因為 UI 要據此決定是否再次顯示確認 |
| `node_tunnel_settings.enabled` 預設 **TRUE** | D3：整合的總開關在平台層，per-node 預設參與。**要停用某一台就在這張表關掉**，而 node 擁有者仍可用本機設定一票否決（D17） |
| `allowed_ports` 兩層都是 `NULL = 不額外收窄` | 讓「沒設定」與「設成空清單（全部禁止）」是兩件不同的事。後者是合法且有意義的設定 |
| 沒有 per-node token | D18：平台一組憑證。若日後真的需要 per-node token，那是一次新的資料保管決定，不是加一欄 |

下行 migration 直接 drop 兩張表；需通過 upgrade→downgrade→upgrade 重複執行測試。

**加密與金鑰**：AES-GCM，金鑰來自新設定 `CLIORA_SECRET_ENCRYPTION_KEY`（32 bytes，base64）。實作放在新的 `backend/app/security/secret_box.py`，用既有的 `cryptography>=45`（`backend/pyproject.toml` 已有），**不新增依賴**。三條規則寫在該檔檔頭：

1. 金鑰未設定時，`enable` 與 `set_credential` 一律拒絕（`SECRET_KEY_MISSING`），不得退化成明文儲存。
2. 解密只發生在 `tunnel.open` 的組裝路徑上，明文不進任何 dataclass 欄位、不進日誌、不跨 await 邊界持有超過必要範圍。
3. 金鑰遺失＝已存憑證無法解密。處置是「重新輸入 token」，不是還原資料 —— runbook 要寫（`00-…md` §7 上線階段）。

### 2.3 Migration `0015_seed_tunnel_actions.py`

idempotent seed，**三個** action：`tunnel.view` ＋ `tunnel.manage` 授予 **Admin 與 Developer**；**`integration.manage` 只授予 Admin**；**Viewer 三者皆無**（`FR-TUNNEL-002.AC-04`）。四種情境測試：clean、repeat、prior-data、permission contraction。

| action | 角色 | 為什麼 |
|---|---|---|
| `tunnel.view` | Admin、Developer | 看得到網址等於能存取那個預覽。Viewer 的唯讀語意在被代理的 app 內不成立 |
| `tunnel.manage` | Admin、Developer | 建立／關閉／換密碼，邊界由 ownership 承擔 |
| **`integration.manage`** | **只有 Admin** | 它包含「貼上組織的第三方憑證」與「決定全組織是否使用這個服務」。Developer 能開隧道，但不能決定用誰的服務、用誰的帳號 —— 這與 `enrollment.manage`／`node.manage` 只給 Admin 的既有分界一致 |

三處同步（少一處 `backend/tests/db/test_permission_matrix.py` 會失敗，不得 skip）：`services/rbac.py:26-36` 新增三個常數、同檔 `:53-59`（Developer 兩個）與 `:60`（`_ADMIN_ACTIONS` 加 `INTEGRATION_MANAGE`）、`frontend/src/api/dto.ts` 新增三個 `ACTION_*`。`docs/permission-matrix.md` 以 `scripts/p4/render_permission_matrix.py --write` 重新產生。

資源層（`services/authz.py`）四個判定：

| 判定 | 規則 |
|---|---|
| `may_manage_integration(user)` | `integration.manage`（無資源範圍：整合設定是單一全域物件） |
| `may_create_tunnel(user, node)` | `tunnel.manage` **且** 整合已啟用 **且** node 未停用 **且** 三層設定的交集允許（`04-…md` §1.1） |
| `may_close_tunnel(user, tunnel)` | `tunnel.manage` **且**（`created_by == user` **或** 持有 `node.manage`） |
| `may_view_tunnel(user, tunnel)` | `tunnel.view` |

per-node 設定的修改（`PG-11` 的頁面）授權：**`tunnel.manage`**，不是 `integration.manage`。理由：那是「這台機器允許哪些 port」的日常操作，而不是「本組織是否使用這個服務」的決定。

### 2.4 Node 的能力回報

Central 必須能在 API 層就回答「這個 node 能不能開隧道」，否則使用者要按下按鈕、等 daemon 回一個錯誤才知道。

做法：`node.register` 與 `node.runtime_status` 的 payload 新增 `tunnel`（物件，可選）：

```json
{"tunnel": {"veto": false, "ssh_available": true, "egress_ok": true,
            "known_hosts_ok": true, "allowed_ports": ["3000-3999", "5173"],
            "max_tunnels": 1, "daemon_supports_tunnel": true}}
```

**回報的是先決條件，不是憑證。** 憑證已由平台保管（D4／D18），所以 node 不再有 `credential_configured` 這個欄位可回報。

| 欄位 | 用途 |
|---|---|
| `veto` | node 本機是否否決（`tunnel.enabled: false`）。**平台無法覆寫**（D17），UI 必須顯示「此 Node 已在本機停用」 |
| `ssh_available`／`egress_ok`／`known_hosts_ok` | 三個先決條件（`03-…md` §1.3 的 `doctor` 三項）。UI 據此顯示可行動的原因，而不是讓使用者按下建立後拿到一個 20 秒的逾時 |
| `allowed_ports`／`max_tunnels` | node 本機的收窄值，參與 D17 的交集運算 |
| `daemon_supports_tunnel` | 舊版 daemon 沒有這個能力。缺欄位＝不支援，UI 顯示「請升級此 Node 的 agentd」 |

存進 `nodes` 表新增的欄位（migration `0016` 一併）：`tunnel_veto`、`tunnel_prereq_ok`（三項的 AND）、`tunnel_prereq_detail`（JSONB，三項各自的值）、`tunnel_local_allowed_ports`、`tunnel_local_max`、`tunnel_reported_at`。需要在 node 離線時仍能顯示「上次回報的狀態」。

`egress_ok` 的量測時機：**隨 heartbeat 每 5 分鐘一次**（不是每次 heartbeat —— 那是每 10 秒對第三方發一次 TCP 連線，會像掃描）。這個值天生會過時，UI 顯示時要帶 `tunnel_reported_at`。

### 2.5 Settings（`backend/app/settings.py`）

啟用與否**不再是環境變數**，改由 `tunnel_integration.enabled` 決定（需求變更：Admin 在 UI 啟用）。環境變數只留三類：金鑰、上限、逾時。

```python
# --- P11 第三方隧道整合（ADR 0022）---
# 保管整合憑證用的對稱金鑰（32 bytes，base64）。未設定 → 啟用整合的 API 直接
# 拒絕（SECRET_KEY_MISSING），絕不退化成明文儲存。功能的開關本身在資料庫
# （tunnel_integration.enabled），由持有 integration.manage 的 Admin 在 UI 決定。
secret_encryption_key: str = ""
tunnel_max_ttl_seconds: int = 24 * 3600
tunnels_per_node_max: int = 3           # 與整合設定、per-node 設定、node 回報取 min
tunnels_per_user_max: int = 5
tunnel_open_timeout_seconds: float = 20 # ssh 連線 + provider 指派 URL + 解析
tunnel_basic_password_length: int = 24
tunnel_node_prereq_interval_seconds: int = 300   # egress 探測頻率（§2.4）
```

兩個 validator（沿用該檔既有 `reject_dev_secrets_in_production` 的形狀）：

1. `secret_encryption_key` 非空時必須是 base64 解碼後恰好 32 bytes，否則啟動失敗。一個長度錯的金鑰會在第一次加密時才爆，而那時使用者正在按「儲存憑證」。
2. `environment == "production"` 且 `secret_encryption_key` 為空 → **不阻止啟動**（多數部署不用這個功能），但 `/readyz` 的 body 要標示「tunnel integration unavailable: no encryption key」。理由：這不是服務不可用，是一個功能不可用，把它變成啟動失敗會逼所有不用這個功能的部署都去產一把金鑰。

**`tunnel_open_timeout_seconds` 為什麼是 20 秒**：它包含 SSH 交握、provider 指派 URL、daemon 解析 stdout 三段，其中第二段完全不在我們掌握中。這是本期最可能需要依 `PG-01` 實測值調整的常數，註解要寫明它的來源是量測而非猜測。

**`tunnel_open_timeout_seconds` 為什麼是 20 秒**：它包含 SSH 交握、provider 指派 URL、以及 daemon 解析 stdout 三段，其中第二段完全不在我們掌握中。這是本期最可能需要依 `PG-01` 實測值調整的常數，註解要寫明它的來源是量測而非猜測。

### 2.5 Error catalog

> **實作順序修正（2026-08-01）**：`backend/tests/test_error_catalog.py` 有三條互鎖的守門規則 ——
> (a) wire enum 內的每個碼都必須在 catalog 裡（所以六個 wire 碼要與契約同一個 PR）、
> (b) catalog 裡的每個碼都必須真的有人拋（所以 `TUNNEL_INTEGRATION_DISABLED`／
> `TUNNEL_NODE_DISABLED`／`SECRET_KEY_MISSING` **必須與 `PG-07`／`PG-09` 的服務同一個 PR**，
> 提早加會讓 `test_the_catalog_documents_nothing_fictional` 失敗）、
> (c) 前端 `utils/errorCatalog.ts` 的碼集合與 `retryable` 旗標必須完全一致，且**每筆都要明寫
> `retryable`**（守門測試是逐筆位置比對，省略會讀到下一筆的值）。
> `scripts/p4/render_error_catalog.py` 的 `SECTIONS` 也要加一節，否則
> `test_every_entry_appears_in_exactly_one_rendered_section` 會失敗。

`backend/app/api/error_catalog.py` 新增六筆；`docs/error-catalog.md` 由 `scripts/p4/render_error_catalog.py` 重新產生。幾筆的 `next_step`（使用者唯一會看到的東西）：

| 碼 | next_step |
|---|---|
| `TUNNEL_INTEGRATION_DISABLED` | 「埠轉發整合尚未啟用。請由管理員在「系統整合設定」啟用並填入服務商憑證。」 |
| `SECRET_KEY_MISSING` | 「此環境未設定憑證加密金鑰，因此無法保存服務商憑證。請聯繫部署管理員設定 `CLIORA_SECRET_ENCRYPTION_KEY`。」 |
| `TUNNEL_NODE_DISABLED` | 「此 Node 未參與埠轉發。可在此頁的設定區開啟；若顯示為本機停用，需由該 Node 的擁有者在 `/etc/agentd/config.yaml` 解除。」 |
| `TUNNEL_PROVIDER_NOT_CONFIGURED` | 「此 Node 尚不具備埠轉發的先決條件（ssh 用戶端、對外連線、主機金鑰）。請於該 Node 執行 `agentd doctor` 查看缺哪一項。」 |
| `TUNNEL_PROVIDER_UNAVAILABLE` | 「暫時無法連上隧道服務商。請稍後重試；若持續發生，請確認該 Node 可對外連線到服務商的 443 埠。」 |
| `TUNNEL_PROVIDER_UNAUTHORIZED` | 「服務商憑證無效或已過期。請由管理員在「系統整合設定」更新憑證。」 |
| `TUNNEL_PROVIDER_UNTRUSTED` | 「服務商的主機金鑰與已佈署的紀錄不符，連線已中止。這可能代表該 Node 的對外連線被攔截；請聯繫管理員，勿停用金鑰驗證。」 |

最後一條的措辭是刻意的：使用者遇到 host key 不符時最自然的反應是找方法關掉檢查，錯誤訊息必須先把那條路堵住。

### 2.6 驗收

- `make test-db` 全綠，含 `0014`／`0015`／`0016` 的 upgrade→downgrade→upgrade。
- `port` CHECK、`protection` CHECK、`provider` CHECK、`plan_tier` CHECK 各有一例直接 INSERT 的負向測試；`tunnel_integration` 的 singleton 約束有一例「插入第二列必須失敗」。
- `test_permission_matrix.py` 全綠；四例：Viewer 對 tunnel 端點 403（action 層）、**Developer 對整合設定端點 403（action 層，`integration.manage` 只給 Admin）**、Developer 關他人隧道 403（scope 層）、Developer 關自己成功。
- `secret_box.py` 的單元測試：加解密往返、錯誤金鑰無法解密（AES-GCM 的 tag 驗證）、金鑰未設定時 `encrypt` 直接拋錯而非回傳明文、金鑰長度錯誤在 settings validator 就被擋。
- 契約：四筆 invalid fixture 全被拒，含 `credential` 含 `+` 的那一筆。
- 整合未啟用時所有 tunnel 端點 404，且有測試。
