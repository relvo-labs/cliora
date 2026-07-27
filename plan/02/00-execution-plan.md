# 00 — P1 執行總控

## 1. 成功定義與非目標

P1 要退休五個最高風險：durable 資料層（migration/rollback/tz-aware）是否可靠、正式 authentication 與 WS handshake 是否安全、enrollment token 是否防過期/重放/超次數、Go daemon 是否能以可撤銷 credential 完成 outbound WSS 認證與 heartbeat、以及 Node 狀態是否只由 Central 依 monotonic timeout 判定而不信任 daemon 自報。

P1 必須交付：

- FastAPI 分 `api / services / repositories` layer；PostgreSQL + SQLAlchemy 2（async）+ Alembic，timestamp 全 tz-aware。
- login/refresh/logout/me；Argon2id 密碼雜湊；短效 JWT access + 可撤銷 refresh；HTTP 與 browser/daemon WS boundary 皆做 authentication；可插拔 resource RBAC。
- Admin 建立限時、限次 enrollment token；DB 只存 hash；明文只顯示一次；防重放；成功後交換可撤銷 node credential。
- `agentd` cobra 子命令、typed YAML config（`0600`）、non-root 檢查、outbound WSS + TLS 驗證 + Ed25519 nonce challenge、heartbeat、backoff+jitter、graceful shutdown、Claude/Codex allowlisted runtime 偵測。
- Central connection registry（durable metadata 入 DB、socket 不入 DB）、Online/Degraded/Offline/Disabled 計算、node disable、request correlation 與 timeout。
- Linux amd64/arm64 binary、checksum、systemd unit、`install.sh`、`agentd doctor`，並在三個支援發行版通過安裝矩陣。
- Login/Nodes/Node detail/Enrollment 頁，資料由 typed API store 提供並處理全部非同步狀態。

P1 明確**不做**：真實 Terminal session 生命週期與 attach（P2）、workspace 檔案樹與唯讀預覽（P3）、RBAC 完整營運/Audit 檢視介面與 Daemon 自動更新（P4）、Dashboard 真實聚合（P4）、macOS daemon、任意 shell、Central SSH、多 agent orchestration、水平擴充。P0 的 dev gateway（`/ws/p0/*`、fixed identity、shared token）保留在明確 `CLIORA_P0_ENABLED` flag 之後，供 Terminal 垂直切片使用，直到 P2 以認證連線取代；P1 不刪除它，但正式 control plane 不得依賴它。

## 2. 固定實作基線

| 項目 | P1 決定 |
|---|---|
| Layout | 沿用 `backend/`、`daemon/`、`frontend/`、`contracts/`、`tests/`；backend 新增 `app/{api,services,repositories,db,auth,security}`，daemon 依 tech §6.3 補 `internal/{config,connection,auth,runtime,systeminfo,installer,localstore}` |
| Runtime | 沿用 ADR 0001：Python 3.12.3、Go 1.26.5、Node 22.14.0、tmux ≥3.4；不導入 Turborepo |
| DB | PostgreSQL 16；SQLAlchemy 2 async（asyncpg driver）；Alembic 管理 migration；測試以獨立 schema/資料庫並可離線重跑 |
| Password | Argon2id（`argon2-cffi`）；參數在 settings 固定並記入 ADR |
| Token | JWT（access 15 分鐘、refresh 14 天可撤銷）；browser WS 用一次性短效 ticket（60s、single-use、綁 user+resource）；不放長效 JWT 於 query string 或 log |
| Node credential | `node_id + private_key`；DB 只存 `secret_hash`；每次連線以 challenge-response HMAC 驗證；credential 檔 `0600`、可撤銷、可輪替 |
| Enrollment token | 預設過期 1 小時、`max_uses=1`；DB 只存 `token_hash`；明文只回一次 |
| Node 狀態 | 由 Central 依**最後 heartbeat 的 monotonic 間隔**計算：0–30s Online、31–90s Degraded、>90s Offline；管理員停用為 Disabled；不信任 daemon 自報狀態 |
| Heartbeat | 每 10s；回報 daemon version、active session count、資源摘要；OS/arch/runtime/workspace roots 於 `node.register` 一次性上報 |
| Product name | 正式名稱 `Cliora`（沿用 ADR 0005）；UI 移除 prototype `App.vue` 的 `Cask` 字樣，或明確標示其為棄用 reference |
| Time | 內部 aware time；傳輸 RFC 3339 UTC `Z`；duration/timeout/backoff 以 monotonic clock |
| Terminal storage | 沿用 ADR 0004：terminal bytes 不進 log/DB；P1 無新增 terminal 持久化 |

任何偏離上表的實作差異先記 ADR 再改，不以未量測預設值當永久產品限制。

## 3. 垂直架構與 ownership

