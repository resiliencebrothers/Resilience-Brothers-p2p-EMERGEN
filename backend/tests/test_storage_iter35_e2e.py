"""End-to-end integration tests for iter35 R2 storage integration.

Covers items 1-11 of the iter35 review request:
- Backend boots with STORAGE_PROVIDER=r2 (openapi exposes /api/files/{key}).
- POST /api/orders persists base64 proof_image to R2 → /api/files/orders/<key>.
- GET /api/files/<key> ownership rules (owner 200, admin 200, other 403, anon 401).
- 404 on missing key, 400/404 on path-traversal attempts.
- Oversize (>8 MB) falls back to base64.
- Admin withdrawal `payout_proof_image` is uploaded to /api/files/withdrawals/...
- POST /api/admin/company-withdrawals `invoice_image` is uploaded to /api/files/company_invoices/...

Live tests target a real Cloudflare R2 bucket. Each test uploads a 68-byte PNG
(or a single small derivative) — total bucket writes per full run ≈ 4-5 objects.
"""
import base64
import os

import pytest
import requests

from conftest import (
    ADMIN_TOKEN, VIP_TOKEN, NORMAL_TOKEN, EMPLOYEE_TOKEN,
    make_admin_totp,
)

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")

PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c6300010000000500010d0a2db40000000049454e44ae426082"
)
PNG_1PX_DATA_URL = "data:image/png;base64," + base64.b64encode(PNG_1PX).decode("ascii")


