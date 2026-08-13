# 08 — 驗證、證據與出口（`TK-11`）

## 1. 共通完成定義（每張 ticket）

沿用 `research/02/10` §1：變更檔案清單與行為摘要、`make check` 通過、
涉及 daemon／tmux 的跑 `make integration`、涉及畫面的跑 `make e2e` ＋ 截圖、
涉及 DB 的跑 `make test-db` ＋ 上下行演練、涉及 RBAC 的三條矩陣測試全綠、
涉及 protocol 的 valid ＋ invalid fixtures 齊備、高風險的產出安全審查文件。

**不算完成**：跳過測試沒說明理由、驗證只是「看起來沒問題」、UI 改了沒截圖、
AC 沒逐項檢查、動了不相關的檔案。

## 2. 測試矩陣

| 層 | 覆蓋 | 票 |
|---|---|---|
| Contract | `context.project`／`projected` 各 valid ＋ **8 條 invalid**；既有 fixtures **零變更** | `TK-07` |
| Daemon 單元 | `VerbStore` 對 `.cliora/` 仍被拒（迴歸）；`VerbProject` 六條政策；mkdir；`FILE_EXISTS` → skipped；清理白名單；`.token` 的敏感檔分類 | `TK-07` |
| Daemon 整合 | 真實 workspace 投影 → `git status --porcelain` 空；第二次同版本被 skip；`.cliora` symlink 攻擊被拒 | `TK-07` |
| Daemon／CLI | argv[0] 分派；`.cliora/` 往上找的四種版面；**離線兩句訊息逐字比對**；`context show` 免連線 | `TK-08` |
| Central 單元 | 進站檢核四種結果；循環偵測三種環；Done Gate 本期只看 `dependsOn`；gate 的四種拒絕 | `TK-04` |
| Central 單元 | Agent scope 交集為空；`PATCH` 欄位層拒絕；跨 Project 404 | `TK-06` |
| Central DB | 併發 PATCH（樂觀鎖）；併發建卡（配號）；四道門的 token 撤銷；`redact_actors` 不動 `actor_kind` | `TK-02`／`TK-06` |
| RBAC | `test_permission_matrix.py` 三條；`UNENFORCED_ACTIONS` 仍為空 | `TK-04` |
| 安全 | token 五個「不出現」（含 **OpenAPI schema 斷言**）；gate 端點對 Agent 401；投影路徑逃逸 | `TK-06`／`TK-07` |
| 前端單元 | 看板分組；藍圖兩個未分類桶；三種 actor；拖曳三種回滾 | `TK-09` |
| E2E | 判準 1–6、8；旗標關閉的完整回歸 | `TK-11` |
| 手動 | 判準 4（情境包 ≤ 4 KB 的人工檢視）、判準 9（Traqora 上的 `git status`） | `TK-11` |

## 3. 旗標關閉回歸套組

`CLIORA_PROJECTS_ENABLED=false` 時**整套再跑一次**（沿用 `plan/16` 在 CI 裡的雙旗標 matrix，
`.github/workflows/v2-projects.yml` 加本期的項目）：

| 檢查 | 方法 |
|---|---|
| API 表面 | OpenAPI 與 `TK-00` 基線 diff：只允許新增路徑，且新增路徑全部 404 |
| **Protocol** | 既有 fixtures 全數通過；**逐檔 sha256 與基線相同**；舊 daemon（0.7.0）可連線並正常工作 |
| **daemon 0.8.0 在旗標關閉的部署上** | 行為與 0.7.0 相同：不收到任何 `context.project`，清理迴圈沒有東西可清 |
| 六個既有路由 | e2e 逐一造訪 `/dashboard`、`/nodes`、`/sessions`、`/enrollment`、`/audit`、`/settings/integrations` |
| 導覽與 Session Workspace 外觀 | 截圖與 V2.0 基線逐位元組比對 |
| Session 全生命週期 | 建立 → 操作 → 重整重連 → 接手 writer → 終止 |
| 檔案面 | 瀏覽、搜尋、預覽、圖片投放、一般上傳（含 `FILE_EXISTS` 拒絕） |
| System terminal／Tunnel | 開啟、姿態、關閉 |
| RBAC | 三角色 × 既有 17 動作的矩陣（新增的三個在旗標關閉時仍在詞彙裡，但端點 404） |
| DB | 既有表逐欄比對 |

