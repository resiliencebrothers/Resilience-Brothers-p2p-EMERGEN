"""iter55.29 — Admin-controlled `is_convertible_to` flag on Currency.

Bug reported by owner on 12 Feb 2026: the platform's converter allowed
converting USDT → USD (Zelle), but Resilience only RECEIVES Zelle, it cannot
SEND Zelle out. This let clients accumulate a currency the platform could
never disburse.

Fix: new admin-controlled boolean `is_convertible_to` on Currency (default
True for backward compat). When False, the destination is REJECTED by
`POST /vip/convert` with a Spanish 400. Does NOT affect P2P orders or
withdrawals (per operator decision, those flows use their own delivery_methods
pipeline).
"""
import os
import uuid
from datetime import datetime, timezone

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL as API_ROOT, VIP_TOKEN, ADMIN_TOKEN

API = f"{API_ROOT}/api"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _iso():
    return datetime.now(timezone.utc).isoformat()


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _upsert_currency(code, ctype, *, is_convertible_to=True, delivery_methods=None):
    _db().currencies.update_one(
        {"code": code},
        {"$set": {
            "code": code, "name": f"Test {code}", "type": ctype,
            "is_active": True, "delivery_methods": delivery_methods,
            "is_convertible_to": is_convertible_to,
            "updated_at": _iso(),
        }, "$setOnInsert": {"id": uuid.uuid4().hex, "created_at": _iso()}},
        upsert=True,
    )


def _upsert_rate(from_code, to_code, rate):
    _db().rates.update_one(
        {"from_code": from_code, "to_code": to_code},
        {"$set": {"from_code": from_code, "to_code": to_code,
                  "rate_normal": rate, "rate_vip": rate, "updated_at": _iso()},
         "$setOnInsert": {"id": uuid.uuid4().hex}},
        upsert=True,
    )


def _clear_balance(code):
    _db().users.update_one(
        {"user_id": "user_test_vip01"},
        {"$unset": {f"vip_balances.{code}": ""}},
    )


def _cleanup():
    for code in ("ZELLE29", "USDT29", "CUP29"):
        _db().currencies.delete_many({"code": code})
        _db().rates.delete_many({"$or": [{"from_code": code}, {"to_code": code}]})
        _clear_balance(code)


# ============================================================
# Backend HTTP guard
# ============================================================

def test_convert_to_non_convertible_currency_is_rejected():
    """The bug reproducer — trying to convert USDT29 → ZELLE29 (marked as
    non-convertible) must return 400 with a Spanish message."""
    _cleanup()
    _upsert_currency("USDT29", "crypto", is_convertible_to=True)
    _upsert_currency("ZELLE29", "fiat", is_convertible_to=False,
                     delivery_methods=["transfer"])
    _upsert_rate("USDT29", "ZELLE29", 0.98)
    _db().users.update_one({"user_id": "user_test_vip01"},
                             {"$set": {"vip_balances.USDT29": 100.0}})

    r = requests.post(
        f"{API}/vip/convert", headers=_hdr(VIP_TOKEN),
        json={"from_code": "USDT29", "to_code": "ZELLE29", "amount_from": 10.0},
    )
    assert r.status_code == 400, r.text
    body = r.json()
    detail = body.get("detail", "")
    assert "no puede enviar" in detail.lower() or "destino de conversión" in detail.lower(), detail
    assert "ZELLE29" in detail

    # Balance is untouched — the guard fires BEFORE any DB mutation.
    fresh = _db().users.find_one({"user_id": "user_test_vip01"}, {"_id": 0, "vip_balances": 1})
    assert float(fresh["vip_balances"]["USDT29"]) == 100.0

    _cleanup()


