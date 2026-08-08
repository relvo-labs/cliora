# 多節點 CLI Agent 中央管理平台 PRD

## 1. 文件資訊

| 項目           | 內容                           |
| ------------ | ---------------------------- |
| 文件名稱         | 多節點 CLI Agent 中央管理平台 PRD     |
| 版本           | v1.0                         |
| 文件狀態         | 初稿                           |
| 產品類型         | 內部開發工具／Agent 管理平台            |
| 目標使用者        | 開發人員、技術主管、平台管理員              |
| 後端技術         | FastAPI、PostgreSQL、WebSocket |
| 前端技術         | Vue 3、TypeScript、Naive UI    |
| VM Daemon    | Go                           |
| Terminal     | xterm.js                     |
| 檔案預覽         | Monaco Editor                |
| 主要支援 Runtime | Claude CLI、Codex CLI         |

---

# 2. 產品背景

目前 Claude CLI、Codex CLI 等 AI 開發工具通常直接執行於單一開發主機或 VM 中，使用者需要透過 SSH、遠端桌面或直接登入 VM 才能操作。

當組織內存在多台 VM、多個專案與多個 CLI Session 時，會出現以下問題：

1. 無法在單一介面查看所有 VM 的在線狀態。
2. 無法快速知道每台 VM 是否已安裝 Claude CLI 或 Codex CLI。
3. 需要分別登入各 VM 才能操作 CLI。
4. 不易管理不同 CLI Session 與其對應的工作目錄。
5. 無法在 Web 上快速查看 CLI 正在處理的專案內容。
6. VM 上的 CLI Session 在網路中斷或瀏覽器關閉後，不易重新連線。
7. 安裝與設定 Agent Daemon 的流程容易因 VM 環境不同而不一致。

本產品將提供一個中央 Web 管理平台，透過安裝於各 VM 的 Go Daemon，統一管理 Claude CLI 與 Codex CLI。

使用者可透過 Web：

* 查看所有 VM。
* 選擇 VM。
* 選擇 Claude 或 Codex。
* 指定工作目錄。
* 建立與操作 CLI Session。
* 瀏覽 Workspace 目錄與檔案。
* 重新連線既有 Session。
* 查看 VM 與 Runtime 狀態。

本系統不重新實作 Claude 或 Codex 的審批、工具執行與 Agent 邏輯，而是完整保留原生 CLI 操作體驗。

---

# 3. 產品目標

## 3.1 核心目標

建立一套輕量、集中式的 CLI Agent 管理平台，讓使用者可透過瀏覽器操作分散於不同 VM 的 Claude CLI 與 Codex CLI。

## 3.2 具體目標

1. 提供所有 VM 的集中管理介面。
2. 由 VM 主動連線中央平台，避免中央主動 SSH 至 VM。
3. 支援 Claude CLI 與 Codex CLI 切換。
4. 支援由使用者指定 CLI 的工作目錄。
5. 提供完整互動式 Web Terminal。
6. 保留 CLI 原生審批流程與互動方式。
7. 提供 Workspace 檔案樹與唯讀檔案預覽。
8. 支援 Session 重新連線。
9. 提供簡單的一行指令安裝 Daemon。
10. 降低 VM 安裝、設定與維運成本。

---

# 4. 非目標

第一階段不包含以下功能：

<a id="scope-001"></a>
<a id="scope-001-ac-01"></a>
1. 不解析 Claude 或 Codex 的內部事件。
<a id="scope-002"></a>
<a id="scope-002-ac-01"></a>
2. 不建立中央審批機制。
<a id="scope-003"></a>
<a id="scope-003-ac-01"></a>
3. 不攔截或替代 CLI 原生權限確認。
<a id="scope-004"></a>
<a id="scope-004-ac-01"></a>
4. 不建立多 Agent 自動協作流程。
<a id="scope-005"></a>
<a id="scope-005-ac-01"></a>
5. 不進行任務自動分派。
<a id="scope-006"></a>
<a id="scope-006-ac-01"></a>
6. 不提供 Web 端完整 IDE。
<a id="scope-007"></a>
<a id="scope-007-ac-01"></a>
7. 不提供第一階段的檔案寫入與編輯功能。
<a id="scope-008"></a>
<a id="scope-008-ac-01"></a>
8. 不提供自動 Git Commit、Push 或 Merge Request。
<a id="scope-009"></a>
<a id="scope-009-ac-01"></a>
9. 不提供 CLI 對話內容的語意分析。
<a id="scope-010"></a>
<a id="scope-010-ac-01"></a>
10. 不建立跨 Runtime 的統一 Agent 行為模型。
<a id="scope-011"></a>
<a id="scope-011-ac-01"></a>
11. 前端不得指定任意 Shell Command 字串。前端只送 Runtime ID，實際 Binary 由 Node 自行解析；
    協定上不存在 Command／Binary／Argv／Env／Entrypoint 欄位。
    （範圍變更 2026-07-31，ADR 0021：互動式系統終端機改由 FR-SHELL-001 明文規範並限定條件開放，
    本條原先的「完全不提供任意 Shell」已由 FR-SHELL-001.AC-03 取代。）
    （2026-08-01，ADR 0023：本期**未再削減**本條。Daemon 雖新增自有的固定啟動參數，
    前端與 Central 仍不得指定命令、參數、環境變數或 Entrypoint；見 FR-RUNTIME-003.AC-02。）
<a id="scope-012"></a>
<a id="scope-012-ac-01"></a>
12. 不將 VM 檔案系統直接掛載至中央伺服器。
<a id="scope-013"></a>
<a id="scope-013-ac-01"></a>
13. 不由平台自建對外反向代理。埠轉發以第三方隧道服務整合交付：該路徑的流量不經過平台，
    平台因此不提供存取記錄、內容政策與頻寬計量；服務訂閱與帳號由使用者自行持有，平台不代管。
    （範圍新增 2026-08-01，ADR 0022；自建方案見 plan/10，已作廢。）

---

# 5. 使用者角色

## 5.1 平台管理員

負責：

* 建立 Daemon 安裝 Token。
* 管理 VM Node。
* 停用或移除 Node。
* 查看 Node 在線狀態。
* 設定可使用的 Workspace Root。
* 管理使用者與權限。
* 查看系統操作紀錄。

## 5.2 開發人員

負責：

* 選擇 VM。
* 選擇 Claude 或 Codex。
* 選擇 Workspace。
* 建立 CLI Session。
* 操作 Web Terminal。
* 查看 Workspace 檔案。
* 中止或重新連線 Session。

## 5.3 唯讀使用者

負責：

* 查看 Node 狀態。
* 查看 Session 狀態。
* 瀏覽 Workspace 檔案。
* 不可建立或操作 Terminal Session。

---

# 6. 核心使用流程

## 6.1 安裝 Daemon

1. 管理員登入中央平台。
2. 建立 Enrollment Token。
3. 平台產生安裝指令。
4. 管理員於 VM 執行安裝指令。
5. 安裝腳本下載對應架構的 Go Binary。
6. Daemon 建立設定檔與 systemd Service。
7. Daemon 啟動後向中央平台註冊。
8. 中央平台顯示新的 VM Node。
9. Daemon 回報 Claude 與 Codex 的可用狀態。

## 6.2 建立 CLI Session

1. 使用者進入 Node 詳情頁。
2. 選擇 Runtime：

   * Claude
   * Codex
3. 選擇 Workspace Root。
4. 瀏覽目錄並選擇工作目錄。
5. 輸入 Session 名稱。
6. 點擊「啟動 Session」。
7. 中央平台送出 Session 建立命令。
8. Daemon 驗證工作目錄是否合法。
9. Daemon 使用 PTY 或 tmux 啟動 CLI。
10. 前端開啟 xterm.js。
11. 使用者開始操作 CLI。

## 6.3 操作 CLI

1. 使用者在 Web Terminal 輸入文字或快捷鍵。
2. 前端透過 WebSocket 傳送輸入。
3. 中央平台轉送至指定 Daemon。
4. Daemon 將輸入寫入 PTY。
5. CLI 輸出由 PTY 傳回 Daemon。
6. 中央平台將輸出轉送至瀏覽器。
7. xterm.js 顯示原始終端內容。
8. CLI 原生審批選單可直接由鍵盤操作。

## 6.4 瀏覽 Workspace

1. 使用者於 Session 頁面開啟 Files。
2. 前端請求 Workspace 根目錄。
3. 中央平台將請求轉送至 Daemon。
4. Daemon 驗證路徑。
5. Daemon 回傳目錄內容。
6. 使用者展開資料夾。
7. 使用者點擊檔案。
8. Daemon讀取並回傳檔案內容。
9. Monaco Editor 以唯讀模式顯示。

## 6.5 重新連線 Session

1. 使用者關閉瀏覽器或網路中斷。
2. CLI Session 持續在 VM 執行。
3. 使用者重新登入平台。
4. 進入 Session 詳情頁。
5. 點擊「重新連線」。
6. Daemon重新附加至原 Session。
7. 前端重新取得終端輸出或 Scrollback。
8. 使用者繼續操作。

---

# 7. 系統架構

```text
┌───────────────────────────────────────────────┐
│                  Vue Web                      │
│                                               │
│ Node 管理                                     │
│ Session 管理                                  │
│ Runtime 選擇                                  │
│ xterm.js Terminal                             │
│ Workspace File Tree                           │
│ Monaco File Preview                           │
└──────────────────────┬────────────────────────┘
                       │ HTTP / WebSocket
                       ▼
┌───────────────────────────────────────────────┐
│              FastAPI Central Server           │
│                                               │
│ Authentication                                │
│ Node Registry                                 │
│ Session Management                            │
│ WebSocket Relay                               │
│ Workspace Request Relay                       │
│ Enrollment Token                              │
│ Audit Log                                     │
└──────────────────────┬────────────────────────┘
                       │ Persistent WebSocket
                       ▼
┌───────────────────────────────────────────────┐
│                  Go Daemon                    │
│                                               │
│ Connection Manager                            │
│ Heartbeat                                     │
│ Runtime Detection                             │
│ Claude / Codex Launcher                       │
│ PTY / tmux Session Manager                    │
│ Workspace Validation                          │
│ Filesystem Browser                            │
│ System Information                            │
└───────────────────────────────────────────────┘
```

---

# 8. 功能需求

# 8.1 使用者登入與權限

<a id="fr-auth-001"></a>
## FR-AUTH-001 使用者登入

系統應提供帳號密碼登入。

驗收條件：

