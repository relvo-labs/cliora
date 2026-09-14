# 08 — 驗證、閘門與離場條件（`MS-22`～`MS-25`）

`02-rollout-and-verification.md` §3 定義了 `MSP-F-*`（fixture，已通過）與 `MSP-R-*`（正式，全部未完成）。
本文件把 `MSP-R-*` 接到**實際存在的測試檔、閘門 ID 與 traceability 條目**上——
沒有這一層，`MSP-R-*` 只是一份願望清單，沒有任何東西會在 CI 裡變紅。

## 0. 先接既有的，不要另建一套

本期最容易犯的錯是新建一組行動測試，與既有套件並行。既有資產：

| 既有 | 位置 | 本期 |
|---|---|---|
| 水平溢位量測 | `tests/e2e/theme.spec.ts:404-440`，2 主題 × 3 尺寸（1440／1024／390）× 3 路由 | **擴充**尺寸與路由，不新建 |
| 主題就地重繪 | 同檔 `:165-300`（buffer／捲動／未送輸入／角色皆保留） | 加 pocket |
| 焦點環、scrim、badge 文字 | 同檔 `:302-400` | 自動涵蓋 pocket（迴圈依 `THEMES`） |
| 靜態色彩閘門 | `scripts/vr/vr-gates.sh`（4 個） | 新增行動相關檢查於同一個 runner 家族 |
| 版面不變式 | `scripts/ly/layout-gates.sh`（3 個） | 新增斷點字面值檢查 |
| token 契約 | `theme/theme.contract.test.ts`、`themes.test.ts`、`theme.contrast.test.ts` | pocket 自動納管 |

`theme.spec.ts` 的響應式區塊以 `E2E_FULL_STACK=1` ＋ 管理員憑證為條件跳過。**行動測試沿用同一條件**，
不得為了讓 CI 好看而改成無需全套環境的假環境版本。

## MS-22 單元與靜態層

寫入 `theme/theme.contract.test.ts`、`scripts/` 下的閘門 runner、`composables/useBreakpoint.test.ts`（新）。

新增測試：

| 檢查 | 位置 | 為什麼 |
|---|---|---|
| 行動尺度 media 區塊**不含任何 `COLOR_TOKENS` 成員** | `theme.contract.test.ts` | `MS-01` 開了一個 `@media (max-width:767px) :root {}` 區塊，它不在 theme 區塊的既有保護範圍內，會變成偷渡顏色的後門 |
| `pocket` 定義全部 `COLOR_TOKENS`、且不重定義尺度 | 既有兩條規則自動涵蓋 | — |
| `terminalAnsi()` 對深色主題回傳值 === 現行 `TERMINAL_ANSI` | `themes.test.ts` | `MS-18` §0.1 拆分的整個安全性建立在這一條 |
| ANSI 16 色納入 `PAIRS`：彩色 ≥4.5、灰梯遠端 ≥4.5、灰梯近端 1.25–4.5、明度單調、normal/bright ≥1.3 | `contrast.ts` ＋ `theme.contrast.test.ts` | 那 16 個值至今**不在任何測試裡**（`07-…md` §0.1.1）。五個深色主題已算過會通過 |
| 每個主題**具名宣告**灰梯的 dim 兩色，不由明暗推斷 | `themes.ts` | 推斷會在下一個主題加進來時安靜地選錯兩個 |
| `theme-boot.js` ≤12 行、接受 pocket 的寬度派生 | `theme.contract.test.ts:166-186` 擴充 | `MS-D-07` 明文不放寬界限 |
| `useBreakpoint` 以 `matchMedia` 而非 resize；`onScopeDispose` 解除綁定 | `useBreakpoint.test.ts` | 洩漏的監聽器在 SPA 裡是累積型缺陷 |
| `AppLayout` 卸載時移除 `visualViewport` 監聽 | `AppLayout.test.ts` 擴充 | 同上 |

新增靜態閘門（`traceability/gates.json`，owner `frontend`，layer `static`）：

| 閘門 | 檢查 |
|---|---|
| `GATE-MS-BREAKPOINT` | `frontend/src` 的 `@media` 寬度值只允許 767／768／1023／1024／1439／1440；JS 端不得再出現 `innerWidth <` 的版面判斷 |
| `GATE-MS-TOUCH-TOKEN` | 互動元素不得直接寫死 `min-height`／`height` 的像素值，必須走 `--density-*` |

兩者與 `scripts/vr/vr-gates.sh`、`scripts/ly/layout-gates.sh` 同形狀：純文字檢查，
**明確寫下它們看不見什麼**（看不見渲染後的幾何，那要瀏覽器）。

## MS-23 瀏覽器 E2E

寫入 `frontend/playwright.config.ts`、`tests/e2e/theme.spec.ts`（擴充）、`tests/e2e/mobile.spec.ts`（新）。

`playwright.config.ts` 新增兩個 project：

```ts
{ name: "mobile-chrome", use: { ...devices["Pixel 7"] } },
{ name: "mobile-safari", use: { ...devices["iPhone 14"] } },
```

**這是模擬，不是真機。** 兩個 project 的名稱、報告與證據都必須標示為 emulation；
它們滿足不了任何 `MSP-R-010` 的真機要求（`02-…md` §5 已明文：「UAT cannot be marked complete from Chromium viewport screenshots」）。
它們買到的是**回歸偵測**：一旦有人改壞了行動版面，在合併前就紅。

`theme.spec.ts` 的溢位矩陣尺寸由 3 擴至 8，對齊 `MSP-F-009`：
360×844、390×844、430×932、844×390、768×844、1024×768、1100×800、1440×900。
路由由 3 擴至涵蓋 `/sessions/:id` 的兩個模式。

