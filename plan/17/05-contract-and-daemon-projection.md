# 05 — Contract v1.10.0 與 daemon 投影（`TK-07`）

**這是本期偏離上游規劃最遠的一張票**，理由在 `00-…md` D1。這裡只做設計。

## 1. 為什麼不能用既有的 `filesystem.store`

兩個各自獨立的阻擋，都在程式碼裡：

```go
// daemon/internal/files/store_policy.go:83
if verb == VerbStore && (rel == clioraDir || strings.HasPrefix(rel, clioraDir+"/")) {
    return "platform_owned"
}
```

```go
// daemon/internal/files/store.go 步驟 6
// The destination directory must already exist and be a real directory.
```

第一條讓 `.cliora/` 底下一律拒絕；第二條讓 `.cliora/context/` 這個目錄
**沒有任何協定訊息可以把它建出來**。

而同一份檔案裡的 `Verb` 型別註解已經寫好了正解：

> `Verb` identifies which operation is being judged. It exists so that a second write verb
> cannot quietly inherit the answers below — **the `.cliora/` rules in particular are
> per-verb**.

所以：**新增一個 verb，不放寬既有那個。**

## 2. Contract v1.10.0

### 2.1 兩個新訊息

```text
context.project     Central → daemon
{
  "session_id": uuid,
  "process_version": string,            ← 決定 process/ 的目錄名
  "files": [
    {"path": ".cliora/context/<sid>.md", "mode": "0600", "data": <base64>},
    {"path": ".cliora/context/<sid>.token", "mode": "0600", "data": <base64>},
    {"path": ".cliora/process/2026.08-1/kanban.md", "mode": "0600", "data": <base64>}
  ]
}

context.projected   daemon → Central
{
  "session_id": uuid,
  "written": [".cliora/context/<sid>.md", …],
  "skipped": [".cliora/process/2026.08-1/kanban.md"],   ← FILE_EXISTS，視為成功
  "bytes": integer
}
```

schema 的硬約束（**寫在 schema 裡，不是只寫在 daemon 裡**）：

| 約束 | 值 |
|---|---|
| `path` 樣式 | `^\.cliora/(context|process|reference)/[^/\x00-\x1f]+(/[^/\x00-\x1f]+)*$` |
| 檔案數 | 1–32 |
| 單檔 base64 長度 | ≤ 87384（64 KiB 的 base64 形式） |
| 訊息總大小 | 沿用既有的 large-frame 上限（`codec.go` 的 `LargeFrameTypes`，`context.project` 加入該集合） |
| `mode` | 只允許 `"0600"`（一個值的 enum：欄位存在是為了讓它在日後可能需要 0700 時不必改 schema，但現在只有一個合法值） |
| `additionalProperties` | `false`，全部物件 |

**`..` 在樣式層就不可表示**（沿用 `filesystem-store.schema.json` 的既有做法：
protection moves from "there is no field" to "the field cannot hold a path"）。

### 2.2 Fixtures

valid ×3：一般投影、只有流程檔、只有情境包。
invalid ×8，每一條對應一個真的會被利用的形狀：

```text
context-project-outside-cliora.json        path 不在 .cliora/ 底下
context-project-parent-escape.json         .cliora/context/../../etc/x
context-project-uploads.json               .cliora/uploads/x  ← 使用者的地盤，禁區
context-project-gitignore.json             .cliora/.gitignore ← 平台不覆寫它
context-project-too-many-files.json        33 個
context-project-oversize.json              單檔超過 64 KiB
context-project-bad-mode.json              "0644"
context-project-extra-field.json           additionalProperties
```

第三與第四條是本期特有的：`.cliora/uploads/` 與 `.cliora/.gitignore` 是
image drop 的既有產物（`upload.go:29-38`），投影**不得碰它們**。

**每一份 fixture 都要登記進 `contracts/v1/fixtures/manifest.json`**——
那份 manifest 是三個語言的 accept／reject 交叉來源，漏登記的 fixture 等於沒有測到。

### 2.3 `node.register` 加一個能力旗標

```json
"context_projection": {"type": "boolean"}
```