<a id="fr-auth-001-ac-01"></a>
* 使用者可使用有效帳號登入。
<a id="fr-auth-001-ac-02"></a>
* 無效帳號或密碼不可登入。
<a id="fr-auth-001-ac-03"></a>
* 登入成功後取得有效 Session 或 JWT。
<a id="fr-auth-001-ac-04"></a>
* Token 過期後需重新登入或刷新。

<a id="fr-auth-002"></a>
## FR-AUTH-002 角色權限

<a id="fr-auth-002-ac-01"></a>
系統至少提供：

<a id="fr-auth-002-ac-02"></a>
* Admin
<a id="fr-auth-002-ac-03"></a>
* Developer
<a id="fr-auth-002-ac-04"></a>
* Viewer

權限範圍：

| 功能           | Admin | Developer | Viewer |
| ------------ | ----: | --------: | -----: |
<a id="fr-auth-002-ac-05"></a>
| 查看 Node      |     ✓ |         ✓ |      ✓ |
<a id="fr-auth-002-ac-06"></a>
| 建立安裝 Token   |     ✓ |           |        |
<a id="fr-auth-002-ac-07"></a>
| 移除 Node      |     ✓ |           |        |
<a id="fr-auth-002-ac-08"></a>
| 建立 Session   |     ✓ |         ✓ |        |
<a id="fr-auth-002-ac-09"></a>
| 操作 Terminal  |     ✓ |         ✓ |        |
<a id="fr-auth-002-ac-10"></a>
| 終止 Session   |     ✓ |         ✓ |        |
<a id="fr-auth-002-ac-11"></a>
| 瀏覽檔案         |     ✓ |         ✓ |      ✓ |
<a id="fr-auth-002-ac-12"></a>
| 查看 Audit Log |     ✓ |           |        |

---

# 8.2 Node 管理

<a id="fr-node-001"></a>
## FR-NODE-001 Node 註冊

<a id="fr-node-001-ac-01"></a>
Daemon 應可使用 Enrollment Token 向中央平台註冊。

註冊資訊至少包含：

<a id="fr-node-001-ac-02"></a>
* Node ID
<a id="fr-node-001-ac-03"></a>
* Node 名稱
<a id="fr-node-001-ac-04"></a>
* Hostname
<a id="fr-node-001-ac-05"></a>
* OS
<a id="fr-node-001-ac-06"></a>
* OS 版本
<a id="fr-node-001-ac-07"></a>
* CPU 架構
<a id="fr-node-001-ac-08"></a>
* Daemon 版本
<a id="fr-node-001-ac-09"></a>
* 執行使用者
<a id="fr-node-001-ac-10"></a>
* Claude 是否存在
<a id="fr-node-001-ac-11"></a>
* Claude 版本
<a id="fr-node-001-ac-12"></a>
* Codex 是否存在
<a id="fr-node-001-ac-13"></a>
* Codex 版本
<a id="fr-node-001-ac-14"></a>
* Workspace Root
<a id="fr-node-001-ac-15"></a>
* 註冊時間

<a id="fr-node-002"></a>
## FR-NODE-002 Node 在線狀態

<a id="fr-node-002-ac-01"></a>
Daemon 應定期送出 Heartbeat。

建議頻率：

<a id="fr-node-002-ac-02"></a>
* 每 10 秒一次。

Node 狀態：

<a id="fr-node-002-ac-03"></a>
* Online
<a id="fr-node-002-ac-04"></a>
* Degraded
<a id="fr-node-002-ac-05"></a>
* Offline
<a id="fr-node-002-ac-06"></a>
* Disabled

判斷建議：

<a id="fr-node-002-ac-07"></a>
* 30 秒內收到 Heartbeat：Online。
<a id="fr-node-002-ac-08"></a>
* 30 至 90 秒未收到：Degraded。
<a id="fr-node-002-ac-09"></a>
* 超過 90 秒未收到：Offline。

<a id="fr-node-003"></a>
## FR-NODE-003 Node 列表

<a id="fr-node-003-ac-01"></a>
Node 列表需顯示：

<a id="fr-node-003-ac-02"></a>
* Node 名稱
<a id="fr-node-003-ac-03"></a>
* Hostname
<a id="fr-node-003-ac-04"></a>
* 在線狀態
<a id="fr-node-003-ac-05"></a>
* OS
<a id="fr-node-003-ac-06"></a>
* Claude 可用狀態
<a id="fr-node-003-ac-07"></a>
* Codex 可用狀態
<a id="fr-node-003-ac-08"></a>
* 執行中 Session 數量
<a id="fr-node-003-ac-09"></a>
* 最後在線時間

<a id="fr-node-004"></a>
## FR-NODE-004 Node 詳情

<a id="fr-node-004-ac-01"></a>
Node 詳情需顯示：

<a id="fr-node-004-ac-02"></a>
* 系統資訊
<a id="fr-node-004-ac-03"></a>
* Runtime 狀態
<a id="fr-node-004-ac-04"></a>
* Workspace Root
<a id="fr-node-004-ac-05"></a>
* Daemon 版本
<a id="fr-node-004-ac-06"></a>
* Session 列表
<a id="fr-node-004-ac-07"></a>
* 最後 Heartbeat
<a id="fr-node-004-ac-08"></a>
* 安裝與更新狀態

<a id="fr-node-005"></a>
## FR-NODE-005 Node 停用

<a id="fr-node-005-ac-01"></a>
管理員可停用 Node。

停用後：

<a id="fr-node-005-ac-02"></a>
* Daemon 可保持連線。
<a id="fr-node-005-ac-03"></a>
* 不可建立新 Session。
<a id="fr-node-005-ac-04"></a>
* 既有 Session 是否中止由管理員選擇。
<a id="fr-node-005-ac-05"></a>
* 前端顯示 Disabled。

---

# 8.3 Daemon 安裝

<a id="fr-install-001"></a>
## FR-INSTALL-001 建立 Enrollment Token

<a id="fr-install-001-ac-01"></a>
管理員可建立一次性或限時 Token。

Token 屬性：

<a id="fr-install-001-ac-02"></a>
* Token 值
<a id="fr-install-001-ac-03"></a>
* 建立者
<a id="fr-install-001-ac-04"></a>
* 建立時間
<a id="fr-install-001-ac-05"></a>
* 過期時間
<a id="fr-install-001-ac-06"></a>
* 最大使用次數
<a id="fr-install-001-ac-07"></a>
* 已使用次數
<a id="fr-install-001-ac-08"></a>
* 是否停用

<a id="fr-install-002"></a>
## FR-INSTALL-002 一行安裝指令

<a id="fr-install-002-ac-01"></a>
平台應產生類似以下指令：

```bash
curl -fsSL https://platform.example.com/install.sh | \
sudo bash -s -- \
  --server https://platform.example.com \
  --token enroll_xxxxx \
  --name dev-vm-01 \
  --user neil
```

<a id="fr-install-003"></a>
## FR-INSTALL-003 自動安裝流程

<a id="fr-install-003-ac-01"></a>
安裝腳本應：

<a id="fr-install-003-ac-02"></a>
1. 檢查 Linux 發行版。
<a id="fr-install-003-ac-03"></a>
2. 檢查 CPU 架構。
<a id="fr-install-003-ac-04"></a>
3. 下載正確的 Go Binary。
<a id="fr-install-003-ac-05"></a>
4. 驗證 Binary Checksum。
<a id="fr-install-003-ac-06"></a>
5. 安裝至 `/usr/local/bin/agentd`。
<a id="fr-install-003-ac-07"></a>
6. 建立 `/etc/agentd/config.yaml`。
<a id="fr-install-003-ac-08"></a>
7. 建立 `/var/lib/agentd`。
<a id="fr-install-003-ac-09"></a>
8. 建立 systemd Service。
<a id="fr-install-003-ac-10"></a>
9. 設定執行使用者。
<a id="fr-install-003-ac-11"></a>
10. 啟用開機啟動。
<a id="fr-install-003-ac-12"></a>
11. 啟動 Daemon。
<a id="fr-install-003-ac-13"></a>
12. 驗證中央連線。
<a id="fr-install-003-ac-14"></a>
13. 回傳安裝結果。

<a id="fr-install-004"></a>
## FR-INSTALL-004 Daemon CLI

<a id="fr-install-004-ac-01"></a>
Daemon 應至少提供：

```text
agentd install
agentd uninstall
agentd start
agentd stop
agentd status
agentd doctor
agentd register
agentd config validate
agentd runtime list
agentd workspace list
agentd version
```

<a id="fr-install-005"></a>
## FR-INSTALL-005 Daemon 更新

<a id="fr-install-005-ac-01"></a>
第一階段可使用手動更新：

```bash
sudo agentd update
```

更新流程：

<a id="fr-install-005-ac-02"></a>
1. 向中央取得最新版本資訊。
<a id="fr-install-005-ac-03"></a>
2. 下載新 Binary。
<a id="fr-install-005-ac-04"></a>
3. 驗證 Checksum。
<a id="fr-install-005-ac-05"></a>
4. 備份舊版本。
<a id="fr-install-005-ac-06"></a>
5. 替換 Binary。
<a id="fr-install-005-ac-07"></a>
6. 重新啟動 Daemon。
<a id="fr-install-005-ac-08"></a>
7. 若啟動失敗則回復舊版本。

---

# 8.4 Runtime 管理

<a id="fr-runtime-001"></a>
## FR-RUNTIME-001 Runtime 偵測

<a id="fr-runtime-001-ac-01"></a>
Daemon 啟動時應偵測：

<a id="fr-runtime-001-ac-02"></a>
* `claude`
<a id="fr-runtime-001-ac-03"></a>
* `codex`

偵測項目：

<a id="fr-runtime-001-ac-04"></a>
* Binary 路徑
<a id="fr-runtime-001-ac-05"></a>
* 是否可執行
<a id="fr-runtime-001-ac-06"></a>
* 版本資訊
<a id="fr-runtime-001-ac-07"></a>
* 執行使用者是否可使用
<a id="fr-runtime-001-ac-08"></a>
* 最後檢查時間

<a id="fr-runtime-002"></a>
## FR-RUNTIME-002 Runtime 選擇

<a id="fr-runtime-002-ac-01"></a>
建立 Session 時使用者必須選擇：

<a id="fr-runtime-002-ac-02"></a>
* Claude
<a id="fr-runtime-002-ac-03"></a>
* Codex

若 Runtime 不可用：

<a id="fr-runtime-002-ac-04"></a>
* 選項應顯示 Disabled。
<a id="fr-runtime-002-ac-05"></a>
* 顯示不可用原因。
<a id="fr-runtime-002-ac-06"></a>
* 不可送出建立 Session 請求。

