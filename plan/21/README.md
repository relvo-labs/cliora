# Cliora V2.4 — 交付、驗證與證據

> **狀態：計畫已完成（A 類待確認項目已於 2026-08-14 全數裁決），尚未開工。**
> 前置條件是 V2.3（[`plan/20/`](../20/README.md)）的出口條件：**24 條裡 22 條已綠**，
> 而 **2026-08-14 使用者以 staging 手動部署確認過 V2.3**
> （`https://cliora-staging.up.railway.app`，記在 `plan/20/08` §4）。
> 尚未關閉的仍是 M-SC-2 的量測與那兩條需要別人 repository 憑證的條件（`plan/20/08` §7）。
> 本目錄不改變那條規則：**合併一律由人決定**，出口條件全綠只是取得提案資格。

本目錄是 [`research/02/`](../../research/02/README.md) 規劃的**第六個階段**的執行計畫，
ticket 統一使用 `DV-` 前綴（**D**elivery and **V**erification）。

規劃層（[`research/02/06-phase-v24-delivery-and-verification.md`](../../research/02/06-phase-v24-delivery-and-verification.md)）
回答「V2.4 要做什麼、為什麼」；本目錄回答「在**這個 repo 的現況**上怎麼做得出來、做完怎麼證明」。

## 這一期真正的形狀

> V2.3 的 run 是「在隔離目錄裡帶著機密執行，把 `cliora/` 分支推回去」。
> 這一期回答**兩個平台目前答不出來的問題**：
> ① 這張卡的成果**該以哪一種形式離開**（五種 delivery，而不只是「有沒有推分支」）；
> ② **這件事憑什麼算做完**（驗證報告、證據、Done Gate，而不是 Agent 說完成就完成）。

三個風險等級完全不同的半邊：

```text
                 交付半                   驗證半                  判準半
                 (DV-04,05)              (DV-04,06)              (DV-07,08,09)
 daemon          0.11.0：五種 delivery    0.11.0：在 run 內執行    不參與
                 的節點半邊               驗證命令、擷取 evidence
 contract        v1.13.0：**只在           不動 `spec`             不動
                 node→central 方向新增**   （沿用既有的欄位，D6）
 Central         **第一次主動連到          三張新表、三級 source    Done Gate、`--force`、
                 github.com**（開 PR）     由伺服器端判定           流程覆寫、跨專案指標
 新增的           **新的對外副作用**       **新的執行能力**         零新副作用
                 ＋ provider 憑證首次使用  （但邊界比看起來窄）      （純判準）
 觸發安審         **是**（對外副作用、憑證） **是**（新執行能力）     **是**（旁路與證據完整性）
 壞了會怎樣        **在別人的 repo 上開了    Agent 自述被當成機器事實  卡片憑一句「完成」進 done
                 一個不該開的 PR**
```

本期命中 `research/02/10` §6 的**三個**觸發條件，
所以 `docs/security-review-v24.md` 是**三節**且不可略過（`08-…md` §6）。

## 本期一個很值得先知道的性質

**contract v1.13.0 幾乎只動 node→central 的方向。** 這不是巧合，是兩條決策換來的：

- **PR 由 Central 開，不由 daemon 開**（D1）——所以 `delivery: pull_request` 在**線上表現為 `branch`**（D2），
  wire 的 `delivery` 集合一個值都不必加。
- **驗證命令沿用 `spec.allowed_verification_commands`**（D6）——那個欄位 V2.2 就放進 schema 與 Go struct 了，
  而且它的 `$comment` 白紙黑字寫著「present so that V2.4's verification step does not need a contract change」。

為什麼這件事值得寫在最前面：`daemon/internal/protocol/codec.go:437` 的 `strictUnmarshal` 是
`DisallowUnknownFields`，而且**遞迴適用到 `spec`**。任何加進 `spec` 的新欄位，都會讓
**尚未升級的 node 靜默丟掉整個 `run.offer`**——沒有錯誤、沒有回應、租約到期、重排三次、`blocked`。
上面兩條決策把本期會踩到這件事的路徑從兩條降到零（易錯 1／2）。

