// The daemon-update section of NodeDetailView (P4-10).
//
// One behaviour here is easy to get wrong and expensive when it is: a 200 from
// `POST /api/nodes/{id}/update` does **not** mean the update finished. The daemon
// restarts mid-update, so `in_progress` is a legitimate outcome — reporting it as
// success would tell an operator the fleet moved when it may not have.

import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createRouter, createWebHistory, type Router } from "vue-router";

import { ApiError } from "../api/client";
import type { NodeDetail, NodeUpdateStatus, ReleaseManifest } from "../api/dto";
import { useAuthStore } from "../stores/auth";
import * as auth from "../stores/auth";
import NodeDetailView from "./NodeDetailView.vue";

function updateStatus(
  overrides: Partial<NodeUpdateStatus> = {},
): NodeUpdateStatus {
  return {
    current_version: "1.3.0",
    latest_version: "1.4.0",
    status: null,
    target_version: null,
    last_result: null,
    updated_at: null,
    auto_update_enabled: false,
    ...overrides,
  };
}

function nodeDetail(status: NodeUpdateStatus): NodeDetail {
  return {
    id: "n-1",
    name: "vm-1",
    hostname: "vm-1.local",
    status: "online",
    os: "linux",
    architecture: "amd64",
    claude_available: true,
    codex_available: true,
    session_count: 0,
    last_seen_at: "2026-07-25T11:59:00Z",
    os_version: "Ubuntu 24.04",
    daemon_version: status.current_version,
    run_user: "cliora",
    is_enabled: true,
    registered_at: "2026-07-01T00:00:00Z",
    runtimes: [],
    workspace_roots: [],
    resources: null,
    update_status: status,
    recent_errors: [],
  };
}

function manifest(versions: string[]): ReleaseManifest {
  return {
    latest: versions[0] ?? null,
    artifacts: versions.flatMap((version) =>
      (["amd64", "arm64"] as const).map((architecture) => ({
        version,
        architecture,
        filename: `agentd_${version}_linux_${architecture}.tar.gz`,
        sha256: "a".repeat(64),
        size: 1024,
      })),
    ),
    generated_at: "2026-07-25T12:00:00Z",
  };
}

