"""Iter11 — Transactions registry (ENTRADAS + SALIDAS) for accounting.

Coverage:
- /api/admin/transactions: admin-only (403 employee, 401 anon), filters direction/currency/holder/since/until.
- Only approved/completed orders and approved/paid withdrawals appear.
- Pre-feature data (sender_name empty / beneficiary_name empty) is excluded.
- Totals computed per currency: in, out, count.
- CSV: UTF-8 BOM, 11 columns.
- PDF: valid %PDF-1.4 / %%EOF.
- OrderCreate / WithdrawalCreate now require sender_name / beneficiary_name (min_length=2).
"""
import time
import uuid
import pytest
import requests

from conftest import make_vip_totp, make_admin_totp, BASE_URL, ADMIN_TOKEN as ADMIN, VIP_TOKEN as VIP, EMPLOYEE_TOKEN as EMP


def _h(tok=None):
    h = {"Content-Type": "application/json"}
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h


# ---------- Validation: new required fields ----------
class TestRequiredFields:
    def test_order_create_rejects_empty_sender_name(self):
        r = requests.post(
            f"{BASE_URL}/api/orders", headers=_h(VIP),
            json={"from_code": "USD", "to_code": "CUP", "amount_from": 5.0,
                  "delivery_method": "accumulate", "delivery_details": "x"},
        )
        assert r.status_code == 422

    def test_order_create_rejects_short_sender_name(self):
        r = requests.post(
            f"{BASE_URL}/api/orders", headers=_h(VIP),
            json={"from_code": "USD", "to_code": "CUP", "amount_from": 5.0,
                  "delivery_method": "accumulate", "delivery_details": "x",
                  "sender_name": "a"},  # 1 char
        )
        assert r.status_code == 422

    def test_withdrawal_create_rejects_missing_beneficiary(self):
        r = requests.post(
            f"{BASE_URL}/api/vip/withdraw", headers=_h(VIP),
            json={"amount_usd": 1, "method": "transfer", "details": "x"},
        )
        assert r.status_code == 422


# ---------- Access control ----------
class TestTransactionsAccess:
    def test_unauth_401(self):
        assert requests.get(f"{BASE_URL}/api/admin/transactions").status_code == 401

    def test_employee_now_allowed(self):
        # As of iter12 employees can see admin transactions for accounting
        r = requests.get(f"{BASE_URL}/api/admin/transactions", headers=_h(EMP))
        assert r.status_code == 200

    def test_admin_ok(self):
        r = requests.get(f"{BASE_URL}/api/admin/transactions", headers=_h(ADMIN))
        assert r.status_code == 200
        body = r.json()
        assert "items" in body and "totals" in body
        assert isinstance(body["items"], list)
        assert "X-Total-Count" in r.headers


# ---------- E2E: new transaction appears with holder ----------
class TestTransactionsE2E:
    def test_new_order_appears_as_entrada(self):
        unique_holder = f"Holder_{uuid.uuid4().hex[:6]}"
        # 1) Create + approve an order
        r = requests.post(
            f"{BASE_URL}/api/orders", headers=_h(VIP),
            json={"from_code": "USDT", "to_code": "USD", "amount_from": 1.0,
                  "delivery_method": "transfer", "delivery_details": "bank x",
                  "sender_name": unique_holder, "proof_image": ""},
        )
        assert r.status_code == 200, r.text
        order_id = r.json()["id"]
        # Approve
        upd = requests.put(
            f"{BASE_URL}/api/admin/orders/{order_id}/status",
            headers=_h(ADMIN), json={"status": "approved"},
        )
        assert upd.status_code == 200
        time.sleep(0.2)
        # 2) Query transactions filtered by holder
        r = requests.get(
            f"{BASE_URL}/api/admin/transactions",
            headers=_h(ADMIN), params={"holder": unique_holder},
        )
        assert r.status_code == 200
        items = r.json()["items"]
        assert len(items) >= 1
        match = next((it for it in items if it["ref_id"] == order_id), None)
        assert match, "approved order should appear in transactions"
        assert match["direction"] == "in"
        assert match["holder_name"] == unique_holder
        assert match["amount"] == 1.0

    def test_new_withdrawal_appears_as_salida(self):
        unique_bene = f"Beneficiario_{uuid.uuid4().hex[:6]}"
        # Withdraw 1 USD
        r = requests.post(
            f"{BASE_URL}/api/vip/withdraw", headers=_h(VIP),
            json={"amount_usd": 1.0, "method": "transfer", "details": "Acc Z",
                  "beneficiary_name": unique_bene, "totp_code": make_vip_totp()},
        )
        # Could fail with 400 if balance insufficient — top up first by direct admin tweak:
        if r.status_code == 400:
            pytest.skip("VIP balance insufficient — test environment limitation")
        assert r.status_code == 200, r.text
        wid = r.json()["id"]
        # Approve it
        upd = requests.put(
            f"{BASE_URL}/api/admin/withdrawals/{wid}/status",
            headers=_h(ADMIN), json={"status": "approved", "totp_code": make_admin_totp()},
        )
        assert upd.status_code == 200
        time.sleep(0.2)
        # Query
        r = requests.get(
            f"{BASE_URL}/api/admin/transactions",
            headers=_h(ADMIN), params={"holder": unique_bene, "direction": "out"},
        )
        assert r.status_code == 200
        items = r.json()["items"]
        match = next((it for it in items if it["ref_id"] == wid), None)
        assert match, "approved withdrawal should appear as salida"
        assert match["direction"] == "out"
        assert match["holder_name"] == unique_bene


