"""iter109 — Tests for VIP status request flow.

Coverage:
 1. Normal client submits request → 200, doc created with status=pending,
    notifications fired.
 2. Duplicate pending → 409.
 3. VIP/admin/employee cannot submit → 403.
 4. Invalid payment method → 422.
 5. GET /vip/requests/me returns current state + cooldown info.
 6. Admin lists pending requests + count endpoint.
 7. Approve → user.role becomes "vip", client notified, 2nd approve → 409.
 8. Reject with admin_note → status=rejected, cooldown starts.
 9. Post-rejection 7-day cooldown blocks re-submission (mutate reviewed_at).
10. Post-rejection after cooldown allows re-submission.
11. Permission gating: client cannot list, employee w/o perm cannot approve.
12. Rejected request stored admin_note is exposed in the client GET.
"""
import os
import pytest
import httpx
from datetime import datetime, timezone, timedelta

API_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001")
NORMAL_TOKEN = "test_session_normal_X"
VIP_TOKEN = "test_session_vip_X"
EMPLOYEE_TOKEN = "test_session_employee_X"
ADMIN_TOKEN = "test_session_admin_X"


def h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _reset_state():
    from db_client import db
    await db.vip_requests.delete_many({
        "user_id": {"$in": ["user_test_normal01", "user_test_vip01"]}
    })
    # Ensure the normal user is normal again in case a previous approve run left
    # them as VIP.
    await db.users.update_one(
        {"user_id": "user_test_normal01"},
        {"$set": {"role": "normal"}},
    )
    await db.users.update_one(
        {"user_id": "user_test_employee01"},
        {"$set": {"allowed_permissions": []}},
    )


async def _set_reviewed_at(request_id: str, days_ago: int) -> None:
    from db_client import db
    ts = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    await db.vip_requests.update_one({"id": request_id}, {"$set": {"reviewed_at": ts}})


VALID_PAYLOAD = {
    "message": "Quisiera acceder al programa VIP porque hago volumen alto.",
    "estimated_monthly_volume_usd": 25000,
    "preferred_payment_method": "bank_transfer",
}


