# Cliora Visual Refresh — 共用規範

版本：0.1.0 · 狀態：Proposed · 日期：2026-09-09（UTC+08:00）

## 範圍與優先順序

本規範定義五種風格共用的功能語意、互動與實作邊界。各風格文件負責色彩、字體、版型與元件造型。
這些文件是待審閱的候選設計，尚未取代 `research/style.md`，亦未更改正式需求、ADR與安全契約。

實作順序：既有授權與Session契約 → 共用互動／可讀性要求 → 選定的風格規格 → 視覺圖稿。圖稿是視覺參考，不是API或權限證據。產生衝突時先記錄並提交設計裁決，不擅自以圖片覆蓋行為。

## 資訊架構

| 層次 | 內容 | 行為 |
|---|---|---|
| 全域 | 工作台、Sessions、Nodes、概況、管理 | 所有頁面保留相同命名與順序 |
| Session身份 | 名稱、Node、Runtime、Workspace | 長路徑截斷時提供完整查看與複製 |
| 工作面 | CLI、系統終端、唯讀檔案預覽 | 一次一個主面板，切換不結束遠端程序 |
| 輔助面板 | 檔案樹、操作工具、上傳回饋 | 可收合；窄視窗用抽屜 |
| 狀態列 | Session狀態、連線、控制權 | 分開描述；不要合成一個綠色「正常」 |

## 狀態與錯誤

| 狀況 | 必須呈現 | 操作 |
|---|---|---|
| 初次載入 | 區域loading；尚無數據不可顯示0 | 提供合適loading語意 |
| 更新中 | 保留原資料並標示更新中 | 不清空內容 |
| 空清單 | 尚未建立Session／Node | 顯示有權限執行的建立入口 |
| 無搜尋結果 | 沒有符合條件的項目 | 清除搜尋與篩選 |
| 連線中／重連 | 對應瀏覽器連線狀態 | 禁止誤送輸入；保留現有輸出 |
| Session已結束 | 結束狀態與可用歷史 | 不將Reconnect呈現為重新啟動 |
| 唯讀 | 「唯讀」與控制權說明 | 有權限時顯示取得控制權 |
| 部分資料過期 | 回報時間、缺失區塊 | 保留其他有效資料，可重試 |
| 上傳失敗 | 檔名、原因、重試方式 | 錯誤不隨Toast消失 |
| 禁止存取 | 說明此資源不可存取 | UI隱藏不能取代伺服器授權 |
| 輸出截斷 | 清楚說明只顯示最新片段 | 不暗示完整歷史已載入 |

Runtime就緒與Session執行中不代表Agent正在思考；沒有可靠資料來源的AI工作狀態不得新增。

## Tokens與前端對應

| 新語意 | 現有原型CSS變數 | 正式實作方向 |
|---|---|---|
| surface.canvas | --bg | 外層背景 |
| surface.default | --surface | 一般面板 |
| surface.hover | --raised | hover／浮層，必要時再分開 |
| terminal.background | --terminal | 終端及預覽背景 |
| border.subtle | --line | 裝飾分隔，不保證適合必要控制邊界 |
| text.primary / secondary | --text / --muted | 主要／輔助資訊 |
| accent.primary / subtle | --accent / --tint | 品牌動作／選取背景 |
| radius.panel | --radius | 元件可另定義button與dialog半徑 |

新增text.onAccent、text.onTerminal、border.control、focus.ring以及狀態foreground/background tokens。每個主題必須明確定義，不用鏈式fallback掩蓋缺漏。xterm主題與Monaco主題使用相同語意來源；不能只更新頁面CSS而忽略終端及編輯器（**修訂（`plan/28`，ADR 0027 §6）：原本此處與各風格文件的「原型差距」段都寫著 Naive UI。它從未被使用，相依已移除**——所以本段列的四件既有 UI 元件能力（Dialog 焦點約束與返回、分頁箭頭鍵、抽屜關閉、樹狀鍵盤操作）其中兩件由本期自建：Dialog 焦點約束與抽屜。另兩件已經存在且做得對：`WorkspaceTabs` 的 roving tabindex 與 `FileTree` 的鍵盤操作）。

## 可讀性與輸入

- 本提案驗收目標：一般文字對比至少4.5:1，必要控制邊界及焦點至少3:1；每次報告標明具體前景／背景，不以單一色值宣布合格。
- 14px作為一般操作文字，12px只供次要資訊。使用rem及可縮放布局。
- 品牌色不是通用狀態色。綠、琥珀、紅、藍分別承擔success、warning、error、info，但所有狀態都有文字。
- Disabled保留可理解的原因；placeholder不取代label。
- 按鈕具可讀名稱；圖示按鈕提供aria-label及tooltip。Lucide作為正式UI圖示來源，不混入文字符號充當導覽icon。
- 觸控目標44px，桌面緊湊視覺控制可使用額外點擊區。
- Dialog焦點約束及返回、Esc、分頁箭頭鍵、抽屜關閉與樹狀鍵盤操作**自建**（`plan/28`：沒有 UI 元件庫可以「使用既有能力」，見 §Tokens 的修訂）；Dialog 與抽屜共用一個 `useFocusTrap`。
- 快捷鍵不可攔截終端原生輸入；僅在非終端焦點下啟用全域快捷鍵。

## 終端與檔案

- App Shell只設定一次視窗高度；終端尺寸根據可見容器計算。
- 面板隱藏不以0×0 resize遠端PTY；重新顯示後再fit。
- 切換CLI／系統終端保持既有終端連線與buffer；瀏覽器斷線不等於tmux結束。
- 系統終端的主機範圍、沙箱與可提權姿態依實際Node回報呈現，輸入前可見。
- 預覽保持唯讀；不新增編輯、刪除、覆寫或任意主機路徑存取。
- 圖片投放、一般檔案上傳與控制權必須沿用既有功能限制。
- ANSI常規及亮色16色、選取、搜尋命中、cursor、IME、中文及emoji寬度須在正式終端中驗收；不得以靜態原型當成通過證據。

## 頁面與元件清單

共用實作元件：AppShell、PrimaryNav、SessionHeader、WorkspaceTabs、StatusBar、FilePanel、Toolbar、Button、IconButton、StatusBadge、Field、DataTable、EmptyState、InlineNotice、Dialog、Toast。
風格差異使用tokens與明確layout variant；不要複製五份業務邏輯。

桌面與窄視窗覆蓋Sessions、Nodes、概況與工作台；管理頁後續延伸時沿用同一套表單、表格與錯誤規則。手機操作能力仍由既有產品需求與授權決定，本提案只要求控制項可觸及。

## 整合與驗收流程

1. 審閱五款文件，記錄主題及版型選擇；可以混搭，但需定義一套確定tokens與layout，不留下含糊比例。
2. 在原型修正對比及所選版型差距，取得視覺回饋。
3. 將tokens與展示元件導入Vue；保留既有stores、composables與協定。
4. 驗證工作台高度、面板切換、控制權、斷線重連、檔案預覽／上傳及真實終端fit。
5. 更新既有正式視覺文件與必要的traceability；只有通過對應驗收後才標記實作完成。

共用驗收矩陣：5種主題 × 1440×900／1024×768／390×844；每款覆蓋正常、空、錯誤、唯讀、重連及長文字。正式選定僅支援部分主題時，縮減矩陣需明確記錄範圍。

## 已知限制

本次是文件交付。未新增真實功能、未進行瀏覽器視覺驗收；靜態色彩數值檢查只驗證列出的不透明色值配對。GitHub私人預覽的存取權不等同repository權限。
