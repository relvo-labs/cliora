"""The error catalog cannot drift from the code, and carries nothing unsafe (P4-07).

An error catalogue is only useful if it is complete and current. One stale row and an
operator stops trusting the whole table, which is worse than having no table — so the
checks here are bidirectional: a code Central raises must be documented, and a
documented code must be real.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from app.api import error_catalog
from app.api.error_catalog import CATALOG, DAEMON, protocol_error_codes, safe_message
from app.services import audit

ROOT = Path(__file__).parents[2]
APP = ROOT / "backend/app"


def _app_sources() -> list[str]:
    return [
        path.read_text(encoding="utf-8")
        for path in APP.rglob("*.py")
        if "migrations" not in path.parts and path.name != "error_catalog.py"
    ]


# Every way the app turns a code into a client-visible error. `ApiError` alone is not
# enough: `services/auth.py` raises through an `_unauthorized(code, message)` wrapper,
# so a scan for `ApiError("…")` reported four real codes as fictional. That is the same
# defect that made `audit.view` look enforced in P4-03 — a scan narrow enough to prove
# the wrong thing — so both raiser shapes are matched, and a new wrapper has to be
# added here.
_RAISERS = re.compile(r"(?:ApiError|_unauthorized)\(\s*\n?\s*\"([A-Z][A-Z0-9_]+)\"")


def raised_codes() -> set[str]:
    """Codes this service raises as an error, found in the source text.

    A literal scan on purpose: the point is to catch a code introduced at a call site
    without a catalog entry, and only the source shows that.
    """
    found: set[str] = set()
    for source in _app_sources():
        found.update(_RAISERS.findall(source))
    return found


def mentioned_codes() -> set[str]:
    """Every upper-snake literal the app mentions anywhere.

    Used only for the "nothing fictional" direction, where over-collecting is safe: a
    code that appears nowhere in the codebase and is not in the wire enum is one nothing
    can produce. Codes reported in a payload rather than raised (`CANCELLED` in
    `services/files.py`) are real, and this is how they are seen.
    """
    pattern = re.compile(r"\"([A-Z][A-Z0-9_]{3,})\"")
    found: set[str] = set()
    for source in _app_sources():
        found.update(pattern.findall(source))
    return found


# --------------------------------------------------------------------------- #
# Completeness, in both directions
# --------------------------------------------------------------------------- #


def test_every_code_central_raises_is_documented() -> None:
    undocumented = sorted(raised_codes() - set(CATALOG))
    assert undocumented == [], (
        f"codes raised but absent from the catalog: {undocumented}. "
        "Add them to app/api/error_catalog.py and re-render the doc."
    )


def test_every_protocol_error_code_is_documented() -> None:
    """The wire enum is closed, so any code in it can reach a client through the relay.
    An undocumented one arrives at the UI with no cause and no next step."""
    missing = sorted(protocol_error_codes() - set(CATALOG))
    assert missing == [], f"protocol error codes absent from the catalog: {missing}"


def test_the_catalog_documents_nothing_fictional() -> None:
    """An entry for a code nothing can produce is the other half of drift: it makes the
    table look comprehensive while describing behaviour that does not exist."""
    real = mentioned_codes() | protocol_error_codes()
    fictional = sorted(set(CATALOG) - real)
    assert fictional == [], (
        f"catalog entries for codes nothing produces: {fictional}. "
        "Either wire them up or remove them."
    )


def test_every_entry_appears_in_exactly_one_rendered_section() -> None:
    """A code in no section is silently omitted from the published table; a code in two
    is rendered twice with the same content."""
    sys.path.insert(0, str(ROOT / "scripts/p4"))
    import render_error_catalog

    listed = [code for _, codes in render_error_catalog.SECTIONS for code in codes]
    assert sorted(listed) == sorted(CATALOG), "sections and catalog disagree"
    assert len(listed) == len(set(listed)), "a code is listed in two sections"


def test_the_published_catalog_is_current() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/p4/render_error_catalog.py"), "--check"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


# --------------------------------------------------------------------------- #
# Content safety
# --------------------------------------------------------------------------- #


# Credential *shapes*, not field names. An earlier version banned the words
# "password" and "Bearer", which flagged "Invalid username or password" and "Missing
# bearer token" — both of which name a field and disclose nothing. What must never
# appear is a value: an assignment, a bearer token, a connection string, a JWT.
_SECRET_SHAPES = (
    re.compile(r"(?:password|token|secret|pepper)\s*[=:]\s*\S", re.I),
    re.compile(r"Bearer\s+[A-Za-z0-9._-]{8,}"),
    re.compile(r"\b\w+://[^\s]*:[^\s]*@"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\."),
)


@pytest.mark.parametrize("code", sorted(CATALOG))
def test_no_message_carries_a_path_or_a_credential(code: str) -> None:
    """These strings are returned to a browser verbatim. A server path in one would
    disclose the deployment's layout to every user who triggers it."""
    item = CATALOG[code]
    blob = " ".join([item.message, item.cause, item.next_step])
    # `/etc/agentd/config.yaml` in a next-step is a documented, fixed location an
    # operator needs; what must not leak is a *deployment's* own layout, so the check
    # targets paths outside the two the installer itself defines.
    for match in re.findall(r"/(?:etc|var|root|home|usr)/[\w./-]*", blob):
        assert match.startswith(("/etc/agentd", "/usr/local/bin/agentd", "/var/lib/agentd")), (
            f"{code} names a server path: {match}"
        )
    for shape in _SECRET_SHAPES:
        assert not shape.search(blob), f"{code} contains a credential-shaped value"


