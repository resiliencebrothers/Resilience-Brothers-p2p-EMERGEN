"""iter117 — Staff mutations require 2FA to be enabled.

A proactive enrollment gate: any admin/employee performing a state-changing
(POST/PUT/PATCH/DELETE) action must have 2FA enabled, else 412
TOTP_SETUP_REQUIRED. GET reads and 2FA-setup/logout stay allowed; normal/vip
clients are unaffected.
"""
import os
import pytest
import httpx

API_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001")
from conftest import ADMIN_TOKEN, EMPLOYEE_TOKEN, NORMAL_TOKEN, VIP_TOKEN, make_employee_totp

EMPLOYEE_UID = "user_test_employee01"


def h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _set_employee_totp(enabled: bool) -> None:
    from db_client import db
    if enabled:
        await db.users.update_one({"user_id": EMPLOYEE_UID},
                                  {"$set": {"totp_enabled": True}})
    else:
        await db.users.update_one({"user_id": EMPLOYEE_UID},
                                  {"$set": {"totp_enabled": False}})


class TestStaff2faMutationGate:
    @pytest.mark.asyncio
    async def test_mutation_blocked_without_2fa(self):
        await _set_employee_totp(False)
        try:
            async with httpx.AsyncClient(base_url=API_URL, timeout=30) as c:
                # PUT order status → require_permission("orders"), mutating.
                r = await c.put("/api/admin/orders/nonexistent_id/status",
                                headers=h(EMPLOYEE_TOKEN),
                                json={"status": "approved"})
                assert r.status_code == 412, r.text
                detail = r.json()["detail"]
                assert detail["code"] == "TOTP_SETUP_REQUIRED"
                assert detail["setup_url"]
        finally:
            await _set_employee_totp(True)

    @pytest.mark.asyncio
    async def test_get_read_allowed_without_2fa(self):
        await _set_employee_totp(False)
        try:
            async with httpx.AsyncClient(base_url=API_URL, timeout=30) as c:
                r = await c.get("/api/admin/orders", headers=h(EMPLOYEE_TOKEN))
                assert r.status_code == 200, r.text
        finally:
            await _set_employee_totp(True)

    @pytest.mark.asyncio
    async def test_2fa_setup_endpoint_never_blocked(self):
        await _set_employee_totp(False)
        try:
            async with httpx.AsyncClient(base_url=API_URL, timeout=30) as c:
                # POST /me/2fa/setup must be reachable so staff can enrol.
                r = await c.post("/api/me/2fa/setup", headers=h(EMPLOYEE_TOKEN))
                assert r.status_code != 412, r.text
        finally:
            await _set_employee_totp(True)

    @pytest.mark.asyncio
    async def test_mutation_allowed_with_2fa(self):
        await _set_employee_totp(True)
        async with httpx.AsyncClient(base_url=API_URL, timeout=30) as c:
            # With 2FA enabled the gate passes; endpoint then 404s the fake id
            # (proving we got past require_permission's 2FA gate).
            r = await c.put("/api/admin/orders/nonexistent_id/status",
                            headers=h(EMPLOYEE_TOKEN),
                            json={"status": "approved", "totp_code": make_employee_totp()})
            assert r.status_code in (400, 404), r.text
            assert r.status_code != 412

    @pytest.mark.asyncio
    async def test_client_mutation_unaffected(self):
        # A normal/vip client is not staff → the gate must not touch them.
        async with httpx.AsyncClient(base_url=API_URL, timeout=30) as c:
            r = await c.put("/api/admin/orders/nonexistent_id/status",
                            headers=h(NORMAL_TOKEN), json={"status": "approved"})
            # Blocked by RBAC (403), never by the 2FA-enrollment gate (412).
            assert r.status_code == 403, r.text
