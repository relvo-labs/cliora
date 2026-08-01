# 07 — 實作進度與證據

本檔隨實作更新；「證據」欄只填**實際跑過的指令與其輸出位置**，不填計畫中的測試。

最後更新 2026-08-01（第三次交棒，含補齊）：**PG-01–PG-11、PG-13、PG-14 完成；`PG-12` 依 D-5 不做。
fake provider 的 stack 已建好並在本機驗過（14 項斷言全綠）；剩下的三項都需要這台機器沒有的東西
（root 裝的瀏覽器函式庫、staging、付費 token）。**

> ### 下一輪從這裡接手
>
> **本期的功能面已可交付**：`scripts/pg/evidence.sh` 的 17 道 gate 全綠（`artifacts/pg/local/summary.md`），
> 兩筆 skip 都是誠實的：真實 provider（需帳號，release-triggered）與 fake provider 的 E2E（未實作）。
>
> **剩下三件事，全部是環境限制，沒有一件是「還沒寫」：**
>
> | # | 項目 | 缺什麼 | 現有替代證據 |
> |---|---|---|---|
> | 1 | **瀏覽器那一段**（`frontend/tests/e2e/tunnel.spec.ts` 的 rendering 斷言） | Playwright 的系統函式庫要 root 裝（`libatk-1.0.so.0`）。CI 有，這台機器沒有 | spec 已寫好，`p2.yml` 的 `npm run test:e2e` 會跑整個 `tests/e2e` 目錄，因此三個引擎都會跑到它。本機以 `scripts/pg/tunnel-stack-check.sh` 走完同一條平台路徑（14 項斷言，無瀏覽器） |
> | 2 | **真實 provider 在 staging 的那一次** | staging 環境 | `PG-01` 已在本機對真實服務跑完十二項並存檔；`GATE-TUNNEL-PROVIDER` 已註冊為 release-triggered |
> | 3 | **Pro 方案的三項實測**（60 分鐘實際行為、固定子網域 hostname、方案真實併發數） | 付費 token | `concurrent_budget` 預設 8，UI 已寫「請依你的方案填寫」；重連換網址的程式路徑有測試 |
>
> **啟動 stack 的指令**（這台機器可跑，需要一個空的資料庫）：
>
> ```bash
> CLIORA_DATABASE_URL=postgresql+asyncpg://cliora:cliora@127.0.0.1:5432/cliora_e2e \
>   scripts/e2e/run-stack.sh scripts/pg/tunnel-stack-check.sh
> ```
>
> **環境事實（會影響第一個指令）：**
>
> | 事實 | 值 |
> |---|---|
> | 工具鏈不在 PATH 上 | `export PATH="$HOME/.local/bin:/usr/local/go/bin:$HOME/.nvm/versions/node/v22.23.2/bin:$PATH"` |
> | Postgres 已在跑（使用者於 2026-08-01 啟動） | `postgresql+asyncpg://cliora:cliora@127.0.0.1:5432/cliora_test`，已 `alembic upgrade head` 到 `0016` |
> | **`make test-db` 要同時設兩個變數** | `CLIORA_TEST_DATABASE_URL` **與** `CLIORA_DATABASE_URL`。只設前者時 `AuthzDenialAuditMiddleware` 會用預設 URL 開自己的 session 而寫失敗，症狀是 `test_audit_coverage.py` 兩例失敗、`audit_write_failed` 出現在 log —— 看起來像本期的 bug，其實是環境 |
> | docker 不可用 | 沒有 root、沒有 docker group；DB 由使用者在宿主機起 |
> | `pkill -f <pattern>` 會殺掉自己的 shell | wrapper 的命令列含同一字串；用 `pkill -x ssh` 或 bracket trick |
> | 真實 provider 可達 | `free.pinggy.io:443` 通，`ssh` 在，`scripts/tunnel/verify-provider.sh` 可重跑 |
>
> **三筆「刻意延後」已全部帶回**（`PG-07`／`PG-08`／`PG-09` 落地時）：三個 `tunnel.*` 稽核 action、
> 兩個 Central-only 錯誤碼、`rbac.UNENFORCED_ACTIONS` 清空。守門測試現在是綠的，而不是被繞過的。
>
> **既有 flake 已修**：`test_publishing_a_release_is_picked_up_without_a_restart` 原本三次失敗兩次
> （兩次發佈落在同一個 mtime tick，快取鍵相同）。測試端在第二次發佈後把 mtime 往前推一秒；連跑五次全綠。
> 這是本期之外的修正，但它會讓 `make check` 隨機變紅並掩蓋真正的失敗，而 exit 條件要求「不得有任何測試失敗」。
>
> 取代 [plan/10](../10/)（已作廢）。

**2026-08-01 需求變更**：使用者確認「訂閱自理、在系統整合設定啟用、每個 node 有自己的 Pinggy 設定頁」。
因此新增 `PG-09`（整合設定服務與憑證加密）與 `PG-10`（系統整合設定頁），原「Node 詳情 Tunnels 區塊」
升級為 `PG-11`（node 埠轉發設定頁）；並**反轉了初版的 D4**（憑證改由平台保管）。

## 決策紀錄

