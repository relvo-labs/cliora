# 04 — 八種來源、authority 與 repo sync（`KN-04`／`KN-05`／`KN-06`）

## 1. 逐一對應

每一列的 `external_id` 與 `version` 是**冪等鍵的兩半**，所以它們是這張表最重要的兩欄。

| source_type | 來自哪張表 | `external_id` | `source_version` | authority | ticket |
|---|---|---|---|---|---|
| `policy` | `projects`（description、`verification_commands` 名稱、`process_overrides`）＋ `process_definitions` | `project:<id>` / `process:<version>` | `updated_at` 的 ISO 秒 | `authoritative` | `KN-04` |
| `ticket` | `tasks`（title、description、objective、scope、non_goals、acceptance_criteria、readiness）＋ `task_dependencies` | `task:<id>` | `v<tasks.version>` | `discussion` | `KN-04` |
| `conversation` | `task_messages`（`kind ∈ comment/question/answer/proposal`） | `message:<id>` | `seq:<conversation_seq>` | `discussion`；`proposal` → `generated` | `KN-04` |
| `decision` | `task_messages(kind='decision')`、`requirements`、`feature_specs`、`document_patch_proposals` | `decision:<message_id>` / `spec:<id>` | `seq:<n>` / `v<seq>` | `accepted`；人工標記後 `authoritative` | `KN-04` |
| `artifact` | `task_artifacts` ＋（可索引型別的）`task_artifact_blobs` | `artifact:<id>` | `sha256:<12>` | `verified` 若掛在 pass 的 report 上，否則 `generated` | `KN-05` |
| `verification` | `verification_reports`、`evidence_items` | `report:<id>` / `evidence:<id>` | `reported_at` / `collected_at` 的 ISO 秒 | `verified` | `KN-05` |
| `repo_doc` | run 內推上來的檔案（D77） | `<repository_id>:<path>` | commit SHA | `canonical` | `KN-06` |
| `activity` | `activity_events`（gate 核准、force done、run 結束） | `activity:<id>` | `occurred_at` 的 ISO 秒 | `platform fact` → 存成 `verified` | `KN-05` |

★ 最後一列是上游的一個不一致：§2 的表把 Activity 的 authority 寫成 `platform fact`，
但 D45 的十級裡沒有這一級。本期把它存成 **`verified`**（它是平台自己觀察到的事實，
與機器驗證同一等級），並在 ADR 0038 的 authority 表註明這個對應。
**不新增第十一級**——一個只有一種來源在用的等級不值得讓所有排序邏輯多一個分支。

### 1.1 `version` 的三種形狀，與為什麼不統一

```text
單調計數器   v3、seq:41           ticket、conversation、decision
內容位址     sha256:9f2c…、<SHA>  artifact、repo_doc
時間戳       2026-08-22T11:03:07Z activity、verification、policy
```

統一成時間戳很誘人，但會壞掉冪等：兩個 worker 在同一秒處理同一則訊息會產生兩個版本。
統一成內容 hash 也不行：`ticket` 的內容 hash 會讓「改一個字」變成一個新版本，
於是 supersede 鏈在一週後有兩百節。

**規則是：能拿到單調計數器就用它，拿不到就用內容位址，都沒有才用時間戳。**
這一句要進 ADR，因為第一個加新來源的人會問。

## 2. Authority 的寫入規則（D45）

```text
authority 的寫入權力只在 ingestion pipeline 手上。API 不接受呼叫端指定。
```

可測形式（`GATE-KN-AUTHORITY-SERVER-SIDE`）：
**沒有任何 Pydantic request schema 有 `authority` 欄位**，AST 斷言。
這與 `FR-VERIFY-002`「三級 `source` 由伺服器端判定，忽略 payload」是同一條原則，
而那裡的做法更強一階——`verification_reports` 的服務函式**根本沒有 `source` 參數**。
本期照抄：`upsert_source()` 的 `authority` 由 handler 決定，
呼叫端傳不進來。

