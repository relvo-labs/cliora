# 06 — 驗證、安全審查與退出（PG-13、PG-14）

## PG-13：Traceability 與安全審查

### 1.1 影響分析（先做，不要事後補）

```bash
scripts/trace impact --base master --head HEAD
```

在 `PG-06`（daemon）與 `PG-11`（前端）的 PR 上各跑一次。可預期的命中：

| 既有 criterion 家族 | 為什麼被命中 | 要確認什麼 |
|---|---|---|
| `SEC-005`（Transport Security） | 新增一條 node → 第三方的 SSH egress | 敘述要涵蓋 provider 連線；host key 釘選是本期唯一自有的傳輸控制 |
| `SEC-003`（Token 保護） | 新增一種憑證（provider token），且**由平台保管** | 敘述補「第三方憑證以 AES-GCM 加密儲存、永不回傳、僅以指紋顯示與稽核；下發後僅存於 Node 記憶體與子行程 argv，不落地」。**這是本期對既有安全需求最實質的一次擴充**，不是加一句話而已 |
| `FR-NODE-001`／`FR-NODE-002` | `node.register`／`node.runtime_status` 新增 `tunnel` 先決條件物件 | payload 變更是加法式；確認既有 criterion 的敘述不受影響 |
| `FR-AUTH-002`（角色權限） | 新增第三個 action `integration.manage`（只給 Admin） | 敘述與 `docs/permission-matrix.md` 同步；Developer 與 Admin 的分界多一條 |
| `FR-NODE-005`（Node 停用） | 停用 node 要讓隧道一併不可用 | 新增一例測試 |
| `SEC-006`（Audit） | 三個新 action | 敘述補三個 action；**並補一句能力缺口：埠轉發的流量不經過平台，因此無存取記錄** |
| `FR-INSTALL-003`（自動安裝流程） | installer 多佈署一個 `pinggy_known_hosts` | 確認安裝驗證仍成立 |

### 1.2 註冊四個 requirement

`traceability/requirements.json` 新增 `FR-TUNNEL-001`（8 criteria）、`FR-TUNNEL-002`（5）、`FR-TUNNEL-003`（4）、**`FR-TUNNEL-004 整合設定與憑證保管`（6）**，格式對照 `FR-SHELL-001`：`kind: functional`、`lifecycle: active`、`applicability: ["mvp"]`、`criticality: must`，`source_anchor` 對應 `01-…md` §2.3 寫入 PRD 的 anchor。

`FR-TUNNEL-004` 的六個 criterion 條文見 `01-…md` §2.3(a)（**不在此重複，避免兩份會漂移的敘述**）。

每個 criterion 需要四類 `role: "primary"` 連結（23 個 criterion × 4 = **92 條**）：

| 連結型別 | 目標 |
|---|---|
| `planned_by` | `plan/11/03-…md`（daemon）、`plan/11/04-…md`（Central）、`plan/11/05-…md`（前端） |
| `specified_by` | `research/prd.md`（AC 涉及傳輸者另加 `research/tech.md`） |
| `implemented_by` | `daemon/internal/tunnel/*.go`、`daemon/internal/config/config.go`、`backend/app/services/tunnels.py`、`backend/app/services/integrations.py`、`backend/app/security/secret_box.py`、`backend/app/api/http/tunnels.py`、`backend/app/api/http/integrations.py`、`frontend/src/views/IntegrationsView.vue`、`frontend/src/views/NodeTunnelsView.vue` |
| `verified_by` | 對應測試 + `gate_id`（`GATE-BACKEND-UNIT`、`GATE-BACKEND-DB`、`GATE-DAEMON-RACE`、`GATE-DAEMON-INTEGRATION`、`GATE-CONTRACT-CROSS-LANGUAGE`、`GATE-FRONTEND-UNIT`、`GATE-BROWSER-E2E`、`GATE-SECURITY`、新增的 `GATE-TUNNEL-PROVIDER`） |

`SCOPE-013` 另註冊一筆 `kind: scope`、`criticality: must`、`owner: product`，守門測試為「Central 沒有代理路由」（`01-…md` §2.3(b)）。

> **順序陷阱**：`validate.py` 檢查 selector 路徑是否存在，所以 `verified_by` 必須與測試檔同一個 PR 落地。

