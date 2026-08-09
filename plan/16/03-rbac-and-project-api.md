# 03 — RBAC 與 Project API（`PJ-03` ＋ `PJ-04`，同一個 PR）

> **這兩張票不能分開合併。** `test_every_action_is_enforced_somewhere` 是對
> `backend/app/**/*.py`（排除 `rbac.py` 與 migrations）的**文字掃描**：
> `PROJECT_VIEW` 一寫進 `rbac.py` 而別處沒出現，測試立刻紅。
> 唯一的迴避方式是把它加進 `UNENFORCED_ACTIONS`，而 `research/02/01` D13 明寫
> 「不要為了先 merge 而往裡面加東西」——那個集合現在是空的，本期結束時也要是空的。
>
> 分開寫成兩節只是為了閱讀，不是為了分開出貨（`00-…md` D7）。

## 1. `PJ-03` — RBAC 詞彙與 seed

### 1.1 `backend/app/services/rbac.py`

```python
PROJECT_VIEW = "project.view"
PROJECT_MANAGE = "project.manage"
```

歸屬（`research/02/01` D13）：

| 動作 | Viewer | Developer | Admin |
|---|:--:|:--:|:--:|
| `project.view` | ✅ | ✅ | ✅ |
| `project.manage` | ❌ | ❌ | ✅ |

- `PROJECT_VIEW` 加進 `_VIEWER_ACTIONS`（三個角色巢狀繼承，所以只加一處）。
- `PROJECT_MANAGE` 加進 `_ADMIN_ACTIONS`。
- **`_DEVELOPER_ACTIONS` 一個字都不改。**

`_ADMIN_ACTIONS` 上要補一段註解，密度照既有的（`integration.manage` 那段是範本）：

> `project.manage` 與 `enrollment.manage`／`node.manage` 同層：建立一個 Project 並把
> workspace 綁上去，決定的是「這個組織有哪些專案、它們涵蓋哪些機器上的哪些目錄」——
> 那是組織層的決定。V2.3 之後綁定的意義會再擴大一次（綁一個 runner 到一個 Project
> 等於授權它取用該專案的機密），所以這個動作從一開始就不該落在 Developer 手上。
> Viewer 只拿 `project.view`，維持既有的唯讀角色定義。

**`UNENFORCED_ACTIONS` 保持 `frozenset()`。**

### 1.2 Seed migration `0022_seed_project_actions.py`

`down_revision = "0021_projects"`。照 `.agent/skills/seed-migration` 的規矩與
`0019_seed_file_upload_action.py` 的形狀：

- **冪等**：以角色名稱為自然鍵，讀出 `permissions->'actions'`、union 新動作、寫回。
  重跑不產生第二份。
- **可下行**：`downgrade()` 從三個角色的 actions 陣列移除這兩個鍵。
- **不混入其他東西**：這支 migration 只碰 `roles.permissions`。

### 1.3 三份副本要同步

`ROLE_ACTIONS` 是單一事實來源，另外三處是它的副本，各有一條測試盯著：

| 副本 | 怎麼做 | 盯著它的測試 |
|---|---|---|
| PostgreSQL 的 seed | `0022` | `test_permission_matrix.py`（矩陣 vs 實際 seed） |
| `frontend/src/api/dto.ts` 的 `ACTION_*` | 手加 `ACTION_PROJECT_VIEW`／`ACTION_PROJECT_MANAGE` | `test_authz.py`（讀 dto.ts 的文字） |
| `docs/permission-matrix.md` | **重新產生**，不要手改 | 檔頭寫著 do not edit |

```bash
uv run --project backend python ../scripts/p4/render_permission_matrix.py --write
```

產生出來的表要有兩列新的中英標籤，例如
`查看專案 / View projects` 與 `管理專案 / Manage projects & workspace bindings`。
標籤的來源是 render 腳本裡的對照表，**那份對照表也要一起改**。

## 2. `PJ-04` — Project API

