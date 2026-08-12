# 01 — 決策與治理

本期新增 **D32–D36** 五個決策，接在 `research/02/01` 的 D1–D31 之後。
**沒有新 ADR**（理由見 §6）。

---

## D32 — prototype §2 的 18 個語意色整組採納

**決策**：`research/prototype-v2/styles.css` §2 的 18 個候選值**原值進 `tokens.css`**，
一個都不改。另補 12 個尺度 token（`--space-1`…`6`、`--font-xs`…`xl`）
與一個 `--font-mono`。

**為什麼整組而不是逐個挑**：那 18 個值不是 18 個獨立選擇，它們是**四組關係**——
六車道要有推進感、三種「進行中」要能區分、三級可信度要有明確的視覺權重差、
風險三級要與狀態色不撞。挑掉其中幾個，關係就斷了。

**為什麼原值不調**：prototype 已經把它們排在一個可點擊的畫面上（`V.tokens`），
色票、hex、並排比較都在。**要調的時機是那個畫面上，不是在 `tokens.css` 的 diff 裡。**
`UI-11` 把那個審查畫面搬進產品（`TokenShowcaseView`），之後要調隨時可調。

**代價**：`tokens.css` 從 27 個 custom property 變成 58 個。這是可接受的——
它本來就少到不夠用，那正是 104 個錯名字的成因。

**開工前需要點頭。**

---

## D33 — 看板欄位走 OpenAPI 快照，不動 `contracts/`

**決策**：`BoardCardDTO` 新增三個欄位，**純新增**，由 `scripts/pj/openapi_diff.py`
的既有快照機制治理。`contracts/` 一個字不改，契約版號不動，daemon 不動。

**為什麼要明寫**：`plan/18` 的每一張 ticket 幾乎都伴隨 contract 版號變更，
所以「動了 API 就要動 contract」很容易被當成慣例。**它不是。**
`contracts/` 只裝 WSS 控制通道的 envelope 與 messages
（實際內容：`control-envelope.schema.json` ＋ `messages/`），board 從來不在裡面。

**相容性**：純新增欄位，舊前端忽略多的鍵。**沒有破壞性變更，不需要旗標。**

---

## D34 — 不重新引入全域 class layer，改做 Vue 元件

**決策**：prototype 的 `.card`／`.badge`／`.table`／`.page-head` **做成
`frontend/src/components/ui/` 底下的 Vue 元件**，不做成全域 CSS class。

### D34 不是新主張，是把 `P4-07` 沒做完的後半做完

> **2026-08-12 修正。** 本節原本寫的是「D34 是**遵守** P4-07 的既有決定」，
> 引的是 `base.css` 檔頭那句「已被 scoped style 完全遮蔽卻仍在打包」。
> 回去讀 `plan/05/03-dashboard-and-error-management.md` §P4-07 的原始紀錄之後，
> **那個說法不準確**，而準確的版本對 D34 更有利。

**P4-07 根本不是一個 CSS 架構決定。** 它的標題是「**原型退場與 Error Management**」，
同一張票裡還有移除 P0 dev relay、拿掉 Google Fonts CDN、改套件名、建 error catalog。
刪 `styles.css` 只是其中一項，而刪它的四條理由**每一條都很具體**：
CDN `@import` 違反 P3「`dist` 不得有 CDN 參照」並會被 ADR 0017 的 CSP 擋掉、
`body{min-width:1180px}` 逼出頁面級橫向捲軸、硬編碼色值**自成一套平行變數**
（`--side`／`--top`／`--border`／`--muted`）與 `tokens.css` 衝突、以及一批 grep 確認的死 class。

**沒有一條是「共用樣式不該放全域」。**

而那張表還有第五列，講**仍在使用**的 class，處置寫得很明確：

> **仍被使用**的 class：`.primary`（5 個檔）、`.danger`（3 個）、`.head`（6 個）、
> `.panel`（2 個）、`.ghost`
> → **遷移為共用元件或 scoped style：新增 `components/common/{PageHeader,Panel}.vue`**
> 與按鈕樣式。**逐檔遷移 ＋ 每檔視覺回歸截圖**，避免一次大改造成 UI 迴歸。

所以 P4-07 的決定是**兩半**：刪掉原型檔 ＋ **為還在用的東西建共用元件**。

