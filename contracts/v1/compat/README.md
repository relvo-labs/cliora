# Frozen schemas for compatibility tests

Files here are **verbatim copies of an older contract** and are **never edited**. They are
not part of the live contract: no consumer loads them at runtime, and `contracts/v1/schemas`
is the only source of truth for what a current Central, daemon or browser accepts. They
exist so that a test can ask what an *older* peer would do with a message the current code
produces.

| File | Copied from | Contract | sha256 |
|---|---|---|---|
| `node-register.pre-1.11.schema.json` | `contracts/v1/schemas/messages/node-register.schema.json` at `157efe3178999a8c35b34f55ee183d47842c63ec` (last changed by `26f4178`) | 1.9.0, preserved byte for byte; tests derive 1.10.0 in memory by adding `file_download` | `cec889d6b671f7be1613308a958e6bf1b8500e04dab9c85e8276635691918d4b` |

`backend/tests/test_contract_compat.py` checks the digest, so an edit to a frozen file fails
CI rather than silently changing what "the old Central" means. Its `$ref`s
(`runtime-item`, `node-tunnel-report`) resolve against the current message schemas, which
1.11.0 did not change.

What the test pins (ADR 0029 §9, plan/31/02 §6.4): a `node.register` carrying
`binary_preview` is **rejected** by a 1.10.0 Central (so the forward order must be Central
first, then daemons), and a disabled 1.11 daemon, which **omits** the key, is **accepted**
(so rolling Central back is possible after disabling the switch).

The frozen 1.9.0 bytes remain available for historical checks. The compatibility test
derives the 1.10.0 surface in memory by adding only `file_download`, so the rollback
claim is specifically about a Central that already supports #71.
