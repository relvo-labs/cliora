# 06 — P1-W6 Installer 與 artifacts

對應 `research/01/02-phase-1-node-control-plane.md` §P1-W6。涵蓋 ticket **P1-15**（artifacts + install）、**P1-16**（doctor + 安裝矩陣）。需求：FR-INSTALL-002/003、FR-CONN-002、SEC-007、NFR-004/005、tech §15、§23。

## 目標

讓管理員以一行指令在支援的 Linux 安裝 Daemon：腳本只做偵測/下載/驗 checksum/呼叫 `agentd install`，真正邏輯在 Go binary。安裝以非 root 指定使用者執行，config/credential `0600`，systemd 長期服務不得 root；`agentd doctor` 可離線診斷；在 Ubuntu 22.04/24.04、Debian 12（amd64/arm64）通過安裝、啟動、重啟、移除。

## P1-15：Artifacts、install 與 systemd

一行安裝（PRD §8.3 FR-INSTALL-002）：

```bash
curl -fsSL https://platform.example.com/install.sh | \
  sudo bash -s -- \
    --server https://platform.example.com \
    --token enroll_xxxxx \
    --name dev-vm-01 \
    --user neil
```

`install.sh`（tech §15.1）只負責：偵測發行版與 CPU 架構 → 由 `--server` 下載對應 `agentd` binary → 驗 SHA256 → 執行 `agentd install --server --token --user --name`。所有實質邏輯在 Go binary。

`agentd install` 步驟（FR-INSTALL-003、tech §15.2）：

- 安裝 binary 至 `/usr/local/bin/agentd`；建立 `/etc/agentd/`（`config.yaml`、`credentials.yaml`，`0600`）、`/var/lib/agentd/`、`/var/log/agentd/`（或 journald）。
- 以 enrollment token 呼叫 `POST /api/nodes/register`（見 03），取得 `node_id + private_key`，寫 `credentials.yaml`（`0600`）；明文 secret 不落 log。
- 產生 `config.yaml`（server url 轉 `wss://…/ws/nodes`、node name、runtime enabled/binary 偵測結果、workspace roots）。
- 建立 systemd unit（tech §8.1）並啟用開機啟動、啟動服務、驗證中央連線、回報安裝結果。

systemd unit 要點（tech §8.1）：`Type=simple`、`User=<--user>`/`Group=<--user>`、`ExecStart=/usr/local/bin/agentd run --config /etc/agentd/config.yaml`、`Restart=always`、`RestartSec=5`、`LimitNOFILE=65535`、`NoNewPrivileges=true`、`PrivateTmp=true`、`After/Wants=network-online.target`、`WantedBy=multi-user.target`。**不得** `PrivateHome=true`（會擋掉使用者 Home 內的 CLI 設定與 workspace）。安裝流程需明示該 Daemon 將具備該 Linux 使用者權限（SEC-007）。

Release artifacts（tech §15.3、§20.3，以 GoReleaser）：`agentd_<ver>_linux_amd64.tar.gz`、`agentd_<ver>_linux_arm64.tar.gz`、`checksums.txt`。`GET /api/downloads/{filename}` 提供 binary，`GET /api/install-script` 提供 `install.sh`；下載端一律附/對照 checksum。

規則：

- checksum 驗證在 install 與（P4 的）update 都是強制（SEC/tech §23 #12）；驗證失敗即中止、可診斷、不洩漏 token。
- 平台/架構不符（非 amd64/arm64、非支援發行版）給明確錯誤。
- 缺 tmux、無法連 endpoint、config 權限錯誤，安裝需可診斷且不洩漏 token。

驗收：install/uninstall 在乾淨環境可重現；config/credential 權限為 `0600`；unit 檔內容與上表一致且服務以指定使用者執行；checksum mismatch、錯架構、缺 tmux、連線失敗都有可診斷輸出且無 token 外洩。

## P1-16：`agentd doctor` 與安裝矩陣

`agentd doctor`（NFR-004、PRD §20.1）檢查並輸出結構化結果：網路可達 central、config 與 credential 檔權限（`0600`）、runtime 偵測（claude/codex 可執行與版本）、tmux 版本、allowed roots 存在且可讀、非 root 執行。doctor 不外洩 secret。

安裝矩陣（NFR-005）：在 Ubuntu 22.04、Ubuntu 24.04、Debian 12 的 amd64（必要時 arm64）測試環境，執行安裝 → 啟動 → 確認 outbound WSS 註冊成功並 heartbeat → systemd 重啟後自動重連重註冊 → `agentd doctor` 全綠 → 移除（uninstall）後無殘留檔案/unit/使用者資料外洩。

驗收（延續 research §P1-W6）：三發行版的安裝、啟動、重啟、移除流程通過；doctor 對正常與各故障情境（斷網、權限錯、缺 runtime、缺 tmux）回正確診斷；重啟後重連重註冊有證據；移除後 `/etc/agentd`、unit、開機啟動皆已清除。