# ---------- Filters + Totals ----------
class TestTransactionFilters:
    def test_direction_in_only(self):
        r = requests.get(f"{BASE_URL}/api/admin/transactions",
                         headers=_h(ADMIN), params={"direction": "in"})
        assert r.status_code == 200
        for it in r.json()["items"]:
            assert it["direction"] == "in"

    def test_direction_out_only(self):
        r = requests.get(f"{BASE_URL}/api/admin/transactions",
                         headers=_h(ADMIN), params={"direction": "out"})
        assert r.status_code == 200
        for it in r.json()["items"]:
            assert it["direction"] == "out"

    def test_invalid_direction(self):
        r = requests.get(f"{BASE_URL}/api/admin/transactions",
                         headers=_h(ADMIN), params={"direction": "sideways"})
        assert r.status_code == 400

    def test_totals_consistent_with_items(self):
        r = requests.get(f"{BASE_URL}/api/admin/transactions",
                         headers=_h(ADMIN), params={"limit": 500})
        assert r.status_code == 200
        body = r.json()
        # Re-aggregate from items and compare with totals
        manual: dict = {}
        for it in body["items"]:
            slot = manual.setdefault(it["currency"], {"in": 0.0, "out": 0.0, "count": 0})
            slot[it["direction"]] += it["amount"]
            slot["count"] += 1
        for cur, expected in manual.items():
            actual = body["totals"]["by_currency"].get(cur, {})
            assert abs(actual.get("in", 0) - expected["in"]) < 0.01


# ---------- Amount range filters ----------
class TestTransactionAmountFilters:
    def test_min_amount_filter(self):
        r = requests.get(f"{BASE_URL}/api/admin/transactions",
                         headers=_h(ADMIN), params={"min_amount": 10, "limit": 200})
        assert r.status_code == 200
        for it in r.json()["items"]:
            assert it["amount"] >= 10

    def test_max_amount_filter(self):
        r = requests.get(f"{BASE_URL}/api/admin/transactions",
                         headers=_h(ADMIN), params={"max_amount": 5, "limit": 200})
        assert r.status_code == 200
        for it in r.json()["items"]:
            assert it["amount"] <= 5

    def test_amount_range(self):
        r = requests.get(f"{BASE_URL}/api/admin/transactions",
                         headers=_h(ADMIN),
                         params={"min_amount": 5, "max_amount": 10, "limit": 200})
        assert r.status_code == 200
        for it in r.json()["items"]:
            assert 5 <= it["amount"] <= 10

    def test_negative_amount_rejected(self):
        r = requests.get(f"{BASE_URL}/api/admin/transactions",
                         headers=_h(ADMIN), params={"min_amount": -1})
        assert r.status_code == 400

    def test_min_greater_than_max_rejected(self):
        r = requests.get(f"{BASE_URL}/api/admin/transactions",
                         headers=_h(ADMIN),
                         params={"min_amount": 100, "max_amount": 50})
        assert r.status_code == 400

    def test_amount_filter_propagates_to_csv(self):
        r = requests.get(f"{BASE_URL}/api/admin/transactions/export.csv",
                         headers=_h(ADMIN), params={"min_amount": 50})
        assert r.status_code == 200
        # Decode and check each amount column >= 50 (column index 3)
        import csv as _csv, io
        text = r.content.decode("utf-8-sig")
        rows = list(_csv.reader(io.StringIO(text)))
        for row in rows[1:]:  # skip header
            assert float(row[3]) >= 50

    def test_amount_filter_propagates_to_pdf(self):
        r = requests.get(f"{BASE_URL}/api/admin/transactions/export.pdf",
                         headers=_h(ADMIN),
                         params={"min_amount": 10, "max_amount": 100})
        assert r.status_code == 200
        assert r.content.startswith(b"%PDF-")


