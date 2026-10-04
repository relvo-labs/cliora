import { computed, onScopeDispose, readonly, ref } from "vue";
import { FitAddon } from "@xterm/addon-fit";
import { SearchAddon } from "@xterm/addon-search";
import { WebLinksAddon } from "@xterm/addon-web-links";
import { Terminal } from "@xterm/xterm";

import { DEFAULT_THEME, xtermTheme, type ThemeId } from "../theme/themes";

// A local monospace stack with no webfont name in it. What this replaces asked
// for "JetBrains Mono", which has never been bundled (ADR 0016 ships no font
// files), so it was a name that could only ever fall back — the terminal has
// always rendered in whatever came next in the list.
const TERMINAL_FONT_FAMILY =
  'ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace';
// See the note in `terminalOptions`: 1.2, not the documents' 1.6.
const TERMINAL_LINE_HEIGHT = 1.2;

export type TerminalStatus =
  | "idle"
  | "connecting"
  | "connected"
  | "reconnecting"
  | "disconnected"
  | "exited"
  | "gap";
export type TerminalRole = "writer" | "viewer";

// Fetches a fresh single-use ws-ticket for a session (tickets are one-shot, so
// every (re)connect mints a new one). Injected by the view so the composable
// stays decoupled from the API client and is easy to test.
export type TicketProvider = (sessionId: string) => Promise<string>;

const RETRY_MS = [1000, 2000, 5000, 10000, 30000] as const;

// The debounce every resize path goes through (plan/29 MS-09: one timing scheme,
// 100 ms). On its own it was not enough (#127): a phone keyboard, a tab switch or
// a rotation moves the layout in steps, and a step that held for more than
// 100 ms reached the PTY — measured in chromium, one keyboard animated in 120 ms
// steps sent eight resizes, 16 rows down to 2. So a size is sent only once it has
// *settled*: measured the same twice, one debounce apart, with no layout change
// in between. That is at least 200 ms of stillness, and one resize per size the
// layout actually rests at.
const RESIZE_DEBOUNCE_MS = 100;

// Every Terminal this module builds gets these, so a size measured on a probe
// (`measureTerminalSize`) is a size the real terminal will agree with: the cell
// size comes from the font and line height, and FitAddon reserves scrollbar
// width only when there is scrollback.
function terminalOptions(fontSize: number, themeId: ThemeId) {
  return {
    cursorBlink: true,
    convertEol: false,
    scrollback: 10000,
    fontFamily: TERMINAL_FONT_FAMILY,
    fontSize,
    // xterm's `lineHeight` is a multiplier on the *measured cell height*, not
    // a CSS line-height. The five design documents say 1.6, which is the
    // convention for UI body copy; applied here it costs 9 rows. Measured in
    // chromium at the target geometry (1440x900, a 674px CLI panel):
    // 14px/1.2 -> 19px cell -> 35 rows; 14px/1.4 -> 30 rows exactly;
    // 14px/1.6 -> 25px cell -> 26 rows, under plan/09's floor of 30.
    lineHeight: TERMINAL_LINE_HEIGHT,
    theme: xtermTheme(themeId),
  };
}

// Clamped to the wire contract's own bounds
// (contracts/v1/schemas/messages/session-start.schema.json: rows 2-300,
// columns 2-500), because a very wide window really can propose more than 500
// columns and Central answers that with a 422 — the terminal would simply fail
// to open. Under 2 the daemon's tmux rejects the size, so that is no answer.
function clampProposal(
  proposed: { rows: number; cols: number } | undefined,
): { rows: number; columns: number } | null {
  if (!proposed) return null;
  if (proposed.rows < 2 || proposed.cols < 2) return null;
  return {
    rows: Math.min(proposed.rows, 300),
    columns: Math.min(proposed.cols, 500),
  };
}

/**
 * The size a terminal would have in a box of `box` CSS pixels, measured on a
 * throwaway xterm rather than computed, so the cell size is the one the real
 * terminal will measure (#115). For a session that is created before its panel
 * exists — the New Session dialog — and only for that: no socket, no observer,
 * no focus (focus would raise a phone's keyboard), disposed before returning.
 *
 * The probe is laid out but invisible (`visibility: hidden`, not `display:
 * none`, which measures nothing). Null when the box is empty or the
 * measurement is degenerate; callers then fall back to the server default
 * rather than guess.
 */