<a id="fr-runtime-003"></a>
## FR-RUNTIME-003 Runtime 白名單

<a id="fr-runtime-003-ac-01"></a>
前端不得直接傳入任意 Command。

Daemon 僅接受預先設定的 Runtime ID：

```text
claude
codex
```

Daemon 根據 Runtime ID 產生實際執行命令。

<a id="fr-runtime-003-ac-02"></a>
Runtime 的啟動參數由 Daemon 端固定決定；前端、Central 與協定訊息均不得指定參數、
旗標、環境變數或 Entrypoint。Node 僅能以布林開關既定的參數集，不得指定其內容。
（範圍變更 2026-08-01，ADR 0023。）

<a id="fr-runtime-004"></a>
## FR-RUNTIME-004 Runtime 設定

<a id="fr-runtime-004-ac-01"></a>
Daemon 設定檔可指定：

```yaml
runtime:
  claude:
    enabled: true
    binary: /usr/local/bin/claude

  codex:
    enabled: true
    binary: /usr/local/bin/codex
    sandbox_bypass: true
```

<a id="fr-runtime-004-ac-02"></a>
`codex` Runtime 於 Node 上預設在停用核准流程與沙箱的狀態下執行
（`sandbox_bypass` 缺項即為啟用）。此為可丟棄之隔離 VM 的預期姿態（ADR 0023）。

<a id="fr-runtime-004-ac-03"></a>
Node 得以 `sandbox_bypass: false` 關閉此預設；平台無任何路徑可覆寫該設定。

<a id="fr-runtime-004-ac-04"></a>
Runtime 的實際沙箱狀態須回報平台並於介面顯示。若 Node 要求停用而已安裝的 CLI
不接受該參數，回報與顯示均須為「沙箱啟用」，不得顯示未實際發生的狀態。

---

# 8.5 Workspace 管理

<a id="fr-workspace-001"></a>
## FR-WORKSPACE-001 Workspace Root

<a id="fr-workspace-001-ac-01"></a>
Daemon 應設定一個或多個允許的 Workspace Root。

例如：

```yaml
workspace:
  allowed_roots:
    - /home/neil/projects
    - /srv/projects
```

<a id="fr-workspace-002"></a>
## FR-WORKSPACE-002 Workspace 瀏覽

<a id="fr-workspace-002-ac-01"></a>
使用者可在前端逐層展開 Workspace Root。

每筆目錄資料包含：

<a id="fr-workspace-002-ac-02"></a>
* 名稱
<a id="fr-workspace-002-ac-03"></a>
* 完整路徑
<a id="fr-workspace-002-ac-04"></a>
* 類型
<a id="fr-workspace-002-ac-05"></a>
* 修改時間
<a id="fr-workspace-002-ac-06"></a>
* 是否隱藏
<a id="fr-workspace-002-ac-07"></a>
* 是否可讀

<a id="fr-workspace-003"></a>
## FR-WORKSPACE-003 指定工作目錄

<a id="fr-workspace-003-ac-01"></a>
建立 Session 時，使用者可選擇 Allowed Root 下的任意合法目錄。

Daemon 必須驗證：

<a id="fr-workspace-003-ac-02"></a>
* 目錄存在。
<a id="fr-workspace-003-ac-03"></a>
* 目錄可讀。
<a id="fr-workspace-003-ac-04"></a>
* 執行使用者具備必要權限。
<a id="fr-workspace-003-ac-05"></a>
* 目錄位於 Allowed Root。
<a id="fr-workspace-003-ac-06"></a>
* Symlink 解析後仍位於 Allowed Root。

<a id="fr-workspace-004"></a>
## FR-WORKSPACE-004 最近使用 Workspace

<a id="fr-workspace-004-ac-01"></a>
系統應記錄使用者最近使用的 Workspace。

建立 Session 時可快速選擇：

<a id="fr-workspace-004-ac-02"></a>
* 最近使用
<a id="fr-workspace-004-ac-03"></a>
* 收藏 Workspace
<a id="fr-workspace-004-ac-04"></a>
* 目錄瀏覽

<a id="fr-workspace-005"></a>
## FR-WORKSPACE-005 Workspace 收藏

<a id="fr-workspace-005-ac-01"></a>
使用者可收藏常用 Workspace。

收藏資料：

<a id="fr-workspace-005-ac-02"></a>
* User ID
<a id="fr-workspace-005-ac-03"></a>
* Node ID
<a id="fr-workspace-005-ac-04"></a>
* Workspace Path
<a id="fr-workspace-005-ac-05"></a>
* Display Name
<a id="fr-workspace-005-ac-06"></a>
* 建立時間

---

# 8.5.1 系統終端機

<a id="fr-shell-001"></a>
## FR-SHELL-001 系統終端機

系統終端機是 Session 工作區中的一個互動式 Shell，供使用者直接在 Node 上操作。
範圍變更與取捨見 ADR 0021。

<a id="fr-shell-001-ac-01"></a>
Node 可停用系統終端機；停用後該 Node 上不得開啟。

<a id="fr-shell-001-ac-02"></a>
僅持有 `terminal.shell` 的使用者，且僅於自己擁有的 Session 上，可開啟系統終端機。

<a id="fr-shell-001-ac-03"></a>
前端僅指定 Runtime ID，不得指定 Binary、Command 或 Shell 指令字串。

<a id="fr-shell-001-ac-04"></a>
系統終端機綁定於一個 CLI Session；該 Session 結束時一併結束。

<a id="fr-shell-001-ac-05"></a>
其他使用者（含 Admin）不得連線至他人的系統終端機。

<a id="fr-shell-001-ac-06"></a>
系統終端機的建立、連線與終止須留下稽核紀錄；終端機內容不得寫入資料庫或 Log。

<a id="fr-shell-001-ac-07"></a>
系統終端機計入 Node 與使用者的 Session 上限。

<a id="fr-shell-001-ac-08"></a>
關閉終端機或離開 Session 工作區時，系統終端機即終止。

<a id="fr-shell-001-ac-09"></a>
系統終端機可經 sudo 取得 root 時，介面須明示該 Node 的提權姿態。
（新增 2026-08-01，ADR 0023：ADR 0021 §4.2 以「Daemon 非 root」為補償控制，
該條在提權姿態下不再成立，可見性即為其替代。）

---

# 8.6 Session 管理

<a id="fr-session-001"></a>
## FR-SESSION-001 建立 Session

<a id="fr-session-001-ac-01"></a>
建立 Session 必填欄位：

<a id="fr-session-001-ac-02"></a>
* Node
<a id="fr-session-001-ac-03"></a>
* Runtime
<a id="fr-session-001-ac-04"></a>
* Workspace
<a id="fr-session-001-ac-05"></a>
* Session 名稱

選填欄位：

<a id="fr-session-001-ac-06"></a>
* Terminal Rows
<a id="fr-session-001-ac-07"></a>
* Terminal Columns
<a id="fr-session-001-ac-08"></a>
* 啟動參數
<a id="fr-session-001-ac-09"></a>
* 環境變數 Profile

第一階段不允許任意自訂 CLI 啟動參數。

<a id="fr-session-002"></a>
## FR-SESSION-002 Session 狀態

<a id="fr-session-002-ac-01"></a>
Session 狀態至少包含：

```text
STARTING
RUNNING
DISCONNECTED
EXITED
FAILED
TERMINATING
TERMINATED
```

<a id="fr-session-003"></a>
## FR-SESSION-003 Session 列表

<a id="fr-session-003-ac-01"></a>
列表顯示：

<a id="fr-session-003-ac-02"></a>
* Session 名稱
<a id="fr-session-003-ac-03"></a>
* Node
<a id="fr-session-003-ac-04"></a>
* Runtime
<a id="fr-session-003-ac-05"></a>
* Workspace
<a id="fr-session-003-ac-06"></a>
* 建立者
<a id="fr-session-003-ac-07"></a>
* 狀態
<a id="fr-session-003-ac-08"></a>
* PID
<a id="fr-session-003-ac-09"></a>
* 開始時間
<a id="fr-session-003-ac-10"></a>
* 最後活動時間

<a id="fr-session-004"></a>
## FR-SESSION-004 Session 詳情

<a id="fr-session-004-ac-01"></a>
Session 詳情顯示：

<a id="fr-session-004-ac-02"></a>
* Session metadata
<a id="fr-session-004-ac-03"></a>
* Web Terminal
<a id="fr-session-004-ac-04"></a>
* Workspace 檔案樹
<a id="fr-session-004-ac-05"></a>
* Runtime
<a id="fr-session-004-ac-06"></a>
* Node
<a id="fr-session-004-ac-07"></a>
* Workspace
<a id="fr-session-004-ac-08"></a>
* 開始時間
<a id="fr-session-004-ac-09"></a>
* 最後活動時間
<a id="fr-session-004-ac-10"></a>
* 結束原因

<a id="fr-session-005"></a>
## FR-SESSION-005 終止 Session

<a id="fr-session-005-ac-01"></a>
有權限的使用者可終止 Session。

流程：

<a id="fr-session-005-ac-02"></a>
1. 前端送出終止請求。
<a id="fr-session-005-ac-03"></a>
2. 中央平台轉送至 Daemon。
<a id="fr-session-005-ac-04"></a>
3. Daemon先送出正常終止信號。
<a id="fr-session-005-ac-05"></a>
4. 等待指定秒數。
<a id="fr-session-005-ac-06"></a>
5. 若未結束，送出強制終止。
<a id="fr-session-005-ac-07"></a>
6. 更新 Session 狀態。

<a id="fr-session-006"></a>
## FR-SESSION-006 Session 重新連線

<a id="fr-session-006-ac-01"></a>
Session 在瀏覽器斷線後不得自動終止。

使用者應可重新附加至執行中的 Session。

<a id="fr-session-007"></a>
## FR-SESSION-007 多人連線限制

<a id="fr-session-007-ac-01"></a>
MVP 建議採用：

<a id="fr-session-007-ac-02"></a>
* 同一 Session 僅允許一個可寫入連線。
<a id="fr-session-007-ac-03"></a>
* 其他使用者可唯讀觀看。
<a id="fr-session-007-ac-04"></a>
* 新使用者要求控制權時，需明確接管。

避免多人同時輸入造成 CLI 狀態混亂。

---

# 8.7 Terminal 功能

<a id="fr-term-001"></a>
## FR-TERM-001 Terminal 顯示

