"""View CRUD: two scopes, one table, and no new permission (PX-26, ADR 0042 §2).

The load-bearing property is a negative one: **a view grants nothing.** A shared view
whose filter matches cards the caller may not read returns those cards *missing* — not an
error and not the cards — and `visible_fields` shapes the response while taking no part in
authorization. Both have tests, because a field list is the most natural place for
somebody to eventually put a permission.

Deletion is asymmetric and deliberately so (D112): a `project` view is soft-deleted
because colleagues hold links to it, and a `personal` view is deleted outright because
nobody else does and a graveyard of one person's abandoned views only grows.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.clock import now_utc
from app.db.models import User, WorkView
from app.services import audit as audit_actions
from app.services.audit import AuditService

PERSONAL = "personal"
PROJECT = "project"
LAYOUTS = frozenset({"board", "list", "roadmap"})
DENSITIES = frozenset({"compact", "comfortable"})


class WorkViewService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._audit = AuditService(session)

    async def require(self, view_id: uuid.UUID) -> WorkView:
        view = await self._session.get(WorkView, view_id)
        if view is None or view.deleted_at is not None:
            # The existing generic `NOT_FOUND`, not a new code. The phase's machine-code
            # budget is seven named ones, and "this view is not there" needs no name of
            # its own — nothing acts differently on it.
            raise ApiError("NOT_FOUND", "View not found", status.HTTP_404_NOT_FOUND)
        return view

    async def visible_for(self, *, project_id: uuid.UUID, actor: User) -> list[WorkView]:
        """The project's shared views plus **this caller's own** personal ones.

        Somebody else's personal view is absent from the list rather than refused — which
        is why modifying one is a 403 (`VIEW_NOT_OWNED`) and not a 404: the list already
        does not mention it, so a 403 on a direct request leaks nothing, and it lets the
        client tell "this is somebody else's" apart from "this does not exist".
        """
        rows = (
            await self._session.execute(
                select(WorkView)
                .where(
                    WorkView.deleted_at.is_(None),
                    WorkView.project_id == project_id,
                    (WorkView.scope == PROJECT) | (WorkView.owner_user_id == actor.id),
                )
                .order_by(WorkView.position, WorkView.name)
            )
        ).scalars()
        return list(rows)

    async def create(
        self,
        *,
        project_id: uuid.UUID,
        actor: User,
        scope: str,
        fields: dict[str, Any],
        may_manage: bool,
    ) -> WorkView:
        self._require_scope_permission(scope, may_manage)
        await self._require_name_free(
            project_id=project_id,
            owner_user_id=actor.id if scope == PERSONAL else None,
            name=str(fields["name"]),
            scope=scope,
        )
        position = (
            await self._session.execute(
                select(func.coalesce(func.max(WorkView.position), -1) + 1).where(
                    WorkView.project_id == project_id
                )
            )
        ).scalar_one()
        view = WorkView(
            id=uuid.uuid4(),
            project_id=project_id,
            owner_user_id=actor.id if scope == PERSONAL else None,
            scope=scope,
            position=position,
            created_by=actor.id,
            updated_by=actor.id,
            **self._validated(fields),
        )
        self._session.add(view)
        await self._session.flush()
        if scope == PROJECT:
            # A shared view is a change to what a team sees. A personal one is a
            # preference, and auditing preferences turns the audit log into telemetry.
            await self._audit.record(
                audit_actions.PROJECT_UPDATE,
                user_id=actor.id,
                metadata={
                    "project_id": str(project_id),
                    "work_view_id": str(view.id),
                    "action": "create_shared_view",
                    "name": view.name,
                },
            )
        return view

    async def update(
        self, *, view: WorkView, actor: User, fields: dict[str, Any], may_manage: bool
    ) -> WorkView:
        self._require_write_permission(view, actor, may_manage)
        if "name" in fields and fields["name"] != view.name:
            await self._require_name_free(
                project_id=view.project_id,
                owner_user_id=view.owner_user_id,
                name=str(fields["name"]),
                scope=view.scope,
            )
        for key, value in self._validated(fields).items():
            setattr(view, key, value)
        view.updated_by = actor.id
        view.version += 1
        await self._session.flush()
        return view

    async def set_default(self, *, view: WorkView, actor: User, may_manage: bool) -> WorkView:
        """Two updates in one transaction: clear the old default, set the new one.

        `uq_work_views_default` is what makes it two rather than one — and the pair is
        exactly what the audit entry records, because "which view does this project open
        on" is a decision about everybody's first screen.
        """
        if view.scope != PROJECT or view.project_id is None:
            raise ApiError(
                "VIEW_NOT_OWNED",
                "Only a shared project view can be the project default",
                status.HTTP_403_FORBIDDEN,
                details={"view_id": str(view.id), "scope": view.scope},
            )
        self._require_write_permission(view, actor, may_manage)
        previous = (
            await self._session.execute(
                select(WorkView.id).where(
                    WorkView.project_id == view.project_id,
                    WorkView.scope == PROJECT,
                    WorkView.is_default.is_(True),
                    WorkView.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if previous == view.id:
            return view
        await self._session.execute(
            update(WorkView)
            .where(
                WorkView.project_id == view.project_id,
                WorkView.scope == PROJECT,
                WorkView.is_default.is_(True),
            )
            .values(is_default=False)
        )
        view.is_default = True
        view.updated_by = actor.id
        view.version += 1
        await self._session.flush()
        await self._audit.record(
            audit_actions.PROJECT_UPDATE,
            user_id=actor.id,
            metadata={
                "project_id": str(view.project_id),
                "action": "set_default_view",
                "old_view_id": str(previous) if previous else None,
                "new_view_id": str(view.id),
            },
        )
        return view

    async def delete(self, *, view: WorkView, actor: User, may_manage: bool) -> None:
        self._require_write_permission(view, actor, may_manage)
        if view.scope == PROJECT:
            view.deleted_at = now_utc()
            view.updated_by = actor.id
            await self._session.flush()
            await self._audit.record(
                audit_actions.PROJECT_UPDATE,
                user_id=actor.id,
                metadata={
                    "project_id": str(view.project_id),
                    "work_view_id": str(view.id),
                    "action": "delete_shared_view",
                },
            )
            return
        await self._session.delete(view)
        await self._session.flush()

    async def duplicate(self, *, view: WorkView, actor: User, name: str) -> WorkView:
        """Copy any readable view into a **personal** one.

        Always personal, whatever the source was: copying a shared view is how somebody
        experiments without changing what the team sees, and a duplicate that landed as
        another shared view would make "try this" a broadcast.
        """
        await self._require_name_free(
            project_id=view.project_id,
            owner_user_id=actor.id,
            name=name,
            scope=PERSONAL,
        )
        copy = WorkView(
            id=uuid.uuid4(),
            project_id=view.project_id,
            owner_user_id=actor.id,
            scope=PERSONAL,
            name=name,
            layout=view.layout,
            filter_json=dict(view.filter_json or {}),
            group_by=view.group_by,
            subgroup_by=view.subgroup_by,
            order_by_json=list(view.order_by_json or []),
            visible_fields_json=list(view.visible_fields_json or []),
            density=view.density,
            show_subtasks=view.show_subtasks,
            is_default=False,
            position=view.position,
            created_by=actor.id,
            updated_by=actor.id,
        )
        self._session.add(copy)
        await self._session.flush()
        return copy

    # --- rules ------------------------------------------------------------------

    @staticmethod
    def _require_scope_permission(scope: str, may_manage: bool) -> None:
        if scope not in (PERSONAL, PROJECT):
            raise ApiError(
                "INVALID_ARGUMENT",
                "scope must be personal or project",
                status.HTTP_400_BAD_REQUEST,
                details={"scope": scope},
            )
        if scope == PROJECT and not may_manage:
            raise ApiError(
                "FORBIDDEN",
                "You do not have permission for this action",
                status.HTTP_403_FORBIDDEN,
            )

    @staticmethod
    def _require_write_permission(view: WorkView, actor: User, may_manage: bool) -> None:
        if view.scope == PROJECT:
            if not may_manage:
                raise ApiError(
                    "FORBIDDEN",
                    "You do not have permission for this action",
                    status.HTTP_403_FORBIDDEN,
                )
            return
        if view.owner_user_id != actor.id:
            # 403, not 404. The view is already absent from this caller's listing, so
            # saying "this is not yours" discloses nothing they could not infer — and it
            # lets a client distinguish it from a deleted view.
            raise ApiError(
                "VIEW_NOT_OWNED",
                "This personal view belongs to somebody else",
                status.HTTP_403_FORBIDDEN,
                details={"view_id": str(view.id)},
            )

    async def _require_name_free(
        self,
        *,
        project_id: uuid.UUID | None,
        owner_user_id: uuid.UUID | None,
        name: str,
        scope: str,
    ) -> None:
        existing = (
            await self._session.execute(
                select(WorkView.id).where(
                    WorkView.project_id == project_id,
                    WorkView.owner_user_id == owner_user_id,
                    WorkView.name == name,
                    WorkView.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            # Checked here as well as by `uq_work_views_name`, so the caller gets a named
            # code instead of a constraint violation. The index is still what makes it
            # true under concurrency.
            raise ApiError(
                "VIEW_NAME_CONFLICT",
                f"a view named {name!r} already exists here",
                status.HTTP_409_CONFLICT,
                details={"name": name, "scope": scope},
            )

    @staticmethod
    def _validated(fields: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "name",
            "layout",
            "filter_json",
            "group_by",
            "subgroup_by",
            "order_by_json",
            "visible_fields_json",
            "density",
            "show_subtasks",
        }
        unknown = sorted(set(fields) - allowed)
        if unknown:
            raise ApiError(
                "FORBIDDEN_FIELD",
                f"Unknown fields: {', '.join(unknown)}",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        cleaned = {
            key: value
            for key, value in fields.items()
            if value is not None or key in {"group_by", "subgroup_by"}
        }
        if "layout" in cleaned and cleaned["layout"] not in LAYOUTS:
            raise ApiError(
                "INVALID_ARGUMENT",
                f"layout must be one of {sorted(LAYOUTS)}",
                status.HTTP_400_BAD_REQUEST,
                details={"layout": cleaned["layout"]},
            )
        if "density" in cleaned and cleaned["density"] not in DENSITIES:
            raise ApiError(
                "INVALID_ARGUMENT",
                f"density must be one of {sorted(DENSITIES)}",
                status.HTTP_400_BAD_REQUEST,
                details={"density": cleaned["density"]},
            )
        return cleaned
