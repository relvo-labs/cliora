# V2.2 — Agent Runner 與任務認領（ticket 前綴 `AR-`）

> **2026-08-10 裁決（改寫本文件）**
>
> 1. **Agent 自己把專案拉到本地**，像 GitLab Runner 那樣。不再「在使用者綁定的 workspace 上執行」。
> 2. **拉下來的東西放在 daemon 擁有的隱藏目錄（`.cliora/runs/<run_id>/`）**，不在任何 allowed root 內。
> 3. **Workspace 綁定從此只服務互動式 Session**（既有的 CLI 與 Terminal 功能）。
>    V2.2 新增的 runner 功能**鎖定在看板任務處理**，不碰 workspace 綁定這一層。
> 4. **`project_agents` 綁定與 label 比對本期都不做**：現在**每個 agent 都可以拉每個 project**。
>    label match 是後續功能。
>
> 這次裁決把 D19（隔離工作目錄）與 D20 的**取得半邊**從 V2.3 提前到 V2.2，
> 並把 D18（綁定與 labels）從 V2.2 延後到 V2.3。§0 記錄搬動了什麼、為什麼。

## 0. 這次裁決搬動了什麼

| | 原本 | 現在 | 為什麼 |
|---|---|---|---|
| run 的工作目錄 | V2.2 用使用者綁定的 workspace，V2.3 才隔離 | **V2.2 就隔離**：`<state>/.cliora/runs/<run_id>/` | 「在使用者的 workspace 上無人值守執行」是原本 V2.2 最大的已知缺口。裁決直接把它移除，而不是讓它存在一個階段 |
| git 取得 | V2.3 | **V2.2**（clone／fetch／checkout） | Agent 要自己拉專案，這是裁決的字面要求 |
| **平台的** git 送回（push） | V2.3 | **仍是 V2.3** | 取得與送回是兩件事。**平台**在 V2.2 的成果出口只有卡片產物 |
| **Agent 自己**的 git 操作（含 push） | 未明說 | **允許**（2026-08-10 第二次裁決） | 沙箱內的自由是刻意給的（D25）。收斂點是紅線 5 的原則 ＋ 可觀測性，不是 daemon 的 argv 表（§AR-04b 第 3 點） |
| 機密（PAT／SSH key） | V2.3 | **仍是 V2.3** | V2.2 用 node 上**既有的** git 認證，平台不管理、不注入任何憑證（§AR-04b） |
| `project_agents` 綁定 | V2.2 | **V2.3**（與機密同一份 ADR） | 綁定在 V2.2 沒有授權任何東西；它要授權的是機密，所以與機密一起做才有讀者 |
| `labels` × `required_labels` 比對 | V2.2 | **後續**（欄位已在，不比對） | 裁決明文「後續可以加入 label match」 |
| ADR 0031（隔離目錄與 git） | V2.3 | **V2.2 發佈，V2.3 增補 push 半邊** | 文件跟著能力走 |

**紅線 2 的適用範圍因此變得更乾淨**：`workspace.Root` 管的是使用者的 allowed root，
而 Agent Run 從第一天就不在那裡面。兩者不得互通，**而這條在 V2.2 就可以被測試**。

## 目標

讓任務卡從「人在看板上推」變成「Agent 自己領走、把專案拉到自己的隔離目錄、執行、把成果附回卡片」。

本階段**刻意不碰機密、平台自己不 push、不碰 PR**——那些是 V2.3／V2.4。
（**Agent 自己用機器憑證 push 是允許的**，見 §AR-04b。）
這裡要證明六件事：工單掛得出去、被領得到、領走之後不會雙重領取、
**專案拉得下來而且拉在一個不會弄壞任何人東西的地方**、runner 死掉能重排、執行過程看得見。

## 前置條件

- V2.1 出口條件全數通過。
- D16、D17、D17b、D19、D24、D26、D27、D29 已裁決；**D18 延後至 V2.3**。
- ADR 0029（Agent Runner 模型與 run 生命週期）、ADR 0030（run 的輸出：log 與產物）、
  **ADR 0031（隔離工作目錄與 git 取得）** 已撰寫並接受。
- **M11（clone 與 worktree 耗時）與 M12（run 目錄大小）已量**——原本是 V2.3 開工前，
  現在是 V2.2 開工前（`10` §5）。

## 工作包

### AR-01 — ADR 0029：Runner 模型

要寫清楚的六件事：

1. **Runner 是 `agentd` 的一個模式**（D16），重用既有的 enrollment、Ed25519 憑證、WSS、heartbeat。
   **不新增信任建立流程**——這是本 ADR 最重要的一句。
2. **拉取式認領**（D17）與其理由：平台不寫排程器，背壓天然。
   **指定 agent 是 poll 查詢的一個 `WHERE` 條件，不是推送**（D17b）。
