# 01 — 決策與治理（D68–D76）

編號接在 `plan/23` 之後。`plan/23` 用到 D59–D66，`D67` 是實作時新增的
（一般留言在 run 還活著時關閉問題，`plan/23/10` §2.1）。所以本期從 **D68** 開始。

體例沿用：**每一項都寫「不同意的話會怎樣」**。三個月後沒有人會想知道選了什麼，
但每個人都會想知道當時放棄了什麼。

> **☑ 九項全部於 2026-08-21 裁決，全部採納計畫的答案。**
> 每一節的標題後面標了裁決，**「不同意的話會怎樣」全部保留**——
> 一份只留下結論的決策紀錄，會在半年後被讀成「當時沒有別的選擇」。

---

## D68 — 本期不改產品程式（A 類，擋開工）· ☑ 2026-08-21 裁決：不能改

> **計畫的答案：`backend/app/` 與 `frontend/src/` 相對 `ac3dfef` 零 diff。
> 例外必須是一張具名 ticket ＋ 一段寫在 [`10`](./10-implementation-status.md) 的紀錄。**

`alpha.2` 的程式已經被 1762 條 Central 測試、686 條前端測試、
八個 gate 與一次安全審查看過。本期要加的是**另一種**證據：整條堆疊上的旅程。
兩件事同時做會產生一個沒有人能回答的問題——

> 旅程紅了，是產品有缺陷，還是旅程寫錯，還是剛剛那個「順手的小修正」？

所以本期把變數固定成一個。`GATE-CE-NO-PRODUCT-DRIFT`
（[`08`](./08-verification-and-exit.md) §1）用 `git diff --stat` 對兩個目錄斷言為空。

**旅程照出真缺陷時怎麼辦**（這是預期會發生的，不是意外）：

| 嚴重度 | 處置 |
|---|---|
| 讓旅程無法完成（例如某個按鈕在真的堆疊上根本點不到） | 開一張 `CE-1x` ticket，在 [`10`](./10-implementation-status.md) 具名 waiver，修完重跑**全部**旅程 |
| 不影響旅程但確實是缺陷 | 記進 release note 的 known limitations，**不在本期修** |
| 只影響 stand-in 或腳本 | 直接修，不需 waiver（`cmd/fakecli`、`scripts/` 不在禁區） |

**不同意的話（允許邊做邊修）**：本期的產出從「一組證據」變成「一組證據 ＋ 一批未經
完整回歸的修改」，而 `CE-03` 的 clean-room 基線會在每一次修改後失效，
必須重跑——那是三套測試加八個 gate，以分鐘計。實務上會演變成「最後再跑一次」，
而那正是 `plan/23/10` §9.1 那個縫的產生方式：兩邊各自綠著。

---

## D69 — 七條旅程分兩層寫（B 類）· ☑ 2026-08-21 裁決：分兩層

> **計畫的答案：需要人看見的走瀏覽器（J1a、J3、J7），
> 需要精確控制時序或併發的走 API 腳本（J5、J6、J8、J9）。**

| 旅程 | 層 | 為什麼是這一層 |
|---|---|---|
| **J1a** 三輪釐清 ＋ proposal ＋ 接受 | 瀏覽器 | 出口條件 11 的字面是「**在同一個畫面**完成」。API 版本無法證明那件事 |
| **J3** 提問 → 卡片顯示等待你的回覆 | 瀏覽器 | 斷言的是「徽章來自投影欄」，那是畫面上的東西 |
| **J7** 失敗 → 顯示原因 → 再派工 | 瀏覽器 | 「顯示原因」是旅程的一半 |
| **J5** chaos | API 腳本 | 要在 answer commit 與 daemon 重啟之間插入 SIGKILL，瀏覽器測試對這個時序沒有控制權 |
| **J6** 20 則 comment | API 腳本 | 20 次寫入 ＋ 計數，瀏覽器只會讓它慢 30 倍而不會多證明什麼 |
| **J8** 兩人同時回答 | API 腳本 | 真正的併發需要兩個請求同時在飛。兩個瀏覽器分頁做不到「同時」 |
| **J9** Agent 送 decision | API 腳本 | 沒有 UI 路徑可以做這件事——**那正是要證明的** |

四條 API 腳本放在 `scripts/cv/journeys/`，用與 `measure-answer-to-turn.py` 相同的形狀
（httpx ＋ 直連資料庫做斷言），由 `scripts/cv/evidence.sh` 串起來。

**不同意的話（全部走瀏覽器）**：J8 會變成一條假的併發測試——兩個 `page.click()`
之間至少隔著一次 IPC，而 CAS 的競態窗口是毫秒級。它會**永遠綠**，
並且在 CAS 被拿掉的那一天仍然綠。

