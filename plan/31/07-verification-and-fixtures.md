# 07 — 驗證、語料與效能（`BP-09`）

**寫入集：** `scripts/p31/gen_preview_fixtures.py`（新，產生器）、
`daemon/internal/files/testdata/preview/`（**只放小檔**）、`frontend/tests/e2e/binary-preview*.spec.ts`
（與 `BP-07` 共用，`BP-09` 補情境）、`backend/perf/`（新情境）。
**前置：** `BP-08` 不是 `FAIL`。

## 1. 高風險語料

**原則：** 炸彈與大檔**不進 Git**，由產生器在測試時生成到暫存目錄。
Git 裡只放 ≤ 64 KiB 的小樣本。產生器是 deterministic 的（固定 seed），
輸出附 SHA-256 清單，讓同一份語料可以在 CI 與實機重現。

| 類別 | 檔案（產生或小樣本） | 預期 |
|---|---|---|
| 正常 | `ok.png`（1200×800）、`ok.jpg`（EXIF 方向 6）、`ok.webp`（lossy／lossless／VP8X 各一）、`ok.gif`（動畫 10 幀）、`ok-apng.png`、`ok.pdf`（40 頁）、`ok-cjk.pdf`（CID 字型繁中）、`ok-jpx.pdf` | 顯示；JPEG 方向正確；GIF／APNG 只有首幀；CJK 字形正確 |
| 解壓縮炸彈 | `png-bomb-50k.png`（50000×50000，IDAT 約數 KB）、`png-iccp-bomb.png`（約 1 KiB 的 `iCCP` 展開成 100 MiB）、`png-ztxt-bomb.png`（約 1 KiB 的 `zTXt` 展開成 100 MiB）、`png-itxt-compressed-bomb.png`、`png-many-ztxt.png`（65 個）、`apng-1001-frames.png`、`apng-frame-outside-canvas.png`、`jpeg-app-3mib.jpg`（APPn 合計 3 MiB）、`jpeg-icc-over-budget.jpg`（APP2 ICC 拼接後 1 MiB＋1）、`webp-iccp-over-budget.webp`、`webp-exif-xmp-over-budget.webp`、`webp-1001-anmf.webp`、`gif-ext-over-budget.gif`（comment／application extension 合計 1 MiB＋1）、`gif-1001-frames.gif`、`jpeg-sof-65535.jpg`、`jpeg-1000-scans.jpg`、`webp-16k.webp`（16383×16383）、`gif-frame-outside-screen.gif` | `FILE_PREVIEW_LIMIT`／`INVALID`；**瀏覽器收到 0 bytes** |
| 真實世界的中繼資料 | `ok-screenshot-p3.png`（macOS 或 iOS 截圖，含 Display P3 `iCCP`）、`ok-editor-export.png`（編輯器匯出，含 `iCCP` 與 `iTXt` XMP）、`ok-camera.jpg`（EXIF＋APP2 ICC）、`ok-extended.webp`（VP8X＋`ICCP`＋`EXIF`） | 全部**通過**，而且送出的位元組與原檔 SHA-256 相同（只量不改）。這一列用來證明預算不會誤拒日常檔案（`BP-OM-13`） |
| 中繼資料預算邊界 | `iCCP` 展開恰好 1 MiB 與 1 MiB＋1；壓縮附屬展開合計 2 MiB 與 2 MiB＋1；JPEG APPn 合計 2 MiB 與＋1；GIF extension 1 MiB 與＋1 | 恰好等於上限的通過，超過一的拒絕 |
| 邊界 | 4096×4096 PNG（恰好等於像素上限）、4097×4096、8192×2048、8193×1、8 MiB 整與 8 MiB＋1 的 JPEG、16 MiB 整與 ＋1 的 PDF、200 與 201 頁 PDF | 恰好等於上限的通過，超過一的拒絕 |
| 格式錯誤 | 截斷 PNG（無 IEND）、IHDR 不在第一個、RIFF 大小不符的 WebP、無 `%%EOF` 的 PDF、`%PDF` 不在 offset 0、xref 損毀但信封正常的 PDF | daemon `malformed`；信封正常的交給 PDF.js → `render_failed` |
| 加密 PDF | RC4-40、AES-128、AES-256，**有使用者密碼**；同樣三種，**只有權限密碼（空使用者密碼）** | 有使用者密碼 → 前端 `pdf_password_required`，沒有密碼輸入框；只有權限密碼 → 依 OD-8 建議預設**正常唯讀顯示**（OD-8 若選 (b)，改為被拒）。daemon 對兩者都**不**判定加密，所以兩者都會傳到瀏覽器，這一點要寫在測試名稱與說明裡 |
| 主動內容 PDF | 內含 JS（OpenAction）、URI 連結、Launch、GoToR、表單 submit、XFA、內嵌附件；CVE-2024-4367 PoC 形狀 | 惰性；無 navigation、popup、網路請求、script |
| 錯誤 magic／多型檔 | `html-named.png`、`svg-named.png`、`pdf-named.jpg`、`png-named.pdf`、`zip-pdf-polyglot.pdf`、`text-named.pdf` | 依內容判定：HTML／SVG／text → `unsupported_type`；互換副檔名的 PNG／PDF 依真實型別顯示 |
| 敏感名稱與路徑 | `.env.png`、`id_rsa.pdf`、`credentials-diagram.png`、`secrets-report.pdf`、`.ssh/diagram.png`、`photo.png → .env`（工作區內符號連結）、`link.pdf → ../outside.pdf`（外部符號連結） | `FILE_DENIED`；敏感者有稽核，不含路徑 |
| 非一般檔案 | FIFO `fifo-a.png`、`fifo-b.png`（沒有寫入端）、unix socket `sock.pdf`、目錄 `dir.pdf/`、指向 `/dev/zero` 的符號連結 | `not_regular` 或 `outside_root`。**兩個 FIFO 的預覽送出並回應之後，第三個合法 PNG 預覽必須成功，三者合計 2 秒內完成**（daemon 層 `TestPreviewTwoFifosDoNotStarveWorkers`，full-stack 再跑一次） |
| 符號連結語意 | `ok-link.png → images/ok.png`（in-root）、`photo.png → .env`（in-root，敏感） | 前者**顯示**（open 會跟隨 in-root 連結）；後者在 `RealRel` 二次判定被拒 |
| 讀取中變動 | 讀取期間 append 的 PNG | `changed` |

