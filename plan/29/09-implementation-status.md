# 09 — 實作狀態與開放測量

本文件是本期唯一的「現在到哪了」來源。**每一次票的狀態改變都在這裡更新，不在 PR 描述裡。**
`plan/28` 用 `07-implementation-status.md` 與 `08-open-measurements.md` 兩個檔，本期合併為一個，
理由是本期開放測量的數量遠多於已完成項目，分成兩檔會讓讀者以為完成度比實際高。

## 1. 截至目前的真實狀態

**正式程式碼改動：0 行。**

PR #68（已合併，`f012b14`）只新增了 `prototypes/mobile-session/` 與 `plan/29/` 的文字檔。
沒有 frontend／backend／daemon／CI／governance 修改，沒有 API、PTY、WebSocket、shell、
真實檔案寫入或 session 生命週期的副作用。

本次補完另外完成了一項**算術**（不是實作，也不是渲染證據）：
`07-…md` §1 的明亮終端調色盤，16 個 ANSI 值加 9 個終端 token，全部通過 `theme/contrast.ts` 的既有門檻。
同時發現 **ANSI 16 色從來不在 `PAIRS` 裡**（§0.1.1）——這是所有主題共有的既有缺口，由 `MS-19` 補。

已成立的只有 `MSP-F-001`～`012`：**fixture 行為**。它們證明提案的互動是連貫的，
**不證明** reconnect、路徑限制、RBAC、ANSI、IME、二進位拒絕的正式服務行為、真實裝置版面或安全狀態。

## 2. 決策狀態（`MS-D-*`）

| ID | 主題 | 狀態 |
|---|---|---|
| MS-D-01 | 行動進入點 | 提案，待 M0 |
| MS-D-02 | preview 與返回鍵（含 `mode` 值域由 `terminal` 改為 `cli` 的具名修訂） | 提案，待 M0 |
| MS-D-03 | 斷點單一來源 | 提案，待 M0 |
| MS-D-04 | 明亮落實機制（新增 `pocket` 主題） | 提案，需 ADR |
| MS-D-05 | pocket 觸發條件 | 提案，需 ADR |
| MS-D-06 | 既有主題偏好的處理 | 提案，需 ADR |
| MS-D-07 | 冷載入閃爍 | 提案，需 ADR |
| MS-D-08 | 1024–1100 缺陷 | **待重現**（`MS-OM-01`） |
| MS-D-09 | 鍵盤高度所有權 | 提案，待 M0 |
| MS-D-10 | 輸入形態 | **待測量**（`MS-OM-02`） |
| MS-D-11 | 保留與 analytics | 提案，待 M0 ＋ 安全 |
| MS-D-12 | 推出旗標 | 提案，待 release owner |
| MS-D-13 | 需求編號 `NFR-007` | 提案，待 M0 |
| MS-D-14 | 上傳範圍 | 提案，待 M0 ＋ 安全 |

`01-mobile-addendum-v0.1.md` 狀態仍為 **Proposed**，尚未成為 VDS 1.0 或 ADR 0027 的修訂。
`07-…md` 對 v0.1 提出兩處具名修訂（per-theme ANSI、Monaco `base` 分支），需與 addendum 一併核准。

## 3. 票狀態（`MS-*`）

全部 **未開始**。

| 票 | 階段 | 擁有者 | 擋在 | 文件 |
|---|---|---|---|---|
| MS-01 斷點單一來源與行動尺度 | M1 | shell writer | MS-D-03 | 04 |
| MS-02 安全區與軟體鍵盤 | M1 | shell writer | MS-01、MS-D-09 | 04 |
| MS-03 行動主導覽 | M1 | shell writer | MS-01、MS-D-01 | 04 |
| MS-04 Sessions 清單行動形態 | M1 | shell writer | MS-01 | 04 |
| MS-05 1024–1100 檔案欄缺陷 | M1 | shell writer | MS-D-08 | 04 |
| MS-06 StatusBar 與標頭壓縮 | M1 | shell writer | MS-01 | 04 |
| MS-07 行動模式外殼 | M1 | shell writer | MS-05 | 05 |
| MS-08 preview 返回鍵 | M1 | shell writer | MS-D-02、MS-07 | 05 |
| MS-09 終端宿主與 fit | M2 | terminal writer | M1 全數合併 | 05 |
| MS-10 連線／重連／detach | M2 | terminal writer | MS-09 | 05 |
| MS-11 IME／輸入 spike | M1（並行） | spike owner | 無 | 05 |
| MS-12 行動終端輸入元件 | M2 | terminal writer | MS-11、MS-D-10 | 05 |
| MS-13 writer／viewer／姿態 | M2 | terminal writer | MS-09 | 05 |
| MS-14 行動檔案瀏覽 | M3 | file writer | M2 合併 | 06 |
| MS-15 檔名搜尋行動形態 | M3 | file writer | MS-14 | 06 |
| MS-16 全幅唯讀預覽 | M3 | file writer | MS-14 | 06 |
| MS-17 上傳（可切除） | M3 | file writer | MS-16、MS-D-14 | 06 |
| MS-18 `pocket` token 值 | 主題 | theme owner | MS-D-04 | 07 |
| MS-19 對比與真實渲染 | 主題 | theme owner | MS-18 | 07 |
| MS-20 選擇層 | 主題 | theme owner | MS-18、MS-D-05～07 | 07 |
| MS-21 桌面回歸 | 主題 | theme owner | MS-20 | 07 |
| MS-22 單元與靜態層 | 驗證 | frontend | MS-01、MS-18 | 08 |
| MS-23 瀏覽器 E2E | 驗證 | frontend | M1 合併 | 08 |
| MS-24 真機／安全／UAT | M4 | QA ＋ 安全 | M3 合併 | 08 |
| MS-25 Traceability 與推出 | M4 | release owner | MS-24 | 08 |

