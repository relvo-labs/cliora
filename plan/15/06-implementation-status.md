# 06 — 實作進度與證據

本檔隨實作更新；「證據」欄只填**實際跑過的指令與其輸出位置**，不填計畫中的測試。

最後更新 2026-08-03：**`FU-01`–`FU-08` 全部完成並落地。`make check` 全綠；
`scripts/fu/evidence.sh` 15 道通過、0 失敗、1 筆誠實的 skip（需要瀏覽器的 probe）。**

> ### 下一輪從這裡接手
>
> **功能是可交付的。** 拖檔進檔案樹 → 節點落地 → 檔案樹出現，整條路徑都在程式碼裡。
>
> **唯一沒關的事：** `docs/security-review-p15.md` §7 最後一段記的
> **`.git` 的讀取方向仍未保護** —— `.git/config` 今天仍然預覽得到。
> 本期只補了寫入方向，因為關掉讀取會讓一批現在看得到的檔案變成看不到，
> 那需要它自己的 release note。**這不是本期的缺口，是本期特意切開的一半。**
>
> **這台機器上跑不了的一件事：**
>
> | 項目 | 原因 | 處置 |
> |---|---|---|
> | `DataTransfer` 對資料夾的 browser probe | 內建 Chromium 缺 `libatk-1.0.so.0`，且無免密碼 sudo | 改用 fail-closed 規則讓它失去閘門地位（`07-…md` §1）；probe 已寫好留在 `scripts/fu/datatransfer-probe.mjs`，在有瀏覽器依賴的機器上一行可跑 |
>
> **環境事實：**
>
> | 事實 | 值 |
> |---|---|
> | 工具鏈不在預設 PATH 上 | `export PATH="$HOME/.local/bin:/usr/local/go/bin:$HOME/.nvm/versions/node/v22.23.2/bin:$PATH"`（`scripts/fu/evidence.sh` 自己會補，不必外部設） |
> | Go | 1.26.5 |
> | Postgres | `postgresql+asyncpg://cliora:cliora@127.0.0.1:5432/cliora_test`，已 `alembic upgrade head` 到 `0020` |
> | `make test-db` 要同時設兩個變數 | `CLIORA_TEST_DATABASE_URL` **與** `CLIORA_DATABASE_URL` |
> | alembic 要在 `backend/` 目錄下跑 | `cd backend && CLIORA_DATABASE_URL=… uv run --project . alembic upgrade head` |

## `FU-01` 實測結果（原始輸出：[`07-open-measurements.md`](07-open-measurements.md)）

| # | 量測 | 閘門 | 結果 | 對實作的影響 |
|---|---|---|---|---|
| 1 | `DataTransfer` 對資料夾的表現 | ✔ | **跑不了** | 規則改成 fail-closed（只上傳能正面確認為檔案的項目），**因此不再是閘門** |
| 2 | 非 ASCII 檔名往返 | | 四個發現 | (A) `+` 在 query 是空白 → 前端必須 `encodeURIComponent`；(B) `%2F` 解出 `/` → **驗證必須在解碼之後**，這是安全審查第 3 題的答案；(C) NFC／NFD 在 ext4 上是兩個檔案 → 不做正規化；(D) `maxLength` 是 code point → 255 **位元組**的上限要各自實作 |
| 3 | `Statfs` 的可用空間 | | `Bavail` 與 `df` 相符，`Bfree` 高估 7.9 GiB | 確立用 `Bavail`（agentd 非 root，拿不到 root 保留區塊） |
| 4 | 空檔案在三個 consumer | | 三者都乾淨接受 `""` | `data` 的 `minLength: 0` ＋ 可選群組 pattern；空檔案可以上傳 |
| 5 | 敏感規則在寫入方向的誤擋率 | | **誤擋 0**（34780 檔中只擋到 2 個 `.env` 與 1 個 `.pem`） | 不動 `denied_patterns` 預設值。順手核對出：最擔心的 `*credentials*`／`*secret*` 兩個 glob **根本不在預設值裡** |

## Ticket 進度

