# 多節點 CLI Agent 中央管理平台

# 技術規劃文件

## 1. 文件資訊

| 項目         | 內容                            |
| ---------- | ----------------------------- |
| 文件名稱       | 多節點 CLI Agent 中央管理平台技術規劃      |
| 文件版本       | v1.0                          |
| 對應 PRD     | 多節點 CLI Agent 中央管理平台 PRD v1.0 |
| 系統類型       | 中央化遠端 CLI 管理平台                |
| 使用範圍       | 內部開發環境與受控 VM                  |
| 核心 Runtime | Claude CLI、Codex CLI          |
| 中央後端       | Python、FastAPI、PostgreSQL     |
| 前端         | Vue 3、TypeScript、Naive UI     |
| VM Daemon  | Go                            |
| Terminal   | xterm.js、PTY、tmux             |
| 檔案預覽       | Monaco Editor                 |

---

# 2. 技術目標

本系統的技術目標，是建立一個可集中管理多台 VM 上 Claude CLI 與 Codex CLI 的平台。

平台需做到：

1. VM 可透過 Go Daemon 主動連線中央平台。
2. 使用者可從 Web 選擇 VM。
3. 使用者可選擇 Claude 或 Codex。
4. 使用者可指定合法的 Workspace。
5. Daemon 可在指定 Workspace 啟動 CLI。
6. Web 可完整操作原生 Terminal。
7. 瀏覽器斷線後，CLI Session 持續執行。
8. 使用者重新開啟頁面後可重新連線 Session。
9. Web 可瀏覽 Workspace 檔案樹與唯讀預覽檔案。
10. Daemon 可透過單一 Binary 安裝於 VM。
11. 系統不重新實作 Claude 或 Codex 的 Agent、權限與審批流程。

---

# 3. 架構原則

## 3.1 保留 CLI 原生能力

中央平台只處理 Terminal 輸入與輸出，不解析 Claude 或 Codex 的畫面內容。

以下功能均交由 CLI 本身處理：

* 工具執行審批
* 權限確認
* Slash Command
* 對話歷程
* Agent 行為
* 檔案修改
* Git 操作
* MCP 工具
* CLI 設定

## 3.2 Daemon 主動連線

中央平台不主動透過 SSH 連入 VM。

由 Go Daemon 主動建立持久 WebSocket：

```text
VM Agent Daemon
      │
      │ WSS 主動連線
      ▼
Central Platform
```

優點：

* VM 不需要開放額外對外 Port。
* 容易穿越 NAT 與防火牆。
* 中央平台不需要管理 SSH 金鑰。
* Node 連線狀態較容易管理。
* 可統一進行身分驗證與訊息轉送。

## 3.3 Session 與瀏覽器分離

瀏覽器不是 CLI Process 的父生命週期。

```text
Browser Close
     │
     ├── WebSocket 中斷
     │
     └── CLI Session 繼續執行
```

CLI Session 應由 tmux 或 Daemon 管理，不能因使用者關閉網頁而終止。

## 3.4 預設最小權限

* Daemon 不應預設使用 root 執行。
* 前端不可傳入任意 Shell Command。
* Workspace 只能位於設定的 Allowed Root。
* 檔案瀏覽第一階段為唯讀。
* 敏感檔案預設禁止預覽。

## 3.5 中央平台保持無狀態化

除 WebSocket 連線路由資訊外，中央 API 應盡可能保持無狀態。

持久資料保存於 PostgreSQL：

* Node
* Runtime
* Session metadata
* 使用者
* Workspace 收藏
* Audit Log

Terminal 原始輸出原則上不保存於 PostgreSQL。

---

# 4. 整體系統架構

```text
┌─────────────────────────────────────────────────────────────┐
│                       Web Browser                           │
│                                                             │
│ Vue 3 + TypeScript + Naive UI                               │
│ xterm.js                                                    │
│ Monaco Editor                                               │
└───────────────────────────┬─────────────────────────────────┘
                            │
                  HTTPS / WebSocket
                            │
┌───────────────────────────▼─────────────────────────────────┐
│                    Central Platform                         │
│                                                             │
│ FastAPI                                                     │
│ ├── Authentication API                                      │
│ ├── Node Management API                                     │
│ ├── Session Management API                                  │
│ ├── Workspace Relay API                                     │
│ ├── Enrollment API                                          │
│ ├── Audit API                                               │
│ ├── Browser WebSocket Gateway                               │
│ └── Daemon WebSocket Gateway                                │
│                                                             │
│ PostgreSQL                                                  │
└───────────────────────────┬─────────────────────────────────┘
                            │
                   Persistent WSS
                            │
┌───────────────────────────▼─────────────────────────────────┐
│                       VM Daemon                             │
│                                                             │
│ Go Binary                                                   │
│ ├── Connection Manager                                      │
│ ├── Authentication                                          │
│ ├── Heartbeat                                               │
│ ├── Runtime Manager                                         │
│ ├── Session Manager                                         │
│ ├── tmux Manager                                            │
│ ├── PTY Adapter                                             │
│ ├── Workspace Manager                                       │
│ ├── Filesystem Browser                                      │
│ ├── Runtime Detector                                        │
│ ├── Installer / Updater                                     │
│ └── Local State Store                                       │
│                                                             │
│ Claude CLI / Codex CLI                                      │
└─────────────────────────────────────────────────────────────┘
```

---

# 5. 技術選型

## 5.1 中央後端

| 項目             | 技術                                   |
| -------------- | ------------------------------------ |
| 語言             | Python 3.12+                         |
| Web Framework  | FastAPI                              |
| ASGI Server    | Uvicorn                              |
| Database       | PostgreSQL                           |
| ORM            | SQLAlchemy 2                         |
| Migration      | Alembic                              |
| Validation     | Pydantic                             |
| Authentication | JWT Access Token＋Refresh Token       |
| Password Hash  | Argon2id                             |
| WebSocket      | FastAPI／Starlette WebSocket          |
| Logging        | structlog 或標準 logging JSON Formatter |
| Metrics        | Prometheus                           |
| Testing        | pytest、pytest-asyncio                |
| Code Quality   | Ruff、mypy                            |

