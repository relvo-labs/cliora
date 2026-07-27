"""Bounded audit-trail queries (P4-05, ADR 0016).

This is the read side of `services/audit.py`, and it is deliberately narrow. The
audit table is the one place that records who did what, so an unbounded query
surface over it is both a performance hazard and an information-disclosure one.
Three rules follow from that, and each is enforced here rather than left to the
caller:

* **Every query is time-bounded.** Omitting `from`/`to` does not mean "all of
  history": the window defaults to the last `audit_query_max_days` and a wider
  explicit range is refused. A filter that can be widened without limit is not a
  filter.
* **Filter values come from closed vocabularies.** An unknown `action` is a 422,
  never a pattern match — otherwise the endpoint becomes an arbitrary query
  surface over an append-only table.
* **Paging is keyset, not offset.** The cursor carries `(created_at, id)`, so
  concurrent writes cannot make a later page repeat or skip rows, and deep pages
  do not degrade into a full scan.

Reading the trail writes no audit row of its own (ADR 0016): an Admin reviewing
it would otherwise inflate what they are reviewing, and the read is already in
the request log.
"""

from __future__ import annotations

import base64
import binascii
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.clock import ensure_aware_utc, now_utc
from app.repositories.audit import AuditRepository, AuditRow
from app.services.audit import ALL_ACTIONS, FORBIDDEN_METADATA_KEYS
from app.settings import Settings, get_settings

# Metadata keys that are part of the row's identity rather than its payload, and
# are surfaced as their own response fields instead of inside `metadata`.
_PROMOTED_METADATA_KEYS = frozenset({"request_id"})


@dataclass(frozen=True)
class AuditItem:
    id: uuid.UUID
    action: str
    created_at: datetime
    user_id: uuid.UUID | None
    username: str | None
    display_name: str | None
    node_id: uuid.UUID | None
    node_name: str | None
    session_id: uuid.UUID | None
    request_id: str | None
    metadata: dict[str, Any]


@dataclass(frozen=True)
class AuditPage:
    items: list[AuditItem]
    next_cursor: str | None


def _invalid(message: str) -> ApiError:
    """422, not 400: these are semantic rejections of a syntactically valid query,
    and the UI turns them into "narrow your filter" guidance."""
    return ApiError("INVALID_QUERY", message, status.HTTP_422_UNPROCESSABLE_ENTITY)


def encode_cursor(created_at: datetime, entry_id: uuid.UUID) -> str:
    payload = json.dumps({"t": created_at.isoformat(), "i": str(entry_id)}, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    """Opaque to the client: a malformed or hand-edited cursor is a 422, never a
    silent fall back to the first page (which would loop the caller forever)."""
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode()))
        created_at = datetime.fromisoformat(str(data["t"]))
        entry_id = uuid.UUID(str(data["i"]))
    except (
        binascii.Error,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        UnicodeDecodeError,
        ValueError,
    ) as exc:
        raise _invalid("cursor is not valid") from exc
    if created_at.tzinfo is None:
        raise _invalid("cursor is not valid")
    return created_at, entry_id


def sanitize_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Drop banned keys on the way out.

    `services/audit.py` already minimizes and redacts on the way *in*, which is
    the real control; this is the second half of the same rule applied at the
    boundary that publishes the data. A key that slipped past the write path — or
    predates the rule — must not be served to a browser just because it is in the
    table.
    """
    if not metadata:
        return {}
    return {
        key: value
        for key, value in metadata.items()
        if key not in _PROMOTED_METADATA_KEYS and str(key).lower() not in FORBIDDEN_METADATA_KEYS
    }


class AuditQueryService:
    def __init__(self, session: AsyncSession, *, settings: Settings | None = None) -> None:
        self._repo = AuditRepository(session)
        self._settings = settings or get_settings()

    def _window(self, start: datetime | None, end: datetime | None) -> tuple[datetime, datetime]:
        """Resolve `(from, to)` into an aware-UTC window that is always bounded."""
        max_span = timedelta(days=self._settings.audit_query_max_days)
        bounds: dict[str, datetime | None] = {}
        for label, value in (("from", start), ("to", end)):
            try:
                bounds[label] = ensure_aware_utc(value) if value is not None else None
            except ValueError as exc:
                # A naive instant is ambiguous, and silently assuming UTC would
                # shift every boundary by the operator's offset (ADR 0009).
                raise _invalid(f"`{label}` must include a timezone offset") from exc
        resolved_end = bounds["to"] or now_utc()
        resolved_start = bounds["from"] if bounds["from"] is not None else resolved_end - max_span
        if resolved_start > resolved_end:
            raise _invalid("`from` must not be after `to`")
        if resolved_end - resolved_start > max_span:
            raise _invalid(f"time range must not exceed {self._settings.audit_query_max_days} days")
        return resolved_start, resolved_end

    def _limit(self, limit: int | None) -> int:
        if limit is None:
            return self._settings.audit_page_default
        if limit < 1 or limit > self._settings.audit_page_max:
            raise _invalid(f"`limit` must be between 1 and {self._settings.audit_page_max}")
        return limit

    @staticmethod
    def _actions(actions: list[str] | None) -> list[str] | None:
        if not actions:
            return None
        unknown = sorted(set(actions) - ALL_ACTIONS)
        if unknown:
            raise _invalid(f"unknown action(s): {', '.join(unknown)}")
        return sorted(set(actions))

    async def query(
        self,
        *,
        actions: list[str] | None = None,
        user_id: uuid.UUID | None = None,
        node_id: uuid.UUID | None = None,
        session_id: uuid.UUID | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> AuditPage:
        window_start, window_end = self._window(start, end)
        page_size = self._limit(limit)
        rows = await self._repo.list(
            start=window_start,
            end=window_end,
            # One extra row answers "is there a next page?" without a count(*)
            # over the window — and without ever claiming a total the UI would
            # then have to fake.
            limit=page_size + 1,
            actions=self._actions(actions),
            user_id=user_id,
            node_id=node_id,
            session_id=session_id,
            cursor=decode_cursor(cursor) if cursor else None,
        )
        has_more = len(rows) > page_size
        page = rows[:page_size]
        next_cursor = (
            encode_cursor(page[-1].entry.created_at, page[-1].entry.id)
            if has_more and page
            else None
        )
        return AuditPage(items=[_item(row) for row in page], next_cursor=next_cursor)


def _item(row: AuditRow) -> AuditItem:
    entry = row.entry
    metadata = entry.audit_metadata or {}
    request_id = metadata.get("request_id")
    return AuditItem(
        id=entry.id,
        action=entry.action,
        created_at=entry.created_at,
        user_id=entry.user_id,
        username=row.username,
        display_name=row.display_name,
        node_id=entry.node_id,
        node_name=row.node_name,
        session_id=entry.session_id,
        request_id=request_id if isinstance(request_id, str) else None,
        metadata=sanitize_metadata(metadata),
    )
