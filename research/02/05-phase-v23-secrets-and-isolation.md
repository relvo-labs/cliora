# V2.3 — 機密下放、git 送回與 tag 派工（ticket 前綴 `SC-`）

> **⚠️ 2026-08-13 裁決：git 憑證的下放預設不開放。**
>
> > 平台下放 git 憑證涉及較廣。**可以實作，但由環境變數控制、預設不開放。**
> > 現階段 git 認證**以 node 端手動配置為準**——那部分系統不管，交給 node owner 自行處理。
>
> 本階段因此變成**兩個交付面 ＋ 一個預設關閉的第三面**：
>
> | 面 | 狀態 |
> |---|---|
> | **機密下放（`kind: env`）** | 本期主路徑，預設開啟 |
> | **tag 派工** | 本期主路徑，預設開啟 |
> | **git 送回**（分支、push、五條硬約束） | 本期交付，**用 node 上既有的 ambient 憑證推**（與 V2.2 的 clone 同一種來源） |
> | **git 憑證下放（`kind: git_pat`／`git_ssh_key`）** | 機制照做，**由 `CLIORA_GIT_SECRET_DELIVERY_ENABLED` 控制，預設 `false`** |
>
> 三處連帶修訂，逐條落在下面：SC-02 的 `isolate_ambient_credentials`（只對真的收到平台憑證
> 的 run 生效）、SC-04b（整條路徑 flag 化）、SC-06（Repository 的認證選項預設不可選）。
> 決策全文在 `01` D20 的 2026-08-13 裁決。

> **執行計畫在 [`plan/20/`](../../plan/20/README.md)。**
> 它讀的是程式碼，本文件讀的是構想——**兩者不一致時以執行計畫為準**。
> 已知的十一處偏離見 `plan/20/README.md` §「與 `research/02/05` 的差異」，
> 其中兩處需要人接受代價（`kind` 分流、九處過期的程式註解）。

> **2026-08-10 裁決改寫本階段的範圍。**
> 隔離工作目錄（D19）與 git 的**取得**半邊（D20）已經在 **V2.2** 交付——
> Agent 自己把專案拉到 `<state>/.cliora/runs/<run_id>/`，workspace 綁定只服務互動式 Session。
>
> | 從 V2.3 移出（已在 V2.2） | 移入 V2.3（原本在別處） |
> |---|---|
> | run 目錄的六條規則、配額、清理、mirror 快取 | ~~`project_agents` 綁定（D18）~~ → **2026-08-12 取消，見下** |
> | `clone`／`fetch`／`checkout`／`worktree add` | **tag 比對**（D18）——原本是「後續功能」，現在提前到本期 |
> | host allowlist、known_hosts pinning | |
>
> **⚠️ 2026-08-12 裁決（Agent 配對）再次改寫本階段：`project_agents` 綁定表不做了。**
> 原本本期要交付的「綁定＝機密授權邊界」整條移除，換上的是 **tag 比對**（派工路由）。
> 兩者不是替代關係——tag 解決的是**派給哪台機器**，不解決**哪台機器可以拿機密**。
> 後者的答案從此是：**enrollment**。這是刻意的取捨，代償四條見 `01` D18，本期逐條落地。
>
> 搬動表見 `04-phase-v22-agent-runner.md` §0。**本階段仍是 V2 安全面最重的一階段**：
> 它要把 V2.2 那份「用 node 上 ambient git 憑證」的權宜作法換成平台管理、範圍受限、可撤銷的憑證。

## 目標

把 V2.2 的 run 從「在隔離目錄裡用**機器本來就有的** git 認證拉程式碼、成果只能附成產物」
變成「帶著**平台下放的、範圍受限的、可撤銷的**機密，而且能把分支推回去」。

三件事：**機密**（新的儲存面）、**git 送回**（新的對外副作用）、
**tag 派工**（讓「這類卡片給這類機器」成為 offer 查詢裡的一個條件，而不是靠人逐張指定）。

## 前置條件

- V2.2 出口條件全數通過（**含隔離目錄與 clone 的那七條**）。
- D18（**2026-08-12 改寫版**：不綁定、tag 比對、授權邊界是 enrollment）、D20（送回半邊）、D21、D22、D23 已裁決。**2026-08-08 補齊**：主金鑰放**環境變數**；git 認證**同時支援 fine-grained PAT 與 SSH key**。
- **ADR 0031 已在 V2.2 發佈**（目錄六條規則 ＋ git 取得）；本階段**增補**它的送回半邊。
- ADR 0032（機密管理與 SEC-002 修訂）已撰寫並接受。