def test_convert_to_convertible_currency_still_works():
    """Backward-compat: currencies with is_convertible_to=True (default) keep
    working exactly like before."""
    _cleanup()
    _upsert_currency("USDT29", "crypto", is_convertible_to=True)
    _upsert_currency("CUP29", "fiat", is_convertible_to=True,
                     delivery_methods=["cash"])
    _upsert_rate("USDT29", "CUP29", 100.0)
    # iter55.36i — universal fee/min needs USDT valuation for both codes.
    _upsert_rate("USDT29", "USDT", 1.0)
    _upsert_rate("USDT", "CUP29", 100.0)
    _db().users.update_one({"user_id": "user_test_vip01"},
                             {"$set": {"vip_balances.USDT29": 10.0,
                                       "vip_balances.USDT": 0.01}})

    r = requests.post(
        f"{API}/vip/convert", headers=_hdr(VIP_TOKEN),
        json={"from_code": "USDT29", "to_code": "CUP29", "amount_from": 2.0},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # iter77 — Destination receives FULL equivalent; fee is separate USDT debit.
    assert body["amount_to"] == 200.0

    _clear_balance("USDT29")
    _clear_balance("CUP29")
    _cleanup()


def test_convert_from_non_convertible_source_still_works():
    """The flag ONLY gates DESTINATION selection. Clients holding a residual
    balance in a non-convertible currency must still be able to convert it
    OUT to something the platform can disburse."""
    _cleanup()
    _upsert_currency("ZELLE29", "fiat", is_convertible_to=False,
                     delivery_methods=["transfer"])
    _upsert_currency("USDT29", "crypto", is_convertible_to=True)
    _upsert_rate("ZELLE29", "USDT29", 0.95)
    # iter55.36i — universal fee/min needs USDT valuation for both codes.
    _upsert_rate("ZELLE29", "USDT", 0.95)
    _upsert_rate("USDT29", "USDT", 1.0)
    _db().users.update_one({"user_id": "user_test_vip01"},
                             {"$set": {"vip_balances.ZELLE29": 50.0,
                                       "vip_balances.USDT": 0.01}})

    r = requests.post(
        f"{API}/vip/convert", headers=_hdr(VIP_TOKEN),
        json={"from_code": "ZELLE29", "to_code": "USDT29", "amount_from": 10.0},
    )
    # iter77 — Full 10 × 0.95 = 9.5 credited; fee 0.01 USDT debited separately.
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["amount_to"] == 9.5

    _clear_balance("USDT29")
    _clear_balance("ZELLE29")
    _cleanup()


def test_backward_compat_missing_flag_treated_as_convertible():
    """Existing rows in production don't have the flag yet. They must default
    to convertible so redeploy is zero-downtime."""
    _cleanup()
    _upsert_currency("USDT29", "crypto", is_convertible_to=True)
    _upsert_currency("CUP29", "fiat", delivery_methods=["cash"])
    # Simulate a pre-iter55.29 row: remove the flag entirely.
    _db().currencies.update_one({"code": "CUP29"}, {"$unset": {"is_convertible_to": ""}})
    _upsert_rate("USDT29", "CUP29", 100.0)
    # iter55.36i — universal fee/min needs USDT valuation for both codes.
    _upsert_rate("USDT29", "USDT", 1.0)
    _upsert_rate("USDT", "CUP29", 100.0)
    _db().users.update_one({"user_id": "user_test_vip01"},
                             {"$set": {"vip_balances.USDT29": 5.0,
                                       "vip_balances.USDT": 0.01}})

    r = requests.post(
        f"{API}/vip/convert", headers=_hdr(VIP_TOKEN),
        json={"from_code": "USDT29", "to_code": "CUP29", "amount_from": 2.0},
    )
    assert r.status_code == 200, r.text  # legacy rows keep working

    _clear_balance("USDT29")
    _clear_balance("CUP29")
    _cleanup()


# ============================================================
# Admin CRUD persists the flag
# ============================================================

def test_admin_can_toggle_convertible_flag():
    """The admin API accepts `is_convertible_to` on create + edit + it survives
    the round trip. This is what the AdminCurrencies UI relies on."""
    _cleanup()
    # Create with flag=False
    r = requests.post(
        f"{API}/admin/currencies", headers=_hdr(ADMIN_TOKEN),
        json={"code": "ZELLE29", "name": "Test Zelle",
              "type": "fiat", "is_active": True, "is_convertible_to": False},
    )
    assert r.status_code == 200, r.text
    created = r.json()
    assert created["is_convertible_to"] is False

    # Read back from list
    listing = requests.get(f"{API}/currencies").json()
    stored = next(c for c in listing if c["code"] == "ZELLE29")
    assert stored["is_convertible_to"] is False

    # Toggle back to True
    r = requests.put(
        f"{API}/admin/currencies/{created['id']}", headers=_hdr(ADMIN_TOKEN),
        json={"code": "ZELLE29", "name": "Test Zelle",
              "type": "fiat", "is_active": True, "is_convertible_to": True},
    )
    assert r.status_code == 200, r.text
    assert r.json()["is_convertible_to"] is True

    _cleanup()


def test_orders_endpoint_still_allows_non_convertible_target():
    """Per operator decision, the flag does NOT block P2P orders — Zelle is
    perfectly valid AS PAYMENT SOURCE. This guard-rail regression ensures the
    flag stays scoped to /vip/convert only."""
    _cleanup()
    _upsert_currency("ZELLE29", "fiat", is_convertible_to=False,
                     delivery_methods=["transfer"])
    _upsert_currency("CUP29", "fiat", is_convertible_to=True,
                     delivery_methods=["cash", "transfer"])
    _upsert_rate("ZELLE29", "CUP29", 100.0)

    # Client pays 5 ZELLE29 to receive CUP29 (P2P) → ZELLE is SOURCE, not target
    # Target is CUP29 (convertible). Order should be accepted regardless of
    # ZELLE29's is_convertible_to flag.
    r = requests.post(
        f"{API}/orders", headers=_hdr(VIP_TOKEN),
        json={
            "from_code": "ZELLE29", "to_code": "CUP29",
            "amount_from": 5.0,
            "delivery_method": "cash",
            "delivery_details": "Nombre: Juan Pérez, ID 12345, Cel +5300",
            "sender_name": "Test Sender", "proof_image": "",
        },
    )
    assert r.status_code == 200, r.text

    _cleanup()
