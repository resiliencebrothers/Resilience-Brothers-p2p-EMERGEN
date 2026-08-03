"""iter107.1 — GET /admin/support/unread-count powers the sidebar pill.

Coverage:
 1. Admin gets `{unread: N}` and N matches the count of open/answered
    tickets with `unread_by_staff=True`.
 2. Closing a ticket makes it drop out of the unread count.
 3. Admin reply flips `unread_by_staff=False` → count decreases.
 4. Client without `support` perm → 403.
 5. Employee without `support` perm → 403.
 6. Fresh tenant with no tickets → `{unread: 0}`.
"""
import os
import pytest
import httpx

API_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001")
from conftest import NORMAL_TOKEN, VIP_TOKEN, EMPLOYEE_TOKEN, ADMIN_TOKEN


def h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _wipe_test_tickets() -> None:
    from db_client import db
    await db.support_tickets.delete_many(
        {"user_id": {"$in": ["user_test_normal01", "user_test_vip01"]}}
    )


async def _set_employee_perms(perms):
    """Toggle the test employee's allowed_permissions for the 403 test."""
    from db_client import db
    await db.users.update_one(
        {"user_id": "user_test_employee01"},
        {"$set": {"allowed_permissions": perms}},
    )


class TestSupportUnreadCount:
    @pytest.mark.asyncio
    async def test_matches_pending_tickets(self):
        await _wipe_test_tickets()
        async with httpx.AsyncClient(base_url=API_URL, timeout=15) as c:
            r0 = await c.get("/api/admin/support/unread-count", headers=h(ADMIN_TOKEN))
            assert r0.status_code == 200
            initial = r0.json()["unread"]
            assert initial == 0

            # Plant 3 tickets → count should jump to 3.
            for i in range(3):
                r = await c.post(
                    "/api/support/tickets", headers=h(NORMAL_TOKEN),
                    json={"category": "general",
                          "subject": f"iter107 pill probe {i}",
                          "message": "necesito ayuda"},
                )
                assert r.status_code == 200, r.text

            r1 = await c.get("/api/admin/support/unread-count", headers=h(ADMIN_TOKEN))
            assert r1.status_code == 200
            assert r1.json()["unread"] == 3

        await _wipe_test_tickets()

    @pytest.mark.asyncio
    async def test_close_drops_from_unread(self):
        await _wipe_test_tickets()
        async with httpx.AsyncClient(base_url=API_URL, timeout=15) as c:
            r = await c.post(
                "/api/support/tickets", headers=h(NORMAL_TOKEN),
                json={"category": "general",
                      "subject": "iter107 close probe",
                      "message": "necesito ayuda"},
            )
            tid = r.json()["id"]
            assert (await c.get("/api/admin/support/unread-count",
                                headers=h(ADMIN_TOKEN))).json()["unread"] == 1

            r_close = await c.post(f"/api/admin/support/tickets/{tid}/close",
                                   headers=h(ADMIN_TOKEN))
            assert r_close.status_code == 200

            assert (await c.get("/api/admin/support/unread-count",
                                headers=h(ADMIN_TOKEN))).json()["unread"] == 0
        await _wipe_test_tickets()

    @pytest.mark.asyncio
    async def test_reply_flips_unread(self):
        await _wipe_test_tickets()
        async with httpx.AsyncClient(base_url=API_URL, timeout=15) as c:
            r = await c.post(
                "/api/support/tickets", headers=h(NORMAL_TOKEN),
                json={"category": "general",
                      "subject": "iter107 reply probe",
                      "message": "necesito ayuda"},
            )
            tid = r.json()["id"]
            assert (await c.get("/api/admin/support/unread-count",
                                headers=h(ADMIN_TOKEN))).json()["unread"] == 1

            # Admin reply → `unread_by_staff` flips to False.
            r_reply = await c.post(
                f"/api/admin/support/tickets/{tid}/reply",
                headers=h(ADMIN_TOKEN),
                json={"text": "Hola, ya lo revisamos.", "images": []},
            )
            assert r_reply.status_code == 200

            assert (await c.get("/api/admin/support/unread-count",
                                headers=h(ADMIN_TOKEN))).json()["unread"] == 0

            # Client replies again → back to unread=1.
            r_client = await c.post(
                f"/api/support/tickets/{tid}/reply", headers=h(NORMAL_TOKEN),
                json={"text": "Sigo con dudas", "images": []},
            )
            assert r_client.status_code == 200
            assert (await c.get("/api/admin/support/unread-count",
                                headers=h(ADMIN_TOKEN))).json()["unread"] == 1
        await _wipe_test_tickets()

    @pytest.mark.asyncio
    async def test_client_403(self):
        async with httpx.AsyncClient(base_url=API_URL, timeout=15) as c:
            r = await c.get("/api/admin/support/unread-count",
                            headers=h(NORMAL_TOKEN))
            assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_scoped_employee_403(self):
        # Give the test employee a permission list that lacks 'support'.
        await _set_employee_perms(["orders"])
        try:
            async with httpx.AsyncClient(base_url=API_URL, timeout=15) as c:
                r = await c.get("/api/admin/support/unread-count",
                                headers=h(EMPLOYEE_TOKEN))
                assert r.status_code == 403
        finally:
            # Reset so other tests aren't affected.
            await _set_employee_perms([])
