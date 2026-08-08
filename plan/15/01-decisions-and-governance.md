# 01 — 決策與治理（`FU-02`）

一份新 ADR、一份既有 ADR 的一句話修訂、三處 PRD 修訂、traceability 註冊、
兩份 skill 修訂。**核准之前不得動 daemon 程式碼**（`00-…md` §4）。

規範來源一律回指 `research/prd.md`、`research/tech.md`、`docs/adr/`；本目錄不複製需求內容
（`.agent/skills/AUTHORING.md`「Never duplicate canonical research」）。

---

## 1. ADR 0026：一般檔案上傳（新增）

檔案：`docs/adr/0026-general-file-upload.md`，狀態 `proposed` → `FU-02` 核准後 `accepted`。

Header：

```
- Amends: ADR 0024's W2 — its third leg ("a retention period") is refined, not
  removed: retention applies to platform-owned destinations; where the user
  chooses the destination, the corresponding requirement is visibility. See §3.
- Related: ADR 0014（路徑安全；W1 全靠它）、ADR 0015（預覽政策與上限）、
  ADR 0016（RBAC 是一張表）、ADR 0024（寫入姿態、W1–W4、圖片投放；
  本 ADR 是它 rejected 表裡「general file upload」那一列的設計）
- Requirements: `FR-FILE-010`（新增）、`NFR-005.AC-109`（再收窄）、
  `NFR-005.AC-142`（一句話修訂）、`FR-FILE-005`（延伸到寫入方向）
- Contract: v1.9.0
- Ships in: `agentd` 0.7.0（migration `0020`）
- Plan: `plan/15/`（取代已作廢的 `plan/14`）
```

### 1.1 Context

使用者在 2026-08-03 收斂了需求：

> 實際上使用者只需要將檔案上傳到 workspace 底下的目錄，
> 要可以將檔案拖拉進檔案瀏覽器中，其餘就用 cli 或是 terminal 處理

前一份計畫（`plan/14`，工作區檔案編輯）被同一則指示判定為改動過大並作廢。
**這件事本身要寫進 Context**，因為它解釋了本 ADR 為什麼刻意小：
最後那半句「其餘就用 cli 或是 terminal 處理」是一條**範圍指令**，
不是一句客套 —— 它把編輯、更名、刪除、下載全部移出，
而那四樣正是 `plan/14` 裡所有複雜機制（版本前提、回收桶、undo、dirty 狀態機）
存在的唯一理由。

ADR 0024 的 rejected 表裡有這一列：

> | Open general file upload, since writes are allowed now | Withdrawing read-only
> did not remove the boundary. W2/W3/W4 must hold for general upload too, and they
> are not designed for it — starting with what a quota means for arbitrary file sizes. |

那不是「永遠不做」，是「還沒設計」。本 ADR 去設計那三條（§2、§3、§4），
而不是主張它們不適用。

### 1.2 Decision A — 一條新的落地路徑，而它可以指名

`filesystem.store` 帶 `directory` 與 `filename`。這是平台第一次讓請求端
指定工作區裡的落地位置與檔名。

**這正是 ADR 0024 §4 預告的情況，而 §4 的兩個警告都要被遵守：**

| ADR 0024 §4 的警告 | 本 ADR 怎麼遵守 |
|---|---|
| 不要拿「請求端不得命名」當先例，主張未來的路徑也不能指名 | 本 ADR 就是不受它約束的那條路徑。截圖不需要名字；`requirements.txt` 的名字就是它的全部意義 |
| 不要拿本期當先例，回頭在 `filesystem.upload` 上加一個 `filename` | **新增另一個型別**，`filesystem.upload` 一個欄位都不動（`00-…md` D10）。兩個型別並存，各自的規矩各自成立 |

指名換來的是一套自己的防護，逐條對上 ADR 0024 §4 列的清單：

| ADR 0024 §4 說編輯／上傳會需要的 | 本 ADR |
|---|---|
| path normalisation | `relClean`（既有）＋ `filename` 在 wire 上就不允許 `/`（§2） |
| binding the decision to the opened inode（`RealRel`） | 目的地目錄以 `LstatIn` 確認是真目錄（不是 symlink），落地用 `O_EXCL｜O_NOFOLLOW` |
| applying the sensitive-file policy in the write direction | 同一個 `SensitiveClassification()`，套在 `directory/filename` 合成的路徑上 |
| refusing symlink creation | 本期不建立任何 symlink；也不經由 symlink 寫入 |
| protecting `.git/` | 拒絕，**含 worktree 那種作為檔案存在的 `.git`**（§5 的既有缺口） |

