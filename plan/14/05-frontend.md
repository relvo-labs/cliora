# 05 — 前端（`WE-07`、`WE-08`、`WE-09`）

前端是本期使用者唯一會看到的部分，也是本期最容易安靜地弄壞東西的地方：
daemon 的錯誤會噴錯誤碼，編輯器偷改內容不會。

---

## 1. 編輯模式（`WE-07`）

### 1.1 `useMonacoModel` 的擴充

目前它是「唯讀預覽的生命週期擁有者」。本期讓它同時擁有 **dirty 狀態**，
而不是在 `PreviewPane.vue` 裡另外放一份 —— 一個 model 的 dirty 狀態
與那個 model 的 dispose 必須由同一個地方管，否則就會有「dispose 掉一個 dirty model」
這種資料遺失。

新增的狀態與方法：

```ts
const mode = ref<"read" | "edit">("read");
const dirty = ref(false);
const revision = ref<string | null>(null);   // 從 FileContent 帶進來
const saving = ref(false);
const conflict = ref<null | { serverRevision?: string }>(null);

function enterEdit(): boolean;      // 需要 canEdit；設 readOnly:false
function leaveEdit(discard: boolean): boolean;
async function save(): Promise<SaveOutcome>;
```

**`PreviewState` 不新增值。** `mode` 與 `dirty` 是正交的：一個檔案可以是
`ready` × `edit` × `dirty`。把它們塞進同一個 enum 會產生
`ready`／`editing`／`editing-dirty`／`saving`／`conflict` 五個值，
而其中三個的差別只在 header 上顯示什麼字。

### 1.2 D15 的五項設定，逐項落在哪

| 要防的偷改 | 落在哪 | 驗收 |
|---|---|---|
| 行尾空白被吃掉 | `editor.updateOptions({ trimAutoWhitespace: false })` | 往返測試（行尾有空白的檔案） |
| 結尾自動補換行 | Monaco 預設不補；**不要**開 `insertFinalNewline` | 往返測試（無結尾換行的檔案） |
| EOL 被正規化成 LF | 建立 model 後 `model.setEOL()` 依內容偵測（含 `\r\n` 就用 CRLF）。Monaco 的 `createModel` 會依平台猜 | 往返測試（CRLF 檔案） |
| BOM 被吞掉或重複 | 內容字串原樣進 model（`﻿` 就是第一個字元），存檔時原樣送出。**不要**在任何一層 strip | 往返測試（BOM 檔案） |
| 縮排被轉換 | `detectIndentation` 只影響**新輸入**的縮排；不呼叫 `formatDocument`、不裝任何 formatter | 往返測試（tab 縮排的檔案） |

**這五項不靠設定清單保證，靠 `FR-FILE-010.AC-04` 的往返測試保證。**
設定清單會被下一個人動（「加一個 formatter 應該很方便」），測試不會。
往返測試要在**前端**也有一份（Vitest：把五個 fixture 字串放進 model，
不做任何編輯，取 `getValue()`，斷言與輸入完全相同）——
daemon 那一份（`02-…md` §8）測的是寫入面，這一份測的是編輯器面，
而 D15 講的問題只在編輯器面。

### 1.3 儲存

```
1. dirty 為假 → 不發請求（沒有東西要存）
2. 送 PUT /files/content?path=…，If-Match: "<revision>"，body 是 model.getValue()
3. 成功 → revision 換成回應的新值、dirty 清掉、顯示「已儲存 HH:mm:ss」
4. 412 → conflict.value = {...}，dirty 保持為真，畫面切到 §1.4
5. 其他錯誤 → 顯示錯誤，dirty 保持為真，內容一個字都不動
```

第 5 步的「內容一個字都不動」要寫成註解。一個存檔失敗之後把使用者的編輯
回捲成伺服器版本的編輯器，會讓人失去剛剛打的東西 —— 而那正是他還沒存起來的東西。

**觸發**：`Ctrl+S`／`Cmd+S`（在編輯器內攔截並 `preventDefault`，
否則是瀏覽器的「儲存網頁」）＋ header 的「儲存」按鈕。
`Ctrl+S` 只在 `mode === "edit"` 時攔截；唯讀時放行給瀏覽器。

