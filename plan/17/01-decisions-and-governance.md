# 01 — 決策、ADR 與治理（`TK-00`、`TK-01`）

## 1. 為什麼需求變更仍然是第一張票

V2.0 已經改過 `.agent/skills/cliora-project-context/SKILL.md` 的範圍句，並寫下 ADR 0027。
那份 ADR 涵蓋的是**專案層與真實來源的翻面**；本期新增的兩個面它沒有涵蓋：

| 本期新增的面 | ADR 0027 有沒有涵蓋 |
|---|---|
| 平台把檔案寫進使用者 workspace 的 `.cliora/` | ❌ 沒有。0027 提到 `.cliora/` 投影是「V2.1 的事」，但沒有決定寫入機制、保留期歸誰、與 ADR 0024／0026 寫入姿態的關係 |
| 一種新的憑證（Session token）與一條新的認證路徑 | ❌ 完全沒有 |
| 內化的流程定義成為**會拒絕請求**的閘門 | ⚠️ 只寫了原則（「規則從請 Agent 遵守變成不遵守就寫不進去」），沒有寫閘門的邊界 |

所以 **`TK-01` 交付 ADR 0028**，不是修訂 0027。理由與這個 repo 一貫的做法一致：
一份 accepted 的 ADR 記錄的是**當時的決定**，後續的決定寫新的並在 Related 互指。

> **ADR 編號確認**：`docs/adr/` 現有 `0001`–`0024`、`0026`、`0027`（`0025` 空號，
> 沿用既有事實不補號）。所以本期用 **0028**。
> 這會讓 `research/02/CHECKLIST` §8 的 ADR 表順移一格：
> V2.2 的兩份變成 **0029／0030**，V2.3 的兩份變成 **0031／0032**，V2.4 → **0033**，
> V2.5 → **0034**。回寫那張表是 `TK-01` 的一部分。

## 2. `TK-00` — 基線擷取與 M1 量測（閘門）

### 2.1 要擷取的四份基線

改完之後**沒有任何辦法**補一份「本期之前」的快照。四份都存進
`artifacts/tk/local/baseline/`（沿用 `artifacts/pj/local/baseline/` 的版面）：

| 基線 | 工具 | 判準用在哪 |
|---|---|---|
| OpenAPI schema | `scripts/pj/openapi_diff.py`（重用，不複製） | 判準 10：旗標關閉時只允許新增路徑，且新增路徑全部 404 |
| `pg_dump --schema-only` | `scripts/pj/schema_snapshot.py`（重用） | 出口條件：既有表逐欄無變化，新增只有本期宣告的那幾張 |
| **contract fixtures 清單 ＋ 逐檔 sha256** | 新增 `scripts/tk/contract_snapshot.py` | **本期新增的一條**：既有 fixtures 一個位元組未變（`08-…md` §4 `GATE-TK-CONTRACT-ADDITIVE`） |
| 導覽與 Project 頁截圖 | `scripts/pj/nav-shot.mjs`（重用） | 旗標關閉時畫面與 V2.0 相同 |

**重用而不是複製。** `scripts/pj/` 的四個工具已經是通用的；本期只加第三份的擷取器。
複製一份 `scripts/tk/openapi_diff.py` 會讓兩份在下一次 FastAPI 升級時分歧。

### 2.2 M1 — 200 張卡的看板 API

**這是本期唯一一個開工前必須有答案的量測**（`research/02/10` §5）。
它決定 `GET /api/projects/{id}/board` 的形狀，而形狀改了前端就要改。

| 項目 | 做法 |
|---|---|
| 造資料 | `scripts/tk/seed_board_fixture.py`：1 個 Project、200 張卡、每張 5 條 AC、7 項 readiness、6 個 gates、平均 1.5 條相依 |
| 量什麼 | ① 未分頁回應的 gzip 前／後位元組數 ② p50／p95 伺服器耗時 ③ 前端首次渲染到可拖曳的時間 |
| 判準 | 回應 **> 512 KB** 或 p95 **> 400 ms** → 看板端點改為**逐車道分頁**（每車道預設 50 ＋ `has_more`），且卡片摘要不含 AC 全文與 gates 明細 |
| 記在哪 | `10-…md` §1，含實際數字與所選形狀 |

**先量再定形狀，不是先做再最佳化**：兩者的差別是前者只要改一次 DTO，
後者要改 DTO、前端、e2e 與已經寫好的測試。

### 2.3 順手確認的三件事（不擋開工）

- `research/02/CHECKLIST` §0 的兩項（`.env` gitignore cherry-pick、`dev` 的 branch protection）
  在 V2.0 收尾時仍是 ☐。它們與本期無關但每一期都會再被問一次，在 `09-…md` 記一次狀態即可。
