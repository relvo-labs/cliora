import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createRouter, createWebHistory, type Router } from "vue-router";

import { ApiError } from "../api/client";
import type { NodeTunnelPolicy, TunnelDetail, TunnelSummary } from "../api/dto";
import * as auth from "../stores/auth";
import { useAuthStore } from "../stores/auth";
import NodeTunnelsView from "./NodeTunnelsView.vue";

const NODE_ID = "33333333-3333-4333-8333-333333333333";

function policy(overrides: Partial<NodeTunnelPolicy> = {}): NodeTunnelPolicy {
  return {
    node_id: NODE_ID,
    enabled: true,
    blocked_by: null,
    allowed_ports: ["3000-3999", "5173"],
    max_tunnels: 3,
    live_tunnel_count: 0,
    node_enabled: true,
    node_allowed_ports: null,
    node_max_tunnels: null,
    local_veto: false,
    prereq_ok: true,
    prereq_detail: {
      ssh_available: true,
      egress_ok: true,
      known_hosts_ok: true,
      daemon_supports_tunnel: true,
    },
    local_allowed_ports: null,
    local_max_tunnels: null,
    reported_at: "2026-08-01T09:00:00Z",
    plan_tier: "free",
    default_protection: "basic",
    default_ttl_seconds: 14400,
    ...overrides,
  };
}

function tunnel(overrides: Partial<TunnelSummary> = {}): TunnelSummary {
  return {
    id: "44444444-4444-4444-8444-444444444444",
    node_id: NODE_ID,
    node_name: "vm",
    port: 5173,
    label: "vite",
    url: "https://abc-1-2-3-4.run.pinggy-free.link",
    url_updated_at: "2026-08-01T09:30:00Z",
    url_change_count: 1,
    state: "running",
    protection: "basic",
    basic_auth_user: "preview",
    provider: "pinggy",
    upstream_expires_at: "2026-08-01T10:30:00Z",
    expires_at: "2026-08-01T13:00:00Z",
    created_by_username: "alice",
    created_at: "2026-08-01T09:00:00Z",
    capabilities: { can_close: true, can_rotate: true },
    state_error_code: null,
    ...overrides,
  };
}

function detail(overrides: Partial<TunnelDetail> = {}): TunnelDetail {
  return {
    ...tunnel(),
    allowed_ips: null,
    rewrite_host: false,
    basic_auth_password: "s3cret-password-value",
    ...overrides,
  };
}

