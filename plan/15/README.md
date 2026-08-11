# Cliora 一般檔案上傳：把檔案拖進檔案瀏覽器

本目錄交付 2026-08-03 由使用者指示的一件事，ticket 統一使用 `FU-` 前綴
（**F**ile **U**pload）：

> 經過考慮後我認為 ./plan/14 改動過大要作廢，實際上使用者只需要將檔案上傳到
> workspace 底下的目錄，要可以將檔案拖拉進檔案瀏覽器中，其餘就用 cli 或是 terminal 處理

**取代 [`plan/14`](../14/README.md)**（工作區檔案編輯），該目錄保留為歷史 ——
與 `plan/10`（自建 tunnel，因成本被否決）同一個做法。

## 這一期真正的形狀

它是 ADR 0024 的 rejected 表裡那一列的設計：

> | Open general file upload, since writes are allowed now | Withdrawing read-only
> did not remove the boundary. **W2/W3/W4 must hold for general upload too, and
> they are not designed for it** — starting with what a quota means for arbitrary
> file sizes. |

那不是「永遠不做」，是「還沒設計」。本期去設計那三條：
W2 在 `00-…md` D5（並且需要修訂 ADR 0024 的措辭）、W3 在 D8、W4 在 D7。

同時它是 ADR 0024 §4 明白預告的第二種情況：

```
              ADR 0024 §3（圖片投放）        ADR 0026（本期）
              ──────────────────           ────────────────
  wire        沒有 filename／path          有 directory ＋ filename
  為什麼      截圖不需要名字，所以連       requirements.txt 的名字
              路徑穿越的入口都沒有         就是它的全部意義
  怎麼安全    把入口關掉                   O_EXCL、0644、名字與位置
                                            都過讀取面同一份政策
  型別        filesystem.upload            filesystem.store（新增）
              ── 一個位元組都不動 ──
```

ADR 0024 §4 同時警告了兩個相反的錯誤，本期兩個都不犯：
不拿「請求端不得命名」當先例主張任何路徑都不能指名（那會做不出這個功能），
也不回頭在 `filesystem.upload` 上加一個 `filename`（那會白白弄壞一條已經正確的路徑）。
**兩個型別並存，各自的規矩各自成立。**

## 為什麼這一份比 `plan/14` 小這麼多

`plan/14` 的機制沒有一項是多餘的 —— 版本前提、412、回收桶、undo、
dirty 狀態機、目錄子樹走訪，每一項都是某個動詞的必要條件。**問題在動詞太多。**

本期只有一個動詞，而且是**唯一一個不會破壞任何既有東西的**那一個：

| `plan/14` 的機制 | 本期為什麼不需要 |
|---|---|
| `revision`／`precondition`／412／428 | 它們只為「覆寫」存在。本期 `O_EXCL`，永不覆寫 |
| `.cliora/trash/`、7 天清理、還原 | 它們只為「刪除與覆寫」存在。本期沒有任何位元組會消失 |
| 目錄的有界子樹走訪 | 它只為「遞迴刪除／更名」存在 |
| Monaco 編輯模式、dirty、往返位元組測試、衝突橫幅 | 它們只為「編輯」存在 |
| `file.write` action ＋ seed migration | 本期沿用 `file.upload` |

**一句話：不覆寫、不刪除，機制就整批消失了。**
使用者指示的最後半句「其餘就用 cli 或是 terminal 處理」不是客套，
它是一條範圍指令 —— 而那條指令買下的就是上面這整張表。

## 這一期最容易做錯的六件事

1. **加一個 `overwrite` 旗標。** 那是 `plan/14` 的第一步，然後上面那張表會一項一項回來。
   `GATE-FU-NO-OVERWRITE` 守它，而那個 gate 守的不只是安全，是**規模**。
2. **弄壞圖片投放。** 它兩天前才上線，而本期會動到它三個地方
   （`_read_bounded_body` 抽出、`uploadWithProgress` 抽出、稽核多一個 `source`）。
   exit 條件第 8 項就是「它的既有測試與 fixture 全綠且未被修改」。
3. **靜默改名。** 同名時自動變成 `data (1).csv` 會讓 CLI 讀到舊的那一份，
   而使用者以為它讀到新的 —— 症狀是「AI 看的是舊資料」，而那種 bug 很難被歸因到上傳。
   同名一律拒絕，並給一個預填的改名框（D2、`04-…md` §2.4）。
