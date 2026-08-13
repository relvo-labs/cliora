# 00 — 執行總控（V2.3 機密下放、tag 派工與 git 送回）

Ticket 前綴 `SC-`。上游規劃：[`research/02/05-phase-v23-secrets-and-isolation.md`](../../research/02/05-phase-v23-secrets-and-isolation.md)。

> **2026-08-12 的裁決決定了本期的形狀**：`project_agents` 綁定表**不做**，
> 配對改用**卡片 tag × runner tag**，**授權邊界永久是 enrollment**。
> 這不是延後——本期不會有一張授權表，安全審查也不會有那個檢查點。
> 換上的是 `01` D18 的**代償四條**，而本計畫把它們各自綁上一個出口條件（§1）。

## 1. 成功定義

**要交付的：** Admin 在 Project Settings 建立一枚 `NPM_TOKEN`（`kind: env`，
建完之後任何人、任何 API 都讀不回它的值）；
Developer 在一張卡片上宣告 `required_labels: ["docker"]` 與 `required_secrets: ["NPM_TOKEN"]`、
`delivery: branch`；派給 Agent 之後，**只有 tag 對得上的那台 runner** 領得到；
它用**該 node 上既有的 git 認證**（node owner 自己配置的，平台不管——2026-08-13 裁決）
clone、在 `cliora/TASK-123-1` 分支上工作、由平台把分支推回去；
機密的值在 CLI 輸出裡出現過，而平台收到的 log 是 `***`；
run 結束後那枚機密的 `last_used_at` 更新了，稽核裡有一筆「下放了哪幾個**名稱**」；
刪掉那枚機密，下一次 run 就拿不到它。
**而那台 runner 之所以拿得到機密，唯一的理由是它被 enroll 過**——這句話寫在發 token 的那一頁上。

**另外要交付、但預設關閉的一條**：把 `CLIORA_GIT_SECRET_DELIVERY_ENABLED` 打開之後，
同一張卡改成用平台下放的 PAT 或 SSH key clone 與 push，
而機器原本的 git 憑證在那次 run 的 git 環境裡看不見。
**兩種組態都要驗**（出口條件 4b／4c）。

**其餘一律不做。** PR／MR、`existing_pr`、驗證報告、需求釐清——那是 V2.4 之後的事（§2）。

**不得弄壞的十二件事：**

1. **兩個旗標都關閉時，系統與 V2.2_1 逐位元組一致。** 本期新增端點全數 404、
   `runner.register` 一律拒絕、Secrets 區不出現。
2. **互動式 Session 的行為一個位元組都不變。** SEC-002 的 argv 條款逐字保留，
   `daemon/internal/runtime/{runtime,launch}.go` 對 `SC-00` 基線**零 diff**（沿用 `GATE-AR-TOUCH-LIST`）。
3. 🆕 **SEC-002 只被修訂一句，而那一句要寫在 ADR 裡而不是在程式碼註解裡。**
   修訂後的不變式：**「沒有任何請求 payload 能命名一個命令、或攜帶一個機密的值。」**
   `spec` 裡新增的 `secrets` 是**平台從自己的 store 取出的值**，不是呼叫端送進來的
   （`01-…md` §3.2）。
4. 🆕 **沒有任何 API 回傳機密的值，而這件事有兩條機器斷言**：對 OpenAPI schema 掃描
   （不存在名為 `value`／`value_encrypted`／`plaintext` 的回應欄位），
   以及對實際回應斷言（`04-…md` 不適用；見 `02-…md` §5）。
5. 🆕 **機密永不落檔。** 例外只有一個：`ssh-agent` 的 socket，而**socket 不是金鑰**
   （`04b-…md` §3.2）。`WriteContext` 寫 `run.token` 那個既有形狀**不得被複製到機密上**。
6. 🆕 **五條 git 硬約束寫死在 daemon，不是設定值。** 一條約束一旦可以從設定關掉就等於沒有。
7. 🆕 **平台不做 PR、不 merge、不 force push、不刪遠端分支、不動 tag。**
   daemon 的 git 子命令是一張封閉表，`GATE-SC-PUSH-ARGV` 對它斷言。
8. **既有 24 個 RBAC 動作的角色歸屬不變。** 只新增一個 `secret.manage`（合計 25），Admin 專屬。
9. **run 憑證永遠拿不到 `secret.manage`。** 而且不是靠一行 if——它根本不走使用者的認證路徑。
10. **卡片產物仍然不可變**，run log 的兩種保留期不變。
11. 🆕 **tag 不是授權，而 UI 上不得有任何相反的暗示。** 沒有鎖頭圖示、沒有「授權」字樣。
    這是一條**畫面斷言**（出口條件 3g），不是文件承諾。
12. 🆕 **`agent_runners.labels` 與 `run_untagged` 一律唯讀。** 它們是 node 上的設定檔宣告，
    平台端可編輯會製造第二個真實來源——node 重連時 `runner.register` 會把編輯蓋掉。

成功的判準是以下十二項，每一項都要有可貼上的輸出（`07-…md` §5）：

1. 建立一枚機密 → 列表回名稱／kind／建立者／`last_used_at`，**回應與 OpenAPI schema 都沒有值**。
2. `CLIORA_SECRET_MASTER_KEY` 缺少／過短／等於 dev 預設值，且 `CLIORA_AGENT_RUNS_ENABLED=true`
   → **Central 拒絕啟動並指名**；旗標關閉時照常啟動（D4）。
