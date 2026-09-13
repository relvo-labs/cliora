"use strict";

const sessions = [
  {
    id: "sess-web-7f2a",
    name: "web / Claude",
    node: "lab-tpe",
    runtime: "Claude",
    workspace: "~/workspace/web",
    status: "執行中",
    tone: "success",
    note: "剛剛使用 · 主 CLI 可重新附接",
  },
  {
    id: "sess-api-31bc",
    name: "api / Codex",
    node: "lab-tpe",
    runtime: "Codex",
    workspace: "~/workspace/api",
    status: "執行中",
    tone: "success",
    note: "12 分鐘前 · Viewer 正在查看",
  },
  {
    id: "sess-docs-a901",
    name: "docs / Claude",
    node: "build-02",
    runtime: "Claude",
    workspace: "~/workspace/docs",
    status: "已結束",
    tone: "danger",
    note: "昨天 · exit 0",
  },
];

const fixtureOptions = [
  ["normal", "正常"],
  ["empty", "空資料夾"],
  ["forbidden", "403 權限拒絕"],
  ["failure", "暫時載入失敗"],
  ["unsupported", "不支援：二進位／圖片"],
  ["too-large", "檔案過大"],
  ["ended", "工作階段已結束"],
  ["partial-results", "部分搜尋：結果上限"],
  ["partial-depth", "部分搜尋：深度上限"],
  ["partial-scanned", "部分搜尋：掃描上限"],
  ["partial-timeout", "部分搜尋：逾時"],
];

const fileTree = {
  ".": [
    ["src", "directory", "—"],
    ["docs", "directory", "—"],
    ["assets", "directory", "—"],
    ["fixtures", "directory", "—"],
    ["README.md", "text", "5.8 KB"],
    ["package.json", "code", "1.4 KB"],
    ["vite.config.ts", "code", "0.9 KB"],
    ["tsconfig.json", "code", "0.7 KB"],
    ["CHANGELOG.md", "text", "8.2 KB"],
    ["build.log", "text", "18 KB"],
    ["huge-report.txt", "too-large", "3.7 MiB"],
    ["archive.zip", "binary", "420 KB"],
    ["notes-01.md", "text", "2.1 KB"],
    ["notes-02.md", "text", "2.2 KB"],
    ["notes-03.md", "text", "2.3 KB"],
    ["notes-04.md", "text", "2.4 KB"],
    ["notes-05.md", "text", "2.5 KB"],
    ["notes-06.md", "text", "2.6 KB"],
  ],
  src: [
    ["components", "directory", "—"],
    ["main.ts", "code", "2.2 KB"],
    ["app.ts", "code", "7.4 KB"],
    ["router.ts", "code", "4.1 KB"],
    ["state.ts", "code", "6.3 KB"],
    ["types.ts", "code", "3.0 KB"],
  ],
  "src/components": [
    ["SessionList.vue", "code", "8.4 KB"],
    ["FilePanel.vue", "code", "9.8 KB"],
    ["PreviewPane.vue", "code", "6.1 KB"],
  ],
  docs: [
    ["mobile-guide.md", "text", "12 KB"],
    ["terminal-contract.md", "text", "9.1 KB"],
    ["workspace-guide.md", "text", "7.2 KB"],
  ],
  assets: [
    ["architecture.svg", "binary", "42 KB"],
    ["diagram.png", "image", "188 KB"],
  ],
  fixtures: [
    ["empty", "directory", "—"],
    ["report-alpha.md", "text", "2.0 KB"],
    ["report-beta.md", "text", "2.3 KB"],
    ["report-gamma.md", "text", "2.7 KB"],
  ],
  "fixtures/empty": [],
};

const allFiles = Object.entries(fileTree).flatMap(([dir, entries]) =>
  entries
    .filter((entry) => entry[1] !== "directory")
    .map(([name, type, size]) => ({
      name,
      type,
      size,
      path: dir === "." ? name : `${dir}/${name}`,
    })),
);

const state = {
  screen: "sessions",
  sessionId: null,
  pane: "terminal",
  fixture: "normal",
  dir: ".",
  query: "",
  filesScroll: 0,
  previewPath: null,
  previewType: null,
  previewSize: null,
  previewScroll: new Map(),
  returnFocusId: null,
  recoveryNote: "",
  generation: 0,
};

