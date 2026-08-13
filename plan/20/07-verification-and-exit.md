# 07 — `SC-09`：驗證、gate 與出口條件

## 1. 完成定義（每張 ticket）

沿用既有紀律（`research/02/10` §1）：變更檔案清單與行為摘要、`make check`、
涉及 daemon 的 `make integration`、涉及畫面的 `make e2e` ＋ 截圖、
涉及 DB 的 `make test-db` ＋ 上下行演練、涉及 RBAC 的三條矩陣測試、
涉及 protocol 的 valid ＋ invalid fixtures、高風險的安全審查文件、
已知限制寫下來。

**不算完成**：跳過測試沒說明理由、驗證只是「看起來沒問題」、UI 改了沒截圖、
AC 沒逐項檢查、動了不相關的檔案。

## 2. 測試矩陣

| 層 | 本期覆蓋 |
|---|---|
| Contract fixtures | 新增：`spec.secrets` 的 valid ×3（一枚 env／一枚 git_pat／混合）＋ invalid ×8（超過 8 個、單值超過 8 KiB、`kind: provider_token`、名稱小寫、缺 `kind`、`additionalProperties`、**`secrets` 出現在 `run.accept`**、`secrets` 出現在 `run.complete`）；`runner.register` 的兩個布林 valid ×2 ＋ invalid ×2；`spec.branch` valid ×1 ＋ invalid ×3（非 `cliora/` 前綴、前導 `-`、超長）。**既有 fixtures 逐檔 sha256 未變** |
| Daemon 單元 | `kind` 分流、Redactor 的四條性質、危險名稱跳過、`HOME`／`GIT_CONFIG_GLOBAL` 的 A／B、tag 上報永不 nil、`BuildControl → ValidateControl` 的往返 |
| Daemon 整合 | **對真的 git 與本地 bare 遠端**：五條硬約束的四種拒絕、PAT 的四處斷言、SSH 的三條、淺 clone 之後 push、`ssh-agent` 不殘留 |
| Central 單元 | tag 比對的兩個方向、`tag_match_clause` ≡ `tag_match`（參數化 ≥12 組）、最小缺集、dispatch 的四種 409、offer 訊框過大時釋放認領 |
| Central DB | migration 上下行、機密的十條（`02-…md` §6）、RBAC 矩陣、**下放稽核不含值** |
| 前端單元 | `ProjectSecrets` 四條、`AgentsView` 四條、`EnrollmentView` 一條、`TaskDetail` 三條 |
| E2E | 建機密 → 設 repository 用 PAT → 建卡（宣告 tag ＋ 機密 ＋ `delivery: branch`）→ dispatch → **只有對的 runner 領到** → clone → 執行 → push → 分支在遠端 → log 裡是 `***` → 刪機密 → 下一次 dispatch 被 409 指名 |
| 安全 | 機密不可讀回（schema ＋ 五條回應）、log／summary／error 三處去識別、git 四種推送拒絕、兩種認證的不落檔、代償四條、**UI 沒有暗示 tag 是授權** |

## 3. 十個 gate

`scripts/sc/gates.sh`，沿用 `scripts/ar/gates.sh` 的形狀（`check`／`pass`／`fail`）。

