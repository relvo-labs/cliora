# 11 — 實作進度與證據

> **本檔在實作期間逐步回填。與計畫不同時以這裡為準，並回寫計畫。**
>
> **目前狀態（2026-08-28）：波次 0、1 完成。** `HD-00`／`HD-07`／`HD-13` 三張 ticket 完成，
> 十七個 `GATE-HD-*`／繼承 gate 全部 PASS 或 SKIP（零 FAIL），
> backend **2,120 passed**、frontend **847 passed**、lint／typecheck／format 全綠。
> 已知一個真實的紅燈：`GATE-PX-JOURNEY-COVERAGE` 因為我改了 `work.py` 而要求
> 重跑 j10／j16 的瀏覽器旅程——**那個 gate 說的是實話**，落點在 §6。
>
> **2026-08-25** — ★ D120 裁決為「只做 pull」，其餘八項採納計畫的答案；★ D46 一併關閉。
>
> **2026-08-27** — **SR-2、SR-3（兩列）、PR #45 核准全部簽核完成**，
> 沿用 SR-1 的 owner-authorisation 形狀；**九份 `proposed` ADR 一併轉 accepted**
> （0029／0031 的 amendment、0032／0033／0034、0038／0039、0040／0042）。
> `plan/25` 的出口條件因此變成 **27／28**，`plan/26` 變成 **40／40**。
>
> **剩下的阻礙三項，而只有一項是工作**：
> ① **Railway 的 `pg_trgm` 量測**（`HD-00` 承接，擋波次 2、3）
> ② `v2.0.0-alpha.3` tag（等 ①）③ `v2.0.0-beta.1` tag（條件已全綠）＋ `HD-06` 的 go／no-go。
>
> **波次 0、1、5 不被擋，六張 ticket 現在可以開工**
> （`HD-00`／`HD-07`／`HD-13`／`HD-04`／`HD-05`／`HD-10`）。

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
| ☐ | **`plan/25` 的 Railway `pg_trgm` 量測** | **2、3** | **一次量測，不是一個簽名。** SR-2 item 8 仍是 `PARTIAL`；`HD-00` 承接 |
| ☐ | `v2.0.0-alpha.3` annotated tag | 2、3 | 條件 **27／28**，只等上一列 |
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
| 2 | `HD-01` | ☐ 未開工（**擋於 Railway `pg_trgm` 量測 ＋ `alpha.3` tag**；SR-2 已簽） |
| 3 | `HD-02`、`HD-03`、`HD-15` | ☐ 未開工（同波次 2） |
| 4 | `HD-06` | ☐ 未開工（**擋於 `beta.1` tag ＋ go／no-go**；SR-3 與 PR #45 已關） |
| 5 | `HD-10` | ☐ 未開工，**無阻礙**（含 provider queue 的那一半要等波次 3） |
| 6 | `HD-08`、`HD-09` | ☐ 未開工 |
| 7 | `HD-14`、`HD-12` | ☐ 未開工 |

## 4. 每個波次的可看產出

[`00`](./00-execution-plan.md) §4b 的八列，逐波次回填。
**「這個波次沒有可看的東西」是一個要寫在這裡的事實**，不是一個可以略過的欄位。

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

*（待回填）*

## 6. 出口條件

[`09`](./09-verification-and-exit.md) §8 的 42 項，逐項回填。

*（待回填）*

## 7. 旅程

十八條（[`09`](./09-verification-and-exit.md) §4）。**J1 不可降級**，
且本期它多一段：Agent 引用的 knowledge 裡至少一則來自 merged PR。

*（待回填）*
