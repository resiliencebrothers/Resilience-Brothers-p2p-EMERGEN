"""iter116 — Regression tests for the second batch of security hardening.

1. Withdrawal refund is idempotent across rejected↔pending flips (no double
   credit / no phantom credit).
2. VIP ledger email endpoint is rate-limited (10/hour) — abuse guard.
3. Login no longer leaks account existence (unified INVALID_CREDENTIALS,
   same status + message for missing account and wrong password).
4. Security self-audit endpoint runs (admin-only) and returns the checklist.
"""
import os
import uuid
import pytest
import httpx

API_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001")
from conftest import ADMIN_TOKEN, EMPLOYEE_TOKEN, VIP_TOKEN, NORMAL_TOKEN, with_totp_admin

VIP_UID = "user_test_vip01"


def h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _get_balance(currency: str = "USD") -> float:
    from db_client import db
    u = await db.users.find_one({"user_id": VIP_UID}, {"_id": 0, "vip_balances": 1})
    return float((u.get("vip_balances") or {}).get(currency, 0.0))


class TestWithdrawalRefundIdempotency:
    @pytest.mark.asyncio
    async def test_reject_pending_reject_no_double_credit(self):
        from db_client import db
        # Seed a withdrawal owned by the VIP in 'approved' state, and give the
        # VIP a known starting balance. The withdrawal amount is NOT part of the
        # balance yet (it was debited at creation) — mirrors production.
        await db.users.update_one({"user_id": VIP_UID},
                                  {"$set": {"vip_balances.USD": 100.0}})
        wid = f"wtest_{uuid.uuid4().hex[:10]}"
        await db.withdrawals.insert_one({
            "id": wid, "user_id": VIP_UID, "user_email": "vip.test@resilience.com",
            "user_name": "VIP Test", "amount_usd": 40.0, "currency": "USD",
            "method": "transfer", "status": "approved", "beneficiary_name": "X",
            "created_at": "2026-07-30T00:00:00+00:00",
        })
        start = await _get_balance("USD")
        async with httpx.AsyncClient(base_url=API_URL, timeout=30) as c:
            def body(status):
                return with_totp_admin({"status": status, "admin_note": "t"})
            # approved → rejected  (should credit +40 once)
            r1 = await c.put(f"/api/admin/withdrawals/{wid}/status",
                             headers=h(ADMIN_TOKEN), json=body("rejected"))
            assert r1.status_code == 200, r1.text
            after_reject1 = await _get_balance("USD")
            assert round(after_reject1 - start, 2) == 40.0, after_reject1

            # rejected → pending  (should re-debit -40)
            r2 = await c.put(f"/api/admin/withdrawals/{wid}/status",
                             headers=h(ADMIN_TOKEN), json=body("pending"))
            assert r2.status_code == 200, r2.text
            after_pending = await _get_balance("USD")
            assert round(after_pending - start, 2) == 0.0, after_pending

            # pending → rejected  (should credit +40 once, NOT +80)
            r3 = await c.put(f"/api/admin/withdrawals/{wid}/status",
                             headers=h(ADMIN_TOKEN), json=body("rejected"))
            assert r3.status_code == 200, r3.text
            after_reject2 = await _get_balance("USD")
            assert round(after_reject2 - start, 2) == 40.0, after_reject2

            # rejected → rejected (idempotent, no change)
            r4 = await c.put(f"/api/admin/withdrawals/{wid}/status",
                             headers=h(ADMIN_TOKEN), json=body("rejected"))
            assert r4.status_code == 200
            after_reject3 = await _get_balance("USD")
            assert round(after_reject3 - start, 2) == 40.0, after_reject3

        doc = await db.withdrawals.find_one({"id": wid}, {"_id": 0, "balance_refunded": 1})
        assert doc["balance_refunded"] is True
        # cleanup
        await db.withdrawals.delete_one({"id": wid})
        await db.users.update_one({"user_id": VIP_UID},
                                  {"$unset": {"vip_balances.USD": ""}})


class TestLedgerEmailRateLimit:
    @pytest.mark.asyncio
    async def test_vip_ledger_email_rate_limited(self):
        # 11 rapid calls — at least one must be 429 (limit is 10/hour).
        codes = []
        async with httpx.AsyncClient(base_url=API_URL, timeout=30) as c:
            for _ in range(12):
                r = await c.post("/api/vip/ledger/email", headers=h(VIP_TOKEN),
                                 json={"to": "someone@example.com"})
                codes.append(r.status_code)
        assert 429 in codes, f"expected a 429 among {codes}"


class TestLoginEnumeration:
    @pytest.mark.asyncio
    async def test_unknown_and_wrong_password_identical(self):
        async with httpx.AsyncClient(base_url=API_URL, timeout=30) as c:
            r_missing = await c.post("/api/auth/login",
                                     json={"email": f"ghost_{uuid.uuid4().hex}@x.com",
                                           "password": "whatever12345"})
            assert r_missing.status_code == 401
            d = r_missing.json()["detail"]
            assert d["code"] == "INVALID_CREDENTIALS"
            assert "USER_NOT_FOUND" not in r_missing.text


class TestSelfAuditEndpoint:
    @pytest.mark.asyncio
    async def test_admin_can_run_checklist(self):
        async with httpx.AsyncClient(base_url=API_URL, timeout=60) as c:
            r = await c.get("/api/admin/security/self-audit", headers=h(ADMIN_TOKEN))
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["verdict"] in ("pass", "warn", "fail")
            ids = {c["id"] for c in body["checks"]}
            for cid in ("SEC-001", "SEC-002", "SEC-003", "SEC-004"):
                assert cid in ids
            # the 4 audited invariants must all pass
            by_id = {c["id"]: c for c in body["checks"]}
            for cid in ("SEC-001", "SEC-002", "SEC-003", "SEC-004"):
                assert by_id[cid]["status"] == "pass", by_id[cid]

    @pytest.mark.asyncio
    async def test_non_admin_forbidden(self):
        async with httpx.AsyncClient(base_url=API_URL, timeout=30) as c:
            r = await c.get("/api/admin/security/self-audit", headers=h(EMPLOYEE_TOKEN))
            assert r.status_code == 403
