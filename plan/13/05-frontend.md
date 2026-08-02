# 05 — 前端（`WF-07`、`WF-08`）

---

## 1. 三個入口，一條程式路徑（`WF-07`）

新增 `frontend/src/composables/useImageDrop.ts`，由
`SessionWorkspaceView.vue` 掛在 CLI 終端機面板上。三個入口都收斂到同一個
`submit(file: File)`：

| 入口 | 事件 | 注意 |
|---|---|---|
| 貼上 | 終端機宿主元素的 `paste`（**capture** 階段） | 只在 `clipboardData.files.length > 0` 時 `preventDefault()` 並接手。**沒有檔案時一律放行給 xterm.js** —— 一般文字貼上是每天都在用的功能，弄壞它比沒有圖片投放糟糕得多 |
| 拖放 | 面板的 `dragover`／`drop` | `dragover` 要 `preventDefault()` 才會觸發 `drop`；拖放時面板顯示一層虛線邊框的落點提示 |
| 挑檔 | 工具列按鈕 → 隱藏的 `<input type="file" accept="image/png,image/jpeg,image/gif,image/webp">` | 有鍵盤可及性，也是三個入口裡唯一在觸控裝置上可用的 |

`WF-01` 第 2 項要先量 xterm.js 5.5.0 對含 `clipboardData.files` 的 paste 事件的實際行為
（它自己有 paste 處理），再決定攔截點是宿主元素還是 `textarea.xterm-helper-textarea`。

### 1.1 `submit(file)` 的順序

1. **前端預檢**：型別在四種之內、大小 ≤ 4 MiB。不過的話直接顯示訊息，不發請求 —— 
   使用者拖了一個 20 MiB 的 PSD 進來，不需要先傳 20 MiB 才知道不行。
2. 產生 `URL.createObjectURL(file)` 當縮圖，顯示在終端機上方的一條上傳列。
3. `POST /api/sessions/{id}/files/images`，`Content-Type` 用 `file.type`，body 是 `file`。
   顯示進度（`XMLHttpRequest.upload.onprogress`；`fetch` 沒有上傳進度）。
4. 成功 → §1.2 插入路徑，上傳列變成「已加入：`<原始檔名>` → `<相對路徑>`」，
   附縮圖與一顆「複製路徑」按鈕，10 秒後自動收起。
5. 失敗 → 上傳列顯示對應文案（§1.3），保留縮圖與一顆「重試」。

**`URL.revokeObjectURL` 一定要呼叫**：在上傳列收起時、以及 `onScopeDispose` 時。
一張沒有 revoke 的 4 MiB blob 會活到分頁關閉為止，而使用者可能一天丟幾十張。

### 1.2 路徑怎麼進到終端機

```ts
// writer only; the server enforces this too (useTerminalSession.ts:231).
terminal.typeText(`${path} `);
```

`useTerminalSession` 新增一個 `typeText(text: string)`，內部就是既有 `onData` 那條路徑
用的 `socket.send(new TextEncoder().encode(text))`，同樣的 writer 檢查。

- **尾隨一個空白，不送 Enter**（`00-…md` D6）。使用者通常還要接著打「這張圖裡的錯誤是什麼」。
- 路徑字元集是 `[A-Za-z0-9._/-]`（daemon 產生，`03-…md` §1），不需要跳脫。
  即使如此，`typeText` 要拒絕含控制字元的輸入 —— 它是一個「往終端機打字」的公開函式，
  下一個使用它的人不會知道路徑是誰產生的。
- 送出後 `terminal.focus()`，讓使用者可以直接接著打字。

### 1.3 失敗文案（對應 `04-…md` §2.3 的錯誤碼）

