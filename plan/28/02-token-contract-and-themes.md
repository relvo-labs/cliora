# 02 — Token 契約與主題（`VR-03`）

本檔是本期的地基。所有頁面票都硬依賴它，順序不能顛倒（`00-…md` D6：
「不得出現字面色值」這條 gate 只有在出口補齊之後才成立）。

## 1. 為什麼需要兩份來源

| 消費者 | 需要什麼 | 能不能吃 `var(--x)` |
|---|---|---|
| Vue 元件的 scoped CSS | custom property | 可以 |
| `xterm` 的 `terminal.options.theme` | **具體色值字串** | **不行** |
| `monaco.editor.defineTheme()` 的 `colors` | **具體色值字串** | **不行** |
| `<meta name="theme-color">`、`color-scheme` | 具體值 | 不行 |

所以 `theme/tokens.css`（CSS 的來源）與 `theme/themes.ts`（JS 的來源）並存，
由 `theme.contract.test.ts` 綁死（§7）。`getComputedStyle` 反查被否決的兩個理由
寫在 `00-…md` D5——其中「在 `display:none` 的面板上拿到空字串」不是理論問題：
CLI 面板正是靠 `v-show` 隱藏的（`SessionWorkspaceView.vue:547`）。

## 2. 語意 token 清單

### 2.1 表面與邊界

| Token（CSS 名） | 用途 | 現有名 | 現有引用數 | 遷移 |
|---|---|---|---:|---|
| `--surface-canvas` | 整體畫布（App Shell 背景） | 同 | 7 | 不動 |
| `--surface-default` | 導覽、面板、卡片 | `--surface-elevated` | 22 | 機械改名 |
| `--surface-raised` | hover、浮層、選單、Toast | `--surface-default` 的一部分 | 31 | **逐處判斷** |
| `--surface-scrim` | Dialog 背後的遮罩 | `ConfirmDialog.vue:42` 的字面 `rgb(15 20 25 / 45%)` | 1 | 收進 token |
| `--border-subtle` | 裝飾分隔線、卡片外框 | `--border-default` 的一部分 | 61 | **逐處判斷** |
| `--border-control` | **必要**控制邊界（輸入框、次要按鈕、Checkbox） | 無 | 0 | 新增（§5.3） |
| `--focus-ring` | 鍵盤焦點外框 | `--border-focus` | 5 | 改名並**換值**（現況 2.85:1 不合格） |

`--border-subtle` 與 `--border-control` 的分家是本期的重點之一：
共用規範寫了「`border.subtle`：裝飾分隔，**不保證適合必要控制邊界**」，
但沒有給替代值。五款的 `border.subtle` 對面板底實測 1.21–1.61:1，**沒有一個到 3:1**（§6.3）。

### 2.2 文字

| Token | 用途 | 現有名 | 引用數 | 遷移 |
|---|---|---|---:|---|
| `--text-primary` | 一般介面文字 | 同 | 10 | 不動 |
| `--text-secondary` | 輔助資訊、次列、時間戳 | `--text-muted` | 90 | 機械改名 |
| `--text-on-accent` | 疊在 `accent` 填色上的文字 | `--text-inverse` | 12 | 改名（語意收窄：它**不是**「反色」，是「疊在強調色上」） |
| `--text-on-terminal` | 疊在 `terminal.background` 上的 UI 文字（分頁、提示列、drop bar） | 無 | 0 | 新增 |
| `--text-disabled` | disabled 控制項的標籤 | `--action-disabled` 兼任 | 2 | 新增（disabled **保留可讀標籤**，不靠透明度） |

現有的 `--text-secondary`（30 處）在新表裡**沒有對應**——它是舊表的中間層。
`VR-03` 逐處判斷：預設落到 `--text-primary`，明顯屬於輔助資訊者落到 `--text-secondary`。
這 30 處要列成清單放進 PR 描述，因為它是本期唯一一批「靠判斷而不是靠規則」的遷移。

### 2.3 強調色與動作

