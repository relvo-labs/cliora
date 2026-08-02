# 03 — Daemon 圖片落地面（`WF-04`）

範圍：`daemon/internal/workspace/root.go` 新增寫入方法、
`daemon/internal/files/` 新增 `upload.go`、`daemon/internal/config/config.go` 新增設定、
`daemon/internal/connection/files_handlers.go` 新增 handler、`agentd doctor` 新增一行。

規範來源：ADR 0024（`01-…md` §1）、`FR-FILE-009`、ADR 0014（路徑安全不變）。

---

## 1. 目錄與命名

```text
<workspace>/
└── .cliora/
    ├── .gitignore                       ← 內容 "*\n"，僅在不存在時建立（D10）
    └── uploads/
        └── 2026-08-05/
            └── 01K1ZQ9F3B7T2M8V4X6Y0N5R3D.png
```

- **日期目錄**用節點本地時區的日期？**不是** —— 用 UTC 日期。理由：清理邏輯（§4）
  比較的是 mtime，跨時區的節點若用本地日期會產生「昨天的目錄在今天被建立」這種
  只在 runbook 上出現一次就再也沒人記得的狀況。專案的時區規則本來就是全鏈 UTC
  （`.agent/skills/timezone-precision`）。
- **檔名**是 ULID ＋ 嗅探到的副檔名。ULID 而不是 UUID：它按時間排序，
  所以 `ls` 出來就是投放順序，這在使用者要找「剛剛那張」的時候有用。
  daemon 已經在協定層用 ULID（`request_id`），不必引入新東西。
- 客戶端原始檔名**不進入這條路徑的任何一環** —— 不進 wire、不進檔名、不進稽核（D2）。
  它只在瀏覽器端當作縮圖旁邊的標籤。

### 1.1 相對路徑就是回傳值

`filesystem.uploaded` 回的是 `.cliora/uploads/2026-08-05/01K….png`（工作區相對）。
session 以 `tmux new-session -c <workspace>` 啟動（`daemon/internal/tmux/client.go:147`），
所以這個字串直接打進 CLI 就解得開。Central 與瀏覽器都不需要、也不會拿到絕對路徑
（ADR 0014）。

---

## 2. `workspace.Root` 的寫入面

在 `daemon/internal/workspace/root.go` 新增，與既有的 `OpenDir`／`OpenFile` 並列，
共用 `relClean` 與 `mapPathErr`：

```go
// MkdirAllIn creates rel (and parents) under the root with perm, confined by
// os.Root. Every component is resolved beneath the root by the kernel.
func (r *Root) MkdirAllIn(rel string, perm os.FileMode) error

// CreateExclusive opens rel for writing, failing if it already exists. The
// O_EXCL is load-bearing: the daemon generates the name, so a collision means
// something else is writing into the upload directory.
func (r *Root) CreateExclusive(rel string, perm os.FileMode) (*os.File, error)

// RenameIn atomically renames oldRel to newRel, both confined to the root.
func (r *Root) RenameIn(oldRel, newRel string) error
```

實作全部走 `r.root.MkdirAll` / `r.root.OpenFile(clean, os.O_WRONLY|os.O_CREATE|os.O_EXCL, perm)`
/ `r.root.Rename`（Go 1.26 的 `os.Root` 都有，且都受 `RESOLVE_BENEATH` 約束）。

**三條紀律：**

1. 這三個方法是**這一期唯一**新增的寫入面。程式碼審查的判準：
   `daemon/` 底下不得出現 `os.WriteFile`／`os.Create`／`os.MkdirAll` 直接吃工作區內路徑的呼叫。
2. `.cliora` 本身在使用前要 `Lstat` 確認是目錄且不是 symlink。
   `os.Root` 會跟隨 root 內的 symlink，所以 `.cliora -> some/other/dir` 是可能的；
   讀取面用 `RealRel` 把決定綁在 inode 上（`read.go` 第 3b 步），寫入面用這個檢查達到同一件事。
   不是目錄或是 symlink → `FILE_UPLOAD_FAILED`，並在節點端 log 一行 `WARN`。
3. 權限：目錄 `0o700`、檔案 `0o600`。CLI 以同一個使用者身分執行，讀得到；
   同機其他使用者讀不到。

---

## 3. 落地流程（`daemon/internal/files/upload.go`）

`func (s *Service) SaveImage(root *workspace.Root, data []byte, now time.Time) (UploadResult, error)`

固定順序，default-deny，與 `read.go` 的體例一致：

1. **停用檢查** — `filesystem.upload.enabled == false` → `Denied{Code: "FILE_UPLOAD_DISABLED"}`。
2. **大小** — `len(data) > upload.max_bytes`（預設 4 MiB）→ `FILE_UPLOAD_TOO_LARGE`。
   Central 已經擋過一次；這裡再擋是因為 Central 不是唯一可能的呼叫者。
3. **嗅探** — magic number，只認四種：

   | 格式 | 前綴 | 副檔名 |
   |---|---|---|
   | PNG | `89 50 4E 47 0D 0A 1A 0A` | `.png` |
   | JPEG | `FF D8 FF` | `.jpg` |
   | GIF | `47 49 46 38 37 61` / `47 49 46 38 39 61` | `.gif` |
   | WebP | `52 49 46 46 ?? ?? ?? ?? 57 45 42 50` | `.webp` |

   不符 → `FILE_UPLOAD_UNSUPPORTED_TYPE`。**不看**呼叫端宣告的型別（D3）。
   嗅探結果同時決定回傳的 mime 與副檔名 —— 兩者不可能不一致，因為它們來自同一次判定。
