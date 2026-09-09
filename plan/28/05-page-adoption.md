# 05 — 頁面採用（`VR-07`／`VR-08`／`VR-09`）

十一個頁面。順序是刻意的：工作台先（它是主要畫面，也是唯一有終端的），
表格頁次之（它們共用 `DataTable`，一次改完），表單與其他最後。

**共同規則：這三張票不改任何 store、composable、`api/` 或 `protocol/`。**
判準見 `00-…md` D14。每一頁的驗收都對照 `04-…md` §4 的十一種狀態。

## 1. `VR-07`：Session 工作台

`SessionWorkspaceView.vue`（1100 行）是本期最大的一塊，也是唯一一個
「動錯就會斷線」的頁面。

### 1.1 結構

```
AppLayout(fill)
└─ .workspace                      ← flex column，高度來自 shell（plan/09 D1）
   ├─ SessionHeader                 72px 固定
   ├─ InlineNotice ×0..n            actionError / gap / uploadRefusal
   ├─ .grid                         minmax(0,1fr) × [center | FilePanel]
   │  ├─ .center                    flex column
   │  │  ├─ WorkspaceTabs           44px 固定
   │  │  ├─ .pane.terminal-pane     ← 選擇器名不得改
   │  │  ├─ .pane.terminal-pane     （系統終端）
   │  │  └─ .pane .preview          ← 選擇器名不得改
   │  └─ FilePanel                  258px 可調 / 抽屜
   └─ StatusBar                     28px 固定
```

### 1.2 五條不得違反的既有性質

1. **`.workspace` 容器永不卸載。** loading／forbidden／error 以 `.veil` 疊在上面，
   不是取代它（`WT-02`）。本期新增的 StatusBar 在 veil 之下也要**能顯示**——
   Session 載入失敗時，狀態列要說「無法載入」而不是空白。
2. **兩個終端面板 `v-show` 不 `v-if`。** 它們持有 WebSocket 與 xterm buffer。
3. **`v-if="previewPath"` 的預覽面板維持 `v-if`。** 它沒有連線，關閉要 dispose Monaco。
4. **面板隱藏時不以 0×0 resize 遠端 PTY**；重新顯示後才 fit（既有的
   `watch(activeTab)` 已經做對，不要在重排時弄丟它）。
5. **`pagehide` 與 `onBeforeUnmount` 的系統終端收尾三條路徑**（`:205-248`）一行不動。

### 1.3 資訊重組

| 資訊 | 現在在哪 | 本期在哪 |
|---|---|---|
| Session 名稱 | `.head h1` | SessionHeader 第 1 列 |
| runtime、workspace 路徑 | `.head .dim` | SessionHeader 第 2 列（路徑中段省略 ＋ 複製） |
| Node 名稱 | **沒有顯示** | SessionHeader 第 2 列（共用規範的「Session 身份」要求 Node） |
| Session 狀態 badge | `.head` | **StatusBar** |
| 連線狀態 badge | `.head` | **StatusBar** |
| 控制權標籤 | `.head .role` | **StatusBar** |
| 沙箱／提權姿態 | `.head .posture` | SessionHeader 第 2 列（**留在這裡**，ADR 0023 D10） |
| Request control | `.head .actions` | SessionHeader 第 1 列（唯讀且有權限時） |
| Reconnect | `.head .actions` | SessionHeader 第 1 列（`canRetry` 時） |
| Terminate | `.head .actions`（常駐紅鈕） | **`⋯` 選單**，確認框顯示 Session 名稱 |
| Back | `.head .actions` | 移除——導覽已經有 Sessions，而且瀏覽器有上一頁 |

「Node 名稱沒有顯示」是實質缺口而不是樣式問題：共用規範的資訊架構把
「名稱、Node、Runtime、Workspace」四項並列為 Session 身份，而 Node 是其中
唯一一個現在看不到的（`nodePosture` 已經抓回來了，只是沒有印出來）。

### 1.4 圖片投放與檔案上傳的外觀

**行為一行不動**（ADR 0024／0026、`00-…md` D14）。只改：

- drop bar 從一條 inline flex 收進 `Toolbar`，坐在終端面板頂端，
  文字用 `--text-on-terminal`。
- 上傳佇列移進 `FilePanel`（`04-…md` §3.3）。
- 拖放高亮用 `--accent-primary` 的 2px 外框，**不用**背景色填滿——
  填滿會蓋掉終端內容，而使用者正在看的就是那些內容。
- `renameAndRetry` 目前用 `window.prompt`（`:364`）。**本期不改它。**
  換成內嵌表單是行為變更（焦點、驗證、取消路徑都要重新設計），
  而它不在視覺更新的範圍。列進 `08-…md` 的「沒有要量什麼」。

### 1.5 終端

