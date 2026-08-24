# 11 — 未量測項

> **這一份的用途是「不要假裝量過」。** 每一條寫：是什麼、為什麼現在不量、何時量、
> 以及**不量的風險由誰承擔**。

## 1. per-project ACL 下的 counts 存在性洩漏

**是什麼**：上游 SR-3 要求「無權專案的卡不在 items 也不在 counts」，
並要一條 inference 測試證明無權使用者的 count 為 0 而不是 403。

**為什麼現在不量**：這個部署**沒有 per-project membership**
（[D93](./01-decisions-and-governance.md)）。`_VIEWER_ACTIONS` 含 `project.view`，
一個持有它的人看得到全部專案。所以「有權看 A、無權看 B」這個狀態不存在，
負面案例造不出來。

**何時量**：per-project membership 進來的那一期（`Horizon 3`／Enterprise governance）。
那時要一併回頭改 [`05`](./05-work-items-and-view-api.md) §6 的
`RANK_NEIGHBOR_STALE.cross_project`——今天回 409 是安全的，
有了 membership 之後它必須回 404。

**風險由誰承擔**：`GATE-PX-ONE-PROJECT-SCOPE` 讓「未來加 ACL 時只有一個地方要改」
成為可檢查的事實。但它不保證那一個地方會被改對。
**SR-3 的簽核文字必須包含這句話**，否則簽核的人以為自己批准的是一個已驗證的邊界。

## 2. 多 worker 部署下 attention 的兩個 runtime 級

**是什麼**：`no_eligible_runner` 與 `assigned_runner_offline` 由
`NodeConnectionRegistry` 這個行程內 dict 決定（[D92](./01-decisions-and-governance.md)）。
若 Central 跑多個 worker，每個 worker 只看得到自己那些節點連線。

**為什麼現在不量**：Central 今天是單行程。
`Makefile:96` 的 `uvicorn` 沒有 `--workers`，`deploy/compose/compose.yaml`
也沒有 replica 設定，Railway 的兩個 json 同理。**所以今天正確。**

**何時量**：任何一次「把 Central 水平擴展」的討論的第一個議程項目。
那時的正確答案很可能不是「同步 registry」，而是
「把 runner 的線上狀態變成一個可查詢的事實」——
而那要先撤銷 ADR 0029 §1，所以它是一個 ADR 級的決定，不是一個設定。

**風險由誰承擔**：`work-items` 回應的 `runtime_signals_available` 欄位
（[`05`](./05-work-items-and-view-api.md) §2）讓前端能區分
「沒看」與「看了沒有」，但它**分不出「這個 worker 沒看到」與「真的沒有」**。
這一句要進 release note 的 known limitations。

## 3. 20 秒輪詢是不是對的數字

**是什麼**：[D95](./01-decisions-and-governance.md) 訂了 `work-counts` 20 秒。
它的兩個對手是「太慢，人以為看板壞了」與「太快，一個開三十個分頁的人打爆 endpoint」。

**為什麼現在不量**：需要真實使用者與真實分頁數。
`alpha.2` 量到的 message → turn P95 是 10 秒級，20 秒與它相稱，
但那是推理不是量測。

**何時量**：`beta.1` 上線後的第一個月，量三件事——
`work-counts` 的 QPS、每個使用者的中位分頁數、
以及「attention 出現」到「使用者開啟該卡」的中位延遲。
第三個才是真正該最佳化的量。

**風險由誰承擔**：`work-counts` 的 P95 < 200ms 預算
（[`10`](./10-verification-and-exit.md) §7）是唯一的護欄。超過它就先降頻，不先加索引。

## 4. 300 行自製 query 層的維護成本

**是什麼**：[D100](./01-decisions-and-governance.md) 的 `queryCache.ts`。
D56 已經裁決不引入套件，但「不引入」的代價要在一個 release 之後才看得到。

**為什麼現在不量**：需要至少一個 release 的實際使用。

**何時量**：`beta.2`。判準寫在 [`09`](./09-frontend-architecture.md) §2 的反悔點：
**若它開始長出 retry policy、suspense、devtools，就是該換套件了。**
這是一個可以在 code review 裡回答的問題，不需要儀器。

## 5. `required_labels` 的 `contains` 是不是熱點

**是什麼**：[`02`](./02-data-layer.md) §4 決定**先不建** GIN 索引。

**為什麼現在不量**：一個專案的卡片是數百張，順序掃描 JSONB 陣列很可能夠快；
而 GIN 的維護成本落在每一次卡片更新上，而卡片更新比 label 篩選頻繁得多。

