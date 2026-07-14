"""iter55.27 — Fiat-cash floor credits residue to balance + USDT convert fee.

Business rules changed by the owner on 11 Feb 2026:
1. Cash delivery to ANY fiat (not just USD) floors the delivered amount and
   the sub-unit residue is credited to the client's on-platform balance in
   the SAME currency (nothing is lost — accumulates across trades).
2. Any conversion to USDT via /vip/convert charges a flat 0.01 USDT service
   fee and requires the NET result to be >= 1.00 USDT (blocks dust conversions).
"""
import os
import uuid
from datetime import datetime, timezone

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL as API_ROOT, VIP_TOKEN

API = f"{API_ROOT}/api"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _iso():
    return datetime.now(timezone.utc).isoformat()


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _upsert_currency(code, ctype, delivery_methods):
    _db().currencies.update_one(
        {"code": code},
        {"$set": {"code": code, "name": f"Test {code}", "type": ctype,
                  "is_active": True, "delivery_methods": delivery_methods,
                  "updated_at": _iso()},
         "$setOnInsert": {"id": uuid.uuid4().hex, "created_at": _iso()}},
        upsert=True,
    )


def _upsert_rate(from_code, to_code, rate):
    _db().rates.update_one(
        {"from_code": from_code, "to_code": to_code},
        {"$set": {"from_code": from_code, "to_code": to_code,
                  "rate_normal": rate, "rate_vip": rate,
                  "updated_at": _iso()},
         "$setOnInsert": {"id": uuid.uuid4().hex}},
        upsert=True,
    )


def _get_balance(code):
    doc = _db().users.find_one({"user_id": "user_test_vip01"}, {"_id": 0, "vip_balances": 1}) or {}
    return float((doc.get("vip_balances") or {}).get(code, 0))


def _clear_balance(code):
    _db().users.update_one(
        {"user_id": "user_test_vip01"},
        {"$unset": {f"vip_balances.{code}": ""}},
    )


def _cleanup():
    _db().orders.delete_many({"from_code": {"$regex": "^ZELLE27"}})
    _db().rates.delete_many({"from_code": {"$regex": "^ZELLE27"}})
    _db().currencies.delete_many({"code": {"$regex": "^ZELLE27|^EURCASH27"}})
    # iter55.36i — also purge stray rates between the CUP/EUR/USD/USDT test
    # aliases; `convert_to_usdt` prefers `USDT→code` inverse quotes so any
    # leftover rate from a sibling test would mis-value the source.
    _test_codes = ["CUPCASH27", "EURCASH27", "USDCASH27"]
    _db().rates.delete_many({"from_code": {"$in": _test_codes}})
    _db().rates.delete_many({"to_code": {"$in": _test_codes}})
    for c in _test_codes:
        _clear_balance(c)


# ============================================================
# Part 1 — residue credit on fiat-cash orders
# ============================================================

def test_pure_helper_flags_any_fiat_cash():
    """iter55.27 broadened the rule from USD-only to any fiat+cash."""
    from services.orders_helpers import _cash_no_cents

    # Any fiat + cash: True
    assert _cash_no_cents("USD",  "fiat", "cash") is True
    assert _cash_no_cents("CUP",  "fiat", "cash") is True
    assert _cash_no_cents("EUR",  "fiat", "cash") is True
    assert _cash_no_cents("MLC",  "FIAT", "cash") is True  # case-insensitive on type
    # Crypto to cash: False (never — crypto doesn't have physical cash)
    assert _cash_no_cents("USDT", "crypto", "cash") is False
    # Fiat + non-cash: False (transfers/crypto payouts preserve precision)
    assert _cash_no_cents("USD",  "fiat", "transfer") is False
    assert _cash_no_cents("CUP",  "fiat", "crypto")   is False
    # Missing type: False (defensive)
    assert _cash_no_cents("USD",  "",     "cash") is False


