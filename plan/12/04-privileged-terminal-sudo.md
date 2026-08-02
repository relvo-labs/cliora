# 04 — 特權終端機：sudo 的開放方式（PV-05）

適用 skill：`go-daemon-development`（systemd 封裝）＋ `cliora-security-review`（本檔是 `PV-11` 的主要審查對象）。

## 1. 為什麼「移除一行」是本期的核心

`daemon/internal/install/systemd.go:32` 的 `NoNewPrivileges=true` 會讓核心對整個
service cgroup 設下 `no_new_privs`，**setuid 從此無效**。sudo 是 setuid binary，因此在這行存在時
sudo 必定失敗（`PV-01` #9 要記下確切訊息，它會出現在 runbook 裡）。

所以「開放 sudo」的最小充分條件是兩件事，缺一不可：

1. unit **不再**設 `NoNewPrivileges=true`；
2. 服務使用者在 sudoers 裡有權限，且**不需要密碼**（`00-…md` D9）。

而「daemon 仍是非 root」在這兩件事之後仍然成立 —— 這正是 D8 選擇 sudo 而不是 `User=root` 的原因。

## 2. 實作

### 2.1 systemd unit

`UnitFile`（`daemon/internal/install/systemd.go:17`）加一個參數 `PrivilegedTerminal bool`：

```go
// UnitParams …
type UnitParams struct {
    User       string
    BinaryPath string
    ConfigPath string
    // PrivilegedTerminal drops NoNewPrivileges so that sudo works inside the
    // system terminal (ADR 0023). It is a posture switch, not a tuning knob:
    // with it set, the ceiling of the shell runtime is root on this machine.
    // The daemon itself still runs as User (EnsureNonRoot is unchanged) — see
    // plan/12/00 D8 for why that is not cosmetic.
    PrivilegedTerminal bool
}
```

- `PrivilegedTerminal` 為 false → 完全維持今天的字串（`NoNewPrivileges=true`），
  **既有節點的 unit 內容不變**。
- 為 true → 該行改為註解＋說明，而不是單純消失：

  ```ini
  # NoNewPrivileges is deliberately NOT set: the system terminal is allowed to
  # escalate with sudo on this node (ADR 0023, /etc/sudoers.d/60-agentd).
  ```

  理由：一個「不見了的 hardening 選項」在下一次有人 review unit 時會被當成疏漏而補回去，
  而補回去的症狀是「sudo 突然不能用了」，且沒有任何線索指向那次修改。
- `PrivateTmp=true` **保留**（`PV-01` #10 驗證它與 sudo 相容）。
- 新增 `RuntimeDirectory=agentd`（`03-…md` §2.2 的前提）。這一行與姿態無關，兩種姿態都要有。
- `install_test.go:143-146` 目前斷言 `NoNewPrivileges=true` 存在 —— 要改成**兩個**測試：
  非特權姿態下存在、特權姿態下不存在且註解在。不要只是把舊斷言刪掉。

### 2.2 sudoers drop-in

檔案 `/etc/sudoers.d/60-agentd`，內容：

```text
# Managed by agentd (ADR 0023, plan/12). Do not edit by hand.
# The Cliora system terminal (FR-SHELL-001) runs as this user; NOPASSWD is
# required because the service account has no password to type and because codex
# runs unattended (plan/12/00 D9). Remove this file and re-add
# NoNewPrivileges=true to the unit to revoke.
<user> ALL=(ALL) NOPASSWD:ALL
```

寫入程序（`daemon/internal/install/sudoers.go`，新檔），順序不可調換：

1. 檢查使用者名稱符合 `^[a-z_][a-z0-9_-]{0,31}$`（POSIX 使用者名）。**不符即中止**，
   不做任何寫入 —— 這個字串會進入一個會被 root 解析的檔案。
2. 寫到同一個檔案系統上的暫存檔（`/etc/sudoers.d/.60-agentd.tmp`，0440，root:root）。
3. `visudo -cf <tmpfile>`。**失敗即刪除暫存檔並中止安裝**。
4. `os.Chmod(0o440)` → `os.Rename` 到最終路徑（同檔案系統，原子）。
5. 驗證：以服務使用者身分跑 `sudo -n -u root true`（`runuser -u <user> -- sudo -n true`）；
   失敗則**還原**（刪除 drop-in）並回報，不留下半套狀態。

