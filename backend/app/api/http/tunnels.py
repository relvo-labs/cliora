"""Tunnels API: create, list, close, extend, rotate, and the per-node policy page (PG-08).

Every route answers 404 when the integration is switched off, and the switch is a database
row rather than an environment variable — an administrator turning it off in the UI must make
the API agree immediately, not at the next deploy.

Two shapes here are worth reading twice:

* `POST /api/tunnels` and `POST /api/tunnels/{id}/rotate-password` return `TunnelDetail`, the
  one DTO with `basic_auth_password`. Every other route returns `TunnelSummary`, which has no
  field it could appear in.
* `rotate-password` is implemented as close-and-reopen, because the provider fixes its remote
  options when the connection is made. The response therefore carries a possibly different
  `url`, and the UI says so: pretending it was an in-place change is what would leave someone
  handing out a dead link.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.api.http.deps import require_action
from app.api.http.schemas import (
    CreateTunnelRequest,
    NodeTunnelPolicyDTO,
    TunnelDetail,
    TunnelSummary,
    UpdateNodeTunnelSettingsRequest,
)
from app.clock import now_utc
from app.db.engine import get_session
from app.db.models import User
from app.repositories.integrations import IntegrationRepository
from app.repositories.nodes import NodeRepository
from app.repositories.tunnels import TunnelRepository
from app.services import authz
from app.services.integrations import IntegrationService
from app.services.rbac import TUNNEL_MANAGE, TUNNEL_VIEW
from app.services.registry import NodeConnectionRegistry, get_node_registry
from app.services.tunnels import TunnelService, node_report_layer

router = APIRouter(prefix="/api", tags=["tunnels"])


def get_registry() -> NodeConnectionRegistry:
    """Registry dependency (overridable in tests), matching the sessions API."""
    return get_node_registry()


def _service(session: AsyncSession, registry: NodeConnectionRegistry) -> TunnelService:
    return TunnelService(session, registry=registry)


@router.get("/tunnels", response_model=list[TunnelSummary])
async def list_tunnels(
    node_id: uuid.UUID | None = None,
    mine: bool = Query(default=False),
    include_ended: bool = Query(default=False),
    user: User = Depends(require_action(TUNNEL_VIEW)),
    session: AsyncSession = Depends(get_session),
    registry: NodeConnectionRegistry = Depends(get_registry),
) -> list[TunnelSummary]:
    """Every `tunnel.view` holder sees the fleet's tunnels; per-row capabilities say which
    ones they may act on. Viewer holds neither action (ADR 0022): being able to read a URL is
    being able to reach the application behind it, and a platform role cannot promise that
    application is read-only."""
    service = _service(session, registry)
    await service.require_integration_enabled()
    views = await service.list(user, node_id=node_id, mine=mine, include_ended=include_ended)
    return [TunnelSummary.from_view(view) for view in views]


@router.post("/tunnels", response_model=TunnelDetail, status_code=status.HTTP_201_CREATED)
async def create_tunnel(
    body: CreateTunnelRequest,
    user: User = Depends(require_action(TUNNEL_MANAGE)),
    session: AsyncSession = Depends(get_session),
    registry: NodeConnectionRegistry = Depends(get_registry),
) -> TunnelDetail:
    service = _service(session, registry)
    try:
        view = await service.create(
            user,
            node_id=body.node_id,
            port=body.port,
            protection=body.protection,
            allowed_ips=body.allowed_ips,
            label=body.label,
            ttl_seconds=body.ttl_seconds,
            rewrite_host=body.rewrite_host,
            acknowledge_third_party=body.acknowledge_third_party,
            acknowledge_public=body.acknowledge_public,
        )
    except ApiError:
        # The service removes the row itself when the node refuses or does not answer; this
        # commit is what makes that removal — and the audit rows written before it — durable.
        await session.commit()
        raise
    await session.commit()
    return TunnelDetail.from_view(view)


@router.delete("/tunnels/{tunnel_id}", status_code=status.HTTP_204_NO_CONTENT)
async def close_tunnel(
    tunnel_id: uuid.UUID,
    user: User = Depends(require_action(TUNNEL_MANAGE)),
    session: AsyncSession = Depends(get_session),
    registry: NodeConnectionRegistry = Depends(get_registry),
) -> Response:
    service = _service(session, registry)
    await service.require_integration_enabled()
    # Load first, then check ownership: holding `tunnel.manage` is not enough to close
    # somebody else's exposure unless you are an administrator (ADR 0016).
    existing = await service.get(tunnel_id, user)
    authz.authorize_tunnel_close(user, existing.tunnel)
    await service.close(user, tunnel_id)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/tunnels/{tunnel_id}/extend", response_model=TunnelSummary)
async def extend_tunnel(
    tunnel_id: uuid.UUID,
    user: User = Depends(require_action(TUNNEL_MANAGE)),
    session: AsyncSession = Depends(get_session),
    registry: NodeConnectionRegistry = Depends(get_registry),
) -> TunnelSummary:
    service = _service(session, registry)
    await service.require_integration_enabled()
    existing = await service.get(tunnel_id, user)
    authz.authorize_tunnel_close(user, existing.tunnel)
    view = await service.extend(user, tunnel_id)
    await session.commit()
    return TunnelSummary.from_view(view)


@router.post("/tunnels/{tunnel_id}/rotate-password", response_model=TunnelDetail)
async def rotate_tunnel_password(
    tunnel_id: uuid.UUID,
    user: User = Depends(require_action(TUNNEL_MANAGE)),
    session: AsyncSession = Depends(get_session),
    registry: NodeConnectionRegistry = Depends(get_registry),
) -> TunnelDetail:
    """Replace the one-time password. **The URL may change**: this closes the tunnel and
    opens a new one, because the provider's remote options are fixed at connection time."""
    service = _service(session, registry)
    await service.require_integration_enabled()
    existing = await service.get(tunnel_id, user)
    authz.authorize_tunnel_close(user, existing.tunnel)
    try:
        view = await service.rotate_password(user, tunnel_id)
    except ApiError:
        # The old tunnel is closed either way — that part succeeded and must not be rolled
        # back into a row that claims to be live with a password nobody holds.
        await session.commit()
        raise
    await session.commit()
    return TunnelDetail.from_view(view)


