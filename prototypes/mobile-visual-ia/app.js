"use strict";
/* Cliora #75 mobile visual / IA prototype.
 *
 * Everything here is synthetic and in memory: no API, PTY, WebSocket, storage
 * or remote asset. One information architecture, three visual variants
 * (switched by `data-variant` on <html>, i.e. CSS only). The "activity" view
 * is a HYPOTHESIS that depends on #73 structured events and applies only to a
 * future managed session; existing tmux sessions stay native-terminal only
 * (#72, user-confirmed 2026-09-27).
 *
 * No colour literal may appear in this file (test_prototype.py checks).
 */

const $ = (sel, root = document) => root.querySelector(sel);
const esc = (v) =>
  String(v).replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );

/* ---------- Icons: simple outline strokes drawn for this prototype ---------- */
const PATHS = {
  back: '<path d="M15 5l-7 7 7 7"/>',
  more: '<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>',
  menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
  search: '<circle cx="11" cy="11" r="6"/><path d="M20 20l-4.5-4.5"/>',
  folder: '<path d="M3 7h6l2 2h10v10H3z"/>',
  file: '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4"/>',
  chevron: '<path d="M9 5l7 7-7 7"/>',
  alert: '<path d="M12 4l9 16H3z"/><path d="M12 10v4M12 17v.5"/>',
  terminal: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M7 10l3 2-3 2M12 15h5"/>',
  image: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 16l5-5 4 4 3-3 6 6"/>',
  close: '<path d="M6 6l12 12M18 6L6 18"/>',
  refresh: '<path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 5v6h-6"/>',
  edit: '<path d="M4 20h4L19 9l-4-4L4 16z"/>',
  eye: '<path d="M2 12s4-6 10-6 10 6 10 6-4 6-10 6S2 12 2 12z"/><circle cx="12" cy="12" r="2.5"/>',
  user: '<circle cx="12" cy="8" r="3.5"/><path d="M5 20c1-4 4-5.5 7-5.5s6 1.5 7 5.5"/>',
  note: '<path d="M4 5h16v11H9l-5 4z"/>',
  check: '<path d="M5 12l4 4 10-10"/>',
  lock: '<rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
  wrap: '<path d="M4 7h16M4 12h12a3 3 0 0 1 0 6h-4M14 16l-2 2 2 2M4 17h5"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  minus: '<path d="M5 12h14"/>',
  gap: '<path d="M4 8h16M4 16h16"/><path d="M9 12h6" stroke-dasharray="2 2"/>',
};
const icon = (name, label) =>
  `<svg class="icon" viewBox="0 0 24 24" ${label ? `role="img" aria-label="${esc(label)}"` : 'aria-hidden="true"'}>${PATHS[name]}</svg>`;

/* ---------- Synthetic fixtures (clearly fake names, reserved domains) ---------- */
const NODES = {
  a: { id: "node-demo-a", name: "demo-node-a", status: "線上", privileged: false },
  b: { id: "node-demo-b", name: "demo-node-b", status: "線上", privileged: true },
  c: { id: "node-demo-c", name: "demo-node-c", status: "離線", privileged: false },
};
const SESSIONS = [
  { id: "sess-7f2a-demo", name: "demo-web-refactor", runtime: "claude", node: "a", status: "running", workspace: "/srv/demo/web-refactor", last: "3 分鐘前", kind: "native", canShell: true, canImage: true },
  { id: "sess-31bc-demo", name: "demo-api-tests", runtime: "codex", node: "b", status: "running", workspace: "/srv/demo/api-tests", last: "12 分鐘前", kind: "native", sandboxBypass: true, canShell: true, canImage: false },
  { id: "sess-a9d0-demo", name: "demo-docs-managed", runtime: "claude", node: "a", status: "running", workspace: "/srv/demo/docs", last: "剛剛", kind: "structured", canShell: false, canImage: false },
  { id: "sess-50e1-demo", name: "demo-docs-pass", runtime: "claude", node: "a", status: "exited", exitCode: 0, workspace: "/srv/demo/docs-pass", last: "昨天 18:40", kind: "native" },
  { id: "sess-c4f8-demo", name: "demo-migration-check", runtime: "codex", node: "b", status: "failed", workspace: "/srv/demo/migration", last: "昨天 11:05", kind: "native", sandboxBypass: true },
];
const RUNTIME = { claude: "Claude", codex: "Codex" };
const SESSION_STATUS = {
  running: ["執行中", "success"],
  starting: ["啟動中", "info"],
  exited: ["已結束", "neutral"],
  failed: ["失敗", "error"],
};

const FILES = {
  ".": [
    { n: "src", dir: true },
    { n: "docs", dir: true },
    { n: "logs", dir: true },
    { n: "README.md", size: "2.1 KB", mod: "今天 09:12" },
    { n: "package.json", size: "812 B", mod: "9/26" },
  ],
  src: [
    { n: "components", dir: true },
    { n: "router.ts", size: "3.4 KB", mod: "3 分鐘前" },
    { n: "app.ts", size: "1.8 KB", mod: "9/26" },
  ],
  "src/components": [{ n: "demo-list.ts", size: "1.1 KB", mod: "9/25" }],
  docs: [{ n: "router.md", size: "940 B", mod: "今天 09:40" }],
  logs: [{ n: "build-demo.log", size: "5.0 MB", mod: "今天 08:02", tooLarge: true }],
};

