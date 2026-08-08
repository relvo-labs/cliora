# 03 — 契約與 Central（`FU-04`、`FU-05`）

---

## 1. 契約 v1.9.0（compatible）

`version` 整數維持 `1`。**一對新型別、一個回報欄位。** 沒有共用定義要新增，
沒有既有型別要改，沒有訊框上限要動。

### 1.1 一對型別

| 型別 | 方向 | payload |
|---|---|---|
| `filesystem.store` | Central → daemon | `{session_id, directory, filename, data}` |
| `filesystem.stored` | daemon → Central | `{path, size, modified_at}` |

**沒有** `overwrite`、`mode`、`mime`、`precondition`、`revision`、`recursive`
這些欄位，`additionalProperties: false`。

- **沒有 `overwrite`**：落地一律 `O_EXCL`（`00-…md` D2）。
  這個欄位不存在，就沒有一段程式碼需要決定什麼時候可以信任它。
- **沒有 `mode`**：落地一律 `0644`（`00-…md` D6）。
- **沒有 `mime`**：沿用 ADR 0024 §3 的理由 —— 一旦欄位存在，
  就會有人問它能不能被信任。而本期根本不做型別判定（`02-…md` §2.1）。
- **沒有 `precondition`／`revision`**：那是 `plan/14` 為覆寫設計的機制。
  本期不覆寫，所以它們不該出現在 wire 上，而 `GATE-FU-NO-OVERWRITE` 會 grep 它們。

### 1.2 `directory` 與 `filename` 是兩個欄位，不是一個 `path`

```jsonc
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object", "additionalProperties": false,
  "required": ["session_id", "directory", "filename", "data"],
  "properties": {
    "session_id": {"type": "string", "format": "uuid"},
    "directory": {
      "type": "string", "minLength": 1, "maxLength": 4096,
      "$comment": "workspace-relative; '.' is the workspace root",
      "pattern": "^(?![/~])(?!.*(?:^|/)\\.\\.(?:/|$))[^\\u0000-\\u001f]+$"
    },
    "filename": {
      "type": "string", "minLength": 1, "maxLength": 255,
      "$comment": "one path segment: no separator, not . or .., no control chars",
      "pattern": "^(?!\\.{1,2}$)[^/\\u0000-\\u001f]+$"
    },
    "data": {
      "type": "string", "minLength": 1, "maxLength": 5592408,
      "pattern": "^[A-Za-z0-9+/]+={0,2}$"
    }
  }
}
```

**為什麼拆成兩個欄位，這是本型別唯一的設計決定：**

一個 `path` 欄位需要一段驗證程式碼去確認「最後一個片段就是使用者打的那個名字」，
而路徑穿越正是從那段程式碼的漏洞長出來的。兩個欄位讓
**「檔名裡有一個斜線」在 wire 上不可表達** —— schema 的 pattern 直接排除 `/`，
三個 consumer 一致。這是 ADR 0024「把入口關掉就沒有驗證程式碼會寫錯」
同一個手法，只是這次關的入口比較小。

`data` 的上限 `5592408` 是 4 MiB base64 之後的長度，與 `filesystem.upload`
用的是同一個數字（`00-…md` D3）。**沿用而不是重算**：兩個型別共用同一個
單檔上限設定鍵，wire 上的數字也要一樣，否則有一天它們會分岔。

`directory` 允許 `"."`（工作區根目錄是合法的落地位置，`02-…md` §2 第 7 列）。

### 1.3 `filesystem.stored`

```jsonc
{
  "required": ["path", "size", "modified_at"],
  "properties": {
    "path": {"type": "string", "minLength": 1, "maxLength": 4096,
             "pattern": "^(?![/~])(?!.*(?:^|/)\\.\\.(?:/|$))[^\\u0000-\\u001f]+$"},
    "size": {"type": "integer", "minimum": 0, "maximum": 4194304},
    "modified_at": {"type": "string",
                    "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\\.[0-9]{1,6})?Z$"}
  }
}
```

`size` 的 `minimum` 是 **0** 而不是 1：一個空檔案是合法的上傳
（`touch` 出來的佔位檔、空的 `__init__.py`）。
`filesystem.uploaded`（圖片）的 `minimum` 是 1，因為零位元組的圖片不存在 ——
兩個型別在這一格刻意不同，要在 CHANGELOG 寫一句，否則會被當成筆誤。

