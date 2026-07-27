# 08 — P3 實作進度與證據

> 本文件隨實作更新。**目前狀態：P3-01…P3-10 全部完成，本機全綠（含 full-stack browser E2E 與兩段延遲量測）。唯一未完成項：`.github/workflows/p3.yml` 尚未在真實 GitHub runner 執行**（本工作目錄不是 git repo）。完整判定見 `docs/p3-report.md`。

## Ticket 狀態

| Ticket | 主題 | Wave | 狀態 | 證據 / 續作點 |
|---|---|---|---|---|
| P3-01 | 決策 ADR 0014/0015 | 0 | ✅ 已完成 | `docs/adr/0014-…`、`0015-…`（0015 追加 frame-bound amendment）；00 §7 九項閘門定稿 |
| P3-02 | protocol v1.3 凍結（filesystem.*） | 0 | ✅ 已完成 | 6 型別 + 3 request schema + error code；fixtures + manifest；三語言 codec。**追加 1.3.1**：filesystem 回應 frame 上限拆分（見下方缺口 1） |
| P3-03 | path security library（**Gate**） | 1 | ✅ 已完成 | `internal/workspace/root.go`（`os.Root` handle、`RealRel`）。`go test -race ./internal/workspace` 全綠（含 symlink-swap/bounded-read TOCTOU）；`FuzzOpenFile` 7.2M execs、0 containment 違規 |
| P3-04 | daemon list/search handler | 2 | ✅ 已完成 | `internal/files/{service,list,search,policy}.go` + `connection/files_handlers.go`。unit + **真實連線 integration**（`files_integration_test.go`） |
| P3-05 | daemon read policy | 2 | ✅ 已完成 | `internal/files/read.go`（sensitive→confined open→fstat→size→bounded read→binary，`RealRel` 複查）。`TestReadPolicyMatrix` + integration 六案（dotenv/symlink→dotenv/binary/oversize/traversal/missing） |
| P3-06 | Central files relay + HTTP API | 3 | ✅ 已完成 | `app/services/files.py`、`app/api/http/files.py`、`0007_seed_file_browse`。`tests/db/test_files_api.py` 12 pass |
| P3-07 | File tree UI | 4 | ✅ 已完成 | `stores/files.ts`、`composables/useFileTree.ts`、`components/file/{FileTree,FileTreeNode,FileSearchBar,FileTreeToolbar}.vue`、`api/client` + `dto.ts`（AbortSignal）。`useFileTree.test.ts` 17 + `FileTree.test.ts` 5 |
| P3-08 | Monaco read-only preview | 4 | ✅ 已完成 | `monaco-editor@0.56.0`（pin、curated、自帶 worker）、`monaco/setup.ts`、`composables/useMonacoModel.ts`、`components/file/{PreviewPane,PreviewDenied}.vue`。`useMonacoModel.test.ts` 16（含 leak gate）+ `PreviewDenied.test.ts` 8 |
| P3-09 | file audit 與 observability | 5 | ✅ 已完成 | audit（classification + 副檔名）；`app/metrics.py` + `daemon/internal/metrics`；correlation log（keyword 只留 digest）。DB 測試以 `JsonFormatter` 實際輸出斷言無 path/content/keyword |
| P3-10 | 驗證與 exit（`docs/p3-report.md`） | 5 | ◐ 本機全綠 | `p3.yml`（8 jobs，含 `evidence`）、`tests/e2e/files.spec.ts`（Chromium 12/12、Firefox 12/12）、`bench_test.go` + `perf/files_bench.py`、`scripts/p3/evidence.sh` 產出完整證據包、`docs/p3-report.md`、traceability §9。**僅剩真實 runner 執行（含 WebKit）** |

狀態圖例：⬜ 未開始／🟡 進行中／◐ 本機完成待外部驗證／✅ 已驗證（附證據）／⛔ 受阻。

## Exit gate 找出的兩個真實缺口（皆已修 + 回歸測試）

單元測試全綠卻仍存在，只有把真實元件接起來才會出現——這是 P3-10 這道關卡的價值所在。

1. **2 MiB 預覽根本送不到瀏覽器**（`perf/files_bench.py` 發現）。控制 frame 上限兩端都是 64 KiB，但 ADR 0015 規定的 2 MiB 預覽超出 32×、2000 筆列表超出約 5×。Central `decode_control` 丟 `FRAME_TOO_LARGE`，node WS loop `continue`，parked Future 永不 resolve → 使用者等 15 秒拿到 `REQUEST_TIMEOUT`。既有測試測不到：daemon 測試直接呼叫 file service、Central 測試 fake registry，沒有任何路徑跨過真實 codec。修法：三個 filesystem **回應**型別改用獨立 8 MiB 上限（`MAX_FILE_PAYLOAD` / `MaxFilePayload`），其餘控制型別維持 64 KiB；daemon 另外拒絕「建構」超限 frame（`ErrFrameTooLarge` → `FRAME_TOO_LARGE` 回覆），讓失敗是明確錯誤而非 hang。記於 `contracts/CHANGELOG.md` 1.3.1 與 ADR 0015 amendment，兩語言各有測試。
2. **新註冊的節點完全沒有敏感檔政策**（full-stack Playwright 發現：`.env` 直接顯示內容、`node_modules` 可展開）。`internal/install/plan.go` 產生 config 時未寫出政策清單，`yaml.Marshal` 把 nil slice 寫成 `[]`，載入端只檢查 `== nil` 因而跳過預設 → 每個新節點「不擋任何敏感檔、不排除任何目錄」，是部署路徑上的 SEC-004 / FR-FILE-005 實際破口。修法：installer 顯式寫出預設（也給 operator 可見的擴充點）；兩個**安全**清單改為「空即套預設」，default-deny 不可因省略而失效；`excluded_directories` 維持 nil-only（它是 ignore rule，明寫 `[]` 應被尊重）。回歸測試：`internal/config`（空→預設、明列覆寫、明寫空的 excluded 被尊重）、`internal/install`（產生的 config 帶政策且 marshal→Load 往返不掉）。

