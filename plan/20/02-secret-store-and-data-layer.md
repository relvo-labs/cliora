# 02 — `SC-03`／`SC-04`：Secret store 與資料層

## 0. 現況（`SC-00` 基線）

| 項目 | 值 |
|---|---|
| migration head | **`0032_runner_pressure`**，32 張表 |
| `tasks` | 已有 `required_labels`、`required_secrets`、`source`、`repository_id`、`base_branch`、`delivery`、`target_branch`、`existing_pr_ref`（V2.1 建，`0023`；**宣告了但沒有讀者**） |
| `agent_runners` | 已有 `labels`（`0029`，**只存不比對**）、`runtimes`、`max_concurrent`、`max_waiting`、`dedicated`、`enabled`、V2.2 補的四個壓力欄（`0032`） |
| `project_repositories` | 只有身分欄位：`scheme`／`host`／`path`／`default_branch`／`label`。**三個憑證欄刻意沒建**（`plan/18/00` 表列第 11 條：一個指向不存在的表的 nullable UUID 沒有讀者可以驗證它） |
| `projects` | **沒有** `allowed_secret_names` |
| 加密 | `app/security/secret_box.py`（ADR 0022，tunnel 憑證）：AES-GCM、`CLIORA_SECRET_ENCRYPTION_KEY`、**無信封、無 `key_version`** |

所以本期資料層要補的是**一張新表 ＋ 三處新增欄**，全部是新增，`GATE-SC-SCHEMA-ADDITIVE` 守。

## 1. migration `0033_project_secrets`

一支 migration，四件事。放在一起的理由是它們互為前提：
`project_repositories.credential_secret_id` 是 FK → `project_secrets`，
而 `tasks.required_secrets` 的子集檢查要有 `projects.allowed_secret_names` 才有意義。

### 1.1 `project_secrets`

```text
id                  UUID PK
project_id          UUID NOT NULL FK → projects(id) ON DELETE CASCADE
name                VARCHAR(128) NOT NULL
kind                VARCHAR(16)  NOT NULL   -- env | git_pat | git_ssh_key | provider_token
value_encrypted     BYTEA        NOT NULL   -- AES-GCM(DEK, value)
value_nonce         BYTEA        NOT NULL
dek_wrapped         BYTEA        NOT NULL   -- AES-GCM(master, DEK)
dek_nonce           BYTEA        NOT NULL
key_version         INTEGER      NOT NULL DEFAULT 1
created_by          UUID NULL FK → users(id) ON DELETE SET NULL
created_at          TIMESTAMPTZ  NOT NULL
rotated_at          TIMESTAMPTZ  NULL
last_used_at        TIMESTAMPTZ  NULL
deleted_at          TIMESTAMPTZ  NULL

UNIQUE (project_id, name) WHERE deleted_at IS NULL      -- partial unique index
INDEX  (project_id) WHERE deleted_at IS NULL
```

七個設計說明：

1. **四個 bytea 而不是兩個。** AES-GCM 的 nonce 必須與密文同存且**每次寫入換新**
   （`secret_box.py` 的規則 2）。信封有兩層密文，所以有兩個 nonce。
   把 nonce 前置在密文裡是常見的省欄位作法，**這裡不這樣做**：分欄讓
   「這一列的加密結構長什麼樣」在 `\d` 上就看得到，而這是一張安全審查會逐欄讀的表。
2. **唯一鍵是 partial 的。** `UNIQUE (project_id, name)` 加上 `WHERE deleted_at IS NULL`——
   軟刪除一枚 `GITHUB_TOKEN` 之後必須能重新建立一枚同名的，否則「刪掉重建」這個
   最常見的復原動作會撞唯一鍵，而使用者看到的是一個看不懂的 409。
3. **`kind` 是 `VARCHAR` 加 CHECK，不是 enum type。** 沿用本 repo 既有慣例
   （`task_runs.status`、`project_repositories.scheme` 都是這個形狀）：
   PostgreSQL 的 enum type 要改值就要 `ALTER TYPE`，而 V2.4 會加東西。
