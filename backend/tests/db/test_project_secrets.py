"""The secret store: what it stores, what it refuses, and what it never gives back.

FR-RUNENV-001/002, ADR 0032. The two assertions worth reading first are in
`test_no_endpoint_returns_a_value`, because they guard different mistakes: the schema
scan catches a *future* endpoint that hands back a whole row, and the sentinel scan
catches a present one whose schema is right and whose implementation is not.
"""

from __future__ import annotations

import base64
import json
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from app.db.models import ProjectSecret, Role, User
from app.security import secret_envelope
from app.security.passwords import hash_password
from app.settings import Settings

pytestmark = pytest.mark.asyncio


async def _actor(client: AsyncClient, maker, role_name: str = "Admin") -> dict[str, str]:
    """Same shape as `test_agent_api._actor`: a real role row, a real login."""
    async with maker() as session:
        role = (await session.execute(select(Role).where(Role.name == role_name))).scalar_one()
        username = f"{role_name.lower()}-{uuid.uuid4().hex[:8]}"
        session.add(
            User(
                id=uuid.uuid4(),
                username=username,
                display_name=username,
                password_hash=hash_password("pw"),
                role_id=role.id,
            )
        )
        await session.commit()
    tokens = await client.post("/api/auth/login", json={"username": username, "password": "pw"})
    return {"authorization": f"Bearer {tokens.json()['tokens']['access_token']}"}


async def _admin(client: AsyncClient, maker) -> dict[str, str]:
    return await _actor(client, maker)


async def _project(client: AsyncClient, headers: dict[str, str]) -> str:
    slug = f"p-{uuid.uuid4().hex[:8]}"
    response = await client.post(
        "/api/projects", headers=headers, json={"name": slug, "slug": slug}
    )
    assert response.status_code in (200, 201), response.text
    return response.json()["id"]


