# 00 — 升級總覽

> **2026-08-08 的三次裁決已寫入本目錄**
> 1. 任務卡要能在平台上拖曳。
> 2. Monstrare 以**功能內化**方式導入，不複製檔案進使用者專案。
> 3. **平台成為使用者與 Agent 之間的橋樑**：Agent 是類似 GitHub Runner 的執行者，自行認領任務卡、在隔離工作目錄拉取 git、依卡片的交付模式產出結果（PR／分支／無交付）；Project 與 Agent 是多對多；原有 Session 保留給使用者直接操作。
>
> 第三次裁決把 V2 從「專案管理功能」變成「AI 開發的執行控制平面」，並且**明確撤銷了兩條既有紅線**。§7 記錄撤銷了什麼、換上什麼。

## 1. 目標與成功定義

讓 Cliora 從「跨 VM 的 CLI Agent 遠端控制台」升級為**跨專案的 AI 開發控制平面**：使用者在看板上建立與溝通任務，Agent 自行認領、在隔離環境完成工作、把成果交付回來，全程可追蹤、可驗證、可稽核。

成功需同時成立：

- **Version 1 的每一項能力都還在，而且行為未變**（清單見 §5）。互動式 Session 是使用者直接操作的路徑，不被 Agent Run 取代。
- 關掉 `CLIORA_PROJECTS_ENABLED` 後，畫面、API 與 protocol 與升級前完全一致。
- 一個 Agent 可以同時服務多個 Project；一個 Project 可以有多個 Agent。
- 任務卡**可以指定特定 Agent，也可以不指定**（預設不指定，任一符合資格者皆可領）。指定永遠不能繞過綁定授權。
- 使用者在看板上就能與正在執行的 Agent 對話，不必進 Terminal。**同一條管道也用來釐清需求**（D28）。
- 一句模糊的需求可以被問成規格、拆成任務卡，每一步都有人工關卡。
- **Agent 的產出只落在人看過才生效的地方**：任務卡產物、獨立分支、PR，或什麼都不交付。永不推共用分支、永不自動合併（§7 紅線 5）。
- **不需要交付的任務卡**（調查、分析、驗證、寫規格）也能被認領與完成，且不產生任何 git 變更。
- 機密以具名、專案範圍、可撤銷的方式下放；任何 API 都讀不回值，任何日誌都不含值。

## 2. 兩種執行模式並存

這是 V2 最重要的結構事實：平台從此有**兩條執行路徑**，生命週期不同、風險不同、UI 不同。

| | **互動式 Session（V1，保留）** | **Agent Run（V2 新增）** |
|---|---|---|
| 誰驅動 | 人在瀏覽器打字 | 平台掛出工單，**Agent 自行認領**（拉取式；卡片可指定特定 Agent，也可不指定） |
| 工作目錄 | 使用者選定的 allowed root（**綁定只服務這一欄**） | **每次執行一個隔離目錄**，daemon 擁有，`<state>/.cliora/runs/<run_id>/`（**V2.2 起**） |
| 程式碼來源 | 目錄裡本來就有的 | 依任務卡從 git clone／checkout（或不需要） |
| 生命週期 | tmux 持久化，人來人往 | queued → claimed → 執行 → 交付 → 結束即銷毀 |
| 誰看輸出 | 人即時看 Terminal | 平台收 run log（有界、去識別、有保留期） |
| 產出 | 就地變更 | 依卡片的 delivery：**卡片產物**／PR／分支／無 |
| 出錯的收斂方式 | 人隨時介入 | 租約逾時重排、PR 未合併、證據留存 |

**兩者共用**：Node 註冊與憑證、Runtime allowlist、WSS 控制通道、heartbeat、audit。
**兩者不共用**：workspace 授權模型、檔案面、Terminal relay。

## 3. Monstrare 的內化（第二次裁決）

能不能內化，取決於**誰在讀它**。這條分界不是偏好，是 Claude Code 與 Codex 的載入機制決定的。

