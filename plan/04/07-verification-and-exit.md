# 07 — 驗證、證據與 P3 Exit Gate（P3-W6）

對應 ticket **P3-10** 與 `research/01/04-phase-3-workspace-files.md` §P3-W6。延續 P0/P1/P2 的驗證紀律（`plan/01/07`、`plan/02/08`、`plan/03/08`），聚焦路徑安全、敏感內容防護、relay bounds/cancel、Monaco lifecycle 與檔案操作延遲。

## 1. 測試分層

| 層級 | 必跑內容 | 主要 owner |
|---|---|---|
| Contract | protocol v1.3 新型別 schema、三語言 fixtures、round trip；forbidden（absolute path/`..`/null byte/rg 參數）、naive-time、bad-enum、unknown-field 拒絕；denial content 型別 round trip | protocol |
| Unit（daemon） | **path security（P3-03 Gate）**：`../`/absolute escape/prefix collision/symlink chain/broken link/null byte/非 regular file 全拒；list ordering/entry limit/excluded/hidden；search bounds（depth/results/scanned/timeout）與 cancel 無 goroutine leak；read policy（sensitive 四類/binary/oversize/permission/不確定型別預設拒）；回覆無 absolute path；`-race` | daemon |
| Fuzz/Property | `go test -fuzz=FuzzResolve`（固定預算）：任何成功 resolve/open 的 canonical path 必在 root 內；corpus 含惡意樣本無 counter-example | daemon |
| Unit（backend） | files relay：session→node 解析、前置授權（absolute/`..`/null 於 boundary 422）、`registry.request` correlation/timeout/cancel/斷線 cleanup 無 pending leak、`NODE_BUSY`、safe error 映射、DTO 無 absolute path、file.browse RBAC allow/deny、sensitive-denied audit（無內容）、redaction | Central |
| Unit（frontend） | `useFileTree`（lazy/cache/refresh/狀態機/搜尋回 tree/切 session clear+abort/keyboard）、`useMonacoModel`（cache LRU dispose、**leak gate**、allowed→denied 清空、denial 畫面） | frontend |
| Integration | Central→fake daemon→fixture workspace：tree lazy load、大目錄分頁、search partial/cancel、read 成功/各 denial、TOCTOU（read 前 replace/symlink swap 不繞過）、daemon disconnect 中途 relay cleanup | Central+daemon |
| Browser（E2E） | login→session workspace→展開/lazy load→大目錄 partial→搜尋回 tree→預覽程式碼（高亮/行號/search/wrap/copy/goto/refresh）→敏感/binary/oversize/permission denial→切 session 清空→node offline/forbidden→keyboard-only + screen reader | frontend |
| Performance | 目錄列表 < 2 秒、≤2 MB 檔案預覽 < 3 秒的代表性量測（含環境）；大目錄/深樹 search 上限行為 | cross-stack |
| Security | traversal/symlink/sensitive/binary/oversize/replacement-swap 拒絕矩陣；Central 不接受 absolute/command/rg 參數；relay bounds/timeout/cancel/disconnect；log/audit/DB 無 file/terminal content、無 keyword 明文、無不必要 absolute path | cross-stack |

測試不得依賴外部網路或個人真實路徑；path/read/search 測試用**受控 fixture workspace**（含 symlink swap、broken link、prefix-collision 目錄、敏感/binary/oversize 樣本）；time/timeout/cancel 用 fake/monotonic clock；PostgreSQL 以 CI service container 或 ephemeral schema 提供並清理。

## 2. 必要 CI gates

延續 `.github/workflows`（P1/P2 的 `backend`/`daemon`/`contract`/`security`/`e2e`），P3 新增/擴充（建議 `p3.yml`）：

