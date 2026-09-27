# 00 — 執行總控（唯讀二進位預覽：圖片與 PDF）

## 1. 成功定義

**要交付的：** 持有 `file.browse` 的使用者（Admin／Developer／**Viewer**）在手機或桌面的
檔案瀏覽中點一個 PNG／JPEG／WebP／GIF 或 PDF，同一個 session 內就會出現全幅唯讀預覽：
圖片可以符合寬度、可以縮放；PDF 可以逐頁看、可以跳頁、可以縮放。返回後回到原本的資料夾、
搜尋結果與捲動位置。整個過程沒有任何「存檔」入口，也不會在任何地方落地。

**不得弄壞的六件事：**

1. **文字預覽語意不變。** `filesystem.read` 的 schema、`read.go` 的七步、2 MiB 上限、
   `FILE_BINARY` 分類，一個位元組都不動（#77 驗收第三項）。
2. **`workspace.Root` 與敏感檔案政策只有一份實作。** 預覽呼叫同一個
   `SensitiveClassification()`，呼叫兩次（`read.go:18-20`、`:49-55` 的同一模式）。
3. **中央、edge、瀏覽器都不落地。** 不寫磁碟、DB、log、metrics label、HTTP 快取、
   Service Worker、IndexedDB（ADR 0029 §5、§6、§14）。
4. **舊 daemon 不會收到新型別；舊 Central 不會讓新瀏覽器開啟功能**（ADR 0029 §9）。
5. **預覽不是下載。** 不共用 #71 的端點、開關、稽核與型別；預覽失敗時不提供「改下載」（§16）。
6. **#76 的 session 綁定與 auth-loss 清理不退步**；本功能掛在它上面，不繞過它。

**成功判準（每一項都要有可貼上的輸出，見 `07-…md` §4）：**

1. Viewer 在 390 px 的 iPhone Safari 打開一張 3 MB 的 PNG：符合寬度顯示，雙指或按鈕可放大，
   長按**沒有**「儲存影像」。
2. 同一個 Viewer 打開一份 40 頁、5 MB 的 PDF：顯示「第 1／40 頁」，可以翻頁、跳頁、縮放；
   PDF 裡的外部連結按了沒有任何反應，也不會開新分頁。
3. `50000×50000` 的 PNG 炸彈：daemon 回 `FILE_PREVIEW_LIMIT`/`pixels`，
   **瀏覽器沒有收到任何位元組**（Central log 的 `bytes=0`）。
4. `photo.png` 是指向 `.env` 的工作區內符號連結：`FILE_DENIED`，並留下
   `file.sensitive_read_denied` 稽核（只有 classification 與副檔名）。
5. 需要密碼才能開啟的 PDF：「此 PDF 需要密碼，預覽不支援」；沒有密碼輸入框，也沒有「改下載」。
   只有權限密碼（空使用者密碼）的 PDF 照常以唯讀顯示（OD-8 建議預設）。
6. 傳輸到一半切換 session：舊 session 的位元組**從未**畫出，canvas 已歸零，
   daemon 的快照表在 30 秒內歸零。
7. 在另一個分頁登出：這個分頁的預覽在同一個 tick 內消失（沿用 #76 模式）。
8. 舊版 daemon（沒有 `binary_preview`）：UI 顯示既有的 `FILE_BINARY` 面板；
   Central log 證明沒有送出任何 `filesystem.preview_*`。
9. 同一台節點 `binary_preview` 開、`file_download` 關（#71 合併後）：預覽可用、
   下載 403；反過來亦然。
10. 1440×900 桌面：文字預覽、檔案樹、搜尋、上傳全部不退步。
11. 以含辨識記號的 canary 路徑（例如 `bp-canary-<隨機>/機密-<隨機>.pdf`）預覽之後，在兩份 nginx access log、
    uvicorn／Central stdout、Central JSON log、稽核表與 Railway 的 log 搜尋該記號（原文與 percent-encoded 都搜）：
    **零筆**（`BP-OM-10`）。
12. 工作區內兩個 FIFO 同時被預覽，第三個合法請求仍在 2 秒內完成；兩個 FIFO 都回 `not_regular`。
13. 把一台節點設為 `filesystem.binary_preview.enabled: false` 後，它的 `node.register` 可被 **1.10.0 的
    Central** 接受（凍結 schema 相容測試＋staging 回退演練）。

## 2. 範圍

### 納入

