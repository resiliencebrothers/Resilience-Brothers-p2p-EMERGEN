"""iter55 — Coverage for the two P0 bugs reported by the operator:

1) `_compute_company_funds` MUST subtract order payouts (`amount_to`) whenever
   an order is completed with a physical delivery_method (transfer/cash/crypto).
   `accumulate` orders MUST NOT be subtracted (the money stays in the treasury).

2) `build_transactions` MUST list those same order payouts as `direction=out`
   rows with `ref_type=order_payout` — so the accounting log matches reality.
"""
import os
import time
import uuid
import requests

from tests.conftest import BASE_URL, ADMIN_TOKEN, VIP_TOKEN, make_admin_totp

H_ADMIN = {"Authorization": f"Bearer {ADMIN_TOKEN}"}
H_VIP = {"Authorization": f"Bearer {VIP_TOKEN}"}


def _mongo():
    from pymongo import MongoClient
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _seed_order(delivery_method: str, status: str = "completed",
                to_code: str = "CUP", amount_to: float = 10000.0,
                from_code: str = "USDT", amount_from: float = 100.0) -> str:
    """Directly upsert an order (bypasses admin approval UI)."""
    from datetime import datetime, timezone
    db = _mongo()
    oid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "id": oid,
        "user_id": "user_test_vip01",
        "user_email": "vip.test@resilience.com",
        "user_name": "Test VIP",
        "from_code": from_code,
        "to_code": to_code,
        "amount_from": amount_from,
        "amount_to": amount_to,
        "rate": amount_to / amount_from if amount_from else 0,
        "real_rate": amount_to / amount_from if amount_from else 0,
        "delivery_method": delivery_method,
        "delivery_details": "iter55 test payout",
        "status": status,
        "created_at": now,
        "updated_at": now,
    }
    db.orders.insert_one(doc)
    return oid


def _clean(oid: str):
    db = _mongo()
    db.orders.delete_one({"id": oid})


class TestCompanyFundsOrderOutflow:
    def test_completed_transfer_reduces_balance(self):
        # Baseline
        r0 = requests.get(f"{BASE_URL}/api/admin/company-funds", headers=H_ADMIN, timeout=15)
        assert r0.status_code == 200
        base = {row["currency"]: row for row in r0.json()}
        base_out = float(base.get("CUP", {}).get("outflow_orders") or 0.0)
        base_bal = float(base.get("CUP", {}).get("balance") or 0.0)

        oid = _seed_order("transfer", "completed", to_code="CUP", amount_to=25000.0)
        try:
            r1 = requests.get(f"{BASE_URL}/api/admin/company-funds", headers=H_ADMIN, timeout=15)
            assert r1.status_code == 200
            row = next(x for x in r1.json() if x["currency"] == "CUP")
            assert "outflow_orders" in row
            assert row["outflow_orders"] >= base_out + 24999.9
            # Balance moved down by 25000 (relative to baseline)
            assert row["balance"] <= base_bal - 24999.9
        finally:
            _clean(oid)

    def test_completed_accumulate_does_not_reduce_balance(self):
        r0 = requests.get(f"{BASE_URL}/api/admin/company-funds", headers=H_ADMIN, timeout=15)
        base = {row["currency"]: row for row in r0.json()}
        base_out = float(base.get("CUP", {}).get("outflow_orders") or 0.0)
        base_bal = float(base.get("CUP", {}).get("balance") or 0.0)

        oid = _seed_order("accumulate", "completed", to_code="CUP", amount_to=50000.0)
        try:
            r1 = requests.get(f"{BASE_URL}/api/admin/company-funds", headers=H_ADMIN, timeout=15)
            row = next(x for x in r1.json() if x["currency"] == "CUP")
            # accumulate → outflow_orders unchanged; balance unchanged
            assert abs(row["outflow_orders"] - base_out) < 0.01
            assert abs(row["balance"] - base_bal) < 0.01
        finally:
            _clean(oid)

    def test_approved_but_not_completed_does_not_count_yet(self):
        r0 = requests.get(f"{BASE_URL}/api/admin/company-funds", headers=H_ADMIN, timeout=15)
        base = {row["currency"]: row for row in r0.json()}
        base_out = float(base.get("CUP", {}).get("outflow_orders") or 0.0)

        oid = _seed_order("transfer", "approved", to_code="CUP", amount_to=7777.0)
        try:
            r1 = requests.get(f"{BASE_URL}/api/admin/company-funds", headers=H_ADMIN, timeout=15)
            row = next(x for x in r1.json() if x["currency"] == "CUP")
            # not yet completed → not deducted
            assert abs(row["outflow_orders"] - base_out) < 0.01
        finally:
            _clean(oid)


class TestTransactionsRegistryPayouts:
    def test_completed_transfer_shows_as_outbound(self):
        oid = _seed_order("cash", "completed", to_code="USD", amount_to=333.0)
        try:
            r = requests.get(
                f"{BASE_URL}/api/admin/transactions?direction=out&currency=USD&limit=500",
                headers=H_ADMIN, timeout=15,
            )
            assert r.status_code == 200
            rows = r.json()["items"]
            match = [x for x in rows if x.get("ref_id") == oid]
            assert len(match) == 1, "order payout should appear as an outbound tx"
            row = match[0]
            assert row["direction"] == "out"
            assert row["ref_type"] == "order_payout"
            assert row["currency"] == "USD"
            assert row["amount"] == 333.0
            assert row["method"] == "cash"
        finally:
            _clean(oid)

    def test_accumulate_does_not_show_as_outbound(self):
        oid = _seed_order("accumulate", "completed", to_code="USD", amount_to=222.0)
        try:
            r = requests.get(
                f"{BASE_URL}/api/admin/transactions?direction=out&currency=USD&limit=500",
                headers=H_ADMIN, timeout=15,
            )
            assert r.status_code == 200
            rows = r.json()["items"]
            # accumulate → no P2P payout to log
            assert not any(x.get("ref_id") == oid for x in rows)
        finally:
            _clean(oid)

    def test_client_sees_own_payout(self):
        oid = _seed_order("transfer", "completed", to_code="CUP", amount_to=1500.0)
        try:
            r = requests.get(
                f"{BASE_URL}/api/me/transactions?limit=500", headers=H_VIP, timeout=15,
            )
            assert r.status_code == 200
            match = [x for x in r.json()["items"] if x.get("ref_id") == oid]
            assert len(match) == 1
            assert match[0]["direction"] == "out"
            assert match[0]["ref_type"] == "order_payout"
        finally:
            _clean(oid)

    def test_filter_by_currency_works_on_payouts(self):
        oid = _seed_order("transfer", "completed", to_code="EUR", amount_to=99.0)
        try:
            r = requests.get(
                f"{BASE_URL}/api/admin/transactions?direction=out&currency=EUR",
                headers=H_ADMIN, timeout=15,
            )
            assert r.status_code == 200
            match = [x for x in r.json()["items"] if x.get("ref_id") == oid]
            assert len(match) == 1
        finally:
            _clean(oid)
