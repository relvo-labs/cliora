# 01 — `SC-00`／`SC-01`／`SC-02`／`SC-02b`：基線、ADR 與治理

本檔是波次 0。**它的產出全部是文件與一個版本號**，一行功能程式碼都沒有——
而閘門二寫著它核准前不得動 `backend/`、`frontend/`、`daemon/`、`contracts/`。

## 1. `SC-00` — 基線擷取

沿用 `plan/18` 的六份基線，**同一批擷取器，同一個目錄慣例**：
`artifacts/sc/local/baseline/`，全部取自同一個 commit。

| 檔案 | 內容 | 擷取／比對 |
|---|---|---|
| `COMMIT` | HEAD ＋ ISO 時間 ＋ 擷取當下未提交的路徑清單 | `scripts/ar/capture-baseline.sh`（**沿用，不新寫**） |
| `openapi-flags-off.json` | `CLIORA_PROJECTS_ENABLED=false CLIORA_AGENT_RUNS_ENABLED=false` | 同上 |
| `openapi-flags-on.json` | 兩個旗標都開。**與 flags-off 應逐位元組相同**——那個「相同」本身是要守的性質（`plan/18/09` §3 第 2 條），本期新端點也必須無條件掛載、靠 dependency 回 404 | 同上 |
| `schema.txt` | **36 張表**，`alembic revision: 0032_runner_pressure`（本行原寫「32 張表」，那是把 migration 編號當成表數的筆誤——AR 基線 28 張 ＋ V2.2 的 8 張 ＝ 36，已於擷取當下更正） | `scripts/pj/schema_snapshot.py --diff` |
| `contract-fixtures.txt` | 逐檔清單 ＋ sha256 | `scripts/tk/contract_snapshot.py --diff` |
| `frontend-routes.txt` | 路由表 | `scripts/ar/frontend_routes.py --diff` |
| `terminal-latency.json` | 50 samples 的 p50／p95 | `scripts/e2e/run-stack.sh scripts/ar/capture-baseline.sh --latency-only` |

**基線點以實際擷取當下的 `v2` HEAD 為準，並把它寫回這一行。**
（`plan/18` 寫死了一個 commit 然後在 `09` §3 第 1 條解釋為什麼不是那一個。
本計畫不重蹈：這裡不預先寫一個 SHA。）

**終端延遲基線在本期的用途與 V2.2 不同**：那時是為了「run log 不得讓終端變頓」，
本期是為了 **D6 的去識別**——它跑在 `send` 的路徑上，而那條路徑與終端共用一條 socket。
`SC-07` 要在同一台 node 上重量一次，判準是 **p95 不比基線高 20% 以上**。

### 1.1 `SC-00` 的另一件事：cut `agentd 0.9.0`（D21）

**一個獨立 commit，只動 `daemon/VERSION`**：`0.8.0` → `0.9.0`。

在基線擷取**之後**做，理由是基線要如實記錄「本期之前這個 repo 是什麼樣子」，
而「V2.2 的 daemon 功能已完成但版本從未 cut」正是那個樣子的一部分。

順帶補的兩件事：

- `docs/release-note-agent-runner.md` 補一行發布版本號（它現在沒有）。
- 確認 `TestVersionMatchesTheVersionFile` 仍綠——它存在的理由就是防止版本號與別處漂開。

**不做**：不觸發 `node_update`、不推給任何 node。發布時機是人的決定（`plan/18/09` §4 第 3 條）。

## 2. `SC-00` 的三項量測

完整判讀在 [`09-open-measurements.md`](./09-open-measurements.md)。這裡只寫它們**擋什麼**。

