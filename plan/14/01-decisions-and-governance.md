# 01 — 決策與治理（`WE-02`）

本文件是 `WE-02` 的交付內容：一份新 ADR、兩份既有 ADR 的加註與修訂、
六處 PRD 修訂、`research/tech.md` 一節新增，以及 traceability 的註冊。
**核准之前不得動 daemon 程式碼**（`00-…md` §4）。

規範來源一律回指 `research/prd.md`、`research/tech.md`、`docs/adr/`；本目錄不複製需求內容
（`.agent/skills/AUTHORING.md`「Never duplicate canonical research」）。

---

## 1. ADR 0025：工作區檔案編輯（新增）

檔案：`docs/adr/0025-workspace-file-editing.md`，狀態 `proposed` → `WE-02a` 核准後 `accepted`。

Header 欄位沿用 0024 的體例：

```
- Amends: none. Implements ADR 0024's W1–W4 for a second write path, and
  supersedes its §4 note only in the sense that the note said this ADR would exist.
- Related: ADR 0014（路徑安全，本 ADR 的 W1 全靠它）、ADR 0015（預覽政策與上限，
  本 ADR 把它的上限延伸到寫入方向）、ADR 0016（RBAC 是一張表）、
  ADR 0021 §1（`SCOPE-011` 存活的那半條：前端不得命名任何指令）、
  ADR 0024（寫入姿態與 W1–W4）
- Requirements: `FR-FILE-010`、`FR-FILE-011`、`NFR-005.AC-142`（二次修訂）、
  `NFR-005.AC-109`（再收窄）、`FR-FILE-002`（加註）、`FR-FILE-005`（延伸到寫入方向）
- Contract: v1.9.0
- Ships in: `agentd` 0.7.0（migrations `0020`、`0021`）
- Plan: `plan/14/`
```

### 1.1 Context

使用者在 2026-08-02 指示：

> 目前已經實際驗證過平台基本功能無問題，此階段我要解放工作檯的前端編輯功能，
> 在前端要可以 create/edit/rename/delete 檔案，以達到可以直接在系統前端一次性完成所有工作的效果

ADR 0024 在**前一天**（2026-08-01）撤銷了唯讀姿態，立下每一條寫入路徑都要滿足的
W1–W4，交付了第一條路徑（圖片投放），並且明白寫著：

> A future editing feature inherits them and will need **its own** ADR for
> everything else it must decide — conflict handling, concurrent writes, whether
> the sensitive-file policy applies in the write direction, protection of
> `.git/`, undo.

本 ADR 就是那一份。它要回答的是那五件事，加上 ADR 0024 §4 特意留下的那條界線：
**編輯必須讓客戶端指名檔案，所以「請求端不得命名檔案」不能沿用**，
需要的是另一套防護。

Context 段還要寫下一件看起來像瑣事、實際上是方法論證據的事：
`NFR-005.AC-142`（產品核心原則第 7 條）在 **24 小時內要被改第二次**。
第一次（ADR 0024）把「檔案總覽第一階段採唯讀模式」改成「預覽為唯讀＋寫入路徑受 W1–W4 約束」；
第二次（本 ADR）要把「預覽為唯讀」再改成「預覽**預設**為唯讀，編輯是顯式模式」。
**被推翻的每一次都是描述現況的那半句，W1–W4 一次都沒有動。**
這就是 ADR 0024 堅持「寫姿態而不是寫例外」換到的東西 ——
本 ADR 不需要重新辯論工作區可不可以被寫，只需要辯論怎麼寫。

### 1.2 Decision A — W1–W4 對編輯的逐條落地

ADR 0024 的四條規矩不是被引用，是被逐條回答。ADR 裡要有這張表，
因為六個月後第三條寫入路徑會照著它做：

