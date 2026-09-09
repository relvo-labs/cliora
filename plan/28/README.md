# Cliora 前端視覺更新：把五款風格規格落成一套可切換的 token 系統

本目錄把 [`docs/design/visual-refresh/`](../../docs/design/visual-refresh/README.md) 的五份風格規格與
[`prototypes/visual-refresh/`](../../prototypes/visual-refresh/README.md) 的互動原型，轉成可建立 ticket、
撰寫程式與驗收的執行規格。ticket 統一使用 `VR-` 前綴（**V**isual **R**efresh）。

## 編號為什麼是 28

`master` 這條線目前只到 `plan/15`，但 `plan/16`–`plan/27` 在 `v2` 分支上已經是 V2 系列的十二期
（`plan/16` = V2.0 專案基座 … `plan/27` = V2-E1）。如果本期占用 `plan/16`，同一個目錄名在兩條線上
會指兩件不同的事，而那種衝突在合併時不會報錯、只會安靜地覆蓋。**目錄名一律全 repository 唯一**，
所以本期取全域下一個空號 `28`。

本期在 `master` 這條線上，**不帶入也不依賴 V2 的任何東西**。

## 這一期真正的形狀

五份風格文件的最後一節都寫著同一句話：「本文件不宣稱已完成瀏覽器驗收」。
[共用規範](../../docs/design/visual-refresh/00-shared-foundation.md) 的「整合與驗收流程」第 3 步
是「將 tokens 與展示元件導入 Vue」——**本期就是那一步，以及它之後的第 4、5 步。**

而導入之前有三件事必須先承認：

### 1. 現在的顏色不是一套系統，是三套並存

| 來源 | 位置 | 現況 |
|---|---|---|
| CSS custom properties | `frontend/src/theme/tokens.css` | 27 個 token，只有淺色一組，沒有主題維度 |
| 元件裡的字面色值 | 13 個檔案、63 個 hex ＋ 6 個 `rgb()` | `StatusBadge.vue` 一個檔案就有 12 個 |
| JS 裡的第四份 | `useTerminalSession.ts:218-223`、`monaco/setup.ts` 的 `defineTheme()` | xterm 與 Monaco 各自寫死深色值 |

換主題不是「改幾個變數」，是先把後面兩套收回第一套。這是本期最大的一塊工作，
也是為什麼本期第一張功能票是 token 契約而不是任何一個頁面。

### 2. 現況已經有五處量得出來的可讀性失敗

不是「看起來有點淡」，是實測值（sRGB 相對亮度比，計算方法見 `02-…md` §6）：

| 配對 | 位置 | 實測 | 目標 |
|---|---|---:|---|
| `--border-focus` ／ 面板底 | `tokens.css:19`，全站鍵盤焦點環 | **2.85:1** | 3:1 |
| `--text-inverse` ／ `--status-error` | `ConfirmDialog.vue` 的 danger 鈕＝**Terminate 確認鈕** | **4.09:1** | 4.5:1 |
| `--border-default` ／ 面板底 | `tokens.css:17`，所有輸入框與次要按鈕的邊界 | **1.37:1** | 3:1 |
| `online` badge 綠字／綠底 | `StatusBadge.vue:44-46` | **3.13:1** | 4.5:1 |
| `degraded` badge | `StatusBadge.vue:48-50` | **2.63:1** | 4.5:1 |

八個 StatusBadge 配對裡有**六個**不到 4.5:1（全表在 `02-…md` §6.1）。
換句話說：本期就算什麼視覺風格都不改，這五處也該修。視覺更新只是把它們一次做完的機會。

### 3. 五份風格文件本身有四處需要修訂，其中一處是它自己漏檢的對比失敗

文件的對比表只驗了**三組**配對（主文字、次文字、主按鈕文字），而導覽與分頁的選中態
——「accent 文字疊在 accent.subtle 底上」——**沒有被驗過，而且 Porcelain 沒過**：

```
Porcelain  accent.primary #286BF0 ／ accent.subtle #E9F0FF  =  4.13:1   ← 未達 4.5:1
Studio     accent.primary #B6653F ／ accent.subtle #F1E2D7  =  3.37:1   ← 未達 4.5:1
```

而那正是共用規範說「導覽與分頁：鈷藍文字＋淡藍底」要用的那一個配對。
處置在 `02-…md` §5：新增 `accent.strong`，Porcelain 取 `#1B54C4`（實測 5.90:1）。

另外三處（Naive UI 實際上沒有被使用、`style.md §24` 與五份文件的響應式互相矛盾、
`--layout-sidebar` 的 208px 與 Graphite 文件的 216px 打架）寫在 `01-…md` §2–§4。

## 已定的四個選擇

