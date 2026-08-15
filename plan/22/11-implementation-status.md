# 11 — 實作狀態（V2.5）

> **狀態：`RQ-00`…`RQ-12` 全部實作完成，`make check` 全綠，十二個 gate 全 PASS。**
> 尚未合併——`v2` → `dev` 一律由人決定（`research/02/README` 第 6 條）。

本檔記錄**實作時與計畫不同的地方**，以及那些差異各自的理由。
計畫是讀著程式碼寫的，所以差異比前幾期少；但有十三處，
其中**四處是計畫寫錯了**，五處是實作時才看得見的細節，
四處是實作中發現的缺陷（一個既有的、三個補前端入口時才浮出來的）。

## 1. 完成度

| Ticket | 狀態 | 交付物 |
|---|---|---|
| `RQ-00` | ✅ | `scripts/rq/capture-baseline.sh`、`artifacts/rq/local/baseline/`（七項，含新增的 `contract-tree.sha256`） |
| `RQ-01` | ✅ | ADR 0034（`proposed`）、PRD §8.16（七節、七個 FR-SPEC）、traceability 168 條、error catalog 23 個新 code |
| `RQ-02` | ✅ | migration `0039`、`DocumentPatchProposal` model、`card_kind`／`sections`／兩個 `run_id`、兩個索引 |
| `RQ-03` | ✅ | dispatch 四道新拒絕、`card_kind` 鎖定、`AGENT_FORBIDDEN_FIELDS` 加一 |
| `RQ-04` | ✅ | 兩個情境包渲染器、分層預算、伺服器端「一次一個問題」 |
| `RQ-05` | ✅ | `POST /api/cli/runs/spec` |
| `RQ-06` | ✅ | `POST /api/cli/runs/proposal` ＋ 提案樹六道驗證 |
| `RQ-07` | ✅ | 拒絕帶理由、`overrides`、相依翻譯、`remaining_item_ids` |
| `RQ-08` | ✅ | `PatchProposalService` ＋ 四條路由 |
| `RQ-09` | ✅ | agentd **0.12.0**：五個新子命令、本機提問檢查、embed 的規格範本 |
| `RQ-10` | ✅ | `ProposalTree.vue`、`PatchProposals.vue`、規格審閱九節、版本並排、來源可追溯、五種徽章、Requirements 分頁的兩顆派工按鈕 |
| `RQ-11a` | ✅ | mockup 卡 dispatch 拒絕；`ui` gate 自動停用的既有行為補上測試 |
| `RQ-11b` | ⏸ | **本期不做**（D5）。設計在 `08-…md` §3 |
| `RQ-12` | ✅ | `scripts/rq/gates.sh`（12 檢查）、安全審查、release note |

### 1.1 測試

| 層 | 數量 | 備註 |
|---|---|---|
| Central（全部） | **1727 passed** | 其中 V2.5 新增 **28** 條（`test_clarification_and_decomposition.py`） |
| daemon | 全綠 | CLI 新增 **6** 條，含「本機與伺服器同一組 fixture」的 5 個 subtest |
| 前端 | **673 passed** | 新增 `ProposalTree.test.ts` **10** 條、`PatchProposals.test.ts` **6** 條、派工按鈕 **5** 條 |
| traceability | 32 passed、blocking=0 | FR-SPEC-002…008 以 `proposed` 生命週期加入 |
| gates | **12 PASS** | `scripts/rq/gates.sh` |

## 2. 計畫寫錯的四處

### 2.1 `agent_runs_enabled` 這個 fixture 不存在

`03`／`04` 的測試設計假設有兩個 fixture。實際上 `projects_enabled`
**同時打開兩個旗標**（`conftest.py:141`），而註解寫明了為什麼：
V2.2 起的路由帶兩道 guard，內層旗標關著時測到的是「路由不存在」而不是「被拒絕」。

**照計畫寫會得到 18 個 fixture-not-found。** 已改用 `projects_enabled`。

### 2.2 `card_kind` 要同時進 `UpdateTaskRequest`，計畫只寫了 `EDITABLE_FIELDS`