## 5.2 前端

| 項目               | 技術                    |
| ---------------- | --------------------- |
| Framework        | Vue 3                 |
| Language         | TypeScript            |
| Build Tool       | Vite                  |
| UI Library       | Naive UI              |
| State Management | Pinia                 |
| Router           | Vue Router            |
| Terminal         | xterm.js              |
| File Preview     | Monaco Editor         |
| HTTP Client      | Axios 或原生 Fetch       |
| WebSocket        | 原生 WebSocket 封裝       |
| Testing          | Vitest、Vue Test Utils |
| E2E              | Playwright            |
| Lint             | ESLint                |
| Format           | Prettier              |

## 5.3 Go Daemon

| 項目                 | 技術                 |
| ------------------ | ------------------ |
| 語言                 | Go                 |
| WebSocket          | gorilla/websocket  |
| PTY                | creack/pty         |
| CLI Framework      | cobra              |
| Config             | YAML               |
| Config Library     | koanf、viper 或自製設定層 |
| Logging            | slog 或 zap         |
| Process Management | os/exec、syscall    |
| Session Host       | tmux               |
| Local Metadata     | JSON 或 BoltDB      |
| File Watch         | fsnotify，後續版本      |
| Testing            | Go testing         |
| Build              | GoReleaser         |

## 5.4 基礎設施

| 項目                 | 建議                            |
| ------------------ | ----------------------------- |
| Reverse Proxy      | Nginx 或 Traefik               |
| Central Deployment | Docker Compose 起步             |
| TLS                | Let’s Encrypt 或公司憑證           |
| Database Backup    | pg_dump＋定期備份                  |
| Monitoring         | Prometheus＋Grafana            |
| Log Aggregation    | Loki 或既有 Log 平台               |
| Binary Release     | GitLab Release／Object Storage |
| CI/CD              | GitLab CI                     |

---

# 6. 系統模組劃分

## 6.1 Central Backend 模組

```text
backend/
├── app/
│   ├── main.py
│   ├── core/
│   │   ├── config.py
│   │   ├── security.py
│   │   ├── logging.py
│   │   ├── exceptions.py
│   │   └── permissions.py
│   │
│   ├── api/
│   │   ├── auth.py
│   │   ├── nodes.py
│   │   ├── sessions.py
│   │   ├── workspaces.py
│   │   ├── enrollment.py
│   │   ├── users.py
│   │   └── audit.py
│   │
│   ├── websocket/
│   │   ├── daemon_gateway.py
│   │   ├── terminal_gateway.py
│   │   ├── connection_manager.py
│   │   ├── node_registry.py
│   │   └── protocol.py
│   │
│   ├── services/
│   │   ├── auth_service.py
│   │   ├── node_service.py
│   │   ├── session_service.py
│   │   ├── workspace_service.py
│   │   ├── enrollment_service.py
│   │   └── audit_service.py
│   │
│   ├── models/
│   ├── schemas/
│   ├── repositories/
│   ├── db/
│   └── tests/
│
├── alembic/
├── pyproject.toml
└── Dockerfile
```

## 6.2 Frontend 模組

```text
frontend/
├── src/
│   ├── api/
│   │   ├── auth.ts
│   │   ├── nodes.ts
│   │   ├── sessions.ts
│   │   └── workspaces.ts
│   │
│   ├── components/
│   │   ├── terminal/
│   │   ├── workspace/
│   │   ├── node/
│   │   ├── session/
│   │   └── common/
│   │
│   ├── composables/
│   │   ├── useTerminal.ts
│   │   ├── useTerminalSocket.ts
│   │   ├── useWorkspaceTree.ts
│   │   └── useReconnect.ts
│   │
│   ├── layouts/
│   ├── pages/
│   │   ├── LoginPage.vue
│   │   ├── DashboardPage.vue
│   │   ├── NodesPage.vue
│   │   ├── NodeDetailPage.vue
│   │   ├── SessionsPage.vue
│   │   ├── SessionWorkspacePage.vue
│   │   └── InstallationPage.vue
│   │
│   ├── stores/
│   ├── router/
│   ├── types/
│   └── utils/
│
├── package.json
└── vite.config.ts
```

## 6.3 Go Daemon 模組

```text
agent-daemon/
├── cmd/
│   └── agentd/
│       └── main.go
│
├── internal/
│   ├── app/
│   ├── config/
│   ├── connection/
│   │   ├── client.go
│   │   ├── reconnect.go
│   │   ├── heartbeat.go
│   │   └── dispatcher.go
│   │
│   ├── auth/
│   ├── protocol/
│   ├── runtime/
│   │   ├── runtime.go
│   │   ├── registry.go
│   │   ├── claude.go
│   │   └── codex.go
│   │
│   ├── session/
│   │   ├── manager.go
│   │   ├── session.go
│   │   ├── state.go
│   │   └── recovery.go
│   │
│   ├── terminal/
│   │   ├── pty.go
│   │   ├── resize.go
│   │   ├── output.go
│   │   └── ring_buffer.go
│   │
│   ├── tmux/
│   │   ├── client.go
│   │   ├── session.go
│   │   └── attach.go
│   │
│   ├── workspace/
│   │   ├── roots.go
│   │   ├── validator.go
│   │   └── favorites.go
│   │
│   ├── filesystem/
│   │   ├── list.go
│   │   ├── read.go
│   │   ├── search.go
│   │   ├── mime.go
│   │   └── denylist.go
│   │
│   ├── systeminfo/
│   ├── installer/
│   ├── updater/
│   └── localstore/
│
├── packaging/
│   └── systemd/
│
├── scripts/
│   └── install.sh
│
├── configs/
│   └── config.example.yaml
│
├── go.mod
└── .goreleaser.yaml
```

---

# 7. Central Backend 設計

## 7.1 分層架構

後端採用以下分層：

