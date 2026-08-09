# 00 — 執行總控（V2.1 任務看板與 Agent 工具鏈）

Ticket 前綴 `TK-`。上游規劃：[`research/02/03-phase-v21-task-board.md`](../../research/02/03-phase-v21-task-board.md)。

## 1. 成功定義

**要交付的：** 一個 Developer 可以在平台上把一個 Project 的工作寫成 Epic → User Story →
Task，在六車道的看板上拖著卡片走，被沒完成的前置卡擋下來；從一張卡開一個 Session，
Session 裡的 `claude` 或 `codex` **讀得到這張卡的情境包、也推得動這張卡的狀態**；
而它想勾 Review Gate 的時候被拒絕。

**其餘一律不做。** Agent Runner、自主執行、機密、隔離目錄、交付、訊息串、產物——那是
V2.2 之後的事（§2）。

**不得弄壞的八件事：**

1. **旗標關閉時，系統與 V2.0 逐位元組一致。** `CLIORA_PROJECTS_ENABLED=false` 時
   `/api/tasks*` 與 `/api/projects/*/board` 全數 404、不發任何 Session token、
   不送任何 `context.project`、導覽與畫面與 V2.0 相同。
2. **互動式 Session 的行為一個位元組都不變。** 情境投影是 Session 建立**之後**的一次加值
   往返，失敗不讓 Session 失敗（D8）；terminal relay、tmux、resize、backpressure 完全不碰。
3. **檔案面的讀取與既有寫入面完全不動。** 新的 verb 只能寫 `.cliora/` 的三個子樹，
   使用者的 `filesystem.store`／`filesystem.upload` 路徑與政策**一行不改**（紅線 3）。
4. **`authorize_workspace()` 仍然只有一份實作。** 從卡片開 Session 是**預填**不是新流程，
   Node／Runtime／Workspace 的驗證一步都不能省（`07-…md` §5）。
5. **既有 17 個 RBAC 動作的角色歸屬不變。** 只新增三個（合計 20）。
6. **Agent 憑證永遠拿不到 `task.approve`、`project.manage`、`file.upload`、
   `terminal.*`。** 而且不是靠一行 if——它根本不走使用者的認證路徑（D3）。
7. **`activity_events` 沒有保留期這件事不變。** 它是產品內容。新增的 kind 沿用同一條規則；
   要有保留期的是 `.cliora/` 的投影檔（30 天，由 daemon 清），兩者的答案不同（D9）。
8. **Ad-hoc Session 仍然是產品的一部分。** `terminal_sessions.task_id` 與 `project_id`
   一樣永遠 nullable，平台不從 workspace 或 Session 反查 Task。

成功的判準是以下十項，每一項都要有可貼上的輸出（`08-…md` §3）：

1. 建立 1 個 Epic、2 個 User Story、3 張 Task，拖曳推進，Roadmap 完成度正確，
   **未指定 User Story 的卡出現在「（未分類任務）」桶**。
2. 前置卡未完成的卡拖到 `implementing` → **409 並指名是哪幾張卡**（不是「相依未滿足」這種話）。
3. 兩個瀏覽器分頁同時拖同一張卡 → 後者 409（`version` 衝突）、彈回原位、重新載入該卡。
4. 從 Task Detail 開 Session → `.cliora/context/<session_id>.md` 與 `.token` 出現、
   情境包 **≤ 4 KB** 且含逐項驗收標準；`.cliora/process/<version>/` 出現。
5. Session 裡執行 `cliora task update TASK-3 --stage implementing` → 看板即時更新 →
   時間軸出現一筆事件，**`actor_kind` 是 `agent`**，且沒有任何人類名字被冒充。
6. 同一個 Agent token 執行 `cliora task approve` 或直接 `POST /api/tasks/{id}/gates/architecture`
   → **401/403**，且 audit 有一筆 `authz.denied`。
7. **Central 停機時**：Session 裡的 CLI Agent 照常工作；`cliora context show` 仍讀得到；
   `cliora task update` 以非零 exit code 失敗，訊息含「Session 可繼續工作」那一句（D14）。
