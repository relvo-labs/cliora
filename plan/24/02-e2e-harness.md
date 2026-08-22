# 02 — E2E 堆疊（`CE-01`、`CE-02`）

## 1. 現況：堆疊有一半

`plan/23/10` §9.2 為了量效能，替 `scripts/e2e/run-stack.sh` 加了 `E2E_RUNNER=1`：
兩個 feature flag、`runner:` 設定區塊、Central 那一側的 runner 啟用、
以及 `fakecli` 的 runner 模式（`-p` ＋ JSONL 事件流）。那一段確實有用——
`measure-answer-to-turn.py` 就是靠它量到 P95 5.00s 的。

**但那個腳本量的是「answer 之後多久有新 run」，它從來不需要 Agent 真的做任何事。**
一旦旅程需要 Agent 提問、提規格、失敗，堆疊就缺三樣東西：

```text
① run 裡沒有 cliora            → Agent 不能問問題（J1a/J3/J5/J7/J8 全部卡在第一步）
② fakecli 永遠 exit 0          → 造不出失敗的 run（J7 卡在第一步）
③ daemon 的 handle 沒有 export → 測試不能重啟它（J5 卡在第二步）
```

## 2. ① run 裡的 `cliora`

### 症狀

子行程的環境是 daemon 的環境（`daemon/internal/connection/run_handlers.go:327`）：

```go
childEnv := append(secrets.ChildEnv(os.Environ()), isolation...)
```

`run-stack.sh` 啟動 daemon 時的 `PATH` 只加過 `/usr/local/go/bin`（第 86 行），
而所有二進位放在 `$BIN`（`$WORK/bin`），**`$BIN` 從未進入 `PATH`**。
所以 run 裡的任何 `cliora …` 都是 `command not found`。

這一條與 `plan/23/10` §9.1 是**同一條縫的兩半**：那一次修好了「`cliora` 找得到自己的憑證」，
而在 e2e 的 run 裡，它連被執行的機會都沒有。兩邊各自的測試都是綠的。

### 做法

```bash
# scripts/e2e/run-stack.sh，緊接在 go build 之後
ln -sf "$BIN/agentd" "$BIN/cliora"     # 一個 binary 兩個工具（ADR 0028 §4）
export PATH="$BIN:$PATH"               # daemon 的環境 → 子行程的環境
```

**用 symlink 而不是 `agentd cliora …`**：`cli.NewCommand()` 兩條路都通
（`daemon/cmd/agentd/main.go:30` 看 `filepath.Base(os.Args[0])`，
第 57 行同時把它掛成子命令），但**真的部署走的是 symlink**
（`install.go:220` `ensureCLISymlink`，`/usr/local/bin/cliora`）。
旅程要走使用者真的會走的那條路，否則它證明的是另一個東西。

`export PATH="$BIN:$PATH"` 放在 daemon 啟動之前、且 `$BIN` 在**前面**：
機器上若剛好裝了別的 `cliora`，堆疊要用自己建的那一個。

### 怎麼知道它修好了

`CE-01` 附一條斷言：堆疊起來之後，用一個最小的 run 執行 `cliora context show`，
斷言 exit code 0 且輸出含卡片編號。**這條斷言比它看起來重要**——
它是「Agent 那半邊活著」的最小證明，其餘六條旅程全部建立在它上面。

## 3. ② fakecli 造得出失敗

### 症狀

`runNonInteractive()`（`daemon/cmd/fakecli/main.go`）不論腳本成功與否，
最後都送 `{"type":"result","subtype":"success","is_error":false}` 然後 exit 0。
腳本的失敗只出現在中間那個事件的 `"failed": true` 欄位裡。

而 daemon 判定失敗看的是 `outcome.ExitCode != 0`
（`run_handlers.go:485`）。所以**目前的堆疊造不出一個 failed run**。

### 做法

讓腳本的退出碼變成行程的退出碼，並且照樣送完事件：

```go
if script := os.Getenv("CLIORA_FAKECLI_SCRIPT"); script != "" {
    cmd := exec.Command("/bin/bash", script)
    cmd.Dir, cmd.Env = ".", os.Environ()
    out, err := cmd.CombinedOutput()
    emit(...)                                  // 不變
    if code := exitCode(err); code != 0 {
        // 先把 result 事件送出去再離開：daemon 從事件流判斷活著，
        // 一個沒有 result 就消失的行程與一個被 idle timeout 殺掉的行程
        // 在日誌上長得一樣，而那是兩種不同的失敗。
        emit(map[string]any{"type": "result", "subtype": "error", "is_error": true})
        os.Exit(code)
    }
}
```

