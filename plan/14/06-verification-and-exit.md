# 06 — 驗證、證據與收尾（`WE-11`、`WE-12`）

---

## 1. 測試清單

### 1.1 Daemon（`go test -race ./...`）

見 `02-…md` §8 與 `03-…md` §6。最短的摘要：四個動詞 × 每一個否決分支、
往返位元組相同、權限保留、`.git` 兩種形狀、工作區根目錄四種寫法、
`.cliora/` 四動詞矩陣、目錄走訪的兩個上限與「含受保護項目時整棵不動」、
回收桶階梯、檔案與目錄的還原、配額、併發同 revision 只有一個贏。

### 1.2 Central（`pytest`）

見 `04-…md` §4。

### 1.3 契約（`make contract`）

十個 golden fixture × 三個 consumer，一致接受／拒絕。
`node-register.file_editing` 的有效與非布林各一。

### 1.4 前端（`vitest`）

見 `05-…md` §4。

### 1.5 端到端（`scripts/e2e`）

一條完整路徑，刻意包含一次衝突：

```
登入 → 開 CLI session → 開一個檔案 → 進編輯模式 → 改一行 → 存檔
     → 節點上內容改變、git diff 只有那一行
     → 在終端機用 sed 改同一個檔 → 在瀏覽器再存一次 → 得到 412
     → 選「重新載入」→ 內容是 sed 的版本
     → 建立一個新資料夾 → 在裡面建兩個檔 → 更名該資料夾 → 刪除該資料夾
     → trash 裡找得到整棵子樹 → 更名回原位 → 兩個檔的內容與權限都相同
     → 對一個含 .git 的資料夾按刪除 → 被拒且節點上未變動
     → 稽核有 file.create ×3（含 kind=directory）/ file.edit / file.rename ×2 /
       file.delete（kind=directory, entries=2）
```

**這條路徑要一次跑完**，因為本期的價值主張就是「一次性完成所有工作」，
而分開驗證每一個動詞不會證明它們串得起來。

---

## 2. 已知會被改變的既有行為

要寫進 release note 的三項：

1. **`.cliora/uploads/` 的圖片現在刪得掉了。** ADR 0024 的
   `FILE_UPLOAD_QUOTA_EXCEEDED` 錯誤訊息一直在叫使用者「在檔案樹刪除不需要的圖片」，
   而在本期之前那件事做不到。這是補上一張既有的空頭支票（`02-…md` §5.2）。
2. **存檔會換掉檔案的 inode。** hardlink 斷開、CLI 已開啟的 fd 讀到舊內容、
   inotify watcher 可能漏事件。這是 `00-…md` D5 的代價，
   `WE-01` 第 3 項要量出 watcher 的實際行為再定稿措辭。
3. **每一次預覽讀取多算一次 SHA-256。** 對 2 MiB 檔案預估 1–2 ms
   （`WE-01` 第 5 項要量），對 ADR 0015 的 3 秒預算是可忽略的，
   但它落在**所有**使用者身上而不只是編輯的人。

---

## 3. Evidence 與 gates

`scripts/we/`：

| Script | 產出 |
|---|---|
| `evidence.sh` | 彙整下列輸出到 `artifacts/we/`，沿用各期既有體例 |
| `check-no-unconditional-write.sh` | grep 三個契約 schema、Go 的 payload struct、Python 的 relay，確認 `precondition` 必填且不存在 `force`／`overwrite`／`recursive`／`if_exists`。形狀沿用 `scripts/pv/check-no-argv-channel.sh` 與 `scripts/wf/check-no-naming-channel.sh` |
| `write-policy-scan.sh <dir>` | 對一棵樹跑寫入政策，列出會被拒絕的路徑與分類。同時是 runbook 工具（「為什麼我不能編輯這個檔案」與「為什麼我不能刪這個資料夾」的第一步 —— 後者尤其需要它，因為錯誤訊息只會指出**第一個**受保護的項目） |
| `roundtrip-check.sh` | 對一個真實工作區的每一個可預覽檔案做「讀出→原樣寫回→比對 SHA256」的乾跑（**只算不寫**），輸出不相同的清單 |

`traceability/gates.json` 新增三個：

```jsonc
{"id": "GATE-WE-NO-UNCONDITIONAL-WRITE", "owner": "architecture", "layer": "contract",
 "command": ["scripts/we/check-no-unconditional-write.sh"],
 "working_directory": ".", "timeout_seconds": 120,
 "trigger": ["pull_request", "main", "release"],
 "required_for": ["changed", "all", "mvp", "security"]}

{"id": "GATE-WE-ROUNDTRIP", "owner": "daemon", "layer": "unit",
 "command": ["go", "test", "./internal/files/", "-run", "TestWriteRoundTrip", "-count", "1"],
 "working_directory": "daemon", "timeout_seconds": 300,
 "trigger": ["pull_request", "main", "release"],
 "required_for": ["changed", "all", "mvp"]}

{"id": "GATE-WE-WRITE-POLICY", "owner": "daemon", "layer": "unit",
 "command": ["go", "test", "./internal/files/", "-run", "TestWritePolicy|TestDirectoryWalk", "-count", "1"],
 "working_directory": "daemon", "timeout_seconds": 300,
 "trigger": ["pull_request", "main", "release"],
 "required_for": ["changed", "all", "mvp", "security"]}

```

