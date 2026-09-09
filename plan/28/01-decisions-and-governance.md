# 01 — 決策與治理（`VR-02`）

本檔是波次 0 的第二張票。它產出的東西**全部是文件**，但它是 `frontend/src` 的閘門：
本期要改 `research/style.md` 的七處數字與一整節範圍，先改程式再改文件就是製造下一期的漂移
（`plan/09` D5／D6 的教訓）。

## 1. ADR 0027：視覺主題化與 token 契約

> 編號檢查：`docs/adr/` 目前到 `0026`（`0025` 是空號），所以本期取 `0027`。

### 提案內容（草稿）

**Status:** proposed → accepted（`VR-02` 核准時）

**Context.** ADR 0005 把 `tokens.css` 定為調色盤的唯一來源，並預期
「Naive UI overrides reference those variables instead of duplicating hex values」。
三年下來的實際狀態是：`tokens.css` 有 27 個 token 且只有淺色一組；
`frontend/src` 底下另有 **69 處字面色值**分散在 13 個檔案；
xterm（`useTerminalSession.ts:218-223`）與 Monaco（`monaco/setup.ts` 的 `defineTheme()`）
各自持有第三、第四份深色調色盤；而 **Naive UI 從未被使用**（§2）。
`docs/design/visual-refresh/` 的五份規格要求主題化、深淺兩色、
以及 xterm／Monaco 與頁面共用同一份語意來源。

**Decision.**

1. **語意 token 是唯一的色彩來源，且它有主題維度。**
   `theme/tokens.css` 以 `:root` 定義預設主題、以 `:root[data-theme="…"]` 覆蓋；
   每個主題**必須明確定義每一個 token**，不得以鏈式 fallback 掩蓋缺漏（共用規範明文）。
2. **CSS 與 JS 有兩份來源，並由一條測試綁死。**
   `theme/themes.ts` 提供 xterm 與 Monaco 需要的具體色值字串；
   `theme.contract.test.ts` 解析 `tokens.css` 並逐鍵比對，任一漂移即失敗。
   理由與被否決的替代方案見 `00-…md` D5。
3. **`frontend/src` 底下不得出現字面色值**，`theme/tokens.css` 與 `theme/themes.ts` 除外。
4. **主題以 `<html data-theme>` 套用**，由 `public/theme-boot.js`（外部檔、render-blocking）
   在第一次繪製前設定。CSP 是 `script-src 'self'`，不得改用內嵌 script（`00-…md` D7）。
5. **本期支援 Graphite（預設）與 Porcelain。** Midnight／Studio／Industrial 的色值進主題表
   但不進切換器、不進驗收矩陣（`00-…md` D2）。
6. **Naive UI 從相依中移除**（§2）。ADR 0005 中「Naive UI overrides」那一句由本 ADR 取代。
7. **不引入 webfont。** ADR 0016 的系統字體堆疊與「dist 不含 CDN 參照」的 build-time grep
   繼續有效；`useTerminalSession.ts:216` 那個從未被打包的 `"JetBrains Mono"` 名字刪除。

**Consequences.**

- 好的：換主題是改一個屬性，不是改 13 個檔案；xterm 與 Monaco 不可能再與頁面不同步；
  對比是一條會變紅的測試而不是一次審查。
- 代價一：**兩份色彩來源**。這是為了同時滿足「CSS 要 custom property」與
  「xterm 要具體字串」而付的，`theme.contract.test.ts` 是它的保險絲——沒有那條測試，
  這個決定就只是兩份會分岔的檔案。
- 代價二：**`public/` 多了一支不經打包的 script**。它必須保持 8 行以內、
  不引用任何模組、不做任何 I/O 以外的事；`VR-11` 有一條 gate 檢查它的行數與內容。
- 代價三：**移除 Naive UI 之後，共用規範裡「使用既有 UI 元件能力」的四件事
  （Dialog 焦點約束、分頁箭頭鍵、抽屜關閉、樹狀鍵盤操作）改由本期自建**。
  其中兩件已經有了（`WorkspaceTabs.vue` 的 roving tabindex、`FileTree` 的鍵盤操作），
  兩件沒有（Dialog 焦點約束、抽屜）。這是 `VR-05` 的範圍，不是「順便」。

## 2. Naive UI：共用規範說「保留」，但它從來沒有被使用

共用規範的「原型差距與實作邊界」在五份文件都寫著同一句：

> 正式整合保留既有 Vue、Pinia、**Naive UI**、xterm.js、Monaco 與協定

這句話對其他四項都成立，對 Naive UI **不成立**。實際狀態：

