# 07 — Release 產物與封版（`CE-12`、`CE-13`、`CE-14`）

## 1. 先打 `alpha.1`，再打 `alpha.2`（D72）

`git tag -l` 現在是空的。這件事有兩個直接後果：

1. `alpha.2` 的 release note 寫「升級自 `v2.0.0-alpha.1`」時，那句話指向一個不存在的東西；
2. `research/03/02` 的前置條件（「`alpha.1` freeze checklist 完成」）從來沒有被滿足，
   而 `alpha.2` 的程式已經在它上面疊了四個 commit。

**處置：本期產出兩個 tag，順序不可顛倒。**

```bash
git tag -a v2.0.0-alpha.1 f91d9c4 -m "…"      # target 是 f91d9c4，不是 HEAD
git tag -a v2.0.0-alpha.2 <closeout-commit> -m "…"
```

`alpha.1` 的 target 是 `f91d9c4`——`research/03/00` §1.3 已經定過：
「commit 一改就改成 `alpha.2`，**不移動 `alpha.1`**。一個會移動的 tag 不是版本，是書籤。」

`alpha.2` 的 target 是本期最後一個 commit（旅程、腳本、文件都進去之後）。
**不是 `ac3dfef`**：那個 commit 沒有旅程，而旅程是這個 tag 之所以能被建立的理由。

### `alpha.1` freeze checklist 十項（`CE-13`）

沿用 `research/03/00` §6，逐項落到本期：

| ☐ | 事項 | 本期怎麼做 |
|---|---|---|
| ☐ | tag target 仍是 `f91d9c4` | `git rev-parse` 比對；不符**不移動舊 tag**，改版號 |
| ☐ | 乾淨環境重跑 gates 與測試 | `CE-03` 的 `scripts/cv/evidence.sh`，**在 `f91d9c4` 的 worktree 上跑一次**（`CE-09` 已經會建那個 worktree，共用） |
| ☐ | CI 可觀測性 | `CE-08` 的第三條 leg。若某一項仍無法進 CI，保存手動輸出並開 issue（`research/03/00` §6 的退路） |
| ☐ | component manifest | §2 的表 |
| ☐ | fresh install／upgrade／downgrade | `deploy/compose` 一次；Railway 一次。downgrade 的斷言沿用 `GATE-CV-MIGRATION-ROUNDTRIP` |
| ☐ | flag 全關 = V1 行為 | `scripts/pj/gate-flag-off.sh` **已經存在**，直接跑；補一條 `CLIORA_AGENT_RUNS_ENABLED=false` 的 leg |
| ☐ | known limitations | `alpha.1` 的六條已在 `docs/release-note-requirements-and-decomposition.md`（`plan/23/10` §9.3 補的） |
| ☐ | 標明 diverged 狀態 | **ahead 64／behind 6**（本期實測值，不是規劃時的 60／6） |
| ☐ | 人工 security／release sign-off | 與 `CE-14` 的 SR-1 簽核同一次 |
| ☐ | annotated tag ＋ GitHub pre-release | 勾選 pre-release |

**第二列有一個陷阱**：在 `f91d9c4` 的 worktree 上跑測試，
用的是**現在的資料庫**。`0040` 已經套用過的資料庫跑 `f91d9c4` 的測試會出現
「表多了兩張」——那些測試不會因此紅（它們不斷言表的集合），但 migration
相關的斷言會。做法是給 worktree 一個自己的資料庫（`cliora_alpha1`），
並在 `dataset.json` 的兄弟檔 `alpha1-evidence.json` 裡記下它的名字。

## 2. 九項必要產物（`research/03/00` §7）

| # | 產物 | 現況 | `CE-12` 要補什麼 |
|---:|---|---|---|
| 1 | Release note | ☑ `docs/release-note-ticket-conversation.md`（157 行） | 「Verified」一節改成引用本期的證據（旅程、相容性、四項量測） |
| 2 | Known limitations | ☑ 六條 | 第 6 條（未升級節點是論證不是證據）**在 `CE-09` 之後刪除**；新增：CLI 新旗標需要升級節點、兩個 machine code 沒有 metric |
| 3 | **Compatibility manifest** | ☐ 散在各處 | §3 的表，單獨一節 |
| 4 | Migration／rollback note | ◑ 有 upgrade 一行 | 補 rollback：`alembic downgrade 0039` 之後**會失去什麼**（question 表、consumer cursor、seq 欄位；訊息本身不會遺失） |
| 5 | Security delta | ☑ 有一節 ＋ SR-1 | SR-1 簽核後把「unsigned」那句改掉 |
| 6 | Test／gate evidence | ◑ 只有數字 | `artifacts/cv/local/` 的清單與**在哪台機器、什麼版本、什麼 commit** |
| 7 | **Feature flag matrix** | ☐ 完全沒有 | §4 的表 |
| 8 | **Data retention delta** | ◑ 在 limitation 4 提過一句 | 單獨一節：本期新增哪些會長期存在的資料 |
| 9 | Manual sign-off record | ☐ | `CE-14`：具名、日期、簽了什麼 |

