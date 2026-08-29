# 10 — 驗證、出口條件與安全審查

## 1. 驗證原則

沿用 `research/02/10` 的四條，加上一條新的：

1. 每張 ticket 以「決策 → 契約 → 實作 → 自動測試 → 操作證據」完成。
2. 出口條件是**可執行的斷言**，不是「看起來對」。
3. 未量測的項目**明寫在該階段的 open measurements**，不假裝量過。
4. 安全紅線的驗證用**負面測試**：證明做不到，而不是證明沒做。
5. **（新增）產品體驗的出口條件用時間量測，不用主觀判斷。**
   「更好用」不可驗證；「找到 Waiting for me 的卡片 ≤ 10 秒」可驗證。

## 2. 測試矩陣

### 2.1 Unit

| 分類 | 項目 |
|---|---|
| Conversation | seq 取號併發、cursor 合併、question 狀態轉移、message kind → resume policy、idempotency 衝突判定、kind 舊值讀取映射 |
| Knowledge | authority × freshness rerank、supersede／tombstone 投影、chunk 切分、context budget 優先序、citation 格式 |
| Work | attention 優先序推導（8 種 × 組合）、filter 驗證、group／order 解析、stage → lifecycle 映射、view 權限、visible fields 投影 |
| Rank | 移植自 kintra 的三個不變式、相鄰插入、再平衡不改相對順序 |
| 前端 | URL state 序列化／反序列化、optimistic rollback reducer、query key 穩定性 |

### 2.2 Backend integration

| 分類 | 項目 |
|---|---|
| Conversation | answer＋question close＋turn enqueue 的**原子性**；併發回答同一 question → 一成功一 409；重送同 idempotency key → 1 則訊息 1 個 turn；cursor catch-up；run token 只能讀寫自己的 task／run actor；Agent proposal／answer 進不了 human decision path；Viewer 不可發言 |
| Knowledge | ingest job retry 冪等；source deletion cascade 到 chunks／index／cache；Project ACL 套用於 search／citation／context pack／**counts**；`knowledge_enabled=false` 的行為；authority transition（PR merge、spec accept） |
| Work | filter／group／count 下的 resource-level authorization；personal vs project view ownership；shared default view audit；per-group cursor 分頁；bulk update 交易行為與逐張授權；stale version 409；My Work 跨專案隔離 |
| 相容 | `BoardCardDTO` 與 `/board` 的 OpenAPI diff 為空；`agentd` 0.12.0 未升級節點跑完整 run 生命週期 |

### 2.3 Frontend component

conversation 無限捲動與新訊息合併、composer draft 在 network failure 後保留、
question card 三態、**「留言」與「回覆並繼續」不可混淆**、
八種 attention 的卡片變體、compact／comfortable、
Drawer 開啟／重整／關閉、欄位衝突草稿保留、filter 狀態持久、
move 失敗回滾、**server count vs 已載入卡片數**、
knowledge result 的 citation／authority／version 呈現、
context preview 的 pin／exclude／budget 揭露。

### 2.4 Contract

若 D44 維持「不動」：**`contracts/` 的 diff 必須為空**，並有一個 gate 斷言它。
若改為 1.14.0：新增 fixtures（valid ＋ invalid 各 ≥3），
並新增「未宣告 feature 的節點不會收到新訊息型別」的測試。

## 3. 十六個 E2E 旅程