## 裁決紀錄

本目錄的形狀被以下裁決決定。**這張表是唯一的索引**，各處 inline 註記都指回這裡。

| 日期 | 裁決 | 對本期的意義 |
|---|---|---|
| 2026-08-08 | **D21：`source` 與 `delivery` 是兩個獨立欄位**——要不要程式碼、成果怎麼離開，是兩個問題 | `DV-01`（ADR 0033）的核心。`delivery` 五值本期全部跑通 |
| 2026-08-08 | **D10 例外 2：措辭定案**——否決的是「讓呼叫端指名命令的 API」，允許的是「daemon 在 run 目錄內執行驗證命令」 | `DV-04` 的驗證半邊成立的依據。**但那句話裡「命令從哪裡來」有兩種寫法，本計畫必須選一種**（D4、易錯 8） |
| 2026-08-08 | **D25：限制出口而非限制沙箱內行為** | 紅線 5 的落地方式：出口只有五種，沒有第六種；`merge` 不是其中之一 |
| 2026-08-08 | **D29：Agent 可交付產物到卡片**；能力與 `delivery: artifact` 宣告分開 | `artifact` 不是「附件功能」，是「這張卡的完成證據就是產物」（`03-…md` §1） |
| 2026-08-10 ② | **不擋 Agent push，憑證不必唯讀** | 五條硬約束的主詞是**平台的 push 路徑**。本期新增的 PR 路徑同樣只約束平台自己 |
| 2026-08-12 | **不做 `project_agents`**；授權邊界永久是 enrollment | 本期不新增任何授權表。`process.manage`／`task.force_done` 兩個新動作都是 Admin 專屬 |
| 2026-08-13 | **git 憑證的下放預設不開放** | 本期的 PR 憑證（`provider_token`）**走完全不同的路**：它**從不下放到 node**，只在 Central 用（D1）。與 `CLIORA_GIT_SECRET_DELIVERY_ENABLED` 無關 |
| **2026-08-14** | **驗證命令：兩個來源都要**（D4）——Project 設定 ＋ 卡片宣告，而**卡片宣告要 `task.approve`** | 上游那兩句矛盾的話變成一個欄位的兩個值。新增 `origin` 這個第二軸、`tasks.verification_commands`、`require_project_verification`（預設關閉） |
| **2026-08-14** | **`existing_pr` 只對平台自己開的 PR 成立**（D7，選項 A） | 五條硬約束一個字不改；不在 `cliora/` 內的 base 在 **dispatch 當下**被拒 |
| **2026-08-14** | **provider 先做 GitHub 一家**（D15） | GitLab 留 adapter 介面不實作；未支援的 host 在 dispatch 當下拒絕 |

### 2026-08-14 D4 的四個後果

上游那兩句互相矛盾的話（`research/02/01` D10 例外 2 的「**卡片宣告的**驗證命令」與
`research/02/06` DV-04 的「來自 **Project 設定**，不是卡片」）**不再需要二選一**——
它們描述的是兩個來源，而本計畫把它們做成同一個欄位的兩個值。

1. **`origin` 是第二軸，不是第三級。** `source` 回答「誰**觀察**到這件事」，
   `origin` 回答「誰**指定**要跑這件事」——兩者正交，
   而把它們壓成一個 enum 是原本設計的一次簡化。
