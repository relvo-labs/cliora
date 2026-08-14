# 08 — 實作進度與證據

本檔隨實作更新；「證據」欄只填**實際跑過的指令與其輸出位置**，不填計畫中的測試。
沿用 `plan/17/09`／`plan/18/09`／`plan/19/09` 的體例：
**這裡記的是實際發生的事**，與計畫不同時，**以這裡為準並回寫計畫**。

**狀態：十三張 ticket 全部完成（2026-08-13）。**

```
make check                                  綠
scripts/sc/gates.sh                         10/10
backend/tests/db  (PostgreSQL)              531 passed
daemon  go test ./...                       17 packages（含 -race）
contract（Python／Go／TypeScript 三邊）       201 / 180 passed
alembic upgrade → downgrade 0032 → schema   與 SC-00 基線逐位元組相同
OpenAPI（旗標關閉）                          只新增三條路徑，且三條都 404
```

**剩下的都是人的事**（§4）：ADR 0032 仍是 `proposed`（閘門二是人的核准）、
traceability 仍是 `proposed`、Traqora 實跑、以及三項需要真機的驗證（§7）。

## 0. 待確認項目

**這一節是開工前唯一要讀的東西。** 每一項都寫了「不同意的話會怎樣」。

### 0.1 A 類 — 會擋開工（**0 項，已於 2026-08-13 裁決結清**）

---

**☑ D5／D5b — git 憑證的下放由環境變數控制，預設不開放**

> **裁決（2026-08-13）**：平台下放 git 憑證涉及較廣。**可以實作，但由環境變數控制、
> 預設不開放。現階段以 node 端手動配置為準，手動配置這部分系統不用管，
> 交給 node owner 自行處理。**

| | |
|---|---|
| **落地** | `CLIORA_GIT_SECRET_DELIVERY_ENABLED`，預設 `false`（D5b）。關閉時：git kind 的機密**建立被拒**、`auth_kind` 只能 `ambient`、`spec.secrets` 不含 git kind、**D9 的隔離不生效**、clone 與 push 用機器的憑證 |
| **原本的 A 類爭議因此消失** | D5 的 `kind` 分流照做，但它現在描述的是一條**預設關閉**的路徑；代價（Agent 不能用**平台的**憑證 fetch／push）只在有人主動打開它時才發生。**2026-08-10 ② 給的 git 自由在預設組態下完整保留** |
| **要一起接受的代價** | **平台開始 push 了，而預設路徑上它用的憑證平台管不到**——「可撤銷」在那條路徑上不成立。五條硬約束仍然完整適用（它們約束的是**推什麼**）。這一句要進 ADR 0031 amend、安全審查 §3a 與 release note |
| **連帶改動** | D9 的語意（隔離只對真的收到平台憑證的 run 生效）、出口條件 4b／4d／6／6b–6g、`04b-…md` 分成兩半、`06-…md` 的兩處「⊘ 停用不隱藏」、M-AR-6 降級 |

---

### 0.2 B 類 — 確認即可（4 項）

| ☐ | 項目 | 內容 | 不同意的話 |
|---|---|---|---|
| ☐ | **D2** | `run.offer` 留在 64 KiB；`context` 上限 65536 → 32768；Central 加出口方向的大小檢查，超過就**釋放認領** | 若不改 `context` 上限，機密的預算只剩下不到一半，`maxItems: 8` 要降到 3–4。若不加 Central 的檢查，`plan/18` D2 描述的那個症狀（訊息不見了但沒有錯誤）會從潛在變成常見 |
| ☐ | **D4** | 主金鑰的啟動驗證是**條件式**的（綁 `agent_runs_enabled`） | 照規劃的字面做成無條件，會讓每一個沒在用 V2 的既有部署升級後起不來，而那些部署裡一筆機密都沒有 |
| ☐ | **D21** | `SC-00` 先 cut `agentd 0.9.0`，本期發 `0.10.0` | 直接發 0.10.0 省一個 commit，但 `node_update` 的版本序會跳過一個**真的可以部署的組態**（有 runner、沒有機密），而本期的相容性測試會失去一個真的舊版本可對 |
| ☐ | **`SC-07a` 的位置** | tag 上報（節點半的一小塊）排在 Central 的比對**之前** | 不同意就等於接受本期的每一次驗收都用 SQL 手改 `agent_runners.labels` 完成，而上線第一天每一張宣告 tag 的卡片都沒人領（`run_handlers.go:52` 寫死 `labels: []`） |

### 0.3 C 類 — 開工時決定，計畫已給預設值（5 項）

