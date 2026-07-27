# 00 — P3 執行總控（Workspace 與 Files）

## 1. 成功定義與非目標

P3 要退休六個最高風險：**(a)** 路徑安全在 list/read/search 每一次操作是否都重新 canonicalize 並在 symlink 解析後仍位於 allowed root（含 TOCTOU：check 後被替換/symlink swap）、**(b)** 敏感檔案（`.env`/key/token/credentials）是否預設拒絕且不洩漏內容或內部路徑、**(c)** binary/oversize/不確定型別是否預設不可預覽且只回 metadata、**(d)** Central 是否只 relay/authorize 而**不代替 daemon 讀 Node filesystem**，且 relay 有 request/queue/timeout/cancel 上限與斷線清理、**(e)** filename search 是否有 depth/result/scanned/time 上限且可 cancel、不做內容搜尋、不接受任意 `rg` 參數、**(f)** Monaco model 生命週期是否單一 owner、切檔 dispose 或受控 cache、denial 不殘留前一檔內容。

P3 必須交付：

- **Path security library（daemon）**：以既有 `internal/workspace/Guard` 為基礎，抽出/擴充成 list/read/search 共用的單一 guard；每次操作重新驗證（absolute、clean、null-byte reject、`EvalSymlinks`、`filepath.Rel` containment），對 root、target 與 parent symlink 的 TOCTOU 風險記錄並採最安全可行策略（優先在**同一已解析的 fd/handle** 上操作，避免 path→再開啟的 race）。明確區分 `WORKSPACE_INVALID`/`WORKSPACE_OUTSIDE_ALLOWED_ROOT`/`WORKSPACE_NOT_FOUND`/`WORKSPACE_NOT_DIRECTORY`/`WORKSPACE_PERMISSION_DENIED` 與 `FILE_*` safe error code。
- **Directory list 與 filename search（daemon + Central relay）**：typed request/response，含 request_id、timeout、page/entry limit 與 deterministic ordering；ignore rule（excluded_directories 顯示但預設不載入）、hidden entry 行為與 root display name 明確；filename search 有 depth/result/scanned/time bounds、可 cancel、不做檔案內容搜尋。**Central 只 relay/authorize，不讀 Node filesystem**。
- **Read-only file policy（daemon）**：先 `stat` 再 bounded `io.LimitReader` 讀取（防 check 後變大）；binary detection（前 8 KB null byte + UTF-8 validation + 控制字元比例 + 副檔名/MIME）；sensitive filename/pattern deny（exact/extension/glob/directory 四類）；permission deny；**預設拒絕不確定型別**。response 含 language hint/encoding/mtime/size/denial reason，但不洩漏敏感內容或 server absolute path。
- **File audit / observability**：failed sensitive read 記 audit（只記分類與相對識別，不記內容或完整絕對路徑，SEC-006）；filesystem list/read/search 的 latency、bounds-hit、cancel、daemon disconnect metric；request/node/session/user ID correlation log。
- **File tree UI（frontend）**：lazy expand、loading child、empty folder、refresh、stale、partial、offline、forbidden、error 全狀態；keyboard tree semantics、focus/selection 分離、folder/file/hidden/excluded icon 可辨識；搜尋結果回到 tree context；Node/session 切換清空不相容 cache；不把 server absolute path 暴露到不必要 UI/log。
- **Monaco read-only preview（frontend）**：新增 `monaco-editor`（自帶 worker、無 CDN 外連）；readOnly、line numbers、search、word wrap、copy、goto line、refresh，與 terminal 共用深色工作區主題；每個 model 有 owner，切檔 dispose 或使用有上限的受控 cache；binary/oversize/sensitive/permission/not-found 各有具體不可預覽畫面與下一步；檔案從允許變成拒絕時清除既有內容。

P3 明確**不做**：檔案**編輯/寫入/建立/刪除**、**上傳/下載**、**Git 操作**、**全文（內容）搜尋**與任意 `ripgrep` 參數、任意 filesystem API、即時檔案系統監控（FR-FILE-006 僅提供手動 refresh 與 session 執行中可選自動刷新，不要求 watch 所有異動）、`workspace_favorites`/最近使用 workspace（FR-WORKSPACE-004/005，可延後至 P4）、RBAC 完整營運/Audit 檢視介面（P4）、Dashboard 真實聚合（P4）、圖片/PDF/壓縮檔/執行檔的內容預覽（第一階段僅回 metadata）。需要其中任一項時，先依 `research/01/06-requirement-traceability.md` §6 變更 canonical requirements。