@pytest.mark.usefixtures("projects_enabled")
async def test_creates_and_lists_without_ever_returning_the_value(api) -> None:
    client, maker = api
    headers = await _admin(client, maker)
    project = await _project(client, headers)

    created = await client.post(
        f"/api/projects/{project}/secrets",
        headers=headers,
        json={"name": "NPM_TOKEN", "kind": "env", "value": "sentinel-value-01"},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["name"] == "NPM_TOKEN"
    assert "value" not in body
    assert body["last_used_at"] is None

    listed = await client.get(f"/api/projects/{project}/secrets", headers=headers)
    assert listed.status_code == 200
    assert [row["name"] for row in listed.json()] == ["NPM_TOKEN"]
    assert all("value" not in row for row in listed.json())


@pytest.mark.usefixtures("projects_enabled")
async def test_no_endpoint_returns_a_value(api) -> None:
    """The two halves of exit condition 1.

    The **schema** half scans every response in the whole document, not just this
    module's: the endpoint most likely to leak a value is not the one being watched, it
    is a future route that hands back a whole row.

    The **sentinel** half reads the raw bytes of five responses. A schema can be right
    while an implementation serialises a model directly, and only one of these two
    catches that.
    """
    client, maker = api
    headers = await _admin(client, maker)
    project = await _project(client, headers)
    sentinel = f"sentinel-{uuid.uuid4().hex}"
    await client.post(
        f"/api/projects/{project}/secrets",
        headers=headers,
        json={"name": "GITHUB_TOKEN", "kind": "env", "value": sentinel},
    )

    forbidden = {"value", "value_encrypted", "dek_wrapped", "plaintext", "secret_value"}
    spec = (await client.get("/openapi.json")).json()
    schemas = spec.get("components", {}).get("schemas", {})

    # **Responses only.** A first version of this walked every schema in the document
    # and failed on `CreateProjectSecretRequest`, which of course carries a value — that
    # is the request that stores one. A guard that cannot tell a request from a response
    # would have been "fixed" by renaming the field somebody has to type, which is worse
    # than having no guard.
    def refs(node: object) -> set[str]:
        found: set[str] = set()
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
                found.add(ref.rsplit("/", 1)[-1])
            for child in node.values():
                found |= refs(child)
        elif isinstance(node, list):
            for child in node:
                found |= refs(child)
        return found

    reachable: set[str] = set()
    for operations in spec.get("paths", {}).values():
        for operation in operations.values():
            if isinstance(operation, dict):
                reachable |= refs(operation.get("responses", {}))
    # Transitively: a response schema that nests another one.
    frontier = set(reachable)
    while frontier:
        nxt = set()
        for name in frontier:
            for candidate in refs(schemas.get(name, {})) - reachable:
                reachable.add(candidate)
                nxt.add(candidate)
        frontier = nxt

    leaked = {
        f"{name}.{field}"
        for name in reachable
        for field in forbidden & set(schemas.get(name, {}).get("properties") or {})
    }
    assert not leaked, f"a response schema exposes {sorted(leaked)}"
    # And the guard is not vacuous: it did reach the DTO this module returns.
    assert "ProjectSecretDTO" in reachable

    for path in (
        f"/api/projects/{project}/secrets",
        f"/api/projects/{project}",
        "/api/projects",
        "/api/audit",
        "/api/agents",
    ):
        response = await client.get(path, headers=headers)
        assert sentinel.encode() not in response.content, f"{path} echoed the value"


@pytest.mark.usefixtures("projects_enabled")
async def test_two_secrets_with_the_same_value_are_different_bytes(api) -> None:
    """A fresh data key per row, so "these two projects share a token" is unreadable."""
    client, maker = api
    headers = await _admin(client, maker)
    project = await _project(client, headers)
    for name in ("ONE_TOKEN", "TWO_TOKEN"):
        await client.post(
            f"/api/projects/{project}/secrets",
            headers=headers,
            json={"name": name, "kind": "env", "value": "identical"},
        )
    async with maker() as session:
        rows = list((await session.execute(select(ProjectSecret))).scalars())
    assert len(rows) == 2
    assert rows[0].value_encrypted != rows[1].value_encrypted
    assert rows[0].dek_wrapped != rows[1].dek_wrapped


@pytest.mark.usefixtures("projects_enabled")
async def test_rotating_the_master_key_rewraps_the_dek_and_leaves_the_ciphertext(
    monkeypatch,
) -> None:
    """Exit condition 1c, and the property the KMS upgrade path rests on.

    Not an API test: rotation is an operator procedure, and what has to be true is a
    property of the envelope rather than of a route.
    """
    from app.settings import get_settings

    key_v1 = base64.b64encode(b"\x01" * 32).decode()
    key_v2 = base64.b64encode(b"\x02" * 32).decode()
    monkeypatch.setattr(secret_envelope, "get_settings", lambda: Settings(secret_master_key=key_v1))
    sealed = secret_envelope.seal("a-real-looking-token")
    assert secret_envelope.unseal(sealed) == "a-real-looking-token"

    # The old key stays reachable under its versioned name; the current one moves on.
    monkeypatch.setenv("CLIORA_SECRET_MASTER_KEY_V1", key_v1)
    monkeypatch.setattr(
        secret_envelope,
        "get_settings",
        lambda: Settings(secret_master_key=key_v2, secret_master_key_version=2),
    )
    rewrapped = secret_envelope.rewrap(sealed, to_version=2)

    assert rewrapped.value_encrypted == sealed.value_encrypted
    assert rewrapped.value_nonce == sealed.value_nonce
    assert rewrapped.dek_wrapped != sealed.dek_wrapped
    assert secret_envelope.unseal(rewrapped) == "a-real-looking-token"
    # And the pre-rotation row still opens, because its key is still in the environment.
    assert secret_envelope.unseal(sealed) == "a-real-looking-token"

    get_settings.cache_clear()


async def test_a_missing_old_key_names_the_version(monkeypatch) -> None:
    """ "Could not decrypt" sends an operator looking for corruption; this does not."""
    key = base64.b64encode(b"\x03" * 32).decode()
    monkeypatch.setattr(secret_envelope, "get_settings", lambda: Settings(secret_master_key=key))
    sealed = secret_envelope.seal("token")
    stale = secret_envelope.SealedSecret(
        value_encrypted=sealed.value_encrypted,
        value_nonce=sealed.value_nonce,
        dek_wrapped=sealed.dek_wrapped,
        dek_nonce=sealed.dek_nonce,
        key_version=7,
    )
    monkeypatch.delenv("CLIORA_SECRET_MASTER_KEY_V7", raising=False)
    with pytest.raises(secret_envelope.SecretDecryptionFailed) as exc:
        secret_envelope.unseal(stale)
    assert "CLIORA_SECRET_MASTER_KEY_V7" in str(exc.value)


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        ("", "is not set"),
        ("dev-only-change-me", "development default"),
        ("not base64 at all !!", "base64"),
        (base64.b64encode(b"short").decode(), "32 bytes"),
    ],
)
def test_master_key_is_required_only_when_the_runner_layer_is_on(raw: str, reason: str) -> None:
    """Exit condition 1b, both directions.

    The flag-off half is the one that matters: an unconditional check would stop every
    deployment that does not use V2 from booting, to protect zero rows.
    """
    with pytest.raises(ValueError) as exc:
        Settings(agent_runs_enabled=True, secret_master_key=raw)
    assert reason in str(exc.value)
    assert Settings(agent_runs_enabled=False, secret_master_key=raw) is not None


