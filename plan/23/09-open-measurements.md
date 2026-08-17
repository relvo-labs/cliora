# 09 — 未量測項

沿用既有體例：**這裡列的是本期知道自己沒量的東西，以及為什麼不量。**
一個沒有列在這裡、也沒有被量的東西，是一個漏洞而不是一個決定。

| # | 項目 | 為什麼現在不量 | 何時量 | 誰負責 |
|---:|---|---|---|---|
| 1 | 真實對話的輪數分佈與放棄率 | 需要真實使用者。本期只有 metric 的埋點（`cliora_conversation_turns_per_task`），沒有資料 | `beta.1` 試用之後 | product |
| 2 | continuation 該不該插隊 | 目前 `_eligible()` 是 `ORDER BY queued_at`，沒有優先權——那是 ADR 0029 明確的姿態。**先量 answer→turn 的 P95**（[`08`](./08-verification-and-exit.md) §6），超過 10 秒再談 | `alpha.2` 上線後一個月 | central |
| 3 | poll 間隔 5 秒是否需要調短 | 與第 2 項同一組資料。若 P95 的瓶頸是 poll 那一段，選項有三個：調短間隔（成本是所有 runner 的請求量）、D44 的通知路徑、或接受 | 同上 | central／daemon |
| 4 | **continuation 拿不到上一輪未提交的變更**，實務上有多痛 | 隔離工作目錄是 per-run 的（`FR-AGENT-011`），continuation 是新目錄。對釐清卡無影響；對實作卡的影響取決於「Agent 多常在改到一半時提問」，而那個數字現在是零筆 | `beta.1` | daemon |
| 5 | 逾時後回覆的粗糙邊緣 | question `expired` 之後卡片在 `blocked`，UI 給的動作是「重新派工」而不是「回覆並繼續」。**新的一輪不會帶著那則遲來的回覆**——它會出現在對話裡，但不在 `input_from_seq..input_to_seq` 的範圍內 | `beta.1`，看真實逾時頻率 | central |
| 6 | 情境包 16 KiB 上限是否合適 | 沒有真實對話長度分佈。上限選在這裡是因為它大約是 4000 token，佔一個典型 context window 的個位數百分比 | `alpha.3` 的 Context Builder 會重新校準 | central |
| 7 | `cliora task wait` 的 120 秒上限 | 需要真實 Agent 行為：如果沒有人用 `wait`（因為結束 process 更好），這個上限就不重要 | `beta.1` | daemon |
| 8 | 十六個 machine code 的實際命中分佈 | 上線前只能猜。有幾個（`CONVERSATION_CURSOR_AHEAD`、`TURN_ALREADY_QUEUED`）預期是零——**不是零就是有 bug**，那時才有用 | 持續 | central |

## 幾條特別要說明的

### 第 2、3 項是同一個決定的兩半

「answer 之後多久 Agent 才動」這件事，Central 能做的只有兩個：
讓 continuation 排前面，或讓 runner 更早知道。前者改排序、後者改 contract，
**兩個都要證據才值得做**。所以本期先埋 metric、先接受 P95 < 10s，
把兩個選項都留著。

這也是為什麼 [`08`](./08-verification-and-exit.md) §6 要求把 10 秒**拆成三段**記錄：
沒有拆開，就分不出該選哪一個。

### 第 5 項是一個已知會被抱怨的邊緣

實際的樣子：Agent 問了問題，沒有人在 24 小時內回，卡片退回 `blocked`；
第二天有人回了——那則回覆會出現在對話裡（它就是一則訊息），
但因為 question 已經 `expired`，不會建立 continuation。
使用者要自己按「重新派工」，而新的一輪走的是完整的第一輪情境包，
**上下文不會遺失**（對話都在），但那不是「回覆並繼續」的體感。

不在本期修的理由：修法有三種（延長逾時、允許 expired 復活、
讓 `blocked` 的卡也能 continuation），**三種都需要知道逾時多常發生**，
而目前的部署是單人的，那個數字沒有意義。

### 第 8 項的「應該是零」

`CONVERSATION_CURSOR_AHEAD` 與 `TURN_ALREADY_QUEUED` 這兩個 code
在正常運作下**永遠不會被回傳**：前者表示 client 的狀態壞了，
後者表示有一條路徑沒走 CAS。

它們存在的價值不是「處理這個情況」，是**「這個情況發生時看得見」**。
所以它們要進 metric，而且要有告警門檻——不是「超過 N 次」，是**「大於 0」**。
