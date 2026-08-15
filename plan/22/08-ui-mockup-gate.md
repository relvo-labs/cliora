# 08 — UI Mockup 關卡（`RQ-11a` 必做／`RQ-11b` 本期不做）

D5 把 `research/02/07` 的 RQ-07 切成兩半。這一節先交代切法為什麼是這樣，
再分別寫兩半——**`RQ-11b` 的設計寫完整，因為延後不等於留白**。

## 0. 這個關卡目前完成了三分之一

| D31／`research/02/10` 出口條件 11 的四子項 | 現況 |
|---|---|
| ① `ui` gate 由系統自動停用（不靠 Admin 記得） | **已實作**：`services/process.py:189-191`，`depends_on_integration: "tunnel"` ＋ `_integration_states()` |
| ② Project Settings 寫出停用原因 | **沒有**。`disabled_reason` 已經從 API 送出來了（`process.py:206`），但前端沒有那段文案 |
| ③ 產出 mockup 變體的卡在整合未啟用時 dispatch 被拒 | **沒有任何程式碼** |
| ④ 一般 UI 實作卡照常執行 | **實質上已成立**（gate 停用 ⇒ Done Gate 不要求它），但**沒有任何測試證明它** |

**「做了三分之一、沒人驗」是本期不整包延後的唯一理由。**
下一期讀到 `depends_on_integration` 這一行的人會合理地以為這個關卡是完整的。

## 1. `RQ-11a` — 未啟用時的正確性（必做）

### 1.1 ③：dispatch 的第四道拒絕

已寫在 `03-…md` §1.2。這裡只補訊息的三段結構：

```text
409 TASK_MOCKUP_INTEGRATION_DISABLED

這張卡的交付物是 mockup 變體，而這個部署沒有啟用 tunnel 整合，
平台沒有辦法提供互動式預覽。

· 一般的 UI 實作卡不受影響，照常派工。
· Agent 附截圖為卡片產物也不受影響。
· 要啟用：設定 → 整合（需要 Admin）
```

**第二段的兩條「不受影響」是訊息的重點，不是註腳。**
一個只說「被拒絕」的錯誤，會讓人以為整個 UI 工作在這個部署上停擺
——而那正好是 D31「一般 UI 實作卡照常執行」那一列要避免的誤解。

### 1.2 ②：Project Settings 的停用原因

`ProjectDetailView.vue` 的 Settings 分頁，流程覆寫那一區塊，
逐個 gate 列出時對 `enabled: false` 的顯示原因：

| `disabled_reason` | 文案 | 動作 |
|---|---|---|
| `tunnel_integration_disabled` | 「介面審查：**停用** —— 未啟用 tunnel 整合」 | `[ 前往設定 ]`（Admin 才顯示） |
| `disabled_by_project` | 「介面審查：**停用** —— 本專案已關閉」 | 開關（需 `process.manage`） |

**兩個原因要用不同的文案**，`process.py:193-198` 的註解已經寫了為什麼：
「這個部署沒有 tunnel 整合」與「這個專案關掉了」把人送去兩個不同的人那裡，
而一個共用的「停用」會送錯一半。

### 1.3 ④：一條測試，不是一段程式碼

```text
給定 tunnel 整合未啟用
  且一張 card_kind='implementation' 的卡，其 links 沒有 mockupDecision
當它走完 run 並被拖到 done
則 Done Gate 通過
```

**這條測試現在應該就會過。** 寫它的價值在於：
它會在有人把 `ui` gate 從 `depends_on_integration` 改成硬性必要時**變紅**，
而那個改動在今天沒有任何東西擋。

### 1.4 `card_kind='mockup'` 在整合已啟用時的行為（本期）

**照常 dispatch，然後就是一張普通的 `delivery: artifact` 卡。**
Agent 產出 HTML／截圖並附成產物，人下載來看。
**沒有預覽、沒有變體比較介面、沒有 `links.mockupDecision`**——那些是 RQ-11b。

這一格要寫進 release note 的「已知限制」，否則啟用了整合的部署會期待預覽。

## 2. 為什麼 `RQ-11b` 本期不做（D5 的三個理由）

| # | 理由 |
|---|---|
| 1 | **它是本期唯一會新增對外面的東西。** 本期的賣點之一是「零新對外副作用」（README 的第一張表），而安全審查的節數會從一節變成兩節（`09-…md` §6） |
| 2 | **它換不到本期的目標。** 一句模糊需求走到卡片，全程不需要 mockup。出口條件 1–10 沒有一條碰它 |
| 3 | 🆕 **Monstrare 的 mockup 關卡依賴一份平台沒有的東西。** `../Monstrare/ai/skills/ui-mockup-gate.md` 開宗明義：「跑這個關卡前**一律先讀 `ai/context/design-system.md`**」，且「mockup 必須用已定案的 design token 與元件庫拼出來，不得憑空發明新色彩」。**平台沒有 `design-system.md` 的等價物**，也沒有計畫要有。少了它，平台的 mockup 關卡會退化成「看三張隨機風格的圖選一張」——那不是 Monstrare 的那個關卡，只是長得像 |

第三條是讀了 Monstrare 才發現的，**而它比前兩條更難用時間解決**：
RQ-11b 要真的等價於 Monstrare 的關卡，需要先內化 design system 這件事本身，
而那是一個獨立的階段規模。**寫進 `10-…md` §4 的追蹤項。**

