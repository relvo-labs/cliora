#!/usr/bin/env bash
# The "agent" the conversation journeys run against (`CE-02`, D70).
#
# **What this round does is decided by the conversation itself**, never by a counter on
# disk. A continuation's working directory is a *new* directory (`FR-AGENT-011`), so a
# file written last round is not there this round; and a fixed path under /tmp would let
# two journeys running against one stack read each other's state. Reading the thread has
# neither problem — and it makes every round exercise `cliora task messages`, `ask` and
# `propose-spec` for real, which is the half of `CV-08` that no test had ever run inside
# an actual run (plan/23/10 §9.1 is what that costs).
#
#   round 1  no questions yet          -> ask the first one
#   round 2  one question              -> ask the second one
#   round 3  two questions, no spec    -> propose a specification
#   round 4  changes were requested    -> propose a second version
#   later    nothing to do             -> say so, and exit 0
#
# Exit codes: 0 did something, 3 could not reach the platform (see below).
set -uo pipefail

# `--after 0` reads the whole thread on purpose. This process has no memory of the
# previous round — that it does not need one is the property the phase exists to prove.
page="$(cliora task messages --after 0 --json 2>&1)" || {
  # Distinguishable from "nothing to do" by design: a run whose CLI cannot reach Central
  # spent its life printing an outage at a platform that was answering fine, and the only
  # signal was a delivery that never arrived (plan/23/10 §9.1).
  printf 'cliora task messages failed: %s\n' "$page" >&2
  exit 3
}

read -r questions proposals changes <<<"$(python3 - "$page" <<'PY'
import json, sys

page = json.loads(sys.argv[1])
items = page.get("items", [])
questions = sum(1 for m in items if m.get("kind") == "question")
proposals = sum(1 for m in items if m.get("kind") == "proposal")
# A person asking for changes writes a `decision` whose body the panel prefixes with
# 要求修改 (ConversationPanel's `@changes` handler). Matching the prefix rather than any
# decision keeps "accepted" from looking like "please revise".
changes = sum(
    1 for m in items
    if m.get("kind") == "decision" and str(m.get("body", "")).startswith("要求修改")
)
print(questions, proposals, changes)
PY
)"

# python3 rather than jq: the stack already parses JSON with python3 everywhere, and a
# journey should not be the reason a machine needs a new package installed.

if [ "$questions" -eq 0 ]; then
  cliora task ask "這個功能要不要支援 SSO 登入？"
elif [ "$questions" -eq 1 ]; then
  cliora task ask "登入失敗時要重試幾次才鎖定帳號？"
elif [ "$proposals" -eq 0 ]; then
  cat >spec-v1.md <<'SPEC'
# 規格提案 v1

## 範圍
- SSO 登入（依第一輪的回覆）
- 失敗重試與鎖定（依第二輪的回覆）

## 驗收標準
1. 使用者可用 SSO 登入並取得與密碼登入相同的權限。
2. 連續失敗達到約定次數後鎖定，並記一筆 audit。
SPEC
  cliora task propose-spec spec-v1.md
elif [ "$changes" -gt 0 ] && [ "$proposals" -eq 1 ]; then
  cat >spec-v2.md <<'SPEC'
# 規格提案 v2

依「要求修改」調整：把鎖定時間與解鎖方式寫進驗收標準。

## 驗收標準
1. 使用者可用 SSO 登入並取得與密碼登入相同的權限。
2. 連續失敗達到約定次數後鎖定 15 分鐘，並記一筆 audit。
3. 管理者可提前解鎖，該動作本身也記 audit。
SPEC
  cliora task propose-spec spec-v2.md
else
  cliora task say "目前沒有待辦事項：問題都有答案，規格提案也在卡片上等人決定。"
fi
