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
    （範圍澄清 2026-08-08，ADR 0027：本條**不變且繼續有效**。V2 開放的是任務由 Agent
    **自行認領**——平台掛出工單，Agent 依自己的容量與資格去領；平台仍不做自動指派、
    排程最佳化與負載平衡。卡片上的「指定 Agent」是該 Agent 拉取查詢的一個過濾條件，
    不是推送。見 SCOPE-014。）
<a id="scope-006"></a>
<a id="scope-006-ac-01"></a>
6. 不提供 Web 端完整 IDE。
<a id="scope-007"></a>
<a id="scope-007-ac-01"></a>
7. 不提供第一階段的檔案寫入與編輯功能。
<a id="scope-008"></a>
<a id="scope-008-ac-01"></a>
8. 不提供自動 Git Commit、Push 或 Merge Request。
    （範圍變更 2026-08-08，ADR 0027：本條自 V2.3 起**部分撤銷**。Agent Run 得在受限條件下
    commit 與 push，並得建立 PR／MR；**自動 Merge 仍完全不提供**。撤銷換上的四條約束由
    SCOPE-014 承接，且各配一個實際的 gate。V2.0–V2.2 期間本條仍完全成立，
    因為那三個階段沒有任何 git 程式碼。）
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
<a id="scope-014"></a>
14. Agent 自主執行的產出，每一種離開隔離環境的形式都必須落在**人看過才生效**的位置。
    SCOPE-008 撤銷之後換上的四條約束如下，四條都寫死在 daemon 而非設定值：
<a id="scope-014-ac-01"></a>
    (a) Agent 只能推送到 `cliora/<card_ref>-<run_seq>` 命名空間的分支。
<a id="scope-014-ac-02"></a>
    (b) 永不推送到 base 分支、target 分支或受保護分支，即使任務卡如此宣告。
<a id="scope-014-ac-03"></a>
    (c) **永不自動 Merge**；PR／MR 一律由人審、由人合。
<a id="scope-014-ac-04"></a>
    (d) 派工是拉取式的：Agent 自行認領，平台不做自動指派、排程最佳化或負載平衡。
    （範圍新增 2026-08-08，ADR 0027。四條約束在 V2.0 尚無任何程式碼，
    各自的 gate 於 V2.2–V2.4 接上。）

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

# 8.11 專案管理

專案讓散落在不同 Node 上的 Workspace 成為一個可管理的整體：可以建立、可以綁定跨 Node 的
工作目錄、可以從它進入 Session，並且看得到這個專案上發生過什麼。範圍與取捨見 ADR 0027。

本節的能力由 `CLIORA_PROJECTS_ENABLED` 控制，預設關閉；關閉時系統行為與未導入專案層之前
完全一致。

> **Ad-hoc Session（不屬於任何 Project 的 Session）仍受完整支援，
> 且不會被平台自動歸屬到任何 Project。** 一個 Workspace 路徑可以同時屬於多個 Project，
> 所以由路徑反查專案沒有唯一解；「這是不是 Ad-hoc」必須是建立者的陳述，而不是平台的推論。

<a id="fr-project-001"></a>
## FR-PROJECT-001 Project 生命週期

<a id="fr-project-001-ac-01"></a>
使用者可建立 Project，指定名稱與可選的描述；建立者為擁有者。

<a id="fr-project-001-ac-02"></a>
每個 Project 有一個專案內識別碼（slug），全平台唯一、由名稱產生且可於建立時覆寫，
**建立後不可變更**。

<a id="fr-project-001-ac-03"></a>
Project 狀態有三種：`active`、`paused`、`archived`。**沒有刪除。**

<a id="fr-project-001-ac-04"></a>
`archived` 的 Project 不得建立新的 Session，亦不得新增 Workspace 綁定；
既有的 Session 與綁定一律不受影響，且解綁、改名與檢視歷史仍可進行。

<a id="fr-project-001-ac-05"></a>
建立、更新、狀態變更均須留下稽核紀錄。

<a id="fr-project-002"></a>
## FR-PROJECT-002 Project 與 Workspace 綁定

<a id="fr-project-002-ac-01"></a>
一個 Project 可綁定多個 Workspace，且可跨越不同的 Node；同一個 Workspace 路徑
也可以同時屬於多個 Project。

<a id="fr-project-002-ac-02"></a>
綁定時須以該 Node 的啟用中 Workspace Root 驗證路徑；驗證失敗時拒絕綁定。

<a id="fr-project-002-ac-03"></a>
**綁定是捷徑而非授權。** 任何以綁定路徑發起的操作都必須重新執行同一次驗證，
不得因為該路徑曾經合法而略過。

<a id="fr-project-002-ac-04"></a>
同一組（Project、Node、路徑）重複綁定為冪等操作，回傳既有的綁定而非錯誤。

<a id="fr-project-002-ac-05"></a>
一個 Project 至多有一個主要（primary）綁定。

<a id="fr-project-002-ac-06"></a>
解除綁定不得影響任何進行中的 Session。

<a id="fr-project-002-ac-07"></a>
Node 被移除後，其綁定不再出現於任何回應中；Project 本身不受影響。

<a id="fr-project-002-ac-08"></a>
綁定的可用性須逐列呈現，且至少能區分「Node 離線」與「Root 已停用」兩種原因。

<a id="fr-project-003"></a>
## FR-PROJECT-003 Project 與 Session 關聯

<a id="fr-project-003-ac-01"></a>
建立 Session 時可指定所屬 Project；該欄位為選填，**且永遠為選填**。

<a id="fr-project-003-ac-02"></a>
指定 Project 時，該 Session 的 Workspace 必須是該 Project 的綁定之一；
不符時拒絕建立，不得靜默忽略該欄位。

<a id="fr-project-003-ac-03"></a>
未指定 Project 時，平台不得由 Workspace 推論所屬 Project。

<a id="fr-project-003-ac-04"></a>
Session 列表可依 Project 篩選，並可篩選出未屬於任何 Project 的 Session。

<a id="fr-project-004"></a>
## FR-PROJECT-004 專案活動時間軸

<a id="fr-project-004-ac-01"></a>
Project 建立與更新、Workspace 綁定與解綁、所屬 Session 的起訖，各產生一筆活動事件。

<a id="fr-project-004-ac-02"></a>
活動事件可依專案分頁查詢，順序穩定（同一時刻的事件不得重複出現或遺漏）。

<a id="fr-project-004-ac-03"></a>
不具稽核檢視權限者，取得的活動事件不含操作者身分，且回應須明示該資訊已被隱藏。

<a id="fr-project-004-ac-04"></a>
活動事件的內容不得包含檔案內容、搜尋關鍵字、密碼、權杖或私鑰。

<a id="fr-project-004-ac-05"></a>
活動事件為專案內容而非診斷紀錄，**不設保留期**；專案封存不移除其歷史。

<a id="fr-project-005"></a>
## FR-PROJECT-005 功能旗標與相容性

<a id="fr-project-005-ac-01"></a>
`CLIORA_PROJECTS_ENABLED` 關閉時，所有專案相關的 API 路徑一律回應 404。

<a id="fr-project-005-ac-02"></a>
旗標關閉時，建立 Session 的請求若攜帶專案欄位，須以驗證錯誤拒絕。

<a id="fr-project-005-ac-03"></a>
旗標關閉時，前端導覽與專案層導入前完全一致。

<a id="fr-project-005-ac-04"></a>
旗標的開關不得改變伺服器掛載的路由集合。

<a id="fr-project-005-ac-05"></a>
既有 API 的請求與回應不得移除欄位、改名、變更型別或變更必填性；
專案層只以新增路徑與選填欄位的方式擴充。

---

# 8.12 任務與流程

任務層讓一個 Project 的工作在平台上被寫下來、被推進、被檢核：Epic → User Story → Task
三層、六個車道的看板、就緒條件與審查關卡。範圍與取捨見 ADR 0028。

本節的能力與 §8.11 同受 `CLIORA_PROJECTS_ENABLED` 控制，預設關閉；關閉時系統行為與未導入
任務層之前完全一致。

> **任務資料的真實來源是平台，使用者的 repo 只有程式碼。** 平台在使用者的工作目錄中
> **只寫入平台專屬目錄**（`.cliora/`），且只新增、不覆寫，也不刪除或修改使用者的檔案。

> **卡片上的執行設定（來源與交付模式）是意圖宣告。** 本階段沒有任何執行者會依它行動；
> 依它行動的能力自 V2.3 起分階段提供。

<a id="fr-task-001"></a>
## FR-TASK-001 任務層級與生命週期

<a id="fr-task-001-ac-01"></a>
一個 Project 內可建立 Epic、User Story 與 Task 三層；Task 可指定所屬 User Story，
User Story 可指定所屬 Epic，兩者皆為選填。

<a id="fr-task-001-ac-02"></a>
每個 Epic、User Story 與 Task 有一個專案內唯一、人類可讀的編號（如 `TASK-12`），
由平台配號，**建立後不可變更**；編號不保證連續。

<a id="fr-task-001-ac-03"></a>
指定了 Epic 但未指定 User Story 的 Task，須在藍圖中呈現於該 Epic 的未分類群組；
兩者皆未指定的 Task 須呈現於頂層的未分類群組。**卡片不得因未歸類而不出現。**

<a id="fr-task-001-ac-04"></a>
封存的 Project 不得建立新的 Epic、User Story 或 Task，亦不得修改既有卡片；
檢視歷史不受影響。

<a id="fr-task-001-ac-05"></a>
建立與更新均須留下稽核紀錄，並在該 Project 的活動時間軸產生對應事件。

<a id="fr-task-002"></a>
## FR-TASK-002 看板與車道

<a id="fr-task-002-ac-01"></a>
車道有六個：待辦、阻塞、就緒、進行中、驗證中、完成；卡片可在任意兩個車道之間移動。