`backend/app/api/http/projects.py`，`APIRouter(prefix="/api/projects", tags=["projects"])`，
在 `app/main.py` **無條件** `include_router`（`00-…md` D1）。

### 2.1 端點（七條）

```text
GET    /api/projects                              project.view
POST   /api/projects                              project.manage
GET    /api/projects/{project_id}                 project.view
PATCH  /api/projects/{project_id}                 project.manage
GET    /api/projects/{project_id}/activity        project.view
POST   /api/projects/{project_id}/workspaces      project.manage
DELETE /api/projects/{project_id}/workspaces/{binding_id}   project.manage
```

**七條而不是八條**：`research/02/02` 列了 `GET /{id}` 與 `GET /{id}/overview` 兩條，
本計畫合併為一條。理由：兩者服務同一個畫面、同一組權限、沒有各自的快取語意，
拆開只是讓 Project 總覽頁多打一次往返。`GET /{id}` 直接回傳綁定清單與三個計數
（`workspace_count`、`active_session_count`、`last_activity_at`）。

`/activity` 保持獨立**是**因為它有獨立的分頁語意，而總覽頁只要最近 10 筆。

### 2.2 `ROUTE_ACTIONS`

`backend/tests/test_authz.py` 的 `ROUTE_ACTIONS` 加七列，**否則
`test_every_mounted_route_is_in_the_matrix` 立刻紅**（雙向斷言）。
每一列旁邊寫一句為什麼，照既有列的習慣：

```python
# Project layer (ADR 0027). `project.view` is held by all three roles for the same
# reason `node.view` is: a Viewer may look at the fleet's shape. `project.manage`
# sits with enrollment/node management — deciding which projects exist, and which
# machines and directories they cover, is an organisation-level call.
("GET", "/api/projects"): rbac.PROJECT_VIEW,
...
```

### 2.3 行為

| 端點 | 要點 |
|---|---|
| `POST /api/projects` | `name`（1–128）、`slug`（可選，缺則由 name 產生）、`description`（可選）。`owner_user_id` **由伺服器指定為呼叫者**，永不從 body 接受（沿用 `session.create` 的既有規則）。slug 撞了回 409 `PROJECT_SLUG_TAKEN` |
| `PATCH /api/projects/{id}` | 可改 `name`、`description`、`status`。**`slug` 不在可改欄位裡**（`02-…md` §2）。狀態轉換：`active ⇄ paused`、`* → archived`、`archived → active`（解封存允許，因為封存不是刪除）。每次成功寫一筆 `project.updated` activity，payload 帶 `from`／`to` |
| `GET /api/projects` | 篩選 `status`、`owned_by_me`。分頁 `limit`（預設 50，上限 200）／`offset`，形狀照 `GET /api/sessions` |
| `GET /api/projects/{id}` | 專案本體 ＋ 綁定清單（每列含 node 名稱、線上狀態、**可用性**，見 §2.4）＋ 三個計數 |
| `GET /api/projects/{id}/activity` | keyset 分頁（`before` = `(occurred_at, id)` 游標），預設 50、上限 200。**actor 依 `audit.view` 遮蔽**（§2.5） |
| `POST /{id}/workspaces` | body `{node_id, path, label?, is_primary?}`。三步：node 存在且未 soft-delete → `sessions.authorize_workspace(node, path)` → 插入。已存在同組回 **200 ＋ 既有列**（冪等，沿用 favorites 的裁決）。`is_primary: true` 時在同一個交易裡把該 Project 其他列設為 false |
| `DELETE /{id}/workspaces/{binding_id}` | 刪一列。**不碰任何 Session**——正在跑的 session 的 `project_id` 不變、狀態不變、terminal 不斷。204 |

**封存的語意**（`00-…md` D9）：

| 動作 | `active` | `paused` | `archived` |
|---|---|---|---|
| 建立 Session 時指定它 | ✅ | ✅ | ❌ 409 `PROJECT_ARCHIVED` |
| 新增綁定 | ✅ | ✅ | ❌ 409 `PROJECT_ARCHIVED` |
| 解綁、改名、看時間軸 | ✅ | ✅ | ✅ |