- Traqora 的 clone 位置與可讀性（D13 的驗收素材，本期第一次真正使用）。
- `agentd` 0.7.0 在測試機上的實際安裝路徑——D2 的 symlink 要放在它旁邊（`06-…md` §1.3）。

## 3. `TK-01` — ADR 0028

**標題**：任務層、Session Token 與平台投影（V2.1）

### 3.1 必須寫進去的七件事

**一、內化的流程定義是閘門，而閘門的邊界在哪。**
`research/02/01` D2 那句「當平台能真的拒絕時，需要靠 prompt 說服 Agent 的部分就變少了」
是 ADR 的核心論證。但要同時寫下**本期真的會拒絕什麼**（只有 `dependsOn`）
與**只警告什麼**（DoR 七項、WIP），以及為什麼（`00-…md` D7）。
不寫這條，V2.4 接 Done Gate 的人會以為 V2.1 已經全部強制過了。

**二、`.cliora/` 的寫入是一條新的寫入路徑，而它為什麼不違反紅線 3。**
這是本期最需要被寫清楚的一段：

| | 使用者的寫入面（ADR 0024／0026） | 平台投影（本期新增） |
|---|---|---|
| 誰發起 | 使用者，帶著 `file.upload` | **平台**，在 Session 建立之後 |
| 寫得到哪 | allowed root 下**除了** `.cliora/` 的任何地方 | **只有** `.cliora/{context,process,reference}/` |
| 覆寫 | 永不（`O_EXCL`） | 永不（同一條，`FILE_EXISTS` 視為成功） |
| 誰清 | 沒有保留期，使用者自己的檔案 | **30 天，daemon 清** |

一句話的不變式：**兩條路徑的可寫集合是互斥的，而且兩條都不覆寫。**
紅線 3（不編輯、不移動、不刪除使用者的檔案）完全成立——投影只在平台自己的目錄裡新增。

**三、Session token 是什麼、不是什麼。**
它不是使用者的 JWT、不是 node credential、不能勾 gate、不能開 Session、不能碰檔案。
`research/02/08` §6 的兩欄表原樣抄進去，並補上本期的實作事實：
**它不走 `get_current_user`**（`00-…md` D3）。

**四、`task.approve` 與 `task.update` 的持有者集合刻意相同。**
D13 例外 3 的定案措辭要在這裡再寫一次（ADR 0027 已寫過一次，
但那時 `task.*` 還不存在，所以那段話沒有一個具體的動作可以指）：

> `task.approve` 與 `task.update` 的持有者集合**刻意相同**。拆開不是為了角色分離，
> 是為了讓「Agent 憑證拿不到核准權」成為一個**可以寫死在 token scope 裡的東西**——
> 一個不存在的動作沒辦法從 scope 裡排除。

**五、`ui` gate 的衍生停用**（D31、`00-…md` D10）。
規則、為什麼不能做成 Admin 手動開關、以及 Project Settings 要寫出停用原因。

**六、三種新儲存的保留期各自的答案**（`00-…md` D9）。
ADR 0024 W2 的問題要對每一種新儲存回答一次，三個答案不同：
`activity_events` 無保留期、投影檔 30 天、`session_tokens` 列保留 90 天。

**七、`source`／`delivery` 建欄不接行為的代價**（`00-…md` D11）。
寫進 Consequences，不是寫進 Context——它是一個**已知會讓人誤解的狀態**，
要能被指著說「這是當初接受的」。

### 3.2 Alternatives rejected（至少這六列）

| 方案 | 為什麼否決 |
|---|---|
| 放寬 `VerbStore` 讓使用者的上傳路徑也能寫 `.cliora/` | 任何持有 `file.upload` 的使用者就能覆寫平台的情境包與 **token 檔**。`store_policy.go` 的 `Verb` 型別註解正是為了讓第二個寫入動詞不繼承第一個的答案而存在 |
| 把情境包寫在 workspace 根目錄的一個檔案（避開新 verb） | 目的地目錄必須事先存在，所以只有根目錄可寫；那會污染使用者 repo 且落在 `.cliora/.gitignore` 的保護之外，直接違反判準 9 |
| 讓 CLI 自己向 Central 拉情境並寫檔（避開 daemon 變更） | 憑證從哪來？token 本身就是要投影的東西之一。而且 D14 要求 `context show` **免連線**，一個「第一次成功後才有快取」的設計在平台一開始就不可用時等於沒有 |
| 投影 `cliora` 二進位到 `.cliora/bin/` | 4 MiB 上限、`.cliora/` 禁區、update 解壓器只取單一成員——三條各自足以否決（`00-…md` D2） |
| Session token 解析成一個 `User` 物件重用既有依賴 | 它會繼承那個人的全部動作，包括 `task.approve` 與 `terminal.operate`。scope 檢查會變成唯一防線，而唯一防線總有一天會被一次重構繞過 |
| 用 `count(*)+1` 或 UUID 當 `card_ref` | 前者會撞號（D5）；後者讓人看不懂，而 `card_ref` 的**唯一用途**就是給人看與進分支名 |