| Token | 用途 |
|---|---|
| `--accent-primary` | **不承載文字的**填色：選中底線、進度、導覽項的 2px 左邊線。<br>**實作修訂**：原本也寫「主按鈕背景」與「疊在 surface 上的文字」，但實測 Porcelain 的 `accent.primary` 疊在 `surface.raised` 上是 **4.20:1**（hover 態的按鈕文字），Studio 白字疊它是 **4.27:1**。規則收成一句：**有文字的地方一律用 `--accent-strong`**。Graphite 兩者同值，所以這條在預設主題上看不出來、在 Porcelain 上是必要的 |
| `--accent-strong` | 疊在 `--accent-subtle` 上的文字、以及主按鈕的背景（淺色主題） |
| `--accent-subtle` | 低強度選取底（導覽選中、分頁選中、表格列選中） |
| `--accent-hover` | 主按鈕 hover 的背景 |
| `--danger-bg` / `--danger-fg` / `--danger-hover` | 危險動作按鈕。**與 `status.error` 分開**：一個是動作，一個是狀態 |

`--accent-strong` 是本期新增的，它的存在理由是一個實測失敗（§6.4、`01-…md` C1）。

### 2.4 狀態（每個狀態三個值）

`success` / `warning` / `error` / `info` / `neutral`，各有 `-fg` / `-bg` / `-border`，共 15 個 token。

規則（`00-…md` D8）：

- 狀態一律**圓點 ＋ 文字 ＋ 1px 邊線**。淺色主題的 `-bg` 對面板底實測只有 1.07–1.17:1，
  沒有邊線的話那個膠囊在畫面上是看不見的（§6.2）。
- `warning` 另外強制帶警告圖示——Studio 的品牌橘與 warning 是近鄰，
  而其他主題也不該讓「顏色」單獨承擔語意。
- Node 狀態（`online`／`offline`／`degraded`／`disabled`／`error`）與
  連線狀態（`connected`／`reconnecting`／`gap`）與 Session 狀態各自映射到這五個語意，
  **但標籤文字不共用**——`StatusBadge` 現在把三種東西塞進同一個 `data-status`，
  結果是 `exited` 與 `gap` 共用一條 CSS 規則（`StatusBadge.vue:37-40`）。

### 2.5 終端與編輯器

| Token | 用途 |
|---|---|
| `--terminal-background` | 終端與唯讀預覽的底 |
| `--terminal-foreground` | 終端一般文字 |
| `--terminal-input` | 使用者輸入的字（規格：`#E4EEEB`） |
| `--terminal-cursor` | 游標 |
| `--terminal-selection` | 選取（半透明） |
| `--terminal-ansi-{black…brWhite}` | ANSI 十六色（§8） |

**這一組在兩款主題下是同一份值。** Porcelain 的終端不變白——共用規範明文：
「終端內的文字、游標與搜尋不得繼承淺色外框的深色文字」。
Porcelain 需要的是 `--text-on-terminal`（分頁、提示列這些疊在終端底上的 **UI** 文字），
不是把終端本身改成淺色。

### 2.6 幾何與動態

| Token | 值 | 備註 |
|---|---|---|
| `--layout-header` | 56px | 不變 |
| `--layout-sidebar` | 208px | 不變（`00-…md` D4） |
| `--layout-sidebar-collapsed` | 64px | 新增 |
| `--layout-workhead` | 72px | 新增 |
| `--layout-tabs` | 44px | 新增（現況由內容決定） |
| `--layout-status` | 28px | 已存在但從未使用；本期實作 |
| `--layout-inspector` | 258px | 由 300px 改（`00-…md` D15） |
| `--layout-inspector-min` / `-max` | 220px / 360px | 新增 |
| `--density-row` | 48px | 表格列 |
| `--density-control` | 36px | 表單控制項 |
| `--density-touch` | 44px | 觸控目標下限 |
| `--radius-control` | 8px | 按鈕、輸入框 |
| `--radius-panel` | 8px | 面板、卡片 |
| `--radius-dialog` | 12px | 對話框 |
| `--radius-pill` | 999px | 狀態膠囊 |
| `--motion-fast` / `--motion-base` | 120ms / 180ms | 共用規範「切換狀態 120–180ms」 |
| `--shadow-overlay` | 每主題一值 | **只用於真正浮在內容上的元件** |