| 檢查 | 結果 |
|---|---|
| `package.json:28` | `"naive-ui": "2.42.0"` 是 dependency |
| `frontend/src` 有沒有 `<n-…>` 元件 | **0 個** |
| `frontend/src` 有沒有 `import … from "naive-ui"` | 只有 `theme/naive.ts:1` 的**型別** import（`GlobalThemeOverrides`） |
| `theme/naive.ts` 有沒有被任何檔案 import | **沒有**。`main.ts` 沒有 `NConfigProvider`，整個檔案是死碼 |
| 三個對話框元件 | `ConfirmDialog.vue`、`NewSessionDialog.vue` 都是手寫 |

而 `theme/naive.ts` 那八行本身也不能用：它把 `primaryColor` 設成
`"var(--action-primary)"`，但 Naive UI 會拿這個值去**推導** hover／pressed／disabled 的色階
（它要解析成 RGB 再做明度運算），拿到一個 `var(…)` 字串時推導會失敗。
換句話說：那個檔案就算被接上也不會如預期運作。

**決定：移除 `naive-ui` 相依與 `theme/naive.ts`。**

理由：

1. **「保留」一個沒有被使用的東西，實際上是「導入」。** 導入 Naive UI 是新增一整套
   元件語彙、一套主題覆寫系統（它有自己的 token 名字），以及讓本期的 token 表
   同時要餵兩個消費者。那是一張獨立的票，不是視覺更新的一部分。
2. **它有具體成本。** 一個沒有被 import 的 dependency 不會進 bundle，但會進
   `package-lock.json`、進 CI 的安裝時間、進 supply-chain 的攻擊面
   （`security/daily-*` 那幾條分支就是在處理這一類），而換到的價值是零。
3. **本期需要的四件 a11y 能力有兩件已經自建且做得對**（roving tabindex、樹狀鍵盤），
   剩下兩件（Dialog 焦點約束、抽屜）加起來約 120 行。

**被否決：** 這一期把 Naive UI 真的接起來（範圍暴漲，且會讓「token 是唯一來源」
變成「token ＋ Naive 覆寫是兩個來源」）；留著相依不動（付成本不拿價值，
而且下一個人讀到共用規範那句話還是會以為它在用）。

**要同步的地方：** ADR 0005 那一句、`.agent/skills/vue-naive-ui-workflow` 這個 skill 的名稱與內容
（§7）、共用規範與五份風格文件裡的那句話（§4）。

## 3. `research/style.md` 的七處修訂

`style.md` 是 canonical（`cliora-project-context` skill）。本期改它，不是繞過它。

| # | 節 | 現況 | 改成 | 理由 |
|---|---|---|---|---|
| M1 | §3 Color System | 單一組淺色 hex 清單（Gray-50…950、Primary-50…900、四個狀態色、三個終端色） | 保留為 **Porcelain 之前的歷史調色盤**並標註，另立「§3.1 語意 token 與主題」指向 `02-…md` 的表 | 原本的清單是**原始色階**（primitive），不是語意 token。兩者都需要，但混在一起的結果就是元件直接引用 `Gray-300` |
| M2 | §9 Layout | `Inspector 300` | `Inspector 258（可調 220–360）` | `00-…md` D15 |
| M3 | §9 Layout | Status Bar 28px 有規格、無實作 | 不改數字，補一句「自 `plan/28` 起實作，內容為 Session 狀態／瀏覽器連線／控制權**三者分列**」 | `00-…md` D11 |
| M4 | §17 Status Badge | 只寫「Online Green／Busy Orange／Offline Gray／Error Red」與高度 24px、radius 999px | 補「每個狀態是 foreground／background／border **三元組**，且一律圓點＋文字＋1px 邊線」 | `00-…md` D8。現況六個 badge 配對不到 4.5:1，成因就是規格只說了「綠色」 |
| M5 | §18 Terminal | 無字級規定（實作是 13px） | 「預設 14px、行高 1.2、使用者可調 12–20px」（`VR-01` 實測後定案） | `00-…md` D12 |
| M6 | §22 Design Tokens | `font: body: Inter / mono: JetBrains Mono`、`layout.inspector: 300` | `font` 改為系統堆疊並註明 ADR 0016；`inspector: 258` | Inter 與 JetBrains Mono 從來沒有被打包，寫在規格裡讓實作以為它們存在——`useTerminalSession.ts:216` 就是這樣寫出來的 |
| M7 | §24 Responsive | 「Desktop Only（MVP）／不考慮手機／平板僅提供唯讀模式」 | 四段：≥1440 桌面／1024–1439 收合導覽／768–1023 檔案欄改抽屜／<768 單欄且主導覽改選單。**並保留一句**：可觸及不等於授權放寬，終端輸入權限不因裝置尺寸改變 | 五份風格文件都規定了 <768px 的行為，與 §24 直接矛盾。**必須先解決這個矛盾**，否則 390×844 的畫面既是交付物又是違規 |

