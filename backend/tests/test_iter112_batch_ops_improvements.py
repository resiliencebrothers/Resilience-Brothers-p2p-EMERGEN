"""iter112 — Mejoras operativas de la sección de lotes VIP.

Coverage:
 1. `/admin/vip-batches/pending-count` returns items/capital/settlements
    counters and reflects a planted pending capital deposit.
 2. `/vip/batch-currencies` returns only currencies with a USDT rate path,
    USDT first; VIP-only (403 for normal client).
 3. Capital deposit without `deposit_method` → 422.
 4. Transfer deposit without proof → 422; with proof but no holder → 422.
 5. Crypto deposit without tx hash → 422.
 6. Cash deposit needs nothing extra → 200 pending.
 7. Transfer happy path persists method + holder + proof.
 8. Crypto happy path persists tx_hash.
"""
import os
import pytest
import httpx

API_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001")
from conftest import NORMAL_TOKEN, VIP_TOKEN, ADMIN_TOKEN


def h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


PROOF = (
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
    "AAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


async def _reset():
    from db_client import db
    await db.vip_capital_deposits.delete_many({"vip_user_id": "user_test_vip01"})
    await db.currencies.delete_many({"code": "ZZTEST"})


async def _ensure_rate(from_code: str, to_code: str, rate: float):
    from db_client import db
    await db.rates.update_one(
        {"from_code": from_code, "to_code": to_code},
        {"$set": {"from_code": from_code, "to_code": to_code,
                  "rate_normal": float(rate), "rate_vip": float(rate),
                  "real_rate": float(rate)}},
        upsert=True,
    )


async def _ensure_currency(code: str, name: str, ctype: str = "fiat"):
    from db_client import db
    await db.currencies.update_one(
        {"code": code},
        {"$set": {"code": code, "name": name, "type": ctype, "is_active": True}},
        upsert=True,
    )


class TestPendingCount:
    @pytest.mark.asyncio
    async def test_counters_shape_and_capital_pending(self):
        await _reset()
        async with httpx.AsyncClient(base_url=API_URL, timeout=30) as c:
            r = await c.post("/api/vip/capital-deposits", headers=h(VIP_TOKEN),
                             json={"currency": "USDT", "amount": 100,
                                   "deposit_method": "cash"})
            assert r.status_code == 200, r.text

            rc = await c.get("/api/admin/vip-batches/pending-count", headers=h(ADMIN_TOKEN))
            assert rc.status_code == 200
            body = rc.json()
            for key in ("pending", "items_pending", "capital_pending",
                        "settlements_pending", "total_pending"):
                assert key in body, f"missing {key}"
            assert body["capital_pending"] >= 1
            assert body["total_pending"] >= body["capital_pending"]
        await _reset()

    @pytest.mark.asyncio
    async def test_counter_forbidden_for_vip(self):
        async with httpx.AsyncClient(base_url=API_URL, timeout=30) as c:
            r = await c.get("/api/admin/vip-batches/pending-count", headers=h(VIP_TOKEN))
            assert r.status_code == 403


class TestBatchCurrencies:
    @pytest.mark.asyncio
    async def test_only_currencies_with_rates_usdt_first(self):
        await _reset()
        await _ensure_currency("USDT", "Tether", "crypto")
        await _ensure_currency("ZZTEST", "Sin tasa configurada")
        await _ensure_rate("USDT", "USDT", 1.0)
        async with httpx.AsyncClient(base_url=API_URL, timeout=30) as c:
            r = await c.get("/api/vip/batch-currencies", headers=h(VIP_TOKEN))
            assert r.status_code == 200, r.text
            items = r.json()["items"]
            codes = [i["code"] for i in items]
            assert "USDT" in codes
            assert codes[0] == "USDT"
            assert "ZZTEST" not in codes
            usdt = items[0]
            assert usdt["usdt_per_unit"] == 1.0
        await _reset()

    @pytest.mark.asyncio
    async def test_vip_only(self):
        async with httpx.AsyncClient(base_url=API_URL, timeout=30) as c:
            r = await c.get("/api/vip/batch-currencies", headers=h(NORMAL_TOKEN))
            assert r.status_code == 403


class TestCapitalDepositValidation:
    @pytest.mark.asyncio
    async def test_method_required(self):
        async with httpx.AsyncClient(base_url=API_URL, timeout=30) as c:
            r = await c.post("/api/vip/capital-deposits", headers=h(VIP_TOKEN),
                             json={"currency": "USDT", "amount": 100})
            assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_transfer_requires_proof(self):
        async with httpx.AsyncClient(base_url=API_URL, timeout=30) as c:
            r = await c.post("/api/vip/capital-deposits", headers=h(VIP_TOKEN),
                             json={"currency": "USDT", "amount": 100,
                                   "deposit_method": "bank_transfer",
                                   "account_holder": "Juan Pérez"})
            assert r.status_code == 422
            assert "captura" in r.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_transfer_requires_holder(self):
        async with httpx.AsyncClient(base_url=API_URL, timeout=30) as c:
            r = await c.post("/api/vip/capital-deposits", headers=h(VIP_TOKEN),
                             json={"currency": "USDT", "amount": 100,
                                   "deposit_method": "zelle",
                                   "proof_image": PROOF})
            assert r.status_code == 422
            assert "titular" in r.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_crypto_requires_hash(self):
        async with httpx.AsyncClient(base_url=API_URL, timeout=30) as c:
            r = await c.post("/api/vip/capital-deposits", headers=h(VIP_TOKEN),
                             json={"currency": "USDT", "amount": 100,
                                   "deposit_method": "crypto",
                                   "account_holder": "Juan Pérez",
                                   "proof_image": PROOF})
            assert r.status_code == 422
            assert "hash" in r.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_cash_needs_nothing_extra(self):
        await _reset()
        async with httpx.AsyncClient(base_url=API_URL, timeout=30) as c:
            r = await c.post("/api/vip/capital-deposits", headers=h(VIP_TOKEN),
                             json={"currency": "USDT", "amount": 200,
                                   "deposit_method": "cash"})
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["status"] == "pending"
            assert body["deposit_method"] == "cash"
        await _reset()

    @pytest.mark.asyncio
    async def test_transfer_happy_path_persists_fields(self):
        await _reset()
        async with httpx.AsyncClient(base_url=API_URL, timeout=30) as c:
            r = await c.post("/api/vip/capital-deposits", headers=h(VIP_TOKEN),
                             json={"currency": "USDT", "amount": 500,
                                   "deposit_method": "bank_transfer",
                                   "account_holder": "María García",
                                   "proof_image": PROOF})
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["deposit_method"] == "bank_transfer"
            assert body["account_holder"] == "María García"
            assert body["proof_url"]  # stored ref or base64 fallback

            rl = await c.get("/api/admin/vip-capital-deposits",
                             headers=h(ADMIN_TOKEN), params={"status": "pending"})
            row = next(i for i in rl.json()["items"] if i["id"] == body["id"])
            assert row["account_holder"] == "María García"
        await _reset()

    @pytest.mark.asyncio
    async def test_crypto_happy_path_persists_hash(self):
        await _reset()
        tx = "a" * 64
        async with httpx.AsyncClient(base_url=API_URL, timeout=30) as c:
            r = await c.post("/api/vip/capital-deposits", headers=h(VIP_TOKEN),
                             json={"currency": "USDT", "amount": 500,
                                   "deposit_method": "crypto",
                                   "account_holder": "María García",
                                   "tx_hash": tx,
                                   "proof_image": PROOF})
            assert r.status_code == 200, r.text
            assert r.json()["tx_hash"] == tx
        await _reset()


def _crypto_payload(tx: str, amount: float = 300) -> dict:
    return {"currency": "USDT", "amount": amount, "deposit_method": "crypto",
            "account_holder": "Ana Ruiz", "tx_hash": tx, "proof_image": PROOF}


class TestDuplicateHashGuard:
    @pytest.mark.asyncio
    async def test_duplicate_flags_blocks_and_force_overrides(self):
        await _reset()
        await _ensure_rate("USDT", "USDT", 1.0)
        tx = "b" * 64
        async with httpx.AsyncClient(base_url=API_URL, timeout=30) as c:
            r1 = await c.post("/api/vip/capital-deposits", headers=h(VIP_TOKEN),
                              json=_crypto_payload(tx))
            d1 = r1.json()["id"]
            ok = await c.post(f"/api/admin/vip-capital-deposits/{d1}/confirm",
                              headers=h(ADMIN_TOKEN))
            assert ok.status_code == 200, ok.text

            r2 = await c.post("/api/vip/capital-deposits", headers=h(VIP_TOKEN),
                              json=_crypto_payload(tx, amount=450))
            d2 = r2.json()["id"]

            rl = await c.get("/api/admin/vip-capital-deposits",
                             headers=h(ADMIN_TOKEN), params={"status": "pending"})
            row = next(i for i in rl.json()["items"] if i["id"] == d2)
            assert row["duplicate_hash"] is True

            blocked = await c.post(f"/api/admin/vip-capital-deposits/{d2}/confirm",
                                   headers=h(ADMIN_TOKEN))
            assert blocked.status_code == 409, blocked.text
            det = blocked.json()["detail"]
            assert det["code"] == "DUPLICATE_TX_HASH"
            assert any(d["id"] == d1 for d in det["duplicates"])

            forced = await c.post(f"/api/admin/vip-capital-deposits/{d2}/confirm",
                                  headers=h(ADMIN_TOKEN), json={"force": True})
            assert forced.status_code == 200, forced.text
            assert forced.json()["status"] == "confirmed"
        await _reset()

    @pytest.mark.asyncio
    async def test_rejected_duplicate_does_not_block(self):
        await _reset()
        await _ensure_rate("USDT", "USDT", 1.0)
        tx = "c" * 64
        async with httpx.AsyncClient(base_url=API_URL, timeout=30) as c:
            r1 = await c.post("/api/vip/capital-deposits", headers=h(VIP_TOKEN),
                              json=_crypto_payload(tx))
            d1 = r1.json()["id"]
            rej = await c.post(f"/api/admin/vip-capital-deposits/{d1}/reject",
                               headers=h(ADMIN_TOKEN), json={"admin_note": "borrosa"})
            assert rej.status_code == 200

            r2 = await c.post("/api/vip/capital-deposits", headers=h(VIP_TOKEN),
                              json=_crypto_payload(tx))
            d2 = r2.json()["id"]

            rl = await c.get("/api/admin/vip-capital-deposits",
                             headers=h(ADMIN_TOKEN), params={"status": "pending"})
            row = next(i for i in rl.json()["items"] if i["id"] == d2)
            assert row["duplicate_hash"] is False

            ok = await c.post(f"/api/admin/vip-capital-deposits/{d2}/confirm",
                              headers=h(ADMIN_TOKEN))
            assert ok.status_code == 200, ok.text
        await _reset()

    @pytest.mark.asyncio
    async def test_no_hash_deposits_never_flagged(self):
        await _reset()
        await _ensure_rate("USDT", "USDT", 1.0)
        async with httpx.AsyncClient(base_url=API_URL, timeout=30) as c:
            for _ in range(2):
                r = await c.post("/api/vip/capital-deposits", headers=h(VIP_TOKEN),
                                 json={"currency": "USDT", "amount": 50,
                                       "deposit_method": "cash"})
                assert r.status_code == 200
            rl = await c.get("/api/admin/vip-capital-deposits",
                             headers=h(ADMIN_TOKEN), params={"status": "pending"})
            for row in rl.json()["items"]:
                assert row["duplicate_hash"] is False
        await _reset()