**不需要的是版本前提。** ADR 0024 §4 把它列在編輯的需求裡，是因為編輯會取代既有內容。
本 ADR **永遠不覆寫**（`00-…md` D2），所以沒有任何既有位元組會被動到，
也就沒有「你以為那裡是什麼」這個問題。這一句要寫進 ADR，
因為它是本 ADR 與 `plan/14` 在規模上的**全部**差別。

### 1.3 Decision B — 落地的形狀

五條限制，固定死：

1. **不覆寫**：`O_EXCL`。同名（檔案、目錄或 symlink）存在 → `FILE_EXISTS`，不落地。
2. **不建目錄**：目的地必須是一個已經存在的目錄。
3. **不可執行**：一律 `0644`。
4. **位置與名字都要過讀取面同一份政策**：`.git`（兩種形式）、`.cliora/`、
   排除目錄、敏感名稱一律拒絕。
5. **有界**：單檔 4 MiB、每 session 累計 256 MiB、每日 200 個檔案、
   可用空間下限；**沒有保留期**（§3）。

不限制**檔案型別**。圖片投放用 magic number 只認四種，因為它要保證 CLI 讀得懂；
一般上傳沒有這個義務 —— 使用者要放 `.csv`、`.tar.gz`、`.pdf` 或 `.parquet`
都是他的事。取代型別檢查的是第 3 條（不可執行）與第 4 條（名字要過政策）。

### 1.4 Decision C — 授權與稽核沿用既有的 `file.upload`

不新增 RBAC action，不新增稽核事件。`file.upload` 的**語意擴大**：
從「把一張圖片投放到平台自有目錄」變成「把一個檔案放到工作區裡的一個位置」。

理由在 `00-…md` D8。**代價要寫在 ADR 的 Consequences 而不是註腳**：
一個曾經只授權截圖投放的組織，升級後那個授權變大了，
而它沒有辦法只保留舊的那一半（除了在節點側關掉 `filesystem.upload.files.enabled`）。
節點側的那個開關因此不是可選的貼心設計，它是這個決定的配套。

### 1.5 Consequences

- **正面**：使用者可以把檔案放進工作區，而這是 CLI 協作第二常見的缺口
  （第一是截圖，已由 ADR 0024 交付）；整條路徑重用 ADR 0014 的封閉性與
  ADR 0015 的敏感檔案政策，沒有第二套實作；而且它**不需要** `plan/14` 的任何機制。
- **負面**：
  - **`file.upload` 的語意變大了**（§1.4）。
  - **平台會在使用者選定的位置建立檔案。** 圖片投放只會寫進 `.cliora/`；
    這條路徑會寫進使用者的原始碼樹（但**永遠不會取代**其中任何東西）。
  - **`filesystem.store` 是第二個使用 8 MiB 訊框上限的請求型別**
    （第一個是 `filesystem.upload`，ADR 0024 §7）。訊框上限本身不變。
  - **升級即取得行為**：`filesystem.upload.files.enabled` 預設 `true`
    （同 ADR 0023 D2、ADR 0024 D8 的取捨），因此有 release note 與 runbook 的義務。
  - **4 MiB 的上限會被撞到。** 這是刻意的，替代路徑是終端機；
    但它是一個要被觀測的決定而不是一個終局（`00-…md` D3）。
  - **W2 的措辭需要修訂**（§3）。這是本 ADR 對 ADR 0024 的唯一改動。
- **決定不做（而不是延後）**：編輯、更名、刪除。它們由 CLI／終端機承擔，
  前端不會長出這些動作 —— 兩條寫入路徑都只會**新增**檔案，
  所以工作區裡的東西不可能因為前端的操作而消失或被取代。
  這個區別要寫成「決定」而不是「還沒做」：後者會招來一份計畫，
  而一份刪除的計畫會把版本前提、回收桶與 undo 整套拖回來（§6.2）。
- **不在此決定**：下載、資料夾上傳、分塊上傳。

### 1.6 Alternatives rejected

