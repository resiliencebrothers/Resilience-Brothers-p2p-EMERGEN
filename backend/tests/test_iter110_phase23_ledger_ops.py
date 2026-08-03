"""iter110 · Phases 2+3 — capital deposits & settlements on the VIP ledger.

Coverage:
Phase 2 (capital deposits):
 1. VIP creates a deposit → status=pending; positive_usdt untouched.
 2. Admin confirm → positive_usdt += converted; status=confirmed.
 3. Admin reject → status=rejected; ledger untouched.
 4. Non-VIP cannot create → 403. Non-orders-perm employee cannot confirm → 403.
 5. Missing rate → 422 on confirm.
 6. Double confirm → 409.

Phase 3 (settlements):
 7. VIP creates payout request → pending; positive_usdt unchanged; then admin
    approve → positive_usdt decreases by amount_usdt.
 8. VIP cannot request "collection" (422 — admin path only).
 9. Admin unilateral collection → status=confirmed instantly; negative_usdt
    decreases.
10. Admin unilateral payout → status=confirmed; positive_usdt decreases.
11. Non-VIP cannot create → 403; non-VIP target rejected → 422.
12. Reject a pending settlement → no ledger change.
13. Double approve → 409.
"""
import os
import pytest
import httpx

API_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001")
from conftest import NORMAL_TOKEN, VIP_TOKEN, EMPLOYEE_TOKEN, ADMIN_TOKEN


def h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _reset():
    from db_client import db
    await db.vip_capital_deposits.delete_many({"vip_user_id": "user_test_vip01"})
    await db.vip_settlements.delete_many({"vip_user_id": "user_test_vip01"})
    await db.vip_ledger.delete_many({"vip_user_id": "user_test_vip01"})


async def _ensure_rate(from_code: str, to_code: str, rate: float):
    from db_client import db
    await db.rates.update_one(
        {"from_code": from_code, "to_code": to_code},
        {"$set": {"from_code": from_code, "to_code": to_code,
                  "rate_normal": float(rate), "rate_vip": float(rate),
                  "real_rate": float(rate)}},
        upsert=True,
    )


async def _seed_positive(amount_usdt: float):
    from db_client import db
    await db.vip_ledger.update_one(
        {"vip_user_id": "user_test_vip01"},
        {"$set": {"positive_usdt": float(amount_usdt), "negative_usdt": 0.0,
                  "updated_at": "2026-01-01T00:00:00+00:00"}},
        upsert=True,
    )


# iter113 — capital deposits & payout settlements operate on the VIP's
# per-currency account balance (`users.vip_balances.USDT`), not the legacy
# ledger positive. These helpers read/restore it so tests on the shared dev
# DB never pollute the VIP's real balance.
async def _usdt_balance() -> float:
    from db_client import db
    u = await db.users.find_one({"user_id": "user_test_vip01"},
                                {"_id": 0, "vip_balances": 1})
    return float(((u or {}).get("vip_balances") or {}).get("USDT") or 0.0)


async def _inc_usdt_balance(delta: float):
    from db_client import db
    await db.users.update_one({"user_id": "user_test_vip01"},
                              {"$inc": {"vip_balances.USDT": float(delta)}})


async def _seed_negative(amount_usdt: float):
    from db_client import db
    await db.vip_ledger.update_one(
        {"vip_user_id": "user_test_vip01"},
        {"$set": {"positive_usdt": 0.0, "negative_usdt": float(amount_usdt),
                  "updated_at": "2026-01-01T00:00:00+00:00"}},
        upsert=True,
    )


VALID_DEPOSIT = {"currency": "USDT", "amount": 4000, "note": "capital inicial",
                 "deposit_method": "cash"}


