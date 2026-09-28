# 06 — 安全審查（`BP-08`）

**寫入集：** `docs/security-review-p31.md`（新）。對實作**唯讀**；發現的修正退回原 writer 的 ticket。
**審查者：** 不得是 `BP-02`…`BP-07` 任何一張票的 writer。
**方法：** `.agent/skills/cliora-security-review/SKILL.md`。每一個發現都要附 severity、
evidence（file:line）、asset、exploit precondition、impact、fix、verification，
並把「確認的缺陷」與「設計問題」分開列。

## 1. 逐項審查威脅模型

以 ADR 0029 的 T1–T17 為清單，每一項都要回答四題：

1. 控制是否**真的存在於程式碼**？附 file:line，不接受引用 ADR 或計畫當證據。
2. RED 測試是否**真的會在控制被移除時變紅**？做法是暫時註解掉控制、跑測試、看它紅，
   然後還原（mutation check），並把結果記下來。
3. 殘餘風險是否與 ADR 所寫一致？
4. 描述是否與程式碼行為一致？特別是「open 會跟隨 in-root 符號連結」（不是 `O_NOFOLLOW`），
   以及「加密判定只在渲染器」（daemon 沒有加密啟發式）。文件把啟發式寫成保證，本身就算一個發現。

## 2. 必答的十八題

| # | 題目 | 通過條件 |
|---|---|---|
| 1 | 敏感判定是否與文字預覽**同一個函式**，且呼叫兩次？ | `SensitiveClassification` 在 `preview.go` 出現兩次，沒有複本 |
| 2 | 符號連結能否繞過？ | 第二次判定用的是 `RealRel(f)` 的結果 |
| 3 | 型別是否只由 magic 加結構決定？ | 程式碼裡沒有任何以副檔名做安全判定的分支 |
| 4 | 炸彈是否在**傳輸前**被擋？ | 像素、邊長、掃描數在 daemon 端檢查，拒絕時 `bytes=0` |
| 5 | 節點內容能否在 console 網域被渲染或執行？ | 七個標頭為一組；前端沒有 `<img src=blob>`、`iframe`、`object`、`embed`、viewer、scripting |
| 6 | PDF 主動內容是否全部惰性？ | `setup.ts` 選項鎖定；E2E `pdf_active_content_inert` 在真實 CSP 下綠 |
| 7 | 中央、edge、瀏覽器是否留下位元組？ | 磁碟、DB、log、metrics label、HTTP 快取、SW、IndexedDB 皆無；nginx 專用 location 的指令存在（`04-…md` `BP-05`） |
| 8 | 跨 session／跨使用者能否看到別人的預覽？ | session 切換、登出、換使用者三條路徑都有同步清除的測試 |
| 9 | 舊 daemon 會不會收到新型別？ | `test_old_daemon_is_never_asked` 斷言零 frame |
| 10 | Viewer 是否只多了「看」，沒有多「取得」？ | 沒有任何存檔入口；預覽與下載的開關互不影響的測試存在 |
| 11 | DoS：並發、慢速 client、巨檔、終端飢餓？ | 各上限有測試；`BP-OM-05` 有量測 |
| 12 | 路徑或內容是否出現在 log、metrics、稽核、錯誤訊息？ | `test_log_has_no_path` 與成功稽核 key 集合測試 |
| 13 | 工作區路徑是否出現在**任何** URL，因而進入 nginx、uvicorn 或 Railway 的 access log？ | 路由拒絕 query 參數；前端只用 POST body；兩份 nginx 的專用 location 用 `cliora_noquery`；`BP-OM-10` canary 搜尋在每一處皆為零筆 |
| 14 | 帶路徑的請求 body 或回應 body 是否可能被 edge 寫到暫存檔？ | `client_body_buffer_size` ≥ `client_max_body_size`；`proxy_buffering off`＋`proxy_max_temp_file_size 0`；`BP-OM-06` 證據；未證實的拓樸 flag 保持關閉（OD-11） |
| 15 | FIFO、socket、裝置能否佔住 preview worker？ | 先 `StatIn`、`O_NONBLOCK` 開啟、fd `fstat`＋`SameFile`；`TestPreviewTwoFifosDoNotStarveWorkers` 在阻塞式實作下會紅（mutation check：把 `OpenFileNonBlocking` 換回 `OpenFile`） |
| 16 | Central 回退是否可行而且可測？ | 停用時省略欄位（`const: true`，`false` 無效）；凍結 schema 相容測試；`test_invalid_register_is_silently_skipped` 釘住故障形態；staging 回退演練有證據 |
| 17 | 完成的串流是否立即釋放 daemon snapshot？ | 每一種結束路徑都送 `preview_close`；N+1 次連續預覽測試綠；把成功路徑的 close 移除後測試必須變紅（mutation check） |
| 18 | 非阻塞 open 無法證實時是否 fail closed？ | `TestStartupProbeFailsClosed`；程式中沒有在工作區路徑上被放棄的 goroutine |

## 3. 依賴與授權審查（`pdfjs-dist`）

- 確認 pin 的版本**已修補所有已公開的 PDF.js advisory**。截至 2026-09-27 為 **≥ 6.2.108**：CVE-2024-4367／GHSA-wgrm-67xf-hhpq 在 4.2.67 修正；CVE-2026-16633／GHSA-hq66-cqwq-w95j（`>= 5.6.83, < 6.2.108`）於 2026-09-27 以 GitHub Advisory API 查證。pin 當天與發布前**各查一次** advisory database（閘門）；確認 `LICENSE` 為 Apache-2.0 並列入第三方授權清單。
- transitive 依賴逐一列出授權，出現 copyleft 就停。
- 確認 bundle 中沒有 `web/viewer`、`pdf.sandbox`、scripting。
- 指定 CVE watch 的負責人與頻率（寫進 `BP-11` 的 runbook）；
  PDF.js 發布安全修正時的處置是「flag off → 升版 → 重跑 `BP-09` → flag on」。

## 4. 判定格式

`PASS`、`PASS_WITH_FOLLOWUPS`（無 P0／P1，追蹤項列出議題編號）或 `FAIL`。
`FAIL` 時 ADR 0029 不得轉為 `accepted`，也不得進 `BP-11`。

## 5. 不在範圍

修正程式碼（退回原 writer）；#71 下載路徑本身的審查（它有自己的審查）；
既有 `/content` 的 edge 溢寫問題（只記錄）。
