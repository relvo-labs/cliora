# 08 — 實測（`WF-01`）

實測於 **2026-08-01**，Go **1.26.5**（linux/amd64，Intel Skylake），
對 `daemon/internal/files.DetectBinary`（`policy.go` 現況）與本 repo 的工作樹。
`artifacts/*/local/` 是 gitignore 的，所以結果放在這裡。

**本文件只記錄已經量到的事實。** `WF-01` 還有三項尚未量測，列在 §4；
其中第 1 項是圖片投放的閘門（`00-…md` §5 第一列）。

---

## 1. 誤判：8 KiB 窗格切在多位元組字元中間

以現行 `DetectBinary` 掃過本 repo 的工作樹（排除 `.git`、`node_modules`、
`.venv`、`dist`、各種 cache；副檔名白名單 24 種）：

```text
valid-utf8 text files: 878
  >8KiB: 261, of which contain multi-byte runes: 231
  FALSE binary verdicts: 20 (8.7% of >8KiB multi-byte files)
```

**20 個誤判全部是同一個原因**：檔案整體是合法 UTF-8，但 `sample[:8192]`
切在一個多位元組字元中間，`utf8.Valid(window)` 因此為 false。
判定程式對這 20 個檔案回的是 `application/octet-stream`。

被誤判的檔案（全部在 `plan/` 下，因為那是本 repo 中文密度最高的地方）：

```text
plan/02/01-data-layer.md                      8951
plan/03/09-implementation-status.md          10464
plan/04/01-path-security-and-protocol.md     10560
plan/04/README.md                             9578
plan/05/00-execution-plan.md                 33544
plan/05/03-dashboard-and-error-management.md 16823
plan/05/06-workspace-favorites.md             8437
plan/05/README.md                            15810
plan/07/01-platform-constraints-and-decisions.md 14786
plan/07/03-edge-console-and-single-origin.md 13771
plan/08/00-execution-plan.md                 13801
plan/08/04-verification-and-exit.md          10568
plan/09/01-app-shell-and-height.md           10269
plan/10/00-execution-plan.md                 23720
plan/10/06-verification-and-exit.md          15730
plan/10/README.md                             9948
plan/11/05-frontend.md                       11401
plan/11/07-implementation-status.md          36764
plan/12/00-execution-plan.md                 18650
plan/12/06-verification-and-exit.md           9843
```

（另有一個真正的無效 UTF-8 檔案 `contracts/v1/fixtures/invalid/malformed-utf8.json`
被判為 binary —— 那是**正確**的，它就是為了這個目的存在的 fixture。）

切點的直接示範，同一段 CJK 內容加上 0／1／2 個 ASCII 前綴：

```text
pad=0 len=96000 binary=true   windowValid=false
pad=1 len=96001 binary=true   windowValid=false
pad=2 len=96002 binary=false  windowValid=true
```

對純 CJK（每字 3 bytes）內容，切點落在字元中間的機率是 **2/3**。
本 repo 量到 8.7%，是因為 `.md` 是中英混排，第 8192 個位元組常常落在 ASCII 上。
**一份純中文的文件，會有三分之二的機率打不開。**

---

## 2. 其他分類行為（現況）

```text
plain-ascii    len=12     binary=false
utf8-bom       len=16     binary=false
tab-heavy      len=1600   binary=false
empty          len=0      binary=false
utf8-4gb-cut   len=10000  binary=false   ← 2-byte rune，切點剛好對齊
png-header     len=8      binary=true
utf16le-bom    len=6      binary=true
big5           len=9      binary=true
gbk            len=5      binary=true
latin1         len=18     binary=true
formfeed       len=1200   binary=true    ← "page\x0c\n" × 200
escape-log     len=3400   binary=true    ← "\x1b[32mok\x1b[0m line\n" × 200
nul-late       len=15001  binary=false   ← 只有最後一個位元組是 NUL
```

### 2.1 ANSI 上色需要多少才會被判為二進位

```text
plain                （無 escape）                    binary=false
one-colour-pair      "\x1b[32m…\x1b[0m …"             binary=false
three-colour-pairs   每行三組顏色                      binary=true
spinner              "\x1b[2K\x1b[1G\x1b[36m⠋\x1b[0m"  binary=true
```

