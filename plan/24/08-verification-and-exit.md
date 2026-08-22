# 08 — 驗證與封版條件

## 1. 三個新 gate

沿用 `scripts/cv/gates.sh` 的形狀，加在同一個腳本裡（**不開第二個腳本**：
八個舊 gate 與三個新 gate 回答的是同一個問題「這一版還成立嗎」，
兩個腳本的第一個後果是有人只跑其中一個）。

| Gate | 斷言 | 違反時會怎樣（而且沒有其他症狀） |
|---|---|---|
| `GATE-CE-NO-PRODUCT-DRIFT` | `git diff --stat ac3dfef -- backend/app frontend/src` 為空，且 `git status --porcelain -uall` 對這兩個目錄為空 | D68 被悄悄推翻：旅程紅了到底是產品缺陷還是剛剛那個小修正，沒有人分得出來 |
| `GATE-CE-JOURNEY-COVERAGE` | playwright 的 JSON report 裡七條旅程**各執行一次且沒有被 skip**；四條 API 旅程各留下一份 `artifacts/cv/local/journeys/J*.json` | **七條旅程全部 skip，套組仍然綠**——這是本期最可能發生的假綠 |
| `GATE-CE-EVIDENCE-FRESH` | `artifacts/cv/local/*.json` 裡的 `commit` 欄位等於 `--at` 指定的 ref（預設 HEAD） | 引用了上一輪的數字。`plan/23/10` §5 的 29.9 秒樣本就是「舊狀態污染新結論」的一次 |

`--at` 這個旗標是封版當天長出來的，理由值得寫下來：**證據屬於被 tag 的那個 commit，
不屬於「之後又提交了什麼」**。打完 tag 之後只要再有一次文件提交，`--at HEAD` 就會紅，
而一個永遠紅的 gate 是一個沒有人讀的 gate。所以：

```bash
uv run --project backend python scripts/cv/gate_closeout.py                        # 準備發版時
uv run --project backend python scripts/cv/gate_closeout.py --at v2.0.0-alpha.2    # 事後查核那一版
```

（它用 `<ref>^{commit}` 解析，因為 annotated tag 的 `rev-parse` 給的是 tag 物件本身的
hash——拿那個去比對證據會用一個沒有人猜得到的理由紅掉。）

### 1.1 `GATE-CE-NO-PRODUCT-DRIFT` 的例外怎麼寫

不是 `--exclude` 旗標，而是一個檔案：`scripts/cv/product-drift-waivers.txt`，
每一行是 `<path> <ticket-id> <一句話理由>`。gate 讀它、印出來、
並且**在輸出裡列出每一條 waiver**——一個沉默的例外清單，
半年後沒有人記得為什麼那三行在裡面。

這個形狀取自 `GATE-CV-TOUCH-LIST` 對 `secrets.py` 的處理方式：
`plan/23` 把那個例外寫在腳本的註解裡「所以例外是看得見的而不是沉默的」。

### 1.2 `GATE-CE-JOURNEY-COVERAGE` 怎麼實作

```bash
npx playwright test --project=chromium --reporter=json > report.json
```

然後斷言：`report.json` 裡 title 含 `J1a`／`J3`／`J7` 的 spec
`status == "expected"` 且 `annotations` 不含 `skip`。
四條 API 旅程各自寫一份 JSON 到 `artifacts/cv/local/journeys/`，
gate 檢查七個檔案都在、且 `commit` 是 HEAD。

**用 report 而不是 exit code**：playwright 的 exit code 對「全部 skip」是 0。
這正是要防的那件事。

## 2. 為什麼旅程不能被整合測試取代

J6 與 J9 已經有等價的整合測試，而它們仍然要被寫成旅程。理由值得寫下來，
因為每一次封版都會有人問：

```text
整合測試證明的                     旅程證明的
服務層的函式在同一個行程裡           兩個行程之間、跨 HTTP、跨 websocket、跨 5 秒 poll
用同一個 session、同一個交易         用真的 token、真的租約、真的子行程
在測試的 fixture 資料上             在真的 migration 跑過的資料庫上
「這段程式做對了」                   「這個系統做對了」
```

`plan/23/10` §9.1 是這個差別的一個具體案例：daemon 寫 `run.token`、
CLI 讀 `<id>.token`，**兩邊各自的單元測試都是綠的**，而中間那條縫
讓一個 staging run 的一生都在對著正常的平台印「無法連線」。
本期的每一條旅程都在問同一種問題。

## 3. 回歸範圍

本期不改產品程式，所以**沒有新的回歸面**。但有三件既有的事要重跑，
因為它們的前提是「在這個 commit 上」：

