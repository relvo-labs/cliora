# V2.3 — 機密下放、git 送回與綁定授權（ticket 前綴 `SC-`）

> **2026-08-10 裁決改寫本階段的範圍。**
> 隔離工作目錄（D19）與 git 的**取得**半邊（D20）已經在 **V2.2** 交付——
> Agent 自己把專案拉到 `<state>/.cliora/runs/<run_id>/`，workspace 綁定只服務互動式 Session。
>
> | 從 V2.3 移出（已在 V2.2） | 移入 V2.3（原本在 V2.2） |
> |---|---|
> | run 目錄的六條規則、配額、清理、mirror 快取 | **`project_agents` 綁定**（D18）——它授權的是機密，所以與機密同一份 ADR |
> | `clone`／`fetch`／`checkout`／`worktree add` | **labels 比對**仍是後續，不在 V2.3 |
> | host allowlist、known_hosts pinning | |
>
> 搬動表見 `04-phase-v22-agent-runner.md` §0。**本階段仍是 V2 安全面最重的一階段**：
> 它要把 V2.2 那份「用 node 上 ambient git 憑證」的權宜作法換成平台管理、範圍受限、可撤銷的憑證。

## 目標

把 V2.2 的 run 從「在隔離目錄裡用**機器本來就有的** git 認證拉程式碼、成果只能附成產物」
變成「帶著**平台下放的、範圍受限的、可撤銷的**機密，而且能把分支推回去」。

三件事：**機密**（新的儲存面）、**git 送回**（新的對外副作用）、
**綁定授權**（讓「哪個 runner 可以碰哪個專案的機密」成為一列真實資料）。

## 前置條件

- V2.2 出口條件全數通過（**含隔離目錄與 clone 的那七條**）。
- D18、D20（送回半邊）、D21、D22、D23 已裁決。**2026-08-08 補齊**：主金鑰放**環境變數**；git 認證**同時支援 fine-grained PAT 與 SSH key**。
- **ADR 0031 已在 V2.2 發佈**（目錄六條規則 ＋ git 取得）；本階段**增補**它的送回半邊。
- ADR 0032（機密管理與 SEC-002 修訂）已撰寫並接受。

## 工作包

### SC-01 — ADR 0032：機密管理與 SEC-002 修訂（**先寫這一份**）

放在最前面，因為它決定其餘工作包能不能開工。

要交付的三段：

1. **SEC-002 的精確修訂**（D23）：只撤銷「呼叫端不得指定環境變數」中關於**值**的那一句，argv／binary／shell string 完全保留，互動式 Session 完全不變。修訂後的不變式一句話：

   > 沒有任何請求 payload 能命名一個命令、或攜帶一個機密的值。

2. **機密的九條規則**（D22 的表）：加密儲存、永不可讀回、按需下放、不落檔、runner 端去識別、名稱 allowlist、node 可拒絕、稽核不含值、可輪替可撤銷。

3. **主金鑰在環境變數的代價**（D22）——**這一段不能只寫好處**：金鑰與密文共用同一個信任邊界、沒有解密稽核、金鑰遺失即全部不可復原。同時寫出讓它不變成死路的四件事（信封加密、`key_version`、啟動時驗證、**KMS 升級路徑**）。

4. **Alternatives rejected**：卡片直接寫 env 值（機密會進資料庫明文欄位與 UI）、runner 從 node 本機 `.env` 讀（平台無法稽核也無法撤銷）、與 `tunnel_integration` 共用一張表（風險等級不同，混用會讓規則互相污染）、**主金鑰放 KMS**（本次否決的理由是新增雲端依賴且自架部署做不到，**不是因為它比較差**——這句要寫，否則日後看起來像是沒想過）。

### SC-02 — ADR 0031 的增補：git 送回 ＋ 綁定授權

**目錄六條規則已在 V2.2 的 ADR 0031 定稿**（`04` AR-02b），本階段不重寫，只 amend 兩段：

**一、`project_agents` 綁定是機密的授權邊界**（D18，從 V2.2 移入）。
綁定表在這裡才第一次授權了某個東西，所以三層要在這份 amend 裡講清楚：
綁定（授權，Admin）／labels（能力，後續功能）／`assigned_runner_id`（意圖）。
**第三層永遠不能覆蓋第一層**，而 D17b 邊界 1 的測試在這裡才第一次有東西可測。

**二、平台憑證加進來，而 ambient 憑證藏不藏是一個設定（2026-08-11 已裁決預設值）。**

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

**V2.3 開工前要複核的是值不是形狀**：若 M-AR-6（clone 失敗原因分布）顯示
ambient 憑證在實務上根本拉不動私有 repo，那 A 就不是「收回自由」而是「唯一可行的路」，
預設值的爭議會自己消失。

**git 的五條硬約束**（D20，寫死在 daemon，各配一條測試）：

