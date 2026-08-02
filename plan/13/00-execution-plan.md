# 00 — 執行總控（工作區檔案邊界：圖片投放與文字判定）

## 1. 成功定義

**要交付的：** (1) 使用者在瀏覽器裡把一張圖片交給節點上的 CLI —— 貼上、拖放或挑檔，
圖片落到節點工作區內一個由 daemon 命名的目錄，路徑被打進終端機輸入行，CLI 讀得到那張圖；
(2) 目前被誤判成 binary 而無法預覽的純文字檔可以被預覽，而真正的二進位檔仍然被擋。

**不得弄壞的五件事：**

1. **`os.Root` 的封閉性。** 新的寫入面必須走 `workspace.Root`，與 P3 的讀取面共用同一個
   `openat2 RESOLVE_BENEATH` handle（ADR 0014、`SEC-001`）。任何 `os.WriteFile(absolutePath, …)`
   形狀的程式碼都是這一期做錯了。**唯讀撤銷之後（D21）這一條的地位改變了**：
   以前繞過它最壞是讀到不該讀的，現在是寫到不該寫的。它排在第一位不是排版問題。
2. **這一條路徑上，前端與 Central 都不得命名檔案。** wire 上沒有 `filename`、`path`、
   `directory`、`extension` 欄位，瀏覽器送出的是**位元組**，落地的檔名與目錄由 daemon 決定（D2）。
   上一期把「不讓對面命名」守在 argv 上，這一期守在檔名上。
   **但它不是通則** —— 未來的編輯功能必然要讓客戶端指名，那需要另一套防護（`01-…md` §1.5）。
3. **節點的絕對路徑不外流。** 回給瀏覽器與寫進稽核的只有工作區相對路徑，而且那是**平台自己取的名字**
   （D11）。ADR 0014「browser sees workspace-relative paths only」不變。
4. **終端機的 single-writer 語意。** 路徑是**前端以 writer 身分打進去**的，不是 Central 注入的。
   本期不新增任何「平台可以對終端機打字」的通道（D6）。
5. **judgement 放寬不等於放行。** 文字判定改寬的同時必須有一份釘住的分類 corpus，否則
   `FR-FILE-004`（Binary 判斷）就從「有規則」變成「有感覺」（D16）。

成功的判準是這十項，每一項都要有可貼上的輸出（`06-…md` §3）：

1. 在 CLI session 的終端機上按 `Ctrl+V` 貼一張 PNG，終端機輸入行出現
   `.cliora/uploads/2026-08-05/01K…​.png ` （尾隨一個空白、**沒有** Enter），
   節點上該檔案存在且位元組與來源相同（SHA256 相符）。
2. 同一張圖改成拖放到終端機面板、以及用工具列按鈕挑檔，結果與 ① 完全一致（同一條程式路徑）。
3. `claude` 與 `codex` 各自被要求描述那張圖，回覆內容與圖片相符（`WF-01` 的實測項，這條沒過就沒有這個功能）。
4. Viewer 角色看不到投放入口，且直接呼叫 HTTP 端點得到 403；`file.upload` 未持有時
   `authz.denied` 稽核有一筆。
5. 送一個 `Content-Type: image/png` 但內容是 ELF 的請求，得到 `FILE_UPLOAD_UNSUPPORTED_TYPE`，
   節點上**沒有**產生任何檔案。送一個 5 MiB 的 PNG，得到 `FILE_UPLOAD_TOO_LARGE`，同上。
6. `plan/` 目錄下那 20 個今天被誤判為 binary 的 Markdown（`08-…md` §1）全部可以預覽，
   且 `docs/`、`backend/`、`frontend/`、`daemon/` 全樹掃描的誤判數為 **0**。
7. 分類 corpus（≥ 40 個檔案）全部符合期望表：PNG／ELF／tar.gz／UTF-16／尾端才出現 NUL 的檔案
   判為不可預覽；ANSI 上色的 log、含換頁字元的原始碼、CRLF、BOM、每一個切點的 CJK 文件判為文字。
