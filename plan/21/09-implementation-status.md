# 09 — 實作進度與證據

本檔隨實作更新；「證據」欄只填**實際跑過的指令與其輸出位置**，不填計畫中的測試。
沿用 `plan/17/09`／`plan/18/09`／`plan/19/09`／`plan/20/08` 的體例：
**這裡記的是實際發生的事**，與計畫不同時，**以這裡為準並回寫計畫**。

**狀態：十二張 ticket 全部完成（2026-08-14）。**

```
make check                                   綠（format／lint／typecheck／tokens／unit
                                             ／contract／build／traceability／railway）
backend  unit                                1648 passed
frontend unit                                649 passed（41 檔）
contract（Python／Go／TypeScript）             213 / ok / 192 passed
daemon   go test ./...                       17 個套件全綠（含 -race）
scripts/dv/gates.sh                          13/13
alembic upgrade → downgrade 0034 → schema    與 DV-00 基線逐位元組相同
M6                                           最差 p95 279.9 ms，未觸發設計改動
```

**剩下的都是人的事**（§4）：ADR 0033 仍是 `proposed`（閘門二是人的核准）、
traceability 仍是 `proposed`、Traqora 的第一個真實 PR、以及供應商憑證的保管。

```
make check                                   綠（format／lint／typecheck／tokens／unit
                                             ／contract／build／traceability／railway）
backend  unit                                1635 passed
frontend unit                                641 passed（40 檔）
contract（Python／Go／TypeScript）             213 / ok / 192 passed
contract additive                            既有 172 個 fixture 逐位元組未變，新增 12
daemon   go test ./...                       17 個套件全綠（含 -race）
alembic upgrade → downgrade 0034 → schema    與 DV-00 基線逐位元組相同
schema 只新增                                 40 張表，基線的每一行都還在
M6                                           最差 p95 279.9 ms，未觸發設計改動
```

**波次順序有一處被 repo 的守門測試改寫**（§3 第 7 條）：
`0037` 的兩個 RBAC 動作、`rbac.py` 的宣告、以及**至少一個執行它的端點**
必須同時落地，所以 `DV-07`／`DV-08` 提前到波次一之後、`DV-03` 之前完成。

## 0. 待確認項目

**這一節是開工前唯一要讀的東西。** 完整內容與「不同意的話會怎樣」在
[`00-execution-plan.md`](./00-execution-plan.md) §0。

### 0.1 A 類 — **已於 2026-08-14 裁決結清（0 項）**

| ☑ | 項目 | 裁決 |
|---|---|---|
| ☑ | **D4** | **兩個來源都要。** `origin` 成為第二軸；卡片宣告需要 **`task.approve`**（`RUN_TOKEN_SCOPES` 永遠不含它，`agent_auth.py:70`），所以人可以宣告、Agent 不行，`machine_verified` 因此保住。連帶新增 `tasks.verification_commands`、`projects.require_project_verification`（預設關閉）、`origin` 徽章與出口條件 15b／19c／24b |
| ☑ | **D7** | **選項 A：縮範圍。** `existing_pr` 的 base 必須在 `cliora/` 內，dispatch 當下拒絕；`push.go` 的五條硬約束一個字不改 |

### 0.2 B 類 — 確認即可（4 項）

| ☐ | 項目 | 一句話 |
|---|---|---|
| ☐ | **D1／D2** | PR 由 Central 開；`pull_request` 在 wire 上表現為 `branch`。不這麼做的話 `provider_token` 要下放到沙箱，而且舊 node 會靜默丟掉 offer |
| ☐ | **D6** | 驗證命令沿用既有的 `spec.allowed_verification_commands`（tab 分隔）。新增 `spec` 欄位會讓每一台未升級的 node 丟掉每一個 offer |
| ☐ | **D9** | AC 的 `result` 本期封閉成四值，**會改寫既有資料**（migration 會印出改了幾列） |
| ☐ | **D10** | `--force` 是新的 Admin 動作 `task.force_done`，CLI 沒有對應子命令 |

### 0.3 C 類 — 開工時決定，計畫已給預設值（5 項）

