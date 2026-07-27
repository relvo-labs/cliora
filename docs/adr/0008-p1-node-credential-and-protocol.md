# ADR 0008: P1 node credential and protocol v1.2

Status: accepted (2026-07-24), amended for Ed25519 challenge-response

## Node credential

- `node_credentials` stores `node_id`, base64 raw Ed25519 `public_key`, algorithm, version, issue/revoke timestamps. Central never receives or stores the private key.
- During enrollment the daemon generates an Ed25519 keypair with the OS CSPRNG, sends only `public_key`, and writes `private_key` to `credentials.yaml` with mode `0600`.
- This is a breaking security migration: migration 0003 revokes every active legacy shared-secret credential. Existing nodes must re-enrol; there is no legacy fallback.
- On WebSocket connect Central sends `node.challenge` with a fresh 32-byte nonce and unique challenge id. The daemon signs the domain-separated bytes `cliora-node-auth-v1\n{node_id}\n{challenge_id}\n{nonce}` and returns `node.auth`. Central verifies with the stored public key, consumes the challenge in that socket flow, then returns `node.authenticated`.
- WSS with normal certificate and hostname verification remains mandatory. Nonce signatures add application-layer replay protection but do not replace TLS.
- Rotation adds a new key/version and revokes the old row. Revocation drops the live connection; disable keeps the connection but rejects new operations.

Enrollment tokens remain stored as `HMAC-SHA256(server_pepper, token)` because they are high-entropy, one-time bearer values. This hashing rule no longer applies to node identity.

## Protocol v1.2 (compatible envelope, breaking node-auth payload)

The envelope version remains `1`. `node.challenge` is added. `node.auth` changes from `{node_secret}` to `{challenge_id, signature}`. Python, Go, and TypeScript validate the same fixtures. Daemon→Central metadata frames remain strict and forbid command/argv/env injection.
