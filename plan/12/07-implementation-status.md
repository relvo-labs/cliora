# 07 — 實作進度與證據

本檔隨實作更新；「證據」欄只填**實際跑過的指令與其輸出位置**，不填計畫中的測試。

最後更新 2026-08-01：**`PV-01`–`PV-11` 全部完成並落地。`make check` 全綠；
`scripts/pv/evidence.sh` 13 道 gate 執行、0 失敗、1 筆誠實的 skip（瀏覽器 e2e 需要 stack）。**

> ### 下一輪從這裡接手
>
> **功能面已可交付。** 三件事都在程式碼裡，不是計畫裡：codex 帶固定旗標啟動、
> 終端機可捲動、系統終端機可 sudo（新裝節點預設開啟）。
>
> **唯一還沒關的事：** `docs/security-review-p12.md` §5 最後一個核可項 ——
> §2「已接受的風險」需要**使用者本人**確認，因為那份清單建立在使用者自己的前提
> （可丟棄 VM）上，不是工程可以自己簽掉的東西。
>
> **這台機器上跑不了的一件事：** `frontend/tests/e2e/session.spec.ts` 的捲動斷言需要
> 一個有 online node 的 stack（`scripts/e2e/run-stack.sh`）。spec 已寫好、
> `p2.yml` 會跑整個 `tests/e2e` 目錄，所以 CI 會跑到它。evidence pack 會偵測
> 「Playwright 自己 skip」並記成 skip 而不是 exit=0 的 pass —— 這一點特意處理過，
> 因為 Playwright 對 skipped test 回 0。
>
> **環境事實：**
>
> | 事實 | 值 |
> |---|---|
> | 工具鏈不在預設 PATH 上 | `export PATH="$HOME/.local/bin:/usr/local/go/bin:$HOME/.nvm/versions/node/v22.23.2/bin:$PATH"` |
> | `codex` 在 `$HOME/.local/bin`（不在系統 PATH） | `command -v codex` 在乾淨 shell 下會失敗，但 node 的 config 指的是絕對路徑，所以 daemon 找得到 |
> | Postgres 可用 | `postgresql+asyncpg://cliora:cliora@127.0.0.1:5432/cliora_test`，已 `alembic upgrade head` 到 `0017` |
> | `make test-db` 要同時設兩個變數 | `CLIORA_TEST_DATABASE_URL` **與** `CLIORA_DATABASE_URL` |
> | 這台機器本身裝了 agentd（0.4.x，非本次 build） | `agentd doctor` 跑的是舊 binary，因此不會顯示本期新增的姿態行 |
> | 預設 socket 上有 1 個殘留的 `cliora-*` session | 正是 D5b 描述的情況，`node-posture-check.sh` 會報出來 |

## `PV-01` 實測結果（原始輸出：[`08-measurements.md`](08-measurements.md)）

| # | 量測 | 結果 | 對決策的影響 |
|---|---|---|---|
| 1 | codex 版本與旗標 | `codex-cli 0.146.0`；`--help` 列出 `--dangerously-bypass-approvals-and-sandbox` | 旗標存在，D1 的表可以照寫 |
| 2 | 旗標與 `--version` 偵測 | `codex --dangerously-… --version` → `codex-cli 0.146.0`，exit 0 | 不影響既有 `Detect`（`runtime.go` 用 `--version`） |
| 4 | **tmux 如何解讀多參數 shell-command** | **直接 execvp，不經 shell**（多參數形式下 `'$HOME'` 保持字面；單一字串形式會被展開成 `/home/ubuntu`）；live argv 為 `/bin/sleep 30` | **D4 的結論反過來了**：`flagPattern` 檢查是多一層保險而非必要條件，未來含空白的參數也會是安全的。檢查仍保留（成本為零，且讓參數清單可一眼檢視），但註解已改成誠實的說法 |
| 5 | `-f` 與 `history-limit` | 預設 socket = **2000**；`-f` 帶入的 50000 生效；`new-session` 之後才設**無效** | `FR-TERM-004.AC-04` 在本期之前不成立；conf 檔是唯一修法 |
| 6 | `mouse on` 的 escape sequence | 預設送 `1000l/1002l/1006l`（關閉）；`mouse on` 送 `1002h/1006h`（開啟）；attach 一律先送 `1049h`（alt screen） | ② 的根因與修法 |
| — | `set-option -t <s> mouse on` 對既有 session | **有效** | 升級路徑的救援（`03-…md` §2.4） |
| 9 | `NoNewPrivileges` 下的 sudo | `sudo: The "no new privileges" flag is set, which prevents sudo from running as root.` | runbook §4 第一種失敗模式的原文 |