def _h(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


def _mongo_db():
    from pymongo import MongoClient
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


# ---------- Item 1: boot + openapi ----------

class TestStorageBoot:
    def test_root_alive(self):
        r = requests.get(f"{BASE_URL}/api/", timeout=10)
        assert r.status_code == 200

    def test_openapi_exposes_files_route(self):
        # iter36 — OpenAPI schema moved under /api/openapi.json so the public
        # k8s ingress (which proxies /api/*) can reach it. 82 paths total
        # after iter37 (`/api/admin/health/summary` added on top of iter35's 81).
        # including /api/files/{key}.
        r = requests.get(f"{BASE_URL}/api/openapi.json", timeout=10)
        assert r.status_code == 200
        paths = r.json().get("paths", {})
        # iter52: added 2 balance-ledger endpoints → 87 paths.
        assert len(paths) == 106, f"expected 106 paths, got {len(paths)}"
        assert "/api/files/{key}" in paths, (
            f"/api/files/{{key}} missing. sample={list(paths.keys())[:6]}"
        )


# ---------- Items 2-7: orders upload + auth matrix ----------

@pytest.fixture(scope="module")
def created_order_with_proof():
    """POST /api/orders with base64 proof_image, return the order doc."""
    payload = {
        "from_code": "USD", "to_code": "CUP", "amount_from": 1.0,
        "delivery_method": "transfer", "delivery_details": "Bank xxx",
        "sender_name": "Iter35 E2E", "proof_image": PNG_1PX_DATA_URL,
    }
    r = requests.post(
        f"{BASE_URL}/api/orders", headers=_h(NORMAL_TOKEN), json=payload, timeout=20
    )
    assert r.status_code == 200, r.text
    return r.json()


class TestOrdersR2Upload:
    def test_proof_image_uploaded_to_storage(self, created_order_with_proof):
        order = created_order_with_proof
        proof = order.get("proof_image") or ""
        assert proof.startswith("/api/files/orders/"), (
            f"Expected R2 reference, got: {proof[:80]!r}"
        )
        assert proof.endswith(".png")
        assert not proof.startswith("data:")

    def test_mongo_persisted_reference(self, created_order_with_proof):
        doc = _mongo_db().orders.find_one(
            {"id": created_order_with_proof["id"]}, {"_id": 0, "proof_image": 1}
        )
        assert doc is not None
        assert doc["proof_image"] == created_order_with_proof["proof_image"]
        assert doc["proof_image"].startswith("/api/files/orders/")

    def test_owner_can_fetch_file(self, created_order_with_proof):
        key = created_order_with_proof["proof_image"].split("/api/files/", 1)[1]
        r = requests.get(
            f"{BASE_URL}/api/files/{key}", headers=_h(NORMAL_TOKEN), timeout=15
        )
        assert r.status_code == 200, r.text
        assert r.headers["content-type"].startswith("image/png")
        assert r.content == PNG_1PX

    def test_admin_can_fetch_any_file(self, created_order_with_proof):
        key = created_order_with_proof["proof_image"].split("/api/files/", 1)[1]
        r = requests.get(
            f"{BASE_URL}/api/files/{key}", headers=_h(ADMIN_TOKEN), timeout=15
        )
        assert r.status_code == 200
        assert r.content == PNG_1PX

    def test_employee_can_fetch_any_file(self, created_order_with_proof):
        """Employee role is also in the bypass list."""
        key = created_order_with_proof["proof_image"].split("/api/files/", 1)[1]
        r = requests.get(
            f"{BASE_URL}/api/files/{key}", headers=_h(EMPLOYEE_TOKEN), timeout=15
        )
        assert r.status_code == 200

    def test_other_non_admin_user_forbidden(self, created_order_with_proof):
        """VIP (different normal-tier user, not admin/employee) cannot see another user's file."""
        key = created_order_with_proof["proof_image"].split("/api/files/", 1)[1]
        r = requests.get(
            f"{BASE_URL}/api/files/{key}", headers=_h(VIP_TOKEN), timeout=15
        )
        assert r.status_code == 403, f"expected 403, got {r.status_code}: {r.text}"

    def test_unauthenticated_returns_401(self, created_order_with_proof):
        key = created_order_with_proof["proof_image"].split("/api/files/", 1)[1]
        r = requests.get(f"{BASE_URL}/api/files/{key}", timeout=15)
        assert r.status_code == 401, f"expected 401, got {r.status_code}: {r.text}"

    def test_missing_key_returns_404(self):
        # Authenticated admin (bypasses ownership) → access check passes,
        # storage layer returns None → handler returns 404 with the
        # expected Spanish detail.
        r = requests.get(
            f"{BASE_URL}/api/files/orders/2026/01/01/non-existent-uuid.png",
            headers=_h(ADMIN_TOKEN), timeout=15,
        )
        assert r.status_code == 404
        assert "Archivo no encontrado" in r.text


# ---------- Item 8: path traversal ----------

class TestPathTraversal:
    def test_path_traversal_blocked(self):
        # FastAPI normalises this to /api/files/something at the router level
        # which then either 404s (route mismatch) or 400s ("key inválida").
        # Either is acceptable — what matters is that no file bytes are served.
        r = requests.get(
            f"{BASE_URL}/api/files/../something",
            headers=_h(ADMIN_TOKEN), timeout=15,
            allow_redirects=False,
        )
        assert r.status_code in (400, 404), r.status_code
        # Make sure we didn't accidentally serve a real object
        assert "image/" not in r.headers.get("content-type", "")


# ---------- Item 9: oversize falls back to base64 ----------

class TestOversizeFallback:
    def test_oversize_proof_image_returns_413(self):
        """iter36 — oversize uploads must return HTTP 413 with PROOF_TOO_LARGE
        instead of silently keeping the base64 inline."""
        big_bytes = b"\x00" * (9 * 1024 * 1024)  # 9 MB > 8 MB hard limit
        big_url = "data:image/png;base64," + base64.b64encode(big_bytes).decode("ascii")
        payload = {
            "from_code": "USD", "to_code": "CUP", "amount_from": 1.0,
            "delivery_method": "transfer", "delivery_details": "x",
            "sender_name": "Big Proof", "proof_image": big_url,
        }
        r = requests.post(
            f"{BASE_URL}/api/orders", headers=_h(NORMAL_TOKEN), json=payload, timeout=60
        )
        assert r.status_code == 413, r.text
        body = r.json()
        # FastAPI nests the structured detail under "detail"
        detail = body.get("detail") or {}
        assert detail.get("code") == "PROOF_TOO_LARGE"
        assert detail.get("size_mb", 0) > 8
        assert detail.get("limit_mb") == 8


# ---------- Item 10: admin withdrawal payout_proof_image ----------

@pytest.fixture
def withdrawal_to_pay():
    """Create a pending USD withdrawal as VIP user, returns the withdrawal id."""
    from conftest import make_vip_totp
    totp = make_vip_totp()
    # Ensure VIP has USD balance ≥ 1 (test_credentials says 5000 — auto-seed
    # only sets totp; balance is set by the iter test harness in some flows.
    # We tolerate balance unavailable by creating via Mongo direct insert as
    # a fallback to keep the test focused on the storage angle).
    payload = {
        "amount_usd": 1.0, "currency": "USD", "method": "transfer",
        "details": "Acct 1234", "beneficiary_name": "Iter35 Beneficiary",
        "totp_code": totp,
    }
    r = requests.post(
        f"{BASE_URL}/api/vip/withdraw", headers=_h(VIP_TOKEN), json=payload, timeout=15
    )
    if r.status_code == 200:
        return r.json()["id"]
    # Fallback: direct DB insert so we can still test the admin endpoint.
    import uuid
    from datetime import datetime, timezone
    wid = str(uuid.uuid4())
    _mongo_db().withdrawals.insert_one({
        "id": wid, "user_id": "user_test_vip01",
        "user_email": "vip.test@resilience.com", "user_name": "VIP",
        "amount_usd": 1.0, "currency": "USD", "method": "transfer",
        "details": "Acct 1234", "beneficiary_name": "Iter35 Beneficiary",
        "status": "pending", "admin_note": "",
        "payout_proof_image": "", "payout_tx_hash": "",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return wid


class TestAdminWithdrawalProof:
    def test_payout_proof_uploaded_when_marking_paid(self, withdrawal_to_pay):
        wid = withdrawal_to_pay
        body = {
            "status": "paid", "admin_note": "test",
            "payout_proof_image": PNG_1PX_DATA_URL,
            "totp_code": make_admin_totp(),
        }
        r = requests.put(
            f"{BASE_URL}/api/admin/withdrawals/{wid}/status",
            headers=_h(ADMIN_TOKEN), json=body, timeout=20,
        )
        assert r.status_code == 200, r.text
        # Verify Mongo doc carries the storage reference (not the base64).
        doc = _mongo_db().withdrawals.find_one(
            {"id": wid}, {"_id": 0, "payout_proof_image": 1, "status": 1}
        )
        assert doc is not None
        assert doc["status"] == "paid"
        assert doc["payout_proof_image"].startswith("/api/files/withdrawals/")
        assert doc["payout_proof_image"].endswith(".png")
        # And the file is reachable by admin.
        key = doc["payout_proof_image"].split("/api/files/", 1)[1]
        rf = requests.get(
            f"{BASE_URL}/api/files/{key}", headers=_h(ADMIN_TOKEN), timeout=15
        )
        assert rf.status_code == 200
        assert rf.content == PNG_1PX


# ---------- Item 11: company-withdrawals invoice_image ----------

class TestCompanyWithdrawalInvoice:
    def test_invoice_image_uploaded(self):
        # Seed some company funds so the endpoint accepts amount=0.01 USD.
        # Approach: pick a small amount and accept that the endpoint may
        # reject for insufficient funds → if so, skip rather than fail (the
        # storage-helper side is exercised only when the request reaches
        # the persistence step).
        body = {
            "amount": 0.01, "currency": "USD",
            "beneficiary": "Iter35 Vendor", "concept": "iter35 storage e2e",
            "invoice_image": PNG_1PX_DATA_URL,
            "totp_code": make_admin_totp(),
        }
        r = requests.post(
            f"{BASE_URL}/api/admin/company-withdrawals",
            headers=_h(ADMIN_TOKEN), json=body, timeout=20,
        )
        if r.status_code == 400 and "Fondo insuficiente" in r.text:
            pytest.skip("No company funds available in this env — storage path not reached")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["invoice_image"].startswith("/api/files/company_invoices/"), (
            f"expected /api/files/company_invoices/..., got: {data['invoice_image'][:80]!r}"
        )
        # Verify the bucket actually has it (admin fetch).
        key = data["invoice_image"].split("/api/files/", 1)[1]
        rf = requests.get(
            f"{BASE_URL}/api/files/{key}", headers=_h(ADMIN_TOKEN), timeout=15
        )
        assert rf.status_code == 200
        assert rf.content == PNG_1PX
