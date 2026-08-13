# 04 — `SC-06`／`SC-07a`／`SC-07`：contract v1.12.0 與 daemon 的機密面

## 1. 現況

| 項目 | 值 |
|---|---|
| contract | **v1.11.0**（`contracts/CHANGELOG.md`）。訊息 schema 在 `contracts/v1/schemas/messages/` |
| 控制訊框上限 | **64 KiB**（`codec.py:15` `MAX_PAYLOAD`）。`LARGE_FRAME_TYPES` 六個型別，**`run.offer` 不在其中** |
| 出口方向的大小檢查 | **沒有。** `codec.py` 只有 `decode_control` 檢查，`encode_binary` 檢查二進位——**組控制訊框的路徑上沒有任何大小斷言** |
| `run-spec.schema.json` | `context` 上限 **65536 字元**——**單欄就等於整個訊框預算** |
| daemon 的 register payload | `run_handlers.go:48` `runnerRegisterPayload()`，**`"labels"` 寫死成 `[]string{}`** |
| daemon 的去識別 | **不存在。** `grep -rn 'Redactor\|redact' daemon/` 只命中 `metrics.go` 的一句註解 |
| daemon 的 env | `run_handlers.go:245` `runtime.RunOptions{Dir, Context, Env: os.Environ()}` |
| `RunnerConfig` | `config.go:190`：`enabled`／`work_dir`／`max_concurrent`／`max_waiting`／`poll_interval_seconds`／`idle_timeout_seconds`／`run_quota_bytes`／`total_quota_bytes`／`min_free_bytes`／`retention_*`／`git.{allowed_hosts,known_hosts_path,fetch_timeout_seconds}` |

## 2. `SC-06` — contract v1.12.0

### 2.1 `runner-register.schema.json`：兩個 optional 欄位

```jsonc
"run_untagged": {
  "$comment": "GitLab 語意的第二半。缺席時視為 true——與 Central 的 server default 一致，所以升級前後行為不變（plan/20/00-…md D12）。這個相容性敘述刻意不依賴任何 agentd 版本號：它斷言的是 payload 的形狀。",
  "type": "boolean"
},
"accept_secrets": {
  "$comment": "node 對自己的宣告：false 的 node，其 runner 只會被 offer required_secrets 為空的卡片（ADR 0032 §0 代償第 2 條）。由 node 的營運者宣告，比平台上的一格勾選更接近事實。缺席時視為 true——與 run_untagged 同一個理由。",
  "type": "boolean"
}
```

`labels` 的 `$comment` 要改寫：現在寫著「Displayed and **never compared** in V2.2」，
本期起它**參與比對**。同時要加一句：**tag 是 runner 自報的能力宣告，不是授權**
（`01` D18；ADR 0029 amend 與 0032 §0 各寫一次，schema 是第三次——
這個重複是刻意的，因為三種讀者只會讀其中一份）。

### 2.2 `run-spec.schema.json`：`secrets`

```jsonc
"secrets": {
  "$comment": "只含這張卡宣告的那幾個，且必須是 Project allowlist 的子集。**值只能來自平台的 secret store**：SEC-002 修訂後的不變式是「沒有任何請求 payload 能命名一個命令、或攜帶一個機密的值」，而這個欄位在 central→node 方向、由平台自己填（ADR 0032 §1）。`kind` 一起送，因為它決定這個值在 node 上會去哪裡：env 進子程序的環境，git_pat/git_ssh_key 只進 daemon 自己的 git 環境（plan/20/00-…md D5）。",
  "type": "array",
  "maxItems": 8,
  "uniqueItems": false,
  "items": {
    "type": "object",
    "additionalProperties": false,
    "required": ["name", "kind", "value"],
    "properties": {
      "name":  {"type": "string", "minLength": 1, "maxLength": 128,
                "pattern": "^[A-Z][A-Z0-9_]*$"},
      "kind":  {"enum": ["env", "git_pat", "git_ssh_key"]},
      "value": {"type": "string", "minLength": 1, "maxLength": 8192}
    }
  }
}
```

四個決定：

- **`name` 的 pattern 是大寫底線。** 它會變成一個環境變數名，
  而一個叫 `PATH` 或 `foo-bar` 的機密是兩種不同的災難。
  ⚠️ **`PATH`／`HOME`／`LD_PRELOAD` 這一類要在 Central 端另外擋**（§4.2），
  schema 擋不了語意。
