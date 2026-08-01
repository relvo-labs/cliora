# 00 — 執行總控（特權節點姿態）

## 1. 成功定義

**要交付的：** 一台升級後的 node 上，(1) `codex` session 預設在無沙箱、無核准流程下啟動；
(2) 瀏覽器裡的終端機可以用滑鼠滾輪往上看到先前的輸出；(3) 系統終端機裡 `sudo` 可用。
三者的**實際狀態**都被 daemon 回報、被平台儲存、被 UI 顯示，並可由稽核回答「誰在什麼姿態的機器上開了什麼」。

**不得弄壞的四件事：**

1. **前端與 Central 都不得命名命令。** `session.start` 維持五個欄位與 `additionalProperties:false`；
   啟動參數只能來自 daemon 內的固定表（D1）。這是 `SCOPE-011` 在 ADR 0021 §1 之後存活的那半條，
   本期**不再削一次**。
2. **daemon 仍以非 root 執行。** `config.EnsureNonRoot()`（`daemon/internal/config/credentials.go:53`）
   維持在 `run` 與 `doctor` 的第一步。提權是終端機使用者按下 `sudo` 時才發生的事，不是服務的執行身分（D8）。
3. **終端內容不落地。** ADR 0004 與 `TECH-SEC-08` 不變：平台不記錄終端輸入輸出。sudo 在
   `/var/log/auth.log` 留下的紀錄是**作業系統**的，不是平台的，界線寫進 ADR 0023（`01-…md` §2.5）。
4. **既有 session 生命週期語意。** CLI session 在瀏覽器離線後存活（`FR-SESSION-006`）、
   系統終端機相反（ADR 0021 §6）。本期只改「怎麼啟動」與「怎麼捲動」，不動「什麼時候死」。

成功的判準是這九項，每一項都要有可貼上的輸出（`06-…md` §3）：

1. `runtime: codex` 的 session 起來後，node 上 `ps -o args=` 看到
   `codex --dangerously-bypass-approvals-and-sandbox`；UI 的 session 標頭顯示「沙箱：已停用」。
2. 同一台 node 設 `runtime.codex.sandbox_bypass: false` 並重啟後，行程**沒有**該旗標，UI 顯示「沙箱：啟用」。
   設定、daemon 回報、UI 三處說的是同一件事。
3. 新增的 golden invalid fixture（`session.start` 夾帶 `args`）被 Python／Go／TypeScript **一致拒絕**；
   `backend/tests/test_scope_guards.py` 擴充後仍綠。
4. 瀏覽器裡滾輪往上可看到先前輸出；在 bash session 裡往上滾**不再**翻出歷史命令（這是現況的症狀）；
   滾到底自動回到即時輸出。
5. `tmux -L cliora display-message -p '#{history_limit}'` ≥ 5000，且值來自 `session.scrollback_limit`。
6. cliora 的 session 位於專用 socket：node 擁有者 `tmux ls` 看不到 `cliora-*`，其個人 tmux 的
   `mouse`／`status` 選項未被改動。
7. 系統終端機裡 `sudo -n id` 回 `uid=0`；同時 `systemctl show -p User agentd` 與 `ps -o user= -p $(pidof agentd)`
   都是那個非 root 使用者。
8. `agentd doctor` 對本期三件事各有明確一行（沙箱旗標支援、tmux 環境、sudo 可用性），
   且任一項失敗時的訊息說得出「要改哪個檔案」。
9. Node 詳情頁與 Session 工作區各自顯示姿態標示；`session.create` 稽核 metadata 含
   `sandbox`（`bypassed`／`enforced`）與 `privileged`（`true`／`false`）。

## 2. 範圍

### 納入

- `PV-01` 行為實測（codex 旗標、tmux argv 傳遞、sudo 在 unit 兩種設定下的差異）、`PV-02` ADR 0023 與 PRD 修訂。
- daemon：啟動參數表與 `sandbox_bypass`（`PV-03`）；專用 tmux socket、自有 `tmux.conf`、
  `scrollback_limit` 接線、既有 session 的遷移處理（`PV-04`）；特權終端的 unit／sudoers／installer 旗標／`doctor`（`PV-05`）。
- 契約 v1.7.0（compatible）：`runtime-item.sandbox_bypass` 與 `node-register.privileged_terminal`
  兩個附加欄位，加三個 golden invalid fixture（`PV-06`）。
