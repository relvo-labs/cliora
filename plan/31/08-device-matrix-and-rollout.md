# 08 — 實機矩陣、推出與 rollback（`BP-10`／`BP-11`）

## `BP-10` 實機矩陣

**寫入集：** 外部證據目錄（不進 Git）；結果回填 `09-implementation-status.md`。
**前置：** `BP-09` 綠。**執行者：** 使用者或指定的 QA，在可安全的測試環境與非敏感測試檔上進行
（#76 的實機規則：不公開檔名、session 名稱與內容）。

### 1. 裝置 × 寬度

| 平台 | 瀏覽器 | 寬度（CSS px） | 方向 |
|---|---|---|---|
| iPhone（產品支援清單中最舊與最新各一） | Safari | 390、430；360 以 iPhone SE 或縮放模擬，並註明 | 直向；橫向抽一項 |
| Android（中階機一台） | Chrome | 360、390（或最接近的實機寬度）、430 | 直向；橫向抽一項 |
| 桌面 | Chrome、Safari、Firefox | 1440×900 | — |

每一格記錄：OS 版本、瀏覽器版本、實際 viewport、`devicePixelRatio`。

### 2. 每一格要做的事

| # | 操作 | 通過條件 |
|---|---|---|
| 1 | 開一張 3 MB PNG | 符合寬度；雙指與按鈕縮放；拖曳；邊緣不溢出（無水平捲軸） |
| 2 | 長按圖片 | **沒有**「儲存影像」／「加入照片」／「在新分頁開啟」選單（`BP-OM-03`） |
| 3 | 開一張動畫 GIF | 只有首幀，並有「僅顯示第一幀」標示 |
| 4 | 開一張 EXIF 方向 6 的 JPEG | 方向正確 |
| 5 | 開 40 頁 PDF | 第 1／40 頁；上一頁／下一頁／輸入頁碼；縮放；工具列不被 home indicator 遮住 |
| 6 | 開 CJK PDF | 繁中字形正確，沒有豆腐字 |
| 7 | 點 PDF 裡的外部連結 | 沒有任何反應 |
| 8 | 開 16 MiB PDF 後立即返回 | 載入取消；返回後資料夾、搜尋 query、捲動位置都還在；焦點回到那一列 |
| 9 | 預覽中切換到另一個 session | 舊內容立刻消失，新 session 的檔案清單出現 |
| 10 | 預覽中在另一個分頁登出 | 回到這個分頁時預覽已消失、頁面被覆蓋（#76 行為） |
| 11 | 預覽中把 app 切到背景 30 秒再回來 | 不崩潰；若 tab 被回收，重新載入後不殘留舊內容 |
| 12 | 炸彈檔、需要密碼的 PDF、只有權限密碼的 PDF、損毀檔 | 需要密碼者顯示 `pdf_password_required` 且沒有密碼框；只有權限密碼者依 OD-8 顯示；其餘各自的拒絕文案；**沒有下載入口** |
| 13 | VoiceOver（iOS）／TalkBack（Android） | 圖片念出檔名與尺寸；PDF 念出「第 n／N 頁」；工具列按鈕都有名稱；載入進度有宣告 |
| 14 | 旋轉 | 重新符合寬度，頁碼不變 |
| 15 | 大量操作（連續開 20 張圖） | 沒有分頁崩潰；記錄 Safari 的記憶體警告（`BP-OM-01`） |

### 3. 桌面回歸

1440×900：檔案樹、搜尋、文字預覽（Monaco 的搜尋、換行、行號、複製、重新整理、跳行）、上傳，
全部與基準行為相同；新增的圖片與 PDF 預覽在桌面同樣可用（OD-7）。

### 4. 驗收清單

- [ ] §1 每一格 × §2 每一項都有結果；失敗項目有議題編號。
- [ ] `BP-OM-01`／`02`／`03`／`07` 有實測值，並據以確認或修改 OD-2、OD-9。
- [ ] 桌面回歸無退步。

### 5. 不在範圍

平板專屬版面；native app；離線。

---

## `BP-11` 推出與 rollback

**寫入集：** `docs/release-note-binary-preview.md`、`docs/runbooks/binary-preview.md`、
各環境的 Central 設定。**前置：** `BP-10` 完成、`BP-08` 非 `FAIL`，而且**發布閘門** `BP-OM-06`（暫存檔）與
`BP-OM-10`（canary log 搜尋）在**每一種**要出貨的部署拓樸上都已結案（`04-…md` `BP-05`）。
某個拓樸結案不了，**該拓樸的 flag 就保持關閉**（OD-11 建議預設）。要在未證實的 edge 上開啟，必須先有產品負責人對
`FR-FILE-012.AC-09` 的明確修訂，不是發布當下的判斷。

### 1. 推出順序（ADR 0029 §9，順序本身就是控制）

```text
1. 合併契約 1.11.0、Central（含 migration 0022）、前端、edge 設定。
   binary_preview_enabled = false（OD-5）。UI 因 can_preview_binary=false 而隱藏。
2. 升級 daemons。啟用的節點開始回報 binary_preview:true（節點預設，OD-5），
   但 Central flag 仍關，所以沒有任何請求到達節點。
   ※ 絕不可以在步驟 1 之前升級「啟用中」的 daemon：舊 Central 的 node-register schema 是
     additionalProperties:false，會拒收這個 key，而且是靜默的（ws/nodes.py:199-202）。
     節點看起來在線，註冊內容卻不更新（BP-02 RED 測試 4）。
     在步驟 1 之前就要先升級 daemon 的話，先把該節點設為 enabled:false（欄位會被省略）。
   確認方式：記下重啟前的時間 T0，重啟後每台節點的 last_registration_at > T0
   （新欄位，migration 0022，只在 persist_registration 設定）。不用 daemon_version：
   版本不變的重啟也會讓它看起來「已更新」。
3. staging 打開 flag，跑 07-…md §2 的矩陣。
4. production 打開 flag。可先只對部分環境打開；Central flag 是全域的，
   不提供以使用者或角色為單位的開關（那會變成第二套 RBAC）。
```

