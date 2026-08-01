"""Port-forwarding tunnels: three-layer policy, lifecycle and URL propagation (P11, ADR 0022).

This service is deliberately thin. The traffic never touches Central — the tunnel is an
`ssh -R` child process on the node, and the provider is the one carrying bytes — so all that
happens here is: write a row, send a control frame, take in what comes back. There is no
registry, no stream manager and no proxy; that absence *is* the integration design (ADR 0022,
replacing plan/10's self-hosted reverse proxy).

Two pieces carry the weight:

* `effective_policy` — a pure function over the three configuration layers (platform
  integration, per-node platform settings, the node's own reported config). Every layer may
  only narrow, and the node's local veto cannot be overridden by anything the platform says
  (D17). It is a separate function with its own tests because it has four inputs and three
  outputs and a mistake in it is a security bug, not a display bug.
* `derive_state` — the tunnel's state, computed rather than stored (see `NodeTunnel`). A
  stored status would be a second answer to a question that already has one, and it would be
  the stale one.

The provider credential appears in exactly one expression, inside `create`, on its way into
the `tunnel.open` frame. It is not held on a dataclass, not logged, and not included in any
error message — the plaintext's whole lifetime is the assembly of that one frame.
"""

from __future__ import annotations

import ipaddress
import secrets
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.clock import now_utc
from app.db.models import Node, NodeTunnel, NodeTunnelSettings, TunnelIntegration, User
from app.logging import get_logger
from app.repositories.audit import AuditRepository
from app.repositories.integrations import IntegrationRepository
from app.repositories.nodes import NodeRepository
from app.repositories.tunnels import TunnelRepository, TunnelRow
from app.security.passwords import hash_password
from app.services import audit
from app.services.audit import AuditService
from app.services.authz import may_close_tunnel
from app.services.integrations import (
    PLAN_PRO,
    PROTECTIONS,
    IntegrationService,
)
from app.services.nodes import ensure_node_enabled
from app.services.registry import NodeConnectionRegistry, get_node_registry
from app.settings import Settings, get_settings

log = get_logger("cliora.tunnels")

# The absolute floor, restated here as the outermost of four layers (wire schema, database
# CHECK, daemon, this). Forwarding a port below 1024 means forwarding something a root
# process bound — sshd is the one that matters — and no configuration may lower it.
PORT_FLOOR = 1024
PORT_CEILING = 65535

# Which layer refused, for a message that can name it. Three layers means "not allowed" has
# three possible causes and three different remedies: change the platform setting, change
# this node's platform setting, or ask the node's owner to edit their config file. A refusal
# that does not say which one leaves the user trying all three.
LAYER_INTEGRATION = "integration"
LAYER_NODE_SETTINGS = "node_settings"
LAYER_NODE_LOCAL = "node_local"

# Derived states (there is no status column). Ordered by precedence in `derive_state`.
STATE_CLOSED = "closed"
STATE_EXPIRED = "expired"
STATE_FAILED = "failed"
STATE_UNAVAILABLE = "unavailable"
STATE_OPENING = "opening"
STATE_RUNNING = "running"

# The username the provider enforces basic auth against. Fixed rather than the caller's
# name: the credential is shown once and shared with whoever gets the link, so tying it to a
# person's account name only invites reuse of that name somewhere it matters.
BASIC_AUTH_USER = "preview"

_MAX_ALLOWED_IPS = 32


# --- The three configuration layers, as plain values -------------------------------- #
#
# Small frozen inputs rather than ORM rows so `effective_policy` can be tested without a
# database, which is the only way a four-input pure function gets the case coverage it needs.


@dataclass(frozen=True, slots=True)
class IntegrationLayer:
    enabled: bool
    allowed_ports: list[str] | None


@dataclass(frozen=True, slots=True)
class NodeSettingsLayer:
    enabled: bool
    allowed_ports: list[str] | None
    max_tunnels: int | None


@dataclass(frozen=True, slots=True)
class NodeReportLayer:
    """What the node last said about itself (contracts: `node-tunnel-report`).

    `reported_at is None` means the node has never told us, which is not the same as telling
    us "no" — the UI has to be able to say "unknown" rather than "not ready".
    """

    veto: bool
    prereq_ok: bool
    allowed_ports: list[str] | None
    max_tunnels: int | None
    reported_at: datetime | None
    daemon_supports: bool


