# 09 — 前端架構

> **ticket：`PX-27`（queryCache）、`PX-17`（token）、`PX-64`（模組佈局）。**

## 1. 現況（2026-08-23 實測）

```text
frontend/src/
  views/            28 個檔案，其中 ProjectDetailView.vue 1515 行
  modules/
    knowledge/      views/ + components/     ← alpha.3 建立，本期沿用同一形狀
  components/
    project/        TaskBoard.vue 474 · TaskDetail.vue 734 · conversation/ConversationPanel.vue
                    TaskRoadmap · TaskAgentPanel · ProjectRepositories · ProjectSecrets …
    layout/ common/ ui/ session/ dashboard/ file/
  composables/      useAsyncResource（78 行，**無快取**）＋ 5 個
  stores/           12 個 Pinia store
  theme/            tokens.css（**62** 個 custom property）· base.css · checkTokens.test.ts
  api/              client.ts · dto.ts
  router/index.ts   /projects/:id + ?tab=；/projects/:id/knowledge 已是獨立路由
```

依賴：`vue` 3.5、`vue-router` 4.5、`pinia` 2.3、`naive-ui` 2.42、
`lucide-vue-next`、`monaco-editor`、`@xterm/*`。
**沒有 server-state／query cache 套件**（D56），本期也不加。

**`modules/` 已經存在**——`alpha.3` 的 `modules/knowledge/` 建立了這個慣例。
本期不是在引入新結構，是在沿用它。

## 2. Server state（[D100](./01-decisions-and-governance.md)）

> **一個要先說清楚的事**（[D114](./01-decisions-and-governance.md)）：
> `modules/` 佈局的依據是 kintra 的十六個模組，
> 而 **kintra 用 `@tanstack/vue-query`**（`package.json`，`modules/board/queries.ts` 整支建立在它上面）。
> 所以 kintra 是「這個結構在同等規模下可讀」的證據，**不是「自建 query 層可行」的證據**。
> D56／D100 選擇自建，代價就是要自己做 kintra 用一個套件解決的事——
> [`11`](./11-open-measurements.md) 第 4 項的對照組因此是 kintra 的 `queries.ts`。

### 為什麼是新模組而不是擴充

```ts
// composables/useAsyncResource.ts — 全檔 78 行，本體 26 行
export function useAsyncResource<T>(loader, options = {}): AsyncResource<T> {
  const data = shallowRef<T | null>(null);   // ← 每次呼叫都是新的
  …
}
```

它沒有 key、沒有跨呼叫點的儲存、沒有 in-flight 去重、沒有失效。
**沒有東西可以擴充。** 它進禁區清單，V1 的 28 個呼叫點一行不動。

### `modules/work/queryCache.ts`（目標 250–350 行）

| 能力 | 要求 |
|---|---|
| query key | `(project, view, filter, group, sort)` 的結構化 key，**序列化穩定**（key 的 property 順序不影響結果） |
| 快取 | `key → { data, error, updatedAt, inflight }` |
| in-flight 去重 | 同 key 的第二次請求回同一個 promise |
| invalidation | 前綴比對；`invalidate(['work-items', projectId])` 打掉該專案全部 |
| optimistic | `mutate(fn, { snapshot, rollback })`，**失敗必回滾** |
| 精準失效 | task update 只 invalidate card、drawer、counts 與相關 group |
| **不 reload 整個 Board** | 打開 Drawer 只取 task detail |
| Conversation | 獨立 infinite query，以 `conversation_seq` 合併；**append 不重排** |
| **counts 輪詢器** | [D95](./01-decisions-and-governance.md)：20s、`visibilitychange` 暫停、delta 才失效 items |

### 輪詢器的形狀

```ts
// 沿用 stores/dashboard.ts:134 已經在用的 setInterval + 生命週期綁定，
// 但把「誰負責停」明確化：Board 掛載時 subscribe，卸載時 unsubscribe，
// 最後一個 subscriber 離開時 interval 才 clear。
//
// document.hidden 時暫停而不是繼續打——一個開了三十個分頁的人
// 不該是這個 endpoint 最大的來源。
```

**反悔點**：若 `beta.1` 期間這 300 行開始長出 retry policy、
suspense、devtools 等框架特徵，就在 `beta.2` 改用套件。
這一條記在 [`11`](./11-open-measurements.md) 第 4 項。

## 3. View state 放哪

| 狀態 | 位置 | 理由 |
|---|---|---|
| shared view config | DB | 團隊共用 |
| personal saved view | DB | 跨裝置 |
| active view id | **URL**（`view=`） | 可分享 |
| temporary filter | **URL**（`f=`，base64url） | 可分享；「你看一下這個篩選」是真實需求 |
| group / sort | **URL**（`g=` / `o=`） | 同上 |
| open task id | **URL**（`task=`） | 可分享、可重整 |
| density | localStorage | 純視覺偏好，不寫 audit |
| board scroll | local transient | 不該進 URL |
| composer draft | **以 task id 隔離的 local 儲存** | mutation 失敗不得清除 |

URL 長度控制：`f=` 超過 1500 字元時退回「view id ＋ 本機暫存」，
並在 UI 說明「此篩選未包含在連結中」（[D103](./01-decisions-and-governance.md)）。

## 4. 目錄佈局

