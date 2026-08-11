# 03 — 回收桶、配額與清理（`WE-04`）

回收桶不是附加的貼心功能。它是 ADR 0024 **W2 的第三腿**（保留期）在編輯這條路徑上
唯一有意義的形狀，也是 ADR 0024 點名要編輯自己決定的 **undo**。
`00-…md` D21 因此把它訂為刪除功能出貨的硬性前提。

---

## 1. 目錄配置

```text
<workspace>/.cliora/
├── .gitignore                              # 內容 "*"，圖片投放已建立；本期沿用不重建
├── uploads/<UTC 日期>/<ULID>.<副檔名>        # ADR 0024
└── trash/<UTC 日期>/
    ├── <ULID>-notes.md                     # 被刪的檔案
    ├── <ULID>-main.go                      # 被覆寫的舊版本
    └── <ULID>-src/                         # 被刪的目錄，整棵子樹原樣在裡面
        ├── a.go
        └── nested/b.go
```

命名規則：`<ULID>-<原本的 base name>`，**檔案與目錄同一條規則**。

- **ULID 在前**：`ls` 出來就是刪除順序，找「剛剛那個」不必比對時間戳
  —— 與圖片投放同一個理由。
- **原檔名在後**：這與圖片投放的「daemon 命名、不採用客戶端檔名」**看似矛盾，其實不是**。
  那條規矩擋的是「請求端命名」；這裡的 base name 來自**節點上已經存在的檔案**，
  是 daemon 從自己的檔案系統讀到的，而且經過 `relClean`。
  沒有它，回收桶就是一堆 26 個字元的亂碼，而回收桶存在的唯一理由是讓人找回東西。
- **被刪目錄的內部結構原樣保留**，因為刪除就是把它整個 rename 進來（§2.2）——
  不是走訪後逐檔搬。所以還原也是一次 rename，整棵回去。
- **但 trash 的頂層是平的**：一個被刪的 `src/a.go` 進來之後是
  `trash/<日期>/<ULID>-a.go`，不是 `trash/<日期>/src/a.go`。
  重建原始路徑會讓還原變成一個需要建目錄的操作，而還原是一次 rename。
  **「它本來在哪」的權威來源是稽核**（`file.delete` 事件的 `path`），
  UI 也會在 trash 的列上顯示它（`05-…md` §3.2）。

`.cliora/trash/` 不需要自己的 `.gitignore` —— `.cliora/.gitignore` 的內容是 `*`，
涵蓋整個子樹。若該檔不存在（節點從未用過圖片投放），寫入面在建立
`trash/` 時要沿用 `ensureUploadDir` 既有的「僅在不存在時建立」邏輯。
**這意味著 `upload.go` 的 `ensureUploadDir` 要被拆出一個共用的
`ensureClioraDir(root, subdir)`** —— 不是重寫，是把已經正確的那段抽出來共用，
包括它對 `.cliora` 是 symlink 或非目錄的 `LstatIn` 檢查。

---

## 2. 進回收桶的三個時機

### 2.1 覆寫（`Write` 帶 `Revision` 前提）—— 用 `Link`

```
1. temp 檔已寫完並 fsync（02-…md §4.1 第 8 步的前半）
2. LinkIn(rel, trashRel)          ← 舊版本進回收桶，原檔仍在原位
3. RenameIn(tempRel, rel)         ← 新版本就位，原 inode 只剩 trash 這個名字
```

**順序不能顛倒。** 先 rename 再 link 的話，第 2 步已經沒有東西可以 link 了。
第 2 步成功、第 3 步失敗的殘留是「trash 裡多一份與原檔相同的副本」——
無害，而且下一次清理會處理掉。

**這是唯一必須用 hardlink 的時機**，因為原檔必須在新內容就位之前一直留在原位。
另外兩個時機不需要，所以它們不用（§2.2）。

### 2.2 刪除（檔案或目錄）—— 用 `Rename`

```
RenameIn(rel, trashRel)           ← 這一個 syscall 就是刪除
```

沒有第二步。檔案與目錄**同一行程式碼**，而目錄的整棵子樹一起搬走。

這比原本設想的 link＋unlink 好，而且是目錄需求逼出來的改進：

| | link＋unlink | rename |
|---|---|---|
| 步驟 | 2 個 syscall，中間有一個兩個名字都在的窗格 | 1 個，沒有中間狀態 |
| 目錄 | **不支援**（`link(2)` 不能用在目錄上） | 支援，整棵子樹 |
| 失敗形狀 | 可能留下孤兒 | 要嘛全發生要嘛沒發生 |
| inode | 保留 | 保留 |

`renameat` 會靜默覆寫目的地這件事在這裡不是問題：目的地是我們自己產生的
`<ULID>-<名字>`，撞名的機率是零。**但仍然要在 rename 之前 `LstatIn` 一次**，
撞到就回 `FILE_WRITE_FAILED` 並 `slog.Error` —— 那代表 ULID 產生器壞了，
而那件事必須大聲。