| # | 旅程 | 里程碑 |
|---|---|---|
| **J1** | **主旅程**：模糊需求 → 三輪對話 → spec proposal → 人類要求修改 → Agent 更新 → 人類接受 → Ready → Agent 引用 knowledge 開工 → 交付 → 驗證 → 人類核准 → Done。**全程不進 Terminal** | `beta.1` |
| J2 | Backlog 建卡 → 補 readiness → 移到 Ready | `beta.1` |
| J3 | Ready 卡被 Agent 認領 → Running → Waiting for input | `alpha.2` |
| J4 | 從 My Work 開 Drawer → 回答指定 question 並繼續 → continuation turn 讀到 answer | `beta.1` |
| J5 | answer commit 後 daemon 斷線／重啟 → 補拉且**只建立一個 turn** | `alpha.2` |
| J6 | 只送 comment → Agent 收到通知但 run **不被誤 resume** | `alpha.2` |
| J7 | Run failure → 顯示原因 → retry，**conversation 保留** | `alpha.2` |
| J8 | 兩個使用者同時回答同一 question → 一成功、一收到可恢復 conflict | `alpha.2` |
| J9 | Agent 嘗試送 decision／approval → server 拒絕並記 audit | `alpha.2` |
| J10 | Board filter → 開 Task → close → **filter／scroll 不變** | `beta.1` |
| J11 | 新 accepted decision／repo doc 進 Knowledge → 新 Agent turn 可引用 | `alpha.3` |
| J12 | repo 文件被更新或刪除 → 舊 chunk 不再被 retrieval 命中 | `alpha.3` |
| J13 | repo 文件內含 prompt injection → 僅作 data，**不提升為 instruction** | `alpha.3` |
| J14 | 無權 Project token 搜尋 knowledge／開 citation → 全部拒絕且 **count 不洩漏** | `alpha.3` |
| J15 | No eligible runner → 顯示缺少 tag → 修正 required labels → 認領成功 | `beta.1` |
| J16 | PX flag off → 舊 Project UI 可用；Projects flag off → V1 行為維持 | `beta.1` |

**J1 是不可降級的那一條。** 其餘任何一條失敗都是 bug；J1 失敗表示這一輪沒有達成目的。

## 4. 四次安全審查

每一次都在該里程碑的 tag 之前，由人執行並具名簽核。

### SR-1（`alpha.2` 前）— Conversation 的 actor 與傳遞邊界

| 審查項 | 通過標準 |
|---|---|
| run token 不能寫 `decision` | 負面測試 ＋ audit 記錄 |
| run token 不能跨 task 讀寫、不能指定 actor | 兩個負面測試 |
| Viewer 不可發言 | 負面測試 |
| comment 不 resume、answer 不 approve | 兩個測試 |
| secret value 不出現在 message、notification、error、telemetry | redaction fixture，沿用既有 runner redaction |
| audit 只記 metadata，不複製 message body | audit payload 斷言 |
| message body 大小上限與附件型別檢查 | 超限回 `MESSAGE_TOO_LARGE` |
| **未升級節點（`agentd` 0.12.0）行為不變** | 完整 run 生命週期 E2E |

### SR-2（`alpha.3` 前）— Knowledge 的隔離與注入

| 審查項 | 通過標準 |
|---|---|
| Project isolation 在 retrieval boundary | ≥8 條 isolation 測試，涵蓋 search／count／citation／context pack／cache |
| 無權查詢不洩漏存在性 | count 為 0，不是 403 |
| secret／credential／敏感檔不進 index | ingestion redaction 測試 |
| prompt injection 不提升為 instruction | J13 |
| 未核准 Agent proposal 不是 authoritative | context pack 結構斷言 |
| 刪除／撤權 cascade tombstone | J12 ＋ Project 刪除測試 |
| **Central 未新增對外連線** | `pyproject.toml` 無新依賴；egress 清單未變 |
| `CREATE EXTENSION pg_trgm` 在兩條部署路徑成功 | compose ＋ Railway 各一次 |

### SR-3（`beta.1` 前）— 讀模型的權限邊界

| 審查項 | 通過標準 |
|---|---|
| counts 與 items 用同一 predicate | 程式碼審查 ＋ inference 測試 |
| filter／group 不繞過授權 | 對每個 allowlist 欄位各一條測試 |
| My Work 跨專案隔離 | ~~無權專案的卡不在 items **也不在 counts**~~ ——**這個系統沒有 per-project membership**，見下 |
| bulk update 逐張授權 | 混合權限的 batch → all-or-nothing 拒絕 |
| view 不改變 Task 權限 | 共用 view 含無權卡 → 該卡不出現 |
| UI 簡化未隱藏安全資訊 | 造成 blocked／warning 的設定自動展開（四種情境） |
| human approval 顯示 actor 與時間 | 視覺 ＋ 元件測試 |
| Agent 仍不可自動核准／合併／部署 | 既有負面測試套組回歸 |