<a id="fr-task-002-ac-02"></a>
卡片進入「就緒」或其後任一車道時，其所有前置任務必須均已完成；
不滿足時**拒絕移動，並在錯誤中指名是哪幾張卡片**。

<a id="fr-task-002-ac-03"></a>
就緒條件（七項）未齊備時**不阻擋**移動，但回應須攜帶警告，且畫面須逐項標示缺項。

<a id="fr-task-002-ac-04"></a>
車道的建議並行上限超標時，僅以視覺提示呈現，**不得阻擋**。

<a id="fr-task-002-ac-05"></a>
看板回應**不得包含**驗收標準全文與審查關卡明細；那是任務詳情的內容。

<a id="fr-task-003"></a>
## FR-TASK-003 併發與相依

<a id="fr-task-003-ac-01"></a>
更新一張卡片須攜帶其版本；版本不符時拒絕，且**不得寫入任何一部分變更**。

<a id="fr-task-003-ac-02"></a>
版本衝突的回應須附上該卡片的現值，使呼叫端不需再次查詢即可重新呈現。

<a id="fr-task-003-ac-03"></a>
相依關係不得形成循環；建立時偵測並拒絕，錯誤須指出形成循環的路徑。

<a id="fr-task-003-ac-04"></a>
一張卡片不得相依於自己。

<a id="fr-task-004"></a>
## FR-TASK-004 就緒條件與審查關卡

<a id="fr-task-004-ac-01"></a>
就緒條件七項與審查關卡六項由平台提供的流程定義決定；本階段為全域單一定義，不可由專案覆寫。

<a id="fr-task-004-ac-02"></a>
勾選審查關卡須具備核准權限，且**操作者必須是人類**；非人類憑證一律拒絕。

<a id="fr-task-004-ac-03"></a>
每個已勾選的關卡須記錄核准者與核准時間，並可於畫面上看到。

<a id="fr-task-004-ac-04"></a>
取消核准與核准同權限，且同樣留下稽核紀錄。

<a id="fr-task-004-ac-05"></a>
未啟用第三方隧道整合時，涉及畫面預覽的關卡須**自動停用**（不得倚賴管理者手動關閉），
且停用原因須在專案設定中明白呈現。

<a id="fr-task-005"></a>
## FR-TASK-005 需求、規格與拆解（人工流程）

<a id="fr-task-005-ac-01"></a>
使用者可以一句自然語言的敘述提出需求，不強制填寫其他欄位。

<a id="fr-task-005-ac-02"></a>
規格為版本列，只新增不修改；每一版記錄撰寫者與時間。

<a id="fr-task-005-ac-03"></a>
規格存在未解決的開放問題時**不得核准**，且拒絕須指名是哪幾個問題。

<a id="fr-task-005-ac-04"></a>
未核准的規格不得被拆解為任務提案；此限制須由 API 強制，不得僅由畫面隱藏。

<a id="fr-task-005-ac-05"></a>
任務提案可全部、部分或編輯後接受；被拒絕的提案須保留其理由。

<a id="fr-task-005-ac-06"></a>
接受提案所建立的卡片，其就緒條件若不齊備，**須落在待辦而非就緒**，並說明原因。

<a id="fr-task-005-ac-07"></a>
由提案建立的卡片須可回溯至來源需求與提案。

<a id="fr-task-006"></a>
## FR-TASK-006 Task 與 Session 關聯

<a id="fr-task-006-ac-01"></a>
建立 Session 時可指定所屬 Task；該欄位為選填，**且永遠為選填**。

<a id="fr-task-006-ac-02"></a>
指定 Task 時必須同時指定 Project，且該 Task 必須屬於該 Project；不符時拒絕建立。

<a id="fr-task-006-ac-03"></a>
平台不得由 Workspace 或 Session 反查所屬 Task。

<a id="fr-task-006-ac-04"></a>
任務詳情須顯示其歷史 Session（含已結束者）；Session 詳情須顯示所屬 Task。

<a id="fr-task-007"></a>
## FR-TASK-007 任務情境投影

<a id="fr-task-007-ac-01"></a>
Session 建立後，平台將任務情境、流程說明與該 Session 的憑證寫入工作目錄下的
**平台專屬目錄**；平台不得寫入該目錄以外的任何路徑。

<a id="fr-task-007-ac-02"></a>
情境包須包含任務目標、範圍、逐項驗收標準、相依任務與其狀態，且**不得超過 4 KB**；
超出時須保留驗收標準並明示已省略的內容與取得方式，不得靜默截斷。

<a id="fr-task-007-ac-03"></a>
投影**不得覆寫**任何既有檔案；同版本的流程說明已存在時視為成功。

<a id="fr-task-007-ac-04"></a>
投影失敗不得使 Session 建立失敗；失敗須記錄並在畫面上提供重試。

<a id="fr-task-007-ac-05"></a>
Node 的 daemon 版本不支援投影時，Session 須照常建立，並顯示可行動的升級說明。

<a id="fr-task-007-ac-06"></a>
投影產生的檔案有保留期並由 daemon 清理；清理**不得**觸及使用者上傳的檔案與
使用者可能擁有的 `.gitignore`。

<a id="fr-task-007-ac-07"></a>
投影完成後，於使用者的版本控制中不得出現任何未被忽略的新檔案。

<a id="fr-task-008"></a>
## FR-TASK-008 Session 憑證

<a id="fr-task-008-ac-01"></a>
每個 Session 發行至多一枚憑證，範圍限於該 Session 所屬的單一 Project。

<a id="fr-task-008-ac-02"></a>
憑證的權限範圍在發行時固定，且**永遠不含**審查關卡核准、專案管理、檔案與終端相關動作。

<a id="fr-task-008-ac-03"></a>
Session 進入任一終止狀態時憑證立即失效；憑證另有效期上限。

<a id="fr-task-008-ac-04"></a>
憑證只以不可逆的形式儲存；**任何 API 回應、日誌、稽核紀錄或畫面都不得出現憑證值**。

<a id="fr-task-008-ac-05"></a>
以憑證進行的寫入，其稽核與活動紀錄須標示為非人類操作者，**不得冒用任何人類身分**。

<a id="fr-task-008-ac-06"></a>
平台不可用時，使用憑證的工具須直接失敗而非排隊補送，且其訊息須說明 Session 本身可繼續工作。

---

# 8.13 Agent Runner

任務層讓工作被寫下來；本節讓工作在**沒有人看著**的情況下被推進：一張就緒的卡片可以被派成
工單，一台已納管節點上的 Runner 自己領走、把該專案登記的程式碼取到一個**平台自己擁有的
隔離目錄**、在那裡非互動地執行、把過程與成果送回卡片。範圍與取捨見 ADR 0029、0030、0031。

本節的能力受 `CLIORA_AGENT_RUNS_ENABLED` 控制，預設關閉，且**外層仍受
`CLIORA_PROJECTS_ENABLED` 控制**；兩者皆關閉時，系統行為與未導入 Agent Runner 之前完全一致。

> **本階段的授權邊界是「納管」。** 任何一台已納管節點上的 Runner 都能領任何專案的卡片、
> 取任何專案的程式碼。**這是一個被接受的姿態，不是缺陷**；逐專案的授權自 V2.3 起提供。
> 節點納管本身是管理者專屬的動作。

> **Agent 在沙箱內對 git 的操作不受平台限制，包含推送。** 平台自己一次推送都不執行。
> 平台提供的是**可觀測性**（本次執行對得上哪個遠端、有幾個提交尚未推送），不是阻擋。

> **執行不使用工作區綁定。** 工作區綁定自本階段起只服務互動式 Session。

<a id="fr-agent-001"></a>
## FR-AGENT-001 Runner 註冊

<a id="fr-agent-001-ac-01"></a>
Runner 是既有節點程式的一種模式；**不得新增任何建立信任關係的流程**，
納管、節點憑證、對外連線、心跳、診斷與更新一律沿用既有機制。

<a id="fr-agent-001-ac-02"></a>
Runner 的上線狀態即該節點的上線狀態；**不得另設一套心跳或另一個線上旗標**。

<a id="fr-agent-001-ac-03"></a>
一台節點至多對應一列 Runner；其可執行的執行環境是一個集合，
並行上限與等待上限皆為節點層級。

<a id="fr-agent-001-ac-04"></a>
節點須回報自己是否為**專用 Runner**（未設定任何 Allowed Root），
且該狀態須在管理畫面上明白呈現；混合用途須以警示樣式呈現並說明其後果。

<a id="fr-agent-001-ac-05"></a>
未具備 Runner 能力的舊版節點須繼續正常提供互動式 Session，且永不被指派工單。

<a id="fr-agent-003"></a>
## FR-AGENT-003 任務認領

<a id="fr-agent-003-ac-01"></a>
認領是 Runner 主動的；**平台不得推送、不得自動指派、不得排程最佳化或負載平衡**。

<a id="fr-agent-003-ac-02"></a>
資格判定為**四條件**且全部成立才成立：卡片在「就緒」車道、其所有前置任務均已完成、
所需執行環境為該 Runner 所具備、該卡未指定 Runner 或指定的正是該 Runner。

<a id="fr-agent-003-ac-03"></a>
本階段的授權邊界是**節點納管**：任一已納管節點上的 Runner 皆可領取任何專案的卡片。
此姿態須同時出現在權限模組的註解與管理畫面上，**不得只寫在文件裡**。

<a id="fr-agent-003-ac-04"></a>
兩個 Runner 同時對同一張卡片提出認領時，**只有一個成立**；
該卡的執行紀錄中至多一列帶有 Runner。

<a id="fr-agent-003-ac-05"></a>
本階段不比對標籤，也不檢查專案與 Agent 的綁定；Runner 的標籤與卡片要求的標籤**顯示但不比對**。

