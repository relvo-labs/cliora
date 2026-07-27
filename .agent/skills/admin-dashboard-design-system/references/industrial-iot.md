# Industrial and IoT Dashboard Guidance

Use this reference for equipment monitoring, AMR fleet dashboards, charging stations, LED controllers, camera/streaming systems, industrial control panels, and realtime device management.

## Core Concepts

Industrial and IoT dashboards must prioritize operational clarity over visual decoration. Operators need to know:

1. What is running?
2. What is abnormal?
3. Where is it?
4. How fresh is the data?
5. What action should be taken?
6. What happened before this state?

## Required Device Fields

For device list or detail pages, consider including:

- device name
- device id / serial number
- site / zone / location
- connectivity status
- health status
- current mode
- firmware / software version
- last seen
- telemetry freshness
- assigned task or current job
- owner / maintenance group
- actions available under current permission

## Realtime State Rules

- Show last updated time and stale-data state.
- Distinguish offline, unknown, stale, and error. Do not collapse them into one generic failure state.
- Use optimistic updates carefully for control actions; show pending state until device confirms.
- If polling is paused or failed, make it visible.
- For destructive or physical-world actions, require confirmation and show command delivery status.

## Alert Rules

Alert rows should include:

- severity
- source device or subsystem
- message
- first seen
- last seen
- count / recurrence
- status: active, acknowledged, resolved, suppressed
- owner or assignee
- action: acknowledge, assign, inspect, silence, resolve

Rules:

- Acknowledge means someone saw it; resolve means the underlying condition ended or was closed.
- Critical alerts should remain visible after acknowledgement until resolved.
- Suppression/silencing must have duration, reason, and audit trail.

## Telemetry Panels

Good telemetry panels specify:

- metric name
- unit
- sampling interval
- aggregation method
- threshold line where relevant
- current value
- trend direction
- missing data behavior

Use line charts for time-series trends, gauges only when threshold-based instant reading matters, and tables when exact current values matter more than trend.

## Map / Floorplan / Topology Views

Use map or topology only when spatial relationship affects decisions.

Rules:

- Pair visual map with list/table fallback.
- Make abnormal nodes easy to locate.
- Provide zoom, search, and selection synchronization with the detail panel.
- Do not rely on tiny icons as the only status indicator.

## Maintenance Mode

Maintenance mode should specify:

- who enabled it
- start time
- expected end time
- reason
- affected alerts or automations
- visible banner or badge
- audit trail

Never silently hide maintenance devices from operational summaries unless the page clearly separates active and maintenance states.