> **第三項改寫過**（2026-08-23，`plan/26`
> [D93](../../plan/26/01-decisions-and-governance.md)）。
> RBAC 是**全域三角色**，而 `_VIEWER_ACTIONS` 就含 `project.view`：
> 拿得到它的人看得到**全部**專案，拿不到的一個都看不到。
> `services/authz.py` 裡沒有任何 project-scope 函式，也沒有 `project_members` 表。
>
> 照字面寫的測試會用一個沒有 `project.view` 的角色去斷言 403 ——
> 那證明的是 `require_action`，與讀模型的查詢邊界無關。
> **一組毫無阻力通過的 isolation 測試比沒有測試更糟**：它讓下一個人以為這件事被守住了。
>
> 改成三條證得出來的：counts 與 items 由**同一個** `ProjectScope` 與同一次 filter
> 編譯產生；`GATE-PX-ONE-PROJECT-SCOPE` 用 AST 斷言沒有第二條路徑；
> inference 測試保留但**誠實命名**
> （`test_a_viewer_without_project_view_sees_no_work_items_and_zero_counts`）。
>
> 證不出來的那一半——「有 membership 時 counts 不洩漏存在性」——
> 寫進 [`plan/26/11`](../../plan/26/11-open-measurements.md) §1，
> 而 SR-3 的簽核文字必須寫明「本部署的模型下無法產生負面案例，守護方式是 gate 而非測試」。

### SR-4（`beta.2` 前）— Provider ingestion 的信任邊界

> **2026-08-28 更新（`plan/27` 的 `HD-00`）**：★ D120 裁決 `beta.2` **只做 pull**，
> 所以下表的前兩項**不存在**（沒有 webhook 就沒有簽章、沒有 delivery id），
> 第三項改寫，並新增三項 pull 特有的。**八項的全文在
> [`plan/27/02`](../../plan/27/02-provider-ingestion.md) §8。**
>
> 原表保留在下面。少掉兩項而不說明為什麼，下一個讀者會以為它們被漏掉了
> ——而簽核文字必須寫明這件事。

| 審查項（原表） | 通過標準 | pull 模型下 |
|---|---|---|
| webhook signature 驗證 | 偽造簽章被拒 | ~~不存在~~ |
| delivery id 去重 | 重送同一 delivery → 一次 ingest | ~~不存在~~——reconcile 每輪重讀 entity 當前狀態，重複是免費的 |
| webhook 不在請求內同步抓 repo 或算 embedding | 程式碼審查 ＋ 回應時間 | **改寫**為 `GATE-HD-NO-PROVIDER-IN-REQUEST`：`api/http/` 下不得 import `provider_reads`。**精神相同而且更強**——原版審查一個行為，這個斷言一個依賴 |
| provider token 的保存、範圍與輪替 | 沿用既有 secret 機制 | **保留** |
| merge 前的 PR 內容不自動成為 policy | authority transition 測試 | **保留**，且變成一個**值域限制**而不是一個流程（D122） |
| — | — | **新增**：撤權 token 不會讓 reconcile 無限重試（J18） |
| — | — | **新增**：`provider_reads.py` 只發 GET（兩個 gate） |
| — | — | **新增**：錯誤 body 不含 token、不進 log／metric label |

## 5. 效能預算

**門檻在 `alpha.1` 的固定資料集上量測後校正，變更必須留紀錄。**
資料集：200 tasks、6 active runs、10 human waits、5 failures、
一個 dependency graph、500 則 conversation message、
一個中型 repo（約 2000 個 tracked 檔、300 個文件檔）。

