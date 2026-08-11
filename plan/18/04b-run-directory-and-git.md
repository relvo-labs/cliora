# 04b — `AR-02b`／`AR-07b`：隔離工作目錄與 git 取得

**這一章是 2026-08-10 裁決加進本期的。** 原本它是 V2.3 的 `SC-02`／`SC-05`。
它同時是 `docs/security-review-v22.md` **第五節**的來源。

上游：`research/02/04` AR-02b／AR-04／AR-04b、`research/02/01` D19／D20。

## 1. 為什麼這一章排在執行面之前

`AR-07b` 在波次表上排在 `AR-07`（非互動執行）**之前**。順序不是任意的：
先有一個正確隔離、有配額、會清理的目錄，再往裡面放一個會跑一小時、會寫檔案的程序。
反過來做，第一次整合測試就會在一台機器上留下三十個沒人清的 clone，
而那時你要同時 debug「執行對不對」與「目錄為什麼滿了」。

## 2. 一台 node 上的兩棵樹（**先看這個**）

本章其餘部分是理由。**這一節是「東西實際上長在哪裡」**，先讀它。

一台同時提供互動式 Session 與 Agent Run 的 node 上，會有**兩棵完全不相干的樹**：

```text
/var/lib/agentd/                          ← Agent Run 的地盤
│                                            systemd StateDirectory=agentd，0700，服務使用者所有
└── .cliora/
    ├── mirrors/
    │   └── a3f9c1…/                      ← 該 repo 的 bare mirror
    │                                        這台機器上所有 run 共用一份（§5.3）
    └── runs/
        ├── 9f3c1a20-4e7b-4c11-9a55-…/    ← 一個 run 一個目錄（run_id 是 UUID）
        │   ├── repo/                     ← git worktree ★ 程序的 cwd 就是這裡
        │   ├── .cliora/
        │   │   ├── context/<run_id>.md      情境包（≤4 KB）
        │   │   ├── context/<run_id>.token   run token，0600，run 結束即刪
        │   │   └── process/v1/              流程投影
        │   ├── artifacts/                run 自己產生的檔案（上傳後平台有副本）
        │   └── .git-config               user.name = cliora-run（§5.4 第五點）
        └── 5b8e…-…/                      ← 另一個 run，完全獨立的一份 worktree

/home/neil/projects/traqora/              ← 互動式 Session 的地盤
│                                            workspace.allowed_roots 裡的一條，使用者自己的
└── .cliora/
    ├── context/<session_id>.md           V2.1 的投影（VerbProject 寫的）
    ├── uploads/                          image drop（ADR 0024）
    └── .gitignore                        內容是 *
```

**Agent Run 只活在上面那棵。** 它甚至不知道下面那棵在哪——
`run.offer` 的 `spec` **沒有 `workspace` 欄位**（`04-…md` §1.2），
run 目錄由 daemon 自己決定，**Central 連它叫什麼都不知道**。

### 2.1 具體執行的那一行

```bash
cd /var/lib/agentd/.cliora/runs/<run_id>/repo
claude -p  <<< "<情境包>"        # 沒有 PTY、沒有 tmux；stdout/stderr 接到 daemon 的分塊器
```

對照互動式 Session 的那一行（**本期一個位元組都不改**）：

```bash
tmux new-session -d -s <session> -c /home/neil/projects/traqora  claude
# PTY、tmux 持久化、輸出走二進位訊框到瀏覽器
```

### 2.2 兩者可以同時跑，而且是三種「同時」

| 「同時」的意思 | 可以嗎 | 上限由誰決定 |
|---|---|---|
| 一台 node 上：一個 run 在跑，同時有人開 Session | ✅ **出口條件 16 要驗的就是這個** | 兩個**互不相干**的計數器：`sessions_per_node_max`（Central，`settings.py:75`，預設 10）與 `agent_runners.max_concurrent`（daemon 回報，預設 1） |
| 一個 runner 同時跑多個 run | ✅ | `max_concurrent`。每個 run 一個自己的 `runs/<run_id>/`，共用 `mirrors/`。滿了**就不送 poll**（背壓天然，不是送 `capacity: 0`） |
| 一個 run 裡的 Agent 一邊做事、一邊用 `cliora` CLI 回報 | ✅ **這是設計本身** | 無。`cliora` 就是 `agentd` 那支二進位，從 cwd 往上找到 `<run>/.cliora/context/` 拿 token（`05-…md` §2.1） |

