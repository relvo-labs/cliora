# CLI Agent Platform

# Visual Design Specification (VDS)

Version: 1.0

Design Language

> Quiet Intelligence × Developer Workbench × Modern Industrial

---

# 1. Design Philosophy

## Design Vision

建立一套讓開發者可以長時間工作的企業級 AI 開發平台。

介面應具有：

* 冷靜
* 專業
* 精準
* 高資訊密度
* 幾乎沒有學習成本

不是展示 AI，而是展示「工程能力」。

整體氛圍應讓使用者感受到：

> Everything is under control.

---

# Design Keywords

```text
Calm
Industrial
Developer
Precise
Minimal
Focused
Efficient
Reliable
```

---

# Emotional Tone

不像 ChatGPT

不像 Notion

不像 Figma

更像

VSCode
+
GitHub
+
JetBrains
+
Datadog
+
Cloudflare Dashboard

融合而成。

---

# 2. Visual Principles

遵循五個原則。

---

## Principle 1

Information First

資訊優先。

不要為了漂亮增加裝飾。

任何元素都要有存在理由。

---

## Principle 2

Low Cognitive Load

降低思考成本。

同一功能永遠放同一位置。

同一操作永遠使用相同交互。

---

## Principle 3

Developer Native

介面應符合工程師直覺。

例如：

Sidebar

Tabs

Terminal

Tree

Split View

Command Palette

Keyboard Shortcut

都優先存在。

---

## Principle 4

Industrial Reliability

畫面應具有設備管理平台的可靠感。

例如：

Node Online

CPU

Memory

Health

Session Count

都具有固定位置。

---

## Principle 5

Quiet Intelligence

不要大量動畫。

不要大量漸層。

不要過度玻璃擬態。

不要炫技。

AI 本身就是主角。

UI 只是工具。

---

# 3. Color System

> **修訂（`plan/28`，2026-09-08，ADR 0027）。** 本節以下的色階清單是**原始色階**
> （primitive palette），不是語意 token，而且它只有一組淺色值。它保留為
> **Porcelain 之前的歷史調色盤**：讀它可以知道 MVP 到 `plan/27` 為止的實際顏色，
> 但**元件不得直接引用它**——直接引用 `Gray-300` 就是繞過語意層，而那正是
> 2026-09-08 量到 69 處字面色值的來源。
>
> 有主題維度的語意 token 表在 **§3.1**。

## Neutral

```text
Gray-50     #FAFBFC
Gray-100    #F4F6F8
Gray-200    #E9EDF2
Gray-300    #D7DDE4
Gray-400    #B5BDC8
Gray-500    #8993A0
Gray-600    #66707D
Gray-700    #48505A
Gray-800    #2E343B
Gray-900    #1A1F24
Gray-950    #101317
```

---

## Primary

```text
Primary-50     #F1F7F8
Primary-100    #DCEDEF
Primary-200    #BEDDE0
Primary-300    #94C1C8
Primary-400    #67A2AE
Primary-500    #4E8593
Primary-600    #406B73
Primary-700    #35575D
Primary-800    #2C464B
Primary-900    #24383C
```

Primary

代表：

系統

控制

目前焦點

---

## Success

```text
#3E8C6A
```

---

## Warning

```text
#C08B3E
```

---

## Error

```text
#C45C5C
```

---

## Info

```text
#4A7FB8
```

---

# Status Color

Node Online

```text
#2F9B63
```

Offline

```text
#727B87
```

Busy

```text
#C68C37
```

Error

```text
#D25454
```

---

# Terminal

Background

```text
#0F1115
```

Selection

```text
rgba(120,170,255,.25)
```

Cursor

```text
#FFFFFF
```

---

# 3.1 語意 Token 與主題

自 `plan/28`（ADR 0027）起，**顏色只有一個來源，而且它有主題維度**：

- `frontend/src/theme/tokens.css` —— CSS 的來源。`:root` 定義預設主題 Graphite，
  `:root[data-theme="porcelain"]` 覆蓋。**每個主題必須明確定義每一個 token**，
  不得以 `var(…, fallback)` 的鏈式 fallback 掩蓋缺漏。
- `frontend/src/theme/themes.ts` —— JS 的來源。xterm 的 `terminal.options.theme` 與
  Monaco 的 `defineTheme()` 都吃不了 `var()`，需要具體色值字串。
- 兩份來源由 `theme/theme.contract.test.ts` 逐鍵綁死；任一漂移即測試失敗。