@dataclass(frozen=True, slots=True)
class EffectivePolicy:
    enabled: bool
    # Set exactly when `enabled` is false.
    blocked_by: str | None
    # Empty means "nothing may be forwarded", which is a legitimate setting and distinct
    # from the unconstrained default (the whole 1024-65535 range).
    allowed_ports: tuple[tuple[int, int], ...]
    max_tunnels: int

    def permits(self, port: int) -> bool:
        return any(low <= port <= high for low, high in self.allowed_ports)

    def port_display(self) -> str:
        parts = [f"{low}" if low == high else f"{low}-{high}" for low, high in self.allowed_ports]
        return ", ".join(parts) or "none"


def parse_port_specs(specs: list[str] | None) -> tuple[tuple[int, int], ...] | None:
    """Turn stored specs ("5173", "3000-3999") into ranges, or None for "do not narrow".

    Unparseable entries are dropped rather than raised on: these values were validated when
    they were written, so a bad one here means data from elsewhere, and the safe reading of
    an unintelligible restriction is to ignore it rather than to fail every request on that
    node. Ranges are clamped to the floor, so a stored `80-90` narrows to nothing instead of
    quietly permitting port 80.
    """
    if specs is None:
        return None
    ranges: list[tuple[int, int]] = []
    for spec in specs:
        low, _, high = str(spec).strip().partition("-")
        try:
            start = int(low)
            end = int(high) if high else start
        except ValueError:
            continue
        start = max(start, PORT_FLOOR)
        end = min(end, PORT_CEILING)
        if start <= end:
            ranges.append((start, end))
    return tuple(sorted(ranges))


def _intersect(
    left: tuple[tuple[int, int], ...] | None, right: tuple[tuple[int, int], ...] | None
) -> tuple[tuple[int, int], ...] | None:
    if left is None:
        return right
    if right is None:
        return left
    out: list[tuple[int, int]] = []
    for a_low, a_high in left:
        for b_low, b_high in right:
            low, high = max(a_low, b_low), min(a_high, b_high)
            if low <= high:
                out.append((low, high))
    return tuple(sorted(out))


def effective_policy(
    integration: IntegrationLayer,
    node_settings: NodeSettingsLayer,
    node_report: NodeReportLayer,
    settings: Settings,
) -> EffectivePolicy:
    """Intersect the three layers (D17). Every layer may narrow; none may widen.

    The node's veto is checked last and cannot be reached past: whatever the platform's two
    layers say, `tunnel.enabled: false` in the node's own config file is final. That
    ordering is also the reporting order — the first layer that refuses is the one named,
    and the platform layers are the ones a platform user can actually change.
    """
    blocked_by: str | None = None
    if not integration.enabled:
        blocked_by = LAYER_INTEGRATION
    elif not node_settings.enabled:
        blocked_by = LAYER_NODE_SETTINGS
    elif node_report.veto or not node_report.daemon_supports:
        # A daemon too old to support port forwarding is reported as the local layer on
        # purpose: like a veto, it is resolved on the node and by its owner.
        blocked_by = LAYER_NODE_LOCAL

    ports = _intersect(
        _intersect(
            parse_port_specs(integration.allowed_ports),
            parse_port_specs(node_settings.allowed_ports),
        ),
        parse_port_specs(node_report.allowed_ports),
    )
    if ports is None:
        ports = ((PORT_FLOOR, PORT_CEILING),)

    caps = [settings.tunnels_per_node_max, node_settings.max_tunnels, node_report.max_tunnels]
    # The fleet-wide `concurrent_budget` is deliberately absent: it is checked separately as
    # a global count (D17b).
    max_tunnels = min(cap for cap in caps if cap is not None and cap > 0)

    return EffectivePolicy(
        enabled=blocked_by is None,
        blocked_by=blocked_by,
        allowed_ports=ports,
        max_tunnels=max_tunnels,
    )


def integration_layer(row: TunnelIntegration | None) -> IntegrationLayer:
    if row is None:
        return IntegrationLayer(enabled=False, allowed_ports=None)
    return IntegrationLayer(
        enabled=row.enabled, allowed_ports=list(row.allowed_ports) if row.allowed_ports else None
    )


