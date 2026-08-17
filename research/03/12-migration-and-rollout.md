# 12 — 遷移、`beta.2` 硬化與發布

> **`beta.2` 的 ticket 前綴 `HD-`（Hardening）。**

## 1. Feature flag 矩陣

| `CLIORA_PROJECTS_ENABLED` | `CLIORA_AGENT_RUNS_ENABLED` | `CLIORA_PROJECT_EXPERIENCE_V2` | 行為 |
|---|---|---|---|
| `false` | — | — | 全部 Project UI 與 API 關閉；**與 V1 完全一致** |
| `true` | `false` | `false` | 舊 Project experience；無 Agent 功能 |
| `true` | `true` | `false` | 舊 Project experience ＋ Agent Runner（＝ `alpha.1` 行為） |
| `true` | `false` | `true` | 新 IA、views、Drawer；**View 中不顯示 Agent-specific filter**，Board／Backlog 仍完整可用 |
| `true` | `true` | `true` | 完整 `beta.1` |

Conversation 與 Knowledge **沒有部署旗標**（[D52](./01-architecture-decisions.md)）：
前者是既有 `task_messages` 的修復，後者用 per-project 的 `knowledge_enabled`。

`CLIORA_PROJECT_EXPERIENCE_V2` 預設 `false`，`beta.1` 期間預設不變；
是否翻預設由 `beta.2` 依真實使用決定。

## 2. Schema 遷移策略

全部 **additive**，唯一例外是 `CREATE EXTENSION pg_trgm`（[`08`](./08-data-model-and-contract.md) §3.1）。

| Migration | 內容 | 可逆？ |
|---|---|---|
| `0040` | conversation seq／questions／turns／consumers | ✅ 欄位與表可 drop；backfill 的 seq 不可還原（無害） |
| `0041` | `pg_trgm` ＋ `projects.knowledge_*` | ⚠️ **extension 的 drop 需要沒有依賴物件**；downgrade 順序是先 `0042` 再 `0041` |
| `0042` | knowledge 六張表 | ✅ |
| `0043` | `work_views` ＋ `tasks` 五欄 ＋ 索引 | ✅ |
| `0044`／`0045` | provider sync（`beta.2`） | 待 ADR 0043 |

**每一個 migration 都要有一次演練**：在 `alpha.1` 的資料快照上跑 upgrade → 驗證 → downgrade → 驗證。
`HD-08` 是這件事的 ticket。

## 3. Stage 相容投影與最終遷移

[D49](./01-architecture-decisions.md)：`beta.1` **只做投影**，不動 `tasks.stage` 的值域。

### 3.1 `beta.1` 的過渡狀態

```text
資料庫      stage 六值不變 ＋ is_blocked/blocking_reason/blocking_message 三個新欄
舊看板      完全不變
新讀模型    stage='blocked' → lifecycle='ready' + is_blocked=true + legacy_stage='blocked'
新 UI 寫入  不再寫 stage='blocked'，改寫 is_blocked
舊 UI 寫入  仍可寫 stage='blocked'（新讀模型會投影它）
```

### 3.2 Ambiguous report

backfill 時，`stage='blocked'` 的卡設 `is_blocked=true`，
`blocking_reason` 依下列順序推導，**都推不出來就是 `unknown`**：

1. 有未滿足的 `task_dependencies` → `dependency`
2. active run 為 `waiting_for_input` → `human_input`
3. 最近一次 dispatch 失敗於資格判定 → `no_eligible_runner`
4. 指定的 runner 離線 → `assigned_runner_offline`
5. 最近 verification 不合格 → `verification_failed`
6. 有未通過的 gate → `gate_unmet`
7. 以上皆非 → **`unknown`，列入 ambiguous report**

**不猜測 previous stage。** 提案 §6.2 說「若無法安全推導 previous stage，
預設留在 `ready`」——本規劃採納，並補上：**留在 `ready` 這件事要出現在 report 上**，
因為那是一個猜測，即使是保守的猜測。

Report 是一個 CSV／JSON 檔案 ＋ 一個 UI 清單，內容：card_ref、title、
`updated_at`、最近 5 筆 activity、推導結果。**人工檢查完才能繼續**。

### 3.3 `beta.2` 的最終遷移（`HD-06`）

1. 確認 ambiguous report 已清空或已人工歸類。
2. dual write 期結束：舊 UI 下線，`stage='blocked'` 不再被寫入。
3. 把既有 `stage='blocked'` 的卡改寫為推導出的 stage ＋ `is_blocked=true`。
4. 加 CHECK 約束禁止 `stage='blocked'`。
5. 一段穩定期後才移除 `legacy_stage` DTO 欄位。