## 2. 固定實作基線

| 項目 | P3 決定 |
|---|---|
| Layout | 沿用現況；daemon 新增 `internal/files`（list/read/search + policy），重用 `internal/workspace/Guard`，在 `internal/connection/dispatch` 接上 `filesystem.*` handler；backend 新增 `app/api/http/files.py`（HTTP relay）、`app/services/files.py`（relay/authorize、bounds、cancel）、audit 走既有 `app/services/audit.py`；frontend 新增 `views` 內 file 面板整合到 `SessionWorkspaceView.vue`、`components/file/*`（`FileTree`、`FileTreeNode`、`PreviewPane`、denial 畫面）、`stores/files.ts`、`composables/useFileTree.ts` 與 `composables/useMonacoModel.ts` |
| Runtime | 沿用 ADR 0001：Python 3.12.3、Go 1.26.5、Node 22.14.0；新增前端依賴 `monaco-editor`（pin 版本，自帶 worker，離線可 build） |
| 路徑驗證 | 沿用 tech §11.2 九步驟與既有 `Guard.Resolve`；**每次 list/read/search 重新驗證**；容器判斷禁用 `strings.HasPrefix`；對已解析路徑優先以開啟後的 fd/handle 操作（`openat`/`O_NOFOLLOW` 語意）降低 TOCTOU |
| 讀取輸入 | Central 僅接受 `session_id`（決定 node 與授權範圍）+ **workspace-relative path**（或 daemon 回報過的 entry path），**不接受任意 absolute path、command、glob 或 rg 參數**（SEC-002 延伸）；search 僅接受 `keyword`（檔名子字串/簡單 glob，由 daemon 解讀，不外傳 shell） |
| 檔案大小 | `filesystem.max_preview_size` 預設 2 MiB（沿用 `DefaultMaxPreviewSize`，FR-FILE-003）；超過回 `FILE_TOO_LARGE` + size，不讀內容 |
| Binary/敏感 | binary → `FILE_BINARY` + MIME/size/mtime（FR-FILE-004）；sensitive → `FILE_DENIED` + denial reason（FR-FILE-005/SEC-004）；**不確定型別預設拒絕預覽** |
| 搜尋上限 | `filesystem.search{max_depth:10, max_results:200, max_scanned, timeout_seconds:10}`（沿用 tech §11.8 建議值，皆可設定）；逾時/滿額回 partial + 明確旗標，可 cancel |
| Audit/儲存 | 只有 **failed sensitive read** 與（依 P4 policy）file 事件寫 audit metadata；**檔案內容、目錄清單、search 結果、terminal bytes 一律不入 DB/log**；audit 只記分類 + 相對識別，不記完整 server absolute path |
| RBAC | 沿用 `file.browse`（`FILE_BROWSE`）作為 list/search/preview 的單一 read-only 授權（**不細分 preview**）；**Admin/Developer/Viewer 三角色皆可 `file.browse`**（Viewer 唯讀，仍受敏感/binary/oversize 拒絕保護），以 versioned seed migration 綁定 |
| Browser 傳輸 | filesystem 走 **HTTP relay**（`/api/sessions/{id}/files/*`），非 terminal binary WS；沿用 auth guard、RBAC、typed DTO、safe error、request_id；大檔預覽以 bounded body 回傳，不 streaming 二進位 |
| Time | 內部 aware time；傳輸 RFC 3339 UTC `Z`；search/read/relay timeout 與 cancel 以 monotonic clock |

任何偏離上表的實作差異先記 ADR（0014/0015）再改，不以未量測預設值當永久產品限制。

## 3. 垂直架構與 ownership

