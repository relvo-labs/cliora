# Cliora P1 可實作規劃

本目錄把 `research/01` 的 Phase 1（Node Control Plane）轉成可直接建立 ticket、撰寫程式與驗收的執行規格。P1 的產品成果，是讓管理員能建立一次性 enrollment token、以一行指令在支援的 Linux 安裝 Daemon，Daemon 以 outbound WSS 自動註冊、認證與 heartbeat，平台則正確呈現 Node、runtime 與 online/offline/degraded/disabled 狀態，並可停用 Node 與撤銷 credential。P1 不實作真實 Terminal session 生命週期、workspace 檔案瀏覽或 RBAC 完整營運介面（留在 P2–P4）。

## 前置狀態

- P0 已交付並經審查（見 `docs/p0-report.md`）：protocol v1 契約與三語言 codec、`ConnectionRegistry`/`BrowserChannel` backpressure、daemon reconnect/heartbeat loop、tmux/PTY session manager、xterm composable 與 semantic tokens 皆為可用且有測試的基礎。
- P0 exit 標記為 **No-Go**，唯一 blocker 是「daemon/browser 中斷後 tmux attach client 殘留導致 recovered attach 阻塞」。該 blocker 屬 Terminal 重連路徑（P2 範疇）。**P1 的 control-plane 工作可並行推進**，但 P1 的 daemon 重連與 Central restart 重註冊測試不得依賴 terminal reattach；該 blocker 必須在 P2 開工前關閉（見 `08-verification-and-exit.md` §風險）。
- P0 為單一硬編碼 node（`…0001`）+ 單一硬編碼 session（`…0002`）、fake runtime、無資料庫、無 router/Pinia、dev token + subprotocol 認證。P1 依 `docs/adr/0006-p1-auth-handoff.md` 以「認證瀏覽器 session + 資源授權 + 可撤銷、可輪替的 daemon credential」取代這些 dev 捷徑。

## 文件順序

| 文件 | 用途 |
|---|---|
| [00-execution-plan.md](./00-execution-plan.md) | 範圍、非目標、固定基線、垂直架構、ticket 波次、共同完成定義與 P1 預設限制 |
| [01-data-layer.md](./01-data-layer.md) | P1-W1：Central 分層、PostgreSQL + SQLAlchemy 2 + Alembic、schema、tz-aware、health/error/log |
| [02-auth-rbac.md](./02-auth-rbac.md) | P1-W2：login/refresh/logout/me、Argon2id、JWT、role seed、RBAC 骨架、WS handshake |
| [03-enrollment-credential.md](./03-enrollment-credential.md) | P1-W3：enrollment token、hash-at-rest、once-only、replay/過期/次數、credential 交換與撤銷 |
| [04-daemon-connection.md](./04-daemon-connection.md) | P1-W4：agentd 子命令、typed config、outbound WSS + Ed25519 challenge、heartbeat、runtime adapters、graceful shutdown |
| [05-registry-node-status.md](./05-registry-node-status.md) | P1-W5：connection registry、node 狀態計算、disable、request correlation |
| [06-installer-artifacts.md](./06-installer-artifacts.md) | P1-W6：amd64/arm64 artifact、checksum、systemd unit、install.sh、doctor、安裝矩陣 |
| [07-node-ui.md](./07-node-ui.md) | P1-W7：router/Pinia/API client、Login、Nodes、Node detail、Enrollment 與所有非同步狀態 |
| [08-verification-and-exit.md](./08-verification-and-exit.md) | 測試矩陣、CI gates、操作證據、P1 exit gate、ADR/決策清單、風險 |

## 使用規則

1. 先完成 `P1-01`（決策 ADR）與 `P1-02`（protocol v1.1 契約凍結），再並行 Central、Daemon 與 Frontend。修改契約的 PR 必須先於 consumer 合併，且同步更新 schema、fixtures 與 Python/Go/TS 三個 consumer。
2. 每項 task 都需提交其列出的產物與測試；「可手動展示」不能替代自動測試。
3. 依 `.agent/skills/cliora-project-context`：先檢視 repo 現況、不假設規劃中的目錄已存在、做最小可行變更，並保全 trust-boundary invariants（outbound-only daemon WSS、runtime-ID allowlist、無 Central SSH、無任意 shell、PostgreSQL 不存 terminal bytes）。
4. 需求變更先更新 `research/prd.md`／`tech.md`／`style.md`，再同步 `research/01/06-requirement-traceability.md`，不得在 implementation ticket 中暗自擴張範圍。
5. 所有時間採 tz-aware；持久化用 timezone-aware PostgreSQL 型別，傳輸 RFC 3339 UTC，畫面才本地化；duration（heartbeat timeout、token expiry、backoff）以 **monotonic** 計算。

## 完成結果

P1 通過時，管理員可在 Enrollment 頁建立一次性 token、複製一行安裝指令，在 Ubuntu 22.04/24.04 或 Debian 12（amd64/arm64）以非 root 使用者安裝 Daemon；Daemon 驗 checksum、寫 `0600` config/credential、以 outbound WSS + Ed25519 nonce challenge 認證後 `node.register`，並每 10 秒 heartbeat。Central 依 monotonic heartbeat timeout 計算 Online/Degraded/Offline，正確顯示 Claude/Codex 可用狀態，管理員可停用 Node 並撤銷 credential；過期、重放、超次數、撤銷後連線與未授權 WS 全被拒絕並留下不含 secret 的 audit。整套 control plane 在沒有任何 Terminal session 功能下即可獨立部署、診斷與觀測。
