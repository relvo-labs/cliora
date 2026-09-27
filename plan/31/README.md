# Cliora 唯讀二進位預覽：圖片與 PDF（含 Viewer）

版本：**v0.2（提案，僅設計）**。v0.1 = `c7b85c5`；v0.2 回應該版的獨立設計審查（BLOCKED），各項處置見 `09-…md` §6
議題：#77。基準：master `157efe3178999a8c35b34f55ee183d47842c63ec`。
決策文件：[`docs/adr/0029-read-only-binary-preview.md`](../../docs/adr/0029-read-only-binary-preview.md)（`proposed`）。
Ticket 前綴 `BP-`（**B**inary **P**review）。開放測量為 `BP-OM-*`，產品決策為 `OD-*`。

> **本目錄只是規劃，不等於已上線**（#77 驗收末項）。截至本版，
> `frontend/`、`backend/`、`daemon/`、`contracts/` 沒有任何一行為本功能改動。

## 為什麼是 `plan/31` 而不是 `plan/30`

開啟中的 PR #71（檔案下載）已經佔用 `plan/30/`、ADR 0028、契約 v1.10.0、
migration `0021`、`FR-FILE-011` 與 `node-register.file_download`。
本計畫的每一個編號都**排在它後面**，並且與它**不共用任何名稱**：

| 項目 | PR #71（下載） | 本計畫（預覽） |
|---|---|---|
| ADR | 0028 | **0029** |
| plan 目錄 | `plan/30/` | **`plan/31/`** |
| 契約版本 | v1.10.0 | **v1.11.0**（提案） |
| 需求 ID | `FR-FILE-011` | **`FR-FILE-012`**（提案，未登記） |
| 訊息型別 | `filesystem.download`／`downloaded` | **`filesystem.preview_open`／`_opened`／`_chunk`／`_data`／`_close`／`_closed`** |
| 回報欄位 | `node-register.file_download` | **`node-register.binary_preview`** |
| 節點設定鍵 | `filesystem.download.*` | **`filesystem.binary_preview.*`** |
| 稽核動作 | `file.download` | **`file.binary_preview`**（OD-6） |
| HTTP 路徑 | `GET …/files/download` | **`POST …/files/binary-preview`**（路徑在 JSON body，不在 URL） |
| Migration | `0021_node_file_download` | **`0022_node_binary_preview`**（提案） |
| Ticket 前綴 | `FD-` | **`BP-`** |

**條件式編號**：若 #71 沒有先合併，上表右欄在合併當下一律往前挪一號
（ADR 0028、`plan/30`、v1.10.0、`0021`、`FR-FILE-011`）；語意不變。
`BP-01` 的第一個驗收項就是「合併前重新核對 master 與 #71 的狀態」。

## 這一期最重要的一句話

```
  預覽是「在 console 裡畫出來」，不是「交給你一份」。
  平台不會畫出它不肯顯示給你看的檔案，也不會因為畫不出來就改成交給你。
```

前半句是 ADR 0029 §7：沒有存檔、分享、另開分頁、列印或複製圖片的入口，
節點開關也與下載分開。後半句是 #77 的硬性規定：安全上畫不出來的檔案（炸彈、損毀、
超出上限），**不得**降級成把 binary 直接送到瀏覽器下載。

## 這一期最容易做錯的九件事

1. **在 `filesystem.read` 加 `raw:true`。** 一個型別兩套政策。`BP-02` 用 golden
   fixture `invalid/filesystem-read-with-raw.json` 把它釘死。
2. **拿 #71 的下載端點回來的位元組直接 inline 顯示。** 那是另一個授權、另一個開關、
   另一種稽核。預覽不得依賴下載被啟用（ADR 0029 §16）。
3. **用 `<img src="blob:…">`。** 現行 CSP `img-src 'self' data:`
   （`deploy/nginx/nginx.conf:134`）本來就不允許，而且 `<img>` 在 iOS 長按會出現
   「儲存到照片」，等於下載。改用 `createImageBitmap` 畫到 `<canvas>`（§11）。
