# 03 — Dashboard、原型退場與 Error Management（P4-W3）

涵蓋 ticket **P4-06**（aggregates API + freshness 契約）、**P4-07**（原型退場與 error management）與 **P4-08**（Dashboard UI）。對應 `research/01/05` §P4-W3、`research/01/00` §2（原型盤點與處置）、PRD §10.2、style §10/§23、tech §18.1。

---

## P4-06：Aggregates API 與 freshness 契約

### 現況

沒有任何 aggregates 端點。可用的資料來源都已存在：`nodes` 表（`status`／`is_enabled`／`deleted_at`／`last_seen_at`／`daemon_version`）、`node_runtimes`（`available`／`version`）、`terminal_sessions`（`status`／`runtime`／`node_id`／`user_id`／`created_at`／`ended_at`）、`audit_logs`（recent activity）、以及 `NodeConnectionRegistry`（`connection_count()`、`is_connected()`、`seconds_since_heartbeat()`、`resources_for()`——**全部只在 process 記憶體**）。`compute_status()`（`services/registry.py:240`）已是 online/degraded/offline 的唯一判定處，Dashboard 必須沿用它而非另寫一套。

**關鍵設計約束**：`registry` 的資料是**當前 process 的即時狀態**，DB 的 `nodes.status` 是**最後一次寫入的快照**。兩者可能不一致（例如 Central 剛重啟，daemon 還沒重連）。Dashboard **不得把 DB 快照當成即時狀態呈現**——這正是 research「stale/partial 指標必須標示 freshness，不偽裝即時資料」的具體含義。

### 端點

`GET /api/dashboard/summary`（`require_action(NODE_VIEW)`——所有角色可見，內容依角色調整）：

```
{
  "generated_at": "<RFC3339 Z>",
  "blocks": {
    "nodes":            {"status":"ok|stale|degraded", "generated_at":..., "data":{...}},
    "sessions":         {...},
    "runtimes":         {...},
    "resources":        {...},
    "recent_activity":  {...},
    "unhealthy_nodes":  {...}
  }
}
```

**每個 block 獨立**：由 `services/dashboard.py` 內各自的取數函式擁有，任一函式拋錯只讓該 block 變 `degraded`（`data: null` + `error_code`），**不讓整個回應失敗**。這是 research「partial backend failure E2E 通過」的實作前提。

| Block | 內容 | 來源與 freshness 規則 |
|---|---|---|
| `nodes` | `online`／`degraded`／`offline`／`disabled`／`total` | 以 `nodes` 表 + `registry`/`compute_status()` 重新計算；`status:"stale"` 當 registry 顯示的最後 heartbeat 超過 §6 門檻（30 s），或 Central uptime < heartbeat interval（剛重啟，狀態尚未收斂） |
| `sessions` | `running`／`starting`／`stopping`／`total_active`；per-runtime（`claude`／`codex`／`fake`）計數 | `terminal_sessions` 聚合查詢（`status IN ACTIVE_STATES`）；PRD §10.2 要求 Claude/Codex sessions 分列 |
| `runtimes` | 每個 runtime 在多少 node 上可用／不可用／未知 | `node_runtimes` join `nodes`（排除 disabled/deleted）；`checked_at` 過舊即標 stale |
| `resources` | fleet 層級的 CPU／memory／disk／load 概況（平均 + 最高 + 有樣本的 node 數） | `node_metric_samples`（P4-06 新建表）最近一個取樣窗；**沒有樣本時回 empty 而非 0** |
| `recent_activity` | 最近 20 筆 audit 的安全欄位（time／action／actor／resource） | `audit_logs`；**只取安全欄位，不含 metadata 全文**；需 `audit.view` 才顯示 actor 細節，否則只顯示 action 與時間（角色差異） |
| `unhealthy_nodes` | 異常 Node 清單（bounded，如 10 筆）＋原因 | 判定：`offline` 且 `is_enabled`、或 `degraded`、或所有 runtime 皆不可用、或最近有 `session.failed`；每筆帶 `reason` code |

- **快取**：process 內 5 s TTL（§6）。快取命中時 `generated_at` 是**取數時間**而非請求時間——這是 freshness 契約的核心，不得回填為 `now()`。
- **空部署**：所有 block 回合法的空值（`total: 0`、`items: []`）並讓 UI 顯示 empty 狀態與「安裝第一個 Node」的下一步，**不回 404、不回 null 讓前端崩**。
- **角色差異**：`recent_activity` 的 actor 細節與 `unhealthy_nodes` 的 node 名稱依權限調整；測試必須覆蓋三角色各自看到的內容。

### `node_metric_samples` 表（migration `0010`）

