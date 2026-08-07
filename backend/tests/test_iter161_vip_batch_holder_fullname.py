"""iter161 — VIP batch add-item: no card required, holder full name mandatory."""
import os
import pytest
import httpx

from conftest import VIP_TOKEN

API_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001")


def h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _ensure_currency(code: str, name: str, ctype: str = "fiat",
                           extra: dict | None = None):
    from db_client import db
    doc = {"code": code, "name": name, "type": ctype, "is_active": True}
    if extra:
        doc.update(extra)
    await db.currencies.update_one({"code": code}, {"$set": doc}, upsert=True)


async def _ensure_rate(fc: str, tc: str, rate: float = 350.0):
    from db_client import db
    await db.rates.update_one(
        {"from_code": fc, "to_code": tc},
        {"$set": {"from_code": fc, "to_code": tc,
                  "rate_normal": float(rate), "rate_vip": float(rate),
                  "real_rate": float(rate)}},
        upsert=True,
    )


async def _cleanup_test_batches():
    from db_client import db
    ids = [b["id"] async for b in db.vip_batches.find(
        {"vip_user_id": "user_test_vip01"}, {"id": 1, "_id": 0})]
    if ids:
        await db.vip_batch_items.delete_many({"batch_id": {"$in": ids}})
        await db.vip_batches.delete_many({"id": {"$in": ids}})


def teardown_module(module):
    """Restore the canonical seeded USDT→CUP rate (380/395/410) so sibling
    suites (test_vip_convert expects rate_vip=395) are not polluted."""
    import os
    from pymongo import MongoClient
    db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    db.rates.update_one(
        {"from_code": "USDT", "to_code": "CUP"},
        {"$set": {"rate_normal": 380.0, "rate_vip": 395.0, "real_rate": 410.0}},
    )


async def _create_pair_batch(c: httpx.AsyncClient) -> dict:
    await _cleanup_test_batches()
    await _ensure_currency("USDT", "Tether", "crypto")
    await _ensure_currency("CUP", "Peso Cubano", "fiat",
                           extra={"requires_cup_card": True})
    await _ensure_rate("USDT", "CUP", 350.0)
    r = await c.post("/api/vip/batches", headers=h(VIP_TOKEN),
                     json={"from_code": "USDT", "to_code": "CUP",
                           "note": "iter161-test"})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.asyncio
async def test_create_pair_batch_requires_card_false():
    async with httpx.AsyncClient(base_url=API_URL, timeout=30) as c:
        batch = await _create_pair_batch(c)
        assert batch.get("requires_card") is False, batch
    await _cleanup_test_batches()


@pytest.mark.asyncio
async def test_get_batch_detail_requires_card_false_even_when_legacy_true():
    async with httpx.AsyncClient(base_url=API_URL, timeout=30) as c:
        batch = await _create_pair_batch(c)
        from db_client import db
        await db.vip_batches.update_one(
            {"id": batch["id"]}, {"$set": {"requires_card": True}})
        r = await c.get(f"/api/vip/batches/{batch['id']}", headers=h(VIP_TOKEN))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["batch"].get("requires_card") is False, body["batch"]
    await _cleanup_test_batches()


@pytest.mark.asyncio
async def test_single_word_holder_rejected():
    async with httpx.AsyncClient(base_url=API_URL, timeout=30) as c:
        batch = await _create_pair_batch(c)
        r = await c.post(f"/api/vip/batches/{batch['id']}/items",
                         headers=h(VIP_TOKEN),
                         json={"items": [{"holder_name": "Juan", "amount": 10}]})
        assert r.status_code == 422, r.text
        detail = (r.json().get("detail") or "").lower()
        assert "nombre" in detail and "apellido" in detail, detail
    await _cleanup_test_batches()


@pytest.mark.asyncio
async def test_empty_holder_rejected():
    async with httpx.AsyncClient(base_url=API_URL, timeout=30) as c:
        batch = await _create_pair_batch(c)
        r = await c.post(f"/api/vip/batches/{batch['id']}/items",
                         headers=h(VIP_TOKEN),
                         json={"items": [{"holder_name": "", "amount": 10}]})
        assert r.status_code == 422
    await _cleanup_test_batches()


@pytest.mark.asyncio
async def test_full_name_accepted_no_card():
    async with httpx.AsyncClient(base_url=API_URL, timeout=30) as c:
        batch = await _create_pair_batch(c)
        r = await c.post(f"/api/vip/batches/{batch['id']}/items",
                         headers=h(VIP_TOKEN),
                         json={"items": [{"holder_name": "Juan Pérez",
                                          "amount": 12.5}]})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["added"] == 1
        item = body["items"][0]
        assert item["holder_name"] == "Juan Pérez"
        assert item["card_number"] is None, item
        assert item["amount"] == 12.5

        g = await c.get(f"/api/vip/batches/{batch['id']}", headers=h(VIP_TOKEN))
        assert g.status_code == 200
        gitem = next(i for i in g.json()["items"] if i["id"] == item["id"])
        assert gitem["card_number"] is None
    await _cleanup_test_batches()


@pytest.mark.asyncio
async def test_card_number_in_payload_is_ignored():
    async with httpx.AsyncClient(base_url=API_URL, timeout=30) as c:
        batch = await _create_pair_batch(c)
        r = await c.post(f"/api/vip/batches/{batch['id']}/items",
                         headers=h(VIP_TOKEN),
                         json={"items": [{"holder_name": "María López",
                                          "amount": 5,
                                          "card_number": "9204123456789012"}]})
        assert r.status_code == 200, r.text
        item = r.json()["items"][0]
        assert item["card_number"] is None, item
    await _cleanup_test_batches()
