# 03 — `SC-05`：tag 派工、五條件資格判定與空等的原因

## 1. 現況

`backend/app/services/runs.py` 有**兩個**判資格的地方，而它們今天各寫一份條件：

| 位置 | 用途 | 現在的條件 |
|---|---|---|
| `_eligible()`（`runs.py:455`） | 真正的 offer 查詢，`poll()` 呼叫 | `status=queued` ＋ `stage=ready` ＋ 不在 `blocked` 子查詢 ＋ 指定為 null 或等於自己 ＋ runtime |
| `_eligible_runner_count()`（`runs.py:346`） | 算 `waiting_reason`，`resolve_waiting_reason()` 呼叫 | 線上 ＋ `enabled` ＋ runtime |

第二個是**用 Python 迴圈算的**（`select(AgentRunner).where(enabled)` 之後 `sum(...)`），
因為它要呼叫 `is_online(node_id)` 這個來自 registry 的述詞——那不是 SQL 能表達的東西。

**這是本期最容易漏的一格**（`README` 易錯 7）：只改第一個，
畫面會說「等待可用的 Agent」而真相是「沒有 runner 有這些 tag」。

`_eligible()` 的 docstring 目前還寫著「V2.3 adds the `project_agents` join, and it goes
**first**, because by then it authorises secrets」——**那件事被取消了**（`01-…md` §5b 第 6 條）。
這張票一定會動到那段文字，順手改對。

## 2. 五條件資格判定

### 2.1 最終形狀

一個 run 會被 offer 給一個 runner，當且僅當：

1. 任務在 `ready`
2. `dependsOn` 全滿足
3. runtime 相符
4. **tag 相符**（本期新增）
5. `assigned_runner_id` 為 null，**或**正好是這個 runner

### 2.2 tag 相符的兩個子條件（GitLab 語意）

```sql
-- ① 超集比對：卡片要的 tag 是 runner 有的 tag 的子集
AND (t.required_labels IS NULL
     OR jsonb_array_length(t.required_labels) = 0
     OR t.required_labels <@ :runner_labels)

-- ② run_untagged：關掉的 runner 只領有宣告 tag 的卡片
AND (:run_untagged
     OR jsonb_array_length(coalesce(t.required_labels, '[]'::jsonb)) > 0)
```

`<@` 是 PostgreSQL 的 jsonb「被包含於」。**方向很容易寫反**：
`required_labels <@ runner_labels` 讀作「卡片要的被 runner 有的包含」——
runner 多幾個 tag 不影響，這正是 GitLab 的語意。
寫成 `@>` 的後果是**只有 tag 完全相等的 runner 才領得到**，
而那在實務上不可用（`01` D18 的 Alternatives rejected 第 3 列）。

⚠️ **一條測試要專門釘住方向**：runner 有 `["docker","node20","gpu"]`，
卡片要 `["docker"]` → **領得到**。反過來 runner 只有 `["docker"]`、卡片要
`["docker","node20"]` → **領不到**。兩個方向各一條，因為 `<@`／`@>` 寫反時
其中一個方向仍然是綠的。

### 2.3 SQLAlchemy 的落地

```python
def tag_match_clause(runner: AgentRunner):
    """條件 4，作為 SQL。`_eligible()` 用它。"""
    labels = cast(runner.labels or [], JSONB)
    declared = func.jsonb_array_length(func.coalesce(Task.required_labels, text("'[]'::jsonb")))
    subset = or_(declared == 0, Task.required_labels.op("<@")(labels))
    if runner.run_untagged:
        return subset
    return and_(subset, declared > 0)


def tag_match(runner: AgentRunner, task: Task) -> bool:
    """條件 4，作為 Python。`_eligible_runner_count()` 與 dispatch 的 409 用它。"""
    required = set(task.required_labels or [])
    if not required:
        return bool(runner.run_untagged)
    return required <= set(runner.labels or [])
```

**兩個函式，一組測試。** 參數化測試餵同一批 `(runner_labels, run_untagged, required_labels)`
案例給兩者，斷言結果相同。這是 D11 的機器形式，而 `GATE-SC-TAG-BOTH-QUERIES`
用 `ast` 斷言 `_eligible` 與 `_eligible_runner_count` 都引用了對應的那一個
（而不是各自 inline 一份條件）。

**為什麼不用一份 SQL 就好**：`_eligible_runner_count` 的第一個條件是
`is_online(node_id)`，那是 registry 裡的記憶體狀態，不在 DB 裡。
把它硬塞進 SQL 需要把線上狀態寫回 DB，而那正是 `plan/18` D9 拒絕的
「假指示燈」。所以兩份實作是必要的，而**兩份實作必須被同一組測試釘在一起**。

### 2.4 `_eligible()` 的改法