見 `00-…md` §0.3。其中：

- **provider 先做哪一家** ☑ 已裁決（2026-08-14）：**GitHub**。
- **evidence 的採集逾時** ☑ **10 秒**（M6 已量，§1.2）。
- 🆕 **`require_project_verification`** 預設關閉（D4 的收斂點，`06-…md` §2.1 第 4b 項）。

## 1. Ticket 狀態

| Ticket | 標題 | 狀態 | 證據 |
|---|---|---|---|
| `DV-00` | 基線擷取 ＋ **M6** | ✅ | 六份基線在 `artifacts/dv/local/baseline/`（§1.1）；M6 在 `artifacts/dv/local/m6-git-evidence.json`（§1.2）。`scripts/dv/capture-baseline.sh` 是三行 wrapper、`scripts/dv/measure_git_evidence.py` 是新的 |
| `DV-01` | ADR 0033 ＋ 三則增補 ＋ PRD §8.15 ＋ traceability ＋ **回溯條目** | ✅ | `docs/adr/0033-…md`（**proposed**，等閘門二）；ADR 0029 增補 C／0031 增補 B／0032 增補 A；PRD §8.15 十一條 FR ＋ **58 個 AC**；`traceability/requirements.json` 十一筆 `proposed`，`trace validate --level static` ＋ `render --check` 綠；skill 的交付段落改寫。**過期承諾清單延到 `DV-11`**（§3 第 8 條） |
| `DV-02` | migration `0035`／`0036`／`0037` ＋ 模型 ＋ **AC 四值收緊** ＋ **兩個驗證命令來源** | ✅ | **40 張表**；`downgrade` 回 `0034` 與基線**逐位元組相同**；AC 收緊實測改寫 **4 項／2 張卡**並印出筆數；seed 重跑無變化；Admin **27** 個動作，Developer 18、Viewer 5 不變 |
| `DV-03` | contract **v1.13.0** ＋ fixtures（**`spec` 零新增**） | ✅ | 三處新增**全部是 node→central**：`run.complete` 的 `pushed_branch`／`verification`、`run.progress` 的 `verifying`、`runner.register` 的 `features`。**三種語言各自實作**（Python schema、Go `codec.go`、TS `decode.ts`）；12 個新 fixture（6 valid ＋ 6 invalid），含「`spec` 帶 `verification`」「`delivery: pull_request`」「`result: delivered_branch_only`」三條**證明它們不可表示**的 invalid 案例；CHANGELOG 1.13.0 |
| `DV-04` | `agentd` **0.11.0**：交付、驗證、證據三塊 | ✅ | `DeclaresNoCode` 一個述詞兩個呼叫端；`runner/verification.go`（不經 shell、每條 300s／整組 900s、逾時 `-1`、剩餘時鐘不足時**出聲跳過**）；`Fetcher.DiffStat` ＋ `Inspect` 套 **M6 的 10 秒**；`features` 上報 ＋ `doctor` 三行；`verification_test.go` **13 條**；`daemon/VERSION` cut **0.11.0** |
| `DV-05` | PR 建立 ＋ provider adapter ＋ egress（**安審 §1**） | ✅ | `services/providers.py`（三個動作、封閉動作表、host allowlist、**不重試**、token 不進錯誤與 log）＋ `services/deliveries.py`（四種結果、`branch_only` 不算 run 失敗）；worker 掛在 reaper 的第四個 job，**`finish()` 只寫意圖**；`test_pull_request_delivery.py` **12 條**，含逾時只送一個請求、token 遮罩、`GATE-DV-NO-HTTP-IN-LOOP` 的靜態形式 |
| `DV-06` | 三張表的 service／API ＋ CLI 三個子命令（**安審 §2**） | ✅ | `services/evidence.py`（三個 service、`_SOURCE_FOR_KIND` 綁死 kind→source）；八條路由**只有 GET／POST**；`finish()` 寫 `machine_verified` ＋ evidence ＋ **`artifact` 缺產物改判不成功**；CLI `plan snapshot`／`verify report`／`evidence add`（**全部只寫不讀**）；`test_evidence.py` **12 條**。⚠️ **卡片驗證命令端點延到 `DV-09`**（§3 第 10 條） |
| `DV-07` | Done Gate ＋ `--force`（**安審 §3**） | ✅ | `services/done_gate.py` 六項＋五分支；`test_done_gate.py` **23 條**（含五種 delivery 的參數化十例）；`--force` 三件事（403／必填理由／永久可見）；**run 不推進卡片**的斷言 |
| `DV-08` | 流程覆寫 ＋ `process.manage` | ✅ | `PUT /api/projects/{id}/process/overrides`；未知 key 被拒並指名；停用原因分得出 `disabled_by_project` 與整合未啟用；**覆寫碰不到 Done Gate** 的斷言 |
| `DV-09` | 六個指標 ＋ 卡片／專案的驗證命令端點 | ✅ | `dashboard.py` 的 `delivery` block（六個數字，掛在既有的 per-block 降級契約上）；`PUT /projects/{id}/verification-commands`（`project.manage`）與 `PUT /tasks/{id}/verification-commands`（**`task.approve`**）；`assemble_verification_commands` 兩個來源合併、**project 排前面**；migration `0038` 的 `agent_runners.features` |
| `DV-10` | 前端：完成面板與來源徽章 | ✅ | `SourceBadge` 加 `origin`（**兩個 origin 同一個實心樣式**、`未經平台驗證` 是文字不是 tooltip）；`TaskCompletion.vue`（Done Gate 平時就顯示、失敗項排前面、矛盾兩列並存不仲裁、force 徽章常駐）；`TaskCompletion.test.ts` **8 條**畫面斷言 |
| `DV-11` | 驗證、gate、安審定稿、release note | ✅ | `scripts/dv/gates.sh` **13/13**；`docs/security-review-v24.md` **三節**；`docs/release-note-delivery-and-verification.md`；`deploy/railway/env.md` 四個新變數；**過期承諾清單六處全掃**（`GATE-DV-NO-STALE-PROMISE` 綠） |
| — | **合併提案** | ⬜ **待人工** | 條件全綠只是取得提案資格，不是核准 |

