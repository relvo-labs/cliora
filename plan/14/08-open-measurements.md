# 08 — 待實測項目（`WE-01`）

本檔在實測完成後填入原始輸出，體例沿用 `plan/13/08-measurements.md`
（`artifacts/*/local/` 是 gitignore 的，所以結果放這裡）。

**目前六項全部未測。** 其中第 1、6 項是閘門（`00-…md` §4）。

---

## 1.（閘門）`os.Root.Link` 與 `os.Root.Rename` 的語意與可用性

**為什麼要量：** `00-…md` D6 的整個回收桶設計建立在下列假設上 ——
覆寫那一半靠 `Link`，刪除那一半（含目錄）靠 `Rename`。
任何一個不成立，回收桶就要改設計（複製或拒絕），那是 ADR 修訂不是參數調整。

| 要確認的 | 方法 | 不成立的話 |
|---|---|---|
| 目的地已存在時 `Root.Link` 回 `EEXIST`（而不是覆寫或成功） | 小程式：建兩個檔案，`Link(a, b)`，斷言 error 且 `b` 內容未變 | 更名的「不覆寫」要改用 Lstat＋Rename，並接受 TOCTOU（`02-…md` §4.2 的被否決選項就會變成唯一選項） |
| 目的地路徑會被 `os.Root` 限制在 root 內 | `Link(a, "../outside")` 與 `Link(a, "link-to-outside/x")` | W1 破洞，本期停下來 |
| 節點實際使用的檔案系統支援 hardlink | 在 ext4、overlayfs（Docker）、以及一個實際的節點工作區上各試一次 | `03-…md` §2.5 的 fallback 從「例外」變成「常態」，`max_copy_bytes` 的預設值要重新決定 |
| 工作區含 submount 時 `EXDEV` 的實際表現 | 在工作區底下 mount 一個 tmpfs，對其中的檔案做刪除 | 同上 |
| **`os.Root.Rename` 對已存在目的地的行為** | 三格：目的地是非空目錄（預期 `ENOTEMPTY`）、是檔案（預期 `ENOTDIR`）、是空目錄（**預期靜默取代**） | 第三格若不是靜默取代，`02-…md` §4.2 第 7b 步的殘留風險敘述要改寫（會變成更好，但敘述要對）|
| **`os.Root.Rename` 可以搬動整個目錄** | 建一棵三層的樹，rename 到 `.cliora/trash/x`，確認結構完整、inode 不變 | 目錄刪除要改設計 —— 這是 `00-…md` D6 對目錄那一半的前提 |

**輸出格式：** 一段 Go 程式的原始輸出 ＋ `mount | grep <workspace>` 的結果。

---

## 2. Monaco 0.56 的往返忠實度

**為什麼要量：** `00-…md` D15 列了五項設定，但那份清單是從 Monaco 的
option 名稱推出來的，不是量出來的。真正的問題是「還有沒有第六項」。

**方法：** 五個 fixture 字串（LF／CRLF／無結尾換行／BOM／tab 縮排＋行尾空白），
各自 `createModel` → 不做任何編輯 → `getValue()`，比對是否完全相同；
再各自做一次「在中間插入一個字元又刪掉」之後比對。

**要特別看的：**

- `createModel` 對 `\r\n` 的預設 EOL 判定（它會不會依平台而非依內容）。
- BOM（`U+FEFF`）是留在 model 的第一個字元，還是被吞掉。
- `trimAutoWhitespace` 的預設值在這個版本是什麼（它會不會在**未編輯**的行上作用 —— 應該不會，但要確認）。
- 「插入又刪掉」之後 `getValue()` 是否回到原字串（undo stack 的正確性）。

**不成立的話：** 增加 D15 的清單，或（若某一項無法用設定關掉）
把該種檔案排除在編輯之外並在 UI 說明 —— 排除比偷改好。

---

## 3. rename-over 對 watcher 與 CLI 的影響

**為什麼要量：** `00-…md` D5 用 temp＋rename 換掉了「寫到一半失敗＝資料損毀」，
代價是換 inode。代價的實際大小沒有量過，而 release note 要寫。

**方法：**

| 對象 | 怎麼測 |
|---|---|
| `vite`／`nodemon` 之類的 watcher | 起一個 dev server，用 temp＋rename 改一個被 watch 的檔案，看有沒有觸發重載；與直接 `echo >` 對照 |
| `claude`／`codex` 已開啟的檔案 | 讓 CLI 讀一個檔案，rename-over 之後再問它同一個檔案的內容 |
| hardlink | 建一個 hardlink，rename-over 之後確認兩個名字的內容是否分岔（預期會） |
| 與 CLI 的衝突頻率 | 讓 claude 跑一個會改多個檔案的任務，同時在瀏覽器上編輯其中一個，記錄 412 出現的次數 |

