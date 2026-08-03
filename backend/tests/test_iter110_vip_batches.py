"""iter110 · Phase 1 — VIP batch operations + running USDT balance.

Coverage:
 1. Only role="vip" can create/list batches (403 for normal + admin + employee).
 2. VIP creates a credit batch, adds items, admin approves each → positive_usdt++.
 3. VIP creates a debit batch, admin approves → negative_usdt++.
 4. Batch totals (pending/approved/rejected + amount) update on decision.
 5. Reject sets status=rejected and does NOT touch ledger.
 6. Closing a batch blocks further items.
 7. Duplicate approve → 409.
 8. Missing rate → 422, ledger untouched.
 9. Employee without `orders` permission cannot approve.
10. GET /vip/balance mirrors the ledger.
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
    await db.vip_batches.delete_many({"vip_user_id": "user_test_vip01"})
    await db.vip_batch_items.delete_many({"vip_user_id": "user_test_vip01"})
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


class TestVipBatches:
    @pytest.mark.asyncio
    async def test_only_vip_can_create(self):
        await _reset()
        async with httpx.AsyncClient(base_url=API_URL, timeout=30, transport=httpx.AsyncHTTPTransport(retries=2)) as c:
            body = {"direction": "credit", "currency": "USDT"}
            for tok in (NORMAL_TOKEN, ADMIN_TOKEN, EMPLOYEE_TOKEN):
                r = await c.post("/api/vip/batches", headers=h(tok), json=body)
                assert r.status_code == 403, (tok, r.text)

            # VIP OK
            r = await c.post("/api/vip/batches", headers=h(VIP_TOKEN), json=body)
            assert r.status_code == 200
        await _reset()

    @pytest.mark.asyncio
    async def test_credit_flow_increments_positive(self):
        await _reset()
        await _ensure_rate("USDT", "USDT", 1.0)  # identity rate for USDT
        async with httpx.AsyncClient(base_url=API_URL, timeout=30, transport=httpx.AsyncHTTPTransport(retries=2)) as c:
            b = await c.post("/api/vip/batches", headers=h(VIP_TOKEN),
                             json={"direction": "credit", "currency": "USDT"})
            bid = b.json()["id"]
            r_add = await c.post(
                f"/api/vip/batches/{bid}/items", headers=h(VIP_TOKEN),
                json={"items": [
                    {"holder_name": "Arianna", "amount": 150},
                    {"holder_name": "Alberto", "amount": 459},
                ]},
            )
            assert r_add.status_code == 200
            assert r_add.json()["added"] == 2

            items = (await c.get(f"/api/vip/batches/{bid}", headers=h(VIP_TOKEN))).json()["items"]
            for it in items:
                r_ap = await c.post(
                    f"/api/admin/vip-batches/items/{it['id']}/approve",
                    headers=h(ADMIN_TOKEN),
                )
                assert r_ap.status_code == 200
                assert r_ap.json()["balance_delta_usdt"] > 0

            bal = (await c.get("/api/vip/balance", headers=h(VIP_TOKEN))).json()
            assert bal["positive_usdt"] == pytest.approx(609.0, abs=0.01)
            assert bal["negative_usdt"] == 0.0
        await _reset()

    @pytest.mark.asyncio
    async def test_debit_flow_increments_negative(self):
        await _reset()
        await _ensure_rate("USDT", "USDT", 1.0)
        async with httpx.AsyncClient(base_url=API_URL, timeout=30, transport=httpx.AsyncHTTPTransport(retries=2)) as c:
            b = await c.post("/api/vip/batches", headers=h(VIP_TOKEN),
                             json={"direction": "debit", "currency": "USDT"})
            bid = b.json()["id"]
            await c.post(f"/api/vip/batches/{bid}/items", headers=h(VIP_TOKEN),
                         json={"items": [{"holder_name": "Cliente A", "amount": 300}]})

            it = (await c.get(f"/api/vip/batches/{bid}", headers=h(VIP_TOKEN))).json()["items"][0]
            r_ap = await c.post(
                f"/api/admin/vip-batches/items/{it['id']}/approve",
                headers=h(ADMIN_TOKEN),
            )
            assert r_ap.status_code == 200

            bal = (await c.get("/api/vip/balance", headers=h(VIP_TOKEN))).json()
            assert bal["negative_usdt"] == pytest.approx(300.0)
            assert bal["positive_usdt"] == 0.0
            assert bal["net_usdt"] == pytest.approx(-300.0)
        await _reset()

    @pytest.mark.asyncio
    async def test_reject_does_not_touch_ledger(self):
        await _reset()
        await _ensure_rate("USDT", "USDT", 1.0)
        async with httpx.AsyncClient(base_url=API_URL, timeout=30, transport=httpx.AsyncHTTPTransport(retries=2)) as c:
            b = await c.post("/api/vip/batches", headers=h(VIP_TOKEN),
                             json={"direction": "credit", "currency": "USDT"})
            bid = b.json()["id"]
            await c.post(f"/api/vip/batches/{bid}/items", headers=h(VIP_TOKEN),
                         json={"items": [{"holder_name": "X", "amount": 100}]})
            it = (await c.get(f"/api/vip/batches/{bid}", headers=h(VIP_TOKEN))).json()["items"][0]

            r_rej = await c.post(
                f"/api/admin/vip-batches/items/{it['id']}/reject",
                headers=h(ADMIN_TOKEN),
                json={"admin_note": "El titular no coincide."},
            )
            assert r_rej.status_code == 200
            assert r_rej.json()["status"] == "rejected"
            assert r_rej.json()["balance_delta_usdt"] is None

            bal = (await c.get("/api/vip/balance", headers=h(VIP_TOKEN))).json()
            assert bal["positive_usdt"] == 0.0
        await _reset()

    @pytest.mark.asyncio
    async def test_close_blocks_new_items(self):
        await _reset()
        async with httpx.AsyncClient(base_url=API_URL, timeout=30, transport=httpx.AsyncHTTPTransport(retries=2)) as c:
            b = await c.post("/api/vip/batches", headers=h(VIP_TOKEN),
                             json={"direction": "credit", "currency": "USDT"})
            bid = b.json()["id"]
            close = await c.post(f"/api/vip/batches/{bid}/close", headers=h(VIP_TOKEN))
            assert close.status_code == 200

            r_add = await c.post(
                f"/api/vip/batches/{bid}/items", headers=h(VIP_TOKEN),
                json={"items": [{"holder_name": "Y", "amount": 50}]},
            )
            assert r_add.status_code == 409
        await _reset()

    @pytest.mark.asyncio
    async def test_double_approve_conflicts(self):
        await _reset()
        await _ensure_rate("USDT", "USDT", 1.0)
        async with httpx.AsyncClient(base_url=API_URL, timeout=30, transport=httpx.AsyncHTTPTransport(retries=2)) as c:
            b = await c.post("/api/vip/batches", headers=h(VIP_TOKEN),
                             json={"direction": "credit", "currency": "USDT"})
            bid = b.json()["id"]
            await c.post(f"/api/vip/batches/{bid}/items", headers=h(VIP_TOKEN),
                         json={"items": [{"holder_name": "Z", "amount": 20}]})
            it = (await c.get(f"/api/vip/batches/{bid}", headers=h(VIP_TOKEN))).json()["items"][0]
            await c.post(f"/api/admin/vip-batches/items/{it['id']}/approve",
                         headers=h(ADMIN_TOKEN))
            dup = await c.post(f"/api/admin/vip-batches/items/{it['id']}/approve",
                               headers=h(ADMIN_TOKEN))
            assert dup.status_code == 409
        await _reset()

    @pytest.mark.asyncio
    async def test_missing_rate_returns_422(self):
        from db_client import db
        await _reset()
        # Delete any XYZ rate so conversion fails.
        await db.rates.delete_many({"from_code": "XYZ"})
        await db.rates.delete_many({"to_code": "XYZ"})
        async with httpx.AsyncClient(base_url=API_URL, timeout=30, transport=httpx.AsyncHTTPTransport(retries=2)) as c:
            b = await c.post("/api/vip/batches", headers=h(VIP_TOKEN),
                             json={"direction": "credit", "currency": "XYZ"})
            bid = b.json()["id"]
            await c.post(f"/api/vip/batches/{bid}/items", headers=h(VIP_TOKEN),
                         json={"items": [{"holder_name": "T", "amount": 1}]})
            it = (await c.get(f"/api/vip/batches/{bid}", headers=h(VIP_TOKEN))).json()["items"][0]
            r = await c.post(f"/api/admin/vip-batches/items/{it['id']}/approve",
                             headers=h(ADMIN_TOKEN))
            assert r.status_code == 422

            bal = (await c.get("/api/vip/balance", headers=h(VIP_TOKEN))).json()
            assert bal["positive_usdt"] == 0.0
        await _reset()

    @pytest.mark.asyncio
    async def test_scoped_employee_without_orders_perm_403(self):
        from db_client import db
        await _reset()
        await _ensure_rate("USDT", "USDT", 1.0)
        await db.users.update_one(
            {"user_id": "user_test_employee01"},
            {"$set": {"allowed_permissions": ["kyc"]}},
        )
        try:
            async with httpx.AsyncClient(base_url=API_URL, timeout=30, transport=httpx.AsyncHTTPTransport(retries=2)) as c:
                b = await c.post("/api/vip/batches", headers=h(VIP_TOKEN),
                                 json={"direction": "credit", "currency": "USDT"})
                bid = b.json()["id"]
                await c.post(f"/api/vip/batches/{bid}/items", headers=h(VIP_TOKEN),
                             json={"items": [{"holder_name": "P", "amount": 10}]})
                it = (await c.get(f"/api/vip/batches/{bid}", headers=h(VIP_TOKEN))).json()["items"][0]
                r = await c.post(f"/api/admin/vip-batches/items/{it['id']}/approve",
                                 headers=h(EMPLOYEE_TOKEN))
                assert r.status_code == 403
        finally:
            await db.users.update_one(
                {"user_id": "user_test_employee01"},
                {"$set": {"allowed_permissions": []}},
            )
            await _reset()

    @pytest.mark.asyncio
    async def test_batch_totals_update(self):
        await _reset()
        await _ensure_rate("USDT", "USDT", 1.0)
        async with httpx.AsyncClient(base_url=API_URL, timeout=30, transport=httpx.AsyncHTTPTransport(retries=2)) as c:
            b = await c.post("/api/vip/batches", headers=h(VIP_TOKEN),
                             json={"direction": "credit", "currency": "USDT"})
            bid = b.json()["id"]
            await c.post(f"/api/vip/batches/{bid}/items", headers=h(VIP_TOKEN),
                         json={"items": [
                             {"holder_name": "A", "amount": 100},
                             {"holder_name": "B", "amount": 200},
                             {"holder_name": "C", "amount": 300},
                         ]})
            items = (await c.get(f"/api/vip/batches/{bid}", headers=h(VIP_TOKEN))).json()["items"]
            # Approve 2, reject 1.
            await c.post(f"/api/admin/vip-batches/items/{items[0]['id']}/approve",
                         headers=h(ADMIN_TOKEN))
            await c.post(f"/api/admin/vip-batches/items/{items[1]['id']}/approve",
                         headers=h(ADMIN_TOKEN))
            await c.post(f"/api/admin/vip-batches/items/{items[2]['id']}/reject",
                         headers=h(ADMIN_TOKEN), json={"admin_note": ""})

            batch = (await c.get(f"/api/vip/batches/{bid}", headers=h(VIP_TOKEN))).json()["batch"]
            assert batch["items_approved"] == 2
            assert batch["items_rejected"] == 1
            assert batch["items_pending"] == 0
            assert batch["amount_approved"] == pytest.approx(300.0)
        await _reset()

    @pytest.mark.asyncio
    async def test_pending_count_endpoint(self):
        await _reset()
        async with httpx.AsyncClient(base_url=API_URL, timeout=30, transport=httpx.AsyncHTTPTransport(retries=2)) as c:
            r0 = (await c.get("/api/admin/vip-batches/pending-count",
                              headers=h(ADMIN_TOKEN))).json()
            base = r0["pending"]

            b = await c.post("/api/vip/batches", headers=h(VIP_TOKEN),
                             json={"direction": "credit", "currency": "USDT"})
            bid = b.json()["id"]
            await c.post(f"/api/vip/batches/{bid}/items", headers=h(VIP_TOKEN),
                         json={"items": [{"holder_name": "N", "amount": 5},
                                          {"holder_name": "N2", "amount": 6}]})
            r1 = (await c.get("/api/admin/vip-batches/pending-count",
                              headers=h(ADMIN_TOKEN))).json()
            assert r1["pending"] == base + 2
        await _reset()