- Central：migration 0017（`nodes` 兩個布林欄）、register／runtime_status 落地、Nodes API DTO、
  `session.create` 稽核 metadata（`PV-07`）。
- 前端：Node 詳情與 Session 工作區的姿態標示、終端機的滾動／選取提示、新建 session 對話框的 codex 說明（`PV-08`）。
- `.agent/skills` 更新：`cliora-project-context` 與 `go-daemon-development` 各一段不變量修訂（`PV-09`）。
- evidence／gates／runbook／release note（`PV-10`）、安全審查與 exit gate（`PV-11`）。

### 不納入

- **新的 RBAC action（例如 `terminal.privileged`）。** 見 D12。
- **sudo 命令白名單。** 見 D9 的「被否決」。
- **記錄終端輸入或 sudo 命令到平台。** ADR 0004／`TECH-SEC-08` 不變；本期只在 ADR 裡把
  OS 端 `auth.log` 的存在與界線寫清楚。
- **OSC 52 剪貼簿（`@xterm/addon-clipboard`）。** 選用票 `PV-08b`，本期**不做**（D7）。
- **移除 reattach 的 2 MiB snapshot。** 它與 `session.attached.continuity` 及 `FR-TERM-004.AC-05` 綁在一起，
  本期只把「使用者實際看得到的 scrollback 是 tmux history」寫成明文（D6b）。
- **把 `shell` 以外的 runtime 也交給 tmux copy-mode 之外的捲動機制**（例如前端自製捲動模式）。見 D6 的「被否決」。
- **per-user 或 per-session 的沙箱／提權開關。** 姿態是 node 級的（D11）。

## 3. 固定基線決策