4. **把 `filename` 和 `directory` 合成一個 `path` 欄位。** 那需要一段驗證程式碼去確認
   「最後一個片段就是使用者打的名字」，而路徑穿越正是從那段程式碼長出來的。
   兩個欄位讓「檔名裡有斜線」在 wire 上不可表達（`03-…md` §1.2）。
5. **靜默擴大 `file.upload` 的語意。** 它從「投放截圖到平台自有目錄」
   變成「把檔案放到工作區裡的一個位置」。這是本期唯一一個對既有授權的改動，
   要放在 release note 的**第一段**而不是附註（D8、`05-…md` §2）。
6. **忘記 git worktree 的 `.git` 是一個檔案。** 而且**今天 `.git` 完全沒有被保護** ——
   它只在 `excluded_directories`（那份清單的註解明寫「不是安全控制」），
   `denied_directories` 的預設值裡沒有它。本期讓客戶端可以指名落地位置，
   所以這個缺口必須同期補上（`01-…md` §5）。

## 一件本期刻意不做而必須誠實寫下來的事

ADR 0024 的 `FILE_UPLOAD_QUOTA_EXCEEDED` 錯誤訊息一直在叫使用者
「請在檔案樹的 `.cliora/uploads/` 刪除不需要的圖片」——
而本期**不做刪除**，所以那件事仍然做不到。

處置是**改那句文案**（改成「請在節點上以終端機刪除」），
不是留著一個明知為假的指示。這是本期唯一一處會動到圖片投放文案的地方
（`05-…md` §2 第 3 項）。

## 一件 ADR 0024 需要被修訂的事

W2 寫「per-operation size, cumulative quota, and a retention period — **all three**」。
本期的落地位置是**使用者選的**，所以七天後把那個檔案刪掉會是災難而不是紀律。

W2 的正確形狀因此是：**保留期只對平台自有的目的地成立；
使用者選定的位置以「可見性」取代它** —— 每一個位元組都落在使用者選的、
看得見的路徑上，由他自己清理，與他的 CLI 寫出來的檔案沒有兩樣。
磁碟填滿的風險由**可用空間下限**直接擋住（`00-…md` D5、`01-…md` §2）。

**這是修訂而不是 waiver**：規矩的目的在兩種目的地上有兩種正確形狀。
把它寫成修訂，下一條寫入路徑才會問對的問題（「這個位置誰負責清」），
而不是照抄一個 7 天。

## 檔案

| 檔案 | 內容 |
|---|---|
| `00-execution-plan.md` | 成功定義（九項判準）、範圍、固定基線決策 D0–D12、波次與 ticket、風險 |
| `01-decisions-and-governance.md` | ADR 0026、ADR 0024 的 W2 修訂、PRD 三處修訂、traceability、`.git` 的既有缺口、**`plan/14` 帶過來與沒帶過來的東西**、兩份 skills |
| `02-daemon-store-path.md` | `FU-03`：`StatIn` 與 `ErrExists`、位置與名字的政策、`Store` 的八個步驟、可用空間、配額、設定、`doctor` |
| `03-contract-central-and-rbac.md` | `FU-04`／`FU-05`：契約 v1.9.0（一對型別、`file_upload`、六個 fixture）、HTTP 端點、沿用的 RBAC 與稽核、錯誤碼、metrics、migration `0020` |
| `04-frontend-drop-target.md` | `FU-06`：放置目標的三條推導、資料夾的擋法、上傳佇列、改名流程、顯示條件 |
| `05-verification-and-exit.md` | `FU-07`／`FU-08`：測試清單、evidence、兩個 gate、runbook、release note、安全審查七題、exit 條件 |
| `06-implementation-status.md` | 實作進度（**計畫完成，全部未開始**） |
| `07-open-measurements.md` | `FU-01` 四項待實測，其中一項是閘門；以及「沒有要量什麼、為什麼」 |

規範來源一律回指 `research/prd.md`、`research/tech.md`、`docs/adr/`，本目錄不複製需求內容
（`.agent/skills/AUTHORING.md`「Never duplicate canonical research」）。
`.agent/skills` 本身的更新是 `FU-07`（`01-…md` §7）。

## 不需要只做一半

只有一個動詞、一條路徑、一個節點開關，拆開出貨不會讓任何一半更早可用。
唯一的方向性建議是前端（`FU-06`）可以晚於後端（`FU-05`）——
有能力但沒有入口是安全的方向，反過來不是（`05-…md` §6）。
