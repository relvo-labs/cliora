# 04 — 契約 v1.8.0、Central、RBAC 與稽核（`WF-05`、`WF-06`）

---

## 1. 契約 v1.8.0（compatible）— `WF-05`

`version` 整數維持 `1`。新增兩個型別、一個回報欄位、四個 golden invalid fixture。

### 1.1 `filesystem.upload`（Central → daemon）

`contracts/v1/schemas/messages/filesystem-upload.schema.json`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object", "additionalProperties": false,
  "required": ["session_id", "data"],
  "properties": {
    "session_id": {"type": "string", "format": "uuid"},
    "data": {"type": "string", "minLength": 4, "maxLength": 5592408,
             "pattern": "^[A-Za-z0-9+/]+={0,2}$"}
  }
}
```

**兩個欄位，就這樣。** 沒有 `filename`、沒有 `path`、沒有 `directory`、
沒有 `extension`、沒有 `mime`、沒有 `overwrite`。這是 `00-…md` D2 的 wire 形狀，
也是 1.4.0／1.6.0／1.7.0 那條「不讓對面命名」規則在檔案面的延續。

- `mime` **不放進來**，即使它看起來只是個提示：一旦有這個欄位，
  下一個人會問「那能不能相信它以省掉嗅探」，而那個問題不應該存在。
  daemon 嗅探的結果由 `filesystem.uploaded` 回報。
- `maxLength` 5592408 是 4 MiB 的 base64 長度（`ceil(4194304/3)*4`）。
  在 schema 上釘住，代表一個過大的請求在**解碼之前**就被拒絕。
- `pattern` 排除換行與 URL-safe 變體，與 daemon 端的 `StdEncoding.Strict()` 一致。

### 1.2 `filesystem.uploaded`（daemon → Central）

payload：`{path, mime, size, modified_at}`。
`path` 是工作區相對路徑，`mime` 是四個固定值之一，`size` 是原始位元組數。

**`filesystem.upload` 要加進 `LargeFrameTypes` / `LARGE_FRAME_TYPES`，
`filesystem.uploaded` 不要。** 這是 1.3.1 那個名單第一次收進**請求**型別，
而且方向是 Central→daemon，所以三份 codec 的註解都要把理由寫上去
（`daemon/internal/protocol/codec.go:25`、`backend/app/protocol/codec.py:23`、
`frontend/src/protocol/decode.ts`）。理由是：對面是已認證的 Central，
且 daemon 在解碼後立刻檢查型別與大小。

前端**不是**這兩個型別的生產者或消費者（圖片走 HTTP），
但 TypeScript decoder 仍要驗證它們 —— 沿用 1.6.0 對 tunnel 訊框的同一個理由：
「一個被接受卻不檢查的型別，就是一個會轉送畸形資料的型別」。

### 1.3 `node-register.image_upload`

`node-register.schema.json` 新增一個選用布林，與 1.7.0 的 `privileged_terminal` 並列。
缺項讀作 `false`（舊 daemon 沒有這個能力）。**絕不是「未知」** —— 
沒有人回報過的能力，主控台不得推測。

### 1.4 四個 golden invalid fixture

| 檔案 | 內容 | 為什麼 |
|---|---|---|
| `invalid/filesystem-upload-with-filename.json` | 夾帶 `filename: "x.png"` | D2 的主防線 |
| `invalid/filesystem-upload-with-path.json` | 夾帶 `path: "../../etc/x.png"` | 路徑穿越的形狀，即使 daemon 會擋，wire 也要擋 |
| `invalid/filesystem-upload-non-base64.json` | `data` 含 `\n` 與 `-_` | 嚴格 base64 |
| `invalid/filesystem-upload-oversize.json` | `data` 超過 `maxLength` | 解碼前拒絕 |

三個 consumer（Python schema、Go、TypeScript）必須**一致拒絕**這四個，
`make contract` 涵蓋。另外 `backend/tests/test_scope_guards.py` 擴充一條：
`filesystem.upload` 的 schema 不得包含任何命名類欄位（以 property 名稱的 deny-list 檢查），
與既有的「`session.start` 不得有 argv 類欄位」同一個守門形狀。

### 1.5 `contracts/CHANGELOG.md`

寫一段 1.8.0，重點四句：
(a) 兩個新型別、一個回報欄位；
(b) **請求不得命名檔案** —— 這是本版的全部重點，四個 fixture 釘住它；
(c) `filesystem.upload` 是第一個進入 8 MiB 名單的請求型別，代價寫明；
(d) `image_upload` 缺項是「否」，不是「未知」。

---

## 2. Central — `WF-06`

### 2.1 HTTP 端點

```text
POST /api/sessions/{session_id}/files/images
Content-Type: image/png | image/jpeg | image/gif | image/webp
Body: raw bytes
→ 200 {"path": ".cliora/uploads/2026-08-05/01K….png",
        "mime": "image/png", "size": 20481, "modified_at": "…Z"}