| 項目 | 目標 | 里程碑 |
|---|---|---:|
| 200 張卡 work-items 初次回應 P95 | < 1s | `beta.1` |
| Board 首次可互動 | < 2s | `beta.1` |
| 打開已快取 Task Drawer | < 150ms 感知 | `beta.1` |
| filter apply | < 300ms 感知 | `beta.1` |
| optimistic move | < 100ms 畫面回應 | `beta.1` |
| My Work counts P95 | < 500ms | `beta.1` |
| Ticket message commit P95 | < 500ms | `alpha.2` |
| **message commit → continuation turn 開始 P95** | **< 10s** | `alpha.2` |
| conversation reopen（最近 50 則）P95 | < 500ms | `alpha.2` |
| Ticket／decision ingest freshness P95 | < 10s | `alpha.3` |
| knowledge search P95 | < 1s | `alpha.3` |
| context pack build P95（index warm） | < 2s | `alpha.3` |
| `WorkItemCardDTO` 200 張 payload | ≤ 160 KB | `beta.1` |

> `< 10s` 是本規劃唯一放寬提案數字的效能目標（提案是 2s），
> 原因與代價寫在 [`01`](./01-architecture-decisions.md) §1.2。若 D44 改為採納通知路徑，
> 這一格回到 < 2s。

## 6. Accessibility

WCAG 2.2 AA 為目標。`beta.1` 的 `HD-04` 執行完整 audit。

全鍵盤操作（建卡、開卡、移動、篩選、回覆）、focus trap／restore、
Drawer aria label 與角色、狀態播報（move、attention 變化）、
DnD 的鍵盤等價路徑、色彩對比、reduced motion、200% zoom。

**所有 attention state 不得只靠顏色。**

## 7. 使用者任務時間

| 任務 | 目標 | 怎麼量 |
|---|---|---|
| 找到 Waiting for me 的卡片 | ≤ 10s | 固定資料集，5 位受測者，從登入起算 |
| 判斷卡片沒被 Runner 認領的原因 | ≤ 15s | 同上 |
| Backlog 建卡並送到 Ready | ≤ 30s | 不含內容撰寫 |
| 從 Board 開卡、回覆、返回 | 不丟失任何 Board state | 客觀斷言（J10） |
| 回答 Agent 並繼續 | 一個 Drawer、一次明確動作 | 客觀斷言 |
| 完成三輪需求釐清 | 不進 Terminal、不重貼背景 | 客觀斷言（J1） |
| 找到失敗 Run 並 retry | ≤ 20s | 量測 |
| 判斷交付能否核准 | 一個 Drawer 內完成 | 客觀斷言 |

`alpha.1` 之後、`beta.1` 之前各量一次（`PX-04` 的基線與收尾）。

## 8. 產品指標（只記 metadata）

Waiting for input 的中位回應時間、human answer → next Agent reply 延遲、
每張 Ticket 的釐清輪數、釐清放棄率、spec proposal → 接受率、
**重複 continuation／重複 Agent 回覆率（目標 0）**、
帶引用的 Agent 回答比率、citation 開啟率、retrieval relevance eval 分數、
**stale／superseded source 被檢索到的比率（目標 0）**、
context 中 authoritative／accepted 來源覆蓋率、knowledge ingest lag、
最舊失敗 job 的年齡、No eligible runner 的中位解決時間、
Backlog → Ready lead time、Ready → Claimed、Review → Done、
run failure retry 率、Drawer 開啟 → 動作完成率、saved view 採用率、每週 My Work 使用率。

**不保存 terminal bytes、secret value、message body 或敏感 prompt 內容。**

## 9. 全期出口條件（`beta.1` 取得合併提案資格的門檻）