| # | 決策 | 狀態 | 決定者／日期 | 備註 |
|---|---|---|---|---|
| D-0 | 不自建反向代理，改以第三方整合交付 | ✅ **已決定 2026-08-01**（使用者） | 使用者／2026-08-01 | plan/10 作廢，保留為替代方案論證。ADR 0022 尚未撰寫 |
| D-1 | `PG-02`：把使用者的 HTTP 流量交給 Pinggy，且由平台保管其憑證 | ✅ **已核准並落地 2026-08-01**（使用者指示實作） | 使用者／2026-08-01 | ADR 0022 已寫入七項必記內容並合併。**書面決定已完成**，不再是閘門 |
| D-2 | 整合方式：`exec ssh`（而非 `x/crypto/ssh`） | ✅ **已確認 2026-08-01（實測）** | — | `BatchMode=yes` 可行，認證方式 `none`。重開條件不觸發 |
| D-3 | node 端預設停用 | ⬜ 未決定 | — | 與 plan/08（shell 預設啟用）與 plan/10 相反。若改成預設啟用，release note 的內容會反過來，且 D-1 的核准範圍要重新界定 |
| D-4 | 保護模式預設 `basic` | ✅ **已確認 2026-08-01（實測）** | — | 免費版即支援 `b:user:pass`（401/401/200），不需要 Pro |
| D-5 | `PG-12`（iframe 內嵌）做或不做 | ✅ **決定不做 2026-08-01（實作者，依 `05-…md` §3.1 的成本表）** | — | 四項成本換到的是「少按一次新視窗」：它是本期唯一要放寬 CSP 的工作、要把第三方網域寫進自家安全政策（provider 免費版與 Pro 網域不同）、**只有 `ipallow` 與 `public` 能內嵌**（Chrome 不在 cross-origin iframe 顯示 basic auth 對話框，等於內嵌只在較弱的保護模式下可用），而且本期後端不在資料路徑上、無法像 plan/10 那樣先探測 `X-Frame-Options`，所以「畫面空白」沒有可靠的失敗事件。`frame-ancestors 'none'` 兩份 edge 設定皆未改動 |
| D-6 | Pro 訂閱由誰持有 | ✅ **已決定 2026-08-01（使用者）**：**使用者自行處理** | 使用者／2026-08-01 | 平台不代購、不代管帳號、不呼叫 Pinggy 管理 API（D20）。**平台端仍需指定「誰負責在整合設定裡換 token」**，這一項留在 `PG-14` 的 exit 條件 |
| D-7 | 憑證由平台保管（**反轉初版 D4**） | ✅ **已決定 2026-08-01（需求）** | 使用者／2026-08-01 | 「在系統整合設定啟用」的實質內容就是提供 token。代價：平台成為第三方憑證的保管者 → 需要 `CLIORA_SECRET_ENCRYPTION_KEY`、AES-GCM、永不回傳、只顯示指紋（D19），以及金鑰遺失／平台被入侵兩種情境的 runbook |
| D-8 | node 本機「預設參與 + 一票否決」（而非「必須明確啟用」） | ✅ **已依此實作 2026-08-01** | — | `applyTunnelDefaults()`：缺項＝不否決；`enabled: false` 為絕對否決，daemon 端獨立再檢查一次。理由（node 已授予平台 `shell` runtime，ADR 0021）寫在 config.go 與生成的 `config.yaml` 註解裡。**若要反轉為「必須明確啟用」，改一處預設值＋release note 的敘述** |
| D-9 | `concurrent_budget` 預設 **8** | ✅ **已決定 2026-08-01（使用者）** | 使用者／2026-08-01 | 車隊級上限（整個平台同時存活的隧道數），以全域計數單獨檢查，**不進 per-node 的 `min()`**（D17b）。**`PG-01` #8 仍要確認方案的實際併發數**：若方案允許少於 8，此值必須調降，否則第 9 條會踢掉別人的隧道 |
| D-10 | 併發預算與 per-node 上限是兩條獨立檢查（D17b） | ✅ 已決定 2026-08-01（修正） | — | 原計畫把兩者放進同一個 `min()`，那會讓「預算 8、per-node 3」變成每台 3 條而全域永遠檢查不到 8 —— 車隊實際可開 3×N 條 |

## Provider 事實表（`PG-01` 已於 2026-08-01 對真實服務實測）

證據：`artifacts/pg/local/provider-verify.json`，腳本 `scripts/tunnel/verify-provider.sh`（可重跑）。
**十二項全數執行、全數通過**；`pro_token_supplied: false`，因此 Pro 專屬的三項仍未驗。

