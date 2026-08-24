# 13 — 從 `../kintra` 移植什麼、不移植什麼

> **上游 [`research/03/01`](../../research/03/01-architecture-decisions.md) §1.9 列了七項處置。
> 本份是它落到 `beta.1` 的逐項交代，並補上**實際讀過 kintra 之後才看得到的六件事**。**

寫這份的理由：上游 §1.9 是在核對 kintra 之後寫的，但它服務的是**整個 `research/03`**
（含 `alpha.3` 的 `search_documents` 模式）。`beta.1` 用得到的是其中五項，
而其中三項上游只寫了一句話——那一句話不足以實作。

---

## 0. 一句話結論

kintra 的看板已經解過 `beta.1` 要解的五個問題（rank、saved view、
move dialog、卡片欄位可見度、拖曳只寫一列），**每一個都附帶一個踩過坑的細節**。
但 kintra 也做了兩個 Cliora **明確不採納**的選擇（`@tanstack/vue-query`、
扁平 criteria），而那兩個在上游 §1.9 裡沒有出現——
因為 §1.9 只列了「要移植什麼」，沒有列「kintra 做了但我們不做的」。

**不列出後者，「參考 kintra」會被讀成對 kintra 全盤的背書。**

---

## 1. 上游七項的逐項處置

| # | kintra 的東西 | 上游處置 | 本期落點 | 狀態 |
|---:|---|---|---|---|
| 1 | `backend/app/modules/board/ranking.py` | 逐字移植純函式 ＋ 測試 | `PX-61` → `services/work/ranking.py` | ✅ 已核對，見 §2 |
| 2 | `board_views` 的 schema 形狀 | 移植欄位設計 | `PX-22` → `work_views` | ✅ 已核對，**發現兩處上游沒寫的**，見 §3 |
| 3 | `search_documents` 的冪等寫入 | 移植模式 | **不在本期**——`alpha.3` 的 `KN-03` 已經用了 | — |
| 4 | `TicketDetailDrawer.vue`（1394 行） | 只移植互動規格與測試案例 | `PX-38` | ✅ 已核對，見 §5 |
| 5 | `BoardCardVisibilityPopover.vue` | 移植「卡片欄位是看板層設定」這個決定 | `PX-32` | ✅ 已核對，**補一個上游沒寫的**，見 §6 |
| 6 | Naive UI 元件 | 不移植（`plan/19` D35） | — | ✅ 遵守 |
| 7 | 自動化規則、custom field、worklog | 不移植（提案 §3.2 非目標） | — | ✅ 遵守。kintra 的 `board/` 有 `automation_actions.py`／`automation_triggers.py`／`custom_field_query.py`／`worklog_service.py`，**本期一行都不看** |

---

## 2. `ranking.py`（`PX-61`）

**逐字移植**：`ALPHABET`／`BASE`／`FIRST`／`LAST`／`MID`／`INITIAL_RANK`／
`REBALANCE_THRESHOLD`／`INLINE_REBALANCE_THRESHOLD`／`_INDEX`／
`validate_rank`／`rank_after`／`rank_before`／`_midpoint`／`rank_between`／
`_to_base36`／`rebalanced_ranks`。

**翻譯 docstring**（[D99](./01-decisions-and-governance.md)），保留三個不變式的編號與理由。

**測試逐字移植**：`../kintra/backend/tests/unit/test_ranking.py` ＋
`../kintra/backend/tests/integration/test_rank_rebalance.py`。

### 讀完之後才看得到的兩件事

**① 再平衡的門檻是「產出的 rank 字串長度」，不是「相鄰 rank 的共同前綴長度」。**

```python
# ../kintra/.../ticket_service.py:544
if len(new_rank) > ranking.INLINE_REBALANCE_THRESHOLD:
    # 同步保險閥（P2-D25）：背景工作來不及時當場平衡該桶
    await self.rebalance_bucket(...)
```

上游 [`05`](../../research/03/05-phase-p2-board-and-backlog.md) §5 只寫
「再平衡 背景 24、同步保險閥 48」，沒說 24 和 48 量的是什麼。
**本計畫的第一版寫成「共同前綴長度」，那是錯的**，已在
[`05`](./05-work-items-and-view-api.md) §6 更正。

**② 鄰居的 rank 是一次查詢取兩個，不是兩次 `get()`。**

