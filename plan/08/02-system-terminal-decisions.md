# 02 — 系統終端機：決策與契約（WT-04、WT-05）

## WT-04：決策閘門（ADR 0021、PRD 修訂與 `SCOPE-011` 處置）

> **狀態（2026-07-31）：已決定為選項 A（收窄 `SCOPE-011`），D6／D7 亦已決定（見 `05-implementation-status.md` D-1/D-3/D-4）。**
> 決定已下，**交件尚未完成**：ADR 0021、PRD 修訂與 traceability 的 supersedes 鏈都還沒寫。
> **在這三項合併之前，`WT-05` 起的程式不得合併**——決定本身不能取代把決定寫下來，這正是本閘門存在的理由。

### 1.1 為什麼這不是一張功能票

`traceability/requirements.json` 記著：

```json
{ "id": "SCOPE-011", "kind": "scope", "title": "不允許使用者從前端執行任意 Shell Command。",
  "source": { "path": "research/prd.md", "anchor": "scope-011" },
  "lifecycle": "active", "criticality": "must", "owner": "product" }
```

對應 PRD 第 107-109 行。它的守門連結有兩條，其中一條是自動測試：

```
LNK-SCOPE-011-AC-01-GUARDS-EXEC → pytest:
  backend/tests/test_scope_guards.py::test_scope_011_the_front_end_cannot_name_a_command
  assertion: "Session start is closed over five fields; none of command, args,
              argv, shell, env or entrypoint exists."
```

**這個測試在加入 `shell` runtime 之後仍然全綠**——因為前端送的依舊只是一個 runtime id，wire 上依舊沒有命令字串。也就是說：CI 不會擋、coverage 不會掉、release gate 不會亮紅燈，但一個 criticality `must` 的產品非目標實質上被推翻了。

這正是必須由人明確決定的情形。`WT-04` 的產出不是程式，是一個書面決定。

### 1.2 三個可選結果（**已選 A**，B／C 保留於此作為決策紀錄）

| | 選項 | 對 `SCOPE-011` 的處置 | 後果 |
|---|---|---|---|
| **A** | **收窄（建議）** | 保留 ID、改寫內容為「前端不得指定任意 Shell Command **字串**；互動式 shell session 僅限持有 `terminal.shell` 的使用者於自己擁有的 Session 上開啟，且 Node 可停用」。原 `SCOPE-011.AC-01` 標 `lifecycle: deprecated`，由新的 `FR-SHELL-001.AC-03` 以 `supersedes` 連結取代並記錄 rationale | 守門測試的意圖（wire 上沒有命令字串）完整保留，且仍然有效；新能力有自己的 requirement 與驗收 |
| **B** | 整條撤回 | `SCOPE-011` 整體 `lifecycle: deprecated` | 不建議。撤回會連帶失去「前端不得指定命令字串」這個仍然成立且仍在防守的性質，等於為了開一扇門拆掉整面牆 |
| **C** | 維持不變 | 不動 | 曾是有效結果（只交付波次 0）。**未採用**——2026-07-31 決定做範圍變更 |

> ADR 0019 的規則（也是這個 repo 踩過的坑）：`lifecycle: deprecated` 的 criterion **必須**有來自替代者的 `supersedes` 連結與書面 rationale，否則 `scripts/trace validate` 直接失敗。撤回需求是清掉 coverage 缺口最便宜的手段，所以它被刻意做得需要留痕。

### 1.3 ADR 0021 必須記錄什麼

檔名 `docs/adr/0021-system-terminal-and-shell-runtime.md`（現有最新為 `0020`）。除了決策本身，以下四件事缺一不可：

**(1) 它繞過了什麼。** 逐條列出，不含糊：

| 既有控制 | 對 shell session 是否仍有效 |
|---|---|
| allowed workspace roots 前綴授權（`backend/app/services/sessions.py:58` `authorize_workspace`） | **僅在啟動時有效**。shell 的 cwd 會是合法的 workspace，但 `cd ..` 之後不再受限 |
| daemon 端每次操作重新 canonicalize（`TECH-SEC-05`） | 對 P3 的 filesystem relay 仍有效；對 shell 內的行為**完全無效** |
| 唯讀檔案政策、敏感檔案拒讀（`TECH-SEC-09`） | 對預覽仍有效；shell 內 `cat` 任何檔案**不受限** |
| `SEC-002` 前端不得指定命令 | **仍有效**（見 §1.1） |
| `TECH-SEC-08` terminal bytes 不入 log | **仍有效**，且本期不得為了「稽核 shell 指令」而破壞它（決策 D9） |
| daemon 非 root 常駐 | **仍有效**。shell 以 daemon 的身分執行，因此其權限上界就是 daemon 的權限上界——這是本設計最重要的一個既有保護 |