| 量測 | 問題 | 擋什麼 | 怎麼量 |
|---|---|---|---|
| ~~**M-AR-6**~~ | ambient 憑證在實務上拉得動私有 repo 嗎？ | ~~D9 的值~~ → **2026-08-13 裁決之後不擋任何票**（git 憑證預設不下放，隔離也就不生效）。**降級為上線後觀察**，而它答的問題變成「『交給 node owner』撐不撐得住」——撐不住的處置是打開旗標，不是調預設值（`09-…md` §1.1） | — |
| **M-SC-1** | 一枚 PAT、一把 ed25519 私鑰、一枚典型 env 機密各多大？一張卡典型宣告幾個？ | **contract 的三個上限**（單值／總量／個數）→ 擋 `SC-06` | 直接量：`gh` 的 fine-grained PAT 是 93 字元；ed25519 私鑰約 400 bytes；RSA-4096 約 3.2 KB。**RSA 是那條會撐爆預算的**，量完決定要不要在 UI 上勸退它 |
| **M-SC-2** | 去識別對每一個外送訊框做字串替換的成本？ | **D6 的實作層級**（`send` 閉包 vs 只在 log 路徑）→ 擋 `SC-07` | 對一個 32 KiB 的 chunk、5 個機密值跑 benchmark。**若 p95 增加超過終端延遲基線的 20%**，改為只對 `data`／`message`／`summary` 三個已知欄位做，而不是走遍整個 payload |

**兩項都不擋波次 0 與 1。** M-SC-1 擋 `SC-06`，M-SC-2 擋 `SC-07`。
（M-AR-6 在 2026-08-13 裁決之後不擋任何票。）
所以 ADR 0032、資料層、`SC-07a` 的 tag 上報都可以在量測還沒做完時開工。

**V2.2 遺留的兩項量測（M-AR-2、M-AR-9 的尾巴）不擋本期任何一張票**，
但它們仍在 `09-…md` 裡列著——沒有它們，`RUN_IDLE_TIMEOUT` 的 300 秒仍然是一個有根據的猜測。

## 3. `SC-01` — ADR 0032：機密管理與 SEC-002 修訂

**先寫這一份，因為它決定其餘工作包能不能開工。** 五段，順序不可調換。

### 3.1 §0 — 機密的授權邊界是 enrollment（**放最前面**）

它決定後面每一段的威脅模型，所以它在最前面。三件事：

> **發出一張 enrollment token，等於授權那台機器取用所有專案的機密。**

1. **`project_agents` 綁定表不做。** 理由與被否決的替代方案**照抄 `01` D18 的那張表**，
   包含「這是刻意用安全姿態換營運簡單」那一句。
   **「讓 tag 兼任授權」為什麼不行**要單獨寫一段：tag 是 runner 在 `runner.register` 裡
   **自報**的字串，一台被入侵或設定錯誤的 runner 只要多報一個 tag 就能改變自己領到什麼。
2. **爆炸半徑與代償四條**，每一條指向一個工作包與一個出口條件：

   | 代償 | 落在哪 | 出口條件 |
   |---|---|---|
   | 機密永遠是「這張卡宣告的那幾個」，且必須是 Project allowlist 的子集 | `SC-03`／`SC-04`／`SC-05` | 4 |
   | node 可宣告 `accept_secrets: false` | `SC-07` | 5 |
   | 可撤銷 ＋ 下放稽核（名稱，永不含值） | `SC-04` | 判準 1、出口條件 10 |
   | **enrollment 畫面的說明文字改寫** | `SC-08` | 3g |

   **四條各自對應一個可測的東西，不是一句宣言。**
3. **這一段是安全審查第二節的入口。** 原本審查要看的是綁定表這個檢查點；
   現在沒有那個檢查點，所以審查改為**驗代償四條真的存在**，
   且 **UI 沒有暗示有一個更強的邊界**。

⚠️ **本期要新增、`research/02/05` 沒寫的一句誠實記錄**：
`run.dispatch` 是 Developer 的動作，而指定一台 runner 之後那台機器就會拿到該卡宣告的機密。
**沒有一層 Admin 授權擋在中間**（`01` D17b 已經寫了，但它在 D17b 裡，
而讀 ADR 0032 的人不會回去讀 D17b）。收斂靠的是 enrollment 本身是 Admin 動作。

### 3.2 §1 — SEC-002 的精確修訂（D23）

