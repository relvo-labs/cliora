/* Cliora V2 前端 prototype — 零依賴，直接開 index.html 即可。
 *
 * 這份 prototype 要讓人「看得到並且點得到」的，是 research/02 裡幾個
 * 光看文字很難判斷對錯的決定：
 *   1. 208px sidebar 在三組導覽下夠不夠（09 §3）
 *   2. 「等待你的回覆」是不是真的最醒目（D24）
 *   3. 拖曳被拒的三種訊息分不分得出來（D17b／D21／DV-05）
 *   4. 三組「進行中」的顏色能不能一眼區分（09 §7）
 *   5. 三種證據 source 的視覺分級（D10）
 *   6. Session Workspace 加了 Task/Plan 之後 Terminal 有沒有變窄（plan/08、plan/09）
 *   7. 產物只有下載、機密沒有顯示值（D29 §4、D22）
 */

// ════════════════════════════════════════════════════════════════════════
// 1. 假資料
// ════════════════════════════════════════════════════════════════════════

const STAGES = [
  { id: 'backlog',      label: '待辦',   wip: null },
  { id: 'blocked',      label: '阻塞',   wip: null },
  { id: 'ready',        label: '就緒',   wip: null },
  { id: 'implementing', label: '進行中', wip: 3 },
  { id: 'verify',       label: '驗證中', wip: 5 },
  { id: 'done',         label: '完成',   wip: null },
];

const RUN_LABEL = {
  queued: '排隊中', running: '執行中', waiting_for_input: '等待你的回覆',
  succeeded: '成功', failed: '失敗', lost: '遺失', cancelled: '已取消',
};
const DELIVERY_LABEL = {
  none: '無交付', artifact: '卡片產物', branch: '分支',
  pull_request: 'PR', existing_pr: '追加至 PR',
};
const SOURCE_LABEL = {
  machine_verified: '機器事實', platform_observed: '平台紀錄', agent_reported: 'Agent 自述',
};

const AGENTS = [
  { id: 'r1', name: 'dev-vm-01', node: 'dev-vm-01', runtime: 'claude',
    labels: ['linux', 'node20'], max: 2, load: 1, online: true, secrets: true,
    projects: ['Cliora Platform', 'Monstrare Kit'], pinned: 1 },
  { id: 'r2', name: 'build-vm-02', node: 'build-vm-02', runtime: 'codex',
    labels: ['linux', 'docker'], max: 3, load: 0, online: true, secrets: true,
    projects: ['Cliora Platform'], pinned: 1 },
  { id: 'r3', name: 'edge-vm-03', node: 'edge-vm-03', runtime: 'claude',
    labels: ['linux'], max: 1, load: 0, online: false, secrets: false,
    projects: ['Monstrare Kit'], pinned: 0 },
];

const TASKS = [
  { ref: 'TASK-101', title: '建立 Project 與 Workspace 綁定', stage: 'done', risk: 'medium',
    epic: 'E1', us: 'US1', delivery: 'pull_request', source: 'repo', owner: 'neil',
    ac: 3, acDone: 3, verified: true, pr: '#412' },
  { ref: 'TASK-102', title: '導覽重整為三組（Projects / Sessions / Infrastructure）', stage: 'done',
    risk: 'low', epic: 'E1', us: 'US1', delivery: 'pull_request', source: 'repo', owner: 'neil',
    ac: 2, acDone: 2, verified: true, pr: '#415' },
  { ref: 'TASK-103', title: '內化流程定義與六車道', stage: 'verify', risk: 'medium',
    epic: 'E1', us: 'US2', delivery: 'pull_request', source: 'repo', agent: 'dev-vm-01',
    run: 'succeeded', ac: 4, acDone: 4, verified: true, pr: '#418' },
  { ref: 'TASK-104', title: '看板拖曳與樂觀鎖', stage: 'implementing', risk: 'medium',
    epic: 'E1', us: 'US2', delivery: 'pull_request', source: 'repo', agent: 'dev-vm-01',
    run: 'running', ac: 3, acDone: 1, verified: false, demo: 'gate' },
  { ref: 'TASK-105', title: 'Runner 註冊與認領協定', stage: 'implementing', risk: 'high',
    epic: 'E2', us: 'US3', delivery: 'pull_request', source: 'repo', agent: 'build-vm-02',
    run: 'waiting_for_input', ac: 5, acDone: 2, verified: false, star: true },
  { ref: 'TASK-106', title: '調查：run log 的儲存體積與保留策略', stage: 'ready', risk: 'low',
    epic: 'E2', us: 'US3', delivery: 'artifact', source: 'repo', demo: 'conflict' },
  { ref: 'TASK-107', title: '機密下放的加密與金鑰管理設計', stage: 'ready', risk: 'high',
    epic: 'E2', us: 'US4', delivery: 'pull_request', source: 'repo',
    assigned: 'build-vm-02', secrets: ['GIT_TOKEN'] },
  { ref: 'TASK-108', title: '隔離工作目錄與配額', stage: 'backlog', risk: 'high',
    epic: 'E2', us: 'US4', delivery: 'pull_request', source: 'repo',
    dependsOn: ['TASK-105'], demo: 'dep' },
  { ref: 'TASK-109', title: 'PR 建立與供應商整合', stage: 'blocked', risk: 'medium',
    epic: 'E2', us: 'US4', delivery: 'pull_request', source: 'repo', dependsOn: ['TASK-107'] },
  { ref: 'TASK-110', title: '撰寫 ADR 0029：run 的兩種輸出', stage: 'ready', risk: 'low',
    epic: 'E2', us: 'US3', delivery: 'artifact', source: 'none' },
];

const EPICS = [
  { id: 'E1', name: '平台基座', stories: [
    { id: 'US1', name: '專案與導覽' }, { id: 'US2', name: '任務看板' }] },
  { id: 'E2', name: 'Agent 執行', stories: [
    { id: 'US3', name: 'Runner 與認領' }, { id: 'US4', name: '隔離與機密' }] },
];

const MESSAGES = [
  { kind: 'system', body: 'build-vm-02 認領了這張卡（run #7）', time: '14:02' },
  { kind: 'agent', name: 'build-vm-02', time: '14:09',
    body: '已讀過 contracts/v1/schemas/ 與 daemon/internal/connection/。租約續租我打算走既有的 WSS 控制通道，不另開連線。' },
  { kind: 'agent', name: 'build-vm-02', time: '14:11', question: true,
    body: '租約逾時要用固定 180 秒，還是依 runner 回報的 max_concurrent 調整？兩者的差別在於一台跑滿的機器會不會被誤判為死亡。' },
  { kind: 'user', name: 'neil', time: '14:26',
    body: '先用固定 180 秒。等 M13 量到真實的 renew 間隔分布再說。' },
  { kind: 'agent', name: 'build-vm-02', time: '14:27',
    body: '收到。已更新執行計畫第 3 步，並附上目前的協定草稿。' },
  { kind: 'agent', name: 'build-vm-02', time: '14:31', question: true,
    body: 'runner 在 poll 時要不要回報目前的磁碟餘量？這會影響 V2.3 的配額判斷要在哪一端做。' },
];

const ARTIFACTS = [
  { name: 'runner-protocol-draft.md', type: 'text/markdown', size: '14 KB', run: '#7', at: '14:27', by: 'build-vm-02', preview: true },
  { name: 'lease-timeout-simulation.png', type: 'image/png', size: '182 KB', run: '#7', at: '14:30', by: 'build-vm-02', img: true },
  { name: 'claim-race-test.html', type: 'text/html', size: '38 KB', run: '#7', at: '14:33', by: 'build-vm-02', html: true },
  { name: 'uncommitted-changes.patch', type: 'text/x-patch', size: '6 KB', run: '#7', at: '14:34', by: '平台', note: '本卡宣告 delivery，但偵測到未提交變更，已自動附為產物' },
];