**`HD-06` 的存在本身就是 D49 這筆技術債的還款計畫。**
若 `beta.2` 決定不還，那要是一個明確的決定並記在 ADR 0040 的修訂，
而不是「後來就沒人提了」。

## 4. Route 相容

| 舊 | 新 | 處置 |
|---|---|---|
| `/projects/:id?tab=board` | `/projects/:id/work` | redirect（保留 query 的其餘部分） |
| `/projects/:id?tab=roadmap` 等 | 對應子路由 | redirect |
| `/projects/:id/tasks/:taskId` | 不變 | **保留**；Drawer 的「開新分頁」指向它 |
| `/projects/:id/requirements/:reqId` | 不變 | 保留 |
| `/projects/:id/runs/:runId` | 不變 | 保留 |
| `/dashboard` | `/` → Home | 保留 `/dashboard` 為別名 |

**browser back 必須依序：關閉 Drawer → 還原 view → 才離開 Project。**
這一條有 E2E 測試，因為它是「Drawer 用 `router.replace` 還是 `push`」
這個看似細節的選擇的可觀察後果。

## 5. Rollback

| 保證 | 怎麼達成 |
|---|---|
| 新 schema additive | 除 `pg_trgm` 外全部可 drop |
| 舊 UI 保留至少一個 release window | `beta.1` 與 `beta.2` 都保留 |
| PX flag 關閉後不讀 view tables | 程式碼層面的 guard ＋ 測試 |
| 新增資料不破壞舊 Task API | `BoardCardDTO` OpenAPI diff 為空 |
| **rollback 不刪除使用者 saved views** | 表保留，只是不被讀取 |
| **rollback 不刪除 conversation** | `alpha.2` 的資料是產品資料，降版後仍在 |
| knowledge 可整組停用 | `knowledge_enabled=false`，資料保留待人決定 |

**Rollback drill（`HD-09`）**：在 `beta.1` 的資料上，
把旗標關掉 → 驗證舊 UI 完整可用 → 把 `0043` downgrade → 驗證 → 再 upgrade → 驗證資料未損。

## 6. `beta.2` tickets

| ID | 工作 | 來源 |
|---|---|---|
| `HD-01` | **ADR 0043** ＋ provider webhook 入口（signature、delivery 去重、非同步 enqueue） | PX-K11 |
| `HD-02` | PR／MR ingestion 與 authority transition（merge 後升 `canonical`） | PX-K11 |
| `HD-03` | Release ingestion ＋ provider reconciliation 排程 | PX-K11 |
| `HD-04` | Accessibility audit（WCAG 2.2 AA） | PX-57 |
| `HD-05` | 視覺回歸套組擴充（沿用 `plan/19` baseline 機制，只補新畫面） | PX-55 ＋ PX-20 |
| `HD-06` | **Stage 最終遷移**（拆掉 D49 的過渡） | PX-54 |
| `HD-07` | 舊路由 redirect 與 `?tab=` 相容 | PX-53 |
| `HD-08` | Migration rehearsal（upgrade／downgrade／restore，兩條部署路徑） | PX-59 |
| `HD-09` | Rollback drill ＋ 效能／負載測試 | PX-58 ＋ PX-59 |
| `HD-10` | 大 Project 的 indexing、retention、queue、cost 與 observability | 新增 |
| `HD-11` | E2E 十六條旅程的完整回歸 | PX-56 |
| `HD-12` | Release note、known limitations、compatibility manifest、人工合併提案 | PX-60 |

`HD-09` 是**選配的通知路徑**（若 D44 改為採納）的落點；
維持不動 contract 時，`HD-09` 只做 rollback drill 與效能測試。

## 7. 每個 prerelease 的發布流程

```text
1  該里程碑出口條件全綠（10 的表）
2  安全審查（SR-1..SR-4 對應）通過並具名簽核
3  在乾淨環境重跑全部 gates 與測試，保存證據
4  產生 compatibility manifest（Central commit / agentd / contract / migration head）
5  撰寫 release note ＋ known limitations ＋ migration/rollback note ＋ security delta
6  驗證 fresh install / upgrade / downgrade，兩條部署路徑
7  驗證 feature flag 矩陣的五種組合
8  人工 sign-off
9  建立 annotated tag ＋ GitHub pre-release（勾選 pre-release）
```

**第 1 步到第 8 步任何一步失敗，就不是「先發再補」，是不發。**
prerelease 的意義是「這個邊界是可重現的」，不是「這一版比較不重要」。

## 8. 合併規則

`v2` → `dev` **一律由人工確認**。出口條件全綠只是取得**提案資格**。
任何自動化——CI、agent、排程——都不得執行這個合併。

發版到 `master` 時**不帶 V2**：從 V2 系列之前切 `release/*` 分支，不用 `dev` 當 head。
