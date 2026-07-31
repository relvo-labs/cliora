# 02 — 面板填滿與首次量測（LY-03、LY-04）

`LY-03` 是本期的主修正：它直接解掉「CLI 只有一半高度」。`LY-04` 收掉一個相鄰的、開場尺寸不對的小問題。

---

## LY-03 — 四個面板改 flex column 填滿

### 現況與問題

三個面板用「grid 列樣板 + auto-placement」決定高度，也就是**用子元素的數量與順序**決定誰拿到 `1fr`：

| 檔案:行 | 樣板 | 實際子元素 | 結果 |
|---|---|---|---|
| `SessionWorkspaceView.vue:598-604` | `auto minmax(0,1fr) auto` | CLI 面板只有 `.terminal-host`（`:386-390`）；TERMINAL 面板有提示列＋host＋狀態列（`:403-429`） | CLI 的 host 落在第 1 列 `auto` → **高度由 xterm 自己的 24 列決定**（迴圈推導見 `README.md` §1）。TERMINAL 面板正確，純屬子元素數量剛好對上 |
| `PreviewPane.vue:154-161` | `auto auto 1fr` | `.head`、`.meta`（`v-if="preview.meta.value && showEditor"`，`:110-113`）、`.body`（`:115`） | `meta` 不存在時 `.body` 落在第 2 列 `auto` → Monaco 容器塌陷。`meta` 只在「有 meta 且顯示編輯器」時出現，所以**raw／hint／錯誤狀態下必然踩到** |
| `FileTree.vue:163-169` | `auto auto auto 1fr` | `h2`、`FileSearchBar`、`FileTreeToolbar`、`.tree`，正常狀態剛好 4 個 | 目前正確。任何人在 `h2` 後面多插一行說明就會壞，而且不會有任何測試變紅 |

`.terminal-host`（`:631-634`）還有 `height: 100%`，在 `auto` 列裡是循環定義（百分比對不確定高度的列 → 退回 auto → 由內容決定 → 內容就是 xterm 自己），這是迴圈能自我維持的另一半。

### 目標寫法

**`SessionWorkspaceView.vue`**

```css
.terminal-pane {
  display: flex;
  flex-direction: column;
  background: var(--terminal-background);
  border-radius: var(--radius-md);
  overflow: hidden;
}
/* 提示列與狀態列都是 v-if：它們在不在，都不能影響 host 拿到剩餘空間。 */
.shell-notice,
.shell-status {
  flex: 0 0 auto;
}
.terminal-host {
  flex: 1 1 auto;
  min-height: 0;
  width: 100%;
  /* height: 100% 必須移除：在 flex column 裡它會被當成 flex-basis 的來源，
     於是 host 想要「容器的 100%」而提示列也想要自己的高度，總和超出容器後
     由 shrink 決定誰被壓縮——結果依然不是「host 拿剩餘空間」。 */
}
```

**`PreviewPane.vue`**

```css
.preview {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-height: 0;
  height: 100%;
}
.head,
.meta {
  flex: 0 0 auto;
}
.body {
  flex: 1 1 auto;
  min-height: 0;
  position: relative; /* 原本就有 */
  ...
}
```

`.host`（`:191-194`）的 `width/height: 100%` **保留**：`.body` 作為 flex item 在版面結算後有確定高度，百分比可以正常解析（這與現在「`meta` 存在時」的行為完全相同，只是不再取決於 `meta` 在不在）。Monaco 是 `automaticLayout: true`（`useMonacoModel.ts:92`），容器一變它自己會 `layout()`，所以不需要新增任何 JS。

**`FileTree.vue`**

```css
.tree-panel {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 0;
  height: 100%;
}
.tree {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
}
```

`h2`、`FileSearchBar`、`FileTreeToolbar` 與各種 `AsyncState` 都不必標 `flex: 0 0 auto`——flex column 的預設 `flex: 0 1 auto` 對它們正確（不成長、必要時可壓縮）。只有 `.tree` 需要明確成長。

**`.rail` 保持 `overflow: auto`（`SessionWorkspaceView.vue:584-590`）不動。** 看起來它與 `.tree` 的 `overflow: auto` 形成嵌套滾動，但這一層是很矮的視窗下唯一能捲到工具列的方式；`.tree` 拿走剩餘空間後，常態下 `.rail` 不會有可滾內容。把它改成 `hidden` 會讓「視窗太矮」從可以捲動變成永久看不到，那是把一個沒人抱怨的東西換成一個會被抱怨的東西。

