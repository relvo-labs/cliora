# 08 — 開放量測項

沿用 `plan/12`／`plan/15` 的慣例：這些是**還不知道答案的問題**，不是待辦事項。
一個待辦事項寫下來是為了被做掉；一個量測項寫下來是為了讓某個決定有依據。

## 1. M8 — sidebar 208px 在分組後夠不夠 ✅ **已量（2026-08-08）**

> **結論：夠。採用的分隔線版本餘裕 61px，不用改任何東西。**
>
> ```
> chromium 149.0.7827.55  viewport 1440x900  --layout-sidebar 208px  aside padding 24px
>
> --- variant: divider  (ADOPTED) ---
> item              indent  content  needed  note
> Projects          0px     97px     121px   V2.0 new, flat
> Sessions          0px     100px    124px   existing, flat
> Infrastructure    0px     98px     122px   group label
> Dashboard         0px     114px    138px   all roles
> Nodes             0px     86px     110px   all roles
> Enrollment        0px     116px    140px   enrollment.manage
> Audit             0px     79px     103px   audit.view
> Integrations      0px     123px    147px   integration.manage
> widest: Integrations 147px   headroom: 61px   FITS
>
> --- variant: indented ---
> ... (same content widths, children +12px)
> widest: Integrations 159px   headroom: 49px   FITS
>
> VERDICT: adopted variant fits with 61px to spare — no change needed
> ```
>
> 量法：`scripts/pj/measure-sidebar.mjs`（Playwright + Chromium 149.0.7827.55，
> 1440×900）。它讀**真的** `theme/tokens.css` 與 `theme/base.css`，
> nav 規則逐字複製自 `AppLayout.vue` 的 scoped block——沒有一個數字是估的。
>
> **兩個變體都量，是刻意的**：分隔線 vs 縮排是一個**設計選擇**，不是被寬度逼出來的
> （兩者都通過）。把落選的那個也留在輸出裡，日後「為什麼選了餘裕 61px 的那個
> 而不是 49px 的」才查得到（`05-…md` §1.3）。
>
> 四件從數字裡讀出來的事：
>
> 1. **V2.0 幾乎沒花掉餘裕。** 採用的版本最寬仍是 `Integrations` 的 147px——
>    與升級前**完全相同**，因為子項不縮排。新增的 `Projects`（121px）比它窄。
>    `plan/09` 的 64px 餘裕一分都沒動到（61px 的差是 aside padding 的算法差異）。
> 2. **`plan/09/03` 的 144px 確實過期了**，但方向相反——它**低估**了目前的最寬項
>    （`Integrations` 是 147px，而它算的是 `Enrollment` 的 140px）。差距只有 7px，
>    所以那份決定的結論沒有錯，只是基準項換了人。
> 3. **對非 Admin，最長的不是分組標籤。** 我在規劃時假設
>    Developer／Viewer 只看得到三項時 `Infrastructure`（122px）會變成最長的東西——
>    **錯了**，`Dashboard` 是 138px。`05-…md` §1.4 的第二、三檔因此用不到，
>    但推論寫錯了要記下來。
> 4. **縮排版本也過得了。** 選分隔線不是因為縮排放不下，是因為側欄還會再長
>    （V2.2 要加 `Agents`），而縮排讓每一個子項都付 12px。
>
> **仍然要做的一件事**：高度。Admin 現在是 6 列，之後是 8 列 ＋ 1 個標題列。
> 1080p 沒問題，但 `plan/09` 的 app-shell 高度規則要在 `PJ-06` 用真的畫面複驗一次
> （`aside` 有 `overflow-y: auto`，所以最壞情況是捲動而不是破版）。

以下是量測前的原始問題，保留供追溯。

`research/02/10` §5 唯一一條列為「V2.0 開工時」的量測。

**問題**：`plan/09` 把 `--layout-sidebar` 從 280px 改成 208px，理由是
「最長項需 ≈144px，208px 留 64px 餘裕：中文化標籤或多一個項目都不會擠」。
V2.0 要花掉的正是那 64px 的一部分。

**量什麼**（devtools 實測，不是估算）：

| # | 量測 | 值 |
|---|---|---|
| 1 | 目前最長項 `Integrations` 的渲染寬度（icon ＋ 11px gap ＋ 文字 ＋ 左右各 11px padding） | — |
| 2 | 同上 ＋ 12px 縮排 | — |
| 3 | 分組標題 `Infrastructure` 無縮排的寬度 | — |
| 4 | max(1,2,3) ＋ `aside` 的左右 padding 各 12px | — |

**判準**：第 4 項 ≤ 208px 就過。處置順序見 `05-…md` §1.4。

**一個規劃文件沒算到的複雜度**：導覽項是**權限條件**的，所以「最長項」在三種角色下不同。

| 角色 | 可見的最長項 |
|---|---|
| Admin | `Integrations`（縮排後） |
| Developer／Viewer | `Dashboard`（縮排後）——`Infrastructure` 這個**分組標題**反而更長 |

所以第 3 項不是可有可無的：**對非 Admin 而言，最長的東西是分組標題本身。**

**高度亦已用真的 app shell 複驗**：`scripts/pj/measure-nav-height.mjs` 在
1440×900 得到 `client=844, scroll=844, last=344`，在 1920×1080 得到
`client=1024, scroll=1024, last=344`；兩者皆 `FITS`。輸出在
`artifacts/pj/local/nav-height.txt`。

> ~~**這台機器跑不了瀏覽器**（`07-…md` §4）。這是開工前第一個要解決的問題。~~
> **已解決**（2026-08-08，使用者補上 Chromium 的系統套件）。量測已完成，見本節開頭。

