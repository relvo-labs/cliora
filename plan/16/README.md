# Cliora V2.0 — 專案基座

> **狀態：實作與客觀驗證已完成。** 九條出口條件有可重跑的單元、DB、整合與
> live-stack 瀏覽器證據；CI 也在 `CLIORA_PROJECTS_ENABLED=true/false` 各跑完整套組。
> 進度、證據與已知邊界見 [`07-implementation-status.md`](./07-implementation-status.md)。
> **`PJ-08` 的人工合併提案尚未提出**——計畫明文禁止 CI 或 agent 代為發起。

本目錄是 [`research/02/`](../../research/02/README.md) 規劃的**第一個階段**的執行計畫，
ticket 統一使用 `PJ-` 前綴（**P**ro**J**ect）。

規劃層（`research/02/`）回答「V2 要做什麼、為什麼」；本目錄回答「在**這個 repo 的現況**上
怎麼做得出來、做完怎麼證明」。兩者不重複：需求與決策一律回指 `research/02/`、
`research/prd.md`、`docs/adr/`（`.agent/skills/AUTHORING.md`「Never duplicate canonical research」）。

## 這一期真正的形狀

> 讓「專案」成為平台上真實存在的東西：可以建立、可以綁定散落在不同 Node 上的 Workspace、
> 可以從它進到 Session，並且看得到這個專案上發生過什麼。

它是整個 V2 裡**唯一一個不碰任何既有風險面**的階段：

```text
            V2.0（本期）              V2.1 起
  daemon    一行都不動                投影 .cliora/、runner 模式
  contract  v1.9.0 不變               v1.10.0 起
  檔案面    一個位元組都不動          仍不動（Agent Run 走另一套目錄）
  terminal  一個位元組都不動          仍不動
  新增的    三張表、一個 nullable 欄、 看板、Agent Runner、機密、交付
            七條 API、兩個畫面
```

**這是刻意的。** V2 的骨架要先在不觸碰 `os.Root`、不觸碰 protocol、不觸碰 tmux 的前提下站起來，
之後每一個真正危險的階段才有一個已知良好的基準可以回歸。

## 這一期最容易做錯的七件事

每一條都對應本目錄的一個決策，而且**每一條都是從這個 repo 的既有程式碼裡讀出來的**，
不是從規劃文件抄的。

1. **用 `include_router` 的條件掛載去實作旗標。**
   `backend/tests/test_authz.py:test_every_mounted_route_is_in_the_matrix` 讀的是
   `app.routes` 這個**匯入期就固定**的清單。條件掛載會讓 `make check` 的結果取決於跑測試時的
   環境變數——綠或紅由 `.env` 決定，那不是一個 gate。旗籤必須擋在 handler，回 404（`00-…md` D1）。

2. **讓 Activity Timeline 洩漏 actor。**
   Dashboard 的近期活動**已經**因為這件事做過一次裁決：沒有 `audit.view` 的人看得到
   「發生了什麼」但看不到「誰做的」（`services/dashboard.py:project_for`）。
   Project 的時間軸給的是 `project.view`——**三個角色都持有**。照抄一個帶 `actor_name` 的
   時間軸，等於把 P4 特意關上的那道門在 V2.0 重新打開（`00-…md` D5）。

3. **先合 RBAC 詞彙，之後再接強制點。**
   `test_every_action_is_enforced_somewhere` 是**文字掃描**：`PROJECT_VIEW` 一旦寫進 `rbac.py`
   而 `backend/app/` 其他地方沒有出現，測試立刻紅。所以 `PJ-03` 與 `PJ-04` 是**同一個 PR**，
   不是兩個（`00-…md` D7）。D13 明寫「不要為了先 merge 而往 `UNENFORCED_ACTIONS` 裡加東西」。

4. **以為 Node 被刪除時綁定列會自己消失。**
   Node 的移除是 **soft delete**（ADR 0011，`nodes.deleted_at`），`ON DELETE CASCADE` 根本不會觸發。
   `workspace_favorites` 的 migration 註解已經寫過這個教訓，並且說明它的做法是「服務層過濾」。
   出口條件第 4 條要照這個事實重寫（`00-…md` D4、`06-…md` §5）。

5. **沒有先擷取基線就開始改。**
   出口條件裡有三條是「與升級前 diff」：OpenAPI schema、`pg_dump --schema-only`、導覽截圖。
   改完之後**沒有任何辦法**補一份升級前的快照。所以 `PJ-00` 是閘門，而且它是本目錄唯一一張
   「必須在動任何一行程式碼之前完成」的票（`00-…md` §4、`08-…md` §1）。

6. **把綁定表當成授權。**
   `WorkspaceFavorite` 的 docstring 已經把這句寫死了：「A shortcut, never an authorization.」
   `project_workspaces` 是同一種東西的第二個實例。綁定時跑 `authorize_workspace()`，
   **每一次使用再跑一次**，因為 root 會被停用（紅線 2、`00-…md` D3）。

7. **為了容納分組把 sidebar 加寬回 280px。**
   `plan/09` 把它從 280 收到 208，理由是把空間讓給中央區；`research/style.md` §12／§18 與
   `plan/08` 是同一個方向。加寬會一次推翻三份決定。
   **已量掉這個風險**（2026-08-08，`scripts/pj/measure-sidebar.mjs`）：
   採用的無縮排分隔線版本最寬 147px、餘裕 61px，**一分餘裕都沒花到**（`08-…md` §1）。

## 與 `research/02/` 的差異

本計畫在十處偏離規劃，每一處都是因為讀了程式碼之後發現規劃的假設與現況不符。
**這些是修正，不是裁量**——沒有一條需要新的裁決。

