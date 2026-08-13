# 07 — 前端：看板、藍圖、任務詳情與 Requirements（`TK-09`、`TK-10`）

沿用 `research/style.md` 的方向與 `plan/16/05` 的既有決定。
**沒有新的視覺語言，只有新的資訊層級**（`research/02/09` §1）。

## 1. 導覽與路由

**導覽一列都不加。** V2.0 已經把 `Projects` 放進導覽，本期的東西全部在 Project 詳情頁的分頁下：

```text
/projects/:id                      ← 既有，本期加四個分頁
  Overview（既有）
  Requirements   ← 新
  Board          ← 新
  Roadmap        ← 新
  Activity（既有）
  Settings       ← 新（本期只有流程定義的唯讀顯示 ＋ ui gate 停用說明）

/projects/:id/tasks/:taskId        ← 新路由：任務詳情
```

- **sidebar 不重量**（M8 是 V2.0 量的，本期沒有新的導覽項；V2.2 加 `Agents` 時才要重量）。
- 任務詳情是一個**獨立路由**不是 modal：它會被貼進聊天、貼進 PR 描述，需要一個 URL。
- 分頁狀態放在 query（`?tab=board`），重整不跳回 Overview。

## 2. Board

### 2.1 版面

六車道橫向排列，車道標頭帶計數與 WIP 建議值（超標變色，**不阻擋**）。
卡片顯示：`card_ref`、標題、risk 徽章、owner、**阻塞徽章**（`dependsOn` 未滿足）、
`delivery` 徽章（`none` 用低調樣式）。

**本期沒有 run 狀態徽章與「等待你的回覆」**——那是 V2.2 的東西。
卡片上留好位置但不渲染空殼。

顏色：六個 stage 的顏色要與既有 Session 狀態色**明顯區分**
（`research/02/09` §7：同一個畫面上會有「Session 進行中」與「任務進行中」）。
用既有 token 組合，**不新增一次性色彩**；缺的組合登記回 `frontend/src/theme/`。

### 2.2 拖曳的互動契約

```text
放開 → 樂觀更新（卡片立刻出現在新車道）
     → PATCH /api/tasks/{id} { stage, version }
     → 200：以回應的 version 更新本地
     → 4xx：彈回原位 ＋ 重新載入該卡 ＋ 具體訊息
```

訊息必須具體（`research/02/03` TK-07）：

| 狀況 | 文案 |
|---|---|
| 409 `TASK_VERSION_CONFLICT` | 「這張卡剛被別人改過，已重新載入。」 |
| 409 `TASK_DEPENDENCY_UNSATISFIED` | 「TASK-3、TASK-7 尚未完成。」（**指名**，用回應的 `blocking_refs`） |
| 200 ＋ `warnings` | 卡片上一個非阻擋的提示：「就緒條件缺 3 項」 |

**彈回原位是硬要求**：一個失敗後停在新車道的卡片會讓人以為成功了。

### 2.3 不裝拖曳套件（README 第 8 條）

`frontend/package.json` 目前沒有任何 DnD 相依。用原生 HTML5 drag events
（`draggable`、`dragstart`／`dragover`／`drop`），約 80 行的 composable。

**同時做一條鍵盤／選單的等效路徑**：卡片上的「移動到…」選單，
每個車道一個選項，`Enter` 可達。兩個理由：

1. **可及性**：HTML5 DnD 對鍵盤使用者完全不可用。
2. **e2e 的主要斷言路徑**：HTML5 DnD 在 Playwright 上不穩定。
   選單路徑驗**行為**（樂觀更新、409、彈回），另有一條真實拖曳的測試驗**互動**
   （允許重試，且失敗時不 block 整條 pipeline——但它必須存在，
   只有選單那條會讓「拖不動」上線）。

## 3. Roadmap

Epic → User Story → Task 三層摺疊，每層顯示完成度（`stage === 'done'` 的卡數／總卡數）。

**未分類桶要有兩個**，這是 D4 的語意（沿用 Monstrare）：

- 指定 Epic 但未指定 User Story 的 Task → 該 Epic 下的「（未分類任務）」。
- 兩者都沒指定的 Task → 頂層的「（未歸類）」。

卡片不該憑空消失——這是判準 1 的一部分。

## 4. Task Detail

兩欄（`research/02/09` §4.5）：

```text
+---------------------------------------------------------------+
| TASK-12  Workspace File Tree API                    進行中     |
+------------------------------+--------------------------------+
| 任務定義                      | 執行                           |
| ・目標／範圍／非目標          | 本階段由人執行                 |
| ・驗收標準（可勾選結果）      | Session：進行中 / 歷史 3 次    |
| ・Readiness 7 項              | [開始工作]                     |
| ・Review Gates 6 項           |                                |
| ・相依與阻塞原因（指名）      | 執行設定（V2.3 起生效）        |
| ・來源：需求 #12 的提案 #3    | source / delivery / base branch |
+------------------------------+--------------------------------+
| 活動（本卡的 activity_events，含 actor_kind 標示）             |
+---------------------------------------------------------------+
```

四個要點：

