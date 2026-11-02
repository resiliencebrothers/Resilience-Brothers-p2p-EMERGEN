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
        # Legacy confirmed EUR transfer deposit WITHOUT any collection account
        # recorded (the "50 EUR" historical case). Used by the assign flow.
        await db.deposits.update_one(
            {"id": "dep_legacy_test02"},
            {"$set": {
                "id": "dep_legacy_test02", "user_id": "user_test_normal01",
                "user_email": "normal.test@resilience.com", "user_name": "QA Normal",
                "user_role": "normal", "currency": "EUR", "amount": 50.0,
                "method": "transfer", "account_holder": "TEST_legacy",
                "status": "confirmed", "created_at": "2026-02-01T00:00:00+00:00",
                "updated_at": "2026-02-01T00:00:00+00:00",
                "reviewed_at": "2026-02-01T00:00:00+00:00"},
             "$unset": {"payment_account_id": "", "payment_account_label": "",
                        "payment_account_details": "", "confirmed_account_id": "",
                        "confirmed_account_label": "", "credit_pending": ""}},
            upsert=True)
        # CO-01 — two USDT accounts on DIFFERENT networks + a confirmed crypto
        # deposit sent via TRC20, to test network-aware confirmed-account assign.
        await db.payment_accounts.delete_many({"id": {"$in": ["pa_usdt_trc", "pa_usdt_erc"]}})
        await db.payment_accounts.insert_many([
            {"id": "pa_usdt_trc", "currency_code": "USDT", "label": "Wallet TRC20",
             "account_details": "TRC20-addr", "network": "TRC20", "min_amount": 1,
             "max_amount": None, "is_active": True,
             "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00"},
            {"id": "pa_usdt_erc", "currency_code": "USDT", "label": "Wallet ERC20",
             "account_details": "0x-addr", "network": "ERC20", "min_amount": 1,
             "max_amount": None, "is_active": True,
             "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00"},
            # R-01 — cuenta ESTRUCTURADA pero SIN red: no debe aceptarse para cripto.
            {"id": "pa_usdt_nonet", "currency_code": "USDT", "label": "Wallet sin red",
             "account_details": "addr-sin-red", "network": "", "min_amount": 1,
             "max_amount": None, "is_active": True,
             "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00"}])
        await db.deposits.update_one(
            {"id": "dep_crypto_trc_test"},
            {"$set": {
                "id": "dep_crypto_trc_test", "user_id": "user_test_normal01",
                "user_email": "normal.test@resilience.com", "user_name": "QA Normal",
                "user_role": "normal", "currency": "USDT", "amount": 50.0,
                "method": "crypto", "network": "TRC20", "tx_hash": "0xdeadbeefTRC20test",
                "status": "confirmed", "created_at": "2026-02-02T00:00:00+00:00",
                "updated_at": "2026-02-02T00:00:00+00:00",
                "reviewed_at": "2026-02-02T00:00:00+00:00"},
             "$unset": {"payment_account_id": "", "confirmed_account_id": "",
                        "confirmed_account_label": "", "credit_pending": ""}},
            upsert=True)
    _db_run(_seed)
    yield
    async def _clean(db):
        await db.payment_accounts.delete_many({"id": {"$in": ["pa_test_eur_a", "pa_test_eur_b",
                                                              "pa_usdt_trc", "pa_usdt_erc",
                                                              "pa_usdt_nonet"]}})
        if CREATED:
            await db.deposits.delete_many({"id": {"$in": CREATED}})
        await db.deposits.delete_one({"id": "dep_legacy_test02"})
        await db.deposits.delete_one({"id": "dep_crypto_trc_test"})
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
        # CO-02 — asignar registra la cuenta CONFIRMADA (conciliada), no la prevista.
        r = requests.put(f"{API}/admin/deposits/dep_legacy_test02/payment-account",
                         json={"payment_account_id": "pa_test_eur_a",
                               "note": "conciliado extracto #42"}, headers=ADMIN)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["confirmed_account_label"] == "Revolut RB Europe"
        assert d["confirmed_account_id"] == "pa_test_eur_a"
        assert d["confirmed_account_by_name"]
        assert d["confirmed_account_at"]
        # la cuenta PREVISTA del legado sigue vacía (no se deduce por importe).
        assert not d.get("payment_account_label")
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
        # CO-02 — la cuenta confirmada aparece y queda marcada como verificada.
        assert row["confirmed_account_label"] == "Revolut RB Europe"
        assert row["account_verified"] is True
        assert row["credited_to"] == "EUR balance"
        assert row["generates_margin"] is False
        # P4 — identificadores estables presentes.
        assert "client_user_id" in row and "payment_account_id" in row


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


