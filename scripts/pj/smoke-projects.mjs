// Drive the project screens in a real browser (plan/16 PJ-06/PJ-07).
//
// Not a replacement for the Playwright suite: this is the operational evidence the
// plan asks for — that the two new views render against a live Central, that a
// binding's usability shows up, and that a Viewer sees the timeline without actor
// names. It writes screenshots so the result is inspectable rather than asserted
// into a green tick.
//
//   CLIORA_PROJECTS_ENABLED=true scripts/e2e/run-stack.sh bash -c '... node ../scripts/pj/smoke-projects.mjs'

import { mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const frontend = resolve(here, "../../frontend");
const { chromium } = createRequire(resolve(frontend, "package.json"))("@playwright/test");

const UI = process.env.E2E_BASE_URL ?? "http://127.0.0.1:5173";
const API = process.env.E2E_API_URL ?? "http://127.0.0.1:8000";
const OUT = resolve(here, "../../artifacts/pj/local/smoke");
mkdirSync(OUT, { recursive: true });

const ADMIN = {
  user: process.env.E2E_ADMIN_USER ?? "e2e-admin",
  pw: process.env.E2E_ADMIN_PASSWORD ?? "e2e-admin-pw",
};
const VIEWER = { user: "e2e-viewer", pw: process.env.E2E_SEED_PASSWORD ?? "e2e-seed-pw" };

const fail = [];
function check(name, condition, detail = "") {
  console.log(`${condition ? "ok  " : "FAIL"}  ${name}${detail ? ` — ${detail}` : ""}`);
  if (!condition) fail.push(name);
}

async function token({ user, pw }) {
  const resp = await fetch(`${API}/api/auth/login`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ username: user, password: pw }),
  });
  const body = await resp.json();
  return body.tokens.access_token;
}

async function signIn(page, { user, pw }) {
  await page.goto(`${UI}/login`, { waitUntil: "domcontentloaded" });
  await page.locator('input[name="username"]').fill(user);
  await page.locator('input[name="password"]').fill(pw);
  await page.locator('button[type="submit"]').click();
  await page.waitForURL(/\/(dashboard|nodes|sessions)/, { timeout: 15000 });
}

const adminToken = await token(ADMIN);
const authed = (body) => ({
  method: "POST",
  headers: { "content-type": "application/json", authorization: `Bearer ${adminToken}` },
  body: JSON.stringify(body),
});

// Seed through the API so the browser part stays about rendering.
const nodes = await (
  await fetch(`${API}/api/nodes`, { headers: { authorization: `Bearer ${adminToken}` } })
).json();
const node = nodes[0];
const root = (
  await (
    await fetch(`${API}/api/nodes/${node.id}`, {
      headers: { authorization: `Bearer ${adminToken}` },
    })
  ).json()
).workspace_roots[0];

const slug = `smoke-${Date.now().toString(36)}`;
const project = await (
  await fetch(`${API}/api/projects`, authed({ name: `Smoke ${slug}`, slug }))
).json();
check("project created", Boolean(project.id), project.slug);

const bound = await (
  await fetch(
    `${API}/api/projects/${project.id}/workspaces`,
    authed({ node_id: node.id, path: root.path, is_primary: true }),
  )
).json();
check("workspace bound", Boolean(bound.id), `${bound.node_name}:${bound.path} → ${bound.usability}`);

const browser = await chromium.launch();

// --- Admin: list, then detail -------------------------------------------- //
{
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  await signIn(page, ADMIN);

  await page.goto(`${UI}/projects`, { waitUntil: "networkidle" });
  check("projects list shows the project", (await page.textContent("body")).includes(slug));
  await page.screenshot({ path: resolve(OUT, "projects-list.png"), fullPage: false });

  await page.goto(`${UI}/projects/${project.id}`, { waitUntil: "networkidle" });
  const detail = await page.textContent("body");
  check("detail shows the binding", detail.includes(root.path));
  check("detail shows the node name", detail.includes(node.name));
  check("detail shows an actor for an Admin", detail.includes("Administrator"));
  await page.screenshot({ path: resolve(OUT, "project-detail-admin.png"), fullPage: false });

  await page.locator('button:has-text("Activity")').click();
  await page.waitForTimeout(300);
  const activity = await page.textContent("body");
  check("activity lists the bind event", activity.includes("綁定 Workspace"));
  check("no hidden-actor notice for an Admin", !activity.includes("audit permission"));
  await page.screenshot({ path: resolve(OUT, "project-activity-admin.png"), fullPage: false });
  await context.close();
}

// --- Viewer: same page, no actor names ----------------------------------- //
{
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  await signIn(page, VIEWER);

  await page.goto(`${UI}/projects/${project.id}`, { waitUntil: "networkidle" });
  const detail = await page.textContent("body");
  check("a Viewer can read the project", detail.includes(root.path));
  check("a Viewer sees no Archive control", !detail.includes("Archive"));

  await page.locator('button:has-text("Activity")').click();
  await page.waitForTimeout(300);
  const activity = await page.textContent("body");
  check("a Viewer is told actors are hidden", activity.includes("audit permission"));
  // Scoped to the timeline rows, not the page. The header carries "owned by
  // <name>", which is a *resource attribute* rather than an actor — a Viewer is
  // told to ask an Admin, so they have to be able to see which one (ADR 0027
  // Consequences). What must not appear is a name against each event.
  const actors = await page
    .locator(".timeline li .who")
    .evaluateAll((cells) => cells.map((c) => c.textContent?.trim() ?? ""));
  check(
    "a Viewer sees no actor on any timeline row",
    actors.length > 0 && actors.every((value) => value === "—"),
    actors.join(" | "),
  );
  await page.screenshot({ path: resolve(OUT, "project-activity-viewer.png"), fullPage: false });
  await context.close();
}

await browser.close();
console.log(`\n${fail.length === 0 ? "ALL CHECKS PASSED" : `${fail.length} FAILED: ${fail.join(", ")}`}`);
process.exit(fail.length === 0 ? 0 : 1);
