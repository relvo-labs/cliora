# 05 — PRD Patch 提案（`RQ-08`）

`version2.md` §7.6 的四步，**但平台不套用**。

```text
使用者提需求 → Agent 分析受影響的文件 → Agent 寫 patch 提案
            → 平台渲染 diff 與理由 → 人接受／拒絕
            → 接受後由 Agent（或人）在後續 run 中自己套用（走 delivery: pull_request）
```

## 1. 為什麼「不套用」不只是保守

三個理由，第三個才是決定性的：

| 理由 | 說明 |
|---|---|
| 套用一份 markdown patch 是**通用檔案編輯** | 那是 `plan/14` 被撤銷的能力。要它回來需要一份新 ADR，而本期換不到 |
| 平台沒有那個檔案 | patch 的目標在 repo 裡，而 Central **不 clone repo**（D1：只有 daemon 有工作目錄）。「套用」在 Central 上是一個沒有落點的動詞 |
| **走一張正常的卡比較好，不只是比較安全** | 一張 `delivery: pull_request` 的卡讓 PRD 的修改**跟程式碼一樣有 PR 可審**——有 diff、有 reviewer、有 branch protection。平台代為套用得到的是一個沒有人 review 的 commit |

第三條要寫進 ADR 0034 §6 的第一句，因為前兩條讀起來像「做不到」，
而真正的理由是「不該做」。

## 2. 四條路由

```text
POST   /api/cli/runs/patch-proposal      run 憑證，task.update      ← 第九條 run 路由
GET    /api/projects/{id}/patch-proposals            project.view
POST   /api/patch-proposals/{id}/accept              task.approve
POST   /api/patch-proposals/{id}/reject              task.approve
```

**沒有人工的建立路由。** 一個人要改 PRD 就直接改，不需要平台幫他記一份提案。
這條路存在的唯一理由是「Agent 想改，而 Agent 不能改」。

**沒有 `PATCH` 也沒有 `DELETE`。** 只 INSERT（`02-…md` §2 第 1 點），
`GATE-RQ-APPEND-ONLY` 對這張表斷言。

### 2.1 提交端的守衛

與另兩條 run 路由不同：**`card_kind` 不設限**。

理由是 `research/02/07` RQ-06 把它從 V2.4 移到 V2.5 時寫的那句話——
「它屬於這裡，它是釐清的產物之一」——但實務上**一張實作卡也會發現 PRD 錯了**。
一張「修復報表匯出」的卡在做的過程中發現 PRD 對匯出格式的描述與程式碼不符，
那時它應該能提一份 patch 提案，而不是只能在卡片上留言。

所以守衛只有三道：

```python
task = await _run_task(session, principal)     # principal.task_id 相符
# target_path 的三道格式驗證（02-…md §2 第 5 點）
# diff 長度 ≤ 256 KiB
```

`requirement_id` 從 `task.requirement_id` 帶（可為 NULL）。

### 2.2 `sections` 的四個封閉鍵

照 `version2.md` §7.6：

```jsonc
{
  "added_sections":    ["§8.17 匯出格式"],
  "modified_sections": ["§8.4 報表"],
  "removed_sections":  [],
  "related_docs":      ["docs/adr/0012-….md"]
}
```

`reason`、`related_task_ids`、`open_questions` 是獨立欄位（`02-…md` §2）。

**`open_questions` 在這裡也是一等欄位**，同一個理由：
一份「我不確定這一節該不該動」的 patch 提案，那個不確定必須看得見。
**但它不擋接受**——與規格核准不同。理由是 patch 提案的接受**不會產生任何東西**
（接受只是一個記錄 ＋ 一顆按鈕），而規格的核准會解鎖拆解。
**不對稱的閘門要有不對稱的理由，這是它的理由**，寫進 ADR。

## 3. 平台做的兩件事，以及不做的那一件

### 3.1 做：渲染 diff

前端顯示 unified diff。**唯讀、不可編輯、不可套用。**

渲染規則沿用 ADR 0015 的預覽政策與 D29 §4 的產物提供規則：

