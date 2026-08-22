# Cliora `v2.0.0-alpha.2` — 封版（V2-C1 Exit）

> **狀態：`CE-01`…`CE-19` 全部實作完成（2026-08-21）。** 2026-08-19 開立。
> `E2E=1 scripts/cv/evidence.sh` → **7 passed, 0 failed, 0 skipped**；
> 七條旅程全過、0.12.0 已實測、五項量測有數字、四份 ADR 已 accepted、SR-1 已簽核。
> **封版條件 28／28**；兩個 annotated tag 已建立（`v2.0.0-alpha.1` → `f91d9c4`、`v2.0.0-alpha.2` → `139f143`）。
> **刻意留在本機**：push 與 GitHub pre-release 都會發佈，而那是與打 tag 分開的決定。
> 上游規劃：[`research/03/02-phase-c1-ticket-conversation.md`](../../research/03/02-phase-c1-ticket-conversation.md)。
> 實作紀錄：[`plan/23/`](../23/README.md)（**本目錄不取代它，只接在它後面**）。
> **合併規則不變**：`v2` → `dev` 一律由人決定，出口條件全綠只是取得提案資格。

Ticket 前綴 `CE-`（**C**onversation **E**xit）。

---

## 這一組計畫要回答的問題

`plan/23` 把 `alpha.2` 的**程式**做完了：`CV-00`…`CV-13` 全部落地，
`make check` 全綠、八個 gate 全 PASS、出口條件 **21／23**。

**剩下的兩項不是功能，是證據。** 而一個沒有證據的出口條件，
與一個沒有做的功能，在 release 那一天是同一件事：

> `alpha.2` 的核心承諾是「**一個 answer 只會讓 Agent 跑一次**」。
> 這件事目前由 15 條整合測試、一個唯一索引與一個 AST gate 保證——
> 全部都在**同一個行程裡**。沒有任何一次證明，是在
> 「真的 daemon 被 kill 之後重新起來」這個情境下做出來的。

所以這一期的形狀是：

```text
                     plan/23（已完成）              plan/24（本期）
 產出                 程式                          證據
 主要動詞             實作                          執行、量測、簽核、封版
 測到的層             服務、路由、元件、CLI 單元      整條堆疊：瀏覽器 → Central → 真 daemon → 子行程
 失敗長什麼樣          測試紅                        旅程卡在某一步，而那一步就是缺陷所在
 完成時可以說什麼      「我們實作了持久對話」          「`v2.0.0-alpha.2` 是一個可重現、可驗證、可回滾的產品邊界」
```

**這一期刻意不新增任何產品能力**（[`01`](./01-decisions-and-governance.md) D68）。
`backend/app/` 與 `frontend/src/` 的預設狀態是**零 diff**，
由 `GATE-CE-NO-PRODUCT-DRIFT` 守著。旅程如果照出一個真的缺陷，
那個缺陷會有具名的 waiver、一張自己的 ticket 與一段寫在
[`10`](./10-implementation-status.md) 的紀錄——而不是順手改一改。

---

## 五個真正的缺口（讀完程式碼與堆疊才看得到的那種）

| # | 缺口 | 證據 | 修在哪 |
|---:|---|---|---|
| 1 | **run 裡沒有 `cliora` 可以執行。** `run-stack.sh` 只把二進位放進 `$BIN`，而 `$BIN` 不在 daemon 的 `PATH` 上；子行程繼承的正是 daemon 的環境（`run_handlers.go:327` `secrets.ChildEnv(os.Environ())`） | `scripts/e2e/run-stack.sh:86-91`（只加 `/usr/local/go/bin`） | `CE-01` |
| 2 | **fakecli 在 runner 模式下永遠 exit 0。** 腳本失敗只變成一個 `"failed": true` 的事件，行程仍然成功——而 daemon 判定失敗看的是 `outcome.ExitCode != 0` | `daemon/cmd/fakecli/main.go:runNonInteractive`、`run_handlers.go:485` | `CE-01` |
| 3 | **daemon 無法被測試重啟。** `run-stack.sh` 把 binary、config、credentials 全留在 `mktemp -d` 裡，一個都沒 export；PID 只在 `PIDS[]` 陣列裡 | `scripts/e2e/run-stack.sh:52-175` | `CE-01` |
| 4 | **CV 的八個 gate 從未在 CI 跑過。** 沒有任何 workflow 引用 `scripts/cv/` | `grep -rn "scripts/cv" .github/workflows` 無結果 | `CE-08` |
| 5 | **四個 conversation 計數器沒有任何告警。** `metrics.py` 自己寫著「`CONVERSATION_DUPLICATE_TURN_TOTAL` 的門檻是大於零」，而 `alerts.yml` 裡沒有這個字串 | `backend/app/metrics.py:64-72`、`deploy/prometheus/alerts.yml` | `CE-11` |

**第 1、2、3 條合起來解釋了一件事**：為什麼六條旅程「還沒寫」——
它們不是沒空寫，是**寫了也跑不起來**。`plan/23/10` §9.2 說「缺的是旅程本身，不是堆疊」，
那句話對了一半：Central 與 runner 那半邊確實已經就位（`E2E_RUNNER=1` 是那一輪加的），
**但 Agent 那半邊沒有**。這正是 `plan/23/10` §9.1 那條縫的延伸——
`cliora` 現在找得到自己的憑證了，可是在 e2e 的 run 裡它根本不在 `PATH` 上。

