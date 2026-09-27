# 09 — 實作狀態

最後更新：2026-09-27。**唯一的「現在到哪了」來源。**

## 1. Ticket 狀態

| Ticket | 狀態 | 備註 |
|---|---|---|
| Phase 1 設計文件 | **本版提交（未 commit）** | ADR 0029（`proposed`）＋本目錄 |
| `BP-01` 治理 | 未開始 | 等 #76 合併、#71 狀態確定、產品決策 OD-1…OD-11 |
| `BP-02` 契約 | 未開始 | — |
| `BP-03` daemon | 未開始 | — |
| `BP-04` Central | 未開始 | — |
| `BP-05` edge | 未開始 | — |
| `BP-06` 前端生命週期＋圖片 | 未開始 | 依賴 #76 合併 |
| `BP-07` 前端 PDF.js | 未開始 | — |
| `BP-08` 安全審查 | 未開始 | — |
| `BP-09` 驗證 | 未開始 | — |
| `BP-10` 實機 | 未開始 | — |
| `BP-11` 推出 | 未開始 | — |

**沒有任何功能已上線，沒有任何測試已寫。** 本版只有設計文件。

## 2. 外部相依的當下狀態（2026-09-27 核對）

| 項目 | 狀態 | 對本計畫的影響 |
|---|---|---|
| #76（手機檔案清單空白） | 開啟中；修補在本機分支 `fix/mobile-file-browser-76` @ `a453bd4`，**尚未推送**（見 #76 留言） | `BP-06` 的 auth-loss 掛點（`router/authLoss.ts`）只存在於該分支 |
| PR #71（下載） | 開啟中，mergeable，最後更新 2026-09-16 | 佔用 ADR 0028、`plan/30`、v1.10.0、`0021`、`FR-FILE-011`；本計畫編號排在其後（README） |
| `make traceability` census | 依 #71 描述，master 上自 `NFR-007` 起即為紅燈 | `BP-01` §5 第 4 點 |

## 3. 開放測量（`BP-OM-*`）

每一項都可能推翻某個預設。量到之前，相關的 OD 不算定案。**標為「發布閘門」者未結案時，`BP-11` 不得開始**。

| ID | 問題 | 影響 | 在哪一張票量 | 性質 |
|---|---|---|---|---|
| `BP-OM-01` | iOS Safari 的 canvas 最大面積與單頁總記憶體上限實際是多少？ | OD-2 像素上限；§11 縮放策略 | `BP-06` 開工時；`BP-10` 複驗 | 定預設 |
| `BP-OM-02` | 在現行 CSP（`img-src 'self' data:`）下，iOS／Android 的 `createImageBitmap(Blob)` 是否可用、是否受 `img-src` 約束；`imageOrientation` 與 resize 選項的支援 | 是否需要 `img-src blob:` 的 fallback（需另行審查） | `BP-06` | 定設計 |
| `BP-OM-03` | iOS Safari 與 Android Chrome 長按 `<canvas>` 是否出現存檔選單 | 「沒有存檔入口」這個宣稱 | `BP-06`；`BP-10` #2 | 定宣稱 |
| `BP-OM-04` | 選定的 PDF.js 版本在現行 CSP 下：worker、wasm、FontFace、cMap 是否全部可用而無 violation | 是否需要改 CSP（需另行審查） | `BP-07` 第一天 | 定設計 |
| `BP-OM-05` | 每節點 4 條預覽串流時，終端 echo 延遲的增量 | 512 KiB 分塊與並發上限 | `BP-09` | 定預設 |
| `BP-OM-06` | 每種部署拓樸上，preview 的請求 body 或回應 body 是否被寫到任何檔案：nginx 的 `proxy_temp`／`client_body_temp`，以及 Railway edge | 「不落地」宣稱；OD-11 | `BP-05` | **發布閘門** |
| `BP-OM-07` | PDF.js 現代 build 在產品支援清單裡最舊的 iOS／Android 瀏覽器上是否可用 | OD-9 | `BP-07`；`BP-10` | 定預設 |
| `BP-OM-08` | ~~舊 Central 收到帶 `binary_preview` 的 `node.register` 時，是拒收該訊息還是斷線~~ **已由讀程式解答**：拒收該訊息且靜默（`codec.py:100-102` → `ws/nodes.py:199-202` 的 `continue`），不回覆、不持久化、連線照常；daemon 忽略 ack（`connection.go:474-475`）。由 `BP-04` 的 `test_invalid_register_is_silently_skipped` 與 `BP-02` 的相容測試釘住 | 回退程序（ADR §9） | `BP-02`／`BP-04`（測試確認） | 已解答，待測試 |
| `BP-OM-09` | Central 是否為單一 process 服務一個節點的 WebSocket（串流上限用 process 內 semaphore 的前提） | 並發上限的實作方式 | `BP-04` | 定設計 |
| `BP-OM-10` | canary 路徑（原文與 percent-encoded）在兩份 nginx access log、uvicorn／Central stdout、Central JSON log、稽核表、Railway HTTP／deploy log 中是否為零筆 | 「log 無路徑」宣稱；OD-11 | `BP-05`（步驟見 `04-…md` `BP-05`「發布閘門」） | **發布閘門** |
| `BP-OM-11` | `RequestIdMiddleware`（`BaseHTTPMiddleware`，`middleware.py:41`）是否破壞 `StreamingResponse` 的背壓或斷線偵測 | ADR §6 第 6 步「真正的背壓」與 §15 取消 | `BP-04`（完整 middleware stack 下的測試） | 定設計 |
| `BP-OM-12` | PDF.js 是否提供可靠訊號，辨識「不需密碼即可開啟、但有加密」的文件 | 只有 OD-8 選 (b) 時才需要 | `BP-07` 第一天 | 條件式 |

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

