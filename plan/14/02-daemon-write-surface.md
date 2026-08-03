# 02 — Daemon 寫入面（`WE-03`、`WE-03b`）

四個動詞、一份政策、兩種版本識別。整段程式碼的形狀刻意與
`daemon/internal/files/read.go` 對稱：**同樣的 default-deny 順序、同樣的
「否決不是 error」約定、同樣的「便宜且決定性的檢查排前面」**，
這樣兩個方向可以並排讀。

---

## 1. `workspace.Root` 要補的方法

`daemon/internal/workspace/root.go` 目前有
`OpenDir`／`OpenFile`／`MkdirAllIn`／`CreateExclusive`／`RenameIn`／`RemoveIn`／
`LstatIn`／`RealRel`／`FS`。本期補三個，全部沿用既有的 `relClean` ＋ `mapPathErr` 體例。
**目錄的刪除不需要新方法** —— 它是 `RenameIn`（搬進回收桶），與檔案的刪除同一條路徑（`00-…md` D6）。

| 方法 | 簽章 | 用途與注意 |
|---|---|---|
| `LinkIn` | `func (r *Root) LinkIn(oldRel, newRel string) error` | 回收桶的核心（`00-…md` D6）。`link(2)` 在目的地已存在時回 `EEXIST`，**這是我們要的語意**：trash 的檔名帶 ULID，撞名代表出事了，不是要重試。要新增一個 `ErrExists` 哨兵並在 `mapPathErr` 中對應 `fs.ErrExist` —— 目前的 `mapPathErr` 會把它落到 `ErrInvalid`，那會讓「已存在」與「路徑不合法」在錯誤碼上分不出來，而本期有三個地方要分（建立、更名、回收桶） |
| `OpenForReplace` | `func (r *Root) OpenForReplace(rel string) (*os.File, os.FileInfo, error)` | 以 `O_RDONLY\|O_NOFOLLOW` 開啟既有檔案並回傳 fd 與 `Stat()`。呼叫端拿它做三件事：算 revision、驗 `RealRel`、讀出 `info.Mode().Perm()` 以便複製權限。**不是 `OpenFile` 的別名** —— 它強制 `O_NOFOLLOW`，而 `OpenFile` 依賴 `os.Root` 對中間段的保護、允許最終段是 in-root symlink |
| `CreateTemp` | `func (r *Root) CreateTemp(dirRel, base string, perm os.FileMode) (*os.File, string, error)` | 在目標檔案的**同一個目錄**建立 `.{base}.{ULID}.part`，回傳 fd 與相對路徑。同目錄是硬性要求：rename 只在同一個檔案系統內原子。ULID 而不是固定後綴，是因為兩個瀏覽器同時存同一個檔案時固定後綴會互相踩到（第二個 `O_EXCL` 失敗，而它其實應該收到 412 而不是 500） |

`RemoveIn` 與 `RenameIn` 不動。**不新增 `Root.Chmod` 的包裝**：Go 的
`os.Root.Chmod` 文件明載在 Unix 上對「操作中被換成 symlink」有 race，
本期一律用 temp 檔自己的 `f.Chmod(mode)`（走 `fchmod`，綁在 fd 上）。
這一點要在 `root.go` 留註解，否則下一個人會很自然地補上那個包裝。

### 1.1 三個新的錯誤哨兵

`workspace/guard.go` 的錯誤集合新增：

```go
ErrExists = errors.New("workspace: path already exists")
ErrIsDir  = errors.New("workspace: path is a directory")
```

**不要加 `ErrNotEmpty`。** 目錄的刪除是把整棵子樹 rename 進回收桶，
不是 `rmdir`，所以 `ENOTEMPTY` 這條路徑在本期根本不存在。
加一個沒有呼叫端的哨兵，等於預告一個沒有被決定的功能
（而且會讓下一個人以為「刪除前要先清空」是規則）。

---

## 2. 版本識別（revision）

### 2.1 兩種定義，一種格式

```go
// FileRevision identifies the exact bytes a client was shown. Read is bounded
// by max_preview_size and refuses anything larger, so this always covers the
// entire file and never a prefix.
func FileRevision(content []byte) string   // "sha256:" + hex(sha256(content))

// DirRevision identifies the directory listing a client was shown: the sorted
// "name\ttype\n" lines of its IMMEDIATE entries, hashed. It answers "is this
// still the directory I looked at", which is the precondition a recursive
// delete needs — someone dropped a file in while you were not looking, and the
// delete is refused.
//
// Deliberately shallow, and deliberately NOT including size or mtime: a
// recursive hash would change every time the CLI touched anything anywhere
// below, which would make deleting a directory impossible while a CLI runs.
// Enumerating the subtree is walkSubtree's job (§3.2), not this one.
func DirRevision(entries []Entry) string
```

