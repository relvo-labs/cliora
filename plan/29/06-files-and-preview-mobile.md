# 06 — 檔案瀏覽與預覽的行動形態（`MS-14`～`MS-17`）

對應 **M3 file writer** 寫入集。依賴：M2 合併完成（`02-…md` §1 的排序，避免導覽與檔案 writer 同時碰工作台外殼）。
本階段**不改** `contracts/`、daemon、或任何 API 形狀。

## 0. 現況與原型之間真正的差距

`01-mobile-addendum-v0.1.md` §2 把檔案部分寫成「調整既有元件」，但有一處落差值得先寫明白，
否則 M3 會在實作中才發現要改的比預期多：

**正式版是樹，原型是逐層資料夾瀏覽器。**

`composables/useFileTree.ts` 產出的是一份扁平化的**樹列**（`TreeRow`，含 `root`／`entry`／`status`／`more` 四種 kind，
有 `ancestorsOf()`、有 `expandable`、有展開狀態）。`FileTree.vue` 渲染的是一棵可展開的樹，根列是 workspace。
原型（與 #64 參考的 C）呈現的是**一次一層**：目前資料夾的內容 ＋ 上一層 ＋ 麵包屑。

好消息是**資料層不必改**：`stores/files.ts` 的 `loadDir(key)` 本來就是「以 rel_path 為 key 逐個資料夾載入」
（`:189-215` 帶 `truncated`／`next_cursor`），`useSession`／`clearForSession`／`abortInflight`（`:138-148, 315`）
也已經是精確 session 綁定。所以：

**決定**：新增一個行動專用的呈現層 composable（暫名 `useFileBrowser`），**與 `useFileTree` 並存、共用同一個 store**。
不改寫 `useFileTree`，不讓它同時服務兩種形態。

理由：把樹與逐層瀏覽塞進同一個 composable，會讓 `expandable`／`ancestors`／`more` 這幾個只有樹需要的概念
在行動端變成死程式碼，而死程式碼在下一次改動時會被當成有人依賴。兩個呈現層、一個資料層，是較小的重複。

## MS-14 行動檔案瀏覽

寫入：新增 `composables/useFileBrowser.ts`、新增行動瀏覽元件；`stores/files.ts` **唯讀使用，不改**。

- 呈現目前資料夾一層的內容；「上一層」與相對路徑麵包屑；**永不**顯示絕對路徑（ADR 0014）。
- 麵包屑在窄螢幕以中段省略，兩端（workspace 根與目前資料夾）保持可見且可點。
- `truncated` 為真時顯示真實的「載入更多」延續（帶 `next_cursor`），**不得**把被截斷的一層標示為完整。
- 每列 ≥ 44px 命中區（`MS-01` 的 `--density-row: 52px` 已涵蓋）。
- session 切換：沿用 `clearForSession` ＋ `abortInflight`，**舊 session 的遲到回應不得落地**——這是既有的 load-bearing 行為（addendum §2），行動端不得繞過。
- 空資料夾與「搜尋無結果」是**兩種不同訊息與不同下一步**，不得共用同一個空狀態。
- session 已結束：不向 daemon 發出瀏覽請求，也不顯示一個按了沒用的重試鈕。

## MS-15 檔名搜尋的行動形態

寫入 `components/file/FileSearchBar.vue`（行動版面）；搜尋語意**完全不動**。

現行 `FileSearchBar.vue` 已經做對了關鍵的兩件事：`STOP_REASONS` 四種原因各有文案（`:30-41`），Escape 清除（`:71`）。
行動端要補的是**範圍不能被誤讀**：

- 搜尋涵蓋**目前 session 的整個 workspace**，不是目前資料夾。`useFileTree.ts:463` 是
  `search: (keyword) => store.runSearch(keyword)`，**不傳 `root`**（`stores/files.ts:262` 的 `root?` 為選用）。行動端必須維持不傳，且 UI 上要有明確的範圍標示。
  在一個「目前資料夾是 `src`」的畫面上放一個搜尋框，預設讀法就是「搜尋 `src`」，這個誤讀必須用文字擋掉。
