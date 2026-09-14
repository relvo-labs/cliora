# 07 — 行動專用明亮的契約落實（`MS-18`～`MS-21`）

對應 **theme owner** 寫入集。依賴 `MS-D-04`～`MS-D-07` 核准（需 ADR 0027 修訂或新 ADR）。
#62 已核准「行動固定明亮、桌面政策不變」的**方向**；本文件只處理**機制**，不重開方向。

## 0. 兩個 addendum 沒有點名的技術後果

`01-mobile-addendum-v0.1.md` §6 說「行動 xterm／preview／工具列／拒絕／警告／錯誤維持明亮」。
讀了實際的 `theme/themes.ts` 之後，有兩件事必須先寫下來，否則 M0 會在不知道成本的情況下核准：

### 0.1 ANSI 調色盤目前只有一套，而且是為深底調的

```
themes.ts:357  TERMINAL_ANSI = { black: #3A4145 … white: #C9D3D8 … brWhite: #E8EEF0 }
               「One ANSI set for every theme, verified against all five terminal backgrounds.」
```

那五個背景**全部是深色**——包含 Porcelain，因為 Porcelain 的 `--terminal-background` 仍是 `#101416`。
把終端背景換成近白之後，`brWhite #E8EEF0`（對白底 1.06:1）、`white #C9D3D8`、`brGreen #A8DCB2`
這幾個**幾乎不可見**。

實測現況（以 `theme/contrast.ts` 的 `contrastRatio` 計算，對各主題自己的 `terminal-background`）：

| | graphite | porcelain | midnight | studio | industrial |
|---|---:|---:|---:|---:|---:|
| `black` | 1.78 | 1.78 | 1.79 | 1.50 | 1.81 |
| `brBlack` | 3.88 | 3.88 | 3.89 | 3.25 | 3.93 |
| 其餘 14 色 | 5.79 ～ 16.02，**全部 ≥4.5** | | | | |

也就是說，現行調色盤其實已經隱含一條規則：**16 色裡有 14 色是「可讀」的，
另外 2 色（`black`、`brBlack`）是刻意壓暗的「靠近背景」那一端**——
`themes.ts:358` 的註解 `black/brBlack are deliberately dim` 說的正是這件事。
明亮版要做的不是發明新規則，是把這條規則**鏡像**過去。

### 0.1.1 順帶發現：ANSI 16 色從來沒有被對比測試涵蓋過

`theme/contrast.ts` 的 `PAIRS` 只宣告了四組終端相關的配對
（`terminal-foreground`／`terminal-input`／`text-on-terminal`／`text-on-terminal-dim` 對 `terminal-background`）。
**`TERMINAL_ANSI` 的 16 個值，一個都不在 `PAIRS` 裡。**

所以 `themes.ts:357` 那句「verified against all five terminal backgrounds」是**人工審查的結論，不是測試保障的**。
今天沒出事，是因為那 16 個值從 plan/28 之後沒有人動過。新增一個明亮主題正是第一個會動到它的情境。

這一項不是 pocket 造成的，但 pocket 讓它變成必須修：見 `MS-19` 的第一條。

### 0.2 Monaco 每個主題都硬編 `base: "vs-dark"`

```
monaco/setup.ts:110  base: "vs-dark",   // 「for every theme, including the light ones」
```

註解寫得很清楚，而且理由是對的（style.md §19：預覽與終端共用深底，一個工作台不該有兩種程式碼背景）。
**pocket 讓那個理由反過來仍然成立**：pocket 的終端是明亮的，所以預覽也必須明亮，兩者仍是同一個背景。

`defineThemes()` 必須依主題分支 `base`（pocket 用 `"vs"`），且 `monaco/setup.ts` 的那段註解必須同步改寫——
留著一段說「每個主題都用 vs-dark」的註解而程式已經不是那樣，是下一個人會相信的錯誤文件。

## 1. 明亮終端調色盤：規則與實測提案

本節是 `MS-OM-04` 的算術部分。**算術做完了，渲染還沒做**——
底下每個值都通過了 `contrast.ts` 的計算，但沒有一個經過真實 xterm 渲染或真實 CLI 輸出，
那是 `MSP-R-009` 的事，不得以本節代替。

### 1.1 四條規則

