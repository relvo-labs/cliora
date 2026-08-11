# 04 — 契約、Central 與 RBAC（`WE-05`、`WE-06`）

---

## 1. 契約 v1.9.0（compatible）

`version` 整數維持 `1`。四對新型別、一個共用定義、兩個新增的 `revision` 欄位、一個回報欄位。

### 1.1 共用定義：`precondition`

新檔 `contracts/v1/schemas/messages/precondition.schema.json`：

```jsonc
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "oneOf": [
    {
      "type": "object", "additionalProperties": false,
      "required": ["absent"],
      "properties": {"absent": {"const": true}}
    },
    {
      "type": "object", "additionalProperties": false,
      "required": ["revision"],
      "properties": {"revision": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}}
    }
  ]
}
```

**會破壞或取代東西的三個**請求型別 `$ref` 它，且都把 `precondition` 放進 `required`。
`filesystem.mkdir` **不** `$ref` 它，也沒有這個欄位 —— 而因為它是
`additionalProperties: false`，送一個 `precondition` 給 mkdir 會被拒。
理由在 `00-…md` D2：`mkdir(2)` 在 syscall 層就不可能覆蓋任何東西，
替它發明一個只有一種合法值的欄位，會讓「每一個破壞性操作都帶前提」這句話
從一條規矩退化成一種格式。

**`oneOf` 而不是兩個可選欄位**：兩個可選欄位會允許「都不帶」與「都帶」兩種狀態，
而那兩種狀態各自需要一段程式碼決定怎麼辦。`oneOf` 讓解碼層就把它們消滅掉，
三個 consumer 一致。

**`absent` 的值固定為 `true`**（`const`）而不是 boolean：`{"absent": false}`
是什麼意思？「這個檔案不應該不存在」？把它變成不可表達，比替它想一個意思好。

### 1.2 四對型別

| 型別 | 方向 | payload |
|---|---|---|
| `filesystem.write` | Central → daemon | `{session_id, path, content, precondition}` |
| `filesystem.written` | daemon → Central | `{path, revision, size, modified_at, old_revision?, trash_path?}` |
| `filesystem.mkdir` | Central → daemon | `{session_id, path}` |
| `filesystem.directory_created` | daemon → Central | `{path, modified_at}` |
| `filesystem.rename` | Central → daemon | `{session_id, from, to, precondition}` |
| `filesystem.renamed` | daemon → Central | `{from, to, kind, revision?, modified_at}` |
| `filesystem.delete` | Central → daemon | `{session_id, path, precondition}` |
| `filesystem.deleted` | daemon → Central | `{path, kind, old_revision, trash_path?, entries?, bytes?}` |

`kind` 是 `"file" | "directory"`，由 daemon 依它實際動到的東西回報 ——
**請求端不說自己以為那是什麼**（那會多出一個「你說是檔案但它是目錄」的分支，
而 `precondition` 的雜湊比對已經涵蓋了這件事，`02-…md` §2.1）。

`entries`／`bytes` 只在刪除目錄時出現，是走訪計數，供 UI 說「已移入回收桶（37 個項目）」。
**刻意不回傳被刪項目的清單**：那是一個大小隨使用者資料成長的回應，
而使用者真正需要知道的是它們去了哪裡（`trash_path`）。

`path`／`from`／`to` 沿用既有的 workspace-relative pattern
（`filesystem-read.schema.json` 那一條：拒絕絕對路徑、`~`、`..` 片段、控制字元）。
**不複製那個 pattern，抽成 `$defs` 讓四個檔案共用** —— 今天它已經在
`filesystem-list`／`filesystem-read`／`filesystem-search` 三處各寫了一次，
本期會變成七處，那是它該被抽出來的門檻。

`content`：`{"type": "string", "maxLength": 2097152}`。

> **`maxLength` 的單位是「字元」不是「位元組」**（JSON Schema 定義為 code point 數）。
> 一個 2 MiB 的 CJK 檔案只有約 70 萬個 code point，所以這個上限**比實際的位元組上限鬆**。
> 這是刻意的：schema 只擋掉離譜的東西，**真正的位元組上限由 daemon 判**
> （`02-…md` §4.1 第 2 步），因為只有它知道 UTF-8 編碼後的長度。
> 這一點要寫進 CHANGELOG，否則下一個人會以為 schema 已經擋住了。

`trash_path` 是選填：hardlink 與複製兩條路都會填，`FILE_TRASH_UNAVAILABLE`
的情況下操作根本沒發生，所以不會有回應。它回給瀏覽器是為了讓「已刪除，
可在回收桶找回」這句話能附上實際路徑。

