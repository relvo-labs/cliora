"""The filter allowlist and its six refusals (PX-23, plan/26/04 §5).

No database: `compile_filter` is a function from a request model to a clause plus a list
of derived terms. What is asserted here is the part that decides whether a caller can be
told what they did wrong — every refusal has to **name the field or the operator** and
say what was available instead, because an error that only says "invalid filter" is one
the reader fixes by guessing.
"""

from __future__ import annotations

import uuid

import pytest

from app.api.errors import ApiError
from app.services.tasks import PRIORITIES, RISKS
from app.services.work.filters import (
    _PRIORITY_ORDER,
    _RISK_ORDER,
    DERIVED_FIELDS,
    FIELDS,
    MAX_SEARCH_LENGTH,
    MAX_TERMS,
    MAX_VALUES,
    FilterNode,
    compile_filter,
    compile_order,
    matches,
    search_clause,
    split_attention_terms,
)


def node(payload: dict) -> FilterNode:
    return FilterNode.model_validate(payload)


def _raises(payload: dict) -> ApiError:
    with pytest.raises(ApiError) as raised:
        compile_filter(node(payload))
    return raised.value


# --- the six negative cases -------------------------------------------------------


def test_an_unknown_field_names_itself_and_lists_the_alternatives() -> None:
    error = _raises({"field": "assignee", "op": "eq", "value": "x"})
    assert error.code == "FILTER_FIELD_NOT_ALLOWED"
    assert error.details["field"] == "assignee"
    assert "owner" in error.details["allowed_fields"]


def test_a_disallowed_operator_lists_the_ones_that_are_allowed() -> None:
    """`allowed_ops` is the point of this error.

    What the reader has to do is pick a different operator, and telling them which ones
    exist saves the round trip to the documentation — the same reasoning
    `_smallest_missing_tags` uses in `services/runs.py`.
    """
    error = _raises({"field": "lifecycle", "op": "contains", "value": "x"})
    assert error.code == "FILTER_OP_NOT_ALLOWED"
    assert error.details == {
        "field": "lifecycle",
        "op": "contains",
        "allowed_ops": list(FIELDS["lifecycle"].ops),
    }
    assert error.details["allowed_ops"]


def test_contains_belongs_only_to_the_label_array() -> None:
    assert _raises({"field": "risk", "op": "contains", "value": "x"}).code == (
        "FILTER_OP_NOT_ALLOWED"
    )
    # And it is the *only* operator that field has: equality against a JSONB array would
    # mean "asks for exactly these tags", which nobody wants to express.
    assert FIELDS["required_labels"].ops == ("contains",)


def test_depth_four_is_refused_and_says_which_limit() -> None:
    deep = {"and": [{"or": [{"and": [{"field": "risk", "op": "eq", "value": "high"}]}]}]}
    error = _raises(deep)
    assert error.code == "FILTER_TOO_COMPLEX"
    assert error.details["limit"] == "depth"


def test_twenty_one_leaf_conditions_are_refused() -> None:
    payload = {
        "and": [{"field": "risk", "op": "eq", "value": "high"} for _ in range(MAX_TERMS + 1)]
    }
    error = _raises(payload)
    assert error.code == "FILTER_TOO_COMPLEX"
    assert error.details == {"limit": "terms", "actual": MAX_TERMS + 1, "maximum": MAX_TERMS}


def test_a_list_of_fifty_one_values_is_refused() -> None:
    payload = {
        "field": "owner",
        "op": "in",
        "value": [str(uuid.uuid4()) for _ in range(MAX_VALUES + 1)],
    }
    error = _raises(payload)
    assert error.code == "FILTER_TOO_COMPLEX"
    assert error.details["limit"] == "values"


# --- values are a different kind of problem from fields ----------------------------


def test_a_bad_value_is_a_validation_error_not_a_field_error() -> None:
    """A malformed uuid is a problem with the value.

    Calling it `FILTER_FIELD_NOT_ALLOWED` would send the reader to change a field name
    that was correct (plan/26/04 §3).
    """
    error = _raises({"field": "owner", "op": "eq", "value": "not-a-uuid"})
    assert error.code == "INVALID_QUERY"
    assert error.status_code == 422
    assert error.details["field"] == "owner"


def test_an_enum_value_outside_the_set_is_refused() -> None:
    error = _raises({"field": "lifecycle", "op": "eq", "value": "shipping"})
    assert error.code == "INVALID_QUERY"


# --- `@me` -------------------------------------------------------------------------