| # | 項目 | 原假設 | **實測結果** | 影響 |
|---|---|---|---|---|
| 1 | 非互動式啟動（`BatchMode=yes`） | 可行 | ✅ **可行**，認證方式為 `none`，無密碼提示 | D1（`exec ssh`）成立，重開條件不觸發 |
| 2 | URL 印出格式與時機 | stdout，可能需 PTY | ✅ **stdout，且絕不可加 PTY**。無 PTY 時是四行乾淨文字（前兩行是狀態、後兩行是 URL）；**加 `-t` 會得到 19 KB 的 ANSI 全螢幕 TUI，完全無法解析** | `03-…md` §2.1：禁止 `-t`／`-tt`，不使用 `creack/pty` |
| 2b | 網址數量與網域 | 一個 | ✅ **兩個**：`https://<slug>-<公網IP>.run.pinggy-free.link` 與 `https://<slug>-<公網IP>.free.pinggy.net` | URL 解析要接受兩種後綴；取第一個 https |
| 2c | **網址是否洩漏資訊** | 未預期 | ⚠️ **免費版的 hostname 內嵌該 node 的公網 IP**（`xxxxx-114-32-49-189.…`） | **新增揭露義務**：ADR、UI 與 release note 必須明講 |
| 3 | host key 指紋 | 未知 | ✅ **RSA 4096，`SHA256:nFd5rfJMGuZXvfeRzJ/BtT3TfksAxTWMajcrHRcI7AM`**，`free`／`pro`／`a.pinggy.io` 三個主機**同一把**；服務端只提供 RSA（KEX offer 為 `rsa-sha2-512,rsa-sha2-256`），無 ed25519／ecdsa 可釘 | `deploy/pinggy_known_hosts` 已寫入（三行，含輪替說明） |
| 4 | basic auth 是否需要 Pro | 免費即可用 | ✅ **免費版即可用**：無憑證 401、錯誤憑證 401、正確憑證 200，`WWW-Authenticate: Basic realm="Pinggy Basic Auth Failed"` | D5 的預設 `basic` 成立，`PG-10` 不需要分支 |
| 5 | 免費版 60 分鐘的行為 | 行程退出 | ⏳ **未驗**（需等滿 60 分鐘）。橫幅明文寫「Your tunnel will expire in 60 minutes」 | `03-…md` §2.4 的重連判定仍以「行程退出」為主要路徑，並保留「隧道靜默失效」的健康檢查作為未關項 |
| 6 | 重連後 URL 是否改變 | 是（免費） | ✅ **每次連線都是新的隨機 slug**（觀察到 6 次連線 6 組不同網址） | D9 成立 |
| 7 | Pro persistent subdomain 的 hostname | 未知 | ⏳ **未驗**（無 Pro token） | `PG-12`（iframe）的 CSP 若要做，需先補這一項 |
| 8 | 同一 identity 能否並存多條 | 假設不能 | ✅ **可以**：兩條同時存活，兩個網址皆可用，無 `too many`／`limit` 訊息（匿名免費身分下） | `concurrent_budget: 8`（使用者決定）在技術上無阻礙；**Pro 方案的實際併發數仍需以 token 實測**，少於 8 就調降 |
| 9 | `x:https`／`x:xff` 的效果 | 生效 | ✅ **皆生效**：`http://` 被 **301** 導向 https；app 收到 `X-Forwarded-For: <呼叫者公網 IP>`，另有 `Forwarded:` 與 `X-Forwarded-Host`／`X-Forwarded-Proto` | 明文入口是導向而非拒絕，UI 文案照此描述 |
| 10 | 不可用／認證失敗／host key 不符可否分辨 | 三者 stderr 不同 | ⚠️ **只有兩者可分辨**。host key 不符與 known_hosts 空檔皆為 `exit 255` + `Host key verification failed.`（可靠）；但**無效憑證不會失敗** —— 服務**靜默降級為匿名免費隧道**並照樣給網址 | **`03-…md` §2.4 必須改寫**：`_UNAUTHORIZED` 只能靠解析 stdout 的 `You are not authenticated.` 判定，且 Pro 模式下必須視為失敗並中止隧道 |
| 11 | app 收到的 `Host` 與 header 原貌 | 未知 | ✅ `Host` **是隧道網域**（不是 loopback）→ Vite／Next 的 host allowlist 會擋；**`Cookie` 與 `Authorization` 原樣通過** | **新增 D8b**：提供選用的 Host 改寫（`u:Host:…`）。Cookie 通過是相對 plan/10 的優勢，寫進 ADR |
| 12 | 免費版的其他限制 | 未知 | ⏳ 僅確認 60 分鐘與「未認證」橫幅；頻寬／請求數未觀察到限制 | UI 免費模式說明照此撰寫 |

**仍未關的三項（皆需 Pro token，屬 staging-gated）**：#5（60 分鐘實際行為）、#7（Pro 固定子網域 hostname）、#8 的 Pro 方案併發數。`PG-14` 的 exit 條件保留這三項。

## 波次 0：閘門

| Ticket | 標題 | 狀態 | 證據 | 備註 |
|---|---|---|---|---|
| PG-01 | Pinggy 行為實測與 host key 取得 | ✅ **完成 2026-08-01** | `scripts/tunnel/verify-provider.sh`（12 檢查全通過）；`artifacts/pg/local/provider-verify.json`；`deploy/pinggy_known_hosts` | 免費版全數實測。**三項假設被推翻**（PTY／無效憑證／Host），已回頭修正計畫。Pro 專屬三項仍為 staging-gated |
| PG-02 | ADR 0022、PRD 修訂與 `SCOPE-013` | ✅ **完成 2026-08-01** | `scripts/trace validate --level static` 與 `render --check` 皆通過（新 anchor 全部存在） | `docs/adr/0022-third-party-tunnel-integration.md`（七項必記內容，含「實測改變了什麼」一節）；PRD 新增 §8.10 的 `FR-TUNNEL-001`–`004`（23 個 AC）、`SCOPE-013`、`SEC-008`、`FR-CONN-006.AC-09`；tech.md §8.0 與 §12.2 |

## 波次 1：契約與資料