第一列在程式碼上是兩條分開的路徑，同一個 `agentd` 行程、同一條 WSS：

| | 互動式 Session | Agent Run |
|---|---|---|
| 誰啟動 | 人在瀏覽器按下 | runner 的 poll 迴圈領到卡 |
| 怎麼跑 | `session.Manager` → tmux → PTY | `exec.Cmd`，**沒有 PTY、沒有 tmux** |
| 工作目錄 | allowed root 內 | `runs/<run_id>/repo` |
| 輸出到哪 | 二進位訊框 → 瀏覽器即時 | `run.log_chunk` → 聚合 → `run_logs` |
| 憑證 | `cliora_st_…` | `cliora_rt_…` |

### 2.3 兩棵樹共用三樣東西，而第三樣是重點

**不共用**：目錄、生命週期、憑證、tmux。**共用**：

1. **一條 WSS socket** → log chunk 與終端輸出搶同一條線。
   這是 `00-…md` D3 那兩個常數（32 KiB／2 秒）的理由，也是出口條件 24 要量的。
2. **一顆磁碟** → 所以 `runner.min_free_bytes` 與 image drop 用同一個保留水位（§4.1）。
3. **一個 OS 使用者** → **§3.4 的整節都在講這一條的後果。**
   一句話版本：run 的程序跑在 agentd 的服務使用者之下，
   而 `/home/neil/projects/traqora` 必須被那個使用者讀寫（否則 Session 開不起來），
   所以**一個決定要去看的 Agent，`cd` 過去就看到了**。
   「專用 runner」（`allowed_roots: []`）的意思就是**讓下面那棵樹不存在**
   ——沒有第二棵樹，就沒有東西可讀（§3.5）。

## 3. run root 的設計理由

### 3.1 為什麼是 `StateDirectory` 而不是 `RuntimeDirectory`

現況的 systemd unit（`daemon/internal/install/systemd.go:39`）只有：

```ini
RuntimeDirectory=agentd        # → /run/agentd，tmpfs，放產生出來的 tmux 設定（PV-04）
PrivateTmp=true
NoNewPrivileges=true           # 非特權姿態
User=<非 root 使用者>            # SEC-007
```

**`RuntimeDirectory` 不能用**：它是 tmpfs，重啟就消失，而失敗的 run 目錄要留 14 天
（保留期是「那才是需要人來看的」，D19 規則 2）。

所以 unit 新增一行：

```ini
StateDirectory=agentd          # → /var/lib/agentd，systemd 建立、chown 給服務使用者
```

用 systemd 原生的 `StateDirectory` 而不是自己 `mkdir` ＋ `chown`：
它會用服務使用者的身分建立、設 0700、並在 unit 被移除時交由 systemd 處理。
自己做等於在 `install` 套件裡多一條要處理 root／非 root 差異的路徑，
而 `install/` 是本期唯一要動的一行——**只動這一行**。

### 3.2 路徑與 `.cliora`

```text
runner.work_dir            預設 <StateDirectory>/.cliora/runs
                           → /var/lib/agentd/.cliora/runs/<run_id>/
```

`.cliora` 這一段保留，有兩個理由（一個是裁決的字面要求，一個是實用的）：

1. 裁決明寫「應該放到一個隱藏資料夾，比如 `.cliora`」。
2. 營運者若把 `work_dir` 設到別的路徑上（大容量磁碟、非 systemd 的機器），
   這個名字讓它是隱藏的，**而且與既有 `.cliora/.gitignore` 的慣例一致**——
   image drop 已經在 `.cliora/` 下寫過 `*` 的 gitignore（`upload.go:38`），
   所以萬一 run root 落在一個 repo 裡面，git 本來就會忽略它。
   這是一個**意外的好處而不是設計依賴**，但它讓最壞情況不那麼壞。

### 3.3 目錄版面的三個設計點

版面本身在 §2 的樹裡。這裡只記三件容易做錯的：