| ☐ | 項目 | **計畫的預設** | 什麼情況要改 |
|---|---|---|---|
| ☑ | `isolate_ambient_credentials` 的**值** | **A（取代），且只對真的收到平台憑證的 run 生效** | **已不需決定**：2026-08-13 裁決讓 git 憑證預設不下放，原本的爭議（收不收回 Agent 的 git 自由）在預設組態下不存在。M-AR-6 隨之降級為上線後觀察 |
| ☐ | 機密單值上限 | **8 KiB** | M-SC-1 量出 RSA-4096 之外還有更大的合法輸入 |
| ☐ | `maxItems` | **8** | 同上；或 M-SC-1 顯示典型卡片宣告超過 4 個 |
| ☐ | Redactor 走多深 | **遞迴走整個 payload** | M-SC-2 顯示終端延遲 p95 超過基線 20%，退成三個已知欄位 |
| ☐ | SSH ＋ 缺 provider_token | **提示，不擋** | V2.4 開放 `pull_request` 時改為擋下（`05-…md` §3.2） |

## 1. Ticket 狀態

| Ticket | 標題 | 狀態 | 證據 |
|---|---|---|---|
| `SC-00` | 基線擷取 ＋ M-SC-1／M-SC-2 ＋ **cut `agentd 0.9.0`** | ✅ | 六份基線在 `artifacts/sc/local/baseline/`（§1.1）；`daemon/VERSION` ＝ `0.9.0`，`TestVersionMatchesTheVersionFile` 綠；M-SC-1 已量（§1.2）。M-SC-2 排在 `SC-07` |
| `SC-01` | ADR 0032、PRD §8.14、skill、traceability、**過期承諾清單** | ✅ | `docs/adr/0032-…md`（**proposed**，等閘門二）；PRD §8.14 十一條 FR-RUNENV、58 個 AC；`traceability/requirements.json` 九筆 `proposed`，`scripts/trace validate --level static` ＋ `render --check` 綠；skill 的 Git automation 那一句改寫；**九處過期註解逐處改對**（§3 第 4 條） |
| `SC-02` | ADR 0031 增補：git 送回 | ✅ | 附在 `0031` 之後：A1 兩半的相反預設、A2 五條硬約束、A3 憑證（預設關閉）、A4 分支來源 ＋ Alternatives |
| `SC-02b` | ADR 0029 增補：tag 派工 | ✅ | 附在 `0029` 之後：B1 兩層、B2 五條件、B3 GitLab 語意、B4 比對在 Central、B5 tag 不是授權 |
| `SC-03` | migration `0033`／`0034` ＋ 模型 | ✅ | `0033_project_secrets`（一張表 ＋ 四處新增欄）、`0034_seed_secret_action`；**37 張表**；`downgrade` 回 `0032` 與基線**逐位元組相同**；seed 重跑 `UPDATE 0`（冪等）；Admin 25 個動作 |
| `SC-07a` | 🆕 tag／`run_untagged`／`accept_secrets` 的設定與上報 ＋ `doctor` | ✅ | `RunnerConfig` 三個欄位（後兩個是指標型別）、`TagList()` 排序去重且**永不 nil**、`runnerRegisterPayload` 改讀設定、`doctor` 三行；`go test ./...` 17 個套件全綠 |
| `SC-04` | Secret store ＋ API（**安審 §1**） | ✅ | `security/secret_envelope.py`（`secret_box.py` 零 diff）、`services/secrets.py`、`api/http/secrets.py` 五條端點、`Settings` 條件式驗證；`test_project_secrets.py` **21 條**；安審 §1 已寫 |
| `SC-05` | 五條件資格判定、兩個查詢共用述詞、dispatch 409、反向查詢 | ✅ | 三個述詞、兩個查詢都改、`WaitingReason` 帶最小缺集、四種 409；`test_tag_dispatch.py` **12 條**；`GATE-SC-TAG-BOTH-QUERIES` 綠 |
| `SC-06` | contract v1.12.0 ＋ fixtures ＋ 訊框大小檢查 | ✅ | `spec.secrets`／`spec.branch`／`delivery: branch`／`authenticating` phase／`runner.register` 兩個布林；`context` 65536 → **32768**；**21 個新 fixture**（6 valid ＋ 15 invalid，含「`secrets` 出現在 `run.accept`／`run.complete`」兩條）；Central 出口方向的大小檢查 ＋ 釋放認領；CHANGELOG 1.12.0 |
| `SC-07` | `agentd` 0.10.0 機密面：`kind` 分流、去識別、ambient 隔離 | ✅ | `runner/secrets.go`：`SortSecrets`／`ChildEnv`／`Redactor`／`IsolateAmbient`；Redactor 掛在 `send` 上；`secrets_test.go` **6 條**，含「run 目錄全域搜尋不含任何機密值」 |
| `SC-07b` | git 面：helper、`ssh-agent`、分支、push（**安審 §3**） | ✅ | `gitfetch/push.go`（五條硬約束）＋ `credentials.go`（`GIT_ASKPASS` helper、`ssh-agent`）；`push_test.go` **7 條**，含**對真的 bare 遠端推一條 `cliora/` 分支**與四種拒絕；`agentd` cut **0.10.0** |
| `SC-08` | 前端六處 | ✅ | Agents 頁（tag／兩個宣告／授權邊界）、`ProjectSecrets.vue`、Repository 的 ⊘ 停用、卡片的 tag／機密與**打錯字提示**、**enrollment 文案**、Run 詳情的機密名稱。`AgentsView` 12 條 ＋ `ProjectSecrets` 7 條 ＋ `EnrollmentView` 2 條 |
| `SC-09` | 驗證、gate、安審定稿、release note | ✅ | `scripts/sc/gates.sh` **10/10**；`docs/security-review-v23.md` 三節；`docs/release-note-secrets-and-dispatch.md`；`deploy/railway/env.md` 三個新變數 |
| — | **合併提案** | ⬜ **待人工** | 條件全綠只是取得提案資格，不是核准 |