```text
Browser (Vue Router + Pinia)
  ├─ HTTP: api/client → FastAPI api/ → services/ → repositories/ → PostgreSQL
  │        auth guard、ws-ticket、typed DTO、safe error
  └─ (P2) browser terminal WS，用 ws-ticket 認證

FastAPI Central
  api/            HTTP route + browser/daemon WS boundary（authN + authZ + validation）
  services/       use case、RBAC、node 狀態、enrollment、correlation
  repositories/   PostgreSQL persistence（唯一寫 durable state 之處）
  db/             engine、session、Alembic
  registry（記憶體）NodeConnectionRegistry：活躍 daemon socket、pending request、send-lock
        └─ daemon outbound WSS（/ws/nodes/{node_id}，Ed25519 nonce challenge 後建立）
             └─ Go daemon
                  connection/  單一 read owner + 單一 write owner + reconnect/heartbeat
                  auth/        challenge-response 簽章、credential 載入
                  runtime/     claude/codex 偵測與 allowlisted BuildCommand（P1 只偵測/回報）
                  session/     沿用 P0 tmux/PTY（P1 不擴充生命週期）
```

資源 owner：每個 HTTP request 在 boundary 完成 authN/authZ/validation 後才進 service；service 內以單一 transaction 完成 mutation。Central 每條 daemon WS 由一個 handler 擁有 read task 與 per-node send-lock；registry 是活躍 socket 與 correlation 的唯一 owner，durable metadata 一律經 repository 落 DB。Daemon 一個 goroutine 擁有 socket read、一個擁有 write，其他 producer 只送 bounded channel；credential、heartbeat timer、runtime detector 皆可在 shutdown 時被取消並等待結束。

## 4. 執行順序與 ticket

| Wave | Ticket | 產出 | 前置 |
|---:|---|---|---|
| 0 | P1-01 | 決策 ADR：auth 方案、node credential 模型、狀態計時、DB/migration、installer/systemd | 無 |
| 0 | P1-02 | protocol v1.1：node.register/registered/system_info/runtime_status/shutdown、daemon.doctor/version、新 error codes、fixtures 與三語言 codec | P1-01 |
| 0 | P1-03 | Central 分層 scaffold + DB engine/session + Alembic + health/readiness + request-id + safe error + structured log | P1-01 |
| 1 | P1-04 | schema migration（users/roles/nodes/node_runtimes/node_workspace_roots/enrollment_tokens/node_credentials/audit_logs）+ role seed migration | P1-03 |
| 1 | P1-05 | Auth：login/refresh/logout/me、Argon2id、JWT access+refresh、expiry、logout 撤銷 | P1-04 |
| 1 | P1-06 | RBAC 骨架、resource authorization、audit 寫入服務 | P1-05 |
| 1 | P1-07 | WS handshake：browser ws-ticket + daemon Ed25519 nonce challenge-response boundary | P1-05、P1-02 |
| 2 | P1-08 | Enrollment token CRUD、hash-at-rest、once-only、過期/次數/replay、audit | P1-06 |
| 2 | P1-09 | Node 註冊 + credential 簽發/撤銷/輪替、`node.register` 處理、install-script/downloads endpoint | P1-07、P1-08 |
| 2 | P1-10 | Go daemon：cobra 子命令、typed YAML config、credential `0600`、non-root 檢查、`config validate` | P1-02 |
| 2 | P1-11 | Daemon connection manager：outbound WSS + TLS 驗證 + HMAC、heartbeat、backoff+jitter、graceful shutdown | P1-09、P1-10 |
| 2 | P1-12 | Runtime adapters：Runtime interface、claude/codex 偵測（含 timeout）、allowlist、system_info/runtime_status 上報 | P1-10 |
| 3 | P1-13 | Central connection registry：durable metadata 落 DB、per-node send-lock、request correlation + timeout + late-response cleanup | P1-07、P1-11 |
| 3 | P1-14 | Node 狀態計算（monotonic timeout）、disable 行為、duplicate connection、Central restart 重註冊 | P1-13 |
| 4 | P1-15 | Release artifacts（amd64/arm64、checksums、GoReleaser）、`install.sh`、`agentd install/uninstall`、systemd unit、目錄權限 | P1-11、P1-12 |
| 4 | P1-16 | `agentd doctor` 檢查 + Ubuntu 22.04/24.04、Debian 12 安裝/啟動/重啟/移除矩陣 | P1-15 |
| 5 | P1-17 | Frontend 基礎：vue-router + Pinia + typed API client + auth store/guard、AppShell 導覽 | P1-05 |
| 5 | P1-18 | Login + Nodes list + Node detail views（全非同步狀態、RBAC 差異、responsive） | P1-17、P1-14 |
| 5 | P1-19 | Enrollment view（once-only secret、過期/已用/撤銷/錯誤、一行指令複製、安裝紀錄） | P1-17、P1-09 |
| 6 | P1-20 | CI 擴充（DB service、migration test、install 矩陣、security suite）、E2E、操作證據、exit review | 全部 |