新 gate `GATE-TUNNEL-PROVIDER`：`command: ["scripts/tunnel/verify-provider.sh"]`、`trigger: ["release"]`、`environment: ["provider-account"]` —— 需要真實帳號，因此 release-triggered 且在 `07-…md` 標為 staging-gated。

### 1.3 安全審查（13 項）→ `docs/security-review-p11.md`

沿用 `docs/security-review-p8.md` 的格式。**每一項都要有可重跑的測試或指令。**

| # | 對抗項目 | 期望 | 證據 |
|---|---|---|---|
| 1 | **host key 不符** | `ssh` 拒絕連線；平台顯示 `TUNNEL_PROVIDER_UNTRUSTED`；**不 fallback 成不驗證** | Go test（fake provider 用不同 host key）+ grep gate 斷言原始碼中不存在 `StrictHostKeyChecking=no`／`UserKnownHostsFile=/dev/null` |
| 2 | **`known_hosts` 檔案缺失或為空** | 拒絕啟動子行程（斷言 dial 次數 0），不是「跳過驗證」 | Go test |
| 3 | **憑證在靜態儲存中** | DB 內為 AES-GCM ciphertext；每次加密 nonce 不同；用錯金鑰無法解密（tag 驗證失敗）；**沒有任何欄位或路徑可以存明文** | pytest + DB 內容檢查 |
| 3b | **憑證在介面上** | `GET /api/integrations/tunnel` 的回應不含 token 的任何字元（只有 `configured` 與 8 hex 指紋）；前端 DOM 中亦無；稽核 metadata 只有指紋 | pytest（鍵集合 + 值比對）+ vitest（DOM 斷言）+ redaction 測試 |
| 3c | **憑證在傳輸與 node 上** | `tunnel.open` 攜帶憑證（TLS）；node **不寫入磁碟**（斷言檔案系統無該值）、log 中以 `<credential>` 佔位、`doctor` 輸出不含它；pid 檔不含它 | Go test（含 log 內容斷言）+ integration test |
| 3d | **憑證字元集** | 含 `+`／`@`／空白／非 `[A-Za-z0-9]` 的值在 API、schema、daemon 三處皆被拒。**這是注入 SSH 目的地與隧道型別的入口** | pytest + invalid fixture + Go test |
| 3e | **金鑰不可用時** | `CLIORA_SECRET_ENCRYPTION_KEY` 未設定時，啟用整合與設定憑證皆回 `SECRET_KEY_MISSING`，**不退化成明文儲存**；`/readyz` body 標示該功能不可用 | pytest |
| 4 | **basic auth 密碼的注入面** | 含 `:` 的密碼在 schema、Central、daemon 三處皆被拒；參數以 `[]string` 傳遞，無 shell 解讀路徑 | invalid fixture + pytest + Go test |
| 5 | **密碼只顯示一次** | `GET /api/tunnels`／`/{id}` 的回應 JSON 無密碼欄位；DB 存的是 Argon2 hash | pytest（鍵集合斷言 + hash 比對） |
| 6 | **URL 是不可信輸入** | daemon 拒絕 `http://`、未知網域、>2048、含控制字元的 URL；schema 為第二層 | Go test ×4 + invalid fixture |
| 7 | **特權 port 與允許清單** | `22`／`80` 在 API、DB CHECK、daemon 三層各被拒一次；不在 node 允許清單者被拒 | pytest + 直接 INSERT 的 DB 負向測試 + Go test |
| 8 | **權限邊界** | Viewer 建立／檢視 403（**action 層**）；**Developer 對整合設定端點 403（`integration.manage` 只給 Admin）**；Developer 關他人隧道 403（**scope 層**） | pytest ×3 |
| 8b | **三層設定只能收窄** | 平台設定放寬時，node 本機的否決與較窄的 port 清單仍然生效；`effective_policy` 的純函式測試涵蓋四輸入的邊界組合；**沒有任何 API 路徑能覆寫 node 否決** | pytest（純函式）+ Go test（daemon 端第二層）|
| 9 | **孤兒行程** | `kill -9` daemon 後重啟，前一代 `ssh` 已不存在；`/run/agentd/tunnels/` 無殘留 | integration test |
| 10 | **稽核與 log 的內容** | 無 URL、無密碼、無 token、無 label；`public` 模式有 `tunnel.public_acknowledged`；首次確認可從稽核回查 | pytest（redaction）+ metrics label 斷言 |

