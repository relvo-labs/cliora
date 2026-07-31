# 01 — Workspace 版面與中央區 Tab 化（WT-01、WT-02、WT-03）

本文件是波次 0，可獨立上線，**不得夾帶任何 shell 相關變更**。

## WT-01：左欄 Sessions 退場與規格同步

### 1.1 程式變更

`frontend/src/views/SessionWorkspaceView.vue` 三處：

| 位置 | 現況 | 改為 |
|---|---|---|
| `:201-204` | `<aside class="rail sessions-rail">` + `<h2>Sessions</h2>` + 「切換自 Sessions 清單。」 | 整段刪除 |
| `:329` | `grid-template-columns: 200px 1fr 300px` | `grid-template-columns: 1fr 300px` |
| `:390-398` | `@media (max-width: 1100px)` 內同時隱藏 `.workspace-rail, .sessions-rail` | 只留 `.workspace-rail` |

`.rail`／`.rail h2` 的樣式規則（`:360-373`）**保留**——右欄 `FileTree` 仍在用。

header 的 `Back` 按鈕（`:184`）與 `AppLayout.vue:51` 的 sidebar 連結**不動**，它們是移除後唯一的切換入口，必須確認兩者都還在。

### 1.2 規格同步（本 ticket 的主要工作量）

左欄與「面板拖曳/收合」都是規格明文要求過的，移除等於改規格。以下每一處都要改，並且要寫出「為什麼放棄」，而不是靜靜刪掉：

| 檔案 | 位置 | 現況內容 | 處置 |
|---|---|---|---|
| `research/prd.md` | §10.6（第 1451 行起的三欄示意圖） | 左欄 `Sessions` / `Claude ●` / `Codex`；文末「右側 Workspace 區域提供：Files / Preview / Info」 | 示意圖改兩欄；把 Files/Preview 的位置更正為「中央區 tab」，`Info` 併入 header（現況本來就沒有 Info 面板） |
| `research/tech.md` | §16.1（1699-1727） | 三欄示意圖；「支援：左右面板拖曳調整／Workspace 面板收合／Terminal 自動 Fit／頁面刷新後重連／Session 切換時保留狀態」 | 示意圖改兩欄；**刪除拖曳與收合**兩項（從未實作，見 `00-execution-plan.md` §2）；新增「中央區以 tab 切換，非作用中 panel 保留 DOM」 |
| `research/style.md` | §12（585-604） | 三欄 ASCII 圖 | 改兩欄，並保留「Terminal 佔最大比例」這句——它現在才真的成立 |
| `plan/03/05-frontend-session-flow.md` | `:27-29`、`:33`、`:35`、`:38` | 左欄「列表/切換」、拖曳/收合、「左欄 session 清單支援切換不同 session」、驗收項「session 切換不串流」 | 各加一行 `> 已於 plan/08（WT-01）放棄，理由見 plan/08/00-execution-plan.md §2 與 §6`。**不刪除原文**——它是當時的決定，改變決定要留下痕跡 |
| `plan/03/09-implementation-status.md` | `:20` | P2-12 標 ✅，說明只提「三欄、P3 workspace 面板佔位」 | 補上「左欄自始為佔位，未實作 session 切換；已於 plan/08 移除」 |
| `docs/p2-report.md` | `:24` | 「✅ 3-column layout」 | 同上，補實情與指向 plan/08 |

### 1.3 驗收

- `grep -rn "sessions-rail" frontend/src` 無結果。
- `grep -rn "三欄\|3-column" research plan docs` 的每一處命中都指向已更新的兩欄敘述，或帶有放棄註記。
- `frontend/tests/e2e/session.spec.ts` 新增一條斷言：進入 `/sessions/:id` 後 `page.getByRole("heading", { name: "Sessions" })` 的計數為 0（現在是 1，來自左欄的 `<h2>`）。這是最便宜的回歸鎖。
- 1440×900 與 1100px 以下皆無水平溢位。

---

## WT-02：xterm 掛載生命週期修正

**這是 `WT-03` 的前置條件，不是可選項。**

### 2.1 缺陷

`useTerminalSession.ts:139-140`：

```ts
function mount(element: HTMLElement): void {
  if (terminal) return;          // ← 已存在就什麼都不做
```

唯一呼叫點是 `SessionWorkspaceView.vue:90-99` 的 `onMounted`，且只在 `resource.state === "success"` 時才呼叫。於是：

1. 初次載入失敗 → 模板走到 `:139-145` 的 error `AsyncState`，`.workspace` 整段（含 `ref="host"`）不存在。
2. 使用者按 `:144` 的 Retry → 成功 → `.workspace` 出現，`host` 拿到一個**新的** DOM element。
3. 但 `onMounted` 不會再跑，沒有任何人呼叫 `mount()`；即使有人呼叫，`if (terminal) return` 也會擋掉。
4. 結果：終端機面板永久空白，只能重新整理頁面。

