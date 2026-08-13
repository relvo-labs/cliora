# Cliora V2.1 — 任務看板與 Agent 工具鏈

> **狀態：十二張票的本機實作已落地；`scripts/tk/evidence.sh` 11/11、雙旗標 Chromium 全綠。**
> **尚不可發布**：Traqora 正式 repo 實跑、合併與 agentd 發布仍待完成／人工決定；M1 真實查詢已補量。
> 進度、證據與九處實作偏離見 [`09-implementation-status.md`](./09-implementation-status.md)。
> **合併提案尚未提出**——條件全綠只是取得提案資格，不是核准。
> 前置條件是 V2.0（[`plan/16/`](../16/README.md)）的九條出口條件全綠——**已全綠**，
> 但 `PJ-08` 的人工合併提案尚未提出（`plan/16/07` §1）。本目錄不改變那條規則：
> 合併一律由人決定。

本目錄是 [`research/02/`](../../research/02/README.md) 規劃的**第二個階段**的執行計畫，
ticket 統一使用 `TK-` 前綴（**T**as**K**）。

規劃層（`research/02/03-phase-v21-task-board.md`）回答「V2.1 要做什麼、為什麼」；
本目錄回答「在**這個 repo 的現況**上怎麼做得出來、做完怎麼證明」。
需求與決策一律回指 `research/02/`、`research/prd.md`、`docs/adr/`，不重複抄寫。

## 這一期真正的形狀

> 讓任務成為平台上真實存在的東西：Epic → User Story → Task 在平台上建立與推進，
> 看板可以拖，卡片的閘門會真的拒絕；**並且讓 Session 裡的 Agent 拿得到情境、推得動卡片**。

它由**兩個風險等級完全不同的半邊**組成，這是本期最重要的結構事實：

```text
             平台半（TK-02..TK-05、TK-09）      節點半（TK-06..TK-08、TK-10）
  daemon     一行都不動                        agentd 0.8.0：新的寫入 verb ＋ 清理迴圈
  contract   v1.9.0 不變                       v1.10.0：一組 context.project 訊息
  新增的     八張表、三個動作、二十一條 API、   session_tokens、Agent 認證路徑、
             四個新畫面                        `.cliora/` 投影、`cliora` CLI
  觸發安審   否                                **是**（新憑證流，`research/02/10` §6）
```

**上游規劃寫的「V2.1 不動 daemon、不動 contract」在這個 repo 上不成立。**
理由是兩行程式碼，不是判斷：`.cliora/` 是 daemon **明文保留給平台**的子樹而既有的寫入
verb 對它一律拒絕（`daemon/internal/files/store_policy.go:83`），而且既有的寫入路徑
**要求目的地目錄事先存在**、協定裡沒有任何 mkdir（`daemon/internal/files/store.go` 步驟 6）。
完整推導與三個被否決的替代方案在 [`00-execution-plan.md`](./00-execution-plan.md) D1。

## 這一期最容易做錯的八件事

每一條都對應本目錄的一個決策，而且**每一條都是從這個 repo 的既有程式碼裡讀出來的**。

1. **以為可以用既有的 `filesystem.store` 寫 `.cliora/`。**
   會拿到 `FILE_DENIED` / `platform_owned`。那條規則是刻意的，而且 daemon 已經替這次擴充
   留好了形狀——`Verb` 型別的註解寫著「`.cliora/` 的規則是 per-verb 的」。要走的是**新增
   一個 verb**，不是放寬既有那個（`00-…md` D1、`05-…md` §3）。

2. **想把 `cliora` 二進位投影進工作目錄。**
   三條各自足以否決：單檔上限 4 MiB（`config.go:205`）、`.cliora/` 對使用者寫入 verb 是禁區、
   而 Go 靜態二進位遠大於 4 MiB。正解是**它就是 `agentd` 那支二進位**（子命令 ＋ 安裝時的
   symlink），這順便把 D11 想要的「穩定可執行路徑」提前拿到手（`00-…md` D2、`06-…md` §1）。