def test_at_me_expands_per_request_not_per_view() -> None:
    """A shared view storing `@me` shows **each reader** their own cards.

    Bound at compile time it would be the author's cards forever, for everybody — which
    is why the substitution happens during validation of each request (plan/26/04 §7).
    """
    first, second = uuid.uuid4(), uuid.uuid4()
    payload = {"field": "owner", "op": "eq", "value": "@me"}
    one = str(
        compile_filter(node(payload), actor_id=first).sql.compile(
            compile_kwargs={"literal_binds": True}
        )
    )
    two = str(
        compile_filter(node(payload), actor_id=second).sql.compile(
            compile_kwargs={"literal_binds": True}
        )
    )
    # `.hex`, not `str()`: SQLAlchemy renders a bound uuid without dashes under
    # `literal_binds`.
    assert first.hex in one
    assert second.hex in two
    assert one != two


def test_at_me_expands_inside_a_list_too() -> None:
    actor = uuid.uuid4()
    compiled = compile_filter(
        node({"field": "owner", "op": "in", "value": ["@me"]}), actor_id=actor
    )
    assert actor.hex in str(compiled.sql.compile(compile_kwargs={"literal_binds": True}))


# --- the two-phase field ----------------------------------------------------------


def test_only_attention_readiness_and_execution_are_derived() -> None:
    """Everything else is a column comparison, and that is the claim worth pinning.

    `lifecycle` in particular is **not** derived at query time: it maps onto
    `tasks.stage` values, so it stays an `IN` that `ix_tasks_project_stage` serves.
    """
    assert DERIVED_FIELDS == {"attention", "readiness", "execution_status"}


@pytest.mark.parametrize(
    ("levels", "sql_half", "runtime_half"),
    [
        (["run_failed"], ("run_failed",), ()),
        (["no_eligible_runner"], (), ("no_eligible_runner",)),
        (
            ["run_failed", "assigned_runner_offline"],
            ("run_failed",),
            ("assigned_runner_offline",),
        ),
        ([], (), ()),
    ],
    ids=["sql-only", "runtime-only", "mixed", "empty"],
)
def test_the_attention_split_is_one_function(
    levels: list[str], sql_half: tuple[str, ...], runtime_half: tuple[str, ...]
) -> None:
    """The one place in the compiler where SQL is not the whole answer.

    Isolated into a function so that a reader auditing "where does this query stop being
    a query" has one place to look.
    """
    assert split_attention_terms("in", levels) == (sql_half, runtime_half)


def test_a_runtime_attention_filter_reports_that_it_needs_the_registry() -> None:
    compiled = compile_filter(
        node({"field": "attention", "op": "eq", "value": "no_eligible_runner"})
    )
    assert compiled.needs_runtime is True
    assert compiled.has_derived is True


def test_a_sql_attention_filter_does_not_need_the_registry() -> None:
    compiled = compile_filter(node({"field": "attention", "op": "eq", "value": "run_failed"}))
    assert compiled.needs_runtime is False
    assert compiled.has_derived is True


def test_attention_is_matched_against_the_whole_signal_set() -> None:
    """Not only the primary.

    "Cards where a run failed" means cards where that is true, not cards where it happens
    to be the most urgent thing. The primary is a presentation decision (D107); the
    filter is a question about facts.
    """
    compiled = compile_filter(node({"field": "attention", "op": "eq", "value": "run_failed"}))
    assert matches(
        compiled,
        lifecycle="in_progress",
        readiness="ready",
        execution="failed",
        attention_signals=("waiting_for_your_input", "run_failed"),
    )
    assert not matches(
        compiled,
        lifecycle="in_progress",
        readiness="ready",
        execution="failed",
        attention_signals=("waiting_for_your_input",),
    )


def test_a_negated_derived_term_excludes_rather_than_requires() -> None:
    compiled = compile_filter(node({"field": "readiness", "op": "neq", "value": "draft"}))
    assert matches(
        compiled,
        lifecycle="ready",
        readiness="ready",
        execution="not_queued",
        attention_signals=(),
    )
    assert not matches(
        compiled,
        lifecycle="ready",
        readiness="draft",
        execution="not_queued",
        attention_signals=(),
    )


# --- ordering ----------------------------------------------------------------------


def test_the_default_order_is_rank_ascending() -> None:
    assert compile_order(None) == [("rank", False)]


def test_attention_is_not_sortable() -> None:
    """Two of its eight levels are not in SQL (D92).

    An ordering that is *mostly* right is harder to debug than none, and the product
    answer is to group by attention instead — grouping happens within a page.
    """
    with pytest.raises(ApiError) as raised:
        compile_order("attention:desc")
    assert raised.value.code == "FILTER_FIELD_NOT_ALLOWED"
    assert "rank" in raised.value.details["allowed_fields"]