3. 換 `key_version` → **只重新包裝 DEK**，`value_encrypted` 逐位元組未變，舊版本仍解得開。
4. 卡片宣告 `required_secrets` 不在 Project allowlist 內 → **dispatch 409 並指名是哪幾個**。
5. `accept_secrets: false` 的 node → 其 runner 永遠不會被 offer 需要機密的卡片。
6. **tag 比對**：卡片要 `docker` → 只有具備 `docker` 的 runner 拿得到；
   另一台線上、閒置、runtime 相符但沒有該 tag 的 runner **永遠不會被 offer 它**。
7. `run_untagged: false` 的 runner **只領有宣告 tag 的卡片**；
   同時線上的 `run_untagged: true` runner 照常領走沒宣告 tag 的卡片（**兩者一起跑一次才算通過**）。
8. 指定一個 tag 不符的 runner → **409，訊息指名缺哪幾個 tag**，且不入佇列。
9. 湊不齊 tag 的卡片顯示的是「**沒有 runner 同時具備 `docker`、`node20`**」，
   不是泛用的「等待可用的 Agent」。
10. 機密的值出現在 CLI 輸出 → **平台收到的 log 是 `***`**，且在 Central 端斷言
    `run_logs`、`task_runs.summary`、`task_runs.error_code` 全都不含原值。
11. `source: repo` ＋ `delivery: branch` → run 目錄的 `repo/` 在正確的 base branch 上，
    分支名 `cliora/<card_ref>-<run_seq>`，**用 node 上既有的憑證推成功一次**（預設組態）。
11b. **`CLIORA_GIT_SECRET_DELIVERY_ENABLED=true` 時 PAT 與 SSH 各再推成功一次**；
    token 不出現在 `git remote -v`、reflog、`ps` 或任何錯誤訊息（四處各一條斷言）；
    私鑰**從未寫入磁碟**（run 目錄全域搜尋比對），run 結束 `ssh-agent` 不殘留。
11c. **旗標關閉時**：`kind: git_pat`／`git_ssh_key` 的機密建立被拒並指名該變數、
    `auth_kind` 只能是 `ambient`、**run 的 `HOME`／`GIT_CONFIG_GLOBAL` 未被改寫**。
12. daemon 嘗試推 `main`、推非 `cliora/` 前綴、force push、推到 allowlist 外的 host
    → **四種全部被拒，且拒絕發生在 daemon 內**（不是靠遠端拒絕）。

外加一條回歸判準：**兩個旗標關閉時完整 V1＋V2.0＋V2.1＋V2.2 全綠、
既有 contract fixtures 一個位元組未變、`agentd` 0.10.0 在旗標關閉的部署上行為與 0.8.0 相同。**

## 2. 範圍

### 納入

- `SC-00` **基線擷取 ＋ 兩項量測**（閘門）：
  M-SC-1（機密的實際大小 → 決定訊框預算）、M-SC-2（去識別的成本 → 決定它放在哪一層）。
  （M-AR-6 原本是第三項，2026-08-13 裁決之後降級為上線後觀察。）
  **另加一件不是量測的事**：`daemon/VERSION` cut `0.9.0`（D21）。
- `SC-01` **ADR 0032**（機密管理與 SEC-002 修訂，**§0 是授權邊界**）＋ `research/prd.md` §8.14
  ＋ skill 的 Git automation 那一句 ＋ traceability（FR-RUNENV-001…008）
  ＋ **過期承諾清單**（九處 `project_agents` 的程式註解）。
- `SC-02` **ADR 0031 的增補**：git 送回半邊（五條硬約束、ambient 憑證的隔離開關）。
- `SC-02b` **ADR 0029 的增補**：tag 派工（兩層配對、五條件資格判定、比對放 Central 的理由）。
- `SC-03` 資料層：migration `0033`（`project_secrets`、`projects.allowed_secret_names`、
  `agent_runners.run_untagged`、`project_repositories` 的三個憑證欄）、
  `0034`（seed `secret.manage`）。
- `SC-04` Secret store：信封加密、金鑰驗證、**永不可讀回**的 service 與 API、下放稽核。
- `SC-05` tag 派工：五條件資格判定、兩個查詢共用一個述詞、dispatch 的 409、反向查詢。
- `SC-06` contract **v1.12.0**：`spec.secrets`、`runner.register.run_untagged`、
  **訊框總量上限** ＋ fixtures ＋ Central 出口方向的大小檢查。
- `SC-07` `agentd` **0.10.0** 的機密面：接收、**按 `kind` 分流**、去識別、
  ambient 憑證隔離、`runner.tags`／`runner.run_untagged` 上報、`doctor`。
- `SC-07b` `agentd` **0.10.0** 的 git 面：分支命名空間、push 與五條硬約束
  （**這一半預設就在跑**，用 node 上既有的憑證）＋ `GIT_ASKPASS` helper、`ssh-agent`
  （**這一半由 `CLIORA_GIT_SECRET_DELIVERY_ENABLED` 控制、預設關閉**）。**安全審查第三節**。
- `SC-08` 前端：Secrets 區、Repository 認證、卡片的 tag 與機密輸入、Agents 頁改寫、
  **enrollment 文案**、Run 詳情。
- `SC-09` 驗證與出口：測試、雙旗標關閉回歸、十個 gate、`docs/security-review-v23.md`、
  release note、**合併提案並停下來**。

### 不納入

- **PR／MR 的建立、`delivery: pull_request`／`existing_pr`。** V2.4。
  本期 dispatch 仍對這兩個值回 409（`UNSUPPORTED_DELIVERIES` 保留這兩列，
  **只拿掉 `branch`**）。