- ADR 0029 核准、PRD `FR-FILE-012` 與三處修訂、traceability、permission-matrix generator（`BP-01`）。
- 契約 v1.11.0：六個型別、一個回報欄位、五個錯誤碼、golden fixtures（`BP-02`）。
- daemon：`PreviewOpen`、格式信封驗證、快照表、worker pool、設定開關（`BP-03`）。
- Central：`POST …/files/binary-preview`（路徑在 body）、串流、能力協商、稽核、migration、rollout flag（`BP-04`）。
- Edge：兩份 nginx 設定的專用 location（不緩衝、不寫暫存檔、不記 query 的 log 格式），以及 `BP-OM-06`／`BP-OM-10` 兩道**發布閘門**（`BP-05`）。
- 前端：共用生命週期與圖片檢視（`BP-06`）、PDF.js 渲染器（`BP-07`）。
- 安全審查（`BP-08`）、驗證語料與 E2E（`BP-09`）、實機矩陣（`BP-10`）、推出與 rollback（`BP-11`）。

### 不納入

- 檔案清單縮圖；SVG、HEIC／HEIF、AVIF、BMP、TIFF、ICO；影片、音訊、Office 文件。
- GIF 動畫播放（OD-1 預設首幀）；PDF 文字選取、搜尋、文字層（OD-3 預設不做）。
- 需要密碼才能開啟的 PDF（OD-8）；列印；PDF 表單填寫；PDF 內連結的導覽（OD-4）。
- 任何下載、存檔、分享入口。這是 #71 的範圍，**而且兩者不互相啟用**。
- 放寬敏感檔案政策；修改 `filesystem.read`。
- #76 本身的修補。本計畫**依賴**它先綠（#77 驗收第一項）。

## 3. 固定基線決策（D0–D14）

以下是 ADR 0029 的決策摘要，細節與理由在 ADR。標為 **OD** 的是產品決策，目前填的是建議預設。

| # | 決策 | ADR § | 日後 |
|---|---|---|---|
| D0 | 新增一組 `filesystem.preview_*` 型別，不動 `filesystem.read`，不借用下載 | §1 | — |
| D1 | 型別由 daemon 依 magic 加結構檢查決定；副檔名只當路由提示 | §2 | — |
| D2 | 白名單：PNG、JPEG、WebP、GIF（首幀）、PDF；其餘一律 `unsupported_type` | §2 | 新格式需修訂 ADR |
| D3 | daemon 只做表頭／標記走訪，不解碼像素、不解析 PDF 內容；不新增 Go 依賴 | §3 | — |
| D4 | 上限：圖 8 MiB／16.7 MP／邊長 8192；PDF 16 MiB／200 頁 | §4 | **OD-2** |
| D5 | 頁數與加密由瀏覽器端 PDF.js 判定；daemon 只做信封檢查，**不做加密判定** | §4 | **OD-8** |
| D6 | 讀一次成記憶體快照、驗證、再以 512 KiB 分塊拉取；不落地、不做 range | §5 | — |
| D7 | 預覽 handler 跑在有界 worker pool，不在 dispatch 迴圈上 | §5 | — |
| D8 | 每個 HTTP 請求從頭授權 `file.browse`（含 Viewer）；`preview_id` 永不出 Central | §6、§7 | — |
| D8a | 路徑放在 POST 的 JSON body，**任何 URL 都不帶工作區路徑**；edge 另用不含 query 的 log 格式作縱深防禦 | §6 | — |
| D8b | daemon 的 open：先 `StatIn` 判定型別、以非阻塞方式開啟、再對 fd `fstat`＋`SameFile`；不是 `O_NOFOLLOW`，in-root 符號連結由 `RealRel` 二次判定 | §3 | — |
| D9 | 三道閘：Central rollout flag、節點**當下連線**回報、RBAC | §9 | **OD-5** |
| D9a | 停用時**省略** `binary_preview`（schema 為 `const: true`），停用的新 daemon 才能向舊 Central 註冊；Central 版本回退前先停用或回退 daemon | §9 | — |
| D10 | 稽核：敏感拒絕沿用，且**先 commit 再回 HTTP 錯誤**；成功記 `file.binary_preview`，用獨立短 session 寫入，不記路徑 | §6、§10 | **OD-6** |
| D11 | 圖片畫到 canvas（`createImageBitmap`），不用 `<img>`／object URL；CSP 不變 | §11、§13 | `BP-OM-02` |
| D12 | PDF 用 `pdfjs-dist` 顯示層，worker 內解析，無腳本、無註解 DOM、無 XFA | §12 | 版本在 `BP-07` 定 |
| D13 | 記憶體只留畫面上那一份；session／使用者／能力改變時同步清除 | §14 | — |
| D14 | 預覽與下載開關、稽核、型別完全分開；預覽失敗不提供改下載 | §16 | — |

