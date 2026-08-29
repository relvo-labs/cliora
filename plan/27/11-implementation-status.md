# 11 — 實作進度與證據

> **本檔在實作期間逐步回填。與計畫不同時以這裡為準，並回寫計畫。**
>
> **目前狀態（2026-08-29）：十六張 ticket 全部實作完成，八個波次走完；
> 42 項出口條件為 35 ☑／1 ◐／6 ☐。**
>
> `scripts/hd/evidence.sh` 九步一次跑完：**前八步全綠**——
> 十七個 gate、七項靜態檢查、backend **2,154 passed**、frontend **852 passed**、
> traceability、兩次演練、a11y、視覺回歸、七個 `EXPLAIN`。
> **第九步兩個 FAIL，兩個都是人的簽名**（SR-4、a11y 六項人工）。
>
> **舊十六條旅程本體已在本期程式碼上重跑並全綠。** 真 daemon：J1 **36／36**、
> J4 13／13、J15 8／8、J5/J6/J8/J9 39／39、J11–J14 擴充後 34／34；browser：
> J1a/J3/J7 3／3、J2/J10/J16 flag on/off 全綠。provider 的 J13/J14 擴充也已在
> real daemon stack 通過 9／9、11／11；J1 亦已用真 GitHub merged PR 完整通過；
> J12 production-reader HTTP lifecycle 亦為 9／9、J16 disabled transport trap 為
> reader 0／GET 0；J17/J18 controlled event＋Chromium journey 亦已通過。
>
> **本期實跑找到並修好的五個缺陷**：
> `alpha.3` 的 trigram 通道對它宣稱要服務的查詢回傳零筆（§2.10）、
> `style.md` 的四個語意色六期以來沒有一個能當小字用（§2.6）、
> `MetricCard` 的 `aria-label` 從來沒有生效過（§2.5 的連帶），以及一小時
> provider 觀測找到的假 lag metric 與 session advisory-lock 漏出（§2.21）。
>
> **出口仍有六項未達成**：人工 a11y 三項（checklist／實際聽到的字／J2 錄影）、
> CI 視覺綠燈、SR-4 具名簽核、`v2` → 上游人工核准。另有一項部分達成：
> Railway 演練。真 300 秒排程下的 provider event-to-reconcile P95 已關閉。

## 0. 要回寫上游的九處

寫這份計畫時核對程式碼發現 `research/03/` 有六處已經過期、不精確或缺漏，
**2026-08-27 的簽核又讓三處變成過期**（第 2b、2c 與第 2 項的 `K1` 一列），合計九處。
**`HD-00` 負責回寫**，形式是**保留原文並劃掉**而不是覆蓋——
下一個讀者要看得到當時寫的是什麼，否則他無從判斷這份文件還有哪裡可能同樣過期。

**這是第三次。** `plan/25` §0 與 `plan/26` §0 各做過一次，
而三次的理由完全相同：一份被下一個讀者當成事實的規劃文件，它的錯誤會被繼承。