@router.get("/nodes/{node_id}/tunnel-policy", response_model=NodeTunnelPolicyDTO)
async def get_node_tunnel_policy(
    node_id: uuid.UUID,
    _: User = Depends(require_action(TUNNEL_VIEW)),
    session: AsyncSession = Depends(get_session),
    registry: NodeConnectionRegistry = Depends(get_registry),
) -> NodeTunnelPolicyDTO:
    """The effective policy for one node **and what each layer contributed**.

    The per-layer breakdown is the page's most useful part: three layers mean a refusal has
    three possible causes, and the remedy differs for each (a platform setting, this node's
    platform setting, or the node owner's config file).
    """
    service = _service(session, registry)
    integration = await service.require_integration_enabled()
    node = await NodeRepository(session).get(node_id)
    if node is None:
        raise ApiError("NODE_NOT_FOUND", "Node not found", status.HTTP_404_NOT_FOUND)
    policy = await service.policy_for(node)
    node_settings = await IntegrationRepository(session).get_node_settings(node_id)
    report = node_report_layer(node)
    return NodeTunnelPolicyDTO(
        node_id=node_id,
        enabled=policy.enabled,
        blocked_by=policy.blocked_by,
        allowed_ports=[
            f"{low}" if low == high else f"{low}-{high}" for low, high in policy.allowed_ports
        ],
        max_tunnels=policy.max_tunnels,
        live_tunnel_count=await TunnelRepository(session).count_live_for_node(
            node_id, now=now_utc()
        ),
        node_enabled=node_settings.enabled if node_settings is not None else True,
        node_allowed_ports=list(node_settings.allowed_ports)
        if node_settings is not None and node_settings.allowed_ports is not None
        else None,
        node_max_tunnels=node_settings.max_tunnels if node_settings is not None else None,
        local_veto=report.veto,
        prereq_ok=report.prereq_ok,
        prereq_detail=node.tunnel_prereq_detail,
        local_allowed_ports=report.allowed_ports,
        local_max_tunnels=report.max_tunnels,
        reported_at=report.reported_at,
        plan_tier=integration.plan_tier,
        default_protection=integration.default_protection,
        default_ttl_seconds=integration.default_ttl_seconds,
    )


@router.put("/nodes/{node_id}/tunnel-settings", response_model=NodeTunnelPolicyDTO)
async def update_node_tunnel_settings(
    node_id: uuid.UUID,
    body: UpdateNodeTunnelSettingsRequest,
    user: User = Depends(require_action(TUNNEL_MANAGE)),
    session: AsyncSession = Depends(get_session),
    registry: NodeConnectionRegistry = Depends(get_registry),
) -> NodeTunnelPolicyDTO:
    """`tunnel.manage`, not `integration.manage`.

    Deciding which ports one machine may forward is day-to-day work for whoever uses that
    machine. Deciding whether the organisation uses this provider at all, and on whose
    account, is not — that stays Admin-only on the integration routes (ADR 0022 §2.3).
    """
    service = _service(session, registry)
    await service.require_integration_enabled()
    node = await NodeRepository(session).get(node_id)
    if node is None:
        raise ApiError("NODE_NOT_FOUND", "Node not found", status.HTTP_404_NOT_FOUND)
    await IntegrationService(session).update_node_settings(
        user,
        node_id,
        enabled=body.enabled,
        allowed_ports=body.allowed_ports,
        max_tunnels=body.max_tunnels,
        clear_allowed_ports=body.clear_allowed_ports,
        clear_max_tunnels=body.clear_max_tunnels,
    )
    await session.commit()
    return await get_node_tunnel_policy(node_id, user, session, registry)