| Ticket | 狀態 | 證據 |
|---|---|---|
| `FU-01` 行為實測 | 完成（1 項誠實記為跑不了） | `07-open-measurements.md`；`scripts/fu/{datatransfer-probe.mjs,statfs-probe.go}` |
| `FU-02` 治理 | 完成 | `docs/adr/0026-general-file-upload.md`；ADR 0024 的 W2 修訂＋header＋rejected 表加註；PRD 新增 `FR-FILE-010`（12 AC）、`NFR-005.AC-109` 再收窄、`NFR-005.AC-142` 二次修訂；tech §11.5／§11.7／§11.9.2；`requirements.json`＋`links.json`（49 條）＋`gates.json`（2 個） |
| `FU-03` daemon 落地面 | 完成 | `workspace/root.go` `StatIn`＋`ErrExists`；`files/store_policy.go`；`files/store.go`；`config` 的 `files` 子區塊；`doctor` 兩行；`store_test.go`／`store_policy_test.go`／`store_quota_test.go` 共 26 組，含 `-race` 併發測試 |
| `FU-04` 契約 v1.9.0 | 完成 | 2 個新 schema、`node-register.file_upload`、8 個 fixture、control-envelope 的兩個 `allOf` 分支與錯誤碼列舉、三個 consumer（Go／Python／TS）、CHANGELOG 十一條；`make contract` 95 個 fixture 全綠 |
| `FU-05` Central | 完成 | `POST /files/upload`；`_read_bounded_body` 抽出（兩條路徑共用）；`_reject_filename`；`store_file` relay；稽核加 `source`；三個錯誤碼；migration `0020`；`test_files_store_api.py` 25 組；`pytest` 1075 passed |
| `FU-06` 前端 | 完成 | `useFileUpload.ts`＋15 組測試；`FileTree` 放置目標＋7 組測試；`FileTreeToolbar` 挑檔；`client.uploadFile`＋`uploadWithProgress` 抽出；`SessionWorkspaceView` 上傳列與雙旗標閘門＋6 組測試；`vitest` 456 passed |
| `FU-07` 收尾 | 完成 | 兩份 SKILL.md；`scripts/fu/{check-no-overwrite,write-policy-scan,evidence}.sh`＋`internal/files/storescan`；2 個 gate 註冊；`docs/runbooks/file-upload.md`；`docs/release-note-file-upload.md`；error catalog 三列＋一句錯誤文案修正 |
| `FU-08` 安全審查與 exit | 完成 | `docs/security-review-p15.md`，九題全答，0 open finding、3 筆刻意記錄的 gap |

## 與計畫的差異

