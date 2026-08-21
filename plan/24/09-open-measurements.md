# 09 — 未量測項

沿用既有體例：**這裡列的是本期知道自己沒量的東西，以及為什麼不量。**
一個沒有列在這裡、也沒有被量的東西，是一個漏洞而不是一個決定。

`plan/23/09` 的八項**全部繼承**，狀態未變（真實對話輪數、continuation 插隊、
poll 間隔、未提交變更、逾時後的粗糙邊緣、16 KiB 上限、`wait` 的 120 秒、
machine code 命中分佈）。本期新增七項：

| # | 項目 | 為什麼現在不量 | 何時量 | 誰負責 |
|---:|---|---|---|---|
| 1 | **旅程只在 chromium 跑** | `v2-projects.yml` 現行的做法就是 `--project=chromium --workers=1`；三個瀏覽器的矩陣在 `ci.yml` 的既有 e2e job 上。七條旅程斷言的是資料與流程，不是 CSS——**唯一有跨瀏覽器風險的是 localStorage 草稿**，而那條有元件測試 | `beta.1` 的 Drawer，那時畫面才是主角 | frontend |
| 2 | **真實 Agent（Claude／Codex）跑過旅程** | 旅程要證明的是平台。用真的模型，一條紅掉的旅程分不出是平台壞了還是模型今天沒問問題 | 真實試用時，以 manual evidence 記錄而不是 CI | product |
| 3 | **`answer_to_turn_seconds` histogram** | 現在有真實 runner 了，但 histogram 的價值在**分佈**，而單人部署的分佈沒有意義 | `beta.1` 試用後 | central |
| 4 | **`CONVERSATION_CURSOR_AHEAD` 與 `TURN_ALREADY_QUEUED` 的 metric** | 加它們要動 `backend/app/`，違反 D68。目前它們只出現在 HTTP 回應與 audit | `beta.1`，與第 3 項一起 | central |
| 5 | **四項效能量測若超標，超多少才要緊** | 目標值（500／500／300ms）是從 `plan/23/08` §6 抄來的，而那些數字當時沒有資料支撐。本期產出的是**第一組實測值**，它們自己就是未來的門檻依據 | `beta.1` 有對照組時 | central |
| 6 | **`compose` 與 Railway 兩條部署路徑的 conversation 行為差異** | `CE-13` 會在兩條路徑各跑一次 fresh install／upgrade／downgrade，但**不會在 Railway 上跑七條旅程**——那需要一個能被 kill 的 daemon，而 Railway 的節點不是我們起的 | `beta.2` 的 hardening | ops |
| 7 | **多人同時在同一張卡上對話的實際體感** | J8 證明了併發的正確性（一成功一 409），但「兩個人一起釐清一張卡」是什麼感覺，需要兩個人 | `beta.1` | product |

## 1. 第 1 項的一個具體風險，寫下來以免它被當成已涵蓋

`MessageComposer` 的草稿存在 `localStorage`，key 是 `cliora.draft.<taskId>`。
**讀的那一半有 try／catch**，而且註解寫了理由——
「storage 被停用的瀏覽器會在重新整理後失去草稿，那比失去草稿更糟的是 composer 根本畫不出來」。

**寫的那一半沒有**：`watch(draft, …)` 裡的 `setItem`／`removeItem` 是裸的。
storage 被停用或配額用盡時它會 throw，而那個 throw 發生在 Vue 的 watcher 裡。
既有的元件測試（「the draft survives a failed send」）測的是送出失敗，
不是儲存失敗，所以這條分支沒有被涵蓋。

**不擴大它的份量**：它需要一個相當特定的瀏覽器狀態，
而它不影響七條旅程。依 D68 的表歸在第二列——
**記進 release note 的 known limitations，本期不修**，
並在 `beta.1` 把 composer 搬進 Drawer 時一起處理。

## 2. `FR-CONV` 的 traceability：一個橫跨整個 V2 系列的姿態

十條 `FR-CONV` 需求已註冊、`lifecycle: proposed`、**零條 link**。
`scripts/trace coverage --scope all --strict` 通過，
因為 `validate.py:458` 跳過非 active 的需求。

**這不是 `alpha.2` 的缺口。** 六個 V2 家族（FR-AGENT 12 條、FR-RUNENV 9 條、
FR-SPEC 7 條、FR-DELIVERY 4 條、FR-VERIFY 3 條、FR-EVIDENCE 2 條）全部相同，
而 `links.json` 的 2090 條 link 裡指向非 active 需求的是 **0 條**——
這是一個一致的、看得出來是刻意的姿態。

要改變它，要改的是**整個 V2 系列**，並且要一次回答一個問題：
V2 的需求在什麼條件下轉 active？（合併回 `dev`？GA？還是各里程碑的 tag？）
那個問題屬於 `beta.1` 或 GA convergence，不屬於一次封版。
**寫在這裡，是為了讓「它一直是零」與「我們忘了」不會被混為一談。**
