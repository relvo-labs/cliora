# 09 — 實作狀態

最後更新：2026-09-28。**唯一的「現在到哪了」來源。**

## 1. Ticket 狀態

| Ticket | 狀態 | 備註 |
|---|---|---|
| Phase 1 設計文件 | 完成（`c7b85c5`…`9de2cc7`，四次審查） | ADR 0029 + 本目錄 |
| `BP-01` 治理 | **完成（工作樹，待 commit）** | ADR 0029 `accepted`（2026-09-27）；OD-1…OD-11 全部採建議預設（`01-…md` §6.1）；PRD `FR-FILE-012`＋三處註記；tech §11.6／§11.10；matrix generator＋重新產生；registry／links／census。**偏差**見 §1.1 |
| `BP-02` 契約 | **完成（工作樹，待 commit）** | v1.11.0：六個 schema、`binary_preview` `const:true`、五個 wire 錯誤碼、21 個 fixture、凍結的 1.9.0 `node-register`（`contracts/v1/compat/`，digest 把關）與 `test_contract_compat.py`；Python／Go／TS 三個消費端（Go 另有兩個 response 分支與凍結的 1.9.0 型別表）；CHANGELOG。偏差 DV-8…DV-10 |
| `BP-03` daemon | **完成（工作樹，待 commit）** | `files/preview*.go`（十一步、四種圖片走訪＋PDF 信封、D15 有界解壓、共用 32 MiB／4 handle 池、每連線 handle 表與 janitor）；`workspace.Root.OpenFileNonBlocking`（只新增）；`connection/preview_handlers.go`（open 2／chunk 4 worker，滿了即 `NODE_BUSY`；啟動 FIFO probe，失敗即省略欄位）；`config` 的 `filesystem.binary_preview.*`（只能調低）；metrics；停用時省略 `binary_preview`。`read.go`、`Root.OpenFile`、`go.mod` 無 diff。`0571205` 時七個 fuzz 目標各跑 10 分鐘、無發現：`FuzzSniffPNG`／`FuzzSniffJPEG`／`FuzzSniffGIF`／`FuzzSniffWebP`／`FuzzPDFEnvelope`／`FuzzDecodeBinary`／`FuzzOpenFile`，全數 PASS。偏差 DV-11…DV-14 |
| `BP-04` Central | **完成（工作樹，待 commit）** | `POST …/files/binary-preview`（路徑在 body、拒絕任何 query、只收 JSON `{path}`、≤24 KiB）；兩道閘（flag 預設關、**當下連線**的 `binary_preview`）在送任何 frame 之前；每使用者 2／每節點 4 條串流；拉取式串流（15／10／60 秒）與七個標頭、無 `Content-Disposition`；每種結束路徑都送 `preview_close`（shielded，1 秒）；敏感拒絕先 commit 再 raise；成功稽核 `file.binary_preview` 用獨立 session；`SessionCapabilities.can_preview_binary`；`nodes.binary_preview`／`last_registration_at`（migration `0022`，可降級）；錯誤目錄兩個 Central 碼。偏差 DV-15…DV-17 |
| `BP-05` edge | **設定部分完成；發布閘門開放** | compose／Railway 專用 regex location、`cliora_noquery`、24 KiB body／32 KiB buffer、無 response buffering／temp file；parity 測試與兩份 `nginx -t` 見 §3.1。`BP-OM-06`／`BP-OM-10` 尚未量測，兩種拓樸的 flag 仍須保持關閉 |
| `BP-06` 前端生命週期＋圖片 | **完成** | `useBinaryPreview`（唯一 owner：AbortController、位元組、`ImageBitmap`、canvas；session／能力變更與 auth-loss 皆同步清除；identity pending 只 abort）；`stores/binaryPreview.ts`（`clear()`＋metadata）；`ImagePreview.vue`（canvas、符合寬度、＋／−、雙指與拖曳、44×44 工具列）；`PreviewPane` 路由分支；`PreviewDenied` 16 個二進位狀態文案（皆無下載）；`fetchBinaryPreview`（POST、路徑在 body、無 query）；`authLoss.ts` 一個 import＋一行呼叫。§5 的 13 項 RED→GREEN，另有 E2E（真實 CSP、mocked Central）9 項。偏差 DV-18…DV-25 |
| `BP-07` 前端 PDF.js | **完成** | 依賴審查先行（`docs/security-review-p31.md` 附錄 A）：`pdfjs-dist` **6.3.289** 精確 pin（最新穩定版，≥ 6.2.108；GitHub advisory 對該版 0 筆；`npm audit` 前後相同 6 筆既有項，無新增；Apache-2.0；唯一 transitive 為 optional 的 `@napi-rs/canvas` 1.0.9，MIT，不進 bundle）。`pdf/setup.ts` 是唯一的 `getDocument` 呼叫點（鎖定選項、位元組而非 URL、自建 Worker 以 port 交給 PDF.js、`onPassword` 直接銷毀）；`vite.config.ts` 自寫 plugin 自架 `cmaps`／`standard_fonts`／`wasm`（**不含** QuickJS）／`iccs`；lazy `PdfPreview.vue`（單欄、最多 3 個 canvas、翻頁取消離開的 render、每頁 10 秒、頁碼輸入、縮放、OD-3 提示）；頁數上限在渲染前判定；需要密碼的 PDF 拒絕且無輸入框。首頁 chunk 與 `BP-06` 相同（135 058 B），PDF.js chunk 437 614 B、worker 1 265 413 B。§4 的 4 項 unit 與 6 項 E2E RED→GREEN；E2E 共 19 項 × chromium／Pixel 7 模擬 = 38 項綠。偏差 DV-26…DV-33 |
| `BP-08` 安全審查 | 未開始 | — |
| `BP-09` 驗證 | 未開始 | — |
| `BP-10` 實機 | 未開始 | — |
| `BP-11` 推出 | 未開始 | — |

**沒有任何功能已上線。** Central flag 預設關閉。

### 1.1 實作偏差（與計畫文字不同之處，逐項記錄）

