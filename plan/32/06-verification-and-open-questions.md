# 06 — 驗證紀錄與待決問題

## 1. 做了什麼、在哪裡

| 項目 | 結果 | 證據（repository 外） |
|---|---|---|
| 現況實拍 | master `1c73568` 真實 bundle，22 張（390×844 為主，另 360／430／844×390），Playwright 攔截 `/api/**` 與 `/ws/**`，無伺服器 | `/opt/data/cliora-mobile-75-run/shots/current/`、`metrics.json`、`measure.json` |
| 現況量測 | 終端 y=267／28 列；xterm 與 Monaco 底色 `rgb(16,20,22)` vs `--terminal-background #ffffff`；Viewer／重連時 `main` 421／431 > 390 | `measure.json` |
| 變體截圖 | 3 變體 × 30 張（v0.1 時 23 情境；390×844，另 360、430、844×390） | `shots/variants/{a,b,c}/` |
| 對照圖 | 20 個畫面家族，每張「現況＋A＋B＋C」，直式 1230px 寬（橫向家族為 4 列堆疊） | `shots/sheets/*.png` |
| 原型測試（v0.1） | `test_prototype.py` **exit 0**，12 項 PASS；幾何 345 次載入，其中 44px 觸控只量 276 次（195×422 不量） | — |
| 原型測試（v0.2） | `test_prototype.py` **exit 0**，**13 項 PASS**（新增 C 方向一項，另 242 次頁面載入） | `shots/test/mobile-visual-ia-test.json` |
| v0.2 C 截圖 | 只重拍 C：30 張；A／B 沿用 v0.1 的 30＋30 張，對照圖上標「（v0.1 截圖）」 | `shots/variants/c/`、`shots/sheets/`（20 張，重建） |
| 原型測試（v0.2.1） | `test_prototype.py` **exit 0**，**16 項 PASS**；幾何 360 次載入（24 情境），其中 44px 觸控 288 次；對比 49 組 | 同上 JSON |
| v0.2.1 C 截圖 | 清單列改版後重拍 C 的清單類畫面（見 §1.2） | `shots/variants/c/`、`shots/sheets/01-list.png` |

### 1.1 v0.2 原型修正：先紅後綠

新增 `c_direction_suite`（`test_prototype.py`），逐項收集失敗。**同一份測試**分別跑在 `6361724`（修正前）與修正後的原型上
（以 `git show HEAD:…` 取出舊檔，放在 repository 外執行）：

| # | 修正 | 斷言 | 修正前（`6361724`） | 修正後 |
|---|---|---|---:|---:|
| F1 | 標頭與終端在 360／390／430／844×390／195×422（窄寬重排近似）不截斷、不互相遮擋 | 終端 `scrollWidth ≤ clientWidth`；被截斷的標題／meta 必須帶與全文相同的 `title`；`.detail-top` 內各區塊不重疊、狀態格不被裁切 | **198** 筆（按頁面計：終端被切 48 頁、標題／meta 被截斷且無全文 100 頁、橫向狀態格被裁 2 頁；一頁可有多筆） | 0 |
| F2 | Viewer 不顯示終端輸入框；C 在輸入位置放整寬「取得控制權」 | Viewer 的終端文字不含輸入框；C 的按鈕填滿終端底部列的內容寬 | **35** | 0 |
| F3 | 分隔線／輸入框不再是固定寬度 | 含 CLI 標頭的終端必須有 `.rule`，寬度介於內容寬的 85–100% | **135** | 0 |
| F4 | 未帶 `v` 時預設 C | `data-variant` 與切換器都是 `c`；`?v=a` 仍選到 A | **1** | 0 |

F2 的「整寬」定義在第一次紅燈後修正過一次：原本拿按鈕寬除以**視窗**寬（門檻 0.85），在 195×422 窄寬重排近似下按鈕已填滿容器
（195 − 2×16px 內距）卻只有 0.84；改成除以**容器內容寬**、門檻 0.99——對一般寬度更嚴，不是放寬。修正後的測試對舊檔重跑仍是上表的 35 筆紅。