| # | `research/02/` | 本計畫 | 依據 |
|---|---|---|---|
| 1 | `PJ-03`（RBAC）與 `PJ-04`（API）是兩張票 | **同一個 PR** | `test_every_action_is_enforced_somewhere` 的文字掃描（`00-…md` D7） |
| 2 | 「導覽現況五個平項」「Integrations 從頁內入口升格為導覽項」 | **現況已經是六項，Integrations 早已是導覽項**（`AppLayout.vue`，`plan/11`） | 讀 `AppLayout.vue`。M8 的量測基數與旗標關閉的截圖比對都要照這個事實改（`05-…md` §1） |
| 3 | 出口條件 4：「Node 被刪除時綁定列一起消失」 | **改寫為「列表中消失、DB 列仍在」** | Node 是 soft delete（ADR 0011） |
| 4 | 未指明前端如何得知旗標 | `UserResponse` 新增 `features: list[str]` | `/api/auth/me` 目前只回 `permissions`，沒有任何伺服器旗標的管道（`04-…md` §3） |
| 5 | `GET /api/projects/{id}` 與 `GET /api/projects/{id}/overview` 兩條 | **合併為一條** | 同一個畫面、同一組權限、沒有獨立的快取語意（`03-…md` §2.1） |
| 6 | `projects` 有 `default_node_id`、`default_runtime` | **不建這兩欄** | 本期沒有任何程式碼會讀它們；預填來自 `is_primary` 綁定。需要時是一次 `ALTER`（`02-…md` §2.1） |
| 7 | Activity Timeline 未提 actor 的可見性 | **依 `audit.view` 遮蔽 actor** | `services/dashboard.py:project_for` 的既有裁決（`00-…md` D5） |
| 8 | 需求在 `PJ-01` 一次註冊完成 | **分兩段：`PJ-01` 註冊為 `proposed`，`PJ-08` 翻成 `active`** | `validate` 要求 link target 存在於磁碟，`coverage --scope all --strict` 要求 active criterion 的 link 齊備——兩條規則讓「先註冊後實作」在工具鏈上不成立（`01-…md` §6.1） |
| 9 | 紅線 4 的四條約束只寫在 ADR 0027 裡 | **另註冊 `SCOPE-014`，四條約束各一條 AC，由 V2.2–V2.4 各自接上 `guards_scope` gate** | 撤銷是現在發生的，四條約束的第一行程式碼要到 V2.3。中間隔三個階段，一段寫在 ADR 裡的文字守不住它——而 repo 已有 `kind: scope` ＋ `guards_scope` 的現成機器（`01-…md` §3.1b） |
| 10 | V2.0 用 `Lei-k/Traqora` 當驗收素材（D30） | **V2.0 不用，改用 `run-stack.sh` 的合成 workspace；D30 的第一次真正使用是 V2.1** | V2.0 一行程式碼都不讀，連 `.cliora/` 都不寫。Traqora 的價值（`base_branch: main`、分支慣例、真實待辦）從 V2.1 才開始兌現（`00-…md` D13，已回寫 `research/02/01` D30） |

另有一處是**補充**而非偏離：新增 `PJ-00`（基線擷取與 M8 量測）作為閘門票，
因為出口條件裡的三條 diff 在改完之後就再也無法取得基準。

## 檔案

| 檔案 | 內容 |
|---|---|
| `00-execution-plan.md` | 成功定義（八項判準）、範圍、固定基線決策 D0–D12、波次與 ticket、風險 |
| `01-decisions-and-governance.md` | `PJ-01`：ADR 0027、PRD 增訂、skill 範圍句修訂、traceability 註冊、**為什麼這是第一張票** |
| `02-data-layer.md` | `PJ-02`：migration `0021`、三張新表與一個既有表 ALTER 的逐欄設計、索引、上下行演練 |
| `03-rbac-and-project-api.md` | `PJ-03`／`PJ-04`：RBAC 詞彙與 seed `0022`、七條 API、錯誤碼、稽核、**兩票同 PR 的理由** |
| `04-session-association-and-feature-flag.md` | `PJ-05`：Session 的 optional `project_id`、旗標的三個強制點、`features` 欄位 |
| `05-frontend-navigation-and-projects.md` | `PJ-06`：導覽重整、sidebar 驗算、`/projects` 與 `/projects/:id`、旗標關閉的還原 |
| `06-verification-and-exit.md` | `PJ-07`／`PJ-08`：測試清單、旗標關閉回歸套組、證據、exit 條件、**為什麼本期不觸發安全審查** |
| `07-implementation-status.md` | 實作進度、實測證據與人工移交點 |
| `08-open-measurements.md` | M8（已量）與本期新增的四個量測項；以及「沒有要量什麼、為什麼」 |

實作產出的工具在 `scripts/pj/`：`measure-sidebar.mjs`（M8）、`schema_snapshot.py`、
`openapi_diff.py`、`nav-shot.mjs`、`smoke-projects.mjs`、`seed_users.py`、
`measure-project-detail.py`、`measure-nav-height.mjs`、四個 gate、`evidence.sh` 與
`browser-evidence.sh`。

## 執行慣例

沿用 `research/02/README.md` 的建議，本階段開一個背景 tmux 承載長時間工作：

```bash
tmux new-session -d -s cliora-v20 -c /home/ubuntu/workspace/cliora
tmux send-keys -t cliora-v20 'make check' C-m
tmux attach -t cliora-v20        # 需要看的時候才 attach
```

## 合併回 `dev`

**一律由人工確認。** 出口條件全綠只是取得提案資格，不是核准；
自動化（含 CI 與 agent）不得發起或完成這個合併（`research/02/10-verification-and-exit.md` §7）。
</content>
</invoke>
