# 05 — 前端：導覽重整與 Project 畫面（`PJ-06`）

沿用 `research/style.md` 的 Quiet Intelligence ＋ Developer Workbench ＋ Modern Industrial。
**本期沒有新的視覺語言，只有新的資訊層級。** 不新增一次性色彩、間距、字級；
新徽章用既有 token 組合，缺的元件照既有風格補做並登記回 `frontend/src/theme/`。

一條貫穿全篇的原則（`research/02/09` §1）：

> **Terminal 仍然是主要工作區。** V2 加的所有東西都不得讓它變窄。

本期不碰 `SessionWorkspaceView.vue` 的版面，所以這條在本期是**一句禁令**：
如果 diff 出現在 `SessionWorkspaceView.vue` 的 `grid-template-columns` 或
`--layout-sidebar`，就是走錯路了。

## 1. 導覽重整

### 1.1 現況（讀 `AppLayout.vue`，不是讀規劃文件）

六個平項，其中三個是權限條件的：

```text
Dashboard        無條件
Nodes            無條件
Sessions         無條件
Enrollment       canManageEnrollment  (enrollment.manage)
Audit            canViewAudit         (audit.view)
Integrations     canManageIntegrations(integration.manage)
```

| 角色 | 看得到 | 數量 |
|---|---|---|
| Admin | 全部六項 | 6 |
| Developer | Dashboard、Nodes、Sessions | 3 |
| Viewer | Dashboard、Nodes、Sessions | 3 |

> `research/02/09` §2 寫「現況五個平項」並說要把 `Integrations`
> 「從只能從頁內進入升格為導覽項」——**兩句都與程式碼不符**（`plan/11` 已經做了）。
> 本期的比對基準與 M8 的量測基數照上表。

### 1.2 目標

```text
Projects                    ← 新，hasFeature('projects') && hasPermission('project.view')
  Projects                    /projects

Sessions                    ← 既有 /sessions，位置與樣式不變
  Sessions                    /sessions

Infrastructure
  Dashboard                   /dashboard        無條件
  Nodes                       /nodes            無條件
  Enrollment                  /enrollment       enrollment.manage
  Audit                       /audit            audit.view
  Integrations                /settings/integrations  integration.manage
```

三條硬規則：

1. **既有路由路徑一律不變。** 這是重新分組，不是搬家。任何人存的書籤都還能用。
2. **旗標關閉時退回 §1.1 的原樣**，含順序與（沒有分組標題的）平坦結構。
   不是「隱藏 Projects 群組但保留分組」——是**完全退回**，截圖比對逐像素相同。
3. **`Sessions` 自己一組**，即使它只有一項。它與 `Agents`（V2.2）是兩條執行路徑的入口，
   刻意分開；把 run 混進 Sessions 清單會讓兩種生命週期看起來像同一種東西。
   本期就把這個位置留出來，V2.2 才不用再搬一次。

### 1.3 分組標題的實作 — **無縮排分隔線（2026-08-08 定案）**

沿用 `research/prototype-v2/` 的做法：**分組標題是一條分隔線 ＋ 一個極小的標籤，
子項不縮排。**

```text
  ▦ Projects
  ▷ Sessions
  ──────────────  Infrastructure        ← 分隔線 ＋ 11px 標籤，無縮排
  ◈ Dashboard                            ← 子項與上面兩項對齊，不縮排
  ▣ Nodes
  ◉ Enrollment
  ☰ Audit
  ⇄ Integrations
```

**三個理由**（兩種做法都通過 M8，所以這是設計選擇不是被寬度逼的）：

| | 分隔線（**採用**） | 標題列 ＋ 12px 縮排 |
|---|---|---|
| 最寬項 | `Integrations` **147px**，餘裕 **61px** | `Integrations` 159px，餘裕 49px |
| 側欄還會再長 | V2.2 加 `Agents` 到 `Infrastructure` 底下變六個子項，每一列都省 12px | 每一列付 12px |
| 與 `plan/09` 的方向 | 一致（密度、空間讓給中央區） | 反向 |
| 你看過了嗎 | ✅ prototype 已畫出並量過（README 記 158px／50px，與實測 159／49 對上） | ❌ 只存在於文件裡 |