@pytest.mark.usefixtures("projects_enabled")
@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("lower_case", "SECRET_NAME_INVALID"),
        ("1LEADING", "SECRET_NAME_INVALID"),
        ("HAS-DASH", "SECRET_NAME_INVALID"),
        ("PATH", "SECRET_NAME_RESERVED"),
        ("LD_PRELOAD", "SECRET_NAME_RESERVED"),
        # Not decorative: a secret called GIT_ASKPASS takes over the credential helper
        # the whole PAT path is built on.
        ("GIT_ASKPASS", "SECRET_NAME_RESERVED"),
        ("CLIORA_ANYTHING", "SECRET_NAME_RESERVED"),
    ],
)
async def test_refuses_a_name_that_would_hijack_the_environment(api, name: str, code: str) -> None:
    client, maker = api
    headers = await _admin(client, maker)
    project = await _project(client, headers)
    response = await client.post(
        f"/api/projects/{project}/secrets",
        headers=headers,
        json={"name": name, "kind": "env", "value": "x"},
    )
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == code


@pytest.mark.usefixtures("projects_enabled")
async def test_git_kinds_are_refused_while_delivery_is_disabled(api) -> None:
    """The default posture (2026-08-13 ruling), and why it is a refusal not a store.

    A credential the platform holds and never delivers is a setting that looks finished
    and is not — the same judgement that declined to pre-create an authorization table
    which authorised nothing.
    """
    client, maker = api
    headers = await _admin(client, maker)
    project = await _project(client, headers)
    refused = await client.post(
        f"/api/projects/{project}/secrets",
        headers=headers,
        json={"name": "DEPLOY_KEY", "kind": "git_ssh_key", "value": "-----BEGIN..."},
    )
    assert refused.status_code == 422, refused.text
    error = refused.json()["error"]
    assert error["code"] == "GIT_SECRET_DELIVERY_DISABLED"
    # The message names the variable, because the fix is one environment variable and
    # not a code change.
    assert "CLIORA_GIT_SECRET_DELIVERY_ENABLED" in json.dumps(error)

    allowed = await client.post(
        f"/api/projects/{project}/secrets",
        headers=headers,
        json={"name": "PLAIN_TOKEN", "kind": "env", "value": "x"},
    )
    assert allowed.status_code == 201


