# 06 — `AR-04`／`AR-09`：RBAC、API 與卡片產物

> **2026-08-10 裁決對本章的三個影響**：① `agent.manage` **本期不含「綁定 Project」**
> （`project_agents` 延後到 V2.3），所以它管的只有啟用／並行度／labels；
> ② 新增 **Repository 的兩條端點**——Agent 要自己 clone，平台就得知道 repo 在哪；
> ③ dispatch 的 409 集合換了（`03-…md` §4）。

## 1. `AR-04` — 四個動作與它們的強制點（同一個 PR）

`test_every_action_is_enforced_somewhere` 是對 `backend/app/**/*.py` 的**文字掃描**，
而且**雙向失敗**：動作寫進 `rbac.py` 而別處沒出現就紅，先加進 `UNENFORCED_ACTIONS`
再移除則在第二步紅。所以四個動作與十二條端點在**同一張 ticket**（沿用 `TK-04`／`PJ-03` 的 D6）。

`UNENFORCED_ACTIONS` **保持空集合**。

| 動作 | Viewer | Developer | Admin | 強制點 |
|---|---|---|---|---|
| `agent.view` | ✅ | ✅ | ✅ | `GET /api/agents`、`GET /api/agents/{id}` |
| `agent.manage` | ❌ | ❌ | ✅ | `PATCH /api/agents/{id}`（啟用／並行度／labels）。**本期沒有綁定端點** |
| `run.dispatch` | ❌ | ✅ | ✅ | `POST /api/tasks/{id}/dispatch` |
| `run.cancel` | ❌ | ✅ | ✅ | `POST /api/runs/{id}/cancel` |

🆕 **另有一處既有動作的強制點在本期擴充**（2026-08-11 裁決）：
`task.update` 現在還守著 `POST /api/tasks/{id}/messages` 與 `POST /api/tasks/{id}/artifacts`。
上游 `research/02/04` AR-07 原本把這兩條標成 `project.view`，**而那是一個 Viewer 寫入路徑**
——`rbac.py` 的註解明寫「handing Viewer a write would contradict the read-only viewer
the rest of the system promises」。改成 `task.update` 之後：

- **Viewer 讀得到訊息串與產物，但發不了言、附不了檔。** 與「Viewer 不能拖卡」一致。
- **run token 的 scope 不必動**（它本來就有 `task.update`，`05-…md` §1.3）
  ——而且這讓那個 scope 從「靠資源層檢查兜著」變成「真的對應它做的事」。
- **`GET` 仍然是 `project.view`。** 讀寫分開，不是整條端點升級。

**`agent.manage` 在本期只管三件小事**（啟用／並行度／labels），單看不像組織層決定。
`rbac.py` 的註解要寫未來式，並且要寫下本期的姿態宣告——理由與那三個地方各自的讀者見
`02-…md` §6。

同步更新四處，否則 `test_permission_matrix.py` 的三條斷言其中之一會紅：
`rbac.py` 的 `ROLE_ACTIONS`、seed migration `0030`、
`frontend/src/api/dto.ts` 的 `ACTION_*`、`docs/permission-matrix.md`（重新產生）。

`rbac.py` 裡要寫進去的兩段註解（`02-…md` §6 已列理由）：
`agent.manage` 為什麼從第一天就是 Admin（**V2.3 起綁定＝授權取用機密**），
以及 `run.dispatch` 為什麼獨立於 `task.update`（**會 clone 一個 repo 並在一台機器上跑程序**）。

## 2. API

全部掛在 `require_projects_enabled` **之後**再掛 `require_agent_runs_enabled`
（`00-…md` D12 的順序：反過來會讓旗標關閉的部署回 403 而不是 404，
那洩漏了這條路由存在）。

```text
GET    /api/agents                              agent.view      清單（線上狀態、負載、磁碟）
GET    /api/agents/{id}                         agent.view
PATCH  /api/agents/{id}                         agent.manage    啟用／停用、max_concurrent、labels
                                                                （**本期沒有綁定端點**，V2.3 才有）

GET    /api/projects/{id}/repositories          project.view    🆕
POST   /api/projects/{id}/repositories          project.manage  🆕 登記（身分，不含憑證）
DELETE /api/projects/{id}/repositories/{rid}    project.manage  🆕

POST   /api/tasks/{id}/dispatch                 run.dispatch    掛上佇列（202）
GET    /api/tasks/{id}/runs                     project.view    這張卡的 run 歷史
GET    /api/runs/{id}                           project.view
GET    /api/runs/{id}/logs                      project.view    分頁（?after_seq=）
POST   /api/runs/{id}/cancel                    run.cancel

GET    /api/tasks/{id}/messages                 project.view    ?since= 分頁
POST   /api/tasks/{id}/messages                 task.update 或 run token   留言／發言
POST   /api/tasks/{id}/artifacts                task.update 或 run token   上傳
GET    /api/artifacts/{id}                      project.view    下載（attachment）
GET    /api/artifacts/{id}/preview              project.view    白名單才有（§5）
DELETE /api/artifacts/{id}                      project.manage  需理由 ＋ audit
```

