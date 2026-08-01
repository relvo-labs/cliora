# 01 — App shell 幾何與高度來源（LY-01、LY-02）

這兩張 ticket 只做一件事：**讓「可用高度」在整個前端只有一個定義處**。它們本身不會讓 CLI 變高（那是 `LY-03`），但沒有它們，`LY-03` 只是把面板填滿一個算錯的框。

---

## LY-01 — App shell 改為視窗高度 grid，`main` 成為唯一滾動容器

### 現況與問題

`AppLayout.vue` 目前是「兩個 fixed 元素 + 一個用 padding 補位的 main」：

| 位置 | 現況 | 後果 |
|---|---|---|
| `:67-78` | header `position: fixed; inset: 0 0 auto; height: var(--layout-header); z-index: 3` | 脫離文件流，main 必須自己讓開 |
| `:124-133` | aside `position: fixed; top: var(--layout-header); bottom: 0; width: var(--layout-sidebar); z-index: 2` | 同上，main 必須 `margin-left` |
| `:152-156` | main `min-height: 100vh; margin-left: var(--layout-sidebar); padding: calc(var(--layout-header) + 24px) 28px 40px` | **main 的高度是隱含的**：內容區實際只有 `100vh − 56 − 24 − 40 = 100vh − 120`，而且是 `min-height` 不是 `height`，沒有任何 view 能從 CSS 直接繼承它 |
| `:157-167` | `@media (max-width: 900px)`：aside 縮 64px、main `margin-left: 64px` | 兩處寬度要各自改，容易漏 |

`SessionWorkspaceView.vue:494` 因此自己寫了第二套公式 `calc(100vh - var(--layout-header) - 48px)`，與上面差 16px，造成 Session Workspace 一直有一條約 16px 的整頁垂直滾動。

### 目標寫法

```css
.shell {
  display: grid;
  grid-template-columns: var(--layout-sidebar) minmax(0, 1fr);
  /* header 用 auto 而不是 var(--layout-header)：header 內容在窄視窗會換行，
     寫死列高會讓它溢出到 main 上面（現在是 fixed 所以看不出來）。header 自身
     仍保留 height: var(--layout-header)，所以常態下這一列就是 56px。 */
  grid-template-rows: auto minmax(0, 1fr);
  /* 100vh 先寫，dvh 後寫：不支援 dvh 的瀏覽器停在 100vh（決策 D2）。 */
  height: 100vh;
  height: 100dvh;
}
.shell > header {
  grid-column: 1 / -1;
  /* position/z-index/inset 全部移除 */
}
.shell > aside {
  /* position/top/bottom/z-index 移除；寬度由 grid 欄決定 */
  min-height: 0;
  overflow-y: auto; /* 導覽項在很矮的視窗仍可捲到 */
}
.shell > main {
  min-height: 0;
  overflow: auto; /* 唯一滾動容器 */
  padding: 24px 28px 40px; /* 不再需要為 fixed header 補上 56px */
}
@media (max-width: 900px) {
  .shell {
    grid-template-columns: 64px minmax(0, 1fr);
  }
  .shell > aside span {
    display: none;
  }
  /* main 的 margin-left 規則整條刪除 */
}
```

三個要點：

1. **`minmax(0, 1fr)` 而非 `1fr`。** `1fr` 的最小值是 `auto`，一個內容很寬（Monaco、寬表格）的 main 會把欄撐爆，這正是 plan/08 花力氣擋掉的水平溢位（`session.spec.ts:253-334`）。
2. **`main` 有確定高度。** 這是整張 ticket 的目的：view 可以直接 `height: 100%`，不必推導。
3. **不需要 `html`／`body`／`#app` 的 `height: 100%` 鏈。** `frontend/index.html:11` 的 `#app` 沒有任何高度規則，`theme/base.css` 也沒有；用 viewport 單位就不必新增這三層（決策 D2）。

### 行為變更：滾動容器從 document 換成 main

這是本 ticket **唯一**的對外行為變更，必須實測而不是推論：

