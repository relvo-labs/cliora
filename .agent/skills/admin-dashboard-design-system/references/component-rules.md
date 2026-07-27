# Component Rules

Use this reference when specifying or reviewing admin dashboard components.

## Page Header

Required content:

- page title
- short description when workflow is not obvious
- primary action when available
- scope selector if the page depends on site, tenant, project, fleet, or date range
- freshness indicator for realtime or operational data

Avoid placing too many unrelated actions in the header. Move secondary actions to overflow menus or contextual toolbars.

## KPI Cards

Use KPI cards for high-level status, volume, risk, or progress.

Required anatomy:

- label
- value
- unit where needed
- delta or trend only when meaningful
- status/severity when relevant
- tooltip or help text for ambiguous metrics

Rules:

- Prefer 3-6 cards per summary row.
- Do not mix unrelated units in a visually identical way.
- Show skeletons for loading and clear empty values when no data exists.
- Avoid using KPI cards as navigation unless the affordance is explicit.

## Data Tables

Use tables when users need to scan, compare, sort, filter, or act on many records.

Required features:

- clear primary column
- visible status/severity field when relevant
- sortable important columns
- filterable operational fields
- row-level actions
- empty state
- loading state
- error state
- pagination or virtual scrolling for large datasets

Recommended columns for admin resources:

- name / id
- status
- type/category
- owner/group/site
- last updated / last seen
- version/configuration where relevant
- created/modified metadata
- actions

Rules:

- Keep row height stable.
- Align numbers right; align text left.
- Use monospace only for IDs, hashes, and technical identifiers.
- Use sticky headers for long tables.
- Use horizontal scrolling only when columns are optional and user-controlled.
- Do not hide critical status in a tooltip.

## Filter Bars

Use filters to reduce data to an actionable subset.

Recommended controls:

- search input for name, id, email, device id, or serial number
- status filter
- severity filter
- date/time range
- owner/site/project/fleet selector
- reset filters action

Rules:

- Show active filters clearly.
- Make default filters explicit.
- Persist filters only when it helps repeated work.
- Use server-side filtering for large datasets.

## Forms

Required behavior:

- label every field
- mark required fields clearly
- validate inline
- preserve entered data after validation error
- separate destructive actions from save/cancel
- explain irreversible actions

Rules:

- Group related fields into sections.
- Use helper text for technical values, not placeholders alone.
- Disable submit only when the reason is obvious or explained.
- Show success and failure feedback after submission.

## Status Badges

Use status badges to communicate state quickly.

Rules:

- Use text labels, not color alone.
- Keep status vocabulary small and stable.
- Separate severity from lifecycle status when both exist.
- Include icon when scanning speed matters.

Common status groups:

- health: healthy, warning, critical, unknown
- connectivity: online, offline, degraded, stale
- lifecycle: active, disabled, pending, archived
- job state: queued, running, succeeded, failed, cancelled

## Drawers and Modals

Use drawers for contextual detail without leaving the table or dashboard. Use modals for focused decisions or confirmations.

Rules:

- Detail drawers should preserve page context.
- Forms with many fields usually deserve a full page or drawer, not a small modal.
- Confirmation modals must name the object and consequence.
- Dangerous confirmations should require a deliberate action when impact is high.

## Navigation

Rules:

- Group navigation by user workflow, not database entities alone.
- Highlight current section clearly.
- Keep side navigation labels short and stable.
- Avoid putting rarely used admin tools above high-frequency operational pages.