格式相同（`sha256:<64 小寫 hex>`），所以 wire 上的 `precondition` 只有兩種形狀
（`00-…md` D2、D3），不必為目錄發明第三種。

**型別不符會自然被擋住**：客戶端以為那是檔案而送了內容雜湊，
而目標現在是一個目錄 —— daemon 算出來的是目錄雜湊，兩者不會相等，
得到 `FILE_REVISION_MISMATCH`。這是正確的答案，不需要額外的錯誤碼。

### 2.2 誰算它

- **讀取時**：`files.Read()` 回傳 `FileRevision(content)`（進 `filesystem.content`）；
  `files.List()` 回傳 `DirRevision(entries)`（進 `filesystem.entries`）。
  **`List` 的 revision 要在分頁截斷之前、對完整排序後的清單計算** ——
  對半頁計算出來的值會隨 cursor 改變，那不是「這個目錄」的識別。
- **寫入前**：三個破壞性動詞都會重新開檔／重新列目錄、重新算，與請求帶來的值比對。
  **不快取**：一個放在 daemon 記憶體裡的 path→revision 表，會在
  session 重啟、檔案被 CLI 改動、daemon 更新之後說謊，而說謊的方向是「放行」。

### 2.3 成本與它落在誰身上

SHA-256 對 2 MiB 的成本要在 `WE-01` 第 5 項量（預估 1–2 ms）。
它加在**每一次預覽讀取**上，包括從不編輯的使用者。可接受的理由與 ADR 0024 對
全檔掃描的理由相同：`Classify()` 已經走過整個 buffer，雜湊是同一個數量級，
而 ADR 0015 給預覽的預算是 3 秒。

**被否決**：`filesystem.read` 加一個 `with_revision` 旗標，只有要編輯時才算。
那是為了省 1 ms 而在 wire 上多一個模式欄位，而且前端在點開檔案的當下
還不知道使用者接下來會不會按「編輯」。

---

## 3. 寫入方向的政策（`files/write_policy.go`）

一個函式，四個動詞共用，**在任何 syscall 之前**執行：

```go
// WritableClassification returns "" if rel may be acted on by verb, or a coarse
// refusal reason. It is the write-direction counterpart of
// SensitiveClassification and deliberately calls it rather than
// re-implementing it (ADR 0025 §1.3).
//
// verb is a parameter rather than three call sites each making their own
// judgement, because the .cliora/ rules differ per verb (§5.2) and a table that
// lives in four places is a table that will one day be updated in three.
func (p *Policy) WritableClassification(rel string, verb Verb) string
```

順序（default-deny，第一個命中就回）：

| # | 檢查 | 回傳 | 為什麼在這個位置 |
|---|---|---|---|
| 1 | 路徑正規化：`relClean` 已經擋掉絕對路徑、`~`、NUL、`..` 逃逸。這裡再擋**空片段**與**結尾斜線** | `invalid` | 便宜、決定性，而且它決定後面每一個字串比對看到的是什麼 |
| 2 | `.git` 保護：任何路徑片段等於 `.git`，**或最末片段等於 `.git`** | `git_metadata` | **這是一條全新的規則，不是把既有的搬過來。** 已核對：`.git` 在 `workspace.excluded_directories`（`config.go:143`），而那份清單的註解明寫「this is an ignore rule, **not a security control**」，它只影響自動展開與搜尋；`filesystem.denied_directories` 的預設值是 `.ssh`／`.aws`／`.gnupg`，**不含 `.git`**。所以今天直接指定路徑是讀得到 `.git/config` 的。兩種形式都要擋：一般 repo 的 `.git` 是目錄（片段命中）；**git worktree 與 submodule 的 `.git` 是一個內容為 `gitdir: …` 的檔案**（末段命中），改掉它等於把 worktree 指到別的地方 —— `WE-01` 第 6 項要先確認這個形狀 |
| 3 | `.cliora/` 保護：路徑在 `.cliora/` 之下 | `platform_owned` | 平台自己的目錄。**唯一例外見 §5.4**（從 trash rename 出來） |
| 4 | 既有的敏感規則：`SensitiveClassification(rel) != ""` | 原分類（`dotenv`／`private_key`／…） | **同一個函式**，不是複製（`00-…md` D4） |
| 5 | 排除目錄：任何片段命中 `workspace.excluded_directories`（`.git`、`node_modules`、`.venv`、`dist`、`build`、`__pycache__`） | `excluded_dir` | 檔案樹已經把它們標成不可展開；讓它們可寫會很奇怪，而且那些目錄的內容是工具產生的。**注意這一條在寫入方向確實是安全控制**，而同一份清單在讀取方向被明白宣告為「不是安全控制」—— 同一份資料被兩種強度使用，要在程式碼註解裡寫明，否則下一個人會以為可以隨手放寬它。`.git` 會被第 2 條先命中（分類比較精確），第 5 條是它的第二層 |
| 6 | **工作區根目錄**：`rel` 正規化後等於 `.`，且動詞是 rename 或 delete | `workspace_root` | 最明顯的災難性案例，而它剛好是 `relClean` 唯一會回傳的特殊值。放在最後是因為前五條也擋得住大部分寫法，但**它必須有自己的分類**，否則使用者會看到「無效的路徑」而不是「不能刪除工作區」 |