| # | 計畫 | 實際 | 理由 |
|---|---|---|---|
| DV-1 | `01` §7 前置：#76 合併後才做 `BP-01` | #76 仍未合併時即完成 `BP-01`…`BP-04`（後端半部） | 協調者指示；後端不依賴 #76。`BP-06` 仍等 #76 |
| DV-2 | README：#71 未合併則全部編號往前挪一號 | **不重排**；#71 已先合併，保留 0029／v1.11.0／`0022`／`FR-FILE-012`／`FR-CONN-006.AC-13` | 已接上 `0021`，合併 CHANGELOG、PRD、census 與 traceability |
| DV-3 | `01` §5.3：`BP-01` 一次寫完每條 AC 的四條連結 | `BP-01` 只寫 `planned_by`／`specified_by`；`implemented_by`／`verified_by` 在實作該 AC 的階段才加，census 每階段一行 | validator 要求連結目標存在；指向尚未存在的檔案等於宣稱，不是連結 |
| DV-4 | `01` §5：`FR-CONN-006.AC-13` 在 `BP-01` 計入 census | 以 `lifecycle: proposed` 登記，`BP-04` 加入預算時轉 active（+1 另起一行） | `FR-CONN-006` 是 `must`，沒有實作的 active criterion 會讓 coverage 變 blocking |
| DV-5 | `01` §1：`BP-08` 非 FAIL 後才 `accepted` | 產品核准當天即 `accepted`；`BP-08` 改為發布閘門（FAIL 重開 ADR、阻擋 `BP-11`） | 協調者指示「ADR accepted with approval date」 |
| DV-6 | `00` §5 `BP-01` write-set 不含 `docs/traceability/*.md` | 以 `make traceability-render` 重新產生 | master 自 NFR-007 起即 stale（base `157efe3` 上 `render --check` 失敗），不重新產生就無法讓 `traceability-validate` 綠 |
| DV-7 | `01` §5.2：AC-15 的 `verification_profile` 為 `device` | `measurement` | schema 的 enum 沒有 `device`；NFR-006 的 390 px 檢查用的也是 `measurement` |
| DV-8 | `00` §5：錯誤目錄屬 `BP-04` | 五個 **wire** 錯誤碼的目錄項（`error_catalog.py`、`render_error_catalog.py` 分節、`docs/error-catalog.md`）在 `BP-02` 加；Central 專屬的兩碼仍在 `BP-04` | `test_every_protocol_error_code_is_documented` 要求 wire enum 裡的每個碼都有目錄項，不加 `BP-02` 就不綠 |
| DV-9 | 協調者：本次不改 `frontend/`（codec 除外） | `frontend/src/utils/errorCatalog.ts` 的 `GUIDANCE` 多五筆（純資料，無 UI） | `test_the_frontend_knows_every_code_it_can_receive` 要求兩邊的碼集合相同；協調者已接受純資料 frontend 項目 |
| DV-10 | `test_scope_guards.py` 屬 `BP-04` | `test_scope_006` 的 schema 名稱集合在 `BP-02` 加入六個 preview 型別 | 該測試列舉 `schemas/messages/`；schema 一落地就要改 |
| DV-11 | `03` §8：`connection.go` 只多三個 `case` | 另有：`Manager` 一個欄位與其初始化、`registerPayload` 改為先建 map 再呼叫 `reportBinaryPreview`、dispatch 開頭兩行（每連線 handle 表的建立與關閉）、`handleStop` 一行（`session.stop` hook） | 後三項都是計畫本身要求的掛點（`00` §5 的 register／stop hook、`03` §3 的每連線表）；其餘邏輯全在 `preview_handlers.go` |
| DV-12 | `03` §4：三個型別「全部轉交 worker」 | `preview_open`、`preview_chunk` 走 worker；`preview_close` 留在 dispatch 上同步處理 | close 是 O(1) 的 map 刪除；放進有上限的 worker 就可能被 `NODE_BUSY` 拒絕，而 close 正是釋放 snapshot 的那一步 |
| DV-13 | `03` 寫入集：`daemon/internal/files/testdata/preview/**` | 沒有新增二進位 fixture；全部由測試程式碼產生（`preview_fixtures_test.go`） | 每個 fixture 的性質寫在程式裡可審查；跨層共用的語料仍是 `BP-09` 的產生器 |
| DV-14 | `03` §7 `TestPreviewPNGRealWorldICCPasses`：真實 Display P3 截圖 | 以決定性的 536 bytes 假描述檔（Display P3 的大小）代替；另有最壞情況（~1 MiB＋4×256 KiB）的合法 PNG | 本機沒有可授權放進 repo 的真實截圖；真實樣本的分布仍是 `BP-OM-13` |
| DV-15 | 協調者：本次不改 `frontend/`（codec 除外） | 另加 `frontend/src/api/dto.ts` 的 `AUDIT_ACTIONS` 一筆、`utils/auditActions.ts` 標籤一筆與「工作區」篩選群組一筆、`utils/errorCatalog.ts` 兩筆（皆純資料，無 UI；`AuditView.test.ts` 要求每個動作恰好在一個群組） | `test_audit_actions_match_the_frontend_constants` 與 `test_the_frontend_knows_every_code_it_can_receive` 要求兩端集合相同；與 DV-9 同一處置，協調者已接受純資料 frontend 項目 |
| DV-16 | `04` §1 第 5 步：415／413／422／400 | 四種都用既有的 `INVALID_ARGUMENT` 碼，只以 HTTP 狀態區分 | 都是「請求形狀不對」這一類；另開新碼只會多一條目錄項而沒有不同的下一步 |
| DV-17 | `04` §7 `test_preview_does_not_imply_download` | 已補於 `backend/tests/db/test_files_binary_preview_api.py` | #71 已合併；雙向測試證實 preview 可用時下載仍可 403，下載可用時 preview 仍可 409 |