| # | 文件 | 原本 | 應為 |
|---:|---|---|---|
| 1 | ☑ `research/03/README.md` 規劃基準表 | `v2` HEAD `3e503de`；migration head 0042；ADR「空號只剩 0040 與 0042」；requirements 189 條／28 family；tokens 62 | HEAD **`5854325`**（ahead 91／behind 0）；migration head **0043**；ADR **`0043` 之下沒有可用空號**（`plan/26` 用掉 0040 與 0042；本期從 0043 起用）；requirements **201** 條／**29** family；tokens **72**（不是 73——一個較鬆的 grep 會把 `--attention-failed` 的 `var()` 換行數成一列） |
| 2 | ☑ 同上，執行計畫表 | `P1 \| plan/26/ \| 已建立`；`E1 \| plan/27/ \| 未建立`；`K1` 那一列寫「出口條件 **26／28**，缺 Railway `pg_trgm` 驗證**與 SR-2 簽核**」 | `P1` 改「**已實作，出口 40／40，未 tag**」；`E1` 改「**已建立**（本目錄，2026-08-25）」；**`K1` 改「出口 27／28，只缺 Railway `pg_trgm`」**——SR-2 已於 2026-08-27 簽核 |
| 2b | `research/03/README.md` §「建議使用方式」第 6 條與 §「規劃基準」的 tag 列 | 隱含 `alpha.3`／`beta.1` 都還在等簽核 | **兩份審查都已簽核（2026-08-27）**，連同 PR #45；**兩個 tag 仍未建立**。擋 tag 的東西從「等一個人」變成「一次 Railway 量測」 |
| 2c | `research/03/00` §2 的三層版本表與 §6 freeze checklist | 未提 ADR 狀態 | **九份 `proposed` ADR 已於 2026-08-27 全部轉 accepted**（0029／0031 的 amendment、0032／0033／0034、0038／0039、0040／0042）。其中 0029–0034 五份是 `alpha.1` 時代的欠款，而 **§6 的 freeze checklist 十個方框仍然全空** |
| 3 | **`research/03/README.md` 與 `01` §3** | 「Central 對外連線只有 `httpx`，只有 `services/providers.py` 一個模組（**SCOPE-013**）」 | **SCOPE-013 的實際文字是「不由平台自建對外反向代理；埠轉發以第三方整合交付」**。單模組那件事是 `GATE-KN-NO-NEW-EGRESS (httpx)`，**一個 gate 而不是一條需求**。三處引用要改 |
| 4 | `research/03/01` §3 的 ★ D46 | ☐ 未裁決 | **☑ 已於 2026-08-25 裁決**：由 ★ [D120](./01-decisions-and-governance.md#d120) 一併關閉（落在 `beta.2`，形狀是 pull）。§3 的標題「仍需你裁決（原四項，**現只剩 D46**）」要改成「四項全部已裁決」 |
| 5 | `research/03/10` §4 的 SR-4 | 五項，三項是 webhook 專屬 | pull 模型下**兩項保留、三項改寫、三項新增**（[`02`](./02-provider-ingestion.md) §8） |
| 6 | `research/03/12` §2 migration 表 ＋ §6 ticket 表 | `0044`／`0045` provider sync（待 ADR 0043）；十二張 ticket | `0044` provider、**`0045` stage 資料（可逆）、`0046` 收 CHECK（不可逆）**；**十六張** ticket（[`00`](./00-execution-plan.md) §2） |

還有**三處是規劃層的缺口而不是錯誤**，已在本目錄補上並要回寫：

| # | 缺口 | 補在哪 |
|---:|---|---|
| 7 | 上游沒有提到 `GATE-DV-PROVIDER-VERBS` 與 `GATE-KN-NO-NEW-EGRESS` 對 provider 讀取形成夾擊，而 `HD-02`／`HD-03` 照字面寫會撞到其中一個 | [D119](./01-decisions-and-governance.md#d119)、[`02`](./02-provider-ingestion.md) §3 |
| 8 | 上游說 `HD-05` 沿用 `plan/19` 的 baseline 機制，而那個機制**不存在**（`toHaveScreenshot` 在 `frontend/` 全樹為零） | [D124](./01-decisions-and-governance.md#d124)、[`05`](./05-visual-regression.md) §1 |
| 9 | 上游沒有提到 `ck_tasks_stage` 在資料庫裡但不在 ORM，也沒有提到三個 `stage='blocked'` 寫入點在 `GATE-DV-SINGLE-DONE-PATH` 的視野外 | [D123](./01-decisions-and-governance.md#d123)、[`03`](./03-stage-final-migration.md) §2 |

## 1. 開工前的裁決單

### A 類 — 擋開工

> **☑ 九項全部於 2026-08-25 裁決，全部採納計畫的答案。**
> 各項全文（含「不同意的話會怎樣」）保留在 [`00`](./00-execution-plan.md) §0.1
> 與 [`01`](./01-decisions-and-governance.md) §1——**裁決之後那一段仍然保留**，
> 它是日後想推翻某一項的人唯一的參考。

| # | 決定 | 狀態 | 裁決日 | 一起接受的代價 |
|---|---|---|---|---|
| **★ D120** | **只做 pull，不做 webhook** | ☑ **採納** | 2026-08-25 | 新鮮度 300 秒；webhook 只在 ADR 0043 裡（已設計、未實作） |
| D119 | `provider_reads.py` 是第二個 httpx 模組 | ☑ **採納** | 2026-08-25 | 兩份 timeout／allowlist／redaction，刻意重複 |
| D121 | 兩個新 source type ＋ `EXTERNALLY_TRIGGERED` | ☑ **採納** | 2026-08-25 | 覆蓋率測試從斷言值變成斷言兩個宣告一致 |
| D122 | provider authority 天花板 ＋ 專屬檔案 | ☑ **採納** | 2026-08-25 | 真的被當規格讀的 PR 描述永遠低一級 |
| D123 | `HD-06` 拆 `0045`／`0046` ＋ go／no-go | ☑ **採納** | 2026-08-25 | 多一個過渡欄位、多一個 revision；**go／no-go 可能導致整張跳過** |
| D124 | `toHaveScreenshot` 八畫面、門檻 0.01 | ☑ **採納** | 2026-08-25 | 八個畫面之外沒有回歸 |
| D125 | `@axe-core/playwright` 是唯一新套件 | ☑ **採納** | 2026-08-25 | 「不新增前端套件」（D56）這條線破一次 |
| D126 | `/board` 刪；`?tab=` 保留到 `rc.1` | ☑ **採納** | 2026-08-25 | 一個寫得很好的釘死測試要被刪，docstring 搬進 ADR 0044 |
| D138 | 波次 1 是 a11y；新增 `HD-15` | ☑ **採納** | 2026-08-25 | `HD-15` 是唯一沒有上游對應的功能 ticket |

**★ D120 裁決之後固定的四件事**（[`00`](./00-execution-plan.md) §0.1）：
`0044` 沒有 `provider_deliveries` 表、`api/http/` 不新增路由檔案且連 import 都不行、
`secrets.py` 留在禁區、**「300 秒」成為一個要用 `provider_reconcile_lag_seconds` 證明的產品承諾**。

### B 類 — 依計畫執行

`D127`…`D137`、`D139`、`D140`：☐ 未裁決（依計畫執行，有異議時記在 §2）。

### 從上游繼承、仍未關閉

| # | 決定 | 狀態 | 影響 |
|---|---|---|---|
| ☑ ★ D46 | provider 同步落在哪一版 | ☑ **已關閉**（2026-08-25） | 由 ★ D120 一併關閉：落在 `beta.2`，形狀是 pull。**上游 `research/03/01` §3 的待裁決項至此清空**——`HD-00` 負責回寫 |
| ADR 0040 | stage 只做投影是過渡 | 過渡中 | `HD-06` ＋ [D139](./01-decisions-and-governance.md#d139) |
| D118 | `/board` 由 `beta.2` 刪除 | 待執行 | [D126](./01-decisions-and-governance.md#d126) |

### 前置條件

| ☑/☐ | 事項 | 擋哪些波次 | 狀態 |
|---|---|---|---|
| ☑ | SR-2 具名簽核 | — | **2026-08-27**，`docs/security-review-v2k1.md` §6 |
| ☑ | SR-3 具名簽核（**兩列**） | — | **2026-08-27**，`docs/security-review-v2p1.md` §6 |
| ☑ | PR [#45](https://github.com/Lei-k/cliora/pull/45) 核准 | — | **2026-08-27** |
| ☑ | 九份 `proposed` ADR 轉 accepted | — | **2026-08-27** |
| ☑ | **`plan/25` 的 `pg_trgm` 驗證** | — | **2026-08-28 關閉**（`HD-00`）。不是量測出來的，是發現判準是資料庫 `CREATE` 權限而不是 superuser |
| ☐ | `v2.0.0-alpha.3` annotated tag | **2、3** | 條件 **28／28 全綠**；tag 是一個人的動作 |
| ☐ | `v2.0.0-beta.1` annotated tag | 4 | 條件 **40／40 全綠**；tag 是核准之後的另一個動作 |
| — | **波次 0、1、5 不被擋且無前序依賴 → 現在可開工** | — | 六張 ticket |
| — | 波次 6、7 不被前置條件擋，但等波次 4、5 的產物 | — | — |

**簽核之後這件事反過來了。** 開工前擋著波次 2、3 的是兩個簽名 ＋ 一次量測；
現在**只剩那次量測**——一個下午的工作，卡著兩個波次。
它記在一份**已簽核**的安全審查的 §6 裡，而已簽核的文件很少被重讀，
所以它同時出現在這裡、`HD-00` 的 ticket 描述、
以及 [`09`](./09-verification-and-exit.md) §7 的 known limitations。

## 2. 與計畫的差異

> 實作期間逐項回填。格式沿用 `plan/25`／`plan/26` §2：
> **標題一句話說出差異，內文說出「計畫怎麼想、實際是什麼、為什麼」。**
>
> 帶 ★ 的是「所有測試都是綠的，但東西是錯的」那一類。
> **帶 ★★ 的是實跑才找到的那一類**——`plan/26` 有五條，
> 而它們全部在同一天被找到，在那之前那些實跑被記成「需要這個環境沒有的東西」。
>
> **本期預先指出三個最可能出現 ★ 的位置**（寫計畫時的推測，未實測）：
>
> 1. `search.py:_HALF_LIFE_DAYS` 漏掉新型別——`.get(…, 90.0)` 讓 release 靜默拿到 90 天而不是 365
> 2. `knowledge_jobs` 的 `source_type` CHECK 被漏掉（**兩張表都有**，而只有一張會在測試裡被寫到）
> 3. `0046` 的 downgrade 在**沒有** `legacy_blocked_at` 的卡上「成功」——因為它只改值域，不檢查資料

### ★ 2.20 D132 寫進了計畫與 ADR，卻沒有一條寫入路徑實作它

**計畫怎麼想**：closed-unmerged PR 留下但退出預設檢索、上游刪除 release 要
tombstone、repository 移除時三種 derived source 一起 tombstone。

**實際是什麼**：provider pass 只 upsert provider 回傳的列；不存在於 release list 的列
完全不處理。PR handler 也沒有接 `state`，所以 closed-unmerged 仍以 `active=true` 寫入；
repository delete 直接刪父列，三種 source 沒有 FK，因而全部留成「原始仍存在」。所有舊測試
都是新增／成功／三次失敗，沒有一條走 retention 表的三個分支。

**補齊**：`ExtractedSource.active` 讓 handler 宣告可逆的 inactive；release reconcile 只在
provider page 足以證明缺席的時間窗內 tombstone，滿 50 筆時不誤刪 pagination 隱藏的歷史；
repository delete 依 project＋三型＋UUID prefix tombstone，保留 source id／本文並關閉 chunk。
五條新 DB 測試逐一證明 closed PR、release deletion、pagination 邊界與 repository removal。

### ★★ 2.21 一小時觀測先量出假零，再讓 session lock 漏到第七輪

**計畫怎麼想**：`provider_reconcile_lag_seconds` 能證明 event 到 ingest 的 300 秒承諾，
既有 advisory lock 能讓多 replica 安全 single-flight。

**實際是什麼**：第一版在同步寫回 `provider_synced_at=now` 後才量
`now - provider_synced_at`，所以無論 provider event 多舊都接近零；histogram 的預設 bucket
又只到 10 秒，根本無法計算 300 秒 SLO。修好量測後跑真 300 秒 cadence，舊的
session-level `pg_try_advisory_lock` 在 `commit()` 後把持鎖連線還給 pool，再由可能不同的
連線執行 unlock；第六輪後 PostgreSQL 報 `you don't own a lock`，第七輪永遠拿不到鎖。

**補齊**：lag 只收 live cursor 後實際改變的 entity `updated_at → ingested_at`，首次
backfill 不算；histogram 加 300／1800／7200 秒 bucket。reconciler 改用
`pg_try_advisory_xact_lock`，由 commit／rollback／connection close 釋放，並加實 PostgreSQL
同時執行與 commit 後再取得測試。重新從零觀測 **3613.071 秒、12 輪、24 event**，P95
**291.013 秒／300 秒**，24／24 落在 300 秒 bucket；前次 failure point 後再完成六輪。

### ★ 2.1 `legacy_route_hit_total` 做不出來，而照計畫加下去會比不加更糟

**計畫怎麼想**（[D126](./01-decisions-and-governance.md#d126)）：`/board` 的消費者是程式碼、
grep 得到零就刪；`?tab=` 的消費者是連結、grep 不到，所以**加一個計數器**，
連續一個 release window 為 0 才刪。

**實際是什麼**：那個計數器**沒有地方可以被增加**。`?tab=` 的 redirect 跑在
`router/index.ts` 的 vue-router 裡，而 SPA 是 **nginx** 送的
（`deploy/nginx/nginx.conf` 的 `location /`）——FastAPI 從來不會被要求
`/projects/:id?tab=board`。我一度已經把 `LEGACY_ROUTE_HIT_TOTAL` 寫進 `metrics.py`，
然後才去查 SPA 是誰送的。

**為什麼這比「少一個指標」嚴重**：它會產生一個**永遠是 0 的計數器**，
而那個 0 讀起來是「沒有人在用 `?tab=`」——一個**由儀器自己製造出來的刪除理由**。
`plan/26` 的 D97 說「一個沒有 raise 點的 machine code 是文件不是行為」；
這一個更糟，因為一個空的 machine code 不會被引用，而一個空的指標**會被相信**。

**改成什麼**：宣告式日落。`beta.2` 的 release note 寫明 `?tab=` 於 `rc.1` 移除，
`rc.1` **不論使用量**都移除。要證據的人去 nginx access log，
而「哪個 log、哪個字串」寫在 ADR 0044 §4——「去看 log」不是一個計畫。

**連帶**：`/dashboard` 的別名先前被歸成「可量測」那一類，**歸錯了**，同樣是 client-side。

### 2.2 兩個 e2e 測試在 `beta.1` 就已經死了，而沒有東西說出來

`frontend/tests/e2e/tasks.spec.ts` 有一個
`the two queued waiting reasons remain different on the board`，
它驅動 `/projects/:id?tab=board` 並讀 `.waiting-copy`。
**兩者都在 V2-P1 隨 `ProjectDetailView.vue` 消失了**（`grep -rn 'waiting-copy' frontend/src` 為空）。

**它不會失敗，它只是不再跑。** e2e 需要一個 stack，而那個 stack
在刪除與現在之間沒有被跑過——所以一個瞄準已刪畫面的測試
與一個通過的測試在任何儀表板上長得一樣。

處置：刪除，並在原地寫下它守的性質現在住在哪三個會跑的地方
（`attention.ts` 的第 5、6 級文案、`quickFilters.ts`、旅程 J15）。
同檔的 `M1 records p50 and p95` 改指向 `work-items` 並在輸出加一個
`endpoint` 欄位——**跨日落的兩份數字不可比**，而一個沒有這個欄位的
`m1-live.json` 會被拿來跟舊的比。

### 2.3 十個「既有測試失敗」全部是環境，而其中九個的症狀會被讀成缺陷

跑基準線時 `pytest tests` 有 11 個失敗，其中 10 個在**未改動的樹**上一樣失敗。
原因兩個，第二個值得記：

1. `cliora` 資料庫不存在（`test_run_reaper` 六個）——建庫並 migrate 即可。
2. **`AuthzDenialAuditMiddleware._record` 用 `get_database()` 開自己的 session**，
   而不是 fixture 的。於是 `CLIORA_DATABASE_URL` 與 `CLIORA_TEST_DATABASE_URL`
   指向不同資料庫時，audit row 寫到一個、斷言讀另一個。
   **症狀是 `assert 0 == 1`，三個畫面之前有一行 `audit_write_failed` warning**
   ——讀起來像 audit chain 壞了，而它沒有。

兩者都寫進 `scripts/hd/env.sh`，因為下一個人會再撞一次。
**兩個環境變數指向同一個資料庫**是這個 repo 跑測試的必要條件，而它先前沒有寫在任何地方。

## 3. 波次進度

| 波次 | ticket | 狀態 |
|---|---|---|
| 0 | `HD-00`、`HD-07`、`HD-13` | ☑ **完成**（2026-08-28）。基準線、`/board` 整組刪除、九處回寫、四處死碼。詳見 §4 |
| 1 | `HD-04`、`HD-05` | ☑ **實作完成**（2026-08-28）。axe 0/0×8、八張 baseline ＋ 反向測試。**六項人工 checklist 未執行**，見 §6 |
| 2 | `HD-01` | ☑ **實作完成**（2026-08-28）。ADR 0043、`provider_reads.py`、migration `0044`、FR-PROV 四條 |
| 3 | `HD-02`、`HD-03`、`HD-15` | ☑ **實作完成**（2026-08-29 再稽核）。handler、reconcile pass、五個 metric、20 支 provider 後端測試 ＋ **`HD-15` 的四種同步狀態在真的畫面上跑過**（`artifacts/hd/local/w3/provider-sync-states.png`）；D132 lifecycle 見 §2.20 |
| 4 | `HD-06` | ☑ **實作完成**（2026-08-28）。`0045`／`0046`、三個寫入點、ADR 0040 修訂。在 3800 張真實形狀的卡上演練過 roundtrip |
| 5 | `HD-10` | ☑ **實作完成**（2026-08-28）。2000 卡 seed、七個 `EXPLAIN`、體積與成本。**找到一個 `alpha.3` 的檢索缺陷**，見 §2.10。provider queue 的那一半等波次 3 |
| 6 | `HD-08`、`HD-09` | ☑ **實作完成**（2026-08-28）。演練五步全綠（含 `pg_trgm` 邊界與 dump/restore）、rollback drill 六步全綠。**演練找到一個 `0046` 的真缺陷**，見 §2.18 |
| 7 | `HD-14`、`HD-12` | ☑ **文件與腳本完成**（2026-08-28）。SR-4、release note、`evidence.sh` 九步實跑。**三項開著**：SR-4 簽名、a11y 六項人工、十八條旅程 |

## 4. 每個波次的可看產出

[`00`](./00-execution-plan.md) §4b 的八列，逐波次回填。
**「這個波次沒有可看的東西」是一個要寫在這裡的事實**，不是一個可以略過的欄位。

### ★★ 2.18 `0046` 只在「已經跑過它」的資料庫上work，而只有從空的建一次才看得出來

`HD-08` 的演練從一個**空的**資料庫把整條鏈跑起來，第一步就紅了：

```
UndefinedObjectError: constraint "ck_tasks_stage" of relation "tasks" does not exist
```

原因是這個 codebase 的命名慣例把 `ck_%(table_name)s_%(constraint_name)s` 套在
**輸入**上，而 `0023` 建這個 constraint 時給的 `name` 已經帶了前綴：

```
0023: name="ck_tasks_stage"   → 實際名字 ck_tasks_ck_tasks_stage
drop_constraint("stage")      → 找 ck_tasks_stage           不存在
drop_constraint("ck_tasks_stage") → 找 ck_tasks_ck_tasks_stage  存在
```

**而我兩種都試過，並且把對的那個改成錯的**：第一版用了後者，
在 `cliora_hd` 上失敗（因為那個資料庫已經被前一次失敗的嘗試改過名），
於是我「修正」成前者——**而它之所以在那台機器上work，正是因為它已經跑過了**。

`0044` 的同一段看起來一模一樣而且是**對的**，因為 `0042` 給的 `name` 沒有前綴。
所以規則不是「一律傳裸名」，是「傳建立它的那個 migration 傳的東西」，
而唯一知道的方法是去讀它。`0046` 改用 raw SQL ＋ 兩個名字 ＋ `IF EXISTS`。

**測試套組抓不到這個**，因為測試資料庫也是遞增遷移上來的。
只有「從空的建一次」會抓到，而那正是 `HD-08` 存在的理由——
它在第一次跑就付清了自己的成本。

### 2.19 rollback drill 的第一版斷言了與文件相反的事

drill 的 step 3 原本斷言「被封鎖的卡會回到 stage」。它紅了，而**紅得對**：
seed 出來的卡是 `HD-06` 之後的形狀（直接寫 `is_blocked`），
從來沒有經過 `0045`，所以**沒有 `legacy_blocked_at`**——
downgrade 正確地不去猜它們。

那正是 ADR 0040 修訂裡寫的那條不可逆性。
斷言改成證明它，而不是要求它的反面：
**一個要求那些卡回來的 drill，是在要求 `0043` 拒絕做的那個猜測。**

### ★★ 2.17 視覺 baseline 的第一版釘的是一整頁豆腐字

八張 baseline 拍完、`GATE-HD-VISUAL-BASELINE` 綠了之後，
才在 `HD-15` 的截圖裡看到：**這個容器只有 DejaVu，沒有 CJK 字型**。
而這個 UI 的文字幾乎全是繁體中文。

所以那八張 baseline 釘的是一整頁 `□□□□`——版面對、字全是方框。
**那比沒有 baseline 更糟**：在這台機器上永遠過，
在任何有中文字型的機器上永遠失敗，而失敗訊息會說「版面變了」。

裝 `NotoSansCJK` 之後重拍。**真正的結論不是「裝了字型」**，
是 [`05`](./05-visual-regression.md) §5 那句「跑不起來就不要建這套」
比寫的時候更嚴格：**視覺 baseline 綁定的不只是瀏覽器，是整個字型環境**。
進 known limitations 第 4b 條。

**這一條是實跑找到的，而且是被另一張截圖找到的**——
視覺套組自己永遠不會報告這件事，因為它比較的是它自己拍的東西。

### 2.16 metric 的 label allowlist 在呼叫點擋下了一個新標籤，而它是對的

`provider_read_total` 第一版用 `outcome="ok"`／`"refused"`。
`_check_labels` 直接 raise：`outcome` 不在 allowlist 裡。

改用既有的 `status`。**一個想法兩個標籤名，是儀表板長出兩條本該是一條的序列的方式**——
而這個 allowlist 是在呼叫點而不是在 scrape 時擋下來的，
所以它是一個立刻失敗的測試而不是三個月後的一張圖。

`metrics.py` 的 docstring 早就說了理由（「a metric that silently loses its labels
looks like it is working」）；這是它第一次真的擋下東西。

### 2.13 `HD-06` 的 go／no-go：在本機資料上做，而那不是計畫說的那個

[D123](./01-decisions-and-governance.md#d123) 的四項前提，第一項是
「`beta.1` 已部署在一個有真實資料的環境」。**那個環境不存在**，所以嚴格照計畫應該跳過。

實際做的是**第三條路**，而它比跳過強、比假裝有生產資料誠實：
本機的 `cliora_hd` 有 **3800 張 `stage='blocked'` 且 `is_blocked=false`** 的卡——
那正是三個舊寫入點在 `0043` 之後產生的形狀，也正是 `0045` 要處理的族群。
不是造出來給 migration 看的，是 seed 走一般路徑寫出來的。

於是 `0045`／`0046` 在一個真實形狀、真實規模的族群上跑過完整 roundtrip：
3800 → `is_blocked` ＋ `legacy_blocked_at` → downgrade → **3800 完全還原** → 再 upgrade。

**推導結果全部是 `unknown`**，而那是誠實的答案：合成的卡沒有相依、沒有 run、沒有驗證。
一個產生出漂亮 reason 分佈的 fixture 會是在測 fixture 而不是測推導。

**仍然缺的是**：一份真實 report 被一個人讀過並歸類。那一項留著，
而它現在擋的不是實作而是**簽核**——程式碼、migration、測試、ADR 修訂都在了。

### ★ 2.14 兩個 migration 踩到同一個命名慣例陷阱

`op.drop_constraint("ck_tasks_stage", ...)` 會被 metadata 的 naming convention
再包一層，變成 `ck_tasks_ck_tasks_stage`——一個不存在的名字。
要傳的是**慣例的輸入**（`"stage"`），不是它的輸出。

`0044` 在 `knowledge_sources` 上踩了一次，一小時後 `0046` 在 `tasks` 上又踩一次。
**同一期兩次，就不是失誤而是這個 codebase 的一個性質**，兩個 migration 的註解都寫了。

### 2.15 固定資料集裡有 `blocked` 卡，所以它自己也 seed 不進去了

`0046` 收掉值域之後，`scripts/cv/seed-dataset.py`（三期的量測基準）
與 `test_work_items_size.py` 的 fixture 都插不進去——它們各有 20 張 `blocked`。

D127 說**不要改** `seed-dataset.py`，因為它是三期數字的對照組。
處置：**族群不變，只有寫法變**——那 20 張變成 `ready` ＋ `is_blocked=true`，
也就是 `0045` 對真實資料做的事。卡數、比例、seed 全部一樣，
所以三期的數字仍然可比。**只有「blocked 怎麼寫下來」移動了，而那正是 `HD-06` 的全部內容。**

### ★ 2.12 規劃時只找到兩個 gate，實際上有**三個**執行點

[D119](./01-decisions-and-governance.md#d119) 的「兩個 gate 夾擊」寫得對，但**數漏了一個**：
除了 `scripts/kn/gates.sh` 與 `scripts/dv/gates.sh`，
還有 `backend/tests/test_scope_guards.py::test_scope_013_central_does_not_proxy_to_a_node_http_service`
——**一個真正的測試，而且它才是 SCOPE-013 的實際守門人**。

規劃時我 grep 的是 `scripts/`，沒有 grep `tests/`。
新增 `provider_reads.py` 之後它紅了，訊息完全正確：
「an HTTP client appeared outside the provider adapter」。

**處置與 V2.4 當初做的一樣**：把規則收窄而不是放寬。
那個測試自己的註解記著這段歷史——V2.4 把「哪裡都不准有 HTTP client」
改成「只有一個模組」，並在同一步變得**更嚴格**（那個模組必須查 host allowlist）。
`beta.2` 改成兩個**具名**模組，並且同樣在同一步變嚴格：

- 兩個模組**各自**都要查 `provider_api_host_list`（不能一個繼承另一個檢查過的 client）
- 讀取模組裡不得出現 `"POST"`／`"PUT"`／`"PATCH"`／`"DELETE"`
- 用**名字清單**而不是數量：「恰好兩個」任兩個都滿足

**教訓**：規劃階段找執行點時只看 `scripts/` 是不夠的。
這個 repo 把不變式放在三種地方——gate script、AST gate、以及**普通測試**，
而第三種最容易在規劃時被漏掉，因為它不在名字裡帶 `gate`。

### ★ 2.9 擋了兩個波次六個星期的那一項，問錯了問題

`plan/25` 的出口條件第 17 項寫著「Railway 的 PostgreSQL 通常給非 superuser，**必須實測**」，
而 `CREATE EXTENSION` 需要 superuser 這個前提**對 `pg_trgm` 不成立**。

`pg_trgm` 的 control 檔寫著 `trusted = true`。PostgreSQL 13 起，
一個 trusted extension 可以由**任何持有資料庫 `CREATE` 權限的角色**安裝——
而 Railway 配給的使用者**擁有**它配的資料庫。所以那裡的預期結果是**成功**。

實測（PostgreSQL 16.14，三種角色）：

| 角色 | 資料庫 `CREATE` | `0041` |
|---|---|---|
| superuser | 有 | 成功 |
| **擁有自己的資料庫、不是 superuser** | 有 | **成功**——正是這一項假設會失敗的情況 |
| 只有 schema 權限 | 無 | 停在 preflight 的第二段訊息；管理員照訊息跑一次 `CREATE EXTENSION pg_trgm` 之後，`alembic upgrade head` 走到 `0043`，`gin_trgm_ops` 索引建起來 |

兩條拒絕路徑都跑過，兩條都給出它們該給的、可行動的訊息。
`docs/deployment-railway.md` 補上了那一節——**包含一行部署前就能跑的述詞**：

```bash
psql "$DATABASE_URL" -tAc "SELECT has_database_privilege(current_user, current_database(), 'CREATE');"
```

**沒有對真 Railway 跑過**，而那正是這一行述詞存在的理由：
它把剩下的未知（Railway 自己的 extension allowlist）縮成一次 `psql` 呼叫，
而不是一個期。

**值得單獨記的是時間**：這一項開了六個星期，擋著兩個波次，
而關掉它花的是一個下午——其中大部分時間在建三個測試角色。
「Railway 通常給非 superuser」是**真的，而且無關**，
兩者之間的距離就是那六個星期。

`test_pg_trgm_is_a_trusted_extension` 讓這個前提不會再漂走。

### 2.8 兩個同時跑的 `pytest` 會互相污染，而症狀讀起來像回歸

一次背景 run 還沒結束就啟了第二個，兩個都跑 `tests/db/`——
而那個套組共用一個 PostgreSQL 資料庫，沒有 per-worker 命名空間。

結果：**同一份程式碼，一次 73 failed，一次 54 failed。**
73 這個數字讀起來像一次大回歸；真正的線索是**它不穩定**。
單獨跑一次就回到全綠。

寫進 `scripts/hd/env.sh`：報了幾十個失敗時，
**先看 `pgrep -af pytest`，再看 traceback**。

### 波次 1（2026-08-28）

| 產出 | 證據 |
|---|---|
| 一份 axe 報告從紅到綠 | `artifacts/hd/local/w1/axe-before.json`（12 serious）→ `axe-after.json`（0／0，八畫面） |
| **八張視覺 baseline** | `frontend/tests/hd/__screenshots__/`，`GATE-HD-VISUAL-BASELINE (8 screens)` PASS |
| **反向測試**：改一個 padding → 兩個畫面紅 → 還原 → 綠 | `artifacts/hd/local/w1/visual-negative.md` |
| 四個語意色從「不能當小字」變成 AA | `research/style.md` §Success/Warning/Error/Info ＋ `tokens.css` |

**這是本期第一個使用者看得到的變化**，而它排在波次 1 是 [D138](./01-decisions-and-governance.md#d138) 的規則。

### ★★ 2.10 trigram 檢索通道對它宣稱要服務的查詢**回傳零筆**，而且花 131 毫秒

`HD-10` 的規模量測找到的，不是效能問題，是**功能缺陷**。

`search.py` 用 `content % query`。`%` 比較的是**兩個字串整體**——
一個 chunk 是 100–800 個字元，而一個 commit SHA 或卡片編號不到二十個，
於是兩者的 trigram 聯集被 chunk 主導。實測：一個**逐字包含**該查詢的 chunk，
`similarity` 是 **0.05**，而門檻是 0.25。

所以這個通道**一筆都比對不到**，同時在 20000 chunk 上花掉 **131 毫秒**——
GIN 索引把兩萬列全部當候選丟出來，recheck 再全部丟掉。

而那個模組自己的 docstring 寫著，這個通道是
「the half of retrieval that finds `CV-05`, a commit SHA and a typo」。
**三個都是短針長草堆，而 `%` 一個都服務不了。**

改成 `<%`／`word_similarity`——它比較的是查詢與內容中**最相符的一段**，
也就是這個通道一直在問的問題。同一個 chunk、同一個查詢：**1.0**。
現在 27 毫秒回 20 筆。

**為什麼沒有測試抓到**：`test_knowledge_search.py` 裡每一條 trigram 測試的
body 都是二十個字左右，而在那個長度下整體相似度很高，因為兩個字串長度接近。
**這個缺陷在 fixture 尺度上看不見，在真實尺度上是全毀。**

新增的 `test_a_short_query_is_found_inside_a_realistically_long_chunk`
與鄰居只差一件事：body 很長。**它對舊程式碼實測會紅**——
而它的第一版不會，因為它查的是完整 SHA，**FTS 通道會答**，
把一個回零筆的 trigram 通道遮住。最終版查的是差一個字元的錯字。

### 2.11 這次量測在被相信之前說了兩次謊

兩次都產生了有自信、看起來合理、而錯的數字：

1. **只有一個專案。** 2000 張卡全在同一個專案裡，於是 `project_id = ?`
   選中 2011 列裡的 2000 列，PostgreSQL 正確地偏好循序掃描。
   每一份 plan 都印著 `Seq Scan`——那**看起來就像缺索引**。
   加九個 sibling 專案讓目標佔 10%，才是 `ix_tasks_project_rank` 有意義的條件。
2. **過期的 dataset 檔。** `seed-large.py` 每次重建專案、id 會變，
   而 `explain.sh` 信任 `large-dataset.json`，於是**對一個空專案量了七份 plan**，
   全部次毫秒、全部報告「index used」。

兩者是同一種失敗：**一個分不出「很快」與「什麼都沒量到」的量測。**
`explain.sh` 現在在專案卡數少於 100 時拒絕執行。

### ★★ 2.5 a11y 套組第一次跑是綠的，而它只掃了八個畫面裡的五個

**這一條是本期目前最重要的一條，而它是實跑找到的。**

三個 Drawer 畫面的 URL 由執行期解析出來的 task id 組成。
`page.request` 不帶 Authorization header（token 在 `localStorage`，ADR 0006/0007），
解析回傳空字串，於是字面的 `?task=__WAITING__` 進了 router——
router 靜靜丟掉它，畫面就是那個**沒有 Drawer 的看板**。

**八個畫面裡三個是同一個看板，而整個套組是綠的。**
沒有任何一項檢查失敗，因為每一項檢查都真的通過了。

修法有兩半，而第二半才是重點：

1. 解析改成從 `localStorage` 讀 token（外加 `limit=100`，`MAX_LIMIT` 是 100，200 是 422）。
2. **`assertResolved`：URL 裡還留著 `__PLACEHOLDER__` 就是 failure，不是 skip。**
   skip 會把剛剛拿掉的沉默原封不動裝回去。

**加上守衛之後立刻找到八個 `critical`**——Drawer 裡三個沒有標籤的 `<select>`
（卡片的來源、交付、指派 Agent）。螢幕閱讀器使用者無法知道那三個控制項在設定什麼。
**那八個在第一次「綠」的時候就在那裡了。**

`screens.ts` 自己的註解早就警告過這一類的鄰居（截到 skeleton 的圖），
而這次踩到的是另一個版本。**寫下警告不等於防住它。**

### ★ 2.6 `research/style.md` 的語意色六期以來沒有一個能當小字用

十六個 `color-contrast` 全部追回到四個值，而四個都在 `style.md` 自己的調色盤裡：
Success 4.07、**Warning 3.00**、Error 4.17、Info 4.18——AA 小字要 4.5。

而同一份文件的〈顏色以外的辨識線索〉寫著
「一個只靠顏色區分的狀態，對色覺缺陷使用者……不存在」。
**規範要求不要只靠顏色，而它給的顏色連看得見都不保證。**

處置：只降明度、不動色相與飽和度（[`00`](./00-execution-plan.md) §4 說改既有 token 的值）。
原值仍可用於大字、填色與邊框（門檻 3:1，四個都過）。
**Warning 變化最大**（`#C08B3E` → `#93692F`，明顯偏褐），那是必要的代價——
3.00 距離 4.5 太遠，任何保住明度的做法都到不了。
若要換一個更亮而仍達標的暖色，那是一次**配色決定**，要連同 `style.md` 那張表一起改。

### 2.7 一個單元測試斷言了「屬性存在」，而那個屬性從來沒有生效

`DashboardView.test.ts` 的 `gives each big number an accessible name`
找的是 `[aria-label]` 這個選擇器。它綠了好幾個月，
而那個 `aria-label` 掛在 `<p>` 上——ARIA 禁止，accessibility tree 直接丟掉。
**斷言一個屬性在，不等於斷言它有作用。**

### 波次 0（2026-08-28）

| 產出 | 證據 |
|---|---|
| **OpenAPI 少一條路徑，而且恰好一條** | `GATE-HD-OPENAPI-DIFF` PASS，訊息是「exactly /board removed」。136 → 135 |
| 基準線十一個檔案 | `artifacts/hd/local/baseline/`（COMMIT、contracts sha、依賴三份、tokens、requirements、migration head、httpx importers、stage 寫入點、ADR 狀態、OpenAPI 路徑、tasks 索引） |
| `research/03/` 九處回寫，**保留原文並劃掉** | `git diff research/03/`——30 處 `~~` |

**這個波次對使用者是零可見變化**，而那是誠實的答案：它刪掉的東西已經沒有人在叫，
補上的東西是給下一個讀者的。**可看的產出在波次 1**（`HD-04`／`HD-05`）。

### 完成的三張 ticket

| Ticket | 做了什麼 |
|---|---|
| `HD-00` | `scripts/hd/capture-baseline.sh`（十一項，比 `plan/26` 的多五項）＋ `scripts/hd/env.sh` ＋ `research/03/` 九處回寫。**Railway `pg_trgm` 那一半未做**——見 §6 |
| `HD-07` | `/board` 六處全刪 ＋ ADR 0044 ＋ N+1 測試移植到 `work-items` ＋ 兩個 e2e 處置 ＋ `GATE-PX-BOARD-UNCHANGED` 退役、`GATE-HD-BOARD-GONE` 三段接手 |
| `HD-13` | `work.py` 說謊的 docstring、`getBoard()` 死碼、`plan/26` §0 十四處再核對（**發現其中兩處在同一期內就過期了**，§2.4） |

### ★ 2.4 `plan/26` 的回寫在同一期之內就過期了，而它被標成「☑ 完成」

`plan/26/12` §0 說十四處「☑ 全部於 2026-08-23 回寫完成」。核對之後：
`research/03/README.md` 的 migration head 仍寫 **0042**、requirements 仍寫 **189 條**。

**兩個數字在回寫的那一天都是對的。** 然後同一期的 `PX-22` 加了 `0043`、
`PX-21` 註冊了十二條需求，而沒有任何東西回頭改那張表。

**所以「開工時回寫基準表」這個動作保證它在收工時是錯的。**
本期的處置有兩層：每一列除了現況也寫**本期預計到哪裡**（migration `0046`、
requirements ≤208），並把回寫**移到封版**（`HD-12`）而不是開工。
一個寫了目標值的欄位，讀者看得出它是不是還沒到；一個只寫現況的欄位，過期與正確長得一樣。

## 5. 量測

十三項效能（2000 卡 vs 200 卡並列）、三個並發、六個 `EXPLAIN`、
六個 metric、retention 五列、provider 配額佔比。

**十三項效能預算全部達標**：context pack build 原先為 3236.24ms／2000ms；
補上異質語料七項人工 gold relevance control 後，FTS 改用候選集合不變的
`ts_rank`，同一 22,240-chunk DB 重量為 **102.76ms**。
`work-counts` 修正後三個 HTTP 並發場景為 132.18ms／401.45ms／802.96ms，
500／500 全部成功（第三項只記錄）。真 GitHub transport＋ingest 有一次 1.63 秒實測；
production worker 未改 300 秒 cadence 的一小時觀測為 12 輪／24 event、P95
**291.013 秒**；完整輸出在 `artifacts/hd/local/provider-lag-hour.json`。
完整數字與成本模型在 `artifacts/hd/local/w6/perf-2000.md`。

## 6. 出口條件

[`09`](./09-verification-and-exit.md) §8 的 42 項，逐項回填。

**35 ☑／1 ◐／6 ☐**（2026-08-29）。六項未達與一項部分達成均在該節逐項列出；
不得用「16／16 ticket 完成」代替封版結論。

## 7. 旅程

**舊十六條旅程本體在 `beta.2` 的程式碼上重跑，全綠**（2026-08-29）：

| # | 結果 | 說明 |
|---|---|---|
| **J1** | **36／36 PASS** | **不可降級且已擴充。** 真 GitHub merged PR 經管理 API pin、context pack 與 Agent citation；一句模糊需求走到 done，全程沒開過 terminal session |
| J4 | 13／13 PASS | My Work → 回答 → continuation |
| J15 | 8／8 PASS | No eligible runner → 指名缺的 tag → 修正 → 認領 |

其餘結果：J5/J6/J8/J9 **39／39**、J11–J14 擴充後 **34／34**；browser
J1a/J3/J7 **3／3**、J2/J10/J16（flag on/off）全綠。所有 stack 都使用 fresh database；
臨時資料庫在收證後刪除。

`scripts/cv/stack-evidence.sh` 的整組路徑也在 dedicated ports 上全綠；前段 J7 曾留下
一個仍在收尾的執行，讓 0.12 相容性控制組吃到共享 agent-script 狀態。相容性 harness
現在先等前段 execution capacity 歸零，再開始 subject/control；同一路徑重跑 **20／20**。

`artifacts/hd/local/journeys/`。**這是本期最重要的一項回歸**：
`0046` 動了 `tasks.stage` 的值域、三個寫入點改了、`/board` 整組刪了、
`search.py` 的檢索通道換了運算子——而主旅程一個斷言都沒有掉。

### J1 計畫新增的 merged-PR 引用也已通過

[`09`](./09-verification-and-exit.md) §4 給 J1 多加的
「Agent 引用的 knowledge 裡至少一則來自 merged PR」已在 fresh database 與 real
daemon stack 上通過：真 GitHub GET reconcile 寫入 48 sources、0 failures；merged PR #49
以 `reviewed` 進入 knowledge，經具名使用者的管理 API pin，出現在實作 run 的
`context_packs.source_manifest`，再由 Agent 透過 `cliora knowledge cite [S2]` 引用。
整條主旅程最後仍為 Done、terminal session 仍為 0，合計 **36／36**。

### provider 增量也已全部跑完

J13 的 PR-body injection 與 J14 的 provider 兩型已用 real daemon ＋ real handler/store
補跑，分別 **9／9**、**11／11**；它們直接回答 post-ingestion 的 evidence boundary 與
project isolation，不假裝回答 transport。之後以現有 GitHub credential 做了 **GET-only 真
provider reconcile**：1.63 秒、48 sources、0 failures，merged PR #49 以 `reviewed` 進入 search
且被 context pack 選中（`artifacts/hd/local/provider-real.json`）；J1 又把同一條讀取路徑接到
真 run citation，36／36（`artifacts/px/local/journeys/j1.json`）。J12 以 production
`GitHubReader` 對 controlled upstream 發出四次 HTTP GET，9／9 證明
release deletion、原文保留、退出檢索與舊 citation 的 `no longer exists`。J16 的 disabled
transport trap 證明 reader 0／GET 0／empty outcome。最後 J17/J18 讓 controlled upstream
從 open→merged、再回 401：前者經 production reader、Central、Vue Drawer 與 Chromium
重跑為 **2.260 秒／300 秒**；後者三輪各失敗一次、第四輪 read 0／skipped 1，設定畫面顯示
`Bad credentials`。因此 [`09`](./09-verification-and-exit.md) 第 40 項已由 ◐ 改為 ☑。





---

## 補做：`HD-09` 的第二半，以及一張沒勾的表（2026-08-29）

宣告「十六張 ticket 完成」之後，被問了一句「計畫都做完了嗎」。
去數 [`09`](./09-verification-and-exit.md) §8 才發現：**42 項出口條件，0 項勾過。**

ticket 與 wave 的狀態我在這份文件裡一路更新，
**出口條件那張表一次都沒走過**。工作是做了的——但
「工作做完了」與「計畫結清了」是兩句話，而我只講了第一句。

### 走完之後：35 ☑ ／ 1 ◐ ／ 6 ☐

而走的過程中發現 **38 與 39 整段被跳過了**：
`HD-09` 的前半（rollback drill）做了，**後半（十三項效能重量、三個並發場景）沒做**。
`w5` 的七個 `EXPLAIN` 讓它看起來像做過了——但 `EXPLAIN` 是查詢計畫，不是預算。

補做的第一輪找到兩個 miss；兩個都已在本次補齊中修回預算內：

| | 200 卡／1000 chunk | 2000 卡／22000 chunk | 預算 |
|---|---:|---:|---|
| context pack build P95 | 78.80ms | ~~3236.24ms~~ → **102.76ms** | 2000ms |
| `work-counts` P95（併發 10） | — | **132.18ms** | 200ms |

**第一輪的兩個 miss 都不是本期造成的迴歸。** 它們都是寫它的那一期就有的形狀，
只是從來沒有人拿真實大小的資料去量；下列處置已把兩項關閉。

- **context pack**：全部成本在 layer 4，而且**不是** trigram 通道（那是本期修過的那個，
  8.8ms）。是 FTS：`ts_rank_cd` 成本 ≈ `0.018ms × 命中列數 × 查詢詞數`，
  兩個因子都被 CJK 放大、兩個都沒有上界。加入中英、title/body、source/authority、
  age、identifier、typo 與 noise 的七項人工 gold relevance control 後，改用候選集合
  不變的 `ts_rank`；43／43 search/context DB tests 通過，同一 scale DB P95 **102.76ms**。
- **`work-counts`（已修回預算內）**：改為只投影 attention policy 真正需要的欄位，
  並合併同一瞬間、完全相同的 poll；不快取已完成結果，下一輪仍重算。fresh 2000-card
  HTTP 重量為併發 10 P95 **132.18ms**、50 **401.45ms**、100 **802.96ms**，
  500／500 全部成功；counts/items 仍共用同一個 `derive_attention` policy。
- 順帶量出來的第三件事：**repo 裡沒有任何地方設過 uvicorn worker 數**。
  每一條啟動指令都吃預設的 1。這不是被選過的預設值，只是沒被問過。

### 這一段本身的教訓

**勾表是封版的動作，不是實作的副產品。**
如果當初照表逐項勾，第 38、39 項會在那時就露出來是空的，
而這兩個數字會早兩天出現、而不是在被問「做完了嗎」的時候。

三份補的產物：`scripts/hd/measure-2000.py`、`scripts/hd/measure-concurrency.py`、
`artifacts/hd/local/w6/perf-2000.md`。
六項仍未達成，其中五項要人操作或具名核准、一項要遠端 CI；另有一項部分達成——名單在
[`09`](./09-verification-and-exit.md) §8 結算區。
