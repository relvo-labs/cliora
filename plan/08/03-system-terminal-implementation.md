# 03 — 系統終端機實作（WT-06、WT-07、WT-08）

前置：`WT-04` 已核准（選項 A）、`WT-05` 已合併。

## WT-06：Daemon `shell` runtime 與 node 端停用開關

### 1.1 Runtime 實作

`daemon/internal/runtime/runtime.go` 的 `cliRuntime` 是「帶 `--version` 旗標的 CLI」通用轉接器，`bash --version` 完全符合，因此**不需要新的 Runtime 型別**——只要用同一個轉接器註冊 `shell` 即可。需要的變更：

- 註冊表加入 `shell`，binary 來自 `config.yaml` 的 `runtime.shell.binary`。
- `Detect` 沿用既有的 `LookPath` + 版本探測；不可用時回 `ReasonNotFound`／`ReasonNotExecutable`（`:19-22`），與其他 runtime 同一組理由碼。
- **`BuildCommand` 只回傳 binary 本身，不附加任何參數。** `RuntimeConfig` 只有 `{Enabled, Binary}` 兩個欄位（`daemon/internal/config/config.go:102`），本來就沒有地方放 argv——這個限制要維持，不要為了 `-l`／`--login` 新增欄位。要 login shell 就在 config 指定 binary 路徑，argv 永遠是單一 token。

### 1.2 Config 與安裝預設（D6：預設啟用）

決策 D6 在 2026-07-31 改為**預設啟用**。「預設」有兩個落點，兩個都要做，否則語意會不一致：

**(1) 新安裝**：`install/plan.go` 的 `DetectRuntimes`（`:55-61`）加入 `"shell": {Enabled: true, Binary: "bash"}`；`BuildConfig`（`:64`）產生的 `config.yaml` 內含明確的 shell 區塊，並附註解說明它是什麼、以及如何停用。設定檔要能自我解釋——node 的擁有者是最後一道防線。

**(2) 既有 node（設定缺項）**：`Config.Load`（`:113`）新增 `applyRuntimeDefaults()`，在 `Validate()` 之前對「`runtime` map 中沒有 `shell` 鍵」的情形注入 `{Enabled: true, Binary: "bash"}`。沿用既有的 `applyFilesystemDefaults()`（`:125`）同一個模式與位置。

> **這是能力變更，不是修補。** 既有 node 的 `config.yaml` 沒有 shell 區塊，升級 daemon 後就會取得遠端 shell 能力。必須：
> - 在 release note 與 `docs/runbooks/` 明確列出（`00-execution-plan.md` §8 上線階段已列為阻擋條件）；
> - daemon 啟動時對 shell 的啟用狀態輸出一行結構化 log（`runtime_shell_enabled=true source=default|config`），讓操作者能從 log 確認自己這台是哪一種，而不必去推測；
> - 明確的 `enabled: false` 永遠優先於預設，且要有測試證明「停用不會被 defaults 覆寫回來」——這是整個預設機制最容易寫錯的一點。

`Config.Validate()` 必須拒絕「`runtime.shell.enabled: true` 但 `binary` 為空」。config 以 `dec.KnownFields(true)`（`:118`）嚴格解析，拼錯欄位名會直接失敗——既有行為，不要破壞。

若 node 上沒有 `bash`，`Detect` 會回 `ReasonNotFound` 並回報 `available: false`，Central 的 `_require_runtime` 隨即以 409 `RUNTIME_NOT_FOUND` 擋下。**預設啟用不等於保證可用**，這條退路要有測試。

### 1.3 為什麼 session 管線不需要改

`daemon/internal/session/manager.go:78` 的 `StartSession(ctx, id, runtimeID, workspace, binary, rows, columns)` 對 runtime 只做兩件事：傳給 `tmux.StartSpec.RuntimeID`（供 `allowedRuntimeID` 檢查）與用 `binary` 當啟動命令。`Attach`（`:104`）、`Capture`／snapshot（`:110`）、`Input`／`Resize`（`:190`/`:199`）、`Stop` 的兩段式終止（`:227`，`tmux/client.go:148`）全都只認 session id。