**(2) 補償控制。** D6／D7 在 2026-07-31 都採了較寬的預設（node 端預設啟用、Admin + Developer 皆持有 `terminal.shell`），因此補償控制**全部集中在以下四項**，ADR 必須逐項寫明它們各自擋住什麼：

| 控制 | 擋住什麼 |
|---|---|
| **Ownership**（只能在自己擁有的 session 開 shell；他人一律不得 attach，含 Admin） | 橫向移動與旁觀。這是取代「僅 Admin」之後的主要邊界 |
| **daemon 非 root 執行** | 權限上界。shell 不提升任何權限，它把 daemon 既有權限暴露成互動介面——**這一項失守，整個設計的風險等級改變** |
| **parent 綁定 + tab 關閉即終止 + idle 逾時**（D8、`03-…md` §2.4） | 無人看管的殘留 shell |
| **session 級 audit（含 `runtime` 標記）**（D9） | 事後追溯「誰在哪個 node 何時開過 shell」 |

`node` 端仍可明確 `enabled: false` 停用，但它現在是**否決權**而非預設姿態，不能再被當成第一道防線。

**(3) 為什麼守門測試仍會綠。** 明確寫下來，讓下一個讀 `test_scope_guards.py` 的人不會誤以為這個能力通過了自動審查。

**(4) 被否決的替代方案與理由**：
- *另開一條獨立的 shell WS 通道*：要重寫 ticket、relay、single-writer、reconnect、snapshot、terminate、audit 各一份。`daemon/internal/session/manager.go:78` 的 `StartSession(id, runtimeID, workspace, binary, rows, columns)` 本來就是 runtime-generic 的，重寫等於製造第二套安全邊界。
- *把 shell 做成 CLI session 的第二個 tmux window*：省一個 session row，但會讓「終止 CLI」與「終止 shell」變成同一件事的兩個一半，且 P3 filesystem relay 以 session id 取 workspace（`manager.go:168`）會對不上。
- *記錄 shell 指令以換取可稽核性*：與 ADR 0004／`TECH-SEC-08` 直接衝突。

### 1.4 PRD 修訂內容

**(a) `SCOPE-011`（第 107-109 行）** 依 §1.2 選項 A 改寫，保留 `<a id="scope-011">` 與 `<a id="scope-011-ac-01">` 兩個 anchor——traceability 以 anchor 定位，改掉 anchor 會使 `anchor.missing` 驗證失敗。

**(b) 新增 `## FR-SHELL-001 系統終端機`**，置於 `FR-WORKSPACE-005` 之後。格式必須與既有 FR 完全一致（`## FR-XXX-NNN 標題` + 每個 criterion 一個 `<a id="fr-shell-001-ac-0N"></a>`，見 `research/prd.md:713-731` 的寫法）。八個 criterion：

| ID | 內容 |
|---|---|
| `FR-SHELL-001.AC-01` | Node 可停用系統終端機；停用後該 Node 上不得開啟 |
| `FR-SHELL-001.AC-02` | 僅持有 `terminal.shell` 的使用者，且僅於自己擁有的 Session 上，可開啟系統終端機 |
| `FR-SHELL-001.AC-03` | 前端僅指定 Runtime ID，不得指定 Binary、Command 或 Shell 指令字串 |
| `FR-SHELL-001.AC-04` | 系統終端機綁定於一個 CLI Session；該 Session 結束時一併結束 |
| `FR-SHELL-001.AC-05` | 其他使用者（含 Admin）不得連線至他人的系統終端機 |
| `FR-SHELL-001.AC-06` | 系統終端機的建立、連線與終止須留下稽核紀錄；終端機內容不得寫入資料庫或 Log |
| `FR-SHELL-001.AC-07` | 系統終端機計入 Node 與使用者的 Session 上限 |
| `FR-SHELL-001.AC-08` | 關閉終端機或離開 Session 工作區時，系統終端機即終止 |

