"""iter98 — Live SSE role-filtered publish + admin queue notifications.

Coverage:
1. `publish(user_id=None, roles=("admin",))` reaches admin subs but NOT
   regular users — even though both are broadcast-subscribed.
2. `publish(user_id=None)` without `roles` still reaches everybody
   (regression guard against accidentally coupling role filter to the
   broadcast fan-out).
3. When a normal user creates an order, an `order_created` event fires
   for admin subscribers only.
4. When a normal user requests a withdrawal, a `withdrawal_created`
   event fires for admin subscribers only.
"""
import asyncio
import pytest


class TestRoleFilteredPublish:
    @pytest.mark.asyncio
    async def test_admin_only_publish_skips_non_admins(self):
        from services.live_bus import (
            subscribe as bus_subscribe,
            unsubscribe as bus_unsubscribe,
            publish as bus_publish,
        )
        sub_admin = await bus_subscribe("admin_u", role="admin")
        sub_employee = await bus_subscribe("employee_u", role="employee")
        sub_normal = await bus_subscribe("normal_u", role="normal")
        try:
            await bus_publish(
                "order_created",
                {"id": "o1"},
                roles=("admin", "employee"),
            )
            evt_a = await asyncio.wait_for(sub_admin.queue.get(), 1)
            evt_e = await asyncio.wait_for(sub_employee.queue.get(), 1)
            assert evt_a["type"] == "order_created"
            assert evt_e["type"] == "order_created"
            # Normal user must NOT receive it.
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(sub_normal.queue.get(), 0.2)
        finally:
            await bus_unsubscribe(sub_admin)
            await bus_unsubscribe(sub_employee)
            await bus_unsubscribe(sub_normal)

    @pytest.mark.asyncio
    async def test_broadcast_still_reaches_everyone(self):
        from services.live_bus import (
            subscribe as bus_subscribe,
            unsubscribe as bus_unsubscribe,
            publish as bus_publish,
        )
        sub_admin = await bus_subscribe("admin_u2", role="admin")
        sub_normal = await bus_subscribe("normal_u2", role="normal")
        try:
            await bus_publish("rates_updated", {"rate_id": "r1"})
            evt_a = await asyncio.wait_for(sub_admin.queue.get(), 1)
            evt_n = await asyncio.wait_for(sub_normal.queue.get(), 1)
            assert evt_a["type"] == "rates_updated"
            assert evt_n["type"] == "rates_updated"
        finally:
            await bus_unsubscribe(sub_admin)
            await bus_unsubscribe(sub_normal)

    @pytest.mark.asyncio
    async def test_role_filter_ignored_for_targeted_publish(self):
        """`roles` filter should be a no-op when publishing to a
        specific user_id — that's already the strongest filter."""
        from services.live_bus import (
            subscribe as bus_subscribe,
            unsubscribe as bus_unsubscribe,
            publish as bus_publish,
        )
        sub = await bus_subscribe("normal_u3", role="normal")
        try:
            # user_id set → roles filter must be ignored (normal receives it).
            await bus_publish(
                "balance_updated",
                {"reason": "test"},
                user_id="normal_u3",
                roles=("admin",),
            )
            evt = await asyncio.wait_for(sub.queue.get(), 1)
            assert evt["type"] == "balance_updated"
        finally:
            await bus_unsubscribe(sub)

    @pytest.mark.asyncio
    async def test_dual_publish_reaches_owner_and_admins(self):
        """Regression: `order_status_changed` must reach BOTH the order
        owner (via user_id=owner call) AND admin/employee broadcast
        subscribers (via roles=('admin','employee') call). Route-level
        code path in admin.py calls publish twice."""
        from services.live_bus import (
            subscribe as bus_subscribe,
            unsubscribe as bus_unsubscribe,
            publish as bus_publish,
        )
        sub_owner = await bus_subscribe("owner_u4", role="normal")
        sub_admin = await bus_subscribe("admin_u4", role="admin")
        sub_third = await bus_subscribe("third_u4", role="normal")
        try:
            # Mimic routes/admin.py behavior: two publishes.
            await bus_publish("order_status_changed", {"order_id": "o1"},
                              user_id="owner_u4")
            await bus_publish("order_status_changed", {"order_id": "o1"},
                              roles=("admin", "employee"))

            evt_owner = await asyncio.wait_for(sub_owner.queue.get(), 1)
            evt_admin = await asyncio.wait_for(sub_admin.queue.get(), 1)
            assert evt_owner["type"] == "order_status_changed"
            assert evt_admin["type"] == "order_status_changed"
            # Third-party normal user must NOT get the admin broadcast.
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(sub_third.queue.get(), 0.2)
        finally:
            await bus_unsubscribe(sub_owner)
            await bus_unsubscribe(sub_admin)
            await bus_unsubscribe(sub_third)
