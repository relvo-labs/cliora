# 06 — `SC-08`：前端

## 0. 前提：V2.2_1 定下的東西一律沿用

`plan/19` 交付了 token 系統（58 個 custom property）、五顆語意徽章、
五個版面原語（`PageHead`／`UiCard`／`DataTable`／`EmptyState`／`ToastHost`）
與**守門**（`scripts/frontend/check-tokens.mjs` 掛在 `make check` 上）。

本期的三條硬規則：

1. **不新增任何 `var(--…)` 而不定義它。** 守門會擋，但更重要的是
   本期需要的顏色**應該已經都在**——機密頁沒有新的語意色，
   它用的是既有的 `danger`／`warning`／`muted`。
   真的需要新 token 時**進 `tokens.css` 並同步 `research/style.md`**，
   不是就地寫一個 hex（`plan/19/07` §3.3 的 WARN 級別）。
2. **不新增全域 class layer。** 新東西是元件（D34）。
3. **不擴大 naive-ui 使用面**（D35）。

## 1. Project Settings → Secrets（新區塊）

`ProjectDetailView` 的 `Settings` 分頁，`ProjectRepositories.vue` 旁邊，
新元件 `ProjectSecrets.vue`。

### 1.1 版面

```text
┌ 機密 ─────────────────────────────────────────────────────┐
│ ⚠ 主金鑰遺失時，這裡的所有機密都不可復原，只能全部重建。      │
│                                                            │
│ 名稱             類型      建立者   最後使用        操作     │
│ GITHUB_TOKEN     git_pat   neil    3 小時前     [輪替][刪除] │
│ NPM_TOKEN        env       neil    從未使用     [輪替][刪除] │
│                                                            │
│ [＋ 新增機密]                                               │
│                                                            │
│ 可用名稱 allowlist（卡片只能從這裡挑）                       │
│ GITHUB_TOKEN ✕   NPM_TOKEN ✕   SENTRY_DSN ✕   [＋]         │
└────────────────────────────────────────────────────────────┘
```

### 1.2 六條規則

1. **沒有「顯示值」按鈕，也沒有「複製」。**
   不是因為做不到，是因為**沒有任何 API 回傳值**——UI 上有那顆按鈕會讓人以為
   平台留了一份可讀的副本。
2. **「輪替」就是覆寫值**，跳同一個對話框，只有值一個欄位。
   名稱與 kind 唯讀（`02-…md` §4.2）。
3. **⚠ 那一行直接寫在頁面上**，不是躺在 runbook 裡（`01` D22 的營運硬事實）。
   用 `warning` 而不是 `danger`：它是一個要知道的事實，不是一個錯誤。
4. **「最後使用」是這一頁最有用的一欄。** 「從未使用」是低調樣式而不是警示——
   一枚剛建好的機密本來就沒用過。
5. **刪除的確認對話框要說出它不做什麼**：
   > 刪除只讓平台不再下放這枚機密。**請另外到來源系統（GitHub／npm…）撤銷它。**
   沒有這一句，使用者會以為刪掉就安全了（`02-…md` §4.4）。
6. **allowlist 與機密清單是兩個東西，畫面上要看得出來。**
   一個名稱可以在 allowlist 裡而還沒建立（卡片可以宣告它，dispatch 時會說
   「這枚機密還沒建立」）。用兩個區塊而不是一個表格的兩欄。

### 1.3 新增對話框

```text
名稱   [ GITHUB_TOKEN            ]   大寫字母、數字與底線
類型   (•) env         一般環境變數，會進 Agent 的執行環境
       ( ) git_pat     ⊘ 此部署未啟用平台管理的 git 憑證
       ( ) git_ssh_key ⊘ 此部署未啟用平台管理的 git 憑證
       ( ) provider_token  開 PR 用（V2.4 起生效）
值     [ ●●●●●●●●●●●●●●●●●●●● ]   送出後即不可見
```

**兩個 git kind 預設停用**（`CLIORA_GIT_SECRET_DELIVERY_ENABLED`），
與 Repository 那一格同一個處置：停用 ＋ 一行原因，不隱藏。

四個提示，**依 kind 顯示不同的一段**（後三段只在旗標開啟時看得到）：

- `git_pat` → 最小權限：`Contents: Read and write`、
  `Pull requests: Read and write`（若同一枚要開 PR）、
  **指定 repository 而非 all**、**設定到期日**（fine-grained PAT 強制要求，
  這正是選它而不選 classic PAT 的理由）。
- `git_ssh_key` → 「貼上私鑰全文（含 `-----BEGIN`…）。
  **建議用 ed25519**：RSA-4096 約 3.2 KB，會佔掉派工訊框相當大一部分的預算。」
  （M-SC-1 的實際數字進這句話。）
- `env` → 「這個值會出現在 Agent 的執行環境裡。**git 憑證請不要用這個類型**——
  那會讓 Agent 拿到平台的憑證。」（D5 在 UI 上的一句話。）
- `provider_token` → 「本階段不會下放它；它的用途是開 PR（V2.4）。」

