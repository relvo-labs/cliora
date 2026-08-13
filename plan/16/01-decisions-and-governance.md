# 01 — 決策、ADR 與治理（`PJ-00`、`PJ-01`）

## 1. 為什麼需求變更是第一張票

`.agent/skills/cliora-project-context/SKILL.md` 第 20 行：

> Do not introduce Central SSH, arbitrary shell commands, PostgreSQL terminal logs, a Web IDE,
> **Git automation, task routing, or multi-agent orchestration** without a requirements change.

V2 三者都碰：task routing 從 V2.1 起（任務認領）、Git automation 在 V2.3、
而「同一個 Agent 走完整個流程」需要明確講清楚它**不是**多 Agent 編排。

所以 `PJ-01` 不是文書工作，它是**取得動手資格的那一步**。沒有它：

- 後面每一張票都在違反這個 repo 自己寫下的規則；
- `make check` 內的 `traceability-validate` 會擋下沒有註冊的需求；
- 而且最實際的一點——**六個月後沒有人記得為什麼紅線 4 不見了**。

## 2. `PJ-00` — 基線擷取與 M8 量測（閘門）

**這張票不改任何程式碼，它只是把「升級前長什麼樣」存下來。**

出口條件裡有三條是「與升級前 diff」，而升級前的快照**改完就再也取不到**。
先做這一步的成本是二十分鐘，不做的成本是三條出口條件永遠無法驗證。

產出物一律放在 **`artifacts/pj/local/baseline/`**，需要保留的摘要抄進 `07-…md`。

> 路徑要精確：`.gitignore` 第 18 行忽略的是 **`artifacts/*/local/`**，不是 `artifacts/`。
> 放在 `artifacts/pj/baseline/` 會被 git 追蹤到——那裡面有一份幾千行的 `openapi.json`
> 和三張截圖。

| # | 擷取什麼 | 怎麼做 | 用在哪 |
|---|---|---|---|
| B1 | OpenAPI schema | 起 Central，`curl -s localhost:8000/openapi.json \| jq -S . > baseline/openapi.json` | `06-…md` §3 的 API 表面 diff |
| B2 | DB schema | `pg_dump --schema-only --no-owner $DB > baseline/schema.sql` | 出口條件：既有表逐欄無變化 |
| B3 | 導覽截圖 | Admin／Developer／Viewer **各一張**（見下） | 旗標關閉時的外觀比對 |
| B4 | RBAC 矩陣 | `docs/permission-matrix.md` 現況複本 | 只新增兩列的證據 |
| B5 | 路由清單 | `python -c` 印 `sorted(mounted_routes())` | 只新增七條的證據 |

**B3 要三張不是一張。** 導覽項是權限條件的（`AppLayout.vue`）：

| 角色 | 現況看得到的導覽項 | 數量 |
|---|---|---|
| Admin | Dashboard、Nodes、Sessions、Enrollment、Audit、Integrations | **6** |
| Developer | Dashboard、Nodes、Sessions | **3** |
| Viewer | Dashboard、Nodes、Sessions | **3** |

> `research/02/09-frontend-information-architecture.md` §2 寫「現況五個平項」並把
> `Integrations` 列為「從頁內入口升格為導覽項」。**這兩句都與程式碼不符**：現況是六項，
> 而 `Integrations` 早在 `plan/11` 就已經是導覽項（`AppLayout.vue` 的
> `canManageIntegrations`）。旗標關閉時的比對基準與 M8 的量測基數都照上表，不照規劃文件。

### M8 — sidebar 208px 在分組後夠不夠

`plan/09` 的原始論證是「最長項需 ≈144px，208px 留 64px 餘裕」。V2.0 要花掉的是：
**一個新導覽項（`Projects`）＋ 兩層階層（分組標題 ＋ 子項縮排）**。

量法（在瀏覽器 devtools 裡量，不是估）：

1. 目前最長項 `Integrations` 的實際渲染寬度（icon ＋ gap ＋ 文字 ＋ padding）。
2. 加 12px 縮排之後的寬度。
3. 分組標題 `Infrastructure` 在**無縮排**時的寬度。
4. 三者取最大值 ＋ `aside` 的 `padding: 16px 12px` 左右各 12px。

