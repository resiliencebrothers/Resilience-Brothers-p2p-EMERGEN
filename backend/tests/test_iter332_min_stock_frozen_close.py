"""IPV Fase 2 + Cierre Congelado — iter332.

min_stock por producto: umbral efectivo (None=global, 0=solo agotado), fila de
control con estado correcto, endpoint PATCH y permisos.
Acta congelada: save_close_review congela un snapshot inmutable y versionado
(existencia + valor CUP/USDT + tasa + firmas); endpoint close-snapshot.
"""
import os
import uuid
import asyncio

import requests
import pytest
from pymongo import MongoClient

from services.inventory import (effective_low_stock_threshold,
                                build_control_rows)

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"
_db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
ADMIN = {"session_token": "test_session_admin_X"}
VIP = {"session_token": "test_session_vip_X"}


def _loop():
    return asyncio.get_event_loop()


@pytest.fixture
def company_prod():
    pid = f"TEST_IPV332_{uuid.uuid4().hex[:8]}"
    _db.products.insert_one({
        "id": pid, "name": "Prod Min 332", "category": "Prueba",
        "is_active": True, "stock": 4, "cost_usd": 10.0, "price_usd": 20.0,
        "owner_id": ""})
    yield pid
    _db.products.delete_one({"id": pid})
    _db.inventory_movements.delete_many({"product_id": pid})


class TestEffectiveThreshold:
    def test_none_uses_global(self):
        assert effective_low_stock_threshold({"min_stock": None}, 5) == 5
        assert effective_low_stock_threshold({}, 7) == 7

    def test_zero_is_respected(self):
        # 0 configurado NO vuelve al global (distingue vacío de cero).
        assert effective_low_stock_threshold({"min_stock": 0}, 5) == 0

    def test_custom_value(self):
        assert effective_low_stock_threshold({"min_stock": 12}, 5) == 12


class TestControlRowEstado:
    def test_min_stock_drives_estado(self, company_prod):
        # stock 4; con min_stock 10 → 'bajo' (4<=10) aunque el global sea 5.
        _db.products.update_one({"id": company_prod}, {"$set": {"min_stock": 10}})
        rows = _loop().run_until_complete(build_control_rows())
        r = next(x for x in rows if x["product_id"] == company_prod)
        assert r["min_stock"] == 10
        assert r["effective_min"] == 10
        assert r["estado"] == "bajo"

    def test_min_stock_zero_only_agotado(self, company_prod):
        # stock 4, min_stock 0 → 'ok' (no bajo); solo 'agotado' al llegar a 0.
        _db.products.update_one({"id": company_prod}, {"$set": {"min_stock": 0}})
        rows = _loop().run_until_complete(build_control_rows())
        r = next(x for x in rows if x["product_id"] == company_prod)
        assert r["estado"] == "ok"


class TestMinStockApi:
    def test_patch_sets_and_clears(self, company_prod):
        r = requests.patch(f"{API}/admin/inventory/products/{company_prod}/min-stock",
                           json={"min_stock": 3}, cookies=ADMIN)
        assert r.status_code == 200 and r.json()["min_stock"] == 3
        assert _db.products.find_one({"id": company_prod})["min_stock"] == 3
        r2 = requests.patch(f"{API}/admin/inventory/products/{company_prod}/min-stock",
                            json={"min_stock": None}, cookies=ADMIN)
        assert r2.status_code == 200 and r2.json()["min_stock"] is None
        assert _db.products.find_one({"id": company_prod})["min_stock"] is None

    def test_patch_denied_for_vip(self, company_prod):
        r = requests.patch(f"{API}/admin/inventory/products/{company_prod}/min-stock",
                           json={"min_stock": 3}, cookies=VIP)
        assert r.status_code == 403

    def test_patch_404_unknown(self):
        r = requests.patch(f"{API}/admin/inventory/products/NOPE/min-stock",
                           json={"min_stock": 3}, cookies=ADMIN)
        assert r.status_code == 404


class TestFrozenClose:
    def _cleanup(self, day):
        _db.inventory_closes.delete_many({"close_date": day})
        _db.inventory_close_snapshots.delete_many({"close_date": day})

    def test_close_freezes_immutable_versioned_snapshot(self):
        day = "2026-03-15"
        self._cleanup(day)
        try:
            body = {"date": day, "responsable": "Ana", "revisado_por": "Luis",
                    "folio": "F-TEST", "note": "n"}
            r = requests.post(f"{API}/admin/inventory/close-review",
                              json=body, cookies=ADMIN)
            assert r.status_code == 200
            d = r.json()
            assert d.get("snapshot_version") == 1
            assert d.get("value_cup") is not None
            assert d.get("fx_rate_vip") is not None
            # snapshot inmutable y con firmas + totales CUP/USDT
            s = requests.get(f"{API}/admin/inventory/close-snapshot",
                             params={"date": day}, cookies=ADMIN)
            assert s.status_code == 200
            snap = s.json()["snapshot"]
            assert snap["immutable"] is True
            assert snap["version"] == 1
            assert snap["responsable"] == "Ana" and snap["revisado_por"] == "Luis"
            assert "value_cup" in snap["totals"] and "value_usdt" in snap["totals"]
            assert "rate_vip" in snap["fx"]
            # re-cierre → v2 preservando v1 (revisión trazable)
            requests.post(f"{API}/admin/inventory/close-review",
                          json={**body, "note": "corr"}, cookies=ADMIN)
            s2 = requests.get(f"{API}/admin/inventory/close-snapshot",
                              params={"date": day}, cookies=ADMIN)
            data2 = s2.json()
            assert data2["snapshot"]["version"] == 2
            assert len(data2["versions"]) == 2
            assert any(v["version"] == 1 for v in data2["versions"])
        finally:
            self._cleanup(day)

    def test_close_snapshot_denied_for_vip(self):
        r = requests.get(f"{API}/admin/inventory/close-snapshot",
                         params={"date": "2026-03-15"}, cookies=VIP)
        assert r.status_code == 403