### 1.1 `DV-00` 的基線

（開工後填。預期六份，在 `artifacts/dv/local/baseline/`。
擷取器是 `scripts/ar/capture-baseline.sh` 的 `BASELINE_OUT` 覆寫，
與 `plan/20/08` §3 第 2 條的處置一致。）

| 檔案 | 預期 | 實際 |
|---|---|---|
| `COMMIT` | commit ＋ 未提交路徑（應只有 `plan/21/`、`scripts/dv/`） | ✅ `32b9248`（2026-08-14T01:01:51Z）。未提交的是 `plan/21/`、`scripts/dv/` 與三份已回寫的文件（`plan/20/08`、`research/02/06`、`research/02/README`）——**全部是文件與擷取器本身**，與 V2.2／V2.3 的先例一致 |
| `openapi-flags-off.json` / `-on.json` | 兩份逐位元組相同 | ✅ 362 322 bytes，`cmp` 綠 |
| `schema.txt` | **37 張表**、`0034_seed_secret_action` | ✅ 兩者都對 |
| `contract-fixtures.txt` | **172 行**（171 個檔 ＋ `manifest.json`） | ✅ 172 |
| `frontend-routes.txt` | 19 條 | ✅ 19 |
| `terminal-latency.json` | 三次量測取 p50 中位數 | ✅ p50 **0.205 ms**、p95 0.714 ms（三次的中位數）。三次的原始檔一併留著（`terminal-latency-run{1,2,3}.json`） |

**三次量測本身就是一個結果，而它證實了 `plan/20/08` §3 第 3 條的修訂是對的：**

| | run1 | run2 | run3 | 中位數 |
|---|---|---|---|---|
| p50 | 0.190 | 0.205 | 0.372 | **0.205** |
| p95 | 1.177 | 0.270 | 0.714 | **0.714** |