8. 2 MiB 檔案的判定成本 < 5 ms（`08-…md` §3 已量到 2.66 ms），`≤2 MB preview < 3 s` 的
   ADR 0015 預算不受影響。
9. `filesystem.upload` 夾帶 `filename`／`path`／`directory` 的三個 golden invalid fixture 被
   Python／Go／TypeScript **一致拒絕**；`backend/tests/test_scope_guards.py` 擴充後仍綠。
10. 關閉 `filesystem.upload.enabled` 的節點回報 `image_upload: false`，UI **不顯示**投放入口
    （而不是顯示一顆按了會失敗的按鈕）。

## 2. 範圍

### 納入

- `WF-01` 剩餘行為實測（CLI 是否吃相對路徑的圖、xterm.js 的 image paste 事件、tmux 下的貼上行為）、
  `WF-02` ADR 0024、ADR 0015 修訂、PRD 修訂、traceability 註冊。
- daemon：文字／二進位判定重寫與分類 corpus（`WF-03`）；圖片落地面
  —— `workspace.Root` 的寫入方法、magic-number 嗅探、daemon 命名、配額、過期清理、設定與 `doctor`（`WF-04`）。
- 契約 v1.8.0（compatible）：`filesystem.upload`／`filesystem.uploaded` 兩個型別、
  `node-register.image_upload` 一個回報欄位、四個 golden fixture（`WF-05`）。
- Central：`POST /api/sessions/{id}/files/images`、RBAC action `file.upload`、稽核 `file.upload`、
  四個錯誤碼、migration 0018（`nodes.image_upload`）（`WF-06`）。
- 前端：三個投放入口與路徑插入（`WF-07`）；預覽否決文案區分「二進位」與「編碼不支援」、
  「唯讀」標示的誠實化（`WF-08`）。
- `.agent/skills` 更新（`WF-09`）、evidence／gates／runbook／release note（`WF-10`）、
  安全審查與 exit gate（`WF-11`）。

### 不納入

- **一般檔案上傳。** 只有四種圖片格式、只有一個由 daemon 命名的目錄。見 D3。
- **下載、編輯、刪除、重新命名。** `NFR-005.AC-109` 這一期只被切下一片，不是被撤銷（`01-…md` §2.2）。
- **在預覽窗顯示圖片。** ADR 0015 的 "image/PDF/archive preview: metadata only" 不變。
  上傳後的縮圖用瀏覽器端的 blob URL 呈現，不經節點（D19 的「被否決」）。
- **自動偵測非 UTF-8 編碼。** 見 D15：這一期給的是**命名**（`unsupported_encoding`），
  不是猜測；轉碼是選用票 `WF-03b`，本期不做。
- **新的 binary frame kind。** 圖片走既有控制訊框，terminal 資料面（kind 1／2）一個位元組都不動（D5）。
- **Central 對終端機注入輸入。** 見 D6 的「被否決」。
- **拖放資料夾、多檔批次、剪貼簿讀取節點端內容。**

## 3. 固定基線決策

