# 05 — Phase 4：管理、維運與上線強化

## 階段目標

把已完成的垂直功能收斂為可營運 MVP：角色權限一致、重要操作可稽核、異常可觀測、Daemon 可安全更新，並通過發布與安全門檻。

## 工作包

### P4-W1 RBAC 完整化

- 建立 permission matrix：Admin/Developer/Viewer 對 node、enrollment、session、terminal writer、files、audit 的 action。
- HTTP、browser WS、daemon WS 與 UI visibility 使用同一 domain policy；UI 隱藏不能替代 server authorization。
- role/permission 透過 idempotent Alembic seed migration，測 clean/repeat/prior-data/permission contraction。
- 資源範圍與 owner 規則明確，尤其 attach/takeover/terminate/read file。

驗收：每個 endpoint/message type 具 allow/deny tests，Viewer forged mutation 一律失敗。

### P4-W2 Audit Log

- 涵蓋 login/security event、enrollment、node register/disable、session create/attach/takeover/terminate、敏感路徑拒絕、daemon update。
- metadata 最小化、redact、aware timestamp、actor/resource/request ID；不得記 terminal bytes、password/token/credential。
- Admin audit UI 支援 filter、pagination、empty/loading/error 與 timezone 顯示。

驗收：重要操作均產生單一可追蹤 audit；redaction test 與 retention/backup 決策完成。

### P4-W3 Dashboard 與 error management

- 將 prototype Dashboard 接上真實 aggregates：online/offline nodes、running sessions、runtime health、recent activity。
- stale/partial 指標必須標示 freshness，不偽裝即時資料。
- 建立 node/session/error detail 與可行建議；不把 daemon internal error 原樣暴露。
- 確認所有原型硬編碼值、token、版本、日期已移除。

驗收：partial backend failure、empty deployment、offline fleet、timezone locale 與角色差異 E2E 通過。

### P4-W4 Observability 與容量

- Backend metrics：connections、sessions、WS bytes/messages、queue、timeout、HTTP latency、DB pool。
- Daemon heartbeat metrics：CPU/memory/load/disk/session/uptime；structured logs 可 correlation。
- 建立 alerts/runbooks：heartbeat loss、queue saturation、timeout surge、DB exhaustion、update failure。
- 以 PRD 100 nodes、10 sessions/node、500 terminal WS 做 representative load test。

驗收：slow client/flood 不造成 unbounded memory；告警可在演練環境觸發並依 runbook 處置。

### P4-W5 Daemon release/update

- amd64/arm64 reproducible artifacts、checksum、version manifest、簽章/來源策略。
- update 僅接受 allowlisted release，驗證 checksum，失敗可 rollback，不以 root 長期運行。
- 升級時 existing tmux session 的保留/reconciliation 行為有文件與測試。
- doctor/version/UI 清楚呈現 current/latest/update status，但不在 client 任意指定 URL/binary。

驗收：successful、checksum mismatch、network failure、rollback、restart recovery 全通過。

### P4-W6 Backup、deployment 與 release gate

- PostgreSQL backup/restore rehearsal；確認不含 terminal raw log。
- production HTTPS/WSS、secret injection、migration order、readiness、graceful shutdown。
- 瀏覽器 Chrome/Edge/Safari/Firefox 最新版 smoke；Linux 支援矩陣驗證。
- security review：stolen token、replay、forged frames、path attacks、viewer input、WS flood、log leakage。
- release checklist 含 accessibility、performance、E2E、race、dependency/artifact scan。

驗收：staging restore、rollback 與 incident drill 完成；所有 P0–P4 exit criteria 有可重現證據。

## MVP 最終驗收旅程

1. Admin 登入並建立一次性 enrollment token。
2. 在支援 Linux 以 non-root user 一行安裝，daemon 自動 outbound WSS 註冊。
3. 平台顯示 Node、runtime 與正確 online/offline。
4. Developer 在 allowed workspace 建立 Claude/Codex session，完整操作原生 CLI。
5. Browser refresh 後 reattach，另一使用者只能 viewer，授權 takeover 可稽核。
6. 唯讀瀏覽/預覽合法程式碼；敏感、binary、oversize、symlink escape 均拒絕。
7. 終止 session、停用 node、撤銷 credential；Dashboard、audit、metrics 正確反映。
8. 備份/還原與 daemon update/rollback 演練通過。

## 階段出口

- PRD 第 19 節 20 項 MVP 驗收條件全部有測試或操作證據。
- PRD NFR latency/scale/availability 有量測結果，未達標項目有明確 release decision。
- Security baseline 15 項全數簽核，無未處理 Critical/High finding。
- 發布版本可重建、可部署、可 rollback、可觀測並有 runbook。