**何時量**：`PX-24` 的量測順便量。若 `contains` 的 filter 讓 `work-items`
P95 超過 1s，開一個 `0043b` 補索引——**而不是現在先建一個可能用不到的**。

## 6. `WorkItemCardDTO` 的真實大小

**是什麼**：[D94](./01-decisions-and-governance.md)。33 欄的實際 bytes 今天未知。

**為什麼現在不量**：DTO 還不存在。

**何時量**：`PX-25` 的**第一個 commit**。這是本清單裡唯一一條
「在本期之內就會被關掉」的項目，列在這裡是因為
**計畫階段引用一個未量測的數字（160 KB）正是本期要避免的錯誤**。

## 7. 十級 authority 是否過細

**是什麼**：`alpha.3` 的 D45 定了十級 authority。上游把「是否過細」的量測
排在 `beta.1`。

**為什麼現在不量**：需要真實使用。而 `beta.1` 對 knowledge 的接觸只有
`PX-62`（Related knowledge 區塊），它顯示 authority 但不產生新的使用資料。

**何時量**：`beta.2`。**本期把它從 `beta.1` 移到 `beta.2`**，
並在 [`12`](./12-implementation-status.md) §0 記為要回寫上游的一處。

## 8. `cliora task wait` 的 120 秒上限

**是什麼**：`alpha.2` 的 `CV-08` 訂了 120 秒。上游排在 `beta.1` 量。

**為什麼現在不量**：本期的 daemon diff 是零（[D106](./01-decisions-and-governance.md)），
而這個數字只有在觀察真實 Agent 行為時才有意義。

**何時量**：`beta.2` 的 `HD-11`（十六條旅程完整回歸）順便收集。
同樣移到 `beta.2`，記在 [`12`](./12-implementation-status.md) §0。

## 9. Ready transition 的「仍要送到 Ready」被按下的比率

**是什麼**：[D97](./01-decisions-and-governance.md) 維持 DoR 只警告。
如果幾乎每個人都按「仍要送到 Ready」，那表示 DoR 的七項與實際工作方式不符，
而那是一個產品訊號而不是一個 UI 問題。

**為什麼現在不量**：需要真實使用者。

**何時量**：`beta.1` 上線後。這是一個**只記 metadata** 的計數
（按了幾次、缺哪幾項），**不記卡片內容**。

**風險由誰承擔**：如果比率很高而沒有人看這個數字，
D97 的「維持警告」就從一個決定退化成一個現況。

## 10. 大 Project（>2000 卡）的分頁與 counts

**是什麼**：本期全部量測用 200 卡的固定資料集。

**為什麼現在不量**：手上沒有這種專案，而造一個 2000 卡的 fixture
只會量到 PostgreSQL 的效能，量不到真實的 filter 分布。

**何時量**：`beta.2` 的 `HD-10`（大 Project 的 indexing／retention／queue／cost）。
唯一在本期做的預防是 `ix_tasks_project_updated`
（[D104](./01-decisions-and-governance.md)）在 2000 卡上也量一次 `EXPLAIN`。

## 11. `STALE_AFTER` 的七天

**是什麼**：attention 第 8 級的「停滯」門檻。
計畫（[`03`](./03-read-model-and-attention.md) §2）寫的是
`updated_at < now() - :stale_after`，**沒有給值**；
`PX-24` 訂了 7 天，並限定只對 `ready`／`in_progress`／`review` 三個 lifecycle 生效。

**為什麼現在不量**：這是一個關於**團隊節奏**的數字，不是關於系統的。
一個兩週衝刺的團隊與一個每日出貨的團隊，「一張卡多久沒動算不動了」差三倍，
而本期沒有任何真實看板可以看。七天是「一個完整工作週都沒有人碰」，
這個說法至少可以被反駁。

**何時量**：`beta.1` 上線後，與 [§9](#9-ready-transition-的仍要送到-ready-被按下的比率)
同一批：第 8 級佔全部 attention 的比率。
**若它超過三成，這個門檻就在製造噪音而不是訊號**——
一個大半塊看板都有的徽章等於沒有徽章。

**風險由誰承擔**：它是 `services/work/projection.py` 的一個模組常數，
不是 per-project 設定。這是刻意的（一個沒人調的旋鈕需要 migration、UI 與預設值，
而只有預設值會被用到），代價是改它要發版。

**這一項與 [§9](#9-ready-transition-的仍要送到-ready-被按下的比率) 的差別**：
§9 量的是一個決定（只警告）對不對，這一項量的是一個常數對不對。
兩者都只記 metadata，不記卡片內容。