### 1.3 兩處新增 `revision`

`filesystem.content` 與 `filesystem.entries` 都沒有 JSON schema
（P3 的三個回應型別都沒有，只有 `filesystem.uploaded` 有），
所以這是三個 consumer 的結構變更：

| 回應 | 新欄位 | 用途 |
|---|---|---|
| `filesystem.content` | `revision`（檔案內容雜湊） | 編輯、更名、刪除**檔案**的前提 |
| `filesystem.entries` | `revision`（直屬項目清單的雜湊） | 更名、刪除**目錄**的前提 |

兩者都是**選填**，因為舊 daemon 不會送。前端在缺少它時
**不顯示對應的入口**（而不是送一個空的 precondition）——
「不知道版本」與「版本是空的」是兩件事。

`filesystem.entries` 的 `revision` 有一個要寫進 CHANGELOG 的性質：
**它對分頁不敏感**。daemon 在截斷之前、對完整排序後的清單計算它，
所以同一個目錄的第 1 頁與第 2 頁回傳同一個 revision。
不這樣做的話，「刪除一個大目錄」會依使用者剛好翻到第幾頁而成功或失敗。

### 1.4 `node-register.file_editing`

`node-register.schema.json` 新增 `"file_editing": {"type": "boolean"}`，選填。
**缺席即為否**，與 `image_upload`／`privileged_terminal` 同一條規矩：
沒有人回報過的姿態，不是「未知」。

### 1.5 十個 golden fixture

| Fixture | accept | 釘住什麼 |
|---|---|---|
| `valid/filesystem-write-create.json` | ✓ | `{"absent": true}` 形狀 |
| `valid/filesystem-write-replace.json` | ✓ | `{"revision": "sha256:…"}` 形狀 |
| `valid/filesystem-written.json` | ✓ | 回應含 `old_revision` 與 `trash_path` |
| `invalid/filesystem-write-no-precondition.json` | ✗ | **本期的核心不變量**：沒有前提就沒有寫入 |
| `invalid/filesystem-write-both-preconditions.json` | ✗ | `oneOf` 真的排他 |
| `invalid/filesystem-write-with-force.json` | ✗ | `additionalProperties:false` 擋掉 `force`／`overwrite` |
| `invalid/filesystem-write-bad-revision.json` | ✗ | revision 的 pattern（大寫 hex、長度不對、缺前綴） |
| `invalid/filesystem-rename-absolute-target.json` | ✗ | `to` 也要過 workspace-relative pattern，不只 `from` |
| `valid/filesystem-mkdir.json` | ✓ | 只有 `{session_id, path}` |
| `invalid/filesystem-mkdir-with-precondition.json` | ✗ | **`mkdir` 沒有前提，而且送了會被拒** —— 這一格是 `00-…md` D2 那條例外的證據，沒有它，那條例外只是一段散文 |

`invalid/filesystem-delete-absent-precondition.json` 也要考慮
（`{"absent": true}` 對 delete 在語意上是荒謬的）—— 但它在 **schema 層是合法的**，
因為 `precondition` 是共用定義。**所以這一格由 daemon 拒絕，不由 schema 拒絕**
（`02-…md` §4.3 第 2 步），fixture 放在 Go 的整合測試而不是 golden fixtures，
manifest 不收。這個分工要寫進 CHANGELOG：
**schema 管形狀，daemon 管語意**，把語意塞進 schema 會讓共用定義長出 `if/then`。

### 1.6 `LARGE_FRAME_TYPES`

`filesystem.write` 加入三個 consumer 的大訊框名單。
`02-…md` §7 的那段推導（為什麼 2 MiB 內容在 8 MiB 訊框內綽綽有餘）
要原文寫進 `contracts/CHANGELOG.md`。

---

## 2. Central

### 2.1 五個 HTTP 端點

全部掛在既有的 `router = APIRouter(prefix="/api/sessions/{session_id}/files")`。

| Method | Path | Precondition header | 成功 |
|---|---|---|---|
| `PUT` | `/content?path=` | `If-None-Match: *`（建立）／`If-Match: "sha256:…"`（覆寫） | 201／200 |
| `POST` | `/directories?path=` | **不接受**（帶了回 400） | 201 |
| `DELETE` | `/entry?path=` | `If-Match: "sha256:…"` | 204 |
| `POST` | `/rename` | `If-Match: "sha256:…"` | 200 |
| `GET` | `/content?path=` | — | 既有，回應多一個 `revision` 與 `ETag` |
| `GET` | `/tree?path=` | — | 既有，回應多一個 `revision` |