def node_settings_layer(row: NodeTunnelSettings | None) -> NodeSettingsLayer:
    if row is None:
        # No row means nobody has narrowed this node. The default is participation (D3): a
        # node that has been enrolled already grants the platform a shell runtime (ADR 0021).
        return NodeSettingsLayer(enabled=True, allowed_ports=None, max_tunnels=None)
    return NodeSettingsLayer(
        enabled=row.enabled,
        allowed_ports=list(row.allowed_ports) if row.allowed_ports is not None else None,
        max_tunnels=row.max_tunnels,
    )


def node_report_layer(node: Node) -> NodeReportLayer:
    ports = node.tunnel_local_allowed_ports
    return NodeReportLayer(
        veto=bool(node.tunnel_veto),
        prereq_ok=bool(node.tunnel_prereq_ok),
        allowed_ports=[str(p) for p in ports] if isinstance(ports, list) else None,
        max_tunnels=node.tunnel_local_max,
        reported_at=node.tunnel_reported_at,
        # Never reported means we cannot claim support. The refusal names the local layer
        # and tells the owner to upgrade, which is the true remedy either way.
        daemon_supports=node.tunnel_reported_at is not None,
    )


def derive_state(tunnel: NodeTunnel, *, connected: bool, now: datetime) -> str:
    """The tunnel's state, in precedence order.

    `failed` outranks `unavailable`: a recorded failure carries a code and a remedy, while
    "the node is offline right now" is an observation that will change on its own. Showing
    the weaker of the two would hide the only actionable half.
    """
    if tunnel.closed_at is not None:
        return STATE_CLOSED
    if tunnel.expires_at <= now:
        return STATE_EXPIRED
    if tunnel.state_error_code is not None:
        return STATE_FAILED
    if not connected:
        return STATE_UNAVAILABLE
    if tunnel.url is None:
        return STATE_OPENING
    return STATE_RUNNING


def generate_basic_password(length: int) -> str:
    """A URL-safe password with no `:`.

    The colon is the provider's own separator in `b:user:pass`, so one inside the password
    would silently become a second credential pair or an unintended remote option.
    `token_urlsafe` yields `[A-Za-z0-9_-]`, which satisfies the wire schema's visible-ASCII
    pattern without any filtering.
    """
    bounded = max(8, min(length, 64))
    raw = secrets.token_urlsafe(bounded)
    return raw[:bounded]


@dataclass(frozen=True, slots=True)
class TunnelView:
    """One tunnel as an interface may see it.

    `basic_auth_password` is populated on exactly two paths (creation and rotation) and is
    `None` everywhere else, because it is never stored — only its Argon2 hash is.
    """

    tunnel: NodeTunnel
    node_name: str | None
    created_by_username: str | None
    state: str
    can_close: bool
    can_rotate: bool
    basic_auth_password: str | None = None


