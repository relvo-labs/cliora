# 02 — `AR-03`：資料層（migration `0029`／`0030`／`0031`）

現況基線是 **`0028_node_removal_sessions`**（`plan/17/09` §5），所以本期是 `0029` 起。
規劃寫的 `0026` 已經被 V2.1 用掉了（流程種子），已回寫 `research/02/08` §2。

> **2026-08-10 裁決對本章的三個影響**：
> ① **`project_agents` 不在本期**——延後到 V2.3，與 `project_secrets` 同一支 migration，
>   因為它授權的就是機密（`research/02/01` D18）。
> ② **`project_repositories` 進本期**（只有身分欄位，憑證欄位是 V2.3）——
>   Agent 要自己 clone，平台就得知道 repo 在哪。
> ③ **`task_runs` 沒有 `workspace_node_id`／`workspace_path`**，改為 `repository_id`／
>   `source_ref`／`commit_sha`／`disk_bytes`——run 不再使用 workspace 綁定。

三支 migration 而不是一支，沿用 V2.1 的分法（`plan/17/09` §3 第 2 條）：
**領域不同、自然鍵不同、downgrade 的影響範圍不同**。

| Migration | 內容 | 為什麼分開 |
|---|---|---|
| `0029_agent_runs` | 八張新表（含 `project_repositories`；**不含 `project_agents`**） | 主體 |
| `0030_seed_agent_actions` | `agent.view`／`agent.manage`／`run.dispatch`／`run.cancel` 進三個角色的 `permissions.actions` | 角色權限是**種子資料**，與結構變更的 downgrade 語意不同；併在一起會讓其中一個的回滾帶走另一個 |
| `0031_node_agent_runner` | `nodes.agent_runner BOOLEAN NOT NULL DEFAULT false` | 與 `0027_node_context_projection` 逐字同形狀：**預設 false 且不回填**——0.8.0 的節點確實不是 runner |

## 1. 上下行演練

沿用 `scripts/tk/gate-migration-roundtrip.sh`：`upgrade head` → `pg_dump --schema-only`
→ `downgrade` 到 `0028` → 再 dump → **與 `AR-00` 的基線逐位元組相同**。
`GATE-AR-SCHEMA-ADDITIVE` 另外斷言 `0028 → head` 的 diff **只有新增**。

`0029` 的 downgrade 必須把八張表按 FK 反序 drop，且 `0031` 的 downgrade 要 `drop_column`——
`nodes` 是既有表，留一個孤兒欄位會讓下一期的基線比對永遠對不上。

## 2. `0029_agent_runs` — 八張表

### 2.1 `agent_runners`

```text
id                UUID PK
node_id           UUID FK nodes(id) ON DELETE CASCADE   -- UNIQUE
name              VARCHAR(128)
runtimes          JSONB NOT NULL DEFAULT '[]'    -- 該 node 上 runner-capable 的 runtime 集合
labels            JSONB NOT NULL DEFAULT '[]'
max_concurrent    INTEGER NOT NULL DEFAULT 1
max_waiting       INTEGER NOT NULL DEFAULT 5
enabled           BOOLEAN NOT NULL DEFAULT true
dedicated         BOOLEAN NOT NULL DEFAULT false  -- 回報：該 node 沒有 allowed root
registered_at / last_registered_at / disabled_at
created_at / updated_at
UNIQUE (node_id)
```

三個與規劃不同的地方，各有理由：

- **`UNIQUE (node_id)` 與 `runtimes` 是集合**（`00-…md` D9）。規劃寫「一個 node 可跑多個
  runner（不同 runtime）」，在資料模型上等價於一列帶一個集合，而後者少一個會說謊的欄位
  （多列共用一條 WSS，「哪一列在線」永遠等於 node 的狀態）。
