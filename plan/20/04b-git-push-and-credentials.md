# 04b — `SC-07b`：git 送回、兩種認證與五條硬約束

> **安全審查第三節就是這一份文件驗的東西。**
> 本期新增的是**平台第一次代表卡片對外寫入**——V2.2 為止平台一次 push 都沒發生過
> （`plan/18/00` 不得弄壞第 11 條）。

> ## ⚠️ 這份文件分成兩半，而它們的預設狀態相反（2026-08-13 裁決）
>
> | 半邊 | 內容 | 預設 |
> |---|---|---|
> | **送回** | 分支命名空間、`Push`、五條硬約束、commit identity（§2、§4、§5） | **開啟。** 用 node 上既有的憑證推——與 V2.2 的 clone 同一種來源 |
> | **憑證** | `GIT_ASKPASS` helper、`ssh-agent`、ambient 隔離（§3） | **關閉。** `CLIORA_GIT_SECRET_DELIVERY_ENABLED`，預設 `false` |
>
> 裁決的原話：**「平台下放 git 憑證涉及較廣。可以實作，但由環境變數控制、預設不開放。
> 現階段以 node 端手動配置為準，手動配置這部分系統不用管，交給 node owner 自行處理。」**
>
> **兩個要一起記住的後果**：
>
> - **五條硬約束與用哪一種憑證無關**（D10）。它們約束的是**推什麼**，
>   所以預設組態下它們一樣完整適用。
> - **但「可撤銷」在預設路徑上不成立**——平台拿的是機器的憑證，撤銷不了。
>   收斂點回到 node 的部署姿態與紅線 5。**這一句要寫進 ADR 0031 的 amend**，
>   它是這條裁決最容易被忽略的後果：平台開始 push 了，而它推的憑證平台管不到。

## 1. 現況

`daemon/internal/gitfetch/gitfetch.go`（348 行）已經有：

| 有的 | 說明 |
|---|---|
| `Fetcher{AllowedHosts, KnownHosts, Timeout, Env}` | node 端的 host allowlist（Central 是粗篩、node 是最終權威） |
| `CheckURL` | scheme 只能 https／ssh；**userinfo 只接受字面 `git@` 且只在 ssh 上**；冒號那一半（密碼）不可表示 |
| `Clone` | `--depth 1 --single-branch --branch <ref> --no-tags -- <url> <dest>`，**detached HEAD、不建分支** |
| `fetchEnv` | `GIT_TERMINAL_PROMPT=0`、**`GIT_ASKPASS=/bin/false`**、`GIT_SSH_COMMAND` 含 `BatchMode=yes` ＋ `StrictHostKeyChecking=yes` ＋ known_hosts |
| `Status`／`Diff`／`Remotes`／`UnpushedCommits` | run 摘要用；`Remotes` 已經 `MaskUserinfo` |
| `SetRunIdentity` | `user.name=cliora-run`、`user.email=cliora-run@<node>`。註解自己寫著「bot identity 與 commit trailer 完整版是 V2.3」 |
| `validRef` | 前導 `-` 被拒（封閉 argv 表保護不了一個**本身就是 flag** 的值） |
| `run` | 每一個子命令都走這裡，`cmd.Env = f.fetchEnv(f.Env)` |

**`origin` 在**。V2.2 的第二次裁決撤回了「clone 之後移除 origin」（`gitfetch.go:141`）。

## 2. 五條硬約束的實作位置

新檔 `daemon/internal/gitfetch/push.go`。**一張封閉表，五條約束各對應表裡的一個位置**：

