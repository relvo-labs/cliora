# 07 — 實作進度與證據

本檔隨實作更新；「證據」欄只填**實際跑過的指令與其輸出位置**，不填計畫中的測試。

最後更新 2026-08-01：**`WF-01`–`WF-11` 全部完成並落地。`make check` 全綠；
`scripts/wf/evidence.sh` 13 道 gate 執行、0 失敗、2 筆誠實的 skip（需要 stack 的 e2e、
本機無 WebP 編碼器）。**

> ### 下一輪從這裡接手
>
> **兩件事都可交付。** 圖片投放（貼上／拖放／挑檔 → 節點落地 → 路徑打進終端機）與
> 文字判定修正都在程式碼裡，不是計畫裡。
>
> **唯一還沒關的事：** `docs/security-review-p13.md` 第 8 題的結論需要被**下一期**接手 ——
> 它不是本期的缺口，而是本期特意留給編輯功能的輸入：W2 對編輯只成立一半，
> 而「敏感檔案政策要套到寫入方向」與「`.git/` 要保護」兩件事今天完全不存在，
> 也沒有可以照抄的先例。
>
> **這台機器上跑不了的兩件事：**
>
> | 項目 | 原因 | 處置 |
> |---|---|---|
> | 瀏覽器 e2e（貼上→CLI 讀圖） | 需要有 online node 的 stack（`scripts/e2e/run-stack.sh`） | `evidence.sh` 記為 skip；CLI 那一半已由 `WF-01` 手動實測（`08-…md` §4） |
> | WebP 實測 | 本機沒有任何 WebP 編碼器（`convert`／`magick`／`ffmpeg`／`cwebp`／PIL 皆無；Go 標準庫只編 PNG／JPEG／GIF） | 四種格式實測了三種；嗅探器的 WebP 分支有單元測試。若補測失敗，移除它是一行常數 |
>
> **環境事實：**
>
> | 事實 | 值 |
> |---|---|
> | 工具鏈不在預設 PATH 上 | `export PATH="$HOME/.local/bin:/usr/local/go/bin:$HOME/.nvm/versions/node/v22.23.2/bin:$PATH"` |
> | Postgres 可用 | `postgresql+asyncpg://cliora:cliora@127.0.0.1:5432/cliora_test`，已 `alembic upgrade head` 到 `0019` |
> | `make test-db` 要同時設兩個變數 | `CLIORA_TEST_DATABASE_URL` **與** `CLIORA_DATABASE_URL` |
> | `claude` 與 `codex` 都可用 | `claude 2.1.220`、`codex-cli 0.146.0`，都在 `$HOME/.local/bin` |
> | `codex exec` 在非 git 目錄要加旗標 | `--skip-git-repo-check`，否則拒絕啟動 |

## `WF-01` 實測結果（原始輸出：[`08-measurements.md`](08-measurements.md)）

| # | 量測 | 結果 | 對決策的影響 |
|---|---|---|---|
| A | 判定誤判率（本 repo 全樹） | 878 個合法 UTF-8 文字檔中 **20 個誤判**；成因 100% 是窗格切在 rune 中間 | 確立 D12／D13；也確立 D15：**誤判與編碼無關**，本期不引入轉碼 |
| B | ANSI／控制字元行為 | 每行三組顏色的 log、spinner、含換頁字元的檔案今天都被判為二進位 | 確立 D14 |
| C | 反向漏判 | 前 8 KiB 為可列印 ASCII、之後才有 NUL 的檔案被當成文字 | 產生 `FR-FILE-008.AC-03`；release note 必須預告「有些檔案會變成看不到」 |
| D | 全檔掃描成本 | 2 MiB → **2.66 ms**（vs 窗格版 11.6 µs） | 確立 D12；`FR-FILE-008.AC-05` 上限 5 ms（實測落在 2.2 ms） |
| 1 | **CLI 讀不讀得到相對路徑的圖**（閘門） | **成立。** claude 與 codex 都接受**裸的工作區相對路徑**，PNG／JPEG／GIF 三種格式六次全對 | **D1／D6 照原樣實作**，兩個備案都不必啟動 |
| 1b | codex 是否需要無沙箱姿態 | **不需要**：`sandbox: read-only` 預設下也讀得到 | 圖片投放**不依賴** ADR 0023 的姿態，寫進 ADR 0024 §2 |
| 2 | xterm.js 5.5.0 的 paste 行為 | 它只呼叫 `stopPropagation()`、且只讀 `text/plain` | 攔截點確定為「宿主元素＋capture 階段」，且只在有 files 時接手 |
| 3 | 連續送出的路徑在 CLI 輸入行 | **逐字顯示，未被折疊**成 `[Pasted text]` | D6 的「不送 Enter」可行 |
| 4 | WebP | **未量測**（本機無編碼器） | 見上表 |

## Ticket 進度

