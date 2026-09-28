# 05 — 對 token 與 VDS 的影響（提案，未套用）

本期**沒有**修改 `frontend/src/theme/tokens.css`、`themes.ts`、`research/style.md` 或任何桌面行為。
以下是「若選定某個變體，正式實作前必須先版本化核准什麼」。

## 1. 顏色：零變更

三個變體只用 `:root[data-theme="pocket"]` 既有的值（原型 token 區塊逐一複製，另加 `plan/29/07` §1.2 的 pocket ANSI）。
`test_prototype.py` 以與 `theme/contrast.ts` 相同的公式量了 49 組配對（v0.2.1；v0.1／v0.2 只量了 41，當時 ANSI 只涵蓋 6 個 normal 彩色）：

- 文字 ≥4.5:1（38 組）：`text-primary`／`text-secondary` 對三種表面、`accent-strong` 對白與 `accent-subtle`、白字對 `accent-strong`、
  五個 `status-*-fg` 對各自 `-bg` 與白、`terminal-foreground`／`terminal-input`／`text-on-terminal-dim` 對終端底、
  ANSI **12 個彩色（6 normal ＋ 6 bright）**＋`black`／`brBlack`（pocket 的可讀端）對白底。
- 非文字 ≥3:1（9 組）：`focus-ring`、`border-control` 對三種表面；`text-disabled`；ANSI `white`（pocket 的 dim 端）。
- dim 帶 1.25 ≤ x < 4.5（2 組）：ANSI `white`、`brWhite`——`plan/29/07` R1 規定靠近白底的兩個灰是刻意壓淡的，不是文字目標。

值取自 `themes.ts` 的 `POCKET_ANSI`（與 `plan/29/07` §1.2 一致）。6 個 bright 彩色全部 ≥4.5:1（最低 `brGreen` 8.04），**沒有需要縮窄的項目**。
觀察（不是失敗）：`brWhite #c2c8ce` 對白是 1.69:1，若用 3:1 的非文字門檻會不通過；它依 R1 屬 dim 端，所以放在 dim 帶檢查，未改色值。

數字在 `/opt/data/cliora-mobile-75-run/shots/test/mobile-visual-ia-test.json`。
**因此 `GATE-VR-*` 與 `theme.contract.test.ts` 不受任何變體影響。**

唯一的顏色面前置條件是 D1／D2：xterm 與 Monaco 要真的拿到 pocket。那是既有 MS-20 契約的修復，不是新 token。

## 2. 尺度：需要一次版本化修訂

現況**沒有字級 token**：`frontend/src/**/*.vue` 有 229 處字面 `font-size:`，行動端只靠 `@media (max-width: 767px)`
覆寫 `--density-control`／`--density-row`／`--layout-workhead` 三個尺度 token（`tokens.css` 末段）。
任何一個變體要在多頁一致落地，都會碰到這件事。

**v0.2：產品負責人已選 C（`04-…md` §0），因此提案的 token 值就是 C 的那一欄。** A 的值只在 C 未通過 UAT 時才會回到討論；B 已不列入。

**提案：VDS 1.1 行動附錄（`style.md` §24 之下新增一節），token 只進 `tokens.css` 既有的行動尺度 media 區塊，不進任何 theme 區塊：**

| 新 token | 提案值（C） | 備註 | 備案（A，僅 C 未過 UAT 時） |
|---|---:|---|---:|
| `--type-title` | **18px** | Session 名稱、頁面標題 | 20px |
| `--type-body` | **16px** | 內文；亦是 iOS 輸入框不自動放大的下限 | 15px |
| `--type-meta` | **14px** | 狀態、時間、說明；**不得小於 12** | 13px |
| `--type-mono` | **13px** | 識別子；終端字級另由使用者偏好決定（12–20），不在此 | 13px |
| `--line-body` | **1.55** | | 1.6 |
| `--space-inline` | **16px** | 行動左右內距 | 20px |
| `--radius-sheet` | **16px** | 底部 sheet；`style.md` §6 上限正好是 16 | 12px |

**`--radius-control`：Q8 已決定 (b)**（2026-09-28，產品負責人 Neil，對話中：「那就用8」）。手機控制項／卡片維持 `--radius-control: 8px`
（`--radius-panel` 同為 8），C 只在底部 sheet 用 `--radius-sheet: 16px`；**不修訂 `style.md` §22，也不在行動 media 區塊覆寫 `--radius-control`**。
下表是決策前的選項，保留為紀錄：

| 選項 | 做法 | 代價 |
|---|---|---|
| (a) | 在行動尺度 media 區塊覆寫 `--radius-control: 12px`（`--radius-panel` 同步），並經 VDS 1.1 行動附錄修訂 `style.md` §22 的 `radius.control: 8` | 手機與桌面的控制項形狀不同；多一條要維護的例外；最接近原型 C 的樣子 |
| (b) **← 已選** | 維持 `--radius-control: 8px`，C 只在 sheet 用 16px | C 與 A 的視覺差距變小；不需修 §22 |