```go
// Push 是平台代表卡片執行的唯一一種遠端寫入。
//
// **argv 是封閉的，而且它比 clone 的那張更封閉**：clone 的 URL 來自平台設定，
// 而這裡連 refspec 都是組出來的——呼叫端能決定的只有分支名，而分支名要通過
// 前綴檢查。五條硬約束（ADR 0031 amend）在這個函式裡各有一個 return。
func (f Fetcher) Push(ctx context.Context, dir, branch, remoteURL string) error {
    // ① 只能推 cliora/ 前綴
    if !strings.HasPrefix(branch, "cliora/") || !validRef(branch) {
        return fmt.Errorf("%w: %q", ErrBranchNotAllowed, branch)
    }
    // ② 永不推 base/target 分支 —— ① 已經涵蓋（base/target 不可能有 cliora/ 前綴），
    //    但仍然明寫一條，因為「涵蓋」是一個推論而約束要是一個斷言
    if branch == f.BaseBranch || branch == f.TargetBranch {
        return fmt.Errorf("%w: %q is the base or target branch", ErrBranchNotAllowed, branch)
    }
    // ④ remote allowlist —— 與 clone 走同一個 CheckURL
    if err := f.CheckURL(remoteURL); err != nil {
        return err
    }
    // ③ 沒有 --force、沒有 --delete、沒有 --tags、沒有 :refs/…，
    //    而且 refspec 是組出來的不是傳進來的
    args := []string{"push", "--", remoteURL,
        "refs/heads/" + branch + ":refs/heads/" + branch}
    _, err := f.run(ctx, dir, args...)
    return err
}
```

**第③條的實作方式是「那些 flag 根本不在表裡」**，這比檢查它們不存在強：
一個檢查可以被繞過（多一個呼叫點），一張沒有那個字串的表不行。
`GATE-SC-PUSH-ARGV` 用 `ast`／文字掃描斷言 `daemon/internal/gitfetch/` 裡
**不存在** `--force`、`--force-with-lease`、`--delete`、`--tags`、`--mirror`、
`push --all` 這些字串，`--prune` 只允許出現在註解裡。

**第⑤條在別的地方**（§4）：commit trailer 與 bot identity 是 commit 的屬性，不是 push 的。

### 2.1 為什麼 URL 每次傳進去而不是用 `origin`

`git push origin <branch>` 會用 `.git/config` 裡的 URL，而那個檔案
**Agent 在 run 期間可以改**（沙箱內的 git 自由，2026-08-10 ②）。
傳明確的 URL 讓第④條的 allowlist 檢查對的是**平台知道的那個位址**，
而不是 Agent 最後一次寫進 config 的那個。

⚠️ 這也意味著 `git remote -v` 上顯示的 origin 與平台推的目標**可能不同**，
而那是 run 摘要已經在報告的事實（`Remotes` ＋ `UnpushedCommits`）。
Run 詳情頁要把兩者並排：**「平台推到：`github.com/org/repo`」與
「工作目錄的遠端：…」**。不一致本身不是錯誤，但它是一個值得看見的事實。

## 3. 兩種認證（**整節預設關閉**）

> `CLIORA_GIT_SECRET_DELIVERY_ENABLED=false`（預設）時：
> Central 不會把 `kind: git_*` 的機密放進 `spec.secrets`，所以 daemon 端
> `secrets.git` 是空的，本節的每一條路徑都不執行——
> **`fetchEnv` 逐位元組維持 V2.2 的樣子**（`GIT_ASKPASS=/bin/false`、
> `GIT_TERMINAL_PROMPT=0`、`GIT_SSH_COMMAND`），clone 與 push 用機器的憑證。
>
> **這一節仍然要完整實作與測試**，只是驗收時要標明是在旗標開啟的組態下跑的。

**兩者都不得把 token 或私鑰寫進檔案。**

### 3.1 Fine-grained PAT（D7）

`GIT_ASKPASS` 現在被寫死成 `/bin/false`（`gitfetch.go:92`），而那是出口條件 9
（缺憑證秒級失敗，V2.2 實測 2.7 秒）成立的三個變數之一。
本期讓兩者**一起成立**：

