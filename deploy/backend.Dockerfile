# Cliora Central (P4-12).
#
# Two properties this image must have, both asserted by tests rather than assumed:
#   * it contains no secret. Every credential arrives from the environment at run time
#     (tech §23 #4), and `Settings.reject_dev_secrets_in_production` refuses to start
#     with the dev defaults — so a misconfigured deploy fails loudly instead of running
#     on a placeholder JWT secret.
#   * it does not migrate on start. Migrations are a separate one-shot job
#     (`deploy/migrate.sh`); a replica that migrates on boot races its siblings and
#     turns a rollout into an unplanned schema change.

FROM python:3.12-slim-bookworm AS build

# uv is pinned by digest-bearing tag: an unpinned installer is a supply-chain hole in
# the build of the thing that enforces checksums elsewhere (SEC-002).
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

WORKDIR /build
# Dependency layer first, so application edits do not re-resolve the lock.
COPY backend/pyproject.toml backend/uv.lock ./
# --locked, not --frozen: a lock that does not match pyproject must fail the build
# rather than be silently re-resolved into something nobody reviewed.
RUN uv sync --locked --no-install-project --no-dev

COPY backend/ ./
RUN uv sync --locked --no-dev


FROM python:3.12-slim-bookworm AS runtime

# Non-root, matching the daemon's own rule (SEC-007). Central has no reason to hold
# root: it opens one port, talks to PostgreSQL, and reads nothing from the host.
RUN groupadd --system --gid 10001 cliora \
 && useradd --system --uid 10001 --gid cliora --no-create-home --shell /usr/sbin/nologin cliora

WORKDIR /app
COPY --from=build --chown=root:root /build /app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER cliora
EXPOSE 8000

# No shell form: SIGTERM must reach uvicorn directly, or the graceful drain
# (`app.main._drain`) never runs and every deploy disconnects browsers without
# explanation. A shell wrapper would swallow the signal.
ENTRYPOINT ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
