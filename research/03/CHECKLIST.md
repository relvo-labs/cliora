# 執行清單

13 份文件裡有 **76 張 ticket、9 份 ADR、5 項待裁決、9 個未量測項**散在各處。
這一份把它們攤平成可以逐條打勾的清單。

**閱讀順序**：§0 是現在就能做的 → §1 是擋著開工的 → §2 起是各里程碑。

---

## §0 現在就能做（不依賴任何裁決）

| ☐ | 事項 | 為什麼急 |
|---|---|---|
| ☑ | 把 `research/02/` 標註為 `v2.0.0-alpha.1` | ✅ 已完成（本次） |
| ☐ | 修正 `plan/19/README.md` 的狀態句 | 它寫「尚未開工」，但 `09-implementation-status.md` 寫「實作完成」。**任何讀計畫的人都會先讀 README** |
| ☐ | 跑 `alpha.1` freeze checklist（[`00`](./00-roadmap-and-versioning.md) §6） | tag 的前提；也是效能基線的量測點 |
| ☐ | 建立 `alpha.1` 的固定測試資料集 | 200 tasks／6 runs／10 waits／5 failures／dependency graph／500 messages／中型 repo。**每一個效能門檻都建立在它上面** |
| ☐ | 量測八項使用者任務的基線時間 | `beta.1` 的成功判準要有對照組，事後補量沒有意義 |
| ☐ | 對 `dev` 設 GitHub branch protection（若尚未） | 讓「合併需人工確認」由平台強制，不只靠紀律 |

---

## §1 擋著開工的裁決（原五項，D40／D42／D44 已定，剩兩項）

**未裁決前，相關 ticket 不開工。** 全文在 [`01`](./01-architecture-decisions.md) §3。

| ☐ | 決策 | 建議 | 擋住什麼 |
|---|---|---|---|
| ☑ | ~~**D44** — `alpha.2` 動不動 contract~~ | **已裁決 2026-08-16：不動** | — |
| ☑ | ~~**D40** — `alpha.3` 要不要向量檢索~~ | **已裁決 2026-08-16：不做** | — |
| ☑ | ~~**D42** — 放不放寬「一 run 一未答問題」~~ | **已裁決 2026-08-16：不放寬** | — |
| ☐ | **D46** — provider sync 落在哪一版 | **`beta.2`** | `alpha.3` 的範圍與 SR-2 的審查項 |
| ☐ | **D51** — conversation／knowledge 的保留、匯出、刪除 | 見 §3 建議 | `CV-03` 的 schema、`KN-02` 的 cascade 測試 |

---

## §2 `alpha.2` / V2-C1 — Ticket Conversation

> **`CV-00`…`CV-13` 已實作（2026-08-16）。** 進度、十二處與計畫不同的地方、
> 以及三項未完成的收尾，在 [`plan/23/10-implementation-status.md`](../../plan/23/10-implementation-status.md)。

**里程碑 C0 — Durable Thread**

| ☐ | ID | 工作 |
|---|---|---|
| ☑ | `CV-00` | 修 `plan/19/README.md`；產出 `alpha.1` known limitations 六條 |
| ☑ | `CV-01` | **ADR 0035** ＋ PRD／requirements 註冊（FR-CONV-001…010） |
| ☑ | `CV-02` | **ADR 0036 ＋ 0037 ＋ 0041**；`contracts/CHANGELOG.md` 明寫「本輪不動及理由」 |
| ☑ | `CV-03` | **Migration 0040**：seq／questions／turn 欄位／consumers ＋ backfill（相同 `created_at` 以 id 決勝） |
| ☑ | `CV-04` | Conversation query ＋ 冪等 mutation API ＋ 八個 machine code |

**里程碑 C1 — Answer and Resume**

| ☐ | ID | 工作 |
|---|---|---|
| ☑ | `CV-05` | Answer ＋ resume 原子交易（CAS、continuation enqueue、409 路徑） |
| ☑ | `CV-06` | Cursor catch-up 與 consumer 追蹤 |
| ☑ | `CV-07` | Child run：`parent_run_id`、turn 排隊、`waiting_for_input` 釋放 compute |
| ☑ | `CV-08` | CLI：`messages --after`／`wait`（≤120s）／`say --reply-to`／`propose-spec` |
| ☑ | `CV-09` | Context pack v2：初始摘要＋未決問題＋delta＋前 turn 摘要 |

**里程碑 C2 — Product UX**

| ☐ | ID | 工作 |
|---|---|---|
| ☑ | `CV-10` | Conversation UI：訊息串、question card、composer、delivery state |
| ☑ | `CV-11` | Spec proposal ／ 人工接受流程 |
| ☑ | `CV-13` | 卡片投影：`open_question_count`／`waiting_for_actor`／`conversation_last_seq` |

**里程碑 C3 — Hardening**

| ☐ | ID | 工作 |
|---|---|---|
| ☑ | `CV-12` | 安全、E2E（J3／J5／J6／J7／J8／J9）、chaos、metrics |
| ☐ | — | **SR-1 安全審查**通過並具名簽核 |
| ☐ | — | 出口條件 14 項全綠（[`02`](./02-phase-c1-ticket-conversation.md) §9） |
| ☐ | — | 建立 `v2.0.0-alpha.2` annotated tag ＋ GitHub pre-release |