M7 是本期唯一一處**範圍變更**（其餘六處是精確化或修正）。它要單獨在 `VR-02` 的核准裡點名。

## 4. 五份設計文件的四處修訂

這些文件是 Proposed 狀態的候選設計，本期把它們推進到「已選定並有實作規格」。

| # | 位置 | 問題 | 處置 |
|---|---|---|---|
| C1 | 五份文件的對比表 | 只驗了三組配對，**漏掉導覽／分頁選中態的 `accent.primary` ／ `accent.subtle`**。實測 Porcelain **4.13:1**、Studio **3.37:1**，兩者都不到 4.5:1——而那正是「鈷藍文字＋淡藍底」「陶土橘文字＋淡暖橘底」要用的配對 | 各文件的對比表補上這一組（含實測值），並在色彩表新增 `accent.strong`：Porcelain `#1B54C4`（實測 5.90:1）、Studio `#984D2E`（實測 4.83:1）。Graphite／Midnight／Industrial 的 `accent.strong` 等於 `accent.primary`（實測 6.35／6.50／6.97，通過） |
| C2 | 五份文件的對比表第三列 | 「原型主按鈕文字／accent.primary」的數值（Graphite 9.60、Midnight 9.76、Industrial 10.25、Porcelain 4.52）**是拿 `surface.canvas` 當按鈕文字算出來的**——而同一頁下面就寫著「不得以 canvas 字色推導所有按鈕文字」 | 把那一列改名為「`text.onAccent` ／ `accent.primary`」並明確列出 `text.onAccent` 的值（本期兩款：Graphite `#111518`、Porcelain `#FFFFFF`），而不是讓讀者從 canvas 推 |
| C3 | 共用規範「原型差距與實作邊界」（五份都有） | 「正式整合保留既有 Vue、Pinia、**Naive UI**、xterm.js、Monaco」——Naive UI 沒有被使用（§2） | 那句話裡刪掉 Naive UI，並加一句指向 ADR 0027 |
| C4 | Graphite §4 | 「完整導覽 216px」 | 改為 208px 並註明來源是 `plan/09` LY-05 的量測（五個導覽項含圖示與內距約 144px）。**改文件不改程式**：8px 買不到任何東西，卻要動三處數字並讓 `GATE-LY` 重新校準（`00-…md` D4） |

C1 與 C2 是**設計文件自己的錯誤**，不是實作偏離設計。它們要修在文件上，
否則下一個實作者會照著錯的表做出一樣的失敗。

## 5. `research/prd.md`：新增 `NFR-006` 與三條 AC

現況：traceability 的 115 條需求裡，**沒有一條在講可讀性、鍵盤操作或視覺主題**。
所以今天那五處對比失敗（`README.md` §2）在追溯上完全看不見——不是被 waive，是根本沒有對應的需求。

### 提案：`NFR-006 介面可及性與視覺主題`

| AC | 內容 | verification_profile | risk |
|---|---|---|---|
| `NFR-006.AC-01` | 使用者需要閱讀的文字，對其實際背景的對比 ≥ 4.5:1；必要控制邊界與焦點指示 ≥ 3:1。配對清單由元件契約產生 | automated | high |
| `NFR-006.AC-02` | 每一個可聚焦控制項有看得見的焦點指示，且不以 hover 代替 | automated | medium |
| `NFR-006.AC-03` | 狀態不以顏色單獨表達；每個狀態同時有文字 | automated | medium |
| `NFR-006.AC-04` | Dialog 開啟時焦點被關在 Dialog 內，Esc 可關閉，關閉後焦點回到觸發點 | automated | medium |
| `NFR-006.AC-05` | 圖示按鈕有可讀名稱（`aria-label`）與 tooltip | automated | low |
| `NFR-006.AC-06` | 1440×900／1024×768／390×844 下核心操作可觸及，無不必要的整頁橫向溢出 | automated | medium |
| `NFR-006.AC-07` | 主題切換不改變任何授權、不中斷 Session、不重建終端 | automated | high |
| `NFR-006.AC-08` | 在 `prefers-reduced-motion` 下停用非必要動畫；終端內容永不套用動畫 | automated | low |

### 既有需求新增的三條 AC