```text
API / WebSocket
       ↓
Application Service
       ↓
Repository
       ↓
PostgreSQL
```

各層責任：

### API Layer

負責：

* HTTP Request 解析
* 權限驗證
* Schema Validation
* Response Formatting
* HTTP Error Mapping

### Service Layer

負責：

* 業務邏輯
* Node 狀態判斷
* Session 建立流程
* Daemon Command 發送
* Timeout 處理
* Audit Log 寫入

### Repository Layer

負責：

* Database Query
* Transaction
* Row Mapping
* 資料持久化

### WebSocket Layer

負責：

* Daemon Connection
* Browser Terminal Connection
* Message Routing
* Request／Response Correlation
* Connection Cleanup
* Backpressure

---

## 7.2 Node Connection Registry

中央平台需維護在線 Daemon 連線。

```python
class NodeConnectionRegistry:
    connections: dict[UUID, NodeConnection]
```

`NodeConnection` 建議包含：

```text
node_id
websocket
connected_at
last_heartbeat_at
pending_requests
active_terminal_streams
send_lock
```

必須避免不同 Coroutine 同時呼叫同一 WebSocket 的 `send`，因此每個 Node 連線應有獨立 Send Lock 或 Send Queue。

建議架構：

```text
Business Coroutine
       │
       ▼
Node Send Queue
       │
       ▼
Single Sender Coroutine
       │
       ▼
Daemon WebSocket
```

---

## 7.3 Request Correlation

Workspace、Session、Runtime 等命令採 Request／Response 模式。

中央平台產生 `request_id`：

```json
{
  "type": "filesystem.list",
  "request_id": "01J...",
  "payload": {}
}
```

中央暫存：

```text
pending_requests[request_id] = Future
```

Daemon 回應：

```json
{
  "type": "filesystem.entries",
  "request_id": "01J...",
  "success": true,
  "payload": {}
}
```

中央收到後完成對應 Future。

需要處理：

* Timeout
* Node Disconnect
* Duplicate Response
* Unknown Request ID
* Daemon Error Response

建議逾時：

| 操作              | Timeout |
| --------------- | ------: |
| Runtime List    |    10 秒 |
| Workspace Roots |    10 秒 |
| Directory List  |    15 秒 |
| File Read       |    30 秒 |
| Session Start   |    30 秒 |
| Session Stop    |    20 秒 |
| Session Attach  |    15 秒 |

---

## 7.4 Node 狀態計算

Node 狀態不完全依賴資料庫欄位，應由最後 Heartbeat 動態計算。

```text
0～30 秒：ONLINE
31～90 秒：DEGRADED
超過 90 秒：OFFLINE
管理員停用：DISABLED
```

Daemon WebSocket 斷開時，可立即標示為 Offline，但仍保存 `last_seen_at`。

---

# 8. Go Daemon 設計

## 8.1 Daemon 執行模式

Daemon 啟動：

```bash
agentd run --config /etc/agentd/config.yaml
```

systemd：

```ini
[Unit]
Description=CLI Agent Management Daemon
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=neil
Group=neil
ExecStart=/usr/local/bin/agentd run --config /etc/agentd/config.yaml
Restart=always
RestartSec=5
LimitNOFILE=65535

NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

若 `PrivateHome=true`，Daemon 可能無法存取使用者 Home、Claude/Codex 設定與 Workspace，因此不建議直接啟用。

---

## 8.2 Daemon 啟動流程

```text
讀取 Config
   ↓
驗證 Config
   ↓
取得 System Info
   ↓
偵測 Claude / Codex
   ↓
掃描既有 tmux Session
   ↓
載入 Local Session Metadata
   ↓
建立中央 WebSocket
   ↓
完成 Node Authentication
   ↓
註冊 Node
   ↓
啟動 Heartbeat
   ↓
啟動 Message Dispatcher
```

---

## 8.3 Runtime 抽象

定義統一 Runtime Interface：

```go
type Runtime interface {
    ID() string
    Detect(ctx context.Context) DetectionResult
    BuildCommand(opts StartOptions) (*exec.Cmd, error)
    Validate(opts StartOptions) error
}
```

`StartOptions`：

```go
type StartOptions struct {
    SessionID string
    Workspace string
    Rows      uint16
    Columns   uint16
}
```

Runtime Registry：

```go
type Registry struct {
    runtimes map[string]Runtime
}
```

前端只能送出 Runtime ID：

```text
claude
codex
```

不得傳入：

```text
bash -c "..."
/usr/bin/python ...
任意 binary path
```

---

## 8.4 Claude Runtime

設定：

```yaml
runtime:
  claude:
    enabled: true
    binary: /usr/local/bin/claude
```

建構命令：

```go
cmd := exec.Command(config.Binary)
cmd.Dir = workspace
cmd.Env = buildTerminalEnv(os.Environ())
```

第一階段不由 Web 傳入任意 CLI Arguments。

必要時可由中央平台定義受控 Profile：

```yaml
profiles:
  default:
    args: []

  continue:
    args:
      - "--continue"
```

但 MVP 建議先不提供。

---

## 8.5 Codex Runtime

設定：

```yaml
runtime:
  codex:
    enabled: true
    binary: /usr/local/bin/codex
```

建構方式與 Claude 相同。

Runtime Detector 應執行受控版本命令，例如：

```text
claude --version
codex --version
```

需設定 Timeout，避免命令阻塞。

---

# 9. Session 與 Terminal 架構

## 9.1 為何採用 tmux

若 Daemon 直接持有 PTY：

* Daemon 重啟後 Session 消失。
* Process 與 Daemon 綁定。
* 重新連線與 Scrollback 需自行實作。
* Session Recovery 複雜。

使用 tmux：

* 瀏覽器關閉不影響 CLI。
* Daemon 重啟後可重新掃描 Session。
* 可重新 Attach。
* 原生提供 Scrollback。
* CLI Process 與 WebSocket 分離。

因此建議：

```text
Daemon
  └── tmux session
        └── Claude / Codex
