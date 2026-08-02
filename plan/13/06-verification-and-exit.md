# 06 — 驗證、證據與收尾（`WF-10`、`WF-11`）

---

## 1. 測試清單

### 1.1 Daemon（`go test -race ./...`）

| 檔案 | 測什麼 |
|---|---|
| `internal/files/policy_test.go` | `02-…md` §2.4 的七項（rune 邊界、任意位置 NUL、ANSI log、比例單位、編碼、corpus、benchmark） |
| `internal/files/upload_test.go` | 七步流程的每一個否決分支；四種格式的嗅探；宣告型別與內容不符時以內容為準；`.part` 在失敗後不殘留；`O_EXCL` 碰撞 |
| `internal/files/prune_test.go` | 7 天邊界（6d23h 留、7d1m 刪）；空日期目錄移除；`.gitignore` 不被刪 |
| `internal/workspace/root_test.go` | 三個新寫入方法的逃逸測試：`../` 路徑、指向 root 外的 symlink、`.cliora` 是 symlink |
| `internal/config/config_test.go` | `upload` 預設值；`enabled` 缺項記為 default |
| `internal/connection/files_integration_test.go` | `filesystem.upload` 端到端；非嚴格 base64 被拒；解碼後超大被拒；`filesystem.uploaded` 走 64 KiB 上限 |
| `internal/protocol/codec_test.go` | `filesystem.upload` 在 8 MiB 名單內、`filesystem.uploaded` 不在 |

### 1.2 Central（`pytest`）

| 檔案 | 測什麼 |
|---|---|
| `tests/test_files_upload.py` | 四種 `Content-Type` 通過、其餘 415；`Content-Length` 說謊時串流累積仍中止；4 MiB+1 被拒；relay 逾時 |
| `tests/test_rbac.py` | Viewer 403、Developer／Admin 200；`ROLE_ACTIONS` 三個自動化檢查 |
| `tests/test_audit.py` | 成功與兩種失敗各留一筆；metadata 不含內容、不含客戶端檔名 |
| `tests/test_scope_guards.py` | `filesystem.upload` schema 不得含命名類欄位（`04-…md` §1.4） |
| `tests/test_protocol_codec.py` | `LARGE_FRAME_TYPES` 的新成員；`filesystem.uploaded` 仍受 64 KiB |
| `tests/test_migrations.py` | 0018 up／down |

### 1.3 契約（`make contract`）

四個 invalid fixture × 三個 consumer，一致拒絕。
`node-register.image_upload` 的有效與非布林兩個 fixture。

### 1.4 前端（`vitest`）

見 `05-…md` §3。

### 1.5 端到端（`scripts/e2e`）

一條完整路徑：登入 → 開 CLI session → 貼上 PNG → 節點上檔案存在且 SHA256 相符 →
終端機輸入行含該路徑 → 稽核有一筆 → 檔案樹看得到。

---

## 2. 已知會被修好的既有違反

`FR-FILE-004` 今天在兩個方向上都不成立，本期一次修掉，要在 `07-…md` 記錄：

1. **誤判**：本 repo 878 個合法 UTF-8 文字檔中 20 個無法預覽（`08-…md` §1）。
2. **漏判**：前 8 KiB 為可列印 ASCII 的二進位檔會被當成文字送進 Monaco（`08-…md` §2）。

第 2 點是**收緊**，所以 release note 要寫：升級後會有少數今天看得到的檔案變成看不到。
這一句不能省 —— 一個「本來可以現在不行」的變更如果沒有預告，回報會以 bug 的形式進來。

---

## 3. Evidence 與 gates

`scripts/wf/`：

| Script | 產出 |
|---|---|
| `evidence.sh` | 彙整下列輸出到 `artifacts/wf/` |
| `classify-scan.sh <dir>` | `02-…md` §4 的全樹掃描；六個目錄各一份 |
| `check-no-naming-channel.sh` | grep 契約 schema 與 Go／Python 結構，確認 `filesystem.upload` 路徑上不存在 `filename`／`path`／`directory`／`extension` 欄位（沿用 `scripts/pv/check-no-argv-channel.sh` 的形狀） |
| `upload-quota-check.sh` | 在測試節點上連續投放至配額，確認拒絕且不落地 |

`traceability/gates.json` 新增兩個：

```jsonc
{"id": "GATE-WF-CLASSIFY-CORPUS", "owner": "daemon", "layer": "unit",
 "command": ["go", "test", "./internal/files/", "-run", "TestClassifyCorpus"],
 "working_directory": "daemon", "required_for": ["changed", "all", "mvp"]}
{"id": "GATE-WF-NO-NAMING-CHANNEL", "owner": "architecture", "layer": "contract",
 "command": ["scripts/wf/check-no-naming-channel.sh"],
 "working_directory": ".", "required_for": ["changed", "all", "mvp", "security"]}
```

第二個 gate 掛在 `security` 上，理由與 `GATE-PV-ARGV-CHANNEL` 相同：
它守的是一條**不能靠註解守住**的邊界。