<a id="fr-term-001-ac-01"></a>
前端使用 xterm.js 顯示完整 ANSI Terminal。

必須支援：

<a id="fr-term-001-ac-02"></a>
* ANSI 色彩
<a id="fr-term-001-ac-03"></a>
* Cursor
<a id="fr-term-001-ac-04"></a>
* Interactive Prompt
<a id="fr-term-001-ac-05"></a>
* 中文輸入
<a id="fr-term-001-ac-06"></a>
* UTF-8
<a id="fr-term-001-ac-07"></a>
* Ctrl+C
<a id="fr-term-001-ac-08"></a>
* Ctrl+D
<a id="fr-term-001-ac-09"></a>
* Tab
<a id="fr-term-001-ac-10"></a>
* 方向鍵
<a id="fr-term-001-ac-11"></a>
* Page Up／Page Down
<a id="fr-term-001-ac-12"></a>
* CLI 原生審批選單

Terminal 的可用尺寸必須等於它被分配到的容器尺寸。以下兩條以量測表述，因為
「看起來對」在這件事上不可靠：面板可以在所有測試皆綠的情況下只用掉一半高度。

<a id="fr-term-001-ac-13"></a>
* Terminal 面板必須填滿中央工作區的可用高度：終端機畫面高度不低於面板可用高度的
  90%（其餘為不足一列的餘量），且在 1440×900 下可顯示的列數不少於 30 列。

<a id="fr-term-001-ac-14"></a>
* Session 工作區不得因版面高度計算而產生整頁滾動；Terminal 的可用高度必須來自
  容器的實際高度，而非任何頁面自行推導的公式。

<a id="fr-term-002"></a>
## FR-TERM-002 Terminal 輸入

<a id="fr-term-002-ac-01"></a>
前端輸入應以低延遲 WebSocket 傳送至中央平台，再轉送至 Daemon PTY。

<a id="fr-term-003"></a>
## FR-TERM-003 Terminal Resize

<a id="fr-term-003-ac-01"></a>
瀏覽器尺寸變更時，前端需通知 Daemon：

<a id="fr-term-003-ac-02"></a>
* Rows
<a id="fr-term-003-ac-03"></a>
* Columns

Daemon 應調整 PTY Size。

<a id="fr-term-004"></a>
## FR-TERM-004 Terminal Scrollback

<a id="fr-term-004-ac-01"></a>
重新連線時應提供最近的終端輸出。

MVP 採用 tmux Scrollback：

<a id="fr-term-004-ac-02"></a>
* 使用 tmux Scrollback。
<a id="fr-term-004-ac-04"></a>
* Daemon 的 tmux Scrollback 至少保存 5000 行。
<a id="fr-term-004-ac-05"></a>
* 重新連線送出的 Scrollback 快照上限為 2 MB；超出時保留最新的部分並標示為截斷。

<a id="fr-term-004-ac-03"></a>
* ~~Daemon 保存 2 MB 至 10 MB Ring Buffer。~~（已作廢：未採用的替代方案。實際保證見上列以行數與快照上限表述的條件。）

<a id="fr-term-004-ac-06"></a>
* 使用者須能於瀏覽器中向上檢視終端機的既有輸出，並可回到即時輸出。
  （新增 2026-08-01，ADR 0023：在此之前 tmux 預設 `history-limit` 為 2000 行，
  且滑鼠滾輪被轉譯為方向鍵，因此 AC-04 實際上並未成立。）

<a id="fr-term-004-ac-07"></a>
* 重新連線快照為連續性機制，不作為使用者檢視歷史輸出的途徑；
  使用者可檢視的 Scrollback 為 Daemon 端 tmux 的 History。

<a id="fr-term-005"></a>
## FR-TERM-005 Terminal 連線狀態

<a id="fr-term-005-ac-01"></a>
前端需顯示：

<a id="fr-term-005-ac-02"></a>
* Connected
<a id="fr-term-005-ac-03"></a>
* Reconnecting
<a id="fr-term-005-ac-04"></a>
* Disconnected
<a id="fr-term-005-ac-05"></a>
* Session Exited

<a id="fr-term-006"></a>
## FR-TERM-006 自動重連

<a id="fr-term-006-ac-01"></a>
WebSocket 中斷時，前端應自動重連。

建議重試：

<a id="fr-term-006-ac-02"></a>
* 1 秒
<a id="fr-term-006-ac-03"></a>
* 2 秒
<a id="fr-term-006-ac-04"></a>
* 5 秒
<a id="fr-term-006-ac-05"></a>
* 10 秒
<a id="fr-term-006-ac-06"></a>
* 最大 30 秒間隔

---

# 8.8 檔案總覽

<a id="fr-file-001"></a>
## FR-FILE-001 檔案樹

<a id="fr-file-001-ac-01"></a>
前端需以 Tree 呈現 Workspace。

每個節點顯示：

<a id="fr-file-001-ac-02"></a>
* 檔案或資料夾名稱
<a id="fr-file-001-ac-03"></a>
* 圖示
<a id="fr-file-001-ac-04"></a>
* 是否可展開
<a id="fr-file-001-ac-05"></a>
* 修改狀態
<a id="fr-file-001-ac-06"></a>
* 大小
<a id="fr-file-001-ac-07"></a>
* 修改時間

目錄採延遲載入，不一次掃描完整 Workspace。

<a id="fr-file-002"></a>
## FR-FILE-002 檔案預覽

<a id="fr-file-002-ac-01"></a>
使用者點擊檔案後，系統應以 Monaco Editor 唯讀顯示。

支援：

<a id="fr-file-002-ac-02"></a>
* 語法高亮
<a id="fr-file-002-ac-03"></a>
* 行號
<a id="fr-file-002-ac-04"></a>
* 自動換行
<a id="fr-file-002-ac-05"></a>
* 複製
<a id="fr-file-002-ac-06"></a>
* 搜尋
<a id="fr-file-002-ac-07"></a>
* 重新整理
<a id="fr-file-002-ac-08"></a>
* 跳至指定行

<a id="fr-file-003"></a>
## FR-FILE-003 檔案大小限制

<a id="fr-file-003-ac-01"></a>
預設最大預覽大小：

```text
2 MB
```

超過限制時：

<a id="fr-file-003-ac-02"></a>
* 不直接讀取。
<a id="fr-file-003-ac-03"></a>
* 顯示檔案過大。
<a id="fr-file-003-ac-04"></a>
* 顯示檔案大小。
<a id="fr-file-003-ac-05"></a>
* 第一階段不提供完整載入。

<a id="fr-file-004"></a>
## FR-FILE-004 Binary 判斷

<a id="fr-file-004-ac-01"></a>
若檔案被判斷為 Binary：

<a id="fr-file-004-ac-02"></a>
* 不顯示原始內容。
<a id="fr-file-004-ac-03"></a>
* 顯示「不支援預覽」。
<a id="fr-file-004-ac-04"></a>
* 顯示 MIME Type、大小與修改時間。

判定方式（2026-08-01 修訂，取代 `research/tech.md` §11.6 原本的「讀取前 8 KB」）：

* 判定範圍是**已讀取的完整內容**（受 `max_preview_size` 約束），不是前 8 KB 的窗格。
  窗格會切在多位元組字元中間而誤判合法的 UTF-8 文字檔，也會漏看窗格之後的二進位內容。
* 「無法以 UTF-8 解讀」與「二進位」是兩件事，畫面上必須分開說明：前者的下一步是轉編碼，
  後者的下一步是別看了。
* 準確度本身是一條需求，見 `FR-FILE-008`。

<a id="fr-file-005"></a>
## FR-FILE-005 敏感檔案保護

<a id="fr-file-005-ac-01"></a>
預設禁止預覽：

```text
.env
.env.*
*.pem
*.key
id_rsa
id_ed25519
*.p12
*.pfx
credentials*
secrets*
```

系統應允許管理員調整規則。

<a id="fr-file-006"></a>
## FR-FILE-006 檔案重新整理

<a id="fr-file-006-ac-01"></a>
檔案樹應提供：

<a id="fr-file-006-ac-02"></a>
* 重新整理目前目錄。
<a id="fr-file-006-ac-03"></a>
* 重新整理檔案內容。
<a id="fr-file-006-ac-04"></a>
* Session 執行時可選擇自動刷新。

MVP 不要求即時監控所有檔案異動。

<a id="fr-file-007"></a>
## FR-FILE-007 檔案搜尋

<a id="fr-file-007-ac-01"></a>
MVP 可提供檔名搜尋。

輸入：

<a id="fr-file-007-ac-02"></a>
* Keyword
<a id="fr-file-007-ac-03"></a>
* Workspace
<a id="fr-file-007-ac-04"></a>
* 最大結果數

回傳：

<a id="fr-file-007-ac-05"></a>
* 完整路徑
<a id="fr-file-007-ac-06"></a>
* 名稱
<a id="fr-file-007-ac-07"></a>
* 類型
<a id="fr-file-007-ac-08"></a>
* 修改時間

全文內容搜尋可列入後續版本。

<a id="fr-file-008"></a>
## FR-FILE-008 文字判定準確度

<a id="fr-file-008-ac-01"></a>
完全合法的 UTF-8 文字檔不得被判為不可預覽，與檔案大小無關。

<a id="fr-file-008-ac-02"></a>
含 ANSI escape sequence 的文字檔（終端機輸出、建置 log）視為文字。

<a id="fr-file-008-ac-03"></a>
含 NUL 位元組的檔案一律不可預覽，與該位元組出現在檔案何處無關。

<a id="fr-file-008-ac-04"></a>
判定必須有一份可執行的分類 corpus，且 corpus 全數符合期望。

<a id="fr-file-008-ac-05"></a>
2 MiB 檔案的判定耗時不得超過 5 ms。

<a id="fr-file-009"></a>
## FR-FILE-009 圖片投放

使用者可從瀏覽器把一張圖片交給 Session 所在節點，供 CLI 讀取。

<a id="fr-file-009-ac-01"></a>
持有 `file.upload` 的使用者可從瀏覽器把一張圖片交給 Session 所在節點。

<a id="fr-file-009-ac-02"></a>
支援貼上、拖放、挑檔三種入口，三者行為一致。

<a id="fr-file-009-ac-03"></a>
落地路徑與檔名由 Daemon 決定；請求不得包含檔名、路徑或目錄。

<a id="fr-file-009-ac-04"></a>
僅接受 PNG、JPEG、GIF、WebP，且以內容而非宣告的型別判定。

<a id="fr-file-009-ac-05"></a>
單張 4 MiB、每 Session 64 MiB、每日 200 張上限，逾越時明確拒絕且不落地。

