#!/usr/bin/env bash
# GATE-PJ-FLAG-OFF: the deployment must not expose the project layer when disabled.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

export PATH="$HOME/.local/bin:$PATH"
: "${CLIORA_TEST_DATABASE_URL:=postgresql+asyncpg://cliora:cliora@127.0.0.1:5432/cliora_test}"
: "${CLIORA_DATABASE_URL:=$CLIORA_TEST_DATABASE_URL}"
export CLIORA_TEST_DATABASE_URL CLIORA_DATABASE_URL

uv run --project backend pytest -q \
  backend/tests/db/test_projects_api.py::test_every_project_route_is_404_while_the_flag_is_off \
  backend/tests/db/test_projects_api.py::test_the_flag_does_not_change_the_mounted_route_set \
  backend/tests/db/test_sessions_project_link.py::test_naming_a_project_is_refused_while_the_flag_is_off \
  backend/tests/db/test_sessions_project_link.py::test_features_reports_the_deployment_not_the_person
