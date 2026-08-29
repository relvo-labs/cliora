# 03 — Stage 最終遷移（`HD-06`）

> 上游：[`research/03/12`](../../research/03/12-migration-and-rollout.md) §3.3 的五個步驟。
> 決策：[D123](./01-decisions-and-governance.md#d123)（拆兩個 revision ＋ go／no-go）、
> [D139](./01-decisions-and-governance.md#d139)（跳過也要寫下來）。
> **這是 V2 系列第一個不可逆的 migration。**

## 1. 這張 ticket 在還什麼債

`beta.1` 的 D49／ADR 0040 決定 stage **只做投影**：
`stage='blocked'` 在讀模型上被投影成 `lifecycle='ready' + is_blocked=true + legacy_stage='blocked'`，
資料庫的六值不動。

那是一個對的決定——它讓 `beta.1` 的 migration 全部 additive。
但它留下的狀態是：**同一件事有兩個寫法，而系統同時接受兩個。**

```python
# db/models.py:887 —— beta.1 自己寫下的欠款證明
# The blocked face of ADR 0040 §1, and it is **not the whole truth about being
# blocked** until `beta.2`'s `HD-06`: `stage='blocked'` always projects onto
# blocked regardless of this column, because the platform's three legacy writers
# (`run_reaper.py` twice, `runs.py` once) still set the stage and not this.
# Anyone reading this column directly is wrong about the cards the reaper touched
```

**「Anyone reading this column directly is wrong」** 是這張 ticket 存在的全部理由。
一個布林欄位，讀它會得到錯的答案——而正確的讀法是一個叫
`project_is_blocked()` 的函式。這個狀態每多存在一個 release，
就多一個機會讓某個新查詢直接讀那個欄位。

## 2. 上游沒有寫的三件事

### 2.1 `ck_tasks_stage` 在資料庫裡，但不在 ORM 裡

```python
# db/models.py:796 —— 讀 model 看不到值域
stage: Mapped[str] = mapped_column(String(16), default="backlog")
```

```python
# 0023_task_board.py:378 —— 值域在這裡，三年前寫的
sa.CheckConstraint("stage IN (" + ", ".join(f"'{stage}'" for stage in STAGES) + ")",
                   name="ck_tasks_stage")
```

於是「stage 的合法值是哪六個」這個問題，**讀 `models.py` 得不到答案**。
`HD-06` 要動的正是這個約束，所以第一步是**把它寫進 model**——
不是新增約束，是把一個已存在的資料庫事實搬到看得見的地方。

`Task.__table_args__` 目前只有 `(UniqueConstraint("project_id", "card_ref"),)`。

### 2.2 三個寫入點繞過 `TaskService.update()`，而守門的 gate 看不到它們

```text
services/run_reaper.py:176    task.stage = "blocked"
services/run_reaper.py:246    task.stage = "blocked"
services/runs.py:1510         task.stage = "blocked"
```

而守門的 gate 是：

```bash
# scripts/dv/gates.sh:106 —— 只掃一個檔案、只禁一個值
absent "GATE-DV-SINGLE-DONE-PATH" "a run advanced a card into done" \
  -E '\.stage\s*=\s*["'"'"']done["'"'"']' backend/app/services/runs.py
```

`plan/26` 的 D96 已經記過這個 gate「比它的名字弱得多」，
而那一次的處置是**新增**一個 gate 給 bulk update 用。
這一次的處置要更大一格：**掃全樹、禁 `'blocked'`**。

### 2.3 `LANE_ORDER` 還含 `blocked`

```python
# services/process.py:46
LANE_ORDER = ("backlog", "blocked", "ready", "implementing", "verify", "done")
```

`HD-06` 之後 `blocked` 不再是一個 stage，所以這個 tuple 要少一個成員——
而它是**六欄舊看板的排序來源**，所以改它之前要確認舊看板已經沒有消費者
（`HD-07` 刪掉 `/board` 就是在做這件事，因此 `HD-06` 依賴 `HD-13` 而 `HD-13` 依賴 `HD-07` 的結果）。

## 3. 兩個 revision

### `0045` — 改資料，**完全可逆**

```text
ADD COLUMN tasks.legacy_blocked_at TIMESTAMPTZ NULL

UPDATE  對 stage='blocked' 的每一張卡：
          stage             ← 推導出的 stage（見 §4）
          is_blocked        ← true
          blocking_reason   ← 推導值，推不出來就 'unknown'
          legacy_blocked_at ← now()
          blocking_message  ← 保持 NULL（同 0043 的決定）

程式碼：三個寫入點改成寫 is_blocked ＋ blocking_reason，不寫 stage
        run_reaper.py 兩處 → blocking_reason='human_input' 或 'verification_failed'
                              （依該處的實際情境，讀那兩段的上下文）
        runs.py:1510    → blocking_reason 依該處的失敗原因

downgrade:
        legacy_blocked_at IS NOT NULL 的卡 → stage='blocked'
        DROP COLUMN legacy_blocked_at
        三個寫入點還原（程式碼層面，不在 migration 裡）
```

**`legacy_blocked_at` 唯一的用途**是讓 downgrade 說得出
「這張卡曾經是 stage-blocked」。沒有它，downgrade 只能猜——
而「猜哪些卡要退回 blocked」與 `0043` 拒絕做的「猜 previous stage」是同一類錯誤。

**這一欄會在 `rc` 之後移除**，而那要是一個寫進 release note 的計畫，不是一個遺留。

### `0046` — 收 CHECK，**不可逆**

```text
ALTER TABLE tasks DROP CONSTRAINT ck_tasks_stage
ALTER TABLE tasks ADD  CONSTRAINT ck_tasks_stage
      CHECK (stage IN ('backlog','ready','implementing','verify','done'))

downgrade:
        把 'blocked' 加回 CHECK
        —— **值域還原，資料不還原**
```

**為什麼 downgrade 還原不了資料**：`0046` 之後被阻塞的卡走的是 `is_blocked` 路徑，
它們**沒有 `legacy_blocked_at`**（那一欄只在 `0045` 那一刻被填）。
退版之後它們仍然是 `is_blocked=true`，而不是 `stage='blocked'`。

若舊看板還在（`HD-07` 之前），那些卡會出現在它們的**真實** stage 欄而不是 blocked 欄。
若舊看板已刪（`HD-07` 之後），沒有任何畫面會不一致。
**這是 `HD-07` 必須先於 `HD-06` 的實質理由**，不只是依賴圖上的一條線。

### 退回去失去什麼（要進 release note）

| 退到 | 失去 |
|---|---|
| `0045` | 什麼都沒失去 |
| `0044` | `legacy_blocked_at` 與三個寫入點的行為回到 stage。**`0045` 之後新阻塞的卡的 `blocking_reason` 消失** |
| `0043` | provider 的兩型 source 與其 chunk 全部 drop（可逆，但要重新 ingest） |

## 4. 推導順序（沿用 `0043`，五條而不是七條）

`0043` 已經把上游的七條砍成五條，而砍掉的兩條的理由值得再寫一次：

```text
1  有未滿足的 task_dependencies              → dependency
2  active run 為 waiting_for_input           → human_input
3  ~~最近一次 dispatch 失敗於資格判定~~        ✂ 在 migration 裡不可用
4  ~~指定的 runner 離線~~                      ✂ 在 migration 裡不可用
5  最近 verification 不合格                   → verification_failed
6  有未通過的 gate                            → gate_unmet
7  以上皆非                                   → unknown，列入 report
```

第 3、4 條被砍的理由（`plan/26/02` §5.2）：兩者都要問「這個 node 現在連著嗎」，
而答案在 `NodeConnectionRegistry`——Central 行程內的一個 dict。
`alembic upgrade` 是一個獨立的程序，裡面沒有 registry，
也沒有任何欄位存著它的內容（ADR 0029 §1 明文拒絕存）。

**`0045` 的推導與 `0043` 完全相同**——刻意的。
兩次用同一段邏輯，意思是 `0043` 之後才變成 blocked 的卡，
與 `0043` 當時處理的卡得到同一種答案。

## 5. Go／no-go

`HD-06` 動的是**資料**而不是程式碼，而它的正確性依賴一份
只有在一個跑過 `0043` 的真實部署上才存在的東西：

```text
☐ beta.1 已部署在一個有真實資料的環境
☐ scripts/px/ambiguous-report.py 跑過並產出檔案
☐ 檔案裡 reason='unknown' 的卡全部被人歸類，歸類結果寫回 report
☐ 一個具名的人簽「這份 report 我看過」
```

`ambiguous-report.py` 自己的 docstring 已經寫著這一條：

> **A card is not held up by being on this list.** … What the list gates is `beta.2`'s
> `HD-06`, the migration that removes the legacy `blocked` stage — that one cannot be
> written until somebody has read this.

**四項任一未達 → `HD-06` 整張跳過**，而那是一個要寫下來的決定
（[D139](./01-decisions-and-governance.md#d139)）：ADR 0040 的修訂區塊寫
「本期不還，因為前提 N 未達成；下一次落在 M」。

**現況（2026-08-25）**：`v2.0.0-beta.1` 沒有 tag、沒有部署，
所以這份 report 現在**不存在**。
`HD-06` 的第一個動作不是寫 migration，是**確認能不能拿到它**。

## 6. 新 gate

```bash
# GATE-HD-NO-LEGACY-BLOCKED —— 全樹，不只 runs.py
absent "GATE-HD-NO-LEGACY-BLOCKED" "something still writes stage='blocked'" \
  -nE '\.stage\s*=\s*["'"'"']blocked["'"'"']' \
  --include='*.py' backend/app

# GATE-HD-STAGE-CHECK-IN-MODEL —— 值域要在 model 上看得見
present "GATE-HD-STAGE-CHECK-IN-MODEL" \
  -E 'ck_tasks_stage' backend/app/db/models.py
```

**第一個 gate 為什麼掃全樹**：`GATE-DV-SINGLE-DONE-PATH` 只掃 `runs.py`，
於是 `run_reaper.py` 的兩處在它的視野外三年。
一個只掃一個檔案的 gate 保護的不是一個不變式，是一個檔案。

**第二個 gate 為什麼是 present 而不是 absent**：它斷言的是
「有人把資料庫的約束寫進了 model」，而那是一個要**存在**的東西。
本期的 gate 大多是 absent（以缺席驗證），這一個刻意相反——
因為它防的是「改完 CHECK 忘了同步 ORM」，而那個遺漏的表現是沉默。

## 7. 出口條件（本節）

| ☐ | 條件 | 證據 |
|---|---|---|
| ☐ | **go／no-go 四項全綠，或 `HD-06` 明確跳過並記進 ADR 0040 修訂** | report ＋ 簽名，或 ADR 修訂區塊非空 |
| ☐ | `0045` upgrade → downgrade → upgrade，`legacy_blocked_at` 的卡完整還原 | roundtrip 測試 ＋ 逐卡比對 |
| ☐ | `0046` upgrade → downgrade，值域還原且**失去什麼已寫進 release note** | roundtrip ＋ release note |
| ☐ | 三個寫入點全部改寫，`GATE-HD-NO-LEGACY-BLOCKED` 全綠 | gate |
| ☐ | `ck_tasks_stage` 在 `models.py` 上，`GATE-HD-STAGE-CHECK-IN-MODEL` 綠 | gate |
| ☐ | `LANE_ORDER` 少一個成員，且沒有消費者壞掉 | `HD-07` 的 OpenAPI diff ＋ 前端測試 |
| ☐ | ambiguous report 從 N 筆變 0 筆 | 遷移前後兩份 report |
| ☐ | `is_blocked` 可以被直接讀了——`models.py:887` 那段警語已刪除 | diff |
