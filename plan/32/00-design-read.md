# 00 — Design Read：現況手機介面

## 1. 方法：拍的是真的 bundle，不是重畫

| 項目 | 做法 |
|---|---|
| 程式 | master `1c73568` 的 `frontend/`，`vite build` 輸出到 repository 外（`/opt/data/cache/scratch/75/dist`） |
| 瀏覽器 | Chromium headless shell rev 1234，`isMobile` ＋ `hasTouch`，`deviceScaleFactor: 2`，reduced motion |
| Central | 以 Playwright `context.route` 全數攔截：靜態檔從 dist 回、`/api/**` 回合成 JSON（`/auth/me`、`/sessions`、`/sessions/:id`、`/nodes/:id` posture、`/files/tree`、`/files/content`…），**沒有啟動任何伺服器** |
| 終端 | `context.routeWebSocket` 送 `terminal.role`、一段合成 ANSI、以及 `terminal.gap`／`terminal.exited`／斷線 |
| 尺寸 | 390×844 為主；360×780、430×932、844×390 |
| 輸出 | `/opt/data/cliora-mobile-75-run/shots/current/*.png`、`metrics.json`、`measure.json`（不進 repo） |

模式沿用 `frontend/tests/e2e/binary-preview.harness.ts`（真 bundle、假 Central），腳本在
`/opt/data/cache/scratch/75/capture-current.mjs`，不提交。

**已知的模擬假象**（不當成發現）：斷線情境裡，模擬的 WebSocket 在重連後再送一次同一畫面，
所以截圖中輸出重複了一次；真實 relay 送的是 snapshot，不會這樣。

## 2. 量到的數字

390×844，writer、已連線、無通知：

| 層 | 高度 | 內容 |
|---|---:|---|
| App header | 56 | 漢堡鈕、「Cliora」、頭像＋姓名＋角色 |
| Session header | 48 | 名稱、posture 膠囊、`⋯` |
| 「顯示 Session 資訊」 | （疊在上一層下緣） | 11px 文字按鈕，padding 0 |
| 終端機／檔案 切換 | 54 ＋ 8 | 灰底兩段式大按鈕 |
| CLI／TERMINAL 分頁 | 44 | 第二排分頁，英文大寫 |
| 圖片投放列 | 44 | 「投放圖片」＋「可貼上（Ctrl+V）、拖放…」 |
| **終端機** | **536（28 列）** | 從 **y=267** 開始 |
| 狀態列 | 28 | 三個 20px 膠囊，標籤在 <768 視覺隱藏 |

外框合計 **295 / 844 = 35%**。360×780 只剩 24 列，844×390 橫向只剩 **8 列**（見 D8）。
有 gap 通知時終端再少 3 列（25 列）。

## 3. 缺陷（有證據、非本期造成、本期不修）

這些是「程式沒有做到既有決策」，不是設計偏好。每一條都附重現方式；修復屬於另開的實作票。