| # | 決策 | 選擇 | 理由 |
|---|---|---|---|
| D0 | **前提不能沿用上一期** | ADR 0023 D0（節點是可丟棄的隔離 VM）**不作為本期的免責條款**。本期新增的風險不落在「節點壞掉」，而落在兩個 VM 隔離管不到的地方：**寫進工作區的內容**（那是使用者的程式碼庫，重建 VM 不會還原它）與 **Central 成為一條檔案通道**（跨租戶） | 上一期可以用「壞掉就再做一個」把節點內的破壞移到已接受成本，因為那些破壞的範圍就是那台機器。這一期不行：使用者的 workspace 通常掛在會被心疼的地方，而 Central 是共用的。把這句話寫在第一條，是為了擋掉「反正 sandbox 都關了，寫個檔案有什麼關係」這種推論 |
| D1 | 圖片落在哪 | **工作區內**的固定相對目錄 `.cliora/uploads/<YYYY-MM-DD>/<ULID>.<ext>` | 三個理由：(a) 沿用 P3 既有的整套限制（`os.Root`、allowed roots、guard 的 re-canonicalise），不需要為寫入發明第二套路徑安全；(b) session 以 `tmux new-session -c <workspace>` 啟動（`daemon/internal/tmux/client.go:147`），所以**相對路徑就是 CLI 解得開的路徑**，Central 不必知道絕對路徑；(c) 使用者在檔案樹裡看得到、也刪得掉自己丟過什麼。**被否決**：`/var/lib/agentd/uploads`（跳出 ADR 0014 的封閉範圍，且 CLI 讀工作區外的檔案在還有沙箱的節點上會被擋）；`/tmp`（重開機消失，且同機其他使用者可讀） |
| D2 | 檔名由誰決定 | **daemon**。wire 上沒有 `filename`／`path`／`directory`／`extension` 欄位；瀏覽器送位元組，daemon 產生 `<ULID>.<嗅探到的副檔名>` | 沿用 1.4.0（`daemon.update` 只有版本號）、1.6.0（`tunnel.open` 沒有 host）、1.7.0（姿態只回報不指定）的同一條規則：**不讓對面命名**。這一個決定同時消滅三個問題 —— 路徑穿越、雙副檔名（`x.png.sh`）、覆寫既有檔案 —— 而且不需要三段驗證程式碼去擋。客戶端原始檔名只作為 UI 顯示標籤，不進 wire、不進檔名、不進稽核 |
| D3 | 允許哪些格式 | `image/png`、`image/jpeg`、`image/gif`、`image/webp` 四種，以 **magic number** 判定，不看宣告的 `Content-Type` | 四種是 claude／codex 都吃的交集（`WF-01` 覆核）。**被否決**：SVG（是可執行的 XML，且 CLI 不把它當圖）；PDF（不是使用者要解的問題，而且它會把「圖片投放」偷偷變成「文件投放」）；任意檔案（**唯讀撤銷不等於一般上傳被核可** —— W2 的配額對任意大小的檔案還沒有設計，W3 的稽核形狀也不同。那是下一個 ADR 的事，不是這一個的推論） |
| D4 | 大小上限 | 單張 **4 MiB**（原始位元組）。Central 先擋，daemon 再擋 | base64 後 5.33 MiB，加 JSON 外殼仍在 `MaxFilePayload` 8 MiB 之內，也在 uvicorn `ws_max_size` 16 MiB 之下。上限訂在 Central 是為了**不把 4 MiB 以上的東西送進節點連線**；訂在 daemon 是因為 Central 不是唯一可信的呼叫者 |
| D5 | 傳輸形狀 | 既有控制訊框 ＋ base64。新增 `filesystem.upload`（Central→daemon）與 `filesystem.uploaded`（daemon→Central）。`filesystem.upload` 加入 `LargeFrameTypes` | 這是 1.3.1 之後**第一個**被允許用 8 MiB 的請求型別，而且方向是 Central→daemon —— 代價要寫明：節點側的控制訊框解碼上限，對這一個型別從 64 KiB 放寬到 8 MiB。可接受的理由是這條連線的對面是已認證的 Central，且 daemon 仍在解碼後立刻檢查大小與型別。**被否決**：新增 binary frame kind 3（動到 terminal 資料面，要處理分塊、重組與亂序，為一張 4 MiB 的圖不值得）；分塊控制訊框（需要組裝狀態機與逾時清理，同樣的理由） |
| D6 | 路徑怎麼進到 CLI | 上傳成功後，**前端**以既有的 terminal WebSocket、以 **writer** 身分送出「相對路徑 ＋ 一個空白」，不送 Enter | 不新增協定、不新增權限。使用者保留最後一步（他可能還要打字說明要這張圖做什麼）。**被否決**：Central 代打（那會開出一條「平台可以對任何終端機打字」的通道，那個權限比圖片上傳大得多，而且它會繞過 single-writer）；自動送 Enter（把「我在準備一段話」變成「我送出了一段話」） |
| D7 | 誰可以投放 | 新 RBAC action **`file.upload`**，Admin＋Developer 持有，Viewer **不**持有；UI 另外只在 `role === "writer"` 時顯示入口 | **被否決**：沿用 `file.browse`（三個角色都持有，Viewer 會一併取得寫入權，而 P3 明確把 Viewer 定為唯讀）；沿用 `terminal.operate`（語意是操作終端機，不是寫檔；稽核上會分不出「他打了字」與「他寫了檔案」）。權限與 writer 角色是兩件事：前者決定「可不可以」，後者決定「現在輪不輪得到你」 |
| D8 | 節點可以拒絕 | daemon 設定 `filesystem.upload.enabled`（預設 `true`），並在 `node.register` 以 `image_upload` **回報**；UI 依回報決定是否顯示入口 | 沿用 1.7.0 的 report-only：節點說自己是什麼姿態，平台不指定。預設 `true` 的代價與 ADR 0023 D2 相同 —— **升級即取得新行為** —— 所以同樣要有 release note 與 runbook（`06-…md` §4），不得靜默 |
| D9 | 配額與清理 | 每 session 累計 **64 MiB**、每日 **200 張**（皆可設定），超過回 `FILE_UPLOAD_QUOTA_EXCEEDED`；daemon 在 session 啟動時與每 6 小時清掉 `.cliora/uploads/` 中 **7 天前**的檔案 | 這是平台的第一條寫入路徑，沒有上限就是一個磁碟填滿的入口。**被否決**：不清理（工作區會長出一個沒有人負責的目錄，而且它會被 commit 進去）；session 結束就刪（使用者下一個 session 可能還要引用同一張圖，而 CLI 的對話紀錄會指到一個已經消失的檔案，症狀是「AI 說它看不到圖」） |
| D10 | `.cliora/` 的 git 汙染 | 建立目錄時**一併寫入** `.cliora/.gitignore`（內容 `*`），且僅在該檔不存在時寫 | 不寫的話，每個使用者的 `git status` 都會多出一批圖，而它們會被 `git add .` 帶進 commit。這是一行檔案就能避免的長期麻煩。「僅在不存在時寫」是因為使用者可能有自己的規則，平台不覆寫使用者的檔案 —— 這條同時是本期唯一允許寫入非 `uploads/` 路徑的例外，要在程式碼裡寫死 |
| D11 | 稽核 | 新增 `file.upload` 稽核事件，記 `session_id`、`node_id`、嗅探到的 mime、位元組數、**相對路徑** | 相對路徑可以記，因為它是**平台自己取的名字**，不是節點上既有的檔名。ADR 0014 禁止的是洩漏節點既有的路徑結構；這條路徑是我們造出來的，而且不記的話「誰在哪個 session 丟了什麼」就只剩一個計數器。內容永遠不記 |
| D12 | 判定的範圍 | 從「前 8 KiB」改為**已讀取的全部內容**（≤ `max_preview_size`） | 這是本期修掉誤判的主因。實測（`08-…md` §1）：本 repo 878 個純 UTF-8 文字檔中，20 個被誤判，**每一個**的原因都是 8 KiB 窗格切在多位元組字元中間；佔 >8 KiB 且含多位元組字元的檔案的 **8.7%**。同一個改動也修掉反向的漏判（`08-…md` §2：前 8 KiB 都是可列印 ASCII 的二進位檔今天會被當文字送出）。成本已量測：2 MiB 檔案 **2.66 ms**，對 3 秒的預覽預算是 0.09% |
| D13 | UTF-8 驗證的邊界 | 驗證必須落在 **rune 邊界**上（若未來又引入窗格，尾端最多回退 3 bytes） | 這是 D12 的根因本身。即使改成全檔掃描，這條規則仍要寫成註解與測試，否則下一個為了效能重新引入窗格的人會把同一個 bug 裝回去 |
| D14 | 控制字元比例 | ESC（0x1b）、FF（0x0c）、VT（0x0b）**視為文字**；比例改成 rune 對 rune；門檻維持 10% | 實測（`08-…md` §2）：每行三組 ANSI 顏色的 log 今天被判為 binary，spinner 輸出也是 —— 而那正是使用者最想在瀏覽器上看的檔案之一。ESC 本來就是終端機的文字。另外，今天的比較是 **rune 數對 byte 長度**，單位不一致：同樣密度的控制字元，CJK 檔案因為位元組多而被放行，ASCII 檔案被擋。單位一致之後 10% 這個數字才有意義。**被否決**：把門檻調到 30%（那是把單位錯誤用一個更寬的數字蓋過去） |
| D15 | 非 UTF-8 的文字編碼 | **不猜**。UTF-8 驗證失敗時回一個新的否決原因 `unsupported_encoding`（沿用 `FILE_BINARY` 這個 code，以 `reason` 區分），前端文案改為「編碼不支援」而不是「二進位」 | 使用者的抱怨是「純文字檔被當成 binary」，而實測顯示這個 repo 裡**全部**的誤判來自 D12，不是來自編碼。在沒有證據的情況下引入 `golang.org/x/text`（daemon 目前只有 6 個直接相依）與一套編碼猜測，是用一個會猜錯的機制去解一個還沒被量到的問題 —— 而猜錯的代價是畫面顯示亂碼，看起來像檔案損毀。**選用票 `WF-03b`**：若 `WF-01` 在使用者真實工作區上量到 Big5／GBK 檔案確實常見，再以**明示設定** `filesystem.fallback_encoding`（預設空）加上去，回應的 `encoding` 欄位據實回報 —— 那個欄位前端已經在顯示了（`PreviewPane.vue:112`） |
| D16 | 放寬必須被釘住 | 新增分類 corpus `daemon/internal/files/testdata/classify/`（≥ 40 個檔案＋期望表），並新增需求 **`FR-FILE-008` 文字判定準確度**（`verification_profile: measurement`） | 「判得太嚴」的相反不是「判得對」，是「判得太鬆」。沒有 corpus 的話，這一期的改動在六個月後會被一個「某個 log 又被擋了」的回報再放寬一次，而沒有人知道那樣會不會讓 ELF 檔灌進 Monaco。corpus 讓兩個方向都有數字 |
| D17 | 契約 | **v1.8.0（compatible）**：兩個新型別、一個回報欄位。**不新增任何可讓 Central 指定檔名、路徑、目錄、副檔名或覆寫行為的欄位** | 與 D2 同一條規則的 wire 版本。四個 golden invalid fixture 把它釘住（`04-…md` §1.3） |
| D18 | Central 不落地 | 請求體直接讀進記憶體（上限 4 MiB）、轉 base64、送出、丟棄。**不寫暫存檔、不寫 DB、不進 log、不進 metrics label** | Central 是共用的；一張圖在 Central 落地一次，就要回答保存多久、誰能讀、備份裡有沒有這三個問題。不落地就不必回答。實作上要用 `Content-Length` 先擋、再以有上限的串流讀取，避免「先讀完再檢查」 |
| D19 | 「唯讀」標示要誠實 | 預覽窗的「唯讀」標示保留（預覽確實不可編輯），但工作區**不再唯讀**。檔案樹要能看出 `.cliora/uploads/` 是平台寫入的目錄，release note 要明寫這是第一條寫入路徑 | ADR 0015 的 RBAC 段落與 P3 的整個敘事都建立在「唯讀 MVP」上。留著一個不再為真的標示，比沒有標示更糟。**被否決**：在預覽窗顯示上傳的圖片（那是 ADR 0015 明確排除的 image preview，而且它需要節點回傳二進位內容 —— 一條新的資料出口。上傳後的縮圖用瀏覽器端還握著的 blob 呈現就夠了，不必經過節點） |
| D20 | 這一期不碰的東西 | terminal relay 的 single-writer、ws-ticket、backpressure、tunnel、daemon update、edge nginx、CSP | 判準：若 diff 出現在 `backend/app/api/ws/terminal.py` 的寫入者仲裁、`deploy/`、`daemon/internal/tunnel/` 或 `daemon/internal/update/`，就是走錯路了。**已核對**：`client_max_body_size` 兩處都已是 `16m`（`04-…md` §2.5），4 MiB 的上傳不需要任何 edge 變更，所以這條沒有例外 |
| D21 | **唯讀是被撤銷，不是被開了一個例外** | 使用者 2026-08-01 指示：唯讀工作區可撤銷、日後朝向可編輯、平台可寫入使用者工作區。因此本期撤銷 `NFR-005.AC-142`（產品核心原則裡的那一條），並以 ADR 0024 的 **W1–W4** 取代它：經 `workspace.Root`、有配額與保留期、每次寫入留稽核、節點可拒絕並回報。圖片投放是第一個實例，**不是全部** | 「例外」與「姿態變更」在文件上差一個詞，在後果上差很多：例外會被當成一次性特許，於是下一條寫入路徑要重新辯論一次；姿態變更會被當成新的預設，於是下一條路徑照著 W1–W4 做。使用者要的是後者。代價是**平台的預設答案從「不能寫」變成「這條路徑還沒做」**，所有講唯讀的地方都要改語氣（`01-…md` §3 第 2 點）。**這一期仍然不做編輯** —— 撤銷姿態不等於交付功能，而編輯要決定的（衝突、並行、`.git/` 保護、敏感檔案在寫入方向的政策）每一項都比圖片投放大 |