> `plan/09/03` 的 144px 是拿 **`Enrollment`** 算的，而 `Integrations` 比它長——
> 那個項目是 `plan/11` 之後才加的。所以 144px 這個數字**今天就已經過期了**，
> 不能拿它當基準往上加，要重新量一次。

**判準**：最大值 ＋ 24px ≤ 208px 就過。不過的處置順序見 `00-…md` §5，
**加寬是最後一項且需要先翻案 `plan/09`**。

結果填進 `08-…md` §1。這一項**擋 `PJ-06`，不擋其他票**——後端可以先做。

## 3. `PJ-01` — ADR 0027

檔名：`docs/adr/0027-v2-project-layer-and-source-of-truth.md`。

沿用既有 ADR 格式（Status／Date／Amends／Related／Requirements／Contract／Ships in／Plan
＋ **Alternatives rejected 表**）。這個 repo 的 ADR 之所以有用，多半是因為那張表
把「以後有人會再提一次的東西」先寫掉了。

### 3.1 必須寫進去的六件事

| # | 內容 | 來源 |
|---|---|---|
| 1 | **D2：Monstrare 功能內化**，含「誰在讀它」的邊界表（哪些能內化、哪些是硬邊界） | `research/02/01` D2 |
| 2 | **D1：平台 DB 是任務資料的真實來源**，以及它換來與付出的東西 | `research/02/01` D1 |
| 3 | **D12：相容機制**——兩個獨立旗標、永久 nullable 的關聯欄位、每階段的旗標關閉回歸 | `research/02/01` D12 |
| 4 | **D13：RBAC 新動作與角色歸屬**，含「為什麼 `task.approve` 獨立於 `task.update`」 | `research/02/01` D13 |
| 5 | **紅線 4 的撤銷與換上的四條約束**（分支命名空間、永不推共用分支、永不自動合併、派工是拉取式） | `research/02/00` §7 |
| 6 | **`.cliora/` 投影的規則**，含流程檔以版本號目錄避開 `O_EXCL` 的做法 | `research/02/01` D2 |

第 5 與第 6 項在 V2.0 **還不會有任何程式碼**。仍然要寫，因為 ADR 記的是決定不是實作，
而這兩項正是「為什麼可以開始做 V2」的依據。

第 4 項（D13）要照 2026-08-08 的**例外 3** 寫理由，不要照原文：
`task.approve` 與 `task.update` 的持有者集合**刻意相同**，拆開是為了讓
「Agent 憑證拿不到核准權」成為一個可以寫死在 token scope 裡的東西——
一個不存在的動作沒辦法從 scope 裡排除。**不是**為了角色分離。
（不寫這句，日後的「反正持有者一樣，合併吧」會靜默打開 Agent 自我核准的路。）

### 3.1b 紅線 4 的四條約束要註冊成 `SCOPE-` 需求，不能只寫在 ADR 裡

**這是 `PJ-01` 除了 ADR 之外最重要的一件事**，理由是時間差：

```text
  現在（V2.0）          V2.1        V2.2        V2.3
  紅線 4 撤銷 ────────────────────────────────→ 四條約束的第一行程式碼
       │                                              │
       └──────────── 三個階段 ─────────────────────────┘
```

一段寫在 ADR 裡的約束，三個階段之後只是一段文字。但這個 repo 已經有現成的機器可以守它：
`traceability/schema/requirements.schema.json` 的 ID pattern 收 **`SCOPE-[0-9]{3}`**，
而 `validate.py:441` 對 `kind: "scope"` 要求的 primary link 是 **`guards_scope`**——
也就是一個真的 gate。

| 欄位 | 值 |
|---|---|
| ID | **`SCOPE-014`**（現有 `SCOPE-001`–`SCOPE-013`，已核對） |
| `kind` | `scope` |
| `title` | Agent 自主執行的出口約束（紅線 4 撤銷後換上的四條） |
| `lifecycle` | `proposed`（`PJ-01`）→ `active`（V2.4 收尾時） |
| AC | 四條各一：分支命名空間強制、永不推共用分支、永不自動合併、派工是拉取式 |

`guards_scope` link 的接法（各自的階段負責）：

| AC | 接到哪個 gate | 階段 |
|---|---|---|
| 分支命名空間 `cliora/<card_ref>-<run_seq>` | daemon 的 git argv 組裝測試 | V2.3 |
| 永不推共用分支 | daemon 內的四種推送拒絕測試 | V2.3 |
| **永不自動合併** | **對 daemon git 子命令 allowlist 的斷言**（`10` §2.6 第 5 條：「自動合併的程式碼路徑不存在」） | V2.4 |
| 派工是拉取式 | Central 沒有任何推送端點的路由矩陣斷言 | V2.2 |

