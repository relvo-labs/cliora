# 05 — `beta.1` 第二段：Active Board 與 Backlog

> **ticket 前綴 `PX-`。前置條件：[`04`](./04-phase-p1-view-and-read-model.md) 的 `PX-22`–`PX-27`。**

## 1. 這一段解決什麼

現況：固定六欄，`ORDER BY updated_at DESC`，沒有搜尋、沒有篩選、沒有分組、
沒有 Backlog 專用視圖、沒有排序控制、沒有 saved view。使用者為了回答六個不同的問題
（哪些等我？哪些沒有 runner？哪些 run 失敗？哪些還沒 ready？哪些待核准？
哪些屬於這個 Requirement？）只能在同一個畫面上用眼睛掃。

這一段之後：

```text
Active Board   Ready | In progress | Review | Done     ——今天要做的事
Backlog        高密度 List，可拖曳排序                  ——還沒投入執行的事
Saved views    個人的與專案共用的                       ——每個人自己的問題
```

## 2. Board Toolbar

由左至右：

```text
[View selector ▾] [Board|List] [🔍 Search] [Filter ▾] [Group ▾] [Sort ▾] [Display ▾] [⛶] [+ Create]
```

Quick filters（一列 chip，點擊即套用於目前 view，**不改存檔**）：

```text
Waiting for me · Agent active · Failed · Blocked · High risk · Unassigned · Gate unmet
```

**Quick filter 與 saved view 的關係要明確**：quick filter 是**暫時**的，寫進 URL，
不改 view 定義；改了之後 toolbar 顯示「已修改」與「另存為…／還原」。
這一條是提案沒寫但每個看板產品都要面對的歧義。

## 3. Active Board

### 3.1 預設四欄

```text
Ready | In progress | Review | Done
```

- **Backlog 不出現在 Active Board。**
- **Done 預設只顯示最近 7 天或最近 N 張**（N 預設 20），欄頭顯示「近 7 天 / 共 348」。
- **blocked work 留在原 stage**，卡片以 attention 呈現，不獨立成欄。
- 欄頭數字是 **server count**，不是已載入卡片數。這一條有測試（`PX-36`）——
  「已載入 20 張，欄頭寫 20，實際 348」是這類看板最常見的謊。

### 3.2 卡片結構

```text
┌─────────────────────────────────────┐
│ ⚠ Waiting for your input            │  ← primary attention（若有）
│ TK-142                              │  ← card ref
│ 支援 SAML SSO 登入                   │  ← title，最多三行
│ ─────────────────────────────────── │
│ 🤖 runner-03 · waiting · 12m        │  ← execution zone
│ ─────────────────────────────────── │
│ 陳小美 · high · PR · +2             │  ← metadata（依 view，最多 3–5 項）
└─────────────────────────────────────┘
```

| 區 | 內容 |
|---|---|
| Primary | card ref、title（≤3 行）、primary attention banner |
| Execution | runner 名、execution status、duration 或 waiting reason |
| Metadata | 依 view 的 `visible_fields`，最多 5 項 |
| Hover／focus | move、assign owner、dispatch／open run、more |

**Attention 不能只靠顏色**（`plan/19` 已建立的原則）：每個 attention 徽章
同時有 icon、文字與形狀差異中的至少兩項。

### 3.3 密度

| | Compact | Comfortable（預設） |
|---|---|---|
| 標題 | 1–2 行 | 3 行 |
| Execution line | 只在有 active run 時 | 總是 |
| Metadata | ≤2 | ≤5 |
| 適用 | 100–200 張掃描 | 日常 |

密度是**個人偏好**，不寫 audit，不影響 project view 定義。

### 3.4 Drag and drop

沿用 `plan/19` 已確立的 accessibility-first 原則：

| 規則 | 為什麼 |
|---|---|
| native DnD 或已核准的小型依賴 | 不引入大型 DnD 框架 |
| **keyboard move ／ Move dialog 是正式路徑**，不是備援 | 提案 P7；也是 a11y 出口條件 |
| optimistic update | 感知回應 < 100ms |
| **versioned mutation** | 帶 `version`，409 時回滾 |
| failure rollback ＋ 保留重試入口 ＋ 具體原因 | 「移動失敗」不是原因 |
| screen-reader announcement | 移動前後都播報 |
| **filter 開啟時送 neighbor IDs，不送 index** | 篩選後的第 3 個位置不是資料裡的第 3 個位置 |
| 不允許的 stage 在 drop target 就給拒絕線索 | 但 **server 仍是最終判斷** |

### 3.5 Grouping / swimlane

`beta.1` 提供：Epic、Owner、Agent、Risk、Requirement、Execution state。

