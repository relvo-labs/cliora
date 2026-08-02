# 01 — 實測閘門與規範修訂（PV-01、PV-02）

## 1. `PV-01` 行為實測

一次姿態變更不能建立在「應該是這樣」上面。以下十項要在一台真實的 node（可丟棄 VM）上跑過，
輸出存到 `artifacts/pv/measure/`，並把結論回填 `07-…md` 的決策紀錄。

| # | 量測 | 方法 | 為什麼非測不可 |
|---|---|---|---|
| 1 | codex 版本與旗標存在 | `codex --version`；`codex --help \| grep -c dangerously-bypass-approvals-and-sandbox` | 旗標名稱是第三方 CLI 的介面。**D3 的整個設計（回報實況而非設定）建立在「它可能不存在」上面** |
| 2 | 旗標與 `--version` 偵測不衝突 | `codex --dangerously-bypass-approvals-and-sandbox --version` | 既有 `Detect` 用 `--version` 判可用性（`runtime.go:93`）。若旗標讓 `--version` 改變行為或要求 TTY，偵測會誤判成 `RUNTIME_NOT_EXECUTABLE` |
| 3 | 旗標在非 TTY 與 tmux 內都被接受 | 直接跑一次；再 `tmux new-session -d … codex --dangerously-…` 後 `ps -o args=` | 有些 CLI 對 root／非 TTY／無 git repo 另有拒絕條件。要看到的是**行程活著且 argv 正確** |
| 4 | **tmux 如何解讀多個 `shell-command` 參數** | `tmux -L m new-session -d -s a /bin/echo one two`；再測 `… /bin/echo 'one two'`；用 `ps -o args=` 與 `capture-pane` 對照 | D4：決定參數表未來能不能放含空白的值。若 tmux 會把多參數 join 後交給 shell，則參數表**永久**只能是 shell-safe token，且要有測試釘住這個限制 |
| 5 | `-f` 與 `history-limit` 的生效條件 | 已於 2026-08-01 實測：`tmux -L probe2 -f conf new-session …` → `#{history_limit}` = 50000；預設 socket = **2000** | 已知結論，但要在目標 node 的 tmux 版本上重跑一次（3.2a 與 3.4 的選項名稱有差異風險） |
| 6 | `mouse on` 的 escape sequence | 已於 2026-08-01 實測：預設 → `ESC[?1000l/1002l/1006l`（關閉）；`mouse on` → `ESC[?1002h ESC[?1006h`（開啟） | 這是 ② 的根因與修法的**同一份證據**。目標 node 上重跑，存 raw bytes |
| 7 | 瀏覽器端的實際捲動 | 起一個 shell session，`seq 1 5000`，用滑鼠滾輪往上；再在 bash 裡確認**沒有**翻出歷史命令 | 前六項都是 node 端。使用者的抱怨在瀏覽器端，所以驗收也必須在瀏覽器端 |
| 8 | Shift＋拖曳選取仍可用 | 同一個 session，Shift＋拖曳後 `Ctrl/Cmd+C`，貼到別處 | D7 的補償措施。若它其實不成立，D7 要改成「引入 OSC 52」而不是「寫在提示裡」 |
| 9 | sudo × `NoNewPrivileges` | 在 `NoNewPrivileges=true` 的 unit 下於系統終端機執行 `sudo -n true`（**預期失敗，記下確切訊息**）；移除該行 `daemon-reload` 重啟後再測（預期 `uid=0`） | D8 的因果要有證據。那句失敗訊息也是 runbook 的內容 —— 使用者遇到時要能對得上 |
| 10 | sudo × `PrivateTmp=true` | 保留 `PrivateTmp=true`，跑 `sudo -n id`、`sudo -n apt-get -s install curl` | `PrivateTmp` 保留是本期的預設。若它與 sudo 或套件管理有衝突，要在這裡發現，而不是在使用者第一次裝東西時 |

**不需要量測的**：xterm.js 的兩個分支（`!buffer.hasScrollback` 轉方向鍵、`shouldForceSelection` 取 `shiftKey`）
已於 2026-08-01 在 `frontend/node_modules/@xterm/xterm/lib/xterm.js`（5.5.0）核對過原始碼；
版本已鎖在 `package.json`，升級時才需重驗。

## 2. `PV-02` ADR 0023

檔名 `docs/adr/0023-privileged-node-posture.md`。狀態 accepted，日期依實際核准日。
`Related`：ADR 0004（終端內容不落地）、ADR 0011（installer／unit）、ADR 0013（session 生命週期）、
ADR 0021（系統終端機）、ADR 0017（update／healthcheck 的身分假設）。
`Plan`：`plan/12/`。

