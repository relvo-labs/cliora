# 01 — 決策與治理（`BP-01`）

## 1. ADR 0029

[`docs/adr/0029-read-only-binary-preview.md`](../../docs/adr/0029-read-only-binary-preview.md)，
狀態 `proposed`。轉為 `accepted` 需要三件事，缺一不可：

1. 產品負責人對 §7（`file.browse` 語意變寬，含 Viewer）**書面簽核**。#77 已表達意向，
   但 #77 自己要求「需在版本化 PRD、RBAC、審計與部署說明正式記錄；不應默默沿用舊規則」。
   issue 裡的一句話不是版本化紀錄。
2. 本檔 §6 的 OD-1…OD-10 全部有答案（採用建議預設也算答案，但要寫下來）。
3. `BP-08` 安全審查的判定不是 `FAIL`。

## 2. PRD 修訂（草案，`BP-01` 核准後才寫進 `research/prd.md`）

本期**不改** `research/prd.md`。PR #71 正在改同一份檔案（新增 `FR-FILE-011`、
`FR-CONN-006.AC-12`、`NFR-005` 兩處註記），現在動它只會製造衝突。
以下錨點編號假設 #71 先合併；若沒有，依 README 的條件式編號往前挪。

### 2.1 新增 `FR-FILE-012 唯讀二進位預覽`（草案文字）

> 使用者可在 Session 工作區中，以唯讀方式在 console 內檢視白名單內的圖片與 PDF。
> 本需求只有「在畫面上呈現」一個動詞：不提供存檔、分享、另開分頁、列印或複製圖片，
> 也不因預覽失敗而改為下載。與 `FR-FILE-002`（文字預覽）與 `FR-FILE-011`（下載）是三條
> 不同的路徑。

| AC（草案） | 內容 | 風險 |
|---|---|---|
| `FR-FILE-012.AC-01` | 持有 `file.browse` 且可檢視該 Session（Admin／Developer／Viewer）的使用者可預覽；Shell session 一律拒絕 | high |
| `FR-FILE-012.AC-02` | 型別由 Node 依檔案內容判定；白名單為 PNG、JPEG、WebP、GIF、PDF，其餘一律「不支援預覽」 | critical |
| `FR-FILE-012.AC-03` | `FR-FILE-005` 的敏感檔案規則適用，且與文字預覽共用同一份判定；對請求路徑與實際開啟檔案的解析名稱各判定一次 | critical |
| `FR-FILE-012.AC-04` | 上限（檔案大小、像素、邊長、PDF 頁數）超出時明確拒絕並顯示原因，不得逾時或部分顯示 | high |
| `FR-FILE-012.AC-05` | 結構異常、內容與宣稱型別不符、加密 PDF 一律拒絕，錯誤不含內容或絕對路徑 | high |
| `FR-FILE-012.AC-06` | GIF 只顯示第一幀（OD-1） | medium |
| `FR-FILE-012.AC-07` | PDF 不執行腳本、不啟用連結、表單或附件；不使用第三方服務 | critical |
| `FR-FILE-012.AC-08` | 平台不提供任何存檔入口；回應不得以可渲染型別或附件形式交付 | critical |
| `FR-FILE-012.AC-09` | 中央、edge 與瀏覽器不保存預覽內容：不落磁碟、DB、log、metrics label、HTTP 快取或瀏覽器持久儲存 | critical |
| `FR-FILE-012.AC-10` | 切換 Session、登出或換使用者時，畫面與記憶體中的預覽內容於同一刻清除 | critical |
| `FR-FILE-012.AC-11` | 不支援此功能的 Node 或中央不得啟用入口；中央不得向未回報能力的 Node 送出預覽請求 | high |
| `FR-FILE-012.AC-12` | Node 可停用並回報；中央另有 rollout 開關；兩者任一關閉即隱藏入口 | medium |
| `FR-FILE-012.AC-13` | 敏感拒絕留稽核（分類與副檔名）；成功預覽留稽核（型別、大小），兩者皆不記路徑與內容（OD-6） | high |
| `FR-FILE-012.AC-14` | 載入可取消；離開畫面即取消；並發與傳輸時間有上限 | medium |
| `FR-FILE-012.AC-15` | 手機（360／390／430 px）與桌面皆可縮放圖片、逐頁瀏覽 PDF，返回時保留資料夾、搜尋與捲動位置 | medium |

