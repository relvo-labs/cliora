# 12 — V2.2_1 前端修復期（UI／UX）

> **狀態：已實作，2026-08-12；DB-backed browser 證據待 PostgreSQL 環境重跑。**
> 執行紀錄在 [`plan/19/09-implementation-status.md`](../../plan/19/09-implementation-status.md)。
> ticket 前綴 `UI-`。

這一期不是「把畫面弄漂亮」。它修的是一個**已經量得出來的缺陷**：
V2.0–V2.2 交付的前端引用了 **104 個從未定義的 CSS custom property**，
瀏覽器把那些宣告整條丟棄，所以看板、任務詳情、藍圖三個 V2 主畫面
**實際上是以接近無樣式的 HTML 在渲染**。

`research/prototype-v2/` 那份 prototype 早就把正確的樣子做出來了，
只是它的結論從來沒有被搬進 `frontend/`。這一期就是把那條路走完。

---

## 0. 診斷：三層缺口，不是一層

三層必須分開講，因為**修好第一層畫面就不再醜，但那三個要被看見的狀態仍然看不見**。

### 第 1 層 — 機械層：104 個未定義的 token，其中 83 個真的壞掉

`frontend/src/theme/tokens.css` 定義 **27** 個 custom property（`base.css` 定義 0 個）。
`frontend/src/` 引用 **43** 個。中間差的 16 個名字**從來不存在**，被引用了 **104 次**。

**但這 104 次分成兩種，後果完全不同**，而這個區分正是整份診斷最關鍵的一段：

| | 寫法 | 後果 |
|---|---|---|
| **83 次** | `var(--space-2)` — **沒有 fallback** | `var()` 解不開 → **整條宣告被丟棄** → 真的壞掉 |
| **21 次** | `var(--status-danger, crimson)` — **有 fallback** | 宣告有效，用 fallback 值渲染 → **不壞，但繞過了 token 系統** |

而這兩種寫法**沿著檔案乾淨地分開**：

| 檔案 | 壞掉／總數 |
|---|---|
| `components/project/TaskBoard.vue` | **31 / 31** |
| `components/project/TaskDetail.vue` | **26 / 26** |
| `components/project/TaskRoadmap.vue` | **17 / 17** |
| `views/RequirementDetailView.vue` | **5 / 5** |
| `views/TaskDetailView.vue` | **4 / 4** |
| `views/ProjectDetailView.vue` | 0 / 8 |
| `views/ProjectsView.vue` | 0 / 4 |
| `components/session/NewSessionDialog.vue` | 0 / 3 |
| `views/AgentsView.vue` | 0 / 2 |
| `SessionWorkspaceView`／`RunDetailView`／`EnrollmentView`／`FileTreeNode` | 0 / 各 1 |

**上面五個 100% 壞掉的檔案，就是 V2.1 的任務層畫面**——看板、任務詳情、藍圖、
任務詳情頁、需求詳情。下面八個有 fallback 的，是 V2.0／V2.2／V1 的畫面。

換句話說：**寫任務層那批畫面的人，83 個引用一個 fallback 都沒寫，所以那批畫面
整組是壞的；寫其他畫面的人全程有 fallback，所以那些畫面看起來正常。**
這不是隨機分佈的疏漏，是兩種習慣，而其中一種產出了三個完全無樣式的主畫面。

### 21 個有 fallback 的也要修，但理由不同

它們不會壞，但它們**把 token 系統繞過去了**——實際渲染出來的是
`crimson`、`seagreen`、`darkorange`、`#d0d0d0` 這些**寫死在 fallback 位置的顏色**。

一個有 design token 檔的專案裡出現 `crimson`，靠的就是這個管道。
所以它們照修，但要知道：**修它們會改變畫面顏色**（從 `crimson` 變成 `--status-error`
的 `#d25454`），那是使用者看得見的變化，要有人確認過。

那 16 個不存在的名字分成四類，每一類都是**同一個錯誤的四種形狀**——
有人憑印象寫了一套 token 命名，而不是讀 `tokens.css`：

| 類別 | 寫成 | 實際存在的名字 |
|---|---|---|
| 顏色改用 `--color-*` 命名空間 | `--color-text-muted`、`--color-border`、`--color-surface`、`--color-surface-2`、`--color-warning`、`--color-success` | `--text-muted`、`--border-default`、`--surface-elevated`、`--surface-default`、`--status-busy`、`--status-online` |
| 狀態色用錯字尾 | `--status-warning`、`--status-danger`、`--status-success` | `--status-busy`、`--status-error`、`--status-online` |
| 間距／字級／等寬 | `--space-1`…`--space-4`、`--font-size-xs/sm/lg`、`--font-mono` | **完全不存在**——`tokens.css` 從來沒有間距與字級刻度 |
| 其他 | `--border-subtle`、`--surface-raised` | `--border-default`、`--surface-elevated` |

