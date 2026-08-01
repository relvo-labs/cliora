"""Integration settings API: the platform's port-forwarding provider account (PG-09, ADR 0022).

Four routes, all `integration.manage` (Admin only). They are the platform's side of a decision
a Developer may not make on the organisation's behalf: whether traffic may leave for a third
party at all, and on whose account.

Three properties of this surface are load-bearing:

* **No response carries the credential.** Not the full token, not a prefix, not a masked form.
  `TunnelCredentialDTO` has room for a fingerprint and nothing else, so there is no field for
  it to leak through — and `test_the_integration_response_never_carries_the_token` asserts it
  against the serialized JSON rather than against the type.
* **`secret_key_available` is reported, not discovered.** Without it, an administrator on a
  deployment with no encryption key finds out by typing a credential and getting a 503.
* **There is no "test connection" route.** Testing means opening a real tunnel on a real node,
  which is an outward exposure the user did not ask for, and it would fail for exactly the
  reasons a real creation fails. The first tunnel on the node's own page is the test (PG-09
  §0.3).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.http.deps import require_action
from app.api.http.schemas import (
    SetTunnelCredentialRequest,
    TunnelIntegrationDTO,
    UpdateTunnelIntegrationRequest,
)
from app.clock import now_utc
from app.db.engine import get_session
from app.db.models import User
from app.repositories.tunnels import TunnelRepository
from app.services.integrations import IntegrationService
from app.services.rbac import INTEGRATION_MANAGE

router = APIRouter(prefix="/api/integrations/tunnel", tags=["integrations"])


async def _dto(session: AsyncSession, service: IntegrationService) -> TunnelIntegrationDTO:
    return TunnelIntegrationDTO.from_view(
        await service.view(),
        active_tunnel_count=await TunnelRepository(session).count_live(now=now_utc()),
    )


@router.get("", response_model=TunnelIntegrationDTO)
async def get_integration(
    _: User = Depends(require_action(INTEGRATION_MANAGE)),
    session: AsyncSession = Depends(get_session),
) -> TunnelIntegrationDTO:
    return await _dto(session, IntegrationService(session))


@router.put("", response_model=TunnelIntegrationDTO)
async def update_integration(
    body: UpdateTunnelIntegrationRequest,
    user: User = Depends(require_action(INTEGRATION_MANAGE)),
    session: AsyncSession = Depends(get_session),
) -> TunnelIntegrationDTO:
    service = IntegrationService(session)
    await service.update(
        user,
        enabled=body.enabled,
        plan_tier=body.plan_tier,
        concurrent_budget=body.concurrent_budget,
        default_protection=body.default_protection,
        default_ttl_seconds=body.default_ttl_seconds,
        allowed_ports=body.allowed_ports,
        clear_allowed_ports=body.clear_allowed_ports,
        acknowledge=body.acknowledge,
    )
    dto = await _dto(session, service)
    await session.commit()
    return dto


@router.put("/credential", response_model=TunnelIntegrationDTO)
async def set_credential(
    body: SetTunnelCredentialRequest,
    user: User = Depends(require_action(INTEGRATION_MANAGE)),
    session: AsyncSession = Depends(get_session),
) -> TunnelIntegrationDTO:
    """Store or replace the provider credential.

    Write-only by construction: the response is the same settings object every other route
    returns, so there is no shape in which this could echo what was just submitted.
    """
    service = IntegrationService(session)
    await service.set_credential(user, body.token, body.plan_tier)
    dto = await _dto(session, service)
    await session.commit()
    return dto


@router.delete("/credential", response_model=TunnelIntegrationDTO)
async def clear_credential(
    user: User = Depends(require_action(INTEGRATION_MANAGE)),
    session: AsyncSession = Depends(get_session),
) -> TunnelIntegrationDTO:
    service = IntegrationService(session)
    await service.clear_credential(user)
    dto = await _dto(session, service)
    await session.commit()
    return dto
