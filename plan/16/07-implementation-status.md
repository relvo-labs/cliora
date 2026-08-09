# 07 — 實作進度與證據

本檔隨實作更新；「證據」欄只填**實際跑過的指令與其輸出位置**，不填計畫中的測試。

最後更新 2026-08-08：**程式、文件與客觀驗證已落地；只剩人工合併提案。**
`scripts/pj/evidence.sh` 涵蓋兩個 project gate、schema／migration、靜態／單元／DB／
daemon integration／traceability 與 M-PJ-01；`scripts/pj/browser-evidence.sh` 另在旗標
關／開各跑一次完整 live-stack Chromium 套組。`.github/workflows/v2-projects.yml`
把相同的雙旗標套組固定進 CI。

最後一次本機結果：`evidence.sh` **10 passed／0 failed／2 個有理由的 browser skip**；
browser evidence 旗標關閉 **21 passed／5 個預期 project skip**，旗標開啟 **26 passed**。

## 1. Ticket 狀態

| Ticket | 標題 | 狀態 | 證據 |
|---|---|---|---|
| `PJ-00` | 基線擷取與 M8 量測（**閘門**） | ✅ 完成 | `artifacts/pj/local/baseline/`；M8 = 147px／餘裕 61px |
| `PJ-01` | ADR 0027、PRD 增訂、skill 範圍句、traceability | ✅ 完成 | 見下 |
| `PJ-02` | migration `0021`：三張新表＋`terminal_sessions.project_id` | ✅ 完成 | 見下 |
| `PJ-03`＋`PJ-04` | RBAC ＋ seed `0022` ＋ 七條 API（**同一個 PR**） | ✅ 完成 | 見下 |
| `PJ-05` | Session 關聯、`features`、旗標三個強制點 | ✅ 完成 | 見下 |
| `PJ-06` | 導覽重整、`/projects`、`/projects/:id` | ✅ 完成 | 見下 |
| `PJ-07` | 測試、旗標關閉回歸套組、`scripts/pj/evidence.sh` | ✅ 完成 | 見下 |
| `PJ-08` | release note、traceability 補齊、**合併提案** | ⏳ 待人工提案 | 技術收尾完成；`06-…md` §8 禁止 CI／agent 發起或完成合併 |

## 2. 出口條件

| # | 條件 | 狀態 | 怎麼證的 |
|---|---|---|---|
| 1 | 跨兩個 Node 綁定 ＋ 兩種不可用分得出來 | ✅ | DB：`test_one_project_spans_two_nodes`、`test_a_binding_is_judged_against_its_own_node`；瀏覽器：`projects.spec.ts` 的 root 撤銷與雙 Node 案例 |
| 2 | Project Session 入時間軸、Ad-hoc 不入| ✅ | DB 的 ad-hoc 案例；瀏覽器建立真 Session 與 Ad-hoc 後斷言 `session.started` 僅一筆 |
| 3 | 解綁不影響進行中的 Session| ✅ | DB 測試加瀏覽器解綁後重返 Session，斷言狀態、terminal 與檔案樹仍可用 |
| 4 | Node soft delete → 綁定列消失、DB 列仍在| ✅ | `test_soft_deleted_nodes_drop_out_of_the_listing_but_keep_their_row` 同時斷言重新啟用後綁定回來 |
| 5 | root 停用後以綁定路徑建 Session 被拒| ✅ | DB 重驗證；瀏覽器顯示 `root_disabled` 並斷言建立回 `WORKSPACE_OUTSIDE_ALLOWED_ROOT` |
| 6 | 旗標關閉：完整回歸 ＋ 導覽退回基線| ✅ | `browser-evidence.sh` 跑完整 live-stack suite，三角色導覽結構與 PNG 逐位元組相同；CI 另有 true／false matrix |
| 7 | `pg_dump` diff 只有預期的三表四索引一 ALTER| ✅ | `gate-schema-additive.sh`：diff 只移除 alembic revision 那一行；`gate-migration-roundtrip.sh` 下行後與基線完全相同 |
| 8 | `project_id` 與 workspace 不符回 400 且無列被建立| ✅ | `test_a_workspace_outside_the_projects_bindings_is_refused`（400 ＋ 斷言沒有任何 session 列） |
| 9 | Viewer 看得到專案、看不到 actor、寫入 403| ✅ | API／瀏覽器皆以精確 `POST /api/projects` 驗 403，並斷言只有一筆 `authz.denied`／`project.manage`；timeline actor 遮蔽另驗 |

