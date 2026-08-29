# Cliora `v2.0.0-beta.2` — V2-E1 Ecosystem and Hardening

> **狀態（2026-08-28）：十六張 ticket 全部實作完成，八個波次走完。**
> `scripts/hd/evidence.sh` 前八步全綠（十七 gate、backend 2,154、frontend 852、
> 兩次演練、a11y 0/0、七個 `EXPLAIN`）；**第九步兩個 FAIL，兩個都是人的簽名**。
> J1 **36／36** 對真 daemon 通過——真 GitHub merged PR 經管理 API pin、context pack
> 與 Agent citation，且不可降級的原主旅程仍一個斷言都沒掉。
> 逐項與二十條「與計畫的差異」在 [`11`](./11-implementation-status.md)。
> 上游規劃：[`research/03/12`](../../research/03/12-migration-and-rollout.md) §6 的十二張 `HD-` ticket。
> 前一期：[`plan/26`](../26/README.md)（P1 已實作，出口條件 **40／40 全綠**
> ——SR-3 與 PR #45 於 2026-08-27 簽核；**`v2.0.0-beta.1` 仍未 tag**，那是核准之後的另一個動作）。
> **合併規則不變**：`v2` → `dev` 一律由人決定，出口條件全綠只是取得提案資格。
> 發版到 `master` 時不帶 V2。

Ticket 前綴 `HD-`（Hardening）。

---

## 這一期要交付什麼

一句話：

> **把三件事從「可以動」變成「可以交給別人」**——
> 一個外部世界的事實（PR 合了、版本發了）能進到 Project 記憶並帶著正確的可信層級；
> `blocked` 這個從 V2.0 就存在的雙重語意被真的拆掉而不是再投影一版；
> 而畫面上每一件事都有一條不用滑鼠、不靠顏色、在 200% 縮放下仍然可用的路徑。

`alpha.2` 交付的是「一句話怎麼保證只被做一次」；
`alpha.3` 交付的是「Agent 讀到的每一句話說得出它從哪裡來」；
`beta.1` 交付的是「同一個事實在六個畫面上不會有六種說法」。
**本期的形狀是「這個系統可以被交給一個不是作者的人」**——
而那需要三種東西：一個**能收外部事實**的入口、一份**還完的技術債**、
以及一套**演練過的升級與退版**。

---

## 九個真正的缺口（讀完程式碼與 gate 才看得到的那種）

上游規劃寫的是「要做什麼」。以下九條是把它對到這個 repo 的現況之後，
**規劃層沒有寫、但會決定實作形狀**的事實。每一條都在
[`01`](./01-decisions-and-governance.md) 有對應的裁決。