1. **`repo/` 與 `.cliora/` 是兄弟不是父子。** 所以情境包不在 clone 裡面——
   它不會出現在 `git status`、不會被 Agent 誤 commit、也不需要靠 gitignore 保護。
2. **`cliora` CLI 不必改一行就找得到它。** `FindContext`（`cli.go:71`）是
   「從 cwd **往上**找 `.cliora/context/`」：cwd 是 `repo/`，往上一層就是 run 目錄。
   而且那個目錄裡**只有一份** context，所以
   `contextFrom` 的「多個情境包要指定 `--session`」分支永遠不會觸發
   ——那個歧義只存在於共用 workspace 的場景，裁決把它一起消滅了。
   （唯一要改的是兩句訊息的措辭，`05-…md` §2.1。）
3. **`process/` 的投影不必處理「已存在就跳過」。** V2.1 那條
   「`FILE_EXISTS` 視為成功」的規則是為了共用 workspace 而設的；run 目錄每次都是新的。

### 3.4 誠實面對一件事：run 程序**可以**讀 allowed root

本章原本（與 `00-…md` 的判準 6、`08-…md` 的出口條件 8）寫著
「run 程序讀寫不到任何 allowed root」。**那句話沒有任何東西可以兌現，所以要改掉。**

機制上為什麼不行：

| 事實 | 出處 |
|---|---|
| run 的子程序跑在**與 agentd 同一個 OS 使用者**之下 | 沒有第二個使用者；`systemd.go:51` 的 `User=` 只有一個 |
| allowed roots **必須**被那個使用者讀寫 | 否則互動式 Session 開不起來 |
| unit 刻意**不**隱藏家目錄 | `systemd.go:33`：「PrivateHome is deliberately NOT set: it would hide the user's CLI config and workspaces that the runtimes need」 |
| 沒有 chroot／mount namespace／seccomp | 本期不引入（見下） |

所以一個決定要去看的 Agent，`cd <allowed_root>` 就看到了。
**原本那條測試（「一個會嘗試讀取的 fakecli 變體斷言讀取失敗」）在一台普通機器上會讀成功**
——它是一條斷言寫錯的測試，不是一條會抓到 bug 的測試。

**平台實際保證的是三件比較小、但是真的的事**：

1. **平台自己的任何路徑都不寫 allowed root。** run 目錄由 daemon 建立在 allowed root 之外，
   情境包直接寫進 run 目錄（§4 of `04-…md`），`daemon/internal/files/` 整包零 diff。
2. **既有的檔案 API 讀不到 run 目錄**（反方向是真的、也可測的）。
3. **`git status --porcelain` 在使用者的 workspace 上全程為空**——
   這證明的是「平台沒動它」，不是「Agent 不能動它」。

**剩下的那一段由部署姿態承擔，而不是由一句話承擔**（§3.5）。
這與 D25 的立場一致：**不試圖限制 Agent 在沙箱裡能做什麼**——
本期只是要誠實承認「沙箱」在 V2.2 的邊界比字面上鬆。

#### 為什麼本期不引入 mount namespace

技術上做得到（`unshare` ＋ 只掛 run 目錄與系統目錄，或 bubblewrap）。三條理由不做：

- **它需要 unprivileged user namespaces**，那是一個 node 層的核心設定，
  而平台一向的姿態是**回報機器實際的姿態、不假設它**（ADR 0023 D3）。
  做成「有就用、沒有就降級」等於做了一個一半的保證。
- **它會遮掉 CLI 需要的東西**：`~/.claude`、`~/.codex`、`~/.gitconfig`、`~/.ssh`。
  要精確地只遮 allowed root 而不遮這些，是一份 per-node 的 mount 清單——
  一個要維護的東西，而它保護的是 D25 明說不保護的面。
- **`codex exec -s workspace-write` 已經提供了一個真沙箱**（landlock），
  範圍就是 run 目錄。所以在 codex 這條路徑上，第 3 點的保證確實更強——
  **而那是 runtime 給的，不是平台給的**，所以它是一個附帶好處而不是一條承諾。

真的需要平台級的強制隔離時，開一份 ADR，而它的第一個問題是
「這與 D25『不限制沙箱內能做什麼』的關係」。

### 3.5 「專用 runner node」的可檢查定義，以及平台怎麼顯示它

