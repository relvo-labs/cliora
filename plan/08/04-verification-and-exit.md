# 04 — 驗證、安全審查與退出（WT-09、WT-10、WT-11）

## WT-09：Traceability 註冊與影響分析

這個 repo 的 traceability 目前處於**完整 release blocking**（ADR 0019 第三階段，`traceability/baseline-debt.json` 為空，`scripts/trace coverage --scope all --strict` 退出 0）。本期同時新增與移除規格行為，兩個方向都必須落到 `traceability/`，否則 `make traceability` 會失敗。

### 1.1 影響分析（先做，不要事後補）

```bash
scripts/trace impact --base master --head HEAD
```

在 `WT-01` 與 `WT-08` 的 PR 上各跑一次。它會依 `links.json` 的 target locator 反查「這次改的檔案關聯到哪些 criterion」。`SessionWorkspaceView.vue`、`useTerminalSession.ts`、`authz.py`、`sessions.py` 都是既有 criterion 的 implemented_by 目標，所以兩張票都會有命中；命中清單就是「必須確認仍然成立或必須改敘述」的 criterion 清單。

### 1.2 新增 `FR-SHELL-001`

`traceability/requirements.json` 新增一筆（格式對照 `FR-WORKSPACE-004`）：

```json
{
  "id": "FR-SHELL-001",
  "kind": "functional",
  "title": "系統終端機",
  "source": { "path": "research/prd.md", "anchor": "fr-shell-001" },
  "lifecycle": "active",
  "applicability": ["mvp"],
  "criticality": "must",
  "owner": "central",
  "criteria": [ /* AC-01 … AC-08，source_anchor 對應 WT-04 §1.4(b) 寫入 PRD 的 anchor */ ]
}
```

每個 criterion 的 `verification_profile` 為 `automated`（八條都有對應自動測試，見 `03-…md` §2.7／§3.5）。

**`kind: functional` + `criticality: must` 意味著每個 criterion 都需要四類 `role: "primary"` 連結**（`scripts/traceability/validate.py:433-434`）：

| 連結型別 | target kind | 本期的目標 |
|---|---|---|
| `planned_by` | `plan` | `plan/08/03-system-terminal-implementation.md`（AC-01/02 指向 `plan/08/02-…md`） |
| `specified_by` | `source` | `research/prd.md`（AC-03 另加 `research/tech.md`） |
| `implemented_by` | `code` | `backend/app/services/authz.py`、`backend/app/api/http/sessions.py`、`daemon/internal/runtime/runtime.go`、`frontend/src/views/SessionWorkspaceView.vue`（依 criterion 分派） |
| `verified_by` | `pytest`／`gotest`／`vitest`／`playwright` selector | 對應測試，並掛 `gate_id`（`GATE-BACKEND-DB`、`GATE-DAEMON-RACE`、`GATE-FRONTEND-UNIT`、`GATE-BROWSER-E2E`） |

缺任何一類 → 該 criterion 狀態為 `specified`、`missing` 非空、`criticality: must` → **列入 blocking，release gate 退出非零**。

連結 id 沿用既有命名：`LNK-FR-SHELL-001-AC-01-PLANNED-BY` 等。

> **順序陷阱**：`validate.py` 會檢查 selector 路徑是否真的存在（`selector.path_missing`，`:403`）。所以 `verified_by` 連結必須與測試檔在同一個 PR 落地；先註冊需求、後補測試會讓中間每一個 commit 的 `make traceability` 都是紅的。

### 1.3 `SCOPE-011` 的處置（選項 A）

```
SCOPE-011.AC-01:  "lifecycle": "deprecated"  + rationale（引用 ADR 0021）
新增連結:  FR-SHELL-001.AC-03 --supersedes--> SCOPE-011.AC-01
```

**這一步不能省。** `lifecycle: deprecated` 的 criterion 若沒有來自替代者的 `supersedes` 連結與書面 rationale，靜態驗證直接失敗——這個規則存在的原因就是：撤回需求是清掉 coverage 缺口最便宜的手段，所以它被刻意做得需要留痕。

### 1.4 版面部分（波次 0）的 traceability