| Gate | 做什麼 | 為什麼是機器而不是 review |
|---|---|---|
| `GATE-SC-SCHEMA-ADDITIVE` | 對 `SC-00` 基線只允許新增 | 沿用 `scripts/pj/gate-schema-additive.sh` |
| `GATE-SC-MIGRATION-ROUNDTRIP` | `downgrade` 回 `0032` 與基線逐位元組相同 | 沿用 `scripts/ar/gate-migration-roundtrip.sh` |
| `GATE-SC-CONTRACT-ADDITIVE` | 既有 fixtures 逐檔 sha256 未變 | 沿用 `scripts/tk/contract_snapshot.py` |
| `GATE-SC-TOUCH-LIST` | D19 的禁區零 diff（**新增 `secret_box.py`**） | 沿用 `GATE-AR-TOUCH-LIST` |
| **`GATE-SC-NO-SECRET-IN-RESPONSE`** | dump OpenAPI，走訪**所有** response schema，屬性名為 `value`／`value_encrypted`／`dek_wrapped`／`plaintext`／`secret_value` → 失敗 | 一個未來的端點順手回傳整列，是這件事最可能的發生方式，而它不會出現在本期的 review 裡 |
| **`GATE-SC-NO-PLAINTEXT-COLUMN`** | `project_secrets` 的欄位名不得出現不帶 `_encrypted`／`_wrapped` 的 `value`，也不得有 `plain`／`raw` | 擋的是「先存明文之後再加密」——`secret_box.py` 的規則 1 已經寫好了為什麼那沒有回頭路 |
| **`GATE-SC-SINGLE-DECRYPT`** | `ast`：`backend/app/` 裡呼叫 `secret_envelope.unseal` 的模組只有 `services/secrets.py` | 多一個呼叫者就是多一條要審的路徑，而它會長在一個沒人注意的地方 |
| **`GATE-SC-TAG-BOTH-QUERIES`** | `ast`：`_eligible` 與 `_eligible_runner_count` 都引用述詞函式，而不是各自 inline 條件 | D11。只改一個查詢的症狀是「畫面說的話是假的」，而那不會讓任何測試變紅——除非有這一條 |
| **`GATE-SC-PUSH-ARGV`** | `daemon/internal/gitfetch/` 不含 `--force`／`--force-with-lease`／`--delete`／`--tags`／`--mirror`／`push --all` 這些字串（註解除外） | 一條「檢查它不存在」的約束可以被多一個呼叫點繞過；一張沒有那個字串的表不行 |
| **`GATE-SC-NO-SECRET-TO-DISK`** | `ast`：daemon 裡 `Secrets` 的欄位不得流向 `os.WriteFile`／`os.Create`／`os.OpenFile` | 「寫個 0600 檔案就好」是這件事最自然的實作直覺，而 ADR 的一句話擋不住直覺 |
| **`GATE-SC-NO-BINDING-PROMISE`** | 掃 `backend/app/`／`frontend/src/`／`daemon/`（migration 目錄除外）中同時出現 `project_agents` 與 `V2.3`／`arrives`／`起提供` 的行 | 九處過期承諾（`01-…md` §5b），而其中三處在 RBAC 與 API 的說明文字裡 |

> ⚠️ **三個 gate 的第一版很可能會掃到自己的說明文字**——V2.2 撞過三次
> （`plan/18/09` §3 第 15 條）。`GATE-SC-PUSH-ARGV` 與
> `GATE-SC-NO-BINDING-PROMISE` 尤其危險，因為它們掃的正是**解釋規則為什麼存在**
> 的那些句子。**一個會找到自己說明的守衛比沒有守衛更糟**：讓它變綠最便宜的做法
> 是刪掉那段文字。所以這兩個 gate 要排除註解，並且**自己有一條測試**
> 餵一段含有那些字串的註解、斷言不會誤報。

## 4. 旗標關閉回歸

`CLIORA_AGENT_RUNS_ENABLED=false`：

| 檢查 | 方法 |
|---|---|
| API 表面未變 | `openapi-flags-off.json` 與 `SC-00` 基線 diff：**只允許新增路徑，且新增路徑全部 404** |
| 兩個旗標各自獨立 | `PROJECTS_ENABLED=true` ＋ `AGENT_RUNS_ENABLED=false`：看板可用、Secrets 區不出現、`/api/projects/{id}/secrets` 404 |
| **主金鑰不必存在** | 旗標關閉時 `CLIORA_SECRET_MASTER_KEY` 未設定 → **Central 正常啟動**（D4） |
| Protocol 未變 | 既有 fixtures 全綠；**0.9.0 的 daemon 連得上、領得到無 tag 的卡**（D12 的形式：register 沒帶那兩個布林） |
| 五個既有路由可直達 | e2e 逐一造訪 |
| Session 全生命週期 | 建立 → 操作 → 重整重連 → 接手 writer → 終止 |
| 檔案面／System terminal／Tunnel | 沿用既有回歸套組 |
| RBAC | 三角色 × **25** 個動作的矩陣 |
| DB | 既有表逐欄比對 |
| **終端延遲** | run 全速輸出且 Redactor 在跑時，同 node 的終端 echo p95 **不比 `SC-00` 基線高 20% 以上**（D6／M-SC-2） |

## 5. 出口條件（24 條）

> **1–3g 是機密與授權邊界，4–6d 是 git，7–11 是回歸。**
> 每一條要有可貼上的輸出，逐條記在 `08-…md` §2。