**回傳的是分類字串而不是 bool**，理由與讀取面相同：稽核與 metrics 需要粗分類，
而使用者面的文案需要知道「為什麼不行」——「這是 git 的內部檔案」與
「這是敏感檔案」對使用者的下一步不同。

### 3.1 目錄操作要對整棵子樹套用同一個判斷（`WE-03b`，D22）

目錄的 **rename 與 delete** 在動手之前先走一次有上限的子樹：

```go
// walkSubtree applies the write policy to every entry beneath dirRel and totals
// what a delete would move. It is the reason a recursive delete cannot be used
// to launder a per-file refusal: dropping a submodule's .git into the trash is
// exactly as forbidden as editing it in place.
//
// Bounded twice over: it stops at maxEntries (refusing rather than truncating —
// a truncated walk that says "looks fine" is worse than no walk) and it never
// follows a symlink into another tree.
func (s *Service) walkSubtree(root *workspace.Root, dirRel string, verb Verb) (
    entries int, bytes int64, blocked *BlockedEntry, err error)
```

| 情況 | 回傳的否決碼 |
|---|---|
| 任一項被 `WritableClassification` 拒絕 | `FILE_DIRECTORY_CONTAINS_PROTECTED`，reason 是**第一個**命中的分類，並帶上該項的工作區相對路徑 |
| 項目數 > `editing.max_directory_entries`（20000） | `FILE_DIRECTORY_TOO_LARGE` |
| （僅 delete）子樹位元組數放不進回收桶配額 | 先 `PruneTrashToFit`，仍不足才 `FILE_WRITE_QUOTA_EXCEEDED` |

三個要寫進註解的細節：

1. **更名也要走訪，不只刪除。** 把一個含 `.env` 的資料夾搬出
   `.gitignore` 涵蓋的位置，與直接動那個 `.env` 是同一件事。
   一致的規則也表示只有一份實作、一份測試。
2. **走訪中遇到 symlink 就當成一個項目計數，不跟進去。** 跟進去會離開這棵子樹，
   而 rename／delete 動的是子樹本身，不是 symlink 的目標。
3. **走訪的結果不快取。** 走完到 rename 之間仍有一個窗格，
   而那個窗格由 D3 的目錄 revision 覆蓋直屬層 —— 深處的變化擋不住。
   **這一點要誠實寫進 ADR 與 release note**：目錄刪除的保護是
   「四層一起」而不是「其中任何一層都完備」。

### 3.2 內容的檢查

位置由 §3 決定，**內容**由讀取面同一個函式決定：

```go
if verdict, _ := Classify(content); verdict != VerdictText {
    return WriteResult{Denied: true, Code: "FILE_CONTENT_NOT_TEXT"}, nil
}
```

這一行同時擋掉三件事：含 NUL 的內容（使用者會建立一個自己再也打不開的檔案）、
非 UTF-8 的位元組序列（wire 上是 JSON 字串，理論上不會發生，但 daemon 不以
「Central 應該檢查過了」為前提）、以及控制字元比例過高的內容。

**注意 `Classify` 對空內容回 `VerdictText`** —— 建立空檔案要能成功，這是對的。

---

## 4. 四個動詞