<a id="fr-agent-004"></a>
## FR-AGENT-004 租約與重排

<a id="fr-agent-004-ac-01"></a>
執行中的工單持有租約並週期續租；租約逾時者標記為失聯，其嘗試次數加一並重新排入佇列。

<a id="fr-agent-004-ac-02"></a>
重排次數達上限（三次）後，卡片進入「阻塞」車道，並記錄可讀的原因。

<a id="fr-agent-004-ac-03"></a>
被指定 Runner 的卡片重排後**仍只提供給原本被指定的那一個**，不得退回給任意 Runner。

<a id="fr-agent-004-ac-04"></a>
租約回收須能跨平台重啟後仍然生效，不得倚賴僅存在於記憶體中的計時器。

<a id="fr-agent-005"></a>
## FR-AGENT-005 Run 生命週期

<a id="fr-agent-005-ac-01"></a>
Run 有自己的狀態機；**執行過程不得寫入任何 Session 紀錄**——
一次完整的派工與執行前後，Session 資料表的列數必須不變。

<a id="fr-agent-005-ac-02"></a>
Run 不得使用互動式終端的傳輸路徑、不佔用寫入者名額、不建立終端多工工作階段。

<a id="fr-agent-005-ac-03"></a>
三個計時器各自回答不同的問題且不得混用：租約回答「Runner 是否還在」（逾時即重排）、
閒置回答「子程序是否仍在前進」（逾時即終止但不重排）、牆鐘僅為兜底。
**一個仍在工作但很慢的 Run 不得被判定為死亡。**

<a id="fr-agent-005-ac-04"></a>
存活判定以執行環境提供的**事件流**為準，不以牆鐘為準。
無法取得事件流的執行環境視為不具備 Runner 能力，**不得退回牆鐘判定**。

<a id="fr-agent-005-ac-05"></a>
取消一個 Run 須終止其**整個程序群組**；終止後該程序群組下不得殘留任何程序。

<a id="fr-agent-005-ac-06"></a>
等待人類回覆的 Run 續租但不累計執行逾時，**且不佔用並行執行上限**；
逾時未獲回覆者，卡片退回「阻塞」車道。

<a id="fr-agent-006"></a>
## FR-AGENT-006 Run 記錄

<a id="fr-agent-006-ac-01"></a>
Run 記錄有大小上限；超過時**自中間截斷**並明示被丟棄的位元組數。

<a id="fr-agent-006-ac-02"></a>
Run 記錄的內容是執行環境的**結構化事件流**而非終端位元組；截斷不得切斷一筆事件。

<a id="fr-agent-006-ac-03"></a>
所有 Run 記錄在離開節點前都須經過去識別處理的掛勾點，
即使本階段沒有可去識別的內容，該掛勾點仍須存在並被測試涵蓋。

<a id="fr-agent-006-ac-04"></a>
Run 記錄有保留期（成功較短、失敗較長）並自動刪除；
**互動式 Session 不儲存終端內容的承諾不因本節而改變**。

<a id="fr-agent-006-ac-05"></a>
Run 記錄的傳送不得使互動式終端的回應延遲明顯變差；
判準是同一台節點上的終端回應時間 p95 不劣於升級前基線 20% 以上。

<a id="fr-agent-007"></a>
## FR-AGENT-007 看板溝通

<a id="fr-agent-007-ac-01"></a>
Agent 可在卡片上留言；訊息串須能區分人類、Agent 與系統三種來源。

<a id="fr-agent-007-ac-02"></a>
Agent 可在卡片上提問；提問後該 Run 進入等待回覆狀態，卡片明白顯示「等待你的回覆」。

<a id="fr-agent-007-ac-03"></a>
人類回覆後，Agent 須能取得該回覆並繼續執行。

<a id="fr-agent-007-ac-04"></a>
逾時（24 小時）未獲回覆的提問，卡片自動退回「阻塞」車道並記錄原因。

<a id="fr-agent-008"></a>
## FR-AGENT-008 指定 Agent

<a id="fr-agent-008-ac-01"></a>
派工時可指定也可不指定 Agent，**預設不指定**。

<a id="fr-agent-008-ac-02"></a>
指定一個已停用或執行環境不符的 Agent 時，派工當下即拒絕且**不進入佇列**，
錯誤訊息須指名是哪一項條件不符。

<a id="fr-agent-008-ac-03"></a>
指定的 Agent 目前離線時**接受派工並進入佇列**，卡片顯示等待該 Agent 且標示其離線；
此文案與「目前沒有符合資格的 Agent」**必須不同**。

<a id="fr-agent-008-ac-04"></a>
本階段做不到的宣告須在派工當下拒絕並說明自哪一個階段起生效，
不得接受後靜默忽略。

<a id="fr-agent-009"></a>
## FR-AGENT-009 任務卡產物

<a id="fr-agent-009-ac-01"></a>
Run 執行期間隨時可附加產物；附加能力不以卡片上的交付宣告為前提。

<a id="fr-agent-009-ac-02"></a>
產物儲存於平台而非節點；**節點上的執行目錄被回收之後，產物仍可下載**。

<a id="fr-agent-009-ac-03"></a>
產物不可變更：沒有任何介面可以修改一件已附加的產物。
刪除須具備專案管理權限、須填寫理由並留下稽核紀錄。

<a id="fr-agent-009-ac-04"></a>
產物有三層配額：單件大小、單次執行件數、專案總量；超過時明確拒絕並說明是哪一層。

<a id="fr-agent-009-ac-05"></a>
**平台不保證產物不含機密。** 去識別只對記錄的文字串流有效，
畫面文案不得暗示產物已被清理。

<a id="fr-agent-010"></a>
## FR-AGENT-010 產物的安全提供

<a id="fr-agent-010-ac-01"></a>
產物的下載回應一律標示為附件並禁止內容型別嗅探；
內容型別由伺服器判定，**不採信上傳者的宣告**。

<a id="fr-agent-010-ac-02"></a>
只有圖片、純文字與 Markdown 可在畫面內預覽，且 Markdown 以純文字提供。

<a id="fr-agent-010-ac-03"></a>
**應用程式來源內沒有任何路徑會渲染產物內容**——包含在新分頁開啟。
此否定命題以兩個機器判定的清單證明：伺服器介面清單與前端路由清單，
兩者皆須與升級前的基線比對。

<a id="fr-agent-010-ac-04"></a>
產物的存取權限繼承其所屬專案，不另設更寬鬆的路徑。

<a id="fr-agent-011"></a>
## FR-AGENT-011 隔離工作目錄

<a id="fr-agent-011-ac-01"></a>
執行目錄由節點程式自己建立，**不在任何 Allowed Root 之內，兩個方向皆然**；
既有的檔案介面對執行目錄一律拒絕存取。

<a id="fr-agent-011-ac-02"></a>
執行目錄的根路徑落在任何 Allowed Root 之內時，
節點程式**須拒絕以 Runner 模式啟動並指名是哪一條**，不得只印警告後照常啟動。

<a id="fr-agent-011-ac-03"></a>
節點須回報自己是否為專用 Runner，並由平台呈現；
**平台不宣稱能阻止執行中的程序讀取 Allowed Root**，該部分由部署姿態承擔。

<a id="fr-agent-011-ac-04"></a>
執行目錄每次執行都是全新的，不重複使用、不共用；
並具備單次執行與節點總量兩層容量上限，以及一條磁碟餘裕水位。

<a id="fr-agent-011-ac-05"></a>
容量上限用盡時**停止領取新工單並回報原因**，不得表現為節點離線。

<a id="fr-agent-011-ac-06"></a>
執行目錄依結果保留一段期間後由節點程式自動回收（成功較短、失敗較長）；
**執行憑證檔案於執行結束時立即刪除，不等保留期**。

<a id="fr-agent-011-ac-07"></a>
平台的任何路徑都不寫入使用者的工作區：一次完整執行的前後，
該專案所綁定的每一個工作區的版本控制狀態都必須為空。

<a id="fr-agent-012"></a>
## FR-AGENT-012 自行取得程式碼

<a id="fr-agent-012-ac-01"></a>
卡片宣告需要程式碼時，節點程式依該專案登記的儲存庫取得程式碼至執行目錄，
並回報取得的版本識別；同一儲存庫的第二次執行不得重新完整取得。

<a id="fr-agent-012-ac-02"></a>
取得程式碼的指令參數來自一張封閉表，**沒有任何一個參數來自請求內容、
卡片的自由文字欄位或 Agent 的輸出**；儲存庫位置是平台設定而非呼叫端字串。

<a id="fr-agent-012-ac-03"></a>
儲存庫位置的通訊協定與主機須通過允許清單檢查，
且**位置本身不得包含帳號密碼資訊**（以分欄儲存使其無法表示）。

<a id="fr-agent-012-ac-04"></a>
節點缺少必要的存取憑證時，取得程式碼須**於數秒內失敗**並回報明確的錯誤代碼，
不得掛在互動式提示上直到牆鐘逾時。

<a id="fr-agent-012-ac-05"></a>
每一次執行結束時，摘要須記錄得出這次執行**有沒有動到遠端**：
對應的遠端位置（帳號密碼資訊須遮蔽）與尚未推送的提交數。

<a id="fr-agent-012-ac-06"></a>
執行所產生的提交，其作者身分為機器身分，**不得冒用任何人類身分，也不得偽裝為平台**。

<a id="fr-agent-013"></a>
## FR-AGENT-013 變更不得靜默丟棄

<a id="fr-agent-013-ac-01"></a>
卡片宣告不交付或僅交付產物，而執行結束時工作目錄有變更時，
變更內容須自動附加為一件產物。

<a id="fr-agent-013-ac-02"></a>
該情況須在執行摘要中明白記載「宣告不交付，但偵測到變更」與變更的檔案數。