翻成 `active` 的那一刻，`make traceability` 就會替你守著它。
**這讓「撤銷一條護欄就要換上一條」從一句承諾變成一個會失敗的測試。**

同時註冊 `SCOPE-` 的另一個好處：`00` §9 的「明確不做」清單
（自動合併、自動部署、多 Agent 協作、自動指派…）也有地方掛。

### 3.2 本期額外要寫進 ADR 0027 的三件事（`research/02` 未涵蓋）

這三件是讀了程式碼之後才發現需要決定的，不寫下來的話下一個階段會重新爭論一次：

**一、`activity_events` 與 `audit_logs` 的分工**（`00-…md` D6）。
把那張兩欄表原樣抄進 ADR，並且明寫判準是 ADR 0024 W2 的問題：**誰清這個、什麼時候清。**
`activity_events` 的答案是「跟著 Project 走，沒有保留期」——這與 `run_logs`（V2.2，有保留期）
是**不同**的答案，而混淆這兩者是後面階段最容易犯的錯（`research/02/08` §2 特別點名過）。

**二、Project 時間軸的 actor 依 `audit.view` 遮蔽**（`00-…md` D5）。
這是既有裁決的適用而不是新裁決，但**必須寫下來**：`project.view` 三個角色都持有，
而 `services/dashboard.py:project_for` 的那段 docstring 是唯一記錄這個規則的地方。
V2.1 之後還會有第三個、第四個「近期活動」形狀的東西，那時要有一句可以指的話。

**三、`features` 不是 `permissions`**（`00-…md` D2）。
一個回答「這個部署有沒有這個功能」，一個回答「這個人可不可以」。
兩者在 UI 上是 AND，伺服器兩個都會再檢查一次。

### 3.3 Alternatives rejected（至少這五列）

| 方案 | 為什麼否決 |
|---|---|
| 複製 Monstrare 的檔案（`ai/`、`tools/kanban/`、`.claude/skills/`）進使用者的 repo | 污染使用者 repo；與既有 `CLAUDE.md` 衝突時要覆寫，那會踩到 ADR 0024／0026 的寫入姿態；而且平台有 API 可以**真的拒絕**，不需要靠 prompt 說服（`research/02/01` D2） |
| 平台寫入 node 的 `~/.claude/` | 寫到 allowed root 之外，且是 node 層全域——專案間沒有隔離 |
| 任務資料以 repo 檔案為真實來源、DB 為投影 | 內化之後使用者 repo 裡不再有卡片檔案，沒有東西可以當 writer of record；而且拖曳會變成一次檔案覆寫（`filesystem.replace` ＋ `expected_sha256` ＋ 路徑白名單），那正是紅線 3 不肯開的那道縫 |
| 條件掛載 router 來實作旗標 | `test_every_mounted_route_is_in_the_matrix` 讀的是匯入期固定的 `app.routes`，條件掛載讓 `make check` 的結果取決於環境變數（`00-…md` D1） |
| V2.0 就做 `project_members` | 它是一張新表加一層資源授權，**不會回頭改動本期任何欄位或端點**，所以現在做只是提早付款。代價（多團隊共用時互相看得到專案名稱與時間軸）要寫在 ADR 的 Consequences |

### 3.4 Related

`0014`（路徑安全，紅線 2 的適用範圍要點名）、`0016`（RBAC 兩層授權）、
`0022`（tunnel 憑證與 `CLIORA_SECRET_ENCRYPTION_KEY`，V2.3 的機密主金鑰**與它獨立**）、
`0024`／`0026`（寫入姿態，紅線 3 完全不被觸碰）。

## 4. `PJ-01` — `research/prd.md` 的 Project 章節

新增 **§8.11 專案管理**（現況最後一節是 §8.10 埠轉發預覽，第 1442 行；§9 是通訊協定）。

沿用既有格式：`<a id="fr-project-00X"></a>` ＋ `## FR-PROJECT-00X 標題`，
每一條 AC 一個 `<a id="fr-project-00X-ac-NN"></a>` 錨點（照 `FR-WORKSPACE-005` 的樣子）。

