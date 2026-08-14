# 02 — 資料層（`DV-02`）

三支 migration，三張新表，兩個新 RBAC 動作，**一次對既有資料的收緊**，
以及 D4 換來的**兩個驗證命令來源**（`projects` 與 `tasks` 各一欄）。

現況：`0034_seed_secret_action`，**37 張表**，RBAC 25 個動作。
本期結束：`0037`，**40 張表**，RBAC 27 個動作。

## 0. 這一張 ticket 最容易做錯的事

**AC 的 `result` 收緊是一次會動到既有資料的遷移，而它藏在一堆新表中間。**
`tasks.py:603` 今天對 `acceptance_criteria` 只檢查「是 dict 的 list」與渲染後的長度；
`result` 是自由字串，唯一的處置是 render 那一行的 `item.get('result') or '未驗'`。
所以生產資料裡的 `result` 可能是 `None`、`"未驗"`、`"passed"`、或任何人打進去的字。

**Done Gate 的「每一項 AC 都有結果」在自由字串上等於沒有檢查。**
先收緊再做 Gate，順序反了的話 Gate 上線第一天就是一個假的檢查。

## 1. migration `0035_delivery_and_verification`

三張表。**三張都只 INSERT**（D11），所以三張都沒有 `updated_at`。

### 1.1 `execution_plans`

```sql
CREATE TABLE execution_plans (
    id           UUID PRIMARY KEY,
    task_id      UUID NOT NULL REFERENCES tasks(id)      ON DELETE CASCADE,
    run_id       UUID          REFERENCES task_runs(id)  ON DELETE SET NULL,
    project_id   UUID NOT NULL REFERENCES projects(id)   ON DELETE CASCADE,
    seq          INTEGER NOT NULL,
    note         TEXT,
    steps        JSONB   NOT NULL DEFAULT '[]'::jsonb,
    created_by_kind TEXT NOT NULL,            -- 'user' | 'agent'
    created_by      UUID REFERENCES users(id) ON DELETE SET NULL,
    created_by_runner_id UUID REFERENCES agent_runners(id) ON DELETE SET NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (task_id, seq)
);
CREATE INDEX ix_execution_plans_task ON execution_plans (task_id, seq DESC);
```

`steps[]` 的形狀（**schema 在 service 層驗，不在 DB 層**，與 `acceptance_criteria` 一致）：

```json
{"title": "…", "status": "pending|in_progress|completed|skipped|failed", "note": "…"}
```

**`note` 的必填規則不在 DB 上**：`seq > 1` 時 `note` 必填（改計畫要說為什麼），
`seq = 1` 時不必。做成 CHECK 約束的話，第一版計畫與後續版本的差異會變成一條
讀不懂的 DB 錯誤；做在 service 層可以回一句話。

**`project_id` 是冗餘的**（`task_id` 就能推出來），而它在這裡是刻意的：
跨專案指標要對這三張表做聚合，而每次 join `tasks` 會讓五個指標各多一次 join。
`task_artifacts` 已經立過同一個先例（它也帶 `project_id`）。

### 1.2 `verification_reports`

```sql
CREATE TABLE verification_reports (
    id           UUID PRIMARY KEY,
    task_id      UUID NOT NULL REFERENCES tasks(id)     ON DELETE CASCADE,
    run_id       UUID          REFERENCES task_runs(id) ON DELETE SET NULL,
    project_id   UUID NOT NULL REFERENCES projects(id)  ON DELETE CASCADE,
    result       TEXT NOT NULL,      -- not_started|running|passed|failed|partial
    checks               JSONB NOT NULL DEFAULT '[]'::jsonb,
    acceptance_criteria  JSONB NOT NULL DEFAULT '[]'::jsonb,
    remaining_risks      JSONB NOT NULL DEFAULT '[]'::jsonb,
    completion_summary   TEXT,
    source       TEXT NOT NULL,      -- agent_reported|platform_observed|machine_verified
    reported_by_kind     TEXT NOT NULL,
    reported_by          UUID REFERENCES users(id) ON DELETE SET NULL,
    reported_by_runner_id UUID REFERENCES agent_runners(id) ON DELETE SET NULL,
    reported_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_verification_result CHECK (
        result IN ('not_started','running','passed','failed','partial')),
    CONSTRAINT ck_verification_source CHECK (
        source IN ('agent_reported','platform_observed','machine_verified'))
);
CREATE INDEX ix_verification_reports_task ON verification_reports (task_id, reported_at DESC);
```