一個三組八列的側欄不需要縮排來表達層級——分隔線就夠。

**單項群組仍然摺疊。** `Projects` 與 `Sessions` 各只有一項，所以它們**不產生標題**，
就是兩個平項；只有 `Infrastructure` 上方有分隔線與標籤：

```text
渲染規則：一組只有一項且標題與項名相同時，渲染為一個沒有分隔線的平項。
```

這讓本期實際新增的高度是**一條分隔線 ＋ 一個導覽項**，不是三條分隔線。

**分組標題不是連結、不可收合。** 收合狀態要持久化（localStorage）、要處理
「當前路由在收合的組裡」、要有動畫——為了一個最多八列的側欄不值得。
`Infrastructure` 永遠展開。

### 1.4 M8 的處置 — **已量，落在第一檔**

> **2026-08-08 實測**（`scripts/pj/measure-sidebar.mjs`）：採用的分隔線版本
> 最寬是 `Integrations` 的 **147px**，208px 餘裕 **61px**。
> **什麼都不用改**——sidebar 維持 208px。完整數字見 `08-…md` §1。
>
> 一處推論要更正：我原本假設非 Admin 只看得到三項時，`Infrastructure` 這個
> **分組標籤**會變成最長的東西。實測不是——`Dashboard` 的 138px 比標籤的 122px 寬。
> 下面的第二、三檔因此用不到。

處置階梯（**分隔線已經是階梯的第二階，本期直接從那裡起跳**），
供 V2.2 加 `Agents` 時再用：

| 結果 | 做什麼 |
|---|---|
| 最長項 ＋ 24px ≤ 208px | 什麼都不用改 ← **2026-08-08 落在這一檔（147px／餘裕 61px）** |
| 略超 | 分組標籤字級降一階並改用 `--text-muted`；icon 與文字的 gap 11→8px |
| 仍超 | 最長的標籤改詞（`Integrations` → `Integration`／`整合`——中文標籤比英文短，而 `research/style.md` 本來就朝中文化走） |
| 還是超 | **停下來，寫一份翻案 `plan/09` 的說明再談加寬** |

**縮排那一檔已經用掉了**：本期就是選了不縮排的版本（§1.3），所以它不在階梯上——
沒有 12→8px 可以退，因為根本沒有 12px。

第四檔不是形式主義：`plan/09` 把 sidebar 從 280 收到 208 的整個理由是
「空間讓給中央區」，而 `plan/08` 與 `research/style.md` §12／§18 是同一個方向。
加寬會一次推翻三份決定，那需要一份寫得出來的理由。

### 1.5 `AppLayout.test.ts`

既有測試的 `testRouter()` 要加 `/projects` 路由，`render()` 的預設 permissions 要能
表達「有／沒有 project.view」與「features 有／沒有 projects」四種組合。

新增四條：

1. `features: []` → 完全沒有 `Projects` 群組，且**沒有任何分組標題**（退回平坦）。
2. `features: ['projects']` ＋ `project.view` → 有 `Projects` 與 `Infrastructure` 兩個標題。
3. 六個既有導覽項的 `href` 在兩種狀態下都不變（**這是「重新分組不是搬家」的機器檢查**）。
4. Viewer（三項）在旗標開啟時看到 `Projects` ＋ `Infrastructure`（Dashboard、Nodes），
   `Infrastructure` 底下只有兩項——**空的群組不渲染標題**。

第 3 條是本節最重要的一條測試。

## 2. 路由

`frontend/src/router/index.ts` 加兩條，放在 `/sessions` 那一組附近：

