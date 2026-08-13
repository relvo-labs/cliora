# Cliora V2.3 — 機密下放、tag 派工與 git 送回

> **狀態：計畫已完成，尚未開工。**
> 前置條件是 V2.2（[`plan/18/`](../18/README.md)）與 V2.2_1（[`plan/19/`](../19/README.md)）
> 的出口條件。**兩者本機均已全綠**，但 `plan/18` 的出口條件 9（Traqora 正式 repo 實跑）、
> 四項量測與**合併提案**仍待人工（`plan/18/09` §4）。
> 本目錄不改變那條規則：**合併一律由人決定**，出口條件全綠只是取得提案資格。

本目錄是 [`research/02/`](../../research/02/README.md) 規劃的**第五個階段**的執行計畫，
ticket 統一使用 `SC-` 前綴（**S**ecrets and **C**redentials）。

規劃層（[`research/02/05-phase-v23-secrets-and-isolation.md`](../../research/02/05-phase-v23-secrets-and-isolation.md)）
回答「V2.3 要做什麼、為什麼」；本目錄回答「在**這個 repo 的現況**上怎麼做得出來、做完怎麼證明」。

## 這一期真正的形狀

> V2.2 的 run 是「在一個隔離目錄裡，用**機器本來就有的** git 認證拉程式碼，成果只能附成產物」。
> 這一期把它換成「帶著**平台下放的、範圍受限的、可撤銷的**機密執行，把分支推回去，
> 而且『這類卡片給這類機器』是 offer 查詢裡的一個條件而不是靠人逐張指定」。

三個風險等級完全不同的半邊：

```text
                 機密半                   派工半                  送回半
                 (SC-03,04,06,07)        (SC-05)                 (SC-07b)
 daemon          0.10.0：收下、進 env、    0.10.0：上報 tags       0.10.0：分支、push
                 去識別、不落檔            與 run_untagged         五條硬約束
 contract        v1.12.0：spec.secrets    v1.12.0：register 加     不新增訊息
                                          run_untagged            （push 是 daemon 內部行為）
 新增的           新的儲存面 ＋ 加密       零新儲存面              **新的對外副作用**
                 ＋ 新的憑證流             （一格布林 ＋ 兩個 WHERE）
 觸發安審         **是**（機密流、新儲存面） 否（但要驗「沒有暗示    **是**（git 寫入）
                                          tag 是授權」）
 壞了會怎樣        機密外洩                 卡片沒人領              **推錯地方，而遠端是別人的**
```

本期命中 `research/02/10` §6 的**三個**觸發條件（機密流、新儲存面、git 寫入），
所以 `docs/security-review-v23.md` 是**三節**且不可略過（`07-…md` §6）。

## 裁決紀錄

本目錄的形狀被三次裁決決定。**這張表是唯一的索引**，各處 inline 註記都指回這裡。

| 日期 | 裁決 | 對本期的意義 |
|---|---|---|
| 2026-08-08 | 主金鑰放**環境變數** `CLIORA_SECRET_MASTER_KEY`；git 認證**同時支援** fine-grained PAT 與 SSH key | `SC-03`／`SC-07b` 的形狀 |
| 2026-08-10 ② | **不擋 Agent push，憑證不必唯讀**——沙箱內的 git 自由是刻意給的 | 五條硬約束的主詞是**平台的 push 路徑**（D10）。本期新增的後果見下 |
| 2026-08-11 | `runner.git.isolate_ambient_credentials` **預設「取代」、可關成「疊加」** | D9。**開工前要複核的是值不是形狀** |
| **2026-08-12** | **不做 `project_agents`**；配對改用**卡片 tag × runner tag**；**授權邊界永久是 enrollment** | 本期最大的一次改寫。`SC-01` §0、`SC-02b`、`SC-05` |
| **2026-08-13** | **git 憑證的下放預設不開放**——可以實作，但由環境變數控制；**現階段 git 認證以 node 端手動配置為準，平台不管，交給 node owner 自行處理** | D5／D9／D10 改寫，`SC-07b` 整條 flag 化。見下 |

### 2026-08-13 裁決的四個後果