新檔 `daemon/internal/files/write.go`。共同的回傳型別與 `UploadResult` 對稱：

```go
type WriteResult struct {
    RelPath     string
    Revision    string   // 寫入後的新版本；delete 時為空
    OldRevision string   // 被覆寫或刪除的版本；create 時為空
    Size        int64
    ModifiedAt  time.Time
    TrashPath   string   // 舊版本被搬到哪；create 與 mkdir 時為空
    Kind        string   // "file" | "directory"
    Entries     int      // 僅目錄的 rename/delete：走訪到的項目數
    Bytes       int64    // 僅目錄的 delete：搬進回收桶的位元組數

    Denied bool
    Code   string
    Reason string
}
```

`Denied` 不是 error，只有非預期失敗回 err —— 與 `Read`／`SaveImage` 同一個約定。

### 4.1 `Write`（建立與覆寫）

```go
func (s *Service) Write(root *workspace.Root, rel string, content []byte,
                        pre Precondition, now time.Time) (WriteResult, error)
```

`Precondition` 是一個小型別，只有兩種形狀（`00-…md` D2）：

```go
type Precondition struct {
    Absent   bool
    Revision string // 兩者互斥，且必有其一；由解碼層保證
}
```

順序：

| # | 步驟 | 否決碼 |
|---|---|---|
| 1 | 功能是否啟用（W4） | `FILE_WRITE_DISABLED` |
| 2 | `len(content) > maxWriteBytes`（＝`maxPreview`） | `FILE_WRITE_TOO_LARGE` |
| 3 | `WritableClassification(rel)` | `FILE_DENIED` ＋ reason |
| 4 | `Classify(content) != VerdictText` | `FILE_CONTENT_NOT_TEXT` |
| 5 | 每日寫入次數配額 | `FILE_WRITE_QUOTA_EXCEEDED` |
| 6 | **前提比對**（見下） | `FILE_EXISTS` ／ `FILE_NOT_FOUND` ／ `FILE_REVISION_MISMATCH` |
| 7 | 舊版本進回收桶（僅覆寫；`03-…md` §2） | `FILE_TRASH_UNAVAILABLE` |
| 8 | temp → 寫入 → `fsync` → `f.Chmod(oldPerm)` → rename | — |

**第 6 步的兩條分支：**

```
Absent:
    LstatIn(rel) 必須是 ErrNotFound；否則 FILE_EXISTS
    MkdirAllIn(parent, 0o755)        ← 隱含補父目錄（00-…md D8；顯式建目錄見 §4.4）
                                       0755 而不是 0700：這是使用者的原始碼樹，
                                       0700 會讓同機的其他工具讀不到

Revision:
    f, info := OpenForReplace(rel)           O_NOFOLLOW；ErrNotFound → FILE_NOT_FOUND
    realRel := RealRel(f)                    綁 inode
    WritableClassification(realRel) 必須為空 ← 讀取面 3b 的寫入版本
    info.Mode().IsRegular() 必須為真          否則 FILE_DENIED / not_regular
    Revision(讀出的內容) 必須等於 pre.Revision  否則 FILE_REVISION_MISMATCH
    oldPerm = info.Mode().Perm()
```

`realRel` 那一步是**讀取面 §3b 的鏡像**，而且在寫入方向更重要：讀取面被繞過是
看到不該看的，寫入面被繞過是**覆寫**不該覆寫的（例如工作區內
`notes.txt -> .env`，`O_NOFOLLOW` 會擋住最終段的 symlink，但 `RealRel` 是
對「中間段有 symlink 讓路徑指到別處」的第二道）。

**第 8 步的順序不能換：** `f.Chmod` 一定要在 rename **之前**，
否則有一個窗格是新檔案已經就位但權限還是 0600 —— 對一個正在被執行的腳本，
那個窗格會表現為 `Permission denied`。

失敗時 `RemoveIn(tempRel)`，與圖片投放同一個形狀。

### 4.2 `Rename`（檔案與目錄）

```go
func (s *Service) Rename(root *workspace.Root, fromRel, toRel string,
                         pre Precondition, now time.Time) (WriteResult, error)
```

