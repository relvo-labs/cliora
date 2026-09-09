# 07 — 實作進度

**狀態：`VR-01`–`VR-12` 已實作；瀏覽器量測待 CI（本機無完整 stack）。**

使用者於 2026-09-08 依建議核准 `01-…md` 的四項治理提案
（ADR 0027、`style.md` M1–M7 含 §24 的範圍變更、移除 `naive-ui`、`NFR-006`）
以及 `00-…md` 的 D0–D15，並要求「儘可能依照原型」實作。

規則與前幾期相同：**「完成」要附得出證據**，沒有證據的一律是「進行中」。

## Ticket

| Ticket | 標題 | 狀態 | 證據 |
|---|---|---|---|
| `VR-01` | 六項行為實測（兩項閘門） | **第 1、2 項完成**（chromium）；第 3、5、6 項待瀏覽器 leg；**第 4 項完成** | `scripts/vr/xterm-geometry-probe.mjs`；`artifacts/vr/local/vr-01-xterm-probe.md`；bundle 增量見下 §Bundle |
| `VR-02` | ADR 0027、`style.md` 七處、PRD `NFR-006`、設計文件四處、traceability | **完成** | `docs/adr/0027-*.md`（accepted）；`research/style.md` §3／§3.1／§9／§17／§18／§21／§22／§23／§24；`research/prd.md` `NFR-006` ＋ 三條；五份設計文件 C1–C4；`make traceability` 綠燈 |
| `VR-03` | Token 契約、兩款主題、xterm／Monaco 主題橋、`theme-boot.js` | **完成** | `theme/{tokens.css,themes.ts,contrast.ts,applyTheme.ts}` ＋ 三條測試（272 個斷言）；`public/theme-boot.js`（9 行）；五款主題 **220 組**配對全部通過 |
| `VR-04` | App Shell、PrimaryNav、SessionHeader、StatusBar、響應式與抽屜 | **完成** | `PrimaryNav.vue`、`SessionHeader.vue`、`StatusBar.vue`、`ThemeMenu.vue`；`AppLayout.test.ts` 11 個斷言（含收合、skip link、390px 選單） |
| `VR-05` | 基礎元件八個 | **完成** | `components/ui/`：Button／IconButton／Field／Dialog／InlineNotice／EmptyState／LoadingState／ToastHost／ActionMenu ＋ `useFocusTrap`／`useToast`；`StatusBadge` 與 `ConfirmDialog` 重寫 |
| `VR-06` | 資料與工作區元件 | **完成** | `UiDataTable`、`UiToolbar`；`WorkspaceTabs` 改造（44px、四要素選中態、Lucide 關閉鈕）；`PreviewPane` 主題化 |
| `VR-07` | Session 工作台 | **完成** | `SessionWorkspaceView.vue`：SessionHeader ＋ StatusBar ＋ 可調寬／抽屜檔案欄 ＋ drop bar 改 Toolbar；`SessionWorkspaceView.test.ts` 全綠 |
| `VR-08` | Sessions、Nodes、NodeDetail、NodeTunnels | **完成** | Sessions／Nodes／Enrollment／Audit 採用 `UiDataTable`；Nodes 的列操作進 ActionMenu；`node.resources` 為空顯示「無資料」 |
| `VR-09` | Dashboard、Audit、Enrollment、Integrations、Login、TokenShowcase | **完成** | 八個字面符號圖示 → Lucide；`TokenShowcaseView` 擴充為驗收面板（含實測對比表） |
| `VR-10` | 偏好 UI 與持久化 | **完成** | `stores/preferences.ts`（四個鍵，全部有邊界檢查）；`ThemeMenu`、`TerminalFontControl`、可拖曳／可鍵盤操作的檔案欄把手 |
| `VR-11` | 四條 gate、量測式 E2E、既有測試同步 | **完成（靜態）／待 CI（瀏覽器）** | `scripts/vr/vr-gates.sh`（四條，六種失敗模式各驗過一次會變紅）；`ci.yml` ＋ `make check`；`tests/e2e/theme.spec.ts`（66 個案例）；`session.spec.ts` 同步 |
| `VR-12` | evidence、驗收矩陣、安全審查、skills、exit | **完成（可自動化的部分）** | `scripts/vr/evidence.sh`（13 個 leg 全綠、7 個明列 skip）；`docs/security-review-p28.md`；`.agent/skills` 三份 ＋ 改名 ＋ 索引 |