| 規矩 | 圖片投放怎麼滿足（ADR 0024） | 編輯怎麼滿足（本 ADR） | 差別在哪 |
|---|---|---|---|
| **W1** 經 `workspace.Root` | 一個 `CreateExclusive` | 四個動詞、新增的 `LinkIn`／`OpenForReplace`／`CreateTemp`、fd 形式的 `Chmod`，**rename 的兩個端點都要驗**，**目錄操作要驗整棵子樹** | 寫入的位置由**客戶端指名**，所以 W1 從「限制寫在哪」變成「驗證客戶端說的那裡是不是那裡」。`RealRel` 綁 inode 這件事從讀取面搬到寫入面；而目錄操作讓它再擴一次 —— 一個動作可能同時動到幾百個位置（§1.2b） |
| **W2** 有上限、有清理 | 4 MiB／64 MiB／200 張／7 天 | 單次 2 MiB（＝預覽上限，`00-…md` D11）／每日 2000 次／目錄走訪 20000 項／trash 64 MiB／7 天 | 編輯本身沒有東西會過期，**被覆寫或刪除掉的版本才有**。W2 的第三腿因此變成回收桶（`00-…md` D6），而不是被 waive 掉 |
| **W3** 每次寫入留稽核 | 一個 `file.upload` 事件 | 四個事件，metadata 含**相對路徑**、`kind`、前後 revision，目錄刪除另含項目數 | 圖片的路徑是平台取的名字；編輯的路徑是使用者既有的檔案。為什麼仍然要記，見 `00-…md` D18 |
| **W4** 節點可拒絕並回報 | `filesystem.upload.enabled` → `image_upload` | `filesystem.editing.enabled` → `file_editing` | 兩個獨立的開關，不合併。一台機器可以願意接圖片而不願意被改原始碼 |

### 1.2b W1 在目錄操作上的延伸

刪除或更名一個資料夾，是把同一個操作套用到它裡面的每一樣東西。
所以 W1 不能只驗那一個路徑：

> **一個目錄操作在動手之前，要對它子樹裡的每一項套用與逐檔操作完全相同的判斷。**

沒有這一條，遞迴刪除就是本 ADR 每一條保護的萬用繞道 ——
刪掉一個含 submodule 的資料夾，等於把 §1.3 花了整整一列去保護的 `.git` 搬進回收桶。
實作與上限見 `02-…md` §3.1（`00-…md` D22）。

這一條同時是 W1–W4 這套規矩第一次被**第二種形狀的寫入**檢驗：
圖片投放與檔案編輯都是「一次動一個路徑」，目錄操作不是。
W1 撐得住，但它需要這一句延伸 —— 而下一條寫入路徑若也是批次的，
應該引用這一句而不是重新想一次。

**這張表本身就是 ADR 0024 的驗收**：W1–W4 是不是真的可以承接第二條路徑，
在 `docs/security-review-p13.md` 第 8 題被列為待答，本 ADR 給出答案 ——
**四條全部成立，其中 W2 的第三腿需要一個新機制（回收桶）才有意義**，
而那個機制不是為了滿足規矩而發明的，它同時就是 ADR 0024 點名的 undo。

### 1.3 Decision B — 五個 ADR 0024 點名的問題，逐一回答

| ADR 0024 點名的問題 | 本 ADR 的答案 | 對應 |
|---|---|---|
| **衝突處理（conflict handling）** | 樂觀鎖：每次讀取回傳 `revision`（內容 SHA-256），每次破壞性操作必須帶上它。不符即拒絕，不合併、不重試、不 diff | `00-…md` D3、D14 |
| **並行寫入（concurrent writes）** | 同上。此外**不要求 writer 角色** —— single-writer 是終端機的語意，不是工作區的。兩個瀏覽器同時改同一個檔案，第二個會收到 412 | `00-…md` D9 |
| **敏感檔案政策是否適用於寫入方向** | 適用，而且是**同一個函式**：`SensitiveClassification()`。rename 的來源與目的地都要過。同時，寫入的**內容**也要過讀取面同一個 `Classify()` | `00-…md` D4 |
| **`.git/` 的保護** | 四個動詞在 `.git/` 之下一律拒絕，**且要同時擋住 git worktree 裡 `.git` 是一個檔案的形式** —— 目前的 `denied_directories` 只比對路徑片段，擋不住那個檔案 | `00-…md` D4、`WE-01` 第 6 項 |
| **undo** | `.cliora/trash/`，7 天。刪除＝把目標 rename 進回收桶（檔案與目錄同一行程式碼，整棵子樹一起走）；覆寫＝把舊版本 hardlink 進回收桶。還原＝rename 出來，不是新動詞 | `00-…md` D6、D7 |