## 工作包

### SC-01 — ADR 0032：機密管理與 SEC-002 修訂（**先寫這一份**）

放在最前面，因為它決定其餘工作包能不能開工。

要交付的五段：

0. **機密的授權邊界是 enrollment**（D18，2026-08-12 裁決）——**這一段放在最前面**，
   因為它決定後面每一段的威脅模型。要寫的是三件事：

   > **發出一張 enrollment token，等於授權那台機器取用所有專案的機密。**

   - **`project_agents` 綁定表不做**，理由與被否決的替代方案照抄 `01` D18 的那張表
     （尤其是「讓 tag 兼任授權」為什麼不行：tag 是 runner 自報的）。
   - **爆炸半徑與代償四條**：卡片級 `required_secrets`（SC-03／SC-04）、
     node 端 `accept_secrets: false`（SC-04）、下放稽核與可撤銷（SC-03）、
     **enrollment 說明文字的改寫**（SC-06）。四條各自對應一個工作包，不是宣言。
   - **這一段是 V2.3 安全審查的入口**（`10` §6）。原本審查要看的是綁定表這個檢查點；
     現在沒有那個檢查點了，所以審查改為驗證代償四條真的存在、且 UI 沒有暗示有一個更強的邊界。

1. **SEC-002 的精確修訂**（D23）：只撤銷「呼叫端不得指定環境變數」中關於**值**的那一句，argv／binary／shell string 完全保留，互動式 Session 完全不變。修訂後的不變式一句話：

   > 沒有任何請求 payload 能命名一個命令、或攜帶一個機密的值。

2. **機密的九條規則**（D22 的表）：加密儲存、永不可讀回、按需下放、不落檔、runner 端去識別、名稱 allowlist、node 可拒絕、稽核不含值、可輪替可撤銷。

3. **主金鑰在環境變數的代價**（D22）——**這一段不能只寫好處**：金鑰與密文共用同一個信任邊界、沒有解密稽核、金鑰遺失即全部不可復原。同時寫出讓它不變成死路的四件事（信封加密、`key_version`、啟動時驗證、**KMS 升級路徑**）。

4. **Alternatives rejected**：**`project_agents` 綁定表當機密的授權邊界**（2026-08-12 否決——
   照抄 `01` D18 的那張表，包含「這是刻意用安全姿態換營運簡單」那一句；
   **這一列不能省略**，否則日後讀 ADR 0032 的人會以為沒人想過授權表）、
   **runner 層級的 `secrets_enabled` 開關**（同日否決：與 node 端 `accept_secrets` 重複且方向較差）、
   卡片直接寫 env 值（機密會進資料庫明文欄位與 UI）、runner 從 node 本機 `.env` 讀（平台無法稽核也無法撤銷）、與 `tunnel_integration` 共用一張表（風險等級不同，混用會讓規則互相污染）、**主金鑰放 KMS**（本次否決的理由是新增雲端依賴且自架部署做不到，**不是因為它比較差**——這句要寫，否則日後看起來像是沒想過）。

### SC-02 — ADR 0031 的增補：git 送回

**目錄六條規則已在 V2.2 的 ADR 0031 定稿**（`04` AR-02b），本階段不重寫，只 amend 一段
（原本是兩段——**綁定授權那一段隨 2026-08-12 裁決刪除**，取而代之的 tag 比對不屬於這份 ADR，
它是派工路由不是目錄與 git 存取，寫在 ADR 0029 的 amend 裡，見 SC-02b）：

**平台憑證加進來，而 ambient 憑證藏不藏是一個設定（2026-08-11 已裁決預設值）。**

V2.2 的 clone 用機器本來就有的認證，而 2026-08-10 的第二次裁決明確
**那不是權宜作法，是刻意給 Agent 的自由**（`04` AR-04b 第 3 點）。
所以本階段**不能理所當然地假設它必須消失**。兩個選項，ADR 0032 要選一個並寫理由：

