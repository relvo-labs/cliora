"""Workspace favourites and recently-used workspaces (P4-13, FR-WORKSPACE-004/005).

**The non-negotiable premise: this is a UX shortcut, never an authorization source.**

Saving a path grants nothing. Creating a session from a favourite runs the identical
checks as typing the path by hand — Central's prefix authorization against the node's
enabled roots, then the daemon's canonical `os.Root` resolution inside the allowed root.
The same function does the prefix check here as does it on the session-create path
(`services.sessions.authorize_workspace`), imported rather than reimplemented: a second
copy would be the thing that eventually disagrees, and the direction it disagreed in
would decide whether a stored path could escape its root.

A favourite can also *become* invalid after it is saved — a root removed, a directory
deleted, a node disabled. So it is validated on the way in **and** re-validated on every
use, and the listing reports whether each entry is usable now rather than implying it is.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Literal

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.db.models import Node, User, WorkspaceFavorite
from app.repositories.favorites import FavoriteRepository, FavoriteRow, RecentWorkspace
from app.repositories.nodes import NodeRepository
from app.services.sessions import authorize_workspace
from app.settings import Settings, get_settings

# Bounded so one user cannot turn the list endpoint into an unbounded response, and so
# the UI's shortcut row stays a shortcut rather than becoming a second file browser.
MAX_FAVORITES = 100

# Why a favourite cannot be used right now. Coarse codes; the UI owns the wording.
# A closed vocabulary, so a new reason has to be added here and in the DTO together
# rather than appearing as an unrecognised string the UI renders raw.
Usability = Literal["usable", "node_disabled", "node_offline", "outside_allowed_root"]

USABLE: Usability = "usable"
NODE_DISABLED: Usability = "node_disabled"
NODE_OFFLINE: Usability = "node_offline"
OUTSIDE_ALLOWED_ROOT: Usability = "outside_allowed_root"


def validate_path(path: str) -> str:
    """Reject a path that could not be a legitimate workspace, before it is stored.

    Central's prefix check happens next and the daemon re-resolves canonically after
    that; this is the cheap syntactic gate that keeps obvious rubbish out of the table in
    the first place. A stored `..` would be re-rejected on every use, but it has no
    business being persisted — and a control character or NUL in a stored path is a
    problem for whatever later reads it, not only for the resolver.
    """
    if not path or not path.startswith("/"):
        raise ApiError(
            "WORKSPACE_INVALID",
            "Workspace must be an absolute path",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    if len(path) > 4096:
        raise ApiError(
            "WORKSPACE_INVALID", "Workspace path is too long", status.HTTP_422_UNPROCESSABLE_ENTITY
        )
    if "\x00" in path or any(ord(character) < 0x20 for character in path):
        raise ApiError(
            "WORKSPACE_INVALID",
            "Workspace path contains control characters",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    # Checked as path *segments*, so a directory legitimately named "..foo" is allowed
    # while a traversal segment is not.
    if any(segment == ".." for segment in path.split("/")):
        raise ApiError(
            "WORKSPACE_INVALID",
            "Workspace path must not contain '..'",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    return path


class FavoriteService:
    def __init__(self, session: AsyncSession, *, settings: Settings | None = None) -> None:
        self._repo = FavoriteRepository(session)
        self._nodes = NodeRepository(session)
        self._settings = settings or get_settings()

    async def list_favorites(
        self,
        actor: User,
        *,
        seconds_since_heartbeat: Callable[[uuid.UUID], float | None] | None = None,
    ) -> list[tuple[FavoriteRow, Usability]]:
        """The user's favourites, each with a usability verdict.

        The verdict is computed rather than stored: a favourite saved when a root existed
        must not keep claiming to be usable after that root is removed.

        Liveness is injected as a lookup rather than read from a global registry, so this
        stays testable without a connection registry — and so the ordering of the reasons
        is decided in one place instead of half here and half in the route.
        """
        rows = await self._repo.list_for_user(actor.id, limit=MAX_FAVORITES)
        verdicts: list[tuple[FavoriteRow, Usability]] = []
        for row in rows:
            verdicts.append((row, await self.usability(row.favorite, seconds_since_heartbeat)))
        return verdicts

    async def usability(
        self,
        favorite: WorkspaceFavorite,
        seconds_since_heartbeat: Callable[[uuid.UUID], float | None] | None,
    ) -> Usability:
        """Reasons in order of permanence, worst first.

        "The root is gone" outranks "the node is down" deliberately: a favourite that can
        never work again is worth saying so about even while the machine happens to be
        offline, whereas the reverse ordering would show a transient reason for a
        permanent problem and have the user wait for a recovery that fixes nothing.

        Public because the create response must report the *same* verdict as the next
        listing. It previously hard-coded `usable` on the theory that `add()` refuses
        anything unusable — which is false: `add()` deliberately allows favouriting a
        path on a node that is merely offline, so a POST claimed `usable` for a row the
        immediately following GET called `node_offline`.
        """
        node = await self._nodes.get(favorite.node_id)
        if node is None or not node.is_enabled:
            return NODE_DISABLED
        try:
            authorize_workspace(node, favorite.path)
        except ApiError:
            # Still listed, marked unusable with a reason: silently dropping it would
            # leave the user wondering where their favourite went, and showing it as
            # usable would fail only at the moment they tried to use it.
            return OUTSIDE_ALLOWED_ROOT
        if seconds_since_heartbeat is not None and not node_is_online(
            node, seconds_since_heartbeat(favorite.node_id), self._settings
        ):
            return NODE_OFFLINE
        return USABLE

    async def add(
        self, actor: User, *, node_id: uuid.UUID, path: str, display_name: str | None
    ) -> WorkspaceFavorite:
        """Save a favourite, or return the existing one.

        Idempotent by design: a second POST for the same `(user, node, path)` is the same
        intent expressed twice, and answering 409 would make the UI's optimistic toggle
        need a special case for "already there".

        An **offline** node is accepted: bookmarking a path is not starting a session, and
        refusing to save one because the machine happens to be down would make the feature
        useless exactly when planning ahead is most useful. The stored row then reports
        `node_offline` until the node returns.
        """
        validate_path(path)
        node = await self._nodes.get(node_id)
        if node is None:
            raise ApiError("NOT_FOUND", "Node not found", status.HTTP_404_NOT_FOUND)
        if not node.is_enabled:
            raise ApiError("NODE_DISABLED", "Node is disabled", status.HTTP_409_CONFLICT)
        # The same prefix authorization the session-create path uses. A path that could
        # not start a session must not be storable as a shortcut to starting one.
        authorize_workspace(node, path)

        existing = await self._repo.find(actor.id, node_id, path)
        if existing is not None:
            if display_name is not None:
                existing.display_name = display_name
            return existing

        if await self._repo.count_for_user(actor.id) >= MAX_FAVORITES:
            raise ApiError(
                "INVALID_ARGUMENT",
                f"At most {MAX_FAVORITES} favourites are kept per user",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        favorite = WorkspaceFavorite(
            user_id=actor.id, node_id=node_id, path=path, display_name=display_name
        )
        self._repo.add(favorite)
        return favorite

    async def remove(self, actor: User, favorite_id: uuid.UUID) -> None:
        """Delete one of the caller's own favourites.

        Another user's favourite answers **404, not 403**: a 403 would confirm that the id
        exists, which is how a per-user list becomes a way to probe other users' rows.
        """
        favorite = await self._repo.get_owned(favorite_id, actor.id)
        if favorite is None:
            raise ApiError("NOT_FOUND", "Not found", status.HTTP_404_NOT_FOUND)
        await self._repo.delete(favorite)

    async def recent(self, actor: User, *, limit: int | None = None) -> list[RecentWorkspace]:
        bounded = min(
            max(limit or self._settings.recent_workspaces_default, 1),
            self._settings.recent_workspaces_max,
        )
        return await self._repo.recent_for_user(actor.id, limit=bounded)


def node_is_online(
    node: Node | None, seconds_since_heartbeat: float | None, settings: Settings
) -> bool:
    """Whether a session could be started on this node right now.

    Used to annotate favourites and recents. Offline is *not* filtered out — the entry is
    shown with the reason, because "your favourite disappeared" is a worse experience
    than "your favourite is there but that machine is down" (FR-NODE-002).
    """
    if node is None or not node.is_enabled or node.deleted_at is not None:
        return False
    return (
        seconds_since_heartbeat is not None
        and seconds_since_heartbeat <= settings.node_degraded_within_seconds
    )