| # | 決策 | 選擇 | 理由 |
|---|---|---|---|
| D0 | **前提：節點是可丟棄的隔離 VM** | 明文寫進 ADR 0023 的 Context：node 為一次性 VM，損毀的處置是重建而非復原；因此本期把「節點內的破壞」從風險清單移到**已接受的成本**，而把「跨節點與跨租戶的影響」留在風險清單上 | 使用者 2026-08-01 的指示是「已做 VM 隔離、壞掉就再做一個」。把它寫成前提有兩個作用：三個變更不必各自發明一套緩解措施；而**當前提不成立時（有人把 agentd 裝在會被心疼的機器上）有一個可以指出的地方**。前提不成立時的安裝方式是 `--no-privileged-terminal` 與 `sandbox_bypass: false` |
| D1 | codex 的旗標從哪裡來 | **daemon 內的固定參數表**（`runtime` 套件的常數），node 只能用**一個布林** `runtime.codex.sandbox_bypass` 開關它 | `RuntimeConfig` 沒有 argv 欄位是刻意的設計（`config.go:172` 註解），`session.start` 的封閉性是 ADR 0021 §1 明列「存活的那半條」。**被否決**：`runtime.codex.args: [...]` 自由字串陣列 —— 它把 argv 的決定權搬到設定檔，而下一步「讓 Admin 在 UI 上填」會顯得只是搬個位置；而且 `SCOPE-011.AC-01` 的守門測試只看 wire，抓不到這種漂移 |
| D2 | 預設值方向 | **預設帶旗標（bypass）**；`sandbox_bypass` 缺項＝`true`，僅對 `codex` 有意義 | 使用者明確指示「預設要帶」。缺項即啟用與 ADR 0021 對 `shell` 的處理一致（`applyRuntimeDefaults`），代價同樣是**升級即取得新姿態**，所以同樣必須有 release note 與 runbook（`06-…md` §4），不得靜默 |
| D3 | 旗標不被支援時怎麼辦 | **回報實況，不靜默**：`Detect` 額外探測一次旗標是否被該版 codex 接受，`runtime-item.sandbox_bypass` 回報的是「設定要求 **且** 實測支援」的合成結果；不支援時 session 仍可啟動（不帶旗標），但 `doctor` 出 `[warn]`、UI 顯示「沙箱：啟用」 | 兩種偷懶都不行：**依設定樂觀回報**會讓 UI 說謊（使用者以為沒有沙箱，實際上有，於是把 codex 的失敗歸因錯地方）；**旗標不支援就拒絕啟動**會讓一次 codex 升級把整個車隊的 codex session 打掉。旗標名稱是第三方 CLI 的介面，會改名 |
| D4 | 參數如何進到 tmux | `tmux.StartSpec` 新增 `Args []string`，展開為 `new-session … <binary> <args…>` 的獨立 argv 元素 | `PV-01` 要實測 tmux 3.2a 對多個 `shell-command` 參數是直接 `execvp` 還是先交給 shell 拼字串。本期的參數只含 `-` 與英數，兩種行為的結果都正確；但**行為要被記下來**，因為它決定了未來能不能放含空白的參數（結論若是「經過 shell」，則參數表永久只能是 shell-safe 的 token，並以測試釘住） |
| D5 | tmux 環境的所有權 | **專用 socket `-L cliora` ＋ daemon 自有的 `/run/agentd/tmux.conf`（`-f`，由 unit 的 `RuntimeDirectory=agentd` 建立；實作時從 `/etc` 改到 `/run`，因為它是每次啟動依 `scrollback_limit` 重新產生的執行期狀態，不是給人編輯的設定）** | 今天 production 用預設 socket（`connection.go:101` 的 `ctmux.Client{}`），也就是**與 node 擁有者自己的 tmux server 共用**；在那裡設 `mouse on`／`status off`／`history-limit` 會改掉別人的環境，而這正是會被抱怨的那種改動。**實測**：`-f` 只在 server 啟動時生效，且 `history-limit` 必須在 pane 建立前就位（`#{history_limit}` 才會是 50000）。**被否決**：在共用 socket 上 `set -g`；`new-session` 之後 `set-option -t`（對已建立的 pane 的 history 無效） |
| D5b | 切 socket 的代價 | **升級當次，既有的 `cliora-*` session 不會被接回**（它們留在舊 socket 上，`has-session` 找不到）。處置：daemon 啟動時對預設 socket 掃一次 `cliora-*`，把發現寫成一行 `WARN` 並在 `doctor` 顯示；**不自動搬移**（tmux 無法跨 server 搬 session），不自動 kill | tmux 的 session 綁在 server 上，這個代價無法規避，只能選擇「說出來」或「靜默」。舊 session 變成 orphan 而 UI 顯示 `exited`，如果沒有這行 WARN，看起來會像本期弄壞了 session 復原（ADR 0004）。runbook 要寫「如何手動收掉舊 socket 上的殘留」 |
| D6 | 捲動的實作路徑 | **tmux 端 `mouse on` ＋ `history-limit`；xterm.js 一行程式都不改** | 根因已實測（`README.md` §「兩項已量測的事實」）：alt buffer 沒有 scrollback，且 tmux 主動關閉滑鼠回報，於是 xterm.js 把滾輪轉成方向鍵。`mouse on` 讓 tmux 送 `1002h/1006h`，xterm.js 改為轉送 SGR 事件，滾輪進 copy-mode；而 claude／codex 這類自己啟用滑鼠追蹤的 TUI，tmux 會把事件轉給它們，因此它們的內建捲動也能用。**被否決**：`terminal-overrides ',*:smcup@:rmcup@'`（讓 tmux 不用 alt screen、改吃 xterm.js 的 scrollback）—— 對全螢幕 TUI，每次重繪都會把整頁垃圾灌進 scrollback；**被否決**：前端自製「捲動模式」按鈕送 copy-mode 按鍵 —— 用 500 行前端程式重做 tmux 已經有的東西 |
| D6b | 誰是 scrollback 的正本 | **tmux 的 history 是使用者實際看得到的 scrollback**；reattach 的 2 MiB snapshot 保留但被明文降級為「重連瞬間的連續性證據」 | 實測：`tmux attach` 立刻送 `ESC[?1049h`，snapshot 落在 xterm.js 的**正常 buffer**、隨即被 alt buffer 蓋住，使用者看不到。這是既有實作的事實，本期不動它（動 `continuity` 語意與 `FR-TERM-004.AC-05` 超出範圍），但**必須寫進 PRD 與 ADR**，否則下一個人會以為 snapshot 是捲動的來源而在錯的地方找問題 |
| D7 | 選取與複製的取捨 | 開 `mouse on` 之後拖曳選取被 tmux 接手；**瀏覽器原生選取改為 Shift＋拖曳**（已核對 xterm 5.5.0：`shouldForceSelection` 取 `shiftKey`）。UI 必須寫出這句話。**不引入 OSC 52 剪貼簿**（選用票 `PV-08b`） | 這是本期唯一一個使用者會感覺到的**退步**，所以它要被寫在使用者看得到的地方，而不是只寫在計畫裡。順帶一個容易被誤解的細節：Shift＋滾輪**不會捲動**（xterm.js 的 `getLinesScrolled` 遇 `shiftKey` 回 0），提示文字不能寫成「按 Shift 捲動」。OSC 52 延後的理由：它讓遠端內容可以寫入使用者的系統剪貼簿，是一個新的攻擊面，值得單獨評估而不是搭這一期的車 |
| D8 | sudo 的形狀 | **非 root 但可提權**：unit 移除 `NoNewPrivileges=true`，加 `/etc/sudoers.d/60-agentd`（`<user> ALL=(ALL) NOPASSWD:ALL`）；`EnsureNonRoot()` 保留 | 三個理由，缺一不可：(a) `NoNewPrivileges=true` 下 sudo **必定失敗**（setuid 被禁），所以那一行就是真正的阻擋點，不移除則其他都是白做；(b) 走 sudo 而不是把服務改成 root，`/var/log/auth.log` 會留下每一次提權 —— 在 ADR 0021 §5「不記錄終端輸入」的前提下，這是**唯一還取得到**的特權操作紀錄；(c) 檔案擁有權、update healthcheck 以服務使用者跑 `doctor` 的身分假設全部不變。**被否決**：`User=root`（一次廢掉 `EnsureNonRoot`、healthcheck 的身分語意、workspace 檔案擁有權，且 ADR 0021 §4.2 的整段論述要重寫而不是修訂） |
| D9 | 為什麼是 `NOPASSWD:ALL` | 服務使用者通常沒有密碼可輸；而 codex 在無沙箱模式下會自己執行 `sudo apt-get …`，一個互動式密碼提示會讓它**卡住到 timeout**，症狀是「codex 沒反應」而不是「codex 沒有權限」 | **被否決**：命令白名單。使用者要的是「開放 sudo」，而在一個能執行任意命令的 shell 裡，白名單只有兩種結局 —— `sudo bash` 在名單上（等於全開，但多一份會過期的清單），或不在名單上（使用者第一次裝套件就撞牆，然後手動改成全開，而那次修改沒有人審）。誠實的全開比裝飾性的白名單好 |
| D10 | 姿態必須在產品裡看得見 | Node 詳情、Session 工作區、新建 session 對話框三處顯示；`session.create` 稽核 metadata 加兩個鍵 | ADR 0021 §4.2 把「daemon 非 root」列為系統終端機的**補償控制第 2 條**，並寫下「若這一點變成 root，本 ADR 的風險等級改變並須重審」。本期沒有把它變成 root，但把它變成了「一個 `sudo` 之遙」—— 這在效果上就是該條所預告的情況。既然補償控制被拿掉了一半，能給使用者的就只剩「知道自己在什麼邊界裡」，那它就必須是一等公民而不是一行 tooltip |
| D11 | 姿態的粒度 | **node 級**（`nodes.privileged_terminal`、`node_runtimes.sandbox_bypass`），不做 per-user／per-session | 兩者都由機器上的檔案（unit、sudoers、config.yaml）決定，平台無法在單一 session 上讓 sudo 失效 —— 一個 per-session 的開關會是**假的**。可回報、可顯示、可稽核，但不可由平台調整 |
| D12 | RBAC | **不變**：不新增 `terminal.privileged` action | `terminal.shell` 已由 Admin＋Developer 持有，而系統終端機的天花板本來就是服務使用者的全部權限。新增一個 action 只能決定「誰能開終端」，不能決定「終端裡能不能 sudo」—— 後者在 shell 裡就是那顆按鈕。**重開條件**：若未來出現「同一台 node 上要區分可提權與不可提權的使用者」的需求，正確做法是兩台 node（兩種姿態），而不是一個擋不住的 action |
| D13 | 契約 | **v1.7.0（compatible）**，只加兩個選用欄位：`runtime-item.sandbox_bypass`、`node-register.privileged_terminal`。**不新增任何可讓 Central 指定 argv、旗標、sudo 命令或 tmux 選項的欄位** | 沿用 1.4.0／1.6.0 的既有作法：新增能力時只讓 node **回報**，不讓 Central **指定**（`daemon.update` 只有版本號、`tunnel.open` 沒有 host 欄位）。三個 golden invalid fixture 把這件事釘住（`05-…md` §1.3） |
| D14 | 這一期不碰的東西 | edge nginx、CSP、relay、single-writer、ws-ticket、RBAC、檔案系統中繼、tunnel | 判準：若 diff 動到 `deploy/nginx/`、`backend/app/api/ws/`、`backend/app/security/rbac.py` 的權限表，就是走錯路了。唯一的例外是 `sessions.py` 的稽核 metadata（D10 要求） |

