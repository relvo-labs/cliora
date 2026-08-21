# 10 — 實作進度與證據

> **狀態：`CE-01`…`CE-15` 全部完成（2026-08-21）。七條旅程通過、0.12.0 已實測、
> 五項量測有數字、告警與 runbook 就位、九項 release 產物齊備。**
> 剩下的兩件事**只有人做得到**：四份 ADR 改 `accepted` ＋ SR-1 簽核（同一次），
> 以及兩個 tag。清單在 [`docs/release-checklist-alpha2.md`](../../docs/release-checklist-alpha2.md)。
>
> **這一期照出四個產品缺陷／落差**：`CE-16`、`CE-17`（已修）、`CE-18`、`CE-19`（記錄不修）。
> 其中 `CE-17` 讓「未升級節點行為不變」這句話的答案從 PASS 變成 **MEASURED**。
>
> 沿用 `plan/17/09`／`plan/19/09`／`plan/22/11`／`plan/23/10` 的體例：
> **這裡記的是實際發生的事**，與計畫不同時，**以這裡為準並回寫計畫**。

## 0. 開工前的裁決單

### A 類 — 擋開工

| ☑ | 決策 | 計畫的答案 | 裁決 | 日期 |
|---|---|---|---|---|
| ☑ | **D68** 本期能不能改產品程式 | 不能，例外要具名 waiver | **不能** | 2026-08-21 |
| ☑ | **D72** `alpha.1` 要不要先打 tag | 要，target `f91d9c4` | **要**（且不移動它） | 2026-08-21 |
| ☑ | **D74** ADR accepted 與 SR-1 簽核 | 同一次，證據之後、tag 之前 | **同一次**，含追認實作先於 accepted | 2026-08-21 |

### B 類 — 實作時依計畫的答案執行

**六項於 2026-08-21 一併裁決，全部採納計畫的答案。** 「落地」欄由實作時回填。

| ☑ | 決策 | 裁決（＝計畫的答案） | 落地 |
|---|---|---|---|
| ☑ | **D69** 旅程分兩層 | 3 條瀏覽器 ＋ 4 條 API | |
| ☑ | **D70** Agent 依對話狀態決定行為 | 不用計數器檔 | |
| ☑ | **D71** 0.12.0 binary | `git worktree` 出 `f91d9c4` 現地建 | |
| ☑ | **D73** gate 與旅程進 CI | `v2-projects.yml` 第三條 leg | |
| ☑ | **D75** chaos 用 SIGKILL | 殺整個 process group | |
| ☑ | **D76** 資料集不進版本控制 | 固定 seed 的種子腳本 | |

### 繼承項

| ☑ | 決策 | 裁決 | 日期 |
|---|---|---|---|
| ☑ | **D51** 保留／附件／大小 | **確認為已裁決**——`plan/23` 實作時已落地，不重新討論 | 2026-08-21 |
| — | **D46** provider sync 落點 | **確認不擋本期**（屬 `alpha.3`／`beta.2`） | 2026-08-21 |

## 1. Ticket 狀態