沿用 `image_upload`／`file_upload` 的既有形狀。舊 daemon 不送這個欄位 → Central 視為 `false`：

- Session 照常建立、照常運作。
- **不送 `context.project`**（送了會被舊 daemon 當未知型別拒絕，那是一個沒有意義的往返）。
- Session 詳情與 Node 詳情顯示：
  「此 node 的 agentd 需升級到 0.8.0 才能送出任務情境。[前往更新]」
  ——`research/02/08` §9 要求的可行動訊息，不是 500，也不是讓 node 從清單消失。

### 2.4 既有訊息一個位元組都不改

`GATE-TK-CONTRACT-ADDITIVE`（`08-…md` §4）以 `TK-00` 的逐檔 sha256 斷言它。
`contracts/CHANGELOG.md` 加一節 `## 1.10.0 — (compatible)`。

## 3. daemon 0.8.0：`VerbProject`

### 3.1 政策

在 `store_policy.go` 加第二個 verb，**不修改 `VerbStore` 的任何一行**：

```go
const VerbProject Verb = iota + 1

// ProjectableClassification：VerbProject 的可寫集合與 VerbStore 互斥。
```

| 檢查 | 規則 |
|---|---|
| 前綴 | 必須是 `.cliora/context/`、`.cliora/process/`、`.cliora/reference/` 之一 |
| `.cliora/uploads/`、`.cliora/.gitignore` | **拒絕**（`platform_owned` 的鏡像：對這個 verb 而言那才是別人的地盤） |
| `.git` 任一段 | 拒絕（沿用 `classifyGitPath`，直接呼叫不重寫） |
| 敏感檔分類 | **不套用**——投影的內容是平台自己產生的，而 `.token` 這個副檔名正是敏感檔政策會擋的東西。這一條要在程式碼註解裡寫明為什麼是例外 |
| 檔名 | 沿用 `classifyFilename`（單一路徑段、無控制字元、≤255 bytes） |

### 3.2 寫入

```text
1. LstatIn(".cliora")      ← 若存在且不是目錄 → 拒絕（與 ensureUploadDir 同一條防 symlink 的理由）
2. MkdirAllIn(dir, 0o700)  ← 這是新 verb 存在的第二個理由
3. 確保 .cliora/.gitignore 存在（不存在才建，內容 "*\n"）  ← 重用 ensureUploadDir 的既有函式
4. CreateExclusive(rel, 0o600) → 寫入 → Sync → Chmod
5. ErrExists → 記為 skipped，不是錯誤
```

第 3 步是重用而不是複製：`upload.go` 已經有那段邏輯，
**兩份 gitignore 建立邏輯會在某次修改時分歧**。

第 5 步是 `research/02/03` TK-05 規則 2 的落點：流程檔以內容版本號當目錄名，
同版本已存在就跳過。**不得因此想加 `overwrite`**——那會一次推翻 ADR 0024／0026 的整個姿態。

### 3.3 `session.start` 之後、投影之前

daemon 端**不需要**知道 Session 的內容：`context.project` 帶 `session_id`，
daemon 用既有的 session→workspace 解析（與 `filesystem.store` 同一條）拿到 `os.Root`。
所以本期**不改 session 生命週期的任何一行**。

## 4. `.cliora/` 的最終版面

```text
<workspace>/.cliora/
  .gitignore                      "*"        ← image drop 已建立；投影只在缺少時補
  uploads/<day>/…                            ← image drop 的地盤，投影不碰
  context/<session_id>.md         0600       ← 情境包，≤ 4 KB（D8）
  context/<session_id>.token      0600       ← Session token
  process/<version>/*.md          0600       ← 六車道、DoR、Gates、DoD 的說明
  reference/*.md                  0600       ← design-system 等（本期只在 Project 有設定時）
```

### 4.1 情境包的內容（D8）

Always Included，目標 **≤ 4 KB**，**第一段就是怎麼回報進度**：

