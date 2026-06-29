"""iter42: delivery_method ↔ to_code.type compatibility.

Covers the order-creation guardrail that prevents impossible combinations:
- USDT/BTC destination → cash/transfer rejected (cripto only)
- CUP/USD/BRL/MXN destination → crypto rejected (fiat envelope)
- accumulate is always allowed (stays as balance)
"""
import os
import uuid

import pytest
import requests
from pymongo import MongoClient

from conftest import BASE_URL, VIP_TOKEN, NORMAL_TOKEN


MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]


def _h(token=None):
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


@pytest.fixture(scope="module", autouse=True)
def _seed_rates():
    """Ensure both pairs exist (idempotent)."""
    db = MongoClient(MONGO_URL)[DB_NAME]
    for r in [
        {"id": "test_rate_usdt_cup", "from_code": "USDT", "to_code": "CUP",
         "rate_normal": 380, "rate_vip": 395, "real_rate": 410},
        {"id": "test_rate_usd_usdt", "from_code": "USD", "to_code": "USDT",
         "rate_normal": 0.97, "rate_vip": 0.99, "real_rate": 1.0},
        {"id": "test_rate_usd_cup", "from_code": "USD", "to_code": "CUP",
         "rate_normal": 380, "rate_vip": 395, "real_rate": 410},
    ]:
        db.rates.update_one({"from_code": r["from_code"], "to_code": r["to_code"]},
                            {"$set": r}, upsert=True)
    yield


def _new_details(tag: str) -> str:
    return f"TEST_iter42_{tag}_{uuid.uuid4().hex[:6]}"


class TestDeliveryMethodValidation:
    def test_cash_to_crypto_rejected(self):
        r = requests.post(
            f"{BASE_URL}/api/orders",
            headers=_h(NORMAL_TOKEN),
            json={
                "from_code": "USD", "to_code": "USDT", "amount_from": 10.0,
                "delivery_method": "cash",
                "delivery_details": _new_details("cash_to_crypto"),
                "sender_name": "Test Holder",
            },
        )
        assert r.status_code == 400, r.text
        assert "cripto" in r.text.lower() or "wallet" in r.text.lower()

    def test_transfer_to_crypto_rejected(self):
        r = requests.post(
            f"{BASE_URL}/api/orders",
            headers=_h(NORMAL_TOKEN),
            json={
                "from_code": "USD", "to_code": "USDT", "amount_from": 10.0,
                "delivery_method": "transfer",
                "delivery_details": _new_details("tx_to_crypto"),
                "sender_name": "Test Holder",
            },
        )
        assert r.status_code == 400, r.text

    def test_crypto_to_fiat_rejected(self):
        r = requests.post(
            f"{BASE_URL}/api/orders",
            headers=_h(NORMAL_TOKEN),
            json={
                "from_code": "USDT", "to_code": "CUP", "amount_from": 100.0,
                "delivery_method": "crypto",
                "delivery_details": _new_details("crypto_to_fiat"),
                "sender_name": "Test Holder",
            },
        )
        assert r.status_code == 400, r.text
        assert "fiat" in r.text.lower() or "transferencia" in r.text.lower()

    def test_transfer_to_fiat_accepted(self):
        r = requests.post(
            f"{BASE_URL}/api/orders",
            headers=_h(NORMAL_TOKEN),
            json={
                "from_code": "USDT", "to_code": "CUP", "amount_from": 100.0,
                "delivery_method": "transfer",
                "delivery_details": _new_details("transfer_to_fiat"),
                "sender_name": "Test Holder",
            },
        )
        assert r.status_code == 200, r.text

    def test_cash_to_fiat_accepted(self):
        r = requests.post(
            f"{BASE_URL}/api/orders",
            headers=_h(NORMAL_TOKEN),
            json={
                "from_code": "USDT", "to_code": "CUP", "amount_from": 100.0,
                "delivery_method": "cash",
                "delivery_details": _new_details("cash_to_fiat"),
                "sender_name": "Test Holder",
            },
        )
        assert r.status_code == 200, r.text

    def test_crypto_to_crypto_accepted(self):
        r = requests.post(
            f"{BASE_URL}/api/orders",
            headers=_h(NORMAL_TOKEN),
            json={
                "from_code": "USD", "to_code": "USDT", "amount_from": 10.0,
                "delivery_method": "crypto",
                "delivery_details": _new_details("crypto_to_crypto"),
                "sender_name": "Test Holder",
            },
        )
        assert r.status_code == 200, r.text

    def test_accumulate_always_allowed_for_vip(self):
        """accumulate is the 'no delivery' branch — must work regardless of to_code type."""
        for to_code in ("USDT", "CUP"):
            r = requests.post(
                f"{BASE_URL}/api/orders",
                headers=_h(VIP_TOKEN),
                json={
                    "from_code": "USDT" if to_code == "CUP" else "USD",
                    "to_code": to_code, "amount_from": 50.0,
                    "delivery_method": "accumulate",
                    "delivery_details": _new_details(f"accumulate_{to_code}"),
                    "sender_name": "Test Holder",
                },
            )
            assert r.status_code == 200, f"to_code={to_code} → {r.text}"