`--radius-sm/md/lg`（74 處引用）由上面四個語意名取代。理由與顏色相同：
`sm/md/lg` 是原始尺標，用它就等於每個元件自己決定「這裡算 md 還是 lg」。

## 3. Graphite（預設，深色）

| Token | 值 |
|---|---|
| `--surface-canvas` | `#111518` |
| `--surface-default` | `#191E22` |
| `--surface-raised` | `#20272C` |
| `--surface-scrim` | `#00000099` |
| `--border-subtle` | `#2B3339` |
| `--border-control` | `#606C73` |
| `--focus-ring` | `#81C9B9` |
| `--text-primary` | `#E4E9EB` |
| `--text-secondary` | `#8E9AA3` |
| `--text-on-accent` | `#111518` |
| `--text-on-terminal` | `#C9D3D8` |
| `--text-disabled` | `#6E7A82` |
| `--accent-primary` | `#81C9B9` |
| `--accent-strong` | `#81C9B9` |
| `--accent-subtle` | `#233A36` |
| `--accent-hover` | `#93D3C4` |
| `--danger-bg` | `#F08C8C` |
| `--danger-fg` | `#111518` |
| `--status-success-fg` / `-bg` / `-border` | `#6FC79B` / `#17302A` / `#2E5648` |
| `--status-warning-fg` / `-bg` / `-border` | `#E0AE5E` / `#332918` / `#5A4A2B` |
| `--status-error-fg` / `-bg` / `-border` | `#F08C8C` / `#3A2020` / `#603A3A` |
| `--status-info-fg` / `-bg` / `-border` | `#8CB6E8` / `#182B3D` / `#31485F` |
| `--status-neutral-fg` / `-bg` / `-border` | `#A6B0B8` / `#262B30` / `#434A50` |
| `--shadow-overlay` | `0 12px 32px #00000066` |

## 4. Porcelain（淺色）

| Token | 值 | 與原型的差別 |
|---|---|---|
| `--surface-canvas` | `#F9FAFC` | — |
| `--surface-default` | `#FFFFFF` | — |
| `--surface-raised` | `#EEF2F7` | — |
| `--surface-scrim` | `#25313C73` | — |
| `--border-subtle` | `#E0E5EB` | — |
| `--border-control` | `#858F9B` | **新增**（原型沒有這一層） |
| `--focus-ring` | `#286BF0` | — |
| `--text-primary` | `#25313C` | — |
| `--text-secondary` | `#5E6B78` | **改**（原型 `#77828D` 實測 3.92:1，不合格） |
| `--text-on-accent` | `#FFFFFF` | 明確定義，不由 canvas 推導 |
| `--text-on-terminal` | `#C9D3D8` | **新增**：疊在深色終端上的 UI 文字 |
| `--text-disabled` | `#8B95A1` | 新增 |
| `--accent-primary` | `#286BF0` | — |
| `--accent-strong` | `#1B54C4` | **新增**（`#286BF0` 疊在 `accent-subtle` 上實測 4.13:1，不合格） |
| `--accent-subtle` | `#E9F0FF` | — |
| `--accent-hover` | `#1B54C4` | — |
| `--danger-bg` | `#B03434` | **改**（`#C45C5C` 配白字實測 4.17:1，不合格） |
| `--danger-fg` | `#FFFFFF` | — |
| `--status-success-fg` / `-bg` / `-border` | `#1F7A54` / `#E4F3EA` / `#B8DCC8` |
| `--status-warning-fg` / `-bg` / `-border` | `#7E5712` / `#FAF0DC` / `#E0C68C` |
| `--status-error-fg` / `-bg` / `-border` | `#B03434` / `#FBE9E9` / `#E8B8B8` |
| `--status-info-fg` / `-bg` / `-border` | `#1F5C96` / `#E8F0FA` / `#B6CDE6` |
| `--status-neutral-fg` / `-bg` / `-border` | `#5E6B78` / `#EEF1F4` / `#CBD3DA` |
| `--shadow-overlay` | `0 8px 28px #25313C1F` | 原型值 |

