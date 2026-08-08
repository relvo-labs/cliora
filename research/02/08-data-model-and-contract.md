# 07 — 資料模型、契約與版本節奏

## 1. 既有基線（2026-08-08 核對）

| 項目 | 現況 |
|---|---|
| Migration | 到 `0020_node_file_upload` |
| Contract | v1.9.0 |
| `agentd` | 0.7.0 |
| RBAC 動作 | 16 個，`UNENFORCED_ACTIONS` 為空集合 |
| 既有資料表 | `roles`、`users`、`nodes`、`node_runtimes`、`node_workspace_roots`、`enrollment_tokens`、`node_credentials`、**`terminal_sessions`**、`session_connections`、`workspace_favorites`、`node_metric_samples`、`node_tunnels`、`tunnel_integration`、`node_tunnel_settings`、`audit_logs` |

> `version2.md` §10 稱之為 `sessions` 的表，實際名稱是 **`terminal_sessions`**。

## 2. 新增資料表

全部是權威表（D1：平台 DB 是真實來源）。

| 表 | 階段 | Migration |
|---|---|---|
| `projects`、`project_workspaces`、`activity_events` | V2.0 | 0021 |
| `process_definitions`、`epics`、`user_stories`、`tasks`、`task_dependencies`、`task_sessions` | V2.1 | 0023 |
| **`requirements`、`feature_specs`、`task_proposals`** | **V2.1**（表與人工表單）／V2.5（Agent 驅動） | 0023 |
| `session_tokens` | V2.1 | 0024 |
| `agent_runners`、`project_agents`、`task_runs`、`run_logs`、`task_messages`、**`task_artifacts`** | V2.2 | 0026 |
| `project_secrets`、`project_repositories` | V2.3 | 0027 |
| `execution_plans`、`verification_reports` | V2.4 | 0028 |
| `evidence_items` | V2.4 | 0029 |
| `document_patch_proposals` | V2.5 | 0030 |

seed migration 另計（各自獨立一支）：`0022`（`project.*`）、V2.1 的 `task.*`、V2.2 的 `agent.*`／`run.*`、V2.4 的 `process.manage`。

### `tasks` 的欄位

合併 Monstrare 卡片 schema、`version2.md` §7.3，與 V2 執行模型需要的四個新欄位。

```text
id                UUID
project_id        FK
epic_id           FK nullable      ← 未分類桶（D4）
user_story_id     FK nullable
card_ref          VARCHAR(64)      ← 人類可讀編號 TASK-123，專案內唯一
title / description / objective / scope / non_goals
stage             六值（D3）
risk / priority
owner_user_id     nullable
assigned_runner_id FK nullable     ← 指定 agent（D17b）；**null = 任一符合資格者，這是預設**
required_labels   JSONB            ← 能力需求（D18）
readiness         JSONB            ← DoR 七項 boolean
gates             JSONB            ← 六項 {approved_by, approved_at}
acceptance_criteria JSONB
links / refs      JSONB
version           INTEGER          ← 樂觀鎖

-- V2 執行模型（D21）
source            none|repo|existing_branch
repository_id     FK nullable
base_branch       VARCHAR nullable
delivery          none|artifact|branch|pull_request|existing_pr    ← 五值（D21／D29）
target_branch     VARCHAR nullable ← PR 合併回哪裡，不是推送目標
existing_pr_ref   VARCHAR nullable
required_secrets  JSONB            ← 必須是 project.allowed_secret_names 的子集
```

三個設計說明：

- **`gates` 存核准者與時間，不只是 boolean。** 「agent 輸出不是核准」在資料層的形式，就是這一格永遠有一個人類 user_id。
- **`acceptance_criteria` 用 JSONB 不獨立建表。** 隨 Task 一起讀寫，沒有獨立查詢需求；獨立表會讓「改一行 AC」變成多列 upsert 與孤兒清理。
- **`source` 與 `delivery` 分開**（D21）：要不要程式碼、成果怎麼離開，是兩個問題。混成一個欄位就做不出「調查型任務」。

### `task_runs` 與狀態機

```text
id / task_id / project_id / runner_id(nullable) / seq
status        queued|claimed|running|waiting_for_input|succeeded|failed|lost|cancelled
attempt       INTEGER            ← 重排計數，上限 3
claimed_at / lease_expires_at / started_at / finished_at
result        succeeded|failed|no_changes|delivered_branch_only
delivery_ref  JSONB              ← {branch, pr_url, commit_sha, diff_stat}
error_code / summary / created_by
```