const T = (cls, text) => `<span class="${cls}">${esc(text)}</span>`;
// The CLI's own prompt box. In the product these are box-drawing characters the
// CLI redraws to the PTY's column count; here CSS draws them to the current width.
const INPUT_BOX = `<span class="rule rule-box fg-dim" data-input-box><span class="fg-input">&gt;</span></span>`;
const TERMINAL = {
  claude: [
    `<span class="rule rule-title fg-dim">── demo agent cli</span>`,
    "",
    T("bold", "> 把 router 的測試補齊"),
    "",
    `${T("fg-cyan", "●")} Read  src/router.ts`,
    `${T("fg-cyan", "●")} Edit  src/router.ts  ${T("fg-green", "+12")} ${T("fg-red", "-3")}`,
    `${T("fg-cyan", "●")} Bash  npm test -- router`,
    `  ${T("fg-green", "✓")} 18 passed  ${T("fg-dim", "(1.2s)")}`,
    "",
    "已補上三個邊界測試；需要我也更新文件嗎？",
    "",
    INPUT_BOX,
    T("fg-dim", "  ? for shortcuts"),
  ],
  codex: [
    T("fg-magenta", "demo codex cli") + T("fg-dim", "  · workspace /srv/demo/api-tests"),
    "",
    T("bold", "user"),
    "跑一次 API 測試，列出失敗的項目",
    "",
    `${T("fg-blue", "exec")} npm run test:api`,
    `  ${T("fg-green", "✓")} 41 passed`,
    `  ${T("fg-red", "✗")} 2 failed  ${T("fg-dim", "demo/orders.spec.ts")}`,
    "",
    T("bold", "codex"),
    "兩個失敗都來自同一個合成 fixture 的日期欄位。",
    "",
    T("fg-input", "▌"),
  ],
  shell: [
    `${T("fg-green", "demo@demo-node-b")}:${T("fg-blue", "~")}$ uptime`,
    " 09:41:07 up 3 days,  load average: 0.21, 0.18, 0.12",
    `${T("fg-green", "demo@demo-node-b")}:${T("fg-blue", "~")}$ ${T("fg-input", "▌")}`,
  ],
};

const CODE = [
  "// Synthetic demo file for the #75 prototype.",
  'import { createRouter } from "./demo-router";',
  "",
  "export interface DemoRoute {",
  "  path: string;",
  "  name: string;",
  "}",
  "",
  "export const routes: DemoRoute[] = [",
  '  { path: "/", name: "home" },',
  '  { path: "/sessions", name: "sessions" },',
  '  { path: "/sessions/:id", name: "session-workspace" },',
  "];",
  "",
  "export function resolve(path: string): DemoRoute | undefined {",
  "  return routes.find((route) => route.path === path);",
  "}",
  ...Array.from({ length: 40 }, (_, i) => `// demo line ${i + 18}: a longer comment that shows how wrapping behaves on a narrow phone screen`),
];

// Structured activity — HYPOTHESIS. Every label below would have to come from
// provider-issued structured events (#72/#73), never from PTY bytes.
function activityEvents(kind) {
  const base = [
    { k: "turn", what: "第 1 回合 · 09:02" },
    { k: "user", what: "把 router 的測試補齊", when: "09:02" },
    { k: "tool", ic: "eye", what: "讀取", mono: "src/router.ts", when: "09:02", st: ["完成", "success"] },
    { k: "tool", ic: "edit", what: "編輯", mono: "src/router.ts", detail: "+12 −3", when: "09:03", st: ["完成", "success"] },
    { k: "tool", ic: "terminal", what: "執行", mono: "npm test -- router", detail: "18 passed · 1.2s", when: "09:03", st: ["完成", "success"] },
    { k: "agent", what: "已補上三個邊界測試；需要我也更新文件嗎？", when: "09:04" },
    { k: "turn", what: "第 2 回合 · 09:10" },
    { k: "user", what: "好，也更新 docs/router.md", when: "09:10" },
  ];
  const long = [];
  for (let i = 0; i < 9; i += 1) {
    long.push({ k: "tool", ic: i % 3 === 0 ? "eye" : i % 3 === 1 ? "edit" : "terminal", what: i % 3 === 0 ? "讀取" : i % 3 === 1 ? "編輯" : "執行", mono: i % 3 === 2 ? `npm run lint -- demo-${i}` : `docs/section-${i}.md`, detail: i % 3 === 1 ? "+4 −1" : undefined, when: `09:${String(11 + i).padStart(2, "0")}`, st: ["完成", "success"] });
  }
  const tail = [
    { k: "tool", ic: "edit", what: "編輯", mono: "docs/router.md", when: "09:21", st: ["進行中", "info"] },
  ];
  if (kind === "await") {
    tail.push({ k: "await", what: "CLI 正在等待確認：執行 npm run build", when: "09:22" });
  }
  if (kind === "gap") {
    tail.unshift({ k: "gap", what: "事件流中斷：09:14–09:19 之間的活動未收到", detail: "不補寫、不推測；完整輸出請看終端機。", when: "09:19" });
  }
  return [...base, ...long, ...tail];
}

/* ---------- Scenarios ---------- */
const SCENARIOS = [
  ["list", "清單", { screen: "list" }],
  ["list-empty", "清單（空）", { screen: "list", empty: true }],
  ["create", "建立 Session", { screen: "list", sheet: "create" }],
  ["terminal", "詳情 · 終端機（有控制權）", { session: 0, tab: "cli" }],
  ["menu", "詳情 · Session 選單", { session: 0, tab: "cli", sheet: "menu" }],
  ["viewer", "詳情 · Viewer（可接管）", { session: 0, role: "viewer", canTakeover: true }],
  ["viewer-locked", "詳情 · Viewer（不可接管）", { session: 0, role: "viewer", canTakeover: false }],
  ["posture", "詳情 · 可提權＋沙箱停用", { session: 1 }],
  ["shell", "詳情 · 系統終端機", { session: 1, shellOpen: true, tab: "shell" }],
  ["reconnecting", "詳情 · 重新連線中", { session: 0, conn: "reconnecting" }],
  ["disconnected", "詳情 · 已斷線", { session: 0, conn: "disconnected" }],
  ["gap", "詳情 · 輸出截斷（gap）", { session: 0, conn: "gap" }],
  ["exited", "詳情 · 已結束", { session: 3 }],
  ["load-error", "詳情 · 載入錯誤", { session: 0, load: "error" }],
  ["forbidden", "詳情 · 無權限（403）", { session: 0, load: "forbidden" }],
  ["activity", "活動 · 長活動與工具（假設）", { session: 2, tab: "activity" }],
  ["await", "活動 · 等待原生確認（假設）", { session: 2, tab: "activity", events: "await" }],
  ["events-gap", "活動 · 事件流中斷（假設）", { session: 2, tab: "activity", events: "gap" }],
  ["unsupported", "活動 · runtime 不支援 → 原生終端", { session: 2, tab: "activity", events: "unsupported" }],
  ["files", "檔案 · 清單", { session: 0, tab: "files" }],
  ["preview", "檔案 · 預覽", { session: 0, tab: "files", dir: "src", preview: "src/router.ts" }],
  ["preview-denied", "檔案 · 預覽拒絕（過大）", { session: 0, tab: "files", dir: "logs", preview: "logs/build-demo.log" }],
  ["keyboard", "鍵盤開啟（模擬）", { session: 0, tab: "cli", keyboard: true }],
];

