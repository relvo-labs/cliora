import {
  createRouter,
  createWebHistory,
  type Router,
  type RouteRecordRaw,
} from "vue-router";

import { useAuthStore } from "../stores/auth";

export const routes: RouteRecordRaw[] = [
  {
    path: "/login",
    name: "login",
    component: () => import("../views/LoginView.vue"),
    meta: { public: true },
  },
  // The dashboard is the landing page from P4-08: fleet health is what an operator
  // wants first, and the node list is one click away.
  // V2-P1 (PX-63): `/` **is** the page and `/dashboard` is its alias, which is the
  // reverse of what it was. The page is called Home now and its content grows into a
  // cross-project summary — but the name is a rename, not a rewrite, and the fleet health
  // block on it is pixel-identical to the one on Dashboard. That is deliberate: fleet
  // health is what V1 operators use every day, and moving it is a move.
  //
  // The route **keeps the name `dashboard`**. Fourteen call sites use it, including the
  // auth guard's fallback and the catch-all, and a rename would be fourteen edits whose
  // only visible effect is that old bookmarks break.
  { path: "/dashboard", redirect: { name: "dashboard" } },
  {
    path: "/",
    name: "dashboard",
    component: () => import("../views/DashboardView.vue"),
  },
  {
    path: "/nodes",
    name: "nodes",
    component: () => import("../views/NodesView.vue"),
  },
  {
    path: "/nodes/:id",
    name: "node-detail",
    component: () => import("../views/NodeDetailView.vue"),
    props: true,
  },
  // A separate page rather than a seventh section on the node detail view: this one holds
  // settings, a list and a create form, which would make that page two things (plan/11 §2.1).
  {
    path: "/nodes/:id/tunnels",
    name: "node-tunnels",
    component: () => import("../views/NodeTunnelsView.vue"),
    props: true,
  },
  {
    path: "/enrollment",
    name: "enrollment",
    component: () => import("../views/EnrollmentView.vue"),
  },
  // No permission guard, for the same reason as /audit below: a client-side guard decides
  // what renders, not what is allowed. Reaching this without `integration.manage` shows the
  // forbidden state from the server's own 403.
  {
    path: "/settings/integrations",
    name: "integrations",
    component: () => import("../views/IntegrationsView.vue"),
  },
];

// The authenticated Session Workspace replaces the P0 terminal PoC (the P0 dev
// gateway is superseded by the P2 relay, ADR/plan 03). The token showcase stays
// as a dev-only design reference.
// No permission guard, and none for the feature flag either — same reason as
// /audit and /settings/integrations below: a client-side guard decides what
// renders, not what is allowed. Reaching these without `project.view`, or in a
// deployment with the layer switched off, shows the state driven by the server's
// own 403 or 404 (ADR 0027).
routes.push({
  // V2-P1 (PX-49/PX-63). **Above Projects in the rail**, because "what is waiting for
  // me" is the question somebody opens this application to answer. No permission guard,
  // for the same reason as every route here: a client-side guard decides what renders,
  // not what is allowed — without `project.view` the page shows the server's own 403.
  path: "/my-work",
  name: "my-work",
  component: () => import("../modules/mywork/views/MyWorkView.vue"),
});
routes.push({
  path: "/projects",
  name: "projects",
  component: () => import("../views/ProjectsView.vue"),
});
// V2-P1 (PX-64, D117). One shell with seven children, replacing the 1,515-line
// `ProjectDetailView.vue` and its `?tab=` state machine. The old file is **deleted**
// rather than kept beside this: there is no version flag and no second path.
//
// `project-detail` keeps its name and becomes the parent, so every existing
// `{ name: 'project-detail' }` in the codebase still resolves — the breadcrumbs in
// `TaskDetailView`, `RequirementDetailView` and `SessionWorkspaceView` all use it. A
// rename would have been six edits and a broken bookmark for every reader.
routes.push({
  path: "/projects/:id",
  name: "project-detail",
  component: () => import("../modules/project/ProjectShell.vue"),
  props: true,
  // `?tab=` is honoured **here**, in one place, rather than by a compatibility branch
  // inside the shell. Old links keep working, the redirect is visibly temporary, and
  // nothing in the components has to know the query parameter ever existed.
  redirect: (to) => {
    const tab = Array.isArray(to.query.tab) ? to.query.tab[0] : to.query.tab;
    const legacy: Record<string, string> = {
      overview: "project-overview",
      board: "project-work",
      roadmap: "project-roadmap",
      requirements: "project-requirements",
      activity: "project-activity",
      settings: "project-settings",
    };
    const { tab: _dropped, ...query } = to.query;
    return {
      name: legacy[String(tab)] ?? "project-overview",
      params: to.params,
      // Everything except `tab` survives, because `?task=` is the Drawer's state and a
      // link to a card inside a board must not lose the card on the way through.
      query,
    };
  },
  children: [
    {
      path: "overview",
      name: "project-overview",
      component: () =>
        import("../modules/project/views/ProjectOverviewView.vue"),
    },
    {
      // `work`, not `board`: a board is one layout of the work, and `PX-29` adds a list
      // beside it. The URL should not name whichever layout came first.
      path: "work",
      name: "project-work",
      component: () => import("../modules/project/views/ProjectWorkView.vue"),
    },
    {
      path: "roadmap",
      name: "project-roadmap",
      component: () =>
        import("../modules/project/views/ProjectRoadmapView.vue"),
    },
    {
      path: "requirements",
      name: "project-requirements",
      component: () =>
        import("../modules/project/views/ProjectRequirementsView.vue"),
    },
    {
      path: "activity",
      name: "project-activity",
      component: () =>
        import("../modules/project/views/ProjectActivityView.vue"),
    },
    {
      path: "settings",
      name: "project-settings",
      component: () =>
        import("../modules/project/views/ProjectSettingsView.vue"),
    },
  ],
});
routes.push({
  // V2-K1 built this as a top-level route because `ProjectDetailView` was already 1,515
  // lines managing twelve things (D82). **It stays top-level** rather than becoming a
  // child of the shell: the knowledge page has its own header and its own loading state,
  // and folding it in would mean rewriting both to fit a shell it does not need. The
  // shell's navigation links to it, so a reader cannot tell the difference.
  path: "/projects/:id/knowledge",
  name: "project-knowledge",
  component: () =>
    import("../modules/knowledge/views/ProjectKnowledgeView.vue"),
  meta: { requiresAuth: true },
});

