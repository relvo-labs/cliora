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
#377C60
```

## Warning

```text
#93692F
```

## Error

```text
#BE4B4B
```

## Info

```text
#4272A9
```

> **四個值都在 2026-08-28 調暗過（`plan/27` 的 `HD-04`），原值在下表。**
> 這不是換配色，是同一個色相降亮度到可讀——**原來的四個值沒有一個能當小字用**。
>
> | | 原值 | 對白底 | 現值 | 對白底 | 對 Gray-100 |
> |---|---|---:|---|---:|---:|
> | Success | ~~`#3E8C6A`~~ | 4.07 | `#377C60` | **4.98** | 4.60 |
> | Warning | ~~`#C08B3E`~~ | **3.00** | `#93692F` | **4.88** | 4.51 |
> | Error | ~~`#C45C5C`~~ | 4.17 | `#BE4B4B` | **4.89** | 4.51 |
> | Info | ~~`#4A7FB8`~~ | 4.18 | `#4272A9` | **4.99** | 4.60 |
>
> **這一節與同一份文件的〈顏色以外的辨識線索〉互相矛盾了六期。**
> 那一節寫著「一個只靠顏色區分的狀態，對色覺缺陷使用者……不存在」，
> 而這一節提供的四個顏色，**用在 11px／12px 的文字上時對比是 3.00 到 4.18**，
> 全部低於 WCAG 2.2 AA 要求的 4.5:1。也就是說：規範要求不要只靠顏色，
> 而它給的顏色連「看得見」都不保證。
>
> **是 axe 找到的，不是人讀出來的**——`HD-04` 的第一次掃描在八個畫面上
> 報了 16 個 `color-contrast`，追回來全部指向這四個值
> （證據：`artifacts/hd/local/w1/axe-before.json`）。
> 一份被讀了六期的規範文件，它的錯誤要靠工具才發現，
> 這件事本身就是 `plan/27` D125 說「人工 audit 的結論不能回歸」的例子。
>
> **Warning 的變化最大**（`#C08B3E` → `#93692F`，明顯偏褐）。
> 那是必要的代價：3.00 距離 4.5 太遠，任何保住原有明度的做法都到不了。
> 若日後要換一個更亮而仍達標的暖色，那是一次**配色決定**，
> 要連同這張表一起改，而不是只改 `tokens.css`。
>
> 原值**仍可用於大字（≥18pt 或 ≥14pt 粗體）、填色與邊框**——
> WCAG 對那三種用途的門檻是 3:1，四個原值都過。
> 這裡改的是「小字可用的那一組」，而這個系統的狀態文字幾乎都是 11–12px。

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
|           |                         |                 |
|           |                         |                 |
+-----------+-------------------------+-----------------+
| Status Bar                                            |
+-------------------------------------------------------+
```

---

Sidebar

208px

Inspector

300px

Header

56px

Status Bar

28px

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

---

# 22. Design Tokens

## V2 工作語彙

V2 任務層使用下列語意 token（來源：`research/02/12` §2；實作裁決：
`plan/19` D32）。Session 進行中沿用 `--status-online` 綠；Task 進行中使用
`--stage-implementing` 藍；Run 執行中使用 `--run-running` 琥珀並附文字與動態點。
顏色不是唯一線索。

```text
Task stage
--stage-backlog       #8892A0
--stage-blocked       #B4574F
--stage-ready         #4A7C8C
--stage-implementing  #3F6FA8
--stage-verify        #7A5EA8
--stage-done          #2F7A56

Run
--run-queued          #8892A0
--run-running         #C68C37
--run-waiting         #D2691E
--run-succeeded       #2F9B63
--run-failed          #D25454
--run-lost            #A0673F

Risk
--risk-low            #6B7684
--risk-medium         #C68C37
--risk-high           #C45C5C

Evidence source
--source-machine      #2F7A56  (machine_verified, solid)
--source-platform     #4A7C8C  (platform_observed, outline)
--source-agent        #8892A0  (agent_reported, quiet)