主題票（MS-18～21）在 DAG 上與 M2／M3 並行，但 `MS-20` 會碰 `SessionWorkspaceView.vue` 的主題套用路徑，
**必須與 M2 序列化**。這是本期唯一一處跨階段的檔案爭用。

## 4. 開放測量（`MS-OM-*`）

這些是**還不知道答案**的問題，不是待辦事項。把它們寫成待辦會讓人以為只要做就好；
其中幾項的答案可能會推翻上面的票。

| ID | 問題 | 為什麼重要 | 誰量 |
|---|---|---|---|
| `MS-OM-01` | 1024–1100px 下 `.workspace-rail` 的 computed `display` 與抽屜鈕是否存在 | 決定 `MS-05` 是缺陷修復還是不改 | M1 shell writer |
| `MS-OM-02` | iOS Safari 與 Android Chrome 的繁中 IME 事件序列與實際送出 bytes | 決定 `MS-D-10`，進而決定 `MS-12` 的整個形狀 | IME spike owner |
| `MS-OM-03` | `visualViewport.height` 是否已排除 home indicator（各平台） | 決定底部安全區是否重複相減；錯了會在有 home indicator 的裝置上多切掉一條 | IME spike owner |
| `MS-OM-04` | 明亮終端底下 ANSI 16 色的**真實 xterm 渲染**與真實 CLI 輸出 | **算術已完成**：`07-…md` §1.2 有一組通過 `contrast.ts` 全部門檻的提案值，規則見 §1.1。剩下的是渲染——次像素反鋸齒、真實 Claude／Codex／tmux 輸出、`\e[3Xm`／`\e[4Xm` 8×8 矩陣。屬 `MSP-R-009` | theme owner |
| `MS-OM-05` | `theme-boot.js` 加入寬度判斷後的實際行數 | >12 行就必須回到「接受冷載入閃爍」，不是放寬門檻 | theme owner |
| `MS-OM-06` | 390×844、軟體鍵盤開啟時，終端實際剩下幾列 | plan/09 為桌面訂的下限是 30 列。若行動端只剩 8 列，`MS-12` 的輔助鍵列可能必須改設計，甚至整個輸入形態要重想 | M2 terminal writer |
| `MS-OM-07` | `popstate` 與 vue-router 導航守衛在 session 切換時是否互相干擾 | 決定 `MS-08` 是否要回退到只留 Escape 與關閉鈕 | M1 shell writer |
| `MS-OM-08` | Monaco 在實機行動瀏覽器上的載入時間、記憶體與觸控捲動可用性 | 預覽是本期三大功能之一。若 Monaco 在中階手機上不可用，`MS-16` 需要一個不是 Monaco 的唯讀呈現，而那是新的決策不是調參 | M3 file writer |
| `MS-OM-09` | 行動瀏覽器背景化後回前景時，WebSocket 的實際存活率與重連耗時 | 決定 `MS-10` 的 stale 標示與重連提示要多積極 | M2 terminal writer |
| `MS-OM-10` | 搜尋框與輸入列在鍵盤升起時是否被遮住（各平台） | `MS-02` 拒絕 `position: fixed` 的前提就是這個量測還沒做 | QA |
| `MS-OM-11` | pocket 的 6 個色相在明亮底的色盲可辨性 | 深色底的可辨性結論不能直接搬到明亮底。現行調色盤也沒做過這項評估，所以這是新缺口不是回歸 | theme owner |

`MS-OM-06`、`MS-OM-08` 兩項**可能推翻既有票的設計**，不只是填一個數字。
它們應該在對應階段的**最前面**量，不是在實作完之後驗。

## 5. 本期不做的事

沿用 `01-mobile-addendum-v0.1.md` §8，逐條保留：

native app、PWA 離線、推播、chat、approval inbox、agent 事件解析、摘要、shell 命令組裝器、
session 建立／停止、system shell 控制、編輯、重新命名、刪除、下載、SFTP、全文搜尋、
圖片／PDF／archive 預覽、任意路徑、遠端字型或資產、新相依套件。

另外，依本次補完新增的三條：

- **不改任何 `contracts/` 下的 wire schema。** 若發現非改不可，該階段停止並轉為獨立審查的契約／ADR 更新，
  跨瀏覽器、Central 與 daemon 三方（`02-…md` M2 已有這條，此處重申因為 `MS-09` 最接近這條線）。
- **不放寬既有閘門的門檻**以容納本期（`theme-boot.js` 的 12 行、resize 的 2–300／2–500、
  `GATE-VR-NO-LITERAL-COLOR`）。
- **不在 `stores/files.ts` 上動刀**（`06-…md` 已載明：若非改不可，代表 addendum §2 的假設有問題，交還 M0）。
