# UX Review Rubric

Use this reference for screenshot critique, dashboard polish, design QA, and frontend implementation review.

## Actionability Rubric

Every major issue must be actionable. Include:

- problem: what is wrong or risky
- evidence: where it appears in the UI
- impact: why it matters to the user's workflow
- fix: concrete change to layout, component, content, behavior, or code
- priority: p0 / p1 / p2 / p3
- affected component: specific UI area or component name
- implementation note: design token, state handling, component variant, or accessibility note when useful

Reject vague feedback. Replace:

- "make it cleaner" with grouping, spacing, hierarchy, or typography changes
- "improve usability" with a workflow-specific fix
- "looks inconsistent" with the exact inconsistent component or rule

## Heuristic Checks

### Visibility of system status

Check whether users can see:

- current status
- loading/progress
- freshness of data
- success/failure of actions
- paused/offline/degraded states

### Match with real-world workflow

Check whether labels and flow match user mental models:

- operator language instead of database names
- status vocabulary users understand
- units and time zones are clear
- critical workflow order is natural

### User control and freedom

Check whether users can:

- cancel or undo where appropriate
- reset filters
- return from detail view
- recover from errors
- avoid accidental destructive actions

### Consistency and standards

Check whether similar actions, statuses, tables, filters, spacing, and labels behave the same across the screen.

### Error prevention

Check whether the UI prevents:

- destructive misclicks
- invalid form submission
- ambiguous actions
- accidental bulk operations
- stale-data decisions

### Recognition rather than recall

Check whether users can understand the screen without remembering hidden meanings:

- clear labels
- visible active filters
- status legends
- contextual help
- readable row actions

### Flexibility and efficiency

Check whether frequent users can work quickly:

- keyboard shortcuts where relevant
- saved filters
- bulk actions
- quick search
- table column control
- compact density option

### Aesthetic and minimalist design

Check whether the UI removes noise while keeping necessary operational detail. Minimalism must not hide critical state.

### Help users recover from errors

Check whether errors explain:

- what failed
- why it may have failed
- what the user can do next
- whether retry is safe

## Severity Guide

- p0: safety risk, data loss risk, irreversible wrong action, hidden critical status, core workflow blocked
- p1: serious workflow friction, ambiguous operational state, likely user error, missing key edge state
- p2: consistency, readability, layout density, moderate discoverability issue
- p3: minor polish, copy improvement, low-risk visual refinement