**另一組**：`PROJECTS_ENABLED=true`。本期沒有第二個旗標
（`CLIORA_AGENT_RUNS_ENABLED` 是 V2.2 才有），所以是兩組不是四組。

## 4. 四個 gate

沿用 `scripts/pj/gate-*.sh` 的形狀，新增在 `scripts/tk/`：

| Gate | 斷言 |
|---|---|
| `GATE-TK-SCHEMA-ADDITIVE` | `pg_dump --schema-only` 與基線 diff 只有本期宣告的九張表、三個新增欄與其索引；**既有表逐欄無變化** |
| `GATE-TK-MIGRATION-ROUNDTRIP` | `upgrade head` → `downgrade 0022` → 與基線逐位元組相同 |
| `GATE-TK-CONTRACT-ADDITIVE` | `contracts/v1/fixtures/**` 的既有檔案 sha256 與 `TK-00` 基線相同；只允許新增檔案 |
| `GATE-TK-TOUCH-LIST` | `git diff --name-only` 對照白名單（**本期與 `PJ` 不同：daemon 與 contract 會動**） |

`GATE-TK-TOUCH-LIST` 的白名單（daemon 側）：

```text
允許：daemon/internal/files/{store_policy,project_store,project_store_test}.go
      daemon/internal/files/{policy,search,files_test}.go（token 不可預覽／搜尋）
      daemon/internal/session/{manager,manager_test}.go（只提供 live workspace 給清理迴圈）
      daemon/internal/config/**                 （保留期設定）
      daemon/internal/connection/*        （新 handler）
      daemon/internal/protocol/codec.go   （LargeFrameTypes 加一列）
      daemon/internal/install/plan.go     （symlink）
      daemon/cmd/agentd/*                 （argv[0] 分派 ＋ CLI）
      daemon/internal/cli/**              （新目錄）
      daemon/VERSION
禁止：daemon/internal/{terminal,tmux,session,tunnel,update}/**
      daemon/internal/files/{store,upload,read,list}.go 的既有函式
```

**「禁止」那半是本期真正的護欄**：它斷言我們沒有為了投影去動終端、tmux、tunnel 或既有的
檔案路徑。`policy`／`search` 與 session manager 是安全審查後具名加入的最小例外：前者確保
任何 `.cliora/**/*.token` 都不能被預覽或搜尋，後者只把 live workspace 提供給投影清理器，
不改 Session 的啟停／恢復語意。前四期用的是「daemon 零 diff」，本期不能用那個，所以要換一個一樣硬的。

## 5. 出口條件（11 條）

前十條是 `00-…md` §1 的判準，逐條要有可貼上的證據；第 11 條是治理。

1. Epic → US → 3 張 Task 建立、拖曳推進、Roadmap 完成度正確、**兩個未分類桶各有一張卡**。
2. 前置卡未完成的卡拖到 `implementing` → 409 且**指名 `card_ref`**。
3. 兩分頁同時拖同一張卡 → 後者 409、彈回、重新載入。
4. 從 Task Detail 開 Session → `.cliora/context/<sid>.md` 與 `.token` 出現、
   情境包 **≤ 4 KB** 且含逐項 AC、`.cliora/process/<version>/` 出現。
5. `cliora task update TASK-3 --stage implementing` → 看板即時更新 →
   時間軸一筆 `actor_kind = agent`、**沒有任何人類名字**。
6. Agent token 對 `POST /gates/architecture` → **401**；audit 有一筆對應紀錄。
7. **Central 停機**：Session 中的 CLI Agent 照常工作；`context show` 可讀；
   `task update` 非零 exit code ＋ 那兩句訊息。
8. 同一 workspace 開第二個 Session → 流程檔目錄被 skip（不是錯誤）、情境包是新檔案。
9. 在 **Traqora** 上做完 1–8 → `git status --porcelain` **完全為空**。
   （比上游規劃的「只看到 `.cliora/`」更強：`.cliora/.gitignore` 的 `*` 讓整個子樹被忽略。
   若該 repo 已有自己的 `.cliora/.gitignore`，平台**不覆寫**，此時條件放寬為
   「只看到 `.cliora/`」並在證據裡註明原因。）
