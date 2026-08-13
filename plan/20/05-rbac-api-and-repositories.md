# 05 — RBAC、Secrets API 與 Repository 的憑證半邊

本檔是 `SC-04` 的 API 半邊（service 與資料層在 [`02-…md`](./02-secret-store-and-data-layer.md)），
加上 `project_repositories` 從「身分」變成「身分 ＋ 憑證」的那一段。

## 1. RBAC：一個新動作

| 動作 | Viewer | Developer | Admin | 強制點 |
|---|---|---|---|---|
| `secret.manage` | ❌ | ❌ | ✅ | Secrets 的四條端點、`PATCH /api/projects/{id}` 的 `allowed_secret_names`、Repository 的建立與修改 |

**既有 24 個動作的角色歸屬一行都不動**（`00-…md` 不得弄壞第 8 條）。合計 25。

三處要同步（`test_permission_matrix.py` 的三條會雙向失敗）：
`rbac.py` 的常數與 `_ADMIN_ACTIONS`、`frontend/src/api/dto.ts` 的 `ACTION_*`、
`docs/permission-matrix.md`。

### 1.1 為什麼 Repository 從 `project.manage` 升到 `secret.manage`

V2.2 的 Repository 是「這個專案的程式碼在哪」；本期之後它是
**「用哪一枚機密去拿那份程式碼」**。後者是憑證的處置。

⚠️ **兩個動作都是 Admin 專屬，所以實際上沒有任何角色失去能力。**
但這仍然是一個權限收緊，`SC-09` 的 release note 要寫它——
一個未宣告的收緊在別人的自動化上會長成一個看不懂的 403。

### 1.2 run 憑證的 scope

`run_tokens` 對應的 `AgentPrincipal` 永遠拿不到 `secret.manage`——
**而且不是靠一行 if**：它根本不走使用者的認證路徑
（`plan/18/05-…md` 建立的兩條分離的 dependency）。
本期只需要一條測試把它釘住：run 憑證對 `GET /api/projects/{id}/secrets` → 401／403。

**這條測試的價值在未來**：`secret.manage` 是第一個「Agent 絕對不能有」的新動作，
而 `run_tokens` 的 scope 是一張會成長的表。

## 2. Secrets API

`backend/app/api/http/secrets.py`（新檔）。五條端點的表在 `02-…md` §4.2；
這裡只寫**形狀上的四個決定**。

### 2.1 端點無條件掛載，靠 dependency 回 404

`SC-00` 的基線裡 `openapi-flags-off.json` 與 `openapi-flags-on.json`
**逐位元組相同**，而那是要守的性質（`plan/18/09` §3 第 2 條）。
本期新端點必須沿用同一個形狀：router 無條件掛載，
`require_projects_enabled` → `require_agent_runs_enabled` 兩層 dependency 依序拒絕。

順序反了會從 404（正確）變成 403（洩漏這條路由存在）——`plan/18/00` D12。

### 2.2 DTO 裡沒有值的欄位，而且用 `load_only` 讓它取不到

```python
class ProjectSecretDTO(BaseModel):
    id: UUID
    name: str
    kind: Literal["env", "git_pat", "git_ssh_key", "provider_token"]
    created_by: UUID | None
    created_at: datetime
    rotated_at: datetime | None
    last_used_at: datetime | None
```

**沒有 `value`、沒有 `fingerprint`、沒有 `size`。**
`size` 看起來無害，但它是一個側通道：一枚 93 字元的值幾乎一定是 fine-grained PAT。

service 端的查詢用 `load_only(...)` 明確列出七個欄位——
理由不是效能，是讓一個未來的 `dict(row.__dict__)` 這種寫法**取不到值**（`02-…md` §4.1）。

### 2.3 建立時的名稱檢查（`04-…md` §4.2）

422 並指名，四類：

| 類別 | 例子 | 訊息 |
|---|---|---|
| 格式 | `foo-bar`、`1TOKEN` | 必須是大寫字母、數字與底線，且以字母開頭 |
| **危險名稱** | `PATH`、`HOME`、`LD_PRELOAD`、`LD_LIBRARY_PATH` | 這個名稱會覆寫執行環境的基本設定 |
| **前綴保留** | `GIT_*`、`SSH_*`、`CLIORA_*` | 這些前綴由平台使用 |
| 重複 | 同專案已有同名且未刪除 | 409，建議改用輪替 |

**`GIT_*` 保留是必要的**：一枚叫 `GIT_ASKPASS` 的 `env` 機密會直接接管 D7 的整個機制。

### 2.4 `allowed_secret_names` 的編輯

走既有的 `PATCH /api/projects/{id}`，**但這個欄位需要 `secret.manage`**，
其餘欄位仍是 `project.manage`。

⚠️ **這是本 repo 第一個「同一條端點上不同欄位需要不同動作」的地方。**
兩個選項：

| | A：一條端點、欄位級檢查（**選這個**） | B：獨立端點 `PUT …/allowed-secret-names` |
|---|---|---|
| 實作 | `if "allowed_secret_names" in changes: require(secret.manage)` | 多一條路由 |
| 樂觀鎖 | 沿用既有的 `version` | 要自己處理，或跳過（而跳過就是一個競態） |
| 前端 | 一個表單 | 兩個表單，而它們在同一張設定頁上 |

選 A，並在 `services/projects.py` 的那一段寫下為什麼——
**因為 B 看起來比較乾淨，而它的代價（第二個樂觀鎖路徑）不明顯**。

從 allowlist 移除一個仍被卡片宣告的名稱 → **不擋，但回應帶一個 warning**
列出受影響的卡片。理由：那些卡片會在 dispatch 時被 409 指名（`03-…md` §4.1），
而擋住編輯會讓「清掉一個不再用的名稱」變成一件要先改十張卡的事。