### 2. Kill switch 與 rollback

| 層級 | 動作 | 效果 | 生效時間 |
|---|---|---|---|
| Central flag | `binary_preview_enabled=false` 並重啟 | 所有入口隱藏；端點 409；進行中的串流在下一塊時中止 | 重啟後即時 |
| 單一節點 | `filesystem.binary_preview.enabled: false`，重啟 agentd | 該節點重新註冊時**省略**欄位（等於 false）；Central 立即 409（看當下連線） | 重連後即時 |
| 前端 | 回退前端版本 | 入口消失；既有 `FILE_BINARY` 面板 | 部署後 |
| Central（回退版本） | **依序**：① Central flag off；② 每台節點設 `enabled:false` 並重啟 agentd（欄位被省略，舊 schema 接受），**或**回退 daemon；③ 在**新** Central 上確認每台的 `last_registration_at` 晚於重啟前的時間（證明停用後的註冊被接受）；④ 回退 Central；⑤ 在**舊** Central 上（沒有那個欄位）以名稱標記確認：把該節點的 `node.name` 暫時改成一次性標記再重啟，node list 出現該標記即證明被接受，舊 Central 只在接受註冊時寫入 `name`（`nodes.py:247`）；確認後改回原名 | 端點消失；節點照常註冊 | 部署後 |
| Central（**錯誤示範**） | 在啟用中的新 daemon 仍連線時直接回退 Central | 這些節點的註冊被舊 Central **靜默略過**：看起來在線，但版本、runtime、workspace root 不更新。runbook 必須寫出這個症狀與修復方法（對那些節點做第 ② 步） | — |
| Migration | `0022` downgrade | 刪除 `0022` 加的**全部**：`ix_nodes_binary_preview` 索引、`nodes.binary_preview`、`nodes.last_registration_at`（都是 report-only，沒有使用者資料）。之後再 upgrade 必須乾淨、沒有 drift（`04-…md` `BP-04` §8 的 `test_migration_0022_roundtrip`）。注意：降級會移除回退演練第 ③ 步用的 `last_registration_at`，所以**先完成第 ③ 步，再降級** | — |

**PDF.js 安全公告時：** flag off → 升版 → 重跑 `BP-07` §4 與 `BP-09` → flag on。runbook 要寫負責人。

**rollback 演練（本票驗收的一部分）：** 在 staging 依序執行：
(1) flag off，截取「UI 隱藏」與「端點 409、零 frame」的證據；
(2) 單一節點停用，截取「註冊不含 `binary_preview`、端點 409」的證據；
(3) 完整的 Central 版本回退（上表 ①→⑤），**全程 `daemon_version` 不變**。截取「新 Central 上 `last_registration_at` 前進」與「舊 Central 上名稱標記出現」兩份證據；
(4) 反例：一台**啟用中**的新 daemon 帶著名稱標記連到回退後的 Central，node list **不出現**該標記（註冊被靜默略過），症狀與 runbook 描述一致，再用第 ② 步修復。

### 3. Release note（第一段固定）

> **`file.browse` 現在也允許在 console 內檢視圖片與 PDF，Viewer 也包含在內。**
> 這不是下載：平台不提供任何存檔入口，節點開關也與下載分開。若你的組織把 Viewer 當作
> 「只能看文字」，請關閉 Central 的 `binary_preview_enabled`，或在個別節點把
> `filesystem.binary_preview.enabled` 設為 `false`。

第二段：兩個開關與推出順序。第三段：已知限制，包括 PDF 內文無法被螢幕報讀器讀取（OD-3）、
GIF 只顯示首幀（OD-1）、需要密碼的 PDF 不支援（OD-8；只有權限密碼的照常顯示）、格式清單（OD-10）與上限（OD-2）。
「不落地」與「log 無路徑」只能依 `BP-OM-06`／`BP-OM-10` 的實測結果寫，而且要寫明適用哪些部署拓樸；
某個拓樸未證實，該拓樸就不開 flag，release note 也就不涉及它（OD-11）。**不得**寫成無條件的保證。
第四段：Central 版本回退要先停用或回退 daemon（§2），以及做錯時的症狀。

### 4. Runbook

如何開關（兩層）；如何確認某節點目前的姿態（節點頁面，以及 `nodes.binary_preview` 查詢）；
稽核查詢（`file.binary_preview`，依 user／session）；如何判斷「預覽失敗」是節點、Central、
edge 還是瀏覽器；PDF.js CVE watch 的負責人與處置。

### 5. 驗收清單

- [ ] 推出順序在 staging 實際走過一次，證據附上。
- [ ] rollback 演練的兩列證據附上。
- [ ] release note 第一段如 §3；runbook 如 §4。
- [ ] ADR 0029 標頭的狀態、日期與 `Ships in` 更新。

### 6. 不在範圍

以使用者或角色為單位的 flag；自動化的漸進推出。
