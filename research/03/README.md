# Cliora V2 產品體驗重設 — 分階段規劃

本目錄是 [`research/cliora-project-experience-redesign-plan.md`](../cliora-project-experience-redesign-plan.md)
（下稱**體驗重設提案**，v1.3）落到**這個 repo 現況**的執行規劃。

提案回答「要做什麼、為什麼」；本目錄回答「在已經存在的 189 條需求、43 個 migration、
1873 行 model、27 個 RBAC 動作、contract 1.13.0 與 `agentd` 0.14.1 之上，
**怎麼做得出來、做完怎麼證明、哪一段不該做**」。

一句話說明這一輪要做的事：

> Ticket 從「一張卡加一串留言」變成**一條可恢復的持久對話**；Project 從「一堆卡」變成
> **一層有來源、有版本、有可信層級的記憶**；看板從「六個固定欄」變成**同一份資料的多個投影**。
> 三者合起來，讓一句模糊的需求能在同一張 Ticket 裡被問成規格、被 Agent 引用著知識實作、
> 把成果與驗證送回同一張 Ticket，由人做最後決定。

## 版本定位

| 產品版本 | 里程碑 | 內容 | 本目錄的文件 |
|---|---|---|---|
| `v2.0.0-alpha.1` | **V2-A1** Control Plane Baseline | [`research/02/`](../02/README.md) 的七期實作，已完成 | 只在 `00` 記錄 freeze checklist |
| `v2.0.0-alpha.2` | **V2-C1** Ticket Conversation | 持久對話、question、answer＋resume、continuation turn | [`02`](./02-phase-c1-ticket-conversation.md) |
| `v2.0.0-alpha.3` | **V2-K1** Project Memory | knowledge sources、hybrid search、citations、Context Builder | [`03`](./03-phase-k1-project-knowledge.md) |
| `v2.0.0-beta.1` | **V2-P1** Collaborative Project Workspace | View 讀模型、Board／Backlog、Task Drawer、My Work | [`04`](./04-phase-p1-view-and-read-model.md)–[`07`](./07-phase-p4-my-work-and-overview.md) |
| `v2.0.0-beta.2` | **V2-E1** Ecosystem and Hardening | provider 同步、a11y、效能、遷移演練、rollback | [`12`](./12-migration-and-rollout.md) |

`research/02/` 的 `V2.0`–`V2.5` 從此**只是歷史 implementation phases**，不是產品 release number。
三層版本名稱（product release／capability milestone／component version）的分工在 [`00`](./00-roadmap-and-versioning.md) §2。

## 文件導覽

| 文件 | 用途 |
|---|---|
| [CHECKLIST.md](./CHECKLIST.md) | **執行清單**：76 張 ticket、9 份 ADR、待裁決（**現只剩 D46**）、9 個未量測項攤平成可打勾的清單 |
| [00-roadmap-and-versioning.md](./00-roadmap-and-versioning.md) | 版本定案、release train、rolling-horizon roadmap、`alpha.1` freeze checklist |
| [01-architecture-decisions.md](./01-architecture-decisions.md) | **D37–D58 決策**，含「與提案不同的八處」與待裁決項（**現只剩 D46**）|
| [02-phase-c1-ticket-conversation.md](./02-phase-c1-ticket-conversation.md) | `alpha.2` Ticket-native Agent Conversation（`CV-`） |
| [03-phase-k1-project-knowledge.md](./03-phase-k1-project-knowledge.md) | `alpha.3` Project Knowledge Hub（`KN-`） |
| [04-phase-p1-view-and-read-model.md](./04-phase-p1-view-and-read-model.md) | `beta.1` 第一段：View schema、attention projection、work-items API（`PX-`） |
| [05-phase-p2-board-and-backlog.md](./05-phase-p2-board-and-backlog.md) | `beta.1` 第二段：Active Board、Backlog、rank、DnD（`PX-`） |
| [06-phase-p3-task-drawer.md](./06-phase-p3-task-drawer.md) | `beta.1` 第三段：URL-driven Drawer、conversation-first（`PX-`） |
| [07-phase-p4-my-work-and-overview.md](./07-phase-p4-my-work-and-overview.md) | `beta.1` 第四段：My Work、Project Overview（`PX-`） |
| [08-data-model-and-contract.md](./08-data-model-and-contract.md) | 12 張新表、既有表的 additive 欄位、contract 影響、RBAC、兩種憑證 |
| [09-frontend-architecture.md](./09-frontend-architecture.md) | ProjectDetailView 拆分、server state、URL state、元件清單 |
| [10-verification-and-exit.md](./10-verification-and-exit.md) | 各里程碑出口條件、測試矩陣、**四次安全審查**、效能預算 |
| [11-requirement-traceability.md](./11-requirement-traceability.md) | 新需求 ID（FR-CONV／FR-KNOW／FR-WORK）、ADR 清單、必須同步修訂的文件 |
| [12-migration-and-rollout.md](./12-migration-and-rollout.md) | feature flag、stage 相容投影、遷移演練、rollback、release 產物 |

## 建議使用方式

1. 先讀 [`01`](./01-architecture-decisions.md) 的 **§1（與提案不同的七處）**——那是本目錄唯一真正需要你看的東西。
2. §3 的裁決狀態：**D40／D42／D44 已於 2026-08-16 裁決**（不做向量檢索／不放寬／不動 contract）；
   **D51 已於 2026-08-22 隨 `plan/25` 的 D81 關閉**。只剩 **D46**（provider sync 落點）。
