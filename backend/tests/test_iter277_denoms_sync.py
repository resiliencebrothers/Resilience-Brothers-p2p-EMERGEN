"""iter277 — Sincronización caja física ↔ desglose por cuenta.

Cubre los 3 reportes del operador:
1. «Caja física por denominación» = suma del estado canónico de TODAS las
   cuentas de efectivo (conteo base ± movimientos con desglose), no solo los
   ajustes manuales.
2. Un retiro/depósito con desglose ACTUALIZA los billetes derivados de la
   cuenta: al reabrir el desglose ya no aparece la diferencia fantasma.
3. Transferencias entre cuentas y retiros de empresa pagados en efectivo
   viajan con su desglose de billetes.
Además: denominaciones configurables (añadir billetes nuevos, ej. 10000 CUP).
"""
import uuid
import os
from datetime import datetime, timedelta, timezone

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, NORMAL_TOKEN, make_admin_totp

API = f"{BASE_URL}/api"
MARK = "ITER277"


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _iso(minutes_ago=0):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


def _cleanup():
    db = _db()
    acc_ids = [a["id"] for a in db.fund_accounts.find(
        {"name": {"$regex": MARK}}, {"id": 1})]
    db.fund_accounts.delete_many({"id": {"$in": acc_ids}})
    db.fund_account_denoms.delete_many({"account_id": {"$in": acc_ids}})
    db.company_fund_adjustments.delete_many({"source_name": {"$regex": MARK}})
    db.fund_account_transfers.delete_many({"note": {"$regex": MARK}})
    db.company_withdrawals.delete_many({"beneficiary": {"$regex": MARK}})
    db.cash_box_movements.delete_many({"concept": {"$regex": MARK}})
    db.app_settings.update_one({"key": "cash_denominations_extra"},
                               {"$pull": {"value.CUP": 7777}})


def _mk_account(name, currency="CUP", method="cash"):
    r = requests.post(f"{API}/admin/company-funds/accounts",
                      headers=_hdr(ADMIN_TOKEN),
                      json={"name": name, "currency": currency, "method": method})
    assert r.status_code == 200, r.text
    return r.json()