| DV-18 | `05` §0／§5 `focus_returns_to_row`：寫入集內完成 | 另改 `SessionWorkspaceView.vue`（在記憶體保存資料夾、捲動、開啟列，預覽關閉時交回）、`FileBrowser.vue`（`remember`／`resume`）、`FileSearchBar.vue`（一個 `data-rel-path` 屬性）、`useFileBrowser.ts`（一個型別） | 手機上檔案清單在預覽時是卸載的（#76 既有行為），寫入集內做不到；協調者核准「寫入集外的最小修正」。原提案「預覽時以 `v-show` 保留清單」會破壞既有測試（`SessionWorkspaceView.files.test.ts:340` 斷言 `#file-panel` 不存在），故改為記住再還原。文字預覽同樣受益；桌面行為不變（關閉預覽仍聚焦終端機）。位置只在記憶體，不進 URL／history。#77 審查修正：資料夾載入中止會刪除 loading entry；還原等待現在於 `idle`、session／權限變更及元件卸載時結束，並停止 watcher，不留下舊資料夾／列位置 |
| DV-19 | `05` §2：`fetchBinaryPreview` 以串流讀取 | `client.ts` 的方法只送 POST 並回傳未讀的 `Response`；長度與標頭檢查（`readPreviewBody`）在 `useBinaryPreview` | 與 §2「由 owner 以 `ReadableStream` 讀取」一致，並讓這段程式留在預覽的 lazy chunk。首頁 chunk 仍 **+577 B**（134 481 → 135 058）：計畫指定的 `client.ts` 方法與 `authLoss.ts` 必須 import 的 store 都在主 chunk，增量無法為 0；PDF.js（`BP-07`）對主 chunk 的增量另計，須為 0 |
| DV-20 | `05` §1：`routeHint` 含 `pdf` | `BP-06` 只含四種圖片；`pdf` 由 `BP-07` 加入 | `BP-06` 沒有 PDF 渲染器，先加提示只會讓 PDF 落到錯誤狀態 |
| DV-21 | `00` §5：`authLoss.ts` 只加一行 | 一個 import＋`wipeUserScoped` 內一行呼叫；identity pending 的「只 abort」由 composable 自己以 `flush:"sync"` 監看 `auth.identityPending` | 協調者要求 `authLoss.ts` 的 diff 為一個呼叫；第二個呼叫點（`stopPending`）會違反它，而行為相同 |
| DV-22 | ADR 0029 §16：下載入口可依 #71 自己的條件出現 | 二進位路由的任何狀態都**不顯示**標頭的下載按鈕 | 比 ADR 更嚴；協調者要求「沒有任何狀態提供下載或另存」。文字路由（含能力為 false 時的 `FILE_BINARY` 面板）的下載行為不變 |
| DV-23 | `01` §5：traceability 在 `BP-01` 一次寫完 | 依 DV-3：`BP-06` 為 AC-06／08／10 加 implemented_by／verified_by，census +3 verifiable（另起一行），並以 `make traceability-render` 重新產生 `docs/traceability/*.md`；AC-16 的密碼半邊屬 `BP-07`，連結留到那時 | 同 DV-3、DV-6 |
| DV-24 | `05` BP-07 寫入集：`binary-preview*.spec.ts`；`07`：產生器屬 `BP-09` | 圖片 E2E（`binary-preview.spec.ts`＋`binary-preview.harness.ts`）與最小產生器 `scripts/p31/gen_preview_fixtures.py`（PNG／EXIF 6 JPEG／動畫 GIF）隨 `BP-06` 提交；`BP-07` 擴充 PDF | 讓圖片的瀏覽器證據與實作同一個 commit。E2E 用真實 bundle、`deploy/nginx/nginx.conf` 的 CSP 原字串與 mocked Central（不是 full-stack；full-stack 矩陣仍屬 `BP-09`） |
| DV-25 | `05` §4：狀態表 | 多一個內部狀態 `node_unsupported`（`FILE_PREVIEW_UNSUPPORTED_NODE`／`FILE_PREVIEW_DISABLED`）：不顯示文案，直接改走文字路徑 | 節點以停用狀態重連時，行為與 `can_preview_binary=false` 相同（既有 `FILE_BINARY` 面板），不另造一個使用者狀態 |

| DV-26 | `05` BP-07 §2：鎖定選項清單 | 另加 `iccUrl`（自架 `iccs/`） | 6.3.289 以此載入 CMYK 色彩描述檔；不自架就會落回內建處理，自架則維持「沒有第三方 origin」 |
| DV-27 | `05` §2：`enableScripting: false` 由哪一層讀取待確認 | **已確認**：6.3.289 的 `getDocument` 不讀 `enableScripting`（只有 annotation layer 與 viewer 讀），也完全沒有 `isEvalSupported`。兩者仍留在鎖定集合；實際控制是結構性的：不 import `pdf.sandbox*`、不建立 annotation DOM、自架資產**排除** `wasm/quickjs-eval.*`（腳本沙箱的 JS 引擎） | 見 `docs/security-review-p31.md` A.3。若照原樣複製 `wasm/`，origin 上就會有一個文件腳本引擎 |
| DV-28 | `05` §2：worker 以 `new URL("pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url)` 載入 | `?url` import（原樣輸出、帶 hash）＋自建 `new Worker(url, {type:"module"})`，以 `PDFWorker.create({ port })` 交給 PDF.js | Vite 的 `new URL()` 不解析 bare specifier；交 port 而非 `workerSrc`，PDF.js 就沒有「worker 起不來改在主執行緒解析」的 fake-worker 路徑，而且 worker 由我們終止（PDF.js 1 秒內沒收完也照樣終止） |
| DV-29 | `05` §3：目前頁＋相鄰一頁 | 只畫目前頁；canvas 以「每次渲染」為單位、上限 3（縮放時新解析度畫好才替換，避免閃白）；不預先渲染相鄰頁 | 符合「最多 3 個」上限；預渲染是效能選項，v1 不做。#77 審查修正：同頁縮放的新渲染失敗或逾時時，以最新嘗試顯示錯誤與重試，舊 canvas 仍作為畫面備援 |
| DV-30 | `00` §5 BP-07 寫入集 | 新增 `composables/usePanZoom.ts`（圖片與 PDF 共用的縮放／拖曳／雙指），`ImagePreview.vue` 改用它 | 避免兩份相同的手勢程式；`BP-06` 的圖片 E2E 作為回歸，全數仍綠 |
| DV-31 | OD-9：舊瀏覽器顯示「不支援」 | `pdfSupported()` 檢查 6.3.289 無 fallback 直接呼叫的四個 builtin（`Map.prototype.getOrInsertComputed`、`Math.sumPrecise`、`Promise.try`、`Uint8Array.fromBase64`）與 `Worker`；不符就 `unsupported_browser`，而且**不送請求** | 讓引擎不足時有誠實的狀態，而不是文件畫到一半才崩潰；清單寫在 `docs/security-review-p31.md` A.7 |
| DV-32 | `05` §4：E2E「真實 CSP」 | 以 `vite preview` 服務 build 後的 bundle，對每個非 API 回應注入 `deploy/nginx/nginx.conf` 的 CSP 原字串，Central 以 Playwright route 模擬（`binary-preview.harness.ts`）。只跑了 Playwright 的 chromium 與 mobile-chrome-emulated；webkit／firefox 本機未安裝，full-stack 本機無 Go 工具鏈（見 §3.2） | 測的是渲染器、生命週期與 CSP；daemon 與 Central 的閘門有自己的測試，full-stack 矩陣屬 `BP-09` |
| DV-33 | `05` §4 `no_csp_violation`／`07` §1：CJK 字形正確 | E2E 斷言 CMap 以 200 載入、零 violation、頁面渲染完成（`data-rendered`），**不**斷言字形 | 本機 headless Chromium 沒有 CJK 系統字型，非內嵌 CID 字型畫出來是空白；字形正確屬 `BP-10` #6 |

