# 04 — 驗證與退出（LY-06、LY-07、LY-08）

---

## LY-06 — 量測式 E2E 與三條 CI 回歸鎖

### 為什麼這張 ticket 不能省

三處面板高度塌陷在 `make check`、330 個前端單元測試、整條 browser E2E 全綠的情況下存活至今。原因很具體：

- jsdom 沒有 layout，`clientHeight` 永遠是 0（`useTerminalSession.test.ts:116-117` 必須用 `Object.defineProperty` 手動塞值才能測到尺寸相關邏輯）。
- plan/08 補的版面測試 `session.spec.ts:253-334` **只量水平方向**（`:309-321`）。垂直方向沒有任何斷言。

所以本期的修正如果沒有一個「會因為高度塌陷而變紅」的測試，下一次重構就會原地復發，而且同樣不會有人發現。

### 新增測試 1：垂直幾何（Playwright）

放在 `frontend/tests/e2e/session.spec.ts`，沿用該檔既有的 `signIn()`／`openDialogAndCountNodes()` 與 `E2E_FULL_STACK` 閘門（`:12-14`、`:60-63`）。名稱：

```
layout: the CLI terminal fills the centre pane and the page does not scroll
```

量測方式（一次 `page.evaluate` 取回所有數字，失敗訊息才有診斷價值）：

```ts
const geometry = await page.evaluate(() => {
  const pane = document.querySelector("#panel-cli") as HTMLElement;
  const host = pane.querySelector<HTMLElement>('[aria-label="Interactive CLI terminal"]')!;
  const screen = pane.querySelector<HTMLElement>(".xterm-screen")!;
  const rows = pane.querySelectorAll(".xterm-rows > div").length;
  const root = document.documentElement;
  const main = document.querySelector<HTMLElement>("main[data-fill]")!;
  return {
    paneHeight: pane.clientHeight,
    hostHeight: host.clientHeight,
    screenHeight: Math.round(screen.getBoundingClientRect().height),
    rows,
    pageOverflowY: root.scrollHeight - root.clientHeight,
    mainOverflowY: main.scrollHeight - main.clientHeight,
    asideWidth: document.querySelector<HTMLElement>("aside")!.clientWidth,
    centreWidth: pane.clientWidth,
  };
});
```

斷言（下界取自 `00-…md` §4 的推算，留了足夠餘裕給字型度量差異）：

| # | 斷言 | 擋住什麼 |
|---|---|---|
| 1 | `hostHeight >= paneHeight - 4` | host 沒有拿到面板的剩餘空間（CLI 面板落在 `auto` 列的直接症狀） |
| 2 | `screenHeight >= paneHeight * 0.9` | host 高度對了但 xterm 沒有重新 fit（只有 24 列被畫出來） |
| 3 | `rows >= 30`（1440×900） | 一個「比例正確但整體很小」的版面仍然不可接受。24 列是現況，30 是明確高於它的下界，43 是推算值 |
| 4 | `pageOverflowY <= 1` | 兩套高度公式（現況 16px 滾動） |
| 5 | `mainOverflowY <= 1` | fill 模式的 `overflow: hidden` 底下仍有內容溢出（`LY-02`） |
| 6 | `asideWidth <= 220` | sidebar 沒有真的變窄（`LY-05`） |
| 7 | `centreWidth >= 860` | 中央區沒有真的變寬（`LY-05`；推算 888） |
| 8 | 切到 `[filename]` 再切回 `CLI` 後重新量測，`rows` 與步驟 3 相同 | 隱藏期間被錯誤 fit（plan/08 已付代價的正確性條件，`research/tech.md:1728-1740`），或切回來沒有重新量測 |
| 9 | 切回後 `.banner.gap` 不存在 | 切 tab 造成輸出不連續（gap）——高度變更不該影響串流 |

第二個尺寸 1000×800（`1100px` 斷點內、單欄）重複斷言 1、2、4、5，並把 3 的下界放寬為 `rows >= 20`（可用高度本來就較小）。

**允差為什麼是 4px / 90% 而不是精確值**：`.xterm-screen` 的高度是 `列數 × 儲存格高度`，而儲存格高度取決於實際字型度量（三種瀏覽器不同），永遠會在容器底部留下不足一列的餘量。要求精確相等會做出一個在 CI 上隨字型更新而閃紅的測試。