8. 同一個 workspace 開第二個 Session → 流程檔目錄已存在被跳過（`FILE_EXISTS` 視為成功），
   情境包是一個新檔案，**不產生任何錯誤**。
9. 在 **Traqora**（D30 的第一次真正使用）上做完 1–8 之後，
   `git status --porcelain` **完全為空**。
10. `CLIORA_PROJECTS_ENABLED=false` 時：完整 V1＋V2.0 回歸全綠；
    **既有 contract fixtures 一個位元組未變**；`agentd` 0.8.0 在旗標關閉的部署上
    行為與 0.7.0 相同。

## 2. 範圍

### 納入

- `TK-00` **基線擷取與 M1 量測**（閘門，動任何程式碼之前）。
- `TK-01` 需求變更：**ADR 0028**、`research/prd.md` §8.12、skill 補述、traceability 註冊。
- `TK-02` 資料層：migration `0023`（`process_definitions`、`epics`、`user_stories`、`tasks`、
  `task_dependencies`、`requirements`、`feature_specs`、`task_proposals`、
  `terminal_sessions.task_id`、`activity_events.actor_kind`、`projects.next_card_seq`）、
  `0024`（`session_tokens`）、`0025`（seed `task.*`）。
- `TK-03` 流程定義內化：六車道、DoR 七項、Gates 六項、模板欄位的**全域單筆種子**（D15），
  含 `ui` gate 的衍生停用規則（D31）。
- `TK-04` RBAC ＋ Task API（**同一個 PR**，D6）：`task.create`／`task.update`／`task.approve`、
  十四條端點、進站與出站檢核、錯誤碼、audit ＋ activity。
- `TK-05` 需求與規格的人工流程：Intake、規格版本列、`open_questions` 閘門、手動拆卡。
- `TK-06` Session token 與 Agent principal（**觸發安全審查**）。
- `TK-07` contract v1.10.0 ＋ `agentd` 0.8.0：`context.project`、新的寫入 verb、
  `.cliora/` 清理迴圈、`context_projection` 能力旗標。
- `TK-08` `cliora` CLI：四個子命令、離線行為、安裝時的 symlink。
- `TK-09` 前端：看板（可拖）、藍圖、任務詳情、Requirements 四個畫面中的三個。
- `TK-10` Task ↔ Session：optional `task_id`、投影觸發點、Task Detail 的「開始工作」。
- `TK-11` 驗證與出口：測試、旗標關閉回歸、四個 gate、`docs/security-review-v21.md`、
  release note、**合併提案並停下來**。

### 不納入

以下每一項都是**被上游規劃明確排除**或**被本期的形狀排除**，不是能力不足：

- **Agent Runner、`run.*`、任何自主執行。** V2.2。本期的 Agent 只在人開的 Session 裡工作。
- **卡片訊息串、`task ask`／`say`／`messages`、任務卡產物。** V2.2（D24／D29）。
  Requirements 的「釐清中」畫面因此**本期不做**——它明文重用訊息串元件（`research/02/09` §4.5b）。
- **執行計畫、驗證報告、Evidence、Done Gate 的驗證項強制。** V2.4。
  本期的 Done Gate 只檢查 `dependsOn`。
- **機密、git、隔離目錄、交付模式。** V2.3／V2.4。`tasks` 的 `source`／`delivery`／
  `required_secrets` 欄位**本期建欄但不接任何行為**（D11）。
- **MCP。** 條件性，V2.4，由 M2／M5／M17 決定（`research/02/01` D11）。
- **流程可設定性。** D15：本期是全域單筆種子，不可覆寫；`process.manage` 動作到 V2.4 才加。
- **「代打第一行指令」。** 已於 2026-08-08 裁決整條刪除（D7 例外 1）。
- **離線佇列。** D14 已裁決：直接失敗。
- **`project_members`、任務指派給人、優先權排序、工時估算。**
- **把 Monstrare 的檔案複製進任何使用者專案。**

## 3. 固定基線決策