3. **本期的資格判定只有四條件**（D18 延後之後）：卡片在 `ready`、`dependsOn` 全滿足、
   runtime 相符、`assigned_runner_id` 為 null 或等於該 runner。
   **`project_agents` 與 labels 不在本期的判定裡**，而**enrollment 是 runner 在本期唯一的授權邊界**
   ——這句話要明寫，它是一個姿態宣告而不是遺漏。
4. **租約語意**：續租週期、逾時判定、重排上限、用完進 `blocked`。
5. **Agent Run 不是 Session**：不進 `terminal_sessions`、不走 Terminal relay、不佔 writer 名額、
   沒有 tmux 持久化。**也不使用 workspace 綁定**——那一層從此只服務互動式 Session。
   兩條路徑在程式碼上分開。
6. **Alternatives rejected**：平台推送式派工（會長成排程引擎，違反紅線 4）、
   把 run 建成一種 Session（生命週期不同）、新做一支 runner binary（重複整條信任鏈）、
   **在使用者綁定的 workspace 上執行**（本次裁決否決的那一個：無人值守 ＋ 使用者的未提交工作
   ＝ 一個不該存在一個階段的缺口）。

### AR-02 — ADR 0030：run 的兩種輸出（log 與產物）

一份 ADR 涵蓋兩者，因為它們是同一個問題的兩半：**run 產生的東西怎麼離開 node、存多久、誰清。**

**Part A — run log（D27）**：核心是那張「互動式 Session vs Agent Run」對照表，以及一句話：

> **這不構成「平台現在會存終端內容」的先例。** 互動式 Session 的承諾未變。

四條約束（有界、runner 端去識別、保留期、不是 Terminal relay）逐條寫進 Decision，各配一條測試。

**Part B — 卡片產物（D29）**：能力與宣告分開、存平台不存 node、三層配額、
**提供時預設下載不渲染**、不可變、不保證不含機密。

**兩者的保留期不同，這是本 ADR 最重要的一句**：log 是**診斷**（保留期到期即刪），
產物是**交付物**（跟著卡片走）。混為一談會讓卡片上出現死連結。

**第五條約束（2026-08-11 裁決接受）**：Central 端把 `run.log_chunk` 在記憶體聚合
（≤64 KiB／≤2 秒才寫一列），所以**Central 崩潰會掉每個進行中 run 最後未 flush 的一段**。
接受的理由是同一條核心區分：log 可重跑，而**產物走 HTTP 逐件落地、訊息走 API 逐筆 commit,
兩者刻意不走聚合這條路**。這個不對稱要寫進 ADR 0030 的 Consequences——
一個「資料會掉」的設計若只寫在程式碼旁邊，下一個人會以為 `run_logs` 是完整的。
替代方案（每 chunk 一次 DB 往返）會在 `node_gateway` 的單一迴圈裡阻塞互動式終端的輸出。

**本期新增的第三種輸出要一起寫進來**：`delivery: none|artifact` 的卡片若在工作目錄留下變更，
**`git diff` 要被附成一件產物**（D21 誠實性規則 ＋ D29 §7）。
原本那條規則是 V2.4 的，現在因為 run 真的會拉程式碼、真的會改檔案，**它在 V2.2 就必要了**：
run 目錄有保留期，那份工作若不附成產物就會消失。

### AR-02b — ADR 0031：隔離工作目錄與 git 取得（**本期新增，原屬 V2.3**）

**只寫取得半邊。** push、分支命名空間、五條 git 硬約束留給 V2.3 增補同一份 ADR。

**一台 node 上會有兩棵完全不相干的樹**，先看這個：

```text
/var/lib/agentd/                       ← Agent Run 的地盤（systemd StateDirectory=agentd，0700）
└── .cliora/
    ├── mirrors/<repo-hash>/           ← bare mirror，這台機器上所有 run 共用一份
    └── runs/<run_id>/                 ← run_id 是 UUID
        ├── repo/                      ← git worktree ★ 程序的 cwd
        ├── .cliora/context/<run_id>.{md,token}
        ├── .cliora/process/<version>/
        └── artifacts/

/home/<user>/projects/traqora/         ← 互動式 Session 的地盤（allowed_roots 裡的一條）
└── .cliora/{context/<session_id>.md, uploads/, .gitignore}
```

**Agent Run 只活在上面那棵**，而且它不知道下面那棵在哪——
`run.offer` 的 `spec` **沒有 `workspace` 欄位**，Central 連 run 目錄叫什麼都不知道。

具體執行的那一行是 `cd <run>/repo && claude -p <<< "<情境包>"`
——沒有 PTY、沒有 tmux。對照 Session 的 `tmux new-session -c <allowed_root> claude`。

**兩者可以同時跑**，而且是三種「同時」：一台 node 上 run ＋ Session 併行
（兩個互不相干的計數器：`sessions_per_node_max` 與 `max_concurrent`）；
一個 runner 多個 run；一個 run 裡的 Agent 一邊做事一邊用 `cliora` CLI 回報。
共用的只有三樣：一條 WSS、一顆磁碟、**一個 OS 使用者**——第三樣的後果見規則 1。
逐項的表在 `plan/18/04b-run-directory-and-git.md` §2。

