"""iter97 — Server-Sent Events live stream.

`GET /api/live/stream` → text/event-stream

Every logged-in user (Bearer OR session cookie) opens ONE connection
and receives a live push whenever:

  * rates_updated   — any admin created / edited / deleted a rate
  * order_status_changed — one of *their* orders was approved / rejected / completed
  * balance_updated — their VIP or company balance changed

The endpoint keeps the socket alive with a `:heartbeat` comment every
20 seconds so proxies (nginx / cloudflare / k8s ingress) don't idle-kill
the connection.  The client-side `useLiveStream` hook auto-reconnects
with exponential back-off if the socket drops.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, AsyncGenerator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from auth_utils import require_user, get_session_user, _enforce_staff_active
from services.live_bus import event_iterator, subscribe, unsubscribe

log = logging.getLogger("live_stream")
router = APIRouter(prefix="/live", tags=["Live"])


HEARTBEAT_INTERVAL = 20  # seconds

# STAFF-06 (auditoría 26-10-2026) — una suscripción SSE sella el rol en el
# momento de conectar y los feeds restringidos por rol (ledger_changed, soporte,
# solicitudes de empresa) se entregaban a ese rol para siempre. Revalidamos la
# sesión/rol/estado de cuenta periódicamente: si el rol cambió, la cuenta de
# staff se suspendió o la sesión se invalidó (reset de contraseña / logout),
# cerramos el stream para que el cliente reconecte y vuelva a autorizarse.
REAUTH_INTERVAL = 30  # seconds


def _sse_frame(event: str, payload: dict) -> str:
    """Build one wire-format SSE frame."""
    body = json.dumps(payload, default=str, ensure_ascii=False)
    return f"event: {event}\ndata: {body}\n\n"


@router.get("/stream")
async def live_stream(request: Request) -> Any:
    user = await require_user(request)
    # STAFF-05/06 — una cuenta de staff suspendida o en revisión no abre feed.
    _enforce_staff_active(user)
    user_id = user["user_id"]

    sub = await subscribe(user_id, role=user.get("role"))

    async def gen() -> AsyncGenerator[str, None]:
        # Immediate hello so the client's `onopen` fires even before the
        # first real event lands.
        yield _sse_frame("hello", {"user_id": user_id, "version": "iter97"})
        heartbeat_task = None
        stream_task = None

        heartbeat_queue: asyncio.Queue[str] = asyncio.Queue()

        async def _heartbeat_loop() -> None:
            while True:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                # SSE comments (starting with `:`) are ignored by the
                # client but keep the TCP + HTTP proxy alive.
                await heartbeat_queue.put(":heartbeat\n\n")

        async def _stream_loop() -> None:
            async for ev in event_iterator(sub):
                await heartbeat_queue.put(_sse_frame(ev["type"], ev["data"]))

        try:
            heartbeat_task = asyncio.create_task(_heartbeat_loop())
            stream_task = asyncio.create_task(_stream_loop())

            last_reauth = time.monotonic()
            while True:
                if await request.is_disconnected():
                    break
                # STAFF-06 — revalidación periódica de sesión/rol/estado.
                now = time.monotonic()
                if now - last_reauth >= REAUTH_INTERVAL:
                    last_reauth = now
                    fresh = await get_session_user(request)
                    if fresh is None:
                        break  # sesión revocada / reset de contraseña / logout
                    if (fresh.get("role") or None) != (sub.role or None):
                        break  # rol cambió → reconecta y re-sella el rol
                    if fresh.get("role") in ("admin", "employee") and \
                            (fresh.get("account_status") or "active") != "active":
                        break  # staff suspendido en caliente
                try:
                    chunk = await asyncio.wait_for(
                        heartbeat_queue.get(), timeout=HEARTBEAT_INTERVAL + 5,
                    )
                    yield chunk
                except asyncio.TimeoutError:
                    # Nothing came in that window (rare) — still emit a
                    # heartbeat so the connection stays warm.
                    yield ":heartbeat\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            if heartbeat_task:
                heartbeat_task.cancel()
            if stream_task:
                stream_task.cancel()
            await unsubscribe(sub)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # tell nginx not to buffer
        },
    )