## 2. M-PJ-01 — Project 詳情頁的回應大小與耗時

> ✅ **已量（2026-08-08）**：50 條綁定、30 個 ASGI HTTP 樣本，回應
> **14,241 bytes**，mean **51.877ms**、p95 **53.917ms**，低於 200ms 判準。
> 不設綁定上限、不加快取。可重跑的 harness 是
> `scripts/pj/measure-project-detail.py`，原始結果在
> `artifacts/pj/local/project-detail-performance.json`。

**問題**：`GET /api/projects/{id}` 要做四件事——讀 Project、讀綁定清單、
**對每一條綁定跑一次 `authorize_workspace()` 與一次 `seconds_since_heartbeat`**、
數進行中的 Session。第三件是 O(綁定數) 的，而且它碰的是 registry 的記憶體狀態。

**影響什麼**：綁定數要不要設上限；`BindingUsability` 要不要快取。

**何時測**：`PJ-04` 完成後，用 50 條綁定的假資料。

**判準**：p95 < 200ms 就不處理。超過的處置順序是
（a）把 heartbeat 查詢批次化、（b）綁定數設一個上限並在 UI 說明、
（c）最後才是快取——快取會讓「root 剛被停用」與畫面之間出現一個窗口，
而那個窗口正是紅線 2 要關掉的東西。

## 3. M-PJ-02 — `activity_events` 的成長速率

**問題**：一個活躍專案一天產生幾筆？一年之後那張表多大？

V2.0 只有六個 `kind`，而且都是低頻的（建立、綁定、Session 起訖）。
但 V2.1 會加上任務狀態轉換，V2.2 會加上 run 的每一個階段——**成長速率會跳一個量級**。

**影響什麼**：`00-…md` D6 決定「沒有保留期」。那個決定的前提是這張表**不會無界成長到
變成問題**。如果 V2.2 之後一個專案一天產生上千筆，這個前提要重新檢查——
但那時的答案不會是「加一個保留期」（它是產品內容），而是「哪些 kind 其實是診斷、
應該去 `run_logs`」。

**何時測**：V2.0 上線後持續觀察，**V2.2 開工前必須有數字**。

## 4. M-PJ-03 — 有多少 Session 實際上是 Ad-hoc（`research/02/10` 的 M7）

**問題**：`GET /api/sessions?project_id=none` 的比例。

**影響什麼**：`research/02/10` §5 把它列為「決定 V2 的預設值該不該變」。
更直接的用途是：**如果幾乎沒有人用 Project，那 V2.1 的看板也不會有人用**——
它與 M14（人工規格表單有沒有人用）是同一類的早期訊號。

**何時測**：V2.0 上線後持續觀察。`?project_id=none` 這個查詢參數就是為此存在的
（`04-…md` §1.2）。

## 5. M-PJ-04 — 「路徑已不存在」值不值得偵測

**問題**：`BindingUsability` 本期只有兩種真的不可用（`node_offline`、`root_disabled`）。
第三種——路徑被刪掉了——需要一次 `filesystem.*` 往返，而本期不動 protocol。

**要量的是**：綁定的路徑實際上有多常消失？

**影響什麼**：V2.1 動 daemon 時要不要順帶做。三個可能的答案：

| 觀察結果 | 處置 |
|---|---|
| 幾乎不發生 | **不做**。使用者在建立 Session 時拿到 daemon 的既有錯誤，與今天手動輸入不存在的路徑完全一樣 |
| 偶爾發生 | 在 Project 詳情頁做一次**按需**檢查（一個〔檢查〕按鈕），不做輪詢 |
| 經常發生 | 隨綁定清單一起查——但那會讓 `GET /{id}` 變成 O(綁定數) 次 daemon 往返，需要先解 M-PJ-01 |

**何時測**：V2.0 上線後觀察，**V2.1 開工前**要有傾向。

## 6. 沒有要量什麼，以及為什麼

| 沒量 | 為什麼不量 |
|---|---|
| Project 數量的上限 | 一個組織的專案數是人手打進去的，不會失控。真的到需要分頁的量級時，`GET /api/projects` 已經有 `limit`／`offset` |
| 綁定的路徑深度／長度 | `String(4096)` 與 `terminal_sessions.workspace` 一致，那個上限已經活了四期 |
| 導覽重整對「找得到 Nodes」的影響 | 這不是量測問題，是設計問題：路由不變 ＋ `Infrastructure` 永遠展開（`05-…md` §1.3）。量它會得到一個沒有基準可比的數字 |
| `features` 欄位對回應大小的影響 | 一個最多兩個短字串的陣列，出現在兩個端點上 |
| 三張新表的寫入延遲 | 每一次寫入都是單列 INSERT，而且它們都掛在一個本來就要寫 audit 的路徑上——多一筆 INSERT 不會改變那條路徑的量級 |

## 7. 從 `research/02/10` §5 繼承但**不屬於本期**的

列在這裡是為了讓它們不被遺忘，不是為了在本期做：

| # | 問題 | 什麼時候 |
|---|---|---|
| M1 | 200 張卡的看板 API 回應大小與耗時 | V2.1 開工前 |
| M2 | Agent 實際使用 `cliora` CLI 回報的比例 | **V2.1 上線後最重要的一項**——它驗證內化路線的核心假設 |
| M3 | 情境包壓到 4 KB 後 Agent 行為是否變好 | V2.1 上線後 |
| M9 | 平台不可用的實際頻率與時長 | V2.1 起持續（D14 重新評估的觸發條件） |
| M11／M12 | repo clone／worktree 耗時、run 目錄大小 | V2.3 開工前 |
| M6 | `git status --porcelain` 在最大 repo 的耗時 | V2.4 開工前 |
</content>
