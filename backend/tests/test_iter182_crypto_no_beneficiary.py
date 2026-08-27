"""iter182 — Crypto withdrawals no longer require the bank-account holder
(`beneficiary_name`). The on-chain address in `details` identifies the
destination. Transfer/cash withdrawals still require it (400 otherwise).
"""
import os
import uuid
import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, VIP_TOKEN, make_vip_totp

API = f"{BASE_URL}/api"
TRC20_ADDR = "TJRabRWQdrJc7iCPFy4gnPCJcXbc17ncCk"


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _sync_db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _seed(code, ctype="crypto"):
    _sync_db().currencies.update_one(
        {"code": code},
        {"$set": {"code": code, "name": f"Test {code}", "type": ctype,
                  "is_active": True, "delivery_methods": None},
         "$setOnInsert": {"id": uuid.uuid4().hex, "created_at": "2026-07-10T00:00:00+00:00"}},
        upsert=True,
    )
    _sync_db().users.update_one(
        {"user_id": "user_test_vip01"},
        {"$set": {f"vip_balances.{code}": 5000}},
    )


def _cleanup(code):
    _sync_db().currencies.delete_one({"code": code})
    _sync_db().users.update_one(
        {"user_id": "user_test_vip01"},
        {"$unset": {f"vip_balances.{code}": ""}},
    )
    _sync_db().withdrawals.delete_many({"currency": code})


def test_crypto_withdrawal_without_beneficiary_succeeds():
    code = "USDT182A"
    _seed(code)
    try:
        r = requests.post(
            f"{API}/vip/withdraw", headers=_hdr(VIP_TOKEN),
            json={
                "amount_usd": 25, "currency": code, "method": "crypto",
                "details": TRC20_ADDR, "crypto_network": "TRC20",
                # NO beneficiary_name at all
                "totp_code": make_vip_totp(),
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["method"] == "crypto"
        doc = _sync_db().withdrawals.find_one({"id": body["id"]})
        assert doc is not None
        assert doc.get("beneficiary_name", "") == ""
    finally:
        _cleanup(code)


def test_crypto_withdrawal_ignores_sent_beneficiary():
    """Even if the client sends a beneficiary for crypto, we store empty."""
    code = "USDT182B"
    _seed(code)
    try:
        r = requests.post(
            f"{API}/vip/withdraw", headers=_hdr(VIP_TOKEN),
            json={
                "amount_usd": 25, "currency": code, "method": "crypto",
                "details": TRC20_ADDR, "crypto_network": "TRC20",
                "beneficiary_name": "Juan Pérez",
                "totp_code": make_vip_totp(),
            },
        )
        assert r.status_code == 200, r.text
        doc = _sync_db().withdrawals.find_one({"id": r.json()["id"]})
        assert doc.get("beneficiary_name", "") == ""
    finally:
        _cleanup(code)


def test_transfer_withdrawal_without_beneficiary_succeeds_iter191():
    """iter191 — the holder requirement was dropped for transfers too."""
    code = "USDX182C"
    _seed(code, ctype="fiat")
    try:
        r = requests.post(
            f"{API}/vip/withdraw", headers=_hdr(VIP_TOKEN),
            json={
                "amount_usd": 10, "currency": code, "method": "transfer",
                "details": "Banco Popular · cuenta 0102987654321",
                # NO beneficiary_name
                "totp_code": make_vip_totp(),
            },
        )
        assert r.status_code == 200, r.text
        doc = _sync_db().withdrawals.find_one({"id": r.json()["id"]})
        assert doc.get("beneficiary_name", "") == ""
    finally:
        _cleanup(code)


def test_transfer_withdrawal_with_beneficiary_succeeds():
    code = "USDX182D"
    _seed(code, ctype="fiat")
    try:
        r = requests.post(
            f"{API}/vip/withdraw", headers=_hdr(VIP_TOKEN),
            json={
                "amount_usd": 10, "currency": code, "method": "transfer",
                "details": "Banco Popular · cuenta 0102987654321",
                "beneficiary_name": "Juan Pérez",
                "totp_code": make_vip_totp(),
            },
        )
        assert r.status_code == 200, r.text
        doc = _sync_db().withdrawals.find_one({"id": r.json()["id"]})
        assert doc.get("beneficiary_name") == "Juan Pérez"
    finally:
        _cleanup(code)


CASH_DETAILS = (
    "Nombre: Juan Pérez Rodríguez\n"
    "Celular: +53 55512345\n"
    "Dirección: Calle 23 #456, Vedado, La Habana"
)


def test_cash_withdrawal_without_beneficiary_succeeds():
    """iter183 — cash is delivered in person; no bank holder needed."""
    code = "CUPE183A"
    _seed(code, ctype="fiat")
    _sync_db().currencies.update_one(
        {"code": code}, {"$set": {"delivery_methods": ["cash"]}})
    try:
        r = requests.post(
            f"{API}/vip/withdraw", headers=_hdr(VIP_TOKEN),
            json={
                "amount_usd": 25, "currency": code, "method": "cash",
                "details": CASH_DETAILS,
                "province": "La Habana",
                # NO beneficiary_name
                "totp_code": make_vip_totp(),
            },
        )
        assert r.status_code == 200, r.text
    finally:
        _cleanup(code)


def test_cash_withdrawal_stores_receiver_as_beneficiary_when_sent():
    """The frontend auto-fills the cash receiver name for accounting."""
    code = "CUPE183B"
    _seed(code, ctype="fiat")
    _sync_db().currencies.update_one(
        {"code": code}, {"$set": {"delivery_methods": ["cash"]}})
    try:
        r = requests.post(
            f"{API}/vip/withdraw", headers=_hdr(VIP_TOKEN),
            json={
                "amount_usd": 25, "currency": code, "method": "cash",
                "details": CASH_DETAILS,
                "province": "La Habana",
                "beneficiary_name": "Juan Pérez Rodríguez",
                "totp_code": make_vip_totp(),
            },
        )
        assert r.status_code == 200, r.text
        doc = _sync_db().withdrawals.find_one({"id": r.json()["id"]})
        assert doc.get("beneficiary_name") == "Juan Pérez Rodríguez"
    finally:
        _cleanup(code)