**目錄六條規則**（D19）：

1. **不在任何 allowed root 內**，也不得被既有的檔案瀏覽 API 觸及。
   使用者要看 Agent 做了什麼，看的是 run log 與卡片產物。
   daemon 在 runner 模式啟動時，若 run root 落在任何 `workspace.allowed_roots` 之內，
   **拒絕啟動並指名**，不是印一行警告。

   ⚠️ **反向不成立，而這一點原文寫錯了。** D19 規則 1 的原文說
   「Agent Run 不能讀寫使用者的 allowed root，這一條要有測試」——
   **平台沒有實作那件事**：run 的子程序與 agentd 同一個 OS 使用者，
   而 allowed roots 必須被那個使用者讀寫（否則互動式 Session 開不起來，
   `daemon/internal/install/systemd.go:33` 的註解明寫家目錄刻意不隱藏）。
   沒有 chroot／mount namespace／seccomp。

   **改成兩件真的、可測的事**：
   ① **平台的任何路徑都不寫 allowed root**（`daemon/internal/{files,workspace}/` 零 diff
   ＋ run 全程 workspace 的 `git status --porcelain` 為空）；
   ② **這台 node 是不是專用的，由 daemon 回報並在 console 上顯示**——
   `runner.register` 的 `dedicated` 欄位（＝ `len(allowed_roots) == 0`）。
   `allowed_roots` 為空時「Agent 讀不到 allowed root」才是恆真的。
   **回報而不是強制**，沿用 `sandbox_bypass` 的 requested／actual 分離（ADR 0023 D3）。
   完整推導見 `plan/18/04b-run-directory-and-git.md` §3.4／§2.5。
2. **每次執行新建，結束後依保留期清理**（成功 3 天、失敗 14 天——失敗的要留久一點）。
3. **配額**：單一 run 目錄上限、node 上所有 run 的總量上限。超過就拒絕領新工作並回報給平台顯示。
4. **repo 快取**：同一個 repository 在同一個 node 上共用一份 bare mirror，
   run 目錄用 `git worktree` 掛出來。M11 決定 mirror 與淺 clone 的取捨。
5. **誰清這個**：daemon 的既有清理迴圈（`projectionRetentionLoop` 已有同型的東西可循）。
   這是 ADR 0024 W2 的答案之一，要寫進 ADR。
6. **`artifacts/` 不是可瀏覽目錄**：它的內容經由 `cliora task attach` 上傳到平台，
   卡片上看到的是平台的副本，不是 node 的目錄。

**git 取得的約束**（D20 的取得半邊）：

- **平台**只做 `clone`／`fetch`／`checkout`／`worktree add`。
  **daemon 的 git argv 封閉表裡沒有任何寫入遠端的動作**——這是可被 gate 斷言的形式。
  （Agent 自己在沙箱裡呼叫 `git` 不受這張表限制，那是刻意的，見 §AR-04b。）
- **remote allowlist**：只能拉該 Project 登記的 repository host。
- SSH 走 `StrictHostKeyChecking=yes` ＋ known_hosts pinning（沿用 `fix/update-healthcheck-known-hosts`
  與 `tunnel.known_hosts_path` 的既有做法）。
- **`origin` 保留**（2026-08-10 第二次裁決撤回了「clone 後移除 origin」——
  它會連帶弄壞 fetch／pull 與那個被允許的 push，見 §AR-04b）。

### AR-03 — Contract：runner 與 run 訊息（contract v1.11.0）

```text
runner.register    { runner_id, name, runtimes[], labels[], max_concurrent, max_waiting }
runner.registered  { accepted, reason? }
runner.poll        { runner_id, capacity }
run.offer          { run_id, task_id, project_id, spec }
run.accept         { run_id }
run.decline        { run_id, reason }
run.lease_renew    { run_id }
run.progress       { run_id, phase, message }
run.log_chunk      { run_id, seq, data, truncated }
run.complete       { run_id, result, summary }
run.failed         { run_id, error_code, message }
run.cancel         { run_id, reason }        ← 平台 → runner
```

`spec` 在本階段含：runtime、**source（`none`／`repo`／`existing_branch` ＋ repo URL ＋ ref）**、
情境包內容、允許的驗證指令清單、**兩個逾時**（`timeout_seconds` 牆鐘兜底、
`idle_timeout_seconds` 存活判定）。**不含機密**（V2.3 才有）。

