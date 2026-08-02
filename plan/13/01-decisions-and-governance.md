# 01 — 決策與治理（`WF-02`）

本文件是 `WF-02` 的交付內容：一份新 ADR、一份既有 ADR 的修訂、四處 PRD 修訂、
以及 traceability 的註冊。**核准之前不得動 daemon 程式碼**（`00-…md` §4）。

規範來源一律回指 `research/prd.md`、`research/tech.md`、`docs/adr/`；本目錄不複製需求內容。

---

## 1. ADR 0024：工作區寫入姿態與圖片投放（新增）

檔案：`docs/adr/0024-workspace-write-posture.md`，狀態 `proposed` → `WF-02` 核准後 `accepted`。

> **2026-08-01 使用者指示，本 ADR 的性質因此改變：**
> 「已經可以撤銷唯讀工作區了，日後會朝向可編輯，平台可以寫進使用者工作區。」
>
> 所以這不是「在唯讀邊界上開一個例外」的 ADR，而是**撤銷唯讀姿態**、
> 並為之後每一條寫入路徑立下規矩的 ADR。圖片投放是它的第一個實例，不是它的全部。
> 這個區別是實質的：例外會被當成一次性的特許，姿態變更會被當成新的預設 ——
> 而使用者要的是後者。

### 1.1 Context

平台到今天為止，對節點檔案系統只有一條路徑，而且是唯讀的（ADR 0014、ADR 0015）。
唯讀不只是實作現況，它是**寫在產品核心原則裡**的一條：
`research/prd.md` §23 的「檔案總覽第一階段採唯讀模式」（`NFR-005.AC-142`）。
ADR 0015 的 Scope 段（"Out of P3: editing/upload/download"）與 §21 未來擴充方向
第 18 項（`NFR-005.AC-109`）是它的兩個下游。

使用者的即時需求是「從網頁直接把圖片放進 CLI」。這件事在技術上沒有第二條路：
claude 與 codex 讀的是**節點本機的檔案**，而位元組在瀏覽器裡，所以位元組必須跨過那條邊界。
使用者同時表明了方向：唯讀可以撤銷，之後會走向可編輯。

**因此本 ADR 要做兩件事，而且要分開做**：撤銷一條核心原則（§1.2），
以及交付一條具體的寫入路徑（§1.3）。分開做的理由在 §1.4 ——
它們的存活條件不同，混在一起寫，下一條寫入路徑會拿錯的東西當先例。

### 1.2 Decision A — 撤銷唯讀姿態，並立下寫入路徑的四條共同規矩

「工作區唯讀」不再是產品不變量。取而代之的是：**每一條寫入路徑，
無論現在的圖片投放或未來的檔案編輯，都必須同時滿足這四條**：

| # | 規矩 | 為什麼它必須跨越所有寫入路徑 |
|---|---|---|
| W1 | **經 `workspace.Root`**（`os.Root`／`RESOLVE_BENEATH`），不得有吃絕對路徑的寫入 | 這是 ADR 0014／`SEC-001` 唯一還在守著的東西。唯讀撤銷之後，它從「多一層保險」變成**唯一**的那層 |
| W2 | **有上限、有清理**：單次大小、累計配額、保留期三者齊備 | 一條沒有上限的寫入路徑就是一個磁碟填滿的入口。這條不能等到「之後再補」，因為補的時候會發現要改的是資料模型 |
| W3 | **每一次寫入都留稽核**：誰、哪個 session、哪個節點、寫了什麼形狀（不記內容） | 唯讀時期「誰改了這個檔案」不是平台要回答的問題。撤銷之後它是 |
| W4 | **節點可以拒絕**，並把拒絕的事實回報給平台 | 不是每台機器的工作區都可以被平台寫。沿用 1.7.0 的 report-only 形狀 |

**W1–W4 是本 ADR 真正的產出。** 圖片投放（§1.3）滿足這四條；
未來的編輯功能也必須滿足這四條，而它會需要**自己的** ADR 去決定四條之外的事
（衝突處理、並行寫入、備份、undo）—— 那些不是這一期能一起決定的。

