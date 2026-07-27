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
  {
    path: "/enrollment",
    name: "enrollment",
    component: () => import("../views/EnrollmentView.vue"),
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
