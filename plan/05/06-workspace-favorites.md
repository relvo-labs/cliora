# 06 — Workspace 收藏與最近使用（FR-WORKSPACE-004/005）

涵蓋 ticket **P4-13**。對應 PRD FR-WORKSPACE-004（最近使用 Workspace）／FR-WORKSPACE-005（Workspace 收藏）與 PRD §12.8（`workspace_favorites` 表），以及 `research/01/06-requirement-traceability.md` §5（「Workspace favorites｜P3 前決定｜非核心安全路徑，可在 tree 完成後排入」）與 `docs/p3-report.md`「Deferred to P4」。

這是 **P4 唯一新增的資料面功能**。它被排在 P4 是因為它不觸及路徑安全核心，但它是 PRD §8.5 的功能需求，而 P4 是最後一個 phase——因此必須在此交付，或以明確的 release decision 記錄為不交付。

---

## 現況

- `node_workspace_roots` 表已存在（`path`／`display_name`／`is_enabled`，per-node），P2 用它做 Central 端的 workspace prefix 前置授權。
- `terminal_sessions` 已記錄每次 session 的 `workspace`（models.py:166）、`user_id`、`node_id`、`created_at`——**「最近使用 workspace」可完全從既有資料推導，不需新表**。
- **`workspace_favorites` 表不存在**（PRD §12.8 規劃過）。
- `NewSessionDialog.vue`（P2）是選 node/runtime/workspace 建立 session 的地方；P3 的 `FileTree` 已能在 session 內瀏覽該 workspace。
- daemon 端每次操作都經 `internal/workspace` 的 `os.Root` handle 重新 canonicalize（P3-03 gate），Central 端有 `_reject_rel_path` 與 workspace prefix 授權。

---

## 安全前提（不可協商）

**收藏與最近使用只是 Central 的 UX 捷徑，不是授權來源。**

- 從收藏/最近清單建立 session 時，走的是**完全相同**的既有路徑：Central 的 workspace prefix 授權 → daemon 的 `Guard`/`os.Root` 解析與 allowed-root containment 判定。收藏中的路徑**不會**被當成「已驗證過」而跳過任何檢查（對齊 `research/01/00` §5「任何檔案存取都重新 canonicalize，不信任前次 tree listing」的同一原則）。
- 收藏的 path 可能在之後失效（root 被移除、目錄被刪、node 被停用、path 落到 allowed root 之外）。UI 必須把這種項目顯示為**不可用並附原因**，而不是靜默失敗或讓使用者以為它還能用。
- 收藏是 **per-user**（不跨使用者共享），因此不會成為「A 使用者洩漏自己 workspace 路徑給 B」的通道。清單 API 只回當前使用者自己的收藏。
- **不新增任何 filesystem 操作**：這個 ticket 不讀 node 檔案系統，只讀寫 Central 的 metadata。

---

## 交付內容

### 1. Migration `0011`：`workspace_favorites`

| 欄位 | 說明 |
|---|---|
| `id` UUID PK | |
| `user_id` FK(→users, CASCADE) | per-user |
| `node_id` FK(→nodes, CASCADE) | 收藏綁 node（路徑只在該 node 上有意義） |
| `path` String(4096) | workspace 絕對路徑（與 `terminal_sessions.workspace`／`node_workspace_roots.path` 同語意） |
| `display_name` String(128) nullable | 使用者可命名 |
| `created_at` timestamptz | aware |
| Unique | `(user_id, node_id, path)` — 重複收藏為 idempotent |
| Index | `(user_id, created_at DESC)` |

附 upgrade→downgrade→upgrade 測試，以及「node 或 user 被刪除時 CASCADE 正確」的測試（node remove 是 soft delete，因此另需測試：soft-deleted node 的收藏不出現在清單中）。

### 2. API

| Endpoint | 授權 | 行為 |
|---|---|---|
| `GET /api/workspaces/favorites` | `session.create`（能建立 session 才需要收藏；Viewer 不需要）★ | 回當前使用者的收藏，過濾掉 node 已 soft-deleted/disabled 者或標記其為不可用；bounded（上限如 100） |
| `POST /api/workspaces/favorites` | `session.create` | body `{node_id, path, display_name?}`。**驗證**：node 存在且啟用；`path` 為絕對路徑、無 `..`、無控制字元、無 null byte；**必須落在該 node 的 `node_workspace_roots` 之一底下**（與 P2 建立 session 時的同一個 prefix 授權函式，不重寫）。重複則回既有項（idempotent，200 而非 409） |
| `DELETE /api/workspaces/favorites/{id}` | `session.create` + **owner**（只能刪自己的，經 `services/authz.py`） | 204；不存在或非自己的一律 404（不洩漏他人收藏是否存在） |
| `GET /api/workspaces/recent` | `session.create` | 由 `terminal_sessions` 推導：當前使用者最近 N 筆（預設 5，上限 20）distinct `(node_id, workspace)`，依最近一次 `created_at` 倒序；標註 node 目前是否 online/enabled。**無新表** |

