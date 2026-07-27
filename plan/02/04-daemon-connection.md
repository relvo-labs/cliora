# 04 — P1-W4 Go Daemon 連線管理

對應 `research/01/02-phase-1-node-control-plane.md` §P1-W4。涵蓋 ticket **P1-10**（CLI/config）、**P1-11**（connection manager）、**P1-12**（runtime adapters）。需求：FR-INSTALL-004、FR-RUNTIME-001/003/004、FR-CONN-001/002/003/004、SEC-007、tech §5.3/§6.3/§8/§14.2。

## 目標

把 P0 的 env-only、單一 dev-node、fake-runtime daemon，升級為以 typed YAML config + 可撤銷 credential 運作的正式 daemon：cobra 子命令、outbound WSS + TLS 驗證 + Ed25519 認證、10s heartbeat、backoff+jitter、graceful shutdown，並偵測/回報 Claude/Codex allowlisted runtime。沿用 P0 已驗證的 reconnect/heartbeat loop（`[1s,2s,5s,10s,30s]`+≤250ms jitter）、`boundedWriter`（512 frame／4 MiB）、tmux/PTY session manager 與 `safe(err)` redaction。

## P1-10：CLI 與 config

以 cobra 建立子命令（PRD §8.3 FR-INSTALL-004）：

```text
agentd run --config /etc/agentd/config.yaml      systemd entrypoint（tech §8.1）
agentd install / uninstall                        見 06（installer）
agentd start / stop / status                      封裝 systemctl
agentd doctor                                     見 06（本機診斷）
agentd register                                   以 enrollment token 呼叫 HTTP register（見 03）
agentd config validate                            驗 config schema 與檔案權限
agentd runtime list                               列偵測到的 claude/codex 狀態
agentd workspace list                             列 allowed roots
agentd version                                    版本
agentd update                                     P1 保留 stub（更新流程屬 P4）
```

Config（`/etc/agentd/config.yaml`，PRD §13）以 typed struct + 明確驗證載入（koanf/viper），欄位：`server.url`(wss)、`node.name`、`runtime.{claude,codex}.{enabled,binary}`、`workspace.allowed_roots`、`workspace.excluded_patterns`、`filesystem.max_preview_size`、`session.backend: tmux`、`session.scrollback_limit`、`heartbeat.interval_seconds`。credential 分離於 `/etc/agentd/credentials.yaml`（`node_id`、`private_key`）。

規則：

- config 與 credentials 檔權限必須 `0600`；啟動時檢查權限、拒絕 group/other 可讀（tech §23 #13）。
- **non-root 檢查**：啟動偵測 `uid==0` 時以明確錯誤拒絕長期執行（SEC-007）；安裝以指定 dev user 執行。
- `config validate` 對缺欄位、非 wss URL、不存在的 binary path、非法 allowed root 給可診斷、不洩漏 secret 的錯誤。
- P0 的 env 變數（`CLIORA_CENTRAL_WS`、`CLIORA_P0_TOKEN` 等）僅保留於 P0 dev flow；正式 `run` 一律讀 config + credentials。

驗收：`config validate` 對合法/各類非法 config 有測試；權限與 non-root 檢查有測試；子命令 help/version 穩定；log 無 secret。

## P1-11：Connection manager 與認證

建立 `internal/connection`（client/reconnect/heartbeat/dispatcher）與 `internal/auth`：

- **outbound WSS**：dial `server.url`（`/ws/nodes/{node_id}`）。production 強制 `wss://` 並做標準 TLS 驗證（驗 CA、hostname）；`ws://` 只允許於明確 dev flag（ADR 0007）。TLS/handshake 失敗以 `safe(err)` 記錄，不外洩憑證細節。
- **Ed25519 認證**：連線後接收 Central nonce challenge，以 credential `private_key` 簽章（ADR 0008）；private_key 只存在記憶體與 `0600` 檔，永不進 log 或 query string。
- **單一 owner**：一 goroutine 擁 socket read、一 goroutine 擁 socket write；其他 producer（heartbeat、runtime status、session）只送 bounded channel（沿用 `boundedWriter`）。
- **heartbeat**：每 `heartbeat.interval_seconds`（預設 10s）送 `node.heartbeat`，payload `{daemon_version, active_sessions, resources:{cpu_usage, memory_usage, load_average?, disk_usage?, daemon_uptime?}}`（tech §18.2）；資源以 monotonic/週期取樣，不阻塞連線。
- **reconnect**：沿用 P0 backoff ladder + jitter，成功即重置；斷線後重連需**重新認證並重送 `node.register`**（NFR-002：Central 重啟後 daemon 重新註冊）。
- **graceful shutdown**：收到 SIGINT/SIGTERM 時，先送 `node.shutdown` deregister 通知（best-effort，有 timeout），取消 heartbeat/reconnect timer，等待 read/write goroutine 與 in-flight handler 結束；不 kill 既有 tmux session（沿用 P0：session 與連線生命週期分離）。

驗收（延續 research §P1-W4）：Central restart（daemon 自動重連並重註冊）、網路中斷、bad credential、撤銷 credential、TLS failure、nonce 過期/重放、shutdown 競態，皆有測試（含 `go test -race`）；log 掃描無 token/secret。

## P1-12：Runtime adapters（Claude/Codex）

建立 `internal/runtime`（tech §8.3–8.5）：

```go
type Runtime interface {
    ID() string                                   // "claude" | "codex"
    Detect(ctx context.Context) DetectResult      // available, version, binary_path, checked_at
    Validate(opts StartOptions) error
    BuildCommand(opts StartOptions) *exec.Cmd      // P2 才實際啟動；P1 只建構/驗證
}
type Registry struct { runtimes map[string]Runtime }  // 只註冊 claude/codex
```

規則：

- **allowlist**：只接受 runtime ID `claude`/`codex`（FR-RUNTIME-003、SEC-002）；前端/協定不得傳入任意 command、argv、binary path、shell、env。實際命令由 adapter 依 config `binary` 產生。
- **偵測**：啟動時對 enabled runtime 執行 `<binary> --version`（帶 timeout，避免阻塞啟動，tech §8.5），記錄 available、version、binary_path、run_user 可執行性、checked_at（FR-RUNTIME-001）。偵測不可掛住連線建立。
- **回報**：偵測結果以 `node.runtime_status` 上報 central 並落 `node_runtimes`；系統資訊以 `node.system_info`（OS/arch/kernel/run_user，`internal/systeminfo`）於註冊時上報。unavailable runtime 標示原因（`RUNTIME_NOT_FOUND`/`RUNTIME_DISABLED`/`RUNTIME_NOT_EXECUTABLE`）。
- **P1 範疇**：P1 只做偵測與回報，不實作 session 啟動（BuildCommand/tmux 整合的實際啟動屬 P2）；P0 的 `fake` runtime 保留於 dev/test，不出現在正式 registry。

驗收（延續 research §P1-W4）：runtime 偵測（存在/不存在/不可執行/停用）與 allowlist（拒絕非 claude/codex ID 與任意命令欄位）有 unit test；偵測 timeout 不阻塞連線有測試；`node.runtime_status`/`node.system_info` payload 通過 contract 驗證。