const PLAN_STEPS = [
  { t: '盤點既有 WSS 控制通道與 heartbeat', s: 'completed' },
  { t: '設計 runner.register / poll 的 envelope', s: 'completed' },
  { t: '租約續租與逾時判定（改為固定 180s）', s: 'in_progress' },
  { t: '原子認領的 SQL 與併發測試', s: 'pending' },
  { t: '撰寫 contract fixtures（含 secrets 誤入的 invalid 案例）', s: 'pending' },
];

const CHECKS = [
  { name: 'Contract fixtures', cmd: 'make contract', code: 0, src: 'machine_verified' },
  { name: 'Daemon 單元測試', cmd: 'go test ./internal/connection/...', code: 0, src: 'machine_verified' },
  { name: 'Central 單元測試', cmd: 'uv run pytest tests/test_runs.py', code: 1, src: 'machine_verified' },
  { name: 'Lint', cmd: 'ruff check app', code: 0, src: 'machine_verified' },
];

const EVIDENCE = [
  { kind: '分支', v: 'cliora/TASK-105-7', src: 'machine_verified' },
  { kind: 'Commit', v: '3f9a1c2', src: 'machine_verified' },
  { kind: '變更檔案', v: '11 個檔案（+412 / −87）', src: 'machine_verified' },
  { kind: '變更檔案（Agent 自述）', v: '9 個檔案', src: 'agent_reported', conflict: true },
  { kind: 'Run 起訖', v: '14:02 → 執行中', src: 'platform_observed' },
  { kind: '已知限制', v: 'lease renew 尚未在網路抖動下測過', src: 'agent_reported' },
];

const OPEN_QUESTIONS = [
  '這個功能要不要支援 GitLab，還是先只做 GitHub？',
  '「指定 agent」的卡片如果那台機器永久下線，要自動退回還是一直等？',
];

const PROPOSALS = [
  { lvl: 'epic', ref: 'E3', title: 'Agent 交付與驗證', checked: true },
  { lvl: 'us', ref: 'US5', title: '交付模式', checked: true },
  { lvl: 'task', ref: 'T-a', title: '實作 delivery: artifact 的 Done Gate', checked: true, delivery: 'pull_request', risk: 'medium', dor: true },
  { lvl: 'task', ref: 'T-b', title: '調查 GitLab MR API 與 GitHub 的差異', checked: true, delivery: 'artifact', risk: 'low', dor: true },
  { lvl: 'task', ref: 'T-c', title: 'PR 內文產生器', checked: false, delivery: 'pull_request', risk: 'low', dor: false, miss: '缺「相關檔案或搜尋入口」與「驗證方法」' },
  { lvl: 'us', ref: 'US6', title: '證據可信度', checked: false },
  { lvl: 'task', ref: 'T-d', title: 'source 三級的伺服器端判定', checked: false, delivery: 'pull_request', risk: 'high', dor: true },
];

const SECRETS = [
  { name: 'GIT_TOKEN', kind: 'git_credential', by: 'neil', used: '2026-08-08 14:02' },
  { name: 'GITHUB_APP_KEY', kind: 'provider_token', by: 'neil', used: '2026-08-07 09:41' },
  { name: 'NPM_TOKEN', kind: 'env', by: 'neil', used: '尚未使用' },
];

// ════════════════════════════════════════════════════════════════════════
// 2. 小工具
// ════════════════════════════════════════════════════════════════════════

const $ = (s, r = document) => r.querySelector(s);
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

function note(html, ref) {
  return `<div class="note">${html}${ref ? ` <span class="ref">— ${esc(ref)}</span>` : ''}</div>`;
}
function toast(title, body, ok) {
  const el = document.createElement('div');
  el.className = 'toast' + (ok ? ' ok' : '');
  el.innerHTML = `<div><b>${esc(title)}</b>${esc(body)}</div>`;
  $('#toasts').appendChild(el);
  setTimeout(() => el.remove(), 6000);
}

const stageBadge = (id) => {
  const s = STAGES.find((x) => x.id === id);
  return `<span class="badge solid" style="background:var(--stage-${id})">${s.label}</span>`;
};
const runBadge = (status, agent) => {
  if (!status) return '';
  const wait = status === 'waiting_for_input';
  const live = status === 'running' || wait;
  const txt = RUN_LABEL[status] + (agent && status === 'running' ? ` · ${agent}` : '');
  return `<span class="badge" style="background:var(--run-${wait ? 'waiting' : status});color:#fff">
    ${live ? '<span class="dot pulse"></span>' : '<span class="dot"></span>'}${esc(txt)}</span>`;
};
const deliveryBadge = (d) => {
  if (d === 'none') return `<span class="badge quiet">無交付</span>`;
  if (d === 'artifact') return `<span class="badge outline" style="color:var(--stage-verify)">📎 卡片產物</span>`;
  return `<span class="badge outline" style="color:var(--text-muted)">${DELIVERY_LABEL[d]}</span>`;
};
const riskBadge = (r) => `<span class="badge outline" style="color:var(--risk-${r})">${{ low: '低', medium: '中', high: '高' }[r]}風險</span>`;
const sourceBadge = (s) => {
  if (s === 'machine_verified') return `<span class="badge solid" style="background:var(--source-machine)">${SOURCE_LABEL[s]}</span>`;
  if (s === 'platform_observed') return `<span class="badge outline" style="color:var(--source-platform)">${SOURCE_LABEL[s]}</span>`;
  return `<span class="badge quiet">${SOURCE_LABEL[s]}</span>`;
};

const task = (ref) => TASKS.find((t) => t.ref === ref);

// ════════════════════════════════════════════════════════════════════════
// 3. 導覽
// ════════════════════════════════════════════════════════════════════════

const NAV = [
  { id: 'projects', label: 'Projects', ico: '▣' },
  { id: 'sessions', label: 'Sessions', ico: '▤' },
  { group: 'Infrastructure' },
  { id: 'dashboard', label: 'Dashboard', ico: '◈' },
  { id: 'nodes', label: 'Nodes', ico: '◉' },
  { id: 'agents', label: 'Agents', ico: '⬢' },
  { id: 'enrollment', label: 'Enrollment', ico: '⚿' },
  { id: 'audit', label: 'Audit', ico: '≡' },
  { id: 'integrations', label: 'Integrations', ico: '⚙' },
];

const SCREENS = [
  ['projects', 'Projects — 專案列表'],
  ['project', 'Project — 總覽'],
  ['board', 'Project — 看板（可拖曳）'],
  ['roadmap', 'Project — 藍圖'],
  ['task', 'Task 詳情（訊息串＋產物＋計畫＋驗證＋證據）'],
  ['requirements', 'Requirements — 釐清與拆解'],
  ['agents', 'Agents — Runner 管理'],
  ['run', 'Run 詳情（log＋時間軸）'],
  ['sessions', 'Sessions — V1 保留的路徑'],
  ['workspace', 'Session Workspace（兩欄＋右欄 tab）'],
  ['secrets', 'Project Settings — Secrets'],
  ['tokens', 'Design token 候選（待審查）'],
];

let route = 'projects';

function renderNav() {
  $('#nav').innerHTML = NAV.map((n) => {
    if (n.group) return `<div class="nav-group">${n.group}</div>`;
    const active = n.id === route || (n.id === 'projects' && ['project', 'board', 'roadmap', 'task', 'requirements', 'run', 'secrets'].includes(route))
      || (n.id === 'sessions' && route === 'workspace');
    return `<a data-nav="${n.id}" class="${active ? 'active' : ''}"><span class="ico">${n.ico}</span>${n.label}</a>`;
  }).join('');
}

// ════════════════════════════════════════════════════════════════════════
// 4. 畫面
// ════════════════════════════════════════════════════════════════════════

const projectTabs = (cur) => `
  <div class="tabs" style="margin-bottom:var(--space-4);border-bottom:1px solid var(--border-default);background:transparent;padding:0">
    ${[['project', '總覽'], ['requirements', '需求'], ['board', '看板'], ['roadmap', '藍圖'], ['activity', '活動'], ['secrets', '設定']]
      .map(([id, l]) => `<button data-go="${id}" class="${cur === id ? 'active' : ''}">${l}</button>`).join('')}
  </div>`;

const V = {};