- `contract`：Python/Go/TS 對 v1.3 `manifest.json` 一致 accept/reject（含新 filesystem fixtures）。
- `daemon`：`go vet`、`go test -race ./...`、`-tags integration -race ./internal/files ./internal/workspace`、**`go test -fuzz=FuzzResolve -fuzztime=…`**、build amd64/arm64。
- `backend`：files relay/audit unit；DB job（若新增 audit action seed）跑 migration upgrade/downgrade + rollback。
- `frontend`：lint/typecheck/build（含 monaco worker 打包驗證，離線 build 可過）、vitest（含 Monaco leak gate、useFileTree）。
- `e2e`：Playwright Chromium/Firefox/WebKit，涵蓋 tree→search→preview→denial→切 session（full-stack 以 env flag 開，沿用 `nodes.spec.ts` gating）。
- `security`：path-escape/sensitive/binary/oversize/replacement-swap、Central 拒 absolute/command/rg、relay bounds、redaction 掃描。
- `performance`（merge/RC）：list/preview latency artifact。

每個 PR 跑 format/lint、typecheck、unit、contract、build 與（若涉 DB）migration；合併主分支與 RC 另跑 fuzz、integration、E2E matrix、security 與 performance。CI log 不列印 secret/token/**file content**/**terminal content**/keyword 明文。

## 3. 操作證據包

於 `artifacts/p3/<run-id>/`（CI artifact）保存：

- `versions.txt`、`commands.txt`（root task 與 exit status）。
- `contract.xml`、`unit-daemon.xml`、`unit-backend.xml`、`unit-frontend.xml`、`integration.xml`、`e2e.xml`、`race.txt`、`fuzz.txt`（corpus/counter-example 狀態）。
- `pathsec-gate.txt`：P3-03 traversal/symlink/prefix/broken-link/null-byte/TOCTOU 結果與 fuzz 摘要。
- `latency.json`：目錄列表與 ≤2 MB 預覽延遲分佈（含環境）與是否達 < 2s / < 3s。
- `denial-matrix.md`：sensitive（四類）/binary/oversize/permission/not-found/不確定型別 的實際回覆與畫面。
- `relay-bounds.md`：list/search entry/results 上限、search stopped_reason、cancel、daemon disconnect cleanup、`NODE_BUSY`。
- `security-report.md`：path escape、Central 拒 absolute/command/rg、replacement swap、redaction 掃描。
- `screenshots/`：tree（loading/empty/partial/offline/forbidden/error）、search→tree、preview（程式碼）、各 denial 畫面、切 session 清空、keyboard focus。

發布前以掃描確認 log/artifact/DB 不含 file content、terminal content、keyword 明文、token、不必要 absolute path。

## 4. Exit Gate checklist

### 功能

- [ ] 使用者可於 Session Workspace 從 allowed root 展開檔案樹（lazy、excluded/hidden 明示）、以檔名搜尋並跳回 tree context。
- [ ] 可以 Monaco 唯讀預覽合法程式碼（高亮、行號、search、word wrap、copy、goto line、refresh）。
- [ ] `.env`/key/token 敏感檔、binary、oversize、permission、不確定型別 各有具體不可預覽畫面與下一步，且無內容外洩。
- [ ] 切換 Node/session 清空不相容 cache；檔案由允許變拒絕時畫面內容被清；Monaco 無 model/worker leak。

### 安全（發布前提，任一未過即 No-Go）

- [ ] **P3-03 path-security gate 全綠**：`../`、absolute escape、prefix collision、symlink chain、broken link、null byte、非 regular file、**TOCTOU replacement/symlink swap** 全被拒；fuzz 無 counter-example。
- [ ] 每次 list/read/search 都重新 canonicalize，不信任 client breadcrumb 或前次 listing。
- [ ] Central 只 relay/authorize，**不代替 daemon 讀 Node filesystem**；不接受 absolute path/command/rg 參數（boundary 即拒）。
- [ ] 敏感檔預設拒絕預覽（四類）；binary/oversize/不確定型別不回內容；denial 不洩漏內容或 server absolute path。
- [ ] failed sensitive read 記 audit（僅分類 + 相對識別，無內容）；log/audit/DB 掃描無 file/terminal content、無 keyword 明文、無不必要 absolute path。

### 效能與工程基線