| | A：平台憑證**取代** ambient（隔離 `HOME`／`GIT_CONFIG_GLOBAL`） | B：平台憑證**疊加**在 ambient 之上 |
|---|---|---|
| 機密的可撤銷性 | 完整——run 只能用平台給的 | 部分——Agent 仍可用機器的 |
| 與第二次裁決的關係 | **收回了那個自由** | 保留 |
| 五條 git 硬約束的實效 | 對平台的 push 完整有效；Agent 也無路可繞 | 對平台有效，Agent 仍可繞 |
| 適用場景 | 共用的 runner node | 專用的 runner node |

**已裁決（2026-08-11）：做成 node 層設定 `runner.git.isolate_ambient_credentials`，
預設 A（取代），可關成 B（疊加）。**

理由：V2.3 引入的是**可撤銷**的機密，而「可撤銷」如果旁邊還有一份不可撤銷的憑證，
那個保證就打了折——所以預設要是 A。但 2026-08-10 第二次裁決給 Agent 的 git 自由
是真的需求，所以留一個開關而不是直接拿掉。

> **⚠️ 2026-08-13 裁決修訂這一段的語意（不是它的值）。**
> 上面那個理由**只在真的有平台憑證的時候成立**。而 git 憑證的下放現在預設關閉，
> 所以照字面實作 A 的後果是：**藏起 ambient 憑證、而沒有任何東西取代它**——
> 預設組態下每一次私有 repo 的 clone 都會失敗。
>
> 修訂後的語意：**隔離只對「這次 run 真的收到了平台的 git 憑證」的情況生效。**
> 沒有平台憑證時 ambient 原樣可用，行為與 V2.2 完全相同。
> 設定值與預設值（`true` ＝取代）都不變，改變的是它什麼時候被套用。
>
> 連帶：**M-AR-6 從「擋開工」降級為「上線後觀察」**——它原本決定的是這個預設值，
> 而那個爭議已經被裁決本身解掉了。

**git 的五條硬約束**（D20，寫死在 daemon，各配一條測試）：

1. 只能推 `cliora/<card_ref>-<run_seq>` 前綴的分支。
2. 永不推 base／target 分支——`target_branch` 是「PR 合併回哪裡」，不是推送目標。
3. 永不 force push、不刪遠端分支、不動 tag。
4. remote allowlist：只能推到該 Project 登記的 repository host。
5. commit trailer 帶 run id，作者是 bot identity，不冒充人類。

**Alternatives rejected**：讓 run 目錄落在 allowed root 內（會讓兩套授權模型互通，且 Agent 的中間產物會出現在使用者的檔案瀏覽器裡）、每次完整 clone（大 repo 不可接受）、允許 Agent 自行決定推送目標（那條約束一旦是設定值就等於沒有）。

### SC-02b — ADR 0029 的增補：tag 派工（D18，2026-08-12 新增）

tag 比對是**派工路由**，不是目錄與 git 存取，所以它 amend 的是 ADR 0029（Runner 模型），
不是 0031。四段：

1. **配對只有兩層**：tag（能力與路由，runner 自報 ＋ 卡片宣告）／`assigned_runner_id`（意圖）。
   **沒有第三層**——`project_agents` 不做，理由指回 ADR 0032 §0，**不在這裡重複論證**
   （授權是機密的問題，不是派工的問題，兩份 ADR 各講一次會開始互相偏移）。
2. **資格判定的最終五條件**（`01` D17）：`ready` ＋ `dependsOn` 滿足 ＋ runtime 相符
   ＋ **tag 相符** ＋ 指定為 null 或等於該 runner。
3. **GitLab 語意**：`required_labels ⊆ runner.labels`；卡片沒宣告 tag 時，
   runner 需 `run_untagged = true` 才會被 offer；tag 是自由字串，不做預先註冊的字典。
4. **比對在 Central，不在 runner**。平台是唯一的 offer 來源（D17），
   把過濾放在 runner 端等於信任 runner 的自我克制；更實際的理由是
   **「這張卡為什麼沒人領」必須在平台端答得出來**——那是一個查詢，不是一句文案。