# CO-01 — network-aware confirmed-account assignment for crypto deposits
class TestCryptoNetworkAssign:
    def test_assign_wrong_network_422(self):
        # deposit was received via TRC20; assigning an ERC20 account must fail.
        r = requests.put(f"{API}/admin/deposits/dep_crypto_trc_test/payment-account",
                         json={"payment_account_id": "pa_usdt_erc"}, headers=ADMIN)
        assert r.status_code == 422, r.text
        assert "red" in r.json()["detail"].lower()

    def test_assign_right_network_200(self):
        r = requests.put(f"{API}/admin/deposits/dep_crypto_trc_test/payment-account",
                         json={"payment_account_id": "pa_usdt_trc"}, headers=ADMIN)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["confirmed_account_id"] == "pa_usdt_trc"
        assert d["confirmed_account_network"] == "TRC20"

    def test_resolve_endpoint_network_filter(self):
        # same amount, two networks → each returns ITS account, never the other.
        trc = requests.get(f"{API}/payment-accounts/resolve",
                           params={"currency": "USDT", "amount": 50, "network": "TRC20"},
                           headers=NORMAL).json()
        erc = requests.get(f"{API}/payment-accounts/resolve",
                           params={"currency": "USDT", "amount": 50, "network": "ERC20"},
                           headers=NORMAL).json()
        bep = requests.get(f"{API}/payment-accounts/resolve",
                           params={"currency": "USDT", "amount": 50, "network": "BEP20"},
                           headers=NORMAL).json()
        assert trc["account"]["id"] == "pa_usdt_trc"
        assert erc["account"]["id"] == "pa_usdt_erc"
        assert bep["account"] is None and bep["network_available"] is False


# CO-03 — confirmed deposit still awaiting the balance credit shows 'pending'
class TestCreditPendingStatus:
    def test_credit_pending_surfaced(self):
        async def _mark(db):
            await db.deposits.update_one(
                {"id": "dep_crypto_trc_test"},
                {"$set": {"credit_pending": {"reason": "test", "at": "now"}}})
        _db_run(_mark)
        try:
            r = requests.get(f"{API}/admin/transactions",
                             params={"ref_type": "deposit", "currency": "USDT"}, headers=ADMIN)
            row = [i for i in r.json()["items"] if i["ref_id"] == "dep_crypto_trc_test"][0]
            assert row["credit_pending"] is True
            assert row["credit_status"] == "pending"
            assert row["credited_to"] == ""
        finally:
            async def _clear(db):
                await db.deposits.update_one({"id": "dep_crypto_trc_test"},
                                             {"$unset": {"credit_pending": ""}})
            _db_run(_clear)

    def test_credited_when_no_pending(self):
        r = requests.get(f"{API}/admin/transactions",
                         params={"ref_type": "deposit", "currency": "USDT"}, headers=ADMIN)
        row = [i for i in r.json()["items"] if i["ref_id"] == "dep_crypto_trc_test"][0]
        assert row["credit_pending"] is False
        assert row["credit_status"] == "credited"
        assert row["credited_to"] == "USDT balance"



# R-01 — red desconocida/ausente NO debe aceptarse para cripto en ninguna ruta
class TestR01NetworkStrict:
    def test_assign_legacy_rejected_for_crypto(self):
        # una cuenta legada (sin red) no es válida para un depósito cripto.
        r = requests.put(f"{API}/admin/deposits/dep_crypto_trc_test/payment-account",
                         json={"payment_account_id": "legacy_USDT"}, headers=ADMIN)
        assert r.status_code == 422, r.text
        assert "red" in r.json()["detail"].lower()

    def test_assign_account_without_network_rejected(self):
        # cuenta estructurada SIN red definida → rechazo para cripto.
        r = requests.put(f"{API}/admin/deposits/dep_crypto_trc_test/payment-account",
                         json={"payment_account_id": "pa_usdt_nonet"}, headers=ADMIN)
        assert r.status_code == 422, r.text
        assert "red" in r.json()["detail"].lower()

    def test_assign_right_network_still_ok(self):
        r = requests.put(f"{API}/admin/deposits/dep_crypto_trc_test/payment-account",
                         json={"payment_account_id": "pa_usdt_trc"}, headers=ADMIN)
        assert r.status_code == 200, r.text
        assert r.json()["confirmed_account_network"] == "TRC20"

    def test_options_crypto_filtered_by_network(self):
        # el selector de cuentas para un depósito cripto TRC20 solo ofrece TRC20
        # (ni ERC20, ni la cuenta sin red, ni la legada).
        r = requests.get(f"{API}/admin/deposits/payment-account-options",
                         params={"currency": "USDT", "method": "crypto", "network": "TRC20"},
                         headers=ADMIN)
        assert r.status_code == 200
        ids = {o["id"] for o in r.json()["items"]}
        assert "pa_usdt_trc" in ids
        assert "pa_usdt_erc" not in ids
        assert "pa_usdt_nonet" not in ids
        assert not any(str(i).startswith("legacy_") for i in ids)


# R-02 — depósito localizable por ID (enlace exacto desde Transacciones)
class TestR02DepositById:
    def test_get_deposit_by_id_ok(self):
        r = requests.get(f"{API}/admin/deposits/dep_crypto_trc_test", headers=ADMIN)
        assert r.status_code == 200, r.text
        assert r.json()["id"] == "dep_crypto_trc_test"
        assert "_id" not in r.json()

    def test_get_deposit_by_id_404(self):
        r = requests.get(f"{API}/admin/deposits/nope_does_not_exist", headers=ADMIN)
        assert r.status_code == 404

    def test_get_deposit_by_id_requires_auth(self):
        assert requests.get(f"{API}/admin/deposits/dep_crypto_trc_test").status_code == 401
