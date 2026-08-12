# 03 — `UI-04`／`UI-05`：徽章族與版面原語

**D34**：做成 `frontend/src/components/ui/` 底下的 Vue 元件，**不做全域 class**。

## 1. 兩組徽章的邊界（D36）

| 用哪個 | 什麼時候 | 狀態集 |
|---|---|---|
| `common/StatusBadge.vue`（**不動**） | 基礎設施健康度 | `connected`／`reconnecting`／`disconnected`／`exited`／`gap`／`online`／`degraded`／`offline`／`disabled`／`error` |
| `ui/*Badge.vue`（**新增**） | V2 工作語彙 | task stage、run 狀態、risk、delivery、evidence source |

這條邊界要在 `UI-11` 的審查畫面上**並排展示**，否則下一個人只會看到「有兩套徽章」。

## 2. `UI-04` — 徽章族

### 2.1 `BaseBadge.vue`

所有語意徽章的底座。三種變體，對應 D10 的可信度語言：

| 變體 | 樣式 | 語意 |
|---|---|---|
| `solid` | 實心底色 ＋ 白字 | **最強**：機器事實、當前 stage |
| `outline` | 透明底 ＋ 同色框線與文字 | **中**：平台紀錄、risk、delivery |
| `quiet` | 淺灰底 ＋ muted 字 | **最弱**：無交付、標籤、Agent 自述 |

```vue
<!-- props -->
variant: 'solid' | 'outline' | 'quiet'
tone:    string          // 對應一個 CSS class，不是一個顏色值（見 §2.3）
pulse?:  boolean         // 脈動點，只有 running / waiting_for_input 用
```

**每顆徽章一律帶文字**（B4）。`pulse` 是**附加**線索不是唯一線索——
色盲、單色列印、截圖壓縮之後，文字都還在。

### 2.2 五個語意徽章

| 元件 | props | 顯示 |
|---|---|---|
| `StageBadge` | `stage: TaskStage` | `solid`，六車道色，中文：待辦／阻塞／就緒／進行中／驗證中／完成 |
| `RunBadge` | `status: RunStatus`, `runnerName?: string` | `solid`；`running` 顯示「執行中 · <runner>」；`running`／`waiting_for_input` 帶 `pulse` |
| `RiskBadge` | `risk: string` | `outline`，低／中／高風險 |
| `DeliveryBadge` | `delivery: string` | `outline`；**`none` 用 `quiet`**——它不是一個承諾 |
| `SourceBadge` | `source: string` | 三級：`machine_verified`→`solid`／`platform_observed`→`outline`／`agent_reported`→`quiet`＋「Agent 自述」 |

**中文標籤只在顯示層**（B3）：`stage`／`risk`／`delivery` 的**值一律不動**，
改值會動到 API、契約與 Monstrare 的詞彙對應。

### 2.3 為什麼 `tone` 是 class 不是顏色值

prototype 寫的是 `style="background:var(--stage-${id})"`——**動態組出變數名**。
那在零依賴 prototype 裡很方便，但它有兩個代價：

1. `UI-03` 的檢查器**看不懂**動態組出來的名字（`07-…md` §3.3），
   等於這批 token 的引用全部逃出守門；
2. 打錯一個 stage 值就是靜默的無樣式，正是這一期在修的那類 bug。

所以元件用**明確的 class 對應**：

```vue
<span class="badge" :class="[`v-${variant}`, `t-${tone}`]">
```
```css
.t-stage-backlog { --badge-color: var(--stage-backlog); }
.t-stage-blocked { --badge-color: var(--stage-blocked); }
/* …每一個都明寫，共 20 行 */
```

**囉嗦 20 行，換到守門看得見、打錯會被 CSS 選擇器落空而在視覺測試中現形。**
這是一個為了可檢查性而做的實作選擇。

### 2.4 未知值退路（B5）

`BoardCard.risk` 與 `.delivery` 在 `dto.ts` 是 **`string` 不是 union**，
`RunStatus` 雖是 union 但後端可能先行新增值。

每個徽章的規則：

```
查不到對應標籤 → 顯示原字串，用 quiet 變體，不套色
```

**不得 throw、不得渲染空白、不得讓整頁壞掉。**
每個元件要有一個單元測試餵 `"totally_unknown"` 並斷言這個行為。

### 2.5 測試

| 測什麼 | 怎麼測 |
|---|---|
| 每個值都有中文標籤 | 遍歷 `TaskStage`／`RunStatus` 全集，斷言渲染出的文字非空且非原值 |
| 未知值退路 | 餵 `"totally_unknown"`，斷言顯示原字串 ＋ `quiet` |
| 三級 `source` 變體正確 | 斷言三個值分別得到 `v-solid`／`v-outline`／`v-quiet` |
| **D10 三處一致** | 斷言 `SourceBadge` 是唯一產生 source 徽章的元件（掃描 `src/` 沒有別處寫 `machine_verified` 的樣式） |
| 文字不依賴顏色 | 斷言每顆徽章的 `textContent` 非空 |

---

## 3. `UI-05` — 版面原語