**R1 — 灰梯維持單調，只有「靠近背景」的那一端換邊。**
`black < brBlack < white < brWhite` 的明度順序在任何主題都不變。
深色底時失去對比的是暗端（`black` 1.78、`brBlack` 3.88）；
明亮底時失去對比的就是亮端（`white`、`brWhite`）。**恰好兩個，與深色主題同數量。**

這條規則排除了一個看似聰明、實際會壞事的做法：把 `black` 映射成淺灰、`white` 映射成深灰
（讓兩端都「可讀」）。那會讓調色盤的明度語意反過來——CLI 寫 `\e[30;47m`（黑字白底）
是成對授權的，反轉後會渲染成亮字暗底，**視覺上整塊反白**。
那不是對比問題，是正確性問題。

**R2 — 12 個彩色全部 ≥4.5:1。**
彩色是 CLI 輸出真正承載意義的部分（錯誤紅、成功綠、diff）。沒有例外，沒有豁免。

**R3 — bright 在明亮版是「更深更飽和」，不是「更亮」。**
這是 pocket 唯一一處**刻意不鏡像**的地方，理由要寫明白：
對 4 個灰色來說，`bright` 指的是梯子上的位置（所以維持更亮）；
對 12 個彩色來說，`bright` 在 CLI 的實際用途是**強調**。
深色底上「更亮」＝更高對比＝更強調；明亮底上「更亮」會變成更低對比＝更弱，
把作者想強調的那一段變成最難讀的那一段。所以彩色的 bright 往深走。
同色相的 bright 必須比 normal **更遠離終端表面**（對比之比 ≥1.15），否則強調等於沒發生。

> **實作時修正過一次**：規則原本寫成「normal 與 bright 互相可分辨 ≥1.3:1」，
> 而那個門檻讓**現行五個深色主題全部變紅**（實測 1.19–1.26）。
> 那些調色盤已經審過也在線上，`#E8807F` 與 `#F09B9A` 明明是兩個紅——所以錯的是門檻不是值。
> 改成「對比之比」還有第二個好處：`contrastRatio(normal, bright)` 是對稱的，
> 對一個**更靠近**背景的 bright 一樣會放行；相除才問得出方向。
> 門檻 1.15 取自實測下限（深色最小 1.19、pocket 最小 1.41）。

**R4 — `black` 與 `brBlack` 在明亮版必須是可讀的深色。**
這是 R1 的直接結果，也是 `\e[30m`（黑字）在明亮終端上唯一合理的解釋。

### 1.2 實測提案值

終端背景取 `#ffffff`：明亮工作台裡「正在讀的東西應該是最亮的」，
終端是中央面板，所以它拿「紙」的角色，canvas 用近白往後退。

四階灰梯（對比值刻意鏡像 graphite 的 1.78／3.88／12.17／15.81）：

| | 值 | 對 `#ffffff` | 角色 |
|---|---|---:|---|
| `black` | `#22282d` | 14.90 | 可讀 |
| `brBlack` | `#39424a` | 10.23 | 可讀 |
| `white` | `#7d8790` | 3.66 | **dim 端** |
| `brWhite` | `#c2c8ce` | 1.69 | **dim 端** |

12 個彩色：

| 色相 | normal | 對比 | bright | 對比 | 強調倍率 |
|---|---|---:|---|---:|---:|
| red | `#b62b2b` | 6.23 | `#8f1f1f` | 8.81 | 1.41 |
| green | `#1f7a45` | 5.35 | `#155c33` | 8.04 | 1.50 |
| yellow | `#7a5a12` | 6.37 | `#5c430d` | 9.28 | 1.46 |
| blue | `#1f5fd0` | 5.82 | `#16469c` | 8.79 | 1.51 |
| magenta | `#9333a8` | 6.40 | `#72237f` | 9.28 | 1.45 |
| cyan | `#0f6f77` | 5.90 | `#0a5359` | 8.77 | 1.49 |

終端相關 token（沿用 `contrast.ts` 既有的 `PAIRS` 門檻，未新增寬鬆例外）：

