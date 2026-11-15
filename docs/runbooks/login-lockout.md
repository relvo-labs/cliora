# 登入鎖定與解鎖（#59）

Central 登入失敗的帳號計數存於 PostgreSQL `login_lockouts`，包含不存在的帳號。
必須先執行 `alembic upgrade head`（`0023_login_lockout`）再啟動 Central。
此 revision 尚未合併，Delta 1 直接更新 0023 的內容，沒有新增 0024。
若測試環境曾套用舊 Draft schema，先停止 Central、回退至 0022，再升級至 head，
重新套用 0023；這會清除舊 Draft 的保護計數，保留使用者與其他權限。
帳號連續失敗第 5 次鎖 60 秒、第 10 次鎖 900 秒、第 20 次起每次鎖 3600 秒；
第 6–9、11–19 次不新增鎖期。鎖期內任何密碼均拒絕，且不執行 Argon2；
拒絕本身不增加帳號計數或延長鎖期。到期後才可再次驗證，成功即清空帳號計數。
同一帳號的併發登入在資料庫列鎖下依序處理，避免遺失計數或成功重設的競爭。

保護鍵是原始帳號 UTF-8 的 `SHA-256(username)`，與登入查找的精確比對一致。
大小寫或 Unicode 變體可代表不同帳號，各自累計失敗，彼此不清除計數。
不存在的帳號使用同樣的精確鍵與保護規則，仍執行 dummy verify；
已鎖定的已知／未知帳號都走相同的快速拒絕路徑。錯誤為
`LOGIN_THROTTLED` / HTTP 429，`Retry-After` 是向上取整的剩餘秒數。

IP 僅使用 ASGI 的 `request.client.host`；沒有 client 時共用 `unknown` bucket。
應用不解析 forwarding headers，可信代理設定由 EDGE lane 負責。
同一 IP 在滑動 600 秒內失敗 20 次，於第 20 次開始拒絕登入 600 秒；
帳號已鎖定的拒絕也計入 IP 失敗，IP 已封鎖的拒絕不延長期限。
IP 限制為單一 Central 行程的記憶體狀態，重新啟動即清空；帳號計數持續存在。
每個 IP 最多保留 20 個時間點，最多 10,000 個 IP，過期資料在下次操作時清理。
容量滿時，按最近一次失敗的時間，由最舊開始回收尚未達封鎖門檻的 probation entries；
不淘汰有效封鎖。全部名額都是有效封鎖時，新 IP 可繼續登入，但暫不追蹤其 IP 失敗。
單純因為容量滿不會回 429；未被追蹤的 IP 仍受帳號鎖定與 edge 限制。
成功登入只清帳號計數，不清 IP 失敗視窗。

`last_activity_at`（有時區、索引）記錄每次進入帳號保護流程的登入與手動解鎖，
包含已鎖帳號的拒絕。已被 IP 限制擋下的請求不建立帳號資料。
已知與未知帳號使用同一個 retention 規則：未鎖定或鎖期已結束，且閒置 **超過** 24 小時，
資料可刪除；恰好 24 小時仍保留。活躍鎖定不提前刪除，近期活動也不刪除。
因此在閒置 retention 後，過往的連續失敗會歸零，已知與未知帳號一致。
登入路徑最多每 60 秒執行一次清理，每批最多刪除 1,000 列，由最舊開始。
以 `FOR UPDATE SKIP LOCKED` 跳過進行中登入持有的列；刪除與登入的原子 upsert
共用列鎖，避免 cleanup 與重新活動競爭。清理與當次登入同交易提交；若回滾，
下一個 interval 再嘗試。單一行程在 await 前取得清理名額，避免併發啟動多批。
沒有登入流量時不執行清理；積壓可能需多批處理。這不是資料庫總列數的硬上限，
需依建立速率與 backlog 調整批量／頻率並觀察資料庫容量。

retention 新預設為工程提案：`login_lockout_idle_retention_seconds=86400`、
`login_lockout_cleanup_interval_seconds=60`、`login_lockout_cleanup_batch_size=1000`。
三者均可透過 `CLIORA_` 前綴調整，批量最高 10,000，須重新啟動 Central。

Argon2 hash、verify、dummy verify 共用行程級 semaphore，預設最多 4 個操作，
排隊最多 5 秒，超時統一回 HTTP 503 / `INTERNAL_ERROR`。
登入、管理員 bootstrap、隧道密碼雜湊皆在專用 worker threads 執行；
等待名額不阻塞事件迴圈。取消請求不會提前釋放仍在執行的工作名額。
`Settings` 的 `password_*`、`login_lockout_*`、`login_ip_*` 可調整（`CLIORA_` 前綴）；
併發與等待時間分別最高為 4 與 5 秒，調整後須重新啟動 Central。

持有 `user.unlock` 的 Admin 可呼叫：

```http
POST /api/auth/unlock
Authorization: Bearer <access token>
Content-Type: application/json

{"username":"account-name"}
```

成功回 204。Developer／Viewer 回 403。此操作也可清除未知帳號的保護鍵，
且不回報帳號是否存在。沒有使用者管理 UI；本次沒有新增 UI。
當所有管理員均被鎖定時，可於 backend 目錄執行：

```bash
python -m app.bootstrap unlock-user --username account-name
```

兩個入口均寫入 `user.unlocked` 稽核。API 記錄操作者 ID，CLI 記錄
`source=system`；僅記錄最多 64 字元的帳號，不含密碼或憑證。
解鎖不解除 IP 封鎖，也不變更密碼、停用狀態或 token。
`user.login_failed` 的 `reason=lockout_started` / `account_locked` 分別表示
鎖期開始／鎖期內拒絕；`ip_locked` 表示 IP 限制。

回退至 `0022_node_binary_preview` 會移除帳號計數及所有角色的 `user.unlock`
授權，保留使用者與其他權限；升級後計數由零開始。先備份並停止新版 Central，
避免舊 schema 與仍在執行的新版程式並存。IP 限制及 Argon2 限制不涵蓋 refresh
或 ws-ticket；edge 和 node WebSocket 限制由各自 lane 提供。