routes.push({
  path: "/projects/:id/tasks/:taskId",
  name: "task-detail",
  component: () => import("../views/TaskDetailView.vue"),
  props: true,
});
routes.push({
  path: "/projects/:id/requirements/:requirementId",
  name: "requirement-detail",
  component: () => import("../views/RequirementDetailView.vue"),
  props: true,
});
// V2.2. No permission guard and no feature guard, for the same reason as every route
// above: a client-side guard decides what renders, not what is allowed. Reaching these
// without `agent.view`, or in a deployment with either flag off, shows the state driven
// by the server's own 403 or 404 (ADR 0029).
//
// **Neither of these renders an artifact.** That is asserted rather than assumed: the
// artifact download endpoint always answers `attachment`, and criterion 14 compares
// this table against the one captured before the phase started.
routes.push({
  path: "/agents",
  name: "agents",
  component: () => import("../views/AgentsView.vue"),
});
routes.push({
  path: "/projects/:id/runs/:runId",
  name: "run-detail",
  component: () => import("../views/RunDetailView.vue"),
  props: true,
});
routes.push({
  path: "/sessions",
  name: "sessions",
  component: () => import("../views/SessionsView.vue"),
});
routes.push({
  path: "/sessions/:id",
  name: "session-workspace",
  component: () => import("../views/SessionWorkspaceView.vue"),
  props: true,
});
// No permission guard: `audit.view` is enforced by the server, and a client-side
// guard would only decide what to render, not what is allowed. Reaching this
// route without the action shows the forbidden state from the server's 403.
routes.push({
  path: "/audit",
  name: "audit",
  component: () => import("../views/AuditView.vue"),
});
if (import.meta.env.DEV) {
  routes.push({
    path: "/poc/tokens",
    component: () => import("../views/TokenShowcaseView.vue"),
    meta: { public: true },
  });
}

routes.push({ path: "/:pathMatch(.*)*", redirect: { name: "dashboard" } });

// Guard: unauthenticated access to a non-public route redirects to /login
// (preserving the intended path); an authenticated user never sees /login.
export function registerGuards(router: Router): void {
  router.beforeEach((to) => {
    const auth = useAuthStore();
    if (!to.meta.public && !auth.isAuthenticated) {
      return { name: "login", query: { redirect: to.fullPath } };
    }
    if (to.name === "login" && auth.isAuthenticated) {
      // The landing page, matching `/` (P4-08).
      return { name: "dashboard" };
    }
    return true;
  });
}

export function createAppRouter(): Router {
  const router = createRouter({ history: createWebHistory(), routes });
  registerGuards(router);
  return router;
}