1. **V2.3 的預設 git 路徑仍然是 ambient**（＝ V2.2 的行為）。平台不管理、不稽核、
   不撤銷它——**這是範圍宣告，不是缺口**（`00-…md` §5 的風險表有它自己的一列）。
2. **下放的機制照做**（PAT 的 helper、SSH 的 `ssh-agent`、不落檔的兩條），
   由 Central 的 **`CLIORA_GIT_SECRET_DELIVERY_ENABLED` 控制，預設 `false`**。
   關閉時 `kind: git_pat`／`git_ssh_key` 的機密**不能建立**、`auth_kind` 只能是 `ambient`。
3. **`isolate_ambient_credentials` 的語意跟著改**（D9）：它**只對「這次 run 真的收到了
   平台憑證」的情況生效**。否則預設組態下每一次私有 repo 的 clone 都會失敗——
   **藏起 ambient 憑證、而沒有任何東西取代它**。
4. **2026-08-10 ② 給 Agent 的 git 自由在預設組態下完整保留。**
   原本要寫進 release note 的「行為改變一」因此消失了。

**這條裁決同時解掉了本計畫原本唯一的 A 類待確認項**（D5 的 `kind` 分流）：
分流照做，但它現在描述的是一條預設關閉的路徑，代價（Agent 不能用平台憑證 fetch／push）
只在有人主動打開它時才發生。

## 這一期最容易做錯的十三件事

每一條都是從**這個 repo 的既有程式碼**讀出來的，不是從規劃推想的。

1. 🔴 **以為 daemon 已經會上報 tag。**
   `run_handlers.go:52` 的 `runnerRegisterPayload` 把 `"labels"` 寫死成 `[]string{}`——
   **沒有任何設定值可以讓它非空**。Central 端的 `agent_runners.labels` 欄位確實存在
   （`0029` migration），contract 也帶了這個欄位，但**線上每一台 runner 報的都是空集合**。
   先做 Central 的 tag 比對而沒做 daemon 的上報，結果是**每一張宣告 tag 的卡片永遠沒人領**，
   而 Agents 頁上每一台都顯示「無 tag」——看起來像設定漏了，其實是功能沒接（`04-…md` §3）。

2. 🔴 **以為 daemon 已經有一個 no-op 的 `Redactor` 掛勾點可以換掉。**
   `research/02/05` SC-05 這樣寫，但**整個 `daemon/` 裡沒有 `Redactor`、沒有 `redact`**
   （唯一的命中是 `metrics.go` 的一句註解）。去識別在本期是**新程式碼**，不是替換。

3. 🔴 **只對 `run.log_chunk` 做去識別。**
   `run.failed` 的 `message` 會帶 git 的 stderr（`run_handlers.go:221`），
   `run.complete` 的 `summary` 是自由文字。**去識別要包住 `send` 這個閉包，不是包住
   `chunkSink`**（`04-…md` §5、D6）。

4. 🔴 **照字面實作「隔離 ambient 憑證」，而預設根本沒有東西取代它。**
   2026-08-13 裁決之後 git 憑證的下放預設關閉，所以一個無條件的
   `isolate_ambient_credentials: true` 會**藏起機器的憑證、而不提供任何替代**——
   預設組態下每一次私有 repo 的 clone 都失敗，而症狀看起來像「憑證設錯了」。
   正解是**隔離只對真的收到平台憑證的 run 生效**（D9）。

4b. 🔴 **把 git 憑證塞進 CLI 子程序的環境**（旗標開啟時）。
   規劃寫「以環境變數傳給 CLI 程序」，但那句話的對象是**卡片宣告的 env 機密**。
   `git_pat` 一旦進了子程序的環境，**平台剛買到的「可撤銷」就等於同時發給了 Agent**——
   而 Agent 可以拿它推到任何地方，五條硬約束一條都攔不到（它們寫在 daemon 裡）。
   本計畫的 D5：**按 `kind` 分流**。