V.projects = () => `
  <div class="page-head"><div><h1>Projects</h1>
    <div class="sub">2 個專案 · 5 個 workspace 綁定橫跨 3 個 node</div></div>
    <span class="spacer"></span><button class="btn primary">建立 Project</button></div>
  ${note('導覽從 5 個平項改為 <b>Projects / Sessions / Infrastructure</b> 三組，<b>既有路由路徑一律不變</b>——這是重新分組，不是搬家。群組標題做成無縮排的分隔線，208px 才夠用。', '09 §2、§3')}
  <div class="card"><table class="table">
    <thead><tr><th>名稱</th><th>狀態</th><th>Workspace</th><th>Agent</th><th>進行中</th><th>最後活動</th></tr></thead>
    <tbody>
      <tr class="clickable" data-go="project"><td><b>Cliora Platform</b><div class="muted xs">V2 升級</div></td>
        <td><span class="badge outline" style="color:var(--status-online)">Active</span></td>
        <td>3 個 · 2 nodes</td><td>2 個 runner</td>
        <td>1 run · 1 session</td><td class="muted">3 分鐘前</td></tr>
      <tr class="clickable" data-go="project"><td><b>Monstrare Kit</b><div class="muted xs">治理層維護</div></td>
        <td><span class="badge outline" style="color:var(--status-online)">Active</span></td>
        <td>2 個 · 2 nodes</td><td>2 個 runner</td>
        <td>—</td><td class="muted">2 天前</td></tr>
    </tbody></table></div>
  <div style="margin-top:var(--space-4)" class="empty">
    <strong>沒有專案時的空狀態長這樣</strong>
    還沒有專案。你仍然可以直接從 Sessions 建立 Ad-hoc Session。
  </div>
  ${note('空狀態同時教了兩件事：怎麼建專案，以及<b>不建專案也能用</b>。Ad-hoc Session 是一等公民（D12）。', '09 §4.1')}`;

V.project = () => `
  <div class="page-head"><div><h1>Cliora Platform</h1>
    <div class="sub">把 Cliora 從遠端控制台升級為 AI 開發控制平面</div></div>
    <span class="spacer"></span><button class="btn">設定</button></div>
  ${projectTabs('project')}
  <div class="grid g3" style="margin-bottom:var(--space-4)">
    <div class="card"><div class="bd"><div class="muted sm">進度</div>
      <div style="font-size:26px;font-weight:600;margin:4px 0 8px">20%</div>
      <div class="meter"><i style="width:20%"></i></div>
      <div class="muted xs" style="margin-top:6px">2 / 10 張卡完成</div></div></div>
    <div class="card"><div class="bd"><div class="muted sm">進行中</div>
      <div style="font-size:26px;font-weight:600;margin:4px 0 8px">1 run · 1 session</div>
      <div class="row wrap">${runBadge('waiting_for_input')}</div>
      <div class="muted xs" style="margin-top:6px">TASK-105 等待回覆已 18 分鐘</div></div></div>
    <div class="card"><div class="bd"><div class="muted sm">風險與阻塞</div>
      <div style="font-size:26px;font-weight:600;margin:4px 0 8px">2 高 · 1 阻塞</div>
      <div class="row wrap">${riskBadge('high')}${stageBadge('blocked')}</div>
      <div class="muted xs" style="margin-top:6px">TASK-109 被 TASK-107 擋住</div></div></div>
  </div>
  <div class="grid g2">
    <div class="card"><div class="hd">Workspace 綁定</div><table class="table">
      <tbody>
        <tr><td><b>backend</b><div class="muted xs mono">/srv/cliora/backend</div></td>
          <td>dev-vm-01</td><td><span class="badge outline" style="color:var(--status-online)"><span class="dot"></span>線上</span></td>
          <td style="text-align:right"><button class="btn sm">開 Session</button></td></tr>
        <tr><td><b>frontend</b><div class="muted xs mono">/srv/cliora/frontend</div></td>
          <td>dev-vm-01</td><td><span class="badge outline" style="color:var(--status-online)"><span class="dot"></span>線上</span></td>
          <td style="text-align:right"><button class="btn sm">開 Session</button></td></tr>
        <tr><td><b>daemon</b><div class="muted xs mono">/srv/cliora/daemon</div></td>
          <td>build-vm-02</td><td><span class="badge outline" style="color:var(--status-busy)"><span class="dot"></span>Root 已停用</span></td>
          <td style="text-align:right"><button class="btn sm" disabled>開 Session</button></td></tr>
      </tbody></table>
      ${note('綁定列上的三種狀態要分得出來：<b>node 離線</b>、<b>root 被停用</b>、<b>路徑不存在</b>。都不是錯誤頁，是這一列上的一個狀態。而且綁定<b>永遠不是授權</b>——每次使用都重跑前綴檢查。', '00 紅線 2、09 §4.2')}
    </div>
    <div class="card"><div class="hd">近期活動</div><div class="bd">
      <div class="timeline">
        <div class="tl"><span class="t">14:31</span><span class="d on"></span><span>build-vm-02 在 TASK-105 提問，等待回覆</span><span class="dur"></span></div>
        <div class="tl"><span class="t">14:27</span><span class="d"></span><span>附加產物 runner-protocol-draft.md</span><span class="dur"></span></div>
        <div class="tl"><span class="t">14:02</span><span class="d"></span><span>build-vm-02 認領 TASK-105（run #7）</span><span class="dur"></span></div>
        <div class="tl"><span class="t">13:40</span><span class="d"></span><span>neil 把 TASK-103 移到「驗證中」</span><span class="dur"></span></div>
        <div class="tl"><span class="t">11:12</span><span class="d"></span><span>TASK-102 完成，PR #415 已合併</span><span class="dur"></span></div>
      </div></div></div>
  </div>`;

V.board = () => {
  const lanes = STAGES.map((s) => {
    const items = TASKS.filter((t) => t.stage === s.id);
    const over = s.wip && items.length > s.wip;
    return `<div class="lane" data-lane="${s.id}">
      <div class="hd"><span class="bar" style="background:var(--stage-${s.id})"></span>${s.label}
        <span class="count ${over ? 'over-wip' : ''}">${items.length}${s.wip ? ` / ${s.wip}` : ''}</span></div>
      <div class="bd">${items.map(tcard).join('')}</div></div>`;
  }).join('');
  return `
  <div class="page-head"><div><h1>Cliora Platform</h1><div class="sub">看板</div></div>
    <span class="spacer"></span><button class="btn">新增任務</button></div>
  ${projectTabs('board')}
  <div class="board-bar">
    <span class="muted">車道詞彙沿用 Monstrare 的 <code class="mono">stage</code>，UI 顯示中文標籤</span>
    <span class="spacer" style="flex:1"></span>
    <span class="muted">WIP 超標只變色不阻擋</span>
  </div>
  ${note('<b>試著拖看看：</b>把「隔離工作目錄」拖到就緒（相依未滿足）、把「看板拖曳」拖到完成（Done Gate 未過）、把「調查：run log」拖到任一車道（模擬併發 409）。<b>三種拒絕的訊息必須分得出來</b>——分不出來，使用者就不知道是自己設定錯了還是再等一下就好。', 'D17b、DV-05')}
  <div class="lanes">${lanes}</div>
  ${note('<b>「等待你的回覆」是看板上唯一「系統在等人」的狀態</b>，其他都是「人在等系統」。所以它是唯一有滿版色條＋脈動指示的卡片。請確認它在一整面看板中是不是第一個被看到的。', 'D24、09 §4.3')}`;
};

function tcard(t) {
  const wait = t.run === 'waiting_for_input';
  return `<div class="tcard ${wait ? 'waiting' : ''}" draggable="true" data-ref="${t.ref}" data-go="task">
    ${wait ? '<div class="waiting-strip"><span class="pulse"></span>等待你的回覆</div>' : ''}
    <div class="ref">${t.ref}</div>
    <div class="title">${esc(t.title)}</div>
    <div class="meta">${riskBadge(t.risk)}${deliveryBadge(t.delivery)}
      ${t.run && !wait ? runBadge(t.run, t.agent) : ''}
      ${t.dependsOn ? `<span class="badge outline" style="color:var(--stage-blocked)">⛒ 待 ${t.dependsOn.join(', ')}</span>` : ''}
      ${t.secrets ? `<span class="badge quiet">🔑 ${t.secrets.length}</span>` : ''}</div>
    <div class="who">${t.assigned ? `指定 ${t.assigned}` : t.agent ? t.agent : t.owner ? t.owner : '任一 Agent'}</div>
  </div>`;
}

