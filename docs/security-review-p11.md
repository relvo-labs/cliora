# Security review — port forwarding through a third-party provider (plan/11, ADR 0022)

Scope: everything reachable through the port-forwarding integration — the platform's custody
of a third-party credential, the node's `ssh` child process, and the three-layer configuration
policy that decides whether a port may be forwarded at all.

**Evidence rule** (same as `docs/security-review-p4.md` and `-p8.md`). Every row names a test or
a file. "Implemented" is a claim, not evidence. A partly-covered row says so, and the gap
appears in [Findings](#3-findings) rather than being smoothed over.

**Why this review is different from the previous two.** P8 reviewed a capability that escalated
nothing: the shell exposed privileges the daemon already had. This one adds two genuinely new
things. The platform now **holds a secret it must be able to read back** — every other secret in
the system is hashed — and a node now **opens an outbound connection to a party outside our
infrastructure** which can see the unencrypted HTTP it relays. Neither is mitigated by any
control below; they are the cost of the decision recorded in ADR 0022, and the review's job is
to make sure the things that *are* controllable were.

---

## 1. Attack table

| # | Attempt | Expected | Evidence | Verdict |
|---:|---|---|---|---|
| 1 | Provider presents a host key that does not match the pinned one | `ssh` refuses; the platform shows `TUNNEL_PROVIDER_UNTRUSTED`; **no fallback to unverified** | `daemon/internal/tunnel#TestStartRefusesWhenTheHostKeyDoesNotMatch`, `#TestArgsPinTheHostKeyAndRefuseToSkipIt`; repository-wide gate `backend/tests/test_security.py::test_no_source_disables_provider_host_key_verification` forbids `StrictHostKeyChecking=no` and `UserKnownHostsFile=/dev/null` in every source, script, workflow and deployment file | **pass** |
| 2 | `known_hosts` file missing or empty | The child process is never started (dial count 0), rather than "verification skipped" | `#TestArgsRefuseAnEmptyKnownHostsPath`, `#TestStartRefusesWithoutAPinnedKeyFile`. The daemon reports it as `TUNNEL_PROVIDER_UNTRUSTED`, not `_UNAVAILABLE`, so nobody is sent to check a firewall | **pass** |
| 3 | Read the provider credential out of the database | AES-GCM ciphertext with a per-write nonce; a wrong key cannot decrypt; **no column and no code path holds plaintext** | `backend/tests/test_secret_box.py` (round trip, fresh nonce per write, wrong key, tampering detected); `backend/tests/db/test_tunnels_api.py::test_the_stored_token_is_ciphertext_in_the_database` asserts the stored bytes do not contain the token | **pass** |
| 3b | Read it back through an interface | No response contains any character of it: `configured` plus an 8-hex fingerprint. The DOM has none either; the audit trail records the fingerprint | `::test_the_integration_response_never_carries_the_token` (asserted against the serialized body, not the DTO type), `::test_the_credential_audit_records_the_fingerprint_and_nothing_else`, vitest `IntegrationsView.test.ts#shows only the fingerprint for a stored credential, never the token` and `#clears the input after saving so the token does not stay bound to the DOM` | **pass** |
| 3c | Find it on the node | Delivered in `tunnel.open` over the existing TLS control connection; the daemon puts it in the child's argv and nowhere else — not on disk, not in the pid file, not in a log line, not in `doctor` output | `daemon/internal/tunnel#TestTheCredentialIsNeverWrittenToDiskOrLogged` opens a tunnel with a credential and then asserts the negative directly: the value appears in **no file the daemon wrote** (the run directory is walked, and the walk fails if it found nothing to read) and in **nothing it logged** (the handler is captured). Verified to fail on a deliberate one-line `slog` leak before being committed. Plus `#TestArgsAreNeverPassedThroughAShell`, `#TestAPidFileIsWrittenAndRemoved` | **pass** |
| 3d | Inject through the credential's character set (`abc+tcp`, `tok@evil.host`) | Refused at the API, in the wire schema, and in the daemon | `::test_a_token_outside_the_permitted_character_set_is_refused`; `contracts/v1/fixtures/invalid/tunnel-open-credential-with-plus.json` (rejected by all three languages via `make contract`); `daemon/internal/tunnel#TestArgsRejectACredentialThatCouldRedirectTheTunnel`. **This is the entry point for choosing the SSH destination and the tunnel type**, which is why it is validated three times rather than once | **pass** |
| 3e | Run without `CLIORA_SECRET_ENCRYPTION_KEY` | Enabling the integration and storing a credential both return `SECRET_KEY_MISSING`; **no degradation to plaintext**; `/readyz` reports the feature as unavailable while staying ready | `test_secret_box.py::test_without_a_key_encryption_refuses_rather_than_storing_plaintext`, `::test_settings_rejects_a_key_of_the_wrong_length`; `app/main.py` `/readyz` body carries `tunnel_integration`; vitest `IntegrationsView.test.ts#replaces the whole form when the deployment has no encryption key` | **pass** |
| 4 | Basic-auth password containing the provider's option separator (`:`) | Refused in the schema, in Central and in the daemon; arguments are passed as `[]string`, never through a shell | `contracts/v1/fixtures/invalid/tunnel-open-colon-in-password.json`; `backend/tests/test_tunnel_policy.py::test_the_generated_password_never_contains_the_providers_separator`; `daemon/internal/tunnel#TestArgsRejectBasicAuthContainingTheOptionSeparator`, `#TestArgsAreNeverPassedThroughAShell` | **pass** |
| 5 | Recover the one-time password after creation | Impossible: only an Argon2 hash is stored, and no read response has a field for it | `::test_creating_returns_the_url_and_the_only_copy_of_the_password` (list response asserted free of it, DB hash verified against the plaintext); vitest `NodeTunnelsView.test.ts#shows the one-time password in the creation dialog and nowhere else` | **pass** |
| 6 | Make the platform show a hostile URL (`http://`, `javascript:`, unknown domain, oversized) | The daemon accepts only the measured https suffixes; the wire schema is a second layer; Central re-checks the `https://` prefix before storing | `daemon/internal/tunnel#TestExtractURLAcceptsTheMeasuredSuffixes`, `#TestExtractURLIgnoresTheDashboardLink`; `contracts/v1/fixtures/invalid/tunnel-opened-http-url.json`; `app/services/tunnels.py` rejects a non-https URL and rolls the row back | **pass** |
| 7 | Forward a privileged port (22, 80) or one outside the allowlist | Refused at four independent layers: wire schema, database CHECK, Central, daemon | `::test_a_privileged_port_is_refused_before_it_reaches_the_node` (asserts no frame was sent), `db/test_tunnel_schema.py::test_a_port_below_the_floor_cannot_be_stored_at_all` (raw INSERT), `daemon/internal/config#TestPortsBelow1024AreNeverAllowed`, `daemon/internal/tunnel#TestArgsRejectPrivilegedPorts` | **pass** |
| 8 | Cross the permission boundary | Viewer: 403 at the **action** layer for both tunnel routes. Developer: 403 on every integration-settings route (`integration.manage` is Admin-only). Developer closing a colleague's tunnel: 403 at the **scope** layer | `::test_a_viewer_holds_neither_tunnel_action`, `::test_a_developer_may_not_touch_the_integration_settings`, `::test_a_developer_cannot_close_someone_elses_tunnel_but_an_admin_can` | **pass** |
| 8b | Widen the policy from the platform side | Every layer may only narrow. A node's `tunnel.enabled: false` is final, and no API path overrides it; three port lists intersect | `test_tunnel_policy.py::test_the_nodes_veto_survives_everything_the_platform_says`, `::test_three_port_lists_intersect_instead_of_the_last_one_winning`, `::test_a_refusal_names_the_layer_that_refused`; second layer on the node: `daemon/internal/config#TestAnExplicitFalseIsAnAbsoluteVeto`, `#TestAConfiguredAllowlistCanOnlyNarrow`, and `connection/tunnel_handlers.go` re-checks both on every open | **pass** |
| 9 | Leave an orphaned `ssh` process behind (`kill -9` the daemon, then restart) | The previous generation's child is gone and its pid file is cleaned; unrelated processes are untouched | `daemon/internal/tunnel#TestReapOrphansKillsAPreviousGenerationsTunnel`, `#TestReapOrphansLeavesUnrelatedProcessesAlone`, `#TestCloseStopsTheProcessAndReports`, `#TestStopEndsTheProcess`; and against a live stack, `scripts/pg/tunnel-stack-check.sh` asserts that no provider process survives a close (a real `pgrep`, not a mock) | **pass** |
| 10 | Read secrets or URLs out of the audit trail and logs | No URL, no password, no token, no label. `public` protection writes its own `tunnel.public_acknowledged` action; the first-time acknowledgement is answered from the trail itself | `::test_the_paid_tier_sends_the_decrypted_credential_and_records_its_fingerprint` (asserts `url` absent from metadata), `::test_an_unprotected_tunnel_requires_its_own_acknowledgement_and_is_audited`, `::test_the_first_tunnel_on_a_node_requires_the_third_party_acknowledgement`; `FORBIDDEN_METADATA_KEYS` and `test_audit_redaction.py` still apply — and the redaction pass is why the tunnel metadata key is `fingerprint` rather than `credential_fingerprint`, which would be masked to `***` | **pass** |
| 11 | Silently accept an anonymous tunnel when a paid credential was rejected | The provider does not refuse a bad credential — it downgrades to an anonymous free tunnel and returns a URL (measured, PG-01 #10). Both ends refuse it | `daemon/internal/tunnel#TestStartTearsDownWhenTheProviderDowngradesAPaidTunnel`; Central re-checks `authenticated` and tears down: `::test_a_silently_anonymous_tunnel_is_rejected_rather_than_handed_over` | **pass** |
| 12 | Reach a node's tunnel by reporting status from a different node | Ignored: a `tunnel.status` frame may only speak about tunnels belonging to the node that sent it | `::test_a_status_report_for_another_nodes_tunnel_is_ignored` | **pass** |
| 13 | Keep a tunnel alive after the node is disabled, removed, or its credential revoked | All live tunnels on that node are closed and audited with the reason; the rows stop counting against the fleet budget | `::test_disabling_a_node_closes_its_tunnels`; the same path runs on removal and credential revocation (`app/services/nodes.py`) | **pass** |

---

## 2. What no control here addresses

These are recorded, not tested. Each one is a consequence of the decision, and writing it down
is the only honest treatment.

1. **The provider sees the traffic.** Pinggy terminates TLS, so it can read the unencrypted
   HTTP it relays — including `Cookie` and `Authorization`, which pass through unchanged
   (measured, PG-01 #11). No control in the table above changes this. It is why the capability
   is scoped to *previewing applications under development* and why both acknowledgements
   (D14) state it in plain words rather than in a link.
2. **A process with the same uid on the node can read the credential.** It lives in the
   `ssh` child's argv and in the daemon's memory — the provider's interface leaves no
   alternative. The daemon running as a non-root user is both the protection and the boundary.
   Third appearance of the same sentence in three features (ADR 0021's shell, plan/10's
   proxy, this).
3. **The platform is now a custodian of a third-party credential.** Two consequences that
   belong in the runbook, not in a test: losing `CLIORA_SECRET_ENCRYPTION_KEY` means the stored
   credential cannot be decrypted — the remedy is entering it again, not recovering it — and a
   compromise of the platform must be treated as a compromise of that credential, to be
   rotated at the provider.
4. **The free tier's hostname contains the node's public IP** (`xxxxx-114-32-49-189.…`,
   measured PG-01 #2c). Anyone given the URL learns the machine's address. Disclosed in the
   UI and in the release note.
5. **There is no access log for the preview.** The traffic never reaches the platform, so
   "who opened this URL" is unanswerable by design. This is a capability gap, not a privacy
   feature, and `SEC-006`'s narrative says so.
6. **Disabling the integration does not close live tunnels** (04 §0.2). Deliberate: closing
   requires reaching every node, some of which are offline, and an action that can partly fail
   must not be dressed as a switch. The UI splits it into two reportable actions.
7. **Exit classification depends on matching the provider's stderr strings** (03 §2.4). If the
   provider rewords its messages, every distinguishable failure degrades to
   `TUNNEL_PROVIDER_UNAVAILABLE` — the pinned-host-key case included, which is the one worth
   watching for.
8. **No fallback.** If the provider is down, the feature is down (D15). Building a fallback
   means building the reverse proxy `SCOPE-013` forbids.

---

## 3. Findings

| id | Severity | Finding | Disposition |
|---|---|---|---|
| F-1 | Info | The three Pro-tier provider facts (60-minute behaviour observed to completion, persistent-subdomain hostname, real concurrency limit of a paid plan) are unverified: PG-01 ran without a Pro token | Staging-gated behind `GATE-TUNNEL-PROVIDER`; recorded in `plan/11/07-implementation-status.md`. `concurrent_budget` defaults to 8 and the settings page tells the administrator to match their plan, because exceeding it evicts somebody else's tunnel rather than queueing |
| F-2 | Low | ~~No test greps a node's filesystem for the credential after an open.~~ | **Closed 2026-08-01**: `TestTheCredentialIsNeverWrittenToDiskOrLogged` measures the negative for both the run directory and the log, and was verified to fail on a deliberate leak. What remains outside it is a whole-filesystem sweep on a live node, which no unit test can do honestly — the stack check covers the process side of the same question |
| F-3 | Low | The browser leg of the stand-in-provider stack cannot run on an unprivileged host: Playwright's system libraries need root (`playwright install --with-deps`) | **Partly closed 2026-08-01.** The stack itself is built (`faketunnelprovider`, `faketunnelapp`, `scripts/e2e/run-stack.sh`), and its **platform path is verified locally**: `scripts/pg/tunnel-stack-check.sh` drives Central, the protocol, the supervisor and the fake provider through 14 assertions with no browser. `frontend/tests/e2e/tunnel.spec.ts` exists and runs in CI (`p2.yml` runs the whole `tests/e2e` directory on chromium/firefox/webkit). Only the *rendering* assertions are unverifiable on this host, and the evidence pack records that as an environment skip rather than a pass |
| F-4 | Info | `PG-12` (iframe embedding) is not done, so nothing here relaxes CSP. `frame-ancestors 'none'` is unchanged in both edge configurations | Closed by decision, recorded in `plan/11/07-implementation-status.md` (D-5) |

No Critical or High findings.

---

## 4. How to re-run this review

```bash
# The whole gate set this review cites, minus the provider account:
make format-check lint typecheck unit contract
CLIORA_TEST_DATABASE_URL=... CLIORA_DATABASE_URL=... make test-db
cd daemon && go test -race ./...
cd frontend && npm run test:unit -- --run

# The host-key gate on its own (the one that must never be weakened):
uv run --project backend pytest \
  backend/tests/test_security.py::test_no_source_disables_provider_host_key_verification -q

# The scope guard that keeps a reverse proxy from growing back:
uv run --project backend pytest \
  backend/tests/test_scope_guards.py::test_scope_013_central_does_not_proxy_to_a_node_http_service -q

# Against the real provider (needs an account; release-triggered):
scripts/tunnel/verify-provider.sh
```
