"""iter78 — Conversions surface in /me/transactions.

Scenarios covered:

1. After a `POST /vip/convert` call the audit_log carries the
   `vip.convert` event AND `/api/me/transactions?direction=conversion`
   surfaces it as a distinct row.
2. The row shape carries `direction: "conversion"`, `ref_type: "conversion"`,
   `from_code`, `to_code`, `amount_from`, `amount_to`, `usdt_fee`,
   `rate`, and a `conversion_subtype` = "normal" or "small_balance"
   based on the source USDT-equivalent threshold (< 5.0 USDT → small).
3. Response totals include `conversion_count` and conversions DO NOT
   pollute the per-currency in/out totals.
4. `direction=in` and `direction=out` filters DO NOT include conversions.
5. `direction=conversion` returns ONLY conversion rows.
6. `direction` validator accepts the new "conversion" value; invalid
   directions still 400.
"""
import os
import pytest
import requests
from pymongo import MongoClient

from conftest import BASE_URL, VIP_TOKEN

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

VIP_UID = "user_test_vip01"


def _db():
    return MongoClient(MONGO_URL)[DB_NAME]


def _reset_balances(**bals):
    _db().users.update_one(
        {"user_id": VIP_UID},
        {"$set": {"vip_balances": {k: float(v) for k, v in bals.items()}}},
    )


@pytest.fixture
def clean_conversions():
    """Wipe any leftover vip.convert audit rows for this user so the row
    count is deterministic. Snapshot + restore balances."""
    db = _db()
    original = db.users.find_one({"user_id": VIP_UID}, {"_id": 0, "vip_balances": 1})
    db.audit_log.delete_many({"actor_id": VIP_UID, "action": "vip.convert"})
    yield
    db.users.update_one(
        {"user_id": VIP_UID},
        {"$set": {"vip_balances": (original or {}).get("vip_balances", {})}},
    )
    db.audit_log.delete_many({"actor_id": VIP_UID, "action": "vip.convert"})


def _headers():
    return {"Authorization": f"Bearer {VIP_TOKEN}"}


def _do_convert(from_code, to_code, amount_from):
    r = requests.post(
        f"{BASE_URL}/api/vip/convert",
        headers=_headers(),
        json={"from_code": from_code, "to_code": to_code, "amount_from": amount_from},
        timeout=30,
    )
    assert r.status_code == 200, f"convert failed: {r.status_code} {r.text}"
    return r.json()


def test_conversion_appears_in_me_transactions(clean_conversions):
    # Seed 100 USDT and convert 10 → CUP (a well-known configured rate).
    _reset_balances(USDT=100.0)
    _do_convert("USDT", "CUP", 10.0)

    r = requests.get(
        f"{BASE_URL}/api/me/transactions",
        headers=_headers(),
        timeout=30,
    )
    assert r.status_code == 200, r.text
    payload = r.json()
    convs = [it for it in payload["items"] if it["direction"] == "conversion"]
    assert len(convs) == 1
    row = convs[0]
    assert row["ref_type"] == "conversion"
    assert row["from_code"] == "USDT"
    assert row["to_code"] == "CUP"
    assert row["amount_from"] == pytest.approx(10.0, rel=1e-6)
    assert row["amount_to"] > 0
    assert row["usdt_fee"] == pytest.approx(0.01, rel=1e-6)
    assert row["rate"] > 0
    # 10 USDT source is well above the 5 USDT dust threshold → normal.
    assert row["conversion_subtype"] == "normal"

    # Totals: conversions never affect the in/out per-currency totals.
    totals = payload["totals"]
    assert totals.get("conversion_count") == 1
    # No entry should be a conversion in the by_currency map (it aggregates
    # in/out only).
    for _, slot in totals.get("by_currency", {}).items():
        assert "conversion" not in slot


def test_small_balance_subtype(clean_conversions):
    # 2 USDT source is BELOW the 5 USDT dust threshold → small_balance.
    _reset_balances(USDT=100.0)
    _do_convert("USDT", "CUP", 2.0)

    r = requests.get(
        f"{BASE_URL}/api/me/transactions?direction=conversion",
        headers=_headers(),
        timeout=30,
    )
    assert r.status_code == 200, r.text
    convs = r.json()["items"]
    assert len(convs) == 1
    assert convs[0]["conversion_subtype"] == "small_balance"


def test_direction_filters_exclude_conversions(clean_conversions):
    _reset_balances(USDT=100.0)
    _do_convert("USDT", "CUP", 3.0)

    # in-only: no conversions
    r_in = requests.get(
        f"{BASE_URL}/api/me/transactions?direction=in",
        headers=_headers(),
        timeout=30,
    )
    assert r_in.status_code == 200, r_in.text
    for it in r_in.json()["items"]:
        assert it["direction"] == "in"

    # out-only: no conversions
    r_out = requests.get(
        f"{BASE_URL}/api/me/transactions?direction=out",
        headers=_headers(),
        timeout=30,
    )
    assert r_out.status_code == 200, r_out.text
    for it in r_out.json()["items"]:
        assert it["direction"] == "out"

    # conversion-only: ONLY conversions
    r_conv = requests.get(
        f"{BASE_URL}/api/me/transactions?direction=conversion",
        headers=_headers(),
        timeout=30,
    )
    assert r_conv.status_code == 200, r_conv.text
    items = r_conv.json()["items"]
    assert len(items) == 1
    assert all(it["direction"] == "conversion" for it in items)


def test_invalid_direction_still_rejected():
    r = requests.get(
        f"{BASE_URL}/api/me/transactions?direction=foobar",
        headers=_headers(),
        timeout=30,
    )
    assert r.status_code == 400