4. **`created_by` 是 `SET NULL` 而不是 `CASCADE`。** 一個人離職不該讓專案的機密消失。
5. **沒有 `description`、沒有 `fingerprint`。** 指紋在這裡多餘且有害（`00-…md` D22）：
   它服務的是「我上週輪替的是不是這一枚」，而 `rotated_at` 答同一個問題且不洩漏任何東西。
6. **`last_used_at` 在**認領**時更新，不是在 run 結束時**（D22）。
7. **沒有 `value` 欄位，沒有任何欄位存明文。** `GATE-SC-NO-PLAINTEXT-COLUMN` 對這張表的
   欄位名做斷言（不得出現 `value` 而不帶 `_encrypted`／`plain`／`raw`）——
   一個純粹的命名守衛，成本為零，而它擋的是「先存明文之後再加密」那個沒有回頭路的錯誤
   （`secret_box.py` 的規則 1 已經替這件事寫好了理由）。

### 1.2 `projects.allowed_secret_names` JSONB

```text
ALTER TABLE projects ADD COLUMN allowed_secret_names JSONB NOT NULL DEFAULT '[]'::jsonb;
```

名稱 allowlist。卡片的 `required_secrets` **必須是它的子集**，檢查在
`SC-05` 的 dispatch 與 `SC-04` 的卡片編輯兩處（兩處都要，理由見 §4.3）。

**為什麼是專案上的一格 JSONB 而不是從 `project_secrets` 推導**：
allowlist 與「目前存在哪些機密」是兩個不同的東西。allowlist 是**意圖**
（這個專案的卡片可以要求哪些名稱），而機密可能還沒建、可能被刪了。
從實際存在的機密推導 allowlist 會讓「刪掉一枚機密」悄悄地讓一批卡片變成不可派工——
而那個因果關係在畫面上完全看不出來。

### 1.3 `agent_runners` 的兩格布林

```text
ALTER TABLE agent_runners
  ADD COLUMN run_untagged    BOOLEAN NOT NULL DEFAULT true,
  ADD COLUMN accept_secrets  BOOLEAN NOT NULL DEFAULT true;
```

**兩格布林，不 backfill**（server default 就是 backfill）。D12：register payload
沒帶欄位時視為 `true`，與預設值一致，所以升級前後行為不變。

**兩格的預設值都是 `true`，但它們的「安全方向」相反**，這一點值得停一下：
`run_untagged: true` 是**比較寬鬆**的（什麼卡都領），
`accept_secrets: true` 也是（願意收機密）。
兩者都選寬鬆，理由是同一個：**它們是 node 對自己的宣告，而預設值必須等於
「升級前的行為」**。一台 0.9.0 的 runner 今天什麼卡都領、而機密根本還不存在，
所以升級後的等價行為就是這兩個 `true`。**收緊是營運者的動作，不是升級的副作用**——
這與 `runner.enabled` 預設 `false` 是同一條紀律的兩面（那一格控制的是
「這台機器要不要開始無人值守地跑東西」，那才是不該因為升級而發生的事）。

### 1.4 `project_repositories` 的三個憑證欄

```text
ALTER TABLE project_repositories
  ADD COLUMN auth_kind VARCHAR(16) NOT NULL DEFAULT 'ambient',
  ADD COLUMN credential_secret_id UUID NULL
      REFERENCES project_secrets(id) ON DELETE RESTRICT,
  ADD COLUMN provider_token_secret_id UUID NULL
      REFERENCES project_secrets(id) ON DELETE RESTRICT;
```

三點：

