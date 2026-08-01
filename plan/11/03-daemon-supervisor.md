# 03 — Daemon 端：本機否決、host key 與子行程監管（PG-05、PG-06）

> 需求變更（2026-08-01）：憑證改由平台保管並隨 `tunnel.open` 下發（`00-…md` D4／D18），
> 因此本檔**移除** node config 的 `token` 欄位，`tunnel:` 區塊縮成「本機否決與收窄」，
> 並新增「憑證只在記憶體」的處理規則（§2.1a）。

## PG-05：本機否決設定、host key 釘選與 `doctor`

### 1.1 設定

`daemon/internal/config/config.go` 新增（沿用既有 `FilesystemConfig`／`TunnelConfig` 風格的註解密度）：

```go
// TunnelConfig is this node's *veto and narrowing* over the platform's port
// forwarding settings (P11, ADR 0022). The platform decides whether the
// integration exists at all and holds the provider credential; this file decides
// whether THIS machine participates and, if so, within which bounds. Every field
// here can only make the platform's settings narrower, never wider (ADR 0022 D17).
//
// There is deliberately no token field: the credential is held by the platform
// and arrives with each tunnel.open, so it never touches this machine's disk.
type TunnelConfig struct {
    // Enabled false is an absolute veto that the platform cannot override.
    // Absent → true: this node already grants the platform a shell runtime
    // (ADR 0021), so requiring a second per-machine edit to forward a port is
    // form, not substance. The veto exists for machines that need it.
    Enabled *bool `yaml:"enabled"`
    // AllowedPorts narrows the platform's list. Empty → no extra narrowing.
    // Ports below 1024 are refused regardless of what any layer says.
    AllowedPorts []string `yaml:"allowed_ports"`
    // MaxTunnels narrows the platform's budget. Zero → no extra narrowing.
    MaxTunnels int `yaml:"max_tunnels"`
    // KnownHostsPath pins the provider's SSH host keys. Empty → the packaged
    // default (/etc/agentd/pinggy_known_hosts). Host key checking is never
    // disabled; see ADR 0022 and PG-01 for where these keys came from.
    KnownHostsPath string `yaml:"known_hosts_path"`
}
```

`Enabled` 是 `*bool` 而不是 `bool`：需要分辨「沒寫」（＝不否決）與「明確寫 false」（＝否決）。零值型別在這裡會讓「沒寫」變成否決，而那會使每一台既有 node 在升級後都無法參與 —— 症狀是平台上每台機器都顯示「已在本機停用」，而沒有人記得自己停用過。

| 決定 | 選擇 | 理由 |
|---|---|---|
| 預設值 | **不否決**（`enabled` 缺項＝true） | 主閘門在平台（`00-…md` D3）：整合要由 Admin 啟用並提供憑證，per-node 參與也在平台的頁面上關得掉。node 本機的角色是**否決權**，不是第二道啟用開關。理由是這台機器已經授予平台 `shell` runtime（ADR 0021 預設啟用），再要求逐台編輯設定檔才能轉 port 是形式上的安全 |
| 否決不可被覆寫 | `enabled: false` 之後，任何來自 Central 的 `tunnel.open` 一律回 `TUNNEL_NODE_DISABLED` | D17。這一條要有測試，且測試名稱要說得出「平台不能覆寫本機否決」 |
| 沒有 `token` 欄位 | 憑證由平台保管（D4／D18） | 少一份磁碟上的秘密。**若 `Load` 讀到一個 `token:` 鍵，要以警告忽略而非報錯**：升級路徑上可能有人手動寫過（本計畫初版曾這樣設計），報錯會讓 daemon 起不來 |
| 沒有 `provider` 欄位 | provider 由平台整合設定決定 | node 不需要知道用哪一家；它只是被告知「用這個憑證連這個 host」。**host 也由平台在 `tunnel.open` 中給？不 —— host 由 daemon 依 provider 常數決定**，否則 Central 就能指定任意 SSH 目的地（`00-…md` §7 的同一條理由） |
| `MaxTunnels` 預設 | 0（不額外收窄） | 上限由平台的 `concurrent_budget` 與 per-node 設定決定；node 只在有理由時才收得更緊 |
| `MarshalConfig` 的註解 | `tunnel` 區塊上方掛註解：這是什麼、**預設不否決**、啟用後流量會經過第三方、如何否決、為何憑證不在這個檔案裡、為何不能停用 host key 檢查 | 沿用 plan/08 補齊的教訓：決定所需的資訊必須寫在他會打開的那個檔案裡。**特別是「憑證不在這裡」**：不寫的話，node 擁有者會找一個不存在的欄位 |

