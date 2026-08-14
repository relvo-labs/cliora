# 07 — 前端與指標（`DV-09`／`DV-10`）

前端要做的事分兩類：**顯示三張新表**（而顯示的方式決定了三級 `source` 有沒有意義），
以及**顯示五個指標**（而顯示的方式決定了指標會不會被讀成排行榜）。

## 0. 兩條沿用 V2.2_1 的守則

`plan/19` 那一期存在的理由是：V2.0–V2.2 的前端引用了 104 個未定義的 CSS token，
三個 V2 主畫面實際上以無樣式 HTML 渲染。所以：

1. **`make tokens`（`scripts/frontend/check-tokens.mjs`）是本期每一個新元件的前置條件**，
   不是收尾檢查。新增 token 要先進 token 檔再用。
2. **新元件一律附測試。** `plan/20` 的六處前端各自帶了測試
   （`AgentsView` 12 條 ＋ `ProjectSecrets` 7 條 ＋ `EnrollmentView` 2 條），
   本期沿用這個密度。

## 1. Task Detail 的四個新區塊

現況：`TaskDetailView.vue`（133 行，殼）＋ `TaskDetail.vue` ＋ `TaskAgentPanel.vue`。
本期新增四個元件，都掛在 `TaskDetail.vue` 下面。

### 1.1 `TaskExecutionPlan.vue`

顯示 `seq` 最大的一列，歷史可展開。五種 `status` 各自一個樣式，
**`failed` 與 `skipped` 不可用同一個灰**——一個是壞了，一個是刻意不做。

改計畫的 `note` 顯示在版本切換的地方，**不是折疊在裡面**：
「為什麼改」是這張表存在的理由（`version2.md` §7.5）。

### 1.2 `TaskVerification.vue`

最新一份報告 ＋ 歷史。三件事：

- **`result` 五值各一個樣式。** `partial` 不可以看起來像 `passed`。
- **失敗項排在前面且不可摺疊**（FR-VERIFY-001 的 AC）。
- **`source` 徽章**（見 §1.5）。

### 1.3 `TaskEvidence.vue`

九種 kind 分三組顯示（機器事實／平台紀錄／Agent 自述），
**組內按時間，組間不排序**。

**矛盾的處置**（`05-…md` §3.2）：`agent_finding` 與 `changed_files` 並排，
兩者都帶來源徽章，**中間沒有任何「以哪個為準」的提示**。
如果要加一句話，那句話是「**這兩份紀錄不一致，平台不判斷哪一份對**」——
陳述事實，不給結論。

### 1.4 `TaskDoneGate.vue`

**平時就顯示**，不是只在被拒時才出現。六項各一列，
綠勾／灰圈，缺的那幾項直接寫出缺什麼。

**為什麼平時就顯示**：一個只在失敗時出現的檢查清單，會讓人在拖卡片之前
不知道自己缺什麼——而「拖了才知道」正是使用者開始想繞過它的那一刻。

`--force` 的徽章掛在**卡片標題旁**（不在這個區塊裡），常駐、不可摺疊（`06-…md` §3.3）。

### 1.5 `SourceBadge.vue`（**這是本期最重要的一個前端元件**）

三種樣式，而它們必須**一眼看得出差別**：

| `source` | 文案 | 樣式 |
|---|---|---|
| `machine_verified` ＋ `origin: project` | 機器事實・專案設定 | 實心徽章，exit code **加粗等寬字** |
| `machine_verified` ＋ `origin: card` | 機器事實・卡片宣告 | 實心徽章（**同一個實心**）＋ 第二枚細徽章標 `origin` |
| `platform_observed` | 平台紀錄 | 描邊徽章 |
| `agent_reported` | Agent 自述 | 描邊徽章 ＋ **旁註「未經平台驗證」** |

⚠️ **兩個 `origin` 用同一個實心樣式是刻意的**（D4）：它們的**可信度相同**
（兩者都不是 Agent 選的），差別在**誰定的標準**。
把 `origin: card` 畫得比較淡，等於在畫面上宣稱一件資料上不成立的事——
而那正是這個元件存在的理由的反面。`origin` 是**第二枚徽章**，不是第一枚的深淺。

**「未經平台驗證」那句話是文字不是 tooltip。** 一個要 hover 才看得到的限定詞
等於沒有——而這一句正是整個三級分級唯一會被人讀到的地方。
**`origin` 的兩個字（「專案設定」／「卡片宣告」）同理**，理由一樣。