```text
queued → claimed → running → succeeded
                          ↘ failed
                          ↘ waiting_for_input → running
   ↑                      ↘ cancelled
   └── lost（租約逾時）→ 重排（attempt+1）→ 用完進 blocked
```

**原子認領**：`UPDATE task_runs SET runner_id=?, claimed_at=now(), lease_expires_at=? WHERE id=? AND runner_id IS NULL`。回 0 列＝被別人領走，撤回 offer。這條 WHERE 是「雙重領取不可能」的唯一保證。

### `task_artifacts`（D29）

```text
id / task_id / run_id(nullable) / message_id(nullable)
filename / content_type / size / sha256
storage_ref              ← DB blob 或物件儲存的引用
uploaded_by              ← 人類 user_id 或 runner id
created_at
```

**不可變**：沒有 update 端點。要更新就附一件新的，時間軸自然呈現版本。刪除只有 `project.manage`，且僅在配額用盡時，需理由 ＋ audit。

**保留期與 run log 不同，這是最容易寫錯的一點**：

| | `run_logs` | `task_artifacts` |
|---|---|---|
| 是什麼 | **診斷**紀錄 | **交付物** |
| 誰清、何時 | 保留期到期自動刪 | **跟著卡片走**；卡片在就在 |
| 上限 | 單 run 5 MB，超過截斷 | 單件 10 MB、單 run 件數、**專案總配額** |

**提供時**：預設 `Content-Disposition: attachment` ＋ `X-Content-Type-Options: nosniff`；只有圖片／純文字／markdown 可內嵌預覽；**HTML 絕不在應用 origin 內渲染**（D29 §4）。

### `project_secrets`

```text
id / project_id / name / kind(env|git_pat|git_ssh_key|provider_token)
value_encrypted / dek_wrapped / key_version    ← 信封加密：DEK 以主金鑰包裝
created_by / created_at / rotated_at / last_used_at / deleted_at
UNIQUE (project_id, name)
```

**沒有任何 API 回傳 `value_encrypted` 或其明文。** 這一條要有針對 OpenAPI schema 的斷言測試，不只是「我們沒寫那個 endpoint」。

`projects.allowed_secret_names` JSONB 是名稱 allowlist；卡片的 `required_secrets` 必須是它的子集。

`project_repositories` 需要 `auth_kind`（`pat`／`ssh`）、`credential_secret_id`，以及 **`provider_token_secret_id`（nullable）**——因為 **SSH 只有 git 傳輸沒有 API，開 PR 必定要第二枚機密**（D20）。設定畫面就要檢查這個組合，不是等 run 跑到最後才失敗。

### 與 `version2.md` §10 的差異

| `version2.md` 列的表 | 處置 |
|---|---|
| `project_members` | **延後**。V2.0 用既有三角色 ＋ `owner_user_id` |
| `documents` / `document_versions` | **不建表**。文件在使用者 repo；平台存路徑 |
| `document_patches` | **改為 `document_patch_proposals`**（V2.5）：只存提案與人的決定，**平台不套用**——接受後走一張正常的 `delivery: pull_request` 卡片，PRD 的修改就跟程式碼一樣有 PR 可審 |
| `task_acceptance_criteria` / `verification_checks` | 併入 JSONB |
| `task_dependencies` | **建表**（需要循環偵測查詢） |

判準：**沒有獨立查詢需求、隨父物件一起讀寫的東西用 JSONB**；有關聯查詢需求的才建表。

## 3. 既有表的改動（全部是新增 nullable 欄位）

若採納 **D31**（mockup 走 Pinggy 預覽），`node_tunnels` 另加一個 nullable `run_id`——讓預覽 tunnel 能隨 run 一起關閉，並在 Run 詳情頁顯示。**沒有其他欄位需要動**：`protection`／`basic_auth_user`／`basic_auth_hash`／`allowed_ips` 三種保護策略的欄位早已存在（ADR 0022）。


```sql
-- 0021 (V2.0)
ALTER TABLE terminal_sessions ADD COLUMN project_id UUID NULL
  REFERENCES projects(id) ON DELETE SET NULL;
-- 0023 (V2.1)
ALTER TABLE terminal_sessions ADD COLUMN task_id UUID NULL
  REFERENCES tasks(id) ON DELETE SET NULL;
```

**Agent Run 不寫 `terminal_sessions`。** 它有自己的表與狀態機，兩條路徑在資料層就分開（D26／AR-01）。

