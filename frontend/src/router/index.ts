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
  { path: "/", redirect: { name: "dashboard" } },
  {
    path: "/dashboard",
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
  // Personal display settings (plan/28 VR-10). A sibling of the integrations
  // page in URL shape only: that one is platform configuration behind
  // `integration.manage`, this one needs no permission because nothing on it is
  // a capability — every value is a display preference held in this browser.
  {
    path: "/settings/preferences",
    name: "preferences",
    component: () => import("../views/PreferencesView.vue"),
  },
];

// The authenticated Session Workspace replaces the P0 terminal PoC (the P0 dev
// gateway is superseded by the P2 relay, ADR/plan 03). The token showcase stays
// as a dev-only design reference.
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
