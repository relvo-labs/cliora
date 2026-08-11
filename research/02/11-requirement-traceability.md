# 09 — 需求註冊與追蹤

## 1. 為什麼這份文件排在最後、卻是第一張 ticket

`.agent/skills/cliora-project-context/SKILL.md` 明文寫著：不得在沒有需求變更的情況下引入 **task routing** 與 **Git automation**。V2 兩者都碰（前者從 V2.1 起、後者在 V2.3）。

所以 V2.0 的第一張 ticket（`PJ-01`）就是需求變更本身——PRD 增訂、ADR、skill 範圍句修訂、requirements 註冊。沒有這一步，後面每一張 ticket 都在違反這個 repo 自己的規則，而 `make check` 內的 traceability gate 也會擋下來。

## 2. 新需求 ID（提案）

沿用既有命名慣例 `FR-<AREA>-<NNN>`，AC 為 `<REQ>.AC-<NN>`，註冊到 `traceability/requirements.json`（`schema_version` 與既有 115 筆一致，`owner` 用 `central` / `daemon` / `frontend`）。

### FR-PROJECT — 專案管理（V2.0）

| ID | 標題 | Owner | 關鍵 AC |
|---|---|---|---|
| FR-PROJECT-001 | Project CRUD 與狀態 | central | 建立／改名／狀態轉換；封存後不得建立新 Session |
| FR-PROJECT-002 | Project ↔ Workspace 綁定 | central | 跨 Node 綁定；綁定時前綴驗證；**每次使用重驗證**；解綁不影響進行中的 Session |
| FR-PROJECT-003 | Project ↔ Session 關聯 | central | `project_id` 可為空；指定時 workspace 必須屬於該 Project |
| FR-PROJECT-004 | Activity Timeline | central | Session 起訖、綁定變更、任務狀態轉換各產生事件；分頁查詢；也是任務資料的歷史來源 |

### FR-TASK — 任務（V2.1）

| ID | 標題 | Owner | 關鍵 AC |
|---|---|---|---|
| FR-TASK-001 | 內化的流程定義 | central | 六車道、DoR 七項、Gates 六項為平台種子資料；出處標註 Monstrare（MIT） |
| FR-TASK-002 | Epic／User Story／Task CRUD | central | 三層實體；未指定 User Story 的卡落在未分類桶，不遺失 |
| FR-TASK-003 | 看板與藍圖 | frontend | 六車道可拖曳；完成度聚合正確；WIP 超標顯示不阻擋 |
| FR-TASK-004 | 進站與 Done Gate | central | `dependsOn` 未滿足時拒絕並**指名擋住的卡**；循環相依可偵測；DoR 在 V2.1 為警告 |
| FR-TASK-005 | Review Gate 的人工核准 | central | 勾選必帶人類 actor 與 audit；Agent 憑證 scope 寫死不含 `task.approve` |
| FR-TASK-006 | Task ↔ Session 綁定 | central | 從 Task 開 Session 為預填而非新流程；歷史 Session 可回溯 |
| FR-TASK-007 | `.cliora/` 投影與情境包 | central | ≤4 KB；寫入失敗不影響 Session 建立；流程檔以版本號目錄避開 `O_EXCL`；保留期 30 天 |
| FR-TASK-008 | Session Token | central | 單一 Project scope、Session 結束即失效、可撤銷、永不含核准類動作 |
| FR-TASK-009 | `cliora` CLI 最小集合 | central | `context show` 免連線；`task update` 連不上時失敗訊息符合 D14 |
| FR-TASK-010 | 併發控制 | central | `version` 樂觀鎖；409 時前端彈回並重新載入 |

### FR-PLAN / FR-VERIFY — 計畫與驗證（V2.2）