```

---

## 9.2 Session 命名

tmux Session 不應直接使用使用者輸入名稱。

建議格式：

```text
agentd-{session_uuid}
```

例如：

```text
agentd-3e693035-f158-4896-8e99-cd5fb48c13bb
```

使用者顯示名稱保存於 PostgreSQL。

---

## 9.3 建立 Session

流程：

```text
Central 建立 Session DB Record：STARTING
        ↓
發送 session.start
        ↓
Daemon 驗證 Runtime
        ↓
Daemon 驗證 Workspace
        ↓
建立 tmux Session
        ↓
在 tmux 中啟動 Claude / Codex
        ↓
回報 PID / tmux name
        ↓
Central 更新 RUNNING
```

tmux 指令概念：

```bash
tmux new-session \
  -d \
  -s agentd-SESSION_ID \
  -c /workspace/path \
  /usr/local/bin/claude
```

避免使用 Shell String 拼接，應透過 `exec.Command` 傳入獨立參數。

---

## 9.4 Attach Terminal

為了將 tmux Terminal 接到 Web，Daemon 可啟動：

```bash
tmux attach-session -t agentd-SESSION_ID
```

並透過 PTY 執行 attach command。

```text
xterm.js
   ↕
Browser WebSocket
   ↕
Central Relay
   ↕
Daemon WebSocket
   ↕
Attach PTY
   ↕
tmux
   ↕
Claude / Codex
```

---

## 9.5 Session State

中央狀態：

```text
STARTING
RUNNING
DISCONNECTED
EXITED
FAILED
TERMINATING
TERMINATED
```

Daemon 本地狀態：

```text
tmux_exists
runtime_process_alive
attached_clients
last_activity_at
exit_status
```

中央狀態與 Daemon 狀態需要定期同步。

Heartbeat 可包含：

```json
{
  "active_sessions": [
    {
      "session_id": "...",
      "status": "RUNNING",
      "attached_clients": 1
    }
  ]
}
```

---

## 9.6 Session Recovery

Daemon 啟動時：

1. 讀取本地 Session Metadata。
2. 執行 `tmux list-sessions`。
3. 比對 `agentd-*` Session。
4. 將仍存在的 Session 回報中央。
5. 對已不存在的 Session 標記為 Exited。
6. 對中央未知但本地存在的 Session進行 Recovery Report。

本地 metadata 可存放：

```text
/var/lib/agentd/sessions/{session_id}.json
```

內容：

```json
{
  "session_id": "...",
  "tmux_name": "agentd-...",
  "runtime": "claude",
  "workspace": "/home/neil/projects/demo",
  "created_at": "..."
}
```

---

# 10. Terminal WebSocket 設計

## 10.1 連線方式

Browser：

```text
WS /ws/sessions/{session_id}/terminal
```

建立連線後，前端先送控制訊息：

```json
{
  "type": "terminal.attach",
  "rows": 40,
  "columns": 140,
  "mode": "write"
}
```

中央檢查：

* Session 是否存在。
* Node 是否在線。
* 使用者是否有權限。
* 是否已有寫入控制者。

---

## 10.2 Frame 設計

建議區分：

### JSON Text Frame

用於控制命令：

```text
attach
resize
ping
takeover
detach
status
error
```

### Binary Frame

用於 Terminal Input／Output。

但單純 Binary Frame 無法識別方向與 Session。

由於 Browser WebSocket 已綁定單一 Session，因此 Browser 到 Central 可直接：

* Browser Binary：Terminal Input
* Central Binary：Terminal Output

Daemon 與 Central 共用一條 Node WebSocket，需在 Binary 前增加 Header。

可採以下 Binary Protocol：

```text
1 byte   version
1 byte   frame_type
16 bytes session UUID
N bytes  payload
```

Frame Type：

```text
0x01 Terminal Input
0x02 Terminal Output
```

MVP 也可全部先使用 JSON＋Base64 或字串資料，但大量輸出時效率較差。

建議：

* 控制訊息用 JSON。
* Terminal Stream 用 Binary。

---

## 10.3 Backpressure

CLI 可能瞬間產生大量輸出。

若 Browser 消費速度過慢，不可無限制堆積記憶體。

建議：

1. 每個 Browser Connection 有固定大小 Send Queue。
2. Queue 滿時：

   * 丟棄較舊的非關鍵 Output，或
   * 中斷慢速連線並要求重新 Attach。
3. 單次 Frame 限制，例如 64 KB。
4. Daemon PTY Reader 使用固定 Buffer。
5. 中央平台不永久保存完整 Terminal Output。

第一版可先採：

```text
每個 Terminal Client Queue：1～4 MB
```

超過後斷線並顯示：

```text
Terminal output exceeded client buffer. Please reconnect.
```

---

## 10.4 多人操作

MVP 採單一 Writer。

Session Connection Role：

```text
controller
viewer
```

規則：

* 同時間只能有一個 Controller。
* Viewer 可看到輸出但不可輸入。
* Controller 斷線後保留 30 秒控制權。
* 其他使用者可申請接管。
* 接管需要明確操作並記錄 Audit。

---

# 11. Workspace 與檔案瀏覽設計

## 11.1 Allowed Root

Daemon Config：

```yaml
workspace:
  allowed_roots:
    - path: /home/neil/projects
      name: Neil Projects

    - path: /srv/projects
      name: Shared Projects
