# Cliora Visual Refresh — interactive prototype

新版遠端工作台的視覺與互動提案。預設採 Graphite（石墨專業），提供五種主題供比較。

## Preview

[私人線上預覽](https://cliora-workbench.neil0628.chatgpt.site)

線上預覽由原型擁有者私人存取；GitHub 協作者未必具備權限。可依下列步驟在本機查看。

## Run locally

在 repository 根目錄執行：

```sh
python3 -m http.server 8080 --bind 127.0.0.1 --directory prototypes/visual-refresh
```

開啟 http://localhost:8080 。不需要安裝 npm 套件或啟動後端。亦可直接開啟 index.html；主題偏好儲存依瀏覽器對 file URL 的支援而異。

## Included

- Session 工作台：CLI／系統終端／唯讀檔案預覽、可收合檔案欄、聚焦模式。
- Sessions：搜尋、Runtime 篩選、建立與開啟示範 Session。
- Nodes：節點狀態與示範資源資訊、詳情及建立 Session 入口。
- 概況：繼續工作、示範指標與近期活動。
- 模擬控制權切換、重新連線、終止確認及本機圖片選擇回饋。
- 五種主題：Graphite、Porcelain、Midnight、Studio、Industrial。

## Scope and limitations

這是獨立 HTML／CSS／JavaScript 原型，尚未整合正式 Vue、Naive UI、xterm.js 或 Monaco。

- 全部主機、工作目錄、檔案及終端內容均為合成示範；不連接 Central、daemon 或真實主機。
- 終端只提供 help、ls、pwd、git status、clear 的預設回應，不執行指令。
- 圖片選擇只顯示檔名，沒有上傳或圖片投放到 CLI。
- 新建 Session 與其他操作狀態只存在記憶體，重新整理頁面即重設；主題選擇嘗試儲存在 localStorage。
- Nodes 與概況部分數字為固定示範資料，不構成即時監控。
- 畫面切換以本機 UI state 實作，沒有獨立路由或深層連結。
- 五款主題共用主要版面，尚未逐一還原概念圖的所有版型差異。
- 此目錄未納入正式前端建置與部署；沒有攜入預覽服務的 hosting metadata 或憑證。

## Files

- index.html：靜態入口。
- style.css：版面、響應式規則與主題。
- app.js：示範資料、畫面與互動。

## Verification

- JavaScript syntax：`node --check prototypes/visual-refresh/app.js` 通過。
- HTML 引用的本機 CSS／JavaScript 檔案存在。
- 尚未執行瀏覽器互動／視覺回歸驗證，也未宣稱符合正式產品的連線、安全或權限驗收條件。

## Review focus

1. 工作台資訊密度、終端可用空間與檔案側欄。
2. 五款配色與文字可讀性。
3. Session／連線／控制權狀態的識別。
4. 窄視窗操作與聚焦模式。
5. 選定方向後，將展示層整合至既有 Vue 前端，保留正式 Session 生命週期、授權與 WebSocket 邏輯。

本提案以 master 的遠端操作功能為基準，不重新啟用已關閉的 V2 PR #27。
