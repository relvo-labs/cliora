# 06 — 驗證紀錄與待決問題

## 1. 做了什麼、在哪裡

| 項目 | 結果 | 證據（repository 外） |
|---|---|---|
| 現況實拍 | master `1c73568` 真實 bundle，22 張（390×844 為主，另 360／430／844×390），Playwright 攔截 `/api/**` 與 `/ws/**`，無伺服器 | `/opt/data/cliora-mobile-75-run/shots/current/`、`metrics.json`、`measure.json` |
| 現況量測 | 終端 y=267／28 列；xterm 與 Monaco 底色 `rgb(16,20,22)` vs `--terminal-background #ffffff`；Viewer／重連時 `main` 421／431 > 390 | `measure.json` |
| 變體截圖 | 3 變體 × 30 張（23 情境；390×844，另 360、430、844×390） | `shots/variants/{a,b,c}/` |
| 對照圖 | 20 個畫面家族，每張「現況＋A＋B＋C」，直式 1230px 寬（橫向家族為 4 列堆疊） | `shots/sheets/*.png` |
| 原型測試 | `test_prototype.py` **exit 0**，12 項 PASS，345 次頁面載入 | `shots/test/mobile-visual-ia-test.json` |

截圖與量測腳本（不提交）：`/opt/data/cache/scratch/75/capture-current.mjs`、`measure-body.mjs`、`capture-variants.py`。
Chromium：`chromium_headless_shell-1234`（repo 的 Playwright 1.61.1 預期 1228，所以以明確 `executablePath` 指定）；
原型測試用 Python Playwright 1.55.0（`uv run --no-project`，快取在 `/opt/data/cache/scratch/75/`）。

## 2. 閘門

在最後一次變更之後執行（Node 22.14.0 via `.nvmrc`；Go 1.26.8，因為本機 PATH 上沒有 `go`，改用
`~/go/pkg/mod/golang.org/toolchain@v0.0.1-go1.26.8…/bin`，`GOTOOLCHAIN=local`）：

| 指令 | exit |
|---|---:|
| `make format-check` | 0 |
| `make lint` | 0 |
| `make traceability` | 0 |
| `make layout-gates` | 0 |
| `make vr-gates` | 0 |
| `prototypes/mobile-visual-ia/test_prototype.py` | 0 |
| `git diff --check`（含新檔） | 0 |
| `git diff --stat origin/master -- frontend/src backend daemon contracts` | 空 |

> 誠實註記：第一次（基準）執行時 PATH 上沒有 `go`，`make lint` 以 127 失敗，而 `make format-check`
> 的 `test -z "$(gofmt -l .)"` 在 gofmt 不存在時會**空轉通過**。上表是指定 Go 工具鏈後重跑的結果，兩者都實際執行了。
> 這個「gofmt 不存在時 format-check 仍綠」的性質是 Makefile 既有的，本期未改。

## 3. 沒有驗證的事（不得以本期證據代替）

- **真機**：iOS Safari、Android Chrome 都沒有。網址列收合、home indicator、`env(safe-area-inset-*)` 實值、真實軟體鍵盤高度、旋轉。
- **輔助技術**：VoiceOver、TalkBack 的朗讀順序、`role="status"` 播報頻率、sheet 的焦點約束在螢幕閱讀器下的行為。
- **真實 xterm／Monaco**：原型的終端與預覽是 `<pre>`；pocket ANSI 在 xterm 的次像素渲染、真實 Claude／Codex／tmux 輸出（`MSP-R-009`）。
- **真實服務**：RBAC、接管裁決、fresh-ticket 重連、gap、檔案搜尋 partial、上傳、預覽拒絕的伺服器路徑。
- **使用者**：沒有任何真人觀察；`04-…md` 的評等是研究者判斷。
- **繁中字體**：headless 用 Noto CJK；PingFang TC、Android 系統字的實際字寬與 13px 可讀性。
- **時間格式**：現況 `toLocaleString()` 的字樣隨裝置語系變化，headless 是 en-US。
- **桌面 1440×900**：本期沒有改任何正式程式，所以不存在桌面回歸；原型本身只針對手機尺寸設計。

## 4. 給產品負責人的待決問題

每一題都會改變下一步要做什麼；設計偏好（A／B／C）不在這裡，那是 UAT 的事。

| # | 問題 | 選項 | 研究者建議 |
|---|---|---|---|
| **Q1** | D1／D2（手機 xterm 與 Monaco 仍是深色）是否另開修復票，**先於** #73／M0 閘門處理？ | (a) 立即另開小票修 `renderedTheme` 接線並補一條讀取 xterm 實際底色的 E2E；(b) 併入之後的 #75 實作 | (a)。它是 #62 已核准決策的回歸，不是新方向；而且不修它，UAT 比較的是深淺而不是變體 |
| **Q2** | system shell 在手機上要不要暴露？（D6：現況暴露，`plan/29` 文件說不暴露） | (a) 不暴露（改程式）；(b) 暴露但只能從 `⋯` 開啟並帶警示分頁（本原型）；(c) 維持現況常駐分頁（改文件） | (b)，並把 `plan/29/01` §2 改成版本化修訂 |
| **Q3** | Session 詳情在手機上可否不顯示全域 App header（改為「‹ 返回 Sessions」）？ | (a) 可以；(b) 保留漢堡與帳號 | (a)。它是最大的一塊外框（56px）；帳號與其他頁從清單進入 |
| **Q4** | 手機橫向（如 844×390）要不要走手機版？目前只看寬度，落入桌面版、終端 8 列 | (a) 以「高度 ≤500 且橫向」也視為手機（需修 `MS-D-03` 斷點單一來源）；(b) 維持 | (a)，但需先量 iPad／小筆電分割視窗不會被誤判 |
| **Q5** | 清單可否依既有 `status` 分組（例如失敗／斷線在前）？ | (a) 可以，屬既有屬性；(b) 只能用伺服器順序（`plan/29/01` §1 的保守讀法） | 先 (b)，UAT 看使用者是否找得到失敗的 Session 再決定 |
| **Q6** | UAT 的時機與對象：D1 修好之後、iPhone＋Android 各一台、觀察者看 A 與 C？ | — | 是；U1–U9 見 `04-…md` §4 |
| **Q7** | 若選定方向需要新尺度 token（`05-…md` §2），由誰核准 VDS 1.1 行動附錄？ | ADR 0027 修訂或新 ADR | 與 `plan/29` 的 `MS-D-04`～`07`（pocket 機制 ADR）同一次審 |