### 為什麼是 flex 而不是「把 host 明確指到第 2 列」

`grid-row: 2` 也能修 CLI 面板，但它保留了同一個前提：**面板的高度分配依賴每個子元素都正確聲明自己在第幾列**。四個面板、六種條件渲染狀態、`v-if` 的提示列與狀態列——這個前提遲早會再破一次，而且破的時候不會有紅燈（本期就是證明）。flex column 只需要「誰成長」這一個聲明，是**不可能因為新增一個兄弟元素而失效**的寫法。這也是決策 D3 把它寫成硬規則、並由 `LY-06` 的 grep gate 保護的原因。

### 產物清單

| 檔案 | 動作 | 理由 |
|---|---|---|
| `frontend/src/views/SessionWorkspaceView.vue` | `.terminal-pane`、`.shell-notice`、`.shell-status`、`.terminal-host` 四處樣式 | 主修正 |
| `frontend/src/components/file/PreviewPane.vue` | `.preview`、`.head`／`.meta`、`.body` 三處樣式 | 同型錯誤，條件性已壞 |
| `frontend/src/components/file/FileTree.vue` | `.tree-panel`、`.tree` 兩處樣式 | 同型錯誤，目前僥倖成立 |

**不動任何 template、任何 script、任何 JS 邏輯。** 這張 ticket 是純 CSS。如果實作時發現需要改 JS 才能填滿，那表示診斷錯了，回來改本文件再動手。

### 測試

CSS 幾何 jsdom 量不到（D8），所以本 ticket 的自動化分兩層：

| 層 | 測試 | 斷言 |
|---|---|---|
| 幾何（`LY-06`） | Playwright `layout: the CLI terminal fills the centre pane` | `#panel-cli` 內 xterm 畫面高度 ≥ 面板 `clientHeight` × 0.9；1440×900 下列數 ≥ 30；切 tab 往返後列數不變。**這是唯一會因為本 ticket 做錯而變紅的測試** |
| 寫法（`LY-06`） | CI grep gate | `grid-template-rows` 不得再出現在 `.terminal-pane`／`.preview`／`.tree-panel` 三個規則裡；`.terminal-host` 不得再有 `height: 100%` |
| 既有回歸 | `npm run test:unit -- --run` | 330 例全綠；特別是 `SessionWorkspaceView.test.ts`（19 例）與 `FileTree.test.ts`（5 例）不得因為 class 改名而紅——**本 ticket 不改任何 class 名稱**，所以應為零影響 |

### 規格同步

無新增。`research/tech.md:1711-1717`（§16.1）已寫「xterm.js / Monaco（擇一佔滿）」，本 ticket 是讓實作符合它。`LY-07` 會把「佔滿」變成一條**可量測**的 PRD AC，那才是規格層的補強。

### 證據

- `cd frontend && npm run test:unit -- --run`
- `npm run format:check && npm run lint && npm run typecheck && npm run build`
- `LY-06` 的量測輸出（列數與百分比）記進 `05-implementation-status.md`

### 未關項

無。

---

## LY-04 — 首次量測與尺寸同步：shell 不再以 24×80 開場

### 現況與問題

`SessionWorkspaceView.vue:176`：

```ts
const created = await api().openShell(props.id, { rows: 24, columns: 80 });
```

24×80 是硬寫的。`LY-03` 之後真實面板約 43×110（推算，`00-…md` §4），所以開場流程是：node 上以 24×80 開 PTY → 前端 fit → 送 `terminal.resize` → PTY 重新塑形。bash 與任何在啟動時畫過畫面的東西會在使用者眼前重排一次。

CLI session 沒有這個問題：建立時前端不送 rows/columns（`api/dto.ts:208` 的 `rows?` 為選用，`NewSessionDialog.vue` 不帶），由伺服器預設，第一次 attach 後才由 fit 對齊。

另外，`LY-03` 改變了**掛載時的量測結果**：以前 host 在 xterm 尚未渲染前高度為 0，`fitSafely()`（`useTerminalSession.ts:67-74`）依設計拒絕量測，於是 24 列成為既成事實；之後 host 有確定高度，掛載時的 `fitSafely()`（`:220`）就會直接算出正確列數。**這是好事，但要有測試把它釘住**，否則將來有人把 `.terminal-host` 的 `flex: 1` 改回去，症狀又會悄悄回來（只會表現為「行數怪怪的」）。

### 目標

1. `useTerminalSession` 對外新增 `proposeSize()`：

