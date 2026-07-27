# 05 — Daemon Release 與安全更新（P4-W5）

涵蓋 ticket **P4-10**。對應 `research/01/05` §P4-W5、PRD FR-INSTALL-004/005、SEC-002/003/007、tech §15.3/§15.4/§23（#2、#12、#13）、ADR 0011（`agentd update` 明確延後至 P4）。

---

## 現況

- **`agentd update` 是 stub**：`daemon/cmd/agentd/service.go:137`，只印「not available in P1 (auto-update is deferred to P4)」。`deploy/README.md` 的 lifecycle 表同樣標為 stub。
- **Artifacts 管線已可用**：`daemon/.goreleaser.yaml` 產出 `agentd_<ver>_linux_{amd64,arm64}.tar.gz` + `checksums.txt`（sha256），`release.disable: true`（尚未由 tag 觸發發布）。`Makefile` 有 `release`／`release-snapshot`。
- **Central 已能提供 artifacts**：`app/api/http/downloads.py` 以**封閉 allowlist regex**（`agentd_<ver>_linux_(amd64|arm64)\.tar\.gz` 或 `checksums.txt`）+ 解析後 containment 檢查提供 `GET /api/downloads/{filename}` 與 `GET /api/install-script`，由 `Settings.artifacts_dir` 指向目錄，空值時回 404。**沒有 version/release manifest 端點**。
- **安裝端已成熟**：`deploy/install.sh`（偵測 distro/arch → 下載 → **驗 SHA256** → 交給 `agentd install`）、`daemon/internal/install/{plan,register,systemd,verify}.go`（config/credentials 0600、systemd unit `User=`/`NoNewPrivileges`/`PrivateTmp`、non-root、verify 連線）。P3 的 exit gate 已在此發現並修掉「installer 未寫出敏感檔政策」的缺口，說明這條路徑有實測覆蓋。
- **Protocol**：`daemon.version`／`daemon.doctor`／`daemon.doctor_result` 已在 allowlist；`daemon.update`／`daemon.update_result` 由 P4-02 新增。
- **tmux 與 daemon 程序分離**：P2 的 session 由 tmux server 持有（`internal/tmux`），daemon 只 attach PTY；ADR 0012 定義了 recovery/attach 模型與 `recovery_test.go`（live-orphan 驅逐、rapid reattach ×20、post-recovery stop）。**這是「升級期間 session 續存」得以成立的既有基礎**，P4 需明確驗證而非重新設計。

---

## 交付內容

### 1. Release manifest 端點（Central）

`GET /api/releases/manifest`（**公開**，與 `/api/downloads` 一致的理由：daemon 在持有 credential 之前就需要它；且內容不含機密）：

```json
{
  "latest": "1.0.0",
  "artifacts": [
    {"version":"1.0.0","architecture":"amd64","filename":"agentd_1.0.0_linux_amd64.tar.gz","sha256":"<hex>","size":12345678},
    {"version":"1.0.0","architecture":"arm64","filename":"agentd_1.0.0_linux_arm64.tar.gz","sha256":"<hex>","size":12345678}
  ],
  "generated_at": "<RFC3339 Z>"
}
```

`services/releases.py` 由 `artifacts_dir` **實際存在的檔案 + `checksums.txt`** 產生 manifest：

- 只列出通過 `downloads.py` 同一組 allowlist regex 的檔名（**共用同一個 pattern 常數，不重寫**），且 `checksums.txt` 中有對應 sha256、且檔案實際存在且大小相符。
- 任何無法完整對齊的項目**不列入**（不列入 = 不可安裝，fail closed）。
- `latest` 取語意版本最大者；若 `artifacts_dir` 未設定或無有效項目，回 `{"latest": null, "artifacts": []}`（**不是 404**，讓 daemon 能區分「沒有可用更新」與「端點不存在」）。
- 快取：檔案 mtime 為 key 的 process 內快取，避免每次 scan 目錄。