### 2.1 三種會改變 authority 的事件

| 事件 | 從 | 到 | 誰觸發 |
|---|---|---|---|
| 人工標記為正式決策 | `accepted` | `authoritative` | 人（`project.manage`）＋ audit |
| 人工撤回 | 任何 | `retracted` | 人（`project.manage`）＋ audit |
| 新版本進來 | 舊列 → `superseded` | — | pipeline，寫 `knowledge_links(supersedes)` |
| （`beta.2`）PR merge | `reviewed` | `canonical` | provider sync |

`superseded` 與 `retracted` **不是降權，是排除**：預設 retrieval 完全不回傳，
只有帶 `include_history=true` 的歷史查詢看得到（[`05`](./05-retrieval-and-search.md) §3）。

★ **supersede 的判定規則要寫死**：同一個 `(project, source_type, external_id)`
下出現更大的 version 時，舊的那些標 `superseded`。
`repo_doc` 的「更大」是「這個 commit 的 manifest 裡有它」（不比較 SHA 大小——
SHA 沒有順序），其餘是計數器或時間戳的比較。
**這是唯一一處 `repo_doc` 與其他來源規則不同的地方**，值得一個註解。

## 3. 什麼不進索引

| 不進 | 為什麼 | 怎麼保證 |
|---|---|---|
| Raw run log | 有保留期的診斷資料、噪音高、較可能含敏感內容 | `GATE-KN-NO-RAW-LOG-INDEX`（架構上不 import） |
| 機密值、憑證樣式、敏感檔名 | — | [`03`](./03-ingestion-and-outbox.md) §8 |
| 二進位 artifact | 沒有可索引文字 | 只索引 metadata（filename、content_type、size、sha256） |
| vendor／generated／minified | 噪音，且會吃掉整個索引 | `.clioraignore` ＋ 內建 glob（§5.2） |
| Agent 的 raw stdout | 同 run log | 只有經 redaction 的 run summary 與明確 evidence |
| 跨 Project 的任何東西 | 預設禁止 | 每一層查詢帶 `project_id`（`GATE-KN-PROJECT-SCOPED`） |

**人類選定的 log excerpt 是例外**：一個人可以把一段 log 貼成 conversation 訊息，
那時它是 `discussion`；或標記成 `diagnostic`（需要 `project.manage`）。
**平台自己永遠不會挑一段 log 進索引。**

## 4. `KN-04`／`KN-05` 的 handler 形狀

```python
# app/services/knowledge/sources.py
@dataclass(frozen=True, slots=True)
class ExtractedSource:
    external_id: str
    version: str
    authority: str
    title: str
    occurred_at: datetime
    source_updated_at: datetime
    text: str
    uri: str | None                 # 前端 citation 要跳去哪
    links: list[tuple[str, str]]    # (relation, other_external_id)

Handler = Callable[[AsyncSession, uuid.UUID, str], Awaitable[list[ExtractedSource]]]
_HANDLERS: dict[str, Handler] = {...}
```

**handler 是純讀 ＋ 回傳，不寫任何表。** 寫入全部在 worker 的第 4、5 步。
理由：冪等的 upsert 邏輯只有一份，八個 handler 各自寫入會有八個機會寫錯。

### 4.1 `uri` 是 citation 的落點

| source_type | `uri` |
|---|---|
| `ticket` | `/projects/{pid}/tasks/{tid}` |
| `conversation`／`decision` | `/projects/{pid}/tasks/{tid}?seq={n}` |
| `artifact` | `/api/artifacts/{id}` |
| `verification` | `/projects/{pid}/tasks/{tid}#verification-{id}` |
| `repo_doc` | `repo://{repository_id}/{path}@{commit}` |
| `policy` | `/projects/{pid}` |
| `activity` | `/projects/{pid}?activity={id}` |