`_neighbour_ranks()` 的 docstring 只有一句：「讀取兩個鄰居的 rank——**一次查詢**」。
本計畫的第一版偽碼是兩次 `repo.get()`，已更正。

### 不移植的部分

kintra 的 rank scope 是**每個 column 一個桶**（`rebalance_bucket(org, project, status_id)`）。
Cliora 的 scope 是 **project**（D50），因為 Backlog 與 Board 是同一批卡的兩個投影。
所以 `rebalance_bucket` 只移植**形狀**，參數換成 `project_id`。

### 移植過來的一個測試技術

> 「`research/01/05` 的第一條階段風險就是『拖曳造成整欄 UPDATE』，**`P2-T4` 以 SQL 計數斷言**。」

`PX-34` 加一支同型的測試：**一次 move 產生的 `UPDATE tasks` 語句數為 1**。
這比「檢查回應正確」強，因為一個「順手把整欄 rank 重算」的實作會回應正確。

---

## 3. `board_views` → `work_views`（`PX-22`）

上游只說「移植欄位設計（`criteria` JSONB ＋ `is_default` ＋ `position` ＋
`(board,user,name)` 唯一鍵）」。實際讀 `p2_01_board_views.py` 之後，
有**兩處上游沒寫而且會影響正確性**：

### ① 唯一索引是**部分**索引：`WHERE deleted_at IS NULL`

```python
op.create_index(
    "uq_board_views_board_user_name", "board_views", ["board_id", "user_id", "name"],
    unique=True, postgresql_where=sa.text("deleted_at IS NULL"),
)
```

kintra 的 view 是**軟刪除**的，所以名稱在刪除後可以重用。

**Cliora 要不要跟？** 見 [D112](./01-decisions-and-governance.md)：
**project scope 的 view 軟刪除，personal scope 硬刪除。**
理由是兩者的稽核義務不同——
[`research/03/08`](../../research/03/08-data-model-and-contract.md) §7 要求
「shared view created／updated／deleted」寫 audit，而一筆指向已消失 id 的
audit 紀錄回答不了「當時刪掉的是哪一個」。personal view 不寫 audit，
所以沒有這個問題，硬刪除比較乾淨。

### ② `criteria` 是 JSONB 的理由，寫在 migration 的 docstring 裡

> 篩選條件是整體讀寫的值物件，沒有任何查詢需要「找出所有用到 priority=urgent 的檢視」。
> 拆子表只會讓一次讀取變成 join，且每加一種篩選維度就要改表結構（`P2-D15`）。

Cliora 的 `filter_json` 同理。這段話值得抄進 `0043` 的 docstring，
因為「為什麼不拆表」是每個讀到 JSONB 欄位的人都會問一次的問題。

### 不移植的部分

`organization_id` ＋ Row Level Security policy（`board_views_tenant`）。
Cliora 是單租戶，沒有 `organizations` 表。
**但這正是 [D93](./01-decisions-and-governance.md) 的對照組**：
kintra 用資料庫層的 RLS 做隔離，Cliora 用應用層的 `ProjectScope` ＋ AST gate。
兩者都可以，但 Cliora 的選擇需要那個 gate 才成立——
而 kintra 的選擇不需要任何 gate。這一句要進 SR-3 的簽核脈絡。

---

## 4. Filter model：kintra 是扁平的，Cliora 是樹狀的

**這是本文件最重要的一節，因為它是唯一一處 kintra 與上游決策不一致的地方。**

kintra 的 `BoardFilterCriteria`：

```python
class BoardFilterCriteria(BaseModel):
    """看板讀取、欄位分頁與 `board_views.criteria` **共用同一個 model**。
    兩處各寫一次必然漂移（P2-D15）。"""
    assignee_ids: list[UUID] = Field(default_factory=list, max_length=20)
    include_unassigned: bool = False
    labels: list[str] = …
    priorities: list[TicketPriority] = …
    types: list[TicketType] = …
    keyword: str | None = …
    overdue_only: bool = False

    def is_empty(self) -> bool: ...
```

**七個具名欄位，沒有 `and`／`or`、沒有巢狀、沒有深度限制、
沒有 `FILTER_TOO_COMPLEX`、沒有 `FILTER_OP_NOT_ALLOWED`。**
一個 Pydantic model 就是整個驗證層。

Cliora 的 [D54](../../research/03/01-architecture-decisions.md) 選了
allowlist 樹（15 欄 × 8 運算子 ＋ 三個 machine code ＋ 深度限制）。