另外必須在文件中明寫（是紀錄，不是測試）：

- **三項補償控制都擋不住 provider 本身。** Pinggy 位於 TLS 終結點之後，可見未加密的 HTTP 內容。因此**此功能僅適用於預覽開發中的應用**（`01-…md` §2.2 的「不擋什麼」欄）。
- **同一台機器上同 uid 的行程可讀到憑證**（它在 `ssh` 的 argv 與 daemon 記憶體裡，`03-…md` §2.1a）。daemon 非 root 執行同時是保護也是邊界。
- **平台保管第三方憑證的後果**：金鑰遺失＝已存憑證無法解密（處置是重新輸入，不是還原）；平台被入侵＝該憑證應視為已洩漏並在 Pinggy 端撤換。兩者都要寫進 runbook。
- **停用整合不會關閉既有隧道**（`04-…md` §0.2）。這是刻意的，因為關閉可能部分失敗；UI 分成兩個動作。
- **daemon 的執行身分就是權限上界。** 第三次出現在第三個功能上（ADR 0021 的 shell、plan/10 的自建代理、本期）。
- **provider 中斷即功能不可用**，無 fallback（D15）。
- **退出分類依賴 stderr 字串比對**（`03-…md` §2.4），provider 改訊息會讓錯誤全部退化成 `_UNAVAILABLE`。

---

## PG-14：Evidence、CI、runbook 與 exit gate

### 3.1 Evidence 腳本

新增 `scripts/pg/evidence.sh <輸出目錄>`，沿用 `scripts/wt/evidence.sh` 的紀律：**每道 gate 記錄 exit status，任一失敗整支非零，skip 要誠實標記 skip。**

| Gate | 指令 | 本機可跑 |
|---|---|---|
| 格式／lint／typecheck | `make format-check lint typecheck` | ✅ |
| 後端單元 | `pytest backend/tests -q` | ✅ |
| 後端 DB | `make test-db` | ✅ |
| Daemon race | `go test -race ./...` | ✅ |
| Daemon integration（含 `./internal/tunnel`，fake provider） | `make integration` | ✅（不需網路、不需帳號） |
| 契約 | `make contract` | ✅ |
| 前端單元 | `npm run test:unit -- --run` | ✅ |
| Traceability | `make traceability` | ✅ |
| Tunnel E2E（fake provider stack） | `npm run test:e2e -- tunnel.spec.ts` | ✅ chromium／firefox；WebKit CI-only |
| 憑證外洩 grep | `scripts/pg/check-no-token-leak.sh`（掃 log 樣板、fixture、稽核欄位白名單、`doctor` 輸出樣板） | ✅ |
| **真實 provider 驗證** | `scripts/tunnel/verify-provider.sh` | ❌ **staging-gated**（需真實帳號與 Pro token） |

只有最後一列不可在本機關掉。**不得寫成無條件 skip** —— plan/08 的教訓：一道無條件 skip 的 gate，綠燈與紅燈是同一個顏色。

### 3.2 E2E stack：fake provider

`scripts/e2e/run-stack.sh` 擴充（**不連真實 Pinggy**，理由見 `03-…md` §2.6）：

1. 一個假的 provider：`daemon/internal/tunnel/testdata/fake-provider`（小 Go binary，與既有 `cmd/fakecli` 對稱），行為＝印出一行 `https://fake-<random>.example.invalid`、維持行程、可用參數模擬時限退出與 host key 失敗。
2. node config 以 `tunnel.enabled: true` ＋ `provider: pinggy` ＋ 指向 fake binary 的測試專用覆寫（`Provider` interface 的注入點，`03-…md` §2.6）。
3. 一個受測 web app（既有 `cmd/fakecli` 不適用；沿用 plan/10 的建議新增 `daemon/cmd/faketunnelapp`，或直接用 `python -m http.server` —— **選前者**，CI 上一定有 Go，且它能被 Go test 當函式庫用）。