- **`provider_token` 這個 kind 的使用。** 欄位與 UI 提示本期就要有（因為 SSH＋PR 的
  組合要在設定畫面說明），但**沒有任何程式碼會下放它**——它的用途是開 PR，而那是 V2.4。
- 🆕 **預設不下放 git 憑證**（2026-08-13 裁決，D5b）。機制做出來，旗標預設 `false`。
- 🆕 **不管理、不稽核、不撤銷 node 上的 ambient git 憑證。** 那是 node owner 的東西。
  平台能報告的只有 V2.2 已有的可觀測性（run 摘要的 `git remote -v` 與未推送 commit 數）。
  **這是範圍宣告不是缺口**，它有自己的一列風險（§5）。
- **`project_agents` 綁定表。** 2026-08-12 裁決**取消**，不是延後。
- **tag 的字典管理**（預先註冊、命名規範、專案級 tag allowlist）。
  先讓自由字串跑一段，真的出現「同一個能力被寫成三種拼法」再說。
- **從 UI 編輯 runner 的 tag。** tag 是 node 上的設定（不得弄壞第 12 條）。
- **機密的自動輪替、外部 secret manager、KMS。** ADR 0032 要寫**升級路徑**，不寫實作。
- **push 以外的任何 git 寫入。** merge、rebase、release、tag 一律不做。
- **瀏覽 run 目錄、把 run 目錄接進檔案 API。** V2.2 已定的禁區，本期不動。
- **重做隔離目錄與 clone。** V2.2 已交付。本期只增補分支、push、機密與 tag。
- **物件儲存（S3）。** M10／M16 量了再說。
- **token 成本上限。** V2.2 刻意只量（M-AR-10）；本期**仍然不做**，
  理由不變（`claude --max-budget-usd` 有、codex 沒有，接一半比不接更危險）。
  它出現在 release note 的已知取捨裡，不在本期範圍。

## 3. 固定基線決策