§3.4 把一段保證交給了部署姿態。**那段姿態要有一個可檢查的定義**，
否則它就是 runbook 裡一句沒有人驗的話。

| # | 條件 | 怎麼檢查 | 誰檢查 |
|---|---|---|---|
| 1 | **`workspace.allowed_roots` 是空的** | 設定檔一行 | **daemon 自己**，回報給平台（見下） |
| 2 | 機器的 git 憑證範圍 ＝ 你願意讓**任何一張卡**碰的範圍 | `ssh -T git@host`／PAT 的 scope | 人 |
| 3 | 機器上沒有別的東西：其他服務的憑證、production 的 `.env`、**雲端 instance metadata 換得到的角色** | 人 | 人 |
| 4 | 可拋棄、可從設定重建 | 人 | 人 |
| 5 | 對外網路的限制（若需要）在防火牆／egress proxy | 人 | 人 |

**第 1 條是唯一一條平台判得出來的，而它剛好也是最強的一條**：
`allowed_roots` 為空的 node 上，「run 讀不到 allowed root」**是恆真的**——沒有東西可讀。

所以本期加一個**回報**（不是強制）：

```text
runner.register 的 payload 多一個欄位：
  dedicated: bool        ← len(workspace.allowed_roots) == 0

落地為 agent_runners.dedicated，Agents 頁顯示：
  ✔ 專用 runner（此 node 未設定任何 allowed root）
  ⚠ 混合用途（此 node 也提供互動式 Session；Agent 可讀取那些目錄）
```

**回報而不是強制**，三個理由：

- 混合用途的 node 是**合理**的：一個人的單台開發 VM 同時要開 Session 與跑 runner，
  而那個人接受這個姿態。強制會讓最常見的使用情境開不了工。
- 沿用 ADR 0023 D3 建立的同一條原則：**回報機器實際的姿態，不要回報你希望的姿態**。
  `sandbox_bypass` 的做法逐字相同——requested 與 actual 分開回報，console 顯示真相。
- **它把「專用」從 runbook 的散文變成 console 上的一格**。
  一個看得見的 ⚠ 會被問起；一句 runbook 不會。

`agentd doctor` 也印這一行，讓人在 enroll 之前就看得到。

### 3.6 啟動自檢：run root 不得落在 allowed root 內

```text
runner 模式啟動時，對每一個 workspace.allowed_roots：
  若 work_dir 在它之內，或它在 work_dir 之內  → 拒絕啟動，訊息指名是哪一個 root
```

**拒絕啟動，不是印一行警告。** 理由：這個設定錯誤的後果是兩套授權模型互通
（Agent 的中間產物出現在使用者的檔案瀏覽器裡、使用者的 `filesystem.store` 能寫進 run 目錄），
而那是紅線 2 與紅線 3 同時被繞過。一個印了警告然後照常啟動的 daemon，
會讓這個錯誤在一台機器上活很久。

比較用 `filepath.Rel` 而不是字串前綴，理由與 `authorize_workspace` 的
`PurePosixPath.relative_to` 相同（`sessions.py:72` 的註解）：
`/a/projects` 與 `/a/projects-other` 的前綴碰撞會被誤判。
**但不共用那份實作**——那個函式回答的是「使用者能不能用這條路徑」，
這裡問的是「這兩棵樹有沒有交集」，是不同的問題。

## 4. 配額與清理

### 4.1 兩層配額

| 層 | 設定 | 預設 | 超過時 |
|---|---|---|---|
| 單一 run 目錄 | `runner.run_quota_bytes` | M12 量完決定 | run 標 `failed` ＋ `RUN_DISK_QUOTA`，log 明示 |
| node 上所有 run 總量 | `runner.total_quota_bytes` | M12 量完決定 | **停止 poll**，並在 heartbeat 回報原因 |
| 磁碟保留水位 | `runner.min_free_bytes` | 512 MB | 同上 |

第三層沿用既有概念：`filesystem.upload` 已經有 `DefaultFileUploadMinFreeBytes = 512 MB`
（`config.go:226`）。用同一個水位，理由是同一台機器上「Agent 的 clone」與
「使用者上傳的檔案」搶的是同一顆磁碟——兩個不同的水位會讓其中一個先把另一個餓死。

