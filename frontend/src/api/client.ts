// Typed fetch wrapper for Central. Injects the Bearer access token, retries a
// single time through a single-flight refresh on 401, and maps error bodies to
// a typed ApiError ({error:{code,message}, request_id}). The base URL is empty
// by default (same-origin / vite proxy) and overridable via VITE_API_BASE_URL.

import type {
  AttachTicket,
  AuditPage,
  AuditQuery,
  CreateSessionInput,
  DashboardSummary,
  EnrollmentToken,
  EnrollmentTokenCreated,
  FileContent,
  FileUploadResult,
  FileSearchResult,
  FileTreePage,
  LoginResponse,
  CreateTunnelInput,
  NodeDetail,
  NodeSummary,
  NodeTunnelPolicy,
  RecentWorkspace,
  ReleaseManifest,
  SessionDetail,
  SessionSummary,
  TokenPair,
  TunnelDetail,
  TunnelIntegration,
  TunnelSummary,
  UpdateNodeInput,
  UpdateNodeTunnelSettingsInput,
  UpdateTunnelIntegrationInput,
  User,
  WorkspaceFavorite,
} from "./dto";

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly requestId?: string;
  // The server's non-sensitive `error.details`, when it sent any. Kept as data rather than
  // left for callers to re-read out of the message: a 422 that asks for an acknowledgement
  // says which one in `details.requires_acknowledgement`, and matching on the prose instead
  // would break the first time the wording is improved.
  readonly details?: Record<string, unknown>;

  constructor(
    code: string,
    message: string,
    status: number,
    requestId?: string,
    details?: Record<string, unknown>,
  ) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
    this.requestId = requestId;
    this.details = details;
  }
}

// Per-call options. `signal` lets a caller cancel a request it no longer needs
// (an aborted fetch rejects with an AbortError, which callers must not surface
// as a failure state).
export interface RequestOptions {
  signal?: AbortSignal;
}

// True for the rejection produced by aborting a fetch through an AbortSignal.
export function isAbortError(error: unknown): boolean {
  return error instanceof DOMException
    ? error.name === "AbortError"
    : (error as { name?: string })?.name === "AbortError";
}

// The client reads and rotates tokens through this store (implemented by the
// auth Pinia store) so token persistence policy lives in one place.
export interface TokenStore {
  accessToken(): string | null;
  refreshToken(): string | null;
  setTokens(pair: TokenPair): void;
  clear(): void;
}

const BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "";

export class ApiClient {
  private readonly tokens: TokenStore;
  private readonly fetchImpl: typeof fetch;
  private refreshInFlight: Promise<boolean> | null = null;

  constructor(tokens: TokenStore, fetchImpl?: typeof fetch) {
    this.tokens = tokens;
    this.fetchImpl = fetchImpl ?? fetch.bind(globalThis);
  }

  async login(username: string, password: string): Promise<LoginResponse> {
    const res = await this.raw(
      "POST",
      "/api/auth/login",
      { username, password },
      false,
    );
    const body = (await this.parse(res)) as LoginResponse;
    this.tokens.setTokens(body.tokens);
    return body;
  }

  async logout(): Promise<void> {
    try {
      await this.request("POST", "/api/auth/logout");
    } finally {
      this.tokens.clear();
    }
  }

  me(): Promise<User> {
    return this.request("GET", "/api/auth/me");
  }

  listNodes(): Promise<NodeSummary[]> {
    return this.request("GET", "/api/nodes");
  }

  getNode(id: string): Promise<NodeDetail> {
    return this.request("GET", `/api/nodes/${id}`);
  }

  setNodeEnabled(id: string, enabled: boolean): Promise<NodeDetail> {
    return this.request("POST", `/api/nodes/${id}/enabled`, { enabled });
  }

  removeNode(id: string): Promise<void> {
    return this.request("DELETE", `/api/nodes/${id}`);
  }