## 4. 波次與 ticket

| 波次 | Ticket | 標題 | 依賴 |
|---|---|---|---|
| **0（閘門）** | `WF-01` | 行為實測：CLI 讀相對路徑圖片、xterm.js image paste、tmux 下的貼上、四種格式的接受度 | — |
| | `WF-02a` | **姿態**：ADR 0024 的 §1.2（撤銷唯讀、W1–W4）與 §1.5、`NFR-005.AC-142` 撤銷、ADR 0015 的 Scope／RBAC 修訂 | — |
| | `WF-02b` | **需求**：ADR 0024 的 §1.3（圖片投放五條限制）、`FR-FILE-009`、`NFR-005.AC-109` 加註 | `WF-01` |
| | `WF-02c` | **判定**：`FR-FILE-004` 註記、新增 `FR-FILE-008`、tech §11.6 修訂 | — |
| **1（daemon）** | `WF-03` | 文字／二進位判定重寫、分類 corpus、benchmark | `WF-02c` 核准 |
| | `WF-04` | `workspace.Root` 寫入面、嗅探與命名、配額、清理、`.gitignore`、設定、`doctor` | `WF-02a`＋`WF-02b` 核准 |
| **2（契約與 Central）** | `WF-05` | 契約 v1.8.0：兩個型別、`image_upload` 欄位、四個 invalid fixture、三個 consumer | `WF-04` |
| | `WF-06` | HTTP 端點、RBAC `file.upload`、稽核、錯誤碼、migration 0018 | `WF-05` |
| **3（前端）** | `WF-07` | 三個投放入口、上傳進度與失敗處理、路徑插入、縮圖 | `WF-06` |
| | `WF-08` | 否決文案區分二進位／編碼、唯讀標示誠實化、`.cliora/` 在檔案樹的呈現 | `WF-03`、`WF-06` |
| **4（收尾）** | `WF-09` | `.agent/skills` 修訂（`cliora-project-context`、`go-daemon-development`、`vue-naive-ui-workflow`） | `WF-02a` 核准 |
| | `WF-10` | evidence script、gates 註冊、runbook、release note | `WF-03`–`WF-08` |
| | `WF-11` | 安全審查（`docs/security-review-p13.md`）、exit gate | `WF-10` |