## 2. 外部相依的當下狀態（2026-09-27 核對）

| 項目 | 狀態 | 對本計畫的影響 |
|---|---|---|
| #76（手機檔案清單空白） | **已合併**（2026-09-28 核對：base master `a2d316f` 含 #71 與 #76） | `BP-06` 掛在 master 的 `router/authLoss.ts`（`wipeUserScoped`） |
| PR #71（下載） | 開啟中，mergeable，最後更新 2026-09-16 | 佔用 ADR 0028、`plan/30`、v1.10.0、`0021`、`FR-FILE-011`；本計畫編號排在其後（README） |
| `make traceability` census | 依 #71 描述，master 上自 `NFR-007` 起即為紅燈 | `BP-01` §5 第 4 點 |

## 3. 開放測量（`BP-OM-*`）

每一項都可能推翻某個預設。量到之前，相關的 OD 不算定案。**標為「發布閘門」者未結案時，`BP-11` 不得開始**。

| ID | 問題 | 影響 | 在哪一張票量 | 性質 |
|---|---|---|---|---|
| `BP-OM-01` | iOS Safari 的 canvas 最大面積與單頁總記憶體上限實際是多少？ | OD-2 像素上限；§11 縮放策略 | `BP-06` 開工時；`BP-10` 複驗 | 定預設 |
| `BP-OM-02` | 在現行 CSP（`img-src 'self' data:`）下，iOS／Android 的 `createImageBitmap(Blob)` 是否可用、是否受 `img-src` 約束；`imageOrientation` 與 resize 選項的支援 | 是否需要 `img-src blob:` 的 fallback（需另行審查） | `BP-06` | 定設計。**部分（2026-09-28）**：桌面 Chromium（headless shell 1234）在 production CSP 原字串下可用，`securitypolicyviolation` 0，EXIF 6 正確旋轉（`binary-preview.spec.ts`）。iOS Safari／Android 實機未量（`BP-10`） |
| `BP-OM-03` | iOS Safari 與 Android Chrome 長按 `<canvas>` 是否出現存檔選單 | 「沒有存檔入口」這個宣稱 | `BP-06`；`BP-10` #2 | 定宣稱。`BP-06` 已加 `contextmenu` 攔截與 `-webkit-touch-callout:none`；實機長按仍待 `BP-10` |
| `BP-OM-04` | 選定的 PDF.js 版本在現行 CSP 下：worker、wasm、FontFace、cMap 是否全部可用而無 violation | 是否需要改 CSP（需另行審查） | `BP-07` 第一天 | 定設計。**Chromium 已量（2026-09-28）**：production CSP 原字串下，module worker、`openjpeg.wasm`、CMap、標準字型、內嵌字型全部可用，`securitypolicyviolation` 0、console CSP 訊息 0；**不需改 CSP**。WebKit／Firefox 與實機未量 |
| `BP-OM-05` | 每節點 4 條預覽串流時，以及兩個同時的最貴 D15 中繼資料驗證時，終端 echo 延遲的增量與心跳偏離；**發布門檻在目標硬體實測後設定**，CI 的 p95 容差只用於偵測明顯退步 | 512 KiB 分塊與並發上限 | `BP-09` | 定預設 |
| `BP-OM-06` | 每種部署拓樸上，preview 的請求 body 或回應 body 是否被寫到任何檔案：nginx 的 `proxy_temp`／`client_body_temp`，以及 Railway edge | 「不落地」宣稱；OD-11 | `BP-05` | **發布閘門** |
| `BP-OM-07` | PDF.js 現代 build 在產品支援清單裡最舊的 iOS／Android 瀏覽器上是否可用 | OD-9 | `BP-07`；`BP-10` | 定預設。**`BP-07` 靜態分析**：6.3.289 現代 build 無 fallback 直接呼叫四個很新的 builtin（DV-31），需要當前版本的引擎；與 PRD `NFR-005`「前端支援最新版」一致，OD-9 (a) 維持。實機仍待 `BP-10` |
| `BP-OM-08` | ~~舊 Central 收到帶 `binary_preview` 的 `node.register` 時，是拒收該訊息還是斷線~~ **已由讀程式解答**：拒收該訊息且靜默（`codec.py:100-102` → `ws/nodes.py:199-202` 的 `continue`），不回覆、不持久化、連線照常；daemon 忽略 ack（`connection.go:474-475`）。由 `BP-04` 的 `test_invalid_register_is_silently_skipped` 與 `BP-02` 的相容測試釘住 | 回退程序（ADR §9） | `BP-02`／`BP-04`（測試確認） | 已解答，待測試 |
| `BP-OM-09` | Central 是否為單一 process 服務一個節點的 WebSocket（串流上限用 process 內 semaphore 的前提） | 並發上限的實作方式 | `BP-04` | 定設計 |
| `BP-OM-10` | canary 路徑（原文與 percent-encoded）在兩份 nginx access log、uvicorn／Central stdout、Central JSON log、稽核表、Railway HTTP／deploy log 中是否為零筆 | 「log 無路徑」宣稱；OD-11 | `BP-05`（步驟見 `04-…md` `BP-05`「發布閘門」） | **發布閘門** |
| `BP-OM-11` | ~~`RequestIdMiddleware`（`BaseHTTPMiddleware`）是否破壞 `StreamingResponse` 的背壓或斷線偵測~~ **已量（2026-09-27，Starlette 0.49.1）**：背壓保留，但 `BaseHTTPMiddleware` 的 hand-off 多**一塊**預讀——慢速 client 還拿著第一塊時，Central 最多已要了兩塊（`test_stream_backpressure` 斷言 ≤ 2），所以每條串流在 Central 最多持有 **2 × 512 KiB = 1 MiB 原始資料**，另有編碼與 frame 開銷；已更新 ADR §5 與 `08` §`BP-11` 推出容量估算。client 斷線會取消串流，`preview_close` 恰好送一次，記 `CANCELLED`，沒有成功稽核（`test_disconnect_sends_close`）。兩者都以直接呼叫 ASGI app 的方式跑完整 middleware stack | ADR §6 第 6 步、§15 | `BP-04` | 已量並修訂容量敘述 |
| `BP-OM-12` | PDF.js 是否提供可靠訊號，辨識「不需密碼即可開啟、但有加密」的文件 | 只有 OD-8 選 (b) 時才需要 | `BP-07` 第一天 | 條件式。**已查（6.3.289）**：`getMetadata().info.EncryptFilterName` 在有 `/Encrypt` 時非 null，`getPermissions()` 亦非 null。OD-8 為 (a)，不使用，僅記錄 |
| `BP-OM-13` | 日常檔案裡壓縮附屬 chunk 的實際分布：取 macOS、iOS、Android、Windows 截圖與相機／編輯器匯出各一批樣本，量含 `iCCP`／`zTXt`／`iTXt` 的比例，以及展開後大小的最大值；JPEG／WebP／GIF 中繼資料同樣量 | D15 的預算會不會誤拒正常檔案；「`iCCP` 很常見」這個理由本身 | `BP-03`；`BP-09` 語料 | 定預設 |
| `BP-OM-14` | 池滿載時（兩個 16 MiB handle 各在送 chunk，或一個 16 MiB handle 加兩個進行中的 8 MiB open）daemon 的 RSS 與 GC 開銷 | `07-…md` §3 暫定的「基準＋48 MiB」 | `BP-09` | 定預設 |