<a id="fr-file-009-ac-06"></a>
上傳成功後，工作區相對路徑以 Writer 身分送入終端機輸入行，不自動送出。

<a id="fr-file-009-ac-07"></a>
每次上傳留下稽核紀錄（使用者、Session、節點、MIME、位元組數、相對路徑）。

<a id="fr-file-009-ac-08"></a>
節點可停用此功能並回報；停用時前端不顯示投放入口。

<a id="fr-file-009-ac-09"></a>
逾期（7 天）的上傳檔案由 Daemon 清除。

<a id="fr-file-010"></a>
## FR-FILE-010 檔案上傳

使用者可從瀏覽器把檔案放進 Session 工作區內指定的目錄，供 CLI 使用。

與 `FR-FILE-009`（圖片投放）是兩條不同的路徑：那一條由 Daemon 決定落地位置與檔名，
只接受四種圖片；這一條由使用者指定目錄與檔名，不限型別，但永不覆寫既有項目。

**兩條路徑都只會「新增」檔案。** 前端不提供刪除、更名或編輯，而這是**產品決定**
而非未實作：要刪除或取代工作區裡的檔案，一律在該 Node 上以終端機操作
（含圖片投放寫進 `.cliora/uploads/` 的圖片）。因此本需求沒有 undo，
也不需要版本前提 —— 沒有任何既有位元組會被動到。

<a id="fr-file-010-ac-01"></a>
持有 `file.upload` 的使用者可將檔案上傳至 Session 工作區內指定的目錄。

<a id="fr-file-010-ac-02"></a>
支援拖放至檔案樹的目錄列與工具列挑檔兩個入口，兩者行為一致。

<a id="fr-file-010-ac-03"></a>
檔名沿用使用者提供的名稱；名稱不得含路徑分隔符號或控制字元。

<a id="fr-file-010-ac-04"></a>
目的地必須是工作區內既有的目錄；不得建立目錄。

<a id="fr-file-010-ac-05"></a>
同名項目已存在時拒絕，且不得改動既有檔案。

<a id="fr-file-010-ac-06"></a>
敏感檔案規則（`FR-FILE-005`）適用於上傳的目的地與檔名。

<a id="fr-file-010-ac-07"></a>
`.git/`（含 worktree 中作為檔案存在的 `.git`）與平台自有目錄不得作為目的地。

<a id="fr-file-010-ac-08"></a>
落地檔案權限為 `0644`，不得可執行。

<a id="fr-file-010-ac-09"></a>
單檔、每 Session 累計、每日檔數與節點可用空間四項上限，逾越時明確拒絕且不落地。

<a id="fr-file-010-ac-10"></a>
每次上傳留下稽核紀錄（使用者、Session、節點、相對路徑、位元組數），不記內容。

<a id="fr-file-010-ac-11"></a>
節點可停用此功能並回報；停用時前端不顯示上傳入口。

<a id="fr-file-010-ac-12"></a>
不支援資料夾上傳，且必須明確拒絕而非部分處理。

---

# 8.9 Daemon 與中央通訊

<a id="fr-conn-001"></a>
## FR-CONN-001 主動連線

<a id="fr-conn-001-ac-01"></a>
Daemon 必須主動建立至中央平台的 WebSocket 連線。

中央平台不得依賴 SSH 主動連入 VM。

<a id="fr-conn-002"></a>
## FR-CONN-002 TLS

<a id="fr-conn-002-ac-01"></a>
正式環境所有通訊必須使用：

```text
HTTPS
WSS
```

<a id="fr-conn-003"></a>
## FR-CONN-003 自動重連

<a id="fr-conn-003-ac-01"></a>
Daemon 與中央斷線後，應持續重連。

建議 Backoff：

<a id="fr-conn-003-ac-02"></a>
* 1 秒
<a id="fr-conn-003-ac-03"></a>
* 2 秒
<a id="fr-conn-003-ac-04"></a>
* 5 秒
<a id="fr-conn-003-ac-05"></a>
* 10 秒
<a id="fr-conn-003-ac-06"></a>
* 30 秒
<a id="fr-conn-003-ac-07"></a>
* 最大 60 秒

<a id="fr-conn-004"></a>
## FR-CONN-004 訊息請求識別

<a id="fr-conn-004-ac-01"></a>
所有請求與回應需包含：

<a id="fr-conn-004-ac-02"></a>
* Message Type
<a id="fr-conn-004-ac-03"></a>
* Request ID
<a id="fr-conn-004-ac-04"></a>
* Node ID
<a id="fr-conn-004-ac-05"></a>
* Timestamp
<a id="fr-conn-004-ac-06"></a>
* Payload

<a id="fr-conn-005"></a>
## FR-CONN-005 Terminal Binary Frame

<a id="fr-conn-005-ac-01"></a>
Terminal 輸出建議使用 Binary WebSocket Frame。

控制訊息使用 JSON。

<a id="fr-conn-006"></a>
## FR-CONN-006 命令逾時

<a id="fr-conn-006-ac-01"></a>
Workspace 與 Session 控制請求需設定 Timeout。

每一類操作各有自己的預算，逾時即放棄並回報，不無限等待 Daemon：

<a id="fr-conn-006-ac-03"></a>
* 目錄列出：15 秒。
<a id="fr-conn-006-ac-04"></a>
* 檔案讀取：15 秒。
<a id="fr-conn-006-ac-05"></a>
* Session 啟動：30 秒。
<a id="fr-conn-006-ac-06"></a>
* Session 接管與列出：15 秒。
<a id="fr-conn-006-ac-07"></a>
* Session 終止：20 秒。
<a id="fr-conn-006-ac-08"></a>
* Daemon 更新：180 秒（下載、替換與重啟遠長於其他操作，共用一般預算會在正常情況下逾時）。

<a id="fr-conn-006-ac-09"></a>
* 建立埠轉發隧道：20 秒（涵蓋 SSH 交握、服務商指派網址與 Daemon 解析；其中第二段不由平台掌握，
  因此預算較寬，且 Daemon 端的等待刻意更短，讓先放棄的一方是知道原因的那一方）。
<a id="fr-conn-006-ac-10"></a>
* 關閉埠轉發隧道：10 秒（僅為 Node 上的本機工作——結束子行程並回收——完全不觸及服務商，
  因此是最短的一項。平台自己的紀錄在送出此訊息前已寫定，逾時不代表未關閉：Daemon 仍會在 TTL
  結束該子行程，並在重啟時回收孤兒行程）。

<a id="fr-conn-006-ac-11"></a>
* 圖片投放：20 秒（比檔案讀取略長，因為 Node 端要寫入磁碟並 fsync 之後才回覆；
  仍為有上限的等待，讓卡住的 Node 呈現為 `REQUEST_TIMEOUT` 而不是永遠轉圈的瀏覽器）。

<a id="fr-conn-006-ac-02"></a>
* ~~一般控制命令：10 秒。~~（已作廢：不存在單一「一般控制命令」預算，改由上列逐項規範。）

---

# 8.10 埠轉發預覽

埠轉發預覽讓使用者把 Node 上某個 port 的 Web 應用轉出，於瀏覽器中檢視。
本能力以第三方隧道服務整合交付，流量不經過平台；範圍與取捨見 ADR 0022 與 `SCOPE-013`。

<a id="fr-tunnel-001"></a>
## FR-TUNNEL-001 埠轉發隧道

<a id="fr-tunnel-001-ac-01"></a>
埠轉發整合須由平台管理員啟用；Node 得於本機停用該功能，且該停用不得被平台覆寫。

<a id="fr-tunnel-001-ac-02"></a>
持有 `tunnel.manage` 的使用者可為已啟用的 Node 指定一個 port，平台顯示服務商回傳的網址。

<a id="fr-tunnel-001-ac-03"></a>
目標位址固定為該 Node 的 loopback；port 須大於等於 1024 且在該 Node 的允許範圍內。

<a id="fr-tunnel-001-ac-04"></a>
隧道不得在 Node 上開啟任何對外監聽埠；對外連線一律由 Daemon 主動建立。

<a id="fr-tunnel-001-ac-05"></a>
隧道有存活上限，可明確關閉；關閉後平台不再顯示該網址。

<a id="fr-tunnel-001-ac-06"></a>
網址由服務商決定且可能變更；變更後平台須在介面上更新。

<a id="fr-tunnel-001-ac-07"></a>
建立與關閉須留下稽核紀錄；流量內容不經過平台，平台亦不記錄。

<a id="fr-tunnel-001-ac-08"></a>
Node 上不得殘留已關閉隧道的行程。

<a id="fr-tunnel-002"></a>
## FR-TUNNEL-002 隧道保護

<a id="fr-tunnel-002-ac-01"></a>
建立隧道時必須選擇一種保護方式：密碼保護、來源 IP 限制或公開。

<a id="fr-tunnel-002-ac-02"></a>
密碼保護的密碼由平台產生，僅於建立時顯示一次，不以明文儲存。

<a id="fr-tunnel-002-ac-03"></a>
選擇「公開」須經一次明確確認並記錄。

<a id="fr-tunnel-002-ac-04"></a>
僅持有 `tunnel.view` 的使用者可在平台內看到隧道網址；唯讀使用者不得看到。

<a id="fr-tunnel-002-ac-05"></a>
使用者於首次為某 Node 建立隧道時，須確認已知悉流量將經由第三方服務轉送。

<a id="fr-tunnel-003"></a>
## FR-TUNNEL-003 傳輸與依賴

<a id="fr-tunnel-003-ac-01"></a>
與服務商的連線須驗證其主機金鑰，不得停用驗證。

<a id="fr-tunnel-003-ac-02"></a>
隧道僅接受加密的外部連入。

<a id="fr-tunnel-003-ac-03"></a>
服務商不可用、憑證無效與主機金鑰不符須顯示為可區分的狀態。

<a id="fr-tunnel-003-ac-04"></a>
Node 可自我診斷埠轉發的先決條件：用戶端存在、對外連線可達、主機金鑰已佈署、本機未停用。

<a id="fr-tunnel-004"></a>
## FR-TUNNEL-004 整合設定與憑證保管

<a id="fr-tunnel-004-ac-01"></a>
埠轉發整合由平台管理員在系統整合設定中啟用；未啟用時不得建立隧道。

<a id="fr-tunnel-004-ac-02"></a>
服務商憑證由使用者自行取得並提供；平台不代管其帳號，亦不呼叫其管理介面。

<a id="fr-tunnel-004-ac-03"></a>
服務商憑證須加密儲存，且不得由任何介面回傳；僅得顯示其指紋。