  // --- P4 daemon release + update ---
  // The body carries a version and nothing else. A 200 does not mean the update
  // finished: the daemon restarts during it, so the outcome may arrive later and the
  // returned status can legitimately read `in_progress` (SEC-002, ADR 0017).
  updateNode(id: string, input: UpdateNodeInput): Promise<NodeDetail> {
    return this.request("POST", `/api/nodes/${id}/update`, input);
  }

  // Public endpoint: the versions a node may be asked to install.
  getReleaseManifest(): Promise<ReleaseManifest> {
    return this.request("GET", "/api/releases/manifest");
  }

  // --- P4-13 workspace favourites and recents ---
  // Gated on `session.create`; a Viewer gets 403 on all four.
  listFavorites(options?: RequestOptions): Promise<WorkspaceFavorite[]> {
    return this.request("GET", "/api/workspaces/favorites", undefined, options);
  }

  // Idempotent: favouriting the same (node, path) twice returns the same row.
  addFavorite(
    input: { node_id: string; path: string; display_name?: string | null },
    options?: RequestOptions,
  ): Promise<WorkspaceFavorite> {
    return this.request("POST", "/api/workspaces/favorites", input, options);
  }

  removeFavorite(id: string, options?: RequestOptions): Promise<void> {
    return this.request(
      "DELETE",
      `/api/workspaces/favorites/${id}`,
      undefined,
      options,
    );
  }

  listRecentWorkspaces(
    limit?: number,
    options?: RequestOptions,
  ): Promise<RecentWorkspace[]> {
    const query = limit === undefined ? "" : `?limit=${limit}`;
    return this.request(
      "GET",
      `/api/workspaces/recent${query}`,
      undefined,
      options,
    );
  }

  listEnrollmentTokens(): Promise<EnrollmentToken[]> {
    return this.request("GET", "/api/enrollment-tokens");
  }

  createEnrollmentToken(input: {
    ttl_seconds?: number;
    max_uses?: number;
  }): Promise<EnrollmentTokenCreated> {
    return this.request("POST", "/api/enrollment-tokens", input);
  }

  revokeEnrollmentToken(id: string): Promise<void> {
    return this.request("DELETE", `/api/enrollment-tokens/${id}`);
  }

  // Issue a one-time WebSocket ticket (wired for the P2 terminal path).
  wsTicket(resource: string): Promise<{ ticket: string }> {
    return this.request("POST", "/api/ws-ticket", { resource });
  }

  // --- P2 sessions ---
  listSessions(params?: {
    node_id?: string;
    status?: string;
  }): Promise<SessionSummary[]> {
    const query = new URLSearchParams();
    if (params?.node_id) query.set("node_id", params.node_id);
    if (params?.status) query.set("status", params.status);
    const suffix = query.toString() ? `?${query.toString()}` : "";
    return this.request("GET", `/api/sessions${suffix}`);
  }

  getSession(id: string): Promise<SessionDetail> {
    return this.request("GET", `/api/sessions/${id}`);
  }

  createSession(input: CreateSessionInput): Promise<SessionDetail> {
    return this.request("POST", "/api/sessions", input);
  }

  terminateSession(id: string): Promise<SessionDetail> {
    return this.request("POST", `/api/sessions/${id}/terminate`);
  }

  // Terminate fired from a page-unload handler — a reload, a closed tab, a
  // navigation out of the app. `keepalive` is the entire point: an ordinary fetch
  // is cancelled with the document, which is exactly the case that used to leave a
  // system terminal running with nobody watching it (FR-SHELL-001.AC-08).
  //
  // No 401 refresh and no response handling: during unload there is time for one
  // request and nobody left to tell about the outcome. A lost one is not silent
  // loss either — the server treats an unwatched terminal as replaceable on the
  // next open, and the idle reaper still collects it.
  terminateSessionOnUnload(id: string): void {
    void this.raw(
      "POST",
      `/api/sessions/${id}/terminate`,
      undefined,
      true,
      undefined,
      true,
    ).catch(() => undefined);
  }