| Monstrare 的東西 | 誰讀 | 處置 |
|---|---|---|
| 六欄看板 stage 詞彙（`backlog`/`blocked`/`ready`/`implementing`/`verify`/`done`） | 人／平台 | **內化為車道定義**。與 `version2.md` §7.3 一對一對應 |
| 卡片 schema（`risk`/`readiness`/`gates`/`links`/`dependsOn`…） | 人／平台 | **內化為 `tasks` 表欄位**，並擴充 V2 需要的 source／delivery |
| Epic → User Story → Task 三層 | 人／平台 | **內化為平台實體** |
| Definition of Ready／Done | 人／平台 | **內化為真的會拒絕的閘門** |
| Review Gates 六關卡與「agent 輸出不等於核准」 | 人／平台 | **內化**：核准必帶人類 actor；Agent 憑證 scope 寫死不含核准 |
| Context Protocol（Always/On-demand 預算） | 人／平台 | **內化為情境包產生器** |
| `ai/templates/*` | 人／Agent | **內化為表單 schema 與產出物產生器** |
| `tools/kanban/` | 人 | **整個被平台 Board 取代** |
| `ai/context/*.md` | Agent | 平台存內容，執行時投影成檔案 |
| **`.claude/skills/`、`.claude/agents/`、`AGENTS.md`** | **Agent（CLI 從磁碟載入）** | **硬邊界，無法內化**。投影進工作目錄，由情境包指路 |

**硬邊界的意義**：`claude` 與 `codex` 讀的是工作目錄裡的檔案；只存在 PostgreSQL 裡的 skill，CLI 永遠看不到。平台**無法用 API 讓 Agent「知道」一條規則**——它只能把檔案放進 Agent 的工作目錄。

在 Agent Run 路徑上這件事反而更乾淨：工作目錄是平台建立的，投影什麼、放在哪完全由平台決定，不必顧慮污染使用者的 repo。

**出處**：流程定義源自 Monstrare（MIT），在 ADR 0027 與種子資料標註。

## 4. 真實來源：平台 DB

任務、對話、計畫、驗證、執行紀錄的真實來源都是平台 DB。使用者的 repo 只有程式碼；Agent 的隔離工作目錄是暫時的。

```text
  平台 DB（單一事實來源）                  Agent 隔離工作目錄（每次執行，用完即毀）
  ────────────────────────                ──────────────────────────────────────
  projects / project_agents               <state>/runs/<run_id>/
  process_definitions                       repo/              git clone + checkout
  epics / user_stories / tasks              .cliora/context.md    情境包
  task_messages   看板上的對話              .cliora/process/      流程與檢核說明
  agent_runners / task_runs                 .cliora/reference/    design-system 等
  run_logs（診斷：有界、去識別、有保留期）
  task_artifacts（交付物：跟著卡片走，不隨 run 清理）
  project_secrets（加密，寫入後永不可讀回）
  execution_plans / verification_reports
  evidence_items / activity_events
```

## 5. Version 1 保留清單（回歸基準）

| 領域 | 保留內容 | V2 的觸碰方式 |
|---|---|---|
| 認證與 RBAC | 登入、JWT、三角色、16 個動作、`ROLE_ACTIONS` 單一事實來源 | **只新增動作**，不改既有動作的角色歸屬 |
| Node | 註冊、enrollment、credential、heartbeat、offline 判定、doctor、更新 | 不改。Runner 是 `agentd` 的一個模式，**重用同一套信任建立**（D16） |
| Runtime | claude／codex 偵測、allowlist、sandbox 姿態（ADR 0023） | 不改。**不新增 runtime，也不改 argv** |
| Workspace | allowed roots、`authorize_workspace()`、daemon `os.Root` 收斂 | 互動式 Session 完全不變。Agent Run **不使用 allowed root**，走另一套目錄（D19） |
| Session | 生命週期狀態機、tmux 持久化、recover、single writer／多 viewer、system terminal | 只新增 nullable 關聯欄位，不改狀態機。**Agent Run 不是 Session** |
| Terminal | PTY、resize、backpressure、gap、control acquire／release | **一個位元組都不動** |
| 檔案 | 唯讀瀏覽、搜尋、Monaco 預覽、敏感檔分類、圖片投放、一般上傳 | **完全不動** |
| Tunnel／Integration | 第三方 tunnel、憑證管理 | 不改；secret store 是新的一套，不混用（D22） |
| Audit | `audit_logs`、查詢、每個寫入動作一筆 | 新動作沿用同一條路徑 |
| 前端 | 既有 5 個路由與畫面 | 導覽重整為分組，**路徑不變** |

