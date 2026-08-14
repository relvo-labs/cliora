# 08 — 驗證與出口（`DV-11`）

測試矩陣、十一個 gate、**30 條**出口條件、三節安全審查、旗標關閉回歸、合併關卡。

## 1. 測試矩陣

| 層 | 測什麼 | 大約條數 |
|---|---|---|
| contract fixtures | v1.13.0 的三處新增 ＋ **`spec` 不得新增欄位**的 invalid 案例 | 12（8 valid ＋ 4 invalid） |
| daemon 單元 | 共用述詞、驗證命令的四個細節、evidence 逾時、`features` | 18 |
| daemon 整合 | 五種 delivery 的節點半邊、驗證命令對真的 exit code | 6 |
| Central 單元 | `_WIRE_DELIVERY`、`run_branch()` 三值、dispatch 的三個新拒絕 | 14 |
| Central DB | 三張表、Done Gate 六項、`--force`、流程覆寫、指標、**兩個驗證命令來源的授權** | 46 |
| provider | 四種失敗、egress 的六條斷言（對 `cmd/fakeprovider`） | 12 |
| 前端 | §7 的十條 | 22 |
| 端到端 | 五種 delivery 各一次（`none`／`artifact`／`branch` 對本地；`pull_request`／`existing_pr` 對 fake ＋ Traqora） | 5 |

## 2. `cmd/fakeprovider`

四種模式（`ok`／`forbidden`／`unprocessable`／`hang`）＋ **一個請求計數器**。
計數器是出口條件 6／7 的驗收方式：**「沒有開 PR」要用「provider 沒被呼叫」來驗，
不是用「PR 不存在」來驗**——後者在一個沒有網路的 CI 上永遠成立。

## 3. 十一個 gate（`scripts/dv/gates.sh`）

四個是前期的 gate 重新指向本期基線，七個是新的。

| Gate | 守什麼 | 違反時的症狀為什麼是靜默的 |
|---|---|---|
| `GATE-DV-SCHEMA-ADDITIVE` | 基線的每一行 schema 都還在 | 沿用 `plan/20/08` §6 第 9 條的集合比對版本 |
| `GATE-DV-MIGRATION-ROUNDTRIP` | 降到 `0034` 與基線逐位元組相同 | 降級目標是參數（`plan/20/08` §6 第 10 條已改好） |
| `GATE-DV-CONTRACT-ADDITIVE` | 既有 fixture 一個位元組未變 | — |
| `GATE-DV-TOUCH-LIST` | 禁區未被動（D19，含 `push.go` 的**五條約束區塊**） | 動了約束的程式碼會過所有測試 |
| 🆕 `GATE-DV-DELIVERY-COVERAGE` | 五個 delivery 值在**四處**都有分支：`_WIRE_DELIVERY`、`run_branch()`、Done Gate、Run 詳情的前端 | 少一個值＝少一種行為，而少的通常是最新加的（D18） |
| 🆕 `GATE-DV-PROVIDER-VERBS` | provider adapter 不含 `merge`／`approve`／`review`／`close`／`delete`／`release`／`tag` | 紅線 5 的機器形式。一個多出來的方法不會有任何測試紅 |
| 🆕 `GATE-DV-NO-HTTP-IN-LOOP` | `services/runs.py` 不 import `httpx`、不呼叫 adapter | 一個 20 秒的呼叫在接收迴圈裡，症狀是**終端卡住**——沒有人會把它連到 PR 上 |
| 🆕 `GATE-DV-SINGLE-DONE-PATH` | `services/runs.py` 沒有 `task.stage = ` | 從側門繞過 Done Gate，而側門上沒有檢查 |
| 🆕 `GATE-DV-MACHINE-VERIFIED-ONE-WRITER` | `machine_verified` 只有一處寫入 | 第二個寫入點會讓 Agent 自述變成機器事實 |
| 🆕 `GATE-DV-NO-SHELL` | `daemon/` 不出現 `"sh","-c"`／`"bash","-c"` | 一條注入路徑，而它在平台自己的儲存面上 |
| 🆕 `GATE-DV-APPEND-ONLY` | 三張新表沒有 `update()` 呼叫 | 就地改寫一份「憑什麼算做完」的依據 |
| 🆕 `GATE-DV-NO-STALE-PROMISE` | 沒有指向本期或更後的過期承諾（`01-…md` §7） | 一句過期的承諾出現在安全審查會讀的地方 |
| 🆕 `GATE-DV-METRICS-READ-ONLY` | `runs.py`／`tasks.py` 不 import 指標函式 | 指標進了阻擋邏輯（D14） |

