# Cliora 行動工作階段原型與推出計畫

版本：**mobile addendum v0.1（提案）**
基準：`26f4178c7c11e19356c4bafdde0094e17c6cab65`
決策來源：#62 已選方向、#61 共用工程門檻、#64 Files 參考、#67 決策索引。

本計畫把已選定的 **A 版明亮／Pocket Workbench** 整合成單一流程：工作階段清單 → exact selected session → 直接可見的 Terminal／Files 切換 → 資料夾瀏覽、整個工作區的檔名搜尋，以及全幅唯讀 TEXT／CODE 預覽。C 只提供檔案互動參考，不形成第二首頁或平行產品。

可執行原型位於 [`prototypes/mobile-session/`](../../prototypes/mobile-session/README.md)。它與正式 Vue 程式分離，不提出 API／PTY／WebSocket 請求；所有資料與狀態都明確標為記憶體內 fixture。

## 延續的決策

1. 優先完成 responsive web；不承諾 native app、push、離線 CLI 或背景 WebSocket。
2. **行動版**固定全明亮：近白 canvas、白色 surface、深色文字、藍色 accent，以及明亮 terminal／preview。OS dark preference 不得把行動版切成深色；#62 已核准這個方向，不重啟選色。桌面維持既有主題政策。待審查的只有版本化 theme contract／ADR 落實機制。
3. Session 身分不得隱含：session id、node、runtime、workspace 持續可見；`/sessions/:id` 仍指向精確的伺服器 session。
4. Terminal 與 Files 是已選 session 的直接同層入口。開啟 Files 或 preview 不會建立 session、傳送 terminal bytes 或改變 writer。
5. 檔名 substring 搜尋涵蓋**目前 session 的整個工作區**，不是全文搜尋，也不會暗中限縮於目前資料夾；UI 顯示 partial stop reason 與 scanned count。
6. `PreviewPane.vue`／`readFileContent` 只支援唯讀 TEXT／CODE。圖片、SVG、PDF、archive、binary、unsupported encoding、sensitive、permission-denied、missing 與 oversized 都維持拒絕；本原型不是圖片檢視器。
7. 編輯、重新命名及刪除維持不採用；下載尚未建置並排除。正式版既有 upload 不在本原型內，M3 才依既有安全契約調整行動呈現。
8. 關閉／離開 main CLI 只代表 detach，不得 stop。System `TERMINAL` 是另一個 child shell，於關閉／離頁／route-id 變更／pagehide 時終止；本原型不暴露 shell 控制。
9. 原型不提供 session 建立／停止、shell、command-send、chat、approval、agent semantic 或假 reconnect 控制。

## 階段摘要

- **M0 決策與版本化契約**：確認 route／state／retention／acceptance，以及行動版專用明亮色盤的 theme contract／ADR 機制；不重開已核准的明亮方向。
- **M1 行動 shell + 獨立 IME spike**：建置 responsive 導覽／清單／session shell；以不重疊 write set 的裝置 spike 驗證繁中 IME、特殊鍵、貼上、safe area 與 `visualViewport`。
- **M2 真實 xterm**：沿用單一 terminal owner，驗證 writer／viewer、fresh ticket reconnect、resize／posture、detach 與 child-shell lifecycle。
- **M3 Files 與其餘導覽**：調整現有 FileTree／FileSearchBar／TEXT-CODE PreviewPane 契約，再依序處理 upload 與其餘導覽；圖片與其他 binary preview 維持拒絕。
- **M4 真實裝置／安全／UAT**：在 iOS Safari、Android Chrome、真實服務／node／CLI 完成 accessibility、安全、背景／網路、桌面 regression 與獨立 review 後，才可分階段推出。

## 交付內容

### 提案與契約（PR #68）

- [`00-execution-plan.md`](00-execution-plan.md)：Design Read、因果閱讀收據、範圍與實作順序。
- [`01-mobile-addendum-v0.1.md`](01-mobile-addendum-v0.1.md)：提案中的 route、state、component、terminal/input、responsive、security、preview 與 theme 契約。
- [`02-rollout-and-verification.md`](02-rollout-and-verification.md)：階段 DAG、write-set 所有權、acceptance IDs、證據分級、UAT、分階段推出、kill switch 與 rollback。
- [`prototypes/mobile-session/index.html`](../../prototypes/mobile-session/index.html)、`style.css`、`app.js`：整合式互動靜態原型。
- [`prototypes/mobile-session/test_prototype.py`](../../prototypes/mobile-session/test_prototype.py)：本機 HTTP Playwright 行為、viewport、touch、overflow、keyboard、preview restoration 與截圖測試。

### 可執行的實作規格（本次補完）