4. **配額** — 統計 `.cliora/uploads/` 下的總位元組數與當日檔案數
   （`fs.WalkDir` over `root.FS()`，只走這一個子樹）。
   超過 `max_session_bytes`（64 MiB）或 `max_files_per_day`（200）→ `FILE_UPLOAD_QUOTA_EXCEEDED`。
   統計是每次上傳現算，不維護計數器狀態 —— 使用者可能在檔案樹外自己刪檔，
   而一個會和現實不同步的計數器比多走一次目錄糟糕得多（上傳不是熱路徑）。
5. **確保目錄** — `MkdirAllIn(".cliora/uploads/<UTC date>", 0o700)`；
   `.cliora/.gitignore` 不存在則寫入 `*\n`（D10，這是唯一允許寫在 `uploads/` 之外的檔案，寫死）。
6. **原子寫入** — 先 `CreateExclusive(".cliora/uploads/<date>/.<ULID>.part", 0o600)`、
   寫入、`Sync()`、`Close()`、再 `RenameIn` 成最終檔名。
   失敗時刪掉 `.part`，**不留半個檔案**（同 `PV-05` 的 sudoers 紀律）。
   一個以 `.` 開頭、還沒改名的暫存檔即使洩漏出去，也不會被誤認為一張可用的圖。
7. **成功** — 回 `{RelPath, Mime, Bytes, ModifiedAt}`。

### 3.1 記什麼、不記什麼

節點端 log 一行（沿用 `filesystem read`／`list` 的體例）：
`event=filesystem.upload request_id=… session_id=… mime=image/png bytes=… duration_ms=…`。
**不記**內容、不記客戶端檔名。相對路徑可以記（D11）。

metrics：`filesystem_upload_total{code}`、`filesystem_upload_bytes`（histogram）。
mime 可以當 label（四個固定值）；路徑不可以。

---

## 4. 清理（`FR-FILE-009.AC-09`）

`func (s *Service) PruneUploads(root *workspace.Root, now time.Time, maxAge time.Duration) (removed int, freed int64)`

- 觸發點兩個：session 啟動時（在 `session.start` 成功之後、非同步）、以及每 6 小時的 ticker。
- 刪除條件：`.cliora/uploads/` 下 mtime 早於 `now - retention`（預設 7 天）的**檔案**；
  空的日期目錄一併移除。`.cliora/.gitignore` 與 `.cliora/` 本身永不刪。
- 走訪只在這個子樹內，且經 `root.FS()`，不會碰到工作區其他地方。
- 每次清理 log 一行 `event=filesystem.upload_prune removed=… freed_bytes=…`。

**為什麼不在 session 結束時刪**：見 `00-…md` D9。使用者的 CLI 對話紀錄會指向那些檔案，
一個「AI 說它看不到那張圖了」的症狀，會被歸因到 AI 而不是平台。

---

## 5. 設定

```yaml
filesystem:
  max_preview_size: 2097152
  upload:
    enabled: true              # D8；預設 true，升級即取得
    max_bytes: 4194304         # 單張 4 MiB
    max_session_bytes: 67108864
    max_files_per_day: 200
    retention_days: 7
```

- 缺項套預設，`applyFilesystemDefaults` 沿用既有體例。
- `enabled` 缺項時視為 `true`，並在 `UploadFromDefault` 記下「這是預設不是選擇」，
  啟動 log 說出來 —— 與 `SandboxBypassFromDefault`（`config.go:185`）同一個理由：
  「操作者要求的」和「升級造成的」是關於一台機器的兩個不同事實。
- `RuntimeConfig` 沒有 argv 欄位的那條紀律在這裡的對應物是：
  **`upload` 底下沒有 `directory`、`filename_template`、`allowed_types` 這三個鍵**。
  目錄與命名是 daemon 的，格式清單是 wire 契約的一部分（改它要改契約與三個 consumer）。

---

## 6. 協定 handler

`handleFsUpload`，體例完全比照 `handleFsRead`（`files_handlers.go:81`）：

```text
ValidateControl → Unmarshal → openSessionWorkspace → defer root.Close()
  → base64 decode（失敗即 INVALID_MESSAGE）
  → files.SaveImage
  → metrics + slog
  → BuildResponse("filesystem.uploaded", …)
```

- base64 解碼要在 `SaveImage` 之前、且解碼後的長度要再檢查一次
  （一個 8 MiB 的 base64 字串解出 6 MiB，仍然要被 §3 第 2 步擋下）。
- 解碼用 `base64.StdEncoding.Strict()` —— 非嚴格模式會接受尾端垃圾。
- session 不存在 → `SESSION_NOT_FOUND`（沿用 `orSessionNotFound`）。
- `filesystem.uploaded` 是小訊框（一個相對路徑加三個純量），走 64 KiB 的一般上限，
  **不要**把它加進 `LargeFrameTypes` —— 只有請求方向需要放寬（`04-…md` §1.2）。

---

## 7. `agentd doctor`

新增一行，與 `PV-05` 的三行並列：

```text
[ ok ] image upload: enabled, 4 MiB/file, 12 files (3.1 MiB) in workspace uploads, retention 7d
[warn] image upload: disabled by filesystem.upload.enabled=false
[fail] image upload: .cliora exists but is not a directory — remove it or disable uploads
```

`doctor` 的每一行在失敗時都要說得出「要改哪個檔案」（ADR 0023 的成功判準第 8 項，
本期沿用）。`doctor` 不需要 session 就能跑，所以它檢查的是 **allowed roots** 下每一個
既有工作區的 `.cliora` 狀態，而不是某個 session 的。
