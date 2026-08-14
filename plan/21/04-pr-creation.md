# 04 — PR 建立（`DV-05`）　**安全審查第一節**

本期唯一的**對外副作用**。Central 第一次主動連到別人的伺服器，
並以一個帳號的身分在別人的 repo 上留下痕跡。

## 0. 這一張 ticket 最容易做錯的三行程式碼

1. **在 `finish()` 裡 `await adapter.create_pull_request(...)`。**
   看起來完全合理，而 `finish()` 是 `node_gateway` 接收迴圈呼叫的——
   **那條迴圈同時載著互動式終端的位元組**。一個 20 秒的 HTTP 呼叫會讓終端停 20 秒。
   `runs.py` 的 module docstring 與 `GATE-AR-NO-REQUEST-IN-LOOP` 已經為同一件事立過規矩（D17）。
2. **對逾時的 PR 建立做重試。** HTTP client 的慣例是重試，而**「建立」不是冪等的**——
   一次逾時可能是「請求送達了、回應沒回來」，重試會開出**兩個 PR**（D16）。
3. **把 `Authorization` 交給 `httpx` 的預設 log。** provider token 是一枚
   能在別人 repo 上寫東西的憑證，而它會出現在每一個請求的標頭裡。

## 1. 流程

```text
run.complete 進來
  ↓  finish()：只寫意圖，不打電話
  task_runs.delivery_state = 'pending_pr'（僅當 task.delivery ∈ {pull_request, existing_pr}
                                            且 payload.pushed_branch 非空）
  task_runs.pushed_branch  = payload.pushed_branch
  ↓
背景工作（沿用 run_reaper 的迴圈形狀）每 N 秒撿一次 pending_pr
  ↓  ① 解密 provider_token（Central 記憶體，不下放 —— ADR 0032 增補 A2）
  ↓  ② 組 PR 內文（§3）
  ↓  ③ 呼叫 adapter（§2）
  ↓
成功 → delivery_state='delivered'、delivery_ref=PR URL、run.result 不變
      ＋ 卡片上一則事件訊息 ＋ audit PR_CREATE ＋ evidence(kind=delivery, source=platform_observed)
失敗 → delivery_state='branch_only'、run.result='delivered_branch_only'
      ＋ 卡片上一則事件說明原因 ＋ **run 仍算成功**
```

### 1.1 為什麼 `finish()` 只寫意圖

除了 D17 的迴圈理由，還有一條：**PR 只能開在真的存在的分支上**。
`pushed_branch` 是 daemon 回報的**事實**（`03-…md` §3.1），
而 `finish()` 是它第一次到達 Central 的地方。把兩件事分開，
「分支推上去了」與「PR 開了」在資料上就是兩個可以分別失敗的狀態——
而它們本來就會分別失敗。

### 1.2 `existing_pr` 的差別

`existing_pr` 不建立 PR，它**在既有的 PR 上留一筆訊息**（「本次 run 追加了 N 個 commit」）。
所以它走同一條背景路徑但呼叫的是不同的動作，
而**那個動作是 provider 動作表上的第三個**（§2.2）。

## 2. Provider adapter

### 2.1 介面

```python
class ProviderAdapter(Protocol):
    host: str
    async def create_pull_request(
        self, *, repo_path: str, head: str, base: str, title: str, body: str, token: str
    ) -> PullRequestRef: ...
    async def find_pull_request(
        self, *, repo_path: str, head: str, token: str
    ) -> PullRequestRef | None: ...
    async def comment_on_pull_request(
        self, *, repo_path: str, number: int, body: str, token: str
    ) -> None: ...
```

**三個方法，而且這張表是封閉的**（`00-…md` §1 不得弄壞第 4 條）。
`GATE-DV-PROVIDER-VERBS` 掃 adapter 模組：不得出現 `merge`、`approve`、
`review`、`close`、`delete`、`release`、`tag` 這些字串（不論大小寫、不論是方法名還是 URL 片段）。

> **為什麼 `find_pull_request` 在表裡**：`existing_pr` 要找到那個 PR，
> 而「同一個 head 已經有 PR 了」也是 `create` 的四種失敗之一——
> 沒有查詢動作的話，那個失敗只能靠解析 provider 的錯誤訊息來辨認，
> 而那是一條會隨對方改版而壞掉的路徑。