```

中央資料庫只保存 Daemon 回報的 Root metadata。

實際安全判斷必須由 Daemon 執行，不能只依賴中央平台。

---

## 11.2 路徑驗證

每一次目錄與檔案操作都需驗證。

驗證步驟：

1. 拒絕空路徑。
2. 拒絕 Null Byte。
3. 轉為 Absolute Path。
4. 清理 `.` 與 `..`。
5. 解析 Symlink。
6. 解析 Allowed Root 的 Symlink。
7. 使用 `filepath.Rel` 判斷是否仍位於 Root。
8. 檢查檔案權限。
9. 套用 Deny Rule。

不能只使用：

```go
strings.HasPrefix(target, root)
```

因為：

```text
/home/neil/projects-other
```

可能錯誤通過 `/home/neil/projects` 的 Prefix 檢查。

---

## 11.3 目錄列表

請求：

```json
{
  "type": "filesystem.list",
  "request_id": "...",
  "payload": {
    "path": "/home/neil/projects/project-a"
  }
}
```

回應：

```json
{
  "type": "filesystem.entries",
  "request_id": "...",
  "success": true,
  "payload": {
    "path": "/home/neil/projects/project-a",
    "entries": [
      {
        "name": "backend",
        "path": "/home/neil/projects/project-a/backend",
        "type": "directory",
        "size": 4096,
        "modified_at": "...",
        "hidden": false,
        "symlink": false
      }
    ]
  }
}
```

目錄採 Lazy Load。

前端只在使用者展開節點時取得下一層。

---

## 11.4 Ignore Rule

預設避免展開大型或無價值目錄：

```yaml
filesystem:
  excluded_directories:
    - .git/objects
    - node_modules
    - .venv
    - dist
    - build
    - __pycache__
```

處理方式可選：

* 完全隱藏。
* 顯示但不可展開。
* 顯示為「已排除」。

建議顯示但預設不載入，讓使用者了解目錄存在。

---

## 11.5 檔案讀取

讀取前需檢查：

* 是否為 Regular File。
* 是否超過大小限制。
* 是否為敏感檔案。
* 是否位於 Workspace。
* 是否可讀。
* 是否疑似 Binary。

設定：

```yaml
filesystem:
  max_preview_size: 2097152
```

讀取時應使用 Limit Reader，避免檔案在檢查後快速變大造成記憶體問題。

---

## 11.6 Binary 判斷

可採以下方式：

1. 讀取前 8 KB。
2. 若包含 Null Byte，判定為 Binary。
3. 嘗試 UTF-8 Validation。
4. 判斷控制字元比例。
5. 搭配副檔名與 MIME Type。

圖片、PDF、壓縮檔、執行檔第一階段不直接預覽。

---

## 11.7 敏感檔案規則

預設：

```yaml
filesystem:
  denied_patterns:
    - ".env"
    - ".env.*"
    - "*.pem"
    - "*.key"
    - "*.p12"
    - "*.pfx"
    - "id_rsa"
    - "id_ed25519"
    - "*credentials*"
    - "*secret*"
```

需注意 Pattern 不應過度寬鬆，例如 `*secret*` 可能擋到程式碼檔案。

正式設計建議分成：

* Exact Name
* Extension
* Glob Pattern
* Directory Pattern

---

## 11.8 檔案搜尋

MVP 先做檔名搜尋。

Daemon 遞迴搜尋時需限制：

```text
最大深度
最大結果數
最大掃描檔案數
Timeout
Ignore Pattern
```

例如：

```yaml
filesystem:
  search:
    max_depth: 10
    max_results: 200
    timeout_seconds: 10
```

全文搜尋後續可整合 `ripgrep`，但不能允許前端傳入任意 rg 參數。

---

# 12. 通訊協定設計

## 12.1 通用訊息格式

```json
{
  "version": "1",
  "type": "session.start",
  "request_id": "01J...",
  "node_id": "...",
  "timestamp": "2026-07-20T20:00:00+08:00",
  "payload": {}
}
```

回應：

```json
{
  "version": "1",
  "type": "session.started",
  "request_id": "01J...",
  "success": true,
  "error": null,
  "payload": {}
}
```

錯誤：

```json
{
  "version": "1",
  "type": "error",
  "request_id": "01J...",
  "success": false,
  "error": {
    "code": "WORKSPACE_OUTSIDE_ALLOWED_ROOT",
    "message": "Workspace is outside allowed roots",
    "details": {}
  }
}
```

---

## 12.2 訊息類型

### Node

```text
node.register
node.registered
node.heartbeat
node.system_info
node.runtime_status
node.shutdown
```

### Session

```text
session.start
session.started
session.start_failed
session.stop
session.stopped
session.list
session.list_result
session.recover
session.status_changed
```

### Terminal

```text
terminal.attach
terminal.attached
terminal.detach
terminal.resize
terminal.control_acquire
terminal.control_release
terminal.error
```

### Workspace

```text
workspace.roots
workspace.roots_result
workspace.validate
workspace.validate_result
```

### Filesystem

```text
filesystem.list
filesystem.entries
filesystem.read
filesystem.content
filesystem.search
filesystem.search_result
filesystem.stat
filesystem.stat_result
```

### Daemon

```text
daemon.version
daemon.doctor
daemon.doctor_result
daemon.update
daemon.update_result
```

---

## 12.3 錯誤代碼

建議建立固定 Error Code：

```text
NODE_OFFLINE
NODE_DISABLED
RUNTIME_NOT_FOUND
RUNTIME_DISABLED
RUNTIME_NOT_EXECUTABLE
WORKSPACE_NOT_FOUND
WORKSPACE_NOT_DIRECTORY
WORKSPACE_OUTSIDE_ALLOWED_ROOT
WORKSPACE_PERMISSION_DENIED
FILE_NOT_FOUND
FILE_TOO_LARGE
FILE_BINARY
FILE_DENIED
FILE_PERMISSION_DENIED
SESSION_NOT_FOUND
SESSION_ALREADY_EXISTS
SESSION_START_FAILED
SESSION_STOP_FAILED
SESSION_NOT_RUNNING
TERMINAL_ALREADY_CONTROLLED
REQUEST_TIMEOUT
PROTOCOL_VERSION_UNSUPPORTED
INTERNAL_ERROR
```

---

# 13. 資料庫設計

## 13.1 核心資料表

```text
users
roles
user_roles
nodes
node_runtimes
node_workspace_roots
terminal_sessions
session_connections
enrollment_tokens
workspace_favorites
audit_logs
daemon_releases
```

---

## 13.2 terminal_sessions 補充欄位

建議欄位：

| 欄位                 | 說明                |
| ------------------ | ----------------- |
| id                 | UUID              |
| node_id            | Node              |
| created_by         | 建立者               |
| name               | 使用者顯示名稱           |
| runtime            | claude／codex      |
| workspace          | 工作目錄              |
| tmux_name          | tmux Session Name |
| status             | Session 狀態        |
| pid                | Runtime PID       |
| controller_user_id | 目前控制者             |
| started_at         | 開始時間              |
| last_activity_at   | 最後活動              |
| ended_at           | 結束時間              |
| exit_code          | Exit Code         |
| error_code         | 錯誤代碼              |
| error_message      | 錯誤內容              |
| metadata           | JSONB             |

索引：

```text
node_id
created_by
status
started_at
(node_id, status)
```

---

## 13.3 Audit Log

Audit Log 不保存完整 Terminal 內容。

應記錄：

* 使用者登入
* Node 註冊
* Enrollment Token 建立
* Session 建立
* Session Attach
* Session Takeover
* Session Stop
* File Read
* 敏感檔案拒絕
* Node Disable
* Daemon Update

檔案讀取 Audit 可只記：

```text
user
node
workspace
relative_path
result
timestamp
```

避免記錄檔案內容。

---

# 14. Authentication 與授權

## 14.1 使用者驗證

MVP：

* Username／Password
* JWT Access Token
* Refresh Token

Access Token：

```text
15～30 分鐘
```

Refresh Token：

```text
7～30 天
```

WebSocket 連線可透過：

* Cookie，或
* 短效 WebSocket Ticket

不建議將長效 JWT 直接放在 WebSocket Query String，因為可能被 Proxy Log 記錄。

建議流程：

```text
POST /api/ws-ticket
       ↓