[五款風格索引](../../docs/design/visual-refresh/README.md) 的「如何選定」表留了五個空格給使用者。
本期開工前已經填掉四個（2026-09-08）：

| 決策 | 選擇 | 影響 |
|---|---|---|
| 主要風格 | **Graphite**（預設，深色） | `00-…md` D1 |
| 次要／淺色主題 | **Porcelain** | 驗收矩陣 2 主題 × 3 斷點＝6 組 |
| 導覽形式 | **可收合側欄**（展開／64px 圖示列） | `03-…md` §2 |
| 預設資訊密度 | **標準**（表格列 48px、控制項 36px） | `00-…md` D3 |
| 是否混搭 | 只取 Graphite 的版型；Midnight／Studio／Industrial 的版型差異不實作 | `00-…md` D2 |

Midnight、Studio、Industrial **仍然寫進主題表**（它們的色值已經是規格），
但**不列入驗收矩陣**——共用規範明文允許：「正式選定僅支援部分主題時，縮減矩陣需明確記錄範圍」。
記錄在此，並在 `06-…md` §5 再寫一次它們具體沒有被驗什麼。

## 這一期最容易做錯的七件事

1. **先改頁面再改 token。** 那會讓每個頁面各自決定「這裡該用哪個灰」，而那正是現在
   63 個字面色值的來源。`VR-03` 是所有頁面票的硬依賴。
2. **用 `getComputedStyle` 把顏色餵給 xterm。** 它在切換主題的那一幀會拿到舊值，而且
   在 `display:none` 的面板上拿到空字串。做法是 `themes.ts` 與 `tokens.css` 兩份來源
   由一條測試綁死（`02-…md` §7），不是 runtime 反查。
3. **照字面把終端行高調成 1.6。** 五份文件寫「終端預設 14px，行高 1.6」，
   但 1.6 是 **UI 內文**的慣例值——xterm 的 `lineHeight` 是乘在字格高度上的倍率。
   **已實測**（chromium，`08-…md` §1）：目標幾何下 `14px/1.2` 是 **35 列**，
   `14px/1.6` 只剩 **26 列**，而 `plan/09` 的閘門是 1440×900 下**列數 ≥ 30**。
   這是 `VR-01` 的第一項，也是本期唯一一個會擋住 token 票的實測（`00-…md` D12、§4）。
4. **把 `border.subtle` 拿去當輸入框的邊界。** 五個主題的 `border.subtle` 對面板底
   實測是 **1.21–1.61:1**，一個都不到 3:1。共用規範已經寫了「不保證適合必要控制邊界」，
   本期給出實際可用的 `border.control` 值（`02-…md` §5）。
5. **切換主題時重建終端。** 共用規範的驗收明寫「主題切換保留 Session、終端捲動位置、
   控制權與未送出輸入」。xterm 換色是 `terminal.options.theme = …`，不是 `new Terminal()`。
   這一條有一個會變紅的 E2E（`06-…md` §2.3）。
6. **順手把 Naive UI 接起來。** 共用規範寫「保留既有 Vue、Pinia、**Naive UI**、xterm.js、Monaco」
   ——但 Naive UI **從來沒有被使用過**（`01-…md` §2）。把它接起來是新增一整套元件語彙，
   不是「保留」。本期的決定是移除這個相依。
7. **在任何 view 裡重新推導高度。** `plan/09` 的三條 grep gate 仍然有效，本期的新元件
   一樣受它們約束，而且 `.terminal-pane`／`.preview`／`.tree-panel` 這三個選擇器名
   **不得改名**，除非同時改 `scripts/ly/layout-gates.sh`（`00-…md` D13）。

## 一件本期刻意不做的事

**不新增後端的使用者偏好 API。** 主題、密度、終端字級、檔案欄寬度全部存在 `localStorage`。

代價要誠實寫下：換一台機器或換一個瀏覽器，偏好不會跟著走。
換到的是本期**一行後端程式碼、一個 migration、一個契約版本都不動**——
而視覺更新沒有任何理由去動授權面。要做跨裝置偏好時它是一張獨立的票，
而那張票該問的是「偏好要不要進稽核」，不是「順便加個欄位」。

## 檔案

