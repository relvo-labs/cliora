# Daemon 0.8.1 — upgraded nodes start again (#159)

**0.8.0 does not start on a node installed before 0.8.0.** Installers up to 0.7.x
wrote `sandbox_bypass: null` into every runtime block of `/etc/agentd/config.yaml`
(the field had no `omitempty`), and 0.8.0 rejected a null `sandbox_bypass`:

```
error: parse config: runtime sandbox_bypass must not be null; use true or false, or migrate to permission_mode
```

0.8.1 reads a null legacy `sandbox_bypass` as absent again, exactly as 0.7.x did,
including next to `permission_mode`. A null `permission_mode` is still an error.
Everything else in [the 0.8.0 release note](release-note-daemon-0.8.0.md) applies.

## A node stuck on 0.8.0

`agentd update` parses the config before doing anything, so it fails with the same
error. Unblock the node by hand, then update:

1. In `/etc/agentd/config.yaml`, delete every `sandbox_bypass: null` line (any
   runtime block). Keep `permission_mode` only under `codex`.
2. `sudo systemctl restart agentd`, then `agentd doctor` as the service user.
3. `sudo agentd update --version 0.8.1`.

## Doctor and sudo

Run `agentd doctor` as the service user. Under `sudo`, its `non-root` check reports
FAIL because doctor itself is then root; that line says nothing about the service.