V.roadmap = () => {
  const rows = EPICS.map((e) => {
    const et = TASKS.filter((t) => t.epic === e.id);
    const ed = et.filter((t) => t.stage === 'done').length;
    const stories = e.stories.map((u) => {
      const ut = TASKS.filter((t) => t.us === u.id);
      const ud = ut.filter((t) => t.stage === 'done').length;
      return `<div class="rm-row us"><span class="name">${u.id} · ${u.name}</span>
        <span class="muted sm">${ud}/${ut.length}</span>
        <div class="meter"><i style="width:${ut.length ? (ud / ut.length) * 100 : 0}%"></i></div>
        <span class="pct">${ut.length ? Math.round((ud / ut.length) * 100) : 0}%</span></div>
        ${ut.map((t) => `<div class="rm-row task"><span class="name">${t.ref} ${esc(t.title)}</span>
          ${stageBadge(t.stage)}${deliveryBadge(t.delivery)}</div>`).join('')}`;
    }).join('');
    return `<div class="card rm-epic"><div class="rm-row"><b class="name">${e.id} · ${e.name}</b>
      <span class="muted sm">${ed}/${et.length}</span>
      <div class="meter"><i style="width:${(ed / et.length) * 100}%"></i></div>
      <span class="pct">${Math.round((ed / et.length) * 100)}%</span></div>${stories}</div>`;
  }).join('');
  return `<div class="page-head"><div><h1>Cliora Platform</h1><div class="sub">藍圖</div></div></div>
    ${projectTabs('roadmap')}${rows}
    ${note('Epic → User Story → Task 三層，完成度是 <code class="mono">done</code> 卡數／總數。指定了 Epic 但沒指定 User Story 的卡要落在「（未分類任務）」桶，<b>不能憑空消失</b>——這是 Monstrare 明確定義過的語意。', 'D4')}`;
};

V.task = () => `
  <div class="detail-head">
    <div><div class="muted sm mono">TASK-105 · 來自需求 #12 的提案 #3</div>
      <h1 style="margin-top:4px">Runner 註冊與認領協定</h1></div>
    <span class="spacer" style="flex:1"></span>
    <div class="row wrap">${stageBadge('implementing')}${runBadge('waiting_for_input')}${riskBadge('high')}</div>
  </div>
  ${note('版面沿用 <b>兩欄</b>：左「任務定義」右「Agent 執行」。<code class="mono">version2.md</code> §9 畫的是四欄，但 plan/08 已把三欄改成兩欄＋中央區 tab 並放棄面板拖曳，四欄會一次推翻那些決定。', '09 §4.5')}
  <div class="detail-cols">
    <div class="grid" style="gap:var(--space-4)">
      <div class="card"><div class="hd">任務定義</div><div class="bd">
        <dl class="kv">
          <dt>目標</dt><dd>讓 runner 能向平台註冊、以拉取方式認領任務，並在租約下持續回報。</dd>
          <dt>非目標</dt><dd>平台端的排程、負載平衡、自動指派。</dd>
          <dt>來源 source</dt><dd><code class="mono">repo</code> · base <code class="mono">master</code></dd>
          <dt>交付 delivery</dt><dd>${deliveryBadge('pull_request')} → <code class="mono">master</code></dd>
          <dt>需要機密</dt><dd class="muted">無</dd>
          <dt>指定 Agent</dt><dd>未指定（任一符合資格者）</dd>
        </dl></div></div>

      <div class="card"><div class="hd">驗收標準 <span class="muted sm" style="font-weight:400">2 / 5</span></div><div class="bd">
        <ul class="checklist">
          <li><span class="mark ok">✓</span><span>runner 綁兩個 Project，兩邊都能領</span></li>
          <li><span class="mark ok">✓</span><span>沒綁的第三個 Project 永遠不會被 offer</span></li>
          <li><span class="mark muted">○</span><span>兩個 runner 同時 poll 同一張卡，只有一個領到</span></li>
          <li><span class="mark muted">○</span><span>kill runner 後租約逾時能重排</span></li>
          <li><span class="mark muted">○</span><span>重排三次失敗進 blocked，不無限重試</span></li>
        </ul></div></div>

      <div class="card"><div class="hd">Review Gates</div><div class="bd">
        <ul class="checklist">
          <li><span class="mark ok">✓</span><span>產品 <span class="approver">neil · 08-07 16:20</span></span></li>
          <li><span class="mark ok">✓</span><span>架構 <span class="approver">neil · 08-08 09:05</span></span></li>
          <li><span class="mark no">✗</span><span>安全性 <span class="approver">未核准</span></span></li>
          <li><span class="mark muted">○</span><span>測試 · Code review · UI（不適用）</span></li>
        </ul>
        ${note('每個 gate 都存<b>核准者與時間</b>，不是 boolean。「agent 輸出不等於核准」在資料層的形式，就是這一格永遠有一個人類 user_id——Agent 憑證的 scope 寫死不含 <code class="mono">task.approve</code>。', 'D10、D28')}
      </div></div>

      <div class="card"><div class="hd">執行計畫 <span class="muted sm" style="font-weight:400">第 4 版 · 共 4 版</span></div><div class="bd">
        <div class="steps">${PLAN_STEPS.map((s) => `<div class="step ${s.s}">
          <span class="m">${{ completed: '✓', in_progress: '▸', pending: '○', failed: '✗', skipped: '–' }[s.s]}</span>
          <span class="t">${esc(s.t)}</span></div>`).join('')}</div>
        <div class="muted xs" style="margin-top:10px">第 4 版備註：租約改為固定 180 秒（依 neil 14:26 的回覆）</div>
        ${note('計畫是 <b>append-only 版本列</b>，只 INSERT 不 UPDATE。改計畫必須有備註——那正是「發現 Agent 是否偏離 Task」的資料來源。', 'D9')}
      </div></div>

      <div class="card"><div class="hd">驗證報告 <span class="badge solid" style="background:var(--status-error);margin-left:6px">失敗</span></div><div class="bd">
        ${CHECKS.map((c) => `<div class="check">
          <span class="cmd"><b>${esc(c.name)}</b><div class="muted xs mono">${esc(c.cmd)}</div></span>
          ${sourceBadge(c.src)}
          <span class="code ${c.code ? '' : 'muted'}" style="${c.code ? 'color:var(--status-error);font-weight:600' : ''}">exit ${c.code}</span></div>`).join('')}
        <div class="fail-box"><b>失敗項預設展開，且不可摺疊隱藏</b><br>
          <code class="mono">tests/test_runs.py::test_double_claim_impossible</code> — 兩個 runner 同時 poll 時
          <code class="mono">task_runs</code> 出現兩列，原子認領的 WHERE 條件尚未加上。</div>
        ${note('失敗的 check 與 AC <b>預設展開且不可摺疊</b>——失敗測試不可被隱藏。exit code 來自 daemon 在 run 內實際執行，所以是<b>機器事實</b>；Agent 在 payload 裡自填 <code class="mono">machine_verified</code> 會被伺服器忽略並降級。', 'D10、DV-04')}
      </div></div>
    </div>

    <div class="grid" style="gap:var(--space-4)">
      <div class="card"><div class="hd">Agent 執行</div><div class="bd">
        <dl class="kv">
          <dt>Runtime</dt><dd>codex</dd>
          <dt>Runner</dt><dd>build-vm-02</dd>
          <dt>Node</dt><dd>build-vm-02 <span class="badge outline" style="color:var(--status-online)"><span class="dot"></span>線上</span></dd>
          <dt>Run</dt><dd><a data-go="run" style="color:var(--action-primary);cursor:pointer">#7</a> · 第 1 次嘗試</dd>
          <dt>工作目錄</dt><dd class="mono xs muted">runs/7/repo（隔離，非 workspace）</dd>
        </dl>
        <div class="row" style="margin-top:var(--space-3)">
          <button class="btn sm">查看 Run</button><button class="btn sm">取消 Run</button></div>
        ${note('Agent Run <b>不是 Session</b>：不進 <code class="mono">terminal_sessions</code>、不走 Terminal relay、沒有 tmux。兩條執行路徑在資料層就分開。', 'D26、AR-01')}
      </div></div>

      <div class="card"><div class="hd">對話 <span class="badge" style="background:var(--run-waiting);color:#fff;margin-left:6px"><span class="dot pulse"></span>等待你的回覆</span></div><div class="bd">
        <div class="thread">${MESSAGES.map(msgHtml).join('')}</div>
        <div class="composer"><input placeholder="回覆 build-vm-02…"><button class="btn primary">送出</button></div>
        <div class="pull-hint">Agent 上次拉取訊息：14:31（每個停頓點主動拉取，不做中斷式推送）</div>
        ${note('這條訊息串就是「平台作為橋樑」。<b>釐清需求也用同一條管道</b>，不另做聊天介面——兩套管道會讓使用者不知道在哪回話、稽核要看兩個地方。', 'D24、D28')}
      </div></div>

      <div class="card"><div class="hd">產物 <span class="muted sm" style="font-weight:400">4 件 · 240 KB</span></div><div class="bd">
        <div class="grid" style="gap:var(--space-2)">
        ${ARTIFACTS.map((a) => `<div class="artifact">
          <span class="ico">${a.img ? '🖼' : a.html ? 'HTML' : a.name.split('.').pop().toUpperCase()}</span>
          <span class="n"><b>${esc(a.name)}</b><span>${a.size} · run ${a.run} · ${a.at} · ${esc(a.by)}</span>
          ${a.note ? `<div class="muted xs" style="margin-top:3px;color:var(--run-waiting)">⚠ ${esc(a.note)}</div>` : ''}</span>
          <button class="btn sm">下載</button></div>`).join('')}
        </div>
        ${note('<b>只有「下載」，沒有「在新分頁開啟」</b>——那等同內嵌渲染，而 Cliora 是單一 origin 部署，直接渲染 Agent 產生的 HTML 就是 stored XSS。回應一律帶 <code class="mono">Content-Disposition: attachment</code> 與 <code class="mono">nosniff</code>。<br>最後一件是平台自動附上的：本卡宣告要交付 PR，但偵測到未提交變更，<b>不靜默丟棄</b>。', 'D29 §4、§7')}
      </div></div>

      <div class="card"><div class="hd">證據</div><div class="bd">
        ${EVIDENCE.map((e) => `<div class="check">
          <span class="cmd"><b>${esc(e.kind)}</b><div class="muted xs">${esc(e.v)}</div></span>${sourceBadge(e.src)}</div>`).join('')}
        <div class="fail-box" style="border-color:#e4d8c4;background:#fdf6ec">
          <b>矛盾不仲裁</b><br>git 說 11 個檔案，Agent 自述 9 個。<b>兩者都顯示、都標來源</b>，平台不猜誰對。</div>
        ${note('三種 <code class="mono">source</code> 的視覺分級在 Evidence、驗證報告、Run 詳情三處必須<b>完全一致</b>——它是可信度語言，不是裝飾。實心＝機器事實、線框＝平台紀錄、灰字＝Agent 自述。', 'D10、09 §7')}
      </div></div>
    </div>
  </div>`;