### 1.4 Decision C — 換一條規矩來守 wire

ADR 0024 §3 的「請求端不得命名檔案」在編輯上**不成立**，這件事 ADR 0024 §4 已經寫了。
本 ADR 要把接棒的那條規矩寫清楚：

> **請求端必須說出它以為自己在動哪一個版本。**

`filesystem.write`／`rename`／`delete` 三個型別各帶一個**必填**的 `precondition`，
只有兩種形狀：`{"absent": true}` 或 `{"revision": "sha256:<64 hex>"}`。
wire 上不存在 `force`、`overwrite`、`recursive`、`if_exists`。

**目錄不需要第三種形狀**：目錄的 revision 是它直屬項目清單的雜湊
（`00-…md` D3），所以「我要動的是我上次看到的那個資料夾」與
「我要覆寫的是我上次讀到的那個檔案」是同一句話、同一個欄位、同一個 412。
副作用是**你不能刪除一個你沒有打開過的資料夾** —— 那是對的。

**第四個型別 `filesystem.mkdir` 沒有 precondition**，而且送了會被 schema 拒。
`mkdir(2)` 在 syscall 層就不可能覆蓋任何東西，替它發明一個只有一種合法值的欄位，
會讓上面那條規矩從一條規矩退化成一種格式。規矩的正確說法是
**「每一個會破壞或取代東西的操作」**，不是「每一個操作」。

值得寫下它擋掉什麼，因為和 ADR 0024 §3 一樣便宜：
**覆寫別人剛寫的內容、刪掉一個已經被換掉的檔案、把更名蓋在一個新出現的同名檔上** ——
三個問題、三段檢查程式碼、一個共同入口。把入口關掉就沒有檢查程式碼會寫錯。

差別在於 ADR 0024 §3 關掉的是「命名」，本 ADR 關掉的是「無條件」。
**兩者都不是通則**：下一條寫入路徑要自己判斷它該關掉哪一個入口。

### 1.5 Decision D — 這不是 Web IDE，而線在這裡

`.agent/skills/cliora-project-context` 目前把 Web IDE 列為需要 requirements change
才能引入的東西。本 ADR 就是那個 requirements change，因此它有義務說出新的線在哪裡。

**交付**：單一檔案的編輯、顯式儲存、檔案與目錄的建立／更名／刪除、版本衝突偵測。
**不交付**：多檔未存緩衝、分頁列、跨檔重構、內建 git、LSP／自動完成／定義跳轉、
建置任務、編輯器內嵌終端機。

判準寫成一句可以貼進 skill 的話：

> **一次一個目標，一次一個明確的動作，每一個動作在節點上都是一個 syscall。**

（「一個 syscall」對目錄刪除仍然成立 —— 它是一個 `rename`。
走訪是**判斷**，不是動作；動作只有一個，而且要嘛全發生要嘛沒發生。）

這條線不是保守，它是把「編輯器」與「開發環境」分開：前者可以用一句話說出它對節點做了什麼，
後者不行。而「可以用一句話說出它對節點做了什麼」正是這個平台每一條路徑的共同性質 ——
`session.start` 只帶五個欄位、`daemon.update` 只帶版本號、`tunnel.open` 沒有 host。

