# 06 — 驗證、證據與 exit 條件（PV-10、PV-11）

## 1. `PV-10` evidence pack

`scripts/pv/evidence.sh`（沿用 `scripts/pg/evidence.sh` 的形狀：每一道 gate **實際執行**、
狀態寫進 `commands.txt`、跑不了的寫進 `skipped.txt`，**不得靜默省略** ——
「少了一道 gate 的 pack 讀起來跟通過那道 gate 的 pack 一模一樣」）。

輸出預設 `artifacts/pv/local/`。gate 清單：

| # | gate | 命令 | 這一環境跑不動時 |
|---|---|---|---|
| 1 | 契約 schema × 三語言 | `make contract` | 不可 skip |
| 2 | daemon 單元＋race | `go test ./... && go test -race ./internal/session/... ./internal/tmux/... ./internal/runtime/...` | 無 Go → skip 並記 |
| 3 | daemon 參數表守門 | `go test ./internal/runtime -run 'TestLaunchArgs\|TestResolveLaunch'` | 同上 |
| 4 | sudoers／unit 渲染 | `go test ./internal/install -run 'TestUnit\|TestSudoers\|TestPosture'` | 同上 |
| 5 | scope guard | `uv run --project backend pytest backend/tests/test_scope_guards.py -q` | 不可 skip |
| 6 | Central DB 測試 | `make test-db`（需 `CLIORA_TEST_DATABASE_URL` **與** `CLIORA_DATABASE_URL`，見 `plan/11/07-…md` 的環境事實） | 無 DB → skip 並記 |
| 7 | 前端單元 | `npm --prefix frontend run test:unit` | — |
| 8 | 前端 e2e（含捲動斷言） | `npm --prefix frontend run test:e2e` | 缺 Playwright 系統函式庫 → skip，並以 §3 的手動證據補 |
| 9 | traceability | `make traceability` | 不可 skip |
| 10 | **grep gate：沒有人偷偷開 argv 通道** | `scripts/pv/check-no-argv-channel.sh` | 不可 skip |
| 11 | **grep gate：`NoNewPrivileges` 的兩種姿態都存在於程式碼** | 同一個腳本的第二段 | 不可 skip |
| 12 | node 端實測（tmux 選項與 sudo） | `scripts/pv/node-posture-check.sh` | 非 node 機器 → skip |

### 1.1 `scripts/pv/check-no-argv-channel.sh`

三段 grep，任一命中即失敗：

1. `contracts/v1/schemas/` 內出現 `"args"`／`"argv"`／`"command"`／`"flags"`／`"env"`／`"sudo"` 屬性名；
2. `daemon/internal/config/` 內出現 `yaml:"args"`／`yaml:"argv"`／`yaml:"flags"`；
3. `backend/app/` 內把請求欄位傳進 `session.start` payload 的鍵超出既有五個。

這道 gate 的目的不是抓惡意，是抓**善意的漂移**：下一個需求會是「能不能讓使用者加一個 `--model` 參數」，
而最短的實作路徑正好是加一個欄位。ADR 0021 §Context 已經記過一次「CI 全綠但沒有人審過」的事。

### 1.2 `scripts/pv/node-posture-check.sh`

在一台真實 node 上跑，輸出可貼進 `07-…md`：

```text
tmux socket           : cliora
tmux history_limit    : 5000       (期望 ≥5000)
tmux mouse            : on
tmux status           : off
legacy default socket : 0 cliora-* session(s)
NoNewPrivs            : 0
sudo -n true          : 0 (available)
agentd euid           : 1000 (non-root)  ← 必須非 0
codex sandbox flag    : supported
codex argv            : codex --dangerously-bypass-approvals-and-sandbox
```

最後三行是本期的三個交付各自的**單一決定性事實**。`agentd euid` 那一行的位置刻意放在
sudo 之後：這兩行放在一起才能表達「可提權但不是 root」。

## 2. 既有需求的補償：`FR-TERM-004.AC-04`

本期把一條**目前不成立**的 AC 修正為成立（tmux 預設 `history-limit` 實測 2000 < 需求 5000，
且 `session.scrollback_limit` 從未被讀取）。處理方式：

1. `traceability/links.json` 把 `FR-TERM-004.AC-04` 連到 `PV-04` 的實作與整合測試；
2. 若該 AC 目前在 `baseline-debt.json` 或以 `automated` 標記但實際無覆蓋，
   在 `07-…md` 寫明「本期之前它是綠的但不成立」—— 這是一個**追溯性資訊缺陷**，
   比一個新 bug 更值得記，因為它說明覆蓋率數字曾經騙過我們一次；
3. 不追加懲罰性流程。plan/06 的治理機制已經存在，本期只是照它走一次。

## 3. 手動證據（必須有輸出，不可只有勾選）

| # | 項目 | 要留下什麼 |
|---|---|---|
| M1 | 瀏覽器滾輪捲動 | 螢幕錄影或三張截圖（滾動前／滾動後看到早期輸出／滾回底部回到即時輸出）；在 bash session 上做，並確認 prompt 沒有被歷史命令替換 |
| M2 | Shift＋拖曳選取 | 截圖＋貼上的結果 |
| M3 | `sudo -n id` 於系統終端機 | 終端截圖含 `uid=0(root)`，同畫面另一行 `systemctl show -p User agentd` |
| M4 | codex argv | `ps -o args= -C codex` 的輸出 |
| M5 | 關閉姿態後的對照 | `sandbox_bypass: false` ＋ `agentd posture --privileged-terminal=false` 後重跑 M3／M4，兩者都翻轉，且 UI 標示跟著翻轉 |

