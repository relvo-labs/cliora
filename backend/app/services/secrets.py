"""The project secret store: write it, hand it out once, never read it back.

FR-RUNENV-001…003, ADR 0032. Three disciplines are written here rather than spread
across the routes that use them, because each is easy to undo by accident:

**Nothing returns plaintext except `materialise`.** That function has exactly one
caller — `RunService.poll`, at the claim — and `GATE-SC-SINGLE-DECRYPT` asserts by
scanning for a second one. Every extra caller is another path a security review has to
trace, and they tend to arrive as a one-line convenience.

**Reads name their columns.** `_summary_query` selects the seven non-ciphertext columns
rather than the whole row. The reason is not performance: it is that a future
`dict(row.__dict__)` or a permissive DTO cannot reach a ciphertext that was never
loaded.

**`materialise` audits inside the caller's flush.** Splitting the delivery from its
record leaves a window in which a machine holds a secret and nothing says so. A runner
that declines afterwards has still received them, and the audit says so rather than
being retracted — that is the honest record and a known cost of claiming at poll
(ADR 0032 Consequences).
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.api.errors import ApiError
from app.clock import now_utc
from app.db.models import Project, ProjectRepository, ProjectSecret
from app.security import secret_envelope
from app.services import audit as audit_actions
from app.services.audit import AuditService
from app.settings import Settings, get_settings

# The four kinds, and where each one goes on a node (ADR 0032 §4).
KINDS = frozenset({"env", "git_pat", "git_ssh_key", "provider_token"})
# Delivered only when the deployment has turned platform-managed git credentials on.
GIT_KINDS = frozenset({"git_pat", "git_ssh_key"})
# Never delivered in this phase: its purpose is opening a pull request, which is V2.4.
UNDELIVERABLE_KINDS = frozenset({"provider_token"})

# A name becomes an environment variable, so a secret called `foo-bar` and one called
# `PATH` are two different disasters.
_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
# Names that would take over the execution environment rather than add to it. Refused
# at creation, where the person is standing, rather than skipped on the node, where the
# only evidence is a log line.
RESERVED_NAMES = frozenset(
    {"PATH", "HOME", "USER", "SHELL", "PWD", "LD_PRELOAD", "LD_LIBRARY_PATH", "IFS", "TMPDIR"}
)
# `GIT_*` is not decorative: a secret named `GIT_ASKPASS` would take over the whole
# credential-helper mechanism the PAT path is built on.
RESERVED_PREFIXES = ("GIT_", "SSH_", "CLIORA_")

_SUMMARY_COLUMNS = (
    ProjectSecret.id,
    ProjectSecret.project_id,
    ProjectSecret.name,
    ProjectSecret.kind,
    ProjectSecret.created_by,
    ProjectSecret.created_at,
    ProjectSecret.rotated_at,
    ProjectSecret.last_used_at,
)


@dataclass(frozen=True, slots=True)
class MaterialisedSecret:
    """One secret on its way to a node. Exists for the length of one offer frame."""

    name: str
    kind: str
    value: str


class SecretService:
    def __init__(self, session: AsyncSession, *, settings: Settings | None = None) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._audit = AuditService(session)

    # --- reads (never plaintext) ---------------------------------------------

    async def list_for(self, project_id: uuid.UUID) -> list[ProjectSecret]:
        rows = await self._session.execute(
            select(ProjectSecret)
            .options(load_only(*_SUMMARY_COLUMNS))
            .where(ProjectSecret.project_id == project_id, ProjectSecret.deleted_at.is_(None))
            .order_by(ProjectSecret.name)
        )
        return list(rows.scalars())

    async def require(self, project_id: uuid.UUID, secret_id: uuid.UUID) -> ProjectSecret:
        secret = await self._session.get(ProjectSecret, secret_id)
        if secret is None or secret.project_id != project_id or secret.deleted_at is not None:
            raise ApiError("NOT_FOUND", "Secret not found", status.HTTP_404_NOT_FOUND)
        return secret

    async def existing_names(self, project_id: uuid.UUID) -> set[str]:
        rows = await self._session.execute(
            select(ProjectSecret.name).where(
                ProjectSecret.project_id == project_id, ProjectSecret.deleted_at.is_(None)
            )
        )
        return set(rows.scalars())

    async def missing_names(self, project_id: uuid.UUID, names: list[str]) -> list[str]:
        """Declared names with no secret behind them.

        Distinct from "not in the allowlist", and the two get different messages: one is
        fixed in project settings and the other by creating a secret. Collapsing them
        produces a refusal nobody can act on — and this is the commoner of the two,
        because it is what deleting a secret leaves behind.
        """
        have = await self.existing_names(project_id)
        return sorted(set(names) - have)

    # --- writes ---------------------------------------------------------------

    def _check_name(self, name: str) -> None:
        if not _NAME.match(name or "") or len(name) > 128:
            raise ApiError(
                "SECRET_NAME_INVALID",
                "A secret name must be upper-case letters, digits and underscores, "
                "starting with a letter — it becomes an environment variable",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        if name in RESERVED_NAMES:
            raise ApiError(
                "SECRET_NAME_RESERVED",
                f"'{name}' would replace part of the execution environment rather than add to it",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                details={"name": name},
            )
        for prefix in RESERVED_PREFIXES:
            if name.startswith(prefix):
                raise ApiError(
                    "SECRET_NAME_RESERVED",
                    f"The '{prefix}' prefix is reserved by the platform",
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    details={"name": name, "prefix": prefix},
                )

    def _check_kind(self, kind: str) -> None:
        if kind not in KINDS:
            raise ApiError(
                "SECRET_KIND_INVALID",
                f"Unknown secret kind '{kind}'",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        if kind in GIT_KINDS and not self._settings.git_secret_delivery_enabled:
            # Refusing to store it rather than storing something that will never be
            # used: a credential the platform holds and never delivers is a setting
            # that looks finished and is not — the same judgement that declined to
            # pre-create an authorization table that authorised nothing.
            raise ApiError(
                "GIT_SECRET_DELIVERY_DISABLED",
                "This deployment does not deliver git credentials from the platform "
                "(CLIORA_GIT_SECRET_DELIVERY_ENABLED is off). At this stage git "
                "authentication is configured on the node by its owner",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                details={"kind": kind, "setting": "CLIORA_GIT_SECRET_DELIVERY_ENABLED"},
            )

    async def create(
        self, *, project: Project, name: str, kind: str, value: str, actor_id: uuid.UUID
    ) -> ProjectSecret:
        self._check_name(name)
        self._check_kind(kind)
        if name in await self.existing_names(project.id):
            raise ApiError(
                "SECRET_EXISTS",
                f"'{name}' already exists in this project — rotate it instead",
                status.HTTP_409_CONFLICT,
                details={"name": name},
            )
        sealed = self._seal(value)
        secret = ProjectSecret(
            id=uuid.uuid4(),
            project_id=project.id,
            name=name,
            kind=kind,
            value_encrypted=sealed.value_encrypted,
            value_nonce=sealed.value_nonce,
            dek_wrapped=sealed.dek_wrapped,
            dek_nonce=sealed.dek_nonce,
            key_version=sealed.key_version,
            created_by=actor_id,
        )
        self._session.add(secret)
        await self._session.flush()
        await self._audit.record(
            audit_actions.SECRET_CREATE,
            user_id=actor_id,
            metadata={
                "project_id": str(project.id),
                "secret_id": str(secret.id),
                # The name is not the secret. The value never appears in an audit row,
                # and neither does its length.
                "name": name,
                "kind": kind,
            },
        )
        return secret

    async def rotate(
        self, *, project: Project, secret: ProjectSecret, value: str, actor_id: uuid.UUID
    ) -> ProjectSecret:
        """Overwrite the value. **Name and kind are immutable.**

        Changing a kind would retroactively alter where an already-delivered value was
        allowed to go, and changing a name would silently orphan every card pointing at
        the old one — which is a rename dressed up as an edit.
        """
        sealed = self._seal(value)
        secret.value_encrypted = sealed.value_encrypted
        secret.value_nonce = sealed.value_nonce
        secret.dek_wrapped = sealed.dek_wrapped
        secret.dek_nonce = sealed.dek_nonce
        secret.key_version = sealed.key_version
        secret.rotated_at = now_utc()
        await self._session.flush()
        await self._audit.record(
            audit_actions.SECRET_ROTATE,
            user_id=actor_id,
            metadata={
                "project_id": str(project.id),
                "secret_id": str(secret.id),
                "name": secret.name,
                "kind": secret.kind,
            },
        )
        return secret

    async def delete(self, *, project: Project, secret: ProjectSecret, actor_id: uuid.UUID) -> None:
        """Soft delete, effective at the next claim.

        A run in flight is unaffected — the value is already in that machine's memory
        and the platform cannot recall it, which is why the console says so rather than
        implying otherwise.
        """
        used_by = await self._session.execute(
            select(ProjectRepository.host, ProjectRepository.path).where(
                (ProjectRepository.credential_secret_id == secret.id)
                | (ProjectRepository.provider_token_secret_id == secret.id)
            )
        )
        repositories = [f"{host}{path}" for host, path in used_by.all()]
        if repositories:
            raise ApiError(
                "SECRET_IN_USE",
                "This secret authenticates a registered repository: " + ", ".join(repositories),
                status.HTTP_409_CONFLICT,
                details={"repositories": repositories},
            )
        secret.deleted_at = now_utc()
        await self._session.flush()
        await self._audit.record(
            audit_actions.SECRET_DELETE,
            user_id=actor_id,
            metadata={
                "project_id": str(project.id),
                "secret_id": str(secret.id),
                "name": secret.name,
                "kind": secret.kind,
            },
        )

    def _seal(self, value: str) -> secret_envelope.SealedSecret:
        try:
            return secret_envelope.seal(value)
        except secret_envelope.MasterKeyMissing as exc:
            # Unreachable when the flag is on, because the settings validator refuses to
            # start without a key. Kept so that a deployment which somehow gets here is
            # told what is wrong rather than shown a 500.
            raise ApiError(
                "SECRET_KEY_MISSING", str(exc), status.HTTP_503_SERVICE_UNAVAILABLE
            ) from exc
        except ValueError as exc:
            raise ApiError(
                "SECRET_TOO_LARGE",
                f"A secret may be at most {secret_envelope.MAX_PLAINTEXT_BYTES} bytes",
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                details={"limit_bytes": secret_envelope.MAX_PLAINTEXT_BYTES},
            ) from exc

    # --- the one way out ------------------------------------------------------

    async def materialise(
        self,
        *,
        project_id: uuid.UUID,
        names: list[str],
        run_id: uuid.UUID,
        runner_id: uuid.UUID,
    ) -> list[MaterialisedSecret]:
        """Decrypt the secrets a card declared, for one offer frame.

        **The only path back to plaintext, and its only caller is the claim.** The audit
        row and `last_used_at` are written here rather than by the caller, in the same
        flush, because a delivery with no record is exactly the gap the compensating
        controls exist to close.

        Silently skips what it cannot deliver rather than failing the claim:

        * a kind this phase never delivers (`provider_token`);
        * a git kind while `CLIORA_GIT_SECRET_DELIVERY_ENABLED` is off.

        Both are already refused at creation, so reaching them means the flag was turned
        off after a secret was stored — and failing a run for a stale configuration
        would be a worse answer than running without a value the card may not use.
        """
        if not names:
            return []
        rows = await self._session.execute(
            select(ProjectSecret).where(
                ProjectSecret.project_id == project_id,
                ProjectSecret.name.in_(names),
                ProjectSecret.deleted_at.is_(None),
            )
        )
        delivered: list[MaterialisedSecret] = []
        stamped = now_utc()
        for secret in rows.scalars():
            if secret.kind in UNDELIVERABLE_KINDS:
                continue
            if secret.kind in GIT_KINDS and not self._settings.git_secret_delivery_enabled:
                continue
            sealed = secret_envelope.SealedSecret(
                value_encrypted=secret.value_encrypted,
                value_nonce=secret.value_nonce,
                dek_wrapped=secret.dek_wrapped,
                dek_nonce=secret.dek_nonce,
                key_version=secret.key_version,
            )
            delivered.append(
                MaterialisedSecret(
                    name=secret.name, kind=secret.kind, value=secret_envelope.unseal(sealed)
                )
            )
            secret.last_used_at = stamped
        if delivered:
            await self._audit.record(
                audit_actions.SECRET_DELIVER,
                user_id=None,
                metadata={
                    "project_id": str(project_id),
                    "run_id": str(run_id),
                    "runner_id": str(runner_id),
                    # Names, and nothing else. No value, no length, no fingerprint.
                    "secret_names": sorted(item.name for item in delivered),
                    "key_version": secret_envelope.CURRENT_KEY_VERSION,
                },
            )
        await self._session.flush()
        return delivered


def validate_allowlist(names: Any) -> list[str]:
    """A project's allowlist, as a list of well-formed names.

    Shared by the project update path and the card editor so that "which names may a
    card declare" has one answer.
    """
    if not isinstance(names, list) or not all(isinstance(item, str) for item in names):
        raise ApiError(
            "INVALID_ARGUMENT",
            "allowed_secret_names must be a list of names",
            status.HTTP_400_BAD_REQUEST,
        )
    cleaned = sorted({item.strip() for item in names if item.strip()})
    invalid = [item for item in cleaned if not _NAME.match(item)]
    if invalid:
        raise ApiError(
            "SECRET_NAME_INVALID",
            "These are not valid secret names: " + ", ".join(invalid),
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            details={"invalid": invalid},
        )
    return cleaned