const view = document.querySelector("#view");
const announcer = document.querySelector("#announcer");

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function currentSession() {
  return sessions.find((session) => session.id === state.sessionId) ?? null;
}

function announce(message) {
  announcer.textContent = "";
  window.setTimeout(() => {
    announcer.textContent = message;
  }, 0);
}

function clearWorkspaceState() {
  state.generation += 1;
  state.pane = "terminal";
  state.fixture = "normal";
  state.dir = ".";
  state.query = "";
  state.filesScroll = 0;
  state.previewPath = null;
  state.previewType = null;
  state.previewSize = null;
  state.previewScroll.clear();
  state.returnFocusId = null;
  state.recoveryNote = "";
}

function goSessions() {
  saveVisibleScroll();
  clearWorkspaceState();
  state.sessionId = null;
  state.screen = "sessions";
  render({ focus: "#sessions-heading" });
}

function selectSession(sessionId) {
  clearWorkspaceState();
  state.sessionId = sessionId;
  state.screen = "detail";
  const session = currentSession();
  if (session?.tone === "danger") state.fixture = "ended";
  render({ focus: "#work-heading" });
  announce(`已開啟 exact session ${sessionId}`);
}

function render(options = {}) {
  if (state.screen === "sessions") view.innerHTML = sessionsMarkup();
  if (state.screen === "detail") view.innerHTML = detailMarkup();
  if (state.screen === "preview") view.innerHTML = previewMarkup();

  queueMicrotask(() => {
    if (state.screen === "detail" && state.pane === "files") {
      const region = document.querySelector("#file-region");
      if (region) region.scrollTop = state.filesScroll;
    }
    if (state.screen === "preview" && state.previewPath) {
      const code = document.querySelector("#code-viewer");
      if (code) code.scrollTop = state.previewScroll.get(state.previewPath) ?? 0;
    }
    if (options.focus) document.querySelector(options.focus)?.focus({ preventScroll: true });
  });
}

function sessionsMarkup() {
  return `
    <section class="screen sessions-screen" aria-labelledby="sessions-heading">
      <div class="screen-title">
        <p class="eyebrow">Pocket Workbench · Session first</p>
        <h1 id="sessions-heading" tabindex="-1">回到工作現場</h1>
        <p>選擇正在進行的工作階段，再進入終端或檔案。</p>
      </div>
      <div class="section-heading"><span>工作階段</span><span>${sessions.length} 個合成項目</span></div>
      <div class="session-list" aria-label="合成工作階段清單">
        ${sessions
          .map(
            (session) => `
          <button class="session-card" type="button" data-session="${session.id}" aria-label="開啟 ${escapeHtml(session.name)}，${session.status}">
            <span>
              <strong>${escapeHtml(session.name)}</strong>
              <small>${escapeHtml(session.node)} · ${escapeHtml(session.workspace)}</small>
              <small>${escapeHtml(session.note)}</small>
            </span>
            <span class="badge ${session.tone === "danger" ? "danger" : ""}">${session.status}</span>
          </button>`,
          )
          .join("")}
      </div>
    </section>`;
}

function contextMarkup(session) {
  const shownStatus = state.fixture === "ended" ? "已結束（合成）" : session.status;
  return `
    <div class="context-grid" aria-label="目前工作階段脈絡">
      <div class="context-item"><span>Session</span><strong title="${session.id}">${session.id}</strong></div>
      <div class="context-item"><span>Node</span><strong>${escapeHtml(session.node)}</strong></div>
      <div class="context-item"><span>Runtime</span><strong>${escapeHtml(session.runtime)}</strong></div>
      <div class="context-item"><span>Workspace</span><strong title="${escapeHtml(session.workspace)}">${escapeHtml(session.workspace)}</strong></div>
    </div>
    <span class="visually-hidden">狀態：${shownStatus}</span>`;
}