### 1.4 衝突（412）

畫面：一條橫幅蓋在編輯器上方（不是 modal —— 使用者需要看得到自己的內容）：

> **這個檔案已在節點上被修改。** 你的修改還在，但不能直接覆寫。
> 〔重新載入（放棄我的修改）〕 〔另存為新檔…〕 〔取消〕

- **重新載入**：`openFile(path, { force: true })`，dirty 清掉。要二次確認。
- **另存為新檔**：開檔名輸入框，預設是 `<原檔名>.conflict-<HHmmss><副檔名>`，
  送 `PUT` 帶 `If-None-Match: *`。成功後**切到新檔**並清掉衝突。
- **取消**：留在原地。使用者可能想先把內容複製走。

**沒有 diff、沒有合併**（`00-…md` D14）。橫幅的措辭要避免「錯誤」兩個字：
CLI 一直在改檔案，這是日常情境。

### 1.5 `PreviewPane.vue`

header 從「唯讀」一個標籤變成三個狀態：

| 狀態 | 標籤 | 工具列 |
|---|---|---|
| `read` | `唯讀` | 既有五顆（搜尋／換行／行號／複製／重新整理）＋〔編輯〕 |
| `edit` 且未修改 | `編輯中` | 同上，「編輯」變〔結束編輯〕，多〔儲存〕（disabled） |
| `edit` 且 dirty | `未儲存` + 一個圓點 | 〔儲存〕enabled，〔重新整理〕**disabled** |

- 〔編輯〕只在三個條件同時成立時出現：`capabilities.can_edit_files === true`、
  `node.file_editing === true`、`preview.revision !== null`。
  第三個條件涵蓋了「舊 daemon 不送 revision」與「這是一個否決畫面」兩種情況。
- dirty 時〔重新整理〕要 disabled 而不是隱藏：使用者會想按它，
  disabled + title「請先儲存或結束編輯」告訴他為什麼不行。
- `aria-label` 從「唯讀預覽」改為「此預覽為唯讀，可切換為編輯模式」/
  「編輯模式，尚未儲存」，隨狀態變。

### 1.6 三個必須擋住的離開路徑（`00-…md` D13）

| 路徑 | 處置 |
|---|---|
| 在檔案樹點另一個檔案 | `PreviewPane` 的 `watch(props.relPath)` 之前先問。實作上由 `SessionWorkspaceView` 攔截 `onOpen`，dirty 時開確認框，選「儲存」或「捨棄」才真的換 |
| 切換 session／離開路由 | `onBeforeRouteLeave` ＋ `useMonacoModel` 的 `watch(sessionId)` **不再無條件 `disposeAll()`** |
| 關閉分頁 | `beforeunload`，只在 dirty 時註冊，離開編輯模式時解除 |

第二列是一個既有行為的變更，要特別小心：
`useMonacoModel` 目前 `watch(options.sessionId, () => disposeAll())`。
dirty 時 disposeAll 就是資料遺失。改為：dirty 時先發出一個事件讓 view 處理，
view 沒有處理的話**仍然 dispose**（不能讓一個沒人接的 promise 卡住 session 切換），
但要 `console.warn` 並且有一條測試斷言 view 有接。

**LRU 逐出**：因為只允許一個 dirty 檔案，而 dirty 檔案永遠是當前 attach 的那一個，
而 `evictIfNeeded` 本來就跳過 attached model —— **所以不需要改 eviction**。
這一點要寫成註解，否則下一個人會補一個多餘的 dirty 檢查，
然後下下一個人會以為多檔 dirty 是被支援的。

---

## 2. 檔案樹的四個動詞（`WE-08`）

### 2.1 入口

| 動作 | 入口 | 對象 |
|---|---|---|
| 新增檔案 | 工具列〔新增檔案〕（在目前目錄）＋目錄列的 context menu | — |
| 新增資料夾 | 工具列〔新增資料夾〕＋目錄列的 context menu | — |
| 重新命名 | 列的 context menu ＋ `F2` | 檔案與資料夾 |
| 刪除 | 列的 context menu ＋ `Delete` 鍵 | 檔案與資料夾 |