```text
Browser (Vue Router + Pinia)
  ├─ HTTP: api/client → /api/sessions/{id}/files/tree|search|content
  │        auth guard、RBAC(file.browse)、typed DTO、safe error、request_id、cancel(AbortController)
  ├─ FileTree（useFileTree）：lazy expand、cache per (node,session)、狀態機、keyboard semantics
  └─ PreviewPane（useMonacoModel）：Monaco readOnly、model owner、bounded cache、denial 畫面

FastAPI Central
  api/http/files.py     filesystem HTTP boundary（authN+authZ(file.browse)+validation + session→node 解析）
  services/files.py     relay/authorize：以 session 找 node，前置 workspace-prefix 授權，經 registry.request()
                        向 daemon 發 filesystem.list/read/search 並 correlate；套 relay request/timeout/cancel 上限
  services/registry.py  NodeConnectionRegistry.request()（P2 已 production；P3 新一組 caller）
        └─ /ws/nodes/{node_id}（P1 Ed25519 daemon 連線）
             └─ Go daemon
                  connection/dispatch  新增 filesystem.list/read/search → internal/files（單一 read/write owner 已存在）
                  internal/files/      list/search/read + policy（binary/sensitive/size）
                  internal/workspace/  Guard.Resolve：每次操作重新 canonicalize（唯一容器判斷處）
                  internal/config/     workspace.excluded_directories、filesystem.denied_patterns、search bounds
```

資源 owner：每個 filesystem HTTP request 在 boundary 完成 authN/authZ(file.browse)/validation 與 session→node 解析後才進 service；service 以 `registry.request()`（帶 timeout、correlation、cancel、late-response cleanup）與 daemon 互動，**Central 不直接觸碰 Node filesystem**。daemon 一個 goroutine 擁有 socket read、一個擁有 write（沿用 P2）；每個 filesystem 請求在 handler 內以自帶 context/timeout 執行 list/read/search，search 具備可取消的 walk 與上限；**唯一容器判斷在 `Guard.Resolve`**，任何 handler 都不得自行拼路徑或用 `HasPrefix`。前端 `useFileTree` 擁有 tree cache 與展開狀態、`useMonacoModel` 擁有 model 與 bounded cache，兩者在切 node/session 或離頁時完整清理；每個 HTTP 請求以 `AbortController` 綁定可取消。

## 4. 執行順序與 ticket

| Wave | Ticket | 產出 | 前置 |
|---:|---|---|---|
| 0 | **P3-01** | 決策 ADR 0014（path-security & relay 模型：TOCTOU 策略、re-canonicalize 規則、error taxonomy、Central relay-only、search 輸入型別）與 ADR 0015（filesystem limits & preview policy：max_preview_size、search bounds、list page/entry limit、sensitive/binary policy、ignore-rule 顯示行為、Monaco model cache、RBAC 是否細分 preview） | 無 |
| 0 | **P3-02** | protocol v1.3 凍結：`filesystem.list/entries`、`filesystem.read/content`、`filesystem.search/search_result`、（選）`filesystem.stat/stat_result` 與 `workspace.roots/roots_result`；新 error code `FILE_NOT_FOUND/FILE_TOO_LARGE/FILE_BINARY/FILE_DENIED/FILE_PERMISSION_DENIED` 與既有 `WORKSPACE_*`；fixtures + `manifest.json` + Python/Go/TS 三語言 codec accept/reject | P3-01 |
| 1 | **P3-03（Gate）** | **P3-W1 path security library**：抽出/強化 `internal/workspace` 供 list/read/search 共用；每次操作重新 canonicalize；TOCTOU（fd/handle、`O_NOFOLLOW`）；fuzz/property test；`../`/absolute escape/prefix collision/symlink chain/broken link/null byte/race fixture 全拒 | P3-01 |
| 2 | P3-04 | **P3-W2（daemon）**：`filesystem.list` handler（deterministic ordering、hidden/excluded 標記、entry limit、per-request timeout）、`filesystem.search` handler（depth/result/scanned/time bounds、可 cancel、檔名 only）；不回傳未授權 absolute path 細節 | P3-02、P3-03 |
| 2 | P3-05 | **P3-W3（daemon）**：`filesystem.read` handler：stat→bounded LimitReader、binary detection、sensitive deny（exact/ext/glob/dir）、permission deny、預設拒絕不確定型別；response language/encoding/mtime/size/denial reason；failed sensitive read 觸發 audit 事件 | P3-02、P3-03 |
| 3 | P3-06 | **P3-W2/W3（Central）**：`app/services/files.py` + `app/api/http/files.py`（`/api/sessions/{id}/files/tree|search|content`）：RBAC(file.browse) boundary、session→node 解析與 workspace-prefix 前置授權、`registry.request()` relay（timeout/cancel/late-response cleanup）、relay request/queue 上限、safe error 映射、無 absolute-path 洩漏 | P3-04、P3-05 |
| 4 | P3-07 | **P3-W4**：File tree UI（`components/file/FileTree*`、`stores/files.ts`、`composables/useFileTree.ts`）：lazy expand、full state matrix、keyboard tree semantics、focus/selection 分離、icon 辨識、搜尋→tree context、node/session 切換 cache 失效 | P3-06 |
| 4 | P3-08 | **P3-W5**：Monaco read-only preview（新增 `monaco-editor`、`components/file/PreviewPane.vue`、`composables/useMonacoModel.ts`）：readOnly/行號/搜尋/word wrap/copy/goto line/refresh、model owner + bounded cache、binary/oversize/sensitive/permission/not-found denial 畫面、allowed→denied 清空、a11y | P3-06 |
| 5 | P3-09 | File audit 與 observability slice：failed sensitive read audit（無內容/無完整絕對路徑）、filesystem list/read/search metrics（latency、bounds-hit、cancel、daemon disconnect）、correlation log、redaction 掃描 | P3-05、P3-06 |
| 5 | P3-10 | **P3-W6 驗證**：contract/unit/daemon-race/fuzz/integration/E2E、性能量測（list <2s、≤2 MB preview <3s）、安全套件（traversal/symlink/sensitive/binary/oversize/replacement swap）、relay bounds/timeout/cancel/disconnect、操作證據包、exit review（`docs/p3-report.md`） | 全部 |

