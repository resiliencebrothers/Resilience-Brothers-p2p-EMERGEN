"""iter44: admin can override `delivery_methods` per currency via PUT/POST,
and the `/api/currencies/{code}/delivery-methods` endpoint reflects the
override (it wins over the name heuristic)."""
import os
import uuid

import pytest
import requests
from pymongo import MongoClient

from conftest import BASE_URL, ADMIN_TOKEN


MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]


def _h(token=None):
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


@pytest.fixture
def cleanup_test_currencies():
    """Yield, then nuke any currency with code starting with TST_DM."""
    yield
    db = MongoClient(MONGO_URL)[DB_NAME]
    db.currencies.delete_many({"code": {"$regex": "^TST_DM"}})


def _make_currency_payload(code: str, name: str, **extra):
    return {
        "code": code, "name": name, "type": "fiat",
        "symbol": "$", "country": "Test", "is_active": True,
        "payment_account": "", **extra,
    }


class TestDeliveryMethodsAdminOverride:
    def test_create_currency_with_explicit_delivery_methods(
        self, cleanup_test_currencies
    ):
        code = f"TST_DM_{uuid.uuid4().hex[:5].upper()}"
        # Name has no heuristic hints — without override, heuristic returns both.
        payload = _make_currency_payload(
            code=code, name="Generic Test Coin",
            delivery_methods=["cash"],
        )
        r = requests.post(f"{BASE_URL}/api/admin/currencies",
                          headers=_h(ADMIN_TOKEN), json=payload)
        assert r.status_code == 200, r.text
        assert r.json()["delivery_methods"] == ["cash"]
        # Endpoint reflects override
        e = requests.get(f"{BASE_URL}/api/currencies/{code}/delivery-methods")
        assert e.status_code == 200
        assert e.json()["allowed"] == ["cash"]

    def test_update_currency_to_add_delivery_methods_override(
        self, cleanup_test_currencies
    ):
        code = f"TST_DM_{uuid.uuid4().hex[:5].upper()}"
        # First create without override
        payload = _make_currency_payload(code=code, name="Generic Test")
        r = requests.post(f"{BASE_URL}/api/admin/currencies",
                          headers=_h(ADMIN_TOKEN), json=payload)
        assert r.status_code == 200
        cid = r.json()["id"]
        # Heuristic returns both since name has no hints
        e1 = requests.get(f"{BASE_URL}/api/currencies/{code}/delivery-methods")
        assert set(e1.json()["allowed"]) == {"transfer", "cash"}
        # Update with override = only transfer
        upd = _make_currency_payload(
            code=code, name="Generic Test", delivery_methods=["transfer"],
        )
        r2 = requests.put(f"{BASE_URL}/api/admin/currencies/{cid}",
                          headers=_h(ADMIN_TOKEN), json=upd)
        assert r2.status_code == 200, r2.text
        e2 = requests.get(f"{BASE_URL}/api/currencies/{code}/delivery-methods")
        assert e2.json()["allowed"] == ["transfer"]

    def test_clearing_override_falls_back_to_heuristic(
        self, cleanup_test_currencies
    ):
        # Name has "transferencia" hint → heuristic alone says ["transfer"]
        code = f"TST_DM_{uuid.uuid4().hex[:5].upper()}"
        create = _make_currency_payload(
            code=code, name="X Transferencia Bancaria",
            delivery_methods=["cash"],  # override says cash
        )
        r = requests.post(f"{BASE_URL}/api/admin/currencies",
                          headers=_h(ADMIN_TOKEN), json=create)
        assert r.status_code == 200, r.text
        cid = r.json()["id"]
        # Override wins
        assert requests.get(
            f"{BASE_URL}/api/currencies/{code}/delivery-methods"
        ).json()["allowed"] == ["cash"]
        # Now clear override (None) — heuristic should kick in
        upd = _make_currency_payload(
            code=code, name="X Transferencia Bancaria", delivery_methods=None,
        )
        r2 = requests.put(f"{BASE_URL}/api/admin/currencies/{cid}",
                          headers=_h(ADMIN_TOKEN), json=upd)
        assert r2.status_code == 200, r2.text
        e2 = requests.get(f"{BASE_URL}/api/currencies/{code}/delivery-methods")
        assert e2.json()["allowed"] == ["transfer"]

    def test_invalid_delivery_method_value_returns_422(
        self, cleanup_test_currencies
    ):
        # Literal validation on the model rejects unknown values
        code = f"TST_DM_{uuid.uuid4().hex[:5].upper()}"
        bad = _make_currency_payload(
            code=code, name="Bad Test",
            delivery_methods=["fly_drone"],  # not in Literal
        )
        r = requests.post(f"{BASE_URL}/api/admin/currencies",
                          headers=_h(ADMIN_TOKEN), json=bad)
        assert r.status_code == 422, r.text

    def test_empty_delivery_methods_list_treated_as_no_override(
        self, cleanup_test_currencies
    ):
        code = f"TST_DM_{uuid.uuid4().hex[:5].upper()}"
        payload = _make_currency_payload(
            code=code, name="Generic Test Empty",
            delivery_methods=[],
        )
        r = requests.post(f"{BASE_URL}/api/admin/currencies",
                          headers=_h(ADMIN_TOKEN), json=payload)
        assert r.status_code == 200, r.text
        # Empty list → heuristic fallback (both methods for generic fiat)
        e = requests.get(f"{BASE_URL}/api/currencies/{code}/delivery-methods")
        assert set(e.json()["allowed"]) == {"transfer", "cash"}
