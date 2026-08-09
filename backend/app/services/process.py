"""The internalised process: lanes, readiness items and review gates (ADR 0028 sec 1).

Monstrare's process (MIT) as platform data. The row is seeded by migration `0026`;
this module is the only place that reads it, and the only place that decides what the
definition *means* — which in V2.1 is two things:

1. **Which gate is available**, because one of them depends on an integration that may
   not be switched on (§`effective`).
2. **What actually refuses**, which in this phase is exactly one rule: a card may not
   enter `ready` or beyond while a dependency is unfinished. Definition of Ready and
   WIP report and do not refuse — enforcing all seven readiness items from day one is
   how a board stops being written to, and an unused board is a source of truth
   nobody updates.

There is one definition for the whole deployment (`key = 'default'`). V2.4 adds a
minimal per-project override; building configurability before anyone has asked for it
is the easiest thing in this system to over-build (research/02/01 D15).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ProcessDefinition

DEFAULT_KEY = "default"

# The lane order is the board's left-to-right order and also the boundary below: any
# lane from `ready` onwards asks for its dependencies to be finished.
LANE_ORDER = ("backlog", "blocked", "ready", "implementing", "verify", "done")
STAGES = frozenset(LANE_ORDER)

# Entering one of these means claiming the card is workable, which is the claim an
# unfinished dependency contradicts. `blocked` is deliberately *not* in the set: a
# card is moved there precisely because something is in the way.
DEPENDENCY_GATED_STAGES = frozenset({"ready", "implementing", "verify", "done"})


@dataclass(frozen=True, slots=True)
class Gate:
    """One review gate as the API presents it.

    ``requires_human`` is always true today and is carried through from the data
    rather than hardcoded here: "an agent's output is not an approval" needs to be
    something a reader can point at, and V2.2's runner code reads the same field.

    ``disabled_reason`` is set only when the gate is derived-disabled; a gate that is
    simply unapproved is *available*, not disabled.
    """

    key: str
    label: str
    order: int
    requires_human: bool
    enabled: bool
    disabled_reason: str | None


@dataclass(frozen=True, slots=True)
class EffectiveProcess:
    """The definition as it applies right now, integration state included."""

    key: str
    version: str
    source: str
    lanes: list[dict[str, Any]]
    readiness: list[dict[str, Any]]
    gates: list[Gate]
    templates: dict[str, Any]

    def gate(self, key: str) -> Gate | None:
        return next((gate for gate in self.gates if gate.key == key), None)

    def readiness_keys(self) -> list[str]:
        return [item["key"] for item in self.readiness]

    def wip_for(self, stage: str) -> int | None:
        for lane in self.lanes:
            if lane.get("stage") == stage:
                value = lane.get("wip_suggested")
                return int(value) if value is not None else None
        return None


class ProcessService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def definition(self, key: str = DEFAULT_KEY) -> ProcessDefinition:
        row = (
            await self._session.execute(
                select(ProcessDefinition).where(ProcessDefinition.key == key)
            )
        ).scalar_one_or_none()
        if row is None:  # pragma: no cover - the seed migration guarantees the row
            raise RuntimeError(
                "no process definition seeded; run `alembic upgrade head` "
                "(migration 0026 seeds the default one)"
            )
        return row

    async def effective(self, key: str = DEFAULT_KEY) -> EffectiveProcess:
        """The definition with integration-dependent gates resolved.

        The `ui` gate needs a way to show a running mockup, and the only one the
        platform has is the third-party tunnel integration (ADR 0022, D31). When that
        integration is off the gate is **disabled here, on read** — not by an
        administrator remembering to switch it off. A gate nobody can ever satisfy is
        a deadlock, and a deadlock that depends on someone's memory is a worse one.

        Disabled is not hidden: `disabled_reason` travels with the gate so the console
        can say *why* it is not there. A gate that quietly does not exist is worse
        than one that explains itself.
        """
        row = await self.definition(key)
        integrations_enabled = await self._integration_states()
        gates = []
        for raw in sorted(row.gates, key=lambda item: item.get("order", 0)):
            needs = raw.get("depends_on_integration")
            enabled = True
            reason: str | None = None
            if needs is not None and not integrations_enabled.get(needs, False):
                enabled = False
                reason = f"{needs}_integration_disabled"
            gates.append(
                Gate(
                    key=raw["key"],
                    label=raw.get("label", raw["key"]),
                    order=int(raw.get("order", 0)),
                    requires_human=bool(raw.get("requires_human", True)),
                    enabled=enabled,
                    disabled_reason=reason,
                )
            )
        return EffectiveProcess(
            key=row.key,
            version=row.version,
            source=row.source,
            lanes=sorted(row.lanes, key=lambda item: item.get("order", 0)),
            readiness=list(row.readiness),
            gates=gates,
            templates=dict(row.templates),
        )

    async def _integration_states(self) -> dict[str, bool]:
        """Which integrations a gate may depend on, and whether they are on.

        Imported here rather than at module scope because `services.integrations`
        reaches back into settings and the secret box; a top-level import would pull
        both into every module that only wants to know what a lane is called.
        """
        from app.services.integrations import IntegrationService

        return {"tunnel": await IntegrationService(self._session).is_enabled()}
