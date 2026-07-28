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

# /app, not /build: `uv sync` writes an absolute shebang (`#!/app/.venv/bin/python`) into
# every console script, so the venv must be assembled at the path it will be executed
# from. Staging it elsewhere and copying leaves `alembic` and `uvicorn` pointing at an
# interpreter that does not exist in the runtime image, and the exec failure reports the
# *script* as missing — "exec /app/.venv/bin/uvicorn: no such file or directory".
WORKDIR /app
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
COPY --from=build --chown=root:root /app /app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# --- optional: bake one verified agentd release into the image (ADR 0020) ---
#
# For a host deployment this stays off and `CLIORA_ARTIFACTS_DIR` points at a mounted
# directory (see deploy/compose/compose.yaml). It exists because a managed platform's
# container filesystem is ephemeral, while `/api/downloads` and the release manifest read
# the local filesystem — so on such a platform the artifacts must arrive at build time.
#
# Off by default *and* a no-op when off: with no AGENTD_VERSION the script writes nothing
# and exits 0, so the host build acquires no build-time network dependency. Every digest
# is verified against the release's own checksums.txt before anything is written
# (SEC-002, tech §23 #12); see scripts/railway/bake_artifacts.py for what that does and
# does not prove.
ARG AGENTD_VERSION=""
ARG AGENTD_RELEASE_BASE_URL=""
COPY scripts/railway/bake_artifacts.py /tmp/bake_artifacts.py
COPY deploy/install.sh /tmp/install.sh
# The chmod is read-only for everyone, including the user Central runs as: Central
# publishes these and has no reason to be able to alter them. That is what the compose
# deployment says with `:ro` on its mount.
RUN python /tmp/bake_artifacts.py \
      --version "$AGENTD_VERSION" \
      --base-url "$AGENTD_RELEASE_BASE_URL" \
      --dest /srv/artifacts \
      --install-script /tmp/install.sh \
 && rm -f /tmp/bake_artifacts.py /tmp/install.sh \
 && if [ -d /srv/artifacts ]; then chown -R 10001:10001 /srv/artifacts && chmod -R a-w /srv/artifacts; fi

USER cliora
EXPOSE 8000

# No shell form: SIGTERM must reach uvicorn directly, or the graceful drain
# (`app.main._drain`) never runs and every deploy disconnects browsers without
# explanation. A shell wrapper would swallow the signal.
#
# A managed platform that overrides the start command replaces this ENTRYPOINT; the
# override must bind `::`, not `0.0.0.0`, or an IPv6 private network cannot reach it
# (deploy/railway/central.railway.json does exactly that).
ENTRYPOINT ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
