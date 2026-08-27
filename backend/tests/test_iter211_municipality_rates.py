"""iter211 — Tarifas fijas de mensajería por municipio (respaldo del mapa).

Verifica:
1. Auto-siembra de la tabla del operador con precio MÁS ALTO en rangos.
2. Cotización por texto de dirección (detección del municipio).
3. Creación de retiro cash SIN coordenadas + municipio en la dirección →
   cobro automático de la tarifa fija (status charged, delivery job creado).
4. Sin municipio detectable → sigue quedando en revisión manual (regresión).
5. Cobro staff por municipio en el endpoint courier-fee.
"""
import os
import uuid

import requests
from pymongo import MongoClient

from tests.conftest import (
    BASE_URL, ADMIN_TOKEN, VIP_TOKEN, make_vip_totp, with_totp_admin,
)

API = f"{BASE_URL}/api"
VIP_ID = "user_test_vip01"

EXPECTED_PRICES = {
    "10 de Octubre": 2.0,
    "Vedado": 3.0,
    "Centro Habana": 3.0,
    "Arroyo Naranjo": 5.0,       # rango 3–5 → más alto
    "San Miguel del Padrón": 5.0,
    "Cotorro": 7.0,              # rango 5–7 → más alto
    "Boyeros": 7.0,
    "Marianao": 7.0,
    "La Lisa": 7.0,
}


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _balance(cur="CUP"):
    u = _db().users.find_one({"user_id": VIP_ID}, {"vip_balances": 1})
    return float((u.get("vip_balances") or {}).get(cur) or 0)