> **注意 `data` 的 `minLength` 是 1**（base64 至少一個字元），
> 但空檔案的 base64 是空字串。所以**空檔案在 wire 上要怎麼表達？**
> 兩個選項：`data` 允許 `minLength: 0`，或前端不允許上傳空檔案。
> 選前者 —— `"data": ""` 是空內容的自然表達，而拒絕空檔案是一條使用者無法理解的規則。
> `minLength` 因此是 **0**，並且 pattern 要改成 `^([A-Za-z0-9+/]+={0,2})?$`。
> 這一格是 `FU-01` 第 4 項要驗的（三個 consumer 對空字串的處理）。

### 1.4 `node-register.file_upload`

`node-register.schema.json` 新增 `"file_upload": {"type": "boolean"}`，選填。
**缺席即為否**，與 `image_upload`／`privileged_terminal` 同一條規矩：
沒有人回報過的姿態，不是「未知」。

與 `image_upload` **並列而不是取代**（`00-…md` D7）。
一個節點可能回報 `image_upload: true, file_upload: false`。

### 1.5 六個 golden fixture

| Fixture | accept | 釘住什麼 |
|---|---|---|
| `valid/filesystem-store.json` | ✓ | 四個欄位的形狀 |
| `valid/filesystem-store-root.json` | ✓ | `directory: "."` 合法 |
| `valid/filesystem-stored.json` | ✓ | 回應形狀，含 `size: 0` |
| `invalid/filesystem-store-filename-with-slash.json` | ✗ | **本型別的核心不變量**：檔名不是路徑 |
| `invalid/filesystem-store-with-overwrite.json` | ✗ | `additionalProperties:false` 擋掉 `overwrite`／`mode`／`mime` |
| `invalid/filesystem-store-parent-escape.json` | ✗ | `directory` 的 `..` 片段 |

加進 `manifest.json`。`node-register.file_upload` 的有效與非布林各一個 fixture
（沿用 `node-register-image-upload-non-boolean.json` 的形狀）。

**既有的 `filesystem.upload` 五個 invalid fixture 一個都不動** ——
它們釘的是「請求端不得命名」，而那條規矩在圖片投放上仍然成立（`00-…md` D10）。
本期新增的兩條路徑並存，`FU-04` 的驗收之一就是舊 fixture 全綠且未被修改。

### 1.6 CHANGELOG 要寫的四件事

1. **兩個上傳型別並存，各自的規矩各自成立。** `filesystem.upload`
   不接受任何命名欄位（截圖不需要名字）；`filesystem.store` 要求
   `directory` 與 `filename`（`requirements.txt` 的名字就是它的全部意義）。
   引用 ADR 0024 §4 的兩個警告。
2. **`filename` 拆成獨立欄位是安全控制而不是整齊。** §1.2 那段推導。
3. **訊框上限沒有變。** 4 MiB → base64 5.33 MiB → 在既有 8 MiB 之內。
   ADR 0024 §7 已經為圖片付過那次代價，本期不再付。
4. **`filesystem.stored.size` 的 `minimum` 是 0，`filesystem.uploaded` 是 1。**
   刻意不同，見 §1.3。

---

## 2. Central

### 2.1 一個 HTTP 端點

掛在既有的 `router = APIRouter(prefix="/api/sessions/{session_id}/files")`：

```
POST /api/sessions/{session_id}/files/upload
     ?directory=<url-encoded workspace-relative path>
     &filename=<url-encoded single segment>
Content-Type: application/octet-stream
body: 原始位元組
→ 201 {"path": "...", "size": 1234, "modified_at": "..."}
```

**為什麼是 query param ＋ 原始 body 而不是 multipart：**
沿用 `/images` 已經立下的體例（`files.py` 現有註解）——
一個只帶一樣東西的請求不需要一個解析器，也不需要把 `python-multipart`
放進相依清單。檔名的非 ASCII 字元由 URL 編碼處理，
而那是 `FU-01` 第 2 項要實測的一格。

**路徑是 `/upload` 而不是 `/files`**：`/files` 是 prefix 本身。
不用 `/content`（那是預覽的 GET），不用 `/images`（那是圖片投放）。

### 2.2 邊界檢查

`files.py` 的處理順序（沿用 `upload_image` 的形狀）：