完整的語意 token 清單、兩款主題的色值與**實測**對比值在
[`plan/28/02-token-contract-and-themes.md`](../plan/28/02-token-contract-and-themes.md)，
本文件不複製那張表（會漂移）。這裡只記三條不變量：

1. **`frontend/src` 底下不得出現任何字面色值**（`#hex`、`rgb()`、`hsl()`），
   `theme/tokens.css` 與 `theme/themes.ts` 除外。由 `GATE-VR-NO-LITERAL-COLOR` 擋。
2. **`border.subtle` 只做裝飾分隔，不得用於必要控制邊界。** 五款主題的 `border.subtle`
   對面板底實測 1.21–1.61:1，沒有一款到 3:1。輸入框、次要按鈕、Checkbox 一律用
   `border.control`（對 `surface.default` 與 `surface.canvas` 兩者都 ≥ 3:1）。
3. **狀態色不由品牌色兼任，而且每個狀態是 foreground／background／border 三元組**
   （見 §17）。

**本期交付兩款主題**：Graphite（預設，深色）與 Porcelain（淺色）。
Midnight／Studio／Industrial 的色值進 `themes.ts` 並通過完整性與對比測試，
但不進切換器、不實作版型差異、不列入驗收矩陣（ADR 0027 §5）。

---

# 4. Typography

Primary Font

```text
Inter
```

Code

```text
JetBrains Mono
```

Fallback

```text
system-ui
```

---

Heading

```text
32
28
24
20
18
```

Body

```text
16
14
13
12
```

Terminal

```text
13
```

Line Height

```text
1.5
```

Letter Spacing

```text
0
```

不要刻意增加。

---

# 5. Spacing

Base Unit

```text
4px
```

Spacing Scale

```text
4
8
12
16
20
24
32
40
48
64
```

所有 Padding

Margin

Gap

全部使用此 Scale。

---

# 6. Border Radius

Tiny

```text
4
```

Normal

```text
8
```

Large

```text
12
```

Card

```text
16
```

不要超過

```text
16px
```

---

# 7. Shadow

Level 1

```text
0 1px 2px rgba(0,0,0,.05)
```

Level 2

```text
0 4px 12px rgba(0,0,0,.08)
```

Level 3

```text
0 10px 30px rgba(0,0,0,.12)
```

不要玻璃效果。

不要 Neon Glow。

---

# 8. Border

Normal

```text
1px solid Gray-200
```

Active

```text
1px solid Primary-500
```

Danger

```text
1px solid Error
```

---

# 9. Layout

採 IDE Layout。

```
+-------------------------------------------------------+
| Header                                                |
+-----------+-------------------------+-----------------+
| Sidebar   | Main Workspace          | Inspector       |
|           |  (Work head / Tabs)     |                 |
|           |                         |                 |
|           +-------------------------+-----------------+
|           | Status Bar                                |
+-----------+-------------------------------------------+
```

**狀態列屬於工作台頁面，不是 App Shell 的第三列**（`plan/28`，2026-09-08）。
它的內容（Session 狀態、瀏覽器連線、控制權）只在 Session 工作台有意義；
做成 shell 的第三列，就要在其他十個頁面渲染一條空的 28px，或者讓 shell 知道
當前路由是什麼——後者是讓 App Shell 開始認識業務。

---

Sidebar

208px

Sidebar（收合態）

64px

Inspector

258px

Inspector（可調範圍）

220–360px

Header

56px

Work Head

72px

Work Head（1024–1439px 單列）

48px

Tabs

44px

Status Bar

28px

> **修訂（`plan/28`，2026-09-08）。**
> **Inspector 由 300px 改為 258px 可調 220–360px**：Graphite 風格規格明列，
> 而現況是寫死 300px 且 ≤1100px 直接 `display: none`、**沒有任何開啟入口**。
> 「直接隱藏功能」是共用規範禁止的形狀，768–1023px 改為覆蓋抽屜。
>
> **Status Bar 的 28px 數字不變，但它從 P0 至今沒有被實作過**
> （`tokens.css` 的註解自己寫著「Not in use」）。**自 `plan/28` 起實作**，
> 內容為 Session 狀態／瀏覽器連線／控制權**三者分列**——不合成一個綠色「正常」。
> 三者的組合有實際意義：「Session 執行中 ＋ 已斷線」不等於「Session 已結束」，
> 第一種要按重新連線，第二種按了沒有用。
>
> **Sidebar 維持 208px**（收合態新增 64px）。Graphite 文件寫 216px，
> 但 208 是 `plan/09` LY-05 量過的值，8px 買不到任何東西卻要動三處數字
> 並讓 `GATE-LY` 重新校準——**改文件不改程式**。