- **沒有 `status` 欄，也沒有 `last_seen_at`。** D16 的推論：runner 的線上狀態**就是**
  node 的線上狀態。存第二份就有第二份會過期。API 回應的 `online` 由
  `NodeConnectionRegistry.is_connected(node_id)` 現算，與 Nodes 頁同一條路徑
  （`services/registry.py:185`）。**規劃列的 `status`／`last_seen_at` 是這個的兩個副本，刪掉。**
- **`max_waiting`**（本計畫新增）：`waiting_for_input` 的 run 不佔 `max_concurrent`
  （ADR 0029 第 5 點），所以需要第二個上限，否則一個 runner 可以掛著任意多個等回覆的 run。
- 🆕 **`dedicated`（本計畫新增）**：由 daemon 回報 `len(workspace.allowed_roots) == 0`。
  它是一個**姿態回報而不是設定**——與 `nodes.agent_runner`、`sandbox_bypass` 同一種欄位。
  它存在的理由很具體：「Agent 讀不到使用者的 workspace」這件事**平台沒有技術上的隔離**
  （`04b-…md` §3.4），而 `allowed_roots` 為空的 node 上它才是恆真的。
  **這一格讓「混合用途」變成 console 上一個看得見的 ⚠ 而不是一句沒人驗的 runbook 散文。**
  **不做強制**（拒絕在有 allowed root 的 node 上跑 runner）：
  一個人的單台開發 VM 同時開 Session 與跑 runner 是最常見的情境。

`runtimes` 的內容由 `runner.register` 帶上來，且只包含 **`runner_capable`** 的 runtime
（`00-…md` D8）——一個裝了 `codex` 但探不到非互動旗標的 node，`runtimes` 是空陣列，
它會註冊成功但永遠不符合任何卡片的資格。**這是刻意的**：註冊失敗會讓人以為機器壞了，
註冊成功但 `runtimes: []` ＋ Agents 頁上一行「codex：偵測到，但這個版本不支援非互動執行」
才說得清楚。

### 2.2 `project_repositories`（**本期只有身分欄位**）

```text
id              UUID PK
project_id      UUID FK projects(id) ON DELETE CASCADE
scheme          VARCHAR(8)   NOT NULL          -- https | ssh
host            VARCHAR(255) NOT NULL          -- github.com、gitlab.example.com
path            VARCHAR(512) NOT NULL          -- Lei-k/Traqora
default_branch  VARCHAR(255) NOT NULL
label           VARCHAR(128)
created_by      UUID FK users(id) ON DELETE RESTRICT
created_at / updated_at
UNIQUE (project_id, host, path)
CHECK (scheme IN ('https','ssh'))
```

**V2.3 才加的三欄不要現在建**：`auth_kind`、`credential_secret_id`、
`provider_token_secret_id`。這與 V2.1 的 D11（`source`／`delivery` 建欄不接行為）
**刻意做相反的選擇**，理由是那三欄是 FK 到一張本期不存在的表（`project_secrets`），
而一個指向不存在的表的 nullable UUID 沒有任何讀者可以驗證它。

**URL 拆成 `scheme`／`host`／`path` 三欄而不是存一個字串**，這是本期的安全需求：
`runner.git.allowed_hosts` 要對 `host` 做精確比對，而從一個自由字串裡剖 host 出來
是一個會出錯的動作（`https://github.com@evil.example/` 這種東西）。
**拆開之後 userinfo 不可表示**——`04b-…md` §5.2 明文禁止 URL 帶 `user:pass@`
（它會出現在 `git remote -v`、reflog 與錯誤訊息裡），這裡是那條禁令在 schema 上的形式。

`created_by` 用 `RESTRICT`：登記一個 repository 是一個決定，離職的人不該把
「誰登記的」帶走。

> **`project_agents` 呢？** 不在本期（2026-08-10 裁決）。它會在 V2.3 與 `project_secrets`
> 同一支 migration 出現，形狀不變（`project_id`／`runner_id`／`enabled`，複合主鍵）。
> **本期不預先建表**：一個不授權任何東西的授權表，會讓 V2.3 的安全審查失去一個真正的
> 檢查點——它會看到「表已經在了」而不是「這是一條新的授權邊界」。

