# 05 — 驗證與 exit（`FD-07`／`FD-08`）

## 1. 測試清單

| 層 | 檔案 | 釘住什麼 |
|---|---|---|
| daemon | `daemon/internal/files/download_test.go` | 七步 default-deny 的兩個方向：敏感必拒、不可呈現必允 |
| daemon | 同上 `TestDownloadCapFitsFrameBound` | 設定預設與 wire 上限沒有漂移 |
| 契約 | `contracts/v1/fixtures/`（九個）＋三個消費端 | wire 上不能有 range／mime |
| Central | `backend/tests/db/test_files_download_api.py` | 標頭、檔名、錯誤碼、稽核、Viewer |
| Central | `backend/tests/test_scope_guards.py` | 型別集合的變動必須是刻意的 |
| Central | `backend/tests/test_authz.py` | 路由矩陣（Viewer 可下載是一列明文） |
| Central | `backend/tests/test_relay_timeouts.py` | 20 秒預算與 PRD 一致 |
| 前端 | `src/composables/useFileDownload.test.ts` | 取代、取消、scope 釋放、錯誤訊息 |
| 前端 | `src/api/download.test.ts` | `Content-Disposition` 兩種形式的優先序 |
| 前端 | `src/components/file/PreviewDenied.test.ts` | 逐分支的下載提議（五個判決） |

### 兩個承重的測試

1. **`TestDownloadAllowsBinaryContent`** ——
   它讓**同一個 PNG** 同時走 `Read` 與 `Download`，斷言兩者答案相反。
   只斷言下載成功是不夠的：那不會攔下一個為了「一致性」
   把二進位判定加回來的修改，而那個修改會移除這個功能存在的理由。

2. **`test_the_response_is_always_an_opaque_attachment`** ——
   它用一個 `report.html` 且內容是 `<script>alert(1)</script>`。
   測試資料本身就是它要防的攻擊，因為三個標頭之中少任何一個，
   這個檔案就會在 console 自己的網域裡執行。

## 2. Release note

`docs/release-note-file-download.md`。**第一段**必須是 `file.browse` 語意變寬，
而且必須點名 Viewer——不是附註，不是最後一節。

第二段是節點開關，因為它是唯一能保留舊語意的方法。

## 3. Runbook

`docs/runbooks/file-download.md`：如何關閉、關閉後使用者會看到什麼、
如何確認某個節點目前的姿態、稽核查詢怎麼寫。

## 4. 安全審查七題

1. 敏感檔案在下載路徑上是否由**同一個**函式判定？（是，且呼叫兩次）
2. 工作區內的符號連結能否繞過它？（不能——第二次判定綁在 fd 解析後的名字上）
3. 節點內容能否在 console 的網域被渲染？（不能——三個標頭是一組）
4. 中央是否留下任何位元組？（否——磁碟、DB、log、metrics label 皆無）
5. 路徑會不會外洩到 log？（不會——只進稽核表，那裡有存取控制）
6. 新的能力是否可由節點拒絕並回報？（是，且是獨立的第三個開關）
7. 授權變寬是否被寫下來而不是被發現？（是——ADR §5、release note 第一段、
   路由矩陣一列、本檔）

## 5. Exit 條件

1. `make check` 全綠（format／lint／typecheck／unit／contract／build／traceability／
   railway／layout／vr gates）。
2. `make test-db` 全綠（需已 migrate 的 PostgreSQL）。
3. `make traceability` 全綠：`FR-FILE-011` 十條 AC 各有四條連結且目標存在。
4. `docs/error-catalog.md` 已由 `render_error_catalog.py --check` 確認未漂移。
5. Release note 與 runbook 已寫，且 release note 第一段是授權變寬。
6. 上面〈成功定義〉的八項判準各有可貼上的輸出。
7. 既有的預覽與兩條上傳路徑的測試與 fixture **全綠且未被修改**
   （唯一例外是 `PreviewDenied` 的文案，見 `01-…md` §6）。
