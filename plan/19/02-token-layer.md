# 02 — `UI-01`／`UI-02`：Token 層與 104 個引用的還債

## 1. 現況的精確測量（`UI-00` 基線）

重現指令（六份基線之二、之三）：

```bash
# 定義了幾個
grep -ohE '^\s*--[a-z0-9-]+:' frontend/src/theme/tokens.css frontend/src/theme/base.css \
  | tr -d ' :' | sort -u | wc -l          # → 27

# 引用了幾個、各幾次
grep -rohE 'var\(--[a-z0-9-]+' frontend/src --include=*.vue --include=*.css --include=*.ts \
  | sed 's/var(//' | sort | uniq -c | sort -rn
```

**27 個定義（`base.css` 定義 0 個），43 個引用，差 16 個名字、104 次引用。**

### 1.0 104 次分成兩種，後果完全不同

這是整份診斷最關鍵的一段，**先分清楚再談修法**：

```bash
# 有 fallback 的（不會壞）
grep -rnoE 'var\(--(color-|space-|font-size-|font-mono|status-warning|status-danger|status-success|border-subtle|surface-raised)[a-z0-9-]*,[^)]*\)' frontend/src --include=*.vue --include=*.css
```

| | 寫法 | 次數 | 後果 |
|---|---|---|---|
| **A** | `var(--space-2)` 無 fallback | **83** | 整條宣告被丟棄 → **真的壞掉** |
| **B** | `var(--status-danger, crimson)` 有 fallback | **21** | 宣告有效 → 不壞，但**繞過 token 系統**，實際渲染 `crimson` |

**兩種寫法沿著檔案乾淨地分開**：

| 檔案 | 壞掉／總數 | 屬於 |
|---|---|---|
| `components/project/TaskBoard.vue` | **31 / 31** | V2.1 任務層 |
| `components/project/TaskDetail.vue` | **26 / 26** | V2.1 任務層 |
| `components/project/TaskRoadmap.vue` | **17 / 17** | V2.1 任務層 |
| `views/RequirementDetailView.vue` | **5 / 5** | V2.1 任務層 |
| `views/TaskDetailView.vue` | **4 / 4** | V2.1 任務層 |
| `views/ProjectDetailView.vue` | 0 / 8 | V2.0 |
| `views/ProjectsView.vue` | 0 / 4 | V2.0 |
| `components/session/NewSessionDialog.vue` | 0 / 3 | V1 |
| `views/AgentsView.vue` | 0 / 2 | V2.2 |
| `SessionWorkspaceView`／`RunDetailView`／`EnrollmentView`／`FileTreeNode` | 0 / 各 1 | V1／V2.2 |

**A 類 83 個全部落在 V2.1 的任務層五個檔案，一個不漏。** 這不是隨機疏漏，
是兩種寫作習慣，而其中一種產出了三個完全無樣式的主畫面。

**B 類 21 個實際渲染出來的值**（照修，但理由不同）：
`crimson`（4）、`seagreen`、`darkorange`、`monospace`（4）、`#d0d0d0`（3）、
`rgba(127,127,127,0.12)`、以及若干 `var(--另一個既有 token)`。

> 一個有 design token 檔的專案裡出現 `crimson`，靠的就是 fallback 這個管道。
> **B 類修起來風險比 A 類高**——A 類本來就沒有樣式，修好只會變好；
> B 類今天看得見，改了顏色就會變（`crimson` → `--status-error` 的 `#d25454`）。
> 見 §3.3。

### 1.1 16 個不存在的名字，四類