function msgHtml(m) {
  if (m.kind === 'system') return `<div class="msg system">— ${esc(m.body)} · ${m.time}</div>`;
  const cls = m.kind === 'agent' ? `agent${m.question ? ' question' : ''}` : 'user';
  return `<div class="msg ${cls}">
    <span class="av">${m.kind === 'agent' ? '⬢' : 'N'}</span>
    <div><span class="name">${esc(m.name)}</span> <span class="time">${m.time}</span>
      ${m.question ? '<span class="badge" style="background:var(--run-waiting);color:#fff;margin-left:6px">提問</span>' : ''}
      <div class="body">${esc(m.body)}</div></div></div>`;
}

V.requirements = () => `
  <div class="page-head"><div><h1>Cliora Platform</h1><div class="sub">需求</div></div>
    <span class="spacer"></span><button class="btn primary">提個需求</button></div>
  ${projectTabs('requirements')}
  <div class="stepper">
    <span class="s done">✓ 收件</span><span class="arr">→</span>
    <span class="s done">✓ 釐清中</span><span class="arr">→</span>
    <span class="s active">規格審閱</span><span class="arr">→</span>
    <span class="s">提案接受</span></div>
  ${note('四個畫面一條線走下來。<b>Intake 的輸入框刻意簡單</b>——它接受的就是一句模糊的話，那是整條流程的前提，不要一開始就逼人填十個欄位。', 'RQ-08')}
  <div class="grid g2">
    <div class="card"><div class="hd">需求 #12</div><div class="bd">
      <div class="muted sm">neil 於 08-08 10:12 提出</div>
      <p style="margin-top:8px;line-height:1.7">「我想要 agent 做完事情之後可以自動開 PR，但有些任務其實不用開 PR，那種就把結果放在卡片上就好。」</p>
      <div class="muted xs" style="margin-top:10px">釐清 run #6 · 共 4 輪問答 · 已產出規格草稿第 2 版</div>
    </div></div>
    <div class="card"><div class="hd">規格 第 2 版</div><div class="bd">
      <dl class="kv">
        <dt>目標</dt><dd>讓任務卡宣告成果的交付形式，並由 daemon 依宣告執行。</dd>
        <dt>非目標</dt><dd>自動合併、自動部署、PR 審查動作。</dd>
        <dt>驗收標準</dt><dd>5 項（可測試）</dd>
        <dt>風險</dt><dd>${riskBadge('medium')}</dd>
      </dl></div></div>
  </div>
  <div class="card" style="margin-top:var(--space-4)"><div class="hd">未解決的問題 <span class="badge solid" style="background:var(--run-waiting);margin-left:6px">2</span></div><div class="bd">
    ${OPEN_QUESTIONS.map((q, i) => `<div class="q-open"><span class="n">${i + 1}</span><span>${esc(q)}</span></div>`).join('')}
    <div class="row" style="margin-top:var(--space-3)">
      <button class="btn primary" disabled title="仍有 2 個未解決的問題">核准規格</button>
      <span class="muted sm">仍有 2 個未解決的問題，無法核准</span></div>
    ${note('<b><code class="mono">open_questions</code> 是一等欄位，不是備註。</b> 未解決時核准按鈕停用，且要說出是哪幾個問題——不是靜默禁用。Agent 也不得自己編答案填掉它們：不知道就留在這裡，那正是它存在的理由。', 'D28 §3、RQ-03')}
  </div></div>
  <div class="card" style="margin-top:var(--space-4)"><div class="hd">拆解提案 #3 <span class="muted sm" style="font-weight:400">（規格核准後才能拆解）</span></div><div class="bd">
    <div class="prop-tree">${PROPOSALS.map((p) => `<div class="prop ${p.lvl}">
      <input type="checkbox" ${p.checked ? 'checked' : ''} ${p.dor === false ? '' : ''}>
      <span class="n"><b>${p.ref}</b> ${esc(p.title)}
        ${p.lvl === 'task' ? `<div class="row wrap" style="margin-top:5px">${riskBadge(p.risk)}${deliveryBadge(p.delivery)}
          ${p.dor ? '<span class="badge outline" style="color:var(--stage-done)">DoR 完整</span>'
                  : '<span class="badge outline" style="color:var(--status-error)">DoR 缺 2 項</span>'}</div>` : ''}
        ${p.miss ? `<div class="dor-miss">${esc(p.miss)}</div>` : ''}</span></div>`).join('')}</div>
    <div class="row" style="margin-top:var(--space-4)">
      <button class="btn primary">建立 4 張卡片</button>
      <button class="btn">全部拒絕</button>
      <span class="muted sm">缺 DoR 的卡建立後會落在「待辦」而非「就緒」</span></div>
    ${note('Agent 的產出是<b>提案，不是正式卡片</b>。人接受之後才建立真正的 Epic／US／Task。DoR 缺項的卡不會直接變成就緒——這是「agent 輸出不等於核准」在這條路徑上的形式。<br>被拒絕的提案要<b>保留並附理由</b>，下次拆解時當作負面情境。', 'D28 §2、RQ-05')}
  </div></div>`;