終端相關 token 兩款相同：
`--terminal-background: #101416`、`--terminal-foreground: #C9D3D8`、
`--terminal-input: #E4EEEB`、`--terminal-cursor: #FFFFFF`、`--terminal-selection: #78AAFF40`。

## 5. 三個新 token 的推導

### 5.1 `--accent-strong`

問題：五份設計文件的對比表只驗了三組配對，漏掉「`accent.primary` 文字疊在 `accent.subtle` 底上」
——而那正是導覽選中態與分頁選中態的配對。

| 主題 | `accent.primary` ／ `accent.subtle` | 判定 | `accent.strong` | 實測 |
|---|---:|---|---|---:|
| Graphite | 6.35:1 | 通過 | 同 `accent.primary` | 6.35:1 |
| **Porcelain** | **4.13:1** | **不通過** | `#1B54C4` | **5.90:1** |
| Midnight | 6.50:1 | 通過 | 同 `accent.primary` | 6.50:1 |
| Studio | **3.37:1** | **不通過** | `#984D2E` | **4.83:1** |
| Industrial | 6.97:1 | 通過 | 同 `accent.primary` | 6.97:1 |

`--accent-strong` 同時也是 Porcelain 主按鈕的背景：白字疊 `#1B54C4` 實測 **6.75:1**，
比原型的 `#286BF0`（4.72:1）多出一整個等級的餘裕。

### 5.2 `--focus-ring`

要求：對**相鄰的每一個**表面 ≥ 3:1，包含深色終端（工作台的 drop bar 就在終端底上）。

| 主題 | 值 | vs default | vs canvas | vs raised | vs terminal | vs accent.subtle |
|---|---|---:|---:|---:|---:|---:|
| Graphite | `#81C9B9` | 8.79 | 9.60 | 7.92 | 9.69 | 6.35 |
| Porcelain | `#286BF0` | 4.72 | 4.52 | 4.20 | **3.93** | 4.13 |

Porcelain 最緊的一格是終端底上的 3.93:1，仍然過。
**現況 `--border-focus: #67a2ae` 對面板底是 2.85:1、對畫布是 2.64:1——兩個都不過。**

### 5.3 `--border-control`

要求：對 `surface.default` 與 `surface.canvas` **兩者**都 ≥ 3:1（輸入框會出現在兩種底上）。

| 主題 | 值 | vs default | vs canvas |
|---|---|---:|---:|
| Graphite | `#606C73` | 3.11 | 3.40 |
| Porcelain | `#858F9B` | 3.28 | 3.14 |
| Midnight | `#617596` | 3.58 | 3.97 |
| Studio | `#8E8476` | 3.46 | 3.26 |
| Industrial | `#707477` | 3.66 | 3.92 |

對照：現況 `--border-default: #d7dde4` 對面板底是 **1.37:1**。

## 6. 實測對比表

計算方法：sRGB 各通道線性化後取相對亮度 `0.2126R + 0.7152G + 0.0722B`，
比值 `(L_hi + 0.05) / (L_lo + 0.05)`。**不含**透明度疊加、字型渲染與狀態疊層——
半透明的 `--terminal-selection` 與 `--surface-scrim` 不在此表，它們由瀏覽器實測（`06-…md` §2.4）。

### 6.1 現況基線（本期要修的東西）