### 1.3 Decision B — 這一期交付的那一條路徑：圖片投放

形狀由五條限制固定死：

1. **只有圖片**：`image/png`、`image/jpeg`、`image/gif`、`image/webp`，以 magic number 判定，
   不採信宣告的 `Content-Type`。
2. **只有一個目錄**：工作區內的 `.cliora/uploads/<YYYY-MM-DD>/`，路徑由 daemon 組出。
3. **檔名由 daemon 決定**：`<ULID>.<嗅探到的副檔名>`。wire 上不存在 `filename`／`path`／
   `directory`／`extension` 欄位；瀏覽器送的是位元組。
4. **有上限**：單張 4 MiB、每 session 64 MiB、每日 200 張、7 天後清除。
5. **可以被節點關掉**：`filesystem.upload.enabled`，並以 `node-register.image_upload` 回報。

路徑進入 CLI 的方式是**前端以 writer 身分把相對路徑打進終端機**，
不是平台注入輸入；因此本 ADR 不新增任何對終端機的寫入權限。

### 1.4 Consequences

- **正面**：使用者可以把截圖交給 CLI，這是 CLI 協作最常見的缺口；
  整條路徑重用 P3 的 `os.Root` 封閉性，不需要第二套路徑安全；
  而且下一條寫入路徑（編輯）有一份已經寫好的 W1–W4 可以照著做，不必重新辯論一次。
- **負面（要寫在 ADR 裡，不能只寫在計畫裡）**：
  - 「工作區唯讀」這句話從今天起是錯的，而且錯的範圍比這一期的實作大得多 ——
    撤銷的是**姿態**，交付的只有一條路徑。所有依賴唯讀的敘述
    （`NFR-005.AC-142`、ADR 0015 的 Scope 與 RBAC 段、`docs/p3-report.md`、
    前端「唯讀」標示、`.agent/skills`）都要一起改，而它們改完之後，
    平台的預設答案從「不能寫」變成「這條路徑還沒做」。
  - **`SEC-001` 的地位改變了。** 唯讀時期，即使 `os.Root` 被繞過，最壞結果是讀到不該讀的檔案。
    撤銷之後，同一個繞過就是寫到不該寫的地方。W1 因此不是四條裡的第一條，
    它是**另外三條的前提**，安全審查要單獨對它加壓（`06-…md` §5 第 1 題）。
  - `filesystem.upload` 是 1.3.1 之後第一個使用 8 MiB 訊框上限的**請求**型別，
    方向是 Central→daemon。節點側的解碼上限對這一個型別放寬了 128 倍。
  - 平台會在使用者的程式碼庫裡建立一個目錄並寫入 `.gitignore`。這是平台第一次
    寫入非自己管理的檔案樹。
- **與 ADR 0023 的關係**：ADR 0023 D0 的「節點是可丟棄的 VM」**不延伸到本 ADR**，
  而且撤銷唯讀之後這一句更硬：重建 VM 不會還原被寫壞的工作區內容
  —— 那是使用者的程式碼，不是節點的狀態。本 ADR 的 Context 要明寫（`00-…md` D0）。
- **對未來編輯功能的約束**：本 ADR **不**授權編輯，也不預先核可它的形狀。
  它只保證兩件事：W1–W4 對編輯同樣成立；以及 §1.3 的第 3 條
  （請求端不得命名檔案）**不是**通則 —— 見 §1.5。

### 1.5 一個必須寫下來的界線：D2 不能被當成先例

`00-…md` D2「請求端不得命名檔案」在圖片投放上成立，是因為**圖片沒有身分**：
使用者不在乎那張截圖叫什麼，他在乎 CLI 讀不讀得到。

**編輯功能不是這樣。** 編輯的本質就是「改**這一個**檔案」，客戶端必須能指名。
所以未來那條路徑一定會有一個 `path` 欄位，而它需要的是**另一套**防護
（路徑正規化、`RealRel` 綁 inode、敏感檔案政策也要套用在寫入方向、
不得建立 symlink、不得寫入 `.git/`）。