### 2.1 三個 API 形狀上的決定

**路徑參數一律 UUID。** 沿用 V2.1 的差異 #9：`card_ref` 走 `?ref=` 查詢。
一個欄位兩種意義是這個 repo 一貫拒絕的形狀。

**`GET /api/runs/{id}/logs` 是分頁不是串流，回的是 JSONL 事件行。** 規劃寫「分頁／串流」，選分頁：
串流要新開一條 WS 或 SSE，而 run log 的更新頻率（≤64 KiB／2 秒，`03-…md` §7）
用輪詢就夠了。前端每 2 秒帶 `?after_seq=` 拉一次，**跟隨模式**在前端做。
不新增第二條即時管道，是因為既有的那一條（terminal relay）是本期最不該碰的東西。

🆕 **回應體是 JSONL 事件行的陣列，不是一段文字**（D21）。伺服器**不解析、不重組**
——它把 `run_logs.data` 原樣回去，由前端逐行渲染（`07-…md` §4）。
理由：事件的 schema 是第三方 CLI 的，會隨版本變；
在伺服器端解析它等於把一個第三方 schema 變成我們 API 的一部分。

**`POST /api/tasks/{id}/messages` 同時接受兩種憑證，而且兩者要求的是同一個動作。**
人要 `task.update`，run token 的 scope 裡也是 `task.update`——
這是本期唯一一條人與 Agent 走同一個端點的路徑，而那正是 D24 的重點（「同一條管道」）。
**同一個動作**讓「同一條管道」這句話在授權層也成立，而不只是在 URL 上成立。
實作上是兩個依賴、兩條路由函式共用一個 service 方法——
**不是**一個依賴裡面 if 判斷 principal 型別（那會讓 `get_current_user`
與 `get_agent_principal` 的分離失效）。

### 2.2 `POST /dispatch` 的請求與回應

```text
Request   { assigned_runner_id?: uuid }        ← 不給 = 任一符合資格者（預設）
202       { run_id, status: "queued",
            waiting_reason: "any" | "assigned_offline" | "no_eligible_runner" }
409       { code: "TASK_NOT_READY" | "TASK_DEPENDENCY_UNSATISFIED" | "RUN_ALREADY_ACTIVE"
                 | "TASK_REQUIRES_SECRETS" | "TASK_DELIVERY_UNSUPPORTED"
                 | "PROJECT_NO_REPOSITORY" | "REPOSITORY_HOST_NOT_ALLOWED"
                 | "AGENT_DISABLED" | "AGENT_RUNTIME_MISMATCH",
            message, details: { runner_name?, phase?, settings_hint? } }
```

裁決移除了三個碼（`AGENT_NOT_BOUND`／`AGENT_NO_WORKSPACE`／`AGENT_LABELS_MISSING`）
並加了兩個（`PROJECT_NO_REPOSITORY`／`REPOSITORY_HOST_NOT_ALLOWED`）。
**`AGENT_NOT_BOUND` 會在 V2.3 回來，那時它是清單裡的第一個**（`03-…md` §3.1）。

`details.settings_hint` 是 `PROJECT_NO_REPOSITORY` 專用的：它帶 Project Settings 的路徑，
讓前端能直接給一個連結而不是一句「缺少設定」。

`waiting_reason` 是 §4 那三種文案的來源。它在回應裡而不是讓前端自己算，
因為那個判斷要跑一次資格查詢（`03-…md` §4），而前端沒有那條查詢。

`TASK_REQUIRES_SECRETS` 與 `TASK_DELIVERY_UNSUPPORTED` 是 `00-…md` D11 的落地：
**本期做不到的宣告在 dispatch 當下擋下**，`details.phase` 帶 `"V2.3"` 或 `"V2.4"`，
訊息寫「V2.3 起生效」而不是「不支援」。

**`source` 不在這張擋下清單裡了**——裁決之後 `source: repo` 是本期的主路徑，
而它需要的是 `PROJECT_NO_REPOSITORY` 這個**設定**檢查，不是一個「本期不支援」的拒絕。