5. 🔴 **`GIT_ASKPASS` 已經被佔用了。**
   `gitfetch.go:92` 把 `GIT_ASKPASS=/bin/false` 寫死——那是 V2.2 讓「缺憑證秒級失敗」
   成立的三個變數之一（出口條件 9，實測 2.7 秒）。PAT 這條路徑要的正是同一個變數。
   兩者不是二選一而是**要一起成立**：helper 指向一支自己不含機密的小程式，
   `GIT_TERMINAL_PROMPT=0` 保留，所以 helper 失敗時仍然是秒級失敗（`04b-…md` §3.1、D7）。
   ⚠️ **旗標關閉時 `fetchEnv` 一個位元組都不變**——那條路徑是 V2.2 的既有行為。

6. 🔴 **把機密塞進 `run.offer` 而不算大小。**
   `run.offer` 是 **64 KiB 的控制訊框**（`codec.py:15`），而且**不在 `LARGE_FRAME_TYPES` 裡**。
   更要緊的是：`run-spec.schema.json` 的 `context` 上限已經是 **65536 字元**——
   **這是一個既存的潛在缺陷**，一張描述很長的卡片今天就可能組出一個送不出去的 offer，
   而 Central **完全沒有出口方向的大小檢查**（`codec.py` 只有 `decode_control` 有）。
   症狀是 D2 描述的那一種：卡片被領走、offer 靜默消失、租約到期、重排、三次後 `blocked`。
   本期加機密會讓它從潛在變成常見。正解是 **Central 在送出前量，量不過就讓認領大聲失敗**
   （`00-…md` D2、`04-…md` §2.3）。

7. 🔴 **只改一個資格查詢。**
   `services/runs.py` 有**兩個**地方判資格：`_eligible()`（真正 offer 用）與
   `_eligible_runner_count()`（算 `waiting_reason` 用，`runs.py:346`）。
   只改前者，畫面會說「等待可用的 Agent」而其實是「沒有 runner 有這些 tag」——
   那正是出口條件 3e 要擋的事。本計畫要求兩者共用**同一個述詞函式**，並用
   `GATE-SC-TAG-BOTH-QUERIES` 斷言（`03-…md` §2.4）。

8. 🔴 **`dispatch()` 現在會直接 409 掉宣告了機密的卡片。**
   `runs.py:225` 的第 ② 步。本期要把它從「拒絕」換成「驗證是 allowlist 的子集」，
   同時 `UNSUPPORTED_DELIVERIES` 裡的 `"branch": "V2.3"`（`runs.py:93`）要拿掉，
   `pull_request`／`existing_pr` 留給 V2.4。漏掉任一處，本期的主路徑打不開。

9. 🔴 **repo 裡有九處程式註解白紙黑字寫著「V2.3 會加 `project_agents` 綁定」。**
   `rbac.py:79`、`agents.py:221/250/252`、`runs.py:461`、`0029` migration:37/40、
   `0022`／`0030` seed migration、`dto.ts:777`、`AgentsView.vue:140`。
   **2026-08-12 裁決把那張表取消了**，這些句子從「尚未發生」變成「不會發生」。
   一句過期的承諾比沒有說明更糟——尤其它們出現在 RBAC 與安全審查會讀的地方。
   `SC-01` 逐處改寫，`GATE-SC-NO-BINDING-PROMISE` 讓它不會長回來（`01-…md` §5）。

10. **把主金鑰缺失做成無條件拒絕啟動。**
    規劃寫「缺少／過短／等於 dev 預設值 → 拒絕啟動」，照字面做會讓**每一個沒在用 V2 的
    既有部署**在升級後起不來。既有的 `metrics_scrape_token` 驗證器已經給了正確形狀
    （`settings.py:297`：條件式，綁在 `metrics_enabled` 上）。照抄它（D4）。

11. **共用 `secret_box.py`。**
    那支模組是 ADR 0022 的 tunnel 憑證用的，AAD 是 `cliora-integration-credential-v1`、
    金鑰是 `CLIORA_SECRET_ENCRYPTION_KEY`、**沒有信封加密也沒有 `key_version`**。
    共用會讓兩者的輪替互相綁住（`01` D22 明寫），而且會把一支已通過安全審查的模組
    改成兩種用途。本期**新寫** `app/security/secret_envelope.py`，`secret_box.py` 零 diff（D3）。