## 4. 階段 DAG

```text
#76 GREEN（前置，非本計畫）
  └─> BP-01 治理（ADR 0029 核准、OD 定案、PRD／traceability／matrix 提案落地）
        └─> BP-02 契約 v1.11.0
              ├─> BP-03 daemon ─────────────┐
              └─> BP-04 Central（fake daemon 可先行）┤
                      └─> BP-05 edge（nginx） │
                                            v
                              BP-06 前端：生命週期＋圖片
                                            v
                              BP-07 前端：PDF.js（含依賴審查）
                                            v
                              BP-08 安全審查（獨立、唯讀）
                                            v
                              BP-09 驗證語料／E2E／效能
                                            v
                              BP-10 實機矩陣
                                            v
                              BP-11 推出（flag off → daemons → flag on）與 rollback 演練
```

**排序理由：** 後端（`BP-03`／`BP-04`）可以早於前端。有能力但沒有入口是安全的方向，
因為 capability 為 false 時 UI 隱藏。`BP-06` 先做圖片，是因為它不需要新依賴，
可以先把「生命週期、清理、狀態」這一半獨立審完；`BP-07` 只多一件事：PDF.js 與它的供應鏈。

## 5. Ticket 與 write-set

同一時間每個 write-set 只有一個 writer。需要跨 write-set 的修改一律停下來交接，或改為序列進行。

| Ticket | 內容 | 獨占 write-set | 相依 |
|---|---|---|---|
| `BP-01` | 治理 | `docs/adr/0029-*.md`（狀態）、`research/prd.md`、`research/tech.md` §11.6、`traceability/requirements.json`、`traceability/links.json`、`scripts/p4/render_permission_matrix.py`、`docs/permission-matrix.md`（**只能重新產生**）、`scripts/traceability/tests/test_traceability.py`（census） | #76 |
| `BP-02` | 契約 | `contracts/v1/schemas/**`、`contracts/v1/fixtures/**`、`contracts/CHANGELOG.md`、三個消費端的 codec（`backend/app/protocol/codec.py`、`daemon/internal/protocol/codec.go`、`frontend/src/protocol/decode.ts`）與其測試 | `BP-01` |
| `BP-03` | daemon | `daemon/internal/files/preview*.go`（新）、`daemon/internal/connection/preview_handlers.go`（新）、`daemon/internal/workspace/root.go`（**只新增** `OpenFileNonBlocking`；既有 `OpenFile` 不改）、`connection.go` 的 dispatch 三行、register payload 的建構處（停用時省略欄位）、`daemon/internal/config/config.go`、`daemon/internal/metrics/metrics.go`、`daemon/internal/files/testdata/preview/**` | `BP-02` |
| `BP-04` | Central | `backend/app/api/http/files.py`（新路由）、`backend/app/services/files.py`（新方法）、`backend/app/services/authz.py`（capability）、`backend/app/services/registry.py`（live 註冊讀取）、`backend/app/api/ws/nodes.py`（`_register_input` 解析 `binary_preview`、設定／清除 live bit）、`backend/app/api/http/schemas.py`（`SessionCapabilities.can_preview_binary`、`_capabilities`）、`backend/app/services/nodes.py`（含只在註冊時設定的 `last_registration_at`）、`backend/app/db/models.py`、`backend/app/db/migrations/versions/0022_*.py`、`backend/app/api/http/nodes.py`、`backend/app/settings.py`、`backend/app/services/audit.py`、`backend/app/api/error_catalog.py`、`docs/error-catalog.md`（產生）、`backend/tests/**` 新檔 | `BP-02` |
| `BP-05` | edge | `deploy/nginx/nginx.conf`、`deploy/railway/nginx.conf.template`（專用 location 與不含 query 的 log 格式）、對應的 railway parity 測試；`BP-OM-06`／`BP-OM-10` 的量測證據（外部） | `BP-04` |
| `BP-06` | 前端生命週期＋圖片 | `frontend/src/composables/useBinaryPreview.ts`（新）、`frontend/src/stores/binaryPreview.ts`（新）、`frontend/src/components/file/ImagePreview.vue`（新）、`PreviewPane.vue`（路由分支）、`PreviewDenied.vue`（新分支文案）、`frontend/src/api/client.ts`＋`dto.ts`（新方法與型別）、`frontend/src/router/authLoss.ts`（**一行**：`wipeUserScoped` 加呼叫） | `BP-04`、#76 已合併 |
| `BP-07` | 前端 PDF | `frontend/package.json`＋lockfile（**唯一新依賴** `pdfjs-dist`）、`frontend/vite.config.*`（worker／asset）、`frontend/src/components/file/PdfPreview.vue`（新）、`frontend/src/pdf/setup.ts`（新）、`frontend/tests/e2e/binary-preview*.spec.ts`（新） | `BP-06` |
| `BP-08` | 安全審查 | `docs/security-review-p31.md`（新）；對實作唯讀 | `BP-07` |
| `BP-09` | 驗證 | fixture 產生器 `scripts/p31/gen_preview_fixtures.py`（新）、E2E、`backend/perf/**` 新情境 | `BP-08` |
| `BP-10` | 實機 | 外部證據目錄（不進 Git），`plan/31/09-…md` 回填 | `BP-09` |
| `BP-11` | 推出 | `docs/release-note-binary-preview.md`、`docs/runbooks/binary-preview.md`、部署設定的 flag | `BP-10`；**`BP-OM-06` 與 `BP-OM-10` 已結案**（發布閘門） |

