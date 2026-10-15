"""Fase 4 — Ciclo económico de la mensajería de Empresa.

- Al crear la solicitud se RETIENE la tarifa fija del sub-saldo USDT.
- Sin saldo suficiente → 402, nada queda a medias.
- Al cancelar antes de completarse → la tarifa se REEMBOLSA íntegra.
- Al CONFIRMARSE la entrega → el mensajero cobra su parte y Resilience retiene
  la comisión; la solicitud queda 'confirmed'/'charged'.
"""
import os
from datetime import datetime, timezone, timedelta

import pytest
import requests
from pymongo import MongoClient

from db_client import db
from tests.conftest import BASE_URL
import routes.company  # noqa: F401 — registra el handler de liquidación company_delivery

API = f"{BASE_URL}/api"
EMP = "user_test_empresa_f4bill"
EMP_TOKEN = "test_session_empresa_f4bill"
COURIER = "user_test_courier_f4bill"


def _sdb():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr():
    return {"Authorization": f"Bearer {EMP_TOKEN}", "Content-Type": "application/json"}


def _seed(balance=100.0, fee=5.0):
    d = _sdb()
    exp = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    d.users.update_one({"user_id": EMP}, {"$set": {
        "user_id": EMP, "email": "empresa.f4bill@example.com",
        "name": "Empresa F4Bill", "role": "empresa", "account_status": "active",
        "email_verified": True, "phone_verified": True, "phone": "+5350004411",
        "vip_balances": {"USDT": balance}}}, upsert=True)
    d.users.update_one({"user_id": COURIER}, {"$set": {
        "user_id": COURIER, "email": "courier.f4bill@example.com",
        "name": "Mensajero F4Bill", "role": "vip", "is_courier": True,
        "account_status": "active", "vip_balances": {"USDT": 0.0}}}, upsert=True)
    d.user_sessions.update_one({"session_token": EMP_TOKEN}, {"$set": {
        "session_token": EMP_TOKEN, "user_id": EMP, "expires_at": exp}}, upsert=True)
    d.settings.update_one({"id": "global"},
                          {"$set": {"company_delivery_fee_usdt": fee}}, upsert=True)


def _cleanup():
    d = _sdb()
    d.company_delivery_requests.delete_many({"company_id": EMP})
    d.deliveries.delete_many({"user_id": EMP})
    d.credit_ops.delete_many({"op_id": {"$regex": "^cdeliv-fee:"}})


def _bal(uid):
    return float((_sdb().users.find_one({"user_id": uid}) or {})
                 .get("vip_balances", {}).get("USDT", 0.0))


def _mk_payload():
    return {"receiver_name": "Juan Perez", "receiver_phone": "+5355550000",
            "delivery_address": "Calle 23 #456, Vedado, La Habana"}


def test_fee_is_held_on_create_and_delivery_carries_shares():
    _seed(balance=100.0, fee=5.0); _cleanup()
    r = requests.post(f"{API}/company/deliveries", headers=_hdr(),
                      json=_mk_payload(), timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["fee_usdt"] == 5.0 and body["fee_status"] == "held"
    assert _bal(EMP) == 95.0                       # tarifa retenida
    # El trabajo de mensajería lleva la tarifa y el reparto mensajero/plataforma.
    dj = _sdb().deliveries.find_one({"id": body["delivery_id"]})
    assert dj and float(dj["fee_usdt"]) == 5.0
    assert float(dj["courier_share_usdt"]) + float(dj["platform_share_usdt"]) == 5.0
    assert float(dj["platform_share_usdt"]) > 0    # comisión de Resilience
    _cleanup()


def test_insufficient_balance_rejects_and_holds_nothing():
    _seed(balance=2.0, fee=5.0); _cleanup()
    r = requests.post(f"{API}/company/deliveries", headers=_hdr(),
                      json=_mk_payload(), timeout=15)
    assert r.status_code == 402, r.text
    assert _bal(EMP) == 2.0                         # nada retenido
    assert _sdb().company_delivery_requests.count_documents({"company_id": EMP}) == 0
    _cleanup()


def test_cancel_refunds_fee_in_full():
    _seed(balance=100.0, fee=5.0); _cleanup()
    rid = requests.post(f"{API}/company/deliveries", headers=_hdr(),
                        json=_mk_payload(), timeout=15).json()["id"]
    assert _bal(EMP) == 95.0
    r = requests.post(f"{API}/company/deliveries/{rid}/cancel", headers=_hdr(), timeout=15)
    assert r.status_code == 200, r.text
    assert _bal(EMP) == 100.0                       # reembolso íntegro
    req = _sdb().company_delivery_requests.find_one({"id": rid})
    assert req["status"] == "cancelled" and req["fee_status"] == "refunded"
    # Cancelar de nuevo no vuelve a reembolsar (idempotente).
    requests.post(f"{API}/company/deliveries/{rid}/cancel", headers=_hdr(), timeout=15)
    assert _bal(EMP) == 100.0
    _cleanup()


@pytest.mark.asyncio
async def test_confirm_pays_courier_and_charges_fee():
    _seed(balance=100.0, fee=5.0); _cleanup()
    # Crea la solicitud (tarifa retenida).
    rid = requests.post(f"{API}/company/deliveries", headers=_hdr(),
                        json=_mk_payload(), timeout=15).json()["id"]
    did = (await db.company_delivery_requests.find_one({"id": rid}))["delivery_id"]
    # Simula el ciclo hasta 'delivered' con el mensajero asignado.
    await db.deliveries.update_one({"id": did}, {"$set": {
        "status": "delivered", "courier_id": COURIER, "courier_name": "Mensajero F4Bill"}})
    d = await db.deliveries.find_one({"id": did}, {"_id": 0})
    courier_share = float(d["courier_share_usdt"])
    from services.deliveries import do_confirm_delivery
    await do_confirm_delivery(d, {"user_id": "user_test_admin01", "name": "Admin"})
    assert _bal(COURIER) == courier_share           # mensajero cobró su parte
    assert _bal(EMP) == 95.0                         # la empresa NO recupera la tarifa
    req = await db.company_delivery_requests.find_one({"id": rid})
    assert req["status"] == "confirmed" and req["fee_status"] == "charged"
    _cleanup()