只撤銷一句，argv／binary／shell string 完全保留，互動式 Session 完全不變。

| SEC-002 的內容 | 處置 |
|---|---|
| 呼叫端不得指定 command／binary／shell string | **完全保留** |
| 呼叫端不得指定環境變數 | **修訂為**：請求 payload 不得攜帶環境變數的**值**；值只能來自平台 secret store，名稱只能來自專案 allowlist |
| 互動式 Session | **完全不變** |

修訂後的不變式，一句話：

> **沒有任何請求 payload 能命名一個命令、或攜帶一個機密的值。**

**這一段要對著程式碼寫，不是對著規劃寫**：`run.offer` 的 `spec.secrets` 是
**平台從自己的 store 取出來的**，路徑是 `poll() → SecretService.materialise() → spec()`，
中間沒有任何一格接受呼叫端輸入。這句話要有一條 fixture 撐著：
**`secrets` 出現在 `run.offer` 以外的任何訊息 → 拒絕**（`04-…md` §2.2）。

### 3.3 §2 — 機密的九條規則（D22 的表）

加密儲存、永不可讀回、按需下放、不落檔、runner 端去識別、名稱 allowlist、
node 可拒絕、稽核不含值、可輪替可撤銷。

**本期要對第四條加一句細化**（D8）：

> **socket 不是金鑰。**

`ssh-agent` 的 socket 在 run 目錄裡、權限 0700、run 結束就消失。
**不寫這一句，實作時很容易退回「寫個 0600 私鑰檔再刪掉就好」**——
而那違反不落檔規則，且刪除失敗就留在磁碟上。

🆕 **第十條，本計畫新增**（D5）：**`kind` 決定機密去哪裡。**
`env` 進子程序的環境；`git_pat`／`git_ssh_key` 只進 daemon 自己的 git 環境；
`provider_token` 本期不下放。代價（Agent 不能自行 fetch／push）要寫在 Consequences，
不能只寫在 Decision。

### 3.4 §3 — 主金鑰在環境變數的代價

**這一段不能只寫好處。** 三句要寫出來：

- 金鑰與密文**共用同一個信任邊界**——能讀 env 的人通常也能讀 DB。
  這不是致命，但它意味著「DB 備份外洩」的防護仰賴攻擊者拿不到 env，而不是兩道獨立的防線。
- **沒有解密稽核**：不知道誰在何時解了什麼。
- **金鑰遺失即全部不可復原**，只能全部重建（每個 repo 的 token 都要重發）。

同時寫出讓它不變成死路的四件事：**信封加密**、**`key_version` 從第一天就有**、
**啟動時驗證**（D4 的條件式形狀要寫進去，不然日後有人照 ADR 改成無條件）、
**KMS 升級路徑**——有了信封與 `key_version`，改用 KMS 只是換掉「解開 DEK」那一個函式。

### 3.5 §4 — Alternatives rejected

**這一節不可省略任何一列**，尤其第一列：

| 方案 | 為什麼否決 |
|---|---|
| **`project_agents` 綁定表當機密的授權邊界** | 2026-08-12 否決。**照抄 `01` D18 的那張表**，包含「刻意用安全姿態換營運簡單」那一句。**這一列不能省略**，否則日後讀 ADR 0032 的人會以為沒人想過授權表 |
| runner 層級的 `secrets_enabled` 開關 | 同日否決：與 node 端 `accept_secrets` 重複且方向較差（會讓「哪些機器拿得到機密」變成兩個地方都要看） |
| 卡片直接寫 env 值 | 機密會進資料庫的明文欄位與 UI |
| runner 從 node 本機 `.env` 讀 | 平台無法稽核也無法撤銷 |
| 與 `tunnel_integration` 共用一張表／共用 `secret_box.py` | 風險等級不同、輪替時機不同，混用會讓規則互相污染（D3） |
| **主金鑰放 KMS** | 本次否決的理由是**新增雲端依賴且自架部署做不到**，**不是因為它比較差**。這句要寫，否則日後看起來像沒想過 |
| 🆕 **把 git 憑證一起放進子程序的環境** | D5。買到 Agent 的 git 自由，賠掉「可撤銷」的實際範圍，而五條硬約束攔不到它 |
| 🆕 **把 `run.offer` 放進 `LARGE_FRAME_TYPES`** | D2。那條 socket 同時載著互動式終端的二進位輸出，理由與 V2.2 拒絕放大 `run.log_chunk` 完全相同 |