## 6. 五個階段

| 階段 | 可展示成果 | 主要風險退休條件 | 依賴 |
|---|---|---|---|
| **V2.0** 專案基座 | Project、跨 Node 綁定 Workspace、活動時間軸、導覽重整 | 導覽重整不破壞既有畫面；旗標關閉可完全還原 | 決策定案 |
| **V2.1** 任務看板 | 內化流程、Epic→US→Task、看板可拖曳、看板上的對話、從卡片開互動 Session | 內化的閘門真的會拒絕；投影不污染 repo | V2.0 |
| **V2.2** Agent Runner | Agent 註冊、**自行認領**、租約與重排、**自己把專案 clone 到隔離目錄**、run log 回傳、**產物附到任務卡**、看板上看得到執行中 | 認領無雙重領取；runner 死亡能重排；log 有界且去識別；**run 目錄與使用者 workspace 互不可達**；產物有配額且安全提供 | V2.1 |
| **V2.3** 機密、git 送回與綁定授權 | Secret store、安全下放、**取代 node 的 ambient git 憑證**、推 `cliora/` 分支、`project_agents` 綁定 | 機密永不可讀回、永不入日誌；推送五條約束；綁定成為機密的授權邊界 | V2.2 |
| **V2.4** 交付與驗證 | **五種 delivery 模式**、PR／MR 建立、驗證閘門、Evidence、專案指標 | **每種出口都落在人看過才生效的地方**；分支命名空間強制 | V2.3 |
| **V2.5** 需求釐清與拆解 | 從一句模糊需求問成規格、拆成 AI-ready 卡片、PRD patch 提案 | 提案不是正式資料；三個人工關卡都必帶人類；不新增訊息管道 | V2.3（**不依賴 V2.4，可並行**） |

> **2026-08-10 裁決**：Agent 收到任務後**自己把專案拉到本地的隱藏目錄**（`.cliora/runs/<run_id>/`），
> 像 GitLab Runner 那樣。**Workspace 綁定從此只服務互動式 Session**（既有 CLI 與 Terminal）；
> V2.2 的 runner 功能鎖定在看板任務處理。
> 這把 D19（隔離目錄）與 D20 的取得半邊從 V2.3 提前到 V2.2，把 D18（綁定）從 V2.2 延後到 V2.3，
> 並**移除**原本 V2.2 最大的已知缺口（無人值守執行在使用者的 workspace 上）。
> label 比對是後續功能：現在每個 agent 都可以拉每個 project，授權邊界是 enrollment。
> 完整搬動表見 `04-phase-v22-agent-runner.md` §0。

階段是 release gate，不是團隊分工。每階段內部照 `research/01` 的既有節奏：契約先定稿，四邊並行。

**node 升級節奏**（2026-08-09 修訂；2026-08-10 裁決不改節奏，只改各版的內容）：V2.0 不動 daemon；**V2.1／V2.2／V2.3／V2.4 各一次**
（`agentd` 0.8.0 / 0.9.0 / 0.10.0 / 0.11.0）；**V2.5 不動 daemon**（它只是一種 `delivery: none` 的 run）。

> 原本寫的是「V2.0／V2.1 不動 daemon」。V2.1 之所以要動，是因為 `.cliora/` 投影在既有的
> 寫入路徑上做不到（`.cliora/` 對使用者的寫入 verb 是禁區、協定裡沒有 mkdir），
> 而 `cliora` CLI 也無法用投影發行。推導見 `plan/17/00-execution-plan.md` D1／D2。
> **V2.1 的 daemon 變更範圍很窄**：一個新的寫入 verb、一個清理迴圈、一個 argv[0] 分派；
> terminal、tmux、tunnel、既有檔案路徑零 diff，由 gate 斷言。

## 7. 紅線：撤銷了什麼、換上什麼

V1 有四條紅線。第三次裁決**撤銷其中兩條**，這是需求變更，不是繞過。撤銷一條護欄就要換上一條——以下逐條說明換上的是什麼。

### 紅線 1 — SEC-002：呼叫端不指定 argv、binary、shell string 或環境變數