## 4. 波次與 ticket

| 波次 | Ticket | 標題 | 依賴 |
|---|---|---|---|
| **0（閘門）** | `PV-01` | 行為實測：codex 旗標、tmux argv 傳遞、sudo × unit 設定、tmux 選項效果 | — |
| | `PV-02` | ADR 0023、PRD 修訂（SEC-007／FR-SHELL-001／FR-TERM-004／SCOPE-011 註記）、traceability 註冊 | `PV-01` |
| **1（daemon）** | `PV-03` | 啟動參數表、`runtime.codex.sandbox_bypass`、旗標支援偵測、`doctor` | `PV-02` 核准 |
| | `PV-04` | 專用 tmux socket、`/run/agentd/tmux.conf`、`scrollback_limit` 接線、舊 socket 掃描 | `PV-02` 核准 |
| | `PV-05` | systemd unit、sudoers drop-in（含 `visudo -cf`）、installer 旗標、`doctor` | `PV-02` 核准 |
| **2（契約與 Central）** | `PV-06` | 契約 v1.7.0：兩個欄位、三個 invalid fixture、三個 consumer | `PV-03`、`PV-05` |
| | `PV-07` | migration 0017、register／runtime_status 落地、Nodes API DTO、稽核 metadata | `PV-06` |
| **3（介面與規範）** | `PV-08` | 姿態標示（Node 詳情、Session 工作區、新建對話框）、終端操作提示 | `PV-07` |
| | `PV-09` | `.agent/skills` 兩份 SKILL.md 的不變量修訂 | `PV-02` 核准 |
| **4（驗證與收尾）** | `PV-10` | evidence script、gates 註冊、runbook、release note | `PV-03`–`PV-08` |
| | `PV-11` | 安全審查（`docs/security-review-p12.md`）、exit gate | `PV-10` |

