"""iter55.3 — Defensive normalisation of currency codes.

Reproduces the operator's Feb-2026 report where /api/admin/company-funds/adjustments
rejected `CUP` with "no disponible en el catálogo" because the stored catalog
row had a trailing space (`"CUP "`). The lookup is now lenient: it strips
whitespace on both sides and falls back to a case-insensitive regex.
"""
import os
import uuid
import requests

from tests.conftest import BASE_URL, ADMIN_TOKEN, make_admin_totp


def _mongo():
    from pymongo import MongoClient
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _corrupt_cup_code(space_placement: str = "trailing") -> str:
    """Temporarily mutate the CUP row's `code` field to include whitespace.
    Returns the original code so the caller can restore it."""
    db = _mongo()
    row = db.currencies.find_one({"code": "CUP"}, {"_id": 0, "id": 1, "code": 1})
    if not row:
        # Ensure a CUP row exists for the test (idempotent)
        row = {"id": str(uuid.uuid4()), "code": "CUP",
               "name": "Peso Cubano", "type": "fiat", "is_active": True}
        db.currencies.insert_one(row)
    original = row["code"]
    corrupted = {
        "trailing": f"{original} ",
        "leading": f" {original}",
        "lower": original.lower(),
    }[space_placement]
    db.currencies.update_one({"id": row["id"]}, {"$set": {"code": corrupted}})
    return original


def _restore_cup(original: str = "CUP"):
    db = _mongo()
    db.currencies.update_one(
        {"code": {"$regex": r"^\s*cup\s*$", "$options": "i"}},
        {"$set": {"code": original}},
    )


class TestCurrencyCodeLenientLookup:
    def test_adjustment_accepts_cup_when_stored_code_has_trailing_space(self):
        _corrupt_cup_code("trailing")
        try:
            body = {
                "adjustment_type": "inflow",
                "currency": "CUP",
                "amount": 1000,
                "method": "cash",
                "source_name": "Migration test",
                "source_account": "",
                "note": "lenient-lookup",
                "totp_code": make_admin_totp(),
            }
            r = requests.post(
                f"{BASE_URL}/api/admin/company-funds/adjustments",
                json=body,
                headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
                timeout=15,
            )
            assert r.status_code == 200, r.text
            assert r.json()["currency"] == "CUP"
        finally:
            _restore_cup()
            _mongo().company_fund_adjustments.delete_many({"note": "lenient-lookup"})

    def test_adjustment_accepts_lowercase_input(self):
        try:
            body = {
                "adjustment_type": "inflow",
                "currency": "cup",  # user typed lowercase
                "amount": 500,
                "method": "cash",
                "source_name": "Case test",
                "source_account": "",
                "note": "case-insensitive",
                "totp_code": make_admin_totp(),
            }
            r = requests.post(
                f"{BASE_URL}/api/admin/company-funds/adjustments",
                json=body,
                headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
                timeout=15,
            )
            assert r.status_code == 200, r.text
            assert r.json()["currency"] == "CUP"
        finally:
            _mongo().company_fund_adjustments.delete_many({"note": "case-insensitive"})

    def test_currencies_endpoint_returns_normalized_codes(self):
        _corrupt_cup_code("trailing")
        try:
            r = requests.get(f"{BASE_URL}/api/currencies", timeout=10)
            assert r.status_code == 200
            codes = [c["code"] for c in r.json()]
            # No stripped code should have surrounding whitespace even if BD has it
            assert all(c == c.strip() for c in codes), \
                f"Found codes with whitespace: {[c for c in codes if c != c.strip()]}"
            assert "CUP" in codes
        finally:
            _restore_cup()

    def test_delivery_methods_endpoint_survives_corrupted_code(self):
        _corrupt_cup_code("trailing")
        try:
            r = requests.get(
                f"{BASE_URL}/api/currencies/CUP/delivery-methods", timeout=10
            )
            assert r.status_code == 200, r.text
            assert r.json()["code"] == "CUP"
        finally:
            _restore_cup()

    def test_error_message_still_helpful_for_truly_missing_code(self):
        r = requests.post(
            f"{BASE_URL}/api/admin/company-funds/adjustments",
            json={
                "adjustment_type": "inflow",
                "currency": "ZZZ",  # valid length, not in catalog
                "amount": 100,
                "method": "cash",
                "source_name": "xx",
                "source_account": "",
                "note": "missing-code-test",
                "totp_code": make_admin_totp(),
            },
            headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
            timeout=15,
        )
        assert r.status_code == 400, r.text
        detail = r.json().get("detail", "")
        assert "ZZZ" in detail
        assert "Válidas:" in detail
        assert "CUP" in detail  # sanity check: list contains known codes
