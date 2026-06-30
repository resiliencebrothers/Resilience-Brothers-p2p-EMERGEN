"""iter43: GET /api/currencies/{code}/delivery-methods (public).

Source-of-truth endpoint that lets the frontend filter the delivery-method
dropdown without duplicating the heuristic in JS.
"""
import os
import uuid

import pytest
import requests
from pymongo import MongoClient

from conftest import BASE_URL


MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]


@pytest.fixture(scope="module")
def db():
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture(scope="module")
def seed_subtyped_currencies(db):
    """Insert two synthetic sub-typed currencies for the heuristic branches."""
    docs = [
        {"id": str(uuid.uuid4()), "code": "TST_T",
         "name": "Test Transferencia", "type": "fiat"},
        {"id": str(uuid.uuid4()), "code": "TST_E",
         "name": "Test Efectivo", "type": "fiat"},
        # explicit override wins over heuristic
        {"id": str(uuid.uuid4()), "code": "TST_OV",
         "name": "Test Override", "type": "fiat",
         "delivery_methods": ["cash"]},
    ]
    for d in docs:
        db.currencies.update_one({"code": d["code"]}, {"$set": d}, upsert=True)
    yield
    db.currencies.delete_many({"code": {"$in": [d["code"] for d in docs]}})


class TestDeliveryMethodsEndpoint:
    def test_404_for_unknown_currency(self):
        r = requests.get(f"{BASE_URL}/api/currencies/__nope__/delivery-methods")
        assert r.status_code == 404

    def test_crypto_returns_crypto_only(self):
        # USDT seeded by default
        r = requests.get(f"{BASE_URL}/api/currencies/USDT/delivery-methods")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["code"] == "USDT"
        assert body["type"] == "crypto"
        assert body["allowed"] == ["crypto"]

    def test_generic_fiat_returns_transfer_and_cash(self):
        r = requests.get(f"{BASE_URL}/api/currencies/CUP/delivery-methods")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["code"] == "CUP"
        assert body["type"] == "fiat"
        assert set(body["allowed"]) == {"transfer", "cash"}

    def test_subtyped_transferencia_returns_transfer_only(self, seed_subtyped_currencies):
        r = requests.get(f"{BASE_URL}/api/currencies/TST_T/delivery-methods")
        assert r.status_code == 200, r.text
        assert r.json()["allowed"] == ["transfer"]

    def test_subtyped_efectivo_returns_cash_only(self, seed_subtyped_currencies):
        r = requests.get(f"{BASE_URL}/api/currencies/TST_E/delivery-methods")
        assert r.status_code == 200, r.text
        assert r.json()["allowed"] == ["cash"]

    def test_explicit_delivery_methods_override_wins(self, seed_subtyped_currencies):
        r = requests.get(f"{BASE_URL}/api/currencies/TST_OV/delivery-methods")
        assert r.status_code == 200, r.text
        # Even though name "Override" hits neither hint, the explicit list wins.
        assert r.json()["allowed"] == ["cash"]

    def test_accumulate_is_never_in_allowed_list(self):
        # accumulate is a role-gated branch, not a delivery method.
        for code in ("USDT", "CUP"):
            r = requests.get(f"{BASE_URL}/api/currencies/{code}/delivery-methods")
            assert r.status_code == 200
            assert "accumulate" not in r.json()["allowed"]

    def test_endpoint_is_public_no_auth(self):
        r = requests.get(f"{BASE_URL}/api/currencies/USDT/delivery-methods",
                         headers={"Content-Type": "application/json"})
        assert r.status_code == 200
