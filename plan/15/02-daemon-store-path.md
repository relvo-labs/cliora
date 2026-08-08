# 02 — Daemon 落地面（`FU-03`）

一個動詞、一份政策、零個新機制。新檔 `daemon/internal/files/store.go`，
形狀刻意與 `upload.go`（圖片投放）並排可讀：**同樣的 default-deny 順序、
同樣的「否決不是 error」約定、同樣的 temp＋rename**。

---

## 1. `workspace.Root` 要補的東西

**只有一個新方法**，其餘沿用（`MkdirAllIn` 本期不用 —— 不建目錄）。

| 方法 | 簽章 | 用途 |
|---|---|---|
| `StatIn` | `func (r *Root) StatIn(rel string) (os.FileInfo, error)` | 確認目的地目錄存在且是目錄。**與 `LstatIn` 併用而不是取代它**：先 `LstatIn` 確認它不是 symlink（`os.Root` 會跟隨留在 root 內的 symlink，一個 in-root 的 `datasets -> ../../elsewhere-in-root` 會把落地位置悄悄改掉），再 `StatIn` 確認它是目錄 |

還要補一個錯誤哨兵：

```go
// workspace/guard.go
ErrExists = errors.New("workspace: path already exists")
```

並在 `mapPathErr` 中把 `fs.ErrExist` 對應到它。**這一步不能省**：
目前 `mapPathErr` 會把 `EEXIST` 落到 `ErrInvalid`，那會讓「同名檔案已存在」
（本期最常見、而且完全正常的一種拒絕）在使用者面前顯示成「無效的路徑」。

`CreateExclusive` **已經存在**（圖片投放在用），簽章與語意剛好就是本期要的：
`O_WRONLY|O_CREATE|O_EXCL|O_NOFOLLOW`。本期不改它，只是第二個呼叫端。
它的既有註解說 O_EXCL 是 load-bearing（因為 daemon 自己產生每一個檔名），
要**追加一句**：對 `filesystem.store` 而言 O_EXCL 的角色不同 ——
名字是客戶端給的，所以 `EEXIST` 是一個要回報給使用者的**正常結果**，
不是「有別人在寫這個目錄」。同一個 syscall，兩種語意，註解要分開寫。

---

## 2. 政策：位置與名字（`files/store_policy.go`）

一個函式，在任何 syscall 之前執行：

```go
// StorableClassification returns "" if a file may be stored at dir/name, or a
// coarse refusal reason. It is the write-direction counterpart of
// SensitiveClassification and deliberately calls it rather than
// re-implementing it (ADR 0026 §1.2).
func (p *Policy) StorableClassification(dir, name string) string
```

順序（default-deny，第一個命中就回）：

| # | 檢查 | 回傳 | 為什麼在這裡 |
|---|---|---|---|
| 1 | `name` 是單一路徑片段：不含 `/`、不是 `.` 或 `..`、不含控制字元或 NUL、長度 1–255 位元組 | `invalid_name` | 便宜、決定性。**wire 上的 schema 也擋這一條**（`03-…md` §1.2），這裡是 defence in depth —— daemon 不以「Central 檢查過了」為前提 |
| 2 | `dir` 經 `relClean`；合成 `rel = path.Join(dir, name)` | `invalid` | 之後每一個字串比對看到的都是正規化後的路徑 |
| 3 | `dir` 或 `rel` 的任一片段等於 `.git`，**或 `rel` 的最末片段等於 `.git`** | `git_metadata` | 兩種形式都要擋（`01-…md` §5）。目錄形式是 `.git/config`；worktree 與 submodule 的 `.git` 是一個內容為 `gitdir: …` 的**檔案**，所以末段也要比。今天兩者都沒有被擋 |
| 4 | `rel` 在 `.cliora/` 之下 | `platform_owned` | 平台自己的目錄。**本期沒有例外** —— `plan/14` 曾為回收桶的還原開一個例外，本期沒有回收桶 |
| 5 | `SensitiveClassification(rel) != ""` | 原分類（`dotenv`／`private_key`／`keystore`／`sensitive`／`sensitive_dir`） | **同一個函式**，不是複製（`00-…md` D4）。它會同時擋掉目的地在 `.ssh/` 之下與檔名是 `.env` 兩種 |
| 6 | `dir` 或 `rel` 的任一片段命中 `workspace.excluded_directories`（`.git`、`node_modules`、`.venv`、`dist`、`build`、`__pycache__`） | `excluded_dir` | 檔案樹已把它們標成不可展開，讓它們可寫會很奇怪。**注意這一條在寫入方向確實是安全控制**，而同一份清單在讀取方向被明白宣告為「不是安全控制」—— 同一份資料被兩種強度使用，要在程式碼註解裡寫明 |
| 7 | `dir` 正規化後等於 `.` 時**不拒絕**（工作區根目錄是合法的落地位置），但 `rel` 不得等於 `.` | `workspace_root` | 與 `plan/14` 不同：那份計畫要刪除與更名，所以根目錄必須完全不可動；本期只是往裡面放一個檔案，那是正常需求。`rel == "."` 只有在 `name` 通不過第 1 條時才可能發生，第 7 條是它的第二層 |