關鍵路徑為 `P3-01 → P3-02 → P3-03 → P3-04/P3-05 → P3-06 → P3-07/P3-08 → P3-10`。Wave 內可並行，但修改契約或 config schema 的 PR 必須先於 consumer 合併；**P3-03 未通過安全 gate 前，P3-06 不得對外開放端點**。

## 5. 每張 ticket 的完成格式

每張 ticket 至少附：變更檔案、契約/假設、成功與失敗測試（含 forbidden/traversal/symlink/sensitive/binary/oversize/timeout/cancel/disconnect/TOCTOU）、實際執行命令（`make contract/unit/integration/e2e`、`go test -race`、`go test -fuzz`）、log/metric/audit 影響（且證明無 secret/token/**file content**/**terminal content**/不必要 absolute path）、以及對應 requirement（`FR-FILE-001…007`、`FR-WORKSPACE-001/002`、`SEC-001/002/004/006`、`NFR-*`）。跨語言行為改變時，同一變更必須同步 schema、`manifest.json`、fixtures 與 Python/Go/TS 三個 consumer。config 行為改變時（新增 `excluded_directories`/`denied_patterns`/`search` bounds），需附 default 與 unknown-field/負值/越界拒絕測試。time/timeout/cancel 以 fake/monotonic clock 測；path 測試用 fixture workspace（含 symlink swap、broken link、prefix-collision 目錄），不依賴個人真實路徑。

## 6. P3 預設限制與參數（待量測，記入 ADR 0014/0015）

| 項目 | 初值 | 滿額/逾時行為 |
|---|---:|---|
| 檔案預覽上限 | 2 MiB（`DefaultMaxPreviewSize`，FR-FILE-003） | `FILE_TOO_LARGE` + size，不讀內容 |
| Binary sniff 視窗 | 前 8 KiB（tech §11.6） | null byte / 非 UTF-8 / 控制字元比例超標 → `FILE_BINARY` + MIME |
| 目錄單次 entry 上限 | 每次回傳上限（如 2000，可設定）+ 分頁 cursor | 超過分頁；`truncated` 標記，前端提示 |
| Search max_depth | 10（tech §11.8） | 超過深度不再遞迴 |
| Search max_results | 200 | 達上限即停並標記 partial |
| Search max_scanned | 掃描檔案數上限（如 50000，可設定） | 達上限即停並標記 partial |
| Search timeout | 10s（monotonic） | 逾時回已收集結果 + `partial=true`，可 cancel |
| 排除目錄 | `.git/objects`、`node_modules`、`.venv`、`dist`、`build`、`__pycache__`（tech §11.4） | 顯示但預設不載入（顯示「已排除」） |
| Filesystem relay request timeout | list 15s、read 15s、search 12s（可設定） | `REQUEST_TIMEOUT`，清 correlation entry |
| Per-node pending requests | 128（沿用 P1 `pending_requests_max`，與 session 共用） | 超過回 `NODE_BUSY` |
| 目錄列表延遲 | < 2 秒（代表性量測，NFR） | 未達標列 release decision |
| ≤2 MB 檔案預覽延遲 | < 3 秒（代表性量測，NFR） | 未達標列 release decision |