| 方案 | 為什麼不 |
|---|---|
| 在 `filesystem.upload` 上加 `filename`／`directory` | ADR 0024 §4 預先擋掉的兩個錯誤之一：會把一條已經正確的路徑（截圖不需要名字，所以它連路徑穿越的入口都沒有）換成一條需要三段驗證的路徑，**而且沒有換到任何東西** |
| 允許覆寫（`overwrite: true`） | 那是 `plan/14` 的第一步。覆寫要安全就需要版本前提、412、回收桶與 undo，而使用者要取代一個檔案時有終端機 |
| 同名時自動加尾碼 | 靜默改名會讓 CLI 讀到舊的那一份而使用者以為它讀到新的。症狀是「AI 看的是舊資料」，而那種 bug 很難被歸因到上傳 |
| 用 multipart/form-data 帶檔名 | 會為了一個只帶一樣東西的請求引入 `python-multipart` 與一個解析器。ADR 0024 的 `/images` 已經立了「原始 body」的體例 |
| 現在就做分塊上傳 | 使用者剛剛才判定前一份計畫改動過大。分塊要一個組裝狀態機、逾時清理與部分落地的收尾 —— 那是一個新 ADR |
| 支援資料夾上傳 | 要建目錄、要處理無界數量與部分失敗，而使用者已經指定「其餘用 cli 或 terminal 處理」 |
| 沿用圖片投放的 `image_upload` 開關 | 「可以放截圖到 `.cliora/`」與「可以放任意檔案到任意位置」對節點擁有者是不同大小的授權 |
| 新增 `file.write` action | `plan/14` 的做法。會帶來一個 seed migration 與三處矩陣維護，換到的只有一個沒有人會分開設定的旗標 |
| 落地時保留來源檔案的權限 | 一個從瀏覽器拖進來的檔案不應該是可執行的 |

---

## 2. ADR 0024 修訂：W2 的第三腿

ADR 0024 的 W2 目前寫：

> **Bounded**: per-operation size, cumulative quota, and a retention period — all three.

`FU-02` 要把它改成：

> **Bounded**: per-operation size, cumulative quota, and — for a
> **platform-owned** destination — a retention period. Where the **user** chooses
> the destination, retention is replaced by **visibility**: every byte the
> platform writes must land at a path the user picked and can see in the tree, so
> that the user is the one who removes it. A retention period on a user-chosen
> path would mean the platform deleting the user's data on a timer, which is the
> opposite of what W2 exists to prevent. Free-space refusal covers the exhaustion
> risk that retention covered. (Refined by ADR 0026.)

**為什麼這是修訂而不是 waiver**：waiver 的意思是「這條規矩在這裡不成立，
我們接受那個風險」。這裡的情況是規矩的**目的**在兩種目的地上有兩種正確形狀 ——
`.cliora/uploads/` 需要保留期是因為沒有人負責清它；`datasets/data.csv`
不需要保留期是因為有人負責清它，而那個人就是選了那個路徑的使用者。
把它寫成修訂，下一條寫入路徑才會問對的問題（「這個位置誰負責清」），
而不是照抄一個 7 天。

ADR 0024 的其餘部分（W1、W3、W4、§3 的「請求端不得命名」、§4 的兩個警告、
圖片投放的五條限制）**一個字都不動**。

---

## 3. PRD 修訂（`research/prd.md`）

### 3.1 新增 `FR-FILE-010` 檔案上傳

放在 §8.8（`FR-FILE-009` 之後），anchor `fr-file-010`，
`owner: central`、`applicability: ["mvp"]`、`criticality: "should"`：

| AC | 內容 | verification_profile | risk |
|---|---|---|---|
| AC-01 | 持有 `file.upload` 的使用者可將檔案上傳到 Session 工作區內指定的目錄 | automated | medium |
| AC-02 | 支援拖放至檔案樹的目錄列與工具列挑檔兩個入口，兩者行為一致 | automated | low |
| AC-03 | 檔名沿用使用者提供的名稱；名稱不得含路徑分隔符號或控制字元 | automated | critical |
| AC-04 | 目的地必須是工作區內既有的目錄；不得建立目錄 | automated | high |
| AC-05 | 同名項目已存在時拒絕，且不得改動既有檔案 | automated | critical |
| AC-06 | 敏感檔案規則（`FR-FILE-005`）適用於上傳的目的地與檔名 | automated | critical |
| AC-07 | `.git/`（含 worktree 中作為檔案存在的 `.git`）與平台自有目錄不得作為目的地 | automated | critical |
| AC-08 | 落地檔案權限為 `0644`，不得可執行 | automated | high |
| AC-09 | 單檔、每 Session 累計、每日檔數與節點可用空間四項上限，逾越時明確拒絕且不落地 | automated | high |
| AC-10 | 每次上傳留下稽核紀錄（使用者、Session、節點、相對路徑、位元組數），不記內容 | automated | high |
| AC-11 | 節點可停用此功能並回報；停用時前端不顯示上傳入口 | automated | medium |
| AC-12 | 不支援資料夾上傳，且必須明確拒絕而非部分處理 | automated | low |