function freshState() {
  return {
    screen: "list",
    empty: false,
    sheet: null,
    session: 0,
    tab: "cli",
    role: "writer",
    canTakeover: true,
    conn: "connected",
    load: "ok",
    events: "normal",
    shellOpen: false,
    dir: ".",
    preview: null,
    wrap: true,
    query: "",
    fileQuery: "",
    runtimeFilter: "all",
    keyboard: false,
    fontSize: 14,
    createNode: "a",
    note: "",
  };
}
let state = freshState();
let scenarioId = "list";
let returnFocus = null;

function applyScenario(id) {
  const found = SCENARIOS.find((s) => s[0] === id) ?? SCENARIOS[0];
  scenarioId = found[0];
  state = { ...freshState(), screen: "detail", ...found[2] };
  const s = SESSIONS[state.session];
  if (state.tab === "cli" && s.kind === "structured" && !found[2].tab) state.tab = "activity";
  document.documentElement.style.setProperty("--kb", state.keyboard ? "320px" : "0px");
  render();
}

/* ---------- Derived state ---------- */
function current() {
  return SESSIONS[state.session];
}
function sessionTabs(s) {
  const tabs = [];
  if (s.kind === "structured") tabs.push(["activity", "活動"]);
  tabs.push(["cli", "終端機"], ["files", "檔案"]);
  if (state.shellOpen) tabs.push(["shell", "系統 shell"]);
  return tabs;
}
function connection(s) {
  if (s.status === "exited" || s.status === "failed") return ["程序已結束", "neutral", null];
  return {
    connected: ["已連線", "success", null],
    reconnecting: ["重新連線中（第 2 次）", "warning", "alert"],
    disconnected: ["已斷線", "error", "alert"],
    gap: ["輸出截斷", "warning", "alert"],
  }[state.conn];
}
function control(s) {
  if (s.status !== "running") return ["唯讀（已結束）", false];
  if (state.conn === "disconnected" || state.conn === "reconnecting") return ["輸入已停用", false];
  return state.role === "writer" ? ["你有控制權", true] : ["唯讀 · 他人持有", false];
}
function nextAction(s) {
  if (s.status !== "running") return null;
  if (state.conn === "disconnected") return ["reconnect", "重新連線", "refresh"];
  if (state.role === "viewer" && state.canTakeover && state.conn === "connected") return ["takeover", "取得控制權", "lock"];
  return null;
}
function tone(s) {
  if (s.status === "failed" || state.conn === "disconnected") return "error";
  if (state.conn === "reconnecting" || state.conn === "gap") return "warning";
  return "";
}

/* ---------- Markup ---------- */
function stMarkup(label, t, ic) {
  return `<span class="st" data-tone="${t}">${ic ? icon(ic) : ""}${esc(label)}</span>`;
}

function listMarkup() {
  const rows = state.empty ? [] : SESSIONS;
  const q = state.query.trim().toLowerCase();
  const filtered = rows.filter(
    (s) =>
      (state.runtimeFilter === "all" || s.runtime === state.runtimeFilter) &&
      (!q || `${s.name} ${s.workspace}`.toLowerCase().includes(q)),
  );
  const body = !rows.length
    ? `<div class="empty"><h2>尚未建立 Session</h2><p class="hint">建立第一個 Session 後，會在這裡繼續工作。</p><button class="btn primary" type="button" data-action="open-create">${icon("plus")}新建 Session</button></div>`
    : !filtered.length
      ? `<div class="empty"><h2>沒有符合條件的 Session</h2><p class="hint">調整搜尋字串，或清除 Runtime 篩選。</p><button class="btn" type="button" data-action="clear-filters">清除搜尋與篩選</button></div>`
      : `<ul class="sessions" aria-label="Sessions">${filtered
          .map((s) => {
            const [label, t] = SESSION_STATUS[s.status];
            const kind = s.kind === "structured" ? " · 活動＋終端（假設）" : "";
            return `<li><button type="button" class="srow" data-action="open-session" data-id="${s.id}" aria-label="開啟 ${esc(s.name)}，${label}">
              <span class="name">${esc(s.name)}</span>${stMarkup(label, t, t === "error" ? "alert" : "")}
              <span class="meta">${RUNTIME[s.runtime]} · ${esc(NODES[s.node].name)} · ${esc(s.last)}<span class="kind">${kind}</span></span>
              <span class="path mono"><bdi>${esc(s.workspace)}</bdi></span>
            </button></li>`;
          })
          .join("")}</ul>`;
  const filters = rows.length
    ? `<div class="filters">
        <label class="search"><span class="visually-hidden">搜尋名稱或工作目錄</span><input id="session-search" class="input" type="search" placeholder="搜尋名稱或工作目錄" value="${esc(state.query)}" data-input="query" /></label>
        <label class="runtime"><span class="visually-hidden">Runtime 篩選</span><select class="select" data-input="runtimeFilter" aria-label="Runtime 篩選">
          <option value="all"${state.runtimeFilter === "all" ? " selected" : ""}>全部</option>
          <option value="claude"${state.runtimeFilter === "claude" ? " selected" : ""}>Claude</option>
          <option value="codex"${state.runtimeFilter === "codex" ? " selected" : ""}>Codex</option>
        </select></label>
      </div>`
    : "";
  return `<div class="screen" data-screen="list">
    <header class="lbar">
      <button class="icon-btn" type="button" data-action="open-nav" aria-label="開啟主導覽">${icon("menu")}</button>
      <span class="wordmark">Cliora</span><span class="spacer"></span>
      <button class="icon-btn" type="button" data-action="noop" aria-label="帳號：Demo User（Developer）"><span class="avatar" aria-hidden="true">D</span></button>
    </header>
    <div class="scroll">
      <div class="list-head"><h1>Sessions${rows.length ? `<span class="count">${filtered.length} / ${rows.length}</span>` : ""}</h1>
        ${rows.length ? `<button class="btn primary" type="button" data-action="open-create">${icon("plus")}新建</button>` : ""}
      </div>
      ${filters}
      ${body}
    </div>
  </div>`;
}