```go
func (f Fetcher) fetchEnv(base []string) []string {
    // AskpassPath 只有在這次 run 收到了平台的 git 憑證時才非空。旗標關閉的
    // 預設組態下這個函式的輸出與 V2.2 逐位元組相同。
    askpass := "/bin/false"
    if f.AskpassPath != "" {
        askpass = f.AskpassPath
    }
    env := append(append([]string{}, base...),
        "GIT_TERMINAL_PROMPT=0",     // 保留
        "GIT_ASKPASS="+askpass,
        "GIT_SSH_COMMAND="+ssh)      // 保留
    if f.Password != "" {
        env = append(env, "CLIORA_GIT_PASSWORD="+f.Password)
        env = append(env, "CLIORA_GIT_USERNAME="+f.Username)
    }
    return env
}
```

helper 是 run 目錄裡一支 0700 的檔案，**內容不含機密**：

```sh
#!/bin/sh
case "$1" in
  Username*) printf '%s' "${CLIORA_GIT_USERNAME:-x-access-token}" ;;
  *)         printf '%s' "${CLIORA_GIT_PASSWORD}" ;;
esac
```

四個性質：

1. **helper 本身可以被讀、被複製、被 commit，而它什麼都不洩漏。**
   值在環境裡，而環境是 daemon 給 git 程序的——**不是給 CLI 子程序的**（D5）。
2. **沒有值時輸出空字串** → git 認證失敗 → 仍然是秒級失敗。
   `GIT_TERMINAL_PROMPT=0` 保證它不會退回互動提示。
   **出口條件 9 要在本期重跑一次**，因為本期動到了它成立的那個變數。
3. **不得把 token 塞進 remote URL**（出現在 `git remote -v`、reflog、錯誤訊息，
   而 contract 的 URL pattern 已經讓它不可表示——`run-source.schema.json` 的
   「冒號那一半不可表示」正是這條規則在 wire 上的形式）。
4. **不得用 `-c http.extraHeader`**（出現在 `ps`）。

**四處斷言**（出口條件 6b）：clone ＋ push 各跑一次之後，
`git remote -v`、`.git/logs/HEAD`（reflog）、`/proc/<pid>/cmdline`（run 期間取樣）、
以及失敗路徑的 `err.Error()` 四者都不含 token。

### 3.2 SSH key（D8）

```go
// StartAgent 為一個 run 起一個 ssh-agent，把私鑰從 **stdin** 餵進去。
//
// **socket 不是金鑰。** 這是對「機密不落檔」的細化，明寫在 ADR 0032 §2 的第十條旁邊：
// 一個 0700 的 socket 在 run 目錄裡、run 結束就消失，而一個 0600 的私鑰檔在磁碟上，
// 而且刪除失敗就留在那裡。實作時最容易退回的就是後者。
func StartAgent(ctx context.Context, dir, privateKey string) (*Agent, error)
```

- `ssh-agent -a <run>/.cliora/ssh-agent.sock`，socket 的父目錄 0700。
- `ssh-add -` 從 **stdin** 讀入私鑰。**永不落檔。**
- `SSH_AUTH_SOCK` 只進 `Fetcher.Env`，**不進子程序的環境**（D5）。
- run 結束 `Agent.Close()`：kill 程序 ＋ 移除 socket。
  **`defer` 不夠**——run 可能被 SIGKILL。所以 run 目錄的清理迴圈
  （`runner/rundir.go` 已有）也要處理殘留的 socket，而 `ssh-agent` 程序
  由 `Setpgid` 的 process group 終止一併收掉（V2.2 已建立的機制）。
- **known_hosts pinning ＋ `StrictHostKeyChecking=yes`** 沿用既有的
  `GIT_SSH_COMMAND`，一行都不改。

**出口條件 6c 的三條**：私鑰**從未寫入磁碟**（run 目錄全域搜尋比對）；
run 結束後 `ssh-agent` 程序不殘留（掃 `/proc` 第 5 欄，沿用 V2.2 的 pgid 掃描）；
未知 host 被 `StrictHostKeyChecking` 拒絕。

### 3.3 一個必須在 UI 就擋下來的後果

**SSH 只有 git 傳輸、沒有 API**，所以用 SSH 認證的 repo 若卡片
`delivery: pull_request`，**必定還需要一枚 `provider_token`**。

