"""What must not reach the index, removed before it is written (ADR 0038 §8).

Two layers, and they answer different questions.

**The project's declared secrets** go through `SecretService.redact`, which already
exists and lives where it does because `GATE-SC-SINGLE-DECRYPT` requires exactly one
module to turn a stored secret back into plaintext. This module calls it and does not
reimplement it — a helper here would raise that count to two for a convenience.

The names passed are the **project's** `allowed_secret_names` rather than one card's
`required_secrets`, and that difference matters: a repository document belongs to no
card, and it may mention any of the project's secrets.

**Credential-shaped literals** go through a fixed pattern list. Not an entropy
heuristic: an entropy score has a threshold, a threshold has false positives, and a
false positive here silently deletes a sentence from a document somebody wrote. Every
pattern below matches a format that is a credential by construction — a prefix this
platform issues, a PEM header, a provider's documented key shape.

Both run **before** the insert. Afterwards is too late; storing it is the thing being
prevented.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import replace

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Project
from app.services.knowledge.store import ExtractedSource
from app.services.secrets import SecretService

REDACTED = "[已遮蔽]"

#: Formats that are credentials by construction. Kept short on purpose: every entry has
#: to be defensible as "this cannot be anything else", because a pattern that is merely
#: suspicious removes real content from a document nobody will think to check.
_PATTERNS: tuple[re.Pattern[str], ...] = (
    # This platform's own tokens. `run.token` and the session credential both land in
    # files an agent can read, so a document that quotes one is the likeliest accident.
    re.compile(r"cliora_(?:rt|st)_[A-Za-z0-9_\-]{16,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    re.compile(r"\bglpat-[A-Za-z0-9_\-]{20,}\b"),
    re.compile(r"\bxox[abposr]-[A-Za-z0-9\-]{10,}\b"),
    # A URL carrying userinfo. ADR 0031 already forbids the platform from producing one;
    # this catches a person having pasted one into a description.
    re.compile(r"\b[a-z][a-z0-9+.\-]*://[^/\s:@]+:[^/\s@]+@"),
)

#: Filenames never collected, whatever an include rule says. Checked against the base
#: name and against the whole path, because `config/.env.production` is both.
_SENSITIVE_NAMES: tuple[re.Pattern[str], ...] = (
    re.compile(r"(^|/)\.env(\.|$)"),
    re.compile(r"(^|/)\.npmrc$"),
    re.compile(r"(^|/)\.netrc$"),
    re.compile(r"(^|/)id_(rsa|dsa|ecdsa|ed25519)(\.pub)?$"),
    re.compile(r"\.(pem|key|p12|pfx|jks|keystore)$"),
    re.compile(r"(^|/)credentials?(\.|$)"),
    re.compile(r"(^|/)secrets?\.(ya?ml|json|toml|ini)$"),
    re.compile(r"(^|/)\.aws/"),
    re.compile(r"(^|/)\.ssh/"),
)


def is_sensitive_path(path: str) -> bool:
    """Whether a repository path is refused outright.

    Checked **before** collection rather than after: a file that is never read cannot be
    partially redacted into the index by a pattern that did not quite match.
    """
    lowered = path.lower()
    return any(pattern.search(lowered) for pattern in _SENSITIVE_NAMES)


def scrub_literals(text: str) -> str:
    for pattern in _PATTERNS:
        text = pattern.sub(REDACTED, text)
    return text


async def redact_for_index(
    session: AsyncSession, project_id: uuid.UUID, extracted: list[ExtractedSource]
) -> list[ExtractedSource]:
    """Both layers, over a handler's whole output.

    Applied in `sources.ingest` rather than in each handler: eight handlers would be
    eight chances to forget, and what is being prevented is storing a secret.
    """
    if not extracted:
        return extracted
    names = list(
        await session.scalar(
            sa.select(Project.allowed_secret_names).where(Project.id == project_id)
        )
        or []
    )
    secrets = SecretService(session)
    out: list[ExtractedSource] = []
    for item in extracted:
        text = scrub_literals(item.text)
        title = scrub_literals(item.title)
        if names:
            text = await secrets.redact(project_id, names, text)
            title = await secrets.redact(project_id, names, title)
        out.append(replace(item, text=text, title=title))
    return out
