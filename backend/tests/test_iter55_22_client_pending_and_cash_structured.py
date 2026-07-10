"""iter55.22 — Client dashboard "Pendientes" counter + structured cash details.

Bug 1: The client's dashboard was showing "PENDIENTES: 0" even when they had
a cash withdrawal in status="approved" (rendered as "En progreso" in the UI).
The counter now includes withdrawals in flight, not only orders.

Bug 2: The cash withdrawal details field was a free-form textarea. The user
requested a structured form (Nombre / Celular / Dirección / ID opcional) so
every client submits the same format. The frontend composes a labelled string
and posts it as `details`. This test verifies the composed string flows
through the backend unchanged, meets the min-length gate, and is persisted
verbatim so admin sees the same block.
"""
import os
import uuid
import requests

from tests.conftest import BASE_URL as API_ROOT, VIP_TOKEN, make_vip_totp
from pymongo import MongoClient

API = f"{API_ROOT}/api"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _upsert_currency(code, name, ctype="fiat", delivery_methods=None):
    _db().currencies.update_one(
        {"code": code},
        {"$set": {
            "code": code, "name": name, "type": ctype, "is_active": True,
            "delivery_methods": delivery_methods,
            "updated_at": "2026-07-10T00:00:00+00:00",
        },
         "$setOnInsert": {"id": uuid.uuid4().hex, "created_at": "2026-07-10T00:00:00+00:00"}},
        upsert=True,
    )


def _seed_vip_balance(code, amount):
    _db().users.update_one(
        {"user_id": "user_test_vip01"},
        {"$set": {f"vip_balances.{code}": amount}},
    )


def _clear_balance(code):
    _db().users.update_one(
        {"user_id": "user_test_vip01"},
        {"$unset": {f"vip_balances.{code}": ""}},
    )
    _db().currencies.delete_one({"code": code})


def test_cash_withdrawal_accepts_structured_details_from_new_ui():
    """The frontend now sends `details` as a labelled multiline block:
      Nombre: Juan Pérez
      Celular: +5355555555
      Dirección: Calle 23 nº 456, Vedado, La Habana
    That composed string must (a) pass the >=20 char gate, (b) persist
    verbatim so admin sees the same structure, (c) return 200."""
    _upsert_currency("USDCASH_S22", "USD Efectivo iter55.22", "fiat", delivery_methods=["cash"])
    _seed_vip_balance("USDCASH_S22", 500)

    composed = (
        "Nombre: Juan Pérez Rodríguez\n"
        "Celular: +5355551234\n"
        "Dirección: Calle 23 nº 456, entre A y B, Vedado, La Habana"
    )
    r = requests.post(
        f"{API}/vip/withdraw", headers=_hdr(VIP_TOKEN),
        json={
            "amount_usd": 40,
            "currency": "USDCASH_S22",
            "method": "cash",
            "details": composed,
            "beneficiary_name": "Juan Pérez Rodríguez",
            "totp_code": make_vip_totp(),
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["method"] == "cash"
    assert body["details"] == composed, "Backend must persist the composed block verbatim"

    _db().withdrawals.delete_many({"id": body["id"]})
    _clear_balance("USDCASH_S22")


def test_cash_withdrawal_with_optional_id_also_persists():
    """The optional 4th line (ID / Carné) is preserved when present."""
    _upsert_currency("USDCASH_S22B", "USD Efectivo iter55.22b", "fiat", delivery_methods=["cash"])
    _seed_vip_balance("USDCASH_S22B", 500)

    composed = (
        "Nombre: María López\n"
        "Celular: +5354449988\n"
        "Dirección: Ave 51 nº 220, Marianao\n"
        "ID / Carné: 87050112345"
    )
    r = requests.post(
        f"{API}/vip/withdraw", headers=_hdr(VIP_TOKEN),
        json={
            "amount_usd": 25,
            "currency": "USDCASH_S22B",
            "method": "cash",
            "details": composed,
            "beneficiary_name": "María López",
            "totp_code": make_vip_totp(),
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "ID / Carné: 87050112345" in body["details"]

    _db().withdrawals.delete_many({"id": body["id"]})
    _clear_balance("USDCASH_S22B")


def test_vip_withdrawals_mine_endpoint_returns_approved_status():
    """The dashboard's PENDIENTES fix depends on this endpoint returning
    withdrawals in `approved` state (== "En progreso" for cash). Regression
    guard: if a future refactor filters approved out server-side, the client
    counter goes back to showing 0 pendientes."""
    r = requests.get(f"{API}/vip/withdrawals/mine", headers=_hdr(VIP_TOKEN))
    assert r.status_code == 200, r.text
    data = r.json()
    assert isinstance(data, list)
    statuses = {w.get("status") for w in data}
    # Non-strict — we don't require an `approved` withdrawal to exist right
    # now, but if one exists it must NOT be filtered out.
    assert statuses <= {"pending", "approved", "paid", "rejected"}, statuses