| ticket | 狀態 | 證據 |
|---|---|---|
| `CE-01` 堆疊三缺口 | ☑ | `run-stack.sh`：`cliora` symlink ＋ `$BIN` 進 `PATH`、`CLIORA_PUBLIC_BASE_URL`、五個 `E2E_DAEMON_*`、`E2E_AGENT_SCRIPT`；`fakecli` 帶出腳本退出碼；`scripts/cv/daemon-ctl.sh`；`j0_agent_seam.py` **5／5 PASS** |
| `CE-02` 會提問的 Agent | ☑ | `scripts/cv/agent/clarify.sh`（依對話狀態決定這一輪，D70） |
| `CE-16` run 情境包沒有平台位址 | ☑ | §2.1；`backend/tests/db/test_conversation.py::test_a_runs_context_pack_says_where_cliora_is`（**已驗證去掉修正會紅**） |
| `CE-17` `run.complete` 被靜默丟棄 | ☑ | §2.2；`run_handlers_test.go` 兩條（以 `ValidateControl` 驗整個 frame）；真堆疊上 run 現在會結束 |
| `CE-18` 要求修改不會續跑 | ◑ **記錄不修** | §2.4；J1a 改成「人再派工一次」，因為那是今天唯一走得通的路 |
| `CE-19` 對話面板不會自己更新 | ◑ **記錄不修** | §2.5；三條瀏覽器旅程都要 reload |
| `CE-03` clean-room 重驗 | ☑ | `scripts/cv/evidence.sh` 九節 ＋ `_stack-evidence-inner.sh`；沒有 `E2E=1` 時**正確地**回報「不可 tag」 |
| `CE-04` J3 ＋ J6 | ☑ | `conversation.spec.ts`（J3）＋ `j6_comments.py` **10／10** |
| `CE-05` J1a | ☑ | `conversation.spec.ts`——四輪、兩份提案、兩則 decision、全程不進 Terminal |
| `CE-06` J5 chaos | ☑ | `j5_chaos.py` **14／14**，`claimed_before_kill=False`（真的是「認領前崩潰」那一種） |
| `CE-07` J7 ＋ J8 ＋ J9 | ☑ | `conversation.spec.ts`（J7）、`j8_concurrent.py` **7／7**、`j9_decision.py` **8／8** |
| `CE-08` CI leg | ☑ | `v2-projects.yml` 的第三條 leg（`conversation`）＋ `gate_closeout.py` 三個 gate |
| `CE-09` 0.12.0 實測 | ☑ | `compat-0120.sh` ＋ `journeys/compat_0120.py`，**19／19**；`artifacts/cv/local/compat-0120.json` |
| `CE-10` 資料集 ＋ 四項量測 | ☑ | `seed-dataset.py`（seed 20260819）＋ `measure-conversation.py`；四項全部遠低於門檻（§5） |
| `CE-11` 告警 ＋ runbook | ☑ | 三條規則 ＋ `docs/runbooks/conversation-duplicate-turn.md`；52 條 alert 測試綠 |
| `CE-12` release 九項產物 | ☑ | release note 補上 manifest／flag matrix／retention／rollback／evidence／sign-off；`Verified` 改成引用實際的 JSON |
| `CE-13` `alpha.1` freeze ＋ tag | ◑ | 清單已寫成可執行的 [`docs/release-checklist-alpha2.md`](../../docs/release-checklist-alpha2.md) §2；**tag 需要人** |
| `CE-14` ADR ＋ SR-1 ＋ `alpha.2` tag | ◑ | SR-1 已更新為「兩項發現由執行關閉」；**簽核與 tag 需要人** |
| `CE-15` 回寫 | ☑ | `plan/23/03` §2、`plan/23/08` §4、`plan/23/10` §7／§8、`research/03/CHECKLIST` §0／§1／§2、`research/03/00` §6、`research/03/README` |

## 2. 與計畫的差異

> 每一處寫成：**計畫說什麼 → 實作時發現什麼 → 所以改成什麼 → 要回寫哪一份文件**。
> `plan/23/10` §2 有十二個範例可以照抄形狀。**旅程照出的產品缺陷寫在這裡，
> 不是寫在 commit message 裡。**

### 2.1 ★ `CE-16`：run 的情境包從來沒說平台在哪

**計畫說**（[`02`](./02-e2e-harness.md) §2）：堆疊缺的是 `cliora` 不在 `PATH` 上，
補上 symlink 與 `PATH` 就能讓 Agent 那半邊活起來。

**實際發生**：補完之後 `cliora context show` 成功了，`cliora task say` 卻印
「無法連線到 Cliora（Session 可繼續工作）」——**對著一個正在正常回應 daemon 的平台**。

原因有兩層，第一層是堆疊的，第二層是產品的：

| 層 | 缺什麼 | 落點 |
|---|---|---|
| 堆疊 | `CLIORA_PUBLIC_BASE_URL` 沒設。它是 `compose.yaml` 的必填（`${…:?}`）、`check_env.py` 會擋的值——**一個沒設它的堆疊模擬的是一個不可能存在的部署** | `scripts/e2e/run-stack.sh` |
| **產品** | 設了之後仍然是空的：`render_run_context`／`render_clarification_context`／`render_decomposition_context`／`render_continuation_context` **四份情境包都叫 Agent 用 `cliora`，而沒有一份寫 `API：` 那一行**。CLI 唯一的位址來源就是那一行（`cli.apiBaseFrom`），拿不到就是空字串，於是每一次呼叫都連線失敗 | `backend/app/services/runs.py` |