> **2026-08-11 更正：兩個逾時而不是一個。** 一次性指令的牆鐘逾時
> **不代表它沒在執行**，很可能 Agent 還在處理——拿它當存活訊號就是拿誤判當機制。
> 兩支 CLI 都有為程式設計的事件流（`claude -p --output-format stream-json`、
> `codex exec --json`），所以存活判定改成**距上一個事件多久**，
> 牆鐘放大成兜底。推導與被否決的「用互動模式（PTY）」見
> `plan/18/04-contract-and-daemon-runner.md` §3.4。
**不含 workspace**——那個欄位隨著裁決一起消失了，run 的目錄由 daemon 自己決定。

> **原本規劃把 `source` 排在 v1.12.0**（`08` §4）。裁決把 clone 提前，
> 所以 `source` 提前到 v1.11.0，而 v1.12.0 只剩 `secrets`。

fixtures：每個訊息 valid ＋ invalid（缺 `run_id`、未知 phase、`log_chunk` 超過大小、
`capacity` 為負、非 UTC 時間、未知型別、**`spec` 帶 `secrets`／`command`／`args`／`env`**、
**repo URL 的 host 不在 allowlist**）。

### AR-04 — Daemon：runner 模式（`agentd` 0.9.0）

- `agentd serve --runner` 或設定檔開關；容量控管 `max_concurrent`，滿了就不 poll。
- **run 目錄的建立、clone／worktree、清理**（AR-02b 的六條規則）。
- **執行 CLI 的方式**：非互動模式，argv 仍由既有的 `runtime` 套件組出
  （**SEC-002 的 argv 部分完全不變**）。它不掛 PTY、不進 tmux。
  **情境從 stdin 進去，不進 argv。**
- 輸出處理：擷取 stdout（**JSONL 事件**）與 stderr → **逐行**分塊（不切斷一行 JSON）
  → 大小上限 → 送 `run.log_chunk`；每一行事件同時更新 `last_event_at`。
- **去識別的掛勾點先做好**（本階段沒有機密可去識別，但介面要在）。
- **三個計時器，各答一個問題**（2026-08-11）：
  `lease_expires_at` 答「**runner** 活著嗎」（Central 判，逾時 → `lost` → 重排）；
  **idle timer** 答「**child** 在前進嗎」（daemon 判，→ `RUN_IDLE_TIMEOUT`，**存活的主要判定**）；
  牆鐘 `timeout_seconds` 答「它會不會永遠不停」（→ `RUN_TIMEOUT`，**兜底**，建議 6 小時）。
  **`run.lease_renew` 刻意維持無條件**——它答的是另一個問題，
  改成「只在 child 有活動時續租」會讓兩種失敗長得一樣而它們的處置不同。
- 收到 `run.cancel` 要能真的停下來（送訊號、等待、強制終止三段，**對整個 process group**）。
- **`delivery: none|artifact` 但工作目錄有變更**時，把 `git diff` 附成產物（AR-02 的第三種輸出）。

### AR-04b — 本期用哪一份 git 認證，以及 Agent 的 git 自由

機密下放是 V2.3。所以 V2.2 的 clone 用的是**node 上既有的** git 認證
（ssh-agent、credential helper、或公開 repo），**平台不管理、不注入、不記錄任何憑證**。

> **2026-08-10 第二次裁決：不需要擋 Agent 自己 push，憑證也不需要唯讀。**
> 本節原本寫成「本期最大的新風險」＋四道處置。那個框架**被撤回**：
> Agent 在沙箱裡的 git 自由是**刻意給的**。撤回的具體內容：
> 不做 `git remote remove origin`、runbook 不再建議「runner node 只帶唯讀憑證」、
> 風險表不再有那一列、出口條件不再要求 `git remote -v` 為空。

五條必須寫進 ADR 0031 的後果：

1. **平台不新增任何機密面**，所以 V2.3 的 ADR 0032 範圍不變。

2. **私有 repo 只有在那台機器本來就拉得動時才拉得動，而且要快速失敗**：
   `GIT_TERMINAL_PROMPT=0` ＋ `GIT_ASKPASS=/bin/false` ＋ SSH `BatchMode=yes`。
   **這三個只套用在 daemon 自己的 clone／fetch 環境上，不進 Agent 程序的環境**
   ——套進去會讓一個需要密碼的 push 失敗，而那正是裁決要允許的。
   沒有它們，一次缺憑證的 clone 會掛在提示上直到**牆鐘兜底**（6 小時）。
   **idle timer 救不了這一種**：clone 在 `run.accept` 之前，還沒有事件流可以量。

3. **Agent 可以用機器的憑證做 git 能做的任何事，包含 push。這是刻意的。**
   它與 D25 一致：不限制沙箱內能做什麼，改為限制產出怎麼離開。
   紅線 5 的原則在分支這個出口上仍然成立——**沒有人 merge 的分支不影響任何人**。
   **連帶要改一件事**：紅線 4 第 1、2 條的主詞從「Agent」改為「平台的 push 路徑」
   （`00` §7 已於同日修訂）。