⚠️ **這一條要有畫面斷言**，形式抄 `plan/20` 的出口條件 3g（tag 不得被呈現為授權）：

```ts
test("an agent-reported row says it was not verified", …)
test("an agent-reported exit code is not rendered in the machine-fact style", …)
test("both origins render in the same machine-fact style", …)   // D4
test("origin is named in words, not encoded as a shade", …)
```

理由一樣：**後端做對了三件事，而一個把三級畫成一樣的畫面會讓它們全部白做。**

## 2. Run 詳情的交付結果

`RunDetailView.vue`（363 行）新增一個「交付」區塊：

| 情況 | 顯示 |
|---|---|
| `none`／`artifact` 無變更 | 「本卡宣告不交付程式碼變更。」 |
| `none`／`artifact` 有變更 | 「偵測到 N 個檔案變更，diff 已附為產物 →〈連結〉」 |
| `branch` | 分支連結 ＋ `diff --stat` |
| `pull_request` 成功 | **PR 連結** ＋ `diff --stat` ＋「由 Cliora 代為建立（憑證擁有者：X）」 |
| `pull_request` 無變更 | 「無變更，未建立 PR。」 |
| `delivered_branch_only` | 「分支已推送，**PR 未能建立**：{原因}。可手動開 PR →〈分支連結〉」 |
| `existing_pr` | 「已追加 N 個 commit 到 PR #{n}」 |
| `pending_pr` | 「PR 建立中…」（背景工作還沒撿到） |

**八種情況全部要有**，而 `GATE-DV-DELIVERY-COVERAGE` 的第四處就是這個元件的
`match`——五個 delivery 值都要在前端有分支。

`verification[]` 也在這一頁顯示（daemon 跑的那幾條），**帶 `SourceBadge`**。

## 3. 跨專案 Dashboard 的六個指標（`DV-09`）

掛在 `services/dashboard.py` 既有的 **per-block 降級契約**上，
不新寫一套（`README.md` 差異表第 16 條）。每一個指標是一個 block，
有自己的 `status` 與 `error_code`，一個查詢失敗只降級一格。

| # | 指標 | 定義 | 這個數字在說什麼 |
|---|---|---|---|
| 1 | 有 run 的 Task 比例 | 近 30 天建立的卡片中，至少有一次 run 的比例 | **內化路線的核心假設**：人真的把工作交給 Agent 了嗎 |
| 2 | 有驗證報告的完成 Task 比例 | 近 30 天進 `done` 的卡片中，有驗證報告的比例 | 判準是不是真的在運作 |
| 3 | `--force` 次數 | 近 30 天 | **判準是不是訂錯了**——不是抓人 |
| 3b 🆕 | `origin: card` 的檢查佔比 | 近 30 天所有 `machine_verified` 的檢查中，卡片宣告的比例 | D4 換來的彈性用得多不多。**偏高不代表壞**，但它是決定要不要打開 `require_project_verification` 的依據（`06-…md` §2.1 第 4b 項） |
| 4 | run 失敗率與失敗原因分布 | 近 30 天，依 `error_code` 分組 | 哪一種失敗最貴 |
| 5 | `waiting_for_input` 的平均等待時間 | 近 30 天 | **產品健康度**：等太久代表 Agent 問太多、或人回太慢，兩種都要知道 |

### 3.1 每個指標都要帶一句說明

**不是 tooltip，是卡片上的一行小字。** 一個沒有解釋的計數會被讀成排行榜，
而第 3 個指標尤其危險——它看起來像「誰在作弊」，而它實際上問的是
「我們的完成判準是不是訂得太嚴」。

### 3.2 指標不進任何自動阻擋邏輯（D14）

這一句要在程式碼裡有痕跡：`services/dashboard.py` 的五個新函式
**只被 dashboard 的路由呼叫**，`GATE-DV-METRICS-READ-ONLY` 掃
`services/runs.py`／`tasks.py` 不得 import 它們。

## 4. Project Overview 的擴充

`ProjectDetailView.vue`（1371 行——**本期不要再往裡面加**，新增的都做成子元件）：

- 進度（Epic／User Story 聚合）
- 風險摘要、阻塞摘要、驗證摘要
- **Agent 產能**：近 7 天完成的 run、平均時長、失敗率

四塊各一個元件，各自有自己的載入狀態。

## 5. Project Settings 的兩節（驗證命令、流程覆寫）