| # | 步驟 | 否決碼 |
|---|---|---|
| 1 | 功能是否啟用 | `FILE_WRITE_DISABLED` |
| 2 | `fromRel != toRel`（正規化後）；`toRel` 不得在 `fromRel` 之下 | `FILE_DENIED` / `same_path`｜`into_self` |
| 3 | `WritableClassification(fromRel, VerbRename)`（**允許 trash 例外**，§5.4） | `FILE_DENIED` ＋ reason |
| 4 | `WritableClassification(toRel, VerbRename)` | `FILE_DENIED` ＋ reason |
| 5 | `LstatIn(fromRel)` 決定型別，並分岔到 5a／5b | `FILE_NOT_FOUND` |
| 5a | **檔案**：`OpenForReplace` → `RealRel` → regular → `FileRevision` 比對 | `FILE_REVISION_MISMATCH` |
| 5b | **目錄**：`walkSubtree`（§3.1）→ `DirRevision(直屬項目)` 比對 | `FILE_DIRECTORY_CONTAINS_PROTECTED` ／ `FILE_DIRECTORY_TOO_LARGE` ／ `FILE_REVISION_MISMATCH` |
| 6 | 目的地父目錄：必須**已存在**且是目錄 | `FILE_NOT_FOUND` / `parent_missing` |
| 7a | **檔案**：`LinkIn(fromRel, toRel)` → 成功後 `RemoveIn(fromRel)` | `FILE_EXISTS`（Link 回 `EEXIST`） |
| 7b | **目錄**：`LstatIn(toRel)` 必須是 `ErrNotFound` → `RenameIn(fromRel, toRel)` | `FILE_EXISTS` |

**第 2 步的 `into_self` 是目錄才有的陷阱**：把 `src` 更名成 `src/old` 會被
`renameat` 以 `EINVAL` 拒絕，但那個錯誤會落到 `ErrInvalid`，
使用者看到「無效的路徑」而不知道自己做了什麼。前置比對一次前綴，給一個能讀的答案。

**第 6 步刻意與 `Write` 不同：更名不補父目錄。** 建立時使用者是在輸入一個新路徑，
補父目錄是他的意圖；更名時使用者是在改一個名字，把 `src/a.go` 打成 `scr/a.go`
應該得到錯誤，而不是一個新目錄。

**第 7 步為什麼分成兩種寫法，要寫進註解：**

`renameat` 會**靜默覆寫**目的地，而 `os.Root` 沒有暴露 `RENAME_NOREPLACE`
（那需要 `renameat2` 與一個裸的 dirfd，而拿到裸 dirfd 等於在 `os.Root` 之外
開第二條路徑 —— 為了關掉一個 race 而打開一個更大的洞）。

- **檔案**用 `link(2)`：它在目的地存在時回 `EEXIST`，是**原子的**「不覆寫」。
  代價是 link 之後、unlink 之前程序死掉會讓檔案同時出現在兩個名字下 ——
  那是**重複**不是遺失，使用者看得到也刪得掉。反過來的順序失敗才會是遺失。
- **目錄**不能 hardlink，所以只能 `Lstat` 之後賭一個窗格。**這個殘留風險是有界的**，
  值得逐條寫下來而不是含糊帶過：目的地若是非空目錄，`renameat` 回 `ENOTEMPTY`（安全）；
  若是檔案，回 `ENOTDIR`（安全）；**唯一會被靜默取代的是一個在窗格內剛好出現的空目錄**，
  而那損失的是零位元組。這是本期接受的唯一一個 TOCTOU，接受它的理由是
  另一個選項（裸 dirfd）會破壞 W1。

**第 5 步的 revision 對更名有意義嗎？** 有：更名不改內容，但它會改變「這是哪一個檔案」。
使用者在檔案樹上看到 `a.go` 並按下更名，中間 CLI 把 `a.go` 換成了別的東西 ——
沒有前提的話，被改名的是那個別的東西。這正是 `00-…md` D2 那條規矩在講的事。

### 4.3 `Delete`（檔案與目錄）

```go
func (s *Service) Delete(root *workspace.Root, rel string,
                         pre Precondition, now time.Time) (WriteResult, error)
```

