"""iter216 — Resumen del día de TODO el equipo en la pestaña Entregas.

Verifica GET /admin/deliveries/summary: entregas confirmadas del día,
sumas de tarifas/ganancias (mensajeros/plataforma), en curso ahora y
desglose por mensajero.
"""
import os
import uuid

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, EMPLOYEE_TOKEN

API = f"{BASE_URL}/api"
DAY = "2026-03-03"


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _seed(status, courier, share, platform, fee, updated):
    did = f"test216_{uuid.uuid4().hex[:10]}"
    _db().deliveries.insert_one({
        "id": did, "kind": "withdrawal", "ref_id": f"ref_{did}",
        "user_id": "user_test_normal01", "client_name": "C216",
        "address": "x", "province": "La Habana", "amount_label": "100 CUP",
        "km": 1.0, "fee_usdt": fee, "share_pct_snapshot": 80.0,
        "courier_share_usdt": share, "platform_share_usdt": platform,
        "status": status, "courier_id": courier[0], "courier_name": courier[1],
        "created_at": f"{DAY}T08:00:00+00:00", "updated_at": updated,
        "timeline": [{"status": status, "at": updated}],
    })
    return did


def test_team_summary_totals_and_by_courier():
    ids = [
        _seed("confirmed", ("c1", "Darianna Cristo"), 4.0, 1.0, 5.0, f"{DAY}T10:00:00+00:00"),
        _seed("confirmed", ("c1", "Darianna Cristo"), 2.4, 0.6, 3.0, f"{DAY}T12:00:00+00:00"),
        _seed("confirmed", ("c2", "Pedro Perez"), 1.6, 0.4, 2.0, f"{DAY}T13:00:00+00:00"),
        # otro día → NO cuenta
        _seed("confirmed", ("c2", "Pedro Perez"), 8.0, 2.0, 10.0, "2026-03-02T10:00:00+00:00"),
        # en curso → cuentan en active, no en ganancias
        _seed("on_the_way", ("c1", "Darianna Cristo"), 1.0, 0.25, 1.25, f"{DAY}T14:00:00+00:00"),
        _seed("delivered", ("c2", "Pedro Perez"), 1.0, 0.25, 1.25, f"{DAY}T14:30:00+00:00"),
    ]
    try:
        r = requests.get(f"{API}/admin/deliveries/summary",
                         params={"date": DAY}, headers=_hdr(ADMIN_TOKEN))
        assert r.status_code == 200, r.text
        s = r.json()
        assert s["confirmed_count"] == 3
        assert s["total_fees_usdt"] == 10.0
        assert s["courier_earned_usdt"] == 8.0
        assert s["platform_earned_usdt"] == 2.0
        assert s["active_count"] >= 1
        assert s["delivered_pending_count"] >= 1
        by = {c["courier_name"]: c for c in s["by_courier"]}
        assert by["Darianna"]["count"] == 2 and by["Darianna"]["earned_usdt"] == 6.4
        assert by["Pedro"]["count"] == 1 and by["Pedro"]["earned_usdt"] == 1.6
        # staff con permiso deliveries también puede verlo
        r = requests.get(f"{API}/admin/deliveries/summary",
                         params={"date": DAY}, headers=_hdr(EMPLOYEE_TOKEN))
        assert r.status_code == 200
        # fecha inválida → 400
        r = requests.get(f"{API}/admin/deliveries/summary",
                         params={"date": "malo"}, headers=_hdr(ADMIN_TOKEN))
        assert r.status_code == 400
    finally:
        _db().deliveries.delete_many({"id": {"$in": ids}})