function detailTop(s) {
  const node = NODES[s.node];
  const [statusLabel, statusTone] = SESSION_STATUS[s.status];
  const [connLabel, connTone, connIcon] = connection(s);
  const [ctlLabel, mine] = control(s);
  const action = nextAction(s);
  const lineTone = tone(s);
  const posture = [];
  if (node.privileged) posture.push(["可提權", "此 Node 可經 sudo 取得 root"]);
  if (s.sandboxBypass) posture.push(["沙箱停用", "Codex 沙箱已停用（Node 設定）"]);
  const tabs = sessionTabs(s);
  return `<div class="detail-top">
    <header class="sbar">
      <button class="icon-btn" type="button" data-action="back-list" aria-label="回到 Sessions">${icon("back")}</button>
      <div class="titles"><h1 id="session-title" title="${esc(s.name)}">${esc(s.name)}</h1>
        <span class="sub" title="${esc(`${RUNTIME[s.runtime]} · ${node.name} · ${s.workspace.split("/").pop()}`)}">${RUNTIME[s.runtime]} · ${esc(node.name)} · <bdi>${esc(s.workspace.split("/").pop())}</bdi></span></div>
      <button class="icon-btn" type="button" data-action="open-menu" aria-haspopup="dialog" aria-label="Session 選單與資訊">${icon("more")}</button>
    </header>
    <div class="state-line" role="status" aria-label="Session 狀態" ${lineTone ? `data-tone="${lineTone}"` : ""}>
      <span class="cell"><span class="key">Session</span>${stMarkup(statusLabel, statusTone, statusTone === "error" ? "alert" : "")}</span>
      <span class="cell"><span class="key">連線</span>${stMarkup(connLabel, connTone, connIcon)}</span>
      <span class="cell"><span class="key">控制權</span><span class="control" ${mine ? "data-mine" : ""}>${esc(ctlLabel)}</span></span>
      ${action ? `<span class="action" data-kind="${action[0]}"><button class="btn ${action[0] === "takeover" ? "primary" : ""}" type="button" data-action="${action[0]}">${icon(action[2])}${action[1]}</button></span>` : ""}
    </div>
    ${posture.length ? `<div class="posture-line" role="note" aria-label="Node 執行姿態">${posture.map(([short, long]) => `<span class="cell">${icon("alert")}<span><strong>${esc(short)}</strong><span class="long">：${esc(long)}</span></span></span>`).join("")}</div>` : ""}
    <nav class="tabs" role="tablist" aria-label="Session 工作區">
      ${tabs
        .map(
          ([id, label]) =>
            `<button class="tab" type="button" role="tab" id="tab-${id}" aria-controls="pane-${id}" aria-selected="${state.tab === id}" tabindex="${state.tab === id ? 0 : -1}" data-action="tab" data-tab="${id}" ${id === "shell" ? "data-shell" : ""}>${id === "shell" ? icon("alert") : ""}${label}</button>`,
        )
        .join("")}
      <span class="end">
        ${state.shellOpen && state.tab === "shell" ? `<button class="icon-btn" type="button" data-action="close-shell" aria-label="關閉並終止系統 shell">${icon("close")}</button>` : ""}
        ${s.canImage && state.role === "writer" && s.status === "running" && state.tab === "cli" ? `<button class="icon-btn" type="button" data-action="attach" aria-label="附加圖片到 CLI">${icon("image")}</button>` : ""}
      </span>
    </nav>
  </div>`;
}

function terminalPane(s, which) {
  let lines = which === "shell" ? TERMINAL.shell : TERMINAL[s.runtime];
  const viewer = which !== "shell" && s.status === "running" && state.role === "viewer";
  // A Viewer is never offered something that looks like a place to type: the
  // synthetic output for this state ends before the CLI's prompt (see README).
  if (viewer) {
    const cut = lines.findIndex((l) => l === INPUT_BOX || l.includes("fg-input"));
    if (cut >= 0) lines = lines.slice(0, cut);
  }
  const bands = [];
  if (which === "shell") {
    bands.push(["warning", "alert", "系統終端機：直接操作此 Node 的 shell，不受 workspace 路徑限制；此 Node 可經 sudo 取得 root。關閉即終止這個 shell；主 CLI 不受影響。"]);
  } else if (s.status === "exited") {
    bands.push(["neutral", "lock", `Session 已結束（exit ${s.exitCode ?? "?"}）。以下是最後輸出，不能再輸入。`]);
  } else if (s.status === "failed") {
    bands.push(["error", "alert", "Session 啟動失敗。以下是最後輸出，不能再輸入。"]);
  } else if (state.conn === "reconnecting") {
    bands.push(["neutral", "lock", "輸出已停止更新（最後更新 09:41）。正在以新的連線憑證重新連線；期間輸入停用，不會排隊送出。"]);
  } else if (state.conn === "disconnected") {
    bands.push(["neutral", "lock", "已斷線。畫面是斷線前的輸出，可能已過時；Session 仍在 Node 上執行。"]);
  } else if (state.conn === "gap") {
    bands.push(["warning", "gap", "只顯示最新輸出片段；先前歷史已截斷，不會補寫。"]);
  }
  return `<section class="pane" id="pane-${which}" role="tabpanel" aria-labelledby="tab-${which}">
    ${bands.map(([t, ic, text]) => `<div class="band" data-tone="${t}">${icon(ic)}<p>${esc(text)}</p></div>`).join("")}
    <pre class="terminal" tabindex="0" aria-label="${which === "shell" ? "系統終端機（合成輸出）" : "主 CLI 終端機（合成輸出）"}" ${which === "shell" ? "data-shell" : ""} style="--term-font:${state.fontSize}px">${lines.map((l) => (l.startsWith('<span class="rule') ? l : `<span class="tl">${l || " "}</span>`)).join("")}</pre>
    ${viewer ? viewerFoot() : ""}
  </section>`;
}

