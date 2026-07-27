# Output Templates

Use these templates to keep outputs consistent.

## Page Specification Template

```markdown
# [Page Name] Page Spec

## Context
- Dashboard type:
- Primary users:
- Primary job-to-be-done:
- Key assumptions:

## Layout
1. Page header:
2. Summary section:
3. Filter/search area:
4. Main content:
5. Detail surface:
6. Actions and feedback:

## Components
| Component | Purpose | Key fields / controls | States |
|---|---|---|---|

## Table Design
- Primary column:
- Default columns:
- Sortable columns:
- Filters:
- Row actions:
- Bulk actions:
- Empty state:
- Loading state:
- Error state:

## Edge States
- No data:
- Permission denied:
- API error:
- Stale data:
- Partial failure:
- Long text / many records:

## Responsive Behavior
- Desktop:
- Tablet:
- Mobile / narrow viewport:

## Implementation Notes
- Suggested component boundaries:
- Design tokens / variants:
- Accessibility notes:
- Data requirements:
```

## UX Critique Template

```markdown
# UX Review

## Summary
[2-4 sentences describing the overall condition and top risks.]

## Priority Issues
| Priority | Affected component | Problem | Why it matters | Suggested fix |
|---|---|---|---|---|

## Layout and Hierarchy
[Specific layout improvements.]

## Component-Level Fixes
[Table, filters, cards, forms, modals, status badges, navigation.]

## Edge States Checklist
- [ ] Loading
- [ ] Empty
- [ ] Error
- [ ] Permission denied
- [ ] Stale data
- [ ] Partial failure
- [ ] Long text / overflow
- [ ] Mobile / narrow viewport

## Frontend Notes
[Implementation-specific suggestions if code or framework context exists.]
```

## Component Specification Template

```markdown
# [Component Name] Specification

## Purpose

## When to Use

## Anatomy

## Variants

## Behavior

## States
- default:
- hover/focus:
- loading:
- empty:
- error:
- disabled:

## Accessibility

## Do / Don't

## Implementation Notes
```

## QA Checklist Template

```markdown
# Dashboard QA Checklist

## Data and State
- [ ] Loading state exists
- [ ] Empty state explains what to do next
- [ ] API error state includes retry or next step
- [ ] Stale data is visible
- [ ] Time zone and units are clear
- [ ] Long text does not break layout

## Tables and Filters
- [ ] Search works for expected identifiers
- [ ] Filters are visible and resettable
- [ ] Sort behavior is clear
- [ ] Pagination or virtual scroll works for large data
- [ ] Row actions are accessible and safe
- [ ] Bulk actions are confirmed when risky

## Forms and Actions
- [ ] Required fields are marked
- [ ] Validation is inline and specific
- [ ] Save/cancel behavior is clear
- [ ] Destructive actions require confirmation
- [ ] Action success/failure feedback is visible

## Accessibility
- [ ] Status is not color-only
- [ ] Keyboard focus is visible
- [ ] Interactive controls have names
- [ ] Contrast is sufficient
- [ ] Modal/drawer focus behavior is correct

## Responsive
- [ ] Desktop layout supports dense workflows
- [ ] Tablet/narrow layouts remain usable
- [ ] Tables have a responsive strategy
- [ ] Critical actions remain reachable
```