`daemon/internal/install/plan.go` 產生的初始設定要寫出 `tunnel: {enabled: true}` 並帶上述註解 —— 明確的值比缺少區塊好，後者會讓人以為這個 daemon 版本不支援。

### 1.2 host key 釘選

- `deploy/pinggy_known_hosts` 由 `PG-01` 產生，installer 佈署到 `/etc/agentd/pinggy_known_hosts`（0644，非機密）。
- 每次啟動子行程時固定帶：`-o StrictHostKeyChecking=yes -o UserKnownHostsFile=<path> -o GlobalKnownHostsFile=/dev/null -o IdentitiesOnly=yes`。
- 檔案不存在或為空 → **不啟動子行程**，回 `TUNNEL_PROVIDER_UNTRUSTED`；不 fallback 成不驗證。
- `GlobalKnownHostsFile=/dev/null` 是為了讓系統層的 `known_hosts`（可能被別人寫過）無法影響判定 —— 我們要的是「只信這一份」。
- host key 輪替是一件**會發生**的事：runbook 要寫「如何更新這個檔案、如何確認新指紋、更新期間的症狀是所有隧道回 `_UNTRUSTED`」（`06-…md` §4.3）。

### 1.3 `agentd doctor` 四項檢查

| 檢查 | 內容 | 失敗時的訊息 |
|---|---|---|
| `ssh` 用戶端 | `exec.LookPath("ssh")` ＋ `ssh -V` | 「找不到 ssh 用戶端，請安裝 openssh-client」 |
| 對外連線 | `net.DialTimeout("tcp", "<provider host>:443", 5s)` | 「無法連線到 <host>:443，請確認防火牆或代理設定」 |
| host key | 檔案存在、非空、可被 `ssh-keygen -l -f` 解析 | 「主機金鑰檔缺失或無法解析，請重新安裝或依 runbook 更新」 |
| 本機否決 | `tunnel.enabled` 是否為 false | 「此 Node 已在本機停用埠轉發（`/etc/agentd/config.yaml` 的 `tunnel.enabled: false`）」 |

**沒有「憑證」這一項** —— node 不再持有憑證（D18），所以 `doctor` 也無從回答。這一點要寫在 `doctor` 的輸出說明裡，否則使用者會以為漏檢查了。

`doctor` 的輸出**不得包含任何憑證字元**（它沒有機會拿到）**，也不得包含 allowed_ports 以外的設定內容**。前三項的結果同時經 heartbeat 回報給 Central（`02-…md` §2.4），因此 UI 與 `doctor` 給出的答案必然一致。

### 1.4 驗收

- Go 單元測試：`enabled` 缺項＝不否決、`enabled: false` 為絕對否決（收到 `tunnel.open` 回 `TUNNEL_NODE_DISABLED` 且不啟動子行程）、遺留的 `token:` 鍵被警告忽略而非導致啟動失敗、`allowed_ports` 只能收窄（給一個比平台更寬的清單，斷言有效集合沒有變寬）、`known_hosts` 缺失時拒絕啟動且不呼叫 dialer（fake supervisor 斷言啟動次數 0）。
- `doctor` 四項各一例（含「輸出不含任何憑證字元」與「本機否決會被明確報告」）。
- `MarshalConfig` 的註解位置有測試（沿用 plan/08 的 `KnownFields(true)` 往回讀的手法）。

---

## PG-06：`ssh` 子行程監管、URL 解析、重連與孤兒回收

新增 `daemon/internal/tunnel/`：`provider.go`（interface）、`pinggy.go`（命令組裝與 URL 解析）、`supervisor.go`（生命週期）。