三個命名決定要寫下來：

1. **刪除的路徑是 `/entry` 而不是 `/content`。** 目錄沒有 content，
   而 `DELETE /content?path=<一個資料夾>` 讀起來像是在清空它而不是移除它。
   `/content` 保留給「這個路徑的位元組」（GET／PUT），
   `/entry` 是「檔案樹上的這一列」（DELETE），`/rename` 兩者皆可。
2. **`POST /directories` 而不是 `PUT /directories?path=` 加 `If-None-Match: *`。**
   後者比較整齊，但它會讓 precondition helper 多出一條「這個端點的前提永遠是同一個值」
   的分支，而那正是 `00-…md` D2 想避免的形式主義。mkdir 不帶前提，
   帶了就是 400 —— 那個 400 是規矩的證據。
3. **沒有 `DELETE /directories`。** 一個路徑一個刪除端點，型別由節點認定。
   兩個端點會讓「客戶端以為那是資料夾但它是檔案」變成一個要處理的分支。

`PUT /content` 的 body 是**原始文字**（`Content-Type: text/plain; charset=utf-8`），
不是 JSON 包裝。理由與 `/images` 相同（`files.py` 現有註解）：一個只帶一樣東西的請求，
不需要一個解析器；也不需要 `python-multipart`。

`POST /rename` 的 body 是 `{"from": "...", "to": "..."}`（JSON），
因為它帶兩個路徑而路徑不適合放在 query string 裡（長度與逃脫）。

### 2.2 Precondition header 的處理

一個共用的 helper，需要前提的三個端點只有它一個入口：

```python
def _precondition(request: Request) -> dict[str, Any]:
    """Translate If-Match / If-None-Match into the wire precondition.

    Exactly one must be present. A missing precondition is 428 rather than a
    default, because the default would have to be "overwrite whatever is there"
    — the one behaviour ADR 0025 removed from the wire.
    """
```

| 情況 | 回應 |
|---|---|
| 兩個都缺 | `428 PRECONDITION_REQUIRED` |
| 兩個都有 | `400 FILE_INVALID_PRECONDITION` |
| `If-None-Match` 不是 `*` | `400 FILE_INVALID_PRECONDITION`（不支援 etag list） |
| `If-Match` 不符 `^"sha256:[0-9a-f]{64}"$`（含引號） | `400 FILE_INVALID_PRECONDITION` |
| daemon 回 `FILE_REVISION_MISMATCH` | `412 PRECONDITION_FAILED` |
| daemon 回 `FILE_EXISTS` | `409 CONFLICT` |
| `POST /directories` 帶了任一個前提 header | `400 FILE_INVALID_PRECONDITION` |

`If-Match` 的值**帶雙引號**（HTTP 的 ETag 語法），helper 負責脫掉。
`GET /content` 與 `GET /tree` 的回應都要一併帶 `ETag: "sha256:…"` header ——
那樣前端拿到的東西與它要送回去的東西是同一個字串，不需要自己組。
（`/tree` 的 ETag 是那個目錄的 revision，不是這一頁的。）

### 2.3 授權與 scope

新增 `authz.may_write_files` ／ `authz.authorize_file_write`，
形狀完全比照 `may_upload_files`／`authorize_file_upload`：

```python
def may_write_files(user: User, session: TerminalSession) -> bool:
    """Whether this user may create, edit, rename or delete in the workspace.

    Scoped exactly like browsing — a shell session is never a route to the
    workspace — but gated on `file.write`, which Viewer does not hold
    (ADR 0025 §1.3). It deliberately does NOT check the terminal write lock:
    single-writer is a property of the terminal, not of the workspace.
    """
    if is_shell(session):
        return False
    return has_action(user, FILE_WRITE) and may_view_session(user, session)
```

`FileRelayService` 新增 `_resolve_for_write`，與 `_resolve_for_upload` 並列
（**不參數化**，理由沿用現有註解：兩個檢查都不能靠傳錯參數到達）。

`session_capabilities` 新增 `"can_edit_files": may_write_files(user, session)`。
`test_permission_matrix.py` 的三重檢查會強制 `ACTION_FILE_WRITE` 同步出現在
`frontend/src/api/dto.ts`。

### 2.4 RBAC

`rbac.py` 新增 `FILE_WRITE = "file.write"`，加入 `_DEVELOPER_ACTIONS`
（Admin 由既有的全集涵蓋）。註解要寫清楚它為什麼不是既有的任何一個
（`00-…md` D9 的三條「被否決」）。

