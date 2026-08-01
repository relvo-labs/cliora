# 06 — 驗證、安全審查、量測與退出（TN-12 – TN-15）

## TN-12：Traceability 註冊與影響分析

這個 repo 的 traceability 處於**完整 release blocking**（ADR 0019 第三階段，`traceability/baseline-debt.json` 為空，`scripts/trace coverage --scope all --strict` 退出 0）。本期新增三個 requirement 與一條 scope，全部必須落到 `traceability/`。

### 1.1 影響分析（先做，不要事後補）

```bash
scripts/trace impact --base master --head HEAD
```

在 `TN-08`（Central）與 `TN-11`（前端）的 PR 上各跑一次。命中清單就是「必須確認仍然成立或必須改敘述」的 criterion 清單。可預期的命中：

| 既有 criterion 家族 | 為什麼會被命中 | 要確認什麼 |
|---|---|---|
| `SEC-005`（Transport Security） | 新增一條對外 origin 與一條新的 WSS | 敘述要涵蓋 tunnel zone；HTTPS/WSS-only 仍成立 |
| `FR-CONN-001`（主動連線） | 新增第二條 daemon→Central 連線 | 「daemon 主動連線」仍成立，敘述補「資料面亦為主動連線」 |
| `FR-CONN-005`（Terminal Binary Frame） | binary kind 白名單放寬 | 終端機的 kind 1／2 語意未變；新 kind 不進終端機路徑 |
| `NFR-001`（效能） | 共用 node 但不共用 socket | 由 `TN-14` §3 的量測支撐；若量測不達標，這一條就是紅的 |
| `FR-NODE-005`（Node 停用） | 停用 node 時 tunnel 要一併失效 | 新增一例測試：停用 node → 既有 tunnel 立即 `unavailable` 且新建被拒 |
| `SEC-006`（Audit） | 新增三個 audit action | 敘述補三個 action；D17 的「不記錄逐筆流量」要寫進 rationale |

### 1.2 新增三個 requirement

`traceability/requirements.json` 新增 `FR-TUNNEL-001`（8 criteria）、`FR-TUNNEL-002`（6）、`FR-TUNNEL-003`（5），格式對照 `FR-SHELL-001`：`kind: functional`、`lifecycle: active`、`applicability: ["mvp"]`、`criticality: must`、`owner`（001/002 為 `central`，003 為 `frontend`），`source_anchor` 對應 `01-…md` §1.3 寫入 PRD 的 anchor。

`kind: functional` + `criticality: must` 意味著**每個 criterion 都需要四類 `role: "primary"` 連結**（`scripts/traceability/validate.py`）：

| 連結型別 | target kind | 本期的目標 |
|---|---|---|
| `planned_by` | `plan` | `plan/10/03-…md`（daemon 相關）、`plan/10/04-…md`（Central）、`plan/10/05-…md`（edge／API／前端） |
| `specified_by` | `source` | `research/prd.md`（AC-02／AC-04 另加 `research/tech.md`） |
| `implemented_by` | `code` | `backend/app/services/tunnels.py`、`backend/app/api/http/tunnels.py`、`backend/app/api/middleware.py`、`daemon/internal/tunnel/*.go`、`daemon/internal/config/config.go`、`frontend/src/views/SessionWorkspaceView.vue`、`frontend/src/views/NodeDetailView.vue`、`deploy/nginx/nginx.conf` |
| `verified_by` | `pytest`／`gotest`／`vitest`／`playwright` selector | 對應測試，並掛 `gate_id`（`GATE-BACKEND-UNIT`、`GATE-BACKEND-DB`、`GATE-DAEMON-RACE`、`GATE-CONTRACT-CROSS-LANGUAGE`、`GATE-FRONTEND-UNIT`、`GATE-BROWSER-E2E`、`GATE-SECURITY`、`GATE-PERFORMANCE`、新增的 `GATE-TUNNEL-ZONE`） |

連結 id 沿用命名：`LNK-FR-TUNNEL-001-AC-01-PLANNED-BY` 等。19 個 criterion × 4 = **76 條新連結**。

> **順序陷阱**（plan/08 已踩過）：`validate.py` 會檢查 selector 路徑是否真的存在。`verified_by` 連結必須與測試檔在同一個 PR 落地；先註冊需求後補測試會讓中間每一個 commit 的 `make traceability` 都是紅的。

### 1.3 `SCOPE-013`

新增一筆 `kind: scope`、`criticality: must`、`owner: product`，`source.anchor: scope-013`，一個 criterion。它的守門連結必須包含**一條自動測試**（`backend/tests/test_scope_guards.py::test_scope_013_a_tunnel_url_is_not_a_credential`：對代理端點發一個不帶 cookie 的請求，斷言 401 且回應 body 與「不存在的 slug」完全相同）。理由與 `SCOPE-011` 相同：最容易被順手放寬的性質必須有機械化的守門。