def test_three_sort_levels_are_refused() -> None:
    with pytest.raises(ApiError) as raised:
        compile_order("rank:asc,updated_at:desc,title:asc")
    assert raised.value.details["limit"] == "order"


def test_the_semantic_orders_cover_their_value_sets() -> None:
    """`priority` and `risk` sort by meaning, not alphabetically.

    "high" < "low" < "normal" is nonsense on a screen. This pins the CASE tables against
    the frozensets in `services/tasks.py`, so adding a value there without ranking it
    here fails rather than silently sorting last.
    """
    assert set(_PRIORITY_ORDER) == PRIORITIES
    assert set(_RISK_ORDER) == RISKS


# --- shape -------------------------------------------------------------------------


def test_an_empty_filter_matches_everything() -> None:
    compiled = compile_filter(None)
    assert compiled.derived_terms == ()
    assert not compiled.has_derived


def test_an_empty_conjunction_is_unfiltered_rather_than_an_error() -> None:
    """A view whose filter is `{"and": []}` means unfiltered, which is what an empty
    conjunction means anyway."""
    assert compile_filter(node({"and": []})).derived_terms == ()


def test_there_is_no_not_node() -> None:
    """`neq` and `not_in` cover the need.

    A `not` node would turn "does this filter exclude resources the caller may not see"
    into a question requiring recursive reasoning.
    """
    assert "not" not in FilterNode.model_fields
    assert "not_" not in FilterNode.model_fields


# --- `q=` search (PX-31) --------------------------------------------------------------
#
# Search is a **parameter of its own**, not a sixteenth field. `search_clause`'s docstring
# says why; these tests pin the two things that would silently go wrong.


def test_a_search_folds_into_the_same_compiled_filter() -> None:
    """One object, so counts and items cannot apply different halves.

    The alternative — a second parameter both endpoints pass to the query builder — is
    exactly the shape `CompiledFilter` exists to prevent: two places to remember, and the
    failure of forgetting one is a header that disagrees with the list below it.
    """
    plain = compile_filter(FilterNode.model_validate({}))
    searched = compile_filter(FilterNode.model_validate({}), search="月報")
    assert str(plain.sql) != str(searched.sql)
    assert "lower" in str(searched.sql).lower() or "ilike" in str(searched.sql).lower()
    # And the derived half is untouched: search is SQL, always.
    assert searched.derived_terms == ()


def test_a_search_matches_the_title_or_the_card_reference_and_nothing_else() -> None:
    rendered = str(compile_filter(None, search="月報").sql)
    assert "tasks.title" in rendered
    assert "tasks.card_ref" in rendered
    # Not the description. A description search sounds free and is a sequential scan of
    # the largest column on the table, matching text nobody was looking at.
    assert "tasks.description" not in rendered


@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
def test_a_blank_search_is_no_search(blank: str) -> None:
    """`?q=%20` and no `q` are the same board.

    Asserted through `search_clause` returning `None` rather than through the rendered
    SQL: the point is that the clause is left out of the `AND` entirely, and an `AND true`
    would pass a string comparison while adding noise to every query plan.
    """
    assert search_clause(blank) is None
    assert search_clause(None) is None


def test_the_like_metacharacters_are_escaped_not_stripped() -> None:
    """A search for `100%` finds `100%`, not everything.

    Stripping them would be the other plausible fix and it is worse: a person searching
    for `100%` would silently get the results for `100`, which looks like it worked.
    """
    rendered = str(compile_filter(None, search="100%_x").sql)
    # The pattern travels as a bind parameter, so what is asserted is the escape clause
    # being present at all — without it the `%` is a wildcard whatever the value says.
    assert "ESCAPE" in rendered.upper()
    clause = search_clause("100%_x")
    assert clause is not None


def test_a_search_longer_than_the_limit_is_refused_by_name() -> None:
    with pytest.raises(ApiError) as raised:
        search_clause("x" * (MAX_SEARCH_LENGTH + 1))
    assert raised.value.status_code == 400
    assert raised.value.details["maximum"] == MAX_SEARCH_LENGTH


def test_search_is_not_a_filter_field() -> None:
    """The allowlist still has fifteen names, and none of them is free text.

    This is the test that would have failed if search had been added as a field, which is
    the tempting shape: it would have put one unconstrained value inside the structure
    whose whole property is that its values are constrained.
    """
    assert "q" not in FIELDS
    assert "search" not in FIELDS
    assert "title" not in FIELDS
    for name, spec in FIELDS.items():
        assert spec.kind in {"enum", "uuid", "bool", "timestamp", "labels"}, name
