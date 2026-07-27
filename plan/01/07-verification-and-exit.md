# 07 — 驗證、證據與 P0 Exit Gate

## 1. 測試分層

| 層級 | 必跑內容 | 主要 owner |
|---|---|---|
| Contract | schema、三語言 fixtures、round trip、malformed/version/type/size | protocol |
| Unit | bounded queue、correlation、state、tmux naming、codec、composable cleanup | 各元件 |
| Integration | Fake CLI ↔ tmux ↔ PTY ↔ daemon ↔ Central | daemon/backend |
| Browser | keyboard/raw bytes、ANSI、Unicode、resize、refresh、gap、route cleanup | frontend |
| Resilience | burst、slow consumer、rapid reconnect、Central/Daemon restart | cross-stack |
| Security | forbidden command/argv/path、oversize/malformed flood、payload log scan | cross-stack |

## 2. 必要 CI gates

GitHub Actions 是固定 CI 平台。每個 PR：format/lint、Python typecheck/test、Go vet/unit/race、TypeScript typecheck/unit、三語言 contract、所有 build。合併主分支與 P0 release candidate：Linux tmux integration及 Playwright Chromium、Firefox、WebKit matrix；release candidate 另跑 restart harness、burst/slow consumer與依賴掃描。

測試不能依賴外部 Claude/Codex、真實 credential、網際網路服務或固定個人路徑。時間/retry 使用 fake clock；UUID/ULID與 burst data 使用可注入 deterministic source。

## 3. 操作證據包

在 `artifacts/p0/<run-id>/`（CI artifact，不必提交大型 binary）保存：

- `versions.txt`：commit、OS、tmux、Python、Go、Node/browser 版本。
- `commands.txt`：執行過的 root task commands 與 exit status。
- `contract.xml`、`unit.xml`、`integration.xml`、`e2e.xml`。
- `race.txt`、`browser-console.txt`、`resource-summary.json`。
- `screenshots/`：connected、reconnecting、gap、exited、token showcase。
- `restart-timeline.json`：Central/Daemon restart 事件與恢復時間。

任何 log/artifact 在發布前以測試掃描確認不含 Fake CLI input/output payload、credential、process environment 或不必要 absolute path。

## 4. Exit Gate checklist

### 功能

- [ ] Browser 可建立固定 Fake session，看到 `FAKECLI_READY`。
- [ ] ANSI、UTF-8、Ctrl+C、Ctrl+D、Tab、方向鍵與 resize 行為有自動證據。
- [ ] refresh 後 tmux/Fake CLI 存活並成功 reattach。
- [ ] stopped/exited session 不進入無限 reconnect。

### 契約與安全

- [ ] Python/Go/TypeScript 共用 fixtures 全通過。
- [ ] renderer 無法指定 command、binary、argv、env 或任意 path。
- [ ] malformed、unknown version/type、oversize frame 安全拒絕。
- [ ] terminal bytes 不在 application log、database（P0 無 DB）或一般 test report。

### 資源與可靠性

- [ ] `go test -race ./...` 通過，pytest 無 pending task，browser console 無 error。
- [ ] mount/unmount、disconnect/reconnect、attach/stop 重複測試無 task/goroutine/listener/timer/process leak。
- [ ] 16 MiB burst 與 slow consumer 不超出 queue limits；gap 對 UI 可見。
- [ ] Central 與 Daemon restart spike 均可恢復既有 tmux session，限制已記 ADR。

### 工程基線

- [ ] 乾淨 checkout 可依 README bootstrap、build、test、run。
- [ ] CI gates 綠燈且 artifact 可追溯到 commit。
- [ ] prototype 拆分方向、Cliora 品牌落實、protocol、limits、recovery 決策都有 ADR。
- [ ] `research/01/06-requirement-traceability.md` 已以實際證據連結更新。

任一項未過即維持 P0 open；不可因 demo 可運作而豁免 race、backpressure、cleanup 或 contract gate。

## 5. ADR/決策清單

| ADR | P0 必答問題 | Owner/截止 |
|---|---|---|
| 0001 toolchain/layout | patch versions、lockfiles、root task runner、GitHub Actions image | P0-01 前 |
| 0002 protocol-v1 | envelope、binary header、ordering、close/error | P0-04 前 |
| 0003 limits | frame/queue/snapshot limit及量測依據 | P0-14 完成時 |
| 0004 recovery | snapshot/gap、Central/Daemon restart 策略 | P0-15 完成時 |
| 0005 frontend foundation | prototype拆分、token source、Cliora 品牌與顯示設定 | P0-12 完成時 |
| 0006 P1 auth handoff | dev auth隔離與正式 browser/daemon WS handshake選項 | P0 exit 前 |

Writer takeover 只在 P0 記錄建議：owner 為 writer、viewer server-side禁止 input、顯式授權才 takeover；正式 lease/grace/admin policy 在 P2 開工前決定。

## 6. Go / No-Go review

Exit review 輸出一頁 `docs/p0-report.md`：結果、未通過項、實測 limits、已知 gap、採納 ADR、P1/P2 follow-ups。只有上述 checklist 全過且沒有未處理的高風險 memory/process leak、任意命令入口或 protocol ambiguity，才可標記 Go。若不可行，報告必須列出替代方案、需要修改的 architecture、重新估算與下一個 time-boxed spike，而非直接進 Phase 2。