### 1.4 新增 gate：`GATE-TUNNEL-ZONE`

`traceability/gates.json` 新增一筆（沿用 `GATE-RAILWAY-DEPLOY-VERIFY` 的形狀）：`layer: "operations"`、`command: ["scripts/tunnel/verify-zone.sh", "$CLIORA_TUNNEL_BASE_DOMAIN"]`、`trigger: ["release"]`、`environment: ["deployed-zone"]`。這道 gate 只能對真實網域跑，因此是 release-triggered 而非 PR-triggered，並在 `07-…md` 明確標為 staging-gated。

### 1.5 驗收

```bash
make traceability
```

全綠，且 `docs/traceability/coverage.md` 中 19 個新 criterion 皆為 `verifiable`。`scripts/traceability/tests` 內的 pinned summary 數字要更新並註明原因（plan/08 已有先例）。

---

## TN-13：安全審查

沿用 `docs/security-review-p4.md`／`docs/security-review-p8.md` 的格式，產出 `docs/security-review-p10.md`。**每一項都要有可重跑的測試或指令，不接受「已檢視」。**

| # | 對抗項目 | 期望 | 證據 |
|---|---|---|---|
| 1 | 未帶 cookie 開啟 tunnel URL；以及開啟一個不存在的 slug | **兩者回應完全相同**（狀態碼、body、header）。URL 不是憑證（`SCOPE-013`） | pytest（逐 byte 比對兩個回應） |
| 1b | ticket 換 cookie 之後，app 收到的第一個請求 | **不含帶 ticket 的 `Referer`**（`/__cliora/session` 回應帶 `Referrer-Policy: no-referrer`）；ticket 二次使用失敗 | pytest（斷言轉發給 daemon 的 header 清單中無 `referer` 或其值不含 `ticket=`） |
| 2 | 使用者 A 的 tunnel cookie 用在使用者 B 建立的 tunnel host | 401（`tid` ↔ Host 綁定） | pytest |
| 3 | tunnel cookie 當作 Bearer token 打 `/api/auth/me` | 拒絕（`aud != "access"`） | pytest |
| 4 | tunnel host 上請求 `/api/*`、`/ws/sessions/*`、console 靜態資產 | 全部 404（不是 403） | pytest ×3 |
| 5 | console host 上請求代理路徑 | 404 | pytest |
| 6 | 資料面訊息塞 `port`／`host`／`url`；`target` 為絕對 URL；header value 含 CRLF；`method: CONNECT` | Python 與 Go 兩端一致拒絕 | `contracts/v1/fixtures/invalid/` ×4 + `make contract` |
| 7 | 建立 port `22`／`80`／`5432` | `22`／`80` 一律拒（`<1024`，三層各擋一次：API、DB CHECK、daemon）；`5432` 依 node 允許清單 | pytest + Go test + 直接 INSERT 的 DB 負向測試 |
| 8 | node 明確 `tunnel.enabled: false` | Central 與 daemon 兩層都拒；**且預設值套用不會把明確停用改回啟用** | pytest + Go test（後者是 plan/08 踩過的同一顆釘子） |
| 9 | Viewer 建立／開啟 tunnel；Developer 關閉他人的 tunnel | 前者 403（**action 層**）、後者 403（**scope 層**）。兩例必須分開測——失敗的層級不同 | pytest ×2 |
| 10 | 慢讀客戶端 + 高輸出 app | 只有該 stream 被 `TUNNEL_BACKPRESSURE` 中止；同 node 的另一條 stream 位元組數持續增加；**終端機延遲不受影響**（與 `TN-14` §3 同一次量測） | pytest + 量測 |
| 11 | app 回 `Set-Cookie: …; Domain=.t.<zone>`；回 `Strict-Transport-Security` | `Domain` 屬性被移除、HSTS 被移除、其餘 header 逐 byte 不變（含 `X-Frame-Options` 被保留） | pytest |
| 12 | 完整生命週期後檢查 audit／log／metrics | 無請求路徑、無 query、無 header 值、無 body、無 label；`tunnel.access_denied` 有節流 | pytest（redaction）+ metrics label 斷言 |
| 13 | node 停用／credential 撤銷／node 移除 | data-plane socket 立即斷、tunnel 立即 `unavailable`、進行中的 stream 在 1 秒內收到 abort、新建被拒 | pytest（`registry.evict` 的既有路徑）+ 一例 DB 測試 |

