# 00 — 執行總控（檔案下載：把工作區的檔案取回本機）

Ticket 前綴 `FD-`（**F**ile **D**ownload）。

## 1. 成功定義

**要交付的：** 使用者在瀏覽器的檔案樹裡點一個檔案，按下下載，
那個檔案就以原本的名字、原本的位元組出現在他的本機——
包括預覽看不了的二進位檔，不包括平台不肯顯示給他看的敏感檔。

**不得弄壞的五件事：**

1. **`workspace.Root` 的封閉性。** 下載路徑與既有的讀取面、兩條寫入面共用同一個
   `workspace.Root`（ADR 0014、`SEC-001`）。`daemon/` 底下不得出現任何
   吃工作區絕對路徑的 `os.Open`／`os.ReadFile`。
2. **敏感檔案政策只有一份實作。** 下載呼叫的是預覽呼叫的**同一個**
   `SensitiveClassification()`，而且呼叫兩次（請求路徑一次、fd 解析後的真實名字一次）。
   第二次是為了把判定綁到真正被開啟的 inode 上。
3. **中央不留任何位元組。** 不落磁碟、不進資料庫、不進 log、不進 metrics label
   （ADR 0024 §5 原樣套用到反方向）。
4. **回應永遠是不透明附件。** `application/octet-stream` ＋ `nosniff` ＋ `attachment`，
   不看副檔名、不嗅探、不採信節點提供的任何型別。
5. **既有的預覽路徑（ADR 0015）與兩條上傳路徑（ADR 0024／0026）不受影響。**
   本期一個位元組都不動它們的政策；唯一動到的是預覽**被拒面板的文案**（D9）。

成功的判準是這八項，每一項都要有可貼上的輸出（`05-…md` §3）：

1. 在檔案樹選一個 `datasets/data.csv` 並下載，本機取得的檔案 SHA256 與節點上相同。
2. 下載一個 PNG：預覽面板本來說「不支援預覽」，現在同一個面板提供下載，且下載成功，
   位元組與節點上完全相同。
3. 下載一個 3 MiB 的文字檔：預覽拒絕（超過 2 MiB），下載成功——
   面板明說它在下載上限之內。
4. 下載一個 9 MiB 的檔案：面板**不顯示下載按鈕**，改說去用終端機。
5. 對 `.env`、`*.pem`、`.ssh/config` 下載：一律 `FILE_DENIED`，
   面板明說「下載同樣被拒」，且節點端沒有讀取過任何內容。
6. 把工作區裡一個 `report.html` 下載：回應是 `application/octet-stream`＋`nosniff`，
   瀏覽器存檔而不是渲染。
7. 檔名為 `年度統計.csv` 時，存檔名稱正確；`Content-Disposition` 同時有
   ASCII 後備與 RFC 5987 形式。
8. 關閉 `filesystem.download.enabled` 的節點回報 `file_download: false`，
   UI **不顯示**下載入口；直接呼叫端點得到 `FILE_DOWNLOAD_DISABLED` 403。

## 2. 範圍

### 納入

- `FD-02` ADR 0028、PRD 修訂（新增 `FR-FILE-011`、`NFR-005.AC-109` 收束、
  `NFR-005.AC-142` 補一句讀取面、`FR-CONN-006.AC-12` 新增預算）、traceability 註冊。
- daemon：`files/download.go`（七步 default-deny）、設定開關與上限（`FD-03`）。
- 契約 v1.10.0（compatible）：一對型別 `filesystem.download`／`filesystem.downloaded`、
  `node-register.file_download` 一個回報欄位、九個 golden fixture（`FD-04`）。
- Central：`GET /api/sessions/{id}/files/download`、沿用 RBAC `file.browse`、
  新增稽核 `file.download`、三個標頭、四個錯誤碼對映、migration `0021`（`FD-05`）。
- 前端：`downloadFile` API、`useFileDownload`、預覽工具列按鈕、
  被拒面板的兩段式提議（`FD-06`）。
- evidence／runbook／release note（`FD-07`）、安全審查與 exit gate（`FD-08`）。