| token | 值 | 配對 | 實測 | 門檻 |
|---|---|---|---:|---|
| `terminal-background` | `#ffffff` | — | — | — |
| `terminal-foreground` | `#2b333b` | 對 bg | 12.81 | ≥4.5 |
| `terminal-input` | `#10161b` | 對 bg | 18.22 | ≥4.5 |
| `terminal-cursor` | `#16324f` | 對 bg | 13.10 | ≥3 |
| `terminal-selection` | `#286bf033` | 半透明 | **瀏覽器實測** | `contrast.ts` 不算半透明色 |
| `text-on-terminal` | `#2b333b` | 對 bg／對 chip | 12.81／11.31 | ≥4.5 |
| `text-on-terminal-dim` | `#5b6670` | 對 bg／對 chip | 5.87／5.18 | ≥4.5 |
| `surface-on-terminal` | `#eef1f5` | — | — | — |
| `border-on-terminal` | `#dfe4ea` | 對 bg | 1.28 | 1.25 ≤ x < 3（裝飾性髮絲線） |
| `border-on-terminal-control` | `#8a949d` | 對 bg | 3.09 | ≥3 |

`terminal-selection` 是唯一算不出來的一格：`contrast.ts:22-25` 明講半透明色的比值取決於底下是什麼，
**誠實的答案在瀏覽器量，不在這裡算**。它跟著 `MSP-R-009` 走。

### 1.3 兩項殘留風險，以及它們沒有那麼嚴重的理由

**(1) CLI 設了背景色、但沿用預設前景時，可能不可讀。**
例如 `\e[41m`（紅底）＋ 預設前景，在 pocket 是 2.06:1。

這看起來很糟，直到量了現行深色主題的同一情境：

| | 彩色當背景 ＋ 預設前景，不可讀（<3:1）的數量 |
|---|---:|
| graphite（現行，深色） | **8 / 9** |
| pocket（提案，明亮） | **7 / 9** |

**pocket 在這一項比現行深色主題略好，不是變差。**
這是終端調色盤的固有性質：CLI 設背景色時幾乎一定同時設前景色，
palette 沒有辦法替沒設前景的那種輸出補救——除非去改寫輸出，而那是 §MS-19 明文禁止的。

**(2) 針對深色終端寫死 `\e[37m`（白字）的 CLI，在明亮版會變淡。**
在提案裡 `white` 是 3.66:1——低於 4.5，但**遠高於「看不見」**（現行深色主題的 `black` 是 1.78）。
這是 R1 的已知代價，換來的是 `\e[30m` 與 `\e[30;47m` 這類成對授權能正確渲染。
實際影響程度只能由 `MSP-R-009` 的真實 CLI 輸出判定；
若真機證據顯示 tmux 狀態列一類的輸出確實不可用，調整的是 `white` 的值（往深走），**不是規則**。

### 1.4 這些值還不算數的地方

- 沒有經過真實 xterm 渲染（次像素反鋸齒在明亮底上的觀感與計算值不是同一件事）。
- 沒有經過真實 Claude／Codex／tmux／`ls`／Git 輸出。
- 沒有 truecolor 的評估——CLI 直接指定 RGB 時 palette 完全不參與，
  addendum §6 已經接受「truecolor 在明亮底可能不完美」，且**不得**為此改寫 bytes。
- 色盲可辨性沒有評估。6 個色相在明亮底的可辨性與深色底不同，列為新的 `MS-OM-11`。

## MS-18 `pocket` 主題的 token 值

寫入 `theme/tokens.css`、`theme/themes.ts`。兩個檔案**同一次提交**，否則 `theme.contract.test.ts` 會失敗——那正是它存在的目的。

- `THEME_IDS` 加入 `"pocket"`；**不加入** `SHIPPED_THEME_IDS`（它不是使用者可選項，是 viewport 派生的，見 `MS-D-05`）。
- `THEMES.pocket` 定義**全部** `COLOR_TOKENS`，一個都不能缺。`themes.test.ts` 斷言 key 集合相等，缺一個就失敗。
- `tokens.css` 新增 `:root[data-theme="pocket"] { color-scheme: light; … }`；
  `theme.contract.test.ts:129` 要求每個 theme 區塊都宣告 `color-scheme`。
- 該區塊**不得重定義任何尺度 token**（`theme.contract.test.ts:114`）。行動尺度走 `MS-01` 的 media 區塊。
- **不得使用鏈式 `var(--x, fallback)`**（`theme.contract.test.ts:109`）。
- 來源：A 版明亮／Pocket Workbench 的近白 canvas、白 surface、深色文字、克制的藍 accent。
  Porcelain 的**非終端** token 是合理起點。終端九個 token 見 §1.2。
  注意 canvas 與 terminal 的角色在 pocket 是反過來的：終端是 `#ffffff`（紙），canvas 往後退到近白。