### 2.3 `task_runs`

```text
id                 UUID PK
task_id            UUID FK tasks(id) ON DELETE CASCADE
project_id         UUID FK projects(id) ON DELETE CASCADE   -- 去正規化，見下
runner_id          UUID FK agent_runners(id) ON DELETE SET NULL   -- nullable
seq                INTEGER NOT NULL                -- 這張卡的第幾次 run
status             VARCHAR(24) NOT NULL DEFAULT 'queued'
attempt            INTEGER NOT NULL DEFAULT 1
assigned_runner_id UUID FK agent_runners(id) ON DELETE SET NULL   -- 快照，見下
repository_id      UUID FK project_repositories(id) ON DELETE SET NULL  -- nullable（source: none）
source_kind        VARCHAR(16)                     -- none | repo | existing_branch
source_ref         VARCHAR(255)                    -- 要 checkout 的 ref
commit_sha         CHAR(40)                        -- 認領後由 runner 回報
disk_bytes         BIGINT                          -- run 目錄大小，結束時回報
runtime            VARCHAR(32)
queued_at / claimed_at / lease_expires_at / started_at / finished_at
waiting_since      TIMESTAMPTZ                     -- waiting_for_input 的計時起點
last_event_at      TIMESTAMPTZ                     -- 最後一個 JSONL 事件的時間（D21）
result             VARCHAR(32)                     -- succeeded|failed|no_changes|cancelled
error_code         VARCHAR(64)
summary            TEXT
log_bytes          BIGINT NOT NULL DEFAULT 0
log_truncated_bytes BIGINT NOT NULL DEFAULT 0
logs_expire_at     TIMESTAMPTZ                     -- 見 §2.4
created_by         UUID FK users(id) ON DELETE SET NULL
created_at / updated_at
UNIQUE (task_id, seq)
CHECK (status IN ('queued','claimed','running','waiting_for_input',
                  'succeeded','failed','lost','cancelled'))
```

五個設計說明：

- **`project_id` 是去正規化的。** 三條路徑都要它而不想 join `tasks`：run token 的資源檢查、
  產物配額（`task_artifacts.project_id` 的來源）、以及**V2.3 加回綁定之後的資格查詢**。
  `tasks.project_id` 不可變（沒有搬家 API），所以這份副本不會漂。
  （本期的資格查詢**不**按 project 過濾——裁決移除了綁定，見 §2.3 索引那段。）
- **`assigned_runner_id` 是快照，不是讀 `tasks.assigned_runner_id`。**
  重排要維持指定（D17b），而卡片的指定欄位在 run 進行中可以被人改。
  重排讀的是 run 上的快照，改卡片影響的是**下一次** dispatch。
  **這條要有測試**，否則「重排維持指定」會在有人編輯卡片時靜默失效。
- 🆕 **沒有 `workspace_node_id`／`workspace_path`。** 裁決之後 run 不使用 workspace 綁定，
  run 目錄由 daemon 自己決定（`<state>/.cliora/runs/<run_id>/`，`04b-…md` §2）。
  **這是本章最重要的一個「不存在的欄位」**：只要它在，就會有人拿它去 join
  `project_workspaces`，而那條 join 就是兩套授權模型互通的第一步。
- 🆕 **`repository_id`／`source_kind`／`source_ref` 在 dispatch 當下從卡片快照下來**，
  不是認領當下讀 `tasks`。理由與 `assigned_runner_id` 相同：卡片在 run 進行中可以被人改，
  而一次 run 應該是對「當時那張卡」的執行。
