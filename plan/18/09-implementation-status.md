# 09 — 實作進度與證據

本檔隨實作更新；「證據」欄只填**實際跑過的指令與其輸出位置**，不填計畫中的測試。

最後更新 **2026-08-11**：**波次 0 開工，`AR-00` 的六份基線已擷取。**
（前一版寫「計畫已依 2026-08-10 裁決改寫，尚未開工」。）
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
| `AR-03` | migration `0029`／`0030`／`0031` ＋ 模型 | ⬜ | |
| `AR-04` | RBAC 四動作 ＋ Agents／**Repositories**／Dispatch API（同一個 PR） | ⬜ | |
| `AR-05` | 資格查詢、claim-then-offer、租約 sweep、重排 | ⬜ | |
| `AR-06` | contract v1.11.0 ＋ fixtures | ⬜ | |
| `AR-07b` | 🆕 `StateDirectory`、run 目錄、mirror ＋ worktree、配額、清理、隔離自檢（**安審 §5**） | ⬜ | |
| `AR-07` | `agentd` 0.9.0 的執行面：非互動執行、log 分塊、取消三段 | ⬜ | |
| `AR-08` | `run_tokens` ＋ `cliora` CLI 0.2.0（**安全審查 §2**） | ⬜ | |
| `AR-09` | 產物：上傳、儲存、配額、安全提供（**安全審查 §4**） | ⬜ | |
| `AR-10` | 前端：Agents 頁、**Repository 設定**、派給 Agent、看板徽章 | ⬜ | |
| `AR-11` | 前端：Run 詳情、訊息串、產物區 | ⬜ | |
| `AR-12` | 驗證、證據、安全審查定稿、release note | ⬜ | |
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

**另外，已知會需要回填的五處**（編號獨立於上面七條）：

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

（實作結束後填寫。預期至少三件，沿用前兩期的形狀：）

1. **合併提案。** `v2` → `dev` 一律由人決定（`research/02/10` §7）。
2. **出口條件在 Traqora 上實跑一次**（D30 的階段表）。
   🆕 **裁決之後正式 repo 可以了**：run 拉的是自己的 clone、不 push、`origin` 還被移掉了，
   對正式 repo 的影響是零。**第一次仍建議先用 scratch clone 走一遍**，
   確認配額與清理之後再對正式 repo 跑。
   （原本這條寫「不得用正式 repo」，理由是 run 沒有隔離——那個前提被裁決移除了。）
3. **`agentd` 0.9.0 的發布時機。** 出口全綠不代表要推給所有 node；
   `node_update` 是既有的分批機制，本期不改它、也不自動觸發它。

## 5. 環境事實

| 事實 | 值 |
|---|---|
| 工具鏈不在預設 PATH 上 | `export PATH="$HOME/.local/bin:/usr/local/go/bin:$HOME/.nvm/versions/node/v22.23.2/bin:$PATH"` |
| DB 測試要**兩個**環境變數 | `CLIORA_TEST_DATABASE_URL` ＋ `CLIORA_DATABASE_URL`（少了後者，三條 audit 測試會無故失敗） |
| **`claude` 與 `codex` 都裝了，但不在預設 PATH 上** | `~/.local/bin/{claude,codex}`（symlink）。`which claude` 在預設 PATH 下是空的——**這正是上一列那個陷阱的第二個受害者**。M-AR-1 已於 2026-08-10 量完（`10-…md`） |
| 🆕 **`git` 是 runner 模式的新前置條件** | daemon 用 `git` 執行檔而不是 Go library（`04b-…md` §5.1）。`agentd doctor` 要檢查它 |
| 🆕 **e2e stack 要一個乾淨的資料庫** | `cliora_e2e` 裡留著 2026-08-08 那次跑剩的 **46 個 `running` session**，而每人的 session 上限比那個小——`POST /api/sessions` 會回 `409 SESSION_LIMIT_REACHED`，而那個訊息看起來像容量問題不像垃圾。基線用的是另建的 `cliora_ar_baseline`：`CLIORA_DATABASE_URL=postgresql+asyncpg://cliora:cliora@127.0.0.1:5432/cliora_ar_baseline` |
| 本期開始時的基線 | **commit `dc61006`**（計畫原寫 `3c8760d`，見 §3 第 1 條）、contract **v1.10.0**、`agentd` **0.8.0**、migration 到 **0028**、RBAC **20** 個動作、`contracts/v1/fixtures/` **109** 個檔（`contract-fixtures.txt` 110 行，多的是 `manifest.json`） |
| 本期結束時的基線（目標） | contract **v1.11.0**、`agentd` **0.9.0**、migration 到 **0031**、RBAC **24** 個動作、導覽**每個角色各多一項 Agents**（`07-…md` §1）、systemd unit 多一行 `StateDirectory=agentd` |