class TunnelService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        registry: NodeConnectionRegistry | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._registry = registry or get_node_registry()
        self._repo = TunnelRepository(session)
        self._nodes = NodeRepository(session)
        self._integration_repo = IntegrationRepository(session)
        self._integrations = IntegrationService(session, self._settings)
        self._audit = AuditService(session)
        self._audit_repo = AuditRepository(session)

    # --- policy ------------------------------------------------------------------- #

    async def policy_for(self, node: Node) -> EffectivePolicy:
        return effective_policy(
            integration_layer(await self._integration_repo.get_integration()),
            node_settings_layer(await self._integration_repo.get_node_settings(node.id)),
            node_report_layer(node),
            self._settings,
        )

    async def require_integration_enabled(self) -> TunnelIntegration:
        """The platform switch, which lives in the database rather than the environment.

        404 rather than 403: with the integration off, port forwarding is not a thing this
        deployment has, and every tunnel route answers the same way (PG-08).
        """
        row = await self._integration_repo.get_integration()
        if row is None or not row.enabled:
            raise ApiError(
                "TUNNEL_INTEGRATION_DISABLED",
                "Port forwarding is not enabled for this deployment.",
                status.HTTP_404_NOT_FOUND,
            )
        return row

    # --- read --------------------------------------------------------------------- #

    async def list(
        self,
        viewer: User,
        *,
        node_id: uuid.UUID | None = None,
        mine: bool = False,
        include_ended: bool = False,
        limit: int = 100,
    ) -> list[TunnelView]:
        now = now_utc()
        rows = await self._repo.list(
            now=now,
            node_id=node_id,
            created_by=viewer.id if mine else None,
            include_ended=include_ended,
            limit=limit,
        )
        return [self._view(row, viewer=viewer, now=now) for row in rows]

    async def get(self, tunnel_id: uuid.UUID, viewer: User) -> TunnelView:
        row = await self._repo.row(tunnel_id)
        if row is None:
            raise ApiError("NOT_FOUND", "Tunnel not found", status.HTTP_404_NOT_FOUND)
        return self._view(row, viewer=viewer, now=now_utc())

    def _view(self, row: TunnelRow, *, viewer: User, now: datetime) -> TunnelView:
        state = derive_state(
            row.tunnel, connected=self._registry.is_connected(row.tunnel.node_id), now=now
        )
        closable = may_close_tunnel(viewer, row.tunnel) and state not in (
            STATE_CLOSED,
            STATE_EXPIRED,
        )
        return TunnelView(
            tunnel=row.tunnel,
            node_name=row.node_name,
            created_by_username=row.created_by_username,
            state=state,
            can_close=closable,
            # Rotating means closing and reopening, so it needs the same right as closing
            # plus something to reopen: a basic-auth tunnel that has not already ended.
            can_rotate=closable and row.tunnel.protection == "basic",
        )

    # --- create ------------------------------------------------------------------- #

    async def create(
        self,
        actor: User,
        *,
        node_id: uuid.UUID,
        port: int,
        protection: str | None = None,
        # `Sequence`, not `list`: this class has a method called `list`, which shadows the
        # builtin inside the class body and makes `list[str]` an invalid annotation.
        allowed_ips: Sequence[str] | None = None,
        label: str | None = None,
        ttl_seconds: int | None = None,
        rewrite_host: bool = False,
        acknowledge_third_party: bool = False,
        acknowledge_public: bool = False,
    ) -> TunnelView:
        integration = await self.require_integration_enabled()
        node = await self._nodes.get(node_id)
        if node is None:
            raise ApiError("NODE_NOT_FOUND", "Node not found", status.HTTP_404_NOT_FOUND)
        ensure_node_enabled(node)

        policy = await self.policy_for(node)
        if not policy.enabled:
            raise self._node_disabled_error(policy.blocked_by)

        # Before the button, not after a 20-second timeout: the three prerequisites are the
        # first thing most people hit, and the node has already told us about them.
        if not node.tunnel_prereq_ok:
            raise ApiError(
                "TUNNEL_PROVIDER_NOT_CONFIGURED",
                "This node is not ready to forward a port"
                + self._prereq_detail(node)
                + " Run `agentd doctor` on the node to see which prerequisite is missing.",
                status.HTTP_409_CONFLICT,
            )
        if not self._registry.is_connected(node_id):
            raise ApiError("NODE_OFFLINE", "Node is not connected", status.HTTP_409_CONFLICT)

        if not policy.permits(port):
            raise ApiError(
                "TUNNEL_PORT_NOT_ALLOWED",
                f"Port {port} may not be forwarded on this node. Allowed: {policy.port_display()}.",
                status.HTTP_409_CONFLICT,
            )

        now = now_utc()
        await self._enforce_limits(
            node=node, actor=actor, integration=integration, policy=policy, now=now
        )

        chosen = protection or integration.default_protection
        if chosen not in PROTECTIONS:
            raise ApiError(
                "INVALID_ARGUMENT",
                "Protection must be one of: basic, ipallow, public.",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        cleaned_ips = _validated_ips(allowed_ips) if chosen == "ipallow" else None
        if chosen == "ipallow" and not cleaned_ips:
            raise ApiError(
                "INVALID_ARGUMENT",
                "An IP allowlist needs at least one address or CIDR range.",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        if chosen == "public" and not acknowledge_public:
            raise ApiError(
                "INVALID_ARGUMENT",
                "An unprotected tunnel is reachable by anyone who has the URL. Confirm "
                "that before creating it.",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                details={"requires_acknowledgement": "public"},
            )

        # First time this person forwards a port from this node, they are told where the
        # traffic goes. Answered from the audit trail rather than a new column: "has this
        # user ever created a tunnel on this node" is exactly what the trail records, and a
        # second table would be a second truth to keep in step (PG-08 §2.2).
        if not acknowledge_third_party and not await self._audit_repo.exists(
            audit.TUNNEL_CREATE, user_id=actor.id, node_id=node_id
        ):
            raise ApiError(
                "INVALID_ARGUMENT",
                "Traffic to this port will pass through the third-party tunnel provider. "
                "Confirm that before creating the first tunnel on this node.",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                details={"requires_acknowledgement": "third_party"},
            )

        existing = await self._repo.live_on_port(node_id, port, now=now)
        if existing is not None:
            raise ApiError(
                "TUNNEL_PORT_NOT_ALLOWED",
                f"Port {port} on this node is already forwarded.",
                status.HTTP_409_CONFLICT,
                details={"tunnel_id": str(existing.id)},
            )

        ttl = self._bounded_ttl(ttl_seconds, integration)
        password = (
            generate_basic_password(self._settings.tunnel_basic_password_length)
            if chosen == "basic"
            else None
        )

        tunnel = NodeTunnel(
            id=uuid.uuid4(),
            node_id=node_id,
            port=port,
            provider=integration.provider,
            protection=chosen,
            basic_auth_user=BASIC_AUTH_USER if password else None,
            basic_auth_hash=hash_password(password, self._settings) if password else None,
            allowed_ips=cleaned_ips,
            label=label,
            rewrite_host=rewrite_host,
            created_by=actor.id,
            expires_at=now + timedelta(seconds=ttl),
        )
        self._repo.add(tunnel)
        await self._session.flush()

        payload: dict[str, object] = {
            "tunnel_id": str(tunnel.id),
            "port": port,
            "protection": chosen,
            "ttl_seconds": ttl,
        }
        if rewrite_host:
            payload["rewrite_host"] = True
        if password:
            payload["basic_auth"] = {"username": BASIC_AUTH_USER, "password": password}
        if cleaned_ips:
            payload["allowed_ips"] = cleaned_ips
        # The one decryption site's one caller. The plaintext exists as a value in this
        # payload dict and nowhere else: not on the row, not on the view, not in a log line,
        # and not in the error raised if the open fails.
        credential = None
        if integration.plan_tier == PLAN_PRO:
            credential = await self._integrations.credential_for_open()
            if credential is None:
                await self._repo.remove(tunnel)
                raise ApiError(
                    "TUNNEL_PROVIDER_UNAUTHORIZED",
                    "The paid tier is selected but no provider credential is stored. Ask an "
                    "administrator to enter it in Integration settings.",
                    status.HTTP_502_BAD_GATEWAY,
                )
            payload["credential"] = credential

        try:
            message = await self._registry.request(
                node_id,
                "tunnel.open",
                payload,
                timeout_seconds=self._settings.tunnel_open_timeout_seconds,
            )
        except ApiError:
            # No tunnel exists, so no row may remain: it would be listed, counted against
            # all three limits, and closable by nobody.
            await self._repo.remove(tunnel)
            raise
        finally:
            payload.pop("credential", None)

        if not (message.type == "tunnel.opened" and message.success):
            code = "TUNNEL_PROVIDER_UNAVAILABLE"
            if message.error and isinstance(message.error.get("code"), str):
                code = str(message.error["code"])
            await self._repo.remove(tunnel)
            raise ApiError(code, "The tunnel could not be opened", status.HTTP_502_BAD_GATEWAY)

        url = message.payload.get("url")
        if not isinstance(url, str) or not url.startswith("https://"):
            await self._repo.remove(tunnel)
            raise ApiError(
                "TUNNEL_PROVIDER_UNAVAILABLE",
                "The provider did not return a usable URL",
                status.HTTP_502_BAD_GATEWAY,
            )
        # The provider answers an unusable credential by silently issuing an anonymous
        # tunnel instead of refusing (measured in PG-01 #10). The daemon aborts on that, and
        # this is the second check: handing over a tunnel nobody asked for, with none of the
        # paid tier's properties, would look like success.
        if credential is not None and message.payload.get("authenticated") is False:
            await self._close_on_node(node_id, tunnel.id)
            await self._repo.remove(tunnel)
            raise ApiError(
                "TUNNEL_PROVIDER_UNAUTHORIZED",
                "The provider did not accept the stored credential and offered an anonymous "
                "tunnel instead, which was rejected.",
                status.HTTP_502_BAD_GATEWAY,
            )

        tunnel.url = url
        tunnel.url_updated_at = now_utc()
        tunnel.upstream_expires_at = _parse_ts(message.payload.get("upstream_expires_at"))

        await self._audit.record(
            audit.TUNNEL_CREATE,
            user_id=actor.id,
            node_id=node_id,
            metadata={
                "port": port,
                "protection": chosen,
                "provider": tunnel.provider,
                "expires_at": tunnel.expires_at.isoformat(),
                # Which credential opened it, never the credential. `None` on the free tier,
                # where there is none. The key is `fingerprint` rather than
                # `credential_fingerprint` on purpose: the redaction pass masks any string
                # under a key containing "credential", so the more descriptive name would
                # store `***` and lose the fact being recorded (matching
                # `integration.credential_set`, which records it under the same key).
                "fingerprint": integration.token_fingerprint if credential else None,
            },
        )
        if chosen == "public":
            await self._audit.record(
                audit.TUNNEL_PUBLIC_ACKNOWLEDGED,
                user_id=actor.id,
                node_id=node_id,
                metadata={"port": port},
            )

        view = self._view(
            TunnelRow(tunnel=tunnel, node_name=node.name, created_by_username=actor.username),
            viewer=actor,
            now=now_utc(),
        )
        # The single response that carries the password. Everything downstream reads the
        # hash, so this value cannot be recovered later — only replaced by a rotation.
        return replace(view, basic_auth_password=password)

    # --- close, extend, rotate ---------------------------------------------------- #

    async def close(self, actor: User, tunnel_id: uuid.UUID, *, reason: str = "user") -> NodeTunnel:
        tunnel = await self._load(tunnel_id)
        if tunnel.closed_at is None:
            await self._end(tunnel, actor_id=actor.id, reason=reason)
        return tunnel

    async def extend(self, actor: User, tunnel_id: uuid.UUID) -> TunnelView:
        """Push the platform deadline out, up to the configured ceiling.

        The provider's own limit is untouched and unreachable from here — on the free tier
        it ends the tunnel after an hour regardless, and the daemon reconnects with a new
        URL. Extending is about our TTL only, which is why the two deadlines are separate
        columns.
        """
        integration = await self.require_integration_enabled()
        tunnel = await self._load(tunnel_id)
        now = now_utc()
        state = derive_state(tunnel, connected=self._registry.is_connected(tunnel.node_id), now=now)
        if state in (STATE_CLOSED, STATE_EXPIRED):
            raise ApiError(
                "TUNNEL_LIMIT_REACHED",
                "This tunnel has already ended. Create a new one.",
                status.HTTP_409_CONFLICT,
            )
        ceiling = now + timedelta(seconds=self._settings.tunnel_max_ttl_seconds)
        extended = tunnel.expires_at + timedelta(seconds=integration.default_ttl_seconds)
        if extended > ceiling:
            extended = ceiling
        if extended <= tunnel.expires_at:
            raise ApiError(
                "TUNNEL_LIMIT_REACHED",
                "This tunnel is already at the maximum lifetime this deployment allows.",
                status.HTTP_409_CONFLICT,
            )
        tunnel.expires_at = extended
        return await self.get(tunnel_id, actor)

    async def rotate_password(self, actor: User, tunnel_id: uuid.UUID) -> TunnelView:
        """Replace the basic-auth password, which means reopening the tunnel.

        The provider fixes its remote options when the connection is made, so there is no
        in-place change to make. Doing it honestly — close, open again, return a possibly
        different URL — is the only version that does not leave the caller believing the old
        URL still works.
        """
        tunnel = await self._load(tunnel_id)
        if tunnel.protection != "basic":
            raise ApiError(
                "INVALID_ARGUMENT",
                "Only a password-protected tunnel has a password to rotate.",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        remaining = int((tunnel.expires_at - now_utc()).total_seconds())
        port, node_id, label = tunnel.port, tunnel.node_id, tunnel.label
        rewrite_host = tunnel.rewrite_host
        await self._end(tunnel, actor_id=actor.id, reason="rotate")
        await self._session.flush()
        return await self.create(
            actor,
            node_id=node_id,
            port=port,
            protection="basic",
            label=label,
            ttl_seconds=max(remaining, 60),
            rewrite_host=rewrite_host,
            # Both already answered for this (user, node) pair: the row being rotated is the
            # proof, and asking again in the middle of a rotation would abort it.
            acknowledge_third_party=True,
        )

    async def close_for_node(
        self, node_id: uuid.UUID, *, actor_id: uuid.UUID | None, reason: str
    ) -> int:
        """End every live tunnel on a node (disable, removal, credential revocation).

        Called from the same paths that tear down sessions. The tunnel would also be
        reported as `unavailable` once the socket goes, but leaving the rows live would keep
        them counted against all three limits until their TTL ran out.
        """
        tunnels = await self._repo.live_for_node(node_id, now=now_utc())
        for tunnel in tunnels:
            await self._end(tunnel, actor_id=actor_id, reason=reason)
        return len(tunnels)

    async def _end(self, tunnel: NodeTunnel, *, actor_id: uuid.UUID | None, reason: str) -> None:
        tunnel.closed_at = now_utc()
        tunnel.closed_by = actor_id
        await self._audit.record(
            audit.TUNNEL_CLOSE,
            user_id=actor_id,
            node_id=tunnel.node_id,
            metadata={
                "port": tunnel.port,
                "reason": reason,
                # How often the provider reassigned the URL. The URLs themselves are not
                # recorded: a URL is part of the access credential, and the audit trail is
                # readable by every `audit.view` holder.
                "url_changed_count": tunnel.url_change_count,
            },
        )
        # The database is written first. The URL stops working when the provider says so, not
        # when we say so, so there is no ordering that makes the close atomic — what matters
        # is that our own record is settled even if the node never hears about it.
        await self._close_on_node(tunnel.node_id, tunnel.id)

    async def _close_on_node(self, node_id: uuid.UUID, tunnel_id: uuid.UUID) -> None:
        if not self._registry.is_connected(node_id):
            return
        try:
            await self._registry.request(
                node_id,
                "tunnel.close",
                {"tunnel_id": str(tunnel_id)},
                timeout_seconds=self._settings.tunnel_close_timeout_seconds,
            )
        except ApiError as exc:
            # A node that cannot be told is not a failed close: the daemon stops the child
            # at its TTL and reaps orphans on restart (PG-06), and our row is already
            # settled. Reporting a 502 here would leave the caller thinking the tunnel is
            # still open.
            log.info(
                "tunnel_close_not_delivered",
                extra={
                    "event": "tunnel_close_not_delivered",
                    "node_id": str(node_id),
                    "error_code": exc.code,
                },
            )

    # --- unsolicited status from the node ----------------------------------------- #

    async def apply_status(self, node_id: uuid.UUID, payload: dict[str, object]) -> None:
        """Apply a `tunnel.status` event (P11: the only unsolicited tunnel message).

        On the free tier the provider issues a new URL on every reconnect, so this is the
        path that keeps the platform's copy true. It is also why `reconnecting` does not
        clear `url`: the last known URL stays visible rather than blinking to empty, and the
        UI can say when it changed.
        """
        raw_id = payload.get("tunnel_id")
        state = payload.get("state")
        if not isinstance(raw_id, str) or not isinstance(state, str):
            return
        try:
            tunnel_id = uuid.UUID(raw_id)
        except ValueError:
            return
        tunnel = await self._repo.get(tunnel_id)
        if tunnel is None or tunnel.node_id != node_id or tunnel.closed_at is not None:
            return

        url = payload.get("url")
        expires = _parse_ts(payload.get("upstream_expires_at"))
        if state == "running":
            if isinstance(url, str) and url.startswith("https://") and url != tunnel.url:
                tunnel.url = url
                tunnel.url_updated_at = now_utc()
                tunnel.url_change_count += 1
            if expires is not None:
                tunnel.upstream_expires_at = expires
            tunnel.state_error_code = None
        elif state == "reconnecting":
            tunnel.state_error_code = None
        elif state == "failed":
            code = payload.get("error_code")
            tunnel.state_error_code = (
                str(code) if isinstance(code, str) else "TUNNEL_PROVIDER_UNAVAILABLE"
            )
            # Not closed automatically: the row is what carries the reason, and deciding
            # whether to retry or give up belongs to the person who created it.
        elif state == "closed":
            await self._end(tunnel, actor_id=None, reason="provider_failed")

    # --- helpers ------------------------------------------------------------------ #

    async def _load(self, tunnel_id: uuid.UUID) -> NodeTunnel:
        tunnel = await self._repo.get(tunnel_id)
        if tunnel is None:
            raise ApiError("NOT_FOUND", "Tunnel not found", status.HTTP_404_NOT_FOUND)
        return tunnel

    def _node_disabled_error(self, layer: str | None) -> ApiError:
        if layer == LAYER_INTEGRATION:
            return ApiError(
                "TUNNEL_INTEGRATION_DISABLED",
                "Port forwarding is not enabled for this deployment.",
                status.HTTP_404_NOT_FOUND,
            )
        if layer == LAYER_NODE_LOCAL:
            return ApiError(
                "TUNNEL_NODE_DISABLED",
                "This node refuses port forwarding in its own configuration "
                "(`tunnel.enabled: false` in /etc/agentd/config.yaml), or its agentd is too "
                "old to support it. The platform cannot override that; the node's owner has "
                "to change it.",
                status.HTTP_409_CONFLICT,
                details={"layer": LAYER_NODE_LOCAL},
            )
        return ApiError(
            "TUNNEL_NODE_DISABLED",
            "Port forwarding is turned off for this node in its platform settings. It can "
            "be turned back on from the node's port-forwarding page.",
            status.HTTP_409_CONFLICT,
            details={"layer": LAYER_NODE_SETTINGS},
        )

    def _prereq_detail(self, node: Node) -> str:
        detail = node.tunnel_prereq_detail
        if not isinstance(detail, dict):
            return "."
        missing = [
            name
            for key, name in (
                ("ssh_available", "an ssh client"),
                ("egress_ok", "outbound access to the provider"),
                ("known_hosts_ok", "the pinned provider host key"),
            )
            if detail.get(key) is False
        ]
        return f": it is missing {', '.join(missing)}." if missing else "."

    async def _enforce_limits(
        self,
        *,
        node: Node,
        actor: User,
        integration: TunnelIntegration,
        policy: EffectivePolicy,
        now: datetime,
    ) -> None:
        """Three independent limits with one code and three messages.

        One code because the caller's situation is the same ("not another one right now");
        three messages because what they can do about it is not: close somebody else's,
        close one on this node, or close one of their own.
        """
        fleet = await self._repo.count_live(now=now)
        if fleet >= integration.concurrent_budget:
            raise ApiError(
                "TUNNEL_LIMIT_REACHED",
                f"The deployment's concurrent tunnel budget is full "
                f"({fleet}/{integration.concurrent_budget}). Close a tunnel that is no "
                f"longer needed, or ask an administrator to raise the budget to match the "
                f"provider plan.",
                status.HTTP_409_CONFLICT,
            )
        on_node = await self._repo.count_live_for_node(node.id, now=now)
        if on_node >= policy.max_tunnels:
            raise ApiError(
                "TUNNEL_LIMIT_REACHED",
                f"This node already has {on_node} of {policy.max_tunnels} tunnels open.",
                status.HTTP_409_CONFLICT,
            )
        mine = await self._repo.count_live_for_user(actor.id, now=now)
        if mine >= self._settings.tunnels_per_user_max:
            raise ApiError(
                "TUNNEL_LIMIT_REACHED",
                f"You already have {mine} tunnels open, which is your limit.",
                status.HTTP_409_CONFLICT,
            )

    def _bounded_ttl(self, requested: int | None, integration: TunnelIntegration) -> int:
        ceiling = self._settings.tunnel_max_ttl_seconds
        if requested is None:
            return min(integration.default_ttl_seconds, ceiling)
        if requested < 60 or requested > ceiling:
            raise ApiError(
                "INVALID_ARGUMENT",
                f"A tunnel's lifetime must be between 60 and {ceiling} seconds.",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        return requested


def _validated_ips(values: Sequence[str] | None) -> list[str]:
    """Validate an IP allowlist for the provider's `w:` option.

    Parsed with `ipaddress` rather than a regular expression: the value is concatenated into
    a comma-separated option, and a permissive pattern is how something that is not an
    address ends up being read as another option.
    """
    if not values:
        return []
    if len(values) > _MAX_ALLOWED_IPS:
        raise ApiError(
            "INVALID_ARGUMENT",
            f"An IP allowlist holds at most {_MAX_ALLOWED_IPS} entries.",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    cleaned: list[str] = []
    for value in values:
        text = str(value).strip()
        try:
            if "/" in text:
                cleaned.append(str(ipaddress.ip_network(text, strict=False)))
            else:
                cleaned.append(str(ipaddress.ip_address(text)))
        except ValueError as exc:
            raise ApiError(
                "INVALID_ARGUMENT",
                f"'{text}' is not an IP address or CIDR range.",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
            ) from exc
    return cleaned


def _parse_ts(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
