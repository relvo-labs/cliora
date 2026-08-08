# 04 — 前端：把檔案拖進檔案瀏覽器（`FU-06`）

這是使用者唯一會看到的部分，也是本期唯一有新互動的部分。
兩個入口收斂到同一個 `submit()`，形狀沿用 `useImageDrop.ts`（p13）
—— 那份程式碼已經解決過「三個入口一條路徑」這個問題，本期照它做。

---

## 1. 放置目標

### 1.1 哪一列可以放

新增 `frontend/src/composables/useFileUpload.ts`，
由 `FileTree.vue` 掛在每一列上。目標目錄的推導只有三條規則：

| 放在哪一列 | 目標目錄 |
|---|---|
| 目錄列（含未展開的） | 該目錄 |
| 檔案列 | **它的父目錄** |
| 根列（workspace） | `"."` |

**檔案列指向父目錄**是刻意的：使用者把檔案拖到 `src/main.go` 上時，
他的意思是「放到 `main.go` 旁邊」。要求他精準命中目錄列會讓這個功能很難用，
而 hover 的高亮會顯示實際目標（§1.2），所以不會猜錯。

不能放的列（`status`／`more` 這兩種合成列，以及 `excluded` 的目錄列）
**不接受拖放，也不顯示高亮** —— 而不是接受後才失敗。

### 1.2 拖放時看得見什麼

- `dragover` 時：目標列加一個外框與淡底色，並在列的右側顯示
  「放到 `<目錄名>/`」的小標籤。**標籤顯示的是實際目標**，
  所以拖在檔案列上時它會顯示父目錄的名字，使用者立刻知道會發生什麼。
- `dragover` 一定要 `preventDefault()`，否則 `drop` 不會觸發。
- `dragleave` 要用計數器或 `relatedTarget` 判斷，
  否則在子元素之間移動時高亮會閃爍（樹的每一列都有巢狀元素）。

### 1.3 資料夾要被擋在發出請求之前（`00-…md` D9）

```ts
// A dropped directory arrives as a DataTransferItem whose
// webkitGetAsEntry().isDirectory is true, and `files` alone cannot tell the
// difference (a dropped folder shows up as a zero-byte File on some platforms).
// So the check must run on `items`, before anything is queued.
```

`DataTransfer.items` 裡任何一個項目是目錄 → **整批拒絕**，
顯示「資料夾請用終端機處理（`git clone`／`scp`／`tar`）」，不發任何請求。
不是跳過目錄只傳檔案 —— 靜默跳過會讓使用者以為整個資料夾都上去了。

`webkitGetAsEntry()` 的實際行為（各瀏覽器、拖放 vs 挑檔）是
`FU-01` 第 1 項的閘門（`07-…md` §1）。**若前端擋不住**，
處置是在 daemon 端也擋（一個零位元組、名字沒有副檔名的檔案不足以判斷，
所以真正的處置會是「前端只送 `items` 判定為 file 的項目，並在無法判定時拒絕整批」）
—— 那是設計變更，所以它是閘門。

### 1.4 落在別的地方的 drop 要被吞掉

瀏覽器對未處理的檔案 drop 的預設行為是**開啟那個檔案**（換頁）。
所以 `SessionWorkspaceView` 要在自己的根元素上加一組
`dragover`／`drop` 的 `preventDefault()`，把落在兩個合法目標之外的 drop 吃掉
並且什麼都不做。

**兩個合法目標**：檔案樹的列（本期）與終端機面板（圖片投放，p13）。
它們是不同的 DOM 子樹，所以不會互相搶 —— 但要有一條測試同時斷言：
拖圖到終端機仍然走圖片投放、拖檔到樹上走本期的路徑（`00-…md` §5 的風險列）。

---

## 2. 上傳佇列

### 2.1 `submit(files, targetDir)`

```
1. 前端預檢（逐檔）：大小 ≤ 4 MiB、檔名長度 1–255、不含 / 與控制字元
   → 不過的直接標記為失敗，不發請求
2. 建立佇列：最多 20 個（超過只取前 20 並顯示「只處理前 20 個檔案」）
3. 循序送出（不併發，00-…md D11），每一個檔案：
   POST /files/upload?directory=…&filename=…
   Content-Type: application/octet-stream，body 是 File
   進度用 XMLHttpRequest.upload.onprogress
4. 每一檔完成後：成功 → 標記；失敗 → 標記 code 與文案（§2.3）
5. 整批結束後：刷新目標目錄一次（不是每一檔刷一次）
```

