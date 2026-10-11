import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { SessionDetail, SessionSummary } from "../api/dto";
import * as auth from "./auth";
import { useSessionsStore } from "./sessions";

function held<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}
const row = (
  id: string,
  status: SessionDetail["status"] = "running",
  canTerminate = true,
): SessionDetail => ({
  id,
  node_id: "node",
  user_id: "owner",
  name: id,
  runtime: "claude",
  workspace: "/workspace",
  status,
  rows: 24,
  columns: 80,
  pid: 12,
  started_at: "2026-10-11T00:00:00Z",
  last_activity_at: "2026-10-11T00:00:00Z",
  ended_at: status === "terminated" ? "2026-10-11T00:01:00Z" : null,
  created_at: "2026-10-11T00:00:00Z",
  exit_code: status === "terminated" ? 0 : null,
  error_message: null,
  capabilities: {
    can_view: true,
    can_write: canTerminate,
    can_takeover: canTerminate,
    can_terminate: canTerminate,
    can_browse_files: true,
    can_upload_files: canTerminate,
    can_open_shell: status !== "terminated" && canTerminate,
    can_preview_binary: true,
  },
});
beforeEach(() => setActivePinia(createPinia()));
afterEach(() => vi.restoreAllMocks());

describe("T2 closure2 active redesign probes", () => {
  it("preserves fresher already-terminated return-to-A detail capabilities", async () => {
    const returning = held<SessionDetail>();
    vi.spyOn(auth, "api").mockReturnValue({
      getSession: () => returning.promise,
      terminateSession: async () => row("A", "terminated", true),
    } as never);
    const store = useSessionsStore();
    store.current = row("B");
    // The GET starts in the browser before the POST response arrives, but
    // reaches the server after commit / role contraction. The same identity
    // retains session.view; its fresh DTO is already ended, not running.
    const load = store.fetchSession("A");
    await store.terminate("A");
    const fresh = row("A", "terminated", false);
    returning.resolve(fresh);
    await load;
    expect(store.current?.status).toBe("terminated");
    expect(store.current?.capabilities.can_terminate).toBe(false);
    expect(store.current).toEqual(fresh);
  });

  it("preserves fresher already-terminated list capabilities in its returned payload", async () => {
    const listing = held<SessionSummary[]>();
    vi.spyOn(auth, "api").mockReturnValue({
      listSessions: () => listing.promise,
      terminateSession: async () => row("A", "terminated", true),
    } as never);
    const store = useSessionsStore();
    const load = store.fetchList();
    await store.terminate("A");
    const fresh = row("A", "terminated", false);
    listing.resolve([row("B"), fresh]);
    const result = await load;
    expect(result[1].capabilities.can_terminate).toBe(false);
  });

  it("does not keep a newly terminated row in a running-only result", async () => {
    const listing = held<SessionSummary[]>();
    vi.spyOn(auth, "api").mockReturnValue({
      listSessions: vi
        .fn()
        .mockReturnValueOnce(listing.promise)
        .mockResolvedValue([row("B")]),
      terminateSession: async () => row("A", "terminated"),
    } as never);
    const store = useSessionsStore();
    const load = store.fetchList({ status: "running" });
    await store.terminate("A");
    listing.resolve([row("B"), row("A")]);
    const result = await load;
    expect(result.every((item) => item.status === "running")).toBe(true);
    expect(store.list).toEqual([row("B")]);
  });

  it("leaves a legitimately current B fetch intact while terminating A", async () => {
    const detail = held<SessionDetail>();
    vi.spyOn(auth, "api").mockReturnValue({
      getSession: () => detail.promise,
      terminateSession: async () => row("A", "terminated"),
    } as never);
    const store = useSessionsStore();
    store.current = row("A");
    const load = store.fetchSession("B");
    await store.terminate("A");
    detail.resolve(row("B"));
    expect(await load).toEqual(row("B"));
    expect(store.current).toEqual(row("B"));
  });

  it("does not mix mutation refreshes between independent store instances", async () => {
    const first = useSessionsStore();
    setActivePinia(createPinia());
    const second = useSessionsStore();
    const secondRead = held<SessionDetail>();
    vi.spyOn(auth, "api").mockReturnValue({
      getSession: () => secondRead.promise,
      terminateSession: async () => row("A", "terminated"),
    } as never);
    const load = second.fetchSession("A");
    await first.terminate("A");
    secondRead.resolve(row("A"));
    expect(await load).toEqual(row("A"));
    expect(second.current?.status).toBe("running");
  });

  it("reset isolates old termination, list, detail and create replies from the new epoch", async () => {
    const detail = held<SessionDetail>();
    const listing = held<SessionSummary[]>();
    const creating = held<SessionDetail>();
    const ending = held<SessionDetail>();
    vi.spyOn(auth, "api").mockReturnValue({
      getSession: vi
        .fn()
        .mockReturnValueOnce(detail.promise)
        .mockResolvedValue(row("A")),
      listSessions: vi
        .fn()
        .mockReturnValueOnce(listing.promise)
        .mockResolvedValue([row("A")]),
      createSession: () => creating.promise,
      terminateSession: () => ending.promise,
    } as never);
    const store = useSessionsStore();
    const loads = [
      store.fetchSession("A"),
      store.fetchList(),
      store.create({} as never),
      store.terminate("A"),
    ];
    store.reset();
    await store.fetchSession("A");
    await store.fetchList();
    ending.resolve(row("A", "terminated"));
    detail.resolve(row("A", "terminated"));
    listing.resolve([row("A", "terminated")]);
    creating.resolve(row("old-created"));
    await Promise.all(loads);
    expect(store.current).toEqual(row("A"));
    expect(store.list).toEqual([row("A")]);
    expect(await store.fetchSession("A")).toEqual(row("A"));
    expect(await store.fetchList()).toEqual([row("A")]);
  });

  it("isolates accepted mutation refreshes from new same-id reads and old replies", async () => {
    const old = held<SessionDetail>();
    vi.spyOn(auth, "api").mockReturnValue({
      getSession: vi
        .fn()
        .mockReturnValueOnce(old.promise)
        .mockResolvedValue(row("A")),
      terminateSession: async () => row("A", "terminated"),
    } as never);
    const store = useSessionsStore();
    const load = store.fetchSession("A");
    await store.terminate("A");
    store.reset();
    await store.fetchSession("A");
    old.resolve(row("A", "terminated"));
    await load;
    expect(store.current).toEqual(row("A"));
  });

  it("preserves latest server ordering and missing rows across multiple pending lists", async () => {
    const old = held<SessionSummary[]>();
    const latest = held<SessionSummary[]>();
    vi.spyOn(auth, "api").mockReturnValue({
      listSessions: vi
        .fn()
        .mockReturnValueOnce(old.promise)
        .mockReturnValueOnce(latest.promise)
        .mockResolvedValue([row("C"), row("B")]),
      terminateSession: async () => row("A", "terminated"),
    } as never);
    const store = useSessionsStore();
    const first = store.fetchList({ node_id: "node" });
    const second = store.fetchList({ node_id: "node" });
    await store.terminate("A");
    latest.resolve([row("C"), row("B")]);
    await second;
    old.resolve([row("A"), row("B"), row("C")]);
    await first;
    expect(store.list).toEqual([row("C"), row("B")]);
  });

  it("trusts fresh role capabilities on reads started after termination", async () => {
    vi.spyOn(auth, "api").mockReturnValue({
      getSession: async () => row("A", "terminated", false),
      listSessions: async () => [row("A", "terminated", false)],
      terminateSession: async () => row("A", "terminated", true),
    } as never);
    const store = useSessionsStore();
    await store.terminate("A");
    await store.fetchSession("A");
    await store.fetchList();
    expect(store.current?.capabilities.can_terminate).toBe(false);
    expect(store.list[0].capabilities.can_terminate).toBe(false);
  });
});