| 規則 | 為什麼 |
|---|---|
| 以純文字 ＋ 行內色塊渲染，**不解析成 HTML** | `diff` 是 Agent 產生的字串，而 Cliora 是單一 origin（ADR 0020）。一個 `<script>` 在 diff 裡是完全合法的內容 |
| 超過 256 KiB 在**提交時**拒絕，不是在渲染時截斷 | 截斷一份 diff 會產生一份看起來完整但實際上不完整的東西，而人會據此做決定 |
| 不提供「下載成 `.patch`」按鈕 | 一個可以下載的 `.patch` 會被有人 `git apply`，而那條路上沒有任何一道本期的關卡 |

**第三條看起來像過度保守，它不是。** 這一整節的設計是「平台不套用」，
而提供一個一鍵取得可套用檔案的按鈕，實質上把套用外包給使用者的終端機
——而那正是這一節要避免的東西的一個更難稽核的版本。
要拿到內容就複製文字，那一步的摩擦是刻意的。

### 3.2 做：記錄決定

`accept`／`reject` 各寫 `decided_by`／`decided_at`／`decision_note`、
一筆 audit、一筆 activity。`reject` 的 `note` **必填**（與提案拒絕同一條規則，`04-…md` §4.1）。

### 3.3 不做：任何檔案寫入

一條 gate：`services/` 底下處理 patch 提案的模組**不 import** `pathlib`／`os`／`shutil`，
且不出現 `open(`。

**這條 gate 守的是一個很容易被「順手」加上的功能**——
「既然都有 diff 了，加一個套用按鈕吧」——而它會通過所有測試。

## 4. 接受之後怎麼變成一張卡（C 類決策：不自動）

接受畫面在成功之後顯示一個按鈕：**「建立套用卡片」**，帶入：

```text
title            "套用 PRD patch #3：§8.4 報表"
card_kind        implementation
source           repo
delivery         pull_request
target_branch    （專案預設分支）
links.patch_proposal_id   <id>
objective        （帶入 reason）
description      （帶入 sections 的四項摘要 ＋ 提案連結）
```

**按鈕，不是自動建立。** 三個理由：

1. **接受一份提案與排一件工作是兩個決定。** 自動建立會讓「我同意這個 PRD 該改」
   變成「現在就去改」，而後者要決定 `target_branch`、`required_labels`、優先順序。
2. 一份 patch 提案可能對應**零張卡**——人看完覺得對，自己改了。那是完全正常的路徑。
3. 也可能對應**多張卡**——一份 patch 動了三份文件，而它們該分開審。

**`links.patch_proposal_id` 是唯一的連結**（`02-…md` §1.4），
所以 patch 提案的詳情頁能反查「這份提案產生了哪些卡」，
而卡片詳情頁能說「這張卡是為了套用 patch #3」。

## 5. 這一節與 RQ-07 的關係

兩者形狀相同（Agent 提案 → 人決定），**但它們刻意不共用程式碼**。

| | `task_proposals` | `document_patch_proposals` |
|---|---|---|
| 接受產生什麼 | **卡片**（一到多張，有 `overrides`、有 DoR 檢查、有相依翻譯） | **零個東西**（只有記錄 ＋ 一顆按鈕） |
| 接受可否分批 | 可以（部分接受） | 不行（一份 patch 是一個整體） |
| 拒絕要不要理由 | 要 | 要 |
| 進情境包 | 被拒的理由進下一次拆解（`04-…md` §4.2） | **不進**——patch 提案沒有「下一次」的概念 |

**「形狀像就抽出一個共用的 Proposal 基底」是本期要避免的一次重構**：
第一欄的複雜度全部來自「接受會產生卡片」，而第二欄沒有那件事。
一個共用基底會讓第二欄背著它用不到的一半。

## 6. 新增的 error code

| code | HTTP |
|---|---|
| `PATCH_PROPOSAL_TARGET_INVALID` | 422 |
| `PATCH_PROPOSAL_TOO_LARGE` | 422 |
| `PATCH_PROPOSAL_ALREADY_DECIDED` | 409 |
| `PATCH_PROPOSAL_REJECT_NEEDS_NOTE` | 422 |
