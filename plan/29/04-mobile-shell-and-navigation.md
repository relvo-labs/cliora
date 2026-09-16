# 04 — 行動 App Shell 與導覽（`MS-01`～`MS-06`）

對應 `02-rollout-and-verification.md` 的 **M1 shell writer** 寫入集。
依賴：`MS-D-01`、`MS-D-03`、`MS-D-08`、`MS-D-09` 核准。
本階段**不改** store、composable 的傳輸行為、API、或任何 wire 契約。

## 0. 現況盤點（靜態閱讀，尚未瀏覽器重現）

盤點是為了不重做已經做對的部分。`AppLayout.vue` 已經有相當完整的窄視窗處理：

| 項目 | 現況 | 位置 | 本期 |
|---|---|---|---|
| shell 擁有視窗高度 | `height: 100vh` → `100dvh` | `AppLayout.vue:172-176` | **不動原則**，只加鍵盤維度 |
| 三段版面模式 | `isNarrow < 768`、`collapsed < 1440` | `AppLayout.vue:60-66` | 改用 `useBreakpoint` |
| 窄視窗導覽 | 漢堡鈕 ＋ `position: fixed; inset: 0` 覆蓋抽屜、焦點返回 | `AppLayout.vue:95-108, 131-147` | 沿用，只補安全區與排序 |
| main padding | 1439／767 兩段 | `AppLayout.vue:216-226` | 沿用 |
| 觸控目標（按鈕） | `::after` 把命中區墊到 44px | `UiButton.vue:75-86`、`UiIconButton.vue:72-73` | 已達標，不動 |
| 工作台標頭壓縮 | 1024–1439 收成一列＋揭露 | `SessionHeader.vue:48, 123, 154` | 延伸至 `<768` |
| StatusBar 窄視窗 | `<768` 隱藏偏好控制與鍵名 | `StatusBar.vue:132-141` | 重新檢視（見 `MS-06`） |

四項確認的缺口：

1. **安全區**：全 repository 無任何 `env(safe-area-inset-*)`（已 grep 確認），而且**更上游的那一步也沒做**——
   `frontend/index.html:5` 的 viewport meta 是 `width=device-width,initial-scale=1.0`，**沒有 `viewport-fit=cover`**。
   缺了它，iOS 上所有 `env(safe-area-inset-*)` 一律解析為 `0`：先寫 CSS 再發現沒效果，是這一格最容易走的冤枉路。
2. **鍵盤高度**：全 repository 無任何 `visualViewport`（已 grep 確認）。軟體鍵盤升起時 `100dvh` **不會縮小**，終端輸入行與檔案搜尋框會被鍵盤蓋住。
3. **輸入類觸控目標**：`UiField.vue:104` 與 `SessionsView.vue:266, 275` 的 `input`／`select` 用 `--density-control`（36px）且**沒有** `UiButton` 那個 `::after` 墊高。按鈕達標、輸入框不達標。
4. **Sessions 清單是五欄表格**：`SessionsView.vue:177-209` 用 `UiDataTable`，`th` 為 `white-space: nowrap`，橫向捲動發生在 `.scroll` 容器內（`UiDataTable.vue` `.scroll { overflow: auto }`）。頁面不會溢位，但 390px 下實際可讀的只有第一欄——這不是溢位缺陷，是**密度不適用**。

## MS-01 斷點單一來源與行動尺度覆寫

依賴 `MS-D-03`。這是本期第一張票，其餘每張都引用它。

新增 `frontend/src/composables/useBreakpoint.ts`：

```text
useBreakpoint() -> {
  isNarrow    // matchMedia("(max-width: 767px)")
  isTablet    // 768-1023
  isCompact   // 1024-1439
  isWide      // >= 1440
}
```

- 以 `matchMedia` ＋ `change` 事件，**不是** `window.innerWidth` ＋ `resize`。現行兩處都用 resize（`AppLayout.vue:53-58`、`SessionWorkspaceView.vue:302-308`），那會在每一幀重算；`matchMedia` 只在跨越界限時觸發一次，而跨越界限正是唯一會改變版面的事件。
- 監聽器在 `onScopeDispose` 移除。
- SSR／無 `matchMedia` 時回退到 `isWide`（與現行 `typeof window === "undefined" ? 1440` 的假設一致）。
- `AppLayout.vue:53-66` 與 `SessionWorkspaceView.vue:302-318` 改為使用它。**同一次提交**，否則兩套並存比原本的三處字面值更糟。

`theme/tokens.css` 末端新增一個**只含尺度、不含任何顏色**的區塊：