| 配對 | 位置 | 實測 | 目標 | 判定 |
|---|---|---:|---|---|
| `--border-focus` ／ `--surface-elevated` | 全站焦點環 | 2.85 | 3.0 | **不通過** |
| `--border-focus` ／ `--surface-canvas` | 全站焦點環 | 2.64 | 3.0 | **不通過** |
| `--text-inverse` ／ `--status-error` | Terminate 確認鈕 | 4.09 | 4.5 | **不通過** |
| `--border-default` ／ `--surface-elevated` | 所有輸入框邊界 | 1.37 | 3.0 | **不通過** |
| `--action-disabled` ／ `--surface-elevated` | disabled 控制項 | 1.90 | 3.0 | **不通過** |
| badge `online` `#2f9b63`／`#e8f5ee` | `StatusBadge.vue:44` | 3.13 | 4.5 | **不通過** |
| badge `degraded` `#c68c37`／`#fbf2e4` | `:48` | 2.63 | 4.5 | **不通過** |
| badge `error` `#d25454`／`#f9eaea` | `:61` | 3.50 | 4.5 | **不通過** |
| badge `offline` `#727b87`／`#eef0f2` | `:52` | 3.75 | 4.5 | **不通過** |
| badge `connected` `#2f815b`／`#e8f5ee` | `:29` | 4.24 | 4.5 | **不通過** |
| badge `reconnecting` `#a56f28`／`#fbf2e4` | `:33` | 3.86 | 4.5 | **不通過** |
| badge `exited/gap` `#b34242`／`#f9eaea` | `:38` | 4.76 | 4.5 | 通過 |
| `--text-primary` ／ `--surface-elevated` | 一般文字 | 16.60 | 4.5 | 通過 |
| `--text-muted` ／ `--surface-canvas` | 輔助文字 | 4.64 | 4.5 | 通過 |
| `--text-inverse` ／ `--action-primary` | 主按鈕 | 7.86 | 4.5 | 通過 |

八個 badge 有六個不通過。這不是巧合——`style.md §17` 只寫了「Online Green」，
沒有寫「綠字疊在什麼底上」，所以實作只能自己配（`01-…md` M4 修訂這一條）。

### 6.2 狀態三元組（本期值）

| 狀態 | Graphite fg／bg | Porcelain fg／bg | bg vs 面板底（G／P） |
|---|---:|---:|---:|
| success | 6.91 | 4.61 | 1.19 ／ 1.15 |
| warning | 7.06 | 5.70 | 1.18 ／ 1.13 |
| error | 6.28 | 5.30 | 1.13 ／ 1.17 |
| info | 6.87 | 6.03 | 1.15 ／ 1.15 |
| neutral | 6.48 | 4.81 | 1.18 ／ 1.13 |

右欄就是 D8 要求 1px 邊線的原因：膠囊底對面板底只有 1.13–1.19:1，
**它本身在畫面上幾乎看不見**。邊線走 `-border` 那一格。

### 6.3 `border.subtle` 為什麼不能當控制邊界

| 主題 | `border.subtle` ／ `surface.default` | ／ `surface.canvas` |
|---|---:|---:|
| Graphite | 1.31 | 1.43 |
| Porcelain | 1.27 | 1.21 |
| Midnight | 1.39 | 1.54 |
| Studio | 1.34 | 1.26 |
| Industrial | 1.50 | 1.61 |

五款沒有一款到 3:1。

### 6.4 本期兩款主題的完整驗收清單

`theme.contrast.test.ts` 至少要涵蓋以下配對 × 2 主題。清單由**元件契約**產生
（`04-…md` 每個元件宣告它用到的配對），不是由 token 表產生——
五份設計文件正是因為從 token 表出發才漏掉 `accent/tint`（`00-…md` §7 最後一列）。

一般文字目標 4.5:1：
`text-primary/default`、`text-primary/canvas`、`text-primary/raised`、
`text-secondary/default`、`text-secondary/canvas`、`text-secondary/raised`、
`text-on-accent/accent-primary`、`text-on-accent/accent-hover`、
`accent-strong/accent-subtle`、`accent-primary/default`、
`danger-fg/danger-bg`、
`status-{success,warning,error,info,neutral}-fg` ／各自的 `-bg`、
`text-on-terminal/terminal-background`、`terminal-foreground/terminal-background`。

非文字目標 3:1：
`border-control/default`、`border-control/canvas`、**`border-control/raised`**、
`focus-ring/default`、`focus-ring/canvas`、`focus-ring/raised`、
`focus-ring/terminal-background`、`focus-ring/accent-subtle`、
`text-disabled/default`、**`text-disabled/canvas`**、**`text-disabled/raised`**、
**`border-on-terminal-control/terminal-background`**。

