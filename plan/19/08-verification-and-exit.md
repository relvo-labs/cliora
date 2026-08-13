# 08 — `UI-12`：驗證、出口條件與合併關卡

## 1. 共通完成定義（每張 ticket）

1. 決策寫在 `01-…md` 或本目錄對應章節，不留在 commit message 裡；
2. 自動測試涵蓋該 ticket 的行為斷言；
3. **`make check` 全綠，含新增的 `tokens` 一項**；
4. 操作證據進 `09-implementation-status.md`；
5. 與規劃層（`research/02/12`）不一致時，**回寫規劃層**。

## 2. 測試矩陣

| 層 | 測什麼 | 在哪 |
|---|---|---|
| **靜態** | 零個未定義 `var()` | `make tokens`（`UI-03`） |
| **靜態** | 守門真的會擋 | `check-tokens` 的反向測試（`unit`） |
| 單元 | 徽章標籤、三級變體、未知值退路 | `components/ui/*.test.ts` |
| 單元 | `SourceBadge` 是唯一的 source 徽章來源 | 掃描式斷言（見 §3） |
| 單元 | D24 唯一性：只有 `waiting_for_input` 有色條 | `TaskBoard.test.ts` |
| 單元 | `EmptyState` 缺 `action` slot 會警告 | `EmptyState.test.ts` |
| 單元 | `prefers-reduced-motion` 不套位移動畫 | `TaskBoard.test.ts` |
| 契約 | board payload 新增三欄；OpenAPI 快照 | `backend/tests/contract` |
| 效能 | **M1 重量 ≤ 90 KB** | 量測腳本，記進 `10-…md` |
| e2e | 拖曳拒絕兩種（相依／409）toast ＋ 彈回 | `tests/e2e/projects.spec.ts` |
| e2e | 兩種等待文案逐字不同 | 同上 |
| **視覺** | V1 畫面逐像素不變（旗標關閉） | Playwright screenshot（`UI-12`） |
| **視覺** | Session Workspace 右欄仍 300px | 既有斷言回歸 |
| 回歸 | **`TokenShowcaseView` 不進 production bundle** | P4-07 定的 `dist` grep 斷言，`UI-11` 擴充後不得失效 |

## 3. 三條掃描式斷言

跟 `plan/18` §3.1 同樣的做法：**有些規則靠 review 盯不住，要寫成掃描測試。**

| # | 斷言 | 為什麼 |
|---|---|---|
| 1 | `src/` 底下除了 `theme/` 與 `ui/BaseBadge.vue`，**沒有任何檔案含裸 hex 色碼** | 這一期修的就是「顏色沒有經過 token」。允許 `theme/` 定義、允許 `BaseBadge` 的中性灰，其餘一律要用 token |
| 2 | `machine_verified`／`platform_observed`／`agent_reported` 這三個字串**只出現在 `ui/labels.ts` 與 `ui/SourceBadge.vue`** | D10 的「三處完全一致」在結構上為真，而不是靠人記得 |
| 3 | `--run-waiting` **只被 `RunBadge` 與看板卡片的 waiting 樣式引用** | D24 之所以有效是因為它唯一。第三個引用點出現時要有人被迫解釋為什麼 |

第 1 條開工時要先掃一次基線——若既有裸 hex 太多（`TokenShowcaseView` 就有三個），
先列白名單並在 `UI-11` 逐一清掉，**不要為了讓測試綠而放寬規則**。

## 4. 視覺回歸基準怎麼取（`UI-12`）

這一期的特殊之處：**修好 token 本身就會改變外觀**，
所以基準不能在期初取一次就用到期末。

| 時機 | 取什麼 | 用途 |
|---|---|---|
| `UI-00`（期初） | 全畫面 screenshot，**含壞掉的 V2 畫面** | 證據，不是基準。放進 `09-…md` 當「修之前長這樣」 |
| **`UI-02` 之後** | **V1 畫面**（旗標關閉）的 screenshot | **這才是出口條件 8 的基準**——V1 畫面在 `UI-02` 之後就不該再變了 |
| `UI-12`（期末） | V2 畫面 screenshot | 之後的基準，交給 V2.3 |

**21 個 B 類引用的前後對照要人工確認**（`02-…md` §3.3）：
它們今天用 fallback 值渲染（`crimson`／`seagreen`／`darkorange`／`#d0d0d0`／裸 `monospace`），
**看起來是正常的**，改成 token 值之後顏色會變。這是預期中的修正，
但因為它動的是「今天看得見的東西」，**風險比修 83 個 A 類高**，必須有人看過。

涉及 8 個檔案，其中 4 個是 V1（`NewSessionDialog`／`SessionWorkspaceView`／`EnrollmentView`／`FileTreeNode`），
4 個是 V2.0／V2.2（`ProjectDetailView`／`ProjectsView`／`AgentsView`／`RunDetailView`）。