### 2.1a 憑證的處理（需求變更後新增）

憑證隨每一次 `tunnel.open` 抵達（`00-…md` D18）。daemon 對它只有四條規則：

| 規則 | 具體做法 |
|---|---|
| **不落地** | 只存在解碼後的 payload struct、`Provider.Start` 的參數、以及子行程的 argv。**不寫檔、不寫環境變數、不進 pid 檔** |
| **不記錄** | 任何錯誤路徑（含 `safeErr`、退出分類、debug log）都不得輸出 argv 全文。`ssh` 的命令列若需記錄，一律以 `<credential>` 佔位取代 —— 這要有一個測試斷言 log 中不含該值 |
| **再驗一次字元集** | schema 已限制 `^[A-Za-z0-9]{8,128}$`（`02-…md` §1.2），daemon 不得依賴上游驗證。**這是防止 `+`／`@` 改寫 SSH 目的地的第二層** |
| **provider host 由 daemon 決定** | `tunnel.open` 只帶憑證，不帶 host。`credential` 非空 → `pro.pinggy.io`；為空 → `free.pinggy.io`。**Central 不得指定 SSH 目的地**，否則協定就多了一個「叫 node 連到任意主機」的能力 |

在記憶體中持有的時間等於隧道的生命週期（`ssh` 行程活著就需要它重連）。這是刻意的：把它丟掉就無法在免費版 60 分鐘後自行重連，而那會讓每小時都要 Central 重新下一次 `tunnel.open`。**代價寫在安全審查**：daemon 的記憶體與子行程 argv 中有一份憑證，同 uid 的行程讀得到。

### 2.1 命令組裝

```
ssh -p 443
    -o BatchMode=yes                        # 實測可行：認證方式 none，無密碼提示
    -o StrictHostKeyChecking=yes
    -o UserKnownHostsFile=/etc/agentd/pinggy_known_hosts
    -o GlobalKnownHostsFile=/dev/null
    -o IdentitiesOnly=yes
    -o ExitOnForwardFailure=yes             # 轉發失敗就退出，不要留一條沒有轉發的連線
    -o ServerAliveInterval=60                # 官方建議
    -o ServerAliveCountMax=3
    -R 0:localhost:<port>
    <token>@pro.pinggy.io | http@free.pinggy.io
    x:https x:xff [b:user:pass | w:ip,ip] [u:Host:localhost:<port>]
```

**絕不出現的兩個旗標**：`-N`（會讓 remote options 無法傳遞）與 `-t`／`-tt`（會得到 ANSI TUI）。兩者都由 `PG-01` 實測確認，且都要有測試守門。

| 決定 | 理由 |
|---|---|
| 參數以 **`[]string` 逐項組裝**，永不經過 shell | 沒有 `sh -c`，就沒有 shell injection 面。`b:user:pass` 的內容來自 Central，即使 schema 已擋 `:`，也不該讓它有機會被 shell 解讀 |
| **不加 `-N`，不加 `-t`／`-tt`** | 兩件事都由 `PG-01` 實測確認：(a) remote options 是以「遠端命令」的形式傳遞，所以不能用 `-N`；(b) **一旦要求 PTY，服務端會渲染一個全螢幕 ANSI TUI**（實測 15 秒產生 19 KB 逃脫序列），URL 完全無法解析。無 PTY 時 stdout 是四行乾淨文字。因此**禁止使用 `creack/pty`**，這一條要有測試守門 |
| `ExitOnForwardFailure=yes` | 沒有它，一條「連上了但沒有轉發」的 SSH 會看起來是成功的，而使用者拿到的 URL 永遠 502 |
| `+force` 是否加 | 依 `PG-01` #8。若同 token 只能一條，`+force` 會踢掉別人的隧道 —— 那時**不加**，改為在 API 層以 `max_tunnels=1` 拒絕，讓使用者知道有人在用 |
| token 傳遞 | 只出現在 `argv` 的 user@host 欄位。**不寫入環境變數**（`/proc/<pid>/environ` 與 `argv` 都可被同 uid 讀取，兩者風險相當，但 argv 是 provider 的既定介面）。這一點要在 ADR 的「能力缺口」中誠實列出：同一台機器上同 uid 的行程可以讀到 token |

