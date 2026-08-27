"""iter205 — regresión: los candados de mensajería NO deben afectar a
retiros transfer/crypto, y el candado equivalente del marketplace debe
seguir bloqueando "delivered" hasta que exista cobro + mensajero entregado.
"""
import os
import time
import uuid
import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, VIP_TOKEN, make_vip_totp, with_totp_admin

API = f"{BASE_URL}/api"
VIP_ID = "user_test_vip01"


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _seed_balance(currency: str, amount: float):
    if currency == "USD":
        _db().users.update_one({"user_id": VIP_ID},
                               {"$set": {"vip_balance_usd": amount}})
    else:
        _db().users.update_one({"user_id": VIP_ID},
                               {"$set": {f"vip_balances.{currency}": amount}})


def _set_status(wid, status, extra=None):
    body = {"status": status, **(extra or {})}
    return requests.put(f"{API}/admin/withdrawals/{wid}/status",
                        headers=_hdr(ADMIN_TOKEN),
                        json=with_totp_admin(body))


def _cleanup_w(wid):
    _db().withdrawals.delete_one({"id": wid})
    _db().deliveries.delete_many({"ref_id": wid})


# ---------- Transfer regression: no cash locks, needs proof to be paid ----------
def test_transfer_withdrawal_unaffected_by_cash_locks():
    _seed_balance("USD", 500)
    r = requests.post(f"{API}/vip/withdraw", headers=_hdr(VIP_TOKEN), json={
        "amount_usd": 25.0, "currency": "USD", "method": "transfer",
        "details": "Zelle: test.regression@example.com",
        "totp_code": make_vip_totp(),
    })
    assert r.status_code == 200, r.text
    w = r.json()
    wid = w["id"]
    try:
        # No courier fields for non-cash
        assert w.get("courier_fee_status") in (None, "none"), w.get("courier_fee_status")
        # No delivery job created
        assert _db().deliveries.find_one({"ref_id": wid}) is None
        # Approve first (no gate)
        assert _set_status(wid, "approved").status_code == 200
        # 'paid' without proof → 400 (transfer needs payout_proof_image),
        #   NOT 409 mensajería
        r_no_proof = _set_status(wid, "paid")
        assert r_no_proof.status_code == 400, r_no_proof.text
        assert "captura" in r_no_proof.json()["detail"].lower()
        # With proof → 200
        proof = ("data:image/png;base64,"
                 "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=")
        r_ok = _set_status(wid, "paid", {"payout_proof_image": proof})
        assert r_ok.status_code == 200, r_ok.text
    finally:
        _cleanup_w(wid)


# ---------- Crypto regression: no cash locks, needs tx_hash to be paid ----------
def test_crypto_withdrawal_unaffected_by_cash_locks():
    _seed_balance("USDT", 500)
    # Valid TRC20 address (34 chars, T prefix)
    addr = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
    r = requests.post(f"{API}/vip/withdraw", headers=_hdr(VIP_TOKEN), json={
        "amount_usd": 15.0, "currency": "USDT", "method": "crypto",
        "details": addr,
        "crypto_network": "TRC20",
        "totp_code": make_vip_totp(),
    })
    assert r.status_code == 200, r.text
    w = r.json()
    wid = w["id"]
    try:
        assert w.get("courier_fee_status") in (None, "none")
        assert _db().deliveries.find_one({"ref_id": wid}) is None
        assert _set_status(wid, "approved").status_code == 200
        # 'paid' without tx_hash and no proof → 400 (evidence), NOT 409 mensajería
        r_no_hash = _set_status(wid, "paid")
        assert r_no_hash.status_code == 400, r_no_hash.text
        detail = r_no_hash.json()["detail"]
        # Should mention hash/proof, not messenger
        assert "mensajero" not in str(detail).lower()
        # Valid TRC20 tx hash (64 hex chars)
        tx = "a" * 64
        r_ok = _set_status(wid, "paid", {"payout_tx_hash": tx})
        assert r_ok.status_code == 200, r_ok.text
    finally:
        _cleanup_w(wid)


# ---------- Marketplace redemption courier lock ----------
def test_redemption_delivered_blocked_without_courier():
    # Seed test product + big USD balance
    pid = f"prod_test_iter205_{uuid.uuid4().hex[:8]}"
    _db().products.insert_one({
        "id": pid, "name": "Test Product iter205", "description": "regression",
        "price_usd": 20.0, "cost_usd": 5.0, "stock": 5, "image_url": "",
        "active": True, "created_at": "2026-01-01T00:00:00+00:00",
    })
    _seed_balance("USD", 2000)
    rid = None
    try:
        # Redemption WITHOUT coords → manual_review
        r = requests.post(f"{API}/vip/redeem", headers=_hdr(VIP_TOKEN), json={
            "product_id": pid, "quantity": 1,
            "delivery_address": "Test address regression",
            "totp_code": make_vip_totp(),
        })
        assert r.status_code == 200, r.text
        red = r.json()
        rid = red["id"]
        assert red.get("courier_fee_status") == "manual_review", red

        # Try delivered → 409 sin cobrar
        r_del = requests.put(f"{API}/admin/redemptions/{rid}/status",
                             headers=_hdr(ADMIN_TOKEN),
                             json=with_totp_admin({"status": "delivered"}))
        assert r_del.status_code == 409, r_del.text
        assert "sin cobrar" in r_del.json()["detail"].lower()

        # Cobrar mensajería manualmente (km=3)
        r_fee = requests.post(f"{API}/admin/redemptions/{rid}/courier-fee",
                              headers=_hdr(ADMIN_TOKEN),
                              json=with_totp_admin({"km": 3}))
        assert r_fee.status_code == 200, r_fee.text

        # Aún sin mensajero → 409
        r_del2 = requests.put(f"{API}/admin/redemptions/{rid}/status",
                              headers=_hdr(ADMIN_TOKEN),
                              json=with_totp_admin({"status": "delivered"}))
        assert r_del2.status_code == 409, r_del2.text
        assert ("mensajero" in r_del2.json()["detail"].lower()
                or "no existe" in r_del2.json()["detail"].lower())

        # Marcar entrega como delivered en DB
        _db().deliveries.update_one(
            {"kind": "redemption", "ref_id": rid, "status": {"$ne": "cancelled"}},
            {"$set": {"status": "delivered", "courier_id": VIP_ID,
                      "courier_name": "Test Courier"}})

        # Ahora sí → 200
        r_ok = requests.put(f"{API}/admin/redemptions/{rid}/status",
                            headers=_hdr(ADMIN_TOKEN),
                            json=with_totp_admin({"status": "delivered"}))
        assert r_ok.status_code == 200, r_ok.text
    finally:
        if rid:
            _db().redemptions.delete_one({"id": rid})
            _db().deliveries.delete_many({"ref_id": rid})
        _db().products.delete_one({"id": pid})
