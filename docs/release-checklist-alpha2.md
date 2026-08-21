# Release checklist — `v2.0.0-alpha.1` and `v2.0.0-alpha.2`

Two tags, in this order, and the order is not negotiable: `alpha.2`'s release note says
"upgrading from `v2.0.0-alpha.1`", and until that tag exists the sentence points at
nothing (`plan/24/01` D72).

Everything a machine can check is in `scripts/cv/evidence.sh`. **This file is only the
part that needs a person** — and every line of it needs one, which is why it is short.

---

## 1. Before either tag

| ☐ | Item | How |
|---|---|---|
| ☐ | The machine checks pass, with the stack | `E2E=1 scripts/cv/evidence.sh` — 8 phase gates, 3 closeout gates, 7 journeys, the 0.12.0 lifecycle, 5 measurements. It prints `all executed checks passed` or it names what failed. |
| ☐ | Read what it produced, do not just read its exit code | `artifacts/cv/local/` — in particular `compat-0120.json` (exit 16 is `MEASURED`, not `PASS`, and the release note explains why) and `conversation-perf.json`. |
| ☐ | The working tree is clean and the evidence is from this commit | `GATE-CE-EVIDENCE-FRESH` covers the second half; `git status` covers the first. |

## 2. `v2.0.0-alpha.1` — the baseline being frozen (`CE-13`)

Target `f91d9c4`, **not** HEAD. `research/03/00` §1.3: a tag that moves is a bookmark.

| ☐ | Item | How |
|---|---|---|
| ☐ | The target is still what the plan says | `git rev-parse f91d9c4` — if the intended commit changed, change the version number instead of moving the tag |
| ☐ | The suites pass **at that commit**, in a clean environment | `git worktree add /tmp/cliora-a1 f91d9c4`, its own database (`cliora_alpha1`), then `make check` and the three suites there. Keep the output. |
| ☐ | Flags all off behaves like V1 | `scripts/pj/gate-flag-off.sh`, plus one run with `CLIORA_AGENT_RUNS_ENABLED=false` |
| ☐ | Fresh install, upgrade, downgrade | `deploy/compose` once and Railway once. The downgrade assertion is the same one `GATE-CV-MIGRATION-ROUNDTRIP` makes. |
| ☐ | Known limitations are written down | `docs/release-note-requirements-and-decomposition.md` — the six from `research/03/01` §2 are already there |
| ☐ | The diverged state is stated | **ahead 64 / behind 6** of `master` as of this closeout. An alpha tag is not a claim that it merges. |
| ☐ | Annotated tag ＋ GitHub pre-release | `git tag -a v2.0.0-alpha.1 f91d9c4`, tick pre-release |

## 3. `v2.0.0-alpha.2` — this release (`CE-14`)

Three things happen together, in this order, and none of them is a formality
(`plan/24/01` D74):

| ☐ | Item | Notes |
|---|---|---|
| ☐ | **Exit conditions** | 23 from `plan/23/08` §7 plus 5 from `plan/24/08` §4.2. Status in `plan/24/10` §6. |
| ☑ | **ADR 0035 / 0036 / 0037 / 0041 → `accepted`** | Done 2026-08-21. ADR 0035's status block carries the provenance **and the ratification sentence**: the implementation landed while the ADR was `proposed`, and that is recorded as a process deviation rather than tidied away. |
| ☑ | **SR-1 signed** | `docs/security-review-v2c1.md` §6, with its provenance written into the row: it records the owner's release authorisation, **not** an independent re-review. Replace the row if your organisation needs a named independent sign-off — everything it would read is listed there. |
| ☐ | Annotated tag | On the closeout commit, not `ac3dfef`: that commit has no journeys, and the journeys are why this tag can exist. **The commit and both tags still have to be made** — the closeout session's `git add` / `git commit` / `git tag` were refused by its permission policy, so this is the one line of the plan that could not execute itself: `git add -A && git commit` then `git tag -a v2.0.0-alpha.1 f91d9c4` and `git tag -a v2.0.0-alpha.2 HEAD` |
| ☐ | Re-run the evidence **after** committing | `GATE-CE-EVIDENCE-FRESH` compares each artefact's commit against HEAD, so a commit makes the current evidence stale by design. `E2E=1 scripts/cv/evidence.sh` once more, then tag. |
| ☐ | Attach the evidence | `artifacts/cv/local/` — or point at the CI run's `alpha2-evidence` artifact |
| ☐ | **Do not push either tag, and do not open the pre-release, in the same breath** | Both publish. Tagging is reversible while it is local; a pushed tag is not. |

## 4. What is **not** in this release

| | |
|---|---|
| `v2` → `dev` | **A person decides.** Green exit conditions earn the right to propose the merge; they are not the approval, and no automation may perform it (`research/03/00` §8). |
| A release to `master` | Cut `release/*` from before the V2 series. Never `dev` as head. |
| Node upgrades being optional | They are not, for this release. See the release note's Upgrading section. |

## 5. If something here fails

The failure is the finding, and it belongs in `plan/24/10` §2 with the same shape as the
four already there: what the plan said, what actually happened, what changed as a result,
and which document has to be rewritten. **Do not tag around it.**
