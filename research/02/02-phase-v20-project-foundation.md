# V2.0 — 專案基座（ticket 前綴 `PJ-`）

## 目標

讓「專案」成為平台上真實存在的東西：可以建立、可以綁定散落在不同 Node 上的 Workspace、可以從它進到 Session，並且看得到這個專案上發生過什麼。

這一階段**完全不碰檔案**：不需要新的 protocol 訊息、daemon 一行都不用改。這是刻意的：先讓 V2 的骨架在不觸碰任何既有風險面的前提下站起來。

## 前置條件

- D1、D2、D12、D13 已裁決（D2 與 D1 已於 2026-08-08 定案：功能內化、平台 DB 為真實來源）。
- `research/prd.md` 已增訂 Project 章節、`traceability/requirements.json` 已註冊 `FR-PROJECT-*`（見 `10`）。
- ADR 0027 已撰寫並接受。

## 工作包

### PJ-01 — 需求變更與範圍宣告（**第一張，不可跳過**）

1. `research/prd.md` 新增「Project 管理」章節：Project 的定義、狀態、與 Workspace／Session 的關係、Ad-hoc Session 仍受支援的明文宣告。
2. `docs/adr/0027-v2-project-layer-and-source-of-truth.md`：記錄 **D2（Monstrare 功能內化，含「誰在讀它」的邊界表）**、D1（平台 DB 為真實來源）、D12（相容機制）、D13（RBAC）、`.cliora/` 投影的規則（含流程檔以版本號目錄避開 `O_EXCL` 的做法），以及**拒絕的替代方案**（複製 Monstrare 檔案進使用者 repo、平台寫入 `.claude/skills/`、寫到 node 的 `~/.claude/`、平台代跑驗證命令）。並標註流程定義源自 Monstrare（MIT）。
3. 修訂 `.agent/skills/cliora-project-context/SKILL.md` 的範圍句：把「no task routing」精確化為「平台管理任務**紀錄**，不做自動指派與排程」，並註明 V2 的四條紅線（`00` §7）。
4. `traceability/requirements.json` 註冊新需求與 AC。

**驗收**：`make check` 內的 traceability gate 通過；ADR 的 Related 欄位正確指向 0014／0016／0024／0026。

### PJ-02 — 資料層

新增 migration `0021_projects.py`：

- `projects`：`id`、`name`、`slug`、`description`、`status`（`active`/`paused`/`archived`）、`owner_user_id`、`default_node_id`（nullable）、`default_runtime`（nullable）、`created_at`、`updated_at`。
- `project_workspaces`：`id`、`project_id`、`node_id`、`path`、`label`、`is_primary`、`created_at`。唯一鍵 `(project_id, node_id, path)`。
- `activity_events`：`id`、`project_id`、`task_id`（nullable，V2.1 才有值）、`session_id`（nullable）、`actor_user_id`（nullable，系統事件為 null）、`kind`、`payload`（JSONB）、`occurred_at`。索引 `(project_id, occurred_at desc)`。
- `terminal_sessions` 新增 **nullable** `project_id`（外鍵 `ON DELETE SET NULL`）。

`terminal_sessions.task_id` 留到 V2.1 一起加（那時 `tasks` 表才存在，它是真的外鍵）。

**驗收**：`make migrate` 前後 `pg_dump --schema-only` 差異只有上述四項；既有表的欄位定義逐欄比對無變化。

### PJ-03 — RBAC 與稽核

- `backend/app/services/rbac.py` 新增 `PROJECT_VIEW`、`PROJECT_MANAGE`（`task.*` 三個到 V2.1、`process.manage` 到 V2.3 再加，避免 unenforced）。
- seed migration `0022_seed_project_actions.py`。
- `frontend/src/api/dto.ts` 對應的 `ACTION_*` 常數。
- 每個 Project 寫入動作（建立／更新／封存／綁定／解綁）一筆 audit。

**驗收**：`backend/tests/db/test_permission_matrix.py` 三條測試全綠（含 `test_every_action_is_enforced_somewhere` 的雙向檢查）。

### PJ-04 — Project API

```text
GET    /api/projects                    列表（含 status 篩選、我的專案）
POST   /api/projects                    建立                        project.manage
GET    /api/projects/{id}               詳情
PATCH  /api/projects/{id}               改名／描述／狀態             project.manage
POST   /api/projects/{id}/workspaces    綁定 (node_id, path)         project.manage
DELETE /api/projects/{id}/workspaces/{wid}                          project.manage
GET    /api/projects/{id}/overview      摘要：workspace 數、進行中 session、近期活動
GET    /api/projects/{id}/activity      分頁時間軸
```

