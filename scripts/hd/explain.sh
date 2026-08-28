#!/usr/bin/env bash
# HD-10: `EXPLAIN (ANALYZE, BUFFERS)` for the six hot queries, on 2000 cards.
#
#   CLIORA_DATABASE_URL=… scripts/hd/explain.sh
#
# **Every output gets a one-line conclusion written beside it** (`plan/27/06` §3). An
# `EXPLAIN` plan nobody has summarised is a file nobody re-reads: the question is "did it
# use the index, or did it scan", and that answer should not require re-reading a plan
# three months later.
#
# The queries are written out here rather than captured from the service layer, and that
# is a real limitation stated plainly: what is measured is the *shape* the read model
# issues, not the statement SQLAlchemy emits for a particular filter. The service-level
# timings in `measure-*.py` are the other half.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

OUT="artifacts/hd/local/w5/explain"
mkdir -p "$OUT"

DATASET="artifacts/hd/local/large-dataset.json"
if [ ! -f "$DATASET" ]; then
  echo "no $DATASET — run scripts/hd/seed-large.py first" >&2
  exit 2
fi
PROJECT="$(python3 -c "import json;print(json.load(open('$DATASET'))['project_id'])")"

# **The dataset file can be stale, and a stale one measures an empty project.**
# `seed-large.py` deletes and recreates its project on every run, so the id changes; a
# `explain.sh` that trusted the JSON without checking would report seven plans over zero
# rows, all fast, all meaningless — and every one of them would say "index used".
# It happened once. This is the check that makes it say so instead.
rows="$(docker exec -i cliora-pg psql -U cliora -d "${PGDATABASE:-cliora_hd}" -tAc \
  "SELECT count(*) FROM tasks WHERE project_id = '$PROJECT'" 2>/dev/null | tr -d ' ')"
if [ "${rows:-0}" -lt 100 ]; then
  echo "project $PROJECT has ${rows:-0} tasks — $DATASET is stale." >&2
  echo "re-run: uv run --project backend python scripts/hd/seed-large.py" >&2
  exit 2
fi

# `psql` against the container rather than through the async driver: `EXPLAIN ANALYZE`
# output is a text artifact, and routing it through SQLAlchemy would add a layer that
# reformats it.
psql() { docker exec -i cliora-pg psql -U cliora -d "${PGDATABASE:-cliora_hd}" "$@"; }

# `$5` is an optional statement run **before** the EXPLAIN in the same session. It exists
# for one caller: `%` reads `pg_trgm.similarity_threshold` from the session, and `EXPLAIN`
# does not accept a `SET` in front of the statement it explains.
run() {
  local slug="$1" title="$2" conclusion_hint="$3" sql="$4" pre="${5:-}"
  printf '\n=== %s\n' "$title"
  {
    printf '%% %s\n%% project = %s\n%% dataset = 2000 cards, 20000 chunks, 200-deep chain\n\n' \
      "$title" "$PROJECT"
    printf '%s\n\n' "$sql"
  } > "$OUT/$slug.txt"
  if psql -qAt ${pre:+-c "$pre"} -c "EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) $sql" \
      >> "$OUT/$slug.txt" 2>&1; then
    # The conclusion, derived rather than asserted: whether a sequential scan appears at
    # all is the fact worth recording, and it is mechanical to read off.
    local verdict
    # **A sequential scan is only a finding on a table big enough for it to matter.**
    # `task_dependencies` is 201 rows in 7 pages; the planner reading it whole is correct
    # and reporting that as a problem trains a reader to skip the conclusions.
    if grep -qE 'Seq Scan on (tasks|knowledge_chunks|knowledge_sources) ' "$OUT/$slug.txt"; then
      verdict="SEQ SCAN — $conclusion_hint"
    else
      used="$(grep -oE 'using [a-z_]+' "$OUT/$slug.txt" | sed 's/using //' | sort -u | tr '\n' ' ')"
      verdict="index used — ${used:-planner chose a scan over a small table, which is correct}"
    fi
    local ms
    ms="$(grep -oE 'Execution Time: [0-9.]+' "$OUT/$slug.txt" | tail -1 | grep -oE '[0-9.]+')"
    printf '%% CONCLUSION: %s\n%% Execution Time: %s ms\n' "$verdict" "${ms:-?}" >> "$OUT/$slug.txt"
    printf '  %-7s ms   %s\n' "${ms:-?}" "$verdict"
    printf '%s\t%s\t%s\n' "$slug" "${ms:-?}" "$verdict" >> "$OUT/summary.tsv"
  else
    printf '  FAILED — see %s\n' "$OUT/$slug.txt"
    printf '%s\t-\tFAILED\n' "$slug" >> "$OUT/summary.tsv"
  fi
}

: > "$OUT/summary.tsv"
echo "seven hot queries on 2000 cards among 20000 (project $PROJECT)"

