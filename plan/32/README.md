# Cliora 行動視覺與資訊層級：去除制式化介面感（研究／原型／方向選擇）

版本：**v0.2（方向已選 C 安靜操作式；待 UAT 驗證；實作仍受閘門阻擋）**。v0.1 = `2c57855`／`6361724`。
議題：#75。基準：master `1c73568`（PR #96 合併後）。分支 `design/mobile-visual-ia-75`。
關聯：#72（對話式操作決策與閘門）、#73（S0 結構化事件可行性）、#74（U0 對話工作面原型）、
#62／#67（已選：Session-first、手機明亮 Porcelain/Pocket、檔案直接可達）、`plan/29`（行動 RWD）、`plan/31`（二進位預覽）。

> **本目錄是研究與原型，不是實作計畫。** #75 的交付邊界是「先研究／原型與產品方向選擇，
> 再依 #72 技術閘門（#73／M0）決定實作工作」。本期沒有改動 `frontend/src/**`、backend、daemon、
> contracts 或桌面行為，也沒有新增相依套件或動畫框架。

## 目前狀態（v0.2）

2026-09-28 產品負責人選定 **C 安靜操作式** 為手機視覺方向（覆蓋了研究者「A 為基底」的建議；紀錄與仍成立的信心限制見
[`04-…md`](04-comparison-and-recommendation.md) §0）。這是產品決策，**不是 UAT 證據**：U1–U9 與 C 特有的 C1–C4 改為「驗證 C、找出要調整的地方」，
A 只在 C 未通過時作為對照。正式實作仍受 #72／#73（M0）閘門阻擋，而且應該**先做 #103**（D1／D2：手機 xterm 與 Monaco 仍是深色），
再做任何 UAT——否則 UAT 量到的是深淺割裂，不是 C。尚待決定：Q1–Q5、Q7 與新增的 Q8（C 的控制項圓角 12 vs 8，`05-…md` §2）。

## 版本紀錄

| 版本 | 內容 |
|---|---|
| v0.1 | Design Read、同一 IA、A／B／C 三變體、對照與研究者建議（A 為基底，約 55%）、token 影響、驗證與 Q1–Q7 |
| v0.2 | 記錄產品決策（選 C）；`04` 新增決策紀錄與 C1–C4；`05` 提案 token 改為 C、新增 Q8 與 C 的額外成本；`06` 改寫 Q6、新增 Q8 與原型修正的紅綠紀錄；原型預設 C，修正終端／標頭截斷、Viewer 輸入框、固定寬度的分隔線與輸入框 |

## 這一期最重要的一句話

```
  手機上「AI 制式感」的最大來源，不是字體或配色，而是六層堆疊的外框：
  畫面的前 32% 都在告訴你「這是一個 App」，而不是「這個 Session 現在怎樣」。
```

現況 390×844 下，終端機從 y=267 才開始，下方再扣 28px 狀態列，外框佔 **35%** 高度；
而「能不能接手」這個最重要的答案，被放在最底下 20px 高的膠囊裡。重整資訊層級之後，
三個變體的終端機都從 y≈145 開始，**同一支手機多出 7–11 列終端**（28 → 35–39 列）。

## 兩件不是設計問題、而是缺陷的事

Design Read 在真實瀏覽器量到：**手機上的 xterm 與 Monaco 仍是深色**（`rgb(16,20,22)`），
而頁面已是 pocket 明亮主題（`--terminal-background: #ffffff`）。issue 附圖所說的
「深色 xterm 與淺色頁面強烈割裂」**不是方向問題，是接線缺陷**：兩個消費者讀的是使用者選的
`preferences.theme`，而不是 `plan/29` MS-20 規定的 `preferences.renderedTheme`
（證據與位置見 [`00-design-read.md`](00-design-read.md) §3 D1/D2）。
`mobile.spec.ts` 只驗 CSS 變數、沒驗 xterm 實際底色，所以它一直是綠的。
**本期不修**（邊界禁止改 `frontend/src`），已另開 #103；它是 UAT 的前置條件（[`06-…md`](06-verification-and-open-questions.md) Q1）。

## 文件

| 檔案 | 內容 |
|---|---|
| [`00-design-read.md`](00-design-read.md) | 現況實拍（真實 bundle ＋ 模擬 Central）、痛點地圖（觀察／判斷／假說／需真機四欄分開）、缺陷清單、值得保留的 Cliora 品牌元素 |
| [`01-reference-boundaries.md`](01-reference-boundaries.md) | `Lei-k/happy@a1eae8d…`、`relvo-labs/agent-runtime@6094215…` 的 pin、可轉譯與不可複製之處 |
| [`02-ia-rework.md`](02-ia-rework.md) | 同一套 IA：小螢幕一次回答四個問題；合併／刪除的外框；原生終端一觸可達；系統 shell 與主 CLI 的區別 |
| [`03-visual-variants.md`](03-visual-variants.md) | A 克制編輯式／B 工程工作台式／C 安靜操作式：字級、中英混排、間距、面板、圓角、密度、圖示、語意色、動效 |
| [`04-comparison-and-recommendation.md`](04-comparison-and-recommendation.md) | 對照表（任務成功、閱讀、控制權辨識、原生可達、成本、文化語境）、建議方向與信心、UAT 必須確認的事 |
| [`05-token-vds-impact.md`](05-token-vds-impact.md) | 對 `theme/tokens.css`／VDS 的影響：**顏色零變更**；尺度 token 的版本化提案（未套用） |
| [`06-verification-and-open-questions.md`](06-verification-and-open-questions.md) | 驗證紀錄、閘門 exit code、未驗證項目、給產品負責人的待決問題 |

原型：[`prototypes/mobile-visual-ia/`](../../prototypes/mobile-visual-ia/README.md)（獨立 HTML/CSS/JS，合成資料，變體切換器＋23 種情境）。

## 截圖不進 repository

現況與變體截圖、每個畫面家族的直式對照圖（≤1290px 寬）都在 repository 外：
`/opt/data/cliora-mobile-75-run/shots/`（`current/`、`variants/{a,b,c}/`、`sheets/`）。
現況截圖同樣只含合成資料：Session 名稱、Node、終端輸出、檔案內容都是為本研究寫的，
沒有任何真實使用者資料、截圖或私人 CLI 輸出。issue 原附圖**未使用**。

## 不在本期

正式實作（任何 `frontend/src` 變更）、對話式 composer 與送出語意（#74）、結構化事件接線（#73）、
桌面 redesign、新動畫框架、新字型、IME／輔助鍵列（`plan/29` MS-11/12）、真機 UAT。