**回傳分類字串而不是 bool**，理由與讀取面相同：稽核與 metrics 需要粗分類，
而使用者面的文案需要知道「為什麼不行」——「這是 git 的內部檔案」與
「這是敏感檔名」對使用者的下一步不同（`04-…md` §2.3）。

### 2.1 沒有內容檢查

圖片投放用 magic number 只認四種型別；編輯（`plan/14`）要求內容是 UTF-8 文字。
**本期兩者都不做**：一般上傳沒有義務保證 CLI 讀得懂，
使用者要放 `.tar.gz` 或 `.parquet` 是他的事。

取代內容檢查的是兩件事，而它們都在別的地方：**名字要過政策**（§2 第 5 條）
與**落地不可執行**（§3 第 8 步）。這一段要寫成註解，
否則下一個人會覺得「這裡少了一個 `Classify()`」。

---

## 3. 動詞：`Store`

```go
// StoreResult is the outcome of one file upload. On denial Denied is true and
// Code carries the reason; RelPath is set only on success.
type StoreResult struct {
    RelPath    string
    Size       int64
    ModifiedAt time.Time

    Denied bool
    Code   string
    Reason string
}

func (s *Service) Store(root *workspace.Root, dir, name string,
                        data []byte, now time.Time) (StoreResult, error)
```

`Denied` 不是 error；只有非預期失敗回 err —— 與 `Read`／`SaveImage` 同一個約定。

順序：

| # | 步驟 | 否決碼 |
|---|---|---|
| 1 | 功能是否啟用（W4，`filesystem.upload.files.enabled`） | `FILE_UPLOAD_DISABLED` |
| 2 | `len(data) > upload.MaxBytes`（4 MiB，與圖片投放共用同一個鍵） | `FILE_UPLOAD_TOO_LARGE` |
| 3 | `StorableClassification(dir, name)`（§2） | `FILE_DENIED` ＋ reason |
| 4 | 配額：每 session 累計位元組、每日檔數（§4） | `FILE_UPLOAD_QUOTA_EXCEEDED` |
| 5 | 可用空間：`Statfs` 的可用位元組 < max(512 MiB, 2×len(data)) | `FILE_UPLOAD_NO_SPACE` |
| 6 | 目的地：`LstatIn(dir)` 必須存在且**不是 symlink**；`StatIn(dir)` 必須是目錄 | `FILE_NOT_FOUND` / `dir_missing`／`FILE_DENIED` / `dir_not_directory` |
| 7 | 目標名稱：`LstatIn(rel)` 必須是 `ErrNotFound` | `FILE_EXISTS` |
| 8 | temp（`.<name>.<ULID>.part`，同目錄，0600）→ 寫入 → `fsync` → **`f.Chmod(0644)`** → `RenameIn` 就位 | — |

幾個要寫進註解的細節：

- **第 5 步為什麼在第 6 步之前**：可用空間是節點層級的事實，不需要碰使用者的目錄結構。
  order 沿用 `Read`／`SaveImage` 的規矩：便宜且決定性的先做，
  在內容被接受之前不碰檔案系統。
- **第 7 步不是安全機制，第 8 步的 `O_EXCL` 才是。** 第 7 步存在的理由是
  **給出正確的錯誤碼**：`CreateExclusive` 失敗時我們只知道 `EEXIST`，
  分不出「同名檔案」與「同名目錄」，而後者的文案不同。真正的保證來自 syscall。
  兩者都要有測試（包含一個「在第 7 與第 8 步之間插入一個同名檔案」的競賽測試，
  斷言結果是 `FILE_EXISTS` 而不是覆寫）。
