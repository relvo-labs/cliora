# 09 — 實作進度與證據

本檔隨實作更新；「證據」欄只填**實際跑過的指令與其輸出位置**，不填計畫中的測試。

最後更新 **2026-08-11（第三版）**：**`AR-00`…`AR-12` 的程式與文件都已完成並在本機全綠；
剩下的都是人工事項（§4）。**
（第二版把 `AR-12` 記成 ✅ 是錯的——當時 #18 的 diff 上傳沒有接上、
`GATE-AR-DISPATCH-COVERAGE` 不存在、dispatch／產物／`RunReaper` 一條後端測試都沒有。
那一輪的補齊見 §3 第 20–25 條。）
裁決內容（Agent 自己拉專案到隔離目錄、workspace 綁定只服務互動式 Session、
綁定與 label 比對延後）與它改動了什麼，見 `research/02/04` §0 與 `00-…md` §3 的
D11／D13／D15–D20。

前置條件是 V2.1 的十一條出口條件全綠——
本機已全綠，但 `plan/17` 的出口條件 9（Traqora 正式 repo 實跑）與**合併提案**
仍待人工完成（`plan/17/09` §4）。**本期不因為那兩件事未完成而提前開工**：
`AR-00` 的基線要在一個確定的 V2.1 狀態上擷取，否則判準 12 的「與升級前 diff」沒有意義。

## 0. 待確認項目的狀態（2026-08-11 結清）

裁決紀錄的索引在 [`README.md`](./README.md) §裁決紀錄。**本節只記還沒有答案的。**

| 類別 | 剩下什麼 |
|---|---|
| **擋開工** | **無。** 基線點、紅線措辭、成本上限三項均已裁決；`AR-00` 的六份基線已擷取（§1.1），閘門一解除 |
| **擋波次 1–2**（`AR-03` 起） | **無。** 三份 ADR 已於 2026-08-11 人工核准，閘門二／三／四同時解除 |
| **擋波次 3**（`AR-07`／`AR-07b`） | **M11／M12 已量**（§1.2，`AR-07b` 不再被它們擋，但 mirror-vs-淺-clone 要先決定）。剩下：**M-AR-2**（要改 `daemon/cmd/fakecli`，所以它同時被閘門二擋著）、**M-AR-9 的尾巴**（要一台可以無人值守執行 `Bash` 的機器） |
| **排在 `AR-07` 第一件事** | 兩項要一次真的 run 才知道：`claude --permission-mode dontAsk` 的語意、`codex exec -s workspace-write` 的 landlock 實際範圍 |
| **V2.3 開工前** | `isolate_ambient_credentials` 的**值**（形狀已定：預設取代、可關成疊加）。M-AR-6 會影響它 |
| **人工、與設計無關** | `plan/17` 的合併提案、出口條件 9 在 Traqora 實跑、`agentd` 0.8.0 的發布時機 |

**量測擋的是節點半，不是閘門票、ADR、資料層、API 與佇列。**
三份 ADR 已於 2026-08-11 核准，波次 1 可以開工。

## 1. Ticket 狀態

