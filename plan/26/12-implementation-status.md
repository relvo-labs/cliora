# 12 — 實作進度與證據

> **本檔在實作期間逐步回填。與計畫不同時以這裡為準，並回寫計畫。**
>
> **目前狀態（2026-08-24）：波次 0 至 7 全部完成，34 張 ticket 全部完成。**
>
> `scripts/px/evidence.sh` 一次跑完十一個 gate、全部靜態檢查、兩套單元測試、
> 資料庫套組、traceability、兩份已發佈目錄、四項量測、回滾演練與**六條旅程**——
> **全綠**（`artifacts/px/local/evidence.log`）。
>
> **四十項出口條件：三十八項達成，剩下的兩項都是人的動作**
> ——34（`v2` → `dev` 核准）與 38（SR-3 具名簽名）。
> **J1 過了**（32／32），它是不可降級的那一條，也是本期宣稱的目的本身。
> **`views/ProjectDetailView.vue`（1,515 行）已刪除**，它的 14 支測試移植到
> `modules/project/projectShell.test.ts` 並加了 12 支關於拆分本身的測試。
>
> **這份文件先前寫「J1／J4／J15 需要這個環境沒有的 Go 工具鏈」，那是錯的**——
> Go 一直都在，harness 一直都能跑。§6 有一段專門記這件事，因為
> 一個附了錯誤理由的空方框比一個空著的方框更難被發現。
>
> **三項前置條件仍然開著**，波次 1 起是在人工裁決下開工的——見 §2.7，
> 那一項是這份文件裡最重要的一條。

## 0. 要回寫上游的九處

寫這份計畫時核對程式碼發現 `research/03/` 有九處已經過期、不精確或缺漏。
**`PX-00` 負責回寫**，因為一份被下一個讀者當成事實的規劃文件，
它的錯誤會被繼承——這是 `plan/25` §0 的同一個理由。

> **☑ 十四處（九處錯誤 ＋ 五處缺口）全部於 2026-08-23 回寫完成。**
> 回寫的形式是**保留原文並劃掉**，不是覆蓋：下一個讀者要看得到當時寫的是什麼，
> 否則他無從判斷這份文件還有哪裡可能同樣過期。
> 第 5 項在回寫時又發現一件事，記在 §2.8。

| # | 文件 | 原本 | 應為 |
|---:|---|---|---|
| 1 | `research/03/README.md` 規劃基準表 | `v2` HEAD `45a3143`；`agentd` 0.13.1；migration head 0040；ADR「0038／0039／0040 是空號」 | HEAD `3e503de`；`agentd` **0.14.1**；migration head **0042**；空號只剩 **0040 與 0042**（0038／0039 已由 `alpha.3` 用掉，0041 已 accepted） |
| 2 | 同上 | requirements **178** 條、27 family | **189** 條、**28** family（`FR-KNOW` 十一條已註冊） |
| 3 | 同上 | `tokens.css` **58** 個 property | **62** |
| 4 | 同上 | 執行計畫表 `P1 \| plan/26/ \| 未建立` | **已建立**（本目錄，2026-08-23）；`K1` 那一列改成「已實作，出口 26／28，未 tag」 |
| 5 | `research/03/01` §1.5 / `04` §6 | `WorkItemCardDTO` 200 張 ≤ **160 KB**，理由「74 KB 的兩倍多一點」 | **74 KB 已過期**。`plan/19` 之後的實測是 **89,251 / 90,000**。預算改為「先量再釘」（[D94](./01-decisions-and-governance.md)） |
| 6 | `research/03/04` §5 | 「要不要物化？建議先做即時計算並量測，200 張卡若 P95 > 1 秒再改物化」 | **兩個選項都不成立**。八級裡有兩級不在資料庫（[D92](./01-decisions-and-governance.md)）。`tasks.attention_primary` 從 §4 的 DDL 移除 |
| 7 | `research/03/08` §8 | machine code 八個，含 `STAGE_TRANSITION_REFUSED` | **七個**。第八個沒有 raise 點（[D97](./01-decisions-and-governance.md)） |
| 8 | `research/03/10` §10 未量測項 7、8 | 「十級 authority 是否過細」與「`task wait` 120 秒」排在 `beta.1` | 移到 **`beta.2`**（[`11`](./11-open-measurements.md) §7、§8） |
| 9 | `research/03/12` §3.2 | ambiguous report 的推導順序七條 | 第 3、4 條（dispatch 失敗、runner 離線）**在 migration 裡不可用**——`alembic upgrade` 沒有 `NodeConnectionRegistry`（[`02`](./02-data-layer.md) §5.2） |

還有三處是**規劃層的缺口而不是錯誤**，已在本目錄補上並要回寫：

| # | 缺口 | 補在哪 |
|---:|---|---|
| 10 | 上游沒有提到系統**沒有 project membership**，而 SR-3 有三項建立在它之上 | [D93](./01-decisions-and-governance.md)、[`04`](./04-filter-and-query-compiler.md) §6 |
| 11 | 上游假設有 WSS 可以推播到瀏覽器，而這個 repo 只有 terminal 一條 | [D95](./01-decisions-and-governance.md)、[`09`](./09-frontend-architecture.md) §2 |
| 12 | 上游沒有提到 `TaskService.update()` 是 stage 的唯一寫入點且有 AST gate，而 bulk update 直接踩到它 | [D96](./01-decisions-and-governance.md)、[`05`](./05-work-items-and-view-api.md) §5 |
| 13 | 上游沒有提到 `task_questions` 沒有 `addressed_to_user_id`，而 My Work 第一段的述詞需要它 | [`08`](./08-my-work-and-navigation.md) §3 |
| 14 | 上游沒有提到 `notification` 系統不存在，而 §4.3 的出口條件建立在它之上 | [`08`](./08-my-work-and-navigation.md) §4（改為 `GATE-PX-MYWORK-READS-STATE`） |

## 1. 開工前的裁決單

### A 類 — 擋開工

> **☑ 八項全部於 2026-08-23 裁決，全部採納計畫的答案。**
> 各項全文（含「不同意的話會怎樣」）保留在
> [`00`](./00-execution-plan.md) §0.1 與 [`01`](./01-decisions-and-governance.md)——
> 那是**為什麼這樣決定**的紀錄。三個月後沒有人會想知道選了什麼，
> 但每個人都會想知道當時放棄了什麼。

| # | 決定 | 狀態 | 裁決日 | 一起接受的代價 |
|---|---|---|---|---|
| D92 | attention 兩相位；`tasks.attention_primary` 永不建立 | ☑ **採納** | 2026-08-23 | 那兩級不能當 `order_by` 鍵；多 worker 下是 per-process（[`11`](./11-open-measurements.md) #2） |
| D93 | 可見專案述詞單一來源；isolation 測「述詞被套用」 | ☑ **採納** | 2026-08-23 | SR-3 #3 的簽核文字要寫明「本部署無法產生負面案例」 |
| D94 | DTO 預算先量再釘 | ☑ **採納** | 2026-08-23 | `PX-25` 的第一個 commit 是量測而不是 endpoint |
| D95 | 只輪詢 counts 20s；不開瀏覽器 WS | ☑ **採納** | 2026-08-23 | `work-counts` 是最熱端點，P95 < 200ms 是硬預算 |
| D96 | bulk update 逐張走 `TaskService.update()` | ☑ **採納** | 2026-08-23 | bulk 慢；且**沒有既有 gate 守著**，要新增 `GATE-PX-BULK-USES-UPDATE` |
| D97 | 不新增 `STAGE_TRANSITION_REFUSED`；DoR 維持警告 | ☑ **採納** | 2026-08-23 | `PX-30` 的缺失項要能直接點開補，UI 責任變重 |
| D115 | 新增波次 0：可見價值先行 | ☑ **採納** | 2026-08-23 | side-car endpoint 是會被刪的 40 行；`PX-25` 負責刪、`PX-28` 斷言刪乾淨 |
| D117 | UI 不分 V1／V2；旗標不建立 | ☑ **採納** | 2026-08-23 | **沒有 kill switch**；回滾前要先匯出 `work_views` |
| ~~D116~~ | ~~旗標預設何時裁決~~ | — | 由 **D117** 取代 | 原論證（預設 `false` 就沒有真實使用）併入 D117 |

**八項全綠，波次 0 至 7 沒有裁決性阻礙。**
剩下的阻礙只有 §1 的三項前置條件，而它們擋的是**波次 1 起**——
**波次 0 現在就可以開工。**

### B 類 — 依計畫執行

`D98`…`D114`、`D118`：☐ 未裁決（依計畫執行，有異議時記在 §2）。

### 從上游繼承、仍未關閉

| # | 決定 | 狀態 | 影響 |
|---|---|---|---|
| ★ D46 | provider 同步落在哪一版 | ☐ 未裁決 | 本計畫假設 `beta.2`。只影響 `PX-66` 的 release note 措辭 |