## 3. 已裁決（2026-08-08）

開工前的三項確認全部完成，`PJ-01` 可以開工。

| 項目 | 裁決 | 落在哪 |
|---|---|---|
| **19 條「建議採納」決策** | **一次全數採納，三條例外** | `research/02/01` §決策裁決表的註記；`research/02/CHECKLIST` §1.2 |
| 例外 1 — **D7** | 「代打第一行指令」**整條刪除**，不留成 opt-in。檔案投影、情境包從 DB 產生、env 注入否決、`.cliora/` 30 天保留期不變 | `research/02/01` D7 段首 |
| 例外 2 — **D10** | 內文與裁決表的矛盾定案：否決的是「讓呼叫端指名命令的 API」，允許的是「daemon 在 run 目錄內執行卡片宣告的驗證命令」。進 ADR 0032 | `research/02/01` D10 段尾 |
| 例外 3 — **D13** | 歸屬不變；理由改寫為「`task.approve` 與 `task.update` 持有者集合刻意相同，拆開是為了 token scope 不是角色分離」。進 ADR 0027 | `research/02/01` D13 段內；本目錄 `01-…md` §3.1 |
| **ADR 0027 的核准範圍** | 核准紅線 4 的撤銷。**外加一項**：四條約束註冊成 `SCOPE-014`，由 V2.2–V2.4 各自接上 `guards_scope` gate | `01-…md` §3.1b |
| **導覽做法** | **無縮排分隔線 ＋ 子項不縮排**（prototype 的版本）。實測 147px／餘裕 61px；縮排版本 159px／49px，兩者都過，選前者是因為側欄還會再長 | `05-…md` §1.3；`08-…md` §1 |
| **驗收素材** | **V2.0 不用 Traqora**，用 `run-stack.sh` 的合成 workspace。D30 的第一次真正使用是 V2.1 | `00-…md` D13；已回寫 `research/02/01` D30 |
| **第二台 node** | `run-stack.sh` 加 **opt-in 的 `E2E_SECOND_NODE=1`**，預設關 | `06-…md` §2.5 |
| **M8** | **已量：147px／餘裕 61px，不用改** | `08-…md` §1 |

## 4. ~~開工前仍要做的兩件事~~（已完成，保留供追溯）

1. **`PJ-00`（基線擷取）。** 出口條件 6 與 7 需要「升級前」的 OpenAPI、`pg_dump`
   與導覽截圖，而那三份快照**改完就再也取不到**。
   **做法已定**：用 `scripts/e2e/run-stack.sh` 起一次性 stack 擷取，
   **不建長期的 dev 實例**——基線要證明的是「升級前的樣子」，而 e2e stack 可重現、
   CI 跑的也是同一份；一個手動維護的 dev 實例三個月後會漂移，那時沒人分得出
   diff 是 V2 造成的還是漂移造成的。
2. **`PJ-01` 的 ADR 0027 撰寫與核准。** 決定已經做了（§3），但文件還沒寫。
   `.agent/skills/cliora-project-context/SKILL.md` 明文禁止在沒有需求變更的
   情況下引入 task routing 與 Git automation。

**不擋開工但建議順手做**（`research/02/CHECKLIST` §0）：
對 `dev` 設 branch protection（required PR review ×1 ＋ 禁止 force push，
**刻意不加 required status checks**——加了會讓「CI 綠了」長得像「可以合併了」，
而 `10` §7 的整個意思是那兩件事不同）；把 `1b3054e` 的 `.env` gitignore 規則
cherry-pick 到 `dev`（已核對：`.env` 三條分支都沒被追蹤，這是預防不是補救）。

