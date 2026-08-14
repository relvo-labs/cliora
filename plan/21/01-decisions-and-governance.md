# 01 — 基線、決策文件與治理（`DV-00`／`DV-01`）

本檔是本期的「寫下來的東西」：基線、一項擋開工的量測、一份新 ADR、三則增補、
PRD 的一節、traceability，以及**一張回溯清單**——V2.3 留下的一個相容洞，
本期修它，而修它的理由要寫在這裡而不是藏在 commit message 裡。

## 1. `DV-00` — 基線擷取

沿用 `plan/20` 的做法：**`scripts/dv/capture-baseline.sh` 是
`scripts/ar/capture-baseline.sh` 的一層 `BASELINE_OUT` 覆寫**，不複製那 60 行。
（`plan/20/08` §3 第 2 條記了為什麼：兩份會在其中一份被修好的第一時間開始分歧。）

```bash
AR_BASELINE_ALLOW_DIRTY=1 \
CLIORA_DATABASE_URL=postgresql+asyncpg://cliora:cliora@127.0.0.1:5432/cliora_dv_baseline \
  scripts/dv/capture-baseline.sh
```

| 檔案 | 內容 | 預期 |
|---|---|---|
| `COMMIT` | commit ＋ 時間 ＋ 未提交路徑清單 | 未提交的應只有 `research/02/`、`plan/21/`、`scripts/dv/` |
| `openapi-flags-off.json` / `-on.json` | 旗標關閉／開啟的 OpenAPI | **兩份逐位元組相同**（那個「相同」本身是要守的性質） |
| `schema.txt` | 表清單 ＋ 目前 revision | **37 張表**、`0034_seed_secret_action` |
| `contract-fixtures.txt` | fixture 清單 | **172 行** ＝ 171 個檔（70 valid ＋ 101 invalid）＋ `manifest.json` |
| `frontend-routes.txt` | 路由清單 | 19 條 |
| `terminal-latency.json` | 終端延遲 | **三次連續量測取 p50 的中位數**（`plan/20/08` §3 第 3 條的修訂：單次 50 samples 的 p95 對尾端離群值太敏感，兩次 idle 基線相差過 27%） |

> ⚠️ **閘門一**：基線完成前不得動任何程式碼。
> 例外與 V2.2／V2.3 一致：擷取器本身（`scripts/dv/`）。

## 2. `DV-00` — M6（**唯一一項擋開工的量測**）

`research/02/10` §5 把 M6 標成 V2.4 開工前要有答案的：

> **`git status --porcelain` 在最大的實際 repo 上要多久？** → 決定證據採集的逾時值。

### 2.1 為什麼它擋開工

evidence 的 `git_state` 是在 **run 的最後一步**採集的，而那一步之後才送 `run.complete`。
逾時值訂太短 → 大 repo 上每一次都採不到證據，而症狀是「證據區塊是空的」，
看起來像功能沒做；訂太長（或不訂）→ 一個卡住的 `git status`
會讓 run 的最後一步無限期停住，**而租約仍在續**，所以 Central 看到的是一個永遠在
`finishing` 的 run。兩種都不是可以事後調的東西：第一種會讓人以為證據功能不可靠，
第二種會產生一種新的卡死。

### 2.2 怎麼量

```bash
# 三種規模，各 10 次，取 p95。乾淨與髒兩種狀態各量一次。
for repo in <small> <medium> <largest-available>; do
  for i in $(seq 10); do
    /usr/bin/time -f '%e' git -C "$repo" status --porcelain >/dev/null
  done
done
```

**三個尺寸的定義**：small ＝ 本 repo；medium ＝ Traqora；largest ＝
手上能找到的最大的一份（若沒有，用 `git clone --depth 1` 一份公開的大 repo，
並在紀錄裡寫明它不是我們的實際工作負載）。

**同時量 `git diff --stat` 與 `git diff`**——三者都在同一個採集步驟裡，
而 `git diff` 在髒的大 repo 上比 `status` 慢得多。

### 2.3 判準

逾時值取 **p95 的 4 倍，並向上取整到 5 秒的倍數，下限 10 秒**。
四倍不是安全邊際的慣例，是因為 run 結束時機器上通常還有**其他 run 在跑**，
而本地磁碟是它們共用的——量的時候是 idle，用的時候不是。

