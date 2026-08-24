# 10 — 驗證、Gate、安全審查與出口條件

> **ticket：`PX-65`（安全 ＋ gate ＋ 授權測試）、`PX-66`（旅程 ＋ 量測 ＋ 封版產物）。**
> **兩張而不是一張**——`plan/24` 花了一整期補上一期塞在最後一張 ticket 尾巴的證據。

## 1. 驗證原則

沿用既有五條：

1. 每張 ticket 以「決策 → 契約 → 實作 → 自動測試 → 操作證據」完成。
2. 出口條件是**可執行的斷言**，不是「看起來對」。
3. 未量測的項目**明寫在 [`11`](./11-open-measurements.md)**，不假裝量過。
4. 安全紅線的驗證用**負面測試**：證明做不到，而不是證明沒做。
5. 產品體驗的出口條件用**時間量測**，不用主觀判斷。

加上本期的第六條：

6. **一個沒有 raise 點的 machine code、一個在本部署模型下恆真的測試，
   要在計畫階段就被指名。** `plan/25` §2.12 的 `CROSS_PROJECT_DENIED`
   是實作到一半才發現的；本期在 [D93](./01-decisions-and-governance.md)
   與 [D97](./01-decisions-and-governance.md) 事先處理了兩個同類的東西。

## 2. `scripts/px/`

```text
scripts/px/
  capture-baseline.sh        PX-00：BoardCardDTO bytes、tasks 索引清單、tokens 數、
                             requirements 數、daemon 樹 sha256、contracts 樹 sha256
  gates.sh                   PX-65：九個新 gate ＋ 既有全部重跑
  gate_work_invariants.py     五個 AST gate，共用一個 Python 行程
  seed-queued.py             PX-24：在固定資料集上造 60 個 queued 且無合格 runner 的 run
  measure.py                 PX-66：六項效能量測
  journeys/                  PX-66：六條旅程
    j1_vague_to_done.py  j2_backlog_to_ready.py  j4_mywork_answer.py
    j10_filter_survives.py  j15_no_runner_fixed.py  j16_flag_matrix.py
```

形狀逐一沿用 `scripts/kn/`（`check()` 函式、印出 exemption、
沒有資料庫時**大聲 skip 而不是靜默通過**）。

## 3. 十個新 gate

| Gate | 守什麼 | 違反時會發生什麼（**而且是靜默的**） |
|---|---|---|
| `GATE-PX-NO-DAEMON-DIFF` | `git diff --stat <baseline>..HEAD -- daemon/` 為空 | 本期宣稱「零 daemon diff」，而一個順手的修正會讓「未升級節點行為不變」從恆真變成未驗證的命題 |
| `GATE-PX-CONTRACT-FROZEN` | `contracts/` 全樹 sha256 與基線相同 | 同上，且 1.13.0 的 changelog 已經記過解碼失敗在這條線上是靜默的 |
| `GATE-PX-ONE-PROJECT-SCOPE` | AST：`services/work/` 對 `Task` 的每一條 select 都經 `ProjectScope.predicate()` | [D93](./01-decisions-and-governance.md)。今天掃過就是綠的；per-project ACL 進來的那天，它是唯一擋得住第九個查詢的東西 |
| `GATE-PX-NO-DYNAMIC-SQL` | AST：`services/work/` 無 `text()`、無 f-string 進 `where()`、無 SQL 字串串接 | filter 是使用者輸入。一個字串拼接會通過所有功能測試 |
| `GATE-PX-SINGLE-ATTENTION` | AST：`ATTENTION_ORDER` 只在 `services/work/attention.py` 出現；前端無八級順序的複本 | 前端重建優先序 → 同一張卡在卡片與 Drawer 上顯示不同的 primary |
| `GATE-PX-BOARD-UNCHANGED` | `/board` 的 OpenAPI 片段 diff 為空 **且** `BoardCardDTO` 200 張 = 89,251 ± 2% | [D94](./01-decisions-and-governance.md)。形狀沒變不代表大小沒變 |
| `GATE-PX-MYWORK-READS-STATE` | AST：`api/http/me.py` 與 `services/work/` 不讀任何 `*_read_at` / `*_seen` 欄位 | notification 進來的那天，第一個「已讀就消失」的寫法會在這裡被擋下 |
| `GATE-PX-BULK-USES-UPDATE` | AST：`services/work/` 與 bulk endpoint 內無對 `Task.stage` 的直接賦值或 `update(Task)` 語句 | [D96](./01-decisions-and-governance.md) 的更正發現：`GATE-DV-SINGLE-DONE-PATH` **只 grep `runs.py` 且只禁 `'done'`**，所以 bulk 的繞過**完全沒有 gate 守著** |
| `GATE-PX-MIGRATION-ROUNDTRIP` | `0043` upgrade → downgrade → schema 與基線相同 | 沿用 `scripts/ar/gate-migration-roundtrip.sh`，target `0042_knowledge_tables` |
| `GATE-PX-JOURNEY-COVERAGE` | 六條旅程都跑過、都有 verdict、stamp 的 commit 是 HEAD | **本期最可能的假綠**（`plan/24` 的原話）：六條旅程全部 skip 而套件回報成功 |

