"""IPV Fase 1+ — iter330: histórico de tasa CUP↔USDT y variación FX.

Cubre: capture_fx_snapshot congela la tasa del día; get_fx_at devuelve la tasa
vigente (último snapshot ≤ fecha) o estimada si no hay; el cutoff-report expone
el bloque fx + value_usdt (rate_vip); y el endpoint fx-variation calcula el %
de ganancia/pérdida por la variación de la tasa (pérdida si el CUP se devalúa).
"""
import os
import uuid
import asyncio

import requests
import pytest
from pymongo import MongoClient

from services.fx_history import capture_fx_snapshot, get_fx_at

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"
_db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]

ADMIN = {"session_token": "test_session_admin_X"}
VIP = {"session_token": "test_session_vip_X"}


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


class TestFxHistoryService:
    def test_capture_and_get_exact(self):
        snap = _loop().run_until_complete(capture_fx_snapshot(source="test"))
        assert snap and snap["rate_vip"] >= 0
        fx = _loop().run_until_complete(get_fx_at(snap["date"]))
        assert fx["rate_vip"] == snap["rate_vip"]
        assert fx["estimated"] is False
        assert fx["rate_date"] == snap["date"]

    def test_get_fx_at_picks_latest_le_date(self):
        tag = "2020-01-01"
        _db.fx_rate_history.insert_one({
            "from_code": "USDT", "to_code": "CUP", "date": tag,
            "rate_normal": 100.0, "rate_vip": 111.0, "source": "test"})
        try:
            # Fecha posterior al snapshot y sin otro intermedio anterior a hoy.
            fx = _loop().run_until_complete(get_fx_at("2020-06-01"))
            assert fx["rate_date"] == tag and fx["rate_vip"] == 111.0
            assert fx["estimated"] is False
            # Fecha ANTERIOR a cualquier snapshot → estimada (usa el más antiguo).
            fx2 = _loop().run_until_complete(get_fx_at("2019-01-01"))
            assert fx2["estimated"] is True
            assert fx2["rate_date"] == tag
        finally:
            _db.fx_rate_history.delete_one(
                {"from_code": "USDT", "to_code": "CUP", "date": tag})


class TestCutoffFxBlock:
    def test_cutoff_report_has_fx_and_usdt(self):
        today = _loop().run_until_complete(capture_fx_snapshot(source="test"))["date"]
        r = requests.get(f"{API}/admin/inventory/cutoff-report",
                         params={"date": today}, cookies=ADMIN)
        assert r.status_code == 200
        d = r.json()
        assert "fx" in d and d["fx"]["rate_field"] == "rate_vip"
        assert d["fx"]["rate"] >= 0
        assert "value_usdt" in d["totals"]
        # consistencia: value_usdt ≈ value / rate_vip
        rate = d["fx"]["rate"]
        if rate > 0 and d["totals"]["value"]:
            expected = round(d["totals"]["value"] / rate, 2)
            assert abs(d["totals"]["value_usdt"] - expected) < 0.05


class TestFxVariation:
    def test_requires_ref(self):
        r = requests.get(f"{API}/admin/inventory/fx-variation",
                         params={"cut": "2026-05-01"}, cookies=ADMIN)
        assert r.status_code == 400

    def test_permission_denied_for_vip(self):
        r = requests.get(f"{API}/admin/inventory/fx-variation",
                         params={"cut": "2026-05-01", "ref": "2026-04-01"},
                         cookies=VIP)
        assert r.status_code == 403

    def test_loss_when_cup_devalues(self):
        # ref: tasa 400 (CUP más fuerte) ; cut: tasa 500 (CUP devaluado) →
        # el mismo inventario CUP vale MENOS USDT en el corte = pérdida.
        ref_d, cut_d = "2026-04-01", "2026-05-01"
        _db.fx_rate_history.insert_many([
            {"from_code": "USDT", "to_code": "CUP", "date": ref_d,
             "rate_normal": 390.0, "rate_vip": 400.0, "source": "test"},
            {"from_code": "USDT", "to_code": "CUP", "date": cut_d,
             "rate_normal": 490.0, "rate_vip": 500.0, "source": "test"},
        ])
        try:
            r = requests.get(f"{API}/admin/inventory/fx-variation",
                             params={"cut": cut_d, "ref": ref_d}, cookies=ADMIN)
            assert r.status_code == 200
            d = r.json()
            assert d["cut"]["rate"] == 500.0 and d["cut"]["estimated"] is False
            assert d["ref"]["rate"] == 400.0 and d["ref"]["estimated"] is False
            # delta_pct = (400/500 - 1) * 100 = -20.0
            assert d["delta_pct"] == -20.0
            assert d["direction"] == "loss"
            # consistencia de valores en USDT
            if d["value_cup"]:
                assert abs(d["cut"]["value_usdt"] - round(d["value_cup"] / 500.0, 2)) < 0.05
                assert d["delta_usdt"] < 0
        finally:
            _db.fx_rate_history.delete_many(
                {"source": "test", "date": {"$in": [ref_d, cut_d]}})