**若最大的 repo 上 p95 超過 5 秒**：evidence 的採集要改成「可以失敗」而不是「必須完成」，
即逾時之後照樣送 `run.complete`，evidence 那一列標 `collection_timed_out`。
**那是一個設計改動不是一個參數調整**，所以要在開工前知道。

## 3. `DV-01` — ADR 0033：交付模式與 PR 建立

`docs/adr/0033-v24-delivery-modes-and-pull-request-creation.md`，狀態先 `proposed`。

### 3.1 §1 Context

三句話：卡片有五種成果離開的方式；平台在 V2.3 已經會 push；
**開 PR 是平台第一次以「一個帳號」的身分在別人的 repo 上留下痕跡**。

### 3.2 §2 Decision — `source` × `delivery` 的兩張表

`source` 三值（`none`／`repo`／`existing_branch`，V2.1 已定）與
`delivery` 五值，**以及它們為什麼是兩個獨立欄位**：要不要程式碼、成果怎麼離開，是兩個問題。

| `delivery` | daemon 做什麼 | Central 做什麼 | 完成的證據 |
|---|---|---|---|
| `none` | 什麼都不推 | 什麼都不做 | 完成摘要 ＋ 驗證報告 ＋ 卡片訊息 |
| `artifact` | 什麼都不推 | **數產物**（D8） | **至少一件卡片產物** ＋ 完成摘要 |
| `branch` | push `cliora/<card_ref>-<run_seq>` | 什麼都不做 | 分支連結 ＋ diff 摘要 |
| `pull_request` | push（**wire 上看到的是 `branch`**，D2） | **確認分支已推 → 開 PR** | PR 連結 ＋ diff 摘要 |
| `existing_pr` | push 到 `base_branch`（**必須在 `cliora/` 內**，D7） | 在該 PR 上留一筆訊息 | 追加的 commit ＋ PR 連結 |

**三個誠實性規則**（寫進 Decision，不是註腳）：

1. **`none`／`artifact` 但工作目錄有變更 → 不得靜默丟棄。**
   結果標示「本卡宣告不產出程式碼變更，但偵測到 N 個檔案變更」，
   **並把 diff 直接附成一件產物**。
   ⚠️ **現況對 `artifact` 只做到一半**：`ShouldAttachDiff`（`supervisor.go:301`）
   涵蓋兩者，`SummaryText`（:316）只對 `none` 說那句話。`DV-04` 讓兩者共用一個述詞。
2. **沒有變更就沒有 PR。** `pull_request` 但 diff 是空的 → run 成功、結果「無變更」、
   **provider API 從未被呼叫**。
3. **`artifact` 但一件產物都沒有 → run 不算成功。** 宣告了要交付卻沒交付，不能算完成。

### 3.3 §3 Decision — PR 由 Central 開（D1／D2）

這一節要把三件事寫死：

- **`provider_token` 永不下放到 node。** 它今天就在 `secrets.py:48` 的
  `UNDELIVERABLE_KINDS` 裡，本期把「為什麼」寫下來：
  五條硬約束約束的是 git push，**攔不到一個 HTTPS 請求**。
- **wire 上的 `delivery` 只有三個值**，而 `pull_request`／`existing_pr` 是
  **Central 的意圖，不是 node 的指令**。這一條讓 daemon 不必知道 PR 這件事，
  也讓未升級的 node 不會靜默丟棄 offer。
- **PR 建立在接收迴圈之外**（D17）。理由與 `runs.py` module docstring 記的一樣。

### 3.3b §3b Decision — 驗證命令的兩個來源與 `origin`（D4）

2026-08-14 裁決之後，這一節要把四件事寫死：

1. **兩個來源，都是平台的儲存面**：`projects.verification_commands`（`project.manage`）
   與 `tasks.verification_commands`（**`task.approve`**）。
   **沒有任何請求 payload 能命名一個命令**——SEC-002 的修訂不變式逐字保留。
2. **卡片宣告的授權是 `task.approve` 而不是 `task.update`**，
   而理由要引用 `agent_auth.py:51` 的既有註解：那個動作是 run 憑證
   **永遠不能持有的那一半**，拆開它正是為了 token scope。
3. **`origin` 是第二軸**：`source` 是「誰觀察到」，`origin` 是「誰指定」。
   `machine_verified` 的定義因此是**「執行者沒有選擇要跑什麼」**，
   而不是「命令來自哪一張表」——這一句是日後判斷這個分級還成不成立的判準。