### 新增測試 2：TERMINAL tab 的開場尺寸（Playwright）

擴充既有的 `system terminal: TERMINAL tab opens a real shell…`（`session.spec.ts:364-500` 一帶）：第一次量到的 shell 列數就要 ≥ 30，不是先 24 再變大。這是 `LY-04` 的驗收點。

實作提醒：斷言要在 `#panel-terminal .xterm-rows` 出現後**立即**量（該處已有 `:494` 的等待），而不是 `waitForTimeout` 之後——等待會把「先 24 再 resize」等成綠燈。

### 新增：三條 CI gate

三條 gate 的**內容**放在 `scripts/ly/layout-gates.sh`（可帶 `height`／`panels`／`sidebar`／`all`），由 `.github/workflows/ci.yml` 的 `frontend` job（`:35-46`）與 `scripts/ly/evidence.sh` **各自呼叫同一個腳本**。

- 放在 `ci.yml` 而不是新開 phase workflow：這三條是**永久不變式**，不是這一期的驗收項；掛在 phase workflow 上會隨那個 phase 一起被遺忘（`wt.yml` 的 grep gate 是 phase-specific 的合理案例，這三條不是）。
- 抽成腳本而不是在 workflow 內就地寫：evidence pack 也要跑同一套，兩處各寫一份必然漂移，而**漂移時兩邊都還是綠的**——這正是本期在修的失敗模式。

| gate | 判定方式 | 訊息 |
|---|---|---|
| 1. 高度只有一個來源 | `grep -rnE '^[[:space:]]*(min-\|max-)?height:[^;]*(100vh\|100dvh)' frontend/src` 扣掉 `AppLayout.vue` 與 `LoginView.vue` 後必須為空。**比對宣告而非任意出現**，否則註解裡提到 `100vh` 就會誤判 | `a view re-derived the page height (plan/09 D1)` |
| 2. 面板不得用列樣板決定高度 | **正面斷言**：抓出 `.terminal-pane`／`.preview`／`.tree-panel` 三個規則區塊（awk，從 `selector {` 讀到 `}`），每個都必須含 `display: flex` 且不得含 `grid-template-rows` | `… must be a flex column (plan/09 D3)` |
| 3. sidebar 寬度規格與實作一致 | 從 `tokens.css` 取 `--layout-sidebar`，與 `research/style.md` §22 的 `sidebar:` 比對，並要求 §9 的 `Sidebar` 後兩行內出現同一個 `NNNpx` | `tokens.css says Npx, research/style.md §22 says M (plan/09 D5)` |

gate 2 刻意用「規則區塊 + 正面斷言」而不是「整檔 grep `grid-template-rows` + 行內容允許清單」：`grid-template-rows` 在同一個檔案的別處是正確用法（`.center` 的 `auto minmax(0,1fr)`），而行內容允許清單擋不住「`.terminal-pane` 換一個新的列樣板」。正面斷言擋得住，而且失敗訊息直接指向該用的寫法。

### 產物清單

| 檔案 | 動作 |
|---|---|
| `frontend/tests/e2e/session.spec.ts` | 新增 1 個 test；擴充既有 system terminal test 的開場尺寸斷言 |
| `scripts/ly/layout-gates.sh` | **新增**：三條 gate 的實作，供 `ci.yml` 與 evidence pack 共用 |
| `.github/workflows/ci.yml` | frontend job 新增三個 step，各呼叫 `scripts/ly/layout-gates.sh <check>` |

E2E 不需要新的 workflow：`wt.yml` 的 `browser-e2e` job 跑的是 `npx playwright test`（`:165`，無 `--grep` 過濾），新測試自動被納入三個瀏覽器。

### 測試

本 ticket 的產物就是測試。自我驗證方式：**先 revert `LY-03`，確認新測試變紅**（斷言 1、2、3 皆紅），再套回來確認變綠。這一步必須實際做過並記進 `05-implementation-status.md`——一個從未紅過的守門測試沒有證據力。

### 證據

- `cd frontend && npx playwright test --project=chromium --project=firefox`（在 `scripts/e2e/run-stack.sh` 起的全棧下）
- 上述「revert 後變紅」的輸出片段
- WebKit：CI-only（安裝系統函式庫需 root，沿用 plan/08 的處置）

### 未關項

