# 04 — Filter 語言與 query compiler

> **ticket：`PX-23`。依賴 `PX-22`。**
> [D54](../../research/03/01-architecture-decisions.md)：allowlist 結構，**不做自由 DSL**。

## 0. 一個 model，服務三個地方（[D113](./01-decisions-and-governance.md)）

query string 的 `f=`、`work_views.filter_json`、`work-counts` 的 filter
**是同一個 Pydantic model**。理由逐字採用 kintra `BoardFilterCriteria` 的 docstring：
「兩處各寫一次必然漂移（`P2-D15`）」。

這是 [`10`](./10-verification-and-exit.md) SR-3 第 1 項「counts 與 items 同 predicate」
的型別層版本——兩者一起成立才算數。

> **與 kintra 的分歧**：kintra 的 criteria 是**扁平**的七個具名欄位，
> 沒有 `and`／`or`、沒有深度限制、沒有三個 machine code。
> Cliora 依 [D54](../../research/03/01-architecture-decisions.md) 用樹狀，
> 因為上游的範例需要 `neq`。差異與代價在 [`13`](./13-kintra-port.md) §4。

## 1. 形狀

```json
{
  "and": [
    { "field": "lifecycle",  "op": "in",  "value": ["ready", "in_progress"] },
    { "field": "attention",  "op": "eq",  "value": "waiting_for_your_input" },
    { "or": [
        { "field": "risk",   "op": "eq",  "value": "high" },
        { "field": "priority","op": "eq", "value": "urgent" }
    ]}
  ]
}
```

三種節點：`and`（陣列）、`or`（陣列）、葉節點（`field`／`op`／`value`）。
`not` **不提供**——`neq` 與 `not_in` 覆蓋了實際需求，
而一個 `not` 節點會讓「這個 filter 有沒有排除掉無權資源」變成要遞迴推理的問題。

## 2. 十五個欄位

| field | 型別 | 來源 | 相位 |
|---|---|---|---|
| `lifecycle` | enum(5) | 投影自 `stage` | A |
| `readiness` | enum(3) | 投影自 `tasks.readiness` ＋ process | A |
| `attention` | enum(8) | `derive_attention` | **A ＋ B** |
| `execution_status` | enum(8) | active run | A |
| `is_blocked` | bool | 新欄位 | A |
| `blocking_reason` | enum(7) | 新欄位 | A |
| `owner` | uuid \| `@me` \| null | `owner_user_id` | A |
| `assigned_runner` | uuid \| null | 既有 | A |
| `required_labels` | string[] | JSONB | A |
| `risk` | enum(3) | 既有 | A |
| `priority` | enum | 既有 | A |
| `delivery` | enum | 既有 | A |
| `requirement` / `epic` / `user_story` | uuid \| null | 既有 FK | A |
| `card_kind` | enum(4) | 既有 | A |
| `updated_at` / `created_at` | timestamp | 既有 | A |

（`requirement`／`epic`／`user_story` 算一格，`updated_at`／`created_at` 算一格，
所以是十五個 field 名對應十八個 key——上游的「15 個」指的是概念數，本表照抄。）

### `attention` 是唯一的兩相位欄位

其餘十四個都編譯成一段 SQL。`attention` 依值分兩種編譯路徑：

```python
RUNTIME_ATTENTIONS = frozenset({"no_eligible_runner", "assigned_runner_offline"})

# eq / in 只含 SQL 級   → 純 SQL predicate
# eq / in 只含 runtime 級 → SQL 端縮到 queued 候選集，Python 端過濾
# in 混合兩種           → SQL 端 OR 上 queued 候選集，Python 端補齊
# neq / not_in 含 runtime 級 → 同上取補集
```

**這是整個 compiler 唯一一處「SQL 不是全部答案」的地方**，
所以它被隔離在 `filters.py` 的一個函式 `split_attention_terms()` 裡，
而不是散在編譯器各處。它有六條單元測試（四種組合 ＋ 兩種否定）。

## 3. 八個運算子

`eq`、`neq`、`in`、`not_in`、`gt`、`lt`、`is_null`、`contains`。

| op | 適用 | 編譯成 |
|---|---|---|
| `eq` / `neq` | 全部（`required_labels` 除外） | `col == v` / `col != v` |
| `in` / `not_in` | enum、uuid | `col.in_(v)` / `~col.in_(v)` |
| `gt` / `lt` | timestamp | `col > v` / `col < v` |
| `is_null` | nullable 欄位（`owner`、`assigned_runner`、三個關聯、`blocking_reason`） | `col.is_(None)` / `col.isnot(None)`，依 `value: bool` |
| `contains` | **只有 `required_labels`** | `col.contains([v])`（JSONB `@>`） |

每一組 `(field, op)` 有一條**明確的編譯路徑**，寫在一張 dict 裡：

```python
_COMPILERS: dict[tuple[str, str], Callable[[Any], ColumnElement[bool]]] = { … }
```

**沒有動態 SQL 字串拼接。** 這一條有一個 gate：
`GATE-PX-NO-DYNAMIC-SQL` 用 AST 掃 `services/work/`，
任何 `text()`、f-string 進 `where()`、或 `+` 串接 SQL 即 FAIL。

`value` 的型別在編譯前依 field 檢查：enum 對照 `frozenset`、
uuid 用 `uuid.UUID()` 解析、timestamp 用 ISO 8601、bool 就是 bool。
型別不合回 `FILTER_FIELD_NOT_ALLOWED`？**不**——回 `422` 的既有
`ApiError` 驗證路徑，因為那是值的問題不是欄位的問題。
三個新 machine code 只用在下面三種情況。

## 4. 排序 allowlist