### 2.5 稽核

`audit.py` 新增四個 action 常數並加入既有的白名單集合：

| Action | metadata |
|---|---|
| `file.create` | `path`, `kind`, `bytes`?, `revision`? |
| `file.edit` | `path`, `bytes`, `old_revision`, `revision` |
| `file.rename` | `from`, `to`, `kind`, `revision`? |
| `file.delete` | `path`, `kind`, `old_revision`?, `trash_path`, `entries`?, `bytes`? |

`kind` 是 `"file" | "directory"`。**建立資料夾用 `file.create` 加一個 `kind`，
不是第五個 action** —— 那是同一個動詞的兩種對象，而稽核查詢的形狀是
「這個人做過什麼」與「這個檔案被誰動過」，兩者都不需要在 action 層分開。
刪除一個資料夾則要帶 `entries`：稽核裡的「刪了 1 個東西」與「刪了 340 個東西」
必須看得出來，否則這條紀錄回答不了它存在的問題。

**四個而不是一個帶 `verb` 欄位的事件**：稽核查詢的形狀是
「這個人做過什麼」與「這個檔案被誰動過」，前者要能按 action 篩。
一個 `file.write` 帶 `verb: delete` 會讓「找出所有刪除」變成 metadata 查詢，
而 metadata 是 JSON 欄位。

失敗時的處置沿用 `_audit_upload` 的既有取捨：稽核寫入失敗**不讓使用者的請求失敗**
（節點上的寫入已經發生，讓請求失敗不會把它變回去），計數 + log。
`FILESYSTEM_AUDIT_ERROR_TOTAL` 的 `action` label 多四個值。

> **有一個地方要與 upload 不同**：`file.delete` 的稽核失敗比較嚴重，
> 因為刪除是唯一「東西不見了」的操作，而稽核是「誰弄的」唯一紀錄。
> 但處置仍然一樣（不失敗請求），理由也一樣。差別在於 log level：
> `file.delete` 的稽核失敗用 `log.error` 而不是 `log.warning`。

### 2.6 錯誤碼

`docs/error-catalog.md` 新增九列（欄位沿用既有表格）：

| Code | HTTP | 使用者看到 | 下一步 |
|---|---|---|---|
| `FILE_REVISION_MISMATCH` | 412 | 這個檔案已在節點上被修改 | 重新載入，或另存為新檔 |
| `FILE_EXISTS` | 409 | 同名的檔案已經存在 | 換一個名字 |
| `FILE_IS_DIRECTORY` | 409 | 這是一個目錄，不能寫入內容 | （前端 bug，使用者不該看到） |
| `FILE_DIRECTORY_CONTAINS_PROTECTED` | 409 | 這個資料夾裡有不能被平台改動的項目 | 訊息要指出**第一個**是哪一個（例如 `sub/.git`），使用者才知道下一步 |
| `FILE_DIRECTORY_TOO_LARGE` | 409 | 這個資料夾太大，無法從瀏覽器操作 | 請在節點上以終端機處理 |
| `FILE_CONTENT_NOT_TEXT` | 415 | 內容不是可儲存的 UTF-8 文字 | （通常是貼上了二進位內容） |
| `FILE_WRITE_TOO_LARGE` | 413 | 檔案超過 2 MiB 上限 | 請在節點上以終端機編輯 |
| `FILE_WRITE_QUOTA_EXCEEDED` | 429 | 今天的寫入次數已達上限 | 請稍後再試或聯絡管理者 |
| `FILE_WRITE_DISABLED` | 403 | 這個節點停用了檔案編輯 | 節點擁有者控制此設定 |
| `FILE_TRASH_UNAVAILABLE` | 507 | 無法建立備份，因此拒絕刪除 | 請在節點上以終端機刪除 |
| `FILE_WRITE_FAILED` | 502 | 節點寫入失敗 | 請通知管理者檢查節點磁碟 |
| `FILE_INVALID_PRECONDITION` | 400 | 請求缺少或帶了無效的版本前提 | （前端 bug，使用者不該看到） |
| `PRECONDITION_REQUIRED` | 428 | 同上 | 同上 |

前九個要進 wire 的錯誤碼列舉（daemon 會送）；後三個是 Central-only。
`_map_error` 要把前七個逐一對應，**不可以讓它們塌成 `INTERNAL_ERROR`** ——
p13 的差異表第 6 項就是被這件事抓到的，這次先寫進計畫。

