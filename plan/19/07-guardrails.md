# 07 — `UI-03`：守門

> **這是本期最重要的一張 ticket。**
> 修 104 個名字是還債；讓第 105 個不可能發生才是交付。
> 沒有這張 ticket，這一期就只是把同一個坑重新填平。

## 1. 為什麼既有的六道檢查全部沒抓到

`make check` = `format-check lint typecheck unit contract build traceability-validate railway-check`。

| 檢查 | 為什麼看不到 |
|---|---|
| `format-check`（Prettier） | 只管排版。`var(--nope)` 的排版完全正確 |
| `lint`（ESLint ＋ `eslint-plugin-vue`） | `flat/essential` 規則集**不解析 `<style>` 區塊**，也沒有任何 CSS 規則 |
| `typecheck`（`vue-tsc`） | TypeScript 不看 CSS |
| `unit`（Vitest ＋ jsdom） | **jsdom 不做 CSS 串接計算**——就算元件被 mount，也不會有人抱怨 |
| `build`（Vite） | `var()` 語法合法，打包成功。Vite **不驗證變數是否有定義**（它不能——變數可能在 runtime 由 JS 設定） |
| `contract` | 只跑 protocol fixtures |

**沒有 stylelint。** `frontend/package.json` 的 devDependencies 裡沒有它。

所以這個缺陷可以活過五次 commit、三個階段、兩次「前端已實作」的宣告——
**不是因為沒人 review，是因為沒有任何自動化在看這件事。**

## 2. 為什麼不直接裝 stylelint

考慮過，**不採用**，三個理由：

1. **它解決的問題比我們需要的大得多**：stylelint 的價值在規則集（排序、簡寫、
   相容性），而我們只要一條斷言。裝它就要選規則集、處理它與 Prettier 的重疊、
   為既有 40 幾個 `.vue` 的 scoped style 補一輪修正——**那是另一期的工作**。
2. **`no-invalid-custom-property` 這條規則不在 stylelint 標準集裡**，
   要靠 `stylelint-value-no-unknown-custom-properties` 這個第三方 plugin，
   而它需要餵一份 `importFrom` 的 token 檔清單——設定的複雜度不比自己寫低。
3. **新增一個 devDependency 要有更好的理由。** 這一期的檢查是 60 行 Node script，
   零依賴，跑在既有的 `node` 上。

> 若日後前端要導入完整的 CSS lint，**那時再裝 stylelint 並把這支 script 換掉**。
> 本期的 script 刻意寫得小到可以整支丟掉。

## 3. 檢查器規格

`scripts/frontend/check-tokens.mjs`，零依賴，Node 22。

### 3.1 做什麼

1. **收集定義**：解析 `frontend/src/theme/tokens.css` 與 `base.css` 裡
   所有 `--name:` 的宣告，成為 `defined` 集合。
2. **收集引用**：掃 `frontend/src/**/*.{vue,css,ts}`，抓出所有 `var(--name`。
   `.vue` 只掃 `<style>` 區塊與 `<template>` 裡的 `style="..."` 字面值。
3. **比對**：`referenced - defined - allowlist` 非空就 **exit 1**，
   並逐條印出 `檔案:行號  var(--名字)`。

### 3.2 白名單（`allowlist`）

三類合法的例外，寫成一個顯式陣列**並各自附理由**——
白名單沒有理由就會變成垃圾桶：

| 名字 | 為什麼合法 |
|---|---|
| `--vh`、`--vw` 之類由 JS 在 runtime 設的 | 若有，寫進來並註明是哪支 JS 設的 |
| xterm.js／Monaco 注入的變數 | 第三方在自己的 DOM 子樹上設定，我們的 token 檔管不到 |

**目前預期白名單是空的。** 開工時實測，有才加，加了要寫理由。

### 3.3 `var(--undefined, fallback)` 要不要擋？**要，但分兩級**

這一條要想清楚，因為 repo 裡**現在就有 21 個**（`02-…md` §1.0）。

`var(--status-danger, crimson)` 在 CSS 上完全合法，宣告不會被丟棄——
**它不會壞畫面**。但它做了一件更難發現的事：**把 token 系統繞過去**，
讓 `crimson`、`seagreen`、`darkorange`、`#d0d0d0` 進到一個有 design token 檔的專案裡。

