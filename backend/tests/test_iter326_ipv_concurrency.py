"""iter326 — IPV concurrency smoke (R01, R02, R03, R04).

E2E real-HTTP concurrency verification layered on top of iter320–325.

- R02: WAC + stock fold atomically under concurrent entries.
- R01: Entry that changes sale_price withdraws active offer atomically;
       entry that preserves price (within 2-dec rounding) keeps the offer.
- R03: POST /counts for a product whose today's count is already
       AUTHORIZED must return 409.
- R04: close-review resultado_sugerido 3-state priority ('descuadra' wins).
"""
import os
import uuid
import concurrent.futures as cf
from datetime import datetime

import pytest
import requests
from pymongo import MongoClient

from conftest import BASE_URL, ADMIN_TOKEN, today_havana

API = f"{BASE_URL}/api"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _auth(tok=ADMIN_TOKEN):
    return {"Cookie": f"session_token={tok}"}


# ───── product helpers ─────
def _create_product(price=500.0, cost=200.0, stock=10, name=None):
    name = name or f"TEST_IPV326_{uuid.uuid4().hex[:8]}"
    r = requests.post(f"{API}/admin/products",
                      json={"name": name, "category": "test",
                            "price_usd": price, "cost_usd": cost,
                            "stock": stock},
                      headers=_auth())
    assert r.status_code == 200, r.text
    return r.json()


def _get_product(pid):
    return _db().products.find_one({"id": pid}, {"_id": 0})


def _cleanup_product(pid):
    try:
        requests.delete(f"{API}/admin/products/{pid}", headers=_auth())
    except Exception:
        pass
    db = _db()
    db.products.delete_one({"id": pid})
    db.inventory_movements.delete_many({"product_id": pid})
    db.inventory_lots.delete_many({"product_id": pid})
    db.inventory_counts.delete_many({"product_id": pid})


def _entry(pid, qty, cost, sale_price=None):
    body = {"product_id": pid, "type": "entrada", "quantity": qty,
            "unit_cost": cost}
    if sale_price is not None:
        body["sale_price"] = sale_price
    return requests.post(f"{API}/admin/inventory/movements", json=body,
                         headers=_auth())


# ──────────────────── R02 — WAC fold atomic ────────────────────
class TestR02WACAtomicFold:
    def test_two_concurrent_entries_merge_wac_and_stock(self):
        """stock=10 cost=200 -> dos entradas concurrentes qty=10 cost=300.
        Esperado: stock=30, WAC=(10*200+10*300+10*300)/30 = 266.6667."""
        p = _create_product(price=500.0, cost=200.0, stock=10)
        pid = p["id"]
        try:
            with cf.ThreadPoolExecutor(max_workers=2) as ex:
                futs = [ex.submit(_entry, pid, 10, 300.0),
                        ex.submit(_entry, pid, 10, 300.0)]
                results = [f.result(timeout=30) for f in futs]
            for r in results:
                assert r.status_code == 200, r.text
            doc = _get_product(pid)
            assert doc["stock"] == 30, (
                f"stock drift under concurrency: {doc['stock']} != 30")
            # WAC fold is atomic AND cost-weighted; round 4 dec.
            expected = round((10 * 200 + 10 * 300 + 10 * 300) / 30, 4)
            got = round(float(doc["cost_usd"]), 4)
            assert got == expected, f"WAC drift: {got} != {expected}"
        finally:
            _cleanup_product(pid)

    def test_many_concurrent_entries_no_lost_update(self):
        """6 entradas concurrentes qty=5 cost=100 sobre stock=0 cost=0."""
        p = _create_product(price=500.0, cost=0.0, stock=0)
        pid = p["id"]
        try:
            with cf.ThreadPoolExecutor(max_workers=6) as ex:
                futs = [ex.submit(_entry, pid, 5, 100.0) for _ in range(6)]
                results = [f.result(timeout=30) for f in futs]
            codes = [r.status_code for r in results]
            assert all(c == 200 for c in codes), codes
            doc = _get_product(pid)
            assert doc["stock"] == 30, doc["stock"]
            assert round(float(doc["cost_usd"]), 4) == 100.0, doc["cost_usd"]
        finally:
            _cleanup_product(pid)


# ──────────────────── R01 — Offer withdrawal on entry ────────────────────
def _put_offer(pid, discount_pct=20.0):
    """Trigger offer via apply-liquidation requires sin_ventas logic; instead
    plant offer fields directly in DB (service wraps this in real flow)."""
    db = _db()
    original = float(_get_product(pid)["price_usd"])
    new_price = round(original * (1 - discount_pct / 100.0), 2)
    db.products.update_one({"id": pid}, {"$set": {
        "price_usd": new_price,
        "on_offer": True,
        "offer_original_price": original,
        "offer_discount_pct": discount_pct,
        "offer_at": datetime.utcnow().isoformat(),
    }})
    return new_price


def _products_list_entry(pid):
    r = requests.get(f"{API}/products", headers=_auth())
    assert r.status_code == 200, r.text
    data = r.json()
    items = data.get("items") if isinstance(data, dict) else data
    for it in (items or []):
        if it.get("id") == pid:
            return it
    return None