<a id="fr-agent-013-ac-03"></a>
未被追蹤的新檔案**只計數不打包**，且須在摘要中說明有幾個未附加，
由人決定如何處理。

---

# 8.14 專案機密、tag 派工與 git 送回

Agent Runner 讓工作在沒有人看著的情況下被推進；本節讓那件工作**帶著平台管理的機密**執行、
讓「這類卡片給這類機器」成為派工的一個條件、並讓成果**以一條分支送回**。
範圍與取捨見 ADR 0032（機密與 SEC-002 修訂）、ADR 0031 增補（git 送回）、ADR 0029 增補（tag 派工）。

本節的能力受 `CLIORA_AGENT_RUNS_ENABLED` 控制；**其中 git 憑證的下放另受
`CLIORA_GIT_SECRET_DELIVERY_ENABLED` 控制且預設關閉**。

> **授權邊界永久是「納管」。** 任何一台已納管節點上的 Runner 只要 tag 對得上，
> 就能領任何專案的卡片、**並取得那張卡宣告的機密**。
> **這是被接受的姿態，不是缺陷，而且不會有逐專案的授權**——縮小影響範圍的是
> 卡片級的機密宣告、節點端的拒收、可撤銷與下放稽核、以及納管畫面上的明白告知。
> **tag 決定派給哪台機器，不決定哪台機器可以拿機密。**

> **git 認證預設由節點擁有者自行配置，平台不管理。** 平台自本節起會代表卡片執行推送，
> 而在預設組態下它用的是那台機器既有的憑證——**五條硬約束仍然完整成立**
> （它們約束的是推什麼），但「可撤銷」在那條路徑上不成立。

<a id="fr-runenv-001"></a>
## FR-RUNENV-001 專案機密的保管

<a id="fr-runenv-001-ac-01"></a>
機密以加密形式保存；**任何介面、任何回應都不得讀回它的值**。
此性質須同時以「回應內容不含值」與「介面定義中不存在值欄位」兩種方式驗證。

<a id="fr-runenv-001-ac-02"></a>
清單只呈現名稱、類型、建立者、建立與輪替時間、最後使用時間。
**不得呈現長度、指紋或任何可用以推測值的資訊。**

<a id="fr-runenv-001-ac-03"></a>
名稱在專案內唯一；**軟刪除之後同名可以重新建立**。

<a id="fr-runenv-001-ac-04"></a>
名稱須為大寫字母、數字與底線，並拒絕會覆寫執行環境基本設定的名稱
（如系統路徑與家目錄變數）與平台保留的前綴。

<a id="fr-runenv-001-ac-05"></a>
輪替即覆寫值；**名稱與類型不可變更**。

<a id="fr-runenv-001-ac-06"></a>
刪除為軟刪除並立即生效於下一次派工；**進行中的執行不受影響**。
刪除的確認須說明平台只停止下放，**來源系統上的撤銷仍須另外執行**。

<a id="fr-runenv-001-ac-07"></a>
被 repository 引用中的機密不得刪除，拒絕訊息須指名是哪一個 repository。

<a id="fr-runenv-002"></a>
## FR-RUNENV-002 加密與主金鑰

<a id="fr-runenv-002-ac-01"></a>
採信封加密：每一筆機密各有一把資料金鑰，資料金鑰以主金鑰包裝後與密文同列保存。

<a id="fr-runenv-002-ac-02"></a>
金鑰版本自第一筆資料起即存在；輪替主金鑰時**只重新包裝資料金鑰**，密文不得被重寫。

<a id="fr-runenv-002-ac-03"></a>
主金鑰缺少、格式錯誤、長度不足或等於開發預設值時，**在啟動時拒絕並指名是哪一種**；
此檢查**僅在 Agent 執行功能啟用時生效**。

<a id="fr-runenv-002-ac-04"></a>
舊金鑰版本的資料在舊金鑰仍存在時可解；舊金鑰不存在時的錯誤須**指名缺少哪一個版本**。

<a id="fr-runenv-002-ac-05"></a>
主金鑰遺失即所有機密不可復原。此後果須**直接呈現在機密設定畫面上**，
不得只記載於維運手冊。

<a id="fr-runenv-003"></a>
## FR-RUNENV-003 按需下放與稽核

<a id="fr-runenv-003-ac-01"></a>
下放發生在**認領當下**，且只送出該卡片宣告的那幾個。

<a id="fr-runenv-003-ac-02"></a>
卡片宣告的名稱必須是專案允許清單的子集；**卡片編輯時與派工時各驗一次**，
且兩者的拒絕訊息須分得出「名稱不被允許」與「機密尚未建立」。

<a id="fr-runenv-003-ac-03"></a>
每一次下放記錄一筆稽核，含執行、專案、Runner 與**名稱**；
**不得含值、長度或指紋**。

<a id="fr-runenv-003-ac-04"></a>
Runner 於下放後放棄該工單時，稽核**如實記為已下放**，不得回頭刪除。

<a id="fr-runenv-003-ac-05"></a>
派工訊息在送出前須驗證其大小；超出上限時**釋放認領並在卡片上說明**，
不得靜默丟棄後等待租約逾時。

<a id="fr-runenv-003-ac-06"></a>
情境包須列出本次執行可用的機密**名稱**，並說明不要將值輸出。

<a id="fr-runenv-004"></a>
## FR-RUNENV-004 節點端的去識別與拒收

<a id="fr-runenv-004-ac-01"></a>
機密在節點上**只存在於記憶體**，以環境變數交給執行程序，**不寫入任何檔案**。

<a id="fr-runenv-004-ac-02"></a>
節點在送出任何訊息之前，對其中的字串**逐一替換已知的機密值**；
涵蓋範圍不限於執行紀錄，亦包含錯誤訊息與摘要。

<a id="fr-runenv-004-ac-03"></a>
去識別為**盡力而為**：經過編碼的值可能漏網。
此限制須明白記載，且第二道保障是「可撤銷」與「保留期」。

<a id="fr-runenv-004-ac-04"></a>
節點可宣告不收機密；該節點的 Runner **永不被派發宣告了機密的卡片**，
且此情況不得使等待原因被顯示為「沒有可用的 Agent」。

<a id="fr-runenv-007"></a>
## FR-RUNENV-007 git 送回的五條硬約束

<a id="fr-runenv-007-ac-01"></a>
平台只能推送 `cliora/<卡片編號>-<執行序號>` 前綴的分支。

<a id="fr-runenv-007-ac-02"></a>
永不推送基準分支或目標分支。

<a id="fr-runenv-007-ac-03"></a>
永不強制推送、永不刪除遠端分支、永不動標籤。
此性質以「那些參數不存在於指令表中」實作，而非以檢查它們不存在實作。

<a id="fr-runenv-007-ac-04"></a>
只能推送到該專案登記的 repository 主機。

<a id="fr-runenv-007-ac-05"></a>
四種違規**全部在節點內被拒**，且拒絕發生在指令被執行之前。

<a id="fr-runenv-007-ac-06"></a>
五條約束**與使用哪一種憑證無關**：它們約束的是推送什麼。

<a id="fr-runenv-007-ac-07"></a>
提交的作者身分為機器身分（硬性）；來源標註以掛勾附加（**盡力而為**）。
兩者的保證等級不同，須分別記載。

<a id="fr-runenv-007-ac-08"></a>
推送失敗不使該次執行失敗，但**須在摘要中明白說出**。

<a id="fr-runenv-009"></a>
## FR-RUNENV-009 平台管理的 git 憑證（預設關閉）

<a id="fr-runenv-009-ac-01"></a>
此能力由環境變數控制且**預設關閉**；關閉時 git 類型的機密**不得建立**，
拒絕訊息須指名該變數。

<a id="fr-runenv-009-ac-02"></a>
關閉時 repository 的認證方式只能是「使用該機器既有的認證」。

<a id="fr-runenv-009-ac-03"></a>
關閉時派工訊息不得攜帶 git 類型的機密。

<a id="fr-runenv-009-ac-04"></a>
關閉時**不得改寫執行程序的家目錄或 git 全域設定**；
機器既有的認證須原樣可用。

<a id="fr-runenv-009-ac-05"></a>
啟用時，權杖不得出現在遠端位址、提交紀錄、行程參數或任何錯誤訊息中。

<a id="fr-runenv-009-ac-06"></a>
啟用時，私鑰**永不寫入磁碟**；代理程式的通訊端不是金鑰，
且執行結束後不得殘留任何代理程式行程。

<a id="fr-runenv-009-ac-07"></a>
啟用時，未知主機須被主機金鑰檢查拒絕。

<a id="fr-runenv-009-ac-08"></a>
既有憑證的隔離**只在本次執行真的收到平台憑證時才套用**。

<a id="fr-runenv-009-ac-09"></a>
以 SSH 認證的 repository 無法建立合併請求；此後果須在**設定畫面上**說明。

<a id="fr-runenv-008"></a>
## FR-RUNENV-008 tag 派工

<a id="fr-runenv-008-ac-01"></a>
資格判定為**五條件**：卡片在就緒車道、前置任務均已完成、執行環境相符、
**tag 相符**、未指定 Runner 或指定的正是該 Runner。

<a id="fr-runenv-008-ac-02"></a>
tag 採**超集比對**：卡片所需的 tag 是該 Runner 所具備 tag 的子集即成立；
Runner 多出的 tag 不影響。

<a id="fr-runenv-008-ac-03"></a>
Runner 可宣告只領取有宣告 tag 的卡片；該設定關閉時仍能領取未宣告 tag 的卡片。

<a id="fr-runenv-008-ac-04"></a>
註冊訊息未攜帶上述兩項宣告時一律視為預設值，**升級前後行為一致**。