function fixtureMarkup() {
  return `
    <div class="fixture-row">
      <label for="fixture-select">合成資料情境</label>
      <select id="fixture-select" aria-describedby="fixture-help">
        ${fixtureOptions.map(([value, label]) => `<option value="${value}"${state.fixture === value ? " selected" : ""}>${label}</option>`).join("")}
      </select>
      <span id="fixture-help" class="visually-hidden">只切換本機記憶體中的明確標示 fixture，不呼叫服務。</span>
    </div>`;
}

function detailMarkup() {
  const session = currentSession();
  if (!session) return sessionsMarkup();
  return `
    <section class="screen work-screen" aria-labelledby="work-heading">
      <header class="work-header">
        <button class="back-button" type="button" data-action="sessions">返回工作階段</button>
        <div class="work-heading">
          <p class="eyebrow">Exact selected session</p>
          <h1 id="work-heading" tabindex="-1">${escapeHtml(session.name)}</h1>
        </div>
        ${contextMarkup(session)}
      </header>
      <div class="pane-tabs" role="tablist" aria-label="工作階段工具">
        <button id="tab-terminal" class="pane-tab" type="button" role="tab" aria-selected="${state.pane === "terminal"}" aria-controls="active-pane" data-pane="terminal">Terminal</button>
        <button id="tab-files" class="pane-tab" type="button" role="tab" aria-selected="${state.pane === "files"}" aria-controls="active-pane" data-pane="files">Files</button>
      </div>
      ${fixtureMarkup()}
      <div id="active-pane" class="pane-body" role="tabpanel" aria-labelledby="tab-${state.pane}">
        ${state.pane === "terminal" ? terminalMarkup(session) : filesMarkup(session)}
      </div>
    </section>`;
}

function terminalMarkup(session) {
  if (state.fixture === "ended") {
    return noticeMarkup(
      "工作階段已結束",
      "這個合成 session 已結束，終端不可重新連線。離開主 CLI 畫面不是 stop；此狀態只由 fixture 控制。",
      "warning",
    );
  }
  return `
    <section class="terminal-pane" aria-label="明亮終端提案">
      <div class="terminal-bar"><span>${escapeHtml(session.runtime)} · ${escapeHtml(session.id)}</span><span>合成 stdout · 唯讀</span></div>
      <pre class="terminal-output" tabindex="0"><span class="dim">[fixture] 保留畫面，不是即時輸出</span>

<span class="ansi-green">${escapeHtml(session.runtime)} CLI</span>
workspace  <span class="ansi-blue">${escapeHtml(session.workspace)}</span>
node       ${escapeHtml(session.node)}

────────────────────────────────

<span class="ansi-magenta">status</span>     waiting for user input
<span class="dim">Cliora 不解析工具、審批或 agent 語意。</span>

&gt; <span class="cursor"> </span></pre>
      <div class="terminal-foot">主 CLI：關閉／返回只 detach，session 繼續。系統 terminal child shell：關閉或離頁會終止；本原型不提供 shell 控制。</div>
    </section>`;
}

function noticeMarkup(title, body, tone = "", button = "") {
  return `<section class="notice ${tone}" role="${tone === "danger" ? "alert" : "status"}"><h2>${title}</h2><p>${body}</p>${button}</section>`;
}

function partialFixture() {
  if (!state.fixture.startsWith("partial-")) return null;
  const reason = state.fixture.replace("partial-", "");
  const copy = {
    results: ["已達結果上限，僅顯示前面的相符項目。", "results", 200],
    depth: ["已達搜尋深度上限，較深的目錄未掃描。", "depth", 148],
    scanned: ["已達掃描檔案數上限，結果不完整。", "scanned", 50000],
    timeout: ["搜尋逾時，僅顯示已找到的結果。", "timeout", 12744],
  }[reason];
  return { message: copy[0], reason: copy[1], scanned: copy[2] };
}