### 2.3 目錄刪除的前置：走訪先過，才動手

目錄的刪除在第 2.2 步之前，一定先跑完 `02-…md` §3.1 的 `walkSubtree`：
政策、筆數上限、子樹位元組數。**走訪不通過就完全不動手** ——
這是「不得部分執行」（`00-…md` D22）在程式碼裡的樣子，
而 rename 讓它變得容易做到：檢查與動作之間沒有可以失敗到一半的東西。

### 2.4 還原

```
RenameIn(trashRel, targetRel)     ← 同一個 syscall 反過來
```

檔案回來的是同一個 inode，所以**內容與權限模式都與刪除前相同**。
目錄回來的是整棵子樹，結構完整。這一點要有測試斷言（§6），
因為若哪天回收桶改成複製（§2.5 的 fallback），權限就會變成 0600 而測試會抓到。

### 2.5 `Link`／`Rename` 失敗時的階梯

兩者都可能因為 `EXDEV`（工作區內有 submount）、`EPERM`（某些 FUSE、
部分容器的 overlayfs upper layer）或 `EMLINK` 而失敗。階梯：

| 情況 | 處置 |
|---|---|
| `ErrExists`（trash 目的地已存在） | 不可能（ULID）。真的發生就是 bug，回 `FILE_WRITE_FAILED` 並記 `slog.Error` |
| 失敗，目標是**檔案**且 ≤ `trash.max_copy_bytes` | 改用複製（讀原檔 → `CreateExclusive` → 寫 → fsync），回應與 log 標記 `trash_mode: copy` |
| 失敗，目標是**檔案**且 > `trash.max_copy_bytes` | **拒絕整個操作**，回 `FILE_TRASH_UNAVAILABLE` |
| 失敗，目標是**目錄** | **一律拒絕**，回 `FILE_TRASH_UNAVAILABLE`。複製一棵樹是無界的工作，而它會在磁碟最緊的時候被觸發 |

最後兩列是本期最容易被覺得「太嚴格」的決定，所以它的理由要寫在程式碼註解裡：
**寧可拒絕刪除，也不做沒有備份的刪除。** 使用者被擋下來時會去用終端機刪 ——
那時他知道自己在做什麼，而這正是差別。

`WE-01` 第 1 項要量出實際節點上 hardlink 與跨目錄 rename 是否可用。
若量到常態失敗，`00-…md` D6 要重新決定，那是設計變更不是參數調整。

---

## 3. 配額

| 上限 | 值（可設定） | 超過時 | 為什麼是這個形狀 |
|---|---|---|---|
| 單次寫入 | `max_preview_size`（2 MiB，**不可獨立設定**） | `FILE_WRITE_TOO_LARGE` | `00-…md` D11：與讀取上限相等，由測試斷言 |
| 每日寫入次數 | 2000 | `FILE_WRITE_QUOTA_EXCEEDED` | 擋住壞掉的客戶端。顯式儲存之下遠高於人手打字的量 |
| Trash 累計 | 64 MiB／工作區 | **先清最舊，仍超過才** `FILE_WRITE_QUOTA_EXCEEDED` | 回收桶是安全網不是封存。「因為回收桶滿了所以你不能存檔」是荒謬的錯誤訊息，所以要先讓出空間 |
| 目錄走訪 | 20000 項 | `FILE_DIRECTORY_TOO_LARGE` | 走訪成本的上限，也是「這種規模該用終端機」的界線（`00-…md` D22） |

### 3.1 每日次數怎麼算

與圖片投放的做法**不同**：那邊是數 `uploads/<今天>/` 的檔案數（現算，不維護計數器），
但編輯不會在檔案系統上留下「今天寫了幾次」的痕跡 —— 覆寫同一個檔案 100 次，
trash 裡是 100 個檔案，但**建立**一個新檔案完全不留痕跡。

所以每日次數用**記憶體計數器**：`map[string]int`，key 是 UTC 日期，
在 `Service` 上加一個 mutex 保護，跨日時清掉舊 key。

**代價要寫下來：daemon 重啟會歸零。** 可接受，因為這個上限守的是
「壞掉的客戶端」而不是「惡意的使用者」（惡意的使用者持有 `terminal.operate`，
`00-…md` D0）。**被否決**：寫進磁碟（要決定寫在哪、多久 fsync 一次、
損毀了怎麼辦 —— 為一個 2000 次的門檻不值得）。

### 3.2 Trash 累計怎麼算

現算：`fs.WalkDir(root.FS(), ".cliora/trash")` 加總大小，
與 `uploadUsage` 同一個形狀，可以共用一個 `subtreeUsage(root, dir)` ——
**而 `walkSubtree`（`02-…md` §3.1）也需要同一件事**，所以是三個呼叫端共用一個走訪，
差別只在要不要順便套政策。寫成一個帶 callback 的走訪，不要三份。

