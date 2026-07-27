# Nielsen Usability Heuristics Checklist

Use these as diagnostic lenses. Tag findings with the heuristic ID.

## H1. Visibility of system status
The interface should keep users informed about what is happening through timely, appropriate feedback.

Check for:
- loading indicators
- progress, save, sync, upload, processing, and refresh status
- disabled or pending states
- freshness timestamps for data-heavy screens
- confirmation that user actions succeeded or failed

Common UX defects:
- no feedback after submit
- hidden background processing
- stale dashboard data without timestamps
- optimistic UI without failure recovery

## H2. Match between system and the real world
The product should use the user's language and follow domain conventions.

Check for:
- user-facing terminology instead of internal system terms
- natural order of information
- familiar patterns for the domain
- units, formats, dates, currencies, and localization

Common UX defects:
- engineering labels exposed to users
- unclear abbreviations
- dates or measurements without units
- task flow ordered by database structure instead of user intent

## H3. User control and freedom
Users need clear exits, undo paths, and safe recovery from accidental actions.

Check for:
- cancel, back, undo, close, reset, and escape behaviors
- destructive action confirmation
- reversible operations where possible
- unsaved-changes protection

Common UX defects:
- modal cannot be dismissed safely
- accidental destructive action has no recovery
- browser back breaks task state
- no way to exit a multi-step flow

## H4. Consistency and standards
Users should not wonder whether different words, actions, or layouts mean the same thing.

Check for:
- consistent button hierarchy
- consistent labels for the same action
- consistent placement of navigation/actions
- platform and design-system conventions

Common UX defects:
- same action has different labels across screens
- primary button moves between steps
- icons without consistent meaning
- custom controls replacing standard expected behavior

## H5. Error prevention
Prevent problems before they happen, especially serious or irreversible mistakes.

Check for:
- validation before submit
- constraints and input masks
- confirmation for destructive/high-impact actions
- clear previews before irreversible changes
- safeguards against duplicate submission

Common UX defects:
- user can submit invalid forms
- dangerous actions placed beside safe actions
- no confirmation for delete/reset/overwrite
- accidental double-click creates duplicate records

## H6. Recognition rather than recall
Reduce memory burden by making options, context, and required information visible.

Check for:
- visible labels and helper text
- contextual summaries in multi-step flows
- persistent selected filters or scope
- examples and defaults

Common UX defects:
- user must remember previous step values
- icons without labels in complex workflows
- hidden filters affect results invisibly
- vague placeholders replacing labels

## H7. Flexibility and efficiency of use
Support both new and experienced users with efficient paths.

Check for:
- sensible defaults
- shortcuts, bulk actions, recent items, saved filters
- keyboard support
- progressive disclosure
- reduced repetitive input

Common UX defects:
- repetitive manual data entry
- no bulk operation for repeated tasks
- expert users must click through slow onboarding paths
- common actions are buried

## H8. Aesthetic and minimalist design
Interfaces should not contain irrelevant or rarely needed information that competes with important content.

Check for:
- visual hierarchy
- density and grouping
- typography scale
- contrast and emphasis
- removal of redundant labels or visual noise

Common UX defects:
- too many equal-weight elements
- excessive borders, colors, badges, or icons
- important actions visually buried
- dense tables without grouping or scan paths

## H9. Help users recognize, diagnose, and recover from errors
Errors should be written in plain language, identify the issue, and suggest a recovery path.

Check for:
- inline validation and field-level errors
- global error summaries for forms
- retry or fallback actions
- specific cause and next step
- preservation of user input after failure

Common UX defects:
- raw error codes
- generic “something went wrong”
- failed submit clears form data
- no retry or contact-support path

## H10. Help and documentation
Help should be searchable, task-focused, concrete, and available when needed.

Check for:
- contextual help
- tooltips for complex domain concepts
- onboarding only where useful
- docs linked at decision points
- examples for complex setup

Common UX defects:
- help hidden away from the task
- vague documentation that describes features but not steps
- tooltip overload
- first-run users lack guidance for critical setup
