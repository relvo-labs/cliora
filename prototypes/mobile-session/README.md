# Cliora 行動工作階段原型

這是一個整合式、僅使用合成資料的互動原型：採用已選定的 **A 版明亮／session-first** 方向，並把 C 版的檔案操作納入同一個已選工作階段。它不是第二套產品、正式 Vue 實作或服務驗證證據。

## 查看原型

在複製完成的儲存庫根目錄執行：

```sh
python3 -m http.server 8080 --bind 127.0.0.1 --directory prototypes/mobile-session
```

開啟 `http://127.0.0.1:8080/`；完成後以 Ctrl+C 停止伺服器。

## 可攜式測試與證據擷取

以下方式不依賴本次驗證主機的既有虛擬環境。請在複製完成的儲存庫根目錄執行，並把虛擬環境與證據目錄放在儲存庫外：

```sh
cd /path/to/cloned/cliora
python3 -m venv /tmp/cliora-prototype-venv
/tmp/cliora-prototype-venv/bin/pip install playwright
/tmp/cliora-prototype-venv/bin/python -m playwright install chromium
/tmp/cliora-prototype-venv/bin/python prototypes/mobile-session/test_prototype.py \
  --evidence-dir /tmp/cliora-mobile-session-evidence
```

測試程式會自動啟動及停止自己擁有的本機 HTTP 伺服器。若 Chromium 已由環境提供，可省略 Playwright 的瀏覽器安裝步驟並傳入 `--chromium /absolute/path/to/chromium`。

本主機已驗證的精確指令是：

```sh
/opt/data/cliora-mobile-study/venv/bin/python prototypes/mobile-session/test_prototype.py \
  --chromium /opt/hermes/.playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell \
  --evidence-dir /opt/data/cliora-mobile-pr/evidence/mobile-session-writer
```

## 原型範圍

- 顯示 exact selected session、Terminal／Files 直接切換、巢狀資料夾、上一層／breadcrumb，以及整個已選 session 工作區的檔名 substring 搜尋。
- 全幅唯讀 TEXT／CODE 預覽對齊現有 `PreviewPane.vue`／`readFileContent` 能力，並驗證檔案清單與預覽實際捲動位置、返回焦點、Escape 及切換 session 後清除狀態。
- 圖片、SVG、其他二進位與過大檔案都明確拒絕；本原型不是圖片檢視器，也不加入任何圖片顯示能力。
- 明確的合成狀態包含：正常、空資料夾、403、暫時失敗／誠實重試、圖片／二進位不支援、過大、session 已結束，以及四種 bounded-search 停止原因。
- 所有狀態與輸出只存在 JavaScript 記憶體；重新整理即重設。沒有 localStorage／sessionStorage、API、PTY、WebSocket、shell、指令執行或遠端資產。
- 不提供建立／停止 session、system shell、輸入、上傳、編輯、重新命名、刪除或下載控制。正式版既有 upload 不在本原型範圍內。

## 行動版明亮主題決議

行動版終端與預覽固定使用明亮外觀；OS 的 dark preference 不得把行動版切成深色。這是 #62 已核准的行動版方向，不再重啟視覺方向討論。桌面版維持現有主題政策，不受本提案改動；待審查的只有如何透過版本化 theme contract／ADR 正式落實行動版專用色盤，以及相符的 `tokens.css`／`themes.ts` contract 與真實 CLI 色彩驗證。
