# 02 — Phase 1：Node Control Plane

## 階段目標

完成可安全註冊、驗證、連線與觀測的 Node 基礎，使管理員能一行安裝 Daemon，平台能正確呈現 Node、runtime 與在線狀態。

## 工作包

### P1-W1 Central 基礎與資料層

- FastAPI 分 API/service/repository/WS layers；PostgreSQL + SQLAlchemy 2 + Alembic。
- 建立 users/roles、nodes、node_runtimes、node_workspace_roots、enrollment_tokens、audit_logs。
- 所有 timestamp 使用 timezone-aware DB type 與 RFC 3339 UTC DTO。
- 建立 health/readiness、request ID、safe error mapping、structured logging。

驗收：migration 可 clean upgrade、重跑及支援的 downgrade；transaction rollback 與 aware timestamp 測試通過。

### P1-W2 Authentication 與基本授權骨架

- 實作 login/refresh/logout/me，密碼安全雜湊與 token/session expiry。
- 建立 Admin/Developer/Viewer stable role keys；以 versioned migration seed，不在 startup 偷 seed。
- HTTP 與 browser/daemon WS handshake 都做 authentication；resource RBAC 可插拔。

驗收：success、invalid、disabled、expired、forbidden、expiry equality 與 WS unauthorized 測試通過。

### P1-W3 Enrollment 與 Daemon credential

- Admin 建立限時、限次 token；DB 只存 hash；明文只顯示一次。
- enrollment 防 replay；成功後交換可撤銷的 node credential。
- 記錄 create/revoke/use/register audit，但不記 secret。
- UI 實作產生、複製、過期、已使用、撤銷、錯誤狀態。

驗收：過期、重放、超次數、競態使用與撤銷後連線全被拒絕。

### P1-W4 Go Daemon connection manager

- `agentd serve/doctor/version`、typed config、credential `0600`、non-root 檢查。
- outbound WSS、TLS peer validation、heartbeat、exponential backoff + jitter、graceful shutdown。
- runtime adapters 只偵測/啟動 Claude、Codex allowlisted binaries；不上傳 shell command。
- heartbeat 回報版本、OS/arch、runtime、resource summary 與 session count。

驗收：Central restart、網路中斷、bad credential、TLS failure、shutdown/race 測試通過；log 無 token。

### P1-W5 Connection registry 與 Node 狀態

- Central registry 維護 active daemon connection；durable metadata 入 DB、socket 不入 DB。
- 依 heartbeat/monotonic timeout 計算 online/offline/stale，不信任 daemon 自報狀態。
- node disable 立即拒絕新操作並撤銷/斷開 credential；行為具 audit。
- request correlation 有 timeout、late response cleanup 與 per-node bounds。

驗收：duplicate connection、missing heartbeat、late response、Central restart 與 disabled node 行為確定。

### P1-W6 Installer 與 artifacts

- Linux amd64/arm64 binary、checksum、systemd unit、config/credential 目錄權限。
- 安裝流程明示執行 Linux user 的權限；長期服務不得 root。
- installer 檢查 checksum、平台/架構、tmux、endpoint，失敗可診斷且不洩漏 token。
- `doctor` 檢查網路、config 權限、runtime、tmux、allowed roots。

驗收：Ubuntu 22.04/24.04、Debian 12 測試環境安裝、啟動、重啟與移除流程通過。

### P1-W7 Node UI

- routes：Login、Nodes list、Node detail、Enrollment；Dashboard 此階段只做必要 summary。
- 將原型 nodes cards/list 拆成 typed components，資料由 API store 提供。
- 處理 loading/empty/stale/offline/forbidden/partial/error；last seen 本地化且 tooltip 顯示完整 instant。
- Node detail 顯示 runtime、workspace roots、daemon、resource、最近錯誤；危險操作需 confirm。

驗收：keyboard 操作、角色差異、offline/stale、API failure、空清單與 responsive overflow E2E 通過。

## 階段出口

- 管理員可建立一次性 token 並以一行指令在支援 Linux 安裝。
- Daemon 自動 outbound WSS 註冊，Central 正確顯示 online/offline 與 Claude/Codex 狀態。
- credential revocation、node disable、heartbeat timeout 與 audit 可被測試證明。
- 無 Terminal session 功能也能獨立部署、診斷與觀測 control plane。