> 十一個是計畫值；上表列了十三列，因為前四個是繼承的。
> **繼承的四個一樣不可略過**——「只有新增」與「禁區還在」是同一個問題問不同的起點。

## 4. 三節安全審查（`docs/security-review-v24.md`）

**不可略過，且不可合寫成一段。** 本期命中三條觸發（`research/02/10` §6）：
新增對外副作用、新增憑證流的**使用**、新增在 node 上執行程序的能力。

| 節 | 觸發 | 對應計畫 |
|---|---|---|
| §1 | **對外副作用 ＋ provider 憑證首次使用** | `04-…md` §4 的七條 ＋ 四種失敗 |
| §2 | **新的執行能力**（驗證命令） | `05-…md` §5 的五個問題 |
| §3 | **完成判準的旁路與證據完整性** | `06-…md` §5 的四個問題 |

**§1 要額外回答一個 V2.3 沒問過的問題**：
平台現在以一個帳號的身分在別人的 repo 上留下痕跡，
而那個身分**不是按下派工鍵的人**。追溯路徑是什麼？
答案：PR 內文的最後一行 ＋ `audit_actions.PR_CREATE` ＋ Run 詳情的連結（`01-…md` §3.6）。

## 5. 30 條出口條件

**交付（1–7）**

1. **五種 `delivery` 各跑通一次。**
2. `none`／`artifact` 跑完之後**遠端沒有新分支、沒有新 PR**（用遠端狀態驗，不用 log 驗）。
3. **對 Traqora 開出第一個真實 PR**（`pull_request`，target `main`）。⬜ 人工
4. `none`／`artifact` 但有變更 → 摘要明示「偵測到 N 個檔案變更」**且 diff 已附為產物**。
   **兩種 delivery 都要**（`supervisor.go:316` 的既存落差）。
5. `artifact` 但一件產物都沒有 → **run 不算成功**，結果說明缺什麼。
6. `pull_request` 但無變更 → run 成功、結論「無變更」、**provider API 呼叫次數為 0**。
7. `existing_pr` 的 base 不在 `cliora/` 內 → **dispatch 當下拒絕**，訊息說得出為什麼（D7）。

**PR 建立（8–12）**

8. PR 建立的四種失敗各一次 → `delivered_branch_only`／`delivered`、原因可讀、**run 不算失敗**。
9. provider 逾時 → **只送出一個請求**（不重試，D16）。
10. provider token 不出現在任何 log 記錄裡（跑一次真的失敗請求，掃 caplog 每一筆）。
11. `pending_pr` 超過 50 筆 → 停止取件並在 Dashboard 上可見。
12. **`finish()` 裡沒有任何 HTTP 呼叫**（gate）。

**不做的事（13–14）**

13. **自動合併的程式碼路徑不存在**：daemon 的 git 子命令表 ＋ Central 的 provider 動作表，兩個 gate。
14. 對任意 node 執行任意命令的 API 不存在：Central 從不從 request payload 讀驗證命令（一條測試）。

**驗證與證據（15–19）**

15. 故意讓一條驗證命令失敗 → 報告 `failed`、`exit_code` 是真的那一個。
15b. **兩個來源各跑一條**：兩列都是 `machine_verified`，`origin` 分別是 `project` 與 `card`，
   且 project 的**排在前面**（D4／D6）。
16. 驗證命令逾時 → `exit_code: -1`，**其他條照跑**。
17. 剩餘 wall clock 不足 → 跳過驗證並**說明**，不是靜默跳過。
18. 機密出現在驗證命令的輸出 → `output_tail` 是 `***`。
19. Agent 在 payload 帶 `source: machine_verified` → **存為 `agent_reported` ＋ 記一筆 activity**。
19b. 畫面上 Agent 自述那一列帶「未經平台驗證」**文字**（不是 tooltip），
   且 exit code 不用機器事實的樣式（**畫面斷言**）。
19c. **run 憑證改 `tasks.verification_commands` → 403**（缺 `task.approve`）；
   人改同一個欄位可以；畫面上 Agent 看得到那份清單但**是唯讀**（**畫面斷言**）。

**Done Gate（20–23）**