## 已驗證證據（累積）

- **三語言 gates**：`ruff format --check` + `ruff check` + `mypy`（61 檔）clean；`gofmt` + `go vet` clean；prettier + eslint + `vue-tsc` clean。
- **daemon**：`go test -race ./...` 全綠；`-tags integration -race ./internal/{session,connection,files,workspace}` 全綠（tmux 3.4）；`FuzzOpenFile` 7.2M execs 無違規。
- **backend**：`pytest` **193 pass**（hermetic + PostgreSQL 16）；contract **58**；migration up/down/up 含 `0007`。
- **frontend**：**136 unit tests**；production build 離線通過，`editor.worker` 為本地 asset、`dist` 無 CDN 參照；Monaco 以 async component 切出（workspace chunk 332 kB，編輯器 2.96 MB 首次預覽才載入）。
- **full-stack E2E**：`files.spec.ts` 5/5；全套（auth + nodes + session + files）**Chromium 12/12、Firefox 12/12** 對真實 Central + rootless 註冊的 daemon node 綠燈；WebKit 待 CI。
- **證據包**：`artifacts/p3/local/`（見下方續作紀錄）；`.env` denial 截圖經目視確認畫面上無任何 secret 片段。
- **延遲量測**（`artifacts/p3/local/`）：目錄列表 ~12 ms、2 MiB 預覽 ~9 ms、搜尋 ~7 ms（daemon + Central 兩段 p95 相加），目標 2 s / 3 s。relay bounds：timeout / cancel / `NODE_BUSY`(128) / disconnect 皆無 pending 殘留。

## 續作紀錄

- 2026-07-25（前段）：Wave 0–3 完成 — ADR、protocol v1.3、path security gate、daemon `internal/files`、Central relay + RBAC seed、sensitive-read audit。
- 2026-07-25（本次）：Wave 4–5 完成 —
  - **P3-07**：`api/client` 加 `AbortSignal` 支援與三個 filesystem 端點；`stores/files.ts`（per-session cache、in-flight abort、late-response 丟棄）；`useFileTree`（狀態機、lazy、分頁、搜尋 reveal、keyboard）；四個 `components/file/*`；掛入 `SessionWorkspaceView.vue`（原 line 174 佔位）。
  - **P3-08**：`monaco-editor` 0.56.0（新版 `features/*/register` 粒度 API，只註冊唯讀所需 contributions 與 daemon 會回報的語言）；JSON 無獨立 tokenizer 且其 language service 要 930 kB，故 `json→javascript` alias（記於 `monaco/setup.ts`）；`useMonacoModel`（LRU 8、dispose、allowed→denied 清空）。
  - **a11y 修正**：tree 由 roving tabindex 改為 **`aria-activedescendant`**（容器持有唯一 tab stop）——原設計在展開造成 re-render 時可能掉失 DOM focus，導致下一次按鍵被吞掉（由 E2E 逼出）。
  - **P3-09**：`app/metrics.py`、`daemon/internal/metrics`、`_observe()` correlation log + redaction、audit 失敗不阻斷請求。
  - **P3-10**：daemon filesystem integration、兩段延遲量測、`files.spec.ts`、`p3.yml`、`docs/p3-report.md`、traceability §9；`scripts/e2e/run-stack.sh` 新增 P3 workspace fixtures。
- 2026-07-25（補完盤點後）：關掉兩個可在本機關掉的缺口 —
  - **跨瀏覽器 E2E**：Firefox 全套 12/12 通過（與 Chromium 相同）。**WebKit 在本沙箱無法啟動**（缺 `libgstreamer-plugins-bad`/`libwoff1` 等系統套件，需 root；同 [[installer-sandbox-limits]]），由 `p3.yml` 的 `browser-e2e`（`--with-deps webkit`）覆蓋。
  - **操作證據包（plan/04/07 §3）**：新增 `scripts/p3/evidence.sh`，產出 `versions.txt`、`commands.txt`（18 道 gate 全 exit=0）、三語言 contract、`unit-{backend,frontend}.xml`、`race.txt`、`integration.txt`、`pathsec-gate.txt`（含 fuzz 摘要）、`fuzz.txt`、`latency.json`（兩段合計 + NFR 判定）、`denial-matrix.md`、`relay-bounds.md`、`security-report.md`、`e2e.xml` 與 8 張 `screenshots/`。腳本在任一 gate 失敗時回傳非零，證據包不可能描述沒發生過的綠燈；已接入 `p3.yml` 的 `evidence` job。
- **下一步**：push 觸發 `p3.yml`（唯一未驗項，同時關掉 WebKit）→ 依結果把 `docs/p3-report.md` 由 Conditional 改為 Go → 進入 P4（Dashboard／RBAC 營運介面／metrics export／FR-WORKSPACE-004/005）。
- **本機 E2E 注意**：`run-stack.sh` 會在 DB 寫入真實資料。本次驗證使用獨立資料庫 `cliora_e2e_p3`（跑完已 drop），避免污染共用的 `cliora_test`（DB 測試有首筆計數斷言）。
