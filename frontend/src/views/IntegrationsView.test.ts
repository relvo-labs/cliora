import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createRouter, createWebHistory, type Router } from "vue-router";

import { ApiError } from "../api/client";
import type { TunnelIntegration } from "../api/dto";
import * as auth from "../stores/auth";
import { useAuthStore } from "../stores/auth";
import IntegrationsView from "./IntegrationsView.vue";

// A token shaped like a real one, so the "never rendered" assertions have something
// searchable to look for.
const TOKEN = "AbCd1234EfGh5678";

function integration(
  overrides: Partial<TunnelIntegration> = {},
): TunnelIntegration {
  return {
    enabled: false,
    provider: "pinggy",
    plan_tier: "free",
    credential: {
      configured: false,
      fingerprint: null,
      updated_at: null,
      updated_by: null,
    },
    concurrent_budget: 8,
    default_protection: "basic",
    default_ttl_seconds: 14400,
    allowed_ports: null,
    acknowledged_at: null,
    secret_key_available: true,
    active_tunnel_count: 0,
    ...overrides,
  };
}

function testRouter(): Router {
  return createRouter({
    history: createWebHistory(),
    routes: [
      {
        path: "/settings/integrations",
        name: "integrations",
        component: IntegrationsView,
      },
    ],
  });
}

async function render(api: Record<string, unknown>) {
  vi.spyOn(auth, "api").mockReturnValue(
    api as unknown as ReturnType<typeof auth.api>,
  );
  const router = testRouter();
  await router.push("/settings/integrations");
  await router.isReady();
  const wrapper = mount(IntegrationsView, {
    global: {
      plugins: [router],
      stubs: { AppLayout: { template: "<div><slot /></div>" } },
    },
  });
  await flushPromises();
  return wrapper;
}