function testRouter(): Router {
  return createRouter({
    history: createWebHistory(),
    routes: [
      {
        path: "/nodes/:id/tunnels",
        name: "node-tunnels",
        component: NodeTunnelsView,
        props: true,
      },
      {
        path: "/nodes/:id",
        name: "node-detail",
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

async function render(api: Record<string, unknown>) {
  vi.spyOn(auth, "api").mockReturnValue(
    api as unknown as ReturnType<typeof auth.api>,
  );
  const router = testRouter();
  await router.push(`/nodes/${NODE_ID}/tunnels`);
  await router.isReady();
  const wrapper = mount(NodeTunnelsView, {
    props: { id: NODE_ID },
    global: {
      plugins: [router],
      stubs: { AppLayout: { template: "<div><slot /></div>" } },
    },
  });
  await flushPromises();
  return wrapper;
}

function loaded(
  overrides: Partial<NodeTunnelPolicy> = {},
  tunnels: TunnelSummary[] = [],
  extra: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    getNodeTunnelPolicy: vi.fn().mockResolvedValue(policy(overrides)),
    listTunnels: vi.fn().mockResolvedValue(tunnels),
    ...extra,
  };
}

function button(wrapper: Awaited<ReturnType<typeof render>>, label: string) {
  return wrapper.findAll("button").find((b) => b.text() === label);
}

describe("NodeTunnelsView", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    useAuthStore().user = {
      id: "u",
      username: "alice",
      display_name: "Alice",
      role: "Developer",
      permissions: ["tunnel.view", "tunnel.manage"],
    };
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows the four prerequisites with the time they were reported", async () => {
    const wrapper = await render(
      loaded({
        prereq_ok: false,
        prereq_detail: {
          ssh_available: true,
          egress_ok: false,
          known_hosts_ok: true,
        },
      }),
    );
    const items = wrapper.findAll("ul.prereq li").map((li) => li.text());
    expect(items).toHaveLength(4);
    expect(items[0]).toContain("✓");
    expect(items[1]).toContain("✕");
    expect(items[3]).toContain("本機未否決");
    // The egress check is refreshed every five minutes, so the value is stale by
    // construction and must be shown with its age.
    expect(wrapper.text()).toContain("的回報");
    expect(wrapper.text()).toContain("agentd doctor");
  });

  it("says a node that has never reported may need its daemon upgraded", async () => {
    const wrapper = await render(
      loaded({ reported_at: null, prereq_ok: false }),
    );
    expect(wrapper.text()).toContain("尚未回報埠轉發能力");
    expect(wrapper.text()).toContain("升級");
  });

  it("states that a local veto cannot be overridden by the platform", async () => {
    const wrapper = await render(
      loaded({ local_veto: true, enabled: false, blocked_by: "node_local" }),
    );
    expect(wrapper.text()).toContain("tunnel.enabled: false");
    expect(wrapper.text()).toContain("平台無法覆寫");
  });

  it.each([
    [{}, "由整合設定的全域範圍決定"],
    [{ node_allowed_ports: ["3000-3500"] }, "由此節點的平台設定限制"],
    [{ local_allowed_ports: ["3100-3200"] }, "本機設定"],
  ])(
    "names which layer narrowed the port range (%#)",
    async (overrides, expected) => {
      // Three layers mean "port 3000 is not allowed" has three possible causes and the reader
      // can only change one of them. Without naming the layer they try each in turn.
      const wrapper = await render(
        loaded(overrides as Partial<NodeTunnelPolicy>),
      );
      expect(wrapper.text()).toContain(expected as string);
    },
  );

  it("refuses a per-node port range below the floor without asking the server", async () => {
    const api = loaded({}, [], { updateNodeTunnelSettings: vi.fn() });
    const wrapper = await render(api);
    await wrapper.find('input[type="text"]').setValue("80-90");
    await flushPromises();
    expect(wrapper.text()).toContain("1024 以下的 port 永不轉發");
    await button(wrapper, "儲存設定")!.trigger("click");
    expect(api.updateNodeTunnelSettings).not.toHaveBeenCalled();
  });

  it("asks for the public acknowledgement every time that mode is chosen", async () => {
    const api = loaded({}, [], { createTunnel: vi.fn() });
    const wrapper = await render(api);
    await button(wrapper, "建立隧道")!.trigger("click");
    await wrapper.findAll("select")[0].setValue("public");
    await flushPromises();
    expect(wrapper.text()).toContain("任何拿到網址的人都能存取");
    expect(
      wrapper.find('button[type="submit"]').attributes("disabled"),
    ).toBeDefined();
  });

  it("shows the four third-party statements when the server asks for them", async () => {
    // The 422 is the server asking a question, not an error to render as one (D14).
    const createTunnel = vi
      .fn()
      .mockRejectedValueOnce(
        new ApiError(
          "INVALID_ARGUMENT",
          "Traffic to this port will pass through the third-party tunnel provider.",
          422,
          "01KREQ",
          { requires_acknowledgement: "third_party" },
        ),
      )
      .mockResolvedValueOnce(detail());
    const wrapper = await render(loaded({}, [], { createTunnel }));
    await button(wrapper, "建立隧道")!.trigger("click");
    await wrapper.find('form input[type="number"]').setValue(5173);
    await wrapper.find("form").trigger("submit");
    await flushPromises();

    expect(wrapper.text()).toContain("這是你在這台節點上的第一條隧道");
    expect(wrapper.text()).toContain("Cookie 與 Authorization");
    const checks = wrapper.findAll('input[type="checkbox"]');
    await checks[checks.length - 1].setValue(true);
    await wrapper.find("form").trigger("submit");
    await flushPromises();
    expect(createTunnel).toHaveBeenCalledTimes(2);
    expect(createTunnel.mock.calls[1][0].acknowledge_third_party).toBe(true);
  });

  it("shows the one-time password in the creation dialog and nowhere else", async () => {
    const created = detail();
    const wrapper = await render(
      loaded({}, [tunnel()], {
        createTunnel: vi.fn().mockResolvedValue(created),
      }),
    );
    // The list — rendered before anything is created — has no password and no copy control
    // for one, because only the hash is stored.
    expect(wrapper.html()).not.toContain(created.basic_auth_password!);
    expect(wrapper.find("table").text()).not.toContain("複製帳密");

    await button(wrapper, "建立隧道")!.trigger("click");
    await wrapper.find('form input[type="number"]').setValue(5173);
    await wrapper.find("form").trigger("submit");
    await flushPromises();

    const dialog = wrapper.find('[role="dialog"]');
    expect(dialog.text()).toContain(created.basic_auth_password!);
    expect(dialog.text()).toContain("只會顯示這一次");
    expect(
      dialog.findAll("button").some((b) => b.text().includes("複製帳密")),
    ).toBe(true);
  });

  it("warns that rotating the password may change the URL", async () => {
    // The user's model is "edit the password"; the implementation closes and reopens the
    // tunnel. Not saying so leaves somebody handing out a dead link.
    const wrapper = await render(loaded({}, [tunnel()]));
    await button(wrapper, "換密碼")!.trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("網址可能改變");
  });

  it("opens the URL in a new window with noopener and says it may change", async () => {
    const wrapper = await render(loaded({}, [tunnel()]));
    const link = wrapper.find("table a");
    expect(link.attributes("target")).toBe("_blank");
    expect(link.attributes("rel")).toBe("noopener noreferrer");
    expect(wrapper.text()).toContain("網址由服務商指派，可能變更");
    expect(wrapper.text()).toContain("已變更 1 次");
  });

  it("keeps the platform TTL and the provider's own deadline in separate columns", async () => {
    const wrapper = await render(loaded({}, [tunnel()]));
    const headers = wrapper.findAll("th").map((th) => th.text());
    expect(headers).toContain("平台到期");
    expect(headers).toContain("服務商時限");
  });

  it("explains a failed tunnel through the shared error catalog", async () => {
    const wrapper = await render(
      loaded({}, [
        tunnel({
          state: "failed",
          state_error_code: "TUNNEL_PROVIDER_UNTRUSTED",
        }),
      ]),
    );
    expect(wrapper.text()).toContain("TUNNEL_PROVIDER_UNTRUSTED");
    // The wording comes from utils/errorCatalog.ts rather than being written here twice.
    expect(wrapper.text()).toContain("不要以停用金鑰驗證的方式繞過");
  });

  it("explains the integration being off instead of showing an error", async () => {
    const wrapper = await render({
      getNodeTunnelPolicy: vi
        .fn()
        .mockRejectedValue(
          new ApiError("TUNNEL_INTEGRATION_DISABLED", "not enabled", 404),
        ),
      listTunnels: vi.fn().mockResolvedValue([]),
    });
    expect(wrapper.text()).toContain("埠轉發整合尚未啟用");
    // A Developer holds no `integration.manage`, so they are told who can turn it on rather
    // than given a link that answers 403.
    expect(wrapper.text()).toContain("請聯繫管理員");
    expect(wrapper.find("form").exists()).toBe(false);
  });
});