## 3. Repository 的憑證半邊

### 3.1 現況

`frontend/src/components/project/ProjectRepositories.vue` 與
`backend/app/services/runners.py` 的 `RepositoryService`：
三個欄位（scheme／host／path）＋ default_branch ＋ label。
`clone_url()` 從三欄組出 URL——**憑證在 URL 裡不可表示**，這條不動。

### 3.2 本期加的

`POST`／`PATCH` 的 body 加三個欄位，並在 service 端做**五條驗證**：

0. 🆕 **`CLIORA_GIT_SECRET_DELIVERY_ENABLED=false`（預設）→ `auth_kind` 只能是 `ambient`**，
   其餘兩個回 422 `GIT_SECRET_DELIVERY_DISABLED` 並**指名那個環境變數**
   （與機密建立同一個錯誤碼，`02-…md` §4.2）。**這一條排在最前面**：
   在一個沒有啟用 git 憑證下放的部署上，第 2–4 條問的問題根本不該被問到。
1. `auth_kind: ambient` → `credential_secret_id` 必須是 null。
2. `auth_kind: pat` → `credential_secret_id` 必須指向一枚 `kind: git_pat`
   且**屬於同一個 project** 的機密。
3. `auth_kind: ssh` → 必須指向 `kind: git_ssh_key`，
   **且 `scheme` 必須是 `ssh`**（一枚 SSH key 配一個 https 的 URL 是一個
   會在 clone 的第一秒失敗的組合）。
4. **SSH ＋ 未指定 `provider_token_secret_id`** → 儲存時就提示
   「SSH 無法開 PR，若要用 `delivery: pull_request` 需另外指定一枚 provider_token」。
   ⚠️ **本期是提示還是擋下？**
   `research/02/05` SC-06 寫「並在未指定時擋下儲存」。
   **本計畫改為：提示，不擋。** 理由是 `delivery: pull_request` 在本期
   本來就會在 dispatch 被 409（V2.4），所以擋住儲存會讓一個
   **今天完全合法**的組態（SSH ＋ 只推分支）無法設定。
   **V2.4 開放 `pull_request` 時把它改成擋下**，而那時擋的是一個真的會失敗的組合。
   出口條件 6d 因此改寫成「**設定畫面就說得出這個後果**」而不是「擋下儲存」。

### 3.3 host allowlist 的兩層不變

Central 的 `git_allowed_hosts`（設定）是粗篩，node 的
`runner.git.allowed_hosts` 是最終權威。**本期一行都不動**——
它已經是對的，而 push 走同一個 `CheckURL`（`04b-…md` §2）。

## 4. 既有端點的兩處改動

### 4.1 `GET /api/agents`（`agents.py:210`）

`AgentRunnerDTO` 加三個欄位：`run_untagged`、`accept_secrets`、
以及 `labels_compared: true`（一個常數，讓前端不必知道階段）。

⚠️ **`labels` 與 `run_untagged` 一律唯讀**（`00-…md` 不得弄壞第 12 條）。
`PATCH /api/agents/{id}` 的 `EDITABLE_RUNNER_FIELDS` **不加它們**，
而 `agents.py:250` 那段「刻意沒有綁定端點」的 docstring 要順手改對（`01-…md` §5b）。

### 4.2 `GET /api/tasks/{id}` 與看板

`TaskDTO` 已經有 `required_labels` 與 `required_secrets`（V2.1 建，宣告但沒有讀者）。
本期它們有讀者了，所以**回應不變、語意變**。

`BoardCardDTO`（V2.2_1 的 `UI-06` 加了三個 run 欄位）**本期不加欄位**：
看板一次渲染幾十張卡，而 tag 不影響卡片的視覺狀態——
它影響的是**空等的原因**，而那已經在 `run_status`／`waiting_reason` 裡。

⚠️ 但 `waiting_reason` 現在要能帶 `missing_tags`（`03-…md` §3）。
它今天是一個字串欄位，本期變成一個小物件——**這是一個 DTO 的破壞性變更**，
由 OpenAPI 快照比對治理（`UI-06` 建立的 D33 慣例：看板欄位走快照，不動 contract）。
前端與後端同一個 PR。

## 5. 測試

`backend/tests/db/test_secret_api.py`：

1. 三個角色 × 五條端點 = 15 條，只有 Admin 通過（`secret.manage`）。
2. run 憑證對 secrets 端點 → 拒絕（§1.2）。
3. 旗標關閉 → 五條全部 404，**不是 403**。
4. 名稱的四類拒絕各一條（§2.3）。
5. `PATCH /api/projects/{id}` 只改 `name` → `project.manage` 就夠；
   同時改 `allowed_secret_names` → 需要 `secret.manage`（§2.4 的 A 方案）。
6. 從 allowlist 移除一個被卡片宣告的名稱 → 成功，回應帶 warning 列出卡片。
7. Repository 的五條驗證各一條（§3.2）；第 0 條斷言旗標關閉時
   `auth_kind: pat` 回 422 且訊息含變數名，第 4 條斷言是**提示而不是 409**。
8. `PATCH /api/agents/{id}` 帶 `labels` 或 `run_untagged` → 400 `UNKNOWN_FIELD`
   （沿用 `EDITABLE_RUNNER_FIELDS` 既有的 unknown 檢查）。
9. **OpenAPI 掃描**：整份 spec 的所有 response schema 都沒有名為
   `value`／`value_encrypted`／`dek_wrapped`／`plaintext`／`secret_value` 的屬性
   （`GATE-SC-NO-SECRET-IN-RESPONSE`）。
10. **五條端點的原始回應 bytes 不含 sentinel 值**（`02-…md` §5 的第二條）。
