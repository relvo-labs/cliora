"""ASGI send/receive ordering for the binary preview success audit."""

from collections.abc import Awaitable, Callable

import pytest
from starlette.types import Message, Receive, Scope, Send

from app.api.middleware import (
    BinaryPreviewCompletion,
    BinaryPreviewCompletionMiddleware,
    set_binary_preview_completion,
)


@pytest.mark.parametrize("disconnect_before_final", [True, False])
async def test_success_audit_follows_accepted_final_byte(disconnect_before_final: bool) -> None:
    audits = 0
    delivered = bytearray()
    disconnected = False

    async def audit() -> None:
        nonlocal audits
        audits += 1

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        set_binary_preview_completion(scope, BinaryPreviewCompletion(size=4, audit=audit))
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ab", "more_body": True})
        if disconnect_before_final:
            assert (await receive())["type"] == "http.disconnect"
        await send({"type": "http.response.body", "body": b"cd", "more_body": False})
        if not disconnect_before_final:
            assert (await receive())["type"] == "http.disconnect"

    async def receive() -> Message:
        nonlocal disconnected
        disconnected = True
        return {"type": "http.disconnect"}

    async def send(message: Message) -> None:
        if message["type"] == "http.response.body" and not disconnected:
            delivered.extend(message.get("body", b""))
        # Uvicorn 0.35.0 returns normally after disconnect without writing.

    middleware: Callable[[Scope, Receive, Send], Awaitable[None]] = (
        BinaryPreviewCompletionMiddleware(app)
    )
    await middleware({"type": "http"}, receive, send)

    assert delivered == (b"ab" if disconnect_before_final else b"abcd")
    assert audits == (0 if disconnect_before_final else 1)
