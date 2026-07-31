# Cliora Workspace 中央區 Tab 化與系統終端機 可實作規劃

本目錄把「Session Workspace 的中央區從上下分割改成 tab 切換」與「新增一個可直接操作 node shell 的 TERMINAL tab」轉成可建立 ticket、撰寫程式與驗收的執行規格。ticket 統一使用 `WT-` 前綴。

它由兩塊性質完全不同的工作組成，**刻意不綁在一起交付**：

| | 內容 | 性質 | 阻擋條件 |
|---|---|---|---|
| **A. 版面** | 移除左欄 Sessions 佔位、中央區改 tab（CLI / `[filename]`）、修掉 xterm 無法重掛的缺陷 | UI 重構 + 一個既有缺陷修復。不新增資料面能力、不動 protocol、不動 RBAC | 無。可立即開工 |
| **B. 系統終端機** | 第三個 tab `TERMINAL`，在 node 上開一個互動式 shell | **範圍變更**。它與 `SCOPE-011` 直接衝突，並且是 MVP 以來第一個能繞過 workspace 路徑限制的資料面能力 | `WT-04` 決策閘門**已於 2026-07-31 核准（選項 A：收窄 `SCOPE-011`）**；`WT-05` 起可開工 |

把 B 卡住不該讓 A 一起卡住——A 修的是每天都在用的操作體驗，以及一個現在按「Retry」就會踩到的終端機空白缺陷。

## 為何需要這一期

**版面**：`SessionWorkspaceView.vue:206` 在開啟檔案時把中央區切成 `1fr / 45%`，CLI 與預覽各拿一半高度，兩邊都難用。而左欄自前端首版 `05dd2ce` 起就只是一段佔位文字（`:201-204`），沒有繫任何資料、窄視窗還整欄隱藏，卻固定佔住 200px。`plan/03/09-implementation-status.md:20` 與 `docs/p2-report.md:24` 把 P2-12 標成 ✅ 並揭露了「右欄是 P3 佔位」，但沒有揭露左欄也是佔位——這是必須一併補正的紀錄漂移。

**一個真正的缺陷**：`useTerminalSession.ts:139-140` 的 `mount()` 在 `terminal` 已存在時直接 return，而它只從 `SessionWorkspaceView.vue:90-99` 的 `onMounted` 呼叫過一次。只要 `.workspace` 容器被卸掉再回來（初次載入失敗 → 按 `:144` 的 Retry 成功），就沒有任何人重新掛載 xterm，終端機從此寫進脫離 DOM 的節點，只能重新整理頁面。**tab 化會讓這個缺陷從邊角案例變成每次切 tab 都踩**，所以 `WT-02` 是 `WT-03` 的前置條件而非可選項。

**系統終端機**：需求本身合理——使用者在 workspace 內需要一個能 `git status`、看 log、裝套件的地方。但這件事在這個 repo 裡不便宜：

- `SCOPE-011`（criticality `must`）明文寫著不提供這個能力，而它的守門測試只檢查 wire 上沒有 command 欄位，**加一個 `shell` runtime 不會讓任何測試變紅**。綠燈不等於核准。
- P3/P4 花了整整兩期建立的 workspace 路徑限制（`TECH-SEC-05`、allowed roots、每次操作重新 canonicalize、唯讀檔案政策）對一個互動式 shell 全部失效——`cd ..` 就出去了。
- 反過來，`SEC-002`（前端不得指定 Command/Binary/Shell 指令）**可以完整保住**：只要前端送的仍然只是一個 runtime id，binary 由 node 自己的 config 決定，wire 上就依然沒有任何命令字串。這是本期選擇實作路徑的主要理由（見 `00-execution-plan.md` §3 D5）。

## 文件導覽