**第 5 步只刷一次**：三個檔案上傳完刷三次會讓樹跳三下，
而且每一次都是一個節點請求。

**第 3 步不併發**的理由在 `00-…md` D11：`filesystem.store` 是大訊框型別，
20 × 4 MiB 併發會塞住那條共用的控制訊框通道。

### 2.2 上傳列的樣子

檔案樹上方（或下方，依 `research/style.md` 的版面）一條可收起的區塊，
每一個檔案一列：

```
data.csv          → datasets/          ████████░░ 78%
notes.md          → datasets/          ✓ 已上傳
huge.zip          → datasets/          ✗ 超過 4 MiB 上限
config.json       → datasets/          ✗ 已有同名檔案   〔改名〕
```

- 全部完成且無失敗 → 5 秒後自動收起。
- 有任何失敗 → **不自動收起**，保留到使用者關閉。
  一個自己消失的錯誤訊息等於沒有錯誤訊息。
- 上傳中不允許離開頁面？**不擋。** 本期沒有未儲存的狀態
  （失敗的上傳沒有留下任何東西），所以 `beforeunload` 不需要 ——
  這是 `plan/14` 有而本期沒有的東西之一。

### 2.3 錯誤文案

| Code | 文案 | 下一步 |
|---|---|---|
| （前端預檢）大小 | 超過 4 MiB 上限 | 較大的檔案請在節點上以終端機處理 |
| （前端預檢）檔名 | 檔名不可包含 `/` 或控制字元 | — |
| `FILE_EXISTS` | 這個目錄裡已經有同名的檔案 | 〔改名〕（§2.4），或在終端機取代它 |
| `FILE_UPLOAD_TOO_LARGE` | 超過 4 MiB 上限 | 同上 |
| `FILE_UPLOAD_QUOTA_EXCEEDED` | 這個 Session 的上傳用量已達上限 | 請稍後再試或聯絡管理者 |
| `FILE_UPLOAD_NO_SPACE` | 節點磁碟空間不足 | 請通知管理者 |
| `FILE_DENIED` / `git_metadata` | 不能放進 git 的內部目錄 | — |
| `FILE_DENIED` / `platform_owned` | 這是平台管理的目錄 | 請選其他目錄 |
| `FILE_DENIED` / `excluded_dir` | 這個目錄由工具管理，不開放上傳 | 請選其他目錄 |
| `FILE_DENIED` / `dotenv`｜`private_key`｜`keystore`｜`sensitive` | 這個檔名受保護，不能從瀏覽器上傳 | 請在節點上以終端機處理 |
| `FILE_DENIED` / `dir_not_directory` ｜ `FILE_NOT_FOUND` | 目標目錄不存在或已改變 | 請重新整理檔案樹 |
| `FILE_UPLOAD_DISABLED` | 這個節點停用了檔案上傳 | （正常情況看不到，入口會被隱藏） |
| 403 | 沒有上傳檔案的權限 | — |

**每一列都要有下一步或明確的「—」。** 沒有下一步的錯誤訊息會被當成 bug 回報。

`FILE_DENIED` 的敏感檔名那一列要特別注意措辭：**不要說「這是敏感檔案」** ——
使用者拖進來的 `secrets.example.json` 不是秘密，它只是名字命中了規則。
說「這個檔名受保護」是準確的，而且指出了可以怎麼做（改名或用終端機）。

### 2.4 同名衝突的改名流程（`00-…md` D2）

`FILE_EXISTS` 的那一列出現一顆〔改名〕。按下去展開一個 inline 輸入框：

- 預設值是**加尾碼的建議名**：`config.json` → `config-2.json`
  （`<stem>-<n><ext>`，n 從 2 開始，不檢查伺服器上是否也存在 ——
  檢查要多一個往返，而重試失敗只是再看到同一個錯誤）。
