# Cliora Version 2 分階段升級規劃

本目錄把 [`research/version2.md`](../version2.md) 的升級構想，與 [`../../Monstrare`](../../Monstrare)
的治理流程層，合併成一份可逐階段執行與驗收的計畫。

一句話說明 V2 要做的事：

> 平台成為**使用者與 Agent 之間的橋樑**。使用者丟一句模糊的需求，Agent 在看板上反覆提問把它問成規格、拆成任務卡；
> Agent 像 GitHub Runner 一樣自行認領任務卡，在隔離的工作目錄裡拉取 git、帶著安全下放的機密執行，
> 依卡片宣告的交付模式（**卡片產物**／PR／分支／無交付）把成果送回來，執行中也能隨時把報告、截圖、diff 附到卡片上。
> **原有的互動式 Session 完整保留**，那是使用者要親自操作時的路徑。

## 三次裁決（2026-08-08）

| # | 裁決 | 影響 |
|---|---|---|
| 1 | 任務卡要能在平台上拖曳 | 內化之後這是一次 DB `UPDATE`，不碰檔案 |
| 2 | Monstrare **功能內化**，不複製檔案進使用者專案 | 真實來源翻面為平台 DB；取消了原本風險最高的兩份 ADR |
| 3 | **Agent 作為 Runner 自行認領任務**（拉取式；卡片可指定或不指定 agent），多對多、隔離環境、機密下放、依卡片交付 | V2 從「專案管理功能」變成「執行控制平面」；**撤銷兩條既有紅線**，換上新的紅線 5 |
| 4 | **納入 Monstrare 的需求釐清與任務拆解能力** | 新增 V2.5。釐清的「問」直接落在既有的看板溝通管道上，不新增介面 |
| 5 | **Agent 可交付產物到任務卡**（執行中亦可留言附檔） | 紅線 5 從「列舉三種出口」改為**陳述原則**：每一種出口都必須落在人看過才生效的地方。卡片產物是其中最安全的一種 |

## 文件導覽

| 文件 | 用途 |
|---|---|
| [00-upgrade-roadmap.md](./00-upgrade-roadmap.md) | 全局定位、兩種執行模式、Monstrare 內化清單、**紅線撤銷與換上什麼**、六階段 |
| [01-architecture-decisions.md](./01-architecture-decisions.md) | **D1–D29 決策**，含已裁決、建議採納、仍需裁決三張表 |
| [02-phase-v20-project-foundation.md](./02-phase-v20-project-foundation.md) | V2.0 專案基座（`PJ-`） |
| [03-phase-v21-task-board.md](./03-phase-v21-task-board.md) | V2.1 任務看板與流程內化（`TK-`） |
| [04-phase-v22-agent-runner.md](./04-phase-v22-agent-runner.md) | V2.2 Agent Runner 與任務認領（`AR-`） |
| [05-phase-v23-secrets-and-isolation.md](./05-phase-v23-secrets-and-isolation.md) | V2.3 機密下放與隔離工作目錄（`SC-`） |
| [06-phase-v24-delivery-and-verification.md](./06-phase-v24-delivery-and-verification.md) | V2.4 交付、驗證與證據（`DV-`） |
| [07-phase-v25-requirements-and-decomposition.md](./07-phase-v25-requirements-and-decomposition.md) | V2.5 需求釐清與任務拆解（`RQ-`） |
| [08-data-model-and-contract.md](./08-data-model-and-contract.md) | 資料表、protocol 新增訊息、RBAC、兩種憑證、版本節奏 |
| [09-frontend-information-architecture.md](./09-frontend-information-architecture.md) | 導覽重整、看板、Agents 頁、Requirements、訊息串、Run 詳情 |
| [10-verification-and-exit.md](./10-verification-and-exit.md) | 各階段出口條件、回歸套組、測試矩陣、**四次安全審查**、未量測項 |
| [11-requirement-traceability.md](./11-requirement-traceability.md) | 新需求 ID、ADR 清單、必須同步修訂的既有文件 |

## 建議使用方式

1. 先讀 `00`，特別是 **§2（兩種執行模式）** 與 **§7（紅線撤銷了什麼、換上什麼）**。
2. 再讀 `01` 的三張裁決表，處理「仍需你裁決」那四項。
3. 每次只啟動一個階段。階段內可同時推進 contract、Central、Daemon、Frontend，但**共享契約先定稿**。
4. 每個工作包以「決策 → 契約 → 實作 → 自動測試 → 操作證據」完成。
5. 階段出口條件未通過，不把下一階段標為可發布。
6. **`v2` 合併回 `dev` 一律由人工確認**——條件全綠只是取得提案資格，不是核准（`10` §7）。
7. 需求變更先更新 `research/prd.md` 與 `traceability/requirements.json`，再同步 `11` 的追蹤表。

## 兩個獨立旗標

| 旗標 | 控制什麼 |
|---|---|
| `CLIORA_PROJECTS_ENABLED` | Project、看板、任務（V2.0／V2.1） |
| `CLIORA_AGENT_RUNS_ENABLED` | Agent Runner 與自主執行（V2.2 起，含 V2.5 的釐清／拆解 run） |

**刻意分開**：看板與自主執行的風險等級差很多，組織可能想要前者不要後者。兩者都關閉時，系統行為與 V1 完全一致。

## 執行慣例：每個階段一個背景 tmux

建議每個階段開一個背景 tmux session 承載長時間工作（agent 執行、`make check`、`make e2e`、遷移演練），不要佔用互動視窗：

```bash
tmux new-session -d -s cliora-v22 -c /home/ubuntu/workspace/cliora
tmux send-keys -t cliora-v22 'make check' C-m
tmux attach -t cliora-v22        # 需要看的時候才 attach
```

命名沿用階段代號（`cliora-v20`…`cliora-v25`）。這也是 dogfooding：平台管的就是這種東西。

## 規劃基準（已核對過的事實）

- 升級構想：`research/version2.md`（已逐節加註五次裁決的偏離處）。
- Version 1 產品與架構：`research/prd.md`、`research/tech.md`、`research/style.md`、`research/01/`。
- 已實作現況：`plan/01`–`plan/15`、`docs/adr/0001`–`0026`。
- 治理流程來源：`../Monstrare/ai/process/`、`ai/templates/`、`tools/kanban/`（MIT，內化時標註出處）。
- 目前基線：contract **v1.9.0**、`agentd` **0.7.0**、migration 到 **0020**、RBAC 16 個動作、前端 5 個導覽項。

> 本目錄只做規劃，不含程式碼變更。階段開工時在 `plan/16/` 起算建立執行計畫目錄，沿用 `plan/15/` 的文件結構。
