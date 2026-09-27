# 02 — 契約 v1.11.0（`BP-02`）

**寫入集：** `contracts/v1/schemas/**`、`contracts/v1/fixtures/**`、`contracts/v1/compat/**`（新，凍結的舊 schema，見 §2）、`contracts/CHANGELOG.md`，
以及三個消費端的 codec 與其測試（`backend/app/protocol/codec.py`、
`daemon/internal/protocol/codec.go`、`frontend/src/protocol/decode.ts`）。

**前置：** `BP-01` 核准；#71 已合併（否則依 README 重排編號）。

## 1. 型別（`version` 整數仍為 `1`，compatible）

| 型別 | 方向 | Payload | 大 frame？ |
|---|---|---|---|
| `filesystem.preview_open` | C → D | `{session_id, path}`，與 `filesystem-read.schema.json` 相同的 `path` pattern；`additionalProperties:false` | 否（64 KiB） |
| `filesystem.preview_opened` | D → C | 成功：`{success:true, preview_id, path, kind, mime, size, modified_at, chunk_size, chunk_count, width?, height?}`；拒絕：`{success:false, path, error:{code, reason, size?, limit?}}` | 否 |
| `filesystem.preview_chunk` | C → D | `{session_id, preview_id, index}` | 否 |
| `filesystem.preview_data` | D → C | `{preview_id, index, data}` | **是**（加入 `LargeFrameTypes`，response 方向） |
| `filesystem.preview_close` | C → D | `{session_id, preview_id}` | 否 |
| `filesystem.preview_closed` | D → C | `{preview_id}` | 否 |

欄位約束：

- `preview_id`：ULID pattern（與 `request_id` 同一個 pattern，`control-envelope.schema.json:9`）。
- `kind`：enum `["image", "pdf"]`。`mime`：enum `["image/png", "image/jpeg", "image/webp", "image/gif", "application/pdf"]`。
  **enum 就是白名單**；schema 本身就拒絕 `image/svg+xml`。
- 另加 `if/then`：`kind:"image"` ⇒ `mime` 以 `image/` 開頭且 `width`／`height` 必填；
  `kind:"pdf"` ⇒ `mime` 為 `application/pdf` 且**不得**有 `width`／`height`。
- `size`：`1 … 16777216`；`chunk_size`：const `524288`；`chunk_count`：`1 … 32`。
- `width`／`height`：`1 … 8192`。像素乘積上限由 daemon 保證，schema 表達不了乘積。
- `index`：`0 … 31`。
- `data`：canonical 標準字母表 base64（與 1.8.0 同一 pattern），`maxLength: 699052`
  （= 512 KiB 的 base64 長度）；空字串不允許（沒有空檔案可預覽）。
- `modified_at`：UTC `Z` 時間（與既有 `non-utc-time` 規則同）。

**刻意缺席的欄位**，以及各自擋掉的東西：

| 缺席欄位 | 它會帶來什麼 |
|---|---|
| request 的 `mime`／`kind`／`format` | 呼叫端「宣稱」型別，而那正是 magic 判定要取代的東西 |
| `raw`／`encoding`／`mode` | 在同一個型別上長出第二套政策 |
| `offset`／`length`／`range` | 對活檔案做 range 讀取（ADR 0029 §5 拒絕的替代方案） |
| `disposition`／`filename` | 讓預覽長得像下載 |
| `password` | OD-8 |

## 2. 回報欄位

`node-register.binary_preview`：選用，schema 為 **`{"const": true}`**；**缺席即 false**。
Report-only：節點陳述姿態，平台不能選擇。

**停用時省略，永不送 `false`。** 這是與 `image_upload`／`file_upload`／`file_download`（一般布林）
刻意不同的地方，理由是 Central 回退（ADR 0029 §9）：舊 Central 的 `node-register` 是
`additionalProperties:false`，它拒收的是**這個 key**，不看值。而且是靜默拒收：
`codec.py:100-102` 拋錯，`ws/nodes.py:199-202` 直接 `continue`，不回覆、不持久化，連線照常。
所以停用的新 daemon 必須在 wire 上與舊 daemon 長得一樣。`const: true` 讓「送了 `false`」
在三個消費端都是**無效訊息**，daemon 的錯誤會在共用 fixture 上變紅，而不是等到回退那天才被發現。

