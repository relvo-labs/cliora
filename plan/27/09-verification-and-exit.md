# 09 — 驗證與出口條件

> 上游：[`research/03/10`](../../research/03/10-verification-and-exit.md)（SR-4、效能預算、十六條旅程）。
> 本檔把它落到本期，並補上上游沒有的：**十個 gate、42 項出口條件、SR-4 在 pull 模型下的形狀**。

## 1. 一句話的出口條件

> **十六條旅程全綠（J1 不可降級）＋ SR-4 具名簽核 ＋ 兩條部署路徑各一次完整演練
> ＋ `HD-06` 的結果被寫下來（還了或明確不還）。**

任一未達 → **不建立 `v2.0.0-beta.2` tag**。

## 2. 十個新 gate

| Gate | 斷言什麼 | 形式 | 來源 |
|---|---|---|---|
| `GATE-HD-READS-ARE-GETS` | `provider_reads.py` 的 HTTP method 字面只有 `"GET"` | AST | [D119](./01-decisions-and-governance.md#d119) |
| `GATE-HD-NO-WRITE-IMPORT` | `provider_reads.py` 不 import `providers.py` 的三個動作 | grep | D119 |
| `GATE-HD-NO-PROVIDER-IN-REQUEST` | `api/http/` 下不得 import `provider_reads` | grep | ★ [D120](./01-decisions-and-governance.md#d120)（上游 SR-4 第三項的改寫） |
| `GATE-HD-PROVIDER-AUTHORITY-CEILING` | `provider_sources.py` 不出現 `accepted`／`authoritative`／`canonical`／`verified` | grep | [D122](./01-decisions-and-governance.md#d122) |
| `GATE-HD-NO-LEGACY-BLOCKED` | **`backend/app` 全樹**不出現 `.stage = 'blocked'` | grep | [D123](./01-decisions-and-governance.md#d123) |
| `GATE-HD-STAGE-CHECK-IN-MODEL` | `models.py` **出現** `ck_tasks_stage` | grep（**present**） | D123 |
| `GATE-HD-VISUAL-BASELINE` | `__screenshots__/` 檔數 == spec 宣告的畫面數 | 計數 | [D124](./01-decisions-and-governance.md#d124) |
| `GATE-HD-OPENAPI-DIFF` | OpenAPI diff **恰好**少 `/api/projects/{project_id}/board` 一條 | diff | [D126](./01-decisions-and-governance.md#d126) |
| `GATE-HD-TOUCH-LIST` | [`00`](./00-execution-plan.md) §3 的禁區未被動；前端依賴**與基線相差恰好一個** | diff | [D125](./01-decisions-and-governance.md#d125) |
| `GATE-HD-EGRESS-ALLOWLIST` | `backend/app` 內 import `httpx` 的模組**恰好是明列的兩個** | grep | D119（取代 `GATE-KN-NO-NEW-EGRESS (httpx)` 的單檔版本） |

**沿用並換基線的三個**：`GATE-PX-CONTRACT-FROZEN`、`GATE-PX-NO-DAEMON-DIFF`、
`GATE-PX-MIGRATION-ROUNDTRIP`。基線由 `HD-00` 的 `capture-baseline.sh` 產生。

**刪除的一個**：`GATE-PX-BOARD-UNCHANGED`（它守的東西被刪了，D126）。

### 2.1 兩個 gate 的形式值得說明

**`GATE-HD-EGRESS-ALLOWLIST` 為什麼取代而不是新增**：
`GATE-KN-NO-NEW-EGRESS (httpx)`（`scripts/kn/gates.sh:65`）的寫法是
`grep -v 'services/providers.py'`——一個排除。
排除一個檔案與明列兩個檔案在今天等價，**在第三個檔案出現時不等價**：
排除式的版本會在第三個檔案出現時紅，而它的訊息是
「httpx is imported outside services/providers.py」——**說不出是哪一個**。
明列式的版本說得出。

**`GATE-HD-STAGE-CHECK-IN-MODEL` 為什麼是 present**：
本期的 gate 大多是 absent（以缺席驗證），這一個相反，
因為它防的是「改完資料庫的 CHECK 忘了同步 ORM」——
而那個遺漏的表現是沉默，不是錯誤。

## 3. 測試矩陣

| 層 | 本期新增 | 落點 |
|---|---|---|
| 單元（Python） | `provider_reads` 的 host allowlist、timeout、token 剝除；`provider_sources` 的 authority 值域（四個高階各一負面）；`0045` 的推導順序五條各一 | `backend/tests/unit/` |
| 資料庫 | `0044` roundtrip；`0045`／`0046` roundtrip；`legacy_blocked_at` 的完整還原；`set(_HALF_LIFE_DAYS) == SOURCE_TYPES`；`SOURCE_TYPES - mapped == EXTERNALLY_TRIGGERED` | `backend/tests/db/` |
| API | provider 設定的 403（無 `project.update`）；provider source 的跨專案隔離（兩型各一）；`/board` 已 404 | `backend/tests/api/` |
| 前端單元 | `HD-15` 的 Related delivery 三種狀態；設定頁的失敗原因顯示 | `frontend/src/modules/**/*.test.ts` |
| a11y | 八個畫面 × axe（0 critical／0 serious） | `frontend/tests/a11y/` |
| 視覺 | 八個畫面 × `toHaveScreenshot` ＋ **一個反向測試** | `frontend/tests/visual/` |
| E2E／旅程 | 十六條（§4） | `scripts/hd/journeys/`、`frontend/tests/hd/` |
| 演練 | `HD-08` 兩條路徑 × 五步；`HD-09` 六步 | `scripts/hd/` |
| 量測 | 十三項效能 ＋ 三個並發 ＋ 六個 `EXPLAIN` | `scripts/hd/measure-*.py` |

## 4. 十六條旅程

`research/03/10` §3 的十六條，**本期全部回歸**（`HD-12`）。
前十五條的行為不變，**新增的斷言只在 J1 與兩條新的**：

| # | 旅程 | 里程碑 | 本期新增的斷言 |
|---|---|---|---|
| **J1** | **主旅程**（模糊需求 → … → Done，**不進 Terminal**） | `beta.1` | **＋一段**：Agent 引用的 knowledge 裡**至少一則來自 merged PR**（authority `reviewed`） |
| J2 | Backlog 建卡 → 送 Ready | `beta.1` | **＋全鍵盤走完**（`HD-04` 第 3 項） |
| J3 | Ready → 認領 → Waiting for input | `alpha.2` | — |
| J4 | My Work → 回答 → continuation | `beta.1` | — |
| J5 | answer 後 daemon 斷線 → 只建一個 turn | `alpha.2` | — |
| J6 | comment 不誤 resume | `alpha.2` | — |
| J7 | Run failure → retry，conversation 保留 | `alpha.2` | — |
| J8 | 兩人同答一題 → 一成一敗 | `alpha.2` | — |
| J9 | Agent 送 decision → 拒絕 ＋ audit | `alpha.2` | — |
| J10 | filter → 開卡 → 關 → filter 不變 | `beta.1` | — |
| J11 | 新 decision 進 knowledge → 新 turn 可引用 | `alpha.3` | — |
| J12 | repo 文件刪除 → 舊 chunk 不再命中 | `alpha.3` | **＋** release 被刪除 → `deleted_at` 有值、內容保留、citation 說得出「後來被刪了」 |
| J13 | prompt injection 不提升為 instruction | `alpha.3` | **＋一則含注入字串的 PR body** |
| J14 | 無權 Project 搜尋 → 拒絕且 count 不洩漏 | `alpha.3` | **＋** provider 兩型各一 |
| J15 | No eligible runner → 修正 → 認領 | `beta.1` | — |
| J16 | flag 矩陣 | `beta.1` | **＋** `provider_sync_enabled=false` 時不發任何 GET |
| **J17** | **PR 合掉 → ≤300 秒進 knowledge → Drawer 上看得到** | **`beta.2`** | 全新。pull 模型的那個承諾本身 |
| **J18** | **撤權 token → 3 輪後停止 → 設定頁顯示原因** | **`beta.2`** | 全新。SR-4 第 5 項 |

**十六 ＋ 二 = 十八條**，而上游說「十六條」。
差額是本期新增的兩條，而它們是**本期唯一兩個新能力的驗證**——
一個少了它們的十六條回歸，證明的是舊功能沒壞，不是新功能做了。

**J1 仍然是不可降級的那一條。** 它多的那一段（引用一則 merged PR）
是本期把 provider 接進主旅程的證明：
若那一段降級，本期做的事就只是「多了兩張表」。

## 5. SR-4 — Provider ingestion 的信任邊界

**pull 模型下的八項**，全文在 [`02`](./02-provider-ingestion.md) §8。

| # | 審查項 | 通過標準 |
|---:|---|---|
| 1 | provider token 的保存、範圍與輪替 | 既有機制的回歸 |
| 2 | merge 前的 PR 內容不自動成為 policy | `GATE-HD-PROVIDER-AUTHORITY-CEILING` ＋ 四個負面測試 |
| 3 | 對外 GET 只發生在 worker | `GATE-HD-NO-PROVIDER-IN-REQUEST` |
| 4 | `provider_reads.py` 只發 GET | 兩個 gate |
| 5 | 被撤權的 token 不會無限重試 | J18 |
| 6 | 錯誤 body 不含 token、不進 log／metric | redaction 測試 ＋ label allowlist |
| 7 | 無權專案的 provider source 不外洩 | J14 的擴充 |
| 8 | provider 內容不進 instruction layer | J13 的擴充 |

**簽核文字必須寫明兩件事**：

1. **為什麼少了上游的兩項**（webhook signature、delivery 去重）——
   因為 pull 模型下它們不存在。一個少了兩項而沒有說明的審查表，
   下一個人會以為它被漏掉了。
2. **`plan/26` SR-3 那句還沒關的話仍然沒關**：
   「有 membership 時 counts 不洩漏存在性」——
   這個部署沒有 project membership（`rbac.py:92` 的 `_VIEWER_ACTIONS` 含 `project.view`），
   所以那一句本期也證不出來，而簽名的人要知道自己在簽它。

## 6. 效能預算

`research/03/10` §5 的十三項，**在 2000 卡上重量一次**，與 200 卡並列。
**新增三項**：

| 項目 | 目標 | 為什麼 |
|---|---|---|
| **provider reconcile lag P95** | **< 300s** | pull 模型的產品承諾本身 |
| `work-counts` 50 併發 P95 | < 500ms | 一個 50 人團隊每人一個分頁 |
| `work-counts` 100 併發 | **只記數字** | 想知道在哪裡開始不行，而不是它應該多快 |

**已知會超的一項**：`work-counts` 的 P95 < 200ms 是在 200 卡上訂的
（`plan/26` D95）。2000 卡上它**可能超**。
超了的處置有三個，按優先序：①加索引 ②把輪詢從 20 秒調長 ③列入 known limitations。
**不許做的是把預算調高而不說**。

## 7. Known limitations（至少四條，[D140](./01-decisions-and-governance.md#d140)）

| # | 限制 | 誰承擔 |
|---:|---|---|
| ~~0~~ | ~~**`pg_trgm` 在 Railway 上未經驗證**~~ → **☑ 2026-08-28 關閉，而且是發現問題問錯了**：`pg_trgm` 是 trusted extension，判準是資料庫的 `CREATE` 權限不是 superuser。三種角色實測、兩條拒絕路徑各驗、`docs/deployment-railway.md` 補上該節。**剩下的未知只有 Railway 自己的 extension allowlist**，而文件裡有一行 `psql` 述詞可以在部署前回答它 | 運維。原文保留：它開了六個星期、擋了兩個波次，而關掉它花了一個下午 |
| 1 | **provider 同步的新鮮度是 300 秒，不是即時。** 一個 PR 合掉之後最多五分鐘才出現在 Related knowledge | 使用者。webhook 的設計在 ADR 0043 裡，實作未排期 |
| 2 | **只有 GitHub。** GitLab 在 `adapter_for` 裡沒有 entry，且是刻意的（D15） | 使用 GitLab 的部署——**完全無法使用 provider 同步** |
| 3 | **2000 卡／20000 chunk 以上沒有量過。** 資料庫大小、GIN 重建時間、queue 深度三項的實測值只到這個量 | 運維 |
| 4 | **視覺回歸只涵蓋八個畫面。** 第九個畫面的版面回歸沒有東西會抓到 | 開發 |
| 4b | **視覺 baseline 綁定字型環境，不只是綁瀏覽器。** 第一版 baseline 在一個沒有 CJK 字型的容器裡拍出來，釘的是一整頁方框——在那台機器上永遠過，在別處永遠失敗。已裝 `NotoSansCJK` 重拍，但 **CI 的 image 必須有相同字型**，否則第一次跑就是八張全紅 | 開發／CI |
| 5 | **50 個 repository 時 provider API 用掉 GitHub 配額的 36%**（1800／5000 GET 每小時） | 運維。超過約 140 個 repository 會撞配額 |
| 6 | **`legacy_blocked_at` 是一個過渡欄位**，計畫在 `rc` 之後移除 | 開發 |
| 7 | **無 project membership**，所以「無權專案的卡不在 counts」在本部署證不出來（承 `beta.1`） | 安全簽核的人 |
| ~~8~~ | ~~若 `HD-06` 跳過：`stage='blocked'` 的雙重語意仍然存在~~ → **☑ `HD-06` 做了**（`0045`／`0046`，ADR 0040 修訂）。`is_blocked` 現在可以直接讀 | — |

**第 8 條是條件式的，而它沒有成真**——但它出現在這張表上仍然是對的做法：
一個「可能會跳過」的 ticket，它跳過之後的後果要**先寫下來**，
否則跳過的那天沒有人會想起要寫。**先寫下來的成本是三行；沒寫的成本是一筆無人認領的技術債。**

## 8. 42 項出口條件

| ☐ | # | 條件 | 來自 |
|---|---:|---|---|
| ☑ | 1 | ADR 0043 accepted，含 webhook 設計並標未實作 | [`02`](./02-provider-ingestion.md) |
| ☑ | 2 | ADR 0044 accepted，含 `BoardCardDTO` 的量測紀錄 | [`08`](./08-sunset-and-cleanup.md) |
| ☑ | 3 | **ADR 0040 修訂區塊非空**（還了或明確不還） | [D139](./01-decisions-and-governance.md#d139) |
| ☑ | 4 | `0044` roundtrip 三次，資料未損 | [`02`](./02-provider-ingestion.md) |
| ☑ | 5 | `0045` roundtrip，`legacy_blocked_at` 的卡完整還原 | [`03`](./03-stage-final-migration.md) |
| ☑ | 6 | `0046` roundtrip，**失去什麼已進 release note** | [`03`](./03-stage-final-migration.md) |
| ☑ | 7 | `set(_HALF_LIFE_DAYS) == SOURCE_TYPES` | [`02`](./02-provider-ingestion.md) |
| ☑ | 8 | `SOURCE_TYPES - mapped == EXTERNALLY_TRIGGERED` | [D121](./01-decisions-and-governance.md#d121) |
| ☑ | 9 | 十個 `GATE-HD-*` 全綠 | §2 |
| ☑ | 10 | `GATE-PX-CONTRACT-FROZEN`／`NO-DAEMON-DIFF` 換基線後全綠 | §2 |
| ☑ | 11 | `GATE-PX-BOARD-UNCHANGED` 已刪除（它守的東西不在了） | [D126](./01-decisions-and-governance.md#d126) |
| ☑ | 12 | `providers.py` 的 diff 為零 | `GATE-HD-TOUCH-LIST` |
| ☑ | 13 | `secrets.py`／`rbac.py`／`deliveries.py` 的 diff 為零 | 同上 |
| ☑ | 14 | 前端依賴與基線相差**恰好一個** | [D125](./01-decisions-and-governance.md#d125) |
| ☑ | 15 | backend 依賴未變 | 同上 |
| ☑ | 16 | 八個畫面 axe **0 critical／0 serious** | [`04`](./04-accessibility.md) |
| ☑ | 17 | axe **audit 前**的報告也存下來 | 同上 |
| ☐ | 18 | 六項人工 a11y checklist ＋ **具名簽核** | 同上 |
| ☐ | 19 | 第 2 項的證據含**實際聽到的字** | 同上 |
| ☐ | 20 | 全鍵盤走完 J2 的錄影 | 同上 |
| ☑ | 21 | 八張視覺 baseline ＋ **反向測試** | [`05`](./05-visual-regression.md) |
| ☐ | 22 | 視覺套組在 **CI 上**跑過並綠 | `v2-projects.yml` 已新增 `hardening-browser`，本地以同一個 fresh-DB／Noto CJK／Chromium 形狀跑 **9／9**；尚未 push，所以沒有 GitHub Actions 綠燈，不能把「可在 CI 跑」寫成「已在 CI 跑過」 |
| ☑ | 23 | `/board` 六處全刪，OpenAPI diff 恰好少一條 | [`08`](./08-sunset-and-cleanup.md) |
| ☑ | 24 | `?tab=` **未刪**，刪除條件進 release note。**改為宣告式**（`rc.1` 移除，不論使用量）——`HD-07` 實作時發現 FastAPI 看不到 `?tab=`，計數式做不出來，ADR 0044 §4 | 同上 |
| ☑ | 25 | `work.py` docstring 已改；`getBoard()` 已刪 | 同上 |
| ☑ | 26 | `ck_tasks_stage` 在 `models.py` 上 | [`03`](./03-stage-final-migration.md) |
| ☑ | 27 | 三個 `stage='blocked'` 寫入點全改，全樹 gate 綠 | 同上 |
| ☑ | 28 | ambiguous report 從 N 筆變 0 筆（或 `HD-06` 明確跳過） | 同上 |
| ☑ | 29 | 2000 卡 seed 可重跑；200 卡 seed 一行未改 | [`06`](./06-scale-and-observability.md) |
| ☑ | 30 | 六個 `EXPLAIN` ＋ 每份一行結論 | 同上 |
| ☑ | 31 | **五個**新 metric 在 `/metrics`，label 全在 allowlist（`legacy_route_hit_total` 不做——`HD-07` 實作時發現 FastAPI 看不到 `?tab=`） | 同上 |
| ☑ | 32 | **`provider_reconcile_lag_seconds` P95 ≤ 300s** | `provider-lag-hour.json`：production `KnowledgeWorker` 未改 300 秒 cadence、12 輪／24 個 live-cursor event、實時間 3613.071 秒；DB 的 `ingested_at - source_updated_at` P95 **291.013 秒**，histogram 24／24 落在 300 秒 bucket。controlled loopback upstream，production `GitHubReader`，不改外部 provider object |
| ☑ | 33 | retention 與體積五列有實測值，進 release note | 同上 |
| ☑ | 34 | provider API 配額佔比進 release note | 同上 |
| ◐ | 35 | `HD-08` 兩條部署路徑各一次五步演練 ＋ 七項驗證 | compose 那條做完了（`w6/rehearsal-compose.log`，五步各七項，**第一次跑就抓到 `0046` 的真缺陷**）。**Railway 那條沒做**——本環境沒有 Railway 部署，與第 12 項的 `psql` 判定是同一個缺口 |
| ☑ | 36 | 七個 revision 的可逆性表完整 | 同上 |
| ☑ | 37 | `HD-09` 六步全綠，`work_views` 已匯出 | 同上 |
| ☑ | 38 | 十三項效能在 2000 卡上重量，與 200 卡**並列** | `w6/perf-2000.{json,md}`。八項量測、五項具名不重量並寫明理由。context pack 的 `ts_rank_cd` 成本先量出 3236.24ms，加入異質語料七項人工 gold relevance control 後改用 `ts_rank`；同一 22,240-chunk DB 重量為 **102.76ms／2000ms，全部達標** |
| ☑ | 39 | 三個並發場景各一次；超預算項逐項有處置 | `w6/concurrency-2000.json`（2026-08-29 修正後）：併發 10 P95 **132.18ms**／200ms、併發 50 **401.45ms**／500ms、併發 100 **802.96ms**（500／500、只記錄）。narrow projection ＋ identical-poll single-flight，且 counts/items 仍共用 `derive_attention` |
| ☑ | 40 | 十八條旅程 | **全數通過。** 舊十六條本體全綠；J1 真 GitHub merged-PR **36／36**、J12 production-reader HTTP release lifecycle **9／9**、J13 **9／9**、J14 **11／11**、J16 reader 0／GET 0。J17 controlled open→merged event 經 production reader、Central 與 Chromium Drawer 重跑為 **2.260 秒／300 秒**；J18 三輪各失敗一次、第四輪 read 0／skipped 1，設定畫面顯示 `Bad credentials` |
| ☐ | 41 | **SR-4 八項具名簽核**，含「為什麼少兩項」與 membership 那句 | §5 |
| ☐ | 42 | **`v2` → 上游由人工核准** | 治理 |

**第 42 項永遠是最後一項，而它永遠不是自動的。**
出口條件全綠只是取得提案資格。

### 結算：35 ☑ ／ 1 ◐ ／ 6 ☐（2026-08-29）

**這張表在十六張 ticket 都做完之後，仍然一格都沒勾過。**
勾選是封版的動作，不是實作的副產品——而本期把它漏掉了，
直到有人問「計畫都做完了嗎」才發現。記在這裡，因為
「工作做完了」與「計畫結清了」是兩句話，而下一期會再犯一次。

**六項未達成，其中五項要人操作或具名核准，一項要遠端 CI：**

| # | 未達成 | 誰能做 |
|---:|---|---|
| 18 | 六項人工 a11y checklist ＋ 具名簽核 | 一個人，在瀏覽器前。六項全部記錄為**未執行**，不是「執行過且通過」 |
| 19 | 第 2 項的證據含實際聽到的字 | 同上——需要真的開一次螢幕閱讀器 |
| 20 | 全鍵盤走完 J2 的錄影 | 同上 |
| 22 | 視覺套組在 **CI 上**跑過並綠 | CI job 已接好且同形狀本地 9／9；需要 push 後取得一次 GitHub Actions 綠燈 |
| 41 | SR-4 八項具名簽核 | 一個沒寫過 V2-E1 程式的人 |
| 42 | `v2` → 上游核准 | 一個人，且永遠不是自動化 |

**一項部分達成（◐）**：35 少了 Railway 路徑。第 32 項已用真 300 秒排程下的
12 輪／24 event 關閉，P95 **291.013 秒**。

**本次結算過程中補做了 38 與 39**（`HD-09` 的第二半，先前整段跳過），
補做時有**兩個效能預算沒過**；本次補齊已把兩個都修回預算內：
`work-counts` 以窄投影與 identical-poll single-flight 關閉，context pack 則先加入
異質語料七項人工 gold relevance control，再把 `ts_rank_cd` 改為候選集合不變的
`ts_rank`。同一 22,240-chunk DB 的 context P95 由 3236.24ms 降到 **102.76ms**。

## 9. 每個 prerelease 的必要產物（`HD-12`）

沿用 `research/03/00` §7 的九項，**每一項本期的具體內容**：

```text
Release note              provider 同步、a11y、視覺回歸、stage 還債（或明確不還）
Known limitations         §7 的八條，第 8 條是條件式的
Compatibility manifest    Central commit / agentd 0.14.1 / contract 1.13.0 / migration 0046
Migration/rollback note   七個 revision 的可逆性表 ＋ 0046 的「失去什麼」
Security delta            provider 是新的 egress 目的地；httpx 從一個模組變兩個；無新入口
Test/gate evidence        scripts/hd/evidence.sh 一次跑完的輸出
Feature flag matrix       兩個部署旗標 × per-project 的 knowledge_enabled 與 provider_sync_enabled
Data retention delta      provider 兩型 source 無保留；legacy_blocked_at 是過渡欄位
Manual sign-off record    SR-4 ＋ a11y ＋ ambiguous report ＋ 合併核准，四個具名
```

**Security delta 那一行是本期最重要的一句**：
`httpx` 從一個模組變成兩個，而那是三期以來 `SCOPE-013`（實際文字）之外
第一次動到「Central 對外連線的形狀」。它要被明確寫下來，
而不是藏在「新增 provider 同步」這句話裡。