```

放在既有的 `backend/app/api/http/files.py`（`prefix="/api/sessions/{session_id}/files"`）。

- **不用 multipart。** `UploadFile` 需要 `python-multipart`，那是一個新的相依
  與一個新的解析攻擊面，而我們只需要一個檔案、而且不需要它的檔名（D2）。
  raw body 少一層解析，也少一個依賴。
- **不先讀完再檢查。** 先看 `Content-Length`：缺少或超過 4 MiB → 413 `FILE_UPLOAD_TOO_LARGE`。
  再以 `request.stream()` 累積，累積量超過上限即中止並回同一個錯誤
  （宣告的長度可以說謊）。
- `Content-Type` 不在四種之內 → 415 `FILE_UPLOAD_UNSUPPORTED_TYPE`。
  這是**便宜的預檢，不是判定**；權威判定在 daemon（`03-…md` §3 第 3 步）。
  Central 另外檢查前 12 個位元組的 magic number，這樣一個明顯不是圖片的請求
  不會佔用節點連線 —— 但兩邊的清單只有一份，寫在 `backend/app/services/files.py`
  與 daemon 的 `upload.go`，並由契約的 `mime` enum 綁在一起。
- 通過後 base64、組 `filesystem.upload`、走既有的 request-correlation relay
  （逾時 20 秒，比 read 的 15 秒長一點，因為要寫磁碟）。
- **不落地**（D18）：不寫暫存檔、不寫 DB、不進 log、不進 metrics label。
  函式結束後緩衝區就丟掉。

### 2.2 RBAC

`backend/app/services/rbac.py`：

```python
FILE_UPLOAD = "file.upload"
_DEVELOPER_ACTIONS = _VIEWER_ACTIONS | {..., FILE_UPLOAD}
```

Viewer **不**持有（`_VIEWER_ACTIONS` 維持 `{NODE_VIEW, SESSION_VIEW, FILE_BROWSE}`）。
`ROLE_ACTIONS` 是唯一真相（ADR 0016），三個自動化檢查會跟著更新；
`docs/permission-matrix.md` 要一起改。

端點以 `Depends(require_action(FILE_UPLOAD))` 保護。
**權限之外還有一層：** 前端只在 `role === "writer"` 時顯示入口（`05-…md` §2）。
兩者不重複 —— 權限決定「可不可以」，writer 決定「現在輪不輪得到你」。
後端**不**檢查 writer：路徑要不要打進終端機，是前端那條既有的 writer-gated 通道
（`useTerminalSession.ts:231`）自己會擋的事，在 HTTP 層再檢查一次會需要把
WS 的即時狀態搬進 HTTP 請求，那是一個會過期的耦合。

### 2.3 稽核與錯誤碼

新增稽核 action `file.upload`（`backend/app/services/audit.py`，
與 `FILE_SENSITIVE_READ_DENIED` 並列）。metadata：
`{session_id, node_id, mime, bytes, path}`。內容永遠不記（D11）。

失敗也要記：`FILE_UPLOAD_UNSUPPORTED_TYPE` 與 `FILE_UPLOAD_QUOTA_EXCEEDED`
各留一筆，否則「有人一直在試」在稽核上看不出來。

錯誤碼（`backend/app/api/error_catalog.py`，四個新增）：

| Code | HTTP | 何時 |
|---|---|---|
| `FILE_UPLOAD_TOO_LARGE` | 413 | 超過 4 MiB（Central 或 daemon） |
| `FILE_UPLOAD_UNSUPPORTED_TYPE` | 415 | 不是四種圖片之一 |
| `FILE_UPLOAD_QUOTA_EXCEEDED` | 429 | session 或每日配額 |
| `FILE_UPLOAD_FAILED` | 502 | 節點端寫入失敗（磁碟、權限、`.cliora` 不是目錄） |

Central-only、不上 wire：`FILE_UPLOAD_DISABLED`（403，節點回報 `image_upload: false`
時直接拒絕，不打擾節點）。

### 2.4 migration 0018 與 DTO

`nodes` 新增 `image_upload BOOLEAN NOT NULL DEFAULT FALSE`，
`node.register` 落地，Nodes API DTO 帶出去（沿用 0017 對 `privileged_terminal` 的做法）。
前端據此決定顯不顯示入口（D8）。

### 2.5 edge — **已確認不需要改**

已核對（2026-08-01）：`deploy/nginx/nginx.conf:63` 與
`deploy/railway/nginx.conf.template:75` 都是 `client_max_body_size 16m`
（註解寫的理由是「>= the 8 MiB filesystem contract, matching uvicorn」）。
4 MiB 的圖片請求在現值之內，**本期不動 nginx**。

因此 `00-…md` D20 的「唯一例外」不成立 —— 判準回到最單純的形狀：
**這一期的 diff 不應該出現在 `deploy/` 底下**。
若未來把單張上限提高到 12 MiB 以上，才需要重新看這兩個檔案。