綁定時的驗證**重用既有函式**：`app/services/sessions.authorize_workspace(node, path)`（enabled-roots 前綴檢查）。不要複製一份新的路徑檢查邏輯。

> 紅線 2 提醒：綁定成功不代表該路徑之後永遠合法。任何以綁定路徑發起的操作（Session 建立、`.cliora/` 投影）都要**重跑**同一個檢查，而不是信任綁定表。`WorkspaceFavorite` 的既有註解已經寫過這個教訓，沿用同樣的措辭。

### PJ-05 — Session 關聯（最小版）

- `POST /api/sessions` 接受 optional `project_id`。
- 若給了 `project_id`：驗證 workspace 屬於該 Project 的綁定之一（不符就是 400，不是靜默忽略）。
- `GET /api/sessions` 支援 `project_id` 篩選。
- Session 建立／結束時寫入 `activity_events`。

**不做**：從 Project 頁面「一鍵開 Session」的完整流程留到 V2.1（因為那時才有 Task 可以選）。V2.0 只要 Session 建立表單多一個 optional 的 Project 下拉。

### PJ-06 — 前端：導覽重整與 Project 畫面

見 `08` 的完整規格。本階段交付：

- 導覽從 5 個平項改為分組：`Projects` / `Sessions` / `Infrastructure`（Dashboard、Nodes、Enrollment、Audit、Integrations 收進 Infrastructure）。**既有路由路徑一律不變**，只改導覽的組織方式。
- `/projects` 列表、`/projects/:id` 總覽（描述、綁定的 workspace 清單含 node 狀態、進行中的 session、近期活動）。
- Session 建立表單的 optional Project 欄位。
- 旗標關閉時，導覽退回 V1 的 5 個平項，`/projects*` 404。

**注意**：`plan/09` 把 sidebar 從 280px 收到 208px 時，明確算過「最長項需 ≈144px，208px 留 64px 餘裕：中文化標籤或多一個項目都不會擠」。V2 要加的是**兩個項目加一層分組標題**，所以 208px 必須重新驗算，不能假設還夠（`08` §3 有數字）。

### PJ-07 — 驗證與出口

見 `09` §2.1。

## 這一階段明確不做

- 不讀寫使用者 repo 裡的任何檔案（`.cliora/` 投影從 V2.1 才開始）。
- 不新增 protocol 訊息、不動 daemon、不改 contract 版本。
- 不做 Task、看板、Plan、Verification、Evidence。
- 不做 `project_members`：V2.0 用既有三角色 ＋ owner 欄位就夠。專案級成員制在有第二個團隊真的需要時再做，屆時它是一張新表加一層授權，不會回頭改動這裡的任何東西。

## 出口條件

1. 可以建立一個 Project（**驗收素材：`Lei-k/Traqora`**，D30），綁定**兩個不同 Node** 上的 workspace，從 Project 頁面看到兩者的 node 線上狀態。
2. 從 Project 建立的 Session 出現在該 Project 的時間軸上；Ad-hoc Session 不受影響也不出現在任何 Project。
3. 解綁一個 workspace 不影響正在跑的 Session。
4. Node 被刪除時，綁定列一起消失，Project 本身不受影響。
5. `CLIORA_PROJECTS_ENABLED=false` 時，完整 V1 回歸測試（`make check`＋`make integration`＋`make e2e`）全綠，且前端截圖與升級前一致。
6. 綁定一條「曾經合法但 root 已被停用」的路徑後，用它建立 Session 會被拒絕（重驗證，不信任綁定）。

## 風險

| 風險 | 對策 |
|---|---|
| 導覽重整讓既有使用者找不到 Nodes | 路由不變；Infrastructure 群組預設展開；`08` 的 e2e 檢查五個舊路由都還可直達 |
| sidebar 寬度不夠 | PJ-06 先量測再決定（`09` §3），必要時把分組標題做成分隔線而非獨立列 |
| 專案與 workspace 多對多造成「這個 session 屬於哪個專案」歧義 | Session 的 `project_id` 由建立者明確指定，平台**不做推論**；一個 workspace 綁到兩個專案是允許的，但建立 Session 時必須選一個 |
