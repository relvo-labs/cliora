# 01 — 決策與治理（D119–D140）

> 每一項都寫「不同意的話會怎樣」，而且**裁決之後那一段保留**。
> A 類九項的全文在 [`00`](./00-execution-plan.md) §0.1，本檔不重複，只補 §0.1 放不下的細節。
> 編號從 **D119** 起——`plan/26` 用到 D118。

## 0. 裁決單

> **☑ A 類九項全部於 2026-08-25 裁決，全部採納計畫的答案。**
> 各項全文（含「不同意的話會怎樣」）保留在 [`00`](./00-execution-plan.md) §0.1 與本檔 §1
> ——那是**為什麼這樣決定**的紀錄。三個月後沒有人會想知道選了什麼，
> 但每個人都會想知道當時放棄了什麼。

| # | 決定 | 類別 | 狀態 | 裁決日 | 一起接受的代價 |
|---|---|---|---|---|---|
| ★ D120 | `beta.2` 只做 pull，不做 inbound webhook | **A** | ☑ **採納** | 2026-08-25 | 新鮮度 300 秒而非即時；webhook 只在 ADR 0043 裡（已設計、未實作） |
| D119 | `provider_reads.py` 是 `httpx` 的第二個合法模組 | **A** | ☑ **採納** | 2026-08-25 | 兩份 timeout／host allowlist／token 剝除，刻意重複 |
| D121 | 兩個新 source type ＋ `EXTERNALLY_TRIGGERED` 宣告 | **A** | ☑ **採納** | 2026-08-25 | 覆蓋率測試從斷言一個值，變成斷言兩個宣告一致 |
| D122 | provider authority 值域 frozenset ＋ 天花板 gate | **A** | ☑ **採納** | 2026-08-25 | 真的被當規格讀的 PR 描述永遠低於 `accepted` 一級 |
| D123 | `HD-06` 拆 `0045`／`0046` ＋ go／no-go | **A** | ☑ **採納** | 2026-08-25 | 多一個過渡欄位 `legacy_blocked_at`、多一個 revision；**且 go／no-go 可能導致整張跳過** |
| D124 | `toHaveScreenshot` 八畫面、門檻是比例 | **A** | ☑ **採納** | 2026-08-25 | 第九個畫面的版面回歸沒有東西會抓到 |
| D125 | `@axe-core/playwright` 是唯一新套件 ＋ 六項人工 | **A** | ☑ **採納** | 2026-08-25 | 「不新增前端套件」（D56）這條線破一次 |
| D126 | `/board` 刪除；`?tab=` 保留到 `rc.1` 並計數 | **A** | ☑ **採納** | 2026-08-25 | 一個寫得很好的釘死測試要刪，量測紀錄搬進 ADR 0044 |
| D138 | 波次 1 是 a11y；新增 `HD-15` | **A** | ☑ **採納** | 2026-08-25 | `HD-15` 是十六張裡唯一沒有上游對應的功能 ticket |
| D127–D137 | 見 §2 | B | ☐ 依計畫執行 | — | 有異議時記在 [`11`](./11-implementation-status.md) §2 |
| D139 | `HD-06` 若跳過，ADR 0040 的修訂要寫「不還」而不是留白 | B | ☐ | — | 同上 |
| D140 | 本期的 known limitations 至少四條，空的清單需要解釋 | B | ☐ | — | 同上 |

**九項全綠，八個波次沒有裁決性阻礙。**
剩下的阻礙有兩種，而它們不一樣：

| 阻礙 | 擋哪些波次 |
|---|---|
| [`00`](./00-execution-plan.md) §0.4 的剩餘三項（**Railway `pg_trgm` 量測**、`alpha.3` tag、`beta.1` tag）＋ `HD-06` 的 go／no-go | 2、3、4 |
| **前一個波次的產物**（不是前置條件） | 6（等 4、5）、7（等全部） |

**現在真正可以開工的是波次 0、1、5 —— 六張 ticket**：
`HD-00`／`HD-07`／`HD-13`／`HD-04`／`HD-05`／`HD-10`。

