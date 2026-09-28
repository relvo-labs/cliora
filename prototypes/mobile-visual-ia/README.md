# Cliora 行動視覺與資訊層級原型（#75）

一套資訊層級、三個視覺變體（A 克制編輯式／B 工程工作台式／**C 安靜操作式——2026-09-28 產品負責人選定，預設顯示**）的互動原型。
獨立 HTML／CSS／JavaScript，**不需要 npm install、不連任何服務**；所有資料是合成的，只存在記憶體。
設計說明、痛點地圖與建議在 [`plan/32/`](../../plan/32/README.md)。

## 查看

在 repository 根目錄：

```sh
python3 -m http.server 8080 --bind 127.0.0.1 --directory prototypes/mobile-visual-ia
```

開啟 `http://127.0.0.1:8080/`，用瀏覽器開發者工具切到手機尺寸（390×844 等）。完成後 Ctrl+C 停止。

頂部灰色虛線列是**原型控制**，不屬於任何變體：左邊選變體，右邊選情境。也可以用網址參數：

| 參數 | 值 | 用途 |
|---|---|---|
| `v` | `a`／`b`／`c` | 變體；省略時為 **C** |
| `s` | 情境 id（見下） | 直接進入某個狀態 |
| `shot` | `1` | 把原型控制列收成一行標籤（截圖用；仍標示「原型 · 合成資料」） |

情境 id：`list`、`list-empty`、`create`、`terminal`、`menu`、`viewer`、`viewer-locked`、`posture`、`shell`、
`reconnecting`、`disconnected`、`gap`、`exited`、`load-error`、`forbidden`、`activity`、`await`、`events-gap`、
`unsupported`、`files`、`preview`、`preview-denied`、`keyboard`。

## 自動檢查

```sh
# 任一有 Playwright 的 Python 環境；以 uv 為例（虛擬環境與快取放在 repository 外）
uv run --no-project --with playwright python prototypes/mobile-visual-ia/test_prototype.py \
  --chromium /absolute/path/to/chromium \
  --evidence-dir /path/outside/repo/evidence
```

省略 `--chromium` 則使用 Playwright 自己下載的 Chromium。測試會自行啟停本機 HTTP 伺服器。檢查內容：

- 360×800、390×844、430×932、844×390 與 200% zoom（195×422）× 3 變體 × 23 情境：無橫向溢出（終端、程式碼、麵包屑是明示的內部捲動區）。
- 同上四種尺寸：所有可見 button／input／select／tab ≥ 44×44 CSS px（單選鈕以其 label 計）。
- 每個詳情情境（直式與橫式）：Session 名稱、三格分開的狀態、「檔案」與「終端機」分頁都可見；posture、接管、重連、系統 shell 各自可辨。
- 鍵盤焦點可見（3px outline）；Escape 關閉 sheet 並把焦點還給開啟鈕；預覽 Escape 回到開啟的那一列。
- `prefers-reduced-motion: reduce` 下 sheet 動畫為 0s（C 平常是 0.18s）。
- token 區塊內 41 組文字／非文字配對達 4.5:1／3:1。
- `style.css` 的 token 區塊之外、`app.js`、`index.html` 沒有任何字面色值（規則同 `GATE-VR-NO-LITERAL-COLOR`）。
- 沒有真實資料特徵（家目錄、e-mail、IP、憑證樣式、外部 URL）；所有 Session／Node 名稱都是 `demo-*`。
- 沒有 page error、外部請求、API、WebSocket、localStorage／sessionStorage。
- C 方向（v0.2）：未帶 `v` 時預設 C；五種尺寸下終端與標頭不截斷、不互相遮擋（被截斷的標題帶全文 `title`，完整名稱另在 `⋯`）；
  CLI 的分隔線與輸入框隨寬度延伸；Viewer 看不到輸入框，C 在該位置放整寬「取得控制權」。

## 範圍與限制

- **這不是正式 Vue 元件**，也不是 xterm 或 Monaco：終端是 `<pre>`、預覽是 `<pre>`，顏色取自 pocket token 與 `plan/29/07` §1.2 的 ANSI 提案值。
  它能比較版面、層級與色彩用法；不能證明 xterm 渲染、IME、貼上、resize、reconnect、RBAC 或任何伺服器行為。
- 終端的合成輸出以「已依寬度換行」的樣子呈現，模擬一個已 fit 到欄數的 PTY；分隔線與輸入框用 CSS 畫到目前寬度，
  代表 CLI 依欄數重繪的結果。正式版這兩者都由 CLI 自己畫在 PTY 裡。
- **Viewer 沒有輸入框只在原型成立**：合成輸出停在提示框之前。正式版不得改寫或遮住 CLI 畫在輸出裡的輸入框（`plan/29/07` MS-19）；
  能做的是讓 Cliora 自己的輸入元件（MS-12）在 Viewer 時不存在，由接管列佔同一個位置（`plan/32/06` §1.1）。
- 「活動」分頁是**假說**：只出現在 `demo-docs-managed` 這個標示為受管的 Session，依賴 #73 的官方結構化事件；
  既有 Session 只有原生終端。沒有 composer、沒有批准按鈕（審批只在原生終端，#72）。對話輸入屬 #74。
- 建立、終止、接管、重連、附加圖片、預覽選單都**不會做任何事**：按下只顯示「原型…」說明或切換合成狀態。
- 鍵盤情境是用 CSS 變數模擬 320px 鍵盤；真實 `visualViewport` 變化時原型也會跟著縮，但這不是裝置證據。
- 圖示是為原型自繪的簡單 outline 線條；正式實作應使用 repository 既有的 `lucide-vue-next`。
- Chromium 模擬不是 iOS Safari 或 Android Chrome；VoiceOver／TalkBack、真實安全區、網址列收合都**未驗證**。
