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
    observer: ResizeObserver | undefined;
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
    sendJson("terminal.resize", {
      session_id: currentSession,
      rows: terminal.rows,
      columns: terminal.cols,
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
      fit?.fit();
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
  function mount(element: HTMLElement): void {
    if (terminal) return;
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
    observer = new ResizeObserver(() => {
      window.clearTimeout(resizeTimer);
      resizeTimer = window.setTimeout(() => {
        fit?.fit();
        if (!terminal) return;
        const size = `${terminal.rows}:${terminal.cols}`;
        if (size !== lastSize) {
          lastSize = size;
          sendResize();
        }
      }, 100);
    });
    observer.observe(element);
    fit.fit();
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
  }
  onScopeDispose(dispose);
  return {
    mount,
    connect,
    retry,
    takeover,
    disconnect,
    dispose,
    status: readonly(status),
    role: readonly(role),
    gap: readonly(gap),
    exit: readonly(exit),
    lastError: readonly(lastError),
    canRetry: computed(() => ["disconnected", "gap"].includes(status.value)),
  };
}
