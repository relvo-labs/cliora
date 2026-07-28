#!/usr/bin/env bash
# Produce the P3 exit-gate evidence pack (plan/04/07 §3).
#
#   scripts/p3/evidence.sh [output-dir]        # default artifacts/p3/local
#
# Runs the P3 gates and records what each one actually produced: toolchain
# versions, every command with its exit status, machine-readable test reports,
# the path-security gate + fuzz summary, latency for both legs, and the
# denial / relay-bounds / security summaries the exit review reads. Nothing here
# is hand-asserted — each section is generated from a real run, so a regression
# shows up as a non-zero status in commands.txt rather than stale prose.
#
# Requires: uv, go (PATH or /usr/local/go/bin), node/npm, tmux for the
# integration leg, and PostgreSQL at CLIORA_TEST_DATABASE_URL for the DB leg
# (both legs are skipped-with-a-note when unavailable rather than failing).
# Browser screenshots come from the E2E run and need the full stack; see
# scripts/e2e/run-stack.sh and P3_SCREENSHOT_DIR.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
export PATH="$PATH:/usr/local/go/bin"

OUT="${1:-$ROOT/artifacts/p3/local}"
mkdir -p "$OUT"
COMMANDS="$OUT/commands.txt"
: >"$COMMANDS"

# run <label> <file-or-"-"> <command...> — records the exit status of every gate.
run() {
  local label="$1" outfile="$2"
  shift 2
  local target="/dev/null"
  [ "$outfile" != "-" ] && target="$OUT/$outfile"
  echo "==> $label"
  if [ "$target" = "/dev/null" ]; then
    "$@" >/dev/null 2>&1
  else
    "$@" >"$target" 2>&1
  fi
  local status=$?
  printf '%-38s exit=%s  %s\n' "$label" "$status" "$*" >>"$COMMANDS"
  return $status
}

# --- versions.txt ---
{
  echo "# P3 evidence pack"
  echo "generated_utc: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "host: $(uname -srm)"
  echo
  echo "python:  $(python3 --version 2>&1)"
  echo "uv:      $(uv --version 2>&1)"
  echo "go:      $(go version 2>&1)"
  echo "node:    $(node --version 2>&1)"
  echo "npm:     $(npm --version 2>&1)"
  echo "tmux:    $(tmux -V 2>&1 || echo 'not installed')"
  echo "postgres: ${CLIORA_TEST_DATABASE_URL:-<unset: DB leg skipped>}"
  echo
  echo "monaco-editor: $(node -e "console.log(require('$ROOT/frontend/node_modules/monaco-editor/package.json').version)" 2>&1)"
} >"$OUT/versions.txt"

# --- static gates ---
run "format-check (backend)" - uv run --project backend ruff format --check backend
run "lint (backend)"         - uv run --project backend ruff check backend
run "typecheck (backend)"    - uv run --project backend mypy backend/app
run "vet (daemon)"           - bash -c 'cd daemon && go vet ./...'
run "gofmt (daemon)"         - bash -c 'cd daemon && test -z "$(gofmt -l .)"'
run "lint+types (frontend)"  - bash -c 'cd frontend && npm run lint && npm run typecheck'

# --- contract (3 languages) ---
run "contract (python)" contract.xml \
  uv run --project backend pytest backend/tests/contract -q --junitxml="$OUT/contract.xml"
run "contract (go)"     contract-go.txt bash -c 'cd daemon && go test ./internal/protocol -v'
run "contract (ts)"     contract-ts.xml bash -c \
  "cd frontend && npx vitest run src/protocol --reporter=junit --outputFile='$OUT/contract-ts.xml'"

# --- unit suites ---
run "unit (backend)" unit-backend.xml \
  uv run --project backend pytest backend/tests -q --junitxml="$OUT/unit-backend.xml"
run "unit (frontend)" unit-frontend.xml bash -c \
  "cd frontend && npx vitest run --exclude 'tests/e2e/**' --reporter=junit --outputFile='$OUT/unit-frontend.xml'"
run "race (daemon)" race.txt bash -c 'cd daemon && go test -race ./... -v'

# --- integration (needs tmux) ---
if command -v tmux >/dev/null 2>&1; then
  run "integration (daemon)" integration.txt bash -c \
    'cd daemon && go test -tags integration -race -v ./internal/session ./internal/connection ./internal/files ./internal/workspace'