沒有任何既有欄位被改變型別、可空性或預設值。

## 4. Protocol

| 訊息 | 階段 | Contract | `agentd` |
|---|---|---|---|
| （無） | V2.0 / V2.1 | v1.9.0 不變 | 0.7.0 不變 |
| `runner.register` / `registered` / `poll` | V2.2 | v1.10.0 | 0.8.0 |
| `run.offer` / `accept` / `decline` / `lease_renew` | V2.2 | v1.10.0 | 0.8.0 |
| `run.progress` / `log_chunk` / `complete` / `failed` / `cancel` | V2.2 | v1.10.0 | 0.8.0 |
| `run.artifact`（metadata ＋ 分塊上傳） | V2.2 | v1.10.0 | 0.8.0 |
| `run.offer` 的 `spec` 擴充 `secrets` 與 `source` | V2.3 | v1.11.0 | 0.9.0 |
| `run.complete` 的 `delivery_ref` | V2.4 | v1.12.0 | 0.10.0 |
| （無） | **V2.5** | v1.12.0 不變 | **0.10.0 不變** |

**既有訊息一個位元組都不改。** 沿用 ADR 0026 讓 `filesystem.store` 與 `filesystem.upload` 並存的同一個判斷：一條已經正確的路徑不該為了對稱被改動。

每個新訊息交付 fixtures：valid ＋ invalid（缺 `run_id`、未知 phase、`log_chunk` 超過上限、`capacity` 為負、`secrets` 出現在非 offer 訊息、非 UTC 時間、未知型別）。

**特別要有的一條 invalid fixture**：`run.offer` 以外的任何訊息攜帶 `secrets` 欄位 → 拒絕。這是紅線 1 修訂後不變式的機器檢查。

## 5. RBAC

| 動作 | 階段 | Viewer | Developer | Admin | 強制點 |
|---|---|---|---|---|---|
| `project.view` | V2.0 | ✅ | ✅ | ✅ | `GET /api/projects*`、`/api/tasks*`、`/api/runs*` |
| `project.manage` | V2.0 | ❌ | ❌ | ✅ | Project CRUD、workspace 綁定 |
| `task.create` | V2.1 | ❌ | ✅ | ✅ | `POST` epics／user-stories／tasks |
| `task.update` | V2.1 | ❌ | ✅ | ✅ | `PATCH /api/tasks/{id}` |
| `task.approve` | V2.1 | ❌ | ✅ | ✅ | `POST /api/tasks/{id}/gates/{gate}`、**規格核准、提案接受、UI 變體選定**（D28） |
| `agent.view` | V2.2 | ✅ | ✅ | ✅ | `GET /api/agents` |
| `agent.manage` | V2.2 | ❌ | ❌ | ✅ | runner 啟用、並行度、Project 綁定 |
| `run.dispatch` | V2.2 | ❌ | ✅ | ✅ | `POST /api/tasks/{id}/dispatch` |
| `run.cancel` | V2.2 | ❌ | ✅ | ✅ | `POST /api/runs/{id}/cancel` |
| `secret.manage` | V2.3 | ❌ | ❌ | ✅ | Project secrets 與 repositories |
| `process.manage` | V2.4 | ❌ | ❌ | ✅ | 流程定義覆寫 |

四點理由：

- `agent.manage`、`secret.manage`、`process.manage` 歸 Admin，與 `node.manage`／`enrollment.manage` 同層：那是組織層決定。**綁定一個 runner 到一個 Project 等於授權它取用該專案的機密**，這不是 Developer 的權力。
- `task.approve` 獨立於 `task.update`：核准與編輯是不同的權力。**Agent 憑證的 scope 寫死不含它。**
- `run.dispatch` 獨立於 `task.update`：把工作掛上佇列會消耗運算資源並可能推 git，與改一個欄位不同量級。它可以**指定** runner，但指定不授權——沒綁定的 runner 一律在 dispatch 當下被拒（D17b）。
- Viewer 只持有兩個 view 動作，維持既有的唯讀角色定義。

**實作約束**：每個動作在同一張 ticket 內接上強制點（`test_every_action_is_enforced_somewhere` 雙向失敗）；同步 `frontend/src/api/dto.ts` 的 `ACTION_*` 與 `docs/permission-matrix.md`。

## 6. 兩種憑證