**部分撤銷：僅環境變數，僅 Agent Run 路徑。**

**保留不變**：argv 仍完全由 daemon 從 allowlist 組出；`StartOptions` 不接受命令字串；互動式 Session 完全不變。

**撤銷的部分**：Agent Run 需要環境變數（git 認證、專案設定）。換上的三條約束：

1. **值不來自任何請求 payload。** 值只來自平台的 secret store，由 Admin 事先建立，寫入後任何 API 都讀不回。
2. **名稱按專案 allowlist。** 一張任務卡只能取用該 Project 宣告過的變數名，卡片本身不能引入新名稱。
3. **值永不進入任何日誌、事件、錯誤訊息或 UI。** runner 在送出 run log 前做值比對去識別。

### 紅線 2 — ADR 0014：路徑安全由 `workspace.Root` 收斂，每次操作都重驗

**不變，但適用範圍要講清楚**：它管的是使用者的 allowed root。Agent Run 的隔離目錄**不在 allowed root 內**，也不該在——它由 daemon 擁有、每次執行建立、用完銷毀，走自己的配額與清理規則（D19）。

**兩者不得互通**：Agent Run 不能讀寫使用者的 allowed root；使用者的檔案面也不能瀏覽 run 目錄。

### 紅線 3 — ADR 0024／0026：寫入面只新增，不編輯、不移動、不刪除

**對使用者 workspace 完全不變。** V2 不新增任何對 allowed root 的寫入路徑。

Agent Run 在它自己的隔離目錄裡當然可以隨意讀寫——那是它的沙箱，不是使用者的工作區。這個區分要寫進 ADR，否則會有人拿它當「寫入姿態已經放寬」的先例。

### 紅線 4 — 不做 Git 自動化與任務派工

**明確撤銷，這正是第三次裁決要的東西。** 換上的四條約束：

1. **分支命名空間強制**：**平台代表卡片執行的 push** 只推 `cliora/<card_ref>-<run_seq>`，
   寫死在 daemon，不是設定值。
2. **永不推上共用分支**：**平台的 push 路徑**對 base／target 分支、受保護分支一律拒絕，
   即使卡片這樣寫。

> **2026-08-10 裁決衍生、2026-08-11 核准的修訂：把這兩條的主詞寫對。**
> 改紅線措辭是治理動作，所以它有獨立的核准，不是隨裁決自動生效的推論。
> 原文寫「Agent 只能推 `cliora/`」。
> 同日的第二次裁決明確：**Agent 在沙箱裡可以用該 node 既有的 git 憑證做 git 能做的任何事，
> 包含 push——這是刻意給的自由，不是一個等著被補起來的洞。**
>
> 所以這兩條約束的對象是**平台代表卡片執行的 push**（V2.3 起才存在），
> 不是 Agent 自己在沙箱內的行為。這與 D25 一向的姿態一致：
> **不限制 Agent 在沙箱裡能做什麼，改為限制它的產出能怎麼離開沙箱**。
>
> 收斂點有三個，都不是 daemon 的 argv 表：
> ① 紅線 5 的原則——**一條沒有人 merge 的分支不影響任何人**；
> ② node 的部署姿態（ADR 0023：node 是可拋棄的隔離 VM；runner node 應專用）；
> ③ **可觀測性**——run 摘要記錄 `git remote -v` 與未推送 commit 數，
> 讓「這個 run 有沒有動到遠端」在 Run 詳情頁上是事實而不是猜測
> （`plan/18/04b-run-directory-and-git.md` §5.4）。
>
> **不改的是第 3、4 條**：永不自動合併、派工是拉取式的。那兩條與這次裁決無關。
3. **永不自動合併**（`version2.md` §13 的既有宣告繼續有效）。PR 由人審、由人合。
4. **派工是拉取式的**：Agent 自行認領，平台不做自動指派、不做排程最佳化、不做負載平衡（D17）。被撤銷的是「任務可以被 Agent 領走」，不是「平台會替你決定誰做什麼」。卡片上的「指定 Agent」是 poll 查詢的一個過濾條件，不是推送（D17b）。

### 🆕 紅線 5 — 自主執行的每一種出口，都必須落在「人看過才生效」的地方