00–02 把「要遵守什麼契約」寫完了，但沒有寫「要改哪個檔、誰改、改完怎麼證明」。
以下七份把 M0–M4 落成 **`MS-D-*` 決策**與 **`MS-01`～`MS-25` 票**，每一張都綁到實際檔案與既有測試閘門。

- [`03-m0-decision-register.md`](03-m0-decision-register.md)：14 項 M0 決策的**選項 → 提案答案 → 理由 → 影響檔案 → 擋住哪張票**。沒有提案答案的決策清單會在開工時變成第二輪討論。
- [`04-mobile-shell-and-navigation.md`](04-mobile-shell-and-navigation.md)：`MS-01`～`MS-06`。斷點單一來源、安全區與軟體鍵盤、行動導覽、Sessions 卡片清單、1024–1100 檔案欄缺陷、標頭與狀態列壓縮。
- [`05-session-workspace-and-terminal.md`](05-session-workspace-and-terminal.md)：`MS-07`～`MS-13`。行動模式外殼、preview 返回鍵、fit 觸發、reconnect/detach、IME spike 的 12 項待測、輸入元件契約、writer/viewer 與姿態。
- [`06-files-and-preview-mobile.md`](06-files-and-preview-mobile.md)：`MS-14`～`MS-17`。逐層瀏覽（正式版是樹、原型是逐層，差距與解法寫在 §0）、檔名搜尋範圍標示、全幅唯讀預覽與拒絕態、可整張切除的上傳票。
- [`07-mobile-light-theme-contract.md`](07-mobile-light-theme-contract.md)：`MS-18`～`MS-21`。新增 `pocket` 主題的完整機制、**明亮終端調色盤的四條規則與一組通過全部對比門檻的實測提案值**（§1），以及 v0.1 沒有點名的三個技術後果——**ANSI 16 色只有一套且是為深底調的**、**ANSI 16 色從來不在對比測試裡**、**Monaco 每個主題都硬編 `base: "vs-dark"`**。
- [`08-verification-and-exit.md`](08-verification-and-exit.md)：`MS-22`～`MS-25`。把 `MSP-R-*` 接到實際測試檔、三個新 `GATE-MS-*` 與 traceability 條目，以及七項離場條件。
- [`09-implementation-status.md`](09-implementation-status.md)：唯一的「現在到哪了」來源，含 10 項**開放測量**（`MS-OM-*`）——其中三項可能推翻既有票的設計。

票的編號規則：`MS-D-*` 是決策，`MS-*` 是實作票，`MS-OM-*` 是開放測量，
`MSP-F-*`／`MSP-R-*` 沿用 `02-…md` 既有的 fixture／正式 acceptance ID，不重新編號。

## 目前進度

實作已在 `feat/mobile-rwd` 分支進行中。**唯一的「現在到哪了」來源是
[`09-implementation-status.md`](09-implementation-status.md)**，其中 §1.1 記錄了實作過程中
被推翻的四處計畫內容，§1.2 記錄了兩個實作中找到、非本期造成的既有缺陷。

## 原型結果，不是正式版狀態

`02-rollout-and-verification.md` 記錄的 `MSP-F-*` fixture acceptance 已通過；所有 `MSP-R-*` 仍待完成。本 PR 不改正式程式，也沒有使用真實 Central、daemon、xterm、Monaco、裝置鍵盤、授權服務或 node。Fixture 只能證明提案互動連貫，不能證明 reconnect、路徑限制、RBAC、ANSI、IME、圖片／二進位拒絕的正式服務行為、真實裝置版面或安全狀態。

## 可攜式本機重現

在複製完成的儲存庫根目錄執行，並將環境與證據放在儲存庫外：

```sh
cd /path/to/cloned/cliora
python3 -m venv /tmp/cliora-prototype-venv
/tmp/cliora-prototype-venv/bin/pip install playwright
/tmp/cliora-prototype-venv/bin/python -m playwright install chromium
/tmp/cliora-prototype-venv/bin/python prototypes/mobile-session/test_prototype.py \
  --evidence-dir /tmp/cliora-mobile-session-evidence
```

只查看原型可執行：

```sh
python3 -m http.server 8080 --bind 127.0.0.1 --directory prototypes/mobile-session
```

若已有 Chromium，可改傳 `--chromium /absolute/path/to/chromium`。本主機已驗證的精確指令為：

```sh
/opt/data/cliora-mobile-study/venv/bin/python prototypes/mobile-session/test_prototype.py --chromium /opt/hermes/.playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell --evidence-dir /opt/data/cliora-mobile-pr/evidence/mobile-session-writer
```

測試程式會自行啟停本機 HTTP 伺服器。Coordinator 接著更新 Draft PR 並要求全新的獨立 review；本 writer 不 commit、push 或進行 GitHub write。
