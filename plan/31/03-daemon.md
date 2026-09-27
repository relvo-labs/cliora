# 03 — Daemon 預覽路徑（`BP-03`）

**寫入集：** `daemon/internal/files/preview.go`、`preview_image.go`、`preview_pdf.go`、
`preview_handles.go`（皆新）與其 `_test.go`、`daemon/internal/files/testdata/preview/**`；
`daemon/internal/connection/preview_handlers.go`（新）；`connection.go` dispatch 的三個
`case`；`daemon/internal/config/config.go`；`daemon/internal/metrics/metrics.go`。

**前置：** `BP-02` 合併（codec 已認得新型別）。

**不新增任何 Go 依賴**（`daemon/go.mod` 不變）。

## 1. `PreviewOpen` 的十個步驟

刻意放在 `read.go` 旁邊（若 #71 已合併，也在 `download.go` 旁邊），三份要能並排讀。

| # | 步驟 | 少了它會怎樣 |
|---|---|---|
| 1 | 節點開關 | 已停用的機器仍會被讀 |
| 2 | 對**請求路徑**做 `SensitiveClassification` | 平台會去開啟它已決定不顯示的檔案 |
| 3 | `root.OpenFile`（侷限、`O_NOFOLLOW`，ADR 0014）；錯誤經 `denyFromWorkspaceErr`（`read.go:95-112`） | 符號連結可以指出工作區；outside-root 會洩漏存在與否 |
| 4 | 在 **fd** 上 `Stat` 並檢查 `IsRegular` | FIFO 會讓讀取永遠不返回 |
| 5 | `RealRel(f)` 後再做一次 `SensitiveClassification` | 工作區內無害名字的符號連結指向 `.env` 就能被畫出來 |
| 6 | 從同一 fd 讀 64 bytes 表頭，依 magic 判定 kind | 副檔名說了算 |
| 7 | 依 kind 的大小上限檢查 fd 的快照大小 | 16 MiB 以上的檔案被整份讀進記憶體 |
| 8 | 從同一 fd 有界讀整份（`LimitReader(cap+1)`），讀完再 `Stat` 一次比對 size／mtime | 驗證的位元組與送出的位元組不同 |
| 9 | 結構驗證（§2） | 炸彈與損毀檔送到瀏覽器 |
| 10 | 登記快照 handle（§3），回 `preview_opened` | — |

第 2 與第 5 步是同一個檢查做兩次，**兩次都不能省**，理由見右欄。
拒絕一律 in-band（`Denied` + `Code` + `Reason`），與 `ReadResult` 同形狀；錯誤訊息是固定字串。

## 2. 結構驗證：只走表頭與標記，不解碼

| 格式 | 檢查 | 實作 |
|---|---|---|
| PNG | 簽章；第一個 chunk 必須是 IHDR；寬高 ≤ 8192 且乘積 ≤ 16 777 216；chunk 走訪：每個 chunk 的長度 ≤ 剩餘位元組，總數 ≤ 4096，`zTXt`／`iTXt`／`iCCP` 壓縮長度合計 ≤ 1 MiB；必須看到 `IEND` | `image/png.DecodeConfig` 取尺寸，再加一個只看長度欄位的 chunk walker（**不驗 CRC、不解壓**） |
| JPEG | SOI；marker 走訪到 EOI；SOF 的寬高；SOS 數 ≤ 64；segment 長度不得越界 | `image/jpeg.DecodeConfig` 取尺寸，再加 marker walker |
| GIF | 簽章；邏輯螢幕尺寸；第一個 image descriptor 存在且落在邏輯螢幕內 | `image/gif.DecodeConfig`，再走到第一個 `0x2C` |
| WebP | `RIFF` 大小欄位與檔案大小一致；`WEBP`；第一個 chunk 為 `VP8 `／`VP8L`／`VP8X`，依各自格式取 canvas 尺寸 | 手寫 reader，約 80 行，全部以 `len` 檢查保護 |
| PDF | offset 0 為 `%PDF-1.[0-7]` 或 `%PDF-2.0`；最後 1 KiB 內有 `%%EOF`；在最後 64 KiB 內做 `/Encrypt` 的**啟發式**掃描 | 位元組比對。**不解析 xref、不 inflate** |

每個 sniffer 都有 `go test -fuzz` 目標，種子語料來自 `07-…md` §1。
每個請求都以 `recover` 包住，panic 回 `FILE_PREVIEW_INVALID`/`malformed` 並計數，不讓 daemon 掛掉。

## 3. 快照 handle 表

```go
type previewHandle struct {
    id        string    // ULID
    sessionID uuid.UUID
    kind      string
    mime      string
    data      []byte    // 已驗證的完整檔案
    created   time.Time // monotonic
    lastUsed  time.Time
}
```

- **每條 WebSocket 連線一張表**，連線結束時整張丟掉。重連後舊 id 一律 `FILE_PREVIEW_EXPIRED`。
- 上限：同時 4 個 handle、合計 32 MiB。超過就在**步驟 7 之前**回 `NODE_BUSY`，不先讀檔。
- 閒置 30 秒、絕對 120 秒到期，由單一 janitor goroutine 回收，它隨連線的 context 結束。
- `session.stop` 會清掉該 session 的所有 handle（在既有的 stop 路徑加一個 hook）。
- `preview_chunk`／`preview_close` 的 `session_id` 與 handle 不符時，回應與「不存在」完全相同。
- `preview_close` 冪等；清除時把 `data` 設為 nil，讓 GC 回收。

