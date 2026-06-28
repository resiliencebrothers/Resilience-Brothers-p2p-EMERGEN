"""Iter38 — Smoke test for the admin router split.

Verifies that all admin endpoints respond 200 with valid JSON after the
1247→538 line split into 6 files.
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
ADMIN_COOKIE = {"session_token": "test_session_admin_X"}


def _g(path, **params):
    return requests.get(f"{BASE_URL}/api{path}", cookies=ADMIN_COOKIE, params=params, timeout=30)


# --- admin.py (slim) endpoints ---
class TestAdminSlim:
    def test_orders(self):
        r = _g("/admin/orders")
        assert r.status_code == 200
        assert isinstance(r.json(), (list, dict))

    def test_redemptions(self):
        r = _g("/admin/redemptions")
        assert r.status_code == 200

    def test_stats(self):
        r = _g("/admin/stats")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, dict)

    def test_settings(self):
        r = _g("/admin/settings")
        assert r.status_code == 200

    def test_transactions(self):
        r = _g("/admin/transactions")
        assert r.status_code == 200

    def test_queue(self):
        r = _g("/admin/queue")
        assert r.status_code == 200

    def test_health_summary(self):
        r = _g("/admin/health/summary")
        assert r.status_code == 200


# --- admin_withdrawals.py ---
class TestAdminWithdrawals:
    def test_list(self):
        r = _g("/admin/withdrawals")
        assert r.status_code == 200

    def test_invalid_status_rejected(self):
        # PUT with invalid status should reject (400 or 422). TOTP step-up should kick in first.
        r = requests.put(
            f"{BASE_URL}/api/admin/withdrawals/non_existent_id/status",
            cookies=ADMIN_COOKIE,
            json={"status": "totally_invalid"},
            timeout=10,
        )
        # Expect 400/404/422; NOT 200 and NOT 500
        assert r.status_code in (400, 401, 403, 404, 422), f"got {r.status_code}: {r.text[:200]}"


# --- admin_users.py ---
class TestAdminUsers:
    def test_list(self):
        r = _g("/admin/users")
        assert r.status_code == 200
        assert isinstance(r.json(), (list, dict))


# --- admin_audit.py ---
class TestAdminAudit:
    def test_list(self):
        r = _g("/admin/audit")
        assert r.status_code == 200

    def test_export_csv(self):
        r = _g("/admin/audit/export.csv")
        assert r.status_code == 200
        assert "text/csv" in r.headers.get("content-type", "").lower() or len(r.content) > 0

    def test_export_pdf(self):
        r = _g("/admin/audit/export.pdf")
        assert r.status_code == 200
        assert r.content[:4] == b"%PDF", "expected PDF magic bytes"


# --- admin_company_funds.py ---
class TestAdminCompanyFunds:
    def test_funds(self):
        r = _g("/admin/company-funds")
        assert r.status_code == 200

    def test_company_withdrawals(self):
        r = _g("/admin/company-withdrawals")
        assert r.status_code == 200


# --- admin_revenue.py ---
class TestAdminRevenue:
    def test_revenue(self):
        r = _g("/admin/revenue")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, dict)

    def test_revenue_days_30(self):
        r = _g("/admin/revenue", days=30)
        assert r.status_code == 200

    def test_timeseries_day(self):
        r = _g("/admin/revenue/timeseries", granularity="day")
        assert r.status_code == 200

    def test_monthly_export_pdf(self):
        from datetime import datetime
        now = datetime.utcnow()
        r = _g(
            "/admin/revenue/monthly/export",
            year=now.year,
            month=now.month,
            format="pdf",
        )
        # accept 200 (PDF) or 404 (no data) — but NOT 500
        assert r.status_code in (200, 404), f"got {r.status_code}: {r.text[:300]}"
        if r.status_code == 200:
            assert r.content[:4] == b"%PDF"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