取得一次性短效 Ticket
       ↓
WS /ws/... ?ticket=xxx
```

Ticket：

* 30～60 秒有效。
* 只能使用一次。
* 綁定 User 與 Resource。

---

## 14.2 Daemon 驗證

Enrollment Token 只用於首次註冊。

首次註冊時，Daemon 以 OS CSPRNG 產生 Ed25519 keypair；只將 public key 送至中央，private key 留在 `/etc/agentd/credentials.yaml`（`0600`）。中央資料庫只保存 public key。

每次 Daemon WebSocket 連線：

1. Daemon 以 Node ID 連線。
2. 中央發送單次 32-byte nonce challenge。
3. Daemon 以 private key 對 domain-separated node id、challenge id 與 nonce 簽章。
4. 中央以 public key 驗證。
5. 建立認證連線。

既有 shared-secret credential 由 migration 0003 全部撤銷並強制重新 enrollment；不提供 fallback。

避免直接重複傳送 Node Secret。

---

# 15. Daemon 安裝與更新

## 15.1 安裝架構

使用者執行：

```bash
curl -fsSL https://platform.example.com/install.sh | \
sudo bash -s -- \
  --server https://platform.example.com \
  --token enroll_xxxxx \
  --user neil \
  --name dev-vm-01
```

Shell Script 只負責：

1. 偵測架構。
2. 下載 Binary。
3. 驗證 SHA256。
4. 執行 `agentd install`。

實際安裝邏輯由 Go Binary 完成。

```bash
agentd install \
  --server ... \
  --token ... \
  --user ... \
  --name ...
```

---

## 15.2 安裝內容

```text
/usr/local/bin/agentd
/etc/agentd/config.yaml
/etc/agentd/credentials.yaml
/var/lib/agentd/
/var/log/agentd/ 或 journald
/etc/systemd/system/agentd.service
```

---

## 15.3 支援架構

MVP：

```text
linux-amd64
linux-arm64
```

發行檔案：

```text
agentd_1.0.0_linux_amd64.tar.gz
agentd_1.0.0_linux_arm64.tar.gz
checksums.txt
```

---

## 15.4 更新流程

`agentd update`：

1. 取得 Release Manifest。
2. 比對目前版本。
3. 下載新 Binary。
4. 驗證 SHA256。
5. 寫入暫存路徑。
6. 備份原 Binary。
7. 原子替換。
8. 重啟 systemd。
9. 執行 Health Check。
10. 失敗時 Rollback。

更新期間 tmux Session 可繼續執行。

Daemon 重啟後重新 Attach／Recovery。

---

# 16. 前端技術設計

## 16.1 Session Workspace 頁面

建議布局：

```text
┌────────────────────────────────────────────────────────────┐
│ Session Header                                             │
│ Node / Runtime / Workspace / Status / Stop                 │
├──────────────┬───────────────────────────┬─────────────────┤
│ Session List │ Terminal                  │ Workspace       │
│              │                           │                 │
│ Claude ●     │ xterm.js                  │ File Tree       │
│ Codex        │                           │ File Preview    │
│              │                           │                 │
└──────────────┴───────────────────────────┴─────────────────┘
```

支援：

* 左右面板拖曳調整。
* Workspace 面板收合。
* Terminal 自動 Fit。
* 頁面刷新後重連。
* Session 切換時保留狀態。

---

## 16.2 xterm.js 模組

建議使用：

```text
@xterm/xterm
@xterm/addon-fit
@xterm/addon-web-links
@xterm/addon-search
```

Terminal 初始化：

```ts
const terminal = new Terminal({
  cursorBlink: true,
  convertEol: false,
  scrollback: 10_000,
  fontFamily: 'JetBrains Mono, monospace',
  fontSize: 13,
})
```

輸入需直接傳送原始 Bytes，不應自行處理 Enter、Ctrl+C 等內容。

---

## 16.3 Terminal Reconnect

前端狀態：

```text
idle
connecting
connected
reconnecting
disconnected
exited
```

重連策略：

```text
1s → 2s → 5s → 10s → 30s
```

連線成功後重新送：

```json
{
  "type": "terminal.attach",
  "rows": 40,
  "columns": 140
}
```

---

## 16.4 Monaco Editor

第一階段：

* readOnly
* syntax highlight
* line number
* search
* word wrap
* copy
* refresh

需要避免一次載入大量 Model。

切換檔案時應 Dispose 舊 Model，或建立受控 Model Cache。

---

# 17. 部署架構

## 17.1 MVP 部署

```text
Internet / Internal Network
          │
       Nginx
          │
   ┌──────┴────────┐
   │               │
