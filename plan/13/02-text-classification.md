# 02 — 文字／二進位判定重寫（`WF-03`）

範圍：`daemon/internal/files/policy.go` 的 `DetectBinary`、`daemon/internal/files/read.go`
第 6 步、以及一份新的分類 corpus。**這一票與圖片投放沒有共用程式碼**，可以獨立出貨。

規範來源：`FR-FILE-004`、新增的 `FR-FILE-008`（`01-…md` §2.3）、
`research/tech.md` §11.6（本期修訂）、ADR 0015 Limits 表（本期修訂）。

---

## 1. 今天的行為與它的三個問題

`daemon/internal/files/policy.go` 目前的判定：取前 8 KiB（`sniffWindow`），
依序檢查 NUL → `utf8.Valid` → 控制字元比例 > 10%。三個問題都已量測（`08-…md`）：

### 1.1 窗格切在多位元組字元中間（主因）

`window := sample[:8192]` 沒有對齊 rune 邊界。當第 8192 個位元組落在一個
多位元組字元的中間，`utf8.Valid(window)` 為 false，整個檔案被判為二進位 —— 
即使它從頭到尾都是合法的 UTF-8。

實測：本 repo 878 個**完全合法 UTF-8** 的文字檔中，20 個被誤判，
全部是這個原因；佔 >8 KiB 且含多位元組字元檔案的 **8.7%**（`08-…md` §1）。
對純 CJK 內容，切點落在字元中間的機率是 2/3。

### 1.2 ANSI escape 被算成控制字元

ESC（0x1b）落進 `r < 0x20` 這一支。實測（`08-…md` §2）：
每行三組顏色的 log、以及帶 `\x1b[2K\x1b[1G` 的 spinner 輸出，都超過 10% 而被判為二進位。
終端機輸出正是使用者最想在瀏覽器裡看的檔案之一，而 ESC 本來就是文字檔的合法內容。

換頁字元 FF（0x0c）同理：`strings.Repeat("page\x0c\n", 200)` 今天被判為二進位。

### 1.3 比例的分子與分母單位不同

`control` 是**字元**數（`utf8.DecodeRune` 逐字前進），`len(window)` 是**位元組**數。
同樣密度的控制字元，CJK 檔案因為位元組多而被放行，ASCII 檔案被擋。
這不是安全性問題，但它讓 10% 這個數字沒有可以討論的意義。

### 1.4 反向：8 KiB 之後的內容完全沒有被看

`nul-late` 實測：`strings.Repeat("text line\n", 2000)` 後面接 `\x00\x01\x02`，判為**文字**；
9000 個 `A` 後面接 `\x00\xff` 的檔案，也判為文字。今天的漏判與誤判是同一個窗格造成的。

---

## 2. 改法

### 2.1 掃描整個已讀取的緩衝區

`read.go` 第 5 步已經把內容讀進記憶體，且被 `s.maxPreview`（預設 2 MiB）綁住。
判定改為掃描 `content` 全部，不再取窗格。

`sniffWindow` 常數移除。若未來為了效能要重新引入窗格，**必須**同時引入 rune 邊界回退
（見 §2.4 的測試），這一點寫成常數旁的註解 —— 這個 bug 是這樣裝上去的，也會這樣再裝一次。

成本已量測（`08-…md` §3）：2 MiB 混合中英內容，全檔掃描 **2.66 ms**（835 MB/s），
對比窗格版本的 11.6 µs。ADR 0015 給預覽的預算是 3 秒，2.66 ms 是它的 0.09%。
`FR-FILE-008.AC-05` 把 5 ms 訂成上限，`bench_test.go` 加一個 `BenchmarkDetectBinary2MiB`。

### 2.2 三段判定的新形狀

```go
// Classify 回傳 (verdict, mime)。verdict 是 classText / classBinary /
// classUnsupportedEncoding 三選一，read.go 依它決定回內容或回否決。
func Classify(content []byte) (Verdict, string)
```

1. **NUL** — 任何位置出現 `0x00` → `classBinary`, `application/octet-stream`。
   全檔掃描，`bytes.IndexByte` 即可（`FR-FILE-008.AC-03`）。
2. **UTF-8** — `utf8.Valid(content)`；失敗 → `classUnsupportedEncoding`。
   注意這裡的語意變化：**驗證失敗不再等於二進位**（§2.5、`00-…md` D15）。
3. **控制字元比例** — 逐 rune 前進，分母改成 rune 數；
   `\t`、`\n`、`\r`、**ESC(0x1b)**、**FF(0x0c)**、**VT(0x0b)** 視為文字；
   其餘 `r < 0x20 || r == 0x7f` 計為控制字元。`control*10 > runes` → `classBinary`。

第 1 步與第 3 步都要全檔走一遍，但第 1 步用 `bytes.IndexByte`（SIMD）、
第 3 步是逐 rune 迴圈 —— 後者是量到的 2.66 ms 的主要來源。
若之後要更快，正確的做法是把第 2、3 步合成一次走訪，而不是縮小掃描範圍。

### 2.3 空檔案