| # | 檢查 | 回應 |
|---|---|---|
| 1 | `Content-Type` 是 `application/octet-stream`（或缺省時放行） | 415 `FILE_UPLOAD_UNSUPPORTED_TYPE` |
| 2 | `directory` 過 `_reject_rel_path(allow_empty=True)` | 400 `FILE_INVALID_PATH` |
| 3 | `filename` 過一個新的 `_reject_filename()`：長度 1–255、不含 `/`、不是 `.`／`..`、無控制字元 | 400 `FILE_INVALID_NAME` |
| 4 | `Content-Length` 宣告 > 4 MiB | 413 `FILE_UPLOAD_TOO_LARGE` |
| 5 | 串流讀取並累計，超過 4 MiB 立刻中止 | 413 `FILE_UPLOAD_TOO_LARGE` |
| 6 | relay `filesystem.store`，等 `filesystem.stored` | 見 §2.4 |

第 4／5 步是 `upload_image` 既有的兩段式檢查，**直接沿用同一段程式碼** ——
抽出一個 `_read_bounded_body(request, limit)`，兩個端點共用。
這是本期唯一一處對既有程式碼的重構，而它不改變 `/images` 的行為
（要有測試斷言這件事）。

**沒有 magic-number 預檢**（`/images` 有）：本期不限制型別（`02-…md` §2.1）。

`_reject_filename()` 是新的，而它與 daemon 的第 1 條檢查是**故意重複**的
（defence in depth，`SEC-001` 的既有體例）：Central 擋是為了不佔用節點連線，
權威判定在 daemon。

### 2.3 授權與 scope

**沿用 `authz.may_upload_files` / `authorize_file_upload`，一行都不改**
（`00-…md` D8）。它已經：

- 要求 `file.upload`（Viewer 不持有）
- 用 `may_view_session` 做 resource scope
- 拒絕 shell session（工作區屬於 CLI session）

`session_capabilities` 的 `can_upload_files` 也沿用 —— 前端用同一個旗標
判斷要不要顯示上傳入口。**不新增 `can_store_files`**：
兩條路徑同一個權限，兩個旗標會讓前端有一天顯示不一致的入口。

> **要注意的一件事**：前端顯示上傳入口的條件是
> `can_upload_files && node.file_upload`（而圖片投放是
> `can_upload_files && node.image_upload`）。同一個權限、兩個節點旗標 ——
> 這個組合要在 `04-…md` §3 寫清楚，並各有一條測試。

### 2.4 錯誤對應

`FileRelayService._map_error` 的 `_UPLOAD_ERROR_STATUS` 表新增三列
（既有五列不動）：

| daemon code | HTTP | 使用者看到 |
|---|---|---|
| `FILE_EXISTS` | 409 | 這個目錄裡已經有同名的檔案 |
| `FILE_UPLOAD_NO_SPACE` | 507 | 節點的磁碟空間不足 |
| `FILE_DENIED`（帶 reason） | 403 | 依 reason 分（`04-…md` §2.3） |

`FILE_UPLOAD_TOO_LARGE`／`QUOTA_EXCEEDED`／`FAILED`／`DISABLED`
**沿用既有對應**（413／429／502／403）。

`FILE_UPLOAD_NO_SPACE` 用 507（Insufficient Storage）而不是 500：
它描述的是節點的儲存狀況，不是平台壞了。與 `plan/14` 對
`FILE_TRASH_UNAVAILABLE` 的選擇同一個理由。

`docs/error-catalog.md` 新增三列（`FILE_EXISTS`、`FILE_UPLOAD_NO_SPACE`、
`FILE_INVALID_NAME`），欄位沿用既有表格。

### 2.5 稽核

**沿用 `audit.FILE_UPLOAD`，不新增事件**（`00-…md` D8）。
`_audit_upload` 的 metadata 從

```python
{"path": ..., "mime": ..., "bytes": ...}
```

在本條路徑上改為

```python
{"path": ..., "bytes": ..., "source": "file"}
```

- **沒有 `mime`**：本期不判定型別。
- **新增 `source`**：`"image"`（圖片投放）或 `"file"`（本期）。
  一個欄位讓稽核查詢分得出兩條路徑，而不需要第二個 action key。
  圖片投放那一邊也要補上 `source: "image"` —— 這是本期**唯一**允許動到
  圖片投放程式碼的地方（`00-…md` D10 的「往下共用」），而且它只是加一個常數。
- `path` 的性質變了：ADR 0024 D11 說相對路徑可以記，因為**那是平台自己取的名字**。
  本期的路徑是**使用者選的**，而它仍然可以記 —— 理由不同但同樣成立：
  使用者本來就看得到那個路徑（他剛剛在檔案樹上選了它），
  而不記路徑的話 W3 要回答的「誰放了什麼進來」就只剩一個計數器。
  **這一段推導要寫進 ADR 0026**，因為它與 ADR 0024 的理由不同。