| # | 決策 | 選擇 | 理由 |
|---|---|---|---|
| D0 | **本期在 V2 的哪一格** | 三個半邊：機密半（新儲存面 ＋ 新憑證流）＋派工半（零新儲存面）＋送回半（**新的對外副作用**）。共用旗標 `CLIORA_AGENT_RUNS_ENABLED` | 三者的失敗長相不同：機密半壞了是外洩、派工半壞了是卡片沒人領、**送回半壞了是推到了別人的遠端上**。共用一個旗標是因為機密沒有派工就沒有下放的對象，派工沒有機密就只是換一種指定方式 |
| D1 ⚠️ | **解密發生在 `RunService.poll()` 裡，就在原子認領之後** | 認領成功 → 讀該卡的 `required_secrets` → 逐筆解封 DEK、解密值 → 組進 `spec.secrets` → 記一筆下放稽核（**只有名稱**）→ 更新 `last_used_at` → 送 `run.offer`。**同一個 flush** | `poll` 是 `node_gateway` 接收迴圈呼叫的，所以三件事必須成立：① **不得呼叫 `registry.request()`**（`runs.py` 的 docstring 已經寫了為什麼，`GATE-AR-NO-REQUEST-IN-LOOP` 在守）；② 解密是純 CPU 的 AES-GCM，不 await，不會讓那條同時載著終端位元組的迴圈停下來；③ 稽核與 `last_used_at` 要與認領同一個交易——**分開會產生「領到了但沒有紀錄」的視窗**。**代價要寫在 ADR**：runner 之後 `run.decline`，機密仍然已經下放過了，稽核如實記為「已下放」而不是回頭刪掉那筆 |
| D2 ⚠️ | **`run.offer` 留在 64 KiB 控制訊框；Central 在送出前量，量不過就讓認領失敗** | contract 加三個上限（單值 8 KiB／總量 32 KiB／最多 8 個名稱），Central 在組完 payload 之後、送出之前算一次序列化長度，超過就**釋放認領**（run 回 `queued`）並在卡片上留一筆事件說明是哪一部分太大 | `run.offer` 不在 `LARGE_FRAME_TYPES`（`codec.py:32`），而它的 `context` 單欄上限已經是 65536 字元——**今天就可能組出一個送不出去的 offer**，而 `codec.py` 只在 `decode_control` 這一側檢查大小，出口方向**沒有任何檢查**。症狀是 D2（`plan/18`）描述的那一種：訊息不見了但沒有錯誤，卡片被領走、租約到期、重排、三次後 `blocked`。**被否決**：把 `run.offer` 放進 `LARGE_FRAME_TYPES`（那條 socket 同時載著互動式終端的二進位輸出，理由與 V2.2 拒絕放大 `run.log_chunk` 完全相同）；把機密拆成第二個訊息（多一個型別、多一個「先到後到」的競態，而 offer 本來就是一次性的事實陳述） |
| D3 ⚠️ | **新寫 `app/security/secret_envelope.py`，`secret_box.py` 零 diff** | 每筆一把 32-byte DEK（AES-GCM 加密值），DEK 以主金鑰包裝（另一次 AES-GCM）後與密文同列。AAD 是 `cliora-project-secret-v1`，**與 tunnel 憑證的 AAD 不同**，所以兩邊的密文互相不可解 | `secret_box.py` 是 ADR 0022 的 tunnel 憑證用的：單一用途、Admin 專屬、**沒有信封加密也沒有 `key_version`**。`01` D22 明寫不共用，理由是輪替時機不同。**新寫而不是擴充**，讓「這支模組只服務一件事」對兩邊都成立，也讓安全審查讀得到一個完整的加密路徑而不是兩個交錯的分支 |
| D4 | **主金鑰的啟動驗證是條件式的，綁在 `agent_runs_enabled` 上** | `Settings` 的 `@model_validator`：`agent_runs_enabled` 為真且（金鑰空／base64 解不開／不是 32 bytes／等於 dev 預設值）→ `ValueError` 並**指名是哪一種**。旗標關閉時完全不檢查 | 既有的 `metrics_scrape_token` 驗證器就是這個形狀（`settings.py:297`），而它成立的理由一樣：**沒開的功能不該讓部署起不來**。無條件檢查會弄壞每一個沒在用 V2 的既有部署，而那不是一個安全性的提升——那些部署裡一筆機密都沒有 |
| D5 ⚠️ 🆕 | **`kind` 決定機密去哪裡**（**而 git 那兩種預設根本不下放**） | `env` → CLI 子程序的環境變數。`git_pat`／`git_ssh_key` → **只進 daemon 自己的 git 環境**（`gitfetch.Fetcher.Env`），永不進子程序，**且整條路徑由 D5b 的旗標控制、預設關閉**。`provider_token` → 本期不下放（V2.4） | 規劃寫「以環境變數傳給 CLI 程序」，而那句話的對象是卡片宣告的 env 機密。**git 憑證不一樣**：它一旦進了子程序的環境，Agent 就能拿平台發出的憑證推到任何地方，而**五條硬約束一條都攔不到**（它們寫在 daemon 的 push 路徑裡）。**2026-08-13 裁決之後這條的適用範圍變小了**：它描述的是一條預設關閉的路徑，代價（Agent 不能用**平台的**憑證 fetch／push）只在有人主動打開它時才發生。**被否決**：全部進子程序（上述）；做一個「要不要給 Agent git 憑證」的卡片欄位（把一個部署姿態變成一個每張卡都要答的問題，而答錯的成本不對稱） |
| D5b ⚠️ 🆕 | **git 憑證的下放是一個預設關閉的能力：`CLIORA_GIT_SECRET_DELIVERY_ENABLED`（預設 `false`）** | 關閉時：① `kind: git_pat`／`git_ssh_key` 的機密**建立被拒**（422 並指名這個變數）；② `project_repositories.auth_kind` **只能是 `ambient`**；③ `run.offer` 的 `spec.secrets` **永不含 git kind**；④ **D9 的隔離不生效**；⑤ clone 與 push 都用 node 上既有的憑證，**與 V2.2 逐位元組相同**。開啟時 `04b-…md` 的全部規則適用 | **2026-08-13 裁決**：「平台下放 git 憑證涉及較廣。可以實作，但由環境變數控制、預設不開放。現階段 git 認證以 node 端手動配置為準，平台不管，交給 node owner 自行處理。」**① 是本條最容易做錯的一格**：允許建立但永不使用，會產生一枚存得下來卻什麼都不做的憑證——而本 repo 已經對這個形狀表過態（`plan/18/02` 拒絕預建一張不授權任何東西的 `project_agents`：「一個不授權任何東西的授權表，會讓安全審查失去一個真正的檢查點」）。**旗標是 Central 的，不是 node 的**：決定「平台要不要管 git 憑證」是部署層的一次選擇，而 node 端已經有 `accept_secrets` 這個方向相反的開關（node 拒收），兩者不重疊 |
| D6 ⚠️ | **去識別包住 `send`，不是包住 `chunkSink`** | daemon 端一個 `Redactor`，持有本次 run 收到的所有機密值；`executeRun` 的 `send` 閉包在 `write` 之前，對 payload 裡**每一個字串值**做替換。`chunkSink` 因此自動被涵蓋 | `run.failed` 的 `message` 帶的是 git 的 stderr（`run_handlers.go:221`），`run.complete` 的 `summary` 是自由文字，`run.progress` 的 `message` 也是。只包 log 會讓最可能出現憑證的那條路徑（**git 的錯誤訊息**）沒有被包到。**規劃說的「換掉 0.9.0 的 no-op 掛勾點」不成立——那個掛勾點不存在**（`grep -rn Redactor daemon/` 只命中 `metrics.go` 的一句註解） |
| D7 ⚠️ | **`GIT_ASKPASS` 從 `/bin/false` 換成一支不含機密的 helper，而其餘兩個 fail-fast 變數保留** | run 目錄內寫一支 0700 的 `askpass.sh`，內容是 `printf '%s' "$CLIORA_GIT_PASSWORD"`——**它自己不含機密**，值在 daemon 傳給 git 的環境裡。`GIT_TERMINAL_PROMPT=0` 與 SSH 的 `BatchMode=yes` 完全保留 | `gitfetch.go:92` 把 `GIT_ASKPASS=/bin/false` 寫死，而那是出口條件 9（缺憑證秒級失敗，實測 2.7 秒）成立的原因之一。PAT 這條路徑要的正是同一個變數，所以兩者必須**一起成立**而不是二選一：helper 在沒有值時輸出空字串 → git 認證失敗 → 仍然是秒級失敗。**被否決**：把 token 塞進 remote URL（出現在 `git remote -v`、reflog 與錯誤訊息，而 contract 的 URL pattern 已經讓它不可表示）；`-c http.extraHeader`（出現在 `ps`）；`git credential-store`（那是一個檔案） |
| D8 ⚠️ | **SSH 用 `ssh-agent` ＋ `ssh-add -` 從 stdin，socket 在 run 目錄內 0700，run 結束 kill** | daemon 為每個需要 ssh 的 run 起一個 agent，`SSH_AUTH_SOCK` 只進 daemon 的 git 環境（D5）。`GIT_SSH_COMMAND` 保留既有的 `BatchMode=yes` ＋ `StrictHostKeyChecking=yes` ＋ known_hosts pinning | 私鑰**永不落檔**。**不得**寫一個 0600 私鑰檔再刪除——那違反不落檔規則，而且刪除失敗就留在磁碟上。**`socket 不是金鑰`**：這句要明寫進 ADR 0032，否則實作時很容易退回「寫個 0600 檔案就好」 |
| D9 | **`isolate_ambient_credentials` 只對「這次 run 真的收到了平台的 git 憑證」生效**（設定值與預設 `true` 都不變，**改變的是它什麼時候被套用**） | 收到平台憑證 → A：run 子程序的 `HOME` 與 `GIT_CONFIG_GLOBAL` 指向 run 目錄內一份最小設定，讓機器原本的 credential helper 與 ssh key 對它不可見（可關成 B ＝只疊加）。**沒有收到平台憑證（＝預設組態）→ 完全不套用**，ambient 原樣可用 | 2026-08-11 裁決的理由是「可撤銷的憑證旁邊不該有一份不可撤銷的」，而**那個理由只在真的有平台憑證時成立**。2026-08-13 之後下放預設關閉，所以照字面實作 A 的後果是**藏起 ambient 憑證、而沒有任何東西取代它**——預設組態下每一次私有 repo 的 clone 都失敗，而症狀看起來像「憑證設錯了」。⚠️ **A 能做到什麼仍要誠實寫**：它讓 git 看不到那些憑證，**它不是沙箱**——run 子程序與 agentd 同一個 OS 使用者，`~` 底下的東西它讀得到（`plan/18/04b-…md` §3.4 的同一個誠實性）。A 買到的是「預設路徑上不會誤用」，不是「不可能用」。**連帶：M-AR-6 從擋開工降級為上線後觀察**——它原本決定的是這個預設值，而那個爭議已被裁決本身解掉 |
| D10 ⚠️ | **五條硬約束的主詞是平台的 push 路徑，而它們與用哪一種憑證無關** | 五條寫死在 `daemon/internal/gitfetch/push.go` 的封閉 argv 表裡，各配一條測試。**無論這次 push 用的是平台下放的憑證還是 node 上既有的憑證，五條都適用。** Agent 自己的 git 行為不在其範圍——2026-08-10 ② 未被本期撤銷 | `research/02/00` §7 的紅線 4 已於 2026-08-11 把主詞改成「平台代表卡片執行的 push」，本期**引用它而不是再改一次**。🆕 **2026-08-13 之後要寫的一句**：預設組態下平台是拿**機器的**憑證推的，所以「可撤銷」在預設路徑上**不成立**——收斂點回到 node 的部署姿態與紅線 5（沒有人 merge 的分支不影響任何人）。**這一句要寫進 ADR 0031 的 amend 與 release note**，因為它是這條裁決最容易被忽略的後果：平台開始 push 了，而它推的憑證平台管不到 |
| D11 ⚠️ | **兩個資格查詢共用一個述詞函式** | 新增 `_tag_match_clause(runner)` 與 `_tag_match_py(runner, task)`，`_eligible()` 用前者（SQL），`_eligible_runner_count()` 用後者（Python）。**兩者由同一組參數化測試餵同一批案例** | `runs.py` 有兩個判資格的地方（`_eligible` 與 `_eligible_runner_count`），只改前者會讓畫面說「等待可用的 Agent」而其實是「沒有 runner 有這些 tag」——出口條件 9 要擋的正是這件事。**`GATE-SC-TAG-BOTH-QUERIES`** 用 `ast` 斷言那兩個函式都引用了述詞，而不是各自寫一份條件 |
| D12 | **`run_untagged` 未帶時視為 `true`** | migration 的 server default 是 `true`；`RunnerService.register` 對缺欄位的 payload 填 `True`；contract 把它列為 optional | 與預設值一致，所以升級前後行為不變。**這條的測試不依賴任何 daemon 版本號**——它斷言的是 payload 的形狀，而那比「0.9.0 的行為」可測得多（`daemon/VERSION` 現在是 `0.8.0`，見 D21） |
| D13 ⚠️ 🆕 | **daemon 的 tag 上報排在 Central 的比對之前** | `SC-07` 的第一件事：`config.RunnerConfig` 加 `Tags []string` 與 `RunUntagged *bool`，`runnerRegisterPayload` 從寫死的 `[]string{}` 改成讀設定。**`SC-05` 的驗收要用一台真的報了 tag 的 runner**，不是用 SQL 直接改 `agent_runners.labels` | `run_handlers.go:52` 目前寫死 `"labels": []string{}`，**沒有任何設定值可以讓它非空**。先做 Central 而不做 daemon，本期的驗收會全部用手改 DB 完成，而上線第一天每一張宣告 tag 的卡片都沒人領。**波次順序因此與 V2.2 不同**：節點半的一小塊要插在 Central 的派工半之前（§4） |
| D14 | **`agentd doctor` 印 tag、`run_untagged`、機密姿態三項** | 三行：`runner.tags`、`runner.run_untagged`、`accept_secrets`。沿用既有 doctor 的 `[ OK ]`／`[WARN]` 版面（`commands.go:69`） | 「這台為什麼領不到卡」與「這台為什麼拿不到機密」是本期最常見的兩個問題，而它們的答案都在 node 的設定檔裡。沒有這三行只能靠猜，而 doctor 已經是那個問題的既有答案（`update/systemd.go:127` 連 update 的健康檢查都在跑它） |
| D15 | **分支在 daemon 端建立，名字由 Central 給** | `run.offer` 的 `spec` 新增 `branch`（optional，`^cliora/` pattern）。Central 依 `<card_ref>-<run_seq>` 組出來，daemon 只驗前綴並 `git checkout -b` | 名字的兩個成分（`card_ref`、`seq`）都在 Central 手上，daemon 沒有。**但 daemon 仍然要驗前綴**——五條硬約束是 daemon 的責任，一條「Central 保證會送對」的約束不是約束 |
| D16 | **`delivery: branch` 本期支援，`pull_request`／`existing_pr` 仍 409** | `UNSUPPORTED_DELIVERIES` 只拿掉 `"branch": "V2.3"` 那一列 | `runs.py:93`。錯誤訊息維持「從 V2.4 起生效」而不是「不支援」 |
| D17 | **`project_repositories` 的三個憑證欄本期補上，SSH＋PR 的組合在設定畫面擋下** | `auth_kind`（`ambient`／`pat`／`ssh`，預設 `ambient`）、`credential_secret_id`、`provider_token_secret_id`，後兩者 FK → `project_secrets` | `models.py:847` 已經替本期留了這三個名字。**`ambient` 是新的一個值**而不是規劃寫的兩值：V2.2 登記過的 repository 全都在用機器的憑證，沒有這個值就沒有一個誠實的 backfill（把它們填成 `pat` 而 `credential_secret_id` 為 null 是一個說謊的資料列） |
| D18 | **沒有 `project_agents`，而這件事要寫在會被讀到的地方** | 不建表。**`SC-01` 逐處改寫九個仍寫著「V2.3 會加綁定」的程式註解**，`GATE-SC-NO-BINDING-PROMISE` 掃描 | 那九處在 `rbac.py`、`agents.py`、`runs.py`、四支 migration、`dto.ts`、`AgentsView.vue`——**RBAC 與安全審查都會讀到它們**。一句過期的承諾在這些位置上比在文件裡糟得多（`01-…md` §5） |
| D19 | **這一期不碰的東西** | `backend/app/services/{terminal_relay,terminal_queue,tunnels,integrations,node_update,files,favorites}.py`、`backend/app/security/secret_box.py`、`backend/app/api/ws/terminal.py`、`daemon/internal/{terminal,tmux,tunnel,update,workspace,systeminfo,session,files}`、`daemon/internal/runtime/{runtime,launch}.go`、`frontend/src/{terminal,monaco,protocol}`、`deploy/`（**除了 `.env.example` 與 `env.md` 的新變數**） | 判準寫死：diff 出現在上述任一處就是走錯路了。**與 `AR` 的兩個差別**：① `secret_box.py` 新增為禁區（D3）；② `daemon/internal/gitfetch/` 從新增變成**可修改**，但 argv 表的封閉性由 `GATE-SC-PUSH-ARGV` 守 |
| D20 ⚠️ | **本期觸發安全審查，三節** | `docs/security-review-v23.md`：① **機密的儲存與下放**（加密、金鑰、不可讀回、稽核、`kind` 分流）；② **授權邊界**（代償四條逐條驗 ＋ 「沒有 UI 暗示 tag 是授權」的畫面斷言）；③ **git 寫入**（五條硬約束、兩種認證的不落檔、known_hosts） | `research/02/10` §6 明寫本期命中三條，且**第二節的形狀被 2026-08-12 改寫**：原本要審的是「綁定表這個檢查點」，現在沒有那個檢查點，所以改為**驗代償四條真的存在**。三節各自獨立，不合寫成一段「Agent 執行環境安全審查」 |
| D21 🆕 | **`SC-00` 先 cut `agentd 0.9.0`，本期發 `0.10.0`** | `daemon/VERSION` 現在是 `0.8.0`；`SC-00` 用一個獨立 commit 把它改成 `0.9.0`（V2.2 的內容早已寫完），本期結束時改成 `0.10.0` | V2.2 的 daemon 功能全部寫完但版本從未 cut（`git log -- daemon/VERSION` 最後一次是 `62d80e6`，V2.1）。不 cut 的後果有兩個：`node_update` 的版本序失去意義（0.8.0 直接跳 0.10.0，中間那個「有 runner 但沒有機密」的階段從此不存在，而它是一個**真的可以部署的組態**）；以及本期的相容性測試沒有一個真的舊版本可以對。**被否決**：直接 cut 0.10.0（省一個 commit，但讓「舊 daemon」在測試裡變成一個想像的東西）；把版本號當成無所謂（`TestVersionMatchesTheVersionFile` 存在正是因為有人這樣想過） |
| D22 | **下放稽核記名稱、不記值，而且記在**認領**的那一刻** | 一筆 `audit_logs`：`run_id`、`project_id`、`runner_id`、`secret_names`（陣列）、`key_version`。**沒有值、沒有長度、沒有指紋** | 長度會洩漏資訊，指紋（`secret_box.fingerprint` 的那種）在這裡是**多餘且有害**的——它服務的是「我上週輪替的是不是這一枚」，而機密頁上有 `rotated_at` 可以答同一個問題。記在認領那一刻而不是 run 結束：**run 可能永遠不結束**，而「這台機器拿到過這幾個名稱」是一個已經發生的事實 |