> **實作時的兩處修訂（2026-09-08，完整理由與數字在 `07-…md`「與計畫不同的六處」）：**
>
> **一、`border-control` 與 `text-disabled` 的驗收面從兩個表面擴為三個。**
> 上面粗體的三格是新增的。D9 只點名 `surface.default` 與 `surface.canvas`，
> 但**對話框與選單是 `surface.raised`，而它們裡面有輸入框**
> （`NewSessionDialog` 一個對話框裡有四個 Field）。計畫給的值在那個表面上是
> 2.80（Graphite）／2.92（Porcelain）。改的是值不是目標：
> `--border-control` 現在是 Graphite `#647784`（3.75／4.09／3.25）、
> Porcelain `#838689`（3.66／3.51／3.26）。
>
> **二、`status-*-border` ／ `-bg` 從這份清單移出。** 原本列在這裡，但**五款主題
> 沒有一個達到 3:1**——實測 1.30–1.70。這是目標寫錯而不是值不夠：邊線不承載語意
> （語意在文字上，≥ 4.5:1，圓點再說一次），而 WCAG 1.4.11 管的是「識別元件與狀態
> 所必需的視覺資訊」。硬拉到 3:1 會讓每個 badge 變成中間色調的描邊晶片，
> 與 `style.md` 的「平面、低對比邊界」和 Graphite §9 的「正常狀態不要比正在工作的
> 內容醒目」直接衝突。
>
> 改成的斷言有兩條，兩條都會因為真正的退化變紅：邊線對自己的填色 ≥ 1.25
> （邊線等於填色是 1.0，過不了），**且**邊線對面板底比填色對面板底更強——
> 邊線必須是這個膠囊最強的一條邊，而那正是 D8 要它存在的理由。
> **這是本期第二處明確縮減驗收目標的地方**，第一處是 ANSI 的 `black`／`brBlack`（§8）。
>
> 另外新增四個 on-terminal token（`--text-on-terminal-dim`、`--border-on-terminal`、
> `--border-on-terminal-control`、`--surface-on-terminal`）：終端是自己的表面，
> 上面真的有 UI（分頁列、投放列、捲動提示、`PreviewDenied`），而 69 處字面色值裡
> 有 9 處就是因為表裡少了這一層才長出來的。`--border-on-terminal` 是裝飾級，
> 測試**斷言它低於 3:1**——它是提示文字的外框，超過控制門檻就會跟終端輸出爭注意力。

## 7. `themes.ts` ↔ `tokens.css` 的綁定

```
theme/
  tokens.css              ← CSS 的來源。:root 是 Graphite，:root[data-theme="porcelain"] 覆蓋
  themes.ts               ← JS 的來源。THEMES: Record<ThemeId, Record<TokenName, string>>
  themes.test.ts          ← 每個主題定義了每一個 token（不得缺、不得多）
  theme.contract.test.ts  ← 解析 tokens.css 的文字，逐鍵比對 THEMES
  theme.contrast.test.ts  ← §6.4 的配對清單
```

`theme.contract.test.ts` 的形狀（不是實作，是契約）：

1. 讀 `tokens.css` 原始文字。
2. 以正規式抽出 `:root { … }` 與每個 `:root[data-theme="…"] { … }` 區塊的
   `--name: value;`，正規化大小寫與空白。
3. 對每個主題：`THEMES[id]` 的鍵集合 **等於** CSS 的鍵集合（`toEqual`，不是 `toContain`），
   且每一個值字串相同。
4. 額外斷言：**沒有任何一個 token 的值是 `var(…)`**。
   共用規範「不用鏈式 fallback 掩蓋缺漏」在這裡變成一條會變紅的測試。

第 3 點用 `toEqual` 而不是 `toContain` 是刻意的：漏定義一個 token 的症狀是
「某個主題下那一塊沿用了上一個主題的顏色」，而那在截圖審查裡看起來只是「有點怪」。

## 8. xterm 主題橋與 ANSI 十六色