| Ticket | 標題 | 狀態 | 證據 |
|---|---|---|---|
| `AR-00` | 基線擷取（**實際基線點 `dc61006`**，見 §3 第 1 條）＋ **M-AR-1／M11／M12（已量）、M-AR-9（部分）、M-AR-2（未做）** | ◐ | 六份基線在 `artifacts/ar/local/baseline/`（§1.1）；量測在 `artifacts/ar/local/measurements/`（§1.2）。擷取器與量測器：`scripts/ar/{capture-baseline.sh,frontend_routes.py,measure_terminal_latency.py,measure_clone.py,measure_event_intervals.py}` |
| `AR-01` | ADR 0029、PRD §8.13、skill、traceability | ✅ **ADR 0029 已於 2026-08-11 人工核准** | `docs/adr/0029-v22-agent-runner-model-and-run-lifecycle.md`（**Status: accepted**）；`research/prd.md` §8.13（FR-AGENT-001、003–013，共 12 條、58 個 AC）；`.agent/skills/cliora-project-context/SKILL.md` 三面補述 ＋ Git automation 那一句改寫；`traceability/requirements.json` 12 筆 `proposed`，`scripts/trace validate --level static`／`--level selectors`／`coverage --strict` 全綠，`docs/traceability/{matrix,owners}.md` 已 render |
| `AR-02` | ADR 0030（log 與產物的兩種保留期） | ✅ **已於 2026-08-11 人工核准** | `docs/adr/0030-v22-run-log-and-card-artifacts.md`（**Status: accepted**）。§Part A 的「掉最後 ≤64 KiB」三句寫在 Consequences 與 Decision 兩處 |
| `AR-02b` | 🆕 ADR 0031（隔離目錄 ＋ git 取得 ＋ Agent 的 git 自由）**＋ 紅線 4 措辭修訂** | ✅ **已於 2026-08-11 人工核准**；紅線 4 **已於 2026-08-10／11 改好**（見 §3 第 5 條） | `docs/adr/0031-v22-isolated-run-directory-and-git-fetch.md`（**Status: accepted**，Status 段已寫明 V2.3 會 amend 本文件，以及 mirror-vs-淺-clone 這一項仍開放） |
| `AR-03` | migration `0029`／`0030`／`0031` ＋ 模型 | ✅ | 八張表 ＋ 種子 ＋ `nodes.agent_runner`；`tasks` 的兩條 FK 一起補（0023 自己承諾的）。`alembic upgrade head` 綠、`scripts/pj/gate-schema-additive.sh` 對 AR-00 基線「只有新增」、新增 `scripts/ar/gate-migration-roundtrip.sh` 且 downgrade 回 `0028` 與基線逐位元組相同 |
| `AR-04` | RBAC 四動作 ＋ Agents／**Repositories**／Dispatch API（同一個 PR） | ✅ | 四個動作 ＋ 十三條端點同一個 commit，`UNENFORCED_ACTIONS` 維持空集合。三個 SCOPE 守衛依它們自己留的指示改寫（見 §3 第 8 條）。`make check` 全綠 |
| `AR-05` | 資格查詢、claim-then-offer、租約 sweep、重排 | ✅ | `services/{runs,run_logs,run_reaper}.py` ＋ `api/ws/nodes.py` 四條分支 ＋ `main.py` 的 lifespan。`backend/tests/db/test_run_queue.py` 九條，含用兩條真連線跑 50 次交錯的雙重領取測試 |
| `AR-06` | contract v1.11.0 ＋ fixtures | ✅ | 十二個新型別、41 個新 fixture（17 valid ＋ 24 invalid），三個語言各自驗。既有 110 個檔逐檔未變。`contracts/CHANGELOG.md` 的 1.11.0 條目補上了（原本 ADR 引用 v1.11.0 但 changelog 沒有那一節）。🆕 **`node.heartbeat` 多一個 optional `runner`**——既有訊息唯一的改動，理由見 §3 第 24 條 |
| `AR-07b` | 🆕 `StateDirectory`、run 目錄、**淺 clone（不做 mirror，見 §3 第 11 條）**、配額、清理、隔離自檢（**安審 §5**） | ✅ | `internal/runner`（版面／自檢／回收）＋ `internal/gitfetch`（封閉 argv 表）；`daemon/go.mod` 零 diff |
| `AR-07` | `agentd` 0.9.0 的執行面：非互動執行、log 分塊、取消三段 | ✅ | `runtime/run.go` 是新檔，`runtime.go`／`launch.go` 對基線零 diff（`GATE-AR-TOUCH-LIST`）。取消的 process group 測試抓到一個真缺陷，見 §3 第 12 條 |
| `AR-08` | `run_tokens` ＋ `cliora` CLI 0.2.0（**安全審查 §2**） | ✅ | 第二張表 ＋ `AgentPrincipal` 的第二種形狀 ＋ `/api/cli/runs` 三條 ＋ 四個子命令。情境解析一行未改 |
| `AR-09` | 產物：上傳、儲存、配額、安全提供（**安全審查 §4**） | ✅ | 六步接收、三層配額、四個下載標頭、三類預覽白名單。新增一個 runtime 依賴 `python-multipart` |
| `AR-10` | 前端：Agents 頁、**Repository 設定**、派給 Agent、看板徽章 | ✅ | Agents 頁（兩段姿態文案）、Project 設定的 Repository 區（**三個欄位而不是一個網址**）、Task 上的派工 picker（三種等待文案）、導覽項與 `agent_runs` feature、🆕 **磁碟／配額欄與「三種狀態三種文案」（出口條件 21，§3 第 24 條）**。**看板徽章沒做**——卡片上的 run 狀態在 Task 詳情頁上，看板一次要渲染幾十張卡而 run 狀態要另一條查詢 |
| `AR-11` | 前端：Run 詳情、訊息串、產物區 | ✅ | Run 詳情頁（log 輪詢、git 摘要、產物區、取消）＋ 卡片上的訊息串與產物區（`TaskAgentPanel`，三種來源混排、提問時說明「正在等你的回覆」） |
| `AR-12` | 驗證、證據、安全審查定稿、release note | ◐ | 七個 gate ＋ 判準 14 的兩個機器斷言全綠（`scripts/ar/gates.sh`）；`docs/security-review-v22.md` 五節；`docs/release-note-agent-runner.md`。🆕 第二輪補上 **`GATE-AR-DISPATCH-COVERAGE`** 與四支後端測試檔（見 §3 第 14–18 條）。**traceability 仍是 `proposed`**，理由見 §3 第 13 條；**四項量測與 Traqora 實跑仍待人工**（§4） |
| — | **合併提案** | ⬜ **待人工** | 條件全綠只是取得提案資格，不是核准 |

### 1.1 `AR-00` 的六份基線（2026-08-11 擷取）

一律在 `artifacts/ar/local/baseline/`，全部取自 **`dc61006`**（§3 第 1 條解釋為什麼不是 `3c8760d`）。