**Alternatives rejected**：綁定表與「tag 兼任授權」（`01` D18，本 ADR 只引用）、
**完全相等比對**（runner 多一個 tag 就領不到卡，實務上不可用）、
**平台端覆寫 runner 的 tag**（會有兩個真實來源：node 重連時 `runner.register` 會把平台上的編輯蓋掉。
tag 是 runner 對自己能力的宣告，**改 tag 就是改 node 上的設定檔**，UI 只顯示不編輯）。

### SC-02c — tag 比對的落地（contract ＋ Central ＋ daemon ＋ UI）

**欄位大多已經在**：`agent_runners.labels` 與 `tasks.required_labels` 在 V2.1／V2.2 就建好了
（當時明說「只存不比對」）。本期新增的只有一格：

- migration（與 `project_secrets` 同期）：`agent_runners.run_untagged` BOOLEAN NOT NULL DEFAULT `true`。
- **contract v1.12.0**：`runner.register` 新增 `run_untagged`。
  **舊版 daemon 沒送這個欄位時視為 `true`**——與預設值一致，所以 0.9.0 的 runner 升級前後行為不變。
- daemon 0.10.0：`runner.tags`（沿用既有 config 的命名慣例）與 `runner.run_untagged` 兩個設定值，
  在 register 時上報。**`agentd doctor` 要印出這兩個值**，否則「為什麼這台領不到卡」只能靠猜。
- **offer 查詢**加兩個條件（接在 runtime 之後）：

  ```sql
    AND (t.required_labels IS NULL OR jsonb_array_length(t.required_labels) = 0
         OR t.required_labels <@ :runner_labels)          -- 超集比對
    AND (:run_untagged
         OR jsonb_array_length(coalesce(t.required_labels,'[]'::jsonb)) > 0)
  ```

- **dispatch 當下的檢查**（D17b 邊界 2）：指定一個 tag 不符的 runner → `409`，
  訊息要**指名缺哪幾個 tag**（「dev-vm-01 缺 `docker`」），不是「不符資格」。
- **「沒有可用的 Agent」要說得出缺什麼**：平台要答得出「目前沒有任何 runner 同時具備
  `docker` 與 `node20`」。這是 offer 查詢的反向查詢，寫在同一支 service 裡（`09` §5）。
- audit：`run_untagged` 或 tag 變動由 `runner.register` 帶進來，**記一筆 activity 事件**
  （actor 是 runner，不是人）——一台機器悄悄改掉自己的 tag 之後領走了別的卡，要看得出來。

### SC-03 — Secret store（Central）

migration `0027` — `project_secrets`：`id`、`project_id`、`name`、`kind`（`env`／`git_pat`／`git_ssh_key`／`provider_token`）、`value_encrypted`、`key_version`、`created_by`、`created_at`、`rotated_at`、`last_used_at`、`deleted_at`。唯一鍵 `(project_id, name)`。

- **信封加密**：每筆一把 DEK，DEK 以主金鑰包裝後與密文同列。輪替主金鑰只需重新包裝 DEK，不必重寫所有密文。
- **主金鑰來自環境變數 `CLIORA_SECRET_MASTER_KEY`**（已裁決）。**啟動時驗證**：缺少、長度不足、或等於 dev 預設值 → 拒絕啟動並指名，沿用 `.env.example` 對 JWT secret 的既有處置。
- `key_version` **從第一天就有**，不是日後再加。
- **沒有任何 API 回傳 `value`**。列表只回名稱、kind、建立者、`last_used_at`。這一條要有測試：對 API schema 斷言不存在 value 欄位。
- 刪除是軟刪除 ＋ 立即失效（進行中的 run 不受影響，下次下放就沒有了）。

`projects` 新增 `allowed_secret_names` JSONB（名稱 allowlist）；`tasks` 新增 `required_secrets` JSONB（這張卡要哪幾個，必須是 allowlist 的子集）。

### SC-04 — 下放與去識別

- `run.offer` 的 `spec` 新增 `secrets: [{name, value}]`，**只含這張卡宣告的那幾個**。
- 走既有已認證的 WSS，與其他控制訊息同一條通道。
- **runner 收到後只放在記憶體**，以環境變數傳給 CLI 程序，**不寫進任何檔案**。
- **去識別在 runner 端**：送 `run.log_chunk` 前對所有已知值做比對替換為 `***`。理由是值不該離開 node——在平台端過濾等於值已經傳過來了。
- 邊界情況要處理：值被 base64／URL-encode 之後出現在 log 裡。**先做原值比對，並在 ADR 誠實記錄這是盡力而為、不是保證**；真正的保證來自「機密可撤銷」與「保留期」。
- node 可宣告 `accept_secrets: false`，該 node 的 runner 只會被 offer `required_secrets` 為空的卡片。

