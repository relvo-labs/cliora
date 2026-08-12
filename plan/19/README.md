# Cliora V2.2_1 — 前端修復期

> **狀態：計畫已定稿，尚未開工。** 2026-08-12 開立。
> 前置條件是 V2.2（[`plan/18/`](../18/README.md)）。
> **合併規則不變**：`v2` → `dev` 一律由人決定，出口條件全綠只是取得提案資格。

本目錄是 [`research/02/12-phase-v22_1-ui-remediation.md`](../../research/02/12-phase-v22_1-ui-remediation.md)
的執行計畫，ticket 統一使用 `UI-` 前綴。

規劃層回答「為什麼要有這一期、要修成什麼樣」；本目錄回答
「在**這個 repo 的現況**上怎麼做得出來、做完怎麼證明」。

---

## 這一期為什麼存在

一句話：

> V2.0–V2.2 的前端引用了 **104 個從未定義的 CSS custom property**。其中 **83 個沒有寫
> fallback**，瀏覽器把那些宣告**整條**丟棄——而那 83 個 **100% 落在 V2.1 任務層的五個檔案**，
> 所以看板、任務詳情、藍圖是以接近無樣式的 HTML 在渲染。
> 另外 21 個有 fallback，不會壞，但把 `crimson`、`seagreen`、`#d0d0d0` 帶進了一個有 design
> token 檔的專案。**`make check` 的八項檢查沒有一項會看到這兩件事。**

`research/prototype-v2/` 早就把正確的樣子做出來並排好了 24 個 token 候選值，
`README.md` 明寫「審查通過之後，那一段才會進 `tokens.css`」。**那次審查沒有發生。**

這一期把那條路走完，並且**加上守門**，讓同一個錯誤不可能再默默通過。

## 三層缺口

修好第一層畫面就不再醜，**但那三個要被看見的狀態仍然看不見**。所以三層都要修。

| 層 | 缺什麼 | 落在哪 |
|---|---|---|
| **1 機械層** | 104 個解不開的 `var()`／13 檔：**83 無 fallback**（`border`／`gap`／`font-size` 整條被丟棄）＋ **21 有 fallback**（不壞，但繞過 token） | `02-token-layer.md` |
| **2 語彙層** | `tokens.css` 沒有 stage／run／risk／source 任何一組顏色，也從來沒有間距與字級刻度 | `02-token-layer.md`、`03-component-primitives.md` |
| **3 決定層** | prototype 要證明的七件事，看板上還缺三件（D24、D10、`09` §7） | `04`、`05` |

**第 3 層裡最重的一條不是樣式問題**：D24（「等待你的回覆」必須最醒目）
目前是**契約缺口**——`plan/18/07` §3.3 指定過看板要多三個欄位，
實作時一個都沒進去，所以看板無從得知哪張卡在等人。詳見 `04-board-contract-and-cards.md`。

## 文件導覽

| 文件 | 用途 |
|---|---|
| [00-execution-plan.md](./00-execution-plan.md) | 成功定義、範圍、固定基線決策、波次與 ticket、風險 |
| [01-decisions-and-governance.md](./01-decisions-and-governance.md) | **D32–D36** 五個本期決策、ADR 處置、紅線檢查 |
| [02-token-layer.md](./02-token-layer.md) | `UI-01`／`UI-02`：token 定稿與 104 個引用的還債 |
| [03-component-primitives.md](./03-component-primitives.md) | `UI-04`／`UI-05`：徽章族與版面原語（**不重新引入全域 class layer**） |
| [04-board-contract-and-cards.md](./04-board-contract-and-cards.md) | `UI-06`／`UI-07`／`UI-08`：看板契約、D24、拖曳反饋 |
| [05-task-detail-and-evidence.md](./05-task-detail-and-evidence.md) | `UI-09`：兩欄版面與 `SourceBadge` 三級（D10） |
| [06-remaining-screens.md](./06-remaining-screens.md) | `UI-10`／`UI-11`：其餘畫面與審查畫面 |
| [07-guardrails.md](./07-guardrails.md) | **`UI-03`**：token 解析守門——這一期最重要的一張 ticket |
| [08-verification-and-exit.md](./08-verification-and-exit.md) | `UI-12`、測試矩陣、9 條出口條件、`evidence.sh` |
| [09-implementation-status.md](./09-implementation-status.md) | 實作進度與證據（開工後填） |
| [10-open-measurements.md](./10-open-measurements.md) | M1 重量、待量項 |