- `FR-TERM-001`（Terminal 顯示，12 個 criterion，owner `frontend`）與 `FR-FILE-002`（檔案預覽，8 個）是 `WT-03` 最可能命中的兩組。逐條確認敘述在 tab 化之後仍然成立；若某條敘述綁定了「與 Terminal 同時可見」這類分割版面的假設，改敘述並在 rationale 註明由 `plan/08` 取代。
- 「面板拖曳／收合」若在任何 criterion 中被斷言過，一併走 `deprecated` + rationale（理由：從未實作，且已在 `WT-01` 從 tech §16.1 移除）。
- 產生視圖：`make traceability-render`，確認 `docs/traceability/*.md` 的差異只包含預期項目。

### 1.5 驗收

```bash
make traceability      # validate + selectors + coverage(strict) + baseline + tests
```

全綠，且 `docs/traceability/coverage.md` 中 `FR-SHELL-001.AC-01`…`AC-08` 皆為 `verifiable`。

---

## WT-10：安全審查

沿用 `docs/security-review-p4.md` 的格式，產出 `docs/security-review-p8.md`。**每一項都要有可重跑的測試或指令，不接受「已檢視」。**

| # | 對抗項目 | 期望 | 證據 |
|---|---|---|---|
| 1 | 非 owner 持有效 ws-ticket 連上他人 shell | handshake 以 1008 關閉 | pytest（WS） |
| 2a | Viewer 直接 `POST /api/sessions/{id}/shell` | 403（**action 層**，資源尚未載入） | pytest |
| 2b | Developer 對**他人**的 session 開 shell | 403（**scope 層**，ownership）。D7 放寬後這是主要邊界，必須單獨測，不能與 2a 混為一談 | pytest |
| 3 | ticket 鑄造後角色被降級，才發起連線 | 拒絕（`may_view_session` 在 handshake 重查，`ws/terminal.py:87`） | pytest |
| 4 | node 明確 `enabled: false` 時 Central 要求開 shell | 409 `RUNTIME_NOT_FOUND`；daemon 端亦拒（雙重）。另需一例：**明確停用不會被 `applyRuntimeDefaults()` 覆寫回啟用**（`03-…md` §1.2） | pytest + Go test |
| 5 | wire 上塞 `binary`／`command`／`args` 進 `session.start` | 三個 consumer 一致拒絕 | `contracts/v1/fixtures/invalid/` + `make contract` |
| 6 | shell 全生命週期後檢查 audit／log／metrics | 無 terminal bytes、無指令字串、無 binary 路徑 | pytest（redaction） |
| 7 | 對 shell session 發 `terminal.control_acquire` | 丟棄（`may_takeover_session` 對 shell 恆 False），並計入 authz 拒絕計數器 | pytest |
| 8 | 用 shell session id 打 filesystem 端點 | 403（`may_browse_files` 對 shell 恆 False） | pytest |
| 9 | 瀏覽器強制中止，不送 terminate | idle 逾時後 shell 被終止，node 上無殘留 tmux session | integration／手動演練 |
| 10 | daemon 執行身分 | 非 root；shell 的權限上界等於 daemon 的權限上界，並在 ADR 0021 明載 | 部署設定檢查 |

第 10 項是整個設計最重要的一句話：**shell 沒有提升任何權限**，它只是把 daemon 既有的權限暴露成互動介面。如果哪天有人把 daemon 改成 root 執行，這個功能的風險等級會瞬間改變——所以它必須寫在 ADR 裡，而不是只存在於某個人的理解中。

---

## WT-11：驗收、evidence 與 exit gate

### 3.1 Evidence 腳本

新增 `scripts/wt/evidence.sh <輸出目錄>`，沿用 `scripts/p3/evidence.sh`／`scripts/p4/evidence.sh` 的紀律：**每一道 gate 都記錄 exit status，任一失敗整支非零，skip 要誠實標記 skip 而不是當成 pass。**

