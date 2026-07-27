# 02 — P0-W2 Protocol v1

## 目標

先凍結最小 wire contract，再讓 Python、Go、TypeScript 各自實作 codec。JSON Schema 是結構來源、golden fixtures 是行為來源；任一 consumer 不得私自擴充 required field。

## P0-04：控制 envelope

所有 control message 使用 UTF-8 JSON text frame：

```json
{
  "version": 1,
  "type": "session.start",
  "request_id": "01K0...",
  "node_id": "00000000-0000-4000-8000-000000000001",
  "timestamp": "2026-07-22T09:00:00Z",
  "payload": {}
}
```

規則：

- `version` 是整數 `1`；不接受字串或其他版本。
- `type` 使用 allowlist；P0 支援 `session.start|started|attach|attached|stop|stopped`、`terminal.resize|gap|exited`、`node.heartbeat`、`error`。
- request 必須有 ULID `request_id`；其 response 沿用同一值。純 event 使用自己的 event ID，不能借用舊 request ID。
- `node_id`、`session_id` 一律 canonical UUID；需要 session 的 message 把 `session_id` 放在 typed payload。
- timestamp 必須是 UTC `Z`、具秒與最多六位小數；拒絕 naive 或 offset timestamp。
- schema 設 `additionalProperties: false`；payload 依 message type discriminated validation。
- response 明示 `success`；錯誤只含 stable `code`、safe `message`、可選的非敏感 details。

`session.start` payload 僅允許 `session_id`、`runtime_id: "fake"`、固定 test workspace ID、`rows`、`columns`；明確禁止 command、binary、argv、shell、env、任意 absolute path。

## Binary terminal frame

Central ↔ Daemon frame：

```text
byte 0      version = 0x01
byte 1      kind: 0x01 input, 0x02 output
byte 2..17  UUID raw 16 bytes, network byte order
byte 18..N  opaque terminal bytes
```

Browser WS 已由 URL 綁定 session，因此 payload 本身就是 opaque bytes；Browser → Central 僅解讀為 input，Central → Browser 僅解讀為 output。空 payload、未知 kind/version、少於 18 bytes、超過 64 KiB payload 一律拒絕。Terminal bytes 不可 decode/re-encode 為文字，也不可寫 log。

ordering 只保證單一 session、單一已連接 transport 上的傳送順序。P0 不做 replay sequence；重新 attach 使用一次 `terminal.attached` metadata + snapshot，overflow 以 `terminal.gap` 明確告知。這項限制須寫入 ADR，P2 若需精準 resume 再加入 sequence number。

## Error 與 close contract

P0 stable codes：

```text
INVALID_MESSAGE
PROTOCOL_VERSION_UNSUPPORTED
MESSAGE_TYPE_UNSUPPORTED
FRAME_TOO_LARGE
INVALID_SESSION
SESSION_NOT_FOUND
SESSION_ALREADY_EXISTS
SESSION_NOT_RUNNING
RUNTIME_NOT_ALLOWED
INVALID_TERMINAL_SIZE
NODE_OFFLINE
REQUEST_TIMEOUT
QUEUE_OVERFLOW
INTERNAL_ERROR
```

可解析的 domain error 先送 `error` frame，再依是否可恢復決定保持或關閉連線；malformed JSON/UTF-8、version mismatch、oversize 直接以 WS 1002/1007/1009 結束。`INTERNAL_ERROR` 不帶 stack、process path、tmux output 或 terminal content。

## Fixtures 與 codec tasks

建立：

```text
contracts/v1/schemas/control-envelope.schema.json
contracts/v1/schemas/messages/*.schema.json
contracts/v1/fixtures/valid/*.json
contracts/v1/fixtures/invalid/*.json
contracts/v1/fixtures/binary/*.bin
contracts/v1/fixtures/manifest.json
```

manifest 對每個 fixture 記錄 expected accept/reject、message type/error code 與 binary payload SHA-256。P0-05 在 Python/Go/TS 各跑同一 manifest，並做 encode → bytes/JSON → decode round trip。

必備 invalid fixtures：缺欄位、額外欄位、錯誤 version/type、naive/non-UTC timestamp、無效 ULID/UUID、rows/columns 邊界、禁止 command 欄位、malformed UTF-8/JSON、short binary、unknown kind、oversize。rows `2..300`、columns `2..500`，邊界內接受、邊界外拒絕。

## 變更規則與驗收

- schema 或 fixture 變更須更新 `contracts/CHANGELOG.md`，標明 compatible/breaking。
- CI 先驗 schema/manifest，再跑三語言 consumer；fixture 缺 consumer 即失敗。
- codec fuzz/property test 至少保證任意輸入不 panic、無未界定 allocation、錯誤不洩漏內容。
- 驗收以三語言相同 accept/reject 結果為準，不以其中一個實作為真相。