### SC-04b — Git 認證的兩種落地（D20）**——整條路徑預設關閉**

> **2026-08-13 裁決：`CLIORA_GIT_SECRET_DELIVERY_ENABLED`，預設 `false`。**
>
> 關閉時（＝預設）：
>
> - `kind: git_pat`／`git_ssh_key` 的機密**不能建立**（API 422 並指名這個變數）。
>   一枚存得下來但永遠不會被使用的憑證，比拒絕它更糟——這是本目錄對
>   「不建一張不授權任何東西的表」用過的同一條判準。
> - `project_repositories.auth_kind` **只能是 `ambient`**。
> - `run.offer` 的 `spec.secrets` **永遠不含 git kind**。
> - clone 與 push 都用 node 上既有的憑證（**與 V2.2 完全相同**），
>   由 node owner 自己配置，平台不管理、不稽核、不撤銷。
>
> 開啟時，下面兩格的規則全數適用。**它們照做，只是預設不啟用。**

**兩者都不得把 token 或私鑰寫進檔案。**

- **Fine-grained PAT**：`GIT_ASKPASS` 指向一支**本身不含機密**的小 helper，helper 從環境變數讀值。
  **不得**把 token 塞進 remote URL（會出現在 `git remote -v`、reflog、錯誤訊息），**不得**用 `-c http.extraHeader`（會出現在 `ps`）。
- **SSH key**：`ssh-agent` ＋ `ssh-add -` 從 **stdin** 讀入，私鑰永不落檔；run 結束 kill agent，socket 在 run 目錄內、權限 0700。
  **不得**寫一個 0600 私鑰檔再刪除——違反不落檔規則，且刪除失敗就留在磁碟上。
  加上 **known_hosts pinning** 與 `StrictHostKeyChecking=yes`（沿用 `fix/update-healthcheck-known-hosts` 的既有做法）。

> **socket 不是金鑰。** 這是對「機密不落檔」的細化，要明寫進 ADR 0032，否則實作時很容易退回「寫個 0600 檔案就好」。

**一個必須在 UI 就擋下來的後果**：SSH 只有 git 傳輸、沒有 API，所以用 SSH 認證的 repo 若卡片 `delivery: pull_request`，**必定還需要一枚 `provider_token`**。設定 repository 時就檢查並提示——不要等 run 跑到最後一步才失敗，那時分支已經推上去了。

### SC-05 — Daemon：機密與 git 送回（`agentd` 0.10.0）

**已在 0.9.0 交付、本階段不重做**：run 目錄的建立與權限、兩層配額、mirror 快取與
`git worktree`、`.cliora/` 直接寫入（目錄是 daemon 自己的，不需要 `filesystem.store`）、
清理迴圈、隔離驗證。以下只列本階段新增的：

- **tag 的上報**：`runner.tags` 與 `runner.run_untagged` 兩個設定值，隨 `runner.register` 送出；
  **`agentd doctor` 要印這兩個值**（SC-02c）。daemon 不做任何比對——比對在 Central。
- **機密的接收與落地**：隨 `run.offer` 收到該卡宣告的那幾個，**只放記憶體**，
  以環境變數傳給 CLI 程序，**不寫進任何檔案**（例外是 `ssh-agent` 的 socket，見 SC-04b）。
- **去識別真的開始工作**：0.9.0 的 `Redactor` 掛勾點是 no-op，本階段換成真的值比對替換。
- **ambient 憑證的隔離（依 SC-02 的裁決）**：選 A 時，run 程序的 `HOME`／
  `GIT_CONFIG_GLOBAL` 指向 run 目錄內的一份最小設定，讓機器原本的 credential helper
  與 ssh key 對它不可見；選 B 時只疊加平台憑證。
  **開關是 `runner.git.isolate_ambient_credentials`，預設 A**（SC-02 第二點）。
- 依卡片的 `source`（D21）新增分支動作：
  - `repo` → checkout `base_branch`，**新建 `cliora/<card_ref>-<run_seq>`**（0.9.0 只 checkout，不建分支）。
  - `existing_branch` → checkout 既有分支，不新建。
  - `none` → 不建 `repo/`（0.9.0 已成立）。