同一台機器、同一個 idle stack、同一輪之內：**p95 的三個值相差 4.4 倍，而 p50 只差 1.96 倍。**
V2.3 是拿兩次相隔數週的量測發現這件事的（相差 27%）；這一次是在**同一輪內**看到更大的離散。
結論不變而且更強：**單次 50 samples 的 p95 不能當「之前」**，
任何拿它比 20% 的判準都落在雜訊底下（M-SC-2 的做法照此，`10-…md` §3.1）。

### 1.2 `DV-00` 的量測

| 量測 | 狀態 | 結論 | 原始資料 |
|---|---|---|---|
| **M6** 三個 git 命令的耗時 | ✅ **已量（2026-08-14）** | **最差 p95 ＝ 279.9 ms**（31 300 檔的髒 repo 上的 `git diff`），是設計改動門檻 5 000 ms 的 **1/18**。所以：**採集維持「必須完成」，逾時 10 秒（下限）**，`00-…md` §0.3 的預設值成立而不是被沿用 | `artifacts/dv/local/m6-git-evidence.json`；逐格見 `10-…md` §1.1 |

## 2. 出口條件

30 條，逐條見 [`08-verification-and-exit.md`](./08-verification-and-exit.md) §5。

| # | 條件 | 狀態 | 證據 |
|---|---|---|---|
| 1 | 五種 delivery 各跑通一次 | ⬜ | |
| 2 | `none`／`artifact` 遠端零副作用 | ⬜ | |
| 3 | **Traqora 上的第一個真實 PR** | ⬜ 人工 | |
| 4 | 有變更時明示 ＋ diff 附為產物（**兩種 delivery**） | ⬜ | |
| 5 | `artifact` 缺產物 → run 不算成功 | ⬜ | |
| 6 | `pull_request` 無變更 → provider 呼叫次數 0 | ⬜ | |
| 7 | `existing_pr` 出命名空間 → dispatch 當下拒絕 | ⬜ | |
| 8 | PR 建立四種失敗的處置 | ⬜ | |
| 9 | 逾時只送一個請求 | ⬜ | |
| 10 | token 不在任何 log 記錄 | ⬜ | |
| 11 | `pending_pr` 佇列上限可見 | ⬜ | |
| 12 | `finish()` 無 HTTP | ⬜ | |
| 13 | 自動合併路徑不存在（兩個 gate） | ⬜ | |
| 14 | 任意命令 API 不存在 | ⬜ | |
| 15 | 驗證失敗 → 報告 `failed`，exit code 是真的 | ⬜ | |
| 15b | 兩個來源各一條，`origin` 分得出來且 project 排前面 | ⬜ | |
| 16 | 驗證逾時 → `-1`，其他條照跑 | ⬜ | |
| 17 | wall clock 不足 → 跳過並說明 | ⬜ | |
| 18 | 驗證輸出的機密被遮罩 | ⬜ | |
| 19 | 偽稱 `machine_verified` → 存為自述 ＋ activity | ⬜ | |
| 19b | 畫面上三級樣式不同（**畫面斷言**） | ⬜ | |
| 19c | run 憑證改卡片驗證命令 → 403；畫面唯讀不隱藏 | ⬜ | |
| 20 | Done Gate 逐項指名 | ⬜ | |
| 21 | `none`／`artifact` 進得了 done；`artifact` 缺產物被擋 | ⬜ | |
| 21b | `no_changes` 與 `delivered_branch_only` 都進得了 done | ⬜ | |
| 22 | `--force` 的三件事（通過／永久可見／403） | ⬜ | |
| 23 | run 完成不移動卡片 | ⬜ | |
| 24 | 流程覆寫生效且碰不到 Done Gate | ⬜ | |
| 24b | `require_project_verification` 開啟時擋、關閉時不影響 | ⬜ | |
| 25 | 六個指標 ＋ 單格降級 | ⬜ | |
| 26 | 旗標關閉回歸全綠 | ⬜ | |
| 26b | 0.10.0 的 node 仍能完成三種卡 | ⬜ | |
| 26c | 0.8.0 的 node 拿不到交付型卡且說得出為什麼 | ⬜ | |

## 3. 實作中發現、與計畫不同的事

沿用 `plan/18/09` §3 的形式：計畫寫的／實際做的／為什麼。