### 前置條件

| ☐ | 事項 |
|---|---|
| ☐ | `plan/25` 的 Railway `pg_trgm` 驗證完成 |
| ☐ | SR-2 具名簽核 |
| ☐ | `v2.0.0-alpha.3` annotated tag ＋ GitHub pre-release 建立 |

## 2. 與計畫的差異

> 實作期間逐項回填。格式沿用 `plan/25` §2：
> **標題一句話說出差異，內文說出「計畫怎麼想、實際是什麼、為什麼」。**
> 帶 ★ 的是「所有測試都是綠的，但東西是錯的」那一類——
> `plan/25` §2.11 的標題進索引就是為了讓下一個人先讀它們。
>
> **三十八條，其中 ★★ 的五條全部是實跑找到的**（§2.24、2.25、2.28，以及 2.25 的孿生條 2.26）：
> 兩條在 in-process 測試全綠的情況下已經出貨，
> 一條讓 Drawer 在最需要說明原因的那張卡上閉嘴，
> 一條讓主控台上一個按鈕從 V2.5 開始就什麼都沒做。
> **它們全部是在同一天、同一批旅程與瀏覽器實跑裡找到的**，
> 而在那之前這份文件寫著那些實跑「需要這個環境沒有的東西」（§6）。

### 2.1 `human_decision` 只有三個值，第四個沒有來源

計畫（[`03`](./03-read-model-and-attention.md) §1.D，承自 `research/03/04` §2）列了
`not_required | pending | approved | changes_requested` 四值。
**實際只實作三個。**

`tasks.gates` 存的是 `{gate_key: {approved_by, approved_at}}`，
而 `TaskService.decide_gate(approve=False)` 是 **`gates.pop(gate_key)`**——
「審查者要求修改」與「還沒有人看過」在資料上是同一列（都是「這個 key 不存在」）。
delivery 也沒有人工審查狀態：`delivery_state` 的三個值
（`pending_pr`／`delivered`／`branch_only`）全部是 worker 的佇列狀態。

於是 `changes_requested` **沒有任何寫入點**。這正是 [D97](./01-decisions-and-governance.md)
剛剛用同樣理由刪掉 `STAGE_TRANSITION_REFUSED` 的那件事，也是 `plan/25` §2.12 的
`CROSS_PROJECT_DENIED`：一個沒有 raise 點的值是文件不是行為。

**要恢復第四個值需要的是資料而不是程式**：`gates` 要能存
`{decision: "changes_requested", by, at, note}`，那是一次 migration ＋ 一個新的
gate decision 端點語意，屬於另一題。理由寫在
`services/work/projection.py` 的 `HUMAN_DECISIONS` 上方。

### 2.2 attention 第 2 級加了一個 lifecycle 條件，計畫沒有寫

計畫的相位 A 表把第 2 級寫成「`human_decision = 'pending'`（gates 未齊 或 delivery 待審）」。
**照字面實作會讓整塊看板都亮起來**：seed 的流程定義有六個 gate
（requirements／architecture／ui／implementation／verification／release），
每一張新卡都是 0/6，所以每一張新卡都「等待人工核准」。

實際條件是 **`lifecycle == 'review' AND human_decision == 'pending'`**。
一張卡進入 review 的時刻，正是它在請人看的時刻。
理由寫在 `derive_attention` 第 2 級的行內註解。

### 2.3 `WorkRow` 多了 `over_wip` 與 `stale` 兩個布林

計畫的 `WorkRow`（[`03`](./03-read-model-and-attention.md) §3）沒有這兩欄，
而第 8 級需要兩個單一列答不出來的事實：**該 lane 有多少張卡**，與**現在幾點**。
把它們放進 `derive_attention` 會讓那個函式不再純，而
[`03`](./03-read-model-and-attention.md) §5 要量它 200 次——
量一個會查東西的函式，量到的是查詢。

所以兩者在建列時算好（`services/work/rows.py`），`derive_attention` 維持純函式。

### 2.4 `stale_after` 是這一期發明的常數

計畫寫 `updated_at < now() - :stale_after` 但沒有給值。
本期訂 **7 天**，且**只對 `ready`／`in_progress`／`review` 三個 lifecycle 生效**
（backlog 是佇列、done 已完成，把兩者算進去會讓大半塊看板帶警告，
而一個大半塊看板都有的警告等於沒有警告）。

**這是一個猜測，不是量測**，已列入 [`11`](./11-open-measurements.md)。

### 2.5 波次 0 的既有看板行為變了一項：全寬提示改由伺服器決定

原本 `TaskBoard.vue` 自己判斷 `active_run_status === 'waiting_for_input'` 並畫一條
橘色全寬提示。現在那條提示是 `AttentionBadge`，由 `derive_attention` 的 `primary` 決定。

差別看得見：一張 run 正在跑但被相依阻塞的卡，以前沒有提示，現在有。
一張 run 是 `waiting_for_input` 但沒有未回答問題的卡，以前有提示，現在沒有——
而後者才是對的（那是一個正要恢復的 run）。
`TaskBoard.test.ts` 的那支測試改寫成斷言這件事。

### 2.6 `--attention-*` 五個 token 有四個是既有顏色的別名

計畫（[`09`](./09-frontend-architecture.md) §5）把五個 attention token 列成新色、
五個 `--work-*` 列成別名。實際上**只有 `--attention-approval` 是新顏色**：
其餘四個分別別名到 `--run-waiting`、`--stage-blocked`、`--status-error`、`--status-busy`。

property 數仍然是 +10（62 → 72），符合 [`00`](./00-execution-plan.md) §4 的表。
理由是同一件事不該有兩個色碼：`--attention-human` 若鑄一個相近的橘，
`plan/19` D24 指定給「有一個人被等著」的那個語意就被拆成兩半。
`staticGuards.test.ts` 的 `--run-waiting` allowlist 因此加入 `theme/tokens.css`
並註明「元件要的是 `--attention-human`」。

### 2.13 ★ 讀模型有三個欄位不是欄位，於是分頁在 SQL 之外收尾

計畫（[`04`](./04-filter-and-query-compiler.md) §2）把十五個 filter 欄位裡的
**十四個**當成「編譯成一段 SQL」，只有 `attention` 是兩相位。實作之後是**三個**不是一個：

| 欄位 | 為什麼進不了 `WHERE` |
|---|---|
| `attention` | 八個述詞蓋在六個別的事實上，其中兩個根本不在資料庫（D92） |
| `readiness` | 依**該專案**的 effective process，同一份 JSONB 在兩個專案意思不同 |
| `execution_status` | 「最新的 active run，否則最新的 run」是一個 window function，讀模型每頁已經算過一次 |

`lifecycle` **不在這張表上**，而那是好消息：它映射到 `tasks.stage` 的值，
所以編譯成一個 `IN`，`ix_tasks_project_stage` 照樣服務它。

代價是真的，而且要說清楚：**帶 derived 條件的查詢會先把 SQL 允許的整個集合載進來再分頁**，
因為游標不能繞過一個還沒套用的述詞。在本期的規模（一個專案幾百張卡）那本來就是一頁的量，
量測在 §5（帶 derived filter 的 P95 是 8.2 ms，比不帶的還快一點，因為它濾掉了更多卡）。
**它在一千張卡以上帶 derived filter 時會停止可接受**，
而那時誠實的反應是把 `execution_status` 與 `readiness` 變成真正的欄位，
不是把一個謊分頁。

守住「counts 與 items 不會不一致」的是 `filters.matches()`：**兩個端點呼叫同一個函式**，
所以 SQL 邊界沒有製造第二個答案，它只製造了一個成本。

### 2.14 `visible_fields` 的「回應不含該欄」需要 DTO 全欄可選

計畫說「一個 `visible_fields` 不含 `owner_name` 的 view，其回應不含該欄」。
照字面做需要**省略 key**，而 Pydantic 的 response model 預設會把未提供的欄位序列化成 `null`。

`"owner_name": null` 同時代表「這張卡沒有 owner」與「這個 view 不顯示 owner」，
**而那是兩件不同的事**。所以 `WorkItemCardDTO` 除了身分四欄（`id`／`card_ref`／
`version`／`updated_at`）之外全部可選且無預設值，路由以
`response_model_exclude_unset=True` 序列化，shaping 就是「少建構幾個 key」。

身分四欄永遠留著：一張客戶端無法定位的卡不是比較短的回應，是壞掉的回應。

### 2.15 `tasks.rank` 的 `NOT NULL` 讓 `ActiveRunProjection` 多了兩欄

`WorkItemCardDTO` 要 `active_run_id` 與 `active_run_started_at`（卡片的 deep link
與「已跑 12 分」那一行），而 `ActiveRunProjection` 沒有這兩欄。