context menu 用一個小型的 `FileRowMenu.vue`，由 `⋯` 按鈕與右鍵同時觸發。
**右鍵不是唯一入口**：那對鍵盤與觸控使用者等於沒有這個功能。
`⋯` 按鈕在 hover 與 focus 時出現，`aria-haspopup="menu"`。

`Delete` 鍵要**只在檔案或資料夾列有 focus 且不在輸入框內**時作用，
並且**永遠先開確認框** —— 一個直接刪除的 `Delete` 鍵在一棵用方向鍵瀏覽的樹上是災難，
而在它可以刪掉整個資料夾之後是更大的災難。

### 2.2 四個對話框

沿用專案既有的對話框體例（`SessionsView` 的終止確認）。

**新增檔案**：輸入框預設空白，label 顯示 `<目前目錄>/`，
即時驗證（不得為空、不得含 `/` 開頭、不得含控制字元、不得是 `.` 或 `..`）。
允許輸入含 `/` 的相對路徑（`sub/new.md`），並在下方即時顯示最終路徑
與一行「將建立 1 個新目錄」（若父目錄不存在）。

**重新命名**：輸入框預設是目前檔名，**選取範圍預設不含副檔名**
（`main.go` 選中 `main`）—— 這是每一個檔案總管的行為，不做的話每次都要手動選。
允許輸入含 `/` 的路徑以達成移動，此時顯示「將移動到 `<目錄>`」。

**新增資料夾**：與新增檔案同一個對話框元件，只差在送出的端點與成功後的行為
（不開啟編輯模式，只展開它）。同樣允許輸入含 `/` 的路徑一次建多層。

**刪除**：不需要打字確認，但內容依對象分三種。

*檔案：*

> 刪除 `notes.md`（4.2 KB）？
> 已刪除的檔案會保留在 `.cliora/trash/` 7 天，之後自動清除。

*資料夾：*

> 刪除資料夾 `src` 與其中的所有內容？
> 這一層有 12 個項目（子資料夾的內容也會一起刪除）。
> 整個資料夾會保留在 `.cliora/trash/` 7 天，可以整個還原。

**「這一層有 12 個項目」用的是前端已經載入的直屬項目數，並且要明說它只算一層。**
前端不知道遞迴總數（那要問節點），而**寫一個模糊的「以及其中所有內容」比
寫一個假裝精確的數字好**。真正的遞迴數字會在成功之後從回應的 `entries` 拿到，
成功訊息因此可以說「已移入回收桶（37 個項目）」。

*符號連結：*

> 這是一個符號連結。刪除後**無法**從回收桶還原。

（對應 `02-…md` §4.3 第 4 步那條刻意留下的縫。）

**刪除資料夾的按鈕要用 danger 樣式，而且不要是對話框的預設焦點。**
這是本期唯一一個「按錯一次就動到幾百個檔案」的動作，
不給它一個與其他確認框不同的視覺重量，就是把它當成一樣的東西。

### 2.3 動作之後

| 動作 | 刷新什麼 | 預覽怎麼辦 |
|---|---|---|
| 新增檔案 | 目標目錄（若父目錄是新建的，刷新最近的既有祖先） | 自動開啟新檔並進入編輯模式 |
| 新增資料夾 | 同上 | 不動；展開新資料夾 |
| 更名 | 來源與目的地兩個目錄 | 若被更名的是目前預覽的檔案，`relPath` 跟著換，不重新載入內容；若被更名的是預覽檔案的**祖先目錄**，同樣改寫 `relPath` 的前綴 |
| 刪除 | 該目錄；**刪資料夾時還要丟掉該路徑底下所有已快取的目錄**（`files` store 的 `dirs` 是扁平 map，不清會留下指向已刪路徑的殘骸） | 若被刪的（或它的祖先）是目前預覽的檔案，關閉預覽（`preview.close()`） |

兩格值得注意：

- **「不重新載入內容」**：更名不改內容也不改 revision，
  重新載入只是多一次往返，而且會把捲動位置歸零。
