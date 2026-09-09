# 00 — 執行總控（前端視覺更新）

Ticket 前綴 `VR-`（**V**isual **R**efresh）。目錄編號的理由見 [`README.md`](README.md)。

## 1. 成功定義

**要交付的：** 把 [五款風格規格](../../docs/design/visual-refresh/README.md) 落成一套語意 token 系統，
以 Graphite（深色，預設）與 Porcelain（淺色）兩款主題導入既有 Vue 前端；十一個頁面、十六個共用元件
與終端／編輯器共用同一份色彩來源；主題可切換且切換不影響任何進行中的工作。

**不得弄壞的六件事：**

1. **終端與 Session 的連續性。** 切換主題、收合導覽、開關檔案欄、切換分頁，都不得
   `new Terminal()`、不得卸載持有 WebSocket 的面板、不得以 0×0 resize 遠端 PTY
   （共用規範「終端與檔案」、`plan/08` D4）。
2. **`plan/09` 的高度模型。** 高度只有一個來源（App Shell）；面板不得以子元素數量決定高度；
   `--layout-sidebar` 的三處數字必須一致。三條 grep gate 保持綠燈（D13）。
3. **授權與能力的來源。** 每個寫入／控制入口仍然是「伺服器算出的 capability **且** Node 自己的回報」，
   兩者任一為否就**隱藏**而不是 disable（`vue-naive-ui-workflow` skill）。視覺變更不得新增、
   放寬或猜測任何權限。
4. **唯讀預覽。** Monaco 換主題不等於換能力；`readOnly`、不註冊寫入類 contribution
   （`monaco/setup.ts` 的三條約束、ADR 0015）一個字都不動。
5. **不新增字型檔以外的外部請求。** ADR 0016 的「dist 不含任何 CDN 參照」仍然成立；
   本期**不引入 webfont**（D12）。
6. **圖片投放與檔案上傳的行為。** 兩條寫入路徑（ADR 0024／ADR 0026）的判斷邏輯、
   放置目標、拒絕文案一個位元組都不動；本期只改它們**長什麼樣子**（D14）。

成功的判準是這十項，每一項都要有可貼上的輸出（`06-…md` §3）：

1. 1440×900 進入 Session 工作台，Graphite 主題下 CLI 終端機填滿中央面板
   （`.xterm-screen` 高度 ≥ 面板高度 90%、列數 ≥ 30），整頁沒有垂直捲軸。
2. 切到 Porcelain，**同一個 Session 沒有斷線**：`terminal.status` 不變、捲動位置不變、
   已輸入未送出的字元還在、`role` 不變；xterm 背景與 Monaco 背景同時變成 Porcelain 的
   `terminal.background`，而**不是**變成白色。
3. 重新整理頁面，主題仍是 Porcelain，且**第一幀就是 Porcelain**（沒有先閃一下深色）。
4. `grep -rnE '#[0-9a-fA-F]{3,8}|rgba?\(|hsla?\(' frontend/src --include=*.vue --include=*.ts`
   的結果是空的（現況 69 處）。
5. `theme.contrast.test.ts` 通過，且把 `text.secondary` 改亮兩階會讓它變紅。
   表內每一組配對都列出實測值（`02-…md` §6）。
6. 兩款主題 × 三個斷點（1440×900／1024×768／390×844）各有一張工作台截圖，
   `document.documentElement.scrollWidth <= clientWidth` 在六種組合都成立。
7. 鍵盤從 Skip link 走到終端：每一個可聚焦控制項都有看得見的焦點環（實測 ≥ 3:1），
   Dialog 開啟後焦點被關在 Dialog 內、Esc 可關、關閉後回到觸發點（現在三件都沒有）。
8. Sessions 空清單、Sessions 篩選無結果、Node 離線、Session 已結束（唯讀）、
   重連中、上傳失敗六種狀態各有一張畫面，**文案彼此不同**，且錯誤不隨 Toast 消失。
9. 導覽在 1440 是展開側欄、在 1024 是 64px 圖示列（每項有 aria-label 與 tooltip）、
   在 390 是可開啟選單；檔案欄在 768–1023 是覆蓋抽屜且有可觸及的開啟鈕。