**(c) §10.6** 的中央區 tab 說明補上第三個 tab（`WT-01` 已改成兩欄與 tab，這裡只是加一列）。

**(d) tech.md** §12.2 訊息類型的 `session.start` runtime 值域補 `shell`；§16.1 補「TERMINAL tab 僅於自己擁有的 Session 且 Node 未停用時出現」。

### 1.5 驗收

- ADR 0021 已合併，§1.3 的四項齊備。
- PRD 修訂已合併，`scripts/trace validate` 通過（anchor 全部存在）。
- `WT-04` 的決定（A/B/C）記錄在 `plan/08/05-implementation-status.md`，含決定者與日期。

---

## WT-05：契約 v1.5.0、`terminal.shell` action 與 migration

### 2.1 契約 v1.5.0（compatible）

`runtime` 是 wire 上的封閉 enum，新增值是契約變更（決策 D12）。**必須先於 consumer 合併。**

| 檔案 | 變更 |
|---|---|
| `contracts/v1/schemas/messages/session-start.schema.json` | `runtime.enum` 加 `"shell"`（現為 `["claude","codex","fake"]`） |
| `contracts/v1/schemas/messages/runtime-item.schema.json` | `runtime.enum` 加 `"shell"`（現為 `["claude","codex"]`）——node 要能回報 shell 的可用性與 binary 解析結果 |
| `contracts/v1/fixtures/valid/` | 新增 `session-start-shell.json`、`node-runtime-status-shell.json`（既有測資皆為 kebab-case，勿用底線） |
| `contracts/v1/fixtures/invalid/` | 新增 `session-start-shell-with-binary.json`：`runtime: "shell"` 同時帶 `binary`／`command` 欄位 → 必須因 `additionalProperties:false` 被拒。**這是把 `SEC-002` 釘在 wire 上的黃金測資**，缺它等於只有註解在防守（對照既有的 `daemon-update-with-binary-path.json` 同一手法） |
| `contracts/v1/fixtures/manifest.json` | 同步新增測資的雜湊 |
| `contracts/CHANGELOG.md` | 新增 `## 1.5.0 — <日期> (compatible)`：說明 runtime enum 新增 `shell`、**明確寫下 payload 形狀未變（沒有新增任何欄位）**、以及新錯誤碼 |

三個 consumer 必須同步（`contracts/CHANGELOG.md` 既有條目的紀律）：Python schema 驗證、Go codec、TypeScript。

### 2.2 Runtime 允許清單：七個必須同步的位置

漏掉任一處的症狀都是「某一層拒絕、另一層放行」，而且不會是同一個錯誤訊息：

| # | 位置 | 現況 | 變更 |
|---|---|---|---|
| 1 | `daemon/internal/config/config.go:110` `AllowedRuntimeIDs` | `{claude, codex}` | 加 `shell` |
| 2 | `daemon/internal/tmux/client.go:84-86` `allowedRuntimeID` | `claude/codex/fake` | 加 `shell` |
| 3 | `daemon/internal/protocol/codec.go:203` `validRuntimeID` | `claude/codex/fake` | 加 `shell` |
| 4 | `daemon/internal/protocol/codec.go:272` `node.runtime_status` 項目檢查 | `it.Runtime != "claude" && it.Runtime != "codex"` | 加 `shell` |
| 5 | `daemon/internal/install/plan.go:56-59` `DetectRuntimes` | `claude`/`codex` 皆 `Enabled: true` | 加 `"shell": {Enabled: true, Binary: "bash"}`。D6 已改為預設啟用；`Load` 端還需要 `applyRuntimeDefaults()` 讓**設定缺項也視為啟用**，否則既有 node 的 config 沒有這個區塊就等於停用（見 `03-…md` §1.2） |
| 6 | `backend/app/services/sessions.py:51` `RUNTIMES` | `{claude, codex, fake}` | 加 `shell` |
| 7 | `backend/app/services/sessions.py:92` `_require_runtime` | `fake` 直接早退，不查 `node.runtimes` | **`shell` 不得比照 `fake`**：必須走 `node.runtimes` 的 `available` 檢查，否則 node 端的停用開關形同不存在 |

