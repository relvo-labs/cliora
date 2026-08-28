"""Lexical hybrid retrieval against a real PostgreSQL (`KN-07`, `FR-KNOW-004`/`-008`).

Two groups. The **relevance** group is the fixed query set that `KN-13` turns into a
baseline — including the one query that is expected to miss, because D40's accepted cost
has to be measured rather than assumed. The **isolation** group is eight assertions that
one project cannot see another's, and one of them is about a count rather than a list:
an unauthorised search must return zero results *and* a zero total, because a non-zero
total discloses that something is there.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
import sqlalchemy as sa

from app.api.errors import ApiError
from app.clock import now_utc
from app.db.models import (
    Epic,
    Project,
    Role,
    Task,
    TaskDependency,
    TaskKnowledgePin,
    User,
)
from app.security.passwords import hash_password
from app.services.knowledge.outbox import invalidate_enabled_cache
from app.services.knowledge.search import KnowledgeSearch
from app.services.knowledge.store import ExtractedSource, KnowledgeStore

pytestmark = pytest.mark.asyncio


async def _project(session, *, knowledge: bool = True) -> Project:
    role = (await session.execute(sa.select(Role).where(Role.name == "Admin"))).scalar_one()
    name = f"kn-{uuid.uuid4().hex[:8]}"
    user = User(
        id=uuid.uuid4(),
        username=name,
        display_name=name,
        password_hash=hash_password("pw-12345678"),
        role_id=role.id,
    )
    session.add(user)
    await session.flush()
    project = Project(
        id=uuid.uuid4(), name=name, slug=name, owner_user_id=user.id, knowledge_enabled=knowledge
    )
    session.add(project)
    await session.flush()
    invalidate_enabled_cache()
    return project


async def _put(
    session,
    project: Project,
    *,
    external_id: str,
    title: str,
    text: str,
    authority: str = "discussion",
    source_type: str = "ticket",
    age_days: float = 0.0,
    version: str = "v1",
) -> uuid.UUID:
    when = now_utc() - timedelta(days=age_days)
    result = await KnowledgeStore(session).upsert(
        project_id=project.id,
        source_type=source_type,
        source=ExtractedSource(
            external_id=external_id,
            version=version,
            authority=authority,
            title=title,
            text=text,
            occurred_at=when,
            source_updated_at=when,
        ),
    )
    await session.flush()
    return result.source_id


async def _titles(session, project, query: str, **kwargs) -> list[str]:
    result = await KnowledgeSearch(session, project.id).search(query, **kwargs)
    return [hit.title for hit in result.items]


# --- the fixed query set (`KN-13` turns these into a baseline) ---------------


async def test_an_exact_card_reference_is_found(session):
    project = await _project(session)
    await _put(
        session,
        project,
        external_id="task:1",
        title="續跑的設計",
        text="這一段延續 CV-05 的 answer 與 resume 交易。",
    )
    await _put(session, project, external_id="task:2", title="別的卡", text="無關的內容")
    assert await _titles(session, project, "CV-05") == ["續跑的設計"]


async def test_a_title_only_match_is_found(session):
    """**The title is indexed, at weight A** (ADR 0038 §4).

    This test exists because it did not pass. The first implementation indexed only the
    chunk body, so a card called "租約過期時要怎麼處理" whose description never repeated
    the phrase was unfindable by it — and every unit test passed, because each of them
    happened to put the search term in the body too. `KN-13`'s fixed query set is what
    caught it: two of eight queries returned nothing against a realistic corpus.
    """
    project = await _project(session)
    await _put(
        session,
        project,
        external_id="task:1",
        title="租約過期時要怎麼處理",
        text="lease_expires_at 到期之後 sweep 會把 run 收成 lost。",
    )
    assert await _titles(session, project, "租約過期") == ["租約過期時要怎麼處理"]


async def test_a_title_match_outranks_a_body_match(session):
    """Weight A over weight B: a document *called* this beats one that mentions it."""
    project = await _project(session)
    await _put(
        session,
        project,
        external_id="task:1",
        title="無關的標題",
        text="順帶一提，租約過期也會發生。" * 3,
    )
    await _put(session, project, external_id="task:2", title="租約過期的處理", text="細節在別處。")
    assert (await _titles(session, project, "租約過期"))[0] == "租約過期的處理"


async def test_a_symbol_is_found(session):
    project = await _project(session)
    await _put(
        session,
        project,
        external_id="task:1",
        title="租約",
        text="lease_expires_at 到期後 sweep 會把 run 收成 lost。",
    )
    assert await _titles(session, project, "lease_expires_at") == ["租約"]


async def test_a_typo_still_finds_it_through_the_trigram_channel(session):
    project = await _project(session)
    await _put(session, project, external_id="task:1", title="租約", text="lease_expires_at 到期")
    assert await _titles(session, project, "lease_expire_at") == ["租約"]


async def test_a_short_query_is_found_inside_a_realistically_long_chunk(session):
    """The trigram channel's actual job, at the size chunks actually are.

    **Every other trigram test on this page passes with a broken channel**, and that is
    the finding rather than an aside. They store bodies of about twenty characters, where
    `similarity(content, query)` — a *whole-string* comparison — is high because the two
    strings are nearly the same length. A real chunk is up to 800 tokens
    (`chunking.py::DEFAULT_CHUNK_TOKENS`), and the same comparison then measures a short
    query against a long paragraph: measured at **0.05** for a chunk that contains the
    query verbatim, against a floor of 0.25.

    So the channel returned **nothing** for exactly the queries its docstring names — a
    SHA, a function name, a typo — while costing 131 ms at 20,000 chunks, because the GIN
    index offered every row as a candidate and the recheck threw all of them away.
    Found by `HD-10`'s scale measurement (`plan/27` §2.10), not by this suite.

    `<%` compares the query against the best-matching *extent* of the content, which is
    the question that was always being asked. This test differs from its neighbours in
    one way only: the body is long.
    """
    project = await _project(session)
    filler = (
        "這一段描述執行器在壓力下的租約續期行為，涉及重試策略與游標分頁，"
        "並記錄了驗證流程與權限矩陣之間的相依鏈。" * 8
    )
    await _put(
        session,
        project,
        external_id="repo:long",
        title="docs/adr/0029.md",
        text=f"{filler} 相關識別碼是 139f143c9a2b，後續由下一期承接。 {filler}",
        source_type="repo_doc",
        authority="canonical",
    )
    assert len(f"{filler} x {filler}") > 400, "the point of this test is a long body"
    # **A typo, not the exact token.** Querying `139f143c9a2b` verbatim proves nothing:
    # the tokenizer indexes it as a lexeme, so the FTS channel answers and the trigram
    # channel could be returning zero rows without anybody noticing. That is precisely
    # how this defect survived — the first version of this very test passed against the
    # broken code. `139f143c9a2d` is one character off, which no lexeme matches.
    assert await _titles(session, project, "139f143c9a2d") == ["docs/adr/0029.md"]


async def test_a_commit_sha_is_found(session):
    project = await _project(session)
    await _put(
        session,
        project,
        external_id="repo:1",
        title="docs/adr/0035.md",
        text="這個決定在 139f143 落地。",
        source_type="repo_doc",
        authority="canonical",
    )
    assert await _titles(session, project, "139f143") == ["docs/adr/0035.md"]


async def test_a_chinese_phrase_is_found(session):
    """The one that does not work without the tokenizer. Without CJK bigrams this
    query matches nothing at all, and nothing raises."""
    project = await _project(session)
    await _put(
        session,
        project,
        external_id="task:1",
        title="逾時處理",
        text="租約過期時，掃描會把這個 run 標成 lost 並重新排隊。",
    )
    await _put(session, project, external_id="task:2", title="無關", text="完全不同的主題")
    assert await _titles(session, project, "租約過期") == ["逾時處理"]


async def test_a_semantically_close_query_with_different_wording_misses(session):
    """**D40's accepted cost, asserted rather than assumed.**

    "怎麼處理逾時" does not share a bigram with "租約過期" beyond the coincidental, so
    lexical retrieval will not reliably connect them. This test exists so the cost has a
    number in `KN-13`'s baseline, and so that the day a vector channel is added there is
    a control group. It is **not** a bug report.
    """
    project = await _project(session)
    await _put(
        session,
        project,
        external_id="task:1",
        title="lease expiry",
        text="When the lease expires the sweep marks the run lost.",
    )
    assert await _titles(session, project, "怎麼處理逾時") == []


async def test_accepted_outranks_generated_for_the_same_words(session):
    project = await _project(session)
    await _put(
        session,
        project,
        external_id="spec:1",
        title="已接受的規格",
        text="驗證由平台執行，Agent 不自行宣稱通過。",
        authority="accepted",
        source_type="decision",
    )
    await _put(
        session,
        project,
        external_id="task:9",
        title="Agent 的提案",
        text="驗證由平台執行，Agent 不自行宣稱通過。",
        authority="generated",
    )
    assert (await _titles(session, project, "驗證"))[0] == "已接受的規格"


async def test_an_old_charter_still_ranks_because_freshness_has_a_floor(session):
    """Old is not the same as wrong. Without the floor a three-year-old charter sinks
    below yesterday's passing remark."""
    project = await _project(session)
    await _put(
        session,
        project,
        external_id=f"project:{project.id}",
        title="專案章程",
        text="交付一律走 PR，不直接推 main。",
        authority="authoritative",
        source_type="policy",
        age_days=1100,
    )
    await _put(
        session,
        project,
        external_id="task:1",
        title="今天的留言",
        text="交付一律走 PR，不直接推 main。",
        authority="discussion",
        age_days=0,
    )
    assert (await _titles(session, project, "交付"))[0] == "專案章程"