10. `research/style.md` §3／§9／§17／§20／§22／§24 與程式一致，
    `scripts/ly/layout-gates.sh all` 綠燈，`make check` 綠燈。

## 2. 範圍

### 納入

- `VR-01` 六項行為實測（`08-…md`），其中第 1、2 項是**閘門**。
- `VR-02` ADR 0027、`research/style.md` 七處修訂、PRD 新增 `NFR-006` 與三條 AC、
  五份設計文件的四處修訂、traceability 註冊（`01-…md`）。
- `VR-03` 語意 token 契約、兩款主題色值、`themes.ts` ↔ `tokens.css` 綁定、
  xterm／Monaco 主題橋、主題套用機制（`02-…md`）。
- `VR-04` App Shell 幾何、PrimaryNav（Lucide、可收合）、SessionHeader、StatusBar、
  四段響應式與抽屜（`03-…md`）。
- `VR-05`／`VR-06` 十六個共用元件與其狀態矩陣、a11y 契約（`04-…md`）。
- `VR-07`–`VR-09` 十一個頁面的採用（`05-…md`）。
- `VR-10` 偏好 UI（主題、終端字級、檔案欄寬度）與 `localStorage` 持久化。
- `VR-11` 四條新 gate、量測式 E2E、對比自動檢查。
- `VR-12` evidence pack、安全審查、`.agent/skills` 三份更新、exit gate。

### 不納入

- **後端、daemon、契約、部署的任何變更。** 判準見 D14。
- **Midnight／Studio／Industrial 的驗收。** 色值進主題表，版型差異不實作，
  不列入驗收矩陣（D2，共用規範明文允許並要求記錄）。
- **跨裝置的偏好同步。** 偏好只在 `localStorage`（`README.md`「一件本期刻意不做的事」）。
- **新功能。** 沒有新的頁面、沒有新的資料、沒有新的權限、沒有 Command Palette
  （`style.md §23` 列了它，但它從來沒有被實作，本期也不做——那是一張獨立的票）。
- **webfont。** Inter 與 JetBrains Mono 不進 bundle（D12）。
- **深色／淺色以外的第三種色彩模式**（高對比模式、色盲模式）。要做時是新 ADR。

## 3. 固定基線決策

