# ADR 0001: P0 toolchain and layout

Status: accepted (2026-07-22)

Cliora P0 uses Python 3.12.3 with uv 0.11.31, Go 1.26.5 modules, Node 22.14.0 with npm, and tmux >=3.4. Patch versions live in root version files and CI reads those files. Each ecosystem owns its lockfile. The root `Makefile` is the single task entry point.

The repository uses `backend/`, `daemon/`, `frontend/`, `contracts/`, and `tests/`. Turborepo is deliberately excluded: only one Node package exists and adding an orchestrator would create a second task graph without improving the cross-language host integration workflow.