## 4. `SC-02` — ADR 0031 的增補：git 送回

**目錄六條規則已在 V2.2 定稿，本階段不重寫**，只 amend。三段：

### 4.1 平台憑證加進來，而 ambient 憑證藏不藏是一個設定

> **⚠️ 2026-08-13 裁決先於這一段：git 憑證的下放預設不開放。**
> 所以本段描述的是一條 **`CLIORA_GIT_SECRET_DELIVERY_ENABLED=true` 才會走到的路徑**，
> 而 ADR 要在這一段的**開頭**就說明它，否則讀者會把它讀成預設行為。
>
> **同時要在 §4.2 之前寫的一句**：預設組態下平台是拿**機器的**憑證推的，
> 所以「可撤銷」在預設路徑上不成立——**平台開始 push 了，而它推的憑證平台管不到**。
> 收斂點是五條硬約束（它們與憑證無關）、node 的部署姿態與紅線 5。

已裁決（2026-08-11）：node 層設定 `runner.git.isolate_ambient_credentials`，
**預設 A（取代），可關成 B（疊加）**。
**2026-08-13 修訂它的語意（不是它的值）**：隔離**只對「這次 run 真的收到了平台憑證」
的情況生效**。否則預設組態下每一次私有 repo 的 clone 都會失敗——
藏起 ambient 憑證，而沒有任何東西取代它（D9）。

| | A：取代（**預設**） | B：疊加 |
|---|---|---|
| 機密的可撤銷性 | 完整 | 部分——Agent 仍可用機器的 |
| 與 2026-08-10 ② 的關係 | **收回了那個自由** | 保留 |
| 五條硬約束的實效 | 對平台的 push 完整有效；**Agent 也無路可繞**（配合 D5） | 對平台有效，Agent 仍可繞 |
| 適用場景 | 共用的 runner node | 專用的 runner node |

**A 能做到什麼要誠實寫**（D9）：它讓 git 看不到那些憑證，**它不是沙箱**——
run 子程序與 agentd 同一個 OS 使用者。A 買到的是「預設路徑上不會誤用」，不是「不可能用」。

**開工前複核的是值不是形狀**（M-AR-6）。

### 4.2 git 的五條硬約束（寫死在 daemon，各配一條測試）

1. 只能推 `cliora/<card_ref>-<run_seq>` 前綴的分支。
2. 永不推 base／target 分支——`target_branch` 是「PR 合併回哪裡」，不是推送目標。
3. 永不 force push、不刪遠端分支、不動 tag。
4. remote allowlist：只能推到該 Project 登記的 repository host。
5. commit trailer 帶 run id，作者是 bot identity，不冒充人類。

**主詞是平台的 push 路徑**（D10）。`research/02/00` §7 的紅線 4 已於 2026-08-11 改好，
本 ADR **引用它而不是再改一次**。

🆕 **要一起寫的一句**：旗標開啟且選 A 時，D5 讓 Agent 連平台的憑證也拿不到，
所以在**那個**組態下 2026-08-10 ② 給的 git 自由實際上被收掉了。
⚠️ **那不是預設組態**——預設路徑上機器的憑證還在，Agent 的 git 自由完整保留。
兩句都要寫進 release note，而且要標清楚哪一句對應哪一個組態。

### 4.3 Alternatives rejected

讓 run 目錄落在 allowed root 內（兩套授權模型互通）、每次完整 clone（V2.2 已用 M11 否決，
本期只引用）、**允許 Agent 自行決定推送目標**（那條約束一旦是設定值就等於沒有）、
🆕 **把五條約束做成 Central 端檢查**（daemon 才是握著 remote 的那一端；
一條「Central 保證會送對」的約束不是約束——D15 的同一個理由）。