關鍵路徑為 `01 → 02/03 → 04 → 05 → 07 → 09 → 11 → 13 → 14 → 20`。Wave 內可並行，但修改契約或 schema 的 PR 必須先於 consumer 合併。

## 5. 每張 ticket 的完成格式

每張 ticket 至少附：變更檔案、契約/假設、成功與失敗測試（含 forbidden/timeout/disconnect/rollback）、實際執行命令、log/metric/audit 影響（且證明無 secret/token/terminal content）、以及對應 requirement（`FR-AUTH-*`、`FR-NODE-*`、`FR-INSTALL-*`、`FR-RUNTIME-*`、`FR-CONN-*`、`SEC-*`、`NFR-*`）。跨語言行為改變時，同一變更必須同步 schema、fixtures 與 Python/Go/TS 三個 consumer。DB 行為改變時，同一變更必須提供 upgrade + downgrade migration 與 rollback 測試。

## 6. P1 預設限制與參數（待量測，記入 ADR 0007/0008）

| 項目 | 初值 | 滿額/逾時行為 |
|---|---:|---|
| JWT access token TTL | 15 min | 過期回 401 `TOKEN_EXPIRED`，需 refresh |
| JWT refresh token TTL | 14 天 | 過期或已撤銷回 401，需重新 login |
| Browser WS ticket | 60 s、single-use | 過期/重用回 handshake 拒絕並 close |
| Enrollment token 預設 | 過期 1 h、`max_uses=1` | 過期/超次數/已撤銷回 `ENROLLMENT_TOKEN_INVALID`，記 audit |
| Ed25519 nonce challenge nonce | 30 s、single-use | 逾時或重用回 auth 失敗並 close |
| Heartbeat interval | 10 s | 見狀態計算 |
| Online / Degraded / Offline | ≤30s / 31–90s / >90s | 由 Central monotonic timeout 判定，不信任自報 |
| Control request timeout | Runtime/Workspace 10s、Directory 15s、File 30s、Session start 30s、stop 20s、attach 15s（tech §7.3） | `REQUEST_TIMEOUT`，清 correlation entry |
| Daemon reconnect backoff | 1/2/5/10/30，上限 60s + ≤250ms jitter | 沿用 P0 daemon loop，成功即重置 |
| Per-node pending requests | 上限（初值 128） | 拒新請求回 `INTERNAL_ERROR`／`NODE_BUSY`，不無界成長 |
| Node 列表載入 | < 2 s（NFR-001） | 分頁/索引；量測後定稿 |
| 規模基準 | 100 node、每 node 10 session、全平台 500 terminal WS（NFR-003） | P1 只驗 control-plane 規模；terminal 於 P2 |

限制與參數皆以可設定值實作，量測後在 ADR 接受或修訂，不硬編碼為永久產品限制。

## 7. 決策閘門（P1-01 前必須記錄）

1. **Auth 方案**：JWT access+refresh 的簽章演算法與 key 管理、logout/refresh 撤銷機制（黑名單 vs 短 TTL + 版本欄位）、browser WS ticket 生命週期。
2. **Node credential 模型**：新增 `node_credentials` 表（PRD §12/tech §13 未明列，本規劃補上）欄位、HMAC 演算法、rotation 與 revocation 語意、challenge nonce 儲存。
3. **狀態計時**：以 monotonic clock 計算 heartbeat 間隔與 online/degraded/offline 邊界；`last_seen_at` 仍以 aware wall-clock 持久化供顯示。
4. **DB/migration 策略**：async engine、Alembic autogenerate 政策、role seed 以 versioned migration（不在 startup 偷 seed）、測試資料庫建置與離線重跑。
5. **user 角色關係**：PRD §12.1 以 `users.role_id` 單一角色 vs tech §13.1 `user_roles` join。P1 採單一 `role_id`（對應 §8.1 權限矩陣），`user_roles` 與 `daemon_releases` 延後至 P4。
6. **TLS 驗證**：production WSS 以標準 server 憑證驗證（驗 CA、hostname）；client cert / pinning 列為可選，記入 ADR。
7. **Enrollment once-only 顯示**：明文 token 與 private_key 只回一次、不再可查；此為安全預設（PRD 未明列，本規劃補上）。

## 8. 明確非目標與變更控制

P1 不加入 Terminal session lifecycle、workspace files、Daemon 自動更新/rollback（`agentd update` 子命令可保留為 stub 但不實作更新流程）、RBAC 完整營運介面、Dashboard 真實聚合、macOS daemon、任意 shell、Central SSH、Git automation、多 agent orchestration 或水平擴充。需要其中任一項時，先依 `06-requirement-traceability.md` §6 變更 canonical requirements，再更新本目錄與階段出口，不能只在 implementation ticket 中暗自擴張。