def _breakdown_row(currency, acc_id):
    r = requests.get(f"{API}/admin/company-funds/accounts/{currency}",
                     headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    return next((a for a in r.json()["accounts"] if a["id"] == acc_id), None)


def _summary_counts(currency):
    r = requests.get(f"{API}/admin/company-funds/cash-denominations",
                     headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    row = next((x for x in r.json() if x["currency"] == currency), None)
    if not row:
        return {}
    return {d["denomination"]: d["count"] for d in row["denominations"]}


def _insert_adj(db, acc, denoms, amount, adjustment_type, minutes_ago=0,
                currency=None, method="cash", account_id=None):
    doc = {
        "id": str(uuid.uuid4()),
        "adjustment_type": adjustment_type,
        "currency": currency or acc["currency"],
        "amount": float(amount), "method": method,
        "source_name": f"{MARK} operador", "source_account": "",
        "note": MARK,
        "account_id": acc["id"] if account_id is None else account_id,
        "account_label": acc.get("name", ""),
        "denominations": denoms,
        "actor_id": "admin", "actor_email": "", "actor_name": "Admin",
        "created_at": _iso(minutes_ago),
    }
    db.company_fund_adjustments.insert_one(doc)
    return doc


class TestDerivedDenoms:
    """Reportes 1 y 2: el desglose por cuenta se deriva del conteo base más
    los movimientos, y la caja física agrega TODAS las cuentas de efectivo."""

    def teardown_method(self, _):
        _cleanup()

    def test_outflow_with_bills_updates_current_state(self):
        """Escenario exacto del usuario: conteo guardado, retiro manual de
        1000 (5×200) → los billetes actuales restan los 5 de 200 y no queda
        diferencia fantasma; la caja física refleja la cuenta."""
        _cleanup()
        db = _db()
        before = _summary_counts("CUP")
        acc = _mk_account(f"{MARK} caja principal")
        # conteo base: 2×1000 + 10×200 = 4000 (hace 60 min)
        db.fund_account_denoms.insert_one({
            "id": f"fdnm_{uuid.uuid4().hex[:12]}", "account_id": acc["id"],
            "account_label": acc["name"], "currency": "CUP",
            "denominations": {"1000": 2, "200": 10}, "total": 4000.0,
            "system_balance": 4000.0, "difference": 0.0, "status": "cuadrada",
            "note": MARK, "created_at": _iso(60),
            "created_by_id": "admin", "created_by_name": "Admin"})
        # retiro manual de 1000 CUP en 5 billetes de 200 (hace 5 min)
        _insert_adj(db, acc, {"200": 5}, 1000, "outflow", minutes_ago=5)

        row = _breakdown_row("CUP", acc["id"])
        assert row and row.get("denoms_current"), "la cuenta expone el estado actual"
        cur = row["denoms_current"]
        assert cur["denominations"] == {"1000": 2, "200": 5}, \
            "los 5 billetes de 200 extraídos se restaron del conteo"
        assert cur["total"] == 3000.0

        after = _summary_counts("CUP")
        assert after.get(1000, 0) - before.get(1000, 0) == 2
        assert after.get(200, 0) - before.get(200, 0) == 5, \
            "la caja física quedó sincronizada con el desglose de la cuenta"

    def test_deposit_adds_bills(self):
        _cleanup()
        db = _db()
        acc = _mk_account(f"{MARK} caja dep")
        _insert_adj(db, acc, {"500": 4}, 2000, "inflow", minutes_ago=3)
        cur = _breakdown_row("CUP", acc["id"])["denoms_current"]
        assert cur["denominations"] == {"500": 4} and cur["total"] == 2000.0

    def test_new_count_supersedes_history(self):
        """Un conteo NUEVO manda: los movimientos anteriores al conteo no se
        re-aplican."""
        _cleanup()
        db = _db()
        acc = _mk_account(f"{MARK} caja conteo")
        _insert_adj(db, acc, {"100": 9}, 900, "inflow", minutes_ago=30)
        r = requests.post(
            f"{API}/admin/company-funds/accounts/{acc['id']}/denominations",
            headers=_hdr(ADMIN_TOKEN),
            json={"denominations": {"1000": 3}, "note": MARK})
        assert r.status_code == 200, r.text
        cur = _breakdown_row("CUP", acc["id"])["denoms_current"]
        assert cur["denominations"] == {"1000": 3}, \
            "el conteo nuevo reemplaza el histórico acumulado"

    def test_unattributed_cash_adjustment_counts_in_canonical_box(self):
        """Ajustes cash legados sin cuenta atribuida cuentan en la caja
        canónica de su moneda (USD para no interferir con CUP)."""
        _cleanup()
        db = _db()
        before = _summary_counts("USD")
        box = db.fund_accounts.find_one(
            {"system_purpose": "company_cash", "currency": "USD"}, {"_id": 0})
        if not box:
            import pytest
            pytest.skip("sin caja canónica USD en este entorno")
        fake = {"id": box["id"], "currency": "USD", "name": box.get("name", "")}
        _insert_adj(db, fake, {"2": 3}, 6, "inflow", minutes_ago=2,
                    currency="USD", account_id="")
        after = _summary_counts("USD")
        assert after.get(2, 0) - before.get(2, 0) == 3


class TestTransferBills:
    """Reporte del usuario: al mover dinero entre cuentas se dice QUÉ
    billetes se mueven y ambas cuentas quedan al día."""

    def teardown_method(self, _):
        _cleanup()

    def test_transfer_moves_bills_between_cash_accounts(self):
        _cleanup()
        db = _db()
        a = _mk_account(f"{MARK} caja A")
        b = _mk_account(f"{MARK} caja B")
        _insert_adj(db, a, {"1000": 5}, 5000, "inflow", minutes_ago=10)

        r = requests.post(
            f"{API}/admin/company-funds/accounts/transfer",
            headers=_hdr(ADMIN_TOKEN),
            json={"currency": "CUP", "from_account_id": a["id"],
                  "to_account_id": b["id"], "amount": 2000,
                  "denominations": {"1000": 2}, "note": MARK,
                  "totp_code": make_admin_totp()})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "confirmed"
        assert r.json().get("denominations") == {"1000": 2}

        cur_a = _breakdown_row("CUP", a["id"])["denoms_current"]
        cur_b = _breakdown_row("CUP", b["id"])["denoms_current"]
        assert cur_a["denominations"] == {"1000": 3}, "el origen restó los billetes"
        assert cur_b["denominations"] == {"1000": 2}, "el destino sumó los billetes"

    def test_transfer_bills_must_match_amount(self):
        _cleanup()
        db = _db()
        a = _mk_account(f"{MARK} caja C")
        b = _mk_account(f"{MARK} caja D")
        _insert_adj(db, a, {"1000": 5}, 5000, "inflow", minutes_ago=10)
        r = requests.post(
            f"{API}/admin/company-funds/accounts/transfer",
            headers=_hdr(ADMIN_TOKEN),
            json={"currency": "CUP", "from_account_id": a["id"],
                  "to_account_id": b["id"], "amount": 2000,
                  "denominations": {"1000": 1}, "note": MARK,
                  "totp_code": make_admin_totp()})
        assert r.status_code == 400, r.text
        assert "coincidir" in r.json()["detail"].lower()


class TestPaidWithdrawalBills:
    """Reporte 3: el retiro del fondo pagado en efectivo captura el desglose
    y resta los billetes de la cuenta de origen."""

    def teardown_method(self, _):
        _cleanup()

    def test_pay_cash_withdrawal_subtracts_bills(self):
        _cleanup()
        db = _db()
        acc = _mk_account(f"{MARK} caja pagos")
        _insert_adj(db, acc, {"100": 5}, 500, "inflow", minutes_ago=15)
        # respaldo del fondo global para poder crear el retiro
        big = _insert_adj(db, acc, None, 1_000_000, "inflow", minutes_ago=20,
                          method="transfer", account_id="")

        r = requests.post(
            f"{API}/admin/company-withdrawals", headers=_hdr(ADMIN_TOKEN),
            json={"amount": 300, "currency": "CUP",
                  "beneficiary": f"{MARK} proveedor", "concept": "servicio",
                  "totp_code": make_admin_totp()})
        assert r.status_code == 200, r.text
        cwid = r.json()["id"]

        # desglose que no cuadra → 400 y el retiro sigue pendiente
        bad = requests.put(
            f"{API}/admin/company-withdrawals/{cwid}/status",
            headers=_hdr(ADMIN_TOKEN),
            json={"status": "paid", "paid_from_account_id": acc["id"],
                  "denominations": {"100": 2}, "totp_code": make_admin_totp()})
        assert bad.status_code == 400, bad.text
        assert db.company_withdrawals.find_one(
            {"id": cwid}, {"_id": 0})["status"] == "pending"

        ok = requests.put(
            f"{API}/admin/company-withdrawals/{cwid}/status",
            headers=_hdr(ADMIN_TOKEN),
            json={"status": "paid", "paid_from_account_id": acc["id"],
                  "denominations": {"100": 3}, "totp_code": make_admin_totp()})
        assert ok.status_code == 200, ok.text
        cw = db.company_withdrawals.find_one({"id": cwid}, {"_id": 0})
        assert cw["status"] == "paid" and cw.get("denominations") == {"100": 3}

        cur = _breakdown_row("CUP", acc["id"])["denoms_current"]
        assert cur["denominations"] == {"100": 2}, \
            "los 3 billetes de 100 pagados salieron del estado de la cuenta"
        db.company_fund_adjustments.delete_one({"id": big["id"]})


class TestDenominationsConfig:
    """Denominaciones configurables: 2000/5000 existen y el admin puede
    añadir billetes nuevos que valen en todos los desgloses."""

    def teardown_method(self, _):
        _cleanup()

    def test_defaults_include_2000_and_5000(self):
        r = requests.get(f"{API}/admin/company-funds/denominations-config",
                         headers=_hdr(ADMIN_TOKEN))
        assert r.status_code == 200, r.text
        cfg = r.json()
        assert 5000 in cfg["CUP"] and 2000 in cfg["CUP"]
        assert 100 in cfg["USD"]

    def test_admin_can_add_new_denomination(self):
        _cleanup()
        r = requests.post(f"{API}/admin/company-funds/denominations-config",
                          headers=_hdr(ADMIN_TOKEN),
                          json={"currency": "CUP", "denomination": 7777})
        assert r.status_code == 200, r.text
        assert 7777 in r.json()["CUP"]
        # duplicada → 400
        dup = requests.post(f"{API}/admin/company-funds/denominations-config",
                            headers=_hdr(ADMIN_TOKEN),
                            json={"currency": "CUP", "denomination": 7777})
        assert dup.status_code == 400
        # un depósito con el billete nuevo se acepta
        acc = _mk_account(f"{MARK} caja nueva denom")
        adj = requests.post(
            f"{API}/admin/company-funds/adjustments", headers=_hdr(ADMIN_TOKEN),
            json={"adjustment_type": "inflow", "currency": "CUP",
                  "amount": 7777, "method": "cash",
                  "source_name": f"{MARK} socio",
                  "account_id": acc["id"],
                  "denominations": {"7777": 1},
                  "totp_code": make_admin_totp()})
        assert adj.status_code == 200, adj.text
        cur = _breakdown_row("CUP", acc["id"])["denoms_current"]
        assert cur["denominations"] == {"7777": 1}

    def test_non_admin_cannot_add_denomination(self):
        r = requests.post(f"{API}/admin/company-funds/denominations-config",
                          headers=_hdr(NORMAL_TOKEN),
                          json={"currency": "CUP", "denomination": 9999})
        assert r.status_code == 403

    def test_invalid_currency_rejected(self):
        r = requests.post(f"{API}/admin/company-funds/denominations-config",
                          headers=_hdr(ADMIN_TOKEN),
                          json={"currency": "EUR", "denomination": 500})
        assert r.status_code == 400