波次 6、7 **不被前置條件擋**，但它們要演練與驗證的東西還不存在。
把這兩種阻礙分開寫是刻意的：一個「等簽名」的波次與一個「等前一個波次」的波次，
**能做的事完全不同**——前者要去催人，後者要去做上一個波次。

## 1. A 類九項的補充細節

### D119 — `provider_reads.py` 的形狀（補充）

`00` §0.1 給了理由，這裡給形狀。**兩個模組刻意不共用 `_request()`**：

```text
services/providers.py          三個動作：create PR / find PR / comment
                               POST + GET + POST
                               GATE-DV-PROVIDER-VERBS: 那七個字不出現

services/provider_reads.py     三個讀取：read PR state / list PRs for branch / list releases
                               只有 GET
                               GATE-HD-READS-ARE-GETS: HTTP method 字面只有 "GET"
                               GATE-HD-NO-WRITE-IMPORT: 不 import providers 的三個動作
```

**共用會失去什麼**：把 host allowlist、timeout 與 token 剝除抽成一個 `_transport.py`
之後，「這個模組只 GET」這件事就不再是一個可以用 grep 斷言的檔案屬性，
而是一個「呼叫端有沒有傳對 method」的約定。而約定需要一個測試，
測試需要一個人記得寫——這正是 `GATE-DV-PROVIDER-VERBS` 選擇「以缺席驗證」的理由。

**重複的成本是三個常數與二十行**，而它換到的是兩個各自成立的 grep。

**`provider_reads.py` 的 host allowlist 沿用 `settings.provider_api_host_list()`**，
與 `providers.py` 同一個部署設定。這是刻意的：兩個模組連到的地方由**同一個**設定決定，
所以「這個部署允許連到哪裡」仍然只有一個答案。

### D120 — pull 模型的三個具體後果（補充）

`00` §0.1 給了選擇，這裡給後果。

**① SR-4 從五項變成兩項 ＋ 三項改寫**：