| # | 步驟 | 否決碼 |
|---|---|---|
| 1 | 功能是否啟用 | `FILE_WRITE_DISABLED` |
| 2 | `pre.Absent` 為真 → 直接否決 | `FILE_DENIED` / `invalid_precondition` |
| 3 | `WritableClassification(rel, VerbDelete)`（**允許 trash 例外**，§5.3；工作區根目錄在此被擋） | `FILE_DENIED` ＋ reason |
| 4 | `LstatIn(rel)` 決定型別：symlink → 直接 `RemoveIn` 並結束（見下） | `FILE_NOT_FOUND` |
| 5a | **檔案**：`OpenForReplace` → `RealRel` → regular → `FileRevision` 比對 | `FILE_REVISION_MISMATCH` |
| 5b | **目錄**：`walkSubtree`（§3.1）→ `DirRevision(直屬項目)` 比對 | `FILE_DIRECTORY_CONTAINS_PROTECTED` ／ `FILE_DIRECTORY_TOO_LARGE` ／ `FILE_REVISION_MISMATCH` |
| 6 | 回收桶配額：`PruneTrashToFit(bytes)`，仍不足則否決 | `FILE_WRITE_QUOTA_EXCEEDED` |
| 7 | `RenameIn(rel, trashRel)` —— **這一步就是刪除**（`03-…md` §2.2） | `FILE_TRASH_UNAVAILABLE` |

**第 7 步對檔案與目錄是同一行程式碼。** 這是 `00-…md` D6 改用 rename 之後
最大的收穫：刪一個資料夾與刪一個檔案走同一條路徑，
整棵子樹在一個 syscall 內離開原位，沒有中間狀態、沒有部分刪除、
沒有「刪到一半失敗」這種需要收拾的形狀。還原也一樣（`03-…md` §2.4）。

**symlink 的刪除是允許的**（第 4 步）：`unlink` 不跟隨 symlink，
刪掉一個指向別處的連結不會動到目標。它也不進回收桶 —— 回收桶存的是內容，
而 symlink 沒有內容（要救回它只需要重新建立，但本期不提供建立 symlink，
所以這一點要在 UI 的刪除確認上寫明：**符號連結刪除後無法從回收桶還原**）。
`pre` 對 symlink 沒有意義，第 4 步直接放行 —— 這是本期唯一一個
「破壞性操作沒有版本前提」的縫，要在 ADR 與測試裡指名。

> **這條縫要不要補？** 可以：對 symlink 要求 `pre.Revision == FileRevision([]byte(target))`。
> 不做的理由是它會讓 `filesystem.content` 也要為 symlink 回傳一個 revision，
> 而讀取面今天根本不預覽 symlink。**留著這條縫並寫下來**，比補一個
> 只有一個呼叫端、而且與讀取面不對稱的機制好。

### 4.4 `Mkdir`

```go
func (s *Service) Mkdir(root *workspace.Root, rel string, now time.Time) (WriteResult, error)
```

| # | 步驟 | 否決碼 |
|---|---|---|
| 1 | 功能是否啟用 | `FILE_WRITE_DISABLED` |
| 2 | `WritableClassification(rel, VerbMkdir)` | `FILE_DENIED` ＋ reason |
| 3 | 每日寫入次數配額（與 `Write` 共用同一個計數器） | `FILE_WRITE_QUOTA_EXCEEDED` |
| 4 | `LstatIn(rel)` 必須是 `ErrNotFound` | `FILE_EXISTS` |
| 5 | `MkdirAllIn(rel, 0o755)` | — |

**沒有 `precondition` 參數**，而這是刻意的（`00-…md` D2）：
`mkdir(2)` 在 syscall 層就不可能覆蓋任何東西 —— 目標存在就 `EEXIST`，
不管它是檔案還是目錄。替它發明一個只有一種合法值的欄位，
會讓「每一個破壞性操作都帶前提」這句話從一條規矩退化成一種格式。
第 4 步的 `Lstat` 只是為了給出 `FILE_EXISTS` 這個明確的碼，
真正的保證來自第 5 步的 syscall。

**`MkdirAllIn` 而不是 `Mkdir`**（補齊父目錄）：與建立檔案時的行為一致。
輸入 `docs/adr/drafts` 而 `docs/adr` 不存在時，兩個都建 ——
使用者在對話框裡看得到最終路徑，而「請先建立上層資料夾」是一句沒有意義的錯誤。

**0755 而不是 0700**：這是使用者的原始碼樹，與 `Write` 的父目錄同一個理由。
（對比 `.cliora/uploads/` 用 0700 —— 那是平台自己的目錄，沒有別人要讀。）

---

## 5. 四個必須寫死並被測試釘住的細節

### 5.1 `.git` 的兩種形狀

```go
// A worktree's or submodule's .git is a FILE containing "gitdir: …", not a
// directory. The existing denied_directories check matches path SEGMENTS, so it
// catches `.git/config` but not a bare `.git` file — and rewriting that file
// repoints the entire worktree. Both forms are refused here.
```