---

## 文件導覽

| 文件 | 用途 |
|---|---|
| [00-execution-plan.md](./00-execution-plan.md) | 九項裁決、四個波次、15 張 ticket、依賴圖、**本期的禁區清單** |
| [01-decisions-and-governance.md](./01-decisions-and-governance.md) | **D68–D76** 全文，含「不同意的話會怎樣」 |
| [02-e2e-harness.md](./02-e2e-harness.md) | 堆疊缺的三件事、`E2E_*` 契約、agent 腳本的形狀 |
| [03-journeys.md](./03-journeys.md) | 七條旅程（J1a／J3／J5／J6／J7／J8／J9）逐步腳本與斷言 |
| [04-compatibility-0120.md](./04-compatibility-0120.md) | 未升級 `agentd` 0.12.0 節點實測（出口 16、SR-1 finding 2） |
| [05-performance-and-dataset.md](./05-performance-and-dataset.md) | 固定資料集、`plan/23/08` §6 五項量測中未量的四項 |
| [06-observability-and-ops.md](./06-observability-and-ops.md) | 告警規則、runbook、「應該永遠是零」的兩個 machine code |
| [07-release-artifacts.md](./07-release-artifacts.md) | `research/03/00` §7 的九項產物、`alpha.1` freeze checklist |
| [08-verification-and-exit.md](./08-verification-and-exit.md) | 三個新 gate、clean-room 重驗程序、**28 項封版條件** |
| [09-open-measurements.md](./09-open-measurements.md) | 本期知道自己沒量的東西與理由 |
| [10-implementation-status.md](./10-implementation-status.md) | 實作後回填；**與計畫不同時以這裡為準並回寫計畫** |

## 建議使用方式

1. 先讀 [`01`](./01-decisions-and-governance.md) 的 **D68**（scope freeze）與 **D72**（先打 `alpha.1`）
   ——那兩項決定了本期的形狀，其餘七項是技術選擇。
   **九項已於 2026-08-21 全部裁決，全部採納計畫的答案**，所以這一步是讀而不是決定。
2. 波次 1（`CE-01`…`CE-03`）是**堆疊**：沒有它，波次 2 的每一條旅程都跑不起來。
3. 每張 ticket 以「決策 → 契約 → 實作 → 自動測試 → 操作證據」完成。
4. **旅程失敗時預設是產品有缺陷，不是旅程寫錯**。反過來的結論要寫進 [`10`](./10-implementation-status.md) 並附理由。
5. 出口條件未通過，不建立 `v2.0.0-alpha.2` tag。

## 基線（開工前確認，2026-08-19 實際核對）

| 項目 | 值 | 怎麼確認的 |
|---|---|---|
| `v2` HEAD | **`ac3dfef`**（`f91d9c4` 之後 4 個 commit） | `git rev-parse HEAD`、`git rev-list --count f91d9c4..HEAD` |
| 相對 `master` | **ahead 64／behind 6** | `git rev-list --left-right --count master...HEAD` |
| **git tag** | **一個都沒有** | `git tag -l` 空白——`alpha.1` 從未被 tag（見 [`07`](./07-release-artifacts.md) §1） |
| contract | **1.13.0，不動** | `artifacts/cv/local/baseline/contract-v1.sha256` |
| `agentd` | **0.13.0**（`daemon/VERSION`）；相容目標是 **0.12.0**（`f91d9c4`） | `git show f91d9c4:daemon/VERSION` |
| migration head | **0040**`_ticket_conversation` | `db/migrations/versions/` |
| ADR 0035／0036／0037／0041 | **四份全部 `Status: proposed`** | 各檔第 2 行 |
| SR-1 | **已產出、未簽核**，兩項未結發現 | `docs/security-review-v2c1.md` §6 |
| 出口條件 | **21／23** | `plan/23/10` §6 |
| `FR-CONV-001`…`-010` | 已註冊，`lifecycle: proposed`，**0 條 traceability link** | 與其他所有 V2 家族一致（見 [`09`](./09-open-measurements.md) §2） |
| conversation 整合測試 | **15 passed**（本機重跑） | `pytest backend/tests/db/test_conversation.py` |
| 四個 AST gate | **OK** | `python scripts/cv/gate_conversation_invariants.py` |

## 給執行者的環境備忘

這台機器上三個工具鏈都在，但**都不在預設 `PATH`**——沿用 `scripts/pj/evidence.sh` 的前導：

```bash
export PATH="$HOME/.local/bin:/usr/local/go/bin:$HOME/.nvm/versions/node/v22.14.0/bin:$PATH"
# PostgreSQL：容器 cliora-pg（postgres:16-alpine）已在 127.0.0.1:5432
export CLIORA_DATABASE_URL=postgresql+asyncpg://cliora:cliora@127.0.0.1:5432/cliora_test
export CLIORA_TEST_DATABASE_URL="$CLIORA_DATABASE_URL"     # 分兩行寫：同一個 export 裡
                                                            # 右邊的 $ 展開發生在賦值之前
```

最後那條註解不是湊字數：寫成一行會讓 `CLIORA_TEST_DATABASE_URL` 是空的，
而 `backend/tests/db/conftest.py:88` 的反應是 **skip 而不是 fail**——
15 條測試會印出 `15 skipped` 然後綠燈通過。本期第一次跑就踩到了這個。
