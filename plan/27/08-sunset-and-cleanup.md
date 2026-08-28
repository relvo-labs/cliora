# 08 — 日落與清理（`HD-07`／`HD-13`）

> 上游：[`research/03/12`](../../research/03/12-migration-and-rollout.md) §6 的 `HD-07`
> 「舊路由 redirect 與 `?tab=` 相容」＋ §4 的 route 相容表。
> 決策：[D126](./01-decisions-and-governance.md#d126)、[D137](./01-decisions-and-governance.md#d137)。

## 1. `HD-07` 已經做完了

上游把它寫成一張要實作的 ticket。**`plan/26` 的 `PX-64` 實作了它**：

```ts
// router/index.ts:106 —— 一處，不是一個相容分支
redirect: (to) => {
  const tab = Array.isArray(to.query.tab) ? to.query.tab[0] : to.query.tab;
  const legacy: Record<string, string> = {
    overview: "project-overview", board: "project-work", roadmap: "project-roadmap",
    requirements: "project-requirements", activity: "project-activity",
    settings: "project-settings",
  };
  const { tab: _dropped, ...query } = to.query;
  return { name: legacy[String(tab)] ?? "project-overview", params: to.params, query };
}
```

`/dashboard` 的別名（`router/index.ts:28`）、
`/projects/:id/tasks/:taskId`、`/requirements/:reqId`、`/runs/:runId` 的保留——
**上游 §4 那張表的六列全部已經成立**。

所以 `HD-07` 的內容改成**拆除**：兩個東西的日落，處置不同。

## 2. `/board` — 整組刪除

**消費者是程式碼，而程式碼可以被 grep 到零。**

```text
api/http/tasks.py:313         @router.get(..., deprecated=True)     刪
repositories/tasks.py         board_cards()                          刪
api/http/schemas.py           BoardCardDTO（16 欄）                   刪
api/client.ts:348             getBoard()  —— 零個呼叫點               刪
scripts/px/gates.sh:86        GATE-PX-BOARD-UNCHANGED                刪
backend/tests/db/test_tasks_api.py::test_the_board_card_stays_a_summary   刪
```

**那個測試的 docstring 要搬走而不是隨檔案消失。** 它記錄了：

> 74 KB／200 張 vs 439 KB／200 張的實測「就是取代分頁的那個決定」

以及 `plan/19` 之後的 **89,251／90,000**。
這兩組數字是三期的設計依據——`research/03/01` §1.5 引用過，
`plan/26` 的 D94 因為它而決定「先量再釘」。

**去哪**：ADR 0044（`/board` 的日落與 `BoardCardDTO` 量測紀錄的歸檔）。
一個 ADR 的用途正是這個：**記下一個被刪掉的東西曾經證明了什麼。**

**驗證**：OpenAPI diff **只少那一個路徑**。
`GATE-HD-OPENAPI-DIFF` 斷言 diff 的內容恰好是 `/api/projects/{project_id}/board` 一條。

## 3. `?tab=` — 保留到 `rc.1`，加一個計數器

**消費者是書籤與聊天記錄裡的連結，而那個集合 grep 不到。**

所以處置不同：加一個 metric，量它。

```text
legacy_route_hit_total{route="tab"}     ?tab= 被命中的次數
legacy_route_hit_total{route="board"}   /board 被叫的次數（刪除前的最後一週）
```

**刪除條件**：連續一個完整的 release window 計數為 **0**。
`beta.2` 期間量，`rc.1` 之前決定。

**為什麼不現在刪**：`router/index.ts:104` 的註解自己寫著
「Old links keep working, the redirect is visibly temporary」。
一個「visibly temporary」的東西被刪掉的正確時機是**有證據沒人在用**，
而不是「下一期」。

**為什麼要量而不是等**：一個沒有計數器的相容層會活到有人記得問它為止，
而那通常是三年。上游 §4 那張表本身就是一個例子——
它的六列在寫下來的時候是計畫，讀的時候已經是現況，而沒有東西說出這件事。

## 4. `HD-13` — 死碼與過期敘述

**四處**，每一處的共同點是：**它不會讓任何測試變紅。**

### 4.1 `api/http/work.py:3` 的 docstring 說謊

```python
# api/http/work.py:3
"""...
Also still the home of the **wave-0 side-car**, `GET /projects/{id}/board-attention`,
which is temporary and whose removal is `PX-25`'s job — it stays until the existing board
is replaced, because deleting it earlier would take the attention badges off the only
board there is.
```

**那個路由已經不在了。** `@router.get` 的清單只有四條，沒有 `board-attention`。
`PX-25` 做了它該做的事，而 docstring 沒有跟上。

`plan/26` §6 有一整段在講這一類東西：

> 一句寫錯的理由比一個空著的核取方框更難發現，
> 因為空方框會被追，而一個附了理由的空方框會被接受。

**這一處是同一個形狀的反面**：一個附了理由的**多餘**敘述，
會讓下一個人去找一個不存在的路由。

### 4.2 `api/client.ts:348` 的 `getBoard()` 是死碼

零個呼叫點。`HD-07` 刪它。

### 4.3 `db/models.py:796` 讀不出 stage 的值域

`ck_tasks_stage` 在資料庫裡（`0023_task_board.py:378`），
`Task.__table_args__` 只有一個 `UniqueConstraint`。
`HD-06` 補上（[`03`](./03-stage-final-migration.md) §2.1）。

### 4.4 `services/process.py:46` 的 `LANE_ORDER` 含 `blocked`

```python
LANE_ORDER = ("backlog", "blocked", "ready", "implementing", "verify", "done")
```

`HD-06` 之後 `blocked` 不再是一個 stage。**但改它有順序要求**：
它是六欄舊看板的排序來源，所以要等 `/board` 刪掉（`HD-07`）之後。

**這是 `HD-13` 依賴 `HD-07`、而 `HD-06` 依賴 `HD-13` 的實質理由**——
三張 ticket 的順序不是行政安排，是一條真的相依鏈。

### 4.5 再核對 `plan/26` §0 的十四處

`plan/26` 的 `PX-00` 回寫了十四處到 `research/03/`，
形式是「保留原文並劃掉」。**本期要再核對一次那十四處是否仍然正確**——
因為其中幾處記的是會變的數字（migration head、requirements 數、tokens 數），
而本期又會動它們。

**這一項的成本是十五分鐘，而它防的是一份被兩期各改一半的基準表。**

## 5. 上游 §4 route 相容表的現況核對

| 舊 | 新 | 上游說 | 實際 |
|---|---|---|---|
| `/projects/:id?tab=board` | `/projects/:id/work` | redirect | ✅ 已實作（`router/index.ts:106`） |
| `/projects/:id?tab=roadmap` 等 | 對應子路由 | redirect | ✅ 已實作，六個 tab 全部 |
| `/projects/:id/tasks/:taskId` | 不變 | 保留 | ✅（`router/index.ts:179`） |
| `/projects/:id/requirements/:reqId` | 不變 | 保留 | ✅（`:185`） |
| `/projects/:id/runs/:runId` | 不變 | 保留 | ✅（`:204`） |
| `/dashboard` | `/` → Home | 保留為別名 | ✅（`:28`） |
| **browser back 依序：關 Drawer → 還原 view → 離開 Project** | — | 有 E2E 測試 | ✅ `plan/26` 的 J10 |

**六列全綠。** 本期要做的是把它們**寫成已完成**並開始量 `?tab=`，
而不是重新實作一次。

## 6. 出口條件（本節）

| ☐ | 條件 | 證據 |
|---|---|---|
| ☐ | `/board` 六處全部刪除 | diff |
| ☐ | `test_the_board_card_stays_a_summary` 的 docstring 已搬進 ADR 0044 | ADR |
| ☐ | OpenAPI diff **恰好**少 `/api/projects/{project_id}/board` 一條 | `GATE-HD-OPENAPI-DIFF` |
| ☐ | `legacy_route_hit_total` 在 `/metrics` 上，兩個 label 都有值 | 截圖 |
| ☐ | `?tab=` **未刪除**，刪除條件已寫進 release note | release note |
| ☐ | `work.py` 的 docstring 已改，不再提一個不存在的路由 | diff |
| ☐ | `getBoard()` 已刪 | diff |
| ☐ | `LANE_ORDER` 已改，且順序（`HD-07` → `HD-13` → `HD-06`）被遵守 | commit 順序 |
| ☐ | `plan/26` §0 的十四處已再核對，不正確的已回寫 | [`11`](./11-implementation-status.md) §0 |
| ☐ | 上游 §4 的六列已標為已完成 | `research/03/12` diff |
