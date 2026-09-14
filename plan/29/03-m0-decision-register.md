# 03 — M0 決策登記簿（`MS-D-*`）

`02-rollout-and-verification.md` 的 M0 只列出「要決定哪些事」，沒有列出**可以被否決的提案答案**。
沒有提案答案的決策清單會在實作啟動時變成第二輪討論，而 M1 的每一張票都擋在它後面。

本文件把每一項 M0 決策寫成：**選項 → 提案 → 理由 → 影響檔案 → 誰決定**。
提案是提案，不是已核准的政策；`01-mobile-addendum-v0.1.md` 的狀態仍是 **Proposed**。
唯一不重開的是 #62 已核准的方向：**行動版固定明亮、桌面主題政策不變**（`MS-D-04`／`MS-D-05`／`MS-D-06`
只處理「用什麼機制落實」，不處理「要不要明亮」）。

決策未定 = 對應的 `MS-*` 票不得開工。對應關係見每一列的「擋住」欄。

---

## MS-D-01 行動版進入點

| | |
|---|---|
| 問題 | 行動裝置登入後第一個畫面是 `/`（現況 dashboard redirect）還是 `/sessions`？ |
| 選項 | (a) 不動 `/`，把 Sessions 放在行動導覽第一項；(b) 依 viewport 改 `/` 的 redirect 目標；(c) 依角色改。 |
| **提案** | **(a)** |
| 理由 | (b) 讓 router 開始認識 viewport，而同一個 URL 在兩種寬度下去到不同頁面是**無法用桌面測試涵蓋的分歧**；`router/index.ts` 的 redirect 是桌面共用路徑，改它等於改桌面。(a) 的成本只是導覽排序，可逆。 |
| 影響 | `router/index.ts`（不改）、`components/layout/PrimaryNav.vue`（排序） |
| 決定者 | M0 產品 owner |
| 擋住 | `MS-03` |

## MS-D-02 Preview 與行動裝置「返回」的關係

| | |
|---|---|
| 問題 | 全幅 preview 是 in-route substate（addendum §1）。但行動瀏覽器的返回手勢／返回鍵此時會**離開整個 session**，而使用者的預期是「關掉 preview」。 |
| 選項 | (a) 不處理，只留 Escape 與關閉鈕；(b) 開啟 preview 時 `history.pushState` 一筆**同 route、無 path 資訊**的 state，`popstate` 關閉 preview；(c) 把 relPath 放進 URL query。 |
| **提案** | **(b)** |
| 理由 | (c) 直接違反 addendum §1／§7：workspace-relative path 會進入瀏覽器歷史與分享連結。(a) 在真實裝置上是主要的誤操作來源（原型用鍵盤驗證，無法證明手勢）。(b) 只推入一筆不帶內容的 state，離開 route 時一併清除，滿足「路徑不落地」同時讓返回鍵可用。 |
| 風險 | `popstate` 與 route 切換的競態：session 切換必須先清 state 再 pop，否則舊 session 的 preview 會在新 session 上被「關閉」。此競態列為 `MS-14` 的驗收條件，不是實作細節。 |
| 影響 | `views/SessionWorkspaceView.vue` |
| 決定者 | M0 產品 owner ＋ M2 terminal writer（共用同一個 view） |
| 擋住 | `MS-08` |

## MS-D-03 斷點定義的唯一來源

| | |
|---|---|
| 問題 | 現況有三處各自寫死寬度：`AppLayout.vue:60`（`< 768`）、`SessionWorkspaceView.vue:318`（`< 1024`）、`SessionWorkspaceView.vue:1298`（`max-width: 1100px`）。 |
| 選項 | (a) 各自維持字面值；(b) 建立 `composables/useBreakpoint.ts` 單一來源，CSS 端以註解標註對應值。 |
| **提案** | **(b)**，四段沿用 VDS：`<768` / `768–1023` / `1024–1439` / `≥1440` |
| 理由 | 1024／1100 的不一致（見 `MS-D-08`）正是「三處字面值」造成的。CSS 的 media query 無法讀 JS 常數，所以 CSS 端仍是字面值，但**只允許出現在 `theme/tokens.css` 註記的四個值**，由 `GATE-MS-BREAKPOINT` 靜態檢查。 |
| 影響 | 新增 `composables/useBreakpoint.ts`；`AppLayout.vue`、`SessionWorkspaceView.vue` 改用它 |
| 決定者 | M1 shell writer 提案、M0 核准 |
| 擋住 | `MS-01`（其餘票皆依賴 `MS-01`） |