`WF-02` 拆成三票，是因為使用者已經核准了姿態（D21），但實測還沒做完 ——
把它們綁在一起會讓一個已經可以寫下來的決定，等一個與它無關的量測：

- **`WF-02a`（姿態）沒有前置。** 撤銷唯讀、立下 W1–W4 不依賴 CLI 怎麼讀圖。
  它應該**最先做完**，因為 `WF-04`（寫入面）與 `WF-09`（skills）都靠它，
  而且它是這一期唯一會被六個月後的人翻出來讀的東西。
- **`WF-02b`（圖片投放的需求）等 `WF-01`。** `FR-FILE-009.AC-06`（相對路徑送進終端機）
  直接寫著實測還沒證實的行為。實測不成立就是設計變更（§5 第一列），
  先把 AC 寫死會得到一條要重寫的需求。
- **`WF-02c`（判定）沒有前置。** 四項實測都做完了（`08-…md` §1–§3）。

**閘門仍然存在**：`WF-02a`＋`WF-02c` 未核准前不得動 daemon 程式碼。
理由和上一期相同 —— 這是一次姿態變更，書面決定必須先於實作
（ADR 0021 §Context「它不是被審查的，是在這裡被公開決定的」）。

**兩條線可以並行、也應該並行：** `WF-03`（文字判定）與圖片投放沒有共用程式碼，
只共用一個套件與一份 release note。若圖片投放卡在 `WF-01`，`WF-03` 不必等 —— 它自己就是一個
可以獨立出貨的修正（`06-…md` §6 的「部分出貨」條件）。

