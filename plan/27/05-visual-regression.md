# 05 — 視覺回歸（`HD-05`）

> 上游：[`research/03/12`](../../research/03/12-migration-and-rollout.md) §6 的
> 「視覺回歸套組擴充（**沿用 `plan/19` baseline 機制**，只補新畫面）」。
> 決策：[D124](./01-decisions-and-governance.md#d124)。

## 1. 那個要沿用的機制不存在

```bash
$ grep -rn "toHaveScreenshot\|toMatchSnapshot" frontend/ --include=*.ts
$ # 空
```

`plan/19` 的「baseline」是這個：

```bash
# scripts/ui/evidence.sh:29
if [ -f artifacts/ui/local/showcase.png ]; then
  printf '%s\n' "[3/9] 三種進行中 ............ MANUAL — 見 artifacts/ui/local/showcase.png"
```

**一疊人工存下來、由人看的截圖。** 那是紀錄，不是回歸——
它抓不到「下一次改版讓這個畫面變了」，因為沒有東西會去比。

而 `plan/26` 的出口條件第 19 項寫的是
「視覺回歸 | `artifacts/px/local/w3/` 逐頁截圖 ＋ w0／w4／w5／w6」——
**同一個機制，同一個性質**。四期下來，這件事還沒有一個會自己紅的形式。

所以 `HD-05` 是**建一個**，而不是補幾張。

## 2. 用 Playwright 內建的，不新增套件

Playwright **1.61.1 已在 devDependencies**，`toHaveScreenshot` 是它內建的。
所以這一項與 [`04`](./04-accessibility.md) 不同——它**不需要新套件**
（[D125](./01-decisions-and-governance.md#d125) 的那一段講的就是這個差別）。

```ts
// frontend/tests/visual/screens.spec.ts —— 形狀
await expect(page).toHaveScreenshot("active-board.png", {
  maxDiffPixelRatio: 0.01,   // 不是 0 —— 見 §4
  animations: "disabled",
  caret: "hide",
  mask: [page.locator("[data-visual-mask]")],  // 時間戳、相對時間
});
```

## 3. 八個畫面

與 [`04`](./04-accessibility.md) §2 的八個**刻意相同**：一組清單，兩個用途。
兩份清單會漂移，一份不會。

| # | 畫面 | 為什麼是它 |
|---:|---|---|
| 1 | Active Board | 本輪最大的版面變化 |
| 2 | Backlog | rank handle 與 multi-select 的版面 |
| 3 | Drawer — waiting for input | attention 最高一級的呈現 |
| 4 | Drawer — no eligible runner | `plan/26` §2 有一條是「Drawer 在最需要說明原因的那張卡上閉嘴」，這一張就是它 |
| 5 | Drawer — blocked by dependency | `blocking_refs` 的呈現，而 `HD-06` 會動它的資料來源 |
| 6 | My Work | 六區一頁，跨專案 |
| 7 | Project Overview | 七個模組一頁 |
| 8 | Home（含 fleet health） | `plan/26` 的 `PX-63` 動過導覽，而 fleet health 是 V1 的東西 |

**`GATE-HD-VISUAL-BASELINE`**：`__screenshots__/` 下的檔數 == spec 裡宣告的畫面數。
少一張的表現是「那個畫面沒被比較」，而那是沉默的。

## 4. 為什麼門檻不是 0

字型 hinting、游標、animation 的最後一格、GPU 合成的 sub-pixel 差異——
這些在同一台機器上重跑都可能產生幾十個像素的差。

一套門檻 0 的套組會在**第一次**就紅。而它紅第三次之後，
**會有人在 CI 加 `--update-snapshots`**，而那時它擋不住任何東西。

`maxDiffPixelRatio: 0.01` 在 1440×900 上約是 13000 個像素——
足以容忍抗鋸齒，不足以容忍一個按鈕移位。

**這個數字是猜的**，它進 [`10`](./10-open-measurements.md) §6：
本期結束時數一次誤報次數，若 > 0 就調高並記錄。

## 5. baseline 放哪、誰更新

| 問題 | 答案 |
|---|---|
| 存哪 | `frontend/tests/hd/__screenshots__/`（進 git），由 `playwright.config.ts` 的 `snapshotPathTemplate` 釘成一層平的目錄——預設會按 spec 與平台分層，那會讓「八個宣告、八個存檔」變成一個對目錄走訪的斷言而不是對涵蓋率的 |
| 幾個平台 | **只 chromium**。三個瀏覽器 × 八個畫面 = 24 張 baseline，而 firefox／webkit 的字型渲染差異會讓其中 16 張永遠在容忍邊緣 |
| 誰能更新 | 改版面的那個 PR。`--update-snapshots` 的 diff **必須出現在 code review 裡**——那正是這套機制的價值：**版面變化變成一個要被看過的 diff** |
| CI 上跑不跑 | 跑。**跑不起來就不要建這套**——一個只在本機跑的視覺回歸與 `artifacts/` 的人工截圖沒有差別 |

## 6. 順序：`HD-04` 之後

若 `HD-04` 改了 `--attention-*` 的顏色值（對比不足時會），
八張 baseline 全部要重拍。所以 **`HD-05` 排在 `HD-04` 之後**，
而它們在同一個波次——因為它們共用同一組畫面清單與同一次 stack 啟動。

## 6b. ★ baseline 的第一版釘的是一堆豆腐字

第一次拍完八張 baseline 之後才發現：**這個容器只有 DejaVu，沒有 CJK 字型**。
而這個 UI 的文字幾乎全是繁體中文，所以那八張 baseline 釘的是
一整頁的 `□□□□`——版面對，字全是方框。

**那比沒有 baseline 更糟**：它在這台機器上永遠會過，
在任何有中文字型的機器上永遠會失敗，而失敗訊息會說「版面變了」。
一套只在一種環境下有意義的 baseline，是一套會教人加 `--update-snapshots` 的 baseline。

處置：裝 `NotoSansCJK-Regular.ttc` 到 `~/.local/share/fonts/` 之後重拍。

**而這一條真正的結論不是「裝了字型」**，是 §5 那句「跑不起來就不要建這套」
比原本寫的時候更嚴格：**視覺 baseline 綁定的不只是瀏覽器，是整個字型環境**。
CI 必須用一個明確的 image，而那個 image 要有 CJK 字型——
否則第一次在 CI 上跑就是八張全紅。這一條進 known limitations。

## 7. 出口條件（本節）

| ☐ | 條件 | 證據 |
|---|---|---|
| ☑ | 八張 baseline 在 repo 裡 | `frontend/tests/hd/__screenshots__/`（**路徑是 `tests/hd/`，不是 `tests/visual/`**——與 a11y 共用同一份 `screens.ts`，兩份清單會漂移） |
| ☑ | `GATE-HD-VISUAL-BASELINE` 綠（檔數 == 宣告數） | `PASS (8 screens)`。**gate 原本數 `toHaveScreenshot(` 的呼叫點，那是錯的**——spec 只有一個呼叫寫在 `for` 裡面，數出來是 1 對 8。改成數 `screens.ts` 的 `id:` |
| ☐ | 在 CI 上跑過一次並綠 | **未做**。本機跑過（8 passed，兩次）。一個只在本機跑的視覺回歸與 `artifacts/` 的人工截圖沒有差別（§5），所以這一格開著 |
| ☑ | 故意改一個 padding → 套組紅 → 還原 → 綠 | **反向測試已跑**：`artifacts/hd/local/w1/visual-negative.md`。改 `.lanes` 的 gap 與 padding → **兩個用到它的畫面紅、其餘六個綠** → 還原 → 八個全綠 |
| ☐ | 誤報次數記錄在 [`11`](./11-implementation-status.md)，若 > 0 則門檻已調並附理由 | **目前 0 次誤報／2 次連續重跑**——樣本太小，本期結束再數一次 |
| ☑ | 沒有新增任何套件 | `GATE-HD-TOUCH-LIST (frontend deps — one permitted addition: @axe-core/playwright)`——那一個是 `HD-04` 的，視覺這一半用 Playwright 內建的 |

**第四項（反向測試）是這一節最重要的一格。**
一套從沒紅過的回歸套組，與一套壞掉的回歸套組在儀表板上長得一樣。
`scripts/ui/evidence.sh:39` 已經有一個「守門反向測試」的先例
（`checkTokens.test.ts` 測 gate 自己會不會抓到），這一項沿用它的形狀。
