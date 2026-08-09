# 04 — Session Token 與 Agent Principal（`TK-06`）

**本期唯一觸發安全審查的工作包**（`research/02/10` §6：新憑證流）。
它的設計要在 `TK-07` 開工前定稿——投影的內容包含 token 檔，
審查若否決落地方式，contract 就要跟著改（`00-…md` 閘門三）。

## 1. Token 的形狀

```text
值：  cliora_st_<43 個 url-safe base64 字元>     ← secrets.token_urlsafe(32)
儲存：HMAC-SHA256(token_pepper, 值) 的 hex       ← 只存這個，永不存值
```

前綴 `cliora_st_` 有三個用途，都不是裝飾：

1. `get_current_user` 看到這個前綴**直接 401**（§2.1）——不必解析、不必查庫。
2. secret scanner 與 log redaction 有一個可以抓的樣式。
3. 使用者在 `.cliora/context/<id>.token` 裡看到它時知道那是什麼。

**沿用 `token_pepper`（ADR 0008）而不是新的金鑰**：enrollment token 與 node secret
已經用它，而三者的輪替時機相同（都是「這個部署的憑證要全部換掉」）。
這與 V2.3 的 `CLIORA_SECRET_MASTER_KEY` 要獨立是**相反**的判斷，理由也相反——
那個的輪替時機與這些不同（`research/02/01` D22）。

### 1.1 Scope

發行時快照進 `session_tokens.scopes`，內容是**寫死的常數**：

```python
SESSION_TOKEN_SCOPES = frozenset({PROJECT_VIEW, TASK_UPDATE})
```

**只有兩個。** 不含 `task.create`（Agent 不建卡，V2.5 的拆解是提案不是建立）、
不含 `task.approve`（D13）、不含 `file.*`、`terminal.*`、`session.*`、`project.manage`。

有一條測試斷言這個集合與四個「永遠不含」的動作的交集為空，
**而且它是對 `ROLE_ACTIONS` 的 Admin 集合取差集寫的**——
這樣新增一個危險動作而忘了排除時，測試會紅。

## 2. Agent Principal 是第二條認證路徑（D3）

### 2.1 兩條路徑不相交

```text
Authorization: Bearer <JWT>            → get_current_user      → User
Authorization: Bearer cliora_st_…      → get_agent_principal   → AgentPrincipal
```

- `get_current_user` 對 `cliora_st_` 前綴 **401 `UNAUTHENTICATED`**，
  訊息與其他 401 相同（不告訴呼叫端「你的 token 型別錯了」——那是一個可以拿來探測的差異）。
- `get_agent_principal` 對非 `cliora_st_` 前綴同樣 401。
- **沒有任何端點同時掛兩個依賴。** 需要兩者都能用的四條端點掛
  `require_actor_action(action)`，它內部依序嘗試兩種解析並回傳一個
  `Actor = User | AgentPrincipal` 的聯集型別。

```python
@dataclass(frozen=True, slots=True)
class AgentPrincipal:
    token_id: uuid.UUID
    session_id: uuid.UUID
    project_id: uuid.UUID
    scopes: frozenset[str]
```

**它沒有 `user_id`。** 這是刻意的：一個帶著 `user_id` 的 Agent principal
遲早會被某個 `actor_id=principal.user_id` 的呼叫拿去冒充人類（D4）。
需要知道是誰開的 Session 時去查 `session_tokens.issued_by`——多一次查詢，
換一個不可能被誤用的型別。

### 2.2 `require_actor_action` 的三件事

1. 動作在 `principal.scopes` 裡（Agent）或在 `role_actions(user)` 裡（人）。
2. 拒絕時 `denial_var.set((action, "action"))` 與 metrics 沿用既有形狀，
   **`role` 標籤對 Agent 填 `session_agent`**——那個 metric 的標籤基數因此加一，
   而不是變成無界（token id 絕不進標籤）。
3. `actor_var` 對 Agent **不設**（它是 user id 的通道）；
   改用新的 `agent_var` 讓 middleware 能在 audit 裡記 `token_id`。

### 2.3 Agent 能碰的四條端點

| 端點 | 為什麼 |
|---|---|
| `GET /api/projects/{id}/tasks?ref=…` | `cliora task list`／`get` 的第一次往返 |
| `GET /api/tasks/{id}` | 詳情 |
| `PATCH /api/tasks/{id}` | `cliora task update`——**唯一的寫入** |
| `GET /api/projects/{id}/process` | 情境包指路用的流程說明（唯讀） |

再加一層資源檢查：**`principal.project_id` 必須等於目標卡片的 `project_id`**，
不符回 404（不是 403——一個 Agent 不該能用錯誤碼確認別的專案有這張卡）。

`PATCH` 對 Agent 另有兩條收斂：

- **不得改 `gates`**（欄位層拒絕，422 `FORBIDDEN_FIELD`）。scope 已經擋住了整條 gate 端點，
  這是第二道，因為 `PATCH` 的 body 是開放形狀的。
- **不得改 `owner_user_id`、`assigned_runner_id`、`required_secrets`**——
  同一條理由，它們是人的決定。

## 3. 生命週期

