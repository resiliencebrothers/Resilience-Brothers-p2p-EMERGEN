"""Empresa Fase 3 (EMP-03) — sub-saldo propio (igual que VIP/clientes).

El rol Empresa reutiliza la MISMA billetera que VIP y clientes normales:
- /vip/balances expone su saldo (las ventas del marketplace lo acreditan como
  a cualquier dueño de producto; los retiros/liquidación salen de aquí).
- Los endpoints de billetera solo bloquean a `employee`, por lo que `empresa`
  pasa el gate de rol (depósitos/retiros disponibles como a los clientes).
"""
import os
from datetime import datetime, timezone, timedelta

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL

API = f"{BASE_URL}/api"
EMP_ID = "user_test_empresa03"
EMP_TOKEN = "test_session_empresa03_X"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr():
    return {"Authorization": f"Bearer {EMP_TOKEN}", "Content-Type": "application/json"}


def _seed(balances):
    db = _db()
    db.users.update_one({"user_id": EMP_ID}, {"$set": {
        "user_id": EMP_ID, "email": "empresa3.test@example.com",
        "name": "Empresa Saldo Test", "role": "empresa", "account_status": "active",
        "email_verified": True, "phone_verified": True, "phone": "+5350000333",
        "vip_balances": balances}}, upsert=True)
    exp = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    db.user_sessions.update_one({"session_token": EMP_TOKEN},
        {"$set": {"session_token": EMP_TOKEN, "user_id": EMP_ID, "expires_at": exp}},
        upsert=True)


def _cleanup():
    db = _db()
    db.users.delete_many({"user_id": EMP_ID})
    db.user_sessions.delete_many({"session_token": EMP_TOKEN})


def test_empresa_can_read_its_sub_balance():
    _seed({"USDT": 42.5})
    try:
        r = requests.get(f"{API}/vip/balances", headers=_hdr(), timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        codes = {b["currency"]: b["amount"] for b in body["balances"]}
        assert abs(codes.get("USDT", 0) - 42.5) < 0.001
        assert body["total_usdt"] >= 42.5
    finally:
        _cleanup()


def test_empresa_wallet_not_blocked_by_role():
    """Un depósito con payload inválido devuelve 422 (validación), NO 403 por
    rol: demuestra que la Empresa pasa el gate de billetera de cliente."""
    _seed({})
    try:
        r = requests.post(f"{API}/deposits", headers=_hdr(),
                          json={"amount": 0, "currency": "", "method": ""}, timeout=15)
        assert r.status_code != 403, r.text
        assert r.status_code in (400, 422), r.text
    finally:
        _cleanup()