V.agents = () => `
  <div class="page-head"><div><h1>Agents</h1>
    <div class="sub">3 個 runner · 拉取式認領，平台不做自動指派</div></div>
    <span class="spacer"></span><button class="btn">安裝說明</button></div>
  ${note('Runner 是 <code class="mono">agentd</code> 的一個模式，<b>重用既有的 enrollment、憑證、WSS、heartbeat</b>，不新增信任建立流程。所以 runner 的線上狀態就是 node 的線上狀態，不另做一套指示燈。', 'D16')}
  <div class="card"><table class="table">
    <thead><tr><th>Runner</th><th>Node</th><th>Runtime</th><th>Labels</th><th>負載</th><th>綁定的 Project</th><th>指定給它的卡</th><th>狀態</th></tr></thead>
    <tbody>${AGENTS.map((a) => `<tr>
      <td><b>${a.name}</b></td><td>${a.node}</td>
      <td><span class="badge quiet">${a.runtime}</span></td>
      <td>${a.labels.map((l) => `<span class="badge quiet">${l}</span>`).join(' ')}</td>
      <td>${a.load} / ${a.max}</td>
      <td>${a.projects.join('、')}</td>
      <td>${a.pinned}</td>
      <td>${a.online
        ? '<span class="badge outline" style="color:var(--status-online)"><span class="dot"></span>線上</span>'
        : '<span class="badge outline" style="color:var(--status-offline)"><span class="dot"></span>離線</span>'}
        ${a.secrets ? '' : '<span class="badge quiet" title="此 node 宣告不接受機密">🔒 不收機密</span>'}</td>
    </tr>`).join('')}</tbody></table></div>
  ${note('<b>綁定 Project ＝ 授權該 runner 取用該專案的機密</b>，所以它是 Admin 權限（<code class="mono">agent.manage</code>），不是一個隨手勾的核取方塊。卡片上的「指定 agent」<b>永遠不能繞過這層綁定</b>——否則任何持有 <code class="mono">run.dispatch</code> 的 Developer 都能拿到別的專案的機密。', 'D17b、D18')}
  <div class="card" style="margin-top:var(--space-4)"><div class="hd">派工對話框（示意）</div><div class="bd">
    <div class="grid" style="gap:var(--space-2);max-width:520px">
      <label class="row"><input type="radio" name="pick" checked> <span>任一符合資格的 Agent<span class="muted sm">（預設）</span></span></label>
      <label class="row"><input type="radio" name="pick"> <span>dev-vm-01 <span class="muted sm">· 負載 1/2</span></span></label>
      <label class="row"><input type="radio" name="pick"> <span>build-vm-02 <span class="muted sm">· 負載 0/3</span></span></label>
      <label class="row" style="opacity:.55"><input type="radio" name="pick" disabled>
        <span>edge-vm-03 <span class="muted sm" style="color:var(--status-error)">· 未綁定此 Project，無法指定</span></span></label>
    </div>
    ${note('不符資格的 runner <b>顯示為停用並附原因，不是隱藏</b>——隱藏會讓人以為那台機器不存在。<br>而且兩種失敗要分得出來：<b>不符資格</b>在 dispatch 當下就回 409 不入佇列；<b>暫時離線</b>則正常入佇列，卡片顯示「等待指定的 Agent（目前離線）」。', 'D17b §2')}
  </div></div>`;

V.run = () => `
  <div class="page-head"><div><div class="muted sm">TASK-105 · Runner 註冊與認領協定</div>
    <h1 style="margin-top:3px">Run #7</h1></div>
    <span class="spacer"></span>
    <div class="row">${runBadge('waiting_for_input')}<button class="btn">取消 Run</button></div></div>
  <div class="detail-cols">
    <div class="card"><div class="hd">執行輸出 <span class="muted sm" style="font-weight:400">4.8 MB / 5 MB</span></div><div class="bd">
      <div class="log">14:02:11 準備工作目錄 runs/7
14:02:12 git worktree add（來自 mirror，未重新 clone）
14:02:13 checkout master → cliora/TASK-105-7
14:02:13 注入環境變數：GIT_TOKEN=<span class="redacted">***</span>
14:02:14 codex 啟動（sandbox bypass = on）
14:09:41 [agent] 已讀 contracts/v1/schemas/control-envelope.schema.json
14:11:02 [agent] cliora task ask —— 進入 waiting_for_input
14:26:55 [platform] 收到使用者回覆，恢復執行
14:27:10 [agent] cliora plan snapshot（第 4 版）
14:27:12 [agent] cliora task attach runner-protocol-draft.md
14:31:40 [agent] cliora task ask —— 進入 waiting_for_input
<span class="truncated">— 已截斷 1,284,006 bytes（超過單次 run 上限）—</span></div>
      ${note('<b>機密在 runner 端就被替換成 <code class="mono">***</code></b>，原值從未離開 node——在平台端過濾等於值已經傳過來了。截斷要<b>明示位元組數</b>，不是靜默丟棄。<br>Run log 是<b>診斷</b>（有保留期，到期即刪）；卡片產物是<b>交付物</b>（跟著卡片走）。兩者保留期不同，混為一談會讓卡片出現死連結。', 'D22、D27、D29 §3')}
    </div></div>
    <div class="grid" style="gap:var(--space-4)">
      <div class="card"><div class="hd">時間軸</div><div class="bd"><div class="timeline">
        <div class="tl"><span class="t">14:02:08</span><span class="d on"></span><span>queued</span><span class="dur">3s</span></div>
        <div class="tl"><span class="t">14:02:11</span><span class="d on"></span><span>claimed · build-vm-02</span><span class="dur">2s</span></div>
        <div class="tl"><span class="t">14:02:13</span><span class="d on"></span><span>preparing（worktree ＋ 機密）</span><span class="dur">1s</span></div>
        <div class="tl"><span class="t">14:02:14</span><span class="d on"></span><span>running</span><span class="dur">8m48s</span></div>
        <div class="tl"><span class="t">14:11:02</span><span class="d on"></span><span>waiting_for_input</span><span class="dur">15m53s</span></div>
        <div class="tl"><span class="t">14:26:55</span><span class="d on"></span><span>running</span><span class="dur">4m45s</span></div>
        <div class="tl"><span class="t">14:31:40</span><span class="d on"></span><span>waiting_for_input</span><span class="dur">進行中</span></div>
      </div></div></div>
      <div class="card"><div class="hd">執行環境</div><div class="bd">
        <dl class="kv">
          <dt>工作目錄</dt><dd class="mono xs">runs/7/ · 340 MB</dd>
          <dt>Checkout</dt><dd class="mono xs">3f9a1c2（master）</dd>
          <dt>分支</dt><dd class="mono xs">cliora/TASK-105-7</dd>
          <dt>使用的機密</dt><dd><span class="badge quiet">GIT_TOKEN</span><div class="muted xs" style="margin-top:3px">只顯示名稱</div></dd>
          <dt>清理時間</dt><dd class="muted">成功後 3 天（失敗則 14 天）</dd>
          <dt>租約</dt><dd>每 30 秒續租 · 逾時 180 秒</dd>
        </dl></div></div>
    </div>
  </div>`;