10. 旗標關閉：完整回歸全綠；**contract 既有 fixtures 零變更**；
    `agentd` 0.8.0 在旗標關閉時行為與 0.7.0 相同。
11. **`docs/security-review-v21.md` 已完成並被讀過**（三節、每節的邊界測試已跑）。

**未達成任何一條，本期不得標為可發布。**
若波次 3（節點半）整批延後，條件 4–9 未達成——那是一個**明確的部分交付**，
要在 `09-…md` 寫成「已交付平台半，節點半延後」，不是把條件改寫成做得到的樣子。

## 6. 安全審查

**本期觸發**（`research/02/10` §6 的四條裡命中兩條）：

| 觸發條件 | 本期是否命中 |
|---|---|
| 新增或改變授權輸入 | ✅ Session token 是一種新的呼叫者身分 |
| 新增寫入路徑或新的儲存面 | ✅ `.cliora/` 的投影 verb ＋ `session_tokens` 表 |
| 新增在 node 上執行程序的能力 | ❌ 沒有。CLI 是使用者在自己的 Session 裡執行的 |
| 新增憑證或機密流 | ✅ 同第一條 |

文件：`docs/security-review-v21.md`，三節，大綱見 `04-…md` §6。
**在 `TK-07` 開工前要有初稿**（`00-…md` 閘門三）。

## 7. 證據

> **2026-08-09：本節的五個 gate（含 migration round-trip）與 `evidence.sh` 都已存在並跑過**——
> `scripts/tk/{gate-touch-list,gate-contract-additive,gate-flag-off,evidence}.sh`，
> schema gate 沿用 `scripts/pj/gate-schema-additive.sh`（重用，不複製）。
> 最後一次結果：**11 passed / 0 failed**。瀏覽器證據亦實跑：旗標關閉
> 21 passed／8 expected skip 且三角色導覽逐像素一致；旗標開啟 29 passed；
> V2.1 Task 專屬 live-stack（含第二次投影與 git status）4 passed，M1 live HTTP
> 200 卡／50 samples 另 1 passed。
>
> 一處與本節原文不同：`GATE-TK-CONTRACT-ADDITIVE` 的範圍是
> **`contracts/v1/fixtures/`**，不是整個 `contracts/`，而 `manifest.json` 具名豁免。
> 理由在 `scripts/tk/contract_snapshot.py` 的檔頭：新增一個訊息型別必然要改 envelope 的
> type enum，凍結全樹等於禁止這個階段；fixture 才是「對已部署 daemon 的承諾」，
> 而 manifest 是索引不是承諾。豁免會列印出來，不靜默（`09-…md` §3 第 6 條）。


`scripts/tk/evidence.sh`（沿用 `scripts/pj/evidence.sh` 的形狀）：
四個 gate、`make check`、`make test-db`、`make integration`、`make contract`、
`make traceability`、M1 的重跑、CLI 的離線測試。

`scripts/tk/browser-evidence.sh`（沿用 `browser-evidence.sh`）：
在旗標關／開各跑一次完整 live-stack Chromium 套組，
含判準 1–3、5 的瀏覽器路徑與旗標關閉的截圖比對。

CI：`.github/workflows/v2-projects.yml` 加本期的 job，維持雙旗標 matrix。

輸出落在 `artifacts/tk/local/`（基線在 `artifacts/tk/local/baseline/`）。

## 8. 合併回 `dev`

**一律由人工確認**（`research/02/10` §7）。

1. 階段工作以正常 PR 進 `v2`。
2. §5 的 11 條與 §3 的回歸套組全部通過 → **在 PR 或 issue 上提出合併請求**，附上證據。
3. 由人審閱後決定合併時機。**沒有自動合併、沒有排程合併、沒有「條件綠了就 merge」的 CI job。**
4. 合併後在 `09-…md` 記錄合併的 commit 與日期。

**`TK-11` 的最後一步是停下來。** CI 與 agent 不得發起或完成這個合併，
即使所有出口條件都是綠的——條件全綠只是取得提案資格，不是核准。

本期另有一件 V2.0 沒有的事：**`agentd` 0.8.0 的發布也是人的決定**。
出口條件全綠不代表要立刻推給所有 node；`node_update` 是既有的分批機制，
本期不改它，也不自動觸發它。