---

## §3 `alpha.3` / V2-K1 — Project Knowledge Hub

**里程碑 K0 — Versioned Memory**

| ☐ | ID | 工作 |
|---|---|---|
| ☐ | `KN-01` | **ADR 0038** ＋ PRD／requirements 註冊（FR-KNOW-001…011） |
| ☐ | `KN-02` | **Migration 0041＋0042**；`CREATE EXTENSION pg_trgm` 在 compose ＋ Railway 兩條路徑驗證 |
| ☐ | `KN-03` | Event outbox ＋ 冪等 ingestion worker ＋ dead-letter ＋ reconciliation |
| ☐ | `KN-04` | Ticket／conversation／decision ingestion（**依賴 `CV-03`**） |
| ☐ | `KN-05` | Artifact／verification／evidence ingestion |
| ☐ | `KN-06` | Repository docs／symbol sync（commit 版本、exclude、增量） |

**里程碑 K1 — Cited Retrieval**

| ☐ | ID | 工作 |
|---|---|---|
| ☐ | `KN-07` | Lexical hybrid：tsvector ＋ trigram ＋ graph boost ＋ authority rerank |
| ☐ | `KN-08` | **ADR 0039** ＋ Context Builder 五層與 budget policy |
| ☐ | `KN-09` | Agent citation contract ＋ CLI |

**里程碑 K2 — Visible and Safe**

| ☐ | ID | 工作 |
|---|---|---|
| ☐ | `KN-10` | Knowledge UI：search／sources／versions／source health |
| ☐ | `KN-11` | Task Drawer 的 Related knowledge（pin／exclude／為什麼被選中） |
| ☐ | `KN-12` | 安全、prompt injection、cascade、relevance eval、metrics |
| ☐ | — | **SR-2 安全審查**通過並具名簽核 |
| ☐ | — | 出口條件 12 項全綠（[`03`](./03-phase-k1-project-knowledge.md) §11） |
| ☐ | — | 建立 `v2.0.0-alpha.3` annotated tag ＋ GitHub pre-release |

---

## §4 `beta.1` / V2-P1 — Collaborative Project Workspace

**第一段：View 與讀模型**

| ☐ | ID | 工作 |
|---|---|---|
| ☐ | `PX-17` | `--attention-*`（5）與 `--work-*`（5，別名）token |
| ☐ | `PX-18` | `WorkItemCard`／`WorkItemRow`（八種 attention × 兩種密度） |
| ☐ | `PX-21` | **ADR 0040 ＋ 0042** ＋ PRD／requirements 註冊（FR-WORK-001…012） |
| ☐ | `PX-22` | **Migration 0043**：`work_views`、`tasks` 五欄、索引、rank backfill、預設 view seed |
| ☐ | `PX-23` | Filter 驗證與 query compiler（15 欄 × 8 op、深度限制、三個 machine code） |
| ☐ | `PX-24` | Attention projection 單一來源 ＋ **200 張卡效能量測 ＋ 物化與否的裁決** |
| ☐ | `PX-25` | `work-items`／`work-counts` API ＋ **160 KB 釘死測試** |
| ☐ | `PX-26` | View CRUD API（scope、default audit、duplicate） |
| ☐ | `PX-27` | 前端最小 query 層（擴充 `useAsyncResource`） |
| ☐ | `PX-28` | OpenAPI 快照、RBAC、audit 測試；**`BoardCardDTO` diff 為空** |

**第二段：Board 與 Backlog**

| ☐ | ID | 工作 |
|---|---|---|
| ☐ | `PX-29` | Active Board 四欄 ＋ Done 的近 N／近 7 天 |
| ☐ | `PX-30` | Backlog List、inline create／rename、Ready transition |
| ☐ | `PX-31` | Search、Filter builder、quick filters ＋「已修改／另存為」 |
| ☐ | `PX-32` | Group、Sort、Display options、density |
| ☐ | `PX-33` | Saved personal／project views、default、duplicate |
| ☐ | `PX-34` | Optimistic move、rollback、retry、具體拒絕原因 |
| ☐ | `PX-35` | Keyboard move、Move dialog、screen-reader announcement |
| ☐ | `PX-36` | 每欄 cursor pagination ＋ **server count 釘死測試** |
| ☐ | `PX-37` | Full-screen board 與 state restore |
| ☐ | `PX-61` | **Rank**：移植 kintra 純函式 ＋ `/tasks/{id}/rank` ＋ 再平衡 |

**第三段：Task Drawer**

