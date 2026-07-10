"""iter55.19 — Withdrawal method must match currency.

Operator reported that a VIP with cash-only USD balance was seeing
"Transferencia bancaria" as the default withdrawal method — the dropdown was
hardcoded and the backend didn't enforce the same delivery-rules constraint
that already gates order creation (iter42/43).

Covers:
1. Currency with `delivery_methods=["cash"]` explicit → withdrawal method
   'transfer' is rejected with 400.
2. Same currency → withdrawal method 'cash' is accepted (happy path).
3. Currency inferred as cash-only via NAME heuristic ("USD Efectivo") →
   'transfer' rejected.
4. Crypto currency → withdrawal method 'transfer' rejected; 'crypto' accepted.
5. Delivery methods endpoint returns the expected list for the sub-typed
   currency (integration coverage for the frontend dropdown).
"""
import os
import uuid
import requests
from pymongo import MongoClient

from tests.conftest import (
    BASE_URL, VIP_TOKEN, make_vip_totp,
)


API = f"{BASE_URL}/api"


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _sync_db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _upsert_currency(code: str, name: str, ctype: str, delivery_methods=None):
    db = _sync_db()
    db.currencies.update_one(
        {"code": code},
        {"$set": {
            "code": code,
            "name": name,
            "type": ctype,
            "is_active": True,
            "delivery_methods": delivery_methods,
            "updated_at": "2026-07-10T00:00:00+00:00",
        },
         "$setOnInsert": {"id": uuid.uuid4().hex, "created_at": "2026-07-10T00:00:00+00:00"}},
        upsert=True,
    )


def _seed_vip_balance(currency: str, amount: float):
    db = _sync_db()
    db.users.update_one(
        {"user_id": "user_test_vip01"},
        {"$set": {f"vip_balances.{currency}": amount}},
    )


def _clear_balance(currency: str):
    db = _sync_db()
    db.users.update_one(
        {"user_id": "user_test_vip01"},
        {"$unset": {f"vip_balances.{currency}": ""}},
    )


# ------------------------------------------------------------------
# 1. Explicit cash-only currency rejects transfer
# ------------------------------------------------------------------

def test_cash_only_currency_rejects_transfer_withdrawal():
    _upsert_currency("USDCASH_TEST", "USD Efectivo Test", "fiat",
                     delivery_methods=["cash"])
    _seed_vip_balance("USDCASH_TEST", 500)

    r = requests.post(
        f"{API}/vip/withdraw", headers=_hdr(VIP_TOKEN),
        json={
            "amount_usd": 100,
            "currency": "USDCASH_TEST",
            "method": "transfer",
            "details": "cuenta 1234",
            "beneficiary_name": "Test",
            "totp_code": make_vip_totp(),
        },
    )
    assert r.status_code == 400, r.text
    detail = r.json().get("detail", "")
    # Human-friendly rejection message (matches _METHOD_ES map)
    assert "efectivo" in detail.lower()
    assert "transferencia" in detail.lower()

    _clear_balance("USDCASH_TEST")


# ------------------------------------------------------------------
# 2. Explicit cash-only currency accepts cash — happy path
# ------------------------------------------------------------------

def test_cash_only_currency_accepts_cash_withdrawal():
    _upsert_currency("USDCASH_TEST", "USD Efectivo Test", "fiat",
                     delivery_methods=["cash"])
    _seed_vip_balance("USDCASH_TEST", 500)

    r = requests.post(
        f"{API}/vip/withdraw", headers=_hdr(VIP_TOKEN),
        json={
            "amount_usd": 100,
            "currency": "USDCASH_TEST",
            "method": "cash",
            "details": "recogida en oficina",
            "beneficiary_name": "Test",
            "totp_code": make_vip_totp(),
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["method"] == "cash"
    assert body["currency"] == "USDCASH_TEST"

    # Cleanup
    _sync_db().withdrawals.delete_many({"id": body["id"]})
    _clear_balance("USDCASH_TEST")


# ------------------------------------------------------------------
# 3. Cash-only inferred by name heuristic (no explicit delivery_methods)
# ------------------------------------------------------------------

def test_heuristic_cash_currency_rejects_transfer():
    # No explicit delivery_methods → name heuristic kicks in ("efectivo")
    _upsert_currency("USDCASH2_TEST", "USD Efectivo", "fiat",
                     delivery_methods=None)
    _seed_vip_balance("USDCASH2_TEST", 500)

    r = requests.post(
        f"{API}/vip/withdraw", headers=_hdr(VIP_TOKEN),
        json={
            "amount_usd": 100,
            "currency": "USDCASH2_TEST",
            "method": "transfer",
            "details": "cuenta 1234",
            "beneficiary_name": "Test",
            "totp_code": make_vip_totp(),
        },
    )
    assert r.status_code == 400, r.text
    _clear_balance("USDCASH2_TEST")


# ------------------------------------------------------------------
# 4. Crypto currency: transfer rejected, crypto accepted
# ------------------------------------------------------------------

def test_crypto_currency_rejects_transfer_accepts_crypto():
    _upsert_currency("USDT_TEST", "Tether Test", "crypto",
                     delivery_methods=None)
    _seed_vip_balance("USDT_TEST", 500)

    r_bad = requests.post(
        f"{API}/vip/withdraw", headers=_hdr(VIP_TOKEN),
        json={
            "amount_usd": 50,
            "currency": "USDT_TEST",
            "method": "transfer",
            "details": "wire",
            "beneficiary_name": "Test",
            "totp_code": make_vip_totp(),
        },
    )
    assert r_bad.status_code == 400, r_bad.text

    r_ok = requests.post(
        f"{API}/vip/withdraw", headers=_hdr(VIP_TOKEN),
        json={
            "amount_usd": 50,
            "currency": "USDT_TEST",
            "method": "crypto",
            "details": "TXxxxxxxxx TRC20 address",
            "beneficiary_name": "Test",
            "totp_code": make_vip_totp(),
        },
    )
    assert r_ok.status_code == 200, r_ok.text
    body = r_ok.json()
    _sync_db().withdrawals.delete_many({"id": body["id"]})
    _clear_balance("USDT_TEST")


# ------------------------------------------------------------------
# 5. Delivery-methods endpoint returns cash-only for the frontend
# ------------------------------------------------------------------

def test_delivery_methods_endpoint_returns_cash_for_effective_currency():
    _upsert_currency("USDCASH_TEST", "USD Efectivo Test", "fiat",
                     delivery_methods=["cash"])
    r = requests.get(f"{API}/currencies/USDCASH_TEST/delivery-methods")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["code"] == "USDCASH_TEST"
    assert body["allowed"] == ["cash"]


# ------------------------------------------------------------------
# 6. Regression — transfer-friendly USD stays functional
# ------------------------------------------------------------------

def test_default_transfer_currency_still_accepts_transfer():
    # Vanilla USD with no override: the heuristic returns ["transfer", "cash"]
    _upsert_currency("USD_TEST_XFR", "USD", "fiat", delivery_methods=None)
    _seed_vip_balance("USD_TEST_XFR", 500)

    r = requests.post(
        f"{API}/vip/withdraw", headers=_hdr(VIP_TOKEN),
        json={
            "amount_usd": 25,
            "currency": "USD_TEST_XFR",
            "method": "transfer",
            "details": "banco X cuenta 999",
            "beneficiary_name": "Test",
            "totp_code": make_vip_totp(),
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    _sync_db().withdrawals.delete_many({"id": body["id"]})
    _clear_balance("USD_TEST_XFR")