```text
rank | updated_at | created_at | priority | risk | title | card_ref
```

七個，每個可 `asc`／`desc`，最多**兩層**。

**`attention` 不在排序 allowlist 裡**（[D92](./01-decisions-and-governance.md)）：
其中兩級不在 SQL，而一個「大部分正確」的排序比沒有排序更難除錯。
產品上的替代是**用 attention 分組**（group_by 支援它，因為分組是在頁面內做的），
而不是排序。

`priority` 與 `risk` 是字串 enum，排序要照**語意順序**不是字典序
（`urgent > high > normal > low`）。編譯成 `CASE WHEN` 表達式，
常數表在 `filters.py`，並有一支測試斷言它與 `services/tasks.py` 的
`PRIORITIES`／`RISKS` 值域完全對齊——那兩個 tuple 是既有的定義。

## 5. 限制與三個 machine code

| 限制 | 值 | 違規 |
|---|---|---|
| 巢狀深度 | ≤ 3 | `FILTER_TOO_COMPLEX` |
| 葉節點總數 | ≤ 20 | `FILTER_TOO_COMPLEX` |
| `in` / `not_in` 的陣列長度 | ≤ 50 | `FILTER_TOO_COMPLEX` |
| 未知 field | — | `FILTER_FIELD_NOT_ALLOWED` |
| 已知 field ＋ 未允許的 op | — | `FILTER_OP_NOT_ALLOWED` |

**回應必須指名是哪一個 field 或 op**，而且要說出允許的是什麼：

```json
{
  "code": "FILTER_OP_NOT_ALLOWED",
  "message": "`contains` is not available on `lifecycle`",
  "details": { "field": "lifecycle", "op": "contains", "allowed_ops": ["eq","neq","in","not_in"] }
}
```

`allowed_ops` 那一欄是本計畫加的。理由與 `services/runs.py` 的
`_smallest_missing_tags` 相同（「what the reader has to do is make *one* machine
eligible」）：**讀這個錯誤的人要做的事是換一個 op，而不是去翻文件。**

六個負面測試（上游的出口條件）：

```text
1  未知 field                     → FILTER_FIELD_NOT_ALLOWED，details.field 正確
2  已知 field + 未允許 op          → FILTER_OP_NOT_ALLOWED，details.allowed_ops 非空
3  深度 4                         → FILTER_TOO_COMPLEX，details.limit = "depth"
4  21 個葉節點                     → FILTER_TOO_COMPLEX，details.limit = "terms"
5  in 的陣列 51 個                 → FILTER_TOO_COMPLEX，details.limit = "values"
6  contains 用在 required_labels 以外 → FILTER_OP_NOT_ALLOWED
```

## 6. 可見專案述詞（[D93](./01-decisions-and-governance.md)）

```python
# services/work/scope.py — 本期唯一決定「哪些專案」的地方
@dataclass(frozen=True, slots=True)
class ProjectScope:
    """Which projects this caller's query may touch.

    Today the answer is "all of them, if you hold project.view" — there is no
    per-project membership in this deployment (`services/rbac.py`, `_VIEWER_ACTIONS`).
    This type exists **because that will change**, and when it does the number of
    places to edit should be one. `GATE-PX-ONE-PROJECT-SCOPE` asserts that it is.
    """
    all_projects: bool
    project_ids: frozenset[uuid.UUID]

    def predicate(self, column) -> ColumnElement[bool]: ...
```

三條規則：

1. **`work-items`／`work-counts`／`me-work-items` 的每一條 select
   都從 `ProjectScope.predicate()` 取專案述詞。** 沒有例外，
   包括 `project_id` 已經在路徑參數裡的單專案查詢——
   因為那個 `project_id` 是「使用者要看哪一個」，不是「使用者可以看哪一個」。
2. **counts 與 items 用同一個 `ProjectScope` 實例。** 不是「同樣的邏輯」，
   是同一個物件——`work_counts()` 的簽章要求呼叫端把它傳進來。
3. `GATE-PX-ONE-PROJECT-SCOPE` 用 AST 掃 `services/work/`：
   任何對 `Task` 的 `select()` 若其 `where` 不包含 `scope.predicate(...)` 的呼叫，
   即 FAIL；例外清單以具名 allowlist 維護，**而 gate 會把它印出來**
   （沿用 `scripts/kn/gates.sh` 的「印出它honoured 的 exemption」形狀）。

**這個 gate 是本期 SR-3 的主要證據。** 因為在沒有 per-project membership 的
部署上，isolation 測試證明不了什麼（D93），而 gate 證明的是
「未來加 ACL 時只有一個地方要改」——那是今天真正可以承諾的東西。

## 7. `@me` 的展開

`owner` 的值可以是 `"@me"`。它在**驗證階段**就被換成呼叫者的 uuid，
而不是編譯成一個引用 session 的 SQL 表達式：

```python
if term.field == "owner" and term.value == "@me":
    term = replace(term, value=str(actor.id))
```

理由：`work_views.filter_json` 會存下 `@me`，
而一個共用 view 存了 `@me` 時，**每個人看到的是自己的卡**——
那是想要的行為。若在編譯期綁定，這個 view 就會永遠是建立者的卡。
這一條有一個測試：兩個使用者讀同一個含 `@me` 的 project view，得到不同的集合。

## 8. 這一份不負責的

| 不在這裡 | 在哪裡 |
|---|---|
| filter 怎麼變成 URL | [`09`](./09-frontend-architecture.md) §3（D103 的 `f=` 序列化） |
| Filter builder 的 UI | [`06`](./06-board-and-backlog.md) §4 |
| group_by 的值域 | [`05`](./05-work-items-and-view-api.md) §2 |