現況 `useTerminalSession.ts:218-223` 只定義四個鍵（background／foreground／
selectionBackground／cursor），**ANSI 十六色全部落在 xterm 的預設值**。
那組預設值對 `#101416` 的實測：

| | 預設值 | 實測 | | 預設值 | 實測 |
|---|---|---:|---|---|---:|
| black | `#2e3436` | 1.46 | brBlack | `#555753` | 2.54 |
| red | `#cc0000` | 3.15 | brRed | `#ef2929` | 4.43 |
| green | `#4e9a06` | 5.25 | brGreen | `#8ae234` | 11.47 |
| yellow | `#c4a000` | 7.39 | brYellow | `#fce94f` | 14.91 |
| blue | `#3465a4` | **3.13** | brBlue | `#729fcf` | 6.68 |
| magenta | `#75507b` | **2.81** | brMagenta | `#ad7fa8` | 5.63 |
| cyan | `#06989a` | 5.26 | brCyan | `#34e2e2` | 11.58 |
| white | `#d3d7cf` | 12.69 | brWhite | `#eeeeec` | 15.94 |

`blue` 3.13 與 `magenta` 2.81 是實際會痛的兩個：`ls` 的目錄色是 blue，
而許多 CLI 的提示與 diff 標頭用 magenta。

### 提案值（兩款主題共用，底色 `#101416`）

| | 值 | 實測 | | 值 | 實測 |
|---|---|---:|---|---|---:|
| black | `#3A4145` | 1.78 | brBlack | `#6B7478` | 3.88 |
| red | `#E8807F` | 6.90 | brRed | `#F09B9A` | 8.70 |
| green | `#8FCB9B` | 9.86 | brGreen | `#A8DCB2` | 11.95 |
| yellow | `#DFBE72` | 10.36 | brYellow | `#EDD08C` | 12.35 |
| blue | `#8FB6E8` | 8.84 | brBlue | `#A9CAF2` | 10.95 |
| magenta | `#C3A0DC` | 8.28 | brMagenta | `#D5B8E8` | 10.45 |
| cyan | `#79C6C9` | 9.47 | brCyan | `#96DADC` | 11.78 |
| white | `#C9D3D8` | 12.17 | brWhite | `#E8EEF0` | 15.81 |

**`black` 與 `brBlack` 刻意不拉到 4.5:1。** 它們的語意就是「被弱化的內容」
（註解、次要提示、`--dim`），拉到一般文字的水準等於取消那個語意。
驗收目標對這兩格改為：`brBlack` ≥ 3:1（3.88 通過），`black` 只作為背景使用時不驗前景。
這是本期唯一一處明確**縮減**驗收目標的地方，寫在這裡而不是藏在測試裡。

### 風險與實測

覆寫 ANSI 調色盤會改變 Claude／Codex 原生畫面的實際顏色。
專案的約束是「保留原生終端**語意**」（不攔截、不替代），不是「不得換色」——
終端換色是終端一向就有的能力。但這仍然要**看過真的畫面**：
`VR-01` 第 5 項要在真實 Claude 與 Codex 的審批畫面、diff 輸出與進度指示上比對十六色，
若任一畫面變得難辨識，就退回 xterm 預設並**只覆寫 `blue` 與 `magenta` 兩格**
（那兩格是唯一低於 3:1 且真的會被當前景用的）。

### 換主題的動作

```
terminal.options.theme = THEMES[id].xterm     // 不是 new Terminal()
```

`useTerminalSession` 新增一個 `applyTheme(id)`，socket、fit、writer gate 一行不動
（`00-…md` D14）。`VR-01` 第 2 項要實測這條路徑**不會**清空 buffer。

## 9. Monaco 主題橋

`monaco/setup.ts` 的 `defineTheme()` 目前寫死十個色值。改為：

- 兩個主題各 `defineTheme("cliora-graphite" | "cliora-porcelain")`，
  `colors` 全部取自 `THEMES[id]`。
- 切換以 `monaco.editor.setTheme(name)`——它是全域的，**不需要重建 editor 或 model**，
  所以捲動位置與 folding 狀態都保留。
