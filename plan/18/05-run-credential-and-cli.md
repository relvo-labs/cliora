# 05 — `AR-08`：run 憑證與 `cliora` CLI 0.2.0

**本票是安全審查的第二節。** 它新增一種憑證，所以命中
`research/02/10` §6 的第四個觸發條件。

> **2026-08-10 裁決對本章的影響很小，而那本身是一個結果**：
> token 檔從「使用者 workspace 的 `.cliora/`」搬到「run 目錄的 `.cliora/`」，
> 而 `FindContext` 因為是「從 cwd 往上找」，**一行都不必改**（§2.1）。

## 1. `run_tokens`：第二種 Agent 憑證

### 1.1 為什麼不是 `session_tokens`

`session_tokens.session_id` 是 `NOT NULL` FK → `terminal_sessions`，`ondelete=CASCADE`
（`0024_session_tokens.py`）。出口條件 12 要求 **`terminal_sessions` 不得多出 run 的列**。
兩者不可能同時成立（`00-…md` D6）。

**被否決的兩個變體**：

| 被否決的 | 為什麼 |
|---|---|
| 把 `session_id` 改成 nullable 再加 `run_id` | 一張表兩種主體。`SessionTokenService.revoke_for_session` 的 docstring 寫「there will be a fifth door」——那句話的前提是這張表只服務一種主體，加了第二種之後它就是謊話。而且 `AgentPrincipal.session_id` 會變成 optional，四條 CLI 端點的每一個 `_same_project` 檢查都要多一個 None 分支 |
| 為 run 建一列假的 `terminal_sessions` | 直接違反出口條件 12，而且會污染 Sessions 畫面、`authz.may_*` 的每一條判斷、以及 `shell_reaper` 的掃描 |

### 1.2 形狀

前綴 `cliora_rt_`（`session_tokens` 是 `cliora_st_`）。三個理由與 V1 逐字相同
（`services/agent_auth.py:38` 的註解）：`get_current_user` 不必解析就能拒絕、
secret scanner 有 pattern、開檔案的人看得懂那是什麼。

**同一把 pepper**（`CLIORA_TOKEN_PEPPER`）、同一個 `keyed_hash`、**只存 HMAC**。
沿用而不是新做，是因為 ADR 0008 的那條建構已經被審過三次。

TTL 用 `spec.timeout_seconds + 15 分鐘`（牆鐘兜底再加一點餘裕），
**上限仍受 `CLIORA_SESSION_TOKEN_TTL_H` 約束**（預設 24 小時）
——牆鐘從 1 小時放大到 6 小時之後（`00-…md` D21），這個上限開始真的會咬到，
所以**兩者的關係要在實作時斷言一次**：`timeout_seconds + 15m` 若超過 TTL 上限，
dispatch 就要拒絕，而不是發一枚會在 run 中途過期的 token——一個 token 的效期不該超過
平台對「Agent 憑證最長活多久」的既有承諾。

失效有**四個**觸發點，全部走同一個 `revoke_for_run`：run 進終態、run 被取消、
Admin 停用該 runner、🆕 **run 目錄被保留期清理掉**（token 檔本身在 run 結束時就刪了，
但列的撤銷要跟著走，否則一個被清理的 run 會留下一枚沒有主體卻仍有效的 token）。與 `revoke_for_session` 同一條理由：**放在狀態機裡，
不是放在四條會結束 run 的路由上**。

### 1.3 scope

```python
RUN_TOKEN_SCOPES = frozenset({PROJECT_VIEW, TASK_UPDATE})
```

**與 session token 完全相同**，這是刻意的。留言、提問、附產物三件事都不需要新動作，
而 2026-08-11 的裁決讓這件事更乾淨——那三條端點現在**都是 `task.update`**：

- 留言／提問 → `POST /api/tasks/{id}/messages`，`task.update` ＋ 資源層檢查
  （「這張卡屬於這個 run」）
- 附產物 → `POST /api/tasks/{id}/artifacts`，同上
- 推進 stage → `PATCH /api/tasks/{id}`，同上

**裁決之前那兩條是 `project.view`**，於是 scope 裡的 `task.update` 只覆蓋第三條，
前兩條全靠資源層兜著。改完之後 **scope 真的對應它做的事**
——這是「不新增假動作」這個選擇能站得住的前提（見下）。

**不新增 `task.message`／`task.attach` 這種 scope-only 的假動作。**
`ROLE_ACTIONS` 是動作詞彙的單一事實來源，而
`test_every_action_is_enforced_somewhere` 是對它的雙向斷言；
一個只存在於 token scope 裡、沒有角色持有的動作會讓那個測試變成一個要記得排除的清單。

