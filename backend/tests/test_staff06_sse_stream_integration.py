"""STAFF-06 (auditoría) — test de INTEGRACIÓN del stream SSE HTTP real
(`routes.live.live_stream`), no solo del bus en memoria.

Comprueba el camino completo del generador de la respuesta: `hello`, entrega de
un feed OPERATIVO autorizado, REVOCACIÓN de permiso con la CONEXIÓN VIVA (se
retira en BD y el ciclo de revalidación del endpoint aplica `update_authz`), y
que el BACKLOG que transita por AMBAS colas (`sub.queue` → `heartbeat_queue`) se
DESCARTA en la compuerta de entrega final si el permiso ya no está — mientras los
eventos PERSONALES del dueño siguen fluyendo (la conexión sigue viva).

Se maneja un lector LENTO conduciendo el `body_iterator` a mano (un frame por
`__anext__`), de modo que el backlog se forma antes de que el generador lo
procese. La revocación NO es instantánea por diseño (se aplica desde el siguiente
ciclo de reauth); por eso primero se entrega un evento personal que fuerza una
iteración y deja el reauth posterior a la revocación, y recién entonces el feed
operativo revocado queda en cola y se descarta.
"""
import asyncio
import os
from datetime import datetime, timezone, timedelta

import pytest
from pymongo import MongoClient
from starlette.requests import Request

import routes.live as live_mod
from services.live_bus import publish as bus_publish

UID = "user_sse_it01"
TOKEN = "sseit_" + "a" * 40


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture
def _seed():
    db = _db()
    now = datetime.now(timezone.utc)
    db.users.delete_many({"user_id": UID})
    db.user_sessions.delete_many({"user_id": UID})
    db.users.insert_one({
        "user_id": UID, "name": "SSE IT", "role": "employee",
        "account_status": "active", "session_version": 0,
        "allowed_permissions": ["orders"], "allowed_currencies": []})
    db.user_sessions.insert_one({
        "session_token": TOKEN, "user_id": UID, "session_version": 0,
        "expires_at": (now + timedelta(days=1)).isoformat()})
    yield db
    db.users.delete_many({"user_id": UID})
    db.user_sessions.delete_many({"user_id": UID})


def _fake_request(token: str) -> Request:
    async def receive():
        # is_disconnected() cancela esta espera de inmediato → nunca "disconnect".
        await asyncio.Event().wait()
        return {"type": "http.disconnect"}

    scope = {
        "type": "http", "method": "GET", "path": "/api/live/stream",
        "scheme": "http", "server": ("test", 80), "client": ("test", 1234),
        "query_string": b"", "root_path": "",
        "headers": [(b"cookie", f"session_token={token}".encode())],
    }
    return Request(scope, receive=receive)


async def _pull(body, timeout: float = 5.0) -> str:
    frame = await asyncio.wait_for(body.__anext__(), timeout)
    return frame if isinstance(frame, str) else frame.decode()


@pytest.mark.asyncio
async def test_sse_stream_live_revocation_drops_staff_backlog(_seed, monkeypatch):
    db = _seed
    # Revalidación en cada iteración para que la revocación en BD se aplique sin
    # esperar los 30 s reales.
    monkeypatch.setattr(live_mod, "REAUTH_INTERVAL", 0.0)

    resp = await live_mod.live_stream(_fake_request(TOKEN))
    body = resp.body_iterator
    try:
        assert "hello" in await _pull(body)

        # 1) Feed OPERATIVO autorizado ('orders') → se entrega.
        await bus_publish("order_status_changed",
                          {"order_id": "A", "from_code": "USD", "to_code": "CUP"},
                          roles=("admin", "employee"))
        f = await _pull(body)
        assert "order_status_changed" in f and '"A"' in f

        # 2) REVOCACIÓN en caliente: se retira 'orders' en la BD (conexión viva).
        db.users.update_one({"user_id": UID},
                            {"$set": {"allowed_permissions": []}})

        # 3) Evento PERSONAL P1: fuerza una iteración y se entrega siempre. Tras
        #    entregarlo el generador queda suspendido en el yield; el reauth del
        #    SIGUIENTE pull ya leerá la BD revocada.
        await bus_publish("balance_updated", {"marker": "P1"}, user_id=UID)
        assert "P1" in await _pull(body)

        # 4) BACKLOG en ambas colas: operativo B (ya NO autorizado) + personal P2.
        await bus_publish("order_status_changed",
                          {"order_id": "B", "from_code": "USD", "to_code": "CUP"},
                          roles=("admin", "employee"))
        await bus_publish("balance_updated", {"marker": "P2"}, user_id=UID)
        await asyncio.sleep(0.05)  # deja que _stream_loop forme el backlog

        # Al reanudar: reauth relee la BD (revocado) → update_authz → la compuerta
        # DESCARTA B; P2 (personal) sí sale. El siguiente frame es P2, nunca B.
        f = await _pull(body)
        assert "P2" in f
        assert '"B"' not in f and "order_status_changed" not in f

        # 5) Confirmación: no hay un B rezagado detrás.
        await bus_publish("balance_updated", {"marker": "P3"}, user_id=UID)
        f = await _pull(body)
        assert "P3" in f and '"B"' not in f
    finally:
        await body.aclose()


@pytest.mark.asyncio
async def test_sse_stream_delivers_authorized_and_personal(_seed, monkeypatch):
    # Camino feliz end-to-end: operativo autorizado + personal, ambos entregados.
    db = _seed
    monkeypatch.setattr(live_mod, "REAUTH_INTERVAL", 0.0)
    resp = await live_mod.live_stream(_fake_request(TOKEN))
    body = resp.body_iterator
    try:
        assert "hello" in await _pull(body)
        await bus_publish("order_created",
                          {"id": "O1", "from_code": "USD", "to_code": "CUP"},
                          roles=("admin", "employee"))
        assert '"O1"' in await _pull(body)
        await bus_publish("balance_updated", {"marker": "ME"}, user_id=UID)
        assert "ME" in await _pull(body)
        assert db.users.find_one({"user_id": UID}) is not None
    finally:
        await body.aclose()
