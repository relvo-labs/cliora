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

# The image mirrors the repository layout: /app is the repo root and the backend lives at
# /app/backend, with contracts/ beside it. Two things depend on that, and both fail at
# import or exec time rather than gracefully:
#
#   * `app/protocol/codec.py` and `app/api/error_catalog.py` resolve the v1 contracts as
#     `Path(__file__).parents[3] / "contracts"`, which is the repo root in a checkout.
#     Flattening backend/ into /app makes parents[3] the filesystem root, and codec.py
#     reads its schema at *import* time — so the process dies before serving anything.
#   * `uv sync` writes an absolute shebang into every console script it generates, so the
#     venv has to be assembled at the path it will be executed from. Staged elsewhere and
#     copied, `alembic` and `uvicorn` point at an interpreter this image does not contain,
#     and the exec failure names the *script* as missing.
#
# Both were invisible until something exec'd the image; `.github/workflows/ci.yml` now
# builds it and imports the app.
WORKDIR /app/backend
# Dependency layer first, so application edits do not re-resolve the lock.
COPY backend/pyproject.toml backend/uv.lock ./
# --locked, not --frozen: a lock that does not match pyproject must fail the build
# rather than be silently re-resolved into something nobody reviewed.
RUN uv sync --locked --no-install-project --no-dev

COPY backend/ ./
RUN uv sync --locked --no-dev


# Builds the agentd release this image serves, at the version `daemon/VERSION` declares.
# This is the default because the artifacts are not a deployment choice: an image that
# serves the daemon built from its own commit cannot be misconfigured into serving none,
# which is the failure this replaced — `/api/install-script` answering 404 on a deployment
# that looked healthy.
#
# It is skipped when `AGENTD_RELEASE_BASE_URL` selects the download route instead. The
# skip is *inside* the stage rather than a skipped stage, because the runtime stage's
# `COPY --from` cannot be conditional: /out is then empty and neither `go mod download`
# nor any compile runs.
FROM golang:1.26-bookworm AS agentd
ARG AGENTD_RELEASE_BASE_URL=""
WORKDIR /src
COPY daemon/go.mod daemon/go.sum ./
RUN if [ -z "$AGENTD_RELEASE_BASE_URL" ]; then go mod download; fi
COPY daemon/ ./
COPY scripts/railway/pack-agentd.sh /usr/local/bin/pack-agentd.sh
RUN mkdir -p /out \
 && if [ -z "$AGENTD_RELEASE_BASE_URL" ]; then /usr/local/bin/pack-agentd.sh /out; fi


FROM python:3.12-slim-bookworm AS runtime

# Non-root, matching the daemon's own rule (SEC-007). Central has no reason to hold
# root: it opens one port, talks to PostgreSQL, and reads nothing from the host.
RUN groupadd --system --gid 10001 cliora \
 && useradd --system --uid 10001 --gid cliora --no-create-home --shell /usr/sbin/nologin cliora

# WORKDIR is the backend, because alembic.ini's `script_location` is relative to it and
# `uvicorn app.main:app` needs the package on the path. The platform's start and pre-deploy
# commands and compose's migrate entrypoint all run here.
WORKDIR /app/backend
COPY --from=build --chown=root:root /app /app
# Read at import time by the protocol codec, so this is a runtime dependency of the
# application and not merely test data. Copied read-only: Central validates against these
# schemas and has no reason to be able to alter them.
COPY --chown=root:root contracts /app/contracts
ENV PATH="/app/backend/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# --- the agentd release this image serves (ADR 0020 §8) ---
#
# This exists because a managed platform's container filesystem is ephemeral, while
# `/api/downloads`, `/api/install-script` and the release manifest read the local
# filesystem — so the artifacts have to arrive at build time.
#
# Nothing here is a deployment variable. The version comes from `daemon/VERSION`, next to
# the code it names, and the directory is set below rather than asked for: a deployment
# that has to remember two settings before its installer works is a deployment that
# answers 404 and looks healthy doing it.
#
# The one knob is `AGENTD_RELEASE_BASE_URL`, and it is a genuine deployment choice —
# *where the bytes come from*:
#
#   unset (default)   the `agentd` stage above compiled them from this commit.
#   set               download that release instead and verify every SHA-256 against its
#                     own checksums.txt before anything lands (SEC-002, tech §23 #12);
#                     see bake_artifacts.py for what that does and does not prove. The
#                     URL must be fetchable without credentials — a private repository's
#                     release assets answer 404 — and its version must agree with
#                     daemon/VERSION or the digest lookup fails the build.
#
# The COPY is unconditional because a `COPY --from` cannot be conditional; on the download
# route /out is empty and the step below fills the directory.
ARG AGENTD_RELEASE_BASE_URL=""
COPY --from=agentd /out /srv/artifacts
COPY daemon/VERSION /tmp/agentd-version
COPY scripts/railway/bake_artifacts.py /tmp/bake_artifacts.py
COPY deploy/install.sh /tmp/install.sh
# The chmod is read-only for everyone, including the user Central runs as: Central
# publishes these and has no reason to be able to alter them. That is what the compose
# deployment says with `:ro` on its mount. It stays last — both branches above write.
RUN if [ -n "$AGENTD_RELEASE_BASE_URL" ]; then \
      python /tmp/bake_artifacts.py \
        --version "$(cat /tmp/agentd-version)" \
        --base-url "$AGENTD_RELEASE_BASE_URL" \
        --dest /srv/artifacts \
        --install-script /tmp/install.sh; \
    else \
      install -m 0644 /tmp/install.sh /srv/artifacts/install.sh; \
    fi \
 && rm -f /tmp/bake_artifacts.py /tmp/install.sh /tmp/agentd-version \
 && chown -R 10001:10001 /srv/artifacts \
 && chmod -R a-w /srv/artifacts

# Set here, not in the platform. `/srv/artifacts` is where this image puts the release, so
# the image is what knows it; a deployment only overrides this to point somewhere else
# (deploy/compose/compose.yaml mounts a host directory over it).
ENV CLIORA_ARTIFACTS_DIR=/srv/artifacts

USER cliora
EXPOSE 8000

# No shell form: SIGTERM must reach uvicorn directly, or the graceful drain
# (`app.main._drain`) never runs and every deploy disconnects browsers without
# explanation. A shell wrapper would swallow the signal.
#
# A managed platform that overrides the start command replaces this ENTRYPOINT. On an
# IPv6 private network `0.0.0.0` is unreachable, but `::` is not the fix: asyncio sets
# IPV6_V6ONLY on an AF_INET6 socket, so it refuses IPv4 regardless of the bindv6only
# sysctl. The override binds an empty host, which asyncio reads as "every family"
# (deploy/railway/central.railway.json does exactly that).
ENTRYPOINT ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