- `base` 兩款都是 `"vs-dark"`：Porcelain 的**預覽仍然是深色**（`style.md §19`
  「與 Terminal 共用深色」，共用規範同意）。淺色主題下改成淺色編輯器會讓
  同一個工作台裡出現兩種程式碼底色。
- contribution 與語言註冊清單一行不動（ADR 0015、`00-…md` §1 不得弄壞第 4 項）。

## 10. 主題套用與 FOUC

```html
<!-- index.html <head>，在任何 stylesheet 之前 -->
<script src="/theme-boot.js"></script>
```

```js
// public/theme-boot.js — 8 行以內，不 import 任何東西
(function () {
  try {
    var t = localStorage.getItem("cliora-theme");
    if (t === "graphite" || t === "porcelain") {
      document.documentElement.setAttribute("data-theme", t);
    }
  } catch (e) {}
})();
```

- **為什麼是外部檔**：CSP 是 `script-src 'self'`，沒有 `'unsafe-inline'`
  （`deploy/nginx/nginx.conf:134`、`deploy/railway/nginx.conf.template:114`）。
  內嵌 script 會被瀏覽器擋掉，而症狀是「主題偶爾不生效」。
- **為什麼放 `public/`**：不要被 Vite 加 hash，`index.html` 才能寫死路徑。
- **為什麼不放 `main.ts`**：那是 defer module，CSS 已經上色之後才跑，
  使用者的明示選擇與 OS 偏好不同時會閃一次。
- **首次造訪（沒有 `localStorage`）**：不設 `data-theme`，由 CSS 的
  `@media (prefers-color-scheme: light)` 在 `:root` 上套 Porcelain 的覆寫。
  四條規則涵蓋四種情況，**沒有一種靠繼承猜**：

  | 情況 | 規則 |
  |---|---|
  | 沒選過、OS 深色 | `:root`（Graphite） |
  | 沒選過、OS 淺色 | `@media (prefers-color-scheme: light) { :root:not([data-theme]) { … } }` |
  | 選了 Graphite | `:root[data-theme="graphite"]` |
  | 選了 Porcelain | `:root[data-theme="porcelain"]` |

- `color-scheme` 與 `<meta name="theme-color">` 一併跟著主題設定，
  否則捲軸與行動裝置的網址列會用錯配色。
- `VR-01` 第 3 項要量 FOUC：以 Playwright 在 `domcontentloaded` 前後各截一張，
  斷言背景色沒有變過。

## 11. 遷移清單（`VR-03` 的實際工作量）

| 動作 | 數量 | 方式 |
|---|---:|---|
| `--text-muted` → `--text-secondary` | 90 | codemod |
| `--border-default` → `--border-subtle` 或 `--border-control` | 61 | **逐處判斷**（控制項用 control，其餘 subtle） |
| `--radius-sm/md/lg` → 四個語意名 | 74 | codemod ＋ 少量判斷 |
| `--action-primary` → `--accent-primary` | 41 | codemod |
| `--status-error` → `--status-error-fg` 或 `--danger-bg` | 38 | **逐處判斷**（狀態 vs 動作） |
| `--surface-default` → `--surface-default` 或 `--surface-raised` | 31 | **逐處判斷** |
| 現有 `--text-secondary` → primary 或 secondary | 30 | **逐處判斷**，清單進 PR |
| `--surface-elevated` → `--surface-default` | 22 | codemod |
| `--text-inverse` → `--text-on-accent` | 12 | codemod |
| `--status-busy` → `--status-warning-fg` | 12 | codemod |
| 字面色值收進 token | 69 | 逐處，13 個檔案 |
| **合計引用點** | **約 480** | |

`GATE-VR-NO-LEGACY-TOKEN`（`06-…md` §1）擋住舊名回來：
`--surface-elevated`、`--text-muted`、`--text-inverse`、`--border-default`、
`--border-focus`、`--action-primary*`、`--action-disabled`、`--status-{online,offline,busy}`、
`--radius-{sm,md,lg}` 在 `frontend/src` 出現即失敗。
