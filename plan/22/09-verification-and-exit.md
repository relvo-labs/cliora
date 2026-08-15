# 09 — 驗證與出口（`RQ-12`）

測試矩陣、十個 gate、**24 條**出口條件、**一節**安全審查、旗標關閉回歸、合併關卡。

## 1. 測試矩陣

| 層 | 測什麼 | 大約條數 |
|---|---|---|
| contract fixtures | **零新增。** 反過來有一條斷言：`contracts/` 全樹雜湊與基線相同（§3） | 0（＋1 gate） |
| daemon 單元 | 三個新子命令、`ask` 的本機檢查、離線訊息、`spec template` 離線可用 | 12 |
| Central 單元 | 四道 dispatch 拒絕、`card_kind` 鎖定、情境包兩種渲染與預算截斷順序 | 20 |
| Central 單元 | 提案樹六道驗證（含環的路徑訊息）、高風險關鍵詞、`overrides` 三條規則 | 18 |
| Central DB | migration 上下行、`sections` 白名單、只 INSERT、`depends_on` 翻譯的三種情況 | 16 |
| **授權** | **三個 `decided_by`／`approved_by` 欄位的每個寫入點**、run 憑證打七條人工路由全 401、`RUN_TOKEN_SCOPES` 內容斷言 | 14 |
| 前端 | `07-…md` §8 的三十條 | 30 |
| 端到端 | §5 的兩條 | 2 |

**「授權」自成一層而不是併進 Central 單元**，因為本期的風險全部是語意的
（README 的第一張表）：沒有新的對外副作用，會出事的方式是
**一份 Agent 寫的東西被當成人核准過的**。那一層的紅燈要一眼認得出來。

## 2. `RUN_TOKEN_SCOPES` 的斷言要寫成什麼形狀

```python
def test_run_token_scopes_are_exactly_two() -> None:
    assert RUN_TOKEN_SCOPES == frozenset({PROJECT_VIEW, TASK_UPDATE})
```

**不是** `assert TASK_APPROVE not in RUN_TOKEN_SCOPES`。

後者在有人加第三個動作時仍然會過，而本期新增了兩條 run 路由
——那正是「順手加一個 scope」最有動機的時刻。

同一個形狀套用在 `AGENT_FORBIDDEN_FIELDS`（本期加 `card_kind`）：斷言整個集合。

## 3. 十個 gate（`scripts/rq/gates.sh`）

四個繼承自前期並重新指向本期基線，六個是新的。

| Gate | 守什麼 | 違反時的症狀為什麼是靜默的 |
|---|---|---|
| `GATE-RQ-SCHEMA-ADDITIVE` | 基線的每一行 schema 都還在 | 沿用 `plan/20/08` §6 第 9 條的集合比對版本 |
| `GATE-RQ-MIGRATION-ROUNDTRIP` | 降到 `0038_runner_features` 與基線逐位元組相同 | 降級目標是參數 |
| `GATE-RQ-TOUCH-LIST` | 禁區未被動：`daemon/internal/{runtime,runner,workspace,gitfetch}`、`push.go` 的五條約束區塊、`process.py:189-191` 的自動停用 | 動了會過所有測試 |
| `GATE-RQ-NO-STALE-PROMISE` | 沒有指向本期或更後的過期承諾 | 一句過期的承諾出現在安全審查會讀的地方（本期特別容易：RQ-11b 延後了，而它的設計寫在 `08-…md`） |
| 🆕 `GATE-RQ-CONTRACT-FROZEN` | **`contracts/` 全樹 sha256 與基線相同** | 既有的 `-CONTRACT-ADDITIVE` 只比對 fixture 清單，**允許新增**——而本期的承諾是一個位元組都不動（`01-…md` §1.1） |
| 🆕 `GATE-RQ-HUMAN-ACTOR` | `requirements.approved_by`、`task_proposals.decided_by`、`document_patch_proposals.decided_by` 的每一個賦值點都在一個 `require_action(TASK_APPROVE)` 的路由可達範圍內 | **本期最重要的一條。** 一個多出來的寫入點不會讓任何測試紅——資料看起來完全正常，只是那個「人」不是人 |
| 🆕 `GATE-RQ-NO-CARD-FROM-RUN` | `POST /api/cli/runs/proposal` 的呼叫圖不含 `TaskService.create_task` | 提案與卡片都存在、都對得起來，壞掉的是「人有沒有看過」 |
| 🆕 `GATE-RQ-APPEND-ONLY` | `feature_specs`、`task_proposals`、`document_patch_proposals` 三張表沒有 `update()` 呼叫（`status`／`decided_*` 欄位的白名單除外） | 就地改寫一份人看過的東西 |
| 🆕 `GATE-RQ-NO-PATCH-APPLY` | 處理 patch 提案的模組不 import `pathlib`／`os`／`shutil`，不出現 `open(` | 「既然都有 diff 了，加一個套用按鈕吧」——它會通過所有測試 |
| 🆕 `GATE-RQ-CONTEXT-DISPATCH` | 情境包的選擇只有一處 `match task.card_kind` | 第二處分支的第一個漏網值，會讓釐清卡拿到實作卡的情境包——**而那份情境包裡有機密提示，那是一句謊** |