## 2. Project Settings → Repositories（擴充）

`ProjectRepositories.vue` 加三個欄位：

```text
認證方式  (•) 使用這台機器既有的 git 認證（ambient）
          ( ) Personal access token   ⊘ 此部署未啟用平台管理的 git 憑證
          ( ) SSH key                 ⊘ 此部署未啟用平台管理的 git 憑證
              └ 由 CLIORA_GIT_SECRET_DELIVERY_ENABLED 控制。
                現階段 git 認證由這台機器的擁有者自行配置。
```

旗標開啟後：

```text
認證方式  ( ) 使用這台機器既有的 git 認證（ambient）
          (•) Personal access token   → [選擇機密：GITHUB_TOKEN ▾]
          ( ) SSH key                 → [選擇機密：DEPLOY_KEY   ▾]

          ⓘ 選 SSH 時：SSH 只有 git 傳輸、沒有 API，所以這個 repository
            無法開 PR。若之後要用 delivery: pull_request，需另外指定一枚
            provider_token。                        [指定 provider_token ▾]
```

**⊘ 是停用不是隱藏**，而這一格是刻意的：隱藏會讓
「這個平台到底能不能管 git 憑證」變成一個要問人的問題，
而停用 ＋ 一行原因同時回答了「能」與「這裡沒開」。
（同一個判斷在 `06-…md` §3.3 用過一次：`pull_request` 也是顯示但標成 V2.4。）

四點：

- **`ambient` 是預設也是既有列的值**（`02-…md` §1.4）。它旁邊要有一句
  「**這台機器的 git 認證由它的擁有者配置，平台不管理也不能撤銷它。**
  改成平台管理的憑證之後，機器原本的認證在 run 的 git 環境裡看不見（可由 node 設定改回）」——
  前半是 2026-08-13 裁決的範圍宣告，後半是 D9 的 A／B。**兩句都要有**：
  前半是使用者最該知道的事實，後半是他們選了另一個選項之後才會遇到的。
- **機密下拉只列該 project 的、kind 相符的、未刪除的**。
  沒有相符的機密時，下拉是一個連到上面 Secrets 區的連結，
  不是一個空的 select（`EmptyState` 的同一條精神）。
- **提示不擋儲存**（`05-…md` §3.2 第 4 條）。
- **改動認證方式要有確認**：它會改變下一次 run 用什麼憑證，而那不是一個
  「按錯了再按回來」的設定——中間可能已經跑過一次 run。

## 3. 卡片的執行設定（`TaskDetail.vue`）

V2.2_1 已經把「執行設定」那一區做出來了（`UI-09`），而 V2.2 的實作狀態記著
一句過期的說明要改（`plan/18/09` §3 第 18 條）。本期加三個輸入：

### 3.1 `required_labels`（tag）— **本期最值得做好的一個輸入**

```text
Tag   [ docker ✕ ] [ node20 ✕ ] [ gpu ✕ ]  [＋]
      ⚠ 目前沒有 runner 具備 `gpu`，這張卡會一直等。
      建議：docker(2)、node20(2)、arm64(1)
```

三條：

- **建議清單是「目前線上 runner 實際擁有的 tag」＋ 每個有幾台。**
  資料來自 `GET /api/agents`（已經回 `labels`）。
- **輸入一個沒有任何 runner 擁有的 tag 時當場提示。**
  這比等它掛在佇列上再去查便宜得多——**打錯一個字就永遠沒人領**
  是這個機制最常見的失敗。
- ⚠️ **提示不擋。** 一個明天才會上線的 runner 是合法的理由。

### 3.2 `required_secrets`

從 allowlist 多選。allowlist 為空時顯示
「這個專案還沒有可用的機密名稱」＋ 連到 Project Settings 的連結。

**已宣告但機密不存在的名稱要標出來**（`02-…md` §4.4 的第二種失敗）——
用 `warning` 樣式加一句「尚未建立」。

### 3.3 `source`／`base_branch`／`delivery`

`delivery` 的下拉現在有一個新的可選值 **`branch`**（D16）。
`pull_request`／`existing_pr` 仍然顯示但**標成「V2.4 起生效」並在選取時提示**——
不要把它們從清單移除，那會讓「這個平台以後會不會做 PR」變成一個要問人的問題。

`delivery: branch` 選取時顯示一行預覽：
**「將推送分支 `cliora/TASK-123-<次數>`」**——這是使用者第一次看到
平台會對他們的 repo 做什麼，值得寫出來而不是等 run 結束才在摘要裡出現。

## 4. Agents 頁（`AgentsView.vue`）

三處改寫，**其中兩處是現在錯的字**。

### 4.1 tag 欄：從「僅供辨識」改為「參與比對」

`AgentsView.vue:254` 現在寫著：

> labels 目前僅供辨識，不參與資格比對。

改成：

> tag 參與派工比對。由該 node 的 `agentd` 設定檔宣告，此處唯讀。

同一格顯示 `run_untagged`：關閉時顯示 **`只領有 tag 的卡片`**。
`accept_secrets: false` 時顯示 **`不收機密`**。