- **`provider_token` 不在 `kind` 的 enum 裡。** 本期**沒有任何程式碼路徑**會送它
  （它的用途是開 PR ＝ V2.4）。一個永遠送不出去的值不該在 wire 上可表示。
  ⚠️ **`git_pat`／`git_ssh_key` 留在 enum 裡**，即使它們預設不會被送出——
  差別是：`provider_token` 本期**不可能**被送出，而這兩個在
  `CLIORA_GIT_SECRET_DELIVERY_ENABLED=true` 時**會**。旗標是執行期的組態，不是 wire 的形狀。
  schema 的 `$comment` 要寫這一句，否則下一個讀者會以為 enum 與旗標不一致。
- **`maxItems: 8`、單值 8 KiB**（M-SC-1）。8 × 8 KiB = 64 KiB，**單這一格就吃光訊框**——
  所以總量的檢查不能只靠 schema，見 §2.3。
- **`uniqueItems: false`**：物件的唯一性在 JSON Schema 裡是逐欄比對，
  而兩枚不同名但同值的機密是合法的。名稱的唯一性在 Central 端保證（`UNIQUE (project_id, name)`）。

**必要的 invalid fixture**：`secrets` 出現在 `run.offer` 以外的任何訊息 → 拒絕。
這是 SEC-002 修訂後不變式的機器檢查（`research/02/08` §4 明列），
而它成立的方式是**其他訊息的 schema 都是 `additionalProperties: false`**——
所以這條 fixture 驗的是那個性質沒有被誰放寬。

### 2.3 訊框總量：contract 一道，Central 一道（D2）

**schema 那一道**：`run-spec` 加一句 `$comment` 說明總量預算，
並把 `context` 的上限從 65536 **降到 32768**。

> ⚠️ **這是一個 breaking-shaped 的變更，但實際上不是。**
> `render_run_context()`（`runs.py:829`）產生的情境包在實測上是 1–2 KB
> （V2.1 的預算是 4 KB，`01` D8）。65536 這個值從來沒有被用到過，
> 它是一個**錯的上限**——它單獨就等於整個訊框預算。
> 降到 32768 之後，`context` ＋ `secrets` ＋ 其餘欄位的最壞情況仍在 64 KiB 內。
> **既有 fixtures 一個位元組都不會變**（沒有任何一個接近那個數字），
> 所以 `GATE-SC-CONTRACT-ADDITIVE` 仍然綠。

**Central 那一道**：`api/ws/nodes.py` 組完 offer payload、送出之前量一次：

```python
frame = build_control("run.offer", …)
if len(frame.encode("utf-8")) > MAX_PAYLOAD:
    await run_service.release_claim(run, reason="OFFER_TOO_LARGE")
    return
```

**釋放認領而不是靜默丟棄**，這是整個 D2 的重點：
今天的失敗長相是「卡片被領走、offer 消失、租約到期、重排、三次後 `blocked`」，
而使用者看到的是一張莫名其妙壞掉的卡。釋放之後，卡片回到 `queued`
並在訊息串上留一筆系統事件說明是哪一部分太大（情境包還是機密），
**下一次 poll 不會再撞同一個問題，因為問題會被人看見**。

`release_claim` 是新的一個方法，但它與既有的 `run.decline` 處理**共用同一段程式碼**
（`apply_event` 的 `run.decline` 分支已經在做「回 `queued`、清 `runner_id`、
清 `claimed_at`、清 `lease_expires_at`」）——抽成一個 `_release(run)` 給兩者用。

**一條測試**：組一個 `context` 32 KiB ＋ 8 枚各 8 KiB 機密的 offer →
Central 釋放認領、卡片回 `queued`、訊息串上有一筆事件、**`task_runs` 沒有變成 `lost`**。

### 2.4 `run-offer.schema.json`：`branch`

```jsonc
"branch": {
  "$comment": "本次 run 要建立並推送的分支。名字由 Central 組（card_ref 與 seq 都在它手上），但 daemon 仍然要驗前綴——五條硬約束是 daemon 的責任，而一條「Central 保證會送對」的約束不是約束（plan/20/00-…md D15）。delivery 為 none 或 artifact 時缺席。",
  "type": "string",
  "minLength": 8, "maxLength": 255,
  "pattern": "^cliora/[A-Za-z0-9._-]+$"
}
```

