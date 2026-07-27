# 07 — P1-W7 Node UI

對應 `research/01/02-phase-1-node-control-plane.md` §P1-W7。涵蓋 ticket **P1-17**（前端基礎）、**P1-18**（Login/Nodes/Node detail）、**P1-19**（Enrollment）。需求：FR-AUTH-001、FR-NODE-002/003/004/005、FR-INSTALL-001/002、PRD §10、style.md。

## 目標

把 P0 的 path-based `P0App.vue`（僅 `/poc/terminal`、`/poc/tokens`）升級為真正的 vue-router + Pinia 應用，接上 typed API client 與 auth guard，實作 Login、Nodes list、Node detail、Enrollment 四個 route，資料全由 API store 提供，並處理全部非同步與權限狀態。Dashboard 此階段只做必要 summary（真實聚合留 P4）。沿用 P0 已建立的 semantic tokens、`AppShell`、`StatusBadge`、`AsyncState` 與 Naive UI theme override。

## P1-17：前端基礎（router / store / API client）

現況：`main.ts` 直接掛 `P0App.vue`，無 router 實例、無 Pinia、無 `src/api`。P1 建立：

```text
frontend/src/router/index.ts       路由 + auth guard（未登入導向 /login）
frontend/src/stores/               Pinia：auth、nodes、enrollment（僅共享狀態）
frontend/src/api/client.ts         fetch wrapper：base URL、Bearer 注入、401 自動 refresh、typed error
frontend/src/api/dto.ts            與 backend DTO 對齊的 TypeScript 型別
frontend/src/composables/          useAsyncResource（loading/error/stale 生命週期 owner）
```

規則：

- **auth guard**：access token 由 auth store 管理；401 時以 refresh token 自動續期，失敗才導回 Login；token 不放 localStorage 明文以外的可疑位置（策略記 ADR）。ws-ticket 取得封裝於 api client 供 P2 使用。
- **AppShell 導覽**：把 P0 的 `<a href>` 佔位導覽換成 router-link，側欄含 Nodes、Enrollment（Dashboard summary、Sessions 佔位待後續 phase）；保留 P0 `/poc/terminal` 於 flag/dev 路由。
- **DTO 對齊**：node 狀態值（Online/Degraded/Offline/Disabled）、runtime、時間欄位（RFC 3339 UTC）與 backend 一致；時間在前端本地化顯示，tooltip 顯示完整 instant。
- 移除或明確標示棄用 prototype `App.vue` 的 `Cask` 字樣；正式品牌 `Cliora`（沿用 ADR 0005，可保留 `VITE_PRODUCT_NAME`）。

驗收：router 導航、未登入 guard、401 refresh、logout 清狀態、api client typed error 對映，皆有 unit test；lint/typecheck/build 通過。

## P1-18：Login、Nodes list、Node detail

Views（對齊 PRD §10、tech §6.2）：

- **LoginPage**：帳號、密碼、登入按鈕、錯誤提示（FR-AUTH-001）；錯誤不區分帳號是否存在；載入/停用/鎖定狀態；鍵盤可操作、focus 管理。
- **NodesPage**（FR-NODE-003、PRD §10.3）：欄位 Node 名稱、狀態、Hostname、OS、Claude、Codex、Session 數量、最後在線時間、操作（查看／停用／移除，依 RBAC 顯示）。以 typed component 呈現（沿用 `StatusBadge`）；狀態色彩依 style.md（Online `#2F9B63`、Offline `#727B87`、Busy `#C68C37`、Error `#D25454`），且**狀態不可只靠顏色**（icon + 文字）。「停用」與「移除」是不同動作：停用切換 `is_enabled`（保連線、禁新操作）；**移除為軟刪除**（保留稽核紀錄、撤銷 credential、自清單消失，見 `05`），需明確二次確認並說明「保留紀錄、不可復用 node_id」。預設清單排除已移除 node。
- **NodeDetailPage**（FR-NODE-004、PRD §10.4）：基本資訊、Runtime 狀態、Workspace Root、目前 Session（P1 顯示 0/佔位）、Daemon 資訊、系統資源、最後 Heartbeat、安裝與更新狀態、最近錯誤。危險操作（停用／移除／撤銷 credential）需二次確認 dialog。

所有資料元件必須處理狀態集：`idle / loading / success / empty / stale / offline / forbidden / partial / error`（UI 狀態契約）。P1 具體對應：

| 狀態 | 來源 | 呈現 |
|---|---|---|
| loading | API 進行中 | skeleton / spinner（style.md §23） |
| empty | 無 node | 空清單引導（建立 enrollment token） |
| stale/offline | Central 計算 Degraded/Offline | badge + 最後在線時間（PRD §17.5 本地化格式） |
| forbidden | RBAC deny（如 Viewer 看不到操作） | 隱藏/停用操作，必要時 403 view（PRD §17.3） |
| partial | 部分 runtime 偵測失敗 | 逐項標示可用/原因 |
| error | API 失敗 | Error view + retry（PRD §17） |

驗收（延續 research §P1-W7）：keyboard 操作、三角色差異（Viewer 無停用/移除/建 token）、offline/stale 呈現、API failure + retry、空清單、responsive overflow（≥1440×900 baseline，較窄 viewport 狀態仍可達）E2E 通過；狀態移除顏色後仍可理解，達 WCAG AA。

## P1-19：Enrollment view

對應 InstallationPage（PRD §10.7）與 FR-INSTALL-001/002：

- 建立 enrollment token（Admin only）：設定過期時間與 max_uses；建立後**只此一次**顯示明文 token 與一行安裝指令（含 `--server/--token/--name/--user`），提供複製；關閉後不可再取回明文（對齊 03 的 once-only）。
- token 清單狀態：有效、已過期、已用完、已撤銷；顯示建立者、建立時間、過期時間、已用/上限次數；撤銷需確認。
- 安裝紀錄/支援平台/Daemon 版本 summary（PRD §10.7）；安裝紀錄可先以最近註冊的 node 呈現。
- 錯誤狀態：建立失敗、撤銷失敗、無權限（Viewer/Developer 不可建立）。

驗收（延續 research §P1-W3/W7）：明文 token 只顯示一次且重新整理後不可再得；過期／已用／撤銷狀態正確；複製指令可用且不顯示真實完整既有 token；RBAC 差異（僅 Admin 可建立/撤銷）E2E 通過；載入/錯誤/空狀態齊備。