同一個機制在 `props.id` 切換 + forbidden 時也會發生（`00-execution-plan.md` §6 第 3 項），但那條路徑已決定不修。

### 2.2 修法（兩層）

**第一層：結構上不讓 host 被卸掉。** `SessionWorkspaceView.vue` 的 loading/forbidden/error 三個 `AsyncState` 目前是 `v-if`/`v-else-if` 鏈，與 `.workspace` 互斥。改為：`.workspace` 容器恆存在，三個狀態以覆蓋層（或 `v-show`）呈現在其上。這樣 `host` 從第一次 render 起就不再消失。

**第二層：掛載改由 ref 驅動，並支援搬移。**

```ts
// SessionWorkspaceView.vue —— 取代 onMounted 內的 terminal.mount(host.value)
watch(host, (element) => {
  if (element) terminal.mount(element);
}, { immediate: true });
```

```ts
// useTerminalSession.ts —— mount 對「已存在但換了容器」要能搬過去
let hostElement: HTMLElement | undefined;
function mount(element: HTMLElement): void {
  if (disposed) return;
  if (terminal) {
    if (hostElement === element) return;      // 同一個容器：真的沒事可做
    if (terminal.element) element.appendChild(terminal.element);  // 搬移而非重建
    hostElement = element;
    observer?.disconnect();
    observer = makeObserver();                 // 觀察新容器
    observer.observe(element);
    fitSafely();
    return;
  }
  // …既有的建立流程，最後記下 hostElement = element
}
```

搬移而不是重建，是因為重建會丟掉整個 scrollback 並需要重新 attach——那是使用者看得見的倒退。

### 2.3 隱藏容器的尺寸污染（`WT-03` 依賴此項）

`display: none` 的容器 `clientWidth/clientHeight` 為 0，`FitAddon.fit()` 會算出無意義的 rows/cols，而 `:170-181` 的 `ResizeObserver` 會把它當成一次真的尺寸變更並 `sendResize()` 送給 PTY——**CLI 的版面會被切 tab 這個動作弄壞**。

新增 `fitSafely()` 並在三處使用（observer callback、`socket.onopen`、tab 啟動時）：

```ts
function fitSafely(): void {
  const el = hostElement;
  if (!el || el.clientWidth === 0 || el.clientHeight === 0) return;  // 隱藏中：不量、不送
  fit?.fit();
}
```

`sendResize()` 同樣要在 `terminal.rows`/`cols` 為 0 或 1 時直接 return。

### 2.4 對外 API 變更

`useTerminalSession` 的回傳值新增：

- `fit(): void` — 呼叫 `fitSafely()` 後若尺寸有變則 `sendResize()`。`WT-03` 在切回 CLI tab 時使用。
- `focus(): void` — 轉呼 `terminal?.focus()`。

### 2.5 測試（`frontend/src/composables/useTerminalSession.test.ts`）

現有測試檔已存在，新增四例：

1. `mount(a)` → `mount(b)`：xterm 的 element 最終在 `b` 底下，且 `Terminal` 建構子只被呼叫一次。
2. 容器 `clientWidth = 0` 時，observer 觸發不會呼叫 `fit()`、也不會送出 `terminal.resize`。
3. 容器恢復尺寸後 `fit()` 會送出一次 `terminal.resize`，且相同尺寸不重複送（`lastSize` 去重仍有效）。
4. `dispose()` 之後 `mount()` 不建立任何東西。

---

## WT-03：中央區 Tab 化（`CLI` / `[filename]`）

### 3.1 新元件 `frontend/src/components/session/WorkspaceTabs.vue`

純呈現元件，不持有業務狀態：

```ts
defineProps<{
  tabs: { id: string; label: string; title?: string; closable?: boolean }[];
  active: string;
}>();
defineEmits<{ select: [id: string]; close: [id: string] }>();
```

無障礙契約（style.md §15/§17，WCAG AA）：

- 容器 `role="tablist"`，每個 tab `role="tab"` + `aria-selected` + `aria-controls`，panel `role="tabpanel"` + `aria-labelledby`。
- **整個 tablist 只有一個 tab stop**：選中的 tab `tabindex="0"`，其餘 `-1`；`←`/`→` 移動並啟動、`Home`/`End` 跳首尾（與 `FileTree` 的單一 tab stop 模式一致，見 `FileTree.vue` 檔頭）。
- 選中狀態不得只靠顏色：加底線 + `font-weight`。
- 關閉鈕是 tab 內的獨立 `<button>`，`aria-label="關閉 <basename>"`。

### 3.2 `SessionWorkspaceView.vue` 的組裝