**這是 allowlist 的單一來源**：daemon 只能安裝出現在此 manifest 中的版本與檔名，因此「allowlisted release」的定義是可驗證的。

### 2. `daemon/internal/update`（新套件）

單一 `Updater` 型別擁有整個流程，全程持有 **process 級 lock**（同時只允許一個 update，第二次回 `UPDATE_IN_PROGRESS`）。流程對齊 tech §15.4 十步：

| Stage | 動作 | 失敗行為 |
|---|---|---|
| `manifest` | `GET {server}/api/releases/manifest`（**server URL 取自本機 `config.yaml`，不接受任何外部輸入**）；比對 `target_version`（來自 CLI flag 或 `daemon.update` payload）是否存在且架構相符；比對目前版本（相同即成功 no-op；**降級預設拒絕**，需 `--allow-downgrade`） | `UPDATE_NOT_ALLOWED`／`UPDATE_DOWNLOAD_FAILED`（網路） |
| `download` | 下載 manifest 指定的 `filename` 至 `/var/lib/agentd/update/<version>/`（0700，node run user 可寫）；bounded size（manifest 的 `size` + 容錯）、bounded 時間 | `UPDATE_DOWNLOAD_FAILED`，清理暫存 |
| `checksum` | 對下載檔算 sha256 並與 manifest 比對；**不符即中止**，不解壓、不落地到 `/usr/local/bin` | `UPDATE_CHECKSUM_MISMATCH`，刪除暫存 |
| `swap` | 解壓取出 `agentd` → 驗證可執行且 `agentd version` 可跑出預期版本（在暫存位置執行，**先驗再換**）→ 備份現行 binary 至 `/usr/local/bin/agentd.bak-<oldver>` → `rename(2)` 原子替換 | 任一步失敗即回復備份；`UPDATE_ROLLED_BACK` |
| `restart` | `systemctl restart agentd`（若非 systemd 環境則回報 `UPDATE_NOT_ALLOWED` 並要求手動） | 失敗 → rollback + restart 舊版 |
| `healthcheck` | 重啟後 **30 s 內**（monotonic）必須：新程序 `agentd doctor` 通過（非 root、config/credentials 0600、tmux 存在、Central 可達）**且** 對 Central 重新完成註冊（以 Central 端可觀測的 `node.register`/`authenticated` 為準） | 逾時或失敗 → **rollback**：回復備份 binary、restart、確認舊版健康；回 `UPDATE_HEALTHCHECK_FAILED` 或 `UPDATE_ROLLED_BACK` |

**權限（SEC-007）**：長駐 `agentd run` 仍為 non-root。替換 `/usr/local/bin/agentd` 與 `systemctl restart` 需要提權，做法二選一（ADR 0017 定案）：**(a)** `agentd update` 由 operator 以 `sudo` 執行（PRD FR-INSTALL-005 的 `sudo agentd update` 就是這個形態）；**(b)** 安裝時建立一個受限的 sudoers 片段或 systemd 輔助 unit，只允許「替換該檔案 + 重啟該 unit」兩個動作，供 non-root daemon 觸發。**預設採 (a) 為 MVP**，`daemon.update` control frame 的行為則是：daemon 收到後檢查自己是否具備提權途徑，若無則回 `UPDATE_NOT_ALLOWED` 並在 audit/log 說明需 operator 手動執行——**絕不為了自動更新而讓 daemon 長駐 root**。ADR 0017 必須寫下這個取捨。

**輸入邊界（SEC-002 延伸）**：`Updater` 的公開介面只接受 `targetVersion string`。URL、filename、checksum、下載路徑全部由 `Updater` 自 manifest 與本機 config 推導。CLI 也只提供 `--version`／`--allow-downgrade`／`--dry-run`，**沒有 `--url`／`--file`／`--checksum` 這類 flag**。以測試斷言：`Updater` 的建構與方法簽章不含任何 URL/path 參數（結構性測試 + code review checklist）。

### 3. tmux session 保留與 reconciliation