1. 建立一個機密後，**任何 API 都讀不回它的值**（對 OpenAPI schema 與五條實際回應各一條）。
1b. `CLIORA_SECRET_MASTER_KEY` 缺少／過短／等於 dev 預設值，**且旗標開啟** →
   Central 拒絕啟動並指名是哪一種；**旗標關閉時照常啟動**。
1c. 主金鑰輪替：換 `key_version` 後**只重新包裝 DEK**，`value_encrypted` 逐位元組未變，
   舊 `key_version` 的資料仍可解；舊金鑰被移除後回一個**指名版本**的錯誤。
2. 機密值出現在 CLI 輸出時，平台收到的 log 是 `***`；
   **原值從未離開 node**——在 Central 端斷言 `run_logs`、`task_runs.summary`、
   `task_runs.error_code` 三者都不含原值。
2b. **把機密值放進 git 的錯誤訊息**（用一個會失敗的 remote）→
   `run.failed.message` 到達 Central 時已是 `***`。
3. `accept_secrets: false` 的 node，其 runner 永遠不會被 offer 需要機密的卡片，
   **且空等原因不會因此說成「等待可用的 Agent」**。
3b. **tag 比對成立**：卡片要 `docker`，只有具備 `docker` 的 runner 拿得到；
   另一台線上、閒置、runtime 相符但沒有該 tag 的 runner **永遠不會被 offer 它**。
3c. **`run_untagged: false` 的 runner 只領有宣告 tag 的卡片**；同時線上的
   `run_untagged: true` runner 照常領走沒宣告 tag 的卡片（**兩者一起跑一次才算通過**）。
3d. **指定一個 tag 不符的 runner → dispatch 回 409，訊息指名缺哪幾個 tag**，且**不入佇列**。
   指定一個 `run_untagged: false` 的 runner 給無 tag 的卡 → **另一個錯誤碼**。
3e. **沒有任何 runner 湊得齊某張卡的 tag 時**，卡片顯示的是
   「沒有 runner 同時具備 `docker`、`node20`」，**不是**泛用的「等待可用的 Agent」。
3f. **register payload 未帶 `run_untagged`／`accept_secrets` 時視為 `true`**，
   行為與升級前一致（**不依賴任何 daemon 版本號**）。
3g. **授權邊界的誠實性**（畫面斷言，代償第 4 條）：Agents 頁與卡片上
   **沒有任何 UI 暗示 tag 是授權**（無鎖頭、無「授權」字樣），
   Agents 頁的那一段**含**「並取得那些卡片宣告的機密」且**不含**「V2.3 起提供」，
   而 **enrollment 畫面的表單內**直接寫著
   「這台機器將可以領取任何專案的卡片，並取得那些卡片宣告的機密」。
3h. 卡片宣告一個不在 allowlist 的名稱 → **卡片編輯時就 422 指名**；
   allowlist 內但機密不存在 → **dispatch 時 409 指名**（兩種是不同的訊息）。
4. `source: repo` ＋ `delivery: branch` 的卡片 → run 目錄有 `repo/`，
   在正確的 base branch 上，分支名為 `cliora/<card_ref>-<run_seq>`，**且分支出現在遠端**。
4b. **用 Traqora 驗 `base_branch: main`**（D30）——證明它是設定值，不是寫死的 `master`。
   **預設組態下（`CLIORA_GIT_SECRET_DELIVERY_ENABLED=false`）用 node 上既有的憑證跑一次。**
4b2. **旗標開啟時 PAT 與 SSH 各再測一次。**
4d. 🆕 **預設組態的完整性**（2026-08-13 裁決）：`kind: git_pat`／`git_ssh_key` 的機密
   **建立被拒並指名該環境變數**；`auth_kind` 只能是 `ambient`；
   `run.offer` 的 `spec.secrets` **不含任何 git kind**；
   **run 的 `HOME`／`GIT_CONFIG_GLOBAL` 未被改寫**；
   **而 clone 與 push 都成功**。前四項是否定命題，最後一項是它們合起來仍然可用的證明。
4c. `source: existing_branch` 且該分支不是 `cliora/` 前綴 → **dispatch 當下拒絕並說明**，
   不是等到 push 才失敗。