---

## 4. Runbook 與 release note

`docs/runbooks/` 新增一節（或新檔 `image-upload.md`）：

- 如何停用：`filesystem.upload.enabled: false` → 重啟 agentd → 確認 `node.register` 回報 `false`
  → 確認 UI 入口消失。
- 如何清空一個工作區的上傳：路徑、可以直接 `rm -rf` 的範圍（`uploads/` 底下，
  **不要**刪 `.cliora/.gitignore`）、以及 daemon 會在下次清理時自行處理空目錄。
- 磁碟告警：`doctor` 那一行的意義、配額調高的後果。
- 使用者回報「某個檔案看不到」時：在節點上跑 `scripts/wf/classify-scan.sh`。

`docs/release-note-image-drop.md`，四段：

1. **新功能**：圖片投放（三個入口、四種格式、4 MiB）。
2. **升級即取得**：`filesystem.upload.enabled` 預設 `true`（D8）。要停用的節點怎麼做。
3. **平台會寫入你的工作區**：`.cliora/uploads/` 與 `.cliora/.gitignore`，7 天清除。
   這是平台第一條寫入路徑。
4. **預覽判定變更**：一批原本看不到的文字檔現在看得到（含本 repo 20 個實例）；
   少數原本看得到的檔案現在會被正確地判為二進位（§2 第 2 點）。

---

## 5. 安全審查（`WF-11`，`docs/security-review-p13.md`）

必須逐條回答的八個問題。**第 1 題的權重與其他七題不同**：唯讀撤銷之後
（`00-…md` D21），繞過 `os.Root` 的後果從「讀到不該讀的」變成「寫到不該寫的」，
它是 W2／W3／W4 的前提而不是四條裡的一條。

1. **寫入面是否完全落在 `os.Root` 之內？** 證據：`daemon/` 下沒有直接吃工作區路徑的
   `os.WriteFile`／`os.Create`／`os.MkdirAll`；`root_test.go` 的三個逃逸測試；
   以及一條負向檢查 —— `.cliora` 被換成指向 root 外的 symlink 時，寫入被拒且不建立任何檔案。
2. **呼叫端能不能影響檔名或位置？** 證據：契約四個 fixture、
   `GATE-WF-NO-NAMING-CHANNEL`、`test_scope_guards.py`。
3. **8 MiB 請求訊框放寬的實際暴露面是什麼？** 誰能送、送多少次、被什麼擋住
   （RBAC → Central 4 MiB → daemon 4 MiB → 配額）。
4. **上傳的內容會不會被當成別的東西執行？** 檔案權限 0o600、副檔名由嗅探決定、
   目錄不在任何 PATH 上；CLI 讀它是當作圖片。要明寫：**沙箱已被停用的節點上
   （ADR 0023），CLI 對這個檔案有完整的檔案系統權限** —— 這是既有姿態，
   本期不改變它，但要寫下來。
5. **Central 有沒有留下位元組？** D18 的四個「不」，以及對應的測試。
6. **稽核夠不夠回答「誰丟了什麼」？** 成功與失敗各一筆、metadata 欄位。
7. **判定放寬有沒有讓不該顯示的東西顯示？** corpus、以及「全檔掃描其實比今天更嚴」
   這個方向的證據。
8. **W1–W4 是否真的可以承接下一條寫入路徑？** 這一題不是關於本期的程式碼，
   而是關於 ADR 0024 的耐用度：拿「檔案編輯」當作假想案例走一次四條規矩，
   指出哪些會直接成立、哪些需要編輯自己的 ADR 補（至少：客戶端指名檔案的防護、
   敏感檔案政策在寫入方向的適用、`.git/` 的保護、並行寫入）。
   **答案要寫進審查報告**，因為使用者已經說了方向是可編輯 —— 六個月後翻開這份報告的人
   會是在做那件事。

---

## 6. Exit 條件

全部成立才收：

1. `00-…md` §1 的十項判準各有可貼上的輸出。
2. 全部 gates 綠（含兩個新增）。
3. `scripts/trace validate --level static` 綠；`FR-FILE-008`／`FR-FILE-009` 已註冊、
   `NFR-005.AC-142` 為 `deprecated` 且帶 `review`、`NFR-005.AC-109` 維持 `active` 且已加註。
4. ADR 0024 為 `accepted`、ADR 0015 的 amendment 已合併、PRD 四處修訂已合併。
5. `docs/security-review-p13.md` 的七題全部回答完畢且無 open finding。
6. runbook 與 release note 已合併。
7. `07-…md` 已填實作進度與差異。

### 部分出貨

`WF-03`（文字判定）可以在圖片投放之前單獨出貨，條件是：
`02-…md` 的測試與 corpus 齊備、ADR 0015 的 Limits 表與 tech §11.6 已修訂、
release note 只出第 4 段。這條路徑要保留，因為判定誤判是使用者**今天**在痛的，
而圖片投放要等 `WF-01` 的閘門（`00-…md` §5 第一列）。