| ID | 標題 | Owner | 關鍵 AC |
|---|---|---|---|
| FR-PLAN-001 | 執行計畫 | central | `(task_id, seq)` 只 INSERT 不 UPDATE；顯示最新 ＋ 歷史；改計畫必須有 `note` |
| FR-VERIFY-001 | 驗證報告 | central | schema 驗證；不合格不寫入半筆；失敗項不可摺疊隱藏 |
| FR-VERIFY-002 | 證據可信度分級 | central | 三級 `source` **由伺服器端判定**，忽略 payload；每列記錄寫入者身分 |
| FR-VERIFY-003 | Done Gate | central | **強制拒絕**並指名缺項；Admin `--force` 需必填理由，理由永久可見 |
| FR-VERIFY-004 | 平台不可用時的行為 | central | **直接失敗不佇列**（D14）；訊息含「Session 可繼續工作」；`context show` 免連線；非零 exit code 但不中斷 Agent |

### FR-AGENT — Agent Runner（V2.2）

| ID | 標題 | Owner | 關鍵 AC |
|---|---|---|---|
| FR-AGENT-001 | Runner 註冊 | daemon | `agentd` 的一個模式；**重用既有 enrollment／憑證／WSS／heartbeat**，不新增信任建立 |
| ~~FR-AGENT-002~~ | ~~Project × Agent 多對多~~ → **移到 V2.3**（FR-RUNENV-006） | central | 2026-08-10 裁決：綁定授權的是機密，與機密同期交付。V2.2 的授權邊界是 **enrollment** |
| 🆕 FR-AGENT-011 | **隔離工作目錄** | daemon | `<state>/.cliora/runs/<run_id>/`，**不在 allowed root 內、與 allowed root 互不可達**；兩層配額；保留期清理；run root 落在 allowed root 內時**拒絕啟動** |
| 🆕 FR-AGENT-012 | **Agent 自行取得程式碼** | daemon | 依 `source` clone／checkout；bare mirror ＋ `git worktree`；host allowlist；known_hosts pinning；缺憑證**快速失敗**不掛住；**不移除 `origin`**——2026-08-10 第二次裁決撤回了那個作法，換上的是可觀測性（run 摘要記 `git remote -v` 與未推送 commit 數） |
| 🆕 FR-AGENT-013 | **變更不得靜默丟棄** | daemon | `delivery: none｜artifact` 但工作目錄有變更 → `git diff` **附成一件產物**（D21 誠實性規則 ＋ D29 §7，原屬 V2.4） |
| FR-AGENT-003 | 任務認領 | central | **拉取式**；原子認領，**雙重領取不可能**；**四**條件資格判定（綁定與 label 兩條已隨 2026-08-10 裁決移到 V2.3） |
| FR-AGENT-008 | 指定 Agent | central | 可指定可不指定（預設不指定）；資格衝突在 dispatch 當下回 409；離線與不符資格的文案不同；重排維持指定；**預設不逾時退回** |
| FR-AGENT-004 | 租約與重排 | central | 續租、逾時標 `lost`、重排上限 3、用完進 `blocked` |
| FR-AGENT-005 | Run 生命週期 | central | 獨立狀態機；**不寫 `terminal_sessions`**；cancel 程序無殘留（process group）；🆕 **三個計時器各答一個問題**：租約答「runner 活著嗎」（→ `lost`、重排）、idle 答「child 在前進嗎」（→ `RUN_IDLE_TIMEOUT`、不重排）、牆鐘只是兜底。**一個「還在跑但很慢」的 run 不得被誤殺** |
| FR-AGENT-006 | Run log | central | 有界、runner 端去識別、保留期；**與互動 Session 的承諾嚴格分開**。🆕 **內容是 JSONL 事件流**（`claude --output-format stream-json`／`codex exec --json`）而不是終端位元組——所以「不是 Terminal relay」是結構上的事實而不是一條紀律；截斷**不切斷一行 JSON** |
| FR-AGENT-007 | 看板溝通 | central | 訊息串三種來源；`waiting_for_input` ＋ 逾時退回 `blocked` |
| FR-AGENT-009 | **任務卡產物** | central | 執行中隨時可附；**存平台不存 node**（run 清理後仍可下載）；不可變；三層配額 |
| FR-AGENT-010 | **產物的安全提供** | central | 預設 `attachment` ＋ `nosniff`；只有圖片／文字／markdown 可內嵌；**HTML 絕不在應用 origin 渲染**；繼承 Project 存取控制 |