// Where the input would be. C shows the take-over action here as a full-width
// block (the state line then carries only the words); A/B keep it in the state
// line, so CSS hides this button for them. Same DOM for every variant.
function viewerFoot() {
  if (state.canTakeover && state.conn === "connected") {
    return `<div class="term-foot"><button class="btn primary takeover-foot" type="button" data-action="takeover">${icon("lock")}取得控制權</button></div>`;
  }
  return `<div class="term-foot"><p class="hint">${icon("lock")}唯讀：控制權由他人持有，這個帳號不能接管。</p></div>`;
}

function activityPane() {
  if (state.events === "unsupported") {
    return `<section class="pane" id="pane-activity" role="tabpanel" aria-labelledby="tab-activity">
      <div class="fallback"><h2>此 Session 只支援原生終端機</h2>
        <p>這個 runtime 沒有宣告可信的結構化事件，所以不顯示活動整理。Cliora 不會從終端輸出推測誰說了什麼。</p>
        <button class="btn primary" type="button" data-action="tab" data-tab="cli">${icon("terminal")}開啟終端機</button></div>
    </section>`;
  }
  const events = activityEvents(state.events);
  return `<section class="pane" id="pane-activity" role="tabpanel" aria-labelledby="tab-activity">
    <div class="band" data-tone="info">${icon("alert")}<p>示意：活動整理需要 #73 的官方結構化事件，只適用未來的受管 Session；既有 tmux Session 維持原生終端。</p></div>
    <div class="scroll"><ol class="activity" aria-label="活動（合成）">${events
      .map((e) => {
        if (e.k === "turn") return `<li class="ev" data-kind="turn">${esc(e.what)}</li>`;
        const glyph = { user: "user", agent: "note", tool: e.ic, gap: "gap", await: "alert" }[e.k];
        const who = { user: "你", agent: "Agent", tool: "工具", gap: "中斷", await: "等待確認" }[e.k];
        return `<li class="ev" data-kind="${e.k}"><span class="glyph">${icon(glyph, who)}</span>
          <span class="what">${esc(e.what)}${e.mono ? ` <span class="mono">${esc(e.mono)}</span>` : ""}</span>
          <span class="when">${e.st ? stMarkup(e.st[0], e.st[1]) : esc(e.when ?? "")}</span>
          ${e.detail ? `<span class="detail">${esc(e.detail)}</span>` : ""}
          ${e.k === "await" ? `<span class="detail">確認只能在原生終端機進行；這裡不提供批准按鈕。</span><button class="btn primary" type="button" data-action="tab" data-tab="cli">${icon("terminal")}到終端機處理</button>` : ""}</li>`;
      })
      .join("")}</ol></div>
    <div class="activity-foot"><span>回覆與確認在終端機進行</span><button class="btn" type="button" data-action="tab" data-tab="cli">${icon("terminal")}終端機</button></div>
  </section>`;
}

function filesPane(s) {
  if (s.status !== "running") {
    return `<section class="pane" id="pane-files" role="tabpanel" aria-labelledby="tab-files"><div class="empty"><h2>Session 已結束，檔案瀏覽不再可用</h2><p class="hint">已結束的 Session 在 Node 上沒有可瀏覽的工作區。</p></div></section>`;
  }
  const parts = state.dir === "." ? [] : state.dir.split("/");
  const crumbs = [["", s.workspace.split("/").pop()], ...parts.map((p, i) => [parts.slice(0, i + 1).join("/"), p])];
  const q = state.fileQuery.trim().toLowerCase();
  let entries;
  let searching = false;
  if (q) {
    searching = true;
    entries = [];
    for (const [dir, list] of Object.entries(FILES)) {
      for (const e of list) {
        if (!e.dir && e.n.toLowerCase().includes(q)) entries.push({ ...e, path: dir === "." ? e.n : `${dir}/${e.n}` });
      }
    }
  } else {
    entries = (FILES[state.dir] ?? []).map((e) => ({ ...e, path: state.dir === "." ? e.n : `${state.dir}/${e.n}` }));
  }
  return `<section class="pane" id="pane-files" role="tabpanel" aria-labelledby="tab-files">
    <div class="files-top">
      <label><span class="visually-hidden">搜尋檔名</span><input id="file-search" class="input" type="search" placeholder="搜尋檔名" value="${esc(state.fileQuery)}" data-input="fileQuery" /></label>
      <p class="hint scope-note">搜尋範圍：整個工作區的檔名，不含檔案內容。</p>
    </div>
    ${searching ? `<p class="hint" style="padding:0 var(--pad-x)">${entries.length} 筆結果 · 已掃描 42 個項目（合成）</p>` : `<nav class="crumbs" aria-label="目前位置">${crumbs
      .map(([path, label], i) => `${i ? `<span class="crumb-sep" aria-hidden="true">/</span>` : ""}<button class="crumb" type="button" data-action="dir" data-dir="${path || "."}" ${i === crumbs.length - 1 ? 'aria-current="location"' : ""}>${esc(label)}</button>`)
      .join("")}</nav>`}
    <div class="scroll" id="file-scroll"><ul class="flist">${entries.length ? entries
      .map((e) => `<li><button class="frow" type="button" id="f-${esc(e.path.replace(/[^a-z0-9]/gi, "-"))}" data-action="${e.dir ? "dir" : "preview"}" data-${e.dir ? "dir" : "path"}="${esc(e.path)}">${icon(e.dir ? "folder" : "file")}<span class="fname">${esc(searching ? e.path : e.n)}</span><span class="fmeta">${e.dir ? icon("chevron") : esc(`${e.size} · ${e.mod}`)}</span></button></li>`)
      .join("") : `<li class="empty"><h2>${searching ? "沒有符合的檔名" : "這個資料夾是空的"}</h2></li>`}</ul></div>
  </section>`;
}