# --- history, pins and the graph --------------------------------------------


async def test_a_superseded_source_is_absent_by_default_and_present_with_history(session):
    project = await _project(session)
    await _put(
        session, project, external_id="task:1", title="v1", text="租約過期的舊說法", version="v1"
    )
    await _put(
        session,
        project,
        external_id="task:1",
        title="v2",
        text="租約過期的新說法",
        version="v2",
        age_days=-1,
    )
    assert await _titles(session, project, "租約過期") == ["v2"]
    with_history = await _titles(session, project, "租約過期", include_history=True)
    assert sorted(with_history) == ["v1", "v2"]
    result = await KnowledgeSearch(session, project.id).search("租約過期", include_history=True)
    assert {hit.title: hit.historical for hit in result.items} == {"v1": True, "v2": False}


async def test_a_pinned_source_always_enters_the_top_result(session):
    """A pin a score can displace is not a pin."""
    project = await _project(session)
    task = Task(id=uuid.uuid4(), project_id=project.id, card_ref="KN-1", title="卡")
    session.add(task)
    await session.flush()
    strong = await _put(
        session, project, external_id="task:9", title="字面最相關", text="租約過期 租約過期"
    )
    weak = await _put(session, project, external_id="task:8", title="人指定的", text="租約過期一次")
    assert (await _titles(session, project, "租約過期", task_id=task.id))[0] == "字面最相關"

    session.add(TaskKnowledgePin(task_id=task.id, source_id=weak, mode="pin"))
    await session.flush()
    assert (await _titles(session, project, "租約過期", task_id=task.id))[0] == "人指定的"
    assert strong is not None