### FR-RUNENV — 機密、git 送回與綁定授權（V2.3）

> **2026-08-10**：隔離目錄與 clone 已移到 V2.2（FR-AGENT-011／012）。
> 本組移入一條：**FR-RUNENV-006 Project × Agent 綁定**（原 FR-AGENT-002）——
> 三層（綁定＝授權／labels＝能力，後續功能／指定＝意圖），**指定永不覆蓋綁定**，
> 未綁定的 Project 永不 offer。另加 **FR-RUNENV-007**：平台憑證取代 node 的 ambient git 憑證。

| ID | 標題 | Owner | 關鍵 AC |
|---|---|---|---|
| FR-RUNENV-001 | Secret store | central | 加密儲存；**任何 API 都讀不回值**（schema ＋ 回應雙重斷言）；可撤銷 |
| FR-RUNENV-002 | 按需下放 | central | 只送卡片宣告的；名稱須為 Project allowlist 子集；稽核不含值 |
| FR-RUNENV-003 | 去識別 | daemon | **在 runner 端**替換為 `***`；原值不離開 node |
| FR-RUNENV-004 | node 可拒絕機密 | daemon | `accept_secrets: false` 的 node 只領無機密卡片 |
| FR-RUNENV-005 | 隔離工作目錄 | daemon | 不在 allowed root；既有檔案 API 不得觸及；配額 ＋ 保留期 ＋ 清理 |
| FR-RUNENV-006 | Git 取得 | daemon | 依 `source` 三值；bare mirror ＋ worktree，不重複完整 clone |
| FR-RUNENV-007 | Git 推送約束 | daemon | 五條硬約束；**四種違規全部在 daemon 內被拒** |

### FR-DELIVERY / FR-VERIFY — 交付與驗證（V2.4）

| ID | 標題 | Owner | 關鍵 AC |
|---|---|---|---|
| FR-DELIVERY-001 | **五種**交付模式 | daemon | `none`／`artifact`／`branch`／`pull_request`／`existing_pr`；**`none` 與 `artifact` 不產生任何遠端變更**；`artifact` 缺產物則 run 不算成功 |
| FR-DELIVERY-002 | 交付的誠實性 | central | `none`／`artifact` 但有變更 → **把 diff 附成產物**，不丟棄；無變更 → 不開空 PR |
| FR-DELIVERY-003 | PR／MR 建立 | central | 內容含 AC 逐項結果與驗證摘要；建立失敗 → `delivered_branch_only`，run 不算失敗 |
| FR-DELIVERY-004 | **無自動合併** | daemon | 程式碼路徑不存在；以 git 子命令 allowlist 斷言 |
| FR-EVIDENCE-001 | 機器事實證據 | daemon | 驗證命令在 run 內執行，exit code 為真；git 狀態固定 argv |
| FR-EVIDENCE-002 | Evidence 彙整 | central | 三種來源共存；**矛盾時兩者都顯示不仲裁** |
| FR-AGENTTOOL-001 | `cliora` CLI | central | 子命令集合；`context show` 免連線 |
| FR-AGENTTOOL-002 | 流程可設定性 | central | 只允許啟用／停用既有項目；跨專案指標仍可聚合 |

> PRD Patch 與任務建議已移至 **FR-SPEC-007／FR-SPEC-004**（它們屬於釐清與拆解，不是工具介面）。

### FR-SPEC — 需求釐清與任務拆解（V2.1 資料模型／V2.5 Agent 驅動）