4. **可觀測性取代阻止，而且它是主要機制不是安慰獎。** run 結束時記錄兩件事：
   `git remote -v`（**userinfo 遮掉**）與 `git log --oneline --branches --not --remotes`
   的行數（＝有幾個 commit 還沒推）。兩行零成本的資訊，
   讓「這個 run 有沒有動到遠端」在 Run 詳情頁上是事實而不是猜測。M-AR-8 統計它。

5. **run 的 git 身分是機器的身分。** 平台本期不做 commit；Agent 若自己 commit／push，
   作者由 run 目錄的最小 `.git-config` 指定為 `cliora-run@<node>`
   ——**不冒充人類、也不假裝是平台**，而且讓 `git log` 上看得出哪些 commit 出自無人值守的 run。
   bot identity 與 commit trailer 的完整形式是 V2.3。

### AR-05 — Central：run 生命週期與佇列

migration（編號依實作當下的現況，見 `08` §2）：

- `agent_runners`：`id`、`node_id`（**唯一**）、`name`、`runtimes` JSONB、`labels` JSONB、
  `max_concurrent`、`max_waiting`、`enabled`、`registered_at`、`disabled_at`。
  **沒有 `status`／`last_seen_at`**——runner 的線上狀態就是 node 的線上狀態（D16）。
- `project_repositories`：`id`、`project_id`、`host`、`path`、`default_branch`、`created_by`。
  **本期只有身分欄位**；`auth_kind`、`credential_secret_id`、`provider_token_secret_id`
  是 V2.3 的增補。
- `task_runs`：`id`、`task_id`、`project_id`、`runner_id`（nullable）、`seq`、`status`、`attempt`、
  `assigned_runner_id`（**快照**，重排維持指定用）、`repository_id`、`source_ref`、`commit_sha`、
  `claimed_at`、`lease_expires_at`、`started_at`、`finished_at`、`result`、`error_code`、
  `summary`、`created_by`。
  **沒有 `workspace_node_id`／`workspace_path`**——run 不再使用 workspace。
- `run_logs`、`task_messages`、`task_artifacts`（＋ blob 分表）、`run_tokens`。
- **`project_agents` 不在本期**（D18 延後到 V2.3，與機密同一份 migration）。

**狀態機**：

```text
queued → claimed → running → succeeded
                          ↘ failed
                          ↘ waiting_for_input → running
   ↑                      ↘ cancelled
   └── lost（租約逾時）→ 重排（attempt+1，上限 3）→ blocked
```

**原子認領**：`UPDATE task_runs SET runner_id=?, claimed_at=now(), lease_expires_at=? WHERE id=? AND runner_id IS NULL`。
回傳 0 列就是被別人領走了。

**資格判定（本期四條件）**：

```sql
WHERE t.stage = 'ready'
  AND NOT EXISTS (未完成的 dependsOn)
  AND (r.runtime IS NULL OR r.runtime = ANY(:runner_runtimes))
  AND (r.assigned_runner_id IS NULL
       OR r.assigned_runner_id = :runner_id)      -- 指定（D17b）
```

**綁定與 labels 兩條不在這裡**（D18 延後）。V2.3 會把綁定那條加回來，
**而且要加在最前面**——那時它授權的是機密。

**重排維持指定**：被指定的 run 變 `lost` 之後仍只給原本那個 runner；
attempt 用完進 `blocked`，原因寫明「指定的 Agent 連續 3 次未能完成」。

**run_logs 的儲存**：先進 PostgreSQL（簡單、可查、與 audit 同一套備份）；
若 `10` §5 的 M10 量測顯示體積失控，再改物件儲存。**先量再改。**

### AR-06 — 看板作為溝通管道（D24）

- 卡片上的訊息串：使用者留言、Agent 回覆、系統事件（領取、開始、完成、失敗）三種混排，
  來源可辨識。
- Agent 用 `cliora task say` 發言；用 `cliora task messages --since` 拉取。
  **不做中斷式推送**（理由見 D24）。
- Agent 提問 → `cliora task ask` → run 進 `waiting_for_input`，卡片顯示「等待你的回覆」，
  租約續租但不計執行逾時、**也不佔 `max_concurrent`**。
- `waiting_for_input` 逾時（預設 24h）自動結束 run，卡片退 `blocked` 並寫明原因。

### AR-06b — 任務卡產物（D29）

**能力與宣告分開**：任何 run 隨時都能附加產物；`delivery: artifact` 的宣告與 Done Gate 留到 V2.4。

- 產物**走 HTTP 端點**上傳（不做 protocol 訊息，理由見 `plan/18/00` D4）。
  **上傳到平台，不留在 node**——run 目錄有保留期，卡片是永久的（D29 §3）。
- `task_artifacts`：`task_id`、`run_id`、`message_id`(nullable)、`filename`、`content_type`、
  `size`、`sha256`、`storage_ref`、`uploaded_by`、`created_at`。**不可變**，無 update 端點。