### 1.1 `SC-00` 的基線

全部取自 **`94ffc92`**（2026-08-13T11:38:16+00:00），一律在 `artifacts/sc/local/baseline/`。
擷取當下未提交的路徑只有 `research/02/`、`plan/20/` 與擷取器本身（`scripts/sc/`），
全部是文件，**證得出來不影響下面任何一份**——所以用了擷取器自己的
`AR_BASELINE_ALLOW_DIRTY=1`，而那些路徑被寫進 `COMMIT`。

| 檔案 | 內容 | 狀態 |
|---|---|---|
| `COMMIT` | `94ffc92` ＋ 時間 ＋ 未提交路徑清單 | ✅ |
| `openapi-flags-off.json` / `-on.json` | 347 846 bytes，**兩份逐位元組相同**（`cmp` 綠）——那個「相同」本身是要守的性質 | ✅ |
| `schema.txt` | **36 張表**、`0032_runner_pressure`（計畫原寫 32，見 §3 第 1 條） | ✅ |
| `contract-fixtures.txt` | 151 行 ＝ 150 個檔 ＋ `manifest.json` | ✅ |
| `frontend-routes.txt` | 19 條路由 | ✅ |
| `terminal-latency.json` | 50 samples：**p50 0.288 ms／p95 1.242 ms**（min 0.133／max 5.411／mean 0.530） | ✅ |

擷取器：`scripts/sc/capture-baseline.sh`，**它只是 `scripts/ar/capture-baseline.sh`
的一層 `BASELINE_OUT` 覆寫**（§3 第 2 條）。

```bash
AR_BASELINE_ALLOW_DIRTY=1 \
CLIORA_DATABASE_URL=postgresql+asyncpg://cliora:cliora@127.0.0.1:5432/cliora_sc_baseline \
  scripts/sc/capture-baseline.sh
CLIORA_DATABASE_URL=…/cliora_sc_latency AR_BASELINE_ALLOW_DIRTY=1 \
  scripts/e2e/run-stack.sh scripts/sc/capture-baseline.sh --latency-only
```

### 1.2 `SC-00` 的兩項量測

| 量測 | 狀態 | 結論 | 原始資料 |
|---|---|---|---|
| **M-SC-1** 機密的實際大小 | ✅ **已量** | 最大的合法輸入是 **RSA-4096 私鑰 3 369 bytes**；ed25519 只要 **399**（8.4 倍差距）；fine-grained PAT **93 字元**。**單值上限 8 KiB／`maxItems` 8／`context` 32768 三個值定案** | `09-…md` §1.2 |
| **M-SC-2** 去識別的成本 | ◐ **未量** | 實作完成（Redactor 走整個 payload），**但成本未量**。量測方法已因 `SC-00` 的發現改寫（§3 第 3 條），而執行它需要一次 run 全速輸出——與 §7 的四項同一台機器。**在量到之前不要把 Redactor 縮成三個欄位**：退路存在，但預設是走全部，因為哪些欄位是自由文字會隨 contract 成長而變 | |

（**M-AR-6** 原本是第三項且擋 `SC-02`／`SC-07b`；2026-08-13 裁決之後降級為
上線後觀察，見 `09-…md` §1.1。）

## 2. 出口條件

24 條，逐條見 [`07-verification-and-exit.md`](./07-verification-and-exit.md) §5。