**每行三組顏色的 log 就會被擋。** 這是 `npm`、`cargo`、`pytest`、`go test`
的預設輸出形狀。

### 2.2 比例的分子與分母單位不同

`control` 逐 rune 計數，分母是 `len(window)`（位元組）。
`"a\x01"×2000` 與 `"中\x01"×2000` 的控制字元密度相同（50%），兩者今天都被擋；
但在 10% 附近的區間，CJK 檔案因為位元組數被放大而較不容易觸發。
這不是安全性問題，是「10%」這個數字在兩種檔案上不代表同一件事。

### 2.3 反向：窗格之後的內容完全沒有被看

```text
"text line\n" × 2000 + "\x00\x01\x02"   → binary=false（長度 20003，NUL 在 20000）
"A" × 9000 + "\x00\xff"                 → binary=false
```

也就是說，**前 8 KiB 可列印的二進位檔今天會被當成文字送進 Monaco**。
`FR-FILE-004.AC-02`（不顯示原始內容）在這個方向上是不成立的。
`01-…md` §2.3 的 `FR-FILE-008.AC-03` 就是為了把這一條寫成需求。

---

## 3. 全檔掃描的成本

2 MiB 的中英混排內容（`"套件說明 package docs line with 中文 and ascii\n"` 重複填滿）：

```text
BenchmarkScratchWindow8K-8    50    11614 ns/op   191400 MB/s   ← 現況（只看前 8 KiB）
BenchmarkScratchFullScan-8    50  2662963 ns/op      835 MB/s   ← 提案（全檔＋ESC 例外＋rune 分母）
```

**2.66 ms**。ADR 0015 給 ≤2 MB 預覽的預算是 3 秒，這是它的 **0.09%**。
`FR-FILE-008.AC-05` 把上限訂在 5 ms，留了接近一倍的餘裕。

成本主要來自逐 rune 的迴圈（第 3 步），不是 NUL 掃描（`bytes.IndexByte` 走 SIMD）。
若之後真的需要更快，正確方向是把 UTF-8 驗證與控制字元計數合成一次走訪，
**不是**把掃描範圍縮回去 —— 那正是這一期在修的東西。

---

## 4. 閘門：CLI 讀不讀得到相對路徑的圖片 — **成立**

實測於 2026-08-01。`claude` **2.1.220**、`codex-cli` **0.146.0**。
工作區為一個臨時目錄，圖片放在 `.cliora/uploads/2026-08-01/`（本期規劃的實際形狀），
CLI 以該工作區為 cwd 啟動。三張測試圖各含一個色塊方形與一個色塊圓形，
問題只問「方形與圓形各是什麼顏色」—— 答錯與沒讀到可以區分。

| CLI | 格式 | 提示中的路徑 | 回答 | 判定 |
|---|---|---|---|---|
| claude | PNG | `.cliora/uploads/2026-08-01/01K….png`（**裸相對路徑**） | 「A small green square in the upper left and a large magenta circle in the center, on a white background.」 | ✅ 正確 |
| claude | JPEG | `.cliora/uploads/2026-08-01/b.jpg` | `b.jpg = blue, orange` | ✅ 正確 |
| claude | GIF | `.cliora/uploads/2026-08-01/c.gif` | `c.gif = black, yellow` | ✅ 正確 |
| codex | JPEG | 同上 | `b.jpg = blue, orange` | ✅ 正確 |
| codex | GIF | 同上 | `c.gif = black, yellow` | ✅ 正確 |
| codex | PNG | 同上 | 「A small green square and a large magenta circle on a white background.」 | ✅ 正確 |

**結論：D1 與 D6 照原樣成立。**

- **不需要 `@` 前綴，也不需要任何 runtime 方言。** 兩個 CLI 都接受**裸的工作區相對路徑**，
  自己去讀檔。`00-…md` §5 第一列的兩個備案都不必啟動。