第 1 項與第 4 項是這份審查的核心：**這個功能的整個安全論證建立在「URL 不是憑證」與「tunnel host 上沒有平台表面」兩句話上**，其餘都是補強。若這兩項有任何一項只有註解在防守，這個功能不能上線。

另外必須在文件中明寫（不是測試，是紀錄）：

- **隧道會忠實轉出 app 的一切行為。** app 若有 `/download?path=…`，隧道就把它變成可從瀏覽器使用的檔案讀取介面。P3 的敏感檔案政策對它無效（`01-…md` §1.2 表）。
- **daemon 的執行身分就是權限上界。** 與 ADR 0021 完全相同的一句話，第二次出現在第二個功能上——這一次是網路而不是檔案系統。
- **不轉發 `Cookie`／`Authorization` 給 app** 的取捨（`03-…md` §2.3）：需要登入的 app 在隧道後面無法維持自己的 session。

---

## TN-14：NFR 量測

新增 `backend/perf/tunnel_bench.py`（沿用 `perf/relay_bench.py`／`perf/files_bench.py` 的形狀），輸出 `artifacts/tn/local/tunnel-bench.json`，並掛進 `make perf`。**每一項不達標就退出非零。**

### 3.1 延遲

| 指標 | 目標 | 為什麼是這個數字 |
|---|---|---|
| 4 KiB `GET` 的端到端 p95（同機 loopback stack） | ≤ 120 ms | 三跳（瀏覽器→Central→daemon→app）各一次排隊。超過這個值，互動式頁面（點按鈕等回應）會被感覺到 |
| 同一請求的**額外**延遲（對照直接打 app 的基線） | ≤ 80 ms p95 | 把網路環境從指標中扣掉，量的是平台本身的成本 |
| WS 訊息往返 p95 | ≤ 60 ms | HMR 的可用性門檻 |

### 3.2 吞吐

| 指標 | 目標 |
|---|---|
| 單一 stream 下載（16 MiB 檔案） | ≥ 8 MiB/s |
| 8 條並行 stream 合計 | ≥ 16 MiB/s，且無 stream 被誤中止 |
| 記憶體 | 8 條並行 stream 期間 Central RSS 成長 ≤ 8 × `tunnel_stream_queue_max_bytes` + 64 MiB（佇列有界的直接後果） |

### 3.3 終端機不得退化（**這一項是 D5 的存在理由**）

一次量測，兩個受測對象同時進行：

1. 在 node 上開一個 CLI session，量測按鍵→回顯的往返 p95（沿用 `perf/relay_bench.py` 既有的量法）。
2. 同時在同一個 node 上以 ≥8 MiB/s 持續下載。

**判準：終端機 p95 相對於「無隧道流量」基線的退化 ≤ 10 ms。**

同時要跑一次**反例**以證明這個量測有辨識力：把隧道流量改走控制面 socket（測試專用旗標，不進產品程式），確認終端機 p95 明顯退化。一個永遠會綠的量測不是量測——plan/09 §5 的教訓（綠燈不等於正確）在這裡的形式是「沒有反例的效能斷言」。

### 3.4 驗收

- 三組數字寫進 `07-implementation-status.md`，標明**量測值**與量測環境。
- `make perf` 退出 0。
- `traceability/gates.json` 的 `GATE-PERFORMANCE` 命令涵蓋新的 bench。

---

## TN-15：Evidence、CI、runbook 與 exit gate

### 4.1 Evidence 腳本

新增 `scripts/tn/evidence.sh <輸出目錄>`，沿用 `scripts/wt/evidence.sh` 的紀律：**每一道 gate 記錄 exit status，任一失敗整支非零，skip 要誠實標記 skip 而不是當成 pass。**

| Gate | 指令 | 本機可跑 |
|---|---|---|
| 格式／lint／typecheck | `make format-check lint typecheck` | ✅ |
| 後端單元 | `pytest backend/tests -q` | ✅ |
| 後端 DB | `make test-db` | ✅（需 `CLIORA_TEST_DATABASE_URL`） |
| Daemon race | `go test -race ./...` | ✅ |
| Daemon integration | `make integration`（含新的 `./internal/tunnel`） | 需 tmux；無則 skip |
| 契約 | `make contract` | ✅ |
| 前端單元 | `npm run test:unit -- --run` | ✅ |
| Edge parity | `make railway-check` | ✅ |
| Traceability | `make traceability` | ✅ |
| 效能 | `make perf` | ✅ |
| Tunnel E2E（真 node、真 web app） | `npm run test:e2e -- tunnel.spec.ts` + `E2E_STACK_DATABASE_URL` | ✅ chromium／firefox；**WebKit 為 CI-only** |
| Zone 驗證 | `scripts/tunnel/verify-zone.sh` | ❌ **staging-gated**（需真實 wildcard 網域與憑證） |