`example.invalid` 是刻意的：E2E **不會**真的去開那個網址（RFC 2606 保證它不可解析），所以測試不依賴網路，也不可能誤打到真實服務。

### 3.3 CI

`.github/workflows/pg.yml`，沿用 `wt.yml` 的結構。額外兩個 gate：

- **host key grep gate**：原始碼與 deploy 設定中不得出現 `StrictHostKeyChecking=no`、`StrictHostKeyChecking no`、`UserKnownHostsFile=/dev/null`。
- **代理復活 gate**：`backend/app/` 中不得出現 catch-all `{path:path}` 路由或任何把請求轉往 node HTTP 服務的程式（`SCOPE-013` 的機械化守門）。

### 3.4 文件

| 文件 | 內容 |
|---|---|
| `docs/runbooks/tunnel-pinggy.md` | **五段判斷**（整合未啟用／node 未參與或本機否決／先決條件不足／host key 不符／provider 不可用）各一個可下的指令；**host key 輪替程序**（症狀是全部隧道回 `_UNTRUSTED`）；**`CLIORA_SECRET_ENCRYPTION_KEY` 的產生、保管與輪替**（含「金鑰遺失＝重新輸入 token」）；憑證輪替程序（換 token 只影響新建隧道）；訂閱由使用者自理但**平台端誰負責換 token**；免費與 Pro 的差異；`rotate-password` 會換 URL；退出分類依賴 stderr 字串這件事 |
| `docs/release-note-tunnel.md` | 兩個讀者。**給平台管理員**：如何在整合設定啟用、需要先備好 `CLIORA_SECRET_ENCRYPTION_KEY`、訂閱與 token 自備、啟用即代表組織同意流量經過第三方。**給 node 擁有者**：升級本身不啟用任何東西；平台啟用後這台機器預設參與；如何以 `tunnel.enabled: false` 一票否決；憑證不在你的機器上 |
| `docs/pg-report.md` | 交付內容、`PG-01` 的實測結果表、能力缺口清單（無存取記錄／無內容政策／URL 會變／iframe 與 basic auth 互斥／provider 中斷即不可用／同 uid 可讀 token）、未關項與歸屬 |
| `docs/release-checklist.md` | 新增一節：`PG-01` 驗證通過、daemon 非 root、release note 已發出、`known_hosts` 已佈署、token 續訂負責人已指定 |
| `docs/deployment.md` | `CLIORA_TUNNEL_INTEGRATION_ENABLED` 與新增的 node egress 需求（TCP 443 到 provider） |

### 3.5 Exit 條件

1. `PG-01` 十項有輸出；第 1、3、4、5、8 項的結果已寫進 `07-…md` 的 provider 事實表，且與計畫假設不同之處已回頭修正相關票。**第 8 項（同 token 能否並存多條）必須有明確答案**，因為它決定 `concurrent_budget` 的預設是否還是 1。
2. ADR 0022（七項必記內容）、PRD 三個 requirement 與 `SCOPE-013`、tech 修訂已合併。
3. 契約 v1.6.0 三語一致，三筆 invalid fixture 全被拒。
4. 23 個新 criterion 在 `docs/traceability/coverage.md` 皆為 `verifiable`；`SCOPE-013` 有自動守門測試。
5. `PG-13` 十三項對抗全部有證據，無未處理 Critical／High；**第 1–2 項（host key）與 3／3b／3c／3d／3e（憑證的五個面）是本期的核心**，必須有測試而非說明。
6. `00-…md` §1 的**八項**判準各有通過的證據，含**孤兒回收**、**host key 不符時的行為**、**金鑰未設定時的拒絕**與**三層設定的交集**。
7. E2E 以 fake provider 在本機 chromium + firefox 實跑通過；真實 provider 驗證在 staging 跑過一次並存檔。
8. 五份文件齊備（§3.4）。
10. **在「整合未啟用」與「金鑰未設定」兩種狀態下各跑一次完整 `make check`**：不得有任何測試失敗、node 頁與 sidebar 的顯示正確、CSP 未被放寬。最容易被忽略的一項 —— 所有人都會測開著的路徑。
11. `PG-12`（iframe）的做／不做已明確記錄（含理由）。
