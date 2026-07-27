# Actionability Rubric for UX Critique

Use this rubric to make findings repairable. A critique should help a downstream designer or engineer improve the interface, not merely describe a preference.

## A1. Evidence grounding
A finding must cite observable evidence from the screenshot, flow, code, or spec.

Strong:
- “The submit button remains visually enabled while `isSubmitting` is true.”
- “The table shows sensor values but no unit or last-updated timestamp.”

Weak:
- “The page feels confusing.”
- “The design needs more polish.”

## A2. User-goal relevance
Explain which user task is affected and why the issue matters.

Ask:
- What is the user trying to accomplish?
- What decision, action, or confidence does this UI need to support?
- Does the issue block completion, slow comprehension, or increase error risk?

## A3. Repair specificity
The recommended fix must name the target element, behavior, state, or copy change.

Strong:
- “Disable the Save button after first submit, show `Saving...`, and re-enable it only if the request fails.”
- “Add a `Last updated 14:32` timestamp next to the chart title and show a stale-data warning after 5 minutes.”

Weak:
- “Improve feedback.”
- “Make the chart clearer.”

## A4. Implementation feasibility
When reviewing frontend or product artifacts, include implementation direction.

Examples:
- React state branch to add
- semantic element to use
- ARIA/focus behavior
- validation timing
- design token or component pattern
- acceptance criteria

Do not over-specify technology if the artifact does not reveal the stack.

## A5. Severity calibration
Severity must reflect user impact, not reviewer preference.

- Critical: blocks task, causes data loss, serious accessibility barrier, irreversible harm.
- High: likely causes wrong decision, serious confusion, repeated failed attempts.
- Medium: adds friction, support burden, or weakens confidence.
- Low: polish or consistency improvement.

## A6. Verification path
Every major finding should include how to verify the fix.

Examples:
- manual QA scenario
- keyboard-only test
- screen-reader smoke test
- responsive breakpoint check
- analytics event to monitor
- user test task

## A7. Coverage of states
A high-quality UX review checks both the happy path and important non-happy paths.

Required state coverage:
- loading
- empty
- error
- disabled
- success
- permission denied
- timeout/offline
- mobile/responsive
- keyboard/focus

## A8. Minimal hallucination
Distinguish observed problems from hypotheses.

Use:
- “Observed” for visible/proven issues.
- “Likely” for strongly implied issues.
- “Needs validation” for hypotheses that require user testing, analytics, or QA.

## Scoring a Finding

Use this score internally or expose it when the user asks for scoring:

- 5: evidence-grounded, user-relevant, specific repair, implementation note, verification path.
- 4: actionable and specific, but missing either implementation or verification detail.
- 3: useful diagnosis, but fix needs interpretation.
- 2: plausible but vague or weakly grounded.
- 1: subjective, generic, or not repairable.

Findings below 4 should be rewritten before final output when they appear in Must Fix or Should Fix.