- `DashboardView`、`NodesView`、`NodeDetailView`、`AuditView`、`EnrollmentView`、`SessionsView` 目前都靠整頁滾動看完長內容。之後改成在 `main` 內滾。
- `FileTree.vue:74` 的 `scrollIntoView({ block: "nearest" })` 對任何滾動容器都成立（已確認全前端只有這一處程式化滾動：`grep -rn "scrollIntoView\|window.scroll\|scrollTop" frontend/src` 僅此一筆）。
- 全前端沒有任何 `position: sticky`（同一次 grep 確認），所以沒有「sticky 相對哪個容器」的問題。
- `LoginView.vue:94` 的 `min-height: 100vh` 不受影響：它不使用 `AppLayout`。

### 產物清單

| 檔案 | 動作 | 理由 |
|---|---|---|
| `frontend/src/components/layout/AppLayout.vue` | 改 `<style scoped>`：`.shell`、`> header`、`> aside`、`> main`、`@media` 五處 | 上面的目標寫法 |
| `frontend/src/components/layout/AppLayout.test.ts` | **新增** | 目前沒有 AppLayout 的單元測試（`ls frontend/src/components/layout/` 只有 `.vue`）。jsdom 不能量幾何（D8），所以這支測試只鎖**結構契約**：header／aside／main 都是 `.shell` 的直接子元素、`main` 承載 slot 內容、`fill` 由 `LY-02` 補 |

### 測試

| 測試 | 斷言 |
|---|---|
| `AppLayout.test.ts`「shell 的三個區塊都是直接子元素」 | `.shell > header`、`.shell > aside`、`.shell > main` 各存在一個（grid 的欄列指派只在直接子元素上生效，這一條擋掉「有人為了包一層而破壞 grid」） |
| `AppLayout.test.ts`「slot 內容渲染在 main 內」 | 傳入的 slot 出現在 `main` 之內而非 `.shell` 之下 |
| `LY-06` 的 Playwright | 整頁無垂直滾動、`main` 是實際的滾動容器（見 `04-…md`） |

**已知不足（明講）**：以上兩項都不會因為 `.shell` 的 `height` 寫錯而變紅。jsdom 沒有 layout，這是 D8 的直接後果；幾何的紅燈只能來自 `LY-06`。

### 手動驗證清單（六頁）

改完後每一頁都要看：內容能滾完、header 與 sidebar 不隨內容滾走、視窗縮到 900px 以下時 sidebar 變成 64px 圖示欄且 main 沒有被 margin 推歪。

`/dashboard`、`/nodes`、`/nodes/:id`、`/sessions`、`/audit`、`/enrollment`。

### 規格同步

無。app shell 的幾何在 `research/style.md:477-505`（§9）已經是「Header 56 / Sidebar / Inspector / Status Bar」的 IDE 版面，本 ticket 只是把實作方式從 fixed 換成 grid，數字不變（寬度數字在 `LY-05` 改）。

### 證據

- `cd frontend && npm run test:unit -- --run`
- `npm run lint && npm run typecheck && npm run build`
- 六頁手動驗證的截圖或錄影放 `artifacts/ly/local/`。

### 未關項

無。

---

## LY-02 — Session Workspace 改 `fill` 模式，刪除第二套高度公式

### 現況與問題

`SessionWorkspaceView.vue:490-495`：

```css
.workspace {
  position: relative;
  display: flex;
  flex-direction: column;
  height: calc(100vh - var(--layout-header) - 48px); /* ← 第二套公式，且比 main 的內容區高 16px */
}
```

`LY-01` 之後 `main` 已有確定高度，這一行可以直接變成 `height: 100%`。但還有一件事要一起處理：**Session Workspace 不該吃 `main` 的通用內距**。`AppLayout.vue:155` 的 `28px` 左右與 `24px/40px` 上下對表格頁合理，對「Terminal 就是工作區」（`research/style.md:734-747`）的頁面則是直接從終端機身上扣掉 64px 高、56px 寬。