**兩個 CHECK 在 DB 上而不是只在 service 層**，理由與 `tasks.delivery` 的
`ck_tasks_delivery`（`0023_task_board.py:383`）一樣：這兩個欄位的值域是**契約的一部分**，
而 Done Gate 與三個指標都在讀它們。一個寫錯的 `source` 會讓一列 Agent 自述
被畫成機器事實——那正是 D12 要防的事，**而 D12 的防線在 service 層，
CHECK 是它後面那一道**。

`checks[]`：`{"name": "…", "origin": "project|card", "argv": ["…"], "exit_code": 0,
"duration_ms": 1234, "output_tail": "…"}`。
`output_tail` 上限 **2000 字元**，只留尾巴——一條失敗的測試命令，有用的資訊在最後面。

**`origin` 是 D4 的資料形式，而它是第二軸不是第三級。**
`source` 回答「誰觀察到這件事」，`origin` 回答「誰指定要跑這件事」——
兩個來源都不是 Agent 選的（卡片宣告要 `task.approve`），
所以兩者的 `source` 都是 `machine_verified`，而 reviewer 仍看得出差別。
**沒有 CHECK 約束**（它在 JSONB 裡），service 層驗兩值。

### 1.3 `evidence_items`

```sql
CREATE TABLE evidence_items (
    id           UUID PRIMARY KEY,
    task_id      UUID NOT NULL REFERENCES tasks(id)     ON DELETE CASCADE,
    run_id       UUID          REFERENCES task_runs(id) ON DELETE SET NULL,
    project_id   UUID NOT NULL REFERENCES projects(id)  ON DELETE CASCADE,
    kind         TEXT NOT NULL,
    source       TEXT NOT NULL,
    written_by_kind      TEXT NOT NULL,
    written_by           UUID REFERENCES users(id) ON DELETE SET NULL,
    written_by_runner_id UUID REFERENCES agent_runners(id) ON DELETE SET NULL,
    payload      JSONB NOT NULL DEFAULT '{}'::jsonb,
    collected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_evidence_kind CHECK (kind IN (
        'git_state','changed_files','diff_stat','command_result',
        'run_event','delivery','agent_finding','agent_limitation','agent_risk')),
    CONSTRAINT ck_evidence_source CHECK (
        source IN ('agent_reported','platform_observed','machine_verified'))
);
CREATE INDEX ix_evidence_items_task ON evidence_items (task_id, collected_at DESC);
CREATE INDEX ix_evidence_items_run  ON evidence_items (run_id);
```

**`payload` 的大小上限在 service 層**（16 KiB／列，一次 run 最多 64 列）。
不在 DB 上是因為 JSONB 沒有便宜的長度約束，而在 service 層可以回一句
「這件證據太大，請改附成產物」——那正是產物存在的理由。

## 2. migration `0036_delivery_columns_and_ac_results`

四組改動，**第四組會動到既有資料**。

### 2.1 `projects` 三欄 ＋ `tasks` 的驗證命令

```sql
ALTER TABLE projects
  ADD COLUMN verification_commands        JSONB   NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN process_overrides            JSONB   NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN require_project_verification BOOLEAN NOT NULL DEFAULT false;

ALTER TABLE tasks
  ADD COLUMN verification_commands JSONB NOT NULL DEFAULT '[]'::jsonb;
```

**兩個來源，同一個形狀**（D4）：`[{"name": "unit tests", "argv": ["pytest","-q","tests/"]}]`。
兩邊各上限 **8 條**，每條 argv **最多 16 個元素、每個元素 ≤128 字元**——
合起來要塞得進 `spec.allowed_verification_commands` 的既有預算
（`maxItems: 16`、每項 `maxLength: 256`），而 `origin` ＋ tab 分隔的編碼會膨脹。
`03-…md` §4.2 有算式。