| 欄位 | 說明 |
|---|---|
| `id` UUID PK、`node_id` FK(→nodes, CASCADE)、`sampled_at` timestamptz | 取樣時間（aware） |
| `cpu_usage`／`memory_usage`／`load_average`／`disk_usage`／`daemon_uptime` | 全部 nullable（daemon 端 best-effort，`systeminfo/resources.go` 已是每欄位獨立 nullable） |
| `active_sessions` int | 來自 heartbeat payload |
| 索引 | `(node_id, sampled_at DESC)`；retention 清理用 `sampled_at` |

寫入點：`app/api/ws/nodes.py` 處理 `node.heartbeat` 時（現行 line 198 附近），**降頻**至每 node 每 60 s 一筆（以記憶體中的 last-persisted monotonic 時間判斷，不查 DB）。寫入失敗只記 `metric_persist_error_total` 並繼續——heartbeat 處理路徑絕不能因為 metrics 寫入而失敗或變慢。

**為何需要這張表**：Dashboard 的 `resources` block 與 runbook 的事後診斷都需要「不只是當前值」的資料；且 Central 重啟後 registry 記憶體清空，沒有持久化就完全無法回答「這個 node 昨天是否一直健康」。retention 30 天（§6），清理走 P4-04 的 `prune-retention` 程序。

### 測試（P4-06）

- 每個 block 的正常值、空部署、以及**單一 block 取數失敗 → 該 block `degraded` 且其他 block 正常**（以 monkeypatch 讓某函式拋錯）。
- freshness：偽造「registry 無連線但 DB 顯示 online」→ `nodes` block 為 `stale`；偽造 heartbeat 超時 → 正確降級。
- 快取：連續兩次請求只取數一次；`generated_at` 為取數時間（fake clock）。
- 三角色的內容差異。
- `node_metric_samples`：降頻正確（60 s 內多次 heartbeat 只寫一筆，fake clock）、寫入失敗不影響 heartbeat、migration up/down/up。

---

## P4-07：原型退場與 Error Management

research/01/00 §2 明確列出必須處置的原型殘留，且 §P4-W3 驗收條件包含「確認所有原型硬編碼值、token、版本、日期已移除」。以下是實際盤點結果與處置。

### 1. `frontend/src/styles.css`（1326 行，由 `main.ts` 全域 import）

| 問題 | 處置 |
|---|---|
| 第 1 行 `@import url("https://fonts.googleapis.com/css2?family=Inter…")` — **production bundle 對外連 CDN**，與 P3「Monaco 必須自帶 worker、`dist` 不得有 CDN 參照」的規則直接矛盾，也讓離線/內網部署字型失效 | 移除。**定案（ADR 0016）**：改用系統字型堆疊 `system-ui, -apple-system, "Segoe UI", Roboto, "Noto Sans TC", sans-serif`，MVP 不自帶 woff2 subset（零 bundle 成本、目標平台已有足夠拉丁與繁中字型覆蓋，且為 ADR 0017 的 CSP 前置條件）。建置後以 grep 斷言 `dist` 無 `fonts.googleapis.com` |
| `body{min-width:1180px}` — research §2 要求「重新設計，依 style responsive 規則處理 overflow/收合」 | 移除。style §24 定義桌機 only、最低 1440×900；改由各 view 自行處理較窄視窗的 overflow（表格橫向捲動、側欄收合已在 `AppLayout` 的 900px breakpoint 實作），不用全域 min-width 逼出頁面級橫向捲動 |
| 硬編碼色值（`#1a1f24`、`#f4f6f8`、`--side`／`--top`／`--border`／`--muted` 等自成一套變數）與 `theme/tokens.css` 的 semantic token 重複且不一致 | 刪除重複定義；統一使用 `theme/tokens.css`。`tokens.css` 已有 `--surface-*`／`--text-*`／`--border-*`／`--action-*`／`--status-*`／`--layout-*`／`--radius-*` |
| 死 class：`.metrics`／`.dashgrid`／`.nodecard`／`.timeline`／`.sidefoot`／`.side nav`／`.system`／`.account`／`.bar`（grep 確認 production views 完全未使用） | 刪除。**注意**：`.metrics`／`.dashgrid`／`.timeline` 是原型 Dashboard 的樣式，P4-08 將以 scoped style + token 重新實作，**不得複製原型 CSS** |
| **仍被使用**的 class：`.primary`（5 個檔）、`.danger`（3 個）、`.head`（6 個）、`.panel`（2 個）、`.ghost` | 遷移為共用元件或 scoped style：新增 `components/common/{PageHeader,Panel}.vue` 與按鈕樣式（優先用 Naive UI `n-button` 的 type，若既有視覺已定案則保留自訂但改為 scoped + token）。**逐檔遷移 + 每檔視覺回歸截圖**，避免一次大改造成 UI 迴歸 |