1. 🔴 **`alembic_version.version_num` 是 `varchar(32)`，而計畫的 revision id 有 36 個字元。**
   `0036_delivery_columns_and_ac_results` 的 DDL **跑完了**，然後在寫入版本號那一句
   `StringDataRightTruncationError`——所以資料庫拿到了新結構卻沒有記下自己在哪一版。
   改名為 `0036_delivery_and_ac_results`（28）。
   ⚠️ **值得記的是失敗的形狀而不是長度限制**：一個太長的 revision id 不會在寫的時候被擋，
   會在**遷移的最後一步**被擋，而那時候結構已經改了。開工前掃一次所有 id 長度比較便宜。

2. 🔴 **Done Gate 必須綁 `CLIORA_AGENT_RUNS_ENABLED`，而計畫只說第 6 項要跳過。**
   `08-…md` §6 寫的是「Done Gate 的第 6 項在這個組態下要跳過」。**那太窄了**：
   第 ①③④ 項要的是驗證報告，而只開看板的部署**永遠不會有任何一份**——
   於是每一張卡都進不了 `done`，那是把 V2.1 弄壞給沒要 V2.2 的人。
   正解是整個 gate 綁旗標（PRD §8.15 本來就寫「本節的能力受該旗標控制」）。
   **是一條既有的 V2.1 測試抓到的**（`test_finishing_the_blockers_unblocks_the_card`）。

3. 🔴 **第 6 項還要對「從未派工的卡片」跳過，而這一條計畫完全沒有。**
   `tasks.delivery` 的資料庫預設是 **`pull_request`**（`0023_task_board.py:347`）。
   所以在一個有在用 runner 的部署裡，一張**手動管理、從來沒派給 Agent** 的卡片
   也會被要求「PR 連結」——而它永遠不會有。
   正解：`delivery` 描述的是**一次 run 怎麼把成果交回來**，沒有 run 就沒有交付可以驗；
   其餘五項照常適用。同樣是既有測試抓到的。

4. 🔴 **`TaskService` 必須從呼叫端收 `settings`，不能自己 `get_settings()`。**
   這是 `plan/20/08` §3 第 5 條那個陷阱的第二次出現：
   `projects_enabled` fixture 用 `app.dependency_overrides[get_settings]` 打開旗標，
   而一個直接呼叫 `get_settings()` 的 service **收不到覆寫**——
   於是 Done Gate 在每一條「旗標開著」的測試裡**靜默失效**，而測試全綠。
   V2.3 對 `secret_envelope` 的解法是設環境變數（那支模組在請求之外也會被呼叫）；
   這裡更簡單，因為它永遠在請求裡：**當成參數傳進來**。
   ⚠️ 修好之後才有第 2、3 條那兩個發現——**在修好之前，gate 根本沒有在跑**。

5. 🔴 **`has_action` 不能出現在路由裡**（`test_authorization_logic_is_confined_to_two_modules`）。
   `--force` 需要的是「這個人有沒有這個動作」而**不是拒絕**，而 `require_action` 只會拒絕。
   新增 `deps.py` 的 `may_perform(action)`——回傳 bool 的依賴。
   把它放在 `deps.py` 而不是路由裡，正是那條測試存在的理由。

6. 🔴 **「run 永不移動卡片」寫成那樣是錯的。**
   `runs.py:879` 早就有 `task.stage = "blocked"`（V2.2 的用盡重試路徑），而那是合理的：
   它是**一份報告**（做不下去了），不是一個完成的主張。
   斷言因此收成**「run 永不把卡片推進 `done`」**，並額外斷言它指派的其他值只有 `blocked`。
   ⚠️ 一個寫得太嚴的守衛看起來更安全，但它會在第一個人讀到它的時候被放寬——
   **而放寬的方式通常是刪掉它**。`GATE-DV-SINGLE-DONE-PATH` 要照這個範圍寫。