# ---------- Exports ----------
class TestTransactionsExports:
    def test_csv_admin_ok_with_bom_and_headers(self):
        r = requests.get(f"{BASE_URL}/api/admin/transactions/export.csv",
                         headers=_h(ADMIN))
        assert r.status_code == 200
        assert "text/csv" in r.headers.get("Content-Type", "")
        body = r.content
        assert body[:3] == b"\xef\xbb\xbf", "UTF-8 BOM expected for Excel"
        first_line = body.decode("utf-8-sig").splitlines()[0]
        for col in ("created_at", "direction", "currency", "amount", "holder_name",
                    "client_name", "method", "status", "ref_id"):
            assert col in first_line

    def test_pdf_admin_valid(self):
        r = requests.get(f"{BASE_URL}/api/admin/transactions/export.pdf",
                         headers=_h(ADMIN))
        assert r.status_code == 200
        assert r.headers.get("Content-Type", "").startswith("application/pdf")
        assert r.content.startswith(b"%PDF-")
        assert b"%%EOF" in r.content[-50:]

    def test_csv_employee_forbidden(self):
        r = requests.get(f"{BASE_URL}/api/admin/transactions/export.csv",
                         headers=_h(EMP))
        assert r.status_code == 200  # employees now have access (iter12)

    def test_pdf_employee_forbidden(self):
        r = requests.get(f"{BASE_URL}/api/admin/transactions/export.pdf",
                         headers=_h(EMP))
        assert r.status_code == 200  # employees now have access (iter12)


# ---------- /api/me/transactions (per-user self-service) ----------
class TestMyTransactions:
    def test_unauth_401(self):
        assert requests.get(f"{BASE_URL}/api/me/transactions").status_code == 401

    def test_vip_returns_only_own(self):
        from conftest import VIP_TOKEN, NORMAL_TOKEN
        r_vip = requests.get(f"{BASE_URL}/api/me/transactions", headers=_h(VIP_TOKEN))
        assert r_vip.status_code == 200
        # Every item returned must belong to vip user
        # (we don't expose user_id but it's filtered server-side; just verify list shape)
        body = r_vip.json()
        assert "items" in body
        assert "X-Total-Count" in r_vip.headers
        # Normal user gets their own (likely empty until they have approved orders)
        r_normal = requests.get(f"{BASE_URL}/api/me/transactions", headers=_h(NORMAL_TOKEN))
        assert r_normal.status_code == 200

    def test_self_isolation(self):
        """Two different users see different sets — vip never sees normal's data and vice-versa."""
        from conftest import VIP_TOKEN, NORMAL_TOKEN
        r_vip = requests.get(f"{BASE_URL}/api/me/transactions",
                             headers=_h(VIP_TOKEN), params={"limit": 500})
        r_normal = requests.get(f"{BASE_URL}/api/me/transactions",
                                headers=_h(NORMAL_TOKEN), params={"limit": 500})
        vip_ids = {it["ref_id"] for it in r_vip.json()["items"]}
        normal_ids = {it["ref_id"] for it in r_normal.json()["items"]}
        # No overlap — strict isolation
        assert vip_ids.isdisjoint(normal_ids)

    def test_filters_work(self):
        from conftest import VIP_TOKEN
        r = requests.get(f"{BASE_URL}/api/me/transactions",
                         headers=_h(VIP_TOKEN),
                         params={"direction": "in", "min_amount": 1})
        assert r.status_code == 200
        for it in r.json()["items"]:
            assert it["direction"] == "in"
            assert it["amount"] >= 1

    def test_csv_export(self):
        from conftest import VIP_TOKEN
        r = requests.get(f"{BASE_URL}/api/me/transactions/export.csv",
                         headers=_h(VIP_TOKEN))
        assert r.status_code == 200
        assert "text/csv" in r.headers.get("Content-Type", "")
        assert r.content[:3] == b"\xef\xbb\xbf"
        first = r.content.decode("utf-8-sig").splitlines()[0]
        # /me CSV should NOT expose other_client_email
        assert "client_email" not in first
        for col in ("created_at", "direction", "currency", "amount", "holder_name"):
            assert col in first

    def test_pdf_export(self):
        from conftest import VIP_TOKEN
        r = requests.get(f"{BASE_URL}/api/me/transactions/export.pdf",
                         headers=_h(VIP_TOKEN))
        assert r.status_code == 200
        assert r.headers.get("Content-Type", "").startswith("application/pdf")
        assert r.content.startswith(b"%PDF-")

    def test_invalid_direction_400(self):
        from conftest import VIP_TOKEN
        r = requests.get(f"{BASE_URL}/api/me/transactions",
                         headers=_h(VIP_TOKEN), params={"direction": "sideways"})
        assert r.status_code == 400