**所以改成**：在 `_context_for` 的**呼叫點**（不是四份 renderer 裡面）補
`_with_api_base()`。放在呼叫點的理由：位址是部署的性質、不是卡片種類的性質，
而四份複製就是四次「下一個 renderer 忘記」的機會。
`GATE-RQ-CONTEXT-DISPATCH` 仍然 PASS——**第一次的寫法讓它紅了**
（多了一個 chooser 名字），那個紅是對的，所以改的是寫法而不是 gate。

**這一條是 `plan/23/10` §9.1 的第三半**：那一次修好了憑證的檔名（daemon 寫
`run.token`、CLI 讀 `<id>.token`），而**位址那一半還缺著**——有 token、沒有 base，
`cliora task ask` 仍然什麼都到不了，run 仍然以 `RUN_DELIVERY_INCOMPLETE` 收場。
兩半各自的單元測試都是綠的，而**中間那條縫現在有三個地方在守**（見 `j0_agent_seam.py` 的註解）。

**回寫**：`docs/release-note-ticket-conversation.md` 要說 `CLIORA_PUBLIC_BASE_URL`
是 Agent 能回報的前提（[`07`](./07-release-artifacts.md) §3 的 manifest）。

### 2.2 ★★ `CE-17`：沒有 git remote 的卡，run 永遠不會結束

**這是本期到目前為止最重要的發現，而它與對話無關——它是 V2.2 就在的缺陷。**

**症狀**：run 被認領、子行程跑完、log 都收到了，然後**什麼都沒有**。
狀態停在 `running` 直到三分鐘後租約過期。Central 的日誌乾淨，daemon 的日誌乾淨，
兩邊都沒有錯誤。

**原因**：`Summarise` 的 `summary.Remotes` 在兩種情況下是 nil——
repo 沒有 remote，以及**那個目錄根本不是 repo**（每一張 `source: none` 的卡，
也就是每一張釐清卡）。nil 的 `[]string` marshal 成 `null`，
而 contract 說 `git_remotes` 是 `type: array`；Central 的 `decode_control`
以 `INVALID_MESSAGE` 丟棄**整個 `run.complete`**，而且**不回報任何東西**。

**最刺的地方**：`run_handlers.go` 的 `send` 包裝器**已經有這條規則的註解**，
逐字寫著「optional strings 是空的就省略、絕不送 `""`……否則整個 `run.complete`
會被帶走，而症狀會是租約過期而不是一個錯誤」。它只少了一個型別：
`[]string`。而 map 裡的 nil `[]string` **不等於 `nil`**，所以泛用的 nil 檢查也接不到它。

**所以改成**：把那段邏輯抽成 `omitEmptyOptionals()`（可被測試呼叫），加上 slice 的分支。
兩條 Go 測試以 `protocol.ValidateControl` 驗**整個 frame**，
形狀直接沿用 `TestRunnerRegisterPayloadIsValidWithNoCapableRuntimes`——
那是**同一個 bug 的上一次**（`runtimes` 的 nil slice），註解裡也寫著同樣的症狀。
第二條測試守反面：真的有 remote 時那個欄位必須留著，
否則「這個 run 有沒有碰過 remote」這個 ADR 0031 §5 選來取代封鎖的觀測性就沒了。

**為什麼以前沒被發現**：`finish()` 的整合測試直接呼叫服務層、payload 是手寫的良品；
`measure-answer-to-turn.py` 只量到 `started_at`，不需要 run 結束。
**沒有任何測試讓一個真的 daemon 把一個 run 跑完。** 這正是 [`08`](./08-verification-and-exit.md) §2
說的那個差別，而它現在有了一個具體的名字。

**兩個必須進 release 文件的後果**：