| # | 計畫怎麼說 | 實際怎麼做 | 為什麼 |
|---|---|---|---|
| 1 | `02-…md` §3 第 8 步：temp 檔＋rename 就位 | **直接以 `O_EXCL` 建立最終檔名**，沒有 temp 檔 | **被測試抓到的計畫錯誤。** `TestStoreConcurrentSameNameHasOneWinner` 一開始是「兩個都成功」：`renameat` 會**靜默覆寫**目的地，而 `os.Root` 沒有暴露 `RENAME_NOREPLACE`，所以 temp＋rename 交付不了 D2 的「永不覆寫」—— 也就是這整條路徑存在的理由。圖片投放可以用 rename 是因為它的檔名是自己產生的 ULID，不可能已經存在；這裡的名字來自客戶端。代價（檔案在寫完前就可見）記在安全審查 §8 與 runbook |
| 2 | `00-…md` D9：偵測到資料夾就整批拒絕 | **只上傳能正面確認為檔案的項目**，其餘整批拒絕 | 閘門實測跑不了（`07-…md` §1）。改成不依賴那個答案的 fail-closed 規則，於是閘門失去阻擋力而不是被跳過。兩條入口的規則因此不同（拖放查 `items`，挑檔不查），因為 `<input type=file>` 的 change 事件本來就沒有 `items` |
| 3 | 計畫未提 `ErrExists` 之外還要動 `mapPathErr` | 新增 `fs.ErrExist → ErrExists` 的對應 | 不加的話 `EEXIST` 會落到 `ErrInvalid`，使用者看到「無效的路徑」而不是「已經有同名檔案」—— 而後者是本期最常走到的一條路 |
| 4 | 計畫未提 `test_scope_006`／`007` | 兩個 scope guard **改寫而非刪除**，並新增 `007c` | 沿用 `SCOPE-011`（ADR 0021）與 p13 的同一個處理方式：收窄要留下可以被指著問的東西。`007` 從「唯一的寫入路徑是圖片投放」改成「**兩條寫入路徑都只會新增檔案**」—— 那才是真正該被守住的性質，而且 `DELETE`／`PUT` 出現時它會紅 |
| 5 | 計畫未提 `test_every_mounted_route_is_in_the_matrix` | 在 `test_authz.py` 的矩陣補一列 | 既有的守門機制抓到新端點沒有宣告授權。這是它存在的目的，不是障礙 |
| 6 | `03-…md` §2.6 說改 `FILESYSTEM_UPLOAD_BYTES` 的 label | 照做（`mime` → `source`），並確認**後端沒有這個 metric** | 那是 daemon 端的 series。後端只有 `op` label，而 `op="store"` 自動生效 |
| 7 | 計畫未提 `MinFreeBytes` 的型別 | 用 `*int64` 而不是 `int64` | 明確設 0 的意思是「關掉這個檢查」（某些容器檔案系統回報的數字沒有意義），那必須與「沒設」分得開 —— 與 `Enabled *bool` 同一個理由 |
| 8 | `05-…md` §3 只列三支 script | 另外寫了 `internal/files/storescan` | `write-policy-scan.sh` 要跑真正的政策函式而不是在 shell 裡重寫規則 —— 一條安全規則的第二份實作正是 ADR 0026 §4 在避免的東西。沿用 p13 `classifyscan` 的既有體例 |
| 9 | 計畫未提 `NFR-005.AC-109`／`AC-142` 的註冊 | **只改 PRD 正文，沒有進 `requirements.json`** | `requirements.schema.json` 的 criterion id pattern 是 `\.AC-[0-9]{2}` —— **兩位數**，所以 `AC-109` 與 `AC-142` 在結構上無法註冊。順手核對出 p13 的狀態表聲稱把 `NFR-005.AC-142` 標成 deprecated 並加了 review，而需求庫裡從來沒有那兩條。**兩位數上限是既有限制，本期不改它**（改 id pattern 會動到整個需求庫的鍵），但這個落差要留著記錄 |
| 10 | `01-…md` §4 說 `FR-FILE-005` 加 `review` | review 掛在 `FR-FILE-005.AC-01` 上，不是 requirement 上 | schema 只允許 criterion 帶 `review`；`rationale` 另有 400 字上限 |
| 11 | 計畫未提 `.gitignore`／清理 | **沒有任何清理程序，而且刻意不做** | ADR 0026 §5：落地位置是使用者選的，那是他的資料。runbook 明寫「如果有人問清理 job 在哪：沒有，而那就是答案」 |

## 從更早幾期帶過來的兩筆帳

| 待辦 | 來源 | 本期怎麼處理 |
|---|---|---|
| `FILE_UPLOAD_QUOTA_EXCEEDED` 的文案叫使用者「在檔案樹刪除不需要的圖片」，而那件事做不到 | ADR 0024 | **改文案**（改成「請在該 Node 上以終端機清理」），錯誤目錄與前端文案兩處都改。本期不做刪除，所以只能誠實 |
| `plan/13/05-…md` §2.2 計畫在檔案樹的 `.cliora/` 旁加「平台寫入」標記，但沒有實作而 `WF-08` 被記為完成 | `plan/13` | **仍未處理，且不在本期範圍。** 已再次核對：`frontend/src/components/file/` 底下沒有相關字串。要在 `plan/13/07-…md` 的差異表補一列，讓那份狀態表恢復可信 —— 那是 p13 的帳，不是這一期的 |