**永遠拿不到的仍然是那一組**：`task.approve`（Agent 的輸出不是核准）、
`task.create`（Agent 提案，人建立 — D28）、每一個 `file.*`、每一個 `terminal.*`、
`project.manage`、`agent.manage`、`run.dispatch`、`run.cancel`。

**最後兩個是本期新增的重點**：一個 run 不能派工給別人，也不能取消別的 run。
沒有這條，一個被 prompt injection 的 Agent 可以把整個佇列清空。

### 1.4 `AgentPrincipal` 的第二種形狀

```python
@dataclass(frozen=True, slots=True)
class AgentPrincipal:
    token_id: uuid.UUID
    kind: str                      # "session" | "run"        ← 新增
    project_id: uuid.UUID
    scopes: frozenset[str]
    session_id: uuid.UUID | None   # kind == "session" 時非 None
    run_id: uuid.UUID | None       # kind == "run" 時非 None  ← 新增
    task_id: uuid.UUID | None      # kind == "run" 時非 None  ← 新增
```

**仍然沒有 `user_id`**，理由逐字沿用 `agent_auth.py:13` 的註解：
一個帶 user_id 的 principal 遲早會被傳進某個記錄 actor 的地方，
於是 Agent 開始冒充開這個 run 的人。

`get_agent_principal` 依前綴分派到兩個 service，**`get_current_user` 對兩個前綴都直接 401**
（現況只擋 `cliora_st_`，本期要加 `cliora_rt_`——**這是一行改動，也是一條測試**）。

`kind` 是一個顯式欄位而不是「`run_id is not None`」的推導，因為
`_same_project`／`_same_task` 那幾個守衛要 `match` 它，而一個推導出來的判別式
會在有人加第三種 token 時靜默走錯分支。

### 1.5 稽核 actor

| | session token | run token |
|---|---|---|
| `audit_logs.user_id` | NULL | NULL |
| metadata `actor_kind` | `session_agent` | **`run_agent`** |
| metadata 其餘 | `session_id`, `token_id` | `run_id`, `runner_id`, `token_id` |
| `activity_events.actor_kind` | `agent` | `agent` |

`actor_kind` 兩個值不同，因為稽核上「一個人開的 Session 裡的 Agent 做的」
與「平台派出去的無人值守 run 做的」是不同的事——後者沒有任何人在旁邊。

## 2. `cliora` CLI 0.2.0

CLI **就是 `agentd` 那支二進位**（V2.1 的 D2，安裝時的 symlink ＋ argv[0] 分派）。
本期只加子命令，**不動發行方式**。

### 2.1 情境解析：**一行都不必改**

`FindContext(start, id)`（`cli.go:71`）是「從 `start` **往上**找 `.cliora/context/`，
在檔案系統根或找到為止」。run 目錄的版面（`04b-…md` §3.3）是：

```text
<run>/repo/          ← 程序的 cwd
<run>/.cliora/context/<run_id>.md + .token
```

往上一層就找到了，而那個目錄裡**只有一份** context——所以：

- `contextFrom` 的「多個情境包要指定 `--session`」分支**永遠不會觸發**。
  那個歧義只存在於「一個 workspace 同時有 Session 與 run 的投影」的場景，
  **而裁決把那個場景整個消滅了**。
- 自動選取（`len(ids) == 1`）就是正確答案，不必新增旗標。
- `source: none` 的 run 沒有 `repo/`，cwd 就是 `<run>/`，同樣找得到。

**唯一要改的是兩句訊息的措辭**，因為它們現在要涵蓋兩種主體：

| 位置 | 現在寫的 | 要改成 |
|---|---|---|
| `FindContext` 找不到時 | 「這個目錄不在一個有任務情境的 **Session** 工作區裡」 | 「這個目錄不在一個有任務情境的工作區裡（Session 或 Agent Run）」 |
| `contextFrom` 找不到 id 時 | 「找不到 **Session** %s 的情境包」 | 「找不到 %s 的情境包」 |

另外接受 `CLIORA_RUN_ID`（daemon 起 run 的程序時設），與既有的 `CLIORA_SESSION_ID` 並列。
**兩個環境變數而不是一個泛用的 `CLIORA_CONTEXT_ID`**：
它們的來源不同（一個是使用者開的 Session，一個是平台派的 run），
而讓 log 與 debug 能分辨是哪一種，值得多一個名字。

### 2.2 四個新子命令