**不同意的話（全部走 API）**：出口條件 11 與 19（前端不推導等待狀態）失去證據，
兩者都是關於畫面的。

---

## D70 — fakecli 依對話狀態決定這一輪做什麼（B 類）· ☑ 2026-08-21 裁決：讀對話

> **計畫的答案：agent 腳本每一輪先 `cliora task messages --after 0 --json`，
> 依「已經問過幾個問題、有沒有被要求修改」決定行為。不用計數器檔。**

J1a 需要一個會在第一輪問 Q1、第二輪問 Q2、第三輪提規格、被要求修改後提第二版的 Agent。
最直覺的做法是一個計數器檔，但 continuation 的工作目錄是 **per-run 的**
（`FR-AGENT-011`，`plan/23/09` §4 記過這件事），所以檔案在下一輪不存在。
放到 `/tmp` 的固定路徑則會讓兩條並行的旅程互相污染。

**讀對話本身，這三個問題都不存在**，而且它多帶來一件事：
每一輪都真的呼叫了 `cliora task messages`、`ask`、`propose-spec`——
也就是 `CV-08` 那四個子命令**第一次在真的 run 裡被執行**。
`plan/23/10` §9.1 的那個 bug（run 裡的 `cliora` 找不到憑證）
就是這條路徑從來沒被走過才活下來的。

**不同意的話（計數器檔）**：需要一個跨 run 的可寫路徑，
那等於在測試裡重建一個 continuation 刻意沒有的東西；而且它證明不了 CLI 能用。

---

## D71 — 0.12.0 的 binary 從 `f91d9c4` 現地建（B 類）· ☑ 2026-08-21 裁決：worktree 現地建

> **計畫的答案：`git worktree add` 出 `f91d9c4`，在那裡 `go build ./cmd/agentd`。**

`git tag -l` 是空的——沒有 release artifact 可以下載，
`daemon/.goreleaser.yaml` 的產物也沒有被發布過。`f91d9c4:daemon/VERSION` 是 `0.12.0`，
而那個 commit 正是 `alpha.1` 的 tag target，所以**現地建出來的就是那個版本**。

worktree 而不是 `git stash` ＋ `checkout`：本期的工作樹上有未提交的旅程腳本，
而一個為了建舊 binary 而暫存又還原的工作樹，是一個會在中途失敗時留下爛攤子的東西。

**不同意的話（用 goreleaser 產物）**：得先發布 `alpha.1` 的 artifact，
而那是 `CE-13` 的事——會讓 `CE-09` 依賴波次 4，把整個排程串成一條線。

---

## D72 — 先打 `v2.0.0-alpha.1`（A 類，擋開工）· ☑ 2026-08-21 裁決：要，且不移動它

> **計畫的答案：要，target `f91d9c4`，在 `alpha.2` 之前，且兩個都是 annotated tag。**

`research/03/02` 開頭寫著「前置條件：`alpha.1` freeze checklist 完成」。
那份 checklist 十項全部未勾，而且 **repo 裡一個 tag 都沒有**。
今天的狀態是：`alpha.2` 的程式已經在 `alpha.1` 之上疊了四個 commit，
而 `alpha.1` 本身還不是一個可以指的東西。

release note 會直接踩到這件事——「升級自 `v2.0.0-alpha.1`」這句話，
在沒有那個 tag 的時候不成立。

**兩個 tag 都在本期產出，順序不可顛倒**（[`07`](./07-release-artifacts.md) §1）。
`alpha.1` 的 tag target 是 `f91d9c4` 而不是 HEAD：
`research/03/00` §1.3 已經寫過「commit 一改就改成 `alpha.2`，**不移動 `alpha.1`**」。

**不同意的話（跳過 alpha.1，直接 alpha.2）**：SemVer 上是合法的，
但 `alpha.1` 的 freeze checklist 裡有六項是**與版本無關的品質項**
（fresh install、upgrade／downgrade、flag 全關 = V1 行為、known limitations），
跳過它們等於讓 `alpha.2` 成為第一個沒有人驗證過安裝路徑的 tag。
若真的決定跳過，那六項要原封不動搬進 `CE-13`，省下的只有 `git tag` 那一行。

---

## D73 — gate 與旅程進 CI（B 類）· ☑ 2026-08-21 裁決：進

> **計畫的答案：在 `.github/workflows/v2-projects.yml` 加第三條 leg。**

事實：`grep -rn "scripts/cv" .github/workflows` 沒有任何結果。
八個 gate 從來只在某個人的機器上跑過。`research/03/00` §6 已經預留了退路
（「若 workflow 未涵蓋，保存手動驗證證據並開 issue」），但那條退路的成本
比做掉它還高——每次 release 都要重新手動一次。