| # | 決策 | 選擇 | 理由 |
|---|---|---|---|
| D0 | **本期在 V2 的哪一格** | 兩個半邊：平台半（零風險面）＋節點半（新憑證流、新寫入 verb）。**兩半可以分開合併**，平台半先行不會讓節點半變得更難做 | V2.2 起每一階段都會再動一次安全姿態。本期把「看板」與「Agent 工具鏈」綁在同一期是上游的安排，但它們的回歸基準不同——分成兩個波次讓出問題時分得出是哪一半造成的 |
| D1 ⚠️ | **`.cliora/` 投影必須新增 protocol 訊息與 daemon 版本** | contract **v1.10.0** 的 `context.project`／`context.projected`；`agentd` **0.8.0** 新增 `VerbProject` | 兩行程式碼決定的，不是判斷：① `store_policy.go:83` 對 `VerbStore` 在 `.cliora/` 下一律回 `platform_owned`；② `store.go` 步驟 6 要求目的地目錄**事先存在**，而協定裡沒有 mkdir。**被否決**：放寬 `VerbStore` 讓它能寫 `.cliora/`（那會讓任何持有 `file.upload` 的使用者覆寫平台的情境包與 token 檔——`Verb` 型別的註解正是為了避免這件事而存在）；把情境包寫到 workspace 根目錄的一個檔案（污染使用者 repo，違反判準 9，且 `.cliora/` 之外沒有 gitignore 保護）；讓 CLI 自己去 Central 拉情境（token 從哪來？——那是雞生蛋，而且違反 D14 的免連線性質） |
| D2 ⚠️ | **`cliora` 就是 `agentd` 那支二進位** | `agentd cliora …` 子命令 ＋ 安裝時建立 `/usr/local/bin/cliora → agentd` symlink，argv[0] 分派 | 三條各自足以否決投影：單檔上限 4 MiB（`config.go:205`）、`.cliora/` 對使用者 verb 是禁區、update 的解壓器**只取單一成員 `agentd`**（`update/files.go` 的 `binaryMember`，那是刻意最小化的解壓面，為了塞第二個檔案去動它是本期最不該碰的東西）。附帶好處：D11 想要的「MCP 設定要指向一個穩定可執行路徑」在 V2.1 就成立，V2.4 不必再搬一次；版本永遠與 daemon 相符。**被否決**：獨立的 `cliora` release pipeline（第二條發佈鏈、第二份 checksum、第二個更新路徑）；投影一支 shell wrapper（仍然要寫進 `.cliora/`，同 D1 的禁區問題） |
| D3 ⚠️ | **Session token 不進 `get_current_user`** | 新增 `get_agent_principal`／`require_agent_action`，只掛在 CLI 需要的四條端點上。`get_current_user` 對 `cliora_st_` 前綴的 bearer **直接 401** | `require_action` 的簽章是 `(User) -> User`；讓 token 解析出一個 `User` 等於讓它繼承那個人的**全部**動作。分離之後「Agent 勾 gate」不是被一行 if 擋下來，而是**沒有任何程式碼路徑存在**。這與 D13 例外 3 的定案措辭一致：拆開 `task.approve` 是為了讓它能被寫死在 scope 外，而 scope 之外還要有這一層 |
| D4 | **稽核與時間軸的 actor 表達** | `audit_logs.user_id = NULL` ＋ metadata `{actor_kind: "session_agent", session_id, token_id}`；`activity_events` 新增 `actor_kind`（`user`／`agent`／`system`） | `audit_logs.user_id` 本來就 nullable（`models.py:567`），所以稽核端不必動 schema。時間軸端必須動：`actor_user_id IS NULL` 現在的意思是「系統事件」，而 `redact_actors` 會把使用者事件也清成 null——三種東西長得一樣就沒有任何一種說得清楚。**Agent 不冒充人類**（`research/02/00` §8） |
| D5 | **`card_ref` 的配號** | `projects.next_card_seq INTEGER NOT NULL DEFAULT 1`，配號用 `UPDATE projects SET next_card_seq = next_card_seq + 1 WHERE id = :id RETURNING next_card_seq - 1`（行鎖；拿到的是遞增前的值）。`EPIC-`／`US-`／`TASK-` **共用同一個序號池** | `count(*)+1` 會在兩個分頁同時建卡時撞號，而 `card_ref` 之後會進分支名（V2.3 的 `cliora/<card_ref>-<run_seq>`）與 PR 標題——一個撞過號的識別碼會在三個階段之後才爆炸。共用序號池讓編號**不連續**，這是刻意的：它是識別碼不是計數器，三個計數器意味著三個要各自加鎖的地方。另配 `UNIQUE (project_id, card_ref)` 當安全網 |
| D6 | **RBAC 詞彙與強制點同一個 PR** | `TK-04` 一次交付三個動作與它們的端點；`UNENFORCED_ACTIONS` 保持空集合 | 與 `PJ-03`／`PJ-04` 同一條理由：`test_every_action_is_enforced_somewhere` 是對 `backend/app/**/*.py` 的**文字掃描**，動作寫進 `rbac.py` 而別處沒出現就立刻紅；先加進 `UNENFORCED_ACTIONS` 再移除則在第二步紅。`research/02/01` D13 明寫不要為了先 merge 而往裡面加東西 |
| D7 | **看板不做狀態機** | 六個車道之間**任意可拖**。硬阻擋只有一條：進入 `ready` 之後的四個車道（`ready`／`implementing`／`verify`／`done`）要求 `dependsOn` 全部 `done`。DoR 七項與 WIP 上限**只警告不阻擋** | Session 有狀態機是因為它對應一個真實的行程；卡片沒有。看板是人的工具，一個會拒絕「往回拖」的看板只會讓人改用別的地方記錄真實狀態，而那正是 D1（平台 DB 為真實來源）最怕的事。DoR 全部強制會讓人放棄使用（`research/02/03` 風險表最後一列） |
| D8 | **投影失敗不讓 Session 建立失敗** | Session 建立成功後**另一次**往返送 `context.project`；失敗記 activity ＋ audit，UI 顯示「情境未送達，可重試」並提供按鈕 | 上游規劃已有這條，本期補上實作上的後果：投影不能寫在 `SessionService.create()` 的交易裡（`session.start` 已經成功，回滾會留下一個平台不知道的 tmux）。做成**建立成功後的第二次呼叫**，由路由層在 commit 之後觸發 |
| D9 | **兩種保留期的答案不同，要各自寫下來** | `activity_events`：**無保留期**（V2.0 已定）。`.cliora/{context,process,reference}/`：**30 天，daemon 清**。`session_tokens`：Session 結束即失效，**列保留** 90 天供稽核 | ADR 0024 W2 的問題要對每一種新儲存回答一次。三個答案不同是對的，寫在同一張表裡是為了讓下一個階段不必重新推導（`05-…md` §5） |
| D10 | **`ui` gate 的衍生停用要在本期就做** | 讀取流程定義時套用 `tunnel_integration.enabled = false ⇒ ui gate 停用`，Project Settings 寫出停用原因 | D31 已裁決。六個 gate 在**本期**上線，所以「涉及畫面的卡片卡在一個永遠無法滿足的關卡上」這個死鎖**在本期就會發生**，不能等 V2.5。它是一條讀取時的衍生規則，不是一個 Admin 要記得去關的開關 |
| D11 | **`source`／`delivery`／`required_secrets` 建欄不接行為** | `0023` 就建這三欄與 `repository_id`／`base_branch`／`target_branch`／`existing_pr_ref`，API 可讀可寫，**但沒有任何程式碼會依它們做事**；UI 顯示為徽章 | 它們是卡片的意圖宣告，人現在就會想寫。V2.3／V2.4 要接的是行為不是欄位——那時再 `ALTER` 會讓已經建好的卡片全部缺欄。**代價要寫進 ADR**：一個宣告了 `delivery: pull_request` 的卡片在 V2.1 不會產生任何 PR，UI 要說清楚「這是意圖，尚未有執行者」 |
| D12 | **這一期不碰的東西** | `backend/app/services/{terminal_relay,terminal_queue,tunnels,integrations,node_update,files}.py`、`backend/app/api/ws/terminal.py`、`daemon/internal/{terminal,tmux,session,tunnel,update}`、`daemon/internal/files/{store,upload,read,search}.go` 的既有函式、`frontend/src/{terminal,monaco,protocol}`、`deploy/` | 判準寫死：若 diff 出現在上述任一處，就是走錯路了。`GATE-TK-TOUCH-LIST`（`08-…md` §4）以 `git diff --name-only` 斷言它。**注意本期的清單與 `PJ` 的不同**：daemon 與 contract 這次會動，所以 gate 從「零 diff」改成「白名單內的 diff」 |
| D13 | **驗收素材：Traqora 正式 repo** | D30 的第一次真正使用。用 Traqora 真實的待辦建看板、開 Session、投影 `.cliora/` | V2.1 只在 workspace 寫 `.cliora/`，不碰程式碼、不執行任何東西，所以正式 repo 是安全的（`research/02/01` D30 的階段表）。它驗到的是規劃說的那件事：**真實待辦撐不撐得住六車道與 DoR**。判準 9 的 `git status --porcelain` 為空，在一個活躍 repo 上才有意義 |
| D14 ⚠️ | **本期觸發安全審查** | `docs/security-review-v21.md`，三節：token 發行與失效、Agent 認證路徑的邊界、`.cliora/` 寫入面 | `research/02/10` §6 的四個觸發條件中命中兩個（新憑證流、新寫入路徑）。V2.0 明文寫過「為什麼不觸發」，本期要寫的是「觸發了，審了什麼」。**不可略過**，而且要在 `TK-11` 之前完成——它會回頭改設計的機率不低（`04-…md` §6） |