`EDITABLE_FIELDS` 管服務層，`UpdateTaskRequest` 是 `extra: forbid` 的 Pydantic 模型。
只改前者的話 `PATCH` 會回 `422 extra_forbidden`——**而錯誤訊息看起來像欄位名打錯**。

### 2.3 出口條件裡的 dispatch 成功是 **202 不是 201**

`00-…md` §1 的反面清單假設 dispatch 成功回 201。實際上沒有 runner 上線時回
**202 ＋ `waiting_reason`**，那是佇列正常運作而不是拒絕。
「一般 UI 卡照常執行」那條出口條件的驗收因此是 202。

### 2.4 十個 gate 實際上是十二個檢查

`09-…md` §3 列十個。實作時 `GATE-RQ-TOUCH-LIST` 拆成四個目錄各一個檢查
（`runtime`／`runner`／`workspace`／`gitfetch`），因為一個合併的檢查只會說
「禁區被動了」而不說是哪一個。**十個 gate、十二行輸出。**

## 3. 實作時才看得見的五處

### 3.1 兩個 `run_id` 造成了外鍵環，而 SQLAlchemy 會警告

加上 `feature_specs.run_id` 與 `task_proposals.run_id` 之後：

```text
feature_specs → task_runs → tasks → task_proposals → feature_specs
```

`sorted_tables` 排不出來，SQLAlchemy 警告「this warning may raise an error in a
future release」。測試會過，`create_all` 目前也會過——**是一個會在升級 SQLAlchemy 時炸的東西**。

**處置**：兩個外鍵各給一個名字並標 `use_alter=True`。
DDL 不變（migration 本來就寫死），改變的是 metadata 可以排序，
而**名字本身就是文件**：這兩條邊是讓圖變成環的那兩條。

### 3.2 `GATE-RQ-HUMAN-ACTOR` 第一版把 DTO 當成寫入

`_proposal_dto(decided_by=…)` 是**讀**，不是寫。第一版的建構子掃描把三個 DTO 工廠函式全標成違規。

**處置**：只有 `db/models.py` 裡的 class 名稱算數，而那份名單是**從 models.py 掃出來的**
不是手寫的——手寫的話，下一張帶決定欄位的表會因為沒被列進去而豁免。

**為什麼這個修正值得寫下來**：一個會誤報的 gate 會訓練下一個人放寬 `ALLOWED`，
放到它什麼都不擋為止。

### 3.3 兩個 gate 第一版比對到自己的說明文字

`GATE-RQ-NO-PATCH-APPLY` 用 grep 找 `open(`，比對到自己 docstring 裡的
「calls no `open(`」。`GATE-RQ-CONTEXT-DISPATCH` 數 `card_kind` 分支，
數到 dispatch 的四道拒絕。

**處置**：兩個都改成 AST。第二個改成斷言**呼叫點唯一**
（三個渲染器只能被 `_context_for` 呼叫），那才是真正要守的性質——
dispatch 依 `card_kind` 分支是完全正當的。

### 3.4 提案樹的「未分類任務」原本是二等公民

第一版的元件用巢狀 `v-for` ＋ 一個 fallback 分支處理沒有 Story 的卡片，
而那個 fallback **只渲染勾選框與 DoR 徽章**——沒有編輯按鈕、沒有 delivery、
沒有缺項說明。三條測試因此紅。

**這不是測試的問題，是元件的缺陷**：一張卡不該因為歸檔方式而長得不一樣，
而那正是 Monstrare 的看板保留「（未分類任務）」桶的理由。

**處置**：`groups` computed 把樹攤平成有標題的群組（含一個 `__unfiled__`），
一份 row 樣板服務所有卡片。

### 3.5 CLI 的失敗路徑測不到，因為 `exit()` 會 `os.Exit`

「檔案還在」那句承諾沒辦法透過執行命令來斷言。
沿用 `RunOfflineMessage` 的做法：抽成常數 `PayloadSurvivedMessage`，對常數斷言。

## 4. 實作中發現的四個缺陷（本期都修了）

### 4.1 `accept()` 從來沒有翻譯 `depends_on`

