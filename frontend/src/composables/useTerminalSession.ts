import { computed, onScopeDispose, readonly, ref } from "vue";
import { FitAddon } from "@xterm/addon-fit";
import { SearchAddon } from "@xterm/addon-search";
import { WebLinksAddon } from "@xterm/addon-web-links";
import { Terminal } from "@xterm/xterm";

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

export function useTerminalSession(getTicket: TicketProvider) {
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
    lastSize = "";

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
  // The size a *new* session should be started at, or null when the container
  // cannot be measured yet (hidden panel, no layout). Callers must fall back to
  // the server's default rather than guess: starting a PTY at the wrong size and
  // resizing it a moment later makes the shell redraw in front of the user.
  //
  // Clamped to the wire contract's own bounds
  // (contracts/v1/schemas/messages/session-start.schema.json: rows 2-300,
  // columns 2-500), because a very wide window really can propose more than 500
  // columns and Central answers that with a 422 — the terminal would simply fail
  // to open.
  function proposeSize(): { rows: number; columns: number } | null {
    if (!terminal || !hostElement) return null;
    if (hostElement.clientWidth === 0 || hostElement.clientHeight === 0) {
      return null;
    }
    const proposed = fit?.proposeDimensions();
    if (!proposed) return null;
    // Same floor as sendResize(): under 2 the daemon's tmux rejects the size.
    if (proposed.rows < 2 || proposed.cols < 2) return null;
    return {
      rows: Math.min(proposed.rows, 300),
      columns: Math.min(proposed.cols, 500),
    };
  }
  function makeObserver(): ResizeObserver {
    return new ResizeObserver(() => {
      window.clearTimeout(resizeTimer);
      resizeTimer = window.setTimeout(applyFit, 100);
    });
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
    terminal = new Terminal({
      cursorBlink: true,
      convertEol: false,
      scrollback: 10000,
      fontFamily: "JetBrains Mono, ui-monospace, monospace",
      fontSize: 13,
      theme: {
        background: "#0F1115",
        foreground: "#D7DDE4",
        selectionBackground: "#78AAFF40",
        cursor: "#FFFFFF",
      },
    });
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
    // Re-measure after the host becomes visible again (tab activation). The
    // caller must wait for the DOM to actually be laid out first.
    fit: applyFit,
    proposeSize,
    focus: () => terminal?.focus(),
    status: readonly(status),
    role: readonly(role),
    gap: readonly(gap),
    exit: readonly(exit),
    lastError: readonly(lastError),
    canRetry: computed(() => ["disconnected", "gap"].includes(status.value)),
  };
}
