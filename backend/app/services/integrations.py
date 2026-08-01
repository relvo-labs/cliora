"""Port-forwarding integration settings and credential custody (P11, FR-TUNNEL-004, ADR 0022).

This service holds the one reversible secret in the system: the tunnel provider's token. Every
other secret here is hashed (passwords, enrollment tokens, node credentials, tunnel basic-auth
passwords) because nothing needs to read them back. This one has to be *used*, so it is
encrypted — and that difference is why the handling is written out rather than assumed:

* **No key, no storage.** With `CLIORA_SECRET_ENCRYPTION_KEY` unset, enabling the integration
  and setting a credential are both refused (`SECRET_KEY_MISSING`). Storing plaintext "until
  the key is set up" cannot be undone: what was written stays written.
* **Write-only.** Nothing here returns the token or any part of it. The read model carries
  `configured` and an eight-character fingerprint, which answers "is this the token I rotated
  last week" and nothing else.
* **One decryption site.** `credential_for_open` is the only path that produces plaintext, for
  the one caller that assembles a `tunnel.open` frame. It is not cached, not logged, and not
  stored on a dataclass.

Disable is deliberately *not* a kill switch for live tunnels. Closing them means a
`tunnel.close` to every node, some of which are offline — an action that can partly fail must
not be dressed up as a switch. Disabling stops new tunnels; closing existing ones is a
separate, reportable action (see `TunnelService`).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.clock import now_utc
from app.db.models import NodeTunnelSettings, TunnelIntegration, User
from app.logging import get_logger
from app.repositories.integrations import IntegrationRepository
from app.security import secret_box
from app.services import audit
from app.services.audit import AuditService
from app.settings import Settings, get_settings

log = get_logger("cliora.integrations")

PROVIDER_PINGGY = "pinggy"
PLAN_FREE = "free"
PLAN_PRO = "pro"
PROTECTIONS = frozenset({"basic", "ipallow", "public"})
# Bounds mirrored from the CHECK constraints in migration 0015. Duplicated on purpose: the
# database refuses a bad value, and this turns the refusal into a message a person can act on
# instead of a 500 from a constraint name.
BUDGET_MIN, BUDGET_MAX = 1, 100
TTL_MIN, TTL_MAX = 60, 86400


@dataclass(frozen=True, slots=True)
class CredentialView:
    """What an interface may know about the stored credential: that it exists, and which one."""

    configured: bool
    fingerprint: str | None
    updated_at: datetime | None
    updated_by: uuid.UUID | None


@dataclass(frozen=True, slots=True)
class IntegrationView:
    enabled: bool
    provider: str
    plan_tier: str
    credential: CredentialView
    concurrent_budget: int
    default_protection: str
    default_ttl_seconds: int
    allowed_ports: list[str] | None
    acknowledged_at: datetime | None
    # Reported so the settings page can say "this environment cannot store credentials"
    # before an administrator types one, rather than after pressing save.
    secret_key_available: bool


def _view(row: TunnelIntegration | None, *, settings: Settings) -> IntegrationView:
    available = secret_box.is_available()
    if row is None:
        # Absent means "never configured". Rendered as a disabled default rather than created,
        # because a read must not leave a trace that looks like a decision.
        return IntegrationView(
            enabled=False,
            provider=PROVIDER_PINGGY,
            plan_tier=PLAN_FREE,
            credential=CredentialView(False, None, None, None),
            concurrent_budget=8,
            default_protection="basic",
            default_ttl_seconds=min(4 * 3600, settings.tunnel_max_ttl_seconds),
            allowed_ports=None,
            acknowledged_at=None,
            secret_key_available=available,
        )
    return IntegrationView(
        enabled=row.enabled,
        provider=row.provider,
        plan_tier=row.plan_tier,
        credential=CredentialView(
            configured=row.token_ciphertext is not None,
            fingerprint=row.token_fingerprint,
            updated_at=row.updated_at,
            updated_by=row.updated_by,
        ),
        concurrent_budget=row.concurrent_budget,
        default_protection=row.default_protection,
        default_ttl_seconds=row.default_ttl_seconds,
        allowed_ports=list(row.allowed_ports or []) or None,
        acknowledged_at=row.acknowledged_at,
        secret_key_available=available,
    )


class IntegrationService:
    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self._session = session
        self._repo = IntegrationRepository(session)
        self._audit = AuditService(session)
        self._settings = settings or get_settings()

    # --- read -------------------------------------------------------------------------

    async def view(self) -> IntegrationView:
        return _view(await self._repo.get_integration(), settings=self._settings)

    async def is_enabled(self) -> bool:
        row = await self._repo.get_integration()
        return row is not None and row.enabled

    async def row(self) -> TunnelIntegration | None:
        return await self._repo.get_integration()

    # --- write ------------------------------------------------------------------------

    async def set_credential(
        self, actor: User, token: str, plan_tier: str | None = None
    ) -> IntegrationView:
        """Store or replace the provider credential.

        The character set is validated here as well as on the wire, because this is where a
        value first enters the system: the credential is later concatenated into ssh's
        `<token>@<host>` argument, where `+` selects a tunnel type and `@` selects the host.
        """
        self._require_secret_key()
        cleaned = token.strip()
        if not _valid_credential(cleaned):
            raise ApiError(
                "INVALID_ARGUMENT",
                "A provider token is 8-128 letters and digits. Copy it from the provider's "
                "dashboard without any surrounding text.",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        if plan_tier is not None and plan_tier not in (PLAN_FREE, PLAN_PRO):
            raise ApiError(
                "INVALID_ARGUMENT", "Unknown plan tier", status.HTTP_422_UNPROCESSABLE_ENTITY
            )

        row = await self._repo.get_or_create_integration(actor_id=actor.id)
        replaced = row.token_ciphertext is not None
        ciphertext, nonce = secret_box.encrypt(cleaned)
        row.token_ciphertext = ciphertext
        row.token_nonce = nonce
        row.token_fingerprint = secret_box.fingerprint(cleaned)
        if plan_tier is not None:
            row.plan_tier = plan_tier
        row.updated_at = now_utc()
        row.updated_by = actor.id
        await self._audit.record(
            audit.INTEGRATION_CREDENTIAL_SET,
            user_id=actor.id,
            metadata={
                "provider": row.provider,
                "plan_tier": row.plan_tier,
                # The fingerprint, never the token. It is what lets a later investigation say
                # which credential a given tunnel was opened with.
                "fingerprint": row.token_fingerprint,
                "replaced": replaced,
            },
        )
        return _view(row, settings=self._settings)

    async def clear_credential(self, actor: User) -> IntegrationView:
        row = await self._repo.get_or_create_integration(actor_id=actor.id)
        row.token_ciphertext = None
        row.token_nonce = None
        row.token_fingerprint = None
        # A Pro tier with no credential is a combination that can only fail, and it would fail
        # at the point a user tries to open a tunnel rather than here.
        if row.plan_tier == PLAN_PRO:
            row.plan_tier = PLAN_FREE
        row.updated_at = now_utc()
        row.updated_by = actor.id
        await self._audit.record(
            audit.INTEGRATION_CREDENTIAL_SET,
            user_id=actor.id,
            metadata={"provider": row.provider, "plan_tier": row.plan_tier, "cleared": True},
        )
        return _view(row, settings=self._settings)

    async def update(
        self,
        actor: User,
        *,
        enabled: bool | None = None,
        plan_tier: str | None = None,
        concurrent_budget: int | None = None,
        default_protection: str | None = None,
        default_ttl_seconds: int | None = None,
        allowed_ports: list[str] | None = None,
        clear_allowed_ports: bool = False,
        acknowledge: bool = False,
    ) -> IntegrationView:
        row = await self._repo.get_or_create_integration(actor_id=actor.id)

        if plan_tier is not None:
            if plan_tier not in (PLAN_FREE, PLAN_PRO):
                raise ApiError(
                    "INVALID_ARGUMENT", "Unknown plan tier", status.HTTP_422_UNPROCESSABLE_ENTITY
                )
            if plan_tier == PLAN_PRO and row.token_ciphertext is None:
                raise ApiError(
                    "INVALID_ARGUMENT",
                    "Set the provider credential before selecting the paid tier: without one "
                    "the provider issues an anonymous, time-limited tunnel instead.",
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                )
            row.plan_tier = plan_tier

        if concurrent_budget is not None:
            if not BUDGET_MIN <= concurrent_budget <= BUDGET_MAX:
                raise ApiError(
                    "INVALID_ARGUMENT",
                    f"The concurrent budget must be between {BUDGET_MIN} and {BUDGET_MAX}.",
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                )
            row.concurrent_budget = concurrent_budget

        if default_protection is not None:
            if default_protection not in PROTECTIONS:
                raise ApiError(
                    "INVALID_ARGUMENT",
                    "Protection must be one of: basic, ipallow, public.",
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                )
            row.default_protection = default_protection

        if default_ttl_seconds is not None:
            ceiling = min(TTL_MAX, self._settings.tunnel_max_ttl_seconds)
            if not TTL_MIN <= default_ttl_seconds <= ceiling:
                raise ApiError(
                    "INVALID_ARGUMENT",
                    f"The default lifetime must be between {TTL_MIN} and {ceiling} seconds.",
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                )
            row.default_ttl_seconds = default_ttl_seconds

        if clear_allowed_ports:
            # NULL, not an empty list: "the platform does not narrow" and "the platform
            # forbids every port" are opposite settings (see `_validated_ports`).
            row.allowed_ports = None
        elif allowed_ports is not None:
            row.allowed_ports = _validated_ports(allowed_ports)

        if acknowledge and row.acknowledged_at is None:
            row.acknowledged_at = now_utc()
            row.acknowledged_by = actor.id

        if enabled is not None and enabled != row.enabled:
            if enabled:
                self._require_secret_key()
                if row.acknowledged_at is None:
                    # The acknowledgement is a person accepting that traffic leaves for a third
                    # party. Refusing here rather than defaulting it is the whole point.
                    raise ApiError(
                        "INVALID_ARGUMENT",
                        "Confirm that forwarded traffic passes through the provider before "
                        "enabling port forwarding.",
                        status.HTTP_422_UNPROCESSABLE_ENTITY,
                    )
                if row.plan_tier == PLAN_PRO and row.token_ciphertext is None:
                    raise ApiError(
                        "INVALID_ARGUMENT",
                        "Set the provider credential before enabling the paid tier.",
                        status.HTTP_422_UNPROCESSABLE_ENTITY,
                    )
            row.enabled = enabled
            await self._audit.record(
                audit.INTEGRATION_ENABLE if enabled else audit.INTEGRATION_DISABLE,
                user_id=actor.id,
                metadata={"provider": row.provider, "plan_tier": row.plan_tier},
            )

        row.updated_at = now_utc()
        row.updated_by = actor.id
        return _view(row, settings=self._settings)

    async def update_node_settings(
        self,
        actor: User,
        node_id: uuid.UUID,
        *,
        enabled: bool | None = None,
        allowed_ports: list[str] | None = None,
        max_tunnels: int | None = None,
        clear_allowed_ports: bool = False,
        clear_max_tunnels: bool = False,
    ) -> NodeTunnelSettings:
        row = await self._repo.get_or_create_node_settings(node_id, actor_id=actor.id)
        if enabled is not None:
            row.enabled = enabled
        if clear_allowed_ports:
            row.allowed_ports = None
        elif allowed_ports is not None:
            row.allowed_ports = _validated_ports(allowed_ports)
        if clear_max_tunnels:
            row.max_tunnels = None
        elif max_tunnels is not None:
            if not BUDGET_MIN <= max_tunnels <= BUDGET_MAX:
                raise ApiError(
                    "INVALID_ARGUMENT",
                    f"A node's cap must be between {BUDGET_MIN} and {BUDGET_MAX}.",
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                )
            row.max_tunnels = max_tunnels
        row.updated_at = now_utc()
        row.updated_by = actor.id
        await self._audit.record(
            audit.INTEGRATION_NODE_SETTINGS_UPDATED,
            user_id=actor.id,
            node_id=node_id,
            metadata={
                "enabled": row.enabled,
                "allowed_ports": list(row.allowed_ports or []) or None,
                "max_tunnels": row.max_tunnels,
            },
        )
        return row

    # --- the one decryption site --------------------------------------------------------

    async def credential_for_open(self) -> str | None:
        """The provider credential in plaintext, for assembling one `tunnel.open`.

        Returns None on the free tier, where there is no credential and the provider issues an
        anonymous tunnel. The caller uses the value immediately and keeps no copy.
        """
        row = await self._repo.get_integration()
        if row is None or row.token_ciphertext is None or row.token_nonce is None:
            return None
        try:
            return secret_box.decrypt(row.token_ciphertext, row.token_nonce)
        except secret_box.SecretKeyMissing as exc:
            raise ApiError(
                "SECRET_KEY_MISSING",
                "This deployment cannot read the stored provider credential.",
                status.HTTP_503_SERVICE_UNAVAILABLE,
            ) from exc
        except secret_box.SecretDecryptionFailed as exc:
            # The key changed, or the row was tampered with. Either way the credential has to
            # be entered again — there is nothing to recover, and saying so beats a 500.
            log.warning(
                "integration_credential_undecryptable",
                extra={"event": "integration_credential_undecryptable"},
            )
            raise ApiError(
                "TUNNEL_PROVIDER_UNAUTHORIZED",
                "The stored provider credential could not be read. Ask an administrator to "
                "enter it again.",
                status.HTTP_502_BAD_GATEWAY,
            ) from exc

    def _require_secret_key(self) -> None:
        if not secret_box.is_available():
            raise ApiError(
                "SECRET_KEY_MISSING",
                "This deployment has no credential encryption key, so a provider credential "
                "cannot be stored.",
                status.HTTP_503_SERVICE_UNAVAILABLE,
            )


def _valid_credential(value: str) -> bool:
    return 8 <= len(value) <= 128 and value.isascii() and value.isalnum()


def _validated_ports(specs: list[str]) -> list[str]:
    """Validate port specs ("5173", "3000-3999") for storage.

    An empty list is kept as an empty list rather than turned into NULL: "forbid everything"
    and "do not narrow" are different settings, and collapsing them would silently widen one
    of them.
    """
    if len(specs) > 64:
        raise ApiError(
            "INVALID_ARGUMENT",
            "Too many port ranges (64 max).",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    cleaned: list[str] = []
    for spec in specs:
        text = spec.strip()
        low, _, high = text.partition("-")
        try:
            start = int(low)
            end = int(high) if high else start
        except ValueError as exc:
            raise ApiError(
                "INVALID_ARGUMENT",
                f"'{spec}' is not a port or a range like 3000-3999.",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
            ) from exc
        if start < 1024:
            raise ApiError(
                "TUNNEL_PORT_NOT_ALLOWED",
                "Ports below 1024 are never forwarded.",
                status.HTTP_409_CONFLICT,
            )
        if end > 65535 or end < start:
            raise ApiError(
                "INVALID_ARGUMENT",
                f"'{spec}' is not a valid port range.",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        cleaned.append(text)
    return cleaned