- CLI：`cliora task attach <file> [--message "說明"]`，也可 `cliora task say --attach`。
- 三層配額：單件 10 MB、單 run 件數上限、**專案總配額**（用盡時 runner 收到明確錯誤並顯示在卡片上）。
- **提供時的安全規則（D29 §4，本工作包最容易做錯的地方）**：
  - 預設 `Content-Disposition: attachment` ＋ `X-Content-Type-Options: nosniff`，**一律下載不內嵌**。
  - 只有圖片／純文字／markdown 可內嵌預覽，走既有的預覽限制（ADR 0015 同一套）。
  - **HTML 產物不得在應用 origin 內渲染**（Cliora 是單一 origin 部署，ADR 0020）。
  - 存取控制繼承 Project（`project.view`），無公開連結、無可猜 URL。
- **不保證產物不含機密**：誠實寫進 ADR 與 UI 文案。

### AR-07 — RBAC 與 API

新增動作：`agent.view`、`agent.manage`（註冊、停用、並行度）、`run.dispatch`、`run.cancel`。
**`agent.manage` 本期不含「綁定 Project」**（那是 V2.3 的事），但歸屬仍是 Admin，
理由在 V2.3 會兌現：綁定＝授權取用機密。

```text
GET    /api/agents                          agent.view
PATCH  /api/agents/{id}                      agent.manage   停用／並行度
GET    /api/projects/{id}/repositories       project.view
POST   /api/projects/{id}/repositories       project.manage  登記 repo（身分，不含憑證）
POST   /api/tasks/{id}/dispatch              run.dispatch   掛上佇列
GET    /api/tasks/{id}/runs                  project.view
GET    /api/runs/{id}                        project.view
GET    /api/runs/{id}/logs                   project.view   分頁
POST   /api/runs/{id}/cancel                 run.cancel
POST   /api/tasks/{id}/messages              task.update 或 run 憑證   留言（可帶 artifact_ids）
POST   /api/tasks/{id}/artifacts             task.update 或 run 憑證   上傳產物
GET    /api/artifacts/{id}                   project.view   下載（attachment，不內嵌）
DELETE /api/artifacts/{id}                   project.manage 僅配額用盡時，需理由 ＋ audit
```

`POST /dispatch` 接受 optional `assigned_runner_id`（不給＝任一符合資格者，這是預設）。

> **2026-08-11 裁決：留言與上傳產物是 `task.update`，不是 `project.view`。**
> 原文把那兩條標成 `project.view`，而 **Viewer 持有 `project.view`**
> ——那會是一個唯讀角色的寫入路徑，直接牴觸 `rbac.py` 的
> 「handing Viewer a write would contradict the read-only viewer the rest of the
> system promises」。改成 `task.update` 之後 Viewer 讀得到但發不了言（與「不能拖卡」一致），
> 而 run token 的 scope 不必動——它本來就有 `task.update`。
> **`GET` 版本仍是 `project.view`**：讀寫分開，不是整條端點升級。

**兩種失敗要分得出來**（D17b 邊界 2）：

| 情況 | 回應 | 卡片顯示 |
|---|---|---|
| 指定的 runner **不符資格**（已停用／runtime 不符／不支援非互動執行） | `409` ＋ 指名是哪一個條件 | 不入佇列，dispatch 當下就擋下 |
| 指定的 runner **暫時離線或忙碌** | `202` 正常入佇列 | 「等待指定的 Agent：dev-vm-01（目前離線）」 |

> 原本這張表的第一列以「沒綁 Project」為主要例子。D18 延後之後，
> 例子換成停用與 runtime 不符，**而「兩種失敗必須分得出來」這條規則不變**。

### AR-08 — 前端

- **Agents 頁**（Infrastructure 群組下）：runner 清單、所在 node、runtimes、labels（**顯示，不比對**）、
  並行度、目前負載、run 目錄配額用量、啟用開關。
  - 線上狀態就是 node 的線上狀態（D16），不另做一套指示燈。
  - **容量或磁碟用盡時顯示原因，不是顯示成離線。**
  - 每個 runner 顯示「目前被指定的卡片數」。
  - **本期沒有「綁定的 Project」欄**（D18 延後）。取而代之要有一行說明：
    **「任何 runner 都可以領取任何專案的卡片。授權邊界是 enrollment。」**
    這句話不寫，使用者會以為有一個他沒找到的綁定設定。
- **Project Settings 的 Repository 區**：登記 host／path／default branch。
  **明示本期不管理憑證**：「clone 使用該 node 上既有的 git 認證。V2.3 起改為平台管理。」
- **卡片上的「派給 Agent」**：預設「任一符合資格的 Agent」；可改為指定某一個。
  不符資格的顯示為停用並附原因（不是隱藏）。
- **看板卡片顯示 run 狀態**：排隊中／執行中（哪個 agent）／等待回覆／失敗。
- **Run 詳情頁**：狀態、時間軸、**clone 的 repo 與 commit**、**run 目錄大小**、
  log 串流（可跟隨、可搜尋、明示截斷）、取消按鈕。
