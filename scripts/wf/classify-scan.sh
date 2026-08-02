#!/usr/bin/env bash
# Whole-tree text/binary classification scan (plan/13 WF-03 §4).
#
# Two jobs:
#   * Acceptance: the number of *valid UTF-8* files judged binary must be 0.
#     Before this change it was 20 on this repository, all of them Markdown
#     whose 8 KiB window happened to cut inside a multi-byte rune.
#   * Runbook: when someone reports "I cannot preview this file", run it on the
#     node against that path and the verdict comes back with the reason.
#
# Usage: scripts/wf/classify-scan.sh [dir-or-file ...]   (default: this repo)
set -euo pipefail
cd "$(dirname "$0")/../.."

targets=("$@")
if [ ${#targets[@]} -eq 0 ]; then
  targets=(plan docs research backend frontend/src daemon contracts scripts)
fi

status=0
for target in "${targets[@]}"; do
  # The scanner is a Go program because the classifier it exercises is the
  # daemon's own — reimplementing the rules in shell would test the shell.
  if ! (cd daemon && go run ./internal/files/classifyscan "../$target"); then
    status=1
  fi
done

if [ "$status" -eq 0 ]; then
  echo
  echo "[ OK ] no valid-UTF-8 file was judged binary (FR-FILE-008.AC-01)"
fi
exit "$status"