**為什麼這會讓畫面崩掉而不只是掉色**——CSS 的 invalid-at-computed-value-time
規則會丟棄**整條宣告**，不是只丟那個值：

- `border: 1px solid var(--color-border)` → 整條 `border` 消失 → **卡片與車道沒有框線**
- `background: var(--color-surface-2)` → 車道沒有底色 → 六車道視覺上不存在
- `gap: var(--space-2)` → 整個 grid／flex 的間距歸零 → **所有東西擠在一起**
- `font-size: var(--font-size-sm)` → `h2`／`h3`／`h4` 退回瀏覽器預設 → **標題變成巨大的粗體**
- `font-family: var(--font-mono)` → `card_ref` 用比例字體 → 對不齊

這四件事在**沒有 fallback 的那 83 個引用上**同時發生，
而它們 100% 集中在任務層的五個檔案，所以那五個畫面就是「無樣式的 HTML 文件」。
這正是被回報的現象。

**它為什麼活過五次 commit**：`make check` 的 `format-check`、`lint`、`typecheck`、
`unit`、`build` **沒有任何一項會看 CSS 變數解不解得開**。
Prettier 只管排版，ESLint 不看 `<style>`，`vue-tsc` 不看 CSS，Vite 照樣打包成功。
**這一層的真正修法是第 3 層的守門，不是把 104 個名字改對。** 改對只是還債。

### 第 2 層 — 語彙層：V2 需要的顏色一個都沒有

就算 104 個引用全部改成既有名字，畫面仍然是錯的，因為 `tokens.css` 裡
**沒有任何一個 V2 語意的顏色**：沒有 stage、沒有 run 狀態、沒有 risk、沒有證據 source。

現況因此退化成：`TaskBoard.vue` 把 `card.risk` 與 `card.delivery`
**原封不動印出英文 enum**（`low`、`pull_request`），而且兩者用**同一顆灰色藥丸**。
六個車道沒有任何顏色區分。`TaskDetail.vue` 的標題列直接印 `task.stage` 的英文值。

`09` §7 要求的「三種『進行中』一眼分得出來」（Session 綠／Task 藍／Run 琥珀＋脈動）
在目前的 token 表上**不可能做到**——那三個顏色只有一個存在。

prototype 的 `styles.css` §2 已經把這 18 個候選值全部備妥並排版成一個審查畫面，
`README.md` 明說「**審查通過之後，那一段才會進 `tokens.css`**」。
**那次審查沒有發生。** 這一期補做，並把結果落地（§2）。

### 第 3 層 — 決定層：prototype 要證明的七件事，看板上一件都沒有

prototype 存在的理由是七個「文字讀不出對錯」的決定。逐條對現況：

| # | 決定 | 出處 | 現況 |
|---|---|---|---|
| 1 | 208px sidebar 在三組導覽下夠用 | `09` §3 | ✅ **已做到**，`AppLayout.vue` 用分隔線式群組標題，量測 147px |
| 2 | **「等待你的回覆」是看板上最醒目的** | D24 | ❌ **完全沒有**——見下方，這是契約缺口不是樣式缺口 |
| 3 | 拖曳三種拒絕分得出來 | D17b／DV-05 | ⚠️ **文案對了，傳達方式錯了**——見下方 |
| 4 | 三種「進行中」可區分 | `09` §7 | ❌ token 不存在 |
| 5 | 三種證據 `source` 的視覺分級 | D10 | ❌ 沒有 `SourceBadge`，三處畫面無從一致 |
| 6 | Session Workspace 的 Terminal 沒變窄 | `plan/08`／`09` §5 | ✅ **已做到**，右欄仍 300px |
| 7 | 產物只有下載、機密沒有顯示值 | D29 §4、D22 | ➖ 尚未到期（V2.3／V2.4） |

**第 3 條的實情要講精確，不要冤枉它。**
prototype 示範的三種拒絕裡，**第二種（Done Gate）屬於 V2.4 的 `DV-05`，本期不到期**——
`DONE_GATE_UNMET` 這個錯誤碼在 backend、frontend、`docs/error-catalog.md` 三處都還不存在，
這是正確的。`TaskBoard.vue` 的 `explain()` 已經正確處理了到期的兩種
（`TASK_VERSION_CONFLICT`、`TASK_DEPENDENCY_UNSATISFIED`，且相依那則會**指名是哪幾張卡**）。