| Ticket | 標題 | 狀態 | 證據 | 備註 |
|---|---|---|---|---|
| PG-03 | 契約 v1.6.0：5 個控制訊息、6 個錯誤碼 | ✅ **完成 2026-08-01** | `make contract` exit 0：Python 101／Go `TestContractJSONManifest`／TS 80 全綠 | 六個 payload schema（含 `node-tunnel-report`）、envelope 加 5 型別＋6 碼、**11 筆 fixture**、CHANGELOG 1.6.0、Go codec（`ValidCredential`／`ValidTunnelURL` 匯出供 supervisor 二次驗證）、**TS decoder 六個 validator**（計畫原寫「不改」，見 `02-…md` §1.4 的修正） |
| PG-04 | migration 0014–0016、三個 action、settings、error catalog | ✅ **完成 2026-08-01（含 DB 驗證）** | `alembic upgrade→downgrade→upgrade` 連跑三輪成功；**`pytest tests/db` 278 passed**（含 22 例新 schema 測試與 `test_permission_matrix` 三方一致）；`pytest backend/tests` 639 passed；`test_secret_box.py` 16 例；`mypy` 87 檔 | 三張表 ＋ `nodes` 六個回報欄位、三個 action（rbac＋seed＋`dto.ts`）、`security/secret_box.py`（AES-GCM）、settings 七項＋金鑰長度 validator、七個 wire／Central 錯誤碼（catalog＋前端 guidance＋渲染節）、`docs/permission-matrix.md` 重新產生 |

## 波次 2：Daemon

| Ticket | 標題 | 狀態 | 證據 | 備註 |
|---|---|---|---|---|
| PG-05 | 本機否決設定、host key 釘選、`doctor` | ✅ **完成 2026-08-01** | `go test -race ./...` 全部 ok；`internal/config` **10 例**新測試；`gofmt`／`go vet` 乾淨 | `TunnelConfig`（`Enabled *bool` 以區分「沒寫」與「明確 false」）、`TunnelPortAllowed`（1024 硬下界，設定只能收窄）、`Validate` 擋跨越下界的範圍、遺留 `token:` 鍵警告忽略、`doctor` 四項（**刻意沒有憑證那一項**）、installer 寫出帶說明的 `tunnel:` 區塊並有 round-trip 測試 |
| PG-06 | `ssh` 子行程監管、URL 解析、重連與 TTL、孤兒回收 | ✅ **完成 2026-08-01** | `internal/tunnel` **29 例**（fake provider 跑完整生命週期）、`-race` 乾淨 | `provider.go`／`pinggy.go`／`supervisor.go`；「不得有 PTY／`-N`」與「憑證不得含 `+`／`@`」都有守門測試；URL 後綴白名單（`dashboard.pinggy.io` 不會被誤取）；退出分類；backoff＋10 次上限；TTL；pid 檔與孤兒回收（含「不殺無關行程」）；憑證只在記憶體與 argv |

## 波次 3：Central

| Ticket | 標題 | 狀態 | 證據 | 備註 |
|---|---|---|---|---|
| PG-09 | **整合設定服務、憑證加解密與 API** | ✅ **完成 2026-08-01** | `pytest backend/tests` 675 passed（含修掉的 releases flake）；`pytest tests/db` 312 passed；`mypy` 91 檔 | service 層原已完成；本輪新增 `api/http/integrations.py` 的四個端點。**回應永不含 token 的任何字元**有兩道測試（序列化後的 body 比對＋DOM 斷言）；`secret_key_available` 由伺服器回報；`active_tunnel_count` 一併回報，讓「停用」的後果在按下之前就看得到。刻意**沒有**「測試連線」端點（會產生使用者沒要求的對外暴露，且失敗原因與正式建立完全相同） |
| PG-07 | tunnel service、三層設定合成、URL 變更傳播 | ✅ **完成 2026-08-01** | `test_tunnel_policy.py` **18 例**（純函式，無 DB）；`test_tunnels_api.py` **34 例**（DB＋fake node）；`test_scope_guards.py` 新增 SCOPE-013 守門 | `repositories/tunnels.py`（`_live()` 一個述詞供三條額度共用）、`services/tunnels.py`（`effective_policy` 純函式、`derive_state` 六狀態、`apply_status` 四種 state、`close_for_node`）。`tunnel.status` 在 `resolve_response` **之前**分派；node 的 `tunnel` 回報在 `node.register`／`node.runtime_status` 兩條路徑落地（`apply_tunnel_report`）。停用／移除／撤銷憑證都會關掉該 node 的隧道（否則 row 會一直佔用車隊預算） |
| PG-08 | Tunnels API、稽核 | ✅ **完成 2026-08-01** | 同上；密碼外洩測試斷言 `GET /api/tunnels` 的 body 不含密碼、DB 存的是 Argon2 hash | 五個 `/api/tunnels` 端點 ＋ 兩個 per-node 端點（`tunnel-policy` 讀、`tunnel-settings` 寫，後者需 `tunnel.manage` 而非 `integration.manage`）。`rotate-password` ＝關閉並重開，**回應帶新的 URL**，測試斷言 `id` 也不同——它是一條新隧道，回應據實呈現 |

## 波次 4：介面

