"""iter304 — Extractos reales tipo Sabadell (.xls) en conciliación bancaria.

El extracto real del banco Sabadell fallaba con «LLM response has no JSON
array»: la cabecera está tras 8+ filas de metadatos (la ventana solo miraba
6), «F. Operativa» no estaba entre los sinónimos de fecha y no hay columna de
remitente (viene dentro del concepto: 'ABONO TRANSFERENCIA DE <NOMBRE>').
Correcciones: ventana de cabecera de 12 filas, sinónimos ES nuevos, extracción
del remitente desde el concepto y parseo NATIVO sin depender de la IA.
"""
import io
import os
import time
import uuid

import requests
from pymongo import MongoClient

from conftest import BASE_URL, ADMIN_TOKEN as ADMIN

API = f"{BASE_URL}/api"
MARK = "iter304sab"


def _h(t):
    return {"Authorization": f"Bearer {t}"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _run(coro):
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        loop.close()
        asyncio.set_event_loop(asyncio.new_event_loop())


_SABADELL_ROWS = [
    ["Consulta de movimiento", "", ""],
    ["13/09/2026 17:14:30", "", ""],
    ["Cuenta: ", "0081-5234-14-000172867", ""],
    ["Divisa: ", "EUR", ""],
    ["Titular:", "BASA TRAVEL AGENCY SL.", ""],
    ["Selección:", "Desde 01/09/2026 hasta 13/09/2026", ""],
    ["F. Operativa", "Concepto", "Importe"],
    ["14/09/2026", "ABONO TRANSFERENCIA DE JUAN PEREZ GOMEZ", 4211.37],
    ["14/09/2026", "ABONO TRANSFERENCIA DE Trustly Group AB", 3110.52],
    ["13/09/2026", "TRANSFERENCIA DE MARIA LOPEZ DIAZ", 2260.44],
    ["12/09/2026", "INGRESO EFECTIVO CAJERO AUTOMATICO 00815234", 1180.09],
    ["11/09/2026", "COMISIONES", -18],
]


def _build_xlsx() -> bytes:
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    for row in _SABADELL_ROWS:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _build_csv() -> bytes:
    lines = [";".join(str(c) for c in row) for row in _SABADELL_ROWS]
    return ("\n".join(lines)).encode()


class TestSenderFromConcept:
    def test_sender_extracted_from_spanish_concepts(self):
        from services.reconciliation_parser import sender_from_description
        assert sender_from_description(
            "ABONO TRANSFERENCIA DE JUAN PEREZ GOMEZ") == "JUAN PEREZ GOMEZ"
        assert sender_from_description(
            "TRANSFERENCIA INMEDIATA DE MARIA LOPEZ") == "MARIA LOPEZ"
        assert sender_from_description(
            "BIZUM DE PEDRO RUIZ") == "PEDRO RUIZ"
        assert sender_from_description("COMISIONES") is None
        assert sender_from_description("") is None


class TestNativeParsing:
    def test_sabadell_xlsx_parses_natively_with_senders(self):
        from services.reconciliation_parser import parse_statement
        txs, errors, mode = _run(parse_statement(_build_xlsx(), "xlsx",
                                                 dayfirst=True))
        assert mode == "xlsx", f"debe parsear NATIVO, sin IA: {mode}"
        assert errors == 0
        assert len(txs) == 5, txs
        credits = [t for t in txs if t["direction"] == "credit"]
        debits = [t for t in txs if t["direction"] == "debit"]
        assert len(credits) == 4 and len(debits) == 1
        assert txs[0]["transaction_date"] == "2026-09-14"
        assert txs[0]["sender_name"] == "JUAN PEREZ GOMEZ", \
            "el remitente sale del concepto 'ABONO TRANSFERENCIA DE …'"
        assert txs[2]["sender_name"] == "MARIA LOPEZ DIAZ"
        assert debits[0]["amount"] == 18.0 and debits[0]["description"] == "COMISIONES"

    def test_sabadell_csv_with_metadata_preamble_parses_natively(self):
        from services.reconciliation_parser import parse_statement
        txs, errors, mode = _run(parse_statement(_build_csv(), "csv",
                                                 dayfirst=True))
        assert mode == "csv", f"cabecera tras 6+ filas de metadatos: {mode}"
        assert len(txs) == 5 and errors == 0


class TestEndToEndUpload:
    def teardown_method(self, _):
        db = _db()
        imps = [i["id"] for i in db.bank_statement_imports.find(
            {"bank_name": {"$regex": MARK}}, {"_id": 0, "id": 1})]
        db.bank_statement_imports.delete_many({"id": {"$in": imps}})
        db.bank_transactions.delete_many({"statement_import_id": {"$in": imps}})

    def test_upload_sabadell_style_xlsx_processes_all_rows(self):
        """E2E real: subir el extracto por la ruta de imports debe detectar
        las 5 filas sin pasar por la IA (antes: FALLÓ / 0 detectados)."""
        files = {"file": (f"sabadell_{uuid.uuid4().hex[:6]}.xlsx",
                          _build_xlsx(),
                          "application/vnd.openxmlformats-officedocument"
                          ".spreadsheetml.sheet")}
        data = {"bank_account_id": "",
                "bank_name": f"CUENTA SABADELL {MARK}", "currency": "EUR"}
        r = requests.post(f"{API}/admin/reconciliation/imports",
                          headers=_h(ADMIN), files=files, data=data)
        assert r.status_code == 200, r.text
        imp_id = r.json()["id"]
        deadline = time.time() + 30
        d = {}
        while time.time() < deadline:
            d = requests.get(f"{API}/admin/reconciliation/imports/{imp_id}",
                             headers=_h(ADMIN)).json()
            if d.get("processing_status") not in ("uploaded", "processing"):
                break
            time.sleep(1)
        assert d.get("processing_status") == "processed", d
        assert d.get("total_transactions_detected") == 5, d
        assert d.get("total_credits_detected") == 4, d
        assert d.get("total_debits_detected") == 1, d
        assert d.get("total_errors") == 0, d
        row = _db().bank_transactions.find_one(
            {"statement_import_id": imp_id, "amount": 4211.37}, {"_id": 0})
        assert row and row.get("sender_name") == "JUAN PEREZ GOMEZ", row
