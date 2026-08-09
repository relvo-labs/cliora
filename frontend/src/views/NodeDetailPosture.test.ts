// The execution-posture section of NodeDetailView (PV-08, ADR 0023).
//
// The thing worth testing here is not that a label renders — it is that the console
// never claims a posture the machine is not in. ADR 0021 §4.2 leaned on "the daemon
// runs non-root" as a compensating control for the system terminal; ADR 0023 replaced
// half of that with "the user can see which boundary they are inside". If this section
// can be wrong, that replacement is worth nothing.

import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createRouter, createWebHistory, type Router } from "vue-router";

import type { NodeDetail, NodeRuntime } from "../api/dto";
import { useAuthStore } from "../stores/auth";
import * as auth from "../stores/auth";
import NodeDetailView from "./NodeDetailView.vue";

function runtime(overrides: Partial<NodeRuntime> = {}): NodeRuntime {
  return {
    runtime: "codex",
    available: true,
    version: "codex 1.2.3",
    binary_path: "/usr/local/bin/codex",
    checked_at: "2026-08-01T09:00:00Z",
    sandbox_bypass: false,
    ...overrides,
  };
}

function nodeDetail(overrides: Partial<NodeDetail> = {}): NodeDetail {
  return {
    id: "n-1",
    name: "dev-vm-01",
    hostname: "dev-vm-01.local",
    status: "online",
    os: "linux",
    architecture: "amd64",
    claude_available: true,
    codex_available: true,
    session_count: 0,
    last_seen_at: "2026-08-01T09:00:00Z",
    os_version: "Ubuntu 24.04",
    daemon_version: "0.5.0",
    run_user: "neil",
    privileged_terminal: false,
    image_upload: false,
    file_upload: false,
    is_enabled: true,
    registered_at: "2026-07-01T00:00:00Z",
    runtimes: [runtime()],
    workspace_roots: [],
    resources: null,
    update_status: {
      current_version: "0.5.0",
      latest_version: "0.5.0",
      status: null,
      target_version: null,
      last_result: null,
      updated_at: null,
      auto_update_enabled: false,
    },
    recent_errors: [],
    ...overrides,
  };
}

function testRouter(): Router {
  return createRouter({
    history: createWebHistory(),
    routes: [
      { path: "/nodes", name: "nodes", component: { template: "<div/>" } },
      { path: "/nodes/:id", name: "node-detail", component: NodeDetailView },
      {
        path: "/nodes/:id/tunnels",
        name: "node-tunnels",
        component: { template: "<div/>" },
      },
      {
        path: "/settings/integrations",
        name: "integrations",
        component: { template: "<div/>" },
      },
    ],
  });
}

async function render(node: NodeDetail) {
  vi.spyOn(auth, "api").mockReturnValue({
    getNode: vi.fn().mockResolvedValue(node),
    getReleaseManifest: vi
      .fn()
      .mockResolvedValue({ latest: null, artifacts: [], generated_at: null }),
  } as unknown as ReturnType<typeof auth.api>);
  const store = useAuthStore();
  store.user = {
    id: "u",
    username: "admin",
    display_name: "Admin",
    role: "Admin",
    permissions: ["node.manage"],
    features: [],
  };
  const router = testRouter();
  await router.push("/nodes/n-1");
  await router.isReady();
  const wrapper = mount(NodeDetailView, {
    props: { id: "n-1" },
    global: {
      plugins: [router],
      stubs: { AppLayout: { template: "<div><slot /></div>" } },
    },
  });
  await flushPromises();
  return wrapper;
}

describe("NodeDetailView — execution posture", () => {
  beforeEach(() => setActivePinia(createPinia()));
  afterEach(() => vi.restoreAllMocks());

  it("says a privileged node can reach root", async () => {
    const wrapper = await render(nodeDetail({ privileged_terminal: true }));
    expect(wrapper.text()).toContain("可提權");
    expect(wrapper.text()).toContain("sudo");
  });

  it("says an unprivileged node cannot escalate", async () => {
    const wrapper = await render(nodeDetail({ privileged_terminal: false }));
    expect(wrapper.text()).toContain("不可提權");
  });

  it("reports the sandbox as disabled only when the node measured it that way", async () => {
    const bypassed = await render(
      nodeDetail({ runtimes: [runtime({ sandbox_bypass: true })] }),
    );
    expect(bypassed.text()).toContain("已停用");
    expect(bypassed.text()).toContain("無沙箱");

    // A node that asked for the bypass but whose codex does not accept the flag
    // reports false — and the console must then say "enforced". Claiming otherwise
    // would send the user looking for the cause of codex's behaviour in the wrong
    // place (ADR 0023 D3).
    const enforced = await render(
      nodeDetail({ runtimes: [runtime({ sandbox_bypass: false })] }),
    );
    expect(enforced.text()).toContain("啟用");
    expect(enforced.text()).not.toContain("無沙箱");
  });

  it("does not invent a codex posture for a node that reports no codex", async () => {
    const wrapper = await render(
      nodeDetail({ runtimes: [runtime({ runtime: "claude" })] }),
    );
    expect(wrapper.text()).toContain("未回報 codex");
  });

  it("says the platform cannot change the posture", async () => {
    // The section is only honest if it also says where the switch is. Without this
    // an operator reads two labels and starts looking for a toggle in the console.
    const wrapper = await render(nodeDetail({ privileged_terminal: true }));
    expect(wrapper.text()).toContain("平台只能顯示，無法變更");
    expect(wrapper.text()).toContain("agentd posture");
  });
});