@pytest.mark.parametrize("code", sorted(CATALOG))
def test_every_entry_states_a_cause_and_a_next_step(code: str) -> None:
    """A code with no guidance is a code the UI can only echo. "None" is an acceptable
    next step — "nothing to do" is guidance — but silence is not."""
    item = CATALOG[code]
    assert item.cause.strip(), code
    assert item.next_step.strip(), code
    assert item.cause.strip().endswith("."), f"{code}: cause reads as a fragment"


def test_the_uniform_forbidden_message_reveals_nothing_about_the_resource() -> None:
    """Both refusal layers share one message so a caller cannot use the response to
    learn whether a resource exists or who owns it (ADR 0016)."""
    forbidden = CATALOG["FORBIDDEN"]
    assert forbidden.message == "You do not have permission for this action"
    for leak in ("owner", "belongs to", "session", "node"):
        assert leak not in forbidden.message.lower()


def test_retryable_is_not_claimed_for_permanent_failures() -> None:
    """Offering retry where it cannot work trains users to ignore the button."""
    for code in ("FORBIDDEN", "FILE_DENIED", "RUNTIME_NOT_ALLOWED", "UPDATE_CHECKSUM_MISMATCH"):
        assert not CATALOG[code].retryable, code
    for code in ("NODE_OFFLINE", "REQUEST_TIMEOUT", "INTERNAL_ERROR", "NODE_BUSY"):
        assert CATALOG[code].retryable, code


def test_audited_matches_the_security_relevant_refusals() -> None:
    """Only security-relevant refusals are audited (ADR 0016). A catalog that claimed
    otherwise would send an operator looking for rows that were never written."""
    assert CATALOG["FORBIDDEN"].audited
    assert CATALOG["UPDATE_CHECKSUM_MISMATCH"].audited
    assert CATALOG["FILE_DENIED"].audited
    # Validation and plain not-found are high-volume and uninteresting.
    for code in ("INVALID_ARGUMENT", "INVALID_QUERY", "NOT_FOUND", "CANCELLED"):
        assert not CATALOG[code].audited, code
    # And the audit vocabulary really does contain the events this claims.
    assert audit.AUTHZ_DENIED in audit.ALL_ACTIONS
    assert audit.DAEMON_UPDATE_RESULT in audit.ALL_ACTIONS


# --------------------------------------------------------------------------- #
# safe_message
# --------------------------------------------------------------------------- #


def test_safe_message_returns_the_catalog_wording() -> None:
    assert safe_message("NODE_OFFLINE") == CATALOG["NODE_OFFLINE"].message


def test_safe_message_falls_back_rather_than_echoing_an_unknown_code() -> None:
    """A code this Central does not know — a newer daemon, a corrupted frame — must
    still produce a sentence, not the raw code or a KeyError."""
    message = safe_message("SOMETHING_NEW_FROM_A_FUTURE_DAEMON")
    assert message == "The request could not be completed"


def test_the_daemon_origin_marking_matches_the_protocol_enum() -> None:
    """`origin: daemon` is what tells a reader a code can arrive over the wire. If it
    disagreed with the enum, the table would misdescribe where a failure came from."""
    wire = protocol_error_codes()
    for code, item in CATALOG.items():
        if item.origin == DAEMON:
            assert code in wire, f"{code} is marked daemon-origin but is not in the wire enum"


def test_the_frontend_knows_every_code_it_can_receive() -> None:
    """The browser pairs the server's safe message with its own cause/next-step. A code
    it does not know renders with no guidance, which is the difference between an error
    a user can act on and one they can only screenshot."""
    source = (ROOT / "frontend/src/utils/errorCatalog.ts").read_text(encoding="utf-8")
    block = re.search(r"const GUIDANCE: Record<string, ErrorGuidance> = \{(.*?)\n\};", source, re.S)
    assert block is not None, "GUIDANCE is missing from frontend/src/utils/errorCatalog.ts"
    known = set(re.findall(r"^  ([A-Z][A-Z0-9_]+):", block.group(1), re.M))
    assert known == set(CATALOG), (
        f"only on the server: {sorted(set(CATALOG) - known)}; "
        f"only in the browser: {sorted(known - set(CATALOG))}"
    )


def test_the_frontend_retry_affordance_matches_the_catalog() -> None:
    """Retryability is part of the contract, not a UI choice: a "Retry" button on a
    permanent failure teaches users to ignore it everywhere."""
    source = (ROOT / "frontend/src/utils/errorCatalog.ts").read_text(encoding="utf-8")
    entries = re.findall(
        r"^  ([A-Z][A-Z0-9_]+): \{.*?retryable: (true|false),", source, re.S | re.M
    )
    assert entries, "could not parse the browser's retryable flags"
    for code, flag in entries:
        assert (flag == "true") == CATALOG[code].retryable, (
            f"{code}: browser says retryable={flag}, catalog says {CATALOG[code].retryable}"
        )


def test_the_contract_schema_is_the_source_of_the_wire_enum() -> None:
    """Read from the schema, not restated: a copy would drift, and the direction of the
    drift decides whether a real daemon error is documented at all."""
    assert error_catalog._CONTRACT_ENVELOPE.is_file()
    assert "FRAME_TOO_LARGE" in protocol_error_codes()