7. 🔴 **seed migration、`rbac.py` 的宣告、以及一個執行該動作的端點，必須同時落地。**
   兩條既有測試從相反方向夾住：`test_role_actions_match_the_seeded_database`
   要求 `ROLE_ACTIONS` 與種子一致，`test_every_action_is_enforced_somewhere`
   要求每個宣告的動作至少有一個端點在用。
   所以計畫把 `0037` 放波次一、把端點放波次三**做不到**——`DV-07`／`DV-08` 因此提前。
   **這不是計畫的錯，是這個 repo 的守門測試比計畫的分期更細**，值得記下來給下一期。

8. **過期承諾清單（`01-…md` §7）延到 `DV-11`。**
   清單上六處裡有四處（`runs.py:94`、`process.py:15`、`run-spec` 的 `$comment`、
   `supervisor.go` 的 `ShouldAttachDiff` 註解）**正好是後面幾張 ticket 要改寫的程式碼**，
   現在改一次、實作時再改一次，是製造 churn 而不是清理。
   `GATE-DV-NO-STALE-PROMISE` 在 `DV-11` 驗收，掃不到就是漏了。

10. 🔴 **Redactor 走不進型別化的 slice，而驗證輸出正好是一個。**
    `Redactor.value()` 遞迴處理 `map[string]any` 與 `[]any`，其餘一律原樣回傳。
    `RunChecks` 回的是 `[]CheckResult`——**放進 payload 就直接繞過了去識別**，
    而一條驗證命令的輸出（`env`、失敗的設定 dump、curl trace）正是機密最可能出現的地方。
    V2.3 「包住 `send` 而不是包住 log sink」買到的是「新欄位自動被涵蓋」，
    **而那個保證只對 redactor 認得的形狀成立**。
    處置：`CheckPayload()` 轉成通用形狀再放進 frame，並加一條測試釘住它
    （`TestACheckOutputPassesThroughTheRedactor`）。**第一版沒過那條測試。**

14. 🔴 **Redactor 走不進型別化的 slice**（見第 10 條），而**同一種形狀的錯誤在 gate 上又出現一次**：
    `GATE-DV-NO-HTTP-IN-LOOP` 抓到 `runs.py` 匯入了 `adapter_for`。
    那個函式只是註冊表查詢、不打任何 HTTP，但**它回傳的是一個可以被呼叫的 adapter**——
    守衛的字面過了、用意沒過。處置是讓 dispatch 改用純述詞 `supports_host()`：
    **問「支不支援」而不是「給我一個 client」**，而那也是比較好的設計。

15. 🔴 **計畫寫了 dispatch 的三個新檢查，而我只清空了 `UNSUPPORTED_DELIVERIES`。**
    是兩條 V2.3 的既有測試抓到的（它們斷言 `pull_request` 會被拒）。
    補上時發現**還缺第四個**：`delivery: pull_request` ＋ `source: none` 是一個
    自相矛盾的組合（要交付程式碼變更，卻宣告不取得程式碼），
    而計畫的三個檢查都攔不到它。新增 `TASK_DELIVERY_NEEDS_SOURCE`。

16. **四個 gate 在寫的時候就抓到自己太寬。**
    `GATE-DV-NO-SHELL` 命中測試檔（測試用 `sh -c` 建情境是**測試在驗這個功能**，
    不是 daemon 在用 shell）；`GATE-DV-DELIVERY-COVERAGE` 指錯前端的第四處
    （值住在 `labels.ts` 而不是 badge 元件）。兩者收窄而不是關掉。
    ⚠️ 值得記的是**它們在收窄之前先抓到了兩件真的事**：一句過期的錯誤訊息
    （「takes effect in a later version」），以及上面第 14 條。

17. 🔴 **`staticGuards` 抓到我把一個呈現決定寫在 `SourceBadge` 之外。**
    `TaskCompletion.vue` 寫了 `source === 'machine_verified'` 來決定要不要用等寬粗體。
    那條守衛要求三個 wire 值只出現在 `labels.ts` 與 `SourceBadge.vue`——
    處置是**把述詞搬過去**（`isMachineVerified()`）而不是把檔案加進白名單。
    `api/dto.ts` 確實加進了白名單，理由不同：那是**線上契約的型別**，不是呈現規則。

