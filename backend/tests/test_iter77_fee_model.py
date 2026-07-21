"""iter77 — Rework converter fee model.

Fee is now a SEPARATE additional debit from the client's USDT balance
(never deducted from destination). Destination receives the FULL equivalent.

Scenarios covered (per iter77 review request):

1. USDT source with enough balance: full amount_to = amount * rate, USDT
   debited by amount + 0.01.
2. USDT source insufficient (seed exactly 100 USDT, try convert 100 → CUP):
   MUST 400 with Spanish message mentioning "necesitas al menos 100.01 USDT
   (100.00 para convertir + 0.01 de comisión)".
3. Non-USDT source WITH 0.01 USDT for fee: convert 10000 CUP → USDT.
   amount_to = 10000 * rate (no subtraction). USDT balance debited 0.01.
4. Non-USDT source WITHOUT USDT for fee: convert 10000 CUP → USDT with
   USDT balance = 0 → 400 with Spanish message
   "Necesitas al menos 0.01 USDT en tu saldo para pagar la comisión...".
5. Non-USDT → non-USDT (EUR → CUP): amount_to = full, USDT debited by 0.01.
6. Response shape has {ok, from_code, to_code, amount_from, amount_to,
   usdt_fee, rate} — no `amount_to_gross` or `fee_in_to_code`.
"""
import os
import pytest
import requests
from pymongo import MongoClient

from conftest import BASE_URL, VIP_TOKEN

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

VIP_UID = "user_test_vip01"


# ---------- helpers ----------
def _db():
    return MongoClient(MONGO_URL)[DB_NAME]


def _reset_balances(**bals):
    """Reset the VIP test user balances to the given dict. Keys are currency codes.
    Un-listed keys are removed so the tests are hermetic."""
    db = _db()
    db.users.update_one(
        {"user_id": VIP_UID},
        {"$set": {"vip_balances": {k: float(v) for k, v in bals.items()}}},
    )


def _get_balance(code):
    db = _db()
    u = db.users.find_one({"user_id": VIP_UID}, {"_id": 0, "vip_balances": 1})
    return float((u or {}).get("vip_balances", {}).get(code, 0))


def _get_rate_vip(from_code, to_code):
    """Read the current VIP rate. Falls back to inverse if not stored directly.
    Mirrors the backend's own lookup so the tests are self-adaptive to whatever
    rates the seed populated."""
    db = _db()
    r = db.rates.find_one({"from_code": from_code, "to_code": to_code})
    if r:
        return float(r.get("rate_vip") or r.get("rate_normal") or 0)
    inv = db.rates.find_one({"from_code": to_code, "to_code": from_code})
    if inv:
        v = float(inv.get("rate_vip") or inv.get("rate_normal") or 0)
        if v > 0:
            return 1.0 / v
    return 0.0


@pytest.fixture
def clean_vip():
    """Snapshot and restore the VIP balances so tests don't leak state."""
    db = _db()
    original = db.users.find_one({"user_id": VIP_UID}, {"_id": 0, "vip_balances": 1})
    yield
    orig_bal = (original or {}).get("vip_balances", {})
    db.users.update_one(
        {"user_id": VIP_UID},
        {"$set": {"vip_balances": orig_bal}},
    )


# ---------- Scenario 1 — USDT source with enough for fee ----------