**凍結的舊 schema：** `contracts/v1/compat/node-register.pre-1.11.schema.json` 是 1.10.0
（或 #71 未合併時的 1.9.0）`node-register.schema.json` 的逐字複本，只給相容測試用，**永不修改**；
檔頭註明來源 commit。

## 3. 錯誤碼（加進 envelope 的 `error.code` enum，`control-envelope.schema.json:18`）

| Code | 何時 | 出現方式 | 下一步 |
|---|---|---|---|
| `FILE_PREVIEW_UNSUPPORTED` | 型別不在白名單（reason `unsupported_type`） | in-band | 無；非白名單型別可試文字預覽 |
| `FILE_PREVIEW_INVALID` | 結構異常（`malformed`）、讀取期間檔案改變（`changed`） | in-band | 重新整理；仍失敗就是檔案壞了 |
| `FILE_PREVIEW_LIMIT` | 像素（`pixels`）、邊長（`dimensions`）、複雜度（`complexity`） | in-band | 無；用終端機處理 |
| `FILE_PREVIEW_DISABLED` | 節點開關關閉，但 Central 的快取還以為開著 | error frame | 洽節點擁有者 |
| `FILE_PREVIEW_EXPIRED` | handle 不存在、過期、屬於別的 session，或連線已重建 | error frame | 重新開啟 |

沿用：`FILE_DENIED`、`FILE_NOT_FOUND`、`FILE_PERMISSION_DENIED`、`FILE_TOO_LARGE`（in-band）、`NODE_BUSY`。
Central 專屬、不上 wire：`FILE_PREVIEW_UNSUPPORTED_NODE`（409）、`FILE_PREVIEW_BUSY`（429）。

## 4. Golden fixtures

| 檔案 | 釘住的性質 |
|---|---|
| `valid/filesystem-preview-open.json` | 正常請求 |
| `valid/filesystem-preview-opened-image.json` | 圖片成功，含 `width`／`height` |
| `valid/filesystem-preview-opened-pdf.json` | PDF 成功，無尺寸 |
| `valid/filesystem-preview-opened-denied.json` | in-band 拒絕（`FILE_PREVIEW_LIMIT`/`pixels`） |
| `valid/filesystem-preview-chunk.json` | 正常分塊請求 |
| `valid/filesystem-preview-data.json` | 正常分塊回應 |
| `valid/filesystem-preview-close.json`、`valid/filesystem-preview-closed.json` | 關閉 |
| `valid/node-register-binary-preview.json` | 與其他開關並存 |
| `invalid/filesystem-read-with-raw.json` | **`filesystem.read` 永遠不接受 `raw`**（ADR 0029 §1） |
| `invalid/filesystem-preview-open-with-mime.json` | 請求不能宣稱型別 |
| `invalid/filesystem-preview-open-with-range.json` | 沒有 range |
| `invalid/filesystem-preview-open-parent-escape.json` | `../` 在 wire 上就被擋 |
| `invalid/filesystem-preview-opened-svg.json` | `image/svg+xml` 不在 enum |
| `invalid/filesystem-preview-opened-pdf-with-size.json` | `if/then` 生效 |
| `invalid/filesystem-preview-chunk-index-out-of-range.json` | `index: 32` |
| `invalid/filesystem-preview-chunk-bad-id.json` | 非 ULID |
| `invalid/filesystem-preview-data-non-base64.json` | 只接受標準字母表 |
| `invalid/filesystem-preview-data-oversize.json` | 超過 699052 字元 |
| `invalid/node-register-binary-preview-non-boolean.json` | 回報欄位型別 |
| `invalid/node-register-binary-preview-false.json` | **停用時必須省略，`false` 無效**（ADR 0029 §9） |

加密不是 wire 上的拒絕原因：daemon 不做加密判定，需要密碼的 PDF 由前端以 `pdf_password_required` 呈現
（ADR 0029 §4、OD-8）。所以 `FILE_PREVIEW_UNSUPPORTED` 沒有 `encrypted` 這個 reason，也沒有對應 fixture。

三個消費端都跑同一份 `manifest.json`。Go 端要為 `preview_opened` 與 `preview_data`
這兩個 **response** 型別加驗證分支（#71 為 `downloaded` 開了先例）；少了它，
`opened-svg` 會被 Python 與 TypeScript 拒絕、卻被 Go 悄悄接受。

## 5. `contracts/CHANGELOG.md` 版本提案