4. **代價**：兩張卡可以用不同的標準宣稱自己完成。
   三個收斂點（可見性、`require_project_verification`、指標）寫進 Consequences，
   **不是寫進註腳**。

### 3.4 §4 — **紅線 5 的拒絕清單**（本 ADR 最重要的一節）

以「這些路徑不存在」的形式寫，並列出各自的驗收方式：

| 不做的事 | 不存在的形式 | 驗收 |
|---|---|---|
| 自動合併 | daemon 的 git 子命令表沒有 `merge`／`rebase`；Central 的 provider 動作表沒有 merge | `GATE-DV-PROVIDER-VERBS` ＋ 既有的 `GATE-SC-PUSH-ARGV` |
| approve 自己的 PR | provider 動作表沒有 review 相關動作 | 同上 |
| 關閉別人的 PR | 同上 | 同上 |
| 動 tag／release | 兩張表都沒有 | 同上 |
| 對任意 node 執行任意命令 | 沒有這個 API；驗證命令來自**兩個平台儲存面**，都不是請求 payload（D4） | 一條測試：Central 從不從 request payload 讀 `verification_commands`；另一條：卡片那一份要 `task.approve` |
| delivery 的第六種 | `DELIVERIES` 是 frozenset，且 `GATE-DV-DELIVERY-COVERAGE` 要求每個值在 dispatch、offer 組裝、Done Gate 三處都有分支 | gate |

### 3.5 §5 Alternatives rejected

照 `research/02/06` 的三條，各補一句「為什麼在這個 repo 上更不可行」：

- **只有一種交付模式**：會逼所有調查型任務開空 PR。
  而本 repo 的 V2.5 全部是調查型（釐清與拆解 run 的 `delivery` 是 `none`）。
- **讓 delivery 由 Agent 自行決定**：那是卡片的意圖，不是執行者的選擇。
  而且它與 D4 是同一個形狀的錯誤——把一個「誰負責」的問題交給被驗證的一方。
- **允許 `merge` 作為第六種模式**：紅線 5，`version2.md` §13 已明列不做。

### 3.6 §6 Consequences

要寫的三條代價：

1. **平台開始以一個身分在別人的 repo 上留痕跡。** 那個身分是 `provider_token` 的持有者，
   而 PR 的作者欄會顯示它——**不是那個按下派工鍵的人**。
   Console 上要顯示「這個 PR 由 <token 的擁有者> 開出」，否則 repo 上的其他人無從追溯。
2. **`existing_pr` 的範圍被硬約束限制住**（D7）。這一條要寫進 release note，
   因為它看起來像 bug。
3. **Central 有了一個對外的網路依賴。** provider 掛掉時 `pending_pr` 的 run 會累積，
   而那要有一個上限與一個可見的地方（`04-…md` §5）。

## 4. `DV-01` — 三則增補

不新寫 ADR，附在既有的之後。**三則各自對應一個既有 ADR 被本期改變的部分。**

### 4.1 ADR 0029 增補 C：`features` 與能力宣告（D3）

- **C1**：`runner.register` 新增 `features`，未帶時**視為空集合**。
- **C2**：**預設極性與 V2.3 的兩個布林相反**，理由寫清楚：
  `run_untagged`／`accept_secrets` 是拒絕旗標（不帶＝不拒絕），
  `features` 是支援旗標（不帶＝不支援）。
  一個寬鬆預設的支援旗標等於**假設沒升級的機器會做新功能**。
- **C3**：Central 在組 offer 時，**只有 node 宣告了對應 feature 才填入相關內容**。
  這是「新增能力」的通用做法，本期之後每一個新 `spec` 內容都走它。

### 4.2 ADR 0031 增補 B：`existing_pr` 與分支來源（D7）

- **B1**：五條硬約束一個字不改。
- **B2**：`existing_pr` 的 `base_branch` 必須在 `cliora/` 命名空間內，
  **在 dispatch 當下拒絕**，而不是在 push 時。
- **B3**：`run_branch()`（`runs.py:1064`）的三值處置：
  `branch`／`pull_request` → 新建 `cliora/<card_ref>-<seq>`；
  `existing_pr` → 沿用 `base_branch`（已驗證在命名空間內）；
  `none`／`artifact` → 空字串。

### 4.3 ADR 0032 增補 A：`provider_token` 的使用路徑

