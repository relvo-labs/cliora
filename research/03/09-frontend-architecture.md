# 09 — 前端架構

## 1. 現況

```text
frontend/src/
  views/            28 個檔案，其中 ProjectDetailView.vue 1515 行
  components/
    project/        TaskBoard.vue 474 · TaskDetail.vue 734 · TaskRoadmap · TaskAgentPanel
                    ProjectRepositories · ProjectSecrets · ProposalTree · PatchProposals
                    TaskCompletion
    layout/ common/ ui/ session/ dashboard/ file/
  composables/      useAsyncResource ＋ 5 個
  stores/           12 個 Pinia store
  theme/            tokens.css（58 個 custom property）· base.css · checkTokens.test.ts
  api/              client.ts · dto.ts
  router/index.ts
```

依賴：`vue` 3.5、`vue-router` 4.5、`pinia` 2.3、`naive-ui` 2.42、
`lucide-vue-next`、`monaco-editor`、`@xterm/*`。
**沒有 server-state／query cache 套件**（[D56](./01-architecture-decisions.md)）。

## 2. 拆分 `ProjectDetailView`

1515 行同時管理 overview、board、roadmap、requirements、activity、
project editing、workspace binding、repository、secret、process、
requirement dispatch 與 task quick creation。不同風險等級的功能共存在同一層頁籤。

目標結構：

```text
modules/project/
  views/
    ProjectOverviewView.vue
    ProjectWorkView.vue           ← Board / List / Backlog 的容器
    ProjectRequirementsView.vue
    ProjectKnowledgeView.vue      ← alpha.3
    ProjectRunsView.vue
    ProjectRoadmapView.vue
    ProjectActivityView.vue
    ProjectSettingsView.vue       ← general/repos/runners/secrets/process/workspaces
  ProjectShell.vue                ← 導覽、麵包屑、共用 header

modules/work/
  components/
    WorkViewToolbar.vue  ViewSelector.vue  FilterBuilder.vue
    DisplayOptionsPopover.vue  QuickFilters.vue
    BoardColumn.vue  WorkItemCard.vue  WorkItemRow.vue
    AttentionBanner.vue  ExecutionLine.vue  MoveDialog.vue
  composables/  useWorkItems.ts  useViewState.ts  useOptimisticMove.ts
  queries.ts    viewState.ts

modules/task/
  components/
    TaskDetailDrawer.vue  TaskPropertySidebar.vue
    ConversationPanel.vue  MessageComposer.vue  QuestionCard.vue
    ProposalCard.vue  RunSummaryPanel.vue  DeliveryReviewPanel.vue
    RelatedKnowledgePanel.vue

modules/knowledge/
  views/ProjectKnowledgeView.vue
  components/SourceList.vue  KnowledgeResult.vue  ContextPreview.vue  SourceHealth.vue
  queries.ts

modules/mywork/
  views/MyWorkView.vue
  components/AttentionSection.vue
```

**拆分是逐頁進行的，不是一次改寫**（提案 R4 的緩解）：
每一頁在旗標關閉時走舊路徑、開啟時走新路徑，`PX-64` 逐頁切換並各自跑視覺回歸。

`modules/` 這個目錄名是新的（現況是 `views/` ＋ `components/<domain>/`）。
採用它的理由是 kintra 的 16 個模組證明了這個結構在同等規模下可讀；
**但既有的 `views/`／`components/` 不搬**——V1 的畫面留在原處，新結構只承載新模組。

## 3. Server state（[D56](./01-architecture-decisions.md)）

不引入套件，擴充 `useAsyncResource` 成最小 query 層（`PX-27`，約 200–300 行）：

| 能力 | 要求 |
|---|---|
| query key | `(project, view, filter, group, sort)` 的結構化 key，序列化穩定 |
| 快取 | key → `{ data, error, updatedAt, inflight }` |
| invalidation | 前綴比對；`invalidate(['work-items', projectId])` 打掉該專案全部 |
| optimistic | `mutate(fn, { snapshot, rollback })`，**失敗必回滾** |
| 精準失效 | task update 只 invalidate card、drawer、counts 與相關 group |
| **不 reload 整個 Board** | 打開 Drawer 只取 task detail |
| Conversation | 獨立 infinite query，以 `conversation_seq` 合併；**append 不重排** |