```ts
routes.push({
  path: "/projects",
  name: "projects",
  component: () => import("../views/ProjectsView.vue"),
});
routes.push({
  path: "/projects/:id",
  name: "project-detail",
  component: () => import("../views/ProjectDetailView.vue"),
  props: true,
});
```

**沒有 route guard**，沿用 `/audit` 與 `/settings/integrations` 的既有裁決與註解：

> 客戶端 guard 決定的是**渲染什麼**，不是**允許什麼**。沒有權限而走到這裡，
> 看到的是伺服器自己那個 403 驅動的畫面。

旗標關閉時直接走到 `/projects` 會拿到 404 驅動的空狀態（API 回 404），
**不是白畫面也不是重導**。這與「`/projects*` 404」的出口條件一致：
路由存在但沒有內容，就跟一個被移除的 node 的詳情頁一樣。

## 3. `/projects` — 專案列表

表格列（不是卡片：這一頁的用途是掃描與比較，而列比卡片密）：

| 欄 | 內容 |
|---|---|
| 名稱 | ＋ slug 以 `--text-muted` 顯示在下方（slug 是給 CLI 與 URL 用的，人要看得到它） |
| 狀態 | 徽章。`active` 用中性色、`paused` 用 warning 的線框、`archived` 用最低調的灰 |
| Workspace | `3 個目錄 · 2 台機器` |
| 進行中 Session | 數字，0 時顯示 `—` 不顯示 `0` |
| 最後活動 | 相對時間 ＋ tooltip 顯示本地絕對時間與時區 |

篩選：狀態、我擁有的。

**空狀態要有意義**，而且**依角色不同**：

| 角色 | 文案 |
|---|---|
| Admin | 「還沒有專案。〔建立專案〕。你仍然可以直接從 Sessions 建立 Ad-hoc Session。」 |
| 非 Admin | 「還沒有專案。請 Admin 建立，或直接從 Sessions 建立 Ad-hoc Session。」 |

第二句在兩種文案裡都在——它同時教了兩件事：專案是可選的，Ad-hoc 沒有被取代。

## 4. `/projects/:id` — 專案總覽

本期只做 `Overview` 與 `Activity` 兩個分頁。
`Requirements`／`Board`／`Roadmap`／`Settings` 是 V2.1 之後的，
**現在不要先放灰掉的 tab**——一個點不下去的 tab 是一個沒有兌現的承諾。

### 4.1 Overview

```text
+------------------------------------------------------------------+
| Demo                       [active]            〔編輯〕〔封存〕   |
| demo · 由 neil 建立於 2026-08-08                                 |
+------------------------------------------------------------------+
| 描述（markdown 不渲染，純文字。本期不引入 markdown 渲染器）      |
+------------------------------------------------------------------+
| 綁定的 Workspace                              〔綁定 Workspace〕 |
|  ● dev-vm-01   /srv/traqora          主要      〔開 Session〕     |
|  ● build-02    /opt/traqora-ci                 〔開 Session〕     |
|  ○ old-vm      /home/x/traqora   root 已停用   （不可開）        |
+------------------------------------------------------------------+
| 進行中的 Session（3）                                            |
+------------------------------------------------------------------+
| 近期活動（10 筆）                          〔查看全部〕          |
+------------------------------------------------------------------+
```

**綁定列的狀態表達是本頁的核心**，而不是裝飾（`03-…md` §2.4 的
`BindingUsability`）。三種不可用**都不是錯誤頁**，是這一列上的一個狀態：

| 值 | 指示燈 | 說明文字 | 〔開 Session〕 |
|---|---|---|---|
| `ok` | ● 綠 | — | 可按 |
| `node_offline` | ○ 灰 | 「機器離線」 | 停用，tooltip 說明 |
| `root_disabled` | ○ 橘 | 「這台機器已不再允許這個目錄」 | 停用 |
| `node_removed` | ○ 灰 | 「機器已移除」 | 停用 |