| # | 觀察（量測） | 位置 | 為什麼重要 |
|---|---|---|---|
| **D1** | 390×844、`data-theme="pocket"`、`--terminal-background: #ffffff`，但 `#panel-cli .xterm-viewport` 背景是 `rgb(16, 20, 22)` | `SessionWorkspaceView.vue:545-548` 以 `preferences.theme`（使用者選的）建立 xterm；`:994-1008` 的 `renderedTheme` watch 沒有 `immediate`，冷載入時不觸發 | #62 已核准「手機終端明亮」；issue 附圖的「深色 xterm 與淺色頁面割裂」就是它。`mobile.spec.ts` 只讀 CSS 變數，沒讀 xterm 實際底色 |
| **D2** | 同條件下 Monaco 背景 `rgb(16, 20, 22)` | `PreviewPane.vue:212-216` watch 的是 `preferences.theme` | 同上；`plan/29/07` §0.2 的 `base: "vs"` 分支寫好了，但拿到的 id 不是 pocket |
| **D3** | Viewer（可接管）或需要重連時，`main.scrollWidth` 421／431 > 390：「取得控制權」／「重新連線」把標頭撐寬，整個工作區右緣被裁掉 | `SessionHeader.vue` `.actions { flex-shrink: 0 }` ＋ posture 膠囊 ＋ 名稱 | 最需要按的那顆鈕出現時，版面壞掉；document 層的 overflow 檢查抓不到，因為 `main` 自己裁掉了 |
| **D4** | 清單卡片路徑 `/srv/demo/demo-web-refactor` 顯示成 `srv/demo/demo-web-refactor/` | `SessionsView.vue` `.card-path { direction: rtl }` | 開頭的 `/` 被雙向演算法搬到尾端；路徑看起來像相對路徑 |
| **D5** | 卡片第三行顯示 `s.node_id`（正式環境是 UUID），不是 Node 名稱 | `SessionsView.vue` 卡片 `.card-meta` | 手機上唯一能分辨「哪台機器」的地方，放的是 36 字元 id |
| **D6** | `<768` 仍出現 `TERMINAL`（system shell）分頁 | `SessionWorkspaceView.vue` `tabs` computed 不看寬度 | 與 `plan/29/01` §2、`05` §0「System shell 在行動端不暴露」不一致。**是文件要改還是程式要改，是產品決策**（Q2） |
| **D7** | 建立 Session 對話框全英文（New session／Node／Start／Cancel），且選 Node 前後都不顯示 posture | `NewSessionDialog.vue:209, 347, 350`（靜態閱讀：檔內無 privileged/sandbox 字樣） | 語言混用；可提權 Node 在「建立之前」沒有被說出來 |
| **D8** | 844×390 橫向落入 ≥768 桌面版：側欄、Porcelain、**深色終端**、終端 152px ≈ 8 列 | `useBreakpoint` 只看寬度 | 手機轉橫是常見動作；得到的是最擠的桌面版 |
| **D9** | Session 已結束時，狀態列仍寫「你有控制權」、「投放圖片」仍可按 | `StatusBar.vue` 控制權只看 `role`；drop bar 條件不看 `sessionEnded` | 控制權在已結束時沒有意義，卻顯示成最強的藍字 |
| **D10** | 403／載入錯誤時，灰色 veil 蓋掉整個工作區，標頭也不見；返回清單只能靠漢堡選單 | `SessionWorkspaceView.vue` `.veil` | 錯誤畫面沒有「回去」；也看不出是哪個 Session 失敗 |

D1、D2 與 D8 合起來解釋了「割裂感」：直式時頁面亮、終端暗；轉橫時整個變成桌面。

> 觸控目標：自動量測列出許多「視覺框 <44px」的控制，但 `UiButton`／`UiIconButton` 用 `::after`
> 墊高命中區（`plan/29/04` §0），所以那張清單**不等於命中區失敗**。能確定沒有墊高的是
> 「顯示 Session 資訊」（`.disclose`，padding 0、11px）。本期不把其他項目當缺陷報。

## 4. 痛點地圖

每一列把四件事分開：**觀察**（截圖／量測上看得到的）、**判斷**（對使用者的影響，屬意見）、
**假說**（我們打算怎麼改、預期會怎樣）、**需真機**（模擬器回答不了的部分）。