| # | 條件 | 狀態 | 證據 |
|---|---|---|---|
| 1 | 任何 API 都讀不回機密的值（schema ＋ 實際回應） | ✅ | `GATE-SC-NO-SECRET-IN-RESPONSE` ＋ `test_no_endpoint_returns_a_value`（五條端點的原始 bytes） |
| 1b | 主金鑰四種壞值 → 拒絕啟動並指名；旗標關閉時照常啟動 | ✅ | `test_master_key_is_required_only_when_the_runner_layer_is_on`（4 × 2 案例） |
| 1c | 輪替只重新包裝 DEK，密文逐位元組未變；舊版本仍可解 | ✅ | `test_rotating_the_master_key_rewraps_the_dek_and_leaves_the_ciphertext` |
| 2 | 機密值出現在輸出時平台收到 `***` | ✅ | `TestRedactorWalksAWholePayload`（含 `message`／`summary`） |
| 2b | git 錯誤訊息裡的機密也被替換 | ✅ | 同上；Redactor 掛在 `send` 而不是 log sink |
| 3 | `accept_secrets: false` 的 node 永不被 offer 需要機密的卡 | ✅ | `test_a_node_that_refuses_secrets_is_never_offered_a_card_with_any` |
| 3b | tag 比對成立（超集，兩個方向） | ✅ | `test_a_runner_with_more_tags…` ＋ `test_a_runner_missing_one_of_the_cards_tags…` |
| 3c | `run_untagged: false` 與 `true` 的兩台一起跑一次 | ✅ | `test_a_reserved_runner_and_an_ordinary_one_sort_two_cards_between_them` |
| 3d | 指定 tag 不符 → 409 指名缺哪幾個，且不入佇列 | ✅ | `test_naming_a_runner_that_lacks_a_tag_is_refused_and_says_which` |
| 3e | 湊不齊 tag 時說得出缺什麼（最小缺集） | ✅ | `test_an_unclaimable_card_says_which_tags_are_missing` ＋ `…smallest_one_not_the_intersection` |
| 3f | register 未帶兩個布林時視為 `true` | ✅ | `test_an_absent_declaration_is_read_as_permissive`（不依賴版本號） |
| 3g | 授權邊界的誠實性（三處畫面斷言） | ✅ | `AgentsView.test.ts`（tag 格無鎖頭／授權；文案含機密、不含「V2.3 起提供」）＋ `EnrollmentView.test.ts` |
| 3h | allowlist 外 vs 尚未建立，兩種不同的拒絕 | ✅ | `test_agent_api.py` 兩條 |
| 4 | `source: repo` ＋ `delivery: branch` → `cliora/<card>-<seq>` | ✅ | `TestPushSendsTheBranchToARealRemote`（真的 bare 遠端） |
| 4b | Traqora 上驗 `base_branch: main`，預設組態 | ⬜ **待人工** | 需要網路與正式 repo（§4） |
| 4b2 | 旗標開啟時 PAT 與 SSH 各測一次 | ◐ | PAT 對 **github.com** 真的認證過一次（失敗路徑，見 6b）；SSH 的 agent 與 host key 已驗。**缺的只有「用真憑證推上去一次」**，那需要別人 repo 的 deploy key |
| 4c | `existing_branch` 不在命名空間 → dispatch 當下拒絕 | ✅ | `TASK_BRANCH_NOT_DELIVERABLE`（`runs.py` 第 ② 步） |
| 4d | 預設組態的完整性（四個否定 ＋ 一個肯定） | ✅ | `test_git_kinds_are_refused_while_delivery_is_disabled`、`TestFetchEnvIsUnchangedWithoutAPlatformCredential`、`TestIsolationOnlyApplies…` |
| 5 | `source: none` → 沒有 `repo/` | ✅ | V2.2 回歸，`rundir_test.go` |
| 6 | 四種推送違規全部在 daemon 內被拒，git 從未執行 | ✅ | `TestPushRefusesEverythingOutsideTheNamespace`（目錄根本不是 repo，所以「拒絕發生在執行前」是這條測試的形式） |
| 6b | PAT 不出現在四處 | ✅ | `TestAPatNeverSurfacesInTheURLTheReflogArgvOrAnError` —— 對 **github.com 真的送出一次帶 token 的認證**並失敗，斷言 token 不在錯誤訊息、不在 argv、helper 檔案不含它、且帶憑證的 URL **不可表示**（後者正是 `remote -v` 與 reflog 那兩處所依賴的性質） |
| 6c | 私鑰從未落檔、`ssh-agent` 不殘留、未知 host 被拒 | ✅ | `TestTheAgentHoldsTheKeyAndTheKeyNeverReachesTheRunDirectory`（真的 `ssh-agent`：`ssh-add -l` 看得到那把 key、run 目錄裡沒有任何私鑰、`Close()` 之後 socket 與**行程都不在**）＋ `TestAnUnknownHostIsRefusedRatherThanTrusted`（空的 known_hosts 對真的 github.com → host key verification failed） |
| 6d | SSH 的開 PR 後果在設定畫面說得出 | ◐ | 後端五條驗證已寫；**Repository 表單的 SSH 提示未做**（§7） |
| 6e | 缺 git 憑證仍然秒級失敗 | ✅ | `TestFetchEnvIsUnchangedWithoutAPlatformCredential`（`GIT_TERMINAL_PROMPT=0` 與 `/bin/false` 都在） |
| 6f | git kind 不出現在子程序環境 | ✅ | `TestKindDecidesWhereAValueGoes` |
| 6g | 隔離只對收到平台憑證的 run 生效 | ✅ | `TestIsolationOnlyAppliesWhenAPlatformCredentialArrived`（同一條測試的兩半） |
| 7 | 保留期清理；第二次 run 仍是淺 clone | ✅ | V2.2 回歸 |
| 8 | run 目錄與 allowed root 的姿態回報 | ✅ | V2.2 回歸（`dedicated`） |
| 9 | 配額用盡停止 poll 並回報原因 | ✅ | V2.2 回歸 |
| 10 | 刪除機密後下次派工被 409 指名；進行中不受影響 | ✅ | `test_delete_is_soft…` ＋ `TASK_SECRETS_MISSING` |
| 10b | 下放稽核記名稱、不含值／長度／指紋 | ✅ | `materialise` 的 payload ＋ `test_no_endpoint_returns_a_value` 掃 `/api/audit` |
| 11 | 旗標關閉：完整回歸全綠 | ✅ | `make check` 綠；OpenAPI 只新增三條路徑且三條 404 |
| 12 | 訊框過大時釋放認領並留下說明 | ✅ | `test_an_oversized_offer_releases_the_claim_instead_of_vanishing` |