async def test_an_excluded_source_is_hidden_for_that_card_only(session):
    """Exclusion is per card and reversible; a tombstone is project-wide and is not.
    Merging them would mean one person excluding a document on one card silently
    removed it from the other forty."""
    project = await _project(session)
    first = Task(id=uuid.uuid4(), project_id=project.id, card_ref="KN-1", title="一")
    second = Task(id=uuid.uuid4(), project_id=project.id, card_ref="KN-2", title="二")
    session.add_all([first, second])
    await session.flush()
    source_id = await _put(session, project, external_id="task:9", title="文件", text="租約過期")
    session.add(TaskKnowledgePin(task_id=first.id, source_id=source_id, mode="exclude"))
    await session.flush()

    assert await _titles(session, project, "租約過期", task_id=first.id) == []
    assert await _titles(session, project, "租約過期", task_id=second.id) == ["文件"]


async def test_a_dependency_neighbour_is_boosted_and_says_so(session):
    project = await _project(session)
    upstream = Task(id=uuid.uuid4(), project_id=project.id, card_ref="KN-1", title="前置")
    current = Task(id=uuid.uuid4(), project_id=project.id, card_ref="KN-2", title="目前")
    session.add_all([upstream, current])
    await session.flush()
    session.add(TaskDependency(task_id=current.id, depends_on_task_id=upstream.id))
    await session.flush()
    await _put(
        session, project, external_id=f"task:{upstream.id}", title="前置的內容", text="租約過期"
    )
    await _put(session, project, external_id="task:zzz", title="無關的卡", text="租約過期")

    result = await KnowledgeSearch(session, project.id).search("租約過期", task_id=current.id)
    top = result.items[0]
    assert top.title == "前置的內容"
    assert "graph:dependency" in top.why


async def test_the_same_epic_is_a_weaker_boost_than_a_dependency(session):
    project = await _project(session)
    epic = Epic(id=uuid.uuid4(), project_id=project.id, card_ref="EP-1", title="史詩")
    session.add(epic)
    await session.flush()
    sibling = Task(
        id=uuid.uuid4(), project_id=project.id, epic_id=epic.id, card_ref="KN-1", title="兄弟"
    )
    current = Task(
        id=uuid.uuid4(), project_id=project.id, epic_id=epic.id, card_ref="KN-2", title="目前"
    )
    session.add_all([sibling, current])
    await session.flush()
    await _put(
        session, project, external_id=f"task:{sibling.id}", title="兄弟的內容", text="租約過期"
    )
    result = await KnowledgeSearch(session, project.id).search("租約過期", task_id=current.id)
    assert "graph:same_epic" in result.items[0].why


