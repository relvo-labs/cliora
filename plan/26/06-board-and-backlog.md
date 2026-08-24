# 06 — Active Board 與 Backlog

> **ticket：`PX-29`（Board）、`PX-30`（Backlog）、`PX-31`（search／filter）、
> `PX-32`（group／sort／display）、`PX-33`（saved views）、
> `PX-34`（move ＋ 鍵盤）、`PX-36`（分頁 ＋ 全螢幕）。依賴 `PX-18`、`PX-64`。**

## 1. 這一段解決什麼

現況：固定六欄、`ORDER BY updated_at DESC`、沒有搜尋、沒有篩選、沒有分組、
沒有 Backlog 專用視圖、沒有排序控制、沒有 saved view、**沒有分頁**
（`read_board` 的 docstring 把不分頁寫成一個決定：
「Moving acceptance criteria and gate detail out of the card bought what paging
would have, without a cursor, a scroll loader or an e2e for either」）。

**☑ [D117](./01-decisions-and-governance.md#d117)：這一段直接取代既有看板，不並存。**

**本期把「不分頁」那個決定的前提改掉了**：新讀模型的卡片是 33 欄不是 15 欄，
而且要支援 filter 與 group，所以「不分頁」不再是免費的。
`PX-36` 補上的 cursor、scroll loader 與 e2e，就是那句 docstring 說的代價。

使用者為了回答六個不同的問題（哪些等我？哪些沒有 runner？哪些 run 失敗？
哪些還沒 ready？哪些待核准？哪些屬於這個 Requirement？）
今天只能在同一個畫面上用眼睛掃。

## 2. Board Toolbar（`PX-31`／`PX-32`／`PX-33`）

```text
[View selector ▾] [Board|List] [🔍 Search] [Filter ▾] [Group ▾] [Sort ▾] [Display ▾] [⛶] [+ Create]
```

Quick filters（一列 chip，點擊即套用於目前 view，**不改存檔**）：

```text
Waiting for me · Agent active · Failed · Blocked · High risk · Unassigned · Gate unmet
```

### Quick filter 與 saved view 的關係（[D103](./01-decisions-and-governance.md)）

```text
點 chip     → 只改 URL 的 f= 參數，不碰 work_views 的列
toolbar     → 顯示「已修改」 ＋ [另存為…] [還原]
「另存為…」 → POST /api/projects/{id}/views（personal scope）
「還原」     → 移除 URL 的 f=，回到 view 的定義
```

**`Blocked` 與 `No runner` 兩個 chip 是特殊的**：它們映射到 attention 的
runtime 級（[D92](./01-decisions-and-governance.md)）。當
`runtime_signals_available` 為 `false` 時，這兩個 chip **顯示為停用並附一行說明**
「節點連線資訊暫時不可用」——不是回 0 筆讓人以為問題解決了。

### 沒有 filter 時套用使用者的預設 view

移植自 kintra `BoardFilterCriteria.is_empty()`（`P2-B15`，[`13`](./13-kintra-port.md) §4）：

```text
URL 沒有 f= 也沒有 view=  → 套用該 project 的 is_default view
URL 有 view= 沒有 f=      → 套用該 view
URL 有 f=                → 套用 f=，toolbar 顯示「已修改」
```

**上游沒有寫這一條**，而少了它，第一次進看板的人看到的是未篩選的全部卡片
——那正是 `beta.1` 要取代的畫面。

### URL 序列化

```text
/projects/:id/work?view=<uuid>&f=<base64url(json)>&g=lifecycle&o=rank:asc&task=<uuid>
```

`f=` 超過 1500 字元時退回「view id ＋ 本機暫存」，
並在 toolbar 顯示「此篩選未包含在連結中」。
`PX-31` 有一組 property 測試：序列化 → 反序列化 → 深度相等。

## 3. Active Board（`PX-29`）

### 3.1 預設四欄

```text
Ready | In progress | Review | Done
```

- **Backlog 不出現在 Active Board。**
- **Done 預設只顯示最近 7 天或最近 N 張**（N 預設 20），欄頭顯示「近 7 天 / 共 348」。
  這一格由 `ix_tasks_project_updated` 支撐（[D104](./01-decisions-and-governance.md)）。
- **blocked work 留在原 stage**，卡片以 attention 呈現，不獨立成欄。
- 欄頭數字是 **server count**（`PX-36` 的釘死測試）。

四欄對應 `group=lifecycle` ＋ `filter: lifecycle in (ready, in_progress, review, done)`。
**這不是四個硬編的欄，是預設 view 的 group 結果**——
所以換 group 之後畫面自然變成別的分組，而不需要第二段版面程式碼。

### 3.2 卡片結構（`PX-18`）

```text
┌─────────────────────────────────────┐
│ ⚠ Waiting for your input            │  ← primary attention（若有）
│ TK-142                              │  ← card ref
│ 支援 SAML SSO 登入                   │  ← title，最多三行
│ ─────────────────────────────────── │
│ 🤖 runner-03 · waiting · 12m        │  ← execution zone
│ ─────────────────────────────────── │
│ 陳小美 · high · PR · +2             │  ← metadata（依 view，最多 3–5 項）
└─────────────────────────────────────┘
```

**Attention 不能只靠顏色**（`plan/19` 已建立的原則）：
每個 attention 徽章同時有 **icon、文字與形狀差異中的至少兩項**。
`PX-17` 的十個 token ＋ `checkTokens.test.ts` 的既有 gate 涵蓋這件事，
而「至少兩項」由 `PX-18` 的一支元件測試斷言
（對八種 attention 各檢查 `aria-label` 非空 ＋ 有 icon 或有形狀 class）。

`attention_count > 1` 時顯示「＋2」，詳情在 Drawer——
卡片只顯示 primary（[D107](./01-decisions-and-governance.md)）。

### 3.3 密度（`PX-32`）

| | Compact | Comfortable（預設） |
|---|---|---|
| 標題 | 1–2 行 | 3 行 |
| Execution line | 只在有 active run 時 | 總是 |
| Metadata | ≤2 | ≤5 |

密度是**個人偏好**，存 localStorage，**不寫 audit**，不影響 project view 定義。
`PX-28` 有一支測試斷言改 density 沒有寫 audit。

### 3.4 Drag and drop（`PX-34`）

沿用 `plan/19` 已確立的 accessibility-first 原則。

| 規則 | 實作 |
|---|---|
| native DnD，不引入 DnD 框架 | `frontend/package.json` 進禁區清單 |
| **keyboard move ／ Move dialog 是正式路徑**，不是備援 | 與拖曳走**同一條** mutation（合併 `PX-35` 的理由） |
| optimistic update | `queryCache.mutate(fn, {snapshot, rollback})` |
| **versioned mutation** | 帶 `version`，409 時回滾並顯示 server 回的 `details.current` |
| failure rollback ＋ 保留重試入口 ＋ 具體原因 | 「移動失敗」不是原因 |
| screen-reader announcement | 移動前後都播報（`aria-live="polite"`） |
| **filter 開啟時送 neighbor IDs，不送 index** | payload 斷言測試 |
| **一次 move 只產生一個 `UPDATE tasks`** | 以 SQL 語句計數斷言（kintra `P2-T4`，[`13`](./13-kintra-port.md) §2） |
| 不允許的 stage 在 drop target 就給拒絕線索 | **但 server 仍是最終判斷** |

**「不允許的 stage」在這個 repo 裡只有一種**（[D97](./01-decisions-and-governance.md)）：
`DEPENDENCY_GATED_STAGES` ＋ 未完成的相依。因為
**`_require_stage()` 只檢查成員資格，沒有轉移矩陣**——任何 stage 到任何 stage 都合法。
所以 drop target 的預先線索只能來自 `blocking_count > 0`，
而 Done 欄的線索來自 Done Gate 的六個條件（前端**不重算**，
用 `pending_human_action` 與 `verification_state` 這兩個既有投影欄）。

四種拒絕情境各一測試（上游的出口條件），machine code 逐一對應：

| 情境 | code | 訊息要含 |
|---|---|---|
| 相依未完成 | `TASK_DEPENDENCY_UNSATISFIED` | `details.blocking_refs` 全部列出 |
| Done Gate 未過 | Done Gate 的既有拒絕 | **每一個** missing item |
| 樂觀鎖衝突 | `TASK_VERSION_CONFLICT` | `details.current` 的完整卡片（既有行為） |
| rank neighbor 失效 | `RANK_NEIGHBOR_STALE` | `details.reason` 三值之一 |

### 3.4b Move dialog（`PX-34`，移植自 kintra `TicketMoveDialog`）

> 三點選單只揭露「移動」這個意圖；目的欄位與放置位置集中在 Dialog 選擇。
> 這讓三點選單維持短小，也讓滑鼠與 `m` 鍵共用同一個可存取流程。

| 規則 | 說明 |
|---|---|
| 目的 group select | **排除目前所在的 group** |
| 位置 | segmented：置頂／置底 |
| 開啟時 | 重設為「第一個可選 group ＋ 置底」 |
| 沒有可選目的地 | confirm 不可按 |
| **送出** | **neighbor IDs，不是 `toTop`** |

最後一列是與 kintra 唯一的差異：kintra 的 dialog 只面對完整欄，
Cliora 的 Board **有 filter**，而「置頂」在篩選後的欄裡有歧義
——是篩選後的最上面還是資料的最上面。

所以 dialog 內部把置頂／置底換算成**目前這一欄已載入清單的第一／最後一張的 id**。
**這段換算要有測試**：篩選開啟時選「置頂」，送出的 `next_task_id`
是篩選後第一張卡的 id，而不是 `null`。

### 3.5 Grouping / swimlane（`PX-32`）

`beta.1` 提供八種 group（[`05`](./05-work-items-and-view-api.md) §2）。

**不得因 grouping 建立第二份排序真實來源。** rank 的 scope 是 project（D50），
grouping 只改變顯示分組。在 group 內拖曳只改 rank；
拖到**另一個 group** 時同時改 rank 與該欄位，**且兩者在同一個請求裡**
（[`05`](./05-work-items-and-view-api.md) §6）。

### 3.6 大量資料（`PX-36`）

- 每 group 獨立 cursor；`Load more`。
- 欄頭 count 為 server total。
- 超過 1000 張再評估 virtualization；**200 張是第一個 performance gate**。
- filter、group、sort **必須 server-side 可執行**——前端排序會讓分頁失去意義。

## 4. Backlog（`PX-30`）

高密度 List，不用大卡片。

```text
⠿  TK-142  支援 SAML SSO 登入       needs_clarification  陳小美  high  EP-3  [sso,backend]  2 天前
↑                                    ↑                     ↑       ↑     ↑     ↑            ↑
rank handle                          readiness            owner   risk  epic  labels       updated
```

操作：inline create、inline rename、drag rank、send to Ready、multi-select、
bulk owner／risk／labels、bulk move to Ready、attach to Epic／Story／Requirement、
open in Task Drawer。

**multi-select ＋ bulk 動作走 `POST /api/tasks/bulk-update`**，
上限 100（[D96](./01-decisions-and-governance.md)）。UI 在超過時明說
「一次最多 100 張，已選 137」，而不是靜默截斷。

## 5. Ready transition（`PX-30`，[D97](./01-decisions-and-governance.md)）

移到 Ready 前：

1. 前端讀 `readiness` 投影（`draft` / `needs_clarification` / `ready`）。
2. 不是 `ready` 時，**顯示一個列出缺失項的確認對話框**，
   而不是一個 400——因為 server 不會拒絕（`process.py:11`）。
3. **每一個缺失項可以直接點開去補**：對話框的每一列是一個連結，
   開啟 Drawer 並聚焦到對應欄位。這是本計畫對 D97 的代價的緩解，
   而它是 `PX-30` 的一個具體交付物，不是一句「UI 要友善」。
4. 對話框有兩個按鈕：`[補齊缺失項]`（主要）與 `[仍要送到 Ready]`（次要）。
5. **不允許 UI 先假設成功、之後才被 server 拒絕而找不到卡片**——
   這是 optimistic update 最常見的破口。Ready transition 的
   optimistic update 只在**沒有未完成相依**時啟用；有相依時等 server。

```text
┌── 這張卡還缺 3 項 ─────────────────────────┐
│ ☐ 驗收條件已定義              → 開啟並聚焦   │
│ ☐ 相依已釐清                  → 開啟並聚焦   │
│ ☐ 交付方式已選擇              → 開啟並聚焦   │
│                                             │
│ Definition of Ready 不會阻擋這次移動，        │
│ 但缺項會出現在這張卡的 readiness 徽章上。      │
│              [補齊缺失項]  [仍要送到 Ready]  │
└─────────────────────────────────────────────┘
```

那句「不會阻擋」是必要的：使用者看到一個列出缺失項的對話框時，
預設會以為它是一道閘門。**不說清楚的話，第一次按下「仍要送到 Ready」
的人會以為自己繞過了什麼。**

## 6. 出口條件

| ☐ | 條件 | 怎麼證明 |
|---|---|---|
| ☐ | Backlog 與 Active Work 清楚分離 | 兩個 view，Backlog 的卡不出現在 Active Board |
| ☐ | filter、scroll、view 在開關 Task 後保留 | E2E-J10 |
| ☐ | 所有 move refusal 都回滾並提供可行動原因 | 四種情境各一測試，訊息含 machine code 與缺失項 |
| ☐ | keyboard 可完成建卡、開卡、移動與篩選 | a11y 測試（`PX-65`） |
| ☐ | 欄頭 count 是 server total | 釘死測試：載入 20 張、count 顯示 348 |
| ☐ | filter 開啟時的移動送 neighbor IDs | 請求 payload 斷言 |
| ☐ | rank 三個不變式成立，再平衡不改變相對順序 | 移植的 kintra 測試 ＋ 新的整合測試 |
| ☐ | grouping 不建立第二份排序來源 | 跨 group 拖曳的**單一請求**斷言 |
| ☐ | 200 張卡 Board 首次可互動 < 2s | 效能量測（`PX-66`） |
| ☑ | Ready transition 的缺失項可直接點開補 | `ReadyTransitionDialog` 六條元件測試 ＋ `wave4.spec.ts` 的瀏覽器實跑：點第一列 → `?task=` ＋ `?focus=` → 焦點在 `[data-readiness=<key>] input`，而且 `?focus=` 用掉即清（重新載入不會再搶焦點）。**主控台本來根本沒有勾選就緒條件的控制項**（§2.26） |
| ☐ | `runtime_signals_available=false` 時兩個 chip 停用而非回 0 | 元件測試 |
| ☑ | 沒有 filter 時套用預設 view | `wave4.spec.ts`：URL 沒有 `view=` 也沒有 `f=` 時工具列顯示「目前的預設檢視」。**預設 view 只在它自己的 layout 生效**——套到清單版會讓剛建的 backlog 卡在打字時消失。並補了 `?view=all`（§2.29） |
| ☐ | 篩選開啟時 Move dialog 的「置頂」送篩選後第一張的 id | payload 斷言 |