**22 條完成、2 條部分、1 條待人工。**

> ⚠️ **這張表在 2026-08-13 修正過一次，而修正的理由值得記著。**
> 上一版把 6b／6c／4b2 標成「需要一台我們沒有的機器」。
> **那個判斷是錯的**：`ssh-agent`、`ssh-add`、`sshd` 都裝著，outbound ssh 也通，
> 而 `StrictHostKeyChecking` 當場就拒絕了未知 host。真正缺的東西比看起來小得多——
> **只是別人 repository 的一枚憑證**。把「缺一枚憑證」說成「缺一台機器」，
> 會讓三條本來今天就驗得完的條件被無限期擱著（§3 第 15 條）。

## 3. 實作中發現、與計畫不同的事

沿用 `plan/18/09` §3 的形式：計畫寫的／實際做的／為什麼。

1. **`schema.txt` 是 36 張表而不是計畫寫的 32。**
   `01-…md` §1 寫「預期 32 張表」，那是**把 migration 編號當成表數**的筆誤：
   AR 基線 28 張（到 `0028`）＋ V2.2 新增的 8 張（`agent_runners`、
   `project_repositories`、`task_runs`、`run_logs`、`task_messages`、
   `task_artifacts`、`task_artifact_blobs`、`run_tokens`）＝ 36。
   `0033` 之後應該是 **37**（只多 `project_secrets`）。兩處已更正。

2. **不為 `SC-00` 另寫一支擷取器，改讓 AR 的那支接受 `BASELINE_OUT`。**
   計畫寫「同一批擷取器，同一個目錄慣例」，而那支腳本把 `OUT` 寫死。
   複製 60 行的代價是**兩份會在其中一份被修好的第一時間開始分歧**，
   而一個沒人信的基線比沒有基線糟。所以 `scripts/ar/capture-baseline.sh`
   改一行（`OUT="${BASELINE_OUT:-…}"`），`scripts/sc/capture-baseline.sh` 是三行的 wrapper。
   ⚠️ **這是閘門一「基線完成前不得動任何程式碼」的一個例外**，而它與 V2.2 的先例一致：
   AR 基線的 `COMMIT` 裡記著的未提交路徑就是「`scripts/ar/`，即擷取器本身」。
   髒樹覆寫的環境變數**刻意沿用 `AR_BASELINE_ALLOW_DIRTY`**：
   它是擷取器自己的開關，改名會讓一個行為有兩個名字。

3. 🔴 **終端延遲的兩次基線相差 27%，而 M-SC-2 的判準是 20%。**
   同一台機器、同樣的 idle stack：V2.2 量到 p95 **0.980 ms**，本期量到 **1.242 ms**。
   兩次都沒有 run 在跑，所以那 27% **全部是雜訊**——而 `09-…md` §1.3 的判準
   （「p95 不比基線高 20% 以上」）整個落在雜訊底下。
   **這不是一個要調閾值的問題，是一個量測方法的問題**：
   `max` 那一格更說明狀況（1.489 → 5.411），單次 50 samples 的 p95 對尾端離群值太敏感。
   M-SC-2 的做法因此改為：**同一輪連續量三次取 p50 的中位數，
   並且在「有 run 在跑」與「沒有 run」兩種情況下各量三次**，比較的是那兩組的中位數。
   詳見 `09-…md` §1.3 的修訂。

