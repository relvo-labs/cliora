"""What an older Central does with the node.register a 1.11 daemon sends (ADR 0029 §9).

`node-register` is `additionalProperties:false`, so a Central that predates a field rejects
the *key*, whatever its value, and it does so silently (`ws/nodes.py` skips the frame and
the daemon ignores acks). That is why a disabled daemon omits `binary_preview` instead of
sending `false`, and why the forward order is Central first. Both properties were a sentence
in a runbook; these tests make them facts that can fail.

The old Central is represented by a frozen, verbatim copy of its schema
(`contracts/v1/compat/`), checked by digest so it cannot drift into the new one.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker  # type: ignore[import-untyped]
from referencing import Registry, Resource

from app.protocol import ProtocolError, decode_control

ROOT = Path(__file__).parents[2]
FIXTURES = ROOT / "contracts/v1/fixtures"
MESSAGES = ROOT / "contracts/v1/schemas/messages"
FROZEN = ROOT / "contracts/v1/compat/node-register.pre-1.11.schema.json"
FROZEN_SHA256 = "cec889d6b671f7be1613308a958e6bf1b8500e04dab9c85e8276635691918d4b"


def _old_central_register_validator() -> Draft202012Validator:
    schema = json.loads(FROZEN.read_text())
    # The frozen bytes remain the real 1.9.0 copy. Derive the 1.10.0
    # Central surface in memory by adding only #71's report field.
    schema["properties"]["file_download"] = {"type": "boolean"}
    # Place the frozen copy where it used to live so its relative $refs resolve to
    # the message schemas it was written against (unchanged by 1.11.0).
    schema["$id"] = (MESSAGES / "node-register.schema.json").as_uri()
    resources = [
        (path.as_uri(), Resource.from_contents(json.loads(path.read_text())))
        for path in MESSAGES.glob("*.schema.json")
        if path.name != "node-register.schema.json"
    ]
    return Draft202012Validator(
        schema, registry=Registry().with_resources(resources), format_checker=FormatChecker()
    )


def _register_payload(fixture: str) -> dict:
    return json.loads((FIXTURES / fixture).read_text())["payload"]


def test_the_frozen_schema_has_not_been_edited() -> None:
    assert hashlib.sha256(FROZEN.read_bytes()).hexdigest() == FROZEN_SHA256


def test_an_old_central_rejects_an_enabled_daemons_register() -> None:
    """Deploying daemons before Central would silently stale every enabled node's
    registration. This is the fact behind "Central first"."""
    payload = _register_payload("valid/node-register-binary-preview.json")
    payload["file_download"] = True
    assert payload["binary_preview"] is True
    errors = list(_old_central_register_validator().iter_errors(payload))
    assert errors, "a pre-1.11 Central must not accept a register carrying binary_preview"


def test_an_old_central_accepts_a_disabled_daemons_register() -> None:
    """The shape a disabled 1.11 daemon sends is the old shape: no key at all.
    This is the fact behind "disable the switch, then roll Central back"."""
    payload = _register_payload("valid/node-register.json")
    payload["file_download"] = True
    assert "binary_preview" not in payload
    assert list(_old_central_register_validator().iter_errors(payload)) == []


def test_an_old_central_would_reject_false_too_which_is_why_false_is_invalid() -> None:
    payload = copy.deepcopy(_register_payload("valid/node-register.json"))
    payload["binary_preview"] = False
    assert list(_old_central_register_validator().iter_errors(payload)), (
        "the old schema rejects the key regardless of its value"
    )
    frame = json.loads((FIXTURES / "valid/node-register.json").read_text())
    frame["payload"] = payload
    with pytest.raises(ProtocolError):
        decode_control(json.dumps(frame))


def test_the_current_central_accepts_both_shapes() -> None:
    for fixture in ("valid/node-register.json", "valid/node-register-binary-preview.json"):
        raw = (FIXTURES / fixture).read_bytes()
        assert decode_control(raw).type == "node.register"
