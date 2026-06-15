"""Iter10 — Tests for offset/limit pagination + X-Total-Count headers on:
- GET /api/admin/orders
- GET /api/admin/users
- GET /api/admin/users with `q` (search by name/email, case-insensitive)
"""
import pytest
import requests

from conftest import BASE_URL, ADMIN_TOKEN as ADMIN


def _h(t=None):
    h = {"Content-Type": "application/json"}
    if t:
        h["Authorization"] = f"Bearer {t}"
    return h


# ---------------- ORDERS PAGINATION ----------------
class TestAdminOrdersPagination:
    def test_headers_present(self):
        r = requests.get(f"{BASE_URL}/api/admin/orders",
                         headers=_h(ADMIN), params={"limit": 5, "offset": 0})
        assert r.status_code == 200
        assert "X-Total-Count" in r.headers
        assert int(r.headers["X-Offset"]) == 0
        assert int(r.headers["X-Limit"]) == 5
        assert isinstance(r.json(), list)
        assert len(r.json()) <= 5

    def test_offset_returns_different_page(self):
        first = requests.get(f"{BASE_URL}/api/admin/orders",
                             headers=_h(ADMIN), params={"limit": 5, "offset": 0})
        total = int(first.headers["X-Total-Count"])
        if total <= 5:
            pytest.skip(f"only {total} orders — cannot test offset")
        second = requests.get(f"{BASE_URL}/api/admin/orders",
                              headers=_h(ADMIN), params={"limit": 5, "offset": 5})
        assert second.status_code == 200
        ids1 = {o["id"] for o in first.json()}
        ids2 = {o["id"] for o in second.json()}
        assert ids1.isdisjoint(ids2), "orders pagination overlap"
        assert int(second.headers["X-Total-Count"]) == total

    def test_filter_status_combined_with_pagination(self):
        r = requests.get(f"{BASE_URL}/api/admin/orders",
                         headers=_h(ADMIN),
                         params={"status": "approved", "limit": 10, "offset": 0})
        assert r.status_code == 200
        for o in r.json():
            assert o["status"] == "approved"
        total_approved = int(r.headers["X-Total-Count"])
        # All-orders total must be >= approved-only total
        r_all = requests.get(f"{BASE_URL}/api/admin/orders",
                             headers=_h(ADMIN), params={"limit": 1, "offset": 0})
        assert int(r_all.headers["X-Total-Count"]) >= total_approved


# ---------------- USERS PAGINATION + SEARCH ----------------
class TestAdminUsersPagination:
    def test_headers_present(self):
        r = requests.get(f"{BASE_URL}/api/admin/users",
                         headers=_h(ADMIN), params={"limit": 5, "offset": 0})
        assert r.status_code == 200
        assert "X-Total-Count" in r.headers
        assert int(r.headers["X-Offset"]) == 0
        assert int(r.headers["X-Limit"]) == 5
        assert isinstance(r.json(), list)

    def test_offset_disjoint_pages(self):
        first = requests.get(f"{BASE_URL}/api/admin/users",
                             headers=_h(ADMIN), params={"limit": 2, "offset": 0})
        total = int(first.headers["X-Total-Count"])
        if total <= 2:
            pytest.skip(f"only {total} users — cannot test offset")
        second = requests.get(f"{BASE_URL}/api/admin/users",
                              headers=_h(ADMIN), params={"limit": 2, "offset": 2})
        ids1 = {u["user_id"] for u in first.json()}
        ids2 = {u["user_id"] for u in second.json()}
        assert ids1.isdisjoint(ids2)

    def test_search_by_email_case_insensitive(self):
        # The seeded admin email contains 'resilience'
        r = requests.get(f"{BASE_URL}/api/admin/users",
                         headers=_h(ADMIN), params={"q": "RESILIENCE", "limit": 50})
        assert r.status_code == 200
        users = r.json()
        assert len(users) >= 1
        for u in users:
            haystack = (u.get("email", "") + " " + u.get("name", "")).lower()
            assert "resilience" in haystack

    def test_search_no_match_returns_empty(self):
        r = requests.get(f"{BASE_URL}/api/admin/users",
                         headers=_h(ADMIN),
                         params={"q": "zzz_no_such_user_xyzqq", "limit": 50})
        assert r.status_code == 200
        assert r.json() == []
        assert int(r.headers["X-Total-Count"]) == 0