## 3. `RQ-11b` 的完整設計（延後，但寫完）

要做的時候照這一節做，不要重新設計。

### 3.0 前提：先決定 design system 那一格怎麼辦

三個選項，**做 RQ-11b 之前必須先選一個**：

| 選項 | 代價 |
|---|---|
| 內化 design system（新資料表 ＋ token／元件 inventory ＋ 一套人工關卡） | 一個獨立階段的規模。**這才是與 Monstrare 等價的做法** |
| 讓 `design-system.md` 留在 repo 裡，情境包給路徑 | 便宜，但平台不知道那份文件說什麼，所以「變體必須用既有 token」這條**平台驗不了** |
| 明說平台的 mockup 關卡只管流程不管視覺一致性 | 誠實，但要寫進 ADR，並且**不要宣稱內化了 Monstrare 的 `ui-mockup-gate`**——只內化了它的人工選定那一半 |

### 3.1 六件要設計的事（D31 原文，逐條落地）

| # | D31 的要求 | 落地 |
|---|---|---|
| 1 | 只服務 `artifacts/preview/`，不是 run 根目錄、不是 `repo/` | daemon 端起一個靜態伺服器，root 用 `workspace.Root` 的同一套 `os.Root` 限制（`root.go`）。**不列目錄、不執行**。`repo/` 與 `.cliora/` 在 root 之外，一次路徑穿越也到不了 |
| 2 | 預覽程序不繼承 run 的 env | 明確傳一個最小 env（沿用 `runner/secrets.go:213` 組 `GIT_CONFIG_GLOBAL` 的同一種手法）。**一條測試：把一個假機密放進 run env，斷言預覽程序的 `/proc/<pid>/environ` 裡沒有它** |
| 3 | 生命週期綁 run | run 結束／取消／租約逾時 → `tunnel.close`。另加與 run 無關的最大 TTL（沿用 `default_ttl_seconds`，4h） |
| 4 | 預設密碼保護，密碼由平台產生 | `tunnel_integration.default_protection` 本來就是 `basic`。密碼走 `generate_secret` ＋ Argon2 存 hash（`NodeTunnel` 已經是這個形狀），**一次性顯示在卡片上** |
| 5 | 「不保護」要多一道確認並寫 audit | 一個 modal ＋ 一句「URL 隨機不等於秘密——它會進瀏覽器紀錄、進卡片、可能進日誌」 |
| 6 | 每個 Project 一個預覽併發上限 | 與既有 `concurrent_budget: 8` 一起算，**專案上限預設 2** |

### 3.2 詢問流程：Agent 問、人選、平台開

```text
Agent  cliora task ask "這份 mockup 要用哪種保護？密碼／限制 IP／不保護"
       → run 進 waiting_for_input，卡片顯示「等待你的回覆」（D24）
人     在卡片上選（三顆按鈕，不是打字——這是本期唯一一個結構化回覆）
平台   以那個策略開 tunnel
Agent  下次 messages 拉取時被告知 URL
```

**`tunnel.manage` 永不在 Agent 憑證的 scope 內**——與 `task.approve`、
`secret.manage`、`process.manage` 同一條規則。這是紅線 5 得以成立的關鍵。

⚠️ **「三顆按鈕」需要 `task_messages` 支援結構化回覆，而它目前只有 `body: Text`。**
最小的做法是**不改資料模型**：三顆按鈕各自送一則 `author_kind='user'` 的固定文字訊息
（`protection: basic`），平台側再解析那三個固定字串。
醜，但它不新增管道，也不需要 migration。要做 RQ-11b 時重新評估。

### 3.3 變體與決定

- 變體同時是**卡片產物**（截圖，永久）與 **Pinggy 預覽**（互動，暫時）。
- 人選一個，決定寫進 `tasks.links.mockupDecision`：
  `{ variant, chosen_by, chosen_at, note }`——
  欄位名沿用 Monstrare `mockup-decision.md` 與 `tools/kanban` 的 `links.mockupDecision`。
- 決定需要 `task.approve`（D28 的第三個關卡）。

### 3.4 出口條件 12（本期不驗）

```text
1. 啟用 tunnel 整合後，mockup 變體可預覽
2. 保護策略由 Agent 在卡片上詢問、人選擇、平台開啟
3. Agent 憑證嘗試 tunnel.manage → 被拒
4. run 結束 → tunnel 一併關閉
5. 預覽程序的環境變數不含 run 的機密
6. 路徑穿越到 repo/ → 404
```

**第 5、6 條是 D31 六件事裡風險最高的兩件**，而它們不在 D31 的出口條件裡
——本計畫補上。要做 RQ-11b 時把這六條加進 `09-…md`，出口條件從 24 條變成 30 條。

## 4. 本期對 RQ-11b 唯一的準備工作

**一個約定，零程式碼**：`links.mockupDecision` 這個鍵名寫進 ADR 0034 §5，
標註「本期不寫入，RQ-11b 才寫」。

理由是它有三個潛在拼法（`mockupDecision`／`mockup_decision`／`mockup`），
而 Monstrare 與 D31 都用第一個。**現在花一行字定下來，
比日後在兩個地方各發現一個拼法便宜。**
