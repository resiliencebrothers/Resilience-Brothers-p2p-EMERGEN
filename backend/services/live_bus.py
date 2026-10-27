"""iter97 — In-memory pub/sub bus for the SSE live stream.

Simple, single-process asyncio.Queue based broadcaster. Consumers
subscribe once per HTTP connection (`GET /api/live/stream`) and the
platform's mutating routes call `publish(...)` after every rate /
order / balance change so every open tab gets the update inside
~200 ms — no polling, no page refresh needed.

Design notes:
- One asyncio.Queue *per open connection* (not per user) so a user
  who has 3 tabs open gets 3 fan-outs, each cancellable independently
  when its tab closes.
- `publish` is fire-and-forget from the caller's perspective: it
  never blocks the request that triggered it. If the destination
  queue is full (100+ backlogged events) we drop the OLDEST event
  to keep the newest — connections that fell behind will get the
  latest state on the next event.
- `user_id=None` means broadcast to everybody (e.g. rate changes are
  visible to every logged-in user); `user_id="..."` restricts the
  event to that user's own subscriptions (order status, balances).

The bus lives in-process so it is NOT horizontally-scalable as-is;
when the platform moves to N workers behind a load-balancer we'll
swap this for Redis Pub/Sub (`aioredis.publish/subscribe`) without
changing the fetch-path.  Keep the interface (`subscribe/publish`)
narrow so that swap stays surgical.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional

log = logging.getLogger("live_bus")

MAX_QUEUE_DEPTH = 128

# STAFF-06-R (auditoría residual) — los feeds OPERATIVOS de staff (los que se
# difunden con `roles=("admin","employee")`) deben autorizarse por CAPACIDAD, no
# solo por rol: retirar el permiso 'orders' tiene que cortar order_created /
# order_status_changed aunque el empleado conserve el rol y la cuenta activa.
# Esta matriz mapea CADA tipo de evento de staff a su código de permiso (la
# misma matriz de capacidades que la UI y los endpoints REST). Un evento de
# staff SIN entrada aquí se DENIEGA (fail-closed) para no reintroducir fugas al
# añadir feeds nuevos sin autorizar. Los eventos personales (user_id=...) y los
# broadcasts públicos (sin roles) NO pasan por aquí.
_STAFF_EVENT_CAP: dict[str, str] = {
    "order_created": "orders",
    "order_status_changed": "orders",
    "withdrawal_created": "withdrawals",
    "withdrawal_status_changed": "withdrawals",
    "deposit_created": "withdrawals",
    "ledger_changed": "transactions",
    "reconciliation_import": "reconciliation",
    "company_request_created": "company_requests",
    "company_request_updated": "company_requests",
    "support_ticket_created": "support",
    "support_ticket_updated": "support",
    # pickups_changed — señal operativa del panel de recogidas (Inventario →
    # Tiendas). Lo consume SOLO personal con 'products' (los endpoints
    # verify/confirm/pickup-ready usan require_permission("products")); antes se
    # difundía a TODOS los usuarios (broadcast sin roles). Ahora es feed de
    # staff gated por capacidad, igual que el resto.
    "pickups_changed": "products",
}

# Campos del payload que acotan el evento a una moneda (ámbito de recurso).
_CURRENCY_FIELDS = ("currency", "from_code", "to_code")


def _event_currencies(data: dict) -> list[str]:
    out: list[str] = []
    if isinstance(data, dict):
        for k in _CURRENCY_FIELDS:
            v = data.get(k)
            if v:
                out.append(str(v).upper())
    return out


def _staff_authorized(sub: "Subscription", event_type: str, data: dict,
                      require_perm: Optional[str]) -> bool:
    """¿Esta suscripción de staff puede recibir este evento operativo?

    1) Capacidad: admin siempre; empleado solo si tiene el permiso requerido
       (deny-by-default vía `_has_permission`). Evento sin mapeo → denegado.
    2) Ámbito de moneda (igual que los filtros REST): solo aplica al rol
       `employee` con `allowed_currencies` no vacío; si el evento declara
       monedas y ninguna está en su ámbito, no lo recibe. Admin y empleados sin
       restricción de moneda la ignoran; eventos sin moneda pasan el ámbito."""
    from services.permissions import _has_permission
    if sub.role == "admin":
        return True  # rol raíz — ve todos los feeds operativos
    cap = require_perm or _STAFF_EVENT_CAP.get(event_type)
    if cap is None:
        log.warning("live_bus: evento de staff '%s' sin mapeo de capacidad — "
                    "denegado para no-admin (fail-closed)", event_type)
        return False
    if not _has_permission(
            {"role": sub.role, "allowed_permissions": sub.allowed_permissions}, cap):
        return False
    if sub.role == "employee" and sub.allowed_currencies:
        evcs = _event_currencies(data)
        if evcs and not (set(evcs) & set(sub.allowed_currencies)):
            return False
    return True


@dataclass(eq=False)
class Subscription:
    """One open EventSource connection. `eq=False` so the default
    id-based hash sticks (asyncio.Queue is un-hashable, so field-based
    equality would break `set.add`)."""

    user_id: str
    role: Optional[str] = None  # iter98 — role stamp so publish can filter admin-only feeds
    # STAFF-06-R — capacidades y ámbito de moneda SELLADOS en la suscripción y
    # refrescados en cada revalidación (ver routes/live.py), de modo que una
    # revocación de permiso/moneda corta el feed sin necesidad de reconectar.
    allowed_permissions: list = field(default_factory=list)
    allowed_currencies: list = field(default_factory=list)
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(MAX_QUEUE_DEPTH))
    connected_at: float = field(default_factory=time.time)


# user_id → set[Subscription]
_subs: dict[str, set[Subscription]] = defaultdict(set)
_broadcast_subs: set[Subscription] = set()  # subs that also receive user_id=None events


async def subscribe(user_id: str, role: Optional[str] = None,
                    allowed_permissions: Optional[list] = None,
                    allowed_currencies: Optional[list] = None) -> Subscription:
    """Register a new consumer. Caller MUST call `unsubscribe` in a
    `finally:` so a disconnect doesn't leak queues forever."""
    sub = Subscription(
        user_id=user_id, role=role,
        allowed_permissions=list(allowed_permissions or []),
        allowed_currencies=[str(c).upper() for c in (allowed_currencies or [])],
    )
    _subs[user_id].add(sub)
    _broadcast_subs.add(sub)
    log.info("live_bus subscribe user=%s role=%s total_user_subs=%d total_open=%d",
             user_id, role, len(_subs[user_id]), len(_broadcast_subs))
    return sub