## 5. 本版文件中明確標為「未驗證」的假設

- iOS canvas 面積上限 16 777 216 px 是常見報告的數字，不是實測（`BP-OM-01`）。
- 以 Blob 呼叫 `createImageBitmap` 不受 `img-src` 約束（`BP-OM-02`）。
- nginx 在預設設定下會把大回應溢寫到 `proxy_temp`，把超過 buffer 的請求 body 寫到 `client_body_temp`。依 nginx 文件如此，本部署未實測（`BP-OM-06`）。
- `os.Root.OpenFile` 會把 `O_NONBLOCK` 原樣傳給 `openat`（`03-…md` §1；`TestOpenFileNonBlockingOnFifoReturns`）。
- PDF.js 的 WebAssembly 解碼器與 FontFace 在現行 CSP 下可用（`BP-OM-04`）。
- PDF.js 的 `stopAtErrors: true` 不會誤拒常見的良性 PDF（`BP-09` 語料驗證）。
- PDF.js 對只有權限密碼的 PDF 會不經提示開啟，對需要使用者密碼的 PDF 會呼叫 `onPassword`（`BP-07` E2E）。
- Starlette／uvicorn 的 `StreamingResponse` 在完整 middleware stack 下會把 client 的背壓傳回 generator（`BP-OM-11`）。
- FastAPI 0.120.1 的 yield dependency 相對於串流 body 的結束時機：本設計**不依賴**它，成功稽核用獨立 session（ADR §6 第 7 步）。
- PDF.js 版本下限 **≥ 6.2.108**：CVE-2026-16633 已於 2026-09-27 以 GitHub Advisory API 查證；CVE-2024-4367 依公開紀錄。授權（Apache-2.0）與實際 pin 在 `BP-07` 核對，advisory 於 pin 當天與發布前再查一次。
- `enableScripting` 由 pinned 版本的哪一層（display API 或 viewer）讀取，未驗證（`BP-07`）；結構性控制仍是不附 scripting bundle。
- daemon 有可寫的私有狀態目錄可供啟動 probe 建 FIFO（`03-…md` §1）；實際路徑在 `BP-03` 核對。

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
| v0.3 | （未 commit） | 回應 `7458141` 的再審查（BLOCKED），各項處置如下 |

| 發現 | 嚴重度 | 處置 | 改在哪裡 |
|---|---|---|---|
| OD-11 的建議預設允許在未證實的 edge 上出貨，與端到端的 AC-09 衝突 | P1 | **改預設**：未證實的拓樸（Railway 或任何 edge）flag **保持關閉**；「限定宣稱」改為必須由產品負責人明確修訂 AC-09 才能選。AC-09、OD-11、推出條件、發布閘門與 release note 文字一致化 | ADR §6；`01` AC-09、OD-11；`00` 風險；`04` `BP-05`；`06` Q14；`08` `BP-11` |
| 成功的串流不送 `preview_close`，snapshot 佔住 handle 直到 TTL | P1 | **修正**：`finally` 在成功、錯誤、取消三種路徑都送 close；TTL 只作 backstop。新增 RED：N+1 次連續成功預覽（時鐘凍結）、close 後 handle 立即歸零、取消與錯誤路徑也釋放 | ADR §5、§6；`03` §7；`04` §1、§7；`06` Q17；`07` |
| 回退演練以 `daemon_version` 作為註冊被接受的證據 | P2 | **修正**：新 Central 用新欄位 `nodes.last_registration_at`（migration `0022`，只在 `persist_registration` 設定，API 唯讀回傳，不是契約變更，已加入 `BP-04` 寫入集與測試）；舊 Central 沒有該欄位，改用一次性的 `node.name` 標記（舊 Central 只在接受註冊時寫入 `name`）。演練全程 `daemon_version` 不變 | ADR §9；`00`／`04` 寫入集；`04` §7；`07`；`08` §1、§2 |
| 非阻塞 open 的後備方案會放棄卡住的 goroutine | P2 | **移除後備方案**：無法證實的 build target 不回報能力；執行期 probe 在 daemon 自己的 FIFO 上測試，失敗時自行解開並省略 `binary_preview`（fail closed） | ADR §3；`03` §1、§7；`06` Q18 |
| PDF.js 版本下限未涵蓋 CVE-2026-16633 | P2 | **已查證並提高下限**：GitHub Advisory API 顯示 GHSA-hq66-cqwq-w95j 影響 `>= 5.6.83, < 6.2.108`，首個修正版 6.2.108。下限改為 ≥ 6.2.108，並明列於 `BP-07`；加上 `enableScripting: false`；advisory 重查列為 pin 與發布的閘門 | ADR §12、T2；`05` `BP-07` §1、§2；`06` §3 |
| `root.Stat` 不存在；AC-05 的範圍超出 daemon 的信封檢查 | P3 | **修正**：改為 `StatIn`（`root.go:196-212`）；AC-05 限定為 Node 端信封拒絕，新增 AC-16 描述瀏覽器端解析／渲染失敗（census +16） | ADR §3；`00`、`03`、`06`、README；`01` §2.1、§5 |
