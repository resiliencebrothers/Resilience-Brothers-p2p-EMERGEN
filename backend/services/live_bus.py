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


@dataclass(eq=False)
class Subscription:
    """One open EventSource connection. `eq=False` so the default
    id-based hash sticks (asyncio.Queue is un-hashable, so field-based
    equality would break `set.add`)."""

    user_id: str
    role: Optional[str] = None  # iter98 — role stamp so publish can filter admin-only feeds
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(MAX_QUEUE_DEPTH))
    connected_at: float = field(default_factory=time.time)


# user_id → set[Subscription]
_subs: dict[str, set[Subscription]] = defaultdict(set)
_broadcast_subs: set[Subscription] = set()  # subs that also receive user_id=None events


async def subscribe(user_id: str, role: Optional[str] = None) -> Subscription:
    """Register a new consumer. Caller MUST call `unsubscribe` in a
    `finally:` so a disconnect doesn't leak queues forever."""
    sub = Subscription(user_id=user_id, role=role)
    _subs[user_id].add(sub)
    _broadcast_subs.add(sub)
    log.info("live_bus subscribe user=%s role=%s total_user_subs=%d total_open=%d",
             user_id, role, len(_subs[user_id]), len(_broadcast_subs))
    return sub


async def unsubscribe(sub: Subscription) -> None:
    _subs.get(sub.user_id, set()).discard(sub)
    if not _subs.get(sub.user_id):
        _subs.pop(sub.user_id, None)
    _broadcast_subs.discard(sub)
    log.info("live_bus unsubscribe user=%s total_open=%d",
             sub.user_id, len(_broadcast_subs))


def _push(sub: Subscription, event_type: str, data: dict) -> None:
    """Enqueue an event on a single subscription queue, dropping the
    oldest item if the consumer fell behind (>128 unread)."""
    try:
        sub.queue.put_nowait({"type": event_type, "data": data, "ts": time.time()})
    except asyncio.QueueFull:
        # Drop oldest to make room; a stale event is worse than
        # blocking the publisher.
        try:
            sub.queue.get_nowait()
        except Exception:
            pass
        try:
            sub.queue.put_nowait({"type": event_type, "data": data, "ts": time.time()})
        except Exception:
            pass


async def publish(
    event_type: str,
    data: dict,
    user_id: Optional[str] = None,
    roles: Optional[tuple[str, ...]] = None,
) -> None:
    """Broadcast an event.

    * `user_id=None`  → everybody sees it (rate updates, marketplace,…)
    * `user_id="uX"` → only subscriptions bound to that user receive it
                       (order-status, balance updates,…)
    * `roles=("admin", "employee")` → additionally restrict a broadcast
                                       (i.e. `user_id=None`) to subscriptions
                                       whose role is in the tuple. Used for
                                       admin-only feeds like `order_created`.
                                       Ignored when `user_id` is set.
    """
    if user_id is None:
        candidates = list(_broadcast_subs)
        if roles:
            targets = [s for s in candidates if s.role in roles]
        else:
            targets = candidates
    else:
        targets = list(_subs.get(user_id, ()))
    for sub in targets:
        _push(sub, event_type, data)


async def event_iterator(sub: Subscription) -> AsyncIterator[dict]:
    """Async generator that yields events for one subscription.
    Never returns on its own — the caller cancels the task when the
    HTTP request is torn down."""
    while True:
        ev = await sub.queue.get()
        yield ev