export function measureTerminalSize(
  box: { width: number; height: number },
  fontSize: number,
): { rows: number; columns: number } | null {
  if (!(box.width > 0) || !(box.height > 0)) return null;
  const probe = document.createElement("div");
  probe.setAttribute("aria-hidden", "true");
  Object.assign(probe.style, {
    position: "fixed",
    left: "0px",
    top: "0px",
    width: `${box.width}px`,
    height: `${box.height}px`,
    visibility: "hidden",
    pointerEvents: "none",
  });
  document.body.appendChild(probe);
  const terminal = new Terminal(terminalOptions(fontSize, DEFAULT_THEME));
  try {
    const fit = new FitAddon();
    terminal.loadAddon(fit);
    terminal.open(probe);
    return clampProposal(fit.proposeDimensions());
  } finally {
    terminal.dispose();
    probe.remove();
  }
}

// Display options the caller owns, passed in rather than read from a store so
// the composable stays testable without Pinia — the same reason `getTicket` is
// injected.
export interface TerminalDisplayOptions {
  themeId?: ThemeId;
  fontSize?: number;
}

export function useTerminalSession(
  getTicket: TicketProvider,
  display: TerminalDisplayOptions = {},
) {
  // Held so a theme or size change that arrives *before* mount is not lost, and
  // so a re-mount rebuilds with the current values rather than the initial ones.
  let themeId: ThemeId = display.themeId ?? DEFAULT_THEME;
  let fontSize = display.fontSize ?? 14;
  const status = ref<TerminalStatus>("idle"),
    gap = ref<string>(),
    exit = ref<number>(),
    lastError = ref<string>(),
    role = ref<TerminalRole>("viewer");
  let terminal: Terminal | undefined,
    fit: FitAddon | undefined,
    socket: WebSocket | undefined,
    observer: ResizeObserver | undefined,
    hostElement: HTMLElement | undefined;
  let resizeTimer: number | undefined,
    retryTimer: number | undefined,
    retryIndex = 0,
    currentSession = "",
    disposed = false,
    lastSize = "",
    // The size seen at the previous settle check, "" when there is none.
    settling = "";

  function isWriter(): boolean {
    return role.value === "writer";
  }
  function sendJson(type: string, payload: Record<string, unknown>): void {
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    socket.send(JSON.stringify({ type, payload }));
  }
  function sendResize(): void {
    // The server applies resize only for the writer; sending as a viewer is a
    // harmless no-op, so no client-side role gate is needed here.
    if (!terminal) return;
    // A measurement taken while the host was hidden collapses to 1x1 or smaller,
    // and the daemon rejects anything under 2 (tmux `validSize`). Sending it
    // anyway would reshape the PTY behind a tab the user cannot even see.
    if (terminal.rows < 2 || terminal.cols < 2) return;
    sendJson("terminal.resize", {
      session_id: currentSession,
      rows: terminal.rows,
      columns: terminal.cols,
    });
  }
  // A hidden host (`display: none`, an inactive tab panel) measures 0x0, and
  // FitAddon happily turns that into a nonsense rows/cols pair. Refusing to
  // measure at all is the only safe answer: the next real fit happens when the
  // panel is shown again.
  function fitSafely(): boolean {
    if (!terminal || !hostElement) return false;
    if (hostElement.clientWidth === 0 || hostElement.clientHeight === 0) {
      return false;
    }
    fit?.fit();
    return true;
  }
  // Fit, then tell the daemon only when the size actually changed.
  function applyFit(): void {
    if (!fitSafely() || !terminal) return;
    const size = `${terminal.rows}:${terminal.cols}`;
    if (size === lastSize) return;
    lastSize = size;
    sendResize();
  }
  // What the host measures right now, without applying it; null while hidden.
  function measure(): string | null {
    if (!terminal || !hostElement) return null;
    if (hostElement.clientWidth === 0 || hostElement.clientHeight === 0) {
      return null;
    }
    const proposed = fit?.proposeDimensions();
    return proposed ? `${proposed.rows}:${proposed.cols}` : null;
  }
  // How a layout change reaches the PTY (#127): the ResizeObserver and every
  // caller of `fit()`. Only a font-size change (a deliberate user action, not a
  // transition) and a re-mount into a new host fit at once. The local terminal is
  // not fitted early either: xterm and the PTY must agree on the grid, so for the
  // ~200 ms of a transition the terminal keeps its previous size and the pane
  // clips it.
  function scheduleFit(): void {
    window.clearTimeout(resizeTimer);
    // A layout change invalidates whatever was being confirmed.
    settling = "";
    resizeTimer = window.setTimeout(settle, RESIZE_DEBOUNCE_MS);
  }
  function settle(): void {
    resizeTimer = undefined;
    const size = measure();
    // Hidden meanwhile: the next real fit happens when it is shown again.
    if (size === null) {
      settling = "";
      return;
    }
    if (size !== settling) {
      settling = size;
      resizeTimer = window.setTimeout(settle, RESIZE_DEBOUNCE_MS);
      return;
    }
    settling = "";
    applyFit();
  }
  // The size a *new* session should be started at, or null when the container
  // cannot be measured yet (hidden panel, no layout). Callers must fall back to
  // the server's default rather than guess: starting a PTY at the wrong size and
  // resizing it a moment later makes the shell redraw in front of the user.
  function proposeSize(): { rows: number; columns: number } | null {
    if (!terminal || !hostElement) return null;
    if (hostElement.clientWidth === 0 || hostElement.clientHeight === 0) {
      return null;
    }
    return clampProposal(fit?.proposeDimensions());
  }
  function makeObserver(): ResizeObserver {
    return new ResizeObserver(scheduleFit);
  }
  function requestControl(): void {
    sendJson("terminal.control_acquire", { session_id: currentSession });
  }
  function scheduleRetry(): void {
    if (disposed || status.value === "exited") return;
    status.value = "reconnecting";
    window.clearTimeout(retryTimer);
    retryTimer = window.setTimeout(
      () => void connect(currentSession),
      RETRY_MS[Math.min(retryIndex++, RETRY_MS.length - 1)],
    );
  }
  async function connect(sessionId: string): Promise<void> {
    if (disposed || !sessionId) return;
    currentSession = sessionId;
    window.clearTimeout(retryTimer);
    socket?.close();
    status.value = retryIndex ? "reconnecting" : "connecting";
    let ticket: string;
    try {
      ticket = await getTicket(sessionId);
    } catch {
      lastError.value = "Could not authorize the terminal session.";
      scheduleRetry();
      return;
    }
    if (disposed) return;
    const scheme = location.protocol === "https:" ? "wss" : "ws";
    socket = new WebSocket(
      `${scheme}://${location.host}/ws/sessions/${encodeURIComponent(
        sessionId,
      )}/terminal?ticket=${encodeURIComponent(ticket)}`,
    );
    socket.binaryType = "arraybuffer";
    socket.onopen = () => {
      status.value = "connected";
      gap.value = undefined;
      retryIndex = 0;
      fitSafely();
      sendResize(); // server auto-attaches; align the PTY to our size
      // Sent unconditionally — every attach starts at the size stored at
      // creation — and recorded, so the fit that settles right after the attach
      // does not send the same size a second time.
      if (terminal) lastSize = `${terminal.rows}:${terminal.cols}`;
    };
    socket.onmessage = (event) => {
      if (typeof event.data === "string") {
        handleControl(event.data);
      } else {
        terminal?.write(new Uint8Array(event.data as ArrayBuffer));
      }
    };
    socket.onerror = () => {
      lastError.value = "Unable to connect to the terminal relay.";
    };
    socket.onclose = () => {
      if (!disposed && status.value !== "exited") scheduleRetry();
    };
  }
  function handleControl(data: string): void {
    let message: {
      type?: string;
      payload?: { reason?: string; code?: number; role?: string };
      error?: { message?: string };
    };
    try {
      message = JSON.parse(data);
    } catch {
      return;
    }
    if (message.type === "terminal.role" && message.payload?.role) {
      role.value = message.payload.role === "writer" ? "writer" : "viewer";
    } else if (message.type === "terminal.gap") {
      gap.value = message.payload?.reason ?? "Output continuity was lost";
      status.value = "gap";
    } else if (
      message.type === "terminal.exited" ||
      message.type === "session.stopped"
    ) {
      exit.value = message.payload?.code;
      status.value = "exited";
    } else if (message.error) {
      lastError.value = "The terminal request could not be completed.";
    }
  }
  // Mount, or *re-mount* into a different host element. The re-mount path is
  // load-bearing: the workspace tabs and the loading/error states both take the
  // host out of the DOM and put a fresh one back, and this used to `return`
  // early on an existing terminal — leaving xterm rendering into a detached node
  // with no way back short of a page reload. The terminal is moved rather than
  // rebuilt so the scrollback and the live socket survive.
  function mount(element: HTMLElement): void {
    if (disposed) return;
    if (terminal) {
      if (hostElement === element) return;
      if (terminal.element) element.appendChild(terminal.element);
      hostElement = element;
      observer?.disconnect();
      observer = makeObserver();
      observer.observe(element);
      applyFit();
      return;
    }
    terminal = new Terminal(terminalOptions(fontSize, themeId));
    fit = new FitAddon();
    terminal.loadAddon(fit);
    terminal.loadAddon(new SearchAddon());
    terminal.loadAddon(new WebLinksAddon());
    terminal.open(element);
    // Raw bytes; only the writer's input is sent (the server also enforces this).
    terminal.onData((data) => {
      if (socket?.readyState === WebSocket.OPEN && isWriter()) {
        socket.send(new TextEncoder().encode(data));
      }
    });
    terminal.onBinary((data) => {
      if (socket?.readyState === WebSocket.OPEN && isWriter()) {
        socket.send(Uint8Array.from(data, (c) => c.charCodeAt(0) & 0xff));
      }
    });
    hostElement = element;
    observer = makeObserver();
    observer.observe(element);
    fitSafely();
    terminal.focus();
  }
  // Type text into the terminal as if the user had typed it — the same
  // writer-gated path `onData` uses, so no new authority is created. Image drop
  // uses it to put the stored path on the input line (ADR 0024 §2): the front
  // end types, Central never injects.
  //
  // Returns false when the caller is not the writer, so the UI can say why
  // instead of appearing to work.
  function typeText(text: string): boolean {
    if (!text || socket?.readyState !== WebSocket.OPEN || !isWriter())
      return false;
    // This is a public "write to the terminal" function and the next caller will
    // not know where its string came from. A control character here could move
    // the cursor, clear the screen, or submit the line on the user's behalf.
    // Spelled out rather than as a regex: a character class of literal
    // control codes is what `no-control-regex` exists to catch, and the
    // intent reads better here than an exception to that rule would.
    for (let i = 0; i < text.length; i += 1) {
      const code = text.charCodeAt(i);
      if (code < 0x20 || code === 0x7f) return false;
    }
    socket.send(new TextEncoder().encode(text));
    return true;
  }

  // Recolour in place. Assigning `options.theme` repaints without touching the
  // buffer — measured in chromium on 2026-09-08 with 200 rows written, scrolled
  // to line 120 and a half-typed line pending: buffer length, viewportY,
  // cursorX and rows were all identical afterwards and the rendered pixels did
  // change (plan/28 08-…md §2). `new Terminal()` here would reconnect the
  // socket and lose the scrollback, which is the whole thing the theme switch
  // promises not to do (`FR-TERM-001.AC-15`).
  //
  // No socket, fit or writer-gate code is touched by this function, and that is
  // a constraint rather than a coincidence (plan/28 D14).
  function applyThemeOption(id: ThemeId): void {
    themeId = id;
    if (!terminal) return;
    terminal.options.theme = xtermTheme(id);
  }
  // Refit after a size change: the cell size changed, so rows/cols changed, and
  // the daemon has to be told or the remote PTY keeps the old geometry. Goes
  // through applyFit so it still cannot send a 0x0 from a hidden panel.
  function setFontSize(size: number): void {
    fontSize = size;
    if (!terminal) return;
    terminal.options.fontSize = size;
    applyFit();
  }

  function retry(): void {
    retryIndex = 0;
    window.clearTimeout(retryTimer);
    void connect(currentSession);
  }
  function takeover(): void {
    requestControl();
  }
  function disconnect(): void {
    window.clearTimeout(retryTimer);
    socket?.close();
    socket = undefined;
    status.value = "disconnected";
  }
  function dispose(): void {
    if (disposed) return;
    disposed = true;
    window.clearTimeout(retryTimer);
    window.clearTimeout(resizeTimer);
    observer?.disconnect();
    socket?.close();
    terminal?.dispose();
    observer = undefined;
    socket = undefined;
    terminal = undefined;
    hostElement = undefined;
  }
  onScopeDispose(dispose);
  return {
    mount,
    connect,
    retry,
    takeover,
    disconnect,
    dispose,
    // Re-measure after the host becomes visible again (tab activation, a
    // phone's mode switch, rotation). Settled like every other layout change
    // (#127): a tab can be shown while the keyboard is still closing, and the
    // size measured at that moment is not the one the layout ends at.
    fit: scheduleFit,
    proposeSize,
    // Recolour and resize in place. Neither rebuilds the terminal.
    applyTheme: applyThemeOption,
    setFontSize,
    focus: () => terminal?.focus(),
    typeText,
    status: readonly(status),
    role: readonly(role),
    gap: readonly(gap),
    exit: readonly(exit),
    lastError: readonly(lastError),
    canRetry: computed(() => ["disconnected", "gap"].includes(status.value)),
  };
}
