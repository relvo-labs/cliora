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

1. 不解析 Claude 或 Codex 的內部事件。
2. 不建立中央審批機制。
3. 不攔截或替代 CLI 原生權限確認。
4. 不建立多 Agent 自動協作流程。
5. 不進行任務自動分派。
6. 不提供 Web 端完整 IDE。
7. 不提供第一階段的檔案寫入與編輯功能。
8. 不提供自動 Git Commit、Push 或 Merge Request。
9. 不提供 CLI 對話內容的語意分析。
10. 不建立跨 Runtime 的統一 Agent 行為模型。
11. 不允許使用者從前端執行任意 Shell Command。
12. 不將 VM 檔案系統直接掛載至中央伺服器。

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

## FR-AUTH-001 使用者登入

系統應提供帳號密碼登入。

驗收條件：

* 使用者可使用有效帳號登入。
* 無效帳號或密碼不可登入。
* 登入成功後取得有效 Session 或 JWT。
* Token 過期後需重新登入或刷新。

## FR-AUTH-002 角色權限

系統至少提供：

* Admin
* Developer
* Viewer

權限範圍：

| 功能           | Admin | Developer | Viewer |
| ------------ | ----: | --------: | -----: |
| 查看 Node      |     ✓ |         ✓ |      ✓ |
| 建立安裝 Token   |     ✓ |           |        |
| 移除 Node      |     ✓ |           |        |
| 建立 Session   |     ✓ |         ✓ |        |
| 操作 Terminal  |     ✓ |         ✓ |        |
| 終止 Session   |     ✓ |         ✓ |        |
| 瀏覽檔案         |     ✓ |         ✓ |      ✓ |
| 查看 Audit Log |     ✓ |           |        |

---

# 8.2 Node 管理

## FR-NODE-001 Node 註冊

Daemon 應可使用 Enrollment Token 向中央平台註冊。

註冊資訊至少包含：

* Node ID
* Node 名稱
* Hostname
* OS
* OS 版本
* CPU 架構
* Daemon 版本
* 執行使用者
* Claude 是否存在
* Claude 版本
* Codex 是否存在
* Codex 版本
* Workspace Root
* 註冊時間

## FR-NODE-002 Node 在線狀態

Daemon 應定期送出 Heartbeat。

建議頻率：

* 每 10 秒一次。

Node 狀態：

* Online
* Degraded
* Offline
* Disabled

判斷建議：

* 30 秒內收到 Heartbeat：Online。
* 30 至 90 秒未收到：Degraded。
* 超過 90 秒未收到：Offline。

## FR-NODE-003 Node 列表

Node 列表需顯示：

* Node 名稱
* Hostname
* 在線狀態
* OS
* Claude 可用狀態
* Codex 可用狀態
* 執行中 Session 數量
* 最後在線時間

## FR-NODE-004 Node 詳情

Node 詳情需顯示：

* 系統資訊
* Runtime 狀態
* Workspace Root
* Daemon 版本
* Session 列表
* 最後 Heartbeat
* 安裝與更新狀態

## FR-NODE-005 Node 停用

管理員可停用 Node。

停用後：

* Daemon 可保持連線。
* 不可建立新 Session。
* 既有 Session 是否中止由管理員選擇。
* 前端顯示 Disabled。

---

# 8.3 Daemon 安裝

## FR-INSTALL-001 建立 Enrollment Token

管理員可建立一次性或限時 Token。

Token 屬性：

* Token 值
* 建立者
* 建立時間
* 過期時間
* 最大使用次數
* 已使用次數
* 是否停用

## FR-INSTALL-002 一行安裝指令

平台應產生類似以下指令：

```bash
curl -fsSL https://platform.example.com/install.sh | \
sudo bash -s -- \
  --server https://platform.example.com \
  --token enroll_xxxxx \
  --name dev-vm-01 \
  --user neil
```

## FR-INSTALL-003 自動安裝流程

安裝腳本應：

1. 檢查 Linux 發行版。
2. 檢查 CPU 架構。
3. 下載正確的 Go Binary。
4. 驗證 Binary Checksum。
5. 安裝至 `/usr/local/bin/agentd`。
6. 建立 `/etc/agentd/config.yaml`。
7. 建立 `/var/lib/agentd`。
8. 建立 systemd Service。
9. 設定執行使用者。
10. 啟用開機啟動。
11. 啟動 Daemon。
12. 驗證中央連線。
13. 回傳安裝結果。

## FR-INSTALL-004 Daemon CLI

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

## FR-INSTALL-005 Daemon 更新

第一階段可使用手動更新：

```bash
sudo agentd update
```

更新流程：