- `terminalAnsi(id)` 依 §0.1 拆分；pocket 用 §1.2 的實測提案值，深色主題沿用現行 `TERMINAL_ANSI` 原值。
- pocket 的 `--terminal-*` 與 `--*-on-terminal` 九個 token 用 §1.2 的表，**不得**沿用 Porcelain 的深色值。

驗收：`theme.contract.test.ts` 全綠（CSS 與 TS 逐 key 相等）；`theme.contrast.test.ts` 對 `pocket` 的每一組 PAIRS 達標——
該測試以 `for (const id of THEME_IDS)` 迭代（`:58`），所以 pocket 一加入就自動納管，**不需要也不允許為它加例外**。

## MS-19 對比與真實渲染驗證

寫入 `theme/contrast.ts`、`theme/theme.contrast.test.ts`、新增真實渲染證據。

**第一條，也是本票真正的內容：把 ANSI 16 色納入 `PAIRS`。**
§0.1.1 的發現是那 16 個值從來沒有被測試涵蓋過。pocket 不應該是唯一被驗的那一個——
新增一個明亮主題卻只驗新主題，等於承認舊的沒人敢動。規則以 §1.1 的 R1–R3 落成：

| 斷言 | 門檻 | 適用 |
|---|---|---|
| 12 個彩色對 `terminal-background` | ≥4.5:1 | 全部主題 |
| 灰梯裡「遠離背景」的兩個 | ≥4.5:1 | 深色＝`white`/`brWhite`；pocket＝`black`/`brBlack` |
| 灰梯裡「靠近背景」的兩個 | 1.25 ≤ x < 4.5 | 深色＝`black`/`brBlack`；pocket＝`white`/`brWhite` |
| 灰梯明度單調遞增 | `black` < `brBlack` < `white` < `brWhite` | 全部主題 |
| 同色相 bright 比 normal 更遠離終端表面 | 對比之比 ≥1.15 | 全部主題 |

「靠近背景的那兩個」由每個主題**具名宣告**（例如 `TERMINAL_DIM_ANSI: Record<ThemeId, [string,string]>`），
**不由明暗推斷**——推斷會在下一個主題加進來時安靜地選錯兩個。

現行五個深色主題在這組規則下**已經全部通過**，但這句話在實作時被修正過一次：
「對背景的對比」那幾條確實一開始就算過（§0.1 的表：14 色 5.79–16.02，兩個 dim 色 1.50–3.93），
**normal／bright 那一條當初沒算就寫進計畫**，而它的初版門檻讓五個深色主題全紅。
門檻已依實測修正（見 §1.1 R3 的方框）。教訓照實記在這裡，而不是把它從計畫裡抹掉。

自動化其餘涵蓋：頁面／終端／編輯器文字、dim 文字、選取、游標與 cursor accent、控制項邊界、焦點環、
警告／錯誤／成功、唯讀與拒絕態的中繼資訊。

真機／真實 CLI 涵蓋（屬 `MSP-R-009`，**不得用 fixture 代替，也不得用 §1.2 的算術代替**）：
ANSI 16 色的 normal 與 bright、選取、游標、dim、警告／錯誤輸出、反白（reverse video）、
明確指定背景色的輸出，以及 Claude／Codex／tmux／`ls`／Git 的代表性 truecolor 輸出。

其中兩項要特別存證，因為它們是 §1.3 兩項殘留風險的實際判定：
`\e[3Xm`／`\e[4Xm` 的完整 8×8 前景背景矩陣，以及 tmux 狀態列一類會寫死 `\e[37m` 的輸出。
判定結果若為不可用，調整的是 §1.2 的值，**不是 §1.1 的規則**。

硬性界線（addendum §6，逐條保留）：

- CLI 送出的 truecolor 可能在明亮底下不完美。**可以接受。bytes 與 ANSI 語意永不更改。**
- 禁止 CSS `filter`／`invert`、canvas 反相、輸出重新上色、改寫 PTY bytes。
- 套用主題只換顏色：不得 remount xterm／Monaco、不重連、不移動捲動、不丟失待送輸入、不改授權。
  現行 `useTerminalSession.ts:299-312` 與 `monaco/setup.ts:127-129` 已是就地重繪，pocket 沿用同一條路徑。

## MS-20 選擇層：誰決定套用 `pocket`