研究者當時建議 (b)——圓角是 C 最便宜的辨識度來源，卻也是 `04-…md` §4.1 C3「看起來像消費型 App」風險最大的一項；C 的核心（大字、少字、需要時整寬的下一步）不靠它。
原型已同步（v0.2.1）：C 的 `--radius` 由 12px 改為 8px，`--radius-sheet` 維持 16px；`test_prototype.py` 的 `radius_suite` 斷言三個變體的控制項／卡片都是 8px、sheet 為 A 12／B 8／C 16。

規則：

1. **桌面不動**：這些 token 在 `:root` 預設區塊給出與桌面現值相同的值（或不給、由元件 fallback 到現值），只有行動 media 區塊覆寫。
   `MS-21` 的桌面回歸（graphite／porcelain token diff 為空）必須維持綠。
2. `theme.contract.test.ts:114`「theme 區塊不得重定義尺度」不需要放寬：新 token 不在任何 theme 區塊。
3. `MS-22` 已有「行動 media 區塊內不得出現 `COLOR_TOKENS`」的測試，沿用。
4. 控制項圓角：Q8 (b)，沿用現行 `--radius-control: 8px`；VDS 1.1 行動附錄在圓角上只新增 `--radius-sheet`。

## 3. 元件層的影響（僅列出，非本期範圍）

| 元件 | 若採用本期 IA 需要的變更 | 對應既有票 |
|---|---|---|
| `AppLayout.vue` | `fill` 頁在 `<768` 可不渲染全域 header（新 prop 或 slot） | MS-03 |
| `SessionHeader.vue` | 返回鈕、兩行標題、posture 移出為獨立帶 | MS-06 |
| `StatusBar.vue` | `<768` 改在上方、需要動作時帶動作；控制權在已結束時改字（D9） | MS-06 |
| `WorkspaceTabs.vue`／`SessionWorkspaceView.vue` | 兩排合一排；system shell 由選單開啟（視 Q2） | MS-07 |
| `SessionsView.vue` | 路徑 `<bdi>`（D4）、Node 名稱（D5）、相對時間、標題列 | MS-04 |
| `NewSessionDialog.vue` | 行動全螢幕、繁中、posture 預告（D7） | — |
| `PreviewPane.vue` | 單一檔案列、拒絕態不顯示工具（P7） | MS-16 |

### 3.1 C 比 A 多出來的成本

選 C 之後，下列項目是 A 不需要、C 需要的（對到上表的元件）：

| C 的成本 | 落在哪個元件 | 說明 |
|---|---|---|
| **條件式整寬動作**：斷線時「重新連線」在狀態列整寬；Viewer 可接管時「取得控制權」放在終端底部、取代輸入位置 | `StatusBar.vue`（狀態列動作槽）、`SessionWorkspaceView.vue`（終端底部列） | 兩個不同位置、各自的出現條件（writer／viewer、`can_takeover`、連線狀態、Session 是否執行中）。終端底部列與 `plan/29/05` MS-12 的行動輸入元件**是同一個位置**：Viewer 時顯示接管列、writer 時顯示輸入元件，兩者互斥，必須由 MS-12 同一位 M2 terminal writer 擁有 |
| **`--surface-raised` 當清單畫布**（白卡浮在灰底） | `AppLayout.vue`（行動 `main` 背景）、`SessionsView.vue`（卡片） | 用的是既有 token，**不是顏色變更**；但手機的畫布與桌面 Porcelain（`--surface-canvas`）不同，要在 VDS 1.1 附錄寫明，避免下一個人以為是漏改 |
| **sheet 進場 180ms、reduced motion 0ms** | `UiDialog.vue`／`UiActionMenu.vue`／`NewSessionDialog.vue` 的 `<768` 底部 sheet 形態 | 用既有 `--motion-base: 180ms`；`UiDialog.vue:153` 已有 `prefers-reduced-motion: no-preference` 的寫法可沿用。成本在「對話框在手機變成底部 sheet」這個新形態，不在動畫本身。sheet 上緣圓角 16px 需新 token `--radius-sheet`（A 可沿用 `--radius-dialog` 12）；控制項／卡片圓角依 Q8 (b) 沿用 8px，**不是** C 的額外成本 |
| **清單不顯示路徑** | `SessionsView.vue`、Session `⋯` sheet | 路徑移到 `⋯`，那裡仍需要 D4 的 `<bdi>` 修正；若 UAT C1 失敗，要加「同名才顯示路徑」的條件 |
| **較大的列高與字級**（56–60px 列、16px 內文） | `SessionsView.vue`、`FileBrowser.vue` | 一屏內容較少；`--density-row` 的行動值（現 52px）可能要調到 56–60，屬 `MS-01` 的行動尺度區塊 |

這些全部碰 `SessionWorkspaceView.vue` 與 M2 terminal writer 的寫入集（`plan/29/05` 寫入集表），**必須序列化**，
並且要等 #72／#73 的 M0 決定受管 Session 是否存在後，再決定「活動」分頁要不要預留位置。
