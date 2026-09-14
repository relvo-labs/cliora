# 05 — Session 工作台、終端與輸入（`MS-07`～`MS-13`）

對應 **M1 shell writer**（`MS-07`、`MS-08`）、**IME spike owner**（`MS-11`）與 **M2 terminal writer**（`MS-09`、`MS-10`、`MS-12`、`MS-13`）。
依賴：`04-mobile-shell-and-navigation.md` 全部合併，且 `MS-D-02`、`MS-D-10` 有結論。

## 0. 一個必須先講清楚的命名衝突

原型與 addendum 說「行動端的兩個頂層模式是 `terminal` 與 `files`」。
但正式程式的中央分頁型別是 `CentreTab = "cli" | "preview" | "terminal"`（`SessionWorkspaceView.vue:104`），
其中：

| 正式 id | 是什麼 | ADR |
|---|---|---|
| `cli` | **主 CLI**，關閉／離開只 detach，session 續存 | ADR 0012／0013、FR-SESSION-006 |
| `terminal` | **System shell 子行程**，關閉／離頁／route-id 變更／`pagehide` 即終止 | ADR 0021 |
| `preview` | 唯讀檔案預覽（Monaco） | ADR 0015／0024 |

**行動端的「Terminal」指的是 `cli`，不是 `terminal`。** 這兩者的生命週期相反，把名字弄混的後果是
「使用者以為只是關掉分頁，實際殺掉了 shell」或反過來「以為關掉了，其實留著」。

**決定**：行動端模式列舉使用 **`cli` 與 `files`** 兩個 id（與正式程式同名），UI 顯示字樣為「終端機」與「檔案」。
`MobileWorkspaceState.mode` 的值域從 addendum §1 的 `terminal | files | preview` 修正為
**`cli | files | preview`**。這是對 v0.1 的一處具名修訂，需在 M0 一併核准（記為 `MS-D-02` 的附帶項）。
System shell 在行動端**不暴露**（addendum §2 已定），因此不需要第三個 id。

## MS-07 行動模式外殼

寫入 `SessionWorkspaceView.vue`、`components/session/WorkspaceTabs.vue`。

- `< 768px`：`WorkspaceTabs` 改為兩段式切換（終端機／檔案），直接可見，不藏在選單後。
  `preview` **不是第三段**——它是 files 的全幅子狀態，切換器在 preview 開啟時仍在 DOM 但被 preview 覆蓋。
- `≥ 768px`：分頁列維持現況三個 id 與關閉行為，**桌面 DOM 不變**。
- 檔案在行動端是**模式**而不是抽屜：`filesAreDrawer`（`:318`）在 `isNarrow` 為 false，`rail` 佔滿主區。
  抽屜維持在 768–1023（`isTablet`），與 addendum §4「file browser is an accessible overlay/dedicated mode」一致。
- **面板一律 `v-show`，不得 `v-if`**：`:673`／`:761` 現行已是 `v-show`，理由寫在 `:393`——unmount 會拆掉一條活的 WebSocket 與 xterm buffer。行動端切到檔案再切回來屬於高頻操作，這條比桌面更關鍵。
  唯一例外仍是 preview（`:804-808` 註明 Monaco 與 model 需要 dispose）。

## MS-08 preview 的返回鍵行為

依賴 `MS-D-02`。寫入 `SessionWorkspaceView.vue`。

開啟 preview 時 `history.pushState(null, "", location.href)`——**同一個 URL，不帶任何 path 或 query**。
`popstate` 關閉 preview 並還原焦點，與 Escape 走同一個關閉函式。

四個必須成立的條件（皆為 `MS-23` 的驗收項，不是實作備註）：

1. 關閉 preview（Escape、關閉鈕、返回鍵三條路徑）之後，歷史堆疊淨增為 0——連續開關十次不得累積十筆。
2. session 切換（route id 變更）時，**先**清 state、**再**處理歷史；舊 session 推入的那筆不得在新 session 上生效。
3. 離開 route 時把自己推入的那筆一併退出，不得留給下一個頁面。
4. URL 在任何時刻都不含 workspace-relative path（addendum §1／§7）。