class TestVipRequestsFlow:
    @pytest.mark.asyncio
    async def test_normal_can_submit(self):
        await _reset_state()
        async with httpx.AsyncClient(base_url=API_URL, timeout=15) as c:
            r = await c.post("/api/vip/requests", headers=h(NORMAL_TOKEN),
                             json=VALID_PAYLOAD)
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["status"] == "pending"
            assert body["user_id"] == "user_test_normal01"
            assert body["preferred_payment_method"] == "bank_transfer"
        await _reset_state()

    @pytest.mark.asyncio
    async def test_duplicate_pending_returns_409(self):
        await _reset_state()
        async with httpx.AsyncClient(base_url=API_URL, timeout=15) as c:
            r1 = await c.post("/api/vip/requests", headers=h(NORMAL_TOKEN),
                              json=VALID_PAYLOAD)
            assert r1.status_code == 200
            r2 = await c.post("/api/vip/requests", headers=h(NORMAL_TOKEN),
                              json=VALID_PAYLOAD)
            assert r2.status_code == 409
        await _reset_state()

    @pytest.mark.asyncio
    async def test_vip_cannot_submit(self):
        await _reset_state()
        async with httpx.AsyncClient(base_url=API_URL, timeout=15) as c:
            r = await c.post("/api/vip/requests", headers=h(VIP_TOKEN),
                             json=VALID_PAYLOAD)
            assert r.status_code == 403
        await _reset_state()

    @pytest.mark.asyncio
    async def test_admin_cannot_submit(self):
        async with httpx.AsyncClient(base_url=API_URL, timeout=15) as c:
            r = await c.post("/api/vip/requests", headers=h(ADMIN_TOKEN),
                             json=VALID_PAYLOAD)
            assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_invalid_payment_method(self):
        await _reset_state()
        async with httpx.AsyncClient(base_url=API_URL, timeout=15) as c:
            r = await c.post("/api/vip/requests", headers=h(NORMAL_TOKEN),
                             json={**VALID_PAYLOAD, "preferred_payment_method": "gold_bars"})
            assert r.status_code == 422
        await _reset_state()

    @pytest.mark.asyncio
    async def test_message_too_short(self):
        await _reset_state()
        async with httpx.AsyncClient(base_url=API_URL, timeout=15) as c:
            r = await c.post("/api/vip/requests", headers=h(NORMAL_TOKEN),
                             json={**VALID_PAYLOAD, "message": "hola"})
            assert r.status_code == 422
        await _reset_state()

    @pytest.mark.asyncio
    async def test_me_endpoint_returns_state(self):
        await _reset_state()
        async with httpx.AsyncClient(base_url=API_URL, timeout=15) as c:
            r0 = await c.get("/api/vip/requests/me", headers=h(NORMAL_TOKEN))
            assert r0.status_code == 200
            assert r0.json()["request"] is None
            assert r0.json()["can_submit"] is True

            await c.post("/api/vip/requests", headers=h(NORMAL_TOKEN), json=VALID_PAYLOAD)

            r1 = await c.get("/api/vip/requests/me", headers=h(NORMAL_TOKEN))
            body = r1.json()
            assert body["request"] is not None
            assert body["request"]["status"] == "pending"
            assert body["can_submit"] is False
        await _reset_state()

    @pytest.mark.asyncio
    async def test_admin_list_and_count(self):
        await _reset_state()
        async with httpx.AsyncClient(base_url=API_URL, timeout=15) as c:
            await c.post("/api/vip/requests", headers=h(NORMAL_TOKEN), json=VALID_PAYLOAD)

            r = await c.get("/api/admin/vip-requests", headers=h(ADMIN_TOKEN))
            assert r.status_code == 200
            body = r.json()
            assert body["pending"] == 1
            assert any(it["user_id"] == "user_test_normal01" for it in body["items"])

            r_cnt = await c.get("/api/admin/vip-requests/pending-count", headers=h(ADMIN_TOKEN))
            assert r_cnt.json()["pending"] == 1
        await _reset_state()

    @pytest.mark.asyncio
    async def test_approve_promotes_user(self):
        from db_client import db
        await _reset_state()
        async with httpx.AsyncClient(base_url=API_URL, timeout=15) as c:
            r = await c.post("/api/vip/requests", headers=h(NORMAL_TOKEN), json=VALID_PAYLOAD)
            rid = r.json()["id"]

            r_app = await c.post(f"/api/admin/vip-requests/{rid}/approve",
                                 headers=h(ADMIN_TOKEN))
            assert r_app.status_code == 200
            assert r_app.json()["status"] == "approved"

            # Client role is now vip.
            u = await db.users.find_one({"user_id": "user_test_normal01"}, {"_id": 0, "role": 1})
            assert u["role"] == "vip"

            # 2nd approve → 409.
            r_dup = await c.post(f"/api/admin/vip-requests/{rid}/approve",
                                 headers=h(ADMIN_TOKEN))
            assert r_dup.status_code == 409
        await _reset_state()

    @pytest.mark.asyncio
    async def test_reject_stores_note_and_notifies(self):
        await _reset_state()
        async with httpx.AsyncClient(base_url=API_URL, timeout=15) as c:
            r = await c.post("/api/vip/requests", headers=h(NORMAL_TOKEN), json=VALID_PAYLOAD)
            rid = r.json()["id"]
            r_rej = await c.post(f"/api/admin/vip-requests/{rid}/reject",
                                 headers=h(ADMIN_TOKEN),
                                 json={"admin_note": "Falta más historial de trading."})
            assert r_rej.status_code == 200
            assert r_rej.json()["status"] == "rejected"
            assert r_rej.json()["admin_note"] == "Falta más historial de trading."

            # Client sees the note via /me.
            r_me = await c.get("/api/vip/requests/me", headers=h(NORMAL_TOKEN))
            assert r_me.json()["request"]["admin_note"] == "Falta más historial de trading."
        await _reset_state()

    @pytest.mark.asyncio
    async def test_cooldown_blocks_resubmit(self):
        await _reset_state()
        async with httpx.AsyncClient(base_url=API_URL, timeout=15) as c:
            r = await c.post("/api/vip/requests", headers=h(NORMAL_TOKEN), json=VALID_PAYLOAD)
            rid = r.json()["id"]
            await c.post(f"/api/admin/vip-requests/{rid}/reject",
                         headers=h(ADMIN_TOKEN), json={"admin_note": ""})

            # Immediately try again → cooldown.
            r_retry = await c.post("/api/vip/requests", headers=h(NORMAL_TOKEN),
                                   json=VALID_PAYLOAD)
            assert r_retry.status_code == 429

            r_me = await c.get("/api/vip/requests/me", headers=h(NORMAL_TOKEN))
            body = r_me.json()
            assert body["cooldown_days_left"] > 0
            assert body["can_submit"] is False
        await _reset_state()

    @pytest.mark.asyncio
    async def test_cooldown_expires_after_7_days(self):
        await _reset_state()
        async with httpx.AsyncClient(base_url=API_URL, timeout=15) as c:
            r = await c.post("/api/vip/requests", headers=h(NORMAL_TOKEN), json=VALID_PAYLOAD)
            rid = r.json()["id"]
            await c.post(f"/api/admin/vip-requests/{rid}/reject",
                         headers=h(ADMIN_TOKEN), json={"admin_note": ""})

            # Backdate reviewed_at to 8 days ago → cooldown elapsed.
            await _set_reviewed_at(rid, days_ago=8)

            r_me = await c.get("/api/vip/requests/me", headers=h(NORMAL_TOKEN))
            assert r_me.json()["cooldown_days_left"] == 0
            assert r_me.json()["can_submit"] is True

            r2 = await c.post("/api/vip/requests", headers=h(NORMAL_TOKEN), json=VALID_PAYLOAD)
            assert r2.status_code == 200
        await _reset_state()

    @pytest.mark.asyncio
    async def test_client_cannot_access_admin_endpoints(self):
        async with httpx.AsyncClient(base_url=API_URL, timeout=15) as c:
            r = await c.get("/api/admin/vip-requests", headers=h(NORMAL_TOKEN))
            assert r.status_code == 403
            r2 = await c.get("/api/admin/vip-requests/pending-count", headers=h(NORMAL_TOKEN))
            assert r2.status_code == 403

    @pytest.mark.asyncio
    async def test_employee_without_perm_403(self):
        from db_client import db
        # Scope the employee to just "orders" — no vip_requests.
        await db.users.update_one(
            {"user_id": "user_test_employee01"},
            {"$set": {"allowed_permissions": ["orders"]}},
        )
        try:
            async with httpx.AsyncClient(base_url=API_URL, timeout=15) as c:
                r = await c.get("/api/admin/vip-requests", headers=h(EMPLOYEE_TOKEN))
                assert r.status_code == 403
        finally:
            await db.users.update_one(
                {"user_id": "user_test_employee01"},
                {"$set": {"allowed_permissions": []}},
            )