`GATE-PX-TOUCH-LIST`（禁區清單，[`00`](./00-execution-plan.md) §3）沿用
`GATE-KN-TOUCH-LIST` 的實作，只換清單。

## 4. 六條旅程（`PX-66`）

上游列了十六條，其中十條屬於 `alpha.2`／`alpha.3` 且已經跑過
（`plan/24` 的七條、`plan/25` 的 J11–J15）。本期新增六條：

| # | 旅程 | 不可降級？ |
|---:|---|---|
| **J1** | **主旅程**：模糊需求 → 三輪對話 → spec proposal → 人類要求修改 → Agent 更新 → 人類接受 → Ready → Agent 引用 knowledge 開工 → 交付 → 驗證 → 人類核准 → Done。**全程不進 Terminal** | **✅ 是** |
| J2 | Backlog 建卡 → 補 readiness → 移到 Ready（含「仍要送到 Ready」的分支） | |
| J4 | 從 My Work 開 Drawer → 回答指定 question 並繼續 → continuation turn 讀到 answer | |
| J10 | Board filter → 開 Task → close → **filter／scroll／view 不變**；browser back 依序關 Drawer → 還原 view → 離開 | |
| J15 | No eligible runner → 顯示缺少 tag → 修正 required labels → 認領成功 | |
| J16 | PX flag off → 舊 Project UI 可用；Projects flag off → V1 行為維持 | |

**J1 是不可降級的那一條。** 其餘任何一條失敗都是 bug；
J1 失敗表示這一輪沒有達成目的。

J1、J4、J15 需要真的 daemon，沿用 [`plan/24/02`](../24/02-e2e-harness.md) 的堆疊。
J2、J10、J16 是瀏覽器層的，用既有 e2e 機制。

**J1 對 knowledge 的依賴**：「Agent 引用 knowledge 開工」那一段需要
`v2.0.0-alpha.3` 已經可用。若 `alpha.3` 的 tag 因故延後，
J1 **不得降級成「跳過引用那一段」**——那會讓這條旅程不再證明本輪的目的。
正確反應是等 `alpha.3` 封版（[`00`](./00-execution-plan.md) §1 的前置條件）。

## 5. 測試矩陣

### 5.1 Unit

