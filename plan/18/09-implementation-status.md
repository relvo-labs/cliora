# 09 — 實作進度與證據

本檔隨實作更新；「證據」欄只填**實際跑過的指令與其輸出位置**，不填計畫中的測試。

最後更新 **2026-08-10**：**計畫已依當日裁決改寫，尚未開工。**
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
| **擋開工** | **無。** 基線點（`3c8760d`）、紅線措辭、成本上限三項均已裁決 |
| **擋波次 3**（`AR-07`／`AR-07b`） | 四項量測：**M-AR-9**（事件間隔的尾巴 → `idle_timeout_seconds`）、**M11**（clone／worktree 耗時 ＋ 淺 clone 對照）、**M12**（run 目錄大小）、**M-AR-2**（log 速率 ＋ JSONL 倍數 ＋ 終端延遲基線）。都需要一台裝了兩支 CLI ＋ 有 Traqora clone 的機器 |
| **排在 `AR-07` 第一件事** | 兩項要一次真的 run 才知道：`claude --permission-mode dontAsk` 的語意、`codex exec -s workspace-write` 的 landlock 實際範圍 |
| **V2.3 開工前** | `isolate_ambient_credentials` 的**值**（形狀已定：預設取代、可關成疊加）。M-AR-6 會影響它 |
| **人工、與設計無關** | `plan/17` 的合併提案、出口條件 9 在 Traqora 實跑、`agentd` 0.8.0 的發布時機 |

**波次 0–2（`AR-00` 到 `AR-05`）現在沒有任何未決事項擋著。**
量測擋的是節點半，不是閘門票、ADR、資料層、API 與佇列。

## 1. Ticket 狀態

| Ticket | 標題 | 狀態 | 證據 |
|---|---|---|---|
| `AR-00` | 基線擷取（**基線點 `3c8760d`**）＋ **M-AR-1（已量）／M-AR-2／M11／M12／M-AR-9** | ◐ **M-AR-1 已量** | 基線六份待取（含 `COMMIT`）；M-AR-1 的答案見 `10-…md` §1.1（claude 2.1.226 ＋ codex-cli 0.146.0 的 `--help` 原始輸出，含 2026-08-11 補量的事件流旗標） |
| `AR-01` | ADR 0029、PRD §8.13、skill、traceability | ⬜ | |
| `AR-02` | ADR 0030（log 與產物的兩種保留期） | ⬜ | |
| `AR-02b` | 🆕 ADR 0031（隔離目錄 ＋ git 取得 ＋ Agent 的 git 自由）**＋ 紅線 4 措辭修訂** | ⬜ | |
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

## 2. 出口條件

24 條（上游改寫後的 23 ＋ 本計畫加的效能條件），逐條見
[`08-verification-and-exit.md`](./08-verification-and-exit.md) §5。
實作開始後把該表複製到這裡並逐條填狀態與證據。

## 3. 實作中發現、與計畫不同的事

（實作時填寫。沿用 `plan/17/09` §3 的形式：三欄——計畫寫的／實際做的／為什麼。）

**已知會需要回填的三處**：

1. ~~`runArgs` 表~~ **已於 2026-08-10 量出並填入**（`10-…md` M-AR-1）：
   `claude: ["-p"]`、`codex: ["exec"]`，兩支都從 stdin 收 prompt，**D7 成立**。
   殘留兩項：① `claude` 的 `--permission-mode` 要用哪個值（`04-…md` §5.4），
   那要一次真的 run 才知道；② **`RunCapable` 的快取要做成「一次連線」而不是
   「一個行程」**（`04-…md` §5.3）——既有的 `bypassProbe` 是後者，而重連並不重探，
   對「能不能領卡」而言那個過期是難查的。
2. `00-…md` D3 的兩個常數（chunk 32 KiB、聚合窗 2 秒）——M-AR-2 量完可能要調。
3. 🆕 `runner.run_quota_bytes` 與 `runner.total_quota_bytes` 的預設值——
   M12 量完才填（`04b-…md` §4.1）。
4. 🆕 **`runner.idle_timeout_seconds` 的值**——M-AR-9 量完事件間隔的尾巴才填
   （`10-…md` §1.5）。**在量到之前不要調小**：誤殺一個正在工作的 Agent 會重排，
   所以誤殺一次通常是誤殺三次。
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
| 本期開始時的基線 | **commit `3c8760d`**、contract **v1.10.0**、`agentd` **0.8.0**、migration 到 **0028**、RBAC **20** 個動作、`contracts/v1/fixtures/` **109** 個檔 |
| 本期結束時的基線（目標） | contract **v1.11.0**、`agentd` **0.9.0**、migration 到 **0031**、RBAC **24** 個動作、導覽**每個角色各多一項 Agents**（`07-…md` §1）、systemd unit 多一行 `StateDirectory=agentd` |