### 2.3 🆕 Repository 端點的驗證

`POST /api/projects/{id}/repositories` 是本期唯一一條「使用者輸入會變成 daemon 的
git argv 的一部分」的路徑，所以驗證是安全需求不是體驗需求（`04b-…md` §5.2）：

```text
scheme          必須是 https 或 ssh（enum，不是自由字串）
host            RFC 1123 主機名，且必須在平台的 CLIORA_GIT_ALLOWED_HOSTS 內
path            ^[A-Za-z0-9._\-]+(/[A-Za-z0-9._\-]+)+$   ← 不含 .. 、不以 / 開頭
default_branch  ^[A-Za-z0-9._\-/]+$，不得以 - 開頭（那會被 git 當旗標）
```

**接受的是三個欄位而不是一個 URL**（`02-…md` §2.2）。一個「貼 URL 進來我們幫你剖」
的端點會在第一天就收到 `https://user:token@github.com/…`，
而那枚 token 會進資料庫、進 `git remote -v`、進錯誤訊息。
**不可表示勝過過濾。**

平台層另有一個 allowlist（`CLIORA_GIT_ALLOWED_HOSTS`），與 node 層的
`runner.git.allowed_hosts` **是兩份**：前者管「這個部署允許連到哪些 host」，
後者管「這台機器允許連到哪些 host」。**兩層都要過**，理由與
「Central 的 `authorize_workspace` ＋ daemon 的 `os.Root` 各驗一次」相同
（`sessions.py:73` 的註解：Central 是粗篩，node 是最終權威）。

## 3. `AR-09` — 產物的接收

### 3.0 🆕 兩種上傳者

| 誰 | 走哪條 | 什麼時候 |
|---|---|---|
| Agent（`cliora task attach`） | run token | 執行中，隨時 |
| 人（卡片上的附加） | 使用者 session | 隨時 |
| 🆕 **daemon 自己**（`git diff`） | run token（同一枚） | run 結束且 `delivery ∈ {none, artifact}` 且有變更（`04b-…md` §6） |

第三列是裁決帶來的，而它**不需要新的端點或新的授權路徑**——
daemon 用的是同一枚 run token 打同一條 HTTP 端點。
這是 D4（產物走 HTTP）的一個附帶好處：如果產物走 WSS，
daemon 就得為自己再實作一條上傳路徑。

### 3.1 上傳

`POST /api/tasks/{id}/artifacts`，`multipart/form-data`：
`file`（必填）、`sha256`（必填）、`message`（選填，有值時同時建一筆 `task_messages` 並互相關聯）。

伺服器端六步，順序是安全性的一部分：

```text
1. 授權：run token → 它的 task_id 必須等於路徑參數；使用者 → **`task.update`**（2026-08-11）
2. 大小：Content-Length 與實際讀入都要檢查（前者可以偽造）
3. 三層配額（§3.2）——在寫入之前，不是之後
4. sha256 重算比對；不符 → 400
5. content_type 判定（§3.3）——丟棄上傳者宣告的值
6. 兩張表一次交易：task_artifacts + task_artifact_blobs（+ task_messages）
```

第 3 步在第 6 步之前，所以配額是**先檢查後寫入**。這在併發下不精確
（兩個同時上傳可能一起通過），代價是配額可能被超出一件的大小。
**這個代價寫進 ADR 0030**，替代方案（對專案取 advisory lock）不做的理由：
配額是一條營運護欄不是安全邊界，而一把跨整個專案的鎖會讓兩個 run 互相等待。

### 3.2 三層配額

| 層 | 預設 | 設定 | 錯誤碼 |
|---|---|---|---|
| 單件 | 10 MB | `CLIORA_ARTIFACT_MAX_BYTES` | `ARTIFACT_TOO_LARGE` |
| 單 run 件數 | 20 | `CLIORA_ARTIFACT_RUN_MAX_COUNT` | `ARTIFACT_RUN_LIMIT` |
| 專案總量 | 1024 MB | `CLIORA_ARTIFACT_PROJECT_QUOTA_MB` | `ARTIFACT_PROJECT_QUOTA` |

三個都回 **`413`** 並帶 `details`（目前用量、上限）。CLI 端把它們翻成三句人話
（`05-…md` §2.3）。**不是靜默失敗**——出口條件 15。

專案用量是 `SUM(size) WHERE project_id=? AND deleted_at IS NULL`，
走 `ix_task_artifacts_project`（`02-…md` §2.6）。

### 3.3 `content_type` 由伺服器判定

