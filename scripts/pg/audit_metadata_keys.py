"""Check the audit metadata keys the port-forwarding services write (plan/11 PG-14).

Called from `scripts/pg/check-no-token-leak.sh`. Kept as a file rather than an inline heredoc
so it can be run and read on its own:

    python3 scripts/pg/audit_metadata_keys.py

Why the AST and not a grep: `services/tunnels.py` legitimately builds a `tunnel.open` payload
containing `basic_auth.password`, and a text search for `"password":` cannot tell that apart
from an audit row that records one. The keys of the dicts actually passed as `metadata=` are
the only thing that matters here.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

SOURCES = (
    "backend/app/services/tunnels.py",
    "backend/app/services/integrations.py",
)

# `url` and `label` are here for the same reason as the secrets: a tunnel's URL is part of the
# access credential (under `public` protection it is the whole of it), and the audit trail is
# readable by every `audit.view` holder — so recording it would hand each of them access to the
# preview after the fact. A label is user-supplied prose about somebody's work in progress.
FORBIDDEN = {"token", "provider_token", "credential", "secret", "password", "url", "label"}


def main() -> int:
    offenders: list[str] = []
    for relative in SOURCES:
        path = ROOT / relative
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or getattr(node.func, "attr", "") != "record":
                continue
            for keyword in node.keywords:
                if keyword.arg != "metadata" or not isinstance(keyword.value, ast.Dict):
                    continue
                for key in keyword.value.keys:
                    if isinstance(key, ast.Constant) and key.value in FORBIDDEN:
                        offenders.append(f"{relative}:{node.lineno} -> {key.value}")
    if offenders:
        print("audit metadata writes a forbidden key:", ", ".join(offenders))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