`?` 若真機測試顯示 `popstate` 與 vue-router 的導航守衛互相干擾到無法滿足 (2)，則回退到 `MS-D-02` 選項 (a)（只留 Escape 與關閉鈕）並記錄，**不得**改用把路徑放進 URL 的選項 (c)。

## MS-09 終端宿主與 fit

寫入 `SessionWorkspaceView.vue`、`composables/useTerminalSession.ts`。

現行機制已經做對了三件事，本票不重寫它們：

- `fitSafely()`（`useTerminalSession.ts:93`）在容器尺寸不可測時**拒絕量測**，而不是產生垃圾 rows/cols。
- `proposeSize()`（`:119-131`）把 rows 夾在 2–300、columns 夾在 2–500，對齊 `session-start.schema.json`。
- resize 只以 writer 身分送出（`:76`），且只在尺寸真的變了才送（`:103-104`）。

行動端要補的是**何時觸發 fit**：

- 從 `files` 切回 `cli` 之後（面板由 `display:none` 變可見）——隱藏中的終端不可 fit，這是 `fitSafely` 已經在防的情況，但目前沒有「變可見時主動 fit」的觸發。
- 螢幕旋轉（`orientationchange` 或 `matchMedia("(orientation: portrait)")` 的 `change`）。
- `visualViewport` 造成的可用高度變化（`MS-02`）稍停後——**去抖動沿用現行 100ms**（`:135-136`），不另立一套。
- 每次 fit 之後仍走既有的「只送變更過的合法尺寸」路徑，**不繞過 writer 檢查**。

**不得**：因為行動螢幕小就放寬 2–300／2–500 夾限，或在 viewer 狀態下送 resize。

## MS-10 連線、重連與 detach 的行動路徑

寫入 `SessionWorkspaceView.vue`、`composables/useTerminalSession.ts`。

- 每次重連都經 `POST /api/sessions/{id}/attach` 取得**全新單次 ticket**（`useTerminalSession.ts:157-170` 現行行為），行動端的背景／前景切換不得快取或重放 ticket。
- 瀏覽器連線狀態、伺服器 session 狀態、控制權三者**各自獨立顯示**（`MS-06` 已保留 StatusBar 三個狀態）。斷線時既有輸出標為 stale 且輸入停用；**沒有離線佇列，沒有稍後重放**。
- 行動瀏覽器背景化（切 app、鎖屏）：`pagehide` 現行只處理 system shell 終止（`:246-259`）。主 CLI 在背景化時**只 detach**，不 stop——這是 FR-SESSION-006 與 ADR 0012／0013 的既有語意，行動端不得新增任何「自動停止以省電」的行為。
- Snapshot 截斷／gap 必須可見。
- 停止 session 仍是明確、另行授權的確認流程，**不在本期範圍**。

## MS-11 獨立 IME／輸入 spike

依賴 `MS-D-10`。**獨立目錄、預設不合併、不碰任何共用前端原始碼**（`02-…md` §2 的 IME spike owner 界線）。

spike 要回答的是問題，不是實作偏好。每一項都必須產出**事件序列與實際送出的 bytes**，而不是「看起來正常」：

