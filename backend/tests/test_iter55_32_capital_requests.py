"""iter55.32 — Capital request flow + user stats endpoint.

Operator ask (12 Feb 2026): VIPs can request working capital from company
funds; admin approves with a discount %, which is auto-applied to every
accumulated order the VIP subsequently completes until the debt is 0.

Coverage:
  - VIP CREATE + LIST own capital requests
  - Non-VIP roles cannot create capital requests
  - Admin list + filter by status
  - Admin approve → credits VIP balance + marks disbursed + debt tracked
  - Admin reject → status flips + reason recorded
  - Auto-discount in `_credit_accumulated_order`: FIFO across multiple debts
  - Once debt hits 0 → status = paid_off
  - `GET /admin/users/{id}/stats` returns correct net position both ways
"""
import os
import uuid
import bcrypt
import pyotp
import requests
from datetime import datetime, timezone
from pymongo import MongoClient

from tests.conftest import BASE_URL as API_ROOT, VIP_TOKEN, ADMIN_TOKEN, NORMAL_TOKEN

API = f"{API_ROOT}/api"

TOTP_SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _totp():
    return pyotp.TOTP(TOTP_SECRET).now()


def _iso():
    return datetime.now(timezone.utc).isoformat()


def _upsert_currency(code, ctype="crypto"):
    _db().currencies.update_one(
        {"code": code},
        {"$set": {"code": code, "name": f"Test {code}", "type": ctype,
                  "is_active": True, "is_convertible_to": True,
                  "updated_at": _iso()},
         "$setOnInsert": {"id": uuid.uuid4().hex, "created_at": _iso()}},
        upsert=True,
    )


def _clear_all_capital_requests_for(uid):
    _db().capital_requests.delete_many({"user_id": uid})


def _clear_vip_balance(uid, code=None):
    if code:
        _db().users.update_one({"user_id": uid}, {"$unset": {f"vip_balances.{code}": ""}})
    else:
        _db().users.update_one({"user_id": uid}, {"$unset": {"vip_balances": ""}})


# ============================================================
# CREATE + LIST
# ============================================================