2. **卡片宣告需要 `task.approve`，不是 `task.update`。**
   `RUN_TOKEN_SCOPES = {PROJECT_VIEW, TASK_UPDATE}`（`agent_auth.py:70`），
   而該模組第 51 行的註解白紙黑字寫著 `task.approve` 是 run 憑證
   「**永遠不能持有的那一半**」。所以人可以在卡片上宣告、**Agent 不行**——
   而這不是一行 if，是既有的 token scope 邊界。
   ⚠️ **這是本條裁決唯一容易做錯的地方**：把 `verification_commands` 放進
   `EDITABLE_FIELDS` 走 `PATCH`，Agent 就能自己改要跑什麼驗證。
   所以它有**自己的端點**（`02-…md` §2.1）。
3. **`machine_verified` 因此保住了。** 這一級的價值是「**執行者沒有選擇要跑什麼**」，
   而兩個來源都滿足它。反過來也成立：哪一天有人把卡片宣告降到 `task.update`，
   `origin: card` 的那幾列就要降級成 `agent_reported`。
4. **新增的取捨要被明確接受**：兩張卡可以用不同的標準宣稱自己完成。
   三個收斂點——`origin` 在四處可見（報告、evidence、Run 詳情、PR 內文）、
   專案級開關 `require_project_verification`（**預設關閉**）、
   以及一個看 `origin: card` 佔比的指標。

### 2026-08-14 D7 的一個後果

`existing_pr` 縮到平台自己開的 PR，所以「修 review 意見的迴圈」
只在平台開的 PR 上成立。**這一條看起來像 bug**，
所以它有三處文案：dispatch 的拒絕訊息、卡片編輯的當場提示、release note 的已知取捨。

## 這一期最容易做錯的十五件事

每一條都是從**這個 repo 的既有程式碼**讀出來的，不是從規劃推想的。

1. 🔴 **以為可以直接把 `delivery: pull_request` 送給既有的 node。**
   `codec.go:961` 的 `runDeliverySet` 只有 `{none, artifact, branch}`。
   agentd 0.10.0 收到 `pull_request` → `ValidateControl` 回錯 →
   `handleRunOffer` 直接 `return`，**不送 `run.decline`、不送任何東西**。
   症狀：卡片被領走、offer 靜默消失、租約到期、重排、三次後 `blocked`——
   與 `plan/20` D2 描述的完全同一種。正解是 **D2：PR 由 Central 在 push 之後開，
   wire 上仍送 `branch`**，`delivery` 集合一個值都不加。

2. 🔴 **以為往 `spec` 加欄位是相容的。**
   `codec.go:437` 的 `strictUnmarshal` 用 `DisallowUnknownFields`，而 `encoding/json`
   的這個設定**遞迴到巢狀結構**。所以任何新的 `spec.*` 欄位對舊 daemon 都是
   「整個 offer 靜默丟棄」。⚠️ **這不是本期才出現的洞**：`spec.branch` 是 v1.12.0 加的，
   一台還停在 0.8.0 的 node 今天就會丟掉每一張 `delivery: branch` 的 offer。
   本期要**同時修掉那個既存的洞**（D3 的能力宣告 ＋ `01-…md` §6 的回溯條目）。

3. 🔴 **照字面實作 `existing_pr`。**
   五條硬約束的第一條寫死在 `push.go:54`／`ValidBranch`，而 PR 的 head 分支通常是
   `feature/foo` 這種名字。照規劃寫「推到既有 PR 的分支」，結果是 run 做完工作、
   在最後一步被自己的 daemon 拒絕——而那時候工作已經花完了。
   正解是 **dispatch 當下就拒絕**（沿用 `TASK_BRANCH_NOT_DELIVERABLE` 的既有形狀，
   `runs.py:339` 已經有一個一模一樣的檢查在守 `existing_branch` ＋ `branch`）。

4. 🔴 **想在 daemon 裡判「`delivery: artifact` 但一件產物都沒有」。**
   產物是 Agent 用 `cliora task attach` 經 **HTTP** 上傳的（`daemon/internal/cli/command.go:204`），
   daemon 完全不知道這次 run 附了幾件。**出口條件 2b 的實作位置只能是 Central 的 `finish()`**
   （`runs.py:793`）：收到 `run.complete` 時數 `task_artifacts.run_id = run.id`，
   為 0 就把結果改寫成不成功。寫在 daemon 端會做不出來，而且會做出一個永遠通過的檢查。