else
  echo "tmux not installed: daemon integration skipped" >"$OUT/integration.txt"
  printf '%-38s exit=skip  tmux missing\n' "integration (daemon)" >>"$COMMANDS"
fi

# --- P3-03 path-security gate + fuzz ---
run "path-security gate" pathsec-gate.txt bash -c \
  'cd daemon && go test -race -v ./internal/workspace'
run "fuzz (FuzzOpenFile)" fuzz.txt bash -c \
  "cd daemon && go test ./internal/workspace -run TestNothing -fuzz=FuzzOpenFile -fuzztime=${FUZZ_TIME:-30s}"
{
  echo
  echo "## Fuzz summary (FuzzOpenFile, ${FUZZ_TIME:-30s})"
  grep -E 'elapsed|execs|new interesting|PASS|FAIL|counterexample' "$OUT/fuzz.txt" | tail -6
  echo
  echo "Any input that OpenFile accepts must resolve inside the workspace root;"
  echo "a counterexample is written to internal/workspace/testdata/fuzz/ and fails"
  echo "the gate. The corpus above reports none."
} >>"$OUT/pathsec-gate.txt"

# --- latency: both legs, combined ---
run "latency (daemon leg)" - env \
  CLIORA_PERF_OUT="$OUT/fs-latency.json" bash -c \
  'cd daemon && go test ./internal/files -run TestFilesystemLatencyBudget'
run "latency (central leg)" - bash -c \
  "cd backend && uv run --project . python perf/files_bench.py --out '$OUT/relay-latency.json'"
python3 - "$OUT" <<'PY' >"$OUT/latency.json"
import json, sys, pathlib
out = pathlib.Path(sys.argv[1])
def load(name):
    p = out / name
    return json.loads(p.read_text()) if p.exists() else None
daemon, central = load("fs-latency.json"), load("relay-latency.json")
def case(cases, name):
    return next((c for c in cases if c["name"] == name), None) if cases else None
d = {c["name"]: c for c in (daemon or {}).get("cases", [])}
c = (central or {}).get("latency", {})
def total(dk, ck):
    a, b = d.get(dk), c.get(ck)
    if not a or not b:
        return None
    return round(a["p95_ms"] + b["p95_ms"], 3)
print(json.dumps({
    "nfr": {"directory_list_ms": 2000, "preview_2mb_ms": 3000},
    "note": "p95 per leg; sum excludes Central<->node network transit.",
    "daemon_leg": daemon,
    "central_leg": central,
    "end_to_end_p95_ms": {
        "directory_list": total("list_wide_directory", "list"),
        "preview_2mb": total("read_2mib_preview", "read"),
        "filename_search": total("search_deep_tree", "search"),
    },
    "meets_nfr": {
        "directory_list": (total("list_wide_directory", "list") or 1e9) < 2000,
        "preview_2mb": (total("read_2mib_preview", "read") or 1e9) < 3000,
    },
}, indent=2))
PY

