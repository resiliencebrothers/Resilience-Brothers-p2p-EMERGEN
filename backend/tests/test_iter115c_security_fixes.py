"""iter115c — Regression tests for the 28/7/2026 security audit fixes.

SEC-001 (HIGH): balance & staff-capability fields on PUT /admin/users/{id}
    are admin-only. A scoped employee must never mint balance or grant
    capability booleans.
SEC-002 (LOW): Google OAuth post-login redirect only accepts same-site
    relative paths.
SEC-003 (LOW): user-controlled search strings are regex-escaped (no 500 on
    crafted patterns).
"""
import os
import pytest
import httpx

API_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001")
from conftest import (NORMAL_TOKEN, VIP_TOKEN, ADMIN_TOKEN, EMPLOYEE_TOKEN,
                      with_totp_admin, with_totp_employee)

TARGET_USER = "user_test_normal01"


def h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class TestSec001BalanceCapabilityGuard:
    @pytest.mark.asyncio
    async def test_employee_cannot_edit_balances(self):
        async with httpx.AsyncClient(base_url=API_URL, timeout=30) as c:
            r = await c.put(f"/api/admin/users/{TARGET_USER}", headers=h(EMPLOYEE_TOKEN),
                            json=with_totp_employee({"vip_balances": {"USDT": 999999}}))
            assert r.status_code == 403, r.text
            assert "admin" in r.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_employee_cannot_edit_legacy_balance(self):
        async with httpx.AsyncClient(base_url=API_URL, timeout=30) as c:
            r = await c.put(f"/api/admin/users/{TARGET_USER}", headers=h(EMPLOYEE_TOKEN),
                            json=with_totp_employee({"vip_balance_usd": 500000}))
            assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_employee_cannot_grant_capabilities(self):
        async with httpx.AsyncClient(base_url=API_URL, timeout=30) as c:
            for field in ("can_manage_blocklist", "can_manage_company_funds",
                          "can_edit_product_prices"):
                r = await c.put(f"/api/admin/users/{TARGET_USER}",
                                headers=h(EMPLOYEE_TOKEN),
                                json=with_totp_employee({field: True}))
                assert r.status_code == 403, f"{field}: {r.status_code} {r.text}"

    @pytest.mark.asyncio
    async def test_admin_can_still_edit_balances(self):
        from db_client import db
        before = await db.users.find_one({"user_id": TARGET_USER}, {"_id": 0, "vip_balances": 1})
        original = (before or {}).get("vip_balances")
        async with httpx.AsyncClient(base_url=API_URL, timeout=30) as c:
            r = await c.put(f"/api/admin/users/{TARGET_USER}", headers=h(ADMIN_TOKEN),
                            json=with_totp_admin({"vip_balances": {"USDT": 12.34}}))
            assert r.status_code == 200, r.text
            assert r.json()["vip_balances"] == {"USDT": 12.34}
        # restore
        if original is not None:
            await db.users.update_one({"user_id": TARGET_USER},
                                      {"$set": {"vip_balances": original}})
        else:
            await db.users.update_one({"user_id": TARGET_USER},
                                      {"$unset": {"vip_balances": ""}})

    @pytest.mark.asyncio
    async def test_balance_edit_flagged_in_audit_log(self):
        from db_client import db
        entry = await db.audit_log.find_one(
            {"action": "user.update", "entity_id": TARGET_USER,
             "details.balance_edit": True},
            {"_id": 0}, sort=[("created_at", -1)],
        )
        assert entry is not None, "balance edit not distinctly logged"


class TestSec002OpenRedirect:
    @pytest.mark.asyncio
    async def test_external_redirect_rejected(self):
        from db_client import db
        async with httpx.AsyncClient(base_url=API_URL, timeout=30,
                                     follow_redirects=False) as c:
            r = await c.get("/api/auth/google/login",
                            params={"redirect": "https://evil.example/phish"})
            assert r.status_code == 302
        doc = await db.oauth_states.find_one({}, {"_id": 0}, sort=[("created_at", -1)])
        assert doc["redirect"] == "/dashboard"

    @pytest.mark.asyncio
    async def test_scheme_relative_redirect_rejected(self):
        from db_client import db
        async with httpx.AsyncClient(base_url=API_URL, timeout=30,
                                     follow_redirects=False) as c:
            r = await c.get("/api/auth/google/login",
                            params={"redirect": "//evil.example/phish"})
            assert r.status_code == 302
        doc = await db.oauth_states.find_one({}, {"_id": 0}, sort=[("created_at", -1)])
        assert doc["redirect"] == "/dashboard"

    @pytest.mark.asyncio
    async def test_relative_redirect_kept(self):
        from db_client import db
        async with httpx.AsyncClient(base_url=API_URL, timeout=30,
                                     follow_redirects=False) as c:
            r = await c.get("/api/auth/google/login",
                            params={"redirect": "/dashboard/batches"})
            assert r.status_code == 302
        doc = await db.oauth_states.find_one({}, {"_id": 0}, sort=[("created_at", -1)])
        assert doc["redirect"] == "/dashboard/batches"


class TestSec003RegexEscape:
    @pytest.mark.asyncio
    async def test_crafted_regex_does_not_500(self):
        async with httpx.AsyncClient(base_url=API_URL, timeout=30) as c:
            for path, params in (
                ("/api/admin/users", {"q": "((((invalid[a-"}),
                ("/api/admin/withdrawals", {"user_q": "((((invalid[a-"}),
            ):
                r = await c.get(path, headers=h(ADMIN_TOKEN), params=params)
                assert r.status_code == 200, f"{path}: {r.status_code} {r.text[:200]}"

    @pytest.mark.asyncio
    async def test_literal_search_still_works(self):
        async with httpx.AsyncClient(base_url=API_URL, timeout=30) as c:
            r = await c.get("/api/admin/users", headers=h(ADMIN_TOKEN),
                            params={"q": "admin.test"})
            assert r.status_code == 200
            assert any("admin.test" in (u.get("email") or "") for u in r.json())