## 5. 風險

| 風險 | 徵狀 | 處置 |
|---|---|---|
| **CLI 不吃相對路徑的圖** | 路徑打進去了，CLI 說找不到檔案，或把它當成純文字看待 | `WF-01` 第 1 項（`08-…md` §4）是閘門。若不成立，備案依序是：(a) 改送絕對路徑 —— 但那要修改 ADR 0014「相對路徑」的敘述，是一次 ADR 修訂而不是一個參數；(b) 改用 CLI 自己的圖片語法（如 `@path`），那會讓前端必須知道 runtime 的方言，要在 D6 加一張對照表 |
| 貼上事件被 xterm.js 吃掉 | 使用者按 `Ctrl+V` 沒有反應，或只貼進檔名文字 | `WF-01` 第 2 項先量：xterm.js 對含 `clipboardData.files` 的 paste 事件的行為。攔截要用 capture 階段、且**只在有 files 時**接手，否則會弄壞一般的文字貼上（那是每天都在用的功能） |
| 8 MiB 的請求訊框被當成新的攻擊面 | 有人用 `filesystem.upload` 對節點連線灌大量資料 | D5：只有這一個請求型別放寬，daemon 解碼後立刻檢查型別與大小；Central 端的 4 MiB 上限與 RBAC 在更前面；配額（D9）在更後面。三層都要有測試 |
| 工作區被寫爆 | 節點磁碟滿，session 起不來 | D9 的三個上限＋7 天清理；`doctor` 增加一行「uploads 目錄大小」；runbook 寫「如何手動清空」 |
| 判定放寬讓二進位內容灌進 Monaco | 預覽窗出現亂碼、瀏覽器卡住 | D16 的 corpus 是主要防線；另外全檔掃描（D12）在這個方向上其實**比今天更嚴**（今天前 8 KiB 乾淨就放行），這一點要在 release note 講清楚，因為會有少數今天看得到的檔案變成看不到 |
| 「唯讀」的敘事斷裂 | 使用者（與六個月後的我們）以為工作區還是唯讀的 | D19：UI 標示、ADR 0015 修訂、release note 三處同時改。判準是：搜尋 `唯讀` 與 `read-only` 的每一處命中都要重讀一次 |
| `.cliora/` 被 commit 進使用者的 repo | PR 裡出現一批 ULID 檔名的圖 | D10 的 `.gitignore`；release note 提醒既有節點在升級後第一次上傳才會產生該檔 |