所以本期在這一條上要修的**不是文案，是傳達方式**：

- 訊息渲染成看板頂端一行 `<p class="board-message">`——**離被拒的那張卡很遠**，
  在一面六車道的看板上，使用者的視線在卡片上，不在頁首。
- 卡片被拒後**沒有任何動作**：prototype 的 `bounce` 彈回動畫是「它真的沒有移動」的唯一體感證據。
  現況只是靜靜地跳回去，看起來像什麼都沒發生。
- 三則訊息共用同一個灰框，**視覺上分不出嚴重程度**。

`UI-08` 因此是「toast ＋ 彈回動畫 ＋ 就地反饋」，**不是補第三種拒絕**。
Done Gate 那一種等 V2.4，屆時只要多一個 `case` 就能接上——這也是把
toast 機制先做好的理由之一。

**第 2 條要獨立看，它不是樣式問題。**
`BoardCard` 這個型別（`frontend/src/api/dto.ts` 與 `backend/app/repositories/tasks.py`
兩端一致）**沒有任何 run 相關欄位**——沒有 `run_status`、沒有 `agent_name`、
沒有等待旗標。所以：

> **D24 目前不是「沒做樣式」，是看板的資料契約無法表達它。**

而擴充那個型別有明確的既有代價，寫在 `tasks.py` 的 docstring 裡：
M1 量過 200 張卡的完整 card 是 439 KB、精簡 card 是 74 KB，
「**Widening this type is how that decision gets undone**」。
所以 `UI-06` 不能隨手加欄位，要**加最少的三個欄位並重跑那個量測**（§4）。

---

## 1. 這一期的形狀

> 把 prototype 已經證明過的視覺與互動語意，變成 `frontend/` 裡真的跑得動的東西；
> 並且加上一道守門，讓「引用不存在的 token」以後在 `make check` 就失敗，
> 而不是在使用者的螢幕上失敗。

**為什麼叫 V2.2_1 而不是 V2.6**：它不推進任何新功能，它把 V2.0–V2.2 已宣稱交付的
前端補到可用。放在 V2.2 之後、V2.3 之前，是因為 V2.3 起的機密與交付畫面
會**繼續沿用**這一期定下的徽章與原語——先修再蓋，才不會蓋第二層歪的。

### 不做（明確劃線）

- **不做深色模式。** 既有 `tokens.css` 也沒有，這一期不開這個頭。
- **不重新引入全域 class layer。** prototype 用的是全域 class（`.card`、`.badge`、
  `.table`）——那是零依賴 prototype 的合理作法，**不是要照搬的結論**。
  這一期把那些 class 做成 **Vue 元件**（§3）。

  > **2026-08-12 修正。** 本條原本引 `base.css` 檔頭那句
  > 「已被 scoped style 完全遮蔽卻仍在打包」。回去讀 `plan/05/03` §P4-07 的原始紀錄，
  > **那句話只涵蓋刪掉的死 class**。P4-07 對**仍在使用**的五個 class 寫的處置是
  > 「**遷移為共用元件：新增 `components/common/{PageHeader,Panel}.vue`**」——
  > 而那兩個元件從未被建立，那五個 class 今天擴散到 **17／9／15／9／22** 個檔案，
  > 各自實作、沒有一份權威。**那個真空正是 104 個未定義 token 得以擴散的條件。**
  >
  > 所以正確的說法是：**這一期是把 P4-07 沒做完的後半做完**，不是遵守一條既有原則。
  > 完整考證見 [`plan/19/01-decisions-and-governance.md`](../../plan/19/01-decisions-and-governance.md) §D34。
- **不改任何路由路徑。** 沿用 `09` §2 的硬規則。
- **不重畫 V1 畫面**（Dashboard／Nodes／Enrollment／Audit／Integrations）。
  四個 V1 檔案共 6 個未定義引用（全部是有 fallback 的 B 類），那 6 個照修，版面不動。
  V1 畫面裡 `.head`／`.panel` 的散落實作**也留到下一期**——它們受出口條件 8 的
  逐像素保護（`plan/19/03` §3.3）。
- **不做 RQ-07 的 mockup 變體檢視。** 它卡在「HTML 產物不能在應用 origin 內渲染」
  這個未決前置問題上（prototype README 已註記），與本期無關。