| # | 決策 | 選擇 | 理由 |
|---|---|---|---|
| D0 | **本期在哪條線上** | `master`。不帶入、不依賴、也不阻擋 `v2` 系列（`plan/16`–`plan/27`） | 視覺更新的來源文件（PR #52 原型、PR #53 規格）都在 `master`，而 V2 是另一條產品線。兩邊都會動 `frontend/src`，所以本期的 diff 要能被 V2 重放——做法是**本期不改任何 store、composable 的介面與任何 `api/` 型別**，只改 `theme/`、`components/`、`views/` 的呈現層與 `AppLayout` 的結構（D14 的判準把這件事寫死） |
| D1 | **交付兩款主題，Graphite 為預設** | Graphite（深色）＋ Porcelain（淺色）。首次造訪依 `prefers-color-scheme` 推導，使用者明示選擇後以 `localStorage` 記住 | 使用者已選定（2026-09-08）。深色為預設的理由不是偏好而是**現況**：終端與 Monaco 已經是深色，淺色外框把它們框在中間會製造一個高對比邊界，而使用者盯著的是中間那塊。Porcelain 必須同時交付，因為五份文件裡**只有淺色主題暴露出真正的難題**（深色終端要在淺色外框裡有自己的一套文字色，共用規範明文），只做深色會讓 token 表少掉 `text.onTerminal` 這一整個維度而不自知 |
| D2 | **另外三款只進主題表，不進驗收矩陣** | Midnight／Studio／Industrial 的九個色值各自寫進 `themes.ts`，但**不實作它們的版型差異**（Midnight 的 64px 精簡導覽、Studio 的側欄摘要、Industrial 的水平導覽），也不在切換器裡提供 | 共用規範：「正式選定僅支援部分主題時，縮減矩陣需明確記錄範圍」。色值留著的成本接近零而且它們已經是規格；**版型留著的成本不是零**——三套 layout variant 是三倍的響應式驗收。**被否決**：把三款色值也刪掉（下次要開啟時得回頭翻設計文件，而那正是漂移的起點）；三款都做（工作量約兩款的 2.5 倍，而 Porcelain／Studio 的對比修正必須全數落地） |
| D3 | **密度：標準，單一組** | 表格列 48px、表單控制項 36px、觸控目標 44×44px、UI 間距 4／8／12／16／20／24／32 | 使用者已選定。五份文件這一段的數值完全相同，所以「標準」不是折衷而是**規格本身**。**被否決**：緊湊（要另外處理 44px 觸控目標，且會讓五份文件的數字全部要改）；兩種都做並可切換（驗收矩陣再乘 2，而且每個元件的間距都要走 token 而不是常數——那是一張獨立的票） |
| D4 | **導覽：可收合側欄** | 展開態沿用 `--layout-sidebar: 208px`；收合態 64px 圖示列；桌面手動收合 ＋ 斷點自動收合 | 使用者已選定。**寬度維持 208px 而不是 Graphite 文件的 216px**：208 是 `plan/09` LY-05 量過的（五個 13px 導覽項含圖示與內距約 144px），而 8px 的差別買不到任何東西，卻要動 `tokens.css`、`style.md §9`、`style.md §22` 三處並讓 `GATE-LY` 重新校準。**處置是改文件不是改程式**（`01-…md` §4） |
| D5 | **色彩只有一個來源，而且是兩份互相綁死的來源** | `theme/tokens.css`（CSS 的來源）與 `theme/themes.ts`（JS 的來源）並存，由 `theme.contract.test.ts` 解析前者、比對後者，任一漂移就變紅 | 為什麼不能只有一份：CSS 需要 custom property 才能讓 `data-theme` 切換不重新掛載元件；xterm 與 Monaco 需要**具體色值字串**（`terminal.options.theme` 不吃 `var()`）。為什麼不 runtime 反查：`getComputedStyle` 在切換的那一幀拿到舊值，在 `display:none` 的面板上拿到空字串——而 CLI 面板正是靠 `v-show` 隱藏的。**兩份來源＋一條綁死的測試**是唯一同時滿足這兩邊的形狀 |
| D6 | **`frontend/src` 不得出現字面色值** | 除 `theme/tokens.css` 與 `theme/themes.ts` 外，任何 `#hex`、`rgb()`、`rgba()`、`hsl()` 都不允許。由 `GATE-VR-NO-LITERAL-COLOR` 擋 | 現況 69 處，其中 `StatusBadge.vue` 一個檔案 12 處、`monaco/setup.ts` 10 處、`useTerminalSession.ts` 4 處。它們不是疏忽而是**沒有出口**——現在的 token 表根本沒有 badge 的前景／背景配對，也沒有終端色。所以這條 gate 只有在 `VR-03` 把出口補齊之後才成立，順序不能顛倒 |
| D7 | **主題套用：`<html data-theme>` ＋ 一支 8 行的 `public/theme-boot.js`** | `:root` 定義 Graphite；`:root[data-theme="porcelain"]` 覆蓋；`<head>` 內以 `<script src="/theme-boot.js">`（**外部檔、render-blocking**）讀 `localStorage` 並設 `data-theme` | 為什麼不能用內嵌 script：`deploy/nginx/nginx.conf:134` 與 Railway 樣板的 CSP 是 `script-src 'self'`，**沒有 `'unsafe-inline'`**，內嵌 bootstrap 會被瀏覽器直接擋掉，而症狀是「主題偶爾不生效」。為什麼不放進 `main.ts`：那是 defer module，會在 CSS 已經上色之後才執行，使用者的明示選擇與 OS 偏好不同時會看到一次閃爍。放 `public/` 而不是 `src/`：不要被 hash 改名，`index.html` 才能寫死路徑。**被否決**：純 CSS `@media (prefers-color-scheme)`（無法表達「使用者明示選了與 OS 相反的那一款」）；把 CSP 加上 `'unsafe-inline'`（為了 8 行程式碼放寬一條全站的安全標頭） |
| D8 | **狀態色不由品牌色兼任，而且每個狀態是三元組** | success／warning／error／info／neutral 各有 `foreground`／`background`／`border` 三個值，每個主題各一組。狀態標籤一律**圓點＋文字＋1px 邊線** | 共用規範：「品牌色不是通用狀態色……但所有狀態都有文字」。三元組而不是單一色：淺色主題的 badge 底色與面板底實測只有 **1.07–1.17:1**（`02-…md` §6.2），沒有邊線的話那個膠囊在畫面上是看不見的，只剩文字浮著。Studio 的橘色同時是品牌色與 warning 的近鄰，所以「warning 必須附警告圖示與文案」這條寫進元件契約而不是各頁自行判斷 |
| D9 | **`border.subtle` 只做裝飾，控制邊界另立 `border.control`** | `border.subtle` 用於分隔線與卡片外框；輸入框、次要按鈕、Checkbox 等**必要控制邊界**一律 `border.control`，實測對 `surface.default` 與 `surface.canvas` **兩者**都 ≥ 3:1 | 共用規範已經寫了「不保證適合必要控制邊界」，但沒有給替代值。實測：五款的 `border.subtle` 對面板底是 1.21／1.27／1.39／1.34／1.50——**沒有一個到 3:1**。而現況 `--border-default #d7dde4` 是 **1.37:1**，也就是今天每一個輸入框的邊界都不合格。值在 `02-…md` §5.3 |
| D10 | **圖示一律 Lucide** | `AppLayout.vue:50, 62-75` 的七個文字符號（`◫ ◈ ▣ ▷ ◉ ☰ ⇄`）全部換掉；圖示按鈕一律有 `aria-label` ＋ tooltip | 共用規範明文：「Lucide 作為正式 UI 圖示來源，不混入文字符號充當導覽 icon」，而 `lucide-vue-next` **已經是相依**（`package.json:26`）且已在四個檔案使用。文字符號的實際問題不是風格：`▷` 在不同平台會被渲染成不同字重甚至 emoji，而它現在還是 `aria-hidden` 之外的可讀文字節點——螢幕閱讀器會把它念出來。收合成 64px 圖示列之後，這七個符號就是導覽的**唯一**視覺內容，所以這一條是 D4 的前提而不是裝飾 |
| D11 | **StatusBar 要真的做出來** | `style.md §9`／`§12` 規定的狀態列（28px）從 P0 至今**沒有被實作過**（`tokens.css:39` 的註解自己寫了「Not in use」）。本期實作，且**分開**顯示 Session 狀態、瀏覽器連線狀態、控制權 | 共用規範的資訊架構把「狀態列」列為五個層次之一，並要求「分開描述；不要合成一個綠色『正常』」。現在這三件事擠在工作標頭的 `.meta` 裡（`SessionWorkspaceView.vue:475-494`），與 Session 名稱、runtime、workspace 路徑、兩個姿態標籤並排——長 Session 名稱一出現就會把它們擠到換行。**代價要寫下**：狀態列吃掉 28px 的終端高度（約 1.7 列），這一項計入 D12 的算式 |
| D12 | **終端字級 14px，但行高**不是**五份文件寫的 1.6** | 預設 14px、`lineHeight: 1.2`、使用者可調 12–20px 並持久化；`fontFamily` 改為純本機等寬堆疊，移除不存在的 `"JetBrains Mono"` | 五份文件寫「終端預設 14px，行高 1.6」。1.6 是 **UI 內文**的慣例值，套在 xterm 上是把字格高度乘 1.6：以 1440×900、扣掉 header 56 ＋ fill 內距 24 ＋ 工作標頭 72 ＋ 分頁 44 ＋ 狀態列 28（D11）＝ 676px，再減面板邊框約 2px ＝ 674px 可用高度。**`VR-01` 第 1 項已實測**（chromium，2026-09-08）：<br>`13px/1.0`（目前的字級設定）→ 字格 15px → **44 列**<br>`14px/1.0` → 字格 16px → **42 列**<br>**`14px/1.2` → 字格 19px → 35 列（採用，餘裕 5 列）**<br>`14px/1.4` → 字格 22px → **30 列**（正好壓線，不採用）<br>`14px/1.6`（文件字面）→ 字格 25px → **26 列** ← 跌破<br>`plan/09` 的閘門是 **≥ 30 列**，`style.md §12` 是「Terminal 佔最大比例」。照字面實作 1.6 會讓終端少掉 16 列，而那正是 `plan/09` 花一整期修好的東西。Firefox／WebKit 待 CI 補（`08-…md` §1）。`"JetBrains Mono"` 從來沒有被打包（ADR 0016），所以它今天就已經是一個永遠 fallback 的名字（`useTerminalSession.ts:216`） |
| D13 | **`plan/09` 的三條不變量繼續有效，而且三個選擇器名不得改** | `.terminal-pane`、`.preview`、`.tree-panel` 是 `scripts/ly/layout-gates.sh` 直接以字串比對的目標。新元件（StatusBar、抽屜、可調寬檔案欄）一樣禁止 `100vh` 與 `grid-template-rows` 決定面板高度 | 那三條 gate 是「以文字檢查擋住一個只有瀏覽器看得見的錯誤」，它們的代價就是**耦合到選擇器名**。重新命名會讓 gate 在找不到規則時報 `FAIL: rule not found`（腳本已經處理了這個情況），但那是一次可以被「順手改 gate」繞過的紅燈。本期把「不得改名」寫成決策，讓繞過需要一句解釋 |
| D14 | **這一期不碰的東西** | `backend/`、`daemon/`、`contracts/`、`deploy/`、`frontend/src/api/`、`frontend/src/protocol/`、`frontend/src/stores/` 的**行為**、`monaco/setup.ts` 的 contribution 與語言註冊清單、`useTerminalSession.ts` 的 socket 與 writer 邏輯 | 判準：diff 出現在前四個目錄，或 `frontend/src/api/`／`protocol/` 的任一檔案，就是走錯路了。`stores/` 允許新增一個 `preferences.ts`（D7 的偏好）但**不得改動任何既有 store 的 state 形狀**——那是 V2 重放本期 diff 的前提（D0）。`useTerminalSession.ts` 只允許改三處：`fontSize`／`lineHeight`／`fontFamily` 常數、`theme` 物件的來源、以及一個新增的 `applyTheme()`；socket、fit、writer gate 一行都不動 |
| D15 | **檔案欄可調寬並持久化** | 預設 258px，可拖曳 220–360px，寬度存 `localStorage`；768–1023px 改為覆蓋抽屜，<768px 同 | Graphite 文件明列，而現況是寫死的 300px（`SessionWorkspaceView.vue:864`）且 ≤1100px 直接隱藏。**「隱藏」是本期要改掉的那一半**：共用規範說「不將功能直接隱藏」，而現在 1000px 的視窗看不到檔案樹也沒有任何開啟入口。`style.md §9` 的 inspector 300px 一併修訂為 258px（`01-…md` §4） |