**因此 reconnect、2 MiB reattach snapshot、graceful→forced 終止、`ActiveCount` 全部自動適用於 shell session，一行不改。** 這是決策 D5 的具體收益。

`ActiveCount()`（`:178`）會把 shell 一起計入 heartbeat 的 session 數——這是要的（D13：資源計數必須誠實）。

### 1.4 測試

- Go unit：`shell` 通過四處 allowlist（`config.AllowedRuntimeIDs`、`tmux.allowedRuntimeID`、`protocol.validRuntimeID`、`node.runtime_status` 項目檢查）；未在 allowlist 的 id 仍被拒。
- Go unit：`runtime.shell.enabled: true` + 空 binary 的 config 被 `Validate()` 拒絕。
- Go unit：`BuildCommand` 的 argv 長度為 1。
- Integration（`//go:build integration`，無 tmux 時 skip，沿用 `daemon/internal/session/integration_test.go` 的模式）：以 `shell` runtime 啟動 → attach → 送入一個列印固定字串的指令 → 從輸出讀到它 → `Stop` 回 `StopGraceful`。

---

## WT-07：Central shell session

### 2.1 端點

```
POST /api/sessions/{id}/shell     → 201 SessionDetail（新的 shell session）
```

`{id}` 是 **parent CLI session**。刻意不走 `POST /api/sessions`：把 parent 綁定放在 URL 上，就沒有任何路徑能建立一個沒有 parent 的 shell session，也就順帶滿足了 D13（清單與 New Session dialog 都不可能生出 shell）。

終止沿用既有的 `POST /api/sessions/{shell_id}/terminate`，不新增端點。

### 2.2 檢查順序（不可調換）

| 順序 | 檢查 | 失敗 |
|---|---|---|
| 1 | `require_action(TERMINAL_SHELL)` | 403 |
| 2 | 載入 parent session；`authz.is_owner(user, parent)` | 403 |
| 3 | parent 狀態非終端（`sessions.py:39` `TERMINAL_STATES`） | 409 |
| 4 | node 已連線且啟用（`ensure_node_enabled`） | 409 `NODE_OFFLINE` |
| 5 | `_require_runtime(node, "shell")` — 走 `node.runtimes` 的 `available` 檢查 | 409 `RUNTIME_NOT_FOUND` |
| 6 | 該 parent 沒有活著的 shell | 409 `SHELL_ALREADY_OPEN` |
| 7 | node/user session 上限 | 409 `SESSION_LIMIT_REACHED` |
| 8 | 建立 row（`parent_session_id`、`runtime="shell"`、workspace 沿用 parent、size 由請求帶入）→ relay `session.start` | 依既有錯誤處理 |

第 2 項是「只有 CLI session 的擁有者能在其中開 shell」。Admin 對別人的 session **不能**開 shell（`node.manage` 不授予此能力），但可以終止——這個不對稱是刻意的：能收拾殘局，不能旁觀他人的 shell。

### 2.3 `authz.py` 的四處特例

shell session 的授權**不是** CLI session 授權的延伸，而是更緊的一組。在 `backend/app/services/authz.py` 現有函式的最前面加上 runtime 判斷：

| 函式 | 現況（CLI） | shell |
|---|---|---|
| `may_view_session`（`:86`） | `session.view` + owner／可 takeover 者 | **僅 owner**。否則持有 `session.view` 的 Viewer 就能旁觀別人的 shell，比旁觀 CLI 嚴重得多 |
| `may_write_session`（`:92`） | `terminal.operate` + (owner 或 `terminal.takeover`) | **僅 owner**，且需 `terminal.shell` |
| `may_takeover_session`（`:105`） | 同 write 資格 | **一律 False**。shell 不可被接管 |
| `may_browse_files`（`:124`） | `file.browse` + 可 view | **一律 False**。檔案樹永遠綁 parent CLI session（D10），不需要也不應該能用 shell session id 走 filesystem relay |
| `session_capabilities`（供 `schemas.py:141-146`） | 回傳現有四項 | 新增 `can_open_shell`：`has_action(TERMINAL_SHELL) and is_owner(...) and runtime != "shell"` |