| 上游 SR-4 審查項 | pull 模型下 |
|---|---|
| webhook signature 驗證 | **不存在**（沒有 webhook） |
| delivery id 去重 | **不存在**——reconcile 的每一輪都是「重讀 entity 當前狀態」，重複是免費的（`outbox.py:15` 的同一個論證） |
| webhook 不在請求內同步抓 repo 或算 embedding | **改寫為** `GATE-HD-NO-PROVIDER-IN-REQUEST`：`api/http/` 下任何模組不得 import `provider_reads`。精神相同——**對外的 GET 只能發生在 worker 裡**，不能發生在使用者的請求裡 |
| provider token 的保存、範圍與輪替 | **保留**，沿用既有 `provider_token` kind（[D129](#d129)） |
| merge 前的 PR 內容不自動成為 policy | **保留**，且變成一個值域限制而不是一個流程（[D122](#d122)） |

**新增兩項**（pull 特有）：

| 審查項 | 通過標準 |
|---|---|
| 一個被撤權的 token 不會讓 reconcile 無限重試 | GET 失敗計數達上限後該 repository 停止同步並在設定頁顯示原因；`PROVIDER_READ_FAILED` 有 raise 點與測試 |
| provider 的錯誤 body 不含 token 也不進 log | 沿用 `providers.py:_safe_detail` 的形狀，**在新模組裡再寫一次**（D119 的重複） |

**② `0044` 少一張表**：不需要 `provider_deliveries`。
需要的只有 `projects.provider_sync_enabled BOOLEAN NOT NULL DEFAULT false`
與 `project_repositories.provider_synced_at TIMESTAMPTZ NULL`
＋ `provider_sync_error TEXT NULL`。

**③ 新鮮度的數字要寫進 release note**：
「一個 PR 合掉之後，最多 300 秒出現在 Related knowledge」。
這是一個**產品承諾**，不是一個實作細節；它與 `alpha.2` 的
「message commit → continuation turn P95 < 10s」是同一類的句子。

### D121 — `EXTERNALLY_TRIGGERED` 的寫法（補充）

```python
# services/knowledge/store.py —— 加在 SOURCE_TYPES 之後
#: Source types with **no `ActivityService` kind**, because the thing that changes them
#: is not something Cliora did. `repo_doc` arrives by push from inside a run; the two
#: provider types arrive because somebody merged or tagged on a server we do not own.
#: `test_every_ingestable_source_type_has_an_activity_kind` reads this set rather than
#: holding its own literal — so adding a ninth type means writing down a *reason*,
#: not editing a test.
EXTERNALLY_TRIGGERED: frozenset[str] = frozenset({"repo_doc", "pull_request", "release"})
```

**半衰期**（`search.py:_HALF_LIFE_DAYS`）：

| 型別 | 半衰期 | 為什麼 |
|---|---:|---|
| `pull_request` | **90 天** | 與 `artifact` 同級。一個 PR 的討論在三個月後仍然解釋得了為什麼程式碼長這樣，但它不是規格 |
| `release` | **365 天** | 與 `decision` 同級。「v1.4 有什麼」這件事不會因為時間而變得比較不真 |

**這兩個數字是猜的**，而它們進 [`10`](./10-open-measurements.md) §5 的未量測項。
`.get(…, 90.0)` 的預設讓漏掉不會崩，所以**要明寫**這兩個是刻意選的而不是撿到預設值。

### D122 — 天花板 gate 的精確形式（補充）

```bash
# GATE-HD-PROVIDER-AUTHORITY-CEILING
absent "the provider handler reached above `reviewed`" \
  -E '"(accepted|authoritative|canonical)"' \
  backend/app/services/knowledge/provider_sources.py
```

**為什麼 handler 放在自己的檔案**：`sources.py` 已經有七個 handler，
其中好幾個**合法地**寫 `authority="accepted"`（`_decision`、`_ticket`）。
把 provider handler 放進去，這個 gate 就無法用 grep 表達——
它會需要一個 AST gate 來分辨「哪個函式裡的字串」。

於是：`services/knowledge/provider_sources.py`（新檔），
`_HANDLERS` 從那裡 import 兩個 handler。**檔案邊界就是 gate 的邊界。**

`verified` 為什麼也不給：`verified` 在這個系統裡的意思是
「Cliora 的驗證機制跑過並通過」（`sources.py:393` 讀 `report.source == "machine_verified"`）。
一個 provider 的 CI 綠燈不是 Cliora 的驗證。**十級 authority 的價值全部來自於每一級只有一個意思。**

### D123 — `HD-06` 兩個 revision 的分界（補充）

```text
0045  ── 可逆 ──────────────────────────────────────────────────────
      ADD COLUMN tasks.legacy_blocked_at TIMESTAMPTZ NULL
      UPDATE  stage='blocked' 的卡 → 推導出的 stage
                                   + is_blocked = true
                                   + blocking_reason = 推導值 or 'unknown'
                                   + legacy_blocked_at = now()
      三個寫入點改成寫 is_blocked（run_reaper.py ×2、runs.py ×1）
      downgrade: legacy_blocked_at IS NOT NULL 的卡 → stage='blocked'
                 —— 完全還原，因為那一欄就是為此存在的

0046  ── 不可逆 ────────────────────────────────────────────────────
      ALTER ck_tasks_stage: 五值，'blocked' 移除
      downgrade: 把 'blocked' 加回 CHECK
                 —— **值域還原，資料不還原**：0046 之後才被阻塞的卡
                    沒有 legacy_blocked_at，退版後它們是 is_blocked 而不是 stage
```

**退回去失去什麼**（要進 release note）：

| 退到 | 失去 |
|---|---|
| `0045` | 什麼都沒失去 |
| `0044` | `legacy_blocked_at` 與三個寫入點的行為回到 stage——**`0045` 之後新阻塞的卡的 `blocking_reason` 消失** |
| `0043` | provider 的兩個 source type 與它們的 source／chunk 全部 drop（可逆但要重新 ingest） |

**go／no-go 的具體條件**：

```text
☐ beta.1 已部署在一個有真實資料的環境
☐ scripts/px/ambiguous-report.py 跑過並產出檔案
☐ 檔案裡 reason='unknown' 的卡全部被人歸類（歸類結果寫回 report）
☐ 一個具名的人簽「這份 report 我看過」
```

**四項任一未達 → `HD-06` 整張跳過**，並在 ADR 0040 的修訂寫下
「本期不還，因為前提 N 未達成」以及**下一次的落點**。
[D139](#d139) 是這一條的紀律：**留白不是決定**。

### D124 / D125 — 為什麼一個新套件而另一個不新增

兩者的差別在於**替代方案的品質**：

| | 視覺回歸 | a11y |
|---|---|---|
| 替代方案 | Playwright **內建** `toHaveScreenshot`（1.61.1 已有） | 人工 audit |
| 替代方案的問題 | 沒有問題——內建的就夠 | 一份 markdown 在下一次改版時沒有任何東西會說它過期 |
| 結論 | **不新增套件** | **新增一個 devDependency** |

**這一段的意義**：「不新增套件」不是一條原則，是一個**在替代方案夠好時成立的偏好**。
把它當成原則的下場是用一份人工文件冒充一個回歸套組。

### D125 — 見上一節

`@axe-core/playwright` 的取捨與 D124 是同一個判斷的兩面，全文在
[`00`](./00-execution-plan.md) §0.1，取捨的對照表在上一節。

### D126 — `/board` 與 `?tab=` 為什麼處置不同（補充）

`00` §0.1 給了裁決，這裡給那條分界線的一般化：

```text
消費者是程式碼    → grep 得到零 → 可以直接刪
消費者是連結      → grep 不到   → 只能量，量到零才刪
```

`/board` 是第一類：`getBoard()` 有零個呼叫點，一次 `grep` 就是證明。
`?tab=` 是第二類：它的消費者在書籤、聊天記錄與別人的文件裡，
而那個集合**沒有任何靜態分析能列舉**。

**這條線值得寫下來，因為它會再用到。** `legacy_blocked_at`（[D123](#d123)）
在 `rc` 之後要移除，而它屬於第一類。`/dashboard` 的別名屬於第二類。
把「哪一類」先問清楚，可以避免一個相容層因為「不確定有沒有人在用」而永久存在——
那是相容層最常見的死法，而它的名字叫做**沒有人量過**。

~~實作：`legacy_route_hit_total{route}`，刪除條件「連續一個 release window 為 0」。~~

> **☒ 實作時發現這個機制做不出來（2026-08-28，`HD-07`）。**
> `?tab=` 的 redirect 跑在 vue-router 裡，而 SPA 是 **nginx** 送的
> （`deploy/nginx/nginx.conf` 的 `location /`）——FastAPI **從來不會被要求** `/projects/:id?tab=board`。
> 所以 `app/metrics.py` 裡沒有任何東西可以增加那個 counter。
>
> **而照計畫加下去的後果比不加更糟**：它會產生一個永遠是 0 的指標，
> 讀起來像「沒有人在用」——一個由儀器自己製造出來的、最強的刪除理由。
> 這正是 `plan/26` D97（沒有 raise 點的 machine code）換一頂帽子，
> 而且更危險，因為一個空的指標**會被相信**。
>
> **改為：宣告而不是量測。** `beta.2` 的 release note 寫明 `?tab=` 於 `rc.1` 移除；
> `rc.1` **不論使用量**都移除，因為使用量在這個系統內部觀察不到。
> 要證據的人去 nginx access log：`grep -c 'tab=' access.log`——
> 寫下來是因為「去看 log」不是一個計畫，除非有人說了是哪個 log、哪個字串。
> 全文在 ADR 0044 §4。
>
> **`/dashboard` 的別名屬於同一類**，先前歸錯類了。

### D138 — 波次順序與 `HD-15`（補充）

`00` §0.1 給了裁決，這裡給它與 `plan/26` D115 的差別。

D115 加的是**一個新波次**（波次 0），因為 `beta.1` 的前端工作全部排在十張後端 ticket 之後。
D138 做的是**重排既有波次**——把 a11y 與視覺回歸從最後移到第一，
因為它們**不依賴本期任何新東西**：跑在既有 `beta.1` 前端上，不等 tag、不等簽名、不等 provider。

**這件事本來就是可以先做的，而它排在最後只是因為上游的 ticket 順序是按主題分組的。**
一個按主題分組的清單讀起來整齊，執行起來會把所有不需要等的工作排在需要等的工作後面。

`HD-15` 則是新增，理由與 D115 的第二半相同：
一個「PR 合了會進 knowledge」的能力，如果沒有一個地方看得到它發生了，
**它與沒做的差別只有測試看得出來**。

## 2. B 類十一項

### D127 — 負載測試的形狀與 2000 卡的固定資料集

**現況**：`scripts/px/measure-work-api.py:22` 明寫「Measured against the service functions
rather than over HTTP: what is being sized is the query and the derivation,
and an ASGI round trip would add the same constant to every number」。
而 `scripts/cv/seed-dataset.py` 是 **200** 卡。

**決定**：
1. **量測沿用 service-level 形狀**，因為要量的還是查詢與推導。
2. **並發那一項例外**：`work-counts` 的並發（10／50／100）**必須走 HTTP**，
   因為要量的正是連線池與 worker 的競爭，而那在 service 層看不到。
3. 新增 `scripts/hd/seed-large.py`，**不改 `seed-dataset.py`**——
   200 卡那組是 `alpha.2`／`alpha.3`／`beta.1` 三期量測的基準，改它等於讓三期的數字失去對照。

**規模**：2000 卡、5000 knowledge source、20000 chunk、50 個 repository、
一條 200 節點的相依鏈（因為相依鏈的深度是 `blocking_counts()` 的成本來源）。

**不同意的話**：若把 2000 卡量測也做成 HTTP，數字會被 uvicorn 的 worker 數綁住，
而那個數字在 compose 與 Railway 上不同——於是「2000 卡上 P95 是多少」會有兩個答案。

### D128 — reconcile 節奏與速率上限

| 參數 | 值 | 為什麼 |
|---|---:|---|
| provider reconcile 間隔 | **300 秒** | 沿用 `worker.py:49` 的 `RECONCILE_INTERVAL_SECONDS`。**同一個迴圈、同一個 advisory lock**，不新增第二個背景任務 |
| 每 repository 每輪 GET 數 | **≤ 3** | PR 清單、release 清單、以及一個 PR 的詳情。三個是「一輪能問完」的最小數 |
| 每 repository 每小時 GET 上限 | **≤ 36** | 300 秒 × 12 輪。**從 `project_repositories.provider_synced_at` 推導**，不建計數表——`repo.py:255` 的同一個論證：「a sync that changed nothing writes nothing, so this bounds the syncs that *cost* something」 |
| 失敗退避 | 連續 3 次失敗 → 該 repository 停止同步 | 並寫 `provider_sync_error`，在設定頁顯示。**不是無限重試**——一個被撤權的 token 會讓迴圈永遠在燒配額 |

### D129 — provider token 沿用既有機制，不新增 kind

`services/secrets.py:44` 的 `KINDS` 已有 `provider_token`，
`UNDELIVERABLE_KINDS`（同檔 `:48`）確保它**永遠不會下放到節點**，
`project_repositories.provider_token_secret_id`（`models.py:1155`）是 per-repository 的欄位。

**本期一行都不改。** `provider_reads.py` 用 `SecretService.provider_token()` 取值，
與 `deliveries.py:224` 同一個呼叫。

**輪替**：沿用既有 secret 的更新路徑。SR-4 的「輪替」那一項因此是
**一個既有機制的回歸測試**而不是新工作：換掉 secret → 下一輪 reconcile 用新值 → 舊值不再出現在任何地方。

### D130 — 不新增 RBAC 動作

provider 同步的開關是 `projects.provider_sync_enabled`，
寫它需要 `project.update`（既有動作）。**27 個動作不動。**

**不同意的話**：一個 `project.provider_sync` 動作要進 `ALL_ACTIONS`、
三個角色的矩陣、一個 migration 的 seed（`0022`／`0030`／`0034` 的形狀）與 RBAC 測試矩陣。
而它保護的東西與 `project.update` 完全同一級——**改專案設定**。

### D131 — contract 與 daemon 都不動

本期是 Central ＋ 前端 ＋ 資料。`GATE-PX-CONTRACT-FROZEN` 與
`GATE-PX-NO-DAEMON-DIFF` 沿用（改名 `GATE-HD-*` 或保留 `PX` 名稱都可以，
**但基線要換**——`HD-00` 負責）。

### D132 — provider source 的保留與 tombstone

沿用 ADR 0038 §6：knowledge 沒有 retention override，`active=false` 與 `deleted_at` 說不同的事。

**兩條 provider 特有的規則要明寫**：

| 情境 | 處置 |
|---|---|
| PR 被關掉但沒合併 | `authority` 維持 `discussion`，`active=false`。**不 tombstone**——「這個提案被否決了」是一個值得留下的事實 |
| Release 被刪掉 | `deleted_at` 設值，`active=false`，**內容保留**。一個被撤下的 release 曾經存在過，而引用它的 context pack 要能說「這個來源後來被刪了」（`models.py:2046` 的同一個論證） |
| Repository 從專案移除 | 該 repository 的全部 provider source **tombstone**（`deleted_at`），與 `repo_doc` 的處置一致 |
| `provider_sync_enabled` 關掉 | **什麼都不做**。資料留著、不再更新。與 `knowledge_enabled` 同一個形狀——關掉是「停止花錢」不是「刪除」 |

### D133 — 大 Project 只加 metric 與 EXPLAIN

**不做**：分割表、改 `BATCH=32`、改 `INTERVAL=3.0`、加第二個 worker 種類。

**理由**：這四項都需要一個真實的大 Project 才知道要調哪一個，
而本期手上只有一個造出來的 2000 卡 fixture。
**在一個 fixture 上調的參數會量到 PostgreSQL，量不到工作負載。**

**做**：六個 metric（[`06`](./06-scale-and-observability.md) §4）與六個熱查詢的 `EXPLAIN`。
量出來的數字進 release note 的 known limitations，
形式是「2000 卡時 X 是 Y；超過這個量沒有量過」。

### D134 — 十級 authority 的量測只記 metadata

**量什麼**：每一級在 context pack 裡被 cite 的次數（十個 counter，label 只有 authority 名）。

**不量什麼**：被 cite 的內容、哪個專案、哪個使用者。
`metrics.py:1` 的 module docstring 已經寫過原因：
「metrics 是唯一沒有 redaction 的 sink」。

**判準**：若有任何一級在一個 release window 內是 **0 次**，那一級要不要合併就有了對照組。
`reviewed` 這一級是本期第一次有寫入者，所以它是這個量測的第一個真實案例。

### D135 — `task wait` 的 120 秒由 `HD-11` 順便收集

`daemon` diff 為零，所以這一項只能**觀察**：十六條旅程跑的時候，
記下每一次 `task wait` 實際等了多久、有沒有撞到上限。

**不改 daemon**——一個沒有資料支撐的常數調整只是換一個沒有資料支撐的常數。

### D136 — query 層的維護成本以「改了幾次」量

`plan/26` D100 造了 `modules/work/queryCache.ts`。上游的未量測項 #3 是
「300 行自製 query 層的維護成本」，排在 `beta.2`。

**量法**：本期結束時數 `git log --oneline -- frontend/src/modules/work/queryCache.ts`
的筆數，並逐筆寫「為什麼改」。

**判準**：若其中有任何一筆是「為了讓某個畫面能用而在快取層開一個特例」，
那就是「自製」的成本開始顯現的訊號，而它要進 `v2.1.0` 的 discovery。
**若一次都沒改，那也是一個答案**——而且是好的那一個。

### D137 — 死碼與過期敘述列成 ticket

四處：

| 位置 | 問題 |
|---|---|
| `api/http/work.py:3` | module docstring 說「Also still the home of the wave-0 side-car, `GET /projects/{id}/board-attention`」——**那個路由已經不在 `@router.get` 清單裡了** |
| `api/client.ts:348` | `getBoard()` 有零個呼叫點 |
| `db/models.py:796` | `stage` 沒有 `CheckConstraint`，而 `ck_tasks_stage` 在資料庫裡（`0023_task_board.py:378`）。**讀 model 看不到值域** |
| `services/process.py:46` | `LANE_ORDER` 含 `blocked`，而 `HD-06` 之後那個值不再是一個 stage |

**為什麼列成 ticket**：`plan/26` §6 的那一段
（「一句寫錯的理由比一個空著的核取方框更難發現」）講的就是第一處那種東西。
一個說謊的 docstring 會讓下一個人去找一個不存在的路由，
而它不會讓任何測試變紅。

### D139 — `HD-06` 若跳過，要寫「不還」

`research/03/12` §3.3 已經預告過這一條：

> 若 `beta.2` 決定不還，那要是一個明確的決定並記在 ADR 0040 的修訂，
> 而不是「後來就沒人提了」。

**本期把它變成一個出口條件**（[`09`](./09-verification-and-exit.md) §5 第 41 項）：
ADR 0040 的修訂區塊**必須非空**，內容是「還了」或「不還，因為 X，下一次落在 Y」。

### D140 — known limitations 至少四條

`research/03/00` §7 寫著「空的清單需要解釋，不是好消息」。
本期已經知道的四條，[`09`](./09-verification-and-exit.md) §7 列出，
包含 pull 模型的 300 秒新鮮度、2000 卡以上未量測、
八個視覺畫面之外沒有回歸、以及 `HD-06` 若跳過的技術債。

## 3. ADR 清單

| ADR | 標題 | 對應決策 | 里程碑 |
|---|---|---|---|
| **0043** | Provider ingestion：pull 模型、信任邊界、authority 天花板（**webhook 設計併記、標未實作**） | ★ D120、D119、D121、D122、D128、D129、D132 | `beta.2` |
| **0044** | `/board` 的日落與 `BoardCardDTO` 量測紀錄的歸檔 | D126 | `beta.2` |
| **0040 修訂** | Stage 過渡的還款結果 | D123、D139 | `beta.2` |

**`0043` 為什麼把 webhook 一起寫**：ADR 記的是**當時的決定與被放棄的選項**。
一個只寫 pull 的 ADR，會讓下一個人以為 webhook 沒被考慮過，
於是他要重新做一次同樣的分析。**寫下來並標記「未實作」的成本是兩段文字。**

## 4. 需要同步修訂的文件

| 文件 | 改什麼 | 誰 |
|---|---|---|
| `research/03/README.md` | 規劃基準表六處（HEAD、tag、migration head、ADR 空號、requirements 數、tokens 數、**SCOPE-013 的誤引用**） | `HD-00` |
| `research/03/01` §3 | D46 標為已裁決，並指向 ★ D120 | `HD-00` |
| `research/03/10` §4 | SR-4 的五項改為 pull 模型下的兩項 ＋ 三項改寫 ＋ 兩項新增 | `HD-01` |
| `research/03/12` §2 | migration 表加 `0044`／`0045`／`0046` 並標可逆性 | `HD-01`、`HD-06` |
| `research/03/12` §6 | 十二張 ticket 改為十六張並標明合併與新增 | `HD-00` |
| `research/prd.md` | `FR-PROV` 節 ＋ AC anchor；a11y 的 NFR 一條 | `HD-01`、`HD-04` |
| `traceability/requirements.json` | `FR-PROV-001`… ＋ 一條 NFR，`lifecycle: proposed` | `HD-01`、`HD-04` |
| `docs/adr/0040-*.md` | 修訂區塊（D139） | `HD-06` |
| `plan/26/12` §0 | 十四處回寫**再核對一次**是否仍然正確 | `HD-13` |