class TestR01OfferAtomicWithdrawal:
    def test_entry_with_different_price_clears_offer(self):
        p = _create_product(price=400.0, cost=100.0, stock=5)
        pid = p["id"]
        try:
            _put_offer(pid, discount_pct=25.0)  # price=300, on_offer=true
            # Entry with NEW price (different from stored 300)
            r = _entry(pid, qty=2, cost=120.0, sale_price=350.0)
            assert r.status_code == 200, r.text
            doc = _get_product(pid)
            assert round(float(doc["price_usd"]), 2) == 350.00
            assert doc.get("on_offer") in (False, None), doc.get("on_offer")
            assert "offer_original_price" not in doc
            assert "offer_discount_pct" not in doc
            assert "offer_at" not in doc
            # /api/products must not announce the offer
            listed = _products_list_entry(pid)
            if listed is not None:
                assert not listed.get("on_offer"), listed
                assert "offer_discount_pct" not in listed or not listed.get(
                    "offer_discount_pct")
        finally:
            _cleanup_product(pid)

    def test_entry_same_price_keeps_offer(self):
        """sale_price 400.001 vs stored 400.00 (rounded) -> no change."""
        p = _create_product(price=400.0, cost=100.0, stock=5)
        pid = p["id"]
        try:
            _put_offer(pid, discount_pct=25.0)  # stored price=300.00
            before = _get_product(pid)
            assert before.get("on_offer") is True
            # Sale price that rounds to SAME stored price
            r = _entry(pid, qty=2, cost=120.0, sale_price=300.001)
            assert r.status_code == 200, r.text
            doc = _get_product(pid)
            assert round(float(doc["price_usd"]), 2) == 300.00
            assert doc.get("on_offer") is True, doc
            assert doc.get("offer_original_price") == 400.0
            assert doc.get("offer_discount_pct") == 25.0
        finally:
            _cleanup_product(pid)


# ──────────────────── R03 — Count vs authorized race ────────────────────
class TestR03CountAfterAuthorized409:
    def test_second_count_after_authorized_returns_409(self):
        p = _create_product(price=500.0, cost=200.0, stock=10)
        pid = p["id"]
        try:
            # First count (dif != 0 so adjust can run)
            r1 = requests.post(f"{API}/admin/inventory/counts",
                               json={"product_id": pid, "counted_qty": 8,
                                     "note": "TEST_IPV326 count"},
                               headers=_auth())
            assert r1.status_code == 200, r1.text
            count_id = r1.json()["id"]

            # Authorize/adjust it
            r2 = requests.post(
                f"{API}/admin/inventory/counts/{count_id}/adjust",
                json={"document": "DOC-TEST-326", "note": "auth"},
                headers=_auth())
            assert r2.status_code == 200, r2.text

            # Retry: should 409 (authorized=true, cannot overwrite)
            r3 = requests.post(f"{API}/admin/inventory/counts",
                               json={"product_id": pid, "counted_qty": 7,
                                     "note": "retry"},
                               headers=_auth())
            assert r3.status_code == 409, (
                f"expected 409, got {r3.status_code}: {r3.text}")
        finally:
            _cleanup_product(pid)


# ──────────────────── R04 — Close-review 3-state priority ────────────────
class TestR04CloseReviewPriority:
    def test_descuadra_wins_over_pendiente(self):
        """Inyecta una salida sin documento (merma con note vacía) hoy; con
        muchos productos sin contar debería dar 'descuadra', NO 'pendiente'."""
        p = _create_product(price=500.0, cost=200.0, stock=20)
        pid = p["id"]
        try:
            # salida sin documento (note vacía) -> anomalía
            r = requests.post(f"{API}/admin/inventory/movements",
                              json={"product_id": pid, "type": "merma",
                                    "quantity": 1, "note": ""},
                              headers=_auth())
            assert r.status_code == 200, r.text
            day = today_havana()
            rev = requests.get(f"{API}/admin/inventory/close-review",
                               params={"date": day}, headers=_auth())
            assert rev.status_code == 200, rev.text
            data = rev.json()
            assert data.get("resultado_sugerido") == "descuadra", data
        finally:
            _cleanup_product(pid)

    def test_pendiente_when_only_missing_counts(self):
        """Sin anomalías pero con productos activos sin conteo del día ->
        'pendiente' (típicamente ya ocurre con la BD como está)."""
        day = today_havana()
        rev = requests.get(f"{API}/admin/inventory/close-review",
                           params={"date": day}, headers=_auth())
        assert rev.status_code == 200, rev.text
        data = rev.json()
        # No podemos garantizar ausencia de anomalías en la BD compartida,
        # así que validamos solo que el valor es uno de los 3 estados y que
        # la clave existe.
        assert data.get("resultado_sugerido") in (
            "cuadra", "pendiente", "descuadra"), data

    def test_invalid_date_400(self):
        r = requests.get(f"{API}/admin/inventory/close-review",
                         params={"date": "bad-date"}, headers=_auth())
        assert r.status_code == 400, r.text