> **`PageHead` 與 `UiCard` 不是本期發明的。**
> `P4-07`（`plan/05/03` §P4-07）在刪 `src/styles.css` 時就指定了替代方案：
> 「仍被使用的 class（`.primary` 5 檔、`.danger` 3 檔、`.head` 6 檔、`.panel` 2 檔、`.ghost`）
> → **遷移為共用元件：新增 `components/common/{PageHeader,Panel}.vue`**」。
> **那兩個元件從來沒有被建立**，而那五個 class 今天擴散到 17／9／15／9／22 個檔案
> （`01` §D34）。本期的 `PageHead` = P4-07 的 `PageHeader`，`UiCard` = `Panel`。

| 元件 | 取代 prototype 的 | 要點 |
|---|---|---|
| `PageHead` | `.page-head`（＝ P4-07 的 `PageHeader`） | slot：標題、副標、右側動作。`h1` 用 `--font-xl`。**吸收 `.head` 的 15 個散落實作** |
| `UiCard` | `.card` / `.hd` / `.bd`（＝ P4-07 的 `Panel`） | slot：`header`、預設。header 可省略。**吸收 `.panel` 的 9 個散落實作** |
| `DataTable` | `.table` | 薄封裝：表頭樣式 ＋ **`overflow-x: auto` 容器**（`base.css` 的既有決定：表格在自己的容器裡捲，不推給頁面） |
| `EmptyState` | `.empty` | **`action` slot 必填** ——見 §3.1 |
| `ToastHost` | `.toasts` / `.toast` | 全域單例，`UI-08` 的落點 |

### 3.1 `EmptyState` 的 `action` slot 為什麼必填

`research/02/09` §6 對空狀態的要求是「**有下一步動作的文案**」，
並舉了一個範例：

> 「還沒有專案。你仍然可以直接從 Sessions 建立 Ad-hoc Session。」

那句話同時教了兩件事。**把 `action` 做成必填 slot，是讓這條規則在型別上成立**，
而不是寫在文件裡等人記得。開發時忘了填，Vue 會在 dev 模式警告。

### 3.2 `ToastHost` 的形狀

- 掛在 `App.vue` 一次，全域單例；
- 用一個 composable `useToast()` 推訊息，不用 provide/inject 鏈；
- 位置：右下固定（prototype `.toasts`）；
- 自動消失 6 秒，**錯誤類不自動消失**——被拒絕的操作訊息要讓人讀完；
- `role="alert"`，鍵盤可關閉。

### 3.3 遷移紀律：沿用 P4-07 規定的做法

P4-07 對這件事已經寫過一條紀律，**照抄，不要重新發明**：

> **逐檔遷移 ＋ 每檔視覺回歸截圖**，避免一次大改造成 UI 迴歸。

所以 `UI-05` 的完成不是「元件建好了」，而是「**每一個被吸收的引用點各有一張前後對照**」。
這條規則在 P4-07 時就寫了，只是那次沒走到遷移那一步。

**本期的遷移範圍要先劃清楚**：`.head`（15 檔）與 `.panel`（9 檔）不是全部都要吸收。

| 吸收 | 不吸收 |
|---|---|
| `UI-09`／`UI-10` 本來就要改的 V2 畫面 | V1 畫面——它們受出口條件 8 的逐像素保護，**本期不碰** |

**V1 畫面裡的散落實作留到下一期。** 這一期把元件建起來、讓 V2 畫面用上它，
就已經止住了擴散；把 V1 也一起遷移會直接撞上出口條件 8。
剩下的數量要記進 `09-…md`，**不要讓它看起來像做完了**。

### 3.4 不做的

- **不做 Modal／Dialog 原語**：既有 `ConfirmDialog.vue` 與 `NewSessionDialog.vue`
  已經在用各自的做法，統一它們是另一期的事，本期不碰。
- **不做 Form 原語**：本期沒有新表單。
- **不把既有 view 全部改寫成原語**：`UI-10` 只對齊 V2 畫面，V1 畫面不動（§3.3）。
- **不動 `.primary`／`.danger`／`.ghost` 的按鈕樣式**：P4-07 也把它們列在遷移清單裡
  （17／9／22 檔），但按鈕牽涉 `naive-ui` 的取捨（D35），本期不開這個題。
  **記進 `10-…md` §6 當未決項**，不要默默跳過。

### 3.5 目錄與命名

```
frontend/src/components/ui/
  BaseBadge.vue
  StageBadge.vue  RunBadge.vue  RiskBadge.vue  DeliveryBadge.vue  SourceBadge.vue
  PageHead.vue    UiCard.vue    DataTable.vue   EmptyState.vue    ToastHost.vue
  labels.ts       // 所有 enum → 中文標籤的對應表，單一來源
  useToast.ts
```

`labels.ts` 是**唯一**的標籤來源。五個徽章都從這裡取，
所以「進行中」這三個字全 app 只寫一次。

### 3.6 完成定義

- [ ] 11 個檔案 ＋ `labels.ts` ＋ `useToast.ts`
- [ ] 每個元件有單元測試
- [ ] `EmptyState` 少了 `action` slot 會在 dev 模式警告（有測試）
- [ ] `make tokens` 綠——新元件不得引入任何未定義 token
- [ ] `UI-11` 能把全部 11 個元件在審查畫面上渲染出來
- [ ] **每個被吸收的引用點各有一張前後對照**（P4-07 的紀律，§3.3）
- [ ] 未吸收的 V1 散落實作數量記進 `09-…md`，不假裝做完了