### 3.1 `BP-05` 設定驗證（2026-09-28）

- `make railway-check` RED：新增的兩份 edge 測試各因缺 `cliora_noquery` 失敗（2 failed，49 passed）；設定落地後 GREEN。
- `nginx:1.27-alpine` 實際 `nginx -t`：在兩份新 location 的 `proxy_max_temp_file_size` 故意拼錯，compose／Railway 各失敗一次；修正後各通過一次。CI 新增 compose 檢查，Railway 沿用既有步驟。本機因 Docker host daemon 看不到工作樹，以 `docker cp` 將設定與測試憑證放進具標籤的容器；所有容器均移除。
- Central `file_preview_max_body_bytes = 24576`，所以 location 採 `24k`，並以 `32k` 保持請求 body 在記憶體。現有 `/api/` 沒有 `add_header`，新 location 也不宣告 `add_header`，兩者都繼承 server 的安全標頭。
- 計畫範例的 regex 必須加引號：未加引號時 nginx 把 `{36}` 當作設定分隔符而拒絕載入。兩份已使用引號，匹配式本身不變。
- 以上只證實靜態設定與 nginx 可載入。`BP-OM-06` 的暫存檔觀察（含 Railway 前端 edge）與 `BP-OM-10` 的 canary 全鏈 log 搜尋**仍為 OPEN**；在每種拓樸證實前不得開啟 flag 或宣稱發布閘門已過。

### 3.2 `BP-06`／`BP-07` 的驗證環境（2026-09-28）

- **E2E**：`frontend/tests/e2e/binary-preview.spec.ts`（圖片 9 項）與 `binary-preview-pdf.spec.ts`（PDF 10 項），以 `vite preview` 服務 build 後的 bundle，注入 production CSP 原字串，Central 以 route 模擬。在 Playwright `chromium` 與 `mobile-chrome-emulated`（Pixel 7）各跑一次，38／38 綠。這台主機的 Playwright 瀏覽器是 revision 1234，repo 的 `@playwright/test` 1.61.1 預期 1228，因此以**不進 repo** 的暫存 config 指定已安裝的 headless shell；webkit、firefox 未安裝，`mobile-safari-emulated` 與桌面 Safari／Firefox **未執行**。
- **Full-stack**（`E2E_FULL_STACK=1`，`scripts/e2e/run-stack.sh`）**未執行**：本機沒有 Go 工具鏈，無法建出 `agentd`。既有的 full-stack spec 因此是 skipped，不是 passed。
- **Go 閘門**（`gofmt`、`go vet`、`go test -race`、`go build`）在具標籤的 `golang` 容器中以 `docker cp` 執行（本期未改 `daemon/`）。
- 截圖只存在工作區外的暫存目錄，不進 Git。

## 4. 審查中確認、但**不在本期修正**的既有缺陷

以下缺陷在本設計的審查過程中以讀程式確認，都早於本計畫。本期不修（docs-only，且屬於既有路徑），
每一項都要另開議題；本設計也**不複製**它們。