- **A1**：這個 kind **在 V2.3 存得下來但沒有任何程式碼會用它**；本期是它第一次被使用，
  而使用的地點是 **Central 的記憶體，不是任何 node**。
- **A2**：它的解密發生在 PR 建立的背景工作裡，**不在接收迴圈裡**（D17），
  所以 D1（V2.3）「解密在 `poll()` 裡」那條約束不適用於它——**兩者是不同的路徑**，
  這一句要寫，否則下一個人會以為機密解密只有一個地方。
- **A3**：下放稽核的形狀不變（記名稱不記值）。PR 建立**另外記一筆**
  `audit_actions.PR_CREATE`，含 repo、PR 編號、head、base——**不含 token**。

## 5. `DV-01` — PRD §8.15 與 traceability

### 5.1 PRD §8.15「交付、驗證與完成判準」

接在 §8.14 之後，同受 `CLIORA_AGENT_RUNS_ENABLED` 控制。十一條 FR：

| ID | 標題 | Owner |
|---|---|---|
| FR-DELIVERY-001 | 五種交付模式 | daemon ＋ central |
| FR-DELIVERY-002 | 交付的誠實性（三條規則） | daemon ＋ central |
| FR-DELIVERY-003 | PR／MR 建立與失敗處置 | central |
| FR-DELIVERY-004 | 無自動合併 | daemon ＋ central |
| FR-PLAN-001 | 執行計畫（append-only） | central |
| FR-VERIFY-001 | 驗證報告 | central |
| FR-VERIFY-002 | 證據可信度分級（**三級 `source` ＋ 兩值 `origin`**） | central |
| FR-VERIFY-003 | Done Gate ＋ `--force` | central |
| FR-EVIDENCE-001 | 機器事實證據（**兩個來源，`origin` 分辨**） | daemon |
| FR-EVIDENCE-002 | Evidence 彙整與矛盾不仲裁 | central |
| FR-AGENTTOOL-002 | 流程可設定性 | central |

**AC 的寫法沿用 §8.14**：每一條 FR 底下是可以逐項打勾的句子，
而不是「系統應該…」。目標約 55–60 個 AC。

### 5.2 traceability

`traceability/requirements.json` 新增 11 筆，`lifecycle: proposed`。
`scripts/trace validate --level static` 與 `render --check` 要綠。
**翻成 `active` 是人的動作**，與合併提案同時做（`plan/20/08` §4 第 4 條的先例）。

⚠️ **FR-VERIFY-004（平台不可用時的行為）已經在 V2.1 交付**（`research/02/11` §37 那一列），
本期**不要重新登記一遍**——重複的 ID 是 `render --check` 抓得到的，
但抓到的時候人已經寫了兩份 AC。

### 5.3 skill 的一句話

`ai/skills`（或等價位置）裡描述交付方式的那一句，V2.3 改成了「平台會推分支」。
本期改成五種模式的一句話，**並明說「平台永不合併」**——
Agent 讀到的文字是它對系統的第一手認識，而「平台會不會幫我合併」是它會猜的問題。

## 6. **回溯條目：V2.3 留下的一個相容洞**

這一節不是本期的新功能，是本期**順手修好的一件既存的事**，
而它值得寫下來因為它示範了一種很難發現的錯誤。

### 6.1 事實

- `daemon/internal/protocol/codec.go:437` 的 `strictUnmarshal` 用 `DisallowUnknownFields`。
- `encoding/json` 的這個設定**遞迴適用到巢狀結構**，所以它也管 `spec`。
- `run.offer` 走 `ValidateControl`（`run_handlers.go:168`），
  而驗證失敗時 `handleRunOffer` **直接 `return`**——不送 `run.decline`、不送任何東西。
- `spec.branch` 是 contract **v1.12.0** 新增的欄位。

### 6.2 後果

一台停在 `agentd 0.8.0` 的 node，連上 V2.3 的 Central 之後：
它會被 offer `delivery: branch` 的卡（`accept_secrets` 未帶視為 `true`、
`run_untagged` 未帶視為 `true`，兩條 V2.3 的相容處置都成立），
然後**在收到 offer 的瞬間靜默丟棄它**。

症狀鏈：卡片被領走（Central 端 `claimed`）→ 沒有 `run.accept` →
租約到期 → `requeue_lost` → 同一台再領一次 → 三次之後 `blocked`。
**沒有任何一則錯誤訊息提到相容性**，而 Agents 頁上那台 node 顯示為正常連線。