### 2.2 GitHub 實作（D15）

- `POST /repos/{owner}/{repo}/pulls`、`GET /repos/{owner}/{repo}/pulls?head=…`、
  `POST /repos/{owner}/{repo}/issues/{n}/comments`。**三個端點，沒有第四個。**
- `repo_path` 從 `ProjectRepository.path` 取（那一欄已經是拆開的，不是自由 URL——
  `models.py:859` 的 docstring 解釋過為什麼，而**同一個理由在這裡再次生效**：
  從自由 URL 取 owner/repo 是另一種 `https://github.com@evil.example/`）。
- **GitLab 不實作**，但 `adapter_for(host)` 的 registry 要留著，
  找不到 → dispatch 當下 `TASK_PROVIDER_UNSUPPORTED`（`03-…md` §2.1）。

## 3. PR 的內容

**由平台產生，不由 Agent 產生。** 這是 `research/02/06` DV-02 的一句話，
而它的理由要寫進 ADR：PR 內文是**給 repo 上其他人看的**，
而那些人沒有 Cliora 的帳號——他們讀到的東西必須是平台能負責的。

### 3.1 標題

`[{card_ref}] {task.title}`，截到 **256 字元**。

### 3.2 內文（正好是 Monstrare `verification-report.md` 模板的內容）

```markdown
## 目標
{task.objective}

## 驗收標準
- [passed] 拒絕 path traversal
- [failed] 拒絕 symlink escape   ← 逐項，帶結果

## 驗證
| 檢查 | 結果 | 來源 | 由誰指定 |
|---|---|---|---|
| unit tests | exit 0 | 機器事實 | 專案設定 |
| lint | exit 1 | 機器事實 | 專案設定 |
| e2e：登入流程 | exit 0 | 機器事實 | 這張卡 |
| 手動確認 UI | passed | Agent 自述（未經平台驗證） | — |

## 殘留風險
- Windows junction 未測試

## 執行
- Run: {console_url}/projects/{pid}/runs/{run_id}
- Commit: {commit_sha}
- 本 PR 由 Cliora 代為建立（憑證擁有者：{token_owner}）
```

三條規則：

1. **`source` 與 `origin` 都要顯示在 PR 內文裡。** 一個 reviewer 讀到「lint 通過」
   卻不知道那是機器跑的還是 Agent 說的，這份報告的價值就只剩下版面；
   而知道它是機器跑的之後，**下一個問題一定是「誰定的標準」**——
   一條「由這張卡自己指定」的檢查，reviewer 讀它的方式與一條專案層級的不同（D4）。
2. **失敗項不可摺疊、不可省略**（FR-VERIFY-001 的 AC）。
   `failed` 的項目排在 `passed` 前面。
3. **最後那一行是誠實揭露**（`01-…md` §3.6 代價 1）：PR 的作者欄顯示的是
   token 的擁有者，而不是按下派工鍵的人。repo 上的其他人要有辦法追溯。

上限 **60 KiB**（`00-…md` §0.3），超過就截斷並附「完整內容在 run 詳情：{url}」。

## 4. 新的 egress 與它的三條斷言（**安全審查 §1 的核心**）

Central 今天沒有任何主動對外的 HTTP 出口（`httpx` 只被 tunnel 那條路徑用）。