## 5. 環境事實（沿用 `plan/15/06` 記過的，開工時複驗）

| 事實 | 值 |
|---|---|
| 工具鏈不在預設 PATH 上 | `export PATH="$HOME/.local/bin:/usr/local/go/bin:$HOME/.nvm/versions/node/v22.23.2/bin:$PATH"` |
| Postgres | 5432 可達。**現存資料庫只有 `postgres`／`cliora_test`／`cliora_e2e`——沒有 `cliora`**，所以這台機器上目前沒有開發用的實例，也沒有任何已 enroll 的 node |
| `run-stack.sh` 只 enroll 一台 node | 出口條件 1／4 需要兩台。要加第二個 `agentd`（`06-…md` §2.5） |
| `make test-db` 要同時設兩個變數 | `CLIORA_TEST_DATABASE_URL` **與** `CLIORA_DATABASE_URL` |
| Playwright Chromium | **可用**（2026-08-08 由使用者補上系統套件）。`chromium-1228` / 149.0.7827.55，`ldd` 無缺項，`chromium.launch()` 實測通過 |
| Playwright 的 `@playwright/test` 只裝在 `frontend/node_modules` | `scripts/pj/*.mjs` 用 `createRequire(frontend/package.json)` 解析，不在 `scripts/` 再裝一份 |

> **B3 與 M8 是本期的閘門，而它們都需要瀏覽器——現在不擋了。**
> M8 已於 2026-08-08 量完（`08-…md` §1：採用的分隔線版本需 147px、餘裕 61px、不用改）。
> B3（三個角色的導覽截圖）仍待做，它需要跑起完整 stack（`scripts/e2e/run-stack.sh`），
> 那要 PostgreSQL 與一個真的 node，不只是瀏覽器。

## 6. 基線快照（`PJ-00` 完成後填）

全部擷取於 commit `1c28057`（`artifacts/pj/local/baseline/COMMIT.txt`），
目錄由 `.gitignore:18` 的 `artifacts/*/local/` 涵蓋。

| # | 項目 | 值／位置 | 擷取時間 |
|---|---|---|---|
| B1 | OpenAPI schema | `baseline/openapi.json`，**43 個 path** | 2026-08-08 |
| B2 | DB schema | `baseline/schema.txt`，254 行，revision `0020_node_file_upload` | 2026-08-08 |
| B3 | 導覽截圖 × 3 角色 ＋ 結構 dump | `baseline/nav-baseline-{admin,developer,viewer}.png`、`nav-baseline.txt` | 2026-08-08 |
| B4 | `docs/permission-matrix.md` 複本 | `baseline/permission-matrix.md` | 2026-08-08 |
| B5 | 路由清單 | `baseline/routes.txt`，**49 條** | 2026-08-08 |
| M8 | sidebar 最長項寬度 | **147px（`Integrations`，分隔線版），208px 餘裕 61px** | 2026-08-08 |

**B3 證實了 `README.md` 差異表第 2 條**（規劃文件說「現況五個平項」）：

```
[admin]      --layout-sidebar: 208px  entries: 6  groups: 0
[developer]  --layout-sidebar: 208px  entries: 3  groups: 0
[viewer]     --layout-sidebar: 208px  entries: 3  groups: 0
```

**兩處與計畫的偏離，都是環境限制而非裁量：**

| 計畫寫的 | 實際做的 | 為什麼 |
|---|---|---|
| `pg_dump --schema-only` | `scripts/pj/schema_snapshot.py`（SQLAlchemy 反射，輸出順序固定） | 這台機器沒有 PostgreSQL client，安裝要 root。而且它對這個 gate 更合用：`pg_dump` 的輸出夾帶 extension／owner／ACL 雜訊，要先過濾 diff 才有意義；反射輸出的每一行都是出口條件點名的事實（欄位、型別、可空性、預設值、FK ondelete、partial index 的 WHERE） |
| 只說「導覽截圖」 | 截圖 **＋** `nav-baseline.txt` 結構 dump | 截圖只告訴你「有東西動了」，dump 告訴你「動了什麼」。而 D11 的「既有路由路徑一律不變」是關於 href 的主張，不是關於像素的 |
| M8 | sidebar 最長項寬度 | **147px（`Integrations`，分隔線版），208px 餘裕 61px，不用改**（縮排版 159px／49px 亦通過，落選）。`scripts/pj/measure-sidebar.mjs` | 2026-08-08 |