- 🆕 **`last_event_at`（D21）**：child 的事件流最後一次有動靜的時間。
  **它不是租約**——租約答「runner 活著嗎」，這一格答「child 在前進嗎」，
  而 idle timeout 的判定在 **daemon 端**（它有事件流），Central 這一格只是為了
  **讓 Run 詳情頁顯示「最後動靜：3 分鐘前」**。
  由 `run.progress` 帶上來，best-effort（與 `run_tokens.last_used_at` 同一種欄位）。
- 🆕 **`commit_sha` 與 `disk_bytes` 由 runner 回報**（`run.progress` 的
  `phase="checked_out"` 與 `run.complete`）。前者讓 Run 詳情頁答得出
  「這次跑的是哪一版程式碼」，後者是 M12 的資料來源。
- **`log_bytes` 與 `log_truncated_bytes` 分開兩欄。** 出口條件 9 要求「明示截斷位元組數」，
  一個「已收 N 位元組」的計數器答不了「丟了多少」。
- **沒有 `delivery_ref`。** 規劃的欄位表列了它，那是 V2.4 的東西（`delivery` 本期不接行為，
  `00-…md` D11）。建一個永遠是 null 的 JSONB 只會讓 V2.4 以為它已經有語意了。

索引三條，各對一個真實查詢：

```sql
CREATE INDEX ix_task_runs_queue   ON task_runs (status, queued_at)
  WHERE status = 'queued';                                  -- 資格查詢（見下）
CREATE INDEX ix_task_runs_lease   ON task_runs (lease_expires_at)
  WHERE status IN ('claimed','running','waiting_for_input'); -- 租約 sweep
CREATE INDEX ix_task_runs_task    ON task_runs (task_id, seq DESC);            -- 卡片上的 run 歷史
```

🆕 **佇列索引不再帶 `project_id`**：裁決移除綁定之後，資格查詢不按 project 過濾
——任何 runner 都看得到所有 `queued` 的 run，所以掃的是「全部 queued 依時間排序」。
V2.3 加回綁定時這條索引要改回帶 `project_id`，**而那是一次索引變更不是一次查詢重寫**
（`03-…md` §3 的 SQL 已經把綁定那條 JOIN 的位置留好了）。

前兩條是 partial index：佇列與租約兩條路徑都是**每秒都在跑**的（poll 與 sweep），
而 `task_runs` 裡絕大多數的列是已完成的終態。第三條不加條件，因為卡片要看全部歷史。

**沒有第四條索引**，因為沒有第四個查詢——沿用 `0023` 那句「一個投機加上的索引是一份沒有讀者的寫入成本」。

### 2.4 `run_logs`

```text
id            UUID PK
run_id        UUID FK task_runs(id) ON DELETE CASCADE
seq           INTEGER NOT NULL          -- runner 端的 chunk 序號（聚合後取區段的第一個）
data          TEXT NOT NULL             -- 已聚合的區段，≤64 KiB；內容是 JSONL 事件 ＋ stderr 行
truncated     BOOLEAN NOT NULL DEFAULT false
received_at   TIMESTAMPTZ NOT NULL
UNIQUE (run_id, seq)
CREATE INDEX ix_run_logs_run ON run_logs (run_id, seq);
```

🆕 **內容是 JSONL 事件行，不是純文字**（D21）：`claude --output-format stream-json`
與 `codex exec --json` 的每一行是一個事件。兩個後果：
① **分塊器不得切斷一行 JSON**——一個被切成兩半的事件在 UI 上無法渲染，
「不切斷一行」比「湊滿 32 KiB」重要；
② **體積比純文字大**，所以 M-AR-2 量的是 JSONL 速率而不是文字速率，
而 `CLIORA_RUN_LOG_MAX_BYTES` 的 5 MB 預設要用那個數字複查。

**一列是一個聚合後的區段，不是一個 chunk**（`00-…md` D3）。Central 端每個 run 一個
記憶體緩衝，攢滿 64 KiB 或 2 秒才寫一列。`seq` 取該區段第一個 chunk 的序號，
所以序號會跳——與 `card_ref` 同樣的性質：**它是排序鍵不是計數器**。