| 檔案 | 內容 | 重擷取／比對指令 |
|---|---|---|
| `COMMIT` | `dc61006…` ＋ `2026-08-11T10:59:22+00:00` ＋擷取當下未提交的路徑清單（只有 `scripts/ar/`，即擷取器本身） | `scripts/ar/capture-baseline.sh` |
| `openapi-flags-off.json` | 283 039 bytes。`CLIORA_PROJECTS_ENABLED=false CLIORA_AGENT_RUNS_ENABLED=false` | 同上 |
| `openapi-flags-on.json` | **與 flags-off 逐位元組相同**（`cmp` 綠）。這個「相同」本身是要守的性質，見 §3 第 2 條 | 同上 |
| `schema.txt` | 28 張表，`alembic revision: 0028_node_removal_sessions` | `scripts/pj/schema_snapshot.py --diff` |
| `contract-fixtures.txt` | **110 行** ＝ 46 valid ＋ 63 invalid ＋ `manifest.json`。計畫 `01-…md` §1 寫的「109 個檔」不含 manifest，兩者一致 | `scripts/tk/contract_snapshot.py --diff` |
| `frontend-routes.txt` | 17 條路由（含 2 條 redirect、1 條 `[dev-only build]` 的 `/poc/tokens`） | `scripts/ar/frontend_routes.py --diff` |
| `terminal-latency.json` | 50 samples：**p50 0.274 ms／p95 0.980 ms**（min 0.209／max 1.489／mean 0.378），fakecli via tmux | `scripts/e2e/run-stack.sh scripts/ar/capture-baseline.sh --latency-only` |

`terminal-latency.json` 是本期新加的那一份，它服務的是 `00-…md` §5 的
「run log 不得讓互動終端變頓」——`AR-07` 要在同一台 node 上讓一個 run 全速輸出時重量一次，
判準是 **p95 不比 0.980 ms 高 20% 以上**。

四項擋波次 3 的量測見下一節。

### 1.2 `AR-00` 的四項量測（2026-08-11）

| 量測 | 狀態 | 一句話結論 | 原始資料 |
|---|---|---|---|
| **M11** clone／worktree 耗時 | ✅ **已量**（**不在 Traqora 上**，見下） | **mirror 每次 run 只省 1.5 秒**，而它的成本幾乎全在 `remote update --prune` 的空跑（一次網路往返，2.40 s）。**在這個量級上淺 clone 就夠了** | `m11-network.json`、`m11-m12.json` |
| **M12** run 目錄大小 | ✅ **已量** | checkout 是 **17 MB**，但 `node_modules` ＋ `.venv` 是 **552 MB**——**配額的量級是 GB 不是 MB**。建議 `run_quota_bytes=2 GB`／`total_quota_bytes=8 GB` | 同上 |
| **M-AR-9** 事件間隔 | ◐ **部分**：中段量到了，**尾巴沒有** | 量到的最大合法間隔 13.75 s，**300 s 沒有被否定**；但這批資料裡沒有任何長工具呼叫，而尾巴就是從那裡來的 | `m-ar-9-*.json` |
| **M-AR-2** log 速率 | ⬜ **未做** | 它要改 `daemon/cmd/fakecli`，而**閘門二在 ADR 核准前禁止動 `daemon/`**。排在核准之後、`AR-07` 之前 | — |

**M11／M12 的兩個限制要記著**：① 這台機器上沒有 Traqora 的 clone，量的是
`cliora`（量級相當）、`parksphere`、`Monstrare`；② 配額建議值的 5 倍餘裕是判斷不是量測。
逐項數字與判讀見 [`10-open-measurements.md`](./10-open-measurements.md) §1.2／§1.3／§1.5。

**M-AR-9 沒量到尾巴的原因本身是一個發現**，而且它比原本要量的東西更要緊：
`claude -p` 在**預設權限下會擋掉 `Bash`，而 run 不會失敗**——
它以 `result/success` 結束，交出一份沒有真的跑過測試就寫出來的報告。
所以「`--permission-mode` 用哪個值」不是一個調校問題而是一個**正確性問題**
（`10-…md` §1.5 的第 1 點）。

## 2. 出口條件

24 條（上游改寫後的 23 ＋ 本計畫加的效能條件），逐條見
[`08-verification-and-exit.md`](./08-verification-and-exit.md) §5。
實作開始後把該表複製到這裡並逐條填狀態與證據。

## 3. 實作中發現、與計畫不同的事

沿用 `plan/17/09` §3 的形式：計畫寫的／實際做的／為什麼。

1. **基線點是 `dc61006` 而不是 `3c8760d`。**
   計畫寫 `3c8760d`（`01-…md` §1），但同一節也寫了「若開工前 `v2` 又前進了，
   **以實際擷取當下的 HEAD 為準並更新這一行**」——而 `v2` 已經前進到 `dc61006`
   （就是把本目錄寫進 repo 的那一個 commit）。
   `git diff --stat 3c8760d dc61006` 只動到 `plan/` 與 `research/`，
   **六份基線量到的五個面（OpenAPI、schema、contract fixtures、前端路由、終端延遲）
   在兩個 commit 之間逐位元組相同**，所以這是換一個更誠實的錨點而不是換一個基線。
   `01-…md` §1 的那一行已同步更新。