3. **讓 Session token 走 `get_current_user`。**
   那條路徑回傳的是 `User`，而 `require_action` 只認 `User`。讓 token 產生一個 `User`
   就等於讓它繼承那個人的**全部**動作，`task.approve` 也在裡面。正解是**第二條認證依賴**，
   Agent 憑證在結構上碰不到使用者路徑（`00-…md` D3、`04-…md` §2）。

4. **在時間軸上用 `actor_user_id IS NULL` 表示「這是 Agent 做的」。**
   那一格現在的意思是「系統事件」，而 `redact_actors` 對沒有 `audit.view` 的人也會把它清成
   `null`——三種完全不同的東西會長得一模一樣。要加 `actor_kind`
   （`services/activity.py` 的 docstring 已經點名這個區分，`02-…md` §2.3）。

5. **用 `count(*)+1` 配 `card_ref`。**
   兩個瀏覽器分頁同時建卡就會撞號，而 `card_ref` 進了卡片、進了分支名
   （V2.3 的 `cliora/<card_ref>-<run_seq>`）、進了 PR 標題。要用 `projects.next_card_seq`
   的 `UPDATE … RETURNING`（行鎖，`02-…md` §2.2）。

6. **先合 RBAC 詞彙，之後再接強制點。**
   與 `PJ-03`／`PJ-04` 同一個理由，`test_every_action_is_enforced_somewhere` 是**文字掃描**：
   `TASK_CREATE` 一旦寫進 `rbac.py` 而別處沒出現，測試立刻紅。所以 `TK-04` 是一個 PR
   （`00-…md` D6）。

7. **把 `.cliora/` 的清理寫成「刪掉整個目錄」。**
   `.cliora/uploads/` 是 image drop 的地盤，有自己的配額與規則（ADR 0024）。
   投影的保留期只能碰 `context/`、`process/`、`reference/` 三個子樹
   （`05-…md` §5——這是 ADR 0024 W2 那個問題在本期的答案）。

8. **為了看板拖曳裝一個 DnD 套件。**
   `frontend/package.json` 目前沒有任何拖曳相依，而這個 repo 的相依是一條一條加進去的。
   看板用原生 HTML5 DnD ＋ 一條鍵盤／選單的等效路徑（後者同時是 e2e 的主要斷言路徑，
   `07-…md` §2.3）。

## 與 `research/02/03` 的差異

本計畫在十處偏離規劃。**除了第 3 條之外都是修正而非裁量**——它們是讀了程式碼之後發現
規劃的假設與現況不符。第 3 條是規劃層要跟著改的連鎖後果，需要你確認一次。