### 2.2 生命週期

```
Start(port, opts) → 組命令 → 啟動 → 等待 URL（timeout 15s）→ 回報 tunnel.opened
                                 │
                    子行程退出 ──┴─→ 分類（見 §2.4）
                                      ├ 可重試 → backoff 重連 → 取得新 URL → tunnel.status{url}
                                      └ 不可重試 → tunnel.status{state: failed, error_code}
Stop() → 送 SIGTERM 給行程群組 → 2s 後 SIGKILL → tunnel.closed
TTL 到期 → 同 Stop()，reason = "expired"
```

| 規則 | 值 | 理由 |
|---|---|---|
| 取得 URL 的等待上限 | 15s（Central 側 20s，`02-…md` §2.4） | 兩層留 5s 餘裕，讓 Central 的逾時**永遠**晚於 daemon 的，否則使用者會看到「逾時」而 node 上其實成功了 |
| 重連 backoff | 沿用 `connection.go:35-37` 的表（1/2/5/10/30s）＋ jitter | 不要為同一件事寫第二套退避 |
| 重連上限 | 連續 10 次失敗 → `state: failed`，停止重試 | 免費版每小時一次正常重連，10 次連續失敗代表環境壞了而不是時限到了。無上限的重連會在 provider 停止服務時對它連續打一整晚 |
| 行程群組 | `SysProcAttr{Setpgid: true}`，kill 整個群組 | `ssh` 可能有子行程（`ProxyCommand` 等）；只殺父行程會留孤兒 |
| daemon 關閉 | 所有隧道一併 Stop，並等待行程真的結束 | 見 §2.5 |

### 2.3 URL 解析

- **URL 在 stdout**（實測）；stderr 只有 OpenSSH 自己的警告與 `Allocated port N for remote forward`。兩者都讀，但 URL 只從 stdout 取。
- 實測到的 stdout 形狀（免費、未認證）：
  ```
  You are not authenticated.
  Your tunnel will expire in 60 minutes. Upgrade to Pinggy Pro … https://dashboard.pinggy.io
  https://<slug>-<公網IP>.run.pinggy-free.link
  https://<slug>-<公網IP>.free.pinggy.net
  ```
  **第 2 行也含一個 https URL**（`dashboard.pinggy.io`），所以「抓第一個 https」是錯的 —— 必須用後綴白名單過濾。
- 只接受 `https://` 開頭、且 host 後綴落在**編譯期常數清單**：`.run.pinggy-free.link`、`.free.pinggy.net`（實測到的兩個），Pro 的固定子網域後綴待 `PG-01` #7 補上。`dashboard.pinggy.io` **不在清單內**，因此不會被誤取。
- 拒絕的情況：`http://`、host 不在清單、長度 >2048、含控制字元。**這是外部輸入進入平台的唯一入口，必須當成不可信輸入處理**（`02-…md` §1.2 的 `url` pattern 是第二層）。
- 掃到多個 URL（Pinggy 會同時印 http 與 https 兩行）→ 取 https 那一個，忽略 http。
- **子行程的輸出不進 log 原文**：只記「已取得 URL」「未在 15 秒內取得 URL」與分類後的錯誤碼。原文只在 `agentd` 的 debug 等級下寫入本地 log，且**永不上傳**（provider 的輸出可能回顯 token 或 basic auth 憑證）。

### 2.4 退出分類