### 1.6 Consequences

- **正面**：使用者可以在瀏覽器裡完成一輪完整的工作；ADR 0024 的 W1–W4 被證明可以承接
  第二條路徑（而且沒有一條需要修改）；敏感檔案政策與文字判定各只有一份實作，
  而它們現在同時守著兩個方向。
- **負面（要寫進 ADR，不能只寫在計畫裡）**：
  - **平台會覆寫與刪除使用者的原始碼。** 這是平台第一次**銷毀**使用者的資料
    —— 圖片投放只會增加檔案。回收桶把「不可回復」降級成「7 天內可回復」，
    但沒有把它變成「安全」。
  - **`SEC-001` 的地位第三次改變。** 唯讀時期繞過 `os.Root` 是讀到不該讀的；
    ADR 0024 之後是寫到不該寫的；現在是**覆寫或刪除**不該動的。
  - **rename-over 會換 inode。** 既有的 hardlink 斷開、CLI 已開啟的 fd 看到舊內容、
    inotify 的 watcher 可能漏事件。這是 `00-…md` D5 為了避免「寫到一半失敗＝資料損毀」
    付出的代價，要寫在 ADR 與 release note 兩處。
  - **`filesystem.write` 是第二個使用 8 MiB 訊框上限的請求型別**（第一個是
    `filesystem.upload`，ADR 0024 §7）。這次的內容是純文字而不是 base64 圖片，
    上限由 `max_preview_size` 決定而不是由訊框決定。
  - **稽核量會上升。** 顯式儲存（`00-…md` D12）把它壓在人手打字的速度上，
    但一個活躍的使用者一天會產生數十筆 `file.edit`。
  - **與 CLI 的寫入衝突是日常而不是例外。** CLI 一直在改檔案，所以 412 會經常出現，
    UI 的措辭不能把它講成錯誤。
- **與 ADR 0023 的關係**：與 ADR 0024 相同，「節點是可丟棄的 VM」**不延伸到本 ADR**，
  而且更硬 —— 重建 VM 不會還原被覆寫的原始碼。
- **目錄操作一次可以動到幾百個檔案**，這是本 ADR 與前一條寫入路徑在**形狀**上的差別，
  §1.2b 的走訪要求是它的代價，而超過上限的資料夾在瀏覽器上不可操作是它的另一個代價。
- **不在此決定**：下載、一般檔案上傳、多檔緩衝、三方合併、git 操作、
  非 UTF-8 檔案的編輯、目錄的內容比對（回收桶只保證整棵還得回來，不保證告訴你少了什麼）。

### 1.7 Alternatives rejected

