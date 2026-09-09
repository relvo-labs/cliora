# 06 — 驗證與 Exit（`VR-10`／`VR-11`／`VR-12`）

## 1. 四條新 gate

註冊進 `traceability/gates.json`，`required_for` 至少含 `changed` 與 `nfr`；
腳本放 `scripts/vr/`，由 `.github/workflows/ci.yml` 與 `scripts/vr/evidence.sh`
**兩個呼叫端共用**（與 `scripts/ly/layout-gates.sh` 同樣的理由：重複會漂移，
而漂移時兩邊都還是綠的）。

| Gate | layer | 內容 |
|---|---|---|
| `GATE-VR-NO-LITERAL-COLOR` | static | `frontend/src` 底下（除 `theme/tokens.css`、`theme/themes.ts`）出現 `#hex`、`rgb(`、`rgba(`、`hsl(`、`hsla(` 即失敗。現況 69 處 |
| `GATE-VR-NO-LEGACY-TOKEN` | static | 十三個舊 token 名（`02-…md` §11 末）出現即失敗 |
| `GATE-VR-NO-GLYPH-ICON` | static | 七個文字符號（`◫ ◈ ▣ ▷ ◉ ☰ ⇄`）出現在 `frontend/src` 即失敗；同時檢查 `public/theme-boot.js` **≤ 12 行且不含 `import`／`fetch`／`eval`** |
| `GATE-VR-THEME-CONTRACT` | unit | `vitest run src/theme` —— 三條測試：token 對齊、每主題完整（`toEqual`）、對比清單 |

**這四條擋得住什麼、擋不住什麼**（要寫進 gate 腳本的檔頭，與 `layout-gates.sh` 一致）：
它們是純文字與純算術檢查，看不見任何實際渲染。
「用了 token 但用錯 token」「主題切換時終端被重建」「1024px 下抽屜打不開」
三種錯誤它們一個都抓不到——那些只有 §2 的瀏覽器量測抓得到。

## 2. 量測式 E2E

加在 `frontend/tests/e2e/`。`plan/09` 的教訓：**綠燈不等於版面正確**，
而 jsdom 沒有 layout、也沒有 computed color。

### 2.1 兩款主題各跑一次的既有測試

`session.spec.ts` 現有的兩條版面測試（水平溢出、垂直列數）改成
以 `test.describe.each(["graphite", "porcelain"])` 各跑一次。
主題以 `page.addInitScript` 寫進 `localStorage` 再導航，
這樣走的是 `theme-boot.js` 的真實路徑。

### 2.2 終端列數（`plan/09` 閘門的延伸）

1440×900、兩款主題，斷言：

- `.xterm-screen` 高度 ≥ CLI 面板高度的 90%；
- `terminal.rows >= 30`；
- 切到預覽再切回來，`rows` 不變。

**餘裕只有 2 列**（`00-…md` §4），所以這條測試的失敗訊息要印出
實際列數、面板高度與字格高度三個數字，否則下一個人只會看到「29 < 30」。

### 2.3 主題切換不中斷（本期最重要的一條）

```
1. 開一個 Session，等 FAKECLI_READY 出現
2. 往終端輸入一段不按 Enter 的文字
3. 往上捲動到非底部
4. 記下：buffer 最後 5 行、viewportY、terminal.status、terminal.role
5. 切主題
6. 斷言四者全部不變，且 xterm 的 background 已經換成新主題的值
7. 斷言 WebSocket 沒有重連（以 status 沒有經過 "connecting" 判定）
```

第 7 步是重點：切主題若走了 `new Terminal()`，`status` 會閃過重連，
而畫面上可能看不出來（重連很快）。

### 2.4 對比與焦點（瀏覽器實測，補齊算術檢查看不到的部分）

- **半透明疊加**：`--terminal-selection` 疊在 `--terminal-background` 上、
  `--surface-scrim` 疊在畫布上，用 `getComputedStyle` 取實際渲染色再算對比。
  `theme.contrast.test.ts` 算不了這兩個（`02-…md` §6 開頭已聲明）。