**開工前已知、計畫已據以修正的六處**（它們不是「實作中發現」，
但列在這裡讓下一個人知道計畫與上游規劃為什麼不同——完整表在 `README.md`）：

1. `daemon/VERSION` 是 `0.8.0`，V2.2 的版本從未 cut（D21）。
2. `run_handlers.go:52` 的 `labels` 寫死成 `[]string{}`（D13）。
3. daemon 裡沒有 `Redactor`（D6）。
4. `run-spec.schema.json` 的 `context` 上限 65536 ＝ 整個訊框預算（D2）。
5. Central 沒有出口方向的訊框大小檢查（D2）。
6. 九處程式註解仍承諾 `project_agents`（D18、`01-…md` §5b）。

4. 🔴 **`GIT_ASKPASS` 之外，`labels` 也曾經是一個死欄位——而那件事在兩層之外還有第三層。**
   計畫記了 daemon 端寫死 `[]string{}`。實作時發現 Central 端另有一處把它變成可寫的：
   `EDITABLE_RUNNER_FIELDS` 含 `labels`，所以 `PATCH /api/agents/{id}` 可以改它。
   在 tag 只是裝飾時那是無害的虛榮；tag 開始決定派工之後，它是一個
   **node 下次 `runner.register` 會靜默覆蓋掉的第二真實來源**。已移出該集合，
   `UpdateAgentRequest` 的欄位一併拿掉（ADR 0029 amendment B5）。

5. 🔴 **依賴覆寫到不了 `get_settings()` 的直接呼叫者。**
   `projects_enabled` fixture 用 `app.dependency_overrides[get_settings]` 注入設定，
   而 `secret_envelope` 像 `secret_box` 一樣直接呼叫 `get_settings()`——**覆寫到不了它**。
   症狀是每一條 secrets 路由回 503 `SECRET_KEY_MISSING`，而覆寫看起來完全正確。
   處置照抄 `test_tunnels_api` 的既有作法：fixture 同時設環境變數並 `cache_clear()`。

6. 🔴 **金鑰輪替的第一版讓輪替之後的舊資料再也打不開，而是自己的測試抓到的。**
   `_key_for_version` 原本寫成「版本等於 `CURRENT_KEY_VERSION` 就用當前金鑰」。
   那在第一次輪替之前都對，之後**當前金鑰已經是新的那一把**，於是每一列
   輪替前的資料都解不開——而症狀是一個看不懂的解密失敗。
   改成**先查版本化的環境變數，查不到才回落當前金鑰**，並把「當前版本」
   從模組常數換成設定值 `CLIORA_SECRET_MASTER_KEY_VERSION`。
   ⚠️ 這是本輪唯一一個「照計畫寫會壞掉」的地方，而計畫寫的是對的形狀、錯的實作細節。

7. 🔴 **「沒有任何回應回傳值」的第一版掃到了請求 schema。**
   它走遍 OpenAPI 的每一個 schema，於是在 `CreateProjectSecretRequest` 上失敗——
   而那當然帶著值，它就是拿來存值的那個請求。
   **一個分不出請求與回應的守衛，最便宜的修法是把使用者要打字的欄位改名**，
   而那比沒有守衛更糟。改成只走**從 responses 可達**的 schema（含遞迴），
   並加一條「它真的走到了 `ProjectSecretDTO`」的非空泛斷言。

8. **五個既有的守門測試在本輪紅了，每一個都是它該紅的時候。**
   `test_all_actions_match_the_frontend_constants`（缺 `ACTION_SECRET_MANAGE`）、
   `test_audit_actions_match_the_frontend_constants`（缺四個 `secret.*`）、
   `test_every_mounted_route_is_in_the_matrix`（五條新路由）、
   以及 `test_error_catalog` 的兩條（十三個新碼、一個過期碼 `TASK_REQUIRES_SECRETS`）。
   最後那一條特別值得記：**它同時抓到「新增沒登記」與「舊的沒清掉」兩個方向**，
   而 `TASK_REQUIRES_SECRETS` 正是本期應該被取代而不是留著的那一個。

