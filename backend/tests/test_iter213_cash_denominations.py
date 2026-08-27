"""iter213 — Ajustes manuales de capital con desglose de billetes
(formato Excel Control_de_Efectivo_CUP_USD) + verificación de la lógica
entrada suma / salida resta en el fondo por moneda.

Verifica:
1. Entrada cash CUP con denominaciones → guardada con desglose; el balance
   CUP del fondo SUBE exactamente el monto.
2. Salida cash CUP → balance BAJA; control físico neto correcto.
3. Validaciones: desglose obligatorio para cash CUP/USD, total debe
   coincidir con el monto, denominación inexistente rechazada.
4. GET /admin/company-funds/cash-denominations agrega billetes netos.
5. CSV export incluye la columna denominations.
"""
import os

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, with_totp_admin

API = f"{BASE_URL}/api"
MARK = "ITER213-TEST"


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _cleanup():
    _db().company_fund_adjustments.delete_many({"source_name": MARK})


def _fund_balance(code):
    r = requests.get(f"{API}/admin/company-funds", headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    row = next((x for x in r.json() if x["currency"] == code), None)
    return float(row["balance"]) if row else 0.0


def _adjust(body):
    return requests.post(f"{API}/admin/company-funds/adjustments",
                         headers=_hdr(ADMIN_TOKEN),
                         json=with_totp_admin(body))


def test_cash_inflow_outflow_updates_fund_balance_and_denoms():
    _cleanup()
    bal0 = _fund_balance("CUP")
    try:
        # 1) Entrada: 3×1000 + 2×500 + 5×100 = 4500 CUP
        r = _adjust({"adjustment_type": "inflow", "currency": "CUP",
                     "amount": 4500, "method": "cash", "source_name": MARK,
                     "denominations": {"1000": 3, "500": 2, "100": 5}})
        assert r.status_code == 200, r.text
        doc = r.json()
        assert doc["denominations"] == {"1000": 3, "500": 2, "100": 5}
        assert doc["account_label"], "efectivo debe caer en la caja"
        assert round(_fund_balance("CUP") - bal0, 2) == 4500.0, \
            "la ENTRADA debe SUMAR al fondo CUP"

        # 2) Salida: 1×1000 + 1×500 = 1500 CUP
        r = _adjust({"adjustment_type": "outflow", "currency": "CUP",
                     "amount": 1500, "method": "cash", "source_name": MARK,
                     "denominations": {"1000": 1, "500": 1}})
        assert r.status_code == 200, r.text
        assert round(_fund_balance("CUP") - bal0, 2) == 3000.0, \
            "la SALIDA debe RESTAR del fondo CUP"

        # 3) Control físico neto: 2×1000, 1×500, 5×100
        r = requests.get(f"{API}/admin/company-funds/cash-denominations",
                         headers=_hdr(ADMIN_TOKEN))
        assert r.status_code == 200, r.text
        cup = next((x for x in r.json() if x["currency"] == "CUP"), None)
        assert cup, "sin fila CUP en control físico"
        counts = {d["denomination"]: d["count"] for d in cup["denominations"]}
        # neto de ESTE test (otros ajustes previos no tienen denominaciones)
        assert counts.get(1000, 0) >= 2
        assert counts.get(500, 0) >= 1
        assert counts.get(100, 0) >= 5
        assert cup["total_value"] >= 3000.0
    finally:
        _cleanup()


def test_validations():
    _cleanup()
    try:
        # sin desglose en cash CUP → 400
        r = _adjust({"adjustment_type": "inflow", "currency": "CUP",
                     "amount": 1000, "method": "cash", "source_name": MARK})
        assert r.status_code == 400 and "desglose" in r.json()["detail"].lower()
        # total no coincide → 400
        r = _adjust({"adjustment_type": "inflow", "currency": "CUP",
                     "amount": 999, "method": "cash", "source_name": MARK,
                     "denominations": {"1000": 1}})
        assert r.status_code == 400 and "coincidir" in r.json()["detail"].lower()
        # denominación inexistente (7 CUP) → 400
        r = _adjust({"adjustment_type": "inflow", "currency": "CUP",
                     "amount": 7, "method": "cash", "source_name": MARK,
                     "denominations": {"7": 1}})
        assert r.status_code == 400 and "no existe" in r.json()["detail"].lower()
        # USD válido: 2×100 + 1×20 = 220
        r = _adjust({"adjustment_type": "inflow", "currency": "USD",
                     "amount": 220, "method": "cash", "source_name": MARK,
                     "denominations": {"100": 2, "20": 1}})
        assert r.status_code == 200, r.text
        # transferencia NO requiere desglose
        r = _adjust({"adjustment_type": "inflow", "currency": "CUP",
                     "amount": 800, "method": "transfer", "source_name": MARK,
                     "source_account": "0012345"})
        assert r.status_code == 200, r.text
    finally:
        _cleanup()


def test_csv_includes_denominations_column():
    _cleanup()
    try:
        r = _adjust({"adjustment_type": "inflow", "currency": "CUP",
                     "amount": 2000, "method": "cash", "source_name": MARK,
                     "denominations": {"1000": 2}})
        assert r.status_code == 200, r.text
        r = requests.get(f"{API}/admin/company-funds/export.csv",
                         headers=_hdr(ADMIN_TOKEN))
        assert r.status_code == 200
        text = r.content.decode("utf-8-sig")
        assert "denominations" in text.splitlines()[0]
        line = next((ln for ln in text.splitlines() if MARK in ln), "")
        assert "2×1000" in line, line
    finally:
        _cleanup()