- **刪資料夾要清 store 的子樹快取**。`useFilesStore.dirs` 用完整路徑當 key，
  沒有父子關係，所以刪掉 `src` 之後 `src/utils` 那一筆會一直留著；
  下次展開同名新資料夾時會先閃出舊內容。加一個
  `dropSubtree(path)`，並且用測試釘住。

### 2.4 未儲存的檔案在被刪的資料夾裡

D13 保證同一時間只有一個 dirty 檔案，但它可能正好在使用者要刪的資料夾底下。
規則：**刪除前檢查 dirty 檔案的路徑是否在目標之下，是的話先走 §1.6 的
「儲存／捨棄／取消」流程**，取消就不刪。

不做這個檢查的話，刪除會成功、dirty buffer 會留在畫面上、按存檔會得到
404 或（更糟）在回收桶外重新建立那個檔案。這是本期最隱晦的一個組合，
所以它要有自己的測試。

### 2.5 錯誤文案

| Code | 文案 | 下一步 |
|---|---|---|
| `FILE_EXISTS` | 已經有一個同名的項目 | 換一個名字 |
| `FILE_REVISION_MISMATCH`（檔案） | 這個檔案已在節點上被修改 | 請先重新整理檔案樹 |
| `FILE_REVISION_MISMATCH`（資料夾） | 這個資料夾的內容已經改變 | 請先重新整理，確認裡面是你以為的東西再刪 |
| `FILE_DENIED` / `git_metadata` | 不能修改 git 的內部檔案 | — |
| `FILE_DENIED` / `platform_owned` | 這是平台管理的目錄 | — |
| `FILE_DENIED` / `dotenv`｜`private_key`｜… | 這是受保護的敏感檔案 | 請在節點上以終端機處理 |
| `FILE_DENIED` / `excluded_dir` | 這個目錄由工具管理，不開放編輯 | — |
| `FILE_DENIED` / `workspace_root` | 不能刪除或更名工作區本身 | — |
| `FILE_DIRECTORY_CONTAINS_PROTECTED` | 這個資料夾裡有不能被平台改動的項目 | **要把伺服器回傳的那一個路徑顯示出來**（例如「`sub/.git` 受保護」），否則使用者只能猜 |
| `FILE_DIRECTORY_TOO_LARGE` | 這個資料夾太大，無法從瀏覽器操作 | 請在節點上以終端機處理 |
| `FILE_TRASH_UNAVAILABLE` | 無法建立備份，因此沒有刪除 | 請在節點上以終端機刪除 |
| `FILE_IS_DIRECTORY` | 這是一個資料夾，不能寫入內容 | （前端 bug，使用者不該看到） |
| 403 | 沒有編輯檔案的權限 | — |

**每一列都要有下一步或明確的「—」。** 沒有下一步的錯誤訊息會被使用者當成 bug 回報。

---

## 3. 「唯讀」敘事與能力旗標（`WE-09`）

### 3.1 第二次全域重讀

`00-…md` D19。搜尋 `唯讀`／`read-only`／`readOnly` 的每一處命中，
判斷它講的是哪一個，這次有**三**種答案（p13 只有兩種）：

| 它在講 | 處置 | 已知位置 |
|---|---|---|
| 工作區不可寫 | 已於 p13 改完，不應該還有 | — |
| 預覽這個模式不可編輯 | **仍然為真**，但要加上「預設」二字 | `PreviewPane.vue`、`useMonacoModel` 的檔頭註解、`monaco/setup.ts` |
| Viewer 這個角色不可寫 | **完全為真，一個字都不用改** | `rbac.py`、ADR 0015 RBAC 段、`docs/p3-report.md` |

第三種是本期的好消息：Viewer 三次改版下來一次都沒有拿到寫入權，
所以所有講 Viewer 的敘述都不用動。這一點要寫進安全審查（`06-…md` §5 第 6 題）。

### 3.2 `.cliora/` 與回收桶在檔案樹的呈現

`plan/13/05-…md` §2.2 計畫在 `.cliora/` 旁加一個「平台寫入」標記，
但**它沒有被實作**（已核對：`frontend/src/components/file/` 底下沒有任何
`.cliora` 或「平台寫入」的字串，而 `plan/13/07-…md` 把 `WF-08` 記為完成時
只列了 `PreviewDenied.vue` 的改動）。所以本期要做的是**新增**而不是擴充，
並且要在 `plan/13` 的差異表補一列 —— 一個被記成完成卻沒有落地的項目，
留著會讓下一份狀態表不可信。