處置後 `main.ts` 只 import `@xterm/xterm/css/xterm.css` 與 `theme/tokens.css`（+ 一個精簡的 `theme/base.css` 放 reset 與 element 預設）。`format:check` 的 prettier 排除清單（目前排除 `src/App.vue`、`src/styles.css`）隨之移除——**原型檔退場後不應再有格式豁免**。

### 2. 其他原型殘留

| 項目 | 現況 | 處置 |
|---|---|---|
| `components/common/AppShell.vue` | 164 行，`@deprecated`，註解指向**已不存在的 `P0App.vue``，grep 確認零使用；nav 指向 `/poc/*`，含硬編碼 "P0 · Local development" 與 "Cliora v0.1 P0" | 刪除 |
| `views/TokenShowcaseView.vue` + dev-only `/poc/tokens` 路由 | 設計參考頁，含 `class="primary"`／`class="danger"` | **定案（ADR 0016）：保留**為 dev-only 設計參考（維持既有 `import.meta.env.DEV` 路由），但以 `dist` grep 斷言 production bundle 不含它。它是唯一能一頁看完 token 系統的地方，成本為零 |
| `frontend/package.json` `"name": "cliora-console-prototype"` | 原型命名 | 改為 `cliora-console` |
| `index.html` `<title>Cliora — Node control plane</title>` | 硬編碼產品名與副標；`AppLayout` 已用 `VITE_PRODUCT_NAME` | 改為可設定（build 時注入或以 router meta 設定 document.title），與 `AppLayout` 的 `productName` 同一來源 |
| **P0 dev relay**：`app/main.py` 的 `/ws/p0/daemon`、`/ws/p0/sessions/{id}/terminal`、`authorized()`（共用靜態 `p0_token`）、`app/relay/{queue,registry}.py`、`Settings.p0_enabled`／`p0_token`／`node_id`、`Makefile` 的 `dev-central`／`dev-daemon`、`daemon/cmd/agentd/p0.go` | P2 relay 已完全取代；以 `environment=="production"` 驗證器 fail-closed（ADR 0006） | **退場**（ADR 0016 定案，已列於 `00-execution-plan.md` §7）。移除路由、relay 套件、設定與 dev 指令；`.github/workflows/p0.yml` 一併處理（保留其 contract 部分或合併進 p4）。`docs/adr/0006` 標記 superseded-by 0016。**理由**：它是唯一以共用靜態 token 授權的 WS 端點，且 `app/relay/*` 的 `BrowserChannel` 已被 `services/terminal_relay.py` 取代——留著是一條無人維護的授權旁路。移除後 `dev-central`／`dev-daemon` 改為指向真實 enrollment 流程（`scripts/e2e/run-stack.sh` 已能 rootless 起全棧，可直接沿用） |
| `backend/dist/` 內有 `cliora_central_p0-0.1.0*` 建置產物，`.gitignore` 只忽略 `frontend/dist/` | build 產物與 **P0 命名**的 wheel 留在工作目錄 | `.gitignore` 補 `backend/dist/`；`pyproject.toml` 的 package name 若仍為 `cliora-central-p0` 一併更名（與 `package.json` 更名同一批） |

**驗收方式**：production build 後對 `dist` 做 grep 斷言——無 `fonts.googleapis.com`／`unpkg`／`jsdelivr`／`cdn.`、無 `P0`／`poc`、無硬編碼 token 樣式字串、無原型 node/session 假資料、無硬編碼版本或日期。這條 grep 進 `p4.yml` 與 `scripts/p4/evidence.sh`。

### 3. Error Management

research 要求「建立 node/session/error detail 與可行建議；不把 daemon internal error 原樣暴露」。

- **映射表**：建立 `docs/error-catalog.md`（由測試斷言與程式碼的 code 集合一致），對每個 stable error code 列出：HTTP status／使用者可見 message／UI 顯示的「原因 + 下一步」／是否可重試／是否記 audit。涵蓋 `NODE_OFFLINE`／`NODE_DISABLED`／`NODE_BUSY`／`RUNTIME_*`／`WORKSPACE_*`／`FILE_*`／`SESSION_*`／`TERMINAL_ALREADY_CONTROLLED`／`REQUEST_TIMEOUT`／`FRAME_TOO_LARGE`／`UPDATE_*`／`FORBIDDEN`／`UNAUTHENTICATED`／`INTERNAL_ERROR`。
- **daemon internal error 不外流**：`services/*` 在收到 daemon 的 error frame 時，只轉換為對應的 stable code + catalog 中的 safe message；原始 message 進 log（帶 `request_id`）不進 HTTP body。以測試斷言「daemon 回一個含絕對路徑/內部字串的 error → HTTP body 不含該字串」（P3 已對 filesystem 做過，本期擴及 session/node/update）。
- **UI**：`components/common/AsyncState.vue` 已存在，擴充為「code → 建議文案」的一致呈現；每個 error 顯示 `request_id` 供回報。`INTERNAL_ERROR` 一律顯示通用訊息 + request_id。
- **測試**：catalog 與程式碼 code 集合一致（自動化）；每個 code 的 UI 呈現有 unit test；leakage 測試如上。

### 測試（P4-07）

```
cd frontend && npm run build && npm run test:unit -- --run
grep -RniE 'fonts\.googleapis|unpkg|jsdelivr|cdn\.' frontend/dist && exit 1 || true
grep -RniE '/ws/p0|p0_token|cliora-p0-dev' backend/app frontend/src && exit 1 || true
uv run --project backend pytest backend/tests -q          # 移除 relay 後全綠
make check
```

視覺回歸：對每個遷移的 view 前後截圖比對（`artifacts/p4/<run>/screenshots/prototype-retirement/`）。

---

## P4-08：Dashboard UI

### 路由與導覽

- 新增 `views/DashboardView.vue`、`stores/dashboard.ts`、`components/dashboard/{MetricCard,HealthCard,ActivityTimeline,NodeSummary,UnhealthyNodeList,FreshnessBadge}.vue`。
- `router/index.ts`：新增 `/dashboard`，並把 `/` 的 redirect 由 `nodes` 改為 `dashboard`；`AppLayout` nav 新增 Dashboard（第一項）與（`audit.view` 時）Audit。
- 設計依 style §10（Metric Card：Icon + Title + Big Number + Trend）、§23（Metric Card／Health Card／Activity Timeline／Node Summary）與 §3 status color；**狀態不可只靠顏色**（每個狀態都要有文字或形狀標示，沿用 P3 `StatusBadge` 的做法）。

### 呈現內容（PRD §10.2）

Online Nodes、Offline Nodes、Running Sessions、Claude Sessions、Codex Sessions、最近活動、異常 Node。加上 fleet 資源概況（style §10 的 CPU/Memory/Storage）。

### Freshness 呈現（本 ticket 的核心）

- 每個卡片顯示資料的 `generated_at`（本地時區相對時間，如「12 秒前」+ hover 顯示絕對時間）。
- `status:"stale"` → 卡片顯示明確的 stale 標示（文字 + icon，非僅變色）與「重新載入」；**數字仍顯示但明確標記為可能過時**。
- `status:"degraded"` → 該卡片顯示「暫時無法取得」+ 原因 code + 重試，**其他卡片正常顯示**。這是 research「partial backend failure E2E」的畫面契約。
- 整頁沒有「假的即時感」：不做無資料時的骨架動畫假裝載入中、不把 0 與「未知」混為一談（`resources` 無樣本時顯示「尚無資料」而非 0%）。

### 狀態矩陣（全部必測）

`idle`／`loading`（骨架）／`success`／`empty`（**空部署**：沒有任何 node → 顯示「安裝第一個 Node」與 enrollment 連結，Admin 才顯示該連結）／`stale`／`partial`（部分 block degraded）／`offline`（**offline fleet**：全部 node 離線 → 明確說明所有 node 皆離線與 runbook 提示）／`forbidden`（角色不足的 block 隱藏或顯示「需要權限」）／`error`（整體請求失敗 + `request_id` + 重試）。

### a11y 與互動

- 自動刷新：預設 **不自動輪詢**（避免偽即時）；提供明確的「重新整理」與可選的 30 s 自動刷新開關（狀態記在 store，切頁保留）；`prefers-reduced-motion` 時停用任何動畫。
- 鍵盤：卡片內連結可 tab、異常 Node 清單可鍵盤導覽並 Enter 進入 node detail；`aria-live="polite"` 播報刷新完成與 stale 轉換。
- 每個卡片的大數字要有可讀的 accessible name（例如 `aria-label="Online nodes: 12"`），不只依賴視覺排版。

### 測試（P4-08）

- **Unit**：`stores/dashboard.ts`（取數、5 s 快取行為、in-flight abort、切頁清理）；`DashboardView` 的九個狀態渲染；`FreshnessBadge` 的相對時間與時區；三角色的內容差異；`prefers-reduced-motion` 下無動畫。
- **E2E（併入 P4-15）**：Admin 登入 → dashboard 顯示真實 node/session 數字（對照 API）→ 停掉 daemon 後數字降級並顯示 stale/offline → 讓某 block 失敗（以測試用注入或 DB 權限）→ 顯示 partial 而非整頁錯誤 → 空部署情境（乾淨 DB）→ Viewer 登入看到受限內容 → 鍵盤走查 → 時區顯示正確（以固定 TZ 執行）。

**對應需求**：PRD §10.2、FR-NODE-002/003、FR-SESSION-003、style §10/§23/§24、research/01/00 §2 與 §5（UI 狀態契約）。