---

高度只有一個來源：App Shell 佔滿視窗高度，Main Workspace 是唯一的滾動容器。
頁面不得自行以 `100vh` 推導可用高度。

Session Workspace 這類「頁面本身就是固定版面」的畫面，Main Workspace 改用
`12px 16px` 內距且不整頁滾動——滾動發生在面板內部（Terminal viewport、
Monaco、File Tree）。

---

# 10. Dashboard

採 SaaS Dashboard。

包含：

Node Summary

Session Summary

Health

Runtime

CPU

Memory

Storage

Recent Activity

---

Card

```
+----------------------------+
| Icon     Title             |
|                            |
| Big Number                 |
|                            |
| Trend                      |
+----------------------------+
```

---

# 11. Node Page

左側

Node List

右側

Node Detail

Node Card

```
Node Name

● Online

Ubuntu 24.04

Claude  ✓

Codex ✓

8 Sessions

CPU

Memory

Disk
```

---

# 12. Session Workspace

主要畫面。

```
+----------------------------------------------------------+
| Session Header                                           |
+-------------------------------------+--------------------+
| [ CLI ] [ app.py ]                  | Workspace          |
|                                     |                    |
|  Terminal 或 Preview（擇一佔滿）      | backend            |
|                                     | frontend           |
|                                     | app.py             |
|                                     | README.md          |
+-------------------------------------+--------------------+
| Status Bar                                               |
+----------------------------------------------------------+
```

Terminal

佔最大比例。

選中的面板填滿整個中央工作區的可用高度與寬度，不得在面板內留下未使用的空白。

Tab

選中狀態同時以字重與底線表示，不只用顏色。

---

# 13. Workspace

Tree

與 VSCode 相同。

Icon

Folder

File

Git

Hidden

全部不同。

Hover

使用

Gray-100

Selected

Primary-100

---

# 14. Tables

Header

Gray-100

Row Hover

Gray-50

Selected

Primary-50

不要 Zebra。

---

# 15. Buttons

Primary

Filled

Secondary

Outline

Ghost

Text

Danger

Icon Button

不要超過五種。

---

# 16. Forms

高度

40px

Label

固定在上方。

Error

Label 下方。

Placeholder

Gray-400

---

# 17. Status Badge

Online

Green

Busy

Orange

Offline

Gray

Error

Red

Badge

高度

24px

Radius

999px

> **修訂（`plan/28`，2026-09-08，ADR 0027 §8）。**
> 上面那四行「綠／橘／灰／紅」是這一節原本的全部內容，而它沒有說**綠色疊在什麼底上**。
> 結果是實作只能自己配底色，而 2026-09-08 實測：**八個 badge 配對有六個不到 4.5:1**
> （`online` 3.13、`degraded` 2.63、`error` 3.50、`offline` 3.75、`connected` 4.24、
> `reconnecting` 3.86）。這不是實作偏離規格，是規格沒有規定到。
>
> 修訂後的規則：
>
> 1. **每個狀態是三元組**：`foreground` ／ `background` ／ `border`，每個主題各一組。
>    語意只有五個：`success` / `warning` / `error` / `info` / `neutral`。
> 2. **一律圓點 ＋ 文字 ＋ 1px 邊線。** 邊線不是裝飾：淺色主題的 badge 底色對面板底
>    實測只有 1.07–1.17:1，沒有邊線的話那個膠囊在畫面上是看不見的，只剩文字浮著。
> 3. **狀態永不只用顏色表達**——每個 badge 都帶可讀文字（WCAG 1.4.1）。
>    `warning` 另外強制帶警告圖示。
> 4. **Node 狀態、連線狀態、Session 狀態各自映射到那五個語意，但標籤文字不共用。**
>    現況把三種東西塞進同一個 `data-status`，結果 `exited` 與 `gap` 共用一條 CSS 規則。
> 5. **品牌色不是通用狀態色。** accent 不得兼任 success。

---

# 18. Terminal

使用

xterm.js

背景

純深色。

不要包一層 Card。

Terminal 就是工作區。

Header

僅保留：

Session

Runtime

Workspace

字級

```text
預設 14px，行高 1.2，使用者可調 12–20px（持久化於 localStorage）
```

字體

```text
本機等寬堆疊（ui-monospace, SFMono-Regular, Menlo, Consolas,
"Liberation Mono", monospace）— 不打包 webfont（ADR 0016）
```