- **`auth_kind` 有三個值不是兩個**（D17）：`ambient`／`pat`／`ssh`。
  `ambient` 是 V2.2 登記過的那些 repository 的**誠實預設**——它們真的在用機器的憑證。
  把它們 backfill 成 `pat` 而 `credential_secret_id` 為 null，是寫下一列不成立的資料。
  🆕 **2026-08-13 之後 `ambient` 不只是 backfill 值，它是預設路徑**：
  `CLIORA_GIT_SECRET_DELIVERY_ENABLED=false` 時 API **只接受這一個值**
  （其餘兩個回 422 並指名那個變數，與機密建立同一個錯誤碼）。
- **`ON DELETE RESTRICT` 而不是 `SET NULL`。** 一枚正在被 repository 使用的機密
  被硬刪除時，應該是一個明確的拒絕（「這枚機密正被 `backend` repository 使用」），
  不是讓那個 repository 悄悄退回 ambient。
  ⚠️ **注意這與軟刪除的關係**：`SC-04` 的刪除是 `deleted_at` 而不是 `DELETE`，
  所以 RESTRICT 平常不會觸發——它守的是「有人直接下 SQL」與未來的硬刪除路徑。
  **軟刪除本身要有自己的檢查**（§4.4）。
- **CHECK 約束**：`auth_kind = 'ambient'` 時 `credential_secret_id` 必須是 null；
  `auth_kind IN ('pat','ssh')` 時必須非 null。一個 `auth_kind: 'pat'` 而沒有憑證的列
  是一個會在 run 的第三分鐘才失敗的東西。

## 2. migration `0034_seed_secret_action`

種一個 RBAC 動作 `secret.manage`，**Admin 專屬**。沿用 `0030_seed_agent_actions.py` 的形狀。

`rbac.py` 的 `_ADMIN_ACTIONS` 加一個常數，`frontend/src/api/dto.ts` 的 `ACTION_*` 同步，
`docs/permission-matrix.md` 同步。**既有 24 個動作的角色歸屬一行都不動**（成功定義第 8 條）。

`secret.manage` 的強制點：`SC-04` 的五條 Secrets 端點 ＋ `SC-05` 的
`PATCH /api/projects/{id}`（改 `allowed_secret_names` 那一部分）
＋ Repository 的建立與修改（因為它現在指向機密）。
`test_every_action_is_enforced_somewhere` 是雙向失敗的，所以這張票裡就要接上。

**為什麼 Repository 從 `project.manage` 升到 `secret.manage`**：
在 V2.2 登記一個 repository 是「這個專案的程式碼在哪」，
本期之後它是「用哪一枚機密去拿那份程式碼」。後者是憑證的處置。
⚠️ 這是一個**權限收緊**，而收緊也會弄壞既有的自動化——但兩個動作都是 Admin 專屬，
所以實際上沒有任何角色失去能力。**這句話要寫進 release note**，否則它看起來像一個未宣告的破壞性變更。

## 3. `app/security/secret_envelope.py`（新檔）

**`secret_box.py` 零 diff**（D3）。新模組的公開介面刻意小：

```python
KEY_BYTES = 32
NONCE_BYTES = 12
MAX_PLAINTEXT_BYTES = 8192          # M-SC-1 決定，見 09-…md
CURRENT_KEY_VERSION = 1
_AAD = b"cliora-project-secret-v1"  # 與 tunnel 憑證的 AAD 不同：兩邊的密文互相不可解

class MasterKeyMissing(RuntimeError): ...
class SecretDecryptionFailed(RuntimeError): ...

@dataclass(frozen=True, slots=True)
class SealedSecret:
    value_encrypted: bytes
    value_nonce: bytes
    dek_wrapped: bytes
    dek_nonce: bytes
    key_version: int

def seal(plaintext: str) -> SealedSecret: ...
def unseal(sealed: SealedSecret) -> str: ...
def rewrap(sealed: SealedSecret, *, to_version: int) -> SealedSecret: ...
def master_key_status() -> tuple[bool, str]: ...   # 給 settings 驗證器與 doctor 用
```

五個性質：

1. **`seal` 每次產生新的 DEK。** 兩枚同值的機密在 DB 裡是兩份完全不同的位元組——
   沒有任何「這兩個專案用了同一個 token」可以從 DB 讀出來。