```text
modules/project/
  ProjectShell.vue              ← 導覽、麵包屑、共用 header
  views/
    ProjectOverviewView.vue  ProjectWorkView.vue  ProjectRequirementsView.vue
    ProjectRunsView.vue  ProjectRoadmapView.vue  ProjectActivityView.vue
    ProjectSettingsView.vue

modules/work/
  queryCache.ts   viewState.ts
  composables/  useWorkItems.ts  useViewState.ts  useOptimisticMove.ts
  components/
    WorkViewToolbar.vue  ViewSelector.vue  FilterBuilder.vue
    DisplayOptionsPopover.vue  QuickFilters.vue
    BoardColumn.vue  WorkItemCard.vue  WorkItemRow.vue
    AttentionBanner.vue  ExecutionLine.vue  MoveDialog.vue

modules/task/
  components/
    TaskDetailDrawer.vue  TaskPropertySidebar.vue
    RunSummaryPanel.vue  DeliveryReviewPanel.vue  DependencyPanel.vue
    ReadinessChecklistDialog.vue

modules/mywork/
  views/MyWorkView.vue
  components/AttentionSection.vue

modules/knowledge/                ← 已存在，PX-62 只加一個 export
```

**terminal／session／node／file 的畫面留在 `views/` 與 `components/`。**
不是因為版本承諾（☑ [D117](./01-decisions-and-governance.md#d117) 取消了那個），
而是因為**它們不在 `beta.1` 的範圍裡**——動它們要有自己的理由與自己的視覺基準。

Project／Task 的既有元件（`TaskBoard.vue`、`TaskDetail.vue`、`ProjectDetailView.vue`）
**會被新模組取代並刪除**，時程在 [`08`](./08-my-work-and-navigation.md) §7。

`ConversationPanel.vue` **留在 `components/project/conversation/`**，
由 `modules/task/TaskDetailDrawer.vue` 與 `views/TaskDetailView.vue` 共同 import。
理由不再是版本承諾，而是**它有兩個消費者**：Drawer 與保留的完整頁面
（`/projects/:id/tasks/:taskId`，在禁區清單，因為 ☑ D117 之後它是唯一的降級路徑）。
搬家要等到只剩一個消費者為止。

## 5. Token 增補（`PX-17`）

`tokens.css` 目前 **62** 個 custom property，已有 `--stage-*`（6）、
`--run-*`（6）、risk 三級。缺：

```css
/* Attention — 五個 */
--attention-human      /* 等待你的回覆 —— 最高層級，沿用 plan/19 D24 的處理 */
--attention-approval
--attention-blocked
--attention-failed
--attention-warning

/* Work lifecycle — 五個，作為 --stage-* 的語意別名 */
--work-backlog:  var(--stage-backlog);
--work-ready:    var(--stage-ready);
--work-progress: var(--stage-implementing);
--work-review:   var(--stage-verify);
--work-done:     var(--stage-done);
```

`--work-*` 是**別名而不是新色**：投影本來就是同一件事的兩個名字，
給兩組色會讓同一張卡在新舊看板顏色不同。

**Badge 不得只用顏色**：icon／text／shape 至少再有一項。
`checkTokens.test.ts` 的既有 gate 涵蓋新 token；
`staticGuards.test.ts` 繼續禁止未核准的 raw semantic color。
`research/style.md` 補一節非顏色規則（`PX-17` 的交付物之一）。

**不擴大 naive-ui 的使用面**（`plan/19` D35）；
**不重新引入全域 class layer**（`plan/19` D34）。

## 6. Conversation 的前端規格

| 規則 | 說明 |
|---|---|
| 三種 actor（human／agent／system）樣式清楚**但不只靠顏色** | icon ＋ 標籤 ＋ 排版位置 |
| Agent 問題以 **question card** 呈現 | 含「仍待回答／已回答／已逾時」三態（對應 `TaskQuestionDTO.state` 的四值，`cancelled` 併入「已回答」顯示為「已取消」） |
| Composer 支援 Markdown、reply-to、草稿保留 | **不新增附件路徑**（`alpha.2` D51 已裁決） |
| `waiting_for_input` 時固定顯示「回覆並繼續」 | 並說明會建立新的 Agent turn |
| 顯示 `sending` / `sent` / `agent_seen` / `failed` | `agent_seen` 的 tooltip 說明它**不代表模型同意** |
| **raw log 不混進 conversation** | system event 可折疊；log 以 deep link 開啟 |
| spec proposal 以可比較的 proposal card 呈現 | 接受／要求修改是**人類動作**，按鈕在 `task.approve` 之下才出現 |
| 輪詢而不是推播 | [D95](./01-decisions-and-governance.md)：Drawer 開著時 5s |

## 7. 效能

| 項目 | 目標 |
|---|---|
| Board 首次可互動（200 張卡） | < 2s |
| 打開已快取 Task Drawer | < 150ms 感知回應 |
| filter apply | < 300ms 感知回應 |
| optimistic move | < 100ms 畫面回應 |
| conversation reopen（最近 50 則） | < 500ms |

超過 1000 張卡再評估 virtualization。**200 張是第一個 gate**，
且 filter／group／sort **必須 server-side 可執行**——前端排序會讓分頁失去意義。

## 8. 不新增任何前端依賴

`frontend/package.json` 的 `dependencies` 進禁區清單（[`00`](./00-execution-plan.md) §3）。
包含 DnD 框架、query cache 套件、virtualization 套件、日期套件。

**唯一可能的例外**是一個小型 DnD helper，而本計畫的立場是
**先用 native HTML5 DnD ＋ 鍵盤路徑做出來**，
量到具體問題再開一張 ticket 討論依賴——因為
「鍵盤 move 是正式路徑」這條 a11y 要求本來就讓拖曳不是唯一入口，
而一個只服務拖曳的框架換不到那條路徑上的任何東西。