| Code | 文案 | 下一步 |
|---|---|---|
| `FILE_UPLOAD_TOO_LARGE` | 圖片超過 4 MiB 上限 | 請壓縮後再試 |
| `FILE_UPLOAD_UNSUPPORTED_TYPE` | 僅支援 PNG／JPEG／GIF／WebP | （若是 SVG）SVG 不受支援 |
| `FILE_UPLOAD_QUOTA_EXCEEDED` | 這個 Session 的圖片用量已達上限 | 請在檔案樹的 `.cliora/uploads/` 刪除不需要的圖片 |
| `FILE_UPLOAD_FAILED` | 節點寫入失敗 | 請通知管理者檢查節點磁碟空間 |
| `FILE_UPLOAD_DISABLED` | 這個節點停用了圖片投放 | （正常情況看不到，因為入口會被隱藏） |
| 403 | 沒有投放圖片的權限 | — |

### 1.4 入口的顯示條件

三個條件同時成立才顯示：`node.image_upload === true`（D8）、
使用者持有 `file.upload`、`terminal.role === "writer"`。

不成立時**不顯示**而不是 disable —— 一顆永遠按不下去的按鈕，
使用者會花時間去猜為什麼。唯一的例外是 writer 條件：
那是暫時的，所以顯示為 disabled 並附 title「取得寫入權後可投放圖片」，
與既有的接管（takeover）提示放在一起。

---

## 2. 預覽否決文案與唯讀標示（`WF-08`）

### 2.1 `PreviewDenied.vue` 的 `REASONS` 新增一項

```ts
unsupported_encoding: "檔案不是 UTF-8 編碼（例如 Big5、GBK、UTF-16）",
```

並且 `FILE_BINARY` 這個 case 要依 `reason` 分岔成兩種畫面
（今天它只有一種，寫死「偵測為二進位內容」）：

| reason | 標題 | 說明 | 下一步 |
|---|---|---|---|
| （無／`binary`） | 不支援預覽此檔案 | 偵測為二進位內容（`mime`），大小、修改時間 | 請在 Node 上以終端機檢視 |
| `unsupported_encoding` | 無法以 UTF-8 顯示此檔案 | 檔案看起來是文字，但不是 UTF-8 編碼 | 請在 Node 上以 `iconv` 轉為 UTF-8，或以終端機檢視 |

這兩件事對使用者的下一步不同 —— 前者是「別看了」，後者是「轉個編碼就看得到」。
今天把它們講成同一句話，是使用者說「純文字檔被當成 binary」時的一部分感受。

### 2.2 「唯讀」標示的誠實化（D19）

- `PreviewPane.vue:69` 的「唯讀」標示**保留**（預覽確實不可編輯），
  但 `aria-label` 從「唯讀預覽」明確化為「此預覽為唯讀，不可編輯」。
- 檔案樹在 `.cliora/` 這個節點旁加一個小標記「平台寫入」，
  hover 說明「圖片投放會寫入此目錄，7 天後自動清除」。
  這是使用者唯一會看到「工作區不再是完全唯讀」的地方，所以它必須存在。
- 全域搜尋 `唯讀` 與 `read-only` 的每一處命中都要重讀一次，
  判斷它講的是「預覽不可編輯」（留著）還是「工作區不可寫入」（要改）。
  已知至少涵蓋 `PreviewPane.vue`、`docs/p3-report.md`、ADR 0015、
  `.agent/skills/cliora-project-context/SKILL.md`。

### 2.3 檔案樹的刷新

上傳成功後，若檔案樹目前展開的目錄包含 `.cliora/uploads/<今天>`，觸發一次該目錄的刷新
（`useFileTree` 既有的 refresh 能力，`FR-FILE-006`）。
不展開的話什麼都不做 —— 不要為了顯示一張圖而自動展開使用者沒有打開的目錄。

---

## 3. 測試（Vitest）

| 測試 | 內容 |
|---|---|
| `useImageDrop.test.ts` | 三個入口都呼叫同一個 `submit`；`paste` 在沒有 files 時**不** `preventDefault`；型別／大小預檢；`revokeObjectURL` 有被呼叫 |
| `useTerminalSession.test.ts` | `typeText` 在 viewer 角色下不送出；含控制字元的輸入被拒；writer 下送出的位元組正確 |
| `PreviewDenied.test.ts` | `FILE_BINARY` × `reason=unsupported_encoding` 顯示編碼文案而非二進位文案 |
| `SessionWorkspaceView` | 三個顯示條件的組合（節點停用／無權限／viewer）各自的呈現 |