<a id="fr-runenv-008-ac-05"></a>
指定一個 tag 不符的 Runner 時，**派工當下即拒絕並指名缺少哪幾個 tag**，且不入佇列。

<a id="fr-runenv-008-ac-06"></a>
無任何 Runner 湊得齊某卡片的 tag 時，畫面須說出**缺少哪幾個 tag**，
不得只顯示「等待可用的 Agent」。

<a id="fr-runenv-008-ac-07"></a>
比對在平台端進行；**「這張卡為什麼沒人領」必須在平台端答得出來**。

<a id="fr-runenv-008-ac-08"></a>
tag 由節點的設定檔宣告，**平台端唯讀**，不得經由介面編輯。

<a id="fr-runenv-010"></a>
## FR-RUNENV-010 授權邊界的誠實揭露

<a id="fr-runenv-010-ac-01"></a>
發出納管權杖的畫面須直接寫明：
**「這台機器將可以領取任何專案的卡片，並取得那些卡片宣告的機密。」**
該句須位於發出權杖的表單之內。

<a id="fr-runenv-010-ac-02"></a>
Agent 管理畫面須寫明授權邊界是納管，**並寫明 tag 不是授權**。

<a id="fr-runenv-010-ac-03"></a>
**tag 欄位周邊不得出現鎖頭圖示或「授權」字樣。**

<a id="fr-runenv-010-ac-04"></a>
機密頁不得提供顯示值或複製值的功能。

<a id="fr-runenv-010-ac-05"></a>
以上四項為**畫面上的可驗證性質**，不得只以文件承諾。

<a id="fr-runenv-011"></a>
## FR-RUNENV-011 機密的類型決定它的去向

<a id="fr-runenv-011-ac-01"></a>
一般環境變數類型的機密進入執行程序的環境。

<a id="fr-runenv-011-ac-02"></a>
git 憑證類型的機密**只進入節點自身的 git 環境，永不進入執行程序的環境**。

<a id="fr-runenv-011-ac-03"></a>
用於建立合併請求的憑證類型在本階段**不下放**。

<a id="fr-runenv-011-ac-04"></a>
上述分流的後果須明白記載：執行程序無法以平台憑證自行取得或推送。

---

# 8.15 交付、驗證與完成判準

前一節讓工作帶著機密執行並把分支送回。本節回答兩個平台先前答不出來的問題：
**這張卡的成果該以哪一種形式離開**，以及**這件事憑什麼算做完**。
範圍與取捨見 ADR 0033（交付模式、驗證與 Done Gate）、ADR 0029 增補 C（節點能力宣告）、
ADR 0031 增補 B（`existing_pr` 的分支來源）、ADR 0032 增補 A（供應商憑證的使用路徑）。

本節的能力受 `CLIORA_AGENT_RUNS_ENABLED` 控制。

> **平台永不自動合併、永不核可自己建立的合併請求、永不關閉他人的合併請求、永不動標籤。**
> 這四件事以**路徑不存在**的形式成立（動作表裡沒有那個字），不是以檢查的形式成立。

> **平台會以一個身分在他人的儲存庫上留下痕跡，而那個身分不是派工的人**——
> 它是供應商憑證的擁有者。合併請求的內文須直接寫出這件事，
> 因為讀到它的人沒有本平台的帳號。

<a id="fr-delivery-001"></a>
## FR-DELIVERY-001 五種交付模式

<a id="fr-delivery-001-ac-01"></a>
卡片以兩個獨立欄位宣告「要不要程式碼」與「成果怎麼離開」；兩者互不決定對方。

<a id="fr-delivery-001-ac-02"></a>
交付模式有五種：不交付、以產物交付、以分支交付、以合併請求交付、以既有合併請求交付。

<a id="fr-delivery-001-ac-03"></a>
不交付與以產物交付**不得產生任何遠端變更**；此性質須以遠端狀態驗證，不得以紀錄驗證。

<a id="fr-delivery-001-ac-04"></a>
以既有合併請求交付**只適用於平台自己建立的合併請求**；
其餘情形須在**派工當下**拒絕，且訊息須說明平台只推送至專屬命名空間之內。

<a id="fr-delivery-001-ac-05"></a>
儲存庫所在主機不受支援時，於**派工當下**拒絕並指名該主機。

<a id="fr-delivery-001-ac-06"></a>
以合併請求交付但未指定目標分支時，於派工當下拒絕。

<a id="fr-delivery-002"></a>
## FR-DELIVERY-002 交付的誠實性

<a id="fr-delivery-002-ac-01"></a>
宣告不交付程式碼變更（不交付、以產物交付）而工作目錄確有變更時，
結果須明示變更檔案數，**且該差異須附為一件卡片產物**，不得靜默丟棄。
**兩種模式皆適用。**

<a id="fr-delivery-002-ac-02"></a>
以合併請求交付但無任何變更時，執行視為成功、結論為「無變更」，
且**不得呼叫供應商介面**。

<a id="fr-delivery-002-ac-03"></a>
宣告以產物交付卻未產生任何產物時，**該次執行不算成功**，且結果須說明缺少什麼。

<a id="fr-delivery-002-ac-04"></a>
未追蹤的新檔案只計數、不打包；理由須可讀。

<a id="fr-delivery-003"></a>
## FR-DELIVERY-003 合併請求的建立與失敗處置

<a id="fr-delivery-003-ac-01"></a>
合併請求由平台端建立；**供應商憑證永不下放至節點**。

<a id="fr-delivery-003-ac-02"></a>
建立發生在**確認分支確實已推送之後**，且不得在節點連線的接收迴圈內進行。

<a id="fr-delivery-003-ac-03"></a>
內文由平台產生，含目標、逐項驗收結果、驗證摘要（含來源與由誰指定）、殘留風險、
執行連結，以及**建立者身分的揭露**。

<a id="fr-delivery-003-ac-04"></a>
失敗（權限不足、目標不存在、供應商不可達）時：分支仍在、結果標示為僅交付分支、
原因可讀，**該次執行不算失敗**。

<a id="fr-delivery-003-ac-05"></a>
同一來源分支已有合併請求時視為**已交付**並指向既有的那一個，不得重複建立。

<a id="fr-delivery-003-ac-06"></a>
逾時**不得重試**；建立不是冪等操作，重試會產生第二個合併請求。

<a id="fr-delivery-003-ac-07"></a>
對外呼叫須有主機允許清單、連線與總計逾時、同時進行數上限，
以及**待處理佇列的上限與可見性**；憑證不得出現在任何紀錄中。

<a id="fr-delivery-004"></a>
## FR-DELIVERY-004 不做的事

<a id="fr-delivery-004-ac-01"></a>
自動合併的程式碼路徑**不存在**；以節點 git 子命令表與平台供應商動作表兩處斷言。

<a id="fr-delivery-004-ac-02"></a>
核可、關閉、標籤、發行等動作皆不在供應商動作表內。

<a id="fr-delivery-004-ac-03"></a>
不存在「對任意節點執行任意命令」的介面。

<a id="fr-delivery-004-ac-04"></a>
交付模式為封閉集合；新增一種模式須同時在派工、派工訊息組裝、完成判準與執行詳情四處具備分支。

<a id="fr-plan-001"></a>
## FR-PLAN-001 執行計畫

<a id="fr-plan-001-ac-01"></a>
執行計畫以版本列保存，**只新增不修改**；畫面顯示最新一版，歷史可展開。

<a id="fr-plan-001-ac-02"></a>
第二版起**必須附上變更理由**。

<a id="fr-plan-001-ac-03"></a>
步驟狀態為五值：待辦、進行中、已完成、略過、失敗；略過與失敗**不得以相同樣式呈現**。

<a id="fr-plan-001-ac-04"></a>
兩個並行提交撞上同一版本序時自動重試一次，第二次才回報衝突。

<a id="fr-verify-001"></a>
## FR-VERIFY-001 驗證報告

<a id="fr-verify-001-ac-01"></a>
報告結果為五值：未開始、進行中、通過、失敗、部分通過；部分通過**不得看起來像通過**。

<a id="fr-verify-001-ac-02"></a>
不合格的報告不得寫入半筆；拒絕須指名欄位。

<a id="fr-verify-001-ac-03"></a>
失敗項**不得摺疊或省略**，且排序在通過項之前。

<a id="fr-verify-001-ac-04"></a>
驗證命令由平台在執行目錄內執行，**擷取真實結束碼**；命令以引數陣列表示，不經命令殼。

<a id="fr-verify-001-ac-05"></a>
逾時的命令記為特別的結束碼並繼續執行其餘命令；
剩餘執行時間不足時**略過並說明**，不得靜默略過。

<a id="fr-verify-001-ac-06"></a>
命令輸出僅保留尾段，且**須經去識別**後才離開節點。

<a id="fr-verify-002"></a>
## FR-VERIFY-002 證據可信度分級

<a id="fr-verify-002-ac-01"></a>
可信度分三級：Agent 自述、平台紀錄、機器事實；**由伺服器端依寫入路徑判定**。

<a id="fr-verify-002-ac-02"></a>
請求內容中的來源欄位**一律忽略**，且忽略時**須留下一筆時間軸紀錄**。

<a id="fr-verify-002-ac-03"></a>
機器事實**只有一個寫入點**。

<a id="fr-verify-002-ac-04"></a>
驗證命令有**兩個來源**：專案設定與卡片宣告，並以獨立欄位記錄是哪一個。
**兩者皆為機器事實**——其可信度來自「執行者未選擇要跑什麼」，而非來自命令存放於何處。

<a id="fr-verify-002-ac-05"></a>
在卡片上宣告驗證命令**需要核准權限**；執行憑證的權限範圍永不含該權限。
兩個來源的命令使用**同一套驗證規則**。

