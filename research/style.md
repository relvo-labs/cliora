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

280px

Inspector

360px

Header

56px

Status Bar

28px

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
  sidebar: 280
  inspector: 360
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