5. 🔴 **`SummaryText` 今天對 `artifact` 少說一句話，而出口條件 2 要求它說。**
   `supervisor.go:316` 是 `if summary.Dirty && delivery == "none"`，
   而同一支檔案的 `ShouldAttachDiff`（:301）涵蓋 `none` **與 `artifact`** 兩者。
   所以現況是：一張 `artifact` 的卡有變更時 **diff 附上去了、摘要裡卻沒有那句話**。
   這是一個既存的小落差，本期修，而且它示範了一件事：
   **兩個函式對同一條規則各寫一次條件，遲早會有一個先被改。** `DV-04` 讓兩者共用一個述詞。

6. 🔴 **清空 `UNSUPPORTED_DELIVERIES` 之後留下一個永遠不成立的檢查。**
   `runs.py:94` 的那張表本期會清空（兩個值都開放了）。一個 `x in {}` 永遠是 False，
   程式仍然正確——但**一個永遠不成立的檢查是下一個人會順手刪掉的東西**，
   而它是「日後又有一種 delivery 還沒做」時唯一的掛勾點。要嘛連同 `raise` 一起拿掉、
   要嘛留著並在註解裡寫明它現在是空的以及為什麼留著。**本計畫選後者**（`00-…md` D18）。

7. 🔴 **`run_branch()` 只認得 `branch` 一個值。**
   `runs.py:1075`：`if task.delivery != "branch": return ""`。
   `pull_request` 與 `existing_pr` 也需要分支名，漏掉這一行的結果是
   **offer 不帶 `branch`、daemon 不建分支、agent 在 base branch 上工作、push 階段沒有東西可推**——
   而症狀是一句「沒有可推送的提交」，看起來像 Agent 什麼都沒做。

8. 🔴 **Done Gate 的「每一項 AC 都有結果」照字面實作等於沒有實作。**
   `tasks.py:603` 對 `acceptance_criteria` 只檢查「是一個 dict 的 list」與**渲染後的長度**，
   `result` 是**自由字串**——`render` 那一行的 `item.get('result') or '未驗'` 就是唯一的處置。
   所以 `result: "隨便"` 今天完全合法。Done Gate 要成立，得**先把四值封閉起來**，
   而那是一次**對既有資料的收緊**：`DV-02` 要先數一次現有 rows（`00-…md` D9）。

9. 🔴 **以為 daemon 已經有一個地方會執行 `allowed_verification_commands`。**
   欄位在（`run-spec.schema.json`、`codec.go:770`），驗證也在（`codec.go:938`，只檢查 `<= 16`），
   **但整個 `daemon/` 沒有任何一行會去執行它**。這與 V2.3 的 `Redactor` 是同一種形狀：
   規劃以為有掛勾點，實際上是新程式碼。
   ✅ **好消息是它反過來給了本期一個很有價值的性質**：舊 daemon 收到非空的清單只是
   **忽略**（長度檢查照樣過），不會丟掉 offer——所以驗證命令這條路徑**天生前向相容**（D6）。

10. 🔴 **Central 目前沒有任何主動對外的 HTTP 出口，而開 PR 是第一個。**
    `httpx` 已經是依賴（`backend/pyproject.toml:27`），但它今天只被 tunnel 那條路徑用。
    開 PR 是 Central **第一次主動連到 github.com**。這帶來三件安全審查會問的事：
    SSRF（`api_base` 若可設定就是一個 SSRF 面）、逾時與重試（一個卡住的 PR 呼叫會佔住什麼）、
    以及 **provider token 不得進 log**。三件都要有斷言，不是只有註解（`04-…md` §4）。