2. **`rewrap` 只重新包裝 DEK**，`value_encrypted` 與 `value_nonce` **逐位元組不變**。
   這是判準 3 的機器形式，而它同時是 KMS 升級路徑成立的原因：
   換 KMS 只是換掉 `_wrap`／`_unwrap` 這兩個函式。
3. **多版本主金鑰的讀取**：`CLIORA_SECRET_MASTER_KEY` 是當前版本，
   `CLIORA_SECRET_MASTER_KEY_V<N>` 是舊版本（可有多個）。
   `unseal` 依 `sealed.key_version` 選金鑰。**沒有舊金鑰時對舊資料回
   `SecretDecryptionFailed` 並指名缺哪一個版本**——不是回一個看不懂的解密錯誤。
4. **`unseal` 是這個 repo 裡唯一解開專案機密的地方。**
   `GATE-SC-SINGLE-DECRYPT` 用 `ast` 斷言 `backend/app/` 裡呼叫 `unseal` 的模組
   **只有一個**（`services/secrets.py`）——多一個呼叫者就是多一條要審的路徑。
5. **例外的訊息永遠不含值、不含長度。** 沿用 `secret_box.SecretDecryptionFailed`
   的既有理由：三種失敗（金鑰錯、截斷、竄改）給同一個例外，
   因為呼叫端的反應相同，而區分它們只會告訴攻擊者是哪一種。

### 3.1 `Settings` 的驗證器（D4）

```python
@model_validator(mode="after")
def require_master_key_when_agent_runs_enabled(self) -> "Settings":
    if not self.agent_runs_enabled:
        return self
    ok, reason = secret_envelope.master_key_status_for(self.secret_master_key)
    if not ok:
        raise ValueError(f"CLIORA_SECRET_MASTER_KEY {reason}")
    return self
```

`reason` 是四種之一且**逐一指名**：`is not set` / `is not valid base64` /
`must decode to 32 bytes` / `is still the development default`。
形狀照抄 `settings.py:297` 的 `metrics_scrape_token` 驗證器
（條件式、指名、在啟動時而不是在第一次使用時）。

⚠️ **一個 import 方向的細節**：`secret_box.py` 從 `app.settings` 取設定，
所以 `secret_envelope` 不能反過來被 `settings` import 整包。
把純函式 `master_key_status_for(raw: str)` 放在模組頂層、不碰 `get_settings()`，
驗證器只用它。（`secret_envelope._key()` 自己還是走 `get_settings()`，與 `secret_box` 一致。）

## 4. `SC-04` — `services/secrets.py`

### 4.1 這支模組的三條紀律（寫在 docstring 裡）

沿用 `services/runs.py` 的作法——**規則寫在它被違反的地方，不是寫在文件裡**：

1. **沒有任何方法回傳明文，除了 `materialise()`。**
   `materialise(project_id, names)` 是唯一的出口，它的呼叫者只有一個：
   `RunService.poll()`。`GATE-SC-SINGLE-DECRYPT` 守這一條。
2. **`materialise()` 記稽核，而且在同一個 flush 裡。**
   分開會產生「領到了但沒有紀錄」的視窗（D1）。
3. **列表與讀取路徑不 `SELECT` 那四個 bytea 欄位。**
   用 `load_only()` 明確列出要的欄位。理由不是效能——是讓一個未來的
   `SecretDTO(**row.__dict__)` 這種寫法**取不到值**。

### 4.2 API（`backend/app/api/http/secrets.py`，新檔）