class TestPhase2CapitalDeposits:
    @pytest.mark.asyncio
    async def test_vip_creates_deposit_pending(self):
        await _reset()
        async with httpx.AsyncClient(base_url=API_URL, timeout=30, transport=httpx.AsyncHTTPTransport(retries=2)) as c:
            r = await c.post("/api/vip/capital-deposits", headers=h(VIP_TOKEN),
                             json=VALID_DEPOSIT)
            assert r.status_code == 200, r.text
            assert r.json()["status"] == "pending"

            bal = (await c.get("/api/vip/balance", headers=h(VIP_TOKEN))).json()
            assert bal["positive_usdt"] == 0.0
        await _reset()

    @pytest.mark.asyncio
    async def test_admin_confirm_adds_to_positive(self):
        await _reset()
        await _ensure_rate("USDT", "USDT", 1.0)
        before = await _usdt_balance()
        try:
            async with httpx.AsyncClient(base_url=API_URL, timeout=30, transport=httpx.AsyncHTTPTransport(retries=2)) as c:
                r = await c.post("/api/vip/capital-deposits", headers=h(VIP_TOKEN),
                                 json=VALID_DEPOSIT)
                did = r.json()["id"]
                r_ok = await c.post(f"/api/admin/vip-capital-deposits/{did}/confirm",
                                    headers=h(ADMIN_TOKEN))
                assert r_ok.status_code == 200
                assert r_ok.json()["status"] == "confirmed"
                assert r_ok.json()["balance_delta_usdt"] == pytest.approx(4000.0)

                # iter113 — the confirmed capital lands in the account balance
                # (vip_balances.USDT); the legacy ledger positive stays at 0.
                after = await _usdt_balance()
                assert after - before == pytest.approx(4000.0)
                bal = (await c.get("/api/vip/balance", headers=h(VIP_TOKEN))).json()
                assert bal["positive_usdt"] == 0.0
        finally:
            drift = (await _usdt_balance()) - before
            if abs(drift) > 1e-9:
                await _inc_usdt_balance(-drift)
            await _reset()

    @pytest.mark.asyncio
    async def test_admin_reject_no_ledger(self):
        await _reset()
        async with httpx.AsyncClient(base_url=API_URL, timeout=30, transport=httpx.AsyncHTTPTransport(retries=2)) as c:
            r = await c.post("/api/vip/capital-deposits", headers=h(VIP_TOKEN),
                             json=VALID_DEPOSIT)
            did = r.json()["id"]
            r_rej = await c.post(f"/api/admin/vip-capital-deposits/{did}/reject",
                                 headers=h(ADMIN_TOKEN),
                                 json={"admin_note": "Foto poco clara."})
            assert r_rej.status_code == 200
            assert r_rej.json()["status"] == "rejected"
            bal = (await c.get("/api/vip/balance", headers=h(VIP_TOKEN))).json()
            assert bal["positive_usdt"] == 0.0
        await _reset()

    @pytest.mark.asyncio
    async def test_non_vip_cannot_create(self):
        async with httpx.AsyncClient(base_url=API_URL, timeout=30, transport=httpx.AsyncHTTPTransport(retries=2)) as c:
            for tok in (NORMAL_TOKEN, ADMIN_TOKEN, EMPLOYEE_TOKEN):
                r = await c.post("/api/vip/capital-deposits", headers=h(tok), json=VALID_DEPOSIT)
                assert r.status_code == 403, tok

    @pytest.mark.asyncio
    async def test_missing_rate_returns_422(self):
        from db_client import db
        await _reset()
        await db.rates.delete_many({"from_code": "XYZ2"})
        await db.rates.delete_many({"to_code": "XYZ2"})
        async with httpx.AsyncClient(base_url=API_URL, timeout=30, transport=httpx.AsyncHTTPTransport(retries=2)) as c:
            r = await c.post("/api/vip/capital-deposits", headers=h(VIP_TOKEN),
                             json={"currency": "XYZ2", "amount": 100,
                                   "deposit_method": "cash"})
            did = r.json()["id"]
            r_c = await c.post(f"/api/admin/vip-capital-deposits/{did}/confirm",
                               headers=h(ADMIN_TOKEN))
            assert r_c.status_code == 422
        await _reset()

    @pytest.mark.asyncio
    async def test_double_confirm_conflicts(self):
        await _reset()
        await _ensure_rate("USDT", "USDT", 1.0)
        before = await _usdt_balance()
        try:
            async with httpx.AsyncClient(base_url=API_URL, timeout=30, transport=httpx.AsyncHTTPTransport(retries=2)) as c:
                r = await c.post("/api/vip/capital-deposits", headers=h(VIP_TOKEN),
                                 json=VALID_DEPOSIT)
                did = r.json()["id"]
                await c.post(f"/api/admin/vip-capital-deposits/{did}/confirm",
                             headers=h(ADMIN_TOKEN))
                dup = await c.post(f"/api/admin/vip-capital-deposits/{did}/confirm",
                                   headers=h(ADMIN_TOKEN))
                assert dup.status_code == 409
        finally:
            drift = (await _usdt_balance()) - before
            if abs(drift) > 1e-9:
                await _inc_usdt_balance(-drift)
            await _reset()


PAYOUT = {"direction": "payout", "currency": "USDT", "amount": 500,
          "settlement_method": "crypto"}