def test_seed_and_admin_list():
    r = requests.get(f"{API}/admin/courier/municipality-rates",
                     headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    rows = {x["municipality"]: x for x in r.json()}
    assert len(rows) >= 15
    for name, price in EXPECTED_PRICES.items():
        assert name in rows, f"falta {name}"
        assert float(rows[name]["price_usdt"]) == price, (
            f"{name}: {rows[name]['price_usdt']} != {price}")
        assert rows[name]["active"] is True


def test_quote_endpoint_matches_by_address_text():
    cases = [
        ("Calle 23 entre L y M, El Vedado", 3.0, "Vedado"),
        ("Reparto XYZ, municipio Cotorro", 7.0, "Cotorro"),
        ("Ave 51, La Lisa, La Habana", 7.0, "La Lisa"),
        ("calle luz #10, habana vieja", 3.0, "Habana Vieja"),
    ]
    for address, price, muni in cases:
        r = requests.get(f"{API}/vip/courier-municipality-quote",
                         headers=_hdr(VIP_TOKEN),
                         params={"address": address, "currency": "CUP",
                                 "amount": 500})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["matched"] is True, f"{address}: no match"
        assert body["municipality"] == muni, f"{address}: {body['municipality']}"
        assert body["fee_usdt"] == price, f"{address}: {body['fee_usdt']}"
        assert body["fee_currency_amount"] > 0
    # sin municipio conocido → sin coincidencia
    r = requests.get(f"{API}/vip/courier-municipality-quote",
                     headers=_hdr(VIP_TOKEN),
                     params={"address": "Calle desconocida 123, Santiago",
                             "currency": "CUP", "amount": 500})
    assert r.json()["matched"] is False


def _create_cash_no_coords(address_line: str):
    body = {
        "amount_usd": 500.0, "currency": "CUP", "method": "cash",
        "cash_delivery_mode": "courier", "province": "La Habana",
        "details": (f"Provincia: La Habana\nNombre: Iter211 Test\n"
                    f"Celular: 5355512345\nDirección: {address_line}"),
        "totp_code": make_vip_totp(),
    }
    r = requests.post(f"{API}/vip/withdraw", headers=_hdr(VIP_TOKEN), json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _cleanup(wid, bal_before):
    db = _db()
    db.withdrawals.delete_many({"id": wid})
    db.deliveries.delete_many({"ref_id": wid})
    db.users.update_one({"user_id": VIP_ID},
                        {"$set": {"vip_balances.CUP": bal_before}})


def test_withdraw_creation_charges_municipality_when_map_fails():
    db = _db()
    db.users.update_one({"user_id": VIP_ID},
                        {"$set": {"vip_balances.CUP": 100000.0}})
    bal_before = 100000.0
    res = _create_cash_no_coords("Calle Maceo #45, Cotorro")
    wid = res["id"] if "id" in res else res.get("withdrawal", {}).get("id")
    try:
        w = db.withdrawals.find_one({"id": wid}, {"_id": 0})
        assert w, "retiro no creado"
        assert w["courier_fee_status"] == "charged", w["courier_fee_status"]
        assert w.get("courier_municipality") == "Cotorro"
        assert float(w["courier_fee_usdt"]) == 7.0
        assert float(w.get("courier_km") or 0) == 0.0
        assert w.get("courier_fee_charged_at")
        # saldo debitado: monto + tarifa convertida
        fee_cur = float(w["courier_fee_currency_amount"])
        assert fee_cur > 0
        assert round(bal_before - _balance(), 2) == round(500.0 + fee_cur, 2)
        # trabajo de mensajería creado con la tarifa fija
        job = db.deliveries.find_one(
            {"kind": "withdrawal", "ref_id": wid,
             "status": {"$ne": "cancelled"}}, {"_id": 0})
        assert job, "no se creó el trabajo de mensajería"
        assert float(job["fee_usdt"]) == 7.0
    finally:
        _cleanup(wid, bal_before)


def test_withdraw_creation_without_known_municipality_stays_manual():
    db = _db()
    db.users.update_one({"user_id": VIP_ID},
                        {"$set": {"vip_balances.CUP": 100000.0}})
    res = _create_cash_no_coords("Calle desconocida 123, reparto perdido")
    wid = res["id"] if "id" in res else res.get("withdrawal", {}).get("id")
    try:
        w = db.withdrawals.find_one({"id": wid}, {"_id": 0})
        assert w["courier_fee_status"] == "manual_review"
        assert not w.get("courier_municipality")
        assert float(w.get("courier_fee_usdt") or 0) == 0.0
    finally:
        _cleanup(wid, 100000.0)


def test_staff_charge_by_municipality():
    db = _db()
    db.users.update_one({"user_id": VIP_ID},
                        {"$set": {"vip_balances.CUP": 100000.0}})
    wid = f"test211_w_{uuid.uuid4().hex[:8]}"
    db.withdrawals.insert_one({
        "id": wid, "user_id": VIP_ID, "user_name": "VIP Test",
        "user_email": "vip.test@resilience.com",
        "method": "cash", "currency": "CUP", "amount_usd": 500,
        "status": "pending", "details": "d", "beneficiary_name": "b",
        "province": "La Habana", "courier_fee_status": "manual_review",
        "created_at": "2026-08-15T09:00:00+00:00",
    })
    try:
        r = requests.post(f"{API}/admin/withdrawals/{wid}/courier-fee",
                          headers=_hdr(ADMIN_TOKEN),
                          json=with_totp_admin({"municipality": "Vedado"}))
        assert r.status_code == 200, r.text
        w = r.json()
        assert float(w["courier_fee_usdt"]) == 3.0
        assert w.get("courier_municipality") == "Vedado"
        assert float(w.get("courier_km") or 0) == 0.0
        job = db.deliveries.find_one(
            {"kind": "withdrawal", "ref_id": wid,
             "status": {"$ne": "cancelled"}}, {"_id": 0})
        assert job and float(job["fee_usdt"]) == 3.0
        # municipio inexistente → 404
        r = requests.post(f"{API}/admin/withdrawals/{wid}/courier-fee",
                          headers=_hdr(ADMIN_TOKEN),
                          json=with_totp_admin({"municipality": "Narnia"}))
        assert r.status_code == 404
    finally:
        _cleanup(wid, 100000.0)