5. `source: none` 的卡片 → run 目錄**沒有** `repo/`，Agent 讀不到任何程式碼（V2.2 回歸）。
6. daemon 嘗試推 `main`、推非 `cliora/` 前綴、force push、推到 allowlist 外的 host
   → **四種全部被拒**，且拒絕發生在 daemon 內（**`git` 從未被執行**，不是靠遠端拒絕）。
   ⚠️ **這四種在旗標關閉的預設組態下也要各跑一次**——五條硬約束約束的是**推什麼**，
   與用哪一種憑證無關（D10），而測試很自然會只在「有平台憑證」的組態下寫。

> **6b–6d 只在 `CLIORA_GIT_SECRET_DELIVERY_ENABLED=true` 時適用。**
> 它們仍然是本期的出口條件——機制照做——但驗收要明說是在旗標開啟的組態下跑的。

6b. **PAT 路徑**：token 不出現在 `git remote -v`、reflog、`ps`／`/proc/<pid>/cmdline`
   或任何錯誤訊息（四處各一條斷言）；`GIT_ASKPASS` helper 檔案本身不含 token。
6c. **SSH 路徑**：私鑰**從未寫入磁碟**（run 目錄全域搜尋比對）；
   run 結束後 `ssh-agent` 程序不殘留；未知 host 被 `StrictHostKeyChecking` 拒絕。
6d. repository 設 SSH 時，**設定畫面就說得出「無法開 PR，需另一枚 provider_token」**
   （本期是提示；V2.4 開放 `pull_request` 時改為擋下儲存——`05-…md` §3.2）。
6e. **缺 git 憑證時仍然秒級失敗**（V2.2 的出口條件 9 在本期重跑，
   因為本期換掉了它成立的那個環境變數）。
6f. **`git_pat`／`git_ssh_key` 不出現在 CLI 子程序的環境裡**（D5；
   用一支印出 `environ` 的 fake CLI 斷言；旗標開啟時測）。
6g. 🆕 **`isolate_ambient_credentials` 只對收到平台憑證的 run 生效**（D9）：
   同一個設定值 `true`，旗標關閉時 `HOME` 不變、旗標開啟時 `HOME` 指向 run 目錄。
   **兩個案例是同一條測試的兩半**——分開寫會讓「設定值 ≠ 每次 run 的事實」這件事看不出來。
7. run 結束後目錄依保留期被清掉（V2.2 回歸）；**第二次 run 仍是淺 clone**
   （不是規劃寫的 mirror——M11 之後改用淺 clone，`plan/18/09` §3 第 11 條）。
8. run 程序嘗試讀寫任何 allowed root → 由部署姿態承擔並由平台**回報**
   （V2.2 已定，本期不改；`dedicated` 欄仍顯示 ⚠）。
9. 配額用盡的 node 停止 poll，平台顯示原因，其他 node 照常領工作（V2.2 回歸）。
10. **刪除機密後，下一次 dispatch 就被 409 指名**；**進行中的 run 不受影響**。
10b. **下放稽核**：一筆 `secret.deliver`，含名稱與 `key_version`，**不含值、不含長度**；
   runner 之後 `run.decline` 時那筆稽核**仍在**且如實記為已下放（D1 的代價）。
11. **旗標關閉：完整 V1＋V2.0＋V2.1＋V2.2 回歸全綠**，
   既有 contract fixtures 一個位元組未變，`agentd` 0.10.0 在旗標關閉的部署上行為與 0.8.0 相同。
12. **`run.offer` 的訊框過大時，認領被釋放且卡片上留下一筆說明**——
   不是靜默丟棄之後租約到期（D2）。

## 6. 安全審查（`docs/security-review-v23.md`，三節）

**三節各自獨立，不合寫成一段「Agent 執行環境安全審查」**（`research/02/10` §6）。

### §1 機密的儲存與下放

要回答的：加密結構（信封、AAD、每次新 nonce）、主金鑰的取得與驗證、
`key_version` 與輪替、**不可讀回的兩條斷言**、下放的路徑
（`poll` → `materialise` → `spec`，中間沒有一格接受呼叫端輸入）、
稽核的內容與時機、**`kind` 分流**（D5）、去識別的範圍與**它做不到什麼**、
危險名稱的兩層擋法、刪除的語意與它不做的事。

**要明寫的代價三條**：金鑰與密文共用同一個信任邊界；沒有解密稽核；金鑰遺失即全毀。