| Gate | 指令 | 本機可跑 |
|---|---|---|
| 格式／lint／typecheck | `make format-check lint typecheck` | ✅ |
| 前端單元 | `npm run test:unit -- --run` | ✅ |
| 後端單元 | `pytest backend/tests -q` | ✅ |
| 後端 DB | `make test-db`（需 `CLIORA_TEST_DATABASE_URL`） | ✅ |
| Daemon race | `go test -race ./...` | ✅ |
| 契約 | `make contract` | ✅ |
| Traceability | `make traceability` | ✅（需兩個 database 環境變數） |
| Daemon integration | `make integration` | 需 tmux；無則 skip |
| Browser E2E | `npm run test:e2e` | 需 `E2E_FULL_STACK=1` + 全棧；WebKit 僅 CI |
| Shell E2E | 同上 + 一個 shell 可用的 online node（預設即可用，無需額外設定） | ~~**僅 CI／staging**~~ ✅ **本機可跑**（見下） |

> **修正（2026-07-31，實作後）**：最後兩列原本判斷為僅 CI／staging，是錯的。`scripts/e2e/run-stack.sh`
> 本來就是 rootless 的（`cmd/enroll-dev` + Fake CLI，不碰 systemd），只需要 go、tmux 與一個
> 空的 PostgreSQL database——三者在跑得動 DB gate 的機器上都已經有了。`evidence.sh` 因此改為
> 吃 `E2E_STACK_DATABASE_URL` 自己把全棧起起來，Chromium 與 Firefox 兩個引擎在本機實跑通過，
> 包含真 node 上的真 `bash`。**只有 WebKit 仍是 CI-only**（裝系統函式庫需要 root）。
>
> 把這兩列判成 CI-only 的代價不是少跑一次測試：這個 leg 在被跳過的期間爛掉了，而且沒有任何
> gate 會變紅（`05-…md`「退出條件補齊」）。**一道無條件 skip 的 gate，綠燈與紅燈是同一個顏色。**

### 3.2 CI

`.github/workflows/wt.yml`，沿用 `p2.yml`／`p3.yml` 的結構（含用 Fake CLI 起一個 online node 的 `scripts/e2e/run-stack.sh`）。shell E2E 需要在該 stack 的 node config 中把 `runtime.shell.enabled` 設為 true——**這是測試環境的設定，不得改動 `install/plan.go` 的預設值來讓 CI 變綠**。

### 3.3 Exit 條件

**版面（波次 0）——全部必須關閉：**

1. 左欄已移除，五份規格文件同步完成（`01-…md` §1.2），`grep` 檢查無殘留。
2. `mount()` 可重掛，且隱藏容器不會污染 PTY 尺寸（`WT-02` 四例測試全綠）。
3. tablist 通過鍵盤與 ARIA 驗收；切 tab 不新增 WebSocket 連線；反覆切換後 CLI 仍可操作。
4. 1440×900 與 <1100px 皆無水平溢位。

**系統終端機（波次 2）——若 `WT-04` 選 A：**

5. ADR 0021 已合併且含四項必記內容；PRD 修訂與 `SCOPE-011` supersedes 鏈完成。
6. `FR-SHELL-001` 八個 criterion 在 `docs/traceability/coverage.md` 皆為 `verifiable`。
7. `WT-10` 十項全部有證據，無未處理 Critical／High。
8. 寬預設（D6／D7）的四項補償控制各有通過的測試：ownership 邊界（第 1、2b、7、8 項）、daemon 非 root（第 10 項）、殘留 shell 回收（第 9 項）、audit 標記與 redaction（第 6 項）。`Viewer` 仍無 `terminal.shell`。
9. 既有 node 的升級 release note 與 runbook 已寫明「升級後取得遠端 shell 能力」，並說明如何以 `enabled: false` 停用。
10. Shell E2E 在 CI 上綠（本機 skip 者明確標為 CI-gated）。

> `WT-04` 已於 2026-07-31 決定為**選項 A（收窄 `SCOPE-011`）**，選項 C 的分支不再適用。

### 3.4 產出報告

`docs/wt-report.md`：交付內容、量測結果、未關項與其歸屬（CI／staging／產品決定），以及 evidence 目錄位置。格式對照 `docs/p3-report.md`／`docs/p4-report.md`，包含一節「這一期發現但當時沒修的問題」——`00-execution-plan.md` §6 的三項降級缺陷要寫進去，否則下一個人會以為那是漏網。