| 命令 | 端點 | 說明 |
|---|---|---|
| `cliora task say <text> [--attach FILE]` | `POST /api/tasks/{id}/messages` | 在卡片上發言 |
| `cliora task ask <text>` | 同上，`kind=question` | 發問並讓 run 進 `waiting_for_input` |
| `cliora task messages [--since TS] [--json]` | `GET /api/tasks/{id}/messages` | 拉取；**不做中斷式推送**（D24） |
| `cliora task attach <file> [--message TEXT]` | `POST /api/tasks/{id}/artifacts` | 附產物 |

四條都沿用 `Client.do`（`cli.go:191`）與 `explain`（`cli.go:237`）的既有形狀，
**包括 D14 的離線行為**：

```text
無法連線到 Cliora（Session 可繼續工作）。
你的變更未被記錄，恢復連線後請重新執行。
```

第一句對 run 而言要換一個詞（run 不是 Session），但**第二句的性質不變**：
平台掛掉不代表 Agent 該停下來。run 的版本：

```text
無法連線到 Cliora（工作可繼續）。
這次的訊息／產物未被記錄，恢復連線後請重新執行。
```

兩句話都要有逐字比對的測試，與 `TestAnUnreachablePlatformSaysTheSessionCanContinue`
同一條路徑（`plan/17/09` §1 的 `AR-08` 對應項）。

### 2.3 `attach` 的三件事

1. **`multipart/form-data`，不是 base64 進 JSON。** 10 MB 的 base64 是 13.3 MB 的字串，
   而 Go 的 `http` 客戶端可以直接串流檔案。
2. **上傳前先算 `sha256` 並帶在欄位裡**，伺服器端重算比對——不符就 400。
   這不是防竄改（連線是 TLS），是防截斷：一個被中途砍斷的上傳應該失敗，
   而不是變成一件壞掉的產物。
3. **配額用盡時回一個明確的錯誤並在卡片上顯示**（出口條件 15）。
   `explain` 要為三個配額碼各給一句人話：

   ```text
   ARTIFACT_TOO_LARGE          這個檔案 12.4 MB，超過單件上限 10 MB。
   ARTIFACT_RUN_LIMIT          這次 run 已經附了 20 件產物，是單次上限。
   ARTIFACT_PROJECT_QUOTA      專案的產物配額已用盡（1024 MB）。請人清理後再試。
   ```

   **不是靜默失敗**——這是規劃點名的一條出口條件，而 CLI 的非零 exit code
   加上這三句話就是它的落地。

### 2.4 `ask` 的頻率限制

D28 §6：一次一個問題。CLI 端在 run 已經處於 `waiting_for_input` 時
拒絕第二個 `ask`，訊息是

```text
已經有一個問題在等回覆。請先用 `cliora task messages` 看看有沒有回應。
```

伺服器端也擋（`409 RUN_ALREADY_WAITING`），**兩端都做**：CLI 端是為了給 Agent
一句它讀得懂的話，伺服器端是為了讓這條規則不依賴 CLI 版本。

## 3. 安全審查第二節的大綱

`docs/security-review-v22.md` §2，四個問題各一段：

1. **發行**：token 在什麼時候產生、明文存在多久（一次寫入
   `<run>/.cliora/context/<run_id>.token`，0600，之後只有 HMAC）、誰能讀那個檔。
   🆕 **裁決讓這一節比原本更好答**：那個檔案在 daemon 擁有的 `StateDirectory`
   （`/var/lib/agentd`，0700，服務使用者所有）之下，**不在任何 allowed root 內**，
   所以**既有的檔案瀏覽 API 讀不到它**——V2.1 那個「token 檔要加入敏感檔分類」
   的處置在本期不必再做一次，因為整棵樹都不可達。
   剩下的邊界是「node 上能讀 `/var/lib/agentd` 的人」，
   與 V2.1 的 Session token 相同，理由也相同：node 是可拋棄的隔離 VM（ADR 0023）。
2. **範圍**：為什麼 scope 與 session token 相同、為什麼不新增假動作、
   `run.dispatch`／`run.cancel` 為什麼特別不能給（§1.3 的最後一段）。
3. **失效**：三個觸發點、90 天的列保留、以及一條測試——
   **run 結束之後拿舊 token 打任何一條 CLI 端點都要 401**。
4. **與使用者路徑的隔離**：`get_current_user` 對兩個前綴都 401 的那條測試，
   以及「沒有任何程式碼路徑能讓 run token 產生一個 `User`」這句話的機器形式
   （對 `services/agent_auth.py` 與 `api/http/deps.py` 的型別斷言）。