| 分類 | 項目 |
|---|---|
| Attention | 八級優先序（8 種單獨 ＋ 12 組組合）；`runtime=None` 時 5／6 **缺席而非 false**；相位 B 與 `resolve_waiting_reason` 對同一 run 一致 |
| 投影 | stage → lifecycle 六格；`blocked` 一律 `is_blocked=true`；`done` 一律 `false`；readiness 三態；`EffectiveProcess` 每 project 只取一次 |
| Filter | 15 欄 × 8 op 的合法組合；六個負面案例；`split_attention_terms` 的四種組合 ＋ 兩種否定；`@me` 展開 |
| Rank | 移植自 kintra 的三個不變式、相鄰插入、`'a0'` 的前驅、再平衡不改相對順序 |
| Cursor | 序列化／反序列化；null 排序鍵的 sentinel；再平衡期間 rank 重複時 `id` 決勝 |
| 前端 | URL state 序列化／反序列化（property 測試）；optimistic rollback reducer；query key 穩定性（property 順序無關） |

### 5.2 Backend integration

| 分類 | 項目 |
|---|---|
| 讀模型 | filter／group／count 下的 resource-level authorization；counts 與 items 集合大小一致；per-group cursor 分頁不重不漏；200 張 ≤ 量測門檻 |
| View | personal vs project ownership；`ck_work_views_scope` 擋掉兩種無意義列；`uq_work_views_default` 擋掉兩個 default；shared default 變更寫 audit；density 不寫；duplicate |
| Bulk | 逐張授權；混權限 batch → all-or-nothing 拒絕且指名哪一張；冪等；audit 一列 ＋ activity N 列；**Done Gate 對 `stage='done'` 的 patch 仍生效** |
| Rank | `RANK_NEIGHBOR_STALE` 三種 reason；跨 group 拖曳是單一請求；backfill 後的順序與 backfill 前相同 |
| My Work | 與 project 端點對同一張卡回相同 `primary_attention`；`ProjectScope` 是同一個實例 |
| 相容 | `BoardCardDTO` OpenAPI diff 為空 ＋ bytes 未變；`agentd` 0.14.1 節點跑完整 run 生命週期 |
| Agent 邊界 | run token 對七個新 endpoint 各一條 403；`is_blocked`／`blocking_reason`／`rank` 的 PATCH → 422 |

### 5.3 Frontend component

八種 attention 的卡片變體 × 兩種密度；「不只靠顏色」（aria-label ＋ icon/shape）；
Drawer 開啟／重整／關閉；欄位衝突**草稿逐字保留**；filter 狀態持久；
move 失敗回滾；**server count vs 已載入卡片數**；
`runtime_signals_available=false` 時 chip 停用與 My Work 第五段的文案；
Ready transition 對話框的每一列可點開並聚焦；
「留言」與「回覆並繼續」**不可混淆**；`agent_seen` tooltip；
raw log 不進 conversation。

### 5.4 Contract

**`contracts/` 的 diff 必須為空**，`GATE-PX-CONTRACT-FROZEN` 斷言。
`daemon/` 的 diff 必須為空，`GATE-PX-NO-DAEMON-DIFF` 斷言。

## 6. SR-3（`beta.1` 前的安全審查）

由人執行並具名簽核。八個審查項，**其中兩項的措辭與上游不同**。

| # | 審查項 | 通過標準 |
|---:|---|---|
| 1 | counts 與 items 用同一 predicate | 程式碼審查 ＋ 兩個 endpoint 對同一 fixture 的集合大小相等 |
| 2 | filter／group 不繞過授權 | 對每個 allowlist 欄位各一條測試（15 條） |
| 3 | **可見專案述詞只有一個來源** ⚠️ **措辭已改** | `GATE-PX-ONE-PROJECT-SCOPE` PASS ＋ 一條「無 `project.view` → items 空、counts 全 0」的測試。**簽核文字必須寫明：本部署無 per-project membership，因此無法產生「有權看 A 專案、無權看 B 專案」的負面案例；守護方式是 gate 而非測試。**（[D93](./01-decisions-and-governance.md)） |
| 4 | bulk update 逐張授權 | 混合權限的 batch → all-or-nothing 拒絕，回應指名哪一張 |
| 5 | view 不改變 Task 權限 | 共用 view 含無權卡 → 該卡不出現；`visible_fields` 不影響集合 |
| 6 | UI 簡化未隱藏安全資訊 | 造成 blocked／warning 的設定自動展開（[`07`](./07-task-drawer.md) §2 的四種情境） |
| 7 | human approval 顯示 actor 與時間 | 視覺 ＋ 元件測試 |
| 8 | Agent 仍不可自動核准／合併／部署 | 既有負面測試套組回歸 ＋ 三個新禁止欄位的負面測試 |
| 9 | **本期未新增對外連線、未新增推播通道** ⚠️ **本計畫新增的一項** | `pyproject.toml` 與 `package.json` 的 dependencies 未變；`grep` 確認前端無新 WebSocket；[D95](./01-decisions-and-governance.md) 的決定被遵守 |