`repo://` 是一個**刻意不可點的 scheme**：前端把它 render 成
「`docs/adr/0035-…md` @ `139f143`」的純文字加一個複製按鈕。
理由是 Cliora 沒有 repo 瀏覽器，而一個假裝可以點的連結比純文字糟。
`?seq={n}` 需要 `TaskDetailView` 支援滾到某一則訊息——`KN-11` 的一部分。

## 5. `KN-06`：repo sync 協定（D77）

### 5.1 兩次呼叫

```text
① POST /api/cli/runs/knowledge/repo-manifest        run token
   { "commit": "<sha>", "repository_id": "<uuid>",
     "files": [ {"path": "docs/adr/0035-x.md", "sha256": "…", "size": 8123}, … ] }
   ←  { "want": ["docs/adr/0035-x.md", …],          Central 沒有這些 content_hash
        "skipped": [ {"path":"…","reason":"too_large"}, … ],
        "removed": 3 }                              上一個 commit 有、這次沒有 → 已 tombstone

② POST /api/cli/runs/knowledge/repo-content         run token
   { "commit": "<sha>", "files": [ {"path": "…", "text": "…"}, … ] }
   ←  { "ingested": 12, "bytes": 148_221 }
```

**內容位址協商**：Central 用 `knowledge_chunks.content_hash` 判斷自己有沒有。
於是「文件沒改」＝「一次 manifest 呼叫、零位元組上傳」，
而這正是絕大多數 run 的情況。這個設計讓 sync 便宜到可以每個 run 都做。

★ **`removed` 在第 ① 步就處理完**：manifest 是**全量**的，
所以 Central 在收到它的那一刻就知道哪些路徑消失了，
不需要等第 ② 步（那一步可能因為上限而不完整）。這是 J12 的前半。

### 5.2 選檔規則

```text
包含（依序判斷，先中先算）
  1. project 的 knowledge_settings.include_globs（若有）
  2. 內建：**/*.md **/*.mdx **/*.rst **/*.txt **/*.adoc
           README* CHANGELOG* CONTRIBUTING* LICENSE*
           docs/** doc/** adr/** rfc/** spec/**
           **/*.sql（schema 與 migration 是文件）
           openapi*.{json,yaml,yml} **/*.proto
排除（優先於包含）
  1. .gitignore                （git 自己已經排除的不會在 checkout 裡）
  2. .clioraignore             （本期新增，語法同 .gitignore）
  3. knowledge_settings.exclude_globs
  4. 內建：**/node_modules/** **/vendor/** **/dist/** **/build/** **/.venv/**
           **/*.min.* **/*.lock **/*-lock.json **/target/** **/__pycache__/**
  5. 敏感檔名（03 §8）
  6. 二進位（前 8 KiB 含 NUL byte）
```

**`.clioraignore` 在 repo 裡，由 `cliora` 在 run 內讀取**——
不是 Central 的設定。理由：它是「這個 repo 的作者說什麼不該被索引」，
而那個判斷屬於 repo，不屬於平台。project 的 `exclude_globs` 是平台側的補充。

★ **symbol map 本期不做。** 上游 `KN-06` 寫「Repository docs／symbol sync」與
「大型 repo 只索引 docs／config／symbol map／變更範圍」。symbol map 需要一個
語言感知的解析器（tree-sitter 或每語言一支），那是一個獨立題目，而它的價值
在 lexical 檢索下有限——function name 已經由 trigram 通道覆蓋。
**寫進 known limitations 與 [`10`](./10-open-measurements.md)，不假裝做了。**
`**/*.sql` 與 `**/*.proto` 進索引是這個缺口的部分補償：它們是「schema 即文件」。

### 5.3 CLI 端（`daemon/internal/cli/knowledge.go`）