⚠️ **tag 旁邊不出現鎖頭圖示或「授權」字樣**（`00-…md` 不得弄壞第 11 條）。
這是一條**畫面斷言**（出口條件 3g），寫成 `AgentsView.test.ts` 的一條測試：
tag 那一格的 DOM 子樹裡不含 `🔒`／`lock`／`授權`／`permission` 這幾個字串。

### 4.2 授權邊界那一段：加強而不是移除

`AgentsView.vue:139–140` 現在寫著：

> 本階段的授權邊界是**節點納管**：任何一台已納管節點上的 Agent
> 都能領取任何專案的卡片、取得任何專案的程式碼。**逐專案的授權自 V2.3 起提供。**

**最後那一句是錯的**（2026-08-12 取消了那件事）。改成：

> 授權邊界是**節點納管**：任何一台已納管節點上的 Agent 都能領取任何專案的卡片、
> 取得任何專案的程式碼，**並取得那些卡片宣告的機密**。
> 這是刻意的設計而不是尚未完成的功能——縮小影響範圍的是
> 卡片級的機密宣告、node 端的 `accept_secrets`、以及機密可即時撤銷。
> tag 決定**派給哪台機器**，**不決定哪台機器可以拿機密**。

**最後那一句話單獨成行**，因為它是這一頁上最容易被誤讀的東西。

### 4.3 「用途姿態」欄不動

`dedicated` 的 ⚠ 混合用途（V2.2 交付）保持原樣。
它與本期的機密有一個新的關聯，寫成 tooltip 的一句：
**「混合用途的機器上，Agent 也讀得到互動式 Session 的工作目錄。」**
（`plan/18/04b` §3.4 的既有誠實性，本期沒有改變它。）

## 5. Enrollment 畫面（代償第 4 條，**不是文案潤飾**）

`EnrollmentView.vue`，**發 token 的那一頁**，發送按鈕旁邊：

```text
┌──────────────────────────────────────────────────────────┐
│ 這台機器將可以領取任何專案的卡片，並取得那些卡片宣告的機密。 │
└──────────────────────────────────────────────────────────┘
```

四條：

- **位置很重要**：它必須在**發 token 的那一頁**，不是躺在 Agents 頁或 runbook 裡。
- **不是提示框、不是 tooltip、不是折疊區**。它是一段一直在那裡的文字。
- 用 `warning` 的框線樣式，不是 `danger`——這是一個要知道的後果，
  不是一個錯誤（與 Secrets 頁的 ⚠ 同一個判斷）。
- **一條測試**（出口條件 3g）：`EnrollmentView.test.ts` 斷言這段文字存在且
  在建立 token 的表單內。**測文字內容而不是測某個 class**——
  這一條的價值就在那句話本身。

## 6. Run 詳情頁

四行新增：

```text
使用的機密    GITHUB_TOKEN、NPM_TOKEN            ← 只有名稱
推送的分支    cliora/TASK-123-1  ✅ 已推送
平台推到      github.com/org/repo
工作目錄的遠端 origin  github.com/org/repo (fetch/push)
```

- **只有名稱**（永遠不會有值可顯示）。
- **「平台推到」與「工作目錄的遠端」並排**（`04b-…md` §2.1）：
  不一致不是錯誤，但它是一個值得看見的事實。
- push 失敗時第二行是 `⚠ 未能推送：<原因>`，
  而**原因已經過 Redactor**（D6）。
- V2.2 已有的 `git remote -v` 與未推送 commit 數不動。

## 7. 測試

`frontend/src/components/project/ProjectSecrets.test.ts`：

1. 列表不顯示任何值的路徑——**斷言元件的 props 型別裡沒有 `value`**，
   而不是斷言畫面上看不到（後者在 DTO 加了欄位時仍然會綠）。
2. 刪除確認含「請另外到來源系統撤銷」那一句。
3. 主金鑰警語存在。
4. `git_pat` 與 `git_ssh_key` 各自的提示段落（旗標開啟時）。
4b. 🆕 **旗標關閉時兩個 git kind 顯示為停用且帶原因**，
   而 `env` 可選——**斷言的是「停用」不是「不存在」**（§2 的判斷）。

`AgentsView.test.ts`（V2.2 已有七條，本期加四條）：

5. tag 格顯示「參與派工比對」。
6. **tag 格的 DOM 不含鎖頭／授權字樣**（§4.1）。
7. `run_untagged: false` 顯示「只領有 tag 的卡片」。
8. 授權邊界那一段含「並取得那些卡片宣告的機密」且**不含**「V2.3 起提供」。

`EnrollmentView.test.ts`：

9. 那一句話存在且在表單內（§5）。

`TaskDetail.test.ts`：

10. 輸入一個沒有 runner 擁有的 tag → 出現提示，**但儲存按鈕仍可用**。
11. `delivery: branch` 顯示分支預覽。
12. 宣告一個尚未建立的機密名稱 → 標成「尚未建立」。

**第 1、6、8、9 條是安全審查第二節會直接引用的四條。**
