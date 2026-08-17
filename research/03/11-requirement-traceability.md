# 11 — 需求註冊與追蹤

## 1. 為什麼這是每個里程碑的第一張 ticket

`.agent/skills/cliora-project-context/SKILL.md` 明文限制：不得在沒有需求變更的情況下
引入 task routing 與 Git automation。`make check` 的 `traceability-validate`
（`scripts/trace validate --level static`）會擋下沒有註冊的新能力。

本輪三個里程碑各自引入新能力：

| 里程碑 | 新能力 | 需要的需求變更 |
|---|---|---|
| `alpha.2` | 持久對話、continuation turn、冪等傳遞 | FR-CONV 家族 |
| `alpha.3` | 專案知識層、retrieval、context 組裝 | FR-KNOW 家族 |
| `beta.1` | 多視圖讀模型、rank、跨專案 attention | FR-WORK 家族 |

所以 `CV-01`、`KN-01`、`PX-21` 都必須包含「PRD 增訂 ＋ ADR ＋ requirements 註冊」，
否則後面每一張 ticket 都在違反這個 repo 自己的規則。

## 2. 新需求 ID

沿用 `FR-<AREA>-<NNN>`，AC 為 `<REQ>.AC-<NN>`，
註冊到 `traceability/requirements.json`（現有 **168 條**、26 個 family，
`schema_version` 不變，`owner` 用 `central`／`daemon`／`frontend`／`security`／`product`）。

### FR-CONV — Ticket 對話（`alpha.2`）

| ID | 標題 | Owner | 關鍵 AC |
|---|---|---|---|
| FR-CONV-001 | 持久 conversation 與單調序號 | central | 每張卡 `conversation_seq` 單調、無洞；backfill 對相同 `created_at` 以 id 決勝；cursor 分頁不重不漏 |
| FR-CONV-002 | 訊息型別與 resume 語意 | central | 六種 kind；`comment` 不改 run 狀態；`answer` 才可觸發續跑；舊值 `message`／`event` 讀取相容 |
| FR-CONV-003 | Question 生命週期 | central | 一個 run 同時一個 open question；四種狀態；24h 過期不刪除，事後回覆仍可續跑 |
| FR-CONV-004 | Answer ＋ resume 原子交易 | central | 單一交易完成 CAS、訊息、child run、audit；重複回答回 `409 QUESTION_ALREADY_ANSWERED` |
| FR-CONV-005 | 冪等傳遞 | central | 同 key 同內容 → 回原結果；同 key 不同內容 → 409；至少一次傳遞 ＋ consumer cursor 去重 |
| FR-CONV-006 | Continuation turn | central | child run `parent_run_id`／`turn_seq`／`input_from_seq`；每個 answer **至多一個** turn；daemon 重啟後可恢復 |
| FR-CONV-007 | Conversation 的 actor 邊界 | security | run token 不能寫 `decision`、不能跨 task、不能指定 actor；Viewer 不可發言；違反寫 audit |
| FR-CONV-008 | Spec proposal 與人工接受 | central | Agent 只能提 `proposal`；只有人類 `decision` 能改 readiness；proposal 不改 gate |
| FR-CONV-009 | CLI conversation bridge | daemon | `messages --after`／`wait`（上限 120s）／`say --reply-to`／`propose-spec`；`--since` 標 deprecated 保留一版 |
| FR-CONV-010 | Conversation 的保留與去識別 | security | body 大小上限；secret redaction 覆蓋 Agent message；audit 只記 metadata；run log 清除不影響 conversation |

### FR-KNOW — 專案知識（`alpha.3`）