- 相對路徑是相對於 CLI 的 cwd，與 `tmux new-session -c <workspace>` 一致。
- **codex 在讀圖時走的是它自己的讀檔工具**，因此 `sandbox: read-only` 的預設姿態下也成功
  （測試時未帶 `--dangerously-bypass-approvals-and-sandbox`）。
  也就是說圖片投放**不依賴** ADR 0023 的無沙箱姿態。

### 4.1 未量到的一項：WebP

這台機器上沒有任何 WebP 編碼器（`convert`／`magick`／`ffmpeg`／`cwebp`／PIL 皆不存在，
Go 標準庫只有 PNG／JPEG／GIF 編碼），因此**四種格式只實測了三種**。
兩個 CLI 的文件都列出 webp 為支援格式，但這不是實測。

處置：`WF-04` 的嗅探表仍照 D3 收四種；`06-…md` §1.5 的 e2e 清單加一項
「在有 WebP 編碼器的環境上補測」，若補測失敗則從嗅探表移除 webp
（那是一行常數的改動，不影響設計）。

---

## 5. `WF-01` 第 2 項：xterm.js 5.5.0 的 paste 行為 — **可攔截**

讀 `frontend/node_modules/@xterm/xterm/lib/xterm.js`（5.5.0）的 paste 實作：

```js
handlePasteEvent = function (e, t, i, s) {
  e.stopPropagation();
  e.clipboardData && r(e.clipboardData.getData("text/plain"), t, i, s)
}
```

三個直接的結論：

1. **xterm.js 只呼叫 `stopPropagation()`，不呼叫 `preventDefault()`。**
   `stopPropagation` 只擋冒泡，所以掛在宿主元素上的**冒泡**監聽器永遠不會被觸發，
   而**capture 階段**的監聽器會在它之前先跑（capture 由外往內）。
   → `05-…md` §1 的「宿主元素 ＋ capture 階段」是正確且**唯一**可行的攔截點。
2. **它只讀 `getData("text/plain")`。** 純圖片的貼上會取得空字串，
   於是走 `triggerDataEvent("")` —— 今天按 Ctrl+V 貼圖「沒有反應」的原因就是這個。
   攔截時只要在 `clipboardData.files.length > 0` 才 `preventDefault()`，
   一般文字貼上完全不受影響。
3. **bracketed paste 只發生在 paste 路徑上**（`bracketTextForPaste` 依
   `decPrivateModes.bracketedPasteMode` 包 `ESC[200~`／`ESC[201~`）。
   `typeText` 直接 `socket.send()`，不經過這條路徑，所以送出的位元組**不會**被包裝。

## 6. `WF-01` 第 3 項：連續送出的路徑在 CLI 輸入行的樣子 — **逐字顯示，未被折疊**

在 tmux（120×30）中以工作區為 cwd 啟動 `claude`，
再一次送出整串 `.cliora/uploads/2026-08-01/01K1ZQ9F3B7T2M8V4X6Y0N5R3D.png ` （含尾隨空白）。
擷取畫面：

```text
❯ .cliora/uploads/2026-08-01/01K1ZQ9F3B7T2M8V4X6Y0N5R3D.png
────────────────────────────────────────────────────────────
  ⏸ manual mode on
```

**路徑逐字出現在輸入行，沒有被折疊成 `[Pasted text]` 之類的佔位符**，游標停在尾隨空白之後，
使用者可以直接接著打字。這是 D6 想要的樣子。

（送出方式為 `tmux send-keys -l`，與 daemon 寫入 PTY 的效果相同：
兩者都是把位元組交給 pane 的輸入，都不附加 bracketed paste 標記。）

### 6.1 一個順帶量到、屬於上一期的事實

同一次擷取裡，**Claude Code 自己印出**了：

```text
tmux detected · scroll with PgUp/PgDn · or add 'set -g mouse on' to ~/.tmux.conf for wheel scroll
```

這是在**預設 socket、沒有 daemon 自有 tmux.conf** 的環境下出現的。
它與 `plan/12` D6 的結論一致（`mouse on` 是正解），且顯示 CLI 本身也會偵測 tmux 並給建議。
`PV-04` 上線後這行提示會變成多餘 —— 值得在該期的 release note 或 runbook 補一句，
但**不是本期的範圍**，這裡只記錄。