### 目標寫法

`AppLayout.vue` 新增一個 prop：

```ts
const props = defineProps<{ fill?: boolean }>();
```

```vue
<main :data-fill="fill ? '' : undefined"><slot /></main>
```

```css
/* 填滿模式：給「頁面本身就是一個固定版面」的 view 用（目前只有 Session
   Workspace）。main 不再滾動——會滾的是版面內部的面板；內距收窄，因為這裡
   每 8px 都直接換成終端機的行數。 */
.shell > main[data-fill] {
  overflow: hidden;
  padding: 12px 16px;
  display: grid;
  grid-template-rows: minmax(0, 1fr);
}
```

`SessionWorkspaceView.vue`：

```vue
<AppLayout fill>
```

```css
.workspace {
  position: relative;
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}
```

用 `data-fill` 屬性而不是 class：scoped style 對屬性選擇器與 class 選擇器同樣有效，而屬性在 DOM 上一眼看得出是誰打開的，也讓 `LY-06` 的 Playwright 可以直接用 `main[data-fill]` 定位量測。

### 為什麼 `overflow: hidden` 不是 `auto`

fill 模式的頁面**沒有整頁滾動這件事**：中央面板自己滾（xterm 的 viewport、Monaco 的編輯器、檔案樹的 `.tree`）。如果 main 還能滾，任何一個內部面板算錯高度就會表現為「整頁多出一點可以滾」——也就是現在這 16px 的樣子——而不是明確的紅燈。`hidden` 讓算錯高度變成看得見的裁切，而不是可以忍受的滾動。

### 產物清單

| 檔案 | 動作 | 理由 |
|---|---|---|
| `frontend/src/components/layout/AppLayout.vue` | 新增 `fill` prop、`data-fill` 綁定與 `main[data-fill]` 樣式 | 上述 |
| `frontend/src/views/SessionWorkspaceView.vue` | `<AppLayout fill>`；`.workspace` 的 `height` 改 `100%` 並加 `min-height: 0` | 刪除第二套公式 |
| `frontend/src/components/layout/AppLayout.test.ts` | 補兩例 | 見下 |

### 測試

| 測試 | 斷言 |
|---|---|
| `AppLayout.test.ts`「預設不是 fill 模式」 | `main` 沒有 `data-fill` 屬性 |
| `AppLayout.test.ts`「fill 模式標在 main 上」 | 傳 `fill` 時 `main` 有 `data-fill` |
| `LY-06` 的 Playwright | `main[data-fill]` 的 `scrollHeight === clientHeight`（fill 頁面不得有任何殘餘滾動） |

既有的 view 單元測試全部把 AppLayout 換成 `stubs: { AppLayout: { template: "<div><slot /></div>" } }`（`SessionWorkspaceView.test.ts:134`、`DashboardView.test.ts:79`、`AuditView.test.ts:69,125`、`NodeDetailUpdate.test.ts:121,279`），stub 忽略未宣告的 prop，所以**新增 prop 不會動到這六處**。也因此 `fill` 的斷言只能寫在 AppLayout 自己的測試裡。

### 規格同步

`research/tech.md:1705-1717`（§16.1）的版面圖與「Terminal 自動 Fit」保持不變，但要在「實作限制」清單（`:1725-1740`）補一條，理由與既有三條同級——它們都是**正確性條件**而不是偏好：

> * 可用高度只有一個來源（app shell）。view **不得**以 `100vh`／`dvh` 或 `calc()` 自行推導頁面高度；需要固定版面的頁面用 app shell 的 fill 模式。兩套公式必然分歧，分歧會表現為整頁多出一小段滾動，而不是明顯的錯誤。

### 證據

- `npm run test:unit -- --run`（AppLayout 4 例）
- `grep -rn "100vh\|100dvh" frontend/src/views frontend/src/components` → 僅 `LoginView.vue` 一筆
- 手動：`/sessions/:id` 在 1440×900 下沒有整頁滾動條

### 未關項

無。
