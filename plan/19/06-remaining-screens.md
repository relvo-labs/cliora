# 06 — `UI-10`／`UI-11`：其餘畫面與審查畫面

## 1. `UI-10` — 其餘 V2 畫面對齊原語

五個畫面，都只做「換上原語 ＋ 補語意徽章」，**不重新設計資訊架構**。

### 1.1 `TaskRoadmap.vue`（17 個未定義引用）

- Epic → User Story → Task 三層，每層一條完成度 meter（prototype `.meter`）；
- Task 列用 `StageBadge` ＋ `DeliveryBadge`；
- 🆕 **「（未分類任務）」桶**：指定了 Epic 但沒指定 User Story 的卡要落在這裡。
  `research/02/09` §4.4 與 D4 明確定義過這個語意，**卡片不能憑空消失**。
  prototype README 把它列為「已知的視覺待辦」（假資料每張卡都有 US），
  **本期補上**——先確認 `TaskRoadmap.vue` 現況是不是真的漏了這桶，漏了才補。

### 1.2 `AgentsView.vue`（2 個未定義引用）

現況已在 V2.2 實作，本期只做：

- 表格換 `DataTable`；
- runtimes／labels 換 `quiet` 徽章；
- **確認三行說明文字還在**（`plan/18/07` §2.0–§2.2，它們承載安全語意）：
  - 「任何 runner 都可以領取任何專案的卡片。授權邊界是 enrollment。」
  - 「用途姿態」欄的 `⚠ 混合用途` 琥珀色標示；
  - labels「目前僅供辨識」。
- **容量或配額用盡時顯示原因，不顯示成離線**（`plan/18` 出口條件 21，已實作，回歸確認）。

### 1.3 `RunDetailView.vue`（1 個未定義引用）

- 時間軸換 prototype 的 `.tl` 版面（時間／點／事件／耗時四欄）；
- log 區塊維持既有的 JSONL 事件渲染（**不做 xterm.js**，`research/02/09` §4.7）；
- 機密遮蔽與截斷位元組數的明示**維持不動**；
- 「最後動靜：3 分鐘前」（D21 的 UI 形式）確認還在；
- `SourceBadge` 用於區分 daemon 觀測 vs Agent 自述的欄位。

### 1.4 `RequirementDetailView.vue`（5 個未定義引用）

- 四步 stepper（prototype `.stepper`）；
- `open_questions` 置頂 ＋ **未解決時核准按鈕停用並指名是哪幾個**
  （`research/02/09` §6：**不是靜默禁用**）；
- 提案樹三層縮排 ＋ DoR 缺項標示。

**V2.5 才有 Agent 驅動的部分，本期只對齊已存在的畫面。**

### 1.5 `ProjectsView.vue` / `ProjectDetailView.vue`（4＋8）

- `PageHead` ＋ `DataTable` ＋ `EmptyState`；
- 空狀態文案照 `research/02/09` §4.1 的原句：
  「還沒有專案。你仍然可以直接從 Sessions 建立 Ad-hoc Session。」
- 綁定列的三種狀態（node 離線／root 停用／路徑不存在）**要分得出來**，
  且都不是錯誤頁——是這一列上的一個狀態（`09` §4.2）。
  現況若只有兩種或全部顯示成同一種，本期補齊。

### 1.6 V1 畫面：只修 token，版面不動

`EnrollmentView.vue`、`FileTreeNode.vue`、`NewSessionDialog.vue`、`SessionWorkspaceView.vue`
在 `UI-02` 已修完引用。`UI-10` **不碰它們**。

---

## 2. `UI-11` — 審查畫面

### 2.1 現況：`TokenShowcaseView.vue` 是 V1 的

100 行，展示的是 `AsyncState` 九態、`StatusBadge` 五個 terminal 狀態、四顆按鈕。
**V2 的語彙一個都沒有**，而且它自己還寫死了兩個 hex（`#4e8593`、`#b34242`、`#e9edf2`）。

### 2.2 改成

保留 V1 那三區（它們仍然有用），**新增四區**：

| 區 | 內容 | 對應決定 |
|---|---|---|
| **三種「進行中」並排** | `Session 進行中`（綠）／`Task 進行中`（藍）／`Run 執行中`（琥珀＋脈動） | `09` §7 — **出口條件 3 就看這一區** |
| **兩組徽章的邊界** | 左：`StatusBadge` 的基礎設施狀態；右：`ui/*Badge` 的工作語彙 | D36 |
| **色票表** | 四組 token 逐項列出色票 ＋ 變數名 ＋ **實際 hex**（用 `getComputedStyle` 讀，不寫死） | D32 |
| **徽章一覽** | 六個 stage、八個 run 狀態、三個 risk、五個 delivery、三個 source 全列 | 審查用 |

hex **用 `getComputedStyle` 讀取**（prototype `fillHex()` 的做法），
不在模板裡寫死——寫死就會和 `tokens.css` 漂移，而這個畫面的用途正是核對它們。

### 2.3 順手清掉三個寫死的 hex

`TokenShowcaseView.vue` 現有的 `#4e8593`、`#b34242`、`#e9edf2` 改用 token。
**一個展示 token 的畫面自己寫死顏色，是這一期要修的那類問題的縮影。**

### 2.4 路由：它是 **dev-only**，這一點會影響出口條件 3

沿用既有路由，**不新增路徑**。但要知道它現在的形狀（`router/index.ts:128`）：

```ts
if (import.meta.env.DEV) {
  { path: "…", component: () => import("../views/TokenShowcaseView.vue") }
}
```

**它只在 dev build 存在**，而且 P4-07 為此定了一條斷言：
「以 `dist` grep 斷言 production bundle 不含它」。

**兩個後果**：

1. **出口條件 3（三種「進行中」一眼可區分）的人工確認是在 dev build 上做的**，
   不是在 production build。`08-…md` §5 要寫明這一點，證據截圖也要註明來源是 dev。
2. **P4-07 的那條 `dist` grep 斷言不得因為本期擴充而失效。**
   `UI-11` 把畫面內容變多了，但它仍然必須不進 production bundle——
   `UI-12` 要把那條 grep 納入回歸。

### 2.5 保留它的理由，P4-07 已經寫過

P4-07 原本要退場所有原型殘留，唯獨這一頁**定案保留**，理由是：

> **它是唯一能一頁看完 token 系統的地方，成本為零。**

本期讓 token 系統從 27 個變成 58 個，**那句話的份量只增不減**。

### 2.6 這個畫面要不要出現在導覽

**不要。** 它是開發與審查工具，不是產品畫面——沿用現況
（dev build 裡知道路徑的人進得去）。
`research/02/09` §2 的導覽三組不因此變成四組。

## 3. 完成定義

- [ ] 五個 V2 畫面換上原語，資訊架構不變
- [ ] Roadmap 的「（未分類任務）」桶存在（或確認本來就有）
- [ ] Agents 頁三行安全說明文字**逐字還在**
- [ ] Requirements 的核准按鈕停用時**指名是哪幾個問題**
- [ ] 專案綁定列三種狀態分得出來
- [ ] `TokenShowcaseView` 有四個新區，hex 用 `getComputedStyle` 讀
- [ ] `TokenShowcaseView` 自己不再寫死任何 hex
- [ ] `make tokens` 綠