2. **`openapi-flags-off.json` 與 `openapi-flags-on.json` 目前相同，而那是要守的性質。**
   計畫要求「兩個旗標都關閉時 dump 一次、都開啟時再 dump 一次（兩份）」，
   預期它們會不同。實際上每一個 V2／V2.1 的 router 都是**無條件掛載**、
   靠 `require_projects_enabled` 這個 dependency 在執行期回 404
   （`api/http/projects.py:4` 的 docstring 寫得很明白），
   所以旗標是執行期的拒絕而不是 schema 的差異。
   **`AR-04` 必須沿用同一個形狀**：新端點也無條件掛載、靠 dependency 拒絕。
   否則「API 表面沒有變」在本期之後會變成一句要先問「哪個部署」的話。
   擷取腳本會 `cmp` 這兩份並在不同時印一行提醒。

3. **`scripts/ar/frontend_routes.py` 用靜態抽取而不是 import 那個模組。**
   計畫只寫「從 `frontend/src/router/index.ts` 抽出 `path`／`name`／`component` 三欄」。
   import 需要整條 Vite graph（vue-router、Pinia、每一個 view），
   而一個只能在 app 的 build 裡跑的快照工具，會為了與它量的東西無關的理由紅掉。
   代價是抽取器看得懂的形狀是有限的，**所以它用「檔案裡的 `path:` 個數必須等於解析到的筆數」
   當自我檢查**——判準 14 是一個否定命題，而「少列了一條」正是那種會讓否定命題
   悄悄變成假的失敗。

4. **量終端延遲要先等畫面靜下來。**
   第一次實作在看到 `FAKECLI_READY` 之後就送第一個 marker，結果是 30 秒逾時而不是一個延遲值：
   那一行是在 tmux 畫完 alternate screen、daemon 送出第一次 resize **之前**印的，
   送進那個窗口的按鍵會直接消失。改成「等輸出靜止 0.5 秒 → 花一次不計入的暖身往返
   → 才開始計時 50 次」。**這件事對 `AR-07` 的重量有直接影響**：
   同一個窗口在有 run 在跑的時候只會更長。

5. **紅線 4 的措辭修訂已經做完了，`AR-01` 不需要再做一次。**
   `00-…md` §5 的風險表寫「`AR-01` 要一起改 `research/02/00` §7 紅線 4 的第 1、2 條」，
   但 `01-…md` §4b 第 4 點寫「`research/02/00` §7 已於同日改好」。
   **實際檢查的結果是後者對**：`research/02/00` §7 的第 1、2 條主詞已經是
   「平台代表卡片執行的 push」，而且帶著一段「2026-08-10 裁決衍生、2026-08-11 核准的修訂」
   的說明。`AR-01` 做的是**引用它**（ADR 0031 §5「紅線措辭」那一段），不是再改一次。

6. **三份 ADR 一開始是 `proposed` 而不是 `accepted`，2026-08-11 才由人翻成 `accepted`。**
   計畫沒有指定，而既有的 ADR 0027／0028 都是 `accepted`。
   選 `proposed` 的理由是閘門本身：`00-…md` §4 的閘門二與閘門三寫的是
   「**核准前**不得動 `backend/`／`frontend/`／`daemon/`／`contracts/`」，
   而核准是一個人的動作。一份自己把自己標成 accepted 的 ADR 會讓那兩道閘門失去意義。
   每一份的 Status 段都寫明它在等哪一道閘門。

7. **`research/02/11` 有兩處在 2026-08-11 之後就不準確了，一併改掉。**
   ① FR-AGENT-003 寫「**五**條件資格判定」——裁決把綁定與 label 移到 V2.3 之後是四條件；
   ② FR-AGENT-012 寫「**clone 後移除 `origin`**」——第二次裁決撤回了那個作法。
   兩處都是上游 2026-08-10 回寫時漏掉的格子（`01-…md` §5.4 的表列了九份檔案，
   而這兩格在其中一份裡）。**PRD §8.13 的 AC 依裁決寫，不依那兩格。**

8. **三個 SCOPE 守衛在本期改寫，而不是刪掉。**
   `test_scope_014_dispatch_is_pull_based.py` 的
   `test_central_holds_no_runner_registry_yet` 是一個**刻意的 tripwire**——
   它的 docstring 自己寫「V2.2 加進來時這條會紅，並強迫另外三條被看過」。
   照做了：它換成那張表必須保持的性質（**runner 的列說一台機器能做什麼，
   永不說它被指派了什麼**），另加一條 `ast` 斷言 `services/runs.py` 不呼叫
   `registry.request/send_*`——那同時是死鎖守衛。
   `SCOPE-001` 的字串 `agent` 換成結構斷言（`RunLogLineDTO` 只有四個欄位）；
   `SCOPE-005` 的 `dispatch` 換成 `schedule`／`assignment`——非目標是**自動**派工。
   **一條也沒有變寬**，三條都變得更難繞過。