  // Mint the single-use ticket the terminal WebSocket consumes.
  attachSession(id: string): Promise<AttachTicket> {
    return this.request("POST", `/api/sessions/${id}/attach`);
  }

  // Open a system terminal inside a CLI session (FR-SHELL-001). The parent is in
  // the path and everything else comes from it, so there is no field here for a
  // command, a binary or a workspace (SEC-002).
  openShell(
    id: string,
    size: { rows: number; columns: number },
  ): Promise<SessionDetail> {
    return this.request("POST", `/api/sessions/${id}/shell`, size);
  }

  // --- P11 port forwarding (ADR 0022) ---
  //
  // Every one of these answers 404 while the integration is disabled, which is a state the
  // caller has to render rather than treat as an error: the capability does not exist on this
  // deployment until an administrator enables it.

  listTunnels(params?: {
    node_id?: string;
    mine?: boolean;
    include_ended?: boolean;
  }): Promise<TunnelSummary[]> {
    const query = new URLSearchParams();
    if (params?.node_id) query.set("node_id", params.node_id);
    if (params?.mine) query.set("mine", "true");
    if (params?.include_ended) query.set("include_ended", "true");
    const suffix = query.toString() ? `?${query.toString()}` : "";
    return this.request("GET", `/api/tunnels${suffix}`);
  }

  // The one response that carries `basic_auth_password`. Whatever the caller does not show
  // the user here is gone: only the hash is stored.
  createTunnel(input: CreateTunnelInput): Promise<TunnelDetail> {
    return this.request("POST", "/api/tunnels", input);
  }

  closeTunnel(id: string): Promise<void> {
    return this.request("DELETE", `/api/tunnels/${id}`);
  }

  extendTunnel(id: string): Promise<TunnelSummary> {
    return this.request("POST", `/api/tunnels/${id}/extend`);
  }

  // Closes and reopens the tunnel, because the provider fixes its options when the
  // connection is made. **The URL in the response may differ from the old one** — callers
  // must show the new one rather than assume the old link still works.
  rotateTunnelPassword(id: string): Promise<TunnelDetail> {
    return this.request("POST", `/api/tunnels/${id}/rotate-password`);
  }

  getNodeTunnelPolicy(
    nodeId: string,
    options?: RequestOptions,
  ): Promise<NodeTunnelPolicy> {
    return this.request(
      "GET",
      `/api/nodes/${nodeId}/tunnel-policy`,
      undefined,
      options,
    );
  }

  updateNodeTunnelSettings(
    nodeId: string,
    input: UpdateNodeTunnelSettingsInput,
  ): Promise<NodeTunnelPolicy> {
    return this.request("PUT", `/api/nodes/${nodeId}/tunnel-settings`, input);
  }

  getTunnelIntegration(options?: RequestOptions): Promise<TunnelIntegration> {
    return this.request("GET", "/api/integrations/tunnel", undefined, options);
  }

  updateTunnelIntegration(
    input: UpdateTunnelIntegrationInput,
  ): Promise<TunnelIntegration> {
    return this.request("PUT", "/api/integrations/tunnel", input);
  }

  // Write-only: the response is the same settings object every read returns, so there is no
  // shape in which this could echo the token back.
  setTunnelCredential(input: {
    token: string;
    plan_tier?: "free" | "pro";
  }): Promise<TunnelIntegration> {
    return this.request("PUT", "/api/integrations/tunnel/credential", input);
  }

  clearTunnelCredential(): Promise<TunnelIntegration> {
    return this.request("DELETE", "/api/integrations/tunnel/credential");
  }

  // --- P3 workspace files (read-only) ---
  // Every filesystem call takes an AbortSignal: the file tree cancels an
  // in-flight expand/search when the user switches directory, keyword, or
  // session so no stale response can land in the cache.

