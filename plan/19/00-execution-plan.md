# 00 — 執行總控（V2.2_1 前端修復期）

## 1. 成功定義

這一期做完，下面五句話同時為真：

1. **`frontend/src/` 裡沒有任何一個 `var(--x)` 解不開**，而且**這件事被 `make check` 保證**——
   故意加一個解不開的引用，`make check` 會失敗。
2. 看板的六個車道、卡片上的 risk／delivery／run 狀態，**用的是中文標籤與有語意的顏色**，
   不是英文 enum 印在同一顆灰色藥丸上。
3. **「等待你的回覆」在一整面看板上第一眼被看到**，而且它的資料來自契約
   （`active_run_status`），不是前端猜的。
4. 三種證據 `source` 的視覺分級（實心／線框／灰字）**在三處畫面完全一致**，
   因為它們是同一個元件。
5. **旗標關閉時的 V1 畫面逐像素不變**，Session Workspace 的 Terminal 一個像素都沒變窄。

### 不算成功的樣子

- 104 個名字改對了，但沒有守門——**那只是把同一個坑重新填平，下一期照樣掉進去**。
- token 進了 `tokens.css`，但元件各自寫死顏色——語彙層等於沒建。
- 看板變好看了，但 `active_run_status` 還是沒有——D24 仍然做不到，只是看起來比較整齊。

## 2. 範圍

### 納入

| # | 內容 |
|---|---|
| 1 | **Token 層**：18 個語意色 ＋ 12 個尺度 token ＋ `--font-mono` 進 `tokens.css`，同步 `research/style.md` |
| 2 | **還債**：104 個未定義引用改對（83 A 類 ＋ 21 B 類；含 `--font-size-*` → `--font-*` 改名，以及拿掉 B 類的 fallback） |
| 3 | **守門**：`scripts/frontend/check-tokens.mjs` ＋ 掛進 `make check` |
| 4 | **元件層**：`frontend/src/components/ui/` — `BaseBadge` ＋ 五個語意徽章 ＋ 五個版面原語 |
| 5 | **看板契約**：`BoardCard` 補上 `plan/18/07` §3.3 指定但未實作的三個欄位 ＋ 補做 M1 量測 |
| 6 | **看板重繪**：車道著色、D24 醒目狀態、`waiting_reason` 兩種文案 |
| 7 | **拖曳反饋**：toast ＋ 卡片彈回動畫 |
| 8 | **Task 詳情**：兩欄版面 ＋ `SourceBadge` 三級 |
| 9 | **其餘畫面**：Roadmap／Agents／Run 詳情／Requirements／Projects 對齊原語 |
| 10 | **審查畫面**：`TokenShowcaseView` 更新為 V2 詞彙 |
| 11 | **視覺回歸**：Playwright screenshot 基準 |

### 不納入

| # | 不做 | 為什麼 |
|---|---|---|
| 1 | 深色模式 | 既有 `tokens.css` 也沒有，這一期不開這個頭 |
| 2 | 全域 class layer | 不翻案，但理由是 **P4-07 已指定共用元件作為替代方案而沒做完**，不是 `base.css` 檔頭那句概括。見 **D34** |
| 3 | 路由路徑變更 | `09` §2 硬規則 |
| 4 | V1 畫面重繪 | 四個 V1 檔案共 6 個未定義引用（全是有 fallback 的 B 類），只修那 6 個，版面不動；出口條件 8 用逐像素比對釘住 |
| 5 | Done Gate 拒絕 | V2.4 `DV-05`，不到期 |
| 6 | daemon 變更 | 這一期完全不動 node |
| 7 | RQ-07 mockup 變體檢視 | 卡在「HTML 產物不能在應用 origin 內渲染」的未決前置問題 |
| 8 | 四欄 Session Workspace | `09` §5 已否決 |
| 9 | naive-ui 全面導入 | 依賴已在 `package.json`，但本期不擴大使用面。見 **D35** |

## 3. 固定基線決策

| # | 決策 | 為什麼寫死在這裡 |
|---|---|---|
| B1 | **基線 commit 取一次，六份基線同一個 commit** | 沿用 `plan/18` `AR-00` 的做法。`UI-00` 擷取：104 個引用清單、43 個引用名單、27 個定義名單、board payload 大小、V1 畫面 screenshot、`make check` 綠燈輸出 |
| B2 | **token 命名採 prototype 的 `--font-*` 與 `--space-*`** | 與既有 `--radius-*`、`--layout-*` 對稱；程式碼裡的 `--font-size-*` 是憑印象寫的，18 處一併改名 |
| B3 | **中文標籤只在顯示層**，`stage`／`risk`／`delivery`／`status` 的值一律不動 | `01` D3。改值會動到 API、契約與 Monstrare 的詞彙對應 |
| B4 | **每顆徽章都帶文字標籤** | 顏色永遠不是唯一線索（WCAG 1.4.1，沿用 `StatusBadge.vue` 既有紀律） |
| B5 | **未知 enum 值必須有退路** | `BoardCard.risk`／`.delivery` 在 DTO 是 `string` 不是 union；後端多送一個值不得讓整頁壞掉 |
| B6 | **不動 `contracts/`、不動 daemon** | 看板是 HTTP REST；`contracts/` 只裝 WSS 的 `control-envelope` 與 `messages/`。`BoardCardDTO` 的變更走 **OpenAPI 快照比對**（`scripts/pj/openapi_diff.py`），且是**純新增欄位**——舊前端忽略多的欄位。見 `01` D33 |