function filesMarkup(session) {
  if (state.fixture === "forbidden") {
    return noticeMarkup(
      "403 · 無法存取目前工作區",
      `伺服器仍須驗證 file.browse；本 fixture 不會提出檔案請求，也不顯示 ${escapeHtml(session.workspace)} 的舊內容。切換 session 會清除路徑、搜尋、預覽與捲動。`,
      "danger",
    );
  }
  if (state.fixture === "failure") {
    return noticeMarkup(
      "暫時載入失敗",
      "合成 relay 暫時失敗；尚未取得任何目錄內容。重試只把本機 fixture 切回正常，不宣稱已連線服務。",
      "danger",
      '<button type="button" data-action="retry-fixture">重試合成載入</button>',
    );
  }
  if (state.fixture === "ended") {
    return noticeMarkup(
      "Session 已結束，檔案瀏覽不可用",
      "已結束的 session 沒有 daemon-side workspace 可供瀏覽；不提供無效重試，也不保留先前 session 內容。",
      "warning",
    );
  }

  const partial = partialFixture();
  const entries = visibleEntries(partial);
  const empty = state.fixture === "empty" || entries.length === 0;
  return `
    <section class="files-pane" aria-label="目前 session 工作區檔案">
      <form id="file-search" class="search-form" role="search">
        <input id="file-search-input" type="search" value="${escapeHtml(state.query)}" aria-label="以檔名搜尋整個目前 session 工作區" placeholder="搜尋整個工作區的檔名" autocomplete="off" />
        <button type="submit">搜尋</button>
      </form>
      <p class="scope-note">範圍：<strong>${escapeHtml(session.workspace)}</strong> 整個工作區 · 檔名 substring（非全文、非目前資料夾限定）</p>
      ${breadcrumbsMarkup(session)}
      ${state.recoveryNote ? `<p class="notice" role="status">${escapeHtml(state.recoveryNote)}</p>` : ""}
      ${partial ? `<p class="notice warning partial-note" role="status" data-stop-reason="${partial.reason}"><strong>部分結果 · ${partial.reason}</strong><br>${partial.message}<br>已掃描 ${partial.scanned} 項。</p>` : ""}
      <div id="file-region" class="file-region" tabindex="0" aria-label="檔案清單" data-dir="${escapeHtml(state.dir)}">
        ${empty ? emptyMarkup() : fileListMarkup(entries)}
      </div>
    </section>`;
}

function visibleEntries(partial) {
  if (state.fixture === "empty") return [];
  if (partial) return allFiles.filter((file) => file.name.includes("report")).slice(0, 3);
  if (state.query) {
    const query = state.query.toLocaleLowerCase("zh-Hant");
    return allFiles.filter((file) => file.name.toLocaleLowerCase("zh-Hant").includes(query));
  }
  return (fileTree[state.dir] ?? []).map(([name, type, size]) => ({
    name,
    type,
    size,
    path: state.dir === "." ? name : `${state.dir}/${name}`,
  }));
}

function emptyMarkup() {
  if (state.query) {
    return `<div class="empty-state" role="status"><h2>沒有符合的檔名</h2><p>整個目前 session 工作區沒有包含「${escapeHtml(state.query)}」的檔名。這不同於空資料夾。</p></div>`;
  }
  return '<div class="empty-state" role="status"><h2>這個資料夾是空的</h2><p>空資料夾 fixture：目錄已成功載入，但沒有項目。</p></div>';
}

function fileListMarkup(entries) {
  return `<ul class="file-list">${entries
    .map((entry, index) => {
      const id = `file-${index}-${entry.path.replaceAll(/[^a-zA-Z0-9_-]/g, "-")}`;
      const kind = entry.type === "directory" ? "DIR" : entry.type === "code" ? "CODE" : entry.type === "text" ? "TEXT" : entry.type === "image" ? "IMAGE" : entry.type === "too-large" ? "LARGE" : "BIN";
      return `<li><button id="${id}" class="file-row" type="button" data-path="${escapeHtml(entry.path)}" data-type="${entry.type}" data-size="${entry.size}" data-file-focus="${id}">
        <span class="file-kind">${kind}</span>
        <span><span class="file-name">${escapeHtml(entry.name)}</span>${state.query ? `<span class="file-path">${escapeHtml(entry.path)}</span>` : ""}</span>
        <span class="file-meta">${entry.type === "directory" ? "開啟" : escapeHtml(entry.size)}</span>
      </button></li>`;
    })
    .join("")}</ul>`;
}