計畫（`04-…md` §4.4）預測了這件事，實作確認了：V2.1 的 `accept()` 的 `fields` 裡沒有
`depends_on`，所以拆解出來的相依關係在接受的那一刻消失，
**而 `dependencies_known` 那個 readiness 項目仍然是 true**。

卡片宣稱「相依已辨識」，資料庫裡沒有相依。

**修法**（三步，順序是承重的）：先建立所有被勾選的卡片、
再翻譯 `depends_on`、最後決定提案狀態。指向沒被勾選節點的相依**不建、回報、
並讓那張卡因為缺 `dependencies_known` 落 `backlog`**。

**這一格計畫寫「最容易做錯」，而它確實有兩個都錯的直覺**：
建立那條相依（指向不存在的卡）、或靜默略過（卡片說謊）。

### 4.2 Requirements 分頁的派工按鈕：錯誤沒有地方顯示

補按鈕的時候發現，**Requirements 分頁根本沒有錯誤橫幅**——`taskError` 只渲染在
Board 分頁裡。而本期新增的四道 dispatch 拒絕**全部落在這個分頁上**。

一條測試（「派工被拒時卡片留著，並說出留下的是哪一張」）因此紅。
**這不是測試的問題**：一個看不見的拒絕，跟一顆按了沒反應的按鈕沒有分別。

處置：把橫幅加到 Requirements 分頁（`data-requirement-error`）。

### 4.3 兩顆按鈕的失敗路徑比成功路徑重要

`sendToAgent` 是兩個請求。第二個經常失敗——「專案還沒登記儲存庫」、
「沒有可用的 runner」、以及本期的四道拒絕。三條規則：

1. **卡片留著。** 失敗就刪卡的話，「還沒有 runner 上線」這種**等待**會刪掉一張完全正確的卡。
2. 訊息說出卡號並連過去，因為那時卡片已經存在。
3. 需求列記得它，所以按第二次不會生出第二張卡。

### 4.4 測試路由缺兩條，症狀是「按鈕不存在」

四條派工測試一開始全紅，錯誤是 `Unable to get [data-clarify=…]`。
原因不是按鈕沒渲染，是 `testRouter()` 沒有 `requirement-detail` 與 `task-detail`，
**`RouterLink` 解析失敗讓整個 `<li>` 的其餘部分沒有渲染出來**。

值得記一筆，因為錯誤訊息（「找不到這個選擇器」）指向的是完全錯誤的方向。

## 5. 沒做的與為什麼

| 沒做 | 理由 |
|---|---|
| `RQ-11b`（mockup 預覽） | D5。三個理由，第三個是 Monstrare 的 mockup 關卡依賴平台沒有的 `design-system.md` |
| E2E ①／②（`09-…md` §5） | 需要 `scripts/e2e/run-stack.sh` 起完整堆疊 ＋ 一台 runner。**28 條 API 層測試涵蓋了每一條斷言**，缺的是「同一個瀏覽器連續走完」那一次。列為合併前的手動驗收 |
| Traqora 上的真實需求驗收 | 同上，且 `10-…md` §1 的 M-RQ-0 建議先查人工流程有沒有人用 |
| `security` review gate | `00-…md` §0 C 類，預設不做 |
| ~~Requirements 分頁的兩顆派工按鈕~~ | ✅ **已補**（§4.2） |
| ~~Patch 提案畫面~~ | ✅ **已補**（§4.3） |

**§5 現在只剩三列，而三列都是「需要別的東西才驗得了」或「刻意不做」**，
沒有一列是「範圍內但沒寫」。

## 6. 出口條件對照