## 5. `SC-02b` — ADR 0029 的增補：tag 派工

tag 比對是**派工路由**，不是目錄與 git 存取，所以它 amend 的是 ADR 0029。四段：

1. **配對只有兩層**：tag（能力與路由，runner 自報 ＋ 卡片宣告）／
   `assigned_runner_id`（意圖）。**沒有第三層**——理由指回 ADR 0032 §0，
   **不在這裡重複論證**（授權是機密的問題，不是派工的問題；兩份 ADR 各講一次會開始互相偏移）。
2. **資格判定的最終五條件**：`ready` ＋ `dependsOn` 滿足 ＋ runtime 相符
   ＋ **tag 相符** ＋ 指定為 null 或等於該 runner。
3. **GitLab 語意**：`required_labels ⊆ runner.labels`；卡片沒宣告 tag 時
   runner 需 `run_untagged = true` 才會被 offer；tag 是自由字串，不做預先註冊的字典。
4. **比對在 Central，不在 runner。** 平台是唯一的 offer 來源，把過濾放在 runner 端
   等於信任 runner 的自我克制；更實際的理由是**「這張卡為什麼沒人領」必須在平台端答得出來**
   ——那是一個查詢（`03-…md` §3），不是一句文案。

**Alternatives rejected**：綁定表與「tag 兼任授權」（`01` D18，本 ADR 只引用）、
**完全相等比對**（runner 多一個 tag 就領不到卡，實務上不可用）、
**平台端覆寫 runner 的 tag**（會有兩個真實來源：node 重連時 `runner.register` 會把
平台上的編輯蓋掉。tag 是 runner 對自己能力的宣告，**改 tag 就是改 node 上的設定檔**，
UI 只顯示不編輯）。

## 5b. `SC-01` 的第二件事：過期承諾清單（D18）

**這不是文件整理。** 下面九處寫著「V2.3 會加 `project_agents` 綁定」，
而 2026-08-12 把那張表取消了——它們從「尚未發生」變成「不會發生」，
且其中三處在 RBAC 與 API 的說明文字裡，安全審查會讀到。

| # | 位置 | 現在寫什麼 | 改成 |
|---|---|---|---|
| 1 | `backend/app/services/rbac.py:79` | 「V2.3's `project_agents` narrows it」 | 授權邊界**永久**是 enrollment；縮小半徑的是代償四條 |
| 2 | `backend/app/services/rbac.py:145` 附近（`PROJECT_MANAGE` 註解） | 「From V2.3 a binding means more again」 | `project.manage` 的理由改為「決定哪些專案存在、以及它們的機密名稱 allowlist」 |
| 3 | `backend/app/services/rbac.py:152` 附近（`AGENT_MANAGE` 註解） | 「From V2.3 it also covers binding a runner to a project」 | `agent.manage` 是**對運算資源的處置**（停用 runner、調整並行度）；**不含編輯 tag** |
| 4 | `backend/app/api/http/agents.py:221` | 「binding arrives in V2.3」 | 同 #1 |
| 5 | `backend/app/api/http/agents.py:250/252` | 「There is deliberately no binding endpoint: `project_agents` arrives in V2.3」 | **保留「刻意沒有綁定端點」這句**，把理由從「延後」換成「取消」並指向 ADR 0032 §0 |
| 6 | `backend/app/services/runs.py:458–463`（`_eligible` docstring） | 「`project_agents` — V2.3 adds the join, and it goes first」 | 改寫成五條件，第四條是 tag；**這一段是 `SC-05` 一定會改到的地方**，順手改對 |
| 7 | `0029_agent_runs.py:37/40` | 「It arrives in V2.3 alongside `project_secrets`」 | migration 是歷史紀錄，**加一段 2026-08-12 的註記，不改原文** |
| 8 | `0022`／`0030` seed migration | 「From V2.3 a binding means more again」 | 同 #7 的處置 |
| 9 | `frontend/src/api/dto.ts:777`、`frontend/src/views/AgentsView.vue:140` | 「逐專案的授權自 V2.3 起提供」 | **這一句是錯的且使用者看得到**——`SC-08` 改成代償四條的說法 |