> 十個是計畫值；上表列了十列，四個繼承的一樣不可略過。

### 3.1 `GATE-RQ-HUMAN-ACTOR` 怎麼實作

grep 不夠——`requirement.approved_by = actor_id` 可以寫成十種樣子。做法是**兩層**：

1. **靜態**：`ast` 走 `backend/app/`，找對這三個屬性的 `Assign`／`keyword`，
   收集所在函式；斷言集合等於一張三個元素的白名單。
2. **動態**：一個測試用 agent principal（session 與 run 兩種）
   對 OpenAPI 列出的**每一條**路由發一次請求，斷言三個欄位在資料庫中全程為 NULL。
   路由清單從 `app.routes` 動態取，**所以新增路由會自動被涵蓋**。

第二層是本期唯一一個「窮舉整個 API 表面」的測試。
它值得的理由：本期新增四條 run 路由，而下一期會再加，
而**忘記把新路由納入授權測試**是這類系統最常見的一種洞。

## 4. 24 條出口條件

前 13 條逐條對應 `research/02/10` §2.7；14–24 是本計畫加的。

**其中第 12 條本期不驗**（RQ-11b 延後，D5），所以本期實際要綠的是 **23 條**。
第 12 條保留編號而不刪除，理由與 traceability 把 FR-SPEC-008 標 `deferred`
而不是省略相同（`01-…md` §4.1）：**「沒做」與「不存在」在驗收表上要能分辨，
而只有前者是本期的刻意決定。**

### 4.1 主線（1–10）

| # | 條件 | 怎麼驗 |
|---|---|---|
| 1 | 丟一句模糊需求 → 釐清 run 領走 → **在看板訊息串裡提問**（不是另一個介面）→ 回答 → 產出規格草稿 | E2E ①；斷言問題那則訊息的 `task_id` 等於釐清卡，且需求詳情頁上沒有第二個輸入框 |
| 2 | 規格帶未解決 `open_questions` → **核准 API 回 409 並列出是哪幾個**；按鈕同時停用 | API 測試 ＋ 前端測試各一條。**兩條都要**——只有前端那條的話，V2.5 的 Agent 走的是 API |
| 3 | 未核准的規格**不能被拆解** | 兩處：dispatch 拒絕（`03-…md` §1.2 3b）與提案提交拒絕（`04-…md` §1.1） |
| 4 | 拆解產出的每張 Task 提案都帶完整 DoR 與 `source`／`delivery`；缺項的卡接受後**落 `backlog`** | 提案樹 fixture 一張 7/7、一張 5/7，接受後查 `stage` |
| 5 | 部分接受：勾 3 張建立 3 張，其餘保留；被拒絕的提案保留理由 | 斷言 `status='partially_accepted'`、`remaining_item_ids` 有值、`decision_note` 非空 |
| 6 | 建立出來的卡片顯示「來自需求 #N 的提案 #M」 | 前端測試 |
| 7 | 釐清 run 嘗試帶機密 → **dispatch 當下被拒** | `TASK_KIND_FORBIDS_SECRETS` |
| 8 | 釐清 run 的 `delivery` 是 `none` → **執行後遠端沒有任何變更**；工作目錄若有變更則明示 | **`git ls-remote` 前後逐位元組相同**，不是讀 log |
| 9 | Agent 嘗試自己核准規格或接受提案 → 被拒 | **401 而不是 403**（`03-…md` §4.4） |
| 10 | 24h 未回覆自動退 `blocked`，**已問到的內容保留為規格草稿** | 逾時之後 `feature_specs` 列數 > 0；`run.waiting_timeout` 的 `spec_count` 與它相符 |