## 4. 不在 dispatch 迴圈上執行

現行 `handleFsRead` 在迴圈上同步執行（`connection.go:509` → `files_handlers.go:82-133`），
同一個迴圈也處理終端輸入（`connection.go:484-489`）。預覽改走有界 worker：

- `preview_open`：semaphore 2。滿了就回 `NODE_BUSY`，**不排隊**。排隊會把延遲藏進逾時裡。
- `preview_chunk`：只是從記憶體切一段加 base64，但 512 KiB 的 base64 與送出仍然不在迴圈上做；
  共用一個 semaphore 4。
- 每個 worker 帶連線的 context；連線結束時，進行中的讀取在下一個 `Read` 邊界停止。

## 5. 設定

```yaml
filesystem:
  binary_preview:
    enabled: true              # 缺省為 true（OD-5）；以指標型別區分「缺省」與「明確 true」
    image_max_bytes: 8388608
    image_max_pixels: 16777216
    image_max_side: 8192
    pdf_max_bytes: 16777216
```

- `enabled` 缺省與明確設定要可以分辨，啟動 log 說得出「這台機器是從升級繼承到這個行為的」
  （與 `UploadFromDefault`、`FileUploadFromDefault` 同一種處理）。
- 上限只能**調低**，不能調高：大於編譯期常數的值在載入時拒絕並報錯。
  因為 `chunk_count ≤ 32` 與 `size ≤ 16 MiB` 是契約（`02-…md` §1），調高設定不會讓 wire 接受。
- 回報：`node-register.binary_preview = enabled`。

## 6. Metrics 與 log

- `filesystem_request_total{op="preview_open"|"preview_chunk", code}`、
  `filesystem_denied_total{code, reason}`（沿用）、`filesystem_preview_bytes`（histogram，
  只在成功的 open 記一次）、`filesystem_preview_handles`（gauge）。
- log：`request_id`、`session_id`、`kind`、`code`、`bytes`、`duration_ms`。
  **不記 path、不記檔名。** 這一點比 `handleFsRead` 嚴格：現行 read 的 log 也不記 path（`files_handlers.go:118-121`）。

## 7. 先寫的 RED 測試

| 測試 | 斷言 |
|---|---|
| `TestPreviewUsesSameSensitivePolicyTwice` | `.env`、`id_rsa`、`.ssh/diagram.png` → `FILE_DENIED`；`photo.png → .env` 符號連結 → `FILE_DENIED`（第二次判定） |
| `TestPreviewNeverReadsBeyondHeaderWhenTooLarge` | 以計數 reader 斷言：超過上限時讀取量 ≤ 64 bytes |
| `TestPreviewAllowlistIsClosed` | SVG、BMP、TIFF、HEIC、ZIP、文字檔 → `unsupported_type`；副檔名與內容不符時以內容為準 |
| `TestPreviewPixelBombRefused` | 50000×50000 PNG、SOF 65535×65535 JPEG → `FILE_PREVIEW_LIMIT`，且沒有 handle 被建立 |
| `TestPreviewJPEGScanBomb` | 1000 個 SOS → `complexity` |
| `TestPreviewChangedDuringRead` | 讀取期間 append → `FILE_PREVIEW_INVALID`/`changed` |
| `TestPreviewFifoAndDevice` | FIFO → `not_regular`，而且**不會卡住**（測試本身有 2 秒 deadline） |
| `TestPreviewHandleBoundToSession` | 用 session B 的 id 拉 session A 的 handle → `EXPIRED` |
| `TestPreviewHandleExpiresAndFrees` | 30 秒閒置後 handle 數歸零（fake clock） |
| `TestPreviewHandlesDroppedOnDisconnect` | 連線結束 → 表清空 |
| `TestPreviewDoesNotBlockDispatch` | 一個 16 MiB 的 open 進行中，terminal input frame 仍在 50 ms 內被處理 |
| `TestPreviewBusyIsImmediate` | 第三個並發 open 立即 `NODE_BUSY`，不排隊 |
| `TestPreviewSnapshotEqualsValidatedBytes` | 所有 chunk 串起來與驗證時的 buffer 位元組相同 |
| `TestReadStillDeniesBinary` | **同一張 PNG** 走 `Read` 仍是 `FILE_BINARY`：文字預覽語意不變 |
| `TestPreviewDisabledSwitch` | `enabled:false` → `FILE_PREVIEW_DISABLED`，且 `node-register` 回報 false |
| Fuzz：`FuzzSniffPNG`／`JPEG`／`GIF`／`WebP`／`PDFEnvelope` | 不 panic、不越界、不超時 |

還要跑 `go test -race ./...`。handle 表是並發資料結構，race 測試是必要條件，不是加分。

## 8. 驗收清單

- [ ] §1 十步與 §2 格式表逐項有測試。
- [ ] §7 全部綠；`go test -race ./...` 綠；每個 fuzz 目標至少跑 10 分鐘，無發現。
- [ ] `daemon/go.mod` 沒有新依賴。
- [ ] `connection.go` 只多了三個 `case`，全部轉交 worker。
- [ ] `read.go` 沒有任何 diff。

## 9. 不在範圍

像素解碼、轉碼、縮圖；PDF 頁數計算；密碼；把 `handleFsRead` 移出 dispatch 迴圈
（值得做，但那是既有路徑的改動，另開議題）。
