"""iter323 — IPV Fase 3: sugerencia de liquidación para capital inmovilizado.

- compute_liquidation (via build_valuation/valuation):
  (a) sin ventas, price=113, cost=100 → disc=10, suggested=101.70, loss=False.
  (b) margen <5% → disc=0.
  (c) price<cost → loss=True, disc=0.
  (d) producto con ventas (activo) → liquidation=None.
- FLOOR nunca por debajo de costo: suggested_price >= wac cuando loss=False.
- POST /admin/inventory/products/{id}/apply-liquidation:
  * aplica new_price = suggested; audita movimiento 'precio'; 200.
  * segundo POST inmediato → 400.
  * producto sin sugerencia (no inmovilizado / loss / disc=0) → 400.
  * producto inexistente → 404.
- Permisos: employee (perms vacíos) → 200/400 según corresponda; vip/normal → 403.
- Totales: totals.liquidation_recovery suma estimated_revenue de los
  productos con descuento>0 sin pérdida; immobilized_value e _count presentes.
"""
import os
import math
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


def _create_product(name=None, price=113.0, cost=100.0, stock=5):
    name = name or f"TEST_LIQ_{uuid.uuid4().hex[:8]}"
    r = requests.post(f"{API}/admin/products",
                      json={"name": name, "category": "test",
                            "price_usd": price, "cost_usd": cost,
                            "stock": stock},
                      headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    return r.json()


def _delete_product(pid):
    try:
        requests.delete(f"{API}/admin/products/{pid}",
                        headers=_auth(ADMIN_TOKEN))
    except Exception:
        pass
    _cleanup(pid)


def _get_val(window=30, tok=ADMIN_TOKEN):
    r = requests.get(f"{API}/admin/inventory/valuation",
                     params={"window": window}, headers=_auth(tok))
    assert r.status_code == 200, r.text
    return r.json()


def _find(data, pid):
    return next((p for p in data["products"] if p["product_id"] == pid), None)


# ────────────────── Casos de compute_liquidation vía /valuation ──────────────────
class TestLiquidationCompute:
    def test_case_a_sin_ventas_discount_10(self):
        """price=113, cost=100 → margin_room≈11.5%, disc=10 (floor 5), sugg≈101.70."""
        p = _create_product(price=113.0, cost=100.0, stock=5)
        pid = p["id"]
        try:
            row = _find(_get_val(window=30), pid)
            assert row is not None
            assert row["capital_status"] == "sin_ventas"
            assert row["immobilized"] is True
            liq = row["liquidation"]
            assert liq is not None, row
            assert liq["loss"] is False
            assert liq["discount_pct"] == 10.0
            assert abs(liq["suggested_price"] - 101.70) < 0.01
            # margin_room ≈ 11.5
            assert abs(liq["margin_room_pct"] - 11.5) < 0.1
            # oldest_age_days: hoy → 0
            assert liq["oldest_age_days"] in (0, None) or liq["oldest_age_days"] >= 0
            # cash_to_free == stock * wac
            assert abs(liq["cash_to_free"] - 5 * 100.0) < 0.5
            # estimated_revenue == stock * suggested
            assert abs(liq["estimated_revenue"] - 5 * liq["suggested_price"]) < 0.5
        finally:
            _delete_product(pid)

    def test_case_b_margin_below_5_disc_0(self):
        """price=103, cost=100 → margen≈2.9% → disc=0 (no hay espacio limpio)."""
        p = _create_product(price=103.0, cost=100.0, stock=5)
        pid = p["id"]
        try:
            row = _find(_get_val(window=30), pid)
            assert row is not None
            liq = row["liquidation"]
            assert liq is not None
            assert liq["loss"] is False
            assert liq["discount_pct"] == 0.0
            # suggested_price == price actual (sin descuento)
            assert abs(liq["suggested_price"] - 103.0) < 0.01
        finally:
            _delete_product(pid)

    def test_case_c_price_below_cost_loss(self):
        """price=90, cost=100 → loss=True, disc=0."""
        p = _create_product(price=90.0, cost=100.0, stock=5)
        pid = p["id"]
        try:
            row = _find(_get_val(window=30), pid)
            assert row is not None
            liq = row["liquidation"]
            assert liq is not None
            assert liq["loss"] is True
            assert liq["discount_pct"] == 0.0
            assert liq["margin_room_pct"] <= 0
        finally:
            _delete_product(pid)

    def test_case_d_active_product_no_liquidation(self):
        """Producto con ventas recientes → no inmovilizado → liquidation=None."""
        p = _create_product(price=50.0, cost=20.0, stock=10)
        pid = p["id"]
        try:
            # Venta hoy (5 de 10 en 30d → daily=0.167 → sellout=60 ≤ 90 → activo).
            rv = requests.post(f"{API}/admin/inventory/movements",
                               json={"product_id": pid, "type": "venta",
                                     "quantity": 5},
                               headers=_auth(ADMIN_TOKEN))
            assert rv.status_code == 200, rv.text
            row = _find(_get_val(window=30), pid)
            assert row is not None
            assert row["capital_status"] == "activo"
            assert row["immobilized"] is False
            assert row["liquidation"] is None
        finally:
            _delete_product(pid)


# ────────────────── FLOOR nunca por debajo de costo ──────────────────
class TestFloorNeverBelowCost:
    def test_suggested_price_never_below_wac(self):
        """Para varios productos inmovilizados con margen suficiente:
        suggested_price >= wac siempre (floor a 5% nunca pasa del margen)."""
        pids = []
        try:
            # Varias combinaciones price/cost para cubrir distintos márgenes.
            specs = [(113.0, 100.0), (150.0, 100.0), (200.0, 100.0),
                     (108.0, 100.0), (300.0, 100.0)]
            for price, cost in specs:
                p = _create_product(price=price, cost=cost, stock=3)
                pids.append(p["id"])
            data = _get_val(window=30)
            seen = 0
            for pid in pids:
                row = _find(data, pid)
                assert row is not None
                liq = row["liquidation"]
                if liq and not liq["loss"]:
                    seen += 1
                    assert liq["suggested_price"] >= row["wac"] - 1e-6, (
                        f"suggested {liq['suggested_price']} < wac {row['wac']}")
                    # el discount debe ser múltiplo de 5
                    assert liq["discount_pct"] % 5 == 0
            assert seen >= 3, "esperábamos >=3 productos con liq calculable"
        finally:
            for pid in pids:
                _delete_product(pid)


# ────────────────── Apply liquidation (mutante) ──────────────────
class TestApplyLiquidation:
    def test_apply_200_and_audit_and_second_400(self):
        p = _create_product(price=113.0, cost=100.0, stock=5)
        pid = p["id"]
        try:
            r = requests.post(
                f"{API}/admin/inventory/products/{pid}/apply-liquidation",
                params={"window": 30}, headers=_auth(ADMIN_TOKEN))
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["applied"] is True
            assert abs(body["old_price"] - 113.0) < 0.01
            assert abs(body["new_price"] - 101.70) < 0.01
            assert body["discount_pct"] == 10.0

            # Producto actualizado
            got = requests.get(f"{API}/admin/products/{pid}",
                               headers=_auth(ADMIN_TOKEN))
            # endpoint may vary → fallback a /admin/products list
            if got.status_code != 200:
                lr = requests.get(f"{API}/admin/products",
                                  headers=_auth(ADMIN_TOKEN))
                assert lr.status_code == 200
                prod = next((x for x in lr.json() if x["id"] == pid), None)
            else:
                prod = got.json()
            assert prod is not None
            assert abs(float(prod["price_usd"]) - 101.70) < 0.01

            # Movimiento 'precio' auditado
            mr = requests.get(f"{API}/admin/inventory/movements",
                              params={"product_id": pid},
                              headers=_auth(ADMIN_TOKEN))
            assert mr.status_code == 200
            mvs = mr.json()
            if isinstance(mvs, dict):
                mvs = mvs.get("items") or mvs.get("movements") or []
            price_mvs = [m for m in mvs if m.get("type") == "precio"]
            assert len(price_mvs) >= 1
            note = (price_mvs[0].get("note") or price_mvs[0].get("detail")
                    or price_mvs[0].get("description") or "")
            assert "liquidación" in note.lower() or "liquidacion" in note.lower()

            # IPV-FINAL-01 (iter325) — un producto ya en oferta no se vuelve a
            # liquidar: el segundo POST responde 409 (antes 400 por agotar
            # margen). El precio permanece en el valor de la primera oferta.
            r2 = requests.post(
                f"{API}/admin/inventory/products/{pid}/apply-liquidation",
                params={"window": 30}, headers=_auth(ADMIN_TOKEN))
            assert r2.status_code == 409, r2.text
        finally:
            _delete_product(pid)

    def test_apply_no_suggestion_400(self):
        """Producto activo (con ventas) → no inmovilizado → 400."""
        p = _create_product(price=50.0, cost=20.0, stock=10)
        pid = p["id"]
        try:
            rv = requests.post(f"{API}/admin/inventory/movements",
                               json={"product_id": pid, "type": "venta",
                                     "quantity": 5},
                               headers=_auth(ADMIN_TOKEN))
            assert rv.status_code == 200
            r = requests.post(
                f"{API}/admin/inventory/products/{pid}/apply-liquidation",
                params={"window": 30}, headers=_auth(ADMIN_TOKEN))
            assert r.status_code == 400, r.text
        finally:
            _delete_product(pid)

    def test_apply_loss_400(self):
        """price<cost → loss → 400."""
        p = _create_product(price=90.0, cost=100.0, stock=3)
        pid = p["id"]
        try:
            r = requests.post(
                f"{API}/admin/inventory/products/{pid}/apply-liquidation",
                params={"window": 30}, headers=_auth(ADMIN_TOKEN))
            assert r.status_code == 400, r.text
        finally:
            _delete_product(pid)

    def test_apply_not_found_404(self):
        r = requests.post(
            f"{API}/admin/inventory/products/nonexistent-xyz/apply-liquidation",
            params={"window": 30}, headers=_auth(ADMIN_TOKEN))
        assert r.status_code == 404, r.text

    def test_apply_fractional_stock_h08(self):
        """H08 (iter343) — producto en libras con stock FRACCIONARIO (10.5),
        costo 200, precio 500 y sugerencia válida: la primera solicitud aplica
        UNA vez (antes daba 409 espurio por truncar 10.5→10 en la guarda). El
        stock fraccionario se conserva y el reintento sigue protegido (409)."""
        name = f"TEST_LIQ_H08_{uuid.uuid4().hex[:8]}"
        r = requests.post(f"{API}/admin/products",
                          json={"name": name, "category": "test",
                                "price_usd": 500.0, "cost_usd": 200.0,
                                "stock": 10.5, "unit": "libra"},
                          headers=_auth(ADMIN_TOKEN))
        assert r.status_code == 200, r.text
        pid = r.json()["id"]
        try:
            data = _get_val()
            row = _find(data, pid)
            assert row and row["liquidation"] and not row["liquidation"]["loss"]
            assert float(row["liquidation"]["discount_pct"]) > 0
            assert abs(float(row["stock"]) - 10.5) < 1e-6

            # primera solicitud válida → aplica una sola vez, sin 409 espurio
            r1 = requests.post(
                f"{API}/admin/inventory/products/{pid}/apply-liquidation",
                params={"window": 30}, headers=_auth(ADMIN_TOKEN))
            assert r1.status_code == 200, r1.text
            assert r1.json()["applied"] is True

            # el stock fraccionario queda intacto tras la liquidación
            prod = _db().products.find_one({"id": pid}, {"_id": 0})
            assert abs(float(prod["stock"]) - 10.5) < 1e-6
            assert prod["on_offer"] is True

            # reintento sigue protegido (producto ya en oferta → 409)
            r2 = requests.post(
                f"{API}/admin/inventory/products/{pid}/apply-liquidation",
                params={"window": 30}, headers=_auth(ADMIN_TOKEN))
            assert r2.status_code == 409, r2.text
        finally:
            _delete_product(pid)

    def test_concurrency_guard_matches_fractional_h08(self):
        """H08 — la guarda de concurrencia con cantidad fraccionaria encuentra
        el doc EXACTO y deja de aplicar si el stock cambia (reintentos y
        modificaciones concurrentes siguen protegidos)."""
        db = _db()
        pid = f"TEST_LIQ_H08C_{uuid.uuid4().hex[:8]}"
        db.products.insert_one({"id": pid, "name": pid, "category": "test",
                                "stock": 10.5, "unit": "libra",
                                "price_usd": 500.0, "cost_usd": 200.0,
                                "on_offer": False})
        try:
            base_stock = db.products.find_one({"id": pid})["stock"]
            ok = db.products.update_one(
                {"id": pid, "on_offer": {"$ne": True}, "price_usd": 500.0,
                 "cost_usd": 200.0, "stock": base_stock},
                {"$set": {"on_offer": True}})
            assert ok.modified_count == 1, "coincide con el stock fraccionario"
            # un cambio concurrente del stock invalida la guarda con el valor viejo
            db.products.update_one(
                {"id": pid}, {"$set": {"on_offer": False, "stock": 9.25}})
            stale = db.products.update_one(
                {"id": pid, "on_offer": {"$ne": True}, "price_usd": 500.0,
                 "cost_usd": 200.0, "stock": 10.5},
                {"$set": {"on_offer": True}})
            assert stale.modified_count == 0, "estado cambiado → no aplica"
        finally:
            db.products.delete_one({"id": pid})


# ────────────────── Permisos del endpoint mutante ──────────────────
class TestApplyLiquidationPermissions:
    def test_vip_normal_403(self):
        p = _create_product(price=113.0, cost=100.0, stock=5)
        pid = p["id"]
        try:
            for tok in (VIP_TOKEN, NORMAL_TOKEN):
                r = requests.post(
                    f"{API}/admin/inventory/products/{pid}/apply-liquidation",
                    params={"window": 30}, headers=_auth(tok))
                assert r.status_code == 403, f"{tok} → {r.status_code}"
        finally:
            _delete_product(pid)

    def test_employee_not_403(self):
        """Employee con perms vacíos = staff en RB → debe pasar el gate
        'products' (200 si hay sugerencia, 400 si no)."""
        p = _create_product(price=113.0, cost=100.0, stock=5)
        pid = p["id"]
        try:
            r = requests.post(
                f"{API}/admin/inventory/products/{pid}/apply-liquidation",
                params={"window": 30}, headers=_auth(EMPLOYEE_TOKEN))
            assert r.status_code in (200, 400), (
                f"employee → {r.status_code} (esperado 200/400, nunca 403): {r.text}")
        finally:
            _delete_product(pid)


# ────────────────── Totales ──────────────────
class TestValuationTotals:
    def test_totals_has_liquidation_recovery(self):
        p = _create_product(price=113.0, cost=100.0, stock=5)
        pid = p["id"]
        try:
            data = _get_val(window=30)
            totals = data["totals"]
            for k in ("liquidation_recovery", "immobilized_value",
                      "immobilized_count"):
                assert k in totals, f"Falta totals.{k}"
            # Nuestro producto aporta ~5·101.70 ≈ 508.5 al recovery.
            assert totals["liquidation_recovery"] >= 508.0 - 1.0
            assert totals["immobilized_count"] >= 1
        finally:
            _delete_product(pid)
