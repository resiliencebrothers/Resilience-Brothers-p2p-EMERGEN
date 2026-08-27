"""iter209b — Sincronización: confirmar entrega de mensajería actualiza la
operación vinculada en Depósitos y Retiros.

Verifica:
1. Retiro cash pending + delivery 'delivered' → admin confirma la entrega
   → retiro pasa a 'paid' (con paid_at) automáticamente.
2. Depósito cash-courier pending + delivery kind=deposit 'delivered' →
   admin confirma → depósito 'confirmed' y saldo del cliente acreditado.
"""
import os
import uuid

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, make_admin_totp

API = f"{BASE_URL}/api"
CLIENT_ID = "user_test_normal01"
COURIER_ID = "user_test_vip01"


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _seed_delivery(kind, ref_id):
    did = f"test209b_{uuid.uuid4().hex[:10]}"
    _db().deliveries.insert_one({
        "id": did, "kind": kind, "ref_id": ref_id,
        "user_id": CLIENT_ID, "client_name": "Cliente 209b",
        "address": "Calle Z", "province": "La Habana",
        "amount_label": "1000 CUP",
        "km": 4.0, "fee_usdt": 4.0,
        "share_pct_snapshot": 80.0,
        "courier_share_usdt": 3.2, "platform_share_usdt": 0.8,
        "status": "delivered",
        "courier_id": COURIER_ID, "courier_name": "Mensajero 209b",
        "payout_credited": False, "payout_credited_at": None,
        "created_at": "2026-08-15T10:00:00+00:00",
        "updated_at": "2026-08-15T10:30:00+00:00",
        "timeline": [{"status": "delivered", "at": "2026-08-15T10:30:00+00:00"}],
    })
    return did


def _usdt_balance(user_id, currency="USDT"):
    u = _db().users.find_one({"user_id": user_id}, {"_id": 0, "vip_balances": 1})
    return float(((u or {}).get("vip_balances") or {}).get(currency) or 0.0)


def _confirm_delivery(did):
    r = requests.post(f"{API}/admin/deliveries/{did}/confirm",
                      headers=_hdr(ADMIN_TOKEN),
                      json={"totp_code": make_admin_totp()})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "confirmed"


def test_confirm_delivery_marks_cash_withdrawal_paid():
    db = _db()
    wid = f"test209b_w_{uuid.uuid4().hex[:8]}"
    db.withdrawals.insert_one({
        "id": wid, "user_id": CLIENT_ID, "user_name": "Cliente 209b",
        "user_email": "normal.test@resilience.com",
        "method": "cash", "currency": "CUP", "amount_usd": 1000,
        "status": "pending", "details": "d", "beneficiary_name": "b",
        "courier_km": 4.0, "courier_fee_usdt": 4.0,
        "courier_fee_charged_at": "2026-08-15T09:00:00+00:00",
        "created_at": "2026-08-15T09:00:00+00:00",
    })
    did = _seed_delivery("withdrawal", wid)
    courier_bal = _usdt_balance(COURIER_ID)
    try:
        _confirm_delivery(did)
        w = db.withdrawals.find_one({"id": wid}, {"_id": 0})
        assert w["status"] == "paid", f"retiro sigue en {w['status']}"
        assert w.get("paid_at"), "falta paid_at"
        assert "mensajería" in (w.get("admin_note") or "")
    finally:
        db.withdrawals.delete_many({"id": wid})
        db.deliveries.delete_many({"id": did})
        db.notifications.delete_many({"data.withdrawal_id": wid})
        delta = round(_usdt_balance(COURIER_ID) - courier_bal, 4)
        if delta:
            db.users.update_one({"user_id": COURIER_ID},
                                {"$inc": {"vip_balances.USDT": -delta}})


def test_confirm_delivery_confirms_cash_courier_deposit_and_credits():
    db = _db()
    dep_id = f"dep_test209b_{uuid.uuid4().hex[:8]}"
    db.deposits.insert_one({
        "id": dep_id, "user_id": CLIENT_ID, "user_email": "normal.test@resilience.com",
        "user_name": "Cliente 209b", "user_role": "normal",
        "currency": "CUP", "amount": 1000.0, "method": "cash",
        "cash_mode": "courier", "usdt_equivalent": 2.5,
        "pickup_address": "Calle Z #1", "pickup_phone": "+5355500000",
        "contact_name": "Cliente 209b",
        "status": "pending",
        "created_at": "2026-08-15T09:00:00+00:00",
        "updated_at": "2026-08-15T09:00:00+00:00",
    })
    did = _seed_delivery("deposit", dep_id)
    client_cup = _usdt_balance(CLIENT_ID, "CUP")
    courier_bal = _usdt_balance(COURIER_ID)
    try:
        _confirm_delivery(did)
        dep = db.deposits.find_one({"id": dep_id}, {"_id": 0})
        assert dep["status"] == "confirmed", f"depósito sigue en {dep['status']}"
        after = _usdt_balance(CLIENT_ID, "CUP")
        assert round(after - client_cup, 2) == 1000.0, (
            f"saldo del cliente no acreditado: {client_cup} → {after}")
    finally:
        db.deposits.delete_many({"id": dep_id})
        db.deliveries.delete_many({"id": did})
        db.notifications.delete_many({"data.deposit_id": dep_id})
        cur = _usdt_balance(CLIENT_ID, "CUP")
        d1 = round(cur - client_cup, 4)
        if d1:
            db.users.update_one({"user_id": CLIENT_ID},
                                {"$inc": {"vip_balances.CUP": -d1}})
        d2 = round(_usdt_balance(COURIER_ID) - courier_bal, 4)
        if d2:
            db.users.update_one({"user_id": COURIER_ID},
                                {"$inc": {"vip_balances.USDT": -d2}})
