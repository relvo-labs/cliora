import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { effectScope } from "vue";

// --- xterm mocks: record instances so we can assert single init / dispose ---
const { terminals } = vi.hoisted(() => ({
  terminals: [] as Array<
    Record<string, ReturnType<typeof vi.fn>> & { rows: number; cols: number }
  >,
}));

const { fits, proposals, nextProposal } = vi.hoisted(() => ({
  fits: [] as ReturnType<typeof vi.fn>[],
  // FitAddon.proposeDimensions() is what "what size should a new session open
  // at" reads; a test can hand back an oversized or degenerate proposal to
  // exercise the clamping and the floor.
  proposals: [] as ReturnType<typeof vi.fn>[],
  // What the *next* FitAddon proposes, for code that builds its own terminal.
  nextProposal: { value: null as null | { rows: number; cols: number } },
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
    // Like xterm's: the grid becomes exactly what was asked for.
    resize = vi.fn((cols: number, rows: number) => {
      this.cols = cols;
      this.rows = rows;
    });
    constructor(public options: Record<string, unknown> = {}) {
      terminals.push(this as never);
    }
  }
  return { Terminal: MockTerminal };
});
vi.mock("@xterm/addon-fit", () => ({
  FitAddon: vi.fn(() => {
    const fit = vi.fn();
    const proposal = nextProposal.value ?? { rows: 43, cols: 110 };
    const proposeDimensions = vi.fn(() => proposal);
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

import { measureTerminalSize, useTerminalSession } from "./useTerminalSession";

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
  nextProposal.value = null;
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
    // The attach settles first (#132); with nothing to measure it sends the
    // grid the terminal already has, as an attach always did — once.
    await vi.advanceTimersByTimeAsync(200);
    const sentOnOpen = sockets[0].sent.length;
    expect(sentOnOpen).toBe(1);

    observers[0].cb();
    await vi.advanceTimersByTimeAsync(1000);

    expect(fits[0]).not.toHaveBeenCalled();
    expect(sockets[0].sent).toHaveLength(sentOnOpen);
  });

  // typeText: how image drop puts a path on the input line (ADR 0024 sec 2).
  // It is the same writer-gated channel as onData, deliberately: the front end
  // types, and no new "platform may write to a terminal" authority is created.
  describe("typeText", () => {
    async function writerSession() {
      const s = newSession();
      s.mount(host({ visible: true }));
      await s.connect(SESSION);
      sockets[0].open();
      makeWriter(sockets[0]);
      return s;
    }

    it("sends the text as raw bytes when the caller is the writer", async () => {
      const s = await writerSession();
      const before = sockets[0].sent.length;

      expect(s.typeText(".cliora/uploads/2026-08-05/01K.png ")).toBe(true);

      const sent = sockets[0].sent[before];
      expect(new TextDecoder().decode(sent as Uint8Array)).toBe(
        ".cliora/uploads/2026-08-05/01K.png ",
      );
    });

    it("sends no Enter, so the user still decides when to submit", async () => {
      const s = await writerSession();
      const before = sockets[0].sent.length;
      s.typeText("path.png ");
      const sent = new TextDecoder().decode(
        sockets[0].sent[before] as Uint8Array,
      );
      expect(sent.endsWith(" ")).toBe(true);
      expect(sent).not.toContain("\r");
      expect(sent).not.toContain("\n");
    });

    it("refuses when the caller is only a viewer", async () => {
      const s = newSession();
      s.mount(host({ visible: true }));
      await s.connect(SESSION);
      sockets[0].open();
      const before = sockets[0].sent.length;

      expect(s.typeText("path.png ")).toBe(false);
      expect(sockets[0].sent).toHaveLength(before);
    });

    it("refuses control characters", async () => {
      const s = await writerSession();
      const before = sockets[0].sent.length;

      // A public "write to the terminal" helper must not be able to submit a
      // line, clear the screen or move the cursor on the user's behalf.
      for (const bad of ["a\r", "a\n", "a\u001b[2J", "a\u0000", "a\u007f"]) {
        expect(s.typeText(bad)).toBe(false);
      }
      expect(sockets[0].sent).toHaveLength(before);
    });

    it("refuses an empty string", async () => {
      const s = await writerSession();
      expect(s.typeText("")).toBe(false);
    });
  });

  it("fit() resizes once the host is visible, and de-duplicates", async () => {
    const s = newSession();
    const element = host({ visible: true });
    s.mount(element);
    await s.connect(SESSION);
    sockets[0].open();
    const before = sockets[0].sent.length;
    // The real FitAddon applies its proposal (43x110 here) to the terminal; the
    // attach above is still settling, so nothing has gone out yet (#132).
    fits[0].mockImplementation(() => {
      terminals[0].rows = 43;
      terminals[0].cols = 110;
    });

    // Settled, not immediate (#127): nothing until the size has held.
    s.fit();
    expect(sockets[0].sent).toHaveLength(before);
    await vi.advanceTimersByTimeAsync(250);
    const afterFirst = sockets[0].sent.length;
    expect(afterFirst).toBe(before + 1);
    expect(JSON.parse(sockets[0].sent[afterFirst - 1] as string).type).toBe(
      "terminal.resize",
    );

    // Same measurement twice must not put a second resize on the wire.
    s.fit();
    await vi.advanceTimersByTimeAsync(250);
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
    // After open it sends a resize (server auto-attaches; no session.attach
    // frame) — once the size has settled (#132).
    await vi.advanceTimersByTimeAsync(200);
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

  // The workspace unbinds its files on this status alone, with no session
  // refetch behind it (#76), so both end-of-session events must produce it.
  it("reports exited on session.stopped as well as terminal.exited", async () => {
    const s = newSession();
    s.mount(document.createElement("div"));
    await s.connect(SESSION);
    sockets[0].open();
    expect(s.status.value).toBe("connected");
    sockets[0].emit(
      JSON.stringify({ type: "session.stopped", payload: { reason: "done" } }),
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

  // #127. The layout behind a phone keyboard, a tab switch or a rotation moves in
  // steps, and every step used to reach the PTY: the 100 ms debounce fired
  // between steps, and `fit()` measured at once. A size goes on the wire only
  // once it has settled, and each settled size goes exactly once.
  describe("settling before a resize is sent (#127)", () => {
    // Makes the mocked FitAddon behave like the real one: `fit()` applies the
    // current proposal to the terminal, and the proposal follows the "host".
    function liveHost(start: { rows: number; cols: number }) {
      let current = { ...start };
      proposals[0].mockImplementation(() => ({ ...current }));
      fits[0].mockImplementation(() => {
        terminals[0].rows = current.rows;
        terminals[0].cols = current.cols;
      });
      return {
        // The host changed size: the ResizeObserver reports it.
        resize(rows: number, cols = current.cols) {
          current = { rows, cols };
          observers[observers.length - 1].cb();
        },
      };
    }
    function resizes(socket: MockSocket): string[] {
      return socket.sent
        .filter((frame): frame is string => typeof frame === "string")
        .map((frame) => JSON.parse(frame))
        .filter((message) => message.type === "terminal.resize")
        .map((message) => `${message.payload.rows}x${message.payload.columns}`);
    }
    async function attached(start = { rows: 18, cols: 40 }) {
      const s = newSession();
      s.mount(host({ visible: true }));
      const layout = liveHost(start);
      await s.connect(SESSION);
      sockets[0].open();
      makeWriter(sockets[0]);
      await vi.advanceTimersByTimeAsync(1000);
      sockets[0].sent.length = 0;
      return { s, layout, socket: sockets[0] };
    }

    it("a host collapsing in steps sends only the size it settles at, once", async () => {
      const { layout, socket } = await attached();

      // A keyboard animating up in steps 120 ms apart — each gap is longer
      // than the 100 ms debounce, which is what used to send every step.
      for (const rows of [16, 14, 12, 10, 8, 6, 4, 2]) {
        layout.resize(rows);
        await vi.advanceTimersByTimeAsync(120);
      }
      await vi.advanceTimersByTimeAsync(1000);

      expect(resizes(socket)).toEqual(["2x40"]);
    });

    it("fit() during a transition does not send the size measured mid-way", async () => {
      const { s, layout, socket } = await attached();

      // Files -> CLI while the keyboard is still up: the panel is shown at the
      // keyboard-open height, then the keyboard finishes closing 60 ms later.
      layout.resize(2);
      s.fit();
      await vi.advanceTimersByTimeAsync(60);
      layout.resize(18);
      await vi.advanceTimersByTimeAsync(1000);

      // 18x40 was already the PTY's size, so nothing at all is sent.
      expect(resizes(socket)).toEqual([]);
    });

    it("each settled size is sent once per keyboard open and close", async () => {
      const { layout, socket } = await attached();

      layout.resize(2); // open, settles
      await vi.advanceTimersByTimeAsync(1000);
      layout.resize(18); // close, settles
      await vi.advanceTimersByTimeAsync(1000);

      expect(resizes(socket)).toEqual(["2x40", "18x40"]);
    });

    it("an attach sends its size once, not again when the first fit settles", async () => {
      const s = newSession();
      s.mount(host({ visible: true }));
      const layout = liveHost({ rows: 18, cols: 40 });
      await s.connect(SESSION);
      sockets[0].open();
      makeWriter(sockets[0]);
      // The observer's initial callback for the freshly observed host.
      layout.resize(18);
      await vi.advanceTimersByTimeAsync(1000);

      expect(resizes(sockets[0])).toEqual(["18x40"]);
    });

    it("a host hidden while settling sends nothing", async () => {
      const element = document.createElement("div");
      let height = 600;
      Object.defineProperty(element, "clientWidth", { value: 800 });
      Object.defineProperty(element, "clientHeight", { get: () => height });
      const s = newSession();
      s.mount(element);
      const layout = liveHost({ rows: 18, cols: 40 });
      await s.connect(SESSION);
      sockets[0].open();
      await vi.advanceTimersByTimeAsync(1000);
      expect(resizes(sockets[0])).toEqual(["18x40"]);
      sockets[0].sent.length = 0;

      layout.resize(10);
      height = 0; // `display: none` before the debounce came due
      await vi.advanceTimersByTimeAsync(1000);

      expect(resizes(sockets[0])).toEqual([]);
    });

    // #131: creation was clamped to the wire contract, live resizes were not,
    // and the daemon rejects a frame outside 2-300 x 2-500 — leaving xterm and
    // the PTY on different grids.
    it("clamps a live resize to 300x500 and sizes xterm to the clamped grid (#131)", async () => {
      const { layout, socket } = await attached();

      layout.resize(900, 620);
      await vi.advanceTimersByTimeAsync(1000);

      expect(resizes(socket)).toEqual(["300x500"]);
      expect([terminals[0].rows, terminals[0].cols]).toEqual([300, 500]);

      // The floor is unchanged: under 2 rows is never put on the wire.
      layout.resize(1, 40);
      await vi.advanceTimersByTimeAsync(1000);
      expect(resizes(socket)).toEqual(["300x500"]);
    });

    // #132.1: a notification that changes nothing about the grid is not a
    // layout change, so it must not restart the confirmation.
    it("notifications with an unchanged proposal do not postpone the settle (#132)", async () => {
      const { layout, socket } = await attached();

      for (let i = 0; i < 10; i += 1) {
        layout.resize(18, 42);
        await vi.advanceTimersByTimeAsync(120);
      }
      expect(resizes(socket)).toEqual(["18x42"]);

      // Faster than the debounce, too.
      for (let i = 0; i < 20; i += 1) {
        layout.resize(18, 44);
        await vi.advanceTimersByTimeAsync(50);
      }
      expect(resizes(socket)).toEqual(["18x42", "18x44"]);
    });

    // #132.2
    it("fit() after dispose arms no timer (#132)", () => {
      const s = newSession();
      s.mount(host({ visible: true }));
      s.dispose();

      s.fit();

      expect(vi.getTimerCount()).toBe(0);
    });

    // #132.3: a socket that opens while the layout is still moving used to send
    // the mid-transition size at once, then the real one (2x40, then 18x40).
    it("an attach mid-transition sends only the size the layout settles at (#132)", async () => {
      const s = newSession();
      s.mount(host({ visible: true }));
      const layout = liveHost({ rows: 2, cols: 40 });
      await s.connect(SESSION);
      sockets[0].open();
      makeWriter(sockets[0]);
      await vi.advanceTimersByTimeAsync(60);
      layout.resize(18);
      await vi.advanceTimersByTimeAsync(1000);

      expect(resizes(sockets[0])).toEqual(["18x40"]);
    });

    it("a stable attach sends its one resize within one settle", async () => {
      const s = newSession();
      s.mount(host({ visible: true }));
      liveHost({ rows: 18, cols: 40 });
      await s.connect(SESSION);
      sockets[0].open();
      makeWriter(sockets[0]);

      await vi.advanceTimersByTimeAsync(200);
      expect(resizes(sockets[0])).toEqual(["18x40"]);
      await vi.advanceTimersByTimeAsync(1000);
      expect(resizes(sockets[0])).toEqual(["18x40"]);
    });

    // A successful takeover is announced by Central as `terminal.role` carrying
    // `writer_conn`, not `role` (backend/app/api/ws/terminal.py `_event`), and
    // Central accepts this connection's resizes from then on. The client's role
    // stays "viewer" (#133), so a client-side role gate would leave the PTY on
    // the old grid while xterm moves to the new one.
    it("after a takeover, a settled grid change still reaches the PTY", async () => {
      const s = newSession();
      s.mount(host({ visible: true }));
      const layout = liveHost({ rows: 18, cols: 40 });
      await s.connect(SESSION);
      sockets[0].open();
      sockets[0].emit(
        JSON.stringify({ type: "terminal.role", payload: { role: "viewer" } }),
      );
      await vi.advanceTimersByTimeAsync(1000);
      sockets[0].sent.length = 0;

      s.takeover();
      expect(JSON.parse(sockets[0].sent[0] as string)).toMatchObject({
        type: "terminal.control_acquire",
        payload: { session_id: SESSION },
      });
      sockets[0].emit(
        JSON.stringify({
          version: 1,
          type: "terminal.role",
          request_id: "00000000000000000000000000",
          node_id: SESSION,
          timestamp: "2026-10-06T00:00:00Z",
          payload: { session_id: SESSION, writer_conn: "conn-1" },
        }),
      );
      layout.resize(16);
      await vi.advanceTimersByTimeAsync(1000);

      expect([terminals[0].rows, terminals[0].cols]).toEqual([16, 40]);
      expect(resizes(sockets[0])).toEqual(["16x40"]);
    });

    // Every attach starts the PTY at the size stored at creation, so a new
    // socket sends its settled size even when the previous socket already sent
    // the same one — once, after one settle.
    it("a reconnect sends the settled size once on the new socket", async () => {
      const { socket } = await attached();
      socket.close();
      await vi.advanceTimersByTimeAsync(1000);
      expect(sockets).toHaveLength(2);
      sockets[1].open();
      makeWriter(sockets[1]);

      await vi.advanceTimersByTimeAsync(200);
      expect(resizes(sockets[1])).toEqual(["18x40"]);
      await vi.advanceTimersByTimeAsync(1000);
      expect(resizes(sockets[1])).toEqual(["18x40"]);
      expect(resizes(socket)).toEqual([]);
    });
  });

  // #115. A CLI is created before its panel exists, so the size it starts at is
  // measured on a throwaway terminal in a box of the panel's size — the same
  // font, line height and scrollback as the real one, so the same cell size.
  describe("measureTerminalSize (#115)", () => {
    it("measures the box with the CLI terminal's own font, then leaves nothing behind", () => {
      const before = document.body.childElementCount;

      expect(measureTerminalSize({ width: 356, height: 356 }, 15)).toEqual({
        rows: 43,
        columns: 110,
      });

      expect(terminals).toHaveLength(1);
      expect(terminals[0].options).toMatchObject({
        fontSize: 15,
        lineHeight: 1.2,
        scrollback: 10000,
      });
      // Measured in a real, laid-out box (visibility, not display: none).
      const probe = terminals[0].open.mock.calls[0][0] as HTMLElement;
      expect(probe.style.width).toBe("356px");
      expect(probe.style.height).toBe("356px");
      expect(probe.style.visibility).toBe("hidden");
      // No focus (it would raise a phone keyboard), no observer, no socket.
      expect(terminals[0].focus).not.toHaveBeenCalled();
      expect(observers).toHaveLength(0);
      expect(sockets).toHaveLength(0);
      expect(terminals[0].dispose).toHaveBeenCalledOnce();
      expect(document.body.childElementCount).toBe(before);
    });

    it("clamps to the wire contract and refuses a degenerate box", () => {
      expect(measureTerminalSize({ width: 0, height: 356 }, 14)).toBeNull();
      expect(terminals).toHaveLength(0);

      const measure = (rows: number, cols: number) => {
        nextProposal.value = { rows, cols };
        return measureTerminalSize({ width: 356, height: 356 }, 14);
      };
      expect(measure(900, 620)).toEqual({ rows: 300, columns: 500 });
      expect(measure(1, 40)).toBeNull();
      // Disposed on the refusal path too.
      expect(terminals.every((t) => t.dispose.mock.calls.length === 1)).toBe(
        true,
      );
    });
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
