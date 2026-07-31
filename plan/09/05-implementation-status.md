# 05 — 實作進度與證據

本檔隨實作更新；每一列的「證據」欄只填**實際跑過**的指令與其輸出位置，不填計畫中的測試。

最後更新 2026-07-31：**LY-01 – LY-08 全部完成**，退出條件 9 項中 8 項關閉，
第 3 項（量測式 E2E 實跑）為 **CI-gated**——本機沒有 Central／PostgreSQL／tmux／
online node，該測試會自行 skip。斷言本身已用量測值證明可區分修正前後（見下方對照表）。

報告見 `docs/ly-report.md`；evidence pack 見 `artifacts/ly/local/summary.md`
（8 executed / 0 failed / 3 skipped）。

## 波次 0：幾何基礎

| Ticket | 標題 | 狀態 | 證據 | 備註 |
|---|---|---|---|---|
| LY-01 | App shell 改視窗高度 grid，`main` 成為唯一滾動容器 | ✅ 完成 | `npm run test:unit -- --run`：`AppLayout.test.ts` 4 例；六路由滾動行為以 Chromium 實測（`/audit` 在 main 內滾 2876px、`/nodes` 1360px，header 固定於 `top: 0`，整頁不滾） | `.shell` 改 `grid-template-columns: sidebar minmax(0,1fr)` + `grid-template-rows: auto minmax(0,1fr)`、`height: 100vh; height: 100dvh`；header／aside 去 `position: fixed`；`@media (max-width:900px)` 改覆寫 grid 欄（860×700 實測：rail 63px、標籤隱藏、main 起點 x=64、無水平溢位）。**header 列用 `auto` 而非寫死 56px**，避免窄視窗換行時壓到 main |
| LY-02 | Session Workspace 改 `fill` 模式，刪除第二套高度公式 | ✅ 完成 | 同上（`AppLayout.test.ts` 含 `data-fill` 兩例）；量測：`mainOverflowY = 0` | `fill` prop → `main[data-fill]`（`overflow: hidden`、`12px 16px`、`grid-template-rows: minmax(0,1fr)`）；`.workspace` 由 `calc(100vh - header - 48px)` 改 `height: 100%`。tech §16.0／§16.1 同步 |
| LY-03 | 四個面板改 flex column 填滿 | ✅ 完成 | 量測：CLI `screen ÷ pane` 由 **0.506 → 0.999**、rows 24 → 49；Preview `body ÷ pane` 0.235 → 0.963 | 純 CSS，未動 template／script。`.terminal-pane`／`.preview`／`.tree-panel` 三處改 flex column；`.terminal-host` 移除 `height: 100%` 改 `flex: 1 1 auto; min-height: 0`；`.shell-notice`／`.shell-status`／`.head`／`.meta` 標 `flex: 0 0 auto`。`.rail` 的 `overflow: auto` 依計畫保留 |

## 波次 1

| Ticket | 標題 | 狀態 | 證據 | 備註 |
|---|---|---|---|---|
| LY-04 | 首次量測與開場尺寸（shell 不再以 24×80 開場） | ✅ 完成 | `useTerminalSession.test.ts` 14 → **18 例**；`SessionWorkspaceView.test.ts` 19 → **21 例** | `proposeSize()`：隱藏容器回 `null`、`<2` 回 `null`、並**夾到 wire 契約的 2–300／2–500**（`contracts/v1/schemas/messages/session-start.schema.json`；原計畫沒寫這一項，實作時發現超寬視窗真的會提出 >500 欄而被 422 拒絕）。`openShellTab()` 先 `await nextTick()` 再量測，量不到才退回 24×80。FitAddon mock 補 `proposeDimensions` |
| LY-05 | sidebar 280→208px、fill 內距、style.md 數字同步 | ✅ 完成 | 量測：rail 279 → 207px、中央面板 792 → **888px**；`scripts/ly/layout-gates.sh sidebar` 通過 | `tokens.css` 208px + `--layout-status` 加註「Status Bar 未實作」；`style.md` §9（Sidebar 208、Inspector 300、新增「高度只有一個來源」與 fill 模式說明）、§12（面板填滿不留空白）、§22 token 區塊 |

## 波次 2：驗證與退出