15. 🔴 **「需要一台我們沒有的機器」是一個錯誤的判斷，而它擋掉了三條本來今天就驗得完的出口條件。**
    §7 的第一版寫著 6b／6c／4b2 需要 `ssh-agent`、真的 sshd 與網路遠端。
    實際檢查之後：`ssh-agent`、`ssh-add`、`ssh`、`sshd` **全都裝著**，
    `github.com` 解析得到，而 `ssh -o StrictHostKeyChecking=yes` 對空的 known_hosts
    **當場就回了 `Host key verification failed`**。
    三條因此在同一輪內補完（見 §2 的 6b／6c）。

    **值得記住的不是我漏看了什麼，而是那句話的形狀**：「缺一台機器」是一個
    沒有人會去挑戰的理由，而「缺一枚別人 repository 的憑證」是一個具體、
    可以請人提供、而且範圍小得多的東西。**把後者說成前者，會讓一件三十分鐘的事
    被無限期擱著。** §7 已改寫成後者。

16. **PAT 的四處斷言用「認證失敗」而不是「認證成功」來驗，而那是更好的測試。**
    出口條件問的不是「token 能用嗎」，是「token 讀不讀得回來」——
    而憑證外洩的地方是**錯誤訊息**，也就是使用者會貼進工單的那段文字。
    所以測試刻意帶一枚假 token 對一個私有 repository 認證，然後斷言那枚 token
    不在錯誤訊息、不在 argv、不在 helper 檔案裡，且帶憑證的 URL 不可表示
    （後者正是 `git remote -v` 與 reflog 那兩處所依賴的性質）。

## 3b. 這一輪跑過的驗證

```
make check                                  綠（format／lint／typecheck／tokens／unit
                                            ／contract／build／traceability／railway）
backend/tests/db  (PostgreSQL)              530 passed
daemon  go test ./...                       17 個套件全綠
alembic upgrade → downgrade 0032 → schema   與 SC-00 基線逐位元組相同
schema 只新增                                基線的每一行都還在（只有 revision 標記改變）
```

## 4. 尚待人工完成的事

> **2026-08-14 更新：使用者已手動部署並在 staging 上確認過本期。**
> 環境：`https://cliora-staging.up.railway.app`。
> 這關掉了「這一期在真實部署上跑不跑得起來」這個問題——三個新環境變數、
> `0033`／`0034` 的遷移、以及旗標關閉的行為都在一個真的 Railway 部署上驗過。
> **它沒有關掉的是下面第 2 條與 §7**：那兩項缺的不是環境，
> 是**一枚我們有寫入權的別人 repository 的憑證**（§3 第 15 條記過為什麼
> 把它說成「缺一台機器」是錯的）。V2.4 的前置條件因此成立，
> 而 4b／4b2 仍留在 ⬜／◐。

1. **合併提案。** `v2` → `dev` 一律由人決定。
2. **出口條件在 Traqora 上實跑一次**（4b：`base_branch: main`、PAT 與 SSH 各一次）。
   ⚠️ **本期是第一次需要 Traqora 的寫入權限**——前四期都只讀。
   先在 scratch 遠端走完出口條件 6 的四種拒絕，再對正式 repo 跑。
   推上去的 `cliora/` 分支由人刪掉。
3. **`agentd` 0.10.0 的發布時機。** 出口全綠不代表要推給所有 node。
4. **翻 traceability 的 `lifecycle`。** 與第 2 條同時做。
5. **V2.2 遺留的兩項量測**：M-AR-2（log 速率）、M-AR-9 的尾巴。
   不擋本期，但沒有它們 `RUN_IDLE_TIMEOUT` 的 300 秒仍是一個有根據的猜測。
6. **主金鑰的產生與保管。** `openssl rand -base64 32`，
   **與資料庫備份分開保管**，且要記下 `key_version`。
   這一條要進 `docs/runbooks/backup-restore.md`，而它是一個人的動作。

## 5. 環境事實

沿用 `plan/18/09` §5，本期新增兩列。

| 事實 | 值 |
|---|---|
| 工具鏈不在預設 PATH 上 | `export PATH="$HOME/.local/bin:/usr/local/go/bin:$HOME/.nvm/versions/node/v22.23.2/bin:$PATH"` |
| DB 測試要**兩個**環境變數 | `CLIORA_TEST_DATABASE_URL` ＋ `CLIORA_DATABASE_URL` |
| `claude` 與 `codex` 都裝了但不在預設 PATH 上 | `~/.local/bin/{claude,codex}` |
| `git` 是 runner 模式的前置條件 | `agentd doctor` 檢查它 |
| e2e stack 要一個乾淨的資料庫 | 見 `plan/18/09` §5 的 46 個殘留 session |
| 🆕 **`ssh-agent`／`ssh-add` 是 SSH 路徑的前置條件** | `SC-07b` 的整合測試要它；`agentd doctor` 本期也該報告它 |
| 🆕 **需要一個可寫的 scratch 遠端** | 出口條件 6 的四種拒絕要對真的遠端跑一次。本地 `git init --bare` 就夠，但 host allowlist 要包含它 |
| 🆕 **需要 `CLIORA_SECRET_MASTER_KEY`** | `openssl rand -base64 32`。**旗標開啟的部署少了它會拒絕啟動**——那是設計，不是故障（D4） |
| 🆕 **`CLIORA_GIT_SECRET_DELIVERY_ENABLED` 預設 `false`** | 出口條件 4b2／6b–6g 要在 `=true` 的組態下跑，其餘在預設組態下跑。**兩種組態各跑一遍是驗收的一部分，不是可選的**（D5b） |
| 本期開始時的基線 | contract **v1.11.0**、`agentd` **0.8.0**（**不是 0.9.0**，見 D21）、migration 到 **0032**、RBAC **24** 個動作 |
| 本期結束時的基線（目標） | contract **v1.12.0**、`agentd` **0.10.0**、migration 到 **0034**、RBAC **25** 個動作 |