9. **`ast` 而不是 grep。** 第一版的 `GATE-AR-NO-REQUEST-IN-LOOP` 用文字掃描，
   而它掃到的是 `services/runs.py` 自己 docstring 裡「為什麼不可以呼叫 `registry.request()`」
   那一句。改成 `ast.walk` 找 `Call`——一個會找到自己說明文字的守衛，
   會讓下一個人為了讓它綠掉而刪掉那段說明。

10. **`tests/db/conftest.py` 的 `projects_enabled` 現在同時開兩個旗標。**
   V2.2 的路由掛了兩個 guard，而內層那個也回 404。只開外層去量授權，
   會再一次記成「Viewer 被拒絕」而其實量到的是「這條路由不存在」——
   那正是這個 fixture 的 docstring 一開始就在防的事。另新增 `agent_runs_disabled`。

11. **採淺 clone，不做 bare mirror。** `04b-…md` §2 的目錄樹畫的是
    `mirrors/` ＋ `git worktree`，而那是一個**假設 repo 很大**的結論。M11 量完
    （§1.2）：走網路時 mirror 每次 run 只省 1.5 秒，而它的成本幾乎全在一次空跑的
    `remote update --prune`——一次網路往返，與 repo 大小幾乎無關。一層要處理鎖競爭、
    損壞與 30 天清理的快取換 1.5 秒不划算。**這件事會翻轉的兩個條件寫在
    ADR 0031 的 Alternatives 裡**：Traqora 實測大一個數量級，或 run 的頻率高到
    1.5 秒開始重要。`04b-…md` §2 的樹與 §4.2 的第三列因此與實作不符，
    以 ADR 0031 與本節為準。

12. 🔴 **`Cancel` 的第一版有一個真缺陷，是 process group 測試抓到的。**
    原本在 SIGINT 之後等 **leader** 結束就回傳。但 Agent 的 shell 收到 SIGINT 會退出，
    它 background 的子程序不會——留下殘留程序、節點的容量計算是錯的，
    **而且看起來一切正常**。改成等整個 group 空掉再無條件 SIGKILL。
    掃 `/proc` 第 5 欄的那條測試就是出口條件 11 的機器形式。

13. **`traceability/requirements.json` 的 12 筆維持 `proposed`，沒有翻成 `active`。**
    計畫的 `AR-12` 寫「翻 `active`」，但翻過去之後 coverage 會要求 58 個 AC 各自有
    `implemented_by`／`verified_by`／`specified_by`／`planned_by` 的連結，
    **而其中有幾條 AC 在本機根本驗不了**：`FR-AGENT-012.AC-04`（缺憑證秒級失敗）是
    `measurement`，`FR-AGENT-011.AC-07`（使用者 workspace 全程未被碰）要一次真的
    端到端 run。補一批指向不存在證據的連結，比留在 `proposed` 糟得多——
    **翻 `active` 應該與出口條件 9（Traqora 實跑）同時發生**，而那是 §4 的人工事項。

14. 🔴 **一個會讓 ssh repo 完全不能用的缺陷，是自己的測試抓到的。**
    contract、Go 與 TypeScript 三邊的 URL 規則原本都寫成「不得有 `@`」，
    但 Central 對 ssh repo 產生的正是 `ssh://git@host/path`——那條規則會讓 ssh 這條
    路徑永遠取不到程式碼。改成只接受字面的 `git@` 而且只在 ssh 上：
    真正要不可表示的是**密碼**（冒號那一半），因為那才是會出現在 `git remote -v`、
    reflog 與錯誤訊息裡的東西。

15. 🔴 **三個 gate 的第一版都掃到了自己的說明文字。**
    `runs.py` 的 docstring 解釋「為什麼不可以呼叫 `registry.request()`」與
    「為什麼不 import `authorize_workspace`」，而 `uploaded_by_runner_id=` 裡面
    有 `runner_id=`。**一個會找到自己說明的守衛比沒有守衛更糟**——讓它變綠最便宜的
    做法是刪掉那段寫著規則為什麼存在的文字。三個都改用 `ast`
    （`scripts/ar/gate_run_invariants.py`）。

16. **`claude -p` 的預設權限會擋掉 Bash，而 run 仍然報成功。**
    見 §1.2。`permissionArgs` 因此是 `runtime/run.go` 裡的第二張封閉表，
    而不是一個可選的調校項。

17. 🔴 **`runner.register` 的 `runtimes` 送成 `null`，而 Central 靜默丟掉那個訊框。**
    第一次真的把服務跑起來時發現的：daemon 的 log 說「runner mode enabled」與
    「registered with central」，`nodes.agent_runner` 也是 `true`，但
    `agent_runners` 是空的、`/api/agents` 回 `[]`，**而且沒有任何一端報錯**。
    原因是 Go 的 nil slice 序列化成 `null`，而 contract 說 `runtimes` 是 array，
    所以 `decode_control` 拋 `ProtocolError`、`node_gateway` 的 `except` 把它吞掉。
    **這正是 D2 描述的那個症狀**：「訊息不見了但沒有錯誤」。
    而且空集合在這裡不是邊界情況而是設計本身——CLI 太舊的 node 就是要以
    `runtimes: []` 註冊成功。修法是讓那兩個欄位永不為 nil，並補一條測試：
    把 payload 組出來、`BuildControl` 之後跑 `ValidateControl`。
    **順帶暴露一件事**：daemon 不驗證自己送出的訊框，只驗收到的。