- **保證**：update 期間 tmux server 與其中的 CLI 程序**不受影響**（tmux server 是獨立程序，非 daemon 的子程序）。因此使用者的 Claude/Codex session 續存，只有 terminal 串流在 daemon 重啟期間中斷。
- **重啟後行為**：走 P2 既有的 session recovery（ADR 0012）——daemon 啟動時掃描 tmux session、與 Central 的 session 清單 reconcile（`session.list`/`session.recover`）、驅逐 orphan、瀏覽器端經既有自動重連（FR-TERM-006）重新 attach。
- **需要新增的測試**（integration，`-tags integration -race`）：
  1. 起 daemon → 建立兩個真實 tmux session（Fake CLI）→ 執行一次 update（以本機假 manifest 與同版本 binary 模擬）→ 重啟後 **兩個 session 仍存在且可重新 attach**、scrollback 未被清空、`session.list` 與 Central 一致。
  2. update 在 `healthcheck` 失敗導致 rollback → 舊版 daemon 起來後**同樣**能 reconcile 到那兩個 session。
  3. update 期間有 browser attach 中 → 連線中斷後自動重連成功，且期間的輸出以 `terminal.gap` 明示（不假裝連續）。
- **文件**：`docs/runbooks/update-failure.md` 記錄「升級期間使用者會看到什麼」與「session 是否會遺失」的明確答案，以及手動 rollback 步驟。

### 4. Central 端整合

- **觸發**：`POST /api/nodes/{node_id}/update`（`require_action(NODE_MANAGE)`，body 只有 `{target_version}`）→ 經 `registry.request()` 送 `daemon.update` → 等待 `daemon.update_result`（timeout 由 `Settings.update_request_timeout_seconds`，預設較長如 180 s，因為含下載與重啟；**逾時不代表失敗**，需以後續的 `node.register`/heartbeat 與 daemon 主動上報的 result 收斂狀態）。
- **狀態呈現**：`nodes` 表已有 `daemon_version`。**定案（ADR 0017）**：migration `0012` 以**明確欄位**新增 `update_status`／`update_target_version`／`update_last_result`／`update_updated_at`（非塞進 `node_metadata` JSONB）——「哪些 node 更新失敗」必須是可索引查詢，且 Dashboard 與 node 列表要以它排序過濾。Central 端觸發逾時**不得**逕自標記為失敗，狀態由 `daemon.update_result` 或下一次成功註冊／heartbeat 收斂。NodeDetail 與 Dashboard 顯示 current / latest（來自 manifest）/ update status。
- **UI（唯讀 + 一鍵）**：NodeDetailView 顯示「目前版本 / 最新版本 / 狀態」，Admin 可按「更新至 x.y.z」（版本由 manifest 提供的下拉，**不可自由輸入 URL 或檔名**），期間顯示進行中與 stage，結束顯示結果或失敗原因 + runbook 連結。
- **Audit**：`daemon.update_started`（actor + node + target_version）與 `daemon.update_result`（from/to/status/stage/error_code），對齊 SEC-006 第八項。
- **Metrics**：`daemon_update_total{status,stage}`（daemon 端）與 `node_update_total{status}`（Central 端）。

### 5. Release 品質（reproducible、簽章、來源）

- **Reproducible**：以固定 toolchain（`.go-version` 1.26.5）+ `CGO_ENABLED=0` + `-trimpath` + 固定 ldflags 建置；驗證方式為**同一 commit 連續建置兩次，checksum 相同**（`p4.yml` 的 `daemon-artifacts` job 執行並把兩次 checksum 存進證據包）。目前 `.goreleaser.yaml` 的 ldflags 有 `-s -w -X main.version=`，需補 `-trimpath`（GoReleaser `builds[].flags`）。
- **簽章／來源策略**（ADR 0017 定案）：MVP 至少維持 **`checksums.txt` + HTTPS 傳輸 + 封閉 allowlist**（tech §23 #12 只要求 checksum）。建議加簽（cosign/minisign）並在 daemon 端驗簽——若決定不做，ADR 必須寫明理由與殘餘風險（例如：artifacts_dir 被寫入即可投毒，緩解為該目錄的檔案系統權限與部署流程管控），並列入 `docs/security-review-p4.md`。
- **Tag 觸發發布**：`.goreleaser.yaml` 的 `release.disable: true` 是否改為由 version tag 觸發（`p1.yml` 已有 `release` 呼叫點）；決定後在 ADR 記錄。