未在本機取得的兩項：`#3`（codex 在 tmux 內的 live argv —— 需要一次真的 codex session）與
`#10`（`PrivateTmp=true` 下的 sudo —— 需要 systemd 環境）。兩者都由
`GATE-PV-NODE-POSTURE`（release-triggered）在真實 node 上補上，且 `node-posture-check.sh`
已經會印出 `codex argv (live)` 這一行。

## 決策紀錄

| # | 決策 | 狀態 | 決定者／日期 | 備註 |
|---|---|---|---|---|
| D-0 | 節點是可丟棄的隔離 VM，node 內的破壞為已接受成本 | ✅ 已決定 | 使用者／2026-08-01 | 寫入 ADR 0023 Context |
| D-1 | codex 預設帶 `--dangerously-bypass-approvals-and-sandbox` | ✅ **已落地** | 使用者／2026-08-01 | `daemon/internal/runtime/launch.go`；node 以 `sandbox_bypass` 否決 |
| D-2 | 系統終端機開放 sudo（非 root＋sudoers NOPASSWD） | ✅ **已落地** | 使用者／2026-08-01 | unit＋`/etc/sudoers.d/60-agentd`；`agentd posture` 為既有節點的升級路徑 |
| D-3 | 終端機捲動修正（tmux `mouse on`＋專用 socket） | ✅ **已落地** | 使用者／2026-08-01 | `daemon/internal/tmux/conf.go` |
| D-4 | ADR 0023 核准 | ✅ **已撰寫並合併** | 使用者／2026-08-01（指示實作） | 同時修訂 ADR 0021 §4.2 第 2 條 |
| D-5 | 切 tmux socket 會結束升級當次的既有 session | ✅ **已採用**（接受該代價） | — | 不自動 kill、只記 WARN 與 `doctor`；release note 第一段就講 |
| D-6 | 不新增 `terminal.privileged` RBAC action | ✅ 已採用 | — | 理由與重開條件見 ADR 0023 Consequences |
| D-7 | 不引入 OSC 52 剪貼簿 | ✅ 已採用 | — | `PV-01` #8 未在本機驗（需瀏覽器）；補償措施是終端機下方的提示文字 |
| D-8 | `sandbox_bypass` 與 `privileged_terminal` 為兩個獨立開關 | ✅ 已採用 | — | `04-…md` §3；release note 明講「關掉 sudo 不會關掉沙箱旗標」 |

## Ticket 進度

| Ticket | 標題 | 狀態 | 證據 |
|---|---|---|---|
| `PV-01` | 行為實測 | ✅ | `plan/12/08-measurements.md`、`artifacts/pv/local/node-posture.txt`（後者 gitignore，重跑：`scripts/pv/node-posture-check.sh`） |
| `PV-02` | ADR 0023、PRD 修訂、traceability | ✅ | `docs/adr/0023-…md`、ADR 0021 末段修訂、PRD 九條 AC、`make traceability` 綠 |
| `PV-03` | 啟動參數表與 codex 無沙箱 | ✅ | `runtime/launch.go`、`launch_test.go`（8 例）、`config/posture_test.go` |
| `PV-04` | tmux 環境自有化與捲動 | ✅ | `tmux/conf.go`、`conf_test.go`（7 例）、`session/scrollback_integration_test.go`（真 tmux：history_limit=7000、mouse=on、status=off、不在預設 socket 上） |
| `PV-05` | 特權終端（unit／sudoers／posture／doctor） | ✅ | `install/sudoers.go`、`sudoers_test.go`（8 例）、`systemd_posture_test.go`、`cmd/agentd/posture.go` |
| `PV-06` | 契約 v1.7.0 | ✅ | 兩個欄位、2 valid＋4 invalid fixture、三語言 `make contract` 綠 |
| `PV-07` | Central（migration 0017、回報、稽核） | ✅ | `0017_node_privileged_posture.py`、`test_node_ws.py` 新增 5 例、`make test-db` 317 綠 |
| `PV-08` | 前端姿態標示與操作提示 | ✅ | `NodeDetailView.vue`、`SessionWorkspaceView.vue`、`NodeDetailPosture.test.ts`（5 例）、e2e 捲動 spec |
| `PV-09` | `.agent/skills` 修訂 | ✅ | `cliora-project-context`、`go-daemon-development` 各一段；未新增 skill（README／RELATIONSHIPS 不變） |
| `PV-10` | evidence／gates／runbook／release note | ✅ | `scripts/pv/{evidence,check-no-argv-channel,node-posture-check}.sh`、兩個 gate、runbook＋release note |
| `PV-11` | 安全審查與 exit gate | ⚠️ **一項待使用者確認** | `docs/security-review-p12.md`；§5 最後一項需使用者確認已接受的風險清單 |