### 3.2 `NFR-005.AC-109`（§21 未來擴充方向第 18 項）— 再收窄

現行加註（2026-08-01）：「其中『把一張圖片交給 CLI』這一片已由 `FR-FILE-009` 交付。
下載、編輯、刪除、更名與一般檔案上傳仍為未來擴充。」

改為：

> *（2026-08-03：一般檔案上傳已由 `FR-FILE-010` 交付。
> 仍為未來擴充的是**下載**、編輯、刪除與更名 —— 後三者依產品決定改由
> CLI／終端機承擔，不再列為平台前端的擴充方向。）*

`lifecycle` 維持 `active`（下載這一片是真的還沒做）。

> **這一句的後半很重要**：編輯／刪除／更名從「未來擴充」變成
> **「已決定由終端機承擔」**。那是使用者 2026-08-03 的指示，
> 而它比「還沒做」是更強的一句話 —— 下一個人不必再問「什麼時候要做編輯」。

### 3.3 `NFR-005.AC-142`（§23 產品核心原則第 7 條）— 一句話修訂

現行文字提到「有配額與保留期」。因為 §2 修訂了 W2 的第三腿，這一行要跟著改：

> …且每一條路徑都必須經 `workspace.Root` 侷限、有配額（平台自有目錄另有保留期，
> 使用者指定位置則以**可見性**取代保留期）、每次寫入留稽核、可由節點拒絕並回報
> （ADR 0024 的 W1–W4，W2 由 ADR 0026 精修）。

anchor 不變，`lifecycle` 維持 `active`，新增一段 `review` 記錄本次修訂。

**「檔案總覽的預覽為唯讀」那半句不動** —— 本期不做編輯，所以它仍然完全為真。
這是本計畫與 `plan/14` 的一個具體差別：那份計畫要改寫核心原則，這份不用。

### 3.4 `research/tech.md`

- **§11.5 檔案讀取**：「寫入僅有一條路徑」改為兩條，並在設定範例補上
  `filesystem.upload.files`。
- **§11.7 敏感檔案規則**：補一句「同一份規則同時適用於上傳的目的地與檔名」。
- **§11.9 圖片投放**：標題改為「圖片投放與檔案上傳」，新增一小節寫本期的落地順序、
  命名（沿用使用者提供的名稱）、不覆寫、`0644`、上限與設定鍵。
  **不改寫既有的圖片投放內容**，只在後面追加。

---

## 4. Traceability 註冊

| 檔案 | 動作 |
|---|---|
| `requirements.json` | 新增 `FR-FILE-010`（12 AC）；`NFR-005.AC-109` 更新 `review`；`NFR-005.AC-142` 新增 `review`；`FR-FILE-005` 新增 `review` 說明它現在同時守上傳的目的地與檔名 |
| `links.json` | 12 條新 AC 連到 `02`–`04` 各節的實作與測試 |
| `gates.json` | 新增 `GATE-FU-NO-OVERWRITE` 與 `GATE-FU-WRITE-POLICY`（`05-…md` §3） |
| `waivers.json` | 不新增 |

PRD 每一條新 AC 都要有 `<a id="…"></a>` anchor，且與 `source_anchor` 完全一致
—— static gate 會檢查這件事。

---

## 5. 一個順手要修的既有缺口

`.git` **今天不受任何保護**。已核對：`.git` 在 `workspace.excluded_directories`
（`daemon/internal/config/config.go:143`），而那份清單的註解明寫它是 ignore rule、
**不是安全控制**，只影響自動展開與搜尋；`filesystem.denied_directories` 的預設值是
`.ssh`／`.aws`／`.gnupg`，**不含 `.git`**。所以直接指定路徑今天就讀得到 `.git/config`。