1. `f91d9c4`（`agentd` **0.12.0**）逐位元組相同地有同一個 bug
   ——所以出口條件 16（「未升級節點行為不變」）的答案變成
   **「行為相同，而那個相同的行為在這一類卡上是壞的」**。`CE-09` 要把這件事量進去。
2. 修的是 `daemon/internal/connection/run_handlers.go`，在 `GATE-CV-TOUCH-LIST` 的禁區上。
   **不刪那條斷言、也不改 gate 的意思**：`scripts/cv/product-drift-waivers.txt`
   記下路徑、ticket 與一句話，gate **把它印出來**再放行
   （形狀沿用它自己對 `secrets.py` 的處理）。`agentd` 因此要升 **0.13.1**。

### 2.4 `CE-18`：「要求修改」不會開始新的一輪

**計畫說**（[`plan/23/03`](../23/03-conversation-api.md) §2 的 kind 表）：`decision` 的續跑欄是
**「依 decision」**；ADR 0035 的狀態機也畫著 `SpecProposed → Clarifying: 人類要求修改`。

**實際發生**：`decision` 在 `backend/app/` 裡只出現兩次——常數與權限檢查。
**沒有任何路徑替 decision 建立 continuation**，只有 `answer` 會。
所以按下「要求修改」之後，Agent 永遠不會再跑；J1a 第一次寫成「等 v2 提案出現」時，
就在那裡等了 120 秒。

**所以旅程改成**：按「要求修改」→ **人再按一次「派給 Agent」** → v2 提案出現。
那是今天唯一走得通的路，而旅程要走使用者真的會走的路。

**為什麼不修**：D68 第二列（不影響旅程完成）。而且怎麼修是一個產品決定而不是一個 bug fix
——「要求修改」要不要自動續跑，牽涉到「人還沒寫完理由就開始跑」的競態，
以及 `input_from_seq` 該從哪裡算。**進 release note 的 known limitations，
並在 `beta.1` 的計畫裡開一張 ticket。**

**回寫**：[`plan/23/03`](../23/03-conversation-api.md) §2 那一列要改成「否」，
`research/03/02` §2 的狀態機要標明那條邊今天由人工重新派工完成。

### 2.5 `CE-19`：對話面板不會自己更新

`useConversation` 只在 mount 與寫入之後載入；**沒有輪詢、沒有通知**
（`CV-06` 明確不做 WSS）。所以一個開著卡片等 Agent 提問的人，
畫面上什麼都不會變——要重新整理。

三條瀏覽器旅程因此都先用 API 等到 question 出現、再 `page.reload()`。
**這個順序本身是有價值的**：它把「Agent 沒問」與「面板沒顯示」分成兩種不同的失敗。

不修（D68 第二列），但**這一條要進 release note**：
它是使用者第一天就會遇到的事，而目前六條 known limitations 沒有提到它。

### 2.6 `TaskRunDTO` 沒有 `turn_seq` 與 `parent_run_id`

J1a 原本要斷言 `turn_seq` 1→2→3→4。那兩個欄位**不在 DTO 上**，
所以瀏覽器看不到哪一個 run 續了哪一個。旅程改成斷言 `seq` 與 `result`，
續跑鏈由有資料庫的 `j5_chaos.py`／`j8_concurrent.py` 斷言。
`beta.1` 的 Drawer 要顯示「這是第三輪」時會需要它——記在這裡以免那時重新發現一次。

### 2.7 `card_kind: clarification` 一直被忽略

`CreateTaskRequest` **沒有 `card_kind` 欄位**，所以旅程（以及
`measure-answer-to-turn.py`）傳的那個鍵一路被靜默丟掉，卡片其實都是
`implementation`。真正的釐清卡需要一個 requirement
（`TASK_CLARIFICATION_NEEDS_REQUIREMENT`），那是 V2.5 的流程。
**對本期的斷言沒有影響**（對話機制不看卡片種類），但註解與命名已改成說實話。

### 2.3 `GATE-CV-TOUCH-LIST` 現在讀 waiver 檔

計畫（[`08`](./08-verification-and-exit.md) §1.1）只讓 `GATE-CE-NO-PRODUCT-DRIFT` 讀它。
`CE-17` 讓禁區清單也需要同一份檔案，所以兩個 gate 共用一份——
**一份例外清單，兩個問它的人**。