| ID | 標題 | Owner | 關鍵 AC |
|---|---|---|---|
| FR-SPEC-001 | 需求 Intake 與規格資料模型 | central | `requirements`／`feature_specs`（版本列，只 INSERT）／`task_proposals`；**V2.1 就有人工表單** |
| FR-SPEC-002 | 釐清 run | central | 提問走**既有看板訊息串**，不新增管道；一次一個問題；五條停止條件在情境包 |
| FR-SPEC-003 | Open questions 閘門 | central | **未解決時規格不得核准**；Agent 不得自行填答 |
| FR-SPEC-004 | 拆解 run 與提案 | central | 產出是**提案不是正式卡**；每張 Task 提案自帶 DoR 七項與 `source`／`delivery` |
| FR-SPEC-005 | 提案接受 | central | 全部／部分／編輯後建立／拒絕；缺 DoR 者落 `backlog`；被拒提案保留理由 |
| FR-SPEC-006 | 來源可追溯 | frontend | 每張卡回溯到需求與提案編號 |
| FR-SPEC-007 | PRD Patch 提案 | central | 平台只渲染與記錄決定，**不套用**；接受後走一張 `delivery: pull_request` 卡片 |
| FR-SPEC-008 | UI Mockup 關卡（**有條件**，可延後） | frontend | **依賴 tunnel 整合已啟用**；未啟用時 `ui` gate **自動停用**、停用原因可見、產出變體的卡 dispatch 被拒、一般 UI 卡照常；已啟用時 2–3 變體可預覽、保護策略由人選定、`tunnel.manage` 不在 Agent scope |

### NFR 與 SEC 增修

| ID | 處置 |
|---|---|
| `SEC-002` | **修訂**（D23）：只撤銷「呼叫端不得指定環境變數」中關於**值**的那一句；argv／binary／shell string 完全保留；互動式 Session 完全不變。修訂後的不變式：**沒有任何請求 payload 能命名一個命令、或攜帶一個機密的值** |
| 新 `SEC-00X` | **紅線 5**：Agent 產出離開隔離目錄的每一種形式，都必須落在**人看過才生效**的位置。目前四種：卡片產物、獨立分支、PR／MR、無交付。永不自動合併、永不部署 |
| 新 `SEC-00Z` | 卡片產物的提供不得成為 stored XSS 管道（預設下載、`nosniff`、HTML 不在應用 origin 渲染） |
| 新 `SEC-00Y` | 機密永不可讀回、永不入日誌、可撤銷；run 目錄不在 allowed root |
| `SCOPE-*` | 需要一條新的 scope 需求，明文寫出 V2 的四條紅線與 `00` §9 的不做清單 |
| 新 `NFR-PROJECT-001` | 看板／藍圖 API 效能：`09` §5 的 M1 定案後填入門檻 |
| 新 `NFR-RUN-001` | Run 啟動延遲（clone／worktree）：M11 定案後填入 |
| 新 `NFR-RUN-002` | Run 目錄與 log 的配額、保留期、清理保證 |
| 新 `NFR-PROJECT-002` | `.cliora/` 投影有界性：單檔大小、每 Session 檔案數、保留期 |
| 新 `NFR-PROJECT-003` | 平台不可用時 Session 不受影響（D14）；CLI 失敗訊息可行動

## 3. 必須同步修訂的既有文件

