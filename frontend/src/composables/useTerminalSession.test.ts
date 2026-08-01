import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { effectScope } from "vue";

// --- xterm mocks: record instances so we can assert single init / dispose ---
const { terminals } = vi.hoisted(() => ({
  terminals: [] as Array<
    Record<string, ReturnType<typeof vi.fn>> & { rows: number; cols: number }
  >,
}));

const { fits, proposals } = vi.hoisted(() => ({
  fits: [] as ReturnType<typeof vi.fn>[],
  // FitAddon.proposeDimensions() is what "what size should a new session open
  // at" reads; a test can hand back an oversized or degenerate proposal to
  // exercise the clamping and the floor.
  proposals: [] as ReturnType<typeof vi.fn>[],
}));

vi.mock("@xterm/xterm", () => {
  class MockTerminal {
    rows = 24;
    cols = 80;
    // xterm exposes the DOM node it rendered into; the re-mount path moves it.
    element = globalThis.document?.createElement("div");
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
  FitAddon: vi.fn(() => {
    const fit = vi.fn();
    const proposeDimensions = vi.fn(() => ({ rows: 43, cols: 110 }));
    fits.push(fit);
    proposals.push(proposeDimensions);
    return { fit, proposeDimensions };
  }),
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
    // A real WebSocket fires `close` once. Without this guard the composable's
    // own `socket?.close()` on reconnect raises a second close event and silently
    // burns an extra step of the retry schedule.
    if (this.readyState === MockSocket.CLOSED) return;
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
  fits.length = 0;
  proposals.length = 0;
  scope = effectScope();
});

// jsdom reports 0 for every layout box, which is exactly the "hidden host" the
// fit guard refuses to measure. Tests that need a *visible* host say so.
function visible(element: HTMLElement): HTMLElement {
  Object.defineProperty(element, "clientWidth", { value: 800 });
  Object.defineProperty(element, "clientHeight", { value: 600 });
  return element;
}
function host(options: { visible?: boolean } = {}): HTMLElement {
  const element = document.createElement("div");
  return options.visible ? visible(element) : element;
}

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

  // The workspace tabs and the loading/error states both replace the host
  // element. Before WT-02 `mount` returned early on an existing terminal, so
  // xterm kept rendering into a node that was no longer in the document and the
  // only way back was a page reload.
  it("re-mounts into a new host element without rebuilding the terminal", () => {
    const s = newSession();
    const first = host();
    const second = host();
    s.mount(first);
    const rendered = terminals[0].element as unknown as HTMLElement;
    expect(rendered.parentElement).toBe(null);

    s.mount(second);

    expect(terminals).toHaveLength(1);
    expect(terminals[0].open).toHaveBeenCalledOnce();
    expect(rendered.parentElement).toBe(second);
    // The old container is no longer observed; the new one is.
    expect(observers[0].disconnect).toHaveBeenCalledOnce();
    expect(observers[1].observe).toHaveBeenCalledWith(second);
  });

  it("does not measure or resize while the host is hidden", async () => {
    const s = newSession();
    s.mount(host()); // jsdom: clientWidth/Height are 0 → hidden
    await s.connect(SESSION);
    sockets[0].open();
    const sentOnOpen = sockets[0].sent.length;

    observers[0].cb();
    await vi.advanceTimersByTimeAsync(100);

    expect(fits[0]).not.toHaveBeenCalled();
    expect(sockets[0].sent).toHaveLength(sentOnOpen);
  });

  it("fit() resizes once the host is visible, and de-duplicates", async () => {
    const s = newSession();
    const element = host({ visible: true });
    s.mount(element);
    await s.connect(SESSION);
    sockets[0].open();
    const before = sockets[0].sent.length;

    s.fit();
    const afterFirst = sockets[0].sent.length;
    expect(afterFirst).toBe(before + 1);
    expect(JSON.parse(sockets[0].sent[afterFirst - 1] as string).type).toBe(
      "terminal.resize",
    );

    // Same measurement twice must not put a second resize on the wire.
    s.fit();
    expect(sockets[0].sent).toHaveLength(afterFirst);
  });

  // proposeSize(): what a *new* session should be opened at (plan/09 LY-04). The
  // shell used to be created at a hardcoded 24×80 and resized a moment later,
  // which the user sees as the prompt redrawing at a different width.
  it("proposes the measured size for a session that has not started yet", () => {
    const s = newSession();
    s.mount(host({ visible: true }));
    expect(s.proposeSize()).toEqual({ rows: 43, columns: 110 });
  });

  it("proposes nothing while the host is hidden, rather than guessing", () => {
    const s = newSession();
    s.mount(host()); // jsdom: 0×0
    expect(s.proposeSize()).toBeNull();
    // Not even asked: a measurement taken from a hidden container is not a
    // measurement, and the caller must fall back to the server default.
    expect(proposals[0]).not.toHaveBeenCalled();
  });

  it("proposes nothing when the measurement is degenerate", () => {
    const s = newSession();
    s.mount(host({ visible: true }));
    proposals[0].mockReturnValueOnce({ rows: 1, cols: 80 });
    expect(s.proposeSize()).toBeNull();
  });

  // A wide enough window really can propose more than the contract's 500
  // columns, and Central answers an out-of-range size with a 422 — the terminal
  // would just fail to open.
  it("clamps the proposal to the wire contract's bounds", () => {
    const s = newSession();
    s.mount(host({ visible: true }));
    proposals[0].mockReturnValueOnce({ rows: 900, cols: 620 });
    expect(s.proposeSize()).toEqual({ rows: 300, columns: 500 });
  });

  it("mount after dispose creates nothing", () => {
    const s = newSession();
    s.mount(host());
    s.dispose();
    s.mount(host());
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

  // The test above only proves the first hop. PRD FR-TERM-006 publishes the whole
  // schedule, so each step is walked here: a drift to a flat 1 s retry would look
  // identical from the first hop alone while hammering a struggling Central.
  it("retries on the full 1/2/5/10/30 second schedule", async () => {
    const s = newSession();
    s.mount(document.createElement("div"));
    await s.connect(SESSION);

    // Every attempt fails to come up, so the schedule advances instead of being
    // reset by a successful open. The last value repeats: it is a ceiling, not
    // the end of the list.
    for (const [attempt, delay] of [
      1000, 2000, 5000, 10000, 30000, 30000,
    ].entries()) {
      const before = sockets.length;
      sockets[before - 1].close();
      expect(s.status.value).toBe("reconnecting");

      // Just short of the step: nothing may be dialled yet.
      await vi.advanceTimersByTimeAsync(delay - 1);
      expect(
        sockets,
        `attempt ${attempt + 1} dialled before its ${delay}ms step`,
      ).toHaveLength(before);
      await vi.advanceTimersByTimeAsync(1);
      expect(
        sockets,
        `attempt ${attempt + 1} should dial at ${delay}ms`,
      ).toHaveLength(before + 1);
    }

    s.dispose();
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
