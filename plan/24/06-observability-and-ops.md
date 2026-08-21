# 06 — 可觀測性與維運（`CE-11`）

## 1. 四個計數器有了，告警沒有

`backend/app/metrics.py:64-72` 定義了四個計數器，而且都真的被 increment：

| 常數 | 遞增點 |
|---|---|
| `CONVERSATION_MESSAGES_TOTAL` | `conversation.py:388`（labels: `kind`、`type`） |
| `CONVERSATION_TURNS_TOTAL` | `conversation.py:685` |
| `CONVERSATION_QUESTION_EXPIRED_TOTAL` | `conversation.py:702` |
| `CONVERSATION_DUPLICATE_TURN_TOTAL` | `runs.py:831` |

**而 `deploy/prometheus/alerts.yml` 裡沒有 `conversation` 這個字。**

這一條的份量比它看起來重，因為 `metrics.py` 自己寫著：

> `CONVERSATION_DUPLICATE_TURN_TOTAL` 的告警門檻是**大於零**而不是一個速率。
> question 的 CAS 已經序列化了 answer，所以非零表示有一條路徑繞過了它——
> **而那個 bug 沒有其他症狀：系統照常運作，某個人的 Agent 回答了兩次。**

一個「沒有其他症狀」的 bug ＋ 一個沒有人看的計數器 = 一個不會被發現的 bug。
`plan/23/09` §8 也把它寫成了「大於 0 就告警」。**本期把那句話變成一條規則。**

## 2. 三條告警規則

加進 `deploy/prometheus/alerts.yml` 的一個新 group：

| alert | expr | severity | 為什麼是這個門檻 |
|---|---|---|---|
| `ClioraConversationDuplicateTurn` | `increase(cliora_conversation_duplicate_turn_total[15m]) > 0` | **critical** | 大於零就是繞過 CAS。沒有「可接受的少量」 |
| `ClioraConversationQuestionExpirySurge` | `increase(cliora_conversation_question_expired_total[1h]) > 5` | warning | 逾時本身是正常的（沒有人在 24 小時內回覆）。**一小時內五個**表示不是「某個人剛好在忙」 |
| `ClioraConversationTurnsStalled` | `increase(cliora_conversation_messages_total{kind="answer"}[15m]) > 0 and increase(cliora_conversation_turns_total[15m]) == 0` | warning | 有人在回答但沒有任何新的一輪被建立——continuation 的路斷了。這是 `duplicate_turn` 的**反面**，而它同樣沒有其他症狀 |

第三條需要說明：它會在一種正常情況下誤報——所有 answer 都落在
「run 還活著」的分支（`mode == "live_run"`，不建立 turn，D67）。
所以它是 warning 不是 critical，而 runbook 的第一步就是分辨這兩者。
**寫下這個已知的誤報條件，比拿掉這條規則好**：
拿掉之後，「回答之後什麼都沒發生」這件事就沒有任何人看得見。

`backend/tests/test_alerts_and_runbooks.py` 會自動涵蓋這三條——
它 parametrize 了整個規則檔，斷言每一條都有 severity、summary 與**一份存在的 runbook**。

## 3. Runbook

`docs/runbooks/conversation-duplicate-turn.md`，沿用既有 runbook 的形狀
（症狀 → 立即確認 → 影響範圍 → 處置 → 事後）：

```text
症狀      ClioraConversationDuplicateTurn 觸發
立即確認  SELECT parent_run_id, resumed_question_id, count(*)
            FROM task_runs WHERE resumed_question_id IS NOT NULL
            GROUP BY 1,2 HAVING count(*) > 1;
          → 有列：唯一索引失效或被繞過（嚴重）
          → 無列：計數器被錯誤地遞增（較輕，但仍是缺陷）
影響範圍  那些 task 的 Agent 可能重複執行了同一輪——
          delivery 是 pull_request 的卡要檢查有沒有重複的 push
處置      ① 停用該 runner（PATCH /api/agents/{id} {"enabled": false}）
          ② 保留現場：不要刪 run
          ③ 回報時附上 uq_task_runs_continuation 是否仍存在
事後      這個計數器非零過一次，就要在下一個 release note 裡出現
```

第二條查詢是 runbook 的重點：**它能分辨「索引失效」與「計數器誤報」**，
而這兩者的處置完全不同。一個只說「檢查日誌」的 runbook 在半夜沒有用。

## 4. 兩個「應該永遠是零」的 machine code

`plan/23/09` §8 指出 `CONVERSATION_CURSOR_AHEAD` 與 `TURN_ALREADY_QUEUED`
在正常運作下**永遠不會被回傳**：前者表示 client 的狀態壞了，
後者表示有一條路徑沒走 CAS。

**本期不新增它們的計數器**（那需要動 `backend/app/`，違反 D68）。
處置是把它們寫進 [`09`](./09-open-measurements.md) 的清單，
並在 release note 的 known limitations 裡明說：
這兩個 code 目前只出現在 HTTP 回應與 audit 裡，沒有獨立的 metric。
`beta.1` 若要加，那是一行 `metrics.increment`，成本不在實作而在
「決定它該不該有自己的告警」——而那需要先看到它出現過。

## 5. 不做的一件事：`answer_to_turn_seconds` histogram

`plan/23/10` §7 記過：六個 metric 縮成四個，
兩個 histogram（`answer_to_turn_seconds`、`turns_per_task`）需要真實 runner 才量得到。

**本期仍然不加**，理由變了但結論相同：現在有真實 runner 了（`E2E_RUNNER=1`），
但 histogram 要有價值需要的是**真實流量的分佈**，而目前的部署是單人的。
`measure-answer-to-turn.py` 已經回答了「這條路徑要多久」，
histogram 要回答的是「不同的卡、不同的時間、它怎麼變化」——
那個問題在 `beta.1` 有人用之前沒有答案。這一條進 [`09`](./09-open-measurements.md)。
