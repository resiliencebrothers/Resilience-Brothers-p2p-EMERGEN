"""iter384 — Deposit collection-account snapshot, admin assign, Transacciones origen/ref_type filter."""
import asyncio
import os

import pytest
import requests
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv("/app/backend/.env")
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"
ADMIN = {"Cookie": "session_token=test_session_admin_X"}
EMPLOYEE = {"Cookie": "session_token=test_session_employee_X"}
NORMAL = {"Cookie": "session_token=test_session_normal_X"}
PNG = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")
CREATED = []


def _db_run(coro_fn):
    async def _go():
        c = AsyncIOMotorClient(os.environ["MONGO_URL"])
        try:
            return await coro_fn(c[os.environ["DB_NAME"]])
        finally:
            c.close()
    return asyncio.run(_go())


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    # conftest stashes ALL payment_accounts at session start → re-plant ours for this module
    async def _seed(db):
        await db.payment_accounts.delete_many({"id": {"$in": ["pa_test_eur_a", "pa_test_eur_b"]}})
        await db.payment_accounts.insert_many([
            {"id": "pa_test_eur_a", "currency_code": "EUR", "label": "Revolut RB Europe",
             "account_details": "IBAN LT12 3456 7890 1234 5678\nTitular: RB Europe",
             "min_amount": 10, "max_amount": 200, "is_active": True,
             "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00"},
            {"id": "pa_test_eur_b", "currency_code": "EUR", "label": "BBVA Empresa",
             "account_details": "ES00 1111 2222 3333", "min_amount": 200.01, "max_amount": None,
             "is_active": True, "created_at": "2026-01-01T00:00:00+00:00",
             "updated_at": "2026-01-01T00:00:00+00:00"}])
    _db_run(_seed)
    yield
    async def _clean(db):
        await db.payment_accounts.delete_many({"id": {"$in": ["pa_test_eur_a", "pa_test_eur_b"]}})
        if CREATED:
            await db.deposits.delete_many({"id": {"$in": CREATED}})
        # restore dep_legacy_test02 to "no account" so UI assign flow can be tested
        await db.deposits.update_one({"id": "dep_legacy_test02"}, {"$unset": {
            "payment_account_id": "", "payment_account_label": "", "payment_account_details": ""}})
    _db_run(_clean)


def _create(amount):
    return requests.post(f"{API}/deposits", headers=NORMAL, json={
        "currency": "EUR", "amount": amount, "method": "transfer",
        "account_holder": "TEST_dayeiry", "proof_image": PNG})


# Client deposit snapshot of collection account (tiered)
class TestClientDepositSnapshot:
    def test_create_50_eur_snapshots_revolut(self):
        r = _create(50)
        assert r.status_code == 200, r.text
        d = r.json()
        CREATED.append(d["id"])
        assert d["payment_account_id"] == "pa_test_eur_a"
        assert d["payment_account_label"] == "Revolut RB Europe"
        assert "IBAN" in d["payment_account_details"]
        assert "_id" not in d

    def test_create_300_eur_snapshots_bbva(self):
        r = _create(300)
        assert r.status_code == 200, r.text
        d = r.json()
        CREATED.append(d["id"])
        assert d["payment_account_id"] == "pa_test_eur_b"
        assert d["payment_account_label"] == "BBVA Empresa"

    def test_create_5_eur_below_min(self):
        r = _create(5)
        assert r.status_code == 400
        assert r.json()["detail"].startswith("El monto mínimo para enviar EUR es 10")

    def test_mine_lists_snapshot(self):
        r = requests.get(f"{API}/deposits/mine", headers=NORMAL)
        assert r.status_code == 200
        mine = {d["id"]: d for d in r.json()["items"]}
        assert CREATED and mine[CREATED[0]]["payment_account_label"] == "Revolut RB Europe"

    def test_config_has_payment_account(self):
        r = requests.get(f"{API}/deposits/config", headers=NORMAL)
        assert r.status_code == 200
        eur = [c for c in r.json()["currencies"] if c["code"] == "EUR"]
        assert eur and "payment_account" in eur[0]
        assert isinstance(eur[0]["payment_account"], str)


