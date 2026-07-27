# 08 — 驗證、證據與 P1 Exit Gate

對應 ticket **P1-20**。延續 P0 的驗證紀律（`plan/01/07-verification-and-exit.md`），擴充資料庫、認證、enrollment、daemon 連線與安裝矩陣。

## 1. 測試分層

| 層級 | 必跑內容 | 主要 owner |
|---|---|---|
| Contract | protocol v1.1 新型別 schema、三語言 fixtures、round trip；forbidden/naive-time/bad-arch/unknown-field 拒絕 | protocol |
| Unit（backend） | node 狀態計算（fake monotonic clock）、enrollment token（過期/次數/replay/併發）、RBAC 矩陣、request correlation/timeout、audit redaction、tz-aware round-trip、transaction rollback | Central |
| Unit（daemon） | config validate、非 root/權限檢查、Ed25519 簽章、runtime 偵測（存在/缺/不可執行/timeout）、allowlist 拒任意命令、reconnect/backoff、graceful shutdown（`-race`） | daemon |
| Migration | clean upgrade、重跑、downgrade、role seed 一致性 | Central |
| Integration | enrollment→credential→WSS+Ed25519→`node.register`→DB；Central restart 重連重註冊；duplicate connection；credential 撤銷即斷線 | Central+daemon |
| Install | Ubuntu 22.04/24.04、Debian 12（amd64/arm64）安裝/啟動/重啟/移除；`agentd doctor` | daemon/ops |
| Browser（E2E） | login→nodes→建立 token→（模擬）daemon 註冊→node online/offline/degraded/disabled→停用/撤銷；RBAC 差異；非同步/錯誤狀態；responsive | frontend |
| Security | HTTP+雙 WS 認證、enrollment 過期/replay、credential 撤銷、runtime allowlist、TLS 驗證、audit/log redaction、非 root 最小權限、forged WS/flood | cross-stack |

測試不得依賴外部 Claude/Codex、真實網際網路服務或固定個人路徑；時間/retry/heartbeat timeout 用 fake/monotonic clock；UUID/ULID/nonce 用可注入 deterministic source。PostgreSQL 以 CI service container（或 ephemeral schema）提供，測試後清理。

## 2. 必要 CI gates

延續 P0 的 GitHub Actions（`backend`/`daemon`/`frontend`/`tmux-integration`/`e2e`），P1 新增/擴充：

- `backend`：新增 PostgreSQL service；跑 Alembic upgrade/downgrade + migration/rollback 測試、auth/RBAC/enrollment/status/correlation/audit unit。
- `daemon`：`go vet`、`go test -race`、build amd64/arm64、產生 checksum；config/auth/runtime/reconnect 測試。
- `contract`：Python/Go/TS 對 v1.1 manifest 一致 accept/reject。
- `install-matrix`：release candidate 於支援發行版跑安裝/啟動/重啟/移除（container 或 VM image）。
- `security`：認證、enrollment replay、credential 撤銷、redaction、forged WS/flood 掃描。
- `e2e`：Playwright Chromium/Firefox/WebKit matrix，涵蓋 login→node→enrollment 流程。

每個 PR 跑 format/lint、typecheck、unit、contract、build 與 migration；合併主分支與 release candidate 另跑 integration、install-matrix、security 與 E2E matrix。cache key 含各自 lockfile；CI log 不列印 secret/token/terminal content。

## 3. 操作證據包

在 `artifacts/p1/<run-id>/`（CI artifact）保存：

- `versions.txt`：commit、OS、PostgreSQL、Python、Go、Node/browser、tmux 版本。
- `commands.txt`：執行過的 root task 與 exit status。
- `contract.xml`、`unit-backend.xml`、`unit-daemon.xml`、`migration.xml`、`integration.xml`、`e2e.xml`、`race.txt`。
- `install-matrix.json`：三發行版 × 架構的安裝/啟動/重啟/移除結果與 doctor 輸出。
- `status-timeline.json`：heartbeat online→degraded→offline 邊界轉換與 Central restart 重註冊時間。
- `security-report.md`：認證/enrollment/credential/redaction/forged-WS 結果。
- `screenshots/`：login、nodes（online/offline/degraded/disabled/empty）、node detail、enrollment（once-only secret、已撤銷）、forbidden view。

發布前以測試掃描確認 log/artifact 不含 password、JWT、enrollment token、private_key、challenge 簽章、process environment 或不必要 absolute path。

## 4. Exit Gate checklist

### 功能

- [ ] Admin 可建立一次性 token 並以一行指令在支援 Linux 以非 root 使用者安裝。
- [ ] Daemon 驗 checksum、寫 `0600` config/credential，以 outbound WSS + Ed25519 nonce challenge 認證後 `node.register`，每 10s heartbeat。
- [ ] Central 依 monotonic timeout 正確顯示 Online/Degraded/Offline 與 Claude/Codex 狀態，並可 disable node、撤銷 credential。
- [ ] 無 Terminal session 功能也能獨立部署、診斷（doctor）與觀測 control plane。