<a id="fr-tunnel-004-ac-04"></a>
環境未具備憑證加密能力時，不得啟用整合，亦不得以明文儲存憑證。

<a id="fr-tunnel-004-ac-05"></a>
每個 Node 有獨立的埠轉發設定；平台設定與 Node 本機設定只能取交集，Node 的停用不得被平台覆寫。

<a id="fr-tunnel-004-ac-06"></a>
整合的啟用、停用、憑證設定與 Node 設定變更均須留下稽核紀錄；憑證內容不得出現於紀錄中。

---

# 9. 通訊協定

## 9.1 Node 註冊

```json
{
  "type": "node.register",
  "request_id": "req_001",
  "payload": {
    "name": "dev-vm-01",
    "hostname": "dev-vm-01",
    "os": "linux",
    "os_version": "Ubuntu 24.04",
    "architecture": "amd64",
    "daemon_version": "1.0.0",
    "run_user": "neil",
    "runtimes": [
      {
        "name": "claude",
        "available": true,
        "version": "x.x.x",
        "binary": "/usr/local/bin/claude"
      },
      {
        "name": "codex",
        "available": true,
        "version": "x.x.x",
        "binary": "/usr/local/bin/codex"
      }
    ],
    "workspace_roots": [
      "/home/neil/projects",
      "/srv/projects"
    ]
  }
}
```

## 9.2 Heartbeat

```json
{
  "type": "node.heartbeat",
  "payload": {
    "active_sessions": 2,
    "cpu_usage": 22.4,
    "memory_usage": 48.1,
    "timestamp": "2026-07-20T19:30:00+08:00"
  }
}
```

## 9.3 建立 Session

```json
{
  "type": "session.start",
  "request_id": "req_100",
  "payload": {
    "session_id": "ses_001",
    "runtime": "claude",
    "workspace": "/home/neil/projects/fleet-platform",
    "rows": 40,
    "columns": 140
  }
}
```

## 9.4 建立成功

```json
{
  "type": "session.started",
  "request_id": "req_100",
  "payload": {
    "session_id": "ses_001",
    "pid": 18342,
    "runtime": "claude",
    "workspace": "/home/neil/projects/fleet-platform"
  }
}
```

## 9.5 Terminal 輸入

```json
{
  "type": "terminal.input",
  "payload": {
    "session_id": "ses_001",
    "data": "請檢查目前專案架構\r"
  }
}
```

## 9.6 Terminal Resize

```json
{
  "type": "terminal.resize",
  "payload": {
    "session_id": "ses_001",
    "rows": 45,
    "columns": 160
  }
}
```

## 9.7 目錄列表

```json
{
  "type": "filesystem.list",
  "request_id": "req_201",
  "payload": {
    "session_id": "ses_001",
    "path": "/home/neil/projects/fleet-platform"
  }
}
```

## 9.8 讀取檔案

```json
{
  "type": "filesystem.read",
  "request_id": "req_202",
  "payload": {
    "session_id": "ses_001",
    "path": "/home/neil/projects/fleet-platform/backend/main.py"
  }
}
```

---

# 10. 前端頁面規劃

# 10.1 登入頁

內容：

* Logo
* 帳號
* 密碼
* 登入按鈕
* 錯誤提示

# 10.2 Dashboard

顯示：

* Online Nodes
* Offline Nodes
* Running Sessions
* Claude Sessions
* Codex Sessions
* 最近活動
* 異常 Node

# 10.3 Nodes 頁

列表欄位：

* Node 名稱
* 狀態
* Hostname
* OS
* Claude
* Codex
* Session 數量
* 最後在線時間
* 操作

操作：

* 查看
* 建立 Session
* 停用
* 移除

# 10.4 Node 詳情頁

區塊：

1. Node 基本資訊。
2. Runtime 狀態。
3. Workspace Root。
4. 目前 Session。
5. Daemon 資訊。
6. 系統資源。
7. 最近錯誤。

# 10.5 建立 Session Modal

欄位：

* Node
* Runtime
* Workspace
* Session 名稱
* Terminal Size

操作：

* 取消
* 啟動

# 10.6 Session 工作區

兩欄布局，中央區以 Tab 切換：

```text
┌──────────────────────────────────────────┬──────────────────┐
│ ┌ CLI ┬ [檔名] ┐                          │ Workspace        │
│ │                                      │ │                  │
│ │  選中的 Tab 佔滿整個中央區              │ │ File Tree        │
│ │  CLI = xterm.js                      │ │                  │
│ └──────────────────────────────────────┘ │                  │
└──────────────────────────────────────────┴──────────────────┘
```

不提供 workspace 內的 Session 清單與切換：切換 Session 一律回到 Sessions 頁。
中央區不採上下分割——同時顯示 Terminal 與 Preview 會讓兩者都不足以操作。

頂部顯示：

* Session 名稱
* Node
* Runtime
* Workspace
* 狀態
* 重新連線
* 終止

中央區 Tab：

* CLI（恆存在，預設選中）
* 檔案預覽（開啟檔案時出現，同時最多一個，標籤為檔名）
* TERMINAL（系統終端機，符合 FR-SHELL-001.AC-01/AC-02 的條件時才出現）

右側 Workspace 區域提供：

* File Tree

# 10.7 安裝管理頁

內容：

* 建立 Enrollment Token。
* Token 狀態。
* 一行安裝指令。
* 支援平台。
* 安裝紀錄。
* Daemon 版本。

---

# 11. 後端 API

## 11.1 Authentication

```text
POST /api/auth/login
POST /api/auth/refresh
POST /api/auth/logout
GET  /api/auth/me
```

## 11.2 Nodes

```text
GET    /api/nodes
GET    /api/nodes/{node_id}
PATCH  /api/nodes/{node_id}
DELETE /api/nodes/{node_id}
```

## 11.3 Enrollment

```text
POST   /api/enrollment-tokens
GET    /api/enrollment-tokens
DELETE /api/enrollment-tokens/{token_id}
GET    /api/install-script
GET    /api/downloads/{filename}
```

## 11.4 Runtime

```text
GET /api/nodes/{node_id}/runtimes
```

## 11.5 Workspace

```text
GET /api/nodes/{node_id}/workspace/roots
GET /api/nodes/{node_id}/workspace/entries
GET /api/nodes/{node_id}/workspace/file
GET /api/nodes/{node_id}/workspace/search
```

## 11.6 Sessions

```text
POST   /api/sessions
GET    /api/sessions
GET    /api/sessions/{session_id}
POST   /api/sessions/{session_id}/attach
POST   /api/sessions/{session_id}/terminate
DELETE /api/sessions/{session_id}
```

## 11.7 WebSocket

```text
WS /ws/nodes/{node_id}
WS /ws/sessions/{session_id}/terminal
```

---

# 12. 資料模型

# 12.1 users

| 欄位            | 類型        | 說明     |
| ------------- | --------- | ------ |
| id            | UUID      | 使用者 ID |
| username      | varchar   | 登入帳號   |
| password_hash | varchar   | 密碼雜湊   |
| display_name  | varchar   | 顯示名稱   |
| role_id       | UUID      | 角色     |
| is_active     | boolean   | 是否啟用   |
| created_at    | timestamp | 建立時間   |
| updated_at    | timestamp | 更新時間   |

# 12.2 roles

| 欄位          | 類型        | 說明                     |
| ----------- | --------- | ---------------------- |
| id          | UUID      | 角色 ID                  |
| name        | varchar   | Admin／Developer／Viewer |
| permissions | jsonb     | 權限                     |
| created_at  | timestamp | 建立時間                   |

# 12.3 nodes

| 欄位             | 類型        | 說明               |
| -------------- | --------- | ---------------- |
| id             | UUID      | Node ID          |
| name           | varchar   | Node 名稱          |
| hostname       | varchar   | Hostname         |
| status         | varchar   | Online／Offline 等 |
| os             | varchar   | OS               |
| os_version     | varchar   | OS 版本            |
| architecture   | varchar   | amd64／arm64      |
| daemon_version | varchar   | Daemon 版本        |
| run_user       | varchar   | 執行使用者            |
| metadata       | jsonb     | 其他資訊             |
| last_seen_at   | timestamp | 最後在線             |
| registered_at  | timestamp | 註冊時間             |
| is_enabled     | boolean   | 是否啟用             |

# 12.4 node_runtimes

| 欄位          | 類型        | 說明           |
| ----------- | --------- | ------------ |
| id          | UUID      | ID           |
| node_id     | UUID      | Node         |
| runtime     | varchar   | claude／codex |
| available   | boolean   | 是否可用         |
| version     | varchar   | 版本           |
| binary_path | varchar   | Binary 路徑    |
| checked_at  | timestamp | 檢查時間         |

# 12.5 node_workspace_roots

| 欄位           | 類型      | 說明        |
| ------------ | ------- | --------- |
| id           | UUID    | ID        |
| node_id      | UUID    | Node      |
| path         | varchar | Root Path |
| display_name | varchar | 顯示名稱      |
| is_enabled   | boolean | 是否啟用      |

# 12.6 terminal_sessions

| 欄位               | 類型        | 說明               |
| ---------------- | --------- | ---------------- |
| id               | UUID      | Session ID       |
| node_id          | UUID      | Node             |
| user_id          | UUID      | 建立者              |
| name             | varchar   | Session 名稱       |
| runtime          | varchar   | claude／codex     |
| workspace        | varchar   | 工作目錄             |
| status           | varchar   | Session 狀態       |
| pid              | integer   | Process ID       |
| rows             | integer   | Terminal Rows    |
| columns          | integer   | Terminal Columns |
| started_at       | timestamp | 開始時間             |
| last_activity_at | timestamp | 最後活動             |
| ended_at         | timestamp | 結束時間             |
| exit_code        | integer   | Exit Code        |
| error_message    | text      | 錯誤               |

# 12.7 enrollment_tokens

| 欄位         | 類型        | 說明       |
| ---------- | --------- | -------- |
| id         | UUID      | Token ID |
| token_hash | varchar   | Token 雜湊 |
| created_by | UUID      | 建立者      |
| expires_at | timestamp | 過期時間     |
| max_uses   | integer   | 最大次數     |
| used_count | integer   | 已使用次數    |
| is_active  | boolean   | 是否有效     |
| created_at | timestamp | 建立時間     |

# 12.8 workspace_favorites