所以檢查器輸出**兩級**：

| 級別 | 條件 | exit code |
|---|---|---|
| **ERROR** | `var(--未定義)` **無** fallback | **1** — 畫面真的壞了 |
| **WARN** | `var(--未定義, fallback)` | 預設 **1**（見下） |

**WARN 也讓它失敗**，理由是：這一期做完之後應該是 0 個，
留一個「警告但通過」的等級，等於留一個讓數字慢慢長回去的地方。

但給一個 `--allow-fallback` 旗標，**只給 `UI-02` 進行中的過渡期用**——
先修 83 個 A 類、讓守門上線擋住新的，再回頭處理 21 個 B 類。
**`UI-03` 完成時這個旗標必須從 `Makefile` 拿掉。**

錯誤訊息要分得出來：

```
ERROR  TaskBoard.vue:194   var(--color-surface-2)          宣告會被丟棄
WARN   ProjectsView.vue:375 var(--status-danger, crimson)  繞過 token，實際渲染 crimson
```

### 3.4 不做什麼（避免誤報）

- **不檢查未使用的 token**（定義了沒人用）。那是清理，不是正確性，
  而且會在 `UI-01` 剛加完 31 個 token 時全數誤報。
- **不解析 JS 動態組出來的變數名**（`var(--stage-${id})` 這種）。
  prototype 用這個寫法，但 `03-…md` 的元件族**刻意不用**——
  改成明確的 class 對應（見 `03-…md` §2.3），正是為了讓這支檢查器看得懂。
  **這是一個為了可檢查性而做的實作選擇，值得記住。**

### 3.5 掛進 `make check`

```makefile
tokens:
	node scripts/frontend/check-tokens.mjs

check: format-check lint typecheck tokens unit contract build traceability-validate railway-check
```

**放在 `typecheck` 之後、`unit` 之前**：它是靜態檢查，跑得比 unit 快，
失敗要早點失敗。同時加進 `.PHONY`。

### 3.6 反向測試（這一條不能省）

**一個不會失敗的守門等於沒有守門。**

`UI-03` 必須交付一個測試，證明檢查器真的會擋：

```bash
# scripts/frontend/check-tokens.test.sh（或 vitest 版本）
# 1. 在暫存副本裡注入一個壞引用
# 2. 跑檢查器，斷言 exit code = 1 且輸出含該檔名與 var(--cliora-does-not-exist)
# 3. 還原，斷言 exit code = 0
```

這支測試進 `unit`，所以**守門本身也被 `make check` 保護**。

出口條件 2 驗的就是這一條，而且要**手動再驗一次**（`08-…md` §5）——
自動測試證明它在受控情境下會擋，人工驗證證明它在真實 repo 上會擋。

## 4. 順帶擋住的第二種錯誤

同一支 script 幾乎免費地多做一件事：**偵測 `--color-*` 這種不存在的命名空間**。

因為 16 個錯名字裡有 6 個是 `--color-*` 開頭，而 `tokens.css` **從來沒有**
這個前綴。加一條額外斷言：

> 引用了 `--color-*` 前綴時，錯誤訊息額外提示：
> 「`tokens.css` 沒有 `--color-*` 命名空間，顏色 token 的前綴是
>  `--surface-` / `--text-` / `--border-` / `--action-` / `--status-`。」

**錯誤訊息要教人下一步怎麼做**，這是既有紀律（`09` §6：錯誤要有安全訊息 ＋ 可行動）。
一個只說「undefined token」的訊息，會讓下一個人再猜一次名字。

## 5. 完成定義

- [ ] `scripts/frontend/check-tokens.mjs` 存在，零依賴
- [ ] `make tokens` 在**修好後的** repo 上輸出 0 個問題
- [ ] `make tokens` 在**基線 commit** 上輸出 **83 ERROR ＋ 21 WARN = 104**（證明它抓得到真實缺陷，且兩級分得對）
- [ ] 反向測試進 `unit` 並通過
- [ ] `make check` 含 `tokens`，全綠
- [ ] 白名單為空，或每一項都有寫理由
- [ ] `--color-*` 的提示訊息有測試