`len(content) == 0` 仍然回 `classText`（今天就是這樣，Monaco 顯示空白）。
corpus 要有一個空檔案，因為「空檔案是文字」是一個容易在重寫時掉掉的邊界。

### 2.4 必須存在的測試（`daemon/internal/files/policy_test.go`）

| 測試 | 內容 |
|---|---|
| `TestClassifyRuneBoundary` | 對同一段 CJK 內容，以 0、1、2 三種前綴長度產生三個檔案，三者都必須是 `classText`。今天 pad=0 與 pad=1 是 binary、pad=2 是 text —— 這個測試就是 §1.1 的回歸測試 |
| `TestClassifyNulAnywhere` | NUL 在第 0、8191、8192、8193、最後一個位元組，五個位置都必須是 `classBinary` |
| `TestClassifyAnsiLog` | 每行 1／3／10 組顏色的 log，全部 `classText`；spinner 序列 `classText` |
| `TestClassifyControlRatio` | 分母是 rune 數：`"a\x01"×N` 與 `"中\x01"×N` 必須得到**相同**判定 |
| `TestClassifyEncodings` | UTF-8 BOM → text；UTF-16LE BOM → binary（有 NUL）；Big5／GBK／Latin-1 → `classUnsupportedEncoding` |
| `TestClassifyCorpus` | §3 的 corpus 全表比對 |
| `BenchmarkDetectBinary2MiB` | `FR-FILE-008.AC-05` 的 5 ms 上限 |

### 2.5 `unsupported_encoding` 怎麼回

沿用既有的 `FILE_BINARY` code（不新增 wire 上的錯誤碼，因為對呼叫端而言處置相同：
不顯示內容、顯示中繼資料），以 `ReadResult.Reason = "unsupported_encoding"` 區分。
`mime` 回 `text/plain; charset=unknown` 而不是 `application/octet-stream` —— 
那是這個否決想說的事：**我們認為它是文字，只是讀不懂它的編碼**。

前端據此顯示不同文案（`05-…md` §3）。

**不做**：編碼偵測與轉碼。理由見 `00-…md` D15。
選用票 `WF-03b` 的觸發條件寫在這裡，以免它被無限期遺忘：
若 `WF-01` 或上線後的 `filesystem_denied_total{reason="unsupported_encoding"}`
顯示這個 reason 佔否決總數超過 5%，就開 `WF-03b`，
以**明示設定** `filesystem.fallback_encoding`（預設空、單一值、不猜）加上轉碼，
並在回應的 `encoding` 欄位據實回報（該欄位前端已經在顯示：`PreviewPane.vue:112`）。

---

## 3. 分類 corpus（`FR-FILE-008.AC-04`）

位置：`daemon/internal/files/testdata/classify/`，每個檔案一列期望值，
期望表放在 `testdata/classify/expected.json`（`{"name": "utf8-cjk-cut-8192.md", "verdict": "text"}`）。

生成的檔案（>1 KiB 者）由 `daemon/internal/files/testdata/generate.go`（`//go:build ignore`）產生，
以免 repo 裡塞進一堆二進位測試資料；小檔案直接入庫。

| 類別 | 檔案（至少） | 期望 |
|---|---|---|
| CJK 切點 | 8190、8191、8192、8193、8194 五個切點各一個 `.md` | text |
| 純文字 | ASCII、CRLF、無結尾換行、空檔、只有換行、UTF-8 BOM | text |
| 終端輸出 | ANSI 上色 log、spinner、`script(1)` 錄製輸出 | text |
| 原始碼 | 含 FF 換頁的 Go、含 VT 的舊式文件、極長單行的 minified JS | text |
| 標記語言 | 含大量 emoji 的 Markdown、含 4-byte rune 的 JSON | text |
| 非 UTF-8 | Big5、GBK、Shift-JIS、Latin-1 各一 | unsupported_encoding |
| 二進位 | PNG、JPEG、GIF、WebP、ELF、tar.gz、zip、UTF-16LE、UTF-16BE、SQLite | binary |
| 邊界 | 前 9000 bytes 全是 ASCII、之後才有 NUL 的檔案 | binary |
| 邊界 | 剛好 `max_preview_size` 的合法 UTF-8 檔案 | text |

corpus 的 gate（`GATE-WF-CLASSIFY-CORPUS`）獨立於單元測試註冊，
這樣它在 `required_for: ["changed", "all", "mvp"]` 下永遠會跑 —— 
判定規則被改寬的那一天，這個 gate 是唯一會出聲的東西。

---

## 4. 全樹掃描的驗收（`00-…md` §1 第 6 項）

`scripts/wf/classify-scan.sh <dir>`：走訪指定目錄下所有副檔名在白名單內的檔案，
對每一個呼叫判定，輸出 `scanned / text / binary / unsupported_encoding` 與被判為非文字的清單。

驗收方式：對 `plan/`、`docs/`、`research/`、`backend/`、`frontend/src/`、`daemon/`
各跑一次，被判為 binary 的**合法 UTF-8 檔案數必須是 0**。
今天的基準值是 20（`08-…md` §1），全部在 `plan/` 下。

這個 script 同時是 runbook 的一部分：使用者回報「某個檔案看不到」時，
第一步是在節點上對那個檔案跑它。
