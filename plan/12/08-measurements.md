# 08 — PV-01 實測記錄

本檔是 `07-…md` 決策表引用的原始輸出。放在 plan 目錄而不是 `artifacts/`，
因為 `artifacts/*/local/` 是 gitignore 的（evidence pack 是重新產生的，不是進 diff 被讀的），
而這幾項量測是「為什麼某些決定長這樣」的唯一依據 —— 特別是 tmux 的 argv 語意那一項，
它讓 `00-…md` D4 的結論反了過來。

重跑方式：`scripts/pv/node-posture-check.sh`（node 端觀測）與本檔下方的指令。

```text
# PV-01 measurements (2026-08-01T18:37:00Z) — host Linux 5.15.0-186-generic x86_64

## 1. codex version and the flag
binary: /home/ubuntu/.local/bin/codex
codex-cli 0.146.0
--help mentions the flag:
      --dangerously-bypass-approvals-and-sandbox

## 2. the flag does not disturb --version detection (runtime.go uses --version)
codex-cli 0.146.0
exit=0

## 4. how tmux 3.2a interprets a multi-word shell-command
multi-arg (/bin/echo '$HOME' one) → pane shows: []
single-string ("/bin/echo $HOME-single") → pane shows: []
multi-arg live argv: [/bin/sleep 30]
multi-arg  (/bin/cat '$HOME'): 
single-str ("/bin/cat $HOME"): 

### 4 (decisive): tmux 3.2a passes a multi-word shell-command straight to execvp
Discriminator: a literal `$HOME` as its own argument stays literal iff no shell is involved.

  multi-arg   tmux new-session -d -s multi /bin/cat '$HOME'
              → /bin/cat: '$HOME': No such file or directory      (literal → execvp, NO shell)
  single-str  tmux new-session -d -s single "/bin/cat $HOME"
              → /bin/cat: /home/ubuntu: Is a directory            (expanded → via shell)

  multi-arg live argv (ps -o args= on the pane pid): "/bin/sleep 30"

The daemon builds the multi-arg form (tmux/client.go Start), so launch flags reach the CLI
as separate argv elements with no shell in between. Consequence for plan/12/00 D4: the
flagPattern check in Start is belt-and-braces, not load-bearing — a future argument
containing a space would also be safe. It stays anyway: it costs nothing and it keeps the
argument list checkable at a glance.

### tmux escape sequences (re-measured here, same as the planning-time result)
  attach, default options : ESC[?1049h  ESC[?1000l ESC[?1002l ESC[?1006l   (alt screen, mouse OFF)
  attach, mouse on        : ESC[?1002h  ESC[?1006h                          (mouse reporting ON)
  default history-limit   : 2000        (< FR-TERM-004.AC-04's 5000)
  history-limit via -f    : applied at pane creation; a later set-option does NOT fix a live pane
  mouse via set-option -t : DOES take effect on a live session (the upgrade-path repair)

### sudo under NoNewPrivileges (observed in a no_new_privs=1 context on this host)
  sudo: The "no new privileges" flag is set, which prevents sudo from running as root.
  (This is the message the runbook quotes for the first of the four sudo failure modes.)
```

## 對決策的影響（摘要，完整版在 07-…md）

| 量測 | 結論 |
|---|---|
| codex 旗標 | `codex-cli 0.146.0` 支援，且不影響 `--version` 偵測 → D1／D3 的形狀成立 |
| tmux 多參數 | **直接 execvp，不經 shell** → D4 反轉：`flagPattern` 是保險而非必要條件 |
| `history-limit` 預設 2000 | `FR-TERM-004.AC-04` 在本期之前不成立 → `06-…md` §2 的補償 |
| `mouse` 的 escape sequence | ② 的根因與修法同一份證據 |
| `set-option -t` 對既有 session 有效、對 history 無效 | `03-…md` §2.4 的救援路徑與其殘留限制 |
| `NoNewPrivileges` 下 sudo 的原文 | runbook §4 第一種失敗模式 |
