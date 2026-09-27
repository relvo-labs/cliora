# 03 — 契約、Central 與 RBAC（`FD-04`／`FD-05`）

## 1. 契約 v1.10.0（compatible）

一對型別加一個回報欄位，`version` 整數仍為 `1`。

### 1.1 `filesystem.download`（Central → daemon）

`{session_id, path}` —— 與 `filesystem.read` **完全相同的兩個欄位**，
且 `additionalProperties: false`。

刻意缺席的欄位，以及各自擋掉的東西：

| 缺席欄位 | 它會帶來什麼 |
|---|---|
| `offset` / `length` / `range` | 組裝狀態機、逾時清理、部分落地語意，外加「兩次 range 之間檔案變了」（＝版本前提） |
| `encoding` | 節點端的轉碼責任，以及「轉失敗算成功還是失敗」 |
| `mime` / `disposition` | 呼叫端可以影響瀏覽器如何對待這些位元組——見 §3 |

這是 1.4.0（`daemon.update` 只帶版本）、1.6.0（`tunnel.open` 沒有 host）、
1.8.0（`filesystem.upload` 不能命名）之後第四次套用同一條規則。

### 1.2 `filesystem.downloaded`（daemon → Central）

`{path, size, modified_at, data}`，**只在成功時送出**。

與 `filesystem.content` 不同（那個把拒絕放在 body 裡）——差別由目的地決定，
理由見 `02-…md` §2。

`size` 的 `minimum` 是 0（空檔案可下載），`data` 接受空字串，
`maximum` 是 4 MiB 的 base64 長度。

它是**第六個**獲准使用 8 MiB frame 上限的型別，而上限不動。
注意每一對裡「大的那一半」在哪：上傳是 request，這裡是 response——
那就是「位元組往哪個方向走」的意思。

### 1.3 `node-register.file_download`

選用布林，缺席即「否」，與 `image_upload`／`file_upload`／`privileged_terminal` 同規則。
Report-only：節點陳述姿態，平台永遠不能選它。

**第三個開關，而不是重用前兩個**——那兩個說什麼可以**寫進**這台機器，
這一個說什麼可以**讀出去**。一個想過外流問題的操作者想的正是這一個鍵。

### 1.4 Golden fixtures（九個）

| 檔案 | 釘住的性質 |
|---|---|
| `valid/filesystem-download.json` | 正常請求 |
| `valid/filesystem-downloaded.json` | 正常回應 |
| `valid/filesystem-downloaded-empty.json` | 空檔案可下載 |
| `valid/node-register-file-download.json` | 三個開關並存 |
| `invalid/filesystem-download-parent-escape.json` | `../` 在 wire 上就被擋 |
| `invalid/filesystem-download-with-range.json` | `offset`／`length` 是**拒絕**而非被忽略的多餘欄位 |
| `invalid/filesystem-downloaded-with-mime.json` | `mime` 是拒絕，不是疏漏 |
| `invalid/filesystem-downloaded-non-base64.json` | 只接受標準字母表的 base64 |
| `invalid/node-register-file-download-non-boolean.json` | 回報欄位型別 |

三個消費端都跑同一份 manifest。Go 這次**為一個 response 型別加了驗證分支**，
這是第一次——沒有它，`filesystem-downloaded-with-mime` 會被 Python 與 TypeScript 拒絕
而被 Go 悄悄接受，也就是共用 fixture 存在要抓的那種漂移。

## 2. Central 端點

```
GET /api/sessions/{session_id}/files/download?path=<workspace-relative>
```

RBAC：`file.browse`（不是新 action，見 `01-…md` §3）。

用 `Response` 而不是 `StreamingResponse`，而且這是誠實的：
relay 以單一相關 frame 回答，所以函式有東西可回傳時整個檔案早就在記憶體裡。
串流交付會**看起來**像 backpressure 卻不提供任何 backpressure；
真正限制記憶體的是節點端的 4 MiB 上限。

## 3. 三個回應標頭是一組

| 標頭 | 它擋掉什麼 |
|---|---|
| `Content-Type: application/octet-stream` | 平台被說服以可渲染型別送出工作區檔案 |
| `X-Content-Type-Options: nosniff` | 瀏覽器推翻上面那一行 |
| `Content-Disposition: attachment` | 內嵌顯示而非存檔 |

理由是 **console 自己的網域**：工作區可以有 `.html`、`.svg`、`.xhtml`，
其中任何一個以可渲染型別從 console 的網域內嵌送出，
就是帶著平台 cookie 的 stored XSS。

一律當成不透明附件，是把問題**移除**而不是逐型別回答它——
也正因如此，`filesystem.downloaded` 才不需要一個 `mime` 欄位讓 Central 動心。

另加 `Cache-Control: no-store`：這些位元組是使用者的檔案，不是可快取的平台資源，
而一個只用 URL 當 key 的共用快取會把它送給下一個問同樣路徑的 session。

## 4. 檔名

`Content-Disposition` 同時帶兩種形式（RFC 6266）：

- `filename="…"` —— ASCII 後備，給不支援 RFC 5987 的客戶端。
- `filename*=UTF-8''…` —— 真正的名字，百分比編碼。

**不倚賴瀏覽器的 `download` 屬性**：它對 same-origin blob 生效、
對 cross-origin blob 被忽略，倚賴它會讓存檔名稱取決於部署拓樸。

ASCII 後備以**丟棄**非 ASCII 字元產生，不做音譯——
一個名字要嘛完全正確，要嘛是後備，而看起來像翻譯的後備會引人採信。
引號與反斜線一併丟掉：那是這裡的標頭注入面，而 `quote` 只保護星號形式。

丟棄字元可能只剩下一個殘段：`年度統計.csv` 會剩 `.csv`，
那不是縮短的檔名而是另一種東西（一個 dotfile），而且客戶端會看不到副檔名。
因此**詞幹全沒了就用 `download` 補上，副檔名保留**：`download.csv`。
副檔名是後備名稱裡真正承重的那一半——它決定哪個應用程式會打開這個檔案。

## 5. 錯誤碼

| daemon code | HTTP | 下一步 |
|---|---|---|
| `FILE_DENIED` | 403 | 沒有——這是政策 |
| `FILE_TOO_LARGE` | 413 | 用終端機 |
| `FILE_NOT_FOUND` | 404 | 重新整理檔案樹 |
| `FILE_DOWNLOAD_DISABLED` | 403 | 洽節點擁有者 |

前三個在 ADR 0028 之前**只會 in-band 出現**在 `filesystem.content` 上，
所以 `_map_error` 這次才要為它們加分支。每一個保留自己的碼，
因為每一個的下一步都不同。

`FILE_DOWNLOAD_DISABLED` 是唯一的新碼，已加入 wire enum 與
`backend/app/api/error_catalog.py`（`docs/error-catalog.md` 由它產生）。

## 6. Migration `0021`

`nodes.file_download`，`server_default=false`，有索引。

`server_default=false` 是承重的：還沒回報的節點讀作**不**提供下載，
console 因此隱藏控制項而不是顯示一個會失敗的按鈕。**缺席永遠不是「未知」。**
不做 backfill——每個 daemon 下次連線都會重新註冊。

沒有 RBAC seed：下載沿用 `file.browse`。
那份重用的代價是這個 action 的**語意**變寬，那是 release note 的義務，不是 schema 的。
