"""SUN-08-R1-REC — endpoint de SALUD de las colas de recuperación POS/fondo.

GET /api/admin/company-funds/reconciliation-health (solo lectura): reporta
cuántas obligaciones hay pendientes en cada cola (ingresos tardíos por compensar,
ventas tardías por anular, cobros POS interrumpidos). Permiso: `company_funds`.
"""
import os
import uuid
from datetime import datetime, timezone

import requests
from pymongo import MongoClient

from conftest import BASE_URL, ADMIN_TOKEN, NORMAL_TOKEN

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
URL = f"{BASE_URL}/api/admin/company-funds/reconciliation-health"


def _h(token=None):
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def test_admin_can_read_reconciliation_health():
    r = requests.get(URL, headers=_h(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body.keys()) >= {"healthy", "total_pending", "checked_at", "queues"}
    assert isinstance(body["healthy"], bool)
    q = body["queues"]
    assert set(q.keys()) == {"aborted_cobro_funds", "reversed_cobro_effects",
                             "stuck_cobros"}
    for v in q.values():
        assert isinstance(v["pending"], int) and v["pending"] >= 0
        assert isinstance(v["label"], str) and v["label"]
    assert body["total_pending"] == sum(v["pending"] for v in q.values())
    assert body["healthy"] == (body["total_pending"] == 0)


def test_non_admin_forbidden():
    r = requests.get(URL, headers=_h(NORMAL_TOKEN))
    assert r.status_code in (401, 403), r.text


def test_health_reports_pending_aborted_fund_obligation():
    """Siembra una venta abortada con INGRESO propio y SIN su salida de reversión
    → el endpoint debe contarla como obligación pendiente y marcar healthy=False."""
    db = MongoClient(MONGO_URL)[DB_NAME]
    mid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    db.inventory_movements.insert_one({
        "id": mid, "product_id": "__t369__", "product_name": "T369",
        "type": "venta", "source": "manual", "quantity": 1, "total": 100.0,
        "cobro_aborted": True, "voided": True, "voided_at": now,
        "created_at": now, "cobro_id": f"c-{mid}"})
    db.company_fund_adjustments.insert_one({
        "id": str(uuid.uuid4()), "adjustment_type": "inflow", "amount": 100.0,
        "currency": "CUP", "ref_id": mid, "dedupe_key": f"invmov-fund:{mid}",
        "created_at": now})
    try:
        r = requests.get(URL, headers=_h(ADMIN_TOKEN))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["queues"]["aborted_cobro_funds"]["pending"] >= 1
        assert body["total_pending"] >= 1
        assert body["healthy"] is False
    finally:
        db.company_fund_adjustments.delete_many({"ref_id": mid})
        db.inventory_movements.delete_many({"id": mid})
