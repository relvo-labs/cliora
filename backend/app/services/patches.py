"""Document patch proposals: the platform renders and records, and never applies (RQ-08).

`version2.md` §7.6 asks for four steps — a user files a need, an agent works out which
documents it affects, the agent writes a patch, and a person decides. This module is the
third and fourth. **The fifth step, applying it, is not here and is not anywhere**:
accepting a proposal creates nothing, and the console offers a button that pre-fills an
ordinary `delivery: pull_request` card instead.

Three reasons, and the third is the one that decides (ADR 0034 §6):

1. applying a markdown patch is general file editing, which `plan/14` designed and had
   withdrawn;
2. Central holds no clone — "apply" has no place to happen on this side at all;
3. **routing the edit through a normal card is better, not merely safer.** The document
   change then gets a branch, a diff and a reviewer, exactly like a code change. A
   platform that applied it would produce a commit nobody reviewed.

`GATE-RQ-NO-PATCH-APPLY` asserts the absence against the code: this module imports no
filesystem module and calls no `open(`. The check exists because "we already have the
diff, let's add an apply button" is a natural next thought that would pass every test.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.clock import now_utc
from app.db.models import DocumentPatchProposal, Task
from app.services import audit as audit_actions
from app.services.activity import PATCH_PROPOSAL_DECIDED, ActivityService
from app.services.audit import AuditService

PENDING = "pending"
ACCEPTED = "accepted"
REJECTED = "rejected"

# The four groups `version2.md` §7.6 names. Closed for the same reason
# `SPEC_SECTION_KEYS` is: two agents inventing two spellings of one idea is a cost the
# review screen pays forever.
PATCH_SECTION_KEYS: frozenset[str] = frozenset(
    {"added_sections", "modified_sections", "removed_sections", "related_docs"}
)

# Refused at submission, never truncated at render. A truncated diff looks complete and
# a person decides on it; the failure is invisible at exactly the moment it matters.
MAX_DIFF_BYTES = 256 * 1024


def _validated_target(path: str) -> str:
    """A repository-relative path, checked for readability rather than for safety.

    **The platform never opens this file** — there is nothing here for a traversal to
    reach. The check exists because `../../etc/passwd` would be rendered on a person's
    review screen, and by then it is a thing that looks like an attack and has to be
    explained.
    """
    cleaned = path.strip()
    if not cleaned or cleaned.startswith("/") or ".." in cleaned.split("/"):
        raise ApiError(
            "PATCH_PROPOSAL_TARGET_INVALID",
            "target_path 必須是 repo 內的相對路徑，不得以 / 開頭、不得含 ..",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            details={"target_path": path},
        )
    return cleaned


def _validated_sections(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ApiError(
            "PATCH_PROPOSAL_TARGET_INVALID",
            "sections 必須是一個物件",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    unknown = sorted(set(value) - PATCH_SECTION_KEYS)
    if unknown:
        raise ApiError(
            "PATCH_PROPOSAL_TARGET_INVALID",
            "修訂提案沒有這幾節：" + "、".join(unknown),
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            details={"unknown": unknown, "allowed": sorted(PATCH_SECTION_KEYS)},
        )
    return dict(value)


class PatchProposalService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._audit = AuditService(session)
        self._activity = ActivityService(session)

    async def require(self, proposal_id: uuid.UUID) -> DocumentPatchProposal:
        row = await self._session.get(DocumentPatchProposal, proposal_id)
        if row is None:
            raise ApiError(
                "PATCH_PROPOSAL_NOT_FOUND", "Patch proposal not found", status.HTTP_404_NOT_FOUND
            )
        return row

    async def listing(
        self, project_id: uuid.UUID, *, pending_only: bool = True
    ) -> list[DocumentPatchProposal]:
        query = select(DocumentPatchProposal).where(DocumentPatchProposal.project_id == project_id)
        if pending_only:
            query = query.where(DocumentPatchProposal.status == PENDING)
        query = query.order_by(DocumentPatchProposal.created_at.desc())
        return list((await self._session.execute(query)).scalars())

    async def submit(
        self,
        *,
        task: Task,
        run_id: uuid.UUID | None,
        payload: dict[str, Any],
    ) -> DocumentPatchProposal:
        """Record a proposal from a run.

        **`card_kind` is deliberately unconstrained here**, unlike the specification and
        decomposition routes. `research/02/07` filed patch proposals under clarification,
        but in practice an implementation card is where a document is discovered to be
        wrong — a card fixing report export finds the PRD describing a format the code
        does not produce. Refusing that would leave the agent able only to mention it in
        a comment.
        """
        diff = str(payload.get("diff") or "")
        if len(diff.encode()) > MAX_DIFF_BYTES:
            raise ApiError(
                "PATCH_PROPOSAL_TOO_LARGE",
                f"修訂內容超過 {MAX_DIFF_BYTES // 1024} KiB",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                details={"bytes": len(diff.encode()), "maximum": MAX_DIFF_BYTES},
            )
        if not diff.strip():
            raise ApiError(
                "PATCH_PROPOSAL_TARGET_INVALID",
                "修訂內容是空的",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        next_seq = int(
            await self._session.scalar(
                select(func.coalesce(func.max(DocumentPatchProposal.seq), 0) + 1).where(
                    DocumentPatchProposal.project_id == task.project_id
                )
            )
            or 1
        )
        proposal = DocumentPatchProposal(
            id=uuid.uuid4(),
            project_id=task.project_id,
            requirement_id=task.requirement_id,
            run_id=run_id,
            seq=next_seq,
            target_path=_validated_target(str(payload.get("target_path") or "")),
            diff=diff,
            sections=_validated_sections(payload.get("sections")),
            reason=payload.get("reason"),
            related_task_ids=[str(task.id)],
            open_questions=list(payload.get("open_questions") or []),
            status=PENDING,
        )
        self._session.add(proposal)
        await self._session.flush()
        return proposal

    async def decide(
        self,
        *,
        proposal: DocumentPatchProposal,
        actor_id: uuid.UUID,
        accept: bool,
        note: str | None,
    ) -> DocumentPatchProposal:
        """Record the decision. **Nothing else happens.**

        A rejection requires a reason, the same rule proposals follow. An acceptance does
        not, because accepting produces a visible artefact — the pre-filled card button —
        while a rejection produces only a row, and a row with no reason is a row that
        will be re-proposed in three months.

        Unresolved `open_questions` do **not** block acceptance here, unlike a
        specification's. The asymmetry is deliberate and has a reason: approving a
        specification unlocks decomposition, while accepting a patch proposal unlocks
        nothing at all.
        """
        if proposal.status != PENDING:
            raise ApiError(
                "PATCH_PROPOSAL_ALREADY_DECIDED",
                "This patch proposal was already decided",
                status.HTTP_409_CONFLICT,
            )
        cleaned = (note or "").strip()
        if not accept and not cleaned:
            raise ApiError(
                "PATCH_PROPOSAL_REJECT_NEEDS_NOTE",
                "拒絕修訂提案要寫理由",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        proposal.status = ACCEPTED if accept else REJECTED
        proposal.decided_by = actor_id
        proposal.decided_at = now_utc()
        proposal.decision_note = cleaned or None
        await self._session.flush()
        await self._audit.record(
            audit_actions.PATCH_PROPOSAL_DECIDE,
            user_id=actor_id,
            metadata={
                "patch_proposal_id": str(proposal.id),
                "seq": proposal.seq,
                "target_path": proposal.target_path,
                "status": proposal.status,
            },
        )
        await self._activity.record(
            PATCH_PROPOSAL_DECIDED,
            project_id=proposal.project_id,
            actor_user_id=actor_id,
            payload={
                "seq": proposal.seq,
                "target_path": proposal.target_path,
                "status": proposal.status,
            },
        )
        return proposal
