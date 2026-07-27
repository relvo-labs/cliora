# 03 — P1-W3 Enrollment 與 Daemon credential

對應 `research/01/02-phase-1-node-control-plane.md` §P1-W3。涵蓋 ticket **P1-08**（enrollment token）、**P1-09**（node 註冊與 credential）。需求：FR-INSTALL-001/002、FR-NODE-001、SEC-003、tech §14.2。

## 目標

讓 Admin 建立限時、限次且 hash-at-rest 的 enrollment token，明文只顯示一次；Daemon 以 token 完成一次性註冊並交換可撤銷的 node credential；成功與撤銷皆有 audit，全程不落 secret 明文。

## P1-08：Enrollment token

Endpoints（PRD §11.3，Admin 專屬）：

```text
POST   /api/enrollment-tokens          建立 → 回 {id, token(明文，僅此一次), expires_at, max_uses}
GET    /api/enrollment-tokens          列出（不含明文；顯示狀態/已用次數/過期）
DELETE /api/enrollment-tokens/{id}     撤銷（is_active=false）
GET    /api/install-script             回一行安裝腳本內容（見 06）
GET    /api/downloads/{filename}       回 artifact（checksum 對照，見 06）
```

實作規則：

- **產生**：token 明文以 CSPRNG 產生（足夠 entropy，帶可辨識 prefix 如 `enroll_`）；DB 只存 `token_hash`（雜湊演算法記 ADR 0008，建議 HMAC-SHA256 或 Argon2id）；明文**只在建立回應回傳一次**，之後不可再查（本規劃補上的安全預設，P1-01 §7）。
- **限時/限次**：`expires_at`、`max_uses`（預設 1）、`used_count`、`is_active`。驗證時檢查 `is_active && now < expires_at && used_count < max_uses`。
- **防重放與併發**：使用時以單一 transaction 對該列 `SELECT … FOR UPDATE` 後遞增 `used_count`，避免兩個併發註冊同時通過 `max_uses`（競態使用測試必過）。過期/超次數/撤銷/未知一律回 `ENROLLMENT_TOKEN_INVALID`（不區分細節以免枚舉）。
- **audit**：`enrollment.create`（記 created_by、expires_at、max_uses，不記明文/ hash）、`enrollment.revoke`、`enrollment.use`（記結果與來源 hostname，不記 token）。

驗收（延續 research §P1-W3）：過期、重放、超次數、併發使用、撤銷後全被拒；明文只回一次且清單/詳情不外洩明文；audit 完整且無 token 值。

## P1-09：Node 註冊與 credential 交換

註冊走 **HTTP**（安裝當下 daemon 尚無 node_id/secret），與認證後的 `node.register` metadata 上報分離：

```text
POST /api/nodes/register
  headers/body: enrollment token + {public_key, name, hostname, os, os_version, architecture,
                daemon_version, run_user, runtimes[], workspace_roots[]}
  → 201 {node_id, server_url}
```

流程與規則：

- 驗 enrollment token（P1-08 語意）→ 於單一 transaction 建立 `nodes` 列（`is_enabled=true`、`registered_at`、`last_seen_at=null`）、`node_runtimes`、`node_workspace_roots`，並建立 `node_credentials`（`public_key`、`algorithm`、`version=1`、`issued_at`）。
- daemon 本機產生 `private_key`，Central 只接收 `public_key`。daemon 收到後寫 `/etc/agentd/credentials.yaml`（`0600`）。
- 遞增 enrollment token `used_count`（同 transaction）；達 `max_uses` 後 token 自然失效。
- 之後 daemon 以 `node_id + private_key` 走 `/ws/nodes/{node_id}` Ed25519 nonce challenge（見 `02-auth-rbac.md` §P1-07）；連線後送 `node.register` 上報/刷新 metadata，central 更新 DB 並回 `node.registered`。
- **Credential 撤銷/輪替**：Admin 停用或移除 node，或安全事件時，可將 `node_credentials.revoked_at` 設值使現行連線與後續認證失效；輪替以新增 `version` 並作廢舊 version 實作（避免 gap）。撤銷寫 `credential.revoke` audit。node disable（`is_enabled=false`）與 credential revoke 是不同動作：disable 保留連線但禁新操作，revoke 直接斷線。

驗收（延續 research §P1-W3/W5）：完整走一次 register→credential→WS 認證連線→`node.register` 落 DB；private_key 僅由 daemon 本機產生，從不回傳；撤銷 credential 後現行連線被斷、後續認證被拒；被 disable 的 node 仍可連線但拒絕建立性操作；所有事件有 audit 且不含 secret。