## 4. 波次與 ticket

| 波次 | Ticket | 標題 | 依賴 |
|---|---|---|---|
| **0（閘門）** | `TK-00` | 基線擷取（OpenAPI、`pg_dump`、contract fixtures 清單）＋ **M1 量測** | — |
| | `TK-01` | ADR 0028、PRD §8.12、skill 補述、traceability 註冊（`proposed`） | `TK-00` 的 M1 |
| **1（平台半・資料）** | `TK-02` | migration `0023`／`0024`／`0025`、SQLAlchemy 模型、上下行演練 | `TK-01` 核准 |
| | `TK-03` | 流程定義內化與種子（六車道／DoR 七項／Gates 六項／模板；`ui` gate 衍生停用） | `TK-02` |
| **2（平台半・API）** | `TK-04` | RBAC 三動作 ＋ 十四條 Task API ＋ 閘門 ＋ 錯誤碼（**同一個 PR**，D6） | `TK-03` |
| | `TK-05` | 需求／規格／提案的人工流程 API | `TK-04` |
| **3（節點半）** | `TK-06` | `session_tokens`、Agent principal、scope、稽核 actor（**安全審查同步進行**） | `TK-04` |
| | `TK-07` | contract v1.10.0 ＋ `agentd` 0.8.0：投影 verb、清理迴圈、能力旗標 | `TK-06` |
| | `TK-08` | `cliora` CLI（agentd 子命令 ＋ symlink） | `TK-07` |
| **4（前端）** | `TK-09` | 看板、藍圖、任務詳情、Requirements 三畫面 | `TK-04`／`TK-05` |
| | `TK-10` | Task ↔ Session、投影觸發點與失敗呈現 | `TK-07`／`TK-09` |
| **5（收尾）** | `TK-11` | 測試、旗標關閉回歸、四個 gate、安全審查定稿、release note、**合併提案並停下來** | 全部 |

