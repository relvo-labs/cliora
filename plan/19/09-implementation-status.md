# 09 — 實作進度與證據

> **狀態：實作完成；瀏覽器 stack 的 V1 像素比對與 DB-backed e2e 待有 PostgreSQL 的環境重跑。**
> 沿用 `plan/17/09`／`plan/18/09` 的體例：**這裡記的是實際發生的事**，
> 與計畫不同時，**以這裡為準並回寫計畫**。

## 0. 裁決單

**這一節是開工前唯一要讀的東西。** 每一項都寫了「不同意的話會怎樣」，
所以可以只看這一張表就做決定，不必回頭讀五份文件。

### 0.1 A 類 — 會擋開工（2 項）

這兩項**會改變後續每一張 ticket 的形狀**，沒有預設值，必須有人決定。

---

**☑ D32 — prototype §2 的 18 個語意色整組採納，原值不調**（`01` D32）

| | |
|---|---|
| **要點頭什麼** | ①「整組」而非逐個挑；②原值不在 `tokens.css` 的 diff 裡調 |
| **為什麼整組** | 那 18 個不是 18 個獨立選擇，是**四組關係**：六車道要有推進感、三種「進行中」要能區分、三級可信度要有權重差、風險三級不能與狀態色撞。挑掉幾個，關係就斷了 |
| **為什麼原值不調** | 調色的正確場合是**看得到色票並排的畫面**，不是 diff。`UI-11` 把 prototype 的審查畫面搬進產品，之後隨時可調 |
| **代價** | `tokens.css` 從 27 個 custom property 變成 **58** 個 |
| **不同意的話** | 需要另外安排一次色彩審查，**`UI-01` 開不了工**，連帶波次 1 全部延後。若只是想調某幾個值，建議先同意整組進去、在 `UI-11` 的畫面上再調——那比在計畫階段猜色票快 |

---

**☑ D34 — 不重新引入全域 class layer，prototype 的 class 改做 Vue 元件**（`01` D34）

| | |
|---|---|
| **要點頭什麼** | **只有「多做 9 個元件」是新的。** `PageHead`／`UiCard` 等同 P4-07 已批准的 `PageHeader`／`Panel`；多的 9 個（五顆語意徽章 ＋ `DataTable`／`EmptyState`／`ToastHost`）有各自理由，見 `01` §D34 末段 |
| **為什麼** | **`P4-07` 指定過但沒做完。** 它刪 `src/styles.css` 時明寫「仍被使用的 class → **遷移為共用元件：新增 `components/common/{PageHeader,Panel}.vue`**」——**那兩個元件從來沒被建立**，五個 class 因此擴散成 17／9／15／9／22 個各自實作。那個真空就是 104 個 token 能擴散而沒人發現的原因（`01` §D34） |
| **prototype 用全域 class 不是結論** | 那是零依賴、無 build、單檔 HTML 的體質，除此之外沒別的選擇。**照搬形式而不是語意，是誤讀 prototype** |
| **額外買到的** | 中文標籤與未知值退路只寫一次；D10 的「三處一致」變成**結構上為真**而非靠 review 盯；每顆徽章可單元測試 |
| **代價** | 模板較囉嗦（`<StageBadge :stage="..." />` vs `class="badge"`） |
| **不同意的話** | 等於決定**繼續讓 P4-07 的後半懸著**，那五個 class 會從 70 幾份長成更多份。若只是覺得 9 個太多，可以只砍 `DataTable`／`EmptyState`／`ToastHost`——五顆徽章是 D10「三處一致」的必要條件，砍不得 |

### 0.2 B 類 — 確認即可（4 項，判斷單純）