- **`f.Chmod(0644)` 在 rename 之前。** 用 temp 檔自己的 fd（走 `fchmod`），
  不是 `Root.Chmod(path)` —— Go 的文件明載後者在 Unix 上對
  「操作進行中被換成 symlink」有 race。順序不能換：rename 之後才 chmod
  會有一個窗格是檔案已經就位但權限是 0600。
- **temp 名字帶 ULID**：兩個瀏覽器同時上傳同名檔案時，固定後綴會讓第二個
  在 temp 上就 `EEXIST`，而它應該收到的是 `FILE_EXISTS`（針對目標，第 7 步），
  或者成功（如果第一個還沒 rename）。ULID 讓這兩種結果不會被 temp 的碰撞污染。
- 失敗時 `RemoveIn(tempRel)`，與圖片投放同一個形狀。

### 3.1 可用空間怎麼取

```go
// freeBytes reports the space available on the filesystem holding the
// workspace. syscall.Statfs is stdlib on Linux, so this adds no dependency
// (the daemon has six direct ones and that is a property worth keeping).
func freeBytes(canonicalPath string) (int64, error)
```

用 `root.Canonical()`（既有方法，daemon 內部用途，不外流）。
取不到時（`Statfs` 失敗）**放行**而不是拒絕 —— 這是唯一一個 fail-open 的檢查，
理由要寫在註解裡：它是一個防止磁碟填滿的**輔助**檢查，不是一條安全邊界，
而讓一個 statfs 的失敗擋掉所有上傳是把輔助檢查當成邊界。
失敗時記一次 `slog.Warn`，讓它不是靜默的。

---

## 4. 配額（`00-…md` D5）

| 上限 | 值（可設定） | 超過時 |
|---|---|---|
| 單檔 | `filesystem.upload.max_bytes`（4 MiB，**與圖片投放共用**） | `FILE_UPLOAD_TOO_LARGE` |
| 每 session 累計 | `filesystem.upload.files.max_session_bytes`（256 MiB） | `FILE_UPLOAD_QUOTA_EXCEEDED` |
| 每日檔數 | `filesystem.upload.files.max_files_per_day`（200） | `FILE_UPLOAD_QUOTA_EXCEEDED` |
| 可用空間 | max(512 MiB, 2×檔案大小) | `FILE_UPLOAD_NO_SPACE` |

**怎麼算，與圖片投放不同，而差別要寫下來：**
圖片投放數 `.cliora/uploads/<今天>/` 的檔案（現算，不維護計數器），
因為那個目錄是平台自有的。本期的檔案**散落在使用者選的位置**，
檔案系統上沒有任何地方記著「平台今天放了幾個檔案」。

所以用**記憶體計數器**：`map[sessionID]{day string; bytes int64; count int}`，
`Service` 上一個 mutex，跨日時重設。

**代價要寫下來：daemon 重啟會歸零。** 可接受，因為這個上限守的是
「壞掉的客戶端」而不是「惡意的使用者」（後者持有 `terminal.operate`，`00-…md` D0），
而磁碟填滿這個真正的風險由可用空間檢查直接擋住。
**被否決**：寫進磁碟（要決定寫在哪、多久 fsync、損毀了怎麼辦 —— 為一個
256 MiB 的軟上限不值得）；掃描整個工作區去統計（不可能 —— 平台不知道哪些檔案是它放的，
而那正是 `01-…md` §2 所說「使用者選的位置由使用者負責」的另一面）。

**沒有保留期，也不做清理。** 理由是 `01-…md` §2 對 W2 的修訂：
本期落地的檔案是使用者的資料。`PruneUploads` 只處理 `.cliora/uploads/`，
本期**不改它**。

---

## 5. 設定

`FilesystemConfig.Upload` 新增一個子區塊，**既有的鍵一個都不動**：

```yaml
filesystem:
  upload:
    enabled: true                    # 既有：圖片投放（ADR 0024）
    max_bytes: 4194304               # 既有：兩條路徑共用的單檔上限
    max_session_bytes: 67108864      # 既有：圖片投放的累計上限
    max_files_per_day: 200           # 既有：圖片投放
    retention_days: 7                # 既有：圖片投放
    files:                           # 本期新增
      enabled: true                  # W4；預設 true（00-…md D7）
      max_session_bytes: 268435456   # 256 MiB
      max_files_per_day: 200
      min_free_bytes: 536870912      # 512 MiB
```