| 類別 | 寫成 | 該寫的 | 次數 |
|---|---|---|---|
| 顏色改用 `--color-*` 命名空間 | `--color-text-muted` | `--text-muted` | 16 |
| | `--color-border` | `--border-default` | 7 |
| | `--color-warning` | `--status-busy` | 4 |
| | `--color-surface` | `--surface-elevated` | 2 |
| | `--color-surface-2` | `--surface-default` | 1 |
| | `--color-success` | `--status-online` | 1 |
| 狀態色錯字尾 | `--status-warning` | `--status-busy` | 5 |
| | `--status-danger` | `--status-error` | 3 |
| | `--status-success` | `--status-online` | 2 |
| 尺度（**根本不存在**） | `--space-1`…`--space-4` | 新增（§2.2） | 33 |
| | `--font-size-xs`／`sm`／`lg` | 新增，改名 `--font-*` | 18 |
| | `--font-mono` | 新增 | 9 |
| 其他 | `--border-subtle` | `--border-default` | 2 |
| | `--surface-raised` | **`--surface-canvas`**（拖放目標高亮，**不是** `--surface-elevated`——見 §3.3.1） | 1 |
| | | **合計** | **104** |

### 1.2 為什麼是「畫面崩掉」而不是「掉個顏色」

CSS 的 **invalid at computed-value time** 規則：`var()` 解不開時，
**整條宣告被丟棄**（規格上等同該屬性被設為 `unset`），不是只丟那個值。

| 寫的 | 實際發生 | 使用者看到 |
|---|---|---|
| `border: 1px solid var(--color-border)` | 整條 `border` 消失 | **車道與卡片沒有框線**——六車道視覺上不存在 |
| `background: var(--color-surface-2)` | 背景消失 | 車道與畫布同色 |
| `gap: var(--space-2)` | grid／flex 間距歸零 | **所有東西擠成一團** |
| `padding: var(--space-2)` | 內距歸零 | 文字貼著邊 |
| `font-size: var(--font-size-sm)` | 字級退回預設 | **`h2`／`h3`／`h4` 變成瀏覽器預設的巨大粗體** |
| `font-family: var(--font-mono)` | 退回比例字體 | `TASK-101` 對不齊 |

**以上只適用 A 類（無 fallback）的 83 個**，而它們 100% 集中在 V2.1 的任務層五個檔案。
`TaskBoard.vue` 31、`TaskDetail.vue` 26、`TaskRoadmap.vue` 17 = 74 個落在三個主畫面上。
這解釋了為什麼是「相當糟糕」而不是「有點醜」。

---

## 2. `UI-01` — Token 定稿

### 2.1 語意色（18 個，D32：原值採納）

寫進 `frontend/src/theme/tokens.css`，**分四組、每組帶註解說明它承載哪個決定**。
註解不是裝飾——`tokens.css` 現有的每個區塊都有註解（見 `--layout-sidebar` 那段
把 280→208px 的理由寫了七行），沿用這個慣例。

```css
/* V2 工作語彙。三組「進行中」必須一眼分得出來（research/02/09 §7）：
 *   Session 進行中 → --status-online（既有綠，不新增）
 *   Task 進行中   → --stage-implementing（藍）
 *   Run 執行中    → --run-running（琥珀）＋ 脈動指示
 * 這三個顏色同時出現在看板與 Task 詳情上，全用綠色會讓人完全看不出差別。 */

/* Task stage（六車道）。刻意避開 --status-* 的綠，走灰→藍→紫→深綠的推進感，
 * 讓「卡片在流程上走到哪」與「機器健不健康」是兩種視覺語言（01 D3）。 */
--stage-backlog: #8892a0;
--stage-blocked: #b4574f;
--stage-ready: #4a7c8c;
--stage-implementing: #3f6fa8;
--stage-verify: #7a5ea8;
--stage-done: #2f7a56;

/* Run 狀態。--run-waiting 是 D24 的專用色：全 app 只有「等待你的回覆」用它，
 * 因為它是唯一一個「系統在等人」的狀態，其他都是「人在等系統」。
 * 用在別的地方會稀釋它，那正是它存在的理由被抵銷的方式。 */
--run-queued: #8892a0;
--run-running: #c68c37;
--run-waiting: #d2691e;
--run-succeeded: #2f9b63;
--run-failed: #d25454;
--run-lost: #a0673f;

--risk-low: #6b7684;
--risk-medium: #c68c37;
--risk-high: #c45c5c;

/* 證據可信度三級。實心＝機器事實、線框＝平台紀錄、灰字＝Agent 自述。
 * 這是可信度語言不是裝飾，三處畫面（驗證報告、證據、Run 詳情）必須完全一致
 * ——所以它只有一個元件在用（D10、01 D34）。 */
--source-machine: #2f7a56;
--source-platform: #4a7c8c;
--source-agent: #8892a0;
```