**停止 poll 而不是回報離線**：這是 UI 上的一條硬要求（`07-…md` §2）。
「磁碟用盡」與「機器不在」是兩件事，而使用者對它們的反應完全不同。

### 4.2 保留期與清理

| 結果 | 保留 | 誰清 |
|---|---|---|
| 成功 | 3 天 | daemon 的清理迴圈 |
| 失敗／`lost`／取消 | 14 天 | 同上 |
| mirror（`<work_dir>/../mirrors/<repo_hash>/`） | 30 天未被使用 | 同上 |

清理迴圈沿用 `projectionRetentionLoop`（`connection.go:627`）的形狀逐字：
由 `Run` 擁有、與連線生命週期共用 cancellation、以 `defer <-done` 證明 goroutine 已退出
（**沒有跨 daemon 重啟的孤兒 ticker**）。

**這是 ADR 0024 W2「誰清這個、什麼時候清」在本期的第三個答案。**
另兩個是 `run_logs`（Central 側，成功 3 天／失敗 14 天）與 `task_artifacts`（**不清**，
跟著卡片走）。三個答案寫在同一張表裡（`01-…md` §4），讓 V2.3 不必重新推導。

**run token 檔要在 run 結束時立刻刪**，不等保留期——憑證的生命週期是 run，不是目錄。

## 5. git 取得

### 5.1 用 `git` 執行檔，不引入 Go library

`daemon/go.mod` 目前有六個直接依賴，沒有一個與 git 有關。本期**不新增依賴**：
新檔 `daemon/internal/gitfetch/`，shell out 到 `git`。

三條理由：

1. mirror ＋ `git worktree` 正是 go-git 支援最弱的部分，而它們是 M11 的核心策略。
2. 引入第二套 git 實作，意味著「daemon 看到的 repo 狀態」與「Agent 用 `git` 看到的」
   可能不同——而 Agent 在沙箱裡用的一定是真的 `git`。
3. `git` 是不是裝了，用與 `RunCapable` 同一套探測回答（`git --version`），
   探不到就 `runtimes: []` ＋ doctor 印出原因。**這是本期新增的一個 node 前置條件**，
   要寫進 runbook 與 `agentd doctor`。

### 5.2 argv 也是封閉表

與 `runArgs`（`04-…md` §5）同一條紀律：

```go
// gitfetch/args.go — 封閉表。呼叫端提供的字串只能出現在標記為 <value> 的位置，
// 而那些位置的來源只有 project_repositories（Admin 建立的平台設定）。
//
// 沒有任何一個 argv 元素來自請求 payload、任務卡的自由文字欄位，或 Agent 的輸出。
mirrorUpdate = ["--git-dir", "<mirror>", "remote", "update", "--prune"]
mirrorClone  = ["clone", "--mirror", "--", "<url>", "<mirror>"]
worktreeAdd  = ["--git-dir", "<mirror>", "worktree", "add", "--detach", "<dest>", "<ref>"]
statusPorcelain = ["-C", "<dest>", "status", "--porcelain"]
remoteVerbose   = ["-C", "<dest>", "remote", "-v"]          ← 只讀，供 run 摘要（§5.4）
logUnpushed     = ["-C", "<dest>", "log", "--oneline", "--branches", "--not", "--remotes"]
diff         = ["-C", "<dest>", "diff"]
```

**`--` 分隔符在 `clone` 上是必要的**：一個以 `-` 開頭的 URL 會被當成旗標。
URL 本身另外驗：scheme 必須是 `https` 或 `ssh`，host 必須在
`runner.git.allowed_hosts` 內，**而且 URL 裡不得含 userinfo**（`https://user:pass@host/…`）
——後者是 D20 明文禁止的「不得把 token 塞進 remote URL」的機器形式，
它會出現在 `git remote -v`、reflog 與錯誤訊息裡。

SEC-002 的判準在這裡仍然成立，而理由要寫清楚：
**repo URL 是平台設定，不是呼叫端字串**——與 `runtime.binary` 來自 `config.yaml`
是同一種來源。差別在於它經過 API 被建立，所以 `POST /api/projects/{id}/repositories`
要做嚴格的格式驗證（`project.manage`，`06-…md` §2）。