| repo 認證 | push | 開 PR |
|---|---|---|
| PAT（含 `Pull requests: RW`） | ✅ 同一枚 | ✅ 同一枚 |
| PAT（只有 `Contents: RW`） | ✅ | ❌ 需另一枚 |
| **SSH key** | ✅ | ❌ **必定**需要另一枚 |

**設定 repository 時就檢查並擋下儲存**（出口條件 6d），不要等 run 跑到最後一步才失敗——
那時分支已經推上去了，使用者只會看到一個沒頭沒尾的錯誤。

⚠️ **本期 `delivery: pull_request` 本來就會在 dispatch 被 409**（V2.4），
所以這條檢查在本期**擋不到任何一次真的失敗**。它仍然要做，理由是
`provider_token_secret_id` 這一欄本期就建了（`02-…md` §1.4），
而一個建了但沒有人檢查它的欄位，會在 V2.4 變成一個「我以為有擋」的洞。

## 4. 分支與 commit

### 4.1 建立分支（D15）

`source: repo` → clone 之後 `git checkout -b <spec.branch>`，
分支名由 Central 組（`cliora/<card_ref>-<run_seq>`），daemon **驗前綴**。

`source: existing_branch` → checkout 既有分支，**不新建**。
這時 `spec.branch` 缺席，而 push 的目標就是那條既有分支——
⚠️ **但第①條硬約束仍然適用**：既有分支若不是 `cliora/` 前綴，
**push 被拒**。這是對的：`existing_branch` 的用途是「接續前一次 run」，
而前一次 run 推的就是一條 `cliora/` 分支。要在別人的 feature branch 上接續？
那不是本期的能力。**這一條要在 dispatch 時就檢查並說明**，不要留到 push 才拒絕。

`source: none` → 不建 `repo/`（V2.2 已成立），`delivery` 只能是 `none`／`artifact`。

### 4.2 淺 clone 與 push 的關係

V2.2 決定用 `--depth 1 --single-branch`（M11：mirror 每次只省 1.5 秒，
`plan/18/09` §3 第 11 條）。**從淺 clone push 一條新分支是可行的**——
遠端已經有那些 commit 的祖先。

⚠️ **一個要實測的邊界**：某些 host 對 shallow push 有限制。
**這是 `SC-07b` 的第一件事**：對 scratch 遠端與 Traqora 各推一次，
確認 `--depth 1` 之下 push 成立。若不成立，退路是 `git fetch --unshallow`
在 push 之前跑一次——**那會讓大 repo 的 run 多等一次完整 fetch**，
而那是一個要記在 `09-…md` 的量測。

### 4.3 commit trailer 與 bot identity（第⑤條）

`SetRunIdentity` 已經寫了 `cliora-run` 的 name／email（`gitfetch.go:232`，
註解自己寫著完整版是 V2.3）。本期補 trailer：

```
git config --local commit.template <run>/.cliora/commit-template
```

template 內容是兩行 trailer：

```
Cliora-Run-Id: <run_id>
Cliora-Card: <card_ref>
```

⚠️ **template 只影響互動式 commit，`-m` 會忽略它**——而 Agent 幾乎一定用 `-m`。
所以第⑤條真正的落地是 **`commit.gpgsign=false` ＋ `user.*` 那兩格已經在的東西**，
加上一個 **`prepare-commit-msg` hook**（run 目錄內，0700）附加 trailer。

**這一段要誠實寫進 ADR**：hook 是 Agent 可以刪掉的
（它在 Agent 有寫入權的目錄裡）。所以第⑤條的保證等級是
**「平台不冒充人類」（`user.email` 是 `cliora-run@<node>`，這一條是硬的）**
加上**「盡力標註來源」（trailer，這一條不是）**。
把兩者寫成同一條約束會讓後者的弱點藏在前者後面。

## 5. `executeRun` 的接法