## 3. Gate 結果

```text
V2-C1 gates (baseline: artifacts/cv/local/baseline, f91d9c4)
  PASS  GATE-CV-{PROJECTION-ONE-WRITER,CONTINUATION-REFUSALS,APPEND-ONLY,NO-CLIENT-WAITING-DERIVATION}
  PASS  GATE-CV-CONTRACT-FROZEN
        waived: daemon/internal/connection/run_handlers.go (CE-17 …)
  PASS  GATE-CV-TOUCH-LIST
  PASS  GATE-CV-NO-LOG-IN-THREAD
  PASS  GATE-CV-MIGRATION-ROUNDTRIP
  PASS  GATE-RQ-CONTEXT-DISPATCH (re-run)
  PASS  GATE-SC-SINGLE-DECRYPT (re-run)

V2-C1 closeout gates (baseline: ac3dfef)
        waived: backend/app/services/runs.py (CE-16 …)
  PASS  GATE-CE-NO-PRODUCT-DRIFT
  PASS  GATE-CE-EVIDENCE-FRESH
  ----  GATE-CE-JOURNEY-COVERAGE   四條腳本旅程齊備；瀏覽器報告只在 E2E=1 的那一輪產生
```

**最後一列不是失敗，是設計**：`gate_closeout.py` 在沒有 playwright JSON 報告時紅，
而那份報告只有帶堆疊的那一輪會產生。所以 `scripts/cv/evidence.sh`
在沒有 `E2E=1` 時的正確結論是**「不可 tag」**，而不是綠燈——
一個在乾淨機器上跑完就宣告可以封版的腳本，會讓「七條旅程」變成一句話。

`make check`、Central **1763** 條（基線 1762 ＋ `CE-16` 的回歸測試）、
daemon 全綠（＋2 條 `CE-17` 的 frame 驗證）、前端單元全綠。

**一次完整的 `E2E=1 scripts/cv/evidence.sh`：7 passed, 0 failed, 0 skipped。**

### 3.1 一個排序缺陷，記在這裡因為它會再發生

第一版的 `evidence.sh` 把三個封版 gate 放在第 2 節，也就是**旅程之前**。
`GATE-CE-JOURNEY-COVERAGE` 讀的是旅程產生的檔案，所以它讀到的是**上一輪**的證據——
在跑過一次的機器上綠，在乾淨的 checkout 上紅。**兩個方向裡比較糟的那一個**：
它會在開發者的機器上一直過關，只在別人第一次跑的時候壞掉。
已移到第 4 節（CI 的那條 leg 一開始就是這個順序，所以是 `evidence.sh` 追上 CI）。

## 4. 旅程結果

**2026-08-21，乾淨資料庫，真的 daemon 在輪詢。**

| 旅程 | 層 | 執行 | 結果 | 證據 |
|---|---|---|---|---|
| **J0** preflight（`CE-01`） | API | ☑ | **5／5** | `artifacts/cv/local/journeys/j0-agent-seam.json` |
| **J1a** 三輪釐清 | 瀏覽器 | ☑ | PASS | playwright（`conversation.spec.ts`） |
| **J3** 顯示等待 | 瀏覽器 | ☑ | PASS | 同上 |
| **J5** chaos | API | ☑ | **14／14** | `j5-chaos.json`（`measured: crash before claim`） |
| **J6** 20 則留言 | API | ☑ | **10／10** | `j6-comments.json` |
| **J7** 失敗後重派 | 瀏覽器 | ☑ | PASS | playwright |
| **J8** 併發回答 | API | ☑ | **7／7** | `j8-concurrent.json` |
| **J9** Agent 送 decision | API | ☑ | **8／8** | `j9-decision.json` |

**七條旅程全部通過，沒有一條被 skip。** J1a 走完四輪、兩份提案、兩則人類 decision，
`page.on("framenavigated")` 收集到的路徑裡沒有任何 `/sessions`——
出口條件 11 的「同一個畫面」是一條斷言而不是一句話。

## 5. 量測

**2026-08-21，一次 `scripts/cv/stack-evidence.sh`，乾淨資料庫，真的 daemon 在輪詢。**