> **「路徑已不存在」本期偵測不到**（需要問 node，而本期不動 protocol）。
> 使用者會看到 `ok` 然後在建立 Session 時失敗——那個失敗是 daemon 給的、
> 訊息是既有的、行為與今天手動輸入一個不存在的路徑**完全一樣**。
> 這是一個已知缺口而不是一個 bug，寫在 `06-…md` §5 與 `08-…md` M-PJ-04。

〔開 Session〕**不是一個新流程**：它導向既有的 `NewSessionDialog`，
預填 `node_id`、`workspace`、`project_id`，runtime 與名稱仍由使用者填。
本期不做「一鍵開 Session」（`00-…md` §2）。

**預填走 query string，不走 store**（`/sessions?project_id=…&node_id=…&workspace=…`）：
它可以被連結、重整後還在，而且讓 dialog 維持成一個「收 props」的元件，
不必反過來去 store 裡打聽自己為什麼被打開。`SessionsView` 讀到預填時**直接打開對話框**——
使用者已經按過一個寫著「在這裡開 Session」的按鈕，再要他按一次〔New session〕
是為同一個意圖問兩次。取消時把 query 從 URL 拿掉，否則下次按〔New session〕
會安靜地重用一個已經被放棄的意圖。

> **實作時踩到的坑，記下來**：第一版只做了 `router.push({ query })`，
> 而 `SessionsView` 根本沒有讀 query——按鈕看起來會動，實際上把人送到一個空的
> Session 列表。**一個看起來有反應的死按鈕比一個沒有的按鈕糟**，
> 因為它不會被回報成缺功能。`projects.spec.ts` 的第二條測試就是守這件事。

### 4.2 Activity

時間軸列表，每列：時間（相對 ＋ tooltip 絕對）、kind 的中文標籤、
一句由 payload 組出來的描述、actor。

**沒有 `audit.view` 時**：actor 欄顯示 `—`，並在列表頂端一行說明
「部分資訊需要稽核權限才能顯示」（由回應的 `actors_hidden` 驅動）。
**不是靜默留白**——留白會讓人以為那是系統事件（而系統事件本來就沒有 actor，
兩者必須分得出來）。

**不重用 `components/dashboard/ActivityTimeline.vue`。**
它吃的是 audit 形狀的資料（`action`／`actor_name`／`node_name`），
而這裡是 activity 形狀的（`kind`／`payload`／`session_id`）。
新做 `components/project/ProjectActivityFeed.vue`。
兩個元件會長得像，但把它們合併需要一個能同時表達兩種 payload 的抽象，
而那個抽象會比兩份各自簡單的實作更難讀。

分頁用「載入更多」（keyset 游標），不是頁碼——時間軸只往一個方向讀。

## 5. Session 建立表單

`NewSessionDialog.vue` 加一個 **optional** 的 Project 下拉，放在 Node 之前
（選了 Project 之後 Node 與 Workspace 的候選會收窄，順序要跟著資料流）。

| 情況 | 行為 |
|---|---|
| 旗標關閉 | **整個欄位不存在**，對話框與升級前逐像素相同 |
| 沒有任何 Project | 欄位仍出現但停用，說明「還沒有專案」 |
| 選了 Project | Node 與 Workspace 收窄為該 Project 的**可用**綁定（`usability !== 'usable'` 的不列——列出來等於提供一個伺服器一定會拒絕的選項）；`archived` 的 Project 不出現在下拉裡 |
| 選了 Project 之後換 Node | 若原本選的 node 不在該 Project 的綁定裡，**清掉它**。留著一個過期的選擇會送出一組伺服器會以 `SESSION_PROJECT_MISMATCH` 拒絕的配對 |
| 綁定路徑 | 以按鈕列出、輸入框轉為唯讀。因為比對是**完全相等**，手打一個子目錄是最容易撞上那個拒絕的方式 |
| 沒選 Project | Node 與 Workspace 是既有的完整候選（**Ad-hoc 路徑一個位元組都不變**） |
| 從 Project 頁面進來 | 三個欄位預填且 Project 欄位唯讀（有 `〔改為 Ad-hoc〕` 可以解開） |