function testRouter(): Router {
  return createRouter({
    history: createWebHistory(),
    routes: [
      { path: "/nodes", name: "nodes", component: { template: "<div/>" } },
      { path: "/nodes/:id", name: "node-detail", component: NodeDetailView },
      // The port-forwarding summary section links to these (P11).
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

async function render(options: {
  status?: NodeUpdateStatus;
  versions?: string[];
  updateNode?: ReturnType<typeof vi.fn>;
  role?: string;
}) {
  const status = options.status ?? updateStatus();
  const updateNode =
    options.updateNode ??
    vi
      .fn()
      .mockResolvedValue(nodeDetail(updateStatus({ status: "succeeded" })));
  vi.spyOn(auth, "api").mockReturnValue({
    getNode: vi.fn().mockResolvedValue(nodeDetail(status)),
    getReleaseManifest: vi
      .fn()
      .mockResolvedValue(manifest(options.versions ?? ["1.4.0"])),
    updateNode,
  } as unknown as ReturnType<typeof auth.api>);

  const store = useAuthStore();
  store.user = {
    id: "u",
    username: "admin",
    display_name: "Admin",
    role: options.role ?? "Admin",
    permissions: options.role === "Developer" ? [] : ["node.manage"],
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
  return { wrapper, updateNode };
}

function button(wrapper: ReturnType<typeof mount>, label: string) {
  return wrapper.findAll("button").find((b) => b.text() === label);
}

describe("NodeDetailView — daemon update", () => {
  beforeEach(() => setActivePinia(createPinia()));
  afterEach(() => vi.restoreAllMocks());

  it("shows the current and the latest available version", async () => {
    const { wrapper } = await render({});
    const text = wrapper.text();
    expect(text).toContain("1.3.0");
    expect(text).toContain("1.4.0");
  });

  it("distinguishes never-updated from a successful update", async () => {
    // A null status means this node has never been asked. Rendering it as
    // "succeeded" would claim an update happened.
    const { wrapper } = await render({
      status: updateStatus({ status: null }),
    });
    expect(wrapper.text()).toContain("尚未執行過更新");
  });

  it("offers only the versions the manifest publishes, as a picker", async () => {
    // Never a free-text field: the version must be an allowlisted release, and
    // there is deliberately no way to name a URL or a filename (SEC-002).
    const { wrapper } = await render({ versions: ["1.4.0", "1.3.0"] });
    const options = wrapper.findAll("select option").map((o) => o.text());
    expect(options).toContain("1.4.0");
    expect(options).toContain("1.3.0");
    expect(wrapper.findAll('input[type="url"]')).toHaveLength(0);
    expect(wrapper.html()).not.toContain("target_version");
  });

  it("sends only a version when the update is triggered", async () => {
    const updateNode = vi
      .fn()
      .mockResolvedValue(nodeDetail(updateStatus({ status: "succeeded" })));
    const { wrapper } = await render({ updateNode });

    await wrapper.find("select").setValue("1.4.0");
    await button(wrapper, "更新")?.trigger("click");
    await flushPromises();

    expect(updateNode).toHaveBeenCalledWith("n-1", {
      target_version: "1.4.0",
    });
  });

  it("reports an in-progress result as pending, not as success", async () => {
    // The whole point: the daemon restarts during the update, so the request
    // succeeding is not the update succeeding.
    const updateNode = vi
      .fn()
      .mockResolvedValue(
        nodeDetail(
          updateStatus({ status: "in_progress", target_version: "1.4.0" }),
        ),
      );
    const { wrapper } = await render({ updateNode });

    await wrapper.find("select").setValue("1.4.0");
    await button(wrapper, "更新")?.trigger("click");
    await flushPromises();

    const text = wrapper.text();
    expect(text).toContain("已送出更新要求");
    expect(text).toContain("tmux session 不受影響");
    expect(text).not.toContain("更新結果：成功");
  });

  it("explains a rollback and links the runbook", async () => {
    const { wrapper } = await render({
      status: updateStatus({
        status: "rolled_back",
        target_version: "1.4.0",
        last_result: "UPDATE_HEALTHCHECK_FAILED",
        updated_at: "2026-07-25T11:00:00Z",
      }),
    });
    const text = wrapper.text();
    expect(text).toContain("已回復");
    // The stable code is shown so it can be looked up and quoted.
    expect(text).toContain("UPDATE_HEALTHCHECK_FAILED");
  });

  it("does not repeat the code when the update succeeded", async () => {
    const { wrapper } = await render({
      status: updateStatus({ status: "succeeded", last_result: "succeeded" }),
    });
    expect(wrapper.findAll("code").map((c) => c.text())).not.toContain(
      "succeeded",
    );
  });

  it("shows the server's message and the runbook when the request is refused", async () => {
    const updateNode = vi
      .fn()
      .mockRejectedValue(
        new ApiError("NODE_OFFLINE", "Node is not connected", 409),
      );
    const { wrapper } = await render({ updateNode });

    await wrapper.find("select").setValue("1.4.0");
    await button(wrapper, "更新")?.trigger("click");
    await flushPromises();

    expect(wrapper.text()).toContain("Node is not connected");
    expect(wrapper.text()).toContain("update-failure runbook");
  });

  it("says so when nothing is published rather than showing an empty picker", async () => {
    const { wrapper } = await render({ versions: [] });
    expect(wrapper.text()).toContain("尚未發佈任何 release");
    expect(button(wrapper, "更新")?.attributes("disabled")).toBeDefined();
  });

  it("hides the control for a role without node.manage", async () => {
    // A courtesy only — the server refuses the request either way (ADR 0016).
    const { wrapper } = await render({ role: "Developer" });
    expect(wrapper.find("select").exists()).toBe(false);
    expect(button(wrapper, "更新")).toBeUndefined();
  });

  it("states that auto-update is off by design, not pending", async () => {
    const { wrapper } = await render({});
    expect(wrapper.text()).toContain("更新一律由人明確觸發");
    expect(wrapper.text()).not.toContain("P1 停用");
  });

  it("renders even when the release manifest cannot be fetched", async () => {
    vi.spyOn(auth, "api").mockReturnValue({
      getNode: vi.fn().mockResolvedValue(nodeDetail(updateStatus())),
      getReleaseManifest: vi.fn().mockRejectedValue(new Error("offline")),
      updateNode: vi.fn(),
    } as unknown as ReturnType<typeof auth.api>);
    const store = useAuthStore();
    store.user = {
      id: "u",
      username: "admin",
      display_name: "Admin",
      role: "Admin",
      permissions: ["node.manage"],
    };
    const router = testRouter();
    await router.push("/nodes/n-1");
    const wrapper = mount(NodeDetailView, {
      props: { id: "n-1" },
      global: {
        plugins: [router],
        stubs: { AppLayout: { template: "<div><slot /></div>" } },
      },
    });
    await flushPromises();

    expect(wrapper.text()).toContain("vm-1");
    expect(wrapper.text()).toContain("尚未發佈任何 release");
  });
});