| 事件 | 動作 |
|---|---|
| Session 建立成功 | 發一枚，`expires_at = min(now + TTL, 無)`；TTL 由 `CLIORA_SESSION_TOKEN_TTL_H`（預設 24）決定 |
| 每次使用 | 更新 `last_used_at`（**非同步、盡力而為**，不擋請求；它是給 UI 看「上次使用」的） |
| Session 進入任一終止狀態 | **立即 `revoked_at = now`** |
| 使用者手動撤銷 | Session 詳情頁的按鈕，`session.terminate` 持有者可用 |
| `expires_at` 到期 | 驗證時視為無效（不必等清理） |
| 撤銷後 90 天 | `app/retention.py` 的迴圈刪列 |

**「Session 結束即失效」的四道門與 `_record_ended` 完全相同**
（`services/sessions.py:551` 的 docstring 已經列過：`POST /terminate`、`DELETE`、
daemon 推的狀態變更、shell reaper）。所以撤銷寫在**同一個地方**——
狀態機裡，不是四條路由裡。這一條有測試，四道門各一條。

**檔案還在不等於 token 還有效**（`research/02/03` TK-05 規則 4）：
`.cliora/context/<id>.token` 在保留期內都在，但 Session 一結束它就是一個無效的字串。
情境包裡要寫明這一點，否則 Agent 會以為讀得到檔案就代表連得上。

## 4. Token 值永遠不出現在哪裡

五個地方，各一條測試：

| 地方 | 保證 |
|---|---|
| API 回應 | 只有**發行的那一次**回傳值，而那一次的接收者是 Central 自己（投影用），**沒有任何 HTTP 端點回傳它** |
| audit metadata | 只記 `token_id`；`FORBIDDEN_METADATA_KEYS` 另加樣式檢查 |
| activity payload | 同上 |
| 結構化日誌 | `app/logging.py:redact_mapping` 加上 `cliora_st_` 的樣式替換 |
| OpenAPI schema | 沒有任何 response model 含 token 欄位——**對 schema 的斷言測試**，不只是「我們沒寫那個端點」（沿用 `research/02/08` §2 對 secrets 的同一條要求） |

## 5. 旗標關閉時

`CLIORA_PROJECTS_ENABLED=false`：**不發 token、不建列、不投影**。
`get_agent_principal` 在旗標關閉時對任何 `cliora_st_` 一律 401——
不是 404，因為那是一條認證路徑不是一個資源。

## 6. 安全審查大綱（`docs/security-review-v21.md`）

沿用 `docs/security-review-p*.md` 的既有格式。三節，**各自獨立的邊界測試**：

### 第一節：憑證發行與失效

- 發行只在 Session 建立成功後、只發一枚、值只存在於那一次投影往返中。
- 儲存只有 HMAC；`token_pepper` 缺失時的行為（沿用既有的啟動驗證）。
- 四道門的撤銷；到期判定用 aware 時間比較。
- **威脅**：一枚被複製出去的 token 能做什麼？答案要具體——
  它能改那個 Project 的卡片 stage 與欄位，直到 Session 結束。
  不能勾 gate、不能讀檔、不能開 Session、不能碰別的專案。

### 第二節：認證路徑的邊界

- 兩條路徑不相交的斷言（把一個合法 JWT 送進 `get_agent_principal` 要 401，反之亦然）。
- scope 集合與四個禁止動作的交集為空。
- `PATCH` 的欄位層拒絕（gates／owner／runner／secrets）。
- 跨 Project 的 404 而非 403。
- **威脅**：一次重構把 `AgentPrincipal` 換成 `User` 會發生什麼？
  答案是「所有動作都拿得到」，而防線是型別本身沒有 `user_id`，以及那條交集測試。

### 第三節：`.cliora/` 寫入面

- 新 verb 的可寫集合（三個子樹）與既有 verb 的可寫集合互斥。
- token 檔 0600、加入 daemon 的敏感檔分類（讀取面拒絕預覽與搜尋命中）。
- 保留期清理的路徑白名單不含 `uploads/`。
- **威脅**：一個能寫 `.cliora/context/` 的攻擊者能做什麼？
  答案是「能餵給 Agent 一份假的情境包」——這是真的風險，而收斂點是
  只有 daemon 自己（以 node 憑證通過的 Central 請求）能寫，
  而工作目錄的其他寫入者本來就是使用者自己。

**審查結論要有一句「已知限制」**：情境包與 token 檔落在使用者的工作目錄裡，
所以任何能讀該目錄的本機使用者都讀得到 token。這不是可以修的——
Agent 要讀它就必須讀得到。收斂靠的是短 TTL、Session 結束即失效與極窄的 scope。

## 7. 測試

| 層 | 覆蓋 |
|---|---|
| 單元 | HMAC 一致性；前綴判定；scope 交集；`AgentPrincipal` 沒有 `user_id`（型別測試） |
| API | 四條端點各以 Agent token 成功一次；其餘每一條端點以 Agent token 各 401 一次（**清單由路由表產生，新增端點自動納入**） |
| API | gate 端點以 Agent token → 401；以無 `task.approve` 的 Viewer → 403 |
| DB | 四道門各撤銷一次；到期後拒絕；跨 Project 404 |
| 安全 | 五個「不出現」各一條，含 OpenAPI schema 斷言 |
