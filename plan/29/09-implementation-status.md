# 09 — 實作狀態與開放測量

本文件是本期唯一的「現在到哪了」來源。**每一次票的狀態改變都在這裡更新，不在 PR 描述裡。**
`plan/28` 用 `07-implementation-status.md` 與 `08-open-measurements.md` 兩個檔，本期合併為一個，
理由是本期開放測量的數量遠多於已完成項目，分成兩檔會讓讀者以為完成度比實際高。

## 1. 截至目前的真實狀態

分支 `feat/mobile-rwd`，10 個 commit。

**已完成**：`MS-01`～`MS-09`、`MS-14`～`MS-16`、`MS-18`～`MS-23`、`MS-25`。
**未完成**：`MS-11`（IME spike，需真機）、`MS-12`（依賴 `MS-11`）、
`MS-13`（writer/viewer 契約未改動，但多裝置驗證需真機）、`MS-17`（上傳，依 `MS-D-14` 可切除）、
`MS-24`（真機／安全／UAT）。

本機驗證：1026 個單元測試、typecheck、lint、prettier、
`GATE-VR-*` 四項、`GATE-LY-*` 三項、新增的 `GATE-MS-BREAKPOINT` 與 `GATE-MS-HISTORY-PATH`，
以及 `scripts/trace validate` 的 schema／static／selectors 三級，全部通過。
E2E 的 13 個不需後端案例在真實 chromium 與 mobile-chrome-emulated 實際執行通過。

**`MSP-R-001`～`012` 仍然全部未完成。** 本期做的是呈現層，沒有碰任何 wire schema、
daemon、RBAC 或 session 生命週期；上面那些綠燈證明的是「改動沒有弄壞既有契約」，
不是「行動版可以上線」。

### 1.1 實作過程中被推翻的計畫內容

四處，都留在原文件裡而不是抹掉：

| 位置 | 計畫原本寫的 | 實際結果 |
|---|---|---|
| `07-…md` §1.1 R3 | normal／bright 互相可分辨 ≥1.3:1，且「五個深色主題已經算過會通過」 | **沒算過**。實測 1.19–1.26，五個深色主題全紅。錯的是門檻不是值；改為有方向性的「對比之比 ≥1.15」 |
| `08-…md` `GATE-MS-TOUCH-TOKEN` | 靜態檢查互動元素不得寫死像素高度 | **放棄**。40 個字面高度多半是圖示與 sr-only，規則會變成「大部分都是例外」。改由 E2E 量幾何，理由寫在 `scripts/ms/ms-gates.sh` 檔頭 |
| `05-…md` `MS-08` 條件 (3) | 離開 route 時把推入的歷史條目一併退出 | **未實作**。在導航進行中呼叫 `history.back()` 會讓 router 跑到誰都沒選的地方。改為「棄用」該條目，殘留一筆同 URL 條目，記入 `MS-OM-07` |
| `06-…md` §0 | 新增 `useFileBrowser` 與 `useFileTree` 並存 | 照做，但另外發現 `FileSearchBar` 缺兩件 ADR 0014/0015 要求的事（`scanned_count` 未顯示、搜尋範圍未標示），一併補上 |

### 1.2 實作中找到、且非本期造成的既有缺陷

兩個，都已修，回歸測試都先驗過「還原舊碼會變紅」：

1. **1024–1100px 檔案欄完全無法取得**（`MS-05`）。詳見 §4.1。
2. **node 姿態在壓縮標頭下被藏起來**（`MS-06`）。`SessionHeader` 的註解寫著
   ADR 0023 D10 要求它在打字前可見，而那兩個徽章就在 `v-if="!compact || detailsOpen"`
   的那一列裡，距離該註解四行。**這一條在修復前影響的是現行桌面 1024–1439px 的使用者**，
   不只是行動版。

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

| 票 | 狀態 |
|---|---|
| MS-01 斷點單一來源與行動尺度 | ✅ 已合併 |
| MS-02 安全區與軟體鍵盤 | ✅ 已合併 |
| MS-03 行動主導覽 | ✅ 已合併 |
| MS-04 Sessions 清單行動形態 | ✅ 已合併 |
| MS-05 1024–1100 檔案欄缺陷 | ✅ 已合併（見 §1.2） |
| MS-06 StatusBar 與標頭壓縮 | ✅ 已合併（見 §1.2） |
| MS-07 行動模式外殼 | ✅ 已合併 |
| MS-08 preview 返回鍵 | ✅ 已合併，條件 (3) 未實作（見 §1.1） |
| MS-09 終端宿主與 fit | ✅ 已合併 |
| MS-10 連線／重連／detach | ➖ 契約未改動；真機驗證屬 MSP-R-002 |
| MS-11 IME／輸入 spike | ❌ **未做，需真機** |
| MS-12 行動終端輸入元件 | ❌ **未做，依賴 MS-11** |
| MS-13 writer／viewer／姿態 | ➖ 契約未改動；多裝置驗證屬 MSP-R-004 |
| MS-14 行動檔案瀏覽 | ✅ 已合併 |
| MS-15 檔名搜尋行動形態 | ✅ 已合併 |
| MS-16 全幅唯讀預覽 | ✅ 已合併 |
| MS-17 上傳（可切除） | ❌ 未做，依 MS-D-14 移出本期 |
| MS-18 `pocket` token 值 | ✅ 已合併 |
| MS-19 對比與真實渲染 | ✅ 自動化部分已合併；真實 CLI 渲染屬 MSP-R-009 |
| MS-20 選擇層 | ✅ 已合併 |
| MS-21 桌面回歸 | ✅ 已合併 |
| MS-22 單元與靜態層 | ✅ 已合併（見 §1.1 的閘門調整） |
| MS-23 瀏覽器 E2E | ✅ 已合併；mobile-safari-emulated 在本機無法執行（webkit 缺系統函式庫） |
| MS-24 真機／安全／UAT | ❌ 未做 |
| MS-25 Traceability | ✅ 已合併，新增 NFR-007 |

