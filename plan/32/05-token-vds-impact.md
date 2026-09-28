# 05 — 對 token 與 VDS 的影響（提案，未套用）

本期**沒有**修改 `frontend/src/theme/tokens.css`、`themes.ts`、`research/style.md` 或任何桌面行為。
以下是「若選定某個變體，正式實作前必須先版本化核准什麼」。

## 1. 顏色：零變更

三個變體只用 `:root[data-theme="pocket"]` 既有的值（原型 token 區塊逐一複製，另加 `plan/29/07` §1.2 的 pocket ANSI）。
`test_prototype.py` 以與 `theme/contrast.ts` 相同的公式量了 41 組配對：

- 文字 ≥4.5:1：`text-primary`／`text-secondary` 對三種表面、`accent-strong` 對白與 `accent-subtle`、白字對 `accent-strong`、
  五個 `status-*-fg` 對各自 `-bg` 與白、`terminal-foreground`／`terminal-input`／`text-on-terminal-dim` 對終端底、
  ANSI 12 色＋`black`／`brBlack`（pocket 的可讀端）對白底。
- 非文字 ≥3:1：`focus-ring`、`border-control` 對三種表面；`text-disabled`；ANSI `white`（pocket 的 dim 端）。

數字在 `/opt/data/cliora-mobile-75-run/shots/test/mobile-visual-ia-test.json`。
**因此 `GATE-VR-*` 與 `theme.contract.test.ts` 不受任何變體影響。**

唯一的顏色面前置條件是 D1／D2：xterm 與 Monaco 要真的拿到 pocket。那是既有 MS-20 契約的修復，不是新 token。

## 2. 尺度：需要一次版本化修訂

現況**沒有字級 token**：`frontend/src/**/*.vue` 有 229 處字面 `font-size:`，行動端只靠 `@media (max-width: 767px)`
覆寫 `--density-control`／`--density-row`／`--layout-workhead` 三個尺度 token（`tokens.css` 末段）。
任何一個變體要在多頁一致落地，都會碰到這件事。提案：

**VDS 1.1 行動附錄（`style.md` §24 之下新增一節），token 只進 `tokens.css` 既有的行動尺度 media 區塊，不進任何 theme 區塊：**

| 新 token | A | B | C | 備註 |
|---|---:|---:|---:|---|
| `--type-title` | 20px | 17px | 18px | Session 名稱、頁面標題 |
| `--type-body` | 15px | 14px | 16px | |
| `--type-meta` | 13px | 12px | 14px | 狀態、時間、說明；**不得小於 12** |
| `--type-mono` | 13px | 12px | 13px | 識別子；終端字級另由使用者偏好決定，不在此 |
| `--line-body` | 1.6 | 1.45 | 1.55 | |
| `--space-inline` | 20px | 12px | 16px | 行動左右內距 |
| `--radius-sheet` | 12px | 8px | 16px | 底部 sheet；C 需此 token，A/B 可直接用 `--radius-dialog` |

規則：

1. **桌面不動**：這些 token 在 `:root` 預設區塊給出與桌面現值相同的值（或不給、由元件 fallback 到現值），只有行動 media 區塊覆寫。
   `MS-21` 的桌面回歸（graphite／porcelain token diff 為空）必須維持綠。
2. `theme.contract.test.ts:114`「theme 區塊不得重定義尺度」不需要放寬：新 token 不在任何 theme 區塊。
3. `MS-22` 已有「行動 media 區塊內不得出現 `COLOR_TOKENS`」的測試，沿用。
4. C 的控制項圓角 12px 會與 `--radius-control: 8px` 衝突——若選 C，要嘛新增 `--radius-control` 的行動覆寫並更新 `style.md` §22，
   要嘛 C 退回 8px（原型的 C 是 12，以便看出差別）。

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

這些全部碰 `SessionWorkspaceView.vue` 與 M2 terminal writer 的寫入集（`plan/29/05` 寫入集表），**必須序列化**，
並且要等 #72／#73 的 M0 決定受管 Session 是否存在後，再決定「活動」分頁要不要預留位置。