### 2.2 尺度 token（12 個）

```css
/* 間距與字級刻度。tokens.css 從第一天就沒有這兩組，所以每個元件各自寫死像素值，
 * 而 V2 的作者憑印象寫了 --space-2 / --font-size-sm 這種名字（104 次，13 個檔案）。
 * 補上刻度，那個錯誤才不會再犯。 */
--space-1: 4px;   --space-2: 8px;   --space-3: 12px;
--space-4: 16px;  --space-5: 24px;  --space-6: 32px;

--font-xs: 11px;  --font-sm: 12px;  --font-base: 13px;
--font-md: 15px;  --font-lg: 19px;  --font-xl: 24px;
```

**命名採 `--font-*` 而非 `--font-size-*`**（B2）：與 `--space-*`、`--radius-*`、
`--layout-*` 對稱，且 prototype 已經用這個名字。程式碼裡的 18 處
`--font-size-*` 在 `UI-02` 一併改名。

### 2.3 `--font-mono`

**`base.css` 完全沒有等寬字堆疊**（實測：`grep monospace base.css` 無輸出）。
它只設了 `:root` 的 sans-serif 堆疊。所以每個要用等寬的地方各自處理，結果是三種寫法並存：

| 寫法 | 在哪 | 實際效果 |
|---|---|---|
| 完整堆疊寫死 | `SessionWorkspaceView.vue`（×2）、`PreviewPane.vue` | 正常，但重複三份 |
| `var(--font-mono, monospace)` | `EnrollmentView`、`ProjectDetailView`（×2）、`NewSessionDialog`（×2） | 退到裸 `monospace` |
| `var(--font-mono)` 無 fallback | `TaskBoard`、`TaskDetail`（×2）、`TaskRoadmap` | **壞掉**，退回比例字體 |

**抽成 token**，值採用既有寫死堆疊中最完整的那一份（prototype 也用同一份）：

```css
--font-mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
```

三處寫死的堆疊改為引用它，**不留四份**。
`PreviewPane.vue` 與 `SessionWorkspaceView.vue` 是 V1 檔案——
改它們會不會影響字形，要在 §3.3 的前後對照裡確認
（預期不會：值刻意取自它們現有的堆疊）。

### 2.4 兩個 prototype 沒涵蓋的 `RunStatus` 值

`dto.ts` 的 `RunStatus` 是 8 個值，prototype 只給了 6 個顏色。補齊的決定：

| 值 | 顏色 | 標籤 | 理由 |
|---|---|---|---|
| `claimed` | `--run-queued`（同色） | 已認領 | 極短的過渡狀態，另給一個顏色只是雜訊 |
| `cancelled` | `--status-offline` 灰 | 已取消 | **刻意不用 `--run-failed` 紅**——取消是人的決定，不是失敗 |

**不新增 token**，這兩個值復用既有的。

### 2.5 同步 `research/style.md`

沿用既有慣例：token 進 `tokens.css` 就同步 `style.md`。
加一節「V2 工作語彙」，把四組列進去並註明出處是 `research/02/12` §2。

---

## 3. `UI-02` — 104 個引用的還債

### 3.1 這張 ticket 的紀律：**只准改名字**

`00-execution-plan.md` §5 把它列為本期最高風險：**`UI-02` 很容易膨脹成一次重設計。**