12. 🔴 **SCOPE-013 禁止 Central 匯入任何 HTTP client，而本期必須有一個。**
    那條守衛的用意是「Central 不得成為通往 node 的反向代理」（ADR 0022），
    而它的實作方式是「整個 `app/` 不得出現 `httpx`」——在 V2.4 之前那是一個好的代理指標，
    現在不再是同一句話：開 PR 是打給**供應商的公開 API**，不是打給 node，也不是代理。
    **處置是收窄而不是刪除，而且收窄之後更嚴**：HTTP client 只能出現在
    `services/providers.py` 一支模組，且該模組必須查部署層的 host allowlist、
    不得把 repository 的欄位插進 URL（兩條新斷言）。
    ⚠️ **這是本期唯一一次放寬既有 scope guard**，所以它進安審 §1。

13. 🔴 **測試的清理順序漏了 `project_repositories`，而註解已經寫對了。**
    `_CLEANUP_TABLES` 的註解說 `project_secrets` 要在「持有 RESTRICT 外鍵的 repository 列」之後清，
    **但那張表根本不在清單裡**。V2.3 之後沒有任何測試把 repository 連到 secret，
    所以那個約束從未被觸發；本期第一個這麼做的測試（PR worker 需要
    `provider_token_secret_id`）**不是在自己的斷言上失敗，是在清理階段失敗**。
    已補 `task_runs` 與 `project_repositories` 兩列。

11. **卡片級驗證命令的端點延到 `DV-09`。**
    D4 的資料層（`tasks.verification_commands`）與授權邊界（`task.approve`）已就位，
    Central 端組 offer 的合併邏輯也還沒接（`DV-05` 之後才有 offer 組裝的改動）。
    **兩者一起做比分兩次做少一次改寫**，而 `origin` 的端到端驗收本來就要等 offer 組裝。

9. **`test_every_kind_has_a_write_site` 與 `test_every_audit_action_has_a_write_site`
   逼出一條紀律**：不要提前宣告還沒有寫入點的 activity kind／audit action。
   本輪一度宣告了 `pr.create`／`verification.source_ignored` 等四個，
   隨即拿掉——它們與 `DV-05`／`DV-06` 一起回來。

**開工前已知、計畫已據以修正的九處**（它們不是「實作中發現」，

**開工前已知、計畫已據以修正的九處**（它們不是「實作中發現」，
但列在這裡讓下一個人知道計畫與上游規劃為什麼不同——完整表在 `README.md`）：

1. `codec.go:961` 的 `runDeliverySet` 只有三值（D2）。
2. `codec.go:437` 的 `strictUnmarshal` 是 `DisallowUnknownFields` 且遞迴到 `spec`（D3／D6）。
3. `push.go:54` 的第一條硬約束讓 `existing_pr` 不成立（D7）。
4. 產物走 HTTP，daemon 數不到（D8）。
5. `supervisor.go:316` 的 `SummaryText` 對 `artifact` 少一句話。
6. `runs.py:1075` 的 `run_branch()` 只認得 `branch`。
7. `tasks.py:603` 的 AC `result` 是自由字串（D9）。
8. `run-spec.schema.json` 的 `allowed_verification_commands` 已存在且 daemon 不執行它（D6）。
9. `finish()` 在接收迴圈上（D17）。

## 3b. 合併到 staging 之後才發現的一件事