| ID | 標題 | Owner | 關鍵 AC |
|---|---|---|---|
| FR-KNOW-001 | 版本化的知識來源 | central | `(project, type, external_id, version)` 唯一；provenance 六欄必填；supersede 鏈可查 |
| FR-KNOW-002 | 冪等 ingestion 與 outbox | central | `INSERT … ON CONFLICT` ＋ `source_updated_at` 比較；retry 不雙寫；dead-letter 有 age metric；排程 reconciliation |
| FR-KNOW-003 | Authority 層級 | central | 十級；**伺服器端判定，忽略 payload**；transition 可稽核；`superseded`／`retracted` 排除於預設 retrieval |
| FR-KNOW-004 | Lexical hybrid retrieval | central | full-text ＋ trigram ＋ graph boost ＋ authority／freshness rerank；精確 ref／symbol／SHA 找得到 |
| FR-KNOW-005 | Context Builder 與 budget | central | 五層；超限先砍 retrieved，**永不砍 policy 與未決問題**；manifest 含來源、版本、authority、token |
| FR-KNOW-006 | Instruction／evidence 分層 | security | 只有 accepted policy 進 instruction；repo 文字永遠是 data；注入 fixture 測試 |
| FR-KNOW-007 | Citations | central／frontend | 每段內容可回原來源；UI 可點回 message／文件版本／artifact／repo path |
| FR-KNOW-008 | Project isolation | security | 授權在 retrieval boundary；search／count／citation／context pack／cache 全部帶 `project_id`；無權查詢 count 為 0 |
| FR-KNOW-009 | 刪除、撤權與 tombstone | security | Project 刪除、source unlink、權限撤銷、retention 到期 → cascade 到 chunks／index／cache |
| FR-KNOW-010 | Per-project opt-in 與 source health | central／frontend | `knowledge_enabled` 需 `project.manage` ＋ audit；關閉時 search 回 404；health 顯示 lag／failed／dead letter |
| FR-KNOW-011 | Repository 同步 | central | commit SHA 為 immutable version；`.gitignore` ＋ `.clioraignore` ＋ project exclude；增量索引；不索引 vendor／generated／binary |

### FR-WORK — 工作視圖（`beta.1`）

| ID | 標題 | Owner | 關鍵 AC |
|---|---|---|---|
| FR-WORK-001 | 四個正交狀態面 | central | lifecycle 由 stage 投影；`blocked` → `ready` ＋ `is_blocked`；DTO 帶 `legacy_stage` |
| FR-WORK-002 | Attention projection 單一來源 | central | 單一函式、八級固定優先序；Board／List／My Work／Overview 結果一致 |
| FR-WORK-003 | Saved views | central | personal／project scope；DB 約束禁止無意義組合；default 變更寫 audit；不新增 RBAC 動作 |
| FR-WORK-004 | Filter allowlist | central | 15 欄位 × 8 運算子；深度 ≤3、條件 ≤20；違規回明確 machine code 並指名欄位 |
| FR-WORK-005 | work-items 讀模型 | central | cursor ＋ per-group cursor；counts 與 items 同 predicate；200 張 ≤160 KB；`BoardCardDTO` 不變 |
| FR-WORK-006 | Rank | central | lexicographic、project scope、三個不變式；filter 開啟時以 neighbor IDs 排序 |
| FR-WORK-007 | Optimistic mutation | frontend | 失敗必回滾；帶 version；拒絕提供 machine code 與可行動訊息 |
| FR-WORK-008 | Task Drawer | frontend | URL 驅動；關閉不丟 view／filter／scroll；403 不洩漏標題；conflict 保留草稿 |
| FR-WORK-009 | My Work 跨專案 | central | 單一 endpoint；權限在 query boundary；notification 已讀不影響 counts |
| FR-WORK-010 | Bulk update | central | ≤100 張；逐張授權；all-or-nothing；冪等；audit 一筆 batch ＋ 完整 item refs |
| FR-WORK-011 | Accessibility | frontend | 全鍵盤路徑為正式路徑；attention 不只靠顏色；focus trap／restore；狀態播報 |
| FR-WORK-012 | Feature flag 與相容 | release | PX flag 關閉回舊 UI；舊路由與 `?tab=` 相容；rollback 不刪 saved views |

### 修訂既有需求