| # | 缺陷 | 證據 | 影響 | 建議 |
|---|---|---|---|---|
| E1 | 文字預覽以阻塞方式開啟 FIFO，而且是在 daemon 的 dispatch 迴圈上 | `read.go:25` → `workspace/root.go:109-118`（`os.Root.Open`）；`connection.go:509` | 可在工作區建立 FIFO 的使用者（例如用終端機的 Developer），加上任何點了該檔的 `file.browse` 持有者，就能讓整台節點的控制迴圈停住：終端輸入、心跳、其他 session 全部受影響 | 以 `Root.OpenFileNonBlocking` 與開啟前 `Stat` 修正 `Read`，並把 `handleFsRead` 移出 dispatch 迴圈 |
| E2 | 既有 GET 檔案路由把工作區路徑與搜尋關鍵字放在 query string，而兩份 nginx access log 與 uvicorn access log 都會記下 | `api/http/files.py:44-73`、`:203-207`；`nginx.conf:52-55`；`railway/nginx.conf.template:64-67`；uvicorn 0.35.0 `protocols/utils.py:52-56`；`backend.Dockerfile:147` | Central 自己刻意只記關鍵字的 digest（`services/files.py:300-304`），但 edge 與 uvicorn 記的是原文 | 路徑與關鍵字改用 body，或至少讓這些路由的 access log 不含 query |
| E3 | `/api/` 回應可能溢寫到 nginx `proxy_temp` | `nginx.conf:174`、`railway/nginx.conf.template:159` | 文字預覽內容可能落在 edge 磁碟上 | 與 `BP-05` 同一組指令 |
| E4 | `read.go:12` 的註解寫「`O_NOFOLLOW` open」，實際是跟隨 in-root 符號連結的 `os.Root.Open` | `read.go:12` 對照 `workspace/root.go:100-118` | 誤導後續設計，本 ADR 初版就照抄了這個錯誤 | 修正註解 |
| E5 | generated permission matrix 缺 `file.upload`、`terminal.shell`、`tunnel.*`、`integration.manage` | `render_permission_matrix.py:29-40` 對照 `rbac.py` | 文件少列權限 | 見 `01-…md` §4 |
| E6 | ORM models 與 migration 建出的 schema 不一致：12 個 index 與 1 個 unique constraint 只存在於 migration（`audit_logs`、`node_metric_samples`、`node_tunnels`、`terminal_sessions`、`workspace_favorites`） | base `157efe3` 上 `alembic.autogenerate.compare_metadata` 回報 14 筆差異；`test_schema.py` 只比對欄位名稱，看不到 | 任何以 autogenerate 產生的新 migration 都會試圖刪掉這些 index | 在 models 上宣告這些 index／constraint，並把 `test_schema.py` 升級為 `compare_metadata` 為空。`test_migration_0022_roundtrip` 暫時只檢查 `nodes` 表 |
| E7 | `app/api/http/schemas.py` 有一個多餘的 `# type: ignore[arg-type]`；`make typecheck`（在 repo 根目錄跑 `mypy backend/app`）看不到，在 `backend/` 內以其 `pyproject.toml` 設定跑 `mypy app` 才報 | base `157efe3` 上 `cd backend && mypy app` → `schemas.py:518: Unused "type: ignore"`；同一時間 `make typecheck` 綠 | 兩種執行方式採用不同設定，閘門與開發者本機的結果不一致 | 移除該註解，並讓 `make typecheck` 使用 `backend/pyproject.toml` 的 mypy 設定 |
| E8 | `make traceability-validate` 在 master 上是紅的：`docs/traceability/{matrix,coverage,mvp,owners}.md` 未重新產生；census 也少了 NFR-007 的 +7 | base `157efe3` 上 `scripts/trace render --check` 失敗；census 458≠451 | 同上 | 本期已順帶修正（DV-6 與 census 的 +7 行）；#71 也帶有同一修正，後合併者需解衝突 |
| E9 | `TestClassifyLatencyBudget`（2 MiB 分類 ≤ 5 ms）在負載高的機器上會隨機失敗 | 本機 load ≈ 10／8 核時量到 5.47 ms；單獨重跑 1／3 次通過 | 牆鐘預算測試在共用 CI 上會 flake | 以多次取最小值或 `testing.B` 取代單次量測 |
| E10 | 沒有 `session.view` 的使用者，對不存在的 session 得到 404、對存在的得到 403，可藉此探測 session id 是否存在 | `services/files.py` `_resolve()`：先 `get`（404）再 `authorize_file_browse`（403）；所有檔案路由共用 | 三個內建角色都持有 `session.view`，只影響自訂角色 | 先做 action 層以外的 view 判定再回 404，或兩者統一回 403 |
| E11 | 手機上從預覽返回時，檔案清單回到工作區根目錄、捲動歸零、焦點落在 `<body>`（文字預覽同樣如此） | `SessionWorkspaceView.vue` 的 `<aside v-if="session && filesVisible">` 在預覽模式下卸載 `FileBrowser`，`useFileBrowser` 的 `cwd` 隨之消失 | 違反 plan/29 MS-15／MS-16 的「返回時還原」 | **本期已修**（DV-18），`focus_returns_to_row` 於 Vitest 與 E2E 各驗一次 |
| E12 | Porcelain（明亮）主題的桌面預覽標頭：檔名與「唯讀」標記用 `--text-primary`，但底下的 `.center` 一律是 `--terminal-background`，對比不足（文字預覽相同） | `PreviewPane.vue` `h2 { color: var(--text-primary) }` 對照 `SessionWorkspaceView.vue` `.center { background: var(--terminal-background) }`；1440×900 截圖 | 桌面明亮主題下看不清正在預覽哪個檔案 | 標頭改用 `--text-on-terminal*` 系列，或讓 `.head` 有自己的面板底色；另開議題 |
| E13 | `frontend/tests/e2e/mobile.spec.ts`「every visible control on the sign-in page reaches the touch floor」在 390 px 失敗：兩個輸入框 276×37、登入鈕 276×41（下限 44） | 以本分支 `BP-06` 之前的 `28e747d` 另行 build（bundle `index-Dhlc2B59.js` 與記錄的基準相同）重跑，結果完全相同；chromium 與 mobile-chrome-emulated 皆然 | 手機登入頁控制項低於觸控下限，既有 E2E 為紅 | 與本期無關；另開議題（`--density-control` 在 < 768 px 的值或 LoginView 的樣式） |

## 5. 本版文件中明確標為「未驗證」的假設