| ☐ | 項目 | 內容 | 不同意的話 |
|---|---|---|---|
| ☑ | **D33** | 看板欄位走 OpenAPI 快照，不動 `contracts/`、不動 daemon | 若堅持動 contract 版號，`UI-06` 多一輪 fixtures，但 `contracts/` 裡沒有 board——**它在技術上放不進去** |
| ☑ | **D35** | 不擴大 naive-ui 使用面 | 若要用 `NTag` 包徽章，得到的是「第三方元件 ＋ 一層自訂色覆寫」，不會更少程式碼 |
| ☑ | **D36** | `StatusBadge` 不動，新徽章族與它並存 | 若要合併，等於動一組有 screenshot 基準且被 e2e 釘住的 V1 元件，與出口條件 8 直接衝突 |
| ☑ | **波次順序** | 波次 1（token ＋ 守門）先合；**`UI-03` 緊接 `UI-02`，中間不插別的 ticket** | 那個空窗期正是 104 個引用當初誕生的條件。不同意就等於接受它再發生一次 |

### 0.3 C 類 — 開工時決定，但計畫已給預設值（6 項）

**這些不擋開工。** 計畫已經選好預設，照做即可；要改再說。
列在這裡是為了讓它們**被決定過**，而不是被自動決定。

| ☐ | 項目 | **計畫的預設** | 什麼情況要改 |
|---|---|---|---|
| ☑ | `StatusBadge.vue` 的裸 hex | **進白名單**，註明「D36：本期不動」 | 除非願意承擔 V1 元件的色差風險（出口條件 8） |
| ✔ | `FileTreeNode.vue` 的 `--surface-raised` | **已查證定案：`--surface-canvas`**。它是拖放目標高亮，坐在白色列上；用 `--surface-elevated`（白）會讓高亮消失 | 已不需決定，`02-…md` §3.3.1 |
| ☑ | 守門白名單 | **預期 0 項**；有才加，加了要寫理由 | 實測為 0 |
| ☑ | `TaskRoadmap` 的「（未分類任務）」桶 | **先確認現況是否真的漏了，漏了才補** | 現況已有 epic 與 top 兩桶，保留 |
| ☑ | `waiting_reason` 欄位 | **做**，但它是 `UI-06` 三欄裡唯一有 N+1 風險的，**也是 M1 超標時第一個砍的** | 89,251 bytes，未超標，保留 |
| ☑ | 卡片顯示「最近一次失敗」 | `UI-07` 的顯示層決定，**不進契約** | 本期不顯示，不擴契約 |

### 0.4 做完必須清掉的暫時措施（1 項）

| ☐ | 項目 | 何時清 |
|---|---|---|
| ☑ | `UI-03` 的 `--allow-fallback` 旗標 | 檢查器仍提供遷移參數，但 `Makefile` 未使用；正式 gate 對 WARN 也失敗 |

### 0.5 明確不在本期決定（4 項）

D34 要不要補 ADR（`01` §6：該是獨立一份、收編 P4-07 舊決定，不夾在本期趕出來）、
是否導入 stylelint、深色模式、`StatusBadge` 與 V2 徽章族最終合不合併。
四項都記在 `10-…md` §6。

## 1. Ticket 狀態

| ticket | 狀態 | 證據 |
|---|---|---|
| `UI-00` 基線 | ◐ | commit／token／payload／check 已存；期初 browser screenshots 因無 DB stack 未取得 |
| `UI-01` Token 定稿 | ☑ | 18 semantic ＋ 12 scales ＋ mono；總定義 58 |
| `UI-02` 104 個引用還債 | ☑ | `make tokens`：0 ERROR／0 WARN |
| `UI-03` **守門** | ☑ | checker、反向測試、真 repo 負向紀錄、`make check` target |
| `UI-04` 徽章族 | ☑ | 五顆語意徽章與未知值退路，28 個 primitive tests |
| `UI-05` 版面原語 | ☑ | PageHead／UiCard／DataTable／EmptyState／ToastHost |
| `UI-06` 看板契約 | ☑ | 三欄、≤4 query 測試、OpenAPI additive、M1 89,251 bytes |
| `UI-07` 看板重繪 | ☑ | lane 色、D24、兩種 waiting copy |
| `UI-08` 拖曳反饋 | ☑ | toast、rollback、reduced motion；e2e selector 已更新 |
| `UI-09` Task 詳情 | ☑ | 兩欄、來源分級、失敗項固定展開測試 |
| `UI-10` 其餘畫面 | ☑ | Roadmap／Agents／Run／Requirement／Projects 對齊；契約限制見 §4 |
| `UI-11` 審查畫面 | ☑ | dev-only showcase、computed token values、production 排除通過 |
| `UI-12` 視覺回歸 | ◐ | showcase 已取；V1 pixel 與 DB-backed e2e 待 stack |

