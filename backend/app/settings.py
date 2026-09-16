import base64
import binascii
from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CLIORA_", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"

    # The P0 development relay's settings (`p0_enabled`, `p0_token`, `node_id`) were
    # removed in P4-07 along with the endpoints they configured (ADR 0016). Note that
    # `extra="ignore"` means a leftover `CLIORA_P0_ENABLED=true` in an old .env is
    # silently accepted and does nothing — which is the safe direction, since there is
    # no longer any endpoint for it to enable.

    # --- P1 data layer (ADR 0009) ---
    database_url: str = "postgresql+asyncpg://cliora:cliora@127.0.0.1:5432/cliora"

    # --- P4 connection pool bounds (ADR 0018) ---
    # Stated explicitly rather than left to SQLAlchemy's defaults. Two reasons: a
    # `database_pool_usage` metric and a "pool exhaustion" alert are meaningless
    # without a known denominator, and an unbounded wait for a checkout turns a
    # saturated pool into a hung request instead of a 503 someone can see.
    db_pool_size: int = 10
    db_max_overflow: int = 10
    db_pool_timeout_seconds: float = 5
    # Recycled well inside the typical proxy/database idle timeout, so a connection
    # is retired by us rather than discovered dead mid-request.
    db_pool_recycle_seconds: int = 1800

    # Public base URL advertised to daemons (installer / register response).
    public_base_url: str = ""

    # Directory holding release artifacts served by /api/downloads and
    # /api/install-script (agentd tarballs, checksums.txt, install.sh). Empty
    # disables the download endpoints (they answer 404). See ADR 0011.
    artifacts_dir: str = ""

    # --- P1 authentication (ADR 0007); real secrets come from the environment ---
    jwt_secret: str = "dev-only-change-me"
    jwt_algorithm: Literal["HS256"] = "HS256"
    access_token_ttl_seconds: int = 15 * 60
    refresh_token_ttl_seconds: int = 14 * 24 * 60 * 60
    ws_ticket_ttl_seconds: int = 60

    # Argon2id parameters for password hashing (ADR 0007).
    argon2_time_cost: int = 3
    argon2_memory_cost_kib: int = 64 * 1024
    argon2_parallelism: int = 4

    # Keyed hash pepper for enrollment tokens and node secrets (ADR 0008).
    token_pepper: str = "dev-only-change-me"

    # --- P1 enrollment defaults (ADR 0008) ---
    enrollment_default_ttl_seconds: int = 60 * 60
    enrollment_default_max_uses: int = 1
    hmac_challenge_ttl_seconds: int = 30

    # --- P1 node status timing (ADR 0010); seconds since last heartbeat ---
    heartbeat_interval_seconds: int = 10
    node_online_within_seconds: int = 30
    node_degraded_within_seconds: int = 90

    # --- P1 connection registry / request correlation (tech §7.3) ---
    # Upper bound on in-flight Central→daemon requests per node so a stuck or
    # flooding daemon cannot grow the pending map without bound.
    pending_requests_max: int = 128

    # --- P2 session / terminal (ADR 0013); measured, not hard-coded ---
    sessions_per_node_max: int = 10
    # Per-user cap across the whole fleet (P4-14, tech §23 #14). The per-node limit alone
    # left one account able to spread sessions thinly over many nodes — a hundred nodes
    # times nine sessions each trips nothing while consuming the fleet. Higher than the
    # per-node figure because a legitimate user works on several machines at once; low
    # enough that a runaway script or a stolen credential is bounded.
    sessions_per_user_max: int = 20
    session_start_timeout_seconds: float = 30
    session_stop_timeout_seconds: float = 20
    session_attach_timeout_seconds: float = 15
    session_list_timeout_seconds: float = 15
    writer_hold_window_seconds: float = 30
    # A system terminal with nobody attached is terminated after this long
    # (FR-SHELL-001.AC-08, ADR 0021 §6). Deliberately the opposite of a CLI
    # session, which must survive a disconnect (FR-SESSION-006): a long-running
    # CLI has value while unwatched, an unattended shell has only risk. Long
    # enough to survive a reload, a suspended laptop or a tunnel blip.
    shell_idle_terminate_seconds: float = 900
    reattach_snapshot_max_bytes: int = 2 * 1024 * 1024
    # Per-browser terminal output queue bounds (byte-aware backpressure).
    terminal_queue_max_bytes: int = 4 * 1024 * 1024
    terminal_queue_max_frames: int = 1024

    # --- P3 filesystem relay (ADR 0015); measured, not hard-coded ---
    file_list_timeout_seconds: float = 15
    file_read_timeout_seconds: float = 15
    # Longer than a read: the node writes to disk and fsyncs before replying
    # (ADR 0024). Still bounded, so a wedged node surfaces as REQUEST_TIMEOUT
    # rather than a browser that waits forever.
    file_upload_timeout_seconds: float = 20
    file_search_timeout_seconds: float = 15
    # Longer than a read for the mirror-image reason to the upload timeout: the
    # node reads up to 4 MiB off disk and base64s it before replying, where a
    # preview is capped at 2 MiB of text. Still bounded, so a wedged node surfaces
    # as REQUEST_TIMEOUT rather than a browser that waits forever (ADR 0028).
    file_download_timeout_seconds: float = 20

    # --- P4 audit retention (ADR 0016) ---
    # Expiry is applied by an explicit operator command
    # (`python -m app.retention prune`, dry-run by default), never by a background
    # scheduler: a mis-scheduled deletion of the audit trail is a worse failure
    # than manual retention, and there is no other background job to attach to.
    audit_retention_days: int = 365
    node_metric_retention_days: int = 30

    # --- P4 audit query bounds (ADR 0016) ---
    audit_page_default: int = 50
    audit_page_max: int = 200
    # Cap on a single query's time span. Without it the viewer can ask for the
    # whole table and call it a filter.
    audit_query_max_days: int = 90

    # --- P4 dashboard aggregates and node metric history (ADR 0018) ---
    # How often a node's heartbeat resource sample is persisted. Heartbeats arrive
    # every `heartbeat_interval_seconds`; writing every one would put six rows per
    # node per minute in the table for no extra fidelity.
    node_metric_sample_interval_seconds: int = 60
    # Process-local aggregate cache. Short enough that a refresh means something,
    # long enough that a page with six blocks does not re-run six queries per
    # viewer. `generated_at` always reports when the data was fetched, never when
    # the request arrived.
    dashboard_cache_ttl_seconds: float = 5
    # Beyond this gap since a node's last heartbeat, the nodes block is `stale`:
    # the numbers are shown but explicitly marked as possibly out of date.
    dashboard_stale_after_seconds: int = 30
    # Window the fleet resource summary aggregates over. Wider than the sampling
    # interval so a single missed sample does not empty the block.
    dashboard_resource_window_seconds: int = 300
    dashboard_recent_activity_limit: int = 20
    dashboard_unhealthy_limit: int = 10

    # --- P4 metrics export (ADR 0018) ---
    # Off by default. An always-on metrics endpoint is a permanent read surface on the
    # control plane, and most deployments do not scrape at all — so it is opt-in rather
    # than opt-out.
    metrics_enabled: bool = False
    # A dedicated token, deliberately **not** the `audit.view` permission: reusing it
    # would mean creating a service account that can read the audit trail just to
    # scrape numbers, and Prometheus holds no user session. Empty while disabled; a
    # validator refuses to enable the endpoint without one.
    metrics_scrape_token: str = ""
    # Per-gauge budget during a scrape. Exceeding it skips that gauge and records
    # `scrape_error_total` rather than failing the whole scrape: losing one number is
    # better than losing all visibility at the moment something is slow.
    metrics_gauge_timeout_seconds: float = 1.0

    # --- P4 workspace favourites / recents (ADR 0016) ---
    recent_workspaces_default: int = 5
    recent_workspaces_max: int = 20

    # --- P4 graceful shutdown (ADR 0018) ---
    # Upper bound on the SIGTERM drain, measured on the monotonic clock. Long enough
    # for every subscribed browser to receive the shutdown notice and for in-flight
    # requests to finish; short enough that a deploy is not held hostage by one stuck
    # socket. Exceeding it proceeds with the shutdown rather than waiting: the CLI
    # sessions survive either way, so a slow drain must not become an outage.
    shutdown_drain_seconds: float = 15

    # --- P4 daemon update (ADR 0017) ---
    # Far longer than any other relay timeout because the daemon downloads, swaps,
    # restarts and health-checks before it can answer — and the restart drops the
    # socket the answer was coming back on. Reaching this bound therefore means
    # "no answer yet", not "failed": the node's state stays `in_progress` until its
    # own report or its next registration settles it.
    update_request_timeout_seconds: float = 180

    # --- P11 third-party tunnel integration (ADR 0022) ---
    # Whether the integration is *on* is not here: it lives in the `tunnel_integration`
    # table, because an administrator turns it on in the UI and supplies the provider
    # credential in the same action. What stays in the environment is the key that makes
    # storing that credential possible, plus the bounds and timeouts.
    #
    # Unset means this deployment cannot store an integration credential, and enabling the
    # integration is refused (SECRET_KEY_MISSING) rather than falling back to plain text.
    # 32 bytes, base64: `openssl rand -base64 32`.
    secret_encryption_key: str = ""
    tunnel_max_ttl_seconds: int = 24 * 3600
    # Per-node ceiling. The fleet-wide budget is a provider-plan fact and lives in the
    # integration row; the two are separate checks, never one minimum (ADR 0022 D17b).
    tunnels_per_node_max: int = 3
    tunnels_per_user_max: int = 5
    # Covers the ssh handshake, the provider assigning a URL, and the daemon parsing it.
    # The middle step is entirely outside our control, which is why this is generous and
    # why the daemon's own wait (15 s) is deliberately shorter: whoever gives up first
    # decides what the user is told, and "the node timed out" is more useful than
    # "Central timed out" when the node is the one that knows.
    tunnel_open_timeout_seconds: float = 20
    # Closing is local work on the node — signal the child, reap it — and touches the
    # provider not at all, which is why it is the shortest tunnel budget. Our own row is
    # already settled when this is sent, so exceeding it costs nothing: the daemon stops the
    # child at its TTL and reaps orphans on restart either way.
    tunnel_close_timeout_seconds: float = 10
    tunnel_basic_password_length: int = 24
    # How often a node re-tests its egress to the provider. Per heartbeat would mean a TCP
    # connection to a third party every ten seconds per node, which looks like scanning.
    tunnel_node_prereq_interval_seconds: int = 300

    @model_validator(mode="after")
    def secret_encryption_key_must_be_32_bytes(self) -> "Settings":
        """Fail at startup rather than when an administrator presses save.

        A wrong-length key is not detectable until the first encryption, and that first
        encryption happens while somebody is typing a credential into a form.
        """
        raw = self.secret_encryption_key.strip()
        if not raw:
            return self
        try:
            decoded = base64.b64decode(raw, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError(
                "secret_encryption_key must be base64 (openssl rand -base64 32)"
            ) from exc
        if len(decoded) != 32:
            raise ValueError(
                "secret_encryption_key must decode to exactly 32 bytes "
                f"(got {len(decoded)}); generate one with `openssl rand -base64 32`"
            )
        return self

    @model_validator(mode="after")
    def require_a_scrape_token_when_metrics_are_enabled(self) -> "Settings":
        """Fail to start rather than serve the endpoint unauthenticated.

        Enabling metrics without a token would publish the full series set to anyone
        who can reach the port. Refusing at startup makes that a deployment error
        instead of a silent exposure.
        """
        if self.metrics_enabled and not self.metrics_scrape_token.strip():
            raise ValueError(
                "metrics_scrape_token must be set when metrics_enabled is true "
                "(the endpoint is never served unauthenticated)"
            )
        if self.metrics_enabled and len(self.metrics_scrape_token) < 16:
            raise ValueError("metrics_scrape_token must be at least 16 characters")
        return self

    @model_validator(mode="after")
    def reject_dev_secrets_in_production(self) -> "Settings":
        if self.environment == "production":
            if self.jwt_secret == "dev-only-change-me" or self.token_pepper == "dev-only-change-me":
                raise ValueError("JWT secret and token pepper must be set in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