```ts
// 供「建立 session 時就用正確尺寸開場」使用。回 null 表示現在量不準
// （容器隱藏或還沒版面），呼叫端應退回伺服器預設，而不是送一個猜的值。
function proposeSize(): { rows: number; columns: number } | null {
  if (!terminal || !hostElement) return null;
  if (hostElement.clientWidth === 0 || hostElement.clientHeight === 0) return null;
  const dims = fit?.proposeDimensions();
  if (!dims || dims.rows < 2 || dims.cols < 2) return null; // 與 sendResize() 同一條下界
  // 上界（實作時補上，原計畫漏了）：wire 契約寫的是 rows 2–300、columns 2–500
  // （contracts/v1/schemas/messages/session-start.schema.json）。這不是理論問題——
  // 夠寬的視窗真的會提出超過 500 欄，而 Central 對超範圍的尺寸回 422，終端機會
  // 直接開不起來。
  return { rows: Math.min(dims.rows, 300), columns: Math.min(dims.cols, 500) };
}
```

2. `openShellTab()`（`SessionWorkspaceView.vue:165-186`）在呼叫 `openShell` **之前** `await nextTick()`，讓剛剛被 `v-show` 顯示的面板完成版面，然後：

```ts
await nextTick(); // 面板剛由 v-show 顯示，量測前必須先有版面
const size = shellTerminal.proposeSize() ?? { rows: 24, columns: 80 };
const created = await api().openShell(props.id, size);
```

保留 24×80 作為退路（例如視窗被最小化時點 tab），但它不再是常態值。

3. `<2` 的下界與 `sendResize()`（`:56`）用同一條，理由相同：daemon 的 tmux `validSize` 會拒絕，猜一個小值等於讓 PTY 以錯誤尺寸開場。

### 產物清單

| 檔案 | 動作 | 理由 |
|---|---|---|
| `frontend/src/composables/useTerminalSession.ts` | 新增 `proposeSize()` 並在回傳物件中公開 | 上述 1 |
| `frontend/src/views/SessionWorkspaceView.vue` | `openShellTab()` 加 `await nextTick()` 與 `proposeSize()` | 上述 2 |
| `frontend/src/composables/useTerminalSession.test.ts` | 擴充 FitAddon mock（現在只有 `fit`，`:32-38`）加上 `proposeDimensions`；新增 3 例 | 見下 |

### 測試

| 測試 | 斷言 |
|---|---|
| `useTerminalSession.test.ts`「host 可量測時 proposeSize 回報 FitAddon 的建議值」 | 以 `Object.defineProperty(element, "clientWidth"/"clientHeight", …)`（既有作法見 `:116-117`）給 800×600，`proposeSize()` 回 `proposeDimensions()` 的值 |
| `useTerminalSession.test.ts`「host 隱藏時 proposeSize 回 null」 | jsdom 預設 0×0（既有作法見 `:182`），回 `null`，且不呼叫 `proposeDimensions` |
| `useTerminalSession.test.ts`「建議值小於 2 列或 2 欄時回 null」 | 擋掉「量到了但量到垃圾」這一類，與 `sendResize()` 的下界一致 |
| `useTerminalSession.test.ts`「建議值夾到契約範圍」 | `{rows: 900, cols: 620}` → `{rows: 300, columns: 500}`，否則超寬視窗會讓 Central 回 422 |
| `SessionWorkspaceView.test.ts`「開啟 TERMINAL 時以量測到的尺寸建立 shell」 | `openShell` 被呼叫時帶的是 `proposeSize()` 的值；量不到時退回 `{rows:24, columns:80}` |

### 規格同步

`research/tech.md:1728-1740` 的「實作限制」補一條，與既有「隱藏容器不得 fit」同源：

> * 建立新的終端機 session 時，若容器已可量測，**應以量測到的 rows/columns 建立**；量不到就交給伺服器預設，不要送猜測值。以錯誤尺寸開場再 resize，會讓 PTY 在使用者眼前重排一次。

### 證據

- `cd frontend && npm run test:unit -- --run`（`useTerminalSession.test.ts` 14 → 17 例、`SessionWorkspaceView.test.ts` 19 → 20 例）
- `LY-06` 的 E2E：TERMINAL tab 開啟後**第一次**量到的列數就 ≥ 30（不是先 24 再變大）

### 未關項

- 「開場尺寸」對 CLI session 不適用（前端不參與建立時的尺寸），本期不改動這一點；若日後 `NewSessionDialog` 要帶尺寸，前置條件是它當時還沒有終端機容器可量，需另設計。
