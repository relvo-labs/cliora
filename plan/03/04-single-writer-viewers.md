# 04 — P2-W4：Single Writer / Viewers 與 Takeover

對應 `research/01/03-phase-2-session-terminal.md` §P2-W4。涵蓋 ticket **P2-10**。需求：FR-SESSION-007、FR-TERM-002、SEC-002/006、PRD §8.6。前置：P2-09（relay）、P2-04（`session_connections` + RBAC action）。

## 目標

同一 session 任一時刻只有一個可寫入連線（writer），其餘為唯讀 viewer；writer 斷線有明確保留、釋放與接管流程；takeover 需 resource RBAC、顯式確認、通知現任並記 audit；**即使前端偽造 input frame，server 端也一律拒絕非 writer 的輸入**。這道 server-side 授權是安全邊界，不可用 UI 隱藏取代（沿用 traceability §5 決策：owner 為 writer、viewer 不可輸入、顯式授權才接管）。

## 決策依據（P2-02 定稿）

- **預設 writer**：session 建立者（owner）在其連線 attach 時取得 writer；同時只允許一個 writer。
- **writer 保留窗**：writer 連線中斷後保留 writer 身分一段 monotonic 窗（初值 30s），窗內同一 user 重連可無縫恢復 writer；逾時釋放，session 進入無 writer 狀態，可被授權者接管。
- **takeover policy**：具 `terminal.takeover` 的使用者可請求接管；MVP 採「顯式接管」——請求 → server 檢查 RBAC → 通知現任 writer（若在線）→ 轉移 writer 標記 → 記 audit。是否需要現任同意或僅 admin override 由 ADR 記錄（預設：具 takeover 權即可接管並通知，不需現任同意）。

## 實作（P2-10）

**Server 端 writer 標記（單一事實來源）**：於 terminal relay 的 per-session 狀態（`app/api/ws/terminal.py` + session 訂閱 owner）維護 `writer_connection_id`；`session_connections` 記錄每條連線的 `role`（writer/viewer）、`connected_at`、`last_seen_at`、`closed_at`、`close_reason`（P2-04 表）。

**輸入授權**：browser→Central 的 input binary frame 與 `terminal.control_acquire` 只有當來源連線 == 當前 writer 才轉往 daemon；viewer（或身分不符）送來的 input frame **靜默丟棄並記一次 rate-limited 安全事件**，不轉 daemon、不影響其他連線。`terminal.resize` 是否僅限 writer 由 ADR 記錄（預設：僅 writer 可 resize，避免 viewer 影響 PTY 尺寸）。

**writer 生命週期**：

- writer attach → 設 `writer_connection_id`，廣播 role 狀態給該 session 所有連線。
- writer 連線斷 → 啟動保留窗 timer（monotonic）；窗內同 user 重連恢復；逾時釋放並廣播「無 writer」。
- takeover：`terminal.control_acquire`（具 `terminal.takeover`）→ 轉移 writer、`terminal.control_release` 給舊 writer、通知現任、audit（見 `07`）。
- session 終止/exit → 清理所有連線的 writer/viewer 標記。

**通知**：writer 轉移、被接管、保留窗釋放皆以 control frame（或既有 status 廣播）通知該 session 連線，供前端更新角色顯示（P2-14）。

## 驗收

（`backend/tests`，`FakeWebSocket` 多連線；含 fake clock 測保留窗）：

- concurrent clients：先到者為 writer，後到者為 viewer；同時只有一個 writer。
- **viewer 偽造 input frame → server 丟棄、不到 daemon**；偽造 `control_acquire` 無 takeover 權 → 拒絕（`TERMINAL_ALREADY_CONTROLLED`/`FORBIDDEN`）。
- stolen/expired browser ws-ticket → handshake 階段即拒（P2-09），不進入 writer 判定。
- writer disconnect → 保留窗內同 user 恢復 writer；逾時釋放並可被接管。
- takeover race：兩個授權者同時請求，只有一個成功，另一個得到明確結果；現任被通知；每次接管恰產生一筆 audit。
- session exit/terminate 後所有 writer/viewer 標記與訂閱清空、無 leak。