| 檔案 | 修訂內容 | 階段 |
|---|---|---|
| `research/prd.md` | 新增 Project／Task／Verification 章節；明文保留 Ad-hoc Session | V2.0 |
| `research/tech.md` | §16.1 的 Session Workspace 版面補上右欄 tab（**不刪原文，加註記**，沿用 `plan/08/01` §1.2 做法） | V2.2 |
| `.gitignore` 建議 | 文件說明使用者可把 `.cliora/` 加入 gitignore（平台不代改使用者的 `.gitignore`） | V2.1 |
| `research/style.md` | §12 版面圖補右欄 tab | V2.2 |
| `.agent/skills/cliora-project-context/SKILL.md` | 範圍句精確化：任務**紀錄**≠任務派工；git **唯讀查詢**≠git 自動化；同一 Agent 走完流程≠多 Agent 編排 | V2.0（前兩項）／V2.3（git 那項） |
| `docs/permission-matrix.md` | 六個新動作（`project.view`／`manage`、`task.create`／`update`／`approve`、`process.manage`） | 各階段 |
| `contracts/CHANGELOG.md` | v1.10.0（V2.1，`context.project`）／v1.11.0（V2.2）／v1.12.0（V2.3）／v1.13.0（V2.4） | V2.1 起每階段 |
| `README.md` / `deploy/README.md` | 新環境變數、`agentd` 版本需求 | V2.1／V2.3 |
| `docs/error-catalog.md` | 新錯誤碼（`TASK_VERSION_CONFLICT`、`TASK_BLOCKED_BY_DEPENDENCY`、`DONE_GATE_UNMET`、`TOKEN_SCOPE_DENIED`、需升級 agentd） | 各階段 |
| `docs/runbooks/` | 新增 `session-context.md`（情境未送達、token 失效、`.cliora/` 清理的處置） | V2.1 |

## 4. ADR 清單

| ADR | 主題 | 階段 |
|---|---|---|
| 0027 | **V2 範圍、Monstrare 功能內化與真實來源**（D2／D1／D12／D13）：邊界表、投影規則、出處標註、**紅線 4 的撤銷與換上的四條約束** | V2.0 |
| **0028** | **任務層、Session Token 與平台投影**（D3／D4／D7／D8／D11／D13／D14／D15）：內化閘門的邊界、`.cliora/` 的寫入面為何不違反紅線 3、Agent 憑證是什麼／不是什麼、三種新儲存各自的保留期 | **V2.1** |
| 0029 | **Agent Runner 模型與 run 生命週期**（D16／D17／D18／D24／D26）：拉取式認領、租約、run 不是 Session | V2.2 |
| 0030 | **run 的兩種輸出：log 與卡片產物**（D27／D29）。核心是兩者**保留期不同**：log 是診斷、產物是交付物 | V2.2 |
| 0031 | **隔離工作目錄與 git 存取**（D19／D20） | **V2.2 發佈**：六條目錄規則 ＋ git **取得**半邊（clone／fetch、host allowlist、known_hosts、clone 後移除 `origin`、ambient 憑證的後果）。**V2.3 增補**：五條 git 約束（push 半邊）＋ `project_agents` 綁定＝機密授權邊界 |
| 0032 | **機密管理與 SEC-002 修訂**（D22／D23） | V2.3 |
| 0033 | **交付模式與 PR 建立**（D21／D25）：`source` × `delivery`、紅線 5 | V2.4 |
| — | **修訂 ADR 0022**：tunnel 也用於 run 的 mockup 預覽（Agent 提議 → 人核准 → 平台執行）；其範圍宣告不變且更強 | V2.5 |
| 0034 | **需求釐清與拆解的形狀**（D28）：釐清用既有管道、產出是提案、三個人工關卡、停止條件內化 | V2.5 |

每份 ADR 沿用既有格式：Status／Date／Amends／Related／Requirements／Contract／Ships in／Plan，以及 **Alternatives rejected 表**——本 repo 的 ADR 之所以有用，多半是因為那張表把「以後有人會再提一次的東西」先寫掉了。

## 5. 追蹤矩陣（階段 × 需求 × 測試）

`PJ-01` 建立、每階段結束時更新：

