# Cliora 特權節點姿態：無沙箱 codex、可滾動的終端機、可提權的系統終端機

本目錄交付三件在 2026-08-01 由使用者指示的變更，ticket 統一使用 `PV-` 前綴（**P**rivileged posture）：

| # | 使用者的話 | 交付內容 |
|---|---|---|
| ① | 「agentd 上的 codex 預設要帶 `--dangerously-bypass-approvals-and-sandbox` 執行」 | daemon 端**固定的啟動參數表**，`codex` 預設帶該旗標；node 可用一個布林關掉；平台把實際狀態回報並顯示 |
| ② | 「terminal 現在不能上下 scroll 要修正」 | tmux 環境改由 daemon 自有（專用 socket＋自有 `tmux.conf`）：`mouse on`＋`history-limit`，滑鼠滾輪進 tmux copy-mode |
| ③ | 「terminal 要開放 sudo 才行」 | systemd unit 移除 `NoNewPrivileges=true`＋`/etc/sudoers.d/60-agentd`；**daemon 本身仍非 root** |

使用者同時說明了風險立場：**「我們已經做了 VM 隔離，我不擔心 VM 壞掉，壞掉就再做一個」**。
本計畫據此把「節點是可丟棄的隔離 VM」寫成明文前提（`00-…md` D0），而不是把三個變更各自包裝成
看起來比較安全的樣子。前提被寫下來的代價是它可以被檢查：一台**不是**可丟棄 VM 的機器，
要用 `--no-privileged-terminal` 與 `sandbox_bypass: false` 安裝（`04-…md` §3）。

## 這一期真正的形狀

三件事看起來各自獨立，實際上都落在同一條路徑上 —— **daemon 如何啟動與承載一個終端**：

```
session.start(runtime=codex)
      │
      ▼
runtime.ResolveLaunch("codex")            ← ① 參數表在這裡（不是設定檔的 argv，不是 wire 欄位）
      │  {Path: /usr/bin/codex, Args: ["--dangerously-bypass-approvals-and-sandbox"]}
      ▼
tmux -L cliora -f /run/agentd/tmux.conf new-session … codex --dangerously-…
      │                    ▲
      │                    └── ② mouse on / history-limit / escape-time / status off 在這裡
      ▼
tmux attach-session（PTY）→ WSS → xterm.js
      │
      └── ③ 這個 PTY 裡的 sudo 能不能成功，由 systemd unit 與 sudoers 決定
```

因此三件事共用同一批測試、同一份 release note、同一次安全審查，也共用同一個必須說實話的地方：
**使用者在 UI 上看得到自己身處哪一種邊界**（`00-…md` D10）。

## 兩項已量測的事實（不是推論）

實測於 2026-08-01、tmux 3.2a、`@xterm/xterm` 5.5.0：

1. **滾不動的根因已定位。** `tmux attach` 一開始就送 `ESC[?1049h`（進入 alternate screen），
   接著明確送 `ESC[?1000l ESC[?1002l ESC[?1006l`（**關閉**滑鼠回報）。xterm.js 的 alt buffer
   沒有 scrollback，而在「應用程式未啟用滑鼠回報」時它會走
   `if (!this.buffer.hasScrollback)` 分支把滾輪**轉成方向鍵**送給應用程式 —— 所以今天在 bash 裡
   往上滾會翻出歷史命令，在 TUI 裡會移動選擇項。開 `mouse on` 之後 tmux 改送 `ESC[?1002h ESC[?1006h`，
   xterm.js 就改為轉送 SGR 滑鼠事件，滾輪進 tmux copy-mode。詳見 `03-…md` §1。
2. **`FR-TERM-004.AC-04` 目前是不成立的。** 該條要求「Daemon 的 tmux Scrollback 至少保存 5000 行」，
   但 tmux 預設 `history-limit` 實測為 **2000**，而 installer 寫進 config 的
   `session.scrollback_limit: 5000`（`daemon/internal/install/plan.go:117`）**從未被任何程式讀取**。
   本期把它接上線，所以 ② 不只是一個 UX 修正，它同時修掉一條既有的需求違反（`06-…md` §2）。

## 這一期最容易做錯的五件事

1. **在設定檔或 wire 上開一個 argv／args 欄位。** `RuntimeConfig` 沒有 argv 欄位是刻意的
   （`daemon/internal/config/config.go:172` 的註解就是在講這件事），`session.start` 的
   `additionalProperties:false` 也是（ADR 0021 §1 存活的那半條 `SCOPE-011`）。① 要的是**一個布林**，
   不是一個字串陣列（D1）。
2. **把 `mouse on` 設在 node 擁有者自己的 tmux server 上。** 今天 production 的
   `session.New(ctmux.Client{}, …)`（`daemon/internal/connection/connection.go:101`）socket 是空字串，
   也就是**共用使用者的預設 tmux server**。在那裡 `set -g` 會改掉別人的環境（D5）。
3. **把 daemon 改成 root 來取得 sudo。** 那會一次廢掉 `EnsureNonRoot()`、update healthcheck 的
   身分假設、workspace 檔案擁有權，以及 ADR 0021 §4.2 整段補償控制的論述。要的是「非 root 但可提權」（D8）。
4. **寫壞 `/etc/sudoers.d/`。** 一個語法錯的 drop-in 會讓**整台機器**的 sudo 失效，包括修復它所需要的
   那次 sudo。必須先寫到暫存檔、`visudo -cf` 驗過、再以 0440 安裝（`04-…md` §2.2）。
5. **讓 UI 說謊。** 「codex 帶了旗標」不能是 UI 依設定推導出來的樂觀值；旗標可能因為 codex 版本
   不支援而沒有生效。回報的必須是 daemon 實測到的狀態（D3）。

## 檔案

| 檔案 | 內容 |
|---|---|
| `00-execution-plan.md` | 成功定義、範圍、固定基線決策 D0–D14、波次與 ticket、風險 |
| `01-decisions-and-governance.md` | ADR 0023、PRD 修訂（SEC-007／FR-SHELL-001／FR-TERM-004／SCOPE-011 註記）、traceability 註冊 |
| `02-daemon-runtime-argv.md` | `PV-03`：啟動參數表、`sandbox_bypass` 設定、偵測與 `doctor` |
| `03-daemon-tmux-scrollback.md` | `PV-04`：專用 socket、`/run/agentd/tmux.conf`、滾動與選取的取捨、既有 session 的遷移 |
| `04-privileged-terminal-sudo.md` | `PV-05`：systemd unit、sudoers drop-in、installer 旗標、`doctor` |
| `05-contract-central-and-frontend.md` | `PV-06`–`PV-08`：契約 v1.7.0、migration 0017、姿態回報與 UI 標示 |
| `06-verification-and-exit.md` | `PV-10`–`PV-11`：測試清單、evidence、gates、runbook、release note、exit 條件 |
| `07-implementation-status.md` | 實作進度與決策紀錄（**已完成**，含與計畫的差異一覽） |
| `08-measurements.md` | `PV-01` 的實測輸出（`artifacts/*/local/` 是 gitignore 的，所以量測結果放這裡） |

規範來源一律回指 `research/prd.md`、`research/tech.md`、`docs/adr/`，本目錄不複製需求內容
（`.agent/skills/AUTHORING.md`「Never duplicate canonical research」）。
`.agent/skills` 本身的更新是 `PV-09`（`05-…md` §4）。
