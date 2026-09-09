# 03 — App Shell 與導覽（`VR-04`）

依賴 `VR-03`。本票**不改任何 store、composable 或 API**——它改的是
`AppLayout.vue` 的結構、三個新元件，以及 `SessionWorkspaceView` 的外層框架。

## 1. 現況與目標

`AppLayout.vue` 是 `plan/09` LY-01 的成果，它做對了最難的一件事：
**shell 擁有視窗高度，而且是唯一一個擁有它的地方**（`:96-110` 的 grid）。
本票**不動那個 grid 的原則**，只增加欄寬的可變性與一列狀態列。

| | 現況 | 本期 |
|---|---|---|
| grid 欄 | `var(--layout-sidebar) minmax(0, 1fr)` 固定 | 同形狀，但第一欄在收合時是 `var(--layout-sidebar-collapsed)` |
| grid 列 | `auto minmax(0, 1fr)` | `auto minmax(0, 1fr)`（狀態列屬於**工作台頁面內部**，不是 shell 的第三列） |
| 導覽圖示 | 七個文字符號（`:50, 62-75`） | Lucide |
| 收合 | 只在 ≤900px 自動（`:207-215`） | 桌面可手動 ＋ 斷點自動；狀態持久化 |
| 品牌區 | `◫` ＋ 產品名 | Lucide 標記 ＋ 產品名，收合時只留標記 |
| 帳號區 | header 右側純文字 ＋ Sign out | 不變（本期只換樣式與 token） |

### 狀態列為什麼不是 shell 的第三列

`style.md §9` 的圖把 Status Bar 畫在最底下、橫跨整個視窗。但它的**內容**
（Session 狀態、瀏覽器連線、控制權）只在 Session 工作台有意義——
Nodes 頁面沒有 Session 可以報。做成 shell 的第三列，就要在其他十個頁面
渲染一條空的 28px，或者讓 shell 知道當前路由是什麼（shell 開始認識業務）。

**決定：狀態列屬於工作台頁面**（`SessionWorkspaceView` 的最後一列），
`--layout-status` 這個 token 由該頁使用。`style.md §9` 的圖同步修訂
（`01-…md` M3 已含這一句）。

## 2. PrimaryNav

### 2.1 圖示對應

`lucide-vue-next` 已是相依（`package.json:26`）且已在四個檔案使用。

| 導覽項 | 現況符號 | Lucide |
|---|---|---|
| 品牌標記 | `◫` | `SquareTerminal` |
| Dashboard | `◈` | `LayoutDashboard` |
| Nodes | `▣` | `Server` |
| Sessions | `▷` | `TerminalSquare` |
| Enrollment | `◉` | `KeyRound` |
| Audit | `☰` | `ScrollText` |
| Integrations | `⇄` | `Plug` |
| 收合／展開 | 無 | `PanelLeftClose` / `PanelLeftOpen` |

文字符號不只是風格問題：`▷` 在部分平台會被字型替換成 emoji 變體（寬度與字重都變），
而且它現在是**可讀的文字節點**——螢幕閱讀器會把它念出來，念成什麼由字型資料庫決定。

### 2.2 收合態

- 展開 `--layout-sidebar`（208px）／收合 `--layout-sidebar-collapsed`（64px）。
- 收合時**只有圖示**：每一項必須有 `aria-label` **與** tooltip（共用規範明文）。
  tooltip 不能取代 `aria-label`——tooltip 是滑鼠的，`aria-label` 是螢幕閱讀器的。
- 切換鈕在側欄底部，`aria-expanded` 反映狀態，`aria-controls` 指向 `<nav>`。
- 狀態存 `localStorage`（`cliora-nav-collapsed`），與主題同一個偏好模組。
- **收合是視覺狀態，不是權限狀態**：收合後每一項仍在 DOM 裡、仍可 Tab 到。

### 2.3 選中態

Graphite 規格：「青綠文字 ＋ 深青綠底 ＋ 2px 左邊線」。落成 token：

```
color: var(--accent-strong);          /* 疊在 accent-subtle 上，實測 6.35:1（G）／5.90:1（P） */
background: var(--accent-subtle);
border-left: 2px solid var(--accent-primary);
font-weight: 600;
```

