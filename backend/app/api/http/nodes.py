from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.api.http.deps import require_action
from app.api.http.schemas import (
    NodeDetail,
    NodeResourcesDTO,
    NodeRuntimeDTO,
    NodeSummary,
    NodeWorkspaceRootDTO,
    RegisterNodeRequest,
    RegisterNodeResponse,
    RotateCredentialRequest,
    SetNodeEnabledRequest,
    UpdateNodeRequest,
    UpdateStatusDTO,
)
from app.db.engine import get_session
from app.db.models import Node, User
from app.services.node_update import NodeUpdateService
from app.services.nodes import NodeManagementService, NodeRegistrationService
from app.services.rbac import NODE_MANAGE, NODE_VIEW
from app.services.registry import NodeConnectionRegistry, compute_status, get_node_registry
from app.services.releases import ReleaseService
from app.settings import Settings, get_settings

router = APIRouter(prefix="/api/nodes", tags=["nodes"])


def _status(node: Node, registry: NodeConnectionRegistry, settings: Settings) -> str:
    return compute_status(
        is_enabled=node.is_enabled,
        seconds_since_heartbeat=registry.seconds_since_heartbeat(node.id),
        online_within=settings.node_online_within_seconds,
        degraded_within=settings.node_degraded_within_seconds,
    )


def _runtime_available(node: Node, runtime_id: str) -> bool:
    return any(r.runtime == runtime_id and r.available for r in node.runtimes)


def _summary(node: Node, registry: NodeConnectionRegistry, settings: Settings) -> NodeSummary:
    return NodeSummary(
        id=node.id,
        name=node.name,
        hostname=node.hostname,
        status=_status(node, registry, settings),
        os=node.os,
        architecture=node.architecture,
        claude_available=_runtime_available(node, "claude"),
        codex_available=_runtime_available(node, "codex"),
        session_count=0,  # sessions arrive in P2
        last_seen_at=node.last_seen_at,
    )


def _resources(node: Node, registry: NodeConnectionRegistry) -> NodeResourcesDTO | None:
    """Latest heartbeat resource sample from the live socket (null when offline)."""
    sample = registry.resources_for(node.id)
    if sample is None:
        return None
    return NodeResourcesDTO(**{k: sample.get(k) for k in NodeResourcesDTO.model_fields})


def _update_status(node: Node, settings: Settings) -> UpdateStatusDTO:
    return UpdateStatusDTO(
        current_version=node.daemon_version,
        latest_version=ReleaseService(settings=settings).manifest().latest,
        status=node.update_status,
        target_version=node.update_target_version,
        last_result=node.update_last_result,
        updated_at=node.update_updated_at,
    )


def _detail(node: Node, registry: NodeConnectionRegistry, settings: Settings) -> NodeDetail:
    summary = _summary(node, registry, settings)
    return NodeDetail(
        **summary.model_dump(),
        os_version=node.os_version,
        daemon_version=node.daemon_version,
        run_user=node.run_user,
        privileged_terminal=node.privileged_terminal,
        is_enabled=node.is_enabled,
        registered_at=node.registered_at,
        runtimes=[
            NodeRuntimeDTO(
                runtime=r.runtime,
                available=r.available,
                version=r.version,
                binary_path=r.binary_path,
                checked_at=r.checked_at,
                sandbox_bypass=r.sandbox_bypass,
            )
            for r in node.runtimes
        ],
        workspace_roots=[
            NodeWorkspaceRootDTO(path=w.path, display_name=w.display_name, is_enabled=w.is_enabled)
            for w in node.workspace_roots
        ],
        resources=_resources(node, registry),
        update_status=_update_status(node, settings),
        # P1 keeps no structured node error history; the section renders empty.
        recent_errors=[],
    )