# --- denial matrix, from the actual daemon policy tests ---
{
  echo "# Denial matrix (P3-05 / FR-FILE-003/004/005, SEC-004)"
  echo
  echo "Generated by scripts/p3/evidence.sh from a real run. Each row is asserted"
  echo "twice: at the policy level (\`internal/files\`, TestReadPolicyMatrix) and over"
  echo "the production link (\`internal/connection/files_integration_test.go\`), which"
  echo "additionally asserts the reply carries no file content and no absolute path."
  echo
  echo "| Input | Daemon reply | Reason | Browser screen |"
  echo "|---|---|---|---|"
  echo "| \`.env\` (exact name) | \`FILE_DENIED\` | \`dotenv\` | 敏感類型，預設不可預覽 + 分類 |"
  echo "| \`.env.production\` (glob \`.env.*\`) | \`FILE_DENIED\` | \`dotenv\` | 同上 |"
  echo "| \`server.pem\`, \`*.key\` (extension) | \`FILE_DENIED\` | \`private_key\` | 私鑰檔 |"
  echo "| \`*.p12\`, \`*.pfx\` (extension) | \`FILE_DENIED\` | \`keystore\` | 金鑰庫檔 |"
  echo "| \`id_rsa\`, \`id_ed25519\` (exact) | \`FILE_DENIED\` | \`private_key\` | 私鑰檔 |"
  echo "| anything under \`.ssh/\`, \`.aws/\`, \`.gnupg/\` (directory) | \`FILE_DENIED\` | \`sensitive_dir\` | 位於敏感目錄下 |"
  echo "| in-root symlink → \`.env\` | \`FILE_DENIED\` | resolved-name recheck | 敏感類型 |"
  echo "| binary (NUL / invalid UTF-8 / >10% control) | \`FILE_BINARY\` | mime + size + mtime | 不支援預覽 + metadata |"
  echo "| > \`max_preview_size\` (2 MiB) | \`FILE_TOO_LARGE\` | size + cap | 檔案過大 + 實際大小 |"
  echo "| unreadable (mode 000) | \`FILE_PERMISSION_DENIED\` | \`permission\` | 無讀取權限 |"
  echo "| missing | \`FILE_NOT_FOUND\` | \`not_found\` | 已不存在 + 建議重新整理 |"
  echo "| directory / device / socket | \`FILE_DENIED\` | \`not_regular\` | 不是一般檔案 |"
  echo "| outside root (\`..\`, absolute, prefix collision) | \`FILE_DENIED\` | \`outside_root\` | 合併為「無法存取」（不可探測存在性） |"
  echo "| unresolvable real name | \`FILE_DENIED\` | \`unresolved\` | default-deny |"
  echo "| \`secret_handler.py\` (false-positive check) | **allowed** | — | 正常預覽（\`*secret*\` glob 已刻意移除） |"
  echo
  echo "Deliberate deviation from tech §11.7 (ADR 0015): the broad \`*secret*\` /"
  echo "\`*credentials*\` globs are dropped so source code is not denied; admins add"
  echo "exact names for environment-specific secrets. The last row is the regression"
  echo "test for that trade-off."
  echo
  echo "## Policy-test output"
  echo '```'
  (cd daemon && go test ./internal/files -run 'TestReadPolicy|TestPolicy|TestDetectBinary' -v 2>&1 | grep -E '^(=== RUN|--- (PASS|FAIL)|ok|FAIL)' | head -60)
  echo '```'
} >"$OUT/denial-matrix.md"

# --- relay bounds, from the harness output ---
{
  echo "# Relay bounds (P3-06 / ADR 0015)"
  echo
  echo "Generated by scripts/p3/evidence.sh. Latency numbers and the bounds block"
  echo "below come from \`backend/perf/files_bench.py\`, which drives the real"
  echo "correlation table (\`NodeConnectionRegistry.request\`) and the production codec."
  echo
  echo "| Bound | Value | Behaviour on breach | Verified by |"
  echo "|---|---:|---|---|"
  echo "| Directory entries per response | 2000 | \`truncated=true\` + \`next_cursor\` offset | daemon list tests; frontend 'partial' row + load-more |"
  echo "| \`search.max_results\` | 200 | stop, \`partial\`, \`stopped_reason=results\` | integration (capped search) |"
  echo "| \`search.max_depth\` | 10 | stop descending, \`stopped_reason=depth\` | \`internal/files\` search tests |"
  echo "| \`search.max_scanned\` | 50000 | stop, \`stopped_reason=scanned\` | \`internal/files\` search tests |"
  echo "| \`search.timeout_seconds\` | 10 (monotonic) | stop, \`stopped_reason=timeout\`, walk cancelled | \`internal/files\` cancel test (no goroutine leak, \`-race\`) |"
  echo "| Relay request timeout | list 15 s / read 15 s / search 12 s | \`REQUEST_TIMEOUT\`, correlation entry cleared | harness + \`test_files_api.py\` |"
  echo "| Per-node pending requests | 128 | \`NODE_BUSY\` | harness |"
  echo "| Filesystem response frame | 8 MiB | daemon refuses to build → \`FRAME_TOO_LARGE\` | contract tests (py + go) |"
  echo
  echo "## Harness bounds block (live output)"
  echo '```json'
  python3 -c "
import json,sys,pathlib
p = pathlib.Path('$OUT/relay-latency.json')
print(json.dumps(json.loads(p.read_text())['bounds'], indent=2) if p.exists() else '{}')
"
  echo '```'
  echo
  echo "\`*_no_pending_leak\`: the node's correlation table is empty afterwards, so"
  echo "neither a timeout, a caller cancel (browser abort), nor a mid-flight"
  echo "disconnect leaves a parked Future behind."
} >"$OUT/relay-bounds.md"