V.workspace = () => `
  <div class="row" style="margin-bottom:var(--space-2)">
    <button class="btn sm">← 返回</button>
    <b>Cliora Platform</b><span class="muted">·</span>
    <span>TASK-105</span><span class="muted">·</span>
    <span class="muted">codex · dev-vm-01 · /srv/cliora/backend</span>
    <span class="spacer" style="flex:1"></span>
    <span class="badge outline" style="color:var(--status-online)"><span class="dot"></span>Session 進行中</span>
  </div>
  <div class="ws" style="height:calc(100dvh - 38px - 56px - 118px)">
    <div class="ws-main">
      <div class="tabs"><button class="active">Terminal</button><button>Files</button><button>Preview</button></div>
      <div class="term">$ codex
Codex CLI v0.42 — /srv/cliora/backend

› 我來看一下 run 的認領邏輯。

⏺ Read(backend/app/services/runs.py)
  ⎿  Read 214 lines

⏺ 原子認領的 UPDATE 少了 WHERE runner_id IS NULL，兩個 runner 同時
  poll 會各拿到一列。我補上這個條件並加一條併發測試。

⏺ Edit(backend/app/services/runs.py)
  ⎿  Updated 1 addition and 1 removal

› _</div>
    </div>
    <div class="ws-rail">
      <div class="tabs"><button class="active">Task</button><button>Plan</button><button>Files</button></div>
      <div class="bd">
        <div class="muted sm mono">TASK-105</div>
        <div style="font-weight:600;margin:4px 0 10px;line-height:1.5">Runner 註冊與認領協定</div>
        <div class="row wrap" style="margin-bottom:12px">${stageBadge('implementing')}${riskBadge('high')}</div>
        <div class="muted xs" style="margin-bottom:6px">驗收標準 2 / 5</div>
        <ul class="checklist sm">
          <li><span class="mark ok">✓</span><span>兩個 Project 都能領</span></li>
          <li><span class="mark ok">✓</span><span>未綁定的不會被 offer</span></li>
          <li><span class="mark muted">○</span><span>雙重領取不可能</span></li>
          <li><span class="mark muted">○</span><span>租約逾時能重排</span></li>
          <li><span class="mark muted">○</span><span>重排三次進 blocked</span></li>
        </ul>
        <div class="muted xs" style="margin:14px 0 6px">相依</div>
        <div class="muted sm">無</div>
      </div>
    </div>
  </div>
  <div class="statusbar">
    <span>Task：${'進行中'}</span><span>驗證：未開始</span>
    <span>Git：<code class="mono">master</code></span>
    <span>Session：writer（neil）</span><span class="spacer" style="flex:1"></span>
    <span class="muted">80×24</span>
  </div>
  ${note('<b>不做 <code class="mono">version2.md</code> §9 的四欄。</b> 沿用既有的兩欄 grid <code class="mono">1fr 300px</code>，右欄（本來只有 FileTree）改成 tab 化。<b>Terminal 一個像素都沒變窄</b>——這是 plan/08、plan/09 與 style.md §12／§18 共同指向的方向。<br>Ad-hoc Session（沒有 Task）時右欄只有 Files，與升級前逐像素相同。', '09 §5')}`;

V.secrets = () => `
  <div class="page-head"><div><h1>Cliora Platform</h1><div class="sub">設定 · 機密</div></div></div>
  ${projectTabs('secrets')}
  <div class="card"><div class="hd">Secrets <span class="muted sm" style="font-weight:400">3 個 · 允許的名稱由本專案宣告</span></div>
    <table class="table"><thead><tr><th>名稱</th><th>類型</th><th>建立者</th><th>最後使用</th><th></th></tr></thead>
    <tbody>${SECRETS.map((s) => `<tr>
      <td class="mono"><b>${s.name}</b></td>
      <td><span class="badge quiet">${s.kind}</span></td>
      <td>${s.by}</td><td class="muted">${s.used}</td>
      <td style="text-align:right"><button class="btn sm">輪替</button> <button class="btn sm">刪除</button></td>
    </tr>`).join('')}</tbody></table></div>
  ${note('<b>沒有「顯示值」按鈕，也沒有「複製」。</b> 值寫入後任何 API 都讀不回——這一條要有針對 OpenAPI schema 的斷言測試，不是「我們沒寫那個 endpoint」而已。<br>下放時只送該卡片宣告的那幾個，走既有已認證的 WSS；runner 收到只放記憶體，不寫進任何檔案。', 'D22')}
  <div class="grid g2" style="margin-top:var(--space-4)">
    <div class="card"><div class="hd">產物配額</div><div class="bd">
      <div class="row" style="justify-content:space-between;margin-bottom:6px"><span>已使用</span><b>240 KB / 1 GB</b></div>
      <div class="meter" style="width:100%"><i style="width:2%"></i></div>
      <div class="muted xs" style="margin-top:8px">單件上限 10 MB · 用盡時 run 會收到明確錯誤並顯示在卡片，不是靜默失敗</div></div></div>
    <div class="card"><div class="hd">Repositories</div><div class="bd">
      <dl class="kv">
        <dt>Repository</dt><dd class="mono xs">github.com/Lei-k/cliora</dd>
        <dt>預設 base</dt><dd class="mono xs">master</dd>
        <dt>預設 target</dt><dd class="mono xs">master</dd>
        <dt>認證</dt><dd><span class="badge quiet">GIT_TOKEN</span></dd>
        <dt>分支命名空間</dt><dd class="mono xs">cliora/&lt;card_ref&gt;-&lt;run_seq&gt;</dd>
      </dl>
      ${note('分支命名空間<b>寫死在 daemon，不是設定值</b>。永不推 base／target 分支、永不 force push、永不自動合併。', 'D20、紅線 4')}
    </div></div>
  </div>`;

V.sessions = () => `
  <div class="page-head"><div><h1>Sessions</h1>
    <div class="sub">使用者直接操作的路徑 — <b>V2 完全保留，行為未變</b></div></div>
    <span class="spacer"></span><button class="btn primary">建立 Session</button></div>
  ${note('這是 V1 的畫面。V2 的 Agent Run <b>不出現在這裡</b>——它有自己的表與狀態機，兩條執行路徑在資料層就分開。把 run 混進 Sessions 清單會讓兩種生命週期看起來像同一種東西。', '00 §2、D26')}
  <div class="card"><table class="table">
    <thead><tr><th>名稱</th><th>Runtime</th><th>Node</th><th>Workspace</th><th>Project / Task</th><th>狀態</th></tr></thead>
    <tbody>
      <tr class="clickable" data-go="workspace">
        <td><b>backend refactor</b></td><td>codex</td><td>dev-vm-01</td>
        <td class="mono xs">/srv/cliora/backend</td>
        <td>Cliora Platform · TASK-105</td>
        <td><span class="badge outline" style="color:var(--status-online)"><span class="dot"></span>進行中</span></td></tr>
      <tr class="clickable" data-go="workspace">
        <td><b>臨時排查</b></td><td>claude</td><td>build-vm-02</td>
        <td class="mono xs">/srv/tmp/scratch</td>
        <td class="muted">Ad-hoc（無 Project）</td>
        <td><span class="badge outline" style="color:var(--status-offline)"><span class="dot"></span>已中斷</span></td></tr>
    </tbody></table></div>
  ${note('第二列是 <b>Ad-hoc Session</b>：只有 Workspace ＋ Runtime，沒有 Project 也沒有 Task。它是一等公民，不是過渡措施——<code class="mono">project_id</code> 與 <code class="mono">task_id</code> 永遠 nullable。', 'D12、version2.md §15')}`;

const UNCHANGED = {
  dashboard: ['Dashboard', '艦隊健康度、node 資源、錯誤摘要'],
  nodes: ['Nodes', 'node 清單、註冊、runtime 偵測、posture、更新'],
  enrollment: ['Enrollment', '一次性註冊 token 與安裝指令'],
  audit: ['Audit', '稽核紀錄查詢'],
  integrations: ['Integrations', '第三方 tunnel 供應商憑證'],
};