`mobile.spec.ts` 新增（每一條對應一個 `MS-*`）：

| 測試 | 對應 |
|---|---|
| 所有可見 `input`／`select`／`button` 的 bounding box ≥ 44×44 | MS-01 |
| `visualViewport` 模擬縮減後 `.shell` 高度跟著縮，且底部安全區未重複相減 | MS-02 |
| 導覽抽屜：焦點陷阱、Escape 返回開啟鈕、背景不捲動 | MS-03 |
| `<768` 為卡片清單且六個欄位齊全；`≥768` 仍是 `UiDataTable` | MS-04 |
| 七個寬度下檔案欄「要嘛佔位、要嘛有可聚焦的開啟控制」 | MS-05 |
| posture 徽章在壓縮態直接可見（不在揭露之後） | MS-06 |
| 模式切換來回十次後，終端 DOM 節點與 WebSocket 未被重建 | MS-07 |
| preview 開關十次後歷史堆疊淨增 0；session 切換時舊 state 不生效 | MS-08 |
| 模式切回終端後觸發一次 fit，且尺寸在 2–300／2–500 內 | MS-09 |
| 搜尋範圍標示存在；四種 `stopped_reason` ＋ `scanned_count` 可見 | MS-15 |
| 拒絕態分類各自不同（含圖片歸入 binary） | MS-16 |
| 模擬 OS dark preference 下，行動仍為 pocket 明亮值 | MS-20／MS-21 |
| 桌面在兩種 OS preference 下的選擇與改動前相同 | MS-21 |

新增閘門 `GATE-MS-VIEWPORT-E2E`（owner `frontend`，layer `e2e`，command `npm run test:e2e -- --project=mobile-chrome --project=mobile-safari`）。

## MS-24 真機、安全與 UAT

**這張票不寫程式，它收集證據。** 對應 `MSP-R-001`～`012`。

`02-…md` §3 的第二張表與 §5 的矩陣是驗收清單本身，此處不重複；此處只補「誰交、交什麼形式」：

| ID | 交付者 | 證據形式 |
|---|---|---|
| MSP-R-001／002／003／004 | M2 terminal writer | 真實 API／node／CLI 的操作記錄 ＋ 伺服器端狀態對照 |
| MSP-R-005 | IME spike owner ＋ M2 | 實機型號／OS／瀏覽器版本 ＋ 事件序列 ＋ 實際送出 bytes |
| MSP-R-006／007 | M3 file writer | 真實 workspace 的每一種 stop reason 與每一種拒絕態 |
| MSP-R-008 | 安全 reviewer | 逾期／403／ticket 重放／登出後的記憶體與快取清除 |
| MSP-R-009 | theme owner | 真實 xterm／Monaco 的 ANSI 16／游標／選取／dim／警告／錯誤／反白／truecolor 截圖 |
| MSP-R-010 | QA | **真機**（非模擬）iOS Safari 與 Android Chrome，含 VoiceOver／TalkBack、200% 文字、旋轉 |
| MSP-R-011 | QA | Wi-Fi↔行動網路、離線、背景 ≥60 秒、node 離線與回復、輸出爆量 |
| MSP-R-012 | 安全 reviewer ＋ release owner | #47／#56／#57／#58／#59 的現行處置與驗證產物、桌面回歸全綠、獨立 review |

**不得**以 `MSP-F-*` 的 fixture 結果、模擬 project 的截圖或本計畫的任何段落代替上表任何一列。

## MS-25 Traceability 與推出

寫入 `research/prd.md`、`traceability/requirements.json`、`traceability/links.json`、`traceability/gates.json`。

- 依 `MS-D-13` 新增 `NFR-007`（行動視窗操作性，owner `frontend`，source `research/prd.md#nfr-007`），
  criteria 對應 `MS-01`～`MS-09` 的可驗項；`pocket` 的對比與 token 契約掛 `NFR-006`。
- `links.json` 新增 `planned_by` 指向 `plan/29/` 對應文件，`verified_by` 指向 `MS-22`／`MS-23` 產出的測試。
- `gates.json` 新增三個閘門（`GATE-MS-BREAKPOINT`、`GATE-MS-TOUCH-TOKEN`、`GATE-MS-VIEWPORT-E2E`），
  `trigger` 與 `required_for` 對齊既有前端閘門。
- `scripts/trace validate --level static` 必須綠。
- 推出依 `02-…md` §6 的四階段，旗標 `mobile_ia` 預設 off（`MS-D-12`）。

## 離場條件

本期可宣告完成，當且僅當**全部**成立：

1. `MS-D-01`～`MS-D-14` 皆已裁決並記錄（含「維持現況」的裁決）。
2. `MS-01`～`MS-21` 全部合併或**明確記錄為移出本期**（`MS-17` 是唯一預先允許移出的）。
3. `GATE-FRONTEND-UNIT`、`GATE-BROWSER-E2E`、四個 `GATE-VR-*`、三個 `GATE-LY-*`、三個新 `GATE-MS-*` 全綠。
4. `MSP-R-001`～`012` 全部有上表指定形式的證據，且**沒有一項以 fixture 或模擬代替**。
5. 桌面回歸（`MS-21`）零差異。
6. 獨立的程式與安全 review 完成。
7. `09-implementation-status.md` 的開放測量（`MS-OM-*`）皆已量得實值或明確記為「已知未量，接受風險」並具名承擔者。

其中任何一項未達成，都不是「幾乎完成」——推出旗標維持 off。