在 runtime 條件之後接上 `tag_match_clause(runner)`。**順序有意義**：
資格條件的順序決定了「這張卡為什麼沒被 offer」在 explain 上的可讀性，
而 runtime 在前的理由是它比 tag 便宜（一個 `IN`，不是 jsonb 運算）。

docstring 改寫成五條件，並把「兩個 reader 會期待的 join 不在這裡」那一段
換成一句話：**`project_agents` 不存在，也不會存在（ADR 0032 §0）**。

## 3. 「這張卡為什麼沒人領」——反向查詢

出口條件 3e／判準 9 要求的不是一句文案，是一個**答得出缺什麼**的查詢。

`RunService.resolve_waiting_reason()` 現在回三個字之一
（`any`／`assigned_offline`／`no_eligible_runner`）。本期讓第三種帶上細節：

```python
@dataclass(frozen=True, slots=True)
class WaitingReason:
    kind: str                       # any | assigned_offline | no_eligible_runner
    missing_tags: list[str] = ()    # 只有 no_eligible_runner 且原因是 tag 時非空
    runner_name: str | None = None  # 只有 assigned_offline 時非空
```

`missing_tags` 的算法，**刻意是最保守的那一種**：

> 對每一個「線上 ＋ 啟用 ＋ runtime 相符」的 runner，算出這張卡缺的 tag 集合；
> 取所有 runner 之中**最小的那一個缺集**。全部 runner 都缺同樣多時取字典序最小的。

為什麼是「最小缺集」而不是「所有 runner 都沒有的 tag 的交集」：
使用者要做的事是**讓某一台機器變成合格的那一台**，而最小缺集直接回答
「離合格最近的那台還差什麼」。交集會在只有一台 runner 缺 `gpu`、
另一台缺 `docker` 時回一個空集合，而那句「沒有 runner 缺任何 tag」是錯的。

**沒有任何線上 runner 時** `missing_tags` 是整張卡的 `required_labels`，
文案是「目前沒有任何線上的 Agent；這張卡需要 `docker`、`node20`」——
兩個資訊一起給，因為它們指向兩件不同的補救。

**這個查詢與 offer 查詢寫在同一支 service 裡**（`research/02/09` §5 的要求），
理由是它們必須一起改：任何一條資格條件加進 `_eligible` 而沒加進這裡，
空等的原因就會開始說謊。

## 4. dispatch：指定不創造資格（D17b）

`RunService.dispatch()` 的第 ④ 步現在檢查兩件事（`enabled`、`runtime`）。本期加第三件：

```python
if not tag_match(runner, task):
    missing = sorted(set(task.required_labels or []) - set(runner.labels or []))
    if missing:
        raise ApiError(
            "AGENT_TAG_MISMATCH",
            f"Agent '{runner.name}' 缺少 " + "、".join(f"`{t}`" for t in missing),
            409, details={"runner_name": runner.name, "missing_tags": missing},
        )
    # required_labels 為空而 runner.run_untagged 為 false
    raise ApiError(
        "AGENT_REFUSES_UNTAGGED",
        f"Agent '{runner.name}' 只領取有宣告 tag 的卡片",
        409, details={"runner_name": runner.name},
    )
```

**兩種錯誤碼不是一種**，因為使用者要做的事不同：
第一種是「給這張卡加 tag，或換一台機器」，第二種是「這張卡沒宣告 tag，
而那台機器被保留給有宣告的工作」。合成一句「不符資格」會讓第二種看起來像設定壞了。

**訊息指名缺哪幾個 tag**（出口條件 3d）。這是本期第一次有東西可以測 D17b 邊界 2。

### 4.1 dispatch 的其餘兩處改動

**第 ② 步：`required_secrets` 從「拒絕」換成「驗證」**（`runs.py:225`）：

```python
if task.required_secrets:
    allowed = set(project.allowed_secret_names or [])
    unknown = sorted(set(task.required_secrets) - allowed)
    if unknown:
        raise ApiError("TASK_SECRETS_NOT_ALLOWED", …, 409,
                       details={"unknown": unknown, "settings_hint": f"/projects/{project.id}#secrets"})
    missing = await SecretService(...).missing_names(project.id, task.required_secrets)
    if missing:
        raise ApiError("TASK_SECRETS_MISSING", …, 409, details={"missing": missing})
```

**兩種檢查不是一種**：`unknown` 是「這個名稱不在 allowlist 裡」（改 Project 設定），
`missing` 是「在 allowlist 裡但還沒建立或已被刪除」（去建一枚）。
第二種是刪除機密之後最常見的失敗（`02-…md` §4.4），它必須自己有一句話。

**`UNSUPPORTED_DELIVERIES` 拿掉 `branch`**（`runs.py:93`，D16）：

```python
UNSUPPORTED_DELIVERIES = {"pull_request": "V2.4", "existing_pr": "V2.4"}
```

`delivery: branch` 從本期起是主路徑之一。訊息維持「從 V2.4 起生效」。