| 需求 | 階段 | 自動測試 | 操作證據 | 狀態 |
|---|---|---|---|---|
| FR-PROJECT-001..005 | V2.0 | `backend/tests/db/test_projects.py`、e2e | 建立→綁定→開 Session 截圖 | ☐ |
| FR-TASK-001..010 | V2.1 | Gate 拒絕邏輯、樂觀鎖併發、token scope、CLI 子命令、看板單元、e2e | 看板拖曳與三種拒絕截圖、`git status` 只見 `.cliora/`、Central 停機下的 CLI 行為 | ☐ |
| FR-PLAN-001 / FR-VERIFY-001..004 | V2.4（FR-VERIFY-004 在 V2.1） | `source` 伺服器端判定、Done Gate、CLI 離線行為 | Plan 面板與失敗報告截圖、`--force` 的時間軸紀錄 | ☐ |
| FR-AGENT-001..010 | V2.2 | 原子認領併發、租約逾時重排、cancel 殘留、log 截斷 | 兩 runner 搶同一卡的紀錄、指定 vs 未指定各一次、kill 後重排錄影、訊息串與產物區截圖、HTML 產物的 response header | ☐ |
| FR-RUNENV-001..007 | V2.3 | 不可讀回（schema＋回應）、去識別、四種推送拒絕、目錄隔離 | 機密 UI 無顯示值、log 中的 `***`、mirror 加速數字 | ☐ |
| FR-DELIVERY-001..004 / FR-EVIDENCE-001..002 / FR-AGENTTOOL-001..002 | V2.4 | 四種 delivery、無自動合併的 allowlist 斷言、exit code 為真 | 四種交付各一次的結果截圖、被拒的 Done Gate | ☐ |
| FR-SPEC-001..008 | V2.1（表單）／V2.5（Agent） | open questions 閘門、提案 DoR 檢查、未核准不得拆解 | 一句需求走到卡片的完整錄影、部分接受的結果 | ☐ |

## 6. 與 `version2.md` 的差異總表

本規劃在七處偏離原始構想，每一處都有理由。`research/version2.md` 已同步加註。

| `version2.md` | 本規劃 | 理由 |
|---|---|---|
| §10「新增資料表」列出 documents／document_versions／document_patches | 不建表 | 專案文件仍在使用者 repo；平台存路徑與「接受／拒絕」的決定 |
| §7.2「文件內容可存於平台資料庫」 | 只存 Agent 需要的參考內容，投影成 `.cliora/reference/*.md` | 平台不做文件庫；`01` D2 的邊界表 |
| §11「Session environment injection」 | 不做；改為情境檔案 ＋ opt-in 代打指令 | 紅線 1（SEC-002）：呼叫端不得指定 env／argv |
| §11「Session command event capture／Exit code capture」 | **互動式 Session 不採集**（終端位元組不儲存）；**Agent Run 採集**，驗證命令由 daemon 在隔離目錄內執行，exit code 為真 | D10／D27：兩條路徑的隱私語意不同 |
| §12 只有四階段、§7 未提及執行者 | **六階段，新增 Agent Runner、隔離執行環境、需求釐清與拆解** | 2026-08-08 的裁決：平台是使用者與 Agent 的橋樑；釐清與拆解能力納入 |
| §7.6／§7.7 的 PRD patch 與任務建議列在「Agent 工具」下 | **獨立為 V2.5 的釐清與拆解階段**，並補上 Monstrare 的 `spec-interrogation` 提問能力 | 它們是同一條流程的三段，不是三個零散工具 |
| §13「不納入：自動派工」 | **任務認領納入**（Agent 主動領）；**自動指派仍不納入**（平台不替你決定誰做什麼） | 同上，且紅線 4 的撤銷範圍要精確 |
| §9 Session Workspace 四欄（Plan｜Terminal｜Workspace｜Task） | 兩欄 ＋ 右欄 tab | `plan/08`／`plan/09`／`style.md` §12 已決定 Terminal 優先、放棄多欄 |

另有三處是**補充**而非偏離：引入 Epic／User Story 中間層（D4）、看板 stage 沿用 Monstrare 的詞彙（D3），以及把 DoR／DoD／Review Gates 內化成**真的會拒絕**的閘門而非文件要求（D2）。

最後一項是 Monstrare 與 Cliora 合併之後才可能存在的東西：Monstrare 只有檔案，只能說服；Cliora 有 API，可以拒絕。