| Ticket | 標題 | 狀態 | 證據 | 備註 |
|---|---|---|---|---|
| LY-06 | 量測式 E2E 與三條 CI 回歸鎖 | ✅ 完成（E2E 實跑為 CI-gated） | 三條 gate 在本機通過，且**在 revert 後三條全紅**（實際輸出見 `docs/ly-report.md`）；E2E 需全棧 | `session.spec.ts` 新增 `layout: the CLI terminal fills the centre pane and the page does not scroll`（1440×900 九項、1000×800 四項），並在既有 shell 測試補「建立時的 rows/columns ≥ 30／60」。**三條 gate 抽到 `scripts/ly/layout-gates.sh`**（原計畫寫在 `ci.yml` 內；抽出的理由是 evidence pack 也要跑同一套，兩處各寫一份會漂移而且兩邊都還是綠的） |
| LY-07 | PRD AC-13／AC-14 與 traceability 註冊 | ✅ 完成 | `validate --level static`／`selectors` 通過；`coverage --scope all --strict` → `criteria=381 verifiable=250 covered-by-parent=131 needs-rewrite=0 blocking=0`；`pytest scripts/traceability/tests` 32 passed | PRD §8.7 新增兩個 anchor；`requirements.json` 兩個 criterion；`links.json` 8 條 primary link（planned_by／specified_by／implemented_by／verified_by）；pinned 摘要 379/248 → **381/250**（與計畫預測一致）；`docs/traceability/*.md` 重新產生。**selector 已用故意打錯測試名稱驗證會 `selector.unresolved`** |
| LY-08 | 驗收、evidence 與 exit gate | ✅ 完成 | `bash scripts/ly/evidence.sh` → `artifacts/ly/local/summary.md`：8 executed / 0 failed / 3 skipped | `scripts/ly/evidence.sh`（缺 `uv` 時 traceability 記 skip 而非 fail——與缺瀏覽器同一種處理）、`docs/ly-report.md` |

---

## 量測值 vs 推算值

方法：Chromium 149（Playwright）＋ Vite dev server ＋ REST 以 `page.route` 模擬，量
`#panel-cli`。「改前」欄是同一支腳本跑在 `git stash` 過的工作樹上。**這不是本期交付的
那支 E2E 測試**（那支需要全棧、在 CI 跑）；這是為了取得真實數字而寫的一次性 harness。

| 項目 | 推算（改前） | **量測（改前）** | 推算（改後） | **量測（改後）** |
|---|---|---|---|---|
| sidebar 寬 | 280 | **279**（差 1px = 邊框） | 208 | **207** |
| 中央面板寬 @1440 | 792 | **792** ✅ | 888 | **888** ✅ |
| 中央面板高 @900 | ≈712 | **712** ✅ | ≈736 | **736** ✅ |
| CLI host 高 @900 | ≈408 | **360** | ≈736 | **736** |
| CLI 畫面 ÷ 面板 | ≈0.57 | **0.506** | ≈1.0 | **0.999** |
| CLI 列數 @900 | 24 | **24** ✅ | ≈43 | **49** |
| Preview body ÷ 面板 | —（未推算） | **0.235** | — | **0.963** |
| 整頁垂直滾動 | 16px | **16px** ✅ | 0 | **0** ✅ |
| CLI 列數 @1000×800 | —（未推算） | **24** | — | **39** |

差異說明：

1. **列數推算偏低（43 vs 49）**：推算假設 13px 字的儲存格高 17px，實際是 **15px**。
   影響的是 `00-…md` §4 的數字，不影響 `LY-06` 的斷言下界（≥30 仍然遠高於 24）。
2. **改前的 host 高度推算偏高（408 vs 360）**：同一個儲存格高度誤差（24 × 15 = 360）。
3. **「只有一半」是字面意義上的準確**：0.506。回報的用詞不是誇飾。
4. 寬度與整頁滾動兩項推算完全命中，說明對「空間被誰吃掉」的診斷正確；高度那組的誤差
   只在字型度量，不在版面模型。

## 與原計畫的差異（實作時的決定）

| 計畫寫的 | 實際做的 | 理由 |
|---|---|---|
| 三條 grep gate 寫在 `.github/workflows/ci.yml` 內 | 抽成 `scripts/ly/layout-gates.sh`，`ci.yml` 與 `scripts/ly/evidence.sh` 都呼叫它 | 兩處各寫一份必然漂移，而漂移時**兩邊都還是綠的**——這正是本期在修的失敗模式 |
| gate 2 用「允許清單放行 `.center` 那一行」 | 改成**正面斷言**：三個面板的規則區塊必須含 `display: flex` 且不得含 `grid-template-rows` | 行內容允許清單擋不住「`.terminal-pane` 換一個新的列樣板」；正面斷言擋得住，且訊息直接指向要用的寫法 |
| `proposeSize()` 只做 `<2` 下界 | 另加上界 `min(rows,300)`／`min(cols,500)` | 契約 schema 的上界是 300／500，超寬視窗真的會提出更多欄，Central 會回 422 → 終端機開不起來 |
| 六頁滾動行為列為人工驗證＋截圖 | 以 Chromium 自動量測（六路由 + 860×700 斷點） | 「header 有沒有跟著滾」用量測比用眼睛可靠，而且可重跑 |
| — | tech.md 新增 **§16.0 App Shell** | §16.1 的新增限制引用了「高度的唯一來源」，那個規則需要一個自己的位置，不能只存在於 plan/ |