| 決定 | 選擇 | 理由 |
|---|---|---|
| 檔名前綴 `60-` | 數字前綴決定 `#includedir` 的讀取順序 | 讓它落在發行版預設檔（通常 `01-`…）之後、使用者自訂之前；同時避免 dpkg 的保留名稱 |
| 權限 0440 root:root | sudo 對權限不符的 drop-in 會**整份忽略** | 症狀是「檔案在那裡但沒作用」，非常難查 |
| 一定要 `visudo -cf` | 語法錯的 drop-in 會讓**整台機器**的 sudo 失效 | 而修復它需要 sudo。這是本期唯一一個可以把機器弄成無法自救的操作（`00-…md` §5） |
| 檔名不含 hostname／node id | 一台機器只有一個 agentd 服務使用者 | 多份 drop-in 會讓「撤銷」變成一件要搜尋的事 |
| 不用 `%group` | 針對單一使用者 | 群組會把權限給未來被加進該群組的人，而那不是本期核准的範圍 |

### 2.3 installer 旗標

| 旗標 | 預設 | 行為 |
|---|---|---|
| `agentd install --privileged-terminal` | **開啟**（`--privileged-terminal=false` 或 `--no-privileged-terminal` 可關） | unit 省略 `NoNewPrivileges`、寫入 sudoers drop-in、config 寫 `node.privileged_terminal: true` |
| `deploy/install.sh --no-privileged-terminal` | 同上，透傳 | shell 只負責傳遞（`install.sh` 的既有分工：「thin by design」） |

安裝過程必須**明示**（`SEC-007.AC-02`），列在既有「該 Daemon 將具備此 Linux 使用者權限」提示之後：

```text
warning: 此 Node 的系統終端機可經 sudo 取得 root 權限，且 codex 將在停用沙箱與核准流程下執行。
         這是預設姿態，適用於可丟棄的隔離 VM。若本機不是，請以 --no-privileged-terminal 安裝，
         並在 /etc/agentd/config.yaml 設 runtime.codex.sandbox_bypass: false。
```

### 2.4 既有節點怎麼升級（不能靠重跑 install）

`agentd install` 需要一次性 enrollment token 並會註冊出**新的 node**，所以它不是升級路徑；
而 `agentd update`（ADR 0017）只換 binary，**不會重寫 unit**。因此既有節點必須有一條明確的路：

新增 `agentd posture`（root 執行，冪等）：

```text
agentd posture --privileged-terminal            # 套用：改 unit、寫 sudoers、daemon-reload、restart
agentd posture --privileged-terminal=false      # 撤銷：還原 NoNewPrivileges、刪 sudoers、restart
agentd posture                                  # 只印目前狀態（unit 是否有該行、drop-in 是否存在、sudo -n 是否成功）
```

| 決定 | 選擇 | 理由 |
|---|---|---|
| 為什麼是新子命令而不是 runbook 的手動步驟 | 手動步驟包含編輯 sudoers，而那是 §2.2 列為「可以把機器弄壞」的那一步 | 同一套 `visudo -cf` ＋原子 rename ＋回滾邏輯，只寫一次、被測試覆蓋 |
| 為什麼不放進 `agentd update` | update 是自動觸發的（Central 可下發）。**姿態變更不可由 Central 觸發**（D11／D13） | 一個能改姿態的遠端指令就是一個能提權的遠端指令 |
| 冪等 | 已是目標姿態時只印狀態、不 restart | 否則 runbook 的「重跑一次確認」會踢掉所有 session |
| restart 的代價 | daemon 重啟不殺 tmux session（ADR 0004 的復原設計），但**本期切 socket 的那一次會**（D5b） | release note 要把兩件事分開講，否則使用者會以為每次 `posture` 都會殺 session |

`uninstall`（`install.go:244` 附近）要一併移除 drop-in（`--purge` 與否都移除 —— 留下一個
指向已不存在服務的 sudoers 檔案是最糟的殘留）。

### 2.5 config 的 `node.privileged_terminal`

```go
// NodeConfig …
    // PrivilegedTerminal is a *report*, not an authorization: the real grant is
    // the sudoers drop-in plus the absence of NoNewPrivileges. It exists so the
    // daemon can tell the platform what posture this machine is in without
    // parsing systemd state at runtime. `agentd posture` keeps the two in sync;
    // `agentd doctor` reports when they disagree.
    PrivilegedTerminal bool `yaml:"privileged_terminal"`
```

**這一欄不能被誤解為安全控制**：把它改成 false 不會讓 sudo 失效。因此 `doctor` 必須能偵測
「config 說 false，但 `sudo -n true` 成功」這種不一致並報 `[warn]`，訊息指向 `agentd posture`。

### 2.6 `agentd doctor` 三項