## 與計畫的差異（實作過程中改掉的東西）

| 計畫原文 | 實際 | 為什麼 |
|---|---|---|
| `02-…md` §1.5：`Args` 驗證是為了「tmux 可能經過 shell」 | 保留驗證，但註解改成「兩種解讀下結果相同」 | `PV-01` #4 實測是 execvp。留著空話比留著檢查糟 |
| `06-…md` §1：12 道 gate | 13 道（拆出 `daemon:launch-table` 與 `daemon:sudoers-and-unit` 兩個具名 leg） | 這兩組是本期的核心斷言，值得在 `commands.txt` 上有自己的一行 |
| `06-…md` §2：`FR-TERM-004.AC-04` 只需回填 links | 另外改了 `scripts/traceability/tests/test_traceability.py` 的釘住數字（274 → 283）並寫下理由 | 那個數字本來就是「每次變動都要被 review」的設計 |
| `01-…md` §4：`SEC-007.AC-02` 為 `manual`、`FR-TERM-004.AC-06` 為 `manual` | 改為 `inspection` 與 `measurement` | registry schema 的 `verification_profile` 詞彙沒有 `manual`，只有 `automated`／`measurement`／`inspection`／`manual_external` |
| 計畫未提 | `agentd` 版本升到 **0.5.0** | 使用者要求；`daemon/VERSION` 與 `main.go` 同步，`TestVersionMatchesTheVersionFile` 守住 |
| 計畫未提 | 修正 `install/plan.go` 兩段 config 註解 | 它們寫著「agentd 必須不以 root 執行**所以**這是天花板」，在特權姿態下只剩一半正確。既有測試斷言了那句話，所以測試的期望字串也一併改了（`install_test.go`） |
| 計畫未提 | `docs/runbooks/system-terminal.md` 新增一節 | 其中「daemon 以 root 執行是嚴重發現」在本期之後需要區分「執行身分」與「可提權」 |
| 計畫未提 | `metrics.allowedLabels` 加入 `sandbox` | 新的 metric 標籤會 panic（allowlist 是 fail-closed 的）。**只有 integration tag 的測試會踩到**，unit 全綠 —— 這是本期唯一一個被測試抓到的實作 bug |
| 計畫未提 | evidence pack 會把 Playwright 的 skip 記成 skip | Playwright 對 skipped test 回 exit 0，照抄會變成一個看起來通過的 gate —— 正是這個 pack 自己 header 在防的事 |

## 已知缺口（誠實列出，不是待辦）

1. **瀏覽器捲動斷言未在本機執行過。** spec 已寫，CI 會跑；本機以 `PV-01` #6 的 escape
   sequence 實測＋xterm.js 原始碼核對支撐。
2. **codex 在 tmux 內的 live argv 未在本機取得**（需要一次真的 codex session）。
   `node-posture-check.sh` 會印，`GATE-PV-NODE-POSTURE` 在 release 時取。
3. **`PrivateTmp=true` 下的 sudo 未驗**（需要 systemd）。若真的衝突，處置是在 unit 移除該行
   並記進 runbook；目前沒有理由預期衝突。
4. **旗標支援的探測每個 daemon process 只做一次。** codex 升級後要重啟 daemon 才會反映。
   已寫進 runbook §3 與安全審查 §3.2 的 residual gap。
