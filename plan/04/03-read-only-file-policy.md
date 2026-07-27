# 03 — Read-Only File Policy（P3-W3）

對應 `research/01/04-phase-3-workspace-files.md` §P3-W3，涵蓋 ticket **P3-05**（daemon `filesystem.read` handler 與檔案讀取安全政策）。Central 的 `content` 端點 relay 已於 [02](./02-directory-list-and-search-relay.md) §P3-06 定義。需求：FR-FILE-002/003/004/005、SEC-001/004/006、tech §11.5/11.6/11.7。

## 目標

在 daemon 實作「唯讀、bounded、預設安全」的單檔讀取：先 `stat` 再 bounded read（防 check 後變大）、判斷 binary、拒絕敏感檔、拒絕權限不足、**預設拒絕不確定型別**，並回足夠讓前端呈現的 metadata（language hint/encoding/mtime/size/denial reason），但**絕不洩漏敏感內容或 server absolute path**。failed sensitive read 觸發 audit 事件（內容見 [06](./06-audit-and-observability.md)）。

## P3-05：Daemon `filesystem.read` handler

在 `dispatch()` 新增 `case "filesystem.read": m.handleRead(...)`，實作於 `daemon/internal/files/read.go` 與 `policy.go`。順序（tech §11.5）：

1. **path 驗證 + root-confined 開啟**：以 P3-03 `OpenFileInRoot` 取得已驗證 fd（避免 resolve→open 的 TOCTOU）。失敗回 `WORKSPACE_*`。
2. **regular file 檢查**：對 fd `fstat`；非 regular（dir/symlink/fifo/socket/device）→ `FILE_DENIED`（dir 由前端走 list）。
3. **sensitive deny（在讀內容之前）**：對檔名/相對路徑套 `denied_patterns` 四類比對（見下）；命中 → `FILE_DENIED` + denial reason（分類），**不讀內容**，觸發 audit。
4. **size 限制**：以 fd 的 `fstat` size 判斷；> `max_preview_size`(2 MiB) → `FILE_TOO_LARGE` + size，不讀內容（FR-FILE-003）。
5. **bounded read**：以 `io.LimitReader(fd, max_preview_size)` 從**同一 fd** 讀取（若讀取中檔案被改大，LimitReader 仍封頂，不 OOM；size 以 fstat 為準）。
6. **binary detection（tech §11.6）**：對已讀 bytes 的前 8 KiB：含 null byte → binary；否則 UTF-8 validation + 控制字元比例；輔以副檔名/MIME。binary → `FILE_BINARY` + `{mime,size,modified_at}`，**不回原始內容**（FR-FILE-004）。
7. **不確定型別預設拒絕**：無法判定為可安全預覽的文字（例如 UTF-8 驗證失敗但未達 binary 明確標準、或未知 MIME）→ 預設 `FILE_BINARY`/`FILE_DENIED`（依 ADR 0015），不回內容。
8. **成功**：回 `filesystem.content{ success:true, rel_path, size, modified_at, encoding(如 utf-8), language_hint, content }`。`language_hint` 由副檔名對應（`.py`→python、`.ts`→typescript…），供前端 Monaco，不影響安全。

**敏感檔案規則（tech §11.7，FR-FILE-005，四類；策略已確認採「平衡」）**：
- Exact name（主力）：`.env`、`id_rsa`、`id_ed25519`。
- Extension（主力）：`*.pem`、`*.key`、`*.p12`、`*.pfx`。
- Glob（**限縮、謹慎**）：`.env.*`。**不採寬鬆的 `*secret*`/`*credentials*`**——已確認以 exact/extension 為主，降低誤擋程式碼（如 `secret_handler.py`）的機率，代價是可能漏擋少數怪命名的敏感檔；此取捨與可設定的補強規則記入 ADR 0015。
- Directory：敏感目錄樣式（如 `.ssh/`、`.aws/`）於路徑任一段命中即 deny。
- admin 可於 config 調整（`filesystem.denied_patterns`）補上環境特有的敏感檔；預設清單對齊 FR-FILE-005 但避免過寬。

**permission deny**：open/read 遇 `EACCES` → `FILE_PERMISSION_DENIED`，不中斷整體、不洩漏路徑。

**TOCTOU 保證**：sensitive 判斷用「開啟後的路徑基準」，read 用「同一 fd」，size 用「fd fstat」；covering 測試包含 read 前把檔案 replace 成 oversize/敏感/symlink-to-outside，證明無法藉替換繞過或逃逸（延續 P3-03 race fixture）。

**回覆不洩漏**：denial 只回分類（code + safe reason），**不回檔案內容片段、不回完整 server absolute path**；binary/oversize 才附 `{size,modified_at,mime}` metadata；敏感檔連 metadata 也僅回分類（避免確認敏感檔存在性由 ADR 0014 統一）。

## 測試

**Daemon（`go test -race`，`-tags integration` 用 fixture workspace）**：
- sensitive fixtures（命中預設「平衡」規則）：`.env`、`.env.production`、`server.pem`、`deploy.key`、`id_rsa`、`.ssh/config` → 全 `FILE_DENIED`、無內容、觸發 audit。
- **誤擋反例（平衡規則下應可正常預覽，斷言不被擋）**：`secret_handler.py`、`credentials_test.ts`；`app_secret.txt`/`credentials.json` 這類非 exact/extension 命中者在預設下**不擋**（若特定環境需擋，由 admin 於 `denied_patterns` 補 exact name，並加對應測試）。
- binary：ELF、PNG、gzip、含 null byte 的檔 → `FILE_BINARY` + mime，無原始內容。
- oversize：> 2 MiB → `FILE_TOO_LARGE` + size，不讀。
- encoding：UTF-8（含多位元組 emoji/CJK）成功、`encoding:utf-8`；非 UTF-8（Latin-1/UTF-16）依 policy 預設拒絕或標記。
- 不確定型別：未知副檔名的純文字成功；未知副檔名的可疑內容預設拒絕。
- permission：`0000` 檔 → `FILE_PERMISSION_DENIED`。
- **TOCTOU**：stat 後 replace 成 oversize/敏感/symlink→outside，證明不繞過（size 由 fd、內容由 fd、容器由 handle）。
- not-found：`FILE_NOT_FOUND`。
- 回覆掃描：任何成功/失敗回覆都不含 server absolute path；敏感 denial 不含內容。

**對應需求**：FR-FILE-002（唯讀預覽的資料來源）、FR-FILE-003（size 限制）、FR-FILE-004（binary 判斷 + metadata）、FR-FILE-005（敏感檔保護）、SEC-001（路徑隔離）、SEC-004（敏感檔不可 web 預覽）、SEC-006（讀取敏感路徑失敗須 audit）。