## 4. 波次與 ticket

| 波次 | Ticket | 標題 | 依賴 |
|---|---|---|---|
| **0（閘門）** | `SC-00` | 基線擷取 ＋ **M-SC-1／M-SC-2** ＋ **cut `agentd 0.9.0`**（D21） | — |
| | `SC-01` | **ADR 0032**（§0 授權邊界）、PRD §8.14、skill、traceability、**過期承諾清單** | `SC-00` |
| | `SC-02` | ADR 0031 增補：git 送回半邊 | `SC-00` 的 M-AR-6 |
| | `SC-02b` | ADR 0029 增補：tag 派工 | `SC-01` |
| **1（資料）** | `SC-03` | migration `0033`／`0034` ＋ 模型 ＋ **`ambient` 這個 backfill 值**（D17） | 三份 ADR 核准 |
| **2（節點・先做這一小塊）** | `SC-07a` | 🆕 **`runner.tags`／`runner.run_untagged` 的設定與上報 ＋ `doctor`**（D13） | `SC-03` |
| **3（Central）** | `SC-04` | Secret store：信封加密、金鑰驗證、service ＋ API、下放稽核（**安審第一節**） | `SC-03` |
| | `SC-05` | 五條件資格判定、兩個查詢共用述詞、dispatch 409、反向查詢 | `SC-03`／`SC-07a` |
| | `SC-06` | contract v1.12.0 ＋ fixtures ＋ **出口方向的訊框大小檢查**（D2） | `SC-04` |
| **4（節點）** | `SC-07` | `agentd` 0.10.0 的機密面：接收、`kind` 分流、去識別、ambient 隔離 | `SC-06` |
| | `SC-07b` | git 面：`GIT_ASKPASS` helper、`ssh-agent`、分支、push 與五條硬約束（**安審第三節**） | `SC-07` |
| **5（前端）** | `SC-08` | Secrets、Repository 認證、卡片 tag／機密輸入、Agents 頁、**enrollment 文案**、Run 詳情 | `SC-04`／`SC-05` |
| **6（收尾）** | `SC-09` | 測試、雙旗標關閉回歸、十個 gate、安審定稿、release note、**合併提案並停下來** | 全部 |

