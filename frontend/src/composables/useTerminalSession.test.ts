import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { effectScope } from "vue";

// --- xterm mocks: record instances so we can assert single init / dispose ---
const { terminals } = vi.hoisted(() => ({
  terminals: [] as Array<
    Record<string, ReturnType<typeof vi.fn>> & { rows: number; cols: number }
  >,
}));

vi.mock("@xterm/xterm", () => {
  class MockTerminal {
    rows = 24;
    cols = 80;
    loadAddon = vi.fn();
    open = vi.fn();
    focus = vi.fn();
    write = vi.fn();
    dispose = vi.fn();
    onData = vi.fn();
    onBinary = vi.fn();
    constructor() {
      terminals.push(this as never);
    }
  }
  return { Terminal: MockTerminal };
});
vi.mock("@xterm/addon-fit", () => ({
  FitAddon: vi.fn(() => ({ fit: vi.fn() })),
}));
vi.mock("@xterm/addon-search", () => ({ SearchAddon: vi.fn(() => ({})) }));
vi.mock("@xterm/addon-web-links", () => ({ WebLinksAddon: vi.fn(() => ({})) }));

// --- WebSocket mock: capture instances, drive lifecycle by hand ---
const sockets: MockSocket[] = [];

class MockSocket {
  static readonly OPEN = 1;
  static readonly CLOSED = 3;
  readyState = 0;
  binaryType = "blob";
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: unknown }) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;
  sent: unknown[] = [];
  closed = false;
  constructor(public url: string) {
    sockets.push(this);
  }
  send(data: unknown) {
    this.sent.push(data);
  }
  close() {
    this.closed = true;
    this.readyState = MockSocket.CLOSED;
    this.onclose?.();
  }
  open() {
    this.readyState = MockSocket.OPEN;
    this.onopen?.();
  }
  emit(data: unknown) {
    this.onmessage?.({ data });
  }
}

const observers: MockObserver[] = [];
class MockObserver {
  observe = vi.fn();
  disconnect = vi.fn();
  constructor(public cb: () => void) {
    observers.push(this);
  }
}

import { useTerminalSession } from "./useTerminalSession";

let scope: ReturnType<typeof effectScope>;

function newSession() {
  let api!: ReturnType<typeof useTerminalSession>;
  scope.run(() => {
    api = useTerminalSession(async () => "ticket-123");
  });
  return api;
}

beforeEach(() => {
  vi.stubGlobal("WebSocket", MockSocket);
  vi.stubGlobal("ResizeObserver", MockObserver);
  vi.stubGlobal("location", { protocol: "http:", host: "localhost:5173" });
  vi.useFakeTimers();
  terminals.length = 0;
  sockets.length = 0;
  observers.length = 0;
  scope = effectScope();
});

afterEach(() => {
  scope.stop();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const SESSION = "00000000-0000-4000-8000-000000000002";

// Make it writer so input/resize paths engage.
function makeWriter(socket: MockSocket) {
  socket.emit(
    JSON.stringify({ type: "terminal.role", payload: { role: "writer" } }),
  );
}

describe("useTerminalSession", () => {
  it("initializes exactly one Terminal with three addons", () => {
    const s = newSession();
    s.mount(document.createElement("div"));
    expect(terminals).toHaveLength(1);
    expect(terminals[0].loadAddon).toHaveBeenCalledTimes(3);
    expect(terminals[0].open).toHaveBeenCalledOnce();
    expect(observers).toHaveLength(1);
  });

  it("mount is idempotent (no duplicate Terminal)", () => {
    const s = newSession();
    const el = document.createElement("div");
    s.mount(el);
    s.mount(el);
    expect(terminals).toHaveLength(1);
  });

  it("connects to the authenticated session WS with a ws-ticket", async () => {
    const s = newSession();
    s.mount(document.createElement("div"));
    await s.connect(SESSION);
    expect(sockets).toHaveLength(1);
    expect(sockets[0].url).toContain(`/ws/sessions/${SESSION}/terminal`);
    expect(sockets[0].url).toContain("ticket=ticket-123");
    sockets[0].open();
    expect(s.status.value).toBe("connected");
    // On open it sends a resize (server auto-attaches; no session.attach frame).
    const first = JSON.parse(sockets[0].sent[0] as string);
    expect(first.type).toBe("terminal.resize");
  });

  it("tracks writer/viewer role from terminal.role", async () => {
    const s = newSession();
    s.mount(document.createElement("div"));
    await s.connect(SESSION);
    sockets[0].open();
    expect(s.role.value).toBe("viewer");
    makeWriter(sockets[0]);
    expect(s.role.value).toBe("writer");
  });

  it("reconnects on unexpected close using the bounded schedule", async () => {
    const s = newSession();
    s.mount(document.createElement("div"));
    await s.connect(SESSION);
    sockets[0].open();
    sockets[0].close();
    expect(s.status.value).toBe("reconnecting");
    expect(sockets).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(1000);
    expect(sockets).toHaveLength(2);
  });

  it("does not reconnect after exit", async () => {
    const s = newSession();
    s.mount(document.createElement("div"));
    await s.connect(SESSION);
    sockets[0].open();
    sockets[0].emit(
      JSON.stringify({ type: "terminal.exited", payload: { code: 0 } }),
    );
    expect(s.status.value).toBe("exited");
    await vi.advanceTimersByTimeAsync(60000);
    expect(sockets).toHaveLength(1);
  });

  it("writes binary frames to the terminal, never control text", async () => {
    const s = newSession();
    s.mount(document.createElement("div"));
    await s.connect(SESSION);
    sockets[0].open();
    sockets[0].emit(new TextEncoder().encode("hi").buffer);
    expect(terminals[0].write).toHaveBeenCalledOnce();
  });

  it("dispose is idempotent and releases every resource", async () => {
    const s = newSession();
    s.mount(document.createElement("div"));
    await s.connect(SESSION);
    sockets[0].open();
    s.dispose();
    s.dispose();
    expect(terminals[0].dispose).toHaveBeenCalledOnce();
    expect(observers[0].disconnect).toHaveBeenCalledOnce();
    expect(sockets[0].closed).toBe(true);
  });

  it("leak gate: 20 mount/dispose cycles leave no live socket, observer, or timer", async () => {
    for (let i = 0; i < 20; i += 1) {
      const s = newSession();
      s.mount(document.createElement("div"));
      await s.connect(SESSION);
      sockets[sockets.length - 1].open();
      s.dispose();
    }
    expect(sockets.every((socket) => socket.closed)).toBe(true);
    expect(
      observers.every(
        (observer) => observer.disconnect.mock.calls.length === 1,
      ),
    ).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
  });
});