`NewSessionDialog.test.ts` 加一條：**旗標關閉時渲染出來的欄位集合與升級前相同**。

## 6. Store 與 API client

- `frontend/src/stores/projects.ts`：列表、詳情、時間軸。形狀照 `stores/sessions.ts`。
- `frontend/src/api/dto.ts`：`ProjectDTO`、`ProjectDetailDTO`、`ProjectWorkspaceDTO`、
  `ActivityEventDTO`、`BindingUsability`、`ACTION_PROJECT_*`、`FEATURE_PROJECTS`、
  `UserDTO.features`、`AUDIT_ACTIONS` 的五個新值。
- 錯誤處理走既有的 `utils/errorCatalog.ts`——五個新碼要有中文文案，
  否則會退到通用訊息。

## 7. 狀態與可用性（每個新畫面都要交付）

沿用既有紀律，逐項列出而不是「照 design system 做」：

| 狀態 | 要求 |
|---|---|
| 載入中 | 骨架，不是 spinner 蓋全頁 |
| 空 | 有下一步動作的文案（§3 的例子），且**依角色不同** |
| 錯誤 | 安全訊息 ＋ `request_id` ＋ 重試 |
| 權限不足 | 由伺服器 403 驅動的畫面，**不做前端路由守衛** |
| 旗標關閉 | `/projects` 顯示 404 驅動的空狀態；導覽完全退回 |
| Node 離線 | 綁定列上的一個狀態，不是錯誤頁 |
| Root 已停用 | 同上，且**文案與離線不同**（一個是機器不在，一個是這個目錄不再被允許） |
| 封存的 Project | 頁面正常顯示，寫入類按鈕停用並說明「已封存」，附〔解除封存〕 |
| 時間軸為空 | 「還沒有活動。從這裡開一個 Session，或綁定一個 Workspace。」 |
| actor 被遮蔽 | 頂端一行說明，不是靜默留白 |

## 8. Design token

- 三個 `status` 徽章（`active`／`paused`／`archived`）與**既有 Session 狀態色明顯區分**。
  同一個畫面上會同時出現「Session 進行中」與「專案 active」，全用同一個綠色會讓人
  看不出差別。建議：Session 沿用既有色，Project status 用中性／warning 線框／灰三檔，
  **刻意不用綠**——把綠留給 V2.1 的 stage 與 V2.2 的 run。
- 四個 `BindingUsability` 用**指示燈 ＋ 文字**，不只用顏色（可及性）。
- 時間一律 RFC 3339 UTC 傳輸、畫面轉本地並顯示時區（既有 `utils/time.ts`）。

## 9. 驗收

| 檢查 | 方法 |
|---|---|
| 分組不搬家 | `AppLayout.test.ts` 的第 3 條：六個既有 `href` 在兩種旗標狀態下相同 |
| 旗標關閉的外觀 | Playwright 截圖 × 三個角色，與 `PJ-00` 的 B3 基線比對 |
| 五個既有路由可直達 | e2e 逐一造訪 `/dashboard`、`/nodes`、`/sessions`、`/enrollment`、`/audit`、`/settings/integrations` |
| sidebar 未加寬 | 一條斷言 `getComputedStyle(...).getPropertyValue('--layout-sidebar') === '208px'`（放在既有的 measuring Playwright 測試裡，`plan/09` 已經有那個位置） |
| 綁定列四種狀態 | 前端單元測試 × 4，各自的文案與按鈕可用性 |
| actor 遮蔽 | 前端單元測試：`actors_hidden: true` 時顯示說明列且 actor 欄是 `—` |
| Ad-hoc 對話框不變 | `NewSessionDialog.test.ts` 的欄位集合比對 |
| e2e 主線 | 建 Project → 綁兩個 node 的 workspace → 從綁定列開 Session → 時間軸出現兩筆 → 解綁 → session 仍在 |
</content>
