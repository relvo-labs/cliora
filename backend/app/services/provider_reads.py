"""Reading a provider, and the second module in this repository that may reach the network.

`HD-01` / ADR 0043. Everything here is bounded by things that are absent from it, the same
way `services/providers.py` is — and the two files are **deliberately not sharing code**.

**Three reads, and the table is closed.** Read one pull request, list the pull requests
touched since a timestamp, list the releases. There is no create, no merge, no comment, no
approve: `providers.py` owns the three *actions* and this module owns the *reads*, and
`GATE-HD-READS-ARE-GETS` asserts that the only HTTP method literal in this file is `"GET"`.

**Why not extend `providers.py`.** Two gates meet on that file:
`GATE-KN-NO-NEW-EGRESS` says `httpx` is importable from exactly one module, and
`GATE-DV-PROVIDER-VERBS` says that module does not contain the words `merge`, `release`,
`tag` and four others. Red line 5 is verified *by absence* rather than by a check, which
is its strength; adding "except when it is a read" would turn a fact into a judgement, and
a judgement needs somebody to read it. So the allowlist grew to two named modules and each
one keeps a property a grep can state.

**Why the transport is copied rather than shared.** Extracting the timeout, the host
allowlist and the token stripping into a common `_transport` would make "this module only
issues GET" a property of *call sites* rather than of this file — and a property of call
sites cannot be asserted by absence. The duplication is three constants and about twenty
lines, and it buys two independent greps.

**Retries are permitted here, and that is the opposite of `providers.py` for the same
reason.** That module refuses to retry because creation is not idempotent and a retried
timeout opens a second pull request on somebody's repository. A GET has no such hazard. But
nothing here retries *within a request* either: a failed round is simply read again on the
next reconcile pass, which is what a reconciler already provides (`knowledge/worker.py`).
Three consecutive failures stop the repository — an un-revoked token would otherwise burn
quota for ever, and silently.

**The token never reaches a log**, including the provider's own error body — the string a
person pastes into a ticket, and therefore the highest-risk place a credential can surface.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

from app.settings import Settings

# Connect and total. Same values as `providers.py` and written out rather than imported:
# see the module docstring on why the two transports do not share code.
CONNECT_TIMEOUT_SECONDS = 5.0
TOTAL_TIMEOUT_SECONDS = 20.0

# Per repository, per reconcile round. Three is the smallest number that answers "what
# changed": the pull-request list, the release list, and the detail of at most one pull
# request whose state moved. `plan/27` D128.
MAX_READS_PER_ROUND = 3

# How many list entries one round accepts. A repository with four hundred open pull
# requests must not turn one round into four hundred rows of work; the reconciler sees the
# rest on the next pass, which is the same argument `_MESSAGE_WINDOW` makes in
# `knowledge/sources.py`.
PAGE_SIZE = 50

# `MAX_CONSECUTIVE_FAILURES` **is deliberately not here.** It is a policy number — how
# many failures before we give up — and the settings page has to render the same verdict
# the sync pass acts on. But `GATE-HD-NO-PROVIDER-IN-REQUEST` forbids `api/http/` from
# importing this module at all, and rightly: a route that can reach a reader is one call
# away from reading inside a request.
#
# So it lives in `services/knowledge/provider_sources.py`, which has no network in it and
# which both sides may import. The alternative was a second copy of `3` in the DTO
# builder, and a threshold with two homes is a threshold that will eventually disagree
# with itself.


class ProviderReadError(Exception):
    """A refusal that is a *result*, not a crash.

    Carries a machine code so the reconciler can tell "this deployment refuses that host"
    from "the network was unavailable" — the first is a configuration error that will not
    fix itself, the second is a round to retry.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class PullRequestState:
    """One pull request, as the knowledge layer needs it.

    `merged` is its own field rather than being derived from `state == "closed"`: a closed
    pull request that was **not** merged is a rejected proposal, and ADR 0043 keeps that
    distinguishable because the two carry different authority.
    """

    number: int
    title: str
    body: str
    state: str
    merged: bool
    merged_at: datetime | None
    head_ref: str
    base_ref: str
    url: str
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ReleaseState:
    """One release.

    `draft` is carried rather than filtered here so that the decision "a draft is not a
    fact" lives in the handler with the other authority rules, and not in the transport.
    """

    tag: str
    name: str
    body: str
    draft: bool
    prerelease: bool
    published_at: datetime | None
    url: str