### 2.2 既有條文的修訂

| 位置 | 改動（草案） |
|---|---|
| `FR-FILE-004`（`research/prd.md:1168-1187`） | 加註：「白名單內的圖片與 PDF 另由 `FR-FILE-012` 以唯讀方式呈現；本條的 Binary 判斷與『不支援預覽』對文字預覽路徑不變。」 |
| `FR-AUTH-002.AC-11`「瀏覽檔案」（`research/prd.md:323-324`） | 加註日期與範圍：「自 `FR-FILE-012` 起，本項包含圖片與 PDF 的唯讀呈現；**Viewer 同樣持有**。不含下載。」 |
| `FR-CONN-006` | 新增 `AC-13`：預覽開啟 15 秒、每塊 10 秒、整體 60 秒（`test_every_relay_budget_is_published` 要求每個 relay 預算都在 PRD 公布） |
| `research/tech.md` §11.6 末段（`:1278`）「圖片、PDF、壓縮檔、執行檔第一階段不直接預覽。」 | 改為：「壓縮檔、執行檔不預覽。圖片與 PDF 不經本節的文字路徑，而由 §11.10 的唯讀二進位預覽處理（ADR 0029）。」 |
| `research/tech.md` 新增 §11.10 | 唯讀二進位預覽：十步順序、上限表、快照與分塊、三道閘；內容指回 ADR 0029，不複製 |
| `plan/29/06-files-and-preview-mobile.md:61`、`:65`、`README.md` 延續決策 6 | **不改**。那是 plan/29 當期的正確陳述，歷史不回寫。`BP-06` 合併時在 `plan/29/09-implementation-status.md` 加一行指向本計畫 |

## 3. `file.browse` 語意變寬，以及它的處置

這是本期唯一一個對既有授權的改動。

- **之前：** 列出、搜尋、UTF-8 文字預覽（≤2 MiB，非敏感）。
- **之後：** 以上，**加上**在 console 內看到白名單圖片與 PDF 的畫面。
- **不包含：** 取得位元組的拷貝（那是 #71／`FR-FILE-011`，有自己的節點開關）。
- **持有者不變：** Admin、Developer、**Viewer**。

處置有四項，缺一不可：

1. release note **第一段**點名 Viewer（`BP-11`）。
2. 節點開關 `filesystem.binary_preview.enabled` 與中央 flag `binary_preview_enabled`，
   是組織保留舊語意的兩個方法（ADR 0029 §9）。
3. generated permission matrix 明文寫出（本檔 §4）。
4. `backend/tests/test_authz.py` 的路由矩陣加一列「Viewer 可預覽二進位」，
   讓日後改變它成為一個決定，而不是一個沒人注意到的預設（`BP-04`）。

## 4. Permission matrix（**提議**，待核准）

`docs/permission-matrix.md` 是**產生的檔案**（`:1-4`），由
`scripts/p4/render_permission_matrix.py` 產生，並由 `backend/tests/test_authz.py:351`
以 `--check` 把關。**手改會讓測試變紅**，所以本期不改它。`BP-01` 要做的是改 generator，然後重新產生：

```diff
 # scripts/p4/render_permission_matrix.py  PRD_ROWS（:29-40）
-    ("瀏覽檔案 / Browse & preview files", rbac.FILE_BROWSE),
+    ("瀏覽檔案 / Browse & preview files (text; images & PDF, view-only)", rbac.FILE_BROWSE),

 # SCOPE_RULES（:47-71），在 "file browse / search / preview" 之後新增
+    (
+        "binary preview (image / PDF, view-only)",
+        "`file.browse` **and** view access to the owning session **and** not a shell "
+        "session **and** the node's live registration reports `binary_preview` **and** "
+        "Central's `binary_preview_enabled` is on. Grants no download.",
+    ),
```

