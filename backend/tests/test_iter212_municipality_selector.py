"""iter212 — Selector de municipio: elección explícita del cliente cuando
ni el mapa ni el texto de la dirección detectan el municipio.

Verifica:
1. Cotización con `municipality` explícito (sin municipio en el texto).
2. La elección explícita GANA sobre la detección por texto.
3. Creación de retiro cash con `courier_municipality` explícito y dirección
   sin municipio → cobro automático de la tarifa fija.
"""
import os
import uuid

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, VIP_TOKEN, make_vip_totp

API = f"{BASE_URL}/api"
VIP_ID = "user_test_vip01"


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def test_quote_with_explicit_municipality():
    r = requests.get(f"{API}/vip/courier-municipality-quote",
                     headers=_hdr(VIP_TOKEN),
                     params={"municipality": "Boyeros",
                             "address": "Calle sin nombre 123",
                             "currency": "CUP", "amount": 500})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["matched"] is True
    assert body["municipality"] == "Boyeros"
    assert body["fee_usdt"] == 7.0


def test_explicit_pick_wins_over_text_detection():
    r = requests.get(f"{API}/vip/courier-municipality-quote",
                     headers=_hdr(VIP_TOKEN),
                     params={"municipality": "Cotorro",
                             "address": "Calle 23, Vedado",
                             "currency": "CUP", "amount": 500})
    body = r.json()
    assert body["municipality"] == "Cotorro"
    assert body["fee_usdt"] == 7.0


def test_withdraw_creation_with_explicit_municipality():
    db = _db()
    db.users.update_one({"user_id": VIP_ID},
                        {"$set": {"vip_balances.CUP": 100000.0}})
    body = {
        "amount_usd": 500.0, "currency": "CUP", "method": "cash",
        "cash_delivery_mode": "courier", "province": "La Habana",
        "details": ("Provincia: La Habana\nNombre: Iter212 Test\n"
                    "Celular: 5355512345\nDirección: Calle sin nombre 123, reparto perdido"),
        "courier_municipality": "Boyeros",
        "totp_code": make_vip_totp(),
    }
    r = requests.post(f"{API}/vip/withdraw", headers=_hdr(VIP_TOKEN), json=body)
    assert r.status_code == 200, r.text
    wid = r.json()["id"]
    try:
        w = db.withdrawals.find_one({"id": wid}, {"_id": 0})
        assert w["courier_fee_status"] == "charged"
        assert w.get("courier_municipality") == "Boyeros"
        assert float(w["courier_fee_usdt"]) == 7.0
        assert float(w.get("courier_km") or 0) == 0.0
        job = db.deliveries.find_one(
            {"kind": "withdrawal", "ref_id": wid,
             "status": {"$ne": "cancelled"}}, {"_id": 0})
        assert job and float(job["fee_usdt"]) == 7.0
    finally:
        db.withdrawals.delete_many({"id": wid})
        db.deliveries.delete_many({"ref_id": wid})
        db.users.update_one({"user_id": VIP_ID},
                            {"$set": {"vip_balances.CUP": 100000.0}})