11. 🔴 **把 `delivered_branch_only` 加進 `run.complete` 的 `result` enum。**
    那個判斷發生在 **Central**（是 Central 在開 PR），daemon 永遠不知道 PR 開了沒有。
    所以它**不是 daemon 送上來的值**，而是 Central 收到 `run.complete` 之後寫進
    `task_runs.result`（`String(32)`，沒有 CHECK 約束）的值。
    **contract 的那個 enum 一個字都不必動**——而「想當然耳去動它」會讓 daemon 端多一條
    永遠走不到的分支，並讓下一個讀 schema 的人以為 daemon 會回報 PR 狀態。

12. 🔴 **以為 run 完成會自動把卡片推進 `done`，於是把 Done Gate 做成兩份。**
    現況 `finish()`（`runs.py:793`）**不碰 `task.stage`**——run 成功不會移動卡片。
    所以 Done Gate 只有**一條**入口：`TaskService.update()` 的 stage 變更（`tasks.py:421`），
    而 `cliora task update --stage done`（`command.go:98`）走的是同一支 service。
    這讓 `DV-07` 比規劃寫的小很多，**但要把「只有一條入口」寫成一條測試**，
    否則日後有人在 `finish()` 裡加一行自動推進，Done Gate 就從側門被繞過去了。

13. 🔴 **把 `--force` 做成 CLI 旗標。**
    規劃寫成 `--force` 的樣子，而 `cliora` CLI 是 **Agent 在用的**（`command.go:21` 的
    docstring 已經解釋過為什麼沒有 `approve` 子命令）。**Agent 絕不能有這個出口。**
    `--force` 是 Console 上的 **Admin 動作**：`PATCH` 帶 `force_reason`，
    需要一個**新的、Admin 專屬的**動作 `task.force_done`（D10）。

14. **evidence 的 daemon 半邊比規劃寫的小很多。**
    `supervisor.go:261` 的 `Inspect()` 已經在做 `status --porcelain`、`remote -v`、
    未推送 commit 數與 `diff`。缺的只有 `diff --stat`，而 commit sha 早就在
    `run.progress{phase: checked_out}` 送過了。**但它要先過 M6**——
    `research/02/10` §5 把「`git status --porcelain` 在最大的實際 repo 上要多久」
    標成**唯一一項 V2.4 開工前**要有答案的量測，因為它決定證據採集的逾時值。

15. **`process_definitions` 只有一列，而 per-project 覆寫可以是一張表也可以是一個欄。**
    `process.py:93` 的 `definition(key)` 從來只被呼叫成預設值，全域只有 `key='default'` 一列。
    DV-08 要的是「**只允許啟用／停用既有項目**」——那是一組布林，不是一份定義。
    **一個 JSONB 欄比一張表誠實**，而且它讓「跨專案指標仍可聚合」這件事在資料層就是真的
    （D13）。做成表會邀請下一個人往裡面塞自訂項目。

## 與 `research/02/06` 的差異

**除了第 3、4、7 條之外都是修正而非裁量**——它們是讀了程式碼之後發現規劃的假設與現況不符。
第 3、4、7 條需要人接受代價。