第一個與第三個掛在 `security` 上，理由與 `GATE-PV-ARGV-CHANNEL`、
`GATE-WF-NO-NAMING-CHANNEL` 相同：它們守的是**不能靠註解守住**的邊界。

第二個沒有掛 `security`，但它是本期最會抓到回歸的一個 ——
「加一個 formatter 應該很方便」這種改動不會弄壞安全性，會弄壞使用者的檔案。

---

## 4. Runbook 與 release note

`docs/runbooks/file-editing.md`（新檔）：

- **「使用者說檔案不見了」**：第一步去 `.cliora/trash/<日期>/`，
  名字是 `<ULID>-<原本的 base name>`（**資料夾也在那裡，整棵子樹原樣**）；
  原始路徑查稽核的 `file.delete` 事件（含 `kind` 與 `entries`）；
  還原方式是在檔案樹上對它按〔還原到…〕，或在節點上 `mv`。
- **「使用者說刪不掉這個資料夾」**：先看錯誤碼。
  `FILE_DIRECTORY_CONTAINS_PROTECTED` 是設計（訊息會指出第一個受保護的項目，
  用 `write-policy-scan.sh` 看完整清單）；`FILE_DIRECTORY_TOO_LARGE` 也是設計；
  `FILE_REVISION_MISMATCH` 是「重新整理再試」。
- **「使用者說存檔一直失敗」**：分辨 412（節點上有人在改，正常）與
  其他錯誤碼；`scripts/we/write-policy-scan.sh` 查是不是被政策擋住。
- **如何停用**：`filesystem.editing.enabled: false` → 重啟 agentd →
  確認 `node.register` 回報 `false` → 確認 UI 入口消失。
  **注意這不會停用圖片投放**（兩個獨立開關）。
- **磁碟**：`doctor` 的 trash 那一行、配額調整的後果、
  手動清空的範圍（`trash/` 底下可以直接 `rm -rf`，**不要**刪 `.cliora/.gitignore`）。
- **hardlink 不可用的節點**：`doctor` 的警告、fallback 的行為、
  超過 `max_copy_bytes` 的檔案會拒絕刪除（這是設計，不是故障）。

`docs/release-note-file-editing.md`，五段：

1. **新功能**：在瀏覽器裡建立、編輯、更名、刪除工作區的檔案**與資料夾**。
2. **升級即取得**：`filesystem.editing.enabled` 預設 `true`（`00-…md` D10）。
   要停用的節點怎麼做。**為什麼預設是 true**：本期不新增能力，只新增介面
   （D0）—— 這一句要寫給那些會問「為什麼平台可以刪我的檔案」的人。
3. **刪除有 7 天回收桶**，位置、命名、還原方式、符號連結的例外。
   **刪除資料夾會連同其全部內容一起移入回收桶，還原時整棵回來**；
   含有 git 內部檔案或受保護檔案的資料夾會被整個拒絕，這是設計。
4. **與 CLI 並行時會看到「檔案已被修改」**，這是正常的，不是錯誤；
   兩條處置路徑。
5. **存檔會換掉檔案的 inode**（§2 第 2 項），以及它對 watcher 與 hardlink 的影響。

---

## 5. 安全審查（`WE-12`，`docs/security-review-p14.md`）

必須逐條回答的十個問題。**第 1、2、9 題的權重與其他七題不同**：
本期是平台第一次**銷毀**使用者的資料，前兩題是「會不會銷毀錯東西」。

1. **寫入面是否完全落在 `os.Root` 之內，包含 rename 的兩個端點與回收桶？**
   證據：`daemon/` 下沒有直接吃工作區路徑的 `os.WriteFile`／`os.Create`／
   `os.Remove`／`os.Rename`／`os.Link`；`root_test.go` 的逃逸測試；
   一條負向檢查 —— `.cliora/trash` 被換成指向 root 外的 symlink 時，
   刪除被拒且**原檔案仍在**。
2. **一個被拒絕的操作，會不會已經動到了什麼？**
   對每一個否決碼追一次：檔案是否未被改動、`.part` 是否未殘留、
   trash 是否未留下孤兒、目錄是否未被建立。
   特別是 `FILE_TRASH_UNAVAILABLE` —— 它的整個意義就是「什麼都沒發生」。
3. **客戶端能不能寫到它讀不到的地方？**
   證據：`WritableClassification` 呼叫的是**同一個** `SensitiveClassification`；
   `.git` 兩種形狀；`.cliora/` 四動詞矩陣；rename 兩端；工作區根目錄；
   `GATE-WE-WRITE-POLICY`。這一題要明確回答 ADR 0024 §4 留下的問題。
   **目錄那一半在第 9 題**，因為它的形狀不同：不是「這個路徑可不可以」，
   而是「這一整批可不可以」。