失敗時的處置沿用既有取捨：稽核寫入失敗不讓使用者的請求失敗
（節點上的寫入已經發生），計數 ＋ log。

### 2.6 Metrics

- `FILESYSTEM_REQUEST_TOTAL` 的 `op` label 新增 `store`。
- `FILESYSTEM_UPLOAD_BYTES` **沿用**，但 label 從 `mime` 改為
  `source`（`image`／`file`）—— 本期沒有 mime 可以標，
  而保留一個永遠是空字串的 label 比改掉它糟。
  **這是一個既有 metric 的 label 變更**，要寫進 release note 的
  observability 段（既有的 dashboard 會斷）。
- **新增 `FILESYSTEM_STORE_REFUSED_TOTAL`**，label `code`。
  它存在的唯一理由是 `00-…md` D3 的觸發條件：
  `FILE_UPLOAD_TOO_LARGE` 佔上傳嘗試 >10% 時才考慮分塊上傳。
  沒有這個 metric，那個決定就只能靠猜。

### 2.7 Migration

| Migration | 內容 |
|---|---|
| `0020_node_file_upload` | `nodes.file_upload BOOLEAN NOT NULL DEFAULT false`。**預設 false** 是 DB 欄位預設，代表「還沒回報過」，與節點設定的預設 `true` 是兩回事 —— 沿用 `0018_node_image_upload` 的既有做法 |

**沒有 seed migration**（沒有新的 RBAC action，`00-…md` D8）。
這是本期與 `plan/14` 在 migration 上的差別：一張 vs 兩張。

`node.register` 的處理要把 `file_upload` 寫進 `nodes`，與 `image_upload` 並列；
`NodeDetail` 帶出來，`NodeDetailPosture` 的畫面多一列。

---

## 3. 前端 API client

```ts
// frontend/src/api/client.ts — 既有的 uploadImage 不動
uploadFile(
  sessionId: string,
  directory: string,
  filename: string,
  file: File,
  onProgress: (fraction: number) => void,
  signal: AbortSignal,
): Promise<FileStoreResult>
```

`uploadImage` 已經用 `XMLHttpRequest` 取上傳進度（`fetch` 沒有上傳進度）。
**把那段抽成 `uploadWithProgress(url, contentType, body, onProgress, signal)`
給兩個方法共用** —— 這是本期第二處（也是最後一處）對既有程式碼的重構，
同樣要有測試斷言 `uploadImage` 的行為不變。

`dto.ts` 新增：

```ts
export interface FileStoreResult {
  path: string;
  size: number;
  modified_at: string;
}
```

`SessionCapabilities` 不動（沿用 `can_upload_files`）；
`NodeDetail` 新增 `file_upload?: boolean`。

---

## 4. Central 測試（`pytest`）

| 檔案 | 測什麼 |
|---|---|
| `tests/db/test_files_store_api.py` | 成功路徑回 201 與 `path`；`directory` 的四種非法寫法（絕對、`~`、`..`、控制字元）；`filename` 的五種（含 `/`、`.`、`..`、空、256 位元組）；`Content-Length` 說謊時串流累積仍中止；4 MiB+1 被拒；`FILE_EXISTS` → 409；`FILE_UPLOAD_NO_SPACE` → 507；空檔案（0 位元組）成功 |
| `tests/db/test_files_upload_api.py` | **既有測試全綠且未修改**，加一條斷言 `_read_bounded_body` 抽出後 `/images` 行為不變（`00-…md` D10） |
| `tests/db/test_rbac.py` | Viewer 對 `/upload` 403；Developer／Admin 201；shell session 403 |
| `tests/db/test_audit.py` | 成功留一筆 `file.upload` 且 `source: "file"`、有 `path` 與 `bytes`、**沒有內容**；圖片那一條的 `source: "image"` |
| `tests/test_scope_guards.py` | `filesystem.store` 的 schema 不得含 `overwrite`／`mode`／`mime`／`precondition`／`revision`；`filename` 的 pattern 拒絕 `/` |
| `tests/test_protocol_codec.py` | `filesystem.store` 在 `LARGE_FRAME_TYPES` 內；`filesystem.stored` 不在；**`MAX_FILE_PAYLOAD` 仍是 8 MiB** |
| `tests/db/test_migrations.py` | `0020` up／down |
