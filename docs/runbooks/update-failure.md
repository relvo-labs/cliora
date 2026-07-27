# Runbook — daemon update failure

**Alerts:** `ClioraDaemonUpdateFailed` (critical)
**Drill:** `scripts/p4/drills/update-failure.sh`

Applies to `agentd update` and to the "Update" action in the Cliora console.
Owner: whoever operates the node. Related: ADR 0017, `plan/05/05-daemon-release-and-update.md`.

---

## 1. Symptom, and the question everyone asks first: are the sessions gone?

**No.** A daemon update does not touch a running CLI session, and it cannot.

The tmux server is a separate process owned by the node's run user; the daemon
merely attaches to it. Restarting `agentd` therefore detaches the terminal stream
and nothing else — Claude and Codex keep running, and their scrollback is intact.

What a user sees during the ~2-5 seconds of restart:

| | |
|---|---|
| Terminal view | Disconnects, then reconnects automatically (FR-TERM-006). |
| Output produced during the gap | Preserved by tmux; delivered on reattach. If the reattach snapshot was truncated, the terminal shows an explicit `terminal.gap` marker — the UI never pretends the stream was continuous. |
| Session list | Unchanged. After the restart the daemon reconciles against tmux and Central (ADR 0012). |
| Node status | Briefly `offline`, then `online` once the daemon re-registers. |

An update that **rolls back** is the same story: the previous binary starts and
reconciles against the same tmux sessions.

The only way to lose a session is to kill the tmux server or reboot the host.
Neither is part of an update.

---

## 2. Immediate impact, and how to read the outcome

Every update ends in one of three states. The distinction that matters is whether
the previous binary is back in place.

| Status | Meaning | Action |
|---|---|---|
| `succeeded` | New version installed, service active, `doctor` passed. | None. |
| `rolled_back` | Something failed; **the previous binary was restored and restarted**. The node is running the version it was running before. | Diagnose at leisure (§3). No outage. |
| `failed` | Refused before anything was replaced (most cases), **or** the rollback itself did not restore the previous binary. | Check which — §4 if the message mentions the rollback. |

The console shows this on the node detail page (`Current / Latest / Status`), and it
is in the audit trail as `daemon.update_started` and `daemon.update_result`. On the
node:

```sh
sudo agentd version --json
sudo journalctl -u agentd -n 100 --no-pager
```

---

## 3. Diagnose by stage

The reported stage says how far it got. Nothing before `swap` has touched the
installed binary.

| Stage | Error code | What happened | Fix |
|---|---|---|---|
| `manifest` | `UPDATE_NOT_ALLOWED` | The version is not an allowlisted release for this architecture, **or** this process cannot install it (see §5), **or** it is a downgrade. | Check `curl -s https://<central>/api/releases/manifest`. Publish the release, or pass `--allow-downgrade` if going backwards is intended. |
| `manifest` | `UPDATE_DOWNLOAD_FAILED` | Central was unreachable or the manifest was unreadable. | Network / TLS / Central health. Retryable. |
| `download` | `UPDATE_DOWNLOAD_FAILED` | The artifact could not be fetched. | As above. The staging directory is cleaned automatically; just retry. |
| `checksum` | `UPDATE_CHECKSUM_MISMATCH` | The downloaded file does not match the manifest digest. **Nothing was extracted or installed.** | Treat as potentially serious — see §6. |
| `swap` | `UPDATE_NOT_ALLOWED` | The archive did not contain `agentd`, the staged binary would not execute (wrong architecture?), or it reported a different version than its filename claims. The installed binary is untouched. | Re-publish the release; check the build. |
| `restart` | `UPDATE_ROLLED_BACK` | The new binary was installed but `systemctl restart` failed. | See §4; then `journalctl -u agentd`. |
| `healthcheck` | `UPDATE_HEALTHCHECK_FAILED` | The service restarted but did not become healthy within 30 s (`doctor` failed, or the unit was not active). | The new version has a real problem in this environment. Capture `agentd doctor` output and report it. |

---

## 4. If the rollback failed

This is the one case that needs hands on the box now: the node is running a binary
that failed its own health check, and no further automated step will fix it.

The updater writes a backup before replacing anything, named after the version it
holds:

```sh
ls -l /usr/local/bin/agentd.bak-*
sudo systemctl stop agentd
sudo cp /usr/local/bin/agentd.bak-<previous-version> /usr/local/bin/agentd
sudo chmod 0755 /usr/local/bin/agentd
sudo systemctl start agentd
sudo agentd doctor
```

tmux sessions survive all of this. Do **not** reboot to "clean up" — that is what
would lose them.

---

## 5. "UPDATE_NOT_ALLOWED" from the console button

Expected, and not a bug. Replacing `/usr/local/bin/agentd` and restarting the unit
require root, and the long-running daemon runs as an unprivileged user on purpose
(SEC-007). It is not given a way to escalate, so it refuses and says so rather than
half-performing the update.

There is a second reason: whoever runs `systemctl restart agentd` must not *be* the
unit being restarted, or the process dies before it can health check the new binary
or roll it back. `sudo agentd update` runs as a separate process and survives to do
both.

Run the update on the node:

```sh
sudo agentd update --version <x.y.z>
# or verify everything without replacing anything:
sudo agentd update --version <x.y.z> --dry-run
```

`--dry-run` fetches the manifest, downloads, verifies the digest and confirms the
staged binary reports the expected version — then stops. Use it to rehearse.

---

## 6. Verify recovery, and why a checksum mismatch is a security event

The digest is computed by the release build and served from `checksums.txt`. A
mismatch means the bytes served are not the bytes published. Benign causes exist (a
truncated upload, a proxy that rewrote the body), but rule out the other one:

1. Do not retry blindly.
2. Recompute on the Central host: `sha256sum <artifacts_dir>/agentd_<ver>_linux_<arch>.tar.gz` and compare with `checksums.txt`.
3. If they disagree, the file in `artifacts_dir` has been modified since publication. MVP does not sign artifacts (ADR 0017 records this and its residual risk): **write access to `artifacts_dir` is write access to every node's next binary.** Audit that directory's permissions and recent writes before publishing anything else.
4. If they agree, the corruption is in transit — check the proxy/TLS path.

The node is safe either way: the mismatch is detected before extraction, so nothing
was installed.

---

## 7. A node stuck at "in progress"

An update restarts the daemon, which drops the socket the reply was travelling on.
Central therefore treats its request timeout as "no answer yet", not as a failure —
marking it failed would report a rollback that never happened, most often for the
updates that actually succeeded.

The state settles when the restarted daemon reports its `daemon.update_result`, or
when its next registration shows the new version. If it stays `in_progress` for more
than a few minutes:

```sh
sudo systemctl status agentd
sudo agentd version
sudo journalctl -u agentd -n 200 --no-pager
```

If the node is running the target version and healthy, the update worked and only
the report was lost; the next successful registration corrects the display. If it is
running the old version, treat it as §3/§4 by stage.

---

## 8. Before a fleet upgrade

- Publish the release and confirm it appears in `GET /api/releases/manifest` with a digest for every architecture in the fleet.
- Rehearse on one node with `--dry-run`, then for real.
- Upgrade in batches. The audit trail (`daemon.update_result`, filter by `status`) and the node list's update-status column are how you find the failures.
- Roll back a batch by updating it to the previous version with `--allow-downgrade`.