async def test_why_is_populated_for_every_hit(session):
    """The line that makes retrieval auditable. A hit with no explanation is the black
    box the Knowledge page exists to open."""
    project = await _project(session)
    await _put(session, project, external_id="task:1", title="文件", text="租約過期")
    result = await KnowledgeSearch(session, project.id).search("租約過期")
    assert result.items and all(hit.why for hit in result.items)


# --- degradation -------------------------------------------------------------


async def test_a_single_character_query_reports_its_degraded_channel(session):
    """Silently returning nothing would read as "this project has nothing about that"."""
    project = await _project(session)
    await _put(session, project, external_id="task:1", title="文件", text="租約過期時")
    result = await KnowledgeSearch(session, project.id).search("期")
    assert result.degraded == "single_token"
    assert "fts" not in result.channels


# --- isolation (SR-2's main evidence) ----------------------------------------


async def test_items_are_scoped_to_one_project(session):
    a = await _project(session)
    b = await _project(session)
    await _put(session, a, external_id="task:1", title="A 的文件", text="租約過期")
    await _put(session, b, external_id="task:1", title="B 的文件", text="租約過期")
    assert await _titles(session, a, "租約過期") == ["A 的文件"]
    assert await _titles(session, b, "租約過期") == ["B 的文件"]


async def test_the_count_is_zero_too_not_only_the_list(session):
    """A non-zero total with an empty list would disclose that something is there."""
    a = await _project(session)
    b = await _project(session)
    await _put(session, b, external_id="task:1", title="B 的文件", text="租約過期")
    result = await KnowledgeSearch(session, a.id).search("租約過期")
    assert result.items == []
    assert result.total == 0


async def test_a_pin_cannot_reach_another_projects_source(session):
    a = await _project(session)
    b = await _project(session)
    task = Task(id=uuid.uuid4(), project_id=a.id, card_ref="KN-1", title="卡")
    session.add(task)
    await session.flush()
    other = await _put(session, b, external_id="task:9", title="B 的文件", text="租約過期")
    session.add(TaskKnowledgePin(task_id=task.id, source_id=other, mode="pin"))
    await session.flush()
    assert await _titles(session, a, "租約過期", task_id=task.id) == []


async def test_a_graph_neighbour_from_another_project_is_ignored(session):
    a = await _project(session)
    b = await _project(session)
    task = Task(id=uuid.uuid4(), project_id=b.id, card_ref="KN-1", title="別的專案的卡")
    session.add(task)
    await session.flush()
    await _put(session, a, external_id="task:1", title="A 的文件", text="租約過期")
    # Searching project A while naming project B's card: the card is not this project's,
    # so it contributes no boost and — critically — leaks nothing about itself.
    result = await KnowledgeSearch(session, a.id).search("租約過期", task_id=task.id)
    assert [hit.title for hit in result.items] == ["A 的文件"]
    assert all("graph:" not in reason for hit in result.items for reason in hit.why)


async def test_a_disabled_project_refuses_with_404(session):
    project = await _project(session, knowledge=False)
    with pytest.raises(ApiError) as raised:
        await KnowledgeSearch(session, project.id).search("租約過期")
    assert raised.value.code == "KNOWLEDGE_DISABLED"
    assert raised.value.status_code == 404


async def test_a_tombstoned_source_is_gone_from_search(session):
    project = await _project(session)
    await _put(session, project, external_id="task:1", title="文件", text="租約過期")
    await KnowledgeStore(session).tombstone(
        project_id=project.id, source_type="ticket", external_ids=["task:1"]
    )
    await session.flush()
    assert await _titles(session, project, "租約過期") == []
    # Not even with history: a tombstone says the original is gone, which is a stronger
    # statement than "an older version exists".
    assert await _titles(session, project, "租約過期", include_history=True) == []


async def test_there_is_no_module_level_result_cache(session):
    """`alpha.3` adds no retrieval cache, and that is a decision rather than an omission.

    The honest form of "the cache does not leak across projects" in a release with no
    cache is an assertion that none exists — so that whoever adds one is reminded to
    bring an isolation suite with it.
    """
    import app.services.knowledge.search as module

    allowed = {"_CHANNEL_WEIGHTS", "_AUTHORITY_WEIGHT", "_HALF_LIFE_DAYS", "__builtins__"}
    suspicious = [
        name
        for name, value in vars(module).items()
        if isinstance(value, dict) and value and name not in allowed
    ]
    assert suspicious == [], f"module-level mutable state that could cache results: {suspicious}"