4. **讓舊 daemon 收到新型別。** 舊 daemon 會**靜默丟棄**未知型別
   （`daemon/internal/protocol/codec.go:87` → `connection.go:491-494`），
   使用者只會看到逾時。Central 必須先看**當下連線**的註冊回報（§9）。
5. **把預覽處理放在 daemon 的 dispatch 迴圈上。** 現行 `handleFsRead` 就在迴圈上同步執行
   （`connection.go:509`），2 MiB 還撐得住，16 MiB 的讀取加驗證會卡住終端輸入與心跳。
6. **以為 Central「不落地」就是整條路不落地。** `/api/` 的 nginx 是 `proxy_buffering on`
   且沒有 `proxy_max_temp_file_size`（`nginx.conf:174`），大回應可能落到 edge 的暫存檔（`BP-05`）。
   同理，**URL 會被每一層記下來**：兩份 nginx 都記 `"$request"`（`nginx.conf:52-55`），
   uvicorn 的 access log 也帶 query string。所以路徑放在 POST body，不放在 `?path=`（ADR §6）；
   「不落地」與「log 無路徑」在 `BP-OM-06`／`BP-OM-10` 量完之前**不得對外宣稱**。
7. **在 dispatch 或 worker 上做會卡住的 open。** 現行 `Root.OpenFile` 是阻塞式 `os.Root.Open`
   （`workspace/root.go:109-118`），遇到 FIFO 會一直等寫入端。預覽改用先 `StatIn`、再以非阻塞方式開啟、
   最後對 fd 做 `fstat` 的順序（ADR §3）。
8. **讓停用的 daemon 送 `binary_preview: false`。** 舊 Central 的嚴格 schema 看到這個 key 就拒收，
   而且是靜默拒收（`ws/nodes.py:199-202`），Central 回退後節點就再也註冊不上。停用時要**省略**這個欄位（ADR §9）。
9. **把解碼後的東西快取起來。** 記憶體裡只保留畫面上那一份。換 session、登出、
   換使用者時同步清掉（沿用 #76 的 auth-loss 模式，§14）。

## 檔案

| 檔案 | 內容 |
|---|---|
| [`00-execution-plan.md`](00-execution-plan.md) | 成功定義、範圍、固定決策 D0–D15、階段 DAG、ticket 與 write-set、風險 |
| [`01-decisions-and-governance.md`](01-decisions-and-governance.md) | `BP-01`：ADR 核准、PRD／tech 修訂草案、traceability 與 permission-matrix 的**提議**變更、**產品決策 OD-1…OD-11** |
| [`02-contract.md`](02-contract.md) | `BP-02`：契約 v1.11.0 schema、fixtures、CHANGELOG 提案、三個消費端 |
| [`03-daemon.md`](03-daemon.md) | `BP-03`：`PreviewOpen` 十一步（含非阻塞開啟）、格式驗證、快照表、worker pool、設定 |
| [`04-central-and-edge.md`](04-central-and-edge.md) | `BP-04`／`BP-05`：端點、串流、標頭、能力協商、稽核、migration、nginx |
| [`05-frontend.md`](05-frontend.md) | `BP-06`／`BP-07`：共用生命週期與圖片檢視、PDF.js 渲染器、狀態、清理 |
| [`06-security-review.md`](06-security-review.md) | `BP-08`：威脅模型逐項審查、依賴與授權審查、判定格式 |
| [`07-verification-and-fixtures.md`](07-verification-and-fixtures.md) | `BP-09`：高風險 fixture 語料、E2E、效能、角色矩陣 |
| [`08-device-matrix-and-rollout.md`](08-device-matrix-and-rollout.md) | `BP-10`／`BP-11`：iOS Safari／Android Chrome × 360／390／430 實機矩陣、推出順序、kill switch、rollback |
| [`09-implementation-status.md`](09-implementation-status.md) | 唯一的「現在到哪了」來源，含開放測量 `BP-OM-01…12`（其中兩項是發布閘門）、審查中確認的既有缺陷、審查處置 |

規範來源一律回指 `research/prd.md`、`research/tech.md`、`docs/adr/`。本目錄不複製需求內容；
PRD 需要的新文字以**草案**形式寫在 `01-…md`，等 `BP-01` 核准後才進 PRD。