function previewScreen(s) {
  const path = state.preview;
  const entry = Object.entries(FILES).flatMap(([dir, list]) => list.map((e) => ({ ...e, path: dir === "." ? e.n : `${dir}/${e.n}` }))).find((e) => e.path === path);
  const name = path.split("/").pop();
  const body = entry?.tooLarge
    ? `<div class="denial"><span class="st" data-tone="warning">${icon("alert")}無法預覽</span><h2>檔案過大</h2><p>${esc(entry.size)}，預覽上限 2 MiB；不會讀取完整內容。</p><p class="hint">下一步：在終端機用 <span class="mono">tail</span> 或 <span class="mono">less</span> 查看。</p><button class="btn" type="button" data-action="preview-to-cli">${icon("terminal")}到終端機</button></div>`
    : `<pre class="code" id="code-view" tabindex="0" aria-label="${esc(name)} 唯讀內容（合成）" ${state.wrap ? "data-wrap" : ""}>${CODE.map((l, i) => `<span class="line"><span class="ln">${i + 1}</span><span class="lc">${esc(l) || " "}</span></span>`).join("")}</pre>`;
  return `<div class="screen" data-screen="preview">
    <header class="pbar">
      <button class="icon-btn" type="button" data-action="close-preview" aria-label="回到檔案清單">${icon("back")}</button>
      <div class="titles"><h1><bdi>${esc(name)}</bdi></h1><span class="sub">唯讀 · ${esc(s.name)} · ${entry?.tooLarge ? esc(entry.size) : `${esc(entry?.size ?? "")} · UTF-8`}</span></div>
      ${entry?.tooLarge ? "" : `<button class="icon-btn" type="button" data-action="toggle-wrap" aria-pressed="${state.wrap}" aria-label="自動換行">${icon("wrap")}</button>
      <button class="icon-btn" type="button" data-action="open-preview-menu" aria-haspopup="dialog" aria-label="預覽選單">${icon("more")}</button>`}
    </header>
    ${statusOnlyIfAbnormal(s)}
    <section class="pane">${body}</section>
  </div>`;
}

// The preview is full screen, but a broken connection must not disappear
// behind it: the state line comes back whenever it is not the calm case.
function statusOnlyIfAbnormal(s) {
  if (!tone(s)) return "";
  const [label, t, ic] = connection(s);
  return `<div class="state-line" role="status" data-tone="${tone(s)}"><span class="cell"><span class="key">連線</span>${stMarkup(label, t, ic)}</span></div>`;
}

function veilMarkup(s) {
  const forbidden = state.load === "forbidden";
  return `<div class="screen" data-screen="veil">
    <header class="sbar"><button class="icon-btn" type="button" data-action="back-list" aria-label="回到 Sessions">${icon("back")}</button>
      <div class="titles"><h1>${forbidden ? "無法開啟這個 Session" : "Session 暫時無法載入"}</h1><span class="sub mono">${esc(s.id)}</span></div></header>
    <div class="veil" role="alert">
      <span class="st" data-tone="error">${icon("alert")}${forbidden ? "沒有權限" : "載入失敗"}</span>
      <h2>${forbidden ? "你的角色沒有檢視這個 Session 的權限" : "Central 暫時沒有回應（合成錯誤）"}</h2>
      <p>${forbidden ? "伺服器拒絕了這個請求；隱藏入口不等於授權。需要存取時請聯絡管理員。" : "原因：伺服器回報了此用戶端尚不認識的錯誤代碼。下一步：稍後重試，或回報下面的 request_id。"}</p>
      <p class="rid mono">request_id: req-demo-${forbidden ? "403" : "500"}</p>
      <div style="display:flex;gap:8px;flex-wrap:wrap">${forbidden ? "" : `<button class="btn primary" type="button" data-action="retry-load">${icon("refresh")}重試</button>`}<button class="btn" type="button" data-action="back-list">回到 Sessions</button></div>
    </div>
  </div>`;
}

function detailMarkup() {
  const s = current();
  if (state.load !== "ok") return veilMarkup(s);
  if (state.preview) return previewScreen(s);
  let pane;
  if (state.tab === "activity") pane = activityPane();
  else if (state.tab === "files") pane = filesPane(s);
  else if (state.tab === "shell") pane = terminalPane(s, "shell");
  else pane = terminalPane(s, "cli");
  return `<div class="screen" data-screen="detail" data-tab="${state.tab}">${detailTop(s)}${pane}</div>`;
}