`run_handlers.go` 的 `executeRun` 在 `Inspect` 之後、`DropToken` 之前插入：

```go
if offer.Spec.Branch != "" && summary.Dirty {
    if err := m.runner.Deliver(ctx, layout, offer, secrets); err != nil {
        // push 失敗不讓 run 變成 failed —— 工作還在，diff 還可以附成產物。
        // 但摘要要說出來，因為一句錯的「已推送」比一句「沒推送」難查得多
        // （V2.2 的 diff 上傳缺陷 plan/18/09 §3 第 20 條的同一條教訓）。
        summaryText += " ⚠ 分支未能推送：" + redact(err.Error())
    } else {
        summaryText += fmt.Sprintf(" 已推送分支 %s。", offer.Spec.Branch)
    }
}
```

四個決定：

- **push 之前先 commit 未提交的變更嗎？不。** 若 Agent 沒有 commit，
  那就沒有東西可推——`ShouldAttachDiff` 的誠實性規則（V2.2）接手，
  diff 被附成產物。**平台不替 Agent 決定什麼算一個 commit。**
  ⚠️ 這代表 `delivery: branch` 但 Agent 只改檔沒 commit 時，
  結果是「沒有分支 ＋ 一件 diff 產物」，而摘要要明說。
- **push 失敗不算 run 失敗**（V2.4 的 `delivered_branch_only` 是同一個形狀的前身）。
- **錯誤訊息要過 Redactor**（D6）——git 的 stderr 是最可能帶 token 的那一條路徑。
- **`run.complete` 加 `delivery_ref`？不。** 那是 v1.13.0／V2.4（`research/02/08` §4）。
  本期把分支名放進 `summary` 的文字裡，Run 詳情頁從 `spec.branch` 顯示它。

## 6. 測試

`daemon/internal/gitfetch/push_test.go`（**對真的 git 與一個本地 bare 遠端跑**，
沿用 V2.2 `gitfetch_test.go` 的既有形狀）：

1. 推 `cliora/TASK-1-1` → 成功，遠端有那條分支。
2. 推 `main` → `ErrBranchNotAllowed`，**且 `git` 從未被執行**（用一個會記錄呼叫的 fake `run`）。
3. 推 `feature/x`（非 `cliora/` 前綴）→ 拒絕。
4. 推到 allowlist 外的 host → `ErrHostNotAllowed`。
5. `--force` 之類的字串**不存在於封裝裡**（`GATE-SC-PUSH-ARGV` 的單元測試版本）。
6. **PAT 路徑**：clone ＋ push 成功；token 不在 `git remote -v`、reflog、
   `err.Error()`；helper 檔案內容不含 token。
7. **SSH 路徑**：clone ＋ push 成功；run 目錄全域搜尋不含私鑰；
   `Close()` 之後 socket 不存在、程序不在。
8. 未知 host 被 `StrictHostKeyChecking` 拒絕（用一個沒有進 known_hosts 的本地 sshd，
   或以 `GIT_SSH_COMMAND` 的錯誤訊息斷言）。
9. **淺 clone 之後 push 一條新分支成立**（§4.2 的那條實測）。
10. `existing_branch` 且分支不是 `cliora/` 前綴 → push 被拒，
    **而 dispatch 早就該擋下它**（一條 Central 端的對應測試）。
11. 🆕 **`secrets.git` 為空時 `fetchEnv` 的輸出與 V2.2 逐位元組相同**
    （旗標關閉的預設路徑，§3 的前提）。
12. 🆕 **預設組態下 push 仍然成功**（用測試環境自己的 git 憑證），
    且五條硬約束的四種拒絕**在這個組態下也全部成立**——
    約束與憑證無關（D10）。**第 12 條是本期最容易漏測的一條**：
    §6 的其餘測試很自然地會在「有平台憑證」的組態下寫，而使用者跑的是另一個。

**第 2 條的「git 從未被執行」比「回傳錯誤」重要**：
一條約束若只是在 git 失敗之後回一個錯誤，那它不是約束，是運氣。
