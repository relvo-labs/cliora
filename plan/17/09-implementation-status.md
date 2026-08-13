# 09 — 實作進度與證據

本檔隨實作更新；「證據」欄只填**實際跑過的指令與其輸出位置**，不填計畫中的測試。

最後更新 2026-08-09：**十二張票的本機實作均已落地，本機自動驗證全綠；發布出口尚未全數完成。**
`scripts/tk/evidence.sh` 十一項 **11 passed / 0 failed**（含新增的 migration round-trip、
四個 gate、`make check`、`make test-db`、`make integration`、daemon 投影與 CLI、M1、
traceability）。`scripts/tk/browser-evidence.sh` 亦實跑：旗標關閉 21 passed／8 個本期功能
預期 skip，三角色導覽逐像素一致；旗標開啟 29 passed。新增的 Task 投影 live-stack 路徑
另跑 4 passed，M1 live HTTP 量測另跑 1 passed，並留下 Task Detail／Requirement 局部接受截圖。

**仍不能標成可發布**：出口條件 9 尚未在 Traqora 正式 repo 實跑；合併與 `agentd`
發布均須人工決定。M1 真實查詢已補量為 p50 7.98 ms／p95 9.37 ms（50 samples）。

## 1. Ticket 狀態

| Ticket | 標題 | 狀態 | 證據 |
|---|---|---|---|
| `TK-00` | 基線擷取 ＋ **M1** | ✅ | `artifacts/tk/local/baseline/`；payload = `m1.json`；真實 200 卡 live HTTP = `m1-live.json`（50 samples，p50 7.98 ms／p95 9.37 ms，61,748 bytes） |
| `TK-01` | ADR 0028、PRD §8.12、skill、traceability | ✅ | `docs/adr/0028-…md`；PRD §8.12（8 條 FR-TASK ＋ 43 條 AC）；八筆需求 `proposed` → `TK-11` 翻 `active`；`make traceability` 綠 |
| `TK-02` | migration `0023`／`0024`／`0025` ＋ 模型 | ✅ | 上下行 roundtrip 與基線逐位元組相同；`gate-schema-additive.sh` = additions only；`test_task_data_layer.py` 12 passed |
| `TK-03` | 流程定義內化（`0026`）＋ `ui` gate 衍生停用 | ✅ | `test_process_seed.py` 5 passed（含版本追隨內容的 tripwire）；`services/process.py` |
| `TK-04` | RBAC 三動作 ＋ Task API（同一個 PR） | ✅ | `test_tasks_api.py` 15 passed；`UNENFORCED_ACTIONS` 仍為空；permission-matrix／error-catalog 已重新產生 |
| `TK-05` | 需求／規格／提案的人工流程 | ✅ | `test_requirements_api.py` 8 passed（三條 API 層拒絕各一條） |
| `TK-06` | Session token 與 Agent principal（**安全審查**） | ✅ | `test_agent_credential.py` 12 passed；`docs/security-review-v21.md` 三節 |
| `TK-07` | contract v1.10.0 ＋ `agentd` 0.8.0 投影 | ✅ | 4 valid ＋ 10 invalid fixtures（三個語言都跑）；`daemon/internal/files/project_test.go` 8 tests；`gate-contract-additive.sh`：**96 個既有 fixture 逐檔未變** |
| `TK-08` | `cliora` CLI（＝ agentd 同一支二進位） | ✅ | `daemon/internal/cli` 8 tests（含離線兩句訊息逐字比對與 `context show` 免連線） |
| `TK-09` | 前端：看板、藍圖、任務詳情、Requirements | ✅ | `TaskBoard.test.ts` 6 tests；前端單元 501 passed；V2.1 Chromium 5 passed（含獨立 Task Detail、兩個未分類桶、相依拒絕、雙分頁回滾、局部接受與 M1） |
| `TK-10` | Task ↔ Session ＋ 投影觸發與呈現 | ✅ | `make test-db` 443 passed；live-stack 連開兩個 Task Session，兩份 context 各自存在、process 檔案集合不變、token 0600、情境包 ≤4 KB、git status 空白；移除 Node 會結束並隱藏其 active Session |
| `TK-11` | 驗證、證據、安全審查、release note | ◐ **本機完成／外部待驗** | `scripts/tk/evidence.sh` 11/11；雙旗標 Chromium 全綠；`docs/security-review-v21.md`；Traqora 實跑仍待人工環境 |
| — | **合併提案** | ⏳ **待人工** | 條件全綠只是取得提案資格，不是核准 |

## 2. 出口條件