- **push**：只推 `cliora/` 前綴，五條硬約束寫死在 daemon。
  **`origin` remote 在此重新出現**——0.9.0 刻意在 clone 之後移除它（`04` AR-04b），
  本階段改為保留但只允許一條 refspec。

### SC-06 — 前端

- **Project Settings → Secrets**：新增（名稱 ＋ 值，值輸入後即不可見）、刪除、輪替（等同覆寫）、顯示 `last_used_at`。**沒有「顯示值」按鈕，也不做「複製」**。
  頁面上要有一句話直接寫著：**主金鑰遺失時所有機密不可復原，只能全部重建**——不要只躺在 runbook 裡。
- **Project Settings → Repositories**：登記 repository、host、預設 base／target branch、**認證方式與對應的 secret**。
  **2026-08-13 裁決之後，認證方式預設只有一個可選值 `ambient`**（「使用這台機器既有的 git 認證」），
  PAT／SSH 兩項顯示為停用並註明「此部署未啟用平台管理的 git 憑證
  （`CLIORA_GIT_SECRET_DELIVERY_ENABLED`）」——**停用而不是隱藏**，
  否則「這個平台到底能不能管 git 憑證」會變成一個要問人的問題。
  啟用之後：選 SSH 時**立刻提示**「SSH 無法開 PR，若要用 `delivery: pull_request` 需另外指定一枚 provider_token」。
  選 PAT 時提示最小權限：`Contents: RW`、`Pull requests: RW`（若同一枚要開 PR）、**指定 repository 而非 all**、**設定到期日**。
- **卡片編輯**：`source`、`base_branch`、`required_secrets`（從 allowlist 多選）、
  **`required_labels`（tag）**——自由輸入，但要把**目前線上 runner 實際擁有的 tag** 列成建議，
  並在輸入一個沒有任何 runner 擁有的 tag 時**當場提示**（「目前沒有 runner 具備 `gpu`，這張卡會一直等」）。
  這比等它掛在佇列上再去查便宜得多。
- **Agents 頁的 tag 欄從「僅供辨識」改為「參與比對」**（`09` §4.3b），並顯示 `run_untagged`。
  兩者都**唯讀**，旁邊註明「由該 node 的 `agentd` 設定檔宣告」（SC-02b Alternatives rejected）。
- **enrollment 畫面的說明文字改寫**（D18 代償第 4 條，**不是可選的文案潤飾**）：
  發 enrollment token 的地方要直接寫著
  **「這台機器將可以領取任何專案的卡片，並取得那些卡片宣告的機密。」**
  這句話的位置很重要——它必須在**發 token 的那一頁**，不是躺在 Agents 頁或 runbook 裡。
- **Run 詳情**：顯示這次 run 用了哪幾個機密的**名稱**、checkout 了哪個 commit、工作目錄大小、清理時間。

## 這一階段明確不做

- 不做 PR／MR 建立（V2.4）。
- 不做 push 以外的任何 git 寫入。
- 不開放瀏覽 run 目錄。要看產物就用 V2.2 的卡片產物（已上傳到平台的那些）。
- 不把 run 目錄接進既有的檔案瀏覽 API。
- **不重做隔離目錄與 clone**（V2.2 已交付）。本階段只增補分支、push、機密與 tag 比對。
- **不做 `project_agents` 綁定表**（2026-08-12 裁決取消，不是延後）。
- 🆕 **預設不下放 git 憑證**（2026-08-13 裁決）。機制做出來，但
  `CLIORA_GIT_SECRET_DELIVERY_ENABLED` 預設 `false`；預設路徑是
  **node owner 自己在機器上配置 git 認證，平台不管**。
- 🆕 **不管理、不稽核、不撤銷 node 上的 ambient git 憑證**。那是 node owner 的東西。
  平台能報告的只有 V2.2 已有的可觀測性（`git remote -v` 與未推送 commit 數）。
- **不做 tag 的字典管理**（預先註冊、命名規範、專案級 tag allowlist）——先讓自由字串跑一段，
  真的出現「同一個能力被寫成三種拼法」再說。