**diff 規則（review 時逐條檢查）**：

- ✅ 允許：`var(--color-text-muted)` → `var(--text-muted)`
- ✅ 允許：`var(--font-size-sm)` → `var(--font-sm)`
- ❌ 不允許：新增／刪除 CSS 宣告
- ❌ 不允許：改動 `<template>` 結構、class 名稱
- ❌ 不允許：新增元件

**B 類要一併把 fallback 拿掉**：`var(--status-danger, crimson)` → `var(--status-error)`。
留著 fallback 就是留著下一個 `crimson` 的入口，而且 `UI-03` 的守門
對有 fallback 的引用**看得見但不會擋**（`07-…md` §3.3）。

驗收指令：

```bash
# diff 裡每一個變動行都必須含 var(--
git diff -U0 -- frontend/src | grep -E '^[+-][^+-]' | grep -v 'var(--' 
# 預期輸出：空
```

版面調整屬於 `UI-07`…`UI-10`，**不在這裡**。

### 3.2 對照表（完整，13 個檔案）

`UI-02` 的實作就是照這張表做機械替換，**只有 `FileTreeNode.vue` 那一列例外**（§3.3.1）。

| 檔案 | 替換 |
|---|---|
| `components/project/TaskBoard.vue`（31） | `--color-border`×4→`--border-default`；`--color-surface`×2→`--surface-elevated`；`--color-surface-2`→`--surface-default`；`--color-text-muted`×4→`--text-muted`；`--color-warning`×4→`--status-busy`；`--font-mono`（新增後可用）；`--font-size-sm`×2→`--font-sm`；`--font-size-xs`×3→`--font-xs`；`--space-*`×10（新增後可用） |
| `components/project/TaskDetail.vue`（26） | `--color-success`→`--status-online`；`--color-text-muted`×7→`--text-muted`；`--font-mono`×2；`--font-size-lg`→`--font-lg`；`--font-size-sm`×2→`--font-sm`；`--font-size-xs`×5→`--font-xs`；`--space-*`×8 |
| `components/project/TaskRoadmap.vue`（17） | `--color-text-muted`×4→`--text-muted`；`--font-mono`；`--font-size-sm`×2→`--font-sm`；`--font-size-xs`×2→`--font-xs`；`--space-*`×8 |
| `views/ProjectDetailView.vue`（8） | `--border-subtle`→`--border-default`；`--font-mono`×2；`--status-danger`×2→`--status-error`；`--status-success`→`--status-online`；`--status-warning`×2→`--status-busy` |
| `views/RequirementDetailView.vue`（5） | `--space-2`×2、`--space-3`×3 |
| `views/TaskDetailView.vue`（4） | `--color-text-muted`→`--text-muted`；`--font-size-sm`→`--font-sm`；`--space-2`、`--space-4` |
| `views/ProjectsView.vue`（4） | `--border-subtle`→`--border-default`；`--status-danger`→`--status-error`；`--status-warning`×2→`--status-busy` |
| `components/session/NewSessionDialog.vue`（3） | `--font-mono`×2；`--status-warning`→`--status-busy` |
| `views/AgentsView.vue`（2） | `--color-border`×2→`--border-default` |
| `views/SessionWorkspaceView.vue`（1） | `--status-success`→`--status-online` |
| `views/RunDetailView.vue`（1） | `--color-border`→`--border-default` |
| `views/EnrollmentView.vue`（1） | `--font-mono` |
| `components/file/FileTreeNode.vue`（1） | `--surface-raised`→**`--surface-canvas`**（拖放目標高亮，已查證；**不是** `--surface-elevated`，那會讓高亮消失——見 §3.3.1） |

### 3.3 B 類（有 fallback）才是風險所在

直覺會以為壞掉的 A 類比較危險。**反過來。**