| 方法 | 路徑 | 動作 | 回什麼 |
|---|---|---|---|
| `GET` | `/api/projects/{id}/secrets` | `secret.manage` | 名稱、kind、建立者、`created_at`、`rotated_at`、`last_used_at`。**沒有值** |
| `POST` | `/api/projects/{id}/secrets` | `secret.manage` | 同上（201）。body：`name`／`kind`／`value` |
| `PUT` | `/api/projects/{id}/secrets/{sid}` | `secret.manage` | 輪替 ＝ 覆寫值。更新 `rotated_at`。**不能改 `name` 也不能改 `kind`** |
| `DELETE` | `/api/projects/{id}/secrets/{sid}` | `secret.manage` | 軟刪除。回 204 |
| `GET` | `/api/projects/{id}/secret-names` | `task.update` | **只有名稱陣列**，給卡片編輯的多選用（Developer 需要它，但不該因此拿到 `secret.manage`） |

五點：

- **`GET` 用 `secret.manage` 而不是 `project.view`。** 一份「這個專案有哪些憑證、
  上次用在什麼時候」的清單本身就是偵察資訊。Developer 需要的是名稱（最後一條端點）。
- **沒有 `PATCH`。** 改名等於一枚新機密（卡片會指向舊名），所以只能刪了再建。
- **`kind` 不可改。** `env` 改成 `git_pat` 會讓一枚已經進過子程序環境的值
  突然被當成「從未離開 daemon」的東西——那是一個回溯性的假設變更。
- **值的大小上限 8 KiB**（M-SC-1）。超過回 `413` 並說明；
  **RSA-4096 私鑰約 3.2 KB 仍在範圍內**，但 UI 要勸退它（`06-…md` §2）。
- 🆕 **`kind: git_pat`／`git_ssh_key` 在 `CLIORA_GIT_SECRET_DELIVERY_ENABLED=false`
  （預設）時建立被拒**：422 `GIT_SECRET_DELIVERY_DISABLED`，訊息**指名那個環境變數**
  並說明現階段 git 認證由 node owner 在機器上配置（D5b ①）。
  **拒絕而不是允許存下來**：一枚存得下來卻永遠不會被使用的憑證是一個假的設定完成狀態，
  而本 repo 已經對這個形狀表過態（`plan/18/02` 拒絕預建一張不授權任何東西的 `project_agents`）。
  `kind: provider_token` 一律可以建立（它的用途是 V2.4，本期不下放但也不誤導）。
- **旗標**：`require_agent_runs_enabled` 掛在 `require_projects_enabled` **之後**
  （`plan/18/00` D12 的順序，反了會從 404 變成 403 而洩漏路由存在）。

### 4.3 卡片的 `required_secrets` 子集檢查做兩次

一次在**卡片編輯**（`PATCH /api/tasks/{id}`，`services/tasks.py`）：宣告一個不在 allowlist
的名稱直接 422，訊息指名是哪幾個。
一次在 **dispatch**（`SC-05`）：因為 allowlist 可能在卡片編輯之後被縮小。

**兩處都要，而且不能只留 dispatch 那一處**：一張帶著無效宣告的卡片可以在看板上待幾天，
而它的問題只有在有人按下「派給 Agent」時才會出現。
（這與 `plan/18` 對 `delivery` 的處置相反——那時只在 dispatch 擋，
理由是 `delivery` 的值本身合法、只是階段還沒到。這裡不同：**名稱是錯的，而且立刻就知道。**）

### 4.4 刪除的語意

軟刪除 ＋ 立即失效：

- 進行中的 run **不受影響**（值已經在那台機器的記憶體裡了，平台收不回來）。
- 下一次 `materialise()` 就取不到它 → dispatch 時該卡的宣告變成無效 → 409 指名。
- **被 repository 引用時拒絕刪除**，訊息指名是哪一個 repository（§1.4 的 RESTRICT 只守硬刪除，
  這一條是軟刪除自己的檢查）。
- **不做「刪除即撤銷遠端 token」**——平台不知道那枚 PAT 在 GitHub 上叫什麼。
  UI 要提示「刪除只讓平台不再下放它；請到來源系統撤銷」。這一句很重要：
  沒有它，使用者會以為刪掉就安全了。

### 4.5 稽核