**正式實作的界線（F2）**：原型能讓 Viewer 的合成輸出「停在提示框之前」，正式版不能——CLI 的輸入框是 CLI 自己畫在 PTY
輸出裡的字元，改寫或遮住它違反 `plan/29/07` MS-19（bytes 與 ANSI 語意永不更改）。正式版能做、也應該做的是：
**Cliora 自己的輸入元件（MS-12 的行動輸入列、叫出鍵盤的焦點）在 Viewer 時不存在**，由整寬接管列佔同一個位置。
UAT 要看的是「使用者是否以為自己能打字」，不是終端裡有沒有那個框。

截圖與量測腳本（不提交）：`/opt/data/cache/scratch/75/capture-current.mjs`、`measure-body.mjs`、`capture-variants.py`。
Chromium：`chromium_headless_shell-1234`（repo 的 Playwright 1.61.1 預期 1228，所以以明確 `executablePath` 指定）；
原型測試用 Python Playwright 1.55.0（`uv run --no-project`，快取在 `/opt/data/cache/scratch/75/`）。

## 2. 閘門

v0.2 在最後一次變更之後重跑（v0.1 的結果見 git 歷史；Node 22.14.0 via `.nvmrc`；Go 1.26.8，因為本機 PATH 上沒有 `go`，改用
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

### 1.2 v0.2.1：獨立審查（Codex，`f3501fa`，PASS_WITH_FOLLOWUPS，無 P0／P1）的四項修正

每項先寫斷言、對 `f3501fa` 的檔案跑出紅燈，再修到綠：

| 審查項 | 修正 | 新斷言 | 修正前 | 修正後 |
|---|---|---|---|---|
| P2 ANSI 涵蓋度被寫大了 | token 區塊補上 6 個 bright 彩色與 `brWhite`；對比清單加入 6 個 bright；`white`／`brWhite` 另以 dim 帶檢查 | `check_ansi_coverage`：12 個彩色都有 token 且都在文字配對裡 | 紅：缺 `ansi-bright-{red,green,yellow,blue,magenta,cyan,white}` | 綠；49 組全過，無需縮窄說法 |
| P2 C1 在 C 做不到 | 清單每列加 44px `⋯`（`aria-haspopup="dialog"`、可鍵盤開啟），顯示等寬 `<bdi>` 完整路徑、Node、Runtime、id，並可「開啟這個 Session」；Escape 依 id 把焦點還給該列的 `⋯`；新增同名一對 `demo-api`（team-a／team-b）與情境 `list-info` | `review_followups_suite` C1 部分：同名兩列都有 ≥44px 的 reveal；鍵盤開啟顯示 `/srv/demo/team-…` 路徑；Escape 回到同一列；從 reveal 開到的是 team-b 的 id | 紅：找不到同名一對 | 綠 |
| P3 觸控與縮放的說法 | 文件改寫：「200% zoom」→「195×422 窄寬重排近似」；44px 的載入數寫實際值；真實 200% 縮放列入 §3 | `check_doc_claims`：04／05／06／原型 README 不得出現舊說法，且必須寫出實測的配對數與觸控載入數 | 紅：04 與原型 README 把 195×422 稱為 200% zoom、04 寫 345 次載入都量了觸控（實際 276） | 綠（49 組、288 次） |
| P3 建立 sheet 換 Node 失焦 | Node select 加 `id="create-node"`，重繪後焦點回到它 | `review_followups_suite` focus 部分：換成可提權 Node 後焦點仍在該 select，且出現警示帶 | 紅：焦點跑到關閉鈕（`BUTTON`） | 綠 |

## 3. 沒有驗證的事（不得以本期證據代替）