1. 向中央取得最新版本資訊。
2. 下載新 Binary。
3. 驗證 Checksum。
4. 備份舊版本。
5. 替換 Binary。
6. 重新啟動 Daemon。
7. 若啟動失敗則回復舊版本。

---

# 8.4 Runtime 管理

## FR-RUNTIME-001 Runtime 偵測

Daemon 啟動時應偵測：

* `claude`
* `codex`

偵測項目：

* Binary 路徑
* 是否可執行
* 版本資訊
* 執行使用者是否可使用
* 最後檢查時間

## FR-RUNTIME-002 Runtime 選擇

建立 Session 時使用者必須選擇：

* Claude
* Codex

若 Runtime 不可用：

* 選項應顯示 Disabled。
* 顯示不可用原因。
* 不可送出建立 Session 請求。

## FR-RUNTIME-003 Runtime 白名單

前端不得直接傳入任意 Command。

Daemon 僅接受預先設定的 Runtime ID：

```text
claude
codex
```

Daemon 根據 Runtime ID 產生實際執行命令。

## FR-RUNTIME-004 Runtime 設定

Daemon 設定檔可指定：

```yaml
runtime:
  claude:
    enabled: true
    binary: /usr/local/bin/claude

  codex:
    enabled: true
    binary: /usr/local/bin/codex
```

---

# 8.5 Workspace 管理

## FR-WORKSPACE-001 Workspace Root

Daemon 應設定一個或多個允許的 Workspace Root。

例如：

```yaml
workspace:
  allowed_roots:
    - /home/neil/projects
    - /srv/projects
```

## FR-WORKSPACE-002 Workspace 瀏覽

使用者可在前端逐層展開 Workspace Root。

每筆目錄資料包含：

* 名稱
* 完整路徑
* 類型
* 修改時間
* 是否隱藏
* 是否可讀

## FR-WORKSPACE-003 指定工作目錄

建立 Session 時，使用者可選擇 Allowed Root 下的任意合法目錄。

Daemon 必須驗證：

* 目錄存在。
* 目錄可讀。
* 執行使用者具備必要權限。
* 目錄位於 Allowed Root。
* Symlink 解析後仍位於 Allowed Root。

## FR-WORKSPACE-004 最近使用 Workspace

系統應記錄使用者最近使用的 Workspace。

建立 Session 時可快速選擇：

* 最近使用
* 收藏 Workspace
* 目錄瀏覽

## FR-WORKSPACE-005 Workspace 收藏

使用者可收藏常用 Workspace。

收藏資料：

* User ID
* Node ID
* Workspace Path
* Display Name
* 建立時間

---

# 8.6 Session 管理

## FR-SESSION-001 建立 Session

建立 Session 必填欄位：

* Node
* Runtime
* Workspace
* Session 名稱

選填欄位：

* Terminal Rows
* Terminal Columns
* 啟動參數
* 環境變數 Profile

第一階段不允許任意自訂 CLI 啟動參數。

## FR-SESSION-002 Session 狀態

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

## FR-SESSION-003 Session 列表

列表顯示：

* Session 名稱
* Node
* Runtime
* Workspace
* 建立者
* 狀態
* PID
* 開始時間
* 最後活動時間

## FR-SESSION-004 Session 詳情

Session 詳情顯示：

* Session metadata
* Web Terminal
* Workspace 檔案樹
* Runtime
* Node
* Workspace
* 開始時間
* 最後活動時間
* 結束原因

## FR-SESSION-005 終止 Session

有權限的使用者可終止 Session。

流程：

1. 前端送出終止請求。
2. 中央平台轉送至 Daemon。
3. Daemon先送出正常終止信號。
4. 等待指定秒數。
5. 若未結束，送出強制終止。
6. 更新 Session 狀態。

## FR-SESSION-006 Session 重新連線

Session 在瀏覽器斷線後不得自動終止。

使用者應可重新附加至執行中的 Session。

## FR-SESSION-007 多人連線限制

MVP 建議採用：

* 同一 Session 僅允許一個可寫入連線。
* 其他使用者可唯讀觀看。
* 新使用者要求控制權時，需明確接管。

避免多人同時輸入造成 CLI 狀態混亂。

---

# 8.7 Terminal 功能

## FR-TERM-001 Terminal 顯示

前端使用 xterm.js 顯示完整 ANSI Terminal。

必須支援：

* ANSI 色彩
* Cursor
* Interactive Prompt
* 中文輸入
* UTF-8
* Ctrl+C
* Ctrl+D
* Tab
* 方向鍵
* Page Up／Page Down
* CLI 原生審批選單

## FR-TERM-002 Terminal 輸入

前端輸入應以低延遲 WebSocket 傳送至中央平台，再轉送至 Daemon PTY。