- WebKit 在本機不可跑，標為 CI-gated。

---

## LY-07 — PRD 新增 AC、traceability 註冊與影響分析

### 為什麼要新增 AC

`research/tech.md:1711-1717` 有「擇一佔滿」，但那是技術設計的敘述，`traceability/` 裡沒有任何 criterion 對應到「面板必須填滿可用高度」。結果就是：這件事壞掉時，沒有任何 requirement 會變成未覆蓋，也沒有任何 gate 會擋。

本期補**兩條可量測的 AC**，掛在既有的 `FR-TERM-001 Terminal 顯示`（`research/prd.md:929-956`，`traceability/requirements.json` 內已有 AC-01…AC-12）之下：

| 新 AC | anchor | 條文（寫進 `research/prd.md` §8.7 FR-TERM-001 的 AC 清單末端） |
|---|---|---|
| `FR-TERM-001.AC-13` | `fr-term-001-ac-13` | Terminal 面板必須填滿中央工作區的可用高度（量測基準：終端機畫面高度不低於面板可用高度的 90%）。 |
| `FR-TERM-001.AC-14` | `fr-term-001-ac-14` | Session 工作區不得因版面高度計算而產生整頁滾動。 |

兩條分開，因為它們會被不同的原因弄壞：AC-13 壞在面板內部的高度分配，AC-14 壞在頁面層的高度來源。合成一條會讓覆蓋率報告無法指出是哪一半失效。

### requirements.json

在 `FR-TERM-001` 的 `criteria` 陣列末端加兩筆，格式與既有項目相同：

```json
{ "id": "FR-TERM-001.AC-13", "source_anchor": "fr-term-001-ac-13",
  "verification_profile": "automated", "risk": "medium" }
```

`risk: medium` 與同族其他 criterion 一致：它不是安全性質，但直接決定產品是否可用。

### links.json

每條 criterion 四類 primary link（`criticality: must` 的 requirement 少任一類就會 blocking）：

| type | target | 說明 |
|---|---|---|
| `planned_by` | `plan` → `plan/09/02-panel-fill.md`（AC-13）／`plan/09/01-app-shell-and-height.md`（AC-14） | 各自的交付工作包 |
| `specified_by` | `source` → `research/tech.md` | **沿用 FR-TERM-001 家族既有慣例**（現有 AC-01…AC-12 的 specified_by 全部指向 `research/tech.md`）。條文本身在 prd.md，anchor 存在性由 `make traceability-validate` 另外檢查 |
| `implemented_by` | `code` → `frontend/src/views/SessionWorkspaceView.vue`（AC-13）／`frontend/src/components/layout/AppLayout.vue`（AC-14） | 主要實作面 |
| `verified_by` | `playwright` → `frontend/tests/e2e/session.spec.ts#layout: the CLI terminal fills the centre pane and the page does not scroll`，`gate_id: GATE-BROWSER-E2E`，`role: primary` | `LY-06` 的量測測試。selector 必須與測試名稱逐字相同，所以 **`LY-07` 必須與 `LY-06` 同一個 PR 或緊接其後**（plan/08 WT-09 踩過這一點） |

id 命名沿用 `LNK-FR-TERM-001-AC-13-PLANNED-BY` 這一組形式。

### 必須一併更新的 pinned 數字

`scripts/traceability/tests/test_traceability.py:88-93` 把覆蓋率摘要釘死（「every one of these numbers moving is a reviewable event」）。新增 2 條 automated criterion 後：

- `total`: 379 → **381**
- `verifiable`: 248 → **250**
- `covered_by_parent`／`needs_rewrite`／`blocking` 不變（131 / 0 / 0）

並在該處註解補一行 `2026-xx-xx: +2 for FR-TERM-001.AC-13/AC-14（plan/09 版面高度）`，格式沿用上一行 plan/08 的寫法。**實際數字以 `make traceability` 的輸出為準**，不要照抄本文件；如果跑出來不是 381/250，先弄清原因再改，不要調整測試去迎合。

### 文件同步

| 文件 | 改什麼 |
|---|---|
| `research/prd.md` §8.7 | 新增 AC-13／AC-14 兩個 anchor 與條文 |
| `research/tech.md` §16.1 | `LY-02` 與 `LY-04` 各補一條實作限制（見 `01-…md`、`02-…md`） |
| `research/style.md` §9／§22 | `LY-05` 的數字同步 |
| `docs/traceability/coverage.md` | 由 `make traceability` 重新產生，不手改 |
| `docs/ly-report.md` | **新增**，`LY-08` 產出 |