- **不動 `version2.md` §9 的四欄版面。** `09` §5 已否決，這一期不翻案。

---

## 2. Design token 裁決（本期要交付的第一個決定）

prototype `styles.css` §2 的 18 個候選值，**建議整組採納**，理由是它們已經
在一份可點擊的畫面上被排過、並且每一組都對應一個寫在 `01` 裡的決定。

### 2.1 語意色（18 個）

| 組 | token | 值 | 對應決定 |
|---|---|---|---|
| Task stage | `--stage-backlog` | `#8892a0` | `01` D3；六車道刻意走灰→藍→紫→深綠的推進感，**避開 `--status-*` 的綠** |
| | `--stage-blocked` | `#b4574f` | |
| | `--stage-ready` | `#4a7c8c` | |
| | `--stage-implementing` | `#3f6fa8` | 「Task 進行中」＝藍（`09` §7 三色之二） |
| | `--stage-verify` | `#7a5ea8` | |
| | `--stage-done` | `#2f7a56` | |
| Run 狀態 | `--run-queued` | `#8892a0` | |
| | `--run-running` | `#c68c37` | 「Run 執行中」＝琥珀＋脈動（`09` §7 三色之三） |
| | `--run-waiting` | `#d2691e` | **D24 的專用色**，全 app 只有這一個狀態用它 |
| | `--run-succeeded` | `#2f9b63` | |
| | `--run-failed` | `#d25454` | |
| | `--run-lost` | `#a0673f` | |
| Risk | `--risk-low` / `--risk-medium` / `--risk-high` | `#6b7684` / `#c68c37` / `#c45c5c` | |
| 證據 source | `--source-machine` | `#2f7a56` | D10；實心＝機器事實 |
| | `--source-platform` | `#4a7c8c` | 線框＝平台紀錄 |
| | `--source-agent` | `#8892a0` | 灰字＝Agent 自述 |

**「Session 進行中」沿用既有的 `--status-online`，不新增。** 三色之一本來就在。

### 2.2 尺度 token（12 個，補既有缺口）

`--space-1`…`--space-6`（4/8/12/16/24/32px）與
`--font-xs/sm/base/md/lg/xl`（11/12/13/15/19/24px）。

這兩組**不是 V2 新需求**——`tokens.css` 從第一天就沒有它們，
所以每個元件各自寫死像素值，而 V2 的作者憑印象寫了 `--space-2` 這種名字。
**補上刻度，那個錯誤才不會再犯。**

> **命名注意**：prototype 用 `--font-sm`，V2 程式碼寫的是 `--font-size-sm`。
> **採用 prototype 的 `--font-*`**（較短、與 `--space-*` 對稱），
> 並在 `UI-02` 把 18 個 `--font-size-*` 引用一併改名。

### 2.3 兩個 prototype 沒涵蓋到的值（本期新增）

`RunStatus` 在 `dto.ts` 是 **8 個值**，prototype 的 token 只給了 6 個：

| 缺的值 | 決定 |
|---|---|
| `claimed` | 視覺上與 `queued` 同色（`--run-queued`），標籤「已認領」。它是一個極短的過渡狀態，另給一個顏色只會增加雜訊 |
| `cancelled` | 用 `--status-offline` 灰，標籤「已取消」。**刻意不用 `--run-failed` 紅**——取消是人的決定，不是失敗 |

同理，`BoardCard.risk` 與 `.delivery` 在 DTO 裡是 **`string` 不是 union**，
所以每個徽章元件都必須有**未知值的退路**：顯示原字串 ＋ 中性樣式，
不得因為後端多送一個值就整頁壞掉。

---

## 3. 元件層：把 prototype 的 class 變成元件

prototype 有一套一致的視覺原語，現況沒有——所以每個 V2 view 各寫各的 scoped CSS，
**這正是 104 個錯名字得以擴散的溫床**。

本期建立 `frontend/src/components/ui/`：

| 元件 | 取代 prototype 的 | 要點 |
|---|---|---|
| `StageBadge` | `stageBadge()` | 實心，六車道色，**中文標籤**（`01` D3：`stage` 值不變，只換顯示） |
| `RunBadge` | `runBadge()` | `running`／`waiting_for_input` 帶脈動點；`running` 附 agent 名稱 |
| `RiskBadge` | `riskBadge()` | 線框，低／中／高 |
| `DeliveryBadge` | `deliveryBadge()` | `none` 用 quiet 樣式（不是一個承諾） |
| `SourceBadge` | `sourceBadge()` | **實心／線框／灰字三級**，D10 要求三處完全一致 |
| `PageHead` | `.page-head` | 標題＋副標＋右側動作槽 |
| `UiCard` | `.card` / `.hd` / `.bd` | |
| `DataTable` | `.table` | |
| `EmptyState` | `.empty` | 空狀態必須帶下一步動作（`09` §6） |
| `ToastHost` | `.toast` / `#toasts` | 拖曳拒絕訊息的落點（§4） |