| Ticket | 標題 | 狀態 | 證據 | 備註 |
|---|---|---|---|---|
| PG-10 | **系統整合設定頁**（`/settings/integrations`） | ✅ **完成 2026-08-01** | `IntegrationsView.test.ts` **10 例**；`npm run test:unit` 379 passed | 五塊依使用順序排列。金鑰不可用時**整個表單被取代**而非 disable；憑證區塊只顯示指紋與更新時間，儲存後立刻清空輸入框（否則 token 會留在 DOM 與記憶體裡）；`pro` ＋ 無憑證就地阻擋；停用的確認文案帶既有隧道條數，「一併關閉」是**逐條回報**的獨立動作 |
| PG-11 | **每個 node 的埠轉發設定頁**（`/nodes/:id/tunnels`） | ✅ **完成 2026-08-01** | `NodeTunnelsView.test.ts` **15 例** | 三塊。第一塊（先決條件＋有效政策＋**被哪一層限制**）是本頁的價值所在，三種來源各有一例測試。清單中**沒有**「複製帳密」（只有建立對話框裡有——只有雜湊被保存，清單提供不了）；`target="_blank" rel="noopener noreferrer"`；15 秒輪詢且只在頁面可見時；`failed` 的文案來自既有 `utils/errorCatalog.ts` 而非前端硬寫 |

## 波次 5：選用

| Ticket | 標題 | 狀態 | 證據 | 備註 |
|---|---|---|---|---|
| PG-12 | iframe 內嵌與 CSP | ⛔ **不做（已決定 2026-08-01，見 D-5）** | `frame-ancestors 'none'` 在兩份 edge 設定中皆未改動 | 唯一需要動安全政策的票；換到的是「少按一次新視窗」。理由完整寫在 D-5，而不只是「沒做」 |

## 波次 6：驗證與退出

| Ticket | 標題 | 狀態 | 證據 | 備註 |
|---|---|---|---|---|
| PG-13 | traceability（23 criterion × 4）與安全審查 13 項 | ✅ **完成 2026-08-01** | `make traceability` 全綠：`criteria=405 verifiable=274 blocking=0`（+24：23 個 `FR-TUNNEL-*` ＋ `SCOPE-013.AC-01`）；`validate --level selectors` 通過（每個 `verified_by` 的測試選擇器都真的存在） | 四個 requirement ＋ `SCOPE-013` 已註冊，**145 條 primary link**；新 gate `GATE-TUNNEL-PROVIDER`（release-triggered、`environment: provider-account`）。`docs/security-review-p11.md`：13 項對抗全部有可重跑的測試或指令，無 Critical／High，四筆 Finding（F-1 Pro 三項未驗、F-2 磁碟層斷言缺、F-3 E2E 未實作、F-4 iframe 不做）。**新增兩道機械守門**：repo-wide 的 host key gate 與 SCOPE-013 的「Central 沒有代理」守門 |
| PG-14 | evidence、五份文件、fake provider stack、exit gate | ✅ **完成 2026-08-01** | `scripts/pg/evidence.sh`：**18 道 gate 執行、18 綠**，2 筆誠實 skip（`artifacts/pg/local/summary.md`）。其中新增的一道是 `tunnel-stack-check.sh`：真的把 stack 起來，14 項斷言全綠 | 五份文件齊備：`docs/runbooks/tunnel-pinggy.md`、`docs/release-note-tunnel.md`、`docs/pg-report.md`、`docs/release-checklist.md` §4.6、`docs/deployment.md` 新增一節。`scripts/pg/check-no-token-leak.sh`（四項檢查，含用 AST 讀 `audit.record` 的 metadata 鍵；已用一次刻意的洩漏驗證它會紅）。**沒有另開 `.github/workflows/pg.yml`**：兩道新 gate 分別是 pytest（host key、SCOPE-013，由 `ci.yml` 的 `pytest backend/tests` 涵蓋）與一支腳本（憑證外洩掃描，已加進 `ci.yml` 的 backend job，與既有 layout gate 同樣的形狀）。理由是它們是**永久規則而非本期場景**，放在 baseline gate 比放在階段 workflow 更難失效；另開一份只會多一份會漂移的清單 |

## 未完成項目（2026-08-01 覆核並補齊後）

十一條 exit 條件中 **10 條已滿足**；剩下的一條（第 7 條的「E2E 實跑」與「真實 provider 在 staging」）
兩半都各有替代證據但都不完整。八項判準全部有證據，其中兩項的證據來自 `PG-01` 對真實服務的實測而非
本機 stack。**沒有任何一項是「程式還沒寫」。**

| # | 未關項 | 屬於哪一條 | 缺什麼 | 現有覆蓋到哪裡 |
|---|---|---|---|---|
| 1 | 瀏覽器 rendering 斷言實跑 | exit 7 前半 | Playwright 的系統函式庫需 root（`libatk-1.0.so.0`）。這是本機唯一擋住的東西 | `tunnel.spec.ts` 已寫（三個案例）；`p2.yml` 跑整個 `tests/e2e` 目錄，因此 CI 的 chromium／firefox／webkit 都會跑到。本機以 `tunnel-stack-check.sh` 走完同一條平台路徑：**14 項斷言全綠**，含「停用時 404」「未確認被拒」「回應不含 token」「URL 形狀」「密碼只出現一次」「稽核無 URL」「關閉後沒有殘留行程」 |
| 2 | 真實 provider 在 staging 跑一次並存檔 | exit 7 後半 | staging 環境 | `PG-01` 已在本機對真實服務跑完十二項（`artifacts/pg/local/provider-verify.json`）；`GATE-TUNNEL-PROVIDER` 為 release-triggered |
| 3 | Pro 專屬三項 | exit 1、判準 #6 | 付費 token 與一次滿 60 分鐘的觀察 | 重連換新網址的**程式路徑**有兩端測試；`concurrent_budget` 預設 8 且 UI 要求依方案填寫 |
| 4 | 整台機器的憑證掃描 | 安全審查 F-2 的殘餘 | 一台可丟棄的機器 | F-2 本體已關：`TestTheCredentialIsNeverWrittenToDiskOrLogged` 量測 run 目錄與 log 兩面，並**先以一行故意的 `slog` 洩漏驗證過它會紅**；stack check 另外斷言關閉後無殘留行程 |