> **修訂（`plan/28`，2026-09-08，ADR 0027）。** 這一節原本**沒有字級規定**，
> 實作是 13px。五份風格文件寫「終端預設 14px，行高 1.6」，而 **1.6 不能照字面實作**：
> 1.6 是 UI 內文的慣例值，xterm 的 `lineHeight` 是**乘在量測到的字格高度上**的倍率。
>
> chromium 實測（`scripts/vr/xterm-geometry-probe.mjs`，1440×900 目標幾何、面板 674px）：
>
> | 字級 / 行高 | 字格高度 | 列數 | 判定 |
> |---|---:|---:|---|
> | 13 / 1.0（改動前的實作） | 15px | 44 | 通過 |
> | **14 / 1.2（採用）** | **19px** | **35** | **通過，餘裕 5 列** |
> | 14 / 1.4 | 22px | 30 | 正好壓線，不採用 |
> | 14 / 1.6（文件字面） | 25px | **26** | **跌破** |
>
> `plan/09` 的閘門是 1440×900 下**列數 ≥ 30**，所以 1.6 是硬性衝突而不是偏好問題。
> 1024×768 下 `14/1.2` 只有 28 列，處置是該斷點的工作標頭收成單列
> 並倚賴使用者可調字級（`13/1.2` 在該尺寸給 30 列）。
>
> `"JetBrains Mono"` 從 §22 與實作中刪除：它從來沒有被打包（ADR 0016），
> 所以它一直是一個永遠 fallback 的名字。

ANSI 十六色

```text
由主題表提供（plan/28/02-…md §8），不使用 xterm 的預設調色盤。
預設值裡 blue #3465A4（3.13:1）與 magenta #75507B（2.81:1）對終端底不到 4.5:1，
而 blue 是 `ls` 的目錄色、magenta 是許多 CLI 的提示與 diff 標頭。
black／brBlack 刻意不拉到 4.5:1（語意就是「被弱化的內容」）：
brBlack ≥ 3:1，black 只作為背景使用時不驗前景。
```

---

# 19. File Preview

Monaco Editor

ReadOnly

Dark Theme

與 Terminal 共用深色。

---

# 20. Icon

採

Lucide Icons

不要使用擬真 Icon。

全部 Outline。

---

# 21. Motion

Animation

150~250ms

只使用：

Fade

Slide

Scale

不要：

Bounce

Elastic

Rotate

> **精確化（`plan/28`，2026-09-08）。** 本節的 150~250ms 與共用規範的
> 「切換狀態 120–180ms」不完全重疊，所以把兩者分開講：
>
> - **狀態切換**（hover、選中、focus、展開收合）走 `--motion-fast` 120ms／
>   `--motion-base` 180ms。這是使用者每分鐘會看幾十次的那一類，慢一點就像卡。
> - **進場／退場**（Dialog、抽屜、Toast）可到 250ms，仍在本節範圍內。
> - **`prefers-reduced-motion` 下停用所有非必要動畫。**
> - **終端內容永不套用動畫**：不淡入、不縮放、不打字動畫。重連時保留可讀輸出。
>   終端裡的每一個像素都是遠端程序畫的，加動畫等於替它重新演出一次。

---

# 22. Design Tokens

```yaml
# 修訂（plan/28，2026-09-08，ADR 0027）。
# radius 改為語意名：sm/md/lg 是原始尺標，用它就等於每個元件自己決定
# 「這裡算 md 還是 lg」——那是 74 處引用各自判斷的來源。
radius:
  control: 8 # 按鈕、輸入框
  panel: 8 # 面板、卡片
  dialog: 12 # 對話框
  pill: 999 # 狀態膠囊

spacing:
  xs: 4
  sm: 8
  md: 16
  lg: 24
  xl: 32

# 密度：標準，單一組（plan/28 D3）。
density:
  row: 48 # 表格列
  control: 36 # 表單控制項
  touch: 44 # 觸控目標下限

font:
  # Inter 與 JetBrains Mono 從來沒有被打包（ADR 0016：dist 不含 CDN 參照，
  # MVP 不出貨任何字型檔）。寫在規格裡讓實作以為它們存在，
  # 而 useTerminalSession.ts 就是這樣寫出一個永遠 fallback 的字型名字的。
  body: system-ui, -apple-system, "Segoe UI", Roboto, "Noto Sans TC", sans-serif
  mono: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace

layout:
  header: 56
  sidebar: 208
  sidebar_collapsed: 64
  workhead: 72
  tabs: 44
  inspector: 258 # 可調 220–360（原 300 固定）
  inspector_min: 220
  inspector_max: 360
  statusbar: 28

motion:
  fast: 120 # ms
  base: 180 # ms

terminal:
  # 具體色值見 theme/tokens.css 與 theme/themes.ts；兩份來源由 contract test 綁死。
  # 本節不再複製色值——複製就會漂移。
  background: token(--terminal-background)
  font_size: 14 # 使用者可調 12–20
  line_height: 1.2 # 不是 1.6，見 §18

card:
  radius: 8 # radius.panel
  border: token(--border-subtle)

button:
  radius: 8 # radius.control
```