`cmd/fakecli/` 不在任何禁區清單上（[`00`](./00-execution-plan.md) §3），
`GATE-CV-TOUCH-LIST` 不列它——它是 stand-in 不是產品。

## 4. ③ daemon 可以被重啟

### 症狀

`run-stack.sh` 把 binary、config、credentials 都放在 `mktemp -d` 出來的 `$WORK` 底下，
export 出去的只有 `E2E_WORKSPACE_ROOT`、`E2E_RUNNER_WORK_DIR`、`E2E_RUNNER_ID`、
`E2E_BASE_URL` 與帳密。**PID 只活在 `PIDS[]` 這個陣列裡**，
而那個陣列連 export 都不可能（bash 陣列不進環境）。

### 做法

多 export 三個變數，並提供一個腳本：

```bash
export E2E_DAEMON_BIN="$BIN/agentd"
export E2E_DAEMON_CONFIG="$WORK/config.yaml"
export E2E_DAEMON_CREDENTIALS="$WORK/credentials.yaml"
export E2E_DAEMON_LOG="$WORK/agentd.log"
export E2E_DAEMON_PGID="$daemon_pid"     # setsid 之後 PID == PGID
```

`scripts/cv/daemon-ctl.sh {kill|start|wait-online}` 用它們做三件事：

| 子命令 | 做什麼 | 為什麼是這個做法 |
|---|---|---|
| `kill` | `kill -9 -- -$E2E_DAEMON_PGID` | D75：崩潰而不是優雅關閉，且要收掉子行程 |
| `start` | 用同一組 config／credentials 重新 `setsid`，把新的 PGID 寫回 `$E2E_DAEMON_PGID_FILE` | 同一個節點身分重新上線，這正是「daemon 重啟」的意思 |
| `wait-online` | 輪詢 `/api/nodes` 直到該節點 `status == "online"`，逾時 30s 就失敗並 `tail` 日誌 | 一個「重啟了但沒上線」的旅程，錯誤訊息必須說出這件事，否則它會被讀成「turn 沒有被建立」 |

`E2E_DAEMON_PGID` 用一個**檔案**而不是只靠環境變數傳遞：
重啟之後 PGID 會變，而子行程改不了父行程的環境。
檔案路徑本身用環境變數傳（`E2E_DAEMON_PGID_FILE`）。

## 5. `E2E_*` 契約（本期之後的完整清單）

| 變數 | 由誰設 | 意義 |
|---|---|---|
| `E2E_RUNNER=1` | 呼叫者 | 啟用 runner 模式（旗標、`runner:` 區塊、Central 端啟用）——`plan/23` 已有 |
| `E2E_CONVERSATION=1` | 呼叫者 | **新增**：啟用 `conversation.spec.ts` 的三條瀏覽器旅程 |
| `E2E_BASE_URL` / `E2E_API_URL` | 堆疊 / 規格 | Central 位址。既有規格讀 `E2E_API_URL`（預設同值） |
| `E2E_WORKSPACE_ROOT` | 堆疊 | 節點的 workspace 根 |
| `E2E_RUNNER_ID` / `E2E_RUNNER_WORK_DIR` | 堆疊 | runner 的 id 與 run 目錄 |
| `E2E_DAEMON_BIN` / `_CONFIG` / `_CREDENTIALS` / `_LOG` / `_PGID_FILE` | 堆疊 | **新增**：`CE-06` 重啟 daemon 用 |
| `E2E_AGENT_SCRIPT` | 堆疊 | **新增**：指向 `scripts/cv/agent/clarify.sh`，同時設成 daemon 環境的 `CLIORA_FAKECLI_SCRIPT` |
| `E2E_COMPAT_DAEMON_BIN` | 呼叫者 | **新增**：`CE-09` 用 0.12.0 的 binary 起第二個節點 |

## 6. 會提問的 Agent（`CE-02`）

`scripts/cv/agent/clarify.sh`——一個 bash 腳本，**每一輪重新讀對話決定自己要做什麼**（D70）：

