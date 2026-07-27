# 05 — P0-W5 重新連線與 Backpressure

## P0-13：refresh 與 reattach

Browser transport 中斷不得送 `session.stop`，daemon transport 中斷不得 kill tmux。重新連線流程：

1. Frontend 狀態依序 `connected → reconnecting`，使用 1s、2s、5s、10s、30s bounded schedule；每次成功後 reset。
2. 手動 Retry 取消現有 timer並立即開始一次；route leave/dispose 可中止等待。
3. browser 重新送 `session.attach` 與 fit 後 rows/columns。
4. daemon 確認 tmux 存在，先以 `capture-pane` 取得最多 2 MiB 的最新 snapshot，再建立 live PTY attach。
5. Central 先送 `session.attached {snapshot_bytes, truncated, continuity:"snapshot"}` control metadata，再送 snapshot binary，最後轉 live output。

為避免 snapshot/live race，daemon session owner 在 attach 切換期間序列化 capture 與 live subscription；若無法證明無縫，不假裝 exact replay，必須送 `terminal.gap {reason:"reattach_boundary"}`。P0 不保存 terminal raw bytes於 Central。

## P0-14：burst 與 slow consumer

實作 byte-aware bounded queue，不只限制 channel item 數：

- enqueue 前以 payload length 原子計帳；dequeue/drop/close 必定歸還。
- control queue 獨立且小（64 frames），terminal queue 採 `00-execution-plan.md` 限制。
- queue overflow 不 block upstream PTY reader；該 consumer 進入 gap/close 流程。
- 多 consumer fan-out 時，一個 slow consumer 不持有全域 lock，也不阻塞其他 consumer。
- close 與 enqueue race 不 panic；關閉後所有已計帳 bytes 歸零。

Metrics：`terminal_queue_bytes`、`terminal_queue_frames`、`terminal_queue_overflow_total`、`terminal_gap_total`、`terminal_reconnect_total`、`terminal_snapshot_bytes`。P0 可先以 in-process metrics endpoint/test collector 暴露，但 label 不含 user input 或高 cardinality request ID。

測試矩陣：

| 情境 | 注入 | 斷言 |
|---|---|---|
| output burst | Fake CLI 16 MiB 固定輸出 | RSS/queue 不越設定界線加固定 overhead；CLI/tmux 存活 |
| slow browser | sender 暫停讀取 | 只有該連線 gap/close，queue bytes 歸零 |
| daemon queue full | Central 暫停讀取 | attach stream cancel，tmux/Fake CLI 存活，可再 attach |
| rapid reconnect | 連續斷線 20 次 | 不重複訂閱，無 goroutine/task/timer leak |
| snapshot oversize | scrollback >2 MiB | 僅最新 bounded snapshot，`truncated=true` |
| malformed flood | invalid frames | bounded CPU/memory，安全 close，不寫 payload log |

RSS 門檻須在測試前後取 baseline；若 CI 雜訊使絕對 RSS 不穩，至少以 queue accounting + heap/profile artifact 證明 bounded，並在 ADR 記錄方法。

## P0-15：restart spikes

### Central restart

操作：session running 時重啟 Central，daemon 與 browser自動重連，再 attach。預期 tmux/Fake CLI 不受影響。因 P0 registry 非 durable，browser需以已知 session UUID 重建 context；這是 P0 限制，不新增 DB。

### Daemon restart

操作：session running 時正常停止/重啟 daemon。預期 tmux仍存在；daemon 掃描嚴格 `cliora-<UUID>` sessions，回報可恢復項目，browser reattach。P0 metadata只有 runtime=fake與固定 workspace，不能據此推廣到 P2；需記錄未來 local metadata/reconciliation需求。

每個 spike 產出 `docs/adr/0004-p0-recovery-strategy.md`：實際命令、timeline、observed gap、殘留資源、選定策略、棄用方案與 P2 follow-up。若 daemon crash 會終止 tmux或無法安全辨識 session，P0 exit 失敗。

## 驗收

- [ ] browser refresh、Central restart、Daemon restart 三條旅程均有自動化或可重現 harness。
- [ ] gap/truncated 在 protocol 與 UI 都可見。
- [ ] retry schedule 以 fake clock 測試，不以真正 sleep 拉長 suite。
- [ ] burst/slow test 產生 queue/heap 證據，沒有 unbounded growth。
- [ ] 所有 disconnect path 保留 tmux；只有明確 stop 才終止 session。