### 5.3 流程

```text
source: none
  → 不建 repo/。Agent 沒有程式碼可讀，這是刻意的（D21 誠實性規則 2）

source: repo | existing_branch
  1. mirror 存在？ → git remote update --prune
     不存在        → git clone --mirror
  2. git worktree add --detach <run>/repo <ref>
     ref = default_branch（repo）或卡片指定的分支（existing_branch）
  3. 記錄 commit_sha，回報給平台（run.progress 的 phase="checked_out"）
  4. 記錄 git status --porcelain 的基準（通常為空）

  （**沒有「移除 origin」這一步**。2026-08-10 第二次裁決：不擋 Agent push，
    憑證也不必唯讀。移除 origin 會連帶弄壞 fetch／pull 與那個被允許的 push。）
```

**`--detach`**：本期不建分支（分支命名空間是 V2.3）。detached HEAD 讓
「這個 run 在哪個 commit 上」是唯一的答案，而不是「在一個叫什麼的分支上」。

### 5.4 認證：用 node 上既有的，而 Agent 的 git 自由是刻意給的

平台管理的機密是 V2.3。所以本期的 clone 用**機器本來就有的** git 認證
（ssh-agent、credential helper、或公開 repo）。**平台不管理、不注入、不記錄任何憑證。**

> **2026-08-10 第二次裁決：不需要擋 Agent 自己 push，憑證也不需要唯讀。**
> 這一段原本寫成「本期最大的新風險」＋四道處置。**那個框架被撤回了**：
> Agent 在沙箱裡的 git 自由是**刻意給的**，不是一個等著被補起來的洞。
> 撤回的具體內容：不做 `git remote remove origin`、
> runbook 不再建議「runner node 只帶唯讀憑證」、風險表不再有那一列。

四條後果，全部要寫進 ADR 0031：

**一、平台不新增任何機密面。** V2.3 的 ADR 0032 範圍不變。

**二、私有 repo 只有在那台機器本來就拉得動時才拉得動——而且要快速失敗。**

```text
（只套用在 daemon 自己的 clone／fetch 呼叫上）
GIT_TERMINAL_PROMPT=0
GIT_ASKPASS=/bin/false
GIT_SSH_COMMAND="ssh -o BatchMode=yes -o StrictHostKeyChecking=yes \
                     -o UserKnownHostsFile=<known_hosts>"
```

**這三個變數不進 Agent 程序的環境。** 這個區分是第二次裁決的直接後果：
它們的目的是「daemon 自己的 clone 不要掛在密碼提示上」，
不是「限制 Agent 能做什麼」。套進 Agent 的環境會讓一個需要輸入密碼的 push 失敗，
而那正是裁決要允許的事情。

沒有這三個，一次缺憑證的 clone 會掛在提示上直到**牆鐘兜底**（6 小時，`04-…md` §3.4），
而使用者看到的是「跑了一小時然後失敗」。出口條件斷言的是**秒級**失敗。

`known_hosts` 沿用既有做法：`tunnel.known_hosts_path` 已經在 config 裡（`config.go:263`），
而 `fix/update-healthcheck-known-hosts` 是這個 repo 處理 host pinning 的前例。
**不共用同一個檔案**（tunnel 的 host 與 git 的 host 是不同的清單），
但共用同一套「pinning 而不是 `StrictHostKeyChecking=no`」的姿態。

**三、Agent 可以用機器的憑證做 git 能做的任何事，包含 push。這是刻意的。**

它與 D25 一致：**不限制 Agent 在沙箱裡能做什麼，改為限制它的產出能怎麼離開沙箱**
——而在本期，「離開」的方式包含 Agent 自己推的分支。
`research/02/00` §7 紅線 5 的原則（每一種出口都要落在人看過才生效的地方）
**在分支這個出口上仍然成立**：一條沒有人 merge 的分支不影響任何人。

**但有一件事必須寫下來，否則它會靜默漂掉**（見 §5.5）：
紅線 4 的第 1、2 條約束（分支命名空間強制、永不推共用分支）
原文寫「寫死在 daemon，不是設定值」。**它們約束的是平台自己的 push 路徑（V2.3），
不是 Agent 用機器憑證的行為。** 本期平台一次 push 都不做，
所以那兩條在本期沒有可約束的對象；而 Agent 推到哪裡，平台不攔。