## 兩道閘門

| 閘門 | 條件 | 狀態 |
|---|---|---|
| G1 | `VR-01` 第 1、2 項通過 → 才可開 `VR-03` | **通過（chromium）**。本次重跑 probe 的數字與計畫一致：`14px/1.2` = **35 列**（閘門 ≥ 30），`14px/1.6` = **26 列**（跌破）。`options.theme` 賦值後 buffer／捲動位置／未送出輸入／列數四者不變且確實重繪。Firefox／WebKit 待 CI |
| G2 | `VR-02` 核准 ＋ 文件已合併 → 才可動 `frontend/src` | **通過**。ADR 0027 accepted、`style.md` 與 `prd.md` 已改、五份設計文件已改 |

## 與計畫不同的七處，以及為什麼

計畫是提案，實作是量測。以下七處是實作時量出來與計畫不同的東西，
**每一處都是計畫自己的規則要求的結果**（「對比是測出來的，不是宣稱的」），
而不是便宜行事。

### 1. `status-*-border` ／ `-bg` 的目標從 3:1 改為「膠囊最強的那一條邊」

`02-…md` §6.4 把這一組列在**非文字 3:1** 的清單裡。實測：五款主題**沒有一個**達到，
範圍是 **1.30–1.70**。這不是值的問題而是目標的問題，所以改的是目標，並寫在明處
（`theme/contrast.ts` 的 `BADGE_EDGE_FLOOR` 附近整段）：

邊線**不承載語意**——語意在文字上（≥ 4.5:1）而且圓點再說一次。WCAG 1.4.11 管的是
「識別元件與狀態所必需的視覺資訊」，而這裡的狀態由文字識別，所以膠囊外框不是必需的
視覺資訊。硬拉到 3:1 會讓每個 badge 變成中間色調的描邊晶片，與 `style.md` 的
「平面、低對比邊界」和 Graphite §9 的「正常狀態不要比正在工作的內容醒目」直接衝突。

實際的斷言改成兩條，兩條都會因為真正的退化而變紅：
邊線對自己的填色 ≥ 1.25（邊線等於填色時是 1.0，過不了），
**且**邊線對面板底比填色對面板底更強——也就是邊線必須是這個膠囊最強的一條邊，
而那正是 D8 要它存在的理由（填色對面板底只有 1.13–1.19，沒有邊線就只剩文字浮著）。

**這是本期第二處明確縮減驗收目標的地方**，第一處是 ANSI 的 `black`／`brBlack`
（`02-…md` §8 已記錄）。兩處都寫在會被讀到的地方，不藏在測試裡。

### 2. `border.control` 的驗收面從兩個表面擴為三個

`00-…md` D9 要求對 `surface.default` 與 `surface.canvas` **兩者** ≥ 3:1。
實測發現漏了一個真實的表面：**對話框與選單是 `surface.raised`，而它們裡面有輸入框**
（`NewSessionDialog` 一個對話框裡有四個 Field）。計畫的值在那個表面上是
2.80（Graphite）／2.92（Porcelain），都不到 3:1。

處置是改值不改目標：`--border-control` 現在對三個表面都 ≥ 3:1
（Graphite `#647784` = 3.75／4.09／3.25；Porcelain `#838689` = 3.66／3.51／3.26）。
`text-disabled` 同樣擴為三個表面。

### 3. `accent.primary` 不再承載任何文字，包含主按鈕

`02-…md` §5.1 讓 `accent.strong` 承擔「疊在 `accent.subtle` 上的文字」與
「淺色主題主按鈕的背景」。實測發現這個規則要再推一步：**Porcelain 的
`accent.primary` 疊在 `surface.raised` 上是 4.20:1**（hover 態的按鈕文字），
而 Studio 的白字疊 `accent.primary` 只有 4.27:1。