### 5.1 驗證命令 — 兩個來源，兩個地方（D4）

**Project Settings 這一節管 `origin: project`；卡片編輯管 `origin: card`**（§6b）。
兩處用**同一個輸入元件**（`VerificationCommandEditor.vue`），
因為兩者的驗證規則逐字相同（D5）——而兩份幾乎一樣的輸入元件會在其中一份
被修好的第一時間開始分歧。

### 5.1a Project Settings 的那一半（`project.manage`）

一張表：`name` ＋ argv（**多個輸入格，不是一個字串輸入框**）。
把它做成一個字串輸入框然後在後端 split，會讓 D5 的「不經 shell」
在使用者的心智模型裡消失——他們會期待 `make test && lint` 能用。

**存檔時算一次編碼後長度**（`03-…md` §4.2），超過就當場說哪一條太長。

底下一段說明：

> 這些命令由 **daemon 在執行目錄內執行**，結果記為「機器事實・專案設定」。
> 它們不經 shell，所以管線與 `&&` 不會生效——請拆成多條。
> 單張卡片可以再宣告最多 8 條自己的（在卡片上），
> **但 Agent 改不了那份清單**——那需要「核准」權限，而 Agent 憑證永遠沒有。

同一節底下是 `require_project_verification` 的開關（預設關閉）：

> 開啟後，一張卡若只跑了自己宣告的檢查、沒跑過任何一條這裡的檢查，
> 就不能進入「完成」。

### 5.2 流程覆寫（`process.manage`）

readiness 七項與 gates 各一排開關，WIP 一組數字。
**停用的項目要顯示「由這個專案關閉」**，而 integration 停用的顯示
「這個部署沒有 X 整合」——兩種原因不同色（`06-…md` §4.2）。

## 6. 卡片編輯：delivery 的五個選項

`TaskDetail.vue` 的 delivery 下拉從三個可用值變成五個。
選 `pull_request` 時**顯示 `target_branch` 欄位並標為必填**；
選 `existing_pr` 時顯示 `base_branch` 並**當場提示命名空間限制**：

> 只能接續平台自己開的 PR（分支在 `cliora/` 之下）。

當場提示而不是等 dispatch 被拒——`plan/20` 的卡片 tag 輸入
已經立過同一個先例（打錯字提示）。

## 6b. 卡片上的驗證命令（D4）

`TaskDetail.vue` 新增一區，用 §5.1 的同一個元件，**但按鈕的可見性綁 `task.approve`**：

- 有 `task.approve` → 可編輯。
- 只有 `task.update`（包含所有 Agent）→ **唯讀顯示**，旁註
  「新增或修改需要『核准』權限」。

⚠️ **唯讀而不是隱藏。** 一個看不到的清單會讓「這張卡到底驗了什麼」
變成一個要去問人的問題，而這一區的全部價值就是回答那個問題。
（同一條理由 `plan/20` 對 Repository 的 ⊘ 停用態表過一次：**停用不隱藏**。）

## 7. 驗收

| # | 斷言 | 怎麼驗 |
|---|---|---|
| 1 | 三種 `source` 樣式不同，且 `agent_reported` 帶「未經平台驗證」文字 | `SourceBadge.test.ts` 三條 |
| 2 | Agent 自述的 exit code 不用機器事實的樣式 | 同上 |
| 2b | **兩個 `origin` 用同一個實心樣式**，且 `origin` 以文字呈現 | `SourceBadge.test.ts` 兩條 |
| 2c | 卡片的驗證命令區：有 `task.approve` 可編輯、否則**唯讀不隱藏** | `TaskDetail.test.ts` 兩條 |
| 3 | 矛盾的兩列都在，且沒有「以哪個為準」 | `TaskEvidence.test.ts` |
| 4 | Done Gate 平時就顯示六項 | `TaskDoneGate.test.ts` |
| 5 | `--force` 徽章常駐且不可摺疊 | `TaskDetail.test.ts` |
| 6 | Run 詳情的八種交付情況各渲染一次 | `RunDetailView.test.ts` |
| 7 | 五個 delivery 值在前端都有分支 | `GATE-DV-DELIVERY-COVERAGE` 的第四處 |
| 8 | 六個指標各有一句說明 | `DashboardView.test.ts` |
| 9 | 沒有未定義的 token | `make tokens` |
| 10 | 路由數不變（19 條） | 與基線比對 |