| 方案 | 為什麼不 |
|---|---|
| 在既有 `filesystem.upload` 上加一個 `filename`，用它做編輯 | ADR 0024 §4 已經預先擋掉：那會白白引進路徑穿越與覆寫，而且**沒有換到任何東西** —— 編輯需要的是版本前提，不是命名能力 |
| 一個型別 `filesystem.mutate` 帶 `op` 欄位 | schema 會變成一串 `if/then`，而 `additionalProperties:false` 對每個 op 的保護會被稀釋；稽核與錯誤碼也會退化成「一個動作」。本 repo 既有的體例是每個動作一對型別 |
| 無條件寫入，衝突用「最後寫的贏」 | 那是把 CLI 剛寫的內容悄悄丟掉，而使用者不會知道。這條路徑沒有 undo（回收桶救得回檔案，救不回「我不知道我蓋掉了什麼」） |
| 用 mtime 當版本識別 | 格式化工具會在同一秒寫回同樣長度的內容，這正是最需要被擋住的情境 |
| 就地 `O_TRUNC` 寫入以保住 inode 與權限 | 寫到一半失敗就是資料損毀。用 temp＋rename＋複製權限，代價是換 inode（可承受、可預告），失敗代價是留下一個 `.part`（可清理） |
| 不做回收桶，改為刪除前顯示強確認 | 確認對話框對「誤點」有效，對「點錯了那一列」無效，而後者才是檔案樹上的實際失誤形狀。而且 ADR 0024 的 W2 第三腿會只剩形式 |
| 回收桶用複製而不是 rename／hardlink | 刪一個 1 GB 的檔案會變成複製 1 GB，刪一個資料夾會變成複製一棵樹，而且它會在磁碟最緊的時候被觸發 |
| 目錄只能建立、不能更名與刪除 | 使用者 2026-08-02 明確要求四個動詞都要涵蓋目錄。原本排除它的三條理由裡，兩條在回收桶改用 rename 之後消失（整棵子樹一個 syscall 搬得走、還原也一樣），剩下的一條變成 §1.2b 的走訪要求 |
| 目錄刪除要求先清空（`rmdir` 語意） | 安全但幾乎無用：使用者得逐檔刪到剩空殼。而且它會製造一個錯誤的心智模型（「刪除是逐項的」），下一個人就會照著做遞迴版本 |
| 遞迴刪除但不走訪子樹 | 那是本 ADR 每一條保護的萬用繞道（§1.2b） |
| 目錄刪除時逐檔搬進回收桶 | 一個目錄變成 N 次 syscall、N 個 trash 項目，還原要重建路徑，而且中途失敗會留下刪一半的樹 |
| 為目錄發明第三種 precondition（`{"kind":"directory"}`） | 它只說「這是個資料夾」，答不出「裡面還是我看到的那些嗎」，而後者才是遞迴刪除需要的保護 |
| 多檔未存緩衝 | 需要分頁列，而分頁列在 §1.5 那條線的另一邊；並且會讓 `useMonacoModel` 的 LRU 逐出變成悄悄丟棄未存內容 |
| 自動儲存 | 稽核會長出使用者沒意識到自己做過的事；而且對同一個工作區裡正在跑的 CLI 是持續的雜訊 |
| 編輯直接寫進終端機（`cat > file <<EOF`） | 「從前端執行任意 shell command」，正面違反 `SCOPE-011` 存活的那半條（ADR 0021 §1） |

---

## 2. ADR 0024 加註（`docs/adr/0024-workspace-write-posture.md`）

**不修改內容，只在 header 追加一行**，並在 §4 末尾追加一句：

```
- Followed by: ADR 0025 (workspace file editing), which is the "own ADR" §4 anticipated.
```

§4 末尾追加：

> *(2026-08-02: that ADR is 0025. Its answer to "the client necessarily names it"
> is a mandatory precondition on every destructive verb — the sender must state
> which version it believes it is acting on. W1–W4 were adopted unchanged.)*

**為什麼只加註不修訂**：ADR 0024 沒有一句話因為本期而變成錯的。
把它改掉會失去一件有價值的事實 —— 它在還沒有編輯功能的時候就正確預測了編輯需要什麼。

---

## 3. ADR 0015 修訂（`docs/adr/0015-…md`）

以第三段 amendment 追加（該 ADR 已有 2026-07-25 與 2026-08-01 兩段）：

1. **Limits 表**新增兩列：
   - `File write | 2 MiB / file (equal to max_preview_size by assertion), 2000 writes / day`
   - `Trash | 64 MiB / session, 7-day retention`
2. **Scope 段**：ADR 0024 已經把 "Out of P3: editing/upload/download" 改寫過一次
   （改成「還沒做」）。這次把 editing 從「還沒做」移出：
   `Editing, create, rename and delete are built (ADR 0025). Still not built:
   download, general file upload, directory create/rename/delete, multi-file
   buffers, git operations.`
3. **RBAC 段**：補一句 `file.write` 為 Admin＋Developer，Viewer 不持有。
   並註明「Viewer read-only」對 Viewer **仍然完全成立** —— 這是它第三次要被重讀，
   而它第三次仍然為真，因為 Viewer 一次都沒有拿到寫入權。