新增的一條，它是前四條讓步之後唯一的收斂點。**它陳述的是原則，不是清單**：

> **Agent 的產出離開隔離目錄的每一種形式，都必須落在一個人類看過之後才會生效的位置。
> 沒有任何形式可以直接生效。**

由這條原則推論出目前的四種出口：

| 出口 | 為什麼符合原則 |
|---|---|
| **任務卡產物**（附件、留言附檔） | 惰性資料。不碰 repo、不碰分支、不觸發任何東西。人打開才看得到 |
| **獨立分支**（`cliora/` 命名空間） | 沒有人 merge 就不影響任何人 |
| **PR／MR** | 必須有人審、有人合 |
| **無交付** | 什麼都沒離開 |

推論出的實作規則：不得直接寫使用者的 workspace、不得推共用分支、**不得自動合併**、不得部署、不得執行任何上述四種以外的外部副作用。

**任務卡產物是四者中最安全的一種**，不是紅線的例外——它連 git 都不碰。把它列進來不是放寬，是補上一個本來就符合原則、卻在第一版表述裡被漏掉的形式。

任何想新增第五種出口的提案，要論證的是**上面那條原則**，不是「清單可以再加一項」。

### 程序前提

`.agent/skills/cliora-project-context/SKILL.md` 明列「Do not introduce … **Git automation, task routing, or multi-agent orchestration** without a requirements change」。

所以**需求變更是 V2.0 的第一張 ticket，不是事後補件**：PRD 增訂、ADR 0027、skill 範圍句修訂、`traceability/requirements.json` 註冊（見 `10`）。修訂要精確：

- Git **自動化**現在在範圍內，但只限紅線 4 的四條約束。
- 任務**認領**在範圍內；任務**自動指派**仍不在。
- 同一個 Agent 走完整流程仍**不是**多 Agent 編排；跨 Agent 協作、Agent 互相派工仍不做。

## 8. 共通工程契約（沿用 V1 紀律）

- 新 API 在 boundary 完成 authentication、resource-level authorization 與 validation；錯誤回傳穩定 machine code、安全訊息與 `request_id`。
- 新 protocol 訊息先進 `contracts/v1/schemas/` 與 fixtures（含 invalid 案例），再寫兩邊實作；contract 走 minor bump。
- 新 RBAC 動作必須同時加進 `ROLE_ACTIONS`、`frontend/src/api/dto.ts` 的 `ACTION_*`、seed migration，**並在同一張 ticket 內接上強制點**（`test_every_action_is_enforced_somewhere` 雙向失敗）。
- 所有時間 aware，傳輸 RFC 3339 UTC，畫面才轉本地。
- 每個平台側寫入動作寫一筆 audit。**Agent 的動作 actor 標示為 runner，不冒充人類。**
- 每一種新的儲存（run 目錄、run log、**卡片產物**、secret）都要回答 ADR 0024 W2 的那個問題：**誰清這個、什麼時候清。**
- **`v2` 分支何時合併回 `dev`，一律由人工確認**（`10` §7）。出口條件全綠只是取得提案資格，不是核准；自動化不得發起或完成這個合併。 注意 run log 與卡片產物的答案不同：前者是診斷，有保留期；後者是交付物，跟著卡片走。

## 9. 明確不做（V2 全期）

- **自動合併、自動部署、自動核准高風險變更。**
- 多 Agent 自動協作、Agent 互相派工、Agent 組織圖、跨 Agent 訊息佇列。
- **需求 → 規格 → 拆解 → 執行 → 交付的全自動鏈**：每個關卡都要人（D28）。
- 需求優先權排序、工時估算、Sprint 規劃。
- 平台自動指派任務給特定 Agent（認領是 Agent 主動的）。
- 排程最佳化、負載平衡、工時預測、Sprint 排程。
- 平台編輯／移動／刪除使用者 workspace 的檔案（ADR 0024／0026 不翻案）。
- 通用的「在 node 上執行任意命令」路徑（D10 的否決理由）。
- Web IDE、視覺化 Workflow Designer、Jira 取代品。
- **儲存互動式 Session 的 terminal bytes**（V1 的承諾繼續有效；run log 是另一件事，見 D27）。