def test_usdt_source_full_amount_to_and_debits_amount_plus_fee(clean_vip):
    _reset_balances(USDT=100.01)
    r = requests.post(
        f"{BASE_URL}/api/vip/convert",
        cookies={"session_token": VIP_TOKEN},
        json={"from_code": "USDT", "to_code": "CUP", "amount_from": 100.0},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["from_code"] == "USDT"
    assert body["to_code"] == "CUP"
    assert body["amount_from"] == 100.0
    assert body["usdt_fee"] == 0.01
    # Full equivalent, no fee subtraction from destination
    expected = round(100.0 * body["rate"], 4)
    assert body["amount_to"] == expected

    # Response shape — no legacy fields
    assert "fee_in_to_code" not in body
    assert "amount_to_gross" not in body
    # Required response keys per iter77 spec
    for k in ("ok", "from_code", "to_code", "amount_from", "amount_to", "usdt_fee", "rate"):
        assert k in body, f"missing key {k} in response {body}"

    # Balance impact: USDT went from 100.01 -> ~0; destination CUP got the full amount
    assert round(_get_balance("USDT"), 4) == 0.0
    assert round(_get_balance("CUP"), 4) == expected


# ---------- Scenario 2 — USDT source insufficient for fee ----------

def test_usdt_source_exactly_amount_no_room_for_fee_rejected(clean_vip):
    _reset_balances(USDT=100.0)  # exactly the conversion amount, no fee room
    r = requests.post(
        f"{BASE_URL}/api/vip/convert",
        cookies={"session_token": VIP_TOKEN},
        json={"from_code": "USDT", "to_code": "CUP", "amount_from": 100.0},
    )
    assert r.status_code == 400, r.text
    detail = r.json().get("detail", "").lower()
    # Spanish error must mention the required 100.01 USDT (amount + fee)
    assert "insuficiente" in detail
    assert "100.01" in detail
    assert "comisi" in detail  # comisión / commission-in-Spanish
    # Balance untouched
    assert _get_balance("USDT") == 100.0
    assert _get_balance("CUP") == 0.0


# ---------- Scenario 3 — Non-USDT source WITH USDT for fee ----------

def test_non_usdt_source_full_amount_to_and_usdt_fee_debit(clean_vip):
    _reset_balances(CUP=50000.0, USDT=0.01)
    r = requests.post(
        f"{BASE_URL}/api/vip/convert",
        cookies={"session_token": VIP_TOKEN},
        json={"from_code": "CUP", "to_code": "USDT", "amount_from": 10000.0},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["usdt_fee"] == 0.01
    expected_amount_to = round(10000.0 * body["rate"], 4)
    assert body["amount_to"] == expected_amount_to

    # USDT ledger: started 0.01 (seed) - 0.01 (fee) + amount_to (credit) = amount_to
    assert round(_get_balance("USDT"), 4) == round(expected_amount_to, 4)
    assert _get_balance("CUP") == 50000.0 - 10000.0


# ---------- Scenario 4 — Non-USDT source WITHOUT USDT for fee ----------

def test_non_usdt_source_zero_usdt_rejected_with_spanish_msg(clean_vip):
    _reset_balances(CUP=50000.0, USDT=0.0)
    r = requests.post(
        f"{BASE_URL}/api/vip/convert",
        cookies={"session_token": VIP_TOKEN},
        json={"from_code": "CUP", "to_code": "USDT", "amount_from": 10000.0},
    )
    assert r.status_code == 400, r.text
    detail = r.json().get("detail", "").lower()
    # Expected phrasing from iter77 spec
    assert "0.01 usdt" in detail
    assert "comisi" in detail  # comisión
    # No balance mutation
    assert _get_balance("CUP") == 50000.0
    assert _get_balance("USDT") == 0.0


# ---------- Scenario 5 — Non-USDT → Non-USDT (EUR → CUP) ----------

@pytest.fixture
def eur_cup_rate():
    """Seed EUR↔CUP + EUR→USDT rates if the env doesn't have them, then clean up.
    Needed because iter77 non-USDT → non-USDT conversions still need a USDT
    valuation route for the min-source guard."""
    db = _db()
    inserted = []
    for r in [
        {"from_code": "EUR", "to_code": "CUP", "rate_vip": 430.0, "rate_normal": 415.0},
        {"from_code": "EUR", "to_code": "USDT", "rate_vip": 1.08, "rate_normal": 1.05},
    ]:
        if not db.rates.find_one({"from_code": r["from_code"], "to_code": r["to_code"]}):
            db.rates.insert_one(dict(r))
            inserted.append((r["from_code"], r["to_code"]))
    yield
    for f, t in inserted:
        db.rates.delete_one({"from_code": f, "to_code": t})


def test_eur_to_cup_full_amount_and_usdt_fee_only(clean_vip, eur_cup_rate):
    _reset_balances(EUR=100.0, USDT=0.01)
    r = requests.post(
        f"{BASE_URL}/api/vip/convert",
        cookies={"session_token": VIP_TOKEN},
        json={"from_code": "EUR", "to_code": "CUP", "amount_from": 50.0},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["usdt_fee"] == 0.01
    expected_amount_to = round(50.0 * body["rate"], 4)
    assert body["amount_to"] == expected_amount_to

    # USDT balance debited by exactly 0.01 (0.01 → 0.00)
    assert round(_get_balance("USDT"), 6) == 0.0
    # Source debited
    assert round(_get_balance("EUR"), 6) == 50.0
    # Destination credited with full amount
    assert round(_get_balance("CUP"), 4) == round(expected_amount_to, 4)


# ---------- Scenario 6 — Response shape sanity ----------

def test_response_shape_removes_legacy_fields(clean_vip):
    _reset_balances(USDT=5.01)
    r = requests.post(
        f"{BASE_URL}/api/vip/convert",
        cookies={"session_token": VIP_TOKEN},
        json={"from_code": "USDT", "to_code": "CUP", "amount_from": 5.0},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body.keys()) == {"ok", "from_code", "to_code", "amount_from", "amount_to", "usdt_fee", "rate"}