| AC | 內容 | 為什麼掛在這裡 |
|---|---|---|
| `FR-TERM-001.AC-15` | 切換視覺主題後，終端 buffer、捲動位置、未送出輸入與控制權四者不變 | 這是 Terminal **顯示**的要求，不是主題的要求。掛在主題底下會讓它在「主題功能被移除」時一起消失 |
| `FR-TERM-001.AC-16` | 終端字級可由使用者調整 12–20px 並持久化，調整後重新 fit 且不重建連線 | 同上 |
| `FR-TERM-005.AC-…` | 連線狀態（Session 狀態／瀏覽器連線／控制權）在狀態列**分列**呈現，不合併為單一指示 | `FR-TERM-005` 是「Terminal 連線狀態」。共用規範「不要合成一個綠色『正常』」是對它的收窄 |

編號以 `scripts/trace` 產生為準；上表的 `AC-15`／`AC-16` 是提案值，`VR-02` 核准時定案。

## 6. traceability 註冊

`VR-02` 要在 `traceability/` 完成四件事，並讓 `make traceability` 綠燈：

1. `requirements.json`：新增 `NFR-006`（`kind: "non-functional"`、`owner: "frontend"`、
   `applicability: ["mvp"]`、`criticality: "must"`）與其八條 criteria；
   `FR-TERM-001` 追加兩條 criteria；`FR-TERM-005` 追加一條。
2. `links.json`：每一條新 AC 四類 primary link（`spec` → `research/prd.md` 的 anchor、
   `design` → 本目錄與 `docs/design/visual-refresh/`、`impl` → 實際檔案、`test` → 實際測試）。
3. `gates.json`：新增四條 gate（`06-…md` §1），`required_for` 至少含 `changed` 與 `nfr`。
4. `docs/traceability/` 的四份產生檔以 `make traceability-render` 重新產生，**不手改**。

**不新增 waiver。** 本期沒有任何一項需要 waive——五處既有失敗是本期要修的東西，
不是本期要豁免的東西。若 `VR-01` 的實測讓某一項做不到（例如終端列數逼得字級退回 13px），
處置是**改規格**（M5）而不是 waive AC。

## 7. `.agent/skills` 的三份更新

| Skill | 改什麼 |
|---|---|
| `vue-naive-ui-workflow` | **改名**為 `vue-frontend-workflow`（目錄與 frontmatter `name` 要一致，`AUTHORING.md` 明文）；描述與內文移除 Naive UI，改為「Vue 3 + TypeScript + Vite + Pinia + Vue Router + xterm.js + Monaco，元件自建」；把「Apply semantic Naive UI tokens from `style.md`」改成「Apply semantic tokens from `theme/tokens.css`；never a literal colour」 |
| `design-system-starter` | 內文「Implement typed Naive UI overrides without duplicate sources」改為「Keep `tokens.css` and `themes.ts` in lockstep via the contract test」；補一句 token 有主題維度、每個主題必須完整定義（不得鏈式 fallback） |
| `cliora-project-context` | 補一段視覺姿態，形狀比照它現有的「Workspace write posture」段：**兩份色彩來源、五款規格只交付兩款、對比是測出來的、終端與編輯器與頁面共用一份語意來源、主題切換不得改變任何授權** |

`.agent/skills/README.md` 的索引與計數要一併更新——它目前寫「Skill count: 17」，
但目錄下實際有 22 份（`cliora-project-context`、`cliora-security-review`、
`go-daemon-development`、`terminal-websocket-protocol`、`vue-naive-ui-workflow` 都沒有列進去）。
這是既有的索引漂移，本期順手修正並在 PR 描述裡點名（**不是**本期造成的）。

## 8. 與既有 ADR 的關係

| ADR | 關係 |
|---|---|
| **0005** frontend foundation | 「Naive UI overrides reference those variables」那一句由 ADR 0027 §6 取代。其餘（`tokens.css` 是調色盤來源、terminal composable 獨佔 xterm 生命週期）**繼續有效並被本期強化** |
| **0015** filesystem limits and preview policy | 不變。Monaco 換主題不等於換能力；`readOnly` 與 contribution 清單一行不動 |
| **0016** RBAC and audit operations | §Fonts 的系統字體堆疊與「dist 不含 CDN 參照」的 build-time grep **繼續有效**。本期刪掉 `useTerminalSession.ts:216` 那個從未被打包的 `"JetBrains Mono"`，是讓程式與 0016 一致，不是變更 0016 |
| **0017** release/update/deployment | CSP 不動。ADR 0027 §4 的 `public/theme-boot.js` 是為了**在 CSP 之內**解決 FOUC 而選的形狀 |
| **0023** privileged node posture | 不變。工作台的兩個姿態標籤（沙箱已停用、可提權）**必須繼續在使用者按下 Enter 之前就可見**——視覺重排不得把它們移到摺疊區或 tooltip 裡 |
| **0024** / **0026** 兩條寫入路徑 | 行為不變。本期只改它們的外觀，且 `05-…md` §2.4 明列「入口的顯示條件不得改動」 |
