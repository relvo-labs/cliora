# 04 — Accessibility（`HD-04`）

> 上游：[`research/03/10`](../../research/03/10-verification-and-exit.md) §6（八行 ＋ 一句「所有 attention state 不得只靠顏色」）。
> 決策：[D125](./01-decisions-and-governance.md#d125)（一個新 devDependency ＋ 六項人工）、
> [D138](./01-decisions-and-governance.md#d138)（排在波次 1，不排在最後）。

## 1. 前提：這個 repo 現在沒有任何 a11y 工具

```bash
$ grep -rn "axe" frontend/package.json frontend/tests
$ # 空
```

所以 `HD-04` 不是「跑一次 audit」，是**建立一個 audit 能被重跑的機制**，
然後跑它，然後修到綠。

**為什麼排在波次 1**：`plan/26` 的 D115 寫過
「這會是第四次把畫面排在最後」。本期上游十二張 ticket 沒有一張是畫面，
而 a11y 是唯一一項**不依賴 provider、不依賴 tag、不依賴任何前置條件**的可見改善。
它跑在既有 `beta.1` 前端上，今天就能開工。

## 2. 自動的那一半（axe）

**套件**：`@axe-core/playwright`（devDependency，本期唯一新增）。

**八個畫面**，與 [`05`](./05-visual-regression.md) 的八個**刻意相同**——
一組畫面清單，兩個用途：

| # | 畫面 | 路徑 |
|---:|---|---|
| 1 | Active Board | `/projects/:id/work` |
| 2 | Backlog | `/projects/:id/work?view=backlog` |
| 3 | Drawer — waiting for input | `/projects/:id/work?task=…` |
| 4 | Drawer — no eligible runner | 同上，另一張卡 |
| 5 | Drawer — blocked by dependency | 同上，另一張卡 |
| 6 | My Work | `/my-work` |
| 7 | Project Overview | `/projects/:id/overview` |
| 8 | Home（含 fleet health） | `/` |

**門檻**：`critical` 與 `serious` 各 **0**。
`moderate` 與 `minor` 記錄但不擋——並且**記錄的數字要進 release note**，
因為「我們知道還有 N 個 moderate」與「我們沒量」是兩句不同的話。

**跑法**：`frontend/tests/a11y/*.spec.ts`，只在 chromium，
與視覺回歸同一次 stack 啟動（`scripts/e2e/run-stack.sh`）。

## 3. 人工的那一半（六項，axe 抓不到）

**這一節是本檔存在的理由。** 一份只有 axe 綠燈的 a11y 報告，
會讓下面六項看起來已經過了——而它們一項都沒被檢查。

| # | 項目 | 怎麼驗 | WCAG 2.2 AA 對應 |
|---:|---|---|---|
| 1 | **Focus 順序符合視覺順序** | 從 Board 的第一張卡開始按 Tab，記下順序，與畫面的閱讀順序比對。Drawer 開啟時 focus 進入 Drawer、關閉時**回到觸發它的那張卡** | 2.4.3 Focus Order |
| 2 | **狀態變化有被播報** | 開螢幕閱讀器（VoiceOver 或 NVDA），做一次 move、一次 filter apply、一次 attention 變化，記下**實際聽到的字**。`plan/26` 的 `PX-34` 有一個 `aria-live` 的實作，這一項驗它真的有聲音 | 4.1.3 Status Messages |
| 3 | **DnD 有鍵盤等價路徑** | 不用滑鼠把一張卡從 Backlog 移到 Ready。`plan/26` 說 Move dialog「是正式路徑而非備援」——這一項驗那句話 | 2.1.1 Keyboard |
| 4 | **200% 縮放下沒有橫向捲軸** | 瀏覽器縮放 200%，八個畫面各看一次。看板的欄位要換行或收合，**不是產生一條橫向捲軸** | 1.4.10 Reflow |
| 5 | **`prefers-reduced-motion` 被尊重** | 開系統設定的減少動態，Drawer 的滑入、optimistic move 的過場、載入骨架的閃動全部要停 | 2.3.3 Animation from Interactions |
| 6 | **attention 不只靠顏色** | 把畫面轉成灰階，八級 attention 要**仍然可分辨**。`plan/26` 的 `PX-18` 要求「icon ＋ 文字 ＋ 形狀至少兩項」——這一項驗它 | 1.4.1 Use of Color |

**每一項的證據是一張截圖或一段錄影 ＋ 一個具名的人。**
第 2 項的證據**必須包含實際聽到的字**，因為
「有 `aria-live` 屬性」與「螢幕閱讀器唸出了有意義的句子」是兩件不同的事。

## 4. 已知會撞到的三處

寫這份計畫時看程式碼推測的，**未實測**：

| 位置 | 疑慮 | 為什麼懷疑 |
|---|---|---|
| `tokens.css` 的 `--attention-*` 五個顏色 | 對比可能不足 AA（4.5:1） | `plan/26` 的 `PX-17` 加這五個 token 時的出口條件是「零 undefined token」，**不是對比** |
| 看板的四欄橫向佈局 | 200% 縮放下大概會產生橫向捲軸 | 四個等寬欄 ＋ 固定卡片寬度是這個結果的典型成因 |
| Drawer 的 focus trap | `plan/26` 有測試，但測的是 trap 存不存在 | trap 存在 ≠ 順序正確；第 1 項要驗的是後者 |

**若對比不足**：改的是既有 token 的**值**，不是加新 token（[`00`](./00-execution-plan.md) §4）。
改動要記進 [`11`](./11-implementation-status.md)，因為一個 token 的值變了，
[`05`](./05-visual-regression.md) 的八張 baseline 全部要重拍——
而那個順序（先修對比、後拍 baseline）是 `HD-04` 必須在 `HD-05` 之前完成的理由。

## 5. 出口條件（本節）

| ☐ | 條件 | 證據 |
|---|---|---|
| ☐ | `@axe-core/playwright` 已加入，`GATE-HD-TOUCH-LIST` 的前端依賴檢查改為「與基線相差恰好這一個」 | `package.json` diff ＋ gate |
| ☐ | 八個畫面 axe **0 critical／0 serious** | `artifacts/hd/local/w1/axe-after.json` |
| ☐ | audit **前**的報告也存下來 | `artifacts/hd/local/w1/axe-before.json` |
| ☐ | `moderate`／`minor` 的數字進 release note | release note |
| ☐ | 六項人工 checklist 全部完成 ＋ **具名簽核** | `docs/a11y-audit-v2e1.md` |
| ☐ | 第 2 項的證據含**實際聽到的字** | 同上 |
| ☐ | 第 6 項的灰階截圖八張 | `artifacts/hd/local/w1/grayscale/` |
| ☐ | 全鍵盤走完 J2（Backlog 建卡 → 送到 Ready）的錄影 | `artifacts/hd/local/w1/keyboard-j2.mp4` |
| ☐ | 若改了 token 值：改動已記錄，`HD-05` 的 baseline 在其**之後**拍 | [`11`](./11-implementation-status.md) ＋ 時間順序 |
