"""Iter25 — Regression coverage for the cyclomatic-complexity refactor.

The main agent extracted private helpers from:
  - routes/admin.py::update_withdrawal  (helpers _assert_paid_lock,
    _refund_balance_on_reject, _collect_payout_evidence, _validate_paid_evidence)
  - routes/admin.py::admin_revenue      (helpers _new_pair_bucket,
    _role_bucket_for, _accumulate_revenue_order, _finalize_pair_items)
  - audit_pdf.py::generate_audit_pdf    (helpers _format_audit_ts,
    _build_audit_row, _build_filters_paragraph)
  - pdf_service.py::generate_vip_closing_pdf  (helpers _compute_closing_totals,
    _format_order_row, _build_currency_breakdown_table)

These tests confirm end-to-end via HTTP that signatures, error codes/messages,
JSON shapes and PDF outputs are unchanged.
"""
import os
import uuid
from datetime import datetime, timezone

import pytest
import requests
from pymongo import MongoClient

from conftest import (
    BASE_URL, ADMIN_TOKEN as ADMIN, EMPLOYEE_TOKEN as EMP, VIP_TOKEN as VIP,
    make_admin_totp, make_employee_totp,
)

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]


def _h(t=None, totp=False):
    h = {"Content-Type": "application/json"}
    if t:
        h["Authorization"] = f"Bearer {t}"
    return h


def _mongo():
    return MongoClient(MONGO_URL)[DB_NAME]