```markdown
## 1.11.0 — <合併日> (compatible)

- **Six new types and one additive report field** (`version` stays `1`):
  `filesystem.preview_open` / `_opened`, `_chunk` / `_data`, `_close` / `_closed`, and
  `node-register.binary_preview`. Read-only, in-console rendering of an allowlisted image or
  PDF. See ADR 0029 and `plan/31`.
- **`filesystem.read` is unchanged**, and `invalid/filesystem-read-with-raw.json` now pins
  that it never grows a `raw` flag.
- **The `mime` enum is the allowlist**: png, jpeg, webp, gif, pdf. SVG is refused by schema.
- **`filesystem.preview_data` is the seventh type allowed the 8 MiB bound** (response
  direction only); its `data` is capped at 512 KiB of raw bytes, so the bound does not move.
- **`binary_preview` is optional, `const: true`, and absent means "no"**. A disabled daemon
  *omits* it rather than sending `false`, so that its registration is still accepted by an
  older Central, whose strict schema rejects the key itself, silently. Unlike
  `image_upload` / `file_upload`, `false` is invalid (`invalid/node-register-binary-preview-false.json`).
- A Central must never send a `filesystem.preview_*` frame to a node whose live
  registration did not report it, because older daemons drop unknown types without replying.
- New error codes: `FILE_PREVIEW_UNSUPPORTED`, `FILE_PREVIEW_INVALID`, `FILE_PREVIEW_LIMIT`,
  `FILE_PREVIEW_DISABLED`, `FILE_PREVIEW_EXPIRED`.
```

「第七個」這個序數假設 #71 的 `filesystem.downloaded` 是第六個；合併時重新數一次。

## 6. 先寫的 RED 測試

1. 新 fixture 全部加入 manifest，schema 還沒寫 → 三個消費端必須全紅（證明 manifest 真的被跑）。
2. `invalid/filesystem-read-with-raw.json` 在**現行** schema 下就應該是綠的，
   因為已經是 `additionalProperties:false`。它是**守門**測試，不是 RED；把它寫進測試名稱。
3. 新 schema 寫好、Go 端還沒加 response 驗證分支 → `opened-svg` 在 Go 必須紅。
4. **部署與回退的相容證明**（Python，`backend/tests/test_contract_compat.py`，新）：以
   `contracts/v1/compat/node-register.pre-1.11.schema.json` 驗證：
   - `valid/node-register-binary-preview.json`（啟用）→ **必須被拒**。這讓「先升 Central、再升 daemon」
     從 runbook 的一句話變成一個會失敗的事實。
   - `valid/node-register.json`（停用的新 daemon 應送出的形狀，也就是沒有這個欄位）→ **必須被接受**。
     這讓「停用即可接回舊 Central」成為可測的性質。
   - daemon 端另有 `TestRegisterOmitsBinaryPreviewWhenDisabled`（`03-…md` §7）：停用時建構出的 register
     payload 與上面那份 fixture 形狀相同，而且**沒有** `binary_preview` 這個 key。
   舊 Central 拒收後的行為已由讀程式確認（靜默略過、連線不斷，原 `BP-OM-08`）；
   `BP-04` 另有一條 Central 端測試把它釘住：送一個 schema 不符的 `node.register`，斷言沒有持久化、沒有回覆、連線仍在。
5. 舊 daemon 的 `allowedTypes`（`codec.go:87`）不含新型別 → 以舊版本的 decoder 解
   `valid/filesystem-preview-open.json` 必須失敗，證明「會被靜默丟棄」這個前提。

## 7. 驗收清單

- [ ] 六個 schema、`node-register` 一個欄位、envelope 五個錯誤碼。
- [ ] §4 的 21 個 fixture 進 manifest；凍結 schema 與其來源 commit 註記；`make contract` 三個消費端綠。
- [ ] `LargeFrameTypes`／`LARGE_FRAME_TYPES` 只加 `filesystem.preview_data`；有測試斷言
      `preview_open`／`preview_chunk` 仍是 64 KiB。
- [ ] `TestPreviewChunkFitsFrameBound`：`chunk_size` 的 base64 加上 envelope 小於 `MaxFilePayload`。
- [ ] CHANGELOG 1.11.0 段落（§5）。
- [ ] §6 的第 4、5 條測試存在且綠（它們斷言的是「被拒」）。

## 8. 不在範圍

daemon 的實際行為、Central 路由、前端呼叫；新的 binary frame kind（ADR 0029 替代方案已拒）；
任何 `filesystem.read`／`filesystem.content` 的修改。
