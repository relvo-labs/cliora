# Cliora 檔案下載：把工作區裡的檔案取回本機

本目錄交付 2026-09-16 由使用者指示的一件事，ticket 統一使用 `FD-` 前綴
（**F**ile **D**ownload）：

> 深入分析專案，在這個專案加入可以在前端下載 agentd 上檔案的功能

## 這一期真正的形狀

它是 ADR 0026 結尾那張清單上**唯一一個被延後、而不是被否決**的項目：

> **Not decided here:** download, editing, rename, delete, folder upload,
> chunked upload, and overwrite.

其中編輯、更名、刪除三項，PRD 已經明白記為「依產品決定改由 CLI／終端機承擔」——
那是決定，不是待辦。下載不是，`NFR-005.AC-109` 從 2026-08-03 起一直把它掛在明面上。

## 這一期最重要的一句話

```
  平台不會交出它不肯顯示給你看的檔案，
  但會交出它只是無法呈現的檔案。
```

前半句是安全規則，**與預覽共用同一份 `SensitiveClassification`**；
後半句是這一期真正要交付的東西。兩句話拆開才對，合成一句就會錯——
ADR 0026 §4 那句「平台不寫入它不肯顯示的位置」若原封不動鏡射過來，
會把二進位檔也一併擋掉，而那正是本功能存在的理由。

同一個檔案，兩條路徑可以有不同答案，而且是**雙向**不同：

| 檔案 | `filesystem.read` | `filesystem.download` |
|---|---|---|
| 300 KiB 的 PNG | 拒絕（二進位） | 允許 |
| Big5 的 `.txt` | 拒絕（非 UTF-8） | 允許 |
| 3 MiB 的原始碼 | 拒絕（超過 2 MiB 預覽上限） | 允許 |
| 3 MiB 的 `.env` | 拒絕（敏感） | **拒絕（敏感）** |
| 30 MiB 的 `.tar.gz` | 拒絕（過大） | 拒絕（過大） |

**這就是為什麼不能在 `filesystem.read` 上加一個 `raw: true`。**
那會讓一個型別同時承載兩套政策，而其中絕對不能漏掉的那一條（敏感檔案）
在兩欄裡長得一模一樣——讀 handler 的人必須同時記住兩欄才知道哪一行適用於誰。

## 這一期最容易做錯的六件事

1. **把預覽的二進位判定抄過來。** 那會擋掉這個功能唯一存在的理由。
   `TestDownloadAllowsBinaryContent` 守它，而且它刻意讓**同一個檔案**
   同時走 `Read` 與 `Download` 兩條路，斷言兩者答案相反。
2. **讓 `filesystem.downloaded` 帶一個 `mime`，然後 Central 照著回。**
   工作區裡的 `.html` 以 `text/html` 從 console 自己的網域送出，
   就是帶著平台 cookie 的 stored XSS。回應一律 `application/octet-stream`
   加 `nosniff` 加 `attachment`，三者是一組（`03-…md` §3）。
3. **加一個 `range` 或 `offset`。** 那是分塊下載的第一步，而它需要組裝狀態機、
   逾時清理、部分落地語意，外加這個方向獨有的一題：**兩次 range 之間檔案變了怎麼辦**——
   那是版本前提，也就是 `plan/14` 當初被作廢的那批機制。
4. **靜默擴大 `file.browse` 的語意。** 它從「列出、搜尋、預覽」變成
   「……並且可以取得檔案的完整位元組」，**而且 Viewer 也持有它**。
   這是本期唯一一個對既有授權的改動，要放在 release note 的**第一段**
   而不是附註（`01-…md` §3、`05-…md` §2）。
5. **重用上傳的節點開關。** 讀出去和寫進來是相反的方向，
   一個操作者對其中一個的答案，對另一個什麼都沒說（ADR 0028 §6）。
6. **忘記兩個上限不一樣。** 預覽 2 MiB、下載 4 MiB，中間夾著一整段
   「看不到但拿得走」的檔案。預覽被拒的面板必須說對這件事，
   而且超過 4 MiB 時要把按鈕**收回去**，不能讓按鈕去教使用者上限在哪。

## 一件本期刻意不做而必須誠實寫下來的事

**沒有配額。** 兩條上傳路徑都有累計配額，因為寫入會消耗節點磁碟；
讀取不消耗任何會用完的東西，所以這裡放一個計數器只會擋不到它看起來在擋的東西，
還會教會操作者「Cliora 的配額是裝飾品」。

外流風險由 **RBAC、敏感檔案政策、節點開關、每次下載一筆稽核** 承擔，
不是由速率限制承擔——一個鐵了心的 `file.browse` 持有者本來就可以連續打預覽端點，
而 `terminal.operate` 持有者根本不需要瀏覽器（ADR 0028 §10）。

這和 ADR 0026 §5「誰負責清這個位置」是同一種形狀的答案：
問對問題（**這裡有什麼東西會用完？**）比照抄上一條路徑的機制重要。

## 檔案

| 檔案 | 內容 |
|---|---|
| `00-execution-plan.md` | 成功定義（八項判準）、範圍、固定基線決策 D0–D10、波次與 ticket、風險 |
| `01-decisions-and-governance.md` | ADR 0028、PRD 修訂三處、traceability、`file.browse` 語意變寬的處置 |
| `02-daemon-download-path.md` | `FD-03`：`Download` 的七個步驟、政策共用、上限、設定開關 |
| `03-contract-central-and-rbac.md` | `FD-04`／`FD-05`：契約 v1.10.0、HTTP 端點與三個標頭、稽核、錯誤碼、migration `0021` |
| `04-frontend-entry-points.md` | `FD-06`：預覽工具列、被拒面板的兩段式提議、顯示條件 |
| `05-verification-and-exit.md` | `FD-07`／`FD-08`：測試清單、release note、runbook、安全審查七題、exit 條件 |
| `06-implementation-status.md` | 實作進度 |

規範來源一律回指 `research/prd.md`、`research/tech.md`、`docs/adr/`，本目錄不複製需求內容。