4. **版本前提可以被繞過嗎？**
   證據：`oneOf` 在三個 consumer 一致；`GATE-WE-NO-UNCONDITIONAL-WRITE`；
   428／412 的測試；併發同 revision 只有一個贏的 `-race` 測試。
   也要回答：revision 是否可能在不同內容上碰撞（SHA-256，不可能）、
   以及**它是否可能在相同內容上不符**（不會 —— 它只看內容，
   所以 `touch` 過的檔案仍然可以存）。
5. **8 MiB 請求訊框的第二個使用者，暴露面變大了多少？**
   誰能送、送多少次、被什麼擋住（RBAC → Central 2 MiB → daemon 2 MiB →
   每日次數）。與 ADR 0024 §7 對照。
6. **Viewer 有沒有在任何一條路徑上拿到寫入？**
   五個端點各一條 403 測試、`ROLE_ACTIONS` 的三重自動檢查、
   `can_edit_files` 對 Viewer 為 false。
   **這一題預期是「完全沒有，而且三次改版下來一句敘述都不用改」**
   （`05-…md` §3.1），它是本期少數可以乾淨回答的問題。
7. **稽核夠不夠回答「誰刪了這個檔案」？**
   四個事件、metadata 欄位、失敗時的處置與 log level。
   要實際查一次：從一個 trash 裡的檔名反推回操作者。
8. **回收桶本身是不是一個新的洩漏面？**
   它保存了使用者刪掉的內容 7 天，而那些內容可能正是他想刪掉的敏感東西。
   要回答：trash 在 `.cliora/` 之下、`.gitignore` 涵蓋、檔案權限跟著 inode
   （hardlink 不改 mode）、**但它會出現在檔案樹與檔名搜尋裡**。
   結論若是「可接受」，要說明為什麼；若不是，處置是把 trash 加進
   `workspace.excluded_directories` 的預設值。**這一題本期必須有答案，
   不能留給下一期** —— 它是本期自己造出來的。
9. **目錄操作有沒有繞過任何一條逐檔保護？**
   這是本期新增的第九題，也是目錄納入範圍之後最重要的一題。
   要逐條走：`.git`（目錄與 worktree 檔案兩種）、`.env` 與其他敏感檔案、
   `.cliora/`、排除目錄、工作區根目錄 —— 每一項各做一次
   「放進一個資料夾然後刪那個資料夾」，斷言**整個操作被拒且節點上一個位元組都沒動**。
   也要回答走訪與 rename 之間那個窗格的實際暴露面（`02-…md` §3.1 第 3 點）。
10. **W1–W4 能不能承接第三條寫入路徑？**
    與 p13 第 8 題同一個形狀，但這次有兩個實例可以對照。
    拿「檔案下載」與「一般檔案上傳」各走一次四條規矩，
    指出哪些直接成立、哪些需要新的機制。**答案要寫進審查報告**，
    因為 `NFR-005.AC-109` 剩下的正好就是那兩片。
    本期額外要記一句：**W1 已經被延伸過一次**（`01-…md` §1.2b，批次操作），
    所以下一條路徑若也是批次的，應該引用那一句而不是重新想一次。

---

## 6. Exit 條件

全部成立才收：

1. `00-…md` §1 的十四項判準各有可貼上的輸出。
2. 全部 gates 綠（含三個新增）。
3. `scripts/trace validate --level static` 綠；`FR-FILE-010`／`FR-FILE-011` 已註冊、
   `NFR-005.AC-142` 的二次 `review` 已加、`NFR-005.AC-109` 已再收窄、
   `FR-FILE-002`／`FR-FILE-005` 已加註。
4. ADR 0025 為 `accepted`、ADR 0024 已加註、ADR 0015 的第三段 amendment 已合併、
   PRD 六處修訂與 tech §11.10 已合併。
5. `docs/security-review-p14.md` 十題全部回答完畢且無 open finding。
6. runbook 與 release note 已合併。
7. 五份 SKILL.md 已修訂（`01-…md` §6）。
8. `07-…md` 已填實作進度與差異。

### 部分出貨

兩條線可以分開出貨，但有一條硬性順序（`00-…md` D21）：

| 可以先出 | 條件 |
|---|---|
| **編輯（`FR-FILE-010`）＋建立檔案與資料夾、更名（`FR-FILE-011` 的 AC-01、AC-02、AC-08）** | 回收桶不是它們的前提（覆寫仍然要進回收桶，所以 `WE-04` 的 link 那一段仍要有；但配額與清理可以後補）。**更名資料夾需要 `WE-03b` 的走訪** |
| **刪除檔案（`FR-FILE-011.AC-03` 的檔案部分）** | **必須**在 `WE-04` 完整落地之後 |
| **刪除資料夾** | 必須在 `WE-03b`（走訪）**與** `WE-04`（回收桶）**都**完整落地之後。這是本期唯一一個需要兩個前置的動作，因為它同時是後果最大的那一個 |

要提前出貨其餘部分時，`WE-06` 以設定關閉尚未就緒的端點，
而不是出一個沒有安全網的刪除。

反過來的順序（先出刪除、之後補回收桶）不被允許，理由在 D21：
中間那段時間的每一次誤刪都是不可回復的，而「之後會補」不會讓已經消失的檔案回來。