`PV-01` 與 `PV-02` 是**閘門**：`PV-01` 的實測結果會改寫 D3／D4 的細節，`PV-02` 未核准前不得動 daemon 程式碼
（本期是一次姿態變更，書面決定必須先於實作 —— 這是 ADR 0021 §Context「它不是被審查的，是在這裡被公開決定的」的同一條規矩）。

## 5. 風險

| 風險 | 徵狀 | 處置 |
|---|---|---|
| codex 旗標改名或行為改變 | 升級 codex 後 session 起來但仍有沙箱，或直接拒絕啟動 | D3 的實測回報＋`doctor` warn；旗標常數集中在一個檔案一個地方；`PV-01` 記下版本 |
| 切 socket 讓既有 session 消失 | 升級後使用者的 session 全部變 `exited` | D5b：WARN＋`doctor`＋runbook；release note 明寫「升級會結束既有 session」 |
| sudoers 寫壞 | 整台機器 sudo 失效，且修復需要 sudo | `visudo -cf` 先驗、0440、原子 rename；installer 失敗時**不留下**半個檔案（`04-…md` §2.2） |
| `mouse on` 讓使用者無法複製文字 | 「以前可以選取，現在選不到」 | D7：UI 明寫 Shift＋拖曳；release note 列為行為變更 |
| copy-mode 沒有視覺回饋（`status off`） | 使用者往上滾之後打字沒反應 | tmux 預設 wheel 綁定帶 `-e`（滾到底自動離開 copy-mode）；UI 提示寫出「按 q 回到即時輸出」；`03-…md` §2.3 |
| 「可丟棄 VM」前提不成立的機器 | 有人把 agentd 裝在共用開發機上 | D0：安裝時的明示提示＋`--no-privileged-terminal`；Node 詳情的姿態標示讓管理者事後也看得出來 |