## 4. 波次與 ticket

**波次 1 必須先合。** 後面每一張 ticket 都在它建立的地基上做，
先合才能讓「引用了不存在的 token」在開發當下就失敗，而不是在 review 時靠肉眼抓。

### 波次 1 — 地基（`UI-00`、`UI-01`、`UI-02`、`UI-03`）

| ticket | 內容 | 完成定義 |
|---|---|---|
| `UI-00` | 擷取六份基線（B1） | 六份檔案進 `plan/19/baseline/`，同一個 commit |
| `UI-01` | Token 定稿 | 31 個 token 進 `tokens.css`；`research/style.md` 同步；每一組有註解說明它承載哪個決定 |
| `UI-02` | 104 個引用還債 | 13 個檔案改完（83 A 類先、21 B 類後）；**畫面外觀在此步驟不刻意改動**——這一步是「讓既有意圖生效」，不是重設計 |
| `UI-03` | **守門** | `check-tokens.mjs` ＋ `make check` 掛載；反向測試（故意加壞的引用會失敗）進 CI |

> **`UI-02` 與 `UI-01` 不可對調。** 先定 token 才有正確的名字可改。
> **`UI-03` 要在 `UI-02` 之後立刻做**，中間不要插別的 ticket——
> 那個空窗期正是 104 個引用當初誕生的條件。

### 波次 2 — 語彙（`UI-04`、`UI-05`）

| ticket | 內容 | 完成定義 |
|---|---|---|
| `UI-04` | 徽章族 | `BaseBadge` ＋ 五個語意徽章；每個有單元測試斷言標籤與變體；未知值退路有測試 |
| `UI-05` | 版面原語 | 五個元件；每個有單元測試；`EmptyState` 強制要求 `action` slot（`09` §6） |

波次 2 的兩張可並行。

### 波次 3 — 看板（`UI-06`、`UI-07`、`UI-08`）

| ticket | 內容 | 完成定義 |
|---|---|---|
| `UI-06` | 看板契約 | OpenAPI 快照更新（純新增欄位）；backend **第三個 grouped 查詢**（不得 N+1）；**M1 重量 ≤ 90 KB 並寫進 `10-…md`** |
| `UI-07` | 看板重繪 | 車道著色；D24 滿版色條＋脈動；兩種等待文案逐字不同 |
| `UI-08` | 拖曳反饋 | toast ＋ 彈回動畫；兩個 e2e case |

`UI-06` 可與波次 2 並行（它動的是後端與契約，不碰元件）。

### 波次 4 — 其餘畫面（`UI-09`、`UI-10`、`UI-11`）

三張可並行，都依賴波次 2。

### 波次 5 — 收尾（`UI-12`）

視覺回歸基準 ＋ 出口條件全綠 ＋ `evidence.sh`。

## 5. 風險

| 風險 | 徵兆 | 處置 |
|---|---|---|
| **`UI-02` 變成一次重設計** | diff 裡出現版面調整、新增 class、改結構 | `UI-02` 的 diff **只允許改 `var(--x)` 的名字**。review 時用 `git diff -U0` 掃，出現非 token 行就退回。版面調整屬於 `UI-07`…`UI-10` |
| **M1 回退** | board payload > 90 KB | **先砍 `waiting_reason`**（它也是查詢成本最高的，`04-…md` §1.3b），再砍 `active_run_runner_name`；`active_run_status` 最後才動。**先量再決定，不預先妥協** |
| **守門誤報擋住開發** | `var(--x)` 寫在字串或動態 style 裡被誤判 | 檢查器只掃 `.vue`／`.css` 的 `<style>` 與 css 檔；`style="..."` 的行內綁定另列白名單機制（`07-…md` §3） |
| **徽章族與既有 `StatusBadge` 打架** | 兩套徽章樣式並存、視覺不一致 | **`StatusBadge` 不動**（它服務 V1 的 node／terminal 狀態，有既有 screenshot 基準）。新徽章族服務 V2 語彙。兩者的邊界寫在 `03-…md` §1 並在 `UI-11` 的審查畫面上並排展示 |
| **B 類的修正改到今天看得見的顏色** | 逐像素比對失敗、或有人回報「顏色變了」 | 21 個有 fallback 的引用今天用 `crimson`／`seagreen`／`darkorange`／`#d0d0d0` 渲染，**看起來正常**。改成 token 值會變色——**這是本期真正的視覺風險，不是那 83 個壞掉的**。處置：8 個涉及檔案各附前後對照，人工確認；出口條件 8 的 V1 基準在 `UI-02` 之後才取（`08-…md` §4） |
| **prototype 被當成規格逐像素抄** | 出現 prototype 專用的 `.proto-bar`、說明模式、假資料 | prototype 是**語意與分級的參考**，不是版面規格。`00` §2 的「不納入」與 `03-…md` §1 的元件清單才是範圍 |