**反悔點**：若 `beta.1` 期間這 300 行開始長出 retry policy、
suspense、devtools 等框架特徵，就在 `beta.2` 改用套件，
並記進 [`10`](./10-verification-and-exit.md) 的未量測項。

## 4. View state 放哪

| 狀態 | 位置 | 理由 |
|---|---|---|
| shared view config | DB | 團隊共用 |
| personal saved view | DB | 跨裝置 |
| active view id | **URL** | 可分享 |
| temporary filter | **URL** | 可分享；「你看一下這個篩選」是真實需求 |
| open task id | **URL**（`?task=`） | 可分享、可重整 |
| density | personal preference（localStorage ＋ 之後同步 DB） | 純視覺偏好 |
| board scroll | local transient | 不該進 URL |
| composer draft | **以 task id 隔離的 local 儲存** | mutation 失敗不得清除 |

URL 長度要控制：filter 序列化用短鍵（`f=`）＋ base64url，
超過 1500 字元時退回「view id ＋ 本機暫存」並在 UI 說明「此篩選未包含在連結中」。

## 5. Conversation 的前端規格

| 規則 | 說明 |
|---|---|
| 三種 actor（human／agent／system）樣式清楚**但不只靠顏色** | icon ＋ 標籤 ＋ 排版位置 |
| Agent 問題以 **question card** 呈現 | 含「仍待回答／已回答／已逾時」三態 |
| Composer 支援 Markdown、附件、reply-to、草稿保留 | 附件沿用既有 artifact 上傳路徑 |
| `waiting_for_input` 時固定顯示「回覆並繼續」 | 並說明會建立新的 Agent turn |
| 顯示 `sending` / `sent` / `agent_seen` / `failed` | `agent_seen` 的 tooltip 說明它**不代表模型同意** |
| **raw log 不混進 conversation** | system event 可折疊；log 以 deep link 開啟 |
| spec proposal 以可比較的 proposal card 呈現 | 接受／要求修改是**人類動作**，按鈕在人類權限下才出現 |
| WSS 事件只 invalidate／append**已確認的** metadata | **不以 socket event 取代 server query** |

## 6. 元件清單（新增）

```text
WorkViewToolbar   ViewSelector      FilterBuilder     DisplayOptionsPopover
QuickFilters      BoardColumn       WorkItemCard      WorkItemRow
AttentionBanner   ExecutionLine     MoveDialog
TaskDetailDrawer  TaskPropertySidebar
ConversationPanel MessageComposer   QuestionCard      ProposalCard
RunSummaryPanel   DeliveryReviewPanel
RelatedKnowledgePanel  SourceList   KnowledgeResult   ContextPreview  SourceHealth
AttentionSection
```

沿用 `plan/19` 已建立的：`PageHeader`、`Panel`、`StatusBadge`、token 體系。
**不擴大 naive-ui 的使用面**（`plan/19` D35）；
**不重新引入全域 class layer**（`plan/19` D34）。

## 7. Token 增補（`PX-17`）

`tokens.css` 已有 `--stage-*`（6）、`--run-*`（6）、risk 三級。缺：

```css
/* Attention — 五個 */
--attention-human      /* 等待你的回覆 —— 最高層級，沿用 D24 的處理 */
--attention-approval
--attention-blocked
--attention-failed
--attention-warning

/* Work lifecycle — 五個，作為 --stage-* 的語意別名 */
--work-backlog  --work-ready  --work-progress  --work-review  --work-done
```

`--work-*` 是別名而不是新色：`--work-progress: var(--stage-implementing)`。
理由是投影（[`04`](./04-phase-p1-view-and-read-model.md) §2）本來就是同一件事的兩個名字，
給兩組色會讓同一張卡在新舊看板顏色不同。

**Badge 不得只用顏色**：icon／text／shape 至少再有一項。
`checkTokens.test.ts` 的 gate 涵蓋新 token；
`staticGuards.test.ts` 繼續禁止未核准的 raw semantic color。

## 8. 效能

| 項目 | 目標 |
|---|---|
| Board 首次可互動（200 張卡） | < 2s |
| 打開已快取 Task Drawer | < 150ms 感知回應 |
| filter apply | < 300ms 感知回應 |
| optimistic move | < 100ms 畫面回應 |
| conversation reopen（最近 50 則） | < 500ms |

超過 1000 張卡再評估 virtualization。**200 張是第一個 gate**，
且 filter／group／sort **必須 server-side 可執行**——前端排序會讓分頁失去意義。
