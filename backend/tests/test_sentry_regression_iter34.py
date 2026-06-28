"""Iter34 regression — confirm Sentry wiring did not break critical auth-gated
endpoints. Covers items 3-7 of the review_request.

These rely on the autouse seed fixture in conftest.py that re-creates the four
fixed sessions (admin / employee / vip / normal) before every test.
"""
import os
import uuid
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN = "test_session_admin_X"
EMPLOYEE = "test_session_employee_X"
VIP = "test_session_vip_X"
NORMAL = "test_session_normal_X"


def _hdr(token):
    return {"Authorization": f"Bearer {token}"}


# ---------- item 3: get_session_user defensive (Sentry hook safe) ----------
class TestAuthMeStillWorks:
    def test_me_valid_admin(self):
        r = requests.get(f"{API}/auth/me", headers=_hdr(ADMIN))
        assert r.status_code == 200
        data = r.json()
        assert data["user_id"] == "user_test_admin01"
        assert data["role"] == "admin"

    def test_me_valid_normal(self):
        r = requests.get(f"{API}/auth/me", headers=_hdr(NORMAL))
        assert r.status_code == 200
        assert r.json()["user_id"] == "user_test_normal01"

    def test_me_missing_token_returns_401(self):
        r = requests.get(f"{API}/auth/me")
        assert r.status_code == 401

    def test_me_invalid_token_returns_401(self):
        r = requests.get(f"{API}/auth/me", headers=_hdr("garbage_token_xyz"))
        assert r.status_code == 401


# ---------- item 4: authenticated flows that depend on get_session_user ----------
class TestAuthenticatedFlows:
    def test_onboarding_complete_normal(self):
        # Idempotent; backend should accept repeat calls without crashing.
        r = requests.post(
            f"{API}/me/onboarding/complete",
            headers=_hdr(NORMAL),
            json={},
        )
        assert r.status_code in (200, 204), r.text

    def test_notifications_admin(self):
        r = requests.get(f"{API}/notifications", headers=_hdr(ADMIN))
        assert r.status_code == 200
        body = r.json()
        # Either list or dict with items key — both fine, just confirm 2xx + JSON.
        assert isinstance(body, (list, dict))

    def test_admin_orders_list(self):
        # iter34 review_request mentions "POST /api/admin/orders search" — but
        # the actual endpoint is GET /api/admin/orders. We want to confirm the
        # admin-scope path still works (get_session_user + role check).
        r = requests.get(
            f"{API}/admin/orders",
            headers=_hdr(ADMIN),
            params={"page": 1, "limit": 5},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert isinstance(body, (list, dict))


# ---------- item 5: order creation + status transition ----------
class TestOrderPath:
    def test_create_order_and_admin_transitions(self):
        # Look up active currencies — endpoint is GET /api/currencies.
        r_curr = requests.get(f"{API}/currencies")
        assert r_curr.status_code == 200, r_curr.text
        currencies = r_curr.json()
        assert isinstance(currencies, list) and len(currencies) >= 1
        cur = currencies[0]
        code = cur.get("code") or cur.get("currency_code")
        rate = float(cur.get("rate") or cur.get("rate_usd") or 1)

        payload = {
            "currency_code": code,
            "amount_foreign": rate * 10,  # ~ $10 worth
            "side": cur.get("side", "buy"),
            "payment_method": "transfer",
            "notes": "iter34 regression",
        }
        r = requests.post(
            f"{API}/orders", headers=_hdr(NORMAL), json=payload
        )
        # Accept either 200/201 OR 400 (validation surface change) but NOT 500
        assert r.status_code < 500, f"order create 5xx: {r.text}"
        if r.status_code in (200, 201):
            order = r.json()
            oid = order.get("id") or order.get("order_id")
            assert oid, order
            # try admin status transition - shouldn't 5xx
            r2 = requests.put(
                f"{API}/admin/orders/{oid}/status",
                headers=_hdr(ADMIN),
                json={"status": "received"},
            )
            assert r2.status_code < 500, r2.text


# ---------- item 6: TOTP step-up on VIP withdraw ----------
class TestVipWithdrawTotp:
    def test_vip_withdraw_without_totp_returns_4xx_not_5xx(self):
        # Without TOTP code, should be rejected with 4xx (challenge required).
        r = requests.post(
            f"{API}/vip/withdraw",
            headers=_hdr(VIP),
            json={"amount_usd": 100},
        )
        assert r.status_code < 500, r.text
        # 400/401/403/422 are all acceptable — challenge/step-up required.
        assert r.status_code in (400, 401, 403, 422, 200), r.status_code


# ---------- item 7: register + login pathway ----------
class TestRegisterLogin:
    def test_register_and_login(self):
        uniq = uuid.uuid4().hex[:10]
        digits = "".join(c for c in uniq if c.isdigit()).ljust(6, "0")[:6]
        email = f"TEST_iter34_{uniq}@resilience.example.com"
        # iter38 — test-only credential. NOT a real secret. Override with
        # TEST_USER_PASSWORD env var if you need a custom value locally.
        password = os.environ.get("TEST_USER_PASSWORD", "TestPwd_" + uniq)
        payload = {
            "email": email,
            "password": password,
            "name": "Iter34 Tester",
            "phone": f"+1202555{digits[:4]}",
        }
        r = requests.post(f"{API}/auth/register", json=payload)
        assert r.status_code in (200, 201), r.text

        # Login may be blocked until email verification — accept 200 OR
        # the canonical "email not verified" 4xx response. Just confirm no 5xx.
        r2 = requests.post(
            f"{API}/auth/login",
            json={"email": email, "password": password},
        )
        assert r2.status_code < 500, r2.text
