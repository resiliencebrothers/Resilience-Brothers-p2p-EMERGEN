"""iter324 — Promoción visible: apply-liquidation marca `on_offer`, GET /products
ordena ofertas-primero y expone precio anterior; clear-offer retira la etiqueta
manteniendo el precio rebajado; editar el precio limpia la oferta; valoración
refleja on_offer/offer_discount_pct.
"""
import os
import uuid

import pytest
import requests
from pymongo import MongoClient

from conftest import BASE_URL, ADMIN_TOKEN, EMPLOYEE_TOKEN, VIP_TOKEN, NORMAL_TOKEN

API = f"{BASE_URL}/api"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _auth(tok):
    return {"Cookie": f"session_token={tok}"}


def _cleanup(pid):
    db = _db()
    db.products.delete_one({"id": pid})
    db.inventory_movements.delete_many({"product_id": pid})
    db.inventory_lots.delete_many({"product_id": pid})


def _create_product(name=None, price=500.0, cost=200.0, stock=8):
    name = name or f"TEST_OFF_{uuid.uuid4().hex[:8]}"
    r = requests.post(f"{API}/admin/products",
                      json={"name": name, "category": "test",
                            "price_usd": price, "cost_usd": cost,
                            "stock": stock},
                      headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    return r.json()


def _delete_product(pid):
    try:
        requests.delete(f"{API}/admin/products/{pid}", headers=_auth(ADMIN_TOKEN))
    except Exception:
        pass
    _cleanup(pid)


def _apply_liq(pid, tok=ADMIN_TOKEN):
    return requests.post(
        f"{API}/admin/inventory/products/{pid}/apply-liquidation",
        params={"window": 30}, headers=_auth(tok))


def _get_products():
    r = requests.get(f"{API}/products")
    assert r.status_code == 200, r.text
    return r.json()


def _find_prod(lst, pid):
    return next((p for p in lst if p.get("id") == pid), None)


# ────────────────── apply-liquidation marca oferta ──────────────────
class TestApplyLiquidationMarksOffer:
    def test_apply_sets_on_offer_fields(self):
        p = _create_product(price=500.0, cost=200.0, stock=8)
        pid = p["id"]
        try:
            r = _apply_liq(pid)
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["applied"] is True
            # margen 60% sin ventas → discount_pct=20 (banda media)
            assert body["discount_pct"] == 20.0
            assert abs(body["new_price"] - 400.0) < 0.5

            products = _get_products()
            prod = _find_prod(products, pid)
            assert prod is not None, "producto debería aparecer en /api/products"
            assert prod.get("on_offer") is True
            assert float(prod.get("offer_discount_pct")) == 20.0
            # precio ANTERIOR en moneda tienda
            assert abs(float(prod.get("offer_original_price_store")) - 500.0) < 0.5
            # precio ANTERIOR en USDT (store currency = CUPFX 1:1 en tests)
            assert "offer_original_price_usdt" in prod
            assert abs(float(prod["offer_original_price_usdt"]) - 500.0) < 0.5
            # price rebajado reflejado en price_usdt / price_store
            assert abs(float(prod.get("price_usdt")) - 400.0) < 0.5
            assert abs(float(prod.get("price_store")) - 400.0) < 0.5
        finally:
            _delete_product(pid)


# ────────────────── Ofertas primero ──────────────────
class TestOffersFirst:
    def test_on_offer_products_precede_non_offer(self):
        # Crear un producto normal (no en oferta) y uno que marcaremos en oferta.
        p_normal = _create_product(price=100.0, cost=50.0, stock=5)
        p_off = _create_product(price=500.0, cost=200.0, stock=8)
        pid_n, pid_o = p_normal["id"], p_off["id"]
        try:
            r = _apply_liq(pid_o)
            assert r.status_code == 200, r.text
            products = _get_products()
            # Localizar el ÍNDICE del primer no-oferta y verificar que todos los
            # on_offer que aparezcan después no existan antes de él... al revés:
            # cada on_offer debe venir ANTES del primer no-oferta.
            first_non_offer_idx = next(
                (i for i, p in enumerate(products) if not p.get("on_offer")),
                None)
            if first_non_offer_idx is not None:
                for i, p in enumerate(products):
                    if p.get("on_offer"):
                        assert i < first_non_offer_idx or all(
                            products[j].get("on_offer") for j in range(first_non_offer_idx + 1)
                        ), f"producto on_offer {p.get('id')} aparece tras un no-oferta"
            # Y nuestro producto en oferta aparece antes que el no-oferta recién
            # creado.
            idx_o = next(i for i, p in enumerate(products) if p["id"] == pid_o)
            idx_n = next(i for i, p in enumerate(products) if p["id"] == pid_n)
            assert idx_o < idx_n
        finally:
            _delete_product(pid_n)
            _delete_product(pid_o)


# ────────────────── clear-offer ──────────────────
class TestClearOffer:
    def test_clear_offer_keeps_price(self):
        p = _create_product(price=500.0, cost=200.0, stock=8)
        pid = p["id"]
        try:
            r = _apply_liq(pid)
            assert r.status_code == 200
            new_price = r.json()["new_price"]  # 400

            r2 = requests.post(
                f"{API}/admin/inventory/products/{pid}/clear-offer",
                headers=_auth(ADMIN_TOKEN))
            assert r2.status_code == 200, r2.text
            assert r2.json().get("ok") is True

            products = _get_products()
            prod = _find_prod(products, pid)
            assert prod is not None
            assert prod.get("on_offer") is False
            # El precio NO se restaura (sigue en 400).
            assert abs(float(prod["price_usdt"]) - new_price) < 0.5
        finally:
            _delete_product(pid)

    def test_clear_offer_twice_returns_400(self):
        p = _create_product(price=500.0, cost=200.0, stock=8)
        pid = p["id"]
        try:
            assert _apply_liq(pid).status_code == 200
            r1 = requests.post(
                f"{API}/admin/inventory/products/{pid}/clear-offer",
                headers=_auth(ADMIN_TOKEN))
            assert r1.status_code == 200
            r2 = requests.post(
                f"{API}/admin/inventory/products/{pid}/clear-offer",
                headers=_auth(ADMIN_TOKEN))
            assert r2.status_code == 400, r2.text
            assert "oferta" in (r2.json().get("detail") or "").lower()
        finally:
            _delete_product(pid)

    def test_clear_offer_not_found_404(self):
        r = requests.post(
            f"{API}/admin/inventory/products/nonexistent-xyz/clear-offer",
            headers=_auth(ADMIN_TOKEN))
        assert r.status_code == 404, r.text

    def test_clear_offer_permissions(self):
        p = _create_product(price=500.0, cost=200.0, stock=8)
        pid = p["id"]
        try:
            assert _apply_liq(pid).status_code == 200
            for tok in (VIP_TOKEN, NORMAL_TOKEN):
                r = requests.post(
                    f"{API}/admin/inventory/products/{pid}/clear-offer",
                    headers=_auth(tok))
                assert r.status_code == 403, f"{tok} → {r.status_code} {r.text}"
            # employee (perms vacíos = staff) debe pasar el gate 'products'
            r_e = requests.post(
                f"{API}/admin/inventory/products/{pid}/clear-offer",
                headers=_auth(EMPLOYEE_TOKEN))
            assert r_e.status_code in (200, 400), (
                f"employee → {r_e.status_code}: {r_e.text}")
        finally:
            _delete_product(pid)


# ────────────────── Editar precio limpia oferta ──────────────────
class TestEditPriceClearsOffer:
    def test_edit_price_clears_offer(self):
        p = _create_product(price=500.0, cost=200.0, stock=8)
        pid = p["id"]
        try:
            assert _apply_liq(pid).status_code == 200
            # Confirmar que está en oferta
            prod = _find_prod(_get_products(), pid)
            assert prod and prod.get("on_offer") is True

            # Editar price_usd a 390 (distinto del 400 actual)
            upd = requests.put(f"{API}/admin/products/{pid}",
                               json={"name": p["name"], "category": "test",
                                     "price_usd": 390.0, "cost_usd": 200.0,
                                     "stock": 8},
                               headers=_auth(ADMIN_TOKEN))
            assert upd.status_code == 200, upd.text

            prod2 = _find_prod(_get_products(), pid)
            assert prod2 is not None
            assert prod2.get("on_offer") is False, (
                f"debería haber limpiado la oferta: {prod2}")
            assert abs(float(prod2["price_usdt"]) - 390.0) < 0.5
        finally:
            _delete_product(pid)

    def test_edit_without_price_change_keeps_offer(self):
        p = _create_product(price=500.0, cost=200.0, stock=8)
        pid = p["id"]
        try:
            r = _apply_liq(pid)
            assert r.status_code == 200
            new_price = r.json()["new_price"]  # 400
            # Editar SIN cambiar precio (sólo descripción/nombre)
            upd = requests.put(f"{API}/admin/products/{pid}",
                               json={"name": p["name"],
                                     "category": "test",
                                     "description": "nueva desc",
                                     "price_usd": new_price,
                                     "cost_usd": 200.0,
                                     "stock": 8},
                               headers=_auth(ADMIN_TOKEN))
            assert upd.status_code == 200, upd.text
            prod2 = _find_prod(_get_products(), pid)
            assert prod2 is not None
            assert prod2.get("on_offer") is True, (
                f"oferta no debería limpiarse sin cambio de precio: {prod2}")
        finally:
            _delete_product(pid)


# ────────────────── Valuation refleja oferta ──────────────────
class TestValuationReflectsOffer:
    def test_valuation_includes_offer_fields(self):
        p = _create_product(price=500.0, cost=200.0, stock=8)
        pid = p["id"]
        try:
            assert _apply_liq(pid).status_code == 200
            r = requests.get(f"{API}/admin/inventory/valuation",
                             params={"window": 30},
                             headers=_auth(ADMIN_TOKEN))
            assert r.status_code == 200, r.text
            data = r.json()
            row = next((p for p in data["products"]
                        if p["product_id"] == pid), None)
            assert row is not None
            assert row.get("on_offer") is True
            assert float(row.get("offer_discount_pct")) == 20.0
        finally:
            _delete_product(pid)