把這句話寫進 ADR，是為了擋掉兩種相反的錯誤：
一種是有人拿 ADR 0024 當先例，主張「編輯也不該讓前端指定檔名」（那會做不出編輯）；
另一種是有人拿編輯當先例，回頭在 `filesystem.upload` 上加一個 `filename`
（那會白白引進路徑穿越與覆寫，而且**沒有換到任何東西**）。

### 1.6 Rejected alternatives

| 方案 | 為什麼不 |
|---|---|
| 這一期就一併交付編輯 | 使用者說的是方向，不是這一期的範圍。編輯要決定衝突處理、並行寫入、敏感檔案在寫入方向的政策、`.git/` 的保護 —— 每一項都比圖片投放大。W1–W4 先立好，編輯才有地基 |
| 只做圖片投放、不撤銷唯讀姿態 | 那會讓實作與 `NFR-005.AC-142` 相衝突，而衝突的那一方向來是規範被默默忽略。使用者已經明示撤銷，把它寫下來的成本是一次 PRD 修訂 |
| 開放一般檔案上傳（作為「反正都可寫了」的推論） | 撤銷唯讀不等於沒有邊界。W2／W3／W4 對一般檔案上傳同樣要成立，而它們今天沒有被設計 —— 尤其是 W2 的配額對任意大小的檔案要怎麼訂 |
| 圖片存在 Central、把 URL 交給 CLI | CLI 要能連外並帶著平台的認證憑證才讀得到；那會把節點變成平台 API 的客戶端，是一條比寫檔大得多的授權變更 |
| 用終端機的 base64 貼上（例如 `base64 -d > file`） | 那是「從前端執行任意 shell command」，正面違反 `SCOPE-011` 存活的那半條 |
| 讓 Central 把路徑注入終端機 | 開出一條平台可對任何 session 打字的通道，且繞過 single-writer |
| 走 SFTP／SSH | ADR 0021 與產品非目標都明確排除 Central SSH |

---

## 2. PRD 修訂（`research/prd.md`）

### 2.1 `FR-FILE-004` Binary 判斷 — 修訂 AC 並新增註記

現行四條 AC 講的是「被判為 Binary 之後要顯示什麼」，這部分**不變**。
新增一段註記，說明判定的兩件事：

- 判定範圍是**已讀取的完整內容**（≤ `max_preview_size`），不是前 8 KB。
  這一句同時取代 `research/tech.md` §11.6 第 1 點「讀取前 8 KB」。
- 「無法以 UTF-8 解讀」與「二進位」是**兩件事**，畫面上要分開講
  （`unsupported_encoding` vs `binary`）。

`FR-FILE-004.AC-03`（顯示「不支援預覽」）因此得到一個更精確的下位規則，
但 AC 本身的 anchor 與文字不動 —— 改動 AC 文字會讓 traceability 的既有連結全部要重驗，
而這一期真正新增的是準確度要求，那應該是一條新需求（§2.3）。

### 2.2 兩條需要重新分類的 criterion（**不是**原先計畫的那一條）

撰寫計畫時原本只打算收窄 `NFR-005.AC-109`。核對需求庫之後有兩點修正：

1. **真正的唯讀不變量不在 §21，而在 §23「產品核心原則」**：
   `NFR-005.AC-142`「檔案總覽第一階段採唯讀模式」。要撤銷的是**這一條**。
2. `lifecycle` 的合法值只有 `proposed`／`active`／`deprecated`／`retired`
   （`traceability/schema/requirements.schema.json`）。**沒有 `narrowed`**
   —— `SCOPE-011.AC-01` 的先例用的是 `deprecated` ＋ `review`。

#### `NFR-005.AC-142` — 撤銷（`deprecated`）