## 4. 目標幾何（1440×900，Graphite，展開導覽）

| 區域 | 現況 | 本期 | 來源 |
|---|---:|---:|---|
| 頂部 header | 56px | 56px | `style.md §9`（不變） |
| 側欄（展開／收合） | 208px／64px（僅 ≤900px 自動） | 208px／64px（**可手動**） | D4 |
| 工作標頭 | 內容決定 | 72px | Graphite §4 |
| 分頁列 | 內容決定（約 33px） | 44px | Graphite §4 |
| 狀態列 | **不存在** | 28px | D11 |
| 檔案欄 | 300px 固定 | 258px 可調 220–360 | D15 |
| 中央面板可用高度 | **未量** | 674px（676 − 面板邊框約 2） | 相減 |
| 終端列數 | **未量** | **35**（`14px/1.2`，chromium 實測） | `plan/09` 閘門 ≥ 30 |

**這張表要誠實讀：本期讓終端變矮。** 狀態列（+28px）、固定高度的分頁列、
更高的工作標頭合計約 60px，再加上字級 13→14 的字格變化。
在本期的目標幾何下實測：`14px / 1.2` 是 **35 列**（閘門 ≥ 30，餘裕 5 列）。
D12 原本推估 32 列、餘裕 2 列，是把字格高估成 21px；實際是 19px。
**閘門仍然是閘門**——`14px/1.6` 實測只有 26 列，若沒有先量就照文件字面做，
會直接跌破 `plan/09` 花一整期修好的東西。