標記加在 `.cliora/` 這個目錄列上，hover 說明：

> 平台管理的目錄。`uploads/` 是圖片投放，`trash/` 是已刪除檔案的 7 天備份。

`trash/` 底下的列（檔案與資料夾都一樣）只顯示〔還原到…〕與〔刪除〕。
**〔還原到…〕送出的就是 rename 請求**（`00-…md` D7）——
這是本期唯一一處「同一個 API 用兩個名字呈現」，理由是使用者在那個情境下
想的不是「改名」而是「拿回來」。

還原對話框的預設目的地要**從稽核以外的地方猜**：trash 的檔名是
`<ULID>-<原本的 base name>`，所以預設值填 base name、目錄預設是工作區根，
並附一句「原始位置請參考稽核紀錄」。這個誠實勝過猜錯 ——
`03-…md` §1 明講了 trash 的頂層是平的，原始路徑只在稽核裡。

### 3.3 能力旗標串接

`SessionWorkspaceView.vue` 沿用 `canUploadImages` 的既有形狀：

```ts
// Server-derived, both of them. The browser must not re-derive RBAC
// (ADR 0016) and must not guess the node's posture (ADR 0024 W4).
const canEditFiles = computed(
  () => capabilities.value?.can_edit_files === true && node.value?.file_editing === true,
);
```

**不加 writer 條件**（`00-…md` D9）。這與圖片投放不同，
而不同的地方最容易被下一個人「順手統一」，所以要留一行註解說明為什麼。

不成立時**不顯示**入口而不是 disable，沿用 p13 的既有判準
（一顆永遠按不下去的按鈕，使用者會花時間猜為什麼）。

---

## 4. 測試（Vitest）

| 測試 | 內容 |
|---|---|
| `useMonacoModel.test.ts` | `enterEdit` 需要 canEdit；dirty 追蹤；**五種檔案的往返 `getValue()` 完全相同**（§1.2）；save 成功換 revision；412 保留內容與 dirty；save 失敗不動內容；session 切換時 dirty 有發事件 |
| `PreviewPane.test.ts` | 三種 header 狀態；dirty 時〔重新整理〕disabled；缺 revision 時不顯示〔編輯〕；`Ctrl+S` 只在編輯模式攔截 |
| `FileTree.test.ts`（擴充） | `F2`／`Delete` 只在檔案列且非輸入框時作用；`Delete` 一定先開確認；`⋯` 按鈕有鍵盤可及性 |
| `FileRowMenu.test.ts` | trash 底下的選單顯示〔還原到…〕而不是〔重新命名〕；資料夾列與檔案列的選單項目差異 |
| `useFileTree.test.ts`（擴充） | 四個動作之後刷新的目錄集合；更名時預覽路徑跟著換且不重新載入；更名祖先目錄時預覽路徑的前綴被改寫；**`dropSubtree` 在刪資料夾後清掉所有子路徑快取** |
| `FileTree.test.ts`（刪除資料夾） | 確認框顯示直屬項目數且明說只算一層；danger 樣式；不是預設焦點 |
| `SessionWorkspaceView.test.ts`（dirty × 刪資料夾） | dirty 檔案在被刪的資料夾底下時，先走儲存／捨棄／取消；取消則不送刪除請求 |
| `SessionWorkspaceView.test.ts`（擴充） | `can_edit_files` × `file_editing` 的四種組合；dirty 時切換檔案會被攔截 |
| `client.test.ts`（擴充） | precondition union 翻成正確的 header；`If-Match` 帶引號 |

**一條要特別寫的測試**：`can_edit_files` 為真但 `file_editing` 為假時，
入口不顯示 —— 這是「伺服器說可以、節點說不行」的組合，
而它在 p13 的圖片投放上已經有一條對應的測試，兩者要並列（同一個 describe），
讓下一個人一眼看到這是同一條規矩的兩個實例。
