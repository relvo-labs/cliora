# 04 — Phase 3：Workspace Files

## 階段目標

在 Session 工作區提供安全的目錄樹、檔名搜尋與唯讀程式碼預覽，且任何輸入都無法逃離設定的 allowed roots。

## 工作包

### P3-W1 Path security library

- Go 建立單一 workspace guard：absolute、clean、null-byte reject、EvalSymlinks、Rel containment。
- root、target 與 parent symlink 的 TOCTOU 風險需記錄並採最安全可行策略。
- 每次 list/read/search 都重新驗證，不依賴 client path breadcrumb 或先前 listing。
- 明確區分 invalid、outside-root、not-found、permission-denied 的 safe error code。

驗收：`../`、absolute escape、prefix collision、symlink chain、broken link、null byte、race fixture 全通過。

### P3-W2 Directory list 與搜尋 relay

- typed request/response，含 request ID、timeout、page/entry limit 與 deterministic ordering。
- ignore rules、hidden entry 行為與 root display name 明確；不回傳未授權 absolute path。
- filename search 有 depth/result/time bounds，可 cancel；不做檔案內容搜尋。
- Central 只 relay/authorize，不代替 daemon 讀 Node filesystem。

驗收：large directory、timeout、daemon disconnect、permission error、partial results 與 cancel 測試通過。

### P3-W3 Read-only file policy

- file size 上限依決策值落實，先 stat 再 bounded read，仍防止變更後超額。
- binary detection、sensitive filename/pattern deny、permission deny；預設拒絕不確定類型。
- response 含 language hint/encoding/mtime/size/denial reason，但不洩漏敏感內容。
- failed sensitive read 記 audit，只記分類與相對識別，不記內容。

驗收：`.env`/key/token fixtures、binary、oversize、encoding、file replacement/symlink swap 測試通過。

### P3-W4 File tree UI

- lazy expand、loading child、empty folder、refresh、stale、partial、offline、forbidden、error。
- keyboard tree semantics、focus/selection 分離、folder/file/hidden icon 可辨識。
- 搜尋結果回到 tree context；Node/session 切換清空不相容 cache。
- 不把 server absolute path 暴露到不必要 UI/log。

驗收：keyboard navigation、large tree、rapid expand/cancel、refresh/deleted file、offline E2E 通過。

### P3-W5 Monaco read-only preview

- Monaco readOnly、line numbers、search、word wrap、copy、refresh；與 terminal 共用深色工作區語言。
- 每個 model 有 owner；切檔 dispose 或使用有上限的受控 cache。
- binary/oversize/sensitive/permission/not-found 各有具體不可預覽畫面與下一步。
- 檔案從允許變成拒絕時清除既有內容，避免 stale sensitive data 留在畫面。

驗收：rapid switching 無 model leak；denial 不顯示前一檔內容；screen reader 有檔名、read-only 與錯誤說明。

### P3-W6 性能與安全驗證

- 目錄列表 <2 秒、2 MB 以下預覽 <3 秒的代表性量測。
- fuzz/property test workspace guard；安全測試覆蓋 traversal/symlink/sensitive/binary/oversize。
- relay queue/request bounds、timeout、cancel 與 daemon disconnect metrics。

## 階段出口

- 使用者能從 Session Workspace 瀏覽、搜尋檔名並唯讀預覽合法程式碼。
- 所有路徑逃逸與敏感內容測試必須通過，否則不可發布。
- Monaco lifecycle、offline/error/denial UI 與 file audit 均有自動驗證。
- MVP 仍不提供編輯、上傳、下載、Git 操作或 arbitrary filesystem API。
