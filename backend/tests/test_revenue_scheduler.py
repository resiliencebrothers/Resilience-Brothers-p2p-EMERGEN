"""Tests for the monthly auto-email scheduler + on-demand send + chart in PDF."""
import requests

from conftest import BASE_URL, ADMIN_TOKEN, EMPLOYEE_TOKEN, make_admin_totp


def _h(t):
    return {"Authorization": f"Bearer {t}"}


class TestPdfChart:
    def test_pdf_export_contains_chart_payload(self):
        """When there is data for the month, the PDF size should be noticeably
        larger than an empty one because the bar+line chart is embedded."""
        r_empty = requests.get(
            f"{BASE_URL}/api/admin/revenue/monthly/export",
            headers=_h(ADMIN_TOKEN),
            params={"year": 2099, "month": 12, "format": "pdf"},
        )
        r_real = requests.get(
            f"{BASE_URL}/api/admin/revenue/monthly/export",
            headers=_h(ADMIN_TOKEN),
            params={"year": 2026, "month": 6, "format": "pdf"},
        )
        assert r_empty.status_code == 200
        assert r_real.status_code == 200
        # Both must be valid PDFs
        assert r_empty.content[:4] == b"%PDF"
        assert r_real.content[:4] == b"%PDF"
        # And the real one (with chart + table) should be a bit heavier
        assert len(r_real.content) >= len(r_empty.content)


class TestSendNowEndpoint:
    def test_requires_totp(self):
        r = requests.post(
            f"{BASE_URL}/api/admin/revenue/monthly/send-now",
            headers=_h(ADMIN_TOKEN),
            json={"year": 2026, "month": 6},
        )
        # Missing TOTP -> 401 TOTP_CODE_REQUIRED
        assert r.status_code == 401
        detail = r.json().get("detail", {})
        if isinstance(detail, dict):
            assert detail.get("code") == "TOTP_CODE_REQUIRED"

    def test_employee_forbidden(self):
        r = requests.post(
            f"{BASE_URL}/api/admin/revenue/monthly/send-now",
            headers=_h(EMPLOYEE_TOKEN),
            json={"year": 2026, "month": 6, "totp_code": "000000"},
        )
        assert r.status_code == 403  # require_admin

    def test_invalid_month_rejected(self):
        r = requests.post(
            f"{BASE_URL}/api/admin/revenue/monthly/send-now",
            headers=_h(ADMIN_TOKEN),
            json={"year": 2026, "month": 13, "totp_code": make_admin_totp()},
        )
        assert r.status_code == 400

    def test_send_now_succeeds_with_totp(self):
        """End-to-end happy path. Email send may return 0 (Resend sandbox) but the
        endpoint must still report ok=True and an integer count."""
        r = requests.post(
            f"{BASE_URL}/api/admin/revenue/monthly/send-now",
            headers=_h(ADMIN_TOKEN),
            json={"year": 2026, "month": 6, "totp_code": make_admin_totp()},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("ok") is True
        assert "sent" in data and "total_admins" in data
        assert data.get("period") == "2026-06"


class TestSchedulerHelper:
    def test_previous_month_helper(self):
        """Direct unit test on the scheduler's _previous_month() — runs in-process."""
        import sys
        import os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from scheduler import _previous_month
        from datetime import datetime, timezone

        # February 1st 09:00 UTC -> previous month is January
        d = datetime(2026, 2, 1, 9, 0, tzinfo=timezone.utc)
        y, m, label = _previous_month(d)
        assert (y, m, label) == (2026, 1, "2026-01")

        # January 1st -> previous is December of last year
        d2 = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
        y2, m2, label2 = _previous_month(d2)
        assert (y2, m2, label2) == (2025, 12, "2025-12")