@router.post("/register", response_model=RegisterNodeResponse, status_code=201)
async def register_node(
    body: RegisterNodeRequest,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> RegisterNodeResponse:
    """Unauthenticated except by the enrollment token itself (the daemon has no
    session yet). The daemon private key never leaves the node."""
    registered = await NodeRegistrationService(session).register(body.token, body.to_input())
    await session.commit()
    return RegisterNodeResponse(
        node_id=registered.node.id,
        server_url=settings.public_base_url,
    )


@router.get("", response_model=list[NodeSummary])
async def list_nodes(
    _: User = Depends(require_action(NODE_VIEW)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> list[NodeSummary]:
    registry = get_node_registry()
    nodes = await NodeManagementService(session).list_active()
    return [_summary(node, registry, settings) for node in nodes]


@router.get("/{node_id}", response_model=NodeDetail)
async def get_node(
    node_id: uuid.UUID,
    _: User = Depends(require_action(NODE_VIEW)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> NodeDetail:
    node = await NodeManagementService(session).get(node_id)
    if node is None:
        raise ApiError("NOT_FOUND", "Node not found", status.HTTP_404_NOT_FOUND)
    return _detail(node, get_node_registry(), settings)


@router.post("/{node_id}/enabled", response_model=NodeDetail)
async def set_node_enabled(
    node_id: uuid.UUID,
    body: SetNodeEnabledRequest,
    user: User = Depends(require_action(NODE_MANAGE)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> NodeDetail:
    service = NodeManagementService(session)
    await service.set_enabled(
        node_id,
        enabled=body.enabled,
        actor_id=user.id,
        terminate_sessions=body.terminate_sessions,
    )
    await session.commit()
    node = await service.get(node_id)
    assert node is not None
    return _detail(node, get_node_registry(), settings)


@router.post("/{node_id}/credential/revoke", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_node_credential(
    node_id: uuid.UUID,
    user: User = Depends(require_action(NODE_MANAGE)),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Revoke the node's credential and immediately sever its live connection."""
    await NodeManagementService(session).revoke_credential(node_id, actor_id=user.id)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{node_id}/credential/rotate", response_model=NodeDetail)
async def rotate_node_credential(
    node_id: uuid.UUID,
    body: RotateCredentialRequest,
    user: User = Depends(require_action(NODE_MANAGE)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> NodeDetail:
    """Rotate to a new credential version (revoke old, issue next, drop socket)."""
    service = NodeManagementService(session)
    await service.rotate_credential(node_id, public_key=body.public_key, actor_id=user.id)
    await session.commit()
    node = await service.get(node_id)
    assert node is not None
    return _detail(node, get_node_registry(), settings)


@router.post("/{node_id}/update", response_model=NodeDetail)
async def update_node(
    node_id: uuid.UUID,
    body: UpdateNodeRequest,
    user: User = Depends(require_action(NODE_MANAGE)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> NodeDetail:
    """Ask a node to update to an allowlisted release.

    The body carries a version and nothing else — no URL, no filename, no digest
    (SEC-002). A 200 does not mean the update finished: the daemon restarts during
    it, so the reply may be the state as of the request being accepted, with the
    outcome arriving later via `daemon.update_result`.
    """
    service = NodeUpdateService(session, settings=settings)
    try:
        node = await service.request_update(
            node_id,
            target_version=body.target_version,
            actor_id=user.id,
            allow_downgrade=body.allow_downgrade,
        )
    except ApiError:
        # The refusal was recorded against the node (offline, busy); that row must
        # survive the raise, exactly as a failed login's audit does (P4-04).
        await session.commit()
        raise
    await session.commit()
    refreshed = await NodeManagementService(session).get(node_id)
    return _detail(refreshed or node, get_node_registry(), settings)


@router.delete("/{node_id}")
async def remove_node(
    node_id: uuid.UUID,
    user: User = Depends(require_action(NODE_MANAGE)),
    session: AsyncSession = Depends(get_session),
) -> Response:
    await NodeManagementService(session).remove(node_id, actor_id=user.id)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
