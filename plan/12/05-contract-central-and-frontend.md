# 05 — 契約、Central、前端與 skills（PV-06 ~ PV-09）

## 1. `PV-06` 契約 v1.7.0（compatible）

適用 skill：`terminal-websocket-protocol`（「Update all implementations and contract tests atomically」）。

### 1.1 兩個欄位，只回報不指定

`contracts/v1/schemas/messages/runtime-item.schema.json`：

```json
"sandbox_bypass": {"type": "boolean"}
```

`contracts/v1/schemas/messages/node-register.schema.json`：

```json
"privileged_terminal": {"type": "boolean"}
```

- 兩者皆**選用**（不進 `required`）：舊版 daemon 不送這兩個鍵，Central 必須照樣接受。
- `additionalProperties: false` 不動。
- `node-runtime-status` 透過 `$ref` 引用 `runtime-item`，因此自動涵蓋 —— 這也是為什麼
  codex 的姿態放在 runtime item 而不是 node 層：**它會隨 runtime 重新偵測而更新**，
  而 `privileged_terminal` 只在 daemon 啟動／重連時才可能改變（unit 與 sudoers 都需要重啟才生效）。
- `sandbox_bypass` 只會出現在 `runtime: "codex"` 的項目上。schema **不強制**這一點
  （`if/then` 會讓這個小 schema 變成三倍長度），改由三個 consumer 各自忽略其他 runtime 的該欄位，
  並由 daemon 端測試（`TestLaunchArgsOnlyCodexHasFlags`）保證不會送出。

### 1.2 語意（寫進 CHANGELOG，不只寫進 schema）

| 欄位 | 語意 | 不是什麼 |
|---|---|---|
| `runtime-item.sandbox_bypass` | 「這個 runtime 在這台 node 上啟動時**實際上**會停用沙箱與核准流程」 | 不是「設定要求停用」。設定要求但旗標不被支援時，這裡是 `false`（`00-…md` D3） |
| `node-register.privileged_terminal` | 「這台 node 的系統終端機**可經 sudo 取得 root**」 | 不是「daemon 以 root 執行」（它沒有），不是一個平台可以改的設定 |

### 1.3 三個 golden invalid fixture

`contracts/v1/fixtures/invalid/`：

| 檔案 | 內容 | 守住什麼 |
|---|---|---|
| `session-start-with-args.json` | `session.start` payload 夾帶 `"args": ["--dangerously-bypass-approvals-and-sandbox"]` | 前端／Central 不得指定啟動參數（`SEC-002`、ADR 0023 §2.4）。**這是本期最重要的一個 fixture** |
| `session-start-with-sandbox-flag.json` | 夾帶 `"sandbox": "bypassed"` | 連「要求某種姿態」都不行 —— 姿態是 node 的事實，不是請求的一部分 |
| `node-register-privileged-terminal-non-boolean.json` | `"privileged_terminal": "yes"` | 型別；一個字串 `"false"` 在三種語言裡有三種真值行為 |

`contracts/v1/fixtures/valid/` 加兩個：`node-register-privileged.json`、
`node-runtime-status-codex-sandbox-bypass.json`。
`contracts/v1/fixtures/manifest.json` 同步。

三個 consumer 都要跟著改，且必須在**同一個 PR**：
`backend/app/protocol/codec.py`、`daemon/internal/protocol/codec.go`、`frontend/src/protocol/decode.ts`。
瀏覽器不是這兩個欄位的消費者（姿態經 HTTP 取得），但 decoder 仍要驗 —— 沿用 1.6.0 的理由：
「一個不檢查就接受的型別，就是一個會轉送畸形資料的型別」。

### 1.4 `contracts/CHANGELOG.md`

新增 `## 1.7.0 — <date> (compatible)`，必須包含：

1. 兩個附加欄位與 `version` 仍為 `1`；
2. **「只回報、不指定」的設計原則**，並列出被刻意排除的欄位：`args`、`flags`、`sandbox`、
   `sudo`、`tmux_options`、`env`。這一段的寫法沿用 1.4.0（`daemon.update` 只有版本號）與
   1.6.0（`tunnel.open` 沒有 host 欄位）；
3. `sandbox_bypass` 是**實測值而非設定值**（`00-…md` D3）；
4. 沒有新增錯誤碼，並說明為什麼：旗標不支援不是錯誤（session 照樣啟動）、sudo 不可用不是錯誤
   （那是姿態），兩者都經由回報欄位表達。**加一個錯誤碼會迫使呼叫端把姿態當成失敗處理**。

## 2. `PV-07` Central

適用 skill：`backend-developer` → `fastapi`；migration 走 `seed-migration` 的規矩（本期無 seed 資料）。

