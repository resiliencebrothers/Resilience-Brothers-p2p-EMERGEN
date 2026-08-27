"""iter205 — Candados anti-pérdida de mensajería en retiros de efectivo.

1. Con coords → la mensajería se COBRA al crear (saldo = monto + fee) y se
   crea el trabajo de mensajero.
2. Sin coords → 'manual_review': el staff no puede marcar 'paid' sin cobrar.
3. Protocolo del mensajero: 'paid' exige que un mensajero haya marcado la
   entrega como realizada (delivered/confirmed).
4. Recogida en oficina → sin fee, sin mensajero, pago directo permitido.
5. Gratis ≥ umbral → sin fee pero MISMO protocolo de mensajero.
6. Rechazo/cancelación → reembolsa monto+fee y cancela el trabajo.
"""
import os
import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, VIP_TOKEN, make_vip_totp, with_totp_admin

API = f"{BASE_URL}/api"
VIP_ID = "user_test_vip01"
COORDS = {"delivery_latitude": 23.1395146, "delivery_longitude": -82.3825415}


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _seed_balance(amount: float):
    _db().users.update_one({"user_id": VIP_ID},
                           {"$set": {"vip_balances.CUP": amount}})


def _balance():
    u = _db().users.find_one({"user_id": VIP_ID}, {"vip_balances": 1})
    return float((u.get("vip_balances") or {}).get("CUP") or 0)


def _create_cash(amount=100.0, mode="courier", coords=True):
    body = {
        "amount_usd": amount, "currency": "CUP", "method": "cash",
        "cash_delivery_mode": mode,
        "details": ("Modalidad: Recogida en oficina\nNombre: Iter205 Test\nCelular: 5355512345"
                    if mode == "office_pickup" else
                    "Provincia: La Habana\nNombre: Iter205 Test\nCelular: 5355512345\nDirección: Hotel Habana Libre"),
        "totp_code": make_vip_totp(),
    }
    if mode == "courier":
        body["province"] = "La Habana"
        if coords:
            body.update(COORDS)
    r = requests.post(f"{API}/vip/withdraw", headers=_hdr(VIP_TOKEN), json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _job(wid):
    return _db().deliveries.find_one(
        {"kind": "withdrawal", "ref_id": wid, "status": {"$ne": "cancelled"}},
        {"_id": 0})


def _mark_delivered(wid):
    _db().deliveries.update_one(
        {"kind": "withdrawal", "ref_id": wid, "status": {"$ne": "cancelled"}},
        {"$set": {"status": "delivered", "courier_id": VIP_ID,
                  "courier_name": "Mensajero Test"}})


def _set_status(wid, status):
    return requests.put(f"{API}/admin/withdrawals/{wid}/status",
                        headers=_hdr(ADMIN_TOKEN),
                        json=with_totp_admin({"status": status}))


def _cleanup(wid):
    _db().withdrawals.delete_one({"id": wid})
    _db().deliveries.delete_many({"ref_id": wid})


def test_creation_with_coords_charges_fee_and_creates_job():
    _seed_balance(10000)
    w = _create_cash()
    try:
        assert w["courier_fee_status"] == "charged", w
        assert float(w["courier_fee_usdt"]) > 0
        fee_cur = float(w["courier_fee_currency_amount"])
        assert fee_cur > 0
        assert abs(_balance() - (10000 - 100 - fee_cur)) < 0.01
        job = _job(w["id"])
        assert job and job["status"] == "available"
        assert float(job["fee_usdt"]) == float(w["courier_fee_usdt"])
    finally:
        _cleanup(w["id"])


def test_paid_blocked_until_courier_delivers():
    _seed_balance(10000)
    w = _create_cash()
    try:
        r = _set_status(w["id"], "paid")
        assert r.status_code == 409, r.text
        assert "mensajero" in r.json()["detail"].lower()
        _mark_delivered(w["id"])
        r = _set_status(w["id"], "paid")
        assert r.status_code == 200, r.text
    finally:
        _cleanup(w["id"])


def test_no_coords_manual_review_blocks_paid_until_fee_charged():
    _seed_balance(10000)
    w = _create_cash(coords=False)
    try:
        assert w["courier_fee_status"] == "manual_review", w
        assert abs(_balance() - 9900) < 0.01  # solo el monto, sin fee
        assert _job(w["id"]) is None
        r = _set_status(w["id"], "paid")
        assert r.status_code == 409, r.text
        assert "sin cobrar" in r.json()["detail"].lower()
        # staff cobra la tarifa manualmente → se crea el trabajo
        r = requests.post(f"{API}/admin/withdrawals/{w['id']}/courier-fee",
                          headers=_hdr(ADMIN_TOKEN),
                          json=with_totp_admin({"km": 4}))
        assert r.status_code == 200, r.text
        assert _job(w["id"]) is not None
        r = _set_status(w["id"], "paid")
        assert r.status_code == 409  # aún falta el mensajero
        _mark_delivered(w["id"])
        assert _set_status(w["id"], "paid").status_code == 200
    finally:
        _cleanup(w["id"])


def test_office_pickup_waives_fee_and_courier():
    _seed_balance(10000)
    w = _create_cash(mode="office_pickup")
    try:
        assert w["courier_fee_status"] == "waived", w
        assert w["cash_delivery_mode"] == "office_pickup"
        assert abs(_balance() - 9900) < 0.01
        assert _job(w["id"]) is None
        assert _set_status(w["id"], "paid").status_code == 200
    finally:
        _cleanup(w["id"])


def test_free_threshold_skips_fee_but_requires_courier():
    _seed_balance(900000)
    w = _create_cash(amount=400000)  # ≈1050+ USDT ≥ 1000 → gratis
    try:
        assert w["courier_fee_status"] == "free", w
        assert float(w.get("courier_fee_usdt") or 0) == 0
        job = _job(w["id"])
        assert job and float(job["fee_usdt"]) == 0
        r = _set_status(w["id"], "paid")
        assert r.status_code == 409, r.text
        _mark_delivered(w["id"])
        assert _set_status(w["id"], "paid").status_code == 200
    finally:
        _cleanup(w["id"])


def test_reject_refunds_amount_plus_fee_and_cancels_job():
    _seed_balance(10000)
    w = _create_cash()
    try:
        assert _set_status(w["id"], "rejected").status_code == 200
        assert abs(_balance() - 10000) < 0.01  # monto + fee devueltos
        assert _job(w["id"]) is None  # trabajo cancelado
    finally:
        _cleanup(w["id"])


def test_client_cancel_refunds_and_cancels_job():
    _seed_balance(10000)
    w = _create_cash()
    try:
        r = requests.post(f"{API}/vip/withdrawals/{w['id']}/cancel",
                          headers=_hdr(VIP_TOKEN),
                          json={"totp_code": make_vip_totp()})
        assert r.status_code == 200, r.text
        assert abs(_balance() - 10000) < 0.01
        assert _job(w["id"]) is None
    finally:
        _cleanup(w["id"])
