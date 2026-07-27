# 01 — 決策、Protocol v1.3 與 Path Security Library

對應 `research/01/04-phase-3-workspace-files.md` §P3-W1，涵蓋 ticket **P3-01**（決策 ADR 0014/0015）、**P3-02**（protocol v1.3 凍結）、**P3-03**（path security library 強化，硬性安全 Gate）。需求：FR-FILE-001…007 的安全前提、FR-WORKSPACE-001/002、SEC-001/002/004、tech §11.1/11.2/12.2/12.3。

## 目標

在對外開放任何 filesystem 端點**之前**，先凍結跨語言契約並把路徑安全核心做到可證明安全：每一次 list/read/search 都重新 canonicalize、在 symlink 解析後仍位於 allowed root、對 check→open 的 TOCTOU 採最安全可行策略，並以 fuzz/property 與惡意 fixture 全面拒絕逃逸。此 ticket 是 P3 的 **Gate**：未全綠前 P3-06（Central 端點）不得開放。

## 現況（P3 起點）

- `daemon/internal/workspace/guard.go`：`Guard.Resolve(target string) (string, error)` 已實作 tech §11.2 容器判斷，回傳 canonical path 與 `ErrInvalid/ErrOutside/ErrNotFound/ErrNotDir/ErrPermision`（字串即 `WORKSPACE_*` code）；`eval evalFunc` seam 讓測試以 fake symlink 解析驗證。P2 只在 `handleStart` 呼叫一次（launch 前）。
- `guard_test.go`：`go test -race ./internal/workspace` 已覆蓋 traversal、symlink、prefix-collision、null-byte。**尚無** fuzz/property test、broken-link、symlink-chain、TOCTOU（replacement/swap）、open-after-resolve 測試。
- `Guard.Resolve` **只回 path 字串**，呼叫端須再自行 `os.Open`/`os.Stat`——這正是 TOCTOU 破口（resolve 與 open 之間可被替換）。P3-03 要補上「回傳已開啟且已驗證的 handle」路徑。
- `contracts/v1/`：`schemas/messages/*.schema.json` + `fixtures/{valid,invalid}` + `manifest.json`（accept/reject 為跨語言真理來源，payload 級規則也在契約內）。P0 凍 v1、P2 凍 v1.2；filesystem 訊息尚未入契約。

## P3-01：決策 ADR 0014 / 0015

在動工前產出兩份 ADR（延續 0001–0013 編號），把 00 §7 的九項閘門定稿。若任一項在實作中發現不可行，先改 ADR 再改碼。

**ADR 0014（path-security & filesystem relay 模型）**：
- TOCTOU 策略：優先「resolve 後在**同一 fd**上 `fstat`+bounded read」，避免 path→再開啟的 race；目錄以 `openat`/`O_NOFOLLOW` 語意逐段開啟或以 `os.OpenInRoot`（Go 1.24+ `os.Root`，確認 toolchain 1.26.5 可用）約束在 root 內。決定 `Guard` 對外介面：新增 `OpenFileInRoot`/`OpenDirInRoot`（回傳已驗證 handle）與保留 `Resolve`（僅供顯示/授權比對）。
- Error taxonomy：`WORKSPACE_*`（路徑/容器層）vs `FILE_*`（檔案讀取層）切分；對前端是否把 `WORKSPACE_OUTSIDE_ALLOWED_ROOT` 與 `WORKSPACE_NOT_FOUND` 合併為單一「無法存取」safe message 以免洩漏存在性（建議合併對外訊息、保留內部細分供 metric）。
- Central relay-only 與輸入型別：Central 接受 workspace-relative path（相對某 enabled root）；search 接受 keyword（檔名子字串）＋可選簡單 glob，皆由 daemon 解讀，**永不接受 absolute path / command / rg 參數**。