**上傳者宣告的 `Content-Type` 一律丟棄。** 這一格是 stored XSS 的主要入口。

```text
1. 副檔名 → 一張封閉表（.png .jpg .jpeg .gif .webp .txt .md .log .json .patch .diff）
2. magic bytes 驗證（圖片）／UTF-8 可解碼驗證（文字）
3. 兩者不一致，或副檔名不在表上 → application/octet-stream
```

第 3 步的預設值是重點：**不認識的東西一律是二進位**，而二進位只能下載。
一個叫 `report.md` 但內容是 HTML 的檔案，會通過 UTF-8 驗證並存成 `text/markdown`
——而 `text/markdown` 的預覽是**當純文字顯示**（§5），所以它仍然渲染不了。

## 4. 產物的提供（本期最容易做錯的地方）

### 4.1 `GET /api/artifacts/{id}`

**恆為下載**，四個標頭一個都不能少：

```http
Content-Type: application/octet-stream
Content-Disposition: attachment; filename*=UTF-8''<percent-encoded>
X-Content-Type-Options: nosniff
Content-Security-Policy: default-src 'none'; sandbox
```

四個說明：

- **`Content-Type` 恆為 `application/octet-stream`，即使 DB 裡存的是 `image/png`。**
  下載端點不需要正確的型別，它需要的是「瀏覽器不會嘗試顯示它」。
  正確的型別在**預覽端點**（§5）上供應。
- **`filename*=UTF-8''…`（RFC 5987）而不是 `filename=`**：檔名可能含非 ASCII，
  而 `filename=` 加引號的形式在檔名含 `"` 或 `\r\n` 時是一條標頭注入。
  百分比編碼讓那件事不可表示，而不是要靠過濾。
- **`nosniff`** 是 `Content-Type` 那條的搭檔：沒有它，IE／舊 Edge 仍會嗅探。
- **CSP `sandbox`** 是第三層：即使前兩層都被繞過，回應也不會有 script origin。

`Content-Disposition` 的 `filename` 另外做一次**檔名清洗**（路徑分隔符、控制字元、
前導 `.`），存的是原始檔名，送的是清洗過的——存原始是為了證據性，
送清洗過的是為了不相信檔名。

### 4.2 存取控制

繼承 Project（`project.view`）。**沒有公開連結、沒有可猜的 URL、沒有簽章連結。**
`artifact_id` 是 UUIDv4，但那不是授權——每一次下載都要查
「這件產物的 project 是不是這個使用者看得到的」，與既有的 Project 資源層一致。

**不做預簽 URL**：那會是這個系統第一條「拿著 URL 就能讀」的路徑，
而 ADR 0020 的單一 origin 部署沒有第二個 origin 可以隔離它。

## 5. 預覽白名單

`GET /api/artifacts/{id}/preview` **只對三類 `content_type` 存在**，其餘回 404
（不是 403——一個不能預覽的東西，「有沒有預覽端點」本身不該是一個訊號）：

| `content_type` | 回應的 `Content-Type` | 說明 |
|---|---|---|
| `image/png`、`image/jpeg`、`image/gif`、`image/webp` | 同值 | 走 ADR 0015 的既有預覽限制（尺寸、大小） |
| `text/plain`、`text/log` | `text/plain; charset=utf-8` | |
| `text/markdown` | **`text/plain; charset=utf-8`** | **不渲染**。要看渲染後的樣子就下載 |

三個標頭仍然要有：`nosniff`、`Content-Disposition: inline`（只有這裡是 inline）、
`Content-Security-Policy: default-src 'none'; sandbox`。

**`text/html` 不在這張表上，而且永遠不會在。** `00-…md` D14 的理由：
Cliora 是單一 origin 部署（ADR 0020），「在新分頁開啟」與「內嵌渲染」是同一件事。
D31 已經給了 V2.5 的答案（mockup 走 Pinggy tunnel 的**另一個 origin**），
所以這裡不必留後路。

### 5.1 兩個機器斷言（出口條件 11）

規劃寫「應用 origin 內沒有任何路徑會渲染它」——那是一個**否定命題**，
目視檢查證不了。兩條可重跑的斷言：

1. **OpenAPI 掃描**：對 `AR-00` 存下來的 `openapi.json` 與本期的 dump 做差集，
   斷言**沒有任何回應宣告 `text/html`**，且 `/api/artifacts/{id}` 只有 `GET` 與 `DELETE`
   （後者同時是「產物不可變」的機器形式）。
