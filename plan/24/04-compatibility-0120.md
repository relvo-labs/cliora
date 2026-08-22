# 04 — 未升級節點的實測（`CE-09`）

> 出口條件 **16**；SR-1 的 **finding 2**（Medium，唯一一項 Medium）；
> release note 的 known limitation **6**。**三份文件指的是同一件沒做的事。**

## 1. 現在有的是論證，缺的是一次執行

`docs/security-review-v2c1.md` §3.1 把話說得很準：

> 「一個沒有升級的節點行為完全與以前相同」這個主張建立在兩個靜態事實上：
> `contracts/v1/` 逐位元組相同（`GATE-CV-CONTRACT-FROZEN`），
> daemon 的節點半邊零 diff（`GATE-CV-TOUCH-LIST`）。
> continuation 到達節點時是一個普通的 queued run，走的是
> `runner.poll` → `run.offer` → `run.accept`，全部是 0.12.0 已經會說的話。
> **缺的是用一個真的 0.12.0 binary 跑完一次完整生命週期。**

論證很強。但**論證與證據的差別，正是這一份文件存在的理由**：
兩個 gate 證明的是「我們沒有改那些檔案」，
它們證明不了「那些檔案在新的 Central 面前行為不變」——
因為改變的是 Central 送出什麼，而不是節點怎麼解碼。

## 2. 取得 0.12.0 的 binary（D71）

`git tag -l` 是空的，沒有可下載的 artifact。現地建：

```bash
git worktree add /tmp/cliora-0120 f91d9c4
( cd /tmp/cliora-0120/daemon && go build -o /tmp/cliora-0120/bin/agentd ./cmd/agentd )
/tmp/cliora-0120/bin/agentd version        # 必須印出 0.12.0
```

**第三行是斷言不是確認**：`main.go` 的 `version` 常數與 `daemon/VERSION`
由 `TestVersionMatchesTheVersionFile` 綁在一起（`plan/23/10` §2.12），
所以它印出 0.12.0 就是那個版本。若印出別的，整個 `CE-09` 停下來——
用錯版本的相容性測試，比沒做更糟。

用完 `git worktree remove /tmp/cliora-0120`。

## 3. 編排：兩個節點，一新一舊

`run-stack.sh` 已經有 `E2E_SECOND_NODE=1`（`plan/16` 留下的），
它會用**不同的 workspace root** 再 enroll 一個節點。本期加一個變數：

```bash
E2E_SECOND_NODE=1 E2E_COMPAT_DAEMON_BIN=/tmp/cliora-0120/bin/agentd \
  E2E_RUNNER=1 scripts/e2e/run-stack.sh scripts/cv/compat-0120.sh
```

第二個節點用 0.12.0 的 binary 起，第一個維持 0.13.0。

### 只讓舊節點拿得到工作

兩個 runner 同時在 poll，而 `_eligible()` 是 `ORDER BY queued_at`——
**哪一個先拿到是競態**。相容性測試不能靠運氣。做法：用既有的
runner tag × required labels 機制（V2.3 已有），
給舊節點一個 `compat-0120` 的 tag，卡片的 required labels 指定它。

**不用「把新節點關掉」**：那會讓測試變成「單節點跑舊 binary」，
而真實的升級情境正是**新舊並存**——那才是「未升級的節點」這句話的意思。

## 4. 一次完整生命週期，加一次 continuation

| # | 步驟 | 斷言 |
|---:|---|---|
| 1 | 舊節點上線並註冊為 runner | `/api/nodes` 顯示 `agentd 0.12.0`；`/api/agents` 有它 |
| 2 | 派一張 `delivery: none` 的釐清卡（required labels 指向舊節點） | 由**舊節點**認領：`task_runs.assigned_runner_id` 是它 |
| 3 | Agent 提問（`cliora task ask`）後結束行程 | question `open`；run `succeeded` / `awaiting_input`——**這是新語意，由舊節點觸發** |
| 4 | 人類 answer ＋ resume | continuation 建立 |
| 5 | **continuation 被舊節點認領並執行完** | `parent_run_id` 那一列有 `claimed_at`、`started_at`、`finished_at` |
| 6 | 全程的協定訊息 | 舊節點的日誌**沒有任何解碼失敗**（`grep -i "unknown message\|decode"`） |
| 7 | 對照組 | 同一組步驟在 0.13.0 節點上跑一次，兩邊的 run 結果欄位相同 |

**第 3 步是這條測試的核心。** `finish()` 的推導是 Central 端的改變
（D59），而舊節點送的仍然是 0.12.0 的 `run.complete`。
如果推導依賴任何 0.13.0 才有的欄位，就會在這一步露出來——
而那正是「未升級節點行為不變」這句話唯一可能不成立的地方。

**第 6 步的形狀取自 contract 1.13.0 的 changelog**：那份 changelog 記過
解碼失敗長什麼樣——「產生不了任何回覆——卡片被認領、offer 消失、租約過期、
卡片重試到耗盡然後 blocked，**而任何地方都不會提到相容性**」。
所以斷言要同時看日誌與看結果：只看結果的話，
一個解碼失敗會顯示成「卡片後來 blocked 了」。

## 5. `CV-08` 的四個子命令在舊節點上會怎樣

**會失敗，而且那是正確的。** `messages --after`、`wait`、`say --reply-to`、
`propose-spec` 是 `agentd` **0.13.0** 的 CLI 才有的。
舊節點上的 Agent 只有 0.12.0 的 `cliora`，所以：

| 子命令 | 0.12.0 上的行為 | 這代表什麼 |
|---|---|---|
| `task ask` | **可用**（0.12.0 已有） | 提問 → continuation 這條主線在舊節點上完整成立 |
| `task messages --since` | 可用 | 舊 Agent 讀得到對話，只是用時間戳分頁 |
| `task messages --after` | `unknown flag` | 舊節點的 Agent 不會用新旗標，**不是相容性問題** |
| `task wait` / `propose-spec` | `unknown command` | 同上 |

這一段要寫進 release note 的 upgrade 段：
**節點不需要升級才能參與對話；升級之後 Agent 才拿得到新的 CLI。**
現在的 release note 說了前半句，沒說後半句。

## 6. 輸出

`artifacts/cv/local/compat-0120.json`：

```json
{
  "old_binary": {"path": "…", "version": "0.12.0", "commit": "f91d9c4"},
  "new_binary": {"version": "0.13.0", "commit": "ac3dfef"},
  "old_node": {"claimed": 2, "completed": 2, "decode_errors": 0},
  "new_node_control": {"claimed": 2, "completed": 2},
  "continuation_on_old_node": true,
  "exit_condition_16": "PASS"
}
```

`decode_errors` 必須在輸出裡而不是只在日誌裡：
**一個沒有被印出來的零，與一個沒有被檢查的零，事後看起來一樣。**