### 6.3 為什麼 V2.3 沒有發現

因為 V2.3 的相容性測試問的是「**register payload 沒帶那兩個布林時會怎樣**」
（出口條件 3f），而那是 **node→central** 的方向。
`spec` 的新欄位是 **central→node** 的方向，**而那個方向沒有被問過**。

> 這一條的教訓比這個 bug 大：**相容性有兩個方向，而兩個方向的預設處置相反。**
> node→central 可以寬鬆（Central 讀不到的欄位就當它沒有）；
> central→node **不可以**，因為接收端是一個會整包拒絕的嚴格解碼器。

### 6.4 本期的處置

1. **D3 的 `features` 是通用解**：從此以後，任何要進 `spec` 的新內容，
   Central 都只送給宣告了對應 feature 的 node。
2. **本期不往 `spec` 加任何欄位**（D6），所以 `features` 在本期只保護驗證命令
   （那個欄位舊 daemon 會忽略而不是拒絕，所以其實不需要保護——
   **但宣告仍要做，因為它是下一期的基礎設施**）。
3. **`spec.branch` 的既存洞**：加一條 Central 端的處置——
   node 未宣告 `branch` feature 且 `agentd` 版本低於 0.9.0 時，
   **不 offer `delivery != none` 的卡片**，並在 Agents 頁上說明原因
   （「這台 node 的 agentd 太舊，無法接受需要交付的卡片」）。
   ⚠️ 這是本期**唯一一處依賴版本號的邏輯**，而它是回溯修補所以無法避免：
   0.8.0 不會宣告 `features`，我們也改不了已經部署的 0.8.0。
   **新的 node 一律走宣告，不走版本號**（ADR 0029 增補 C3）。
4. `08-…md` 的出口條件 12 驗這件事：**用一個真的 0.8.0 binary**（`git` 上取得舊版本編譯）
   連上來，斷言它拿不到 `delivery: branch` 的卡，而且 Agents 頁說得出為什麼。

## 7. 過期承諾清單

沿用 `plan/20/01` §5b 的做法：**掃一次 repo，把「V2.4 會做 X」的程式註解逐處改對。**

已知的（開工時要重掃一次，因為 V2.3 期間可能又寫了新的）：

| 位置 | 現在寫著 | 改成 |
|---|---|---|
| `backend/app/services/runs.py:94-99` | 「The two that remain need a provider API rather than git transport, which is V2.4」 | 本期實現；改寫成 D18 的「這張表現在是空的，以及為什麼留著」 |
| `backend/app/services/process.py:15-17` | 「V2.4 adds a minimal per-project override」 | 改成指向 `projects.process_overrides` 與 D13 |
| `contracts/v1/schemas/messages/run-spec.schema.json`（`allowed_verification_commands` 的 `$comment`） | 「Empty in V2.2 and present so that V2.4's verification step does not need a contract change to be *refused* today」 | 改寫成 D6 的實際語意（tab 分隔、來自 Project 設定） |
| `backend/app/services/tasks.py:66-67` | 「Declared in V2.1, inert until V2.3/V2.4」 | 本期之後 `target_branch`／`existing_pr_ref` 不再 inert |
| `backend/app/services/secrets.py:314` | 「a kind this phase never delivers (`provider_token`)」 | 補一句：本期在 **Central** 使用它，仍然不下放 |
| `daemon/internal/runner/supervisor.go:294-306` | `ShouldAttachDiff` 的註解 | 與 `SummaryText` 共用述詞之後重寫 |

**`GATE-DV-NO-STALE-PROMISE`**：掃 `backend/`、`daemon/`、`contracts/`、`frontend/src/`
不得出現 `V2.4`／`V2.5 會`／`takes effect in a later version` 這類指向本期或更後的承諾，
**除非它出現在一份明確標為「未來」的文件裡**。
（`plan/20` 的同名 gate 抓的是 `project_agents`；本期換一組字串，機制相同。）

> 一句過期的承諾比沒有說明更糟——尤其它們出現在 RBAC 與安全審查會讀的地方。
> `plan/20/08` §3 第 4 條記過一次：`labels` 那個死欄位在兩層之外還有第三層，
> 而第三層是**一個把它變成可寫的 API**。過期註解的危險就是這個形狀。