`frontend/src/router/authLoss.ts` 屬於 #76 的 write-set。`BP-06` 只加一行呼叫，
而且必須等 #76 合併後才動；若屆時該檔結構已變，以「store 的公開 `clear()` 被
sign-out／user 切換／identity pending 三條路徑觸發」這個**性質**為準，不以行號為準。

## 6. 風險

| 風險 | 處置 |
|---|---|
| `file.browse` 語意變寬而組織沒注意到 | release note **第一段**、generated permission matrix 一列明文、`test_authz.py` 路由矩陣一列 Viewer 允許（`BP-01`、`BP-11`） |
| iOS canvas 面積上限與 `createImageBitmap` 行為和假設不同 | `BP-OM-01`／`BP-OM-02` 在 `BP-06` 開工時先量；數字定不下來就不定 OD-2 |
| PDF.js 在 CSP 下需要 ADR 沒預期的放寬 | `BP-OM-04` 在 `BP-07` 第一天用真實標頭跑；任何放寬另行審查，**不得**加第三方 origin |
| PDF.js 新 CVE | pin 精確版本；`BP-11` 的 runbook 要寫 CVE watch 責任人與緊急關閉程序（flag off） |
| 預覽封包擠壓終端延遲 | 512 KiB 分塊加每節點 4 串流上限；`BP-OM-05` 在負載下量 echo 延遲 |
| #71 與本計畫同時改 `services/files.py`、`files.py`、`codec`、manifest、`error_catalog`、`PreviewDenied.vue` | 本計畫在 #71 合併**之後**才開 `BP-02`；若 #71 被放棄，依 README 的條件式編號重排 |
| 部署順序錯誤（新 daemon 先上） | runbook 明文順序；`BP-02` 的 RED 測試證明舊 schema 拒收新欄位；舊 Central 的拒收是**靜默**的（`ws/nodes.py:199-202`），runbook 要教操作者用 node list 的 `daemon_version` 確認 |
| Central 版本回退時，啟用中的新 daemon 註冊不上 | 停用時省略欄位（`const: true`）；回退程序先停用或回退 daemon（`08-…md` `BP-11` §2）；凍結 schema 相容測試 |
| 工作區路徑進入 access log | 路徑只在 POST body；edge 用 `$request_method $uri` 格式；canary 驗證（`BP-OM-10`）是發布閘門 |
| 工作區 FIFO 卡住 worker | 先 `StatIn`、非阻塞開啟、fd `fstat`；「兩個 FIFO＋第三個合法請求」的 deadline 測試 |
| Railway（或任何 edge）的 log／暫存行為無法證實 | 發布閘門；證實不了，該拓樸的 flag **保持關閉**（OD-11）；要改變需產品負責人修訂 AC-09 |
| 完成的串流佔住 daemon handle | Central 在每一種結束路徑都送 `preview_close`；N+1 次連續預覽測試（`03`／`04`） |
| 非阻塞 open 在某平台無法證實 | fail closed：不回報 `binary_preview`；沒有「放棄 goroutine」的後備方案 |