| ID | 修訂 |
|---|---|
| FR-AGENT-006（Run log） | 補一句：**run log 不是 conversation 的依賴**；清除 log 不影響 conversation |
| FR-TASK-005（Review Gate 人工核准） | 補：Agent 的 `decision` kind 一律拒絕並記 audit |
| FR-TASK-003（看板與藍圖） | 補：新讀模型下 `blocked` 為 attention 投影；舊看板行為不變 |
| SCOPE-013（Central 對外連線） | **重申且不放寬**：`alpha.3` 不新增 egress；`beta.2` 的 provider sync 需 ADR 0043 明確擴充 |
| SEC 家族 | 新增 conversation 與 knowledge 的 redaction／isolation AC，掛在既有 SEC 條目下 |

## 3. ADR 清單

| ADR | 標題 | 里程碑 | 對應 ticket |
|---|---|---|---|
| 0035 | Ticket conversation、run turn 與 continuation 模型 | `alpha.2` | `CV-01` |
| 0036 | Conversation 的傳遞語意：cursor、idempotency、at-least-once | `alpha.2` | `CV-02` |
| 0037 | Conversation 的權限與 actor 邊界 | `alpha.2` | `CV-02` |
| 0038 | Project Knowledge 的來源、權威層級與 project isolation | `alpha.3` | `KN-01` |
| 0039 | Context Builder：instruction／evidence 分層與 budget policy | `alpha.3` | `KN-08` |
| 0040 | Work lifecycle、attention projection 與 stage 相容策略 | `beta.1` | `PX-21` |
| 0041 | Conversation 與 knowledge 的保留、匯出與刪除 | `alpha.2`／`alpha.3` | `CV-02`／`KN-01` |
| 0042 | View schema、scope、權限與 rank | `beta.1` | `PX-21` |
| 0043 | Provider ingestion：webhook 信任邊界與 reconciliation | `beta.2` | `HD-01` |

## 4. 必須同步修訂的既有文件

| 文件 | 修什麼 | 誰做 |
|---|---|---|
| `research/prd.md` | 新增 FR-CONV／FR-KNOW／FR-WORK 三節與 AC anchor | `CV-01`／`KN-01`／`PX-21` |
| `traceability/requirements.json` | 註冊 33 條新需求與其 AC | 同上 |
| `research/02/README.md` | ✅ **已修訂**：標註整體為 `v2.0.0-alpha.1`，`V2.x` 降為歷史 phase | 本次 |
| `plan/19/README.md` | 狀態句「計畫已定稿，尚未開工」→ 實作完成（以 `09-implementation-status.md` 為準） | `CV-00` |
| `.agent/skills/cliora-project-context/SKILL.md` | 範圍句：新增 project knowledge retrieval 與 conversation continuation | `CV-01` |
| `docs/adr/` | 新增 0035–0043 | 各里程碑第一張 ticket |
| `contracts/CHANGELOG.md` | 若 D44 維持不動：**明寫「本輪不動 contract 及其理由」** | `CV-02` |
| `README.md`（repo 根） | 功能清單新增 Ticket conversation 與 Project Knowledge | `beta.1` release 前 |
| `research/style.md` | 新增 attention／work token 與 badge 的非顏色規則 | `PX-17` |

## 5. Traceability gate 的期望

`make check` 的 `traceability-validate` 在每個里程碑之後應能：

1. 每條新需求都有 `source.path` ＋ `source.anchor`，且 anchor 在 `research/prd.md` 存在。
2. 每條 AC 有 `verification_profile`（`automated`／`inspection`／`manual`）與 `risk`。
3. `automated` 的 AC 都能對應到至少一個測試（`--level static` 只檢查註冊；
   完整對應在 `--level full`）。
4. 沒有 `lifecycle: proposed` 的需求出現在已發布 tag 的 release note 裡宣稱已完成。

**第 4 條是新增的。** 現況有 `lifecycle: proposed` 的條目（例如 FR-SPEC-008），
而 prerelease 的 release note 會列出「這一版做了什麼」——
兩者不一致時，`alpha.1` 的 freeze checklist 會發現。