function sheetMarkup() {
  if (!state.sheet) return "";
  const s = current();
  let inner = "";
  if (state.sheet === "menu") {
    const node = NODES[s.node];
    inner = `<div class="sheet" role="dialog" aria-modal="true" aria-labelledby="sheet-title">
      <div class="sheet-head"><h2 id="sheet-title">${esc(s.name)}</h2><button class="icon-btn" type="button" data-action="close-sheet" aria-label="關閉">${icon("close")}</button></div>
      <div class="sheet-body">
        <dl class="kv"><dt>Session ID</dt><dd class="mono">${esc(s.id)}</dd><dt>Node</dt><dd>${esc(node.name)} · ${esc(node.status)}</dd><dt>Runtime</dt><dd>${RUNTIME[s.runtime]}</dd><dt>工作目錄</dt><dd class="mono"><bdi>${esc(s.workspace)}</bdi></dd></dl>
        <ul class="menu">
          ${s.canShell && s.status === "running" ? `<li><button type="button" data-action="open-shell">${icon("terminal")}開啟系統終端機（此 Node 的 shell）</button></li>` : ""}
          <li><div class="sep"></div></li>
          <li><div class="menu-row"><span class="label">終端機字級 <span class="mono">${state.fontSize}px</span></span>
            <button class="icon-btn" type="button" data-action="font-down" aria-label="縮小終端機字級">${icon("minus")}</button><button class="icon-btn" type="button" data-action="font-up" aria-label="放大終端機字級">${icon("plus")}</button></div></li>
          <li><div class="sep"></div></li>
          <li><button type="button" data-danger data-action="terminate">${icon("alert")}終止 Session…</button></li>
        </ul>
        ${state.note ? `<p class="hint" role="status">${esc(state.note)}</p>` : ""}
      </div></div>`;
  } else if (state.sheet === "create") {
    const node = NODES[state.createNode];
    inner = `<div class="sheet" data-full role="dialog" aria-modal="true" aria-labelledby="sheet-title">
      <div class="sheet-head"><h2 id="sheet-title">新建 Session</h2><button class="icon-btn" type="button" data-action="close-sheet" aria-label="關閉">${icon("close")}</button></div>
      <div class="sheet-body">
        <label class="field"><span>Node</span><select class="select" data-input="createNode">
          ${Object.entries(NODES).map(([k, n]) => `<option value="${k}" ${k === state.createNode ? "selected" : ""} ${n.status === "離線" ? "disabled" : ""}>${esc(n.name)} · ${esc(n.status)}${n.privileged ? " · 可提權" : ""}</option>`).join("")}
        </select></label>
        ${node.privileged ? `<div class="band" data-tone="warning" style="padding-inline:12px;border-radius:var(--radius)">${icon("alert")}<p>這台 Node 可經 sudo 取得 root；Codex 在此 Node 的沙箱已停用。建立前先確認。</p></div>` : ""}
        <fieldset class="field" style="border:0;padding:0;margin:0"><legend style="font-size:var(--fs-meta);font-weight:var(--fw-strong);margin-bottom:4px">Runtime</legend>
          <div class="seg"><label><input type="radio" name="rt" value="claude" checked />Claude</label><label><input type="radio" name="rt" value="codex" />Codex</label></div></fieldset>
        <label class="field"><span>工作目錄</span><input class="input mono" type="text" placeholder="/srv/demo/…" /></label>
        <div class="field"><span>最近使用</span><ul class="recent"><li><button type="button" data-action="noop"><bdi>/srv/demo/web-refactor</bdi></button></li><li><button type="button" data-action="noop"><bdi>/srv/demo/api-tests</bdi></button></li></ul></div>
        <label class="field"><span>名稱（選填）</span><input class="input" type="text" placeholder="例如 demo-refactor" /></label>
        ${state.note ? `<p class="hint" role="status">${esc(state.note)}</p>` : ""}
      </div>
      <div class="sheet-foot"><button class="btn" type="button" data-action="close-sheet">取消</button><button class="btn primary" type="button" data-action="create-submit">建立</button></div></div>`;
  } else if (state.sheet === "nav") {
    inner = `<div class="sheet" role="dialog" aria-modal="true" aria-labelledby="sheet-title">
      <div class="sheet-head"><h2 id="sheet-title">Cliora</h2><button class="icon-btn" type="button" data-action="close-sheet" aria-label="關閉">${icon("close")}</button></div>
      <ul class="menu"><li><button type="button" aria-current="page" data-action="close-sheet">${icon("terminal")}Sessions</button></li>
        <li><button type="button" data-action="not-in-proto">概況（原型未含）</button></li><li><button type="button" data-action="not-in-proto">Nodes（原型未含）</button></li><li><button type="button" data-action="not-in-proto">偏好設定（原型未含）</button></li></ul>
      ${state.note ? `<p class="hint" role="status" style="padding:0 var(--pad-x) 12px">${esc(state.note)}</p>` : ""}</div>`;
  } else if (state.sheet === "preview-menu") {
    inner = `<div class="sheet" role="dialog" aria-modal="true" aria-labelledby="sheet-title">
      <div class="sheet-head"><h2 id="sheet-title">預覽</h2><button class="icon-btn" type="button" data-action="close-sheet" aria-label="關閉">${icon("close")}</button></div>
      <ul class="menu"><li><button type="button" data-action="not-in-proto">${icon("search")}在檔案中尋找</button></li><li><button type="button" data-action="not-in-proto">複製全部</button></li><li><button type="button" data-action="not-in-proto">重新整理</button></li><li><button type="button" data-action="not-in-proto">下載</button></li></ul>
      ${state.note ? `<p class="hint" role="status" style="padding:0 var(--pad-x) 12px">${esc(state.note)}</p>` : ""}</div>`;
  }
  return `<div class="scrim" data-action="close-sheet"></div>${inner}`;
}

/* ---------- Render & focus ---------- */
function render(focusSelector) {
  const app = $("#app");
  app.innerHTML =
    (state.screen === "list" ? listMarkup() : detailMarkup()) +
    sheetMarkup() +
    (state.keyboard ? '<div class="kb-sim" aria-hidden="true">模擬軟體鍵盤區域（原型）</div>' : "");
  if (focusSelector) {
    const el = $(focusSelector, app);
    if (el) el.focus();
  } else if (state.sheet) {
    const first = $(".sheet button, .sheet select, .sheet input", app);
    if (first) first.focus();
  }
  $("#scenario-select").value = scenarioId;
}
function announce(text) {
  const el = $("#announcer");
  el.textContent = "";
  window.setTimeout(() => (el.textContent = text), 30);
}
function openSheet(name, from) {
  returnFocus = from ?? document.activeElement;
  state.sheet = name;
  state.note = "";
  render();
}
function closeSheet() {
  state.sheet = null;
  state.note = "";
  const back = returnFocus;
  returnFocus = null;
  render();
  if (back && back.dataset && back.dataset.action) {
    const again = $(`[data-action="${back.dataset.action}"]`);
    if (again) again.focus();
  }
}