| # | 觀察 | 判斷 | 假說 | 需真機 |
|---|---|---|---|---|
| P1 外框堆疊 | 六層、295px、35%；終端 y=267 | 首屏在講「App 結構」，不是 Session；這是最像「制式樣板」的地方 | 合併 App header＋Session header，兩排分頁合一，投放列與狀態列移除 → 終端 y≈145、+7～11 列 | 瀏覽器網址列收合、home indicator、鍵盤升起後剩幾列（`MS-OM-06`） |
| P2 兩排分頁兩套詞彙 | 「終端機／檔案」之下又有「CLI／TERMINAL」 | 使用者要理解「終端機」裡還有「CLI」與「TERMINAL」兩種；中英混用 | 一排：「終端機」（主 CLI）＋「檔案」；system shell 移入 `⋯`，開啟後才出現有警示標記的第三分頁 | 無 |
| P3 桌面式投放提示 | 「可貼上（Ctrl+V）、拖放…」常駐 44px | 手機沒有 Ctrl+V 與拖放；文案是桌面的 | 改成分頁列右側一個「附加圖片」圖示鈕，只在 writer＋能力允許時出現 | iOS／Android 的檔案選擇器與相簿權限流程 |
| P4 深淺割裂 | D1、D2 | 明亮決定沒有到達終端，是整頁最刺眼的對比 | 先修 D1/D2（另開票）；原型展示 pocket 調色盤下的樣子 | pocket ANSI 在真實 CLI 輸出的觀感（`MSP-R-009`） |
| P5 狀態放在底部 | 三個 20px 膠囊在最底；接管鈕在右上 | 「能不能打字」的答案離動作最遠，也最小 | 標頭正下方一條「狀態列」：Session／連線／控制權三格仍分開，需要動作時動作就在同一行 | VoiceOver／TalkBack 朗讀順序與 `role="status"` 的播報頻率 |
| P6 膠囊過多 | posture 膠囊＋三個狀態膠囊＋分頁底色＋切換鈕底色 | 每樣東西都有邊框與圓角，層級被抹平（「badge soup」） | 狀態改成「圓點＋文字」不包膠囊；posture 改成一條警示帶（帶圖示），不與狀態混排 | 陽光下的可辨識度 |
| P7 預覽重複與工具列 | 檔名出現三次（分頁、標題、meta）；六顆 44px 帶框按鈕；拒絕態仍顯示整排工具列 | 內容前面先讀三次同一個名字；拒絕時工具列按了也沒用 | 單一檔案列：返回、檔名一次、「唯讀 · Session · 大小」、換行切換、`⋯`；拒絕態不顯示工具 | Monaco 在中階手機的載入與觸控捲動（`MS-OM-08`） |
| P8 清單 | 24px「Sessions」＋標語；重新整理／建立一列；搜尋與 Runtime 各一列；D4、D5；時間 `9/28/2026, 1:00:00 AM` | 標語與兩排按鈕佔掉兩張卡片的高度；時間格式來自 `toLocaleString()` | 標題列放「新建」；搜尋＋篩選同一列；列表用相對時間（`formatRelative` 已存在）＋ Node 名稱 | 時間格式隨裝置語系而變——headless 是 en-US，繁中 iPhone 的實際字樣要真機看 |
| P9 建立流程 | 置中的桌面對話框、英文、無 posture | 手機上像「被塞進來的桌面表單」 | 全螢幕 sheet、繁中、Runtime 用兩顆單選、最近使用的工作目錄可點、選到可提權 Node 時先顯示警示 | 軟體鍵盤是否遮住下方「建立」鈕 |
| P10 橫向 | D8 | 轉橫＝換一個產品 | 以「高度 ≤500 且橫向」判斷手機橫向：標頭、狀態、分頁合成一列（44px），終端 17–18 列 | 旋轉時 xterm fit 與 PTY resize 的實際行為 |
| P11 錯誤與無權限 | D10 | 錯誤畫面是死路 | 保留標頭（返回＋Session id），錯誤卡片沿用 `ErrorNotice` 四段（發生什麼／原因／下一步／request_id），加「回到 Sessions」 | 無 |
| P12 斷線 | 只有底部膠囊變成「重新連線中」，輸出看起來仍是即時的 | 使用者可能對著過時的畫面打字（實際上輸入被擋，但畫面沒說） | 狀態列轉為警示色並說「輸入已停用」；終端上方一條中性說明「輸出已停止更新（最後更新時間）」；**不對終端像素做任何濾鏡** | 背景化回前景後的實際重連耗時（`MS-OM-09`） |

## 5. 值得保留的 Cliora 品牌元素

「不像 AI」不是目標，「不像樣板」才是。以下是現況裡**已經是 Cliora 自己**的部分，三個變體都保留：

1. **「Cliora」字標與終端圖示**：只在清單頁與導覽出現，Session 詳情讓位給 Session 名稱。
2. **Pocket／Porcelain 的近白底、白色面板、深色文字、克制的藍**（`#286bf0` 只做焦點與選取，`#1b54c4` 承載文字）。
3. **狀態三元組語言**（`style.md` §17）：圓點＋文字，warning／error 另帶圖示，永不只靠顏色。
4. **等寬字體只給識別子**：Session id、路徑、指令、檔名——這是「工程工具」而非「聊天工具」的最明顯訊號。
5. **誠實的文案**：`ErrorNotice` 的四段結構、檔案搜尋的「搜尋範圍：整個工作區的檔名，不含檔案內容」、
   `PreviewDenied` 的「下一步」。這種把限制講清楚的語氣，是與通用 AI 介面最大的差別。
6. **三個狀態分開說**（Session／連線／控制權）：`StatusBar.vue` 檔頭寫的理由在手機上一樣成立。

要放掉的是：到處都是的灰底圓角容器、兩段式大切換鈕、英文大寫分頁名、常駐的桌面操作提示。

## 6. 與既有文件的差距摘要

| 來源 | 規定 | 現況 |
|---|---|---|
| `style.md` §18 | Terminal header 僅保留 Session／Runtime／Workspace | 手機上多了 App header、切換鈕、第二排分頁、投放列 |
| `style.md` §12 | 分頁選中以字重＋底線表示 | 手機的「終端機／檔案」用底色，不是底線 |
| `style.md` §17 修訂 | 狀態膠囊高 24px、帶邊線 | 狀態列縮成 20px |
| `plan/29/01` §6、#62 | 手機終端與預覽明亮 | D1、D2 |
| `plan/29/01` §2、`05` §0 | 手機不暴露 system shell | D6 |
| `plan/29/05` MS-07 | `<768` 兩段式「終端機／檔案」 | 做了，但保留了原本的分頁列，變成兩排 |
