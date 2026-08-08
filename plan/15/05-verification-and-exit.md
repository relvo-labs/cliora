# 05 — 驗證、證據與收尾（`FU-07`、`FU-08`）

---

## 1. 測試清單

### 1.1 Daemon（`go test -race ./...`）

見 `02-…md` §8。摘要：八個步驟的每一個否決分支、`0644`、`.git` 三種形狀、
敏感檔名、`.cliora/`、排除目錄、in-root symlink 目的地、配額跨日、
可用空間（含 `Statfs` 失敗時放行）、`O_EXCL` 的競賽測試、
**以及「被拒絕時既有檔案的 SHA256 與 mtime 都沒有變」**。

### 1.2 Central（`pytest`）

見 `03-…md` §4。其中**兩條是回歸測試**：`/images` 的既有測試全綠且未修改，
以及 `uploadImage` 在 `uploadWithProgress` 抽出後的請求形狀不變。

### 1.3 契約（`make contract`）

六個新 golden fixture × 三個 consumer，一致接受／拒絕。
`node-register.file_upload` 的有效與非布林各一。
**既有的 `filesystem.upload` 五個 invalid fixture 未被修改且全綠**
—— 這是 `00-…md` D10 的證據。

### 1.4 前端（`vitest`）

見 `04-…md` §5。

### 1.5 端到端（`scripts/e2e`）

一條路徑，刻意包含一次同名衝突與一次資料夾拒絕：

```
登入 → 開 CLI session → 檔案樹展開 datasets/
     → 拖 data.csv 到 datasets/ 那一列 → 該列出現 datasets/data.csv
     → 節點上 SHA256 相同、權限 0644
     → 在終端機 `cat datasets/data.csv` 內容正確
     → 再拖同一個檔案 → FILE_EXISTS → 按〔改名〕→ data-2.csv 成功
     → 拖一個資料夾進來 → 被拒且沒有任何請求
     → 稽核有兩筆 file.upload，source=file，path 分別是兩個相對路徑
     → 拖一張圖到終端機面板 → 圖片投放仍然正常（回歸）
```

最後一行是**回歸驗收**，不是新功能：本期最容易弄壞的既有功能就是它。

---

## 2. 已知會被改變的既有行為

要寫進 release note 的三項，**第一項要放在最前面**：

1. **`file.upload` 這個權限的意思變大了。** 它從「把一張圖片投放到平台自有目錄」
   變成「把一個檔案放到工作區裡的一個位置」。持有它的角色（Admin、Developer）不變，
   但能做的事變多了。**要停用新行為的節點怎麼做**（`filesystem.upload.files.enabled: false`）
   必須寫在同一段，不能放到附註。
2. **`FILESYSTEM_UPLOAD_BYTES` 的 label 從 `mime` 改成 `source`。**
   既有的 dashboard 會斷（`03-…md` §2.6）。
3. **`.cliora/uploads/` 的圖片仍然刪不掉。** ADR 0024 的
   `FILE_UPLOAD_QUOTA_EXCEEDED` 錯誤訊息一直在叫使用者「在檔案樹刪除不需要的圖片」，
   而本期**不做刪除**，所以那張空頭支票仍然開著。
   **要誠實寫下來並修掉那句錯誤訊息的文案**（改成「請在節點上以終端機刪除」）——
   這是本期唯一一處會動到圖片投放**文案**的地方，而不改它會讓一個明知為假的
   指示繼續存在。

---

## 3. Evidence 與 gates

`scripts/fu/`：

| Script | 產出 |
|---|---|
| `evidence.sh` | 彙整下列輸出到 `artifacts/fu/`，沿用各期既有體例 |
| `check-no-overwrite.sh` | grep 契約 schema、Go 的 payload struct 與 `store.go`、Python 的 relay：確認不存在 `overwrite`／`mode`／`precondition`／`revision`／`force` 欄位，且 `store.go` 只用 `CreateExclusive`（沒有 `O_TRUNC`、沒有 `os.WriteFile`）。形狀沿用 `scripts/wf/check-no-naming-channel.sh` |
| `store-policy-scan.sh <dir>` | 對一棵樹跑上傳政策，列出不能作為目的地的路徑與分類。同時是 runbook 工具（「為什麼我不能傳到這個目錄」的第一步） |