Attention（V2-P1，plan/26 PX-17）
--attention-human     = --run-waiting    #D2691E  (1 waiting_for_your_input)
--attention-approval  #6B5B9E                     (2 pending_human_approval)
--attention-failed    = --status-error   #D25454  (3 verification_failed / 4 run_failed)
--attention-warning   = --status-busy    #C68C37  (5 no_eligible_runner / 6 offline / 8 stale)
--attention-blocked   = --stage-blocked  #B4574F  (7 dependency_blocked)

Work lifecycle（--stage-* 的語意別名，不是新色）
--work-backlog        = --stage-backlog
--work-ready          = --stage-ready
--work-progress       = --stage-implementing
--work-review         = --stage-verify
--work-done           = --stage-done
```

八級 attention 只有五個顏色：**由同一個動作解除的兩級共用一個顏色**
（`verification_failed` 與 `run_failed` 都是「去看為什麼壞了」；
`no_eligible_runner`、`assigned_runner_offline` 與 `over_wip_or_stale`
都是「這張卡在退化但沒有人在等」）。第 1 級不另鑄一個橘色——
`--run-waiting` 在 `plan/19` D24 就已經被指定給「有一個人被等著」這個唯一語意，
再造一個相近的橘會把那個語意拆成兩半。

`--work-*` 是別名而不是新色：lifecycle 是 `tasks.stage` 的投影
（`plan/26/03` §1.A），同一張卡不能因為某個畫面用了另一個名字就換顏色。

## 顏色以外的辨識線索（V2-P1，`PX-17`）

**顏色永遠不是唯一線索。** 這一節是規範，不是建議：一個只靠顏色區分的狀態，
對色覺缺陷使用者、對高對比模式、對列印與對截圖後被壓過的縮圖都不存在。

| 元素 | 顏色之外必須另有的線索（**至少兩項**） |
|---|---|
| Attention 徽章 | icon、文字標籤、形狀（實心／外框／左緣色條）——三者取二 |
| Lifecycle 欄頭與 pill | 文字標籤永遠可見；顏色只作為輔助 |
| Run 狀態 | 文字 ＋（執行中時）動態點 |
| Risk | 文字等級，不得只有一個色點 |
| Evidence source | `SourceBadge` 的實心／外框／低調三種形狀已滿足此條 |

具體規則：

1. **每個 attention 徽章都有非空的 `aria-label`**，內容是該級的完整說法
   （「等待你的回覆」而不是「注意」）。`PX-18` 有一支元件測試對八級逐一斷言。
2. **卡片只顯示 primary attention**；同時成立的其他級以「＋N」表示，
   完整清單在 Task Drawer（`plan/26` D107）。「＋N」是文字，不是顏色深淺。
3. **停用態要說出原因。** runtime 訊號不可用時（`plan/26` D92 的相位 B 失效），
   `Blocked` 與 `No runner` 兩個 quick filter 顯示為停用並附一行說明，
   **不得回 0 筆**——0 筆會被讀成「問題解決了」。
4. **不得以顏色深淺表達數量或新舊。** 需要表達程度時用數字或文字。
5. **焦點環用 `--border-focus`，不得被 attention 顏色取代。** 兩者可同時出現。

共用尺度為 `--space-1` … `--space-6`（4、8、12、16、24、32px）、
`--font-xs` … `--font-xl`（11、12、13、15、19、24px），以及系統內建的
`--font-mono` 等寬字堆疊。元件不得猜測 `--font-size-*` 或 `--color-*` 名稱。

```yaml
radius:
  sm: 4
  md: 8
  lg: 12
  xl: 16

spacing:
  xs: 4
  sm: 8
  md: 16
  lg: 24
  xl: 32

font:
  body: Inter
  mono: JetBrains Mono

layout:
  header: 56
  sidebar: 208
  inspector: 300
  statusbar: 28

terminal:
  background: "#0F1115"

card:
  radius: 12
  border: Gray-200

button:
  radius: 8
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
* Command Palette

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

Desktop Only（MVP）

最低解析度

```text
1440×900
```

最佳解析度

```text
1920×1080
```

不考慮手機。

平板僅提供唯讀模式。

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
