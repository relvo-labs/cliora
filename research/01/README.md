# Cliora 分階段實作規劃

本目錄把既有 PRD、技術規劃、視覺規格與 `frontend` prototype，轉成可逐階段執行與驗收的工作包。

## 文件導覽

| 文件 | 用途 |
|---|---|
| [00-implementation-roadmap.md](./00-implementation-roadmap.md) | 全局策略、架構邊界、里程碑與共通完成定義 |
| [01-phase-0-technical-foundation.md](./01-phase-0-technical-foundation.md) | 技術基線與高風險 PoC |
| [02-phase-1-node-control-plane.md](./02-phase-1-node-control-plane.md) | Central、Daemon、註冊與 Node 管理 |
| [03-phase-2-session-terminal.md](./03-phase-2-session-terminal.md) | Session、tmux、Terminal 與重連 |
| [04-phase-3-workspace-files.md](./04-phase-3-workspace-files.md) | Allowed Root、檔案樹與唯讀預覽 |
| [05-phase-4-operations-hardening.md](./05-phase-4-operations-hardening.md) | RBAC、Audit、監控、更新與上線強化 |
| [06-requirement-traceability.md](./06-requirement-traceability.md) | 需求、階段、測試與原型頁面對照 |

## 建議使用方式

1. 先閱讀總覽，確認範圍、技術決策與不做事項。
2. 每次只啟動一個階段；階段內可依工作流並行，但先完成契約與風險尖峰。
3. 每個工作包以「契約 → 實作 → 自動測試 → 操作證據」完成。
4. 階段出口條件未通過，不把下一階段標為可發布。
5. 需求變更先更新 `research/prd.md`／`tech.md`／`style.md`，再同步本目錄追蹤矩陣。

## 規劃基準

- 產品與範圍：`research/prd.md`，尤其第 6、8–12、15–20 節。
- 架構與協定：`research/tech.md`，尤其第 7–16、18–24 節。
- 視覺與互動：`research/style.md`，尤其第 3–24 節。
- 原型證據：`frontend/src/App.vue`、`frontend/src/styles.css`。
- 專案技能：`.agent/skills` 中的 project context、backend、FastAPI、Go daemon、terminal protocol、Vue/Naive UI、design system、security、timezone 與 testing 指引。

> 名稱注意：目前原型畫面使用 `Cask`，專案文件使用 `Cliora`。正式實作前需由產品決策確認；本規劃不自行把原型名稱提升為產品需求。
