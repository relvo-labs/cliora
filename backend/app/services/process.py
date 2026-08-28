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

There is one definition for the whole deployment (`key = 'default'`), and since V2.4 a
project may **disable** items in it — never add one, never change a lane. That
narrowness is what keeps cross-project metrics comparing like with like, and it is the
reason the override is a JSONB column on `projects` rather than a table: a table invites
somebody to put a custom readiness item in it (ADR 0033 §5, D13).

**The override cannot reach the Done Gate.** Its six conditions are constants in
`services/done_gate.py` and deliberately absent from `process_definitions`. Otherwise
the first person who finds the gate inconvenient disables it, and that leaves no trace —
while `--force` leaves three.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.db.models import ProcessDefinition, Project
from app.services import audit as audit_actions
from app.services.audit import AuditService

DEFAULT_KEY = "default"

# The lane order is the board's left-to-right order and also the boundary below: any
# lane from `ready` onwards asks for its dependencies to be finished.
#
# **Five lanes since `beta.2`, not six.** `blocked` left with `0046` (`HD-06`, ADR 0040's
# amendment): being blocked is `tasks.is_blocked` plus a reason, not a place a card goes.
# The value has to leave *here* as well as leave the CHECK, and for a reason worth stating
# — `_require_stage` reads `STAGES`, so a `PATCH` naming the old value must be refused
# with `TASK_STAGE_INVALID` and its list of legal lanes. Left in, the same request reaches
# PostgreSQL and comes back as a constraint violation: a 500 where the user made an
# ordinary mistake.
LANE_ORDER = ("backlog", "ready", "implementing", "verify", "done")
STAGES = frozenset(LANE_ORDER)

# Entering one of these means claiming the card is workable, which is the claim an
# unfinished dependency contradicts.
#
# It used to say "`blocked` is deliberately *not* in the set: a card is moved there
# precisely because something is in the way". That sentence is now carried by
# `tasks.is_blocked`, which is checked separately — the set below is about lanes, and
# there is no longer a lane that means "in the way".
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

    async def overrides_for(self, project: Project) -> dict[str, Any]:
        return dict(project.process_overrides or {})

    async def set_overrides(
        self, project: Project, overrides: dict[str, Any], *, actor_id: uuid.UUID
    ) -> dict[str, Any]:
        """Validate every key against the default definition, then store.

        A mistyped key is **silently ineffective** otherwise, and the person who typed
        it believes they turned something off — until it blocks a card weeks later. So
        an unknown key is a 422 that names it rather than a value that is ignored.
        """
        row = await self.definition()
        known_readiness = {str(item.get("key")) for item in row.readiness}
        known_gates = {str(item.get("key")) for item in row.gates}
        known_lanes = {str(lane.get("stage")) for lane in row.lanes}

        unknown: list[str] = sorted(
            [k for k in overrides.get("readiness_disabled", []) if k not in known_readiness]
            + [k for k in overrides.get("gates_disabled", []) if k not in known_gates]
            + [k for k in overrides.get("wip", {}) if k not in known_lanes]
        )
        if unknown:
            raise ApiError(
                "PROCESS_OVERRIDE_UNKNOWN_KEY",
                "這些項目不存在於流程定義中：" + "、".join(unknown),
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                details={"unknown": unknown},
            )

        stored = {
            "readiness_disabled": sorted(set(overrides.get("readiness_disabled", []))),
            "gates_disabled": sorted(set(overrides.get("gates_disabled", []))),
            "wip": {k: int(v) for k, v in overrides.get("wip", {}).items()},
        }
        project.process_overrides = stored
        await self._session.flush()
        await AuditService(self._session).record(
            audit_actions.PROCESS_OVERRIDE,
            user_id=actor_id,
            metadata={"project_id": str(project.id), "overrides": stored},
        )
        return stored

    async def effective(
        self, key: str = DEFAULT_KEY, *, project: Project | None = None
    ) -> EffectiveProcess:
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
        overrides = dict(project.process_overrides or {}) if project is not None else {}
        gates_off = set(overrides.get("gates_disabled", []))
        readiness_off = set(overrides.get("readiness_disabled", []))
        wip_override = dict(overrides.get("wip", {}))

        gates = []
        for raw in sorted(row.gates, key=lambda item: item.get("order", 0)):
            needs = raw.get("depends_on_integration")
            enabled = True
            reason: str | None = None
            if needs is not None and not integrations_enabled.get(needs, False):
                enabled = False
                reason = f"{needs}_integration_disabled"
            elif raw["key"] in gates_off:
                # **A distinct reason, not a shared "disabled".** "this deployment has
                # no tunnel integration" and "this project switched it off" send a
                # person to two different people, and a single word would send half of
                # them to the wrong one.
                enabled = False
                reason = "disabled_by_project"
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

        lanes = []
        for lane in sorted(row.lanes, key=lambda item: item.get("order", 0)):
            stage = str(lane.get("stage"))
            lanes.append(
                {**lane, "wip_suggested": wip_override.get(stage, lane.get("wip_suggested"))}
            )

        return EffectiveProcess(
            key=row.key,
            version=row.version,
            source=row.source,
            lanes=lanes,
            # Disabled readiness items are **removed from the effective list**, not
            # flagged: `readiness_keys()` feeds the Definition-of-Ready warnings, and an
            # item that still reports while being "off" is the same as not being off.
            readiness=[item for item in row.readiness if item.get("key") not in readiness_off],
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