| # | `research/02/` | 本計畫 | 依據 |
|---|---|---|---|
| 1 | 「不新增任何 protocol 訊息、不升級 `agentd`、不改 contract」 | **contract v1.10.0 ＋ `agentd` 0.8.0**：一組 `context.project`／`context.projected` | `.cliora/` 對既有寫入 verb 是禁區（`store_policy.go:83`）；沒有 mkdir，目的地目錄必須先存在（`store.go` 步驟 6）（`00-…md` D1） |
| 2 | `cliora` CLI「V2.1 用投影（`.cliora/bin/`）」 | **不投影。CLI 就是 `agentd` 那支二進位**，安裝時建 `cliora` symlink | 4 MiB 單檔上限、`platform_owned` 禁區、update 的解壓器只取單一成員 `agentd`（`update/files.go`）（`00-…md` D2、`06-…md` §1） |
| 3 | 版本節奏表：V2.2 用 contract v1.10.0 ／ `agentd` 0.8.0 | **整體順移一格**：V2.2 → v1.11.0／0.9.0，V2.3 → v1.12.0／0.10.0，V2.4 → v1.13.0／0.11.0 | 本期先用掉 v1.10.0／0.8.0。要回寫 `research/02/08` §4 與 §9（`01-…md` §4） |
| 4 | 情境包寫入用「既有 `filesystem.store`」 | **新 verb `VerbProject`**，只准寫 `.cliora/{context,process,reference}/`，會 mkdir，`FILE_EXISTS` 視為成功 | 同 #1（`05-…md` §3） |
| 5 | 未提舊 daemon 的情況 | `node.register` 加 **`context_projection` 能力旗標**；舊 node 上 Session 照開，UI 說「此 node 的 agentd 需升級到 0.8.0 才能送出情境」 | 沿用 `image_upload`／`file_upload` 的既有形狀（`node-register.schema.json`）；`research/02/08` §9 要求可行動訊息而非 500（`05-…md` §2） |
| 6 | 出口條件 9：「`git status` 只看到 `.cliora/`」 | **改寫為 `git status --porcelain` 完全為空** | image drop 已經在 `.cliora/.gitignore` 寫入 `*`（`upload.go:38`），所以整個子樹本來就被忽略。條件比規劃寫的更強（`08-…md` §5 條件 9） |
| 7 | 未提時間軸如何標示 Agent | `activity_events` 加 **`actor_kind`**（`user`／`agent`／`system`） | 出口條件 3 要求分得出來，但 `actor_user_id IS NULL` 現在的意思是「系統」，而 `redact_actors` 也會產生 null（`02-…md` §2.3） |
| 8 | 「Agent 憑證的 scope 寫死不含 `task.approve`」 | **再加一層：Session token 完全不進使用者認證路徑** | scope 檢查是一行 if；認證路徑分離讓「Agent 自我核准」在結構上不可達（`04-…md` §2） |
| 9 | `GET /api/tasks/{id}` 未指明可否用 `card_ref` | **路徑參數一律 UUID**；`card_ref` 走 `?ref=` 查詢，CLI 多一次往返 | 既有 API 的路徑參數全部是 UUID；一個欄位兩種意義是這個 repo 一貫拒絕的形狀（`03-…md` §3.2） |
| 10 | M1（200 張卡的看板 API）「開工前用假資料測」 | **升格為閘門票 `TK-00` 的一部分** | 與 `PJ-00` 同一個理由：本期還有三份「與升級前 diff」的基線，改完就再也取不到（`01-…md` §2） |

## 檔案

| 檔案 | 內容 |
|---|---|
| `00-execution-plan.md` | 成功定義（十項判準）、範圍、固定基線決策 D0–D14、波次與 ticket、風險 |
| `01-decisions-and-governance.md` | `TK-00`／`TK-01`：基線與 M1、ADR 0028、PRD §8.12、skill 修訂、traceability 註冊 |
| `02-data-layer.md` | `TK-02`：migration `0023`／`0024`／`0025`，九張表逐欄設計、配號、樂觀鎖、循環偵測 |
| `03-process-rbac-and-task-api.md` | `TK-03`／`TK-04`／`TK-05`：流程定義種子、三個動作、十四條 API、閘門語意、錯誤碼 |
| `04-session-token-and-agent-principal.md` | `TK-06`：token 發行與失效、第二條認證路徑、scope、稽核 actor、安全審查大綱 |
| `05-contract-and-daemon-projection.md` | `TK-07`：contract v1.10.0、`agentd` 0.8.0 的新 verb、`.cliora/` 版面、保留期與清理 |
| `06-cliora-cli.md` | `TK-08`：CLI 就是 agentd、四個子命令、D14 的離線行為與那兩句訊息、測試 |
| `07-frontend-board-and-requirements.md` | `TK-09`／`TK-10`：看板與拖曳契約、藍圖、任務詳情、Requirements 表單、Task ↔ Session |
| `08-verification-and-exit.md` | `TK-11`：測試矩陣、旗標關閉回歸、四個 gate、11 條出口條件、安全審查、合併關卡 |
| `09-implementation-status.md` | 實作進度與證據（隨實作更新） |
| `10-open-measurements.md` | M1（開工前）、M2／M3／M9／M14／M17（上線後）與本期新增的四項 |

## 執行慣例

沿用 `research/02/README.md` 的建議，本階段開一個背景 tmux 承載長時間工作：

```bash
tmux new-session -d -s cliora-v21 -c /home/ubuntu/workspace/cliora
tmux send-keys -t cliora-v21 'make check' C-m
tmux attach -t cliora-v21        # 需要看的時候才 attach
```

## 合併回 `dev`

**一律由人工確認。** 出口條件全綠只是取得提案資格，不是核准；
自動化（含 CI 與 agent）不得發起或完成這個合併
（`research/02/10-verification-and-exit.md` §7）。