`may_view_session` 是 browser WS handshake 的守門（`backend/app/api/ws/terminal.py:87`），`may_write_session` 在**每一個 keystroke** 上重新檢查（`:177`），所以這兩處改完即同時覆蓋 HTTP 與 WS——不需要在 WS 層另寫一份。

`SessionCapabilities`（`backend/app/api/http/schemas.py:86-87`）新增 `can_open_shell: bool`；前端據此決定 TERMINAL tab 是否存在（見 `WT-08`）。

### 2.4 生命週期（三層，缺一層就會漏 shell 在 node 上）

**(1) 使用者關閉 tab / 離開 workspace** → 前端呼叫 terminate（`WT-08`）。正常路徑。

**(2) parent 結束** → `SessionService.terminate()` 在停掉 parent 之後，找出其活著的 shell 子 session 並一併停止；`session.status_changed` 讓 parent 進入終端狀態的路徑也要做同一件事（CLI 自己 exit、node 斷線後 reconcile 都會走這裡，不只有使用者按 Terminate）。

**(3) 瀏覽器崩潰／斷網** → 前端什麼都送不出來，所以必須有伺服器端的兜底。**新增設定 `shell_idle_terminate_seconds`（預設 900）**：當一個 shell session 的 relay 訂閱者數量降到 0（`terminal_relay.unsubscribe` 之後）就起算，逾時仍無人 attach 即終止。

> 這與 `FR-SESSION-006`（CLI session 在瀏覽器斷線後**不得**自動終止）刻意相反，理由要寫進 ADR 0021：CLI session 的價值在於長時間執行、離線也要繼續；一個沒人看著的 shell 只有風險沒有價值。這個差異必須在 PRD/ADR 明說，否則下一個人會以為它是 bug 並「修好」它。

### 2.5 清單過濾與計數（D13）

- `backend/app/repositories/sessions.py:31` 的 `list()` 預設排除 `runtime == "shell"`。
- `list_active_for_node`（`:48`）與兩處 `count`（`:67`、`:85`）**不排除**——上限與 node 詳情頁必須誠實，否則會出現「清單顯示 3 個、node 卻回報滿載」。
- Dashboard 的 `per_runtime`（`frontend/src/api/dto.ts:306-308` 的契約：只列真的有 session 的 runtime）自然會出現 `shell` 鍵，不需特別處理。

### 2.6 Audit（D9）

沿用既有的 `SESSION_CREATE` / `SESSION_ATTACH` / `SESSION_TERMINATE` 事件，metadata 加入 `runtime`。**不新增任何記錄終端機內容的路徑。**

必須新增一條測試，斷言 shell session 的完整生命週期跑完後，`audit_logs` 中不含任何 terminal bytes、指令字串或 binary 路徑（沿用 P4 redaction 測試的斷言方式）。這條測試是 `TECH-SEC-08` 對新功能的延伸，不是重複。

### 2.7 測試

- `backend/tests/db/test_sessions_api.py`：§2.2 的八個檢查各一例，含 **Viewer 拿 403（action 層）**、**Developer 對他人 session 拿 403（scope 層）**、**Developer 對自己 session 成功**、重複開啟拿 `SHELL_ALREADY_OPEN`、node 明確停用 shell 時拿 `RUNTIME_NOT_FOUND`。
- authz 單元測試：§2.3 的五個函式對 `runtime="shell"` 的行為，含「Admin 不能 view 他人 shell、但能 terminate」。
- WS 測試：持有 ticket 但非 owner 的連線在 handshake 被 1008 關閉。
- 生命週期：parent terminate → child 也進終端狀態；idle 逾時 → child 被終止。
- redaction 測試（§2.6）。

---

## WT-08：前端 TERMINAL tab

### 3.1 API 與狀態

```ts
// api/client.ts
openShell(sessionId: string): Promise<SessionDetail>   // POST /api/sessions/{id}/shell
```