- **卡片訊息串**與**產物區**：見 `09` §4.6／§4.6b。

> **驗收素材（D30）**：**正式 repo 可以了。**
> 原本的限制（「用 scratch clone 或 fork」）成立的理由是「run 沒有隔離，直接在 workspace 執行」。
> 裁決移除了那個前提：run 拉的是一份自己的 clone、不 push、`origin` 還被移掉了，
> 對正式 repo 的影響是零。**第一次仍建議用 scratch clone 走一遍**，
> 確認清理與配額之後再對正式 repo 跑。

## 這一階段明確不做

- **平台**不做 git push、不做分支命名空間、不做 PR／MR（V2.3／V2.4）。
  **Agent 自己 push 不在「不做」清單上**——那是允許的（§AR-04b 第 3 點）。
- 不碰機密／環境變數（V2.3）。**clone 用 node 上既有的認證**（AR-04b）。
- 不做 `project_agents` 綁定、不做 label 比對（V2.3／後續）。
- 不做自動指派、排程最佳化、負載平衡（`00` §9）。
- 不做「把 run 升級成互動 Session」（D26）。
- **不讓 run 碰使用者的 workspace 綁定**——那一層從此只服務互動式 Session。

## 出口條件

1. **未指定** agent 的卡片：任一 runner 都領得到（本期沒有綁定，所以「任一」就是字面意思）。
2. **指定** agent 的卡片：只有那一個 runner 領得到，其他 runner **永遠不會被 offer 它**。
3. 指定一個**已停用**或**runtime 不符**的 runner → dispatch **回 409 不入佇列**，訊息指名是哪一條。
4. 指定的 runner **離線** → 正常入佇列，卡片顯示「等待指定的 Agent（目前離線）」；
   上線後被它領走。**文案與「沒有可用的 Agent」不同。**
5. 兩個 runner 同時 poll 同一張卡 → **只有一個領到**；`task_runs` 沒有兩列。
6. **`source: repo` 的卡被領走後，run 目錄裡出現一份 clone**，
   `commit_sha` 回報到平台並顯示在 Run 詳情頁。
7. **run 目錄不在任何 allowed root 內**：既有的檔案瀏覽 API 讀不到它；
   而 daemon 在 run root 落在 allowed root 內時**拒絕以 runner 模式啟動並指名**。
8. **平台的任何路徑都沒有碰使用者的 workspace**：run 進行中與結束後，
   對 workspace 做 `git status --porcelain` **完全為空**。
   ⚠️ **不是「Agent 讀不到」**——那件事平台沒有實作（AR-02b 規則 1）。
8b. **混合用途的 node 是看得見的**：`allowed_roots` 非空時 Agents 頁顯示
   **⚠ 混合用途（Agent 可讀取那些目錄）**，`agentd doctor` 印同一行。
9. **run 摘要記錄得出這個 run 有沒有動到遠端**（`git remote -v` ＋ 未推送 commit 數），
   而且一次 Agent 自己發的 `git push` **會成功**（第二次裁決：不擋）。
10. 缺 git 憑證時 clone **快速失敗**（不掛在密碼提示上）：
    `run.failed` 在秒級回報，不是等到牆鐘兜底。
11. 執行中 kill 掉 runner 程序 → 租約逾時後標 `lost`、重排、被領走並完成；
    **被指定的卡重排時仍只給原本那個 runner**。
12. 重排三次都失敗 → 卡片進 `blocked`，原因寫明，不無限重試。
13. `run.cancel` → runner 真的停下來，**process group 下無殘留**。
14. Run log 超過上限 → 從中間截斷、明示截斷位元組數，不是靜默丟棄；**截斷不切斷一行 JSON**。
14b. 🆕 **一個「還在跑但很慢」的 run 不會被誤殺**：每 60 秒吐一個事件、共 20 分鐘 → 正常完成。
14c. 🆕 **一個真的掛住的 child 在 idle 上限內被收掉**（`RUN_IDLE_TIMEOUT`），**不是等牆鐘**。
14d. 🆕 **runner 掛了（`lost` → 重排）與 child 掛了（`RUN_IDLE_TIMEOUT` → 不重排）是兩種結果。**
15. Agent `cliora task ask` → 卡片顯示等待回覆；使用者回覆後 Agent 拉得到；
    24h 未回覆自動退 `blocked`。
16. **互動式 Session 完全不受影響**：run 進行中同時開一個 Session，兩者互不干擾；
    `terminal_sessions` 沒有多出 run 的列。
17. Agent 在執行中 `cliora task attach report.md --message "初步發現"` → 訊息與產物同時出現在卡片；
    **run 目錄被清掉後產物仍可下載**。