- 只做**檔名 substring、大小寫不敏感**。UI 文案不得暗示全文搜尋。
- `partial` 為真時，四種 `stopped_reason` 的字面意義（`results`／`depth`／`scanned`／`timeout`）與 `scanned_count` 必須可見。
  行動端空間小不是省略它們的理由——不完整的結果看起來像完整的結果是本期最嚴重的失真。
- 搜尋框在鍵盤升起時不得被遮住（`MS-02`）。
- 從搜尋結果點進檔案再返回時，query 與結果清單捲動位置還原（`MSP-F-005` 的 fixture 形狀，正式版由 `MSP-R-006` 驗）。

## MS-16 全幅唯讀預覽

寫入 `components/file/PreviewPane.vue`、`components/file/PreviewDenied.vue`、`composables/useMonacoModel.ts`。

- 行動端 preview 是**全幅**，是 files 的子狀態（`MS-07`），返回鍵行為見 `MS-08`。
- **能力範圍不變**：UTF-8 TEXT／CODE 唯讀，行號、換行、尋找、複製、重新整理、跳行（平台支援範圍內）。
  `PreviewPane.vue:64` 已註明 `readOnly` 與 contribution 清單不得動（ADR 0015）。**本期不新增任何預覽型別。**
- 工具列在窄螢幕折成單列圖示，每個 ≥ 44×44；貼底時自行處理 `env(safe-area-inset-bottom)`。
- 拒絕態沿用 `PreviewDenied.vue` 既有分類，一個都不得合併：
  `FILE_TOO_LARGE`（顯示實際大小與 2 MiB 上限，且不讀完整內容）、
  `FILE_BINARY`（**圖片屬於此類，不渲染**）、
  `reason=unsupported_encoding`（與二進位分開說明）、
  `FILE_PERMISSION_DENIED`、敏感／未知分類（不洩漏片段、絕對路徑或帶密的檔名）、
  不存在／無效／超出根目錄（用不利於路徑試探的措辭）、
  暫時性中繼失敗（常駐的行內錯誤 ＋ 誠實的重試）。
- **內容先清再換**：載入中、拒絕、session 切換三種情況，舊內容都必須在新狀態出現**之前**消失。
- Monaco model 與捲動位置上限 8 筆 LRU，離開時 dispose（`useMonacoModel.ts` 既有契約）。
- 開啟 preview 的那個控制在關閉後取回焦點。

## MS-17 上傳（條件性，可整張切除）

依賴 `MS-D-14`。寫入 `components/file/FileTree.vue`、`FileTreeToolbar.vue`、`composables/useFileUpload.ts`。

**只做觸控可達性，不動安全契約。** ADR 0026 的 W1–W4、伺服器 `can_upload_files` ＋ node veto、
配額與剩餘空間、稽核、**永不覆寫**，全部原樣。

- 只有當伺服器能力與 node posture **都**允許時才顯示；UI 隱藏只是 affordance，授權仍在伺服器。
- 觸控選檔器必須可達（行動端沒有拖放）。
- **不新增** 編輯、重新命名、刪除、下載、SFTP。

若 M3 進度落後，本票**整張移出本期**，不得用壓縮驗收的方式硬塞。這是本期唯一的非唯讀表面。

## 寫入集與界線

| 票 | 檔案 |
|---|---|
| MS-14 | `composables/useFileBrowser.ts`（新）、行動瀏覽元件（新） |
| MS-15 | `components/file/FileSearchBar.vue` |
| MS-16 | `components/file/PreviewPane.vue`、`components/file/PreviewDenied.vue`、`composables/useMonacoModel.ts` |
| MS-17 | `components/file/FileTree.vue`、`FileTreeToolbar.vue`、`composables/useFileUpload.ts` |

M3 file writer **不得**碰終端傳輸或 shell 生命週期。
`stores/files.ts` 在本期是**唯讀依賴**：若實作中發現非改不可，停止本票並交還 M0——那代表 addendum §2 的
「exact-session abort/wipe 是 load-bearing」這個假設有問題，而那是決策而非實作。