## FR-TERM-003 Terminal Resize

瀏覽器尺寸變更時，前端需通知 Daemon：

* Rows
* Columns

Daemon 應調整 PTY Size。

## FR-TERM-004 Terminal Scrollback

重新連線時應提供最近的終端輸出。

MVP 建議：

* 使用 tmux Scrollback，或
* Daemon 保存 2 MB 至 10 MB Ring Buffer。

## FR-TERM-005 Terminal 連線狀態

前端需顯示：

* Connected
* Reconnecting
* Disconnected
* Session Exited

## FR-TERM-006 自動重連

WebSocket 中斷時，前端應自動重連。

建議重試：

* 1 秒
* 2 秒
* 5 秒
* 10 秒
* 最大 30 秒間隔

---

# 8.8 檔案總覽

## FR-FILE-001 檔案樹

前端需以 Tree 呈現 Workspace。

每個節點顯示：

* 檔案或資料夾名稱
* 圖示
* 是否可展開
* 修改狀態
* 大小
* 修改時間

目錄採延遲載入，不一次掃描完整 Workspace。

## FR-FILE-002 檔案預覽

使用者點擊檔案後，系統應以 Monaco Editor 唯讀顯示。

支援：

* 語法高亮
* 行號
* 自動換行
* 複製
* 搜尋
* 重新整理
* 跳至指定行

## FR-FILE-003 檔案大小限制

預設最大預覽大小：

```text
2 MB
```

超過限制時：

* 不直接讀取。
* 顯示檔案過大。
* 顯示檔案大小。
* 第一階段不提供完整載入。

## FR-FILE-004 Binary 判斷

若檔案被判斷為 Binary：

* 不顯示原始內容。
* 顯示「不支援預覽」。
* 顯示 MIME Type、大小與修改時間。

## FR-FILE-005 敏感檔案保護

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

## FR-FILE-006 檔案重新整理

檔案樹應提供：

* 重新整理目前目錄。
* 重新整理檔案內容。
* Session 執行時可選擇自動刷新。

MVP 不要求即時監控所有檔案異動。

## FR-FILE-007 檔案搜尋

MVP 可提供檔名搜尋。

輸入：

* Keyword
* Workspace
* 最大結果數

回傳：

* 完整路徑
* 名稱
* 類型
* 修改時間

全文內容搜尋可列入後續版本。

---

# 8.9 Daemon 與中央通訊

## FR-CONN-001 主動連線

Daemon 必須主動建立至中央平台的 WebSocket 連線。

中央平台不得依賴 SSH 主動連入 VM。

## FR-CONN-002 TLS

正式環境所有通訊必須使用：

```text
HTTPS
WSS
```

## FR-CONN-003 自動重連

Daemon 與中央斷線後，應持續重連。

建議 Backoff：

* 1 秒
* 2 秒
* 5 秒
* 10 秒
* 30 秒
* 最大 60 秒

## FR-CONN-004 訊息請求識別

所有請求與回應需包含：

* Message Type
* Request ID
* Node ID
* Timestamp
* Payload

## FR-CONN-005 Terminal Binary Frame

Terminal 輸出建議使用 Binary WebSocket Frame。

控制訊息使用 JSON。

## FR-CONN-006 命令逾時

Workspace 與 Session 控制請求需設定 Timeout。

建議：

* 一般控制命令：10 秒。
* 目錄列出：15 秒。
* 檔案讀取：30 秒。
* Session 啟動：30 秒。

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

建議三欄布局：

```text
┌──────────────┬─────────────────────────┬──────────────────┐
│ Sessions     │ Terminal                │ Workspace        │
│              │                         │                  │
│ Claude ●     │ xterm.js                │ File Tree        │
│ Codex        │                         │ File Preview     │
│              │                         │                  │
└──────────────┴─────────────────────────┴──────────────────┘
```

頂部顯示：

* Session 名稱
* Node
* Runtime
* Workspace
* 狀態
* 重新連線
* 終止

右側 Workspace 區域提供：

* Files
* Preview
* Info

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

## SEC-001 路徑隔離

所有 Workspace 與檔案路徑必須：

* 使用 Absolute Path。
* 解析 Symlink。
* 確認位於 Allowed Root。
* 拒絕 Path Traversal。
* 拒絕 Null Byte。
* 拒絕未授權 Root。

## SEC-002 任意命令限制

前端不得直接指定 Command、Binary 或完整 Shell 指令。

僅可指定：

* Runtime ID
* Workspace
* Session Name
* Terminal Size

## SEC-003 Token 保護

Enrollment Token：

* 不以明文保存於資料庫。
* 使用後可失效。
* 可設定過期時間。
* 可設定使用次數。