必須寫進去的八項，少一項就不是這一期的 ADR：

### 2.1 Context 要先講前提，不是先講功能

「node 是可丟棄的隔離 VM，損毀的處置是重建」是本期所有取捨的**前提**（`00-…md` D0）。
它要寫在 Context 而不是 Decision，因為它不是我們決定的事 —— 它是使用者對其部署形狀的陳述，
而 ADR 的工作是把它記下來並指出**當它不成立時什麼會改變**。

### 2.2 三個變更是一件事

ADR 不寫成三節平行的功能敘述，而要寫成一句話：**這一期把 node 的執行姿態從
「非 root、有沙箱、不可提權」改成「非 root、無沙箱、可提權」**，並列出三個變更各自對應姿態的哪一半。
理由：分成三個獨立小改動來看，每一個都像是可接受的便利性調整；合起來看才是姿態變更。

### 2.3 明確標示 ADR 0021 §4.2 的補償控制已被改寫

ADR 0021 §4.2 第 2 條寫：「**非 root daemon。** 系統終端機不提升任何權限；它把 daemon 已有的權限
變成互動介面。daemon 的執行身分**就是**這個功能的天花板。若這一點變成 root，本 ADR 的風險等級改變並須重審。」

本期的處理必須明說：**執行身分沒有變成 root，但天花板變成了 root**（一個 `sudo` 之遙）。
因此該條補償控制在事實上已不再成立，ADR 0023 要：

1. 在 ADR 0021 檔案末尾加一段 `Amendment (由 ADR 0023 取代第 4.2.2 條)` 的交叉連結；
2. 在 ADR 0023 列出**剩下還成立的補償控制**：擁有權（他人不得連線他人的系統終端機）、
   有界生命週期、session 級稽核 —— 以及本期新增的兩項：**姿態可見**（D10）與 **OS 端 sudo 紀錄**（§2.5）。

### 2.4 `SCOPE-011` 這次沒有再被削

要明寫：本期**沒有**動 `session.start` 的封閉性，前端與 Central 仍不得命名命令、binary、argv、環境或
entrypoint；codex 的旗標來自 daemon 內的常數表。並指出這件事**測得到**：
`backend/tests/test_scope_guards.py` 擴充一個「`session.start` 不得出現 `args`／`flags`／`sandbox`」的斷言，
加上三個 golden invalid fixture（`05-…md` §1.3）。

ADR 0021 §Context 的教訓在這裡要被引用：上一次加 `shell` 到 enum 時，守門測試是綠的、覆蓋率沒變、
release gate 沒動 —— 看 CI 的人會以為它被審過。本期的旗標表同樣不會讓任何既有測試變紅，
所以同樣必須靠這份文件而不是 CI。

### 2.5 sudo 的紀錄界線

- 平台**不**記錄終端輸入輸出（ADR 0004、`TECH-SEC-08`），本期不改。
- 但 sudo 會在 node 的 `/var/log/auth.log`（或 journald）留下「哪個使用者在什麼時間以 root 執行了什麼」。
- 這**不是**平台的稽核來源：平台看不到它、不收集它、也不因它而放寬任何隱私承諾。
- 它的意義只有一個：當有人事後要調查一台 node 上發生過什麼，**它是唯一存在的東西**。
  ADR 要把這句話寫出來，包括它的兩個限制 ——「VM 重建即消失」（D0 的直接後果）與
  「它記的是 sudo 命令，不是終端內容」。

### 2.6 為什麼不是 root、不是白名單

`00-…md` D8／D9 的「被否決」原文照抄進 ADR。理由不能只留在計畫目錄裡：計畫會被歸檔，
ADR 是下一個人問「為什麼不乾脆跑 root」時會找到的地方。

### 2.7 捲動與 scrollback 的雙軌

- tmux history 是使用者實際看得到的 scrollback；
- reattach 的 2 MiB snapshot 落在 xterm.js 的正常 buffer，被 alt buffer 蓋住，**看不到**；
- 兩者都保留，理由分別是「捲動」與「重連連續性」；
- 這是既有實作的既有事實，本期只是把它寫下來（D6b）。

沒有這一節，下一個處理 scrollback 問題的人會先去改 snapshot 大小 —— 那是一條走不通的路，
而它走起來很像對的。

### 2.8 Consequences

- 契約 **v1.7.0**（compatible）：兩個選用欄位，`node` 表兩個布林欄。
- **升級即取得新姿態**（`sandbox_bypass` 與 `privileged_terminal` 的預設都是啟用）：與 ADR 0021 的
  `shell` 預設啟用相同的處理 —— release note ＋ runbook，不得靜默。