## 3. Compatibility manifest

```text
Central          commit <closeout>          （v2 分支，相對 master ahead 64 / behind 6）
agentd           0.13.0                     （最低相容：0.12.0，已實測，見 CE-09）
contract         v1.13.0                    （相對 alpha.1 逐位元組相同）
migration head   0040_ticket_conversation   （可 downgrade 至 0039）
PostgreSQL       16                         （無新增 extension）
RBAC 動作        27                         （未新增；注意：舊文件寫 24 是錯的）
Feature flags    CLIORA_PROJECTS_ENABLED, CLIORA_AGENT_RUNS_ENABLED
                 （CLIORA_PROJECT_EXPERIENCE_V2 是 beta.1 的，本版不存在）
```

最後一行要寫出來：`research/03/README` 的「三個獨立旗標」表列了三個，
而第三個在 `alpha.2` 的程式裡**還不存在**。讀 release note 的人若去找它會找不到。

## 4. Feature flag matrix

| `PROJECTS` | `AGENT_RUNS` | 預期行為 | 證據 |
|---|---|---|---|
| `false` | 任意 | V1 行為：`/api/projects/*` 與 `/api/agents/*` 全部 404；畫面無 Project 分頁 | `scripts/pj/gate-flag-off.sh`（既有）；`v2-projects.yml` 的 `projects=false` leg |
| `true` | `false` | 看板可用；派工路徑 404；**對話 API 可讀可寫**（它掛在 project 層不是 agent 層） | `CE-12` 新增一條斷言 |
| `true` | `true` | 完整 `alpha.2` | 七條旅程 |

**第二列是本期才問得出來的問題**，而它的答案不是猜的：
`GET/POST /api/tasks/{id}/messages` 定義在 `agents.py` 但掛在 `router`（project 層），
只有 `/api/cli/runs/*` 在 `run_router`。所以 agent 旗標關著時，
人還是可以在卡片上留言與回答——只是沒有 Agent 會被喚起。
**這是合理的行為，但它從來沒有被寫下來過**，而一個沒有被寫下來的行為
在下一次有人「順手把兩個旗標綁在一起」時會消失。

## 5. Data retention delta

| 資料 | 保留 | 誰清得掉 |
|---|---|---|
| `task_messages`（含 question／proposal／decision） | **永久**（ADR 0041） | 只有 project 刪除的 cascade |
| `task_questions` | 永久 | 同上 |
| `conversation_consumers` | 永久（每個 consumer 一列，數量有界） | 同上 |
| `task_runs`（含 continuation） | 沿用既有 run retention | retention sweep |
| `run_logs` | **14 天**（未變） | 既有 sweep |

**這張表要與 limitation 4 對照著讀**：訊息永久保留是一個決定
（「一張卡的對話就是它為什麼被這樣做出來的紀錄」），
而 run log 仍然會過期。出口條件 12（清除全部 run log 後對話完整）
守的就是這兩者的分離。

## 6. `CE-14`：三件事同一天

依 D74，順序是**證據 → 簽核 → tag**：

```text
① 出口條件 28 項全綠（08 §4）
② ADR 0035 / 0036 / 0037 / 0041 → Status: accepted（含追認實作先於 accepted 的那段）
③ SR-1 具名簽核（docs/security-review-v2c1.md §6 的表填上）
④ git tag -a v2.0.0-alpha.2
⑤ GitHub pre-release，附 artifacts/cv/local/ 的證據清單
⑥ v2 → dev 的合併提案（★ 由人決定，本期不執行）
```

第 ⑥ 步刻意留在清單裡但不執行：`research/03/00` §8 與本 repo 的記憶
都寫著「`v2` → `dev` 一律由人工確認，條件全綠只是取得**提案資格**」。
把它列出來是為了讓「已經取得資格」與「已經合併」不會被混為一談。

**發版到 `master` 時不帶 V2**：從 V2 系列之前切 `release/*` 分支，不用 `dev` 當 head。
這一條與本期無關，但它每次都被問一次，所以每次都寫一次。