- `fontSize` 14（`VR-01` 定案）、`lineHeight` 1.2、`fontFamily` 純本機等寬堆疊。
- 使用者可在 StatusBar 調 12–20px，變更後 `terminal.options.fontSize = n` ＋ `fit()`，
  **不重建**（`FR-TERM-001.AC-16` 提案）。
- ANSI 十六色套用（`02-…md` §8）。
- **終端內容不做任何動畫**（共用規範明文）：不淡入、不縮放、不打字動畫。
  重連時保留可讀輸出。

## 2. `VR-08`：表格頁

### 2.1 `SessionsView`（202 行）

| 項目 | 規則 |
|---|---|
| 主欄 | Session 名稱（可開啟）＋ **路徑為次列** |
| 比較欄 | Node／Runtime／狀態／最後活動 |
| 空清單 | 「尚未建立 Session」＋ 建立入口（有權限時） |
| 篩選無結果 | 「沒有符合條件的項目」＋ 清除搜尋與篩選 |
| 建立後 | 開啟新工作台（現有行為，不變） |

### 2.2 `NodesView`（315 行）／`NodeDetailView`（775 行）

| 項目 | 規則 |
|---|---|
| 第一層 | 識別、上線狀態、Runtime 可用性 |
| **資源資訊不足** | 顯示「無資料」，**不用 0 代替**（五份文件都明列） |
| Node 卡片 | 1px 邊線區分，**卡片不再包卡片**（Graphite §5） |
| 離線 Node | 不可建立 Session（現有行為）——但要說明**為什麼**不可 |
| 姿態（沙箱／提權） | 沿用現有顯示，換 token（ADR 0023） |

「不用 0 代替」要當成一條可驗的規則：`VR-11` 要有一個單元測試，
餵 `cpu: null` 進去，斷言畫面出現「無資料」而不是 `0%`。

### 2.3 `NodeTunnelsView`（1092 行）

最大的一個檔案，六個字面色值。本期只換樣式與 token、採用 `DataTable` 與 `Field`，
**不重構**它的邏輯——那是一張獨立的票，而且它動到 ADR 0022 的整合設定。

## 3. `VR-09`：其他頁面

### 3.1 `DashboardView`（399 行）

| 項目 | 規則 |
|---|---|
| 順序 | **「繼續工作」在指標之前**（五份文件都明列） |
| 統計 | 顯示回報時間與完整性（`FreshnessBadge` 已存在，保留） |
| 禁止 | **不加入不存在的即時監測**。沒有資料來源的指標不得新增 |
| 部分過期 | 保留其他有效資料 ＋ `InlineNotice` ＋ 可重試（`UnhealthyNodeList` 已有雛形） |

「繼續工作在指標前」是一個真正的重排：現在 `DashboardView` 是
指標卡在最上面。`favorites` store 已經有資料，只是沒有被放在第一位。

### 3.2 `AuditView`（524 行）

可篩選表格。採用 `DataTable` ＋ `Toolbar`。
`forbidden` 狀態要維持現有形狀：伺服器的 403 才是授權，
UI 不做 client-side guard（`router/index.ts` 的註解已寫明，不要在本期「順手加上」）。

### 3.3 `EnrollmentView`（491 行）／`IntegrationsView`（727 行）

表單與設定群組。採用 `Field`：**label 常駐、錯誤在欄位下方、必填可讀**。
Integrations 持有憑證輸入，本期不改任何遮罩／保存邏輯（ADR 0022）。

### 3.4 `LoginView`（163 行）

唯一一個**沒有 AppLayout** 的頁面（`gate_height` 對它與 `AppLayout` 開了例外）。
它要自己套主題：`theme-boot.js` 已經在 `<html>` 上設好 `data-theme`，
所以它只要用 token 就會跟著走。**不要**在這裡加第二套高度公式。

### 3.5 `TokenShowcaseView`（100 行，dev-only）

從「三個元件的展示」擴充成**本期的驗收面板**：十二個共用元件 × 每個元件的
全部狀態，兩款主題各一次。它是 `VR-12` 截圖證據的來源，也是
`00-…md` §6 共同 DoD 第 3 項的落地處。

它仍然只在 `import.meta.env.DEV` 註冊（`router/index.ts:80-86`），
所以不進 production bundle。

## 4. 每頁的驗收清單

十一個頁面 × 兩款主題 × 三個斷點，各要能回答：

- [ ] 十一種狀態（`04-…md` §4）中，這一頁會出現的每一種都有畫面。
- [ ] 空清單與篩選無結果的文案**不一樣**。
- [ ] 長名稱、長路徑不遮住必要動作（測試字串：80 字元的 Session 名稱、
      12 層深的路徑、含中日文與 emoji 的檔名）。
- [ ] 文字縮放 200% 下控制項仍可操作（共用規範明文）。
- [ ] 沒有不必要的整頁橫向溢出。
- [ ] 鍵盤可完成該頁的主要流程。
- [ ] 每一個 disabled 控制項都說得出**為什麼** disabled。
