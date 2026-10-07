"""IPV Fase 1 — Corte histórico del inventario (iter328).

Prueba la reconstrucción a una FECHA DE CORTE con movimientos de fecha
controlada (insertados directamente) y la valoración de diferencias de conteo
al costo de referencia congelado. Cubre los criterios de aceptación del plan:

- Un corte con 12 uds a costo 20 conserva su valor 240 tras una compra/cambio
  de precio POSTERIOR.
- Conteo 9 vs 12 teóricas → diferencia −3, valor −60; un costo posterior no
  modifica esa evidencia (usa el costo de referencia guardado).
- Flujos del período [start, corte] y existencia inicial correctos.
- Cobertura PARCIAL cuando falta base inicial (la existencia cae bajo cero).
"""
import os
import uuid
import asyncio

import pytest
from pymongo import MongoClient

from services.inventory_history import build_cutoff_report

_db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]

_LOOP = None


def _loop():
    # iter342: loop cacheado y siempre fijado como actual. Evita el
    # RuntimeError "no current event loop" en py3.11 cuando un archivo async
    # (pytest-asyncio) cerró su loop antes de este test síncrono.
    global _LOOP
    if _LOOP is None or _LOOP.is_closed():
        _LOOP = asyncio.new_event_loop()
    asyncio.set_event_loop(_LOOP)
    return _LOOP


def _mov(pid, name, mtype, qty, created_at, unit_cost=0.0, unit_price=0.0):
    return {
        "id": str(uuid.uuid4()), "product_id": pid, "product_name": name,
        "type": mtype, "quantity": int(qty), "unit_cost": float(unit_cost),
        "unit_price": float(unit_price), "total": 0.0, "cost_of_sale": 0.0,
        "profit": 0.0, "note": "", "source": "manual", "ref_id": "",
        "created_at": created_at,
    }


@pytest.fixture
def hist_product():
    pid = f"TEST_IPV328_{uuid.uuid4().hex[:8]}"
    name = "Café Histórico"
    # Producto de empresa (owner_id vacío) — existe hoy.
    _db.products.insert_one({
        "id": pid, "name": name, "category": "Prueba", "is_active": True,
        "stock": 12, "cost_usd": 20.0, "price_usd": 35.0, "owner_id": "",
    })
    yield pid, name
    _db.products.delete_one({"id": pid})
    _db.inventory_movements.delete_many({"product_id": pid})
    _db.inventory_counts.delete_many({"product_id": pid})


def _row(report, pid):
    return next((p for p in report["products"] if p["product_id"] == pid), None)


class TestCutoffReport:
    def test_value_frozen_after_later_purchase(self, hist_product):
        pid, name = hist_product
        # D1: entrada 12 @ 20 (mediodía UTC → mismo día en Cuba).
        _db.inventory_movements.insert_one(
            _mov(pid, name, "entrada", 12, "2026-09-10T12:00:00+00:00", unit_cost=20.0))
        # D2 (posterior): entrada 8 @ 50 + cambio de precio.
        _db.inventory_movements.insert_one(
            _mov(pid, name, "entrada", 8, "2026-09-20T12:00:00+00:00", unit_cost=50.0))
        _db.inventory_movements.insert_one(
            _mov(pid, name, "precio", 0, "2026-09-20T12:05:00+00:00", unit_price=99.0))
        # Existencia real consistente con lo documentado (12 + 8, sin salidas):
        # así la base está totalmente documentada y el corte es 'completa'.
        _db.products.update_one({"id": pid}, {"$set": {"stock": 20}})

        # Corte en D1: 12 uds, WAC 20, valor 240 (la compra de D2 NO lo altera).
        rep = _loop().run_until_complete(
            build_cutoff_report("2026-09-10"))
        r = _row(rep, pid)
        assert r is not None
        assert r["final_stock"] == 12
        assert r["wac"] == 20.0
        assert r["value"] == 240.0
        assert r["coverage"] == "completa"

        # Corte en D2: 20 uds, WAC = (12*20 + 8*50)/20 = 32, valor 640.
        rep2 = _loop().run_until_complete(
            build_cutoff_report("2026-09-20"))
        r2 = _row(rep2, pid)
        assert r2["final_stock"] == 20
        assert r2["wac"] == 32.0
        assert r2["value"] == 640.0

    def test_period_flows_and_opening(self, hist_product):
        pid, name = hist_product
        _db.inventory_movements.insert_one(
            _mov(pid, name, "entrada", 12, "2026-09-10T12:00:00+00:00", unit_cost=20.0))
        _db.inventory_movements.insert_one(
            _mov(pid, name, "venta", 3, "2026-09-15T12:00:00+00:00", unit_price=35.0))
        _db.inventory_movements.insert_one(
            _mov(pid, name, "merma", 1, "2026-09-16T12:00:00+00:00", unit_cost=20.0))
        # Período [2026-09-14, 2026-09-20]: inicial 12, ventas 3, merma 1, final 8.
        rep = _loop().run_until_complete(
            build_cutoff_report("2026-09-20", start="2026-09-14"))
        r = _row(rep, pid)
        assert r["opening"] == 12
        assert r["ventas"] == 3
        assert r["merma"] == 1
        assert r["entradas"] == 0  # la entrada fue antes del período
        assert r["final_stock"] == 8
        # Existencia final = inicial + entradas − ventas − merma − … + ajustes.
        assert r["final_stock"] == r["opening"] + r["entradas"] - r["ventas"] \
            - r["merma"] - r["consumo"] - r["otra_salida"] + r["ajuste_neto"]

    def test_count_difference_value_frozen(self, hist_product):
        pid, name = hist_product
        _db.inventory_movements.insert_one(
            _mov(pid, name, "entrada", 12, "2026-09-10T12:00:00+00:00", unit_cost=20.0))
        # Conteo del día de corte: 9 contadas vs 12 teóricas, costo ref. 20.
        _db.inventory_counts.insert_one({
            "id": str(uuid.uuid4()), "product_id": pid, "product_name": name,
            "count_date": "2026-09-10", "counted_qty": 9, "theoretical_stock": 12,
            "difference": -3, "difference_value": -60.0, "reference_cost": 20.0,
            "unit": "u", "currency": "CUP", "status": "faltante",
            "authorized": False,
        })
        rep = _loop().run_until_complete(
            build_cutoff_report("2026-09-10"))
        r = _row(rep, pid)
        assert r["count"] is not None
        assert r["count"]["difference"] == -3
        assert r["count"]["reference_cost"] == 20.0
        assert r["count"]["difference_value"] == -60.0

        # Un costo POSTERIOR del producto no cambia la evidencia del conteo.
        _db.products.update_one({"id": pid}, {"$set": {"cost_usd": 50.0}})
        rep2 = _loop().run_until_complete(
            build_cutoff_report("2026-09-10"))
        r2 = _row(rep2, pid)
        assert r2["count"]["difference_value"] == -60.0  # sigue a costo 20

    def test_partial_coverage_without_opening(self, hist_product):
        pid, name = hist_product
        # Solo una venta, sin entrada previa → existencia reconstruida negativa.
        _db.inventory_movements.insert_one(
            _mov(pid, name, "venta", 5, "2026-09-10T12:00:00+00:00", unit_price=35.0))
        rep = _loop().run_until_complete(
            build_cutoff_report("2026-09-10"))
        r = _row(rep, pid)
        assert r is not None
        assert r["coverage"] == "parcial"
        assert rep["totals"]["partial_count"] >= 1
