# 02 — Daemon 下載路徑（`FD-03`）

實作：[`daemon/internal/files/download.go`](../../daemon/internal/files/download.go)，
刻意放在 `read.go` 旁邊，因為這兩份必須被並排閱讀。

## 1. `Download` 的七個步驟

Default-deny，最便宜的先做，每一步都是下一步的前提：

| # | 步驟 | 少了它會怎樣 |
|---|---|---|
| 1 | 節點開關 | 已停用的機器仍會被讀 |
| 2 | 對**請求路徑**做敏感判定 | 平台會去開啟它已經決定不交出的檔案 |
| 3 | 侷限 `O_NOFOLLOW` 開檔（ADR 0014） | 符號連結可以指出工作區 |
| 4 | 在 **fd** 上做一般檔案判定（不是在路徑上） | FIFO 會讓讀取永遠不返回 |
| 5 | 對 fd **解析後的真實名字**再做一次敏感判定 | 工作區內一個無害名字的符號連結指向工作區內的 `.env`，就可以下載 |
| 6 | 用 fd 的快照大小做上限判定 | 超過 frame 上限的檔案會變成逾時而不是拒絕 |
| 7 | 從**同一個 fd** 有界讀取 | 判定後才變大的檔案會超出上限 |

步驟 2 與 5 是同一個檢查做兩次，**兩次都不能省**，理由在上表右欄。

**第 7 步與 return 之間刻意沒有任何東西。** `Read` 在這裡有一步
（二進位／編碼分類），而它在這裡的**缺席就是這個功能**。

## 2. 拒絕是 error，不是 in-band

`Read` 用 `success:false` 的成功 frame 回傳拒絕，因為瀏覽器有一個「被拒面板」
可以渲染它。下載沒有——這條路徑的 HTTP body **就是檔案**，
所以拒絕除了狀態列之外無處可去。

因此 `DownloadResult` 沒有 `Denied` 欄位，拒絕是一個帶 wire code 的
error 型別（`downloadDenial`），由 `DownloadCode()` 取出。
handler 用它挑錯誤碼，而不是把每一種拒絕都塌成 `INTERNAL_ERROR`——
那會告訴一個檔案太大的使用者「伺服器壞了」。

## 3. 上限：先是 frame 預算，才是政策

`filesystem.download.max_bytes`，預設 4 MiB。這個數字不是品味：

```
  4 MiB 的檔案  →  5.33 MiB 的 base64  →  仍在既有的 8 MiB MaxFilePayload 之內
```

與上傳上限相同，讓「什麼尺寸過得了 Cliora」在兩個方向只有一個答案；
但它是**獨立的設定鍵**（D4）。

`TestDownloadCapFitsFrameBound` 斷言這串算術，理由是：
把設定鍵調高而沒調高 frame 上限**不會大聲失敗**——節點會拒絕建構 frame，
而使用者看到的是逾時。

## 4. 設定

```yaml
filesystem:
  download:
    enabled: true          # 缺省即為 true（見下）
    max_bytes: 4194304
```

`enabled` 是指標型別，讓「缺省」與「明確 false」保持可分辨：
缺省表示這台機器是從升級繼承到這個行為的，而啟動 log 必須說得出這件事
（`DownloadFromDefault`，與 `UploadFromDefault`、`FileUploadFromDefault` 同一種處理）。

缺省為 true 的代價與 ADR 0023 D2、ADR 0024 D8、ADR 0026 §9 相同：
**升級即取得該行為**，因此同樣欠一份 release note 與一份 runbook，而不是沉默。

## 5. 沒有配額

兩條上傳路徑有累計配額，因為寫入消耗磁碟，而磁碟會用完。
讀取不消耗任何會用完的東西，所以這裡放一個計數器：

- 擋不到它看起來在擋的東西（鐵了心的人可以連續打預覽端點），
- 而且會教會操作者「Cliora 的配額是裝飾品」。

外流風險由 RBAC、敏感檔案政策、節點開關、每次下載一筆稽核承擔。
`filesystem_download_bytes` 量的是**離開這台機器的位元組**——
正因為沒有配額，這個數字才是操作者真正需要的那一個。