**判準 #5（`curl` 隧道網址取到該 port 上應用的回應）已滿足**，證據在 `PG-01`：`verify-provider.sh`
自己起一個 echo app、開一條**真實**隧道、以 basic auth `curl` 它，得到 401／401／200 並讀回 app 的
回應與 header。先前把它列為未關項是過於保守的紀錄。

**刻意的偏離（不是未完成，但要有人知道）**：

- 判準 #1 的「node 頁不顯示埠轉發入口」**沒有照字面做**。`05-…md` §2.1 後來要求相反的事：整合未啟用時仍顯示該區塊並說明原因（「使用者需要知道為什麼沒有這個功能」）。以較晚、較具體的那份為準；Tunnels API 仍一律回 404。
- `PG-12`（iframe）**不做**，理由見 D-5。因此 `frame-ancestors 'none'` 未動，`make railway-check` 的 parity gate 全綠。
- 沒有 `.github/workflows/pg.yml`：兩道新 gate 分別進了 `ci.yml`（pytest 與憑證外洩掃描），瀏覽器那一段由 `p2.yml` 既有的 e2e job 涵蓋。理由是它們是永久規則而非本期場景。

## 已落地的產物（2026-08-01）

新增：

| 檔案 | 內容 |
|---|---|
| `docs/adr/0022-third-party-tunnel-integration.md` | 決策、實測改變了什麼、補償控制與「不擋什麼」、六個被否決的替代方案 |
| `scripts/tunnel/verify-provider.sh` | `PG-01` 的十二項實測，可重跑；輸出 `artifacts/pg/local/provider-verify.json` |
| `deploy/pinggy_known_hosts` | 實測取得的 RSA 4096 host key（三個主機同一把）＋輪替說明 |
| `contracts/v1/schemas/messages/tunnel-{open,opened,id,closed,status}.schema.json`、`node-tunnel-report.schema.json` | 契約 v1.6.0 的六個 payload schema |
| `contracts/v1/fixtures/{valid,invalid}/tunnel-*.json`、`node-register-{with-tunnel,tunnel-unknown-field}.json` | 11 筆 golden fixture（4 valid ＋ 5 invalid ＋ 2 register） |
| `backend/app/db/migrations/versions/0014_node_tunnels.py`、`0015_tunnel_integration.py`、`0016_seed_tunnel_actions.py` | 三張表 ＋ `nodes` 六個回報欄位 ＋ 三個 action 的 seed |
| `backend/app/security/secret_box.py` ＋ `backend/tests/test_secret_box.py` | AES-GCM 憑證保管（16 例測試） |
| `backend/app/repositories/integrations.py`、`backend/app/services/integrations.py` | 整合設定 service（`PG-09` 的 service 層） |
| `backend/tests/db/test_tunnel_schema.py` | 22 例資料庫層保證 |
| `daemon/internal/tunnel/{provider,pinggy,supervisor}.go` ＋ 兩個 `_test.go` | 子行程監管（29 例測試，含 fake provider） |
| `daemon/internal/connection/tunnel_handlers.go` | 協定與 supervisor 之間的翻譯層、先決條件回報 |
| `daemon/internal/config/tunnel_test.go` | 10 例本機否決與 port 政策測試 |
| `daemon/VERSION` ＋ `cmd/agentd/main.go` → **0.4.0** | daemon 新增 `internal/tunnel` 整包、一個 config 區塊、三個協定 handler、installer 的 `known_hosts` 佈署與 metrics —— 向後相容的能力新增，依 `004cede` 的先例走 minor。兩份副本一起動（`TestVersionMatchesTheVersionFile` 擋漂移）。release note 因此寫明「需要 agentd 0.4.0 以上」，舊版 daemon 在 UI 上顯示為「不支援、請升級」而非「失敗」 |
| `backend/app/repositories/tunnels.py`、`backend/app/services/tunnels.py` | tunnel 資料層與服務層（`effective_policy`／`derive_state`／`apply_status`／三條額度） |
| `backend/app/api/http/tunnels.py`、`backend/app/api/http/integrations.py` | 九個端點（五個 `/api/tunnels`、兩個 per-node、四個整合設定中的兩個為 credential） |
| `backend/tests/test_tunnel_policy.py`（18 例）、`backend/tests/db/test_tunnels_api.py`（34 例） | 三層政策的純函式測試與 API 層的完整行為 |
| `frontend/src/views/IntegrationsView.vue`、`NodeTunnelsView.vue` ＋ 兩個 `.test.ts`（10／15 例） | `PG-10`／`PG-11` 兩個頁面 |
| `docs/security-review-p11.md` | 13 項對抗、每項有可重跑證據；「沒有任何控制能解決的八件事」；四筆 Finding |
| `docs/runbooks/tunnel-pinggy.md` | 五段判斷各有可下的指令、host key 輪替、金鑰與 token 的保管與輪替、七件會讓人意外的事 |
| `docs/release-note-tunnel.md` | 兩個讀者：平台管理員（啟用前四項準備、啟用的意義）與 node 擁有者（升級不啟用任何東西、如何一票否決） |
| `docs/pg-report.md` | 交付內容、實測推翻的三項假設、八項能力缺口、五筆未關項與歸屬 |
| `scripts/pg/evidence.sh`、`scripts/pg/check-no-token-leak.sh`、`scripts/pg/audit_metadata_keys.py` | evidence pack（18 gate）與憑證外洩靜態掃描（四項檢查） |
| `daemon/cmd/faketunnelprovider`、`daemon/cmd/faketunnelapp` | stand-in provider（印出 `.example.invalid` 的網址、可模擬 host key 失敗／不印 URL／立刻退出）與被轉發的 app。**RFC 2606 保證 `.invalid` 不可解析**，所以 E2E 不可能誤打到真實服務 |
| `scripts/pg/tunnel-stack-check.sh` | 對跑起來的 stack 走完整條平台路徑的 14 項斷言，**不需要瀏覽器**。存在的理由：瀏覽器那一段在無 root 的機器上根本起不來，而「起不來」不該與「通過」同一個顏色 |
| `frontend/tests/e2e/tunnel.spec.ts` | 三個瀏覽器案例（啟用＋只顯示指紋、建立→網址→關閉、sidebar）。**不開啟那個網址**：斷言的是連結被正確呈現（`target="_blank"`、`rel="noopener noreferrer"`），開啟它等於在測服務商 |
| `daemon/internal/tunnel` 的 `TestTheCredentialIsNeverWrittenToDiskOrLogged` | 安全審查 F-2：走訪 run 目錄的每個檔案並攔截 slog，斷言憑證與密碼都不在其中。已用一行故意的洩漏驗證它會紅 |