| | kintra 扁平 | Cliora 樹狀 |
|---|---|---|
| 驗證層 | 一個 Pydantic model | 一個 compiler ＋ 三個 machine code ＋ 六個負面測試 |
| 表達力 | 欄位間隱含 AND，欄位內隱含 OR | 任意 and／or 組合 |
| 加一個維度 | 加一個欄位 | 加一列 allowlist |
| 上游要的 `Waiting for Me` view | ✅ 表達得出來 | ✅ |
| 上游 [`04`](../../research/03/04-phase-p1-view-and-read-model.md) §3 的範例（`risk neq low`） | ❌ 表達不出 `neq` | ✅ |

**本計畫維持樹狀**（D54 已裁決），但採納 kintra 的**一個 model 共用**規則
——見 [D113](./01-decisions-and-governance.md)：
**query string 的 `f=`、`work_views.filter_json`、`work-counts` 的 filter
是同一個 Pydantic model，不是三個各自驗證的地方。**
kintra 的 `P2-D15`「兩處各寫一次必然漂移」正是
[`10`](./10-verification-and-exit.md) SR-3 第 1 項「counts 與 items 同 predicate」
的同一件事，只是講在型別層而不是查詢層。

### 一個 kintra 有而上游沒寫的產品規則

```python
def is_empty(self) -> bool:
    """是否完全沒有篩選——決定要不要套用使用者的預設檢視（P2-B15）。"""
```

**沒有 filter 時，套用使用者的預設 view。** 本計畫採納，寫進
[`06`](./06-board-and-backlog.md) §2。

---

## 5. `TicketDetailDrawer.vue`（`PX-38`）

**不移植程式碼**（1394 行、綁 Naive UI 的 drawer、custom field 與 i18n）。
移植三條互動規格：

```text
結構：Header（ID／標題／狀態／操作）＋ Main（說明／子任務／附件／關聯資源／留言）
      ＋ Sidebar（負責人／優先級／日期／標籤／專案／中介資料）
一般 Ticket 詳情**不使用 Modal**
行動版改為全螢幕
```

Cliora 的 Main 順序不同（conversation 前移到第二位，
[`07`](./07-task-drawer.md) §1），但**「Header ＋ Main ＋ Sidebar 三段、
不用 Modal、行動版全螢幕」這三條逐字採納**——
它們已經寫在 [`07`](./07-task-drawer.md) §2 與 `PX-46`。

「不使用 Modal」這一條值得單獨說：一個 modal 會把背後的看板變成不可互動的，
而 Drawer 存在的理由就是**不打斷前後兩步**。這是同一個決定的兩種說法。

---

## 6. `BoardCardVisibilityPopover.vue`（`PX-32`）

上游要移植的決定是：**「卡片欄位可配置」是看板層設定而非個人設定。**
kintra 把 `card_fields` 放在 `boards` 上；Cliora 放在 **view** 上
（`visible_fields_json`），因為 Cliora 的 view 是第一級物件。✅ 已在
[`02`](./02-data-layer.md) §2 落地。

### 讀完之後補一個上游沒寫的

kintra 的 popover 有一個 **`AppSearchInput`**。理由在它的 docstring 下面一行——
欄位清單包含 custom field，會長到掃不完。

**Cliora 的 `WorkItemCardDTO` 是 33 個欄位**（[`03`](./03-read-model-and-attention.md) §4），
同樣掃不完。所以 `PX-32` 的 Display options popover **要有搜尋框**。

另外兩條逐字採納（它們與 `plan/19` 的既有原則一致，等於獨立驗證）：

> 每列是原生 button，可用 Tab、Enter、Space 操作，純圖示同時有文字狀態，**不只靠顏色**。

---

## 7. `TicketMoveDialog.vue`（`PX-34`）

上游 §1.9 **沒有列這一個**，但它是 `PX-34`（鍵盤等價路徑）最直接的參考。

```text
三點選單只揭露「移動」這個意圖；目的欄位與放置位置集中在 Dialog 選擇。
這讓三點選單維持短小，也讓滑鼠與 `m` 鍵共用同一個可存取流程。
```

具體互動（逐條採納）：

| kintra | Cliora `PX-34` |
|---|---|
| 目的欄位 select，**排除目前所在欄** | 目的 group select，排除目前 group |
| 位置 segmented：top / bottom | 同 |
| 開啟時重設為「第一個可選欄 ＋ bottom」 | 同 |
| 沒有可選目的地時 confirm 不可按 | 同 |
| `confirm` emit `{ columnId, toTop }` | **不同**：Cliora emit **neighbor IDs** |