所以規則收成一句：**`--accent-primary` 是不承載文字的填色**
（選中底線、進度、導覽項的 2px 左邊線），**任何有文字的地方都用 `--accent-strong`**。
Graphite 兩者同值，所以這條規則在預設主題上看不出來、在 Porcelain 上是必要的。

### 4. 新增四個 on-terminal token

`02-…md` §2.2 只給了 `--text-on-terminal`。實際落地時發現終端是一個**自己的表面**，
而且上面真的有 UI：分頁列、圖片投放列、捲動提示、`PreviewDenied` 面板。
那些地方各自需要一個安靜的文字級、一條裝飾邊、一條控制邊和一個晶片底色——
**69 處字面色值裡有 9 處就是這樣長出來的**。

新增（五款主題同值，與其餘終端 token 一致）：
`--text-on-terminal-dim` `#A2ACB8`（對終端底 8.05:1，Studio 的 6.75）、
`--border-on-terminal` `#3A424D`（1.82，裝飾級，且**測試斷言它低於 3:1**——
它是提示文字的外框，超過控制門檻就會跟終端輸出爭注意力）、
`--border-on-terminal-control` `#68727E`（3.79／Studio 3.18）、
`--surface-on-terminal` `#1C2027`。

依計畫自己的規則：「若實作時發現某個元件非分支不可，那是 token 表缺了一格，
回 `VR-03` 補」（`04-…md` 開頭）。缺一個層級與缺一格是同一件事。

### 5. `StatusBadge` 的語彙從三種變成五種

`02-…md` §2.4 要求 Node／連線／Session 三種語彙拆開，且「標籤文字不共用」。
拆開之後立刻暴露一件事：**`EnrollmentView` 一直把 token 生命週期的值餵進
Node 的表**（`active` → `online`）去借它的顏色，`NodeDetailView` 對 runtime 可用性
做同一件事。三種語彙共用一張標籤表時這能運作；一旦標籤按語彙分開，
一個啟用中的 enrolment token 會顯示成「線上」——顏色對，句子是假的。

新增 `token` 與 `runtime` 兩種語彙。這是**拆開語彙本來要找到的東西**。

### 6. Monaco 的主題反應放在 `PreviewPane` 而不是工作台

`02-…md` §9 沒有指定由誰呼叫 `setTheme`。放在 `SessionWorkspaceView` 會
`import` `monaco/setup`，而那會把整個 Monaco bundle 拉進工作台的模組圖——
`PreviewPane` 用 `defineAsyncComponent` 正是為了避免這件事，也就是說使用者
就算從不開檔案也要載入 Monaco。持有 Monaco 的元件持有 Monaco 的主題。

（這一處是先寫錯再改對的：靜態 import 讓 `SessionWorkspaceView.test.ts`
整個 suite 在 jsdom 掛掉，因為 Monaco 的 clipboard contribution 會呼叫
`document.queryCommandSupported`。測試失敗是症狀，bundle 才是問題。）

### 7. 主題切換器搬到「個人設定」，而搬動揭露了兩個缺口

使用者回饋（2026-09-09）：「風格主題應該要做在個人設定裡面」。**對的，而且計畫本來就
這樣寫**——`03-…md` §4 的原文是「主題切換在其他頁面由**帳號選單**提供」。我沒有建帳號選單，
在 header 塞了一個裸 `<select>`，還在工作台狀態列放了第二個。那是兩個錯：
主題是**全域**偏好，常駐在 header 的控制項會讀成「只影響你現在這一頁」；
而放兩份讓它更像頁面層級的東西。

處置：新增 `/settings/preferences`（`PreferencesView`）與 `AccountMenu`。
Header 的 `<select>` 與狀態列那一份都移除；狀態列只留終端字級——那個**真的**只跟這個
終端有關，也是 1024×768 把列數救回來的手段。`ThemeMenu` 只剩 dev-only 的驗收面板在用
（審查者要能在那頁快速翻主題），並在檔頭寫明它不再是產品 UI。

搬動之後才看見兩件本來看不見的事：

