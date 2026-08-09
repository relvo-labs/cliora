import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it } from "vitest";

import type { SessionDetail, SessionSummary } from "../api/dto";
import { useSessionsStore } from "./sessions";

function summary(id: string, nodeId: string): SessionSummary {
  return { id, node_id: nodeId } as SessionSummary;
}

function detail(id: string, nodeId: string): SessionDetail {
  return { id, node_id: nodeId } as SessionDetail;
}

describe("sessions store", () => {
  beforeEach(() => setActivePinia(createPinia()));

  it("drops cached sessions when their node is removed", () => {
    const store = useSessionsStore();
    store.list = [summary("removed", "node-a"), summary("kept", "node-b")];
    store.current = detail("removed", "node-a");

    store.removeForNode("node-a");

    expect(store.list.map((session) => session.id)).toEqual(["kept"]);
    expect(store.current).toBeNull();
  });

  it("keeps an unrelated current session", () => {
    const store = useSessionsStore();
    store.current = detail("kept", "node-b");

    store.removeForNode("node-a");

    expect(store.current?.id).toBe("kept");
  });
});