- `files.enabled` 用 `*bool`（與 `Upload.Enabled` 相同），並設
  `FileUploadFromDefault` 旗標，讓 `doctor` 能分辨「明確設成 true」與「沒設」。
- **不新增 `files.max_bytes`。** 單檔上限兩條路徑共用一個鍵，
  由 `TestUploadCapFitsFrameBound` 斷言它 base64 之後仍在 `MaxFilePayload` 之內
  （`00-…md` D3）。給兩條路徑各一個上限，就是給了它們不一致的可能，
  而不一致的那一天沒有人會發現，直到一個 8 MiB 的檔案讓節點的解碼器沉默地丟掉訊框。

---

## 6. `doctor`

`agentd doctor` 新增兩行，與既有的 `image-upload=…` 並列：

```text
[info] file-upload=enabled (filesystem.upload.files.enabled: default)
[info] workspace free space: 42.1 GiB (min 512 MiB)
[warn] workspace free space: 380 MiB — uploads will be refused
```

`file-upload=disabled` 時只印第一行。**第二／三行是本期唯一會做 syscall 的
doctor 檢查**，而它不寫任何東西（與 `plan/14` 曾經要做的 hardlink 探測不同）。

---

## 7. 訊框

`filesystem.store` 加入 `LargeFrameTypes`（`daemon/internal/protocol/codec.go`），
成為第二個使用 8 MiB 上限的**請求**型別。回應 `filesystem.stored`
是一個路徑加兩個純量，維持 64 KiB。

`codec.go` 現有的註解說 `filesystem.upload` 是「第一個」——
補一句 `filesystem.store` 是第二個，並說明**上限沒有變**：
4 MiB 原始 → base64 5.33 MiB → 仍在既有的 8 MiB 之內。
這一句要寫進契約 CHANGELOG，因為它是「為什麼這次不必再放寬訊框」的唯一理由。

---

## 8. 測試（`go test -race ./...`）

| 檔案 | 測什麼 |
|---|---|
| `internal/workspace/root_test.go` | `StatIn` 的逃逸測試；`mapPathErr` 把 `EEXIST` 對應到 `ErrExists`；`CreateExclusive` 對已存在目標回 `ErrExists`（既有測試補一格） |
| `internal/files/store_test.go` | 八個步驟的每一個否決分支（~14 條）；成功後權限是 `0644`（來源模擬 0777 也一樣）；`.part` 在失敗後不殘留；temp 與目標同目錄；目的地是 in-root symlink 時被拒 |
| `internal/files/store_policy_test.go` | §2 那張表逐列；`.git` 三種（`.git/config`、末段 `.git` 檔案、`foo/.git`）；`.env` 與 `id_rsa` 當檔名；目的地在 `.ssh/` 之下；`node_modules/`；`.cliora/`；工作區根目錄可以放檔案但 `rel == "."` 被拒；非 ASCII 檔名可以通過 |
| `internal/files/store_quota_test.go` | 每日與累計跨日重設；`min_free_bytes`（用一個注入的 `freeBytes` 假函式）；`Statfs` 失敗時**放行**且記 warn |
| `internal/files/upload_test.go` | **既有測試必須全綠且未修改** —— 這是 `00-…md` D10 的證據 |
| `internal/config/config_test.go` | `files` 預設值；`enabled` 缺項記為 default；`TestUploadCapFitsFrameBound` |
| `internal/connection/files_integration_test.go` | `filesystem.store` 端到端；非嚴格 base64 被拒；解碼後超大被拒；`filesystem.store` 在 8 MiB 名單內、`filesystem.stored` 不在 |

**兩條要特別寫的測試：**

1. **競賽測試（`-race`）**：兩個 goroutine 用同一個 `dir`／`name` 同時 `Store`，
   必須恰好一個成功、一個收到 `FILE_EXISTS`，而且檔案內容是成功那一個的完整內容
   （不是兩者交錯）。這條會實際跑到 `O_EXCL` 與 temp 的 ULID 後綴。
2. **不覆寫的負向測試**：目標已存在且內容為 `A`，上傳內容 `B` 得到 `FILE_EXISTS`
   之後，斷言該檔案的 **SHA256 與 mtime 都沒有變**。
   只斷言「回了錯誤碼」是不夠的 —— 本期最重要的保證是「既有位元組不會被動到」。