`ON DELETE CASCADE` 是安全網；**正常路徑是保留期清理**。清理的依據放在
`task_runs.logs_expire_at`（run 結束時寫入：成功 `now()+3d`、失敗 `now()+14d`），
清理迴圈以 run 為單位刪整組，而不是逐列比對 `received_at`——一個 run 的 log
半組被刪掉比整組被刪掉更難解釋。

**`logs_expire_at` 放在 `task_runs` 而不是 `run_logs`**：它是 run 的性質（成功還失敗），
一個 run 的所有列共用同一個答案。放在 `run_logs` 就是把同一個值抄 N 次。

### 2.5 `task_messages`

```text
id           UUID PK
task_id      UUID FK tasks(id) ON DELETE CASCADE
run_id       UUID FK task_runs(id) ON DELETE SET NULL     -- nullable
author_kind  VARCHAR(16) NOT NULL      -- user|agent|system
author_user_id UUID FK users(id) ON DELETE SET NULL       -- nullable
author_runner_id UUID FK agent_runners(id) ON DELETE SET NULL  -- nullable
body         TEXT NOT NULL
kind         VARCHAR(24) NOT NULL DEFAULT 'message'       -- message|question|answer|event
event_kind   VARCHAR(32)               -- 只有 kind='event' 時有值
created_at   TIMESTAMPTZ NOT NULL
CHECK (author_kind IN ('user','agent','system'))
CHECK ((author_kind = 'user') = (author_user_id IS NOT NULL))
CREATE INDEX ix_task_messages_task ON task_messages (task_id, created_at, id);
```

四個說明：

- **`author_kind` 用兩個分開的欄位而不是一個多型 `author_id`**：
  與 `activity_events.actor_kind` 同一條理由（`services/activity.py` 的 docstring）——
  `author_id IS NULL` 已經有「系統」的意思，三種東西長得一樣就沒有一種說得清楚。
  CHECK 約束把「使用者訊息一定有 user_id」寫進 schema 而不是應用碼。
- **`kind` 區分 `question` 與 `message`。** 卡片頂部與看板要顯示「等待你的回覆」，
  而那要能只看訊息串就判定，不必去查 run 的狀態（看板一次要顯示幾十張卡）。
- **`kind='event'` 的系統事件也存這裡**，不是只進 `activity_events`。
  兩者的讀者不同：`activity_events` 是 Project 層的時間軸，訊息串是**一張卡的對話**，
  而 D24 要求三種來源**混排**。存兩份的代價寫進 ADR 0029：
  系統事件是短的、封閉詞彙的，而混排的可讀性是這條決策的產品目的。
- **索引帶 `id` 當第三個鍵**：`cliora task messages --since <ts>` 要穩定分頁，
  同一毫秒的兩筆訊息不能因為排序不穩而漏讀。

`ON DELETE SET NULL` 而不是 CASCADE：run 的紀錄可能被清（保留期），
**但卡片上的對話是產品內容，沒有保留期**——與 `activity_events` 同一條規則。

### 2.6 `task_artifacts` ＋ `task_artifact_blobs`

分兩張表（`00-…md` D5）：