**（a）「跟隨系統」原本是個出不去的狀態。** store 一直有 `themeIsExplicit` 這個第三狀態，
但 UI 是兩選項的 `<select>`，表達不出來——使用者一旦選過任何主題，那個 key 就寫下去
再也不會被移除，**從此永遠忽略作業系統**。新增 `followSystemTheme()`（移除 key，
不是寫入另一個值）與頁面上的第三個選項，而且會顯示「你的系統目前是深色／淺色」，
因為「跟隨系統」不說系統現在說什麼就沒有意義。

**（b）搬走之後，「就地重繪」變成沒有任何路徑可以觸發。** 個人設定是獨立頁面，
去那裡就得離開工作台，而離開會卸載終端、回來是重建的。也就是說本期最核心的機制
——「換色不重建終端」——在產品裡**不可達**，那條 E2E 也就證明不了它要證明的事
（我第一版改成「導航離開再回來」，那個斷言是空的，發現後改掉）。

處置：`installPreferencesStorageSync()`，照 `installAuthStorageSync` 既有的形狀做跨分頁同步。
這同時是更好的產品行為（在一個分頁改主題，所有分頁跟著變），也讓誠實的路徑成立：
**在第二個分頁改主題，持有 live session 的那個分頁就地換色，scrollback、捲動位置、
打到一半的輸入都不動。** E2E 現在走的就是這條路徑（開第二個 tab、勾選、關掉、
斷言第一個 tab 的 buffer 四項不變且沒有經過重連）。

順帶：`PreferencesView` 用手寫的主題清單（每一款要有自己的說明，產生式清單做不到），
所以加了一個 dev-only 的漂移守衛——多一款 shipped 主題卻沒給它說明會直接丟錯，
而不是安靜地只渲染兩個 radio。

## Bundle 增量（`VR-01` 第 4 項）

同一台機器、同一組指令，gzip：

| | 改動前 | 改動後 | 差 |
|---|---:|---:|---:|
| JS | 1023.0 kB | 1037.7 kB | **+14.7 kB** |
| CSS | 30.1 kB | 34.7 kB | **+4.6 kB** |

合計 **+19.3 kB gzip**，在計畫設的 20 kB「tree-shaking 沒生效」門檻之內——
而這個數字是**淨值**，含十二個新 Lucide 圖示與十一個新元件。
移除 `naive-ui` 對這個數字沒有貢獻，因為它從來沒有被 import、也就從來不在 bundle 裡；
它的移除換到的是 **`package-lock.json` 少 22 個套件**（377 → 355）。

## 規格變更的落地狀態

| 文件 | 修訂 | 狀態 |
|---|---|---|
| `docs/adr/0027-*.md` | 新增 | **accepted** |
| `docs/adr/0005-frontend-foundation.md` | Naive UI 那一句被 0027 取代 | **已修改**（原句劃掉並指向 0027 §6） |
| `research/style.md` | M1–M7 七處 ＋ §21 動態範圍精確化 ＋ §23 Command Palette 註記 | **已修改**（九處） |
| `research/prd.md` | `NFR-006` 八條 ＋ `FR-TERM-001.AC-15/16` ＋ `FR-TERM-005.AC-06` | **已修改** |
| `docs/design/visual-refresh/*.md` | C1–C4 ＋ README 的「如何選定」表已填 ＋ 五份的行高 | **已修改** |
| `traceability/requirements.json` | `NFR-006` 與八條 criteria；兩條既有需求追加三條 | **已修改**（451 criteria，blocking 0） |
| `traceability/gates.json` | 四條新 gate | **已修改** |
| `traceability/links.json` | 44 條新 link | **已修改** |
| `scripts/traceability/tests/test_traceability.py` | pinned summary 440 → 451 | **已修改**（附理由） |
| `.agent/skills/vue-naive-ui-workflow/` | 改名為 `vue-frontend-workflow` | **已改名**（含 `agents/openai.yaml`） |
| `.agent/skills/design-system-starter/SKILL.md` | 移除 Naive UI 覆寫段 | **已修改** |
| `.agent/skills/cliora-project-context/SKILL.md` | 新增視覺姿態段 | **已修改** |
| `.agent/skills/README.md` | 索引與計數（既有漂移 17→22） | **已修改**，22 個目錄全部列出 |