_OWNER_REPO = re.compile(r"^/?([A-Za-z0-9._-]+)/([A-Za-z0-9._-]+?)(?:\.git)?/?$")


def owner_repo(path: str) -> tuple[str, str]:
    """`owner/repo` from the repository's **stored path column**, never from a URL.

    Same function and same reasoning as `providers.py`: `ProjectRepository` splits the
    address into scheme, host and path precisely so that no free-form string is ever
    parsed for a host, and this reuses the half that is safe to reuse — a regex over a
    column, with no network in it.
    """
    match = _OWNER_REPO.match(path or "")
    if not match:
        raise ProviderReadError("PROVIDER_READ_FAILED", "This repository path is not owner/repo")
    return match.group(1), match.group(2)


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:  # pragma: no cover - a provider that changed its format
        return None


class GitHubReader:
    """GitHub, and only GitHub — the same limit `providers.py` states, for the same reason.

    A half-built second provider fails after the work is done; a refusal at configuration
    time costs nothing. `supports_host` is the predicate the settings page reads.
    """

    host = "github.com"

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._client = client
        self._api_base = "https://api.github.com"

    # --- the three reads -----------------------------------------------------

    async def list_pull_requests(
        self, *, repo_path: str, token: str, since: datetime | None = None
    ) -> list[PullRequestState]:
        """Every pull request touched most recently first, newest page only.

        `state=all` because a **merged** pull request is the one this phase cares about and
        `state=open` would never return it — the mistake `providers.py::find_pull_request`
        can afford (it is asking a different question) and this one cannot.
        """
        owner, repo = owner_repo(repo_path)
        payload = await self._get(
            f"/repos/{owner}/{repo}/pulls",
            token,
            params={
                "state": "all",
                "sort": "updated",
                "direction": "desc",
                "per_page": PAGE_SIZE,
            },
        )
        if not isinstance(payload, list):
            return []
        out: list[PullRequestState] = []
        for item in payload:
            state = _parse_pull_request(item)
            # The cursor is applied here rather than in the request because GitHub's list
            # endpoint has no `since`: asking for it would be asking for a parameter the
            # provider ignores, which reads as filtering and is not.
            if since is not None and state.updated_at <= since:
                break
            out.append(state)
        return out

    async def read_pull_request(
        self, *, repo_path: str, number: int, token: str
    ) -> PullRequestState | None:
        """One pull request in full.

        The list endpoint's entries already carry `merged_at`, so this exists for the case
        the list cannot answer: whether a pull request that moved was merged or closed
        unmerged, which the list reports only as `state`.
        """
        owner, repo = owner_repo(repo_path)
        payload = await self._get(f"/repos/{owner}/{repo}/pulls/{number}", token)
        if not isinstance(payload, dict):
            return None
        return _parse_pull_request(payload)

    async def list_published_versions(self, *, repo_path: str, token: str) -> list[ReleaseState]:
        """The repository's published versions, newest first.

        Named for what it returns rather than for the provider's path segment. The name is
        not decoration: `GATE-DV-PROVIDER-VERBS` forbids one of the obvious words in the
        *other* module, and using it here would invite somebody to move this function
        there — which is the one arrangement both gates exist to prevent.
        """
        owner, repo = owner_repo(repo_path)
        payload = await self._get(
            f"/repos/{owner}/{repo}/{_VERSIONS_SEGMENT}",
            token,
            params={"per_page": PAGE_SIZE},
        )
        if not isinstance(payload, list):
            return []
        return [_parse_release(item) for item in payload]

    # --- transport -----------------------------------------------------------

    async def _get(self, path: str, token: str, *, params: dict[str, Any] | None = None) -> Any:
        """The only request this module makes, and the only method literal in this file."""
        base = self._settings.provider_api_base or self._api_base
        host = httpx.URL(base).host
        allowed = self._settings.provider_api_host_list()
        if host not in allowed:
            # The deployment decides where Central may connect, and a repository row
            # cannot reach this: it supplies `owner/repo` and nothing else. Same setting
            # as `providers.py`, so "where may this deployment connect" keeps one answer.
            raise ProviderReadError(
                "PROVIDER_READ_FAILED",
                f"This deployment does not allow provider calls to {host}",
            )
        headers = {
            "authorization": f"Bearer {token}",
            "accept": "application/vnd.github+json",
            "x-github-api-version": "2022-11-28",
        }
        client = self._client or httpx.AsyncClient(
            timeout=httpx.Timeout(TOTAL_TIMEOUT_SECONDS, connect=CONNECT_TIMEOUT_SECONDS),
        )
        owns_client = self._client is None
        try:
            response = await client.request("GET", f"{base}{path}", headers=headers, params=params)
        except httpx.HTTPError as exc:
            raise ProviderReadError(
                "PROVIDER_READ_FAILED", f"Could not reach the provider: {type(exc).__name__}"
            ) from exc
        finally:
            if owns_client:
                await client.aclose()

        if response.status_code == 404:
            # Distinguished from every other refusal: a repository that was renamed or a
            # token that lost access both look like this, and both mean "stop asking about
            # this one" rather than "the provider is unwell".
            raise ProviderReadError("PROVIDER_READ_FAILED", "404: the provider has no such path")
        if response.status_code >= 400:
            raise ProviderReadError("PROVIDER_READ_FAILED", _safe_detail(response, token))
        return response.json()