第 9 項是本計畫加的。理由：`beta.1` 最容易在最後一週為了「看板不會自己更新」
而臨時加一條推播，而那會讓 SR-3 的範圍在簽核前一天改變。
**把它寫成審查項，就是在讓那個決定必須被說出口。**

## 7. 效能預算

在 `scripts/cv/seed-dataset.py` 的固定資料集（seed 20260819）上量測。

| 項目 | 目標 | ticket |
|---|---|---|
| 200 張卡 `work-items` 初次回應 P95 | < 1s | `PX-24` |
| **`work-counts` P95** | **< 200ms** | `PX-24`（[D95](./01-decisions-and-governance.md) 讓它每 20 秒被打一次） |
| 相位 B 在 6 queued | 記錄基準 | `PX-24` |
| **相位 B 在 60 queued** | 記錄 | `PX-24`（**證明或推翻 D92 的「成本綁佇列長度」**） |
| bulk update 100 張交易 P95 | < 3s，超過則下修上限 | `PX-25`（[D96](./01-decisions-and-governance.md)） |
| Board 首次可互動 | < 2s | `PX-66` |
| 打開已快取 Task Drawer | < 150ms 感知 | `PX-66` |
| filter apply | < 300ms 感知 | `PX-66` |
| optimistic move | < 100ms 畫面回應 | `PX-66` |
| My Work counts P95 | < 500ms | `PX-66` |
| `WorkItemCardDTO` 200 張 payload | **量測值 ＋15%** | `PX-25`（[D94](./01-decisions-and-governance.md)） |
| `BoardCardDTO` 200 張 payload | **89,251 ± 2%（不得成長）** | `PX-25` |

## 8. 使用者任務時間（`PX-66`）

固定資料集，5 位受測者，從登入起算。
**`alpha.1` 之後、`beta.1` 之前各量一次**——
`research/03/CHECKLIST` §0 的「量測八項基線」若尚未做，
`PX-66` 只能量後測，而那時要在報告裡明說沒有對照組。

| 任務 | 目標 |
|---|---|
| 找到 Waiting for me 的卡片 | ≤ 10s |
| 判斷卡片沒被 Runner 認領的原因 | ≤ 15s |
| Backlog 建卡並送到 Ready | ≤ 30s（不含內容撰寫） |
| 從 Board 開卡、回覆、返回 | 不丟失任何 Board state（客觀斷言 J10） |
| 回答 Agent 並繼續 | 一個 Drawer、一次明確動作（客觀斷言） |
| 完成三輪需求釐清 | 不進 Terminal、不重貼背景（客觀斷言 J1） |
| 找到失敗 Run 並 retry | ≤ 20s |
| 判斷交付能否核准 | 一個 Drawer 內完成（客觀斷言） |

## 9. Feature flag 矩陣（`PX-66` 驗證三種組合）