⚠️ **`tasks.verification_commands` 不進 `EDITABLE_FIELDS`。**
它有自己的端點（`PUT /api/tasks/{id}/verification-commands`）並要求 **`task.approve`**，
而那是本期唯一一處刻意不走 `PATCH` 的卡片欄位。理由在 D4：
`RUN_TOKEN_SCOPES = {PROJECT_VIEW, TASK_UPDATE}`（`agent_auth.py:70`），
把它放進 `EDITABLE_FIELDS` 等於讓 Agent 自選要跑什麼驗證。
**用既有的 scope 邊界，而不是在 `_validated()` 裡加一行 if**——
`tasks.py` 的 module docstring 已經表態過不要一個檢查 principal 型別的依賴。

`require_project_verification`（預設 `false`，`00-…md` §0.3）：
開啟時 Done Gate 額外要求「至少一條 `origin: project` 的檢查跑過」。
**預設關閉是刻意的**：一個一開始就擋人的開關，會讓卡片宣告這條路在第一天就被繞過。

`process_overrides`：`{"readiness_disabled": [...], "gates_disabled": [...], "wip": {...}}`（D13）。
**只允許停用既有項目**——service 層驗每一個 key 都存在於 default 定義裡，
不存在就 422 並指名。

### 2.2 `task_runs` 三欄

```sql
ALTER TABLE task_runs
  ADD COLUMN delivery_state  VARCHAR(24),   -- NULL | pending_pr | delivered | branch_only | failed
  ADD COLUMN pushed_branch   VARCHAR(255),
  ADD COLUMN delivery_ref    TEXT;          -- PR URL / branch URL
```

**`delivery_state` 是 PR 建立的佇列**（D17）：`finish()` 只把它設成 `pending_pr`，
背景工作把它推進到 `delivered` 或 `branch_only`。
**沒有 CHECK 約束**，理由與 `task_runs.result` 一致（那一欄今天也沒有）：
這一欄的值域會隨 delivery 模式成長，而它不是契約的一部分——
它是一個內部狀態機，而狀態機的驗證在 service 層讀得懂。

**`pushed_branch` 是 daemon 回報的**（contract v1.13.0，node→central 方向），
而不是 Central 從 `run_branch()` 推出來的。差別在於：
**推出來的那個是意圖，回報的那個是事實**，而 PR 只能開在事實上。

### 2.3 `tasks` 的 `--force` 三欄

```sql
ALTER TABLE tasks
  ADD COLUMN force_done_reason TEXT,
  ADD COLUMN force_done_by     UUID REFERENCES users(id) ON DELETE SET NULL,
  ADD COLUMN force_done_at     TIMESTAMPTZ;
```

**為什麼在 `tasks` 上而不是只靠 `activity_events`**：D10 要求
「理由**永久可見**在 Task Detail 上」。activity 是一條時間軸，
而時間軸會被後續事件推下去——一個滑到第 200 筆的旁路等於看不見。
三欄放在卡片上，畫面就一定畫得出來。**activity 那一筆照樣要記**，兩者不衝突：
一個是「現在這張卡是被強推的」，一個是「當時發生了什麼」。

### 2.4 AC 的 `result` 收緊（D9）— **會動到既有資料**

```python
# 0036 的 upgrade() 尾段，逐列處理而不是一句 UPDATE：
#   JSONB 陣列裡的一個欄位要逐項改寫，而 SQL 的寫法會比 Python 難讀十倍
#   ——而這一段的可讀性直接關係到「它到底改了什麼」。
VALID = {"passed", "failed", "partial", "not_verified"}
changed = 0
for task_id, criteria in rows:
    updated = []
    for item in criteria or []:
        if item.get("result") not in VALID:
            item = {**item, "result": "not_verified"}
            changed += 1
        updated.append(item)
    ...
print(f"0036: normalised {changed} acceptance criteria results")
```

**印出被改的列數**，而且印在 migration 的輸出裡。
一次無聲的資料改寫是最難在事後說明的東西，而這一次改寫的對象
正好是「這件事憑什麼算做完」的依據。

⚠️ **`downgrade()` 不還原這一步。** 舊值沒有被保留，也不該被保留——
還原需要一張影子表，而那張表會為了一次不會發生的降級永久存在。
**這一句要寫進 migration 的 docstring**，因為 `GATE-DV-MIGRATION-ROUNDTRIP`
比的是 schema 不是資料，它不會抱怨。

## 3. migration `0037_seed_delivery_actions`

兩個新動作，**都是 Admin 專屬**：