- iOS canvas 面積上限 16 777 216 px 是常見報告的數字，不是實測（`BP-OM-01`）。
- 以 Blob 呼叫 `createImageBitmap` 不受 `img-src` 約束（`BP-OM-02`）。
- nginx 在預設設定下會把大回應溢寫到 `proxy_temp`，把超過 buffer 的請求 body 寫到 `client_body_temp`。依 nginx 文件如此，本部署未實測（`BP-OM-06`）。
- ~~`os.Root.OpenFile` 會把 `O_NONBLOCK` 原樣傳給 `openat`~~ **linux/amd64 已證實（2026-09-27，go1.26.0）**：`TestOpenFileNonBlockingOnFifoReturns` 對沒有寫入端的 FIFO 立即返回，fd 即該 FIFO；`TestStartupProbePassesOnThisPlatform` 同樣通過。**linux/arm64 未執行**（本機無模擬器，只跑了 `GOARCH=arm64 go vet`），由執行期 probe 把關：失敗即不回報 `binary_preview`。CI 的 arm64 執行仍待補。
- ~~PDF.js 的 WebAssembly 解碼器與 FontFace 在現行 CSP 下可用（`BP-OM-04`）~~ **Chromium 已證實**（`BP-07`，見 `BP-OM-04`）；WebKit／Firefox／實機未量。
- PDF.js 的 `stopAtErrors: true` 不會誤拒常見的良性 PDF（`BP-09` 語料驗證）。`BP-07` 的產生語料（40／200 頁、CJK、JPX、主動內容、六種加密）全部未被誤拒；只有信封正常、物件圖損毀的 `broken-xref.pdf` 被拒（預期）。真實世界語料仍屬 `BP-09`。
- ~~PDF.js 對只有權限密碼的 PDF 會不經提示開啟，對需要使用者密碼的 PDF 會呼叫 `onPassword`~~ **Chromium 已證實**：RC4-40／AES-128／AES-256 各一，有使用者密碼者呼叫 `onPassword` 並被拒、worker 已終止；空使用者密碼者直接顯示（`binary-preview-pdf.spec.ts`）。
- Starlette／uvicorn 的 `StreamingResponse` 在完整 middleware stack 下會把 client 的背壓傳回 generator（`BP-OM-11`）。
- FastAPI 0.120.1 的 yield dependency 相對於串流 body 的結束時機：本設計**不依賴**它，成功稽核用獨立 session（ADR §6 第 7 步）。
- PDF.js 版本下限 **≥ 6.2.108**：CVE-2026-16633 已於 2026-09-27 以 GitHub Advisory API 查證；CVE-2024-4367 依公開紀錄。授權（Apache-2.0）與實際 pin 在 `BP-07` 核對，advisory 於 pin 當天與發布前再查一次。
- ~~`enableScripting` 由 pinned 版本的哪一層讀取~~ **已確認**：只有 annotation layer 與 viewer 讀取，`getDocument` 不讀（DV-27）。
- ~~daemon 有可寫的私有狀態目錄可供啟動 probe 建 FIFO~~ **已核對**：probe 用 `tmux.ResolveConfigDir()`，也就是 systemd `RuntimeDirectory=agentd` 給的 `/run/agentd`（`$RUNTIME_DIRECTORY`；開發環境退回 `$XDG_RUNTIME_DIR/agentd` 或 `/tmp/agentd-<uid>`），與產生的 tmux 設定同一處；FIFO 名稱帶 ULID，用完即刪。建立失敗同樣 fail closed。

## 6. 設計審查處置（`c7b85c5` 的獨立審查，判定 BLOCKED）

| 發現 | 嚴重度 | 處置 | 改在哪裡 |
|---|---|---|---|
| 預覽路徑會進 edge access log（`?path=` × `"$request"`） | P1 | **改設計**：路徑移到 POST JSON body，URL 不帶任何 query（路由拒絕 query）；專用 location 用 `cliora_noquery` 格式作縱深防禦；請求 body 不得溢寫（`client_body_buffer_size` ≥ 上限）。另外發現 uvicorn access log 同樣帶 query，一併處理。canary 驗證涵蓋兩份 edge log 與 Central／uvicorn log；`BP-OM-06`／`BP-OM-10` 列為**發布閘門**；Railway 量不到的部分依新增的 OD-11 處理。考慮過的替代方案（GET＋關 log、opaque handle）與取捨寫在 ADR §6 | ADR Context、§6、T17、Alternatives；`04` 全篇；`00`、`06`、`07`、`08`、本檔 |
| FIFO／特殊檔可佔住 preview worker；`O_NOFOLLOW` 描述不正確 | P1 | **修正**：開啟前 `Stat` 型別檢查 → 侷限的 `O_NONBLOCK` 開啟 → fd `fstat`＋`SameFile`；RED 測試「兩個 FIFO＋第三個合法請求於 deadline 內完成」；描述改為 `os.Root` 的實際行為（in-root 連結會被跟隨，由 `RealRel` 二次判定）。文字預覽的同一缺陷列為既有 E1 | ADR Context、§3、T9；`03` §1、§7 |
| 停用的新 daemon 仍送 `binary_preview`，Central 無法回退 | P1 | **改設計**：停用時省略欄位，schema 改為 `const: true`（`false` 無效）；凍結的舊 schema 相容測試；回退程序與錯誤示範寫進 runbook 與演練。同時以讀程式確認舊 Central 的拒收是靜默的（原 `BP-OM-08`） | ADR §9、T14、Alternatives；`02` §2、§4、§6；`03` §5、§7；`04` §3、§7；`08` §1、§2 |
| 敏感拒絕稽核未在 raise 前 commit | P2 | **修正**：service 回傳拒絕結果，路由先 commit 再 raise；成功稽核改用獨立短 session；測試斷言 403 後以另一個 session 查得到該列，並做 mutation check | ADR §6 第 5、7 步；`04` §1、§4、§7 |
| capability 寫入集缺 `schemas.py`、`ws/nodes.py` | P2 | **修正**：寫入集補上並逐檔說明；新增「重連同時翻轉端點閘門與 session capability」與「五個回傳點都帶 capability」兩條測試 | ADR §9；`00` §5；`04` 寫入集、§3、§7 |
| 「拒絕加密 PDF」超出可執行範圍 | P2 | **改設計**：移除 daemon 的 `/Encrypt` 啟發式；OD-8 明確處理只有權限密碼的 PDF（建議：照常唯讀顯示），需要密碼者由渲染器拒絕且不提示；AC 文字改為可執行的規則；`encrypted` 不再是 wire reason | ADR §3、§4、§12；`01` AC-05、OD-8；`02` §3、§4；`03` §2；`05`；`07`；`08` |
| `test_success_audit_has_no_path` 過嚴 | P3 | **修正**：允許 `request_id`／`source`，同時列出禁止的 key，並檢查值不含 canary 片段 | ADR §10；`04` §7 |
| 量測閘門（`BP-OM-01/02/04/06/07/09`） | — | `BP-OM-06` 升為**發布閘門**，新增 `BP-OM-10`（發布閘門）、`BP-OM-11`、`BP-OM-12` | 本檔 §3 |

## 7. 變更紀錄

| 版本 | commit | 內容 |
|---|---|---|
| v0.1 | `c7b85c5` | 初版設計 |
| v0.2 | `7458141` | 回應第一次獨立審查（BLOCKED）：見 §6 |
| v0.3 | `653ff61` | 回應 `7458141` 的再審查（BLOCKED），各項處置見下方第一張表 |
| v0.4 | `bad3a2b` | 回應 `653ff61` 的第三次審查（BLOCKED），各項處置見下方第二張表 |