18. **`delivery: none` 的卡在工作目錄留下變更 → `git diff` 被附成一件產物**，不是靜默丟棄。
19. 上傳一個 `.html` 產物 → 下載時帶 `Content-Disposition: attachment` 與 `nosniff`；
    **應用 origin 內沒有任何路徑會渲染它**。
20. 專案產物配額用盡 → runner 收到明確錯誤並顯示在卡片，**不是靜默失敗**。
21. **run 目錄配額用盡 → runner 停止領取新工作並回報原因**，平台顯示為「磁碟用盡」而非「離線」。
22. 已附加的產物**沒有任何 API 可以修改**；刪除只有 `project.manage` 且需理由，寫 audit。
23. 旗標關閉：完整 V1 回歸全綠。

## 風險

| 風險 | 對策 |
|---|---|
| 雙重領取 | 原子 `UPDATE ... WHERE runner_id IS NULL`；出口條件 5 |
| runner 死掉任務永遠卡住 | 租約 ＋ 逾時重排 ＋ 上限；出口條件 11、12 |
| **指定的 agent 永遠不上線，卡片無聲卡住** | 卡片顯示「等待指定的 Agent（離線）」而非「排隊中」；D17b 刻意不做自動退回 |
| **Agent 推出去的東西沒有人知道** | 不擋（第二次裁決：這是刻意給的自由），但**要看得見**：run 摘要的兩行（`git remote -v` ＋ 未推送 commit 數）＋ M-AR-8 統計實際發生率。**偵測不等於阻止，而本期刻意選了偵測**（AR-04b 第 4 點） |
| **紅線 4 的措辭在裁決之後不準確** | `00` §7 第 1、2 條的主詞已於同日改為「平台的 push 路徑」。不改的話 V2.3 的人會讀到一條「Agent 只能推 `cliora/`」的紅線，而那在 V2.2 就不是真的 |
| 缺 git 憑證時 clone 掛住 | `GIT_TERMINAL_PROMPT=0` ＋ `GIT_ASKPASS=/bin/false` ＋ SSH `BatchMode=yes`；出口條件 10 |
| run 目錄撐爆磁碟 | 單 run ／ node 總量兩層配額 ＋ 保留期清理 ＋ M12；出口條件 21 |
| **run root 被設在 allowed root 裡面**，兩條路徑互通 | daemon 啟動時檢查並**拒絕啟動**；出口條件 7 |
| ⚠️ **Agent 在混合用途的 node 上讀了使用者的 workspace** | **平台沒有技術上的隔離**（同一個 OS 使用者、家目錄刻意不隱藏、無 namespace）。三道：① `allowed_roots: []` 的專用 node 讓它恆真；② **平台回報 `dedicated` 並在 Agents 頁顯示 ⚠**，讓混合用途是一個看得見的選擇；③ `codex exec -s workspace-write` 在 codex 路徑上更緊，但那是 runtime 給的。**不做 mount namespace**，理由見 `plan/18/04b` §3.4 |
| repo 每次都完整 clone 太慢 | bare mirror ＋ `git worktree`；M11 在開工前量 |
| run log 撐爆資料庫 | 單 run 上限 ＋ 保留期 ＋ M10，必要時改物件儲存 |
| **產物成為 stored XSS 管道** | 預設下載不渲染 ＋ `nosniff` ＋ 白名單預覽 ＋ HTML 絕不在應用 origin 渲染（出口條件 19） |
| 產物撐爆磁碟 | 三層配額；用盡時明確報錯（出口條件 20） |
| 產物隨 run 目錄被清掉 | 上傳到平台儲存，與 run 保留期無關（出口條件 17） |
| 產物含機密 | 無法保證，誠實寫進 ADR 與 UI |
| `waiting_for_input` 佔容量 | 24h 逾時 ＋ 不佔 `max_concurrent`（出口條件 15） |
| run 與 Session 的狀態機混在一起 | `task_runs` 是獨立的表與獨立的狀態機；出口條件 16 |
| **一個專案的原始碼會被 clone 到任何一台有 runner 的 node 上** | **這不是存取控制的退步**：人本來就看得到所有專案（`backend/app/api/http/projects.py:109` 的 docstring ＋ ADR 0027 Consequences 已記載這個既有揭露），也本來就能在任何 node 的 allowed root 上開 Session 讀程式碼。**真正變的是「程式碼落在哪台機器」**：以前 `project_workspaces` 是 Admin 刻意建立的紀錄，現在 runner 繞過它。處置是**寫下來而不是加機制**：ADR 0029 的 Consequences 記一段，UI 上明說授權邊界是 enrollment（AR-08），V2.3 用 `project_agents` 收斂 |
| **一張卡的 blast radius 是「它落在哪台機器」** | 兩次裁決的組合（任何 node 可領任何卡 ＋ 憑證不必唯讀）。**部署姿態問題不是平台問題**：ADR 0023 已宣告 node 是可拋棄的隔離 VM。安審第一節要寫下接受這個姿態的前提：**runner node 應該是專用的** |