### 2.5 CHANGELOG

`contracts/CHANGELOG.md` 的 1.12.0 一節，三段：

- **Added**：`spec.secrets`、`spec.branch`、`runner.register` 的兩個布林。
- **Changed**：`spec.context` 的上限 65536 → 32768，**並說明為什麼那是修正而不是收緊**。
- **Unchanged**：既有訊息一個位元組都不動；既有 fixtures 逐檔 sha256 未變。

**寫這一節的時候要一起寫的一句話**（沿用 1.11.0 那三段「值得在這裡讀而不是在 schema 裡讀」的體例）：

> **一個 runner 說自己有 `docker`，平台就相信它有 `docker`。**
> tag 決定的是**派給哪台機器**，不是**哪台機器可以拿機密**——後者的答案是 enrollment，
> 而它不在這份契約裡，因為它不是一個欄位。

## 3. `SC-07a` — tag 的上報（**排在 Central 的比對之前**，D13）

**這張票很小，而它的位置是本期與 V2.2 最大的順序差異。**

### 3.1 `config.RunnerConfig` 加三個欄位

```go
// Tags 是這台機器對自己能力的宣告，隨 runner.register 上報並參與派工比對
// （ADR 0029 amend）。**這不是授權**：平台相信 runner 自報的 tag，
// 所以多報一個 tag 就能改變自己領到什麼。授權邊界是 enrollment（ADR 0032 §0）。
Tags []string `yaml:"tags"`
// RunUntagged 關掉之後，這台機器只領有宣告 tag 的卡片。這是「把一台機器保留給
// 特定工作」的唯一手段——沒有它，一台專機仍會被一堆沒宣告 tag 的普通卡片佔滿。
// 指標型別，因為 nil（未設定）與 false 要分得開；nil 視為 true。
RunUntagged *bool `yaml:"run_untagged"`
// AcceptSecrets 為 false 時，這台機器只領 required_secrets 為空的卡片。
// 由營運者宣告，比平台上的一格勾選更接近事實（ADR 0032 §0 代償第 2 條）。
AcceptSecrets *bool `yaml:"accept_secrets"`
```

**指標型別是必要的**：`bool` 的零值是 `false`，而未設定必須視為 `true`（D12）。
一個沒寫 `run_untagged` 的既有設定檔在升級後突然什麼卡都不領，
是最難查的那一類回歸。

### 3.2 `runnerRegisterPayload` 讀設定而不是寫死

```go
"labels":         runner.Tags(m.cfg.Runner),      // 排序、去重、**永不 nil**
"run_untagged":   runner.RunUntagged(m.cfg.Runner),
"accept_secrets": runner.AcceptSecrets(m.cfg.Runner),
```

⚠️ **`labels` 永不為 nil**，理由 `plan/18/09` §3 第 17 條已經用一個真實缺陷寫過了：
Go 的 nil slice 序列化成 `null`，contract 說它是 array，
`decode_control` 拋 `ProtocolError`，`node_gateway` 的 `except` 把它吞掉——
**runner 註冊失敗而兩端都沒有錯誤**。那個缺陷是 `runtimes` 撞的，
而 `labels` 走的是完全一樣的路徑。

**同一輪要補的測試**：把 payload 組出來、`BuildControl` 之後跑 `ValidateControl`
（那正是當初漏掉的那條）。

### 3.3 `agentd doctor` 印三行（D14）

```
[ OK ] runner tags            docker, node20
[ OK ] runner run_untagged    true
[WARN] runner accept_secrets  false — 這台機器不會領取宣告了機密的卡片
```

`accept_secrets: false` 用 `[WARN]` 而不是 `[ OK ]`，**但不影響 exit code**
（doctor 的既有契約：警告不改變結果，`commands.go:86`）。
理由是它是一個合法的組態，但它同時是「為什麼這台領不到那張卡」最不明顯的答案。

`runner.enabled` 為 false 時三行都不印——沿用 doctor 既有的
「不報告一個沒開的功能」的作法。

### 3.4 驗收要用一台真的 runner

**`SC-05` 的驗收不得用 SQL 直接改 `agent_runners.labels`。**
`scripts/ar/dev-stack.sh` 已經會起一台 enroll 過的 runner node
（`plan/18/09` §3 第 19 條，注意它是**就地改寫** config 而不是 append），
本期加一個 `--tags docker,node20` 參數。