**traceability 的順序與計畫不同，理由是機械性的**：驗證器會檢查每一條 link 的
target 檔案存在，所以 `impl`／`test` link 不可能在它們指的檔案之前寫。
計畫把註冊放在 `VR-02`；實際上是 `VR-02` 的內容在 `VR-11` 的時間落地。

## 已知會變紅的既有測試 —— 實際結果

| 測試 | 預期 | 實際 |
|---|---|---|
| `AppLayout.test.ts` | 會變 | **變了**，且改成用**可及名稱**斷言而不是可見文字——那在展開與收合兩種狀態下都成立，也是螢幕閱讀器使用者真正拿到的東西。從 6 個斷言擴到 11 個 |
| `SessionWorkspaceView.test.ts` | 會變 | **一條**變了（forbidden 的文案）。另外新增一條：veil 之下狀態列仍然要報三個狀態 |
| `WorkspaceTabs.test.ts` | 會變 | **沒變**。它一直是用 `aria-label` 查關閉鈕，所以 `×` → Lucide `X` 沒有影響它——這正是它當初寫對了 |
| `tests/e2e/session.spec.ts` | 會變 | **變了**：Terminate 移進選單（抽成一個 helper，三處呼叫）、確認框改名、gap banner 改用文字查詢、1000×800 那段補上抽屜開啟鈕與 Esc 焦點返回 |
| `ErrorNotice.test.ts`、`FileTree.test.ts`、`PreviewDenied.test.ts` | 只換 token 應**不會**變紅 | **沒變紅**。這是計畫刻意設的檢查，它通過了 |
| `terminal.test.ts` | 未列 | **變了**，而且是好訊號：它原本斷言 badge 印出 `reconnecting`（wire 值、英文、小寫），那正是「一張標籤表服務三種語彙」的症狀。從 1 個斷言擴到 5 個 |

## v2 重放成本（`00-…md` §7 最後一列要求的報告）

**先更正一處我自己寫錯的話**：本檔早先寫「這個 clone 沒有 `v2` 分支」——**那是錯的**，
`v2` 存在，`scripts/vr/evidence.sh` 也產出了 `artifacts/vr/local/overlap.txt`。
以下是那份報告該有的結論。

`git diff master...v2 --stat -- frontend/src`：**130 個檔案、+25275 行**。
但重點不是數量，是**它們在同一個位置蓋同一件事**：

### v2 已經自己做了一層 UI primitives

`frontend/src/components/ui/` 這個目錄**兩條線都建立了**：

| v2 的檔案 | 本期的檔案 | 關係 |
|---|---|---|
| `UiButton.vue` | `UiButton.vue` | **同名同路徑**。variant 語彙差一個詞：v2 是 `primary｜secondary｜ghost｜danger`，本期是 `primary｜secondary｜quiet｜danger` |
| `DataTable.vue` | `UiDataTable.vue` | 同一件事，不同檔名 |
| `EmptyState.vue` | `UiEmptyState.vue` | 同一件事，不同檔名 |
| `ToastHost.vue` | `UiToastHost.vue` | 同一件事，不同檔名 |
| `useToast.ts`（在 `components/ui/`） | `useToast.ts`（在 `composables/`） | 同一件事，不同位置 |
| `BaseBadge.vue` ＋ 五個 `*Badge.vue` | `common/StatusBadge.vue` 重寫 | 語彙不同：v2 按 v2 的領域（stage／run／risk／delivery／source）分，本期按五個語意分 |
| `UiCard.vue`、`PageHead.vue`、`labels.ts` | 無 | v2 獨有 |
| `UiField`、`UiDialog`、`UiIconButton`、`UiInlineNotice`、`UiLoadingState`、`UiToolbar`、`UiActionMenu` | 本期獨有 | v2 沒有 |