`v2-projects.yml` 是正確的落點：它已經有 PostgreSQL service、
已經跑 `scripts/e2e/run-stack.sh` 帶完整瀏覽器套組，
只缺 `E2E_RUNNER=1`、旅程的 env 開關與一個 `scripts/cv/gates.sh` 步驟。

矩陣目前是 `projects: ["true","false"]` 兩條 leg。**第三條 leg 而不是加進現有兩條**：
runner 模式會多起一個真的 daemon 與真的子行程，
把它塞進 `projects=false` 那條沒有意義（旗標關著時 `/api/agents` 全 404）。

**不同意的話（維持手動）**：`CE-12` 的 evidence pack 要包含一份具名的手動執行紀錄，
而每一次 `alpha.3`／`beta.1` 的 release 都要重做一次同樣的事。

---

## D74 — ADR 四份的 accepted 與 SR-1 簽核是同一個動作（A 類，擋開工）· ☑ 2026-08-21 裁決：同一次，含追認

> **計畫的答案：證據齊備 →（同一次人工審核）ADR 0035／0036／0037／0041 改 `accepted`
> ＋ SR-1 具名簽核 → 建立 tag。三件事同一天、同一個人、同一份紀錄。**

它們是同一個判斷的三個出口：「這一期的設計與它的安全論證，我接受」。
拆開會產生一個奇怪的中間狀態——ADR 已 accepted 但安全審查未簽，
或反過來。

**必須一起追認的一件事**：ADR 0035 的 Status 那一段寫著
「未 accepted 前，`CV-03` 之後不得修改 `backend/`、`frontend/` 或 `daemon/`」。
那個順序**沒有被遵守**：實作先發生了（`e777674`），ADR 至今仍是 proposed。
本期不改寫那段歷史，處理方式是：`CE-14` 的簽核紀錄裡明寫一行
「本次 accepted 同時追認 `e777674`…`ac3dfef` 期間在 proposed 狀態下進行的實作」，
並在 [`10`](./10-implementation-status.md) 記下這是一次**流程偏差**而不是一次授權。

**不同意的話（先簽 ADR 再補證據）**：SR-1 的兩項未結發現正是出口條件 5、11、16，
先簽等於簽一份自己說「這裡沒有證據」的審查。

---

## D75 — chaos 用 SIGKILL 殺整個 process group（B 類）· ☑ 2026-08-21 裁決：SIGKILL

> **計畫的答案：`kill -9 -- -$PGID`，不是 SIGTERM，也不是 `kill $PID`。**

J5 要證明的是「daemon 死掉之後，那個 answer 仍然只產生一個 turn」。
SIGTERM 會讓 daemon 走它的優雅關閉路徑——那條路徑可能會把手上的狀態收好，
而**一次乾淨的關閉不是一次崩潰**。要測的是後者。

process group 而不是單一 PID：`run-stack.sh` 用 `setsid` 啟動每個背景服務，
正是為了讓 `kill -- -PGID` 能收掉 daemon 的子行程；
只殺 daemon 會留下一個仍在寫 stdout 的孤兒子行程，
而它下一步的行為（對著一個不存在的 parent 送事件）不是本旅程要問的問題。

**不同意的話（SIGTERM）**：測到的是「優雅關閉之後狀態一致」，
那是一個較弱、且已經被既有租約測試涵蓋的性質。

---

## D76 — 固定資料集不進版本控制（B 類）· ☑ 2026-08-21 裁決：不進

> **計畫的答案：`scripts/cv/seed-dataset.py`，固定 seed，輸出摘要進
> `artifacts/cv/local/`（已被 `.gitignore` 排除）。**

`research/03/CHECKLIST` §0 要求「建立 `alpha.1` 的固定測試資料集
（200 tasks／500 messages／…）」，因為**每一個效能門檻都建立在它上面**。
資料集本身是幾 MB 的列，進版本控制會讓每一次調整都變成一個大 diff；
而它真正需要固定的不是位元組，是**產生它的規則**。

腳本用固定 seed（`random.Random(20260819)`），輸出一份含
資料庫 URL、commit、列數與 seed 的 `dataset.json`，量測腳本引用它。
`plan/23/10` §5 的教訓在這裡有一個直接的落地：
量測開始前先數還在飛的 run，不是零就拒絕跑。

**不同意的話（把 dump 進版本控制）**：repo 多幾 MB，
而且 schema 一改（例如 `alpha.3` 的 `0041`）dump 就過期，
過期的方式是「restore 失敗」而不是「數字變了」。