★ **定案（ADR 0016）：`session.create`**。收藏/最近的用途是「建立 session 更快」，Viewer 無 `session.create` 因此不需要。若日後要擴及唯讀瀏覽便利性，改用 `file.browse` 並**在同一個變更內**加入 P4-03 的權限矩陣測試——不可由實作者自行改動。收藏為 **per-user + per-node**、unique `(user_id, node_id, path)`（重複收藏 idempotent）、`recent` 5 筆（上限 20，由 `terminal_sessions` 推導、無新表）、只有 owner 可刪（他人的一律 404）。

`services/favorites.py` 擁有邏輯（含 prefix 授權複用）；`repositories/favorites.py` 負責持久化。

### 3. Frontend

- `stores/favorites.ts`：收藏與最近清單、樂觀新增/移除 + 失敗回復、per-user 快取、登出清空。
- `components/session/NewSessionDialog.vue`（既有）擴充：選定 node 後，workspace 欄位上方顯示「最近使用」與「收藏」兩組快捷（各自可空 → 顯示 empty 提示），點選即填入 path；旁邊有收藏/取消收藏的切換。
- P3 的 `FileTreeToolbar`／session workspace header 可加「收藏此 workspace」（同一 store）。
- **不可用項目的呈現**：node offline → 可見但標「Node 離線，無法建立 session」（沿用 FR-NODE-002 與 PRD §19 條目 18 的規則：offline 不可建 session）；node disabled/removed → 不顯示或標「不可用」；path 已不在 allowed root → 建立時由 server 回既有的 `WORKSPACE_OUTSIDE_ALLOWED_ROOT`/`WORKSPACE_NOT_FOUND`，UI 顯示原因 + 「移除此收藏」的下一步。
- 狀態矩陣：`loading`／`success`／`empty`（「還沒有收藏」+ 說明如何收藏）／`error`（可重試）／`forbidden`（無 `session.create` 時整區不顯示，且 server 端 403 有測試）。
- a11y：快捷清單為可鍵盤導覽的 list（非僅 hover 可見的按鈕）；收藏切換有 `aria-pressed` 與可讀標籤；移除有確認或可復原提示。

### 4. 測試

- **Backend**：
  - prefix 授權：收藏一個不在任何 allowed root 底下的 path → 422/403 且**不寫入**；收藏 `..`／相對路徑／null byte／控制字元 → 422。
  - owner：使用者 A 無法刪除 B 的收藏（404）；`GET` 只回自己的。
  - idempotency：重複 POST 不產生第二筆。
  - soft-deleted/disabled node 的收藏行為（過濾或標記，依 ADR）。
  - `recent`：distinct 與排序正確、bounded、不含他人 session、已終止的 session 仍計入（「最近使用」是歷史而非現況）。
  - RBAC 矩陣（併入 P4-03 的窮舉矩陣，新增 route 必須出現在矩陣中，否則測試失敗）。
  - migration up/down/up + CASCADE。
- **Frontend**：store 的樂觀更新與回復、五種狀態渲染、鍵盤流程、offline node 的呈現。
- **E2E（併入 P4-15）**：建立一個 session（產生 recent）→ 回到 New Session 對話框看到 recent → 收藏它 → 重新載入頁面後收藏仍在 → 用收藏快捷建立第二個 session → 停用該 node 後收藏顯示不可用 → 移除收藏。

---

## 若不交付的處置

若 P4 的時程壓力導致此 ticket 無法完成，**不得默默省略**（FR-WORKSPACE-004/005 是 PRD §8.5 的功能需求）。處置方式：在 `docs/p4-report.md` 與 `research/01/06-requirement-traceability.md` §10 明確記錄「FR-WORKSPACE-004/005 未交付」、影響（使用者每次建立 session 需重新輸入或從 tree 選取 workspace，功能可用但便利性不足）、以及這是否構成 MVP 阻擋（PRD §19 的 20 項驗收條件**不包含**收藏或最近使用，因此不阻擋發布——這是可接受的 release decision，但必須被寫下來而非被遺忘）。

**對應需求**：FR-WORKSPACE-004、FR-WORKSPACE-005、PRD §12.8、SEC-001（收藏不繞過路徑驗證）、FR-NODE-002（offline 不可建 session）。