## 6. 實作中發現的其餘事項（接續 §3）

9. 🔴 **一個 gate 對一次「移動」誤判成「刪除」。**
   `gate-schema-additive.sh` 讀的是 unified diff，而快照是排序的：在一條既有外鍵
   兩側各加一條新的，那條**沒有動過**的行就被報成刪除。gate 於是在一個什麼都沒被
   移除的 schema 上失敗——而那是 gate 最負擔不起的失敗，**會叫錯狼的 gate 是會被關掉的
   gate**。它真正要問的是「基線的每一行是否都還在」，那是集合成員關係。改成
   `grep -Fxv` 的集合比對；排序本來就沒有語意，所以什麼也沒失去。

10. **`gate-migration-roundtrip.sh` 的降級目標改成參數。**
    它寫死降到 `0028`（V2.2 的基線），而本期的基線在 `0032`。複製一份腳本的代價
    與 `capture-baseline.sh` 相同，所以同樣改成參數（預設值不變）。

11. 🔴 **`GATE-SC-NO-SECRET-TO-DISK` 第一版抓到了 `run.token`。**
    那是 V2.2 刻意的例外：`cliora` CLI 是獨立程序，得從某處讀憑證，所以它寫成
    0600 並在 run 結束時刪除。處置是**逐名排除並寫下理由**，而不是把 pattern 放寬——
    放寬會讓下一個真正的違規也一起漏掉。專案機密沒有那個需求（它是環境繼承的），
    所以沒有第二個東西可以走這條路。

12. 🔴 **`spec.branch` 的第一版 pattern 允許 `cliora/-oops`。**
    `[A-Za-z0-9._-]+` 把 `-` 放進了字元集的首位可及範圍。**是自己寫的 invalid fixture
    抓到的**——封閉的 argv 表保護不了一個本身就是 flag 的值，而 `ref` 早就有同一條規則。

13. **`context` 的上限從 65536 降到 32768，而那是修正不是收緊。**
    舊值等於整個控制訊框的預算，所以單一欄位就能吃光它。實測的情境包是 1–2 KB，
    從來沒有接近過。降下來之後 `context` ＋ 8 枚機密的最壞情況仍在 64 KiB 內——
    而「仍在」不等於「保證」，所以 Central 還是要在送出前量一次（D2）。
    ⚠️ 附帶發現：**訊框過大的測試因此改用機密而不是長 context 來觸發**，
    因為降完之後 context 單獨已經撐不破訊框了。這正是這個改動要達到的效果。

14. 🔴 **`_key_for_version` 的第一版讓輪替之後的舊資料再也打不開**（已記在 §3 第 6 條）。

## 7. 真正還缺的兩項（都缺同一樣東西）

**不是缺機器，是缺一枚別人 repository 的憑證。** 兩項都要「對一個我們有寫入權的
真實遠端推一次」，而那是一個人要提供的東西，不是一個環境問題。

| # | 缺什麼 | 為什麼只能人來 |
|---|---|---|
| 1 | 用真憑證（PAT 或 deploy key）成功推一條 `cliora/` 分支 | 需要一個我們有寫入權的 repository。**推送本身已對本機 bare 遠端驗過**（`TestPushSendsTheBranchToARealRemote`），憑證路徑也已對 github.com 驗過（失敗路徑），缺的是兩者合起來跑一次 |
| 2 | **淺 clone 之後能不能 push**（`09-…md` §2.1） | 同上，而且**這是唯一一個可能改變設計的**：若 host 拒絕 shallow push，退路是 push 前 `git fetch --unshallow`，而它在大 repo 上的成本是一個要量的數字 |

**另外兩項是純工作，不缺任何東西**：出口條件 6d 的 Repository 表單 SSH 提示
（後端五條驗證已寫，缺表單那一段），以及 M-SC-2 的去識別成本量測。