18. **`TaskDetail.vue` 的「執行設定」說明在 V2.2 之後過期了。**
    V2.1 寫的是「本階段沒有任何執行者會依它行動」，而 `source` 的三個值與
    `delivery` 的兩個值現在真的會被依循（ADR 0029 §6）。
    一句過期的「沒有人會照做」比沒有說明更糟。

19. **`scripts/ar/dev-stack.sh`：把整個 V2.2 stack 跑起來的那一支。**
    `scripts/e2e/run-stack.sh` 兩個旗標都關、而且 `enroll-dev` 產生的設定裡
    `runner.enabled` 是 `false`（那是對的：一台機器不該因為被納管或升級就開始
    無人值守地跑東西），所以那支腳本開不出一個 runner。這一支是 V2.2 的形狀。
    **`enroll-dev` 會序列化整個 config struct**，所以 `runner:` 區塊已經存在——
    在後面再 append 一段是重複的 key，daemon 會拒絕啟動。要就地改寫。

20. 🔴 **出口條件 18 的實作是死的：`git diff` 從來沒有被上傳過。**
    `SummaryText()` 與 `ShouldAttachDiff()` 都在，摘要也真的會說「diff 已附為產物」，
    **但沒有任何程式碼把它送出去**——`delivery: none` 的卡片跑完之後，
    使用者看到一句說產物在那裡的摘要，和一個空的產物區。
    補上 `internal/runner/upload.go`（HTTP multipart、帶 run 憑證、`sha256` 一起送）
    並在 `executeRun` 接上；上傳失敗時摘要改口說「⚠ diff 未能附加」，
    因為一句錯的「已附上」比一句「沒附上」難查得多。

21. 🔴 **每一個乾淨結束的 run，它的 `run.complete` 都會被靜默丟掉。**
    daemon 送的是 `"summary": ""`，而 contract 寫 `minLength: 1`——
    `decode_control` 丟例外、WS 迴圈的 `except` 吞掉，run 就一路掛到租約過期變成 `lost`。
    **這是第 17 條的同一類缺陷**（`runtimes: null`），而它是被為了抓那一類而寫的
    gate 抓到的，不是被人看到的。修法是 `send` 在送出前把空字串的 optional 欄位拿掉。

22. **`GATE-AR-DISPATCH-COVERAGE`（`backend/tests/test_run_dispatch_coverage.py`）。**
    第 17 條發生時缺的就是這一條。它做兩件事：① 用 `ast` 取出 `nodes.py` 真正比對過的
    型別，對照 contract 的 `run.*`／`runner.*` 清單；
    ② 把 daemon 會組出來的每一種 payload **餵進真正的 `decode_control`**。
    第二半才是抓到第 21 條的那一半——第一半在那個缺陷下是綠的，因為型別有分支，
    錯的是 JSON。

23. **產物的兩個小缺陷。** ① `artifact.attached` 的 activity payload 帶了 `filename`，
    而 `filename` 在 `FORBIDDEN_METADATA_KEYS` 裡——時間軸是全專案每個角色都讀得到的
    feed。改成 `artifact_id`／`size`／`content_type`。
    ② `text/markdown` 不在 `PREVIEWABLE` 裡，但計畫寫 markdown 以純文字預覽（判準 16）。

24. 🔴 **出口條件 21 整條沒有實作，而且它的入口是死程式碼。**
    `Runner.BlockedReason()` 存在、`pollLoop` 也算出了 `blocked`，
    但 `pollLoop` 只 `slog.Debug` 了一行，從來沒有寫回去；`Runner.Poll()` 與
    `Transport` 介面完全沒有呼叫者（而 `Send` 從未被賦值，真的呼叫會 nil panic）。
    往上也一樣空：heartbeat 沒有這個欄位、`agent_runners` 沒有這幾個欄位、
    Agents 頁只有「線上／離線」兩種字。
    **後果是這一頁會把一台磁碟滿了的健康機器顯示成「離線」**，
    而讀的人會去查網路。本輪補齊：
    - migration `0032_runner_pressure`（四個 nullable 欄位，不 backfill）；
    - contract：`node.heartbeat` 多一個 optional `runner`（三個語言各自驗，＋3 個 fixture）；
    - daemon：`Runner.Pressure()`（**即時算，不快取**——快取的理由會剛好在有人盯著頁面的
      那段時間過期），並刪掉 `Poll`／`Transport`／`blocked` 這組死程式碼；
    - Central：`RunnerService.record_pressure()`，**會清掉**已恢復的原因
      （只寫非空值的版本會讓三月滿過磁碟的 runner 在六月還顯示「磁碟用盡」）；
    - 前端：四種原因四句話 ＋「用量未回報」，`AgentsView.test.ts` 七條。
    同時補上計畫點名、最容易漏的另一個數字：**指定給此 Agent 的卡片數**
    （`assigned_cards`，一條 group by，不是每列一次查詢）。