| ☐ | # | 條件 |
|---|---:|---|
| ☐ | 1 | 使用者可從 My Work 在 10 秒內找到等待自己處理的卡片 |
| ☐ | 2 | Backlog 與 Active Board 已分離 |
| ☐ | 3 | Board／List 使用同一資料來源與 attention projection |
| ☐ | 4 | Saved personal／project views 權限正確 |
| ☐ | 5 | Task Drawer URL 可重整、分享與返回 |
| ☐ | 6 | 開關 Drawer 不丟失 view、filter 與 scroll |
| ☐ | 7 | 所有 optimistic mutation 失敗都會回滾 |
| ☐ | 8 | 所有移動拒絕提供 machine code 與可行動訊息 |
| ☐ | 9 | Human approval 仍要求 human actor，且 UI 顯示 actor 與時間 |
| ☐ | 10 | Agent token 仍不可進入 human approval path |
| ☐ | 11 | Secret value 不出現在 API、UI、log 或 error |
| ☐ | 12 | Agent Run 與 interactive Session 邊界未改變 |
| ☐ | 13 | V1 terminal、session、workspace 與 file flows 通過回歸 |
| ☐ | 14 | PX feature flag 關閉可回到舊 UI |
| ☐ | 15 | Projects flag 關閉時 V1 行為不變 |
| ☐ | 16 | 200 張卡 performance gate 通過 |
| ☐ | 17 | Keyboard 可完成核心任務 |
| ☐ | 18 | 零 undefined CSS tokens（沿用 `plan/19` 既有 gate） |
| ☐ | 19 | 視覺回歸與 accessibility audit 通過 |
| ☐ | 20 | migration rehearsal 與 rollback drill 完成 |
| ☐ | 21 | release note 列出 known limitations |
| ☐ | 22 | Ticket 內可完成至少三輪 Human–Agent 需求釐清，不進 Terminal |
| ☐ | 23 | 人類 answer 在斷線／重啟後仍會被 continuation 讀取，且只處理一次 |
| ☐ | 24 | comment 不誤 resume、answer 不誤 approve、Agent proposal 不改 human decision |
| ☐ | 25 | Run log 清除或 run attempt 被替換後，conversation、question 與 spec proposal 仍可用 |
| ☐ | 26 | Viewer 不可發言；run token 不能跨 Task 讀寫，也不能冒充 human actor |
| ☐ | 27 | 每個 Agent context pack 都有可查 source manifest、版本、authority 與 budget |
| ☐ | 28 | Ticket、accepted decision、artifact 與 repo 文件能進 Project search，結果可點回來源 |
| ☐ | 29 | superseded／deleted／unauthorized source 不再進預設 retrieval、citation 或 cache |
| ☐ | 30 | 未核准 Agent proposal 與 repo prompt injection 不會成為 authoritative instruction |
| ☐ | 31 | Project Knowledge 查詢與 counts 通過跨 Project isolation tests |
| ☐ | 32 | **`BoardCardDTO` 與 `/board` 未變更**（新舊看板並存） |
| ☐ | 33 | **未升級的 `agentd` 0.12.0 節點行為不變**（若 D44 維持不動 contract） |
| ☐ | 34 | **`v2` → `dev` 仍由人工明確核准，任何自動化不得合併** |

## 10. 未量測項

| # | 項目 | 為什麼現在不量 | 何時量 |
|---|---|---|---|
| 1 | 沒有向量檢索的召回率損失 | D40 已裁決不做；需要真實查詢紀錄才有對照組 | `KN-12` 建立基準值 |
| 2 | attention 即時計算 vs 物化的效能差 | 需要真實資料量 | `PX-24` |
| 3 | 300 行自製 query 層的維護成本 | 需要至少一個 release 的實際使用 | `beta.2` |
| 4 | 真實對話的輪數、放棄率與多人併發頻率 | 需要真實使用者 | `beta.1` 之後 |
| 5 | 大型 monorepo（>50k 檔）的索引時間與體積 | 手上沒有這種 repo | Horizon 2 |
| 6 | chunk 大小與重疊的最佳值 | 需要 relevance eval 基準 | `KN-12` 之後 |
| 7 | 十級 authority 是否過細 | 需要真實使用 | ~~`beta.1`~~ → **`beta.2`**（`plan/26/11` §7） |
| 8 | `cliora task wait` 的 120 秒上限 | 需要真實 Agent 行為 | ~~`beta.1`~~ → **`beta.2`**（`plan/26/11` §8） |
| 9 | poll 5 秒是否需要調短 | 先量 message → turn 的 P95 | `alpha.2` |