### 2.1 資料層

`backend/app/db/migrations/versions/0017_node_privileged_posture.py`：

| 變更 | 型別 | 預設 |
|---|---|---|
| `nodes.privileged_terminal` | `Boolean` | `server_default=false`、`nullable=False` |
| `node_runtimes.sandbox_bypass` | `Boolean` | `server_default=false`、`nullable=False` |

- 兩欄都用**顯式欄位而非 `metadata` JSONB**：沿用 `update_status` 的判準
  （`models.py:86-90` 的註解）——「哪些 node 是特權姿態」是車隊層級的安全問題，
  必須可查詢、可排序，而 JSONB 裡的鍵不會有人去 index。
- `privileged_terminal` 加 index：這是「列出所有特權節點」的查詢，會被安全審查與 runbook 用到。
- `server_default=false` 的意義：既有 node 在下一次 `node.register` 之前顯示為非特權。
  **這是正確的方向**（未回報 ≠ 特權），並且在 daemon 重啟後就會被更新為真實值。
- downgrade 要能跑（既有 migration 的慣例）。

### 2.2 服務層

- `RegisterNodeInput`／`RuntimeItemInput`（`backend/app/api/http/schemas.py` 與
  `backend/app/services/nodes.py` 的 dataclass）各加一個 optional 布林，預設 `False`。
- `persist_registration`（`nodes.py:222`）：`node.privileged_terminal = data.privileged_terminal`；
  child rows 的重建處（`nodes.py:246`）帶上 `sandbox_bypass=r.sandbox_bypass`。
- **HTTP 註冊路徑**（`agentd install` 的 `POST /api/nodes/register`）也要接同樣的欄位，
  否則新裝的 node 在第一次連線前姿態是空的。
- 姿態變更要不要記稽核？**要**，但記在 node 上而非 session 上：
  `persist_registration` 偵測到布林值改變時記一筆 `node.posture_changed`
  （metadata：`{privileged_terminal: old→new}`）。理由：這是一件「機器上有人改了 unit」的事，
  而平台是唯一會把它記下來的地方。**新增 audit action 要同步
  `docs/permission-matrix.md` 的產生來源與 `rbac.UNENFORCED_ACTIONS` 的檢查**（plan/11 踩過這個坑）。

### 2.3 稽核 metadata

`sessions.py:222` 的 `metadata={"runtime": runtime}` 擴充為：

```python
metadata={
    "runtime": runtime,
    "sandbox": "bypassed" if <該 node 該 runtime 的 sandbox_bypass> else "enforced",
    "privileged": node.privileged_terminal,
}
```

- 值取自**建立當時**的 node 姿態快照（DB 欄位），不是即時問 node。稽核要回答的是
  「當時是什麼姿態」，而不是「現在是什麼姿態」。
- `shell` runtime 的 `sandbox` 一律是 `"n/a"`（它沒有沙箱可談，寫 `enforced` 會是假話）。
- `ADR 0021 §5` 不變：**不記錄終端內容**。這裡記的是姿態，不是行為。

### 2.4 API 與錯誤碼

- Nodes 列表與詳情 DTO 加 `privileged_terminal`；runtime 陣列的每一項加 `sandbox_bypass`。
- **不新增錯誤碼**（§1.4 的理由），`backend/app/api/error_catalog.py` 與
  `docs/error-catalog.md` 不動。
- RBAC 不動（`00-…md` D12）。姿態欄位跟著既有的 node 讀取權限走。

### 2.5 測試

`backend/tests/db/test_node_api.py`、`test_node_ws.py` 擴充：

| 測試 | 斷言 |
|---|---|
| 舊版 daemon 的 register（沒有新欄位） | 200，兩個布林為 false，**沒有** `node.posture_changed` 稽核 |
| 特權 register | 欄位落地、DTO 回傳、產生一筆 `node.posture_changed` |
| 同樣姿態再 register 一次 | **不**產生第二筆稽核（否則每次重連都會塞一筆） |
| 姿態由 true → false | 產生稽核，metadata 含新舊值 |
| `session.create` 稽核 | metadata 三個鍵；`shell` runtime 為 `"n/a"` |
| `test_scope_guards.py` | `session.start` 的欄位集合仍是五個；新增斷言：payload 不得含 `args`／`flags`／`sandbox`／`sudo` |

## 3. `PV-08` 前端

適用 skill：`vue-naive-ui-workflow` ＋ `web-design-guidelines`／`ux-polish-reviewer`（審查）。

### 3.1 姿態要顯示在三個地方