**刻意不改**：`backend/app/services/dashboard.py:81` 的 `BASE_RUNTIMES = ("claude", "codex")`。它驅動「runtime 可用性」區塊，把 shell 加進去會讓所有停用 shell 或沒有 bash 的 node 顯示為「shell 不可用」——那是設定，不是故障（該檔 `:314-316` 對「沉默不等於否定」已有同樣的處理原則）。

### 2.3 `terminal.shell` action

| 檔案 | 變更 |
|---|---|
| `backend/app/services/rbac.py:26-35` | 新增 `TERMINAL_SHELL = "terminal.shell"` |
| 同檔 `:48-53` | 加入 `_DEVELOPER_ACTIONS`（D7）。`_ADMIN_ACTIONS = _DEVELOPER_ACTIONS \| {…}`（`:54`）會自動繼承，**不要在 Admin 集合裡重複列一次**。`_VIEWER_ACTIONS`（`:47`）維持不變 |
| `frontend/src/api/dto.ts:504-513` | 新增 `export const ACTION_TERMINAL_SHELL = "terminal.shell";` |
| `backend/app/db/migrations/versions/0012_seed_terminal_shell_action.py` | idempotent seed，授予 Admin 與 Developer；**Viewer 不得取得** |
| `docs/permission-matrix.md` | 以 `uv run --project backend python ../scripts/p4/render_permission_matrix.py --write` 重新產生（檔頭標明是產生檔，不要手改） |

`backend/tests/db/test_permission_matrix.py` 已有三項自動斷言（rbac.py ↔ seed migration ↔ `dto.ts`，以及「每個 action 都有地方在強制」）。少改任一處就會失敗——**不要用 skip 繞過，那正是這個測試存在的理由**。migration 測試沿用 P4 的四種情境：clean、repeat、prior-data、**permission contraction**（把權限拿掉也要生效）。

### 2.4 Migration `0013`：parent 綁定

```
0013_shell_session_parent.py
  terminal_sessions.parent_session_id  UUID NULL  REFERENCES terminal_sessions(id)
  index  ix_terminal_sessions_parent   (parent_session_id)
  partial unique index  uq_terminal_sessions_live_shell
      (parent_session_id) WHERE runtime = 'shell'
                            AND status IN ('starting','running','disconnected')
```

- **nullable**：CLI session 的此欄為 NULL，既有資料不需回填。
- **partial unique**：一個 CLI session 同時只能有一個活著的 shell（D8 的資料庫層保證）。用 status 過濾而非全表唯一，才允許「關掉再開」。三個狀態取自 `sessions.py:31-37` 的狀態常數；`TERMINAL_STATES`（`:39`）以外的都算活著。
- 下行 migration 必須能在有 shell session 的資料上執行（先 `UPDATE … SET parent_session_id = NULL`，再 drop）。

### 2.5 錯誤碼

只新增一個，其餘複用：

| 情境 | 碼 | 狀態 |
|---|---|---|
| node 已停用 shell 或無可用 binary | `RUNTIME_NOT_FOUND`（既有） | 409 |
| 使用者無 `terminal.shell` | 403（action 層，無需新碼） | 403 |
| 該 CLI session 已有活著的 shell | **`SHELL_ALREADY_OPEN`（新增）** | 409 |
| 超出 node/user 上限 | `SESSION_LIMIT_REACHED`（既有） | 409 |

`docs/error-catalog.md` 補一列 `SHELL_ALREADY_OPEN`，並依該檔既有欄位填寫（狀態、意義、原因、處置、是否可重試、來源層）。

### 2.6 驗收

- `make contract` 通過，新測資在 Python／Go／TypeScript 三處行為一致（含那筆帶 `binary` 欄位必須被拒的 invalid fixture）。
- `make traceability-validate` 通過。
- `backend/tests/db/test_permission_matrix.py` 全綠。三角色對 shell 端點的預期：**Viewer 403（action 層）、Developer 對他人 session 403（scope 層）、Developer 對自己 session 成功**——三例都要有測試，因為它們失敗的層級不同，只測其中一個看不出另一個是否真的在擋。
- migration `0012`/`0013` 的 upgrade→downgrade→upgrade 在 `CLIORA_TEST_DATABASE_URL` 上可重複執行。