**閘門一：`TK-00` 完成前不得動任何程式碼。** 判準 10 需要「本期之前」的 OpenAPI 與
contract fixtures 清單，改完就再也取不到。M1 也在這裡——它決定 `TK-04` 的看板端點
要不要分頁，而那是一個**改了就要改前端**的形狀（`01-…md` §2）。

**閘門二：`TK-01` 核准前不得動 `backend/`、`frontend/`、`daemon/`、`contracts/`。**
與前五期同一條理由：`.agent/skills/cliora-project-context/SKILL.md` 的範圍句。
V2.0 已經改過那一句，本期要補的是 **`.cliora/` 投影與 Session token 這兩個 V2.0 沒有的面**。

**閘門三：`TK-06` 的安全審查草稿要在 `TK-07` 開工前有初稿。** 順序不能反——
審查若否決了 token 的落地方式，`TK-07` 的投影內容就要改，而那時 contract 已經定稿了。

**波次 3 可以整批延後而不擋波次 1／2／4 的大部分。** 這是 D0 的實際用途：
若時程壓縮，平台半（看板可用、人自己拖）是一個可以獨立交付的成果，
只是出口條件 4–8 未達成、本期不得標為完成。

## 5. 風險

| 風險 | 徵狀 | 處置 |
|---|---|---|
| **投影一路做下去才發現 daemon 那條路走不通** | 寫到 `TK-07` 才撞上 `platform_owned` | 已經先撞掉了（D1）。實作第一件事是**寫一條會失敗的 daemon 測試**：用 `VerbStore` 寫 `.cliora/context/x.md` 必須被拒——它同時是新 verb 不得放寬既有規則的迴歸 |
| **`agentd` 0.8.0 推出去，舊 Central 或舊 node 混用** | 部分 node 投影得了、部分不行，而使用者看到的是「有時候有情境有時候沒有」 | `node.register` 的 `context_projection` 能力旗標（差異 #5）＋ UI 上逐 node 顯示。**不做自動升級**：那是既有的 `node_update` 路徑，本期不碰 |
| **Session token 洩漏** | token 進了 log、進了 audit metadata、或被 `filesystem.read` 讀出來 | 三道：儲存只存 HMAC（沿用 `token_pepper` 的既有做法）、audit 只記 `token_id` 不記值、`.cliora/context/*.token` 落地為 0600 且**加入 daemon 的敏感檔分類**（讀取面拒絕預覽，`05-…md` §4）。安全審查的第一節 |
| **情境包塞不進 4 KB** | 驗收標準一多就爆 | M17 從第一天就量（`10-…md`）。超出時的行為**先定好**：截斷 AC 之外的區塊、保留 AC 全文、在檔尾寫「已省略 N 項，用 `cliora task get` 取完整內容」——不是靜默截斷 |
| **Agent 根本不用 CLI** | 看板上只有人拖的卡 | 這是內化路線的核心假設，M2 是它的檢驗。情境包**第一段**就是三行「怎麼回報進度」。若前 10 個 Session 使用率低，那是 MCP 決策規則的輸入而不是一個 bug（`research/02/01` D11） |
| **看板拖曳的 e2e 不穩** | HTML5 DnD 在 Playwright 上時好時壞 | 鍵盤／選單的等效路徑是**主要**斷言路徑，真實拖曳另有一條允許重試的測試。兩條都要有——只有選單那條會讓「拖不動」上線（`07-…md` §2.3） |
| **`.cliora/` 清理誤刪 image drop 的東西** | 使用者的截圖三十天後不見了 | 清理迴圈的路徑白名單只有三個子樹，且有一條測試斷言 `uploads/` 在清理後仍在（`05-…md` §5） |
| **`delivery`／`source` 欄位讓人以為 V2.1 會執行** | 「我設了 pull_request 為什麼沒有 PR」 | D11：UI 上這一區標為「執行設定（V2.3 起生效）」，且 Task Detail 的 Agent 執行欄在本期顯示「本階段由人執行」。文案是唯一的處置，因為欄位本身要提早存在 |
| **需求／規格的人工表單沒人用** | Requirements 分頁一直是空的 | **這不是風險，是訊號**（M14）。它是 V2.5 值不值得做的免費早期指標，所以要量而不是要救（`research/02/01` D28 §4） |
