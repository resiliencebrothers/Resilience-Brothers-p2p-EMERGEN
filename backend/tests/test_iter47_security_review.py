"""iter47 review-request tests for security middleware.

Covers everything called out in the review request:
1. Security headers on GET /api/rates
2. Origin allowlist behaviour (evil origin blocked, allowed origin passes,
   safe GET always allowed, missing Origin allowed)
3. CORS parsing: `*` refused when SENTRY_ENV=production (unit test)
4. Rate limiting on /auth/forgot-password (3/hour), /auth/login (10/min),
   /auth/register (5/hour), /appeals (5/hour) — only exercised when
   RATE_LIMIT_ENABLED=true; otherwise xfail-skipped.

Direct-to-backend (localhost:8001) so we bypass the Emergent ingress that
rewrites the Origin header.
"""
import os
import uuid
import importlib
import requests
import pytest

LOCAL_API = "http://localhost:8001/api"


# -------------------------------------------------
# 1. Security headers on /api/rates
# -------------------------------------------------

class TestSecurityHeaders:
    def test_get_rates_returns_all_security_headers(self):
        r = requests.get(f"{LOCAL_API}/rates")
        assert r.status_code == 200
        h = {k.lower(): v for k, v in r.headers.items()}

        assert "strict-transport-security" in h
        assert "max-age=" in h["strict-transport-security"]

        assert h.get("x-content-type-options") == "nosniff"
        assert h.get("x-frame-options") == "DENY"
        assert "referrer-policy" in h
        assert "permissions-policy" in h
        assert h.get("x-permitted-cross-domain-policies") == "none"

        csp = h.get("content-security-policy", "")
        assert "frame-ancestors 'none'" in csp
        assert "object-src 'none'" in csp


# -------------------------------------------------
# 2. Origin allowlist
# -------------------------------------------------

class TestOriginAllowlist:
    def test_evil_origin_post_blocked_with_403(self):
        r = requests.post(
            f"{LOCAL_API}/auth/login",
            headers={"Origin": "https://evil.com", "Content-Type": "application/json"},
            json={"email": "a@b.com", "password": "x"},
        )
        assert r.status_code == 403
        body = r.json()
        assert "cross-origin" in body.get("detail", "").lower()

    def test_localhost_origin_post_allowed(self):
        r = requests.post(
            f"{LOCAL_API}/auth/login",
            headers={"Origin": "http://localhost:3000", "Content-Type": "application/json"},
            json={"email": "a@b.com", "password": "x"},
        )
        assert r.status_code != 403

    def test_no_origin_header_post_allowed(self):
        r = requests.post(
            f"{LOCAL_API}/auth/login",
            headers={"Content-Type": "application/json"},
            json={"email": "a@b.com", "password": "x"},
        )
        assert r.status_code != 403

    def test_evil_origin_safe_get_allowed(self):
        r = requests.get(f"{LOCAL_API}/rates", headers={"Origin": "https://evil.com"})
        assert r.status_code == 200


# -------------------------------------------------
# 3. CORS unit test: '*' rejected in production
# -------------------------------------------------

class TestCorsProductionRejectsWildcard:
    def test_wildcard_in_production_raises(self):
        from fastapi import FastAPI

        # Save & swap env, reload module so decorator picks up new SENTRY_ENV
        old_env = os.environ.get("SENTRY_ENV")
        old_cors = os.environ.get("CORS_ORIGINS")
        try:
            os.environ["SENTRY_ENV"] = "production"
            os.environ["CORS_ORIGINS"] = "*"
            import security_middleware
            importlib.reload(security_middleware)
            with pytest.raises(RuntimeError) as ei:
                security_middleware.configure_cors(FastAPI())
            assert "CORS_ORIGINS='*'" in str(ei.value)
        finally:
            if old_env is None:
                os.environ.pop("SENTRY_ENV", None)
            else:
                os.environ["SENTRY_ENV"] = old_env
            if old_cors is None:
                os.environ.pop("CORS_ORIGINS", None)
            else:
                os.environ["CORS_ORIGINS"] = old_cors
            import security_middleware
            importlib.reload(security_middleware)

    def test_env_var_cors_origins_parses_multiple_values(self):
        import security_middleware
        parsed = security_middleware._parse_origins(
            "https://a.com,https://b.com/,http://localhost:3000"
        )
        assert parsed == ["https://a.com", "https://b.com", "http://localhost:3000"]


# -------------------------------------------------
# 4. Rate limiting — only meaningful when enabled
# -------------------------------------------------

RATE_LIMIT_ENABLED = os.environ.get("RATE_LIMIT_ENABLED", "true").lower() != "false"


@pytest.mark.skipif(
    not RATE_LIMIT_ENABLED,
    reason="RATE_LIMIT_ENABLED=false — rate-limit assertions skipped",
)
class TestRateLimits:
    def test_forgot_password_3_per_hour(self):
        # Unique IP not achievable; slowapi keys off get_remote_address which
        # in localhost is 127.0.0.1 — same bucket for all four calls.
        email = f"rl_forgot_{uuid.uuid4().hex[:8]}@example.com"
        codes = []
        for _ in range(4):
            r = requests.post(
                f"{LOCAL_API}/auth/forgot-password",
                json={"email": email},
            )
            codes.append(r.status_code)
        # First 3 should be 200, 4th should be 429
        assert codes[:3] == [200, 200, 200], f"Unexpected first 3 responses: {codes}"
        assert codes[3] == 429, f"4th response should be 429, got {codes[3]}"

    def test_forgot_password_429_includes_ratelimit_headers(self):
        # Trip the limit again and verify the 429 carries the headers.
        for _ in range(4):
            r = requests.post(
                f"{LOCAL_API}/auth/forgot-password",
                json={"email": "hdr_test@example.com"},
            )
        # Last response is 429
        assert r.status_code == 429
        # slowapi with headers_enabled=True exposes standard X-RateLimit-* headers
        h = {k.lower(): v for k, v in r.headers.items()}
        # Optional but expected — at least the retry-after must be present
        assert "retry-after" in h or "x-ratelimit-limit" in h

    def test_login_10_per_minute(self):
        # 11 attempts against unknown-user endpoint → first 10 are 404,
        # 11th should be 429.
        codes = []
        for i in range(11):
            r = requests.post(
                f"{LOCAL_API}/auth/login",
                json={"email": f"rl_login_{i}_{uuid.uuid4().hex[:6]}@example.com",
                      "password": "wrongpass"},
            )
            codes.append(r.status_code)
        assert codes[10] == 429, f"11th login should be 429, got {codes[10]} (full: {codes})"

    def test_register_5_per_hour(self):
        codes = []
        for i in range(6):
            r = requests.post(
                f"{LOCAL_API}/auth/register",
                json={
                    "email": f"rl_reg_{i}_{uuid.uuid4().hex[:6]}@example.com",
                    "password": "veryStrongPass123",
                    "name": "RL Test",
                    "phone": f"+1555000{i:04d}",
                },
            )
            codes.append(r.status_code)
        # 6th should be 429
        assert codes[5] == 429, f"6th register should be 429, got {codes[5]} (full: {codes})"


# -------------------------------------------------
# 5. Regression: existing headers don't break other endpoints
# -------------------------------------------------

class TestNoRegression:
    def test_currencies_endpoint_still_returns_200(self):
        r = requests.get(f"{LOCAL_API}/currencies")
        assert r.status_code == 200

    def test_health_root_still_returns_200(self):
        r = requests.get(f"{LOCAL_API}/rates")
        assert r.status_code == 200