| # | `research/02/06` | 本計畫 | 依據 |
|---|---|---|---|
| 1 | migration `0028`／`0029` | **`0035`／`0036`／`0037`** | 現況已到 `0034_seed_secret_action` |
| 2 | ADR **0033** | 編號不變（`docs/adr/` 最後一支是 `0032`） | — |
| 3 ⚠️ | DV-02「PR 內容由平台產生」，未說由誰呼叫 provider API | **由 Central 呼叫，daemon 永不持有 `provider_token`** | `secrets.py:48` 的 `UNDELIVERABLE_KINDS` 已經把 `provider_token` 排除在下放之外；把它下放等於把一枚能改別人 repo 的憑證交給沙箱（D1） |
| 4 ⚠️ | `delivery` 五值都上 wire | **`pull_request` 在 wire 上表現為 `branch`** | `codec.go:961` 的 `runDeliverySet` 只有三值，舊 node 會**靜默丟掉 offer**（易錯 1、D2） |
| 5 | DV-04「驗證命令由 daemon 在 run 內執行」，未說走哪個欄位 | **沿用既有的 `spec.allowed_verification_commands`**，編碼成 `origin\tname\tcmd\targs…` | 該欄位的 `$comment` 就是為了這件事寫的；新增欄位會踩到 `DisallowUnknownFields`（易錯 2、9、D6）。`origin` 塞進同一個字串正是為了不碰 `spec` |
| 5b ✅ | DV-04「命令來自 Project 設定，不是卡片」（且與 `01` D10 矛盾） | **兩個來源都要**，`origin` 分辨；**卡片宣告要 `task.approve`** | **2026-08-14 裁決**。連帶 `tasks.verification_commands`、`require_project_verification`、出口條件 15b／19c／24b |
| 6 | 「`source` 三級由伺服器端決定」 | 同意，並補上**「payload 帶 `machine_verified` 時要記一筆 activity」的實作位置** | 出口條件 7 要驗的是「忽略了而且說出來」，只忽略驗不出來 |
| 7 ✅ | DV-01「`existing_pr`：push 到既有 PR 的分支」 | **只對平台自己開的 PR 成立**，其餘在 dispatch 當下拒絕 | `push.go:54` 的第一條硬約束（易錯 3、D7）。**2026-08-14 裁決：選項 A** |
| 8 | DV-05 Done Gate「接到 `PATCH` 與 **run 完成路徑**上」 | **只接在 `PATCH` 上**，並加一條「run 完成不得移動卡片」的斷言 | `finish()` 現況不碰 `task.stage`（易錯 12） |
| 9 | DV-05「`--force` 出口」 | **新的 RBAC 動作 `task.force_done`，Admin 專屬，且 CLI 沒有這個子命令** | `command.go:21` 的既有先例（易錯 13、D10） |
| 10 | DV-03「`steps[].status` 五值」「只 INSERT 不 UPDATE」 | 同意，並補上**唯一鍵 `(task_id, seq)` 的競態處置** | 兩個併發的 `plan snapshot` 會撞同一個 `seq`；規劃沒說要怎麼辦（`05-…md` §1.3） |
| 11 | DV-06 evidence「git 狀態由 daemon 固定 argv 擷取」 | 同意，但**大半已經存在**（`Inspect()`），本期只補 `diff --stat` 並過 M6 | `supervisor.go:261`（易錯 14） |
| 12 | DV-08「`process_definitions` 從全域種子變成 Project 可覆寫」 | **`projects` 上的一個 JSONB 欄，不新增表** | 「只允許啟用／停用」是一組布林（易錯 15、D13） |
| 13 | 出口條件 2「明示偵測到 N 個檔案變更」 | 同意，並記下**現況對 `artifact` 不成立** | `supervisor.go:316`（易錯 5） |
| 14 | 未提 AC 的 `result` 是自由字串 | **先封閉四值，再做 Done Gate**，並先數一次既有資料 | `tasks.py:603`（易錯 8） |
| 15 | 未提 Central 的對外 egress | **新增一節安全審查與三條斷言** | Central 第一次主動連外（易錯 10） |
| 16 | DV-07「跨專案 Dashboard，先做五個指標」 | 同意，但**掛在既有的 per-block 降級契約上**，不新寫一套 | `dashboard.py` 的每個 block 有自己的 `status` 與 `error_code`；另寫一套會產生第二種「這個數字可不可信」的答案 |

## 檔案