| 文件 | 用途 |
|---|---|
| [00-execution-plan.md](./00-execution-plan.md) | 成功定義、範圍與非目標、13 項固定基線決策、目標布局、ticket 波次、共同 DoD、阻擋規則 |
| [01-workspace-layout-and-tabs.md](./01-workspace-layout-and-tabs.md) | WT-01（左欄退場與規格同步）、WT-02（xterm 掛載生命週期修正）、WT-03（中央區 tab 化：CLI / `[filename]`） |
| [02-system-terminal-decisions.md](./02-system-terminal-decisions.md) | WT-04（**決策閘門**：ADR 0021、PRD 修訂與 `SCOPE-011` 處置）、WT-05（契約 v1.5.0、`terminal.shell` action、migration `0012`/`0013`） |
| [03-system-terminal-implementation.md](./03-system-terminal-implementation.md) | WT-06（daemon `shell` runtime）、WT-07（Central shell session：parent 綁定、authz 特例、audit、清單過濾）、WT-08（前端 TERMINAL tab） |
| [04-verification-and-exit.md](./04-verification-and-exit.md) | WT-09（traceability 註冊與影響分析）、WT-10（安全審查）、WT-11（驗收、evidence 與 exit gate） |
| [05-implementation-status.md](./05-implementation-status.md) | 各 ticket 實作狀態與實際證據；初始均未開工 |

## 使用規則

1. **A 與 B 分開合併。** `WT-01`→`WT-02`→`WT-03` 是一條可獨立上線的鏈，不得在其 PR 中夾帶任何 shell 相關程式、action key 或 protocol 變更。
2. **`WT-04` 是硬閘門，現已放行但仍需交件。** 處置已決定為選項 A（收窄 `SCOPE-011`），但 **ADR 0021 與 PRD 修訂合併之前，`WT-05` 起的程式仍不得合併**——決定本身不能取代把決定寫下來。理由在 §為何需要這一期：這件事沒有任何自動測試會擋，只有文件會擋。
3. **不為了 shell 放寬既有安全性質。** `SEC-002`（wire 上沒有命令字串）、`TECH-SEC-08`（terminal bytes 不進 log/DB）、daemon 不以 root 常駐、outbound-only daemon WSS——這四項在本期一律成立。做不到就記 waiver，不悄悄降級。**其中「daemon 不以 root 常駐」在 D6／D7 採寬預設之後是載重條件**：shell 不提升任何權限，daemon 的執行身分就是這個功能的權限上界。
4. **先看 repo 現況，不假設規劃中的檔案已存在。** 本目錄每一處主張都附 `檔案:行號`；實作時若發現與現況不符，先更新本目錄再改程式，不要讓計畫與程式各說各話。
5. **需求變更先改 `research/prd.md`／`tech.md`／`style.md`，再同步 `traceability/`。** 本期同時**移除**（左欄清單、上下分割）與**新增**（tab、shell）規格行為，兩個方向都要落到 PRD/tech/style 與 traceability，不得只改程式。移除既有 criterion 必須走 `lifecycle: deprecated` + `supersedes` + rationale，否則 `scripts/trace validate` 會失敗（ADR 0019）。
6. **時間一律 tz-aware**，shell session 的 `started_at`／`last_activity_at` 與 CLI session 走完全相同的路徑，沒有第二套時間邏輯。

## 完成結果

本期通過時：進入 Session Workspace 只看到兩欄（中央 + 右側檔案樹），中央區以 tablist 呈現 `CLI` 與最多一個 `[filename]` 預覽 tab，選中的 tab 佔滿整個中央區；切到預覽再切回 CLI 時，終端機仍是同一條連線、沒有 gap、沒有殘留舊尺寸，也不再有任何路徑能讓 xterm 掛不回來。`plan/03/05`、`plan/03/09`、`docs/p2-report.md`、PRD §10.6、tech §16.1、style §12 都已更新為實際交付的版面，沒有任何一份文件還在描述左欄清單或上下分割。

系統終端機部分（`WT-04` 已於 2026-07-31 核准，選項 A）：`TERMINAL` tab 在使用者持有 `terminal.shell`、且該 session 是自己擁有、且該 node 未停用 shell 時出現；它是一個 runtime 為 `shell` 的正規 session，因此 ws-ticket、single-writer、reconnect、terminate 與 audit 全部沿用既有管線，wire 上依然沒有任何命令字串；它綁定在 parent CLI session 上，parent 結束或 tab 關閉即終止，且任何其他使用者（含 Admin）都不能 attach 別人的 shell。ADR 0021 已書面記錄它繞過了哪些路徑限制、為什麼可接受、以及用什麼補償控制，`SCOPE-011` 已在 PRD 中被正式收窄並留下 supersedes 鏈——而不是靠一個仍然全綠的守門測試默默通過。