計畫 §3 說「`repositories/tasks.py` 既有六個方法的回傳形狀不動」。
本期**動了 `active_runs()` 的回傳形狀**（兩個有預設值的新欄位，以及查詢多選兩欄）。
理由與守門的東西：`read_board` 只把 `status` 與 `runner_name` 抄進 `BoardCardDTO`，
所以看板的 payload 一個位元組都沒動——而**證明它的是 `PX-28` 的 bytes 測試**，
不是這段話。這正是 [D94](./01-decisions-and-governance.md) 第 5 步預期的情境
（「有人為了新卡而讓那兩個查詢多回一欄」），而它現在有一個會變紅的測試。

### 2.16 side-car endpoint 的刪除時間改成「與 V1 看板同時」——**已於波次 4 之後執行**

計畫（[`05`](./05-work-items-and-view-api.md) §9 規則 4）說
「波次 2 的 `PX-25` 負責刪掉它，而 `PX-28` 的 OpenAPI 快照斷言它不見了」。

波次 2 **沒有刪**。在 `PX-64` 用子路由取代 `ProjectDetailView.vue` 之前，
既有看板是唯一存在的看板，而 side-car 是它的徽章來源；
波次 2 就刪掉它等於把波次 0 交付的東西收回去三個波次。

所以刪除條件從一個波次號改成一個狀態——**與 V1 看板同時**——
而那個條件寫進了一支測試而不是一則備忘。
波次 4 的 `ProjectWorkView` 換掉 `TaskBoard.vue` 之後條件成立，於是同時刪除了：

```text
GET /api/projects/{id}/board-attention        後端 endpoint 與兩個 DTO
client.getBoardAttention() / BoardAttention   前端型別與方法
components/project/TaskBoard.vue（＋測試）     V1 看板本身，已無任何 import
```

`test_the_side_car_is_gone_now_that_the_v1_board_is` **是同一支測試翻面**，
並額外斷言它不在 OpenAPI 裡（不只是路由不通）。