4. **Preview policy 段**：加一句 —— 預覽的上限現在同時是寫入的上限，
   兩者由 `TestWriteCapEqualsPreviewCap` 斷言相等。

---

## 4. PRD 修訂（`research/prd.md`）

### 4.1 `NFR-005.AC-142`（§23 產品核心原則第 7 條）— 二次改寫

現行文字（ADR 0024 於 2026-08-01 改寫）：

> 檔案總覽的**預覽**為唯讀；工作區的寫入僅經由平台明確定義的路徑，且每一條路徑
> 都必須經 `workspace.Root` 侷限、有配額與保留期、每次寫入留稽核、可由節點拒絕並回報
> （ADR 0024 的 W1–W4）。

建議改為：

> 工作區的寫入僅經由平台明確定義的路徑，且每一條路徑都必須經 `workspace.Root` 侷限、
> 有配額與保留期、每次寫入留稽核、可由節點拒絕並回報（ADR 0024 的 W1–W4）。
> 檔案總覽**預設**為唯讀；編輯是持有 `file.write` 者顯式切換的模式，
> 且僅限單一檔案、顯式儲存、帶版本前提（ADR 0025）。
> *（2026-08-02 二次修訂。原文的「預覽為唯讀」在編輯模式下不再完整為真。
> 兩次修訂被推翻的都是描述現況的那半句，W1–W4 一次都沒有動。）*

anchor `nfr-005-ac-142` **不變**。`lifecycle` 維持 `active`（它從來不是被撤銷，是被改寫），
新增一段 `review` 記錄二次修訂的日期與理由。

> **注意這一條與 §4.4 的分工**：核心原則講的是**姿態**（誰可以寫、要滿足什麼），
> `FR-FILE-010` 講的是**行為**（怎麼編輯）。兩邊都要改，但不要互相複製。

### 4.2 `NFR-005.AC-109`（§21 未來擴充方向第 18 項）— 再收窄

現行加註（2026-08-01）：

> *（2026-08-01：其中「把一張圖片交給 CLI」這一片已由 `FR-FILE-009` 交付。
> 下載、編輯、刪除、更名與一般檔案上傳仍為未來擴充。）*

改為：

> *（2026-08-02：編輯、建立、更名與刪除已由 `FR-FILE-010`／`FR-FILE-011` 交付。
> 仍為未來擴充的只剩：**下載**與**一般檔案上傳**。）*

`lifecycle` 維持 `active`。它剩下的兩片是真的還沒做，標成 deprecated 會讓需求庫
顯示這件事處理完畢。

### 4.3 `FR-FILE-002` 檔案預覽 — 加註（AC 文字不動）

`FR-FILE-002.AC-01`「使用者點擊檔案後，系統應以 Monaco Editor 唯讀顯示」
的 **anchor 與文字都不動**，在該需求末尾加一段註記：

> 預覽**預設**為唯讀。持有 `file.write` 的使用者可顯式切換為編輯模式，
> 見 `FR-FILE-010`；切換前後都是同一個 Monaco 實例，未切換時 `readOnly` 與
> `domReadOnly` 皆為真。

理由沿用 p13 §2.1：改 AC 文字會讓 traceability 的既有連結全部要重驗，
而本期真正新增的是一個模式，那應該是新需求。

### 4.4 新增 `FR-FILE-010` 檔案編輯

放在 `research/prd.md` §8.8（`FR-FILE-009` 之後），anchor `fr-file-010`，
`owner: central`、`applicability: ["mvp"]`、`criticality: "should"`：