`FILE_TRASH_UNAVAILABLE` 用 507（Insufficient Storage）而不是 500：
它描述的是節點的儲存狀況，不是平台壞了。

### 2.7 Metrics

- `FILESYSTEM_REQUEST_TOTAL` 的 `op` label 新增 `write`／`mkdir`／`rename`／`delete`。
- 新增 `FILESYSTEM_WRITE_BYTES`（histogram，無 label —— **不要加 path 或副檔名**）。
- 新增 `FILESYSTEM_TRASH_BYTES`（daemon 端，label `mode: rename|link|copy`）。
- 新增 `FILESYSTEM_DIRECTORY_ENTRIES`（daemon 端 histogram，目錄操作走訪到的項目數）。
  它是「使用者實際上都在刪多大的東西」的唯一觀測點，也是日後調整
  `max_directory_entries` 的依據。

### 2.8 Migrations

| Migration | 內容 |
|---|---|
| `0020_node_file_editing` | `nodes.file_editing BOOLEAN NOT NULL DEFAULT false`。**預設 false** —— 這是 DB 的欄位預設，代表「還沒回報過」，與節點設定的預設 `true` 是兩回事，沿用 `0018` 的既有做法 |
| `0021_seed_file_write_action` | 把 `file.write` 加進 Admin 與 Developer 的 `roles.permissions.actions` |

`0021` 走 `seed-migration` skill 的既有體例。**這一張不能忘**：
p13 的差異表第 4 項記錄了同一個坑 —— RBAC 的真相有兩處（程式碼的 `ROLE_ACTIONS`
與 DB 的 `roles.permissions`），只改前者會讓 Developer 收到 403。

### 2.9 節點註冊

`node.register` 的處理要把 `file_editing` 寫進 `nodes` 表，與 `image_upload` 並列；
`NodeDetail` 的回應帶出來，`NodeDetailPosture` 的畫面多一列。

---

## 3. 前端 API client（`frontend/src/api/client.ts`）

四個方法，沿用既有的 `ApiError` 與 `signal` 體例：

```ts
readFileContent(...)                          // 既有；回傳型別多一個 revision
listFileTree(...)                             // 既有；回傳型別多一個 revision
writeFileContent(sessionId, path, content, precondition, opts)
createDirectory(sessionId, path, opts)        // 沒有 precondition 參數
renameEntry(sessionId, from, to, revision, opts)
deleteEntry(sessionId, path, revision, opts)
```

`precondition` 的型別是 `{ absent: true } | { revision: string }` ——
在 TypeScript 這一層就讓它是 union，前端不可能送出「兩個都有」或「都沒有」。
client 內部把它翻成 `If-Match`／`If-None-Match`，**這個翻譯只有一個地方**。

`createDirectory` **沒有** precondition 參數，`renameEntry`／`deleteEntry`
的 `revision` 是**必填**（不是 `string | undefined`）。
型別系統擋掉的東西，測試就不必再擋一次。

---

## 4. Central 測試（`pytest`）

| 檔案 | 測什麼 |
|---|---|
| `tests/db/test_files_write_api.py` | 五個端點的成功路徑；428／412／409／415／413 各一；`POST /directories` 帶前提 header 回 400；`ETag` 在兩個 GET 回應上；`If-Match` 帶不帶引號的處理（**帶引號是規範，不帶是常見的客戶端錯誤 —— 我們選擇嚴格，並用測試釘住這個選擇**） |
| `tests/db/test_files_directory_api.py` | 刪除資料夾的成功與兩種拒絕（含受保護項目、超過上限）；回應帶 `entries`／`bytes`；稽核的 `kind` 與 `entries` |
| `tests/db/test_rbac.py` | Viewer 對五個端點都 403；Developer／Admin 200；shell session 403；`can_edit_files` 出現在 capabilities |
| `tests/db/test_audit.py` | 四個事件各一筆；metadata 不含內容；`file.delete` 的稽核失敗用 error level |
| `tests/test_scope_guards.py` | `filesystem.write`／`rename`／`delete` 的 schema 不得含 `force`／`overwrite`／`recursive`，且 `precondition` 必填；`filesystem.mkdir` **不得有** `precondition` |
| `tests/test_protocol_codec.py` | `filesystem.write` 在 `LARGE_FRAME_TYPES` 內；另七個型別不在 |
| `tests/db/test_migrations.py` | `0020`／`0021` up／down |
| `tests/db/test_permission_matrix.py` | 既有三重檢查涵蓋 `file.write`（不需新增測試，但要確認它真的紅過一次） |