| 檢查 | 方法 | 訊息 |
|---|---|---|
| `no-new-privs` | 讀 `/proc/self/status` 的 `NoNewPrivs:` | `[info] no-new-privs=0 (privileged terminal enabled)` / `=1 (sudo will fail)` |
| `sudo` | `sudo -n true`（daemon 身分） | 成功 → `[info] sudo=available`；失敗 → `[info] sudo=unavailable`（**非 FAIL**：不特權是合法姿態） |
| 姿態一致性 | config 的 `privileged_terminal` × 前兩項的實測 | 不一致 → `[warn] posture mismatch：config 說 X，實測 Y，請執行 `agentd posture` |

`doctor` 的第一項 `report("non-root", config.EnsureNonRoot())`（`commands.go:87`）**保持不動**。
它現在的意義更重要：它是「我們沒有走 `User=root` 那條路」的持續證據。

## 3. 不特權節點仍然要能用

一台以 `--no-privileged-terminal` 安裝的 node：

- unit 保留 `NoNewPrivileges=true`，沒有 sudoers drop-in；
- 系統終端機照常可用（ADR 0021 不變），只是 sudo 會失敗，**且失敗訊息應該讓人看得懂**
  —— 這一點平台幫不上忙（訊息來自 sudo），但 UI 的姿態標示會顯示「終端機：不可提權」，
  使用者因此知道那不是故障；
- `runtime.codex.sandbox_bypass` 仍可獨立設定：**兩個姿態是分開的**（一台機器可以「有沙箱但可提權」，
  也可以「無沙箱但不可提權」）。不要把兩者綁成一個開關 —— 它們的風險來源不同
  （一個是第三方 CLI 的行為，一個是這台機器的權限模型）。

## 4. 測試

| 測試 | 斷言 |
|---|---|
| `TestUnitFileKeepsNoNewPrivilegesByDefault` | `PrivilegedTerminal: false` → 含 `NoNewPrivileges=true` |
| `TestUnitFileOmitsNoNewPrivilegesWhenPrivileged` | true → 不含該指令、含說明註解、仍含 `PrivateTmp=true` 與 `User=`／`Group=` |
| `TestUnitFileAlwaysHasRuntimeDirectory` | 兩種姿態都含 `RuntimeDirectory=agentd` |
| `TestSudoersRejectsInvalidUserName` | `neil; rm -rf /`、`root ALL`、空字串、超長 → 錯誤且**未寫入任何檔案** |
| `TestSudoersContentAndMode` | 內容為單行 `NOPASSWD:ALL` ＋三行註解；模式 0440 |
| `TestSudoersValidationFailureLeavesNothingBehind` | 注入一個必定失敗的 `visudo` stub → 暫存檔與最終檔皆不存在 |
| `TestSudoersWriteIsAtomic` | 已存在舊內容時，中途失敗不得留下半個檔案（rename 語意） |
| `TestPostureIsIdempotent` | 已是目標姿態 → 沒有 `systemctl restart` 呼叫 |
| `TestPostureRevokeRemovesDropInAndRestoresUnit` | 撤銷後 unit 含 `NoNewPrivileges=true`、drop-in 不存在 |
| `TestUninstallRemovesSudoersDropIn` | `--purge` 與非 `--purge` 兩種都移除 |
| `TestDoctorReportsPostureMismatch` | config true × `sudo -n` 失敗 → `[warn]` 且 exit code 0 |
| **手動**（`PV-01` #9／#10 的重跑） | 系統終端機內 `sudo -n id` → `uid=0`；`systemctl show -p User agentd` → 非 root |

sudoers 與 unit 的寫入邏輯要用**注入的檔案系統根目錄與 `visudo` 路徑**（沿用
`install/verify.go` 已有的注入手法），這樣測試不需要 root 也不會碰到真的 `/etc`。
這一點是硬要求：一個會直接寫 `/etc/sudoers.d` 的測試在 CI 上不是失敗就是危險。

## 5. 安全審查要回答的問題（`PV-11` 的輸入）

1. 除了系統終端機，還有哪些路徑會因為 `no_new_privs` 消失而變得可提權？
   （答案應該是：所有以 daemon 身分執行的東西 —— 包括 `codex`／`claude` 自己會呼叫的子行程。
   這正是使用者要的，但要寫出來。）
2. `tunnel.open` 帶下來的 provider 憑證（plan/11 D18，存在於 `ssh` 的 argv）在特權姿態下的暴露是否改變？
   （同 uid 的行程本來就讀得到；提權後**任何**取得 shell 的人都能讀 —— 但取得 shell 的人本來就是同一個 uid。
   結論應是「未改變」，但要有這一段。）
3. `credentials.yaml`（0600）與 config 在特權姿態下不再有檔案權限保護 —— 對 node 內的攻擊者沒有意義
   （他本來就是那個 uid），但要確認**平台側**沒有依賴 node 內的檔案權限做任何判斷。
4. 一台被完全控制的 node 能對 Central 做什麼？（這一題與本期無關 —— 它在 ADR 0021 就已成立 ——
   但審查要重申答案，因為 D0 的「壞掉就重建」只涵蓋 VM，不涵蓋平台。）