**只執行了前半。** `components/common/` 今天是
`AsyncState`／`ConfirmDialog`／`ErrorNotice`／`StatusBadge` —— **`PageHeader.vue`
與 `Panel.vue` 從來沒有被建立**，從 P4 到 V2.2 三個階段都沒有。

### 後果可以量

那五個 class 名字沒有消失，它們**擴散了**（含該 class 的檔案數，粗略 grep，2026-08-12）：

| class | P4-07 當時 | 現在 |
|---|---|---|
| `.primary` | 5 | **17** |
| `.danger` | 3 | **9** |
| `.head` | 6 | **15** |
| `.panel` | 2 | **9** |
| `.ghost` | —（未記數） | **22** |

同一個視覺現在有 70 幾份各自獨立的 scoped 實作，**沒有一份是權威的**。

**這就是 104 個未定義 token 能擴散而沒人發現的真空**，三件事是同一條因果鏈：
沒有共用元件 → 每個 view 自己寫 CSS → 每個作者憑印象寫變數名 → 沒有東西在檢查。

> `base.css` 檔頭那句「entirely shadowed by scoped styles」也要跟著修正理解：
> **死掉的那些確實是，還在用的那五組不是**——它們被明確指定要變成元件。
> 那句註解把「刪掉的部分」的理由寫成了整件事的理由。`UI-05` 完成時應順手改那段註解。

**prototype 用全域 class 不是結論，是它的體質**：零依賴、無 build、單檔 HTML，
除了全域 class 沒有別的選擇。**照搬形式而不是照搬語意，是誤讀 prototype。**

**元件化額外買到的東西**：
- 中文標籤與未知值退路只寫一次（B3／B5），不會在第七個引用點漂移；
- D10 的「三處完全一致」變成**結構上為真**，而不是靠 review 盯；
- 每顆徽章可以有單元測試。

**代價**：模板比 class 囉嗦（`<StageBadge :stage="card.stage" />` vs `class="badge"`）。
接受——這一期的問題正是「便宜的寫法沒有任何東西在檢查它」。

### 本期唯一真正「新」的部分

P4-07 指定 **2** 個元件（`PageHeader`／`Panel`），D34 做 **11** 個。多的 9 個是：

| 多的 | 為什麼是本期新增的 |
|---|---|
| 五顆語意徽章 | V2 的工作語彙，P4 時還不存在。D10 要求三處一致，這是它成立的方式 |
| `DataTable`／`EmptyState`／`ToastHost` | `EmptyState` 服務 `09` §6 的空狀態規則；`ToastHost` 是 `UI-08` 的落點 |

**這 9 個要自己站得住腳，不能算在 P4-07 頭上。** 上面兩列就是它們各自的理由。

**開工前需要點頭**——但要點頭的是**那 9 個的擴大**，
`PageHead`／`UiCard` 那兩個等同 P4-07 已經批准過的 `PageHeader`／`Panel`。

---

## D35 — 不擴大 naive-ui 的使用面

**決策**：`naive-ui` 已在 `package.json`（2.42.0）且 `theme/naive.ts` 有設定，
但本期**不用它做徽章與版面原語**。

**為什麼**：這一期要建立的是**語意詞彙**（stage／run／risk／source），
那是 Cliora 專屬的，不是通用 UI 元件庫涵蓋的東西。把 `NTag` 包一層再塞進
自訂顏色，得到的是「一個第三方元件 ＋ 一層覆寫」而不是更少的程式碼。

**不是決定移除它**——既有用到的地方不動。這只是劃定本期的範圍。

---

## D36 — `StatusBadge` 不動，新徽章族與它並存

**決策**：既有的 `components/common/StatusBadge.vue`（服務 V1 的 terminal 與 node 狀態）
**完全不動**。新的 V2 徽章族放在 `components/ui/`，兩者並存。

**為什麼不合併**：`StatusBadge` 有既有的 screenshot 基準與 e2e 斷言，
而且它的狀態集（`connected`／`reconnecting`／`online`／`degraded`…）
與 V2 的語彙集沒有交集。合併會為了「只有一個徽章元件」這個美感目標，
去動一組已經穩定且被測試釘住的東西。

**邊界寫下來，免得下一個人猜**：