<a id="fr-verify-002-ac-06"></a>
Agent 自述的項目須以**文字**標示「未經平台驗證」，不得僅以提示框呈現；
其結束碼不得以機器事實的樣式呈現。

<a id="fr-verify-002-ac-07"></a>
兩個來源的機器事實**以相同樣式呈現**，來源差異以文字另行標示；
以深淺區分會宣稱一件資料上不成立的事。

<a id="fr-verify-002-ac-08"></a>
專案可要求「至少通過一條專案層級的檢查」，**預設關閉**。

<a id="fr-verify-003"></a>
## FR-VERIFY-003 完成判準與例外出口

<a id="fr-verify-003-ac-01"></a>
卡片進入完成的前提有六項：完成摘要、每項驗收標準皆有結果、驗證報告、
無未處理的重大失敗、相依卡片皆已完成、以及依交付模式應具備的交付證據。

<a id="fr-verify-003-ac-02"></a>
拒絕須**逐項指名缺少什麼**，不得只回一句話。

<a id="fr-verify-003-ac-03"></a>
驗收標準的結果為封閉四值；既有資料中不符者於升級時一律轉為「未驗證」，
且升級須輸出被轉換的筆數。

<a id="fr-verify-003-ac-04"></a>
「未處理」指**未被明白接受**；列為殘留風險即視為已處理。

<a id="fr-verify-003-ac-05"></a>
完成判準**只有一個入口**；執行完成**不得移動卡片**。

<a id="fr-verify-003-ac-06"></a>
管理者可強制推進，**需要獨立的權限**與必填理由；
理由同時記於卡片與時間軸，**在卡片上永久可見且不可單獨清除**。

<a id="fr-verify-003-ac-07"></a>
不交付與以產物交付的卡片**不得因缺少合併請求被擋**；
以產物交付但無產物者須被擋。無變更與僅交付分支的結論皆須放行。

<a id="fr-verify-003-ac-08"></a>
流程可設定性**不得觸及完成判準**。

<a id="fr-evidence-001"></a>
## FR-EVIDENCE-001 機器事實證據

<a id="fr-evidence-001-ac-01"></a>
git 狀態、變更檔案與差異統計由節點在執行目錄內以固定引數擷取。

<a id="fr-evidence-001-ac-02"></a>
擷取須有逾時；逾時的項目留空並標記，**不得使整個擷取失敗**。

<a id="fr-evidence-001-ac-03"></a>
證據類型決定其來源等級；Agent 不得寫入機器事實類型的證據。

<a id="fr-evidence-002"></a>
## FR-EVIDENCE-002 證據彙整與矛盾

<a id="fr-evidence-002-ac-01"></a>
三種來源的證據並存於同一份清單，各自標示來源。

<a id="fr-evidence-002-ac-02"></a>
Agent 自述與機器擷取矛盾時**兩者皆呈現、皆標來源，平台不判斷孰是孰非**。

<a id="fr-evidence-002-ac-03"></a>
單筆證據有大小上限；超出時拒絕並引導改以產物交付。

<a id="fr-agenttool-002"></a>
## FR-AGENTTOOL-002 流程可設定性與指標

<a id="fr-agenttool-002-ac-01"></a>
專案可覆寫的範圍僅限**啟用或停用既有項目**與調整建議值；
**不得新增自訂項目、不得變更車道**。

<a id="fr-agenttool-002-ac-02"></a>
覆寫指向不存在的項目時拒絕並指名。

<a id="fr-agenttool-002-ac-03"></a>
停用的原因須分得出「本部署未具備該整合」與「本專案關閉了它」。

<a id="fr-agenttool-002-ac-04"></a>
跨專案指標在有覆寫的情況下**仍須可聚合**。

<a id="fr-agenttool-002-ac-05"></a>
指標**只呈現，不進入任何自動阻擋邏輯**；每一項指標須附一句說明其用途，
因為未經說明的計數會被讀成排行榜。

---

# 8.16 需求釐清與任務拆解

前一節回答「這張卡的成果怎麼離開」與「憑什麼算做完」。本節回答更前面的一個問題：
**這張卡是怎麼來的。**

一句模糊的需求，經由 Agent 在既有的看板訊息串上反覆提問，
變成一份人工核准的規格，再拆成一批帶有完整就緒條件的任務提案，
由人逐張決定要不要建立成卡片。範圍與取捨見
ADR 0034（釐清、拆解與三個人工關卡）、ADR 0028 增補 A（卡片種類）、
ADR 0029 增補 D（兩種不產生程式碼的 run）。

本節的能力受 `CLIORA_AGENT_RUNS_ENABLED` 控制；資料模型與人工表單則屬於
`CLIORA_PROJECTS_ENABLED`（V2.1 已交付，見 FR-TASK-005）。

> **本節不新增任何對外副作用、任何新的執行能力、任何新的憑證。**
> 釐清與拆解 run 對遠端儲存庫的影響是零。
> 本節唯一的新風險是語意的：**一份 Agent 寫的規格被讀成一份人核准過的規格。**

> **Agent 寫得到的欄位與人寫得到的欄位，在資料庫上是不同的欄位。**
> 這是「Agent 的產出不等於核准」在本節的形式；它不以檢查的形式成立，
> 而以「那條路不接受這種憑證」的形式成立。

<a id="fr-spec-002"></a>
## FR-SPEC-002 釐清 run

<a id="fr-spec-002-ac-01"></a>
釐清 run 的提問走**既有的卡片訊息串**；平台不得為此新增第二條溝通管道。

<a id="fr-spec-002-ac-02"></a>
在上一個問題尚未獲得人類回覆之前，**平台拒絕同一個 run 提出第二個問題**；
拒絕須指名尚未獲答的問題，並說明可行的替代做法。此限制由伺服器強制，
不得僅由命令列工具或情境說明約束。

<a id="fr-spec-002-ac-03"></a>
釐清與拆解 run **不得攜帶任何機密**；違反者在派工當下被拒，
且拒絕訊息須說明修正方式是清空該欄位，而非放寬專案允許清單。

<a id="fr-spec-002-ac-04"></a>
釐清與拆解 run 的交付方式僅限「無交付」或「卡片產物」；
其執行對遠端儲存庫的影響須為零。

<a id="fr-spec-002-ac-05"></a>
情境包須包含五條停止條件；命中任一條時，Agent 須將問題留在未決問題中，
不得自行選定答案。

<a id="fr-spec-002-ac-06"></a>
長時間未獲回覆而逾時的釐清 run，**已送出的規格草稿與訊息串須完整保留**，
不得整批丟棄。

<a id="fr-spec-003"></a>
## FR-SPEC-003 開放問題閘門

<a id="fr-spec-003-ac-01"></a>
規格存在未解決的開放問題時**不得核准**；拒絕由 API 產生並指名是哪幾個問題，
不得僅以停用按鈕表示。

<a id="fr-spec-003-ac-02"></a>
一則開放問題**不得同時**帶有答案與「已知未知」的標記；
兩者並存會掩蓋「答案是什麼」與「決定不解決」的差別。

<a id="fr-spec-003-ac-03"></a>
未解決的問題只存在於規格的開放問題欄位；其他章節不得成為第二個問題來源。

<a id="fr-spec-004"></a>
## FR-SPEC-004 拆解 run 與任務提案

<a id="fr-spec-004-ac-01"></a>
拆解的產出是**提案**，不是卡片；提交提案的路徑上不得建立任何任務卡。

<a id="fr-spec-004-ac-02"></a>
提案樹的每一張任務須自帶流程定義所要求的就緒條件，
以及來源、交付方式等執行設定；**不得由提案指定所需機密**。

<a id="fr-spec-004-ac-03"></a>
提案樹的節點編號、父子參照與前置關係須在提交當下驗證；
形成循環時拒絕並列出循環路徑。

<a id="fr-spec-004-ac-04"></a>
提案內容命中高風險領域（密鑰、認證、金流、遷移、基礎設施）而未標記高風險時，
提交被拒。此比對刻意寬鬆，寧可誤報。

<a id="fr-spec-004-ac-05"></a>
拆解 run 只能對**自己所屬卡片連結的需求**提交提案；
指向其他需求時視同不存在。

<a id="fr-spec-005"></a>
## FR-SPEC-005 提案接受

<a id="fr-spec-005-ac-01"></a>
提案可全部接受、部分接受、編輯後接受或拒絕；
部分接受後**剩餘的節點仍可再次接受**，且介面須分得出「剩餘」與「已拒絕」。

<a id="fr-spec-005-ac-02"></a>
接受時的欄位覆寫僅適用於本次勾選的節點，且**不得覆寫就緒條件**。

<a id="fr-spec-005-ac-03"></a>
接受所建立的卡片，其就緒條件若不齊備，須落在待辦而非就緒，並說明缺項。

<a id="fr-spec-005-ac-04"></a>
提案中的前置關係在接受時翻譯為卡片相依；
指向未被接受節點的前置關係**不得建立**，須回報，且該卡因此落在待辦。

<a id="fr-spec-005-ac-05"></a>
拒絕提案**須附理由**；理由須保留，並於下一次拆解時作為負面情境提供。

<a id="fr-spec-006"></a>
## FR-SPEC-006 來源可追溯

<a id="fr-spec-006-ac-01"></a>
由提案建立的卡片，其詳情須顯示來源需求與提案編號。

<a id="fr-spec-006-ac-02"></a>
需求詳情須可反查其產生的卡片與各卡目前所在車道。

<a id="fr-spec-006-ac-03"></a>
規格的每一版須顯示撰寫者身分類別（人或執行器）；
由 run 產生者須可連回該次執行。

<a id="fr-spec-007"></a>
## FR-SPEC-007 文件修訂提案

<a id="fr-spec-007-ac-01"></a>
平台**只渲染修訂內容與理由，並記錄人的決定；平台不套用任何修訂**。