選中同時由**顏色、底色、邊線、字重**四者表達。現況只有底色與顏色
（`AppLayout.vue:184-188`），而 `style.md §17` 的原則（狀態不只用顏色）
在導覽上一直沒有被套用。

### 2.4 權限與導覽

`AppLayout.vue:24-33` 的三個 `hasPermission` 判斷**一行不動**。
它們決定的是「要不要顯示這一項」，而伺服器仍然是唯一的授權者（ADR 0016）。
收合態下被隱藏的項目**仍然是隱藏**，不是變成圖示——權限不因版型改變。

## 3. SessionHeader

現況：`SessionWorkspaceView.vue:474-520` 的 `.head`，一個 flex 裡塞了
Session 名稱、runtime、workspace 路徑、兩個 StatusBadge、控制權標籤、
零到兩個姿態標籤，以及右側四個按鈕。長 Session 名稱一出現就換行，
而換行會把整個工作面往下推（因為 `.head` 的高度是內容決定的）。

本期抽成 `SessionHeader.vue`，高度固定 `--layout-workhead`（72px），兩列：

```
第 1 列（28px）  Session 名稱（可截斷，title 顯示完整）    [取得控制權] [重新連線] [⋯]
第 2 列（20px）  Node · Runtime · Workspace 路徑（中段省略，可複製）  · 姿態標籤
```

規則：

- **狀態不放這裡**——Session 狀態、連線狀態、控制權三者移到狀態列（§4）。
  這是本期最明顯的一處資訊重組，理由是共用規範的資訊架構把它們分成兩個層次。
- **姿態標籤留在這裡**（ADR 0023 D10：使用者按下 Enter 之前就要在眼前）。
  它們不是狀態，是這台 Node 的性質。
- **`Terminate` 移進 `⋯` 選單並保留確認**（Graphite §5「危險操作」：
  「終止放操作選單並確認 Session 名稱；不占據日常主動作位置」）。
  確認對話框要**顯示 Session 名稱**——現況只有一句泛用文字。
- 長路徑用中段省略（`/workspace/…/cliora`）而不是尾端省略：
  尾端省略會把最有資訊量的那一段（目錄名）砍掉。完整路徑在 `title` 與複製鈕。

## 4. StatusBar（新元件）

`--layout-status`（28px）從 P0 至今沒有被實作過（`tokens.css:37-39` 的註解自己寫著
「Not in use」）。本期實作。

```
┌──────────────────────────────────────────────────────────────────────┐
│ ● Session 執行中   ● 已連線   ● 你有控制權        14 px 終端  ⌄  主題 ⌄ │
└──────────────────────────────────────────────────────────────────────┘
```

三個狀態**分列**，各自帶文字（共用規範：「分開描述；不要合成一個綠色『正常』」）：

| 位置 | 來源 | 值域 |
|---|---|---|
| Session 狀態 | `session.status` | 建立中／執行中／已結束／失敗／已終止 |
| 瀏覽器連線 | `terminal.status`（composable） | 連線中／已連線／重新連線中／已斷線 |
| 控制權 | `terminal.role` | 你有控制權／唯讀（他人持有） |

右側放兩個偏好控制項（`VR-10`）：終端字級與主題。放在這裡而不是全域 header，
理由是它們**只在有終端的頁面有意義**；主題切換在其他頁面由帳號選單提供。

### 為什麼這三個不能合併

現況把它們並排成兩個 `StatusBadge` ＋ 一個文字標籤（`:481-484`），
而三者的組合有實際意義：**「Session 執行中 ＋ 已斷線」不等於「Session 已結束」**。
第一種要按重新連線，第二種按了沒有用（共用規範：「不將 Reconnect 呈現為重新啟動」）。
合成一個綠燈會讓這兩種情況長得一樣。

### 高度的代價

28px 是從終端拿走的，約 1.7 列（`00-…md` §4 的算式已含）。
這一項與 D12 一起決定終端剩幾列，所以它在 `VR-01` 的量測範圍內。

## 5. 響應式四段

`style.md §24` 現在寫「Desktop Only」，`VR-02` 修訂它（`01-…md` M7）。
修訂後的四段與程式一一對應：