```css
/* 行動尺度。顏色不在這裡 —— 顏色走 pocket 主題（MS-D-04）。 */
@media (max-width: 767px) {
  :root {
    --density-control: 44px;   /* 36px -> 觸控下限，一次修好所有 input/select */
    --density-row: 52px;
    --layout-workhead: var(--layout-workhead-compact);
  }
}
```

這一塊把缺口 3 一次補完：八個 `--density-control` 使用點不需各自改。
`theme.contract.test.ts:114` 的「theme 區塊不得重定義尺度」只檢查 `:root[data-theme="…"]`，本區塊不在其列；
但為了不讓它變成偷渡顏色的後門，`MS-22` 新增一條測試：**這個 media 區塊內不得出現任何 `COLOR_TOKENS` 成員**。

驗收：`MSP-F-009` 的八個尺寸下，所有可見 `input`／`select`／`button` 的 bounding box ≥ 44×44。

## MS-02 視窗高度：安全區與軟體鍵盤

依賴 `MS-01`、`MS-D-09`。寫入 `AppLayout.vue` 與 `tokens.css`。

`.shell` 仍是唯一的高度擁有者（plan/09 D1）。加入兩個維度：

```css
.shell {
  height: 100vh;
  height: 100dvh;
  height: var(--viewport-usable-height, 100dvh);   /* 新增，第三層回退 */
  padding-top: env(safe-area-inset-top, 0px);
  padding-left: env(safe-area-inset-left, 0px);
  padding-right: env(safe-area-inset-right, 0px);
  /* bottom 不在這裡，見下 */
}
```

- **先改 `frontend/index.html:5`**：viewport meta 加上 `viewport-fit=cover`。沒有這一步，下面整段 CSS 在 iOS 上等於沒寫。
  這是本期唯一一處改 `index.html`，且它同時影響桌面——桌面沒有安全區，`env()` 解析為 0，實際無變化，但仍列入 `MS-21` 的桌面回歸確認項。
- `--viewport-usable-height` 由 `AppLayout.vue` 在 `visualViewport` 的 `resize`／`scroll` 寫到 `document.documentElement.style`；**非持久化**，不進任何 store 或 storage。
- 無 `window.visualViewport` 時**完全不設**該變數，讓 `var()` 回退到 `100dvh`。不做 polyfill。
- **底部安全區不得與 `visualViewport` 重複相減**：`visualViewport.height` 已排除鍵盤但未必排除 home indicator，實際疊加行為因平台而異且**目前沒有量測值**。因此底部內距由**最內層那個真正貼底的元素**（終端輸入輔助列、preview 工具列）各自宣告 `padding-bottom: env(safe-area-inset-bottom, 0px)`，shell 不加。量測項列為 `MS-OM-03`。
- 監聽器在 `onBeforeUnmount` 移除；`MS-22` 的單元測試斷言解除綁定。

**拒絕**：`position: fixed` 的輸入列或工具列，除非 `MSP-R-010` 的真機證據顯示它們確實停留在鍵盤之上。在那之前一律用一般流版面，被鍵盤推上去是可接受的，被鍵盤蓋住不是。

## MS-03 行動主導覽

依賴 `MS-01`、`MS-D-01`。寫入 `PrimaryNav.vue`、`AppLayout.vue`。

- 導覽項排序調整，Sessions 為行動端第一項；`/` 的 redirect **不動**（`MS-D-01`）。
- 抽屜面板加入 `padding-top: env(safe-area-inset-top)`，並在面板內可捲動（`overflow-y: auto; overscroll-behavior: contain`）——現行 `inset: 0` 面板在小螢幕加上安全區後，七個導覽項可能超出可視高度。
- 抽屜開啟時鎖住背景捲動（`overscroll-behavior`，**不是** `position: fixed` on body：後者會丟失捲動位置，而 `AppLayout` 的 `main` 是全站唯一捲動容器）。
- 焦點陷阱與 Escape 返回：沿用 `useFocusTrap`（`AppLayout.vue:73` 已註明與檔案抽屜共用同一個 composable），不新增第二套。
- 收合狀態（`preferences.navCollapsed`）在 `isNarrow` 下不適用也不寫入——窄視窗沒有 rail 可收合。

## MS-04 Sessions 清單的行動形態

依賴 `MS-01`。寫入 `SessionsView.vue`（必要時 `UiDataTable.vue` 增加一個 slot，不改其預設行為）。

`<768px` 時同一份 `filtered` 資料改以卡片清單呈現，**不是**把表格橫捲：