<a id="fr-spec-007-ac-02"></a>
修訂內容一律以純文字呈現，不得在應用來源內解析為標記語言，
且不提供可直接套用的檔案下載。

<a id="fr-spec-007-ac-03"></a>
接受一份修訂提案不自動建立任何卡片；
介面得提供一顆帶入欄位的建立按鈕，由人決定是否排入工作。

<a id="fr-spec-007-ac-04"></a>
拒絕修訂提案須附理由；提案本身只新增不修改。

<a id="fr-spec-008"></a>
## FR-SPEC-008 介面草模關卡（條件性）

<a id="fr-spec-008-ac-01"></a>
未啟用第三方隧道整合時，介面審查關卡**自動停用**，
且停用原因須在專案設定中明白呈現（與 FR-TASK-004.AC-05 同一條規則）。

<a id="fr-spec-008-ac-02"></a>
未啟用時，**以產出草模變體為交付物的卡片在派工當下被拒**，
拒絕訊息須說明一般介面實作卡不受影響。

<a id="fr-spec-008-ac-03"></a>
未啟用時，一般介面實作卡照常執行並可完成；
Agent 以截圖作為卡片產物的能力不受影響。

<a id="fr-spec-008-ac-04"></a>
已啟用時，草模變體可預覽、保護策略由人選定、平台負責開啟；
Agent 憑證永不具備開啟隧道的權限。**本項尚未實作。**

---

# 8.17 Ticket 對話

前一節讓一句模糊的需求可以被問成規格。本節回答那個問答**憑什麼撐得住**：

> 一張 Ticket 是一條**持久的對話**；一次 Agent Run 只是處理那條對話的**一次執行**。
> run 結束、失敗、重排、換一台機器認領或 daemon 重啟，都不得讓對話消失。

範圍與取捨見 ADR 0035（對話、run 與 turn 的邊界）、ADR 0036（傳遞語意）、
ADR 0037（actor 邊界）、ADR 0041（保留與附件）。

> **本節不新增任何對外副作用、任何新的執行能力、任何新的憑證，也不動 protocol。**
> continuation 走的是既有的認領路徑，未升級的節點行為完全不變。
> 本節唯一的新風險是傳遞語意的：**同一句話被做了兩次，或一句留言被當成核准。**

本節的能力屬於 `CLIORA_PROJECTS_ENABLED`；continuation 需要
`CLIORA_AGENT_RUNS_ENABLED`（沒有 run 就沒有可續的 turn，但對話本身仍然可用）。

<a id="fr-conv-001"></a>
## FR-CONV-001 持久對話與單調序號

<a id="fr-conv-001-ac-01"></a>
每張卡的訊息具有**單調遞增、無洞、卡片內唯一**的序號；序號由平台指派，
呼叫端不得指定。

<a id="fr-conv-001-ac-02"></a>
對話查詢以序號為游標分頁；同一個範圍重複讀取回傳相同結果，
不因兩則訊息的時間戳相同而重複或遺漏。

<a id="fr-conv-001-ac-03"></a>
游標超前卡片目前序號時**明確拒絕**並回報目前序號，不得回傳空白頁。

<a id="fr-conv-001-ac-04"></a>
清除一張卡的全部 run log 之後，該卡的對話、未決問題與規格提案**仍完整可用**。
訊息不從 log 解析產生，log 不併入訊息串。

<a id="fr-conv-002"></a>
## FR-CONV-002 訊息型別與續跑語意

<a id="fr-conv-002-ac-01"></a>
訊息具有型別，且型別決定兩件事：**會不會觸發續跑**、**構不構成核准**。
一般留言兩者皆否。

<a id="fr-conv-002-ac-02"></a>
送出一般留言**不得**改變任何 run 的狀態，也不得建立新的 Agent 回合。

<a id="fr-conv-002-ac-03"></a>
介面上「留言」與「回覆並繼續」是兩個明確不同的動作；
沒有未決問題時不呈現後者（而非呈現為停用狀態）。

<a id="fr-conv-002-ac-04"></a>
既有訊息的型別值在升級後仍可讀，且不因升級而被改寫。

<a id="fr-conv-003"></a>
## FR-CONV-003 Question 生命週期

<a id="fr-conv-003-ac-01"></a>
問題是一筆可查詢的紀錄，具有未決／已答／已取消／已逾時四種狀態，
並保存提問訊息與回答訊息的關聯。

<a id="fr-conv-003-ac-02"></a>
同一個 run 在上一個問題獲答之前**不得提出第二個問題**（延續 FR-SPEC-002.AC-02）；
此限制由伺服器強制。

<a id="fr-conv-003-ac-03"></a>
逾時未獲回覆的問題標記為已逾時並使卡片退回阻塞，
但**問題與訊息不刪除**；人類事後仍可讀到它。

<a id="fr-conv-003-ac-04"></a>
升級時，既有訊息串中的歷史問題依**升級前的判定規則**建立對應紀錄；
同一張卡對「這題答了沒」的答案不因升級而改變。

<a id="fr-conv-004"></a>
## FR-CONV-004 回答與續跑的原子性

<a id="fr-conv-004-ac-01"></a>
回答一個問題、關閉該問題、建立續跑回合三件事在**同一個交易**內完成；
不存在「答案已保存但續跑未建立」的狀態。

<a id="fr-conv-004-ac-02"></a>
重複回答同一個問題被拒絕，且拒絕訊息須足以讓使用者得知
**誰在什麼時候回答的**並跳至該回覆。

<a id="fr-conv-004-ac-03"></a>
兩個使用者同時回答同一個問題時，恰有一個成功，另一個取得可恢復的衝突；
**至多建立一個續跑回合**。

<a id="fr-conv-004-ac-04"></a>
卡片在等待期間被改成不可派工的狀態時，**回答仍然寫入**，
續跑被拒絕並在卡片上說明原因。使用者輸入的文字不因此遺失。

<a id="fr-conv-005"></a>
## FR-CONV-005 冪等傳遞

<a id="fr-conv-005-ac-01"></a>
訊息寫入接受冪等鍵；相同鍵與相同內容重送回傳**原訊息**，
相同鍵與不同內容則拒絕。

<a id="fr-conv-005-ac-02"></a>
傳遞語意為至少一次；消費者以序號去重，重複讀取同一範圍是安全的。

<a id="fr-conv-005-ac-03"></a>
消費者的已送達／已確認位置是可查詢的紀錄；
**已確認位置不控制任何流程**，它只用於呈現「Agent 已讀取」。

<a id="fr-conv-005-ac-04"></a>
「Agent 已讀取」的呈現須明白說明它**不代表模型同意或已照做**。

<a id="fr-conv-006"></a>
## FR-CONV-006 續跑回合

<a id="fr-conv-006-ac-01"></a>
續跑是同一張卡的一次新執行，記錄其上一輪、對話輪次與這一輪讀取的對話範圍。

<a id="fr-conv-006-ac-02"></a>
續跑走**既有的認領路徑**，不需要新的協定訊息；
未升級的節點行為不變。

<a id="fr-conv-006-ac-03"></a>
Agent 的行程結束或 daemon 重啟之後，對話可從資料庫恢復；
恢復後的回答**只被處理一次**。

<a id="fr-conv-006-ac-04"></a>
續跑重跑卡片層的派工拒絕條件（卡片種類與機密）；
一張在等待期間被加上機密的釐清卡，其續跑被拒。

<a id="fr-conv-006-ac-05"></a>
對交付分支的卡片，續跑**沿用第一輪的分支名**，
不得讓兩輪成果落在兩條分支上。

<a id="fr-conv-006-ac-06"></a>
續跑的對話輪次與重試次數是**兩個不同的計數**。

<a id="fr-conv-007"></a>
## FR-CONV-007 對話的 actor 邊界

<a id="fr-conv-007-ac-01"></a>
run 憑證只能讀寫其所屬卡片的對話；跨卡片存取被拒。

<a id="fr-conv-007-ac-02"></a>
run 憑證以 runner 身分發言，**不得指定發言者**；
所指定的人類身分欄位一律忽略。

<a id="fr-conv-007-ac-03"></a>
run 憑證**不得寫入決策型訊息**；違反者被拒並記錄稽核。

<a id="fr-conv-007-ac-04"></a>
Viewer 可讀對話，不可發言。

<a id="fr-conv-007-ac-05"></a>
人類的留言與回答**不構成任何核准**；核准仍走既有的人工端點。

<a id="fr-conv-008"></a>
## FR-CONV-008 規格提案與人工接受

<a id="fr-conv-008-ac-01"></a>
Agent 只能提出規格**提案**；提案不改變就緒狀態、不動任何關卡。

<a id="fr-conv-008-ac-02"></a>
接受或要求修改是人類動作，需要核准權限，
且在對話上留下**帶人類身分與時間**的紀錄。

<a id="fr-conv-008-ac-03"></a>
沒有核准權限時**不呈現**接受與要求修改的操作。

<a id="fr-conv-008-ac-04"></a>
同一張卡有多份提案時，只有最新一份可被接受；
較早的提案明白標示已被取代。

<a id="fr-conv-009"></a>
## FR-CONV-009 命令列對話橋接

<a id="fr-conv-009-ac-01"></a>
命令列可依序號讀取對話、可回覆指定訊息、可提出規格提案。

<a id="fr-conv-009-ac-02"></a>
命令列提供短暫等待新訊息的能力，並有**明確上限**；
超過上限時拒絕，並說明正確做法是結束行程、由平台以新的一輪喚回。

<a id="fr-conv-009-ac-03"></a>
以時間戳分頁的舊參數保留一個版本並標示淘汰；
與序號參數同時給定時拒絕。

<a id="fr-conv-009-ac-04"></a>
平台連不上時的行為不變：直接失敗、不佇列、訊息說明工作可繼續、
非零結束碼但不中斷 Agent（延續 FR-VERIFY-004）。