3. 一次只啟動一個里程碑。`C1` 與 `K1` 可以並行（依賴只有一條，見 `00` §4），但**共享契約先定稿**。
4. 每張 ticket 以「決策 → 契約 → 實作 → 自動測試 → 操作證據」完成。
5. 里程碑出口條件未通過，不建立該 prerelease tag。
6. **`v2` 合併回 `dev` 一律由人工確認**——條件全綠只是取得提案資格，不是核准。
7. 需求變更先更新 `research/prd.md` 與 `traceability/requirements.json`，再同步 [`11`](./11-requirement-traceability.md)。

## 三個獨立旗標

| 旗標 | 控制什麼 | 預設 |
|---|---|---|
| `CLIORA_PROJECTS_ENABLED` | Project、看板、任務（既有） | 沿用現況 |
| `CLIORA_AGENT_RUNS_ENABLED` | Agent Runner 與自主執行（既有） | 沿用現況 |
| `CLIORA_PROJECT_EXPERIENCE_V2` | **新增**：View 讀模型、Board vNext、Drawer、My Work | `false` |

刻意**不**替 Conversation 與 Knowledge 各開一個旗標，理由在 [`01`](./01-architecture-decisions.md) D52：
conversation 是既有 `task_messages` 的修復，用旗標關掉等於讓留言在兩種語意間漂移；
knowledge 的開關是 **per-project 的 ingestion 設定**而不是部署旗標，因為它的成本與風險是逐專案的。

## 規劃基準（2026-08-16 核對，**2026-08-23 由 `plan/26` 的 `PX-00` 更新**）

以下每一條都在寫這份規劃時實際讀過程式碼確認，**不是從既有文件抄的**。
加註「規劃時是…」的列是 `alpha.2` 之後變動的事實。

| 項目 | 現況 |
|---|---|
| `v2` HEAD | `3e503de`（2026-08-23）。規劃時是 `f91d9c4`，ahead 60／behind 6 |
| contract | **1.13.0**（`contracts/CHANGELOG.md`） |
| `agentd` | **0.14.1**（`daemon/VERSION`）。規劃時是 0.12.0；`alpha.2`／`alpha.3` 各升過一次 |
| migration head | **0042**`_knowledge_tables`。規劃時是 0039 |
| RBAC 動作 | **27 個**（`len(ALL_ACTIONS)`；「24」是文件的舊錯，程式一直是 27——`plan/23/10` §9.4），run token scope 只有 `project.view` ＋ `task.update` |
| ADR | 到 **0039** ＋ **0041**（缺號 0025；`alpha.3` 用掉 `0038`／`0039`，`0041` 已 accepted）。**空號只剩 `0040` 與 `0042`**，`plan/26` 的 `PX-21` 用掉這兩個，之後從 **0044** 起（`0043` 已指派給 `beta.2` 的 provider ingestion） |
| 執行計畫目錄 | `plan/01`–`plan/25` |
| `traceability/requirements.json` | **189 條**，**28** 個 ID family（`FR-CONV` 十條於 `alpha.2`、`FR-KNOW` 十一條於 `alpha.3` 註冊，皆 `lifecycle: proposed`） |
| `frontend/src/theme/tokens.css` | **72 個 custom property**（`alpha.3` 之後 62，`plan/26` 的 `PX-17` 加 10），已含 `--stage-*`／`--run-*`／`--risk-*`／`--attention-*`／`--work-*` |
| `plan/19`（前端修復期） | **已實作**（`plan/19/09-implementation-status.md`），README 的「尚未開工」是過期字串 |
| Board 排序 | `updated_at DESC`——**`tasks` 沒有 rank／position 欄位** |
| `task_messages` | 有 `kind ∈ {message,question,answer,event}`，**沒有 seq、沒有 reply_to、沒有 idempotency key** |
| `cliora task messages` | 以 **timestamp** 分頁（`--since`），不是單調序號 |
| `cliora task ask` | **不等待**；一個 run 同時只能有一個未答問題（ADR 0034 §4）；24 小時無人答 → 卡片進 blocked |
| runner poll | 預設 **5 秒**（`DefaultRunnerPollInterval`） |
| 前端資料層 | **沒有 query cache 套件**；`useAsyncResource` ＋ Pinia store 手寫 |
| PostgreSQL | `postgres:16-alpine`，**沒有 pgvector** |
| Central 對外連線 | 只有 `httpx`，只有 `services/providers.py` 一個模組（SCOPE-013） |

> 本目錄只做規劃，不含程式碼變更。執行計畫在 `plan/` 下逐里程碑建立，沿用 `plan/22/` 的文件結構：
>
> | 里程碑 | 執行計畫 | 狀態（2026-08-23） |
> |---|---|---|
> | C1 實作 | [`plan/23/`](../../plan/23/README.md) | **已實作**（`CV-00`…`CV-13`），剩下的兩項由 `plan/24` 關閉 |
> | **C1 封版** | [`plan/24/`](../../plan/24/README.md) | **已完成**（`CE-01`…`CE-19`），封版條件 28／28，兩個 annotated tag 已建立（留在本機） |
> | **K1** | [`plan/25/`](../../plan/25/README.md) | **已實作**（`KN-00`…`KN-13`），出口條件 **26／28**，`v2.0.0-alpha.3` **未 tag**（缺 Railway `pg_trgm` 驗證與 SR-2 簽核） |
> | **P1** | [`plan/26/`](../../plan/26/README.md) | **已建立**（2026-08-23），A 類八項裁決完成，波次 0 已實作 |
> | E1 | `plan/27/` | 未建立 |
>
> **K1 之後各順移一號**：`alpha.2` 的封版工作佔用了原先留給 K1 的 `plan/24/`，
> 因為它在時間上接在 `plan/23/` 之後，而一個依時間排序的目錄比一個依里程碑預留的空號好讀。
> 執行計畫與本目錄不一致時，**以執行計畫為準並回寫這裡**——它讀的是程式碼，本目錄讀的是構想。