describe("IntegrationsView", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    useAuthStore().user = {
      id: "u",
      username: "admin",
      display_name: "Admin",
      role: "Admin",
      permissions: ["integration.manage", "tunnel.view", "tunnel.manage"],
      features: [],
    };
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("replaces the whole form when the deployment has no encryption key", async () => {
    // Not merely disabled: an administrator must not be invited to type a credential that
    // cannot be stored, and the message has to name what a deployment admin must set.
    const wrapper = await render({
      getTunnelIntegration: vi
        .fn()
        .mockResolvedValue(integration({ secret_key_available: false })),
    });
    expect(wrapper.text()).toContain("未設定憑證加密金鑰");
    expect(wrapper.text()).toContain("CLIORA_SECRET_ENCRYPTION_KEY");
    expect(wrapper.find('input[type="password"]').exists()).toBe(false);
    expect(wrapper.text()).not.toContain("啟用埠轉發");
  });

  it("shows only the fingerprint for a stored credential, never the token", async () => {
    const wrapper = await render({
      getTunnelIntegration: vi.fn().mockResolvedValue(
        integration({
          credential: {
            configured: true,
            fingerprint: "ab12cd34",
            updated_at: "2026-07-29T09:00:00Z",
            updated_by: "u",
          },
        }),
      ),
    });
    expect(wrapper.text()).toContain("已設定");
    expect(wrapper.text()).toContain("ab12cd34");
    // The whole rendered document, markup included: there is no attribute, title or hidden
    // node the value could be sitting in either.
    expect(wrapper.html()).not.toContain(TOKEN);
    expect(wrapper.html()).not.toContain(TOKEN.slice(0, 6));
    // No reveal affordance, because there is nothing behind it: the only credential input is
    // a write-only password field, and no control offers to show what was stored.
    const credentialInputs = wrapper.findAll('input[autocomplete="off"]');
    expect(credentialInputs).toHaveLength(1);
    expect(credentialInputs[0].attributes("type")).toBe("password");
    expect(wrapper.findAll("button").map((b) => b.text())).not.toContain(
      "顯示",
    );
  });

  it("clears the input after saving so the token does not stay bound to the DOM", async () => {
    const setTunnelCredential = vi.fn().mockResolvedValue(
      integration({
        credential: {
          configured: true,
          fingerprint: "ab12cd34",
          updated_at: "2026-07-29T09:00:00Z",
          updated_by: "u",
        },
      }),
    );
    const wrapper = await render({
      getTunnelIntegration: vi.fn().mockResolvedValue(integration()),
      setTunnelCredential,
    });
    const input = wrapper.find('input[type="password"]');
    await input.setValue(TOKEN);
    await wrapper
      .findAll("button")
      .find((b) => b.text() === "儲存憑證")!
      .trigger("click");
    await flushPromises();
    expect(setTunnelCredential).toHaveBeenCalledWith({
      token: TOKEN,
      plan_tier: "free",
    });
    expect((input.element as HTMLInputElement).value).toBe("");
    expect(wrapper.html()).not.toContain(TOKEN);
  });

  it("refuses a token outside the permitted character set before sending it", async () => {
    const setTunnelCredential = vi.fn();
    const wrapper = await render({
      getTunnelIntegration: vi.fn().mockResolvedValue(integration()),
      setTunnelCredential,
    });
    await wrapper.find('input[type="password"]').setValue("abc+tcp@evil.host");
    await flushPromises();
    expect(wrapper.text()).toContain("只接受英數字");
    const save = wrapper
      .findAll("button")
      .find((b) => b.text() === "儲存憑證")!;
    expect(save.attributes("disabled")).toBeDefined();
    await save.trigger("click");
    expect(setTunnelCredential).not.toHaveBeenCalled();
  });

  it("blocks the paid tier while no credential is stored", async () => {
    const wrapper = await render({
      getTunnelIntegration: vi.fn().mockResolvedValue(integration()),
    });
    const select = wrapper.findAll("select")[0];
    await select.setValue("pro");
    await flushPromises();
    expect(wrapper.text()).toContain("選擇付費方案前必須先設定憑證");
  });

  it("requires the four-point acknowledgement before the first enable", async () => {
    const updateTunnelIntegration = vi
      .fn()
      .mockResolvedValue(
        integration({ enabled: true, acknowledged_at: "now" }),
      );
    const wrapper = await render({
      getTunnelIntegration: vi.fn().mockResolvedValue(integration()),
      updateTunnelIntegration,
    });
    expect(wrapper.text()).toContain("服務商可以看到未加密的 HTTP 內容");
    expect(wrapper.text()).toContain("訂閱與帳號由你自己持有");
    const enable = wrapper
      .findAll("button")
      .find((b) => b.text() === "啟用埠轉發")!;
    expect(enable.attributes("disabled")).toBeDefined();

    await wrapper.find('input[type="checkbox"]').setValue(true);
    await enable.trigger("click");
    await flushPromises();
    expect(updateTunnelIntegration).toHaveBeenCalledWith({
      enabled: true,
      acknowledge: true,
    });
  });

  it("does not ask again once the acknowledgement is on record", async () => {
    const wrapper = await render({
      getTunnelIntegration: vi
        .fn()
        .mockResolvedValue(
          integration({ acknowledged_at: "2026-07-01T00:00:00Z" }),
        ),
    });
    expect(wrapper.text()).not.toContain("啟用前請確認");
    expect(
      wrapper
        .findAll("button")
        .find((b) => b.text() === "啟用埠轉發")!
        .attributes("disabled"),
    ).toBeUndefined();
  });

  it("says how many tunnels keep running when disabling", async () => {
    // Disabling stops new tunnels and closes nothing (04 §0.2). A switch that can half-fail
    // must not look like a switch, so the count is in the confirmation.
    const wrapper = await render({
      getTunnelIntegration: vi.fn().mockResolvedValue(
        integration({
          enabled: true,
          acknowledged_at: "x",
          active_tunnel_count: 3,
        }),
      ),
      listTunnels: vi.fn().mockResolvedValue([]),
    });
    await wrapper
      .findAll("button")
      .find((b) => b.text() === "停用埠轉發")!
      .trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("3 條既有隧道會繼續執行至到期");
  });

  it("offers to close the leftovers as a separate action once disabled", async () => {
    const wrapper = await render({
      getTunnelIntegration: vi
        .fn()
        .mockResolvedValue(
          integration({ acknowledged_at: "x", active_tunnel_count: 2 }),
        ),
      listTunnels: vi.fn().mockResolvedValue([]),
    });
    expect(wrapper.text()).toContain("2 條既有隧道在執行");
    expect(
      wrapper.findAll("button").some((b) => b.text() === "一併關閉全部"),
    ).toBe(true);
  });

  it("renders the server's forbidden state rather than a client-side guard", async () => {
    const wrapper = await render({
      getTunnelIntegration: vi
        .fn()
        .mockRejectedValue(new ApiError("FORBIDDEN", "nope", 403)),
    });
    expect(wrapper.text()).toContain("integration.manage");
    expect(wrapper.find('input[type="password"]').exists()).toBe(false);
  });
});
