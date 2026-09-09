# 04 — 元件基座（`VR-05`／`VR-06`）

共用規範列了十六個共用實作元件。四個在 `03-…md`（AppShell、PrimaryNav、
SessionHeader、StatusBar），其餘十二個在這裡。

**規則：風格差異用 token 與明確的 layout variant，不要複製五份業務邏輯**（共用規範明文）。
本期兩款主題的差異**全部**在 token，沒有一個元件需要 `data-theme` 的分支。
若實作時發現某個元件非分支不可，那是 token 表缺了一格，回 `VR-03` 補，不是在元件裡開 `if`。

## 1. 現有元件的處置

| 檔案 | 行數 | 處置 |
|---|---:|---|
| `common/AsyncState.vue` | 39 | **拆成三個**：`LoadingState`、`EmptyState`、`InlineNotice`。理由見 §2.1 |
| `common/ErrorNotice.vue` | 130 | 保留邏輯（error catalog 的四段式是對的），只換樣式與 token |
| `common/StatusBadge.vue` | 64 | **重寫**：12 個字面色值 → 狀態三元組；三種語意（Node／連線／Session）拆開 |
| `common/ConfirmDialog.vue` | 89 | **重寫**：加焦點約束、Esc、焦點返回；`danger` 改用 `--danger-*`（現況 4.09:1 不合格） |
| `session/WorkspaceTabs.vue` | 147 | 改造：固定 44px、選中態四要素、`--text-on-terminal`。**roving tabindex 的邏輯一行不動**（它做得對） |
| `session/NewSessionDialog.vue` | 530 | 採用新的 `Dialog` ＋ `Field`；表單邏輯不動 |
| `file/FileTree*.vue` | 280＋309＋135＋203 | 採用 `FilePanel` 框架與 `Toolbar`；**鍵盤操作邏輯一行不動** |
| `file/PreviewPane.vue` | 255 | 主題化（`monaco.editor.setTheme`）；`readOnly` 與 contribution 不動 |
| `file/PreviewDenied.vue` | 166 | 換 token（6 個字面色值） |
| `dashboard/*.vue` | 5 個檔案 | 採用 `MetricCard`／`HealthCard` 的新樣式，資料邏輯不動 |
| `theme/naive.ts` | 8 | **刪除**（`01-…md` §2） |

## 2. `VR-05`：基礎元件

### 2.1 為什麼要拆掉 `AsyncState`

`AsyncState.vue` 用一個 prop 表達九種狀態（`idle`／`loading`／`success`／`empty`／
`stale`／`offline`／`forbidden`／`partial`／`error`），render 出來的是
`<strong>{{ state }}</strong>` ——**把狀態名直接印在畫面上**（英文、小寫、給開發者看的）。

九種狀態需要的**動作**完全不同：

| 狀態 | 使用者要做什麼 | 應有的元件 |
|---|---|---|
| loading | 等 | `LoadingState`（區域 skeleton／spinner） |
| empty | 建立第一個 | `EmptyState` ＋ **有權限時**的建立入口 |
| 篩選無結果 | 清除搜尋／篩選 | `EmptyState`（**與 empty 不同文案**，共用規範明文） |
| stale／partial | 知道哪一塊舊了、可重試 | `InlineNotice`（保留現有資料） |
| offline／forbidden／error | 看原因、決定重試 | `ErrorNotice`（已存在，四段式） |

一個元件不可能同時是這五種。**拆的判準**：`empty` 與「篩選無結果」必須是
兩段不同文案，而現在它們連同 `stale` 都印同一行字。

### 2.2 元件契約表

每個元件宣告它用到的**色彩配對**，`theme.contrast.test.ts` 的清單由這一欄產生
（`02-…md` §6.4；五份設計文件正是因為從 token 表出發才漏掉一組）。

