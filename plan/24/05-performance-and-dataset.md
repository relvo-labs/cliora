# 05 — 固定資料集與其餘四項量測（`CE-10`）

## 0. 現況：五項量測，量了一項

[`plan/23/08`](../23/08-verification-and-exit.md) §6 列了五個效能項目。
`plan/23/10` §5 量了其中一個（也是唯一進出口條件的那個）：

| 項目 | 目標 | 狀態 |
|---|---|---|
| **answer → continuation turn 開始 P95** | **< 10s** | ☑ **5.00s**（20 樣本，`artifacts/cv/local/answer-to-turn.json`） |
| message commit P95 | < 500ms | ☐ 未量 |
| conversation reopen（最近 50 則）P95 | < 500ms | ☐ 未量 |
| cursor 分頁（每頁 200，深度 500）P95 | < 300ms | ☐ 未量 |
| 20 併發寫同一張卡 | 無錯誤、seq 無洞 | ◑ **有單元測試**，但不在固定資料集上、沒有量時間 |

**四項未量不是遺漏，是沒有資料集。** `plan/23/08` §6 第一句就寫著
「固定資料集：一張卡 500 則訊息、一個專案 200 張卡、一個 runner」，
而那個資料集從來沒有被建出來——`research/03/CHECKLIST` §0 也還記著這一條未勾。

**這四項都不是出口條件**（出口條件只有第一項）。做它們的理由是另一個：
`beta.1` 的 Board／Drawer 會在同一張表上做更重的查詢，
而**沒有 `alpha.2` 的數字，`beta.1` 的回歸就沒有對照組**。
`research/03/CHECKLIST` §0 說得更直接：「事後補量沒有意義」。

## 1. 固定資料集（D76）

`scripts/cv/seed-dataset.py`，固定 seed，直接寫資料庫（不走 HTTP——
200 張卡走 API 是分鐘級，而這裡要的是列不是路徑覆蓋）：

```text
1 個 project
200 張 task            分佈：backlog 80 / ready 40 / running 20 / waiting 20 / done 40
  其中 1 張「深卡」      500 則 task_messages，seq 1..500，混合六種 kind
  其中 20 張「等待卡」    各 1 則 open question
6 個 task_runs 的歷史   含 2 個 continuation（parent_run_id 有值）
1 個 runner            enabled，poll 5s
```

輸出 `artifacts/cv/local/dataset.json`：seed、commit、資料庫 URL、
每張表的列數、深卡的 id。**量測腳本讀它而不是自己找卡片**——
「量到的是哪一張卡」這件事要能被第二個人重現。

**這份資料集同時關掉 `research/03/CHECKLIST` §0 的第四列**
（「建立 `alpha.1` 的固定測試資料集」），所以它的規格取那一列的並集：
200 tasks／6 runs／10 waits／5 failures／dependency graph／500 messages。

## 2. 四項量測

`scripts/cv/measure-conversation.py`，形狀沿用 `measure-answer-to-turn.py`
（httpx ＋ 直連資料庫、nearest-rank 百分位、輸出 JSON）：

| 量什麼 | 怎麼量 | 目標 |
|---|---|---|
| message commit | 對深卡 `POST /messages` 100 次，量 HTTP 往返 | P95 < 500ms |
| conversation reopen | `GET /messages?limit=50`（最新一頁）100 次 | P95 < 500ms |
| cursor 分頁 | `GET /messages?after_seq=&limit=200` 走完深度 500，重複 100 輪 | P95 < 300ms |
| 20 併發 | 20 個 `asyncio.gather` 的 POST 到同一張卡 | 無錯誤、seq 恰好 1..20 各一次、且記錄 wall-clock |

**百分位用 nearest-rank**，理由沿用 `measure-answer-to-turn.py` 的註解：
內插會造出一個沒有任何一次請求真的達到的數字。

### 兩個必須先做的健康檢查

`plan/23/10` §5 記過一個 29.9 秒的樣本，原因是上一輪的 run 還佔著
runner 的 `max_concurrent` 名額。所以腳本開始前：

1. 數還在飛的 run（`status IN ('queued','claimed','running')`），**不是零就拒絕跑**；
2. 印出資料集的 `dataset.json` 摘要與 commit。

第 2 條不是裝飾：**四個數字若沒有附上它們是在哪一份資料上量的，
`beta.1` 拿它們當對照組時會做出錯誤的比較。**

## 3. 輸出

`artifacts/cv/local/conversation-perf.json`：

```json
{
  "dataset": {"seed": 20260819, "tasks": 200, "deep_card_messages": 500, "commit": "…"},
  "inflight_runs_at_start": 0,
  "message_commit":      {"n": 100, "median": …, "p95": …, "target_ms": 500,  "verdict": "PASS"},
  "conversation_reopen": {"n": 100, "median": …, "p95": …, "target_ms": 500,  "verdict": "PASS"},
  "cursor_page":         {"n": 100, "median": …, "p95": …, "target_ms": 300,  "verdict": "PASS"},
  "concurrent_20":       {"errors": 0, "seq_gaps": 0, "wall_clock_s": …}
}
```

## 4. 超標的話怎麼辦

**不修，記錄。** 本期是封版期（D68），四項都不是出口條件。
超標的處置是：寫進 release note 的 known limitations、
寫進 [`09`](./09-open-measurements.md)，並在 `beta.1` 的計畫裡開一張 ticket。

**唯一的例外**是第四項（20 併發）出現 `seq_gaps > 0` 或 `errors > 0`——
那不是效能問題，那是 `uq_task_messages_seq` 或取號路徑的正確性缺陷，
屬於 D68 表格的第一列（讓旅程無法完成），要停下來修。