| 觀察到的 | 分類 | 上報的碼 |
|---|---|---|
| stderr 含 `Host key verification failed.`（實測：錯的釘選 key 與空的 known_hosts 皆為 `exit 255` + 這一句） | 不可重試 | `TUNNEL_PROVIDER_UNTRUSTED` |
| **憑證無效** —— 實測**不會**失敗：服務靜默降級為匿名免費隧道並照樣給網址。判定方式是**送了 `credential` 卻在 stdout 收到 `You are not authenticated.`** | 不可重試，**且必須主動中止已建立的隧道** | `TUNNEL_PROVIDER_UNAUTHORIZED` |
| 連線被拒 / DNS 失敗 / 逾時 | 可重試 | `TUNNEL_PROVIDER_UNAVAILABLE` |
| 正常退出（免費版時限） | 可重試 | 不上報錯誤，重連後送 `tunnel.status{url}` |
| `ExitOnForwardFailure` 觸發 | 可重試一次，之後不可重試 | `TUNNEL_PROVIDER_UNAVAILABLE` |

**為什麼「降級」必須被當成失敗**：使用者在整合設定裡填了 Pro token，期待的是固定子網域與無時限；靜默降級給他的是一條 60 分鐘、網址內嵌公網 IP 的匿名隧道。讓它「看起來成功」比失敗更糟 —— 所以 daemon 收到降級橫幅時要 `tunnel.abort` 自己的隧道並回報 `_UNAUTHORIZED`。（`plan_tier=free` 且本來就沒送憑證時，同一條橫幅是正常的，不算錯誤。）

**依賴 stdout／stderr 字串比對是一個明確的脆弱點**：provider 改一句話，分類就退化成「不可用」。因此 (a) 每個比對規則都要有 `PG-01` 記錄的原文作為出處；(b) 分類失敗時的預設是**可重試但計入上限**，不是無限重試；(c) runbook 要寫「若所有錯誤都變成 `_UNAVAILABLE`，先看 provider 是否改了訊息」。

### 2.5 孤兒回收

daemon 重啟後，前一代的 `ssh` 行程會繼續活著並繼續對外服務 —— 這是本期最容易被漏掉的問題，因為它不會有任何錯誤訊息。

- 每條隧道在 `/run/agentd/tunnels/<tunnel_id>.pid` 寫入 pid 與啟動時間（`/run` 是 tmpfs，重開機自動清空）。
- daemon 啟動時掃該目錄：pid 仍存在且 cmdline 符合預期（含 `-R 0:localhost:` 與 provider host）→ **殺掉**。理由：Central 是權威，重連後會重新下 `tunnel.open`；留著一條 Central 不知道的隧道，等於一個沒人管的對外入口。
- cmdline 不符 → 只刪 pid 檔，不殺（避免 pid 重用殺到無關行程）。
- 這一項要有 integration 測試：起一條、`kill -9` daemon、重啟、斷言 `ssh` 行程已不存在。

### 2.6 測試策略：fake provider

真實 Pinggy 只出現在 `PG-01` 與 `PG-14` 的 staging leg。單元／integration 測試一律用 fake：

- `internal/tunnel/testdata/fake-provider.sh`（或一個小 Go binary）：印出一行假的 https URL、視參數模擬「60 秒後退出」「立刻 host key 失敗」「不印 URL」三種行為。
- `Provider` interface 讓 supervisor 接受注入的命令路徑，測試時指向 fake。
- 這樣 CI 不需要網路、不需要帳號，也不會因為 provider 的狀態而變紅。**一個依賴第三方可用性的 CI，紅燈會失去意義。**

### 2.7 Metrics

`daemon_tunnel_start_total{result}`、`daemon_tunnel_reconnect_total{reason}`、`daemon_tunnel_active`（gauge）、`daemon_tunnel_url_changed_total`。**label 不含 port、URL、token、tunnel_id。**

### 2.8 驗收

- Go 單元測試（fake provider）：成功取得 URL、15 秒未取得 URL、URL 形狀被拒（http／未知網域／過長）、三種退出分類、backoff 與 10 次上限、`Stop` 後行程確實消失、TTL 到期。
- 注入測試：`b:user:pass` 的密碼含 `:` 時 daemon **自己也拒絕**（不依賴上游 schema）；參數陣列中不存在 shell metacharacter 被解讀的路徑。
- integration（`make integration` 新增 `./internal/tunnel`）：孤兒回收、真實 `ssh` 對本機 fake SSH 伺服器（或直接對 fake provider script）的端到端。
- `go test -race ./...` 全綠。