## 7. 下一輪從這裡接手

**功能是可交付的。** 建 Project → 綁跨 node 的 workspace → 從綁定列開 Session →
看時間軸，整條路徑都在程式碼裡，並且在真的瀏覽器上跑過（`scripts/pj/browser-evidence.sh`）。

**旗標關閉時與升級前逐位元組相同**，而且這句話是可執行的：OpenAPI 只多了 5 條路徑、
8 個 schema、4 個可選欄位，**0 個被拒絕的變更**；schema diff 只移除了 alembic 版本那一行；
三個角色的導覽截圖 `cmp` 相同。

### 深入稽核補完了什麼

原本被標成完成、但只有淺層或 API 證據的項目，已補成使用者可操作且可重跑的證據：

| 項目 | 狀態 |
|---|---|
| **〔開 Session〕是個死按鈕** | ✅ 修好。`SessionsView` 現在讀 query 並直接打開對話框；`projects.spec.ts` 第 2 條守它 |
| **`NewSessionDialog` 的 prefill 可被誤改、無 Project 時沒有說明** | ✅ Project 頁 prefill 鎖定；只有明確按「Change to an ad-hoc session」才解鎖。無 Project 時 select 停用並說明仍可建 Ad-hoc |
| **Projects 畫面只有讀取，無管理閉環** | ✅ 補 create 的 slug／description、detail 的 edit／pause／archive、bind／unbind；loading skeleton、404 empty、request ID 與 retry 一併補齊 |
| **前端單元測試缺三組** | ✅ `ProjectsView.test.ts` 3 條、`ProjectDetailView.test.ts` 9 條、`NewSessionDialog.test.ts` 總計 20 條 |
| **Playwright 只有淺層 CRUD** | ✅ `projects.spec.ts` 5 條：UI bind、真 Session／Ad-hoc、解綁後 terminal＋files、Viewer 403＋audit、root 撤銷、雙 Node |
| **`E2E_SECOND_NODE` 沒做** | ✅ 加進 `run-stack.sh`，opt-in、各自的 workspace root。出口條件 1 因此轉為完全通過 |
| **`CLIORA_PROJECTS_ENABLED` 沒有文件** | ✅ `deploy/compose/.env.example` ＋ `deploy/railway/env.md`，兩處都寫出「開啟後每個角色多看到什麼」 |
| **summary 暗藏最新 1000 個 Project 上限** | ✅ `summary(project_id)` 改成直接查該 Project；1001 筆資料的回歸測試守住 |
| **旗標關閉沒有完整跑第二次** | ✅ `v2-projects.yml` true／false matrix；`browser-evidence.sh` 亦以單 worker 各跑完整 live-stack suite，避免共享 shell 狀態互撞 |
| **M-PJ-01 與導覽高度未量** | ✅ 50 bindings p95 53.917ms；1440×900、1920×1080 均無 sidebar overflow |

### 仍然沒關的兩件事

| 項目 | 為什麼 |
|---|---|
| **「路徑已不存在」偵測不到** | 它需要一次 `filesystem.*` 往返，而 V2.0 的 D12 與 `GATE-PJ-NO-WIRE` 明文禁止動 protocol 與 daemon。**做它就等於撤銷本期的核心約束**，所以留給 V2.1——那一期本來就要動 daemon（M-PJ-04） |
| **`SCOPE-014.AC-01..03` 仍是 `proposed`** | 分支命名空間、不推共用分支、不自動合併，這三條的 gate 要等 V2.3／V2.4 有 git 程式碼才存在。**AC-04（派工是拉取式）已於本期轉 `active`**，因為它今天就是真的、也守得住（`test_scope_014_dispatch_is_pull_based.py`）。把另外三條一起翻，等於宣稱一個不存在的護欄 |