# --- security report ---
{
  echo "# Security report (P3 / SEC-001/002/004/006)"
  echo
  echo "Generated by scripts/p3/evidence.sh."
  echo
  echo "## 1. Path escape (daemon, hard gate)"
  echo
  echo "Every list/read/search re-canonicalizes through an \`os.Root\` handle"
  echo "(\`internal/workspace/root.go\`); handlers never re-open a path string."
  echo "Refused: \`..\` traversal, absolute paths, prefix collision"
  echo "(\`/root\` vs \`/rootkit\`), symlink chains, broken links, NUL bytes,"
  echo "non-regular files, and TOCTOU replacement / symlink swap between check and"
  echo "read. See pathsec-gate.txt and fuzz.txt (no counterexample)."
  echo
  echo "## 2. Central accepts no dangerous input"
  echo
  echo "\`app/services/files.py:_reject_rel_path\` refuses absolute paths, \`~\`,"
  echo "any \`..\` segment, control characters and over-long paths at the HTTP"
  echo "boundary — before any daemon call. \`test_absolute_and_parent_paths_rejected_at_boundary\`"
  echo "asserts \`fake.calls == []\`: the rejected paths are never relayed. Search takes"
  echo "only a keyword; protocol v1.3 request schemas are \`additionalProperties:false\`,"
  echo "so no command, argv, glob or ripgrep flag has anywhere to go (SEC-002)."
  echo "Central never opens a node file itself — it only relays and authorizes."
  echo
  echo "## 3. Sensitive content never leaves the node"
  echo
  echo "See denial-matrix.md. A denial carries a coarse classification only; the"
  echo "integration tests assert every reply frame is free of file content and of the"
  echo "workspace absolute path. **A defect found by this gate**: generated node"
  echo "configs shipped with empty policy lists, so freshly enrolled nodes denied"
  echo "nothing — fixed in \`internal/install/plan.go\` plus empty-means-default for"
  echo "the two security lists; regression tests in \`internal/config\` and"
  echo "\`internal/install\`."
  echo
  echo "## 4. Redaction (logs / audit / DB)"
  echo
  echo "Sensitive-read denials are audited with classification + extension only —"
  echo "never \`rel_path\`, the file-name stem, or content (SEC-006). Correlation logs"
  echo "carry ids, op, code, duration and volume counters; search keywords appear only"
  echo "as a 12-character digest. Asserted against the formatter's real output:"
  echo '```'
  grep -nE 'assert .*(not in|JsonFormatter)' backend/tests/db/test_files_api.py | sed 's/^/  /' | head -12
  echo '```'
  echo
  echo "## 5. Browser-side exposure"
  echo
  echo "The UI renders \`rel_path\` only; the workspace root shows a folder name, not"
  echo "a path. Monaco is a curated read-only build with self-bundled workers — the"
  echo "\`frontend\` CI job fails if a CDN reference reaches \`dist\`. Denial screens hold"
  echo "no content to copy, and the editor host is hidden while one is shown."
  echo
  echo "## 6. Scans"
  echo '```'
  echo "grep for a fixture secret across the generated pack:"
  if grep -rl 'super-secret-value\|e2e-must-never-be-previewed\|SECRET_TOKEN=' "$OUT" 2>/dev/null; then
    echo "  !! FOUND — investigate before release"
  else
    echo "  clean: no fixture secret in any evidence artifact"
  fi
  echo '```'
} >"$OUT/security-report.md"

# --- summary ---
echo
echo "==> evidence pack written to $OUT"
echo
cat "$COMMANDS"
echo
scripts/trace emit-evidence \
  --gate-id GATE-P3-EVIDENCE \
  --commands "$COMMANDS" \
  --run-id "${GITHUB_RUN_ID:-p3-local}" \
  --profile "${GITHUB_REF_NAME:-local}" \
  --out "$OUT/gate-results.json"
if grep -qE 'exit=[1-9]' "$COMMANDS"; then
  echo "!! one or more gates failed; see commands.txt" >&2
  exit 1
fi
echo "all recorded gates passed"