def _seed_withdrawal(method="transfer", status="pending", currency="USD",
                     amount_usd=25.0, user_id="user_test_vip01"):
    """Insert a withdrawal row directly so we can drive update_withdrawal
    deterministically across its branches."""
    wid = f"TEST_wd_{uuid.uuid4().hex[:10]}"
    doc = {
        "id": wid,
        "user_id": user_id,
        "user_name": "Test VIP",
        "user_email": "vip@example.com",
        "amount_usd": amount_usd,
        "currency": currency,
        "method": method,
        "status": status,
        "address_or_account": "wallet_or_acct",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _mongo().withdrawals.insert_one(doc)
    return wid


def _cleanup_withdrawal(wid):
    _mongo().withdrawals.delete_one({"id": wid})


# ============================================================
# update_withdrawal — refactored branches
# ============================================================
class TestUpdateWithdrawalRefactor:
    """Drives each refactored helper through PUT /admin/withdrawals/{wid}/status."""

    # (a) invalid status -> 400
    def test_invalid_status_returns_400(self):
        wid = _seed_withdrawal()
        try:
            r = requests.put(
                f"{BASE_URL}/api/admin/withdrawals/{wid}/status",
                json={"status": "garbage", "totp_code": make_admin_totp()},
                headers=_h(ADMIN),
            )
            assert r.status_code == 400, r.text
            assert "status inválido" in r.json().get("detail", "")
        finally:
            _cleanup_withdrawal(wid)

    # (b) missing id -> 404
    def test_missing_id_returns_404(self):
        r = requests.put(
            f"{BASE_URL}/api/admin/withdrawals/TEST_doesnotexist/status",
            json={"status": "approved", "totp_code": make_admin_totp()},
            headers=_h(ADMIN),
        )
        assert r.status_code == 404, r.text
        assert "No encontrado" in r.json().get("detail", "")

    # (c) employee cannot un-pay a paid withdrawal
    def test_employee_cannot_unpay_paid(self):
        wid = _seed_withdrawal(status="paid")
        try:
            r = requests.put(
                f"{BASE_URL}/api/admin/withdrawals/{wid}/status",
                json={"status": "pending", "totp_code": make_employee_totp()},
                headers=_h(EMP),
            )
            assert r.status_code == 403, r.text
            assert "ya fue entregado" in r.json().get("detail", "").lower()
        finally:
            _cleanup_withdrawal(wid)

    # (c2) admin CAN un-pay (lock applies only to non-admin)
    def test_admin_can_unpay_paid(self):
        wid = _seed_withdrawal(status="paid")
        try:
            r = requests.put(
                f"{BASE_URL}/api/admin/withdrawals/{wid}/status",
                json={"status": "approved", "totp_code": make_admin_totp()},
                headers=_h(ADMIN),
            )
            assert r.status_code == 200, r.text
            assert r.json()["status"] == "approved"
        finally:
            _cleanup_withdrawal(wid)

    # (d) marking 'rejected' refunds vip_balances[currency]
    def test_reject_refunds_balance(self):
        wid = _seed_withdrawal(currency="USD", amount_usd=33.0)
        users = _mongo().users
        before = users.find_one({"user_id": "user_test_vip01"}) or {}
        bal_before = float((before.get("vip_balances") or {}).get("USD") or 0.0)
        try:
            r = requests.put(
                f"{BASE_URL}/api/admin/withdrawals/{wid}/status",
                json={"status": "rejected", "totp_code": make_admin_totp()},
                headers=_h(ADMIN),
            )
            assert r.status_code == 200, r.text
            after = users.find_one({"user_id": "user_test_vip01"}) or {}
            bal_after = float((after.get("vip_balances") or {}).get("USD") or 0.0)
            assert abs((bal_after - bal_before) - 33.0) < 1e-6, (bal_before, bal_after)
        finally:
            # roll back the balance bump so the test is idempotent
            users.update_one(
                {"user_id": "user_test_vip01"},
                {"$inc": {"vip_balances.USD": -33.0}},
            )
            _cleanup_withdrawal(wid)

    # (e) paid + transfer + missing proof -> 400
    def test_paid_transfer_missing_proof_400(self):
        wid = _seed_withdrawal(method="transfer", status="approved")
        try:
            r = requests.put(
                f"{BASE_URL}/api/admin/withdrawals/{wid}/status",
                json={"status": "paid", "totp_code": make_admin_totp()},
                headers=_h(ADMIN),
            )
            assert r.status_code == 400, r.text
            assert "captura" in r.json().get("detail", "").lower()
        finally:
            _cleanup_withdrawal(wid)

    # (f) paid + crypto + no tx_hash & no proof -> 400
    def test_paid_crypto_no_evidence_400(self):
        wid = _seed_withdrawal(method="crypto", status="approved")
        try:
            r = requests.put(
                f"{BASE_URL}/api/admin/withdrawals/{wid}/status",
                json={"status": "paid", "totp_code": make_admin_totp()},
                headers=_h(ADMIN),
            )
            assert r.status_code == 400, r.text
            detail = r.json().get("detail", "").lower()
            assert "hash" in detail and "captura" in detail
        finally:
            _cleanup_withdrawal(wid)

    # (g) paid + crypto + tx_hash -> 200
    def test_paid_crypto_with_hash_ok(self):
        wid = _seed_withdrawal(method="crypto", status="approved")
        try:
            r = requests.put(
                f"{BASE_URL}/api/admin/withdrawals/{wid}/status",
                json={
                    "status": "paid",
                    "payout_tx_hash": "0xdeadbeefcafeface",
                    "totp_code": make_admin_totp(),
                },
                headers=_h(ADMIN),
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["status"] == "paid"
            assert body.get("payout_tx_hash") == "0xdeadbeefcafeface"
        finally:
            _cleanup_withdrawal(wid)

    # (h) TOTP step-up: missing totp on a 2FA-enabled admin -> 401
    def test_missing_totp_step_up_returns_401(self):
        # admin has 2FA pre-enabled via conftest.make_admin_totp()
        wid = _seed_withdrawal()
        try:
            r = requests.put(
                f"{BASE_URL}/api/admin/withdrawals/{wid}/status",
                json={"status": "approved"},  # no totp_code
                headers=_h(ADMIN),
            )
            assert r.status_code == 401, r.text
        finally:
            _cleanup_withdrawal(wid)


# ============================================================
# admin_revenue — JSON shape preserved by refactor
# ============================================================
class TestRevenueShape:
    EXPECTED_TOP_KEYS = {
        "total_profit_usdt", "p2p_profit_usdt", "marketplace_profit_usdt",
        "total_volume_usdt", "profit_margin_pct", "by_pair", "by_role",
        "marketplace", "missing_real_rate_pairs", "orders_total",
    }
    PAIR_KEYS = {
        "pair", "from_code", "to_code", "orders", "volume_from", "volume_to",
        "profit_to", "profit_usdt", "real_rate", "rate_normal", "rate_vip",
        "avg_profit_pct",
    }
    ROLE_KEYS = {"profit_usdt", "orders", "volume_usdt"}

    def _assert_shape(self, data):
        missing = self.EXPECTED_TOP_KEYS - set(data.keys())
        assert not missing, f"missing top-level keys: {missing}"
        assert isinstance(data["by_pair"], list)
        assert isinstance(data["missing_real_rate_pairs"], list)
        assert data["missing_real_rate_pairs"] == sorted(data["missing_real_rate_pairs"])
        assert set(data["by_role"].keys()) >= {"normal", "vip"}
        for role in ("normal", "vip"):
            assert self.ROLE_KEYS <= set(data["by_role"][role].keys())
        for item in data["by_pair"]:
            missing_p = self.PAIR_KEYS - set(item.keys())
            assert not missing_p, f"pair item missing keys: {missing_p} -> {item}"
        # sort order: by_pair sorted by profit_usdt desc
        profits = [p["profit_usdt"] for p in data["by_pair"]]
        assert profits == sorted(profits, reverse=True)
        # marketplace shape
        for k in ("total_revenue_usd", "total_cost_usd", "total_profit_usd",
                  "items", "deliveries"):
            assert k in data["marketplace"], k

    def test_revenue_default(self):
        r = requests.get(f"{BASE_URL}/api/admin/revenue", headers=_h(ADMIN))
        assert r.status_code == 200, r.text
        self._assert_shape(r.json())

    def test_revenue_days_30(self):
        r = requests.get(f"{BASE_URL}/api/admin/revenue?days=30", headers=_h(ADMIN))
        assert r.status_code == 200, r.text
        self._assert_shape(r.json())


# ============================================================
# PDFs — content-type + magic bytes
# ============================================================
class TestPDFOutputs:
    def test_vip_daily_closing_no_orders(self):
        # Use a far-future date that surely has no orders.
        r = requests.get(
            f"{BASE_URL}/api/vip/daily-closing?date=2099-01-01",
            headers=_h(ADMIN),
        )
        assert r.status_code == 200, r.text
        assert r.headers.get("content-type", "").startswith("application/pdf")
        assert r.content[:4] == b"%PDF"

    def test_vip_daily_closing_today(self):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        r = requests.get(
            f"{BASE_URL}/api/vip/daily-closing?date={today}",
            headers=_h(ADMIN),
        )
        assert r.status_code == 200, r.text
        assert r.headers.get("content-type", "").startswith("application/pdf")
        assert r.content[:4] == b"%PDF"

    def test_audit_pdf_no_filters(self):
        r = requests.get(f"{BASE_URL}/api/admin/audit/export.pdf",
                         headers=_h(ADMIN))
        assert r.status_code == 200, r.text
        assert r.headers.get("content-type", "").startswith("application/pdf")
        assert r.content[:4] == b"%PDF"

    def test_audit_pdf_with_filters(self):
        params = {
            "action": "order.approved",
            "since": "2020-01-01T00:00:00",
            "until": "2099-12-31T23:59:59",
            "actor_id": "user_test_admin01",
        }
        r = requests.get(f"{BASE_URL}/api/admin/audit/export.pdf",
                         params=params, headers=_h(ADMIN))
        assert r.status_code == 200, r.text
        assert r.headers.get("content-type", "").startswith("application/pdf")
        assert r.content[:4] == b"%PDF"


# ============================================================
# /admin/health/summary — 7-section smoke
# ============================================================
class TestHealthSummaryShape:
    REQUIRED = {"sentry", "storage", "throughput", "defensive_mode",
                "negative_margin", "queues", "platform"}

    def test_sections_present(self):
        r = requests.get(f"{BASE_URL}/api/admin/health/summary",
                         headers=_h(ADMIN))
        assert r.status_code == 200, r.text
        missing = self.REQUIRED - set(r.json().keys())
        assert not missing, f"missing health sections: {missing}"