- **升級會結束既有 session**（D5b 切 socket）。這是 ADR 0004 的復原承諾在本期的一次性例外，要明寫。
- `tmux` 環境從此由 daemon 擁有：node 擁有者的個人 tmux 不再被 cliora 影響，反之亦然。
- 行為變更：終端機內拖曳選取改為 tmux 的選取；瀏覽器原生選取需 Shift＋拖曳。

## 3. PRD 修訂（`research/prd.md`）

每一條都要有 `<a id="…">` 錨點，並同步 `traceability/requirements.json`（§4）。

| 需求 | 修訂 | 內容 |
|---|---|---|
| `SEC-007 執行使用者` | **AC-01 不變**（「Daemon 不應預設以 root 長期執行」仍有效，仍由 `EnsureNonRoot` 測試守住） | — |
| | **新增 `SEC-007.AC-02`** | 安裝時須明確提示：該 Node 的系統終端機**可經 sudo 取得 root 權限**；此姿態可於安裝時關閉。 |
| | **新增 `SEC-007.AC-03`** | Node 的提權姿態須回報平台並於介面顯示；平台不得以任何 API 或訊息改變之。 |
| `FR-SHELL-001 系統終端機` | **新增 `AC-09`** | 系統終端機可提權時，介面須明示該 Node 的提權姿態。 |
| `FR-TERM-004 Terminal Scrollback` | **AC-04 不變**（「至少保存 5000 行」）——但它**現在才第一次成立**（`06-…md` §2） | — |
| | **新增 `AC-06`** | 使用者須能於瀏覽器中向上檢視終端機的既有輸出，並可回到即時輸出。 |
| | **新增 `AC-07`** | 重連快照為連續性機制，不作為使用者檢視歷史輸出的途徑。 |
| `FR-RUNTIME-*`（見 §3.1） | **新增一條 AC** | Runtime 的啟動參數由 Node 端固定決定，不得由前端、Central 或協定訊息指定；Node 僅能以布林開關既定參數集。 |
| | **新增一條 AC** | codex Runtime 於 Node 上預設在停用沙箱與核准流程下執行；Node 可關閉此預設；實際狀態須回報平台並顯示。 |
| `SCOPE-011` | **不修訂**，但在該條下方加一行註記 | 指向 ADR 0023 §2.4：本期未再削減本條；存活的那半條仍被測試守住。 |

### 3.1 `FR-RUNTIME-*` 的落點要先查

`daemon/internal/runtime/runtime.go:2` 的註解引用 `FR-RUNTIME-001/003/004`，但**修訂前必須先
`rg -n "FR-RUNTIME" research/prd.md` 確認每一條的實際標題與現有 AC 編號**，把兩條新 AC 掛在
語意最接近的那一條下（很可能是講「Runtime 啟動」的那條），而不是新開一個需求 id。
`.agent/skills/cliora-project-context` 的第 3 步就是這件事：先用 `rg` 找錨點，再讀範圍。
若兩條新 AC 在既有需求下都無處可掛，才新增 `FR-RUNTIME-00x`，並在 `07-…md` 記下這個決定。

## 4. traceability 註冊

`traceability/requirements.json`（`schema_version` 不變）：

- 新增／修改的 AC 各自加一筆 `criteria`，格式沿用既有條目：`id`、`source_anchor`、
  `verification_profile`、`risk`。
- 風險等級建議：`SEC-007.AC-02`／`AC-03` 與 codex 沙箱那條 **high**（姿態變更且對外可見），
  `FR-TERM-004.AC-06`／`AC-07` **medium**。
- `verification_profile`：能自動測的（旗標組裝、`history_limit`、DTO 欄位、UI 標示、scope guard）填 `automated`；
  「瀏覽器裡滾輪真的捲動了」與「sudo 真的回 uid=0」屬於 `manual`／`assisted`，
  **不要為了讓數字好看而填 `automated`** —— `06-…md` §3 會把它們列成有輸出的手動證據。
- `traceability/links.json`：把每個 AC 連到實作檔案與測試（`scripts/trace validate --level static` 會檢查）。
- 若某條 AC 在本期收尾時仍無自動化覆蓋，走 `traceability/waivers.json` 的正規流程並寫理由，
  **不得**留下無連結的 AC（`GATE-TRACE-STATIC` 會紅）。

## 5. 核准要求

`PV-02` 的產出（ADR 0023、PRD 修訂 diff）要由使用者核准後才動 daemon 程式碼。
核准要記在 `07-…md` 的決策紀錄表，含日期與決定者 —— 本期的三個變更每一個都是
「事後很難說清楚是誰決定的」那一類，而 ADR 0021 §Context 已經示範過一次代價。