`paused` 對平台**沒有任何強制效果**，它是給人看的標記。這一點要寫在 DTO 的註解上，
否則會有人以為它擋住了什麼。

### 2.4 綁定列的可用性——三種不可用要分得出來

這是 `research/02/09` §4.2 點名「很重要」的那件事，而且它是**本期唯一需要跨層查詢的邏輯**。

```python
class BindingUsability(str, Enum):
    OK = "ok"
    NODE_OFFLINE = "node_offline"       # node 存在、綁定合法，但沒有 heartbeat
    ROOT_DISABLED = "root_disabled"     # authorize_workspace() 現在會拒絕這條路徑
    NODE_REMOVED = "node_removed"       # 只在硬刪除的空窗期出現；正常不會被看到
```

- `node_offline` 用 `registry.seconds_since_heartbeat` ＋ `compute_status`，
  **與 `services/favorites.py:node_is_online` 同一條路徑**，不另做一套判定。
- `root_disabled` 就是**再跑一次** `authorize_workspace()` 並攔 `ApiError`。
  這是紅線 2 在 UI 上的具體形式：綁定表不是授權，每一次讀取都重新問一次。
- **「路徑已不存在」本期查不出來**，因為那需要問 node（一次 `filesystem.*` 往返），
  而本期不動 protocol、不做檔案存取。這是一個**要誠實寫下來的缺口**：
  `research/02/02` 的出口條件把「路徑已不存在」列為三種狀態之一，本期只做得到兩種。
  處置見 `06-…md` §5 的出口條件 1 改寫，以及 `08-…md` 的 M-PJ-04。

### 2.5 Activity 的 actor 遮蔽（`00-…md` D5）

```python
def redact_activity(items: list[ActivityItem], *, can_view_audit: bool) -> list[ActivityItem]:
    """Without `audit.view`, an activity row keeps the action and the instant but
    loses who did it — the same rule `services/dashboard.project_for` applies to the
    Dashboard's recent activity (FR-AUTH-002). `project.view` is held by all three
    roles, so without this the project timeline would re-open the channel P4 closed.
    """
```

回應帶 `actors_hidden: true`，**與 Dashboard 的欄位同名**——UI 才能用同一個元件說同一句話。

一條**必要**的測試：Viewer 讀某個 Project 的時間軸，回應裡每一列的
`actor_id` 與 `actor_name` 都是 `null`，而 Admin 讀同一組資料拿得到值。

### 2.6 錯誤碼

加進 `backend/app/api/error_catalog.py`（`CENTRAL` 來源），
之後 `python scripts/p4/render_error_catalog.py` 重新產生 `docs/error-catalog.md`。

| 碼 | HTTP | 安全訊息 | 指引 |
|---|---|---|---|
| `PROJECT_NOT_FOUND` | 404 | Project not found | 它可能已被移除，或你打錯了識別碼 |
| `PROJECT_SLUG_TAKEN` | 409 | A project with this slug already exists | slug 建立後不可更改，請換一個 |
| `PROJECT_ARCHIVED` | 409 | This project is archived | 封存的專案不能新增綁定或開新的 Session；先解除封存 |
| `PROJECT_WORKSPACE_NOT_FOUND` | 404 | Workspace binding not found | 它可能已被解綁 |
| `SESSION_PROJECT_MISMATCH` | 400 | The workspace does not belong to this project | 從該專案的綁定清單裡選一個，或不要指定專案 |

**重用而不新增的**：`WORKSPACE_OUTSIDE_ALLOWED_ROOT`（綁定與使用時的路徑拒絕）。
新增一個同義的碼會讓「為什麼這條路徑不行」在兩個地方有兩個答案。

**旗標關閉時不回錯誤碼**，回 FastAPI 的裸 404——因為那條路徑在該部署裡**不存在**，
而一個帶著 `PROJECTS_DISABLED` 的 404 反而洩漏了「這個功能存在只是關著」。