`traceability/gates.json` 新增兩個：

```jsonc
{"id": "GATE-FU-NO-OVERWRITE", "owner": "architecture", "layer": "static",
 "command": ["scripts/fu/check-no-overwrite.sh"],
 "working_directory": ".", "timeout_seconds": 60,
 "trigger": ["pull_request", "main", "release"],
 "required_for": ["changed", "all", "mvp", "security"]}

{"id": "GATE-FU-WRITE-POLICY", "owner": "daemon", "layer": "unit",
 "command": ["go", "test", "./internal/files/", "-run", "TestStorePolicy", "-count", "1"],
 "working_directory": "daemon", "timeout_seconds": 300,
 "trigger": ["pull_request", "main", "release"],
 "required_for": ["changed", "all", "mvp", "security"]}
```

兩個都掛在 `security` 上，理由與 `GATE-PV-ARGV-CHANNEL`、
`GATE-WF-NO-NAMING-CHANNEL` 相同：它們守的是**不能靠註解守住**的邊界。

`GATE-FU-NO-OVERWRITE` 特別重要，因為它守的不只是安全 ——
它守的是**本期的規模**。`plan/14` 的所有機制都是從「可以覆寫」長出來的，
而一個 `overwrite` 欄位溜進來的那一天，那些機制就會一個一個回來
（`01-…md` §6.2）。這一句要寫在 script 的檔頭註解裡。

---

## 4. Runbook 與 release note

`docs/runbooks/file-upload.md`（新檔，與既有的 `image-drop.md` 並列並互相連結）：

- **如何停用**：`filesystem.upload.files.enabled: false` → 重啟 agentd →
  確認 `node.register` 回報 `file_upload: false` → 確認 UI 入口消失。
  **注意這不會停用圖片投放**（兩個獨立開關），反之亦然。
- **「使用者說傳不上去」**：依錯誤碼分流 ——
  `FILE_EXISTS`（設計，請改名或用終端機）、
  `FILE_DENIED`（用 `store-policy-scan.sh` 看那個目錄為什麼不行）、
  `FILE_UPLOAD_NO_SPACE`（`doctor` 那一行）、
  `FILE_UPLOAD_TOO_LARGE`（4 MiB 上限，請用終端機）。
- **「誰上傳了什麼」**：稽核 `file.upload` 且 `source=file`，
  metadata 有相對路徑與位元組數。
- **磁碟**：`doctor` 的可用空間那一行、`min_free_bytes` 調整的後果、
  以及**本期上傳的檔案不會被平台清理**（那是使用者的資料，`01-…md` §2）——
  這一句一定要寫，否則有人會去找那個不存在的清理程序。
- **大檔案的替代路徑**：在節點上 `scp`／`curl`／`git clone`／`tar`。
  runbook 要真的把指令寫出來，因為這是我們主動把使用者推去的地方。

`docs/release-note-file-upload.md`，四段：

1. **權限語意變更**（§2 第 1 項）。放第一段。
2. **新功能**：把檔案拖進檔案樹的任一目錄；4 MiB 上限；不覆寫（同名要改名）；
   落地權限 `0644`；不支援資料夾。
3. **升級即取得**：`filesystem.upload.files.enabled` 預設 `true`（`00-…md` D7），
   停用方式。
4. **observability**：`FILESYSTEM_UPLOAD_BYTES` 的 label 變更（§2 第 2 項）。

**不需要寫「平台會寫入你的工作區」** —— ADR 0024 的 release note 已經寫過，
本期是第二條路徑而不是第一次。但要寫**這一條不會取代任何既有檔案**，
因為那是使用者最可能誤解的地方。

---

## 5. 安全審查（`FU-08`，`docs/security-review-p15.md`）

七個問題。**第 1、2 題的權重與其他五題不同**：
本期第一次讓請求端指名工作區裡的落地位置。

1. **客戶端能不能把檔案放到它不該放的位置？**
   證據：`StorableClassification` 呼叫的是**同一個** `SensitiveClassification`；
   `.git` 三種形狀的測試；`.cliora/`；排除目錄；
   目的地是 in-root symlink 時被拒（`LstatIn` 那一步）；
   `GATE-FU-WRITE-POLICY`。要明確回答 ADR 0024 §4 列的五項防護（`01-…md` §1.2 那張表）。