---

# 23. UI Components

建議元件數約 50 個。

## Navigation

* App Shell
* Header
* Sidebar
* Status Bar
* Breadcrumb
* Tabs
* Command Palette　*（列於此，但從未實作；`plan/28` 亦不做——它是一張獨立的票。
  這一行留著是為了不讓下一個人以為它已經存在。）*

## Dashboard

* Metric Card
* Health Card
* Activity Timeline
* Node Summary

## Node

* Node Card
* Runtime Card
* System Resource Card
* Health Badge

## Session

* Session Card
* Session Header
* Terminal Container
* Session Toolbar

## Workspace

* File Tree
* File Item
* Folder Item
* Search Panel
* Preview Panel

## Forms

* Input
* Password
* Select
* Tree Select
* Checkbox
* Switch
* Radio
* Button
* Icon Button

## Feedback

* Toast
* Dialog
* Confirm
* Empty State
* Loading
* Error View
* Skeleton

## Data

* Table
* Badge
* Tag
* Progress
* Timeline
* Tooltip

---

# 24. Responsive

> **範圍變更（`plan/28`，2026-09-08，ADR 0027）。** 這是本節唯一一次範圍變更，
> 不是精確化。原本寫「Desktop Only（MVP）／不考慮手機／平板僅提供唯讀模式」，
> 但五份風格文件都規定了 <768px 的行為，與本節**直接矛盾**——
> 在解決這個矛盾之前，390×844 的畫面既是交付物又是違規。

基準解析度

```text
1440×900（最佳 1920×1080）
```

## 四段斷點

| 斷點 | 導覽 | 檔案欄 | 工作標頭 | 其他 |
|---|---|---|---|---|
| ≥1440px | 展開 208px（可手動收合） | 258px 可調 | 兩列 72px | 桌面基準 |
| 1024–1439px | **自動收合** 64px（可手動展開為覆蓋層） | 258px 可調 | **單列 48px** | 外距縮減 |
| 768–1023px | 64px | **覆蓋抽屜**，工具列有開啟鈕 | 兩列，路徑可展開 | |
| <768px | **頂部選單**（開啟為覆蓋層） | 覆蓋抽屜 | 單列 ＋ 可展開資訊區 | 主面板單欄 |

三條硬規則：

1. **不將功能直接隱藏。** 現況 ≤1100px 的檔案樹是 `display: none` 而且沒有任何
   開啟入口，那正是共用規範禁止的形狀。窄視窗一律改抽屜並提供可觸及的開啟鈕。
2. **可觸及不等於授權放寬。** 終端輸入的權限**不因裝置尺寸改變**——
   `<768px` 不做「唯讀模式」，那是授權而不是版面。原本「平板僅提供唯讀模式」
   那一句之所以要刪，正是因為它把版面決定寫成了授權決定。
3. **抽屜要有焦點約束與 Esc**，關閉後焦點回到開啟鈕；與 Dialog 共用同一個
   `useFocusTrap`。

1024–1439px 的工作標頭收成單列不是設計偏好而是量出來的：1024×768 的 CLI 面板
只有 542px，`14px/1.2` 只給 28 列；收成單列回收 24px（→ 29 列），
其餘倚賴使用者可調字級（§18）。

---

# 25. 最終視覺定位

這套設計語言應呈現：

**Quiet Intelligence（40%）**

低調、專業、長時間工作舒適。

**Developer Workbench（40%）**

像 IDE 一樣高效率，Terminal 與 Workspace 是主角。

**Modern Industrial（20%）**

透過節點狀態、健康資訊與監控語言，建立企業級設備管理的可靠感。

整體應讓使用者第一眼聯想到的是：

> 一個讓工程團隊可以安心、穩定、高效率管理 AI CLI 與遠端開發節點的專業平台，而不是一個強調 AI 炫技的聊天介面。