function breadcrumbsMarkup(session) {
  const parts = state.dir === "." ? [] : state.dir.split("/");
  const crumbs = [
    `<button type="button" data-breadcrumb=".">${escapeHtml(session.workspace.split("/").pop())}</button>`,
  ];
  parts.forEach((part, index) => {
    crumbs.push('<span class="crumb-separator" aria-hidden="true">/</span>');
    crumbs.push(`<button type="button" data-breadcrumb="${parts.slice(0, index + 1).join("/")}">${escapeHtml(part)}</button>`);
  });
  return `<nav class="file-toolbar" aria-label="工作區相對路徑">
    <button class="up-button" type="button" data-action="up" ${state.dir === "." ? "disabled" : ""}>上一層</button>
    ${crumbs.join("")}
  </nav>`;
}

function openPath(path, type, size, focusId) {
  if (type === "directory") {
    state.dir = path;
    state.query = "";
    state.filesScroll = 0;
    render({ focus: "#file-region" });
    announce(`已開啟資料夾 ${path}`);
    return;
  }
  saveVisibleScroll();
  state.previewPath = path;
  state.previewType = type;
  state.previewSize = size;
  state.returnFocusId = focusId;
  state.screen = "preview";
  render({ focus: "#preview-heading" });
}

function saveVisibleScroll() {
  const files = document.querySelector("#file-region");
  if (files) state.filesScroll = files.scrollTop;
  const preview = document.querySelector("#code-viewer");
  if (preview && state.previewPath) state.previewScroll.set(state.previewPath, preview.scrollTop);
}

function closePreview() {
  saveVisibleScroll();
  const focusId = state.returnFocusId;
  state.screen = "detail";
  state.pane = "files";
  state.previewPath = null;
  state.previewType = null;
  state.previewSize = null;
  render({ focus: focusId ? `#${CSS.escape(focusId)}` : "#file-region" });
}

function previewMarkup() {
  const session = currentSession();
  if (!session || !state.previewPath) return detailMarkup();
  const denial = previewDenial();
  return `
    <section class="screen preview-screen" aria-labelledby="preview-heading">
      <header class="preview-head">
        <button type="button" data-action="close-preview">返回檔案</button>
        <div class="preview-title">
          <h1 id="preview-heading" tabindex="-1">${escapeHtml(state.previewPath.split("/").pop())}</h1>
          <p>${escapeHtml(session.workspace)}/${escapeHtml(state.previewPath)}</p>
        </div>
        <span class="readonly-label">唯讀</span>
      </header>
      <p class="preview-contract">TEXT／CODE 全幅閱讀 fixture · 對齊現有 PreviewPane/readFileContent 邊界；不是編輯器。</p>
      ${denial ?? codeMarkup(state.previewPath)}
    </section>`;
}

function previewDenial() {
  const type = state.previewType;
  if (type === "too-large" || state.fixture === "too-large") {
    return `<div class="preview-denial">${noticeMarkup("檔案過大，拒絕預覽", `大小 ${escapeHtml(state.previewSize ?? "3.7 MiB")}，超過目前 2 MiB 預覽上限。未讀取內容；下載未建置且不在本原型。`, "warning")}</div>`;
  }
  if (["binary", "image"].includes(type) || state.fixture === "unsupported") {
    const isImage = type === "image" || state.previewPath.endsWith(".png");
    return `<div class="preview-denial">${noticeMarkup("不支援此檔案的預覽", `${isImage ? "圖片" : "二進位"}檔案 ${escapeHtml(state.previewPath)} 只顯示中繼資訊（${escapeHtml(state.previewSize ?? "未知大小")}）。現有 PreviewPane 不是圖片檢視器；不載入、不解碼、不顯示內容。`, "warning")}</div>`;
  }
  return null;
}