**`SC-07a` 從節點半切出來排在 Central 之前**，這是本期與 V2.2 最大的順序差異，
理由是 D13：Central 的 tag 比對如果先上線，本期的每一次驗收都會靠手改 `agent_runners.labels`
完成，而那個欄位在真實部署裡永遠是空的。**先讓一台真的 runner 報出 tag**，再讓 Central 比對它。

**閘門一：`SC-00` 的基線完成前不得動任何程式碼。**
（`agentd 0.9.0` 的 cut 是 `SC-00` 內的獨立 commit，它動的是 `daemon/VERSION` 一個檔，
**基線要在它之前擷取**，否則「本期之前 daemon 是什麼版本」這句話會自相矛盾。）

**閘門二：`SC-01` 核准前不得動 `backend/`、`frontend/`、`daemon/`、`contracts/`。**
skill 範圍句要補的是本期唯一一個 V2.2 沒有的面：**平台代表卡片執行 git 寫入**。
（`.agent/skills/.../SKILL.md` 寫著「不得在沒有需求變更的情況下引入 Git automation」，
而本期就是那個需求變更——`research/02/11` §5 已經把它列進必須同步的文件。）

**閘門三：`SC-02` 要在 `SC-07b` 開工前接受。**
（原本它還依賴 M-AR-6 的值；2026-08-13 裁決之後不再依賴——git 憑證預設不下放，
D9 的隔離也就不生效，那個爭議在預設組態下不存在。）
**閘門四：`SC-04` 的安全審查第一節要在該票合併前定稿**（機密的儲存面一旦寫進 DB 就沒有回頭路）。