- **不從 UI 編輯 runner 的 tag**（tag 是 node 上的設定，見 SC-02b）。
- 不做機密的自動輪替、不接外部 secret manager（先做自己的，需求明確後再評估）。

## 出口條件

1. 建立一個機密後，**任何 API 都讀不回它的值**（對 OpenAPI schema 與實際回應各一條測試）。
1b. `CLIORA_SECRET_MASTER_KEY` 缺少／過短／等於 dev 預設值 → **Central 拒絕啟動並指名**，不是啟動後才在第一次解密時炸掉。
1c. 主金鑰輪替：換 `key_version` 後**只重新包裝 DEK**，密文未被重寫；舊 `key_version` 的資料仍可解。
2. 機密值出現在 CLI 輸出時，平台收到的 log 是 `***`；**原值從未離開 node**（在 Central 端斷言 log 內容不含值）。
3. `accept_secrets: false` 的 node，其 runner 永遠不會被 offer 需要機密的卡片。
3b. **tag 比對成立**（D18）：卡片要 `docker`，只有具備 `docker` 的 runner 拿得到；
    另一台線上、閒置、runtime 相符但沒有該 tag 的 runner **永遠不會被 offer 它**。
3c. **`run_untagged: false` 的 runner 只領有宣告 tag 的卡片**；同時線上的
    `run_untagged: true` runner 照常領走沒宣告 tag 的卡片（兩者一起跑一次才算通過）。
3d. **指定一個 tag 不符的 runner → dispatch 回 `409`，訊息指名缺哪幾個 tag**，且**不入佇列**
    （D17b 邊界 1 與 2 在本期第一次有東西可測；斷言的對象是 tag，不是綁定）。
3e. **沒有任何 runner 湊得齊某張卡的 tag 時**，卡片顯示的是「沒有 runner 同時具備 `docker`、`node20`」，
    **不是**泛用的「等待可用的 Agent」。
3f. **舊版 daemon（0.9.0）連上來仍能領無 tag 的卡片**：`runner.register` 沒帶 `run_untagged`
    時視為 `true`，行為與升級前一致。
4. `source: repo` 的卡片 → run 目錄有 `repo/`，在正確的 base branch 上，分支名為 `cliora/<card_ref>-<run_seq>`。
4b. **用 Traqora 驗 `base_branch: main`**（D30）——證明它是設定值，不是寫死的 `master`。
   **預設組態下用 node 上既有的憑證跑一次**（2026-08-13 裁決）；
   `CLIORA_GIT_SECRET_DELIVERY_ENABLED=true` 時**PAT 與 SSH 各再測一次**。
4c. 🆕 **旗標關閉時的預設路徑是完整的**：`kind: git_pat`／`git_ssh_key` 建立被拒並指名該變數、
   `auth_kind` 只能是 `ambient`、`spec.secrets` 不含 git kind、
   **而 clone 與 push 都成功**（用 node 上既有的憑證）。
5. `source: none` 的卡片 → run 目錄**沒有** `repo/`，Agent 讀不到任何程式碼。
6. daemon 嘗試推 `main`、推非 `cliora/` 前綴、force push、推到 allowlist 外的 host → **四種全部被拒**，且拒絕發生在 daemon 內（不是靠遠端拒絕）。
> **6b–6d 只在 `CLIORA_GIT_SECRET_DELIVERY_ENABLED=true` 時適用**（2026-08-13 裁決）。
> 它們仍然是本期的出口條件——機制照做——但驗收要明說是在旗標開啟的組態下跑的。

6b. **PAT 路徑**：token 不出現在 `git remote -v`、reflog、`ps` 或任何錯誤訊息（四處各一條斷言）。
6c. **SSH 路徑**：私鑰**從未寫入磁碟**（run 目錄全域搜尋比對）；run 結束後 `ssh-agent` 程序不殘留；未知 host 被 `StrictHostKeyChecking` 拒絕。
6d. repository 設 SSH 且卡片 `delivery: pull_request` 但沒指定 provider_token → **設定畫面就說得出這個後果**
   （V2.3 是提示；V2.4 開放 `pull_request` 時改為擋下儲存——那時擋的才是一個真的會失敗的組合）。
6e. 🆕 **`isolate_ambient_credentials` 只對收到平台憑證的 run 生效**：
   旗標關閉時 run 的 `HOME`／`GIT_CONFIG_GLOBAL` **不被改寫**，ambient 憑證原樣可用。
