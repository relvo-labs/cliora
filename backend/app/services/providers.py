"""The platform's first outbound call to somebody else's server (DV-05, ADR 0033 §3).

Everything in this module is bounded by things that are absent from it.

**Three actions, and the table is closed.** Create a pull request, find one, comment on
one. There is no merge, no approve, no review, no close, no tag, no release —
`GATE-DV-PROVIDER-VERBS` asserts the words themselves do not appear, because red line 5
is verified by absence rather than by a check: a check has a second call site, and a
table that does not contain the word does not.

**No retries.** The HTTP convention is to retry a timeout; **creation is not
idempotent**, and a timeout may mean the request arrived and the reply did not. Retrying
opens a second pull request on somebody's repository. A timeout is a failure here, and
the run is marked `delivered_branch_only`.

**A host allowlist whose default is one host.** The API base is a deployment setting, so
no repository row can redirect where Central connects — the SSRF shape this would
otherwise have. `ProjectRepository` already stores scheme, host and path in three columns
rather than one URL for the neighbouring reason (`models.py`), and this reuses that:
`owner/repo` comes from the stored path, never from parsing a free-form string.

**The token never reaches a log.** It travels in a header on the way out and is stripped
from anything recorded, including the provider's own error body, which is the string a
person pastes into a ticket.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.settings import Settings

# Connect and total. Short enough that a wedged provider does not hold a worker, long
# enough that a large repository's API call completes.
CONNECT_TIMEOUT_SECONDS = 5.0
TOTAL_TIMEOUT_SECONDS = 20.0

# What may appear in a PR body. Longer than any real report and short enough that a
# provider does not refuse it; the overflow points at the run page.
MAX_BODY_BYTES = 60 * 1024


@dataclass(frozen=True, slots=True)
class PullRequestRef:
    number: int
    url: str


class ProviderError(Exception):
    """A refusal that is a *result*, not a crash.

    `retryable` is deliberately absent. Nothing in this module retries, and a field
    saying otherwise would be an invitation (see the module docstring).
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ProviderAdapter(Protocol):
    host: str

    async def create_pull_request(
        self, *, repo_path: str, head: str, base: str, title: str, body: str, token: str
    ) -> PullRequestRef: ...

    async def find_pull_request(
        self, *, repo_path: str, head: str, token: str
    ) -> PullRequestRef | None: ...

    async def comment_on_pull_request(
        self, *, repo_path: str, number: int, body: str, token: str
    ) -> None: ...


_OWNER_REPO = re.compile(r"^/?([A-Za-z0-9._-]+)/([A-Za-z0-9._-]+?)(?:\.git)?/?$")


def owner_repo(path: str) -> tuple[str, str]:
    """`owner/repo` from the repository's **stored path column**.

    Not from a URL. Extracting a host or an owner from a free-form URL is how
    `https://github.com@evil.example/` gets through, which is the reason
    `ProjectRepository` splits the address into three columns in the first place — the
    same argument, one layer up.
    """
    match = _OWNER_REPO.match(path or "")
    if not match:
        raise ProviderError("PROVIDER_REFUSED", "This repository path is not owner/repo")
    return match.group(1), match.group(2)


class GitHubAdapter:
    """GitHub, and **only** GitHub (D15).

    GitLab is refused at dispatch rather than half-implemented here: a half-built
    provider fails after the work is done, and a refusal at dispatch costs nothing.
    """

    host = "github.com"

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._client = client
        self._api_base = "https://api.github.com"

    # --- the three actions ---------------------------------------------------

    async def create_pull_request(
        self, *, repo_path: str, head: str, base: str, title: str, body: str, token: str
    ) -> PullRequestRef:
        owner, repo = owner_repo(repo_path)
        payload = await self._request(
            "POST",
            f"/repos/{owner}/{repo}/pulls",
            token,
            json={"title": title, "head": head, "base": base, "body": body},
        )
        return PullRequestRef(number=int(payload["number"]), url=str(payload["html_url"]))

    async def find_pull_request(
        self, *, repo_path: str, head: str, token: str
    ) -> PullRequestRef | None:
        """Whether this head already has one.

        In the verb table deliberately: "a pull request already exists for this head" is
        one of the four creation outcomes, and detecting it by parsing somebody's error
        message is a path that breaks the day they reword it.
        """
        owner, repo = owner_repo(repo_path)
        payload = await self._request(
            "GET",
            f"/repos/{owner}/{repo}/pulls",
            token,
            params={"head": f"{owner}:{head}", "state": "open"},
        )
        if isinstance(payload, list) and payload:
            first = payload[0]
            return PullRequestRef(number=int(first["number"]), url=str(first["html_url"]))
        return None

    async def comment_on_pull_request(
        self, *, repo_path: str, number: int, body: str, token: str
    ) -> None:
        owner, repo = owner_repo(repo_path)
        await self._request(
            "POST",
            f"/repos/{owner}/{repo}/issues/{number}/comments",
            token,
            json={"body": body},
        )

    # --- transport -----------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        token: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        base = self._settings.provider_api_base or self._api_base
        host = httpx.URL(base).host
        allowed = self._settings.provider_api_host_list()
        if host not in allowed:
            # The deployment decides where Central may connect. A repository row cannot
            # reach this — it supplies `owner/repo` and nothing else.
            raise ProviderError(
                "PROVIDER_REFUSED",
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
            response = await client.request(
                method, f"{base}{path}", headers=headers, json=json, params=params
            )
        except httpx.HTTPError as exc:
            # **Not retried**, and the class of error is deliberately not inspected: a
            # timeout that actually arrived would become a second pull request.
            raise ProviderError(
                "PROVIDER_UNREACHABLE", f"Could not reach the provider: {type(exc).__name__}"
            ) from exc
        finally:
            if owns_client:
                await client.aclose()

        if response.status_code >= 400:
            raise ProviderError("PROVIDER_REFUSED", _safe_detail(response, token))
        return response.json()


def _safe_detail(response: httpx.Response, token: str) -> str:
    """The provider's own words, with the credential removed.

    The error body is the string a person pastes into a ticket, so it is the highest-risk
    place a token could surface — higher than a log line, because it is quoted
    deliberately rather than collected by accident.
    """
    try:
        body = response.text[:500]
    except Exception:  # pragma: no cover - a body that cannot be decoded
        body = ""
    if token:
        body = body.replace(token, "***")
    return f"{response.status_code}: {body}".strip()


def supports_host(host: str) -> bool:
    """Whether a provider adapter exists for this host — **a predicate, not a client**.

    Dispatch needs to refuse an unsupported host before the work happens, and it must
    not be able to obtain something it could call: `services/runs.py` runs on the node
    receive loop, and `GATE-DV-NO-HTTP-IN-LOOP` asserts that nothing there reaches a
    provider. Handing that module a `ProviderAdapter` would pass the gate's letter today
    and be one line away from failing its purpose.
    """
    return host == GitHubAdapter.host


def adapter_for(host: str, settings: Settings) -> ProviderAdapter | None:
    """Which adapter serves this host, or none.

    A registry with one entry rather than an `if`: the shape is what makes "GitLab is
    not implemented" a fact somebody can see, and the dispatch-time refusal reads it.
    """
    if host == GitHubAdapter.host:
        return GitHubAdapter(settings)
    return None