測試要兩個 case：`.git/config`（目錄形式）與 `.git`（檔案形式），
外加 `foo/.git`（巢狀 submodule）。

### 5.2 工作區根目錄

`rel` 正規化後等於 `.` 時，`rename` 與 `delete` 一律拒絕，分類 `workspace_root`。

```go
// The workspace root is the one path where "delete this" means "delete
// everything the session exists to work on". relClean already collapses "",
// "." and "./" to ".", so this is a single comparison — but it needs its own
// classification, because a user who tries it must be told what happened, not
// handed "invalid path".
```

`write` 與 `mkdir` 對 `.` 自然會失敗（前者是目錄、後者已存在），
但仍然走同一條檢查以取得一致的錯誤碼。

測試要包含 `.`、`""`、`./`、`a/..` 四種寫法。

### 5.3 `.cliora/` 是平台的

任何動詞在 `.cliora/` 之下都拒絕，除了 §5.4。這包括
`.cliora/uploads/**` 的**編輯與更名** —— 但**刪除**要允許，
因為 ADR 0024 的 `FILE_UPLOAD_QUOTA_EXCEEDED` 錯誤訊息已經對使用者說了
「請在檔案樹的 `.cliora/uploads/` 刪除不需要的圖片」，而在本期之前
那件事根本做不到。這是本期順手補上的一個既有的空頭支票。

`Verb` 是 `VerbWrite`／`VerbMkdir`／`VerbRename`／`VerbDelete`（§3 的簽章已帶它）。
`.cliora/` 的規則：

| 路徑 | write | mkdir | rename | delete |
|---|---|---|---|---|
| `.cliora/uploads/**` | 拒 | 拒 | 拒（來源與目的地皆拒） | **允許** |
| `.cliora/trash/**` | 拒 | 拒 | **允許作為來源**（§5.4） | 允許 |
| `.cliora/.gitignore`、`.cliora/` 本身、其他 | 拒 | 拒 | 拒 | 拒 |

把 `verb` 傳進政策而不是在呼叫端各自判斷，是為了讓這張表只有一個地方 ——
四個動詞各判一次，就會有一天只有三個被改到。

**注意 `.cliora/uploads/<日期>/` 這個目錄本身的刪除是拒絕的**（只有其中的檔案可刪）：
那些日期目錄由 daemon 的清理程序管理，讓使用者刪掉一個空的日期目錄不會有壞處，
但讓它可刪就要回答「刪掉今天的目錄之後正在進行的上傳怎麼辦」。不值得。

### 5.4 從回收桶還原

唯一允許 `from` 在 `.cliora/` 之下的情形：

```
from 以 ".cliora/trash/" 開頭  且  to 不以 ".cliora/" 開頭
```

寫死，不可設定，並在程式碼裡留註解說明它為什麼存在（`00-…md` D7）。
測試要有兩個負向 case：`from` 在 `trash` 而 `to` 也在 `.cliora/` 之下 → 拒絕；
`from` 在 `uploads` 而 `to` 在工作區一般位置 → 拒絕（只有 trash 是還原來源）。

**目錄的還原走同一條規則**：trash 裡的目錄 rename 出來，整棵子樹一起回到原位。
還原時 §4.2 第 5b 步的 `walkSubtree` 仍然要跑 —— 一個在回收桶裡待了六天的目錄，
它裡面的東西不會因為待過回收桶就免除政策檢查。

---

## 6. 設定

`daemon/internal/config/config.go` 的 `FilesystemConfig` 新增：

```yaml
filesystem:
  editing:
    enabled: true                     # W4；預設 true（00-…md D10）
    max_writes_per_day: 2000
    max_directory_entries: 20000      # 目錄 rename/delete 的走訪上限（D22）
    trash:
      retention_days: 7
      max_session_bytes: 67108864     # 64 MiB
      max_copy_bytes: 4194304         # hardlink 失敗時願意複製的上限
```

- `enabled` 用 `*bool`（與 `UploadConfig.Enabled` 相同），並設 `EditingFromDefault`
  旗標，讓 `doctor` 能分辨「明確設成 true」與「沒設」。
- **不設 `max_write_bytes`。** 它等於 `max_preview_size`，由
  `TestWriteCapEqualsPreviewCap` 斷言（`00-…md` D11）。給它一個獨立設定鍵，
  就是給了兩者不相等的可能。

---

## 7. 訊框與解碼