**輸出：** 四段觀察 ＋ 最後一項的次數。最後一項決定 `05-…md` §1.4
橫幅的措辭 —— 若 412 是每分鐘都會遇到的事，措辭要更接近「情況說明」而不是「警告」。

---

## 4. 敏感規則在寫入方向的誤擋率

**為什麼要量：** `denied_patterns` 有 `*credentials*` 與 `*secret*`，
它們在讀取方向已經在擋東西了（所以不是回歸），但編輯會讓它變得刺眼 ——
「我連自己的 `secrets.test.ts` 都不能改」。

**方法：** `scripts/we/write-policy-scan.sh`（`06-…md` §3）對本 repo
與一個真實的使用者工作區各跑一次，輸出被拒絕的路徑數與分類分佈。

**判讀：**

- 若被擋的幾乎都是真的敏感檔案 → 不動預設值。
- 若被擋的大量是測試檔／文件 → 處置是**調整 `denied_patterns` 的預設值**
  （`FR-FILE-005` 本來就寫著「系統應允許管理員調整規則」），
  **不是**在寫入方向放寬。放寬會讓 `00-…md` D4 的對稱性破掉，
  而那條對稱性是本期最省事的一個設計。

---

## 5. SHA-256 與目錄走訪的成本

**為什麼要量：** 它加在**每一次**預覽讀取上，包括從不編輯的使用者
（`02-…md` §2.3）。

**方法：** Go benchmark，與 `plan/13/08-measurements.md` §3 的
`Classify` 2 MiB＝2.66 ms 並排，一起計入 ADR 0015 的 3 秒預算。

**預期：** 1–2 ms。若超過 10 ms，回頭考慮被否決的 `with_revision` 旗標。

**同一支 benchmark 順便量目錄走訪**（`02-…md` §3.1）：
1000／10000／20000 個項目的 `walkSubtree` 各要多久。
它不擋任何決定 —— 太慢就把 `max_directory_entries` 調低，而那本來就是設定 ——
但刪除一個資料夾的等待時間會直接被使用者感覺到，
所以數字要進 release note 或至少進 runbook。

---

## 6.（閘門）git worktree 的 `.git` 是檔案

**為什麼要量：** `00-…md` D4 與 `FR-FILE-011.AC-06` 直接建立在這個形狀上。

先把現況核對清楚（已看過程式碼，不是推測）：`.git` 在
`workspace.excluded_directories`（`config.go:143`），而那份清單的註解明寫
它是 ignore rule、**不是安全控制**，只影響自動展開與搜尋；
`filesystem.denied_directories` 的預設值是 `.ssh`／`.aws`／`.gnupg`，**不含 `.git`**。
換句話說 **`.git/config` 今天就可以被預覽**，只要使用者直接指定路徑。

在此之上還有一層：git worktree 與 submodule 的 `.git` 是一個內容為
`gitdir: /path/to/...` 的**純文字檔**，連「目錄」這個形狀都不成立。
本期會讓它可以被編輯，而改掉它等於把整個 worktree 指到別的地方。

**方法：**

```
git worktree add /tmp/wt-probe
file /tmp/wt-probe/.git          # 預期：ASCII text
cat /tmp/wt-probe/.git           # 預期：gitdir: …
```

再對 submodule 做一次。然後實際發一次 `filesystem.read` 確認它**可以**被預覽
（證明缺口存在，而不只是從設定推論）。

**不成立的話**（例如新版 git 改了形狀）：`FR-FILE-011.AC-06` 要重寫，
但保護仍然要做 —— 只是理由與實作要重新確認。

---

## 附：這一期沒有要量的東西

寫下來是為了讓「為什麼不量」也有紀錄：

| 沒量的 | 為什麼不用 |
|---|---|
| SHA-256 的碰撞 | 不需要量 |
| 「使用者實際上都在刪多大的資料夾」 | 上線前量不到。改為埋 `FILESYSTEM_DIRECTORY_ENTRIES`（`04-…md` §2.7），用真實資料回頭調 `max_directory_entries` |
| 2 MiB 內容在 JSON 裡的膨脹率 | 已經用推導蓋掉（`02-…md` §7）：最壞是全 `\n`＝2 倍＝4 MiB，在 8 MiB 之內 |
| `If-Match` 在既有 edge nginx 上會不會被剝掉 | 標準 header，nginx 預設不動它。若真的出事，症狀是 428 而不是靜默覆寫 —— **失敗方向是安全的**，所以不值得先量 |
| 使用者會不會誤刪 | 量不出來。處置是回收桶 |