  listFileTree(
    sessionId: string,
    params: { path?: string; cursor?: string; entry_limit?: number } = {},
    options: RequestOptions = {},
  ): Promise<FileTreePage> {
    const query = new URLSearchParams({ path: params.path ?? "." });
    if (params.cursor) query.set("cursor", params.cursor);
    if (params.entry_limit)
      query.set("entry_limit", String(params.entry_limit));
    return this.request(
      "GET",
      `/api/sessions/${encodeURIComponent(sessionId)}/files/tree?${query}`,
      undefined,
      options,
    );
  }

  searchFiles(
    sessionId: string,
    params: { keyword: string; root?: string; max_results?: number },
    options: RequestOptions = {},
  ): Promise<FileSearchResult> {
    const query = new URLSearchParams({ keyword: params.keyword });
    if (params.root) query.set("root", params.root);
    if (params.max_results)
      query.set("max_results", String(params.max_results));
    return this.request(
      "GET",
      `/api/sessions/${encodeURIComponent(sessionId)}/files/search?${query}`,
      undefined,
      options,
    );
  }

  readFileContent(
    sessionId: string,
    path: string,
    options: RequestOptions = {},
  ): Promise<FileContent> {
    const query = new URLSearchParams({ path });
    return this.request(
      "GET",
      `/api/sessions/${encodeURIComponent(sessionId)}/files/content?${query}`,
      undefined,
      options,
    );
  }

  // --- P4 dashboard aggregates ---
  // No parameters: Central owns the window, the freshness rules and the cache, so
  // there is nothing here for a caller to get wrong.
  getDashboardSummary(options: RequestOptions = {}): Promise<DashboardSummary> {
    return this.request("GET", "/api/dashboard/summary", undefined, options);
  }

  // --- P4 audit trail (Admin only) ---
  // Every parameter is optional; Central supplies the bounded default window, so
  // the browser never has to guess one (and cannot widen it past the cap).
  listAudit(
    query: AuditQuery = {},
    options: RequestOptions = {},
  ): Promise<AuditPage> {
    const params = new URLSearchParams();
    // Repeated `action` is a union server-side, which is why it is appended
    // rather than joined into one comma-separated value.
    for (const action of query.action ?? []) {
      params.append("action", action);
    }
    for (const key of [
      "user_id",
      "node_id",
      "session_id",
      "from",
      "to",
    ] as const) {
      const value = query[key];
      if (value) {
        params.set(key, value);
      }
    }
    if (query.limit !== undefined) params.set("limit", String(query.limit));
    if (query.cursor) params.set("cursor", query.cursor);
    const suffix = params.toString() ? `?${params}` : "";
    return this.request("GET", `/api/audit${suffix}`, undefined, options);
  }

  // Drop one image into the session workspace (ADR 0024). Separate from
  // `request` for two reasons: the body is raw bytes rather than JSON, and this
  // is the one call where progress is worth showing, which `fetch` cannot report
  // for an upload. Hence XMLHttpRequest, and hence the 401 refresh handled here
  // rather than inherited.
  async uploadImage(
    sessionId: string,
    file: Blob,
    options: {
      signal?: AbortSignal;
      onProgress?: (fraction: number) => void;
    } = {},
  ): Promise<FileUploadResult> {
    try {
      return await this.uploadOnce(sessionId, file, options);
    } catch (error) {
      if (
        error instanceof ApiError &&
        error.status === 401 &&
        (await this.refresh())
      ) {
        return this.uploadOnce(sessionId, file, options);
      }
      throw error;
    }
  }