最後一列是本期唯一無法在本機關掉的 gate，必須明確標為 staging-gated 並在 release checklist 中成為放行條件。**不得寫成無條件 skip**——plan/08 的教訓：一道無條件 skip 的 gate，綠燈與紅燈是同一個顏色。

### 4.2 E2E stack 的擴充

`scripts/e2e/run-stack.sh` 需要：

1. 一個確定性的受測 web app：新增 `daemon/cmd/faketunnelapp`（與既有 `cmd/fakecli` 對稱），提供 `/`（固定 HTML，含一個絕對路徑的 `/assets/app.js`）、`/assets/app.js`、`/api/echo`（POST 回相同 body）、`/sse`（每 200ms 一個事件）、`/ws`（echo，text 與 binary 都回）、`/deep/route`（用來驗證深層路由）。**用 Go 寫在 daemon 樹內**，因為 CI 上一定有 Go，而且它要能被 `go test` 直接當函式庫用。
2. `CLIORA_TUNNEL_BASE_DOMAIN=tunnel.localhost` 與 vite dev server 的 `server.allowedHosts` 設定。
3. 一個建立 tunnel 的步驟（用 API，不是 UI），把 slug 交給 Playwright。

### 4.3 CI

`.github/workflows/tn.yml`，沿用 `wt.yml` 的結構（6 jobs）。額外兩個 gate：

- **grep gate**：`frontend/src` 與 `backend/app` 內不得出現內容改寫的痕跡（`rewrite`、`inject`、`<base`、`replace(/src=` 之類的模式），以及不得出現路徑前綴代理端點（D1／D14 的機械化守門）。
- **CSP gate**：四處 CSP 字串一致，且 `frame-src` 只有 zone 一個來源（`make railway-check` 已涵蓋，在 CI 中獨立成一個 job 以便失敗時一眼看出原因）。

### 4.4 文件

| 文件 | 內容 |
|---|---|
| `docs/runbooks/tunnel.md` | 如何判斷 tunnel 不通是哪一跳（edge／Central／data-plane／app 四段各有一個可下的指令）、`Host` 被改寫成 `127.0.0.1:<port>` 這件事對 Vite `allowedHosts` 的影響、WS 訊息 >64 KiB 的限制、不轉發 `Cookie`／`Authorization` 的後果、如何以 `tunnel.enabled: false` 否決、如何查稽核、TTL 與延長、slug 永不重用的意義 |
| `docs/release-note-tunnel.md` | 給 node 擁有者：升級即取得此能力（`03-…md` §1.2 的預設值決定）、如何否決、權限上界為何是 daemon 身分、記錄與不記錄什麼、URL 不是憑證 |
| `docs/tn-report.md` | 交付內容、`TN-14` 的量測結果、已知限制（無 `content-length`／不轉發 cookie／WS 訊息上限／位址列只顯示「導覽到」／不支援非 HTTP 協定）、未關項與其歸屬 |
| `docs/release-checklist.md` | 新增一節：zone 驗證通過、daemon 非 root、release note 已發出、CSP 只放寬到 zone、`tunnel_cookie_insecure` 為 false |
| `docs/deployment.md`／`docs/deployment-railway.md` | zone 設定與「未設定即關閉」是預期行為 |

### 4.5 Exit 條件

全部必須關閉：

1. `TN-01` 的 ADR 0022（六項必記內容）、PRD 三個 requirement 與 `SCOPE-013`、tech 修訂已合併。
2. `TN-02` 六項有輸出，或不成立者有 waiver 且該環境功能關閉。
3. 契約 v1.6.0 在三語一致，四筆 invalid fixture 全部被拒。
4. 19 個新 criterion 在 `docs/traceability/coverage.md` 皆為 `verifiable`；`SCOPE-013` 有自動守門測試。
5. `TN-13` 十三項全部有證據，無未處理 Critical／High；第 1、4 項有逐 byte／逐路徑的斷言。
6. `TN-14` 三組量測達標，含 §3.3 的反例證明量測有辨識力。
7. Tunnel E2E 在本機 chromium + firefox 實跑通過（WebKit 標為 CI-only），涵蓋：絕對路徑資產、深層路由重載、POST、SSE、WS echo、iframe origin ≠ console origin。
8. 五份文件齊備（§4.4）。
9. `make check`、`make traceability`、`make railway-check`、`make perf` 全綠。
10. **關掉 zone 設定後跑一次完整 `make check`**：功能關閉時不得有任何測試失敗、不得留下放寬的 CSP、UI 不顯示入口。這一條是「功能關閉是明確狀態」（D2）的驗收，也是最容易被忽略的一項——所有人都會測開著的路徑。