寫入 `theme/applyTheme.ts`、`stores/preferences.ts`、`public/theme-boot.js`、`views/PreferencesView.vue`、`components/layout/ThemeMenu.vue`。

**選擇與套用分離**（`MS-D-06`）：

```text
preferences.theme          使用者的選擇（graphite | porcelain），照舊持久化，行動端不覆寫
preferences.renderedTheme  實際生效值 = isNarrow ? "pocket" : preferences.theme
```

- `applyTheme.ts:68-70` 的 `light` 判斷加入 `"pocket"`，否則 `color-scheme` 與 `theme-color` meta 會停在深色，
  而捲軸與行動網址列**不讀 custom property**（該檔註解已說明這正是這兩行存在的原因）。
- viewport 跨越 767/768 界限時（旋轉、桌面縮視窗）以 `MS-01` 的 `matchMedia` `change` 重新套用，
  並呼叫既有的就地重繪路徑（`terminal.applyTheme`／`shellTerminal.applyTheme`／`setPreviewTheme`，
  `SessionWorkspaceView.vue:554-555`）。**不重建元件。**
- `PreferencesView.vue` 與 `ThemeMenu.vue` 在 pocket 生效時顯示一行說明：使用者的選擇仍被保留，只是此寬度固定明亮。
  沒有這行，切換器會與畫面公開矛盾。
- `public/theme-boot.js`（`MS-D-07`）：加寬度判斷以避免冷載入深色閃一幀。
  **界限不得放寬**：`theme.contract.test.ts:171` 限制 ≤12 行程式碼，`GATE-VR-NO-GLYPH-ICON` 在 CI 檢查同一界限。
  實測現況 9 行，加寬度判斷後約 10 行；若實作後超過 12 行，回到「接受閃爍」而不是改門檻。
  `theme.contract.test.ts:174-186` 的「只接受 shipped theme ids」需同步更新為「shipped ids ＋ 寬度派生的 pocket」，
  且仍要擋下任何手改的 localStorage 值變成無 CSS 規則對應的屬性。

## MS-21 桌面回歸

寫入：測試。**這張票的產出是證據，不是行為。**

- `graphite` 與 `porcelain` 的 token 值 diff 必須為空。
- 深色主題的 `terminalAnsi()` 回傳值與現行 `TERMINAL_ANSI` 逐 key 相等（§0.1 (a) 的整個安全性建立在這一條上）。
- 桌面（≥768）在模擬 OS dark 與 OS light 下的選擇結果與改動前相同。
- **模擬 OS dark preference 時，行動仍產出核准的 pocket 明亮值**——這是 #62 決定的直接測試，
  也是 `MSP-F-002` 在 fixture 層已通過、`MSP-R-009` 要在正式層重做的那一項。

## 寫入集與排程

| 票 | 檔案 |
|---|---|
| MS-18 | `theme/tokens.css`、`theme/themes.ts` |
| MS-19 | `theme/theme.contrast.test.ts`、`monaco/setup.ts`（`base` 分支與註解）、真實渲染證據 |
| MS-20 | `theme/applyTheme.ts`、`stores/preferences.ts`、`public/theme-boot.js`、`views/PreferencesView.vue`、`components/layout/ThemeMenu.vue`、`theme/theme.contract.test.ts` |
| MS-21 | `theme/themes.test.ts`、`theme/theme.contract.test.ts`、桌面回歸 E2E |

theme owner **不碰** socket 與生命週期程式。
`MS-20` 會碰 `SessionWorkspaceView.vue` 的主題套用路徑（`:545-571`）——該檔同時是 M2 terminal writer 的寫入集，
**必須與 M2 序列化**（`02-…md` §2 已載明這條協調要求）。

## 本文件相對 v0.1 的三處具名修訂

送 M0 時需一併核准：

1. **`TERMINAL_ANSI` 拆為 per-theme**（§0.1），pocket 用 §1.2 的實測提案值。v0.1 未提及；不拆則明亮終端不可讀。
2. **Monaco `base` 依主題分支**（§0.2）。v0.1 未提及；不改則 pocket 的預覽仍是深底，與同畫面的明亮終端矛盾。
3. **ANSI 16 色納入 `PAIRS`**（§0.1.1、`MS-19`）。這一項**不限於行動版**：
   它補的是所有主題都有的既有缺口，現行五個深色主題已驗證會通過。