<a id="fr-conv-010"></a>
## FR-CONV-010 對話的保留與去識別

<a id="fr-conv-010-ac-01"></a>
訊息**不設到期**，不被任何清理排程刪除；
刪除專案時隨卡片一併清除。

<a id="fr-conv-010-ac-02"></a>
訊息長度有上限，超過時以可辨識的錯誤碼拒絕，並回報上限與實際長度。

<a id="fr-conv-010-ac-03"></a>
機密值不得出現在訊息內容中；由 run 憑證寫入的訊息在**寫入前**去識別。

<a id="fr-conv-010-ac-04"></a>
稽核紀錄只記錄事件與身分，**不複製訊息內容**。

<a id="fr-conv-010-ac-05"></a>
訊息建立後不可就地改寫；Agent 的訊息永不可編輯，更正以追加訊息表示。

---

# 8.18 專案記憶

前一節讓一張 Ticket 的對話撐得住一次執行的結束。本節回答**跨 Ticket** 的那一半：

> 每個 Project 有一層**可追溯的記憶**——自動從已經存在的事實收集來源，
> 保留出處、版本、時效與可信層級，以受控檢索提供給 Agent 並附引用，
> 而且**人看得見 Agent 會讀到什麼**。

範圍與取捨見 ADR 0038（來源、權威層級、專案隔離與保留）與
ADR 0039（Context Builder 的分層與預算）。

> **本節不新增任何對外連線、任何新的憑證，也不動 protocol。**
> 內容全部來自平台自己的資料庫，以及由 Agent 在自己的 run 裡推上來的 repo 檔案。
> 本節的新風險有兩個：**跨專案洩漏**，以及**一段引用資料被當成指令**。

本節能力屬於 `CLIORA_PROJECTS_ENABLED`，並額外由**每個專案自己的開關**控制；
關閉的專案行為與未實作本節時完全相同。

<a id="fr-know-001"></a>
## FR-KNOW-001 版本化的知識來源

<a id="fr-know-001-ac-01"></a>
每一筆知識來源都記錄**出處**：來源種類、原始識別、版本、可信層級、發生時間與取得時間；
六者缺一不可。

<a id="fr-know-001-ac-02"></a>
同一份來源的同一個版本**只會存在一筆**；重複收集不產生第二筆，也不改寫既有內容。

<a id="fr-know-001-ac-03"></a>
較舊的版本抵達時**不覆蓋**較新的版本。

<a id="fr-know-001-ac-04"></a>
新版本進入時，舊版本被標記為已被取代，且兩者之間的取代關係可被查詢。

<a id="fr-know-002"></a>
## FR-KNOW-002 收集的可靠性

<a id="fr-know-002-ac-01"></a>
待收集的事件保存在資料庫，**不在記憶體**；平台重啟不遺失待處理的事件。

<a id="fr-know-002-ac-02"></a>
收集失敗時自動重試並逐次延長間隔；達上限後進入失敗佇列，**不無限重試**。

<a id="fr-know-002-ac-03"></a>
失敗佇列的**最舊項目年齡**可被監控查詢，且顯示在專案的來源健康狀態上。

<a id="fr-know-002-ac-04"></a>
除事件路徑外另有**排程校對**：即使某個事件從未送達，該筆事實最終仍會進入索引。

<a id="fr-know-003"></a>
## FR-KNOW-003 可信層級

<a id="fr-know-003-ac-01"></a>
每一筆來源有明確的可信層級，且**由伺服器端依來源判定**，呼叫端指定的值一律忽略。

<a id="fr-know-003-ac-02"></a>
可信層級的變更（標為正式決策、撤回、被取代）留下稽核紀錄，記錄動作者與對象，
**不記錄來源內容**。

<a id="fr-know-003-ac-03"></a>
已被取代與已撤回的來源**不出現在預設檢索結果**；只有明確要求歷史時才回傳，
且回傳時明確標示。

<a id="fr-know-003-ac-04"></a>
Agent 產出的內容其可信層級永遠低於人的決策，且**永不因為時間經過而升級**。

<a id="fr-know-004"></a>
## FR-KNOW-004 檢索

<a id="fr-know-004-ac-01"></a>
精確識別（卡片編號、函式名稱、commit 識別碼、錯誤碼）查得到，
**且輸入有錯字時仍查得到**。

<a id="fr-know-004-ac-02"></a>
以中文語句查詢時查得到中文內容；不因語言而失去檢索能力。

<a id="fr-know-004-ac-03"></a>
排序不只看字面相關度：可信層級較高者、時間較新者、與查詢卡片有明確關聯者排在前面。

<a id="fr-know-004-ac-04"></a>
檢索能力降級時（例如查詢過短而只能做模糊比對）**明確告知**，不靜默降級。

<a id="fr-know-005"></a>
## FR-KNOW-005 情境組裝與預算

<a id="fr-know-005-ac-01"></a>
提供給 Agent 的情境分層組裝，且**有明確的總量上限**。

<a id="fr-know-005-ac-02"></a>
超出上限時的裁切順序固定：先裁檢索到的參考資料，再壓縮較舊的對話；
**專案規則與未決問題永不被裁切**。

<a id="fr-know-005-ac-03"></a>
連專案規則與未決問題都放不下時**明確拒絕**，不靜默截斷。

<a id="fr-know-005-ac-04"></a>
每一次組裝留下清單，說明用了哪些來源、各自的版本、可信層級、佔用量，
以及**哪些被省略與為什麼**。

<a id="fr-know-006"></a>
## FR-KNOW-006 指令與引用的分層

<a id="fr-know-006-ac-01"></a>
情境中「規則」與「引用資料」在結構上分開，且引用資料明確標示為引用。

<a id="fr-know-006-ac-02"></a>
只有人所核准的專案規則可以進入規則區塊；**Agent 的產出永遠不可以**。

<a id="fr-know-006-ac-03"></a>
來源文字中出現的指示性語句（例如「忽略上述規則」）**不因此成為指令**，
仍位於引用區塊並帶出處。

<a id="fr-know-006-ac-04"></a>
上述性質不因為預算裁切而改變：裁切只會移除引用資料，不會移動它的位置。

<a id="fr-know-007"></a>
## FR-KNOW-007 引用

<a id="fr-know-007-ac-01"></a>
情境與檢索結果的每一段內容都帶引用，引用可回到原始來源。

<a id="fr-know-007-ac-02"></a>
每一種來源種類都有可回溯的去處：卡片訊息、文件版本、產物或程式庫路徑。

<a id="fr-know-007-ac-03"></a>
引用的來源已不存在、已被排除或不屬於本專案時，**以可辨識的錯誤碼分別說明**，
且不揭露該來源是否存在於其他專案。

<a id="fr-know-007-ac-04"></a>
Agent 在留言中使用的引用標記由介面盡力還原為連結；**還原失敗時顯示為純文字**，
不因此使留言無法閱讀。

<a id="fr-know-008"></a>
## FR-KNOW-008 專案隔離

<a id="fr-know-008-ac-01"></a>
授權在**檢索邊界**完成，不是在介面上過濾結果。

<a id="fr-know-008-ac-02"></a>
無權查詢時，回傳的結果數為 **0**，且不以錯誤碼揭露該專案或該來源是否存在。

<a id="fr-know-008-ac-03"></a>
執行憑證只能查詢其卡片所屬專案；跨專案查詢一律拒絕。

<a id="fr-know-008-ac-04"></a>
跨專案的相似內容搜尋**預設不存在**，且不可由任何參數開啟。

<a id="fr-know-009"></a>
## FR-KNOW-009 刪除與撤銷

<a id="fr-know-009-ac-01"></a>
來源在原處消失（檔案被刪、產物被刪）之後，**不再出現在預設檢索**。

<a id="fr-know-009-ac-02"></a>
刪除專案時，其全部知識來源、索引與情境紀錄一併消失。

<a id="fr-know-009-ac-03"></a>
撤銷不是刪除：被排除或被取代的來源仍可查詢其存在與原因，只是不進預設檢索。

<a id="fr-know-009-ac-04"></a>
機密值、憑證與敏感檔案**不進入索引**；由來源文字在寫入前去識別，
且敏感檔案在收集前即被排除。

<a id="fr-know-010"></a>
## FR-KNOW-010 逐專案開關與來源健康狀態

<a id="fr-know-010-ac-01"></a>
專案記憶**預設關閉**，開啟需要專案管理權限並留下稽核紀錄。

<a id="fr-know-010-ac-02"></a>
關閉時不收集、不建索引，查詢回應**不揭露該專案是否曾經啟用**。

<a id="fr-know-010-ac-03"></a>
關閉後既有來源標記為停用而**不立即刪除**；刪除是另一個需要二次確認的動作。

<a id="fr-know-010-ac-04"></a>
介面顯示每一類來源的筆數、最後收集時間、待處理量、失敗數與失敗佇列年齡；
**從未收集過的來源顯示為「從未同步」並說明原因**。

<a id="fr-know-011"></a>
## FR-KNOW-011 程式庫內容的收集

<a id="fr-know-011-ac-01"></a>
程式庫內容由 Agent 在自己的執行環境中推送；**平台不主動連向任何程式庫代管服務**。

<a id="fr-know-011-ac-02"></a>
版本以 commit 識別碼表示，且同一個 commit 重複推送不產生第二份內容。

<a id="fr-know-011-ac-03"></a>
排除規則同時來自程式庫自身的設定與專案設定；產生的內容、相依套件目錄與二進位檔案
不被收集。

<a id="fr-know-011-ac-04"></a>
單次推送有明確上限；超過時以可辨識的錯誤碼拒絕並**指名是哪一項上限**，
單一過大檔案則跳過而不使整次推送失敗。

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