class TestPhase3Settlements:
    @pytest.mark.asyncio
    async def test_vip_payout_request_flow(self):
        await _reset()
        await _ensure_rate("USDT", "USDT", 1.0)
        before = await _usdt_balance()
        try:
            async with httpx.AsyncClient(base_url=API_URL, timeout=30, transport=httpx.AsyncHTTPTransport(retries=2)) as c:
                r = await c.post("/api/vip/settlements", headers=h(VIP_TOKEN), json=PAYOUT)
                assert r.status_code == 200
                sid = r.json()["id"]
                assert r.json()["status"] == "pending"

                # balance unchanged before approve
                assert (await _usdt_balance()) == pytest.approx(before)

                r_ap = await c.post(f"/api/admin/vip-settlements/{sid}/approve",
                                    headers=h(ADMIN_TOKEN))
                assert r_ap.status_code == 200
                assert r_ap.json()["status"] == "confirmed"

                # iter113 — payouts debit the account balance (vip_balances.USDT).
                assert (await _usdt_balance()) - before == pytest.approx(-500.0)
        finally:
            drift = (await _usdt_balance()) - before
            if abs(drift) > 1e-9:
                await _inc_usdt_balance(-drift)
            await _reset()

    @pytest.mark.asyncio
    async def test_vip_cannot_request_collection(self):
        await _reset()
        await _ensure_rate("USDT", "USDT", 1.0)
        async with httpx.AsyncClient(base_url=API_URL, timeout=30, transport=httpx.AsyncHTTPTransport(retries=2)) as c:
            r = await c.post("/api/vip/settlements", headers=h(VIP_TOKEN),
                             json={**PAYOUT, "direction": "collection"})
            assert r.status_code == 422
        await _reset()

    @pytest.mark.asyncio
    async def test_admin_unilateral_collection_decreases_negative(self):
        await _reset()
        await _ensure_rate("USDT", "USDT", 1.0)
        await _seed_negative(800)
        async with httpx.AsyncClient(base_url=API_URL, timeout=30, transport=httpx.AsyncHTTPTransport(retries=2)) as c:
            r = await c.post("/api/admin/vip-settlements", headers=h(ADMIN_TOKEN),
                             json={"vip_user_id": "user_test_vip01",
                                   "direction": "collection",
                                   "currency": "USDT", "amount": 300,
                                   "settlement_method": "cash",
                                   "note": "recibí 300 USDT"})
            assert r.status_code == 200
            assert r.json()["status"] == "confirmed"

            bal = (await c.get("/api/vip/balance", headers=h(VIP_TOKEN))).json()
            assert bal["negative_usdt"] == pytest.approx(500.0)
        await _reset()

    @pytest.mark.asyncio
    async def test_admin_unilateral_payout_decreases_positive(self):
        await _reset()
        await _ensure_rate("USDT", "USDT", 1.0)
        before = await _usdt_balance()
        try:
            async with httpx.AsyncClient(base_url=API_URL, timeout=30, transport=httpx.AsyncHTTPTransport(retries=2)) as c:
                r = await c.post("/api/admin/vip-settlements", headers=h(ADMIN_TOKEN),
                                 json={"vip_user_id": "user_test_vip01",
                                       "direction": "payout",
                                       "currency": "USDT", "amount": 250,
                                       "settlement_method": "bank_transfer"})
                assert r.status_code == 200
                # iter113 — unilateral payouts debit the account balance.
                assert (await _usdt_balance()) - before == pytest.approx(-250.0)
        finally:
            drift = (await _usdt_balance()) - before
            if abs(drift) > 1e-9:
                await _inc_usdt_balance(-drift)
            await _reset()

    @pytest.mark.asyncio
    async def test_admin_unilateral_target_must_be_vip(self):
        await _reset()
        await _ensure_rate("USDT", "USDT", 1.0)
        async with httpx.AsyncClient(base_url=API_URL, timeout=30, transport=httpx.AsyncHTTPTransport(retries=2)) as c:
            r = await c.post("/api/admin/vip-settlements", headers=h(ADMIN_TOKEN),
                             json={"vip_user_id": "user_test_normal01",
                                   "direction": "payout",
                                   "currency": "USDT", "amount": 10,
                                   "settlement_method": "cash"})
            assert r.status_code == 422
        await _reset()

    @pytest.mark.asyncio
    async def test_reject_pending_no_ledger(self):
        await _reset()
        await _ensure_rate("USDT", "USDT", 1.0)
        await _seed_positive(500)
        async with httpx.AsyncClient(base_url=API_URL, timeout=30, transport=httpx.AsyncHTTPTransport(retries=2)) as c:
            r = await c.post("/api/vip/settlements", headers=h(VIP_TOKEN), json=PAYOUT)
            sid = r.json()["id"]
            r_r = await c.post(f"/api/admin/vip-settlements/{sid}/reject",
                               headers=h(ADMIN_TOKEN), json={"admin_note": "sin fondos"})
            assert r_r.status_code == 200
            bal = (await c.get("/api/vip/balance", headers=h(VIP_TOKEN))).json()
            assert bal["positive_usdt"] == pytest.approx(500.0)
        await _reset()

    @pytest.mark.asyncio
    async def test_double_approve_conflicts(self):
        await _reset()
        await _ensure_rate("USDT", "USDT", 1.0)
        await _seed_positive(1000)
        async with httpx.AsyncClient(base_url=API_URL, timeout=30, transport=httpx.AsyncHTTPTransport(retries=2)) as c:
            r = await c.post("/api/vip/settlements", headers=h(VIP_TOKEN), json=PAYOUT)
            sid = r.json()["id"]
            await c.post(f"/api/admin/vip-settlements/{sid}/approve",
                         headers=h(ADMIN_TOKEN))
            dup = await c.post(f"/api/admin/vip-settlements/{sid}/approve",
                               headers=h(ADMIN_TOKEN))
            assert dup.status_code == 409
        await _reset()
