"""Tests for the daily/monthly revenue registry + CSV/PDF export (admin).

Verifies:
- GET /api/admin/revenue/timeseries returns day and month buckets with the expected shape
- granularity validation (rejects 'year')
- GET /api/admin/revenue/monthly/export returns CSV with UTF-8 BOM + header rows
- Returns PDF with %PDF magic bytes
- Only admin (not employee/normal) can access
"""
import os
import requests
import pytest

from conftest import BASE_URL, ADMIN_TOKEN, EMPLOYEE_TOKEN, NORMAL_TOKEN


def _h(t):
    return {"Authorization": f"Bearer {t}"}


class TestRevenueTimeseries:
    def test_daily_timeseries_shape(self):
        r = requests.get(
            f"{BASE_URL}/api/admin/revenue/timeseries",
            headers=_h(ADMIN_TOKEN),
            params={"granularity": "day", "days": 30},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["granularity"] == "day"
        assert isinstance(data["rows"], list)
        if data["rows"]:
            row = data["rows"][0]
            # YYYY-MM-DD for day granularity
            assert len(row["bucket"]) == 10 and row["bucket"][4] == "-" and row["bucket"][7] == "-"
            for k in ("p2p_profit_usdt", "marketplace_profit_usdt", "total_profit_usdt",
                      "orders", "deliveries", "volume_usdt"):
                assert k in row

    def test_monthly_timeseries_shape(self):
        r = requests.get(
            f"{BASE_URL}/api/admin/revenue/timeseries",
            headers=_h(ADMIN_TOKEN),
            params={"granularity": "month"},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["granularity"] == "month"
        if data["rows"]:
            # YYYY-MM for month granularity
            assert len(data["rows"][0]["bucket"]) == 7

    def test_invalid_granularity_rejected(self):
        r = requests.get(
            f"{BASE_URL}/api/admin/revenue/timeseries",
            headers=_h(ADMIN_TOKEN),
            params={"granularity": "year"},
        )
        assert r.status_code == 400

    def test_employee_forbidden(self):
        r = requests.get(
            f"{BASE_URL}/api/admin/revenue/timeseries",
            headers=_h(EMPLOYEE_TOKEN),
            params={"granularity": "day"},
        )
        # require_admin → 403 for employee
        assert r.status_code == 403

    def test_normal_user_unauthorized(self):
        r = requests.get(
            f"{BASE_URL}/api/admin/revenue/timeseries",
            headers=_h(NORMAL_TOKEN),
            params={"granularity": "day"},
        )
        assert r.status_code in (401, 403)


class TestMonthlyExport:
    def test_csv_export(self):
        r = requests.get(
            f"{BASE_URL}/api/admin/revenue/monthly/export",
            headers=_h(ADMIN_TOKEN),
            params={"year": 2026, "month": 2, "format": "csv"},
        )
        assert r.status_code == 200, r.text
        assert "text/csv" in r.headers["content-type"]
        assert "ganancia-2026-02.csv" in r.headers.get("content-disposition", "")
        body = r.content.decode("utf-8-sig")
        assert "RESILIENCE BROTHERS" in body
        assert "Período: 2026-02" in body
        # Header columns line
        assert "Fecha" in body and "Ganancia Total" in body

    def test_pdf_export(self):
        r = requests.get(
            f"{BASE_URL}/api/admin/revenue/monthly/export",
            headers=_h(ADMIN_TOKEN),
            params={"year": 2026, "month": 2, "format": "pdf"},
        )
        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "application/pdf"
        assert r.content[:4] == b"%PDF"
        assert "ganancia-2026-02.pdf" in r.headers.get("content-disposition", "")

    def test_invalid_month_rejected(self):
        r = requests.get(
            f"{BASE_URL}/api/admin/revenue/monthly/export",
            headers=_h(ADMIN_TOKEN),
            params={"year": 2026, "month": 13, "format": "csv"},
        )
        assert r.status_code == 400

    def test_invalid_format_rejected(self):
        r = requests.get(
            f"{BASE_URL}/api/admin/revenue/monthly/export",
            headers=_h(ADMIN_TOKEN),
            params={"year": 2026, "month": 2, "format": "xlsx"},
        )
        assert r.status_code == 400

    def test_employee_forbidden(self):
        r = requests.get(
            f"{BASE_URL}/api/admin/revenue/monthly/export",
            headers=_h(EMPLOYEE_TOKEN),
            params={"year": 2026, "month": 2, "format": "csv"},
        )
        assert r.status_code == 403