| 編號 | 待測 | 通過條件 |
|---|---|---|
| `MS-S-01` | 繁中注音／倉頡組字 | `compositionstart` 期間**零 bytes** 送出；`compositionend` 恰好送出一次；其後的 `input` 事件不重複送 |
| `MS-S-02` | iOS Safari 與 Android Chrome 的 `compositionend` 差異 | 兩平台的事件順序各自記錄；若不一致，記錄需要的分支條件 |
| `MS-S-03` | 特殊鍵 | Esc／Tab／方向鍵／Ctrl 組合／Enter／PageUp／PageDown 的 byte 序列與桌面 xterm 相同 |
| `MS-S-04` | Ctrl+C | 標示為中斷，**不是複製**；實際送出 `0x03` |
| `MS-S-05` | 輸入模式 vs 選取模式 | 長按選取期間不得發出任何遠端輸入 |
| `MS-S-06` | 多行貼上 | 確認步驟顯示**完整內容與行數**；確認後送出的 bytes 與顯示的完全一致，**結尾不附加 Enter** |
| `MS-S-07` | 取消貼上 | 送出 0 bytes |
| `MS-S-08` | 單行貼上 | 維持瀏覽器原生行為，除非本 spike 產出需要攔截的風險證據 |
| `MS-S-09` | 剪貼簿圖片 | 既有 capture-phase、僅在有 files 時作用的 image-drop 路徑不被破壞，且不影響純文字貼上 |
| `MS-S-10` | `visualViewport` ＋ 鍵盤 | 鍵盤開／關、旋轉、切換輸入法時的可用高度序列 |
| `MS-S-11` | 安全區疊加 | `visualViewport.height` 是否已含 home indicator（`MS-OM-03`） |
| `MS-S-12` | 斷線態 | viewer 或斷線時輸入元件確實停用，且不緩存按鍵 |

spike 報告必須記錄**實機型號、OS 版本、瀏覽器版本**，並明確寫「這是 spike 結果，不是產品完成度」。
spike 不得宣稱任何 `MSP-R-*` 已達成；它只解鎖 `MS-D-10`。

## MS-12 行動終端輸入元件

依賴 `MS-11` 的結論。寫入新的行動輸入元件與其測試；**由 M2 terminal writer 單一擁有**。

不論 `MS-D-10` 最終選 (a) 或 (b)，以下為契約：

- 前端**不得組裝命令字串**（SCOPE-011、專案 skill 的既有要求）。輸入元件只搬運使用者按鍵與貼上內容。
- 多行貼上一律經確認步驟；確認送出的 bytes 與預覽完全一致，**不附加 Enter**。
- 斷線／viewer 狀態停用送出，且**不佇列**。
- 特殊鍵輔助列（若採 (a)）每個鍵 ≥ 44×44，貼底元素自行處理 `env(safe-area-inset-bottom)`（`MS-02`）。
- 輸入元件的顏色全部走 token；`pocket` 生效時它與終端同為明亮（`07-…md`）。

## MS-13 writer／viewer、接管與姿態

寫入 `SessionWorkspaceView.vue`。

- 一個 writer、多個 viewer，`terminal.control_acquire` 明確取得，接管由伺服器裁決——**契約不變**。
- 行動端不得假設「只有我在用」而略過控制權檢查。
- 多裝置同時開同一 session 時的 orientation／posture 衝突：**沿用現行伺服器契約**；若發現現行契約無法表達（例如兩裝置各自要不同 PTY 尺寸），停止本票並開一份新 ADR，**不得**在前端自行仲裁。
- 節點 privileged 與 Codex sandbox-bypass 姿態在打字前可見（`MS-06` 的硬性條件）。
- 平台只說 runtime id，**永不**顯示 shell 命令／binary／argv／環境變數／entrypoint。

## 寫入集

| 票 | 檔案 | 擁有者 |
|---|---|---|
| MS-07 | `views/SessionWorkspaceView.vue`、`components/session/WorkspaceTabs.vue` | M1 shell writer |
| MS-08 | `views/SessionWorkspaceView.vue` | M1 shell writer |
| MS-09 | `views/SessionWorkspaceView.vue`、`composables/useTerminalSession.ts` | M2 terminal writer |
| MS-10 | 同上 | M2 terminal writer |
| MS-11 | 獨立 spike 目錄 | IME spike owner |
| MS-12 | 新行動輸入元件 ＋ 測試 | M2 terminal writer |
| MS-13 | `views/SessionWorkspaceView.vue` | M2 terminal writer |

`SessionWorkspaceView.vue` 在本期被四張票碰到（`MS-05`／`MS-07`／`MS-08`／`MS-09`／`MS-10`／`MS-13`）。
**M1 的三張（MS-05、MS-07、MS-08）必須全部合併後，M2 才接手。** 兩位 writer 不得同時持有這個檔案。