function codeMarkup(path) {
  const lines = [];
  const codeLike = /\.(ts|vue|json)$/.test(path);
  for (let index = 1; index <= 180; index += 1) {
    if (index === 1) lines.push(codeLike ? `// ${path} — synthetic read-only fixture` : `# ${path} — 合成唯讀內容`);
    else if (index % 17 === 0) lines.push(codeLike ? `export const fixtureLine${index} = "whole-workspace filename search";` : `## 第 ${index} 行：手機預覽捲動與返回位置驗證`);
    else lines.push(codeLike ? `const row${index} = { session: "${state.sessionId}", readOnly: true };` : `第 ${index} 行　這是用來驗證實際非零捲動位置的文字內容。`);
  }
  return `<div id="code-viewer" class="code-viewer" tabindex="0" aria-label="${escapeHtml(path)} 唯讀文字預覽"><ol class="code-lines">${lines.map((line) => `<li>${escapeHtml(line)}</li>`).join("")}</ol></div>`;
}

function setPane(pane) {
  saveVisibleScroll();
  state.pane = pane;
  state.screen = "detail";
  render({ focus: `#tab-${pane}` });
}

function setFixture(value) {
  state.fixture = value;
  state.recoveryNote = "";
  state.filesScroll = 0;
  state.query = value.startsWith("partial-") ? "report" : "";
  state.dir = value === "empty" ? "fixtures/empty" : ".";
  state.previewPath = null;
  state.previewType = null;
  state.previewSize = null;
  if (value === "unsupported") {
    state.pane = "files";
    openPath("assets/diagram.png", "image", "188 KB", null);
    return;
  }
  if (value === "too-large") {
    state.pane = "files";
    openPath("huge-report.txt", "too-large", "3.7 MiB", null);
    return;
  }
  render({ focus: "#fixture-select" });
  announce(`已切換合成資料情境：${fixtureOptions.find(([key]) => key === value)?.[1] ?? value}`);
}

document.addEventListener("click", (event) => {
  const target = event.target.closest("button");
  if (!target) return;
  if (target.dataset.session) {
    selectSession(target.dataset.session);
    return;
  }
  if (target.dataset.pane) {
    setPane(target.dataset.pane);
    return;
  }
  if (target.dataset.path) {
    openPath(target.dataset.path, target.dataset.type, target.dataset.size, target.dataset.fileFocus);
    return;
  }
  if (target.dataset.breadcrumb) {
    state.dir = target.dataset.breadcrumb;
    state.query = "";
    state.filesScroll = 0;
    render({ focus: "#file-region" });
    return;
  }
  switch (target.dataset.action) {
    case "sessions":
      goSessions();
      break;
    case "up": {
      if (state.dir === ".") break;
      const parts = state.dir.split("/");
      parts.pop();
      state.dir = parts.join("/") || ".";
      state.query = "";
      state.filesScroll = 0;
      render({ focus: "#file-region" });
      break;
    }
    case "close-preview":
      closePreview();
      break;
    case "retry-fixture":
      state.fixture = "normal";
      state.recoveryNote = "已重試：合成資料已恢復；未連線任何服務。";
      state.dir = ".";
      render({ focus: "#fixture-select" });
      break;
    default:
      break;
  }
});

document.addEventListener("change", (event) => {
  if (event.target.matches("#fixture-select")) setFixture(event.target.value);
});

document.addEventListener("submit", (event) => {
  if (!event.target.matches("#file-search")) return;
  event.preventDefault();
  const input = event.target.querySelector("#file-search-input");
  state.query = input.value.trim();
  state.filesScroll = 0;
  render({ focus: "#file-search-input" });
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && state.screen === "preview") {
    event.preventDefault();
    closePreview();
    return;
  }
  if (event.key === "Escape" && event.target.matches("#file-search-input")) {
    event.preventDefault();
    state.query = "";
    state.filesScroll = 0;
    render({ focus: "#file-search-input" });
  }
  if (event.key === "ArrowRight" && event.target.matches('[role="tab"]')) {
    event.preventDefault();
    setPane(event.target.dataset.pane === "terminal" ? "files" : "terminal");
  }
  if (event.key === "ArrowLeft" && event.target.matches('[role="tab"]')) {
    event.preventDefault();
    setPane(event.target.dataset.pane === "files" ? "terminal" : "files");
  }
});

window.addEventListener("resize", () => {
  document.documentElement.style.setProperty("--visual-viewport-height", `${window.visualViewport?.height ?? window.innerHeight}px`);
});

render();