| | 修之前 | 修之後 | 風險 |
|---|---|---|---|
| **A 類（83）** | 沒有樣式 | 有樣式 | **低**——只會變好，沒有既有外觀要保住 |
| **B 類（21）** | 用 fallback 值渲染，**看起來正常** | 換成 token 值 | **高**——今天看得見的顏色會變 |

具體會變的顏色：

| 現在渲染的 | 改成 | 檔案 |
|---|---|---|
| `crimson`（#DC143C） | `--status-error`（#d25454） | `ProjectDetailView`×2、`ProjectsView` |
| `seagreen`（#2E8B57） | `--status-online`（#2f9b63） | `ProjectDetailView` |
| `darkorange`（#FF8C00） | `--status-busy`（#c68c37） | `ProjectDetailView` |
| `#d0d0d0` | `--border-default`（#d7dde4） | `AgentsView`×2、`RunDetailView` |
| `rgba(127,127,127,.12)` | `--surface-elevated`（#fff） | `FileTreeNode` |
| 裸 `monospace` | 完整 mono 堆疊 | `EnrollmentView`、`ProjectDetailView`×2、`NewSessionDialog`×2 |

每一列都是**使用者看得見的變化**，而且方向都是「從不協調的預設色，
變成設計系統裡的對應色」——所以是修正，不是回歸。但必須被人看過：

- 每一處附**前後對照截圖**進 `09-implementation-status.md`；
- 人工確認是「本來就該長這樣」而不是「改壞了」；
- 出口條件 8 的逐像素基準**必須在 `UI-02` 之後才取**（`08-…md` §4）。

### 3.3.1 `FileTreeNode.vue` 那一個不要機械替換

`var(--surface-raised, rgba(127, 127, 127, 0.12))`（`FileTreeNode.vue:261`）
是 21 個 B 類裡**唯一一個不能照對照表換**的。

`rgba(127,127,127,.12)` 是**半透明灰**——它疊在底下任何顏色上都成立，
所以它幾乎一定是**互動狀態**（hover／selected），不是一個表面色。
換成 `--surface-elevated` 的**不透明白**是語意改變，不只是色值改變：
在深色或已著色的列上，不透明白會蓋掉底下的東西。

**已經查過了（2026-08-12），答案是 `--surface-canvas`：**

```css
/* Outline plus text, never colour alone (style.md state contract): a hovered row
 * gets a dashed outline AND a label naming where the file would land. */
.row[data-drop-target] {
  outline: 1px dashed var(--action-primary);
  outline-offset: -1px;
  background: var(--surface-raised, rgba(127, 127, 127, 0.12));   /* ← 這一行 */
}
```

它是**拖放目標的高亮**，配一條 `--action-primary` 的虛線外框和一個文字標籤
（那條註解引用的 `style.md` 狀態契約：**永遠不只靠顏色**）。

所以正確的 token 是 `--surface-canvas`（#f4f6f8）——底下的檔案樹列坐在
`--surface-elevated`（#fff）上，淺灰在白底上看得見。

> ⚠️ **`--surface-elevated` 會讓這個高亮完全消失。**
> §3.2 對照表原本寫的就是那個（`--surface-raised` → `--surface-elevated`，
> 純粹照名字猜），而白底加白底等於沒有高亮——只剩虛線外框。
> **這正是「B 類不能機械替換」的具體例子**：它今天用 fallback 的半透明灰
> 正常運作，照名字猜著換會讓它靜默退化，而且退化的是一個
> 無障礙設計刻意做成雙重線索的狀態。

**`SessionWorkspaceView.vue` 的 `--status-success`** 在狀態列上，
而那個畫面有「Terminal 不得變窄」的既有出口條件。**確認只改顏色、不改寬度。**

### 3.4 完成定義

- [ ] 13 個檔案改完，§3.1 的 diff 檢查為空
- [ ] `UI-03` 的檢查器在本機跑出 **0 個未定義引用**
- [ ] 四個 V1 檔案各有一張前後對照
- [ ] `npm run build` 綠、`npm run test:unit` 綠
