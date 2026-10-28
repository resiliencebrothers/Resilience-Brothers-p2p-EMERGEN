"""Conciliación entre cajas (auditoría) — el ESPEJO (`box_mirror_diff`) debe
comparar conjuntos ALINEADOS: la caja FÍSICA del sistema (Fondo Resilience, vía
`cash_box_movements`) contra SU PROPIA cuenta contable
(`system_purpose=company_cash`), NO contra la suma de TODAS las cuentas de
efectivo de la moneda.

Antes, `box_mirror_diff = box − box_physical` sumaba todas las cuentas de caja en
`box` pero `box_physical` era solo la caja del sistema: con varias cuentas/cajas
físicas en la misma moneda aparecía una diferencia FALSA aunque la caja del
sistema estuviera correcta. Esta prueba fija el contrato: añadir efectivo a una
cuenta de caja que NO es la del sistema sube el TOTAL `box` pero NO mueve el
espejo.
"""
import os

import pytest
from pymongo import MongoClient

from services import courier_cash as cc

_ACC_ID = "facc_recontest_other"
_ADJ_ID = "cfa_recontest_other"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


async def _currency() -> str:
    curs = sorted(await cc.physical_cash_currencies())
    assert curs, "debe haber al menos una moneda de efectivo físico configurada"
    return curs[0]


def _row(rows, cur):
    r = next((x for x in rows if x["currency"] == cur), None)
    assert r is not None, f"falta la fila de conciliación para {cur}"
    return r


@pytest.fixture
def _clean():
    db = _db()
    db.fund_accounts.delete_many({"id": _ACC_ID})
    db.company_fund_adjustments.delete_many({"id": _ADJ_ID})
    yield db
    db.fund_accounts.delete_many({"id": _ACC_ID})
    db.company_fund_adjustments.delete_many({"id": _ADJ_ID})


@pytest.mark.asyncio
async def test_other_cash_account_inflates_total_not_mirror(_clean):
    db = _clean
    cur = await _currency()
    r0 = _row(await cc.reconciliation_by_currency(), cur)
    box0 = r0["box"]
    mirror0 = r0["box_mirror_diff"]
    assert "box_system_ledger" in r0  # campo de alcance alineado presente

    # Cuenta de efectivo NO-sistema, no-custodia, misma moneda, con saldo
    # contable Y (vía ajuste de fondo).
    Y = 123456.0
    db.fund_accounts.insert_one({
        "id": _ACC_ID, "name": "Recon test other box",
        "currency": cur, "method": "cash", "is_active": True})
    db.company_fund_adjustments.insert_one({
        "id": _ADJ_ID, "account_id": _ACC_ID, "currency": cur,
        "amount": Y, "adjustment_type": "inflow"})

    r1 = _row(await cc.reconciliation_by_currency(), cur)
    # 1) El TOTAL contable sube con la otra cuenta (sigue contando en `box`).
    assert round(r1["box"] - box0, 2) == Y
    # 2) El ESPEJO NO cambia: la otra cuenta no produce un descuadre falso.
    assert r1["box_mirror_diff"] == mirror0


@pytest.mark.asyncio
async def test_mirror_diff_scoped_to_system_box_only(_clean):
    db = _clean
    cur = await _currency()
    # Si hay cuenta del sistema, el espejo es un número y se mide contra
    # box_system_ledger (no contra el total `box`).
    r = _row(await cc.reconciliation_by_currency(), cur)
    if r["box_mirror_diff"] is not None:
        assert r["box_physical"] is not None
        assert r["box_system_ledger"] is not None
        assert round(r["box_system_ledger"] - r["box_physical"], 2) \
            == r["box_mirror_diff"]