| | Session Token（V2.1） | Runner 憑證（V2.2） |
|---|---|---|
| 給誰 | 互動式 Session 裡的 Agent | `agentd` 的 runner 模式 |
| 怎麼發 | 每個 Session 一枚，投影到 `.cliora/` | **就是既有的 node credential**（D16，不新發） |
| 範圍 | 單一 Project | 該 node 綁定的所有 Project |
| 失效 | Session 結束即失效 | 沿用既有的 credential 撤銷 |
| 永遠不含 | `task.approve`、`project.manage`、`secret.manage`、`process.manage` | 同左 |

## 7. 資源層級授權

| 資源 | 規則 |
|---|---|
| Project | 持有 `project.view` 者皆可見（與 Node 既有做法一致） |
| Workspace 綁定 | 綁定時 `sessions.authorize_workspace()`；**每次使用重跑**（紅線 2） |
| Task／Run | 屬於可見 Project 即可讀；寫入需對應動作 |
| Gate 核准 | `task.approve` ＋ **actor 必須是人類**（token 一律拒絕） |
| Run offer 資格 | 五條件：任務 `ready` ＋ `dependsOn` 滿足 ＋ **runner 綁了該 Project**（授權）＋ runtime／labels 相符（能力）＋ `assigned_runner_id` 為 null 或等於該 runner（指定）。**指定永遠不能覆蓋綁定** |
| 機密下放 | 只給該卡片 `required_secrets` 列出的、且在 Project allowlist 內的 |
| Run 目錄 | daemon 擁有，**不在 allowed root**，既有檔案 API 不得觸及 |
| 卡片產物 | 繼承 Project（`project.view` 可下載）；**無公開連結、無可猜 URL**；上傳需 run 憑證或 `project.view` |
| 互動式 Session | 沿用既有 `authz.may_*`，**不新增概念** |

## 8. 環境變數

| 變數 | 預設 | 說明 |
|---|---|---|
| `CLIORA_PROJECTS_ENABLED` | `false` | V2 總開關（D12） |
| `CLIORA_AGENT_RUNS_ENABLED` | `false` | **Agent Run 獨立開關**：可以只用看板不用 runner |
| `CLIORA_SESSION_TOKEN_TTL_H` | `24` | Session token 上限效期 |
| `CLIORA_RUN_LEASE_TIMEOUT_S` | `180` | 租約逾時 |
| `CLIORA_RUN_MAX_ATTEMPTS` | `3` | 重排上限 |
| `CLIORA_RUN_LOG_MAX_BYTES` | `5242880` | 單次 run 的 log 上限（診斷，有保留期） |
| `CLIORA_ARTIFACT_MAX_BYTES` | `10485760` | 單件卡片產物上限 |
| `CLIORA_ARTIFACT_PROJECT_QUOTA_MB` | `1024` | 專案產物總配額 |
| `CLIORA_RUN_WAITING_TIMEOUT_H` | `24` | `waiting_for_input` 逾時 |
| `CLIORA_SECRET_MASTER_KEY` | — | **機密主金鑰（已裁決：環境變數）**。缺少／過短／等於 dev 預設值 → 拒絕啟動並指名。**與既有的 `CLIORA_SECRET_ENCRYPTION_KEY`（ADR 0022 的 tunnel 憑證）同一種模式但獨立**——兩者輪替時機不同，共用會互相綁住 |

daemon 側另有 run 目錄配額、mirror 與 run 的保留期，走既有 config 檔慣例。

**兩個旗標而不是一個**：看板（V2.1）與自主執行（V2.2+）的風險等級差很多，組織可能想要前者不要後者。

## 9. 版本節奏

| 階段 | Contract | `agentd` | Central | 前端 | CLI |
|---|---|---|---|---|---|
| V2.0 | 不變 | 不變 | minor | minor | — |
| V2.1 | 不變 | 不變 | minor | minor | 0.1.0 |
| V2.2 | v1.10.0 | 0.8.0 | minor | minor | 0.2.0 |
| V2.3 | v1.11.0 | 0.9.0 | minor | minor | 0.2.x |
| V2.4 | v1.12.0 | 0.10.0 | minor | minor | 0.3.0 |
| V2.5 | 不變 | **不變** | minor | minor | 0.4.0 |

新 Central ＋ 舊 daemon：新訊息在舊 daemon 上是未知型別，被既有處理拒絕（fixture 已涵蓋）。Central 要轉成「此 node 的 agentd 需升級到 0.x 才能擔任 Agent Runner」的可行動訊息，**而不是 500，也不是讓該 node 從 runner 清單消失**。