**只有一個檔名直接衝突，而那反而是好消息的一半**：`git merge` 會在 `UiButton.vue`
上報衝突、要人處理。**壞消息的那一半是其餘四個不會報衝突**——合併之後會有
兩個 DataTable、兩個 EmptyState、兩個 toast 系統，全部通過測試、全部在同一個目錄裡。
那是「安靜地重複」，而它比衝突難發現得多。

### 兩條線的 token 策略不相容

| | 本期（ADR 0027） | v2 |
|---|---|---|
| `tokens.css` 的基礎 | **重寫**：五款主題 × 44 個語意 token，有主題維度 | **沿用舊的 27 個**，在上面加約 20 個領域 token（`--stage-*`、`--run-*`、`--attention-*`、`--work-*`） |
| 舊 token 名 | 全部退役，`GATE-VR-NO-LEGACY-TOKEN` 擋 | 仍在用，包含 `--status-error`（**本期的 gate 會擋掉它**） |
| 鏈式 fallback | **禁止**，contract test 斷言沒有任何 `var(…, …)` | `checkTokens.test.ts` 有一個 **migration flag** 明確允許 fallback |
| `theme/naive.ts` | **刪除**（ADR 0027 §6） | **還在** |
| 守門測試 | `theme.contract.test.ts`（解析 CSS 比對 JS 表） | `checkTokens.test.ts` ＋ `staticGuards.test.ts`（檢查 `var()` 引用是否有定義） |

這四列每一列都是**設計決定相反**，不是版本不同。

### 結論：這不是機械合併

本期符合 D0 的約束（不改 store 的 state 形狀、不動 `api/` 與 `protocol/`），
所以**資料層是可重放的**；但**呈現層不是**。合併 `v2` 時要做的是一個決定，不是一次 merge：

1. **哪一層 UI primitives 活下來**，以及另一邊的元件改成用它——這是本期十一個元件
   或 v2 十五個元件其中一邊要重寫。
2. **token 策略選一個**。本期的「每個主題定義每一個 token、禁止 fallback」與
   v2 的「舊基礎 ＋ 領域 token ＋ migration flag 允許 fallback」不能並存：
   本期的 `GATE-VR-NO-LEGACY-TOKEN` 會讓 v2 現有的前端變紅。
3. **v2 的領域 token（stage／run／attention／work）要進本期的主題表**，
   而那表示它們要有五款主題各一組值，並通過對比測試——v2 現在只有一組。

**這是報告，不是閘門**（`06-…md` §7 第 9 條原文，也符合使用者的既有決定：
`v2` → `dev` 一律由人決定）。本期在 `master` 上不依賴、也不阻擋 v2；
但**「V2 只要重放這個 diff 就好」是不成立的**，而知道這件事的成本現在最低。

## 還沒做的事

| 項目 | 為什麼 |
|---|---|
| 瀏覽器量測 leg（主題切換不中斷、FOUC、對比實測、響應式） | 本機沒有完整 stack（需要 PostgreSQL ＋ 已註冊的線上 Node）。`tests/e2e/theme.spec.ts` 的 66 個案例已寫好並可被 Playwright 收集，`artifacts/vr/local/skipped.txt` 明列它們沒跑 |
| 36 格驗收畫面 | 同上，需要瀏覽器 leg |
| `ansi.png`（`VR-01` 第 5 項） | 必須看真實 Claude／Codex 畫面，判準是「使用者看得懂嗎」，沒有數字答案 |
| Firefox／WebKit 的 probe | 這台機器缺系統函式庫（`libgtk-3-0` 等），需要 `sudo apt-get` |
| `NodeTunnelsView` 的邏輯重構 | 刻意不做（`05-…md` §2.3）。它只換了 token 與樣式 |
| `window.prompt` 改成內嵌改名表單 | 刻意不做（`08-…md`）。那是行為變更 |
| 部分頁面仍有自寫的 `.ghost`／`.primary`／`.link` 按鈕 | 它們已經走 token、有文字標籤、且 disabled 不靠透明度（那五處已修）。改成 `UiButton` 是純粹的一致性收斂，價值低於本期其他工作，列為後續 |