### `GATE-PJ-NO-WIRE` 收窄了一次（PJ-09）

寫 env 文件時它擋下了 `deploy/compose/.env.example` 與 `deploy/railway/env.md`。
`deploy/` 底下有兩種檔案：`nginx.conf`、compose 拓撲、Railway 服務定義是**行為**，
改了就改變部署做什麼，繼續禁止；`.env.example` 與 `*.md` 是**文件**，
執行期沒有任何東西讀它們，而 `research/02/11` §3 明文要求新環境變數要寫進那兩個檔。
禁止它們會讓計畫自相矛盾。

**豁免會被印出來，不會靜悄悄**——一個會默默放行的 gate 是一個沒人能稽核的 gate。

### 一個順手修掉的既有缺陷

`make traceability` **在我動手之前就是紅的**，而且紅了五天：

* `LNK-SCOPE-007-AC-01-GUARDS-EXEC` 指向一個在 `plan/15` 被改名的測試
  （`test_scope_007_no_file_write_or_edit_surface` → `..._the_write_paths_are_both_additive`）；
* 覆蓋率帳本 pin 在 `414/283`，而 `plan/13`／`plan/15` 加了 26 個 criterion 沒有更新它。

兩者都與本期無關，但它們擋住本期的出口條件，所以一併修掉並在
`test_traceability.py` 的註解裡寫明**這 26 個不是 V2 的**。

### 移交給 V2.1／V2.2 的三件事

1. **`agent_runs_enabled` 這個設定本期不存在**（`04-…md` §2.1），所以
   `research/02/10` §3 的「兩個旗標各自獨立」**本期沒有被驗過**。V2.2 開工第一張票就加它。
2. **`terminal_sessions.task_id` 留在 V2.1 的 `0023`**，那時 `tasks` 表才存在，它會是真的外鍵。
3. **活動 `kind` 與稽核 `action` 是兩套詞彙**，而且交集是空的。V2.1 加任務事件時，
   前端要加的是 `utils/activityKinds.ts` 而不是 `auditActions.ts` ——
   拿錯了不會壞掉，只會把 `task.moved` 原樣印在畫面上。
   `test_activity_vocabulary.py` 現在會擋住這件事。

### 這台機器上的環境事實

| 事實 | 值 |
|---|---|
| 工具鏈不在預設 PATH 上 | `export PATH="$HOME/.local/bin:/usr/local/go/bin:$HOME/.nvm/versions/node/v22.23.2/bin:$PATH"` |
| Playwright Chromium | 可用（149.0.7827.55）。**但 headless Chromium 沒有 CJK 字型**，所以截圖裡的中文標籤是方框；`textContent` 是對的，只有圖上看不出來 |
| 沒有 `pg_dump` | 用 `scripts/pj/schema_snapshot.py` 取代，見 §6 |
| 資料庫 | `cliora_test`（`make test-db`）與 `cliora_e2e`（`run-stack.sh`）。**沒有 `cliora`** |
| `make test-db` 要同時設兩個變數 | `CLIORA_TEST_DATABASE_URL` **與** `CLIORA_DATABASE_URL` |

### 合併

**已提出，尚未核准。** 出口條件 **9 條全綠**（見 §2），回歸套組全數通過——
但這只是取得**提案資格**，不是核准（`06-…md` §8）。

| 項目 | 值 |
|---|---|
| 提案 PR | [#23](https://github.com/Lei-k/cliora/pull/23) `v2` → `dev` |
| 提出者 | 人工指示（2026-08-09） |
| 提案 commit | `cf47dd3`（PJ-00..PJ-09 的全部程式與文件） |
| 合併 commit／日期 | 待填 |

「客觀條件通過」與「可以合併了」是兩件事：後者還包含時機、其他分支的狀態、
要不要先等某個量測。**PR 開著不等於可以合**——合併時機由人決定，
CI 與 agent 都不得發起或完成它。合併後回填上表最後一列。