| 動作 | 誰有 | 為什麼是新的而不是複用 |
|---|---|---|
| `process.manage` | Admin | 改流程定義會改變所有卡片的判準。`project.manage` 是專案設定，而流程是跨專案的語彙 |
| `task.force_done` | Admin | D10。複用 `task.approve` 會讓「核准一個 gate」與「跳過整個 Done Gate」同權 |

seed 要**冪等**（重跑 `UPDATE 0`），沿用 `0034_seed_secret_action` 的形狀。

三處同步（`plan/20/08` §3 第 8 條記過這三個守門測試會紅，而它們該紅）：

- `frontend/src/api/dto.ts` 的 `ACTION_*` 常數（`test_all_actions_match_the_frontend_constants`）
- audit 動作常數（`test_audit_actions_match_the_frontend_constants`）——
  本期新增 `PR_CREATE`、`TASK_FORCE_DONE`、`PROCESS_OVERRIDE`
- `error_catalog.py` 的新碼（`test_error_catalog` 的兩條，**它同時抓新增沒登記與舊的沒清掉**）

### 3.1 本期的新錯誤碼

| 碼 | 何時 | 使用者要做什麼 |
|---|---|---|
| `TASK_PROVIDER_UNSUPPORTED` | dispatch：repo 的 host 沒有 adapter | 改用 `delivery: branch`，或換一個支援的 host |
| `TASK_PR_TARGET_MISSING` | dispatch：`pull_request` 但沒有 `target_branch` | 填 target branch |
| `TASK_EXISTING_PR_OUT_OF_NAMESPACE` | dispatch：`existing_pr` 的 base 不在 `cliora/` 內（D7） | **訊息要直說**：平台只推得到 `cliora/` 裡面 |
| `TASK_DONE_GATE_UNMET` | Done Gate：缺項 | `details.missing` 逐項列出 |
| `TASK_FORCE_REASON_REQUIRED` | `--force` 沒帶理由 | 填理由 |
| `VERIFICATION_REPORT_INVALID` | 報告 schema 不合 | 指名哪個欄位 |
| `EVIDENCE_PAYLOAD_TOO_LARGE` | evidence 超過 16 KiB | 改附成產物 |
| `PLAN_SEQ_CONFLICT` | 兩個併發的 `plan snapshot` 撞同一個 `seq` | 重試（service 層自動重試一次，第二次才回這個碼） |
| `PROCESS_OVERRIDE_UNKNOWN_KEY` | 覆寫指向不存在的 readiness／gate | 指名那個 key |
| `PROVIDER_UNREACHABLE` | provider API 不可達 | 分支已推，稍後由人開 PR |
| `PROVIDER_REFUSED` | provider 回 4xx | 帶上 provider 的 message（**不帶 token**） |

## 4. 模型與 repository

三張新表各一個 SQLAlchemy 模型，**docstring 要寫「為什麼只 INSERT」**——
這三張表的完整性保證只有這一條，而它在程式碼裡沒有其他痕跡
（沒有 CHECK、沒有 trigger）。

**Repository 層**：三張表各一支，放 `app/repositories/`。
查詢一律帶 `task_id` 或 `run_id`，**沒有跨專案的原始查詢**——
指標走 `services/dashboard.py` 的聚合，而那是唯一一個可以不帶 `task_id` 的呼叫端。

## 5. 驗收

| # | 斷言 | 怎麼驗 |
|---|---|---|
| 1 | 40 張表 | `schema.txt` 與基線比對，只新增 |
| 2 | `downgrade` 回 `0034` 與基線**逐位元組相同** | `GATE-DV-MIGRATION-ROUNDTRIP` |
| 3 | seed 重跑 `UPDATE 0` | 跑兩次 `alembic upgrade head` |
| 4 | AC 收緊印出列數，且收緊後所有值都在四值內 | migration 輸出 ＋ 一條 DB 測試 |
| 5 | 三張表沒有 UPDATE 路徑 | `GATE-DV-APPEND-ONLY`：掃 repository 層不得出現對這三張表的 `update()` |
| 6 | 兩個新動作 Admin 專屬，且 run 憑證拿不到 | `test_agent_api.py` 兩條 |
| 7 | 十一個新錯誤碼都在 catalog 裡，且沒有過期碼 | 既有的 `test_error_catalog` 兩條 |