```jsonc
{
  "id": "NFR-005.AC-142",
  "source_anchor": "nfr-005-ac-142",
  "verification_profile": "inspection",
  "risk": "high",
  "lifecycle": "deprecated",
  "review": {
    "classified_by": "product",
    "classified_at": "<WF-02 核准日>",
    "rationale": "Withdrawn by product decision (2026-08-01): the workspace is no longer read-only, and an editable workspace is a stated direction. Replaced by ADR 0024's four rules that every write path must satisfy — confined by workspace.Root, bounded by quota and retention, audited per write, refusable by the node. The first such path is image drop (FR-FILE-009). Preview itself remains read-only; FR-FILE-002.AC-01 is unaffected.",
    "approved": true
  }
}
```

PRD §23 那一行同時改寫，不要留一句被 traceability 標記為 deprecated 卻仍在文件裡
宣稱唯讀的話 —— 讀 PRD 的人不會去讀 `requirements.json`。
建議改為：「檔案總覽的**預覽**為唯讀；工作區的寫入僅經由平台明確定義的路徑，
且每一條路徑受 ADR 0024 的四條規矩約束。」

#### `NFR-005.AC-109` — 維持 `active`，加註部分交付

「Web 端上傳與下載檔案」在 §21「未來擴充方向」，它**大部分仍是未來**
（下載、編輯、刪除、一般檔案上傳都沒做）。不該標成 deprecated，
那會讓需求庫顯示這件事已經處理完畢。維持 `active`，加一段 `review` 記錄
「圖片這一片由 `FR-FILE-009` 交付」即可。

**為什麼要這麼麻煩：** 因為六個月後有人會問「不是說工作區唯讀嗎」。
上面那兩段話是唯一能回答這個問題的東西，而它必須在需求庫裡，
不是在某個 PR 的討論串裡。

### 2.3 新增 `FR-FILE-008` 文字判定準確度

放在 `research/prd.md` §8.8（`FR-FILE-007` 之後），anchor `fr-file-008`：

| AC | 內容 | verification_profile |
|---|---|---|
| AC-01 | 完全合法的 UTF-8 文字檔不得被判為不可預覽，與檔案大小無關 | automated |
| AC-02 | 含 ANSI escape sequence 的文字檔（終端機輸出、建置 log）視為文字 | automated |
| AC-03 | 含 NUL 位元組的檔案一律不可預覽，與該位元組出現在檔案何處無關 | automated |
| AC-04 | 判定必須有一份可執行的分類 corpus，且 corpus 全數符合期望 | measurement |
| AC-05 | 2 MiB 檔案的判定耗時不得超過 5 ms | measurement |

`owner: daemon`、`applicability: ["mvp"]`、`criticality: "should"`。
AC-03 是刻意寫進來的**收緊**條款：它今天不成立（`08-…md` §2），
而本期的改動同時修好兩個方向。把它寫成需求，是為了讓「放寬」這件事有一個對稱的約束。

### 2.4 新增 `FR-FILE-009` 圖片投放

放在 `FR-FILE-008` 之後，anchor `fr-file-009`，`owner: central`、`criticality: "should"`：

| AC | 內容 | verification_profile |
|---|---|---|
| AC-01 | 持有 `file.upload` 的使用者可從瀏覽器把一張圖片交給 session 所在節點 | automated |
| AC-02 | 支援貼上、拖放、挑檔三種入口，三者行為一致 | automated |
| AC-03 | 落地路徑與檔名由 daemon 決定；請求不得包含檔名、路徑或目錄 | automated |
| AC-04 | 僅接受 png／jpeg／gif／webp，且以內容而非宣告的型別判定 | automated |
| AC-05 | 單張 4 MiB、每 session 64 MiB、每日 200 張上限，逾越時明確拒絕且不落地 | automated |
| AC-06 | 上傳成功後，工作區相對路徑以 writer 身分送入終端機輸入行，不自動送出 | automated |
| AC-07 | 每次上傳留下稽核紀錄（使用者、session、節點、mime、位元組數、相對路徑） | automated |
| AC-08 | 節點可停用此功能並回報；停用時前端不顯示投放入口 | automated |
| AC-09 | 逾期（7 天）的上傳檔案由 daemon 清除 | measurement |

### 2.5 `research/tech.md` 修訂