18. 🔴 **`httpx` 在 dev group，而生產映像用 `--no-dev` 安裝。**
    容器跑完了四支 migration、啟動 uvicorn、然後死在
    `ModuleNotFoundError: No module named 'httpx'`。

    **本機每一道檢查都是綠的，而且必然是綠的**：開發環境裝了 dev group，
    所以 unit、mypy、ruff、build 全部看不到這件事。它第一次出現的地方是生產環境，
    而且是在 migration 已經跑完之後——那是整條時間軸上最糟的位置。

    ⚠️ **`test_scope_guards.py` 的註解早就寫著答案**：
    「(`httpx` is a test dependency; the app does not import it.)」
    我在收窄 SCOPE-013 時讀了那條守衛、改了那條守衛，**卻沒讀那句括號**。
    收窄本身是對的（`04-…md` §4 的七條斷言都成立），漏掉的是它預設的前提。

    處置有兩層。`httpx` 移進 `[project] dependencies`——這是修 bug。
    然後補 `test_runtime_imports_are_declared_runtime_dependencies`：掃 `app/`
    的**模組層** import，逐一比對 runtime 依賴清單。那才是修這一類問題，
    而它上線的第一件事就是抓到第二個：`api/middleware.py` 直接 import `starlette`
    卻靠 FastAPI 的傳遞依賴帶進來——**你 import 的東西就是你依賴的東西**，
    靠別人的傳遞依賴等於讓別人的下一次發版決定你的程序啟不啟動。

    驗收方式是重現生產的安裝：`uv sync --locked --no-dev` 到一個乾淨的環境，
    然後 import `app.main`。這件事本來就該在 `DV-11` 做一次。

## 4. 尚待人工完成的事

1. **合併提案。** `v2` → `dev` 一律由人決定。
2. **Traqora 上的第一個真實 PR**（出口條件 3），以及 `existing_pr` 接在它上面的第二次 run。
   ⚠️ **本期是第一次需要 Traqora 的 PR 建立權限**——前五期最多只到 push。
   開出來的 PR 由人審閱後處置，**平台永不合併**。
3. **`agentd` 0.11.0 的發布時機。** 出口全綠不代表要推給所有 node。
4. **翻 traceability 的 `lifecycle`。** 與第 2 條同時做。
5. **前期遺留的三項量測**：M-SC-2（去識別成本，V2.3）、M-AR-2（log 速率）、
   M-AR-9 的尾巴。不擋本期，但沒有 M-AR-9 的話 `RUN_IDLE_TIMEOUT` 的 300 秒
   仍是一個有根據的猜測。
6. **provider token 的產生與保管。** fine-grained PAT，**權限只要 pull request: write**，
   而且要記下它屬於誰——PR 的作者欄顯示的是它（`01-…md` §3.6 代價 1）。
   這一條要進 `docs/runbooks/`。

## 5. 環境事實

沿用 `plan/20/08` §5，本期新增兩列。

| 事實 | 值 |
|---|---|
| 工具鏈不在預設 PATH 上 | `export PATH="$HOME/.local/bin:/usr/local/go/bin:$HOME/.nvm/versions/node/v22.23.2/bin:$PATH"` |
| DB 測試要**兩個**環境變數 | `CLIORA_TEST_DATABASE_URL` ＋ `CLIORA_DATABASE_URL` |
| `claude` 與 `codex` 都裝了但不在預設 PATH 上 | `~/.local/bin/{claude,codex}` |
| `git` 是 runner 模式的前置條件 | `agentd doctor` 檢查它 |
| e2e stack 要一個乾淨的資料庫 | 見 `plan/18/09` §5 |
| `ssh-agent`／`ssh-add`、可寫的 scratch 遠端 | V2.3 起 |
| `CLIORA_SECRET_MASTER_KEY` | 旗標開啟的部署少了它會拒絕啟動（設計，不是故障） |
| `CLIORA_GIT_SECRET_DELIVERY_ENABLED` | 預設 `false`，本期不動它 |
| 🆕 **一枚有 PR 建立權限的 fine-grained PAT** | 出口條件 3。權限只要 `pull request: write`；**它的擁有者會顯示在 PR 上** |
| 🆕 **`cmd/fakeprovider`** | 出口條件 8／9 的四種失敗與請求計數。真實驗收不可用它取代 |
| 🆕 **`CLIORA_PROVIDER_API_HOSTS`** | 預設只有 `api.github.com`。**預設值必須是安全的**（D16） |
| 本期開始時的基線 | contract **v1.12.0**、`agentd` **0.10.0**、migration **0034**、RBAC **25**、ADR **0032**、**37 張表** |
| 本期結束時的基線（目標） | contract **v1.13.0**、`agentd` **0.11.0**、migration **0037**、RBAC **27**、ADR **0033**、**40 張表** |

## 6. 實作中發現的其餘事項

（開工後填。）
