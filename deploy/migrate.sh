#!/usr/bin/env bash
# Apply database migrations as a one-shot step (P4-12).
#
# Separate from the application on purpose. If Central migrated on startup, then every
# replica would race every other one on a rollout, and a restart would become an
# unplanned schema change — the two failure modes that turn a deploy into an incident.
#
# Order:  migrate.sh  ->  backend starts  ->  /readyz green  ->  nginx serves traffic.
#
# /readyz compares the applied revision against the expected head, so getting this order
# wrong is *detected* rather than merely documented: the backend reports itself unready
# and the healthcheck keeps it out of rotation.
#
#   deploy/migrate.sh              # upgrade to head
#   deploy/migrate.sh current      # show the applied revision, change nothing
#   deploy/migrate.sh downgrade 0010
set -euo pipefail

: "${CLIORA_DATABASE_URL:?CLIORA_DATABASE_URL must be set}"
cd "$(dirname "${BASH_SOURCE[0]}")/../backend"

case "${1:-upgrade}" in
  upgrade)
    echo "==> alembic upgrade head"
    exec uv run --project . alembic upgrade head
    ;;
  current)
    exec uv run --project . alembic current
    ;;
  downgrade)
    target="${2:?usage: migrate.sh downgrade <revision>}"
    # Deliberately interactive. Every P4 migration is reversible and each one's docstring
    # states whether its downgrade is lossy, but reversible is not the same as harmless:
    # rows written since the upgrade can be dropped. See docs/deployment.md before
    # reaching for this during an incident.
    echo "About to downgrade to ${target}. Data written since that revision may be lost."
    read -r -p "Type the revision again to confirm: " confirm
    [ "$confirm" = "$target" ] || { echo "aborted"; exit 1; }
    exec uv run --project . alembic downgrade "$target"
    ;;
  *)
    echo "usage: migrate.sh [upgrade|current|downgrade <revision>]" >&2
    exit 2
    ;;
esac
