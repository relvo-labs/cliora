# Vue + Naive UI UX Review Guide

Use this guide when reviewing Vue 3 applications or Naive UI based interfaces. Treat Naive UI as the design-system layer and review both UX behavior and correct component usage.

## Vue Review Focus

Check the user experience implied by Vue state branches, component props, events, slots, and routing.

- Prefer explicit UI states for `loading`, `error`, `empty`, `success`, `disabled`, `permission denied`, `offline`, and `timeout`.
- Check whether async actions prevent double submission and provide visible progress.
- Verify whether `v-if` / `v-show` state switching preserves user input intentionally.
- Check whether computed labels, disabled states, and validation messages update consistently when dependent fields change.
- For forms, inspect validation trigger timing: avoid only validating after submit when early recovery would help, but avoid noisy validation before the user interacts.
- For route changes and data fetching, check whether page-level feedback avoids blank screens.
- For component composition, check whether slots hide important affordances or make actions hard to discover.
- For transitions, ensure animation does not delay task completion or hide state changes.

## Naive UI Component Checklist

### NForm / NFormItem

- Each field should have a clear label, helper text when needed, and an error message that explains recovery.
- Required fields should be visually and semantically clear.
- Validation triggers should match the field type: blur for text, change for select/date/switch, submit for expensive or cross-field validation.
- Cross-field errors should appear near the field or section that users can fix, not only in a toast.
- Submit buttons should use a loading state and prevent duplicate submission.

### NButton

- Primary, secondary, tertiary, text, and danger buttons should reflect action hierarchy.
- Destructive actions should use danger styling and a confirmation pattern when irreversible.
- Loading buttons should keep stable width where layout shift would be distracting.
- Disabled buttons should explain why the action is unavailable when the reason is not obvious.

### NDataTable

- Tables should show units, timestamps, data freshness, and clear empty/loading/error states.
- Sort, filter, pagination, and search controls should be discoverable and preserve state during navigation when useful.
- Row actions should be scannable and not overload each row with equal visual weight.
- Bulk actions should show selection count, confirmation, and recovery path.
- Dense tables should support responsive behavior or a mobile alternative.

### NModal / NDrawer / NPopconfirm

- Modals should have a clear title, purpose, primary action, cancel action, and escape/close behavior.
- Destructive confirmations should name the target object and consequence.
- Drawers used for editing should protect unsaved changes.
- Focus should move into the overlay and return to the trigger after close.

### NNotification / NMessage / NAlert

- Use transient messages for lightweight confirmation, not for critical errors that users must act on.
- Persistent or blocking problems should use inline errors or alerts near the affected area.
- Messages should state what happened and what the user can do next.

### NSelect / NInput / NDatePicker / NSwitch

- Placeholder text should not replace labels.
- Select options should support search when lists are long.
- Date/time controls should make timezone and format clear when relevant.
- Switches should describe the state and effect, not just use ambiguous on/off labels.

### NConfigProvider / Theme Tokens

- Check consistency with theme tokens rather than one-off styles.
- Verify light/dark mode contrast, hover/focus visibility, and semantic colors for success/warning/error/info.
- Avoid overriding Naive UI styles in ways that break disabled, focus, or validation states.

## Vue + Naive UI Implementation Notes

When giving implementation advice, prefer concrete suggestions such as:

- Use `:loading` and `:disabled` on `NButton` during async submit.
- Use `NForm` rules with appropriate `trigger` values and clear messages.
- Use `NEmpty`, `NSkeleton`, `NSpin`, `NAlert`, or inline fallback states instead of blank areas.
- Use `NPopconfirm` or a confirmation `NModal` for destructive actions.
- Use `NConfigProvider` theme overrides or design tokens for consistency instead of scattered CSS overrides.
- Use `aria-label`, semantic button text, focus management, and keyboard-accessible interactions when Naive UI defaults are not enough.

## Extra Edge Cases

Always check these for Vue + Naive UI apps:

- Initial page load with slow API.
- Submit success, submit failure, validation failure, and duplicate click.
- Empty dataset, partial dataset, and very large dataset.
- Permission denied for hidden/disabled actions.
- Unsaved changes when closing modal/drawer or navigating away.
- Dark mode and high-contrast usage.
- Mobile table behavior and touch target size.