| Ticket | 狀態 | 證據 |
|---|---|---|
| `WF-01` | 完成（WebP 一項誠實記為未測） | `08-measurements.md` |
| `WF-02a` 姿態 | 完成 | `docs/adr/0024-workspace-write-posture.md`；ADR 0015 兩段 amendment；PRD §23 `NFR-005.AC-142` 改寫；`requirements.json` 標 `deprecated` ＋ review |
| `WF-02b` 需求 | 完成 | PRD 新增 `FR-FILE-009`（9 AC）＋ `NFR-005.AC-109` 加註 |
| `WF-02c` 判定 | 完成 | PRD 新增 `FR-FILE-008`（5 AC）、`FR-FILE-004` 註記、tech §11.6 改寫 |
| `WF-03` | 完成 | `policy.go` `Classify()`；40 個 corpus fixture ＋ `expected.json`；`policy_test.go` 8 組；`TestClassifyLatencyBudget` 2.2 ms |
| `WF-04` | 完成 | `workspace/root.go` 五個寫入方法；`files/upload.go`；`upload_test.go` 15 組（含兩種 `.cliora` 劫持）；`agentd doctor` 新增一段 |
| `WF-05` | 完成 | 契約 v1.8.0；2 型別＋1 欄位；5 個 invalid ＋ 3 個 valid fixture；`make contract` 96 綠 |
| `WF-06` | 完成 | `POST /files/images`；`file.upload`；migration `0018`＋`0019`；`tests/db/test_files_upload_api.py` 12 組 |
| `WF-07` | 完成 | `useImageDrop.ts`＋11 組測試；`typeText()`＋5 組測試；`SessionWorkspaceView` 三入口 |
| `WF-08` | 完成 | `PreviewDenied.vue` 區分 binary／`unsupported_encoding`＋2 組測試 |
| `WF-09` | 完成 | 三份 SKILL.md 各一段修訂 |
| `WF-10` | 完成 | `scripts/wf/{evidence,classify-scan,check-no-naming-channel}.sh`；2 個 gate 註冊；runbook；release note |
| `WF-11` | 完成 | `docs/security-review-p13.md`，八題全答，0 open finding |

## 與計畫的差異

| # | 計畫怎麼說 | 實際怎麼做 | 為什麼 |
|---|---|---|---|
| 1 | `04-…md` §2.5：nginx `client_max_body_size` 可能要調整 | **沒有動 `deploy/`** | 核對後兩處都已是 `16m`。計畫在撰寫階段就先改成「已確認不需要」 |
| 2 | `00-…md` D15 選用票 `WF-03b`（編碼轉碼） | **未做**，觸發條件寫在 `02-…md` §2.5 | 實測顯示誤判 0% 來自編碼。條件是上線後 `unsupported_encoding` 佔否決 >5% |
| 3 | `06-…md` §3 只列兩個 gate | 另外寫了 `classify-scan.sh` 與 `evidence.sh` | 前者同時是 runbook 工具（「某個檔案看不到」的第一步），後者是既有各期的體例 |
| 4 | 計畫未提 migration `0019` | 新增了 seed migration | RBAC 的真相有兩處：程式碼的 `ROLE_ACTIONS` 與 DB 的 `roles.permissions`。只改前者會讓 Developer 收到 403 —— 由 `test_files_upload_api.py` 抓到，走 `seed-migration` skill 的既有體例補上 |
| 5 | 計畫未提 `can_upload_files` | 在 `session_capabilities` 新增一個旗標 | 前端既有的決定是「權限＋擁有權由伺服器算」（`SessionWorkspaceView` 的註解）。在瀏覽器重算會與那個決定相衝突 |
| 6 | 計畫未提 `_map_error` | 新增五個 upload 錯誤碼的對應 | 不加的話 daemon 的 `FILE_UPLOAD_QUOTA_EXCEEDED` 會塌成 `INTERNAL_ERROR`，使用者看到「伺服器壞了」而不是「配額滿了」。由測試抓到 |
| 7 | 計畫未提 `DecodeControl` | daemon 端改成兩段式大小檢查 | daemon 過去只**產生**大訊框、不接收，所以沒有例外邏輯。`filesystem.upload` 是它第一個收到的 |
| 8 | 計畫未提 `-race` 與延遲預算的衝突 | `TestClassifyLatencyBudget` 在 race 下 skip，改由 `GATE-WF-CLASSIFY-CORPUS` 無 race 執行 | race detector 有約 15 倍開銷（實測 2.2 ms → 40 ms）。在 race 下斷言 5 ms 只會量到 detector |
| 9 | `06-…md` §2 說 `FR-FILE-004` 有兩個方向的違反 | 兩個都修好了，且**收緊的那一邊**寫進 release note | 「本來看得到現在看不到」如果沒有預告，回報會以 bug 的形式進來 |
| 10 | 計畫未提 `test_scope_006/007` | 兩個 scope guard 改寫而非刪除，並新增 `007b` | 這是 `SCOPE-011` 在 ADR 0021 之後的同一個處理方式：收窄要留下可以被指著問的東西 |
