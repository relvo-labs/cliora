"""Intake, specification versions and task proposals — the manual flow (TK-05).

`version2.md` §17 asks for this order explicitly: **build the data structures and the
human flow first, then let an agent use the same API.** So V2.1 delivers the tables
and the forms, and V2.5 points an agent at exactly these endpoints. If nobody uses the
manual flow, nobody will use the agent one either — which makes the usage of these
five endpoints the cheapest early signal V2.5 could ask for (D28 §4, M14).

Three refusals live here, and all three are **API-level**, not disabled buttons:

1. a specification with an unresolved open question cannot be approved, and the
   refusal names the questions;
2. an unapproved requirement cannot be decomposed;
3. an accepted proposal whose card is missing readiness items lands in `backlog`
   rather than in `ready`, and says which items were missing.

The third is the Definition of Ready finally biting something. It bites here rather
than on the board because this is the one moment where a card is created *by a
decision* rather than by a person typing it — and a decision is exactly what can be
made with a rule attached (D28).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.clock import now_utc
from app.db.models import (
    FeatureSpec,
    Project,
    Requirement,
    Task,
    TaskDependency,
    TaskProposal,
)
from app.repositories.tasks import TaskRepository
from app.services import audit as audit_actions
from app.services.activity import (
    PROPOSAL_ACCEPTED,
    PROPOSAL_REJECTED,
    REQUIREMENT_APPROVED,
    REQUIREMENT_CREATED,
    REQUIREMENT_SPEC_ADDED,
    ActivityService,
)
from app.services.audit import AuditService
from app.services.process import ProcessService
from app.services.tasks import TaskService

INTAKE = "intake"
CLARIFYING = "clarifying"
SPECIFIED = "specified"
APPROVED = "approved"
REJECTED = "rejected"

# The nine sections Monstrare's specification template has and V2.1's five columns did
# not (`../Monstrare/ai/templates/feature-spec.md`, MIT; ADR 0034 §7).
#
# **Closed, and enforced.** Left open, the first agent writes `user_stories` and the
# second writes `userStories`, and the review screen has to read both forever. The
# *contents* are deliberately unvalidated: a specification with every section empty is
# legal, and what stops it is the approval gate — which is the reason a human gate
# exists at all.
SPEC_SECTION_KEYS: frozenset[str] = frozenset(
    {
        "problem",
        "users",
        "user_stories",
        "journeys",
        "functional_requirements",
        "screens",
        "data_and_api",
        "security_privacy",
        "verification_plan",
    }
)

# An agent in a loop submitting a version a second is a table that grows without bound.
# The limit is a backstop, not a design constraint: a real clarification converges in a
# handful of rounds (M-RQ-2 measures it).
MAX_SPEC_VERSIONS = 20
# Not a granularity rule — the server cannot judge whether a card is too big, and a
# guessed rule would reject correct cards. This only stops a runaway (plan/22/04 §3);
# the convergence point is the acceptance screen's count.
MAX_PROPOSAL_TASKS = 40

# Fields a person may change on a proposed card while accepting it (ADR 0034 §6).
#
# **`readiness` is deliberately absent.** Ticking it here would turn "a card missing
# readiness lands in `backlog`" into a rule that disappears whenever it is inconvenient.
# To complete a card's readiness, create it and edit the card — where the edit is a
# `PATCH` with an audit record behind it.
PROPOSAL_OVERRIDE_FIELDS: frozenset[str] = frozenset(
    {
        "title",
        "description",
        "objective",
        "scope",
        "non_goals",
        "stage",
        "risk",
        "priority",
        "delivery",
        "source",
        "target_branch",
        "base_branch",
        "required_labels",
    }
)

# Terms that make a card high risk (ADR 0034 §10). **A guard rail, not a control**: an
# agent that wanted to evade it would change a word. It exists for the honest-but-
# careless agent, and it errs toward noise on purpose — a card about deleting old
# authentication *documentation* gets badged, and the cost of that is one unticked
# badge, while the cost of missing a card that touches payments is that card entering
# `ready` as `low`.
HIGH_RISK_TERMS: tuple[str, ...] = (
    "密鑰",
    "金鑰",
    "機密",
    "secret",
    "credential",
    "token",
    "認證",
    "登入",
    "auth",
    "權限",
    "rbac",
    "金流",
    "付款",
    "payment",
    "billing",
    "遷移",
    "migration",
    "schema",
    "基礎設施",
    "infra",
    "deploy",
    "部署",
)


@dataclass(frozen=True, slots=True)
class AcceptResult:
    created: list[Task]
    # Per created card: which readiness items it lacked. Carried out to the caller so
    # the console can say why a card landed in `backlog`, rather than leaving the user
    # to compare two screens.
    incomplete: dict[str, list[str]]
    # Per created card: the proposal items it depended on that were **not** accepted, so
    # no dependency row was written. Reported rather than silently dropped — a card
    # asserting `dependencies_known` while the database holds none is the failure this
    # field exists to prevent (ADR 0034 §6).
    unresolved_dependencies: dict[str, list[str]] = field(default_factory=dict)


def _validated_sections(value: Any) -> dict[str, Any]:
    """The nine closed keys, checked; the contents, not.

    An unknown key is named in the refusal rather than dropped: a silently discarded
    section is a section its author believes was stored.
    """
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ApiError(
            "SPEC_SECTION_UNKNOWN",
            "sections 必須是一個物件",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    unknown = sorted(set(value) - SPEC_SECTION_KEYS)
    if unknown:
        raise ApiError(
            "SPEC_SECTION_UNKNOWN",
            "規格書沒有這幾節：" + "、".join(unknown),
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            details={"unknown": unknown, "allowed": sorted(SPEC_SECTION_KEYS)},
        )
    return dict(value)


def _reject_ambiguous_questions(questions: list[dict[str, Any]]) -> None:
    """A question may be answered, or recorded as a known unknown — never both.

    `_open_questions` accepts either as "resolved", so filling both makes the approval
    button light up. It also hides the distinction a reviewer needs: *this is the
    answer* and *we decided not to resolve this* are different states, and a row
    claiming both tells them neither.

    A person filling a form never does this. An agent trying to get its specification
    approved will.
    """
    ambiguous = [
        str(item.get("question", item.get("id", "?")))
        for item in questions
        if isinstance(item, dict) and item.get("answer") and item.get("resolved_as")
    ]
    if ambiguous:
        raise ApiError(
            "SPEC_QUESTION_AMBIGUOUS",
            "這幾個問題同時填了答案與「已知未知」，兩者只能擇一：" + "、".join(ambiguous),
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            details={"questions": ambiguous},
        )


def _tree_items(tree: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = (tree or {}).get(key) or []
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ApiError(
            "PROPOSAL_TREE_INVALID",
            f"`{key}` 必須是一個物件陣列",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    return value


def _validate_tree(tree: dict[str, Any]) -> None:
    """Six checks, all at submission time rather than at acceptance.

    Checking at acceptance would mean a cycle among items nobody selected is never
    found — and it surfaces on some later partial acceptance, long after the run that
    produced it is gone.
    """
    epics = _tree_items(tree, "epics")
    stories = _tree_items(tree, "user_stories")
    tasks = _tree_items(tree, "tasks")

    if not tasks:
        raise ApiError(
            "PROPOSAL_EMPTY",
            "提案裡沒有任何 Task",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    if len(tasks) > MAX_PROPOSAL_TASKS:
        raise ApiError(
            "PROPOSAL_TOO_LARGE",
            f"一次拆解最多 {MAX_PROPOSAL_TASKS} 張卡，這份提案有 {len(tasks)} 張。"
            "顆粒度可能太細，或這個需求該先拆成幾個 Epic 分批處理。",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            details={"tasks": len(tasks), "maximum": MAX_PROPOSAL_TASKS},
        )

    epic_ids = _unique_ids(epics, "epics")
    story_ids = _unique_ids(stories, "user_stories")
    task_ids = _unique_ids(tasks, "tasks")

    for story in stories:
        parent = story.get("epic_id")
        if parent is not None and str(parent) not in epic_ids:
            raise ApiError(
                "PROPOSAL_TREE_INVALID",
                f"User Story `{story.get('id')}` 的 epic_id `{parent}` 不存在",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
    for item in tasks:
        for field_name, pool in (("epic_id", epic_ids), ("user_story_id", story_ids)):
            value = item.get(field_name)
            if value is not None and str(value) not in pool:
                raise ApiError(
                    "PROPOSAL_TREE_INVALID",
                    f"Task `{item.get('id')}` 的 {field_name} `{value}` 不存在",
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                )
        if "required_secrets" in item:
            # A decomposition does not decide which credentials a card receives. The
            # field is refused rather than stripped, because stripping it would leave
            # the agent believing it had declared something.
            raise ApiError(
                "PROPOSAL_FIELD_FORBIDDEN",
                f"Task `{item.get('id')}` 宣告了 required_secrets；"
                "機密由人在卡片上補，拆解不得指定",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                details={"field": "required_secrets", "item_id": item.get("id")},
            )
        for dependency in item.get("depends_on") or []:
            if str(dependency) not in task_ids:
                raise ApiError(
                    "PROPOSAL_TREE_INVALID",
                    f"Task `{item.get('id')}` 依賴 `{dependency}`，而樹裡沒有這個節點",
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                )
        _require_risk_declared(item)

    _reject_dependency_cycles(tasks)


def _unique_ids(items: list[dict[str, Any]], label: str) -> set[str]:
    seen: set[str] = set()
    for item in items:
        value = str(item.get("id") or "")
        if not value:
            raise ApiError(
                "PROPOSAL_TREE_INVALID",
                f"`{label}` 裡有節點沒有 id",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        if value in seen:
            raise ApiError(
                "PROPOSAL_TREE_INVALID",
                f"`{label}` 裡的 id `{value}` 重複",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        seen.add(value)
    return seen


def _require_risk_declared(item: dict[str, Any]) -> None:
    """Stop condition 4, as the only thing the platform can hold an agent to.

    See `HIGH_RISK_TERMS`: coarse on purpose and in a chosen direction.
    """
    haystack = " ".join(str(item.get(key) or "") for key in ("title", "objective", "scope")).lower()
    hits = sorted({term for term in HIGH_RISK_TERMS if term in haystack})
    if hits and str(item.get("risk") or "").lower() != "high":
        raise ApiError(
            "PROPOSAL_RISK_UNDERSTATED",
            f"Task `{item.get('id')}` 提到 " + "、".join(hits) + "，但風險等級不是 high",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            details={"item_id": item.get("id"), "terms": hits, "risk": item.get("risk")},
        )


def _reject_dependency_cycles(tasks: list[dict[str, Any]]) -> None:
    """A depth-first walk that names the cycle it found.

    Naming it matters: "there is a cycle" in a forty-node tree is not actionable, and
    the existing `task_dependencies` check set this precedent for the same reason.
    """
    graph = {
        str(item.get("id")): [str(value) for value in (item.get("depends_on") or [])]
        for item in tasks
    }
    visiting: set[str] = set()
    done: set[str] = set()

    def walk(node: str, path: list[str]) -> None:
        if node in done:
            return
        if node in visiting:
            cycle = path[path.index(node) :] + [node]
            raise ApiError(
                "PROPOSAL_TREE_CYCLE",
                "提案的相依形成循環：" + " → ".join(cycle),
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                details={"cycle": cycle},
            )
        visiting.add(node)
        for nxt in graph.get(node, []):
            walk(nxt, [*path, node])
        visiting.discard(node)
        done.add(node)

    for node in graph:
        walk(node, [])


def _open_questions(spec: FeatureSpec) -> list[dict[str, Any]]:
    """Unresolved questions on a spec version.

    "Resolved" means an answer *or* an explicit `resolved_as` — the second is how a
    known unknown gets recorded without pretending it was answered (D28 §3).
    """
    return [
        question
        for question in (spec.open_questions or [])
        if not question.get("answer") and not question.get("resolved_as")
    ]


class RequirementService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._audit = AuditService(session)
        self._activity = ActivityService(session)
        self._tasks = TaskService(session)
        self._repo = TaskRepository(session)
        self._process = ProcessService(session)

    # --- reads ------------------------------------------------------------------

    async def require(self, requirement_id: uuid.UUID) -> Requirement:
        row = await self._session.get(Requirement, requirement_id)
        if row is None:
            raise ApiError(
                "REQUIREMENT_NOT_FOUND", "Requirement not found", status.HTTP_404_NOT_FOUND
            )
        return row

    async def listing(self, project_id: uuid.UUID) -> list[Requirement]:
        rows = (
            await self._session.execute(
                select(Requirement)
                .where(Requirement.project_id == project_id)
                .order_by(Requirement.created_at.desc())
            )
        ).scalars()
        return list(rows)

    async def specs(self, requirement_id: uuid.UUID) -> list[FeatureSpec]:
        rows = (
            await self._session.execute(
                select(FeatureSpec)
                .where(FeatureSpec.requirement_id == requirement_id)
                .order_by(FeatureSpec.seq)
            )
        ).scalars()
        return list(rows)

    async def latest_spec(self, requirement_id: uuid.UUID) -> FeatureSpec | None:
        return (
            await self._session.execute(
                select(FeatureSpec)
                .where(FeatureSpec.requirement_id == requirement_id)
                .order_by(FeatureSpec.seq.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    async def proposals(self, requirement_id: uuid.UUID) -> list[TaskProposal]:
        rows = (
            await self._session.execute(
                select(TaskProposal)
                .where(TaskProposal.requirement_id == requirement_id)
                .order_by(TaskProposal.seq)
            )
        ).scalars()
        return list(rows)

    async def require_proposal(self, proposal_id: uuid.UUID) -> TaskProposal:
        row = await self._session.get(TaskProposal, proposal_id)
        if row is None:
            raise ApiError("PROPOSAL_NOT_FOUND", "Proposal not found", status.HTTP_404_NOT_FOUND)
        return row

    # --- writes -----------------------------------------------------------------

    async def create(self, *, project: Project, actor_id: uuid.UUID, raw_text: str) -> Requirement:
        """Intake: one sentence, nothing else required.

        Deliberately not a form. The flow starts with someone saying what they want in
        their own words, and ten mandatory fields at that moment is how the flow stops
        being used at all.
        """
        if project.status == "archived":
            raise ApiError("PROJECT_ARCHIVED", "This project is archived", status.HTTP_409_CONFLICT)
        card_ref = await self._repo.allocate_card_ref(project.id, "REQ")
        requirement = Requirement(
            id=uuid.uuid4(),
            project_id=project.id,
            card_ref=card_ref,
            raw_text=raw_text,
            status=INTAKE,
            created_by=actor_id,
        )
        self._session.add(requirement)
        await self._session.flush()
        await self._audit.record(
            audit_actions.REQUIREMENT_CREATE,
            user_id=actor_id,
            metadata={"card_ref": card_ref, "project_id": str(project.id)},
        )
        await self._activity.record(
            REQUIREMENT_CREATED,
            project_id=project.id,
            actor_user_id=actor_id,
            payload={"card_ref": card_ref},
        )
        return requirement

    async def add_spec(
        self,
        *,
        requirement: Requirement,
        actor_id: uuid.UUID | None,
        fields: dict[str, Any],
        authored_by_kind: str = "user",
        run_id: uuid.UUID | None = None,
    ) -> FeatureSpec:
        """Append a specification version. Never an update.

        The review screen compares version N with N-1, and a specification that was
        quietly edited is the thing most worth being able to see later.

        `actor_id` is optional from V2.5: a run has no user, and `AgentPrincipal`
        deliberately carries none — a principal with a `user_id` starts impersonating
        the person who dispatched it. `authored_by_kind` is what distinguishes the two,
        which is why it exists as a column rather than being inferred from a NULL.
        """
        if requirement.status == APPROVED:
            raise ApiError(
                "REQUIREMENT_ALREADY_APPROVED",
                "This requirement is approved; a new version needs a new requirement",
                status.HTTP_409_CONFLICT,
            )
        sections = _validated_sections(fields.get("sections"))
        questions = list(fields.get("open_questions") or [])
        _reject_ambiguous_questions(questions)
        used = int(
            await self._session.scalar(
                select(func.count())
                .select_from(FeatureSpec)
                .where(FeatureSpec.requirement_id == requirement.id)
            )
            or 0
        )
        if used >= MAX_SPEC_VERSIONS:
            raise ApiError(
                "SPEC_VERSION_LIMIT",
                f"這個需求已經有 {used} 版規格，超過上限 {MAX_SPEC_VERSIONS}",
                status.HTTP_409_CONFLICT,
                details={"versions": used, "maximum": MAX_SPEC_VERSIONS},
            )
        next_seq = int(
            await self._session.scalar(
                select(func.coalesce(func.max(FeatureSpec.seq), 0) + 1).where(
                    FeatureSpec.requirement_id == requirement.id
                )
            )
            or 1
        )
        spec = FeatureSpec(
            id=uuid.uuid4(),
            requirement_id=requirement.id,
            seq=next_seq,
            objective=fields.get("objective"),
            scope=fields.get("scope"),
            non_goals=fields.get("non_goals"),
            acceptance_criteria=fields.get("acceptance_criteria") or [],
            open_questions=questions,
            sections=sections,
            authored_by_kind=authored_by_kind,
            authored_by=actor_id,
            run_id=run_id,
        )
        self._session.add(spec)
        requirement.status = SPECIFIED if not _open_questions(spec) else CLARIFYING
        await self._session.flush()
        await self._activity.record(
            REQUIREMENT_SPEC_ADDED,
            project_id=requirement.project_id,
            actor_user_id=actor_id,
            payload={"card_ref": requirement.card_ref, "seq": next_seq},
        )
        return spec

    async def approve(self, *, requirement: Requirement, actor_id: uuid.UUID) -> Requirement:
        """The first of D28's three human gates.

        Refused at the API, not by a disabled button: V2.5 sends an agent down this
        same path, and a UI-only rule would not be there when it did.
        """
        spec = await self.latest_spec(requirement.id)
        if spec is None:
            raise ApiError(
                "REQUIREMENT_NOT_SPECIFIED",
                "Write a specification before approving",
                status.HTTP_409_CONFLICT,
            )
        unresolved = _open_questions(spec)
        if unresolved:
            raise ApiError(
                "SPEC_HAS_OPEN_QUESTIONS",
                "Unresolved questions remain",
                status.HTTP_409_CONFLICT,
                details={
                    "questions": [
                        question.get("question", question.get("id", "?")) for question in unresolved
                    ]
                },
            )
        requirement.status = APPROVED
        requirement.approved_by = actor_id
        requirement.approved_at = now_utc()
        await self._session.flush()
        await self._audit.record(
            audit_actions.REQUIREMENT_APPROVE,
            user_id=actor_id,
            metadata={"card_ref": requirement.card_ref, "spec_seq": spec.seq},
        )
        await self._activity.record(
            REQUIREMENT_APPROVED,
            project_id=requirement.project_id,
            actor_user_id=actor_id,
            payload={"card_ref": requirement.card_ref, "spec_seq": spec.seq},
        )
        return requirement

    async def propose(
        self,
        *,
        requirement: Requirement,
        actor_id: uuid.UUID | None,
        tree: dict[str, Any],
        run_id: uuid.UUID | None = None,
    ) -> TaskProposal:
        """Record a decomposition. Proposals are not cards.

        The refusal below is D28's second gate: an unapproved specification cannot be
        decomposed, because a decomposition of something nobody has agreed to is work
        that will be thrown away.

        **Nothing on this path creates a card.** `GATE-RQ-NO-CARD-FROM-RUN` asserts it
        against the code rather than against behaviour, because an implementation that
        also created cards would pass every test — the proposal would exist, the cards
        would exist, and they would agree. What breaks is "a person looked at it", and
        that has no runtime shape to assert.
        """
        if requirement.status != APPROVED:
            raise ApiError(
                "REQUIREMENT_NOT_APPROVED",
                "Approve the specification before decomposing it",
                status.HTTP_409_CONFLICT,
            )
        _validate_tree(tree)
        spec = await self.latest_spec(requirement.id)
        next_seq = int(
            await self._session.scalar(
                select(func.coalesce(func.max(TaskProposal.seq), 0) + 1).where(
                    TaskProposal.requirement_id == requirement.id
                )
            )
            or 1
        )
        proposal = TaskProposal(
            id=uuid.uuid4(),
            requirement_id=requirement.id,
            spec_id=spec.id if spec else None,
            seq=next_seq,
            tree=tree,
            status="pending",
            run_id=run_id,
        )
        self._session.add(proposal)
        await self._session.flush()
        return proposal

    async def reject(
        self, *, proposal: TaskProposal, actor_id: uuid.UUID, note: str
    ) -> TaskProposal:
        """Turn a proposal down, with a reason that is kept.

        The reason is required, and that is the whole change from V2.1's `DELETE`. A
        rejection with no reason produces a row indistinguishable from no row three
        months later — and this is the only signal that *accumulates* on this path: the
        next decomposition of the same requirement gets it as a negative example
        (`runs.py::_rejected_notes`).
        """
        if proposal.status in ("accepted", "rejected"):
            raise ApiError(
                "PROPOSAL_ALREADY_DECIDED",
                "This proposal was already decided",
                status.HTTP_409_CONFLICT,
            )
        if not note.strip():
            raise ApiError(
                "PROPOSAL_REJECT_NEEDS_NOTE",
                "拒絕提案要寫理由——下次拆解時它會進 Agent 的情境包",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        requirement = await self.require(proposal.requirement_id)
        proposal.status = REJECTED
        proposal.decided_by = actor_id
        proposal.decided_at = now_utc()
        proposal.decision_note = note.strip()
        await self._session.flush()
        await self._audit.record(
            audit_actions.PROPOSAL_REJECT,
            user_id=actor_id,
            metadata={"card_ref": requirement.card_ref, "proposal_seq": proposal.seq},
        )
        await self._activity.record(
            PROPOSAL_REJECTED,
            project_id=requirement.project_id,
            actor_user_id=actor_id,
            payload={"card_ref": requirement.card_ref, "proposal_seq": proposal.seq},
        )
        return proposal

    async def produced_item_ids(self, proposal_id: uuid.UUID) -> set[str]:
        """Which proposal items have already become cards.

        Partial acceptance leaves the rest *available* rather than declined, so a second
        acceptance is legitimate and has to be idempotent per item. `ix_tasks_proposal_item`
        is the index for this lookup — without it, a forty-card decomposition makes the
        accept button visibly slow, and nobody connects that to JSONB.
        """
        rows = (
            await self._session.execute(select(Task.links).where(Task.proposal_id == proposal_id))
        ).scalars()
        return {str((links or {}).get("proposal_item_id")) for links in rows}

    async def accept(
        self,
        *,
        project: Project,
        requirement: Requirement,
        proposal: TaskProposal,
        actor_id: uuid.UUID,
        accept_ids: list[str] | None,
        note: str | None,
        overrides: dict[str, dict[str, Any]] | None = None,
    ) -> AcceptResult:
        """Turn accepted proposal cards into real ones.

        Partial acceptance is the normal case, so `accept_ids` selects; `None` means
        all of them. Whatever is not accepted stays on the proposal and remains
        **available**, not declined — a second acceptance of the rest is a normal thing
        to do a week later.

        **A card missing readiness items lands in `backlog`, never in `ready`.** That
        is the Definition of Ready's one hard consequence in V2.1 — and it applies
        here rather than on the board because this is where a card is created by a
        decision instead of by someone typing it (D28).

        Three things happen in a fixed order and the order is load-bearing: create every
        selected card, then translate `depends_on` (which needs all of their ids), then
        decide the proposal's status. Translating inside the creation loop would only
        ever resolve backward references.
        """
        if proposal.status in ("accepted", "rejected"):
            raise ApiError(
                "PROPOSAL_ALREADY_DECIDED",
                "This proposal was already decided",
                status.HTTP_409_CONFLICT,
            )
        process = await self._process.effective(project=project)
        required_readiness = process.readiness_keys()
        items = list((proposal.tree or {}).get("tasks", []))
        selected = None if accept_ids is None else set(accept_ids)
        edits = _validated_overrides(overrides, items, selected)
        already = await self.produced_item_ids(proposal.id)
        chosen = [
            item
            for item in items
            if (selected is None or str(item.get("id", "")) in selected)
            and str(item.get("id", "")) not in already
        ]
        chosen_ids = {str(item.get("id", "")) for item in chosen}

        created: list[Task] = []
        incomplete: dict[str, list[str]] = {}
        unresolved: dict[str, list[str]] = {}
        by_item: dict[str, Task] = {}
        for item in chosen:
            item_id = str(item.get("id", ""))
            override = edits.get(item_id, {})
            readiness = item.get("readiness") or {}
            missing = [key for key in required_readiness if not readiness.get(key)]
            # A dependency on something nobody selected cannot be written, and the card
            # must not go on claiming its dependencies are known. Reported *and* counted
            # as a missing readiness item, which is what sends it to `backlog` — the
            # existing mechanism, given one more reason to fire (ADR 0034 §6).
            dangling = sorted(
                str(value)
                for value in (item.get("depends_on") or [])
                if str(value) not in chosen_ids and str(value) not in already
            )
            if dangling and "dependencies_known" in required_readiness:
                missing = sorted({*missing, "dependencies_known"})
            fields: dict[str, Any] = {
                "title": item.get("title", "untitled"),
                "description": item.get("description"),
                "objective": item.get("objective"),
                "scope": item.get("scope"),
                "non_goals": item.get("non_goals"),
                "stage": item.get("stage", "ready"),
                "risk": item.get("risk", "medium"),
                "priority": item.get("priority", "normal"),
                "acceptance_criteria": item.get("acceptance_criteria") or [],
                "readiness": readiness,
                "links": {
                    **(item.get("links") or {}),
                    "proposal_item_id": item_id,
                },
                "required_labels": item.get("required_labels") or [],
                "source": item.get("source", "repo"),
                "delivery": item.get("delivery", "pull_request"),
                "base_branch": item.get("base_branch"),
                "target_branch": item.get("target_branch"),
                "epic_id": None,
                "user_story_id": None,
            }
            # A person's edit wins over the agent's proposal, and is applied before the
            # readiness rule below so that moving a card to `backlog` on purpose still
            # works.
            fields.update(override)
            # The rule, in one expression, and *after* the override for a reason: the
            # override may not touch `readiness`, so it can never talk a card out of
            # this.
            if missing:
                fields["stage"] = "backlog"
            result = await self._tasks.create_task(
                project=project,
                actor_id=actor_id,
                fields=fields,
            )
            task = result.task
            # Provenance: the detail page says "from requirement #N, proposal #M".
            task.requirement_id = requirement.id
            task.proposal_id = proposal.id
            created.append(task)
            by_item[item_id] = task
            if missing:
                incomplete[task.card_ref] = missing
            if dangling:
                unresolved[task.card_ref] = dangling

        await self._link_dependencies(chosen, by_item, actor_id)

        produced = already | chosen_ids
        proposal.status = (
            "accepted"
            if produced >= {str(item.get("id", "")) for item in items}
            else "partially_accepted"
        )
        proposal.decided_by = actor_id
        proposal.decided_at = now_utc()
        proposal.decision_note = note
        await self._session.flush()
        await self._audit.record(
            audit_actions.PROPOSAL_ACCEPT,
            user_id=actor_id,
            metadata={
                "card_ref": requirement.card_ref,
                "proposal_seq": proposal.seq,
                "created": [task.card_ref for task in created],
                # Per field, because "this card is not what the agent proposed" is a
                # question somebody asks three months later.
                "overrides": {key: sorted(value) for key, value in edits.items() if value},
            },
        )
        await self._activity.record(
            PROPOSAL_ACCEPTED,
            project_id=project.id,
            actor_user_id=actor_id,
            payload={
                "card_ref": requirement.card_ref,
                "created": [task.card_ref for task in created],
            },
        )
        return AcceptResult(
            created=created, incomplete=incomplete, unresolved_dependencies=unresolved
        )

    async def _link_dependencies(
        self,
        chosen: list[dict[str, Any]],
        by_item: dict[str, Task],
        actor_id: uuid.UUID,
    ) -> None:
        """Translate the tree's own ids into `task_dependencies` rows.

        Only edges where **both** ends were created in this acceptance. The other case is
        already reported to the caller and has cost that card its readiness; writing a
        row pointing at a card that does not exist is the alternative, and there is no
        third option that keeps the promise `dependencies_known` makes.
        """
        for item in chosen:
            task = by_item.get(str(item.get("id", "")))
            if task is None:
                continue
            for value in item.get("depends_on") or []:
                target = by_item.get(str(value))
                if target is None or target.id == task.id:
                    continue
                self._session.add(
                    TaskDependency(
                        task_id=task.id,
                        depends_on_task_id=target.id,
                        created_by=actor_id,
                    )
                )
        await self._session.flush()


def _validated_overrides(
    overrides: dict[str, dict[str, Any]] | None,
    items: list[dict[str, Any]],
    selected: set[str] | None,
) -> dict[str, dict[str, Any]]:
    """A person's edits to a proposed card, checked before anything is created.

    Two refusals, and the second is the one that matters:

    * an override for an item that is **not being accepted** is refused rather than
      ignored, because otherwise it would be silently applied at some later partial
      acceptance — a decision nobody remembers making;
    * `readiness` is not in `PROPOSAL_OVERRIDE_FIELDS`, so an attempt to tick it is a
      named refusal. Allowing it would make "a card missing readiness lands in
      `backlog`" a rule that vanishes when inconvenient.
    """
    if not overrides:
        return {}
    known = {str(item.get("id", "")) for item in items}
    for item_id, changes in overrides.items():
        if item_id not in known:
            raise ApiError(
                "PROPOSAL_TREE_INVALID",
                f"提案裡沒有 `{item_id}` 這個節點",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        if selected is not None and item_id not in selected:
            raise ApiError(
                "PROPOSAL_OVERRIDE_NOT_ACCEPTED",
                f"`{item_id}` 不在這次接受的清單裡，不能修改它的欄位",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                details={"item_id": item_id},
            )
        if not isinstance(changes, dict):
            raise ApiError(
                "PROPOSAL_TREE_INVALID",
                f"`{item_id}` 的覆寫必須是一個物件",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        unknown = sorted(set(changes) - PROPOSAL_OVERRIDE_FIELDS)
        if unknown:
            raise ApiError(
                "PROPOSAL_OVERRIDE_NOT_ACCEPTED",
                "接受時不能修改這幾個欄位："
                + "、".join(unknown)
                + (
                    "。就緒條件由拆解填寫；要補齊請先建立卡片再修改，那一步會留下紀錄。"
                    if "readiness" in unknown
                    else ""
                ),
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                details={"unknown": unknown, "allowed": sorted(PROPOSAL_OVERRIDE_FIELDS)},
            )
    return {key: dict(value) for key, value in overrides.items()}