刪一個目錄時要**先**知道它有多大才能決定放不放得下，
所以 `walkSubtree` 回傳的位元組數就是配額檢查的輸入 —— 不必走第二次。

**hardlink 的大小要注意**：`Walk` 看到的是每個名字的 `Size()`，
而 hardlink 的兩個名字指向同一份資料，所以覆寫情境下
trash 的「64 MiB」實際佔用的磁碟可能遠小於 64 MiB（原檔還在的期間）。
這是保守的方向（我們高估佔用），寫進註解即可，不做去重。

---

## 4. 清理

擴充既有的 `PruneUploads`，改名為 `PruneCliora`，同時處理 `uploads/` 與 `trash/`：

```go
func (s *Service) PruneCliora(root *workspace.Root, now time.Time) PruneStats
```

- 兩個子樹用各自的 `retention_days`（都預設 7，但獨立設定 ——
  一個節點可能想留久一點的回收桶而不想留久一點的圖片）。
- 沿用既有行為：清空的日期目錄一併移除；`.gitignore` 與 `.cliora/` 本身永不刪。
- 觸發時機沿用：session 啟動時與每 6 小時（`connection.go:592` 那一條）。
- 回傳 `PruneStats{UploadsRemoved, UploadsFreed, TrashRemoved, TrashFreed}`，
  log 一行，供 runbook 對照。

**超額時的提前清理**（§3 第三列）走同一個函式的一個變體：
`PruneTrashToFit(root, needBytes)` 由最舊的日期目錄開始刪，直到騰出空間或無可刪。
它**不看保留期** —— 那是刻意的：一個 7 天內但空間不足的回收桶，
其中最舊的那些對使用者的價值最低。

---

## 5. `doctor`

`agentd doctor`（`daemon/cmd/agentd/commands.go`）新增一段，
與既有的 `image-upload=…` 那一行並列：

```text
[info] file-editing=enabled (filesystem.editing.enabled: default)
[info] trash: 12 files, 3.4 MiB, oldest 2026-07-28 (retention 7d)
[warn] trash: hardlink unsupported on this filesystem; falling back to copy ≤4 MiB
```

第三行只在實際偵測到時出現。偵測方式：在 `.cliora/` 下做一次
link＋unlink 的探測，失敗就印警告。**這是 `doctor` 唯一會寫檔案的檢查**，
所以它要寫在 `.cliora/` 之下、用 ULID 命名、無論成敗都清掉，
並且在 `--dry-run`（若有）時跳過。

`doctor` 也要在 `filesystem.editing.enabled: false` 時印
`[info] file-editing=disabled`，與圖片投放的 `commands.go:201` 同一個形狀。

---

## 6. 測試

| 檔案 | 測什麼 |
|---|---|
| `internal/files/trash_test.go` | 覆寫用 link、刪除用 rename，兩者的 trash 內容與原檔相同且 `os.SameFile` 為真；覆寫的順序測試（模擬第 3 步失敗，確認原檔還在）；`max_copy_bytes` 的階梯四格（含「目錄一律拒絕」）；`FILE_TRASH_UNAVAILABLE` 時**檔案／目錄未被刪除** |
| `internal/files/trash_dir_test.go` | 刪一個含巢狀子目錄的資料夾：trash 裡結構完整、項目數相符；還原後每一個檔案的內容與權限都與刪除前相同；trash 頂層是平的（`<ULID>-src/` 而不是 `src/`） |
| `internal/files/prune_test.go` | `PruneCliora` 同時處理兩個子樹；7 天邊界（6d23h 留、7d1m 刪）；空日期目錄移除；`.gitignore` 不被刪；`PruneTrashToFit` 由最舊刪起且不看保留期 |
| `internal/files/quota_test.go` | 每日次數跨日歸零；trash 超額時先清最舊；清完仍不夠才拒絕；拒絕時檔案未被改動 |
| `internal/files/write_policy_test.go` | 還原路徑（trash → 正常路徑）成功；trash → `.cliora/` 之下失敗 |
| `cmd/agentd` | `doctor` 三行輸出的三種狀態 |

**兩條要特別寫的測試**：

1. 刪除一個檔案，把它從 trash **rename 回原位**，內容與權限都與刪除前相同。
2. 刪除一個**資料夾**，把它 rename 回原位，整棵子樹的每一個檔案內容與權限都相同。

這兩條是 `FR-FILE-011.AC-04`（「期間使用者可自行取回」）唯一的自動化證據，
而它們同時驗證了 `00-…md` D7 那個寫死的例外真的通得過。

> 權限會相同嗎？rename 與 hardlink 都不改變 inode，所以 mode 跟著 inode 走 —— 會相同。
> 這一點值得斷言，因為若哪天回收桶改成複製（§2.5 的 fallback），
> 這條測試就會抓到「還原回來的檔案權限變成 0600」。