- 旁邊一句小字：**「要取代既有檔案請在終端機處理。」**
  這一句是本期最重要的一句文案：它把「不覆寫」講成規則而不是缺陷，
  並且指出使用者實際上要走的路（而那正是他自己指定的分工）。
- 送出後就是同一個 `submit()`，只是換一個 `filename`。

**沒有「覆寫」按鈕。** 有的話這一整期就要長出版本前提、回收桶與 undo
（`01-…md` §6.2）。

---

## 3. 入口與顯示條件

| 入口 | 位置 | 為什麼需要它 |
|---|---|---|
| 拖放 | 檔案樹的列（§1） | 使用者指定的主要入口 |
| 〔上傳檔案〕 | `FileTreeToolbar.vue`，隱藏的 `<input type="file" multiple>` | **拖放對鍵盤與觸控使用者等於不存在。** 目標目錄取 `useFileTree.currentDir()`（既有方法），並在按鈕的 `title` 顯示它 |

顯示條件**兩個都要成立**：

```ts
// Both server-derived. The browser must not re-derive RBAC (ADR 0016) and must
// not guess the node's posture (ADR 0024 W4). Note this is the SAME permission
// as image drop but a DIFFERENT node flag — one action, two postures (03-…md §2.3).
const canUploadFiles = computed(
  () => capabilities.value?.can_upload_files === true &&
        node.value?.file_upload === true,
);
```

不成立時**不顯示**按鈕，而且**拖放沒有任何反應**（不高亮、不提示）——
沿用 p13 的既有判準：一顆永遠按不下去的按鈕，使用者會花時間猜為什麼。
拖放沒反應也比拖完才被拒好。

**不要求 writer 角色。** 圖片投放要求它，是因為那條路徑最後會把路徑
打進終端機（需要寫入權）。本期不碰終端機，所以不需要 —— 兩個人可以同時上傳。
這個差異要留一行註解，否則會被下一個人「順手統一」。

---

## 4. 上傳成功之後

| 做什麼 | 為什麼 |
|---|---|
| 刷新目標目錄一次（`store.refreshDir(targetDir)`） | 新檔案要出現在樹上 |
| 若目標目錄未展開，**先展開它** | 上傳到一個看不到內容的目錄，使用者無法確認結果 |
| 選中最後一個成功上傳的檔案列（`selectedKey`） | 讓「東西在哪裡」不需要用眼睛找 |
| **不自動開啟預覽** | 上傳一個 40 MB 的 zip 之後跳出「不支援預覽」是一個平台自己製造的錯誤畫面 |

---

## 5. 測試（Vitest）

| 測試 | 內容 |
|---|---|
| `useFileUpload.test.ts` | 兩個入口呼叫同一個 `submit`；目標目錄的三條推導規則；資料夾被擋且**沒有發請求**；大小與檔名預檢；20 個上限；循序而非併發（斷言第二個請求在第一個 resolve 之後才發出）；整批只刷新一次 |
| `FileTree.test.ts`（擴充） | `dragover` 高亮落在正確的列；`status`／`more`／`excluded` 列不接受拖放；標籤顯示的是實際目標目錄（拖在檔案列上顯示父目錄） |
| `FileTreeToolbar.test.ts`（擴充） | 〔上傳檔案〕的 `title` 顯示 `currentDir()`；`multiple` 屬性存在 |
| `SessionWorkspaceView.test.ts`（擴充） | `can_upload_files` × `file_upload` 的四種組合；**`image_upload` 為真而 `file_upload` 為假時，終端機的圖片投放仍在、樹的上傳入口消失**（這是同一個權限兩個節點旗標的關鍵組合）；落在兩個目標之外的 drop 被吞掉 |
| `client.test.ts`（擴充） | `uploadFile` 的 query 編碼（含中文與空白的檔名）；`uploadWithProgress` 抽出後 `uploadImage` 的請求形狀不變 |

**一條要特別寫的測試**：`FILE_EXISTS` → 按〔改名〕→ 預設值是
`config-2.json` → 送出後的請求 `filename` 是新名字而 `directory` 不變。
這條把 D2 的整個使用者面路徑走完了，而它是本期唯一一個多步驟的互動。
