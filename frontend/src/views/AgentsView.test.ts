import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AgentRunner } from "../api/dto";
import AgentsView from "./AgentsView.vue";

/**
 * Exit condition 21: **three states, three sentences**, and none of the first two says
 * 「離線」.
 *
 * The reason this needs a test rather than a glance is that all three look the same on
 * the wire. A runner with no capacity reports it by *not polling* — there is no
 * "capacity: 0" frame — so from Central a full runner, a runner with nowhere to put a
 * checkout and a machine somebody unplugged are identical silences. If the page reads
 * only the connection state, a perfectly healthy node that has filled its disk shows as
 * offline and the person on call goes looking for a network fault.
 *
 * So each state is asserted by the words it puts on screen, not by a CSS class: the copy
 * *is* the feature here.
 */

const { state } = vi.hoisted(() => ({
  state: { list: [] as AgentRunner[], listError: null as unknown },
}));

vi.mock("../stores/auth", () => ({
  useAuthStore: () => ({ hasPermission: () => true }),
  api: () => ({
    listAgents: async () => {
      if (state.listError) throw state.listError;
      return state.list;
    },
    updateAgent: async () => state.list[0],
  }),
}));

function runner(overrides: Partial<AgentRunner> = {}): AgentRunner {
  return {
    id: "r-1",
    node_id: "n-1",
    node_name: "dev-vm-01",
    name: "dev-runner-01",
    runtimes: ["claude"],
    labels: [],
    max_concurrent: 2,
    max_waiting: 5,
    enabled: true,
    dedicated: true,
    online: true,
    active_runs: 0,
    waiting_runs: 0,
    assigned_cards: 0,
    blocked_reason: null,
    disk_used_bytes: null,
    disk_quota_bytes: null,
    registered_at: "2026-08-11T09:00:00Z",
    last_registered_at: null,
    ...overrides,
  };
}

async function render() {
  const wrapper = mount(AgentsView, {
    global: { stubs: { AppLayout: { template: "<main><slot /></main>" } } },
  });
  await flushPromises();
  return wrapper;
}

describe("AgentsView availability", () => {
  beforeEach(() => {
    state.list = [];
    state.listError = null;
  });

  it("says 線上 for a runner that is polling", async () => {
    state.list = [runner()];
    const wrapper = await render();
    expect(wrapper.get(".status").text()).toBe("線上");
  });

  it("says 離線 only when the node is really gone", async () => {
    state.list = [runner({ online: false, blocked_reason: "at_capacity" })];
    const wrapper = await render();
    // `online: false` wins: a machine that is not connected cannot be "full", and
    // reporting the last thing it said before it vanished would be a stale fact.
    expect(wrapper.get(".status").text()).toBe("離線");
  });

  it("says 滿載 with the occupancy rather than 離線", async () => {
    state.list = [
      runner({
        blocked_reason: "at_capacity",
        active_runs: 2,
        max_concurrent: 2,
      }),
    ];
    const wrapper = await render();
    const label = wrapper.get(".status").text();
    expect(label).toContain("滿載");
    expect(label).toContain("2 / 2");
    expect(label).not.toContain("離線");
  });

  it("names the disk, with both figures, rather than 離線", async () => {
    state.list = [
      runner({
        blocked_reason: "disk_quota",
        disk_used_bytes: 5153960755,
        disk_quota_bytes: 5368709120,
      }),
    ];
    const wrapper = await render();
    const label = wrapper.get(".status").text();
    expect(label).toContain("磁碟用盡");
    // Both numbers, because "4.8 GB" alone does not say whether that is a lot.
    expect(label).toContain("4.8 GB");
    expect(label).toContain("5.0 GB");
    expect(label).not.toContain("離線");
  });

  it("distinguishes the waiting limit from the execution limit", async () => {
    // The fourth reason, and a different action for the reader: these runs hold no
    // process, so the fix is answering a question, not adding a machine.
    state.list = [
      runner({
        blocked_reason: "waiting_limit",
        waiting_runs: 5,
        max_waiting: 5,
      }),
    ];
    const wrapper = await render();
    const label = wrapper.get(".status").text();
    expect(label).toContain("等待回覆");
    expect(label).toContain("5 / 5");
  });

  it("does not invent a disk figure the runner never reported", async () => {
    state.list = [runner({ disk_used_bytes: null, disk_quota_bytes: null })];
    const wrapper = await render();
    // "0 B / 0 B" would read as an empty disk with no quota, which is the opposite of
    // "this was never measured".
    expect(wrapper.text()).toContain("用量未回報");
    expect(wrapper.text()).not.toContain("0 B");
  });

  it("shows how many cards are pinned to the runner", async () => {
    // Separate from occupancy: this runner is idle and over-subscribed at once, and a
    // page showing only 執行中 would call it free.
    state.list = [runner({ assigned_cards: 7, active_runs: 0 })];
    const wrapper = await render();
    const facts = wrapper.get(".facts").text();
    expect(facts).toContain("指定給此 Agent 的卡片");
    expect(facts).toContain("7");
  });
});