```ts
const activeTab = ref<"cli" | "preview">("cli");
const previewLabel = computed(() => previewPath.value?.split("/").pop() ?? "");
const tabs = computed(() => [
  { id: "cli", label: "CLI" },
  ...(previewPath.value
    ? [{ id: "preview", label: previewLabel.value, title: previewPath.value, closable: true }]
    : []),
]);
```

行為規則：

| 事件 | 行為 |
|---|---|
| `FileTree` `@open` | 設定 `previewPath`，**並切到 preview tab**（沿用同一個 tab，D2） |
| 已在 preview tab 時再開另一個檔案 | 只換 `previewPath`；`PreviewPane` 的 `watch(() => props.relPath)`（`PreviewPane.vue:42-52`）會呼叫 `preview.openFile(next)`，`useMonacoModel` 以 LRU(8) 管理 model 並在切 session 時全數 dispose（見其檔頭）——**model 生命週期已經正確，本 ticket 不需要動它** |
| 關閉 preview tab | `previewPath = null`，切回 `cli` |
| `FileTree` `@clear`（切 session／失去權限） | `previewPath = null`，切回 `cli` |
| 切到 `cli` | `await nextTick()` → `terminal.fit()` → `terminal.focus()` |

### 3.3 Panel 的掛載策略（D4）

```vue
<div class="center">
  <WorkspaceTabs :tabs="tabs" :active="activeTab" @select="activeTab = $event" @close="closePreview" />

  <!-- CLI：永遠掛載，只隱藏。切走時 socket 與 buffer 都保持，切回來沒有 gap。 -->
  <section class="pane" role="tabpanel" aria-labelledby="tab-cli" v-show="activeTab === 'cli'">
    <div ref="host" class="terminal-host" aria-label="Interactive CLI terminal" />
  </section>

  <!-- 預覽：有檔案才掛載（Monaco 是大包，defineAsyncComponent 已在 :22-24），
       關閉即 unmount 以釋放 editor。 -->
  <section v-if="previewPath" class="pane" role="tabpanel" aria-labelledby="tab-preview"
           v-show="activeTab === 'preview'">
    <PreviewPane :session-id="filesSessionId" :rel-path="previewPath" />
  </section>
</div>
```

`.center` 的 `data-split` 屬性與 `:343-345` 的 `grid-template-rows: … 45%` 規則全部刪除，改為 `grid-template-rows: auto 1fr`（tab bar + panel）。`.preview-pane` 的 `.close` 按鈕（`:217-225`、`:352-359`）由 tab 的關閉鈕取代。

**注意 `PreviewPane` 用 `v-if` 是刻意的**：它的 editor host 在元件內部已經是「永遠掛載、以 `hidden` 切換」（`PreviewPane.vue:7-8, 116-122`），所以 Monaco 只會在元件生命週期內建立一次；而整個 pane unmount 時 `useMonacoModel` 的 scope dispose 會收掉 editor 與所有 model。這與 CLI 的處理不同，因為 CLI unmount 會斷掉一條活的 WebSocket，預覽 unmount 不會。

### 3.4 測試

**Vitest — `frontend/src/components/session/WorkspaceTabs.test.ts`**
- 只有一個 tab stop；`←`/`→`/`Home`/`End` 正確移動並發出 `select`。
- `aria-selected`/`aria-controls`/`aria-labelledby` 三者一致。
- `closable` 為假時不渲染關閉鈕；為真時關閉鈕發出 `close`。

**Vitest — `SessionWorkspaceView` 層**
- 無 `previewPath` 時只有一個 tab；`@open` 後出現第二個且 `active` 變成 preview。
- `@open` 另一個檔案不會新增第三個 tab（D2）。
- 切回 `cli` 會呼叫 `terminal.fit()` 與 `terminal.focus()`（以 spy 驗證，這是 `WT-02` 新增 API 的使用點）。

**Playwright — `frontend/tests/e2e/session.spec.ts`**（沿用既有的 `E2E_FULL_STACK` 與 online-node skip 機制）
1. 建立 session → 看到 `FAKECLI_READY` → 從檔案樹開一個檔案 → 出現 `[filename]` tab 且 Monaco 可見。
2. 切回 `CLI` → `.xterm-rows` **仍含 `FAKECLI_READY`**（證明沒有被 unmount 重建），且 `[data-status="connected"]` 仍在（證明同一條 socket）。
3. 關閉預覽 tab → tab 消失、`CLI` 選中。
4. 反覆切換 5 次後，在 CLI 打一個指令仍有回應（證明 PTY 尺寸沒被隱藏容器污染 → 若 §2.3 沒做，這一步會出現錯行或無回應）。

### 3.5 驗收

- 中央區任一 tab 選中時，該 panel 佔滿整個中央區高度；沒有任何殘留的 45% 規則。
- 切 tab 不產生新的 WebSocket 連線（以 Playwright 的 `page.on("websocket")` 計數斷言）。
- `grep -n "data-split" frontend/src` 無結果。