| AC | 內容 | verification_profile | risk |
|---|---|---|---|
| AC-01 | 持有 `file.write` 的使用者可將預覽切換為編輯模式；未持有者看不到入口 | automated | medium |
| AC-02 | 編輯模式為顯式切換，不自動啟用；儲存之前不寫入節點 | automated | medium |
| AC-03 | 儲存必須帶上讀取時取得的版本識別；版本不符時拒絕寫入並告知，且不覆寫 | automated | critical |
| AC-04 | 未修改內容的儲存必須產生與原檔位元組完全相同的檔案（換行字元、BOM、結尾換行、行尾空白皆不變） | automated | high |
| AC-05 | 寫入不得改變既有檔案的權限模式 | automated | high |
| AC-06 | 同一時間僅允許一個未儲存的檔案；切換檔案、切換 Session 或離開頁面前必須先儲存或捨棄 | automated | medium |
| AC-07 | 不提供自動儲存 | inspection | low |
| AC-08 | 每一次寫入留下稽核紀錄（使用者、Session、節點、相對路徑、位元組數、前後版本識別），不記內容 | automated | high |
| AC-09 | 節點可停用寫入並回報；停用時前端不顯示編輯入口 | automated | medium |
| AC-10 | 可編輯的大小上限與可預覽的大小上限相同 | automated | medium |

### 4.5 新增 `FR-FILE-011` 檔案與目錄的建立、重新命名與刪除

anchor `fr-file-011`，`owner: central`、`applicability: ["mvp"]`、`criticality: "should"`：

| AC | 內容 | verification_profile | risk |
|---|---|---|---|
| AC-01 | 可在指定目錄建立新檔案；同名項目已存在時拒絕，且不覆寫 | automated | high |
| AC-02 | 可重新命名檔案與目錄（含移動至工作區內其他位置）；目的地已存在時拒絕 | automated | high |
| AC-03 | 可刪除檔案與目錄；刪除必須帶版本識別 | automated | critical |
| AC-04 | 被覆寫或刪除的內容保留 7 天後由 Daemon 清除，期間使用者可自行取回；刪除的目錄取回時，其子樹結構、內容與權限皆與刪除前相同 | automated | high |
| AC-05 | 敏感檔案規則（`FR-FILE-005`）在寫入方向同樣適用，且對重新命名的來源與目的地都適用 | automated | critical |
| AC-06 | `.git/` 之下不得建立、修改、重新命名或刪除，且 git worktree 中作為**檔案**存在的 `.git` 同樣受保護 | automated | critical |
| AC-07 | 不得經由 symlink 寫入，也不得建立 symlink | automated | critical |
| AC-08 | 可建立目錄；建立檔案或目錄時自動補齊不存在的父目錄 | automated | low |
| AC-09 | 目錄的重新命名與刪除，在其子樹含有任何依 AC-05／AC-06 受保護的項目、或項目數超過上限時**整個拒絕**，且不得部分執行 | automated | critical |
| AC-10 | 工作區根目錄不得被重新命名或刪除 | automated | critical |
| AC-11 | 建立、重新命名與刪除各自留下稽核紀錄；刪除目錄時紀錄其項目數 | automated | high |

AC-09 與 AC-10 是**目錄納入範圍才存在的兩條**，而且是本需求風險最高的兩條：
一次操作可以動到幾百個檔案，所以「不得部分執行」與「根目錄不可刪」
必須是需求層級的承諾，不是實作細節。

### 4.6 `research/tech.md` 修訂

- **§11.5 檔案讀取**：「寫入僅有一條路徑」那一句改為兩條（`.cliora/uploads/` 與編輯面），
  並在設定範例補上 `filesystem.editing`。
- **§11.7 敏感檔案規則**：補一句「同一份規則同時適用於寫入方向；
  重新命名的來源與目的地都要通過」。
- **新增 §11.10 檔案與目錄編輯**：四個動詞的 default-deny 順序、
  兩種版本識別的定義與計算、原子寫入與權限複製、目錄操作的子樹走訪與上限、
  回收桶配置（刪除用 rename、覆寫用 link）與清理、`.git` 的兩種形式、設定鍵。
  格式沿用 §11.9（圖片投放）。