| 發現 | 嚴重度 | 處置 | 改在哪裡 |
|---|---|---|---|
| OD-11 的建議預設允許在未證實的 edge 上出貨，與端到端的 AC-09 衝突 | P1 | **改預設**：未證實的拓樸（Railway 或任何 edge）flag **保持關閉**；「限定宣稱」改為必須由產品負責人明確修訂 AC-09 才能選。AC-09、OD-11、推出條件、發布閘門與 release note 文字一致化 | ADR §6；`01` AC-09、OD-11；`00` 風險；`04` `BP-05`；`06` Q14；`08` `BP-11` |
| 成功的串流不送 `preview_close`，snapshot 佔住 handle 直到 TTL | P1 | **修正**：`finally` 在成功、錯誤、取消三種路徑都送 close；TTL 只作 backstop。新增 RED：N+1 次連續成功預覽（時鐘凍結）、close 後 handle 立即歸零、取消與錯誤路徑也釋放 | ADR §5、§6；`03` §7；`04` §1、§7；`06` Q17；`07` |
| 回退演練以 `daemon_version` 作為註冊被接受的證據 | P2 | **修正**：新 Central 用新欄位 `nodes.last_registration_at`（migration `0022`，只在 `persist_registration` 設定，API 唯讀回傳，不是契約變更，已加入 `BP-04` 寫入集與測試）；舊 Central 沒有該欄位，改用一次性的 `node.name` 標記（舊 Central 只在接受註冊時寫入 `name`）。演練全程 `daemon_version` 不變 | ADR §9；`00`／`04` 寫入集；`04` §7；`07`；`08` §1、§2 |
| 非阻塞 open 的後備方案會放棄卡住的 goroutine | P2 | **移除後備方案**：無法證實的 build target 不回報能力；執行期 probe 在 daemon 自己的 FIFO 上測試，失敗時自行解開並省略 `binary_preview`（fail closed） | ADR §3；`03` §1、§7；`06` Q18 |
| PDF.js 版本下限未涵蓋 CVE-2026-16633 | P2 | **已查證並提高下限**：GitHub Advisory API 顯示 GHSA-hq66-cqwq-w95j 影響 `>= 5.6.83, < 6.2.108`，首個修正版 6.2.108。下限改為 ≥ 6.2.108，並明列於 `BP-07`；加上 `enableScripting: false`；advisory 重查列為 pin 與發布的閘門 | ADR §12、T2；`05` `BP-07` §1、§2；`06` §3 |
| `root.Stat` 不存在；AC-05 的範圍超出 daemon 的信封檢查 | P3 | **修正**：改為 `StatIn`（`root.go:196-212`）；AC-05 限定為 Node 端信封拒絕，新增 AC-16 描述瀏覽器端解析／渲染失敗（census +16） | ADR §3；`00`、`03`、`06`、README；`01` §2.1、§5 |
| v0.5 | （未 commit） | 關閉第四次審查（`bad3a2b`，PASS_WITH_FOLLOWUPS）的三個文件追蹤項，見下方第三張表 |

**v0.4（回應 `653ff61` 的第三次審查）**

| 發現 | 嚴重度 | 處置 | 改在哪裡 |
|---|---|---|---|
| PNG 壓縮附屬 chunk（`iCCP`／`zTXt`／`iTXt`）只限壓縮後大小，沒有展開後上限 | P1 | **採用有界串流解壓（決策 D15，不列入 OD）**：以標準函式庫 `compress/zlib` 解壓到丟棄端，量展開後大小，超過預算就停；只量不改，不轉碼、不剝除；像素資料照舊不解壓。**不採用「一律拒絕」**，因為 `iCCP` 在 macOS／iOS 截圖與編輯器匯出中很常見，頻率未實測（`BP-OM-13`）。JPEG APPn／ICC、WebP `ICCP`／`EXIF`／`XMP `／`ANMF`、GIF extension／幀數、APNG 幀數一律以長度或數量設預算。新增炸彈、邊界與真實世界樣本的 RED fixture | ADR §3、§4、T3；`03` §2、§2.1、§7；`07` §1；`00` D15；本檔 `BP-OM-13` |
| Migration `0022` 的降級只刪一個欄位 | P2 | **修正**：`downgrade()` 移除兩個欄位與索引；新增 `test_migration_0022_roundtrip`（upgrade → downgrade → upgrade，並以 `compare_metadata` 斷言沒有 drift），列入寫入集；回退表註明先完成 `last_registration_at` 的確認，再降級 | `04` 寫入集、§8；`08` §2；`00` 寫入集 |
| 風險表仍以 `daemon_version` 作為註冊證據；nginx 範例只有 compose 的 upstream | P2 | **修正**：風險表改用 `last_registration_at` 與名稱標記；分別寫出 compose（具名 upstream）與 Railway（`set $cliora_upstream` 加 `$request_uri`，依 `resolver` 在執行期解析）兩份 stanza；兩份渲染後的設定都要 `nginx -t`：Railway 沿用既有 CI 步驟，compose 新增一步（`.github/workflows/ci.yml` 列入 `BP-05` 寫入集） | `00` 風險、寫入集；`04` `BP-05` |

**v0.5（關閉第四次審查 `bad3a2b` 的追蹤項，PASS_WITH_FOLLOWUPS）**

| 發現 | 嚴重度 | 處置 | 改在哪裡 |
|---|---|---|---|
| D15 缺少並發最壞情況的資源測試 | P2 | **已補**：`TestPreviewConcurrentWorstCaseMetadata`，兩個 worker 同時驗證最貴的合法 PNG，並有 terminal 流量與心跳；另以 `GOMAXPROCS=1` 跑一次。暫定目標：驗證 < 1 s、echo 增量 p95 < 50 ms、心跳偏離 < 1 s，以 `BP-OM-05` 定案。full-stack 版列入 `07` §3 | `03` §7；`07` §3；本檔 `BP-OM-05` |
| 容量目標「4 個 16 MiB handle」超出 32 MiB 的 handle 池，無法執行 | P2 | **已修正**：改用兩種允許的組合，RSS 目標改為暫定的「基準＋48 MiB」並計入進行中的 open（`BP-OM-14`）。同時把 32 MiB 明定為 handle 與進行中 open **共用**的預留池，並新增 `TestPreviewPoolReservesInProgressOpens` | `03` §3、§7；`07` §3；本檔 `BP-OM-14` |
| D15 宣稱「每個串流輸入 ≤ 1 MiB」，但只有 `iCCP` 有這個上限 | P3 | **已修正**：新增逐 chunk 的壓縮輸入上限（`zTXt`／壓縮 `iTXt` 各 ≤ 256 KiB）與壓縮輸入合計 ≤ 2 MiB，兩者都在解壓**前**檢查；邊界測試斷言超限時解壓讀取量為 0 | `03` §2.1、§7 |