| 重跑什麼 | 為什麼 |
|---|---|
| `make check` ＋ 三套測試 | `CE-03`：`plan/23` 的綠是在一台跑了一整期的機器上得到的 |
| 八個既有 gate | 同上。`GATE-CV-MIGRATION-ROUNDTRIP` 需要資料庫，**沒有資料庫時它會 FAIL 而不是 skip**（`gates.sh` 刻意這樣寫） |
| `scripts/pj/gate-flag-off.sh` | flag matrix 的第一列（[`07`](./07-release-artifacts.md) §4） |

## 4. 封版條件（23 ＋ 5）

### 4.1 `plan/23/08` §7 的 23 項

前 22 項的狀態沿用 `plan/23/10` §6，本期只改動其中三項：

| # | 條件 | `plan/23` | 本期由誰關閉 |
|---:|---|---|---|
| 5 | daemon 重啟後只處理一次 | ☐ | **`CE-06`（J5）** |
| 11 | 三輪釐清在同一畫面完成 | ☐ | **`CE-05`（J1a）** |
| 16 | 未升級的 `agentd` 0.12.0 節點行為不變 | ☐ | **`CE-09`** |
| 23 | `v2` → `dev` 由人工核准 | ☐ | 流程，**本期仍不執行**（取得提案資格即可） |
| 1–4、6–10、12–15、17–22 | 已通過 | ☑ | `CE-03` **重跑確認**，不重新論證 |

第 23 項要說清楚：它不是「本期關不掉的條件」，
它是一個**永遠只有在人按下按鈕時才會被滿足的條件**。
tag 不需要它——`research/03/00` §8 說的是合併需要它。

### 4.2 本期新增的 5 項

| ☐ | # | 條件 | 證明 |
|---|---:|---|---|
| ☐ | 24 | 七條旅程**全部執行且無 skip**，各留下證據 | `GATE-CE-JOURNEY-COVERAGE` |
| ☐ | 25 | `backend/app/` 與 `frontend/src/` 零 diff，或每一處例外有具名 waiver | `GATE-CE-NO-PRODUCT-DRIFT` |
| ☐ | 26 | `research/03/00` §7 的九項產物齊備 | [`07`](./07-release-artifacts.md) §2 的表全部 ☑ |
| ☐ | 27 | `v2.0.0-alpha.1` 的 tag 存在且 target 是 `f91d9c4` | `git rev-parse v2.0.0-alpha.1` |
| ☐ | 28 | ADR 0035／0036／0037／0041 為 `accepted`，SR-1 具名簽核 | 檔案內容 |

### 4.3 一項刻意不設為條件的東西

**`FR-CONV-001`…`-010` 的 traceability link。** 十條需求已註冊，
`lifecycle: proposed`，**零條 link**——而這與 repo 的現況一致：
`links.json` 的 2090 條 link 裡，指向非 active 需求的有 **0 條**，
FR-AGENT／FR-RUNENV／FR-SPEC／FR-DELIVERY／FR-EVIDENCE／FR-VERIFY
六個 V2 家族全部如此。`scripts/trace coverage --scope all --strict`
現在通過，因為 `validate.py:458` 直接跳過非 active 的需求。

所以這不是 `alpha.2` 的缺口，是**整個 V2 系列共用的一個姿態**：
V2 的需求在 GA 收斂之前不進 release-blocking 的覆蓋率。
本期不單方面改變它（改了會讓 `alpha.2` 成為唯一被那個 gate 擋住的版本），
但把它寫進 [`09`](./09-open-measurements.md) §2，
並在 `beta.1` 的計畫裡當成一張橫跨所有 V2 家族的 ticket 提出。

## 5. 執行順序（一次完整的封版跑法）

```bash
export PATH="$HOME/.local/bin:/usr/local/go/bin:$HOME/.nvm/versions/node/v22.14.0/bin:$PATH"
export CLIORA_DATABASE_URL=postgresql+asyncpg://cliora:cliora@127.0.0.1:5432/cliora_e2e
export CLIORA_TEST_DATABASE_URL="$CLIORA_DATABASE_URL"

dropdb cliora_e2e && createdb cliora_e2e          # 乾淨資料庫，理由見 plan/23/10 §5
scripts/cv/capture-baseline.sh                    # COMMIT / contract-v1.sha256 / schema.txt
scripts/cv/evidence.sh                            # ①–⑨，見 02 §7
```

`evidence.sh` 最後印一份 tally 與一行結論。**它是 `CE-14` 唯一要讀的輸出**——
如果封版的人需要讀三個地方才能知道能不能 tag，那三個地方就會有一個被跳過。