### 不納入

- **範圍／分塊下載。** 見 D3。需要組裝狀態機、逾時清理、部分落地語意，
  外加「兩次 range 之間檔案變了」這一題（那是版本前提）。
- **下載資料夾，或把資料夾打包成壓縮檔。** 需要走訪、無上限的項目數、
  部分失敗語意，以及「誰來決定壓縮格式」。用終端機。
- **一次下載多個檔案。** 同上，而且瀏覽器對多重下載的處置各家不同。
- **放寬敏感檔案政策。** 本期一個字都不動。
- **編輯、刪除、更名。** 產品決定，見 PRD `FR-FILE-010` 的引言。
- **配額。** 見 D8。這是本期最重要的一個「不做」，而且必須寫下來為什麼。

## 3. 固定基線決策（D0–D10）

| # | 決策 | 為什麼 | 日後 |
|---|---|---|---|
| D0 | 新增一對型別，不在 `filesystem.read` 上加旗標 | 一個型別兩套政策，而必須守住的那一條在兩欄長得一樣 | — |
| D1 | 敏感檔案政策共用，且呼叫兩次 | 兩份清單不會保持同步；第二次把判定綁到 inode | — |
| D2 | 二進位判定**不**套用 | 「無法呈現」是關於編輯器的陳述，不是關於檔案的 | — |
| D3 | 單檔 4 MiB，一個 frame | 4 MiB 是 5.33 MiB 的 base64，在既有 8 MiB 之內 | 觸發條件：`filesystem_download_bytes` 顯示拒絕集中在某個區間 |
| D4 | 上限是獨立設定鍵，不與上傳共用 | 想收窄「離開這台機器的東西」的人，不該被迫收窄「進來的東西」 | — |
| D5 | 回應永遠 octet-stream＋nosniff＋attachment | 工作區的 `.html` 內嵌渲染＝帶平台 cookie 的 stored XSS | — |
| D6 | 沿用 `file.browse`，Viewer 也能下載 | 動詞相同；三個固定角色表達不出「可預覽不可下載」 | 若日後角色可自訂，這一條要重看 |
| D7 | 新增稽核動作 `file.download`，記**成功** | 成功的預覽什麼都不留下，成功的下載留下一份拷貝 | — |
| D8 | **沒有配額** | 讀取不消耗任何會用完的東西 | — |
| D9 | 修正預覽被拒面板的文案 | 它現在說「不提供下載」，而那從本版起是假的 | — |
| D10 | 節點開關獨立於兩個上傳開關 | 讀出去和寫進來是相反方向 | — |

## 4. 波次與 ticket

| Ticket | 內容 | 相依 |
|---|---|---|
| `FD-02` | ADR 0028、PRD 三處修訂、traceability 註冊 | — |
| `FD-03` | daemon `Download` 與設定 | `FD-02` |
| `FD-04` | 契約 v1.10.0 與三個消費端 | `FD-02` |
| `FD-05` | Central 端點、稽核、migration `0021` | `FD-04` |
| `FD-06` | 前端入口 | `FD-05` |
| `FD-07` | evidence、runbook、release note | `FD-06` |
| `FD-08` | 安全審查與 exit gate | `FD-07` |

前端（`FD-06`）可以晚於後端（`FD-05`）——有能力但沒有入口是安全的方向，反過來不是。

## 5. 風險

| 風險 | 處置 |
|---|---|
| `file.browse` 語意變寬而組織沒注意到 | release note 第一段；節點開關是唯一能保留舊語意的方法，所以它是決定的條件而非便利 |
| 有人為了「一致性」把二進位判定加回來 | `TestDownloadAllowsBinaryContent` 讓同一個檔案走兩條路，斷言答案相反 |
| 4 MiB 上限造成大量拒絕 | `filesystem_download_bytes` 讓「加上分塊下載」能以分布而非軼事論證 |
| 預覽面板文案與實際能力再次脫節 | 面板的下載提議由 `offerDownload` 逐分支決定，並有五個單元測試釘住每一種判決 |