25. **本輪補上的測試（第二版把 `AR-12` 記成 ✅ 時，這些一條都沒有）。**
    `backend/tests/db/test_agent_api.py`（24 條：dispatch 的九種拒絕、兩種等待理由、
    repository 驗證、產物標頭／預覽／摘要／刪除／存活、專案配額 413 且**沒有寫入半筆**、
    run 產物件數上限、**run 全程 `terminal_sessions` 列數不變**＝判準 16）、
    `test_run_reaper.py`（6 條，含 14d）、`test_run_credential.py`（8 條）、
    `test_run_log_buffer.py`（6 條，含**截斷不切斷一行 JSON**＝判準 14）、
    `daemon/internal/gitfetch`（**Agent 在 run 目錄裡 `git push` 到 scratch 遠端會成功**
    ＝判準 9 的那一條；它的存在本身就是裁決的紀錄）、
    `daemon/internal/runner/pressure_test.go`（3 條）。

**另外，已知會需要回填的五處**（編號獨立於上面二十五條）：

1. ~~`runArgs` 表~~ **已於 2026-08-10 量出並填入**（`10-…md` M-AR-1）：
   `claude: ["-p"]`、`codex: ["exec"]`，兩支都從 stdin 收 prompt，**D7 成立**。
   殘留兩項：① `claude` 的 `--permission-mode` 要用哪個值（`04-…md` §5.4）
   ——**2026-08-11 升級為正確性問題**：預設權限下 `Bash` 被擋，而 run 仍以
   `result/success` 結束並交出一份沒有執行過的報告（`10-…md` §1.5 第 1 點）。
   `BuildRunCommand` 必須帶一個值，**選哪一個仍待一次可無人值守執行的機器上驗**；
   ② **`RunCapable` 的快取要做成「一次連線」而不是
   「一個行程」**（`04-…md` §5.3）——既有的 `bypassProbe` 是後者，而重連並不重探，
   對「能不能領卡」而言那個過期是難查的。
2. `00-…md` D3 的兩個常數（chunk 32 KiB、聚合窗 2 秒）——M-AR-2 量完可能要調。
   **M-AR-2 要改 `daemon/cmd/fakecli`，所以它排在 ADR 核准之後**（閘門二）。
3. ~~🆕 `runner.run_quota_bytes` 與 `runner.total_quota_bytes` 的預設值~~
   **M12 已量（§1.2）。建議值 2 GB／8 GB，`min_free_bytes` 沿用 512 MB。**
   建議而非定案的理由：5 倍餘裕是從一個 repo 的建置產物外推的判斷，不是量測。
4. 🆕 **`runner.idle_timeout_seconds` 的值**——M-AR-9 量到中段但**沒量到尾巴**
   （`10-…md` §1.5）。已量到的最大合法間隔 13.75 s，**300 s 沒有被否定，維持不變**，
   在 `AR-07` 的第一次真實 run 上補量。**在量到之前不要調小**：
   誤殺一個正在工作的 Agent 會重排，所以誤殺一次通常是誤殺三次。
   附帶量到的一條：**兩支 CLI 的事件粒度不同**——`claude` 思考時持續吐事件，
   `codex` 在一次工具呼叫期間完全安靜。所以 idle timeout 要蓋的是
   「最長的單一工具呼叫」而不是「最長的思考」。
4b. 🆕 **mirror 還是淺 clone**——M11 量完（§1.2），**答案偏向淺 clone**：
   mirror 每次 run 只省 1.5 秒，而它要付一整層 `mirrors/` 的鎖競爭、損壞處理與 30 天清理。
   **這件事要在 `AR-07b` 開工前決定**，因為它會改 `04b-…md` §2 的目錄樹與 §4.2 的清理表。
5. 🆕 **`codex exec -s workspace-write` 實際擋得住什麼** ——它在 codex 這條路徑上
   是否真的讓 run 讀不到 allowed root（landlock 的實際範圍）。
   若是，`04b-…md` §3.4 的第 3 點可以從「附帶好處」升級成「codex 路徑的保證」。
   **這要一次真的 run 才知道，不能從 `--help` 讀出來。**

## 4. 尚待人工完成的事

**程式與文件已完成；下面五件都需要人。**

0. **看板上的 run 徽章沒做。** 卡片的 run 狀態在 Task 詳情頁上看得到；
   看板一次要渲染幾十張卡，而 run 狀態需要另一條查詢，所以那是一個要先決定
   「board 回應要不要帶 run 狀態」的設計問題，不是一個補一個元件的問題。
   本期的其餘實作都已完成。