```text
┌─────────────────────────────────────┐
│ <session name>            [status]  │  ← 名稱為主要可點區，整張卡片可點
│ <workspace 相對路徑，可截斷>          │
│ node · runtime · 最近活動            │  ← 次要行，次要文字色
└─────────────────────────────────────┘
```

- 一列即一個連結型控制，命中區 ≥ 44px（`--density-row` 在行動為 52px，見 `MS-01`）。
- 欄位**不減少**：name／workspace／node／runtime／status／last_activity 全部保留（addendum §2「retain server ids/states」）。壓縮的是版面不是資訊。
- 排序只能沿用既有伺服器／清單屬性，**不得發明活動度排名**（addendum §1）。
- 空清單、無搜尋結果兩種狀態維持各自的 `UiEmptyState`（現行 `:183-195` 已分開，保持）。
- 篩選列（搜尋框 ＋ runtime select）在行動改為上下兩列全寬；高度由 `MS-01` 的 `--density-control: 44px` 自動達標。
- 表格語意：卡片清單用 `<ul>`／`<li>`，不是視覺上偽裝成表格的 div。桌面 `≥768` 維持 `UiDataTable` 原狀，**桌面 DOM 不變**。

## MS-05 1024–1100px 檔案欄缺陷

依賴 `MS-D-08`。寫入 `SessionWorkspaceView.vue`。

1. **先重現**：在 390／768／1000／1023／1024／1100／1101 七個寬度，記錄 `.workspace-rail` 的 computed `display` 與抽屜鈕是否存在，存成證據。
2. 確認後刪除 `SessionWorkspaceView.vue:1298-1304` 的整個 `@media (max-width: 1100px)` 區塊，並把 `filesAreDrawer` 改用 `MS-01` 的 `isNarrow || isTablet`（即 `< 1024`，與現行值相同，但來源變成單一）。
3. 驗收：七個寬度下，**檔案欄要嘛佔位、要嘛有一個可聚焦的開啟控制**，沒有第三種狀態。

若重現結果顯示現況其實可用（例如另有規則覆蓋），則不改碼，把重現證據記入 `09-implementation-status.md` 並關閉 `MS-D-08`。

## MS-06 StatusBar 與工作台標頭的行動壓縮

依賴 `MS-01`。寫入 `SessionHeader.vue`、`StatusBar.vue`。

- `SessionHeader.vue:48` 的 `compact` 目前是 1024–1439。改為 `< 1440` 全段，使 `<768` 也走同一條單列＋揭露路徑，而不是落回未壓縮的多列版面。
- **posture 不得只存在於揭露之後**：`sandboxBypassed`／`privilegedNode`（`:143-149`）在壓縮態必須仍然直接可見，可以縮短字樣但不能收進 `detailsOpen`。addendum §5 明文要求「打字前可見」。這是 `MS-06` 唯一的硬性條件。
- `StatusBar.vue:132-141` 現行在 `<768` 隱藏 `.group.end` 與 `.key`。三個狀態（session 狀態／瀏覽器連線／控制權）**必須保留**，理由同上：它們是 addendum §1 要求的四項可見狀態之三。重新檢視隱藏範圍，只允許隱藏偏好控制與鍵名標籤，不允許隱藏狀態值本身。
- 行動端 session id 以安全縮寫呈現，且完整 id 可取得（長按複製或揭露內），符合 addendum §1。

## 寫入集與不得跨越的界線

| 票 | 檔案 |
|---|---|
| MS-01 | `composables/useBreakpoint.ts`（新）、`theme/tokens.css`、`components/layout/AppLayout.vue`、`views/SessionWorkspaceView.vue`（僅 `viewportWidth`／`filesAreDrawer` 兩處來源置換） |
| MS-02 | `frontend/index.html`、`components/layout/AppLayout.vue`、`theme/tokens.css` |
| MS-03 | `components/layout/PrimaryNav.vue`、`components/layout/AppLayout.vue` |
| MS-04 | `views/SessionsView.vue`、`components/ui/UiDataTable.vue`（僅加 slot） |
| MS-05 | `views/SessionWorkspaceView.vue` |
| MS-06 | `components/session/SessionHeader.vue`、`components/session/StatusBar.vue` |

`MS-01` 與 `MS-05` 都會碰 `SessionWorkspaceView.vue`；**必須依序**，不得並行。
本階段不得碰 `useTerminalSession.ts`、`stores/files.ts`、`theme/themes.ts`、任何 `contracts/` 檔案。