**順帶觀察（既有，不在本期修）：** `PRD_ROWS` 沒有 `file.upload`、`terminal.shell` 與
`tunnel.*`／`integration.manage`，所以產生的矩陣沒有列出它們，雖然 `rbac.py` 裡有
（`rbac.py:31`、`:34`、`:38-40`、`:57-70`）。
這是 generator 的既有缺口，不是本期造成的，另開議題處理。

## 5. Traceability（**提議**，待核准）

`traceability/requirements.json` 支援 `lifecycle: "proposed"`
（`traceability/schema/requirements.schema.json:47`），但每條 criterion 都要有存在的
`source_anchor`，也就是 PRD 裡要先有錨點。本期不改 PRD（§2），所以**本期不登記**，
理由與 #71 衝突相同。`BP-01` 核准後一次做完：

1. PRD 加入 §2 的錨點（`fr-file-012`、`fr-file-012-ac-01…15`、`fr-conn-006-ac-13`）。
2. `requirements.json` 新增 `FR-FILE-012`，`lifecycle: "active"`（核准即 active），
   `owner` 依 AC：01／11／12／13 為 `central`，02／03／04／05 為 `daemon`，
   06／07／08／10／15 為 `frontend`，09／14 為 `central`。
   ID 與風險等級照 §2.1 的表，`verification_profile` 除 AC-15 為 `device` 外皆為 `automated`。
   **欄位值以屆時的 schema 為準。**
3. `links.json` 每條 AC 四條連結（planned_by → `plan/31/…`、specified_by → ADR 0029 §、
   implemented_by、verified_by）。implemented_by 與 verified_by **必須指向不同檔案**
   （#71 同一原則）。
4. `scripts/traceability/tests/test_traceability.py` 的 census：**+15**（`FR-FILE-012`）**+1**
   （`FR-CONN-006.AC-13`），**分開寫一行**，並附來源。
   #71 已記錄 master 上的 census 在 `NFR-007`（+7）後就是紅的，而且 #71 自己修了它。
   若 #71 沒合併，這裡要先把那 +7 補上，寫成第三行，不要併進本期的數字。
5. `make traceability` 全部五個階段綠。

## 6. 產品決策（Open decisions for the product owner）

只列真正需要產品負責人回答的題目。每題都附建議預設；**採用預設也要書面確認**。