## 2. 角色與閘門矩陣（full-stack）

| 使用者 | session | Central flag | 節點回報 | 預期 |
|---|---|---|---|---|
| Admin／Developer／Viewer | 可檢視的 CLI session | on | true | 200 |
| Viewer | 別人的 session（無檢視權） | on | true | 403，與「不存在」同訊息 |
| 任何人 | shell session | on | true | 403 |
| 任何人 | 可檢視 | **off** | true | 409，零 frame |
| 任何人 | 可檢視 | on | **false／缺席（舊 daemon）** | 409，零 frame；UI 是既有 `FILE_BINARY` 面板 |
| （#71 合併後）任何人 | 可檢視 | on | `binary_preview:true, file_download:false` | 預覽 200，下載 403 |
| （#71 合併後）任何人 | 可檢視 | on | `binary_preview:false, file_download:true` | 預覽 409，下載 200 |
| 任何人 | 可檢視 | on | 以 true 註冊 → 斷線 → 以省略欄位重連 | `can_preview_binary` 與端點**同時**變成 false／409 |

另加兩項非角色的 full-stack 檢查：

- **Central 回退演練**（`daemon_version` 全程不變）：停用的新 daemon（欄位省略）帶著一次性的 `node.name` 標記
  連到 1.10.0 的 Central，node list 出現該標記，證明註冊被接受；啟用的新 daemon 帶另一個標記連到同一個 Central，
  標記**不出現**（註冊被靜默略過）。後者是**預期中的失敗**，用來證明 runbook 的順序是必要的。
  在新 Central 上則以 `last_registration_at` 前進作為證據。
- **Snapshot 釋放**：連續 N+1＝5 次成功預覽，全部成功而且不等 TTL；每次結束後 daemon 的
  `filesystem_preview_handles` gauge 回到 0；取消與錯誤路徑也回到 0。
- **Canary log 搜尋**（`BP-OM-10`）：依 `04-…md` `BP-05`「發布閘門」的步驟，在兩種部署拓樸上都做。

## 3. 效能與容量（`make perf` 新情境）

| 量測 | 目標（初值，量完再定） |
|---|---|
| 390 px、4G 模擬下 3 MB PNG 到畫出 | p95 < 3 s（與 ADR 0015 的 ≤2 MB 文字預覽同級） |
| 5 MB／40 頁 PDF 第一頁畫出 | p95 < 4 s |
| 每節點 4 條並發串流時，終端 echo 延遲 | 增量 p95 < 100 ms（`BP-OM-05`） |
| daemon RSS 在 4 個 16 MiB handle 時 | < 基準 + 40 MiB |
| Central RSS 在 32 條並發串流時 | < 基準 + 32 MiB |
| 取消後 daemon handle 歸零 | ≤ 30 s（TTL） |

未達目標不是自動失敗，而是一個需要記錄的**發布決定**（ADR 0015 的既有規則）。

## 4. 成功判準的證據

`00-…md` §1 的十項，每一項要有可貼上的輸出：測試名稱與結果、Central log 摘錄（已去識別）、
截圖路徑（**不進 Git**）。截圖與錄影不得含真實檔名、session 名稱或內容（#76 的公開規則）。

## 5. 驗收清單

- [ ] 產生器可重現，SHA-256 清單與 CI 一致。
- [ ] §1 每一列都有自動化測試（daemon、Central 或 E2E 其中一層，並註明是哪一層）。
- [ ] §2 矩陣 full-stack 綠（`E2E_FULL_STACK=1`）。
- [ ] §3 每項有數字；未達標者有書面的發布決定。
- [ ] 文字預覽、上傳、檔案樹、搜尋的既有測試未修改即綠。

## 6. 不在範圍

實機（`BP-10`）；模糊測試的長時間執行（`BP-03` 已跑，這裡只重播發現）。