| 元件 | 狀態 | a11y 契約 | 色彩配對 |
|---|---|---|---|
| `Button` | default／hover／active／disabled／busy | 可讀名稱；`disabled` 保留標籤與**可理解的原因**（`title` 或旁註），不靠透明度；busy 時 `aria-busy` | `text-on-accent`／`accent-primary`、`text-on-accent`／`accent-hover`、`text-primary`／`surface-default`、`border-control`／`surface-default`、`text-disabled`／`surface-default` |
| `Button variant="danger"` | 同上 | 危險動作**不占日常主動作位置**（Graphite §5） | `danger-fg`／`danger-bg` |
| `IconButton` | 同 Button | **必須**有 `aria-label` ＋ tooltip；視覺 ≥24px 時以額外點擊區補到 44px | 同 Button ＋ `focus-ring`／各底 |
| `Field`（label／input／select／error／hint） | default／focus／error／disabled／readonly | **label 常駐**（placeholder 不取代 label）；錯誤在欄位下方且 `aria-describedby`；必填以文字標示 | `text-primary`／`surface-default`、`border-control`／`surface-default`、`focus-ring`／`surface-default`、`status-error-fg`／`surface-default` |
| `StatusBadge` | 五種語意 × 三個來源 | 圓點 ＋ **文字** ＋ 1px 邊線；`role` 依用途（狀態變化用 `status`，靜態標籤不用 role） | 五組 `status-*-fg`／`-bg`、五組 `-border`／`-bg` |
| `InlineNotice` | info／warning／error／stale | `role="status"`（非錯誤）／`role="alert"`（錯誤）；**不自動消失** | 同 StatusBadge 的四組 |
| `EmptyState` | 空清單／篩選無結果 | 兩種文案不共用；建立入口只在**有權限**時出現 | `text-primary`、`text-secondary`／`surface-default` |
| `LoadingState` | 區域 loading | **尚無數據時不得顯示 0**（共用規範明文）；`aria-busy` 在容器上 | `text-secondary`／`surface-default` |
| `Toast` | success／info | **只用於成功與資訊**。失敗一律留在相關區域（`InlineNotice`／`ErrorNotice`），不隨時間消失 | `text-primary`／`surface-raised`、`shadow-overlay` |
| `Dialog` | open／busy | 焦點約束、Esc 關閉、關閉後回到觸發點、`aria-modal`、`aria-labelledby` | `text-primary`／`surface-default`、`surface-scrim`、`shadow-overlay` |

### 2.3 `Dialog` 的三件現在沒有的事

`ConfirmDialog.vue` 目前有 `role="dialog"` 與 `aria-modal="true"`，但：

1. **沒有焦點約束**。Tab 會走出 Dialog 到底下的頁面（`aria-modal` 只影響
   螢幕閱讀器的虛擬游標，不影響實際的 Tab 順序）。
2. **沒有 Esc**。只有點背景可關（`@click.self`），鍵盤使用者關不掉。
3. **沒有焦點返回**。關閉後焦點掉回 `<body>`。

三件都是共用規範明列的要求，也是移除 Naive UI 之後要自建的兩件之一（`01-…md` §1）。
做成一個 `useFocusTrap(containerRef, { onEscape })` composable，
Dialog 與抽屜（`03-…md` §5）共用。約 80 行。

**Terminate 的確認要顯示 Session 名稱**（Graphite §5）。現況 `ConfirmDialog`
只吃 `title` 與 `message` 兩個字串，呼叫端傳的是泛用文字。改為讓呼叫端傳入
`<slot>`，以便把名稱以 `<code>` 標出來。

### 2.4 `Toast` 為什麼要新建，而且要限制它

共用規範：「Toast：成功短暫提示；失敗保留於相關區域並提供重試」。
現況**沒有 Toast**，所有回饋都是 inline——那其實比一個會亂用的 Toast 好。
所以本期新建它，但**在型別上就不允許 error**：

```ts
type ToastKind = "success" | "info";   // 沒有 "error"
```

理由：一個會自己消失的錯誤訊息等於沒有錯誤訊息，而這個限制寫在型別裡
比寫在文件裡有效。上傳失敗、終止失敗、連線失敗全部走 `InlineNotice` 或
`ErrorNotice`，那也是它們現在的位置（`SessionWorkspaceView.vue:698-748`）。

## 3. `VR-06`：資料與工作區元件

### 3.1 `DataTable`

現況沒有共用表格：`NodesView`（315 行）、`AuditView`（524 行）、
`SessionsView`（202 行）、`NodeTunnelsView`（1092 行）各寫各的。

| 規則 | 來源 |
|---|---|
| 列高 `--density-row`（48px） | `00-…md` D3 |
| 表頭用 `--surface-raised`，**不用斑馬紋** | Porcelain §5 |
| 主要名稱可開啟（連結或按鈕），路徑為**次列**不是次欄 | 五份文件的「表格」列 |
| 排序、篩選狀態要有文字，不只箭頭 | 共用規範「狀態都有文字」 |
| 空清單與篩選無結果**不同文案** | 共用規範 |
| 溢出在**表格自己的容器內**捲動，不推整頁 | `plan/08`／`plan/09` 的水平溢出規則 |
| 列可聚焦時 `tabindex` 走 roving，不是每列一個 tab stop | 與 `WorkspaceTabs`、`FileTree` 一致 |

本期**不做**虛擬捲動、不做欄寬拖曳、不做欄位顯示切換。那些是資料量問題，
現在沒有證據說它存在（`AuditView` 已經有分頁）。

### 3.2 `Toolbar`