def test_cash_cup_order_credits_residue_to_balance():
    """The requested scenario: pay 325 ZELLE @ rate 100.5 → gross 32662.5 CUP.
    Floor to 32662 CUP delivered, credit 0.5 CUP to client's balance."""
    _cleanup()
    _upsert_currency("ZELLE27", "fiat", ["transfer"])
    _upsert_currency("CUP", "fiat", ["cash", "transfer"])  # CUP allows cash
    _upsert_rate("ZELLE27", "CUP", 100.5)

    balance_before = _get_balance("CUP")
    r = requests.post(
        f"{API}/orders", headers=_hdr(VIP_TOKEN),
        json={
            "from_code": "ZELLE27", "to_code": "CUP",
            "amount_from": 325,
            "delivery_method": "cash",
            "delivery_details": "Nombre: X\nCelular: +5300\nDirección: y",
            "sender_name": "Test Sender", "proof_image": "",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["amount_to"] == 32662.0, f"Expected 32662.0, got {body['amount_to']}"

    balance_after = _get_balance("CUP")
    delta = balance_after - balance_before
    # 325 * 100.5 = 32662.5 → residue 0.5
    assert abs(delta - 0.5) < 0.001, f"Expected +0.5 CUP residue, got {delta}"

    _cleanup()


def test_transfer_order_does_not_credit_residue():
    """Regression guard — the residue rule must ONLY apply to cash+fiat,
    never to transfer (which preserves precision)."""
    _cleanup()
    _upsert_currency("ZELLE27", "fiat", ["transfer"])
    _upsert_rate("ZELLE27", "USD", 0.95)
    _db().currencies.update_one({"code": "USD"}, {"$addToSet": {"delivery_methods": "transfer"}})

    balance_before = _get_balance("USD")
    r = requests.post(
        f"{API}/orders", headers=_hdr(VIP_TOKEN),
        json={
            "from_code": "ZELLE27", "to_code": "USD",
            "amount_from": 325,
            "delivery_method": "transfer",
            "delivery_details": "Bank X — Account 123456",
            "sender_name": "Test Sender", "proof_image": "",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["amount_to"] == 308.75  # precision preserved

    balance_after = _get_balance("USD")
    assert balance_after == balance_before, "Transfer must NOT credit residue"

    _cleanup()


# ============================================================
# Part 2 — 0.01 USDT universal convert fee + 1.00 USDT minimum source
# (iter55.36i — was 0.01 USDT + net-post-fee-≥-1-USDT under iter55.27)
# ============================================================

def test_convert_to_usdt_charges_flat_fee():
    """Convert 5 CUPCASH27 → USDT at rate 0.5. Gross = 2.5 USDT, fee 0.01 USDT
    (universal). Net = 2.49 USDT. Source is worth 2.5 USDT ≥ 1 USDT min → OK."""
    _cleanup()
    _upsert_currency("CUPCASH27", "fiat", ["cash"])
    _upsert_rate("CUPCASH27", "USDT", 0.5)
    _db().users.update_one({"user_id": "user_test_vip01"},
                             {"$set": {"vip_balances.CUPCASH27": 5.0}})
    usdt_before = _get_balance("USDT")

    r = requests.post(
        f"{API}/vip/convert", headers=_hdr(VIP_TOKEN),
        json={"from_code": "CUPCASH27", "to_code": "USDT", "amount_from": 5.0},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["amount_to_gross"] == 2.5
    assert body["usdt_fee"] == 0.01
    assert body["fee_in_to_code"] == 0.01  # dest = USDT → same as usdt_fee
    assert body["amount_to"] == 2.49

    usdt_after = _get_balance("USDT")
    assert abs((usdt_after - usdt_before) - 2.49) < 0.001

    _cleanup()


def test_convert_blocks_below_1_usdt_source_equivalent():
    """The source amount must be worth ≥ 1.00 USDT. Prevents dust conversions
    regardless of destination currency."""
    _cleanup()
    _upsert_currency("CUPCASH27", "fiat", ["cash"])
    _upsert_rate("CUPCASH27", "USDT", 0.5)
    _db().users.update_one({"user_id": "user_test_vip01"},
                             {"$set": {"vip_balances.CUPCASH27": 5.0}})

    # 1 CUPCASH27 * 0.5 USDT/CUPCASH27 = 0.50 USDT source-equivalent → BLOCKED
    r = requests.post(
        f"{API}/vip/convert", headers=_hdr(VIP_TOKEN),
        json={"from_code": "CUPCASH27", "to_code": "USDT", "amount_from": 1.0},
    )
    assert r.status_code == 400
    assert "equivalente" in r.text.lower() or "USDT" in r.text

    _cleanup()


def test_convert_from_usdt_to_other_charges_fee():
    """iter55.36i — the 0.01 USDT fee now applies to EVERY conversion,
    including USDT → fiat. Fee is expressed in the destination currency
    using the USDT→dest rate."""
    _cleanup()
    _upsert_currency("CUPCASH27", "fiat", ["cash"])
    _upsert_rate("USDT", "CUPCASH27", 100.0)
    _db().users.update_one({"user_id": "user_test_vip01"},
                             {"$set": {"vip_balances.USDT": 10.0}})

    r = requests.post(
        f"{API}/vip/convert", headers=_hdr(VIP_TOKEN),
        json={"from_code": "USDT", "to_code": "CUPCASH27", "amount_from": 2.0},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # Fee = 0.01 USDT · rate USDT→CUPCASH27 (100) = 1 CUPCASH27
    assert body["usdt_fee"] == 0.01
    assert body["fee_in_to_code"] == 1.0
    assert body["amount_to_gross"] == 200.0
    assert body["amount_to"] == 199.0

    _clear_balance("USDT")
    _cleanup()


def test_convert_non_usdt_pair_charges_fee_in_dest_currency():
    """iter55.36i — third case: neither side is USDT (e.g. EUR → CUP). Fee
    is still 0.01 USDT, translated into the destination currency via the
    USDT→dest rate."""
    _cleanup()
    _upsert_currency("EURCASH27", "fiat", ["cash"])
    _upsert_currency("CUPCASH27", "fiat", ["cash"])
    _upsert_rate("EURCASH27", "CUPCASH27", 400.0)  # 1 EUR = 400 CUP
    _upsert_rate("USDT", "CUPCASH27", 100.0)       # 1 USDT = 100 CUP
    _upsert_rate("EURCASH27", "USDT", 1.05)        # 1 EUR = 1.05 USDT (source valuation)
    _db().users.update_one({"user_id": "user_test_vip01"},
                             {"$set": {"vip_balances.EURCASH27": 5.0}})

    # Convert 2 EUR → CUP at 400 CUP/EUR → 800 CUP gross.
    # Source-equivalent USDT = 2 * 1.05 = 2.10 USDT (≥ 1 min → OK).
    # Fee 0.01 USDT in CUP = 0.01 * 100 = 1 CUP.
    # Net = 800 - 1 = 799 CUP.
    r = requests.post(
        f"{API}/vip/convert", headers=_hdr(VIP_TOKEN),
        json={"from_code": "EURCASH27", "to_code": "CUPCASH27", "amount_from": 2.0},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["usdt_fee"] == 0.01
    assert body["fee_in_to_code"] == 1.0
    assert body["amount_to_gross"] == 800.0
    assert body["amount_to"] == 799.0

    _cleanup()
    _db().rates.delete_many({"from_code": {"$in": ["EURCASH27"]}})
    _db().currencies.delete_many({"code": "EURCASH27"})


def test_convert_fee_and_amount_appear_in_audit():
    """The audit trail must record the fee (in USDT for revenue aggregation)
    AND the destination-currency equivalent for operator transparency."""
    _cleanup()
    _upsert_currency("CUPCASH27", "fiat", ["cash"])
    _upsert_rate("CUPCASH27", "USDT", 1.0)
    _db().users.update_one({"user_id": "user_test_vip01"},
                             {"$set": {"vip_balances.CUPCASH27": 5.0}})
    _db().audit_log.delete_many({"actor_id": "user_test_vip01", "action": "vip.convert"})

    r = requests.post(
        f"{API}/vip/convert", headers=_hdr(VIP_TOKEN),
        json={"from_code": "CUPCASH27", "to_code": "USDT", "amount_from": 3.0},
    )
    assert r.status_code == 200, r.text

    e = _db().audit_log.find_one(
        {"actor_id": "user_test_vip01", "action": "vip.convert"},
        sort=[("created_at", -1)],
    )
    assert e is not None
    assert e["details"]["usdt_fee"] == 0.01
    assert e["details"]["fee_in_to_code"] == 0.01
    assert e["details"]["amount_from_usdt"] == 3.0
    assert e["details"]["amount_to_gross"] == 3.0
    assert e["details"]["amount_to"] == 2.99

    _cleanup()
