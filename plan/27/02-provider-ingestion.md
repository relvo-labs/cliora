# 02 — Provider ingestion（`HD-01`–`HD-03`、`HD-15`）

> 上游：[`research/03/12`](../../research/03/12-migration-and-rollout.md) §6 的 `HD-01`–`HD-03`。
> **本檔假設 ★ [D120](./01-decisions-and-governance.md#d120)（只做 pull）已被採納。**
> 若改為採納 webhook，§3 換掉、§4 增加一張表、§8 的 SR-4 回到上游的五項，並多兩個波次。

## 1. 要做的事，一句話

> 一個 PR 合掉了、一個版本發出去了——這兩件**發生在別人伺服器上**的事，
> 要能進到 Project 記憶，帶著一個**低於任何經過 Cliora 核准的事實**的可信層級，
> 而整個過程 Cliora **只發 GET**、**只在 worker 裡發**、**沒有新增任何未認證入口**。

## 2. 為什麼是 pull 而不是 push

`00` §0.1 的 ★ D120 給了裁決，這裡給零件對照。**要做的每一件事都已經有一個實作**：

| webhook 需要 | pull 需要 | 現況 |
|---|---|---|
| 未認證的 `POST` 入口 | — | `api/http/` 有 **140 條路由、零條未認證** |
| HMAC 常數時間比較 | — | 不存在 |
| `provider_deliveries` 去重表 | — | 不需要：「重讀 entity 當前狀態」讓重複免費（`outbox.py:15`） |
| 一個通用 rate limiter | 一個從資料推導的上限 | `knowledge/repo.py:255` **已經是這個形狀** |
| `webhook_secret` secret kind ＋ 輪替 | 既有 `provider_token` | `secrets.py:44` 已有，且在 `UNDELIVERABLE_KINDS` |
| 非同步 enqueue | 既有 reconciler | `worker.py` 有 advisory lock、`FOR UPDATE SKIP LOCKED`、`BATCH=32` |
| 一次針對未認證入口的獨立安全審查 | SR-4 的兩項 | — |

**唯一失去的是新鮮度**：從「秒」變成「一個 reconcile 週期」。
300 秒這個數字要寫進 release note，因為它是一個產品承諾。

## 3. `services/provider_reads.py`（`HD-01`）

**三個讀取，表是關的**——與 `providers.py` 的三個動作同一個紀律：

```text
read_pull_request(repo_path, number, token)      -> PullRequestState | None
list_pull_requests(repo_path, token, *, since)   -> list[PullRequestState]
list_releases(repo_path, token, *, since)        -> list[ReleaseState]
```

`PullRequestState` 至少含：`number`、`title`、`body`、`state`、
`merged`（bool）、`merged_at`、`head_ref`、`base_ref`、`html_url`、`updated_at`。
`ReleaseState`：`tag`、`name`、`body`、`published_at`、`draft`、`prerelease`、`html_url`。

**四個屬性，每一個都有一個 gate 或一個既有論證**：

| 屬性 | 怎麼保證 | 沿用哪一段既有論證 |
|---|---|---|
| 只發 GET | `GATE-HD-READS-ARE-GETS`：檔案內 HTTP method 字面只有 `"GET"` | `GATE-DV-PROVIDER-VERBS` 的「以缺席驗證」 |
| 不含寫入動作 | `GATE-HD-NO-WRITE-IMPORT`：不 import `create_pull_request`／`comment_on_pull_request` | `GATE-DV-NO-HTTP-IN-LOOP` 的同一個形狀 |
| host 由部署決定 | 沿用 `settings.provider_api_host_list()`，**同一個設定** | `providers.py:167`「a repository row cannot reach this」 |
| token 不進 log／error | 自己寫一份 `_safe_detail()`（[D119](./01-decisions-and-governance.md#d119) 的刻意重複） | `providers.py:203`「the error body is the string a person pastes into a ticket」 |

**重試政策與 `providers.py` 相反，而理由是同一個**：
`providers.py` 不重試，因為「creation is not idempotent」。
`provider_reads.py` **可以重試**，因為 GET 是幂等的——
但**不在請求內重試**，而是「這一輪失敗就下一輪再讀」，
因為那正是 reconciler 已經提供的東西。
連續 3 輪失敗 → 該 repository 停止同步（[D128](./01-decisions-and-governance.md#d128)）。

## 4. Migration `0044`

全部 **additive、可逆**。

```text
knowledge_sources.source_type CHECK   八值 → 十值（+ pull_request, release）
knowledge_jobs.source_type    CHECK   八值 → 十值   ← 兩張表都有，別漏
projects.provider_sync_enabled        BOOLEAN NOT NULL DEFAULT false
project_repositories.provider_synced_at   TIMESTAMPTZ NULL
project_repositories.provider_sync_error  TEXT NULL
project_repositories.provider_sync_failures  SMALLINT NOT NULL DEFAULT 0
```

**沒有新表。** provider source 走既有 `knowledge_sources`／`knowledge_chunks`，
provider job 走既有 `knowledge_jobs`。
一張新表的代價是一組新的 cascade 規則、一組新的 isolation 測試與一組新的 retention 問題，
而這三者對 `knowledge_sources` **已經全部答過了**（ADR 0038）。

**downgrade**：CHECK 收回八值**之前**要先刪掉那兩型的 source
（否則 CHECK 加不回去）。順序在 migration 裡寫死，並且
`GATE-PX-MIGRATION-ROUNDTRIP` 會跑到它。

**同步要改的四處程式碼**（漏任何一處都會靜默）：

| 檔案 | 改什麼 | 漏掉的後果 |
|---|---|---|
| `store.py:64` `SOURCE_TYPES` | ＋2 | `store.upsert()` 的 `assert source_type in SOURCE_TYPES`（`:129`）會擋下來——**這一處會響** |
| `store.py` `EXTERNALLY_TRIGGERED` | 新增（[D121](./01-decisions-and-governance.md#d121)） | 覆蓋率測試紅——**會響** |
| `search.py:70` `_HALF_LIFE_DAYS` | ＋2 | `.get(…, 90.0)` **不會響**。PR 拿到 90 天（剛好對），release 也拿到 90 天（**錯，該是 365**）。這一處是**靜默**的 |
| `models.py:2055` 的兩個 `CheckConstraint` | ＋2 | ORM 與資料庫不一致；`alembic revision --autogenerate` 之後會產生一個假的 diff |

**第三處是本節唯一的靜默陷阱**，所以它有一個測試：
`test_every_source_type_has_an_explicit_half_life` 斷言
`set(_HALF_LIFE_DAYS) == SOURCE_TYPES`——**用相等而不是包含**，
這樣多寫一個也會紅。

## 5. Reconcile 的節奏（`HD-03`）

掛進**既有** `knowledge/worker.py` 的 reconcile 相位，不新增背景任務：

```text
每 300 秒（RECONCILE_INTERVAL_SECONDS，既有）：
  取 advisory lock（既有——「its cost is per replica and its benefit is not」）
  對每個 provider_sync_enabled 的 project：
    對每個 host 在 allowlist 內、provider_sync_failures < 3 的 repository：
      GET PR 清單（since = provider_synced_at）      ┐
      GET release 清單（since = provider_synced_at）   ├ ≤ 3 個 GET／輪
      GET 有變動的 PR 的詳情（最多一個／輪）           ┘
      對每一筆變動 enqueue 一個 knowledge_job（既有 outbox 路徑）
      provider_synced_at = now()
    失敗 → provider_sync_failures += 1、provider_sync_error = 訊息（**已剝除 token**）
    成功 → provider_sync_failures = 0、provider_sync_error = NULL
```

**上限從資料推導**（[D128](./01-decisions-and-governance.md#d128)）：
`provider_synced_at` 在一小時內被更新的次數就是這一小時的輪數，
不需要計數表——`repo.py:255` 的同一個論證。

**為什麼 enqueue 而不是直接寫**：走既有 outbox 讓 provider 的 ingest
與其他八種型別**完全同一條路徑**，包含 `MAX_ATTEMPTS=5`、
`FOR UPDATE SKIP LOCKED` 的多 replica 正確性，以及 redaction 在 `ingest()` 的單一出口
（`sources.py:11`：「Putting it here rather than in each handler means a new handler cannot forget it」）。

**`GATE-HD-NO-PROVIDER-IN-REQUEST`**：`backend/app/api/http/` 下不得 import `provider_reads`。
這是上游 SR-4 第三項（「webhook 不在請求內同步抓」）的 pull 版本，
而它比原版強——原版審查一個行為，這個斷言一個依賴。

## 6. 權限、憑證與設定（`HD-15`）

| 面 | 處置 |
|---|---|
| 開關 | `projects.provider_sync_enabled`，寫它需要既有 `project.update`（[D130](./01-decisions-and-governance.md#d130)） |
| 憑證 | 既有 `provider_token` secret kind、per-repository、在 `UNDELIVERABLE_KINDS`（[D129](./01-decisions-and-governance.md#d129)）。**`secrets.py` 一行不改** |
| 讀取 | provider source 的可見性走既有 `knowledge_sources.visibility='project'` ＋ `beta.1` 的可見專案述詞（`services/work/scope.py`）。**不新增第二個授權路徑** |
| 設定 UI | 專案設定頁：開關、上次同步時間、下次同步時間、最近一次失敗原因（**已剝除 token**）、每個 repository 的 `provider_sync_failures` |
| 卡片 UI | Drawer 的「Related delivery」：這張卡的 PR 狀態（開／合／關）、所屬 release、citation 連回 knowledge source |

**設定頁顯示失敗原因是刻意的**：一個被撤權的 token 在 pull 模型下的表現是
「什麼都不再更新」，而那在畫面上與「這個專案最近沒有 PR」**完全一樣**。
`provider_sync_error` 是唯一能區分兩者的東西——這與 `metrics.py:52` 對
`METRIC_PERSIST_ERROR_TOTAL` 寫的理由是同一條。

## 7. Authority transition（`HD-02`）

handler 在 `services/knowledge/provider_sources.py`（新檔，[D122](./01-decisions-and-governance.md#d122)）：

```text
PR / MR
  merged == false  →  authority = "discussion"    (0.75)
  merged == true   →  authority = "reviewed"      (1.15)
Release
  draft == true    →  不 ingest（一個草稿不是一個事實）
  否則             →  authority = "reviewed"      (1.15)

accepted / authoritative / canonical / verified   永不可達
  ← GATE-HD-PROVIDER-AUTHORITY-CEILING（檔案內不出現這四個字串）
```

**`verified` 也不給**：在這個系統裡 `verified` 的意思是
「Cliora 的驗證機制跑過並通過」（`sources.py:393` 讀 `report.source == "machine_verified"`）。
一個 provider 的 CI 綠燈不是 Cliora 的驗證。
**十級 authority 的全部價值來自於每一級只有一個意思。**

**supersede 鏈**：`source_version` 用 provider 的 `updated_at`（PR）或 `published_at`（release）。
一個 PR 從 open 變 merged 是**同一個 entity 的新版本**，
所以它 supersede 舊版而不是新建一條——這正是 `store.upsert()` 的既有語意，
`source_updated_at` 就是為此存在的比較欄位（`models.py:2083`）。

**retention 與 tombstone**：[D132](./01-decisions-and-governance.md#d132) 的四條規則。

## 8. SR-4 在 pull 模型下的樣子

| # | 審查項 | 通過標準 | 來源 |
|---:|---|---|---|
| 1 | provider token 的保存、範圍與輪替 | 沿用既有機制的回歸：換 secret → 下一輪用新值 → 舊值不在任何地方 | 上游保留 |
| 2 | merge 前的 PR 內容不自動成為 policy | `GATE-HD-PROVIDER-AUTHORITY-CEILING` ＋ 四個負面測試（四個高階各一） | 上游保留 |
| 3 | **對外 GET 只發生在 worker，不在使用者請求裡** | `GATE-HD-NO-PROVIDER-IN-REQUEST` | 上游第三項的改寫 |
| 4 | **`provider_reads.py` 只發 GET** | `GATE-HD-READS-ARE-GETS` ＋ `GATE-HD-NO-WRITE-IMPORT` | pull 新增 |
| 5 | **被撤權的 token 不會讓迴圈無限重試** | 連續 3 次失敗停止 ＋ `PROVIDER_READ_FAILED` 有 raise 點與測試 | pull 新增 |
| 6 | provider 的錯誤 body 不含 token、不進 log、不進 metric label | redaction 測試 ＋ metric label allowlist 已封閉（`metrics.py:203`） | pull 新增 |
| 7 | 無權專案的 provider source 不出現在 search／count／citation | 沿用 SR-2 的八條 isolation 測試，**加 provider 兩型各一** | 上游繼承 |
| 8 | provider 內容不進 context pack 的 instruction layer | 沿用 ADR 0039 的 evidence／instruction 分層測試，**加一則含注入字串的 PR body** | 上游繼承 |

**上游的 webhook signature 與 delivery 去重兩項在 pull 模型下不存在**，
而**這件事要寫進簽核文字**——一個少了兩項的審查表，
若不說明為什麼少，下一個人會以為它被漏掉了。

## 9. 出口條件（本節）

| ☐ | 條件 | 證據 |
|---|---|---|
| ☐ | ADR 0043 已 accepted，**含 webhook 設計並標未實作** | `docs/adr/0043-*.md` |
| ☐ | `0044` upgrade → downgrade → upgrade 三次，資料未損 | `GATE-PX-MIGRATION-ROUNDTRIP` |
| ☐ | `set(_HALF_LIFE_DAYS) == SOURCE_TYPES` | `test_every_source_type_has_an_explicit_half_life` |
| ☐ | `SOURCE_TYPES - mapped == EXTERNALLY_TRIGGERED` | 改寫後的覆蓋率測試 |
| ☐ | 四個 `GATE-HD-*`（READS-ARE-GETS、NO-WRITE-IMPORT、NO-PROVIDER-IN-REQUEST、AUTHORITY-CEILING）全綠 | `scripts/hd/gates.sh` |
| ☐ | 一個真的 merged PR 在 ≤ 300 秒內出現在 Related knowledge，authority 是 `reviewed` | `HD-15` 的錄影 ＋ 一條旅程 |
| ☐ | 撤權 token → 3 輪後停止 → 設定頁顯示原因 | 負面測試 ＋ 截圖 |
| ☐ | `providers.py` 的 diff 為零 | `GATE-HD-TOUCH-LIST` |
| ☐ | SR-4 八項全部具名簽核，**含「為什麼少了兩項」** | `docs/security-review-v2e1.md` |