| ID | 標題 | Owner | 關鍵 AC |
|---|---|---|---|
| FR-PROJECT-001 | Project CRUD 與狀態 | central | 建立／改名／狀態轉換；`slug` 專案間唯一；**封存後不得建立新 Session、不得新增綁定**；沒有刪除 |
| FR-PROJECT-002 | Project ↔ Workspace 綁定 | central | 跨 Node 綁定；綁定時前綴驗證；**每次使用重驗證**；解綁不影響進行中的 Session；node soft-delete 後該列不出現在回應中 |
| FR-PROJECT-003 | Project ↔ Session 關聯 | central | `project_id` 可為空且**永遠可為空**；指定時 workspace 必須屬於該 Project 的綁定，不符回 400；平台不從 workspace 反查 Project |
| FR-PROJECT-004 | Activity Timeline | central | Session 起訖、綁定變更、Project 狀態變更各產生事件；分頁查詢；**無 `audit.view` 時 actor 為 null 且回應標示 `actors_hidden`** |
| FR-PROJECT-005 | 功能旗標與相容性 | central | `CLIORA_PROJECTS_ENABLED=false` 時 `/api/projects*` 全數 404、`features` 為空陣列、前端導覽與升級前一致 |

**明文宣告一句**（放在 §8.9 的引言，而不是附註）：

> Ad-hoc Session（不屬於任何 Project 的 Session）仍受完整支援，且不會被平台自動歸屬到任何 Project。

這句話是 D10 在 PRD 上的落點。沒有它，六個月後會有人把「自動歸屬」當成缺漏來補。

## 5. `PJ-01` — skill 範圍句修訂

檔案：`.agent/skills/cliora-project-context/SKILL.md`。

**只改第 20 行那一句，其餘不動。** 修訂要精確——把一整句刪掉會失去它本來擋的東西：

| 原文 | 改成 | 為什麼 |
|---|---|---|
| `task routing` | `automatic task assignment`（並補一句：平台管理任務**紀錄**與**認領**，不做自動指派、排程最佳化或負載平衡） | 被撤銷的是「任務可以被 Agent 領走」，**不是**「平台會替你決定誰做什麼」（`research/02/00` §7 紅線 4 第 4 條） |
| `Git automation` | 保留原文，另加一句：V2.3 起在 `cliora/<card_ref>-<run_seq>` 命名空間內受限開放，五條硬約束寫死在 daemon | V2.0 還沒有任何 git 程式碼。**現在就寫**是為了讓 V2.3 開工時這句已經在了，而不是那時再改一次 |
| `multi-agent orchestration` | 保留原文，另加一句：同一個 Agent 走完整個流程**不是**多 Agent 編排；跨 Agent 協作與 Agent 互相派工仍不做 | 這是最容易被誤讀成「已經放寬」的一條 |

另外新增一段（沿用既有段落的密度，三到四句）：

> V2 專案層（ADR 0027，accepted）：Project 是平台資料，不是使用者 repo 裡的檔案。
> 綁定一條 workspace 路徑是捷徑不是授權——`sessions.authorize_workspace()` 在綁定時跑一次，
> 在**每一次**使用時再跑一次。Project 的時間軸對沒有 `audit.view` 的人隱藏 actor，
> 與 Dashboard 的近期活動同一條規則。

## 6. `PJ-01` — traceability 註冊

### 6.1 一個必須先講清楚的順序問題

工具鏈有兩條會互相打架的規則，而規劃文件沒有提到它們：

| 規則 | 在哪 | 後果 |
|---|---|---|
| `validate --level static` 斷言 **link 的 target 必須存在於磁碟上** | `scripts/traceability/validate.py:308` | `PJ-01` 不能先建指向「計畫中的檔案路徑」的 `implemented_by` link——那些檔案還不存在 |
| `coverage --scope all --strict` 對**每一條 active 的 criterion** 要求它的必要 link 齊備 | `Makefile:78`，`make traceability` | `PJ-01` 一註冊五筆 active 需求，`make traceability` 立刻紅 |

**所以註冊分兩段做**，中間用 `lifecycle` 這個既有機制隔開
（`coverage()` 明確跳過 `lifecycle != "active"` 的需求，`validate.py:458`）：