### §2 授權邊界

**這一節的形狀被 2026-08-12 改寫。** 原本要審的是「`project_agents` 綁定
＝ 機密授權邊界」這個檢查點，**現在沒有那個檢查點**。改為驗兩件事：

1. **代償四條真的存在**，逐條對應一個出口條件：

   | 代償 | 出口條件 | 證據 |
   |---|---|---|
   | 卡片級 `required_secrets` ⊆ Project allowlist | 3h | 兩處檢查、兩種錯誤訊息 |
   | node 端 `accept_secrets: false` | 3 | 資格查詢的兩個位置都涵蓋它 |
   | 可撤銷 ＋ 下放稽核 | 10、10b | 稽核 payload 的實際內容 |
   | enrollment 說明文字 | 3g | 畫面測試 |

2. **沒有任何 UI 暗示 tag 是授權**（3g 的畫面斷言）。

**要明寫的代價兩條**：任何 enroll 過的機器，tag 對得上就能取得該卡宣告的機密；
`run.dispatch` 是 Developer 的動作，而**沒有一層 Admin 授權擋在「指定一台 runner」
與「它拿到機密」之間**（`01` D17b，而讀這份審查的人不會回去讀 D17b）。

### §3 git 寫入

**這一節分兩半，而它們的預設狀態相反**（2026-08-13 裁決）：

**§3a — 送回（預設開啟）**：五條硬約束逐條 ＋ 它們的實作位置
（**表裡沒有那些 flag**，不是檢查它們不存在）、
第⑤條的兩級保證（`user.email` 是硬的，trailer 不是）。
**要正面處理的代價**：預設組態下平台是拿**機器的**憑證推的，
所以「可撤銷」在預設路徑上**不成立**——平台開始 push 了，而它推的憑證平台管不到。
收斂點是五條硬約束（它們與憑證無關）、node 的部署姿態與紅線 5。

**§3b — 憑證下放（預設關閉）**：兩種認證的不落檔（**socket 不是金鑰**）、
known_hosts pinning、`GIT_ASKPASS` helper 自己不含機密、
**`isolate_ambient_credentials` 的 A 能做到什麼與不能做到什麼**、
以及「這個組態下 Agent 的 git 自由被收掉了」這個行為改變。
**這一半要在標題上就寫明它審的是一條預設關閉的路徑**——
否則讀者會把它的保證誤讀成預設組態的保證，而那正好相反。

## 7. 合併關卡

1. 階段工作以正常 PR 進 `v2`。
2. §5 的 24 條與 §4 的回歸套組全部通過 → **在 PR 或 issue 上提出合併請求**，附上證據。
3. **由人審閱後決定合併時機。沒有自動合併、沒有排程合併、沒有「條件綠了就 merge」的 CI job。**
4. 合併後在 `08-…md` 記錄 commit 與日期。

**條件全綠只是取得提案資格，不是核准**（`research/02/10` §7）。

## 8. release note（`docs/release-note-secrets-and-dispatch.md`）

四段，**其中兩段是行為改變而不是新功能**：

1. **新功能**：專案機密（`kind: env`）、tag 派工、`delivery: branch`。
2. ⚠️ **行為改變一**：**平台開始代表卡片 push 了**，而預設組態下它用的是
   **node 上既有的 git 憑證**——平台管理不了也撤銷不了那把憑證。
   五條硬約束仍然完整適用（它們約束的是推什麼），但「可撤銷」在預設路徑上不成立。
   **這是 2026-08-13 裁決刻意選的範圍**：git 認證交給 node owner。
3. ⚠️ **行為改變二**：Repository 的建立與修改從 `project.manage` 升到 `secret.manage`
   （兩者都是 Admin，所以沒有角色失去能力，但自動化可能會撞到）。
4. **預設關閉的能力**：`CLIORA_GIT_SECRET_DELIVERY_ENABLED` 打開之後才有
   平台管理的 git 憑證（PAT／SSH）。打開之後才會發生的第三個行為改變是
   **Agent 在 run 裡不再能用平台的憑證 fetch／push**（`kind` 分流 ＋ ambient 隔離）。
5. **已知取捨**：授權邊界是 enrollment（代償四條）；去識別是盡力而為
   （編碼過的值可能漏網）；**token 成本上限仍然只量不做**（V2.2 的 M-AR-10 延續）。