| # | 條件 | 狀態 | 證據 |
|---|---|---|---|
| 1 | 模糊需求 → 釐清 run → 訊息串提問 → 規格草稿 | ⚠️ **API 層全綠，未走完整 E2E** | `test_a_run_submits_a_spec_version_authored_by_a_runner_not_a_person`、`test_a_second_question_is_refused_…` |
| 2 | 未解決問題 → 核准 409 ＋ 指名；按鈕同時停用 | ✅ | V2.1 既有測試 ＋ `RequirementDetailView` 的 `data-approve-reason` |
| 3 | 未核准不得拆解 | ✅ | dispatch ＋ 提案提交兩處 |
| 4 | 每張 Task 帶 DoR；缺項落 `backlog` | ✅ | `test_a_dependency_on_an_unaccepted_item_…` |
| 5 | 部分接受；被拒提案保留理由 | ✅ | `test_a_partly_accepted_proposal_says_what_remains`、`test_rejecting_a_proposal_requires_a_reason_and_keeps_it` |
| 6 | 卡片顯示來自需求 #N | ✅ | `TaskDetail.vue` 的 `data-provenance` |
| 7 | 釐清 run 帶機密 → dispatch 被拒 | ✅ | `test_a_clarification_card_declaring_a_secret_is_refused_at_dispatch` |
| 8 | `delivery: none` → 遠端零變更 | ⚠️ **結構上成立，未對真實遠端量過** | 四道拒絕使 `branch`／`pull_request` 不可達 |
| 9 | Agent 核准／接受被拒 | ✅ **401** | `test_a_run_cannot_approve_the_specification_it_wrote` |
| 10 | 24h 逾時保留規格草稿 | ⚠️ **機制在，未跑過 24h** | reaper 未改；`spec_count` 由 `feature_specs` 數 |
| 11 | 未啟用 tunnel 的四子項 | ✅ 全四項 | `test_a_mockup_card_is_refused_…`、`test_an_ordinary_implementation_card_is_unaffected_…` |
| 12 | 啟用 tunnel 之後 | ⏸ **本期不驗**（D5） | — |
| 13 | 旗標關閉回歸 | ✅ | `make check` 內既有套組 |
| 14 | `contracts/` 逐位元組相同 | ✅ | `GATE-RQ-CONTRACT-FROZEN` |
| 15 | 一次一個問題（三個判定） | ✅ | 三條測試各一個判定 |
| 16 | 本機與伺服器同一條規則 | ✅ | 同一組 fixture 餵兩邊（5 subtest） |
| 17 | 對別的需求提案 → 404／401 | ✅ | `test_a_decomposition_run_may_only_propose_for_its_own_requirement` |
| 18 | 相依指向未接受節點的三件事 | ✅ | 同 #4 |
| 19 | `overrides` 兩條限制 | ✅ | `test_an_override_cannot_reach_readiness_…` |
| 20 | `card_kind` 執行後鎖定 | ✅ | `test_a_card_kind_is_fixed_once_the_card_has_been_run` |
| 21 | 高風險關鍵詞 → 422 | ✅ | `test_the_proposal_tree_is_validated_at_submission` |
| 22 | diff 以純文字渲染 | ✅ | `PatchProposals.test.ts` 的 `<script>` fixture：斷言它是文字、`querySelector("script")` 為 null、`window.__pwned` 未定義 |
| 23 | 接受 patch 不寫任何檔案 | ✅ | `GATE-RQ-NO-PATCH-APPLY` ＋ `test_a_run_proposes_a_patch_…` |
| 24 | 情境包 ≤ 6 KB 且規則段不被截 | ✅ | `test_the_clarification_pack_never_mentions_secrets_and_fits_the_budget` |

**23 條裡 20 條全綠、3 條部分（#1／#8／#10）、1 條本期不驗（#12）。**

三條部分達成的共同點很單純：**斷言都在，缺的是跑一次真實情境。**
#1 與 #8 要一台 runner ＋ 一個真的遠端；#10 要等 24 小時。
**沒有一條是缺程式碼的**——#22 隨 `PatchProposals.vue` 一起關掉了。

## 7. 合併前建議做的兩件事

1. **M-RQ-0**（十分鐘）：查三張表的列數（`10-…md` §1）。
   D28 把它定成「V2.5 值不值得做的早期訊號」，而它到今天還沒有被讀過。
2. **E2E ① 手動走一次**，在 Traqora 上用一句真實的模糊需求。
   這一次會同時關掉 #1 與 #8，也是唯一還沒有人從瀏覽器連續走完的一段。

（原本的第 3 件——補兩個前端入口——已經做完，見 §4.2／§4.3。）