12. **以為 `agentd` 已經是 0.9.0。**
    `daemon/VERSION` 現在是 **`0.8.0`**——V2.2 的 daemon 功能全部寫完了，但**版本從未 cut**
    （最後一次動那個檔是 `62d80e6`，V2.1）。所以「舊版 daemon 是 0.9.0」這個相容性敘述
    在現況上不成立。處置見 D21，而出口條件 3f 因此改寫成**不依賴版本號**的形式：
    **register payload 沒帶 `run_untagged` 時視為 `true`**。

## 與 `research/02/05` 的差異

**除了第 4、9 條之外都是修正而非裁量**——它們是讀了程式碼之後發現規劃的假設與現況不符。
第 4 條與第 9 條需要人接受代價。

| # | `research/02/05` | 本計畫 | 依據 |
|---|---|---|---|
| 1 | migration `0027` — `project_secrets` | **`0033`／`0034`** | 現況已到 `0032_runner_pressure`（V2.2 補出口條件 21 時用掉了一支） |
| 2 | 「0.9.0 的 `Redactor` 掛勾點是 no-op，本階段換成真的」 | **本期新寫**，且**包住整個 `send`** 而非只包 log | `daemon/` 內不存在 `Redactor`；`run.failed.message` 帶 git stderr（易錯 2／3） |
| 3 | SC-05「tag 的上報：`runner.tags` 與 `runner.run_untagged` 兩個設定值」 | 同意，但要標成**本期最容易漏的一條**並排在 Central 比對**之前** | `runnerRegisterPayload` 目前寫死 `labels: []`（易錯 1） |
| 4 | SC-04「runner 收到後…以環境變數傳給 CLI 程序」 | **按 `kind` 分流**：只有 `env` 進子程序；`git_pat`／`git_ssh_key` 只進 daemon 自己的 git 環境 | 否則平台發出的可撤銷憑證同時落在 Agent 手上，而五條硬約束攔不到它（D5）。**2026-08-13 之後這條只影響一條預設關閉的路徑** |
| 4b ✅ | SC-04b：兩種 git 認證是本期的交付內容 | **整條路徑由 `CLIORA_GIT_SECRET_DELIVERY_ENABLED` 控制，預設 `false`**；預設路徑是 node 端手動配置 | **2026-08-13 裁決**（上游 `research/02/05` 已同步回寫）。連帶 D9 的語意與出口條件 4b／6b–6e |
| 5 | 未提 offer 訊框大小 | **contract 加總量上限 ＋ Central 出口方向的大小檢查** | `run.offer` 是 64 KiB 控制訊框，而 `context` 單欄上限就是 65536；Central 沒有送出前的檢查（易錯 6） |
| 6 | 「主金鑰缺少／過短／等於 dev 預設值 → 拒絕啟動」 | **條件式**：`CLIORA_AGENT_RUNS_ENABLED` 為真時才拒絕 | 照抄 `settings.py:297` 的既有形狀；無條件會弄壞不用 V2 的部署（易錯 10） |
| 7 | SC-02 假設 V2.2「clone 之後移除 `origin`」 | `origin` **在**（V2.2 第二次裁決撤回了移除） | `gitfetch.go:141` 的註解與 `plan/18/09` §3 第 14 條 |
| 8 | 出口條件 7「第二次 run 用 mirror，不重新完整 clone」 | **改為淺 clone 的回歸條件** | V2.2 量完 M11 後決定不做 mirror（`plan/18/09` §3 第 11 條）。這一條在規劃裡是 V2.2 的遺留，改寫而非刪除 |
| 9 ✅ | 出口條件 3f「舊版 daemon（0.9.0）連上來仍能領無 tag 的卡片」 | **改為「register payload 未帶 `run_untagged` 時視為 `true`」** ＋ `SC-00` 補 cut `0.9.0` | `daemon/VERSION` 是 `0.8.0`，0.9.0 從未發布（易錯 12、D21） |
| 10 | SC-01 §0 只說「代償四條要逐條落地」 | 四條各自綁一個**出口條件與一條測試**，並在安審第三節逐條驗 | 一條宣言驗不了；`07-…md` §6 |
| 11 | 未提 repo 內的過期承諾 | **`SC-01` 的一張清單 ＋ 一個 gate** | 九處程式註解仍寫著 `project_agents` 會在 V2.3 到來（易錯 9） |

