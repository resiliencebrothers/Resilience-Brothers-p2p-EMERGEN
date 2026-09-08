"""iter235 — Desglose de billetes por cuenta de efectivo del Fondo de Empresa
(ej. "Fondo Resilience" con 25M CUP) + billetes 2000/5000 en fondos.

Cubre:
- POST /admin/company-funds/accounts/{id}/denominations guarda el conteo,
  calcula total, diferencia vs balance del sistema y estado.
- Acepta billetes de 5000 y 2000 CUP (nuevos en CASH_DENOMINATIONS).
- Solo cuentas de efectivo (method=cash) → 400 para bancarias.
- Denominación inválida → 400; cuenta inexistente → 404.
- GET historial (más reciente primero) y snapshot en el breakdown.
- Cliente normal → 403.
"""
import os
import uuid

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, NORMAL_TOKEN, make_admin_totp

API = f"{BASE_URL}/api"
MARK = "ITER235TEST"


def _h(tok):
    return {"Content-Type": "application/json", "Authorization": f"Bearer {tok}"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _mk_cash_account(currency="CUP", method="cash"):
    db = _db()
    doc = {
        "id": f"facc_{MARK}_{uuid.uuid4().hex[:8]}",
        "name": f"{MARK} Caja",
        "currency": currency,
        "method": method,
        "is_active": True,
        "created_at": "2026-06-20T00:00:00+00:00",
    }
    db.fund_accounts.insert_one({**doc})
    return doc


def _seed_balance(account_id, currency, amount):
    """Ajuste inflow atribuido a la cuenta → balance del sistema."""
    db = _db()
    db.company_fund_adjustments.insert_one({
        "id": f"adj_{MARK}_{uuid.uuid4().hex[:8]}",
        "adjustment_type": "inflow",
        "currency": currency,
        "amount": float(amount),
        "account_id": account_id,
        "source_name": MARK,
        "created_at": "2026-06-20T00:00:00+00:00",
    })


class TestFundDenoms:
    def teardown_method(self, _):
        db = _db()
        ids = [a["id"] for a in db.fund_accounts.find({"name": {"$regex": f"^{MARK}"}})]
        db.fund_accounts.delete_many({"id": {"$in": ids}})
        db.fund_account_denoms.delete_many({"account_id": {"$in": ids}})
        db.company_fund_adjustments.delete_many({"source_name": MARK})

    def test_snapshot_with_5000_and_2000_bills(self):
        acc = _mk_cash_account()
        _seed_balance(acc["id"], "CUP", 25_000_000)
        # 25M = 4000×5000 + 2000×2000 + 1000×1000
        r = requests.post(
            f"{API}/admin/company-funds/accounts/{acc['id']}/denominations",
            headers=_h(ADMIN_TOKEN),
            json={"denominations": {"5000": 4000, "2000": 2000, "1000": 1000},
                  "note": "conteo bóveda"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total"] == 25_000_000.0
        assert body["system_balance"] == 25_000_000.0
        assert body["difference"] == 0
        assert body["status"] == "cuadrada"

    def test_snapshot_difference_faltante_alerts_admins(self):
        db = _db()
        acc = _mk_cash_account()
        _seed_balance(acc["id"], "CUP", 10_000)
        r = requests.post(
            f"{API}/admin/company-funds/accounts/{acc['id']}/denominations",
            headers=_h(ADMIN_TOKEN),
            json={"denominations": {"5000": 1, "2000": 2},
                  "note": "conteo vespertino"})
        assert r.status_code == 200, r.text
        assert r.json()["total"] == 9000.0
        assert r.json()["difference"] == -1000.0
        assert r.json()["status"] == "faltante"
        # iter236 — descuadre → campana a los admins con el detalle
        notif = db.notifications.find_one(
            {"type": "cash_count_mismatch",
             "data.snapshot_id": r.json()["id"]}, {"_id": 0})
        assert notif is not None
        assert "faltan 1,000.00 CUP" in notif["message"]
        assert "conteo vespertino" in notif["message"]
        db.notifications.delete_many({"type": "cash_count_mismatch",
                                      "data.account_id": acc["id"]})

    def test_squared_snapshot_does_not_alert(self):
        db = _db()
        acc = _mk_cash_account()
        _seed_balance(acc["id"], "CUP", 5000)
        r = requests.post(
            f"{API}/admin/company-funds/accounts/{acc['id']}/denominations",
            headers=_h(ADMIN_TOKEN), json={"denominations": {"5000": 1}})
        assert r.status_code == 200 and r.json()["status"] == "cuadrada"
        assert db.notifications.find_one(
            {"type": "cash_count_mismatch",
             "data.account_id": acc["id"]}) is None

    def test_history_and_breakdown_snapshot(self):
        acc = _mk_cash_account()
        for qty in (1, 2):
            requests.post(
                f"{API}/admin/company-funds/accounts/{acc['id']}/denominations",
                headers=_h(ADMIN_TOKEN),
                json={"denominations": {"1000": qty}})
        hist = requests.get(
            f"{API}/admin/company-funds/accounts/{acc['id']}/denominations",
            headers=_h(ADMIN_TOKEN)).json()
        assert len(hist) == 2
        assert hist[0]["total"] == 2000.0  # más reciente primero
        # snapshot visible en el breakdown de la moneda
        bd = requests.get(f"{API}/admin/company-funds/accounts/CUP",
                          headers=_h(ADMIN_TOKEN)).json()
        row = next(a for a in bd["accounts"] if a["id"] == acc["id"])
        assert row["denoms_snapshot"]["total"] == 2000.0

    def test_guards(self):
        bank = _mk_cash_account(method="bank")
        r = requests.post(
            f"{API}/admin/company-funds/accounts/{bank['id']}/denominations",
            headers=_h(ADMIN_TOKEN), json={"denominations": {"1000": 1}})
        assert r.status_code == 400  # solo efectivo

        cash = _mk_cash_account()
        r2 = requests.post(
            f"{API}/admin/company-funds/accounts/{cash['id']}/denominations",
            headers=_h(ADMIN_TOKEN), json={"denominations": {"7000": 1}})
        assert r2.status_code == 400  # denominación inválida

        r3 = requests.post(
            f"{API}/admin/company-funds/accounts/no_existe/denominations",
            headers=_h(ADMIN_TOKEN), json={"denominations": {"1000": 1}})
        assert r3.status_code == 404

        r4 = requests.post(
            f"{API}/admin/company-funds/accounts/{cash['id']}/denominations",
            headers=_h(NORMAL_TOKEN), json={"denominations": {"1000": 1}})
        assert r4.status_code == 403

    def test_adjustment_accepts_new_bills(self):
        # iter235 — los ajustes manuales de efectivo CUP aceptan 2000/5000.
        r = requests.post(f"{API}/admin/company-funds/adjustments",
                          headers=_h(ADMIN_TOKEN), json={
                              "adjustment_type": "inflow", "currency": "CUP",
                              "amount": 7000, "method": "cash",
                              "source_name": MARK, "note": "test billetes",
                              "totp_code": make_admin_totp(),
                              "denominations": {"5000": 1, "2000": 1}})
        assert r.status_code == 200, r.text
        _db().company_fund_adjustments.delete_many({"source_name": MARK})
