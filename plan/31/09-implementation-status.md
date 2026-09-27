# 09 — 實作狀態

最後更新：2026-09-27。**唯一的「現在到哪了」來源。**

## 1. Ticket 狀態

| Ticket | 狀態 | 備註 |
|---|---|---|
| Phase 1 設計文件 | **本版提交（未 commit）** | ADR 0029（`proposed`）＋本目錄 |
| `BP-01` 治理 | 未開始 | 等 #76 合併、#71 狀態確定、產品決策 OD-1…OD-10 |
| `BP-02` 契約 | 未開始 | — |
| `BP-03` daemon | 未開始 | — |
| `BP-04` Central | 未開始 | — |
| `BP-05` edge | 未開始 | — |
| `BP-06` 前端生命週期＋圖片 | 未開始 | 依賴 #76 合併 |
| `BP-07` 前端 PDF.js | 未開始 | — |
| `BP-08` 安全審查 | 未開始 | — |
| `BP-09` 驗證 | 未開始 | — |
| `BP-10` 實機 | 未開始 | — |
| `BP-11` 推出 | 未開始 | — |

**沒有任何功能已上線，沒有任何測試已寫。** 本版只有設計文件。

## 2. 外部相依的當下狀態（2026-09-27 核對）

| 項目 | 狀態 | 對本計畫的影響 |
|---|---|---|
| #76（手機檔案清單空白） | 開啟中；修補在本機分支 `fix/mobile-file-browser-76` @ `a453bd4`，**尚未推送**（見 #76 留言） | `BP-06` 的 auth-loss 掛點（`router/authLoss.ts`）只存在於該分支 |
| PR #71（下載） | 開啟中，mergeable，最後更新 2026-09-16 | 佔用 ADR 0028、`plan/30`、v1.10.0、`0021`、`FR-FILE-011`；本計畫編號排在其後（README） |
| `make traceability` census | 依 #71 描述，master 上自 `NFR-007` 起即為紅燈 | `BP-01` §5 第 4 點 |

## 3. 開放測量（`BP-OM-*`）

每一項都可能推翻某個預設。量到之前，相關的 OD 不算定案。

| ID | 問題 | 影響 | 在哪一張票量 |
|---|---|---|---|
| `BP-OM-01` | iOS Safari 的 canvas 最大面積與單頁總記憶體上限實際是多少？ | OD-2 像素上限；§11 縮放策略 | `BP-06` 開工時；`BP-10` 複驗 |
| `BP-OM-02` | 在現行 CSP（`img-src 'self' data:`）下，iOS／Android 的 `createImageBitmap(Blob)` 是否可用、是否受 `img-src` 約束；`imageOrientation` 與 resize 選項的支援 | 是否需要 `img-src blob:` 的 fallback（需另行審查） | `BP-06` |
| `BP-OM-03` | iOS Safari 與 Android Chrome 長按 `<canvas>` 是否出現存檔選單 | 「沒有存檔入口」這個宣稱 | `BP-06`；`BP-10` #2 |
| `BP-OM-04` | 選定的 PDF.js 版本在現行 CSP 下：worker、wasm、FontFace、cMap 是否全部可用而無 violation | 是否需要改 CSP（需另行審查） | `BP-07` 第一天 |
| `BP-OM-05` | 每節點 4 條預覽串流時，終端 echo 延遲的增量 | 512 KiB 分塊與並發上限 | `BP-09` |
| `BP-OM-06` | nginx 在現行設定下是否真的把大回應寫到 `proxy_temp`；Railway edge 是否緩衝或落地 | `BP-05` 的必要性與 Railway 上的殘餘風險 | `BP-05` |
| `BP-OM-07` | PDF.js 現代 build 在產品支援清單裡最舊的 iOS／Android 瀏覽器上是否可用 | OD-9 | `BP-07`；`BP-10` |
| `BP-OM-08` | 舊 Central 收到帶 `binary_preview` 的 `node.register` 時，是拒收該訊息還是斷線 | 推出順序錯誤時的故障形態 | `BP-02` |
| `BP-OM-09` | Central 是否為單一 process 服務一個節點的 WebSocket（串流上限用 process 內 semaphore 的前提） | 並發上限的實作方式 | `BP-04` |

## 4. 本版文件中明確標為「未驗證」的假設

- iOS canvas 面積上限 16 777 216 px 是常見報告的數字，不是實測（`BP-OM-01`）。
- 以 Blob 呼叫 `createImageBitmap` 不受 `img-src` 約束（`BP-OM-02`）。
- nginx 在預設 `proxy_max_temp_file_size` 下會把大回應溢寫到磁碟。依 nginx 文件如此，本部署未實測（`BP-OM-06`）。
- PDF.js 的 WebAssembly 解碼器與 FontFace 在現行 CSP 下可用（`BP-OM-04`）。
- PDF.js 的 `stopAtErrors: true` 不會誤拒常見的良性 PDF（`BP-09` 語料驗證）。
- Starlette／uvicorn 的 `StreamingResponse` 會把 client 的背壓傳回 generator（`BP-04` 的 `test_stream_backpressure`）。
- PDF.js 的 CVE 下限（4.2.67）與授權（Apache-2.0）依公開資料，實際版本在 `BP-07` 核對。