| 項目 | 結果 | 目標 | 出口條件？ |
|---|---|---|---|
| **answer → turn 開始 P95** | **4.97s**（中位數 4.95s，20 樣本） | < 10s | **是**（第 1 項） |
| message commit P95 | 8ms | < 500ms | 否 |
| conversation reopen P95 | 5ms | < 500ms | 否 |
| cursor 分頁 P95（深度 500、每頁 200） | 28ms | < 300ms | 否 |
| 20 併發寫同一張卡 | 0 錯、0 個洞、seq 前進 20 | 無錯無洞 | 否（但**有洞就停工**） |

三段拆解仍然是同一個形狀，也仍然是同一個結論：

```text
answer commit            中位數 0.013s   ← Central
queued → claimed         中位數 4.921s   ← runner 的 5 秒 poll
claimed → 子行程啟動       中位數 0.013s   ← runtime
```

**後四項全部遠低於門檻，而那不是好消息也不是壞消息——它是對照組。**
`plan/23/08` §6 的三個數字（500／500／300ms）當時沒有資料支撐；
現在有了第一組實測值，`beta.1` 的 Board 與 Drawer 在同一張表上做更重的查詢時，
才有東西可以說「變慢了」。

資料集：`scripts/cv/seed-dataset.py`，seed 20260819，
200 張卡、深卡 500 則訊息，
實際列數在 `artifacts/cv/local/dataset.json`。

## 6. 封版條件（23 ＋ 5）

### 6.1 `plan/23/08` §7 的 23 項

前 22 項的狀態沿用 `plan/23/10` §6（21 通過）。本期改動四項：

| ☑ | # | 條件 | 現在的證據 |
|---|---:|---|---|
| ☑ | 1 | answer → 新 turn P95 < 10s | **重量一次**：P95 4.97s（§5），`artifacts/cv/local/answer-to-turn.json` |
| ☑ | 5 | daemon 重啟後只處理一次 | **`j5_chaos.py` 14／14**，`measured: crash before claim` |
| ☑ | 11 | 三輪釐清在同一畫面完成 | **J1a**：四輪、兩份提案、兩則人類 decision，`framenavigated` 收集的路徑裡沒有 `/sessions` |
| **◑** | 16 | 未升級的 0.12.0 節點行為不變 | **MEASURED，不是 PASS**。線上相容（認領、提問、continuation、零解碼失敗）；**完成不相容**（`CE-17`）。`compat-0120.json` |
| ☐ | 23 | `v2` → `dev` 由人工核准 | 流程。**本期仍不執行**——全綠只是取得提案資格 |
| ☑ | 其餘 18 項 | | `CE-03` 重跑確認，不重新論證 |

**第 16 項的措辭是本期最重要的一次改寫。** 原本的條件是「行為不變」，
而實測的答案是「**行為相同，包含一個只有升級才會修掉的缺陷**」。
把它記成 PASS 會讓 release note 說謊；記成 FAIL 會讓人以為是本期弄壞的。
所以它是 MEASURED，而 release note 的 Upgrading 一節把兩句話分開寫。

### 6.2 本期新增的 5 項

| ☑ | # | 條件 | 證據 |
|---|---:|---|---|
| ☑ | 24 | 七條旅程全部執行且無 skip | `GATE-CE-JOURNEY-COVERAGE`（讀 playwright 的 JSON 報告 ＋ 四份 journey JSON） |
| ☑ | 25 | 產品程式零 diff 或每處例外有具名 waiver | `GATE-CE-NO-PRODUCT-DRIFT`；兩條 waiver（`CE-16`、`CE-17`），gate 會把它們印出來 |
| ☑ | 26 | `research/03/00` §7 的九項產物齊備 | release note 的九節（[`07`](./07-release-artifacts.md) §2 的表） |
| ☑ | 28 | 四份 ADR `accepted` ＋ SR-1 簽核 | **已記錄（2026-08-21）**：ADR 0035 的狀態區塊寫明是誰、依據什麼、**並追認 proposed 期間已完成的實作**；SR-1 §6 的那一列連同它的來源一起寫進去 |
| ◑ | 27 | 兩個 annotated tag | **被環境擋住**，見 §7 第 1 項——不是決定，是權限 |