## MS-D-04 行動明亮的落實機制

| | |
|---|---|
| 問題 | #62 的方向已核准，但 `theme/tokens.css` 與 `theme/themes.ts` 目前沒有任何 viewport 維度，且現行 Porcelain 的 `--terminal-*` 仍是深色（`tokens.css:288` 附近）。 |
| 選項 | (a) 在元件 CSS 裡覆寫；(b) 在 `tokens.css` 加 `@media (max-width:767px)` 覆寫色彩 token；(c) **新增一個完整 theme id `pocket`**，由選擇層（而非 CSS 繼承）決定行動端套用它。 |
| **提案** | **(c)** |
| 理由 | (a) 被 `GATE-VR-NO-LITERAL-COLOR` 擋下，而且 addendum §6 明文禁止「以元件 CSS 夾帶」。(b) 過不了 JS 端：xterm 的 `terminal.options.theme` 與 Monaco 的 `defineTheme()` 需要**解析後的字串**，CSS media query 給不出來，`getComputedStyle` 在 `display:none` 子樹回空字串（`tokens.css` 檔頭已記錄這個否決理由）。(c) 讓「每個 theme 定義每個 token」的既有不變式原封不動，contract test 的形狀不需要改，只是多一個 theme 區塊。 |
| 影響 | `theme/themes.ts`、`theme/tokens.css`、`theme/applyTheme.ts`、`public/theme-boot.js`、`theme/theme.contract.test.ts`、`theme/theme.contrast.test.ts`、`theme/themes.test.ts` |
| 決定者 | M0 VDS owner（需要一份 ADR 0027 修訂或新 ADR） |
| 擋住 | `MS-18`～`MS-21` |
| 細節 | `07-mobile-light-theme-contract.md` |

## MS-D-05 `pocket` 的觸發條件

| | |
|---|---|
| 問題 | 「行動」用什麼判定：寬度、`pointer: coarse`、UA、還是使用者可關？ |
| 選項 | (a) `(max-width: 767px)`；(b) `(pointer: coarse)`；(c) 兩者 or；(d) 加一個使用者開關。 |
| **提案** | **(a)**，與 `MS-D-03` 的 `<768` **同一條件、同一個 `matchMedia` 字串** |
| 理由 | (b) 在觸控筆電上會把桌面翻成 pocket，那是 #62 沒有核准的範圍擴張。(c) 讓 CSS 斷點與主題斷點分歧，之後每個 bug 都要先問「是哪一條」。(d) 等於重開 #62。以寬度單一條件，代價是「窄視窗的桌面瀏覽器也會變 pocket」——這是**可接受且可觀測**的，並且是唯一能在桌面 CI 裡自動驗的形狀。 |
| 影響 | `theme/applyTheme.ts`、`public/theme-boot.js`、`composables/useBreakpoint.ts` |
| 決定者 | M0 VDS owner |
| 擋住 | `MS-20` |

## MS-D-06 行動端如何對待使用者已存的主題偏好

| | |
|---|---|
| 問題 | 使用者在桌面選了 Graphite，手機開同一帳號時該怎麼辦？ |
| 選項 | (a) 覆寫 `localStorage` 成 pocket；(b) **保留儲存值不動，只是不套用**；(c) 分裝置各存一份。 |
| **提案** | **(b)** |
| 理由 | (a) 會讓使用者回到桌面時發現偏好被手機改掉——一個單向的、使用者沒授權的寫入。(c) 需要一個裝置識別概念，ADR 0027 只允許非識別性偏好。(b) 把「選擇」與「實際套用」分成兩個值：`preferences.theme` 仍是使用者的選擇，新增 `preferences.renderedTheme` 是實際生效值。 |
| 附帶 | `views/PreferencesView.vue` 在 pocket 生效時必須顯示一行說明（「此裝置寬度固定使用行動明亮配色」），否則切換器會與畫面公開矛盾。 |
| 影響 | `stores/preferences.ts`、`views/PreferencesView.vue`、`components/layout/ThemeMenu.vue` |
| 決定者 | M0 VDS owner |
| 擋住 | `MS-20` |

## MS-D-07 冷載入是否避免深色閃爍

