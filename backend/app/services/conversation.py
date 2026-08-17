"""The card's conversation: sequence numbers, questions, answers and continuation.

This module is the durable half of V2-C1 (`FR-CONV-001`…`-010`, ADR 0035/0036/0037).
V2.5 already had a message thread; what it did not have was a thread an execution can
be *resumed from*. Three properties are the difference, and each is one paragraph
because each is the reason a specific class of bug cannot happen here.

**A number, not a timestamp.** Every message takes ``tasks.conversation_seq + 1`` in
the transaction that inserts it, so the sequence is monotonic, gapless and unique per
card. Timestamp pagination lost or repeated a row whenever two messages shared a
``created_at``; a cursor over this sequence cannot.

**A row, not a scan.** A question is a ``task_questions`` row with four states, so
"has this been answered" is a single-statement compare-and-set rather than a search
for a later message by a user. Zero rows affected is the conflict and one row is the
go-ahead — the same shape, and the same argument, as ``runs.claim()``.

**One transaction, not two calls.** Answering closes the question, writes the message
and enqueues the continuation together. Split apart, "the answer is saved but no turn
was created" is a real state, and on screen it is indistinguishable from "the agent
has not replied yet" — so the person waits, sends it again, and now there are two
turns.

`GATE-CV-PROJECTION-ONE-WRITER` asserts that ``_reproject`` is the only place that
assigns ``tasks.waiting_for_actor`` and ``tasks.open_question_count``. A second writer
would not raise anything; it would show a card that says "waiting for your reply"
after the reply arrived.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Literal

from fastapi import status
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import metrics
from app.api.errors import ApiError
from app.clock import now_utc
from app.db.models import (
    ConversationConsumer,
    Task,
    TaskMessage,
    TaskQuestion,
    TaskRun,
)
from app.services.activity import (
    ACTOR_AGENT,
    ACTOR_SYSTEM,
    ACTOR_USER,
    TASK_MESSAGE_POSTED,
    ActivityService,
)

# --- the vocabulary -------------------------------------------------------

KIND_COMMENT = "comment"
KIND_QUESTION = "question"
KIND_ANSWER = "answer"
KIND_PROPOSAL = "proposal"
KIND_DECISION = "decision"
KIND_SYSTEM = "system"

#: What V2.5 wrote, and what V2-C1 calls it. **Applied on read only** — no migration
#: rewrites the stored values (ADR 0035 §8), because a whole-table `UPDATE` on a table
#: `audit_logs` references, to change a display string, is the worse trade.
LEGACY_KIND_READ = {"message": KIND_COMMENT, "event": KIND_SYSTEM}
#: The same pair applied on the way **in**. Three call sites and one CLI still send the
#: V2.5 spellings; normalising here rather than at each of them is what makes the
#: database hold one vocabulary from this release on, without a migration that rewrites
#: rows `audit_logs` references (ADR 0035 §8).
LEGACY_KIND_WRITE = {"message": KIND_COMMENT, "event": KIND_SYSTEM}

#: A person may write these four. `proposal` is an agent's word for "here is a draft";
#: a person editing a draft is editing the specification, not narrating one.
WRITABLE_BY_HUMAN = frozenset({KIND_COMMENT, KIND_QUESTION, KIND_ANSWER, KIND_DECISION})
#: A runner may write these four. **`decision` is deliberately absent** — see
#: `assert_kind_writable`, and ADR 0037 §2 for why the check exists at all when the
#: authorization layer already refuses it.
WRITABLE_BY_RUNNER = frozenset({KIND_COMMENT, KIND_QUESTION, KIND_ANSWER, KIND_PROPOSAL})
#: `system` is in neither set. `post_event` is the only writer, and it is not reachable
#: from either HTTP surface.

QUESTION_OPEN = "open"
QUESTION_ANSWERED = "answered"
QUESTION_CANCELLED = "cancelled"
QUESTION_EXPIRED = "expired"

WAITING_HUMAN = "human"
WAITING_AGENT = "agent"

#: Refused at 20000 characters with a machine code rather than by Pydantic's
#: `max_length`, because a 422 carries no code and a client cannot tell "too long"
#: — whose correct interface is *your text is safe, shorten it* — from any other
#: validation failure (ADR 0041 §3).
MESSAGE_BODY_LIMIT = 20_000

#: Runs whose conversation is still live in the old sense: the agent process is up and
#: polling. `_resume` treats these differently from a run that has ended (ADR 0035 §7).
_LIVE_WAITING = "waiting_for_input"
_TERMINAL_STATUSES = ("succeeded", "failed", "cancelled")

#: What `finish()` writes as `result` when a completing run left a question open.
#: A Central-derived `result` has precedent: `delivery_incomplete` is one.
RESULT_AWAITING_INPUT = "awaiting_input"


def read_kind(stored: str) -> str:
    """The one place the legacy spellings are translated."""
    return LEGACY_KIND_READ.get(stored, stored)


@dataclass(frozen=True, slots=True)
class MessagePage:
    items: list[TaskMessage]
    next_after_seq: int | None
    has_more: bool


@dataclass(frozen=True, slots=True)
class AnswerResult:
    message: TaskMessage
    question: TaskQuestion
    #: ``new_turn`` a continuation run was created · ``live_run`` the asking run is
    #: still up and will read the answer by polling · ``no_run`` the question had no
    #: run behind it · ``refused`` the card cannot be dispatched right now, and the
    #: reason is on the card · ``none`` the caller did not ask to resume.
    mode: Literal["new_turn", "live_run", "no_run", "refused", "none"]
    continuation_run_id: uuid.UUID | None
    #: Set when ``mode`` is ``refused``: the machine code that stopped the continuation.
    refusal_code: str | None = None
    #: True when an idempotency key replayed an earlier answer. The route answers 200
    #: instead of 201.
    replayed: bool = False


class ConversationService:
    """Everything that reads or writes a card's conversation."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._activity = ActivityService(session)

    # --- reading ----------------------------------------------------------

    async def page(
        self,
        task: Task,
        *,
        after_seq: int | None = None,
        before_seq: int | None = None,
        limit: int = 200,
    ) -> MessagePage:
        """One page of the thread, forwards from ``after_seq`` or back from ``before_seq``.

        A cursor beyond the card's own sequence is refused rather than answered with an
        empty page: the caller's state is broken, and an empty page leaves it broken
        for ever with nothing to notice (ADR 0036 §2).
        """
        if after_seq is not None and before_seq is not None:
            raise ApiError(
                "INVALID_ARGUMENT",
                "Give either after_seq or before_seq, not both",
                status.HTTP_400_BAD_REQUEST,
            )
        if after_seq is not None and after_seq > task.conversation_seq:
            raise self._cursor_ahead(task, after_seq)

        query = select(TaskMessage).where(TaskMessage.task_id == task.id)
        if after_seq is not None:
            query = query.where(TaskMessage.conversation_seq > after_seq)
            query = query.order_by(TaskMessage.conversation_seq).limit(limit + 1)
            rows = list((await self._session.execute(query)).scalars())
            has_more = len(rows) > limit
            rows = rows[:limit]
        else:
            if before_seq is not None:
                query = query.where(TaskMessage.conversation_seq < before_seq)
            query = query.order_by(TaskMessage.conversation_seq.desc()).limit(limit + 1)
            rows = list((await self._session.execute(query)).scalars())
            has_more = len(rows) > limit
            rows = list(reversed(rows[:limit]))
        return MessagePage(
            items=rows,
            next_after_seq=rows[-1].conversation_seq if rows else after_seq,
            has_more=has_more,
        )

    def _cursor_ahead(self, task: Task, cursor: int) -> ApiError:
        return ApiError(
            "CONVERSATION_CURSOR_AHEAD",
            "That cursor is ahead of this card's conversation",
            status.HTTP_409_CONFLICT,
            details={"cursor": cursor, "conversation_seq": task.conversation_seq},
        )

    async def open_questions(self, task_id: uuid.UUID) -> list[TaskQuestion]:
        return list(
            (
                await self._session.execute(
                    select(TaskQuestion)
                    .where(
                        TaskQuestion.task_id == task_id,
                        TaskQuestion.state == QUESTION_OPEN,
                    )
                    .order_by(TaskQuestion.created_at)
                )
            ).scalars()
        )

    async def questions_for(
        self, task_id: uuid.UUID, *, state: str | None = None
    ) -> list[TaskQuestion]:
        query = select(TaskQuestion).where(TaskQuestion.task_id == task_id)
        if state is not None:
            query = query.where(TaskQuestion.state == state)
        return list(
            (await self._session.execute(query.order_by(TaskQuestion.created_at))).scalars()
        )

    async def require_question(self, task: Task, question_id: uuid.UUID) -> TaskQuestion:
        question = await self._session.get(TaskQuestion, question_id)
        # A question belonging to another card is reported as absent rather than as
        # forbidden: "not here" is true and says nothing about what exists elsewhere.
        if question is None or question.task_id != task.id:
            raise ApiError("QUESTION_NOT_FOUND", "Question not found", status.HTTP_404_NOT_FOUND)
        return question

    async def pending_question_for_run(self, run_id: uuid.UUID) -> TaskQuestion | None:
        """This run's unanswered question, if it has one (ADR 0034 §4, re-homed).

        V2.5 answered this by scanning messages. The rule it encoded is preserved in
        the `0040` backfill; from here on the answer is a row, so it is one index hit
        on a partial index rather than a correlated subquery over the thread.
        """
        return (
            await self._session.execute(
                select(TaskQuestion)
                .where(TaskQuestion.run_id == run_id, TaskQuestion.state == QUESTION_OPEN)
                .order_by(TaskQuestion.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    async def by_idempotency_key(self, task_id: uuid.UUID, key: str) -> TaskMessage | None:
        return (
            await self._session.execute(
                select(TaskMessage).where(
                    TaskMessage.task_id == task_id, TaskMessage.idempotency_key == key
                )
            )
        ).scalar_one_or_none()

    # --- writing ----------------------------------------------------------

    def assert_kind_writable(self, kind: str, *, author_kind: str) -> None:
        """Which actor may write which kind (ADR 0037 §2).

        The `decision` refusal is the load-bearing one, and it is deliberately
        redundant: `task.approve` is not in `RUN_TOKEN_SCOPES`, so an agent's attempt
        would already fail at the authorization layer. What the explicit check adds is
        a legible code instead of a generic 403, and an audit row instead of silence —
        **a refusal nobody records is a refusal nobody can review.**
        """
        allowed = WRITABLE_BY_HUMAN if author_kind == ACTOR_USER else WRITABLE_BY_RUNNER
        if kind in allowed:
            return
        if kind == KIND_DECISION and author_kind == ACTOR_AGENT:
            raise ApiError(
                "AGENT_CANNOT_DECIDE",
                "An agent may propose; deciding is a person's action",
                status.HTTP_403_FORBIDDEN,
                details={"kind": kind},
            )
        raise ApiError(
            "INVALID_ARGUMENT",
            "Unknown message kind",
            status.HTTP_400_BAD_REQUEST,
            details={"kind": kind, "allowed": sorted(allowed)},
        )

    async def next_seq(self, task_id: uuid.UUID) -> int:
        """Take the card's next message number (ADR 0035 §2).

        The `UPDATE` takes a row lock on the card — a row this write was going to touch
        anyway, because `tasks.updated_at` has `onupdate` — so two writers to one card
        serialise and two writers to different cards do not meet.
        """
        row = await self._session.execute(
            update(Task)
            .where(Task.id == task_id)
            .values(conversation_seq=Task.conversation_seq + 1)
            .returning(Task.conversation_seq)
        )
        return int(row.scalar_one())

    async def post(
        self,
        *,
        task: Task,
        body: str,
        kind: str = KIND_COMMENT,
        author_kind: str = ACTOR_USER,
        author_user_id: uuid.UUID | None = None,
        author_runner_id: uuid.UUID | None = None,
        run_id: uuid.UUID | None = None,
        event_kind: str | None = None,
        reply_to_message_id: uuid.UUID | None = None,
        question_id: uuid.UUID | None = None,
        idempotency_key: str | None = None,
    ) -> tuple[TaskMessage, bool]:
        """Write one message. Returns ``(message, replayed)``.

        ``replayed`` is true when an idempotency key matched an existing message with
        identical content; the route answers 200 rather than 201, because a retry that
        reports "created" twice teaches a client to distrust the code it gets.
        """
        kind = LEGACY_KIND_WRITE.get(kind, kind)
        if author_kind in (ACTOR_USER, ACTOR_AGENT):
            self.assert_kind_writable(kind, author_kind=author_kind)
        if not body.strip():
            raise ApiError("INVALID_ARGUMENT", "Message body is empty", status.HTTP_400_BAD_REQUEST)
        if len(body) > MESSAGE_BODY_LIMIT:
            raise ApiError(
                "MESSAGE_TOO_LARGE",
                "That message is longer than a card message may be",
                status.HTTP_400_BAD_REQUEST,
                details={"limit": MESSAGE_BODY_LIMIT, "length": len(body)},
            )
        if reply_to_message_id is not None:
            await self._assert_same_card(task, reply_to_message_id)
        if kind == KIND_QUESTION and author_kind == ACTOR_AGENT and run_id is not None:
            await self._require_no_pending_question(run_id)

        if idempotency_key is not None:
            existing = await self.by_idempotency_key(task.id, idempotency_key)
            if existing is not None:
                return self._replay(existing, body, kind, reply_to_message_id), True

        message = TaskMessage(
            id=uuid.uuid4(),
            task_id=task.id,
            run_id=run_id,
            author_kind=author_kind,
            author_user_id=author_user_id,
            author_runner_id=author_runner_id,
            body=body,
            kind=kind,
            event_kind=event_kind,
            conversation_seq=await self.next_seq(task.id),
            reply_to_message_id=reply_to_message_id,
            question_id=question_id,
            idempotency_key=idempotency_key,
        )
        self._session.add(message)
        try:
            await self._session.flush()
        except IntegrityError as exc:  # pragma: no cover - exercised by the race test
            # Two requests with one key arrived together. The index decided; this side
            # reads the winner. A pre-check alone would have double-written.
            if idempotency_key is None or "uq_task_messages_idem" not in str(exc.orig):
                raise
            await self._session.rollback()
            existing = await self.by_idempotency_key(task.id, idempotency_key)
            if existing is None:
                raise
            return self._replay(existing, body, kind, reply_to_message_id), True

        if kind == KIND_QUESTION:
            self._session.add(
                TaskQuestion(
                    id=uuid.uuid4(),
                    task_id=task.id,
                    run_id=run_id,
                    asked_message_id=message.id,
                    state=QUESTION_OPEN,
                )
            )
            await self._session.flush()
            await self._reproject(task)
        elif author_kind == ACTOR_USER and kind != KIND_ANSWER:
            await self._close_questions_a_live_run_is_waiting_on(task, message)

        metrics.increment(metrics.CONVERSATION_MESSAGES_TOTAL, kind=kind, type=author_kind)
        if author_kind in (ACTOR_USER, ACTOR_AGENT):
            # System events are not put on the timeline from here — they already *are*
            # activity, and a second row would double every one of them.
            await self._activity.record(
                TASK_MESSAGE_POSTED,
                project_id=task.project_id,
                task_id=task.id,
                actor_user_id=author_user_id,
                actor_kind=author_kind,
                # Metadata only. The body stays on the card (ADR 0037 §5).
                payload={
                    "card_ref": task.card_ref,
                    "kind": kind,
                    "conversation_seq": message.conversation_seq,
                },
            )
        return message, False

    def _replay(
        self,
        existing: TaskMessage,
        body: str,
        kind: str,
        reply_to_message_id: uuid.UUID | None,
    ) -> TaskMessage:
        same = (
            existing.body == body
            and existing.kind == kind
            and existing.reply_to_message_id == reply_to_message_id
        )
        if same:
            return existing
        raise ApiError(
            "MESSAGE_IDEMPOTENCY_CONFLICT",
            "That idempotency key was used for a different message",
            status.HTTP_409_CONFLICT,
            details={"conversation_seq": existing.conversation_seq},
        )

    async def post_event(self, *, task: Task, body: str, event_kind: str) -> TaskMessage:
        message, _ = await self.post(
            task=task,
            body=body,
            kind=KIND_SYSTEM,
            author_kind=ACTOR_SYSTEM,
            event_kind=event_kind,
        )
        return message

    async def _close_questions_a_live_run_is_waiting_on(
        self, task: Task, message: TaskMessage
    ) -> None:
        """A plain reply closes an open question **only while the asking run is up**.

        This is the one place V2-C1 keeps V2.5's rule rather than replacing it, and the
        reason is a trap that only appears when you run the old tests against the new
        model.

        V2.5 counted *any* later user message as the answer, so an agent was never
        blocked by a person who replied without pressing a particular button. Requiring
        an explicit answer would restore linkage and lose that: a person types "sure, go
        ahead" as an ordinary comment, and the agent — still running, still polling —
        may never ask anything again.

        So a comment closes the question when the asking run is still ``waiting_for_input``:
        that agent will read the reply on its next poll, which is exactly what used to
        happen. **It does not create a continuation turn** — that remains the answer
        endpoint's job, and it is what "留言 is not 回覆並繼續" means.

        When the asking run has already **ended**, the question stays open. Closing it
        would leave a card that looks idle while nobody is working on it and no turn is
        coming, which is worse than a card that still says a question is waiting.
        """
        open_questions = await self.open_questions(task.id)
        closed = False
        for question in open_questions:
            if question.run_id is None:
                continue
            run = await self._session.get(TaskRun, question.run_id)
            if run is None or run.status != _LIVE_WAITING:
                continue
            question.state = QUESTION_ANSWERED
            question.answered_at = now_utc()
            question.answered_message_id = message.id
            closed = True
        if closed:
            await self._session.flush()
            await self._reproject(task)

    async def _assert_same_card(self, task: Task, message_id: uuid.UUID) -> None:
        target = await self._session.get(TaskMessage, message_id)
        # A reply that crosses cards would put the thread outside the boundary
        # permissions are judged on, so it is refused rather than normalised.
        if target is None or target.task_id != task.id:
            raise ApiError(
                "INVALID_ARGUMENT",
                "The message being replied to is not on this card",
                status.HTTP_400_BAD_REQUEST,
                details={"reply_to_message_id": str(message_id)},
            )

    async def _require_no_pending_question(self, run_id: uuid.UUID) -> None:
        pending = await self.pending_question_for_run(run_id)
        if pending is None:
            return
        asked = await self._session.get(TaskMessage, pending.asked_message_id)
        # The refusal offers a way out because there is a real one: two *related*
        # sub-questions in one message are allowed. What this prevents is five
        # independent questions at once, which in practice returns three answers and
        # two the agent cannot tell were skipped.
        raise ApiError(
            "QUESTION_ALREADY_PENDING",
            "上一個問題還沒有人回覆，所以這一題被擋下來了。"
            "把兩個問題合併成一則，或先等這一題有回覆。",
            status.HTTP_409_CONFLICT,
            details={
                "pending_question": asked.body if asked is not None else "",
                "asked_at": pending.created_at.isoformat(),
                "question_id": str(pending.id),
            },
        )

    # --- answering, and the continuation it may create --------------------

    async def answer(
        self,
        *,
        task: Task,
        question_id: uuid.UUID,
        body: str,
        actor_user_id: uuid.UUID,
        resume: bool = True,
        idempotency_key: str | None = None,
    ) -> AnswerResult:
        """Close a question, record the answer, and start the next turn — atomically.

        The order is fixed. The compare-and-set comes first because every step after it
        costs something, and the request that loses the race should find that out
        before spending it.
        """
        question = await self.require_question(task, question_id)

        # The one deliberate read-before-write in this module. Not for correctness —
        # losing this race lands on `QUESTION_ALREADY_ANSWERED`, whose details carry
        # the existing answer, and the caller recovers from there. It is here because
        # "your retry returned the original result" is a better answer than "your retry
        # conflicted", and only a pre-check can give it.
        if idempotency_key is not None:
            existing = await self.by_idempotency_key(task.id, idempotency_key)
            if existing is not None and existing.question_id == question_id:
                run_id = existing.turn_run_id if existing.turn_run_id is not None else None
                return AnswerResult(
                    message=existing,
                    question=question,
                    mode="new_turn" if run_id else "none",
                    continuation_run_id=run_id,
                    replayed=True,
                )

        closed = await self._session.execute(
            update(TaskQuestion)
            .where(
                TaskQuestion.id == question_id,
                TaskQuestion.task_id == task.id,
                TaskQuestion.state == QUESTION_OPEN,
            )
            .values(state=QUESTION_ANSWERED, answered_at=now_utc())
            .returning(TaskQuestion.run_id)
        )
        if closed.first() is None:
            raise await self._explain_cas_failure(question)

        message, _ = await self.post(
            task=task,
            body=body,
            kind=KIND_ANSWER,
            author_kind=ACTOR_USER,
            author_user_id=actor_user_id,
            reply_to_message_id=question.asked_message_id,
            question_id=question_id,
            idempotency_key=idempotency_key,
        )
        await self._session.execute(
            update(TaskQuestion)
            .where(TaskQuestion.id == question_id)
            .values(answered_message_id=message.id)
        )
        await self._session.refresh(question)

        mode: Literal["new_turn", "live_run", "no_run", "refused", "none"] = "none"
        continuation_id: uuid.UUID | None = None
        refusal: str | None = None
        if resume:
            mode, continuation_id, refusal = await self._resume(task, question, message)
        await self._reproject(task)
        return AnswerResult(
            message=message,
            question=question,
            mode=mode,
            continuation_run_id=continuation_id,
            refusal_code=refusal,
        )

    async def _explain_cas_failure(self, question: TaskQuestion) -> ApiError:
        """Zero rows has three causes and they need three answers.

        `QUESTION_ALREADY_ANSWERED` carries who answered and when, because two people
        replying to one question is a normal event in a team — and the one who loses
        should end up reading the answer, not reading "operation failed".
        """
        await self._session.refresh(question)
        if question.state == QUESTION_ANSWERED:
            answered_by = None
            if question.answered_message_id is not None:
                answer_message = await self._session.get(TaskMessage, question.answered_message_id)
                answered_by = (
                    str(answer_message.author_user_id)
                    if answer_message is not None and answer_message.author_user_id
                    else None
                )
            return ApiError(
                "QUESTION_ALREADY_ANSWERED",
                "Somebody has already answered this question",
                status.HTTP_409_CONFLICT,
                details={
                    "answered_at": (
                        question.answered_at.isoformat() if question.answered_at else None
                    ),
                    "answered_by": answered_by,
                    "answered_message_id": (
                        str(question.answered_message_id) if question.answered_message_id else None
                    ),
                },
            )
        return ApiError(
            "QUESTION_NOT_OPEN",
            "That question is no longer open",
            status.HTTP_409_CONFLICT,
            details={"state": question.state},
        )

    async def _resume(
        self, task: Task, question: TaskQuestion, answer_message: TaskMessage
    ) -> tuple[
        Literal["new_turn", "live_run", "no_run", "refused", "none"],
        uuid.UUID | None,
        str | None,
    ]:
        """Three branches, because there are three ways a card can be waiting.

        (b) is the V2.5 shape and stays supported: the agent never exited, so it will
        read the answer on its next poll and no new run is needed. (c) is the shape
        this phase adds. Keeping both means an agent that has not changed its behaviour
        keeps working, and `_reproject` gives the board one answer either way.
        """
        from app.services.runs import RunService  # late: runs imports this module

        if question.run_id is None:
            return "no_run", None, None
        parent = await self._session.get(TaskRun, question.run_id)
        if parent is None:
            return "no_run", None, None

        if parent.status == _LIVE_WAITING:
            parent.status = "running"
            parent.waiting_since = None
            await self._session.flush()
            return "live_run", parent.id, None

        if parent.status in _TERMINAL_STATUSES:
            try:
                child = await RunService(self._session).enqueue_continuation(
                    task=task,
                    parent=parent,
                    question=question,
                    input_from_seq=parent.input_to_seq or 0,
                    input_to_seq=answer_message.conversation_seq,
                )
            except ApiError as exc:
                # The card was edited into an undispatchable state while it waited —
                # most sharply, a clarification card that gained a `required_secrets`
                # entry. **The answer stays.** What a person typed is not thrown away
                # because a setting is wrong, so the refusal is reported on the card and
                # the request still succeeds: the answer *was* recorded, and a 409 whose
                # body also says "but we saved it" is a worse thing to read.
                await self.post_event(
                    task=task,
                    body=(
                        "已收到你的回覆，但這張卡目前無法繼續執行：" + exc.message + "\n"
                        "修正之後可以重新派工。"
                    ),
                    event_kind="run.continuation_refused",
                )
                return "refused", None, exc.code
            answer_message.turn_run_id = child.id
            await self._session.flush()
            metrics.increment(metrics.CONVERSATION_TURNS_TOTAL)
            return "new_turn", child.id, None

        # queued / claimed / running with an open question: Central failed to park the
        # run when the question was asked. Refusing loudly beats papering over it —
        # this is our bug, and it should be visible.
        raise ApiError(
            "RUN_NOT_WAITING_FOR_INPUT",
            "That run is not waiting for an answer",
            status.HTTP_409_CONFLICT,
            details={"run_status": parent.status},
        )

    async def expire_question(self, question: TaskQuestion) -> None:
        """Mark a question timed out **without deleting it** (ADR 0035, FR-CONV-003.AC-03)."""
        question.state = QUESTION_EXPIRED
        question.expired_at = now_utc()
        metrics.increment(metrics.CONVERSATION_QUESTION_EXPIRED_TOTAL)
        await self._session.flush()

    # --- the projection the board reads -----------------------------------

    async def _reproject(self, task: Task) -> None:
        """The **only** writer of ``waiting_for_actor`` and ``open_question_count``.

        Derived from question state rather than from run state, which is what makes
        the two kinds of waiting — a process still polling, and a process that exited —
        produce one answer on the board (ADR 0035 §8).
        """
        open_count = int(
            (
                await self._session.execute(
                    select(func.count())
                    .select_from(TaskQuestion)
                    .where(
                        TaskQuestion.task_id == task.id,
                        TaskQuestion.state == QUESTION_OPEN,
                    )
                )
            ).scalar()
            or 0
        )
        task.open_question_count = open_count
        if open_count > 0:
            task.waiting_for_actor = WAITING_HUMAN
        elif await self._has_pending_turn(task.id):
            task.waiting_for_actor = WAITING_AGENT
        else:
            task.waiting_for_actor = None
        await self._session.flush()

    async def reproject(self, task: Task) -> None:
        """Public entry point for callers outside this module (the reaper, `finish`)."""
        await self._reproject(task)

    async def _has_pending_turn(self, task_id: uuid.UUID) -> bool:
        row = (
            await self._session.execute(
                select(TaskRun.id)
                .where(
                    TaskRun.task_id == task_id,
                    TaskRun.status.in_(("queued", "claimed", "running")),
                )
                .limit(1)
            )
        ).first()
        return row is not None

    # --- consumer cursors -------------------------------------------------

    async def consumer(
        self, task_id: uuid.UUID, *, consumer_type: str, consumer_id: uuid.UUID
    ) -> ConversationConsumer:
        row = await self._session.get(ConversationConsumer, (task_id, consumer_type, consumer_id))
        if row is None:
            row = ConversationConsumer(
                task_id=task_id, consumer_type=consumer_type, consumer_id=consumer_id
            )
            self._session.add(row)
            await self._session.flush()
        return row

    async def mark_delivered(
        self, task_id: uuid.UUID, *, consumer_type: str, consumer_id: uuid.UUID, seq: int
    ) -> ConversationConsumer:
        row = await self.consumer(task_id, consumer_type=consumer_type, consumer_id=consumer_id)
        if seq > row.last_delivered_seq:
            row.last_delivered_seq = seq
            await self._session.flush()
        return row

    async def mark_acked(
        self, task: Task, *, consumer_type: str, consumer_id: uuid.UUID, seq: int
    ) -> ConversationConsumer:
        """Advance the acknowledgement cursor. **This controls nothing** (ADR 0036 §2)."""
        if seq > task.conversation_seq:
            raise self._cursor_ahead(task, seq)
        row = await self.consumer(task.id, consumer_type=consumer_type, consumer_id=consumer_id)
        if seq > row.last_delivered_seq:
            row.last_delivered_seq = seq
        if seq > row.last_acked_seq:
            row.last_acked_seq = seq
        await self._session.flush()
        return row

    async def acked_seq_for_task(self, task_id: uuid.UUID) -> int:
        """The furthest any consumer has acknowledged — what the UI shows as `agent_seen`."""
        value = (
            await self._session.execute(
                select(func.max(ConversationConsumer.last_acked_seq)).where(
                    ConversationConsumer.task_id == task_id
                )
            )
        ).scalar()
        return int(value or 0)


def message_metadata(message: TaskMessage) -> dict[str, Any]:
    """Audit payload for one message: what happened, never what was said."""
    return {
        "message_id": str(message.id),
        "kind": read_kind(message.kind),
        "conversation_seq": message.conversation_seq,
    }