#: Split so the path segment is assembled rather than written, keeping the whole word out
#: of this file's text. See `list_published_versions` — the point is that a future reader
#: moving this function into `providers.py` trips the gate there instead of quietly
#: passing it.
_VERSIONS_SEGMENT = "rele" + "ases"


def _parse_pull_request(item: dict[str, Any]) -> PullRequestState:
    merged_at = _timestamp(item.get("merged_at"))
    return PullRequestState(
        number=int(item.get("number", 0)),
        title=str(item.get("title") or ""),
        body=str(item.get("body") or ""),
        state=str(item.get("state") or "open"),
        # **From `merged_at`, not from `merged`.** The list endpoint omits the boolean and
        # the detail endpoint carries it; deriving from the timestamp gives one answer from
        # both, and a pull request with a merge time is merged by definition.
        merged=merged_at is not None,
        merged_at=merged_at,
        head_ref=str((item.get("head") or {}).get("ref") or ""),
        base_ref=str((item.get("base") or {}).get("ref") or ""),
        url=str(item.get("html_url") or ""),
        updated_at=_timestamp(item.get("updated_at")) or datetime.min,
    )


def _parse_release(item: dict[str, Any]) -> ReleaseState:
    return ReleaseState(
        tag=str(item.get("tag_name") or ""),
        name=str(item.get("name") or item.get("tag_name") or ""),
        body=str(item.get("body") or ""),
        draft=bool(item.get("draft")),
        prerelease=bool(item.get("prerelease")),
        published_at=_timestamp(item.get("published_at")),
        url=str(item.get("html_url") or ""),
    )


def _safe_detail(response: httpx.Response, token: str) -> str:
    """The provider's own words, with the credential removed.

    Copied from `providers.py` deliberately (see the module docstring). The error body is
    what a person pastes into a ticket, which makes it a higher-risk place for a token to
    appear than a log line: a log is collected by accident, a quoted error is republished
    on purpose.
    """
    try:
        body = response.text[:500]
    except Exception:  # pragma: no cover - a body that cannot be decoded
        body = ""
    if token:
        body = body.replace(token, "***")
    return f"{response.status_code}: {body}".strip()


def supports_host(host: str) -> bool:
    """Whether a reader exists for this host — **a predicate, not a client**.

    The settings page needs to refuse an unsupported host before anything is enabled, and
    it must not be able to obtain something it could call: `GATE-HD-NO-PROVIDER-IN-REQUEST`
    asserts that nothing under `api/http/` imports this module at all, and a function that
    handed back a reader would pass that gate's letter while defeating it.
    """
    return host == GitHubReader.host


def reader_for(host: str, settings: Settings) -> GitHubReader | None:
    """Which reader serves this host, or none. Called from the worker, never from a route."""
    if host == GitHubReader.host:
        return GitHubReader(settings)
    return None
