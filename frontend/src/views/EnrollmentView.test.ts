import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import EnrollmentView from "./EnrollmentView.vue";

vi.mock("../stores/auth", () => ({
  api: () => ({
    listEnrollmentTokens: async () => [],
    createEnrollmentToken: async () => ({
      id: "t-1",
      token: "plaintext-once",
      expires_at: "2026-08-13T12:00:00Z",
      max_uses: 1,
    }),
    revokeEnrollmentToken: async () => undefined,
  }),
  useAuthStore: () => ({
    hasPermission: () => true,
    hasFeature: () => true,
  }),
}));

function render() {
  return mount(EnrollmentView, {
    global: {
      stubs: {
        AppLayout: { template: "<div><slot/></div>" },
        PageHead: true,
        AsyncState: true,
        RouterLink: true,
        ConfirmDialog: true,
      },
    },
  });
}

describe("EnrollmentView", () => {
  beforeEach(() => setActivePinia(createPinia()));

  it("states the authorization boundary inside the form that issues a token", () => {
    // **Compensating control 4 of four** (ADR 0032 §0), and the assertion is about
    // *where* as much as *what*. There is no project-level authorization and there will
    // not be one — enrollment is the boundary — so the person creating one has to be
    // told what they are creating, on the page where they create it. The same sentence
    // on the Agents page would be true and useless: nobody reads it while deciding to
    // enrol a machine.
    const wrapper = render();
    const form = wrapper.find("form");
    expect(form.exists()).toBe(true);

    const text = form.text();
    expect(text).toContain("任何專案");
    expect(text).toContain("機密");
    // It says what the machine *will be able to do*, not what it is asked to do.
    expect(text).toContain("領取");
  });

  it("presents the boundary as a consequence rather than an error", () => {
    // Warning, not danger: enrolling a node is a normal administrative act. Styling it
    // as a failure would teach people to click past it, which is the one outcome this
    // control cannot survive.
    const wrapper = render();
    expect(wrapper.find(".boundary").exists()).toBe(true);
    expect(wrapper.find(".boundary").classes()).not.toContain("error");
  });
});