一筆 `audit_logs`，動作 `secret.deliver`：

```json
{"run_id": "…", "project_id": "…", "runner_id": "…",
 "secret_names": ["GITHUB_TOKEN", "NPM_TOKEN"], "key_version": 1}
```

**沒有值、沒有長度、沒有指紋**（D22）。
另外三個動作 `secret.create`／`secret.rotate`／`secret.delete` 記
`{project_id, secret_id, name, kind}`——**`name` 可以記**，它不是機密。

⚠️ **`FORBIDDEN_METADATA_KEYS` 要檢查一次**：V2.2 撞過一次
（`artifact.attached` 帶了 `filename` 而那個 key 在禁止清單裡，`plan/18/09` §3 第 23 條）。
`secret_names` 這個 key 不在清單裡，但**開工時要重讀那份清單而不是假設**。

## 5. 「永不可讀回」的兩條斷言

判準 1 要求兩條，而它們擋的是不同的錯誤：

| 斷言 | 擋什麼 | 怎麼寫 |
|---|---|---|
| **OpenAPI schema 掃描** | 一個未來的端點回傳了值 | `GATE-SC-NO-SECRET-IN-RESPONSE`：dump OpenAPI，走訪所有 response schema，任何屬性名為 `value`／`value_encrypted`／`dek_wrapped`／`plaintext`／`secret_value` → 失敗。**這一條掃的是整份 spec，不只是 secrets 那幾條路徑** |
| **實際回應斷言** | schema 說沒有但實作漏了（例如一個 `dict(row)`） | 建一枚值為 `SENTINEL-<uuid>` 的機密，然後對 **`GET /api/projects/{id}/secrets`、`GET /api/projects/{id}`、`GET /api/tasks/{id}`、`GET /api/runs/{id}`、`GET /api/audit`** 五條回應的**原始 bytes** 做 `not in` 斷言 |

第二條掃五條端點而不是一條，理由是最可能洩漏的不是 secrets 端點本身
（那支是本期寫的、正在被盯著），而是**別人的端點順手把整列丟出去**。

## 6. 測試

`backend/tests/db/test_project_secrets.py`：

1. 建立 → 列表沒有值、回應原始 bytes 不含 sentinel（§5 第二條的核心）。
2. 建立兩枚同值的機密 → `value_encrypted` 不同（DEK 每次新生）。
3. `rewrap` 到 `key_version: 2` → `value_encrypted`／`value_nonce` **逐位元組不變**，
   `dek_wrapped` 改變，`unseal` 仍得到原值（判準 3）。
4. 舊 `key_version` 的資料在舊金鑰仍在環境裡時解得開；舊金鑰被拿掉時
   → `SecretDecryptionFailed` 且訊息**指名缺哪一個版本**。
5. 軟刪除 → 同名可再建（partial unique index）；被 repository 引用時拒絕刪除並指名。
6. `materialise` 只回卡片宣告的那幾個，且記一筆稽核；稽核 payload 不含值。
7. `kind` 不可改、`name` 不可改。
8. 值超過 8 KiB → 413，**且沒有寫入半筆**（沿用 `plan/18` 產物配額測試的同一條紀律）。
9. **旗標關閉時所有 secrets 端點 404**（不是 403）。
10. `CLIORA_SECRET_MASTER_KEY` 的四種壞值 × `agent_runs_enabled` 兩種 → 八個案例，
    只有旗標開啟的四種會拒絕啟動（D4）。
11. 🆕 `CLIORA_GIT_SECRET_DELIVERY_ENABLED=false` 時：建立 `kind: git_pat` → 422
    且訊息含那個變數名；建立 `kind: env` → 201；`auth_kind: pat` 的 repository → 422。
    `=true` 時三者都成立。

`scripts/sc/gate-migration-roundtrip.sh`：沿用 `scripts/ar/` 的同名腳本，
`downgrade` 回 `0032` 之後與基線 `schema.txt` 逐位元組相同。
