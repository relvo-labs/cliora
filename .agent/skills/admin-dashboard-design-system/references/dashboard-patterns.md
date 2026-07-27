# Dashboard Patterns

Use this reference when designing page structure, information hierarchy, and dashboard layout.

## Dashboard Type Classifier

### Operational monitoring

Purpose: help users understand current state and react quickly.

Use when the product includes realtime status, incidents, equipment health, online/offline devices, queues, jobs, or alerts.

Recommended structure:

1. page header with scope, freshness, and global actions
2. summary KPI row with health/severity counts
3. primary monitoring surface: chart, map, topology, device grid, or status matrix
4. exception table: alerts, failures, delayed jobs, offline devices
5. detail drawer for inspection without losing context
6. event timeline or logs for diagnosis

Key rules:

- Freshness must be visible: last updated, live/paused, polling interval, stale indicator.
- Critical exceptions should be above general charts.
- Default filters should show actionable issues, not only all data.
- Drill-down must preserve the user's current scope.

### CRUD management

Purpose: help users find, inspect, create, edit, disable, delete, and audit records.

Recommended structure:

1. page title and primary action
2. filter/search bar
3. data table
4. row actions and bulk actions
5. create/edit form or side drawer
6. audit metadata and dangerous-action confirmations

Key rules:

- Primary action should be singular and obvious.
- Common filters should be visible; advanced filters can be collapsible.
- The primary column should navigate to detail.
- Destructive actions must not be adjacent to frequent safe actions without separation.

### Analytical reporting

Purpose: help users compare trends, segment data, and reason about causes.

Recommended structure:

1. date range and segmentation controls
2. KPI cards with deltas and comparison period
3. charts grouped by question, not by chart type
4. table for detailed breakdown
5. export/share action if reporting workflow requires it

Key rules:

- Every chart needs title, unit, time range, and empty state.
- Deltas must specify comparison baseline.
- Avoid chart overload; use tables when exact comparison matters.

### Executive overview

Purpose: summarize health, progress, risk, and next decisions.

Recommended structure:

1. small number of high-signal KPIs
2. trend and risk summary
3. exception list or recommended actions
4. links to detailed operational pages

Key rules:

- Avoid operational noise.
- Emphasize interpretation and decision support.
- Use concise labels and consistent units.

### Incident / alert console

Purpose: help users triage, acknowledge, assign, and resolve incidents.

Recommended structure:

1. severity summary
2. alert queue with filters
3. active incident details
4. timeline/logs
5. ownership and acknowledgement actions
6. escalation and resolution notes

Key rules:

- Severity must use text + color + icon.
- Acknowledgement and resolution must be distinct actions.
- Filtering by severity, source, owner, status, and time is usually required.
- Preserve audit trail.

### Infrastructure / device management

Purpose: manage resources, devices, nodes, services, and their health.

Recommended structure:

1. resource summary
2. resource list/table
3. health/status column
4. configuration metadata
5. detail drawer with telemetry, logs, and actions
6. maintenance and lifecycle controls

Key rules:

- Separate operational state from configuration state.
- Show identity, location, ownership, version, last seen, and health.
- Support bulk actions only when they are safe and reversible or clearly confirmed.