ticket 沿用既有 `attachSession(shellId)`；shell 的 WS 路徑與 CLI 完全相同（`/ws/sessions/{id}/terminal`），因此 `useTerminalSession` **原封不動**再實例化一份即可：

```ts
const shellTerminal = useTerminalSession((id) =>
  api().attachSession(id).then((r) => r.ticket));
const shellSession = ref<SessionDetail | null>(null);
const shellState = ref<"idle" | "starting" | "ready" | "error">("idle");
```

### 3.2 Tab 可見性

```ts
const canOpenShell = computed(() => capabilities.value?.can_open_shell === true);
```

沿用 `SessionWorkspaceView.vue:34-40` 既有的做法：**能力來自 server 計算的 payload，不是前端 role 判斷**（ADR 0016）。`can_open_shell` 已同時涵蓋 action、ownership 與該 node 是否停用了 shell（`WT-07` §2.3），所以前端不需要自己組合條件——這在 Developer 也持有 `terminal.shell`（D7）之後更重要：前端若自己用 `hasPermission()` 判斷，會對「別人的 session」也顯示出 tab，然後在按下去時才拿 403。

tab 陣列（接續 `01-workspace-layout-and-tabs.md` §3.2）：

```ts
...(canOpenShell.value ? [{ id: "terminal", label: "TERMINAL" }] : []),
```

### 3.3 生命週期

| 事件 | 行為 |
|---|---|
| 第一次切到 TERMINAL | `shellState = "starting"` → `openShell(props.id)` → 成功後 `shellTerminal.connect(shell.id)`；失敗顯示錯誤碼對應訊息（`SHELL_ALREADY_OPEN`／`RUNTIME_NOT_FOUND`／`SESSION_LIMIT_REACHED` 各有具體文案）並允許重試 |
| 再次切回 TERMINAL | 什麼都不做（panel 一直掛著，socket 一直開著，與 CLI 同一策略 D4）；只 `fit()` + `focus()` |
| 關閉 TERMINAL tab | `terminate(shell.id)` → 清掉 `shellSession`、`shellState = "idle"`、切回 CLI |
| 離開 workspace（unmount / route 變更） | 同上，best-effort terminate；伺服器端的 parent 綁定與 idle 逾時是兜底（`WT-07` §2.4） |

TERMINAL panel **不顯示** Writer/Viewer 標籤與「Request control」按鈕——shell 是 owner-only，`role` 恆為 writer，顯示一個永遠不變的標籤只是雜訊。

### 3.4 視覺與無障礙

- tab 標籤固定為 `TERMINAL`（全大寫，與使用者的原始要求一致），與 `CLI` 同一組樣式。
- panel 內用與 CLI 相同的 `.terminal-host` 與 `--terminal-*` token（style.md §18：Terminal 就是工作區，不包 Card）。
- `starting`／`error` 狀態用既有 `AsyncState`／banner 樣式，不自創第三套。
- 一個明確的視覺區隔：TERMINAL tab 選中時，在 panel 上方顯示一行不可關閉的提示，說明這是 node 上的系統 shell、不受 workspace 路徑限制。這不是裝飾——它是 ADR 0021 補償控制的一部分（使用者必須知道自己現在在哪個安全邊界裡）。

### 3.5 測試

- Vitest：`can_open_shell` 為 false 時沒有 TERMINAL tab；為 true 時有。
- Vitest：第一次啟動只呼叫 `openShell` 一次（快速連點兩次 tab 不會建立兩個 session）。
- Vitest：關閉 tab 會呼叫 `terminate(shellId)`。
- Vitest：三種錯誤碼各自顯示對應文案並可重試。
- Playwright（`E2E_FULL_STACK` + 一個 shell 可用的 online node，沒有則 skip）：Developer 在**自己的** session 開 TERMINAL → 執行 `echo` → 看到輸出 → 關閉 tab → 該 session 在 API 上為終端狀態；同一個 Developer 開啟**他人的** session 時看不到 TERMINAL tab，且直接打 `POST /api/sessions/{id}/shell` 拿到 403；Viewer 兩種情況都拿 403。