## 2. `UI-00` 的六份基線

同一個 commit 擷取，放進 `plan/19/baseline/`：

| # | 檔案 | 內容 | 狀態 |
|---|---|---|---|
| 1 | `COMMIT` | 基線 commit SHA（含工作樹說明） | ☑ |
| 2 | `undefined-tokens.txt` | 104 個未定義引用，A／B 分級 | ☑ |
| 3 | `token-inventory.txt` | 27 個定義與引用次數 | ☑ |
| 4 | `board-payload.json` | 200 張卡、73,851 bytes | ☑ |
| 5 | `screens-before/` | 全畫面 screenshot | ◐ 無 PostgreSQL browser stack，目錄保留但未偽造證據 |
| 6 | `make-check.log` | 基線 `make check` 全綠 | ☑ |

**第 6 份最重要。** 它是這一期存在理由的直接證據：
`make check` 在 83 個會讓宣告被丟棄的引用存在的情況下**全綠**。

## 3. 開工前已核對的事實（2026-08-12）

這些是寫計畫時實測的，開工時要重驗一次（數字可能已變）：

| 事實 | 值 | 怎麼驗 |
|---|---|---|
| `tokens.css` ＋ `base.css` 定義的 custom property | **27** | `grep -ohE '^\s*--[a-z0-9-]+:' frontend/src/theme/*.css \| tr -d ' :' \| sort -u \| wc -l` |
| `frontend/src` 引用的 | **43** | `grep -rohE 'var\(--[a-z0-9-]+' frontend/src \| sort -u \| wc -l` |
| 未定義引用 | **104 次 / 13 檔**，其中 **83 無 fallback（真的壞）／21 有 fallback（不壞但繞過 token）** | `02-…md` §1.0 的指令 |
| 83 個 A 類的分佈 | **100% 落在 V2.1 任務層五檔**：TaskBoard 31、TaskDetail 26、TaskRoadmap 17、RequirementDetail 5、TaskDetailView 4 | 同上 |
| 21 個 B 類實際渲染的值 | `crimson`×4、`seagreen`、`darkorange`、裸 `monospace`×4、`#d0d0d0`×3、`rgba(127,127,127,.12)` 等 | `02-…md` §3.3 |
| `base.css` 有無 mono 堆疊 | **無**（`grep monospace` 無輸出）；三處各自寫死 | `02-…md` §2.3 |
| `BoardCard` 有無 run 欄位 | **無** | `dto.ts:869`、`repositories/tasks.py:23` |
| `active_run_status` | **全 repo 不存在** | `grep -rn active_run_status` |
| `waiting_reason` | 只在 `DispatchResponseDTO` | `schemas.py:1449`、`dto.ts:1132` |
| `waiting_reason` 的值集 | **三個**：`any`／`assigned_offline`／`no_eligible_runner` | `runs.py:331` |
| `_eligible_runner_count()` 的成本 | 每次呼叫都 `select(AgentRunner)` ＋ 線上判定 → **逐卡呼叫是 N+1** | `runs.py:349`；處置見 `04-…md` §1.3b |
| `DONE_GATE_UNMET` | **不存在**（正確，V2.4 才有） | `grep -rn DONE_GATE` |
| `make check` 的組成 | 8 項，**無一解析 CSS** | `Makefile:46` |
| `P4-07` 指定的 `PageHeader.vue`／`Panel.vue` | **從未建立** | `ls frontend/src/components/common/` |
| 那五個 class 的擴散 | `.primary` 5→**17**、`.danger` 3→**9**、`.head` 6→**15**、`.panel` 2→**9**、`.ghost`→**22** | `grep -rl 'class="[^"]*\bX\b' --include=*.vue` |
| `TokenShowcaseView` | **dev-only**（`import.meta.env.DEV`），P4-07 定案保留 | `router/index.ts:128` |
| stylelint | **未安裝** | `frontend/package.json` |