1. **合併提案。** `v2` → `dev` 一律由人決定（`research/02/10` §7）。
2. **出口條件在 Traqora 上實跑一次**（D30 的階段表）。
   🆕 **裁決之後正式 repo 可以了**：run 拉的是自己的 clone、不 push、`origin` 還被移掉了，
   對正式 repo 的影響是零。**第一次仍建議先用 scratch clone 走一遍**，
   確認配額與清理之後再對正式 repo 跑。
   （原本這條寫「不得用正式 repo」，理由是 run 沒有隔離——那個前提被裁決移除了。）
3. **`agentd` 0.9.0 的發布時機。** 出口全綠不代表要推給所有 node；
   `node_update` 是既有的分批機制，本期不改它、也不自動觸發它。

4. **翻 traceability 的 `lifecycle`。** 與第 2 條同時做（§3 第 13 條的理由）。

5. **四項未做的量測**：`M-AR-2`（log 速率）、`M-AR-9` 的尾巴、
   `claude --permission-mode` 的實際語意、`codex exec -s workspace-write` 的
   landlock 實際範圍。前兩項要一台可以無人值守執行的機器，後兩項要一次真的 run。

## 5. 第一次把整個服務跑起來（2026-08-11）

`scripts/ar/dev-stack.sh`：Central（兩個旗標都開）＋ 一台真的 enroll 過的 runner node
＋ Vite dev server。**端到端跑通了一次完整的派工**：

| 步驟 | 結果 |
|---|---|
| `runner.register` | `agent_runners` 一列，`runtimes: []`（fakecli 不是 runner-capable，這是對的）、`dedicated: false`（混合用途，Agents 頁顯示 ⚠） |
| 登記 repository | 三個欄位；`evil.example` 回 `REPOSITORY_HOST_NOT_ALLOWED`；只帶 `url` 的 body 回 **422**（那個欄位不存在） |
| dispatch | `202` ＋ `waiting_reason: "any"` |
| runner poll → 原子認領 | run 進 `claimed`，`activity` 上有 `run.dispatched`（人）→ `run.claimed`（agent） |
| run 目錄 | `<runs>/<run_id>/{repo,.cliora,artifacts}`，0700 |
| clone | Traqora 是私有 repo 且這台機器沒有憑證 → **`RUN_SOURCE_UNAVAILABLE`，queued 到 finished 共 2.7 秒** |
| 使用者的 workspace | 全程未被碰 |

**那 2.7 秒就是出口條件 9**（「缺 git 憑證時 clone 秒級失敗」，而不是掛到六小時的
牆鐘）。三個 fail-fast 環境變數是它成立的原因，而 idle timer 救不了這一種——
clone 發生在 `run.accept` 之前，還沒有事件流可以量。

**還沒有跑到的**：一次成功的 run。這台機器上 `runtime.claude` 指向 `fakecli`，
而 `fakecli` 不接受 `-p`，所以 `runtimes` 是空的——那正是設計要的回報。
要看到 Agent 真的做事，需要一台裝了真 CLI、而且該 repo 拉得下來的機器
（＝出口條件 9 的 Traqora 實跑，§4 第 2 條）。

## 5. 環境事實

| 事實 | 值 |
|---|---|
| 工具鏈不在預設 PATH 上 | `export PATH="$HOME/.local/bin:/usr/local/go/bin:$HOME/.nvm/versions/node/v22.23.2/bin:$PATH"` |
| DB 測試要**兩個**環境變數 | `CLIORA_TEST_DATABASE_URL` ＋ `CLIORA_DATABASE_URL`（少了後者，三條 audit 測試會無故失敗） |
| **`claude` 與 `codex` 都裝了，但不在預設 PATH 上** | `~/.local/bin/{claude,codex}`（symlink）。`which claude` 在預設 PATH 下是空的——**這正是上一列那個陷阱的第二個受害者**。M-AR-1 已於 2026-08-10 量完（`10-…md`） |
| 🆕 **`git` 是 runner 模式的新前置條件** | daemon 用 `git` 執行檔而不是 Go library（`04b-…md` §5.1）。`agentd doctor` 要檢查它 |
| 🆕 **e2e stack 要一個乾淨的資料庫** | `cliora_e2e` 裡留著 2026-08-08 那次跑剩的 **46 個 `running` session**，而每人的 session 上限比那個小——`POST /api/sessions` 會回 `409 SESSION_LIMIT_REACHED`，而那個訊息看起來像容量問題不像垃圾。基線用的是另建的 `cliora_ar_baseline`：`CLIORA_DATABASE_URL=postgresql+asyncpg://cliora:cliora@127.0.0.1:5432/cliora_ar_baseline` |
| 本期開始時的基線 | **commit `dc61006`**（計畫原寫 `3c8760d`，見 §3 第 1 條）、contract **v1.10.0**、`agentd` **0.8.0**、migration 到 **0028**、RBAC **20** 個動作、`contracts/v1/fixtures/` **109** 個檔（`contract-fixtures.txt` 110 行，多的是 `manifest.json`） |
| 本期結束時的基線（目標） | contract **v1.11.0**、`agentd` **0.9.0**、migration 到 **0032**、RBAC **24** 個動作、導覽**每個角色各多一項 Agents**（`07-…md` §1）、systemd unit 多一行 `StateDirectory=agentd` |