### 3.3 Related

`0014`（路徑安全：投影走的是同一套 `os.Root` 收斂，只是換一個 verb）、
`0016`（RBAC 兩層授權：Agent principal 是第三種呼叫者，但**不新增授權層**）、
`0024`／`0026`（寫入姿態：本期新增一條互斥的寫入路徑，不改既有的）、
`0027`（V2 專案層與真實來源：本期是它的直接後續）、
`0022`（tunnel 整合：`ui` gate 的衍生停用依賴它的 `enabled` 欄位）。

## 4. ~~`TK-01` — 要回寫的規劃文件~~ → **已於 2026-08-09 完成**

規劃層有三處會因為本期的決策而不再正確。**回寫是 `TK-01` 的一部分，不是收尾時的雜項**——
下一個階段的人會拿那些表當事實。

> **狀態：已回寫**（採用方案 A 的當下就做掉，不等 `TK-01`）。實際動到八個檔案：
> `00`（node 升級節奏）、`01`（D11 的發佈方式、ADR 0032→0033）、`03`（四處機制註記）、
> `08`（§2 表列、§4 protocol 表、§9 版本節奏）、`10`（§2.2 出口 11、§4 測試矩陣、§6 安審）、
> `11`（§3 CHANGELOG、§4 ADR 清單）、`CHECKLIST`（§1.3、§3、§8、§9）、`README`（plan 指向）。
> 慣例沿用 `plan/08/01` §1.2：**機制敘述不刪原文、加註記**；**版本與編號的表則直接改**——
> 一個過期的編號表會被下一個階段當成事實，而註記救不了它。

| 檔案 | 改什麼 |
|---|---|
| `research/02/03-phase-v21-task-board.md` | TK-05／TK-06 的機制段落加註記（不刪原文，沿用 `plan/08/01` §1.2 的做法）：投影需要新 verb、CLI 隨 agentd 附帶自 V2.1 起 |
| `research/02/08-data-model-and-contract.md` §4／§9 | 版本節奏整體順移一格：V2.1 = v1.10.0／0.8.0；V2.2 = v1.11.0／0.9.0；V2.3 = v1.12.0／0.10.0；V2.4 = v1.13.0／0.11.0；V2.5 不變 |
| `research/02/CHECKLIST.md` §8 | ADR 編號順移：V2.2 → 0029／0030，V2.3 → 0031／0032，V2.4 → 0033，V2.5 → 0034 |

## 5. `TK-01` — `research/prd.md` 的任務層章節

新增 **§8.12 任務與流程**（現況最後一節是 §8.11 專案管理，`research/prd.md:1550` 起）。

沿用既有格式：`<a id="fr-task-00X"></a>` ＋ `## FR-TASK-00X 標題`，
每條 AC 一個 `<a id="fr-task-00X-ac-NN"></a>` 錨點。

| ID | 標題 | Owner | 關鍵 AC |
|---|---|---|---|
| FR-TASK-001 | 任務層級與生命週期 | central | Epic → User Story → Task 三層；`card_ref` 專案內唯一且**建立後不可變**；未指定 User Story 的 Task 落在未分類桶；沒有刪除，只有封存 |
| FR-TASK-002 | 看板與車道 | central | 六個 stage；任意車道間可移動；進入 `ready` 之後的車道要求前置任務全部完成，**拒絕時須指名是哪幾張**；WIP 超標顯示不阻擋 |
| FR-TASK-003 | 併發與樂觀鎖 | central | 每次更新須攜帶版本；版本不符拒絕且不寫入任何一半；相依關係不得形成循環 |
| FR-TASK-004 | 就緒與審查關卡 | central | DoR 七項與 Review Gates 六項；**核准必帶人類操作者**，非人類憑證一律拒絕；核准記錄操作者與時間；tunnel 整合未啟用時 UI 關卡自動停用並說明原因 |
| FR-TASK-005 | 需求、規格與拆解（人工） | central | 需求 Intake；規格為版本列只新增不修改；**未解決的開放問題存在時規格不得核准**；提案接受後缺 DoR 的卡落 `backlog` |
| FR-TASK-006 | Task 與 Session 關聯 | central | `task_id` 選填且永遠選填；指定時必須與 `project_id` 一致；平台不從 workspace 或 Session 反查 Task |
| FR-TASK-007 | 情境投影 | central／daemon | Session 建立後投影情境包、流程說明與憑證到平台專屬目錄；**投影失敗不影響 Session**；同版本流程檔已存在視為成功；投影檔有保留期；平台不寫入該目錄以外的任何路徑 |
| FR-TASK-008 | Agent 憑證 | central | 每個 Session 一枚、單一 Project 範圍、Session 結束即失效；**永不包含核准、專案管理、檔案與終端動作**；憑證值不得出現在任何回應、日誌或稽核紀錄中 |