**四、可觀測性取代阻止，而且它現在是主要機制不是安慰獎。**

run 結束時記錄兩件事進 run 摘要與 `run.complete`：

| 記錄 | 用 |
|---|---|
| `git remote -v` 的輸出（**不含 URL 的 userinfo**，若有就遮掉） | 這個 run 對得上哪個遠端 |
| `git log --oneline --branches --not --remotes` 的行數 | **有幾個 commit 還沒推**（反過來說：0 且工作目錄乾淨，代表它推了） |

第二列不是完美的偵測（Agent 可以在 push 之後改 refs），但它是**零成本、零假設**的一行資訊，
而且它讓「這個 run 有沒有動到遠端」在 Run 詳情頁上是一個看得見的事實而不是一個猜測。

**這一段不是免責聲明。** 它與原本那版的差別是：原本在解釋「我們擋不住，抱歉」，
現在在解釋「我們刻意不擋，而這是你能看到什麼」。

**五、run 的 git 身分是機器的身分。** 本期平台不做 commit；Agent 若自己 commit／push，
作者是機器的 git 設定。run 的 `.git-config`（§3.3）設
`user.name = cliora-run` / `user.email = cliora-run@<node>`——
**不冒充人類，也不假裝是平台**，而且讓 `git log` 上看得出哪些 commit 出自無人值守的 run。
bot identity 與 commit trailer 的完整形式是 V2.3。

### 5.5 一件要回寫紅線的事

`research/02/00` §7 紅線 4 換上的四條約束，第 1、2 條的原文是：

> 1. **分支命名空間強制**：Agent 只能推 `cliora/<card_ref>-<run_seq>`，寫死在 daemon，不是設定值。
> 2. **永不推上共用分支**：base／target 分支、受保護分支一律拒絕，即使卡片這樣寫。

「Agent 只能推」這個主詞在第二次裁決之後**不準確**了。要改成的措辭：

> 1. **分支命名空間強制**：**平台的 push 路徑**只推 `cliora/<card_ref>-<run_seq>`，
>    寫死在 daemon，不是設定值。
> 2. **永不推上共用分支**：**平台的 push 路徑**對 base／target 分支、受保護分支一律拒絕，
>    即使卡片這樣寫。
>
> 這兩條約束的對象是**平台代表卡片執行的 push**（V2.3 起）。
> Agent 在沙箱內用 node 既有憑證的 git 操作**不在這兩條的範圍內**——
> 那是刻意給的自由（ADR 0031 §5.4 第三點），收斂點是紅線 5 的原則
> （沒有人 merge 的分支不影響任何人）與 node 的部署姿態，不是 daemon 的 argv 表。

**這是本期唯一一處需要改紅線措辭的地方**，而它要在 `AR-01` 一起做——
不改的話，V2.3 的人會讀到一條說「Agent 只能推 `cliora/`」的紅線，
而那件事在 V2.2 就已經不是真的。

## 6. `git diff` 附成產物（D20）

run 結束時，若 `delivery ∈ {none, artifact}` 且 `git status --porcelain` 非空：

```text
1. git diff > <run>/artifacts/changes-<run_id>.patch
2. 用 run token 上傳成一件產物（06-…md §3）
3. run 摘要寫「本卡宣告不交付，但偵測到 N 個檔案變更，diff 已附為產物」
```

D21 的誠實性規則原本排在 V2.4。裁決之後**它在本期就必要了**：
run 真的會拉程式碼、真的會改檔案，而 run 目錄有保留期。
不附成產物，那份工作會在三天後消失，**而使用者不會知道它曾經存在**。

第二次裁決（Agent 可以自己 push）**不讓這條規則變得不必要**，只是縮小了它的適用面：
一個推了分支的 Agent 的工作不會消失，但一個**沒推**的 Agent 的工作仍然會。
而平台分不出這兩種——它只知道工作目錄有變更。所以規則不變：**有變更就附**。
`git log --branches --not --remotes` 的行數（§5.4 第四點）寫進摘要，
讓人看得出「這份 diff 是不是已經在遠端有一份了」。