修改：`research/prd.md`（§8.10 四個 requirement、`SCOPE-013`、`SEC-008`、`FR-CONN-006.AC-09`／**AC-10**）、`research/tech.md`（§8.0、§12.2）、
`contracts/v1/schemas/control-envelope.schema.json`、`contracts/v1/fixtures/manifest.json`、`contracts/CHANGELOG.md`（1.6.0）、
`backend/app/{settings,db/models,services/rbac,services/audit,api/error_catalog}.py`、`scripts/p4/render_error_catalog.py`、
`docs/{error-catalog,permission-matrix}.md`（重新產生）、`frontend/src/{protocol/decode.ts,api/dto.ts,utils/errorCatalog.ts,utils/auditActions.ts}`、
`daemon/internal/{config/config,protocol/codec,connection/connection,install/plan,metrics/metrics}.go`；
本輪另修改：`backend/app/{main,api/ws/nodes,api/http/schemas,services/nodes,services/authz,repositories/audit}.py`（路由註冊、`/readyz` 的 `tunnel_integration`、`tunnel.status` 分派、node 回報落地、四個授權判定、稽核存在性查詢）、
`traceability/{requirements,links,gates}.json` 與 `docs/traceability/*`（重新產生）、`docs/{release-checklist,deployment}.md`、
`frontend/src/{router/index.ts,components/layout/AppLayout.vue,views/NodeDetailView.vue,api/client.ts,utils/time.ts}`。

## 實作中修掉的三個自己寫出來的缺陷（測試先抓到）

| 缺陷 | 症狀 | 修法 |
|---|---|---|
| `Stop()` 只送信號、不 reap | 每條被中止的隧道留一個殭屍行程；`signal 0` 偵測不到（殭屍仍接受信號），所以 `Stop` 還會白等滿 2 秒才 SIGKILL | `Stop` 現在會 `Wait`。`Start` 的失敗路徑（憑證被降級、拿不到 URL）本來就沒有 supervisor goroutine 在後面，那些才是真正會累積殭屍的路徑 |
| `node.register` 新增 `tunnel` 欄位，但 schema 與 Go struct 都是嚴格模式 | **每一次註冊都會變成 `INVALID_MESSAGE`** —— 也就是加了這個回報等於讓所有 node 無法連線 | 新增 `node-tunnel-report.schema.json`、兩個 schema 引用它、Go 的 `registerFields`／`runtimeStatusFields` 加欄位與 `validTunnelReport`，並補一組 valid／invalid fixture（invalid 那筆是「回報裡塞 credential」） |
| `tunnelReport()` 在註冊路徑上做 5 秒 TCP 連線 | 每次重連都在控制連線的交握前面卡最多 5 秒，而那個值本來就會過時 | 改成背景探測 + 5 分鐘快取；第一次註冊回報 `false`（＝還沒檢查），由 `tunnel_reported_at` 讓 UI 分辨「沒準備好」與「還不知道」 |

前兩個都是**只有寫測試才會發現**的：第一個靠 `TestStopEndsTheProcess`，第二個靠 manifest-driven 的契約測試。

## 本輪（PG-07…PG-14）修掉的四個自己寫出來的缺陷