  private uploadOnce(
    sessionId: string,
    file: Blob,
    options: { signal?: AbortSignal; onProgress?: (fraction: number) => void },
  ): Promise<FileUploadResult> {
    const path = `/api/sessions/${encodeURIComponent(sessionId)}/files/images`;
    return new Promise<FileUploadResult>((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", `${BASE}${path}`);
      // The image's own type; the server accepts four and re-checks the bytes.
      xhr.setRequestHeader("Content-Type", file.type);
      const token = this.tokens.accessToken();
      if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);

      const onAbort = () => xhr.abort();
      options.signal?.addEventListener("abort", onAbort);
      const done = () => options.signal?.removeEventListener("abort", onAbort);

      if (options.onProgress) {
        xhr.upload.onprogress = (event) => {
          if (event.lengthComputable) {
            options.onProgress?.(event.loaded / event.total);
          }
        };
      }
      xhr.onerror = () => {
        done();
        reject(
          new ApiError("NETWORK_ERROR", "The upload could not be sent", 0),
        );
      };
      xhr.onabort = () => {
        done();
        reject(new ApiError("CANCELLED", "The upload was cancelled", 0));
      };
      xhr.onload = () => {
        done();
        let body: {
          error?: { code?: string; message?: string };
          request_id?: string;
        } & Partial<FileUploadResult> = {};
        try {
          body = xhr.responseText ? JSON.parse(xhr.responseText) : {};
        } catch {
          // A non-JSON body from a proxy (a 413 page, say) still has a status.
        }
        if (xhr.status >= 200 && xhr.status < 300 && body.path) {
          resolve(body as FileUploadResult);
          return;
        }
        reject(
          new ApiError(
            body.error?.code ?? "HTTP_ERROR",
            body.error?.message ?? xhr.statusText,
            xhr.status,
            body.request_id,
          ),
        );
      };
      xhr.send(file);
    });
  }

  private async request<T>(
    method: string,
    path: string,
    body?: unknown,
    options: RequestOptions = {},
  ): Promise<T> {
    let res = await this.raw(method, path, body, true, options.signal);
    if (res.status === 401 && this.tokens.refreshToken()) {
      const refreshed = await this.refresh();
      if (refreshed) {
        res = await this.raw(method, path, body, true, options.signal);
      }
    }
    return (await this.parse(res)) as T;
  }

  // Single-flight: concurrent 401s share one refresh call.
  private refresh(): Promise<boolean> {
    if (!this.refreshInFlight) {
      this.refreshInFlight = (async () => {
        const refreshToken = this.tokens.refreshToken();
        if (!refreshToken) {
          return false;
        }
        const res = await this.raw(
          "POST",
          "/api/auth/refresh",
          { refresh_token: refreshToken },
          false,
        );
        if (!res.ok) {
          this.tokens.clear();
          return false;
        }
        this.tokens.setTokens((await res.json()) as TokenPair);
        return true;
      })().finally(() => {
        this.refreshInFlight = null;
      });
    }
    return this.refreshInFlight;
  }

  private raw(
    method: string,
    path: string,
    body: unknown,
    auth: boolean,
    signal?: AbortSignal,
    keepalive = false,
  ): Promise<Response> {
    const headers: Record<string, string> = {};
    if (body !== undefined) {
      headers["Content-Type"] = "application/json";
    }
    if (auth) {
      const token = this.tokens.accessToken();
      if (token) {
        headers["Authorization"] = `Bearer ${token}`;
      }
    }
    return this.fetchImpl(`${BASE}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
      keepalive,
    });
  }

  private async parse(res: Response): Promise<unknown> {
    if (res.status === 204) {
      return undefined;
    }
    const text = await res.text();
    const data = text ? (JSON.parse(text) as unknown) : undefined;
    if (!res.ok) {
      const errBody = data as
        | {
            error?: {
              code?: string;
              message?: string;
              details?: Record<string, unknown>;
            };
            request_id?: string;
          }
        | undefined;
      throw new ApiError(
        errBody?.error?.code ?? "HTTP_ERROR",
        errBody?.error?.message ?? res.statusText,
        res.status,
        errBody?.request_id,
        errBody?.error?.details,
      );
    }
    return data;
  }
}