```text
task_artifacts
  id            UUID PK
  task_id       UUID FK tasks(id) ON DELETE CASCADE
  project_id    UUID FK projects(id) ON DELETE CASCADE     -- 配額查詢用，去正規化
  run_id        UUID FK task_runs(id) ON DELETE SET NULL
  message_id    UUID FK task_messages(id) ON DELETE SET NULL
  filename      VARCHAR(255) NOT NULL
  content_type  VARCHAR(128) NOT NULL     -- 伺服器判定的，不是上傳者宣告的
  size          BIGINT NOT NULL
  sha256        CHAR(64) NOT NULL
  storage_ref   VARCHAR(255) NOT NULL     -- 本期恆為 'db:<blob_id>'
  uploaded_by_kind VARCHAR(16) NOT NULL   -- user|agent
  uploaded_by_user_id   UUID FK users(id) ON DELETE SET NULL
  uploaded_by_runner_id UUID FK agent_runners(id) ON DELETE SET NULL
  created_at    TIMESTAMPTZ NOT NULL
  deleted_at    TIMESTAMPTZ               -- 軟刪除，見下
  deleted_by    UUID FK users(id) ON DELETE SET NULL
  delete_reason TEXT
  CREATE INDEX ix_task_artifacts_task ON task_artifacts (task_id, created_at DESC)
    WHERE deleted_at IS NULL;
  CREATE INDEX ix_task_artifacts_project ON task_artifacts (project_id)
    WHERE deleted_at IS NULL;            -- 專案配額

task_artifact_blobs
  artifact_id   UUID PK FK task_artifacts(id) ON DELETE CASCADE
  bytes         BYTEA NOT NULL
```

五個說明：

- **分表是為了列表查詢。** 卡片詳情要列出十件產物的檔名與大小；如果 blob 在同一張表，
  一個沒寫 `defer()` 的 ORM 查詢就會把 100 MB 拖進記憶體。分表讓那個錯誤**不可能發生**。
- **`content_type` 是伺服器判定的**（`00-…md` D14）。上傳者宣告的 `Content-Type`
  一律丟棄，由副檔名 ＋ magic bytes 決定，且落在一張封閉表之外的一律存成
  `application/octet-stream`。這一格是 stored XSS 的主要入口。
- **軟刪除。** 產物不可變（D29 §6），刪除只有 `project.manage` 且需理由。
  硬刪除會讓「這件產物被誰以什麼理由刪掉」消失，而那正是需要理由的原因。
  blob 則是**硬刪**（`DELETE FROM task_artifact_blobs`）——配額要真的被釋放，
  否則「刪除是配額用盡時的唯一出路」就是假的。**metadata 留、內容刪**，
  這個不對稱要寫進 ADR 0030。
- **`project_id` 去正規化**：專案總配額是 `SUM(size) WHERE project_id=? AND deleted_at IS NULL`，
  走 `ix_task_artifacts_project`，不必 join `tasks`。
- **`sha256`**：不是為了去重（同一份檔案附兩次是兩件產物，時間軸自然呈現版本），
  是為了下載時可驗證，以及 M16 判斷重複上傳的比例。

**沒有 update 端點**，這是 schema 之外的承諾，由 `08-…md` §3 的一條 OpenAPI 斷言守著：
`/api/artifacts/{id}` 只有 `GET` 與 `DELETE`。

### 2.7 `run_tokens`

```text
id           UUID PK
run_id       UUID FK task_runs(id) ON DELETE CASCADE
project_id   UUID FK projects(id) ON DELETE CASCADE
task_id      UUID FK tasks(id) ON DELETE CASCADE
token_hash   VARCHAR(128) NOT NULL UNIQUE
scopes       JSONB NOT NULL
issued_at / expires_at / revoked_at / last_used_at
CREATE INDEX ix_run_tokens_run ON run_tokens (run_id);
```

與 `session_tokens`（`0024`）**逐欄對照著設計**，差別只有三處，各有理由：

| | `session_tokens` | `run_tokens` | 為什麼 |
|---|---|---|---|
| 主體 | `session_id` NOT NULL | `run_id` NOT NULL | 出口條件 12：run 不得有 `terminal_sessions` 的列（`00-…md` D6） |
| 發行者 | `issued_by` NOT NULL FK users | **沒有這一欄** | run 不是人開的。「誰 dispatch 的」在 `task_runs.created_by`，一次 join 就有；把它抄過來會讓「token 的持有者是誰」多一個似是而非的答案 |
| 額外欄 | — | `task_id` | CLI 的每一次呼叫都要驗「這張卡屬於這個 run」，存下來省一次 join，而且 run 與 task 的關係不可變 |