7. run 結束後目錄依保留期被清掉；同一個 repo 的第二次 run 用 mirror，**不重新完整 clone**（比對耗時）。
8. run 程序嘗試讀寫任何 allowed root → 失敗（隔離驗證測試）。
9. 配額用盡的 node 停止 poll，平台顯示原因，其他 node 照常領工作。
10. 刪除機密後，下一次 run 就拿不到它；進行中的 run 不受影響。
11. 旗標關閉：完整 V1 回歸全綠。

## 風險

| 風險 | 對策 |
|---|---|
| **機密外洩到 log** | runner 端去識別 ＋ 出口條件 2；ADR 誠實記錄「編碼後的值可能漏網」，並以可撤銷 ＋ 保留期作為第二道 |
| 機密外洩到 UI／API | 沒有任何回傳路徑 ＋ 出口條件 1 的 schema 斷言 |
| git 推錯地方 | 五條約束寫死在 daemon ＋ 出口條件 6 的四種拒絕 |
| run 目錄撐爆磁碟 | 單 run ＋ node 總量雙重配額、保留期、用盡即停止 poll（出口條件 9） |
| 兩套授權模型互通 | run 目錄不在 allowed root、檔案 API 不得觸及、出口條件 8 |
| **授權邊界只有 enrollment**：任何 enroll 過的機器，tag 對得上就能取得該卡宣告的機密（2026-08-12 裁決的已知代價） | **這不是可以對策掉的東西，只能縮小半徑**：卡片級 `required_secrets` ＋ Project allowlist、node 端 `accept_secrets: false`、可撤銷 ＋ 下放稽核、**enrollment 畫面直接寫出這個後果**（SC-06）。ADR 0032 §0 要明寫，安全審查驗這四條而不是驗一張綁定表 |
| **tag 被誤當成安全機制**（「我把卡片標成 `prod`，所以只有正式機拿得到」） | tag 是 runner 自報的。UI 上 tag 欄位旁一律不出現鎖頭或「授權」字樣；ADR 0029 amend 與 0032 §0 各寫一次「tag 不是授權」 |
| tag 打錯字 → 卡片永遠沒人領 | 卡片編輯時以線上 runner 的實際 tag 作建議並即時提示（SC-06）；空等狀態說得出缺哪個 tag（出口條件 3e） |
| 大 repo 每次 clone 太慢 | bare mirror ＋ worktree（出口條件 7） |
| **主金鑰與密文共用同一個信任邊界** | 這是環境變數方案的**已知代價**，不是可以對策掉的東西。ADR 要明寫；緩解靠 env 的取得權限管控與 KMS 升級路徑保持暢通 |
| 主金鑰遺失 → 所有機密不可復原 | 啟動時驗證 ＋ 備份還原 runbook 增訂「金鑰另外保管且需與 `key_version` 相符」＋ **UI 上直接寫這句話** |
| 🆕 **平台不管 ambient 憑證，所以「哪台機器能推哪個 repo」平台答不出來**（2026-08-13 裁決接受的代價） | **這不是可以對策掉的東西，它是範圍宣告。** 平台能報告的是 V2.2 已有的可觀測性（run 摘要的 `git remote -v` 與未推送 commit 數）；真正的收斂點是 node 的部署姿態（`dedicated`）與紅線 5（沒有人 merge 的分支不影響任何人）。要把它收回平台管理，就是把 `CLIORA_GIT_SECRET_DELIVERY_ENABLED` 打開 |
| 🆕 **旗標關閉時仍然把 ambient 憑證藏起來** → 每一次私有 repo 的 clone 都失敗 | `isolate_ambient_credentials` **只對真的收到平台憑證的 run 生效**（SC-02 的 2026-08-13 修訂）；出口條件 6e |
| PAT 洩漏到 `ps`／reflog／錯誤訊息（**旗標開啟時**） | `GIT_ASKPASS` helper 不含機密；出口條件 6b 的四處斷言 |
| SSH 私鑰落檔 | `ssh-add -` 從 stdin；出口條件 6c 的全域搜尋比對 |
| SSH repo 開不了 PR，跑到最後才發現 | 設定畫面即檢查（出口條件 6d） |