2. **前端路由表 diff**：對 `AR-00` 的 `frontend-routes.txt` 比對，
   斷言本期新增的路由都不接受 artifact id 當渲染來源
   （新增的三條是 `/projects/:id/runs/:runId` 與兩個既有頁的分頁，都不是）。

## 6. 刪除

`DELETE /api/artifacts/{id}`：`project.manage` ＋ **必填 `reason`** ＋ audit。

- `task_artifacts` **軟刪除**（`deleted_at`／`deleted_by`／`delete_reason`）
- `task_artifact_blobs` **硬刪除**（配額要真的被釋放）

這個不對稱是刻意的，寫進 ADR 0030：**metadata 留是為了「誰以什麼理由刪的」不消失，
內容刪是為了「刪除是配額用盡時的唯一出路」不是假的。**

UI 上被刪除的產物顯示為一行灰字（檔名、大小、刪除者、理由），不是消失——
與 `activity_events` 的「歷史不刪」是同一條規則。

## 7. 測試清單（本兩票）

| # | 測試 | 斷言 |
|---|---|---|
| 1 | Viewer 打 `PATCH /api/agents/{id}` | 403，audit 有 `authz.denied` |
| 1b | 🆕 **Viewer 打 `POST /api/tasks/{id}/messages`** | **403**（需 `task.update`）。同一個 Viewer 打 `GET` 版本 → **200**。**讀寫分開的斷言，兩條測試** |
| 1c | 🆕 **Viewer 打 `POST /api/tasks/{id}/artifacts`** | **403**。留一條而不是只留 1b，因為它們是兩個不同的路由函式，而漏掉一個就是一個 Viewer 寫入路徑 |
| 2 | Developer 打 `POST /api/projects/{id}/repositories` | 403（登記 repo 是 `project.manage`） |
| 3 | 🆕 登記 repo 時 host 不在 `CLIORA_GIT_ALLOWED_HOSTS` | 400，訊息指名 host 不被允許 |
| 4 | 🆕 登記 repo 時 `path` 含 `..`／`default_branch` 以 `-` 開頭 | 400 各一（§2.3） |
| 5 | 🆕 **沒有任何端點接受完整的 repo URL** | OpenAPI 斷言：`repositories` 的 request schema 沒有 `url` 欄位（§2.3 的「不可表示勝過過濾」） |
| 6 | 🆕 dispatch `source: repo` 但 Project 沒登記 repo | 409 `PROJECT_NO_REPOSITORY` ＋ `details.settings_hint` |
| 7 | dispatch 指定已停用的 runner | 409 `AGENT_DISABLED`，**訊息含 runner 名稱** |
| 8 | dispatch 指定 runtime 不符的 runner | 409 `AGENT_RUNTIME_MISMATCH` |
| 9 | 指定的 runner 離線 | 202 ＋ `waiting_reason: "assigned_offline"` |
| 10 | 沒有符合資格的 runner | 202 ＋ `waiting_reason: "no_eligible_runner"`，**與 9 的文案不同** |
| 11 | 卡片宣告 `required_secrets` | 409 `TASK_REQUIRES_SECRETS`，訊息含「V2.3 起生效」 |
| 12 | 卡片宣告 `delivery: pull_request` | 409 `TASK_DELIVERY_UNSUPPORTED`，`details.phase = "V2.4"` |
| 13 | 上傳 12 MB | 413 `ARTIFACT_TOO_LARGE` ＋ `details` |
| 14 | 專案配額用盡 | 413 `ARTIFACT_PROJECT_QUOTA`，**且沒有寫入半筆** |
| 15 | 上傳 `.html` | 存成 `application/octet-stream`；下載帶四個標頭；`/preview` 回 404 |
| 16 | 上傳一個內容是 HTML 的 `.md` | 存成 `text/markdown`；`/preview` 回 `text/plain` |
| 17 | 🆕 上傳 `.patch`（`git diff` 的產物） | 存成 `text/plain`；`/preview` 可看；**不是 `application/octet-stream`**（那會讓最常見的一種產物變成只能下載） |
| 18 | 檔名含 `"` 與換行 | `Content-Disposition` 是百分比編碼，沒有標頭注入 |
| 19 | 產物的 update | **沒有任何路由**（OpenAPI 斷言） |
| 20 | 刪除不帶理由 | 400；帶理由 → blob 消失、metadata 在、audit 有理由 |
| 21 | run 保留期到期、`run_logs` 清空之後下載產物 | 200（判準 14） |
| 22 | 另一個 Project 的使用者下載 | 404（不是 403——存在性也不該洩漏） |
| 23 | 兩個旗標各自關閉 | 本期所有端點 404，不是 403 |