**27／28。** 唯一沒有落地的是 `git tag` 本身。

## 7. 未完成

| # | 項目 | 為什麼 |
|---:|---|---|
| 1 | **兩個 annotated tag** | `alpha.2` 的 tag 需要一個 commit，而這個工作階段的 `git add`／`git commit`／`git tag` **被環境的權限分類器擋住**。這不是「留給人決定」——決定已經在上面那一列做了——而是這個階段沒有那個能力。指令、順序與 target 都寫好了：[`docs/release-checklist-alpha2.md`](../../docs/release-checklist-alpha2.md) §2／§3 |
| 2 | **push tag ＋ GitHub pre-release** | **刻意不做。** 兩者都會發佈，而發佈與打 tag 是兩個不同的決定；一個已經 push 出去的 tag 沒辦法安靜地更正 |
| 3 | `alpha.1` freeze checklist 的六項人工驗證 | fresh install／upgrade／downgrade 在 compose 與 Railway 兩條路徑，需要環境與帳號 |
| 4 | 對 `dev` 的 branch protection | 平台設定，不是程式 |
| 5 | `v2` → `dev` | **一律由人決定**，任何自動化都不得執行（`research/03/00` §8） |

**沒有一項是「做了但沒證明」。** 第 1 項是能力，第 2 與第 5 項是刻意的界線，
第 3、4 項需要這個工作階段沒有的環境。

本期知道自己沒量的東西在 [`09`](./09-open-measurements.md)：旅程只在 chromium 跑、
沒有用真的 Claude／Codex 跑過、兩個 histogram 仍未埋、`CONVERSATION_CURSOR_AHEAD` 與
`TURN_ALREADY_QUEUED` 仍然沒有自己的計數器（加它們要動 `backend/app/`，違反 D68）。

## 8. 回寫清單

| 文件 | 回寫什麼 | 狀態 |
|---|---|---|
| [`research/03/README.md`](../../research/03/README.md) | 執行計畫對照表：K1 → `plan/25`、P1 → `plan/26`、E1 → `plan/27`（本目錄佔用 `plan/24`） | ☑ 2026-08-21 先做——它是唯一會讓讀者走錯目錄的一列 |
| [`plan/23/03`](../23/03-conversation-api.md) §2 | `decision` 的續跑欄「依 decision」→ **否**，含理由（`CE-18`） | ☑ |
| [`plan/23/08`](../23/08-verification-and-exit.md) §4 | J3 與 J1a 的斷言更正（[`03`](./03-journeys.md) §0 的兩處） | ☑ |
| [`plan/23/10`](../23/10-implementation-status.md) §7／§8 | 兩項未完成 → 已完成，並記下它們各照出一個缺陷 | ☑ |
| [`research/03/CHECKLIST.md`](../../research/03/CHECKLIST.md) | §0 三列 ＋ 一列新增、§1 的 D51、§2 的 `CV-12`／SR-1／出口條件／tag | ☑ |
| [`research/03/00`](../../research/03/00-roadmap-and-versioning.md) §6 | ahead 60→**64**；RBAC 24→**27** | ☑ |
| `docs/adr/0035`／`0036`／`0037`／`0041` | `proposed` → `accepted`，含來源與**對 proposed 期間實作的追認** | ☑ |
| `docs/security-review-v2c1.md` | §2 第十一列、§3.1、§3.3、§4 findings、§5、§6 簽核 | ☑ |
| `docs/release-note-ticket-conversation.md` | 版本 0.13.0→**0.13.1**、Verified 引用實際 JSON、known limitations 六→**十**、九項產物、sign-off | ☑ |
| `docs/release-checklist-alpha2.md` | 新增：人工封版清單 | ☑ |

**known limitations 從六條變成十條，而那是好消息。** 多出來的四條有三條是旅程照出來的
（`CE-17`／`CE-18`／`CE-19`），一條是設定前提（`CLIORA_PUBLIC_BASE_URL`）。
一份因為真的去跑而變長的限制清單，比一份因為沒人去跑而看起來很短的清單誠實得多。