**相同的三處是重點**：只存 HMAC（同一把 `CLIORA_TOKEN_PEPPER`）、
`scopes` 在發行時快照、`revoked_at` 的列保留 90 天供稽核。

## 3. 既有表的改動

三處，全部是新增：

| 表 | 改動 | 為什麼在這一期 |
|---|---|---|
| `tasks` | `assigned_runner_id` 加上 **FK → `agent_runners(id) ON DELETE SET NULL`** | `0023` 明寫「No foreign key: `agent_runners` arrives in V2.2」（`0023_task_board.py:315` 附近的註解）。本期兌現 |
| `nodes` | `agent_runner BOOLEAN NOT NULL DEFAULT false`（`0031`） | 與 `0027_node_context_projection` 同形狀。舊 node 顯示「需升級到 0.9.0」而不是 500 |
| `activity_events` | 無 schema 變更，只新增 `kind` 詞彙 | 見 §5 |

**`tasks` 沒有其他改動。** `required_labels`、`source`、`delivery`、`required_secrets`
在 `0023` 就建好了，本期只是開始讀其中兩個（`required_labels`、`assigned_runner_id`）
並在 dispatch 時擋掉另外三個（`00-…md` D11）。

## 4. 狀態機

```text
              dispatch
                 │
                 ▼
              queued ──────────────── cancelled（run.cancel，任何非終態）
                 │ poll 命中（原子認領）
                 ▼
              claimed ─── run.accept ──▶ running ──▶ succeeded
                 │                          │  ▲          │
                 │ run.decline              │  │          ▼
                 └──▶ queued                │  │       failed
                 │                          ▼  │
                 │              waiting_for_input
                 │                          │
                 │        24h 未回覆         │
                 ▼                          ▼
               lost ◀────────────────── lost（租約逾時）
                 │
                 │ attempt < 3 → queued（attempt+1，維持 assigned_runner_id）
                 └ attempt = 3 → 卡片 stage = 'blocked'，run 停在 failed
```

四條寫進 CHECK 或服務層的規則：

1. **`queued → claimed` 只能由那條原子 UPDATE 造成**（`03-…md` §2）。服務層沒有第二個
   寫 `runner_id` 的地方，`GATE-AR-SINGLE-CLAIM` 用文字掃描斷言
   `SET runner_id` 在 `backend/app/` 裡只出現一次。
2. **`run.decline` 把 run 放回 `queued` 並清空 `runner_id`／`claimed_at`／`lease_expires_at`，
   但 `attempt` 不變。** 拒絕不是失敗——runner 可能只是剛好滿了。
   為了避免同一個 runner 立刻再領一次形成熱迴圈，服務層維持一個
   **記憶體中的 `(run_id, runner_id) → 冷卻到期時間`**（60 秒），
   這是唯一一個不進 DB 的狀態，理由寫在程式碼裡：它跨 Central 重啟不需要保留，
   重啟之後最壞情況是多一次 decline。
3. **`lost` 是終態。** 重排**建立新的一列 `task_runs`**（`seq+1`、`attempt+1`），
   不是把舊列改回 `queued`。理由：Run 詳情頁要看得到「第 2 次嘗試在哪裡失敗的」，
   而一列被反覆改寫的 run 沒有那段歷史。**這與規劃的狀態圖畫法不同**（它畫成回到 `queued`），
   要寫進 ADR 0029。
4. **`attempt` 用完之後改的是卡片不是 run**：`tasks.stage = 'blocked'`，
   並在訊息串寫一筆 `kind='event'`，內容指名「指定的 Agent `<name>` 連續 3 次未能完成」
   或「連續 3 次未能完成」（有無指定的文案不同，與出口條件 4 同一條理由）。

## 5. 新增的 `activity_events` kind 與 audit action

