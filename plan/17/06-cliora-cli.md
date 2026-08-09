# 06 — `cliora` CLI（`TK-08`）

**本階段的關鍵路徑**（`research/02/03` TK-06）：內化之後，Agent 沒有工具就完全無法記錄工作。

## 1. 它就是 `agentd`（D2）

### 1.1 為什麼不投影一支二進位

三條各自足以否決：

| 阻擋 | 出處 |
|---|---|
| 單檔上限 4 MiB，而 Go 靜態二進位遠大於它 | `daemon/internal/config/config.go:205` |
| `.cliora/` 對使用者寫入 verb 是禁區 | `store_policy.go:83` |
| update 的解壓器**只取單一成員 `agentd`**，加第二個檔案要動一個刻意最小化的解壓面 | `daemon/internal/update/files.go` 的 `binaryMember` |

第三條最重要：那段程式碼的註解寫著「Deliberately not a general extractor.
There is nothing else in the archive this code needs, and an extractor that handled
directories, symlinks and arbitrary paths would be a tar-traversal surface for no benefit.」
**為了發一支 CLI 去擴充它，是拿一個已經收斂好的安全面去換一個便利。**

### 1.2 形狀

```text
/usr/local/bin/agentd            ← 既有，update 會就地替換
/usr/local/bin/cliora  → agentd  ← symlink，安裝時建立
```

分派：`main()` 讀 `filepath.Base(os.Args[0])`，
`cliora` → CLI 模式，其餘 → 既有的 daemon 模式。
另保留 `agentd cliora …` 子命令形式，讓沒有 symlink 的環境（容器、測試）也能用。

三個附帶好處：

1. **版本永遠與 daemon 相符**——因為它是同一個檔案。
2. **D11 想要的「MCP 設定要指向一個穩定的可執行路徑」在 V2.1 就成立**，
   V2.4 做 MCP 時不必再搬一次家（`research/02/01` D11 的「發佈方式」段落）。
3. release pipeline、checksum、更新路徑**一行都不改**。

### 1.3 symlink 的建立與存活

`daemon/internal/install/plan.go` 的安裝計畫加一步：
建立 symlink（已存在且指向 `agentd` → 視為完成；已存在但指向別處 → **不覆寫**，
在 `agentd doctor` 裡報一條可行動的訊息）。

**update 之後 symlink 仍然有效**：更新是就地替換 `agentd` 那個檔案，symlink 指的是路徑不是 inode。

**0.7.0 升到 0.8.0 的既有 node 不會自動長出 symlink**——update 只換二進位。
所以 0.8.0 的 daemon **啟動時**檢查一次：symlink 不存在且有權限就建立，
沒有權限就在 doctor 輸出裡說明。這一條要有測試。

## 2. 四個子命令（V2.1 的最小集合，D11）

```text
cliora context show                     讀 .cliora/context/<id>.md      不需要連線
cliora task list                        本 Project 的任務
cliora task get <ref>                   單一任務詳情
cliora task update <ref> --stage implementing --note "…"
```

### 2.1 憑證與 Session 的解析

依序嘗試，第一個成功的就用：

1. `CLIORA_SESSION_ID` 環境變數（若日後 daemon 願意注入）——**本期不做**，
   但解析順序先寫進去，因為它是 V2.2 唯一會變的地方。
2. **從 cwd 往上找 `.cliora/context/`**，取其中唯一的一組 `<id>.md` ＋ `<id>.token`。
3. 多於一組時：要求 `--session <id>`，並列出候選。

第 2 條是本期的實際路徑。**往上找**是因為 Agent 常常 `cd` 進子目錄；
停在第一個 `.cliora/` 或 workspace 邊界。

Central 的位址從 `.cliora/context/<id>.md` 的 front-matter 讀
（投影時寫進去），**不從 daemon 的 config 讀**——CLI 是以使用者身分跑的，
不該假設它讀得到 daemon 的設定檔。

### 2.2 `context show` 不需要連線（D14 的前提）

它就是把本機檔案印出來。**沒有任何網路呼叫**，有一條測試在網路完全不可用的情況下跑它。

理由不是效能：平台掛掉時 Agent 至少還知道自己在做什麼，
而那正是 D14 接受「直接失敗」這個取捨的前提。

### 2.3 離線行為（D14）

`task list`／`get`／`update` 需要連線。連不上時：

```text
無法連線到 Cliora（Session 可繼續工作）。
你的變更未被記錄，恢復連線後請重新執行。
```

四條規則：

1. **訊息由 CLI 產生**，不是把 HTTP 錯誤原樣吐出來。
2. **第二句是整條決策的重點**——沒有它，Agent 很可能判斷「我沒辦法繼續」而停下來，
   那才是真正的損失。
3. exit code **非零**（`2` 表示連線問題，`1` 表示請求被拒絕），
   但情境包裡明寫「這不代表你不能繼續工作」。
4. **不排隊、不重試、不寫本機佇列。** D14 已裁決。

### 2.4 其他失敗的訊息

| 情況 | 訊息 |
|---|---|
| token 過期／Session 已結束 | 「這個 Session 的憑證已失效（Session 已結束）。看板上的紀錄需要由人補上。」 |
| 401（token 無效） | 同上，不區分——區分等於給探測者一個信號 |
| 403／scope 不足（例如試圖勾 gate） | 「Review Gate 的核准必須由人在平台上完成；Agent 憑證沒有這個權限。」 |
| 409 版本衝突 | 「這張卡剛被別人改過。用 `cliora task get <ref>` 看目前的狀態再試一次。」 |
| 409 相依未滿足 | 「TASK-3、TASK-7 尚未完成，這張卡還不能進 implementing。」 |

**每一條都要說出下一步。** 這是這個 repo 對錯誤訊息的既有標準
（`error_catalog.py` 的每一條都有），CLI 不例外。

### 2.5 沒有 `cliora task approve`

**刻意沒有這個子命令。** 即使 API 會拒絕，一個存在的子命令會讓 Agent 去試，
而試了會得到一個 403 與一段它要自己解讀的訊息。

不過**要有一條測試**：直接對 gate 端點發請求（繞過 CLI）會被拒（`00-…md` 判準 6）。
CLI 不提供不等於路徑不存在，兩者都要成立。

## 3. 輸出格式

預設人類可讀（表格），`--json` 給結構化輸出。

**`--json` 從第一天就有**：M5（Agent 提交的資料有多少比例不合 schema）要量的東西，
以及 V2.4 決定 MCP 做不做的判準之一，都依賴 Agent 能拿到結構化資料。

## 4. 測試

| 層 | 覆蓋 |
|---|---|
| Go 單元 | argv[0] 分派；往上找 `.cliora/` 的四種版面（cwd 就是 workspace／在子目錄／多組 session／沒有） |
| Go 單元 | 四個子命令的參數解析與 exit code |
| Go 單元 | **離線**：撥號失敗 → 那兩句訊息逐字比對 ＋ exit code 2；`context show` 在同一情況下成功 |
| Go 整合 | 對一個真的 Central（`run-stack.sh`）跑完四個子命令；`task update` 之後看板 API 讀得到新 stage |
| 安裝 | symlink 建立、已存在指向別處時不覆寫、0.7.0→0.8.0 升級後啟動時補建 |
| E2E | 判準 5：Session 裡執行 `task update` → 看板即時更新 → 時間軸 `actor_kind = agent` |