| 斷點 | 導覽 | 檔案欄 | 工作標頭 | 其他 |
|---|---|---|---|---|
| ≥1440px | 展開 208px（可手動收合） | 258px 可調 | 兩列 72px | 桌面基準 |
| 1024–1439px | **自動收合** 64px（可手動展開為覆蓋層） | 258px 可調 | **單列 48px**（Node／Runtime／路徑改為可展開） | 外距縮減 |
| 768–1023px | 64px | **覆蓋抽屜**，工具列有開啟鈕 | 兩列，路徑改為可展開 | |
| <768px | **頂部選單**（開啟為覆蓋層） | 覆蓋抽屜 | 單列 ＋ 可展開資訊區 | 主面板單欄 |

工作標頭在 1024–1439px 收成單列，是 `VR-01` 第 1 項量出來的結果而不是設計偏好：
1024×768 的 CLI 面板只有 542px，`14px/1.2` 只給 **28 列**。收成單列可回收 24px
（→ 29 列），其餘倚賴使用者可調字級（`13px/1.2` 在該尺寸是 30 列）。
完整數字與推導在 `08-…md` §1.1。

三條硬規則：

1. **不將功能直接隱藏。** 現況 ≤1100px 的檔案樹是 `display: none` 而且**沒有任何開啟入口**
   （`SessionWorkspaceView.vue:1092-1098`）。這正是共用規範禁止的形狀。
2. **終端輸入的權限不因裝置尺寸改變**（共用規範明文）。
   `<768px` 不做「唯讀模式」——那是授權，不是版面。
3. **抽屜要有焦點約束與 Esc**，關閉後焦點回到開啟鈕。與 Dialog 共用同一個
   `useFocusTrap`（`04-…md` §3.2）。

### 既有 E2E 的影響

`frontend/tests/e2e/session.spec.ts` 目前在 1000×800 斷言
`getByRole("tree", { name: "工作區檔案" })` 是 **hidden**，
註解寫「Below the breakpoint the file tree is hidden rather than squeezed」。

新行為下 1000px 落在「768–1023：覆蓋抽屜」，抽屜預設關閉 ⇒ 樹仍然 hidden ⇒
**這條斷言仍然通過**，但它的意思變了。`VR-11` 要：

- 更新那段註解（不然它會誤導下一個人以為功能被隱藏是對的）；
- 新增一條斷言：**開啟鈕存在且可觸及**，按下之後樹可見、Esc 之後焦點回到開啟鈕。

## 6. 焦點順序與 skip link

現況沒有 skip link。四段版型下，鍵盤使用者從網址列進來要先穿過
六個導覽項 ＋ 帳號區才能到終端。

- `<a class="skip" href="#main">跳至主要內容</a>` 作為 shell 的第一個可聚焦元素，
  平時視覺隱藏、`:focus` 時可見。
- 焦點順序：skip → 品牌 → 導覽 → 收合鈕 → 帳號 → main。
- **終端拿到焦點後，全域快捷鍵一律停用**（共用規範：「快捷鍵不可攔截終端原生輸入；
  僅在非終端焦點下啟用全域快捷鍵」）。本期不新增任何全域快捷鍵，
  但這條規則要寫進 `04-…md` 的元件契約，因為 `VR-10` 的偏好控制項是第一個候選。

## 7. 不得弄壞的

1. `plan/09` D1：**只有 shell 擁有視窗高度**。新增的抽屜是 `position: fixed` 的覆蓋層，
   不參與 shell 的 grid，也不得使用 `100vh` 以外的高度推導——它用 `inset: 0`。
   `gate_height` 會抓 `100vh`／`100dvh`，抽屜若需要要走 `inset`。
2. `plan/09` D3：面板不得以子元素數量決定高度。SessionHeader 從「內容決定高度」
   改成固定 72px，方向正確；但它內部的兩列**必須用 flex column 而不是
   `grid-template-rows`**，否則 `gate_panels` 的精神被繞過（雖然它只檢查三個選擇器）。
3. `plan/09` D5：`--layout-sidebar` 的三處數字（`tokens.css`、`style.md §9`、`§22`）
   必須一致。本期**不改它**（維持 208），所以 `gate_sidebar` 直接沿用。
4. `.terminal-pane`、`.preview`、`.tree-panel` 三個選擇器名不得改（`00-…md` D13）。