20. 缺驗證報告的卡拖到 `done` → **被拒並逐項指名**；補齊之後通過。
21. `none`／`artifact` 的卡**進得了 `done`**；`artifact` 缺產物時**被擋**。
21b. `no_changes` 的 `pull_request` 卡與 `delivered_branch_only` 的卡**都進得了 `done`**。
22. Admin `--force` 帶理由通過，理由**永久可見**且進時間軸；非 Admin → 403；CLI 沒有這個子命令。
23. run 完成**不移動卡片**（gate ＋ 一條端到端）。

**流程與指標（24–25）**

24. Project 覆寫關掉兩項 readiness 與一個 gate → 該專案照覆寫運作，
    **而跨專案指標仍算得出來**；覆寫**碰不到 Done Gate**。
24b. `require_project_verification` 開啟後，只跑了 `origin: card` 的卡**進不了 done**
    並說得出為什麼；關閉時（**預設**）不影響。
25. **六個**指標各出一個數字；其中一個查詢失敗時**只有那一格降級**。

**相容與回歸（26）**

26. **旗標關閉：完整 V1＋V2.0…V2.3 回歸全綠**，OpenAPI 只新增路徑且新增路徑全部 404。
26b. **`agentd` 0.10.0 的 node 連上 V2.4 的 Central**，仍能正常領取與完成
   `none`／`artifact`／`branch`（只是不跑驗證命令）。
26c. **`agentd` 0.8.0 的 node** 拿不到 `delivery != none` 的卡，
   **且 Agents 頁說得出為什麼**（`01-…md` §6.4 的回溯修補）。

## 6. 旗標關閉回歸套組

沿用 `research/02/10` §3：

| 檢查 | 方法 |
|---|---|
| API 表面未變 | OpenAPI 與基線 diff：只允許新增路徑，且新增路徑全部 404 |
| 兩個旗標各自獨立 | `PROJECTS_ENABLED=true` ＋ `AGENT_RUNS_ENABLED=false`：看板可用、三張新表的端點 404、Done Gate 的交付證據那一項**不生效**（沒有 run 就沒有交付） |
| Protocol 未變 | 既有 fixtures 全數通過 |
| 終端延遲 | 三次連續量測取 p50 的中位數，與基線比 |

⚠️ **中間那一列有一個容易漏的分支**：`CLIORA_PROJECTS_ENABLED=true` 但
`AGENT_RUNS_ENABLED=false` 時，卡片仍然有 `delivery` 欄位（V2.1 就有），
但**沒有任何 run**。Done Gate 的第 6 項在這個組態下要**跳過**而不是擋住——
否則開了看板沒開 runner 的部署，每一張卡都進不了 `done`。

## 7. 合併關卡

**一律由人工確認。** 出口條件全綠只是取得提案資格，不是核准；
自動化（含 CI 與 agent）不得發起或完成 `v2` → `dev` 的合併
（`research/02/10` §7）。

合併提案要附：

1. 30 條出口條件的狀態表（可貼上的輸出）。
2. `scripts/dv/gates.sh` 的 13/13。
3. `docs/security-review-v24.md` 三節。
4. **Traqora 上那個真實 PR 的連結**，以及它被人處置的結果。
5. 尚未完成的量測清單（`10-…md`）。

## 8. Release note

`docs/release-note-delivery-and-verification.md`，四段：

1. **可以做什麼了**：五種交付、驗證報告（**兩個來源**）、Done Gate、流程覆寫、六個指標。
2. **行為改變**：
   - `delivery: pull_request`／`existing_pr` 的卡**不再被 dispatch 拒絕**。
   - 拖到 `done` 現在會被檢查——**這是本期對既有使用者最有感的一條**，
     要寫清楚六項是什麼、`--force` 在哪裡。
   - AC 的 `result` 收緊成四值，**不認得的舊值已被寫成 `not_verified`**（D9）。
   - 🆕 驗證命令有兩個來源：Project Settings（`project.manage`）與卡片
     （**需要「核准」權限，Agent 沒有**）。報告上以 `origin` 分辨（D4）。
3. **已知的取捨**：
   - `existing_pr` 只對平台自己開的 PR 成立（D7）——**這一條要寫得很清楚**，
     因為它看起來像 bug。
   - GitLab 未支援，dispatch 當下拒絕。
   - PR 的作者是憑證擁有者，不是派工的人。
   - 平台永不合併、永不 approve、永不關閉別人的 PR。
4. **升級注意**：`agentd` 0.11.0 的發布時機（出口全綠不代表要推給所有 node）；
   0.8.0 的 node 要升級才能領交付型卡片。
