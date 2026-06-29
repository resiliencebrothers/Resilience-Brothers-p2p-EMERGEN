"""iter43: sub-typed currency delivery rules (e.g. CUPT transferencia / CUPE efectivo).

Tests the `delivery_rules.allowed_delivery_methods` helper + the API guardrail
against custom currencies that the admin creates with sub-method semantics.
"""
import os
import uuid

import pytest
import requests
from pymongo import MongoClient

from conftest import BASE_URL, ADMIN_TOKEN, NORMAL_TOKEN, make_admin_totp


MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]


def _h(token=None):
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


# ---------------- UNIT: helper logic ----------------

class TestAllowedDeliveryMethods:
    def _imp(self):
        import sys
        sys.path.insert(0, "/app/backend")
        from services.delivery_rules import allowed_delivery_methods, is_delivery_method_allowed
        return allowed_delivery_methods, is_delivery_method_allowed

    def test_declared_list_wins(self):
        allowed, _ = self._imp()
        c = {"code": "WEIRD", "type": "fiat", "name": "anything",
             "delivery_methods": ["transfer"]}
        assert allowed(c) == ["transfer"]

    def test_crypto_type_returns_crypto(self):
        allowed, _ = self._imp()
        assert allowed({"code": "BTC", "type": "crypto", "name": "Bitcoin"}) == ["crypto"]
        assert allowed({"code": "USDT", "type": "crypto", "name": "Tether"}) == ["crypto"]

    def test_name_transferencia_returns_transfer_only(self):
        allowed, _ = self._imp()
        c = {"code": "CUPT", "type": "fiat", "name": "Peso Cubano Transferencia"}
        assert allowed(c) == ["transfer"]

    def test_name_efectivo_returns_cash_only(self):
        allowed, _ = self._imp()
        c = {"code": "CUPE", "type": "fiat", "name": "Peso Cubano Efectivo"}
        assert allowed(c) == ["cash"]

    def test_generic_fiat_returns_both(self):
        allowed, _ = self._imp()
        c = {"code": "CUP", "type": "fiat", "name": "Peso Cubano"}
        assert allowed(c) == ["transfer", "cash"]

    def test_usd_zelle_detected_as_transfer(self):
        allowed, _ = self._imp()
        # USD seed name is "US Dollar (Zelle)" — should be transfer-only
        c = {"code": "USD", "type": "fiat", "name": "US Dollar (Zelle)"}
        assert allowed(c) == ["transfer"]

    def test_brl_pix_detected_as_transfer(self):
        allowed, _ = self._imp()
        c = {"code": "BRLP", "type": "fiat", "name": "Real Brasileño Pix"}
        assert allowed(c) == ["transfer"]

    def test_accumulate_always_allowed(self):
        _, is_allowed = self._imp()
        for c in [
            {"code": "CUPT", "type": "fiat", "name": "Peso Cubano Transferencia"},
            {"code": "USDT", "type": "crypto", "name": "Tether"},
            None,
        ]:
            assert is_allowed(c, "accumulate") is True


# ---------------- INTEGRATION: API endpoint ----------------

@pytest.fixture(scope="module")
def db():
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture(scope="module")
def setup_subtyped_currencies(db):
    """Seed a transferencia-only currency CUPT and a cash-only CUPE in test scope."""
    db.currencies.update_one({"code": "CUPT"}, {"$set": {
        "id": "test_cur_cupt",
        "code": "CUPT", "name": "Peso Cubano Transferencia",
        "type": "fiat", "symbol": "₱", "country": "Cuba",
        "is_active": True, "payment_account": "",
    }}, upsert=True)
    db.currencies.update_one({"code": "CUPE"}, {"$set": {
        "id": "test_cur_cupe",
        "code": "CUPE", "name": "Peso Cubano Efectivo",
        "type": "fiat", "symbol": "₱", "country": "Cuba",
        "is_active": True, "payment_account": "",
    }}, upsert=True)
    # Ensure rates exist for both
    for to_code in ("CUPT", "CUPE"):
        db.rates.update_one({"from_code": "USDT", "to_code": to_code}, {"$set": {
            "id": f"test_rate_usdt_{to_code.lower()}",
            "from_code": "USDT", "to_code": to_code,
            "rate_normal": 380, "rate_vip": 395, "real_rate": 410,
        }}, upsert=True)
    yield
    # Cleanup — keep monedas (they may be referenced by created orders) but
    # remove the test rates and any test orders.
    db.rates.delete_many({"id": {"$in": ["test_rate_usdt_cupt", "test_rate_usdt_cupe"]}})


def _details(tag: str) -> str:
    return f"TEST_iter43_{tag}_{uuid.uuid4().hex[:6]}"


class TestSubTypedCurrencyValidation:
    def test_cash_to_transferencia_only_rejected(self, setup_subtyped_currencies):
        r = requests.post(
            f"{BASE_URL}/api/orders",
            headers=_h(NORMAL_TOKEN),
            json={
                "from_code": "USDT", "to_code": "CUPT", "amount_from": 100.0,
                "delivery_method": "cash",
                "delivery_details": _details("cash_to_cupt"),
                "sender_name": "Test Holder",
            },
        )
        assert r.status_code == 400, r.text
        # Error message should hint at transferencia/transfer
        assert "transfer" in r.text.lower()

    def test_transfer_to_transferencia_only_accepted(self, setup_subtyped_currencies):
        r = requests.post(
            f"{BASE_URL}/api/orders",
            headers=_h(NORMAL_TOKEN),
            json={
                "from_code": "USDT", "to_code": "CUPT", "amount_from": 100.0,
                "delivery_method": "transfer",
                "delivery_details": _details("transfer_to_cupt"),
                "sender_name": "Test Holder",
            },
        )
        assert r.status_code == 200, r.text

    def test_transfer_to_efectivo_only_rejected(self, setup_subtyped_currencies):
        r = requests.post(
            f"{BASE_URL}/api/orders",
            headers=_h(NORMAL_TOKEN),
            json={
                "from_code": "USDT", "to_code": "CUPE", "amount_from": 100.0,
                "delivery_method": "transfer",
                "delivery_details": _details("transfer_to_cupe"),
                "sender_name": "Test Holder",
            },
        )
        assert r.status_code == 400, r.text
        # Error message should hint at cash/efectivo
        assert "cash" in r.text.lower() or "efectivo" in r.text.lower()

    def test_cash_to_efectivo_only_accepted(self, setup_subtyped_currencies):
        r = requests.post(
            f"{BASE_URL}/api/orders",
            headers=_h(NORMAL_TOKEN),
            json={
                "from_code": "USDT", "to_code": "CUPE", "amount_from": 100.0,
                "delivery_method": "cash",
                "delivery_details": _details("cash_to_cupe"),
                "sender_name": "Test Holder",
            },
        )
        assert r.status_code == 200, r.text