## 4. `SC-07` — daemon 的機密面（`agentd` 0.10.0）

### 4.1 `kind` 分流（D5）

```go
type Secrets struct {
    env  map[string]string   // kind == "env"      → 子程序的環境
    git  map[string]string   // kind == "git_*"    → 只進 daemon 自己的 git 環境
    all  []string            // 所有值，給 Redactor
}
```

> ⚠️ **`s.git` 在預設組態下永遠是空的**（2026-08-13 裁決，D5b）：
> Central 在 `CLIORA_GIT_SECRET_DELIVERY_ENABLED=false` 時不會把 `kind: git_*`
> 放進 `spec.secrets`。daemon 端**不需要知道那個旗標**——它只看收到什麼，
> 而那正是這個分流寫成資料驅動而不是設定驅動的好處。

**三件事同時成立**：

1. `runtime.BuildRunCommand` 的 `Env` 是 `os.Environ()` ＋ `s.env`，**不含 `s.git`**。
2. `gitfetch.Fetcher.Env` 收到 `s.git` 導出的那幾個變數（`04b-…md` §3）。
   `s.git` 為空時 `Fetcher` 的環境與 V2.2 逐位元組相同。
3. `Redactor` 拿到 `s.all`——**兩類都要去識別**，因為 git 的錯誤訊息會帶 PAT。

**`s` 是一個區域變數，run 結束就沒了。** 沒有任何欄位存在 `Runner` 或 `Manager` 上，
沒有任何值被寫進檔案（`GATE-SC-NO-SECRET-TO-DISK`）。

⚠️ **`WriteContext` 的形狀不得被複製**：`runner/supervisor.go:207` 把 run 憑證寫進
`.cliora/context/run.token`（0600，run 結束刪除）。那是一個**刻意的例外**，
因為 `cliora` CLI 是一支獨立程序、需要從檔案讀憑證。
**機密沒有這個需求**——它們是給 CLI 子程序的環境變數，而環境是繼承的。

### 4.2 危險名稱的擋法在 Central，不在 daemon

`PATH`、`HOME`、`LD_PRELOAD`、`LD_LIBRARY_PATH`、`GIT_*`、`SSH_*`、`CLIORA_*`
這些名字**在建立機密的時候就擋下來**（`SC-04` 的 `POST`，422 並指名）。

**為什麼在 Central 而不是 daemon**：daemon 端擋等於「值送到了才發現不能用」，
而使用者是在 Project Settings 打字的那一刻犯這個錯的。
daemon 端仍然**保留一條最後防線**（收到禁用名稱時跳過該枚並在 log 裡說），
理由與 `gitfetch.validRef` 一樣：**這是真正把它交給 execve 的那一層**。

### 4.3 情境包要說有什麼可用

`render_run_context()`（`runs.py:829`）加一段：

```markdown
## 這次執行可用的環境變數

- `GITHUB_TOKEN`
- `NPM_TOKEN`

它們已經在你的環境裡，**不要把值印出來**——平台會把它們替換成 `***`，
但編碼過的值可能漏網。
```

**只列名稱。** 這一段的存在理由與情境包第一段（怎麼回報）相同：
最可能出錯的不是 Agent 不會用，是 Agent 不知道有。
**「不要印出來」那一句要在**，因為去識別是盡力而為而不是保證（§4.5）。

### 4.4 ambient 憑證的隔離（D9）

> **前提：這一整節只在「這次 run 真的收到了平台的 git 憑證」時執行。**
> 沒有收到時（＝ `CLIORA_GIT_SECRET_DELIVERY_ENABLED=false` 的預設組態）
> **一行都不跑**，`HOME`／`GIT_CONFIG_GLOBAL`／`XDG_CONFIG_HOME` 保持不變，
> ambient 憑證原樣可用——行為與 V2.2 逐位元組相同。
>
> 判斷的依據是 `len(secrets.git) > 0`，**不是設定值**：
> 設定值答的是「有平台憑證時要不要藏起 ambient」，
> 而「有沒有平台憑證」是每一次 run 各自的事實。把兩者合成一個布林
> 就是 2026-08-13 之後最容易做錯的那一格（`README` 易錯 4）。