| 用哪個 | 什麼時候 |
|---|---|
| `StatusBadge` | node 線上狀態、terminal 連線狀態——**基礎設施的健康度** |
| `ui/StageBadge` 等 | task stage、run 狀態、risk、delivery、evidence source——**V2 的工作語彙** |

`UI-11` 的審查畫面要**把兩組並排展示**，讓這條邊界看得見而不是只寫在這裡。

---

## 6. ADR 處置：本期不新增 ADR

**判準**（沿用既有慣例）：ADR 記的是**會被後人質疑、且推翻代價很高**的結構性選擇。

D32／D34／D36 都是**在既有 ADR 的框架內**做事：

- D32 落實的是 `ADR 0027`／`0028` 已經要求的視覺分級，只是把值定下來；
- **D34 是把 `P4-07` 指定過但沒做完的後半做完**（§D34），加上 9 個有各自理由的新元件；
- D36 是不動既有元件。

**唯一需要留下痕跡的是 D33**（為什麼 API 變更沒有伴隨 contract 版號），
而它的正確落點是 `contracts/CHANGELOG.md` 的一行說明，不是一份 ADR。

> **2026-08-12 修正後，D34 該不該有 ADR 的天平往「該有」偏了一點。**
> 原本的理由是「它只是遵守既有決定」——那個理由站不住了：
> P4-07 從來沒有把「共用樣式不放全域」寫成原則，它只是刪掉一份特定的原型檔，
> 而**它指定的替代方案（共用元件）三個階段沒有被建立**，
> 那個真空造成了可量測的後果（五個 class 擴散成 70 幾份各自實作）。
>
> 所以「前端樣式放哪」這件事**目前沒有任何一份文件正式回答過**。
> 若 review 要一份 ADR，它應該叫「**前端樣式的分層：token、元件、scoped style**」，
> 並且要做三件事：①明文回答那個從沒被回答的問題；②收編 P4-07 的紀錄與它沒做完的部分；
> ③修正 `base.css` 檔頭那句過度概括的註解。
>
> **但它仍然不該夾在這一期趕出來**——那是一份重寫既有決定的文件。
> 本期先把 D34 與這份考證寫在這裡，ADR 留給有餘裕的時候（`10-…md` §6 第 1 項）。

## 7. 紅線檢查

V2 的五條紅線（`research/02/00` §7）**沒有一條被這一期碰到**：

| 紅線 | 這一期有沒有碰 |
|---|---|
| 1 — 呼叫端不指定 argv／binary／shell／環境變數 | 無關（純前端 ＋ 一個唯讀查詢） |
| 2 — 路徑安全由 `workspace.Root` 收斂 | 無關 |
| 3 — 寫入面只新增，不編輯／移動／刪除 | 無關 |
| 4 — 不做 Git 自動化與任務派工 | 無關 |
| 5 — 自主執行的每種出口都要落在人看過才生效的地方 | 無關 |

**安全審查：不觸發。** 判準是 `research/02/10` §6 的四項觸發條件
（新增執行面、新增機密面、新增對外提供面、新增信任邊界），本期一項都不符合。

唯一值得記一筆的是 `UI-06` 讓看板多回三個欄位——
**三個欄位都不含機密、不含路徑、不含使用者可控的自由文字**：
`active_run_status` 是 enum、`active_run_runner_name` 是 runner 名稱（已在 Agents 頁公開）、
`waiting_reason` 是後端產生的固定集合值。RBAC 沿用既有的 `project.view`，不新增動作。

## 8. 必須同步修訂的文件

| 檔案 | 內容 | ticket |
|---|---|---|
| `research/style.md` | 新增的 31 個 token（沿用既有慣例：token 進 `tokens.css` 就同步這裡） | `UI-01` |
| `research/02/09` §7 | **已加註**（2026-08-12）：原文的「用既有 token 組合」做不到，修訂指向 `research/02/12` §2 | 已完成 |
| `research/02/00` §6 | **已加註**：階段表新增 V2.2_1 一列 | 已完成 |
| `research/02/CHECKLIST.md` | **已新增** §4b | 已完成 |
| `research/02/11` | **已新增** `NFR-UI-001`…`003` | 已完成 |
| `contracts/CHANGELOG.md` | 一行說明：board 欄位變更為何不在此檔（D33） | `UI-06` |
| `docs/adr/0028` | 若 review 決定要 ADR，改寫此處而非新開一份（§6 的但書） | 視 review |
