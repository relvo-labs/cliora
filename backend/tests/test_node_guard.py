"""The disabled-node establishing-op guard (FR-NODE-005, hermetic)."""

from __future__ import annotations

import pytest

from app.api.errors import ApiError
from app.db.models import Node
from app.services.nodes import ensure_node_enabled


def test_enabled_node_passes() -> None:
    ensure_node_enabled(Node(name="n", hostname="h", is_enabled=True))


def test_disabled_node_is_refused_with_node_disabled() -> None:
    with pytest.raises(ApiError) as exc:
        ensure_node_enabled(Node(name="n", hostname="h", is_enabled=False))
    assert exc.value.code == "NODE_DISABLED"
    assert exc.value.status_code == 409