## 建議使用方式

1. 先讀 `00` §1（成功定義）與 `07`（守門）。**守門是這一期的產品，不是附件。**
   修 104 個名字只是還債；讓第 105 個不可能發生才是交付。
2. `01` 的五個決策要先點頭，特別是 **D32（token 整組採納）** 與
   **D34（不重新引入全域 class layer）**。
3. 波次照 `00` §4：**波次 1（token ＋ 守門）必須先合**，否則後面每一張 ticket
   都在一個測不出錯的地基上做。
4. 每張 ticket 以「決策 → 契約 → 實作 → 自動測試 → 操作證據」完成。
5. 出口條件未全綠，不把 V2.3 標為可開工。

## 這一期不做

- **不做深色模式**（既有 `tokens.css` 也沒有）。
- **不重新引入全域 class layer**——但理由不是 `base.css` 檔頭那句概括。
  `P4-07` 刪 `src/styles.css` 時**同時指定了替代方案：新增
  `components/common/{PageHeader,Panel}.vue`**，而那兩個元件從來沒被建立
  （`01` §D34）。D34 是**把那個後半做完**，不是新主張。
  prototype 用全域 class 是它零依賴的體質，不是要照搬的結論。
- **不改任何路由路徑**（`09` §2 硬規則）。
- **不重畫 V1 畫面**——四個 V1 檔案共有 6 個未定義引用（全部是有 fallback 的 B 類），
  那 6 個照修，版面一個像素不動。
- **不動 daemon，也不動 `contracts/`。** 看板是 HTTP REST；`BoardCardDTO`
  的變更走 OpenAPI 快照比對，且是純新增欄位。
- **不補 Done Gate 拒絕**——那是 V2.4 的 `DV-05`，本期不到期。

## 規劃基準（已核對過的事實，2026-08-12）

- `frontend/src/theme/tokens.css` 定義 **27** 個 custom property（`base.css` 定義 **0** 個）；`frontend/src/` 引用 **43** 個。
- 未定義引用 **104 次 / 13 個檔案** = **83 無 fallback ＋ 21 有 fallback**。
  83 個 **100% 落在 V2.1 任務層**：`TaskBoard.vue`(31)、`TaskDetail.vue`(26)、`TaskRoadmap.vue`(17)、`RequirementDetailView.vue`(5)、`TaskDetailView.vue`(4)。
- `BoardCard`（`frontend/src/api/dto.ts` §857 起、`backend/app/repositories/tasks.py` §23 起）**沒有任何 run 欄位**。
- `waiting_reason` 只存在於 `DispatchResponseDTO`，看板拿不到。
- `DONE_GATE_UNMET` 錯誤碼在 backend／frontend／`docs/error-catalog.md` 三處都不存在（正確，V2.4 才有）。
- `make check` = `format-check lint typecheck unit contract build traceability-validate railway-check`——**沒有任何一項會解析 CSS 變數**。
- `frontend` 沒有 stylelint，`eslint.config.js` 不看 `<style>` 區塊。
- **`P4-07` 指定的 `PageHeader.vue`／`Panel.vue` 從未建立**；它要遷移的五個 class
  今天擴散到 **17／9／15／9／22** 個檔案，各自實作、沒有一份權威。
- `TokenShowcaseView` 是 **dev-only**（`import.meta.env.DEV`），P4-07 定案保留，
  理由是「唯一能一頁看完 token 系統的地方」。