選 A（預設）時，run 子程序的環境加三個覆寫：

```
HOME=<run>/​.cliora/home
GIT_CONFIG_GLOBAL=<run>/.cliora/home/.gitconfig      # 一份空的最小設定
XDG_CONFIG_HOME=<run>/.cliora/home/.config
```

目錄 0700，run 結束隨目錄一起回收。

**要誠實寫在 ADR 與 release note 的兩句**：

- 這**不是沙箱**。run 子程序與 agentd 同一個 OS 使用者，`/home/agentd` 底下的東西
  它讀得到——A 買到的是「git 的預設路徑上看不到那些憑證」，不是「不可能用」。
- 配合 D5，**在旗標開啟且選 A 的組態下，Agent 連平台的憑證也拿不到**，
  所以 2026-08-10 ② 給的 git 自由在那個組態下實際上被收掉了。
  ⚠️ **但那不是預設組態**（2026-08-13 裁決）：預設路徑上機器的憑證還在、
  也沒有被藏起來，**Agent 的 git 自由完整保留**。

### 4.5 去識別（D6）

```go
type Redactor struct{ values []string }   // 依長度由長到短排序

func (r *Redactor) String(s string) string
func (r *Redactor) Payload(p map[string]any) map[string]any  // 遞迴走字串值
```

**掛在 `send` 閉包上**（`run_handlers.go:198`），所以
`run.log_chunk`、`run.progress.message`、`run.failed.message`、`run.complete.summary`
四條路徑一次涵蓋。

四個性質：

1. **由長到短排序**：一枚機密是另一枚的前綴時，先換長的，否則短的會把長的切碎成
   `***<剩下的一段>`——那一段仍然是機密的一部分。
2. **短值不替換**：長度 < 8 的值跳過並在 daemon 啟動時 warn。
   一個值為 `1` 的機密會把每一個數字 1 都換成 `***`，
   而那讓 log 完全不可讀，換來的保護是零。
3. **只做原值比對**，並在 ADR 誠實記錄：**base64／URL-encode 之後的值會漏網**。
   真正的保證來自「機密可撤銷」與「log 有保留期」，不是來自這個函式。
4. **M-SC-2 決定它走多深**：若 benchmark 顯示遞迴走整個 payload 讓終端延遲 p95
   超過基線 20%，改為只對 `data`／`message`／`summary` 三個已知欄位做。
   **那是一個退路而不是預設**——預設是走全部，因為「哪些欄位是自由文字」
   會隨著 contract 成長而改變，而漏掉一個的症狀是機密外洩。

**一條測試**：把機密的值放進 `run.failed` 的 message（模擬 git stderr 帶 token），
斷言 Central 收到的是 `***`。**這條測試比 log 那條重要**，
因為 log 那條是大家會記得寫的。

### 4.6 `run.progress` 的一個新 phase

`fetching` 之後、`checked_out` 之前加一個 `authenticating`，
讓「卡在憑證上」與「卡在網路上」在 Run 詳情頁上分得開。
（V2.2 的 phase enum 在 `run-progress.schema.json`，加一個值是 additive。）

## 5. 測試

`daemon/internal/runner/secrets_test.go`：

1. `kind` 分流：`env` 出現在子程序的 `Env`，`git_pat` **不出現**（D5 的機器形式）。
2. `Redactor` 的長短排序（一枚是另一枚的前綴）。
3. 短值不替換，且啟動時有 warn。
4. `Payload` 遞迴：巢狀 map 與陣列裡的字串都被換掉。
5. **run 結束後 run 目錄全域搜尋不含任何機密值**（`GATE-SC-NO-SECRET-TO-DISK` 的執行期版本）。
6. `accept_secrets: false` 的 node 收到帶 `secrets` 的 offer → **decline 並說明**
   （不該發生，但 daemon 是最後防線）。
7. 危險名稱（`PATH`）被跳過並記一行 log。
8. `HOME`／`GIT_CONFIG_GLOBAL` 在 A 模式下指向 run 目錄，在 B 模式下不變。
9. 🆕 **`secrets.git` 為空時（＝預設組態）三個環境變數完全未被改寫**，
   即使 `isolate_ambient_credentials` 是 `true`（§4.4 的前提，出口條件 11c）。

`backend/tests/test_offer_frame_size.py`：§2.3 的那一條。