| 缺陷 | 症狀 | 修法 |
|---|---|---|
| 稽核 metadata 的鍵取名 `credential_fingerprint` | redaction pass 會遮蔽任何鍵名含 "credential" 的字串，所以指紋被存成 `***` —— 也就是**這一筆稽核的用途被自己的安全機制消掉了**。測試先抓到 | 鍵改為 `fingerprint`（與 `integration.credential_set` 一致），並在程式與 `check-no-token-leak.sh` 都寫下理由。**沒有動 redaction 規則**：它的行為是對的 |
| `TunnelService.list` 與型別註解 `list[str]` 撞名 | 類別內的 `list` 方法遮蔽了 builtin，`mypy` 直接把 `allowed_ips: list[str]` 判為無效型別 | 該處改用 `Sequence[str]` 並註明原因（比改方法名小，且 `list` 這個方法名與 `SessionService` 一致） |
| `db/conftest.py` 的清理清單沒有三張新表 | `tunnel_integration` 留下的列參照 `users`，於是**下一個測試**的 `DELETE FROM users` 撞 FK，而失敗訊息是「duplicate username」——與真正的原因隔了好幾個測試 | 三張表加入 `_CLEANUP_TABLES`（children 先於 parents），並在註解寫下這個症狀 |
| Node 詳情頁的埠轉發摘要把「讀不到」畫成「沒有隧道」 | 摘要載入失敗時仍顯示 `0`，那是一個這一頁沒有驗證過的斷言 | 新增 `error` 分支與重試；同時修好既有 `NodeDetailUpdate.test.ts` 的 router（它沒有新路由，`RouterLink` 直接在 setup 中拋錯——**十個既有測試同時變紅，看起來像大災難，實際是測試 fixture 少兩行**） |

## 實作中觸發的三條既有守門規則（都是對的，都改變了實作順序）

| 守門 | 它擋住什麼 | 處置 |
|---|---|---|
| `test_every_protocol_error_code_is_documented` | wire enum 內有碼、catalog 沒有 → 使用者會收到一個沒有原因也沒有下一步的錯誤 | 六個 wire 碼與契約同一批落地 |
| `test_the_catalog_documents_nothing_fictional` | catalog 有碼、沒有人拋 → 記載了一個永遠看不到的錯誤 | 三個 Central-only 碼延後到 `PG-07`／`PG-09` |
| `test_every_action_is_enforced_somewhere` ＋ `test_every_relay_budget_is_published` | 宣告了 action／逾時預算卻沒有強制點或沒有 PRD 條文 | 三個 action 暫列 `UNENFORCED_ACTIONS`（**強制點落地時測試會強迫移除**）；`tunnel_open_timeout_seconds` 以 `FR-CONN-006.AC-09` 公布並登錄到 `PUBLISHED_BUDGETS` |

這三條合起來的意思是同一句話：**這個 repo 不允許「先宣告、之後再接上」的懸空狀態存在而沒有記錄。**

## 實作中發現的既有問題（不屬本期範圍，但要有人知道）

| 問題 | 證據 | 建議 |
|---|---|---|
| `backend/tests/test_releases.py::test_publishing_a_release_is_picked_up_without_a_restart` 是**既有的** flake，約三次失敗兩次 | 在**未修改**的樹上（`git stash` 後）連跑三次得到 fail／fail／pass | ✅ **已修（2026-08-01，本輪）**：測試在第二次發佈後把目錄與 `checksums.txt` 的 mtime 往前推一秒，因為斷言的對象是**快取鍵**而不是檔案系統的時間粒度。連跑五次全綠。修它的理由是 exit 條件要求「不得有任何測試失敗」，而一個隨機變紅的 gate 會掩蓋真正的失敗 |
| `make test-db` 只設 `CLIORA_TEST_DATABASE_URL` 時，`test_audit_coverage.py` 有兩例失敗 | 在**未修改**的樹上重現；log 中是 `audit_write_failed` | 不是缺陷：`AuthzDenialAuditMiddleware` 刻意用自己的 session 寫稽核（好讓它在請求 rollback 後仍留下紀錄），那條路徑走的是 `CLIORA_DATABASE_URL`。兩個變數都設就綠。已寫進本檔開頭的環境事實表，因為它看起來很像本期的 bug |

## 已知會在實作中遇到的事（先寫下來，避免被當成漏掉）

1. **`-N` 與 remote options 互斥**（`03-…md` §2.1）。Pinggy 的選項是以「遠端命令」形式傳遞，而 `-N` 表示不執行遠端命令。第一次組命令的人一定會撞到。
2. **退出分類靠 stderr 字串比對**（`03-…md` §2.4）。這是整合第三方無法避免的脆弱點；分類失敗的預設是「可重試但計入上限」，不是無限重試。
3. **token 在 `ssh` 的 argv 裡**，所以同一台機器上同 uid 的行程讀得到。已列入安全審查的紀錄項，不是可修的缺陷（provider 的介面如此）。
4. **`rotate-password` 會換掉 URL**。使用者的心智模型是「改密碼」，實際是「重開隧道」。UI 不講清楚就會有人以為舊網址還能用。
5. **免費版每小時換網址**。任何把網址寫進文件、貼進 Slack 的行為都會在一小時後失效 —— UI 必須先講（D9）。
6. **平台無法回答「誰存取了這個預覽」**。這是能力缺口而非隱私設計，`SEC-006` 的敘述要補這一句（`06-…md` §1.1）。
7. **iframe 與 basic auth 天生互斥**（Chrome 不在 cross-origin iframe 顯示 auth 對話框）。這是 `PG-12` 預設不做的主要原因之一。
8. **「為什麼不能建立」有三層可能的原因**（整合／per-node／node 本機）。不在 UI 標明是哪一層，使用者只能一層一層試 —— `05-…md` §2.2 (1) 的那一塊是本期最容易被做成裝飾的功能。
9. **停用整合不會關掉既有隧道**（`04-…md` §0.2）。把它做成「一個開關關掉全部」會產生一個可能部分失敗卻看起來成功的動作。
10. **金鑰遺失沒有還原路徑**：重新輸入 token 而不是解密。這一句要在 runbook 的第一段，不是附註。