### 2.7 稽核

五個新動作加進 `app/services/audit.py`（常數 ＋ `ALL_ACTIONS`），
以及 `frontend/src/api/dto.ts` 的 `AUDIT_ACTIONS` 陣列與
`frontend/src/utils/auditActions.ts` 的中文標籤。
`test_audit_actions_match_the_frontend_constants` 雙向斷言，兩邊少一個都會紅。

| 動作 | 中文標籤 | metadata |
|---|---|---|
| `project.create` | 建立專案 | `{project_id, slug}` |
| `project.update` | 更新專案 | `{project_id, changed: [...]}`；狀態變更額外帶 `from`／`to` |
| `project.workspace_bind` | 綁定 Workspace | `{project_id, node_id, path}` |
| `project.workspace_unbind` | 解綁 Workspace | `{project_id, node_id, path}` |
| `project.archive` | 封存專案 | `{project_id}` |

> `project.archive` 與 `project.update` **分開**，即使封存是透過 `PATCH status` 做的。
> 理由與 `node.disable`／`node.enable` 從 `node.*` 裡分出來一樣：稽核查詢上
> 「誰封存了那個專案」是一個會被單獨問的問題，而 union 兩個鍵再過濾 metadata 不是答案。

**每一個寫入動作一筆 audit ＋ 一筆 activity**（`00-…md` D6）。兩者不是二選一：
audit 回答「誰做了什麼」，activity 回答「這個專案上發生了什麼」。

### 2.8 服務層與資源授權

`backend/app/services/projects.py`。分層照 ADR 0016：

- **動作層**在路由（`Depends(require_action(...))`）。
- **資源層**在服務——本期只有兩條規則，都很短：
  1. Project 對 `project.view` 的持有者一律可見（與 Node 一致，`00-…md` D8）。
  2. 綁定的每一次使用都重跑 `authorize_workspace()`（`00-…md` D3）。

**不新增 `app/services/authz.py` 的函式。** 本期沒有 owner-based 的規則需要它。
V2.1 有 Task 的時候再說。

`backend/app/repositories/projects.py` 放查詢，形狀照 `repositories/sessions.py`。

## 3. 驗收

| 檢查 | 方法 |
|---|---|
| 三份 RBAC 副本一致 | `backend/tests/db/test_permission_matrix.py` 三條全綠 |
| 動作有強制點 | `test_every_action_is_enforced_somewhere`，`UNENFORCED_ACTIONS` 仍為空 |
| 路由都在矩陣裡 | `test_every_mounted_route_is_in_the_matrix` 雙向 |
| 三角色 × 七條端點 | `test_permission_matrix.py` 的 HTTP 矩陣加七組；**Viewer 的每一次寫入嘗試都要斷言「什麼都沒留下」**（沿用 `RecordingRegistry` 的既有手法：沒有列被改、沒有 frame 被中繼） |
| 綁定重驗證 | 綁一條合法路徑 → 停用該 root → `GET /{id}` 那一列是 `root_disabled` → 用它建 Session 回 `WORKSPACE_OUTSIDE_ALLOWED_ROOT` |
| 綁定冪等 | 同組 POST 兩次 → 兩次都 200 且是同一個 `id` |
| `is_primary` 唯一 | 綁第二條 `is_primary: true` → 第一條變 false，同一個交易 |
| 解綁不影響 Session | 建 Session → 解綁 → session 的 status／`project_id` 不變，terminal WS 不斷 |
| actor 遮蔽 | Viewer 與 Admin 讀同一組時間軸，前者全 null ＋ `actors_hidden: true` |
| 封存 | `archived` 的 Project：新增綁定 409、建 Session 409、解綁與改名 200 |
| 稽核詞彙 | `test_every_audit_action_has_a_write_site` ＋ `test_audit_actions_match_the_frontend_constants` |
| 錯誤目錄 | `docs/error-catalog.md` 重新產生後 diff 只有五列新增 |
</content>
