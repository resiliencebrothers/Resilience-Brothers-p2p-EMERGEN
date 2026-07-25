"""iter97 — Live SSE stream regression tests.

Coverage:
1. `/api/live/stream` requires auth (401 without cookie / bearer).
2. A newly-connected client immediately receives the `hello` event.
3. Publishing an event via the live_bus fan-outs to every open
   subscription for the target user (or to everyone when user_id
   is None).
4. Backpressure: when a subscription queue is full (>128 events)
   the oldest event is dropped, not the newest.
"""
import asyncio
import httpx
import pytest
import os

from conftest import BASE_URL, ADMIN_TOKEN, VIP_TOKEN, NORMAL_TOKEN


def _h(t=None):
    if t:
        return {"Authorization": f"Bearer {t}"}
    return {}


class TestLiveStreamHTTP:
    def test_stream_requires_auth(self):
        # No auth headers → 401.
        with httpx.Client(timeout=5) as c:
            r = c.get(f"{BASE_URL}/api/live/stream")
        assert r.status_code == 401

    def test_hello_event_arrives_immediately(self):
        """The `event: hello` frame is sent as the very first line so
        the client-side `onopen` handler always has a payload."""
        with httpx.Client(timeout=6) as c:
            with c.stream("GET", f"{BASE_URL}/api/live/stream",
                          headers=_h(VIP_TOKEN)) as r:
                assert r.status_code == 200
                assert r.headers["content-type"].startswith("text/event-stream")
                # Read enough to see the first event frame.
                buf = ""
                for chunk in r.iter_text():
                    buf += chunk
                    if "event: hello" in buf:
                        break
                    if len(buf) > 4096:
                        break
        assert "event: hello" in buf
        assert '"user_id"' in buf


class TestLiveBusUnit:
    @pytest.mark.asyncio
    async def test_publish_targets_a_single_user(self):
        # In-process import — this only works while the tests share the
        # backend Python process (which they do when run alongside the
        # server via the same pod).
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from services.live_bus import (
            subscribe as bus_subscribe,
            unsubscribe as bus_unsubscribe,
            publish as bus_publish,
        )

        # Two subs on different users
        sub_a = await bus_subscribe("user_A")
        sub_b = await bus_subscribe("user_B")
        try:
            await bus_publish("balance_updated", {"reason": "test"},
                              user_id="user_A")
            # A gets the event, B does NOT.
            evt_a = await asyncio.wait_for(sub_a.queue.get(), 1)
            assert evt_a["type"] == "balance_updated"
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(sub_b.queue.get(), 0.2)
        finally:
            await bus_unsubscribe(sub_a)
            await bus_unsubscribe(sub_b)

    @pytest.mark.asyncio
    async def test_publish_broadcast_reaches_all(self):
        from services.live_bus import (
            subscribe as bus_subscribe,
            unsubscribe as bus_unsubscribe,
            publish as bus_publish,
        )
        sub_a = await bus_subscribe("user_A")
        sub_b = await bus_subscribe("user_B")
        try:
            await bus_publish("rates_updated", {"rate_id": "r1"})
            evt_a = await asyncio.wait_for(sub_a.queue.get(), 1)
            evt_b = await asyncio.wait_for(sub_b.queue.get(), 1)
            assert evt_a["type"] == "rates_updated"
            assert evt_b["type"] == "rates_updated"
        finally:
            await bus_unsubscribe(sub_a)
            await bus_unsubscribe(sub_b)

    @pytest.mark.asyncio
    async def test_backpressure_drops_oldest(self):
        from services.live_bus import (
            MAX_QUEUE_DEPTH,
            subscribe as bus_subscribe,
            unsubscribe as bus_unsubscribe,
            publish as bus_publish,
        )
        sub = await bus_subscribe("user_flood")
        try:
            # Emit MAX + 5 events without draining.
            for i in range(MAX_QUEUE_DEPTH + 5):
                await bus_publish("rates_updated", {"i": i}, user_id="user_flood")
            # Queue holds at most MAX_QUEUE_DEPTH — oldest were evicted.
            assert sub.queue.qsize() <= MAX_QUEUE_DEPTH
            evt = await asyncio.wait_for(sub.queue.get(), 1)
            # Because the oldest were dropped, the first drained event's
            # `i` must be > 0.
            assert evt["data"]["i"] > 0
        finally:
            await bus_unsubscribe(sub)