**`/board` 相反：deprecated 但仍在服務**（[D118](./01-decisions-and-governance.md#d118)）。
差別在於 side-car 從來沒有這個 repo 以外的呼叫者，
而 `/board` 與完整任務頁是 ☑ D117 之後僅剩的兩條降級路徑。
`test_the_board_endpoint_stays_one_more_version` 守著這個差別。

### 2.8 ★ 89,251 這個數字量的不是 `BoardCardDTO`

`plan/26` 的規劃基準表寫「看板卡實測 **89,251 bytes / 200 張**，預算 90,000」，
出處是 `repositories/tasks.py` 的 docstring：
「the same 200-card fixture is 89,251 bytes against a 90,000-byte budget」。
[D94](./01-decisions-and-governance.md) 用 99.2% 這個佔用率論證「新 DTO 不能抄 160 KB」。

**論證成立，數字不是它說的東西。** `PX-00` 重量之後：

| 數字 | 它其實量的是什麼 |
|---|---|
| 74 KB | `plan/17` 的 M1，`plan/19` 加三欄之前 |
| **89,251** | `scripts/tk/measure_board_payload.py` 的**合成**產生器 ＋ 一份**手寫 summary dict**——寫於 `plan/17`，**早於 `BoardCardDTO` 存在**。長英文標題、隨機 owner 名 |
| **75,952** | 真正的 `BoardCardDTO` × 200，跑在 `beta.1` 的固定資料集（seed 20260819）上 |

兩個都可重現（89,251 今天再跑仍然是 89,251），它們只是**兩個不同的 fixture**。

**這件事會咬到 `PX-28`。** 計畫給它的條件是
「`BoardCardDTO` diff 為空 **＋ bytes 未變**」，而「未變」需要一個基準。
若照抄 89,251，那支測試從第一天起就是紅的；
若用合成腳本，它守的是一份不再存在於程式裡的 dict。

**`PX-28` 的釘死值改為 75,952 ± 2%，fixture 寫在測試 docstring 裡。**
合成腳本的 89,251 保留為第二個基準（它守的是 `plan/17` 的形狀決定），
兩者都由 `scripts/px/capture-baseline.sh` 一起抓，
而**捕捉腳本印出來的那一行必須說明兩者的差別**——
一個沒有標籤的數字就是下一次同樣的誤讀。

這是 [D94](./01-decisions-and-governance.md)「先量再釘」的第二個例子，
而且它證明那條規則對**舊卡**也成立，不只是對新卡。

### 2.9 ★ `rank` 設成 `NOT NULL` 之後，沒有人指派它——計畫沒有寫這一段

[`02`](./02-data-layer.md) §5.1 說 backfill 之後
`ALTER TABLE tasks ALTER COLUMN rank SET NOT NULL`。**照做之後任何新卡片都插不進去**：
`TaskService.create_task()` 不設 `rank`，seed 腳本不設，幾十支測試 fixture 也不設。
第一次發現它是 `scripts/cv/seed-dataset.py` 在 `0043` 之後直接失敗。

計畫沒有回答「誰在建卡時決定順序」。本期的答案是兩層：

| 層 | 做什麼 | 為什麼 |
|---|---|---|
| `db/models.py` | 欄位有 Python 端 default `'a'` | 一個沒有 default 的必填欄位會讓每一條**不經過 service** 的插入路徑壞掉——seed 腳本與測試 fixture 都是 |
| `TaskService.create_task()` | `rank_between(None, min(rank))` | 真正的建卡路徑把新卡放到**最上面** |

**最上面而不是最下面**，理由是連續性：V1 看板是 `updated_at DESC`，
而 backfill 依同一個順序指派，所以最新的卡持有最小的 rank。
放到最下面會讓升級後第一次建的卡出現在 200 張 backlog 之後。

一起接受的代價：**兩個同時建卡會拿到同一個 rank**。
欄位沒有唯一約束，這是刻意的——碰撞的代價是一次由次要排序鍵決定的平手，
而約束的代價是建卡路徑上的一個重試迴圈。背景再平衡會在下一次執行時把它們分開。

### 2.10 ★ `ix_tasks_project_updated` 對 V1 看板**完全沒有效果**

[D104](./01-decisions-and-governance.md) 的理由是「看板正是 `ORDER BY updated_at DESC`，
而今天沒有支援它的索引」。**前半對，後半不足以推出這個索引有用。**

實測（`scripts/px/measure-board-index.py`，同一個交易內建索引／刪索引各量一次）：

| 規模 | 查詢 | 無索引 | 有索引 |
|---|---|---|---|
| 200 卡 | 整塊看板（無 `LIMIT`） | `Sort` cost 132.11 | `Sort` cost **132.11** |
| 2000 卡 | 整塊看板（無 `LIMIT`） | `Sort` cost 255.16 | `Sort` cost **255.16** |
| 200 卡 | `LIMIT 50` | `Limit` cost 130.74 | `Limit` cost **99.04** |
| 2000 卡 | `LIMIT 50` | `Limit` cost 207.06、0.396 ms | `Limit` cost **14.71**、**0.059 ms** |

**整塊看板的計畫一個位元組都沒變**，兩個規模都一樣。原因很簡單：
`read_board` 回傳專案的**全部**卡片，而一個反正要讀完的表，索引贏不了循序掃描 ＋ 排序。

索引真正服務的是**會提早停下來**的查詢——也就是 `PX-25` 的游標與
Done 欄的「近 7 天／近 N」。在 2000 卡上那個查詢便宜 **14 倍**、快 **6.7 倍**。

所以 D104 的**決定是對的、理由要改寫**：這個索引不是「讓既有看板變快」，
是「讓本期新加的分頁查詢可行」。[`02`](./02-data-layer.md) §4 那句
「本期唯一一個會讓既有查詢變快的變更」**是錯的**，已在此更正。

### 2.11 `PX-61` 拆成兩半，中間夾著 `PX-22`

計畫把 `PX-61`（rank 純函式 ＋ endpoint）排在 `PX-22`（migration）**之前**，
理由是 `0043` 的 backfill 要用 `rebalanced_ranks()`（[D98](./01-decisions-and-governance.md)）。
那個理由只涵蓋純函式：**endpoint 需要 `tasks.rank` 這個欄位，而欄位是 `PX-22` 加的。**

實際順序：`ranking.py` ＋ 兩組測試 → `PX-22` 全部 → `POST /tasks/{id}/rank`。
D98 的論證不變，只是它管的範圍比它看起來的小一半。

### 2.12 `blocking_reason` 的 `gate_unmet` 推導改了條件

計畫的第 6 條是「有未通過的 gate」。照字面寫成 `gates = '{}'::jsonb`
的結果是**每一張 blocked 卡都被判成 `gate_unmet`**——`{}` 是每一張新卡的預設值，
所以第一次跑出來 20 張 blocked 卡全部是 `gate_unmet`，ambiguous report 空無一物。
一份空的 report 與一份「裡面沒有值得讀的東西」的 report 不是同一件事。

改成 **`gates <> '{}'`**：有人核准過一部分但沒核准完，
那是「審查進行過然後停下來」，是證據。完全沒有核准紀錄的卡沒有提供任何證據，
所以落到 `unknown` 並進 report——那是誠實的答案。

改完之後固定資料集的 20 張 blocked 卡全部是 `unknown`，
而那是對的：它們沒有相依、沒有等待中的 run、沒有驗證報告、沒有 gate 紀錄。

### 2.17 ★ `WorkItemCardDTO` 少了 `project_id`，而 My Work 沒有它就不能用

計畫的 33 欄清單（[`03`](./03-read-model-and-attention.md) §4）**沒有 `project_id`**。
原因看得出來：那份清單是為單一專案的端點寫的，那裡的答案在路徑上。

**My Work 是跨專案的**，而一張連不回去的卡片是一列讀者沒辦法動作的資料。
所以 `project_id` 加進 DTO，而且**進身分那一組**——
`visible_fields` 不能把它藏掉，因為隱藏它產生的不是比較短的回應而是壞掉的回應。

代價已量測：DTO 從 34 欄 159,118 bytes 變成 35 欄 **169,518 bytes**（+6.5%），
釘死值同步改成 194,945。而 `project_id` **是最貴的一欄**（10,400 bytes／200 張）——
一個 uuid 加一個長 key 名，付兩百次。
前五貴的裡面有三個是 key 名而不是值，這正是
[`03`](./03-read-model-and-attention.md) §4 的砍除順序從「沒有人讀的欄位」開始
而不是從「看起來很大的欄位」開始的理由。

### 2.18 `ProjectRunsView` 沒有建立——沒有端點可以讀

計畫的目錄佈局（[`09`](./09-frontend-architecture.md) §4）與 §7 的子路由表都列了
`/projects/:id/runs` → `ProjectRunsView`。**沒有做**，理由是這個 repo 沒有
「列出一個專案的 run」這個端點：只有 `GET /api/tasks/{id}/runs`（單張卡）
與 `GET /api/runs/{id}`（單一 run）。

一個專案層級的 run 清單是一個**新端點**加它自己的分頁、篩選與授權決定，
而那不在 `PX-64`（把既有畫面搬到子路由）的範圍裡。
子路由因此是**六個 ＋ knowledge**，不是八個。
要補的話它是 `beta.2` 的一張 ticket，而不是這一張的尾巴。

### 2.19 `/dashboard` 與 `/` 的方向反過來，但 route 名稱不變

計畫（[`08`](./08-my-work-and-navigation.md) §6）說
「`/dashboard` 保留為 `/` 的別名（既有的 `{ path: "/", redirect: dashboard }` 反過來）」。
照做了：現在 `/` 是頁面、`/dashboard` 是別名。

**route 的 `name` 仍然是 `dashboard`。** 十四個呼叫點用它，
包括 auth guard 的 fallback 與 catch-all；改名是十四次編輯，
而唯一看得見的效果是舊書籤壞掉。畫面上的字是 `Home`，
而**旗標關閉時仍然是 `Dashboard`**——關閉時的側欄必須是 V2 之前那一張圖，
「重新分組之後少一列」與「沒有變」是兩張不同的圖（`plan/16` 出口條件 6）。

### 2.20 側欄從一個 group 變成兩個：Infrastructure 與 Administration

計畫 §6 的樹是四組。實作把原本一個 `Infrastructure`（五項）拆成
**Infrastructure（Nodes／Integrations）** 與 **Administration（Audit／Enrollment）**。

理由：`Nodes` 與 `Integrations` 是維運的人在維護的東西，
`Audit` 與 `Enrollment` 是管理的人在授予的東西。
把「誰可以加入這個機群」放在「哪幾台機器活著」旁邊，
是一個權限形狀的動作混進維運日常的方式。

一個讀者若沒有 `audit.view` 也沒有 enrollment 權限，
`Administration` 就**不出現**（不是出現一個空標題）——
一個看起來空的分組比沒有分組更糟，這一條有測試。

### 2.21 ★ 跨欄拖曳的判斷寫成「沒有分組」，而正確的是「分組就是 lifecycle」

第一版的 `crossing` 條件是 `state.group === null`。看起來對——預設就是沒有分組，
而預設的分組是 lifecycle。

**但使用者一旦在下拉選單裡明確選了「階段」（也就是同一個分組），
`state.group` 就變成 `"lifecycle"` 而不是 `null`，於是跨欄拖曳停止改變 stage。**
卡片在畫面上移動了，下一次輪詢把它移回去。

兩半各自都是對的，所以沒有單元測試會紅。
**抓到它的是瀏覽器證據那一輪**（`artifacts/px/local/w4/`）——
`wave4.spec.ts` 先選了一次「階段」再做鍵盤移動，而移動的播報說 `移動到 done`
而不是 `移動到 verify`。

正確的條件是 `(state.group ?? "lifecycle") === "lifecycle"`。
這一條記在這裡是因為它是這一期第一個**只有把畫面跑起來才會發現**的缺陷，
而 [D115](./01-decisions-and-governance.md) 整段論證就是關於這件事。

### 2.22 Drawer 的「等待中」判斷讀 `WorkItemCard`，不讀 `TaskDTO`

`PX-41` 的自動捲動與聚焦需要「這張卡有沒有未回答的問題」。
`TaskDTO` **沒有** `open_question_count`——那一欄是 `alpha.2` 加在 `tasks` 上的投影，
但沒有進 V2.1 的卡片 DTO。

沒有把它加進 `TaskDTO`：Drawer 已經從呼叫端拿到 `WorkItemCard`
（工作板把它傳下來），而那張卡有 `primary_attention` 與 `open_question_count`。
加一欄會是**第二個答案**，而 `derive_attention` 是唯一的那一個（ADR 0040 §3）。

所以 `TaskDrawer` 多了一個 `card` prop，而它是選填的：
從完整頁面（`/projects/:id/tasks/:taskId`）打開時沒有讀模型的卡，
那時 Drawer 退回「不自動捲動」——比猜一個答案好。

### 2.23 Overview 的兩條 strip 用 `try`，不用 `.catch`

`PX-50` 的 attention strip 與 work distribution 是**註記**，
它們所在的頁面主要內容是專案本身。第一版寫 `await api().getWorkCounts(...).catch(...)`，
而在測試的 mock 裡 `getWorkCounts` 不存在——那是一個**同步**的 TypeError，
`.catch` 接不到，於是整個 `onMounted` 拋出，Overview 空白。

改成 `try`／`catch`。這不只是為了測試：一個註記不該讓它所註記的頁面倒下。

### 2.24 ★★ `derive_attention` 的第一級讀 run 狀態，而正確的是 `waiting_for_actor`

**J4 找到的，而且只有真的 daemon 找得到。** 第一版的判斷是：

```python
if row.open_question_count > 0 and row.execution == "waiting_for_input":
```

而 [`03`](./03-read-model-and-attention.md) §2 就是這樣寫的——**規劃寫錯了，實作照抄。**

Agent 有兩種等法：問完**繼續輪詢**（run 停在 `waiting_for_input`），
和問完**直接結束**（run 是 `succeeded` / `awaiting_input`）。
而 `cliora task ask` 印出來的三個選項裡，**第一個、被標為「建議」的就是「直接結束這個行程」**。
所以照建議做的 Agent，它的卡片在看板上**完全沒有注意力標記**——
那個在等它的人看不出它在等自己。

ADR 0035 §8 的 `tasks.waiting_for_actor` 存在的理由正是這個：
它由 question 狀態寫入（`ConversationService._reproject` 是唯一的 writer），
所以兩種等法給同一個答案。改成：

```python
if row.open_question_count > 0 and row.waiting_for_actor == "human":
```

**為什麼十五條單元測試都沒抓到**：它們全部都用 `execution="waiting_for_input"` 佈景，
因為那是規劃寫的形狀。測試照著規格寫，規格錯了，測試就一起錯。
現在 `test_waiting_for_input_reads_the_projection_not_the_run_status`
**兩種形狀各斷言一次**，而斷言的名字說出讀的是投影而不是 run 狀態。

### 2.25 ★★ `CreateTaskRequest` 沒有 `card_kind` 與 `requirement_id`，主控台的按鈕從 V2.5 就在空轉

**J1 找到的。** `ProjectRequirementsView.vue`（以及它移植前的 `ProjectDetailView.vue`）
按「送給 Agent 釐清」時送出：

```ts
await api().createTask(projectId, { title, card_kind: kind, requirement_id, ... });
```

而 `CreateTaskRequest` 兩個欄位都沒有宣告，也沒有 `extra: "forbid"`——
**Pydantic 預設是忽略**。所以回來的是 201、一張 `card_kind='implementation'`、
`requirement_id=None` 的普通卡，接著 `dispatchTask` 也成功了，跑成一次普通的實作 run。
**沒有任何東西報錯，那個流程只是沒有發生。**

這是 V2.5 的缺陷，不是本期造成的——本期是忠實地移植了它。
它活過了一整期，因為 `test_clarification_and_decomposition.py` 的每一條
都是**直接插入 `Task` 資料列**來造釐清卡的：沒有一條 HTTP 路徑造得出來，
所以沒有一條測試會發現造不出來。

修法是三件事一起：
1. `CreateTaskRequest` 加上 `card_kind` 與 `requirement_id`；
2. `create_task` 驗證 requirement **屬於同一個專案**，不屬於就是 404 而不是 403
   （403 會確認一張看不到的資料列存在）；
3. `card_kind` 是 `clarification`／`decomposition` 而沒有 requirement 時，
   **在建立時就拒絕**，不只在派工時——一張只可能被拒絕的卡比一個錯誤更糟，因為它看起來像進度。

`requirement_id` **刻意不放進 `UpdateTaskRequest`**：一張卡的 requirement 是它「為了什麼」，
而一張在某一版規格寫完之後才改指向別的 requirement 的卡，會讓版本歷史讀不懂。

順帶補上 `TaskDTO.card_kind`——它一直不在裡面，所以主控台看得到一張卡連著 requirement，
卻看不出它是那個 requirement 的釐清卡，而派工時讀 `card_kind` 的四條拒絕
因此無法從詳細資料的任何欄位解釋。

### 2.26 ★ 主控台根本沒有勾選就緒條件的控制項

**寫 J1 的 Ready transition 時發現的。** `TaskDetail.vue` 把七項就緒條件
渲染成 `✓`／`○` 的唯讀清單，而 `readiness` 在 `EDITABLE_FIELDS` 裡、
`UpdateTaskRequest.readiness` 也在——**只是沒有畫面可以寫它**。

於是 [`06`](./06-board-and-backlog.md) §5 的「缺失項可直接點開補」沒有地方可以去：
對話框可以列出缺什麼、可以指向對應的欄位，而那個欄位不存在。

補上一個 checkbox（`canEdit` 時才有），送**整份 map** 而不是單一 key——
`readiness` 是 JSONB 欄位而 `update_task` 直接賦值，
只送一個 key 會把其他六項清掉，而對 JSON 欄位的部分寫入是那種「資料掉了看起來像成功了」的 API。

### 2.27 `readiness_missing` 上了 DTO 又下來，因為量測說它是整份 payload 最貴的欄位

對話框需要「缺哪幾項」而不是「缺幾項」，而 `WorkRow.readiness_missing` 早就算好了，
所以放上 `WorkItemCardDTO` 看起來免費。**量出來是 +34,440 bytes**：
200 張卡從 169,518 變成 203,958（+20 %），一舉超過 `project_id` 成為最貴的欄位。
每一個回應的每一張卡都付這個錢，包括 My Work 的跨專案頁，
換來的是一個對話框對一張卡的需求。

改成對話框自己讀 `/api/tasks/{id}`——按下去的時候，讀那一張卡。
[`03`](./03-read-model-and-attention.md) §4 的裁剪清單從「沒人看的欄位」開始就是這個理由，
而 `test_work_items_size` 是把「看起來免費」變成一個數字的那個東西。

### 2.28 ★★ Drawer 的「自動展開」讀 primary，而該讀的是 signal 集合

**wave 5 的瀏覽器實跑找到的。** [`07`](./07-task-drawer.md) §2 的四種情境
（無可用 Agent、指定 Agent 離線、宣告機密卻被阻塞、宣告交付卻沒綁程式庫）
是要讓「藏起來的設定正好就是答案」時自己打開。第一版讀 `card.primary_attention`。

而一張卡可以同時是好幾件事。示範專案裡那張 `arm64` 卡的 signal 是：

```json
["pending_human_approval", "no_eligible_runner", "over_wip_or_stale"]
```

`pending_human_approval` 是第 2 級、`no_eligible_runner` 是第 5 級，
所以徽章顯示前者（D107：primary 是呈現決定）。於是**情境成立、區塊卻沒有打開**
——那正是「介面拒絕說明原因」的那一刻，而這個規則存在的唯一理由就是不要有那一刻。

看板的卡片**刻意**只帶 primary：兩百張時整份 signal 清單就是 payload 的大半，
而 `test_the_work_item_card_carries_the_primary_attention_and_not_the_set` 的
docstring 早就寫了下一句——**「完整的 signal 清單屬於 Drawer，不屬於卡片」**。
只是那個給 Drawer 的東西沒有被做出來。

補上 `GET /api/tasks/{id}/attention`：一張卡、完整集合、
用**同一個** `WorkRowReader` 與 `derive_attention`
（`GATE-PX-SINGLE-ATTENTION` 擋掉第二套排序，而這條路由讓那個 gate 的意義超出看板：
一個自己讀欄位回答「這張卡為什麼卡住」的端點，會是一份沒人能對得起來的第二意見）。
Drawer 開的時候抓，抓不到就退回 primary——primary 是關於這張卡的真話，只是不完整的真話，
而一個等第二個請求回來才決定要不要展開的區塊會在讀者的游標下閃一下。

`test_the_per_card_endpoint_carries_the_set_the_board_does_not` 斷言三件事：
primary 與看板一致、集合含有 primary、**且 primary 是集合的第一個**
——少了第三件，一條路由可以回對的清單配錯的標題。

### 2.29 主控台無法表達「不套用任何 view」

補上 2.26 的預設 view 之後，`全部卡片` 這個選項變成了空操作：
它刪掉 `view=`，而 `view=` 不存在的意思就是「套用預設 view」。
於是**看板變得無法解除篩選**，而 wave 0 的基準截圖（八級同框）正是在那個畫面上拍的。

加了一個 sentinel：`?view=all`。它讀得懂（貼在訊息裡的連結，同事看得懂那是什麼），
不會跟 view id 相撞（那永遠是 uuid），而且兩句話都說得出來了——
「照這個專案的預設」與「全部給我看」。

### 2.30 `modified` 對每一個選到的 view 都說「已修改」

同一次瀏覽器實跑找到的。判斷寫成
`isModified(state.filter, activeView.filter)`——而沒有打字的時候 `state.filter` 是 null、
view 的 filter 不是，所以比較說它們不同。結果是**每一個選中的 view 都掛著「已修改」**，
還附一個「還原」按鈕。第二次看到那個標籤的人就不會再讀它了。

加上第一個條件：`state.filter !== null &&`。
沒有 `f=` 就沒有修改——看板此刻顯示的就是 view 本身。

### 2.31 三支瀏覽器 spec 對著已經不存在的東西斷言

`wave0` 與 `wave3` 的 `signIn` 斷言 `/(dashboard|nodes|sessions)`，
而本期把落地路由換了（§2.19）；`wave0` 還在找 `[data-stage=...]`，
那是**已刪除的**舊看板的屬性。三支都是「基準」性質的 spec，
而基準 spec 是最容易腐爛的一種：**沒有人會重看一張截圖。**

改成斷言側欄出現（「登入了」的實際意思，而且不會因為路由搬家就要重教），
以及 `[data-group]`。順帶把 `wave0` 的「八個徽章同框」拆掉——見下一條。

### 2.32 一條會隨時間改變答案的斷言

`wave0` 斷言看板上出現八個**不同**的徽章。那句話有兩個問題：

1. 徽章顯示的是一張卡的 **primary**，而一張卡可以帶好幾個 signal
   ——`by_attention` 數的是 signal（事實），徽章顯示的是其中最急的那個（D107）。
   所以「八級都出現在畫面上」從來就不是同一件事；
2. `over_wip_or_stale` 會隨著 fixture 變舊而**累積到每一張卡**上，
   於是同一支測試一週後跑會得到不同的答案。

**一個判定取決於 seed 是多久以前跑的測試，不是測試。**
改成斷言畫面上每一個徽章都是讀模型認得的級別，而事實那一半由 `work-counts` 負責。

### 2.33 `GATE-PX-MIGRATION-ROUNDTRIP` 把自己的前置條件說成 migration 的缺陷

`pytest tests/db` 用 `metadata.create_all` 建 schema，所以剛跑過測試的資料庫
會有一個蓋在「Alembic 從來沒有建過的物件」之上的 `alembic_version`。
於是 `downgrade` 掉在一個本來就不存在的東西上，而 gate 回報的是

> `0043 did not survive down-and-up`

——那是一句關於 migration 的話，而且不是真的。

**一個把自己的前置條件誤判成受測物缺陷的 gate，比一個直接跳過的 gate 更糟**：
它會讓人去改 `0043`。改成先確認資料庫在 head，
並把 downgrade 與 re-upgrade 的失敗**分開回報並附上最後一行輸出**。

### 2.34 兩個 db 套組同時跑，症狀看起來完全不像原因

`tests/db/conftest.py` 在每個 HTTP 測試之間 `DELETE FROM` 每一張表，
所以**同一個資料庫上跑兩份套組**會互相清掉對方的 fixture。而症狀是：

- `unhandled_error` 的 500；
- 幾秒前才發出的 token 回 `TOKEN_INVALID`；
- 插入子資料列時 `parent "is not present in table"` 的外鍵違規。

三個都讀起來像產品缺陷。而**單獨重跑每一個檔案都會過**——
那是最容易誤導人的訊號組合：它看起來像「測試之間互相污染」，
於是人會開始改測試順序或 fixture，而問題根本不在那裡。

conftest 的 docstring 現在寫著這件事，並附上該做的第一件事：
全套失敗而單檔通過時，**先找有沒有第二個 `pytest tests/db` 在跑**，再動任何程式碼。

**同一個 docstring 還寫了第二個陷阱**：`CLIORA_TEST_DATABASE_URL` 是 fixture 連的，
而 `CLIORA_DATABASE_URL` 是**應用程式自己的 engine** 讀的——
`test_run_reaper.py` 那六條走的是後者。只設第一個，它們會失敗在
`database "cliora" does not exist`：一個**指出預設值而不是指出錯誤**的訊息，
讀起來像測試壞了而不是像少了一個環境變數。

追這兩件事花掉的時間，比它們各自的修法長一個數量級。
兩者都不是產品缺陷，而兩者都曾經被我當成產品缺陷回報過一次
——記在這裡，因為下一個看到 105 條紅字的人會做出同樣的判斷。

### 2.35 ★★ 三條旅程的判定比它們涵蓋的程式碼舊，而沒有東西看得出來

`plan/26/10` §3 把 `GATE-PX-JOURNEY-COVERAGE` 說成**本期最可能的假綠**，
理由是「六條旅程全部 skip 而套件回報成功」。它說對了，而實際發生的比那更難看見。

旅程跑完之後，我又動了 `backend/app`（加 `/api/tasks/{id}/attention`、
改 `create_task`）。三份判定 JSON 還在，內容還是 32／32、13／13、8／8，
**而它們是關於一份已經改過的程式碼的**。沒有任何東西看起來是舊的：
JSON 完好、數字漂亮、`evidence.sh` 照樣印綠。

gate 一寫出來就抓到這三條。重跑之後 J1 32／32、J15 8／8，**而 J4 掉到 12／13**——見 2.36。

**commit stamp 擋不住這件事。** 整期都還沒 commit，所以 stamp 永遠等於 HEAD，
不管工作目錄動了多少。所以 gate 比的是**時間**：
沒有它涵蓋的原始檔可以比它新。那是唯一在未 commit 的樹上有效的檢查，
而未 commit 的樹正是 commit 檢查瞎掉的地方。

寫的時候它自己過嚴了兩次，兩次都修掉：
daemon 旅程不碰 `frontend/src`（一次 CSS 編輯不該要求三次 daemon 重跑），
而編輯 J4 的腳本不該讓 J1 的判定失效（每條旅程只依賴共用 harness ＋ 自己那一支）。
**過嚴不是安全的那一邊**——那是 gate 被人關掉的方式。

### 2.36 ★ J4 用 `card_ref` 比對，而 My Work 是跨專案的

2.35 的重跑讓 J4 掉到 12／13，失敗的是最後一條：
「而它從 My Work 的等待區消失了」——回報 `['TASK-1']`。

`card_ref` **只在專案內唯一**，而 `/api/me/work-items` 跨專案是它存在的理由。
`cliora_e2e` 裡有一張早先 J15 留下的 `px-j15-…/TASK-1` 還在等人，
於是斷言看到一個 `TASK-1` 就判失敗——**產品是對的，斷言是錯的**。

改成用 task id 比對，13／13。而原本那次 13／13 是**靠資料庫剛好是乾淨的**換來的：
同一支測試在一個用過的資料庫上會紅，而紅的原因跟它要測的事情無關。
`card_ref` 留在 detail 裡當可讀的那一半，斷言用 id。

### 2.37 `artifacts/px/` 少了 `local/`，而那一層是 gitignore 的界線

`.gitignore` 有一條 `artifacts/*/local/`。**其他每一期的產出都在那一層底下**
——`cv`、`kn`、`dv`、`rq`、`pg`、`sc`、`tk`、`ar`、`fu`、`pv` 全部只有一個 `local/` 子目錄。
本期把東西直接寫在 `artifacts/px/`，於是 76 個檔案、3.8MB 截圖會**進版本歷史並永久留著**。

發現的時機是要開 PR 的前一刻，而那是最後一個還來得及的時機：
一旦 push，3.8MB 的 PNG 就在歷史裡了，`git rm` 拿不掉。

改法是搬到 `artifacts/px/local/` 並改掉 27 個檔案裡的 68 處路徑引用。
`.gitignore` 不用動——那條規則本來就在，是本期沒有照著它的形狀寫。

**這不是排版問題。** 判定檔與截圖是「重跑一次就能再生」的東西
（`scripts/px/evidence.sh` 加上三條旅程的指令），
而把可再生的產出放進歷史，是把一次執行的結果當成原始碼。

### 2.38 `GATE-PX-JOURNEY-COVERAGE` 的依賴清單過嚴了三次

寫這個 gate 的過程本身就是一次「過嚴不是安全的那一邊」的示範。三次都是它自己抓出來的：

1. `frontend/src` 放進 daemon 旅程的依賴——一次 CSS 編輯要求三次 daemon 重跑；
2. `scripts/px/journeys/` 整個目錄——編輯 J4 的腳本讓 J1 的判定失效；
3. `frontend/tests/px/` 整個目錄——編輯 `wave5.spec.ts` 讓 J16 的截圖失效。

正確的模型是**每條旅程只依賴它真的碰到的東西**：
共用的 `backend/app`、`daemon/`、`px_harness.py`，加上它自己那一支腳本。

每一次過嚴都會產生一個「明明沒關係卻要求重跑」的要求，
而那種要求累積起來的結果不是更嚴格，是 gate 被人繞過。

### 2.7 ★ 波次 1 起在三項前置條件未關閉的情況下開工（人工裁決，2026-08-23）

[`00`](./00-execution-plan.md) §1 的三項前置條件——Railway `pg_trgm` 驗證、
SR-2 具名簽核、`v2.0.0-alpha.3` tag——**在波次 1 開工時全部仍然開著**，
而開工是**人工裁決的結果**，不是被忽略。

三項的現況與為什麼實作者關不掉它們：

| 前置條件 | 為什麼沒關 |
|---|---|
| Railway `pg_trgm` | 需要一個 Railway 專案與它的資料庫憑證。compose 那半已驗（`plan/25` §7 第 17 項） |
| SR-2 具名簽核 | 簽核**必須是沒有寫這段程式的人**具名。實作者簽自己的審查等於沒有審查（`plan/25` §8.1） |
| `alpha.3` tag | 依賴上面兩項，而且打 tag 與發 pre-release 是對外發版動作 |

**一起接受的代價，逐字寫下來**：

計畫給前置條件的理由**只咬到 `PX-62`**——
「`PX-62`（Related knowledge）整合 `KN-11`，而在一個沒有簽核的 knowledge 層上疊 UI，
等於把 SR-2 的未結項帶進 SR-3」。裁決是**連 `PX-62` 一起做**，
所以那句話現在是一個**已發生的事實而不是一個被避開的風險**：

> **SR-3 的範圍包含一段建立在未簽核 knowledge 層之上的 UI。**
> SR-2 簽核時若對 `KN-11` 提出任何變更，`PX-62` 要跟著改，
> 而那個改動落在 SR-3 已經審過的表面上。

`PX-65` 的 SR-3 文件必須把這一段寫進「已知未結項」，
`PX-66` 的 release note 必須說明 `beta.1` 疊在一個未簽核的 `alpha.3` 上。
**這兩件事不是加分項，是這個裁決的還款計畫。**

本期的實作**不打任何 tag、不 push、不合併**——
`v2` → `dev` 一律由人決定的規則沒有變（[README](./README.md)）。

## 3. 波次進度

| 波次 | ticket | 可看的產出（[`00`](./00-execution-plan.md) §4b） | 狀態 |
|---|---|---|---|
| **0** | `PX-17`／`PX-24`／`PX-18`／`PX-38` | 既有看板卡片有 attention；點卡開 Drawer | ☑ **完成**（`artifacts/px/local/w0/`） |
| 1 | `PX-00`／`PX-21`／`PX-61`／`PX-22` | Backlog 順序穩定 | ☑ **完成**（`artifacts/px/local/baseline/`） |
| 2 | `PX-23`／`PX-25`／`PX-26`／`PX-47`／`PX-28` | filtered work-items 的 curl 範例 | ☑ **完成**（`artifacts/px/local/w2/`） |
| 3 | `PX-27`／`PX-64`／`PX-63` | 子路由 ＋ 新導覽 | ☑ **完成**（`artifacts/px/local/w3/`；`ProjectDetailView.vue` 已刪除） |
| 4 | `PX-29`／`PX-30`／`PX-31`／`PX-32`／`PX-33`／`PX-34`／`PX-36` | Active Board 與 Backlog | ☑ **完成**（`artifacts/px/local/w4/`） |
| 5 | `PX-39`／`PX-40`／`PX-41`／`PX-42`／`PX-43`／`PX-62`／`PX-46` | Drawer 內完成「回覆並繼續」 | ☑ **完成**（`artifacts/px/local/w5/`） |
| 6 | `PX-49`／`PX-50` | My Work 一頁看到六類待辦 | ☑ **完成**（`artifacts/px/local/w6/`） |
| 7 | `PX-65`／`PX-66` | 六條旅程的 verdict ＋ 八項任務時間 | ☑ **完成**——六條旅程全綠（J1 32／32、J4 13／13、J15 8／8 對真 daemon；J2／J10／J16 在瀏覽器），`artifacts/px/local/journeys/`。**兩個簽名待人**（出口條件 34、38） |

## 4. Gate 狀態

| Gate | 狀態 |
|---|---|
| `GATE-PX-NO-DAEMON-DIFF` | ☑ 含 `VERSION` 未變 |
| `GATE-PX-CONTRACT-FROZEN` | ☑ 整棵 `contracts/`，不只 `v1/` |
| `GATE-PX-ONE-PROJECT-SCOPE` | ☑ AST；exemption 一項並印出 |
| `GATE-PX-NO-DYNAMIC-SQL` | ☑ AST；exemption 一項（`views.py` 的固定 seed 語句）並印出 |
| `GATE-PX-SINGLE-ATTENTION` | ☑ 含前端不得 `sort` 那八級 |
| `GATE-PX-BOARD-UNCHANGED` | ☑ 16 欄 ＋ bytes 釘死測試 |
| `GATE-PX-MYWORK-READS-STATE` | ☑ **改成 AST**——第一版是 grep，它撞到自己的說明段落 |
| `GATE-PX-BULK-USES-UPDATE` | ☑ AST；斷言呼叫 `update_task` 且無自寫 `UPDATE` |
| `GATE-PX-MIGRATION-ROUNDTRIP` | ☑ 需要資料庫；無資料庫時 SKIP 而非 FAIL。**會先確認資料庫在 head**，不然會把自己的前置條件說成 `0043` 的缺陷（§2.33） |
| `GATE-PX-BUILDER-SUBSET` | ☑ 剖析 `filterBuilder.ts` 對照 `FIELDS`：欄位、運算子、值三者都要是編譯器接受的。**第一次跑就抓到八個欄位裡三個的六個錯值**——兩種語言都不可能自己發現這種漂移，而漂移的症狀是「使用者被邀請去用的下拉選單回 400」 |
| `GATE-PX-JOURNEY-COVERAGE` | ☑ `scripts/px/gate_journey_coverage.py`。三件事：六條旅程都有證據、**每一條斷言**都過（不是看 top-level verdict）、而且**沒有它涵蓋的原始檔比它新**。最後那一項是唯一在「整期都還沒 commit」的狀態下有效的檢查——commit stamp 在那時永遠等於 HEAD。它一寫出來就抓到三條旅程的判定比 `work.py` 舊 |
| `GATE-PX-TOUCH-LIST` | ☑ 含兩側 dependency 清單、`useAsyncResource.ts` |

`scripts/px/gates.sh` 執行全部；`scripts/px/gate_work_invariants.py` 是四個 AST 的那一支。

**`GATE-PX-MYWORK-READS-STATE` 的第一版失敗方式值得記下來**：它是一個 grep，
而它比對到的是自己 module docstring 裡「以後這裡會有 notification」那句話。
這正是 `plan/18/09` §3 item 15 記的那件事——V2.2 出了三個會撞到自己註解的 gate，
而讓這種 gate 變綠最便宜的方法是刪掉解釋規則的那段話。
改成先用 `tokenize` 去掉註解與字串再比對。

**V2.4 gate 的 re-run 從「整套」縮成「一項」**：整套會因為那一期自己的
baseline 與資料庫名稱而失敗，於是本期會因為別人的過期 fixture 而變紅——
一個教讀者忽略紅燈的紅燈。只 re-run `GATE-DV-SINGLE-DONE-PATH`，
因為它是 bulk update 必須寫成迴圈的理由。

## 5. 量測結果

| 項目 | 目標 | 實測 | 日期 |
|---|---|---|---|
| 讀模型一頁 200 張 P95（相位 A ＋ `derive_attention`） | < 1s | **10.2 ms** | 2026-08-23 |
| `work-items` 200 張 P95 | < 1s | **9.97 ms**（帶 derived filter：**8.23 ms**） | 2026-08-23 |
| `work-counts` P95 | < 200ms | **10.54 ms** | 2026-08-23 |
| 相位 B（6 queued） | 基準 | **0.222 ms** | 2026-08-23 |
| 相位 B（60 queued） | 記錄 | **0.261 ms** | 2026-08-23 |
| `derive_attention` 純函式 200 次 | < 10ms | **0.08 ms** | 2026-08-23 |
| bulk 100 張交易 P95 | < 3s | **225 ms** → **上限 100 維持不變**（D96 的下修條件未觸發） | 2026-08-23 |
| `WorkItemCardDTO` 200 張 | 量測 ＋15% | **159,118 bytes**（34 欄），釘死在 **182,985**。前五貴：`id` 9,000／`updated_at` 8,800／`pending_human_action` 6,800／`execution_status` 6,580／`active_run_runner_name` 6,200 | 2026-08-23 |
| `BoardCardDTO` 200 張（真 DTO，seed 20260819） | 釘死基準 | **75,952 bytes**（16 欄；`id` 9,000／`updated_at` 8,800／`active_run_runner_name` 6,200 最貴） | 2026-08-23 |
| 合成 summary（`scripts/tk/measure_board_payload.py`） | 89,251 ± 2% | **89,251 bytes**（可重現；**不是 `BoardCardDTO`**，見 §2.8） | 2026-08-23 |
| `ix_tasks_project_updated` 前／後 | 記錄 | **整塊看板無變化**（200／2000 卡皆然）；`LIMIT 50` 在 2000 卡上 cost 207 → **14.7**、0.396 → **0.059 ms**。見 §2.10 | 2026-08-23 |
| rank backfill 是否洗牌 | 不洗牌 | **0 mismatches**（依 rank 排序 = backfill 前依 `updated_at DESC, id DESC` 排序） | 2026-08-23 |
| `0043` downgrade → upgrade | 可逆 | ☑ roundtrip 通過，5 個 view 重新 seed、rank 無 NULL、四個索引齊備 | 2026-08-23 |

環境：本機 `postgres:16-alpine`（`cliora_px`），固定資料集 seed 20260819（200 卡），
20 次取 nearest-rank P95。原始輸出在 `artifacts/px/local/w0/attention-*.json`，
量測腳本 `scripts/px/measure-attention.py`，佇列 fixture `scripts/px/seed-queued.py`。

**[D92](./01-decisions-and-governance.md) 的成本論證成立。**
佇列從 6 拉到 60（10 倍）之後，相位 B 從 0.222 ms 變成 0.261 ms（**1.18 倍**）——
成本由「一次 runner 查詢」主導，而不是由 per-run 的判定主導。
換句話說「相位 B 的成本綁佇列長度而不是看板大小」不只成立，
它比計畫預期的更平：**綁的其實是那一次查詢**。
這也表示若哪天佇列真的很長，要動的是查詢而不是迴圈。

## 6. 出口條件

四十項可打勾的格子（[`10`](./10-verification-and-exit.md) §11，含 22–31 那一格十項）。
目前 **34／40 達成、3 項需要人的動作、3 項需要真的 daemon**。

| ☑/☐ | # | 條件 | 證據 |
|---|---:|---|---|
| ☑ | 1 | My Work 十秒內找到等我的卡 | `artifacts/px/local/w6/01-my-work.png`；六區一頁，跨全部可見專案 |
| ☑ | 2 | Backlog 與 Active Board 分離 | Active Board 是四欄（不含 backlog）；list 版面的預設 filter 是 `lifecycle eq backlog` |
| ☑ | 3 | Board／List 同一資料來源與同一 attention 投影 | 兩者呼叫 `work-items`，只有 `layout` 與預設 filter 不同 |
| ☑ | 4 | saved personal／project view 權限正確 | `test_work_api.py` 五支（含 `VIEW_NOT_OWNED` 是 403 不是 404） |
| ☑ | 5 | Drawer URL 可重整、分享與返回 | J10；`drawer.test.ts` 四支 |
| ☑ | 6 | 開關 Drawer 不丟 view／filter／scroll | J10 逐項斷言 |
| ☑ | 7 | optimistic mutation 失敗一律回滾 | `queryCache.test.ts`「rolls back before the caller sees the failure」 |
| ☑ | 8 | 移動拒絕給 machine code ＋ 可行動訊息 | `board.test.ts` 四個 code 各一支 |
| ☑ | 9 | human approval 顯示 actor 與時間 | 本期未動 gate 路徑；`tasks.gates` 仍存 `{approved_by, approved_at}` |
| ☑ | 10 | agent token 進不了 human approval | run token scope 未變；六個新端點各一條 403 |
| ☑ | 11 | secret 不出現在 API／UI／log | 既有 redaction 套組回歸（`scripts/px/evidence.sh` 第 3 步） |
| ☑ | 12 | Agent Run 與 Session 邊界未變 | 既有負面套組回歸 |
| ☑ | 13 | V1 terminal／session／workspace／file 回歸 | 全套 1,345 ＋ 794 通過 |
| ☑ | 14 | **回滾演練** | `scripts/px/rollback-drill.sh`，四步全綠，`artifacts/px/local/rollback/` |
| ☑ | 15 | `PROJECTS_ENABLED=false` 時 V1 不受影響 | **關旗部署實跑過了**：`journeys.spec.ts` 的 `J16 — with the project layer off`，對一個 `CLIORA_PROJECTS_ENABLED=false` 起來的 Central。側欄是 pre-V2 的樣子（沒有 Projects、沒有 My Work），三個 V1 目的地都在，而 `/api/projects`、`/api/me/work-items`、`/api/me/attention-counts` 都是 **404 而不是 403**。截圖：`artifacts/px/local/journeys/j16-02-flag-off-rail.png`、`j16-03-flag-off-projects-url.png` |
| ☑ | 16 | 200 張卡效能 gate | §5 全部在預算內 |
| ☑ | 17 | 鍵盤可完成核心任務 | Move dialog 是正式路徑而非備援；Drawer focus trap／restore 有測試 |
| ☑ | 18 | 零 undefined CSS token | `check-tokens.mjs`（本期並修好它會撞到自己註解的缺陷） |
| ☑ | 19 | 視覺回歸 | `artifacts/px/local/w3/` 逐頁截圖 ＋ w0／w4／w5／w6 |
| ☑ | 20 | migration rehearsal ＋ rollback drill | `GATE-PX-MIGRATION-ROUNDTRIP` ＋ 演練 |
| ☑ | 21 | release note 列出 known limitations | `docs/release-note-work-views.md` |
| ☑ | 22–31 | `alpha.2`／`alpha.3` 的十項 | 交叉引用（本期未改動它們守的東西） |
| ☑ | 32 | `BoardCardDTO` 與 `/board` 未變且未變大 | `GATE-PX-BOARD-UNCHANGED` ＋ bytes 釘死測試 |
| ☑ | 33 | `agentd` 0.14.1 行為不變、daemon diff 為零 | diff 為零由 `GATE-PX-NO-DAEMON-DIFF` 斷言（含 `VERSION` 未變）；**完整 run 生命週期已跑**——J1 用 0.14.1 的節點走完派工 → 認領 → 對話 → 交付 → 驗證 → 完成 |
| ☐ | 34 | `v2` → 上游由人工核准 | **提案已送出，核准仍待人**：`v2` 已 push（`bf9633c`），PR [#45](https://github.com/Lei-k/cliora/pull/45) → `staging` 已開。**未合併、未打 tag。** 條件全綠只是取得提案資格，合併是一個獨立的人的決定 |
| ☑ | 35 | attention 在三處對同一張卡一致 | `test_attention_consistency.py` 逐卡比對三個端點 |
| ☑ | 36 | 相位 B 與 `resolve_waiting_reason` 一致 | 同上，四種形狀各一 |
| ☑ | 37 | 未新增對外連線、未新增推播通道 | `GATE-KN-NO-NEW-EGRESS` 形狀的 httpx 檢查 ＋ 無 WS 票券新增 |
| ☐ | 38 | **SR-3 具名簽核** | **人的動作。** `docs/security-review-v2p1.md` 證據齊備、簽名欄空著 |
| ☑ | 39 | `/board` 已標 deprecated 且 `ProjectDetailView.vue` 已刪除 | OpenAPI `deprecated: true`；檔案已刪，14 支測試移植 |
| ☑ | 40 | 每個波次都留下可看的產出 | `artifacts/px/local/w0`、`w3`、`w4`、`w5`、`w6`、`journeys` |

### 三項未達成的，逐項說出為什麼

**#34 與 #38 是人的動作**，而且刻意留白。第 38 項的簽名要簽的不只是八列表格，
還有 [`11`](./11-open-measurements.md) §1 那一句「有 membership 時 counts 不洩漏存在性」
——那一句本期證不出來，而簽名的人要知道自己在簽它。

**#15 補上了，而它本來不該被記成「缺一張截圖」。**
旗標是 import 期讀的，所以它在一個跑著的 Central 裡切不掉——
那正是這一半拖這麼久的原因：它需要自己的一份部署，而不是一張截圖。
記成「缺一張畫面」讓一件需要動作的事看起來像一件需要順手的事。

跑起來之後多證了一件本來只有元件測試的事：
`/api/projects`、`/api/me/work-items` 與 `/api/me/attention-counts` 回 **404 而不是 403**。
403 會確認那條路由存在，而「這個部署沒有 project 這一層」不是一個授權答案（ADR 0028）。
兩條 `/api/me/*` 是本期新增的，所以這是它們第一次被這樣問。

**#33 已經補上了。** J1 用 0.14.1 的節點走完了一次完整的 run 生命週期
（派工 → 認領 → 三輪對話 → 規格 → 提案 → 實作 → 驗證 → 完成），
`GATE-PX-NO-DAEMON-DIFF` 同時保證那個節點的程式碼一行都沒有動。

### 一次要記住的錯誤：「沒有 Go 工具鏈」是假的

這份文件、`README`、SR-3 §5、release note 與 `evidence.sh` 都曾寫著
J1／J4／J15「需要 Go 工具鏈，而這個環境沒有」。**那是錯的。**
Go 1.26.5 在 `/usr/local/go/bin`，而 `scripts/e2e/run-stack.sh` 第 106 行
本來就會把它加進 `PATH`——也就是說，那個 harness 從第一天就能跑。

真正的原因是沒有人去跑。把它寫成環境限制，代價不是一行不精確的字：
**它讓一件做得到的事看起來做不到**，於是三條旅程被歸到「等環境」而不是「等人」，
而其中一條是本期宣稱的目的本身。一句寫錯的理由比一個空著的核取方框更難發現，
因為空方框會被追，而一個附了理由的空方框會被接受。

跑起來之後，三條旅程各找到一個真的缺陷（§2 的最後三條），
沒有一個是任何 in-process 測試能找到的。

## 7. 旅程

| # | 旅程 | 狀態 |
|---|---|---|
| J1 | 主旅程（**不可降級**） | ☑ **32／32** — `artifacts/px/local/journeys/j1.json`。真的 daemon、真的 continuation、真的 knowledge 引用；**引用那一段沒有降級** |
| J2 | Backlog → Ready | ☑ `artifacts/px/local/journeys/j2-*.png` |
| J4 | My Work → 回答 → continuation | ☑ **13／13** — `artifacts/px/local/journeys/j4.json` |
| J10 | filter 存活 ＋ browser back 順序 | ☑ `artifacts/px/local/journeys/j10-*.png` |
| J15 | No eligible runner → 修正 → 認領 | ☑ **8／8** — `artifacts/px/local/journeys/j15.json`。畫面那一半另有 `artifacts/px/local/w5/02-drawer-no-runner.png` |
| J16 | flag 矩陣 | ☑ **兩半都跑了**：開旗下 V1 目的地全部可達（`j16-01`）；關旗部署另起一份 Central 實跑（`j16-02`、`j16-03`），side rail 是 pre-V2 的樣子而 project 層是 404 |

**J1 是不可降級的那一條，而它過了。** 一句模糊需求走到 `done`，
全程沒有開過一個 terminal session（最後一條斷言就是 `terminal_sessions` 的計數為零），
而且中間每一步都是真的：三輪 continuation 各由 daemon 認領一次，
規格裡引用了三個回答，實作 run 從 `cliora knowledge context` 讀到被接受的規格並引用了它。

`scripts/px/evidence.sh` 的第 9 步現在**讀這三個 JSON 的判定**而不是印 SKIP，
而檔案不存在時是 FAIL 並附上該跑的指令——一個少掉的行會被讀成「六條都過了」。