**1024×768 另有一項實測發現**：該尺寸的面板只有 542px，`14px/1.2` 只給 28 列。
`plan/09` 沒有在這個尺寸設閘門，但處置寫進 `VR-04`——
1024–1439px 這一段工作標頭收成單列 48px，並倚賴使用者可調字級（`08-…md` §1.1）。

**現況的列數刻意留白**：它取決於內容決定高度的工作標頭，猜一個數字沒有意義。
`VR-01` 第 1 項會同時記錄**改動前與改動後**的實際列數，
release note 用那組實測值，不用這裡的推算（`00-…md` §5 閘門、`08-…md` §1）。

**換到的是**：狀態列把「Session 狀態／連線／控制權」從擠在標頭裡的三個標籤
變成一條讀得懂的列（D11），而分頁列固定高度讓 `plan/09` 修好的
「面板不因子元素數量塌陷」在多一個分頁時仍然成立。

## 5. 波次與 ticket

| 波次 | Ticket | 標題 | 依賴 |
|---|---|---|---|
| **0（閘門）** | `VR-01` | 六項行為實測：終端列數、主題切換成本、FOUC、Lucide bundle 增量、xterm ANSI 十六色、Monaco 主題切換 | — |
| | `VR-02` | ADR 0027、`style.md` 七處修訂、PRD `NFR-006` 與三條 AC、五份設計文件四處修訂、traceability 註冊 | `VR-01` 第 1、2 項 |
| **1（基座）** | `VR-03` | 語意 token 契約、兩款主題、`themes.ts` ↔ `tokens.css` 綁定、xterm／Monaco 主題橋、`theme-boot.js` | `VR-02` 核准 |
| | `VR-04` | App Shell 幾何、PrimaryNav（Lucide、可收合）、SessionHeader、StatusBar、四段響應式與抽屜 | `VR-03` |
| **2（元件）** | `VR-05` | 基礎元件：Button／IconButton／Field／StatusBadge／InlineNotice／EmptyState／Toast／Dialog | `VR-03` |
| | `VR-06` | 資料與工作區元件：DataTable／Toolbar／FilePanel／WorkspaceTabs 改造／PreviewPane 主題化 | `VR-05` |
| **3（頁面）** | `VR-07` | Session 工作台（`SessionWorkspaceView`、`FileTree`、`PreviewPane`、上傳與投放的外觀） | `VR-04`、`VR-06` |
| | `VR-08` | Sessions、Nodes、NodeDetail、NodeTunnels | `VR-06` |
| | `VR-09` | Dashboard、Audit、Enrollment、Integrations、Login、TokenShowcase | `VR-06` |
| **4（收尾）** | `VR-10` | 偏好 UI：主題切換器、終端字級、檔案欄寬度、導覽收合狀態的持久化 | `VR-07`–`VR-09` |
| | `VR-11` | 四條新 gate、量測式 E2E、對比自動檢查、`session.spec.ts` 既有測試的同步 | `VR-10` |
| | `VR-12` | evidence pack、驗收矩陣、安全審查、`.agent/skills` 三份、exit gate | `VR-11` |