| | |
|---|---|
| 問題 | `public/theme-boot.js` 在首次繪製前設 `data-theme`。它目前只認 graphite／porcelain；行動端在無儲存值時會先以 `:root`（Graphite，深色）繪製一幀再被 JS 改成 pocket。 |
| 選項 | (a) 接受閃爍；(b) boot script 加寬度判斷。 |
| **提案** | **(b)** |
| 理由 | 深色閃爍在行動端是整頁的，不是局部。代價是 boot script 變長，而 `theme.contract.test.ts:171` 限制它 **≤12 行程式碼**、且 `GATE-VR-NO-GLYPH-ICON` 在 CI 檢查同一個界限。實測現況 **9 行**（以該測試的計法：去註解後的非空行），加寬度判斷後約 10 行，**在界限內**——這個界限不得為此放寬；若實作後超出，回到 (a) 並記錄，不是改門檻。 |
| 影響 | `public/theme-boot.js`、`theme/theme.contract.test.ts` |
| 決定者 | M0 VDS owner |
| 擋住 | `MS-20` |

## MS-D-08 1024–1100px 檔案欄缺陷的處置

| | |
|---|---|
| 觀察 | `SessionWorkspaceView.vue:318` 的 `filesAreDrawer` 是 `< 1024`，抽屜開關鈕的 `v-if` 也是 `filesAreDrawer`（`:657`）。但 `:1298` 仍留著 `@media (max-width: 1100px) { .workspace-rail { display: none } }`，而 `.workspace-rail` 與 `.rail` 是同一個元素（`:847` `class="rail workspace-rail"`）。**在 1024–1100px：欄位被 CSS 隱藏，而抽屜鈕不渲染。** |
| 現況 | 這是靜態閱讀結論，**尚未在瀏覽器重現**。`02-…md` M0 已要求先重現再宣告缺陷，本表不推翻那條。 |
| 選項 | (a) 刪掉 `:1298-1304` 整個 media block；(b) 把它的閾值改成 1024；(c) 把 `filesAreDrawer` 改成 `< 1100`。 |
| **提案** | 先在 390／768／1000／1023／**1024**／**1100**／1101 重現並存證，確認後採 **(a)** |
| 理由 | (b)/(c) 只是把兩個字面值再對齊一次，`MS-D-03` 的單一來源會讓 `:1298` 整塊失去存在理由——1024 以上是欄位模式，本來就不該有隱藏規則。 |
| 影響 | `views/SessionWorkspaceView.vue` |
| 決定者 | M1 shell writer（重現證據）＋ M0（確認為缺陷） |
| 擋住 | `MS-05` |

## MS-D-09 鍵盤高度變數的所有權

| | |
|---|---|
| 問題 | 軟體鍵盤升起時可用高度會變。誰擁有這個值？ |
| 現況 | 全 repository **沒有任何 `visualViewport` 或 `env(safe-area-inset-*)` 使用**（已 grep 確認）。`AppLayout.vue:172-176` 的 `.shell` 是唯一的視窗高度擁有者（plan/09 D1）。 |
| 選項 | (a) 各頁自行監聽；(b) **shell 獨佔**，發布一個非持久化的 CSS 變數。 |
| **提案** | **(b)**：`AppLayout.vue` 監聽 `visualViewport` 的 `resize`／`scroll`，寫入 `--viewport-usable-height`；`.shell` 高度改為 `var(--viewport-usable-height, 100dvh)`。 |
| 理由 | plan/09 D1 的整個理由就是「高度只有一個來源」，鍵盤高度是同一個東西的第二個維度，讓它有第二個擁有者會複製 plan/09 修掉的那個 16px 分歧。 |
| 界限 | 不得與 `env(safe-area-inset-bottom)` **重複相減**（`visualViewport.height` 已排除鍵盤但未排除 home indicator，實際疊加行為必須在真機量，列為 `MS-OM-03`）。監聽器在 `onBeforeUnmount` 移除。值不寫入任何儲存。 |
| 影響 | `components/layout/AppLayout.vue`、`theme/tokens.css`（變數宣告） |
| 決定者 | M1 shell writer 提案、M0 核准 |
| 擋住 | `MS-02` |

## MS-D-10 行動終端的輸入形態