| 位置 | 內容 | 為什麼是這裡 |
|---|---|---|
| `NodesView.vue`（列表） | 特權節點一個小標籤 | 「我的車隊裡有幾台是特權的」是一眼要能看出來的事 |
| `NodeDetailView.vue` | 一個「執行姿態」區塊：`終端機：可提權（sudo）`／`不可提權`；`codex 沙箱：已停用`／`啟用`；並說明這兩者由 node 上的檔案決定、平台無法變更 | 管理者查一台機器時的落點；也是 `SEC-007.AC-03` 的驗收點 |
| `SessionWorkspaceView.vue` | CLI 面板標頭：codex session 顯示「沙箱：已停用」；系統終端機的既有 `shell-notice`（`SessionWorkspaceView.vue:411`）補一句「此 Node 可經 sudo 取得 root」 | 使用者按下 Enter 之前，資訊要在他眼前（`00-…md` D10） |

`NewSessionDialog.vue`：選到 `codex` 且該 node 的 `sandbox_bypass` 為 true 時，
在 runtime 欄位下方顯示一行說明。**不加確認勾選框**：使用者已在 D0 表明立場，
一個每次都要點的確認框只會被訓練成無意識點擊（plan/11 D14 是相反的情況 —— 那裡有兩個
不同的人在做兩個不同的決定，這裡沒有）。

### 3.2 終端機操作提示

`terminal-pane` 下方一行 `terminal-hint`（灰字、`flex: 0 0 auto`，與既有 `shell-status` 同樣不搶空間）：

```text
滾輪可檢視先前輸出（按 q 回到即時輸出）· 選取文字請按 Shift 拖曳
```

- 兩句話都是本期產生的新操作知識（`03-…md` §2.3、`00-…md` D7）。
- **不要寫成「按 Shift 捲動」**：xterm.js 的 `getLinesScrolled` 遇 `shiftKey` 直接回 0，
  Shift＋滾輪不會捲動。
- 提示只在 `mouse on` 生效的 node 上才是真的。但姿態欄位不涵蓋 tmux 選項，
  而**只要 daemon 是本期之後的版本就一定是 on**（不可設定，`03-…md` §4）——
  因此以 `daemon_version` 判斷是不必要的複雜度：提示常駐。

### 3.3 前端測試

- `dto.ts` 型別與 `NodeDetailView`／`NodesView`／`SessionWorkspaceView` 的三個顯示分支各一個
  vitest 案例（沿用 `NodeDetailUpdate.test.ts` 的手法）。
- 姿態欄位缺失（舊 node）時**不得**顯示「可提權」——測試要涵蓋 `undefined`。
- e2e 的捲動斷言在 `03-…md` §3。

## 4. `PV-09` `.agent/skills` 更新

`.agent/skills/AUTHORING.md` 的規則要一起遵守：只改 `SKILL.md`、不加 per-skill README、
不複製 `research/` 的內容、保持 imperative 與 500 行以內。

| 檔案 | 修訂 | 為什麼一定要改 |
|---|---|---|
| `cliora-project-context/SKILL.md` | 最後一段的不變量清單：把「Preserve native Claude/Codex terminal semantics」改為明確版本 ——「codex 由 daemon 以固定參數表啟動，預設停用沙箱與核准流程（ADR 0023）；參數表只在 daemon 內，node 只能以布林開關」；另加兩條：「daemon 仍非 root，但特權姿態下系統終端機可經 sudo 取得 root」、「tmux 環境（socket 與選項）由 daemon 擁有」 | 這份 skill 是每一次 Cliora 工作的入口。它現在寫的「preserve native Claude/Codex terminal semantics」在本期之後會被讀成「不要加旗標」，而那與已核准的決定相反。**一份會讓下一個 agent 做錯事的 skill 比沒有 skill 糟** |
| `go-daemon-development/SKILL.md` | 第 4 點（typed runtime operations / allowlisted arguments）補一句：啟動旗標的唯一合法位置是 daemon 內的固定表；config 與 wire 都不得有 argv 欄位。最後一段的「Run non-root」保留，補「特權姿態下 `NoNewPrivileges` 被移除，但服務身分仍非 root」 | 「Run non-root」單獨存在會讓人以為 sudoers drop-in 違反 skill |

**不新增 skill。** 本期沒有一個新的、可重複的工作型態需要自己的 skill；
`.agent/skills/README.md` 與 `RELATIONSHIPS.md` 標為 auto-generated 且倉庫內沒有產生器，
不新增 skill 就不需要動它們（技能數量與關係圖都不變）。
`AUTHORING.md` §5 提到的 `quick_validate.py` **在此倉庫中不存在**（已確認），
因此驗證方式是照 `AUTHORING.md` 的規則逐條人工核對，並在 `07-…md` 記下這個事實 ——
不要為了讓步驟看起來完整而新增一個沒人維護的驗證腳本。