### 4.2 UI Mockup（11–12）

| # | 條件 | 本期 |
|---|---|---|
| 11 | 未啟用 tunnel 整合時：`ui` gate **自動停用**；Project Settings 寫出原因；產出 mockup 變體的卡 dispatch 被拒並說明；**一般 UI 實作卡照常執行**；Agent 附截圖不受影響 | **四子項全驗**（`08-…md` §1） |
| 12 | 啟用之後的六條 | **本期不驗**，隨 RQ-11b（`08-…md` §3.4） |

### 4.3 旗標與回歸（13）

| # | 條件 |
|---|---|
| 13 | 兩個旗標關閉：完整 V1 回歸全綠；本期新增端點全數 404；`openapi-flags-off.json` 只允許新增路徑 |

### 4.4 本計畫加的（14–24）

| # | 條件 | 為什麼要加 |
|---|---|---|
| 14 | **`contracts/` 全樹與基線逐位元組相同** | 本期最容易被推翻的承諾（`01-…md` §1.1） |
| 15 | **一次一個問題**：有未答問題時 `POST /api/cli/runs/messages` 回 409；使用者回一句無關的話**算回答**；系統訊息**不算** | D3 的三個判定選擇各一條 |
| 16 | 本機（CLI）與伺服器對「有沒有未答問題」的判定**用同一組 fixture 得到同一個答案** | 兩份不一致的實作會被當成 flaky |
| 17 | 拆解 run 對**另一個**需求提案 → 404 | D2 的資源邊界。**404 不是 403**，與 `_own_task` 一致 |
| 18 | 提案樹的 `depends_on` 指向沒被勾選的卡片時：**不建相依、回報、那張卡落 `backlog`** | `04-…md` §4.4，本期最容易做錯的一格 |
| 19 | 提案的 `overrides` 只對 `accept_ids` 裡的節點生效；改 `readiness` 被拒 | `04-…md` §5 |
| 20 | `card_kind` 在有 run 跑過之後不可改；agent 憑證任何時候都不可改 | `02-…md` §1.1.1 |
| 21 | 高風險關鍵詞命中而 `risk != 'high'` → 422 | `04-…md` §2.4 |
| 22 | PRD patch 的 diff **以純文字渲染**：fixture 裡的 `<script>` 在 DOM 中是文字節點 | 本期唯一的 XSS 面 |
| 23 | patch 提案被接受後**沒有任何檔案被寫入**：`GATE-RQ-NO-PATCH-APPLY` ＋ 一條測試斷言接受前後 repo 樹不變 | `05-…md` §3.3 |
| 24 | 情境包不超過 6 KB，且超出時的截斷順序固定（規則段永不被截） | `03-…md` §2.3 |

## 5. 端到端：兩條

### E2E ① — 一句話走到卡片（本期的主線）

```text
建 Project（Traqora）→ 綁 runner → Requirements 分頁丟一句模糊需求
  → 派給 Agent 釐清 → runner 領走 → 提問 → 人回答 → 提問 → 人回答
  → Agent 送第 2 版規格（open_questions 清空）→ 人核准
  → 派給 Agent 拆解 → Agent 送提案（12 張 Task，其中 3 張缺 DoR）
  → 人勾 5 張、覆寫其中 1 張的 delivery、拒絕其餘並寫理由
  → 5 張卡建立，2 張落 backlog（1 張缺 DoR、1 張相依未勾）
  → 每張卡的詳情頁顯示「來自需求 REQ-x 的提案 #1」
  → git ls-remote 前後逐位元組相同
```