| | |
|---|---|
| 問題 | 手機上使用者實際打字的是哪個元素：xterm 自己的隱藏 textarea，還是一個獨立的輸入列？ |
| 選項 | (a) xterm 原生隱藏 textarea ＋ 一列特殊鍵輔助列；(b) 獨立輸入列，送出時才寫入 PTY；(c) 兩者可切換。 |
| **提案** | **由 M1 的獨立 IME spike 決定；預設假設 (a)** |
| 理由 | (b) 會讓互動式提示（`y/n`、密碼、`less`、tmux prefix）全數失效——那些需要逐鍵到達 PTY，而「送出」語意假設了行導向。但 (a) 的繁中 IME 在 iOS Safari 上是否會重複送出 `compositionend` 的內容，**沒有任何現成證據**，所以這一格不是決策而是**待測量**。 |
| 不得 | 在 spike 出證據前實作任一形態；也不得因為 (a) 較省事就略過 spike。 |
| 影響 | spike 目錄（獨立、預設不合併） |
| 決定者 | M2 terminal writer，依 spike 證據 |
| 擋住 | `MS-12`（`MS-11` spike 本身不被它擋——是它依賴 spike） |

## MS-D-11 保留範圍與 analytics 排除

| | |
|---|---|
| **提案** | 沿用 addendum §1／§7 全文：只保留 workspace-relative path 與最多 8 筆 preview 位置，記憶體內；terminal bytes 與檔案內容不得進入任何錯誤回報、log、截圖自動化或 ticket query。 |
| 需確認 | 現行是否已有前端錯誤回報管道會夾帶 route 參數（`/sessions/:id` 含 session id）。這是既有問題而非本期造成，但行動推出前要有 disposition。 |
| 決定者 | M0 ＋ 安全 reviewer |
| 擋住 | `MS-24` |

## MS-D-12 推出旗標的名稱與所有權

| | |
|---|---|
| **提案** | `mobile_ia`，伺服器／部署控制，預設 off，由 release owner 擁有；只選擇「認證後的導覽與呈現」，不授予能力、不改端點、不鑄 ticket、不改 RBAC、不改 node posture（`02-…md` §6 已定義行為，本表只定名與歸屬）。 |
| 決定者 | Release owner |
| 擋住 | `MS-25` |

## MS-D-13 需求編號

| | |
|---|---|
| 問題 | 本期要不要有自己的需求 ID，還是掛在 `NFR-006`（介面可及性與視覺主題，owner `frontend`）之下？ |
| **提案** | 新增 **`NFR-007` 行動視窗操作性**，owner `frontend`，source `research/prd.md#nfr-007`；`pocket` 主題的對比與 token 契約掛在既有 `NFR-006` 之下，不另開。 |
| 理由 | 行動可操作性（觸控目標、安全區、鍵盤遮擋、無水平溢位）與「視覺主題」是不同的驗證剖面，混在一個 ID 下會讓 `scripts/trace` 的覆蓋率報表看不出缺口。 |
| 影響 | `research/prd.md`、`traceability/requirements.json`、`traceability/links.json` |
| 決定者 | M0 產品 owner |
| 擋住 | `MS-25` |

## MS-D-14 上傳是否納入本期

| | |
|---|---|
| **提案** | **納入 M3 尾端，且只做觸控可達性**：`useFileUpload` 的 W1–W4、伺服器 `can_upload_files` ＋ node veto、配額、稽核、永不覆寫，全部不變。若 M3 檔案票延期，上傳整張票**移出本期**而不是壓縮驗收。 |
| 理由 | ADR 0026 的寫入面是本期唯一的非唯讀表面，它的風險與其餘票不同級，必須可以被單獨切掉。 |
| 決定者 | M0 ＋ 安全 reviewer |
| 擋住 | `MS-17` |

---

## 決策狀態表

全部為 **提案（proposed）**；本 PR 不核准任何一項。

| ID | 主題 | 狀態 | 擋住 |
|---|---|---|---|
| MS-D-01 | 行動進入點 | proposed | MS-03 |
| MS-D-02 | preview 與返回鍵 | proposed | MS-08 |
| MS-D-03 | 斷點單一來源 | proposed | MS-01（全期） |
| MS-D-04 | 明亮落實機制 | proposed | MS-18～21 |
| MS-D-05 | pocket 觸發條件 | proposed | MS-20 |
| MS-D-06 | 既有主題偏好 | proposed | MS-20 |
| MS-D-07 | 冷載入閃爍 | proposed | MS-20 |
| MS-D-08 | 1024–1100 缺陷 | 待重現 | MS-05 |
| MS-D-09 | 鍵盤高度所有權 | proposed | MS-02 |
| MS-D-10 | 輸入形態 | **待測量**（spike） | MS-12 |
| MS-D-11 | 保留與 analytics | proposed | MS-24 |
| MS-D-12 | 推出旗標 | proposed | MS-25 |
| MS-D-13 | 需求編號 | proposed | MS-25 |
| MS-D-14 | 上傳範圍 | proposed | MS-17 |