- **焦點環**：對工作台每一個可聚焦元素 `focus()` 後截圖，
  斷言 `outline-width` 非 0 且 `outline-color` 等於 `--focus-ring`。
- **狀態不只用顏色**：對每一個 `StatusBadge` 斷言它的 `textContent` 非空。

### 2.5 響應式與抽屜

三個斷點 × 兩款主題：

- `document.documentElement.scrollWidth <= clientWidth`；
- 1024×768：導覽是 64px 且每一項有 `aria-label`；
- 1000×800：檔案樹隱藏 **且開啟鈕可觸及**，按下後樹可見，Esc 後焦點回到開啟鈕
  （`03-…md` §5 說明這一條為什麼是新增而不是修改）；
- 390×844：主導覽可由選單開啟，主面板單欄。

### 2.6 FOUC

`page.addInitScript` 設 `cliora-theme=porcelain`，在 `domcontentloaded`
與 `load` 各取一次 `<body>` 的 computed background，斷言兩次相同。

## 3. Evidence pack

`scripts/vr/evidence.sh [output-dir]`，預設 `artifacts/vr/local`。
形狀比照 `scripts/ly/evidence.sh`：**每一個 gate 都被執行**、
退出碼記進 `commands.txt`、這個環境給不了的（瀏覽器、完整 stack、線上 Node）
進 `skipped.txt`——**絕不靜默省略，因為安靜漏掉一個 gate 的 pack 讀起來像通過**。

必含：

| 產物 | 內容 |
|---|---|
| `versions.txt` | commit、dirty 檔數、node／npm 版本 |
| `commands.txt` | 每個 gate 的退出碼 |
| `skipped.txt` | 跳過的 leg 與原因 |
| `contrast.txt` | `theme.contrast.test.ts` 的完整輸出（**每一組配對的實測值**，不只 pass/fail） |
| `screens/` | 11 頁 × 2 主題 × 3 斷點，加上 `TokenShowcaseView` 的 2 張 |
| `vr-01-xterm-probe.{md,json}` | `scripts/vr/xterm-geometry-probe.mjs` 的輸出：字級 × 行高 × 兩個幾何的列數與字格高度、以及主題賦值前後的 buffer 狀態 |
| `terminal-rows.txt` | 兩款主題在**真實工作台**上的實際列數、面板高度、字格高度（probe 量的是裸 xterm，這一份量的是整合後的） |
| `ansi.png` | 真實 Claude／Codex 畫面的十六色比對（`VR-01` 第 5 項） |
| `overlap.txt` | `git diff master...v2 --stat -- frontend/src`（`00-…md` §7 最後一列） |

## 4. 驗收矩陣

**2 主題 × 3 斷點 × 6 狀態 = 36 組**，每組一張截圖。

- 主題：Graphite、Porcelain
- 斷點：1440×900、1024×768、390×844
- 狀態：正常、空、錯誤、唯讀、重連、長文字

長文字那一格的固定測試資料（寫進 fixture，不要每次手打）：

```
Session 名稱  80 字元，含中英夾雜與一個 emoji
Workspace     /home/deploy/workspaces/relvo/2026/q3/cliora-frontend-visual-refresh
檔名          測試-檔案-名稱-很長-的-那-一-個-🎨.tsx
Node 名稱     build-node-ap-northeast-1-spot-0007
```

## 5. 縮減範圍的明確記錄

共用規範：「正式選定僅支援部分主題時，縮減矩陣需明確記錄範圍」。本期的縮減是：

| 沒有被驗的 | 為什麼 |
|---|---|
| Midnight／Studio／Industrial 的**任何**畫面 | `00-…md` D2。色值進 `themes.ts` 並通過 token 完整性與對比測試，但**沒有**瀏覽器驗收、**沒有**進切換器 |
| 這三款的版型差異（64px 精簡導覽、側欄摘要、水平導覽） | 不實作 |
| Studio 的 `accent.strong #984D2E` | 算術上通過（4.83:1），但沒有在瀏覽器裡看過 |
| 緊湊密度 | `00-…md` D3 沒有做 |
| Command Palette | `style.md §23` 列了它，從未實作，本期也不做 |

