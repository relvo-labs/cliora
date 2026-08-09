# 04 — Session 關聯與功能旗標（`PJ-05`）

這張票有兩件事：讓 Session 可以**選擇性地**屬於一個 Project，
以及把旗標做成一個真的關得掉、而且關掉之後看不出來 V2 存在過的東西。

## 1. Session 的 optional `project_id`

### 1.1 `POST /api/sessions`

`CreateSessionRequest` 加一個欄位：

```python
class CreateSessionRequest(BaseModel):
    node_id: uuid.UUID
    runtime: Literal["claude", "codex", "fake"]
    name: str = Field(min_length=1, max_length=128)
    workspace: str = Field(min_length=1, max_length=4096)
    rows: int = Field(default=24, ge=2, le=300)
    columns: int = Field(default=80, ge=2, le=500)
    # Optional, and permanently so: an Ad-hoc session is part of the product
    # (ADR 0027 / D12). The platform never infers this from the workspace —
    # one path may be bound to several projects, so there is no unique answer,
    # and "is this ad-hoc" must stay the caller's statement rather than ours.
    project_id: uuid.UUID | None = None
```

**這是本期唯一一個對既有請求形狀的改動**，而且它是 optional 的——
舊的客戶端送出的 body 一個位元組都不用改。

`SessionService.create()` 在**既有的 workspace 授權之後**多一步：

```text
1. node 存在、未 soft-delete、runtime 可用          （既有）
2. authorize_workspace(node, workspace)             （既有，紅線 2）
3. 若 project_id 不為 None：
   a. 旗標關閉 → 400 VALIDATION_ERROR（欄位在該部署裡不存在，§2.3）
   b. Project 不存在 → 404 PROJECT_NOT_FOUND
   c. Project 是 archived → 409 PROJECT_ARCHIVED
   d. (project_id, node_id, workspace) 不是一條綁定 → 400 SESSION_PROJECT_MISMATCH
4. 建立 session（既有）
5. 寫 activity_events: session.started（新，僅當 project_id 不為 None）
```

第 3d 步的比對是**精確相等**，不是前綴：綁定的是 `/srv/traqora`，
那 `/srv/traqora/backend` 就不是它。要在子目錄開 session 就把子目錄也綁上去。

> **為什麼不做前綴比對？** 前綴會讓「這個 session 屬於哪個綁定」在巢狀綁定下有多個答案，
> 而 `activity_events` 的那一列要指得出來。而且前綴比對正是
> `authorize_workspace()` 已經在做的事——在同一條路徑上做第二次前綴比對，
> 語意會與第一次糾纏（`/a/projects` vs `/a/projects-other` 的那個陷阱）。

### 1.2 `GET /api/sessions`

加一個 `project_id` 篩選參數。三個值域：

| 值 | 意思 |
|---|---|
| 未給 | 全部（含 Ad-hoc），**與升級前完全相同** |
| UUID | 該 Project 的 session |
| `none` | **只有** Ad-hoc（`project_id IS NULL`） |

第三個值是給「有多少 session 其實是 Ad-hoc」這個問題用的（M7，`08-…md`）。
它是一個查詢參數而不是一個新端點。

### 1.3 Session 結束時的 activity

`session.ended` 寫在既有的終止路徑（正常終止、失敗、daemon 回報 exited）。
**只有 `project_id` 不為 null 的 session 才寫。**

要小心的一點：session 的結束有好幾個入口（`POST /terminate`、`DELETE`、
daemon 主動回報、`shell_reaper`）。寫入點要放在**狀態機的轉換函式裡**，
不是四個路由裡各抄一次——否則第五個入口出現時會漏。

### 1.4 SessionSummary／SessionDetail

回應加 `project_id: uuid.UUID | None` 與 `project_name: str | None`。
**只加欄位，不改既有欄位**（D12：舊 API 回應不新增必填欄位）。

旗標關閉時這兩個欄位固定是 `null`——不是消失。理由與 §2.3 同：
一個欄位的存在與否不該取決於部署設定，那會讓前端的型別在兩種部署下不同。

## 2. 功能旗標

### 2.1 設定

`backend/app/settings.py`：

```python
# --- V2 project layer (ADR 0027) ---
# Two independent flags, deliberately. The board and autonomous execution differ
# by an order of magnitude in risk, and an organisation may reasonably want the
# first without the second. Both off is byte-for-byte V1 behaviour.
projects_enabled: bool = False
```

`agent_runs_enabled` **本期不加**。它在 V2.2 才有東西可以關，而一個現在加進去、
關掉什麼都沒有的旗標，會在半年內變成沒有人敢動的裝飾品。
`research/02/08` §8 把它列在同一張表裡是規劃層的完整性，不是本期的範圍。

### 2.2 三個強制點

旗標必須在三個地方擋，少一個就會露出來：

| # | 位置 | 做法 |
|---|---|---|
| 1 | **HTTP 路由** | `Depends(require_projects_enabled)`：關閉時 `raise HTTPException(404)`（裸 404，不帶錯誤碼，§`03-…md` §2.6）。掛在 `projects.py` 的 router 上，一次涵蓋七條 |
| 2 | **Session 建立** | `project_id` 不為 None 且旗標關閉 → 400 `VALIDATION_ERROR`。**不是 404**：這裡拒絕的是 body 裡一個在該部署中無意義的欄位 |
| 3 | **`UserResponse.features`** | 關閉時是空陣列，前端據此完全不渲染 `Projects` 群組（§3） |

**不掛在 `include_router` 上**（`00-…md` D1）。

