# 05 — P1-W5 Connection registry 與 Node 狀態

對應 `research/01/02-phase-1-node-control-plane.md` §P1-W5。涵蓋 ticket **P1-13**（registry 與 correlation）、**P1-14**（狀態計算與 disable）。需求：FR-NODE-002/005、FR-CONN-004/006、NFR-002、tech §7.2–7.4。

## 目標

Central 以記憶體 registry 維護活躍 daemon 連線與 request correlation，durable metadata 一律落 DB；Node 的 online/offline 狀態只由 Central 依 monotonic heartbeat timeout 判定，不信任 daemon 自報；node disable 立即禁止新操作，credential 撤銷立即斷線；所有相關行為可被測試證明並留 audit。

## P1-13：Connection registry 與 request correlation

沿用 P0 `ConnectionRegistry` 的「單一 owner + per-node send-lock」精神，擴充為多 node（tech §7.2）：

- registry 維護 `connections: dict[node_id, NodeConnection]`；`NodeConnection` 持有 `websocket`、`connected_at`、`last_heartbeat_at`（**monotonic** 取樣）、`pending_requests`、`send_lock`。多個 producer 對同一 socket 送訊息時，必須經 per-node `send_lock` 或單一 sender coroutine，避免併發 `send`。
- **durable vs socket**：node/runtime/workspace/audit 等 durable metadata 只經 repository 落 DB；活躍 socket 與 correlation entry 只存記憶體，不入 DB（tech §3.5）。`last_seen_at` 以 aware wall-clock 落 DB 供顯示；狀態判定另用 monotonic。
- **duplicate connection**：同一 node_id 第二條認證連線到達時，明確處置（沿用 P0 daemon gateway 以 close code evict 舊連線的模式，close `1012`），確保 registry 一個 node 只有一條活躍 socket，且無孤兒 pending request。
- **request correlation**（tech §7.3）：central 產生 `request_id`，`pending_requests[request_id]=Future`；daemon 以同 request_id + `success` 回應解 Future。必須處理 timeout（依 §7.3 表清 entry 回 `REQUEST_TIMEOUT`）、node disconnect（拒絕/取消所有 in-flight future）、duplicate response（忽略第二次）、unknown request ID（丟棄且記 warn）、daemon error response（傳回 typed code）。per-node pending 上限（初值 128）避免無界成長。
- late-response cleanup：逾時後才到的回應必須被安全丟棄，不得寫入已釋放的 future 或造成 leak。

驗收（延續 research §P1-W5）：duplicate connection、late response、timeout entry cleanup、node disconnect 清 in-flight、per-node bound、Central restart 後 registry 重建，皆有測試且 `go`/`pytest` 無 leak/pending task。

## P1-14：Node 狀態計算與 disable

狀態集合：`Online / Degraded / Offline / Disabled`（FR-NODE-002/005、tech §7.4）。

- **計算**：以「距最後 heartbeat 的 monotonic 間隔」判定 —— ≤30s Online、31–90s Degraded、>90s Offline；daemon WS 斷開可立即標為 Offline，但保留 `last_seen_at`。管理員停用（`is_enabled=false`）優先顯示 Disabled，與線上/離線正交（disabled 的 node 仍可能有活躍連線）。**狀態一律由 Central 計算，不採 daemon 自報**。
- **不信任自報**：daemon heartbeat 只提供「還活著 + 資源摘要」訊號；online/offline 邊界與 stale 判定在 Central，時鐘偏移不影響（用 monotonic 間隔而非比較兩端 wall-clock）。
- **node disable**（FR-NODE-005）：Admin 停用後，daemon 可保持連線，但 Central 立即拒絕新建立性操作（P2 的 session 建立回 `NODE_DISABLED`）；既有 session 是否中止由 Admin 選擇（P1 無 session，此選項為 P2 掛接點，先在 API 預留參數）；UI 顯示 Disabled。停用寫 `node.disable` audit。
- **credential 撤銷**（見 03）：撤銷後現行連線立即斷開、後續 Ed25519 認證被拒；此為比 disable 更強的動作。
- **node 移除＝軟刪除（已確認決策）**：Admin「移除 Node」不做破壞性 hard delete，而是設 `nodes.deleted_at`、撤銷其 `node_credentials`（斷線 + 拒後續認證）、自 registry 移除活躍連線，並保留該 node 及其 runtimes/workspace_roots/audit_logs 供稽核。三個動作語意由弱到強為：**disable**（`is_enabled=false`，保連線、禁新操作）→ **credential 撤銷**（斷線、拒認證，node 仍存在可重新 enroll）→ **remove**（軟刪除 + 撤銷 credential，node 自預設清單消失、`node_id` 不重用）。移除寫 `node.remove` audit（記 user、node_id、時間，不記 secret）。已軟刪除的 node 不可被 heartbeat/重連復活；同名/同 hostname 的機器需以新 enrollment 產生新 node_id。
- **狀態暴露**：node 列表/詳情 API 回傳「Central 計算後的狀態」+ `last_seen_at`（RFC 3339 UTC，前端本地化）；offline node 的詳情仍可讀最後已知 metadata；預設清單排除 `deleted_at` 非空的 node（可另以明確 filter 供稽核檢視）。

驗收（延續 research §P1-W5）：missing heartbeat 跨越 30s/90s 邊界的狀態轉換（以可注入的 fake monotonic clock）、disabled node 拒新操作但保連線、credential 撤銷即斷線、軟刪除後 node 自預設清單消失且無法以重連復活但 audit 仍在、Central restart 後依既有連線與 heartbeat 重建狀態，皆有測試；disable/credential 撤銷/remove 寫入正確且互相區分的 audit。