```text
# TASK-12 Workspace File Tree API

## 你可以怎麼回報進度（三行）
  cliora task get TASK-12               看這張卡的完整內容
  cliora task update TASK-12 --stage implementing --note "開始"
  平台連不上時這些指令會失敗，但你的工作不受影響——繼續做，恢復後再執行一次。

## 目標／範圍／非目標
## 驗收標準（逐項，含目前結果）
## 允許變更的檔案 / 不得觸碰
## 驗證指令
## 風險等級
## 相依任務與其狀態
## 延伸閱讀（只給路徑，自己用 Read/rg 讀）
  .cliora/process/<version>/kanban.md
  .cliora/reference/…
```

**「怎麼回報」放第一段是刻意的**：M2（Agent 實際使用 CLI 的比例）是內化路線的核心假設，
而一段放在檔尾的說明等於沒放。

**超過 4 KB 時的行為先定好**（`00-…md` §5 風險表）：保留 AC 全文與第一段，
截斷「延伸閱讀」與描述類區塊，檔尾寫
「已省略 N 項，用 `cliora task get TASK-12` 取完整內容」。**不靜默截斷。**

### 4.2 `process_version` 的產生

`process_definitions.version` 是**內容版本號**：內容改變時改變、相同時穩定。
實作為 `<yyyy.mm>-<n>` 的人工版本號 ＋ 一條測試斷言
「種子內容的 sha256 改變時 `version` 必須也改變」。

用內容雜湊當目錄名也可以，但那會讓目錄名不可讀，而它會出現在情境包的路徑裡給 Agent 看。

## 5. 保留期與清理（ADR 0024 W2）

| 儲存 | 誰清 | 何時 |
|---|---|---|
| `.cliora/context/*` | **daemon** | 30 天（`mtime`），可由 daemon config 覆寫 |
| `.cliora/process/<version>/*` | **daemon** | 30 天**且**不是目前生效的版本 |
| `.cliora/reference/*` | **daemon** | 30 天 |
| `.cliora/uploads/*` | **不碰** | image drop 的既有規則（ADR 0024） |
| `.cliora/.gitignore` | **不碰** | 使用者可能有自己的內容 |

實作沿用 `shell_reaper` 的形狀：daemon 內一個週期性迴圈（預設每 6 小時），
只走訪三個子樹，路徑白名單寫死。

**一條測試**：清理跑完之後 `.cliora/uploads/` 與 `.cliora/.gitignore` 仍在
（`00-…md` §5 風險表的那一條）。

**保留期到期後 Session 仍可運作**（`research/02/10` §2.2 條件 10）：
過期只是少了投影，不是壞掉——`cliora task update` 照常（它連的是 Central），
只有 `cliora context show` 會說「情境包已過期，請在平台上重新投影」。

## 6. 敏感檔分類要加 `.token`

`.cliora/context/*.token` 落在使用者的工作目錄裡，而既有的檔案瀏覽面**讀得到它**。
所以 `TK-07` 要在 daemon 的敏感檔政策裡加一條：`.cliora/**/*.token` 分類為 `sensitive`，
預覽被拒、搜尋不命中。

這與 `.env`／私鑰走同一條既有路徑（ADR 0015），**不新增機制**。
有一條測試：`filesystem.read` 對 token 檔回 `FILE_DENIED` ＋ `sensitive`，
且該次拒絕依 SEC-006 寫一筆 audit。

## 7. 測試

| 層 | 覆蓋 |
|---|---|
| Contract | 3 valid ＋ 8 invalid fixtures；三個語言的 validator 都跑（`make contract`） |
| Daemon 單元 | `VerbStore` 寫 `.cliora/` 仍被拒（**迴歸**）；`VerbProject` 的六條政策各一條；mkdir 深度；`FILE_EXISTS` → skipped |
| Daemon 單元 | 清理迴圈：三個子樹過期被刪、`uploads/`／`.gitignore` 未被碰、生效版本的 process 目錄不刪 |
| Daemon 整合 | 真實 workspace：投影 → `git status --porcelain` 為空 → 第二次投影同版本 process 被 skip |
| Daemon 整合 | symlink 攻擊：`.cliora` 指向 root 外 → 拒絕 |
| Central | 舊 daemon（無 `context_projection`）→ 不送訊息、Session 正常、UI 有可行動訊息 |
| Central | 投影逾時／失敗 → Session 仍然 `running`，activity 有一筆，UI 顯示重試按鈕（D8） |
