# 06 — 實作狀態

最後更新：2026-09-16。

| Ticket | 狀態 | 產出 |
|---|---|---|
| `FD-02` 治理 | **完成** | ADR 0028、PRD `FR-FILE-011` ＋ 三處修訂、traceability 十條 AC × 四連結 |
| `FD-03` daemon | **完成** | `files/download.go`、`DownloadConfig`、`handleFsDownload`、`filesystem_download_bytes`、`download_test.go` |
| `FD-04` 契約 | **完成** | v1.10.0：兩個 schema、`node-register.file_download`、九個 fixture、三個消費端 |
| `FD-05` Central | **完成** | `GET …/files/download`、`download_file`、`file.download` 稽核、四個錯誤碼、migration `0021` |
| `FD-06` 前端 | **完成** | `downloadFile`、`useFileDownload`、預覽工具列、被拒面板逐分支提議 |
| `FD-07` 文件 | **完成** | release note、runbook、error catalog 重新產生 |
| `FD-08` exit | **部分** | 見下 |

## 已跑過並通過

- `make check` 的全部項目（format / lint / typecheck / unit / contract / build /
  traceability-validate / railway-check / layout-gates / vr-gates）。
- daemon：`go test ./...`（含 `-race`）。
- backend：735 個單元測試；371 個 DB 測試。
- frontend：1058 個單元測試。
- `make traceability` 全部五個階段（validate／selectors／coverage／
  coverage-baseline／test）。
- `make integration`（daemon 的 `-tags integration -race`，需要 tmux）。

## 順手修正的既有紅燈（不是本期造成的）

`make traceability` 的 census 斷言（`scripts/traceability/tests/test_traceability.py`）
**在本期開始前就已經是紅的**：`NFR-007`（行動視窗的操作性，`plan/29`，commit
`22827cb`）登記了七條 AC 卻沒有更新那個累計數，所以自該 PR 合併起
`make traceability` 在 master 上就過不了。

本期把它改對了，並且**分成兩行寫**：一行記那 +7 與它的來歷，一行記本期的 +10。
折進同一行會比較短，但一個會默默吸收差額的累計數就不再是 census，
而是一個有人改到測試通過為止的數字。

## 尚未跑過，且不假裝跑過

- **full-stack E2E**（`E2E_FULL_STACK=1 ./scripts/e2e/run-stack.sh …`）。
  本期沒有新增 Playwright 案例；下載的瀏覽器端行為（存檔對話框、
  `URL.revokeObjectURL` 的實際時序）只有單元層的覆蓋。
  這是**已知落差**，不是「已驗證」。
- **`make perf`**。本期沒有延遲量測；4 MiB 檔案在真實節點上的
  端到端時間沒有數字，`filesystem_download_bytes` 的分布也還沒有樣本。
  這一點直接關係到 D3 的「日後」欄——加不加分塊下載，目前仍只能從軼事論證。
- **多瀏覽器的 `Content-Disposition` 行為**。RFC 5987 的解析在三大引擎上
  只有規格保證，沒有本期的實測。