最後一列是唯一的差異，理由是 Cliora 的 Board **有 filter**
（kintra 的 move dialog 只面對完整欄）。`toTop` 在篩選後的欄裡是有歧義的
——「最上面」是篩選後的最上面還是資料的最上面。
所以 Cliora 的 dialog 內部把 top／bottom 換算成
**目前這一欄已載入清單的第一／最後一張的 id**，再送鄰居 ID。

**這一段換算要有測試**：篩選開啟時選「置頂」，送出的 `next_task_id`
是篩選後第一張卡的 id，而不是 `null`。

### `TicketMove` 的 payload 命名

```python
class TicketMove(BaseModel):
    """以**鄰居 ID** 而非 index：index 需要前後端對「目前的清單」有一致認知，
    而清單受篩選影響（篩選後的第 3 個 ≠ 全量的第 3 個）。鄰居 ID 是自明的。"""
    version: int
    column_id: UUID | None = None          # 省略 = 同欄重排
    previous_ticket_id: UUID | None = None
    next_ticket_id: UUID | None = None
```

Cliora 採用同樣的命名（`previous_task_id`／`next_task_id`），
已在 [`05`](./05-work-items-and-view-api.md) §6 更正——
本計畫第一版用的是 `before_`／`after_`，那兩個字在時間與順序之間有歧義。

`column_id` 省略代表同 group 重排，這個「省略即同欄」的約定也採納。

---

## 8. kintra 做了但 Cliora 不做的兩件事

**上游 §1.9 沒有這一節，而它是「參考 kintra」最容易被誤讀的地方。**

### 8.1 `@tanstack/vue-query`

```json
"@tanstack/vue-query": "^5.62.7"
```

kintra 的 `modules/board/queries.ts` 整支建立在 `useQuery`／`useMutation`／
`useQueryClient` 上。

**所以：kintra 的十六個模組不是「自建 query 層可行」的證據。**
[`research/03/09`](../../research/03/09-frontend-architecture.md) §2 引用
「kintra 的 16 個模組證明了這個結構在同等規模下可讀」來支持 `modules/` 佈局——
那句話成立。但**同一個 repo 也在說「這個規模需要一個 query library」**，
而 [D56](../../research/03/01-architecture-decisions.md)／[D100](./01-decisions-and-governance.md)
選擇不加。

**這不是反對 D100，是把它的代價說清楚**（[D114](./01-decisions-and-governance.md)）：
`queryCache.ts` 的 250–350 行要做的，是 kintra 用一個套件解決的事。
[`11`](./11-open-measurements.md) 第 4 項的反悔點因此更具體了——
**衡量的對照組就是 kintra 的 `queries.ts`。**

### 8.2 資料庫層的租戶隔離（RLS）

kintra 每張表有 `organization_id` ＋ `ENABLE ROW LEVEL SECURITY` ＋ 一條 policy。
Cliora 單租戶，沒有這個維度；`ProjectScope` 是應用層的。

**差別在於誰保證**：kintra 的隔離由 PostgreSQL 保證，
漏寫一個 `where` 也不會跨租戶；Cliora 的隔離由
`GATE-PX-ONE-PROJECT-SCOPE` 這個 AST gate 保證，**漏寫一個 `where` 會被 gate 擋下，
但只有在 gate 掃得到的地方**。

這一句要進 SR-3 的簽核脈絡（[`10`](./10-verification-and-exit.md) §6 第 3 項），
因為它說明了為什麼那一項的證據是 gate 而不是測試。

---

## 9. 不看的目錄

```text
../kintra/backend/app/modules/board/automation_actions.py     自動化規則
../kintra/backend/app/modules/board/automation_triggers.py    同上
../kintra/backend/app/modules/board/custom_field_query.py     custom field
../kintra/backend/app/modules/board/service/worklog_service.py  worklog
../kintra/frontend/src/modules/board/components/CustomFieldInput.vue
../kintra/frontend/src/modules/board/components/WorklogPanel.vue
../kintra/frontend/src/modules/board/views/AutomationRuleView.vue
../kintra/frontend/src/modules/board/views/FieldDefinitionView.vue
```

提案 §3.2 的非目標：不做通用 no-code automation、不自訂任意 schema。
**列出來是為了下一個人不必再判斷一次。**