`services/activity.py` 的 `ALL_KINDS` 是封閉詞彙，`services/audit.py` 的 `ALL_ACTIONS` 也是。
兩邊都有**雙向失敗**的測試（`test_every_activity_kind_has_a_write_site`），
所以**只加有寫入點的**——這是 `plan/17/09` §3 第 4 條學到的。

| 新增 | 哪一種 | 寫入點 |
|---|---|---|
| `run.dispatched` | activity | `POST /api/tasks/{id}/dispatch` |
| `run.claimed` | activity | 原子認領成功 |
| `run.finished` | activity | `run.complete`／`run.failed`／取消／`lost` 用盡（payload 帶 `result`） |
| `task.message_posted` | activity | 使用者留言與 Agent 發言（**不含**系統事件，那已經是 activity 本身） |
| `artifact.attached` | activity | 產物上傳成功 |
| `agent.register` | audit | `runner.register` 被接受 |
| `agent.update` | audit | 啟用／停用／並行度 |
| `agent.project_bind` / `agent.project_unbind` | audit | 綁定與解除 |
| `run.dispatch` / `run.cancel` | audit | 對應端點 |
| `artifact.upload` / `artifact.delete` | audit | 上傳（actor 可能是 runner）／刪除（必帶理由） |
| `run_token.issue` / `run_token.revoke` | audit | 沿用 `session_token.*` 的形狀 |

**Agent 的動作 `actor_kind` 標為 `agent`，`user_id` 為 null，不冒充人類**
（`research/02/00` §8）。`runner.register` 這種 node 發起的則是 `system`。
`audit_logs.user_id` 本來就 nullable（V2.1 已經驗過這條路），所以稽核端不必動 schema。

## 6. 種子（`0030`）

四個動作進三個角色，與 `research/02/08` §5 的表一致：

| 動作 | Viewer | Developer | Admin |
|---|---|---|---|
| `agent.view` | ✅ | ✅ | ✅ |
| `agent.manage` | ❌ | ❌ | ✅ |
| `run.dispatch` | ❌ | ✅ | ✅ |
| `run.cancel` | ❌ | ✅ | ✅ |

`agent.view` 進 Viewer 的理由與 `node.view`／`project.view` 相同：Viewer 可以看機隊的形狀。

`agent.manage` 進 Admin 的理由要寫在 `rbac.py` 的註解裡，而且**要寫未來式**——
本期它管的只有「啟用／停用、並行度、labels」，那三件事單看起來不像組織層的決定：

> **從 V2.3 起，`agent.manage` 還會涵蓋「把 runner 綁定到 Project」，
> 而綁定等於授權它取用該專案的機密。** 所以這個動作不能先放在 Developer 手上再收回來
> （與 `PROJECT_MANAGE` 那段註解同一條理由）。

🆕 **本期還要多寫一句，因為它是一個姿態宣告**：V2.2 沒有綁定，所以
**任何 enroll 過的 node 上的 runner 都能領任何專案的卡片、拿到任何專案的程式碼**。
授權邊界是 `enrollment.manage`（Admin），不是 `agent.manage`。
這一句要同時出現在 `rbac.py`、ADR 0029、與 Agents 頁的 UI 上（`07-…md` §2）
——三個地方，因為它是那種「不寫下來就會被當成 bug 回報」的設計。

`run.dispatch` 獨立於 `task.update` 的理由也要寫下來：
**掛上佇列會消耗運算資源、會在一台機器上 clone 一個 repo 並跑一個程序**，與改一個欄位不同量級。

種子 migration 與 `ROLE_ACTIONS` 必須一致，由 `test_permission_matrix.py` 的三條斷言守著；
同步更新 `frontend/src/api/dto.ts` 的四個 `ACTION_*` 與 `docs/permission-matrix.md`。
`UNENFORCED_ACTIONS` **保持空集合**——四個動作的強制點在 `AR-04` 同一個 PR 裡（D6 的理由）。