**兩道閘門：**

1. **`VR-01` 第 1 項（終端列數）與第 2 項（主題切換不重建終端）沒過，不得開 `VR-03`。**
   第 1 項決定 token 表裡的字級與行高；第 2 項決定 xterm 主題橋是「換 options」還是
   「必須重建」——若真的必須重建，那是設計變更（切換主題會斷 Session），
   要回到 `VR-02` 重新決定，而不是在實作時默默接受。
2. **`VR-02` 核准前不得動 `frontend/src`。** 理由與 `plan/09` D5／D6、`plan/15` 相同：
   本期要改 `style.md` 的七處數字與 §24 的整節範圍，先改程式再改文件就是製造下一期的漂移。

## 6. 共同 DoD

每一張 `VR-` ticket 完成的定義：

1. `npm run --prefix frontend format:check`、`lint`、`typecheck`、`test:unit -- --run`、`build` 全綠。
2. `scripts/ly/layout-gates.sh all` 綠燈，且**沒有修改該腳本**。
3. 該票新增或改動的每一個元件，在 `TokenShowcaseView` 有一格，**兩款主題各一張截圖**。
4. 該票碰過的每一組色彩配對，在 `theme.contrast.test.ts` 有一行且列出實測值。
5. 該票沒有引入新的字面色值（`GATE-VR-NO-LITERAL-COLOR`）。
6. 該票若動到有狀態的元件（終端、預覽、檔案樹、上傳列），
   PR 描述要回答一句：**「這個改動之後，切主題／收合導覽／改視窗大小時，它會不會被卸載？」**