在此之上，git worktree 與 submodule 的 `.git` 是一個內容為 `gitdir: …` 的**純文字檔**，
連「目錄」這個形狀都不成立 —— 片段比對擋不到它。

本期會讓客戶端可以指名落地位置，所以這個缺口必須在同一期補上（`FR-FILE-010.AC-07`）。
**本期只補寫入方向**：讀取方向的 `.git` 預覽是既有行為，改它會讓一批今天看得到的檔案
變成看不到，那需要自己的 release note，屬於另一期。這個分界要寫進 ADR 的 Consequences。

---

## 6. `plan/14` 作廢，以及從它帶過來的東西

`plan/14`（工作區檔案編輯：建立、編輯、更名、刪除）於 2026-08-03 由使用者判定
改動過大而作廢，目錄保留為歷史 —— 與 `plan/10`（自建 tunnel，因成本被否決）同一個做法。
**一份被否決的計畫是下一份計畫的輸入**，而「為什麼不那樣做」比「要怎麼做」更容易被遺忘。

### 6.1 沿用的四項

| 從 `plan/14` 帶過來的 | 在本計畫的哪裡 |
|---|---|
| 寫入方向的政策函式（`WritableClassification`，呼叫讀取面同一個 `SensitiveClassification`） | `02-…md` §2。本期只需要它的一個動詞版本 |
| **`.git` 有兩種形狀**這個發現，以及它今天完全沒有被擋 | §5、`FR-FILE-010.AC-07` |
| 工作區根目錄要有自己的否決分類（否則使用者看到「無效的路徑」） | `02-…md` §2 第 6 列 |
| 落地檔案不得可執行 | `00-…md` D6 |

### 6.2 沒有沿用的，以及為什麼

| `plan/14` 的機制 | 為什麼本期不需要 |
|---|---|
| 版本識別（`revision`）、`precondition`、412／428 | 它們只為「覆寫」存在。本期 `O_EXCL`，永不覆寫 |
| 回收桶（`.cliora/trash/`）、7 天清理、還原 | 它們只為「刪除與覆寫」存在。本期不刪除也不覆寫，沒有任何位元組會消失 |
| 目錄的有界子樹走訪 | 它只為「遞迴刪除／更名」存在 |
| Monaco 編輯模式、dirty 狀態、往返位元組測試、衝突橫幅 | 它們只為「編輯」存在 |
| `file.write` RBAC action、seed migration | 本期沿用 `file.upload`（`00-…md` D8） |

**這張表就是「改動過大」的診斷**：`plan/14` 的機制沒有一項是多餘的 ——
它們每一項都是某個動詞的必要條件。問題在動詞太多。
把動詞收斂到一個（而且是不破壞任何既有東西的那一個），機制就整批消失了。

---

## 7. `.agent/skills` 修訂（`FU-07`）

兩份，各改一段（`AUTHORING.md`：不複製 canonical research，`SKILL.md` 保持 imperative）。

| Skill | 改什麼 |
|---|---|
| `cliora-project-context` | 工作區寫入姿態那一段：改為**兩條**寫入路徑；補上「請求端可以指名落地位置的路徑必須自帶 §1.2 那五項防護」；並明確寫下**編輯／更名／刪除已由產品決定交給 CLI／終端機**，不是待辦。後者是本期最該進入口 skill 的一句話 —— 沒有它，下一個人會再寫一份 `plan/14` |
| `go-daemon-development` | 正文那一長段：把「generate stored filenames in the daemon rather than accepting one」修為「圖片投放由 daemon 命名；接受客戶端名稱的路徑必須 `O_EXCL`、固定 `0644`、且名稱與目的地都要過讀取面同一份敏感政策」。**不要刪掉原本那句** —— 它對圖片投放仍然成立 |

`cliora-security-review` 不改：它的「sensitive/binary/oversized file denial」
在本期沒有變化，而寫入方向的檢查已經由 `GATE-FU-WRITE-POLICY` 承接。
`vue-naive-ui-workflow` 也不改（它的圖片投放那一段仍然成立，
本期的拖放目標是另一個元素，沒有推翻任何既有規則）。

`.agent/skills/README.md` 的 skill 計數與分類不動，「Last updated」日期要改。