**不得因 grouping 建立第二份排序真實來源。** rank 的 scope 是 project
（[D50](./01-architecture-decisions.md)），grouping 只改變顯示分組，不改 rank。
在 group 內拖曳只改變 rank，不改變 group 欄位——除非拖到**另一個 group**，
那時同時改 rank 與該欄位，且**兩者在同一個請求裡**。

### 3.6 大量資料

- 每欄獨立 cursor pagination；`Load more`。
- 欄頭 count 為 server total。
- 超過 1000 張再評估 virtualization；**200 張是第一個 performance gate**。
- filter、group、sort **必須 server-side 可執行**——前端排序會讓分頁失去意義。

## 4. Backlog

高密度 List，不用大卡片。

### 4.1 欄

```text
⠿  TK-142  支援 SAML SSO 登入       needs_clarification  陳小美  high  EP-3  [sso,backend]  2 天前
↑                                    ↑                     ↑       ↑     ↑     ↑            ↑
rank handle                          readiness            owner   risk  epic  runner tags  updated
```

### 4.2 操作

inline create、inline rename、drag rank、send to Ready、multi-select、
bulk owner／risk／labels、bulk move to Ready、attach to Epic／Story／Requirement、
open in Task Drawer。

### 4.3 Ready transition

移到 Ready 前：

1. 顯示 readiness checklist（既有 Definition of Ready 七項）。
2. 缺失時**拒絕並列出缺失項**（既有行為是警告，`beta.1` 維持警告或改拒絕，
   由 `PX-30` 依 process 設定決定——**不要在這裡硬編**）。
3. 可以直接從拒絕訊息開啟需要補的欄位。
4. **不允許 UI 先假設成功、之後才被 server 拒絕而找不到卡片**——
   這是 optimistic update 最常見的破口。

## 5. Rank

[D50](./01-architecture-decisions.md)：lexicographic 字串，從 `../kintra` 移植純函式。

```text
tasks.rank  VARCHAR(64) NOT NULL
scope       每個 project 一個序列
alphabet    base36 全小寫（避開 collation 差異）
不變式      非空 · 只含字母表字元 · 不以 '0' 結尾
再平衡      背景 24、同步保險閥 48
backfill    依現有 ORDER BY updated_at DESC 產生初始值
```

**「不以 `'0'` 結尾」是三個不變式裡最不直覺、也最重要的那一個**：
`'a0'` 的前驅要落在 `'a'` 與 `'a0'` 之間，而那之間沒有合法字串——
插入會無解。kintra 的測試已經涵蓋這個 case，一起移植。

## 6. Tickets

| ID | 工作 | 來源 |
|---|---|---|
| `PX-29` | Active Board 四欄預設 view ＋ Done 的近 N／近 7 天 | PX-29 |
| `PX-30` | Backlog List、inline create／rename、Ready transition | PX-30 |
| `PX-31` | Search、Filter builder、quick filters ＋「已修改／另存為」 | PX-31 |
| `PX-32` | Group、Sort、Display options、density | PX-32 |
| `PX-33` | Saved personal／project views、default、duplicate | PX-33 |
| `PX-34` | Optimistic move、rollback、retry、具體拒絕原因 | PX-34 |
| `PX-35` | Keyboard move、Move dialog、screen-reader announcement | PX-35 |
| `PX-36` | 每欄 cursor pagination、server counts 釘死測試 | PX-36 |
| `PX-37` | Full-screen board 與 state restore | PX-37 |
| `PX-61` | **Rank：移植 kintra 純函式 ＋ `/tasks/{id}/rank` endpoint ＋ 再平衡** | 新增（[D50](./01-architecture-decisions.md)） |

## 7. 出口條件

| ☐ | 條件 | 怎麼證明 |
|---|---|---|
| ☐ | Backlog 與 Active Work 清楚分離 | 兩個 view，Backlog 的卡不出現在 Active Board |
| ☐ | filter、scroll、view 在開關 Task 後保留 | E2E-J10 |
| ☐ | 所有 move refusal 都回滾並提供可行動原因 | 四種拒絕情境各一測試，訊息含 machine code |
| ☐ | keyboard 可完成建卡、開卡、移動與篩選 | a11y 測試 |
| ☐ | 欄頭 count 是 server total | 釘死測試：載入 20 張、count 顯示 348 |
| ☐ | filter 開啟時的移動送 neighbor IDs | 請求 payload 斷言 |
| ☐ | rank 三個不變式成立，再平衡不改變相對順序 | 移植的 kintra 純函式測試 ＋ 新的整合測試 |
| ☐ | grouping 不建立第二份排序來源 | 跨 group 拖曳的單一請求斷言 |
| ☐ | 200 張卡 Board 首次可互動 < 2s | 效能量測 |