## 7. 風險

| 風險 | 徵狀 | 處置 |
|---|---|---|
| **終端變矮而沒有人發現** | 使用者說「換了新版之後 CLI 看起來擠了」 | D12 的算式 ＋ `VR-01` 閘門 ＋ `plan/09` 既有的量測 E2E（列數 ≥ 30）。**餘裕只有 2 列**，所以 `06-…md` §2.2 把那條 E2E 的門檻同時跑在兩款主題上 |
| **切換主題斷掉 Session** | 切主題之後終端一片空白、要重新連線 | `VR-01` 第 2 項是閘門；`06-…md` §2.3 有一條會變紅的 E2E（切主題後斷言 buffer 內容、捲動位置、未送出輸入、`role` 四者不變） |
| **淺色主題把深色終端框成一個高對比孔洞** | Porcelain 下盯著終端久了眼睛痛 | 這是 Porcelain 文件自己點名的問題（「活動分頁使用深色 terminal 背景與淺色主題文字」）。處置是 `text.onTerminal` 與 `terminal.*` 一整組獨立 token（`02-…md` §5.4），且終端周圍**只保留一層容器**、不加陰影 |
| **token 表建好了，但頁面各自繞過它** | 三個月後又有 30 個字面色值 | `GATE-VR-NO-LITERAL-COLOR` 每次 push 都跑。它擋不住「用錯 token」，但擋得住「不用 token」——後者才是會累積的那一種 |
| **`themes.ts` 與 `tokens.css` 漂移** | xterm 是舊的綠、頁面是新的綠 | `theme.contract.test.ts` 解析 `tokens.css` 的文字並逐鍵比對。**這條測試比它看起來重要**：兩份來源是 D5 刻意的代價，沒有它就只是兩份會分岔的檔案 |
| **V2 那條線重放不了本期的 diff** | 合併 `v2` 時前端整片衝突 | D0 ＋ D14 的判準：本期不改 store 的 state 形狀、不改 `api/` 與 `protocol/`。`VR-12` 要跑一次 `git diff master...v2 --stat -- frontend/src` 並在 exit 報告裡貼出重疊的檔案清單 |
| **`style.md §24` 說 Desktop Only，本期做了四段響應式** | 有人拿 §24 退回 PR，或反過來拿 PR 主張 §24 已作廢 | `VR-02` 必須先修訂 §24（`01-…md` §3）。**在那之前 390×844 的畫面不是交付物，是實測**——這個順序寫進閘門 |
| **對比自動檢查變成橡皮圖章** | 測試只驗 token 表裡列的那幾組，實際畫面上的組合沒被驗到 | 五份設計文件就是這樣漏掉 `accent/tint` 的。處置：配對清單由**元件契約**產生（`04-…md` 每個元件列出它用到的配對），不是由 token 表產生 |