/* ---------- Events ---------- */
document.addEventListener("click", (event) => {
  const el = event.target.closest("[data-action]");
  if (!el) return;
  const a = el.dataset.action;
  if (a === "open-session") {
    const idx = SESSIONS.findIndex((s) => s.id === el.dataset.id);
    state = { ...freshState(), screen: "detail", session: idx, tab: SESSIONS[idx].kind === "structured" ? "activity" : "cli" };
    scenarioId = "terminal";
    render("#session-title");
    $("#session-title")?.setAttribute("tabindex", "-1");
    $("#session-title")?.focus();
  } else if (a === "back-list") {
    state = { ...freshState(), screen: "list" };
    scenarioId = "list";
    render();
  } else if (a === "tab") {
    state.tab = el.dataset.tab;
    state.sheet = null;
    render(`#tab-${state.tab}`);
  } else if (a === "open-menu") openSheet("menu", el);
  else if (a === "open-nav") openSheet("nav", el);
  else if (a === "open-create") openSheet("create", el);
  else if (a === "open-preview-menu") openSheet("preview-menu", el);
  else if (a === "close-sheet") closeSheet();
  else if (a === "open-shell") {
    state.sheet = null;
    state.shellOpen = true;
    state.tab = "shell";
    render("#tab-shell");
    announce("已開啟系統終端機：此 Node 的 shell");
  } else if (a === "close-shell") {
    state.shellOpen = false;
    state.tab = "cli";
    render("#tab-cli");
    announce("系統 shell 已關閉並終止；主 CLI 仍在執行");
  } else if (a === "takeover") {
    state.role = "writer";
    render("#tab-cli");
    announce("已取得控制權（合成）");
  } else if (a === "reconnect") {
    state.conn = "reconnecting";
    render();
    announce("正在重新連線（合成，不會真的連線）");
  } else if (a === "retry-load") {
    state.load = "ok";
    render("#session-title");
  } else if (a === "dir") {
    state.dir = el.dataset.dir;
    state.fileQuery = "";
    render(".crumb[aria-current]");
  } else if (a === "preview") {
    state.returnRow = el.id;
    state.preview = el.dataset.path;
    render('[data-action="close-preview"]');
  } else if (a === "close-preview") {
    const row = state.returnRow;
    state.preview = null;
    render(row ? `#${row}` : "#file-search");
  } else if (a === "preview-to-cli") {
    state.preview = null;
    state.tab = "cli";
    render("#tab-cli");
  } else if (a === "toggle-wrap") {
    state.wrap = !state.wrap;
    render('[data-action="toggle-wrap"]');
  } else if (a === "font-up" || a === "font-down") {
    state.fontSize = Math.max(12, Math.min(20, state.fontSize + (a === "font-up" ? 1 : -1)));
    render(`[data-action="${a}"]`);
  } else if (a === "terminate") {
    state.note = "原型不提供終止；正式版會先以對話框點名要終止的 Session。";
    render('[data-action="terminate"]');
  } else if (a === "create-submit") {
    state.note = "原型：不會建立 Session，也不會送出任何請求。";
    render('[data-action="create-submit"]');
  } else if (a === "not-in-proto") {
    state.note = "原型未含此功能。";
    render(`[data-action="not-in-proto"]`);
  } else if (a === "attach") {
    announce("原型：附加圖片只示意位置，不會選檔或上傳");
  } else if (a === "clear-filters") {
    state.query = "";
    state.runtimeFilter = "all";
    render("#session-search");
  }
});

document.addEventListener("input", (event) => {
  const key = event.target.dataset && event.target.dataset.input;
  if (!key) return;
  state[key] = event.target.value;
  const id = event.target.id;
  const pos = event.target.selectionStart;
  render(id ? `#${id}` : undefined);
  if (id) {
    const again = document.getElementById(id);
    if (again && typeof pos === "number" && again.setSelectionRange) again.setSelectionRange(pos, pos);
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    if (state.sheet) {
      event.preventDefault();
      closeSheet();
    } else if (state.preview) {
      event.preventDefault();
      $('[data-action="close-preview"]')?.click();
    } else if (event.target.id === "file-search" && state.fileQuery) {
      state.fileQuery = "";
      render("#file-search");
    }
    return;
  }
  // Focus stays inside an open sheet.
  if (event.key === "Tab" && state.sheet) {
    const focusables = [...document.querySelectorAll(".sheet button, .sheet select, .sheet input")].filter((el) => !el.disabled);
    if (!focusables.length) return;
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }
  if (event.target.getAttribute && event.target.getAttribute("role") === "tab" && (event.key === "ArrowRight" || event.key === "ArrowLeft")) {
    const tabs = [...document.querySelectorAll('[role="tab"]')];
    const i = tabs.indexOf(event.target);
    const next = tabs[(i + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length];
    event.preventDefault();
    next.click();
  }
});

/* ---------- Boot ---------- */
function boot() {
  const params = new URLSearchParams(location.search);
  const v = params.get("v");
  // C is the chosen direction (product owner, 2026-09-28); A and B stay selectable.
  document.documentElement.dataset.variant = v === "a" || v === "b" || v === "c" ? v : "c";
  if (params.get("shot") === "1") document.documentElement.dataset.shot = "";
  const sel = $("#scenario-select");
  sel.innerHTML = SCENARIOS.map(([id, label]) => `<option value="${id}">${esc(label)}</option>`).join("");
  sel.addEventListener("change", () => applyScenario(sel.value));
  const vs = $("#variant-select");
  vs.value = document.documentElement.dataset.variant;
  vs.addEventListener("change", () => {
    document.documentElement.dataset.variant = vs.value;
    announce(`已切換為變體 ${vs.options[vs.selectedIndex].text}`);
  });
  // A real software keyboard: the visual viewport shrinks, the frame follows.
  if (window.visualViewport) {
    const vv = window.visualViewport;
    const sync = () => {
      if (state.keyboard) return;
      const kb = Math.max(0, Math.round(window.innerHeight - vv.height));
      document.documentElement.style.setProperty("--kb", `${kb}px`);
    };
    vv.addEventListener("resize", sync);
  }
  applyScenario(params.get("s") ?? "list");
  if (!params.get("s")) {
    state.screen = "list";
    render();
  }
}
boot();