**波次 4 可以整批延後而不擋波次 1／2／3／5 的大部分。** 機密存得下來、tag 派得動、
畫面看得到，是一個可以獨立交付的成果，只是判準 10–12 未達成、本期不得標為完成。

## 5. 風險

| 風險 | 徵狀 | 處置 |
|---|---|---|
| **機密外洩到 log** | 值出現在使用者看得到的 log 或摘要裡 | D6 的整格 ＋ 判準 10 的三處斷言。**ADR 要誠實記錄「編碼後的值可能漏網」**（base64／URL-encode），第二道是可撤銷 ＋ 保留期，不是宣稱做得到 |
| **機密外洩到 API／UI** | 一個回應裡有值 | 沒有任何回傳路徑 ＋ 判準 1 的**兩條**斷言（schema 掃描與實際回應）。`GATE-SC-NO-SECRET-IN-RESPONSE` |
| ⚠️ 🆕 **平台開始 push 了，而它推的憑證平台管不到**（2026-08-13 裁決接受的代價） | 預設組態下 push 用的是 node 上既有的憑證。「哪台機器能推哪個 repo」平台答不出來，也撤銷不了 | **這不是可以對策掉的東西，它是範圍宣告。** 五條硬約束仍然完整適用（它們約束的是**推什麼**，與用哪一種憑證無關）；收斂點是 node 的部署姿態（`dedicated`）與紅線 5。要把它收回平台管理，就是把 `CLIORA_GIT_SECRET_DELIVERY_ENABLED` 打開。**這一句要進 ADR 0031 amend 與 release note**——它是這條裁決最容易被忽略的後果 |
| 🆕 **旗標關閉時仍然把 ambient 憑證藏起來** | 預設組態下每一次私有 repo 的 clone 都失敗，而症狀看起來像「憑證設錯了」 | D9：隔離**只對真的收到平台憑證的 run 生效**。出口條件 11c 直接斷言 `HOME`／`GIT_CONFIG_GLOBAL` 未被改寫 |
| 🆕 **允許建立 git kind 的機密但永遠不下放** | 一枚存得下來卻什麼都不做的憑證，而使用者以為設好了 | D5b ①：旗標關閉時**建立就被拒並指名那個變數**。本 repo 已經對這個形狀表過態（`plan/18/02` 拒絕預建 `project_agents`） |
| ⚠️ **平台發出的憑證同時落在 Agent 手上**（**只在旗標開啟時**） | Agent 用平台的 PAT 推到一個平台不知道的地方，而稽核上只看得到「下放了 `GITHUB_TOKEN`」 | **D5 的 `kind` 分流是這條的整個處置** |
| **`GIT_ASKPASS` 換掉之後「缺憑證秒級失敗」不再成立** | 使用者又看到「跑了很久然後失敗」 | helper 在沒有值時輸出空字串，`GIT_TERMINAL_PROMPT=0` 保留；出口條件 9 **在本期重跑一次**（它是 V2.2 的條件，但本期動到了它成立的那個變數）。⚠️ **旗標關閉時 `fetchEnv` 一個位元組都不變**，所以那條路徑不受影響 |
| **PAT 洩漏到 `ps`／reflog／錯誤訊息** | 一個 token 出現在一行別人看得到的字裡 | helper 不含機密、URL 不可表示憑證（contract pattern）、不用 `-c http.extraHeader`；出口條件 6b 的**四處**斷言 |
| **SSH 私鑰落檔** | run 目錄裡有一個 0600 的 key 檔 | `ssh-add -` 從 stdin；出口條件 6c 的 run 目錄**全域搜尋比對**。`GATE-SC-NO-SECRET-TO-DISK` 用 `ast` 掃 daemon，斷言機密值不流向任何 `os.WriteFile`／`os.Create` |
| **git 推錯地方** | 遠端多了一條不該有的分支，或 `main` 被動了 | 五條硬約束寫死 ＋ 判準 12 的四種拒絕，**且拒絕發生在 daemon 內**（對真的 scratch 遠端跑一次，確認不是靠遠端拒絕） |
| **主金鑰與密文共用同一個信任邊界** | — | **這是環境變數方案的已知代價，不是可以對策掉的東西。** ADR 0032 §3 明寫；緩解靠 env 的取得權限管控 ＋ **KMS 升級路徑保持暢通**（信封加密 ＋ `key_version` 讓它只是換掉一個函式） |
| **主金鑰遺失 → 所有機密不可復原** | 還原了備份，機密全是亂碼 | 啟動時驗證 ＋ `docs/runbooks/backup-restore.md` 增訂（金鑰另外保管且需與 `key_version` 相符）＋ **機密設定頁上直接寫這句話**，不要只躺在 runbook 裡 |
| ⚠️ **授權邊界只有 enrollment** | 任何 enroll 過的機器，tag 對得上就能取得該卡宣告的機密 | **這不是可以對策掉的東西，只能縮小半徑。** 代償四條各綁一個出口條件（4／5／判準 1／出口條件 3g），安全審查第二節**驗這四條而不是驗一張表**。⚠️ 本期新增一句：`run.dispatch` 是 Developer 的動作，**沒有一層 Admin 授權擋在「指定一台 runner」與「它拿到機密」之間**（`01` D17b） |
| **tag 被誤當成安全機制** | 「我把卡片標成 `prod`，所以只有正式機拿得到」 | tag 是 runner **自報**的。UI 上 tag 欄位旁一律不出現鎖頭或「授權」字樣（出口條件 3g 是畫面斷言）；ADR 0029 amend 與 0032 §0 **各寫一次**「tag 不是授權」 |
| **tag 打錯字 → 卡片永遠沒人領** | 一張卡安靜地掛在佇列上 | 卡片編輯時以線上 runner 的**實際** tag 作建議並即時提示；空等狀態說得出缺哪個 tag（出口條件 3e／判準 9） |
| **只改一個資格查詢** | 畫面說「等待可用的 Agent」，而真相是「沒有 runner 有這些 tag」 | D11 的共用述詞 ＋ `GATE-SC-TAG-BOTH-QUERIES` |
| **`run.offer` 超過 64 KiB 被靜默丟棄** | 卡片被領走、沒有任何錯誤、租約到期、重排、三次後 `blocked` | D2 的兩道。**這條在本期之前就已經存在**（`context` 上限 65536），本期只是讓它從潛在變成可觸發，所以修它是本期的責任 |
| **九處程式註解承諾了一張不會存在的表** | 半年後有人照著 `rbac.py:79` 去找 `project_agents` | `SC-01` 逐處改寫 ＋ `GATE-SC-NO-BINDING-PROMISE`。**這不是文件整理**：那些句子出現在 RBAC 與安全審查會讀的位置上 |
| **`agentd` 版本序斷掉** | `node_update` 從 0.8.0 直接跳 0.10.0，而中間那個組態真的存在 | D21 的 `SC-00` cut |
| **Agent 根本不用平台給的機密** | 卡片宣告了三枚，run 一枚都沒讀 | 與 M2 同一條理由：這是內化路線的假設，不是 bug。情境包要多一段說明「這次執行有哪幾個環境變數可用」（`04-…md` §4.3）。M-SC-3 上線後量 |