**徽章族共用一個 `BaseBadge`**，`solid` / `outline` / `quiet` 三種變體——
D10 的「可信度語言」要靠這三種變體承載，各寫各的一定會漂移。

**無障礙**：沿用既有紀律（`StatusBadge.vue` 的註解），
**顏色永遠不是唯一線索**——每顆徽章都有文字標籤，脈動只是附加。

---

## 4. 看板契約擴充（`UI-06`）— 本期唯一的後端變更

**這張 ticket 不是新規格，是把 `AR-10` 做完。**
`plan/18/07-frontend.md` §3.3 已經逐欄指定過看板要多哪三個欄位、
每一種狀態顯示什麼徽章、以及「第二列與第三列的文案**逐字不同**」是出口條件 4／5。
實作時**那三個欄位一個都沒進去**：

| plan/18 §3.3 指定的欄位 | 現況 |
|---|---|
| `active_run_status` | ❌ 全 repo 不存在 |
| `active_run_runner_name` | ❌ 全 repo 不存在 |
| `waiting_reason` | ⚠️ 只存在於 **dispatch 的一次性回應**（`DispatchResponseDTO`），看板從來拿不到 |

後果具體而且可複現：**派工之後只要離開那一頁，看板就再也不會告訴你那張卡在等什麼。**
`waiting_reason` 的兩種文案（「等待可用的 Agent」vs「等待指定的 Agent：dev-vm-01（目前離線）」）
在 backend 的 `resolve_waiting_reason()` 裡算得好好的，只是沒有任何畫面在讀它。

所以 `UI-06` 沿用 `plan/18` 的欄位名，不另創：

```
active_run_status:       RunStatus | null   —— null 代表這張卡沒有 active run
active_run_runner_name:  string | null      —— running 時顯示；未指定時前端顯示「任一 Agent」
waiting_reason:          string | null      —— 前端不重算，那個判斷要跑資格查詢
```

**不加**：attempt、seq、時間戳、run_id。那些是 Run 詳情頁的內容，
放進看板 payload 就是在重演 M1 量到的那件事。
（連到 Run 詳情用 `task_id` 走既有路由即可，不必為此多一個 UUID 欄位。）

**成本控制是這張 ticket 的一部分**：

- 後端 `board_cards()` 目前是「一個 Task 查詢 ＋ 一個 grouped blocking 查詢」。
  run 投影**必須是第三個 grouped 查詢**，不得寫成 per-card 的 N+1
  （`tasks.py` 已為此留下明確註解）。
- **重跑 M1**：200 張卡的 payload 大小要重量一次，
  結果寫進 `plan/19/10-open-measurements.md`。
  `plan/18` §3.3 自己估過「每張卡約 80 bytes，200 張卡是 16 KB——可接受，
  但要量一次並記進 `10-…md`，不是假設」。**那次量測沒有發生**，本期補做。
  預算：**≤ 90 KB**（74 KB 基線 ＋ 16 KB 估值）。超過就退回只加 `active_run_status` 一欄。

**版本治理走哪一條**：看板是 HTTP REST，不是 WSS 控制通道——
`contracts/` 只裝 `control-envelope.schema.json` 與 `messages/`，裡面沒有 board。
所以本期**不動 `contracts/`、不改契約版號、不動 daemon**；
`BoardCardDTO` 的變更由 **OpenAPI 快照比對**治理
（`scripts/pj/openapi_diff.py` ＋ `artifacts/*/baseline/openapi*.json`，V2.0 起的既有機制）。

這是一個**純新增欄位**的變更：既有欄位一個都不動，舊前端拿到多的欄位會忽略它。

---

## 5. Ticket 清單（`UI-`）