Frontend        FastAPI
                   │
              PostgreSQL
```

Docker Compose：

```text
nginx
frontend
backend
postgres
prometheus
grafana
```

初期不需要：

* Kafka
* NATS
* Redis
* Temporal
* Kubernetes

---

## 17.2 是否需要 Redis

MVP 單一 Backend Instance 時不需要 Redis。

若未來中央後端水平擴充，多個 Backend Instance 需要共享：

* Node Connection 所在 Instance
* Browser Terminal Route
* Pending Request
* Session Controller Lock

此時可考慮：

* Redis Pub/Sub
* Redis Streams
* NATS

第一階段避免過度設計。

---

## 17.3 Sticky Connection

Daemon WebSocket 是長連線。

若未來有多個 Backend Instance：

* Daemon Connection 會固定於某一 Instance。
* Browser Terminal 可能連到另一 Instance。
* 需要跨 Instance Relay。

MVP 使用單一 Backend Instance，可避免此問題。

正式水平擴充時再加入 Message Broker。

---

# 18. 可觀測性

## 18.1 Backend Metrics

建議監控：

```text
online_nodes
active_daemon_connections
active_terminal_connections
running_sessions
websocket_messages_total
websocket_bytes_total
daemon_request_duration
daemon_request_timeout_total
terminal_client_queue_size
http_request_duration
database_pool_usage
```

## 18.2 Daemon Metrics

Daemon 可先透過 Heartbeat 回報：

```text
cpu_usage
memory_usage
load_average
disk_usage
active_sessions
daemon_uptime
```

不需要初期直接開放 Prometheus Port。

## 18.3 Logging

所有元件採 JSON Structured Log。

共通欄位：

```text
timestamp
level
service
node_id
session_id
request_id
user_id
event
message
error
```

Terminal 原始輸入／輸出不得寫入一般 Log。

---

# 19. 測試策略

## 19.1 Backend Unit Test

涵蓋：

* Session State Transition
* Node Status Calculation
* Enrollment Token
* RBAC
* Request Correlation
* Timeout
* Audit Log
* Workspace Relay

## 19.2 Daemon Unit Test

涵蓋：

* Path Validation
* Symlink Escape
* Runtime Detection
* Command Builder
* Session Metadata
* Binary Detection
* Denied Pattern
* Protocol Encoding／Decoding

## 19.3 Integration Test

建立測試 VM 或 Docker Environment：

* 安裝 tmux。
* 放置 Fake Claude／Fake Codex CLI。
* 建立 Daemon。
* 啟動 Session。
* 傳送 Terminal Input。
* 驗證 Output。
* 模擬 Daemon Disconnect。
* 驗證 Recovery。
* 驗證檔案瀏覽。

Fake CLI 可實作：

```text
輸出 Welcome
讀取 stdin
原樣回傳
支援 Ctrl+C
```

## 19.4 E2E Test

Playwright：

1. 登入。
2. 查看 Node。
3. 建立 Session。
4. 選擇 Runtime。
5. 選擇 Workspace。
6. 操作 Terminal。
7. 開啟檔案。
8. 重整頁面。
9. 驗證 Session 可重新連線。
10. 終止 Session。

## 19.5 安全測試

必測：

```text
../ 路徑逃逸
Symlink Escape
超大檔案
Binary File
敏感檔案
Node Secret 錯誤
過期 Enrollment Token
無權限 Terminal Attach
多人同時控制
WebSocket Flood
慢速 Client
```

---

# 20. CI/CD 規劃

## 20.1 Backend Pipeline

```text
lint
type-check
unit-test
integration-test
build-image
security-scan
deploy
```

## 20.2 Frontend Pipeline

```text
lint
type-check
unit-test
build
e2e
build-image
deploy
```

## 20.3 Daemon Pipeline

```text
go fmt check
go vet
unit-test
race-test
build amd64
build arm64
generate checksum
create release
publish binary
```

Daemon Release 建議使用 Git Tag：

```text
v1.0.0
```

---

# 21. 開發階段規劃

## Phase 0：技術驗證

目標：

驗證核心路徑可行。

內容：

1. Go 使用 PTY 啟動 tmux attach。
2. tmux 內啟動 Fake CLI。
3. Go WebSocket 傳送 Terminal I/O。
4. Browser xterm.js 顯示。
5. Terminal Resize。
6. 瀏覽器斷線後重新 Attach。
7. Go 讀取目錄與檔案。

交付物：

* CLI Terminal PoC。
* Session Recovery PoC。
* Filesystem PoC。

---

## Phase 1：Daemon 與 Node 管理

內容：

* Daemon Config。
* Daemon CLI。
* systemd Install。
* Enrollment Token。
* Node Register。
* Node Authentication。
* Heartbeat。
* Runtime Detection。
* Node List。
* Node Detail。
* Daemon Doctor。

完成條件：

* VM 可一行安裝。
* Node 可正常出現在平台。
* 平台可顯示 Claude／Codex 狀態。

---

## Phase 2：Session 與 Terminal

內容：

* Session Database。
* Session Start。
* Runtime Selection。
* Workspace Selection。
* tmux Session。
* PTY Attach。
* Terminal WebSocket。
* xterm.js。
* Resize。
* Stop。
* Reconnect。
* Session Recovery。
* Single Controller。

完成條件：

* 可從 Web 在指定 Workspace 啟動 Claude 或 Codex。
* CLI 可完整互動。
* Browser 刷新後可繼續操作。

---

## Phase 3：Workspace Files

內容：

* Allowed Root。
* Path Validation。
* Directory Tree。
* File Read。
* Monaco Preview。
* Binary Detection。
* Size Limit。
* Sensitive File Rule。
* Filename Search。
* File Audit。

完成條件：

* 使用者可瀏覽 Session Workspace。
* 可唯讀預覽程式碼。
* 不可越權讀取 Allowed Root 外內容。

---

## Phase 4：管理與維運

內容：

* RBAC。
* Audit Log。
* Node Disable。
* Daemon Update。
* Session History。
* Metrics。
* Dashboard。
* Error Management。
* Backup。

---

# 22. 建議開發優先順序

開發優先順序不應先從完整後台頁面開始。

建議依序：

```text
1. Go PTY + tmux PoC
2. xterm.js Terminal PoC
3. Daemon ↔ Central WebSocket
4. Session Start / Attach / Stop
5. Workspace Validation
6. File Tree / File Preview
7. Enrollment / Installer
8. Node Management UI
9. Authentication / RBAC
10. Audit / Monitoring / Update
```

最大技術風險在：

* PTY 與 tmux Attach。
* Terminal Binary Stream。
* WebSocket Backpressure。
* Session Recovery。
* Workspace Path Security。

因此應優先驗證，不應到後期才處理。

---

# 23. 安全基準

正式上線前必須符合：

<a id="tech-sec-01"></a>
<a id="tech-sec-01-ac-01"></a>
1. 中央平台只允許 HTTPS／WSS。
<a id="tech-sec-02"></a>
<a id="tech-sec-02-ac-01"></a>
2. Daemon 不使用 root 長期執行。
<a id="tech-sec-03"></a>
<a id="tech-sec-03-ac-01"></a>
3. Enrollment Token 一次性或限時。
<a id="tech-sec-04"></a>
<a id="tech-sec-04-ac-01"></a>
4. Node Secret 不明文保存於中央。
<a id="tech-sec-05"></a>
<a id="tech-sec-05-ac-01"></a>
5. Workspace 每次操作都驗證 Root。
<a id="tech-sec-06"></a>
<a id="tech-sec-06-ac-01"></a>
6. Symlink 必須解析。
<a id="tech-sec-07"></a>
<a id="tech-sec-07-ac-01"></a>
7. 前端不可傳任意 Command。
<a id="tech-sec-08"></a>
<a id="tech-sec-08-ac-01"></a>
8. Terminal 原始內容不寫入 Log。
<a id="tech-sec-09"></a>
<a id="tech-sec-09-ac-01"></a>
9. 敏感檔案預設禁止預覽。
<a id="tech-sec-10"></a>
<a id="tech-sec-10-ac-01"></a>
10. Session 建立、接管、終止需 Audit。
<a id="tech-sec-11"></a>
<a id="tech-sec-11-ac-01"></a>
11. WebSocket 必須做身分與權限檢查。
<a id="tech-sec-12"></a>
<a id="tech-sec-12-ac-01"></a>
12. Binary Download 必須驗證 Checksum。
<a id="tech-sec-13"></a>
<a id="tech-sec-13-ac-01"></a>
13. Daemon Config 與 Credential 權限為 `0600`。
<a id="tech-sec-14"></a>
<a id="tech-sec-14-ac-01"></a>
14. 限制單一使用者與 Node 的 Session 數量。
<a id="tech-sec-15"></a>
<a id="tech-sec-15-ac-01"></a>
15. 限制 Terminal Queue 與 Frame 大小。

---

# 24. MVP 技術範圍

MVP 必做：

* FastAPI 中央平台。
* PostgreSQL。
* Vue 管理介面。
* Go Daemon。
* Linux amd64／arm64。
* systemd 安裝。
* Node 註冊與 Heartbeat。
* Claude／Codex 偵測。
* Runtime 切換。
* Workspace 選擇。
* Workspace 安全驗證。
* tmux Session。
* PTY Attach。
* xterm.js。
* Session Reconnect。
* Session Stop。
* File Tree。
* 唯讀檔案預覽。
* 敏感檔案限制。
* 基本 RBAC。
* Audit Log。

MVP 不做：

* Web 編輯檔案。
* 任意 Shell。
* Git Commit／Push。
* CLI 語意解析。
* Agent 自動協作。
* Session 錄影。
* Terminal 全量保存。
* Kubernetes Node。
* 多 Backend 水平擴充。
* Message Broker。
* 多租戶 Billing。
* Token 成本分析。

---

# 25. 最終技術架構

```text
Vue 3 Web
├── Node Management
├── Session Management
├── xterm.js
└── Monaco Editor
          │
          │ HTTPS / WSS
          ▼