### 6. `doctor` / `version` 呈現（FR-INSTALL-004、NFR-004）

- `agentd version` 增加 `--json`（version、commit、build time、arch）。
- `agentd doctor` 新增檢查：**目前版本 vs manifest latest**（可離線降級為 warn）、備份 binary 是否存在且可執行、update 暫存目錄權限（0700）、是否具備提權途徑（若採方案 b）。沿用既有「[ OK ]／[FAIL]／[warn]」輸出與「非零退出代表有硬問題」的語意，且**不印任何 secret**（既有 `doctor` 已遵守）。
- `agentd update --dry-run`：完成 manifest 比對與 checksum 驗證但不替換，供演練使用。

---

## 測試矩陣（research 驗收：successful、checksum mismatch、network failure、rollback、restart recovery 全通過）

| 情境 | 層級 | 判定 |
|---|---|---|
| 成功更新 | daemon integration | 版本變更、備份存在、health check 通過、audit 兩筆（started/result=succeeded）、metrics 遞增 |
| Checksum 不符 | daemon unit + integration | 中止於 `checksum` stage、**binary 未被替換**、暫存清空、回 `UPDATE_CHECKSUM_MISMATCH` |
| 下載失敗／網路中斷 | daemon unit（假 server） | `UPDATE_DOWNLOAD_FAILED`、無殘留暫存、可重試 |
| Manifest 無此版本／架構不符／降級 | daemon unit | `UPDATE_NOT_ALLOWED`，未觸碰檔案系統 |
| 新 binary 不可執行／版本不符 | daemon integration | 在 `swap` 前即擋下（先驗再換），未替換 |
| 重啟失敗 | daemon integration | rollback 至備份、舊版啟動成功、回 `UPDATE_ROLLED_BACK` |
| Health check 逾時 | daemon integration（fake clock/短 timeout） | rollback、舊版健康、回 `UPDATE_HEALTHCHECK_FAILED` |
| Restart recovery | daemon integration | 升級前的 tmux session 於重啟後可 reattach（上文三個情境） |
| 併發 update | daemon unit | 第二次回 `UPDATE_IN_PROGRESS`，不交錯 |
| 任意 URL/檔名注入 | contract + daemon unit | `daemon.update` 帶 `url`/`path` 的 fixture 被 codec 拒絕；`Updater` 介面無此參數 |
| Central 觸發與逾時 | backend DB 測試 | RBAC（僅 `node.manage`）、offline node 回 `NODE_OFFLINE`、逾時後狀態不卡在「進行中」（由後續 result/heartbeat 收斂）、audit 正確 |
| Non-root 保證 | daemon unit + install 測試 | 長駐程序非 root；若無提權途徑則明確回 `UPDATE_NOT_ALLOWED` 而非嘗試以 root 常駐 |
| Reproducible build | CI | 同 commit 兩次建置 checksum 相同 |

沙箱限制：**真實 systemd restart 與六平台矩陣無法在本機執行**（見 memory `installer-sandbox-limits`）。本機以「可注入的 restarter 介面 + 假 systemd」覆蓋邏輯，真實 systemd 路徑由 `p4.yml` 的 install/update matrix job（container 或 VM）執行。這個分工必須在 ticket 的證據中明確標示，不得以本機通過宣稱真實環境通過。

**對應需求**：FR-INSTALL-004/005、SEC-002（不接受任意 URL/binary）、SEC-003、SEC-007（non-root）、SEC-006（update audit）、tech §15.3/15.4、tech §23 #2/#12/#13、PRD §19 條目 2/3（安裝與註冊在升級後仍成立）。