- **§11.5 檔案讀取**：檢查清單新增一行「是否可寫入（僅 `.cliora/uploads/`）」，
  並在設定範例補上 `filesystem.upload`。
- **§11.6 Binary 判斷**：第 1 點「讀取前 8 KB」改為「掃描已讀取的完整內容」，
  並補上兩句實測結論：UTF-8 驗證必須落在 rune 邊界（否則多位元組文件會被誤判）、
  ESC／FF／VT 視為文字。
- **新增 §11.9 圖片投放**：目錄配置、命名、嗅探、配額、清理、設定鍵。

---

## 3. ADR 0015 修訂（`docs/adr/0015-…md`）

以「Amendment (`WF-02` 核准日)」的形式追加，沿用該 ADR 既有的修訂體例
（它已經有一段 2026-07-25 的 amendment）：

1. **Limits 表**：`Binary sniff window | first 8 KiB` 改為
   `Text/binary classification | whole read buffer (≤ max_preview_size)`，
   並新增一列 `Image upload | 4 MiB / file, 64 MiB / session, 200 / day, 7-day retention`。
2. **Scope 段**：`Out of P3: editing/upload/download` 改寫為
   `The read-only posture this ADR assumed is withdrawn (ADR 0024). Still not built:
   editing, download, delete, rename, general file upload. The one write path that
   exists today is image drop; any future path must satisfy ADR 0024's W1–W4.`
   **注意措辭**：是「還沒做」，不是「不做」—— 這是撤銷姿態之後語氣必須改變的地方。
3. **RBAC 段**：補一句 `file.upload` 為 Admin＋Developer，Viewer 不持有；
   並註明 P3 那句「Viewer read-only, consistent with P2's read-only viewer attach」
   對 **Viewer** 仍然成立（Viewer 沒有任何寫入權），但它不再描述整個系統的姿態。

---

## 4. Traceability 註冊

`WF-02` 要在 `traceability/` 完成四件事，並讓 `scripts/trace validate --level static` 通過：

| 檔案 | 動作 |
|---|---|
| `requirements.json` | 新增 `FR-FILE-008`（5 AC）、`FR-FILE-009`（9 AC）；`NFR-005.AC-142` 改為 `deprecated` 並加 `review`；`NFR-005.AC-109` 維持 `active` 並加註部分交付（§2.2） |
| `links.json` | 把新 AC 連到 `02`–`05` 各節的實作與測試；`FR-FILE-004` 既有連結補上新的 corpus 測試 |
| `gates.json` | 新增 `GATE-WF-CLASSIFY-CORPUS` 與 `GATE-WF-NO-NAMING-CHANNEL`（`06-…md` §3） |
| `waivers.json` | 不新增。若 `WF-01` 第 3 項不成立而 `FR-FILE-009` 要延後，走 `waivers.json` 而不是把 AC 刪掉 |

PRD 的每一條新 AC 都要有 `<a id="…"></a>` anchor，且 anchor 與 `source_anchor` 完全一致
—— static gate 會檢查這件事。

---

## 5. `.agent/skills` 修訂（`WF-09`）

三份 SKILL.md，各改一段不變量，改動幅度以「一段」為限（`AUTHORING.md`：不複製 canonical research）：

| Skill | 改什麼 |
|---|---|
| `cliora-project-context` | 「allowed-root read-only MVP access」這句話不再完全為真。改為：唯讀 ＋ 一條由 daemon 命名的圖片寫入路徑；並補一句「請求端不得命名檔名或路徑」，與既有的「不得命名啟動參數」並列 |
| `go-daemon-development` | 補上：任何工作區寫入必須經 `workspace.Root`；檔名由 daemon 產生；新增寫入面時要同時加配額與清理 |
| `vue-naive-ui-workflow` | 補上：終端機的貼上攔截只在 `clipboardData.files` 非空時接手；投放入口同時受 `file.upload` 與 writer 角色控制 |

`.agent/skills/README.md` 的 skill 計數與日期不動（沒有新增 skill）。