- **真機**：iOS Safari、Android Chrome 都沒有。網址列收合、home indicator、`env(safe-area-inset-*)` 實值、真實軟體鍵盤高度、旋轉。
- **真實 200% 縮放與系統字級**：測試的 195×422 只是窄 CSS 視窗（重排近似），沒有瀏覽器縮放 UI、iOS 動態字級或 Android 字型縮放；這三者都要真機量。
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
| **Q1** | D1／D2（手機 xterm 與 Monaco 仍是深色）是否另開修復票，**先於** #73／M0 閘門處理？（v0.2：已開 **#103**；剩下的問題是它是否排在 UAT 之前） | (a) 立即另開小票修 `renderedTheme` 接線並補一條讀取 xterm 實際底色的 E2E；(b) 併入之後的 #75 實作 | (a)。它是 #62 已核准決策的回歸，不是新方向；而且不修它，UAT 比較的是深淺而不是變體 |
| **Q2** | system shell 在手機上要不要暴露？（D6：現況暴露，`plan/29` 文件說不暴露） | (a) 不暴露（改程式）；(b) 暴露但只能從 `⋯` 開啟並帶警示分頁（本原型）；(c) 維持現況常駐分頁（改文件） | (b)，並把 `plan/29/01` §2 改成版本化修訂 |
| **Q3** | Session 詳情在手機上可否不顯示全域 App header（改為「‹ 返回 Sessions」）？ | (a) 可以；(b) 保留漢堡與帳號 | (a)。它是最大的一塊外框（56px）；帳號與其他頁從清單進入 |
| **Q4** | 手機橫向（如 844×390）要不要走手機版？目前只看寬度，落入桌面版、終端 8 列 | (a) 以「高度 ≤500 且橫向」也視為手機（需修 `MS-D-03` 斷點單一來源）；(b) 維持 | (a)，但需先量 iPad／小筆電分割視窗不會被誤判 |
| **Q5** | 清單可否依既有 `status` 分組（例如失敗／斷線在前）？ | (a) 可以，屬既有屬性；(b) 只能用伺服器順序（`plan/29/01` §1 的保守讀法） | 仍建議先 (b)。**選 C 使這題更重要**：C 的清單一屏只有 4–5 列、且不顯示路徑，找「對的那一個」更依賴排序與名稱；UAT C1／C2 失敗時，分組是第一個候選調整。另外 D4 的 `<bdi>` 修正並沒有因為 C 隱藏路徑而變得不需要——路徑移到 `⋯` sheet，那裡一樣要修 |
| **Q6** | **（v0.2 改寫）** UAT 驗證 C：#103 修好之後、iPhone＋Android 各一台，觀察者以 C 完成 U1–U9 與 C1–C4；A 只在 C 某題失敗時作為對照 | — | 是；見 `04-…md` §4、§4.1 |
| **Q7** | 若選定方向需要新尺度 token（`05-…md` §2），由誰核准 VDS 1.1 行動附錄？ | ADR 0027 修訂或新 ADR | 與 `plan/29` 的 `MS-D-04`～`07`（pocket 機制 ADR）同一次審。選 C 不改變這個建議；提案值已改為 C 的那一欄 |
| **Q8** | **（v0.2 新增）** C 的控制項圓角：手機 `--radius-control` 用 12px 還是維持 8px？ | (a) 行動 media 區塊覆寫為 12px，經 VDS 1.1 行動附錄修訂 `style.md` §22；(b) 維持 8px，C 只在 sheet 用 16px，接受較小的視覺差異 | (b)：圓角是「消費型 App／樣板感」風險（C3）最大的一項，而 C 的核心不靠它。最好在 UAT 前決定，以免 UAT 看到的 C 與將要實作的 C 不同 |

Q1–Q4 的建議**不因選 C 而改變**：Q1（#103 先修）反而更急，因為 UAT 已改為驗證單一方向，深色終端會直接污染 C 的結果；
Q2、Q3、Q4 屬共同 IA，與視覺方向無關。