`git diff` 只涵蓋已追蹤檔案的修改。新增的未追蹤檔案要另外處理：
`git status --porcelain` 的 `??` 行數寫進摘要，**但不自動打包**——
一個 `node_modules/` 會讓那件產物爆掉配額。摘要要寫清楚
「另有 N 個未追蹤的新檔案未附加」，讓人決定。

## 7. 測試清單（本兩票）

| # | 測試 | 斷言 |
|---|---|---|
| 1 | `work_dir` 設在 allowed root 內 | daemon **拒絕以 runner 模式啟動**，訊息指名是哪一個 root（正反兩向都測：root 在 work_dir 內也要拒） |
| 2 | `filesystem.list` 指向 run 目錄 | `WORKSPACE_OUTSIDE_ALLOWED_ROOT` |
| 3 | ~~run 程序讀 allowed root 內的檔案~~ | **這條測試刪除**（§3.4）：它斷言的是一件平台沒有實作的隔離。取代它的是下面三條 |
| 3a | 平台的任何路徑都沒有寫 allowed root | `GATE-AR-TOUCH-LIST`（`files/`、`workspace/` 零 diff）＋ run 全程 workspace 的 `git status --porcelain` 為空 |
| 3b | `allowed_roots: []` 的 node | `runner.register` 回報 `dedicated: true`，Agents 頁顯示「專用 runner」 |
| 3c | `allowed_roots` 非空的 node | 回報 `dedicated: false`，Agents 頁顯示 **⚠ 混合用途（Agent 可讀取那些目錄）**，且 `agentd doctor` 印同一行 |
| 4 | `source: repo` 第一次 | mirror 建立、worktree 掛出、`commit_sha` 正確、**`origin` 仍在**（第二次裁決：不移除） |
| 5 | `source: repo` 第二次（同 repo） | **沒有第二次完整 clone**（比對耗時與 mirror 的 mtime） |
| 6 | `source: none` | **沒有** `repo/` 目錄 |
| 7 | repo URL 的 host 不在 allowlist | dispatch 前就擋（Central）＋ daemon 也擋（兩層） |
| 8 | repo URL 帶 userinfo（`https://u:p@host/…`） | 拒絕，訊息不回顯 URL |
| 8b | 🆕 run 摘要裡的 `git remote -v` | **userinfo 被遮掉**（即使 URL 是從別處來的） |
| 8c | 🆕 三個 fail-fast 環境變數 | **只出現在 daemon 自己的 git 呼叫環境**，**不在 Agent 程序的環境裡**（§5.4 第二點） |
| 9 | 缺憑證的私有 repo | **秒級** `run.failed`。⚠️ 注意 idle timer **救不了這一種**——一個掛在密碼提示上的 `git` 不會產生事件，但它也不是 child 的事件流（clone 在 `run.accept` 之前），所以只有這三個環境變數擋得住它 |
| 10 | 單 run 配額用盡 | run `failed` ＋ `RUN_DISK_QUOTA`，log 明示 |
| 11 | node 總量配額用盡 | **停止 poll**，heartbeat 回報原因，平台顯示「磁碟用盡」而非「離線」 |
| 12 | 保留期到期 | 成功 run 的目錄在 3 天後消失、失敗的在 14 天後；**token 檔在 run 結束時就已經不見了** |
| 13 | 清理迴圈與 daemon 重啟 | 沒有孤兒 ticker（`defer <-done` 的既有形狀）；重啟後仍會清掉上次留下的過期目錄 |
| 14 | `delivery: none` ＋ 有變更 | `git diff` 成為一件產物；摘要含檔案數；**未追蹤檔案只計數不打包** |
| 15 | run 全程 | 該 Project 每一個綁定 workspace 的 `git status --porcelain` **為空** |
| 16 | run 結束 | 摘要記錄了 `git remote -v` 與未推送 commit 的行數（可觀測性，§5.4 第四點） |
| 17 | 🆕 Agent 在 run 目錄裡 `git push` 到一個 scratch 遠端 | **成功**（不是被擋下）。這條測試的存在本身就是那個裁決的記錄——它會在有人「順手」把 origin 移除時紅 |