| # | ticket | 內容 | 依賴 |
|---|---|---|---|
| UI-01 | Token 定稿 | §2 的 18 個語意色 ＋ 12 個尺度 token ＋ `--font-mono` 進 `tokens.css`，同步 `research/style.md` | — |
| UI-02 | 還債 | 104 個未定義引用全部改對（含 `--font-size-*` → `--font-*` 改名） | UI-01 |
| UI-03 | **守門** | `make check` 新增 token 解析檢查：任何 `var(--x)` 解不開就失敗 | UI-01 |
| UI-04 | 徽章族 | `BaseBadge` ＋ 五個語意徽章，中文標籤，未知值有退路 | UI-01 |
| UI-05 | 版面原語 | `PageHead`／`UiCard`／`DataTable`／`EmptyState`／`ToastHost` | UI-01 |
| UI-06 | 看板契約 | **把 `AR-10` §3.3 做完**：`BoardCard` 加 `active_run_status`／`active_run_runner_name`／`waiting_reason`＋ 補做那次沒做的 M1 量測 | — |
| UI-07 | 看板重繪 | 六車道著色、卡片改用徽章族、**「等待你的回覆」滿版色條＋脈動**、`waiting_reason` 兩種文案逐字不同 | UI-04, UI-06 |
| UI-08 | 拖曳拒絕 | **toast ＋ 卡片彈回動畫 ＋ 就地反饋**（文案已正確，改的是傳達方式；Done Gate 留給 V2.4） | UI-05, UI-07 |
| UI-09 | Task 詳情 | 兩欄版面對齊 prototype、`SourceBadge` 上線、失敗項預設展開不可摺疊 | UI-04, UI-05 |
| UI-10 | 其餘畫面 | Roadmap／Agents／Run 詳情／Requirements／Projects 對齊原語 | UI-05 |
| UI-11 | 審查畫面 | `TokenShowcaseView` 從 V1 詞彙更新為 V2 詞彙（含三種「進行中」並排） | UI-04 |
| UI-12 | 視覺回歸 | Playwright screenshot 基準；**旗標關閉時的 V1 畫面基準必須逐像素不變** | UI-07…UI-11 |

---

## 6. 出口條件

| # | 條件 | 怎麼證明 |
|---|---|---|
| 1 | **零個未定義 token** | `UI-03` 的檢查在 `make check` 內，全綠 |
| 2 | 守門真的會擋 | 故意引入一個 `var(--nope)`，`make check` 失敗；還原後全綠 |
| 3 | 三種「進行中」可區分 | `TokenShowcaseView` 三顆並排截圖，人工確認（`09` §7） |
| 4 | **D24 成立** | 看板截圖：等待中的卡在一整面看板上第一眼被看到；`run_status` 由契約供給而非前端猜 |
| 5 | 拖曳拒絕**就地看得見** | 兩個到期的 e2e case（相依／409）：斷言 toast 出現、文案**指名是哪幾張卡**、卡片回到原車道 |
| 5b | **兩種等待文案逐字不同** | `plan/18` 出口條件 4／5 的回歸：「等待可用的 Agent」vs「等待指定的 Agent：<名稱>（目前離線）」，由 `waiting_reason` 驅動而非前端重算 |
| 6 | 三處 `source` 徽章完全一致 | 同一個 `SourceBadge` 元件，三處引用；一個單元測試斷言三種變體的樣式 |
| 7 | 看板 payload 未回退 | M1 重量結果 ≤ 90 KB，寫進 `10-open-measurements.md` |
| 8 | **V1 畫面逐像素不變** | 旗標關閉的 screenshot 基準比對 |
| 9 | Terminal 未變窄 | Session Workspace 右欄仍 300px（`09` §5 的既有出口條件，回歸） |

**合併規則不變**：`v2` → `dev` 一律人工確認，出口條件全綠只是提案資格（`10` §7）。

---

## 7. 與既有文件的關係

| 文件 | 這一期怎麼動 |
|---|---|
| `09-frontend-information-architecture.md` §7 | **加註**：token 裁決結果與落點指向本文件 §2。原文不刪（沿用 `plan/08/01` §1.2 的規格同步做法） |
| `00-upgrade-roadmap.md` §6 | 階段表加一列 V2.2_1 |
| `CHECKLIST.md` | 新增 §4b |
| `11-requirement-traceability.md` | 新增 `NFR-UI-001`…`003` |
| `research/style.md` | `UI-01` 完成後同步新 token（沿用既有慣例） |
| `research/prototype-v2/` | **不動。** 它是這一期的驗收參考，改它等於改考題 |

**這份文件與 `plan/19/` 不一致時，以 `plan/19/` 為準並回寫這裡**——
沿用 `README.md` 的既有規則：執行計畫讀的是程式碼，本目錄讀的是構想。