| 檔案 | 內容 |
|---|---|
| [`00-execution-plan.md`](00-execution-plan.md) | 成功定義（十項判準）、範圍與非目標、固定基線決策 D0–D15、波次與十二張 ticket、共同 DoD、風險 |
| [`01-decisions-and-governance.md`](01-decisions-and-governance.md) | ADR 0027、`research/style.md` 七處修訂、PRD 新增 `NFR-006` 與三條 AC、traceability 註冊、Naive UI 的處置、五份設計文件的四處修訂、skills 更新 |
| [`02-token-contract-and-themes.md`](02-token-contract-and-themes.md) | `VR-03`：語意 token 表、Graphite／Porcelain 完整色值與**實測**對比、`accent.strong`／`border.control`／狀態三元組的推導、`themes.ts` ↔ `tokens.css` 的綁定、xterm／Monaco 主題橋、主題套用與 FOUC |
| [`03-app-shell-and-navigation.md`](03-app-shell-and-navigation.md) | `VR-04`：AppShell 幾何、PrimaryNav（Lucide、可收合、64px 態）、SessionHeader、StatusBar（規格有、程式從來沒有）、四段響應式與抽屜 |
| [`04-component-foundation.md`](04-component-foundation.md) | `VR-05`／`VR-06`：十六個共用元件的狀態矩陣與 a11y 契約、Dialog 的焦點約束（現在沒有）、Toast／EmptyState／InlineNotice／DataTable（現在沒有）、既有元件的改造清單 |
| [`05-page-adoption.md`](05-page-adoption.md) | `VR-07`–`VR-09`：十一個頁面的採用順序、每頁的空／錯誤／唯讀／過期畫面、工作台的面板與檔案欄、長文字與長路徑 |
| [`06-verification-and-exit.md`](06-verification-and-exit.md) | `VR-10`–`VR-12`：偏好 UI、四條新 gate、量測式 E2E、evidence pack、驗收矩陣、安全審查七題、exit 條件 |
| [`07-implementation-status.md`](07-implementation-status.md) | 實作進度（**計畫完成，全部未開始**） |
| [`08-open-measurements.md`](08-open-measurements.md) | `VR-01` 六項待實測，其中兩項是閘門（**第 1、2 項已於 2026-09-08 在 chromium 實測完成**）；以及「沒有要量什麼、為什麼」 |

規範來源一律回指 [`research/prd.md`](../../research/prd.md)、[`research/style.md`](../../research/style.md)、
[`research/tech.md`](../../research/tech.md) 與 [`docs/adr/`](../../docs/adr/)，本目錄不複製需求內容
（`.agent/skills/AUTHORING.md`「Never duplicate canonical research」）。

## 使用規則

1. **`VR-02` 核准前不得動 `frontend/src`。** 本期要改 `research/style.md` 的七處數字與一節範圍
   （§24 從「Desktop Only」變成四段響應式），那是規格變更，書面決定必須先於實作。
   這與 `plan/09` D5／D6 學到的是同一課：**先改文件再改程式，否則製造下一期的漂移**。
2. **`VR-01` 的第 1 項（終端列數）沒過就不准開 `VR-03`。** 若 14px×1.6 讓 1440×900 掉到 30 列以下，
   那不是「調一下」，是要在行高與字級之間重新選一次，而那個選擇會寫進 token 表。
3. **色彩只有一個來源。** `frontend/src` 底下除了 `theme/tokens.css` 與 `theme/themes.ts`
   不得出現任何 hex、`rgb()`、`hsl()` 字面值。由 `GATE-VR-NO-LITERAL-COLOR` 擋。
4. **對比是測出來的，不是宣稱的。** 每一組進 token 表的配對都要在
   `theme.contrast.test.ts` 裡有一行，而那條測試會因為改壞色值而變紅。
   任何以「看起來夠深」通過的 PR 退回。
5. **jsdom 不能當版面或顏色證據。** 沿用 `plan/09` D8：幾何與實際渲染色一律 Playwright 量測。
6. **`plan/09` 的三條 grep gate 必須保持綠燈，且不得靠改 gate 本身取得。**
   改了 `scripts/ly/layout-gates.sh` 的 PR 需要在描述裡說明為什麼那條不變量已經不成立。

## 完成結果

本期通過時：

- 使用者可以在 Graphite（預設）與 Porcelain 之間切換，切換後 **Session 不斷、終端 buffer 與捲動位置
  不變、未送出的輸入還在、控制權不變**，且 xterm 與 Monaco 一起換色（不是只有頁面換）。
- `frontend/src` 底下的字面色值數量是 **0**（現況 69 處），主題表涵蓋五款風格的色值。
- 兩款主題 × 三個斷點（1440×900／1024×768／390×844）× 六種狀態（正常／空／錯誤／唯讀／重連／長文字）
  各有一張畫面，且沒有不必要的整頁橫向溢出。
- 現況那五處實測失敗（焦點環 2.85、Terminate 鈕 4.09、控制邊界 1.37、六個 badge）全部達標，
  並由一條會變紅的單元測試鎖住。
- 導覽的七個文字符號（`AppLayout.vue:50,62-75`）全部換成 Lucide，且每個圖示按鈕有 aria-label。
- `research/style.md` §3／§9／§17／§20／§22／§24 與程式的數字一致，
  `plan/09` 的三條 layout gate 仍然綠燈，`traceability/` 有本期四類 primary link。