| 時機 | 做什麼 |
|---|---|
| `PJ-01` | 五筆 `FR-PROJECT-*` ＋ 一筆 `SCOPE-014` 以 **`lifecycle: "proposed"`** 註冊。link 只建指向 `research/prd.md`（該檔存在）的來源關聯 |
| `PJ-02`–`PJ-06` | 每張票落地時，把它涵蓋的 AC 的 link 補上（此時檔案已存在，static validate 過得了） |
| `PJ-08` | **五筆 `FR-PROJECT-*`** 翻成 `lifecycle: "active"`，`make traceability` 必須全綠 |
| V2.4 收尾 | **`SCOPE-014`** 翻成 `active`（它的四條 `guards_scope` 到那時才全部接上，§3.1b） |

**每一條 AC 要四類 primary link，不是兩類**（`validate.py:434`，`kind == "functional"`）：

| link type | 指向 |
|---|---|
| `planned_by` | 本目錄的對應檔案（`plan/16/0X-….md`） |
| `specified_by` | `research/prd.md` 的 AC 錨點 |
| `implemented_by` | 落地的程式碼路徑 |
| `verified_by` | 對應的測試檔 |

`plan/09` 的出口條件已經踩過這一條（「本期新增的 criterion 已備齊
planned_by／specified_by／implemented_by／verified_by 四類 primary link」），
所以這不是新規則，是一條有前例的規則。

**這不是取巧。** `proposed` 就在 schema 的 enum 裡
（`requirements.schema.json:47`），而它的語意正好是這件事：需求已經被寫下來、
已經被核准，但還沒有實作可以連過去。

### 6.2 欄位

`traceability/requirements.json`（現有 115 筆，`schema_version` 沿用）：

- 五筆 `FR-PROJECT-001`–`005`。ID 樣式 `^FR-[A-Z]+-[0-9]{3}$` 通過。
- **一筆 `SCOPE-014`**（紅線 4 的四條約束，§3.1b）。`kind: "scope"`，
  它的必要 link 只有 `guards_scope` 一種（`validate.py:441`），
  由 V2.2／V2.3／V2.4 各自的 ticket 接上——所以它會比五筆 `FR-PROJECT-*` 晚很多
  才翻成 `active`，這是對的，**不要**為了讓表格好看而提早翻。
- `owner` 依 §4 的表（本期全部 `central`，除了 `FR-PROJECT-005` 的前端 AC 用 `frontend`）。
- `applicability` 用 **`["v2"]`**。schema 對這一欄的 items 只要求
  `{"type": "string", "minLength": 1}`（`requirements.schema.json:123`），**不需要擴 enum**。
  既有值只有 `mvp`（102 筆）與 `all`（13 筆）；用 `v2` 的效果是
  `coverage --scope mvp` 會跳過它們，而 `--scope all`（release blocking 的那個）不會。
  **不要借用 `mvp`**——那會讓 MVP 的覆蓋率報告從此含有 V2 的東西。
- `criteria` 的 `verification_profile` 全部 `automated`，除了「導覽截圖比對」
  那一條是 `manual`（manual 的要在 `06-…md` §3 有可貼上的證據）。

### 6.3 產生檔

`make check` 裡的 `traceability-validate` 包含 **`scripts/trace render --check`**。
改了 `requirements.json` 就要跑一次：

```bash
scripts/trace render --write     # 或 make traceability-render
```

否則 `make check` 會在 `render --check` 這一步紅，而錯誤訊息不會告訴你原因是「忘了 render」。

**驗收**：`PJ-01` 之後 `make check` 全綠；`make traceability` 全綠
（五筆是 `proposed`，coverage 跳過它們）。`PJ-08` 之後兩者在 `active` 下仍全綠。

## 7. `PJ-01` 不做的事

- **不改 `docs/permission-matrix.md`。** 它是產生檔（檔頭寫著 do not edit），
  由 `PJ-03` 用 `scripts/p4/render_permission_matrix.py --write` 重新產生。
- **不改 `docs/error-catalog.md`。** 同理，由 `PJ-04` 用 `scripts/p4/render_error_catalog.py` 產生。
- **不寫安全審查文件。** 本期不觸發任何一條觸發條件，理由寫在 `06-…md` §6——
  **但那個「為什麼不觸發」本身要寫下來**，不能是沉默。
- **不改 `research/tech.md` 與 `research/style.md`。** 它們要改的是右欄 tab（V2.2／V2.4），
  本期沒有版面變更。
</content>