V.unchanged = () => {
  const [name, desc] = UNCHANGED[route] || ['—', ''];
  return `<div class="page-head"><div><h1>${name}</h1><div class="sub">${desc}</div></div></div>
    <div class="empty" style="padding:56px 32px">
      <strong style="font-size:var(--font-md)">此畫面 V1 已存在，V2 完全不改</strong>
      這份 prototype 只畫 V2 新增或變動的畫面。<br>
      <span class="muted sm">${name} 的路由路徑、版面與行為都與升級前一致——導覽只是把它收進 Infrastructure 群組。</span>
    </div>
    ${note('V2 對既有畫面的唯一觸碰是<b>導覽分組</b>，<b>路由路徑一律不變</b>。任何人存的書籤都還能用，這也是回歸測試的一條：旗標關閉時導覽退回 V1 的五個平項。', '00 §5、09 §2')}`;
};

V.tokens = () => {
  const groups = [
    ['Task stage（六車道）', ['stage-backlog', 'stage-blocked', 'stage-ready', 'stage-implementing', 'stage-verify', 'stage-done']],
    ['Run 狀態', ['run-queued', 'run-running', 'run-waiting', 'run-succeeded', 'run-failed', 'run-lost']],
    ['Risk', ['risk-low', 'risk-medium', 'risk-high']],
    ['證據可信度', ['source-machine', 'source-platform', 'source-agent']],
    ['既有（不得更動）', ['status-online', 'status-offline', 'status-busy', 'status-error', 'action-primary']],
  ];
  return `<div class="page-head"><div><h1>Design token 候選</h1>
    <div class="sub">V2 需要的新 token 集中在這裡，待本次審查決定是否進 <code class="mono">frontend/src/theme/tokens.css</code></div></div></div>
  ${note('<b>三組「進行中」必須一眼分得出來</b>：Session 進行中（既有綠）、Task 進行中（藍）、Run 執行中（琥珀＋脈動）。同一個畫面上會同時出現這三種，全用綠色會讓人完全看不出差別。<br>下方三顆並排，請確認是否足夠區分。', '09 §7')}
  <div class="card" style="margin-bottom:var(--space-4)"><div class="bd"><div class="row wrap" style="gap:var(--space-4)">
    <span class="badge outline" style="color:var(--status-online)"><span class="dot"></span>Session 進行中</span>
    ${stageBadge('implementing')}
    ${runBadge('running', 'build-vm-02')}
  </div></div></div>
  ${groups.map(([name, keys]) => `<div class="card" style="margin-bottom:var(--space-4)">
    <div class="hd">${name}</div><div class="bd">${keys.map((k) => `<div class="swatch">
      <span class="chip" style="background:var(--${k})"></span>
      <span class="nm">--${k}</span>
      <span class="hex" data-hex="${k}"></span></div>`).join('')}</div></div>`).join('')}
  <div class="card"><div class="hd">徽章一覽</div><div class="bd">
    <div class="row wrap" style="gap:var(--space-2);margin-bottom:var(--space-3)">${STAGES.map((s) => stageBadge(s.id)).join('')}</div>
    <div class="row wrap" style="gap:var(--space-2);margin-bottom:var(--space-3)">${Object.keys(RUN_LABEL).filter((k) => k !== 'cancelled').map((k) => runBadge(k)).join('')}</div>
    <div class="row wrap" style="gap:var(--space-2);margin-bottom:var(--space-3)">${Object.keys(DELIVERY_LABEL).map(deliveryBadge).join('')}</div>
    <div class="row wrap" style="gap:var(--space-2)">${Object.keys(SOURCE_LABEL).map(sourceBadge).join('')}</div>
  </div></div>`;
};

// ════════════════════════════════════════════════════════════════════════
// 5. 路由與互動
// ════════════════════════════════════════════════════════════════════════

const ALIAS = { activity: 'project' };

function go(id) {
  if (ALIAS[id]) id = ALIAS[id];
  route = id;
  const view = V[id] || (UNCHANGED[id] ? V.unchanged : V.projects);
  if (!V[id] && !UNCHANGED[id]) route = 'projects';
  const main = $('#main');
  main.className = route === 'workspace' ? 'fill' : '';
  main.innerHTML = view();
  main.scrollTop = 0;
  renderNav();
  $('#jump').value = SCREENS.some(([s]) => s === route) ? route : '';
  if (route === 'board') wireBoard();
  if (route === 'tokens') fillHex();
}

function fillHex() {
  const cs = getComputedStyle(document.documentElement);
  document.querySelectorAll('[data-hex]').forEach((el) => {
    el.textContent = cs.getPropertyValue('--' + el.dataset.hex).trim();
  });
}

// 拖曳：三種拒絕各有各的訊息，這是本 prototype 最需要被確認的互動
function wireBoard() {
  let dragged = null;
  document.querySelectorAll('.tcard').forEach((c) => {
    c.addEventListener('dragstart', () => { dragged = c; c.classList.add('dragging'); });
    c.addEventListener('dragend', () => { c.classList.remove('dragging'); dragged = null; });
  });
  document.querySelectorAll('.lane').forEach((lane) => {
    lane.addEventListener('dragover', (e) => { e.preventDefault(); lane.classList.add('over'); });
    lane.addEventListener('dragleave', () => lane.classList.remove('over'));
    lane.addEventListener('drop', (e) => {
      e.preventDefault();
      lane.classList.remove('over');
      if (!dragged) return;
      const t = task(dragged.dataset.ref);
      const to = lane.dataset.lane;
      if (t.stage === to) return;
      const rej = reject(t, to);
      if (rej) {
        dragged.classList.add('bounce');
        setTimeout(() => dragged && dragged.classList.remove('bounce'), 350);
        toast(rej[0], rej[1]);
        return;
      }
      t.stage = to;
      go('board');
      toast('已更新', `${t.ref} → ${STAGES.find((s) => s.id === to).label}`, true);
    });
  });
}

const ORDER = ['backlog', 'blocked', 'ready', 'implementing', 'verify', 'done'];

function reject(t, to) {
  // 1. 相依未滿足（D17b / TK-04）——訊息必須指名是哪幾張卡
  if (t.dependsOn && ORDER.indexOf(to) >= ORDER.indexOf('ready')) {
    const blockers = t.dependsOn.filter((r) => task(r) && task(r).stage !== 'done');
    if (blockers.length) {
      return ['無法移動：前置任務尚未完成',
        `${blockers.join('、')} 還沒進入「完成」。指名是哪幾張卡，使用者才知道要去推哪一張。`];
    }
  }
  // 2. Done Gate（DV-05）——訊息必須指名缺哪一項
  if (to === 'done') {
    const miss = [];
    if (!t.verified) miss.push('Verification Report');
    if (t.ac && t.acDone < t.ac) miss.push(`Acceptance Criteria（${t.acDone}/${t.ac}）`);
    if (t.delivery === 'pull_request' && !t.pr) miss.push('PR 連結或「無變更」結論');
    if (t.delivery === 'artifact') miss.push('至少一件卡片產物');
    if (miss.length) {
      return ['無法標記完成：Done Gate 未通過',
        `缺少 ${miss.join('、')}。Admin 可用 --force 強制推進，但需填寫理由且永久可見。`];
    }
  }
  // 3. 併發衝突（TK-07）——訊息要教使用者真實來源在哪
  if (t.demo === 'conflict') {
    return ['這張卡剛被別人改過',
      '你看到的是 3 分鐘前的版本（樂觀鎖 409）。已為你重新載入，請確認後再移動一次。'];
  }
  return null;
}

// ════════════════════════════════════════════════════════════════════════
// 6. 啟動
// ════════════════════════════════════════════════════════════════════════

$('#jump').innerHTML = SCREENS.map(([id, l]) => `<option value="${id}">${l}</option>`).join('');
$('#jump').addEventListener('change', (e) => go(e.target.value));

$('#toggle-notes').addEventListener('click', (e) => {
  const on = document.body.classList.toggle('notes');
  e.target.setAttribute('aria-pressed', String(on));
});

document.addEventListener('click', (e) => {
  const nav = e.target.closest('[data-nav]');
  if (nav) return go(nav.dataset.nav);
  const g = e.target.closest('[data-go]');
  if (g) return go(g.dataset.go);
});

const showW = () => { $('#vw').textContent = `${window.innerWidth}×${window.innerHeight}`; };
window.addEventListener('resize', showW);
showW();

go('projects');