### 證據

- `make traceability-validate`（PRD anchor 全部存在）
- `make traceability`（覆蓋率報告重新產生，0 blocking）
- `scripts/trace coverage --scope all --strict` 退出 0

### 未關項

無。

---

## LY-08 — 驗收、evidence 與 exit gate

### Evidence pack

新增 `scripts/ly/evidence.sh`，直接沿用 `scripts/wt/evidence.sh` 的結構與規則（`:1-50`）：每個 gate **實際執行**並把退出碼寫進 `commands.txt`，環境不足的寫進 `skipped.txt`，**絕不靜默省略**。輸出預設 `artifacts/ly/local`。

| # | gate | 指令 | 缺什麼會 skip |
|---|---|---|---|
| 1 | 前端格式 | `npm run format:check` | — |
| 2 | 前端 lint | `npm run lint` | — |
| 3 | 型別 | `npm run typecheck` | — |
| 4 | 單元測試 | `npm run test:unit -- --run` | — |
| 5 | 建置 | `npm run build` | — |
| 6 | gate 1（高度來源） | `scripts/ly/layout-gates.sh height` | — |
| 7 | gate 2（面板列樣板） | `scripts/ly/layout-gates.sh panels` | — |
| 8 | gate 3（sidebar 一致性） | `scripts/ly/layout-gates.sh sidebar` | — |
| 9 | traceability | `make traceability` | `uv`（`scripts/trace` 透過它執行）、PostgreSQL |
| 10 | 版面量測 E2E（chromium） | `run-stack.sh` + `playwright test --project=chromium --grep layout` | PostgreSQL／tmux／瀏覽器／online node |
| 11 | 版面量測 E2E（firefox） | 同上 `--project=firefox` | 同上 |
| 12 | 版面量測 E2E（webkit） | 同上 `--project=webkit` | 系統函式庫需 root → **本機必 skip，CI-only** |

### 驗收清單（人工，全部要有截圖）

1. `/sessions/:id` 在 1440×900：CLI 填滿、無整頁滾動、sidebar 208px。
2. 開一個檔案 → 預覽填滿；**特意選一個不會顯示 meta 列的狀態**（raw 或錯誤），確認 Monaco 仍填滿（`LY-03` 對 `PreviewPane` 的修正）。
3. TERMINAL tab：開場列數就正確，提示列與狀態列都在，終端機仍填滿剩餘空間。
4. 視窗縮到 1000×800：單欄、檔案樹隱藏、CLI 仍填滿。
5. `/dashboard`、`/nodes`、`/nodes/:id`、`/sessions`、`/audit`、`/enrollment` 六頁：內容可滾完、header／sidebar 不隨內容滾走（`LY-01` 的滾動容器變更）。
6. 900px 以下：sidebar 變 64px 圖示欄、main 沒有被舊的 `margin-left` 推歪。

### 退出條件

| # | 條件 | 判定 |
|---|---|---|
| 1 | `make check` 退出 0 | 指令 |
| 2 | `make traceability` 全綠、`scripts/trace coverage --scope all --strict` 退出 0 | 指令 |
| 3 | `LY-06` 九項斷言在 1440×900 通過、四項在 1000×800 通過 | E2E 輸出 |
| 4 | plan/08 既有的無水平溢位斷言仍通過 | E2E 輸出 |
| 5 | `LY-06` 的「revert `LY-03` 後測試變紅」已實際驗證過 | 貼輸出片段 |
| 6 | 三條 grep gate 在 CI 上實跑通過 | workflow run |
| 7 | 六頁滾動行為人工驗證完成 | 截圖 |
| 8 | `05-implementation-status.md` 記錄的是**量測值**，且與 `00-…md` §4 的推算值一併列出（推算錯了要說明錯在哪） | 文件 |
| 9 | `docs/ly-report.md` 完成 | 文件 |

第 8 項不是形式要求：本目錄所有數字都是從 CSS 推算出來的，如果實測與推算差很多，表示對版面的理解仍有缺口，那個缺口比數字本身重要。

### 未關項

- WebKit 版面量測：CI-only。