`require_projects_enabled` 放在 `app/api/http/deps.py`，形狀照既有的 `require_action`：

```python
def require_projects_enabled(settings: Settings = Depends(get_settings)) -> None:
    """404 rather than 403 when the project layer is off.

    A 403 would say "this exists, you may not have it"; the layer genuinely does not
    exist in this deployment, and a deployment that has never enabled it should not
    advertise a roadmap. Mounted unconditionally so `test_every_mounted_route_is_in_
    the_matrix` reads the same route set regardless of environment (ADR 0027).
    """
    if not settings.projects_enabled:
        raise HTTPException(status_code=404)
```

### 2.3 一條容易漏的：旗標關閉時 `project_id` 欄位還在 OpenAPI 裡

`CreateSessionRequest.project_id` 是 pydantic 模型的一部分，**schema 在兩種部署下都一樣**。
這是對的——強制點在執行期（§2.2 第 2 點），不在 schema。

但它讓 `06-…md` §3 的「API 表面 diff」規則需要一句精確化：

> 允許的 diff：**新增路徑**（旗標關閉時全部 404）、**既有回應的可選新增欄位**、
> **既有請求的可選新增欄位**。
> 不允許的 diff：既有欄位的移除、改名、型別變更、必填性變更；既有路徑的移除；
> 任何回應的必填欄位新增。

這條規則配一條腳本化的斷言（`scripts/pj/openapi_diff.py`），比對 `PJ-00` 的 B1 基線。
**不是人眼看 diff**——`openapi.json` 有幾千行。

## 3. 前端怎麼知道旗標（`00-…md` D2）

### 3.1 `UserResponse.features`

```python
class UserResponse(BaseModel):
    id: uuid.UUID
    username: str
    display_name: str
    role: str
    permissions: list[str]
    # What this *deployment* has, as opposed to what this *person* may do. The two
    # compose with AND in the UI, and the server checks both independently — a
    # feature flag is not a permission and must never be read as one.
    features: list[str] = []
```

`from_user()` 需要 `Settings`，所以簽章改成 `from_user(user, *, settings)`。
呼叫點只有兩處（`/api/auth/login`、`/api/auth/me`），都在 `auth.py`。

值：旗標開時 `["projects"]`，關時 `[]`。V2.2 會多一個 `"agent_runs"`——
那時是**一個字串**，不是一次改版。

### 3.2 為什麼不是別的三種做法

| 方案 | 為什麼否決 |
|---|---|
| `GET /api/features` | 多一條路徑（＋一列 `ROUTE_ACTIONS`、＋一次啟動往返），而導覽必須在它回來之前先渲染一次——就會閃一下。而且它會違反「新增路徑一律 404」那條規則，需要一個具名例外 |
| `VITE_PROJECTS_ENABLED` 建置期變數 | 兩個真實來源。改一次旗標要重新 build 前端，而後端 restart 就生效——兩者之間的窗口裡，UI 說的和伺服器做的不一樣 |
| 由 `/api/projects` 的 404 反推 | 導覽的第一次渲染早於任何 API 呼叫。而且「404」與「後端掛了」在客戶端長得一樣 |
| 塞進 `permissions` | seed migration 是無條件跑的：旗標關閉的部署裡 Admin 一樣持有 `project.manage`。`permissions` 在結構上就承載不了這件事 |

### 3.3 前端側

`frontend/src/stores/auth.ts` 加一個 getter，與既有的 `hasPermission` 並列：

```ts
hasFeature(feature: string): boolean {
  return this.user?.features.includes(feature) ?? false;
}
```

`frontend/src/api/dto.ts` 加 `export const FEATURE_PROJECTS = "projects";`
與 `UserDTO.features: string[]`。

**型別上的一句註解**（照 `00-…md` §5 風險表的最後一列）：

```ts
/** What this deployment has. Not a permission — `hasPermission` answers that, and
 *  the server checks both. `hasFeature(...) && hasPermission(...)` is the UI rule;
 *  neither alone is. */
features: string[];
```

## 4. 驗收

| 檢查 | 方法 |
|---|---|
| Ad-hoc 不受影響 | 不帶 `project_id` 建 session → 行為與升級前逐欄相同；**沒有** activity 事件產生 |
| 綁定不符 | 帶 `project_id` ＋ 一條沒綁的 workspace → 400 `SESSION_PROJECT_MISMATCH`，**沒有 session 列被建立** |
| 封存 | 帶 archived 的 `project_id` → 409 `PROJECT_ARCHIVED` |
| 精確相等 | 綁 `/srv/traqora`，用 `/srv/traqora/backend` ＋ 同一個 `project_id` → 400（不是靜默接受） |
| 時間軸 | 建 Session ＋ 終止 → 該 Project 時間軸有 `session.started` 與 `session.ended` 各一；同時建的 Ad-hoc session **一筆都沒有** |
| 結束事件不漏 | 四個結束入口（terminate、delete、daemon exited、shell_reaper）各測一次都有 `session.ended` |
| 篩選 | `?project_id=<uuid>`、`?project_id=none`、不給，三種各一條測試 |
| 旗標關閉 | 七條 `/api/projects*` 全 404；帶 `project_id` 的建立請求 400；`/api/auth/me` 的 `features` 是 `[]`；`GET /api/sessions` 的回應與基線逐欄相同（兩個新欄位為 null） |
| 旗標開關不影響路由集合 | 兩種設定下 `mounted_routes()` 回傳相同集合（一條測試，直接斷言 D1） |
| OpenAPI diff | `scripts/pj/openapi_diff.py` 對 B1 基線，只允許 §2.3 列出的三種 |
</content>