| # | 決策 | 選項 | **建議預設** | 理由／代價 |
|---|---|---|---|---|
| OD-1 | GIF（與 APNG、動態 WebP）是否播放動畫 | (a) 只顯示首幀；(b) 播放，另設幀數與總時長上限 | **(a) 只顯示首幀** | `createImageBitmap` 本來就取首幀或預設影像，不需要逐格式程式（ADR §11）。播放需要 `<img>`（CSP 要加 `blob:`，而且長按可存檔）或 `ImageDecoder`（Safari 支援不足），並多一個 CPU／記憶體 DoS 面。UI 標示「動畫僅顯示第一幀」。 |
| OD-2 | 上限 | 圖：大小／像素／邊長；PDF：大小／頁數 | **圖 8 MiB、16 777 216 px、邊長 8192；PDF 16 MiB、200 頁** | 像素上限對齊常見報告的 iOS canvas 面積上限（**待 `BP-OM-01` 實測**）。8 MiB 涵蓋一般手機截圖與相機 JPEG；16 MiB／200 頁涵蓋一般規格書。任何一個數字在實測前都不算定案。 |
| OD-3 | PDF 文字層（選取、搜尋、螢幕報讀）是否在 v1 | (a) 不做，純 canvas；(b) 做文字層 | **(a) v1 不做** | 文字層多一層 DOM、一條複製路徑與效能成本。代價是**螢幕報讀器讀不到 PDF 文字**，只讀得到「第 n／N 頁」。release note 與畫面要寫明。建議列為 v1.1 候選。 |
| OD-4 | PDF 內連結 | (a) 全部無效，不顯示；(b) 外部連結以純文字列出供複製；(c) 內部頁面跳轉可用 | **(a) 全部無效** | 連結是 PDF 主動內容裡最直接的一種。(c) 需要註解層 DOM，是 v1.1 候選；(b) 價值低，而且會讓人以為平台背書那個網址。 |
| OD-5 | Rollout 預設 | Central flag 預設開／關；節點開關預設開／關 | **Central flag 預設關；節點開關預設開** | 升級 daemon 不會自己打開任何東西；由操作者按環境打開 Central flag，這是唯一一個動作。節點預設開延續 ADR 0023 D2／0024 D8／0026 §9 的「升級即取得」模式，但這裡有 Central flag 在前面擋住。若要更保守，就把節點也改成預設關，代價是每台節點都要改設定。 |
| OD-6 | 成功預覽是否留稽核 | (a) 留，不含路徑；(b) 不留（與文字預覽一致） | **(a) 留 `file.binary_preview`，只記 kind／mime／size_bytes** | 這是刻意擴大 Viewer 可見範圍的功能，「Viewer 有沒有在用、在哪些 session 用」要能回答，而且不能靠一份有路徑的 log。代價是稽核量隨圖片開啟次數成長。 |
| OD-7 | 桌面是否同時提供 | (a) 手機與桌面共用同一渲染器；(b) 只給手機 | **(a) 共用** | 同一個 `PreviewPane` 分支，只給手機會多一個「為什麼桌面看不到」的支援問題。代價是桌面回歸也在驗收範圍內（成功判準 10）。 |
| OD-8 | 加密 PDF | (a) 拒絕，不提示密碼；(b) 可輸入密碼 | **(a) 拒絕** | 密碼輸入框是一個新的秘密輸入面（log、記憶體、自動填入），而且大多數加密 PDF 只有權限密碼。v1 拒絕，並明說原因。 |
| OD-9 | 瀏覽器最低版本 | (a) PDF.js 現代版，舊瀏覽器顯示「不支援」；(b) 用 legacy build 涵蓋更舊的 iOS | **(a)，待 `BP-OM-07` 量完再確認** | legacy build 較大，而且要多一套 polyfill 審查。若量測顯示產品支援清單內的裝置跑不動現代版，就改 (b)。 |
| OD-10 | 格式清單 | 目前五種；是否加 HEIC／AVIF／SVG | **只有五種；HEIC／AVIF／SVG 都不加** | SVG 是可帶腳本的文件，不是點陣圖。HEIC 在 Android Chrome 無原生解碼，加了等於只在 iOS 能用。AVIF 的解碼器攻擊面較新。任何新增都要修訂 ADR。 |

**不是開放題、但需要簽核的一項：** Viewer 包含在內。#77 已明確表達，
這裡要的是 PRD `FR-AUTH-002.AC-11` 註記（§2.2）與 release note 第一段的簽核，不是再討論一次。

## 7. `BP-01` 階段定義

**寫入集：** 見 `00-…md` §5。只動文件、traceability 與 matrix generator，不動任何產品程式。

**前置：** #76 已合併且綠（#77 驗收第一項）；重新核對 master 與 #71 的狀態，
決定條件式編號走哪一邊。

**先寫的 RED：**

- `make traceability-validate`：先加入 `requirements.json` 條目、還沒加 PRD 錨點 →
  必須以 `anchor.missing` 失敗，證明條目真的被檢查。
- `render_permission_matrix.py --check`：改完 generator、還沒重新產生 → 必須失敗。
- census：新增 16 條之後、還沒改數字 → 必須失敗。

**驗收清單：**

- [ ] ADR 0029 狀態 `accepted`，日期與簽核人寫在 ADR 標頭。
- [ ] OD-1…OD-10 每題都有書面答案，並回填 ADR 0029 相關段落（若答案不是建議預設）。
- [ ] PRD `FR-FILE-012`（15 條）、`FR-FILE-004` 註記、`FR-AUTH-002.AC-11` 註記、`FR-CONN-006.AC-13`。
- [ ] `research/tech.md` §11.6 末段修訂與新 §11.10。
- [ ] generator 修改並重新產生 `docs/permission-matrix.md`；`--check` 綠。
- [ ] `requirements.json`／`links.json`／census；`make traceability` 五階段綠。
- [ ] 本計畫的條件式編號已依 #71 實際狀態定案，README 對照表更新。

**不在範圍：** 任何 schema、程式、fixture；generator 既有缺口（§4 觀察）的修補。