| 檔案 | 內容 |
|---|---|
| `00-execution-plan.md` | 成功定義（十四項判準）、範圍、固定基線決策 **D0–D21**、波次與 ticket、風險 |
| `01-decisions-and-governance.md` | `DV-00` 基線與 **M6**、**ADR 0033**、ADR 0029／0031／0032 的增補、PRD §8.15、traceability、**回溯條目（V2.3 的相容洞）** |
| `02-data-layer.md` | `DV-02`：migration `0035`／`0036`／`0037`、三張新表、AC 四值的收緊、兩個新 RBAC 動作 |
| `03-delivery-modes.md` | `DV-01`／`DV-04` 的交付半邊：五種 delivery 的完整語意、三條誠實性規則的實作位置、能力宣告 |
| `04-pr-creation.md` | `DV-05`：Central 的 provider adapter、PR 內文的產生、失敗處理、**新的 egress 與它的三條斷言**（**安審 §1**） |
| `05-verification-and-evidence.md` | `DV-04`／`DV-06`：驗證命令的來源與執行、三級 `source`、evidence 的九種 kind、矛盾不仲裁（**安審 §2**） |
| `06-done-gate-and-process.md` | `DV-07`／`DV-08`：Done Gate 的六項、`--force` 與它的永久可見性、流程覆寫（**安審 §3**） |
| `07-frontend-and-metrics.md` | `DV-09`／`DV-10`：Task Detail 的四個新區塊、Run 詳情的交付結果、Project Overview、跨專案指標 |
| `08-verification-and-exit.md` | `DV-11`：測試矩陣、**十一個 gate**、**26 條出口條件**、三節安全審查、旗標關閉回歸、合併關卡 |
| `09-implementation-status.md` | 實作進度與證據（隨實作更新） |
| `10-open-measurements.md` | **M6 開工前**、M-DV-1／M-DV-2、V2.3 遺留的 M-SC-2 與 V2.2 遺留的兩項 |

## 執行慣例

```bash
tmux new-session -d -s cliora-v24 -c /home/ubuntu/workspace/cliora
tmux send-keys -t cliora-v24 'make check' C-m
tmux attach -t cliora-v24        # 需要看的時候才 attach
```

**環境事實**（`09-…md` §5，沿用 `plan/20/08` §5）：工具鏈不在預設 PATH 上；
DB 測試要**兩個**環境變數；`claude` 與 `codex` 在 `~/.local/bin`；`git` 是 runner 模式的前置條件；
`ssh-agent`／`ssh-add` 與一個可寫的 scratch 遠端（V2.3 起）。
🆕 **本期多兩個**：一枚對 **Traqora 有 PR 建立權限**的 fine-grained PAT（出口條件 3），
以及一個**可以離線測 provider API 的 fake**（`cmd/fakeprovider`，出口條件 4 的四種失敗要跑得出來）。

## 驗收素材

**Traqora**（D30）。V2.3 是第一次需要它的寫入權限（push）；
**本期是第一次需要它的 PR 建立權限**，而那是整個 V2 的第一次真實交付。所以：

1. **先對 `cmd/fakeprovider` 走完出口條件 4 的四種 PR 建立失敗**（權限不足、target 不存在、
   同一 head 已有 PR、provider 逾時），確認四種都是 `delivered_branch_only` 而不是 run 失敗。
2. 再對 Traqora 開**第一個真實 PR**（`delivery: pull_request`，target `main`）。
   **PR 由人審閱後關閉或合併——平台永不自動合併。**
3. `existing_pr` 的驗收**接在第 2 步的 PR 上**（那是唯一一個在 `cliora/` 命名空間裡的 PR），
   這正好示範了 D7 的範圍限制是什麼意思。
4. `none`／`artifact` 各跑一次，並**斷言 Traqora 上沒有任何新分支與新 PR**——
   「不產生遠端變更」要用遠端的狀態證明，不是用 log 證明。

## 合併回 `dev`

**一律由人工確認。** 出口條件全綠只是取得提案資格，不是核准；
自動化（含 CI 與 agent）不得發起或完成這個合併
（`research/02/10-verification-and-exit.md` §7）。