@pytest.mark.usefixtures("projects_enabled")
async def test_delete_is_soft_and_the_name_becomes_free_again(api) -> None:
    """Delete-and-recreate is the commonest recovery there is; a unique violation on it
    would produce a 409 nobody can act on."""
    client, maker = api
    headers = await _admin(client, maker)
    project = await _project(client, headers)
    created = await client.post(
        f"/api/projects/{project}/secrets",
        headers=headers,
        json={"name": "ROTATE_ME", "kind": "env", "value": "one"},
    )
    secret_id = created.json()["id"]

    duplicate = await client.post(
        f"/api/projects/{project}/secrets",
        headers=headers,
        json={"name": "ROTATE_ME", "kind": "env", "value": "two"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "SECRET_EXISTS"

    deleted = await client.delete(f"/api/projects/{project}/secrets/{secret_id}", headers=headers)
    assert deleted.status_code == 204
    again = await client.post(
        f"/api/projects/{project}/secrets",
        headers=headers,
        json={"name": "ROTATE_ME", "kind": "env", "value": "three"},
    )
    assert again.status_code == 201, again.text

    async with maker() as session:
        rows = (
            await session.execute(
                text("SELECT count(*) FROM project_secrets WHERE name = 'ROTATE_ME'")
            )
        ).scalar()
    assert rows == 2, "the soft-deleted row is kept, not overwritten"


@pytest.mark.usefixtures("projects_enabled")
async def test_rotation_replaces_the_value_and_nothing_else(api) -> None:
    client, maker = api
    headers = await _admin(client, maker)
    project = await _project(client, headers)
    created = await client.post(
        f"/api/projects/{project}/secrets",
        headers=headers,
        json={"name": "ROTATED", "kind": "env", "value": "before"},
    )
    secret_id = created.json()["id"]
    async with maker() as session:
        before = (await session.get(ProjectSecret, uuid.UUID(secret_id))).value_encrypted

    rotated = await client.put(
        f"/api/projects/{project}/secrets/{secret_id}",
        headers=headers,
        json={"value": "after"},
    )
    assert rotated.status_code == 200, rotated.text
    assert rotated.json()["rotated_at"] is not None
    assert rotated.json()["kind"] == "env"
    async with maker() as session:
        row = await session.get(ProjectSecret, uuid.UUID(secret_id))
    assert row.value_encrypted != before
    assert row.name == "ROTATED"


@pytest.mark.usefixtures("projects_enabled")
async def test_a_value_larger_than_a_secret_is_refused_and_nothing_is_written(api) -> None:
    client, maker = api
    headers = await _admin(client, maker)
    project = await _project(client, headers)
    response = await client.post(
        f"/api/projects/{project}/secrets",
        headers=headers,
        json={"name": "HUGE", "kind": "env", "value": "x" * 9000},
    )
    assert response.status_code == 422, response.text
    async with maker() as session:
        count = (await session.execute(text("SELECT count(*) FROM project_secrets"))).scalar()
    assert count == 0


@pytest.mark.usefixtures("agent_runs_disabled")
async def test_every_secrets_route_is_absent_while_the_runner_layer_is_off(api) -> None:
    """404, not 403. A 403 confirms the route exists in a deployment that never had it."""
    client, maker = api
    headers = await _admin(client, maker)
    project_id = uuid.uuid4()
    for method, path in (
        ("get", f"/api/projects/{project_id}/secrets"),
        ("get", f"/api/projects/{project_id}/secret-names"),
        ("post", f"/api/projects/{project_id}/secrets"),
        ("put", f"/api/projects/{project_id}/secrets/{uuid.uuid4()}"),
        ("delete", f"/api/projects/{project_id}/secrets/{uuid.uuid4()}"),
    ):
        call = getattr(client, method)
        response = await (
            call(path, headers=headers, json={})
            if method in {"post", "put"}
            else call(path, headers=headers)
        )
        assert response.status_code == 404, f"{method} {path} -> {response.status_code}"