**ADR 0015（filesystem limits & preview policy）**：
- limits：`max_preview_size`(2 MiB)、search `max_depth`(10)/`max_results`(200)/`max_scanned`/`timeout_seconds`(10)、目錄 entry 上限與分頁 cursor、relay request timeout（list/read/search）——皆可設定、量測定稿。
- sensitive/binary（**已確認：平衡**）：`denied_patterns` 四類（exact/extension/glob/directory），以 exact name + 副檔名為主、glob 限縮（保留 `.env.*`，**移除** `*secret*`/`*credentials*` 避免誤擋程式碼），admin 可補環境特有敏感檔；不確定型別預設拒絕預覽。記錄誤擋/漏擋取捨。
- ignore-rule 顯示：excluded_directories「顯示但預設不載入」並標記「已排除」；hidden entry 預設顯示與否。
- Monaco：切檔 dispose vs bounded model cache 上限；worker 自帶打包；allowed→denied 清空。
- RBAC 粒度（**已確認**）：list/search/preview 共用單一 `file.browse`（不細分）；Admin/Developer/**Viewer** 三角色皆綁定 `file.browse`（Viewer 唯讀）。
- sensitive-denied audit（**已確認**）：僅記分類 + 副檔名，不記 `rel_path`/檔名主體/絕對路徑。

驗收：兩份 ADR 合併入 `docs/adr/`，00 §7 每一項皆有結論；`research/01/06-requirement-traceability.md` §5 對應列（Workspace favorites 等）標註 P3 決策。

## P3-02：Protocol v1.3 凍結

在 `contracts/v1/` 新增 filesystem 訊息（沿用 tech §12.2 命名），並同步 Python/Go/TS 三語言 codec。所有訊息延用既有 envelope（`version`、`type`、`request_id`、方向、payload；naive time/unknown field/bad enum 一律拒絕）。

**新增 request/response 型別**：

```text
filesystem.list          → filesystem.entries        目錄列表（lazy，單層）
filesystem.read          → filesystem.content         單檔唯讀讀取（或 denial）
filesystem.search        → filesystem.search_result   檔名搜尋（bounded、可 partial）
（選）filesystem.stat     → filesystem.stat_result     單一 entry metadata
（選）workspace.roots     → workspace.roots_result     root 清單（預設沿用 Central metadata，見 00 §7.9）
```

**payload 契約（重點欄位，完整以 schema 為準）**：

- `filesystem.list.payload`：`session_id`(UUID)、`path`(workspace-relative)、`cursor`(選，分頁)、`entry_limit`(選，上限受 server clamp)。**拒絕 absolute path、`..` 片段、null byte、unknown field。**
- `filesystem.entries.payload`：`path`、`root_display_name`、`entries[]{name, rel_path, type(directory|file|symlink), size, modified_at(RFC3339 UTC), hidden, symlink, excluded, expandable}`、`truncated`、`next_cursor`。**不回傳 server absolute path。**
- `filesystem.read.payload`：`session_id`、`path`(workspace-relative)。
- `filesystem.content.payload`：成功 → `rel_path, size, modified_at, encoding, language_hint, content`（bounded 文字）；denial → `success:false` + `error{code(FILE_TOO_LARGE|FILE_BINARY|FILE_DENIED|FILE_PERMISSION_DENIED|FILE_NOT_FOUND), reason}` + `metadata{size, modified_at, mime}`（binary/oversize 才帶 metadata，敏感檔僅回分類，不帶內容或完整路徑）。
- `filesystem.search.payload`：`session_id`、`root`(選)、`keyword`、`max_results`(選，clamp)。**不接受 glob 以外的 pattern、不接受 rg 參數。**
- `filesystem.search_result.payload`：`results[]{name, rel_path, type, modified_at}`、`partial`、`stopped_reason(depth|results|scanned|timeout|null)`、`scanned_count`。

**新增 error code**（tech §12.3）：`FILE_NOT_FOUND`、`FILE_TOO_LARGE`、`FILE_BINARY`、`FILE_DENIED`、`FILE_PERMISSION_DENIED`；沿用 `WORKSPACE_INVALID/NOT_FOUND/NOT_DIRECTORY/OUTSIDE_ALLOWED_ROOT/PERMISSION_DENIED`、`REQUEST_TIMEOUT`、`NODE_OFFLINE/BUSY`、`INVALID_MESSAGE`、`PROTOCOL_VERSION_UNSUPPORTED`。

**fixtures + manifest**（新增至 `contracts/v1/fixtures/`，登錄 `manifest.json`）：
- valid：`filesystem-list.json`、`filesystem-entries.json`、`filesystem-read.json`、`filesystem-content-text.json`、`filesystem-content-denied.json`、`filesystem-search.json`、`filesystem-search-result-partial.json`。
- invalid（accept:false、code `INVALID_MESSAGE`）：`filesystem-list-absolute-path.json`（絕對路徑）、`filesystem-list-parent-escape.json`（含 `..`）、`filesystem-read-null-byte.json`、`filesystem-search-forbidden-arg.json`（帶 rg-style 參數/多餘欄位）、`filesystem-content-naive-time.json`、`filesystem-entries-extra-field.json`。

驗收：Python/Go/TS 對 v1.3 `manifest.json` 一致 accept/reject；absolute path/`..`/null byte/rg 參數/naive time/unknown field 全被拒；round trip 一致。**契約 PR 先於任何 consumer 合併。**

## P3-03：Path Security Library（硬性安全 Gate，對應 P3-W1）

在 `daemon/internal/workspace`（或抽出 `internal/pathsec`，依 ADR 0014）建立 list/read/search **共用**的單一 guard，成為唯一容器判斷處。

**要求**：
- **每次操作重新驗證**：list/read/search 各自呼叫 guard，不快取上次結果、不信任 client 傳來的 breadcrumb 或前次 listing 的 path。前端傳 workspace-relative path，guard 以「該 session 的 workspace（本身已在 enabled root 下）」為基準 join 後再走完整九步驗證。
- **TOCTOU**：新增回傳已開啟 handle 的介面（ADR 0014）：`OpenDirInRoot`（列目錄）、`OpenFileInRoot`（讀檔）。解析與開啟之間不留 path→再開啟的窗口；讀檔在同一 fd 上 `fstat`（確認 regular file、size）再 bounded read；目錄以 root-confined 開啟避免 symlink swap 逃逸。root、target 與 parent symlink 的殘留風險在 ADR 記錄並採最安全可行策略。
- **error 明確**：invalid（空/null byte/含 `..` 的相對輸入被正規化後仍越界）、outside-root、not-found、not-directory、permission-denied 各有 code；對外可依 ADR 0014 合併訊息，內部保留細分供 metric。
- **不外洩**：guard 或其呼叫端回給 Central 的錯誤不得帶 server absolute path；canonical path 僅供 daemon 內部與 audit 分類，不回前端。

**測試（`go test -race ./...` + `go test -fuzz`）**：
- 既有：traversal（`../`、多層 `../../`）、absolute escape、prefix collision（`/a/projects` vs `/a/projects-other`）、null byte。
- 新增：symlink chain（root 內 symlink 指向 root 外）、broken/dangling link、symlink **swap race**（resolve 後、open 前替換成指向 root 外的 link，證明 handle 路徑不被騙）、file **replacement race**（stat 後、read 前換成 oversize/敏感檔，證明以 fd 讀且 size 由 fd 決定）、`..` 在 workspace-relative 輸入內、`.`/多重分隔、trailing slash、非 regular file（fifo/socket/device）拒絕。
- **fuzz/property**：以隨機路徑片段（含 `.`/`..`/symlink/null/unicode）property test「任何 `Resolve`/`OpenInRoot` 成功回傳的 canonical path 必定 `filepath.Rel(root, out)` 不以 `..` 開頭且不為 absolute escape」；`go test -fuzz=FuzzResolve` 在 CI 跑固定時間預算，corpus 納入上述惡意樣本。

驗收（research §P3-W1）：`../`、absolute escape、prefix collision、symlink chain、broken link、null byte、race fixture **全通過**；fuzz 無 counter-example；`-race` 無 leak。**此 gate 綠燈前不得進入 P3-06。**
