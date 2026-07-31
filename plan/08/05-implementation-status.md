# 05 — 實作進度與證據

本檔隨實作更新；每一列的「證據」欄只填實際跑過的指令與其輸出位置，不填計畫中的測試。

最後更新 2026-07-31（第二次）：**WT-01 – WT-11 全部完成，退出條件全部關閉。**
`scripts/wt/evidence.sh` **13 道 gate 全數 exit 0，只剩 1 道 skip**（WebKit，安裝系統
函式庫需要 root，僅 CI）。`make traceability`：379 criteria / 248 verifiable / 0 blocking。
報告見 `docs/wt-report.md`，安全審查見 `docs/security-review-p8.md`。

第一次記為完成時，`04-…md` §3.3 有四項退出條件其實沒關；補齊的內容記在下方
[退出條件補齊](#退出條件補齊-2026-07-31)。**其中一項不是漏做而是做錯**：browser E2E
從來沒有在本機跑過，一跑就發現整個 `session.spec.ts` 是紅的。

## 波次 0：版面（可立即開工，不依賴任何決策）

| Ticket | 標題 | 狀態 | 證據 | 備註 |
|---|---|---|---|---|
| WT-01 | 左欄 Sessions 退場與規格同步 | ✅ 完成 | `make check`（退出 0）；`grep -rn "sessions-rail\|data-split" frontend/src` 無結果 | 規格同步七處：PRD §10.6、tech §16.1、style §12、plan/03/05（四處註記）、plan/03/09、docs/p2-report.md、research/01/00 roadmap。e2e 新增「workspace 頁沒有 Sessions heading」回歸鎖 |
| WT-02 | xterm 掛載生命週期修正 | ✅ 完成 | `npm run test:unit`：`useTerminalSession.test.ts` 14 例、`SessionWorkspaceView.test.ts` 10 例 | `mount()` 改為可搬移（`element.appendChild(terminal.element)`，不重建）；新增 `fitSafely()`／`applyFit()`／對外 `fit()`／`focus()`；`sendResize()` 對 <2 的 rows/cols 直接 return；view 改 `watch(host)` 掛載，`.workspace` 恆存在、狀態改用 `.veil` 覆蓋層 |
| WT-03 | 中央區 Tab 化（CLI / `[filename]`） | ✅ 完成 | `WorkspaceTabs.test.ts` 8 例；`SessionWorkspaceView.test.ts` 7 例；e2e `session.spec.ts` 新增 `centre tabs: preview and CLI share one live terminal` | 新增 `components/session/WorkspaceTabs.vue`（roving tabindex、`←/→/Home/End`、選中以字重＋底線非僅顏色）；`.center` 改 `auto 1fr` 且所有 panel 疊在同一 grid cell；CLI panel `v-show`、preview panel `v-if`+`v-show`；45% 分割與 `data-split` 已刪除 |

## 波次 1：決策閘門

| Ticket | 標題 | 狀態 | 證據 | 備註 |
|---|---|---|---|---|
| WT-04 | ADR 0021、PRD 修訂與 `SCOPE-011` 處置 | ✅ 完成 | `make traceability-validate`（PRD anchor 全部存在）；`make check` 退出 0 | `docs/adr/0021-system-terminal-and-shell-runtime.md`；PRD `SCOPE-011` 就地收窄（兩個 anchor 保留）、新增 §8.5.1 `FR-SHELL-001` 八條 AC、§10.6 補 TERMINAL tab；tech §12.2 runtime 值域與 §16.1 條件說明。**traceability 註冊留在 WT-09**（selector 必須與測試同一個 PR 落地） |
| WT-05 | 契約 v1.5.0、`terminal.shell` action、migration `0012`/`0013` | ✅ 完成 | `make contract`（Python 90／Go／TS 69 全綠）；migration upgrade→downgrade→upgrade 於 `cliora_test` 可重複執行 | schema runtime enum ×2、fixtures ×3（含 `invalid/session-start-shell-with-binary.json`）、manifest、CHANGELOG 1.5.0；七處 allowlist 同步；`rbac.py` + `dto.ts` + migration `0012`；`0013` parent 欄位與 partial unique index；`SHELL_ALREADY_OPEN` 由 `error_catalog.py` 產生（原計畫誤寫成手改 md） |

## 波次 2：系統終端機

| Ticket | 標題 | 狀態 | 證據 | 備註 |
|---|---|---|---|---|
| WT-06 | Daemon `shell` runtime 與 node 端停用開關 | ✅ 完成 | `go test -race ./...` 全綠，含 4 例新 config 測試 | `applyRuntimeDefaults()`（缺項即啟用、明確 `enabled:false` 不被覆寫）、`ShellFromDefault` 供啟動 log 標示來源、`install/plan.go` 預設啟用。**runtime 註冊表無需新型別**：`cliRuntime` 的 `--version` 探測對 `bash` 直接適用 |
| WT-07 | Central shell session（parent 綁定、authz 特例、audit、清單過濾、idle 回收） | ✅ 完成 | `make test-db` 253 passed（含 10 例新端點測試）；`pytest backend/tests` 594 passed（含 6 例 authz、6 例 reaper 測試） | `POST /api/sessions/{id}/shell`、`may_open_shell` + 四處 authz 收緊 + `can_open_shell`、parent 綁定與 terminate/status_changed 兩條 cascade、清單過濾、audit 加 `runtime`；`services/shell_reaper.py` 第三層兜底（每個中斷的 shell 一個有界計時器，非排程器；重連即自救；flap 無法延長期限；CLI session 永不被回收） |
| WT-08 | 前端 TERMINAL tab | ✅ 完成 | 前端 330 unit tests（含 6 例 TERMINAL tab 測試） | `openShell()` API、第二個 `useTerminalSession` 實例、延遲建立（點 tab 才開）、關閉即 terminate、三種錯誤碼文案與重試、安全邊界提示列 |

## 波次 3：驗證與退出

| Ticket | 標題 | 狀態 | 證據 | 備註 |
|---|---|---|---|---|
| WT-09 | Traceability 註冊與影響分析 | ✅ 完成 | `make traceability` 全綠；`docs/traceability/coverage.md` 中 `FR-SHELL-001.AC-01…08` 皆為 `verifiable` | 新增 requirement（8 criterion × 4 類 primary link = 32 條）+ `SCOPE-011.AC-01` `deprecated` 與 supersedes 鏈；`test_traceability.py` 的 pinned summary 由 372/241 更新為 379/248 並註明原因 |
| WT-10 | 安全審查 | ✅ 完成 | `docs/security-review-p8.md` | 12 列對抗表（原計畫 10 列；權限那列拆成 action/scope 兩例，另補「shell 內開 shell」與「同一 session 兩個 shell」）；3 項 finding |
| WT-11 | 驗收、evidence 與 exit gate | ✅ 完成 | `artifacts/wt/local/summary.md`（13 executed / 1 skipped） | `scripts/wt/evidence.sh`、`.github/workflows/wt.yml`（6 jobs，含「左欄與分割不得復活」的 grep gate）、`docs/wt-report.md`。evidence 腳本可自行以 `E2E_STACK_DATABASE_URL` 起全棧，browser E2E 不再是無條件 skip |

---

## 退出條件補齊（2026-07-31）

`04-…md` §3.3 的十項，第一次收工時有四項沒關。以下是補的內容與各自的證據。

| 退出條件 | 當時的狀況 | 補了什麼 |
|---|---|---|
| §3.3 第 4 項<br>「1440×900 與 <1100px 皆無水平溢位」 | **完全沒驗**。jsdom 沒有 layout，所以單元測試不可能回答；e2e 沒有設過 viewport；報告也沒有手測紀錄 | `session.spec.ts` 新增 `layout: no horizontal overflow at 1440x900 or below 1100px`：兩個尺寸各量一次 `documentElement.scrollWidth <= clientWidth`，失敗時列出最寬的元素；並斷言斷點以下檔案樹是隱藏而非被壓縮。開著檔案量，因為 Monaco 與 tab bar 才是會撐寬的東西 |
| §3.3 第 10 項<br>「Shell E2E 在 CI 上綠」 | **測試根本不存在**。`session.spec.ts` 只有 3 個 test，沒有一個碰 TERMINAL tab；`evidence.sh` 的 `skip "system terminal on a real node"` 是**無條件**的，在 CI 也會 skip，而 `wt.yml` 的 browser-e2e leg 沒有東西可跑 | `session.spec.ts` 新增 `system terminal: TERMINAL tab opens a real shell…`：真 node、真 `bash`，打一條指令並從 PTY 讀回輸出，切回 CLI 確認兩個終端機互不干擾，關 tab 後由伺服器自己的回應證明那個 session 結束、CLI session 仍連著。**已在本機 chromium + firefox 實跑通過**（WebKit 需 root 裝系統函式庫，仍為 CI-only）。stack 不需要任何 shell 設定——設定缺項即啟用，所以這一跑順便驗了升級路徑的預設值 |
| §3.3 第 9 項<br>「升級 release note 與 runbook」 | **兩份都不存在**。`docs/runbooks/` 八個檔案沒有一個提到 shell；`release-checklist.md` 與 `deployment.md` 也沒有。報告把它寫成待辦，但 WT-11 記為完成 | `docs/release-note-system-terminal.md`（給 node 擁有者：升級即取得、如何以 `enabled: false` 否決、權限上界為何是 daemon 身分、記錄與不記錄什麼）；`docs/runbooks/system-terminal.md`（判斷哪些 node 由預設啟用、停用步驟、稽核查詢、idle 回收、§6 事件處理）；`release-checklist.md` 新增 §4.5 六個勾選項，把「daemon 非 root」與「release note 已發出」變成放行條件 |
| `03-…md` §1.2(1)<br>「產生的 config.yaml 要能自我解釋」 | `MarshalConfig` 是純 `yaml.Marshal`，整份檔案沒有任何註解。node 擁有者是唯一的否決者，而否決權沒有寫在他會打開的那個檔案裡 | `MarshalConfig` 改走 `yaml.Node`，在 `runtime.shell` 區塊上方掛註解（是什麼、預設啟用含既有 node、如何停用、為何 daemon 不能是 root）。兩個新 Go 測試：註解必須在區塊正上方且能通過 `KnownFields(true)` 往回讀，以及**沒有偵測到 shell 時不得留下描述不存在區塊的註解** |

順帶修掉的：**`session.spec.ts` 三個既有 test 本來就是紅的**。P4-08 把登入後的落地頁改成
`/dashboard`，但 `signIn()`（連同 `files.spec.ts`、`nodes.spec.ts`）還在斷言 `/nodes`；
而 WT-08 之後 shell 的 xterm 實例一直掛在 DOM 上，任何沒有限定 panel 的 `.xterm-rows`
都變成兩個元素。「只有 CLI 一個 tab」這種以數量寫的斷言也會被 TERMINAL tab 破壞，已改為
以 label 斷言。這些只有真的把 leg 跑起來才會發現——這正是把它留成無條件 skip 的代價。

---

## 已決事項

### D-1：`SCOPE-011` 的處置 —— **選項 A（收窄）**

| 項目 | 內容 |
|---|---|
| 問題 | `SCOPE-011「不允許使用者從前端執行任意 Shell Command。」`（`criticality: must`，owner `product`）與 TERMINAL tab 直接衝突 |
| 為什麼需要人決定 | 它的守門測試 `backend/tests/test_scope_guards.py::test_scope_011_the_front_end_cannot_name_a_command` 只斷言 wire 上沒有 command 欄位。加入 `shell` runtime 之後**測試仍然全綠、coverage 不掉、release gate 不亮紅燈** |
| **決定** | **A —— 收窄。** 保留「前端不得指定命令字串」這條仍然有效的性質；新增 `FR-SHELL-001` 承接新能力，`SCOPE-011.AC-01` 標 `deprecated` 並由 `FR-SHELL-001.AC-03` 以 `supersedes` 取代 |
| 決定者 | 產品擁有者（neil） |
| 日期 | 2026-07-31 |
| 未完成的交件 | ~~ADR 0021~~✅、~~PRD 修訂~~✅、traceability 的 supersedes 鏈（`04-…md` §1.3，留在 WT-09） |

### D-3：RBAC 範圍 —— **Admin + Developer**

| 項目 | 內容 |
|---|---|
| **決定** | `terminal.shell` 授予 **Admin 與 Developer**；Viewer 不得取得 |
| 日期／決定者 | 2026-07-31／neil |
| 影響 | 邊界從「角色」移到 **ownership**：只能在自己擁有的 session 上開 shell、不能 attach 他人的 shell。`WT-10` 第 2b 項為此新增獨立測試 |
| 連帶條件 | **daemon 非 root 執行從最佳實踐升級為部署阻擋條件**（`00-execution-plan.md` §8） |

### D-4：Node 端預設 —— **預設啟用**

| 項目 | 內容 |
|---|---|
| **決定** | `runtime.shell` 預設啟用；設定缺項亦視為啟用；node 可明確 `enabled: false` 停用 |
| 日期／決定者 | 2026-07-31／neil |
| 影響 | **既有 node 升級 daemon 後即取得遠端 shell 能力**。需 release note、runbook、daemon 啟動 log 標示啟用來源（`03-…md` §1.2），並測試「明確停用不會被 defaults 覆寫」 |
| 尚可反轉 | 若要改為「只有新安裝預設啟用、既有 node 維持現狀」，只需拿掉 `applyRuntimeDefaults()` 的注入，其餘不變 |

---

## 待調整（非阻擋）

### D-2：`shell_idle_terminate_seconds` 的預設值 —— **已採 900 秒**

已實作於 `services/shell_reaper.py`，預設 900 秒，理由與「刻意與 `FR-SESSION-006` 相反」
的取捨寫在 ADR 0021 §6 與該模組的 docstring。**預設值本身仍待實測調整**：目前沒有使用
資料可以判斷 15 分鐘是否太長（安全審查 Finding 3）。

---

## 已知不修（本期刻意降級，不是漏項）

左欄移除後 `SessionWorkspaceView.vue:103-111` 的原地切換不再是使用者動線，以下三項明確不修（詳見 `00-execution-plan.md` §6）：

1. `connect()` 未 `terminal.reset()`，原地換 session 會殘留前一個的 scrollback。
2. `role` / `exit` ref 在 `connect()` 中未重設。
3. watch 無條件 connect，forbidden 時會對無權限的 session 進退避重連迴圈。

**`mount()` 無法重掛不在此列**——它與切換無關且現在就會踩到，由 WT-02 修掉。