**☑ [D117](./01-decisions-and-governance.md#d117) 之後只剩三種組合**——
`CLIORA_PROJECT_EXPERIENCE_V2` 不存在。

| `PROJECTS` | `AGENT_RUNS` | 預期 |
|---|---|---|
| `false` | — | 全部 Project UI 與 API 關閉；terminal／session／node／file 不受影響 |
| `true` | `false` | Board／Backlog／Drawer／My Work 完整可用；**不顯示 Agent-specific filter**；**Done Gate 不適用**（它綁 `AGENT_RUNS`）；attention 只剩不依賴 run 的那幾級 |
| `true` | `true` | 完整 `beta.1` |

第二列的「Done Gate 不適用」是本計畫補的：
`done_gate.py` 的 docstring 明寫「the gate is bound to `CLIORA_AGENT_RUNS_ENABLED`…
applying the gate there would not be strictness, it would be breaking V2.1 for
people who never asked for V2.2」。所以那一格的 Done 欄**沒有** Done Gate 的拒絕，
而 UI 不得顯示一個永遠不會觸發的閘門提示。

第二列同時是 `PX-66` 要驗的一個**新**組合：一個沒有 Agent 的部署也要能用新看板，
而 attention 的八級在那裡只有 2／3／7／8 會出現。UI 不得顯示永遠為空的 quick filter。

## 10. Rollback

| 保證 | 怎麼達成 |
|---|---|
| 新 schema additive | 全部可 drop（[`02`](./02-data-layer.md) §6） |
| ~~舊 UI 保留一個 release window~~ | **☑ D117 取消**。`ProjectDetailView.vue` 在 `PX-64` 完成時刪除 |
| `/board` API 保留一版 | [D118](./01-decisions-and-governance.md#d118)：`beta.1` 標 deprecated，`beta.2` 刪 |
| 完整頁面 `/projects/:id/tasks/:taskId` 保留 | 禁區清單。Drawer 出問題時卡片仍打得開 |

| 新增資料不破壞舊 Task API | `GATE-PX-BOARD-UNCHANGED` |
| **rollback 不刪除使用者 saved views** | **真正的 rollback 路徑是關旗標，不是降 migration**（[`02`](./02-data-layer.md) §6） |
| rollback 不刪除 conversation／knowledge | 那是 `alpha.2`／`alpha.3` 的產品資料 |

**Rollback drill**（`PX-66`）：在 `beta.1` 的資料上，
**回上一個 image → 驗證 → downgrade `0043` → 驗證 → 再 upgrade → 驗證資料未損。**
saved view 會在 downgrade 時消失，這一點要在演練報告裡明寫——
**☑ D117 之後這是唯一的回滾路徑，所以這次演練比原本更重要。**

## 11. 三十八項出口條件

上游 [`10`](../../research/03/10-verification-and-exit.md) §9 有 34 項，
其中 11 項屬於 `alpha.2`／`alpha.3` 且已在前兩期關閉（22–31）。
本期保留與它們的交叉引用，並新增本計畫特有的四項。

| ☐ | # | 條件 | 證據 |
|---|---:|---|---|
| ☐ | 1 | 使用者可從 My Work 在 10 秒內找到等待自己處理的卡片 | §8 |
| ☐ | 2 | Backlog 與 Active Board 已分離 | [`06`](./06-board-and-backlog.md) |
| ☐ | 3 | Board／List 使用同一資料來源與 attention projection | 兩者呼叫同一 endpoint，只有 `layout` 不同 |
| ☐ | 4 | Saved personal／project views 權限正確 | §5.2 |
| ☐ | 5 | Task Drawer URL 可重整、分享與返回 | J10 |
| ☐ | 6 | 開關 Drawer 不丟失 view、filter 與 scroll | J10 |
| ☐ | 7 | 所有 optimistic mutation 失敗都會回滾 | §5.3 |
| ☐ | 8 | 所有移動拒絕提供 machine code 與可行動訊息 | [`06`](./06-board-and-backlog.md) §3.4 四種情境 |
| ☐ | 9 | Human approval 仍要求 human actor，且 UI 顯示 actor 與時間 | SR-3 #7 |
| ☐ | 10 | Agent token 仍不可進入 human approval path | SR-3 #8 |
| ☐ | 11 | Secret value 不出現在 API、UI、log 或 error | 既有 redaction 回歸 |
| ☐ | 12 | Agent Run 與 interactive Session 邊界未改變 | 既有負面測試回歸 |
| ☐ | 13 | V1 terminal、session、workspace 與 file flows 通過回歸 | 既有套組 |
| ☐ | 14 | **回滾演練通過**（回上一版 image ＋ downgrade `0043` ＋ 再 upgrade） | §10（原「旗標關閉回到舊 UI」由 ☑ D117 取消） |
| ☐ | 15 | `CLIORA_PROJECTS_ENABLED=false` 時 terminal／session／node／file 不受影響 | J16 |
| ☐ | 16 | 200 張卡 performance gate 通過 | §7 |
| ☐ | 17 | Keyboard 可完成核心任務 | a11y 測試 |
| ☐ | 18 | 零 undefined CSS tokens | `checkTokens.test.ts`（既有 gate） |
| ☐ | 19 | 視覺回歸通過（**a11y 完整 audit 在 `beta.2` 的 `HD-04`**） | `PX-64` 的逐頁回歸 |
| ☐ | 20 | migration rehearsal 與 rollback drill 完成 | §10 |
| ☐ | 21 | release note 列出 known limitations | `PX-66` |
| ☐ | 22–31 | `alpha.2`／`alpha.3` 的十項 | 交叉引用 `plan/24` §6、`plan/25` §8 |
| ☐ | 32 | **`BoardCardDTO` 與 `/board` 未變更，且大小未成長** | `GATE-PX-BOARD-UNCHANGED` |
| ☐ | 33 | **`agentd` 0.14.1 節點行為不變；本期 daemon diff 為零** | `GATE-PX-NO-DAEMON-DIFF` ＋ 完整 run 生命週期 E2E |
| ☐ | 34 | **`v2` → `dev` 仍由人工明確核准** | 平台 branch protection ＋ 人工紀錄 |
| ☐ | **35** | **attention 在 work-items、My Work、Overview 三處對同一張卡一致** | 一支跨 endpoint 的整合測試 |
| ☐ | **36** | **相位 B 與 `RunService.resolve_waiting_reason` 對同一個 run 給出相同答案** | [`03`](./03-read-model-and-attention.md) §2 的一致性測試 |
| ☐ | **37** | **本期未新增對外連線、未新增推播通道** | SR-3 #9 |
| ☐ | **38** | **SR-3 通過並具名簽核**，含 #3 的「無法產生負面案例」聲明 | 人的動作 |
| ☐ | **39** | **`/board` 已標 deprecated 且 `ProjectDetailView.vue` 已刪除** | [D117](./01-decisions-and-governance.md#d117)／[D118](./01-decisions-and-governance.md#d118)，`PX-64` |
| ☐ | **40** | **每個波次都留下了可看的產出**（截圖／錄影），或在 [`12`](./12-implementation-status.md) §2 寫下為什麼沒有 | [D115](./01-decisions-and-governance.md)、[`00`](./00-execution-plan.md) §4b |

（編號 22–31 是一格十項，所以清單是三十八個可打勾的項目。）

## 12. 九項 release 產物（`PX-66`）

```text
Release note              這一版做了什麼、對誰有意義
Known limitations         含「ProjectDetailView.vue 尚未刪除」與「stage 過渡尚未拆」
Compatibility manifest    Central commit / agentd 0.14.1 / contract 1.13.0 / migration 0043
Migration / rollback note 升級做了什麼、怎麼退回去、退回去會失去 saved views
Security delta            **本期為零新增信任邊界**——這一句要明寫，因為空的清單需要解釋
Test / gate evidence      artifacts/px/local/ 的完整輸出
Feature flag matrix       §9 的三種組合各一次驗證
Data retention delta      work_views 是新的長期資料；rank 與 blocking_* 是卡片的一部分
Manual sign-off record    SR-3 的具名簽核，附日期
```

**第 1 步到第 9 步任何一步失敗，就不是「先發再補」，是不發。**