**這張表要進 release note**，否則「支援五種主題」會被讀成「五種都驗過了」。

## 6. 安全審查七題（`docs/security-review-p28.md`）

1. **有沒有任何 UI 變更放寬了授權？** 逐一核對三個 `hasPermission`
   （`AppLayout.vue:24-33`）、`capabilities.*` 的五個判斷、`canUploadImages`／
   `canUploadFiles` 的雙條件。答案必須是「顯示條件一字未改」，並附 diff 證據。
2. **`public/theme-boot.js` 是否在 CSP 之內？** 它是 `'self'` 的外部檔，
   不是內嵌 script；不引入任何新的 script／connect／font 來源。
   附 `curl -I` 的 CSP 標頭與瀏覽器 console 無 CSP violation 的截圖。
3. **`localStorage` 存了什麼？** 主題 id、導覽收合、終端字級、檔案欄寬度——
   四個都是 UI 偏好，**沒有任何識別資訊、token 或路徑**。
   路徑那一項要特別確認：檔案欄寬度是數字，不是最後開啟的目錄。
4. **有沒有新的外部請求？** 沒有。ADR 0016 的「dist 不含 CDN 參照」build-time grep
   仍然綠燈；本期**刪掉**一個從未生效的字型名字（`useTerminalSession.ts:216`），
   不新增任何字型檔。
5. **顯示的路徑會不會洩漏 Node 絕對路徑？** SessionHeader 的路徑中段省略與
   複製功能是本期新增的顯示面。工作區檔案的相對路徑規則（P3）不變；
   `session.workspace` 本來就已經顯示在標頭（`:478-480`），本期沒有擴大它。
6. **錯誤訊息會不會因為新元件而洩漏伺服器細節？** `ErrorNotice` 的四段式
   （安全訊息／原因／下一步／request id）邏輯一行不動；
   新增的 `InlineNotice` 與 `Toast` **不得**接受 `unknown` 型別的錯誤物件，
   只吃字串，避免有人把 exception 直接丟進去。
7. **移除 `naive-ui` 對供應鏈的影響？** 少一個 dependency（含其傳遞相依）。
   Lucide 已在使用，圖示以 Vue 元件形式打包（不是 inline `<svg>` 字串，
   也不需要 `img-src`），CSP 不受影響。附 `npm ls --omit=dev` 的前後對照。

## 7. Exit 條件

全部達成才算本期完成：

1. `make check` 綠燈；`scripts/ly/layout-gates.sh all` 綠燈**且該腳本未被修改**。
2. 四條新 gate 綠燈並已註冊進 `traceability/gates.json`。
3. `make traceability` 綠燈；`NFR-006` 八條 AC ＋ 三條既有需求的新 AC 各有四類 primary link。
4. `00-…md` §1 的十項判準各有可貼上的輸出，收在 `artifacts/vr/local`。
5. 36 組驗收畫面齊備；§5 的縮減範圍已寫進 release note。
6. `docs/security-review-p28.md` 七題有答案與證據。
7. `research/style.md` 七處修訂已合併；五份設計文件四處修訂已合併；
   ADR 0027 狀態為 accepted。
8. `.agent/skills` 三份已更新，`vue-naive-ui-workflow` 已改名，索引與計數已修正。
9. `git diff master...v2 --stat -- frontend/src` 的重疊清單已附在 exit 報告，
   並由人判斷 V2 那條線的重放成本（**這是報告，不是閘門**——
   合併 `v2` 一律由人決定）。
10. release note 第一段講清楚三件事：**預設主題變成深色**、
    **終端字級與行高改變（列數會變少）**、**只有兩款主題經過驗收**。

第 10 項的前兩件是使用者一開啟就會察覺的變化，放在附註等於沒說。