```text
cliora knowledge sync [--dry-run]
  1. 找 run context（既有 FindContext，含 plan/23/10 §9.1 修過的 run.token 退回）
  2. git rev-parse HEAD                （工作目錄裡就是那個 commit）
  3. 走檔案樹，套 §5.2 規則，算 sha256
  4. POST repo-manifest → 得到 want
  5. 讀 want 的內容，POST repo-content（依 8 MiB 上限分批）
  6. 印摘要：N files indexed, M unchanged, K skipped
```

**`--dry-run` 印出會送什麼但不送。** 這不是方便功能：
它是使用者判斷「我的 exclude 規則對不對」的唯一方法，
而一個要靠上傳之後看結果才知道的排除規則不會被人維護。

★ **`git` 的使用**：只有 `rev-parse HEAD`，唯讀、無網路。
`internal/cli/` 已經沒有 git 呼叫，所以這是第一個——要在
`GATE-KN-TOUCH-LIST` 的例外清單裡具名，並在 code review 確認它不接受任何外部輸入。
若不想加這個依賴，退路是讀 `.cliora/context/` 裡 daemon 已經寫下的 commit
（`internal/runner` 知道它 fetch 了哪個 ref）——但那要動禁區，所以先用 `rev-parse`。

### 5.4 `KN-06` 的測試

| # | 測試 | 斷言 |
|---|---|---|
| 1 | `test_manifest_asks_only_for_unknown_hashes` | 第二次同 commit → `want` 為空 |
| 2 | `test_a_removed_path_is_tombstoned_at_manifest_time` | J12 的前半，不需要第 ② 步 |
| 3 | `test_an_older_commit_does_not_overwrite_a_newer_one` | 兩個 run 順序顛倒送達 |
| 4 | `test_run_token_cannot_sync_another_projects_repository` | `CROSS_PROJECT_DENIED` |
| 5 | `test_files_over_256_kib_are_skipped_not_fatal` | D88 的不對稱 |
| 6 | `test_over_800_files_refuses_with_a_named_limit` | `KNOWLEDGE_SYNC_TOO_LARGE`，`details.limit="files"` |
| 7 | `test_clioraignore_beats_the_builtin_include_list` | 排除優先 |
| 8 | `test_a_binary_file_is_not_indexed` | NUL byte 偵測 |
| 9 | `test_dotenv_is_never_indexed_even_if_included_by_a_glob` | 敏感檔名的優先序 |
| 10 | `test_sync_rate_limit_returns_429_with_retry_after` | D88 |
| 11 | (Go) `TestSyncSkipsIgnoredPaths` | CLI 端的規則 |
| 12 | (Go) `TestSyncBatchesUnderTheByteCeiling` | 8 MiB 分批 |

## 6. `KN-04`／`KN-05` 的測試重點

| # | 測試 | 斷言 |
|---|---|---|
| 1 | `test_a_ticket_edit_supersedes_the_previous_version` | `v3` 進來 → `v2` 標 `superseded` ＋ 一列 `knowledge_links` |
| 2 | `test_a_superseded_source_is_absent_from_default_retrieval` | 出口條件之一 |
| 3 | `test_conversation_sources_are_keyed_by_conversation_seq` | `CV-03` 的依賴被真的用到 |
| 4 | `test_a_proposal_is_generated_not_accepted` | Agent 產出的 authority |
| 5 | `test_accepting_a_spec_writes_an_accepted_source` | 人的動作才升級 |
| 6 | `test_marking_a_decision_authoritative_needs_project_manage_and_audits` | D45 ＋ audit |
| 7 | `test_authority_in_a_request_body_is_rejected_by_the_schema` | gate 的 pytest 版本 |
| 8 | `test_an_artifact_on_a_failed_report_is_generated_not_verified` | §1 的條件 authority |
| 9 | `test_evidence_items_keep_their_contradiction` | 兩列來源都在，各自有 authority（沿用 `EvidenceItem` 的「Contradictions are stored, not resolved」） |
| 10 | `test_a_binary_artifact_indexes_metadata_only` | §3 |