- **勾 gate 的 UI 顯示核准者與時間**——那一格永遠是一個人
  （`research/02/03` TK-07）。取消核准要二次確認。
- **被衍生停用的 `ui` gate** 顯示為停用 ＋ 原因 ＋「前往設定」（`03-…md` §1.3）。
- **執行設定區標為「V2.3 起生效」**（`00-…md` D11）。這是本期唯一會讓人誤解的區塊，
  文案是唯一的處置。
- **活動列表區分三種 actor**：人（名字，無 `audit.view` 時空白 ＋「需要稽核權限」）、
  Agent（帶 runtime 圖示 ＋「Session 的 Agent」）、系統（低調單行）。
  這是 `actor_kind` 存在的唯一理由（`02-…md` §2.3）。

## 5. Task ↔ Session（`TK-10`）

### 5.1 「開始工作」是預填，不是新流程

從 Task Detail 按下去 → 開既有的 New Session 對話框，
預填 Project、Workspace（該 Project 的 `is_primary` 綁定）、Runtime、`task_id`。

**Node／Runtime／Workspace 的選擇與驗證一步都不能省**（`00-…md` 不得弄壞的第 4 條）。
使用者可以改任何一格；改到不屬於該 Project 的 workspace 時，
沿用既有的 `SESSION_PROJECT_MISMATCH` 400。

### 5.2 投影的呈現（D8）

Session 建立成功之後有第二次往返。三種結果三種呈現：

| 結果 | Session Workspace 上的呈現 |
|---|---|
| 成功 | 一行低調的狀態：「任務情境已送達 `.cliora/context/`」 |
| 失敗（逾時、寫入被拒） | 一條可關閉的橫幅：「情境未送達，Session 可正常使用。[重試]」 |
| node 不支援（舊 agentd） | 「此 node 的 agentd 需升級到 0.8.0 才能送出任務情境。[前往更新]」 |

**三種都不是錯誤頁**，Session 照常可用。

### 5.3 Session Workspace 的版面一個像素都不動

`research/02/09` §5 的右欄 tab 化是 **V2.2／V2.4** 的事。本期：

- 中央區、右欄 FileTree、status bar **完全不變**。
- 只在 header 加一段麵包屑：`Project · TASK-12`（純文字連結，不佔垂直空間）。
- **Ad-hoc Session 與升級前逐像素相同**——這是旗標關閉回歸的一部分（`08-…md` §3）。

## 6. Requirements

四個畫面裡本期做三個（`research/02/09` §4.5b）：

| # | 畫面 | 本期 |
|---|---|---|
| 1 | **Intake** | ✅ 一個刻意簡單的輸入框——它接受的就是一句模糊的話 |
| 2 | 釐清中 | ❌ **不做**。它明文重用 V2.2 的卡片訊息串元件，兩套訊息管道會立刻分裂（D28） |
| 3 | **規格審閱** | ✅ objective／scope／non-goals／AC 逐項；`open_questions` **置頂**，未解決時核准鈕停用**並指名是哪幾個**；版本比較（第 N 版 vs N-1） |
| 4 | **提案接受** | ✅ 三層樹狀勾選、可就地編輯、**顯示每張卡的 DoR 缺項**、底部「將建立 N 張卡片」 |

**核准鈕停用時必須說明原因**，不是靜默禁用（`research/02/09` §6）。

## 7. 狀態與可用性

每個新畫面都要交付（沿用既有紀律，逐項列出而不是「照 design system 做」）：

| 狀態 | 要求 |
|---|---|
| 載入中 | 骨架，不是全頁 spinner |
| 空 | 有下一步的文案。看板空狀態：「還沒有任務。先建一個 Epic，或直接建一張卡。」 |
| 錯誤 | 安全訊息 ＋ `request_id` ＋ 重試 |
| 權限不足 | 由伺服器 403 驅動，**不做前端路由守衛**（沿用 `/audit` 與 `/projects` 的既有決定） |
| 旗標關閉 | `/projects/:id/tasks/:taskId` 與其他 project 路由一樣：伺服器 404 驅動的畫面 |
| Node 離線 | 看板照常（任務資料在平台，不在 node）；只有「開始工作」被停用並說明 |
| 拖曳失敗 | §2.2 的三種文案 |
| `ui` gate 停用 | Task Detail 與 Project Settings 兩處都寫出原因 |

## 8. 測試

| 層 | 覆蓋 |
|---|---|
| 前端單元 | 看板分組；藍圖聚合（**含兩個未分類桶**）；三種 actor 的渲染；stage 標籤對照；WIP 超標樣式 |
| 前端單元 | 拖曳 composable 的樂觀更新與三種回滾路徑 |
| E2E（選單路徑） | 建 Epic→US→3 卡→推進→Roadmap 完成度；相依阻擋的指名訊息；兩分頁併發 409 彈回 |
| E2E（真實拖曳） | 一條 happy path，允許重試 |
| E2E | Task Detail 開 Session → 投影成功的狀態列；模擬投影失敗 → 橫幅 ＋ 重試 |
| E2E（旗標關閉） | Session Workspace 截圖與 V2.0 基線逐位元組相同；`/projects/*` 全 404 |