1. 只能推 `cliora/<card_ref>-<run_seq>` 前綴的分支。
2. 永不推 base／target 分支——`target_branch` 是「PR 合併回哪裡」，不是推送目標。
3. 永不 force push、不刪遠端分支、不動 tag。
4. remote allowlist：只能推到該 Project 登記的 repository host。
5. commit trailer 帶 run id，作者是 bot identity，不冒充人類。

**Alternatives rejected**：讓 run 目錄落在 allowed root 內（會讓兩套授權模型互通，且 Agent 的中間產物會出現在使用者的檔案瀏覽器裡）、每次完整 clone（大 repo 不可接受）、允許 Agent 自行決定推送目標（那條約束一旦是設定值就等於沒有）。

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

### SC-04b — Git 認證的兩種落地（D20）

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
- **Project Settings → Repositories**：登記 repository、host、預設 base／target branch、**認證方式（PAT／SSH）與對應的 secret**。
  選 SSH 時**立刻提示**「SSH 無法開 PR，若要用 `delivery: pull_request` 需另外指定一枚 provider_token」，並在未指定時擋下儲存。
  選 PAT 時提示最小權限：`Contents: RW`、`Pull requests: RW`（若同一枚要開 PR）、**指定 repository 而非 all**、**設定到期日**。
- **卡片編輯**：`source`、`base_branch`、`required_secrets`（從 allowlist 多選）。
- **Run 詳情**：顯示這次 run 用了哪幾個機密的**名稱**、checkout 了哪個 commit、工作目錄大小、清理時間。

## 這一階段明確不做

- 不做 PR／MR 建立（V2.4）。
- 不做 push 以外的任何 git 寫入。
- 不開放瀏覽 run 目錄。要看產物就用 V2.2 的卡片產物（已上傳到平台的那些）。
- 不把 run 目錄接進既有的檔案瀏覽 API。
- **不重做隔離目錄與 clone**（V2.2 已交付）。本階段只增補分支、push 與機密。
- **不做 labels 比對**（後續功能）。本階段加回來的只有 `project_agents` 綁定。
- 不做機密的自動輪替、不接外部 secret manager（先做自己的，需求明確後再評估）。

## 出口條件

1. 建立一個機密後，**任何 API 都讀不回它的值**（對 OpenAPI schema 與實際回應各一條測試）。
1b. `CLIORA_SECRET_MASTER_KEY` 缺少／過短／等於 dev 預設值 → **Central 拒絕啟動並指名**，不是啟動後才在第一次解密時炸掉。
1c. 主金鑰輪替：換 `key_version` 後**只重新包裝 DEK**，密文未被重寫；舊 `key_version` 的資料仍可解。
2. 機密值出現在 CLI 輸出時，平台收到的 log 是 `***`；**原值從未離開 node**（在 Central 端斷言 log 內容不含值）。
3. `accept_secrets: false` 的 node，其 runner 永遠不會被 offer 需要機密的卡片。
4. `source: repo` 的卡片 → run 目錄有 `repo/`，在正確的 base branch 上，分支名為 `cliora/<card_ref>-<run_seq>`。
4b. **用 Traqora 驗 `base_branch: main`**（D30）——證明它是設定值，不是寫死的 `master`；**PAT 與 SSH 各測一次**。
5. `source: none` 的卡片 → run 目錄**沒有** `repo/`，Agent 讀不到任何程式碼。
6. daemon 嘗試推 `main`、推非 `cliora/` 前綴、force push、推到 allowlist 外的 host → **四種全部被拒**，且拒絕發生在 daemon 內（不是靠遠端拒絕）。
6b. **PAT 路徑**：token 不出現在 `git remote -v`、reflog、`ps` 或任何錯誤訊息（四處各一條斷言）。
6c. **SSH 路徑**：私鑰**從未寫入磁碟**（run 目錄全域搜尋比對）；run 結束後 `ssh-agent` 程序不殘留；未知 host 被 `StrictHostKeyChecking` 拒絕。
6d. repository 設 SSH 且卡片 `delivery: pull_request` 但沒指定 provider_token → **設定畫面就擋下**，不是 run 到最後才失敗。
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
| 大 repo 每次 clone 太慢 | bare mirror ＋ worktree（出口條件 7） |
| **主金鑰與密文共用同一個信任邊界** | 這是環境變數方案的**已知代價**，不是可以對策掉的東西。ADR 要明寫；緩解靠 env 的取得權限管控與 KMS 升級路徑保持暢通 |
| 主金鑰遺失 → 所有機密不可復原 | 啟動時驗證 ＋ 備份還原 runbook 增訂「金鑰另外保管且需與 `key_version` 相符」＋ **UI 上直接寫這句話** |
| PAT 洩漏到 `ps`／reflog／錯誤訊息 | `GIT_ASKPASS` helper 不含機密；出口條件 6b 的四處斷言 |
| SSH 私鑰落檔 | `ssh-add -` 從 stdin；出口條件 6c 的全域搜尋比對 |
| SSH repo 開不了 PR，跑到最後才發現 | 設定畫面即檢查（出口條件 6d） |
