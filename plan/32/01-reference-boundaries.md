# 01 — 參考來源的界線

兩個參考來源都**可讀取**，已 pin SHA 並只讀了下列檔案（以 GitHub API 讀取，存在 repository 外的暫存目錄，不提交）。
它們不是 Cliora 的設計系統；本期沒有複製任何品牌資產、畫面、元件或程式碼。

## 1. `Lei-k/happy@a1eae8deabef8dc369d63b55d8d1b64db8efc15a`

Commit 日期 2026-09-16（`fix(app): use phone onboarding flow on tablets`）。讀過：

- `packages/happy-app/sources/-session/SessionView.tsx`
- `packages/happy-app/sources/components/ChatList.tsx`
- `packages/happy-app/sources/components/AgentInput.tsx`
- `packages/happy-app/sources/components/tools/PermissionFooter.tsx`、`ToolView.tsx`
- `packages/happy-wire/src/sessionProtocol.ts`

| 可轉譯（互動與可讀性） | 如何進入本期 | 不可複製／不適用 |
|---|---|---|
| **一個畫面同時放訊息、狀態與權限提示**（SessionView 以 header ＋ 狀態 ＋ list ＋ composer 組成，不切頁） | IA 的「一次回答四個問題」：狀態列緊貼標頭，不藏到底部或另一頁 | 它的 header 樣式、語音膠囊（voice pill）、側欄、品牌色 |
| **閱讀位置以最新內容為錨**（ChatList 用 inverted list，檔頭記錄「鍵盤升起時非 inverted 清單離最新訊息 582pt，inverted 不動」的真機量測） | 活動視圖（假說）新內容在底部、鍵盤不應把使用者從最新位置拉走；列為 UAT 項目 | FlashList／React Native 的 `maintainVisibleContentPosition` 無法搬到 Vue＋DOM；Cliora 的終端捲動由 xterm 與 tmux copy-mode 管，**不套用** |
| **觸控裝置上 Enter 只換行**（AgentInput 以 touch 偵測，避免手機誤送） | 記入 #74 的輸入考量；本期無 composer | Cliora 的主輸入是 PTY：Enter 的 byte 語意不得改（`plan/29/05` MS-11/12） |
| **工具事件以「動作＋對象＋狀態」一列呈現**（ToolView） | 活動視圖的事件列：圖示＋「讀取／編輯／執行」＋等寬對象＋狀態字樣 | 它的卡片外觀、展開動畫、diff 元件；以及把權限批准放在聊天面上（PermissionFooter）——**#72 明定審批只能在原生終端** |
| — | — | `happy-wire/src/sessionProtocol.ts` 檔頭自稱 **UNDER REVIEW / frozen**，不作為任何事件語意的依據 |

## 2. `relvo-labs/agent-runtime@60942150905b8e58401f98cb8c2c6009334825df`

main 於 2026-09-27。讀過：`docs/adr/ADR-0001`（Session/Turn/Run/Interaction 身分分離）、
`ADR-0003`（replay-then-live、`caught_up`、overflow）、`ADR-0016`（provider event activation 有序且有界）。
（#72 引用的是較早的 `c3c491a…`；兩者之間的差異本期未比對，只以本 SHA 為準。）

| 可轉譯（事件與狀態語意） | 如何進入本期 | 不可複製／不適用 |
|---|---|---|
| Session → Turn → Run → Interaction 四種身分分開 | 活動視圖以「第 N 回合」分段；等待確認是一個獨立事件，不是一則訊息 | 它的 ID 格式與 DTO；Cliora 沒有 Turn/Run 概念，要等 #73 |
| overflow 時送出明確訊息與第一個未送達序號，**不靜默丟棄** | 「事件流中斷：09:14–09:19 之間的活動未收到，不補寫、不推測」——與終端 `terminal.gap` 同一種誠實 | 它的 cursor／receipt 協定；Cliora 的 wire 契約不改 |
| 中斷／終止後的互動請求會被拒絕、不能逆轉 run 狀態 | 已結束的 Session：控制權顯示「唯讀（已結束）」，不再顯示「你有控制權」（對應 D9） | — |
| — | — | 它是 **No-PTY 的 in-process adapter**，不能接管既有 tmux Session；#72 已由使用者確認「既有 tmux/CLI Session 維持原生終端」 |

## 3. 因此，原型裡的「活動」是什麼

- 只出現在一個標示為「活動＋終端（假設）」的**未來受管 Session**（`demo-docs-managed`）；
  既有 Session 只有「終端機／檔案」兩個分頁。
- 頂部固定一條說明：「示意：活動整理需要 #73 的官方結構化事件，只適用未來的受管 Session；既有 tmux Session 維持原生終端。」
- 等待確認的事件只有「到終端機處理」，**沒有批准按鈕**（測試斷言畫面上沒有「批准／允許／approve」）。
- runtime 未宣告結構化事件時，活動分頁改為「此 Session 只支援原生終端機」＋「開啟終端機」；
  **不從 PTY bytes、ANSI strip 或畫面推測誰說了什麼**。
- composer、送出、ACK、草稿都屬 #74，本期刻意不畫。活動視圖在這裡的角色只是讓三個變體
  在「長內容＋工具事件」這種密度下也能被比較。