| ☐ | ID | 工作 |
|---|---|---|
| ☐ | `PX-38` | URL-driven Drawer shell ＋ Drawer primitive（focus trap／restore、aria） |
| ☐ | `PX-39` | Main ＋ Sidebar 版面、區塊順序、收合規則 |
| ☐ | `PX-40` | Inline editing 與 conflict recovery（**草稿保留**） |
| ☐ | `PX-41` | 整合 `CV-10`／`CV-11`：conversation-first waiting／resume |
| ☐ | `PX-42` | Run summary ＋ log deep link（**log 不混進 conversation**） |
| ☐ | `PX-43` | Artifact／delivery review 面板 |
| ☐ | `PX-44` | Verification／gate／**human actor ＋ 時間**呈現 |
| ☐ | `PX-45` | Dependency／Activity 面板 |
| ☐ | `PX-46` | 行動版全螢幕 detail |
| ☐ | `PX-62` | Related knowledge 區塊（整合 `KN-11`） |

**第四段：My Work 與 Overview**

| ☐ | ID | 工作 |
|---|---|---|
| ☐ | `PX-47` | 跨專案 My Work read model（共用 query compiler ＋ `derive_attention`） |
| ☐ | `PX-48` | Attention counts API（與 items **同 predicate**） |
| ☐ | `PX-49` | My Work 六個 section ＋ 個人 saved views |
| ☐ | `PX-50` | Project Overview attention strip |
| ☐ | `PX-51` | Active runs／recent delivery 模組 |
| ☐ | `PX-52` | Stale／failure 可見性 |
| ☐ | `PX-63` | 全域導覽重整（四組 ＋ My Work ＋ Dashboard→Home，**保留 fleet health**） |
| ☐ | `PX-64` | Project 子路由與 `ProjectDetailView` **逐頁**拆分 |

**收尾**

| ☐ | 事項 |
|---|---|
| ☐ | **SR-3 安全審查**通過並具名簽核 |
| ☐ | E2E **J1**（主旅程）通過——**不可降級** |
| ☐ | 八項使用者任務時間達標 |
| ☐ | 全期出口條件 34 項全綠（[`10`](./10-verification-and-exit.md) §9） |
| ☐ | 建立 `v2.0.0-beta.1` annotated tag ＋ GitHub pre-release |

---

## §5 `beta.2` / V2-E1 — Ecosystem and Hardening

| ☐ | ID | 工作 |
|---|---|---|
| ☐ | `HD-01` | **ADR 0043** ＋ provider webhook 入口（signature、去重、非同步） |
| ☐ | `HD-02` | PR／MR ingestion ＋ authority transition |
| ☐ | `HD-03` | Release ingestion ＋ provider reconciliation |
| ☐ | `HD-04` | Accessibility audit（WCAG 2.2 AA） |
| ☐ | `HD-05` | 視覺回歸套組擴充 |
| ☐ | `HD-06` | **Stage 最終遷移**（拆掉 D49 的過渡） |
| ☐ | `HD-07` | 舊路由 redirect 與 `?tab=` 相容 |
| ☐ | `HD-08` | Migration rehearsal（兩條部署路徑，upgrade／downgrade／restore） |
| ☐ | `HD-09` | Rollback drill ＋ 效能／負載測試（＋ 選配通知路徑，若 D44 改） |
| ☐ | `HD-10` | 大 Project 的 indexing／retention／queue／cost／observability |
| ☐ | `HD-11` | E2E 十六條旅程完整回歸 |
| ☐ | `HD-12` | Release note、known limitations、compatibility manifest、**人工合併提案** |
| ☐ | — | **SR-4 安全審查**通過並具名簽核 |
| ☐ | — | 建立 `v2.0.0-beta.2` annotated tag ＋ GitHub pre-release |

---

## §6 九個未量測項（不要假裝量過）

| ☐ | # | 項目 | 何時量 |
|---|---:|---|---|
| ☐ | 1 | 沒有向量檢索的召回率損失（D40 已裁決不做，這是已知取捨） | `KN-12` 建立基準值 |
| ☐ | 2 | attention 即時計算 vs 物化的效能差 | `PX-24` |
| ☐ | 3 | 300 行自製 query 層的維護成本 | `beta.2` |
| ☐ | 4 | 真實對話輪數、放棄率、多人併發頻率 | `beta.1` 之後 |
| ☐ | 5 | 大型 monorepo（>50k 檔）的索引時間與體積 | Horizon 2 |
| ☐ | 6 | chunk 大小與重疊的最佳值 | `KN-12` 之後 |
| ☐ | 7 | 十級 authority 是否過細 | `beta.1` |
| ☐ | 8 | `cliora task wait` 的 120 秒上限 | `beta.1` |
| ☐ | 9 | poll 5 秒是否需要調短 | `alpha.2` |

---

## §7 每個里程碑都要做的事

| ☐ | 事項 |
|---|---|
| ☐ | 該里程碑第一張 ticket 完成 PRD 增訂 ＋ ADR ＋ requirements 註冊 |
| ☐ | 出口條件全綠並保存證據 |
| ☐ | 對應的安全審查通過並具名簽核 |
| ☐ | 產出 [`00`](./00-roadmap-and-versioning.md) §7 的九項 release 產物 |
| ☐ | 在乾淨環境重跑 gates／測試，保存環境、版本與輸出 |
| ☐ | 驗證 feature flag 矩陣五種組合 |
| ☐ | 建立 annotated tag（**commit 一變就改版號，不移動舊 tag**） |
| ☐ | **`v2` → `dev` 的合併由人決定**——全綠只是提案資格 |