2. **一個被拒絕的上傳，會不會已經動到了什麼？**
   對每一個否決碼追一次：既有檔案的 SHA256 與 mtime 未變、`.part` 未殘留、
   目錄未被建立。**`FILE_EXISTS` 這一格要單獨驗**，因為它是最常走到的那一條。
3. **檔名能不能變成路徑？**
   `filename` 在 wire 上的 pattern 拒絕 `/`；三個 consumer 一致；
   daemon 的第 1 條檢查是 defence in depth；`FU-01` 第 2 項的非 ASCII 往返。
   也要回答：URL 解碼之後（Central 的 query param）才進 schema，
   所以**解碼與驗證的順序**要在報告裡寫明。
4. **上傳的內容會不會被當成別的東西執行？**
   `0644`、不判定型別、目的地不在任何 PATH 上。
   **要明寫**：沙箱已被停用的節點上（ADR 0023），
   CLI 對這個檔案有完整的檔案系統權限 —— 這是既有姿態，本期不改變它，但要寫下來
   （沿用 `docs/security-review-p13.md` 第 4 題的同一句話）。
5. **Central 有沒有留下位元組？**
   ADR 0024 §5 的四個「不」（不寫暫存檔、不寫 DB、不進 log、不進 metrics label）
   對本條路徑同樣成立，**而且要有對應的測試**。
   額外一格：`filename` 會進 log 嗎？**會進稽核，不進 correlation log** ——
   要說明為什麼這個分界是對的（稽核有存取控制，log 沒有）。
6. **`file.upload` 語意擴大的實際暴露面是什麼？**
   誰持有、他本來就能做什麼（`terminal.operate`）、新增的是什麼（介面）、
   節點側的否決怎麼運作。這一題要誠實回答一句：
   **一個組織沒有辦法只保留舊的那一半**，除了在節點側整條關掉。
7. **W1–W4 能不能承接第三條寫入路徑？**
   與 `docs/security-review-p13.md` 第 8 題同一個形狀。本期的答案要包含
   **W2 被修訂了**這件事（`01-…md` §2）：保留期只對平台自有目錄成立，
   使用者選定的位置以可見性取代。下一條路徑（下載不算寫入，所以是編輯或分塊上傳）
   要問的正確問題因此是「這個位置誰負責清」。

**沒有第八題。** `plan/14` 有一題是「回收桶本身是不是新的洩漏面」——
本期沒有回收桶，所以那個問題不存在。這一句要寫進報告，
因為「少一個攻擊面」是本期收斂範圍換到的實際好處，值得被記錄。

---

## 6. Exit 條件

全部成立才收：

1. `00-…md` §1 的九項判準各有可貼上的輸出。
2. 全部 gates 綠（含兩個新增）。
3. `scripts/trace validate --level static` 綠；`FR-FILE-010` 已註冊、
   `NFR-005.AC-109` 已再收窄、`NFR-005.AC-142` 已加 `review`、`FR-FILE-005` 已加註。
4. ADR 0026 為 `accepted`、ADR 0024 的 W2 修訂已合併、
   PRD 三處修訂與 tech §11.9 的追加已合併。
5. `docs/security-review-p15.md` 七題全部回答完畢且無 open finding。
6. runbook 與 release note 已合併；`FILE_UPLOAD_QUOTA_EXCEEDED` 的錯誤文案已修正（§2 第 3 項）。
7. 兩份 SKILL.md 已修訂（`01-…md` §7）。
8. **圖片投放的既有測試與 fixture 全綠且未被修改**（`00-…md` D10）。
9. `06-…md` 已填實作進度與差異。

### 部分出貨

**不需要分階段。** 本期只有一個動詞、一條路徑、一個節點開關，
拆開出貨不會讓任何一半更早可用。

唯一的例外是 `FU-06`（前端）可以晚於 `FU-05` 出貨 ——
端點先上線、入口後上線是安全的方向（有能力但沒有入口），
反過來不是。若要這樣做，`FU-05` 上線時 `file_upload` 的回報值仍然是
節點設定決定的，所以不會有人看到一個沒有後端的按鈕。