## SEC-004 敏感檔案

敏感檔案預設不可透過 Web 預覽。

## SEC-005 Transport Security

正式環境必須使用 TLS。

## SEC-006 Audit

以下動作需記錄：

* Node 註冊。
* 建立 Session。
* 連線 Session。
* 終止 Session。
* 讀取敏感路徑失敗。
* 建立 Enrollment Token。
* 停用 Node。
* Daemon 更新。

## SEC-007 執行使用者

Daemon 不應預設以 root 長期執行。

MVP 可指定既有開發使用者，例如：

```text
User=neil
Group=neil
```

安裝步驟需明確提示該 Daemon 將具備此 Linux 使用者的權限。

---

# 16. 非功能需求

## NFR-001 效能

* Terminal 輸入至顯示的額外延遲目標小於 200 ms。
* Node 列表載入時間小於 2 秒。
* 目錄列表回應小於 2 秒。
* 2 MB 以下檔案預覽小於 3 秒。

## NFR-002 可用性

* Daemon 應自動重連。
* 中央平台重啟後，Daemon 應重新註冊。
* 瀏覽器中斷不得直接終止 CLI Session。
* Session 狀態應可恢復。

## NFR-003 擴充性

MVP 目標：

* 100 個 Node。
* 每個 Node 10 個同時 Session。
* 全平台 500 個同時 Terminal WebSocket。

## NFR-004 可維運性

Daemon 應：

* 使用結構化 Log。
* 支援 Log Level。
* 提供 `agentd doctor`。
* 提供版本資訊。
* 提供連線測試。
* 提供 Runtime 偵測結果。

## NFR-005 相容性

第一階段支援：

* Ubuntu 22.04
* Ubuntu 24.04
* Debian 12
* Linux amd64
* Linux arm64

前端支援最新版：

* Chrome
* Edge
* Safari
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

1. 管理員可於中央平台產生安裝 Token。
2. 使用者可使用一行指令安裝 Go Daemon。
3. Daemon 安裝後可自動啟動並註冊。
4. 平台可顯示 Node Online／Offline。
5. 平台可顯示 Claude 與 Codex 是否可用。
6. 使用者可選擇 Node。
7. 使用者可切換 Claude 或 Codex。
8. 使用者可瀏覽 Workspace Root。
9. 使用者可指定合法工作目錄。
10. Daemon 可在指定目錄啟動 CLI。
11. Web Terminal 可完整操作 CLI。
12. CLI 原生審批畫面可正常顯示與操作。
13. 瀏覽器關閉後，CLI Session 不會立即結束。
14. 使用者可重新連線執行中的 Session。
15. 使用者可查看 Workspace 目錄樹。
16. 使用者可唯讀預覽程式碼檔案。
17. 敏感檔案不可預覽。
18. Node 離線時不可建立新 Session。
19. 使用者可正常終止 Session。
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
9. Claude、Codex 以外的 Runtime。
10. 多 Agent 協作。
11. 自動建立 Git Worktree。
12. 自動建立 Commit 與 Merge Request。
13. Node 群組與標籤。
14. Session 權限共享。
15. 容器化 Workspace。
16. 每個 Session 獨立 Linux User。
17. SSH 或 Kubernetes Node Agent。
18. Web 端上傳與下載檔案。
19. 中央 Prompt Template。
20. 企業 SSO。

---

# 22. 技術選型總結

## Central Backend

* Python
* FastAPI
* PostgreSQL
* SQLAlchemy
* Alembic
* WebSocket
* JWT
* Pydantic

## Frontend

* Vue 3
* TypeScript
* Naive UI
* Pinia
* Vue Router
* xterm.js
* Monaco Editor

## VM Daemon

* Go
* `github.com/gorilla/websocket`
* `github.com/creack/pty`
* tmux
* systemd

## 部署

* 中央平台：Docker Compose 或 Kubernetes。
* Daemon：Go Static Binary＋systemd。
* 通訊：HTTPS／WSS。
* Database：PostgreSQL。

---

# 23. 產品核心原則

1. 中央平台只負責管理，不重新實作 CLI Agent。
2. 保留 Claude 與 Codex 的原生使用體驗。
3. Daemon 主動連線中央，不由中央 SSH 至 VM。
4. 前端不得執行任意 Command。
5. 所有工作目錄必須限制於 Allowed Root。
6. Session 與瀏覽器生命週期分離。
7. 檔案總覽第一階段採唯讀模式。
8. Daemon 必須可快速安裝、更新與診斷。
9. Go Daemon 保持單一 Binary 與低依賴。
10. MVP 優先完成穩定 Terminal 與 Workspace 瀏覽。

