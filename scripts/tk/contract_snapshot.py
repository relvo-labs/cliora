"""Per-file digest of the wire contract (plan/17 TK-00, exit condition 10).

V2.1 is the first phase that adds a protocol message, so "the contract did not
change" stops being provable by "`contracts/` has no diff". What has to stay true is
narrower and, unlike the phases before it, actually needs an instrument:

    every file that existed before this phase is byte-for-byte identical;
    only new files may appear.

That is what `GATE-TK-CONTRACT-ADDITIVE` asserts (`plan/17/08-…md` §4). A digest per
file rather than one digest over the tree, so a failure names the file that changed
instead of only saying that something did.

    python scripts/tk/contract_snapshot.py > artifacts/tk/local/baseline/contract.sha256
    python scripts/tk/contract_snapshot.py --diff artifacts/tk/local/baseline/contract.sha256

Exit code 1 when an existing file changed or disappeared, so it can be a gate rather
than a report. New files are reported on stderr and do **not** fail the check —
adding `context.project` is the point of the phase.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
# **Fixtures only.** Adding a message type necessarily edits two existing schema files
# — the envelope's type enum and nothing else can introduce a type — so a rule that
# froze all of `contracts/` would forbid the phase rather than constrain it. What must
# not move is the *evidence*: a fixture is a recorded decision about what the wire
# accepts and rejects, and an edited one silently rewrites a promise made to every
# daemon already deployed.
ROOT = REPO / "contracts/v1/fixtures"


def _digests() -> dict[str, str]:
    out: dict[str, str] = {}
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(REPO).as_posix()
        out[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def _render(digests: dict[str, str]) -> str:
    return "".join(f"{digest}  {rel}\n" for rel, digest in digests.items())


def _parse(text: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        digest, _, rel = line.partition("  ")
        parsed[rel] = digest
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--diff", type=Path, help="compare against a captured baseline")
    args = parser.parse_args()

    live = _digests()
    if args.diff is None:
        sys.stdout.write(_render(live))
        return 0

    # The baseline captured at TK-00 covers all of `contracts/`, while this gate scopes
    # to fixtures. Filtering rather than recapturing, because the "before" state is
    # exactly what cannot be taken again — and a schema digest outside the scope is not
    # evidence of anything this gate claims.
    prefix = ROOT.relative_to(REPO).as_posix() + "/"
    baseline = {
        rel: digest
        for rel, digest in _parse(args.diff.read_text()).items()
        if rel.startswith(prefix)
    }
    # `manifest.json` is an index, not a payload decision: a new fixture is only tested
    # once it is listed there, so freezing it would forbid adding fixtures at all. The
    # exemption is one file, and it is printed rather than silent — a gate that quietly
    # excuses things is a gate nobody can audit (the same rule `gate-no-wire.sh` states).
    manifest = "contracts/v1/fixtures/manifest.json"
    changed = sorted(
        rel
        for rel, digest in baseline.items()
        if rel != manifest and live.get(rel) != digest
    )
    if live.get(manifest) != baseline.get(manifest):
        print(f"exempt (index, not a payload): {manifest}", file=sys.stderr)
    added = sorted(set(live) - set(baseline))

    for rel in added:
        print(f"added: {rel}", file=sys.stderr)
    if not changed:
        print(f"contract additive: {len(baseline)} existing files unchanged, {len(added)} added")
        return 0
    for rel in changed:
        state = "removed" if rel not in live else "modified"
        print(f"{state}: {rel}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