**`GATE-SC-NO-BINDING-PROMISE`**：掃 `backend/app/`、`frontend/src/`、`daemon/` 裡
同時出現 `project_agents` 與 `V2.3`／`arrives`／`即將`／`起提供` 的行，
**migration 目錄除外**（那是歷史紀錄）。

## 6. PRD、skill 與 traceability

### 6.1 `research/prd.md` §8.14

**ID 族已經在 `research/02/11` §2 登記過了（FR-RUNENV-001…011），本票不另編號。**
本期要做的是替每一條寫 AC 並登記到 `traceability/requirements.json`：

| ID | 一句話 | AC 數（目標） |
|---|---|---|
| FR-RUNENV-001 | Secret store：加密儲存、**任何 API 都讀不回值**、可撤銷 | 7 |
| FR-RUNENV-002 | 按需下放：只送卡片宣告的、須為 allowlist 子集、稽核不含值 | 6 |
| FR-RUNENV-003 | 去識別在 runner 端，原值不離開 node | 5 |
| FR-RUNENV-004 | node 可宣告 `accept_secrets: false` | 3 |
| FR-RUNENV-005 | 隔離工作目錄（**V2.2 已交付，本期只回歸**） | — |
| FR-RUNENV-006 | Git 取得（**V2.2 已交付**；⚠️ 該條寫的是 bare mirror，而實作採淺 clone，`plan/18/09` §3 第 11 條——本期順手把那一格改對） | — |
| FR-RUNENV-007 | Git 推送約束：五條硬約束、四種違規全部在 daemon 內被拒 | 8 |
| FR-RUNENV-008 | **tag 派工**：五條件資格判定、`run_untagged`、空等原因說得出缺什麼 | 8 |
| FR-RUNENV-009 | **平台管理的 git 憑證（預設關閉）**：總開關、兩種認證的不落檔、隔離的條件式生效 | 9 |
| FR-RUNENV-010 | 授權邊界的誠實揭露（代償四條 ＋ 三處畫面斷言） | 5 |
| FR-RUNENV-011 | 🆕 **機密的 `kind` 決定它去哪裡**（本期新增，已回寫上游） | 4 |

⚠️ **FR-RUNENV-002 是「信封加密與金鑰」該掛的地方，而上游沒有替它單獨開一條。**
主金鑰的啟動驗證、`key_version`、`rewrap` 三件事寫成 002 的 AC，
**不要為它新開一個 ID**——上游的 ID 族已經定稿，多一條會讓兩份文件開始偏移。

**lifecycle 一律先進 `proposed`**，理由與 `plan/18/09` §3 第 13 條相同：
翻 `active` 之後 coverage 會要求每個 AC 都有四種連結，而其中幾條
（如 FR-RUNENV-007 的 SSH 路徑）要一台有 `ssh-agent` 與真遠端的機器才驗得了。
**翻 `active` 與出口條件的 Traqora 實跑同時發生**，那是人工事項。

### 6.2 skill

`.agent/skills/cliora-project-context/SKILL.md` 明文寫著：
不得在沒有需求變更的情況下引入 **Git automation**。
**本期就是那個需求變更**——把那一句改寫成「平台代表卡片執行的 git 寫入限於
推送 `cliora/` 前綴的分支，由 ADR 0031 的五條硬約束界定」，並指向 FR-RUNENV-006。

**不要把那句話刪掉。** 它的價值在於下一個想加 git 功能的人會撞到它。

### 6.3 `research/02/11` 的回寫

實作完成後回寫兩格（沿用 `plan/18/09` §3 第 7 條的慣例）：

- ADR 0029 的那一列：V2.3 amend 的內容確實是 tag 派工而不是綁定。
- FR-AGENT-003 的「五條件」在本期真的成立了，把它從「V2.3 起」改成已交付。