M5 是唯一能證明「開關真的是開關」的證據。**只驗開啟不驗關閉**是本期最容易漏的一項，
因為開啟才是預設，關閉沒有人會用 —— 直到有人真的需要它時發現它不管用。

## 4. runbook 與 release note

### 4.1 `docs/runbooks/privileged-node-posture.md`（新）

必須回答的六個問題：

1. **這台 node 是什麼姿態？** → `agentd posture`（唯讀）／Node 詳情頁。
2. **怎麼關掉 sudo？** → `agentd posture --privileged-terminal=false`（會重啟服務）。
3. **怎麼關掉 codex 的無沙箱？** → 改 `runtime.codex.sandbox_bypass: false` ＋重啟；
   為什麼要重啟（偵測只在啟動／重連時做）。
4. **sudo 沒作用怎麼查？** → `NoNewPrivs` 為 1（unit 沒改到／被覆寫）；drop-in 權限不是 0440
   （sudo 會整份忽略，且沒有錯誤訊息）；`PV-01` #9 記下的那句失敗訊息。
5. **升級後既有 session 不見了？** → D5b：切 socket 的一次性代價；如何在舊 socket 上收拾殘留
   （`tmux ls` ＋ `tmux kill-session -t cliora-…`），以及為什麼不自動做。
6. **改了 `scrollback_limit` 但沒生效？** → tmux server 的生命期長於 daemon；需結束所有 session。

### 4.2 `docs/runbooks/system-terminal.md`（既有，需更新）

加一節「特權姿態」，並修正其中任何「daemon 非 root 因此終端機不能提權」的敘述 ——
那句話在本期之後是錯的，而它出現在一份會被照著做的文件裡。

### 4.3 `docs/release-note-privileged-posture.md`（新）

四個行為變更，每一項都要有「使用者會看到什麼」：

| 變更 | 使用者會看到 |
|---|---|
| codex 預設無沙箱 | codex 不再詢問核准；Session 標頭出現「沙箱：已停用」 |
| 系統終端機可 sudo | `sudo` 直接可用（無密碼）；Node 詳情出現「可提權」 |
| 終端機可捲動 | 滾輪可看歷史；**拖曳選取改為 Shift＋拖曳**（這一項是退步，要單獨列） |
| 升級會結束既有 session | 一次性；原因與收拾方式指向 runbook |

**升級即取得新姿態**要寫在最前面（與 ADR 0021 的 `shell` 預設啟用同樣的處理）：
不接受這個姿態的節點必須主動關閉，而不是被動等待。

## 5. gates 註冊

`traceability/gates.json` 新增：

| gate id | layer | command | trigger |
|---|---|---|---|
| `GATE-PV-ARGV-CHANNEL` | static | `scripts/pv/check-no-argv-channel.sh` | pull_request, main, release |
| `GATE-PV-NODE-POSTURE` | manual | `scripts/pv/node-posture-check.sh` | release |

`GATE-PV-NODE-POSTURE` 標 release-triggered（需要一台真實 node），沿用
`GATE-TUNNEL-PROVIDER` 的作法：**每次都記錄它的缺席**，而不是假設它通過。
既有 gate（`GATE-BACKEND-UNIT` 等）不需要新增，本期的測試都落在它們的範圍內。

## 6. `PV-11` 安全審查

`docs/security-review-p12.md`，沿用 `security-review-p8.md`／`p11.md` 的結構。
輸入問題見 `04-…md` §5，另加三題：

1. `runtime-item.sandbox_bypass` 與 `privileged_terminal` 是**單向回報**嗎？
   有沒有任何 API／訊息路徑可以寫入它們？（應為無 —— 只有 `node.register`／`node.runtime_status` 寫入。）
2. 姿態欄位是否洩漏了不該給的資訊？（它們是 node 讀取權限的一部分；Viewer 看得到
   「這台機器可提權」是**刻意的**，因為那是他決定要不要在上面工作的依據。）
3. 本期是否有任何路徑讓 Central 決定 node 上執行什麼？（應為無；`GATE-PV-ARGV-CHANNEL` 是它的持續證據。）

審查結論要明確寫下**已接受的風險**（D0 的直接後果），不要用「已緩解」描述沒有緩解的事：

- node 內的任意程式碼執行與提權：**已接受**（可丟棄 VM，重建即處置）。
- node 上的憑證（`credentials.yaml`、tunnel token 的 argv）對取得 shell 的人可見：
  **未改變**（本來就同 uid），但要寫出來。
- 跨 node、跨租戶與對 Central 的影響：**不在已接受範圍內**，仍由既有控制（節點憑證、
  RBAC、資源範圍授權）承擔；本期沒有改動它們。

## 7. Exit 條件

全部滿足才算完成：

1. `make check` 全綠（含 `contract`、`traceability`、`lint`、`typecheck`、`build`）。
2. `scripts/pv/evidence.sh` 的 12 道 gate：全部執行，失敗數 0；skip 皆有具名理由。
3. `00-…md` §1 的九項判準各有可貼上的輸出，含 M1–M5 五項手動證據。
4. ADR 0023 已合併；ADR 0021 已加上交叉修訂註記；PRD 的六條 AC 修訂已合併並註冊到
   `traceability/requirements.json`，無無連結 AC。
5. `.agent/skills` 兩份 SKILL.md 已更新且符合 `AUTHORING.md`。
6. runbook 兩份（新增一份、更新一份）與 release note 一份已合併。
7. `docs/security-review-p12.md` 已完成，且「已接受的風險」一節有使用者核准的紀錄。
8. `07-…md` 的決策紀錄表沒有 `⬜ 未決定` 的項目 —— 或有，但每一項都寫明「為什麼可以帶著它交付」。