### 4.2 `error_catalog` 的三處

`backend/app/api/error_catalog.py:1008/1012` 與 `frontend/src/utils/errorCatalog.ts:651`
現在寫著「Cards that declare required secrets can be dispatched from V2.3」與
「移除該宣告以在沒有機密的情況下執行，或等 V2.3」。**兩處都要改寫**，
而不是刪掉——那個錯誤碼還在，只是它的意義從「階段還沒到」變成
「名稱不在 allowlist 裡」。新增三個碼：`TASK_SECRETS_NOT_ALLOWED`、
`TASK_SECRETS_MISSING`、`AGENT_TAG_MISMATCH`、`AGENT_REFUSES_UNTAGGED`。

## 5. `run.offer` 的 `secrets` 從哪裡來

`RunOffer.spec()`（`runs.py:121`）加一段：

```python
if self.secrets:
    spec["secrets"] = [{"name": n, "value": v, "kind": k} for n, v, k in self.secrets]
```

而 `self.secrets` 由 `poll()` 在**認領成功之後**填入（D1）：

```python
secrets = ()
if task.required_secrets:
    secrets = await SecretService(self._session).materialise(
        project_id=run.project_id, names=task.required_secrets,
        run_id=run.id, runner_id=runner.id,          # 稽核用
    )
```

四個要一起成立的性質：

1. **在認領之後**：一張沒被領走的卡不該解密任何東西。
2. **不 await 任何 node 往返**：`materialise` 只碰 DB 與 CPU。
   `GATE-AR-NO-REQUEST-IN-LOOP` 已經在守 `runs.py`，本期不放寬它。
3. **稽核與 `last_used_at` 在同一個 flush**。
4. **`kind` 一起送**，因為 daemon 要用它決定機密去哪裡（D5）。

### 5.1 `accept_secrets: false` 的落地（代償第 2 條）

node 在 `runner.register` 帶 `accept_secrets`（預設 `true`），
存進 `agent_runners.accept_secrets`（**這一格也在 `0033`**）。

第六個資格條件？**不是。** 它寫成 `_eligible()` 裡的一個 `WHERE`：

```sql
AND (:accept_secrets
     OR jsonb_array_length(coalesce(t.required_secrets, '[]'::jsonb)) = 0)
```

**為什麼不算成「第六條件」**：五條件是資格判定的公開語彙
（ADR 0029、PRD、UI 都用它），而 `accept_secrets` 是 node 對自己的宣告，
與 `run_untagged` 同一類——它是條件 4 的同族，不是新的一層。
文件上把它寫成「條件 4 的兩個 node 端開關之一」。

⚠️ **`_eligible_runner_count` 與 `resolve_waiting_reason` 也要涵蓋它**，
否則一張需要機密的卡在只有 `accept_secrets: false` 的 node 上會顯示
「等待可用的 Agent」——同一個 D11 的錯誤，換一個欄位。

## 6. 測試

`backend/tests/db/test_tag_dispatch.py`：

1. **超集比對的兩個方向**（§2.2 的兩條）。
2. `run_untagged: false` 的 runner 領不到無 tag 的卡；同時線上的
   `run_untagged: true` runner 照常領走它（**兩台一起跑一次**，判準 7）。
3. `run_untagged: false` 的 runner 領得到有宣告 tag 且相符的卡。
4. register payload **沒帶** `run_untagged` → 存成 `true`，行為與升級前一致（D12、出口條件 3f）。
5. 指定一個缺 `docker` 的 runner → 409 `AGENT_TAG_MISMATCH`，
   `details.missing_tags == ["docker"]`，**且 `task_runs` 沒有新列**（不入佇列）。
6. 指定一個 `run_untagged: false` 的 runner 給一張無 tag 的卡 → 409 `AGENT_REFUSES_UNTAGGED`。
7. **`tag_match_clause` 與 `tag_match` 對同一批案例結果相同**（參數化，≥12 組）。
8. 沒有 runner 湊得齊 → `waiting_reason.kind == "no_eligible_runner"` 且
   `missing_tags == ["docker","node20"]`（判準 9）。
9. 一台缺 `gpu`、一台缺 `docker` → `missing_tags` 是**最小缺集**而不是交集（§3）。
10. `accept_secrets: false` 的 node 永不被 offer 需要機密的卡（判準 5），
    且它的存在不會讓空等原因說成「等待可用的 Agent」。
11. `required_secrets` 不在 allowlist → 409 `TASK_SECRETS_NOT_ALLOWED` 指名；
    在 allowlist 但機密不存在 → 409 `TASK_SECRETS_MISSING` 指名。
12. `delivery: branch` 可以 dispatch；`pull_request` 仍 409 且訊息說 V2.4。

**第 7 條是本期最有價值的一條測試**，因為它是唯一一條在
「有人日後只改了其中一個查詢」時會紅的東西。