FastAPI Central Platform
├── Authentication
├── Node Registry
├── Session Service
├── WebSocket Relay
├── Workspace Relay
├── Enrollment
├── RBAC
└── Audit
          │
          │ Persistent WSS
          ▼
Go Agent Daemon
├── Runtime Registry
├── Claude Runtime
├── Codex Runtime
├── Workspace Validator
├── Filesystem Browser
├── tmux Manager
├── PTY Adapter
├── Session Recovery
├── Installer
└── Updater
          │
          ▼
tmux Session
          │
          ▼
Claude CLI / Codex CLI
```

核心資料流：

```text
使用者選擇 Node
      ↓
選擇 Claude 或 Codex
      ↓
選擇 Workspace
      ↓
Central 建立 Session
      ↓
Daemon 驗證 Runtime 與 Workspace
      ↓
Daemon 建立 tmux Session
      ↓
tmux 啟動 CLI
      ↓
Daemon 透過 PTY Attach
      ↓
Central Relay
      ↓
xterm.js 顯示與操作
```

檔案資料流：

```text
使用者展開 Workspace
      ↓
Central 發送 filesystem.list
      ↓
Daemon 驗證路徑
      ↓
Daemon 讀取目錄
      ↓
Central 回傳結果
      ↓
Vue File Tree 顯示
      ↓
使用者選擇檔案
      ↓
Daemon 驗證大小、類型與敏感規則
      ↓
Monaco Editor 唯讀顯示
```

本技術規劃以最小可行架構完成中央 CLI 管理能力，同時保留後續加入 Git、檔案編輯、Agent 協作、工作排程與多節點擴充的空間。