# Admin options + assign endpoint
class TestAdminAssign:
    def test_options_admin(self):
        r = requests.get(f"{API}/admin/deposits/payment-account-options",
                         params={"currency": "EUR"}, headers=ADMIN)
        assert r.status_code == 200
        items = r.json()["items"]
        ids = [i["id"] for i in items]
        assert "pa_test_eur_a" in ids and "pa_test_eur_b" in ids
        for k in ("id", "label", "account_details", "network", "min_amount", "max_amount"):
            assert k in items[0]
        mins = [float(i["min_amount"] or 0) for i in items if i["min_amount"] is not None]
        assert mins == sorted(mins)

    def test_options_employee_forbidden(self):
        r = requests.get(f"{API}/admin/deposits/payment-account-options",
                         params={"currency": "EUR"}, headers=EMPLOYEE)
        assert r.status_code == 403

    def test_options_client_forbidden(self):
        r = requests.get(f"{API}/admin/deposits/payment-account-options",
                         params={"currency": "EUR"}, headers=NORMAL)
        assert r.status_code in (401, 403)

    def test_assign_legacy02(self):
        r = requests.put(f"{API}/admin/deposits/dep_legacy_test02/payment-account",
                         json={"payment_account_id": "pa_test_eur_a"}, headers=ADMIN)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["payment_account_label"] == "Revolut RB Europe"
        assert d["payment_account_id"] == "pa_test_eur_a"
        assert "_id" not in d

    def test_assign_unknown_404(self):
        r = requests.put(f"{API}/admin/deposits/dep_legacy_test02/payment-account",
                         json={"payment_account_id": "nope_xx"}, headers=ADMIN)
        assert r.status_code == 404

    def test_assign_unknown_deposit_404(self):
        r = requests.put(f"{API}/admin/deposits/dep_does_not_exist/payment-account",
                         json={"payment_account_id": "pa_test_eur_a"}, headers=ADMIN)
        assert r.status_code == 404

    def test_assign_cash_422(self):
        cash = _db_run(lambda db: db.deposits.find_one({"method": "cash"}, {"_id": 0, "id": 1}))
        if not cash:
            pytest.skip("no cash deposit in DB")
        r = requests.put(f"{API}/admin/deposits/{cash['id']}/payment-account",
                         json={"payment_account_id": "pa_test_eur_a"}, headers=ADMIN)
        assert r.status_code == 422

    def test_assign_empty_id_422(self):
        r = requests.put(f"{API}/admin/deposits/dep_legacy_test02/payment-account",
                         json={"payment_account_id": ""}, headers=ADMIN)
        assert r.status_code == 422

    def test_transactions_show_assigned(self):
        r = requests.get(f"{API}/admin/transactions",
                         params={"ref_type": "deposit", "currency": "EUR"}, headers=ADMIN)
        assert r.status_code == 200
        items = r.json()["items"]
        assert all(i["ref_type"] == "deposit" for i in items)
        row = [i for i in items if i["ref_id"] == "dep_legacy_test02"]
        assert row, "dep_legacy_test02 not in transactions"
        row = row[0]
        assert row["payment_account_label"] == "Revolut RB Europe"
        assert row["credited_to"] == "EUR balance"
        assert row["generates_margin"] is False


# Transactions ref_type filter + exports
class TestTransactionsFilters:
    def test_ref_type_orders(self):
        r = requests.get(f"{API}/admin/transactions",
                         params={"ref_type": "order,order_payout", "limit": 500}, headers=ADMIN)
        assert r.status_code == 200
        types = {i["ref_type"] for i in r.json()["items"]}
        assert types <= {"order", "order_payout"}
        assert r.headers.get("X-Total-Count") is not None

    def test_ref_type_total_count_consistent(self):
        all_r = requests.get(f"{API}/admin/transactions", headers=ADMIN)
        dep_r = requests.get(f"{API}/admin/transactions", params={"ref_type": "deposit"}, headers=ADMIN)
        ord_r = requests.get(f"{API}/admin/transactions",
                             params={"ref_type": "order,order_payout"}, headers=ADMIN)
        t_all = int(all_r.headers["X-Total-Count"])
        t_dep = int(dep_r.headers["X-Total-Count"])
        t_ord = int(ord_r.headers["X-Total-Count"])
        assert t_dep > 0 and t_dep + t_ord <= t_all
        assert {i["ref_type"] for i in dep_r.json()["items"]} == {"deposit"}

    def test_csv_payment_account_column(self):
        r = requests.get(f"{API}/admin/transactions/export.csv",
                         params={"ref_type": "deposit", "currency": "EUR"}, headers=ADMIN)
        assert r.status_code == 200
        lines = r.text.splitlines()
        assert lines[0].rstrip().strip('"').endswith("payment_account")
        assert any("dep_legacy_test02" in ln and "Revolut RB Europe" in ln for ln in lines)

    def test_pdf_export(self):
        r = requests.get(f"{API}/admin/transactions/export.pdf",
                         params={"ref_type": "deposit"}, headers=ADMIN)
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/pdf")
        assert r.content[:4] == b"%PDF"