```bash
#!/usr/bin/env bash
# 這一輪要做什麼，由對話本身回答。沒有計數器檔：continuation 的工作目錄是新的，
# 而 /tmp 的固定路徑會讓兩條並行的旅程互相污染。
set -uo pipefail
page="$(cliora task messages --after 0 --json)" || exit 3

questions=$(jq '[.items[] | select(.kind=="question")] | length' <<<"$page")
proposals=$(jq '[.items[] | select(.kind=="proposal")] | length' <<<"$page")
changes=$(jq '[.items[] | select(.kind=="decision" and (.body|startswith("要求修改")))] | length' <<<"$page")

if   [ "$questions" -eq 0 ]; then cliora task ask "這個功能要不要支援 SSO？"
elif [ "$questions" -eq 1 ]; then cliora task ask "登入失敗要重試幾次？"
elif [ "$proposals" -eq 0 ]; then cliora task propose-spec spec-v1.md
elif [ "$changes"  -gt 0 ] && [ "$proposals" -eq 1 ]; then cliora task propose-spec spec-v2.md
else cliora task say "沒有待辦事項。"
fi
```

四件事值得說明：

1. **`--after 0` 讀整串**，不是 `--after $cursor`：這一輪的 Agent 沒有上一輪的記憶，
   而那正是本期要證明的性質（對話不依賴一個行程活著）。
2. **`jq` 是新的外部依賴嗎？** 不是——`run-stack.sh` 已經用 `python3` 解析 JSON。
   為了不新增依賴，實作時用 `python3 -c` 取代 `jq`（形狀相同，此處為可讀性寫成 jq）。
3. **`exit 3`**：`cliora` 讀不到憑證時的退出碼要能與「沒有問題可問」分辨。
   `CE-01` 的最小 run 斷言就是為了讓這一條永遠不會發生。
4. **`spec-v1.md` / `spec-v2.md` 從哪來**：由 `run-stack.sh` 的 workspace fixture 種下
   （沿用既有 `seed_workspace_fixtures` 的做法），
   但要放進 run 的 checkout 而不是 workspace 根——`propose-spec` 的參數是相對於執行目錄的。
   實作時改用 heredoc 就地產生，避免這個路徑問題。

## 7. `CE-03`：clean-room 重驗基線

**`plan/23` 的 21 項出口條件是真的通過了，但那是在一台跑了一整期的機器上。**
封版前重跑一次，理由與 `research/03/00` §6 的 freeze checklist 第二列相同：
「在乾淨環境重跑 gates 與測試，**保存環境／版本／輸出**」。

`scripts/cv/evidence.sh`（形狀沿用 `scripts/pj/evidence.sh`）：

```text
0 環境          uv / go / node / PostgreSQL 版本、commit、dirty、agentd、contract
1 三套測試      pytest backend/tests、go test ./...、vitest --run
  make check    format / lint / typecheck / tokens / unit / contract / build / traceability / railway
2 八個 gate     scripts/cv/gates.sh（含 MIGRATION-ROUNDTRIP，需要資料庫）
3 堆疊（E2E=1） 五項量測 → 七條旅程 → 0.12.0 相容性，一個堆疊跑完
4 三個新 gate   scripts/cv/gate_closeout.py
```

**第 4 節在最後，而第一版把它放在第 2 節。** `GATE-CE-JOURNEY-COVERAGE`
讀的是旅程產生的東西，所以放在旅程前面等於在讀**上一輪**的證據——
在跑過一次的機器上它會綠，在乾淨的 checkout 上它會紅，而這是兩者中比較糟的那個方向。

**第 3 節內部的順序也不是任意的**，理由寫在 `_stack-evidence-inner.sh` 的開頭：
`answer-to-turn` 的守衛把 `waiting_for_input` 算成競爭，所以它要在任何卡片被停下來之前跑；
0.12.0 的相容性檢查放最後，因為它會留下永遠不會結束的 run（`CE-17`），
那對它後面的任何東西都是真的競爭。

**skip 必須帶理由**，這是 `plan/15` 建立、`scripts/pj/evidence.sh` 寫在註解裡的慣例：
一個有解釋的 skip 有用，一個安靜的 skip 是一個什麼都不表示的綠勾。
本期特別容易踩到兩種安靜的 skip：

- `backend/tests/db/` 在 `CLIORA_TEST_DATABASE_URL` 未設時**整批 skip**（`conftest.py:88`）；
- playwright 規格在 env 未設時 `test.skip(!enabled, …)`——**七條旅程全部不跑，套組仍然綠**。

第二種正是 `GATE-CE-JOURNEY-COVERAGE` 存在的理由（[`08`](./08-verification-and-exit.md) §1）。