檔案樹工具列（`FileTreeToolbar.vue`）與未來的表格工具列共用一個框架：
左側動作、右側搜尋、溢出進 `⋯`。高度 `--density-control`（36px）。
**工具列裡的圖示按鈕一律 `IconButton`**，因此一律有 `aria-label`。

### 3.3 `FilePanel`

包住 `FileTreeToolbar` ＋ `FileSearchBar` ＋ `FileTree` ＋ 上傳佇列，
負責三件現在散在 `SessionWorkspaceView` 裡的事：

1. **可調寬**（`--layout-inspector-min/max`，220–360px），寬度持久化（`00-…md` D15）。
   拖曳把手要能用鍵盤操作（`role="separator"` ＋ `aria-valuenow` ＋ 方向鍵）。
2. **抽屜模式**（768–1023px 與 <768px）：`position: fixed`、焦點約束、Esc、
   關閉後焦點回到開啟鈕。
3. **上傳佇列**（現在是 `SessionWorkspaceView.vue:698-748` 的一段 inline template）
   移進來，成為 `FilePanel` 的一個插槽。**上傳的行為一行不動**（ADR 0026、`00-…md` D14）。

### 3.4 `WorkspaceTabs` 的改造

| 項目 | 現況 | 本期 |
|---|---|---|
| 高度 | 內容決定（約 33px） | `--layout-tabs`（44px） |
| 選中態 | 顏色 ＋ 底線（`:125-134`） | 顏色 ＋ 底線 ＋ **字重** ＋ `accent-subtle` 底 |
| 文字色 | `--text-muted` / `--text-primary` | `--text-on-terminal` 系（分頁列坐在終端底上） |
| 關閉鈕 | `×` 字元 | Lucide `X`，`IconButton`，點擊區補到 44px |
| roving tabindex | 已實作且正確 | **一行不動** |

Porcelain 的分頁列是本期最容易做錯的一格：原型「活動分頁使用深色 terminal 背景
與淺色主題文字」（Porcelain §8 自己點名）。正確形狀是分頁列整條坐在
`--surface-default`（白），**只有選中的那一格**銜接到終端底色，
而那一格的文字用 `--text-on-terminal`。

### 3.5 `PreviewPane`

只改三件事：`monaco.editor.setTheme()` 跟著主題、外框走 token、
`.preview` 這個選擇器名**不得改**（`gate_panels` 直接比對它）。
`readOnly`、contribution 清單、語言別名表一行不動（ADR 0015）。

## 4. 狀態矩陣（每個頁面都要有的十一種）

共用規範的「狀態與錯誤」表有十一列。本期把它變成一份**元件層級**的檢查表，
`05-…md` 的每一頁對照它勾選：

| 狀況 | 元件 | 判準 |
|---|---|---|
| 初次載入 | `LoadingState` | 尚無數據不得顯示 0 |
| 更新中 | `InlineNotice`(stale) | 保留原資料，不清空 |
| 空清單 | `EmptyState` | 有權限才顯示建立入口 |
| 無搜尋結果 | `EmptyState` | **與空清單不同文案**，提供清除篩選 |
| 連線中／重連 | `StatusBar` ＋ `InlineNotice` | 禁止誤送輸入；保留現有輸出 |
| Session 已結束 | `StatusBar` ＋ `EmptyState`(files) | **不把 Reconnect 呈現成重新啟動** |
| 唯讀 | `StatusBar` ＋ `Button`(取得控制權) | 「唯讀」要有文字，有權限才顯示取得控制權 |
| 部分資料過期 | `InlineNotice` ＋ `FreshnessBadge` | 回報時間、缺失區塊、其他資料仍有效 |
| 上傳失敗 | `InlineNotice` | 檔名、原因、重試方式；**不隨 Toast 消失** |
| 禁止存取 | `ErrorNotice`(forbidden) | UI 隱藏不能取代伺服器授權 |
| 輸出截斷 | `InlineNotice`(gap) | 清楚說明只顯示最新片段 |

最後一列現況已經有（`SessionWorkspaceView.vue:524-537` 的 gap banner），
文案也對。本期只是把它收進 `InlineNotice`。

## 5. 一條全域禁令

**Runtime 就緒與 Session 執行中不代表 Agent 正在思考；沒有可靠資料來源的 AI 工作狀態
不得新增**（共用規範明文，也對應 `SCOPE-001`「不解析 Claude 或 Codex 的內部事件」）。

具體形狀：不得出現「AI 思考中」「Agent 忙碌」「等待回應」這一類指示，
不論它看起來多像一個小小的裝飾。判準：任何新的狀態指示，
要能指出它讀的是哪一個 API 欄位或哪一個 WebSocket 訊息型別。