「➖」表示該票的契約本來就不需要改動，本期確認沒有破壞它；真正的驗證在對應的 `MSP-R-*`。

## 4. 開放測量（`MS-OM-*`）

這些是**還不知道答案**的問題，不是待辦事項。把它們寫成待辦會讓人以為只要做就好；
其中幾項的答案可能會推翻上面的票。

| ID | 問題 | 為什麼重要 | 誰量 |
|---|---|---|---|
| `MS-OM-01` | ~~1024–1100px 下 `.workspace-rail` 的 computed `display` 與抽屜鈕是否存在~~ | **已量測，見下方 §4.1。確認為缺陷，`MS-D-08` 裁定採選項 (a)** | 已完成 |
| `MS-OM-02` | iOS Safari 與 Android Chrome 的繁中 IME 事件序列與實際送出 bytes | 決定 `MS-D-10`，進而決定 `MS-12` 的整個形狀 | IME spike owner |
| `MS-OM-03` | `visualViewport.height` 是否已排除 home indicator（各平台） | 決定底部安全區是否重複相減；錯了會在有 home indicator 的裝置上多切掉一條 | IME spike owner |
| `MS-OM-04` | 明亮終端底下 ANSI 16 色的**真實 xterm 渲染**與真實 CLI 輸出 | **算術已完成**：`07-…md` §1.2 有一組通過 `contrast.ts` 全部門檻的提案值，規則見 §1.1。剩下的是渲染——次像素反鋸齒、真實 Claude／Codex／tmux 輸出、`\e[3Xm`／`\e[4Xm` 8×8 矩陣。屬 `MSP-R-009` | theme owner |
| `MS-OM-05` | ~~`theme-boot.js` 加入寬度判斷後的實際行數~~ | **已量測：9 行，上限 12。** 且已在真實瀏覽器驗證首次繪製前即生效（擋掉 main.ts 後仍為 pocket） | 已完成 |
| `MS-OM-06` | 390×844、軟體鍵盤開啟時，終端實際剩下幾列 | plan/09 為桌面訂的下限是 30 列。若行動端只剩 8 列，`MS-12` 的輔助鍵列可能必須改設計，甚至整個輸入形態要重想 | M2 terminal writer |
| `MS-OM-07` | `popstate` 與 vue-router 在 session 切換／離開 route 時的互動 | **部分已答**：session 切換已處理（先清 state 再棄用歷史條目，單元測試涵蓋）。**未答**：離開 route 時殘留一筆同 URL 歷史條目，真機上「多按一次返回」的實際觀感未驗 | M4 QA（真機） |
| `MS-OM-08` | Monaco 在實機行動瀏覽器上的載入時間、記憶體與觸控捲動可用性 | 預覽是本期三大功能之一。若 Monaco 在中階手機上不可用，`MS-16` 需要一個不是 Monaco 的唯讀呈現，而那是新的決策不是調參 | M3 file writer |
| `MS-OM-09` | 行動瀏覽器背景化後回前景時，WebSocket 的實際存活率與重連耗時 | 決定 `MS-10` 的 stale 標示與重連提示要多積極 | M2 terminal writer |
| `MS-OM-10` | 搜尋框與輸入列在鍵盤升起時是否被遮住（各平台） | `MS-02` 拒絕 `position: fixed` 的前提就是這個量測還沒做 | QA |
| `MS-OM-11` | pocket 的 6 個色相在明亮底的色盲可辨性 | 深色底的可辨性結論不能直接搬到明亮底。現行調色盤也沒做過這項評估，所以這是新缺口不是回歸 | theme owner |

### 4.1 `MS-OM-01` 量測結果（2026-09-14）

兩個獨立量法，因為 jsdom 沒有 CSS、而瀏覽器骨架不是真元件，單獨一個都不足以定案：

- **抽屜鈕**：vitest 掛載**真實** `SessionWorkspaceView.vue`（終端／FileTree／PreviewPane 為 mock），逐一設定 `window.innerWidth` 後讀 DOM。
- **CSS `display`**：真實 chromium，樣式**直接取自 SFC 的 `<style scoped>` 原文**，依真實 template 的 class 結構搭骨架。

| 寬度 | rail 在 DOM | CSS `display` | 抽屜鈕 | 結果 |
|---:|---|---|---|---|
| 390 | 否（抽屜關閉） | none | 有 | 可開啟 |
| 768 | 否 | none | 有 | 可開啟 |
| 1000 | 否 | none | 有 | 可開啟 |
| 1023 | 否 | none | 有 | 可開啟 |
| **1024** | **是** | **none** | **無** | **完全無法取得** |
| **1100** | **是** | **none** | **無** | **完全無法取得** |
| 1101 | 是 | block | 無 | 欄位可見 |

`<1024` 時 rail 不在 DOM 是正確行為——抽屜關閉時它既不佔位也不覆蓋（`filesVisible` 的定義）。
缺陷只發生在 **1024–1100 含端點**：欄位模式已生效（所以沒有開啟鈕），但舊的 media query 仍把它藏起來。

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