**確認之後才把 V1 基準定下來。** 順序不能顛倒。

## 5. 出口條件（9 條）

| # | 條件 | 怎麼證明 |
|---|---|---|
| 1 | **零個未定義 token**（ERROR 與 WARN 都是 0） | `make tokens` 輸出 0；`--allow-fallback` 旗標已從 `Makefile` 移除 |
| 2 | **守門真的會擋** | ①反向測試在 `unit` 內通過；②**人工**在真實 repo 加一個 `var(--nope)`，`make check` 失敗，還原後全綠。兩者都要 |
| 3 | 三種「進行中」可區分 | `TokenShowcaseView` 三顆並排截圖，**人工確認**（`09` §7）。**截圖來自 dev build**——該頁是 `import.meta.env.DEV` 限定（`06-…md` §2.4），證據要註明來源 |
| 4 | **D24 成立** | 看板截圖：等待中的卡在一整面看板上第一眼被看到；且 `active_run_status` 由契約供給（掃描斷言 3） |
| 5 | 拖曳拒絕就地看得見 | 兩個 e2e：toast 出現、文案**指名是哪幾張卡**、卡片回原車道 |
| 5b | **兩種等待文案逐字不同** | e2e 斷言兩則字串不相等且各自符合預期（`plan/18` 出口條件 4／5 的回歸） |
| 6 | 三處 `source` 徽章完全一致 | 掃描斷言 2 ＋ 三處截圖 |
| 7 | **看板 payload 未回退** | M1 重量 ≤ 90 KB，寫進 `10-…md`；`tasks.py` docstring 已更新 |
| 8 | **V1 畫面逐像素不變** | 旗標關閉的 screenshot 比對（基準取自 `UI-02` 之後，§4） |
| 9 | Terminal 未變窄 | Session Workspace 右欄仍 300px（既有出口條件回歸） |

### 5.1 出口條件 3 為什麼是人工

它問的是「**一眼能不能區分**」，那是一個知覺問題，
自動測試只能斷言三個顏色的 hex 不相等——而那正是它們原本就不相等卻仍然分不出來的情況。

prototype README 把這一條列為「請優先確認的七件事」之四，**做法照舊：人看**。

看的地方是 `TokenShowcaseView`，而 P4-07 保留那一頁的理由正是
「**它是唯一能一頁看完 token 系統的地方，成本為零**」——
本期讓 token 從 27 個變 58 個，那句話只會更成立。

## 6. 安全審查：不觸發

判準是 `research/02/10` §6 的四項觸發條件（新增執行面／機密面／對外提供面／信任邊界），
本期一項都不符合。詳見 `01-…md` §7。

唯一的 API 變更（`UI-06` 三欄位）不含機密、不含路徑、不含使用者可控自由文字，
RBAC 沿用 `project.view` 不新增動作。

## 7. `scripts/ui/evidence.sh`

沿用 `plan/17`／`plan/18` 的做法：一支腳本跑完全部可自動化的出口條件，
輸出逐條 PASS／FAIL。

```
[1/9] 未定義 token .......... PASS (0)
[2/9] 守門反向測試 .......... PASS
[3/9] 三種進行中 ............ MANUAL — 見 artifacts/ui/local/showcase.png
[4/9] D24 ................... PASS (掃描斷言 3)
[5/9] 拖曳拒絕 e2e .......... PASS (2/2)
[5b/9] 等待文案 ............. PASS
[6/9] source 三處一致 ....... PASS
[7/9] M1 重量 ............... PASS (?? KB / 90 KB)
[8/9] V1 逐像素 ............. PASS
[9/9] Terminal 寬度 ......... PASS
```

**人工項顯示成 `MANUAL` 並指向證據檔**，不顯示成 PASS——
一個把人工確認自動標成通過的腳本，比沒有腳本糟。

## 8. Release note 與文件

| 檔案 | 內容 |
|---|---|
| `research/style.md` | 31 個新 token（`UI-01`） |
| `contracts/CHANGELOG.md` | 一行：board 欄位變更為何不在此檔（D33） |
| `docs/` | **不需要新 runbook**——本期沒有新的維運面 |
| `plan/19/09-…md` | 實作進度、與計畫不同的事、人工待辦 |
| `plan/19/10-…md` | M1 重量結果 |

## 9. 合併回 `dev`

**規則不變**：`v2` → `dev` 一律由人決定。
出口條件全綠只是取得**提案資格**，不是核准（`research/02/10` §7）。

提案時要一併附上：

1. `evidence.sh` 的完整輸出；
2. 人工確認的截圖：出口條件 3（三種「進行中」並排）、以及 21 個 B 類引用涉及的 8 個檔案前後對照；
3. M1 重量的前後對比；
4. **`make tokens` 在基線 commit 上輸出 83 ERROR ＋ 21 WARN、在 HEAD 上輸出 0** 的對照——
   這一條最能說明這一期做了什麼。