| 面向 | 決定 | 斷言 |
|---|---|---|
| **host allowlist** | 只允許 `api.github.com`，可由 `CLIORA_PROVIDER_API_HOSTS` 覆寫（形狀抄 `runner.git.allowed_hosts`）。**預設值必須是安全的** | `test_provider_refuses_a_host_outside_the_allowlist`；一條 gate 掃 adapter 不得出現硬編碼的其他 host |
| **SSRF** | `api_base` **不是**每個 repository 的欄位，是部署層的設定。所以一個 repository 的資料改不了 Central 連去哪裡 | `test_repository_row_cannot_redirect_the_api_call` |
| **逾時** | 連線 5 秒、總計 20 秒 | `test_a_hanging_provider_does_not_hold_the_worker`（用 `cmd/fakeprovider` 的 hang 模式） |
| **不重試** | **一次就是一次**（D16）。逾時視為失敗，走 `branch_only` | `test_a_timeout_creates_exactly_one_request`（計數 fake 收到幾個請求） |
| **token 不進 log** | `httpx` 的 event hook 剝掉 `Authorization`；錯誤路徑上 provider 的 response body 照樣記，**但先過一次遮罩** | `test_the_token_never_appears_in_a_log_record`——**跑一次真的失敗請求**，掃 caplog 的每一筆 |
| **併發上限** | 同時最多 2 個 PR 建立在飛 | 一個 semaphore；`test_pending_prs_do_not_fan_out` |
| **佇列上限** | `pending_pr` 超過 50 筆時停止取件並在 Dashboard 上顯示 | `test_a_stuck_provider_surfaces_rather_than_accumulating`（`01-…md` §3.6 代價 3） |

> 最後一條的理由：provider 掛掉時 `pending_pr` 會累積，而**一個看不見的佇列
> 會在 provider 恢復的瞬間變成 50 個 PR**。上限 ＋ 可見，兩者缺一不可。

## 5. 四種失敗，四種處置

| 失敗 | 怎麼辨認 | 處置 | 卡片上寫什麼 |
|---|---|---|---|
| 權限不足 | 403 | `branch_only` | 「PR 未能建立：憑證沒有在該 repository 開 PR 的權限。分支已推送，可手動開 PR。」 |
| target 不存在 | 422 ＋ message 含 base | `branch_only` | 「PR 未能建立：目標分支 `{base}` 不存在。」 |
| 同一 head 已有 PR | `find_pull_request` 先查到 | **`delivered`**，`delivery_ref` 指向既有的那個 | 「已有 PR #{n} 對應這條分支，未重複建立。」 |
| provider 不可達／逾時 | 例外或逾時 | `branch_only` | 「PR 未能建立：無法連線到 provider。分支已推送。」 |

**第三種是 `delivered` 而不是失敗**，而那個判斷值得寫下來：
一條分支對應一個 PR 是 provider 的規則，不是我們的錯誤。
`existing_pr` 的第二次 run 會走到這一格，而它應該是正常路徑。

**四種都不讓 run 失敗**（出口條件 5）。`run.result` 從 `succeeded` 改寫成
`delivered_branch_only`，而 `run.status` 仍是 `succeeded`——
**兩欄的意思不同**：status 是「這次執行怎麼結束的」，result 是「結果是什麼」。

## 6. `cmd/fakeprovider`

一支和 `cmd/faketunnelprovider` 同一個形狀的假伺服器，四種模式：
`ok`、`forbidden`、`unprocessable`、`hang`。
**出口條件 5 的四種失敗要對它跑一次**，因為對真的 GitHub 跑「權限不足」
需要一枚故意做壞的憑證，而那比一支 80 行的 fake 貴得多。

⚠️ **fake 不能取代真實驗收**：出口條件 3（對 Traqora 開第一個真實 PR）
仍然要跑，理由與 V2.3 對 github.com 真的送出一次認證一樣——
**失敗的長相只有真的對方才給得出來**。

## 7. 驗收

| # | 斷言 | 怎麼驗 |
|---|---|---|
| 1 | `finish()` 裡沒有 HTTP 呼叫 | `GATE-DV-NO-HTTP-IN-LOOP`：掃 `services/runs.py` 不得 import `httpx` 或呼叫 adapter |
| 2 | provider 動作表封閉 | `GATE-DV-PROVIDER-VERBS` |
| 3 | 逾時只送一個請求 | fake 的計數 |
| 4 | token 不在任何 log 記錄裡 | caplog 全掃 |
| 5 | 四種失敗都是 `branch_only`／`delivered` 且 run 不失敗 | 四條測試，對 fake |
| 6 | `none`／`artifact` 從不呼叫 provider | fake 的計數為 0（**用計數驗，不用 PR 不存在驗**） |
| 7 | 無變更時不開空 PR | 同上 |
| 8 | 對 Traqora 開出第一個真實 PR | 人工，附截圖與 PR 連結 |