- [ ] 目錄列表 < 2s、≤2 MB 預覽 < 3s 有量測結果；未達標項有明確 release decision。
- [ ] search bounds（depth/results/scanned/timeout）與 cancel 有界且可證明；daemon disconnect 中途 relay 清理無 pending/goroutine leak（`-race`）。
- [ ] 乾淨 checkout 依 README 可 bootstrap、migrate、build（含 monaco 離線打包）、test、run（含 tree→preview 垂直）。
- [ ] CI gates 綠燈且 artifact 可追溯到 commit；`research/01/06-requirement-traceability.md` §7 之後新增一節，以實際證據更新 FR-FILE-001…007、SEC-001/002/004/006、相關 NFR。

任一項未過即維持 P3 open；不可因 demo 可瀏覽/預覽即豁免 path-security gate、敏感內容防護、Central relay-only、redaction 或 leak gate。

## 5. ADR / 決策清單

| ADR | P3 必答問題 | 截止 |
|---|---|---|
| 0014 path-security & filesystem relay | TOCTOU 策略（fd/handle、`os.Root`/`O_NOFOLLOW`）、error taxonomy 與對外訊息合併、Central relay-only 與輸入型別、search 輸入型別、audit 相對識別粒度 | P3-01（P3-03/04/05 前） |
| 0015 filesystem limits & preview policy | max_preview_size、search bounds、目錄 entry 上限/分頁、relay request timeout、sensitive/binary policy 與過寬緩解、ignore-rule 顯示、Monaco model cache 上限與 worker 打包、RBAC 是否細分 preview | P3-01（P3-05/07/08 前） |

若 TOCTOU 兩方案（`os.Root` handle vs `O_NOFOLLOW` 逐段）皆不可行或成本過高，須回報替代設計（例如 daemon 端一律以 chroot-like 隔離的讀取子程序）與重新估算，而非放寬容器判斷。

## 6. 已知風險與相依

- **path security 為硬性 Gate**：P3-03 未全綠前，P3-06（Central 端點）不得對外開放；此為 P3 的最高風險，對齊 research §階段出口「所有路徑逃逸與敏感內容測試必須通過，否則不可發布」。
- **TOCTOU 是真實破口**：既有 `Guard.Resolve` 只回 path 字串，resolve→open 之間可被替換；P3-03 必須改為回傳已驗證 handle 並在同一 fd 上操作，否則安全測試可過但真實 race 仍可逃逸。
- **`*secret*`/`*credentials*` glob 過寬**（已定案）：採「平衡」策略移除這兩個寬鬆 glob、以 exact/extension 為主，admin 可補；風險轉為「可能漏擋少數怪命名敏感檔」，安全測試須含誤擋反例（`secret_handler.py` 可預覽）與 admin 補規則後可擋的案例。ADR 0015 記錄取捨。
- **Monaco bundle 與 worker**：離線打包、worker 自帶、bundle 體積與只註冊必要語言；leak gate 是防 model/worker 累積的關鍵。
- **relay 新 caller**：filesystem 是 `registry.request()` 繼 session 之後的 caller，需在真實 cancel（前端 abort）與 daemon disconnect 下驗證無 pending future/goroutine leak。
- **本規劃補上、需回填 canonical docs 的決策**：TOCTOU handle 介面、error taxonomy 對外合併、audit 相對識別粒度、denied_patterns 限縮——皆於 ADR 0014/0015 記錄並視情況回填 `research/prd.md`/`tech.md`。

## 7. Go / No-Go review

Exit review 輸出一頁 `docs/p3-report.md`：結果、未通過項、實測參數（list/preview 延遲、search 上限行為、relay cancel/disconnect 恢復、Monaco cache 上限）、已知 gap、採納 ADR、P4 follow-ups（`workspace_favorites`/最近使用 workspace FR-WORKSPACE-004/005；file access history；全文搜尋 ripgrep 整合；RBAC 完整營運/Audit 檢視 UI；Dashboard 真實聚合）。只有上述 checklist 全過、且無未處理的高風險：path escape、TOCTOU 繞過、敏感內容外洩、Central 讀取 Node FS、relay leak 或 Monaco leak，才可標記 Go。若不可行，報告須列替代方案、需修改的架構、重新估算與下一個 time-boxed spike，而非硬進 Phase 4。