**明文宣告兩句**（放在 §8.12 引言，不是附註）：

> 任務資料的真實來源是平台，使用者的 repo 只有程式碼。平台在使用者的工作目錄中
> **只寫入平台專屬目錄**，且只新增、不覆寫、不刪除使用者的檔案。

> 卡片上的執行設定（來源與交付模式）是**意圖宣告**。本階段沒有任何執行者會依它行動。

## 6. `TK-01` — skill 補述

檔案：`.agent/skills/cliora-project-context/SKILL.md`。V2.0 已改過範圍句，本期**只加一段**：

> V2.1 任務層（ADR 0028，accepted）：Epic／User Story／Task 是平台資料。平台會在
> Session 的工作目錄中寫入 `.cliora/`（情境包、流程說明、Session 憑證），
> **除此之外不寫入使用者工作區的任何路徑**，且從不覆寫。Session 憑證的範圍寫死不含
> Review Gate 核准——Agent 的輸出永遠不等於核准。平台不可用時 CLI 直接失敗、不排隊，
> 而 Session 本身不受影響。

**不改既有的三句範圍句**（Git automation／task assignment／multi-agent orchestration）：
本期沒有觸碰它們任何一條。

## 7. `TK-01` — traceability 註冊

沿用 `plan/16/01` §6 已經踩過的兩段式做法（規則沒變，這裡只記本期的數字）：

| 時機 | 做什麼 |
|---|---|
| `TK-01` | 八筆 `FR-TASK-001`–`008` 以 **`lifecycle: "proposed"`** 註冊；link 只建指向 `research/prd.md` 的來源關聯 |
| `TK-02`–`TK-10` | 每張票落地時補上它涵蓋的 AC 的 `planned_by`／`implemented_by`／`verified_by` |
| `TK-11` | 八筆翻成 `lifecycle: "active"`，`make traceability` 必須全綠 |

- ID 樣式 `^FR-[A-Z]+-[0-9]{3}$` 通過（`FR-TASK-001`）。
- `applicability: ["v2"]`，與 `FR-PROJECT-*` 一致——`coverage --scope mvp` 跳過、`--scope all` 不跳。
- `owner`：`FR-TASK-007` 是 **`daemon`**（其餘 `central`；純畫面的 AC 用 `frontend`）。
  這是本期第一筆 owner 不是 central 的 V2 需求，因為投影的最終決定權在 daemon。
- `verification_profile` 全部 `automated`，除了「情境包 ≤ 4 KB 的人工檢視」與
  「Traqora 上的 `git status`」兩條是 `manual`，證據貼在 `08-…md` §3。
- **`SCOPE-014` 本期不動。** 它的四條 `guards_scope` 要到 V2.2–V2.4 才接得上
  （`plan/16/01` §3.1b 的表），本期沒有任何一條可以翻成 active。
- 改完 `requirements.json` 要跑 `scripts/trace render --write`，否則
  `make check` 會在 `render --check` 那一步紅而且不會告訴你原因。

## 8. `TK-01` 不做的事

- **不改 `docs/permission-matrix.md`**（產生檔，由 `TK-04` 用
  `scripts/p4/render_permission_matrix.py --write` 重新產生）。
- **不改 `docs/error-catalog.md`**（產生檔，由 `TK-04` 用
  `scripts/p4/render_error_catalog.py` 產生）。
- **不寫安全審查文件**——但本期**會**有一份（`04-…md` §6），由 `TK-06` 起草。
  V2.0 寫的是「為什麼不觸發」，本期要寫的是「觸發了，審了什麼」。
- **不改 `research/tech.md` 與 `research/style.md`。** 右欄 tab 化是 V2.2／V2.4 的事，
  本期的 Session Workspace 版面**一個像素都不動**（`07-…md` §5.3）。