def test_vip_create_capital_request_happy_path():
    _clear_all_capital_requests_for("user_test_vip01")
    _upsert_currency("USDT32", "crypto")
    try:
        r = requests.post(
            f"{API}/vip/capital-requests", headers=_hdr(VIP_TOKEN),
            json={"amount": 500.0, "currency_code": "USDT32",
                  "reason": "Capital para cliente grande esta semana"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "pending"
        assert body["amount"] == 500.0
        assert body["currency_code"] == "USDT32"
        assert body["id"].startswith("cr_")

        # List own — should see it
        lst = requests.get(f"{API}/vip/capital-requests", headers=_hdr(VIP_TOKEN)).json()
        assert any(cr["id"] == body["id"] for cr in lst)
    finally:
        _clear_all_capital_requests_for("user_test_vip01")
        _db().currencies.delete_many({"code": "USDT32"})


def test_normal_user_cannot_create_capital_request():
    _upsert_currency("USDT32")
    try:
        r = requests.post(
            f"{API}/vip/capital-requests", headers=_hdr(NORMAL_TOKEN),
            json={"amount": 100.0, "currency_code": "USDT32",
                  "reason": "Necesito capital operativo"},
        )
        assert r.status_code == 403, r.text
        assert "VIP" in r.json()["detail"]
    finally:
        _db().currencies.delete_many({"code": "USDT32"})


def test_capital_request_rejects_invalid_currency():
    r = requests.post(
        f"{API}/vip/capital-requests", headers=_hdr(VIP_TOKEN),
        json={"amount": 100.0, "currency_code": "NOTEXIST",
              "reason": "moneda inválida no debería crearse"},
    )
    assert r.status_code == 400, r.text


def test_capital_request_rejects_short_reason():
    _upsert_currency("USDT32")
    try:
        r = requests.post(
            f"{API}/vip/capital-requests", headers=_hdr(VIP_TOKEN),
            json={"amount": 100.0, "currency_code": "USDT32", "reason": "hola"},
        )
        assert r.status_code == 422, r.text
    finally:
        _db().currencies.delete_many({"code": "USDT32"})


# ============================================================
# ADMIN APPROVE / REJECT
# ============================================================

def test_admin_approve_credits_balance_and_marks_disbursed():
    _clear_all_capital_requests_for("user_test_vip01")
    _clear_vip_balance("user_test_vip01", "USDT32")
    _upsert_currency("USDT32")
    try:
        # VIP creates
        cr = requests.post(
            f"{API}/vip/capital-requests", headers=_hdr(VIP_TOKEN),
            json={"amount": 500.0, "currency_code": "USDT32",
                  "reason": "Capital para cliente grande esta semana"},
        ).json()

        # Admin approves with 30% discount
        r = requests.post(
            f"{API}/admin/capital-requests/{cr['id']}/approve", headers=_hdr(ADMIN_TOKEN),
            json={"discount_pct": 30, "admin_notes": "cliente confiable", "totp_code": _totp()},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "disbursed"
        assert body["discount_pct"] == 30.0
        assert body["debt_original"] == 500.0
        assert body["debt_remaining"] == 500.0

        # VIP balance credited by 500 USDT32
        u = _db().users.find_one({"user_id": "user_test_vip01"}, {"_id": 0, "vip_balances": 1})
        assert float(u["vip_balances"]["USDT32"]) == 500.0
    finally:
        _clear_all_capital_requests_for("user_test_vip01")
        _clear_vip_balance("user_test_vip01", "USDT32")
        _db().currencies.delete_many({"code": "USDT32"})


def test_admin_reject_locks_request_no_money_moves():
    _clear_all_capital_requests_for("user_test_vip01")
    _clear_vip_balance("user_test_vip01", "USDT32")
    _upsert_currency("USDT32")
    try:
        cr = requests.post(
            f"{API}/vip/capital-requests", headers=_hdr(VIP_TOKEN),
            json={"amount": 200.0, "currency_code": "USDT32",
                  "reason": "solicitud que será rechazada"},
        ).json()

        r = requests.post(
            f"{API}/admin/capital-requests/{cr['id']}/reject", headers=_hdr(ADMIN_TOKEN),
            json={"reject_reason": "Historial de operaciones insuficiente por ahora.",
                  "totp_code": _totp()},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "rejected"
        assert "historial" in body["reject_reason"].lower()

        # Balance NOT touched
        u = _db().users.find_one({"user_id": "user_test_vip01"}, {"_id": 0, "vip_balances": 1}) or {}
        assert float((u.get("vip_balances") or {}).get("USDT32", 0)) == 0.0

        # Cannot re-approve after rejection
        r2 = requests.post(
            f"{API}/admin/capital-requests/{cr['id']}/approve", headers=_hdr(ADMIN_TOKEN),
            json={"discount_pct": 10, "totp_code": _totp()},
        )
        assert r2.status_code == 400
    finally:
        _clear_all_capital_requests_for("user_test_vip01")
        _clear_vip_balance("user_test_vip01", "USDT32")
        _db().currencies.delete_many({"code": "USDT32"})


def test_admin_list_filters_by_status():
    _clear_all_capital_requests_for("user_test_vip01")
    _upsert_currency("USDT32")
    try:
        # Create 2 pending
        for i in range(2):
            requests.post(
                f"{API}/vip/capital-requests", headers=_hdr(VIP_TOKEN),
                json={"amount": 100.0 + i, "currency_code": "USDT32",
                      "reason": f"pedido de prueba número {i} para filtro"},
            )
        listing = requests.get(
            f"{API}/admin/capital-requests?status=pending", headers=_hdr(ADMIN_TOKEN),
        ).json()
        mine = [c for c in listing if c["user_id"] == "user_test_vip01"]
        assert len(mine) >= 2
        assert all(c["status"] == "pending" for c in mine)
    finally:
        _clear_all_capital_requests_for("user_test_vip01")
        _db().currencies.delete_many({"code": "USDT32"})


def _plant_and_accumulate(user_id: str, to_code: str, amount_to: float) -> str:
    """Plant a pending accumulate order + hit admin status endpoint to trigger
    `accumulate_vip_balance` through the running FastAPI server. This runs
    the same code path production uses, including our new capital-request
    auto-discount hook. Returns the order id."""
    oid = f"test_cr_o_{uuid.uuid4().hex[:8]}"
    _db().orders.insert_one({
        "id": oid, "user_id": user_id,
        "user_email": "vip@test", "user_name": "VIP Test", "user_role": "vip",
        "from_code": "USD", "to_code": to_code,
        "amount_from": amount_to, "amount_to": amount_to,
        "rate_applied": 1.0, "commission_percent": 0.0,
        "delivery_method": "accumulate", "delivery_details": "n/a",
        "sender_name": "x", "proof_image": "",
        "status": "pending", "created_at": _iso(),
    })
    r = requests.put(
        f"{API}/admin/orders/{oid}/status", headers=_hdr(ADMIN_TOKEN),
        json={"status": "completed", "admin_note": "cr test",
              "totp_code": _totp()},
    )
    assert r.status_code == 200, r.text
    return oid

def test_auto_discount_on_accumulated_order_pays_down_debt():
    """VIP has a 500 USDT debt @ 30% discount. They complete an accumulated
    order that would credit 100 USDT. Expected:
      - 30% of 100 = 30 USDT goes to debt (500 → 470 remaining)
      - 70 USDT hits vip_balance
    """
    _clear_all_capital_requests_for("user_test_vip01")
    _clear_vip_balance("user_test_vip01", "USDT")
    _upsert_currency("USDT")

    # Set up a capital debt directly (bypass admin approve for speed)
    debt_id = f"cr_{uuid.uuid4().hex[:12]}"
    _db().capital_requests.insert_one({
        "id": debt_id, "user_id": "user_test_vip01",
        "user_email": "vip@test", "user_name": "VIP Test",
        "amount": 500.0, "currency_code": "USDT", "reason": "test",
        "status": "disbursed", "discount_pct": 30.0,
        "debt_original": 500.0, "debt_remaining": 500.0,
        "disbursed_at": _iso(), "created_at": _iso(), "updated_at": _iso(),
        "repayment_events": [],
    })
    _clear_vip_balance("user_test_vip01", "USDT")

    oid = _plant_and_accumulate("user_test_vip01", "USDT", 100.0)
    try:
        # VIP balance = 70 (100 - 30% discount)
        fresh_user = _db().users.find_one({"user_id": "user_test_vip01"},
                                            {"_id": 0, "vip_balances": 1})
        assert round(float(fresh_user["vip_balances"]["USDT"]), 4) == 70.0

        # Debt reduced from 500 → 470
        fresh_debt = _db().capital_requests.find_one({"id": debt_id})
        assert round(float(fresh_debt["debt_remaining"]), 4) == 470.0
        assert fresh_debt["status"] == "disbursed"
        # Repayment event logged
        assert len(fresh_debt["repayment_events"]) == 1
        assert fresh_debt["repayment_events"][0]["order_id"] == oid
        assert round(float(fresh_debt["repayment_events"][0]["amount"]), 4) == 30.0
    finally:
        _db().orders.delete_many({"id": oid})
        _clear_all_capital_requests_for("user_test_vip01")
        _clear_vip_balance("user_test_vip01", "USDT")


def test_auto_discount_closes_debt_at_zero_marks_paid_off():
    """Debt = 20, order credits 100 @ 30% = 30 → but cap at remaining debt 20.
    Expected: debt → 0 (paid_off), balance credited 100 - 20 = 80."""
    _clear_all_capital_requests_for("user_test_vip01")
    _clear_vip_balance("user_test_vip01", "USDT")
    _upsert_currency("USDT")

    debt_id = f"cr_{uuid.uuid4().hex[:12]}"
    _db().capital_requests.insert_one({
        "id": debt_id, "user_id": "user_test_vip01",
        "user_email": "vip@test", "user_name": "VIP Test",
        "amount": 500.0, "currency_code": "USDT", "reason": "test",
        "status": "disbursed", "discount_pct": 30.0,
        "debt_original": 500.0, "debt_remaining": 20.0,  # almost paid off
        "disbursed_at": _iso(), "created_at": _iso(), "updated_at": _iso(),
        "repayment_events": [],
    })
    _clear_vip_balance("user_test_vip01", "USDT")

    oid = _plant_and_accumulate("user_test_vip01", "USDT", 100.0)
    try:
        fresh_user = _db().users.find_one({"user_id": "user_test_vip01"},
                                            {"_id": 0, "vip_balances": 1})
        assert round(float(fresh_user["vip_balances"]["USDT"]), 4) == 80.0

        fresh_debt = _db().capital_requests.find_one({"id": debt_id})
        assert round(float(fresh_debt["debt_remaining"]), 4) == 0.0
        assert fresh_debt["status"] == "paid_off"
        assert fresh_debt.get("paid_off_at") is not None
    finally:
        _db().orders.delete_many({"id": oid})
        _clear_all_capital_requests_for("user_test_vip01")
        _clear_vip_balance("user_test_vip01", "USDT")


def test_auto_discount_fifo_across_multiple_debts():
    """Two active debts (older first). Order 100 @ 30% = 30 total discount.
    Older debt = 15 remaining, newer = 100 remaining.
    Expected: older debt gets 15 (paid_off), newer gets 15 remaining (100 → 85),
    balance credited 70 (100 - 30).
    """
    _clear_all_capital_requests_for("user_test_vip01")
    _clear_vip_balance("user_test_vip01", "USDT")
    _upsert_currency("USDT")

    older_id = f"cr_{uuid.uuid4().hex[:12]}"
    newer_id = f"cr_{uuid.uuid4().hex[:12]}"
    older_iso = "2026-01-01T00:00:00+00:00"
    newer_iso = "2026-02-01T00:00:00+00:00"
    _db().capital_requests.insert_many([
        {"id": older_id, "user_id": "user_test_vip01", "user_email": "vip@test",
         "user_name": "VIP Test", "amount": 100.0, "currency_code": "USDT",
         "reason": "older", "status": "disbursed", "discount_pct": 30.0,
         "debt_original": 100.0, "debt_remaining": 15.0,
         "disbursed_at": older_iso, "created_at": older_iso, "updated_at": older_iso,
         "repayment_events": []},
        {"id": newer_id, "user_id": "user_test_vip01", "user_email": "vip@test",
         "user_name": "VIP Test", "amount": 100.0, "currency_code": "USDT",
         "reason": "newer", "status": "disbursed", "discount_pct": 30.0,
         "debt_original": 100.0, "debt_remaining": 100.0,
         "disbursed_at": newer_iso, "created_at": newer_iso, "updated_at": newer_iso,
         "repayment_events": []},
    ])
    _clear_vip_balance("user_test_vip01", "USDT")

    oid = _plant_and_accumulate("user_test_vip01", "USDT", 100.0)
    try:
        older = _db().capital_requests.find_one({"id": older_id})
        newer = _db().capital_requests.find_one({"id": newer_id})
        user = _db().users.find_one({"user_id": "user_test_vip01"},
                                      {"_id": 0, "vip_balances": 1})

        assert older["status"] == "paid_off"
        assert round(float(older["debt_remaining"]), 4) == 0.0

        assert newer["status"] == "disbursed"
        assert round(float(newer["debt_remaining"]), 4) == 85.0

        assert round(float(user["vip_balances"]["USDT"]), 4) == 70.0
    finally:
        _db().orders.delete_many({"id": oid})
        _clear_all_capital_requests_for("user_test_vip01")
        _clear_vip_balance("user_test_vip01", "USDT")


def test_auto_discount_only_matches_same_currency():
    """Debt is in USDT. Order credits CUP. → No discount applied."""
    _clear_all_capital_requests_for("user_test_vip01")
    _clear_vip_balance("user_test_vip01", "CUP")
    _upsert_currency("USDT")
    _upsert_currency("CUP", "fiat")

    debt_id = f"cr_{uuid.uuid4().hex[:12]}"
    _db().capital_requests.insert_one({
        "id": debt_id, "user_id": "user_test_vip01", "user_email": "vip@test",
        "user_name": "VIP Test", "amount": 500.0, "currency_code": "USDT",
        "reason": "USDT debt only", "status": "disbursed", "discount_pct": 30.0,
        "debt_original": 500.0, "debt_remaining": 500.0,
        "disbursed_at": _iso(), "created_at": _iso(), "updated_at": _iso(),
        "repayment_events": [],
    })

    oid = _plant_and_accumulate("user_test_vip01", "CUP", 1000.0)
    try:
        user = _db().users.find_one({"user_id": "user_test_vip01"},
                                      {"_id": 0, "vip_balances": 1})
        # Full CUP amount credited (no discount from USDT debt)
        assert round(float(user["vip_balances"]["CUP"]), 4) == 1000.0

        # USDT debt untouched
        debt = _db().capital_requests.find_one({"id": debt_id})
        assert round(float(debt["debt_remaining"]), 4) == 500.0
    finally:
        _db().orders.delete_many({"id": oid})
        _clear_all_capital_requests_for("user_test_vip01")
        _clear_vip_balance("user_test_vip01", "CUP")


# ============================================================
# USER STATS ENDPOINT
# ============================================================

def test_admin_user_stats_returns_correct_structure():
    r = requests.get(f"{API}/admin/users/user_test_vip01/stats", headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body.keys()) >= {"user", "balances", "balance_total_usdt", "orders",
                                  "capital", "net_position"}
    assert body["user"]["user_id"] == "user_test_vip01"
    assert body["user"]["role"] == "vip"
    assert "direction" in body["net_position"]


def test_admin_user_stats_net_position_reflects_debt():
    """When client has a large debt vs small balance, net_position direction
    must be `client_owes_platform`."""
    _clear_all_capital_requests_for("user_test_vip01")
    _upsert_currency("USDT")

    _db().capital_requests.insert_one({
        "id": f"cr_{uuid.uuid4().hex[:12]}", "user_id": "user_test_vip01",
        "user_email": "vip@test", "user_name": "VIP Test",
        "amount": 10000.0, "currency_code": "USDT", "reason": "large debt",
        "status": "disbursed", "discount_pct": 20.0,
        "debt_original": 10000.0, "debt_remaining": 10000.0,
        "disbursed_at": _iso(), "created_at": _iso(), "updated_at": _iso(),
        "repayment_events": [],
    })
    try:
        r = requests.get(f"{API}/admin/users/user_test_vip01/stats",
                          headers=_hdr(ADMIN_TOKEN))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["net_position"]["client_owes_platform_usdt"] >= 10000.0
        assert body["net_position"]["direction"] == "client_owes_platform"
        assert body["net_position"]["net_usdt"] < 0
        assert len(body["capital"]["active_requests"]) >= 1
    finally:
        _clear_all_capital_requests_for("user_test_vip01")


def test_admin_user_stats_404_for_unknown_user():
    r = requests.get(f"{API}/admin/users/user_does_not_exist_xxx/stats",
                      headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 404