def update_authz(sub: Subscription, role: Optional[str],
                 allowed_permissions: Optional[list],
                 allowed_currencies: Optional[list]) -> None:
    """STAFF-06-R — re-sella rol/permisos/monedas de una suscripción VIVA tras
    la revalidación periódica, sin cortar el socket."""
    sub.role = role
    sub.allowed_permissions = list(allowed_permissions or [])
    sub.allowed_currencies = [str(c).upper() for c in (allowed_currencies or [])]


async def unsubscribe(sub: Subscription) -> None:
    _subs.get(sub.user_id, set()).discard(sub)
    if not _subs.get(sub.user_id):
        _subs.pop(sub.user_id, None)
    _broadcast_subs.discard(sub)
    log.info("live_bus unsubscribe user=%s total_open=%d",
             sub.user_id, len(_broadcast_subs))


def _push(sub: Subscription, event_type: str, data: dict, staff_feed: bool = False) -> None:
    """Enqueue an event on a single subscription queue, dropping the
    oldest item if the consumer fell behind (>128 unread).

    `staff_feed=True` marks events that were authorized as an OPERATIVE STAFF
    feed (roles=...). STAFF-06-R2 — ese flag viaja con el evento para poder
    RE-AUTORIZARLO en el punto de entrega final (ver reauthorize_event): si el
    permiso se retira mientras el evento está pendiente en CUALQUIER cola, se
    descarta en vez de entregarse con un snapshot viejo."""
    item = {"type": event_type, "data": data, "ts": time.time(), "staff": staff_feed}
    try:
        sub.queue.put_nowait(item)
    except asyncio.QueueFull:
        # Drop oldest to make room; a stale event is worse than
        # blocking the publisher.
        try:
            sub.queue.get_nowait()
        except Exception:
            pass
        try:
            sub.queue.put_nowait(item)
        except Exception:
            pass


def reauthorize_event(sub: Subscription, ev: dict) -> bool:
    """STAFF-06-R2 — compuerta de ENTREGA FINAL. Un evento pendiente (en
    Subscription.queue o ya convertido en frame en heartbeat_queue) debe volver
    a autorizarse contra el snapshot ACTUAL de la suscripción antes de salir.
    Solo re-chequea feeds OPERATIVOS de staff (`staff=True`); los eventos
    personales del dueño (user_id=...) y los broadcasts públicos se entregan
    siempre. Así, si el permiso/moneda se revocó tras encolar, el frame NO sale."""
    if not ev.get("staff"):
        return True
    return _staff_authorized(sub, ev.get("type"), ev.get("data") or {}, None)


async def publish(
    event_type: str,
    data: dict,
    user_id: Optional[str] = None,
    roles: Optional[tuple[str, ...]] = None,
    require_perm: Optional[str] = None,
) -> None:
    """Broadcast an event.

    * `user_id=None`  → everybody sees it (rate updates, marketplace,…)
    * `user_id="uX"` → only subscriptions bound to that user receive it
                       (order-status, balance updates,…). PERSONAL feeds are
                       NOT capability-gated (separados de los feeds de staff).
    * `roles=("admin", "employee")` → OPERATIVE staff feed: additionally
                       restrict a broadcast (i.e. `user_id=None`) to staff
                       subscriptions AND authorize each by CAPACIDAD + ámbito de
                       moneda (STAFF-06-R). The required permission comes from
                       `require_perm` or the `_STAFF_EVENT_CAP` matrix; an
                       unmapped staff event is denied (fail-closed). Ignored when
                       `user_id` is set.
    """
    if user_id is None:
        candidates = list(_broadcast_subs)
        if roles:
            targets = [s for s in candidates
                       if s.role in roles
                       and _staff_authorized(s, event_type, data, require_perm)]
            for sub in targets:
                _push(sub, event_type, data, staff_feed=True)
            return
        else:
            targets = candidates
    else:
        targets = list(_subs.get(user_id, ()))
    for sub in targets:
        _push(sub, event_type, data, staff_feed=False)


async def event_iterator(sub: Subscription) -> AsyncIterator[dict]:
    """Async generator that yields events for one subscription.
    Never returns on its own — the caller cancels the task when the
    HTTP request is torn down."""
    while True:
        ev = await sub.queue.get()
        yield ev