| # | 缺口 | 證據 | 決策 |
|---:|---|---|---|
| 1 | **兩個 gate 對 provider 讀取形成夾擊。** `GATE-KN-NO-NEW-EGRESS (httpx)` 要求 `backend/app` 內 `httpx` 只能從 `services/providers.py` import；而 `GATE-DV-PROVIDER-VERBS` 用一個 case-insensitive grep 斷言 **那個檔案裡不出現 `merge`／`approve`／`close`／`delete`／`release`／`tag`**。於是 `HD-02`／`HD-03` 照字面寫（`def merge_state`、`"tag"`）會撞上第二個 gate，而放到別的模組會撞上第一個。**更糟的是那個 grep 比它的名字弱**——實測 `/releases` 因為 `\b` 落在 `s` 上而**不匹配**，`"merged_at"` 也不匹配，所以一個小心命名的實作會靜靜通過一個以缺席驗證的紅線 | `scripts/kn/gates.sh:65`、`scripts/dv/gates.sh:99-101`（regex 實測見 [`00`](./00-execution-plan.md) §0.1 D119） | **[D119](./01-decisions-and-governance.md#d119)**：新增 `services/provider_reads.py` 為第二個合法模組；**`providers.py` 一行不動**，且**不利用那個弱點** |
| 2 | **webhook 是上游從提案繼承的假設，不是這個 repo 的形狀。** 整個 `backend/app/api/http/` 的 140 條路由**沒有一條是未認證的**，沒有 rate limiter（`grep -rn 'rate_limit' backend/app` 為空）、沒有 HMAC、沒有 delivery 去重表、沒有 webhook secret kind。而**一個帶 advisory lock 的 reconciler 迴圈已經存在**，連「速率上限從資料推導而不是計數表」都寫好了 | `services/knowledge/worker.py:19,49`、`services/knowledge/repo.py:255`、`api/http/*.py` | **☑ ★ [D120](./01-decisions-and-governance.md#d120)**（2026-08-25 採納）：`beta.2` **只做 pull**。SR-4 的五項縮成兩項保留 |
| 3 | **`knowledge_sources.source_type` 有 CHECK，而且在兩張表上。** 加 `pull_request`／`release` 不是加一個字串：`knowledge_sources` 與 `knowledge_jobs` 各有一個 CHECK、`store.py` 有一個 frozenset、`search.py` 有一份半衰期表。而 `test_every_ingestable_source_type_has_an_activity_kind` 斷言的是 `SOURCE_TYPES - mapped == {"repo_doc"}`——**一個字面集合，加兩個型別它就從「覆蓋率斷言」退化成「一份要維護的清單」** | `0042_knowledge_tables.py:135,267`、`store.py:64`、`tests/db/test_knowledge_ingestion.py:168` | **[D121](./01-decisions-and-governance.md#d121)**：型別加，**同時把「外部觸發」變成 `store.py` 的宣告**，測試讀宣告 |
| 4 | **`reviewed` 這一級的權重早就寫好了，但沒有寫入者，而它的註解說出了原因。** `store.py` 的 docstring 寫著 `reviewed`「arrives with provider sync」，`search.py` 給它 1.15。SR-4 的「merge 前的 PR 內容不自動成為 policy」因此不是一個新機制，是**一個值域限制** | `store.py:36`、`search.py:62` | **[D122](./01-decisions-and-governance.md#d122)**：provider handler 的 authority 值域是 frozenset ＋ gate；`accepted`／`authoritative`／`canonical` **永不可從 provider 資料產生** |
| 5 | **`HD-06` 是 V2 系列第一個不可逆的 migration，而上游把它寫成五個步驟的一段。** `ck_tasks_stage`（`0023_task_board.py:378`）在資料庫裡但**不在 ORM 的 `__table_args__`**；收掉 `'blocked'` 之後 downgrade 可以把值加回去，**但沒有東西記得哪些卡曾經是 stage-blocked**。而三個寫入點（`run_reaper.py:176`、`:246`、`runs.py:1510`）直接寫 `task.stage = "blocked"`，繞過 `TaskService.update()`，**而 `GATE-DV-SINGLE-DONE-PATH` 只掃 `runs.py` 的 `'done'`，看不到它們** | `0023_task_board.py:378`、`run_reaper.py:176,246`、`runs.py:1510`、`scripts/dv/gates.sh:106` | **[D123](./01-decisions-and-governance.md#d123)**：拆成 `0045`（可逆）與 `0046`（不可逆）＋ go／no-go ＋ 全樹 gate |
| 6 | **`HD-05` 的前提不存在。** 上游寫「沿用 `plan/19` baseline 機制，只補新畫面」。`grep -rn 'toHaveScreenshot\|toMatchSnapshot' frontend` **是空的**——`plan/19` 的「baseline」是一疊人工存到 `artifacts/` 的截圖，不是像素比對。所以 `HD-05` 是「建一個」而不是「補幾張」 | `frontend/` 全樹無 snapshot API；`scripts/ui/evidence.sh:29` 的 `[3/9] MANUAL` | **[D124](./01-decisions-and-governance.md#d124)**：用 Playwright 內建 `toHaveScreenshot`（不新增套件）、只釘八個畫面、**門檻是比例不是 0** |
| 7 | **`HD-04` 的前提也不存在，而它需要本期唯一一個新套件。** 沒有任何 a11y 工具（`grep -rn axe frontend/package.json` 為空），而 `GATE-PX-TOUCH-LIST (frontend dependencies)` 正在守著「不新增套件」 | `frontend/package.json`、`scripts/px/gates.sh:151` | **[D125](./01-decisions-and-governance.md#d125)**：`@axe-core/playwright` 是**唯一**新 devDependency，基線推進一格並記錄；**axe 抓不到的那一半要明列成人工 checklist** |
| 8 | **`HD-07` 已經做完了，剩下的是拆除。** `router/index.ts:106` 的 `?tab=` redirect 是 `plan/26` `PX-64` 實作的，註解自稱「visibly temporary」。`client.ts:348` 的 `getBoard()` **有零個呼叫點**，`/board` 已標 `deprecated=True`，而 `GATE-PX-BOARD-UNCHANGED` 與 `test_the_board_card_stays_a_summary` **正在守一個要被刪掉的東西** | `router/index.ts:106`、`api/client.ts:348`、`api/http/tasks.py:313`、`scripts/px/gates.sh:86` | **[D126](./01-decisions-and-governance.md#d126)**：`/board` 整組刪除；`?tab=` **保留到 `rc.1` 並加一個計數器**，有人在用就不刪 |
| 9 | **這一期的一半內容使用者看不到，而這正是 `plan/26` D115 罵過的事。** provider 同步、migration 演練、rollback drill、負載測試——四項對使用者是零可見變化。上游十二張 ticket 裡**沒有一張是畫面**，而前四次 prerelease 的共同點就是每次都有充分的理由讓畫面等一等 | `research/03/12` §6；`plan/26/00` §4b | **[D138](./01-decisions-and-governance.md#d138)**：波次 1 是 **a11y 與視覺回歸**（不是最後）；**新增 `HD-15`** 把 PR／Release 做成 Drawer 上看得見的一段 |

第 1、2 條合起來說明一件事：**上游把 `beta.2` 描述成「加一個 webhook」，
它實際上是一個「決定要不要新增系統第一個未認證入口」的期。**
而在這個 repo 的既有零件下，**不新增它**的版本比較短、比較安全，而且少掉的只有新鮮度。

第 3、4、5 條各自是一個**會靜默通過所有測試**的陷阱。
第 5 條是三者中最貴的：它動的是資料而不是程式碼。

**第 8 條不是缺口而是禮物**——上游一張 ticket 的內容已經有一半在 repo 裡了。

---

## 這一期不做什麼

| 不做 | 為什麼 | 落點 |
|---|---|---|
| **inbound webhook** | 系統第一個未認證入口，而 pull 用既有 reconciler 就能做到同一件事，只差新鮮度（**☑ ★ D120 已裁決**） | ADR 0043 記下設計並標未實作；實作進 `rc` 之後或 Horizon 2 |
| GitLab | `providers.py` 的 `adapter_for` 只有一個 entry，而「GitLab 沒實作」是 D15 刻意留下的可見事實 | Horizon 2 |
| 向量檢索 | D40 已裁決；重啟需獨立 ADR | Horizon 2 |
| 瀏覽器 WebSocket | 新的認證通道 = 新的信任邊界（D95 在 `beta.1` 已裁決，本期不翻案） | Horizon 2 |
| virtualization | 本期把量測從 200 卡推到 2000 卡（D127）；**先量再決定要不要做** | 依 `HD-10` 的量測結果 |
| 新的 RBAC 動作、contract 變更、**任何 daemon diff** | 見 [`00`](./00-execution-plan.md) §3 禁區清單 | — |
| 多人同時對話、notification／inbox | 需要真實使用資料；本期只**收集** | `v2.1.0` |

**本期的 `daemon/` diff 應為零，contract 停在 1.13.0。**
這與 `beta.1` 相同，而且理由相同：本期是 Central ＋ 前端 ＋ 資料。
`GATE-PX-NO-DAEMON-DIFF` 與 `GATE-PX-CONTRACT-FROZEN` 沿用，只換基線。

---

## 文件導覽

| 文件 | 用途 |
|---|---|
| [00-execution-plan.md](./00-execution-plan.md) | **開工前唯一必讀**：**A 類九項裁決**、B 類十一項、八個波次、16 張 ticket、禁區清單、版本節奏 |
| [01-decisions-and-governance.md](./01-decisions-and-governance.md) | **D119–D140** 全文，每一項含「不同意的話會怎樣」 |
| [02-provider-ingestion.md](./02-provider-ingestion.md) | `HD-01`–`HD-03`：`provider_reads.py`、migration `0044`、兩個新 source type、authority transition、reconcile 節奏 |
| [03-stage-final-migration.md](./03-stage-final-migration.md) | `HD-06`：`0045`／`0046`、三個寫入點、go／no-go、失去什麼 |
| [04-accessibility.md](./04-accessibility.md) | `HD-04`：axe 的一半與人工的一半、WCAG 2.2 AA 逐項、200% zoom 與 reduced motion |
| [05-visual-regression.md](./05-visual-regression.md) | `HD-05`：八個畫面、門檻、baseline 放哪、誰負責更新 |
| [06-scale-and-observability.md](./06-scale-and-observability.md) | `HD-10`：2000 卡固定資料集、queue／retention／cost、六個新 metric |
| [07-drills.md](./07-drills.md) | `HD-08`／`HD-09`：兩條部署路徑的 upgrade／downgrade／restore、rollback drill、效能與負載 |
| [08-sunset-and-cleanup.md](./08-sunset-and-cleanup.md) | `HD-07`／`HD-13`：`/board` 刪除、`?tab=` 日落條件、死碼與過期敘述 |
| [09-verification-and-exit.md](./09-verification-and-exit.md) | 十個新 gate、測試矩陣、十六條旅程、**SR-4**、效能預算、**42 項出口條件** |
| [10-open-measurements.md](./10-open-measurements.md) | 本期知道自己沒量的東西與理由，含從 `beta.1` 繼承的四項 |
| [11-implementation-status.md](./11-implementation-status.md) | 實作後回填；**與計畫不同時以這裡為準並回寫計畫**。§0 是要回寫上游的六處 |

## 建議使用方式

1. 先讀 [`00`](./00-execution-plan.md) §0.1 的 **A 類九項**。**☑ 已全部裁決**，
   所以這一步是**讀而不是決定**——但要讀，因為每一項的「不同意的話會怎樣」
   就是實作時不能繞過的那條線。★ D120 的裁決固定了四件事（`0044` 沒有去重表、
   `api/http/` 不新增路由、`secrets.py` 留在禁區、300 秒成為一個要用 metric 證明的產品承諾）。
2. 波次順序照 [`00`](./00-execution-plan.md) §1。**波次 1 是 a11y 與視覺回歸，不是最後**
   ——理由是 `plan/26` D115 的同一條，而本期是它第二次被套用。
3. 每張 ticket 以「決策 → 契約 → 實作 → 自動測試 → 操作證據」完成。
4. **出口條件未通過，不建立 `v2.0.0-beta.2` tag。**
   證據是自己的兩張 ticket（`HD-14`／`HD-12`），不是別人的尾巴。
5. 需求變更先更新 `research/prd.md` 與 `traceability/requirements.json`，
   再同步 [`research/03/11`](../../research/03/11-requirement-traceability.md)。
6. **前置條件**：`beta.1` 的兩項人工動作（`v2` → 上游核准、SR-3 簽名）
   與 `alpha.3` 的兩項（Railway `pg_trgm`、SR-2 簽名）**全部仍然開著**。
   哪些波次被它們擋、哪些不被擋，在 [`00`](./00-execution-plan.md) §1 的表。

## 規劃基準（2026-08-25 實際讀過程式碼確認）

以下每一條都在寫這份規劃時實際讀過程式碼確認，**不是從既有文件抄的**。

| 項目 | 現況 | 讀哪裡 |
|---|---|---|
| `v2` HEAD | `5854325`（`docs(v2-p1): 記下提案 PR #45`）。相對 `master` **ahead 91／behind 0** | `git log`、`git rev-list --left-right --count master...HEAD` |
| tag | `v2.0.0-alpha.1`、`v2.0.0-alpha.2` 已建立。**`alpha.3` 與 `beta.1` 都未建立** | `git tag` |
| contract | **1.13.0** | `contracts/CHANGELOG.md` |
| `agentd` | **0.14.1** | `daemon/VERSION` |
| migration head | **0043**`_work_views_and_rank` | `backend/app/db/migrations/versions/` |
| ADR | 0001–0042 全部存在，**除 `0025`**（那是一個永久缺號，`research/03/README` 已記）。**`0043` 之下沒有可用的空號**——`plan/26` 用掉了最後兩個（0040、0042）；`0043` 已由 `research/03/11` 指派給 provider ingestion，本期從 **0043** 起用 | `docs/adr/` |
| RBAC | **27 個動作、三個全域角色、無 project membership**；`_VIEWER_ACTIONS` 含 `project.view` | `services/rbac.py:92` |
| requirements | **201** 條、**29** 個 family（`FR-WORK` 十二條由 `plan/26` 註冊）。**沒有 `FR-PROV`**；`lifecycle` 129 active／72 proposed | `traceability/requirements.json` |
| **`httpx` 可達模組** | **一個**：`services/providers.py`。`GATE-KN-NO-NEW-EGRESS (httpx)` 斷言 `backend/app` 內沒有第二個 | `scripts/kn/gates.sh:65` |
| **provider 動作** | **三個，表是關的**：create PR、find PR、comment。`GATE-DV-PROVIDER-VERBS` 用 `-iE '(def \|"\|/)(merge\|approve\|request_changes\|close\|delete\|release\|tag)\b'` 掃 `providers.py` | `services/providers.py:1`、`scripts/dv/gates.sh:99` |
| provider token | `project_secrets` 的 `provider_token` kind，**在 `UNDELIVERABLE_KINDS` 裡**（永不下放到節點），per-repository 存在 `project_repositories.provider_token_secret_id` | `services/secrets.py:44,48`、`models.py:1155` |
| **未認證路由** | **零條**。140 條 HTTP 路由全部經 `require_action` 或 `Depends(get_current_*)` | `api/http/*.py` |
| **rate limiter** | **沒有通用機制**。唯一的兩處 429 是 `files.py:62` 與 `knowledge/repo.py:273`，後者**從資料推導而不是計數表** | `grep -rn 'rate_limit' backend/app` 為空 |
| knowledge source type | **八個**，CHECK 在 **兩張表**（`knowledge_sources`、`knowledge_jobs`）＋ `store.py` 的 frozenset ＋ `search.py` 的半衰期表 | `0042_knowledge_tables.py:55,135,267`、`store.py:64`、`search.py:70` |
| knowledge authority | **十級**。`reviewed` 有權重（1.15）**但沒有寫入者**，docstring 寫著它「arrives with provider sync」 | `store.py:36`、`search.py:62` |
| ingest 入口 | **唯一**：`ActivityService.record()` 的 outbox hint。覆蓋率由 `SOURCE_TYPES - mapped == {"repo_doc"}` 這個**字面集合**斷言 | `knowledge/outbox.py:1`、`tests/db/test_knowledge_ingestion.py:168` |
| reconciler | 已存在：`knowledge/worker.py`，`BATCH=32`、`INTERVAL=3s`、`RECONCILE_INTERVAL=300s`、advisory lock、`FOR UPDATE SKIP LOCKED` | `services/knowledge/worker.py:45,48,49` |
| `tasks.stage` | 六值，**CHECK `ck_tasks_stage` 在資料庫但不在 ORM `__table_args__`** | `0023_task_board.py:378`；`models.py:796` 只有 `String(16)` |
| `stage='blocked'` 寫入點 | **三個，全部繞過 `TaskService.update()`**：`run_reaper.py:176`、`run_reaper.py:246`、`runs.py:1510` | 同左 |
| `GATE-DV-SINGLE-DONE-PATH` | 只掃 `services/runs.py`、只禁 `'done'`。**看不到上面三個** | `scripts/dv/gates.sh:106` |
| `/board` | `deprecated=True` 已標；`BoardCardDTO` 16 欄由 `GATE-PX-BOARD-UNCHANGED` 釘死；**前端 `getBoard()` 有零個呼叫點** | `api/http/tasks.py:313`、`api/client.ts:348` |
| `?tab=` 相容 | **已實作**，在 `router/index.ts:106` 一處，註解自稱 temporary | `router/index.ts:95-125` |
| 波次 0 side-car | **路由已刪**，但 `api/http/work.py` 的 module docstring **還寫著它在** | `api/http/work.py:3` vs `@router.get` 清單 |
| 視覺回歸 | **不存在**。`toHaveScreenshot`／`toMatchSnapshot` 在 `frontend/` 全樹為零 | `frontend/` |
| a11y 工具 | **不存在**。`axe` 在 `package.json` 與 `tests/` 為零 | `frontend/package.json` |
| Playwright | 1.61.1 已在 devDependencies；`testDir: ./tests/e2e`，而 `plan/26` 的 spec 在 `tests/px/` | `frontend/playwright.config.ts` |
| 固定資料集 | `scripts/cv/seed-dataset.py`：**200** 卡（80 backlog／40 ready／20 implementing／20 blocked／40 done）、20 張等待卡、500 則訊息 | `scripts/cv/seed-dataset.py:16,59` |
| 效能量測形狀 | **對 service 函式量，不走 HTTP**——「an ASGI round trip would add the same constant to every number」 | `scripts/px/measure-work-api.py:22` |
| 負載工具 | **沒有**（locust／k6／artillery 皆不在依賴中） | `backend/pyproject.toml`、`frontend/package.json` |
| metrics | in-process registry，**label key 走封閉 allowlist**，gauge 刻意不存。knowledge 三個 metric 已有 | `backend/app/metrics.py:1,84` |
| 前端 token | **72** 個 custom property（`^\s+--[a-z0-9-]+\s*:` 的宣告形式；一個較鬆的 grep 會數到 73，因為 `--attention-failed` 的 `var()` 換行讓 `--status-error` 自成一列） | `frontend/src/theme/tokens.css` |
| SCOPE-013 | 實際文字是「**不由平台自建對外反向代理；埠轉發以第三方整合交付**」——**不是**「對外連線只有一個模組」。上游三處把它當成後者引用 | `traceability/requirements.json` |

> 執行計畫與 `research/03/` 不一致時，**以本目錄為準並回寫上游**——
> 本目錄讀的是程式碼，上游讀的是構想。已知需要回寫的六處列在
> [`11`](./11-implementation-status.md) §0，由 `HD-00` 負責。