`filesystem.write` 加入 `LargeFrameTypes`（`daemon/internal/protocol/codec.go`），
成為第二個使用 8 MiB 上限的**請求**型別。`mkdir`／`rename`／`delete` 與四個回應型別
（`written`／`directory_created`／`renamed`／`deleted`）都是小訊息，維持 64 KiB ——
**包括目錄刪除的回應**，它只帶路徑與兩個計數，不帶被刪項目的清單。
（會有人想加那份清單，好在 UI 上顯示「刪除了這 300 個檔案」。不加：
那是一個大小隨使用者資料成長的回應，而使用者真正需要知道的是它們去了哪裡。）

`codec.go` 現有的註解說 `filesystem.upload` 是「第一個」—— 那句話仍然為真，
但要補一句 `filesystem.write` 是第二個，並說明它的上限來源不同：
upload 是 4 MiB base64 後的長度，write 是 2 MiB 純文字加 JSON 逃脫的最壞情況
（每個字元變成 `\uXXXX` 是 6 倍 → 12 MiB，超過 8 MiB）。

> **這是一個要在 `WE-05` 解掉的實際問題。** 一個 2 MiB 全是控制字元的檔案不可能存在
> （`Classify` 會擋），但一個 2 MiB 全是 CJK 的檔案在 JSON 裡是 3 位元組字元
> 直接輸出（不逃脫），仍是 2 MiB。真正會膨脹的是 `"`、`\` 與 `\n`，各變成 2 位元組。
> 最壞情況（全是 `\n`）是 2 倍＝4 MiB，仍在 8 MiB 之內。
> **這個推導要寫進契約 CHANGELOG**，因為它是「為什麼 8 MiB 夠」的唯一理由。

---

## 8. 測試（`go test -race ./...`）

| 檔案 | 測什麼 |
|---|---|
| `internal/workspace/root_test.go` | `LinkIn` 的三個逃逸測試（`../` 目的地、指向 root 外的 symlink、目的地已存在回 `ErrExists`）；`OpenForReplace` 對最終段 symlink 回 `ErrInvalid`；`CreateTemp` 的名字落在同一個目錄 |
| `internal/files/write_test.go` | 四個動詞各自的每一個否決分支（共 ~34 條）；建立時補父目錄；`mkdir` 補父目錄且 0755；覆寫保留權限（0755 存完仍是 0755）；`.part` 在失敗後不殘留；temp 與目標同目錄 |
| `internal/files/write_dir_test.go` | 目錄的 rename／delete：`walkSubtree` 的兩個上限；含 `.git`／`.env` 時整個拒絕**且子樹一個位元組都沒動**；`into_self`；目的地已存在（空目錄與非空目錄兩種）；刪除後整棵子樹在 trash 裡結構完整；還原後檔案內容與權限相同 |
| `internal/files/write_roundtrip_test.go` | **`FR-FILE-010.AC-04`**：五種檔案（LF／CRLF／無結尾換行／BOM／tab 縮排）讀出再原樣寫回，SHA256 相同。這一份單獨開檔，因為它是 `GATE-WE-ROUNDTRIP` 的內容 |
| `internal/files/write_policy_test.go` | `.git` 兩種形狀＋巢狀；工作區根目錄的四種寫法；`.cliora/` 四個動詞的矩陣（§5.3 那張表逐格）；trash 還原的正負向；敏感規則對 rename 兩端；排除目錄 |
| `internal/files/revision_test.go` | `FileRevision` 與 `DirRevision` 的格式；空內容與空目錄；與 `Read`／`List` 回傳值一致；**`DirRevision` 在分頁截斷時不隨 cursor 改變**；`TestWriteCapEqualsPreviewCap` |
| `internal/files/trash_test.go` | 見 `03-…md` §5 |
| `internal/config/config_test.go` | `editing` 預設值；`enabled` 缺項記為 default |
| `internal/connection/files_integration_test.go` | 四個動詞端到端；precondition 缺失被解碼層拒絕；`filesystem.mkdir` **帶** precondition 時被拒；`filesystem.write` 在 8 MiB 名單內、另三個不在 |

**併發測試（`-race` 下）**：兩個 goroutine 對同一個檔案帶同一個 revision 同時 `Write`，
必須恰好一個成功、一個收到 `FILE_REVISION_MISMATCH`，且檔案內容是成功那一個的。
這條會實際跑到「temp 的 ULID 後綴避免互相踩」那個設計（§1 `CreateTemp`）。
