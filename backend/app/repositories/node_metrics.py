"""Persistence and aggregation for `node_metric_samples` (P4-06).

Two consumers, two shapes: the write path appends one bounded row per node per
interval, and the Dashboard aggregates the most recent window across the fleet.
Both are here so the aggregation SQL cannot drift into a service that also owns
freshness policy.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Float, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import NodeMetricSample

# The measurements a fleet summary reports on. Kept as data so adding one is a
# one-line change and cannot be half-applied across the query and the DTO.
MEASUREMENTS: tuple[str, ...] = ("cpu_usage", "memory_usage", "disk_usage", "load_average")


@dataclass(frozen=True, slots=True)
class MeasurementSummary:
    """Fleet summary for one measurement.

    `nodes` counts the nodes that actually reported the value, not the nodes in the
    fleet: averaging over a denominator that includes non-reporting nodes would
    understate every figure. When it is 0 the block is empty, and the UI must say
    "no data" rather than 0%.
    """

    average: float | None
    maximum: float | None
    nodes: int


@dataclass(frozen=True, slots=True)
class FleetResources:
    measurements: dict[str, MeasurementSummary]
    # Nodes with at least one sample in the window, and the newest sample instant.
    sampled_nodes: int
    latest_sample_at: datetime | None


class NodeMetricRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(
        self,
        *,
        node_id: uuid.UUID,
        sampled_at: datetime,
        resources: dict[str, float | None],
        active_sessions: int | None,
    ) -> NodeMetricSample:
        sample = NodeMetricSample(
            node_id=node_id,
            sampled_at=sampled_at,
            active_sessions=active_sessions,
            **{name: resources.get(name) for name in MEASUREMENTS + ("daemon_uptime",)},
        )
        self._session.add(sample)
        return sample

    async def fleet_summary(self, *, since: datetime) -> FleetResources:
        """Aggregate the newest sample per node within the window.

        Per node first, then across the fleet: a node that reported ten times in the
        window would otherwise carry ten times the weight of one that reported once,
        so a single chatty node could dominate the fleet average.
        """
        latest = (
            select(
                NodeMetricSample.node_id.label("node_id"),
                func.max(NodeMetricSample.sampled_at).label("sampled_at"),
            )
            .where(NodeMetricSample.sampled_at >= since)
            .group_by(NodeMetricSample.node_id)
            .subquery()
        )
        newest = (
            select(NodeMetricSample)
            .join(
                latest,
                (NodeMetricSample.node_id == latest.c.node_id)
                & (NodeMetricSample.sampled_at == latest.c.sampled_at),
            )
            .subquery()
        )
        columns = [
            expression
            for name in MEASUREMENTS
            for expression in (
                func.avg(getattr(newest.c, name)).cast(Float),
                func.max(getattr(newest.c, name)),
                func.count(getattr(newest.c, name)),
            )
        ]
        statement = select(
            *columns,
            func.count(func.distinct(newest.c.node_id)),
            func.max(newest.c.sampled_at),
        )
        row = (await self._session.execute(statement)).one()

        measurements: dict[str, MeasurementSummary] = {}
        for index, name in enumerate(MEASUREMENTS):
            average, maximum, reporting = row[index * 3 : index * 3 + 3]
            measurements[name] = MeasurementSummary(
                average=float(average) if average is not None else None,
                maximum=float(maximum) if maximum is not None else None,
                nodes=int(reporting or 0),
            )
        return FleetResources(
            measurements=measurements,
            sampled_nodes=int(row[-2] or 0),
            latest_sample_at=row[-1],
        )