### 契約與安全

- [x] Python/Go/TS 共用 v1.2 fixtures 全通過；新型別 forbidden 欄位/naive-time/bad-arch 安全拒絕。
- [ ] enrollment 過期、重放、超次數、併發使用、撤銷後連線全被拒且記 audit。
- [ ] credential 撤銷即斷線並拒後續認證；被 disable node 保連線但拒新操作。
- [x] HTTP、browser ws-ticket、daemon Ed25519 三處認證的 success/失敗路徑有測試；log/audit 無 secret/token/terminal content。
- [ ] production 強制 WSS + TLS 驗證；`ws://` 僅限明確 dev flag。

### 資料與可靠性

- [x] Alembic clean upgrade、重跑、downgrade 通過；transaction rollback 無部分寫入；tz-aware round-trip 與 expiry 相等邊界通過。
- [x] `go test -race ./...` 通過，pytest 無 pending task/leak；duplicate connection、late response、timeout cleanup 無 leak。
- [ ] Central restart 後 daemon 自動重連並重新註冊；狀態依既有連線與 heartbeat 重建。

### 工程基線

- [ ] 乾淨 checkout 依 README 可 bootstrap（含 DB）、migration、build、test、run。
- [ ] CI gates 綠燈且 artifact 可追溯到 commit。
- [x] `research/01/06-requirement-traceability.md` 已以實際證據連結更新（FR-AUTH/NODE/INSTALL/RUNTIME/CONN、SEC、NFR）。

任一項未過即維持 P1 open；不可因 demo 可註冊即豁免認證、enrollment、migration、redaction 或 race gate。

## 5. ADR / 決策清單

| ADR | P1 必答問題 | Owner/截止 |
|---|---|---|
| 0007 auth 方案 | JWT 演算法/key 管理、access/refresh TTL 與撤銷機制、browser ws-ticket 生命週期、TLS 驗證與 dev `ws://` flag | P1-01（P1-05/07 前） |
| 0008 node credential | `node_credentials` 表、HMAC 演算法、rotation/revocation 語意、challenge nonce 儲存、token/secret hash 演算法 | P1-01（P1-08/09/11 前） |
| 0009 資料層 | async engine、Alembic 政策、role/admin seed migration、測試 DB 建置 | P1-03 完成時 |
| 0010 狀態計時 | monotonic heartbeat timeout、online/degraded/offline 邊界、`last_seen_at` 顯示與判定分離 | P1-14 完成時 |
| 0011 installer | install.sh vs `agentd install` 邊界、systemd 選項、支援發行版、checksum/artifact 發佈 | P1-15 完成時 |

同時更新既有 ADR：0006（auth handoff）於 P1 完成時標記 accepted 並連結 0007/0008。

## 6. 已知風險與 P0 carry-over

- **P0 recovery blocker（No-Go）**：daemon/browser 中斷後 tmux attach client 殘留導致 recovered attach 阻塞（`docs/p0-report.md`）。屬 Terminal reattach（P2）。P1 的 daemon 重連與 Central restart 重註冊測試**不得依賴 terminal reattach**；此 blocker 必須在 P2 開工前以獨立 spike 關閉，否則 P2 不得起始。
- **未在 canonical docs 明列、由本規劃補上的決策**（需在對應 ADR 記錄、並視情況回填 PRD/tech）：`node_credentials` 表（PRD §12/tech §13 未明列）、enrollment token/private_key 一次性明文顯示、狀態計時採 monotonic clock 與 backoff jitter、TLS 標準憑證驗證（非 pinning/mTLS）、graceful shutdown 的 `node.shutdown` deregister 序列、`user_roles`/`daemon_releases` 延後至 P4（P1 用單一 `users.role_id`）。
- **規模**：P1 只驗 control-plane 規模（100 node、heartbeat/status），terminal 500 WS 與 session 規模留 P2。

### 已確認產品決策（traceability §5 收斂）

- **平台**：MVP 以 Linux 為主（Ubuntu 22.04/24.04、Debian 12，amd64/arm64）；**macOS daemon 不納入 P1**。
- **Node 移除**：採**軟刪除保留紀錄**（`nodes.deleted_at` + 撤銷 credential），不做 hard delete；語意見 `01`／`05`／`07`。
- **`agentd update`**：P1 僅保留 stub，Daemon 自動更新/rollback 留至 **P4**。

## 7. Go / No-Go review

Exit review 輸出一頁 `docs/p1-report.md`：結果、未通過項、實測參數（token/nonce TTL、狀態邊界、reconnect 恢復時間、安裝矩陣結果）、已知 gap、採納 ADR、P2 follow-ups。只有上述 checklist 全過、且無未處理的高風險認證繞過、secret 外洩、migration 不可回退或 connection/registry leak，才可標記 Go。若不可行，報告必須列出替代方案、需修改的 architecture、重新估算與下一個 time-boxed spike，而非直接進 Phase 2。