| 欄位           | 類型        | 說明        |
| ------------ | --------- | --------- |
| id           | UUID      | ID        |
| user_id      | UUID      | 使用者       |
| node_id      | UUID      | Node      |
| path         | varchar   | Workspace |
| display_name | varchar   | 顯示名稱      |
| created_at   | timestamp | 建立時間      |

# 12.9 audit_logs

| 欄位         | 類型        | 說明      |
| ---------- | --------- | ------- |
| id         | UUID      | ID      |
| user_id    | UUID      | 操作者     |
| node_id    | UUID      | Node    |
| session_id | UUID      | Session |
| action     | varchar   | 動作      |
| metadata   | jsonb     | 詳細資訊    |
| created_at | timestamp | 建立時間    |

---

# 13. Daemon 設定檔

```yaml
server:
  url: wss://platform.example.com/ws/nodes
  enrollment_token: enroll_xxxxx

node:
  name: dev-vm-01

runtime:
  claude:
    enabled: true
    binary: /usr/local/bin/claude

  codex:
    enabled: true
    binary: /usr/local/bin/codex

workspace:
  allowed_roots:
    - /home/neil/projects
    - /srv/projects

  excluded_patterns:
    - node_modules
    - .venv
    - dist
    - build
    - .git/objects

filesystem:
  max_preview_size: 2097152

  denied_files:
    - .env
    - .env.*
    - "*.pem"
    - "*.key"
    - id_rsa
    - id_ed25519

session:
  backend: tmux
  scrollback_limit: 10000

heartbeat:
  interval_seconds: 10
```

---

# 14. Daemon 模組

```text
agent-daemon/
├── cmd/
│   └── agentd/
│       └── main.go
├── internal/
│   ├── config/
│   ├── connection/
│   ├── heartbeat/
│   ├── protocol/
│   ├── runtime/
│   ├── terminal/
│   ├── session/
│   ├── workspace/
│   ├── filesystem/
│   ├── systeminfo/
│   ├── installer/
│   └── updater/
├── packaging/
│   └── systemd/
├── scripts/
│   └── install.sh
├── go.mod
└── go.sum
```

---

# 15. 安全需求

<a id="sec-001"></a>
## SEC-001 路徑隔離

<a id="sec-001-ac-01"></a>
所有 Workspace 與檔案路徑必須：

<a id="sec-001-ac-02"></a>
* 使用 Absolute Path。
<a id="sec-001-ac-03"></a>
* 解析 Symlink。
<a id="sec-001-ac-04"></a>
* 確認位於 Allowed Root。
<a id="sec-001-ac-05"></a>
* 拒絕 Path Traversal。
<a id="sec-001-ac-06"></a>
* 拒絕 Null Byte。
<a id="sec-001-ac-07"></a>
* 拒絕未授權 Root。

<a id="sec-002"></a>
## SEC-002 任意命令限制

<a id="sec-002-ac-01"></a>
前端不得直接指定 Command、Binary 或完整 Shell 指令。

僅可指定：

<a id="sec-002-ac-02"></a>
* Runtime ID
<a id="sec-002-ac-03"></a>
* Workspace
<a id="sec-002-ac-04"></a>
* Session Name
<a id="sec-002-ac-05"></a>
* Terminal Size

<a id="sec-003"></a>
## SEC-003 Token 保護

<a id="sec-003-ac-01"></a>
Enrollment Token：

<a id="sec-003-ac-02"></a>
* 不以明文保存於資料庫。
<a id="sec-003-ac-03"></a>
* 使用後可失效。
<a id="sec-003-ac-04"></a>
* 可設定過期時間。
<a id="sec-003-ac-05"></a>
* 可設定使用次數。

<a id="sec-004"></a>
## SEC-004 敏感檔案

<a id="sec-004-ac-01"></a>
敏感檔案預設不可透過 Web 預覽。

<a id="sec-005"></a>
## SEC-005 Transport Security

<a id="sec-005-ac-01"></a>
正式環境必須使用 TLS。

<a id="sec-006"></a>
## SEC-006 Audit

<a id="sec-006-ac-01"></a>
以下動作需記錄：

<a id="sec-006-ac-02"></a>
* Node 註冊。
<a id="sec-006-ac-03"></a>
* 建立 Session。
<a id="sec-006-ac-04"></a>
* 連線 Session。
<a id="sec-006-ac-05"></a>
* 終止 Session。
<a id="sec-006-ac-06"></a>
* 讀取敏感路徑失敗。
<a id="sec-006-ac-07"></a>
* 建立 Enrollment Token。
<a id="sec-006-ac-08"></a>
* 停用 Node。
<a id="sec-006-ac-09"></a>
* Daemon 更新。

<a id="sec-007"></a>
## SEC-007 執行使用者

<a id="sec-007-ac-01"></a>
Daemon 不應預設以 root 長期執行。

MVP 可指定既有開發使用者，例如：

```text
User=neil
Group=neil
```

安裝步驟需明確提示該 Daemon 將具備此 Linux 使用者的權限。

<a id="sec-007-ac-02"></a>
安裝步驟須明確提示：該 Node 的系統終端機可經 sudo 取得 root 權限，
且 codex 將在停用沙箱與核准流程下執行。此姿態須可於安裝時關閉。
（新增 2026-08-01，ADR 0023。AC-01「不應預設以 root 長期執行」不變且仍生效：
提權發生於終端機使用者執行 sudo 時，而非服務的執行身分。）

<a id="sec-007-ac-03"></a>
Node 的提權姿態與 Runtime 沙箱狀態須回報平台並於介面顯示；
平台不得以任何 API 或協定訊息變更之。

<a id="sec-008"></a>
## SEC-008 第三方隧道邊界

埠轉發預覽經由第三方服務轉送，因此其邊界須明文規範（ADR 0022）。

<a id="sec-008-ac-01"></a>
整合須由平台管理員明確啟用；未啟用時任何 Node 均不得建立隧道。

<a id="sec-008-ac-02"></a>
服務商憑證須加密儲存、不得由任何介面回傳、不得寫入 Node 磁碟，亦不得出現於紀錄中。

<a id="sec-008-ac-03"></a>
與服務商的連線須釘選其主機金鑰；不得以停用驗證的方式繞過金鑰不符。

<a id="sec-008-ac-04"></a>
每條隧道須具備一種保護方式；選擇公開須經明確確認並記錄。

<a id="sec-008-ac-05"></a>
平台設定與 Node 本機設定只能取交集；Node 的停用不得被平台覆寫。

<a id="sec-008-ac-06"></a>
服務商可見未加密的 HTTP 內容，因此此能力僅適用於預覽開發中的應用，不適用於存有真實資料的環境。

---

# 16. 非功能需求

<a id="nfr-001"></a>
## NFR-001 效能

<a id="nfr-001-ac-01"></a>
* Terminal 輸入至顯示的額外延遲目標小於 200 ms。
<a id="nfr-001-ac-02"></a>
* Node 列表載入時間小於 2 秒。
<a id="nfr-001-ac-03"></a>
* 目錄列表回應小於 2 秒。
<a id="nfr-001-ac-04"></a>
* 2 MB 以下檔案預覽小於 3 秒。

<a id="nfr-002"></a>
## NFR-002 可用性

<a id="nfr-002-ac-01"></a>
* Daemon 應自動重連。
<a id="nfr-002-ac-02"></a>
* 中央平台重啟後，Daemon 應重新註冊。
<a id="nfr-002-ac-03"></a>
* 瀏覽器中斷不得直接終止 CLI Session。
<a id="nfr-002-ac-04"></a>
* Session 狀態應可恢復。

<a id="nfr-003"></a>
## NFR-003 擴充性

<a id="nfr-003-ac-01"></a>
MVP 目標：

<a id="nfr-003-ac-02"></a>
* 100 個 Node。
<a id="nfr-003-ac-03"></a>
* 每個 Node 10 個同時 Session。
<a id="nfr-003-ac-04"></a>
* 全平台 500 個同時 Terminal WebSocket。

<a id="nfr-004"></a>
## NFR-004 可維運性

<a id="nfr-004-ac-01"></a>
Daemon 應：

<a id="nfr-004-ac-02"></a>
* 使用結構化 Log。
<a id="nfr-004-ac-03"></a>
* 支援 Log Level。
<a id="nfr-004-ac-04"></a>
* 提供 `agentd doctor`。
<a id="nfr-004-ac-05"></a>
* 提供版本資訊。
<a id="nfr-004-ac-06"></a>
* 提供連線測試。
<a id="nfr-004-ac-07"></a>
* 提供 Runtime 偵測結果。

<a id="nfr-005"></a>
## NFR-005 相容性

<a id="nfr-005-ac-01"></a>
第一階段支援：

<a id="nfr-005-ac-02"></a>
* Ubuntu 22.04
<a id="nfr-005-ac-03"></a>
* Ubuntu 24.04
<a id="nfr-005-ac-04"></a>
* Debian 12
<a id="nfr-005-ac-05"></a>
* Linux amd64
<a id="nfr-005-ac-06"></a>
* Linux arm64

前端支援最新版：

<a id="nfr-005-ac-07"></a>
* Chrome
<a id="nfr-005-ac-08"></a>
* Edge
<a id="nfr-005-ac-09"></a>
* Safari
<a id="nfr-005-ac-10"></a>
* Firefox

---

# 17. 錯誤處理

## 17.1 Runtime 不存在

顯示：

```text
此 VM 未偵測到 Claude CLI。
請先安裝 Claude CLI，或檢查 Daemon 設定中的 Binary Path。
```

## 17.2 Workspace 不合法

顯示：

```text
選擇的工作目錄不在允許的 Workspace Root 範圍內。
```

## 17.3 權限不足

顯示：

```text
Daemon 執行使用者無法讀取或執行此目錄。
```

## 17.4 Session 啟動失敗

顯示：

* Runtime
* Workspace
* 錯誤摘要
* 時間
* Node
* 可查看 Daemon Log 的提示

## 17.5 Node 離線

顯示：

```text
Node 目前離線，無法建立新 Session。
最後在線時間：2026-07-20 19:30
```

## 17.6 檔案無法預覽

原因可能包括：

* Binary。
* 超過大小限制。
* 敏感檔案。
* 權限不足。
* 檔案已刪除。
* 路徑不合法。

---

# 18. MVP 開發範圍

## Phase 1：Daemon 與 Node 連線

* Go Daemon。
* Enrollment Token。
* 一行安裝。
* systemd Service。
* Node 註冊。
* Heartbeat。
* Runtime 偵測。
* Node 列表。

## Phase 2：Terminal Session