## 檔案

| 檔案 | 內容 |
|---|---|
| `00-execution-plan.md` | 成功定義（十二項判準）、範圍、固定基線決策 **D0–D22**、波次與 ticket、風險 |
| `01-decisions-and-governance.md` | `SC-00` 基線與量測、**ADR 0032**、ADR 0031／0029 的增補、PRD §8.14、skill、traceability、**過期承諾清單** |
| `02-secret-store-and-data-layer.md` | `SC-03`／`SC-04`：migration `0033`／`0034`、信封加密、金鑰驗證、**永不可讀回**的 API 與它的兩條斷言 |
| `03-tag-dispatch-and-eligibility.md` | `SC-05`：五條件資格判定、兩個查詢共用一個述詞、dispatch 的 409 指名缺哪幾個 tag、「湊不齊 tag」的反向查詢 |
| `04-contract-and-daemon-secrets.md` | `SC-06`／`SC-07`：contract v1.12.0、**訊框大小的兩道**、`kind` 分流、去識別、ambient 憑證隔離 |
| `04b-git-push-and-credentials.md` | `SC-07b`：五條硬約束的實作位置、`GIT_ASKPASS` helper、`ssh-agent`、分支命名空間、**socket 不是金鑰** |
| `05-rbac-api-and-repositories.md` | `SC-04` 的 API 半邊：`secret.manage`、Secrets 端點、Repository 的三個憑證欄與 SSH＋PR 的設定期檢查 |
| `06-frontend.md` | `SC-08`：Secrets 區、Repository 認證、卡片的 tag 輸入與建議、Agents 頁改寫、**enrollment 文案**、Run 詳情 |
| `07-verification-and-exit.md` | `SC-09`：測試矩陣、**十個 gate**、**24 條出口條件**、三節安全審查、旗標關閉回歸、合併關卡 |
| `08-implementation-status.md` | 實作進度與證據（隨實作更新） |
| `09-open-measurements.md` | **M-AR-6／M-SC-1／M-SC-2 開工前**、M-AR-2／M-AR-9 尾巴（V2.2 遺留）、上線後觀察項 |

## 執行慣例

```bash
tmux new-session -d -s cliora-v23 -c /home/ubuntu/workspace/cliora
tmux send-keys -t cliora-v23 'make check' C-m
tmux attach -t cliora-v23        # 需要看的時候才 attach
```

**環境事實**（`08-…md` §5，沿用 `plan/18/09` §5）：工具鏈不在預設 PATH 上；
DB 測試要**兩個**環境變數；`claude` 與 `codex` 在 `~/.local/bin`；`git` 是 runner 模式的前置條件；
🆕 **本期多兩個**：`ssh-agent`／`ssh-add`（`SC-07b` 的 SSH 路徑）與一個**可寫的 scratch 遠端**
（出口條件 6 的四種拒絕要對真的遠端跑一次）。

## 驗收素材

**Traqora**（D30）。本期是 D30 第一次真的需要它的**寫入**權限——
前四期都只讀。所以：

1. **先在 scratch 遠端走完出口條件 6 的四種拒絕**，確認五條硬約束真的擋得住。
   **在預設組態下跑**（用機器自己的 git 憑證）——那是使用者實際會用的路徑。
2. 再對 Traqora 跑一次 `delivery: branch`，**推的分支是 `cliora/` 前綴**，推完由人刪掉。
3. **把 `CLIORA_GIT_SECRET_DELIVERY_ENABLED` 打開之後 PAT 與 SSH 各再測一次**
   （出口條件 4b2），因為兩條路徑的失敗長相完全不同。
   **前兩步是預設組態、第三步是選用組態，驗收要標明是哪一種。**

## 合併回 `dev`

**一律由人工確認。** 出口條件全綠只是取得提案資格，不是核准；
自動化（含 CI 與 agent）不得發起或完成這個合併
（`research/02/10-verification-and-exit.md` §7）。
