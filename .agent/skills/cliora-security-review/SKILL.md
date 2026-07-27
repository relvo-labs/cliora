---
name: cliora-security-review
description: >-
  Review Cliora trust boundaries for authentication, RBAC, enrollment, daemon credentials, WebSockets, runtime launching, terminal access, workspace paths, sensitive files, audit logs, and non-root execution. Use when auditing designs, code, APIs, protocol changes, installers, or releases.
---

# Cliora Security Review

1. Use `cliora-project-context`; identify assets, actors, boundaries, entry points, and requirement IDs.
2. Read PRD section 15 and tech sections 14, 15, and 23 plus implementation and tests.
3. Trace untrusted input through validation, authorization, and daemon execution.
4. Test stolen tokens, malicious workspaces, symlinks, replay, takeover, concurrent viewers, and forged messages.
5. Separate confirmed defects from design questions.

For every finding include severity, evidence, asset, exploit precondition, impact, fix, and verification.

Check HTTP and both WebSocket authentication/authorization; enrollment expiry and replay; daemon credential revocation; runtime allowlists; canonical allowed-root containment; sensitive/binary/oversized file denial; authorized reattach; TLS peer validation; audit/log redaction; and non-root least privilege. If evidence is incomplete, state what must be inspected.