**用 `cmd/fakecli` 驅動 Agent 那一側**（V2.2 起既有），不用真的 LLM。
理由與前四期相同：E2E 要驗的是平台的路徑，不是模型的產出品質。

### E2E ② — 反面

```text
釐清卡宣告 required_secrets → dispatch 409
Agent 用 run 憑證打 /requirements/{id}/approve → 401
Agent 連問兩個問題 → 第二個 409
拆解 run 對另一個需求提案 → 404
提案含 required_secrets → 422
釐清卡 delivery: pull_request → dispatch 409
card_kind='mockup' 而整合未啟用 → dispatch 409
一張一般 UI 實作卡 → 照常進 done
```

**八條反面全部在同一條 E2E 裡**，因為它們共用同一組前置（一個專案、一個需求、一台 runner），
而分成八條 E2E 的成本是八次環境建置。

## 6. 安全審查：一節（`docs/security-review-v25.md`）

`research/02/10` §6 的三個觸發條件——**新憑證、新儲存面、新執行能力**——
本期**一個都沒有命中**（README 的第一張表）。
`research/02/10` 自己也寫了「V2.5 不必然觸發」。

**但仍然寫一節**，理由是本期有一個那三條沒有涵蓋的東西：

> **§1 — 一條讓 Agent 的輸出成為平台事實的新路徑。**

三個小節：

| 小節 | 問什麼 |
|---|---|
| 1.1 授權邊界 | 兩條新 run 路由的資源邊界是 `principal.task_id` 而不是 URL——**逐條檢查那個推導鏈**（`principal.task_id → tasks.requirement_id → 只能寫這個需求`）。並確認七條人工路由的 `require_action` 參數對基線零 diff |
| 1.2 三個「人」欄位 | `GATE-RQ-HUMAN-ACTOR` 的兩層實作是否真的窮舉；動態那一層的路由清單是否從 `app.routes` 取而不是硬寫 |
| 1.3 提供面 | patch 提案的 diff 與規格的 `sections` 都是 Agent 產生的字串，而 Cliora 是單一 origin（ADR 0020）。逐處確認渲染路徑：**純文字節點、不 `v-html`、沒有下載按鈕** |

**§1.3 是本節唯一真的動到攻擊面的地方**，而它的形狀與 D29 §4 完全相同
（不受信任內容 → 使用者瀏覽器）。所以它引用那一節而不是重新論證。

**不寫第二節。** 若 D5 被推翻（要做 RQ-11b），才加第二節：
「一個新的對外面：從 run 目錄經第三方 tunnel 提供靜態檔案」。

## 7. 旗標關閉回歸

沿用 `research/02/10` §3 的十一項，一項不減。本期特別要看的兩項：

| 項目 | 本期為什麼特別 |
|---|---|
| **Protocol 未變** | 本期宣稱 contract 零變更，所以這一項從「現有 fixtures 全數通過」升級成「**`contracts/` 全樹雜湊相同**」 |
| **DB 既有表逐欄比對** | 本期對 `tasks` 與 `feature_specs` 各加一欄。逐欄比對要能區分「新增欄位」與「既有欄位被改」——`02-…md` §6 的 `md5(舊欄位投影)` |

## 8. 合併關卡

**24 條全綠只是取得提案資格，不是核准。**
`v2` → `dev` 一律由人決定（`research/02/README` 第 6 條、`plan/21` 同一句）。

提案時要一起交的四樣：

1. `scripts/rq/gates.sh` 的十個 PASS。
2. 24 條出口條件的逐條證據（截圖／查詢輸出／測試名稱）。
3. `docs/security-review-v25.md`。
4. `docs/release-note-requirements-and-decomposition.md`，**其中「已知限制」至少四條**：
   - RQ-11b 未做，啟用 tunnel 整合的部署沒有 mockup 預覽（`08-…md` §1.4）。
   - Epic 與 User Story 在提案樹上只用於分組，接受時不建立成獨立項目（`07-…md` §4.5）。
   - `security` review gate 不存在；高風險工作靠 `risk: high` 與 `open_questions` 收斂（README「上游的另一半」§三）。
   - **「一次一個問題」對所有 run 生效，包含 V2.2 起既有的實作 run**——這是行為變更，不是新增（`03-…md` §3.4）。