* 選擇 Node。
* 選擇 Claude／Codex。
* 選擇 Workspace。
* 建立 Session。
* PTY 或 tmux。
* WebSocket Terminal。
* xterm.js。
* Resize。
* 終止 Session。
* 重新連線。

## Phase 3：Workspace 檔案總覽

* Allowed Root。
* 目錄樹。
* 檔案讀取。
* Monaco 預覽。
* 大小限制。
* Binary 判斷。
* 敏感檔案規則。
* 檔名搜尋。

## Phase 4：管理與維運

* RBAC。
* Audit Log。
* Daemon Doctor。
* Daemon Update。
* Node 停用。
* Session 歷史。
* 監控與錯誤頁。

---

# 19. MVP 驗收條件

MVP 完成時，必須符合以下條件：

<a id="mvp-ac-01"></a>
<a id="mvp-ac-01-ac-01"></a>
1. 管理員可於中央平台產生安裝 Token。
<a id="mvp-ac-02"></a>
<a id="mvp-ac-02-ac-01"></a>
2. 使用者可使用一行指令安裝 Go Daemon。
<a id="mvp-ac-03"></a>
<a id="mvp-ac-03-ac-01"></a>
3. Daemon 安裝後可自動啟動並註冊。
<a id="mvp-ac-04"></a>
<a id="mvp-ac-04-ac-01"></a>
4. 平台可顯示 Node Online／Offline。
<a id="mvp-ac-05"></a>
<a id="mvp-ac-05-ac-01"></a>
5. 平台可顯示 Claude 與 Codex 是否可用。
<a id="mvp-ac-06"></a>
<a id="mvp-ac-06-ac-01"></a>
6. 使用者可選擇 Node。
<a id="mvp-ac-07"></a>
<a id="mvp-ac-07-ac-01"></a>
7. 使用者可切換 Claude 或 Codex。
<a id="mvp-ac-08"></a>
<a id="mvp-ac-08-ac-01"></a>
8. 使用者可瀏覽 Workspace Root。
<a id="mvp-ac-09"></a>
<a id="mvp-ac-09-ac-01"></a>
9. 使用者可指定合法工作目錄。
<a id="mvp-ac-10"></a>
<a id="mvp-ac-10-ac-01"></a>
10. Daemon 可在指定目錄啟動 CLI。
<a id="mvp-ac-11"></a>
<a id="mvp-ac-11-ac-01"></a>
11. Web Terminal 可完整操作 CLI。
<a id="mvp-ac-12"></a>
<a id="mvp-ac-12-ac-01"></a>
12. CLI 原生審批畫面可正常顯示與操作。
<a id="mvp-ac-13"></a>
<a id="mvp-ac-13-ac-01"></a>
13. 瀏覽器關閉後，CLI Session 不會立即結束。
<a id="mvp-ac-14"></a>
<a id="mvp-ac-14-ac-01"></a>
14. 使用者可重新連線執行中的 Session。
<a id="mvp-ac-15"></a>
<a id="mvp-ac-15-ac-01"></a>
15. 使用者可查看 Workspace 目錄樹。
<a id="mvp-ac-16"></a>
<a id="mvp-ac-16-ac-01"></a>
16. 使用者可唯讀預覽程式碼檔案。
<a id="mvp-ac-17"></a>
<a id="mvp-ac-17-ac-01"></a>
17. 敏感檔案不可預覽。
<a id="mvp-ac-18"></a>
<a id="mvp-ac-18-ac-01"></a>
18. Node 離線時不可建立新 Session。
<a id="mvp-ac-19"></a>
<a id="mvp-ac-19-ac-01"></a>
19. 使用者可正常終止 Session。
<a id="mvp-ac-20"></a>
<a id="mvp-ac-20-ac-01"></a>
20. 所有重要操作均有 Audit Log。

---

# 20. 風險與對策

## 20.1 CLI 登入狀態

風險：

Claude 或 Codex 的登入資訊通常屬於特定 Linux 使用者。

對策：

* Daemon 以指定 Linux 使用者執行。
* 安裝時要求輸入 `--user`。
* `agentd doctor` 驗證 Runtime 是否可正常啟動。

## 20.2 Session 中斷

風險：

Daemon 重啟可能導致直接管理的 PTY Session 遺失。

對策：

* 優先使用 tmux 作為 Session Host。
* Daemon 只負責建立與附加 tmux Session。
* Daemon 重啟後重新掃描既有 Session。

## 20.3 路徑逃逸

風險：

Symlink 或 `../` 可能存取允許目錄以外的檔案。

對策：

* 使用 `filepath.Abs`。
* 使用 `filepath.EvalSymlinks`。
* 使用 `filepath.Rel` 驗證 Root。
* 每次檔案操作都重新檢查。

## 20.4 Terminal 多人同時輸入

風險：

多人操作同一 CLI 會造成不可預期結果。

對策：

* 單一可寫入連線。
* 其他使用者唯讀。
* 提供明確接管機制。

## 20.5 WebSocket 大量輸出

風險：

CLI 大量輸出可能使中央平台記憶體增加。

對策：

* Terminal 使用 Binary Frame。
* 設定 Buffer 上限。
* 對慢速客戶端設定 Backpressure。
* 不永久保存所有 Terminal Raw Output。

---

# 21. 未來擴充方向

後續可依需求加入：

1. Workspace Web 編輯。
2. Git Status 與 Git Diff。
3. 檔案修改即時通知。
4. Terminal Session 分享。
5. Session 錄影與回放。
6. Runtime 使用統計。
7. Token 或使用成本統計。
8. Agent 任務排程。
<a id="nfr-005-ac-100"></a>
9. Claude、Codex 以外的 Runtime。
<a id="nfr-005-ac-101"></a>
10. 多 Agent 協作。
<a id="nfr-005-ac-102"></a>
11. 自動建立 Git Worktree。
<a id="nfr-005-ac-103"></a>
12. 自動建立 Commit 與 Merge Request。
<a id="nfr-005-ac-104"></a>
13. Node 群組與標籤。
<a id="nfr-005-ac-105"></a>
14. Session 權限共享。
<a id="nfr-005-ac-106"></a>
15. 容器化 Workspace。
<a id="nfr-005-ac-107"></a>
16. 每個 Session 獨立 Linux User。
<a id="nfr-005-ac-108"></a>
17. SSH 或 Kubernetes Node Agent。
<a id="nfr-005-ac-109"></a>
18. Web 端上傳與下載檔案。
    *（2026-08-01：其中「把一張圖片交給 CLI」這一片已由 `FR-FILE-009` 交付。）*
    *（2026-08-03：一般檔案上傳已由 `FR-FILE-010` 交付。仍為未來擴充的是**下載**；
    編輯、刪除與更名依產品決定改由 CLI／終端機承擔，不再列為平台前端的擴充方向。）*
<a id="nfr-005-ac-110"></a>
19. 中央 Prompt Template。
<a id="nfr-005-ac-111"></a>
20. 企業 SSO。

---

# 22. 技術選型總結

## Central Backend

<a id="nfr-005-ac-112"></a>
* Python
<a id="nfr-005-ac-113"></a>
* FastAPI
<a id="nfr-005-ac-114"></a>
* PostgreSQL
<a id="nfr-005-ac-115"></a>
* SQLAlchemy
<a id="nfr-005-ac-116"></a>
* Alembic
<a id="nfr-005-ac-117"></a>
* WebSocket
<a id="nfr-005-ac-118"></a>
* JWT
<a id="nfr-005-ac-119"></a>
* Pydantic

## Frontend

<a id="nfr-005-ac-120"></a>
* Vue 3
<a id="nfr-005-ac-121"></a>
* TypeScript
<a id="nfr-005-ac-122"></a>
* Naive UI
<a id="nfr-005-ac-123"></a>
* Pinia
<a id="nfr-005-ac-124"></a>
* Vue Router
<a id="nfr-005-ac-125"></a>
* xterm.js
<a id="nfr-005-ac-126"></a>
* Monaco Editor

## VM Daemon

<a id="nfr-005-ac-127"></a>
* Go
<a id="nfr-005-ac-128"></a>
* `github.com/gorilla/websocket`
<a id="nfr-005-ac-129"></a>
* `github.com/creack/pty`
<a id="nfr-005-ac-130"></a>
* tmux
<a id="nfr-005-ac-131"></a>
* systemd

## 部署

<a id="nfr-005-ac-132"></a>
* 中央平台：Docker Compose 或 Kubernetes。
<a id="nfr-005-ac-133"></a>
* Daemon：Go Static Binary＋systemd。
<a id="nfr-005-ac-134"></a>
* 通訊：HTTPS／WSS。
<a id="nfr-005-ac-135"></a>
* Database：PostgreSQL。

---

# 23. 產品核心原則

<a id="nfr-005-ac-136"></a>
1. 中央平台只負責管理，不重新實作 CLI Agent。
<a id="nfr-005-ac-137"></a>
2. 保留 Claude 與 Codex 的原生使用體驗。
<a id="nfr-005-ac-138"></a>
3. Daemon 主動連線中央，不由中央 SSH 至 VM。
<a id="nfr-005-ac-139"></a>
4. 前端不得執行任意 Command。
<a id="nfr-005-ac-140"></a>
5. 所有工作目錄必須限制於 Allowed Root。
<a id="nfr-005-ac-141"></a>
6. Session 與瀏覽器生命週期分離。
<a id="nfr-005-ac-142"></a>
7. 檔案總覽的**預覽**為唯讀；工作區的寫入僅經由平台明確定義的路徑，且每一條路徑
   都必須經 `workspace.Root` 侷限、有配額（平台自有目錄另有保留期，使用者指定的落地位置
   則以**可見性**取代保留期）、每次寫入留稽核、可由節點拒絕並回報
   （ADR 0024 的 W1–W4，W2 第三腿由 ADR 0026 精修）。
   *（2026-08-01 修訂：原文為「檔案總覽第一階段採唯讀模式」。唯讀姿態已由使用者撤銷。）*
   *（2026-08-03 修訂：已建置的寫入路徑有兩條 —— 圖片投放 `FR-FILE-009` 與
   檔案上傳 `FR-FILE-010`，後者永不覆寫既有項目。下載尚未建置；編輯、刪除與更名
   依產品決定改由 CLI／終端機承擔。）*
<a id="nfr-005-ac-143"></a>
8. Daemon 必須可快速安裝、更新與診斷。
<a id="nfr-005-ac-144"></a>
9. Go Daemon 保持單一 Binary 與低依賴。
<a id="nfr-005-ac-145"></a>
10. MVP 優先完成穩定 Terminal 與 Workspace 瀏覽。

