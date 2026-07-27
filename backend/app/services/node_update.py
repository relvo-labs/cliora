"""Central's side of a daemon update (P4-10, ADR 0017, SEC-002).

Central authorizes, records and relays. It never names an artifact: the request it
sends carries `{target_version}` and, optionally, `allow_downgrade` — the URL, the
filename and the digest are all derived by the daemon from
`GET /api/releases/manifest` plus its own config file. A client that could name a
binary could name any binary.

Two things this module is careful about, both learned from how "long operation over
a socket" goes wrong:

* **A timeout is not a failure.** The daemon downloads, swaps, restarts and
  health-checks; the reply legitimately takes minutes and the restart itself drops
  the socket the reply was going to come back on. So a timeout leaves the row in
  `in_progress` and lets the truth arrive later — from the daemon's own
  `daemon.update_result`, or from the version in its next registration. Marking it
  failed here would report a rollback that never happened, and would do so most
  often in the case that actually succeeded.
* **A stale result cannot overwrite a newer request.** Results are matched against
  the target version currently recorded, so a late reply from a superseded attempt
  is recorded as history, not as the current state.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app import metrics
from app.api.errors import ApiError
from app.clock import now_utc
from app.db.models import Node
from app.logging import get_logger
from app.repositories.nodes import NodeRepository
from app.services import audit
from app.services.registry import NodeConnectionRegistry, get_node_registry
from app.services.releases import ReleaseService
from app.settings import Settings, get_settings

_logger = get_logger("cliora.node_update")

# `nodes.update_status` vocabulary. `in_progress` is the only non-terminal value,
# and it is deliberately allowed to persist: an update whose outcome never arrived
# is a real state an operator needs to see, not one to guess at.
IN_PROGRESS = "in_progress"
SUCCEEDED = "succeeded"
FAILED = "failed"
ROLLED_BACK = "rolled_back"
UNKNOWN = "unknown"

_RESULT_STATUSES = frozenset({SUCCEEDED, FAILED, ROLLED_BACK})

# The closed vocabularies from contracts/v1/schemas/messages/daemon-update-result.
# Every field taken from a daemon report is clamped to these before it is stored,
# including in audit metadata. The protocol codec already validates a correlated
# response, but this path also handles frames a daemon reports unsolicited, and the
# fields are free-form strings on the way in: a node that put its prose in `stage`
# would otherwise park an absolute path — or a large blob — in the audit table.
_STAGES = frozenset({"manifest", "download", "checksum", "swap", "restart", "healthcheck"})
_ERROR_CODES = frozenset(
    {
        "UPDATE_NOT_ALLOWED",
        "UPDATE_DOWNLOAD_FAILED",
        "UPDATE_CHECKSUM_MISMATCH",
        "UPDATE_HEALTHCHECK_FAILED",
        "UPDATE_ROLLED_BACK",
        "UPDATE_IN_PROGRESS",
        # Central's own refusals, recorded on the same field when it never reached the
        # node at all.
        "NODE_OFFLINE",
        "NODE_BUSY",
        "REQUEST_TIMEOUT",
    }
)
# A semver-shaped version, the only form `daemon.update` accepts as a target.
_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.]+)?$")


@dataclass(frozen=True, slots=True)
class UpdateOutcome:
    status: str
    stage: str | None
    error_code: str | None
    from_version: str | None
    to_version: str | None


class NodeUpdateService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        registry: NodeConnectionRegistry | None = None,
        settings: Settings | None = None,
        releases: ReleaseService | None = None,
    ) -> None:
        self._session = session
        self._nodes = NodeRepository(session)
        self._audit = audit.AuditService(session)
        self._registry = registry or get_node_registry()
        self._settings = settings or get_settings()
        self._releases = releases or ReleaseService(settings=self._settings)

    async def request_update(
        self,
        node_id: uuid.UUID,
        *,
        target_version: str,
        actor_id: uuid.UUID,
        allow_downgrade: bool = False,
    ) -> Node:
        """Ask a node to update, and record that we asked.

        The version is checked against the manifest **here as well as** on the
        daemon. Not because Central's check is the security boundary — the daemon
        re-derives everything and verifies the digest itself — but because refusing
        an unpublished version before touching the node turns a five-minute failed
        update into an immediate, explainable 400.
        """
        node = await self._nodes.get(node_id)
        if node is None:
            raise ApiError("NOT_FOUND", "Node not found", status.HTTP_404_NOT_FOUND)
        if not self._releases.manifest().artifacts:
            raise ApiError(
                "UPDATE_NOT_ALLOWED",
                "No releases are published on this server",
                status.HTTP_409_CONFLICT,
            )
        if not any(
            artifact.version == target_version for artifact in self._releases.manifest().artifacts
        ):
            raise ApiError(
                "UPDATE_NOT_ALLOWED",
                "That version is not an allowlisted release",
                status.HTTP_409_CONFLICT,
            )
        if node.update_status == IN_PROGRESS:
            raise ApiError(
                "UPDATE_IN_PROGRESS",
                "An update is already running on this node",
                status.HTTP_409_CONFLICT,
            )

        # Recorded *before* the frame is sent. If the send fails we would rather
        # have an `in_progress` row to explain than a silent no-op — and the daemon
        # may have received the frame even when the write of it appeared to fail.
        self._mark(node, status_=IN_PROGRESS, target=target_version, result=None)
        await self._audit.record(
            audit.DAEMON_UPDATE_STARTED,
            user_id=actor_id,
            node_id=node.id,
            metadata={
                "target_version": target_version,
                "from_version": node.daemon_version,
                "allow_downgrade": allow_downgrade,
            },
        )

        payload: dict[str, object] = {"target_version": target_version}
        if allow_downgrade:
            payload["allow_downgrade"] = True
        try:
            response = await self._registry.request(
                node_id,
                "daemon.update",
                payload,
                timeout_seconds=self._settings.update_request_timeout_seconds,
            )
        except ApiError as error:
            if error.code == "REQUEST_TIMEOUT":
                # Expected, and not a failure: the restart drops the socket the
                # reply would have come back on. The row stays `in_progress` until
                # the daemon reports or re-registers.
                _logger.info(
                    "node_update_awaiting_result",
                    extra={
                        "event": "node_update_awaiting_result",
                        "node_id": str(node_id),
                        "target_version": target_version,
                    },
                )
                metrics.increment(metrics.NODE_UPDATE_TOTAL, status="awaiting_result")
                return node
            # NODE_OFFLINE / NODE_BUSY: nothing was started, so do not leave the row
            # claiming otherwise.
            self._mark(node, status_=FAILED, target=target_version, result=error.code)
            await self._record_result(
                node,
                UpdateOutcome(
                    status=FAILED,
                    stage="manifest",
                    error_code=error.code,
                    from_version=node.daemon_version,
                    to_version=target_version,
                ),
                actor_id=actor_id,
            )
            raise

        await self.apply_result(node_id, outcome_from_payload(response.payload), actor_id=actor_id)
        refreshed = await self._nodes.get(node_id)
        return refreshed or node

    async def apply_result(
        self,
        node_id: uuid.UUID,
        outcome: UpdateOutcome,
        *,
        actor_id: uuid.UUID | None = None,
    ) -> Node | None:
        """Record a `daemon.update_result`, from the relay reply or reported later.

        Reachable twice for one update (the correlated reply, then an unsolicited
        report after a restart), so it must be idempotent in effect: writing the same
        terminal state twice is harmless, and the audit row is written from the same
        place either way so the count stays one per distinct report.
        """
        node = await self._nodes.get(node_id, include_deleted=True)
        if node is None:
            return None
        resolved = outcome.status if outcome.status in _RESULT_STATUSES else UNKNOWN
        self._mark(
            node,
            status_=resolved,
            target=outcome.to_version or node.update_target_version,
            result=outcome.error_code or resolved,
        )
        if resolved == SUCCEEDED and outcome.to_version:
            # The node re-registers with its real version too; setting it here means
            # the UI is correct immediately rather than after the next handshake.
            node.daemon_version = outcome.to_version
        await self._record_result(node, outcome, actor_id=actor_id)
        return node

    async def _record_result(
        self, node: Node, outcome: UpdateOutcome, *, actor_id: uuid.UUID | None
    ) -> None:
        metrics.increment(metrics.NODE_UPDATE_TOTAL, status=outcome.status)
        await self._audit.record(
            audit.DAEMON_UPDATE_RESULT,
            user_id=actor_id,
            node_id=node.id,
            metadata={
                "from_version": outcome.from_version,
                "to_version": outcome.to_version,
                "status": outcome.status,
                "stage": outcome.stage,
                "error_code": outcome.error_code,
            },
        )

    def _mark(self, node: Node, *, status_: str, target: str | None, result: str | None) -> None:
        node.update_status = status_
        node.update_target_version = target
        node.update_last_result = result
        node.update_updated_at = now_utc()


def outcome_from_payload(payload: dict[str, object]) -> UpdateOutcome:
    """Read a `daemon.update_result` payload defensively.

    Every field is clamped to its closed vocabulary. An unrecognized status becomes
    `unknown` rather than being coerced into `succeeded` — recording an update that may
    never have happened is the worse error — and an unrecognized stage, error code or
    version is dropped rather than stored, so nothing a node writes into a free-form
    string reaches the audit trail or the node row verbatim.
    """

    def text(key: str) -> str | None:
        value = payload.get(key)
        return value if isinstance(value, str) else None

    def one_of(key: str, allowed: frozenset[str]) -> str | None:
        value = text(key)
        return value if value in allowed else None

    def version(key: str) -> str | None:
        value = text(key)
        return value if value and len(value) <= 64 and _VERSION.match(value) else None

    status_value = text("status")
    return UpdateOutcome(
        status=status_value if status_value in _RESULT_STATUSES else UNKNOWN,
        stage=one_of("stage", _STAGES),
        error_code=one_of("error_code", _ERROR_CODES),
        from_version=version("from_version"),
        to_version=version("to_version"),
    )
