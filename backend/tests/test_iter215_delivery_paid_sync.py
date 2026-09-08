"""iter215 — Ciclo completo mensajería ↔ transacciones (ambas direcciones).

Verifica:
1. Cuando el MENSAJERO marca la entrega como 'delivered', el retiro cash
   vinculado pasa a 'paid' automáticamente (Transacciones al día) y la
   entrega queda 'delivered' esperando la confirmación admin del payout.
2. Cuando el ADMIN marca el retiro 'Entregado' (paid, con TOTP) y la entrega
   ya estaba 'delivered', la entrega se confirma sola: payout 80% acreditado
   al mensajero y estado final 'confirmed'.
"""
import os
import uuid

import requests
from pymongo import MongoClient

from tests.conftest import (
    BASE_URL, ADMIN_TOKEN, EMPLOYEE_TOKEN, make_admin_totp,
)

API = f"{BASE_URL}/api"
CLIENT_ID = "user_test_normal01"
COURIER_ID = "user_test_employee01"


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _usdt(uid):
    u = _db().users.find_one({"user_id": uid}, {"_id": 0, "vip_balances": 1})
    return float(((u or {}).get("vip_balances") or {}).get("USDT") or 0.0)


def _seed(status, wid=None):
    db = _db()
    wid = wid or f"test215_w_{uuid.uuid4().hex[:8]}"
    did = f"test215_d_{uuid.uuid4().hex[:8]}"
    db.withdrawals.insert_one({
        "id": wid, "user_id": CLIENT_ID, "user_name": "Cliente 215",
        "user_email": "normal.test@resilience.com",
        "method": "cash", "currency": "CUP", "amount_usd": 700,
        "status": "pending", "details": "d", "beneficiary_name": "b",
        "courier_km": 3.0, "courier_fee_usdt": 3.0,
        "courier_fee_charged_at": "2026-08-27T09:00:00+00:00",
        "created_at": "2026-08-27T09:00:00+00:00",
    })
    db.deliveries.insert_one({
        "id": did, "kind": "withdrawal", "ref_id": wid,
        "user_id": CLIENT_ID, "client_name": "Cliente 215",
        "address": "Calle T", "province": "La Habana",
        "amount_label": "700 CUP",
        "km": 3.0, "fee_usdt": 3.0, "share_pct_snapshot": 80.0,
        "courier_share_usdt": 2.4, "platform_share_usdt": 0.6,
        "status": status,
        "courier_id": COURIER_ID, "courier_name": "Empleado Test",
        "payout_credited": False, "payout_credited_at": None,
        "created_at": "2026-08-27T09:00:00+00:00",
        "updated_at": "2026-08-27T09:30:00+00:00",
        "timeline": [{"status": status, "at": "2026-08-27T09:30:00+00:00"}],
    })
    return wid, did


def _cleanup(wid, did, courier_bal_before):
    db = _db()
    db.withdrawals.delete_many({"id": wid})
    db.deliveries.delete_many({"id": did})
    db.notifications.delete_many({"$or": [
        {"data.withdrawal_id": wid}, {"data.delivery_id": did}]})
    delta = round(_usdt(COURIER_ID) - courier_bal_before, 4)
    if delta:
        db.users.update_one({"user_id": COURIER_ID},
                            {"$inc": {"vip_balances.USDT": -delta}})


def test_courier_delivered_marks_withdrawal_paid():
    wid, did = _seed("arrived")
    bal0 = _usdt(COURIER_ID)
    try:
        r = requests.post(f"{API}/courier/deliveries/{did}/status",
                          headers=_hdr(EMPLOYEE_TOKEN),
                          json={"status": "delivered"})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "delivered"
        w = _db().withdrawals.find_one({"id": wid}, {"_id": 0})
        assert w["status"] == "paid", f"retiro sigue en {w['status']}"
        assert "mensajería" in (w.get("admin_note") or "")
        # el payout del mensajero AÚN espera la confirmación admin
        d = _db().deliveries.find_one({"id": did}, {"_id": 0})
        assert d["status"] == "delivered"
        assert not d.get("payout_credited")
        assert round(_usdt(COURIER_ID) - bal0, 4) == 0.0
    finally:
        _cleanup(wid, did, bal0)


def test_admin_paid_confirms_delivered_job_and_credits_courier():
    wid, did = _seed("delivered")
    bal0 = _usdt(COURIER_ID)
    try:
        r = requests.put(f"{API}/admin/withdrawals/{wid}/status",
                         headers=_hdr(ADMIN_TOKEN),
                         json={"status": "paid", "admin_note": "t215",
                               "totp_code": make_admin_totp()})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "paid"
        d = _db().deliveries.find_one({"id": did}, {"_id": 0})
        assert d["status"] == "confirmed", f"entrega sigue en {d['status']}"
        assert d.get("payout_credited") is True
        assert round(_usdt(COURIER_ID) - bal0, 4) == 2.4, \
            "el 80% del mensajero no se acreditó"
    finally:
        _cleanup(wid, did, bal0)