# 1. The board's first page. `ix_tasks_project_rank` is what `0043` added for it.
run board-page "work-items, no filter, first page" \
  "rank is VARCHAR(64); a seq scan here means the B-tree is not being used for the order" \
  "SELECT id, card_ref, title, stage, rank, updated_at FROM tasks
   WHERE project_id = '$PROJECT' ORDER BY rank, id LIMIT 50"

# 2. Three predicates, the shape the filter compiler produces.
run board-filtered "work-items with a three-clause filter" \
  "the compiler emits ordinary WHERE clauses; a scan means no composite index covers them" \
  "SELECT id, card_ref, title FROM tasks
   WHERE project_id = '$PROJECT' AND stage = 'ready' AND risk = 'high' AND priority <> 'low'
   ORDER BY rank LIMIT 50"

# 3. **The hottest endpoint in the phase** — polled every 20 s by every open board tab.
run work-counts "work-counts, grouped by stage" \
  "counts read every row that matches; the index that matters is (project_id, stage)" \
  "SELECT stage, count(*) FROM tasks WHERE project_id = '$PROJECT' GROUP BY stage"

# 4. The 200-deep chain — the one dimension the fixture scales non-proportionally.
run blocking-counts "blocking_counts() over a 200-deep chain" \
  "an edge walk; the join order is what decides whether depth costs anything" \
  "SELECT d.task_id, count(*) FROM task_dependencies d
   JOIN tasks blocker ON blocker.id = d.depends_on_task_id
   JOIN tasks t ON t.id = d.task_id
   WHERE t.project_id = '$PROJECT' AND blocker.stage <> 'done'
   GROUP BY d.task_id"

# 5 and 5b. The two retrieval channels, **measured separately, because that is how
# `search.py` issues them**.
#
# The first version of this script put them in one `WHERE … OR …`, and PostgreSQL
# answered with a full scan of `knowledge_chunks` at 12.5 ms — an `OR` across two
# different indexes cannot use either. That looked like a finding about the schema and
# was a finding about the test: `KnowledgeSearch` runs two selects and merges in Python
# (`search.py:293` and `:310`), precisely so each one keeps its index.
#
# **Left in the record rather than quietly corrected**, because "the measurement was
# written in a shape the product does not use" is the failure mode a benchmark suite has,
# and it produced a plausible number that would have been quoted.
#
# The **search term** was the second version of the same mistake. `make check` is in every
# seeded chunk, so both channels matched 20,000 of 20,000 rows: the FTS plan was a
# sequential scan (correct — an index cannot help when everything matches) and the
# trigram plan spent 100 ms computing `similarity()` over the whole table. Neither number
# said anything about the index. `HD-1234` appears in roughly ten chunks, which is what a
# real query looks like.
run knowledge-fts "knowledge search — FTS channel, 20000 chunks" \
  "ix_knowledge_chunks_fts; this channel is the one CJK bigrams go through" \
  "SELECT c.id, ts_rank(c.search_document, plainto_tsquery('simple', 'HD-1234')) AS r
   FROM knowledge_chunks c
   WHERE c.project_id = '$PROJECT'
     AND c.search_document @@ plainto_tsquery('simple', 'HD-1234')
   ORDER BY r DESC LIMIT 20"

# `SET` first, because `%` reads `pg_trgm.similarity_threshold` from the session and
# `search.py:48` sets it on the connection rather than writing `similarity() > x` — a
# comparison cannot use the GIN index and the operator can.
# `<%` and `word_similarity`, matching `search.py` after `HD-10`'s fix. The `%` form this
# replaced returned **zero rows in 131 ms** on this dataset: whole-string similarity
# between a short query and a long chunk is ~0.05, so nothing cleared the floor while the
# GIN index still offered every row as a candidate. That is the finding this script was
# written to be capable of producing, and it produced it.
run knowledge-trgm "knowledge search — trigram channel, 20000 chunks" \
  "ix_knowledge_chunks_trgm; <% rather than word_similarity() > x, which cannot use it" \
  "SELECT c.id, word_similarity('HD-1234', c.content) AS r
   FROM knowledge_chunks c
   WHERE c.project_id = '$PROJECT' AND 'HD-1234' <% c.content
   ORDER BY r DESC LIMIT 20" \
  "SET pg_trgm.word_similarity_threshold = 0.6"

# 6. The worker's claim. `uq_knowledge_jobs_pending` is a partial unique index.
run job-claim "knowledge_jobs claim, FOR UPDATE SKIP LOCKED" \
  "the partial index on state='pending'; a scan means the queue is being read whole" \
  "SELECT id FROM knowledge_jobs WHERE state = 'pending'
   ORDER BY created_at LIMIT 32 FOR UPDATE SKIP LOCKED"

echo
echo "written to $OUT (summary.tsv, and one .txt per query with its conclusion appended)"