## 4. 實作中發現、與計畫不同的事

> 開工後填。體例：**每一條寫「計畫說什麼 → 實際是什麼 → 怎麼處理」**，
> 並註明有沒有回寫 `research/02/12`。

1. **Token 數算式錯誤。** 計畫寫 24 semantic ＋ 10 scale ＝新增 34、總數 61；
   prototype 實檔其實是 18 semantic，space 與 font 各 6（12 scale），再加 mono，
   即新增 31、總數 **58**。採 prototype 原值、不發明缺少的 3 色；已回寫本目錄與
   `research/02/12`。
2. **裸 hex 基線遠多於預估。** 排除 theme/test 後期初為 69，不只 showcase 與
   `StatusBadge`。為保護 V1 像素與 Monaco/xterm adapter，保留 12 檔／60 次的精確
   legacy allowlist；`staticGuards.test.ts` 會拒絕任何增加，V2 本期畫面為 0。
3. **Roadmap DTO 沒有 delivery。** 已加 StageBadge 與三層 meter；沒有為了顯示
   DeliveryBadge 擴大 `RoadmapTaskDTO`，避免在 UI-06 之外再開一個 OpenAPI 變更。
4. **Workspace usability 契約只有四值。** 現有 `node_disabled` 把 root 停用／移除
   合在一起，`outside_allowed_root` 也不能證明路徑不存在；UI 已逐值顯示，但不虛構
   契約無法提供的兩種狀態。這是 plan/19 原先對既有契約的誤判。
5. **本機無 PostgreSQL 測試服務。** DB-backed query-count case 與 Playwright full
   stack 已寫好、可列舉，但 pytest fixture 正常 skip；沒有把 skip 寫成 PASS。

## 5. 尚待人工完成的事

> 開工後填。預期至少三項：
> - 出口條件 3（三種「進行中」一眼可區分）的人工確認
> - 21 個 B 類引用涉及的 8 個檔案前後對照確認（`02-…md` §3.3）
> - `v2` → `dev` 的合併決定

- `artifacts/ui/local/showcase.png` 已由 dev build、1440×1200 擷取並人工檢視：
  Session 綠／Task 藍／Run 琥珀三者可一眼區分。容器缺 CJK 字型，所以截圖中文字
  顯示 tofu；這是證據環境限制，不是 CSS 或 DOM 缺字。
- 21 個 B 類所涉 V1 畫面的前後像素比對仍需 PostgreSQL browser stack。
- `v2` → `dev` 的合併決定由維護者執行；本次不代為 merge。

## 6. 環境事實

> 開工後填（Node 版本、瀏覽器版本、screenshot 的解析度基準等）。

- commit：`b6f66e5a0530405fb26a2b31a8feef31c91d678a`（工作樹原先已有 plan/research 變更）
- Node `22.14.0`（`.nvmrc`）、npm `10.9.2`、Playwright `1.61.1`
- uv `0.12.0`、Go `1.26.5`
- showcase：Chromium headless、1440×1200、device scale 1、dev Vite server
- PostgreSQL：未提供；DB tests skip，V1/browser full-stack 證據待補

## 7. 最終自動驗證（2026-08-12）

- `make check`：**PASS**；backend 972 passed／491 skipped、frontend 589 passed、
  contract 180 ＋ frontend protocol 159、daemon race suite／build／traceability／Railway 全綠。
- `make tokens`：**PASS**，58 definitions、0 ERROR、0 WARN。
- 真 repo 負向驗證：注入 `var(--cliora-does-not-exist)` 後如期失敗（exit 2），
  還原後全綠；輸出在 `baseline/token-negative-real-repo.log`。
- production bundle：`TokenShowcaseView`／`/poc/tokens` grep 無結果。
- `scripts/ui/evidence.sh` 的輸出在 `baseline/evidence-after.log`；其中 DB e2e 與
  V1 pixel 明列 SKIP／MANUAL，未冒充通過。