限制與參數皆以可設定 bounded 值實作，量測後在 ADR 接受或修訂，不硬編碼為永久產品限制。

## 7. 決策閘門（P3-01 前必須記錄）

> **已確認（2026-07-25，計畫階段拍板，P3-01 直接寫入 ADR，不再重議）**：
> - 敏感檔規則採**「平衡」**：exact name + 副檔名為主，glob 限縮（保留 `.env.*`，**移除** `*secret*`/`*credentials*`），admin 可補；不確定型別預設拒絕。
> - sensitive-denied audit **僅記分類 + 副檔名**（不記 `rel_path`/檔名主體/絕對路徑）。
> - **Viewer 角色具 `file.browse`**（唯讀瀏覽 + 預覽，仍受敏感/binary/oversize 拒絕保護），與 P2「Viewer 唯讀 attach」一致；不細分 preview 權（list/search/preview 共用 `file.browse`）。
> - TOCTOU 建議 `os.Root` handle（Go 1.24+，toolchain 1.26.5 支援）、`workspace.roots` 沿用 Central metadata、對外 error 合併 not-found/outside-root——為建議預設，P3-01 追認。

1. **TOCTOU 策略**：check→open 的 race（檔案在 stat 後被替換、symlink swap）採哪種最安全可行做法（優先在已解析 fd 上 fstat+read；或 `O_NOFOLLOW`/`openat` 逐段）；`Guard` 是否回傳已開啟的 handle 而非只回 path。
2. **Error taxonomy**：`WORKSPACE_*`（路徑/容器層）與 `FILE_*`（檔案讀取層）如何切分；哪些對外合併成同一 safe code 以免洩漏存在性（例如 outside-root 與 not-found 是否對前端統一為「無法存取」）。
3. **Central relay-only 與輸入型別**：Central 接受 workspace-relative path 還是只接受 daemon 回報過的 entry path token；search 輸入是 keyword、簡單 glob 還是兩者；一律不接受 absolute path 與 rg 參數。
4. **Sensitive/binary policy（已確認：平衡）**：`denied_patterns` 四類（exact/extension/glob/directory）以 exact name + 副檔名為主，glob 限縮（保留 `.env.*`，移除 `*secret*`/`*credentials*` 以免誤擋程式碼），admin 可於 config 補環境特有敏感檔；不確定型別預設拒絕。
5. **Limits**：max_preview_size、search bounds、目錄 entry 上限與分頁、relay request timeout，皆可設定並量測定稿。
6. **Ignore-rule 顯示行為**：excluded_directories 採「顯示但不載入」（tech §11.4 建議）並標記「已排除」；hidden entry 是否預設顯示。
7. **Monaco model 生命週期**：切檔 dispose vs 受控 bounded cache 上限；worker 打包方式（自帶、無 CDN）；allowed→denied 清空策略。
8. **RBAC 粒度（已確認）**：list/search/preview **共用 `file.browse`**（不細分 preview 權）；**三角色 Admin/Developer/Viewer 皆具 `file.browse`**（Viewer 唯讀瀏覽 + 預覽，仍受敏感/binary/oversize 拒絕保護），對齊 P2「Viewer 唯讀 attach」。
9. **workspace.roots 來源**：前端 tree 的根節點用 Central 既有 `NodeWorkspaceRoot` metadata，還是新增 `workspace.roots` daemon 查詢（建議沿用 Central metadata，daemon 仍為最終判斷）。

## 8. 明確非目標與變更控制

P3 不加入檔案編輯/寫入/上傳/下載、Git 操作、全文（內容）搜尋或任意 `ripgrep` 參數、任意 filesystem API、即時檔案監控、圖片/PDF/壓縮檔/執行檔內容預覽、`workspace_favorites`/最近使用 workspace、RBAC 完整營運與 Audit 檢視 UI（P4）、Dashboard 真實聚合（P4）、macOS daemon、任意 shell、Central SSH、多 agent orchestration 或水平擴充。需要其中任一項時，先依 `research/01/06-requirement-traceability.md` §6 變更 canonical requirements（PRD 目標/非目標與 requirement ID → tech trust boundary/protocol/data/failure/security/observability/test → style UI/state contract → 追蹤矩陣與階段出口），不能只在 implementation ticket 中暗自擴張。