| # | 條件 | 狀態 | 怎麼證的 |
|---|---|---|---|
| 1 | Epic→US→3 卡、拖曳、Roadmap 完成度、兩個未分類桶 | ✅ | Chromium 建立對應資料並驗兩個桶與 0/3；`test_the_roadmap_keeps_both_unclassified_buckets`；`TaskBoard.test.ts` 驗車道與移動 |
| 2 | 相依阻擋並指名 `card_ref` | ✅ | `test_a_blocked_card_cannot_enter_implementing_and_the_error_names_the_cards`（含 `blocked` 車道刻意可達） |
| 3 | 併發 409 ＋ 彈回 | ✅ | `test_the_second_writer_gets_409_and_the_current_version`（斷言**沒有半筆寫入**）＋ 前端兩條回滾測試 |
| 4 | 投影出現、情境包 ≤ 4 KB | ✅ | live-stack 真實 Session 斷言 context/token/process 出現、token 0600、兩條 AC 完整、context ≤4096 bytes；超限選填區塊明示省略，不切斷 AC |
| 5 | Agent 更新 → 看板 ＋ `actor_kind = agent` | ✅ | `test_an_agent_write_is_recorded_as_an_agent`（`actor_id` 為 null，不冒充人類） |
| 6 | Agent 勾 gate 被拒 | ✅ | session token 直打人類 gate 路由回 **401**；audit 記 `task.approve`、`actor_kind=session_agent` 與 token id，且 `user_id` 為空 |
| 7 | Central 停機時的 CLI 行為（D14） | ✅ | `TestAnUnreachablePlatformSaysTheSessionCanContinue`、`TestContextShowNeedsNoNetwork`、`TestAServerErrorIsTreatedAsUnreachable` |
| 8 | 第二個 Session 的流程檔被 skip | ✅ | live-stack 同 workspace 連開兩個 Session，第二份 context 新增、process 檔案集合完全不變；daemon 單元另斷言既有內容不被替換 |
| 9 | `git status --porcelain` 為空 | ◐ | live-stack throwaway git repo 實測為空；**Traqora 正式 repo 仍待做**（§4），因此不升為 ✅ |
| 10 | 旗標關閉回歸 ＋ contract 既有 fixtures 零變更 | ✅ | Chromium 21 passed／8 expected skip，三角色導覽逐像素一致；flag-off API 4 passed；96 個既有 fixture 未變、14 個新增 |
| 11 | `docs/security-review-v21.md` 完成 | ✅ | 三節已補 retry 單一 active token、90 天 DB retention、`.cliora/**/*.token` 固有敏感與 node 30 天清理邊界；對應測試全綠 |

## 3. 實作中發現、與計畫不同的九件事

| # | 計畫寫的 | 實際做的 | 為什麼 |
|---|---|---|---|
| 1 | M1 量「回應大小 ＋ p50／p95」 | **只量回應大小**，耗時延後 | 表在 `TK-02` 才存在。而決定形狀的是位元組：summary 在 500 張卡 180 KB，full 在 200 張就 439 KB——**分頁能買的，把 AC 與 gates 移出摘要就買到了** |
| 2 | 流程種子未指定 migration | 另開 **`0026`** | 角色權限與流程定義是不同領域、不同自然鍵；併在一起會讓其中一個的 downgrade 帶走另一個 |
| 3 | `SCOPE-002` 未預期被觸發 | **收斂 `test_scope_002` 的斷言範圍**，理由寫在測試裡 | 被禁的是**擋住執行**的審批；任務層的是治理，擋不住 Agent 執行的任何一個位元組，而 V2.1 根本沒有執行 |
| 4 | 稽核／activity 詞彙一次加齊 | 只加**有寫入點**的，其餘留給後續票 | 兩條 write-site 測試雙向失敗；這個 repo 的規則是引入名字的那次變更就要用到它 |
| 5 | Agent 端點掛 `/api/agent/` | 改為 **`/api/cli/`** | `SCOPE-001` 禁止任何 surface 命名 runtime 內部的 agent 概念。改一個路由名，比第二次收斂 scope 守衛便宜得多 |
| 6 | `GATE-TK-CONTRACT-ADDITIVE` 涵蓋 `contracts/` | **只涵蓋 `contracts/v1/fixtures/`**，`manifest.json` 具名豁免（列印，不靜默） | 新增訊息型別必然要改 envelope 的 enum；凍結全樹等於禁止這個階段。fixture 才是「對已部署 daemon 的承諾」 |
| 7 | 節點能力旗標未指定 migration | `0027_node_context_projection` | 與 `image_upload`／`file_upload` 同形狀，預設 false 且不回填——0.7.0 的節點確實不支援 |
| 8 | 兩條 AC 標為 `manual` | 改為 `measurement`（4 KB 預算）與 `automated`（`git status`） | schema 的 enum 沒有 `manual`；而且這兩件機器判得比人準 |
| 9 | 部分接受後其餘「保留」 | **可以稍後再接受**，且**逐項冪等**（卡片帶 `links.proposal_item_id`） | `research/02/10` §2.7 條件 5 說其餘保留；而同一項接受兩次會建出重複的卡，那是這條流程唯一會靜默出錯的地方 |

## 4. 尚待人工完成的三件事

1. **合併提案。** `v2` → `dev` 一律由人決定（`research/02/10` §7）。條件全綠只是提案資格。
2. **出口條件 9 在 Traqora 上實跑一次**（D30 的第一次真正使用）。機制與單元證據都在，
   缺的是在一個活躍 repo 上把 1–8 走完之後看 `git status --porcelain`。
   這需要一台 enroll 過的 node 與一份 Traqora clone，兩者都不在這台機器上。
3. **`agentd` 0.8.0 的發布時機。** 出口全綠不代表要推給所有 node；`node_update` 是既有的
   分批機制，本期不改它、也不自動觸發它。

## 5. 環境事實

| 事實 | 值 |
|---|---|
| 工具鏈不在預設 PATH 上 | `export PATH="$HOME/.local/bin:/usr/local/go/bin:$HOME/.nvm/versions/node/v22.23.2/bin:$PATH"` |
| DB 測試要**兩個**環境變數 | `CLIORA_TEST_DATABASE_URL` ＋ `CLIORA_DATABASE_URL`。少了後者，authz 拒絕的稽核 middleware 會連到不存在的 `cliora` 資料庫，症狀是三條 audit 測試無故失敗（`make test-db` 兩個都設，手動跑時最容易漏的一件事） |
| 本期結束時的基線 | contract **v1.10.0**、`agentd` **0.8.0**、migration 到 **0028**、RBAC **20** 個動作、前端六個導覽項（未變） |