---

## 5. Traceability 註冊

`WE-02` 要在 `traceability/` 完成五件事，並讓 `scripts/trace validate --level static` 通過：

| 檔案 | 動作 |
|---|---|
| `requirements.json` | 新增 `FR-FILE-010`（10 AC）、`FR-FILE-011`（11 AC）；`NFR-005.AC-142` 維持 `active` 並新增二次修訂的 `review`；`NFR-005.AC-109` 更新 `review` 註記；`FR-FILE-005` 新增 `review` 說明它現在同時守寫入方向 |
| `links.json` | 把 21 條新 AC 連到 `02`–`05` 各節的實作與測試；`FR-FILE-002` 既有連結補上「編輯模式下 `readOnly` 切換」的測試；`FR-FILE-003`／`FR-FILE-004` 補上寫入方向的連結 |
| `gates.json` | 新增 `GATE-WE-NO-UNCONDITIONAL-WRITE`、`GATE-WE-ROUNDTRIP`、`GATE-WE-WRITE-POLICY`（`06-…md` §3） |
| `waivers.json` | 不新增。若 `WE-01` 第 1 項（`os.Root.Link`）不成立而回收桶要改設計，那是 ADR 修訂不是 waiver |
| `baseline-debt.json` | 不動 |

PRD 的每一條新 AC 都要有 `<a id="…"></a>` anchor，且與 `source_anchor` 完全一致
—— static gate 會檢查這件事。

---

## 6. `.agent/skills` 修訂（`WE-10`）

五份 SKILL.md，改動幅度以「一段」為限（`AUTHORING.md`：不複製 canonical research，
`SKILL.md` 保持 imperative、single-purpose、500 行以內）。

| Skill | 改什麼 | 為什麼是這一份 |
|---|---|---|
| `cliora-project-context` | (1)「Do not introduce … a Web IDE …」那條非目標**保留**，但補上本期移動後的線（`§1.5` 那一句）；(2) 工作區寫入姿態那一段補上第二條路徑與它守的規矩（「請求端必須說出它以為自己在動哪一個版本」），並明確說 ADR 0024 §3 的「不得命名」**沒有**被推廣 | 它是入口 skill，下一個人第一個讀到的就是它。線畫在哪裡如果不在這裡，就等於沒畫 |
| `go-daemon-development` | 第 6 點（寫入路徑的測試清單）補四項：版本前提不符、往返位元組相同、權限保留、**批次操作在任一項被拒時整體不執行**；正文那一長段補上「破壞性操作前先把舊版本移進回收桶」與「用 fd 的 `Chmod` 而不是路徑形式」 | 它已經有一段講寫入路徑，本期是往同一段加，不是新增一段 |
| `vue-naive-ui-workflow` | 補一段編輯器的規矩：唯讀是預設、dirty 只能有一個、逐出與 session 切換不得丟棄未存內容、`trimAutoWhitespace` 之類會偷改內容的設定要關 | 「Monaco model 要有唯一 owner 並 dispose」那一句在有 dirty 狀態之後不完整 —— dispose 一個 dirty model 就是資料遺失 |
| `cliora-security-review` | 檢查清單補一項：寫入方向的敏感檔案與 `.git` 保護、版本前提、回收桶 | 它現在列的是「sensitive/binary/oversized file denial」，那是讀取方向的說法 |
| `backend-developer` | 補半句：破壞性 HTTP 端點使用 `If-Match`／`If-None-Match`，缺前提回 428、不符回 412 | 它負責 API 層的體例，而本期新增的是一組新的狀態碼用法 |

`.agent/skills/README.md` 的 skill 計數與分類不動（沒有新增 skill），
但「Last updated」日期要改 —— 那個欄位的用途就是讓人知道索引是不是舊的。
